# Candidate signup is invite-only (amends MULTI_TENANT_ROLLOUT grill C1)

Status: accepted

## Context

`MULTI_TENANT_ROLLOUT.md` grill C1 (settled 2026-05-27) preserved a
B2C self-directed Candidate flow alongside the B2B applicant flow:

> *C1: Does B2C user flow survive? Both coexist. `role='user' AND
> company_id IS NULL` = B2C self-directed Candidate. `role='user'
> AND company_id IS NOT NULL` = B2B applicant who arrived via
> `/apply/{slug}`. No new role string for applicant.*

The 2026-05-29 product review reversed this. The platform is B2B-
only: a Candidate's pathway into the system MUST originate at a
registered Company. The B2C "self-directed practice" path is closed.

Two surviving Candidate entry points after this ADR:

1. **Apply Link** — `/apply/{slug}` (broadcast URL the Company
   shares). Click "Apply now" → `/signup?company={slug}` → account
   is created with `company_id` stamped on first session.
2. **Invite email** — a per-Candidate email sent via
   `POST /api/companies/invite`. The email body contains the
   Company's Apply Link, so the in-product path collapses onto (1).

There is no third way for a `user` profile to exist with a
NULL `company_id` from this date forward. Existing rows with the
pre-pivot shape are grandfathered.

## Decision

### D1: `/signup` without an intent renders an explainer, not a form

The `/signup` route now branches on the URL's query string:

| Query state | Render |
|---|---|
| `?company={slug}` | Apply-link signup form (existing — unchanged) |
| `?next=/companies/signup` | Company-founder signup form (existing — unchanged) |
| no recognized intent | Explainer card: "This platform is invite-only. Ask your hiring company for an Apply Link, or set up your own company." |

The form is unreachable from a fresh visitor's perspective. The
discoverability links on `/login` no longer expose a generic
"Create one" CTA — only the "Setting up your company? Create one →"
remains, because that path leads to `/companies/signup` which DOES
allow signup via the `next` round-trip from D6.

### D2: Existing B2C accounts are grandfathered

The 9 `role='user', company_id=NULL` profiles on the platform at the
time of this pivot continue to work. No data migration. No forced
re-assignment. The gate applies prospectively to NEW signups only.

Migration 004's backfill (created 2026-05-27) had already stamped
those accounts as members of the "Default" company; the `company_id`
column was set to the Default UUID for all `user` rows in the same
operation. So in practice "B2C account" is a historical concept
post-rollout — every existing user already has a `company_id`. The
gate is for FUTURE signups that would have produced a fresh NULL.

### D3: Backend enforcement is deferred; the gate is UI-only for now

The Supabase Auth signup endpoint is unauthenticated by design — any
client (a `curl`, a malicious script) can create a Supabase Auth
user. The backend's auto-create branch in `/api/auth/me` would then
mint a `profiles` row with `role='user', company_id=NULL` for any
such caller, bypassing the UI gate.

For this rollout: accept the gap. The UI is the only natural path
to signup, and a user who curls Supabase Auth directly to create
an orphaned account gets a B2C-shaped profile that exists but has
no UI to surface it (no nav, no dashboard data, no recruiter
visibility). They are effectively dormant.

Future hardening (deferred to a separate ADR):

- A Supabase Auth hook that rejects signup if no `company` slug or
  invite token is present in `user_metadata`.
- An invite-token table (`pending_invites`) that the
  `POST /api/companies/invite` flow writes to, and that the signup
  flow looks up to validate the recipient email.

### D4: No new role; no new column

The pivot does NOT introduce a `role='applicant'`, a `role='guest'`,
or a `pending_signup` boolean. Capability predicates and the
TenantContext shape are unchanged. The change is entirely about
which surfaces are *reachable* from a fresh visitor's perspective.

This keeps the capability module (ADR 0006), the route-level
capability gating (ADR 0007), and the act-as composition all
unchanged. The seam where the pivot lands is **the Signup
component's render-branch logic** — one component, one decision.

## Consequences

- `frontend/src/components/auth/Signup.tsx` learns a third branch:
  no-intent → explainer card. Title + body + CTAs.
- `frontend/src/components/auth/Login.tsx` drops the "Don't have an
  account? Create one →" link. The remaining "Setting up your
  company?" link stays as the only signup-discovery entry point on
  the login page.
- `MULTI_TENANT_ROLLOUT.md` grill C1 is amended in scope. The
  resolution table entry stays as a historical record; a pointer to
  this ADR is the read-side cue that the decision moved.
- `CONTEXT.md`'s **Candidate** entry no longer needs to qualify
  "B2C if company_id is null" — every Candidate post-pivot has a
  Company. The historical caveat about pre-pivot rows can move to
  a footnote.

## Open follow-ups (not decided here)

- **Backend gate (D3 hardening).** Adding a Supabase Auth signup
  hook OR a `pending_invites` table is its own scope. Pick when
  abuse is observed.
- **Invite token vs Apply Link.** Today an Invite email body just
  contains the Apply Link URL — anyone who intercepts the email can
  follow that URL and create an account with a different email.
  Tightening invites to single-use tokens bound to a specific email
  is the natural next step if email security matters more than
  current friction.
- **Existing-B2C UX.** The 9 grandfathered users currently have
  `company_id` = Default. They appear in Default's recruiter list
  as "candidates of Default." If that's not the right home for them
  semantically, an admin action moves them — but that's an ops
  task, not a code change.
