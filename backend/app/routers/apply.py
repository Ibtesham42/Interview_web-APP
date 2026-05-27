"""Public apply route + tenant-claim endpoint (multi-tenant PR 4).

Two endpoints with very different auth postures:

- `GET /api/apply/{slug}` is **public, no auth required** — anyone with
  the shareable link sees the company name on the landing page before
  they decide whether to sign up. This is the only public endpoint that
  reads from a tenant-scoped table; the response is intentionally
  narrow (no candidate counts, no analytics) so a slug enumerator
  cannot mine the platform for tenant size or status.

- `POST /api/auth/claim-company` is **authenticated**. Called by the
  frontend after a candidate completes /signup from an apply link.
  Stamps `company_id` on the caller's profile when they currently have
  `company_id IS NULL`. Refuses to overwrite an existing tenant —
  never silently steals a candidate into a different company.

Why two endpoints, not one combined: the public landing page reads
company info BEFORE the user creates an account; the claim happens
AFTER. They share the slug lookup but live in different auth contexts.
"""
from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_user
from app.models.schemas import ApplyLandingResponse, ClaimCompanyRequest
from app.supabase_client import get_supabase

router = APIRouter()


def _lookup_company_by_slug(supabase, slug: str):
    """Return the company row matching `slug`, or None.

    Lowercases the input for safety. The DB index on `companies.slug`
    is case-sensitive (Postgres default text); the slug regex enforced
    on creation guarantees lowercase, so this normalisation is
    defense-in-depth against a future ALTER that loosens the regex.
    """
    rows = (
        supabase.table("companies")
        .select("id,slug,name")
        .eq("slug", slug.strip().lower())
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


@router.get("/apply/{slug}", response_model=ApplyLandingResponse)
async def apply_landing(slug: str):
    """Public landing for /apply/{slug}.

    No auth — this is the URL a Company shares with candidates before
    they have an account. Returns just enough for the landing page to
    render: company id (so the frontend can pass it through signup),
    name, slug, and `signup_open`. A 404 is the only failure shape
    callers can observe.

    NOTE: slug enumeration is possible by design. The whole point of
    `/apply/{slug}` is that it's shareable; we can't 'hide' valid
    slugs from someone with a list. Rate-limiting + reCAPTCHA on the
    landing page belongs to a hardening pass, not the rollout.
    """
    supabase = get_supabase()
    company = _lookup_company_by_slug(supabase, slug)
    if company is None:
        raise HTTPException(status_code=404, detail="This apply link is not valid")
    return ApplyLandingResponse(
        company_id=company["id"],
        company_name=company["name"],
        slug=company["slug"],
        signup_open=True,
    )


@router.post("/auth/claim-company")
async def claim_company(body: ClaimCompanyRequest, user=Depends(get_current_user)):
    """Stamp `company_id` on the caller's profile.

    Called by the frontend after a candidate signs up from an apply
    link (Signup.tsx + AuthCallback.tsx). The flow:

      Candidate visits /apply/{slug} → clicks "Apply" → lands on
      /signup?company={slug} → completes signup → frontend POSTs here
      with the slug → backend stamps company_id on their profile.

    Idempotency / safety:
    - If the caller's profile already has `company_id` matching the
      slug, the call is a no-op success — safe to retry from the
      frontend without checking first.
    - If the caller already has a DIFFERENT `company_id`, return 403.
      We never silently move a candidate between tenants — that would
      be a real-world data integrity issue (someone applies to A, then
      a malicious B link they accept claims them as a B applicant).
    - If the slug doesn't resolve to a company, return 404 — same
      response shape as the public GET, so a stale invite-link can be
      surfaced consistently in the UI.

    The endpoint never widens role — a `recruiter` claiming a company
    via an apply link does NOT become a `company_admin`. Apply links
    are for candidates only. (A `recruiter` who clicks an apply link
    by mistake will hit the company_id-mismatch 403 if they already
    have a tenant.)
    """
    supabase = get_supabase()

    company = _lookup_company_by_slug(supabase, body.slug)
    if company is None:
        raise HTTPException(status_code=404, detail="This apply link is not valid")
    target_company_id = company["id"]

    # Re-fetch the caller's current company_id so we never make the
    # claim decision against a stale TenantContext. (The caller could
    # have refreshed their profile in another tab between the signup
    # and this call.)
    profile_rows = (
        supabase.table("profiles")
        .select("company_id")
        .eq("id", user.id)
        .execute()
        .data
        or []
    )
    current = profile_rows[0].get("company_id") if profile_rows else None

    if current is None:
        # Fresh claim — stamp the company.
        supabase.table("profiles").update({"company_id": target_company_id}).eq("id", user.id).execute()
        return {"claimed": True, "company_id": target_company_id}

    if current == target_company_id:
        # No-op — already a member. Surface 200 so the frontend can
        # retry without needing a pre-check.
        return {"claimed": False, "company_id": target_company_id, "reason": "already_member"}

    # Different tenant — never silently overwrite.
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Account already belongs to another company. Sign out and apply with a different email.",
    )
