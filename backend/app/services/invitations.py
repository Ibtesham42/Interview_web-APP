"""Candidate-invitation ledger (migration 011).

An invitation is the first-class record that a Company asked a candidate
(identified by email) to interview. It is what lets:

- an existing candidate accept an invite from a second company without
  touching `profiles.company_id` (which stays their primary tenant), and
- one candidate hold invitations from multiple companies at once.

A candidate's tenant access = `profiles.company_id` PLUS every company
with a non-declined invitation for their email. `allowed_company_ids`
is the single place that union is computed; the interview-create path
and the WebSocket tenant gate both consume it.

Every helper here is tolerant of the `candidate_invitations` table not
existing yet (migration 011 not applied): writes are best-effort and
reads degrade to "no invitations" so the pre-existing flows keep
working until the migration lands.
"""
from typing import Any, Dict, List, Optional, Set


def normalize_email(email: Optional[str]) -> str:
    """Lowercased, trimmed email — the ledger's join key."""
    return (email or "").strip().lower()


def upsert_invitation(
    supabase,
    *,
    company_id: str,
    email: str,
    candidate_name: Optional[str] = None,
    invited_by: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Record an invitation; a re-invite of the same (company, email) is a
    no-op (the unique constraint keeps one row). Returns the row, or None
    when the write failed (missing table — logged, never raised: the
    invite email itself is the pre-existing behaviour and must not break).
    """
    addr = normalize_email(email)
    if not addr:
        return None
    payload = {
        "company_id": company_id,
        "email": addr,
        "candidate_name": (candidate_name or "").strip() or None,
        "invited_by": invited_by,
    }
    try:
        existing = (
            supabase.table("candidate_invitations")
            .select("*")
            .eq("company_id", company_id)
            .eq("email", addr)
            .execute()
            .data
            or []
        )
        if existing:
            row = existing[0]
            # A re-invite revives a declined invitation — the company is
            # explicitly asking again.
            if row.get("status") == "declined":
                updated = (
                    supabase.table("candidate_invitations")
                    .update({"status": "pending"})
                    .eq("id", row["id"])
                    .execute()
                    .data
                    or []
                )
                return updated[0] if updated else {**row, "status": "pending"}
            return row
        result = supabase.table("candidate_invitations").insert(payload).execute()
        return result.data[0] if result.data else payload
    except Exception as e:
        print(f"[invitations] upsert failed (migration 011 applied?): {e}")
        return None


def list_invitations_for_email(supabase, email: str) -> List[Dict[str, Any]]:
    """All invitation rows for a candidate email (any status), newest first.
    Returns [] when the table is missing."""
    addr = normalize_email(email)
    if not addr:
        return []
    try:
        return (
            supabase.table("candidate_invitations")
            .select("*")
            .eq("email", addr)
            .order("created_at", desc=True)
            .execute()
            .data
            or []
        )
    except Exception as e:
        print(f"[invitations] list failed (migration 011 applied?): {e}")
        return []


def invited_company_ids(supabase, email: str) -> Set[str]:
    """Companies with a live (pending or accepted) invitation for this email.

    Declined invitations grant no access. Pending counts — accepting is
    implicit in acting on the invite (claiming / starting an interview),
    so a candidate is never blocked on a separate accept step.
    """
    return {
        row["company_id"]
        for row in list_invitations_for_email(supabase, email)
        if row.get("status") in ("pending", "accepted") and row.get("company_id")
    }


def allowed_company_ids(
    supabase, *, email: str, profile_company_id: Optional[str]
) -> Set[str]:
    """Every company this candidate may interview for."""
    allowed = invited_company_ids(supabase, email)
    if profile_company_id:
        allowed.add(profile_company_id)
    return allowed


def mark_accepted(supabase, *, company_id: str, email: str, user_id: str) -> None:
    """Flip a pending/declined invitation to accepted and stamp the user.

    Best-effort: called from claim-company and interview-create where the
    membership decision has already been made; a ledger write failure
    must not fail the user-facing action.
    """
    addr = normalize_email(email)
    if not addr:
        return
    try:
        supabase.table("candidate_invitations").update({
            "status": "accepted",
            "accepted_user_id": user_id,
            "accepted_at": "now()",
        }).eq("company_id", company_id).eq("email", addr).neq("status", "accepted").execute()
    except Exception as e:
        print(f"[invitations] mark_accepted failed: {e}")


def ensure_accepted_membership(
    supabase, *, company_id: str, email: str, user_id: str
) -> None:
    """Guarantee an accepted invitation row exists for (company, email).

    Used by claim-company: a candidate may arrive via a shared apply link
    without ever having been emailed an invitation — the ledger should
    still reflect the membership they just claimed.
    """
    row = upsert_invitation(supabase, company_id=company_id, email=email)
    if row is None:
        return
    if row.get("status") != "accepted":
        mark_accepted(supabase, company_id=company_id, email=email, user_id=user_id)
