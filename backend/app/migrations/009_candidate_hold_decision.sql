-- ============================================================================
-- Migration 009: 'hold' decision value (candidate status management)
-- Run this in the Supabase SQL Editor after migration 008.
--
-- Widens the recruiter_decisions.decision CHECK to add 'hold' — a
-- deliberate, NON-terminal "On Hold" state (parked for later, reversible),
-- distinct from the 'undecided' default. Shortlisted / Rejected remain the
-- only terminal decisions (they stamp decided_at). Existing rows are
-- unaffected (the CHECK is widened, not narrowed).
--
-- Status surfaced in the UI (Invited / Interview Completed / Shortlisted /
-- Rejected / On Hold) is DERIVED from this decision plus the candidate's
-- interview-completion state — no separate status column is stored.
--
-- Idempotent. Safe to re-run.
-- ============================================================================

alter table public.recruiter_decisions
    drop constraint if exists recruiter_decisions_decision_check;
alter table public.recruiter_decisions
    add constraint recruiter_decisions_decision_check
    check (decision in ('shortlisted', 'rejected', 'undecided', 'hold'));
