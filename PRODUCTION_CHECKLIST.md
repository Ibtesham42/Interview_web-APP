# Production Readiness Checklist

Single source of truth for taking the AI Mock Interview platform live, with the
ADR 0012 Resend email pipeline. Tracks what is **verified**, what is
**pending**, and what is **blocked**.

Legend: `[x]` done/verified · `[ ]` not done · `[~]` code-ready, needs live
verification.

Last updated: **2026-06-10**. Verification method: read-only probes against the
hosted Supabase DB (service key + `curl --resolve`); interactive flows must be
run in a browser by an operator, then confirmed via the DB trace listed here.

---

## Current verified state (2026-06-10)

| Signal | Value |
|---|---|
| Backend (`interview-web-app.onrender.com`) | **Up** — `/health` 200, auth gating 401, webhook 401 fail-closed |
| `RESEND_WEBHOOK_SECRET` | **Set** (webhook returns 401, not 503) |
| Migration 010 | **Applied** (`email_events`, `email_suppressions`, new `email_outbox` columns all present) |
| `email_outbox` | 2 rows, both `failed` / "RESEND_API_KEY missing" (2026-05-29/30) — **no send since deploy** |
| `email_events` | 0 — **no webhook events yet** |
| `email_suppressions` | 0 |
| `companies` | 1 (`Default` backfill sentinel) — **no real self-serve signup yet** |
| candidates / interviews | 36 / 20 (newest interview 2026-05-30) — **idle since deploy** |

**Headline:** the release is deployed and the schema is migrated, but the
production system has had **zero activity since deploy**, so the email + flow
paths are unexercised. One real invite (Section C, step 2) unblocks most checks.

---

## A. Email pipeline (ADR 0012 / migration 010)

- [x] **Migration 010 applied** — verified: `email_outbox.idempotency_key/
  email_type/reply_to/last_event_at` present; `email_events` + `email_suppressions`
  tables exist.
- [~] **`RESEND_API_KEY` set on Render** — *unverified.* No send has occurred, so
  the only proof (a `status='sent'` row with `resend_message_id`) doesn't exist
  yet. **Verify:** run an invite (Section C-2) → expect `email_outbox.status='sent'`
  + non-null `resend_message_id`.
- [~] **`RESEND_FROM_EMAIL` = verified domain sender** — *unverified.* Confirm the
  domain is verified in the Resend dashboard; the sandbox `onboarding@resend.dev`
  is fine for testing but not for real candidate mail.
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

## B. Platform configuration (carried over from earlier checkpoints)

- [ ] **Supabase Auth SMTP** configured (signup confirmation email). Separate
  from Resend — this is Supabase's own mailer. Without it, email-confirm signups
  can't complete (Google OAuth is the no-email path).
- [ ] **`ENVIRONMENT=production`** on Render — arms the readiness gate's
  prod-only fatal rules (`app/readiness.py`).
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

1. **Resend env unverified** — top blocker. No send has happened; can't confirm
   `RESEND_API_KEY`/`FROM`/`WEBHOOK_SECRET` are live. → run Section C-2.
2. **Production URLs unknown to the verifier** — need the real **frontend** and
   **backend** URLs to test the webhook endpoint and hand over exact links.
   (Repo has no hardcoded prod URL; it's the `VITE_API_URL` env var.)
3. **No real tenant in production** — only the `Default` sentinel company exists;
   Section C-1 has never run in prod.
4. **Platform config (Section B)** — SMTP / `ENVIRONMENT` / `FRONTEND_BASE_URL` /
   CORS unverified.

## E. How verification is performed

Read-only DB probe (no writes), reused from the diagnosis sessions:

```
# service key from backend/.env; host pinned to a public-DNS IP to bypass any
# stale local resolver for the (resumed) Supabase project.
curl --resolve <host>:443:<ip> \
  -H "apikey: $SUPABASE_KEY" -H "Authorization: Bearer $SUPABASE_KEY" \
  "https://<host>/rest/v1/email_outbox?select=status,email_type,resend_message_id,sent_at&order=sent_at.desc"
```

Webhook endpoint test (no auth — signature-gated):

```
curl -i -X POST <backend>/api/webhooks/resend -d '{}'      # expect 503 (no/!secret)
# with a deliberately wrong svix-signature header           # expect 401
```

---

### Definition of done

All boxes in A, B, C ticked; one real candidate has gone invite → interview →
report → shortlist email, with the matching `email_outbox` (`sent`) and
`email_events` (`delivered`) rows observed.
