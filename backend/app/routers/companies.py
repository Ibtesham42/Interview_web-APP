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

from app.auth import get_current_user, get_tenant_context
from app.config import get_settings
from app.models.schemas import (
    CompanyCreate,
    CompanyResponse,
    CompanySignupResponse,
    InviteCandidateRequest,
    InviteCandidateResponse,
)
from app.services import email as email_svc
from app.services.email_templates import default_invite_template
from app.supabase_client import get_supabase

router = APIRouter()


@router.get("/all")
async def list_all_companies(ctx=Depends(get_tenant_context)):
    """List every Company on the platform.

    Audience: platform admin (`role='admin'`) only. Powers the
    "Act-as company" picker in the SPA header (Candidate C,
    2026-05-29). A `company_admin` / `recruiter` doesn't need this —
    they already have one tenant; cross-tenant browsing isn't part of
    their role.

    Returns a thin payload (id + slug + name) — no contact info, no
    counts. Picker only needs the label and the id to send back as
    `X-Acting-As-Company`.

    The role check uses `ctx.role == 'admin'` rather than
    `get_current_admin` because the latter admits `company_admin` too;
    cross-tenant listing is platform-admin-only.
    """
    if ctx.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-tenant listing is platform-admin-only",
        )

    rows = (
        get_supabase()
        .table("companies")
        .select("id,slug,name")
        .order("name")
        .execute()
        .data
        or []
    )
    return [{"id": r["id"], "slug": r["slug"], "name": r["name"]} for r in rows]


@router.get("/mine", response_model=CompanyResponse)
async def get_my_company(user=Depends(get_current_user)):
    """Return the caller's own company.

    Multi-tenant PR 5 — used by the Settings page (shareable apply link)
    and the Header chip ("you're in Acme"). The caller must have a
    `company_id` set on their profile; platform admins (NULL company_id)
    and B2C users hit 404 — same shape, no role-leak through the error.

    Auth is `get_current_user` (not `get_tenant_context`) so the caller's
    `company_id` is read fresh from the DB rather than cached from the
    request-scoped context — a candidate who just completed
    `/auth/claim-company` (PR 4) sees their tenant on the very next call
    without depending on AuthContext refresh order.
    """
    supabase = get_supabase()

    profile_rows = (
        supabase.table("profiles")
        .select("company_id")
        .eq("id", user.id)
        .execute()
        .data
        or []
    )
    company_id = profile_rows[0].get("company_id") if profile_rows else None
    if company_id is None:
        raise HTTPException(status_code=404, detail="Not a member of any company")

    company_rows = (
        supabase.table("companies")
        .select("id,slug,name,email,phone,address,created_at")
        .eq("id", company_id)
        .execute()
        .data
        or []
    )
    if not company_rows:
        # Profile points at a company that no longer exists — surface
        # the same 404 rather than a misleading 500. Cleanup path is
        # ops-side (orphan rows from a manual delete).
        raise HTTPException(status_code=404, detail="Company not found")

    row = company_rows[0]
    return CompanyResponse(
        id=row["id"],
        slug=row["slug"],
        name=row["name"],
        email=row.get("email", ""),
        phone=row.get("phone"),
        address=row.get("address"),
        created_at=row["created_at"],
    )


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
            "email": body.email.strip(),
            "phone": (body.phone or "").strip() or None,
            "address": (body.address or "").strip() or None,
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
            email=company_row.get("email", ""),
            phone=company_row.get("phone"),
            address=company_row.get("address"),
            created_at=company_row["created_at"],
        ),
        profile=profile_payload,
    )


@router.post(
    "/invite",
    response_model=InviteCandidateResponse,
)
async def invite_candidate(
    body: InviteCandidateRequest,
    ctx=Depends(get_tenant_context),
):
    """Send an apply-link invitation email to a candidate.

    The candidate hasn't signed up yet — `email_outbox.candidate_id`
    is intentionally NULL on this row. The audit trail still works
    (tenant + sender + recipient + body persisted), and a join from
    `email_outbox` to `candidates` later can correlate by `to_email`
    if needed.

    Auth: caller must belong to a Company (`company_id IS NOT NULL`).
    Platform admins and B2C users get 400 — they have no tenant whose
    apply link could be sent. `get_current_admin` is intentionally
    NOT used here so a regular `recruiter` (also tenant-scoped) can
    invite too; matches the B1 access matrix where Recruiters do
    "everything a hiring person does" within their tenant.

    Failure semantics mirror `services/email.send`:
    - Disabled mode (no RESEND_API_KEY) → outbox row written with
      `status='failed'` and `error_message='Email service not
      configured…'`. The UI surfaces the reason to the admin.
    - Resend rejected → same shape; row recorded; caller informed.
    - Insert into outbox itself failed → 500.
    """
    if not ctx.company_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "Only company members can send invitations. "
                "Create a company at /companies/signup first."
            ),
        )

    supabase = get_supabase()

    # Look up the company so the email body includes the company name
    # + the right apply slug. This is one extra SELECT per invite; the
    # caller's TenantContext gives us company_id but not the human
    # name / slug.
    company_rows = (
        supabase.table("companies")
        .select("id,slug,name")
        .eq("id", ctx.company_id)
        .execute()
        .data
        or []
    )
    if not company_rows:
        # Orphaned profile pointing at a deleted Company — surface a
        # clear 404 rather than a misleading 500 inside Resend.
        raise HTTPException(status_code=404, detail="Company not found")
    company = company_rows[0]

    # The frontend's /apply page lives at this URL — see config.py.
    # Production env MUST set FRONTEND_BASE_URL explicitly; the local
    # dev default would send broken links to real candidates.
    base = get_settings().frontend_base_url.rstrip("/")
    apply_url = f"{base}/apply/{company['slug']}"

    rendered = default_invite_template(
        company=company,
        candidate_name=(body.candidate_name or ""),
        apply_url=apply_url,
    )

    try:
        row = await email_svc.send(
            supabase,
            company_id=ctx.company_id,
            candidate_id=None,  # candidate hasn't signed up yet
            sender_id=ctx.id,
            to=body.to_email.strip(),
            subject=rendered["subject"],
            body=rendered["body"],
        )
    except email_svc.EmailServiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return InviteCandidateResponse(
        id=row["id"],
        to_email=row["to_email"],
        subject=row["subject"],
        status=row["status"],
        error_message=row.get("error_message"),
        sent_at=row["sent_at"],
    )
