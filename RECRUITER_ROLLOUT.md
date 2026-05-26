# Recruiter / Admin Candidate Management — Incremental Rollout

**Status:** Planned. Grill complete 2026-05-26. No code shipped yet.

This is a **phase exception** within the declared stability + scalability
phase (see [[project-stability-scalability-phase]] memory and `CLAUDE.md`).
The exception is bounded: incremental, additive, no rewrites of stable
code (voice/realtime pipeline, scoring helpers, integrity write path,
auth/RLS posture). Each PR ships independently in an existing-system-
shaped PR per the phase rule.

Designed via `improve-codebase-architecture` (grounding) + `grill-with-docs`
(12 decisions settled) on 2026-05-26.

---

## Grill resolutions (12 decisions)

| # | Decision | Resolution | Why |
|---|---|---|---|
| F1 | Recruiter — new role or admin subsume? | **New role** `'recruiter'` added to `profiles.role` CHECK | Domain reality differs (Admin = platform ops; Recruiter = workflow). Accountability in `recruiter_decisions.recruiter_id` collapses if conflated. Cheap to add (1-line CHECK + 5-line auth dep). Future-proofs without speculation — a present consumer is named in the request. |
| F2 | Recruiter scope — all candidates or assigned? | **All visible.** No assignment table. | No present consumer for scoping. Shortlist/Bookmark are the de-facto "this is mine" signal. Retrofit later is additive. |
| F3 | Workflow data storage | **New `recruiter_decisions` table** (decision-state shape). UNIQUE (candidate_id, recruiter_id). Columns: decision enum, bookmarked bool, notes text. | Current-state O(1) query, UNIQUE enforces invariant, funnel aggregation trivial. Audit log deferred (separate `recruiter_decision_history` later if needed). |
| F4 | Hiring Funnel stages | **4 stages: Signed up → Started → Completed → Shortlisted.** "Hired" out of scope. | ADR 0004 — platform doesn't observe hire/offer/start events; modeling state we don't observe creates decay. |
| F5 | ADR-0001 forward-only scoring × ranking | **Plain numeric sort + conditional `formula_mixed: true` advisory** in API response. UI conditionally renders a one-line note when the page mixes layer-aware + legacy formula interviews. | Honest, additive, doesn't touch scoring helpers. Upgrade path is cohort filter (deferred). |
| F6 | Auth-gate report endpoints | **Precursor PR (PR 0).** Standalone security fix before recruiter work begins. | Independent security issue (predates this feature). Bundling muddies diff. Same pattern as the CI fix. Initial gate `(owns OR admin)`; recruiter arm added in PR 2. |
| A1 | Sort/ranking implementation | **Hybrid wrapper in `services/recruiter.py`.** SQL WHERE for non-score filters; Python sort + score-filter + paginate after `score_interviews_bulk`. | Composes the pinned function without modifying it. Scales to ~1000 candidates. Upgrade trigger = materialize `final_score` column (additive). |
| A2 | Search implementation | **Simple ILIKE on `(name, field_specialization, resume_text)`** with multi-word AND-of-ORs. | Zero infrastructure. Scale ceiling matches A1. Upgrade path = pg_trgm + GIN (additive, single follow-up PR). |
| A3 | Pagination | **Offset/limit** with defaults `page=1, page_size=50, max=100`. Response includes `total_count`. | Total count is real UX value at this scale. Recruiter UX is filter-then-scan-top, not deep-paginate. Cursor upgrade is additive if ever needed. |
| B1 | Admin vs Recruiter access matrix | **Admin inherits Recruiter capabilities additively.** No row mutation across actors. Notes have Recruiter↔Recruiter privacy but not Admin↔Recruiter. See full matrix below. | Preserves accountability while letting Admin act as Recruiter. Disagreement expressed via new rows, never overwrites. |
| B2 | Integrity flags on Shortlist | **Soft-warn with confirmation dialog.** No API-side block. | Integrity signal is advisory, not authoritative. Hard-block bakes in business policy, not engineering decision. Trivially upgradable. |
| B3 | UI shape | **Search-bar + inline filter pills** (Lever/Greenhouse pattern). | Matches design language (Linear/Stripe/Notion). Search is primary action. Mobile-friendly. Saves vertical space. |

