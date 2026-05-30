-- ============================================================================
-- Migration 008: Richer company onboarding fields
-- Run this in the Supabase SQL Editor after migration 007.
--
-- Expands the company-registration data model (ADR 0010):
--   companies: structured address (city / state / country / postal_code)
--              alongside the existing street `address`, plus optional
--              `website` and `company_size`.
--   profiles:  `username` — a cosmetic display handle. Identity is still
--              email-based (Supabase Auth); username is NOT a login
--              identifier. Collected at account creation, threaded through
--              Supabase user_metadata into the auto-create trigger below.
--
-- All new columns are nullable / optional, so the migration is additive
-- and the existing Default seed row + every current row stay valid.
--
-- Idempotent. Safe to re-run.
-- ============================================================================

-- 1. companies — structured address + optional company facts ----------------
alter table public.companies
    add column if not exists city         text;
alter table public.companies
    add column if not exists state        text;
alter table public.companies
    add column if not exists country      text;
alter table public.companies
    add column if not exists postal_code  text;
alter table public.companies
    add column if not exists website      text;
alter table public.companies
    add column if not exists company_size text;

-- 2. profiles — cosmetic display handle (NOT a login identifier) -------------
alter table public.profiles
    add column if not exists username text;

-- 3. Auto-profile trigger — also copy `username` from user_metadata ----------
--    `create or replace` keeps this idempotent. The trigger still copies
--    full_name; username is additive and defaults to '' when absent so a
--    candidate signup (which sends no username) is unaffected.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
    insert into public.profiles (id, email, full_name, username)
    values (
        new.id,
        new.email,
        coalesce(new.raw_user_meta_data ->> 'full_name', ''),
        coalesce(new.raw_user_meta_data ->> 'username', '')
    )
    on conflict (id) do nothing;
    return new;
end;
$$;
