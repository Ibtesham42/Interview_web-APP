"""Recruiter analytics aggregations (PR 6 of the recruiter rollout).

Three bulk-query aggregations powering the analytics screen:
- `hiring_funnel` — the 4-stage Hiring Funnel per ADR 0004: Signed up
  → Started → Completed → Shortlisted. With per-stage counts,
  conversion rates between adjacent stages, and the same funnel
  broken down per field_specialization.
- `scores_by_field` — average best-completed score per field, using
  the pinned `score_interviews_bulk` (no modification).
- `integrity_event_volume` — counts of integrity events broken down
  by event_type, sorted by volume descending.

All three follow the bulk-query invariant (PROJECT_STATE #5; CLAUDE.md
backend rule) — N table rows resolve to a fixed number of SELECTs,
never N+1.

"Hired" is intentionally not modelled (ADR 0004): the platform doesn't
observe hire/offer/start events, so the funnel terminates at
Shortlisted. ATS integration is a deferred trigger, not in-scope work.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.interview_orchestrator import score_interviews_bulk


# Stable stage order — used by the response and the conversion-rate
# pairing. Don't reorder: the frontend renders left-to-right by this.
FUNNEL_STAGES = ["signed_up", "interview_started", "interview_completed", "shortlisted"]

# Default field bucket when a candidate has no field_specialization set.
_UNCLASSIFIED_FIELD = "general"


def _conversion_rate(numerator: int, denominator: int) -> float:
    """Percent (0-100), rounded to 1dp. 0 when the denominator is 0
    (rather than NaN / divide-by-zero) so the JSON never carries a
    non-numeric value to the chart."""
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100, 1)


def _conversion_rates(counts: Dict[str, int]) -> Dict[str, float]:
    return {
        "signed_up_to_started": _conversion_rate(
            counts["interview_started"], counts["signed_up"]
        ),
        "started_to_completed": _conversion_rate(
            counts["interview_completed"], counts["interview_started"]
        ),
        "completed_to_shortlisted": _conversion_rate(
            counts["shortlisted"], counts["interview_completed"]
        ),
    }


def hiring_funnel(supabase, company_id: Optional[str] = None) -> Dict[str, Any]:
    """Bulk-aggregate the 4-stage funnel.

    Four SELECTs total (candidates, interviews, completed-interviews,
    shortlisted-decisions) — that's `O(stages)` queries, not
    `O(candidates)`.

    `company_id` (multi-tenant PR 1): when non-None, every SELECT filters
    by it so a tenant-scoped recruiter sees only their company's funnel.
    `None` = no scope (platform admin / tests).
    """
    cand_q = supabase.table("candidates").select("id,field_specialization")
    iv_q = supabase.table("interviews").select("candidate_id,status")
    dec_q = (
        supabase.table("recruiter_decisions")
        .select("candidate_id,decision")
        .eq("decision", "shortlisted")
    )
    if company_id is not None:
        cand_q = cand_q.eq("company_id", company_id)
        iv_q = iv_q.eq("company_id", company_id)
        dec_q = dec_q.eq("company_id", company_id)
    candidates = cand_q.execute().data or []
    interviews = iv_q.execute().data or []
    decisions = dec_q.execute().data or []

    field_of: Dict[str, str] = {
        c["id"]: (c.get("field_specialization") or _UNCLASSIFIED_FIELD)
        for c in candidates
    }
    all_candidate_ids = set(field_of.keys())

    started_ids: set = set()
    completed_ids: set = set()
    for iv in interviews:
        cid = iv.get("candidate_id")
        if cid in field_of:
            started_ids.add(cid)
            if iv.get("status") == "completed":
                completed_ids.add(cid)

    # A Candidate is "shortlisted" if ANY Recruiter shortlisted them. Per
    # B1, decisions are per-(Candidate, Recruiter); the funnel collapses
    # across recruiters by design — a Candidate moves to Shortlisted on
    # the first yes.
    shortlisted_ids: set = {
        d["candidate_id"] for d in decisions
        if d.get("candidate_id") in field_of
    }

    overall_counts = {
        "signed_up": len(all_candidate_ids),
        "interview_started": len(started_ids),
        "interview_completed": len(completed_ids),
        "shortlisted": len(shortlisted_ids),
    }

    stages = [{"stage": s, "count": overall_counts[s]} for s in FUNNEL_STAGES]

    # By-field breakdown — same arithmetic, partitioned by field.
    fields = sorted({field_of[cid] for cid in all_candidate_ids})
    by_field: Dict[str, Any] = {}
    for field in fields:
        field_candidates = {cid for cid in all_candidate_ids if field_of[cid] == field}
        counts = {
            "signed_up": len(field_candidates),
            "interview_started": len(started_ids & field_candidates),
            "interview_completed": len(completed_ids & field_candidates),
            "shortlisted": len(shortlisted_ids & field_candidates),
        }
        by_field[field] = {
            "stages": [{"stage": s, "count": counts[s]} for s in FUNNEL_STAGES],
            "conversion_rates": _conversion_rates(counts),
        }

    return {
        "stages": stages,
        "conversion_rates": _conversion_rates(overall_counts),
        "by_field": by_field,
    }


def scores_by_field(supabase, company_id: Optional[str] = None) -> Dict[str, Any]:
    """Average best-completed score per field.

    'Best-completed' matches the dashboard rule: per Candidate, take the
    max final_score across their completed interviews; then average
    those per field. This keeps the analytics chart consistent with what
    the Recruiter sees on the list.

    `company_id` (multi-tenant PR 1): when non-None, candidate + interview
    queries filter by it. `None` = no scope.
    """
    cand_q = supabase.table("candidates").select("id,field_specialization")
    if company_id is not None:
        cand_q = cand_q.eq("company_id", company_id)
    candidates = cand_q.execute().data or []
    if not candidates:
        return {"items": []}

    field_of: Dict[str, str] = {
        c["id"]: (c.get("field_specialization") or _UNCLASSIFIED_FIELD)
        for c in candidates
    }

    iv_q = supabase.table("interviews").select("id,candidate_id,status")
    if company_id is not None:
        iv_q = iv_q.eq("company_id", company_id)
    interviews = iv_q.execute().data or []
    interview_ids = [iv["id"] for iv in interviews]
    iv_scores = score_interviews_bulk(supabase, interview_ids)

    # Per-candidate best completed score (matches RecruiterCandidate.final_score).
    best_by_candidate: Dict[str, float] = {}
    for iv in interviews:
        if iv.get("status") != "completed":
            continue
        score = iv_scores.get(iv["id"], {}).get("score", 0)
        if score <= 0:
            continue
        cid = iv["candidate_id"]
        prev = best_by_candidate.get(cid, 0.0)
        if score > prev:
            best_by_candidate[cid] = score

    by_field: Dict[str, List[float]] = {}
    for cid, score in best_by_candidate.items():
        field = field_of.get(cid, _UNCLASSIFIED_FIELD)
        by_field.setdefault(field, []).append(score)

    items = [
        {
            "field": field,
            "candidate_count": len(scores),
            "average_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
        }
        for field, scores in by_field.items()
    ]
    items.sort(key=lambda row: row["average_score"], reverse=True)
    return {"items": items}


def integrity_event_volume(supabase, company_id: Optional[str] = None) -> Dict[str, Any]:
    """Counts of integrity events broken down by event_type, sorted by
    volume desc. Swallows a missing table cleanly so the analytics
    screen still renders when migration 002 hasn't been applied.

    `company_id` (multi-tenant PR 1): when non-None, the query filters by
    it. `None` = no scope (platform admin / tests).
    """
    try:
        q = supabase.table("interview_integrity_events").select("event_type")
        if company_id is not None:
            q = q.eq("company_id", company_id)
        rows = q.execute().data or []
    except Exception:
        return {"items": [], "total": 0}

    counts: Dict[str, int] = {}
    for row in rows:
        event_type = row.get("event_type") or "unknown"
        counts[event_type] = counts.get(event_type, 0) + 1

    items = [
        {"event_type": event_type, "count": count}
        for event_type, count in counts.items()
    ]
    items.sort(key=lambda r: r["count"], reverse=True)
    return {"items": items, "total": sum(counts.values())}


# Effective company-level status precedence (mirrors the frontend
# deriveStatus / ADR 0011): a candidate sits in exactly one bucket — the
# strongest decision any recruiter made, else their funnel position.
def _effective_status(decisions: set, has_completed: bool) -> str:
    if "shortlisted" in decisions:
        return "shortlisted"
    if "rejected" in decisions:
        return "rejected"
    if "hold" in decisions:
        return "on_hold"
    return "interview_completed" if has_completed else "invited"


def candidate_analytics_summary(
    supabase,
    company_id: Optional[str] = None,
    *,
    name: Optional[str] = None,
    email: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    recent_limit: int = 20,
) -> Dict[str, Any]:
    """Recruiter/company analytics summary.

    KPI totals are company all-time (tenant-scoped) — the standard
    dashboard snapshot. The filters (name / email / status / interview
    date range) scope ONLY the `recent_activity` table, so filtering can
    never produce nonsensical aggregate rates.

    `company_id` mirrors the other aggregations: non-None tenant-scopes
    every SELECT; None = no scope (platform admin → cross-company).

    Bulk-query invariant holds: a fixed set of SELECTs (candidates,
    interviews, decisions, invite outbox, bulk scores), never N+1.
    """
    cand_q = supabase.table("candidates").select("id,name,email,created_at")
    iv_q = supabase.table("interviews").select("id,candidate_id,status,created_at")
    dec_q = supabase.table("recruiter_decisions").select("candidate_id,decision")
    if company_id is not None:
        cand_q = cand_q.eq("company_id", company_id)
        iv_q = iv_q.eq("company_id", company_id)
        dec_q = dec_q.eq("company_id", company_id)
    candidates = cand_q.execute().data or []
    interviews = iv_q.execute().data or []
    decisions = dec_q.execute().data or []

    # Invites live in email_outbox with candidate_id IS NULL (sent before
    # the candidate signs up). Swallow a missing table so the screen still
    # renders pre-migration-006.
    invited = 0
    try:
        out_q = supabase.table("email_outbox").select("to_email,candidate_id")
        if company_id is not None:
            out_q = out_q.eq("company_id", company_id)
        outbox = out_q.execute().data or []
        invited = len({
            o.get("to_email") for o in outbox
            if o.get("candidate_id") is None and o.get("to_email")
        })
    except Exception:
        invited = 0

    # Decision set + completion per candidate (over ALL tenant candidates).
    decisions_by_cand: Dict[str, set] = {}
    for d in decisions:
        cid = d.get("candidate_id")
        if cid:
            decisions_by_cand.setdefault(cid, set()).add(d.get("decision"))

    completed_ids: set = {
        iv["candidate_id"] for iv in interviews
        if iv.get("status") == "completed" and iv.get("candidate_id")
    }
    interviews_completed = sum(
        1 for iv in interviews if iv.get("status") == "completed"
    )

    status_of: Dict[str, str] = {
        c["id"]: _effective_status(
            decisions_by_cand.get(c["id"], set()), c["id"] in completed_ids
        )
        for c in candidates
    }

    registrations = len(candidates)
    completed_candidates = len(completed_ids)
    shortlisted = sum(1 for s in status_of.values() if s == "shortlisted")
    rejected = sum(1 for s in status_of.values() if s == "rejected")
    on_hold = sum(1 for s in status_of.values() if s == "on_hold")

    totals = {
        "invited": invited,
        "registrations": registrations,
        "interviews_completed": interviews_completed,
        "shortlisted": shortlisted,
        "rejected": rejected,
        "on_hold": on_hold,
        # completion = registered candidates who finished ≥1 interview.
        "completion_rate": _conversion_rate(completed_candidates, registrations),
        # shortlist = of those who completed, how many got shortlisted.
        "shortlist_rate": _conversion_rate(shortlisted, completed_candidates),
    }

    # --- Recent activity (filtered) ---
    latest_iv: Dict[str, Optional[str]] = {}
    interviews_in_range_by_cand: Dict[str, bool] = {}
    for iv in interviews:
        cid = iv.get("candidate_id")
        if not cid:
            continue
        ts = iv.get("created_at")
        if ts and (latest_iv.get(cid) is None or ts > latest_iv[cid]):
            latest_iv[cid] = ts
        if _within(ts, date_from, date_to):
            interviews_in_range_by_cand[cid] = True

    iv_scores = score_interviews_bulk(supabase, [iv["id"] for iv in interviews])
    best_score: Dict[str, float] = {}
    for iv in interviews:
        if iv.get("status") != "completed":
            continue
        score = iv_scores.get(iv["id"], {}).get("score", 0)
        cid = iv["candidate_id"]
        if score > best_score.get(cid, 0):
            best_score[cid] = score

    name_l = (name or "").strip().lower()
    email_l = (email or "").strip().lower()
    date_active = bool(date_from or date_to)

    rows: List[Dict[str, Any]] = []
    for c in candidates:
        cid = c["id"]
        if name_l and name_l not in (c.get("name") or "").lower():
            continue
        if email_l and email_l not in (c.get("email") or "").lower():
            continue
        if status and status_of.get(cid) != status:
            continue
        if date_active and not interviews_in_range_by_cand.get(cid):
            continue
        rows.append({
            "candidate_id": cid,
            "name": c.get("name") or "",
            "email": c.get("email"),
            "status": status_of.get(cid, "invited"),
            "last_interview_at": latest_iv.get(cid),
            "best_score": round(best_score.get(cid, 0.0), 1),
        })

    # Most recent activity first; candidates with no interview sort last.
    rows.sort(key=lambda r: r["last_interview_at"] or "", reverse=True)

    return {
        "totals": totals,
        "recent_activity": rows[:recent_limit],
        "recent_total": len(rows),
    }


def _within(ts: Optional[str], date_from: Optional[str], date_to: Optional[str]) -> bool:
    """ISO-timestamp range check (lexicographic — safe for ISO-8601).
    A missing timestamp is never in range."""
    if ts is None:
        return False
    if date_from and ts < date_from:
        return False
    if date_to and ts > date_to:
        return False
    return True
