# Candidate status management (Shortlist / Reject / Hold + status)

Status: accepted

## Context

Company admins (and recruiters) review a Candidate and want to drive a
clear status with templated outreach: Shortlist (congrats email), Reject
(courtesy decline email), or Hold (park for later). The desired
human-readable statuses are Invited, Interview Completed, Shortlisted,
Rejected, On Hold.

Most of the machinery already existed: per-(Candidate, Recruiter)
`recruiter_decisions` (Shortlisted / Rejected / Undecided), the email
composer + outbox (PR 7), `default_shortlist_template` /
`default_rejection_template`, and tenant scoping that already restricts a
`company_admin` to their own Company's Candidates (`get_current_recruiter`
+ `tenant_scope`). The gaps were narrow: a Hold state, wiring Reject to an
email, and a way to display "status".

## Decision

### D1: Reuse the per-Recruiter Decision; do not add a candidate-level status column

Status is modeled on the existing `recruiter_decisions.decision`, not a
new candidate-level `status` column or table. For a single-admin Company
the acting admin's Decision *is* the Company's status; the per-Recruiter
model (two reviewers may disagree — CONTEXT.md) is preserved unchanged.
This avoids a schema fork and a reconciliation problem ("which recruiter's
status wins?") that the product doesn't yet need.

### D2: `hold` is a non-terminal Decision value

Migration 009 widens the `recruiter_decisions.decision` CHECK to add
`'hold'`. Unlike `shortlisted` / `rejected` (terminal — they stamp
`decided_at`), `hold` is a deliberate but reversible parked state and does
NOT stamp `decided_at`. So funnel analytics (which key off
`decided_at IS NOT NULL`) do not count a held Candidate as decided.
`hold` is added to `WRITABLE_DECISIONS`, `VALID_DECISION_FILTERS`, and the
sort rank; `TERMINAL_DECISIONS` is unchanged.

### D3: Candidate Status is DERIVED, not stored

The status label is computed (frontend `deriveStatus`): the reviewer's
Decision if it is shortlisted / rejected / hold, otherwise the Candidate's
furthest Funnel Stage (Interview Completed vs Invited). No status is
persisted — it is always a live projection of Decision + funnel, so it
cannot drift from the underlying decision.

### D4: Shortlist and Reject open an editable, optional email; Hold does not

Clicking Shortlist or Reject saves the Decision AND opens the composer
pre-filled with the matching template (`?template=shortlist|rejection` on
the existing draft endpoint). The admin edits subject/body and Sends, or
closes without sending — the status is saved regardless. Hold sends no
email. Toggling a decision OFF (back to Undecided) is silent. This honors
the "open an editable email modal, allow editing before sending" ask while
not forcing email on a status change.

## Consequences

- Migration 009 (additive CHECK widen). Existing rows unaffected.
- Backend: `WRITABLE_DECISIONS` / filters / rank gain `hold`; the email
  draft endpoint takes `?template=`. No new endpoint, table, or column.
- Frontend: a Hold button + a derived status chip on the review screen;
  Shortlist/Reject open the composer with the right template; the
  dashboard decision filter gains "On Hold".
- Tenant isolation is unchanged and already enforced — a `company_admin`
  can only set decisions / draft email for their own Company's Candidates
  (regression-tested, incl. a new company_admin cross-tenant 404 case).
- CONTEXT.md: Decision gains `On Hold`; new terms On Hold + Candidate
  Status.

## Open follow-ups (not decided here)

- **Per-Company templates.** Still platform-wide defaults (ADR 0005 / PR 6
  grill E2). A `company_email_templates` table + settings UI is the path
  if companies want bespoke copy.
- **Company-level status.** If the product later needs one authoritative
  status per Candidate (not per-Recruiter), that's a deliberate model
  change — promote Decision to a Company-scoped column or add a resolution
  rule. Out of scope here.
