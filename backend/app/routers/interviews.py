"""REST endpoints for the interviews table.

The WebSocket handler (`routers/interview_session.py`) is the authoritative
runtime for an interview; these endpoints are CRUD/read helpers used by
the frontend's interview-room and dashboard screens.

Tenant note (updated 2026-06-12, invitation flow / migration 011): reads
are OWNERSHIP-scoped — a user sees exactly their own interviews. The old
additional `company_id == profile.company_id` narrowing is gone: a
candidate's interviews may legitimately span multiple companies (one
invitation per company), and the narrowing was also hiding every row the
pre-fix create path left with a NULL stamp. Writes now stamp `company_id`
at insert (see `create_interview`) — that stamp is what tenant-scopes the
RECRUITER/admin views, which still filter by it. Platform admins
(`role='admin'`, NULL `company_id`) can read any interview — used by the
admin user-detail page.

Pre-PR-2 audit: GET endpoints below were UNAUTHENTICATED (no `Depends`).
That gap is closed in PR 2 — every read now requires a Supabase Bearer
token and the caller must own the interview (or be a platform admin).
Two PATCH endpoints (`/phase`, `/complete`) remain unauthenticated AND
unused by the frontend; flagged as TODO at the bottom of the module.
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import List
from uuid import UUID

from app.models.schemas import (
    InterviewCreate,
    InterviewResponse,
    InterviewStateResponse,
    EvaluationResponse,
    SnapshotCreate,
    SnapshotListResponse,
    SnapshotRow,
)
from app.supabase_client import get_supabase
from app.auth import get_current_user, get_tenant_context
from app.routers.candidates import resolve_target_company
from app.services.invitations import mark_accepted

router = APIRouter()


def _require_owned_interview(supabase, interview_id: UUID, ctx) -> dict:
    """Fetch an interview the caller is allowed to read.

    Allowed = the caller owns it (`user_id` matches) OR the caller is a
    platform admin. Ownership is the gate — a candidate's interviews may
    span multiple companies (invitation flow, migration 011), so the old
    `company_id == profile.company_id` defense-in-depth check is gone:
    it 404'd a candidate's own company-B interview, and ownership already
    prevents any cross-user read.

    Returns the interview row. Raises HTTP 404 on any failure so the API
    never leaks the existence of interviews the caller cannot see.
    """
    rows = (
        supabase.table("interviews")
        .select("*")
        .eq("id", str(interview_id))
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Interview not found")
    interview = rows[0]

    if ctx.is_platform_admin:
        return interview

    if interview.get("user_id") != ctx.id:
        raise HTTPException(status_code=404, detail="Interview not found")
    return interview


@router.post("/", response_model=InterviewResponse)
async def create_interview(
    interview: InterviewCreate,
    user=Depends(get_current_user),
    ctx=Depends(get_tenant_context),
):
    supabase = get_supabase()

    # Resolve which company this interview is for. Explicit company_id
    # (invitation flow) is validated against the caller's memberships;
    # otherwise inherit the candidate row's company so the pair can't
    # drift apart; otherwise the caller's primary company. The stamp is
    # what the WebSocket tenant gate and every recruiter view key on —
    # leaving it NULL is the bug that produced "Cannot connect to
    # interview" for every tenant candidate.
    company_id = resolve_target_company(supabase, ctx, user, interview.company_id)
    if interview.company_id is None:
        cand_rows = (
            supabase.table("candidates")
            .select("company_id,user_id")
            .eq("id", str(interview.candidate_id))
            .execute()
            .data
            or []
        )
        if cand_rows and cand_rows[0].get("company_id"):
            company_id = cand_rows[0]["company_id"]

    result = supabase.table("interviews").insert({
        "candidate_id": str(interview.candidate_id),
        "job_description": interview.job_description,
        "status": "phase_1",
        "current_phase": 1,
        "conversation_history": [],
        "user_id": user.id,
        "company_id": company_id,
    }).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create interview")

    # Starting an interview for an inviting company accepts the invitation.
    if company_id and not ctx.is_platform_admin:
        mark_accepted(
            supabase,
            company_id=company_id,
            email=getattr(user, "email", "") or "",
            user_id=user.id,
        )

    return result.data[0]


@router.get("/", response_model=List[InterviewResponse])
async def list_interviews(user=Depends(get_tenant_context)):
    supabase = get_supabase()

    # Ownership-scoped only. The previous extra `company_id == profile
    # company` narrowing hid a candidate's own interviews whenever the two
    # stamps diverged (every un-stamped pre-fix row) and would hide all
    # second-company interviews in the multi-company invitation flow.
    result = (
        supabase.table("interviews")
        .select("*")
        .eq("user_id", user.id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


@router.get("/{interview_id}", response_model=InterviewResponse)
async def get_interview(interview_id: UUID, user=Depends(get_tenant_context)):
    supabase = get_supabase()
    return _require_owned_interview(supabase, interview_id, user)


@router.get("/{interview_id}/state", response_model=InterviewStateResponse)
async def get_interview_state(interview_id: UUID, user=Depends(get_tenant_context)):
    supabase = get_supabase()
    interview = _require_owned_interview(supabase, interview_id, user)

    last_message = None
    if interview["conversation_history"]:
        last_msg = interview["conversation_history"][-1]
        last_message = last_msg.get("content", "")[:100]

    eval_result = (
        supabase.table("evaluations")
        .select("*")
        .eq("interview_id", str(interview_id))
        .execute()
    )
    evaluation_progress = {}
    for eval_row in eval_result.data:
        evaluation_progress[f"phase_{eval_row['phase']}"] = eval_row.get("overall_score", 0)

    return InterviewStateResponse(
        interview_id=interview_id,
        phase=interview["current_phase"],
        status=interview["status"],
        last_message=last_message,
        evaluation_progress=evaluation_progress,
    )


@router.get("/{interview_id}/evaluations", response_model=List[EvaluationResponse])
async def get_interview_evaluations(interview_id: UUID, user=Depends(get_tenant_context)):
    supabase = get_supabase()
    # Ownership / tenant gate via the helper — the actual evaluations rows
    # are then transitively scoped (they belong to this interview only).
    _require_owned_interview(supabase, interview_id, user)
    result = (
        supabase.table("evaluations")
        .select("*")
        .eq("interview_id", str(interview_id))
        .order("phase")
        .execute()
    )
    return result.data


# ---------------------------------------------------------------------------
# Proctoring snapshots (migration 012)
# ---------------------------------------------------------------------------

@router.post("/{interview_id}/snapshots", status_code=201)
async def add_snapshot(
    interview_id: UUID,
    snapshot: SnapshotCreate,
    user=Depends(get_tenant_context),
):
    """Store one webcam snapshot for a live interview.

    Owner-only — the candidate's browser is the only writer; the tenant
    stamp is inherited from the interview so company reviewers can read
    it later. Best thought of as an audit append: the client fires and
    forgets (a lost frame must never disturb the interview turn flow),
    so the only hard failures are auth (404) and a missing table (503,
    migration 012 not applied yet).
    """
    supabase = get_supabase()
    interview = _require_owned_interview(supabase, interview_id, user)
    try:
        supabase.table("interview_snapshots").insert({
            "interview_id": str(interview_id),
            "user_id": user.id,
            "company_id": interview.get("company_id"),
            "kind": snapshot.kind,
            "image_base64": snapshot.image_base64,
        }).execute()
    except Exception as e:
        print(f"[snapshots] insert failed (migration 012 applied?): {e}")
        raise HTTPException(
            status_code=503,
            detail="Snapshot storage is not available.",
        )
    return {"stored": True}


@router.get("/{interview_id}/snapshots", response_model=SnapshotListResponse)
async def list_snapshots(interview_id: UUID, user=Depends(get_tenant_context)):
    """Proctoring snapshots for one interview, oldest first.

    Read access mirrors the report gate exactly (owner, hiring roles of
    the interview's tenant, platform admin) — snapshots are evidence
    attached to the report, so they must never be readable more widely
    than the report itself.
    """
    from app.routers.reports import _authorize_report_access

    _authorize_report_access(interview_id, user)
    supabase = get_supabase()
    try:
        rows = (
            supabase.table("interview_snapshots")
            .select("id,kind,created_at,image_base64")
            .eq("interview_id", str(interview_id))
            .order("created_at")
            .execute()
            .data
            or []
        )
    except Exception as e:
        # Missing table (migration 012 not applied) degrades to "no
        # snapshots" — the report page simply omits the section.
        print(f"[snapshots] list failed (migration 012 applied?): {e}")
        rows = []
    return SnapshotListResponse(items=[SnapshotRow(**r) for r in rows])


# ---------------------------------------------------------------------------
# TODO (multi-tenant PR 2 audit): The two PATCH endpoints below are
# UNAUTHENTICATED and UNUSED by the frontend (grep'd 2026-05-27). They
# predate auth on this router. Removing them is the right move but is out
# of PR 2's tenant-scoping scope; tracked as a hardening follow-up. If
# either becomes used, auth-gate + tenant-scope through `_require_owned_interview`.
# ---------------------------------------------------------------------------

@router.patch("/{interview_id}/phase")
async def update_interview_phase(interview_id: UUID, phase: int, status: str):
    supabase = get_supabase()

    result = supabase.table("interviews").update({
        "current_phase": phase,
        "status": status,
    }).eq("id", str(interview_id)).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Interview not found")

    return {"message": "Phase updated", "phase": phase, "status": status}


@router.patch("/{interview_id}/complete")
async def complete_interview(interview_id: UUID):
    supabase = get_supabase()

    result = supabase.table("interviews").update({
        "status": "completed",
        "completed_at": "now()",
    }).eq("id", str(interview_id)).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Interview not found")

    return {"message": "Interview completed"}
