# Production Readiness Checklist

Single source of truth for taking the AI Mock Interview platform live, with the
ADR 0012 Resend email pipeline. Tracks what is **verified**, what is
**pending**, and what is **blocked**.

Legend: `[x]` done/verified · `[ ]` not done · `[~]` code-ready, needs live
verification.

Last updated: **2026-06-10** (post 403 investigation). Verification method:
read-only probes against the hosted Supabase DB (service key + `curl --resolve`)
+ unauthenticated probes of the deployed backend; interactive flows must be run
in a browser by an operator, then confirmed via the DB trace listed here.

---

## Current verified state (2026-06-10)

| Signal | Value |
|---|---|
| Backend (`interview-web-app.onrender.com`) | **Up** — `/health` 200, auth gating 401, webhook 401 fail-closed |
| Deployed commit | `origin/main` = **`b10530d`** (ADR 0012 only). **The 403 fix is NOT deployed** — it's on branch `fix/resend-403-invite-modal` (`52a3ff7`), unmerged. |
| `RESEND_API_KEY` | **Set + valid** — proven by the production 403 (the request *authenticated* at Resend; a bad key is 401). |
| `RESEND_FROM_EMAIL` | **Sandbox / unverified** — the cause of the 403: Resend only delivers from it to the account owner. **Verify a domain + set a real sender.** |
| `RESEND_WEBHOOK_SECRET` | **Set** (webhook returns 401, not 503) |
| Migration 010 | **Applied** (`email_events`, `email_suppressions`, new `email_outbox` columns all present) |
| `email_outbox` | 2 old `failed` rows; first real send returned **403** (sandbox sender) — no `sent` row yet |
| `email_events` / `email_suppressions` | 0 / 0 |
| `companies` | 1 (`Default` backfill sentinel) — **no real self-serve signup yet** |

**Headline:** schema is migrated, `RESEND_API_KEY` + `RESEND_WEBHOOK_SECRET` are
set, but **(a)** the 403 fix isn't merged/deployed and **(b)** `RESEND_FROM_EMAIL`
is the sandbox sender, so real invites 403. Both must close before the email
flow works end-to-end.

---

## A. Email pipeline (ADR 0012 / migration 010)

- [x] **Migration 010 applied** — verified: `email_outbox.idempotency_key/
  email_type/reply_to/last_event_at` present; `email_events` + `email_suppressions`
  tables exist.
- [x] **`RESEND_API_KEY` set + valid** — **verified 2026-06-10** indirectly: the
  first production invite reached Resend and got a **403** (authenticated), not a
  401. The key works.
- [ ] **`RESEND_FROM_EMAIL` = verified domain sender** — **THE 403 CAUSE.** It is
  currently the Resend sandbox sender (`onboarding@resend.dev`) or an unverified
  domain, which only delivers to the Resend account owner's address. **Fix:**
  verify a domain at resend.com/domains, set `RESEND_FROM_EMAIL` to an address on
  it on Render, redeploy. (Interim smoke test: invite the Resend-account-owner's
  own email — sandbox allows that and returns `sent`.)
- [x] **`RESEND_WEBHOOK_SECRET` set** — **verified 2026-06-10**: unsigned
  `POST https://interview-web-app.onrender.com/api/webhooks/resend` returns
  **401 "Invalid signature"** (not 503), proving the secret is set and
  signature verification is live + fail-closed.
- [ ] **Webhook registered in Resend + end-to-end event** — pending a real
  delivery (expect an `email_events` row after Section C-2).
- [ ] **First `status='sent'` + `email.delivered` event observed** end-to-end.
- [ ] `PLATFORM_FROM_NAME` / `EMAIL_RATE_LIMIT_PER_HOUR` reviewed (optional;
  defaults `Rehearsify` / `100`).
- [x] Suppression on hard bounce / complaint — code + unit tests in place;
  exercised once a real bounce/complaint webhook lands.

## A.1 In-flight fixes — branch `fix/resend-403-invite-modal` (`52a3ff7`, NOT merged)

- [ ] **Merge + deploy this branch.** Until then production serves `b10530d`
  (raw 403 string to users, old invite modal).
- [x] Friendly Resend error messages (403/401/422/429) replace the raw
  `HTTPStatusError` — backend code + tests done.
- [x] Readiness warning when `RESEND_FROM_EMAIL` is the sandbox sender — done.
- [x] Invite modal: sticky footer, max-height, Send/Cancel always visible — done.
- [x] `/health` now reports `commit` (Render `RENDER_GIT_COMMIT`) + `environment`
  — enables deploy verification. **After deploy, `/health.commit` must read
  `52a3ff7`.**

## B. Platform configuration (carried over from earlier checkpoints)

- [ ] **Supabase Auth SMTP** configured (signup confirmation email). Separate
  from Resend — this is Supabase's own mailer. Without it, email-confirm signups
  can't complete (Google OAuth is the no-email path).
- [ ] **`ENVIRONMENT=production`** on Render — arms the readiness gate's
  prod-only fatal rules (`app/readiness.py`).
  **⚠ CONFIRMED STILL `development` (verified 2026-06-10):** prod `/health`
  returns `"environment":"development"`, so the prod-only readiness checks are
  dormant. Set `ENVIRONMENT=production` on Render + redeploy; re-verify via
  `/health.environment`.