### B1 access matrix (the long form, locked)

| Capability | Admin | Recruiter |
|---|---|---|
| Existing `/api/admin/overview` (platform analytics) | ✓ | ✗ |
| Existing `/api/admin/users/{id}` (per-user detail) | ✓ | ✗ |
| New `/api/recruiter/candidates` (list) | ✓ | ✓ |
| New `/api/recruiter/candidates/{id}` (detail) | ✓ | ✓ |
| Make own Decision (Shortlist/Reject) | ✓ | ✓ |
| Set own Bookmark | ✓ | ✓ |
| Write own Notes | ✓ | ✓ |
| Read all Decisions on a Candidate (with author attribution) | ✓ | ✓ |
| Read **another Recruiter's** Notes | ✓ | ✗ |
| Edit/delete **another Recruiter's** Decision | ✗ | ✗ |
| New funnel + role-wise analytics | ✓ | ✓ |

---

## Documentation artefacts produced by the grill

- `CONTEXT.md` — 10 new domain terms (Candidate, Admin, Recruiter, Decision,
  Shortlist, Reject, Bookmark, Recruiter Note, Hiring Funnel, Funnel
  Stage). Plus the "User overloaded" ambiguity flagged.
- `docs/adr/0004-hiring-funnel-terminates-at-shortlist.md` — ADR for F4.

No further ADRs warranted (other decisions are reversible, unsurprising,
or not the result of a real trade-off).

---

## Implementation contract — 7 PRs (0 through 6)

Each PR is sized to ship in a single sub-day session. PRs 0 and 1 are
independent (parallelizable). PRs 5 and 6 are also parallelizable after
PR 4 lands. Otherwise serial.

### PR 0 — Auth-gate the report endpoints (security precursor)

**Status:** Not started. Can ship immediately, independent of all recruiter
work.

**Scope:** backend only.
- `backend/app/routers/reports.py:11-20` and `:23-33` — add
  `Depends(get_current_user)` and an ownership/role check:
  ```python
  async def get_interview_report(
      interview_id: UUID,
      user = Depends(get_current_user),
      supabase = Depends(get_supabase),
  ):
      interview = supabase.table('interviews').select('user_id').eq(
          'id', str(interview_id)).single().execute()
      if interview.data['user_id'] != user.id:
          # Allow admins (recruiter arm joins in PR 2)
          profile = supabase.table('profiles').select('role').eq(
              'id', user.id).single().execute()
          if profile.data['role'] != 'admin':
              raise HTTPException(status_code=403, detail="forbidden")
      # ... existing report generation
  ```
- Apply same gate to the `/report/markdown` endpoint.
- Frontend changes: **none** — `services/api.ts:125,128` already attaches the
  Supabase JWT via `fetchJson`; the change is purely backend.

**Verification:**
- `pytest -q` stays green (existing 72 tests).
- Manual: signed-in candidate fetches own report → 200. Signed-in admin
  fetches any report → 200. Unauthenticated curl → 401. Signed-in
  non-owner non-admin → 403.

**Unblocks:** independent — closes the open leak now. The recruiter detail
view (PR 5) will reuse the same authenticated endpoint.

**Sizing:** XS. One backend file changed. ~25 lines diff.

---

### PR 1 — Migration 003: recruiter role + `recruiter_decisions` table

**Status:** Not started. Independent of PR 0.

**Scope:** `backend/app/migrations/003_recruiter.sql` (new file).

