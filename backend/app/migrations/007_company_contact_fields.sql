-- ============================================================================
-- Migration 007: Company contact fields (multi-tenant rollout follow-up)
-- Run this in the Supabase SQL Editor after migration 006.
--
-- Adds three contact-information columns to `companies`:
--   - email   (NOT NULL, defaulted to '' so the existing Default seed
--              row from migration 004 satisfies the constraint without
--              a manual update; new companies are required to supply a
--              real email at the API boundary).
--   - phone   (nullable — optional at signup).
--   - address (nullable — optional at signup).
--
-- The Pydantic validator on CompanyCreate (backend/app/models/schemas.py)
-- enforces email shape + non-empty at the API; the DB-side default of ''
-- exists solely to satisfy NOT NULL when this migration runs on a
-- pre-existing 'default' row.
--
-- Idempotent. Safe to re-run.
-- ============================================================================

-- 1. Add the three columns. ADD COLUMN IF NOT EXISTS makes re-runs no-ops.
--    `email` lands with a default + NOT NULL in one shot; existing rows
--    (just the seeded Default company at this point) get `''`.
alter table public.companies
    add column if not exists email text not null default '';
alter table public.companies
    add column if not exists phone text;
alter table public.companies
    add column if not exists address text;

-- 2. Backfill the Default seed with a clearly-non-real placeholder so a
--    Recruiter inspecting it knows it's a system row, not a real tenant.
--    Skip rows that already have an email value (idempotent re-run safe).
update public.companies
   set email = 'default@invalid.example'
 where id = '00000000-0000-0000-0000-000000000001'::uuid
   and (email is null or email = '');
