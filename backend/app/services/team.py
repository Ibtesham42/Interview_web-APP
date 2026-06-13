"""Team-membership data access (migration 014).

Membership lives on `profiles` (role + company_id) — this module reads members
from there and manages the `team_invitations` ledger (list / invite / revoke /
accept). Authorization (`manage_team`) is enforced in the router; accept is
identity-checked there (the caller's email must match the invitation).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.invitations import normalize_email

# Roles that count as a company's team members. Platform 'admin' is excluded —
# they have no company_id, so they're never a tenant member.
_MEMBER_ROLES = ("recruiter", "company_admin")


def list_members(supabase, company_id: str) -> List[Dict[str, Any]]:
    """Profiles in this company holding a hiring role."""
    return (
        supabase.table("profiles")
        .select("id,email,full_name,role")
        .eq("company_id", company_id)
        .in_("role", list(_MEMBER_ROLES))
        .execute()
        .data
        or []
    )


def list_pending_invitations(supabase, company_id: str) -> List[Dict[str, Any]]:
    return (
        supabase.table("team_invitations")
        .select("id,email,role,status,invited_by,created_at")
        .eq("company_id", company_id)
        .eq("status", "pending")
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )


def upsert_invitation(
    supabase, *, company_id: str, email: str, role: str, invited_by: Optional[str]
) -> Dict[str, Any]:
    """Create a pending team invitation, or revive/re-point an existing one.

    The UNIQUE(company_id, email) constraint keeps one row per address; a
    re-invite updates the role + flips back to pending (an admin re-inviting a
    revoked address, or changing the offered role)."""
    addr = normalize_email(email)
    existing = (
        supabase.table("team_invitations")
        .select("*")
        .eq("company_id", company_id)
        .eq("email", addr)
        .execute()
        .data
        or []
    )
    if existing:
        row = existing[0]
        update = {"role": role, "status": "pending", "invited_by": invited_by}
        updated = (
            supabase.table("team_invitations")
            .update(update)
            .eq("id", row["id"])
            .execute()
            .data
            or []
        )
        return updated[0] if updated else {**row, **update}
    payload = {
        "company_id": company_id,
        "email": addr,
        "role": role,
        "invited_by": invited_by,
        "status": "pending",
    }
    inserted = supabase.table("team_invitations").insert(payload).execute().data or []
    return inserted[0] if inserted else payload


def revoke_invitation(supabase, *, invitation_id: str, company_id: str) -> bool:
    """Revoke a pending invitation in this tenant. Returns True if a row was
    revoked — tenant-scoped + pending-only, so another company's (or an
    already-accepted) invitation is never touched."""
    updated = (
        supabase.table("team_invitations")
        .update({"status": "revoked"})
        .eq("id", invitation_id)
        .eq("company_id", company_id)
        .eq("status", "pending")
        .execute()
        .data
        or []
    )
    return len(updated) > 0


def find_pending_for(
    supabase, *, company_id: str, email: str
) -> Optional[Dict[str, Any]]:
    """The pending invitation for (company, email), or None."""
    rows = (
        supabase.table("team_invitations")
        .select("*")
        .eq("company_id", company_id)
        .eq("email", normalize_email(email))
        .eq("status", "pending")
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def mark_accepted(supabase, *, invitation_id: str, user_id: str) -> None:
    """Flip a pending invitation to accepted, stamping the accepting user. Uses
    an explicit ISO timestamp (PostgREST stores values literally — a bare
    'now()' string would not evaluate)."""
    supabase.table("team_invitations").update({
        "status": "accepted",
        "accepted_user_id": user_id,
        "accepted_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", invitation_id).execute()
