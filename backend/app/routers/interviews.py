"""REST endpoints for the interviews table.

The WebSocket handler (`routers/interview_session.py`) is the authoritative
runtime for an interview; these endpoints are CRUD/read helpers used by
the frontend's interview-room and dashboard screens.

Tenant note (multi-tenant PR 2): every read enforces ownership AND tenant
scope. Ownership is the primary gate (a user only sees their own
interviews); the tenant filter is defense-in-depth so a stale or
manually-edited `company_id` cannot leak data across tenants. Platform
admins (`role='admin'`, NULL `company_id`) bypass both checks and can
read any interview — used by the admin user-detail page.

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
)
from app.supabase_client import get_supabase
from app.auth import get_current_user, get_tenant_context, tenant_scope

router = APIRouter()


def _require_owned_interview(supabase, interview_id: UUID, ctx) -> dict:
    """Fetch an interview the caller is allowed to read.

    Allowed = the caller owns it (`user_id` matches) OR the caller is a
    platform admin. If the caller is tenant-scoped, the interview's
    `company_id` must also match — a cross-tenant id falls through to 404,
    indistinguishable from 'missing'.

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

    # Non-admin: must own + match tenant.
    if interview.get("user_id") != ctx.id:
        raise HTTPException(status_code=404, detail="Interview not found")
    tenant = tenant_scope(ctx)
    if tenant is not None and interview.get("company_id") != tenant:
        raise HTTPException(status_code=404, detail="Interview not found")
    return interview


@router.post("/", response_model=InterviewResponse)
async def create_interview(interview: InterviewCreate, user=Depends(get_current_user)):
    supabase = get_supabase()

    result = supabase.table("interviews").insert({
        "candidate_id": str(interview.candidate_id),
        "job_description": interview.job_description,
        "status": "phase_1",
        "current_phase": 1,
        "conversation_history": [],
        "user_id": user.id,
    }).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create interview")

    return result.data[0]


@router.get("/", response_model=List[InterviewResponse])
async def list_interviews(user=Depends(get_tenant_context)):
    supabase = get_supabase()
    tenant = tenant_scope(user)

    q = (
        supabase.table("interviews")
        .select("*")
        .eq("user_id", user.id)
        .order("created_at", desc=True)
    )
    if tenant is not None:
        q = q.eq("company_id", tenant)
    result = q.execute()
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