```sql
-- Migration 003: Recruiter role + recruiter workflow table.
-- Run after migration 002.

-- 1. Extend profiles.role to include 'recruiter'.
alter table public.profiles
    drop constraint if exists profiles_role_check;
alter table public.profiles
    add constraint profiles_role_check
    check (role in ('user', 'admin', 'recruiter'));

-- 2. Recruiter decisions table.
create table if not exists public.recruiter_decisions (
    id           uuid primary key default gen_random_uuid(),
    candidate_id uuid not null references public.candidates(id) on delete cascade,
    recruiter_id uuid not null references auth.users(id)         on delete cascade,
    decision     text not null default 'undecided'
                      check (decision in ('shortlisted', 'rejected', 'undecided')),
    bookmarked   boolean not null default false,
    notes        text not null default '',
    decided_at   timestamptz,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now(),
    unique (candidate_id, recruiter_id)
);

create index if not exists idx_recruiter_decisions_candidate
    on public.recruiter_decisions (candidate_id);
create index if not exists idx_recruiter_decisions_recruiter
    on public.recruiter_decisions (recruiter_id, updated_at desc);
create index if not exists idx_recruiter_decisions_decision
    on public.recruiter_decisions (decision)
    where decision <> 'undecided';

alter table public.recruiter_decisions enable row level security;

-- No client-side INSERT/UPDATE/DELETE policy: only backend service-role
-- writes. RLS denies clients by default. Backend enforces (candidate_id,
-- recruiter_id == current_user) for writes at the API layer.
```

**Verification:**
- Migration applies cleanly in Supabase SQL editor.
- Existing `'user'` and `'admin'` profile rows unaffected (CHECK widened, not narrowed).
- Manual: insert a test recruiter_decisions row via service-role; SELECT works; INSERT via anon client is denied by RLS.

**Unblocks:** PRs 2+.

**Sizing:** XS. One new SQL file.

---

### PR 2 — Backend recruiter router + list endpoint

**Status:** Not started. Depends on PR 1.

**Scope:** backend only.

New files:
- `backend/app/routers/recruiter.py` — registers in `main.py`.
- `backend/app/services/recruiter.py` — the `rank_candidates` hybrid wrapper from A1.

Modified files:
- `backend/app/auth.py` — add `get_current_recruiter` dependency mirroring `get_current_admin`. Gate is `role in ('recruiter', 'admin')`.
- `backend/app/routers/reports.py` — extend the auth gate from PR 0 to allow `'recruiter'` too: `if profile.data['role'] not in ('admin', 'recruiter')`.
- `backend/app/main.py` — register the new router.
- `backend/app/models/schemas.py` — add `RecruiterCandidateRow`, `RecruiterCandidateListResponse`.

**Single endpoint:** `GET /api/recruiter/candidates`
- Query params: `search`, `field`, `decision`, `min_score`, `max_score`, `integrity`, `date_from`, `date_to`, `sort` (`final_score | created_at | name | decision | integrity_warnings`), `order` (`asc | desc`), `page`, `page_size`.
- Response: `{ items: [...], page, page_size, total_count, formula_mixed: bool }`.
- Service: `services/recruiter.rank_candidates(...)` — SQL WHERE for non-score filters; bulk-score via the unchanged `score_interviews_bulk`; Python sort + score-filter + paginate; compute `formula_mixed` from the page contents.

**No write endpoints in this PR** — Decisions come in PR 4.

**Verification:**
- `pytest -q` stays green; **add tests** for the new service function (filter SQL composition, sort order, pagination edges, formula_mixed detection).
- Manual: hit endpoint with a recruiter-role JWT → list; with admin JWT → list; with user JWT → 403.

**Unblocks:** PR 3 (UI) and PR 4 (write endpoints).

**Sizing:** S. New router file + new service file + auth dependency + schema models. ~150-200 lines net.

---

### PR 3 — Frontend recruiter dashboard (list UI)

**Status:** Not started. Depends on PR 2.

**Scope:** frontend only.

New files:
- `frontend/src/components/recruiter/RecruiterDashboard.tsx` — search-bar + inline filter pills + table + pagination per B3 layout.

Modified files:
- `frontend/src/App.tsx` — new protected route `/recruiter` (and `/recruiter/candidates`) with `restrictTo={['recruiter', 'admin']}`.
- `frontend/src/services/api.ts` — `recruiterApi.candidates(params)` fetch helper.
- `frontend/src/types/index.ts` — `RecruiterCandidate`, filter param types.
- `frontend/src/components/auth/ProtectedRoute.tsx` — already supports `restrictTo` array; verify it handles multi-role.

