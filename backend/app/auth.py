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
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )

    user = getattr(response, "user", None)
    if user is None or not getattr(user, "id", None):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )
    return user


def get_current_admin(user=Depends(get_current_user)):
    """FastAPI dependency: require an authenticated user with the 'admin' role.

    Raises 403 for non-admin users. The role lives on the `profiles` table.
    """
    supabase = get_supabase()
    try:
        result = supabase.table("profiles").select("role").eq("id", user.id).execute()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not verify account role",
        )
    role = result.data[0].get("role") if result.data else None
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user
