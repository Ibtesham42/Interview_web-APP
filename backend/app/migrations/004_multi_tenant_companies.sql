-- ============================================================================
-- Migration 004: Multi-tenant companies + denormalised company_id columns
-- Run this in the Supabase SQL Editor after migration 003.
--
-- Adds: companies table; a nullable company_id column on profiles,
-- candidates, interviews, evaluations, recruiter_decisions, and
-- interview_integrity_events; one index per column; the Default
-- Company seed (fixed UUID); the backfill that stamps every existing
-- pre-rollout row with Default's id (except platform-admin profiles,
-- which stay NULL per ADR 0005 / grill C3); and RLS policies on the
-- companies table itself.
--
-- This is the data-layer foundation for the multi-tenant rollout
-- documented in MULTI_TENANT_ROLLOUT.md (12 grills resolved
-- 2026-05-27) and the schema decisions A1/A2/A3 in
-- docs/adr/0005-multi-tenant-companies.md.
--
-- Behaviour-preserving: no backend code reads or writes company_id
-- yet. Tenant scoping in handlers lands in PR 1 of the rollout.
-- Existing tests + endpoints continue to work unchanged because the
-- new column is nullable and untouched by any current code path.
--
-- Idempotent. Safe to re-run.
-- ============================================================================


-- 1. Companies table -------------------------------------------------------
create table if not exists public.companies (
    id          uuid primary key default gen_random_uuid(),
    slug        text not null unique,
    name        text not null,
    created_by  uuid references auth.users (id) on delete set null,
    created_at  timestamptz not null default now()
);

-- Slug lookup is the hot path for the future /apply/{slug} route
-- (PR 4). The UNIQUE constraint above already provides one but be
-- explicit about the lookup index for clarity.
create index if not exists idx_companies_slug
    on public.companies (slug);


-- 2. Default company seed --------------------------------------------------
-- Fixed sentinel UUID so the backfill below and any test fixture can
-- reference Default by id without a SELECT. The UUID is part of the
-- schema contract (see ADR 0005 "Consequences" section): rename is
-- fine, UUID change is not.
insert into public.companies (id, slug, name, created_by)
values (
    '00000000-0000-0000-0000-000000000001'::uuid,
    'default',
    'Default',
    null
)
on conflict (id) do nothing;


-- 3. Denormalised company_id columns on every tenant-scoped table ---------
-- All nullable in this migration. Whether to enforce NOT NULL is a
-- follow-up decision in a later PR once the B2B and B2C signup flows
-- have both shipped (B2C users are explicitly NULL per grill C1).
--
-- ON DELETE SET NULL on the FK so deleting a Company doesn't cascade
-- into deleting candidates / interviews; tenant offboarding is a
-- product decision that needs its own grilling, not a side-effect
-- of a FK cascade.

alter table public.profiles
    add column if not exists company_id uuid
    references public.companies (id) on delete set null;

alter table public.candidates
    add column if not exists company_id uuid
    references public.companies (id) on delete set null;

alter table public.interviews
    add column if not exists company_id uuid
    references public.companies (id) on delete set null;

alter table public.evaluations
    add column if not exists company_id uuid
    references public.companies (id) on delete set null;

alter table public.recruiter_decisions
    add column if not exists company_id uuid
    references public.companies (id) on delete set null;

alter table public.interview_integrity_events
    add column if not exists company_id uuid
    references public.companies (id) on delete set null;


-- 4. Indexes on the new column for tenant-filter performance --------------
-- Every list/detail/aggregation endpoint will filter by company_id
-- after PR 1. Without these the filter is a sequential scan on
-- tables with even a few hundred rows.
create index if not exists idx_profiles_company
    on public.profiles (company_id);
create index if not exists idx_candidates_company
    on public.candidates (company_id);
create index if not exists idx_interviews_company
    on public.interviews (company_id);
create index if not exists idx_evaluations_company
    on public.evaluations (company_id);
create index if not exists idx_recruiter_decisions_company
    on public.recruiter_decisions (company_id);
create index if not exists idx_integrity_events_company
    on public.interview_integrity_events (company_id);


-- 5. Backfill pre-rollout rows into Default --------------------------------
-- Per grill A1 / ADR 0005: every existing row gets Default's id, with
-- one exception — profiles where role='admin' stay NULL, because
-- admins are platform-wide (grill C3).
--
-- The `where company_id is null` predicates make this re-run safe:
-- already-stamped rows are left alone on a second execution.

update public.profiles
   set company_id = '00000000-0000-0000-0000-000000000001'::uuid
 where company_id is null
   and role <> 'admin';

update public.candidates
   set company_id = '00000000-0000-0000-0000-000000000001'::uuid
 where company_id is null;

update public.interviews
   set company_id = '00000000-0000-0000-0000-000000000001'::uuid
 where company_id is null;

update public.evaluations
   set company_id = '00000000-0000-0000-0000-000000000001'::uuid
 where company_id is null;

update public.recruiter_decisions
   set company_id = '00000000-0000-0000-0000-000000000001'::uuid
 where company_id is null;

update public.interview_integrity_events
   set company_id = '00000000-0000-0000-0000-000000000001'::uuid
 where company_id is null;


-- 6. Row Level Security on companies --------------------------------------
-- companies-table RLS only. Domain-table RLS is unchanged in this PR
-- (the existing ownership-scoped policies from migration 001 still
-- apply to candidates/interviews/evaluations; integrity_events and
-- recruiter_decisions remain service-role-only). PR 1 of the rollout
-- adds tenant-aware policies to those tables for defense-in-depth.
alter table public.companies enable row level security;

-- Anyone signed in can read the companies they belong to. Platform
-- admins read all (no policy needed — the service-role backend
-- handles cross-tenant reads).
drop policy if exists "companies_select_own" on public.companies;
create policy "companies_select_own" on public.companies
    for select
    using (
        exists (
            select 1
              from public.profiles p
             where p.id = auth.uid()
               and p.company_id = companies.id
        )
    );

-- No client-side INSERT/UPDATE/DELETE policy. Companies are created
-- by the backend in response to POST /api/companies (PR 3) using the
-- service-role key, after explicit validation of slug uniqueness +
-- creator role. Mirrors the recruiter_decisions / integrity_events
-- write posture.

-- NOTE: the FastAPI backend uses the service-role key, which bypasses RLS.
-- These policies protect direct client-side queries only.
