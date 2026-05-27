-- ============================================================================
-- Migration 006: Outbound email audit log (multi-tenant rollout PR 6)
-- Run this in the Supabase SQL Editor after migration 005.
--
-- Adds: `email_outbox` table, one row per outbound email sent through the
-- platform. Recipient + subject + full body are stored so the audit
-- record is reproducible from the DB alone (grill E4 resolution —
-- "Full body in outbox" for audit reproducibility, accepted PII
-- duplication cost). Idempotent. Safe to re-run.
--
-- The recruiter / company_admin Shortlist + Email flow (PR 7) writes
-- one row per `Send`. Drafts are NOT persisted server-side (grill E3:
-- client-side drafts only) — only sent messages land here.
-- ============================================================================

create table if not exists public.email_outbox (
    id                   uuid primary key default gen_random_uuid(),
    company_id           uuid not null references public.companies(id) on delete cascade,
    candidate_id         uuid references public.candidates(id) on delete set null,
    sender_id            uuid references auth.users(id)         on delete set null,
    to_email             text not null,
    subject              text not null,
    body                 text not null,
    status               text not null default 'sent'
                              check (status in ('sent', 'failed')),
    resend_message_id    text,
    error_message        text,
    sent_at              timestamptz not null default now()
);

-- Per-candidate audit query (used by recruiter detail page in PR 7
-- to render "previous messages to this candidate").
create index if not exists idx_email_outbox_candidate
    on public.email_outbox (candidate_id, sent_at desc);

-- Per-tenant audit query (used by /admin/settings later — "all emails
-- our company has sent"). Composite ordering by sent_at desc avoids a
-- sort node on the recent-emails view.
create index if not exists idx_email_outbox_company
    on public.email_outbox (company_id, sent_at desc);

-- Per-sender query — useful for accountability ("emails I sent" from
-- the recruiter's perspective).
create index if not exists idx_email_outbox_sender
    on public.email_outbox (sender_id, sent_at desc);

-- Row Level Security: service-role-only writes (mirrors
-- recruiter_decisions and interview_integrity_events). The backend
-- enforces tenant scope on every read via the company_id filter
-- (tenant_scope helper) — no client-side policy needed.
alter table public.email_outbox enable row level security;

-- NOTE: the FastAPI backend uses the service-role key, which bypasses
-- RLS. The absence of any select/insert/update/delete policy here
-- denies direct client access by default. Reads land through the
-- backend in PR 7's recruiter detail endpoint.
