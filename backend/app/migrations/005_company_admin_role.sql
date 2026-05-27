-- ============================================================================
-- Migration 005: Add 'company_admin' role for the multi-tenant rollout (PR 3)
-- Run this in the Supabase SQL Editor after migration 004.
--
-- Widens the profiles.role CHECK constraint to admit 'company_admin' —
-- the new role string for a Company's tenant-local administrator. Created
-- on POST /api/companies/ when an existing 'user' self-serves a company
-- signup; the same call stamps their company_id on the profile.
--
-- DEVIATION from the original C2 sub-resolution
-- ----------------------------------------------
-- The grill table in MULTI_TENANT_ROLLOUT.md said the existing 'recruiter'
-- role would be migrated to 'company_recruiter' during this rollout
-- ("PR 1 migrates all 'recruiter' rows to 'company_recruiter'"). On
-- reflection while authoring PR 1, that rename was deferred as a
-- pragmatic call: the role string 'recruiter' is semantically identical
-- to 'company_recruiter' post-rollout (both are tenant-scoped via the
-- company_id filter — see PRs 1 and 2). Migrating values adds risk
-- without changing behaviour. The CHECK constraint here keeps 'recruiter'
-- and adds 'company_admin'; the docs (CLAUDE.md role list, future ADR
-- if needed) describe 'recruiter' as a tenant-scoped recruiter.
--
-- If a future PR wants to introduce 'company_recruiter' as a distinct
-- role string (e.g. to differentiate from a legacy global recruiter that
-- never gets cleaned up), that's an additive CHECK widening.
--
-- Idempotent. Safe to re-run.
-- ============================================================================

-- 1. Widen profiles.role CHECK to admit 'company_admin' --------------------
--    Existing 'user', 'admin', 'recruiter' rows are unaffected (CHECK is
--    widened, not narrowed).
alter table public.profiles
    drop constraint if exists profiles_role_check;
alter table public.profiles
    add constraint profiles_role_check
    check (role in ('user', 'admin', 'recruiter', 'company_admin'));
