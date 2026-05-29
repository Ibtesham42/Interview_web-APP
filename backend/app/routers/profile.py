"""Current-user profile endpoint.

The frontend reads the signed-in user's profile (including role) from here
instead of querying the `profiles` table directly, so it never depends on
client-side RLS configuration. Uses the service-role key.
"""
from fastapi import APIRouter, Depends

from app.supabase_client import get_supabase
from app.auth import get_current_user

router = APIRouter()


@router.get("/me")
async def get_me(user=Depends(get_current_user)):
    """Return the signed-in user's profile, creating the row if it is missing."""
    supabase = get_supabase()
    result = supabase.table("profiles").select("*").eq("id", user.id).execute()

    if result.data:
        profile = result.data[0]
    else:
        # No profile row yet (e.g. account created before the trigger existed).
        # Create one so the app always has a profile to work with.
        metadata = getattr(user, "user_metadata", None) or {}
        new_row = {
            "id": user.id,
            "email": getattr(user, "email", None),
            "full_name": metadata.get("full_name", ""),
        }
        try:
            inserted = supabase.table("profiles").insert(new_row).execute()
            profile = inserted.data[0] if inserted.data else {**new_row, "role": "user"}
        except Exception:
            profile = {**new_row, "role": "user"}

    # `company_id` MUST be included — the frontend's `AuthContext` uses
    # it to drive `companiesApi.getMine()` and every tenant-scoped
    # capability gate (`invite_candidate`, `manage_company_settings`).
    # Omitting it silently fails every TENANT-requiring capability for
    # `company_admin` / `recruiter` accounts, even though their DB row
    # has the right value. Surfaced on 2026-05-29 — see CHANGE.md.
    return {
        "id": profile["id"],
        "email": profile.get("email"),
        "full_name": profile.get("full_name"),
        "role": profile.get("role", "user"),
        "company_id": profile.get("company_id"),
        "created_at": profile.get("created_at", ""),
    }
