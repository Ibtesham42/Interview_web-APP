-- ============================================================================
-- Migration 010: Email delivery lifecycle, events, suppression & idempotency
-- Run this in the Supabase SQL Editor after migration 009.
--
-- Extends the PR-6 `email_outbox` audit log (migration 006) into a
-- production-grade delivery pipeline WITHOUT replacing it (ADR 0012):
--
--   1. Widens email_outbox.status from {sent,failed} to the full Resend
--      delivery lifecycle, and adds idempotency / categorisation / reply-to
--      / last-event columns.
--   2. Adds `email_events` — the append-only ingestion log for Resend
--      webhooks (one row per provider event, deduped on the Svix message id).
--   3. Adds `email_suppressions` — addresses we must not email again
--      (hard bounce / spam complaint / manual), checked before every send.
--
-- All statements are idempotent (IF [NOT] EXISTS / DROP-then-ADD). Safe to
-- re-run. Service-role-only RLS posture matches email_outbox.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. email_outbox — widen status + add lifecycle columns
-- ---------------------------------------------------------------------------

-- Status lifecycle (ADR 0012):
--   queued      — accepted by us, not yet handed to Resend (transient; the
--                 synchronous path rarely persists this, reserved for retries)
--   sent        — Resend accepted the POST (was the old terminal "success")
--   delivered   — Resend webhook: the receiving server accepted the message
--   bounced     — Resend webhook: hard/soft bounce (address added to suppress)
--   complained  — Resend webhook: recipient marked as spam (address suppressed)
--   failed      — our send raised, or Resend rejected synchronously
--   suppressed  — we refused to send (recipient on the suppression list)
alter table public.email_outbox
    drop constraint if exists email_outbox_status_check;
alter table public.email_outbox
    add constraint email_outbox_status_check
    check (status in (
        'queued', 'sent', 'delivered', 'bounced',
        'complained', 'failed', 'suppressed'
    ));

-- Caller-supplied idempotency key (e.g. a UI-generated UUID per Send click).
-- Lets a network retry / double-click reuse the prior outbox row + Resend's
-- own Idempotency-Key dedupe instead of sending twice. NULL = not provided.
alter table public.email_outbox
    add column if not exists idempotency_key text;

-- Categorises the send for tenant-scoped analytics ("how many invites vs
-- shortlist vs rejection emails did Acme send?"). Free-text, app-controlled.
alter table public.email_outbox
    add column if not exists email_type text;

-- The Reply-To we set (tenant contact address) — persisted so the audit row
-- reproduces exactly what the recipient saw.
alter table public.email_outbox
    add column if not exists reply_to text;

-- Timestamp of the most recent webhook event applied to this row. Lets the
-- UI show "delivered 2m ago" without joining email_events.
alter table public.email_outbox
    add column if not exists last_event_at timestamptz;

-- Idempotency is scoped per tenant: the same key from two different companies
-- is two distinct sends. Partial index so the many NULL keys don't collide.
create unique index if not exists uq_email_outbox_idempotency
    on public.email_outbox (company_id, idempotency_key)
    where idempotency_key is not null;

-- Webhooks arrive keyed by Resend's message id; index it for the
-- event -> outbox-row correlation done on every webhook delivery.
create index if not exists idx_email_outbox_resend_message_id
    on public.email_outbox (resend_message_id)
    where resend_message_id is not null;

-- ---------------------------------------------------------------------------
-- 2. email_events — append-only Resend webhook ingestion log
-- ---------------------------------------------------------------------------
create table if not exists public.email_events (
    id                uuid primary key default gen_random_uuid(),
    -- Svix message id from the `svix-id` header. UNIQUE so a webhook retry
    -- (Svix retries on non-2xx) is ingested exactly once — the dedupe key
    -- for at-least-once delivery.
    svix_id           text unique,
    -- The outbox row this event is about, correlated via resend_message_id.
    -- ON DELETE SET NULL: keep the raw event even if the outbox row is purged.
    outbox_id         uuid references public.email_outbox(id) on delete set null,
    company_id        uuid references public.companies(id)    on delete cascade,
    resend_message_id text,
    -- Resend event type, e.g. 'email.delivered', 'email.bounced'.
    event_type        text not null,
    -- Full provider payload, kept verbatim for forensic/debugging value.
    payload           jsonb,
    -- When Resend says the event occurred vs when we ingested it.
    occurred_at       timestamptz,
    received_at       timestamptz not null default now()
);

create index if not exists idx_email_events_outbox
    on public.email_events (outbox_id, occurred_at desc);
create index if not exists idx_email_events_company
    on public.email_events (company_id, received_at desc);
create index if not exists idx_email_events_message
    on public.email_events (resend_message_id);

alter table public.email_events enable row level security;
-- No policies: service-role backend bypasses RLS; clients are denied by
-- default (reads land through the backend, same posture as email_outbox).

-- ---------------------------------------------------------------------------
-- 3. email_suppressions — do-not-email list
-- ---------------------------------------------------------------------------
-- Suppression is GLOBAL by address (one row per lowercased email): a hard
-- bounce or spam complaint makes an address bad for the WHOLE platform, and
-- re-mailing it from any tenant damages shared sender reputation. company_id
-- + reason + source_event_id record provenance (who triggered it) without
-- narrowing the scope of the block.
create table if not exists public.email_suppressions (
    id              uuid primary key default gen_random_uuid(),
    email           text not null,
    reason          text not null check (reason in ('bounce', 'complaint', 'manual')),
    company_id      uuid references public.companies(id) on delete set null,
    source_event_id uuid references public.email_events(id) on delete set null,
    note            text,
    created_at      timestamptz not null default now()
);

-- Case-insensitive uniqueness: one suppression per address regardless of case.
create unique index if not exists uq_email_suppressions_email
    on public.email_suppressions (lower(email));

alter table public.email_suppressions enable row level security;
-- Service-role-only, as above.
