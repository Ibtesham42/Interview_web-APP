"""Authentication helpers.

The backend uses the Supabase service-role key for database access, so it must
explicitly identify the caller. The frontend sends the user's Supabase access
token as a Bearer token; `get_current_user` validates it against Supabase Auth
and returns the authenticated user.
"""
from fastapi import Depends, Header, HTTPException, status

from app.supabase_client import get_supabase


def get_current_user(authorization: str = Header(None)):
    """FastAPI dependency: resolve the Supabase user from a Bearer token.

    Raises 401 if the Authorization header is missing or the token is invalid.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )

    token = authorization.split(" ", 1)[1].strip()
    try:
        response = get_supabase().auth.get_user(token)
    except Exception as e:
        # Log the real reason server-side (never sent to the client). This
        # distinguishes a genuinely bad token from a backend Supabase
        # misconfiguration: "invalid JWT"/"bad_jwt" => SUPABASE_URL points at a
        # different project than the one that issued the token; "API key" =>
        # SUPABASE_KEY is wrong; a connection error => SUPABASE_URL unreachable.
        print(f"[auth] token validation failed: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )

    user = getattr(response, "user", None)
    if user is None or not getattr(user, "id", None):
        print("[auth] token validation returned no user")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )
    return user


def _fetch_role(user_id: str) -> str | None:
    """Read the role for a given user from the `profiles` table.

    Returns None if the profile row is missing or the lookup fails — callers
    decide how to map that to an HTTP response.
    """
    supabase = get_supabase()
    try:
        result = supabase.table("profiles").select("role").eq("id", user_id).execute()
    except Exception:
        return None
    return result.data[0].get("role") if result.data else None


def get_current_admin(user=Depends(get_current_user)):
    """FastAPI dependency: require an authenticated user with the 'admin' role.

    Raises 403 for non-admin users. The role lives on the `profiles` table.
    """
    role = _fetch_role(user.id)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not verify account role",
        )
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


def get_current_recruiter(user=Depends(get_current_user)):
    """FastAPI dependency: require an authenticated user with the 'recruiter'
    or 'admin' role.

    Per the B1 access matrix (RECRUITER_ROLLOUT.md), Admins inherit Recruiter
    capabilities additively — both roles pass this gate.
    """
    role = _fetch_role(user.id)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not verify account role",
        )
    if role not in ("recruiter", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Recruiter access required",
        )
    return user
