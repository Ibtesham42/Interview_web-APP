# Company onboarding data model + email-verification posture

Status: accepted

## Context

Manual onboarding testing (2026-05-30) surfaced two gaps after the
self-contained `/companies/signup` flow landed (ADR 0009):

1. **Signup confirmation email never arrives.** Founders see "check your
   email" but no mail comes.
2. **The registration form is thin.** It collected name / slug / contact
   email / phone / single-line address. A fuller business profile was
   wanted: founder name, a display handle, structured address (city /
   state / country / pincode), website, company size, plus confirm-
   password and a show/hide toggle.

A field list was proposed that included **"username"**. The platform's
identity is **email-based** (Supabase Auth = email + password), and
CONTEXT.md deliberately avoids "User" as a domain actor — so "username"
needed a decision, not a straight add.

## Decision

### D1: Email verification is a Supabase-config issue, not a code change

The signup confirmation email is sent by **Supabase Auth**, configured in
the hosted dashboard — entirely separate from this app's Resend outbox
(`services/email.py`, which only sends candidate invites + shortlist
mail). The missing email is caused by the hosted project having
confirmation ON with **no custom SMTP**, so the built-in, rate-limited
sender is used.

Chosen posture: **keep email confirmation ON and configure custom SMTP**
(Resend's SMTP endpoint) rather than disabling confirmation. Verification
stays intact; delivery becomes reliable. The dashboard steps + the
localhost/inbucket-vs-production differences are documented in
[`docs/SUPABASE_AUTH_EMAIL.md`](../SUPABASE_AUTH_EMAIL.md). No application
code change is required for delivery; the signup flow already handles both
the confirm-email path and the immediate-session path.

### D2: "Username" is a cosmetic display handle, not an identity

`username` becomes a **nullable, optional `profiles.username` column** —
a display handle only. It is **NOT** a login identifier (Supabase Auth
has no native username login; a lookup shim would be a significant, risky
change to the auth path), and it is **NOT** a new domain concept (no
CONTEXT.md term — login is still by email; the founder's name is already
captured as `full_name`). It is collected at account creation and threaded
through Supabase `user_metadata` into the `handle_new_user` trigger and
the `/api/auth/me` auto-create fallback.

Rejected alternatives: drop it entirely (the field was explicitly
requested); make it a login identifier (auth rework, high risk).

### D3: Structured address columns, not a single text blob

`companies` gains `city`, `state`, `country`, `postal_code` columns
beside the existing street `address`, plus optional `website` and
`company_size`. All nullable/optional. Structured columns (over keeping a
single `address` textarea) enable future per-tenant filtering/display and
match the requested form shape. The cost is one additive migration
(`008`) — the existing Default seed row and every current row stay valid
because every new column is nullable.

### D4: Confirm-password + show/hide are frontend-only

Password confirmation (client-side equality check) and the show/hide
toggle are pure UI. No schema, no backend, no API change — they live
entirely in `CompanySignup` step 1.

## Consequences

- **Migration 008** (additive): `companies` + the six new columns;
  `profiles.username`; `handle_new_user` trigger updated to copy
  `username` from `user_metadata` (idempotent `create or replace`).
- **Backend:** `CompanyCreate` / `CompanyResponse` gain the six company
  fields; `create_company` persists + returns them via a new shared
  `_company_response` mapper (single source of truth, so a new column
  surfaces from every read at once). `/api/auth/me` adds `username` to
  both the auto-create row and the response dict.
- **Frontend:** `CompanySignup` step 1 adds username + confirm-password +
  show/hide; step 2 adds the structured address + website + company-size
  fields. `AuthContext.signUp` threads `username` through metadata. The
  `Profile` + `Company` types and the `companiesApi.create` payload gain
  the new fields.
- **Tenant scoping, roles, capability gates (ADR 0006/0007), the
  self-contained signup flow (ADR 0009), and all realtime/voice code are
  UNCHANGED.** The change is additive columns + form fields.
- **CONTEXT.md is unchanged** — `username` is a cosmetic attribute, not a
  domain concept, and the new company fields are attributes of the
  existing **Company** term. The glossary stays a glossary.

## Operational note

Migration 008 must be applied in the Supabase SQL editor (after 007), and
custom SMTP must be configured in the dashboard, before the new onboarding
behaves end-to-end in a deployed environment.

## Open follow-ups (not decided here)

- **Website / company_size validation.** Both are free-form today. URL
  shape validation + a fixed company-size enum are easy follow-ups if the
  data needs to be queryable/consistent.
- **Backend signup gate (inherited from ADR 0008 D3 / 0009).** Supabase
  Auth signup is still unauthenticated; the UI is the only gate.
