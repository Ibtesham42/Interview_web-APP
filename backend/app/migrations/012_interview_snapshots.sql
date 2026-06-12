-- ============================================================================
-- Migration 012: Interview proctoring snapshots
-- Run this in the Supabase SQL Editor after migration 011.
--
-- WHY (proctoring enhancement, 2026-06-12): the integrity monitor records
-- *events* (tab blur, no_face, multi_face, ...) but keeps camera frames in
-- the browser. Companies asked for visual evidence: periodic webcam
-- snapshots during the interview plus a snapshot at each integrity warning,
-- so a reviewer can verify the candidate's own face/camera/voice was used.
--
-- Snapshots are small JPEG frames (~320px wide, quality ~0.55, roughly
-- 10–25 KB each, base64-encoded). A 30-minute interview at one frame per
-- minute is ~30 rows / ~0.7 MB — storage stays in Postgres so no Storage
-- bucket config is needed. Revisit object storage if volume grows.
--
-- Access: service-role only (RLS enabled, no policies) — reads go through
-- the backend, gated like reports (owner, hiring roles of the same tenant,
-- platform admin).
--
-- Idempotent. Safe to re-run.
-- ============================================================================

create table if not exists public.interview_snapshots (
    id            uuid primary key default gen_random_uuid(),
    interview_id  uuid not null references public.interviews (id) on delete cascade,
    user_id       uuid references auth.users (id) on delete set null,
    company_id    uuid references public.companies (id) on delete set null,
    -- 'periodic' = timer capture; 'integrity' = captured when an integrity
    -- warning fired (the moment that triggered it).
    kind          text not null default 'periodic'
                  check (kind in ('periodic', 'integrity')),
    image_base64  text not null,
    created_at    timestamptz not null default now()
);

-- Reads are always "all snapshots for one interview", ordered by time.
create index if not exists idx_interview_snapshots_interview
    on public.interview_snapshots (interview_id, created_at);

alter table public.interview_snapshots enable row level security;
