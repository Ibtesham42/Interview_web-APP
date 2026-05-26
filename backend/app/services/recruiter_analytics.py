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

from typing import Any, Dict, List

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


def hiring_funnel(supabase) -> Dict[str, Any]:
    """Bulk-aggregate the 4-stage funnel.

    Four SELECTs total (candidates, interviews, completed-interviews,
    shortlisted-decisions) — that's `O(stages)` queries, not
    `O(candidates)`.
    """
    candidates = (
        supabase.table("candidates")
        .select("id,field_specialization")
        .execute()
        .data
        or []
    )
    interviews = (
        supabase.table("interviews")
        .select("candidate_id,status")
        .execute()
        .data
        or []
    )
    decisions = (
        supabase.table("recruiter_decisions")
        .select("candidate_id,decision")
        .eq("decision", "shortlisted")
        .execute()
        .data
        or []
    )

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


def scores_by_field(supabase) -> Dict[str, Any]:
    """Average best-completed score per field.

    'Best-completed' matches the dashboard rule: per Candidate, take the
    max final_score across their completed interviews; then average
    those per field. This keeps the analytics chart consistent with what
    the Recruiter sees on the list.
    """
    candidates = (
        supabase.table("candidates")
        .select("id,field_specialization")
        .execute()
        .data
        or []
    )
    if not candidates:
        return {"items": []}

    field_of: Dict[str, str] = {
        c["id"]: (c.get("field_specialization") or _UNCLASSIFIED_FIELD)
        for c in candidates
    }

    interviews = (
        supabase.table("interviews")
        .select("id,candidate_id,status")
        .execute()
        .data
        or []
    )
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


def integrity_event_volume(supabase) -> Dict[str, Any]:
    """Counts of integrity events broken down by event_type, sorted by
    volume desc. Swallows a missing table cleanly so the analytics
    screen still renders when migration 002 hasn't been applied."""
    try:
        rows = (
            supabase.table("interview_integrity_events")
            .select("event_type")
            .execute()
            .data
            or []
        )
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