- [ ] **`FRONTEND_BASE_URL`** = real deployed frontend — invite links embed it.
- [ ] **CORS** `FRONTEND_ORIGIN_REGEX` anchored to the real prod frontend origin
  (currently may be the wildcard `*.vercel.app`).
- [ ] Backend boots cleanly with the above (check Render logs for the readiness
  report — no `[FATAL]`, warnings reviewed).

## C. End-to-end flow verification

Operator runs each step in a browser; then I confirm the DB trace.

- [ ] **1. Company signup** (`/companies/signup`) → new tenant.
  **Trace:** new `companies` row (slug/name/`created_by`); caller `profiles` row
  flips to `role='company_admin'` + `company_id`.
- [ ] **2. Invite a candidate** to an operator-controlled inbox.
  **Trace:** `email_outbox` row `email_type='invite'`, `status='sent'`,
  `resend_message_id` non-null → proves **A: Resend**. Email arrives. Within ~1 min
  an `email_events` `email.delivered` row → proves **A: webhook**.
- [ ] **3. Candidate registration + interview** via the apply link → signup →
  short interview to completion.
  **Trace:** new `candidate`, `interview` (→ `status='completed'`), and
  `evaluation` rows; report renders.
- [ ] **4. Shortlist / Reject email** from the recruiter candidate-detail page.
  **Trace:** `email_outbox` row `email_type='recruiter_outreach'`, `status='sent'`;
  re-clicking Send reuses the row (idempotency key) — no duplicate.
- [ ] **5. (Optional) Suppression** — reply/mark a test send as spam, or use a
  Resend test bounce address. **Trace:** `email_suppressions` row appears; a
  resend to that address yields `status='suppressed'`.

## D. Remaining blockers (prioritized)

1. **403 fix not merged/deployed** — branch `fix/resend-403-invite-modal`
   (`52a3ff7`) is unmerged; prod serves `b10530d`. Merge PR → redeploy →
   confirm `/health.commit == 52a3ff7`.
2. **`RESEND_FROM_EMAIL` is the sandbox sender → real invites 403** — verify a
   domain in Resend and set a real sender (Section A). The single thing blocking
   actual email delivery.
3. **Supabase Auth SMTP** unconfigured (signup confirmation email) — Section B.
4. **`ENVIRONMENT` is `development` in prod** — confirmed 2026-06-10 via
   `/health` (`"environment":"development"`). Set `ENVIRONMENT=production` on
   Render to arm the readiness gate. (`FRONTEND_BASE_URL` / CORS still to
   verify — Section B.)
5. **No real tenant in production** — only the `Default` sentinel company exists;
   Section C-1 has never run in prod.
6. **Platform-admin `/recruiter/analytics` "stall" — NOT a code bug** (revised
   2026-06-10 after measuring). Direct authed timing of all four endpoints
   against prod returned **200 in 1.4–3.2s** (funnel 3.2 / scores 2.3 /
   integrity 1.4 / summary 2.2). The earlier "Loading analytics…" was almost
   certainly a **Render free-tier cold start** (~50s spin-up on first hit after
   idle) outlasting the 15s screenshot wait — environmental, not the
   aggregations. Operational mitigation already exists: the UptimeRobot
   keep-alive pinging `/health` (keep it active). No code change made.
   - LATENT at scale (not today): `score_interviews_bulk` uses one
     `.in_(all_interview_ids)` query; for the None-tenant path this grows
     unbounded and could hit PostgREST URL-length limits / slow down at large
     interview counts. Revisit (chunk the `.in_`, or lazy-score) only when
     interview volume justifies it — premature against current tiny data.

Resolved since last revision: ~~Resend env unverified~~ (API key + webhook
secret now confirmed set); ~~production URL unknown~~ (`interview-web-app.onrender.com`).
NB: this checklist branch predates the email-fix + design-redesign + admin
company-overview deploys now on `main` (`5212e41`); items A.1 / D-1 about the
403 fix being unmerged are now SUPERSEDED (it shipped). Rebasing this doc onto
`main` is a follow-up.

## E. How verification is performed

Read-only DB probe (no writes), reused from the diagnosis sessions:

```
# service key from backend/.env; host pinned to a public-DNS IP to bypass any
# stale local resolver for the (resumed) Supabase project.
curl --resolve <host>:443:<ip> \
  -H "apikey: $SUPABASE_KEY" -H "Authorization: Bearer $SUPABASE_KEY" \
  "https://<host>/rest/v1/email_outbox?select=status,email_type,resend_message_id,sent_at&order=sent_at.desc"
```

Deployed-build + webhook checks (no auth):

```
curl -s https://interview-web-app.onrender.com/health
# -> {"status":"healthy","commit":"<sha>","environment":"<env>"}
# after deploy, commit must read 52a3ff7 (until then it is 'unknown' on the old build)

curl -i -X POST https://interview-web-app.onrender.com/api/webhooks/resend -d '{}'
# -> 401 "Invalid signature" (secret set; 503 would mean secret missing)
```

---

### Definition of done

All boxes in A, B, C ticked; one real candidate has gone invite → interview →
report → shortlist email, with the matching `email_outbox` (`sent`) and
`email_events` (`delivered`) rows observed.
