# Multi-Tenant Companies + Email Outreach — Incremental Rollout

**Status:** Planning. Open grill questions below. No code shipped yet.

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

## Open grill questions (settle BEFORE PR 0 ships)

These are blocking — no code lands until each one has a recorded
resolution, just like the 12 recruiter grills were recorded.

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

**Status:** Not started. Blocks every later PR.

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

### PR 2 — Backend tenant scoping (dashboard + interviews + reports)

Same shape as PR 1 but for `routers/dashboard.py`, `routers/interviews.py`,
`routers/reports.py`. Plus the WS handler (`routers/interview_session.py`)
verifies the candidate's `company_id` matches the caller's on connect.

### PR 3 — Self-serve company signup

**Scope:** backend + frontend.
- Backend `POST /api/companies` — creates a company + flips the
  caller's role to `company_admin`, stamps their `company_id`. One
  caller can create one company at a time (server-side guard).
- Frontend `/companies/signup` page — form with company name + slug,
  validates uniqueness, redirects to `/admin` on success.
- `ProtectedRoute` learns the `company_admin` role and routes
  accordingly.

### PR 4 — Public apply route (no-auth landing) + company-scoped signup

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

### PR 5 — Company-admin dashboard view

**Scope:** frontend only, mostly.
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

## How to pick up after the user grills the open questions

1. Resolve grills A1, A2, A3, C1, C2, C3, L1, L2, E1, E2, E3, E4
   (12 in total, mirroring the recruiter rollout).
2. Once all resolved, update this document with the resolutions (same
   format as `RECRUITER_ROLLOUT.md`'s "Grill resolutions" table).
3. Draft `docs/adr/0005-multi-tenant-companies.md` capturing the
   schema-level decisions (A1, A2, A3) — the irreversible ones.
4. Ship PR 0 (migration only). Verify.
5. Ship subsequent PRs in sequence.

`platform_admin` documentation: update `CLAUDE.md`'s role list once
the rollout is on PR 3 (when the new role string exists in the DB).
Don't update it preemptively.
