"""Company management endpoints.

PR 3 of the multi-tenant rollout (MULTI_TENANT_ROLLOUT.md).

Today this module exposes one endpoint — `POST /api/companies/` for
self-serve company signup. The caller must be authenticated as a
plain `user` (no existing tenant); the call atomically creates the
Company row and flips the caller's profile to
`role='company_admin' + company_id=<new company>`.

What's intentionally NOT here yet (deferred follow-ups):
- Invite-link / member-management endpoints — single-admin tenants
  for now; a Company has exactly one creator-admin until a future PR
  introduces team invites.
- Company-settings GET/PATCH — name + slug are immutable post-create
  in this PR; renaming flows through a settings endpoint added later.
- Tenant offboarding (delete a Company) — handled outside the
  product surface; not a self-serve action.
"""
from __future__ import annotations

import re
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_tenant_context
from app.models.schemas import CompanyCreate, CompanyResponse, CompanySignupResponse
from app.supabase_client import get_supabase

router = APIRouter()


# Slugs reserved for either operational reasons (so /apply/admin doesn't
# collide with /admin in the SPA router) or for the migration-004 sentinel
# (`default` is the backfill Company id). Keep small + defensive — the
# regex on `CompanyCreate.slug` already rejects most garbage.
_RESERVED_SLUGS = frozenset({
    "default", "admin", "api", "auth", "login", "signup", "settings",
    "companies", "apply", "recruiter", "report", "reports", "dashboard",
    "interview", "interviews", "www", "support", "help",
})

# Same slug regex as the Pydantic field — duplicated here so the
# error message at the API boundary explains *why* a slug was rejected
# (Pydantic's stock pattern error is cryptic). The check itself is
# redundant; we keep it for the clearer message.
_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]*$")


@router.post(
    "/",
    response_model=CompanySignupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_company(body: CompanyCreate, ctx=Depends(get_tenant_context)):
    """Self-serve Company signup.

    Preconditions (caller must satisfy ALL):
    - Authenticated (any Supabase user).
    - Role is `user` — already-admins (platform or company) and
      already-recruiters cannot create a Company through this endpoint.
      A platform admin who needs a Company is a manual ops task; a
      Recruiter creating a Company would split their identity across
      two tenants in confusing ways.
    - `company_id` is NULL — i.e. the caller is a B2C user with no
      existing tenant. (A user who joined via /apply/{slug} already has
      `company_id` set and cannot start a competing Company.)

    Effects (on success):
    - Insert one `companies` row with the given slug + name; created_by
      stamped with the caller.
    - Update the caller's `profiles` row: `role='company_admin'`,
      `company_id=<new company id>`.

    Failure mappings:
    - 400 — invalid slug (extra defense beyond Pydantic), reserved slug,
      or duplicate slug. All return a clear `detail` so the frontend
      can surface a field-level error without a second round-trip.
    - 403 — caller's role / company_id doesn't satisfy the preconditions
      above.
    """
    slug = body.slug.strip().lower()
    name = body.name.strip()
    if not _SLUG_RE.match(slug):
        raise HTTPException(
            status_code=400,
            detail="Slug must start with a letter and contain only lowercase letters, digits, and hyphens.",
        )
    if slug in _RESERVED_SLUGS:
        raise HTTPException(status_code=400, detail=f"Slug '{slug}' is reserved")

    # Preconditions on caller. We reject early so we never half-create a
    # Company that the caller then cannot administer (and which would
    # need manual cleanup).
    if ctx.role != "user":
        raise HTTPException(
            status_code=403,
            detail="Only standard users can create a company. Sign in with a non-admin / non-recruiter account.",
        )
    if ctx.company_id is not None:
        raise HTTPException(
            status_code=403,
            detail="You're already a member of a company. Each user can belong to one company.",
        )

    supabase = get_supabase()

    # Slug uniqueness check (clear error path). The DB also enforces
    # UNIQUE on slug via migration 004 — the existence check below is
    # belt-and-braces so the API never relies on raw Postgres error
    # parsing to produce a useful 400.
    existing = (
        supabase.table("companies")
        .select("id")
        .eq("slug", slug)
        .execute()
        .data
        or []
    )
    if existing:
        raise HTTPException(status_code=400, detail=f"Slug '{slug}' is taken")

    # Atomic-as-we-can-get-it: create the company, then flip the
    # caller's role + company_id. Supabase / PostgREST doesn't expose
    # multi-statement transactions through the JS client; if the second
    # write fails we orphan the company row. A real ATS would wrap this
    # in a Postgres function (SECURITY DEFINER) — deferred until the
    # orphan rate is non-zero. For now: log + best-effort cleanup.
    insert_result = (
        supabase.table("companies")
        .insert({
            "slug": slug,
            "name": name,
            "created_by": ctx.id,
        })
        .execute()
    )
    rows = insert_result.data or []
    if not rows:
        raise HTTPException(status_code=500, detail="Company create failed")
    company_row = rows[0]
    company_id = company_row["id"]

    try:
        profile_result = (
            supabase.table("profiles")
            .update({"role": "company_admin", "company_id": company_id})
            .eq("id", ctx.id)
            .execute()
        )
    except Exception as exc:
        # Best-effort cleanup of the orphan company row so re-attempts
        # don't trip the slug-taken check.
        try:
            supabase.table("companies").delete().eq("id", company_id).execute()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Profile update failed: {exc}")

    profile_rows = profile_result.data or []
    profile_payload: Dict[str, Any] = (
        profile_rows[0]
        if profile_rows
        # Fall back to the in-memory shape if Supabase returned [] on
        # update (same pattern as `upsert_recruiter_decision`).
        else {"id": ctx.id, "role": "company_admin", "company_id": company_id}
    )

    return CompanySignupResponse(
        company=CompanyResponse(
            id=company_row["id"],
            slug=company_row["slug"],
            name=company_row["name"],
            created_at=company_row["created_at"],
        ),
        profile=profile_payload,
    )
