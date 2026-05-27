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

from app.auth import get_current_recruiter, tenant_scope
from app.models.schemas import (
    EmailDraftResponse,
    EmailListResponse,
    EmailOutboxRow,
    EmailSendRequest,
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
from app.services import email as email_svc
from app.services.email_templates import default_shortlist_template
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
            company_id=tenant_scope(user),
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
        company_id=tenant_scope(user),
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
        supabase, str(candidate_id), scope=tenant_scope(ctx)
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
    return hiring_funnel(get_supabase(), company_id=tenant_scope(user))


@router.get("/analytics/scores", response_model=ScoresByFieldResponse)
async def analytics_scores(user=Depends(get_current_recruiter)):
    return scores_by_field(get_supabase(), company_id=tenant_scope(user))


@router.get("/analytics/integrity", response_model=IntegrityVolumeResponse)
async def analytics_integrity(user=Depends(get_current_recruiter)):
    return integrity_event_volume(get_supabase(), company_id=tenant_scope(user))


# ---------------------------------------------------------------------------
# Email composer (PR 7) — draft / send / list for the recruiter Shortlist
# outreach flow. The actual send + outbox writes live in services/email.py;
# this router is the auth + tenant gate + template lookup.
# ---------------------------------------------------------------------------

def _load_candidate_for_email(
    supabase, candidate_id: UUID, ctx
) -> dict:
    """Tenant-scoped candidate fetch for the email endpoints.

    Returns the candidate row (with email, name, company_id). Raises
    HTTPException(404) on missing or cross-tenant — same shape as
    `_resolve_candidate_tenant` but returns the FULL row so the
    composer can populate `to` and pass company_id into the template
    renderer. Centralised here so the three email endpoints share one
    auth/lookup path.
    """
    tenant = tenant_scope(ctx)
    q = (
        supabase.table("candidates")
        .select("id,name,email,company_id")
        .eq("id", str(candidate_id))
    )
    if tenant is not None:
        q = q.eq("company_id", tenant)
    rows = q.execute().data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return rows[0]


def _load_company_for_template(supabase, company_id) -> dict:
    """Look up the Company row for template substitution.

    Returns `{name: str}` shape — the templates only consume the name.
    Falls back to a generic dict if the company_id is somehow missing
    (B2C candidate viewed by platform admin); the template's own
    fallback handles the empty name gracefully.
    """
    if company_id is None:
        return {"name": ""}
    rows = (
        supabase.table("companies")
        .select("id,name")
        .eq("id", company_id)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else {"name": ""}


@router.get(
    "/candidates/{candidate_id}/email/draft",
    response_model=EmailDraftResponse,
)
async def email_draft(
    candidate_id: UUID,
    user=Depends(get_current_recruiter),
):
    """Return a template-rendered draft for the composer.

    Today only the shortlist template is wired up (the default for the
    "Send email" button). A future query param could pick a different
    template (`?template=rejection` etc.) — out of scope until the
    composer UI grows a template picker.
    """
    supabase = get_supabase()
    candidate = _load_candidate_for_email(supabase, candidate_id, user)
    company = _load_company_for_template(supabase, candidate.get("company_id"))

    rendered = default_shortlist_template(candidate, company)
    return EmailDraftResponse(
        to=candidate.get("email") or "",
        subject=rendered["subject"],
        body=rendered["body"],
    )


def _outbox_to_row(raw: dict) -> EmailOutboxRow:
    """Project an outbox dict into the schema-compatible response.

    Used by both the POST /send and GET /emails endpoints. Centralised
    so the column → field mapping lives in one place — schema changes
    on `email_outbox` only need updates here, not in two endpoints."""
    return EmailOutboxRow(
        id=raw["id"],
        to_email=raw["to_email"],
        subject=raw["subject"],
        body=raw["body"],
        status=raw["status"],
        resend_message_id=raw.get("resend_message_id"),
        error_message=raw.get("error_message"),
        sent_at=raw["sent_at"],
        sender_id=raw.get("sender_id"),
    )


@router.post(
    "/candidates/{candidate_id}/email/send",
    response_model=EmailOutboxRow,
)
async def email_send(
    candidate_id: UUID,
    body: EmailSendRequest,
    user=Depends(get_current_recruiter),
):
    """Send the (possibly recruiter-edited) email and record the
    outbox row.

    Failure semantics from `services/email.py::send`:
    - Resend failure → outbox row with `status='failed'`, returned to
      the caller. UI surfaces the failure but the row exists so the
      audit trail is intact (grill E4).
    - Disabled mode (no API key) → same shape, `error_message`
      indicates configuration is missing.
    - Persistence failure → 500 (EmailServiceError surfaced as a
      generic HTTPException).
    """
    supabase = get_supabase()
    candidate = _load_candidate_for_email(supabase, candidate_id, user)
    cand_company = candidate.get("company_id")

    # If the caller is tenant-scoped, the candidate MUST belong to a
    # tenant (tenant_scope check above already enforced this). For
    # platform admins viewing a B2C candidate (company_id NULL), refuse
    # to send — there's no tenant to stamp on the outbox row, and a
    # tenant-less audit row is meaningless.
    if cand_company is None:
        raise HTTPException(
            status_code=400,
            detail="Cannot send email to a candidate with no company affiliation",
        )

    try:
        row = await email_svc.send(
            supabase,
            company_id=cand_company,
            candidate_id=str(candidate_id),
            sender_id=user.id,
            to=body.to.strip(),
            subject=body.subject.strip(),
            body=body.body,
        )
    except email_svc.EmailServiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return _outbox_to_row(row)


@router.get(
    "/candidates/{candidate_id}/emails",
    response_model=EmailListResponse,
)
async def email_list(
    candidate_id: UUID,
    user=Depends(get_current_recruiter),
):
    """List prior outbox rows for the candidate, newest first.

    Tenant-scoped via the candidate lookup — a recruiter of A cannot
    list emails sent to a candidate of B (the candidate fetch 404s
    first). Inside the tenant, every recruiter sees every email
    (accountability through `sender_id`, not through hiding rows —
    matches the B1 access matrix for `recruiter_decisions`).
    """
    supabase = get_supabase()
    _load_candidate_for_email(supabase, candidate_id, user)
    rows = email_svc.list_for_candidate(
        supabase,
        str(candidate_id),
        company_id=tenant_scope(user),
    )
    return EmailListResponse(items=[_outbox_to_row(r) for r in rows])
