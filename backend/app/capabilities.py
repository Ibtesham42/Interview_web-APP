"""Capability gates for cross-layer authorization checks.

Single source of truth for "who can do what." Consumed by:
- FastAPI handlers via `requires(capability)` (this module)
- The role-gate dependencies in `app.auth` — they import the named
  role-sets from here so existing `Depends(get_current_admin)` /
  `Depends(get_current_recruiter)` call sites don't change but the
  rule about which roles count as admin lives in one place
- The TypeScript mirror at `frontend/src/services/capabilities.ts`
  which copies the predicate shapes so the React UI hides controls
  the API would reject

See `docs/adr/0006-capability-module.md` for the design decisions
(D1–D6) that produced this shape. In short:

- Capabilities are named after domain verbs (`'invite_candidate'`).
- Each capability is a pure predicate function of `TenantContext`.
- Admin without a `company_id` honestly fails tenant-requiring
  capabilities (no `is_platform_admin` bypass); ADR 0005 grill C3 is
  preserved.
- `requires(...)` returns a generic 403 on denial; specific 400s with
  user-actionable messages stay in handler code where they have full
  context.

Import note: this module is imported by `app.auth` at module load
(for the role-sets), so it MUST NOT import from `app.auth` at module
load — the FastAPI dependency factory does its `from app.auth`
import lazily inside the factory body.

To add a capability:
1. Add a new entry to `CAPABILITIES` below. Use a verb name.
2. Mirror the entry in `frontend/src/services/capabilities.ts`.
3. (Optional) Use `requires('new_capability')` in the relevant
   FastAPI route, or just call `can(ctx, 'new_capability')` inside
   a handler.

To add a role:
1. Add the role string to the appropriate role-set below.
2. Update the role CHECK constraint in a migration if the DB
   doesn't already admit the new string (see migration 005).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, FrozenSet

from fastapi import HTTPException, status


# ---------------------------------------------------------------------------
# Named role-sets.
#
# These are the "what is an admin / a hiring person?" definitions. The
# capability predicates compose them via set membership. `auth.py` also
# imports them so the get_current_admin / get_current_recruiter deps stay
# in sync without their own copies of the role list.
#
# `frozenset` so accidental mutation at import time is impossible.
# ---------------------------------------------------------------------------

TENANT_ADMINS: FrozenSet[str] = frozenset({"admin", "company_admin"})
"""Roles that see the Admin overview + manage Company Settings.
Platform `admin` is included here even though they have no `company_id`;
the tenant predicate on individual capabilities denies them per-action
where needed (e.g. `manage_company_settings` AND `invite_candidate`)."""

HIRING_ROLES: FrozenSet[str] = TENANT_ADMINS | frozenset({"recruiter"})
"""Roles that perform Recruiter workflow actions (Shortlist, Reject,
Bookmark, Notes). Per the B1 access matrix from RECRUITER_ROLLOUT.md:
Admin and Company Admin both inherit Recruiter capabilities via
role-gating, with actor identity preserved on every workflow row."""


# ---------------------------------------------------------------------------
# Capability predicates.
#
# Each capability is a pure function of TenantContext returning bool.
# No exceptions, no side effects. The factory `requires(...)` below
# wraps these into FastAPI dependencies; the frontend mirror calls
# them directly from React.
#
# Type-hinted as `Any` to avoid the module-load circular import with
# `app.auth` — TenantContext is only used at runtime where duck-typing
# on `.role` + `.company_id` is sufficient.
# ---------------------------------------------------------------------------

Predicate = Callable[[Any], bool]


CAPABILITIES: Dict[str, Predicate] = {
    # Public application funnel — only `'user'` roles can self-serve
    # create a company. A user already in a tenant cannot start a
    # competing one. Mirrors the create_company endpoint preconditions
    # (see companies.py:160).
    "create_company": lambda ctx: ctx.role == "user" and ctx.company_id is None,

    # Tenant-scoped invitation flow. Requires hiring role AND a tenant
    # — admin without `company_id` honestly fails (see ADR 0006 D3).
    "invite_candidate": lambda ctx: (
        ctx.role in HIRING_ROLES and ctx.company_id is not None
    ),

    # Settings page. Apply link + company contact info + invite card.
    # Same predicate shape as invite_candidate; kept separate so a
    # future PR can split "view settings" from "edit settings" without
    # disturbing invite.
    "manage_company_settings": lambda ctx: (
        ctx.role in TENANT_ADMINS and ctx.company_id is not None
    ),

    # Admin overview page. Platform admin allowed even without
    # company_id (they see all-tenants overview); company_admin
    # allowed and sees only their tenant via the existing
    # tenant_scope filter in the handler.
    "see_admin_overview": lambda ctx: ctx.role in TENANT_ADMINS,

    # Recruiter workflow — Shortlist / Reject / Bookmark / Notes on
    # Candidates. Tenant scope enforced at the handler via
    # `_resolve_candidate_tenant`; this gate is role-only.
    "manage_candidates": lambda ctx: ctx.role in HIRING_ROLES,
}


def can(ctx: Any, capability_name: str) -> bool:
    """Return True if the caller has the named capability.

    Raises KeyError on unknown capability names. We don't soft-fail
    unknown names to bool False — a typo at a call site would silently
    hide a button forever; a KeyError surfaces the bug at test time.
    """
    return CAPABILITIES[capability_name](ctx)


# ---------------------------------------------------------------------------
# FastAPI dependency factory.
#
# `requires(capability)` returns a Depends that:
#   1. Resolves the caller's TenantContext via the existing dep.
#   2. Calls `can(ctx, capability)`.
#   3. Raises 403 with a clear capability-name message on denial.
#
# The 403 message names the capability so direct API consumers
# (Postman / curl / integrations) can diagnose. End users hit this
# rarely because the React UI hides controls via `can()` already.
# Handlers that want richer error messages (e.g. the 400-with-action
# in `invite_candidate`) keep their own guard as belt-and-braces
# below the capability gate.
#
# Late import of `app.auth` (inside the factory) breaks the circular
# import: `auth.py` imports the role-sets above at module load; we
# can't reciprocate at module load, but the factory only runs when a
# route module is imported, by which time both modules are loaded.
# ---------------------------------------------------------------------------


def requires(capability_name: str):
    """Build a FastAPI dependency that admits only callers with the
    named capability.

    Usage:

        @router.post("/invite")
        async def invite(
            body: ...,
            ctx = Depends(requires("invite_candidate")),
        ):
            ...
    """
    # Sanity check at module-load (when route decorator runs) — a
    # typo in the capability name surfaces here rather than at first
    # request.
    if capability_name not in CAPABILITIES:
        raise KeyError(
            f"Unknown capability '{capability_name}'. Known: "
            f"{sorted(CAPABILITIES.keys())}"
        )

    # Late import to break the cycle with app.auth. By the time any
    # router calls `requires(...)`, both modules are fully loaded.
    from fastapi import Depends
    from app.auth import get_tenant_context

    def _dep(ctx=Depends(get_tenant_context)):
        if not can(ctx, capability_name):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires '{capability_name}'",
            )
        return ctx

    return Depends(_dep)
