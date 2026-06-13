-- ============================================================================
-- Migration 013: Jobs (requisitions) — the job-centric ATS keystone
-- Run this in the Supabase SQL Editor after migration 012.
--
-- WHY (job-management roadmap, Phase 1):
-- The platform was candidate-centric (ADR 0004): one apply link per company,
-- interviews tied only to candidates. This adds first-class job requisitions so
-- a company can post jobs, invite/interview candidates against a specific job,
-- and (later phases) run per-job pipelines, resume matching, and per-job
-- interview configuration.
--
-- `interviews.job_id` and `candidate_invitations.job_id` are added NULLABLE so
-- every existing candidate-centric interview/invite keeps working untouched and
-- the realtime interview pipeline is unaffected — a job is optional context, not
-- a new requirement. See the new ADR (jobs: candidate-centric -> job-aware).
--
-- Multi-tenant posture matches the rest of the domain (migration 004): every
-- row carries company_id; access is service-role-only via RLS (no client
-- policies), so the FastAPI backend is the sole reader/writer and the handler
-- tenant_scope filter is authoritative.
--
-- Idempotent. Safe to re-run.
-- ============================================================================


-- 1. Jobs table -------------------------------------------------------------
-- One row per requisition. `slug` is unique PER COMPANY (not globally) so the
-- public apply URL is /apply/{company_slug}/{job_slug}; two companies may both
-- have a "backend-engineer" job. `status` gates visibility: only 'open' jobs
-- accept applications; 'draft' is editable-but-unlisted; 'closed' is archived.
-- `interview_config` (jsonb) carries per-job interview tuning consumed by a
-- later phase (topics / focus areas / difficulty) — empty object is the
-- "use platform defaults" signal, so the orchestrator is untouched until set.
create table if not exists public.jobs (
    id                uuid primary key default gen_random_uuid(),
    company_id        uuid not null references public.companies (id) on delete cascade,
    title             text not null,
    slug              text not null,
    description       text,
    required_skills   jsonb not null default '[]'::jsonb,
    employment_type   text,
    location          text,
    status            text not null default 'draft'
                      check (status in ('draft', 'open', 'closed')),
    interview_config  jsonb not null default '{}'::jsonb,
    created_by        uuid references auth.users (id) on delete set null,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now(),
    unique (company_id, slug)
);

-- Company-side listing ("our jobs") is by company_id; the unique
-- (company_id, slug) constraint already indexes the public per-job lookup.
create index if not exists idx_jobs_company
    on public.jobs (company_id, created_at desc);

-- Service-role-only access, same posture as candidate_invitations / email_*:
-- RLS enabled with no policies, so direct client queries see nothing and the
-- FastAPI backend (service key, bypasses RLS) is the only reader/writer.
alter table public.jobs enable row level security;


-- 2. Link interviews to a job (nullable) ------------------------------------
-- Nullable + ON DELETE SET NULL: existing interviews stay job-less, and
-- archiving/deleting a job never destroys interview history.
alter table public.interviews
    add column if not exists job_id uuid references public.jobs (id) on delete set null;

create index if not exists idx_interviews_job
    on public.interviews (job_id);


-- 3. Link invitations to a job (nullable) -----------------------------------
-- An invite may target a specific job; absent => a general company invite
-- (the pre-013 behaviour), so the existing invite flow is unchanged.
alter table public.candidate_invitations
    add column if not exists job_id uuid references public.jobs (id) on delete set null;

create index if not exists idx_candidate_invitations_job
    on public.candidate_invitations (job_id);
