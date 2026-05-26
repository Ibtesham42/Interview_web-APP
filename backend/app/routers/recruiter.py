"""Recruiter API.

Read-only in this PR: a single paginated list endpoint backing the
Recruiter dashboard. Write endpoints (Shortlist / Reject / Bookmark /
Notes) come in PR 4 per RECRUITER_ROLLOUT.md.

Auth posture: gated by `get_current_recruiter`. Admins inherit Recruiter
capabilities additively (B1 access matrix).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_current_recruiter
from app.models.schemas import RecruiterCandidateListResponse
from app.services.recruiter import RankFilters, rank_candidates
from app.supabase_client import get_supabase

router = APIRouter()


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
        return rank_candidates(get_supabase(), user.id, filters)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
