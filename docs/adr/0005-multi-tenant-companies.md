# Multi-tenant: companies as a denormalised tenant column with backend-primary isolation

Status: accepted

The platform transitions from a single-tenant model (everyone shares the
same global candidate pool) to a multi-tenant model where each Company is
a tenant with its own users, candidates, interviews, and recruiter
decisions. A Company A admin must not see Company B's data. The full
rollout is described in `MULTI_TENANT_ROLLOUT.md` (12 grills resolved
2026-05-27); this ADR records the three irreversible schema decisions —
A1, A2, A3 — that gate every later PR in the sequence.

## A1: Existing data is backfilled into a single "Default" Company

Pre-rollout rows on `profiles`, `candidates`, `interviews`, `evaluations`,
`recruiter_decisions`, and `interview_integrity_events` have no concept
of a tenant. The migration creates one Company with a fixed UUID
(`00000000-0000-0000-0000-000000000001`, slug `default`) and stamps every
existing row's new `company_id` column with that ID. Platform admin rows
(`role='admin'`) are the only exception — they stay NULL because admins
are platform-wide (see C3 in the rollout doc).

Alternatives rejected: (i) leave `company_id` nullable forever, with two
code paths everywhere ("legacy NULL row" vs "tenant-scoped row") — a
permanent mess that would never get cleaned up; (ii) hard-delete legacy
data — destroys the recruiter-rollout seed and any test interviews,
without product justification.

The Default Company is **not** a privileged tenant. It is just a normal
Company that happens to contain all pre-rollout data. A platform admin
can rename or delete it without breaking the schema.

## A2: Tenant isolation is enforced primarily in the backend, with RLS as defense-in-depth

The FastAPI backend uses the Supabase **service-role** key for all
domain-table reads and writes (see `supabase_client.py`). Service-role
bypasses RLS. So Row Level Security is **not** the primary enforcement
mechanism for tenant isolation — it cannot be, given the service-role
posture we already shipped.

Primary enforcement: every backend handler that reads tenant-scoped data
adds `.eq("company_id", caller.company_id)` to its Supabase query. The
authentication dependency (`get_current_user`) attaches `company_id` to
the request-scoped user object so handlers don't have to re-fetch it.
Platform admins (NULL `company_id`) skip the filter via an explicit
`if caller.is_platform_admin` branch.

RLS posture: tenant-aware policies *are* added to each domain table as
defense-in-depth, even though service-role bypasses them. The reason is
that the existing RLS policies (ownership-scoped: `auth.uid() = user_id`)
will continue to protect any future direct-from-client read. If a UI
team ever wires `supabase.from('candidates').select(...)` from the
frontend instead of routing through the backend, RLS will still scope
the result. We don't want the architectural option of direct client
reads to require a re-think of tenant safety.

Alternatives rejected: (i) backend-only filtering with no tenant-aware
RLS — works today, but every future direct-client read becomes a
silent cross-tenant leak; (ii) RLS-only enforcement — impossible given
the service-role key.

## A3: `company_id` is denormalised onto every domain table

Strict normalisation would put `company_id` only on `candidates` (and
`profiles`); everything else would resolve tenant via a join chain:
`evaluations.interview_id → interviews.candidate_id → candidates.company_id`.
We deliberately denormalise instead — every domain table carries its own
`company_id` column.

The reason denorm is safe: a Candidate's Company never changes after
creation. There is no "transfer this candidate to another company"
operation, and no product reason to add one (a candidate applies via
Company A's link; if they later apply to Company B, that creates a *new*
candidate row scoped to B). With no update path, the denorm column can
never drift from the source of truth.

The reason denorm is preferable: it makes tenant filtering a one-hop
predicate (`WHERE company_id = X`) on every table, including aggregation
queries like `score_interviews_bulk`. Without denorm, every aggregation
gains a join and `score_interviews_bulk` — pinned canonical per the
scaling-safety audit (CHANGE.md 2026-05-27) — would need refactoring.
Denorm preserves the bulk-query invariant exactly.

Storage cost: 16 bytes per row across six tables. At the platform's
projected scale (thousands of candidates, low millions of evaluations)
this is irrelevant; it would be irrelevant even at 100× scale.

## Consequences

- Migration 004 adds the `companies` table, the `company_id` column on
  six existing tables (all nullable), an index on each, the Default
  Company seed, and the backfill. Column stays nullable in this PR;
  whether to enforce `NOT NULL` later is a follow-up decision once the
  signup flows for both B2B (apply link) and B2C (NULL company_id) are
  shipped.
- Every backend list/detail/aggregation endpoint added prior to the
  rollout — `routers/admin.py`, `routers/dashboard.py`,
  `services/recruiter.py`, `services/recruiter_analytics.py`,
  `routers/reports.py`, `routers/interview_session.py` — needs a
  `company_id` filter added. PRs 1 and 2 of the rollout handle this.
- `score_interviews_bulk` itself is **unchanged**. It takes a list of
  interview IDs and returns scores; the *caller* is responsible for
  passing only IDs that belong to the right tenant. The pinned scoring
  helpers stay pinned.
- If a future product decision adds "transfer this candidate to another
  company," the denorm assumption breaks. That change would have to
  cascade `company_id` updates across interviews / evaluations /
  decisions / integrity events transactionally — easy enough to write,
  but not free. The decision to add such a feature must explicitly
  re-grill A3.
- The Default Company UUID (`00000000-0000-0000-0000-000000000001`) is a
  fixed sentinel. Tests, fixtures, and the backfill all reference it.
  Renaming the Company is fine; changing the UUID is not.
