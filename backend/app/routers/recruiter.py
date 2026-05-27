"""Recruiter API.

List endpoint + workflow write endpoints (Shortlist / Reject /
Bookmark / Notes). All routes gated by `get_current_recruiter` —
Admins inherit Recruiter capabilities additively (B1 access matrix).

Per the F3 grill resolution, each Recruiter owns exactly one
`recruiter_decisions` row per Candidate (UNIQUE constraint at the
DB layer). The three workflow fields (decision / bookmarked / notes)
share that row and are partial-updated through the same
`upsert_recruiter_decision` service so a Bookmark toggle never blows
away a Note, and vice versa.
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_current_recruiter
from app.models.schemas import (
    HiringFunnelResponse,
    IntegrityVolumeResponse,
    RecruiterBookmarkUpdate,
    RecruiterCandidateDetailResponse,
    RecruiterCandidateListResponse,
    RecruiterDecisionRow,
    RecruiterDecisionUpdate,
    RecruiterNotesUpdate,
    ScoresByFieldResponse,
)
from app.services.recruiter import (
    RankFilters,
    candidate_tenant,
    get_candidate_detail,
    rank_candidates,
    upsert_recruiter_decision,
)
from app.services.recruiter_analytics import (
    hiring_funnel,
    integrity_event_volume,
    scores_by_field,
)
from app.supabase_client import get_supabase

router = APIRouter()


def _tenant_scope(ctx):
    """Translate a TenantContext into the `company_id` filter to apply.

    Returns `None` for platform admins (grill C3 — they see across all
    tenants) and the caller's `company_id` otherwise. Centralised here so
    every endpoint reads the same translation; if PR 3 introduces a new
    role that should bypass tenant scoping, this is the single line to
    update.
    """
    if ctx.is_platform_admin:
        return None
    return ctx.company_id


@router.get("/candidates", response_model=RecruiterCandidateListResponse)
async def list_candidates(
    user=Depends(get_current_recruiter),
    search: Optional[str] = Query(None, description="Multi-word AND across name / field / resume_text"),
    field: Optional[str] = Query(None, description="Exact match on field_specialization"),
    decision: Optional[str] = Query(
        None,
        description="One of: shortlisted, rejected, undecided, bookmarked",
    ),
    min_score: Optional[float] = Query(None, ge=0, le=10),
    max_score: Optional[float] = Query(None, ge=0, le=10),
    integrity: Optional[str] = Query(
        None,
        description="One of: any, with_warnings, without_warnings",
    ),
    date_from: Optional[str] = Query(None, description="ISO timestamp lower bound on candidate created_at"),
    date_to: Optional[str] = Query(None, description="ISO timestamp upper bound on candidate created_at"),
    sort: str = Query("final_score"),
    order: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    """List candidates ranked + filtered for the recruiter dashboard.

    See `services.recruiter.rank_candidates` for the hybrid SQL + Python
    composition and the formula_mixed semantics.
    """
    try:
        filters = RankFilters(
            search=search,
            field=field,
            decision=decision,
            min_score=min_score,
            max_score=max_score,
            integrity=integrity,
            date_from=date_from,
            date_to=date_to,
            sort=sort,
            order=order,
            page=page,
            page_size=page_size,
        )
        return rank_candidates(
            get_supabase(),
            user.id,
            filters,
            company_id=_tenant_scope(user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get(
    "/candidates/{candidate_id}",
    response_model=RecruiterCandidateDetailResponse,
)
async def get_candidate(candidate_id: UUID, user=Depends(get_current_recruiter)):
    """Per-Candidate detail view. The B1 access matrix is enforced here:
    Recruiters get only `my_notes`; Admins additionally get `all_notes`
    with author attribution. Both see every Recruiter's Decision row
    (accountability is preserved by attribution, not by hiding rows)."""
    supabase = get_supabase()
    detail = get_candidate_detail(
        supabase,
        str(candidate_id),
        user.id,
        user.role,
        company_id=_tenant_scope(user),
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return detail


def _resolve_candidate_tenant(supabase, candidate_id: UUID, ctx) -> Optional[str]:
    """Verify the candidate exists AND (if caller is tenant-scoped) belongs
    to the caller's tenant. Returns the candidate's own `company_id` to
    stamp the new workflow row with — `None` for B2C candidates seen by a
    platform admin.

    Raises 404 on both 'missing' and 'cross-tenant' so the API never leaks
    whether the candidate exists in another tenant.
    """
    exists, cand_company_id = candidate_tenant(
        supabase, str(candidate_id), scope=_tenant_scope(ctx)
    )
    if not exists:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return cand_company_id


def _to_row(row: dict, candidate_id: UUID) -> RecruiterDecisionRow:
    return RecruiterDecisionRow(
        candidate_id=candidate_id,
        decision=row.get("decision", "undecided"),
        bookmarked=bool(row.get("bookmarked", False)),
        notes=row.get("notes", "") or "",
        decided_at=row.get("decided_at"),
        updated_at=row.get("updated_at"),
    )


@router.put(
    "/candidates/{candidate_id}/decision",
    response_model=RecruiterDecisionRow,
)
async def set_decision(
    candidate_id: UUID,
    body: RecruiterDecisionUpdate,
    user=Depends(get_current_recruiter),
):
    supabase = get_supabase()
    cand_company = _resolve_candidate_tenant(supabase, candidate_id, user)
    try:
        row = upsert_recruiter_decision(
            supabase,
            str(candidate_id),
            user.id,
            decision=body.decision,
            company_id=cand_company,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _to_row(row, candidate_id)


@router.put(
    "/candidates/{candidate_id}/bookmark",
    response_model=RecruiterDecisionRow,
)
async def set_bookmark(
    candidate_id: UUID,
    body: RecruiterBookmarkUpdate,
    user=Depends(get_current_recruiter),
):
    supabase = get_supabase()
    cand_company = _resolve_candidate_tenant(supabase, candidate_id, user)
    row = upsert_recruiter_decision(
        supabase,
        str(candidate_id),
        user.id,
        bookmarked=body.bookmarked,
        company_id=cand_company,
    )
    return _to_row(row, candidate_id)


@router.put(
    "/candidates/{candidate_id}/notes",
    response_model=RecruiterDecisionRow,
)
async def set_notes(
    candidate_id: UUID,
    body: RecruiterNotesUpdate,
    user=Depends(get_current_recruiter),
):
    supabase = get_supabase()
    cand_company = _resolve_candidate_tenant(supabase, candidate_id, user)
    row = upsert_recruiter_decision(
        supabase,
        str(candidate_id),
        user.id,
        notes=body.notes,
        company_id=cand_company,
    )
    return _to_row(row, candidate_id)


# ---------------------------------------------------------------------------
# Analytics (PR 6) — funnel + scores + integrity volume. All bulk-query
# aggregations; see services/recruiter_analytics.py.
# ---------------------------------------------------------------------------

@router.get("/analytics/funnel", response_model=HiringFunnelResponse)
async def analytics_funnel(user=Depends(get_current_recruiter)):
    return hiring_funnel(get_supabase(), company_id=_tenant_scope(user))


@router.get("/analytics/scores", response_model=ScoresByFieldResponse)
async def analytics_scores(user=Depends(get_current_recruiter)):
    return scores_by_field(get_supabase(), company_id=_tenant_scope(user))


@router.get("/analytics/integrity", response_model=IntegrityVolumeResponse)
async def analytics_integrity(user=Depends(get_current_recruiter)):
    return integrity_event_volume(get_supabase(), company_id=_tenant_scope(user))
