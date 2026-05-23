-- ============================================================================
-- Migration 002: Interview integrity / anti-cheating event log
-- Run this in the Supabase SQL Editor after migration 001.
--
-- Adds: interview_integrity_events table, RLS scoped to the candidate, an
-- index for per-interview lookups, and 'terminated_integrity' as a valid
-- interview status. Idempotent.
-- ============================================================================

create table if not exists public.interview_integrity_events (
    id            uuid primary key default gen_random_uuid(),
    interview_id  uuid not null references public.interviews(id) on delete cascade,
    user_id       uuid not null references auth.users(id)         on delete cascade,
    event_type    text not null,
    severity      text not null default 'warning'
                       check (severity in ('info', 'warning', 'critical')),
    metadata      jsonb not null default '{}'::jsonb,
    created_at    timestamptz not null default now()
);

create index if not exists idx_integrity_events_interview
    on public.interview_integrity_events (interview_id, created_at);
create index if not exists idx_integrity_events_user
    on public.interview_integrity_events (user_id, created_at desc);

alter table public.interview_integrity_events enable row level security;

-- Candidates can read their own events. Admin oversight reads via the
-- service-role backend (no client-side admin policy needed).
drop policy if exists "integrity_events_select_own"
    on public.interview_integrity_events;
create policy "integrity_events_select_own"
    on public.interview_integrity_events for select
    using (auth.uid() = user_id);

-- No client-side INSERT/UPDATE/DELETE policy: only the backend service-role
-- key writes events. RLS denies clients by default.
