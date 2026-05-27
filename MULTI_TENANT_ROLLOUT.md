# Multi-Tenant Companies + Email Outreach — Incremental Rollout

**Status:** Grills resolved 2026-05-27. PR 0 (migration 004) is the
next thing to ship. No code shipped yet.

**Phase posture:** This is a **phase exception** within the declared
stability + scalability phase (see `CURRENT_TASKS.md` and the
`project_stability_scalability_phase` memory). User explicitly
overrode the "no large new feature branches" rule on 2026-05-27 with
acknowledgment that this is a multi-PR rollout.

Same posture as the previous recruiter rollout (see
`RECRUITER_ROLLOUT.md`): incremental, additive, each PR ships
independently in an existing-system-shaped commit. No rewrites of
stable code (voice/realtime pipeline, scoring helpers, integrity
write path, scoring tests).

---

## Product shape

What's being added on top of today's system:

1. **Companies as first-class tenants.** A new `companies` table; every
   profile, candidate, interview, and recruiter_decision row is scoped
   to a `company_id`. Tenant isolation is enforced at the RLS layer
   and re-checked in every backend handler.
2. **Self-serve company signup.** Anyone visits `/companies/signup`,
   creates a company, and becomes its `company_admin`. (Anti-abuse —
   email verification + rate limit — deferred to a hardening pass.)
3. **Public application link.** Each company gets a shareable URL
   `/apply/{company-slug}`. Visiting it lands on a candidate-signup
   page that auto-stamps the candidate with the company's `company_id`
   on account creation. No auth required to view the apply page.
4. **Company-scoped admin dashboard.** A `company_admin` sees only
   their own company's candidates / interviews / analytics. The
   existing platform-wide `admin` role (super-admin, internal ops) is
   preserved — they see everything.
5. **Shortlist / reject + email outreach.** When the admin shortlists
   a candidate, a composer modal opens with a default templated email
   (subject + body). Admin edits and clicks **Send** — human-in-the-loop.
   Sent via Resend. Send action is audit-logged.

---

## What the existing system already has (and what changes)

| Capability today | After rollout |
|---|---|
| Global `admin` role (sees everything) | Preserved as platform super-admin. Renamed in docs to `platform_admin`; DB value stays `admin` (no schema churn). |
| Global `recruiter` role (sees all candidates) | Either (a) **becomes company-scoped** — same role, but `company_id` filters their view; or (b) gone, subsumed by `company_admin`. Grill C2 below. |
| `user` role (B2C interview practice) | Either kept as a parallel non-company flow, or removed. Grill C1 below. |
| `recruiter_decisions` table | Reused as-is; `recruiter_id` becomes `actor_id` semantically. Decision rows naturally gain tenant scope via candidate's `company_id`. |
| Public signup at `/signup` | Stays for the existing flow (whichever survives C1). Apply-link signup is a separate route. |
| Existing data | Backfilled into a single "Default" company so all current candidates / interviews stay visible. Grill A1 below. |

---

## Grill resolutions (12 decisions — settled 2026-05-27)

