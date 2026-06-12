"""Candidate-facing invitation endpoints (migration 011).

The company side writes invitations via POST /api/companies/invite; this
router is what the *candidate* sees and acts on:

- `GET /invitations/mine` — every invitation addressed to the caller's
  email, joined with company name/slug, newest first. Drives the
  dashboard "Invitations" panel and the interview-setup company picker.
- `POST /invitations/{id}/accept` — explicit accept. Also happens
  implicitly when the candidate claims an apply link or starts an
  interview for the inviting company, so this endpoint is a UX
  affordance, not a gate.
- `POST /invitations/{id}/decline` — dismiss an invitation. A declined
  invitation grants no tenant access; a company re-inviting flips it
  back to pending.

Matching is by the authenticated user's email (Supabase Auth is the
source of truth for it), lowercased — same key the ledger stores.
"""
from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user
from app.models.schemas import (
    CandidateInvitationListResponse,
    CandidateInvitationRow,
)
from app.services.invitations import list_invitations_for_email, normalize_email
from app.supabase_client import get_supabase

router = APIRouter()


def _require_own_invitation(supabase, invitation_id: str, user) -> dict:
    """Fetch an invitation addressed to the caller. 404 on anything else —
    never reveals whether someone else's invitation id exists."""
    try:
        rows = (
            supabase.table("candidate_invitations")
            .select("*")
            .eq("id", invitation_id)
            .execute()
            .data
            or []
        )
    except Exception:
        rows = []
    if not rows or rows[0].get("email") != normalize_email(getattr(user, "email", "")):
        raise HTTPException(status_code=404, detail="Invitation not found")
    return rows[0]


@router.get("/mine", response_model=CandidateInvitationListResponse)
async def list_my_invitations(user=Depends(get_current_user)):
    supabase = get_supabase()
    invitations = list_invitations_for_email(supabase, getattr(user, "email", ""))

    company_ids = list({i["company_id"] for i in invitations if i.get("company_id")})
    companies: dict = {}
    if company_ids:
        try:
            rows = (
                supabase.table("companies")
                .select("id,name,slug")
                .in_("id", company_ids)
                .execute()
                .data
                or []
            )
            companies = {c["id"]: c for c in rows}
        except Exception:
            companies = {}

    items = []
    for inv in invitations:
        company = companies.get(inv.get("company_id"))
        if company is None:
            # Company deleted since the invite — nothing actionable to show.
            continue
        items.append(
            CandidateInvitationRow(
                id=inv["id"],
                company_id=inv["company_id"],
                company_name=company.get("name") or "",
                company_slug=company.get("slug") or "",
                status=inv.get("status") or "pending",
                candidate_name=inv.get("candidate_name"),
                created_at=inv.get("created_at"),
                accepted_at=inv.get("accepted_at"),
            )
        )
    return CandidateInvitationListResponse(items=items)


@router.post("/{invitation_id}/accept")
async def accept_invitation(invitation_id: str, user=Depends(get_current_user)):
    supabase = get_supabase()
    invitation = _require_own_invitation(supabase, invitation_id, user)
    if invitation.get("status") == "accepted":
        return {"id": invitation_id, "status": "accepted"}
    supabase.table("candidate_invitations").update({
        "status": "accepted",
        "accepted_user_id": user.id,
        "accepted_at": "now()",
    }).eq("id", invitation_id).execute()
    return {"id": invitation_id, "status": "accepted"}


@router.post("/{invitation_id}/decline")
async def decline_invitation(invitation_id: str, user=Depends(get_current_user)):
    supabase = get_supabase()
    invitation = _require_own_invitation(supabase, invitation_id, user)
    if invitation.get("status") == "declined":
        return {"id": invitation_id, "status": "declined"}
    supabase.table("candidate_invitations").update({
        "status": "declined",
    }).eq("id", invitation_id).execute()
    return {"id": invitation_id, "status": "declined"}
