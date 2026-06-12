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
  `company_id IS NULL`. Never overwrites an existing tenant — a
  candidate who already belongs to a company instead gets an ACCEPTED
  row in the `candidate_invitations` ledger (migration 011), which is
  how one candidate holds membership in multiple companies.

Why two endpoints, not one combined: the public landing page reads
company info BEFORE the user creates an account; the claim happens
AFTER. They share the slug lookup but live in different auth contexts.
"""
from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_user
from app.models.schemas import ApplyLandingResponse, ClaimCompanyRequest
from app.services.invitations import ensure_accepted_membership
from app.supabase_client import get_supabase

router = APIRouter()


def _lookup_company_by_slug(supabase, slug: str):
    """Return the company row matching `slug`, or None.

    Lowercases the input for safety. The DB index on `companies.slug`
    is case-sensitive (Postgres default text); the slug regex enforced
    on creation guarantees lowercase, so this normalisation is
    defense-in-depth against a future ALTER that loosens the regex.

    Contact columns (email/phone/address — PR 8) are selected so the
    public apply landing can surface them. They're optional in
    response rendering — a missing column on a pre-PR-8 row degrades
    to empty strings.
    """
    rows = (
        supabase.table("companies")
        .select("id,slug,name,email,phone,address")
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
        company_email=company.get("email") or "",
        company_phone=company.get("phone"),
        company_address=company.get("address"),
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
    - If the caller (a candidate, `role='user'`) already belongs to a
      DIFFERENT company, the claim is recorded as an ACCEPTED
      INVITATION in the `candidate_invitations` ledger (migration 011)
      instead of being rejected. `profiles.company_id` is never
      overwritten — it stays the candidate's first/primary tenant —
      but the candidate can now also interview for the new company.
      This is what lets one candidate hold invitations from multiple
      companies without conflict.
    - If the slug doesn't resolve to a company, return 404 — same
      response shape as the public GET, so a stale invite-link can be
      surfaced consistently in the UI.

    The endpoint never widens role — a `recruiter` claiming a company
    via an apply link does NOT become a `company_admin`. Apply links
    are for candidates only: a tenant-scoped hiring role (`recruiter` /
    `company_admin`) clicking another company's apply link still gets
    the 403 (their account belongs to the tenant they work for).
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
        .select("company_id,role")
        .eq("id", user.id)
        .execute()
        .data
        or []
    )
    current = profile_rows[0].get("company_id") if profile_rows else None
    role = (profile_rows[0].get("role") if profile_rows else None) or "user"
    email = getattr(user, "email", "") or ""

    if current is None:
        # Fresh claim — stamp the company as the candidate's primary
        # tenant, and mirror it into the invitation ledger so "my
        # invitations" reflects the membership.
        supabase.table("profiles").update({"company_id": target_company_id}).eq("id", user.id).execute()
        ensure_accepted_membership(
            supabase, company_id=target_company_id, email=email, user_id=user.id
        )
        return {"claimed": True, "company_id": target_company_id}

    if current == target_company_id:
        # No-op — already a member. Surface 200 so the frontend can
        # retry without needing a pre-check.
        ensure_accepted_membership(
            supabase, company_id=target_company_id, email=email, user_id=user.id
        )
        return {"claimed": False, "company_id": target_company_id, "reason": "already_member"}

    if role == "user":
        # Candidate with an existing primary tenant claiming a second
        # company: membership via the invitation ledger. The primary
        # company_id is intentionally untouched.
        ensure_accepted_membership(
            supabase, company_id=target_company_id, email=email, user_id=user.id
        )
        return {"claimed": True, "company_id": target_company_id, "via": "invitation"}

    # Hiring roles never hop tenants via an apply link.
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This account manages a different company and cannot apply as a candidate.",
    )
