# Company registration is self-contained in /companies/signup (amends ADR 0008 D1)

Status: accepted

## Context

ADR 0008 (Candidate signup is invite-only) settled which signup
*surfaces* are reachable, and in its D1 table routed the company
founder through the candidate form:

> | `?next=/companies/signup` | Company-founder signup form (existing — unchanged) |

That row described the actual implementation: `/companies/signup`
(signed out) rendered a CTA card whose **"Create account"** button
navigated to `/signup?next=/companies/signup`. The `/signup` component
then rendered a "founder" branch — *the same personal-account form the
candidate apply flow uses* — distinguished only by a title string and a
post-submit `navigate(next)`.

A 2026-05-30 manual walk surfaced the defect this produced: clicking
"Create account" in a company-setup context drops the founder onto a
form indistinguishable from candidate registration. The reporter read
it as *"company signup resolves into candidate registration."*

The friction is structural, not cosmetic. "How does a Company register?"
required bouncing across five modules — `CompanySignup`, `Signup`,
`Login`, `AuthCallback`, `safeNext` — wired together by the magic string
`?next=/companies/signup`. `/signup` was overloaded: it served candidate
apply, company founder, AND the invite-only explainer, gated by
query-param sniffing. CONTEXT.md already described the clean shape —
*"Company — Created via `/companies/signup` by a `'user'` who flips to
`'company_admin'`"* — with no glossary term for the "founder personal
account" intermediate, because that intermediate was an implementation
artifact, not a domain concept.

## Decision

### D1: The founder's admin account is created inside /companies/signup

The signed-out `/companies/signup` renders a dedicated, company-branded
**account form** (full name, work email, password, + Google OAuth) as
**step 1 of 2**. On success the session lands and the same component
re-renders into the existing **company-details form** (name, slug,
contact) as step 2. Both steps live in `CompanySignup` — company
registration is one self-contained module.

The backend contract is unchanged: `POST /api/companies/` still requires
an authenticated `role='user'` caller with `company_id IS NULL` and
flips them to `company_admin`. The account must exist before the company
can be created, so the flow is two-step — but both steps are one
coherent intake on one route, not a detour through `/signup`.

### D2: Two-step in one module, not a single combined form

A single form collecting account + company together and creating both on
one submit was rejected: when the Supabase project requires email
confirmation, no session exists at submit time, so the company cannot be
created in the same action. The two-step shape is robust to email
confirm (step 2 simply waits for the confirmed session) and reuses the
working company-create call verbatim.

### D3: /signup is candidate-only; the founder branch is removed

`/signup` now surfaces its form for exactly one intent — an applicant
who arrived via `/apply/{slug}` (`?company=slug`). The `?next=` reading,
the `isCompanyIntent` branch, the "founder account" title, and the
post-submit `navigate(next)` are deleted. A visit to
`/signup?next=/companies/signup` now falls through to the ADR 0008
invite-only explainer — but nothing links there anymore.

### D4: The /login round-trip is preserved for existing founders

A founder who already has an account uses "Already have an account?
Sign in →" → `/login?next=/companies/signup`. `Login` and `AuthCallback`
keep their `?next` handling (and `safeNext`) unchanged; only `Signup`
stops reading `next`. This is the one path where the round-trip still
earns its keep.

## Consequences

- `frontend/src/components/companies/CompanySignup.tsx` gains the step-1
  account form (state, `signUp` / Google handlers, the
  `/auth/callback?next=/companies/signup` redirect). The CTA card that
  detoured to `/signup` is gone.
- `frontend/src/components/auth/Signup.tsx` loses its founder branch and
  its `next` plumbing; `hasSignupIntent` is now just `Boolean(companySlug)`.
- `Login.tsx`, `AuthCallback.tsx`, `safeNext.ts` are unchanged.
- ADR 0008's D1 table row for `?next=/companies/signup` is superseded by
  this ADR (a pointer is added there).
- No backend change. No schema change. No new role string. Tenant
  scoping, capability gates (ADR 0006/0007), and the act-as composition
  are all untouched — preserving the stability/scalability constraints.
- CONTEXT.md is unchanged: no domain term shifted; the code now matches
  the existing "Created via /companies/signup" description.

## Open follow-ups (not decided here)

- **Backend signup gate (inherited from ADR 0008 D3).** Supabase Auth
  signup is still unauthenticated; the UI gate is the only barrier. A
  Supabase Auth hook / `pending_invites` table remains the hardening
  seam if abuse appears.
- **Google OAuth founder parity.** Carried over so the pivot doesn't
  regress it. If Google founder signups prove rare, the button can be
  dropped from step 1 without touching the email path.
