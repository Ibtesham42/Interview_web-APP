# Jobs are first-class requisitions; the link to interviews/invites is nullable

Status: accepted

The platform models **Jobs** (requisitions) as a first-class tenant-scoped
entity (migration 013): a Company can create jobs, publish them at
`/apply/{company_slug}/{job_slug}`, and tie interviews and invitations to a
specific job. This is a deliberate pivot from the **candidate-centric** shape the
platform shipped with — one apply link per Company, interviews tied only to a
Candidate, and CONTEXT.md's explicit "we don't model jobs yet."

The alternatives were: (a) a **lightweight job tag** — a free-text job title on
interviews/candidates, no separate entity, no per-job links or pipelines;
(b) **defer jobs** entirely and keep the platform candidate-centric; (c) the
chosen scope — a **full `jobs` requisition object** with its own slug, status,
required skills, and per-job interview config, that interviews and invitations
reference by id.

We chose **(c)**, because the features queued behind it — a per-job ATS
pipeline, resume-vs-JD matching, and per-job interview configuration — all need a
durable job entity with a stable id to hang off. A free-text tag (a) cannot be
the foreign key those features require; deferring (b) leaves resume matching with
nothing to match against. The cost of the real entity is one additive migration
and a thin CRUD surface, both of which reuse machinery that already exists
(the capability module, tenant scoping, the slug pattern, the apply funnel).

The load-bearing constraint on the pivot: **`interviews.job_id` and
`candidate_invitations.job_id` are NULLABLE**, and `ON DELETE SET NULL`. A job is
*optional context*, never a new requirement. Every interview and invite created
before — and after — migration 013 with no job attached keeps working unchanged,
and critically the realtime interview pipeline (the WebSocket orchestrator the
project guards) never learns about jobs at all: `job_id` is metadata on the
`interviews` row, not an input to question generation or scoring. ADR 0001 (the
LLM only phrases; Python plans the layer/topic) is preserved untouched. Per-job
interview tuning is reserved as `jobs.interview_config` (jsonb), whose empty-object
default means "use platform defaults," so the orchestrator stays untouched until a
Company explicitly opts in (a later phase).

Jobs add a *dimension* to the existing funnel; they do **not** extend it.
ADR 0004 still holds — the funnel terminates at Shortlist, and `job_id` does not
introduce a "Hired" stage. A job is the thing a candidate is shortlisted *for*,
not a new terminal state.

Authorization reuses the capability module (ADR 0006/0007): a new `manage_jobs`
capability admits HIRING_ROLES with a tenant — the same shape as
`invite_candidate`, so a platform admin without a company honestly fails and must
act-as a tenant. Multi-tenant posture matches ADR 0005: every `jobs` row carries
`company_id`, access is service-role-only via RLS, and the handler `tenant_scope`
is authoritative. The public per-job apply lookup is the one un-authed path, and
it serves only `status='open'` jobs.

Slugs are unique **per company**, not globally, so two Companies may each have a
`backend-engineer` job; the public URL is namespaced by the company slug. This
mirrors how the company slug already namespaces the apply link, and keeps job
slugs out of the reserved-slug collision space that top-level routes occupy.

## Consequences

- A new domain entity (`jobs`) and two new nullable foreign keys exist. The
  candidate-centric flow is a strict subset: nothing that worked before requires
  a job now.
- `manage_jobs` is the fifth capability (CAPABILITIES + the TS mirror +
  `test_capabilities`). Adding it surfaced and fixed the misleading `requires()`
  docstring — it already returns a `Depends(...)`; the first real consumer
  (`routers/jobs.py`) must assign it directly, not double-wrap.
- Resume matching (a later phase) now has a `jobs.required_skills` + description
  to match a candidate's `resume_sections` against, and a place
  (`jobs.embedding` / a match cache) to store results. The matcher stays
  advisory per the user-input-authoritative rule.
- The per-job pipeline (Phase 2 / ATS) will scope `recruiter_decisions` by
  `job_id`; that is a uniqueness-constraint change
  (`UNIQUE(candidate_id, recruiter_id, job_id)`) with a backfill, called out
  here as a follow-up, not done in this migration.
- `candidate_invitations` is unique per `(company, email)`, so today `job_id` on
  an invitation reflects the (single) invitation row, not a per-job invite.
  Per-job invitation rows are a later refinement that travels with the pipeline
  work.
- Threading `job_id` from a per-job apply all the way onto the eventual
  `interviews.job_id` *through signup* is not yet wired: the candidate apply
  landing funnels into the existing claim/signup flow (which joins them to the
  Company); a recruiter then interviews them against the job. Closing that gap is
  a follow-up integration, not a schema change.
- If per-tenant verified domains or external ATS sync later land, jobs are the
  natural anchor for "which requisition did this candidate apply to," but the
  source of truth for a *hire* still lives elsewhere (ADR 0004).
