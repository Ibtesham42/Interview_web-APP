-- ============================================================================
-- Migration 011: Candidate invitations ledger + tenant-stamp repair
-- Run this in the Supabase SQL Editor after migration 010.
--
-- WHY (invitation-to-interview fix, 2026-06-12):
--
-- 1. An "invitation" was previously only an email_outbox row + an apply
--    link. There was no first-class record tying (company, candidate
--    email) together, so:
--      - an existing candidate invited by a second company could never
--        accept (claim-company 403s when profiles.company_id is set);
--      - one candidate could not hold invitations from multiple
--        companies (profiles.company_id is single-valued).
--    `candidate_invitations` is the membership ledger that fixes both:
--    a candidate's tenant access = their profile company PLUS every
--    company that invited them. profiles.company_id is untouched and
--    keeps meaning "primary/first company" for back-compat.
--
-- 2. Tenant-stamp repair: create_interview / create_candidate never
--    stamped company_id, while migration 004 backfilled every profile
--    with one. Result: every interview created since the tenant-scoping
--    rollout has company_id NULL, fails the WebSocket tenant gate
--    ("Cannot connect to interview"), is hidden from the candidate's
--    dashboard tenant filter, and is invisible to the inviting
--    company's recruiters. Section 3 stamps those rows from the owner's
--    profile. (The code fix stamps new rows at insert time.)
--
-- Idempotent. Safe to re-run.
-- ============================================================================


-- 1. Invitations ledger ------------------------------------------------------
-- One row per (company, candidate email). Email is stored lowercased by
-- the application; the unique constraint makes re-invites a no-op
-- rather than a duplicate.
--
-- status lifecycle: pending -> accepted (claim / explicit accept /
-- implicitly by starting an interview for that company) or
-- pending -> declined (candidate dismisses it). accepted_user_id is
-- stamped on acceptance so the ledger survives email changes.
create table if not exists public.candidate_invitations (
    id                uuid primary key default gen_random_uuid(),
    company_id        uuid not null references public.companies (id) on delete cascade,
    email             text not null,
    candidate_name    text,
    invited_by        uuid references auth.users (id) on delete set null,
    status            text not null default 'pending'
                      check (status in ('pending', 'accepted', 'declined')),
    accepted_user_id  uuid references auth.users (id) on delete set null,
    created_at        timestamptz not null default now(),
    accepted_at       timestamptz,
    unique (company_id, email)
);

-- Candidate-side lookup ("my invitations") is by email; company-side
-- listing is by company_id (covered by the unique constraint's index).
create index if not exists idx_candidate_invitations_email
    on public.candidate_invitations (email);

-- Service-role-only access, same posture as email_outbox: RLS enabled
-- with no policies, so direct client queries see nothing and the
-- FastAPI backend (service key, bypasses RLS) is the only reader/writer.
alter table public.candidate_invitations enable row level security;


-- 2. Backfill from already-sent invite emails --------------------------------
-- Every invite the platform has emailed so far becomes a pending
-- invitation, so candidates invited before this migration can still
-- accept. DISTINCT ON keeps the earliest send per (company, email).
--
-- Guarded: `email_outbox.email_type` only exists after migration 010.
-- If 010 hasn't been applied yet, there are no typed invite rows to
-- backfill anyway, so this section becomes a no-op instead of aborting
-- the whole migration.
do $$
begin
    if exists (
        select 1 from information_schema.columns
         where table_schema = 'public'
           and table_name = 'email_outbox'
           and column_name = 'email_type'
    ) then
        insert into public.candidate_invitations (company_id, email, invited_by, status, created_at)
        select distinct on (company_id, lower(to_email))
               company_id, lower(to_email), sender_id, 'pending', sent_at
          from public.email_outbox
         where email_type = 'invite'
           and company_id is not null
         order by company_id, lower(to_email), sent_at asc
        on conflict (company_id, email) do nothing;
    end if;
end $$;

-- Invitations whose recipient already joined that company (claimed via
-- the apply link before this migration) are marked accepted.
update public.candidate_invitations ci
   set status = 'accepted',
       accepted_user_id = p.id,
       accepted_at = coalesce(ci.accepted_at, now())
  from public.profiles p
 where ci.status = 'pending'
   and lower(p.email) = ci.email
   and p.company_id = ci.company_id;


-- 3. Repair NULL tenant stamps on candidate-created rows ---------------------
-- Rows created while the insert paths forgot company_id get the owner's
-- profile company. B2C owners (NULL profile company) stay NULL — correct.
update public.candidates c
   set company_id = p.company_id
  from public.profiles p
 where c.company_id is null
   and c.user_id = p.id
   and p.company_id is not null;

update public.interviews i
   set company_id = p.company_id
  from public.profiles p
 where i.company_id is null
   and i.user_id = p.id
   and p.company_id is not null;

-- Evaluations inherit from their interview (the WS handler now stamps
-- new ones at insert time).
update public.evaluations e
   set company_id = i.company_id
  from public.interviews i
 where e.company_id is null
   and e.interview_id = i.id
   and i.company_id is not null;
