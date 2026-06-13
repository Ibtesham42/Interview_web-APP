"""Team management endpoints (migration 014) at /api/team.

Self-serve teammate onboarding: a company_admin invites a person to a hiring
role; on acceptance the invitee's profile is stamped with the role + company.
Management endpoints are gated by `manage_team` (TENANT_ADMINS + a tenant — a
Recruiter cannot add teammates); accept is gated by auth + an email-identity
match. Data access lives in services/team.py.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user, get_tenant_context
from app.capabilities import requires
from app.config import get_settings
from app.models.schemas import (
    AcceptTeamInviteRequest,
    AcceptTeamInviteResponse,
    TeamInvitationRow,
    TeamInviteRequest,
    TeamInviteResponse,
    TeamMemberRow,
    TeamResponse,
)
from app.services import email as email_svc
from app.services import team as team_svc
from app.services.email_templates import default_team_invite_template
from app.supabase_client import get_supabase

router = APIRouter()


def _load_company(supabase, company_id) -> dict:
    rows = (
        supabase.table("companies")
        .select("id,slug,name,email,phone,address")
        .eq("id", company_id)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Company not found")
    return rows[0]


@router.get("/", response_model=TeamResponse)
async def get_team(ctx=requires("manage_team")):
    """Current members (profiles with a hiring role) + pending invitations."""
    supabase = get_supabase()
    members = team_svc.list_members(supabase, ctx.company_id)
    invites = team_svc.list_pending_invitations(supabase, ctx.company_id)
    return TeamResponse(
        members=[
            TeamMemberRow(
                id=m["id"], email=m.get("email") or "",
                full_name=m.get("full_name"), role=m["role"],
            )
            for m in members
        ],
        invitations=[
            TeamInvitationRow(
                id=i["id"], email=i["email"], role=i["role"], status=i["status"],
                invited_by=i.get("invited_by"), created_at=i["created_at"],
            )
            for i in invites
        ],
    )


@router.post("/invite", response_model=TeamInviteResponse)
async def invite_member(body: TeamInviteRequest, ctx=requires("manage_team")):
    """Invite a teammate to a hiring role + email them an accept link."""
    supabase = get_supabase()
    company = _load_company(supabase, ctx.company_id)

    invitation = team_svc.upsert_invitation(
        supabase,
        company_id=ctx.company_id,
        email=body.email,
        role=body.role,
        invited_by=ctx.id,
    )

    base = get_settings().frontend_base_url.rstrip("/")
    accept_url = f"{base}/team/accept?company={company['slug']}"
    rendered = default_team_invite_template(company, body.role, accept_url)
    try:
        sent = await email_svc.send(
            supabase,
            company_id=ctx.company_id,
            candidate_id=None,
            sender_id=ctx.id,
            to=body.email.strip(),
            subject=rendered["subject"],
            body=rendered["body"],
            email_type="team_invite",
            from_name=(company.get("name") or "").strip() or None,
            reply_to=(company.get("email") or "").strip() or None,
        )
        email_status = sent["status"]
        email_error = sent.get("error_message")
    except email_svc.EmailRateLimited as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except email_svc.EmailServiceError:
        # The invitation ledger row is written regardless — membership doesn't
        # depend on email delivery (same posture as candidate invites).
        email_status = "failed"
        email_error = "Could not record the invitation email."

    return TeamInviteResponse(
        id=invitation["id"],
        email=invitation["email"],
        role=invitation["role"],
        status=invitation["status"],
        email_status=email_status,
        email_error=email_error,
    )


@router.post("/invitations/{invitation_id}/revoke")
async def revoke_member_invite(invitation_id: str, ctx=requires("manage_team")):
    """Revoke a pending team invitation in the caller's tenant."""
    supabase = get_supabase()
    if not team_svc.revoke_invitation(
        supabase, invitation_id=invitation_id, company_id=ctx.company_id
    ):
        raise HTTPException(status_code=404, detail="Invitation not found")
    return {"id": invitation_id, "status": "revoked"}


@router.post("/accept", response_model=AcceptTeamInviteResponse)
async def accept_team_invite(
    body: AcceptTeamInviteRequest,
    user=Depends(get_current_user),
    ctx=Depends(get_tenant_context),
):
    """Accept a team invitation: stamp the caller's profile with the invited
    role + company. Identity-checked (the pending invitation must match the
    caller's email) and limited to plain 'user' accounts — a person who already
    administers/recruits for a company can't be silently repurposed (the
    one-user-one-company model can't hold multi-company membership)."""
    supabase = get_supabase()
    company_rows = (
        supabase.table("companies")
        .select("id,slug,name")
        .eq("slug", body.company_slug.strip().lower())
        .limit(1)
        .execute()
        .data
        or []
    )
    if not company_rows:
        raise HTTPException(status_code=404, detail="Company not found")
    company_id = company_rows[0]["id"]

    email = getattr(user, "email", "") or ""
    invitation = team_svc.find_pending_for(supabase, company_id=company_id, email=email)
    if invitation is None:
        raise HTTPException(
            status_code=404, detail="No pending team invitation for your account."
        )

    if ctx.role != "user":
        raise HTTPException(
            status_code=400,
            detail=(
                "This account is already part of a company. Accept team "
                "invitations from a personal account."
            ),
        )

    update = {"role": invitation["role"], "company_id": company_id}
    profile_rows = (
        supabase.table("profiles").update(update).eq("id", user.id).execute().data or []
    )
    team_svc.mark_accepted(supabase, invitation_id=invitation["id"], user_id=user.id)

    profile = profile_rows[0] if profile_rows else {"id": user.id, **update}
    return AcceptTeamInviteResponse(
        company_id=company_id, role=invitation["role"], profile=profile
    )