| # | Decision | Resolution | Why |
|---|---|---|---|
| A1 | Backfill posture for existing data | **Default company.** Create a single "Default" company; backfill every existing row into it; `company_id` becomes NOT NULL. | Preserves existing test data + recruiter-rollout seed. No data loss. One-line `INSERT ... SELECT` to backfill. |
| A2 | Tenant isolation enforcement | **Backend + RLS, both.** Backend always filters by `caller.company_id` (primary enforcement, since the service-role key bypasses RLS). RLS policies added as defense-in-depth for any future direct-client read path. | Mirrors today's auth posture: backend is authoritative, RLS is a safety net. |
| A3 | `company_id` placement | **Denormalise everywhere.** Add `company_id` to candidates, interviews, evaluations, recruiter_decisions, integrity_events. | Candidate's company never changes (no update path), so the denorm is safe. One-hop filter is faster + simpler than join chains. RLS policies stay table-local. |
| C1 | Does B2C `user` flow survive? | **Both coexist.** `role='user' AND company_id IS NULL` = B2C self-directed candidate (existing flow). `role='user' AND company_id IS NOT NULL` = B2B applicant who arrived via /apply/{slug}. **No new role string for applicant** — the `company_id` predicate distinguishes them. | Avoids destruction of existing B2C product surface. No CHECK constraint churn — applicant is just a `user` with a company. |
| C2 | Existing global `recruiter` role | **Becomes `company_recruiter`** (tenant-scoped). Existing recruiter profiles migrate to `company_recruiter` of the Default company. Two tiers per tenant: `company_admin` (settings + signup + everything recruiter does) and `company_recruiter` (reviews candidates only). | Mirrors Lever/Greenhouse ATS shape. Keeps the recruiter rollout that just shipped functional — only its scope narrows from global to tenant-local. |
| C3 | Super-admin (existing `admin` role) | **Stays platform-wide.** `role='admin'` keeps unconditional cross-tenant access; `company_id` is NULL for admins. Docs call this `platform_admin`; DB value stays `admin` (no schema churn). | Operational necessity — you (the deployer) need to debug across tenants. Treating admin as a tenant adds friction without product value. |
| L1 | Apply link URL shape | **Human slug** at `/apply/{slug}`. Company picks the slug at signup; UNIQUE constraint enforces collisions. If a slug is leaked/abused, the company picks a new one (URL break is acceptable — abuse is rare). | Memorable + shareable. UUID hedge deferred until the first real abuse appears. |
| L2 | One link per company or job-specific? | **One link per company** for the rollout. | Job postings are a child concept that can be added later as `/apply/{slug}/{job}` without breaking the existing slug. Scope-control move. |
| E1 | Resend from-email | **Sandbox sender as default** (`onboarding@resend.dev`). Code reads `RESEND_FROM_EMAIL` env var with sandbox as the fallback. | Unblocks the email feature end-to-end without DNS work. Real domain verification (SPF/DKIM) becomes an infra task, not a code blocker. |
| E2 | Email templates | **Platform-wide default**, editable per-send in the composer. Default lives in `services/email_templates.py`. | Per-company templates need a table + settings UI for a customization most early admins won't ask for. Additive follow-up. |
| E3 | Draft persistence | **Client-side only.** Composer holds edits in React state; closing the tab loses them. | No draft table, no autosave endpoint, no conflict handling. Add server-side drafts when a real user complains. |
| E4 | Audit log shape | **Full body in outbox.** `email_outbox` stores subject + body + recipient + sender + sent_at + resend_message_id. | Reproducible from DB alone — no Resend API dependency to view a sent email. PII duplication is acceptable for an audit log that's already in the same DB as the candidate row. |

### Sub-resolutions (recorded for reference)

- **Role CHECK constraint** after the rollout:
  `role IN ('user', 'recruiter', 'admin', 'company_admin', 'company_recruiter')`.
  The existing `'recruiter'` value is kept *temporarily* during the
  migration window — PR 1 migrates all `'recruiter'` rows to
  `'company_recruiter'`, after which the value is dropped from the
  CHECK in PR 2.
- **`company_id` nullability:** NULL for `role='admin'` (platform
  super-admin) and `role='user' AND no company` (B2C). NOT NULL for
  every other role.
- **B2C applicant onboarding via apply link:** the SAME `/signup`
  endpoint handles both flows; the only difference is whether the
  signup URL carries a `?company=slug` query param. If yes, the new
  profile gets stamped with that `company_id` on creation. If no, it's
  a B2C signup.

### Architecture / data model

**A1. Backfill posture for existing data.**
Existing candidates / interviews / profiles have no `company_id`.
Options: (i) create a "Default" / "Legacy" company and assign
everything to it; (ii) require migration to make every row
`company_id NOT NULL`; (iii) allow `company_id NULL` indefinitely
(no tenant scoping for legacy rows).

