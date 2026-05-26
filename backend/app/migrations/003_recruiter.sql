-- ============================================================================
-- Migration 003: Recruiter role + recruiter workflow table (rollout PR 1)
-- Run this in the Supabase SQL Editor after migration 002.
--
-- Adds: 'recruiter' as a valid value in profiles.role; a per-(Candidate,
-- Recruiter) decisions table holding the Decision (shortlisted | rejected
-- | undecided), a Bookmark flag, and Recruiter Notes; indexes for the
-- recruiter list + per-candidate lookups; RLS that denies all client
-- access (backend service-role bypasses, all writes are enforced at the
-- API layer).
--
-- Foundational migration for the recruiter rollout described in
-- RECRUITER_ROLLOUT.md. The 'recruiter' role is a NEW role per grill F1,
-- not a renaming or subsumption of 'admin'. Admins inherit Recruiter
-- capabilities additively (per grill B1) — the role string still says
-- 'admin' and accountability is preserved by stamping every workflow
-- row with the actor's user id.
--
-- Idempotent. Safe to re-run.
-- ============================================================================

-- 1. Widen profiles.role CHECK to include 'recruiter' ----------------------
--    Existing 'user' and 'admin' rows are unaffected (CHECK is widened,
--    not narrowed).
alter table public.profiles
    drop constraint if exists profiles_role_check;
alter table public.profiles
    add constraint profiles_role_check
    check (role in ('user', 'admin', 'recruiter'));

-- 2. Recruiter decisions table --------------------------------------------
--    Shape per grill F3: decision-state, not action-log. UNIQUE
--    (candidate_id, recruiter_id) enforces "one row per Recruiter per
--    Candidate". Bookmark and Notes piggyback because they share the
--    same key (per-Recruiter, per-Candidate state).
--
--    decided_at is set when the row enters a terminal Decision
--    (shortlisted/rejected); it stays null while the Decision is
--    'undecided'. updated_at tracks any field change.
create table if not exists public.recruiter_decisions (
    id            uuid primary key default gen_random_uuid(),
    candidate_id  uuid not null references public.candidates(id) on delete cascade,
    recruiter_id  uuid not null references auth.users(id)         on delete cascade,
    decision      text not null default 'undecided'
                       check (decision in ('shortlisted', 'rejected', 'undecided')),
    bookmarked    boolean not null default false,
    notes         text not null default '',
    decided_at    timestamptz,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now(),
    unique (candidate_id, recruiter_id)
);

-- 3. Indexes ---------------------------------------------------------------
-- Per-candidate lookup (e.g. "show me all Decisions on Candidate X" for the
-- detail view — see B1 access matrix: both Admin and Recruiter read the
-- full list with author attribution).
create index if not exists idx_recruiter_decisions_candidate
    on public.recruiter_decisions (candidate_id);

-- Per-recruiter lookup ordered by recency (e.g. "show my recent
-- shortlists" on the dashboard). updated_at desc supports the common
-- "what did I just do" query without a sort.
create index if not exists idx_recruiter_decisions_recruiter
    on public.recruiter_decisions (recruiter_id, updated_at desc);

-- Partial index on the terminal Decisions — funnel analytics
-- (RECRUITER_ROLLOUT PR 6) counts "shortlisted" frequently; the
-- 'undecided' default is overwhelmingly the common row and need not
-- be indexed for that query.
create index if not exists idx_recruiter_decisions_decision
    on public.recruiter_decisions (decision)
    where decision <> 'undecided';

-- 4. Row Level Security ---------------------------------------------------
-- No client-side INSERT/UPDATE/DELETE policy: only the backend
-- service-role key writes recruiter_decisions rows. RLS denies clients
-- by default. Backend enforces (recruiter_id == current_user.id) for
-- writes at the API layer (PR 4). This mirrors the integrity_events
-- pattern (migration 002) — service-role-only writes, no client policy.
alter table public.recruiter_decisions enable row level security;