**UI conventions:**
- Page `<h1>` auto-styled per ADR 0003 (1.75rem 600, no class).
- Reuse C1 `<Button>` primitive for any buttons (Clear filters, etc.).
- Reuse the integrity-badge styling from `AdminUserDetail.tsx:112-118`.
- Score column shows a colored dot matching the rec-tier from `recommendation_for`.
- Search input debounced 300ms.
- `formula_mixed: true` from API → render one-line advisory under the result count.

**Verification:**
- `npx tsc --noEmit` clean.
- Browser walk: log in as `role='recruiter'` user, see candidate list; filter; search; sort; paginate; integrity badge renders; rec-tier dot renders; formula-mixed advisory renders when applicable.

**Unblocks:** PR 4 (write actions) and PR 5 (detail page) — both depend on this for the row → action / row → detail navigation surfaces.

**Sizing:** S-M. One large component + routing + API helper + types. ~250-350 lines.

---

### PR 4 — Recruiter workflow write endpoints + UI actions (Shortlist/Reject/Bookmark/Notes)

**Status:** Not started. Depends on PR 3.

**Scope:** backend + frontend.

Backend:
- `backend/app/routers/recruiter.py` — extend with:
  - `PUT /api/recruiter/candidates/{candidate_id}/decision` — body: `{ decision: 'shortlisted' | 'rejected' | 'undecided' }`. Upserts a `recruiter_decisions` row scoped to `(candidate_id, current_user.id)`. Sets `decided_at = now()` on terminal states.
  - `PUT /api/recruiter/candidates/{candidate_id}/bookmark` — body: `{ bookmarked: bool }`. Upserts same row, toggles flag.
  - `PUT /api/recruiter/candidates/{candidate_id}/notes` — body: `{ notes: string }`. Upserts notes.
  - All three endpoints use the same underlying `upsert_recruiter_decision` service function.

Frontend:
- Add row-level action buttons on `RecruiterDashboard.tsx`:
  - Shortlist (variant="primary"), Reject (variant="danger"), Bookmark (variant="secondary").
  - Decision column shows current Recruiter's decision badge.
- Add Notes editor — modal or inline expandable row.
- B2 confirmation dialog when shortlisting a Candidate with integrity flags.

**Verification:**
- `pytest -q` extended with tests for the 3 write endpoints (upsert semantics, role gate, ownership).
- Browser walk: shortlist a candidate → row updates; reject → row updates; bookmark → toggle; notes save; shortlisting a flagged candidate triggers confirmation dialog.

**Unblocks:** PR 5 detail view (needs decisions exposed) and PR 6 analytics (funnel needs shortlist data).

**Sizing:** M. Three write endpoints + write service + UI actions + confirmation dialog. ~300-400 lines.

---

### PR 5 — Recruiter candidate detail page

**Status:** Not started. Depends on PR 4.

**Scope:** backend + frontend.

Backend:
- `GET /api/recruiter/candidates/{candidate_id}` — returns:
  ```
  {
    candidate: { id, name, email, field_specialization, ... },
    interviews: [ { id, status, score, recommendation, integrity_warnings, ... } ],
    decisions: [ { recruiter_id, recruiter_name, decision, bookmarked, decided_at } ],
    my_notes: string  // only the current Recruiter's notes
  }
  ```
- The B1 access matrix is enforced at this endpoint: Recruiters get `my_notes` (filtered to their own); Admins get an additional `all_notes` array with author attribution.

Frontend:
- `frontend/src/components/recruiter/RecruiterCandidateDetail.tsx` at route `/recruiter/candidates/:id`.
- Layout: candidate header (name, field, email) → interview list (cards, each links to the auth-gated `/report/{id}` reusing the existing `Report.tsx`) → Decisions panel (current Recruiter's actions + list of all Recruiters' decisions with attribution) → Notes editor.

**Verification:**
- `pytest` for the detail endpoint (B1 enforcement: recruiter sees only own notes; admin sees all notes).
- Browser walk: navigate from list → detail; see interview reports; toggle own decision; verify other Recruiters' decisions appear with attribution; verify Notes privacy.

**Unblocks:** complete recruiter workflow MVP. PR 6 is parallel.

