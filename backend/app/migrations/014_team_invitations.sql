-- ============================================================================
-- Migration 014: Team invitations — self-serve recruiter/admin onboarding
-- Run this in the Supabase SQL Editor after migration 013.
--
-- WHY (Team/Role management, Phase 1):
-- Adding a Recruiter to a Company was a manual ops task (set profiles.role +
-- profiles.company_id by hand in the Supabase console). This ledger lets a
-- company_admin invite a teammate by email to a hiring role; on acceptance the
-- invitee's profile is stamped with the role + company.
--
-- Membership itself still lives on `profiles` (role + company_id) — the
-- existing one-user-one-company model is unchanged. This table is only the
-- INVITATION ledger (who invited whom, to what role, and whether it was
-- accepted), mirroring candidate_invitations (migration 011) but for hiring
-- roles instead of candidates.
--
-- Authorization: only TENANT_ADMINS (company_admin / platform admin) may create
-- or revoke these (capability `manage_team`); a Recruiter cannot add teammates,
-- so a compromised recruiter account can't escalate the tenant's headcount.
--
-- Multi-tenant posture matches the rest of the domain: company_id on every row,
-- service-role-only RLS (no client policies). Idempotent. Safe to re-run.
-- ============================================================================

create table if not exists public.team_invitations (
    id                uuid primary key default gen_random_uuid(),
    company_id        uuid not null references public.companies (id) on delete cascade,
    email             text not null,
    -- The hiring role the invitee receives on acceptance. Restricted to the two
    -- tenant-side roles; you cannot invite someone to be a platform 'admin' or a
    -- plain 'user' through this path.
    role              text not null default 'recruiter'
                      check (role in ('recruiter', 'company_admin')),
    invited_by        uuid references auth.users (id) on delete set null,
    status            text not null default 'pending'
                      check (status in ('pending', 'accepted', 'revoked')),
    accepted_user_id  uuid references auth.users (id) on delete set null,
    created_at        timestamptz not null default now(),
    accepted_at       timestamptz,
    -- One live invitation per (company, email). A re-invite reuses the row
    -- (the application revives a revoked one rather than duplicating).
    unique (company_id, email)
);

-- Invitee-side lookup ("is there a team invite for my email?") is by email;
-- company-side listing is by company_id (covered by the unique index).
create index if not exists idx_team_invitations_email
    on public.team_invitations (email);

-- Service-role-only access, same posture as candidate_invitations / jobs.
alter table public.team_invitations enable row level security;