**A2. RLS strategy.**
How is tenant isolation enforced? Options: (i) Supabase RLS policies
on every domain table using `auth.jwt() -> 'company_id'` — but our
backend uses the service-role key, which bypasses RLS, so this is
defense-in-depth only; (ii) backend always filters by
`company_id = caller.company_id` in every query — primary enforcement;
(iii) both — RLS for direct-from-frontend reads (which currently
don't exist — all reads go through backend), backend filters for the
service-role-key path.
Default direction: **(iii)**. Same posture as today's RLS.

**A3. `company_id` placement on `interviews` and `evaluations`.**
Candidate already has `company_id`; interview has `candidate_id`;
evaluation has `interview_id`. Strictly we could derive tenant from
the candidate FK. But denormalising `company_id` onto every domain
row makes filters one-hop (`WHERE company_id = X`) instead of a join,
and lets RLS policies be table-local. Trade-off: a candidate's
company can never change (it can't), so denorm is safe.
Default direction: **denormalise** on candidates, interviews,
evaluations, recruiter_decisions, interview_integrity_events.

### Roles & access

**C1. Does the existing B2C `user` flow survive?**
Today `role='user'` is a candidate practicing interviews on their own
(no company, no recruiter outreach). Two options:
(i) **Keep it.** B2C and B2B coexist; a `user` has no `company_id`;
the apply-link flow creates a *separate* row class
(`role='applicant'`?) bound to a company.
(ii) **Remove it.** All candidates are company-scoped applicants.
Existing user-role rows backfill into the Default company as
applicants.
Default direction: **(i) — keep both**, because (ii) is destructive
of existing data semantics and we have no signal that B2C should die.

**C2. What happens to the existing global `recruiter` role?**
Three options:
(i) **Subsumed by `company_admin`.** A company has one role tier
(admin); recruiter as a separate global role is dropped. Existing
recruiter profiles migrate to `company_admin` of the Default company.
(ii) **Becomes company-scoped recruiter.** A company can have both
`company_admin` (manages settings + signs up) and `company_recruiter`
(reviews candidates, can't manage company). Two tiers per tenant.
(iii) **Kept as global platform-wide recruiter** — sees ALL candidates
across ALL companies (super-recruiter). Unlikely product fit.
Default direction: **(ii)** — two tiers per company. Mirrors how
real ATS products work. Costs one extra role string + a minor auth
matrix entry; gains real per-tenant team semantics.

**C3. Super-admin (`platform_admin`) — what can they see?**
Today's `admin` role sees everything globally. After the rollout, do
they keep that or do they need to be in a company too? Default: **keep
unconditional access**, treat them as platform operators (you, the
deployer), not tenants.

### Application link

**L1. Slug shape.**
Options: (i) `/apply/{slug}` where slug is a human chosen string at
signup ("acme"); (ii) `/apply/{uuid}` opaque token; (iii) both —
slug is the canonical URL, uuid is a regenerable backup if slug ever
gets leaked / abused.
Default direction: **(i)** — slug only, with uniqueness check at
signup; revocable + regeneratable later if abused (grill cost: a new
column when the abuse appears, not now).

**L2. Multiple links per company / job-specific links.**
Single company → single shareable link, or one-link-per-job-posting?
Default direction: **single link per company** for the rollout. Job
postings can be added later as a child table (`/apply/{slug}/{job}`)
without breaking the single-slug URL.

### Email

**E1. Resend setup.**
You confirmed Resend. Required env vars: `RESEND_API_KEY`,
`RESEND_FROM_EMAIL` (verified sender domain). The from-domain
verification step is a manual DNS task — not blocking the code, but
blocking real email delivery. Default-from for development:
`onboarding@resend.dev` (Resend's sandbox sender, free, no DNS).

**E2. Templates — per-company or platform-wide?**
For the rollout: **platform-wide default**, editable per-send in the
composer. Per-company template storage is a deferred follow-up
(needs a `company_email_templates` table + a settings UI).

**E3. Drafts persistence — yes or no?**
When the admin opens the composer, do edits autosave to a server-side
draft (so a closed tab doesn't lose work)? Or is it pure
client-side until **Send**?
Default direction: **pure client-side draft**. Server-side draft adds
a table + endpoints for a feature most users won't trigger. Add it
when it's actually missed.

**E4. Audit log shape.**
Every `Send` writes an `email_outbox` row with subject + body +
recipient + sender (admin user_id) + candidate_id + sent_at + Resend
message_id. Read endpoint: the candidate detail page shows a list of
emails sent to that candidate. **Decision: keep the body in the
audit row** so a sent email is reproducible from the DB without
hitting Resend's API. Trade-off: PII duplication.

---

## Implementation contract — provisional 8-PR sequence

Each PR is one sub-day session, ships independently, ends with green
CI + `CHANGE.md` entry. Sequencing is mostly serial — a few branches
are flagged.

### PR 0 — Migration 004: `companies` + tenant-id columns (data layer only)

**Status:** Shipped 2026-05-27 (commit on `main`). ADR 0005 added.
Backend imports + 160/160 pytest pass post-migration-file landing
(no app code changed). Migration SQL not yet executed against
Supabase — user runs it in the SQL editor manually.

**Scope:** SQL only. No backend code change. No behavior change.
- New table `companies` (`id uuid pk`, `slug text unique`, `name text`,
  `created_by uuid`, `created_at`).
- Add nullable `company_id uuid references companies(id)` to:
  `profiles`, `candidates`, `interviews`, `evaluations`,
  `recruiter_decisions`, `interview_integrity_events`.
- Seed a "Default" company; backfill `company_id` on all existing
  rows. Decision A1.
- RLS policies on `companies` itself only (read = members, write =
  no one yet). Domain-table RLS lands in PR 1.

**Verification:** Migration runs cleanly in a fresh Supabase; existing
backend imports + tests pass unchanged.

### PR 1 — Backend tenant scoping (admin + recruiter endpoints)

**Status:** Shipped 2026-05-27 (commit on `main`). Backend pytest 177/177
(160 prior + 17 new cross-tenant isolation cases).

**Scope:**
- Extend `get_current_user` to attach `company_id` from the
  authenticated profile.
- Every read in `routers/admin.py` and `services/recruiter.py` /
  `recruiter_analytics.py` gets `.eq("company_id", caller.company_id)`
  added — except when the caller is `platform_admin` (decision C3).
- Tests: add pytest cases that confirm a `company_admin` of Company A
  cannot read Company B's candidates / interviews / decisions.

**Verification:** Existing admin/recruiter tests still pass after the
backfilled "Default" company is set as the test caller's tenant.

### PR 2 — Backend tenant scoping (dashboard + interviews + reports + WS)

**Status:** Shipped 2026-05-27 (commit on `main`). 188/188 pytest pass
(177 prior + 11 new). Also closed three pre-existing unauthenticated
GET endpoints on `/api/interviews/{id}*` that the frontend uses; two
PATCH endpoints flagged as TODO (unused dead code).

Same shape as PR 1 but for `routers/dashboard.py`, `routers/interviews.py`,
`routers/reports.py`. Plus the WS handler (`routers/interview_session.py`)
verifies the candidate's `company_id` matches the caller's on connect.

### PR 3 — Self-serve company signup

**Status:** Shipped 2026-05-27 (commit on `main`). 195/195 pytest pass
(188 prior + 7 new); frontend tsc green. Migration 005 ships in the
same PR; user runs it in the Supabase SQL editor before the endpoint
is functional.

**Scope:** backend + frontend.
- Backend `POST /api/companies` — creates a company + flips the
  caller's role to `company_admin`, stamps their `company_id`. One
  caller can create one company at a time (server-side guard).
- Frontend `/companies/signup` page — form with company name + slug,
  validates uniqueness, redirects to `/admin` on success.
- `ProtectedRoute` learns the `company_admin` role and routes
  accordingly.

### PR 4 — Public apply route (no-auth landing) + company-scoped signup

**Status:** Shipped 2026-05-27 (commit on `main`). 203/203 pytest pass
(195 prior + 8 new); frontend tsc green. No migration needed — uses
existing `companies.slug` + `profiles.company_id` columns from
migrations 004/005.

**Scope:**
- Backend `GET /api/apply/{slug}` — public, returns
  `{company_name, company_id, signup_open: bool}`. 404 on unknown
  slug.
- Frontend `/apply/{slug}` page — no-auth landing showing
  company name + "Apply" CTA → standard signup flow with
  `company_id` query param threaded through.
- Backend signup handler (already exists via Supabase Auth) — after
  account creation, if the redirect URL carries the apply slug, stamp
  `company_id` on the new profile.

### PR 5 — Company-admin dashboard view + Settings

**Status:** Shipped 2026-05-27 (commit on `main`). 207/207 pytest pass
(203 prior + 4 new); frontend tsc green. No migration needed.

**Scope:** frontend mostly, plus one tiny backend endpoint.
- Existing `AdminDashboard` already aggregates platform-wide. The
  backend filter from PR 1 already restricts the response by
  company_id. So this PR is mostly: route a `company_admin` to a
  *company-scoped* version of the existing dashboard (maybe just a
  banner "Showing data for {company_name}").
- Settings page stub — `/admin/settings` shows the shareable apply
  link + a copy button.

### PR 6 — Email service module + outbox migration

**Scope:** backend only.
- Migration 005: `email_outbox` table (id, company_id, candidate_id,
  to_email, subject, body, sender_id, sent_at, resend_message_id,
  status).
- `services/email.py` — Resend client wrapper:
  `send(to, subject, body, sender) -> outbox_row`. Async via
  `asyncio.to_thread` (mirrors the Groq pattern from PR 7).
- `services/email_templates.py` — `default_shortlist_template(candidate, company)` returns
  `{subject, body}`.
- Env vars: `RESEND_API_KEY`, `RESEND_FROM_EMAIL` (with sandbox
  fallback for dev). Documented in `.env.example`.

### PR 7 — Email endpoints + composer UI

**Scope:** backend + frontend.
- Backend `GET /api/recruiter/candidates/{id}/email/draft` — returns
  the template-rendered draft for the shortlist action.
- Backend `POST /api/recruiter/candidates/{id}/email/send` — accepts
  subject + body in the body, calls `services.email.send`, writes
  outbox row, returns it.
- Backend `GET /api/recruiter/candidates/{id}/emails` — lists prior
  outbox rows for the candidate detail page.
- Frontend composer modal — opens when admin clicks "Shortlist + email"
  on the candidate detail page; fetches the draft; lets admin edit
  subject + body; "Send" calls the endpoint; success toast + list
  refresh.

---

## How to pick up next session

1. Draft `docs/adr/0005-multi-tenant-companies.md` capturing A1, A2,
   A3 — the irreversible schema-level decisions. (One short ADR; the
   resolutions table above carries the why.)
2. Ship PR 0 (migration only). Verify on a fresh Supabase.
3. Ship subsequent PRs in sequence — each in its own session.

Documentation updates that happen AS the rollout progresses:

- After PR 0: extend `CONTEXT.md` with the new domain terms (Company,
  Tenant, Apply Link, Company Admin, Company Recruiter, Platform Admin,
  Email Outbox).
- After PR 3 (when `company_admin` role string lives in the DB):
  update `CLAUDE.md`'s role list. Don't update preemptively.
- After PR 6: document the Resend env vars in `.env.example` +
  `PROJECT_STATE.md`.