**Sizing:** M. New endpoint + new screen + reuses Report.tsx for per-interview reports. ~250-350 lines.

---

### PR 6 — Hiring funnel + role-wise analytics

**Status:** Not started. Depends on PR 4 (needs decision data populated).

**Scope:** backend + frontend.

Backend (`backend/app/routers/recruiter.py` extended; `backend/app/services/recruiter_analytics.py` new):
- `GET /api/recruiter/analytics/funnel` — returns the 4-stage Hiring Funnel counts:
  ```
  {
    stages: [
      { stage: "signed_up",         count: 247 },
      { stage: "interview_started", count: 198 },
      { stage: "interview_completed", count: 164 },
      { stage: "shortlisted",       count: 42 }
    ],
    conversion_rates: { ... },
    by_field: { "ml": {...}, "general": {...}, ... }
  }
  ```
  All counts derived from existing `candidates` + `interviews` + `recruiter_decisions` (with `decision='shortlisted'` distinct on candidate_id). One SQL query per stage; aggregations are bulk per Invariant #5.
- `GET /api/recruiter/analytics/scores` — avg final_score by field, computed by reusing `score_interviews_bulk` with field-grouping.
- `GET /api/recruiter/analytics/integrity` — integrity event volume trends by `event_type` over time; one SQL aggregation over the existing `interview_integrity_events` table.

Frontend (`frontend/src/components/recruiter/RecruiterAnalytics.tsx` at `/recruiter/analytics`):
- Funnel visualization (4 stacked-bar stages with counts and conversion rates).
- Role-wise score chart.
- Integrity trends chart.
- Reuse the design language — no chart libraries beyond what already ships if possible (the existing Dashboard.tsx renders trend bars with plain divs; same approach).

**Verification:**
- `pytest` for each analytics endpoint with seeded data verifying the aggregation correctness.
- Browser walk: funnel renders with correct counts; conversion rates compute correctly; charts render at all viewport widths.

**Unblocks:** end of rollout.

**Sizing:** M. Three endpoints + new screen + charts. ~400-500 lines.

---

## Sequencing summary

```
PR 0 ─── (security; ships immediately, independent)
PR 1 ─── (schema; ships immediately, independent)
       ↓
PR 2 ─── (backend list endpoint; requires PR 1)
       ↓
PR 3 ─── (frontend list; requires PR 2)
       ↓
PR 4 ─── (write actions; requires PR 3)
       ├──→ PR 5 (detail page; can ship in parallel with PR 6)
       └──→ PR 6 (analytics; can ship in parallel with PR 5)
```

Total: 7 PRs over an estimated 4-6 working sessions. Each one shippable
and reviewable independently. The rollout can be paused at any point
after PR 3 with a usable (read-only) recruiter experience in production.

---

## After the rollout — known follow-up triggers

These are NOT planned work; they are *triggers* that would justify a
follow-up PR if/when the condition fires.

- **Scale > ~1000 candidates:** A1 hybrid sort and A2 ILIKE both
  start to slow. Triggers: materialize `final_score` as a column on
  `interviews` (with backfill PR); add `pg_trgm` extension + GIN
  index on a derived `searchable_text` column.
- **Recruiter complains about formula-mixed advisory confusion:** add
  cohort filter (F5 option c) — Recruiters explicitly choose
  "post-Matryoshka only" / "pre-Matryoshka only".
- **Hiring-team scale > one Recruiter:** add a `recruiter_assignments`
  table — additive, optional filter on the list endpoint. Existing
  "all-visible" callers keep working.
- **Audit/compliance ask for "who decided what when":** add
  `recruiter_decision_history` table populated by a Supabase audit
  trigger; expose history in the detail view.
- **ATS integration (Greenhouse, Lever):** add `external_hire_events`
  table — the platform becomes a *cache* of hire facts from the
  external system per ADR 0004, never the canonical store.
- **Sufficient request volume to justify cursor pagination:** A3
  upgrade trigger; swap to `?after=<cursor>` additively, deprecate
  offset over a window.

Each follow-up is its own grill + PR sequence. None are pre-approved
work.
