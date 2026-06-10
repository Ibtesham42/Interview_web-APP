# Resend Email — Architecture & Operations Runbook

Production-grade multi-tenant outbound email built on [Resend](https://resend.com).
Introduced incrementally: the audit log + send path (multi-tenant PRs 6–7,
migration 006) and the delivery lifecycle / suppression / idempotency / webhook
layer (**ADR 0012**, migration 010).

This document is the operator's guide: what the pieces are, how to configure
them, and how to verify the system in production.

---

## 1. Architecture at a glance

```
 recruiter / company_admin                         Resend
        │  POST /api/recruiter/.../email/send         ▲   │
        │  POST /api/companies/invite                 │   │ webhook (Svix-signed)
        ▼                                             │   ▼
  services/email.send() ──pre-send guards──▶ Resend POST   POST /api/webhooks/resend
        │   1. idempotency replay                            │  verify signature (fail-closed)
        │   2. suppression check                             │  dedupe on svix-id
        │   3. per-tenant rate limit                         │  advance email_outbox.status
        ▼                                                    │  bounce/complaint → suppression
   email_outbox  ◀──────────status updates──────────────────┘  append email_events
```

Three tables (all service-role-only RLS, tenant-scoped by `company_id`):

| Table | Role |
|---|---|
| `email_outbox` | One row per send attempt. `status` walks the lifecycle: `queued → sent → delivered`, or `bounced / complained / failed / suppressed`. Full body retained for audit (PII duplication accepted, grill E4). |
| `email_events` | Append-only Resend webhook log, one row per provider event, deduped on the Svix message id. Forensic record + status source. |
| `email_suppressions` | Global do-not-email list (one row per lowercased address). Populated automatically on hard bounce / complaint; checked before every send. |

### Why these choices (ADR 0012)

- **No job queue / worker.** The product sends exactly one email per user action
  — there is no bulk-send requirement. A broker + worker against a single-worker
  dyno would be a parallel system at this scale. The send stays synchronous in
  the request path; reliability comes from idempotency + the webhook lifecycle,
  not from a queue. Revisit only if/when a bulk "email all shortlisted" feature
  lands (then a real outbox-drainer worker is justified — `queued` status is
  already reserved for it).
- **One verified sender, tenant-branded.** All mail goes from a single verified
  Resend domain, but the `From` display name is the tenant
  (`"Acme via Rehearsify <noreply@…>"`) and `Reply-To` is the company's contact
  address. This gives per-tenant identity without each company verifying its own
  DNS. **Follow-up:** true per-tenant verified domains (a `company_domains` table
  + the Resend Domains API + a DNS-verification UI) for tenants that want their
  own envelope sender.
- **Suppression is global by address.** A hard bounce or spam complaint makes an
  address bad for the whole platform; re-mailing it from any tenant damages the
  shared sender reputation. Provenance (`company_id`, `reason`, `source_event_id`)
  is recorded without narrowing the block.
- **No new dependency.** Resend is one POST (httpx, not the SDK); the webhook
  signature is verified with stdlib `hmac` (not the `svix` package).

---

## 2. Configuration (environment variables)

| Var | Required | Purpose |
|---|---|---|
| `RESEND_API_KEY` | to send | Resend API key. Empty ⇒ disabled mode (sends recorded as `failed`, no network). |
| `RESEND_FROM_EMAIL` | to send | Verified sender. Default `onboarding@resend.dev` (Resend sandbox, no DNS). |
| `PLATFORM_FROM_NAME` | no | Friendly platform name in the `From`. Default `Rehearsify`. |
| `RESEND_WEBHOOK_SECRET` | for delivery visibility | Svix signing secret (`whsec_…`). Empty ⇒ the webhook **refuses all requests** (fail-closed) and no suppression list is built. |
| `EMAIL_RATE_LIMIT_PER_HOUR` | no | Per-tenant send cap per rolling hour. Default `100`. `0` disables. |
| `FRONTEND_BASE_URL` | in prod | Used to build `/apply/{slug}` links in invite emails. |

The startup readiness check (`app/readiness.py`) warns if `RESEND_API_KEY` is
set but `RESEND_WEBHOOK_SECRET` is not — you'd be sending blind.

---

## 3. First-time production setup

1. **Verify a sending domain** in Resend (Dashboard → Domains → add DNS records).
   Set `RESEND_FROM_EMAIL` to an address on it (e.g. `noreply@mail.yourdomain.com`).
2. **Create an API key** (Dashboard → API Keys) → set `RESEND_API_KEY` on Render.
3. **Apply migration 010** in the Supabase SQL Editor:
   `backend/app/migrations/010_email_delivery_lifecycle.sql` (after 009). It is
   idempotent and safe to re-run. **The new send path needs the new columns —
   apply it before/with the deploy.**
4. **Register the webhook** (Dashboard → Webhooks → add endpoint):
   - URL: `https://<your-api-host>/api/webhooks/resend`
   - Events: `email.sent`, `email.delivered`, `email.delivery_delayed`,
     `email.bounced`, `email.complained` (opened/clicked optional).
   - Copy the signing secret → set `RESEND_WEBHOOK_SECRET` on Render.
5. **Redeploy** the backend so the new env vars load.

---

## 4. Verifying in production (read-only probes)

```sql
-- Delivery outcomes over the last day, per tenant:
select company_id, status, count(*)
from email_outbox
where sent_at > now() - interval '1 day'
group by 1, 2 order by 1;

-- Webhook ingestion is flowing (should be non-empty once mail is delivered):
select event_type, count(*) from email_events
where received_at > now() - interval '1 day' group by 1;

-- Who is suppressed and why:
select email, reason, company_id, created_at from email_suppressions order by created_at desc;
```

Healthy signal: a delivered email is `sent` within seconds, then `delivered`
once the webhook lands. A bounced send shows `bounced` and a matching
`email_suppressions` row.

---

## 5. Failure modes & responses

| Symptom | Likely cause | Action |
|---|---|---|
| All sends `failed`, error "RESEND_API_KEY missing" | Key not set on the host | Set `RESEND_API_KEY`, redeploy. |
| Sends `sent` but never `delivered`; `email_events` empty | Webhook not registered / wrong URL / secret mismatch | Re-check the Resend webhook endpoint + `RESEND_WEBHOOK_SECRET`. |
| Webhook returns 401 | Signature mismatch (secret rotated) | Re-copy the signing secret. |
| Webhook returns 503 | `RESEND_WEBHOOK_SECRET` unset | Set it (fail-closed by design). |
| Send returns 429 | Tenant over `EMAIL_RATE_LIMIT_PER_HOUR` | Expected throttle; raise the cap if legitimate. |
| Send `suppressed` | Recipient hard-bounced/complained earlier | Expected; remove the `email_suppressions` row only after confirming the address is valid again. |

---

## 6. Known follow-ups (not yet built)

- **Per-tenant verified domains** (see §1).
- **Tenant-scoped email log endpoint** (`idx_email_outbox_company` exists; no
  endpoint yet) and an integrity-volume-style delivery dashboard.
- **Retry of transient failures** — only relevant once a queue/worker exists.
