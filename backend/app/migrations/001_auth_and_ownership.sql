-- ============================================================================
-- Migration 001: Authentication & data ownership (Phase 1)
-- Run this in the Supabase SQL Editor.
--
-- Adds: profiles table + roles, auto-profile trigger, user ownership columns
-- on candidates/interviews, and ownership-scoped Row Level Security.
-- Safe to re-run (idempotent).
-- ============================================================================

-- 1. Profiles: one row per auth user, holds display name + role -------------
create table if not exists public.profiles (
    id          uuid primary key references auth.users (id) on delete cascade,
    email       text,
    full_name   text,
    role        text not null default 'user' check (role in ('user', 'admin')),
    created_at  timestamptz not null default now()
);

alter table public.profiles enable row level security;

drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own" on public.profiles
    for select using (auth.uid() = id);

drop policy if exists "profiles_update_own" on public.profiles;
create policy "profiles_update_own" on public.profiles
    for update using (auth.uid() = id);

-- 2. Auto-create a profile whenever a new auth user is created --------------
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.profiles (id, email, full_name)
    values (
        new.id,
        new.email,
        coalesce(new.raw_user_meta_data ->> 'full_name', '')
    )
    on conflict (id) do nothing;
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_user();

-- 3. Backfill profiles for any users that already exist --------------------
insert into public.profiles (id, email, full_name)
select id, email, coalesce(raw_user_meta_data ->> 'full_name', '')
from auth.users
on conflict (id) do nothing;

-- 4. Ownership columns on domain tables ------------------------------------
alter table public.candidates
    add column if not exists user_id uuid references auth.users (id) on delete cascade;

alter table public.interviews
    add column if not exists user_id uuid references auth.users (id) on delete cascade;

create index if not exists idx_candidates_user  on public.candidates (user_id);
create index if not exists idx_interviews_user  on public.interviews (user_id);

-- 5. Replace permissive RLS with ownership-scoped policies ------------------
drop policy if exists "Allow all candidates"   on public.candidates;
drop policy if exists "Allow all interviews"   on public.interviews;
drop policy if exists "Allow all evaluations"  on public.evaluations;

-- Ensure RLS is enabled on the domain tables (idempotent / no-op if already on).
alter table public.candidates  enable row level security;
alter table public.interviews  enable row level security;
alter table public.evaluations enable row level security;

drop policy if exists "candidates_own" on public.candidates;
create policy "candidates_own" on public.candidates
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists "interviews_own" on public.interviews;
create policy "interviews_own" on public.interviews
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

-- Evaluations are owned transitively through their interview.
drop policy if exists "evaluations_own" on public.evaluations;
create policy "evaluations_own" on public.evaluations
    for all
    using (
        exists (
            select 1 from public.interviews i
            where i.id = evaluations.interview_id
              and i.user_id = auth.uid()
        )
    );

-- The question bank is shared: any signed-in user may read it.
-- Skipped gracefully if the ml_questions table has not been created yet
-- (it is optional - the question retriever falls back to built-in questions).
do $$
begin
    if exists (
        select 1 from information_schema.tables
        where table_schema = 'public' and table_name = 'ml_questions'
    ) then
        execute 'alter table public.ml_questions enable row level security';
        execute 'drop policy if exists "Allow all ml_questions" on public.ml_questions';
        execute 'drop policy if exists "ml_questions_read" on public.ml_questions';
        execute 'create policy "ml_questions_read" on public.ml_questions for select using (true)';
    end if;
end $$;

-- NOTE: the FastAPI backend uses the service-role key, which bypasses RLS.
-- These policies protect direct client-side queries (used by the dashboards).
