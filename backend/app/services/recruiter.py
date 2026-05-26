"""Recruiter list / ranking service.

The hybrid wrapper from grill A1 (RECRUITER_ROLLOUT.md):
- SQL `where` for the non-score filters (search, field, signup-date range).
- One bulk score pass via the unchanged `score_interviews_bulk` (ADR 0001;
  CLAUDE.md pinned function).
- Python filter / sort / paginate for score, integrity, decision —
  signals that don't live as denormalised columns on `candidates`.

Scale ceiling: ~1000 candidates per query before the "fetch all then sort
in Python" pattern starts to feel sluggish. The follow-up trigger
(RECRUITER_ROLLOUT.md "After the rollout") is to materialise
`final_score` as a column with backfill; the entry points above stay
identical.

`formula_mixed` is computed from the page's interviews (not the full
candidate set), per grill F5: the advisory only matters for what the
Recruiter is actually looking at.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.interview_orchestrator import (
    recommendation_for,
    score_interviews_bulk,
)


# Terminal decisions stamp `decided_at`; reverting to 'undecided' clears it.
TERMINAL_DECISIONS = {"shortlisted", "rejected"}
WRITABLE_DECISIONS = {"shortlisted", "rejected", "undecided"}


VALID_SORTS = {
    "final_score",
    "created_at",
    "name",
    "decision",
    "integrity_warnings",
}
VALID_ORDERS = {"asc", "desc"}
VALID_INTEGRITY_FILTERS = {"any", "with_warnings", "without_warnings"}
VALID_DECISION_FILTERS = {"shortlisted", "rejected", "undecided", "bookmarked"}


# Score thresholds match recommendation_for() — kept in sync so a
# Recruiter filter pill and the rec-tier label never disagree.
_DECISION_RANK = {"shortlisted": 0, "undecided": 1, "rejected": 2}


@dataclass
class RankFilters:
    search: Optional[str] = None
    field: Optional[str] = None
    decision: Optional[str] = None
    min_score: Optional[float] = None
    max_score: Optional[float] = None
    integrity: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    sort: str = "final_score"
    order: str = "desc"
    page: int = 1
    page_size: int = 50

    def normalise(self) -> "RankFilters":
        """Coerce inputs into the canonical, validated shape.

        Validation belongs to the boundary; the router calls this once and
        then trusts the values downstream. Anything illegal raises ValueError
        and the router maps it to 400.
        """
        if self.sort not in VALID_SORTS:
            raise ValueError(f"invalid sort '{self.sort}'")
        if self.order not in VALID_ORDERS:
            raise ValueError(f"invalid order '{self.order}'")
        if self.integrity is not None and self.integrity not in VALID_INTEGRITY_FILTERS:
            raise ValueError(f"invalid integrity filter '{self.integrity}'")
        if self.decision is not None and self.decision not in VALID_DECISION_FILTERS:
            raise ValueError(f"invalid decision filter '{self.decision}'")
        self.page = max(1, int(self.page))
        # Clamp page_size to A3 grill resolution (max 100, default 50).
        self.page_size = max(1, min(100, int(self.page_size)))
        if self.search is not None:
            self.search = self.search.strip() or None
        if self.field is not None:
            self.field = self.field.strip() or None
        return self


def _apply_candidate_filters(query, filters: RankFilters):
    """SQL WHERE clauses safe to push down to PostgREST.

    Decision/score/integrity filters happen later in Python because they
    depend on derived data (recruiter_decisions row, scored interviews,
    integrity event count) not present on the candidates table.
    """
    if filters.field:
        query = query.eq("field_specialization", filters.field)
    if filters.date_from:
        query = query.gte("created_at", filters.date_from)
    if filters.date_to:
        query = query.lte("created_at", filters.date_to)
    if filters.search:
        # Multi-word AND-of-ORs per grill A2: every token must hit at
        # least one of (name, field_specialization, resume_text). ILIKE is
        # case-insensitive; pg_trgm + GIN is the documented upgrade path
        # if this ever feels slow.
        tokens = [t for t in filters.search.split() if t]
        for token in tokens:
            pattern = f"%{token}%"
            query = query.or_(
                f"name.ilike.{pattern},"
                f"field_specialization.ilike.{pattern},"
                f"resume_text.ilike.{pattern}"
            )
    return query


def _decision_matches(filter_value: Optional[str], decision_row: Dict[str, Any]) -> bool:
    if filter_value is None:
        return True
    if filter_value == "bookmarked":
        return bool(decision_row.get("bookmarked"))
    return decision_row.get("decision", "undecided") == filter_value


def _integrity_matches(filter_value: Optional[str], warnings: int) -> bool:
    if filter_value is None or filter_value == "any":
        return True
    if filter_value == "with_warnings":
        return warnings > 0
    return warnings == 0


def _sort_value(row: Dict[str, Any], sort_field: str):
    """The comparable value for the chosen sort field (no None sentinel)."""
    if sort_field == "final_score":
        return row["final_score"]
    if sort_field == "integrity_warnings":
        return row["integrity_warnings"]
    if sort_field == "name":
        return (row["name"] or "").lower()
    if sort_field == "decision":
        return _DECISION_RANK.get(row["decision"], 99)
    return row.get("created_at") or ""


def _sorted_with_missing_last(items, sort_field: str, reverse: bool):
    """Sort by sort_field; rows whose sort value is None always sit at
    the bottom — regardless of `reverse`.

    Recruiters get confused when a `desc created_at` sort puts "no
    timestamp yet" rows above real dates. Separating the partitions
    avoids the trick of trying to encode "missing last" inside a single
    sort key (which inverts under `reverse`).
    """
    present, missing = [], []
    for row in items:
        if sort_field == "created_at" and row.get("created_at") is None:
            missing.append(row)
        else:
            present.append(row)
    present.sort(key=lambda r: _sort_value(r, sort_field), reverse=reverse)
    return present + missing


def _layer_aware_map(supabase, interview_ids: List[str]) -> Dict[str, bool]:
    """Per-interview: did any evaluation row carry a Matryoshka `layer`?

    Mirrors the inline check inside `compute_phase_scores`. Pulled into a
    standalone bulk query here so the recruiter list can compute
    page-level `formula_mixed` without modifying the pinned scoring path.
    """
    if not interview_ids:
        return {}
    rows = (
        supabase.table("evaluations")
        .select("interview_id,details")
        .in_("interview_id", interview_ids)
        .execute()
        .data
        or []
    )
    is_layer_aware: Dict[str, bool] = {iid: False for iid in interview_ids}
    for row in rows:
        details = row.get("details")
        if isinstance(details, dict) and details.get("layer") is not None:
            is_layer_aware[row["interview_id"]] = True
    return is_layer_aware


def rank_candidates(supabase, recruiter_id: str, filters: RankFilters) -> Dict[str, Any]:
    """Return the paginated, filtered Candidate list for the recruiter UI.

    `recruiter_id` is the caller's `auth.users.id` — used to fetch
    THIS Recruiter's `recruiter_decisions` row for each Candidate (so the
    decision / bookmarked / notes columns reflect the caller's view per
    grill B1).
    """
    filters = filters.normalise()

    cand_query = supabase.table("candidates").select(
        "id,name,email,field_specialization,created_at,user_id"
    )
    cand_query = _apply_candidate_filters(cand_query, filters)
    candidates = cand_query.execute().data or []

    if not candidates:
        return {
            "items": [],
            "page": filters.page,
            "page_size": filters.page_size,
            "total_count": 0,
            "formula_mixed": False,
        }

    candidate_ids = [c["id"] for c in candidates]

    # Interviews for the filtered candidate set — one bulk query.
    interviews = (
        supabase.table("interviews")
        .select("id,candidate_id,status,created_at")
        .in_("candidate_id", candidate_ids)
        .execute()
        .data
        or []
    )
    interview_ids = [iv["id"] for iv in interviews]
    iv_scores = score_interviews_bulk(supabase, interview_ids)

    # Integrity counts — one bulk query, grouped in Python (mirrors the
    # admin endpoint pattern). Swallow if migration 002 isn't applied.
    integrity_counts: Dict[str, int] = {}
    if interview_ids:
        try:
            rows = (
                supabase.table("interview_integrity_events")
                .select("interview_id")
                .in_("interview_id", interview_ids)
                .execute()
                .data
                or []
            )
            for row in rows:
                iid = row.get("interview_id")
                if iid:
                    integrity_counts[iid] = integrity_counts.get(iid, 0) + 1
        except Exception:
            integrity_counts = {}

    # This Recruiter's existing decision rows — one query, scoped to the
    # candidate set.
    decision_rows = (
        supabase.table("recruiter_decisions")
        .select("candidate_id,decision,bookmarked,notes")
        .eq("recruiter_id", recruiter_id)
        .in_("candidate_id", candidate_ids)
        .execute()
        .data
        or []
    )
    decisions: Dict[str, Dict[str, Any]] = {
        row["candidate_id"]: row for row in decision_rows
    }

    # Group interviews per candidate so per-row aggregation is one pass.
    interviews_by_candidate: Dict[str, List[Dict[str, Any]]] = {}
    for iv in interviews:
        interviews_by_candidate.setdefault(iv["candidate_id"], []).append(iv)

    items: List[Dict[str, Any]] = []
    for cand in candidates:
        ivs = interviews_by_candidate.get(cand["id"], [])
        scored = [iv_scores.get(iv["id"], {"score": 0}) for iv in ivs]
        completed_scores = [
            s["score"]
            for iv, s in zip(ivs, scored)
            if iv.get("status") == "completed" and s["score"] > 0
        ]
        best_score = max(completed_scores) if completed_scores else 0.0
        latest = max((iv.get("created_at") for iv in ivs if iv.get("created_at")), default=None)
        warnings = sum(integrity_counts.get(iv["id"], 0) for iv in ivs)
        decision_row = decisions.get(cand["id"], {})

        # Apply derived-data filters here, after we have the numbers.
        if filters.min_score is not None and best_score < filters.min_score:
            continue
        if filters.max_score is not None and best_score > filters.max_score:
            continue
        if not _integrity_matches(filters.integrity, warnings):
            continue
        if not _decision_matches(filters.decision, decision_row):
            continue

        items.append({
            "candidate_id": cand["id"],
            "name": cand.get("name", "Candidate"),
            "email": cand.get("email"),
            "field_specialization": cand.get("field_specialization") or "general",
            "created_at": cand.get("created_at"),
            "interview_count": len(ivs),
            "completed_count": sum(1 for iv in ivs if iv.get("status") == "completed"),
            "final_score": best_score,
            "recommendation": recommendation_for(best_score) if best_score > 0 else "",
            "latest_interview_at": latest,
            "integrity_warnings": warnings,
            "decision": decision_row.get("decision", "undecided"),
            "bookmarked": bool(decision_row.get("bookmarked", False)),
            "notes": decision_row.get("notes", ""),
            # Held just long enough to compute formula_mixed on the
            # *page*. Only completed interviews contribute — the
            # displayed score is `best_score` over completed runs, so
            # the formula advisory must be over the same set. Stripped
            # from the response below.
            "_completed_interview_ids": [
                iv["id"] for iv in ivs if iv.get("status") == "completed"
            ],
        })

    total_count = len(items)

    reverse = filters.order == "desc"
    items = _sorted_with_missing_last(items, filters.sort, reverse=reverse)

    start = (filters.page - 1) * filters.page_size
    end = start + filters.page_size
    page_items = items[start:end]

    # formula_mixed — one extra bulk query across the page's completed
    # interviews only. Composes the pinned scoring function (no
    # modification). False unless we see both formulas on the page.
    page_interview_ids = [
        iid for row in page_items for iid in row["_completed_interview_ids"]
    ]
    layer_aware_by_iv = _layer_aware_map(supabase, page_interview_ids)
    has_layer_aware = any(layer_aware_by_iv.values())
    has_legacy = any(not v for v in layer_aware_by_iv.values()) if page_interview_ids else False
    formula_mixed = has_layer_aware and has_legacy

    for row in page_items:
        row.pop("_completed_interview_ids", None)

    return {
        "items": page_items,
        "page": filters.page,
        "page_size": filters.page_size,
        "total_count": total_count,
        "formula_mixed": formula_mixed,
    }


def get_candidate_detail(
    supabase, candidate_id: str, viewer_id: str, viewer_role: str
) -> Optional[Dict[str, Any]]:
    """Per-Candidate detail view for the Recruiter dashboard.

    Returns the candidate header, all interviews (scored + integrity counts
    via the same bulk path the list uses), every Decision row (with author
    attribution), the viewer's own Notes, and — only for Admins per B1 —
    every Recruiter's Notes (`all_notes`).

    Returns None if the candidate does not exist so the router can map to a
    clean 404 without leaking existence.

    The list endpoint shows one row per Candidate; here we surface the
    underlying data without re-deriving the displayed score. Recruiters
    open the detail page to *judge*, not to filter — so the rows below are
    intentionally rich rather than denormalised summaries.
    """
    cand_rows = (
        supabase.table("candidates")
        .select("id,name,email,field_specialization,created_at,resume_text")
        .eq("id", candidate_id)
        .execute()
        .data
        or []
    )
    if not cand_rows:
        return None
    candidate = cand_rows[0]

    interviews_raw = (
        supabase.table("interviews")
        .select("id,status,created_at,completed_at")
        .eq("candidate_id", candidate_id)
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )
    interview_ids = [iv["id"] for iv in interviews_raw]
    iv_scores = score_interviews_bulk(supabase, interview_ids)

    integrity_counts: Dict[str, int] = {}
    if interview_ids:
        try:
            rows = (
                supabase.table("interview_integrity_events")
                .select("interview_id")
                .in_("interview_id", interview_ids)
                .execute()
                .data
                or []
            )
            for row in rows:
                iid = row.get("interview_id")
                if iid:
                    integrity_counts[iid] = integrity_counts.get(iid, 0) + 1
        except Exception:
            integrity_counts = {}

    interviews: List[Dict[str, Any]] = []
    for iv in interviews_raw:
        scored = iv_scores.get(iv["id"], {"score": 0, "questions": 0})
        completed = iv.get("status") == "completed"
        interviews.append({
            "interview_id": iv["id"],
            "status": iv.get("status", ""),
            "completed": completed,
            "created_at": iv.get("created_at"),
            "completed_at": iv.get("completed_at"),
            "score": scored["score"],
            "questions": scored["questions"],
            "recommendation": recommendation_for(scored["score"]) if completed else "",
            "integrity_warnings": integrity_counts.get(iv["id"], 0),
            "integrity_terminated": iv.get("status") == "terminated_integrity",
        })

    # All Decisions on this Candidate, with author attribution. Both
    # Admins and Recruiters can read this list per B1 — accountability
    # depends on the recruiter_id stamp, never anonymised.
    decision_rows = (
        supabase.table("recruiter_decisions")
        .select("recruiter_id,decision,bookmarked,notes,decided_at,updated_at")
        .eq("candidate_id", candidate_id)
        .execute()
        .data
        or []
    )

    # Resolve author names in one bulk profiles query.
    recruiter_ids = list({row["recruiter_id"] for row in decision_rows})
    authors: Dict[str, Dict[str, Any]] = {}
    if recruiter_ids:
        profile_rows = (
            supabase.table("profiles")
            .select("id,full_name,email")
            .in_("id", recruiter_ids)
            .execute()
            .data
            or []
        )
        authors = {p["id"]: p for p in profile_rows}

    decisions: List[Dict[str, Any]] = []
    my_notes = ""
    all_notes: List[Dict[str, Any]] = []
    for row in decision_rows:
        recruiter_id = row["recruiter_id"]
        author = authors.get(recruiter_id, {})
        decisions.append({
            "recruiter_id": recruiter_id,
            "recruiter_name": author.get("full_name") or author.get("email") or "Recruiter",
            "decision": row.get("decision", "undecided"),
            "bookmarked": bool(row.get("bookmarked", False)),
            "decided_at": row.get("decided_at"),
            "updated_at": row.get("updated_at"),
            "is_you": recruiter_id == viewer_id,
        })
        if recruiter_id == viewer_id:
            my_notes = row.get("notes", "") or ""
        if viewer_role == "admin":
            all_notes.append({
                "recruiter_id": recruiter_id,
                "recruiter_name": author.get("full_name") or author.get("email") or "Recruiter",
                "notes": row.get("notes", "") or "",
                "updated_at": row.get("updated_at"),
            })

    return {
        "candidate": {
            "id": candidate["id"],
            "name": candidate.get("name", "Candidate"),
            "email": candidate.get("email"),
            "field_specialization": candidate.get("field_specialization"),
            "created_at": candidate.get("created_at"),
            # Resume text intentionally truncated — the detail view shows a
            # preview, not the full document. Recruiters who need the full
            # text can request the interview report.
            "resume_excerpt": (candidate.get("resume_text") or "")[:1500] or None,
        },
        "interviews": interviews,
        "decisions": decisions,
        "my_notes": my_notes,
        # Only present for admins per B1. None (not []) so the frontend can
        # detect role without checking the viewer's profile separately.
        "all_notes": all_notes if viewer_role == "admin" else None,
    }


def candidate_exists(supabase, candidate_id: str) -> bool:
    """Used by the write endpoints to surface a clean 404 rather than a
    raw Postgres FK violation when a stale candidate id slips through.
    """
    rows = (
        supabase.table("candidates")
        .select("id")
        .eq("id", candidate_id)
        .execute()
        .data
        or []
    )
    return bool(rows)


def upsert_recruiter_decision(
    supabase,
    candidate_id: str,
    recruiter_id: str,
    *,
    decision: Optional[str] = None,
    bookmarked: Optional[bool] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Partial-update the (candidate_id, recruiter_id) workflow row.

    Three independent write endpoints (decision / bookmark / notes) all
    funnel here so the upsert semantics live in one place:

    - Each named field is updated only when its argument is non-None;
      `setBookmark` cannot accidentally clear Notes, and so on.
    - Setting `decision` to a terminal value stamps `decided_at = now`.
      Reverting to `undecided` clears `decided_at` so the funnel
      analytics in PR 6 do not double-count a Candidate who was
      shortlisted then un-shortlisted.
    - On insert, every column gets a sensible default — same shape the
      migration's DEFAULTs would produce, but stamped here so the
      service is testable without round-tripping to a real DB.

    Returns the upserted row as it now sits.
    """
    if decision is not None and decision not in WRITABLE_DECISIONS:
        raise ValueError(f"invalid decision '{decision}'")

    now_iso = datetime.now(timezone.utc).isoformat()

    existing = (
        supabase.table("recruiter_decisions")
        .select("*")
        .eq("candidate_id", candidate_id)
        .eq("recruiter_id", recruiter_id)
        .execute()
        .data
        or []
    )

    if existing:
        update_payload: Dict[str, Any] = {"updated_at": now_iso}
        if decision is not None:
            update_payload["decision"] = decision
            update_payload["decided_at"] = (
                now_iso if decision in TERMINAL_DECISIONS else None
            )
        if bookmarked is not None:
            update_payload["bookmarked"] = bookmarked
        if notes is not None:
            update_payload["notes"] = notes

        result = (
            supabase.table("recruiter_decisions")
            .update(update_payload)
            .eq("id", existing[0]["id"])
            .execute()
        )
        rows = result.data or []
        # Some Supabase configurations return [] from .update() — fall
        # back to merging the payload onto the prior row so the API
        # response stays consistent regardless.
        return rows[0] if rows else {**existing[0], **update_payload}

    insert_payload: Dict[str, Any] = {
        "candidate_id": candidate_id,
        "recruiter_id": recruiter_id,
        "decision": decision or "undecided",
        "bookmarked": bool(bookmarked) if bookmarked is not None else False,
        "notes": notes if notes is not None else "",
    }
    if decision in TERMINAL_DECISIONS:
        insert_payload["decided_at"] = now_iso

    result = (
        supabase.table("recruiter_decisions")
        .insert(insert_payload)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else insert_payload
