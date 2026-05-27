"""Authentication helpers.

The backend uses the Supabase service-role key for database access, so it must
explicitly identify the caller. The frontend sends the user's Supabase access
token as a Bearer token; `get_current_user` validates it against Supabase Auth
and returns the authenticated user.

For tenant-scoped handlers (admin / recruiter / company-scoped routes), use
`get_tenant_context` — it bundles the caller's role + company_id alongside
their user id so handlers can apply `company_id` filters without re-fetching
the profile per request. The role gates (`get_current_admin`,
`get_current_recruiter`) are thin wrappers over the same context, so handlers
that need both gate and scope use one dependency.
"""
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException, status

from app.supabase_client import get_supabase


@dataclass
class TenantContext:
    """Caller identity + tenant scope.

    Returned by `get_tenant_context` and (transitively) by
    `get_current_admin` / `get_current_recruiter`. Handlers that previously
    wrote `user.id` continue to work via the `id` property — the context
    behaves like a user object for that one attribute and adds tenant
    metadata on top.
    """
    user_id: str
    role: str
    company_id: Optional[str]

    @property
    def id(self) -> str:
        """Backward-compat: handlers that read `ctx.id` get the user id."""
        return self.user_id

    @property
    def is_platform_admin(self) -> bool:
        """`role='admin'` is the platform-wide super-admin per grill C3.

        Platform admins have `company_id IS NULL` and bypass tenant filters
        in every handler. Company-scoped roles (`recruiter` today,
        `company_admin` after PR 3) get scoping applied.
        """
        return self.role == "admin"


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


def _fetch_profile(user_id: str) -> Optional[dict]:
    """Read role + company_id for a given user from the `profiles` table.

    One Supabase round-trip; returns None if the profile row is missing or
    the lookup fails — callers decide how to map that to an HTTP response.
    Replaces the older `_fetch_role` (kept inline below for the auth gates
    that still only need the role, e.g. the report-endpoint precursor PR).
    """
    supabase = get_supabase()
    try:
        result = (
            supabase.table("profiles")
            .select("role,company_id")
            .eq("id", user_id)
            .execute()
        )
    except Exception:
        return None
    return result.data[0] if result.data else None


def _fetch_role(user_id: str) -> Optional[str]:
    """Read just the role for a given user. Kept for callers that don't need
    the full tenant context (e.g. `routers/reports.py` ownership-or-role
    gate). Calls `_fetch_profile` underneath so there's still one query."""
    profile = _fetch_profile(user_id)
    return profile.get("role") if profile else None


def get_tenant_context(user=Depends(get_current_user)) -> TenantContext:
    """FastAPI dependency: resolve the caller's role + tenant scope.

    Used by handlers that filter results by `company_id`. Pairs naturally
    with the role gates (`get_current_admin`, `get_current_recruiter`) which
    return the same `TenantContext` shape — a handler that needs both gate
    and scope picks the gate dependency and reads `ctx.company_id` from the
    same object.
    """
    profile = _fetch_profile(user.id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not verify account profile",
        )
    return TenantContext(
        user_id=user.id,
        role=profile.get("role") or "user",
        company_id=profile.get("company_id"),
    )


def get_current_admin(ctx: TenantContext = Depends(get_tenant_context)) -> TenantContext:
    """FastAPI dependency: require an admin (platform or company).

    Both `role='admin'` (platform-wide super-admin per ADR 0005 C3) and
    `role='company_admin'` (tenant-local admin) pass this gate. The
    conditional filters in the underlying handlers (added in PR 1 and
    PR 2) transparently scope correctly: `is_platform_admin` is True
    only for `role='admin'`, so a `company_admin` always carries their
    `company_id` filter through `tenant_scope`.

    The role-set is sourced from `app.capabilities.TENANT_ADMINS` — see
    ADR 0006 for the single-source-of-truth rationale.
    """
    # Local import: app.capabilities imports TenantContext-shape from
    # this module's data classes, so we keep this import inside the
    # function body to avoid module-load cycles.
    from app.capabilities import TENANT_ADMINS

    if ctx.role not in TENANT_ADMINS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return ctx


def get_current_recruiter(ctx: TenantContext = Depends(get_tenant_context)) -> TenantContext:
    """FastAPI dependency: require recruiter, company_admin, or admin.

    Per the B1 access matrix (RECRUITER_ROLLOUT.md), Admins inherit
    Recruiter capabilities additively. Company Admins also inherit
    Recruiter capabilities within their tenant. Tenant scoping is
    enforced by the handlers via `tenant_scope`; this gate only
    decides role admission.

    The role-set is sourced from `app.capabilities.HIRING_ROLES` — see
    ADR 0006 for the single-source-of-truth rationale.
    """
    from app.capabilities import HIRING_ROLES

    if ctx.role not in HIRING_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Recruiter access required",
        )
    return ctx


def tenant_scope(ctx: TenantContext) -> Optional[str]:
    """Translate a TenantContext into the `company_id` filter to apply.

    Returns `None` for platform admins (grill C3 — they see across all
    tenants) and the caller's `company_id` otherwise. Centralised here so
    every router reads the same translation; if a future role should
    bypass tenant scoping, this is the single line to update.

    Used by admin / recruiter / dashboard / interviews / reports / WS
    handlers — anywhere a query needs to be tenant-filtered.
    """
    if ctx.is_platform_admin:
        return None
    return ctx.company_id
