# CHANGE.md

> **Working memory for this project.** Read this file top-to-bottom at the start
> of every session — it carries recent changes, architecture decisions, known
> issues, technical debt and TODOs across sessions.
>
> **Rules**
> - Log every meaningful change. Append new entries at the TOP (newest first).
> - Entry format:
>   ```
>   ## DD/MM/YYYY HH:MM
>   Type: Feature | Fix | Refactor | Decision | Known Issue | TODO
>
>   <short description>
>
>   Affected files: <paths>
>   Architectural impact: <how it changes the system, or "None">
>   Future considerations: <follow-ups, risks, debt>
>   ```
> - Track: architecture decisions, implemented features, future-impacting
>   decisions, unresolved bugs, technical debt, pending improvements.
> - This file is authoritative context — do not rely on chat history.

---

## 26/05/2026 — Recruiter rollout PR 5 · Candidate detail page (+ B1 access enforcement)
Type: Feature

The per-Candidate detail view a Recruiter lands on after clicking a
row in the dashboard. Closes the broken navigation reported during
PR 4 verification: row click was going to `/recruiter/candidates/:id`
but no route existed, so the catch-all sent the user back home.

Backend:

`backend/app/services/recruiter.py` — new `get_candidate_detail`:
- Pulls the Candidate header, every interview (scored via the pinned
  `score_interviews_bulk`, with integrity counts attached via the
  same bulk pattern as the list endpoint), every Decision row (with
  author attribution), the viewer's own Notes (always), and — only
  for Admins — every Recruiter's Notes (`all_notes`).
- Returns None for an unknown candidate so the router maps to 404
  without leaking existence.
- Resume excerpt is truncated to 1500 chars — the detail view is a
  preview, not the full document. Recruiters who need the full text
  click through to the interview report (now auth-gated since PR 0
  and recruiter-allowed since PR 2).
- Author name resolution is a single bulk profiles query keyed on
  the distinct recruiter_ids seen on the candidate.

`backend/app/routers/recruiter.py` — new
`GET /api/recruiter/candidates/{candidate_id}`. Gated by
`get_current_recruiter`. The viewer's role is read via `_fetch_role`
in the endpoint (rather than threading role through the auth
dependency) so the existing routes don't change shape.

`backend/app/models/schemas.py` — new response shapes:
`RecruiterCandidateHeader`, `RecruiterCandidateInterview`,
`RecruiterDecisionAttribution`, `RecruiterNotesEntry`,
`RecruiterCandidateDetailResponse`. The discriminator that drives
the access-matrix UI is `all_notes: Optional[List[...]]` — `None`
for Recruiters, a (possibly empty) list for Admins.

`backend/tests/test_recruiter_detail.py` — 14 new pytest cases pinning
the B1 access matrix:
- Missing candidate → None (→ 404).
- Resume excerpt truncates at 1500 chars; null when empty.
- Interview scoring + integrity counts attach correctly.
- Recruiter sees only their own Notes (`all_notes is None`).
- Recruiter still sees every Decision row with attribution
  (accountability is preserved by attribution, not by hiding rows).
- `is_you` flag on Decision rows reflects the viewer.
- Admin sees every Recruiter's Notes in `all_notes`.
- An Admin who hasn't decided sees their own `my_notes` as empty
  but `all_notes` populated.
- Author name falls back: full_name → email → "Recruiter" label.
- Brand-new candidate with no decisions: clean empty state, with
  `all_notes` being `[]` for Admins and `None` for Recruiters
  (the role signal must survive the empty case).

Frontend:

`frontend/src/components/recruiter/RecruiterCandidateDetail.tsx`
(new, route `/recruiter/candidates/:candidateId`):
- Header: back link → Candidates, name (`<h1>` unclassed per
  ADR 0003), one-line meta (field · email · joined date), and the
  per-actor action group (Shortlist / Reject / Bookmark) — mirrors
  the dashboard's Actions cell so the muscle memory transfers.
- Stat grid: interviews / completed / integrity warnings /
  recruiter decisions count.
- Interview history list reuses the `iv-list` pattern from
  AdminUserDetail — completed rows link to `/report/:id`, in-progress
  rows render as inert blocks.
- Decisions panel: every Recruiter's Decision row with attribution.
  Current viewer is flagged with " (you)" inline. Bookmark star
  shows when set.
- "Your notes" panel: textarea (4000 char cap) + Save (disabled
  when clean). Saving refetches so the canonical state and the
  draft re-converge.
- Admin-only "All recruiters' notes" panel — only renders when
  `all_notes` is a non-empty array. The Recruiter view never even
  considers it (`null` short-circuits).
- B2 confirm dialog reused from the dashboard: shortlisting from
  the detail view also pauses if `integrity_warnings > 0`.
- Refetch-after-write (rather than dashboard's optimistic-with-
  rollback): this view is single-Candidate, the surface area is
  small, and an actual server round-trip costs the same; the
  consistency benefit outweighs the latency feel.

`frontend/src/types/index.ts` — 5 new types: header, interview,
decision attribution, notes entry, detail response.

`frontend/src/services/api.ts` — `recruiterApi.detail(candidateId)`.

`frontend/src/App.tsx` — new gated route
`/recruiter/candidates/:candidateId`. The catch-all-to-home behaviour
that previously trapped the user is now bypassed by an actual route.

`frontend/src/index.css` — RECRUITER CANDIDATE DETAIL section: header
action group, notes textarea variant, all-notes list + entry.

Verification:
- `python -m pytest -q` → 133 passed (was 119; +14 new detail tests).
- `npx tsc --noEmit` clean.
- Bug reported in this thread (admin clicking a row showed the list
  again) is now structurally impossible — there is a route to land on.
- Browser walk pending: needs migration 003 applied; a
  `role='recruiter'` profile; ideally a Candidate with multiple
  Recruiter decisions so the Decisions panel attribution is visible.

Affected files: `backend/app/services/recruiter.py` (+155),
`backend/app/routers/recruiter.py` (+22),
`backend/app/models/schemas.py` (+48),
`backend/tests/test_recruiter_detail.py` (new, ~240 lines),
`frontend/src/components/recruiter/RecruiterCandidateDetail.tsx`
(new, ~340 lines),
`frontend/src/services/api.ts` (+3),
`frontend/src/types/index.ts` (+44),
`frontend/src/App.tsx` (+2),
`frontend/src/index.css` (+45).

Architectural impact: B1 access matrix now has a concrete UI
embodiment (Recruiter ↔ Recruiter Notes privacy; Admin override).
The `all_notes: list | null` discriminator is a small but durable
contract: the frontend never has to ask "am I an admin?" for the
notes view — it asks the *data*, which is single-source-of-truth.
PR 6 (analytics) can reuse `get_candidate_detail` for its
per-candidate drill-down without re-deriving the access shape.

Future considerations:
- The interview history list uses the same `iv-list` patterns as
  AdminUserDetail. If those two views ever diverge in real UX
  ways, lift the inner row to a shared component; not yet.
- Resume excerpt is currently a simple `[:1500]` slice. If
  Recruiters complain about ugly cut-offs mid-word, slice on the
  nearest sentence boundary — but cheap to defer.
- An "edit decision" history (who shortlisted, then un-shortlisted,
  and when) is intentionally NOT surfaced in this PR; it depends
  on the `recruiter_decision_history` table that grill F3 deferred.
  When (if) that table lands, the Decisions panel gains a "history"
  expand.

---

## 26/05/2026 — Recruiter rollout PR 4 · Workflow write endpoints + UI actions
Type: Feature

Three Recruiter write endpoints (Shortlist / Reject / Bookmark /
Notes) + the corresponding row-level actions on the dashboard. With
this PR the recruiter MVP is functionally complete; PRs 5–6 add the
candidate detail page and analytics on top.

Backend:

`backend/app/services/recruiter.py` — new `upsert_recruiter_decision`
shared by all three write endpoints. Single contract:
- Each named field is only touched when its argument is non-None.
  `setBookmark` cannot clobber Notes; `setNotes` cannot clobber a
  Decision. This is the load-bearing invariant — three endpoints
  sharing one row would otherwise be a foot-gun.
- Terminal Decisions (`shortlisted` | `rejected`) stamp `decided_at`;
  reverting to `undecided` clears it so PR 6 funnel analytics don't
  double-count a Candidate who was shortlisted then un-shortlisted.
- Inserts apply the same DEFAULTs the migration would (so the service
  is testable end-to-end without round-tripping to a real DB).
- Also added `candidate_exists()` so the write endpoints can surface
  a clean 404 instead of leaking a Postgres FK violation.

`backend/app/routers/recruiter.py` — three PUT endpoints:
`/api/recruiter/candidates/{id}/decision`,
`.../{id}/bookmark`, `.../{id}/notes`. All gated by
`get_current_recruiter`; all pre-check `candidate_exists()`; all
return the upserted row as `RecruiterDecisionRow`.

`backend/app/models/schemas.py` — three request shapes
(`RecruiterDecisionUpdate`, `RecruiterBookmarkUpdate`,
`RecruiterNotesUpdate`) plus the `RecruiterDecisionRow` response.
Notes are capped at 4000 characters (server-side soft limit; matches
the textarea `maxLength`).

`backend/tests/test_recruiter_upsert.py` — 14 new pytest cases pinning
the upsert contract: insert vs update, terminal-stamps-decided_at,
undecided-clears-decided_at, switching terminal decisions re-stamps,
each setter doesn't clobber the other two fields, invalid decision
raises (mapped to 400), candidate_exists helper presence/absence.

Frontend:

`frontend/src/components/recruiter/RecruiterDashboard.tsx` reworked:
- New Actions column at the row's right edge with Shortlist /
  Reject / Bookmark / Notes controls. Action cell stops event
  propagation so the row's navigate-to-detail click still works on
  the rest of the row.
- Buttons reflect current state (Shortlist toggles to "✓ Shortlisted"
  in the primary variant; Reject toggles to "✗ Rejected" in danger).
  Re-clicking a terminal state reverts to `undecided` — matches the
  upsert contract on the backend, so a single click round-trips.
- Bookmark is a star icon-button using the existing yellow accent
  (matches `.bookmark-flag` in the name cell).
- Notes button opens an inline expandable row beneath the candidate
  with a textarea (4000-char cap), Save disabled when the draft
  equals the saved value.
- B2 confirmation dialog: clicking Shortlist on a Candidate with
  `integrity_warnings > 0` opens a modal explaining the integrity
  signal is advisory; cancel / "Shortlist anyway" continues the
  action. Hard-block was deliberately rejected at the grill — the
  policy call belongs to the recruiter, not the engine.
- Optimistic UI: row state mutates immediately via a local
  `overrides` map; the network call follows. On error the previous
  value is rolled back and an error banner surfaces above the table.
  On the next refetch the overrides are cleared (server now reflects
  every committed change).

`frontend/src/services/api.ts` — three new methods on `recruiterApi`:
`setDecision`, `setBookmark`, `setNotes`. JSON body, PUT verb.

`frontend/src/types/index.ts` — added `RecruiterDecisionRow`.

`frontend/src/index.css` — new CSS for action cell + icon button +
notes editor + modal (backdrop + panel + actions). Modal honours
`prefers-reduced-motion`.

Verification:
- `python -m pytest -q` → 119 passed (was 105; +14 new upsert tests).
- `npx tsc --noEmit` clean.
- Browser walk pending: needs a Supabase profile with role='recruiter',
  migration 003 applied, and at least one candidate with
  integrity_warnings > 0 to exercise the B2 dialog.

Affected files: `backend/app/services/recruiter.py` (+135),
`backend/app/routers/recruiter.py` (+75),
`backend/app/models/schemas.py` (+22),
`backend/tests/test_recruiter_upsert.py` (new, ~240 lines),
`frontend/src/components/recruiter/RecruiterDashboard.tsx`
(substantial rewrite, ~540 lines total now),
`frontend/src/services/api.ts` (+18),
`frontend/src/types/index.ts` (+10),
`frontend/src/index.css` (+125).

Architectural impact: Recruiters can now make and reverse Decisions;
the workflow row in `recruiter_decisions` becomes meaningful data
for PR 5 (candidate detail) and PR 6 (funnel analytics). The
upsert-with-partial-update pattern is the contract those PRs will
read from — particularly that `decided_at IS NOT NULL` is a clean
signal for "this Recruiter has actually decided", which the funnel
counts on. The optimistic-UI override pattern in the dashboard is
narrow enough to stay inline; if a second screen needs it, lift it
to a small hook.

Future considerations:
- A row-level "Saving…" indicator was deliberately omitted — the
  optimistic update gives instant feedback and errors surface in
  the banner. If users report uncertainty about whether their click
  landed, add a per-row spinner.
- The B2 dialog currently only confirms on Shortlist. If Reject on
  a candidate with strong scores ever needs a confirmation, this
  same `pendingShortlist` state can generalise to a
  `pendingAction` discriminated union.
- Notes are written-by/read-by the same Recruiter only (per B1) —
  read-back of other Recruiters' Notes lands in PR 5's detail view.

---

## 26/05/2026 — Recruiter rollout PR 3 · Frontend recruiter dashboard (list UI)
Type: Feature

The Recruiter-facing screen that consumes PR 2's
`GET /api/recruiter/candidates`. Search-bar + inline filter pills +
sortable table + pagination, per the B3 grill resolution
(Lever/Greenhouse pattern).

What changed:

New `frontend/src/components/recruiter/RecruiterDashboard.tsx`:
- Search input debounced 300ms (local `useEffect` setTimeout —
  search-as-you-type isn't a pattern reused elsewhere yet, so it stays
  inline rather than being lifted to a `useDebounce` hook).
- Filter pill rows for field (auto-derived from the page's results +
  baseline fallbacks), decision (incl. independent `bookmarked`
  selector per F3), and integrity (with / without / any).
- Sort by Score / Signed up / Name / Decision / Integrity columns —
  clicking the active column flips direction; switching columns
  defaults to `desc` for everything except Name (which defaults to
  `asc`).
- Score column shows a 8px coloured dot + score + recommendation tier
  via the existing `scoreClass` heuristic (good ≥ 7, mid ≥ 5.5, low
  below). Matches the rec-tier from `recommendation_for` so the dot
  and the label can't disagree.
- Reuses the existing `.integrity-flag-chip` styling from
  `AdminUserDetail.tsx:112-118` for the integrity column.
- `formula_mixed: true` from the API → renders a one-line advisory in
  the result-count row (grill F5).
- Pagination uses the C1 `<Button>` primitive (Previous / Next +
  "Page X of Y" label). Hides itself when the result set fits a
  single page.
- Row click navigates to `/recruiter/candidates/:id` (the detail view
  in PR 5 — until that lands, the link 404s harmlessly via the
  catch-all redirect).
- All UI conventions per CLAUDE.md: dark / understated; `<h1>` left
  unclassed (ADR 0003 — auto-styled 1.75rem 600); 300ms motion;
  semantic HTML; `aria-label`s on icon-only and sort buttons.

Modified `frontend/src/types/index.ts`:
- `UserRole` widened to `'user' | 'admin' | 'recruiter'`.
- New `RecruiterCandidate`, `RecruiterListResponse`,
  `RecruiterListParams`, `RecruiterSortField`,
  `RecruiterIntegrityFilter`, `RecruiterDecisionFilter`,
  `RecruiterDecision` shapes mirroring the backend models.

Modified `frontend/src/services/api.ts`:
- New `recruiterApi.candidates(params)` helper. `URLSearchParams`
  drops `undefined / null / ''` entries so the backend only sees the
  filters that actually carry intent.

Modified `frontend/src/contexts/AuthContext.tsx`:
- Added `isRecruiter` (true when role is `'recruiter'` or `'admin'`,
  per the B1 access matrix — Admins inherit Recruiter capabilities).

Modified `frontend/src/components/auth/ProtectedRoute.tsx`:
- `restrictTo` now accepts `UserRole | UserRole[]`. The previous
  "admin → /dashboard / user → /admin" hard-coded redirects are
  replaced by a single redirect to `/` (RoleHome) — which already
  knows where each role belongs, so we don't have to teach the gate.

Modified `frontend/src/App.tsx`:
- Header nav: admins see Admin + Candidates; recruiters see
  Candidates; users see Dashboard + New Interview.
- New role badge for `role-recruiter`.
- `RoleHome` extended: admins → `/admin`, recruiters → `/recruiter`,
  users → `/dashboard`.
- New route `/recruiter` gated by `['recruiter', 'admin']`.

Modified `frontend/src/index.css`:
- New `.role-recruiter` badge (sky-blue).
- New section "RECRUITER DASHBOARD" — filter bar, pills (default +
  active states), result-line, formula-mixed advisory, sortable table
  headers, score dot, bookmark flag, decision chips (shortlisted /
  rejected / undecided), pagination row. ~140 lines, all using the
  existing CSS variable tokens.

Verification:
- `npx tsc --noEmit` clean.
- `python -m pytest -q` → 105 passed (no backend regressions; PR 3 is
  frontend-only).
- Browser walk pending — needs a Supabase profile row with role set
  to `'recruiter'` (migration 003 widened the CHECK constraint in
  PR 1, but no rows have been promoted yet).

Affected files: `frontend/src/components/recruiter/RecruiterDashboard.tsx`
(new, ~340 lines), `frontend/src/types/index.ts` (+50),
`frontend/src/services/api.ts` (+18),
`frontend/src/contexts/AuthContext.tsx` (+2),
`frontend/src/components/auth/ProtectedRoute.tsx` (refactor; ~15
net), `frontend/src/App.tsx` (~25 net),
`frontend/src/index.css` (+150).

Architectural impact: First Recruiter-facing UI. `ProtectedRoute` is
now multi-role capable and the previous binary "user vs admin"
home-redirect logic is consolidated to a single `RoleHome` call.
This makes the next role (if ever needed) a one-liner — a new badge,
a new RoleHome branch, and a new `restrictTo`.

Future considerations:
- PR 4 adds row-level actions (Shortlist / Reject / Bookmark / Notes
  with B2 confirmation dialog). The current row click navigates to
  the detail page (PR 5); inline actions land in the row's right
  edge in PR 4.
- The `fieldOptions` pill list is derived from the current page,
  which means a recruiter on page 2 may see a different field-pill
  set than on page 1 if there are rare fields. Acceptable for MVP;
  pull from a backend `/recruiter/fields` aggregate if it becomes
  confusing.
- A `useDebounce` hook should be extracted the second another caller
  needs debounced input — single-use abstraction would be premature.
- Row link `/recruiter/candidates/:id` will be live in PR 5; until
  then the route catch-all sends them home. Avoiding a "(detail
  view coming soon)" guard prevents stale messaging when PR 5 ships.

---

## 26/05/2026 — Recruiter rollout PR 2 · Backend recruiter router + list endpoint
Type: Feature

Read-only recruiter list endpoint behind a role gate. Backs the Phase B
recruiter dashboard (PR 3). Write endpoints (Shortlist / Reject /
Bookmark / Notes) come in PR 4.

What changed:

New `backend/app/services/recruiter.py` — the hybrid wrapper from grill
A1 (RECRUITER_ROLLOUT.md):
- SQL `where` for the cheap, indexable filters (field exact match,
  candidate created_at range, multi-word AND-of-ORs ILIKE search across
  name / field_specialization / resume_text per grill A2).
- One bulk score pass via the pinned `score_interviews_bulk` (ADR 0001;
  no modification).
- One additional bulk query per request for integrity-event counts
  (mirrors the admin router pattern), one for this Recruiter's
  `recruiter_decisions` rows, and one extra bulk query for the
  page-only `formula_mixed` (grill F5) — which checks whether any
  `evaluations.details.layer` is present in the completed interviews
  on the page.
- Python-side filters for score range, integrity (any / with /
  without), and decision (incl. independent `bookmarked` selector).
- Sort + paginate with grill A3 defaults (page=1, page_size=50, max=100).
  `created_at` nulls always sort to the bottom regardless of direction —
  the partition-then-sort trick avoids the inversion bug a single key
  with a sentinel suffers under `reverse=True`.

New `backend/app/routers/recruiter.py` — `GET /api/recruiter/candidates`.
Gated by the new `get_current_recruiter` dependency. Query params are
validated via `RankFilters.normalise`, illegal values surface as 400.

Modified `backend/app/auth.py`:
- Extracted `_fetch_role(user_id)` helper so both admin and recruiter
  gates share one Supabase round-trip pattern.
- Added `get_current_recruiter` — gate is `role in ('recruiter',
  'admin')` per the B1 access matrix (Admins inherit Recruiter
  capabilities additively).

Modified `backend/app/routers/reports.py` — extended PR 0's
`_authorize_report_access` to allow `role in ('admin', 'recruiter')` for
non-owner reads. The recruiter detail view (PR 5) reuses this gate.

Modified `backend/app/models/schemas.py` — new
`RecruiterCandidateRow` and `RecruiterCandidateListResponse` (items,
page, page_size, total_count, formula_mixed).

Modified `backend/app/main.py` — registered the new router at
`/api/recruiter`.

New `backend/tests/test_recruiter_service.py` — 33 tests covering:
filter validation (sort/order/decision/integrity reject illegal
values), Python-side filters (score range, integrity, decision incl.
bookmarked-independent-of-decision), sort key behaviour (final_score,
name, decision rank, created_at None-sorts-last regardless of
direction), pagination edges (page beyond range still reports
total_count), formula_mixed (true only when the page mixes layer-aware
+ legacy completed interviews; in-progress runs are excluded). Faked
Supabase routes per `.table(name)` so multi-table queries can be
exercised in pure-unit form.

Verification:
- `python -m pytest -q` → 105 passed (was 72; +33 new).
- `python -c "from app.main import app"` imports cleanly; route
  `/api/recruiter/candidates` registers.
- Manual JWT walk (recruiter / admin / user) pending against a Supabase
  with migration 003 applied and a 'recruiter' profile populated.

Affected files: `backend/app/services/recruiter.py` (new, ~270 lines),
`backend/app/routers/recruiter.py` (new, ~70 lines),
`backend/app/auth.py` (refactor + `get_current_recruiter`, ~25 net),
`backend/app/routers/reports.py` (gate widened, +1 line of intent),
`backend/app/models/schemas.py` (+30 lines),
`backend/app/main.py` (+2 lines), `backend/tests/test_recruiter_service.py`
(new, ~430 lines).

Architectural impact: First Recruiter-facing surface in the backend.
Composes the pinned scoring helpers (no modification per CLAUDE.md
engineering rule and ADR 0001). The `_authorize_report_access` widening
is the one place the recruiter rollout extends an existing security
gate — done deliberately here rather than in PR 5 so the report
endpoint already accepts Recruiter JWTs when the detail page lands.

Future considerations:
- PR 3 (frontend list UI) and PR 4 (write endpoints) consume this.
- PR 4 introduces `upsert_recruiter_decision` in the same service file.
- Scale ceiling per grill A1/A2: ~1000 candidates. Upgrade triggers
  (materialised `final_score` column, pg_trgm + GIN search index) are
  documented in RECRUITER_ROLLOUT.md "After the rollout — known
  follow-up triggers".
- Search input is currently passed through to `or_(...)` ILIKE unescaped
  for the per-token pattern. Tokens containing PostgREST or-syntax
  reserved characters (commas, parentheses) could cause a 400 from
  Supabase. Realistic recruiter searches do not contain these; if it
  ever bites, sanitize tokens at the service boundary.

---

## 26/05/2026 — Recruiter rollout PR 1 · Migration 003 (recruiter role + recruiter_decisions table)
Type: Feature

Foundational schema migration for the recruiter rollout
(`RECRUITER_ROLLOUT.md`). Adds the `'recruiter'` role and the
`recruiter_decisions` table that holds the Recruiter workflow state
(Decision / Bookmark / Notes) per the F3 grill resolution.

What changed:

New file `backend/app/migrations/003_recruiter.sql`:
- Widens `profiles.role` CHECK from `('user','admin')` to
  `('user','admin','recruiter')`. Existing rows unaffected — CHECK is
  widened, not narrowed. Idempotent via `drop constraint if exists` +
  re-create.
- Creates `public.recruiter_decisions` table:
  - PK `id` (uuid, default gen_random_uuid())
  - `candidate_id` FK → `candidates(id)` on delete cascade
  - `recruiter_id` FK → `auth.users(id)` on delete cascade
  - `decision` text CHECK in (`'shortlisted'`, `'rejected'`,
    `'undecided'`), default `'undecided'`
  - `bookmarked` boolean, default false
  - `notes` text, default `''`
  - `decided_at` timestamptz (null while undecided)
  - `created_at`, `updated_at` timestamptz default now()
  - UNIQUE (candidate_id, recruiter_id) — enforces "one row per
    Recruiter per Candidate" per the F3 decision-state shape.
- Three indexes:
  - `(candidate_id)` — detail view "all Decisions on this candidate".
  - `(recruiter_id, updated_at desc)` — recruiter's recent activity.
  - Partial `(decision) where decision <> 'undecided'` — funnel
    analytics (PR 6) frequently counts shortlisted; undecided is the
    overwhelming default row and not worth indexing for that query.
- RLS: enabled, no client policies. Mirrors the `interview_integrity_events`
  pattern (migration 002) — service-role backend writes; clients are
  denied by default; ownership enforced at the API layer (PR 4).

Affected files: `backend/app/migrations/003_recruiter.sql` (new),
`CHANGE.md`.

Architectural impact: First schema migration for the recruiter rollout.
Strictly additive — no existing table or column touched (CHECK
constraint widening is not a column change). Existing 'user' and 'admin'
profile rows continue working unchanged.

Future considerations:
- PR 2 (backend list endpoint) and PR 4 (write endpoints) consume this
  schema. PR 4 enforces (recruiter_id == current_user.id) at the API
  layer for writes; no client-side RLS policy needed because the
  backend uses the service-role key.
- A `recruiter_decision_history` audit-log table is intentionally NOT
  added at MVP per the F3 deferral; revisit when compliance asks for
  "who decided what when" history.

---

## 26/05/2026 — Recruiter rollout PR 0 · Auth-gate /reports endpoints (security precursor)
Type: Fix

`reports.py:11-20` (`GET /interview/{id}/report`) and `:23-33`
(`/report/markdown`) were UNAUTHENTICATED — anyone holding an
interview_id UUID could pull a candidate's full report including the
transcript. The frontend already attached a Supabase JWT to every
request via `fetchJson` (`api.ts:125,128`); the backend just ignored it.

This is the security precursor PR (rollout PR 0 in
`RECRUITER_ROLLOUT.md`). Independent of the rest of the recruiter
rollout — fixes the open leak immediately, so the recruiter detail
view (PR 5) can later reuse this endpoint safely.

What changed (`backend/app/routers/reports.py`):
- Added `Depends(get_current_user)` to both endpoints.
- New helper `_authorize_report_access(interview_id, user)` enforces the
  access rule: owner of the interview OR admin. Non-existent interviews
  surface as 404 (rather than 403) so we don't leak the existence of
  interviews the caller cannot see.
- Frontend changes: **none**. The JWT was already being sent; only the
  backend's enforcement was missing.

The `'recruiter'` arm of the auth gate is intentionally absent at this
PR — it joins in rollout PR 2 when the role actually has any populated
rows. The gate currently reads `if role != "admin"` → 403; PR 2 changes
it to `if role not in ("admin", "recruiter")` → 403.

Verification:
- `python -c "from app.main import app"` imports cleanly.
- `python -m pytest -q` → 72 passed (no regressions in the existing
  suite).
- Manual verification needed before commit: signed-in candidate fetches
  own report → 200; signed-in admin fetches any report → 200;
  unauthenticated curl → 401; signed-in non-owner non-admin → 403.

No new automated tests added in this PR — the existing project lacks
FastAPI `TestClient` infrastructure (the 72 pytest tests are all pure
helpers / mocked services). Adding integration-test infra is itself a
larger scope than this PR should carry; logged as a future
consideration. The manual verification above is sufficient to ship.

Affected files: `backend/app/routers/reports.py` (~50 lines net),
`CHANGE.md`.

Architectural impact: Closes a real auth leak. The
`_authorize_report_access` helper is in-file (not lifted to `auth.py`)
because the access rule is route-specific (owner-OR-admin, not the
generic admin-only or user-only patterns that already live in `auth.py`).

Future considerations:
- Add FastAPI `TestClient`-based integration tests for the auth gate
  (and other route-level gates) as a separate scope decision. The
  precedent will probably matter for PRs 2 and 4 of the recruiter
  rollout.
- PR 2 of the rollout updates `_authorize_report_access` to add the
  `'recruiter'` arm.

---

## 26/05/2026 — Fix · CI backend job fails during pytest collection (missing env vars)
Type: Fix

**Symptom:** the `Backend (pytest)` job on GitHub Actions crashed during
test collection — before any test ran — with a pydantic `ValidationError`
on `GROQ_API_KEY` / `SUPABASE_URL` / `SUPABASE_KEY`.

**Root cause:** four app modules construct `Settings()` at module-load
time (`main.py:14`, `services/interview_orchestrator.py:9`,
`services/resume_parser.py:6`, `services/voice_service.py:11`). When
pytest imports `from app.services.interview_orchestrator import ...` to
collect tests, the import chain calls `Settings()`, which fails because
the CI runner has no env vars and no `.env` file. The test bodies
themselves never need real credentials (they use `MagicMock` for
Supabase and pure-function inputs for scoring), but collection dies
before getting there.

**Fix:** added `backend/tests/conftest.py` that calls
`os.environ.setdefault(...)` for the three required vars with
obviously-bogus placeholders. Pytest loads `conftest.py` before any
test file in its directory, so the env vars are present by the time
the import chain hits `Settings()`.

**What this does NOT change:**
- `app/config.py` is unchanged — `groq_api_key` / `supabase_url` /
  `supabase_key` remain required fields; `_strip_env` validator
  remains; pydantic-settings precedence is unchanged.
- Production deployments are unaffected — `conftest.py` lives under
  `tests/` and is never imported outside pytest. Render still requires
  real credentials at boot.
- Local devs with real `.env` or shell-exported env vars are
  unaffected — `setdefault` only fills the gap when the var is missing.

**Verified locally:**
- `python -m pytest -q` with real `.env` present → 72 passed.
- Same command with `.env` temporarily moved aside and credential env
  vars cleared (simulating CI) → 72 passed. The conftest's `setdefault`
  kicks in exactly as designed.

Affected files: `backend/tests/conftest.py` (new, ~20 lines incl.
docstring), `CHANGE.md`.

Architectural impact: None. This is a test-environment bootstrap; the
production code path doesn't see it.

Future considerations:
- The deeper smell is that `Settings()` is constructed at module-load
  time in 4 places — an import-time validation side-effect. A more
  principled fix would refactor those four modules to call
  `get_settings()` lazily at first use, and let `main.py` own the
  one early validation call for boot-time fail-fast. Tracked as
  possible follow-up in CURRENT_TASKS (deferred — would touch the
  realtime/voice pipeline which CLAUDE.md asks to keep stable, and
  the conftest fix is sufficient for now).
- If CI is later changed to use GitHub Actions repository secrets
  (`secrets.GROQ_API_KEY` etc.) wired to the workflow's `env:` block,
  the conftest's `setdefault` becomes a harmless no-op (real values
  win) and can be left in place as a belt-and-suspenders default.

---

## 26/05/2026 — UI polish C1 · Button primitive (first reusable component)
Type: Feature

Third slice of the architecture-review-driven UI polish track. Introduces
the first reusable presentational primitive: a `Button` component composing
the existing `.btn` + `.btn-{variant}` + `.btn-{size}` CSS classes.
Stress-tested via `grill-with-docs`; the resolutions trimmed the API far
below the audit's original proposal — kept only what has a present
consumer. Resolutions recorded in `CURRENT_TASKS.md` C1 section.

What changed:

New file `frontend/src/components/Button.tsx`:
- API: `variant: "primary" | "secondary" | "danger"` (no `"ghost"` — no
  CSS rule, no caller); `size: "sm" | "md" | "lg"` (md is the bare
  `.btn`); `fullWidth: boolean` (composes new `.btn-block`); `className`
  passthrough; all native button props via `...rest` (incl `style`,
  `disabled`, `onClick`, `type`).
- No polymorphism (`as` prop) — `<button>`-only. The first `<Link>` call
  site to migrate will widen it.
- No `loading` prop — existing app convention is text-swap + `disabled`,
  not spinners. Callers continue `<Button disabled={x}>{x ? '…' : '…'}</Button>`.
- No `.btn-google` variant — structural differences (full-width baked
  in, neutral palette) make it a poor variant fit; Login/Signup Google
  buttons stay as raw `<button className="btn btn-google btn-lg">`.

CSS addition (`frontend/src/index.css`, BUTTONS section):
- `.btn-block { width: 100%; }` — 5th button modifier, mirrors
  `.btn-sm` / `.btn-lg`. Backs the `fullWidth` prop.

Migrated `frontend/src/components/auth/Login.tsx`:
- Submit button `<button className="btn btn-primary btn-lg" style={{ width: '100%', ... }} disabled={submitting}>`
  → `<Button type="submit" size="lg" fullWidth disabled={submitting} style={{ marginTop: 'var(--space-sm)' }}>`.
  The inline `width: 100%` is gone (handled by `fullWidth` →
  `.btn-block`); the `marginTop: var(--space-sm)` stays inline as a
  deliberate one-off (form spacing, not a generalizable pattern).
- Google OAuth button at `:103` unchanged (out of scope per `.btn-google`
  decision).
- Added `import { Button } from '../Button'`.

Scope discipline: Login is the *only* call site migrated in this PR.
The other 23 call sites (Dashboard CTAs, Signup, CandidateUpload,
InterviewRoom, Report, AdminDashboard, AdminUserDetail, App sign-out,
CameraPreflight) keep their raw `<button className="btn …">` markup
for now. Each migrates in a follow-up PR — or, in the case of `<Link>`
call sites (Dashboard, Report, AdminUserDetail), the PR that needs
them will also widen Button to be polymorphic.

Verification:
- `npx tsc --noEmit` passes (zero output).
- Browser walk **NOT** performed by the agent — needs manual verification
  on `/login`: submit renders full-width lg primary, "Sign in" ↔
  "Signing in…" label swap during submit, disabled state visible, Google
  button unchanged, layout identical to pre-migration.

Affected files: `frontend/src/components/Button.tsx` (new),
`frontend/src/index.css` (+1 line), `frontend/src/components/auth/Login.tsx`,
`CURRENT_TASKS.md` (grill resolutions + implementation contract).

Architectural impact: First reusable presentational primitive. Establishes
the precedent that Button-shaped components compose existing CSS classes
rather than inlining styles or duplicating CSS. The 8 grill decisions
together codify a "build for the consumer in hand" stance — no
speculative API surface — that the next primitive's grill should
inherit.

Future considerations:
- The "two patterns in the codebase" smell (some buttons use `<Button>`,
  most still use raw `<button className="btn …">`) is intentional and
  acceptable for the bridge period.
- The first follow-up PR that migrates a `<Link>` call site (likely
  Dashboard's "New Interview" CTA) will widen Button to be polymorphic
  (`as` prop accepting `Link`).
- When the second primitive lands (Input? Card?), its grill answers
  "introduce `src/components/ui/` subdir now?" against a real peer.
- A proper `GoogleSignInButton` / `SocialButton` is the right eventual
  shape for the 2 OAuth call sites — separate, scoped PR.

---

## 26/05/2026 — UI polish C5 · InterviewRoom inline-style purge
Type: Refactor

Second slice of the architecture-review-driven UI polish track. Mechanical
cleanup of `style={{...}}` attributes in `InterviewRoom.tsx`, no
architectural change. Stress-tested via `grill-with-docs` before
implementation; resolutions recorded in `CURRENT_TASKS.md` C5 section.

What changed:

CSS (`frontend/src/index.css`, additions only, in existing sections):
- New `.btn-sm` size modifier (`padding: 0.375rem 0.75rem; font-size: 0.8125rem`)
  beside existing `.btn-lg`. Completes the half-built button size scale and
  hands C1 (Button primitive, queued next) a ready-made `size="sm"` target.
- New `.interview-header-actions` (mirror of `.interview-info` for the
  right-hand cluster — progress dots + timer + End button).
- New `.interview-info-subtitle` (font-size 0.8125rem, text-tertiary) plus
  scoped `.interview-info h4 { margin: 0; }` to handle the heading-tag
  semantic change.
- New cascade rules `.turn-pill.ready .turn-dot { background: var(--accent-green); }`
  and `.turn-pill.live .turn-dot { background: var(--accent-rose); }`. The
  pill's state class is now the single source of truth for the dot color
  — no per-instance class or inline style needed.

JSX (`frontend/src/components/InterviewRoom.tsx`, 8 edits):
- `:435`, `:457` — Deleted redundant `marginTop` inline (`.iv-connect-state`
  already provides `gap: var(--space-md)`).
- `:481` — `<h3 style={{ fontSize: '0.9375rem', marginBottom: '2px' }}>` →
  `<h4>` per ADR 0003 ("future agents writing `<h1>Foo</h1>` get the
  correct size automatically, with no class to remember"). The scoped
  `.interview-info h4 { margin: 0; }` handles the spacing.
- `:484` — `<p style={{...}}>` → `<p className="interview-info-subtitle">`.
- `:490` — Inline flex container → `<div className="interview-header-actions">`.
- `:511` — End button inline `padding` + `fontSize` → `btn btn-danger btn-sm`.
- `:604`, `:617` — Inline `background` on `.turn-dot` removed; the new
  cascade rules from `.turn-pill.ready` / `.turn-pill.live` own the color.
  Kept `pulse` class on the recording-state dot for the speech-detected
  animation.

Left alone (data-driven, must stay inline): the voice-wave-bar
height/opacity (now `:618`, was `:626` — line shifted) is computed from
live audio level every render; it cannot be a static class.

Verification:
- `npx tsc --noEmit` passes (zero output).
- Inline-style grep on `InterviewRoom.tsx` shows exactly one remaining hit
  (the data-driven voice-wave-bar, as expected).
- Browser walk **NOT** performed by the agent — needs manual verification
  on the terminated screen, lost-connection screen, header layout at
  360 / 768 / 1440 widths, and all five turn-pill states (`connecting`,
  `ai_speaking`, `ready`, `recording`, `transcribing`).

Affected files: `frontend/src/index.css`,
`frontend/src/components/InterviewRoom.tsx`,
`CURRENT_TASKS.md` (grill resolutions + implementation contract).

Architectural impact: None — pure presentation cleanup. The new `.btn-sm`
is a deliberate pre-investment for C1 (the Button primitive will compose
`btn btn-{variant} btn-{size}`), not scope creep. Cascade-from-parent on
`.turn-pill` state continues the project's preference for one canonical
source of truth per concept (analogous to C4's deletion of bespoke
`.page-title` / `.onboard-title` / `.panel-title` in favor of the global
heading scale).

Future considerations: C1 (Button primitive) is now unblocked and
slightly cheaper — it inherits the completed `btn-sm`/`btn-lg` size
modifier pair.

---

## 25/05/2026 — UI polish C4 · heading scale &amp; typography rhythm
Type: Refactor

First slice of the architecture-review-driven UI polish (analysis-only HTML
report at `C:\Users\ibtes\AppData\Local\Temp\architecture-review-2026-05-25-frontend.html`).
Stress-tested via the `grill-with-docs` skill; the design decision is locked
in `docs/adr/0003-in-app-heading-scale-is-restrained.md` so future
architecture reviews don't re-relitigate it.

What changed:

Global heading scale (`src/index.css`):
- h1: 2.5rem 700 → **1.75rem 600** (-0.022em)
- h2: 1.75rem → **1.375rem** (-0.018em)
- h3: 1.25rem → **1.125rem** (-0.014em)
- h4: 1rem → **0.9375rem** (-0.010em)
- Plus rhythm rules: `h1 { margin-bottom: var(--space-md); }`,
  `h3 { margin-bottom: var(--space-md); }`,
  `.page-head { margin-bottom: var(--space-2xl); }`
- Plus two scoped overrides where the global margin would offset flex
  children: `.panel-head h3 { margin-bottom: 0; }` and
  `.onboard-head h3 { margin-bottom: var(--space-xs); }`,
  and `.page-head h1 { margin-bottom: 0; }` (the page-head's own bottom
  margin owns the spacing to the next block).

Bespoke title classes:
- `.page-title` — DELETED (4 JSX call sites un-classed: `App.tsx:74`,
  `Dashboard.tsx:85`, `AdminDashboard.tsx:64`, `AdminUserDetail.tsx:67`).
  The global h1 rule now matches what `.page-title` used to override to.
- `.card-title` — DELETED from CSS (was defined but never used; dead code).
- `.onboard-title` — DELETED; `CandidateUpload.tsx:136` changed from
  `<h2 className="onboard-title">` to `<h3>`. Semantic fix: the page
  already has an `<h1>New interview</h1>` above this card, so the card's
  own heading is subordinate.
- `.panel-title` — DELETED (9 JSX call sites un-classed across Dashboard,
  Report, AdminDashboard, AdminUserDetail). Bare `<h3>` now renders
  correctly. The single non-h3 site (a `<span>` inside the transcript
  toggle button in `Report.tsx:259`) gets its visual styling from a new
  scoped selector `.transcript-toggle > span:first-child` instead.
- `.auth-title` — slimmed to just `text-align: center;`. The size/weight
  override is gone (h1 native rule covers it); the centering is preserved
  because `.auth-card` is a normal block, not a flex container. Both
  Login and Signup keep `className="auth-title"` for the centering intent.

Out of scope (deliberate):
- `.hero-title` not added — no landing page exists today; YAGNI per
  stability phase. When/if a landing surface is built, it opts in then.
- `.features-grid` / `.feature-card` are dead CSS — flagged for a separate
  cleanup PR; not touched here.

Hard constraints honoured:
- No new tokens, no new dependencies, no React component changes.
- No new files except the ADR.
- Realtime / voice / orchestrator — untouched.
- Backend untouched.
- The "user input authoritative" rule + integrity surface — untouched.

Verified:
- `npx tsc --noEmit` clean.
- `npm run test` — Vitest 14/14 pass in ~385ms.
- Manual browser walk-through completed by the user across Dashboard,
  /new, Login, Signup, Report, /admin, /admin/users/:id, and a mobile
  width. No regressions observed; the restrained premium-app direction
  reads as cleaner.

Affected files:
- new: docs/adr/0003-in-app-heading-scale-is-restrained.md
- modified: frontend/src/index.css,
  frontend/src/App.tsx,
  frontend/src/components/Dashboard.tsx,
  frontend/src/components/CandidateUpload.tsx,
  frontend/src/components/Report.tsx,
  frontend/src/components/admin/AdminDashboard.tsx,
  frontend/src/components/admin/AdminUserDetail.tsx
- docs: CHANGE.md, CHANGELOG.md, CURRENT_TASKS.md

Architectural impact: None on the runtime. The semantic h1–h4 scale now
matches the visual hierarchy on every in-app page. Future contributors
writing `<h1>Foo</h1>` get the right size automatically; no className
cargo-culting required. ADR 0003 records the "premium-app over
premium-marketing" decision so the next architecture review doesn't
suggest bumping the scale back up.

Future considerations:
- Candidate 5 from the architecture review (InterviewRoom inline-style
  purge) is the next slice. Separate grilling pass + PR per the user's
  instruction "Do not batch all candidates into one PR".
- Candidate 1 (Button primitive) lands after Candidate 5.
- `.features-grid` / `.feature-card` dead-CSS cleanup is queued as a
  follow-up; not part of any of the three planned candidates.
- The transcript toggle uses a non-semantic `<span>` styled like an h3.
  Acceptable because the parent is a `<button>` (a heading would be
  awkward HTML there), but worth a code-review eye if the toggle pattern
  appears elsewhere — a `Heading-as-label` utility class might be worth
  introducing then.

## 25/05/2026 02:15 — Render keep-alive via UptimeRobot
Type: Decision (deploy / external infra)

External keep-alive configured to eliminate Render free-tier cold starts
(50–60 s on first user hit after 15 min idle). No code change. No
architecture change.

**Chosen:** UptimeRobot HTTP(S) monitor, 5-min interval, pointed at
`https://interview-web-app.onrender.com/health`. Alerting email enabled
on non-2xx responses.

**Why UptimeRobot over cron-job.org:**
- 5-min interval is 3× under Render's 15-min sleep threshold (safety
  margin even if a few pings are throttled/dropped).
- Alerting on non-2xx ships free — cron-job.org has weaker alerting.
- Purpose-built UI for HTTP monitoring; uptime history + response-time
  graphs come along.
- cron-job.org's only edge is sub-minute scheduling; not needed here.

**Cost:** $0. UptimeRobot free tier — 50 monitors, 5-min minimum
interval, email alerts. No credit card required.

**`/health` characteristics** (worth recording so nobody adds DB
checks here):
- Defined at `backend/app/main.py:72-74`.
- Async, no DB hit, returns `{"status": "healthy"}`.
- Hit ~288×/day by the monitor — heavy work here would burn Render
  quota for zero operational gain. If/when we want deeper internal
  health checks, that's a separate endpoint (`/ready`), not `/health`.

**Rollback path:** pause the monitor in UptimeRobot (one click). Render
will sleep again after 15 min idle; the WebSocket retry budget covers
the next cold start.

**Architecture invariants preserved:**
- No new code paths.
- No new dependencies.
- `/health` contract unchanged.
- The realtime / voice / orchestrator pipeline is untouched.

Affected files:
- modified: PROJECT_STATE.md (deploy action #3 marked configured;
  ADR-0002 gap annotated to note the cold-start mitigation),
  CURRENT_TASKS.md (item moved Now → Done), CHANGE.md
- memory: new `reference_uptimerobot_keepalive.md`, MEMORY.md index
  updated
- deploy: UptimeRobot monitor (external; not in repo)

Architectural impact: None on the runtime. Removes the cold-start
failure mode from the user's first-of-the-day request.

Future considerations:
- If we ever migrate off Render free tier, the monitor stops being
  load-bearing and can be repurposed as pure uptime monitoring (the
  alerting half is still useful).
- The 5-min ping rate is the free-tier floor. If we want lower
  latency on `/health` failure detection, that's a paid tier
  upgrade — not justified at current volume.
- If `/health` ever needs DB-aware checks, add a SEPARATE endpoint
  (e.g. `/ready` returning DB status); do NOT modify `/health`. The
  external monitor calls `/health` ~288×/day; adding cost there
  would burn Render quota for zero monitoring benefit.

## 25/05/2026 01:45 — tighten FRONTEND_ORIGIN_REGEX for production
Type: Decision / Fix (deploy + docs)

Closed the wide-open CORS gap from `PROJECT_STATE.md`. The default
`https://.*\.vercel\.app` was a template-friendly fallback but allowed
any *.vercel.app site to call the production API. Now anchored to the
project prefix on Render via env var.

Production value (set in Render dashboard → Environment →
FRONTEND_ORIGIN_REGEX → save → rolling restart):

    ^https://interview-web-app(-[a-z0-9-]+)?\.vercel\.app$

Matches:
- Production: `interview-web-app-lyart.vercel.app`
- Branch previews: `interview-web-app-git-<branch>-lyart.vercel.app`
- Commit previews: `interview-web-app-<hash>-lyart.vercel.app`

Blocks: any unrelated `*.vercel.app` site.

Code changes (no behaviour change; clarifies the template):
- `backend/.env.example`: rewrote the `FRONTEND_ORIGIN_REGEX` comment
  block to call out the wildcard default as "too permissive for
  production" and give the explicit project-prefix template plus this
  project's worked example. The default value in the file is unchanged
  (kept wildcard so first-time clones still work without override).
- `backend/app/config.py`: brought the in-code comment in line with the
  env.example — points readers at the template for the override syntax.

The default in `config.py` stays wildcard intentionally:
- This keeps the repo viable as a template — a fresh clone still works
  without the operator needing to figure out CORS first.
- The production tightening is an operational override, not a code
  change. Render's env var takes precedence over the default; the only
  way this default fires in production is if the env var is missing or
  malformed, which the existing `_strip_env` validator already guards
  against for whitespace mistakes.

Hard constraints honoured:
- No runtime behaviour change in the test suites.
- No new dependencies.
- The Render env var change is the only operational action.

Verified:
- Backend imports clean.
- `python -m pytest`: 72/72 still pass (no test touches CORS config).
- Frontend `npx tsc --noEmit` clean; Vitest 14/14 still pass.

Affected files:
- modified: backend/.env.example, backend/app/config.py
- deploy: Render env var `FRONTEND_ORIGIN_REGEX` (manual step)
- docs: CHANGE.md, PROJECT_STATE.md, CURRENT_TASKS.md, CHANGELOG.md

Architectural impact: None on the runtime; reduces blast radius of a
hypothetical compromised third-party Vercel project that might try to
hit our API.

Future considerations:
- If the project ever migrates to a custom domain, the regex should be
  replaced with an exact-origin entry in `FRONTEND_ORIGINS` (the
  comma-separated allowlist sibling of the regex). `.env.example`
  already documents that path.
- A pytest unit test for the CORS regex (e.g. "my-app-lyart.vercel.app
  matches; evil.vercel.app does not") would close the regression loop
  end-to-end, but adds a brittle test that ties tightly to the slug.
  Skipped under the "no new feature branches" phase rule.

## 25/05/2026 01:15 — pytest for the scoring helpers (41 new tests)
Type: Feature

Adds `backend/tests/test_scoring.py` (41 tests) covering the four shared
scoring helpers in `services/interview_orchestrator.py`. These functions
drive the detailed report, the candidate dashboard, and the admin
aggregations — a regression here moves dashboard numbers silently. The
suite is the regression guard the stability phase asked for.

Coverage:
- `compute_phase_scores`:
  - Empty input → empty dict; phases with no evals are omitted; unknown
    phase numbers (0 / 99+) are silently dropped.
  - **Phase 1** (warm-up): pins the 0.25 / 0.25 / 0.2 / 0.3 weights;
    weights sum to 1; explicit weighted-calculation case; averaging
    across multiple evals.
  - **Phase 2/3 historical**: pins the three-axis formula
    (0.5 / 0.3 / 0.2). Documents the subtle behaviour I initially
    misread — an eval with `depth_score` but no `details.clarity`
    runs the three-axis formula with `avg_clarity=0`, NOT the
    0.7/0.3 fallback. The fallback only fires in the genuinely
    degenerate case (depth_score is None AND details is falsy across
    all evals).
  - **Phase 2/3 layer-aware**: pins the 0.4 / 0.25 / 0.15 / 0.2
    formula; `min(max_layer, 5)/5 * 10` clamp guard for legacy
    drill_level data that exceeds 5; a single eval with
    `details.layer` flips the entire phase to layer-aware; `max_layer`
    in result is the raw max (not clamped).
  - **Phase 4**: `correct_answers` threshold is `accuracy >= 7`;
    `overall` is the average accuracy.
  - **Phase 5**: five facets averaged; overall is the mean of all
    facet values across all evals.
- `compute_final_score`:
  - **PHASE_WEIGHTS sum to 1.0** (the invariant — if it drifts every
    final score in the system moves silently).
  - Phase 1 is NOT weighted into the final (warm-up by design).
  - Empty input → 0; uniform 10 → 10; explicit weighted average
    (8*.30 + 7*.25 + 6*.30 + 5*.15 = 6.70); partial-phase
    renormalisation; missing `overall` key treated as 0.
- `recommendation_for`: parametrised across all four threshold bands
  including exact boundaries (10.0, 8.5, 8.49, 7.0, 6.99, 5.5, 5.49,
  0.0) — boundary inputs are the failure mode the test pins down
  (a 7.0 candidate must be Hire, not Hold).
- `score_interviews_bulk` (PROJECT_STATE invariant #5 — bulk queries):
  - Empty id list short-circuits with NO DB call.
  - **N interviews → exactly one `.table("evaluations")` call** — the
    N+1 regression guard the whole helper exists for.
  - `.in_("interview_id", ids)` keyed on the full id list.
  - Each requested id appears in the result with score + question
    count; ids with no evals get `{score: 0, questions: 0}`.
  - Per-interview grouping is isolated (iv-A's accuracy=10 doesn't
    leak into iv-B's accuracy=2 score).
  - Unrequested ids in the eval batch are dropped (defensive — should
    not happen, but the helper must not crash).

The test module uses tiny named builders (`_phase1_eval`,
`_deep_dive_eval`, etc.) so the assertions read like specs over the
formulas, not over raw dicts. Supabase is `MagicMock`-stubbed for
`score_interviews_bulk` — no DB, no network.

Verified:
- `python -m pytest`: 72/72 pass in 0.63s (31 prior + 41 new).
- Frontend Vitest 14/14 still pass.

Affected files:
- new: backend/tests/test_scoring.py
- docs: CHANGE.md, CURRENT_TASKS.md, CHANGELOG.md, PROJECT_STATE.md

Architectural impact: None on the runtime. Adds a regression guard
around the shared scoring path. Future agents touching
`compute_phase_scores`, `compute_final_score`, `recommendation_for`, or
`score_interviews_bulk` should treat these tests as the documented
contract.

Future considerations:
- The 0.7/0.3 fallback in the historical phase-2/3 formula is nearly
  unreachable (requires depth_score=None AND falsy details across
  EVERY eval row). It's only triggered by very old/degenerate data.
  Worth flagging for removal if a code-cleanup PR lands in this area
  — but ADR 0001's "forward-only scoring" rule means the historical
  branch as a whole stays.
- The phase-4 `if e.get("accuracy_score")` filter is a falsy filter
  (it drops `0` scores) — the test pins this behaviour but it's a
  potential source of confusion if a future change replaces it with
  `is not None`. The `is not None` filter is used in the phase-2/3
  branch — consistency would be a small clarity win.
- Next-best test target after this: `app.routers.reports` (the
  detailed report endpoint, which orchestrates these helpers + the
  integrity-events query). Less pure but the highest-value
  user-facing surface still without a test.

## 25/05/2026 00:45 — remove dead resume-parser `field_specialization` inference
Type: Refactor

Burn-down of the dead-code item from `CURRENT_TASKS.md`. After commit
`b97597f` (the "Web Dev candidate gets ML questions" fix) the resume
parser's inferred `field_specialization` stopped being adopted on writes
for any row where the user had set the field — which is every new row.
The legacy-row fallback (lines 122-123 of `candidates.py`) was the only
remaining caller, and it had the failure mode the principle was created
to forbid: the parser is constrained to four ML-adjacent labels
(nlp/cv/ml/research) and falls back to "ml" on failure, so the
"legacy-row" branch would silently label a Marketing / Design / Web Dev
candidate "ml". Promoting "user input authoritative" to a `CLAUDE.md`
Engineering Rule (CHANGE 25/05/2026 00:15) made keeping this code an
explicit contradiction.

Removed:
- `services/resume_parser.py`: the `field_specialization` extraction
  instructions in both prompts (`_parse_with_file_id` and `_parse_text`),
  the key in `_parse_response`'s success + JSON-decode-failure dicts,
  and the key in the two pdf-extraction fallback dicts at the top and
  bottom of the module. The parser is now scoped to what it does well:
  name, sections, full_text, primary_project.
- `routers/candidates.py`:
  - `parse_resume_only` response: removed the inferred
    `field_specialization` from the JSONResponse body. The function is
    a diagnostic endpoint; the inferred value was the most misleading
    field it exposed.
  - `upload_resume`: dropped the `if not candidate.get(
    "field_specialization"): update_payload["field_specialization"] =
    parsed_data["field_specialization"]` branch and the long comment
    explaining why we *didn't* adopt it. With the inference gone from
    the parser, the branch couldn't fire anyway — clearing it removes
    the dead conditional and the obsolete commentary.
  - `ResumeUploadResponse.field_specialization`: now sourced from the
    candidate row (`candidate.get("field_specialization") or "general"`)
    instead of `parsed_data`. Same wire shape as before; the value is
    now authoritative (user choice) instead of advisory (inference).
- `app/test_resume.py`: dropped the print line that surfaced
  `field_specialization` from the parser result. The file is a manual
  smoke script (not picked up by pytest — testpaths is `tests/`).

What stayed (intentional, do NOT remove):
- The `field_specialization` DB column and every read path
  (`orchestrator`, `dashboard`, `admin`, `interview_session`,
  `routers/candidates.create_candidate`). These all read the
  authoritative user value the form writes via `CandidateCreate`.
- The schema declarations in `models/schemas.py` — these declare DB
  columns / API response fields, not parser output.

Verified:
- Backend imports clean (`python -c "from app.main import app"`).
- `python -m pytest`: 31/31 pass in 0.51s.
- Frontend `npx tsc --noEmit` clean; Vitest 14/14 pass.
- `grep field_specialization backend/`: the only remaining references
  are legitimate (DB column, schema fields, read paths,
  user-form-driven create).

Affected files:
- modified: backend/app/services/resume_parser.py,
  backend/app/routers/candidates.py, backend/app/test_resume.py
- docs: CHANGE.md, PROJECT_STATE.md, CURRENT_TASKS.md, CHANGELOG.md

Architectural impact: None. The wire shape of all endpoints is
preserved. The parser's return contract loses one optional key; only
internal callers consume parser output, and they were already updated
in commit `b97597f` to ignore the inferred field. The "candidate-field"
column reads everywhere in the codebase continue to point at the
authoritative user value.

Future considerations:
- `models/schemas.py:31` has `field_specialization: str` (required) on
  `ResumeUploadResponse`. The frontend already ignores the field; if
  another consumer ever needs it removed, the upgrade path is
  `Optional[str]` with no default, then remove in a later release.
- `routers/candidates.py:63` still has `candidate.field_specialization or "ml"`
  as the default when `create_candidate` receives an empty field. The
  "user input authoritative" rule doesn't apply (no user input to
  preserve), but the choice of "ml" vs "general" as the fallback is a
  product question — the orchestrator and dashboard already use
  "general" as their own fallbacks (`interview_orchestrator.py:501`,
  `dashboard.py:53`). One-line consistency fix sized S if/when product
  decides.

## 25/05/2026 00:15 — promote "user input authoritative" to a CLAUDE.md rule
Type: Decision

Promoted the long-standing project principle into a formal `CLAUDE.md`
Engineering Rule so it lands in every session's startup read. Origin: the
resume-parser bug fix (commit `b97597f`, CHANGE 23/05/2026). The
principle has been an informal invariant + a memory entry since; landing
the integrity rollout cleared the integrity surface to write down rules.

Rule wording (now in `CLAUDE.md` → Engineering Rules):

> User-provided input at API boundaries is authoritative; LLM/parser/
> heuristic-derived data is advisory. Never silently overwrite a field
> the user has explicitly set. If you must persist inferred data
> alongside it, store it separately (e.g. an `inferred_*` column or a
> suggestion the UI can offer) — never blow away the user's choice.
> Code-review red flag: any `update({field: parsed_data[field]})` next
> to a `update({user_text: ...})` for the same row.

Side effects:
- `PROJECT_STATE.md` invariant #6 updated to point at the CLAUDE.md rule
  as the authoritative source.
- `CURRENT_TASKS.md`: item moved from "Now / Maintainability" to "Done in
  this phase".
- Auto-memory entry rewritten to describe itself as a historical pointer
  (origin + code-review heuristic) — CLAUDE.md is the load-bearing copy.

Affected files:
- modified: CLAUDE.md (Engineering Rules section), PROJECT_STATE.md
  (invariant #6 wording), CURRENT_TASKS.md (move to Done)
- memory: project_user_input_authoritative.md rewritten;
  MEMORY.md index line updated

Architectural impact: None on the runtime. The rule already governed
review/PR decisions informally; now it governs them visibly.

Future considerations:
- The code-review heuristic (the "`update({field: parsed_data[field]})`
  next to `update({user_text: ...})`" smell) lives only in the memory
  file and CLAUDE.md. It's specific enough that a grep-based pre-commit
  hook is feasible if this class re-occurs.
- The candidate pipeline (`routers/candidates.py:upload_resume`) is the
  only place this currently matters. If a second user-vs-inferred-data
  surface appears (e.g. interview goals, skill tags), this is the rule
  that governs how to wire it.

## 24/05/2026 23:55 — phase shift: stability + scalability
Type: Decision

The repository enters a declared **stability + scalability** phase. The
integrity rollout (Phases A → C + WS-disconnect bypass close) is shipped,
the first automated test suites are in place (14 Vitest + 31 pytest), CI
runs on every push and PR, and branch protection on `main` makes the
suites required checks. The product is production-deployed and the
integrity surface is load-bearing — adding feature-shaped change now
would dilute that and re-open the "surface area without coverage" gap
the test suites just closed.

Phase policy (DO NOT violate without an explicit user decision):
- No large new feature branches.
- Work is bounded to four buckets: maintainability, scaling safety,
  reliability, production hardening.
- The prioritised slice of work-we-are-willing-to-do-now lives in
  the new `CURRENT_TASKS.md`. The full backlog (including deferred
  items) stays in `IMPLEMENTATION_ROADMAP.md`.

Merge gates on `main` (configured via GitHub branch protection 2026-05-24):
- Required status checks: `Frontend (tsc + vitest)`,
  `Backend (pytest)` — defined in `.github/workflows/ci.yml`.
- Branches must be up to date with `main` before merging.
- Force-pushes blocked.

What this means in practice for future agents:
- When suggesting next work, pull from `CURRENT_TASKS.md`'s "Now"
  section, not from `IMPLEMENTATION_ROADMAP.md`'s deferred backlog.
- Anything sized **L** is deferred until the user explicitly promotes
  it out.
- If the user asks for something feature-shaped, confirm the phase shift
  before agreeing — they may have changed direction and want this
  policy updated.
- Touching `IntegrityMonitor`, `_finalize_status`, or `normalizeWsHost`
  means running both suites and adding tests for any new branch. The
  suites document the contracts those changes must preserve.

Affected files:
- new: CURRENT_TASKS.md
- modified: PROJECT_STATE.md (phase + CI gates sections),
  memory index + new `project_stability_scalability_phase.md` and
  updated `reference_project_docs.md`
- docs: CHANGE.md

Architectural impact: None on the runtime. The change is a policy
declaration plus a task-board file. Future planning will route through
`CURRENT_TASKS.md` first.

Future considerations:
- Coverage CI steps deferred in `CURRENT_TASKS.md` (per the rationale
  there). Re-evaluate after one round of "add tests when touching code"
  has happened.
- The "user input authoritative" memory is now a candidate for promotion
  into `CLAUDE.md` during this phase (sized S in `CURRENT_TASKS.md`).
  If/when promoted, remove the duplicated memory line and replace it
  with a pointer to the CLAUDE.md section.
- If interview drop-rate telemetry ever justifies orchestrator state
  persistence (ADR 0002), that promotion happens by editing the
  "Deferred" section of `CURRENT_TASKS.md` first, not by jumping
  straight to implementation.

## 24/05/2026 23:30 — CI workflow runs both test suites
Type: Feature

GitHub Actions workflow that runs the Vitest + pytest suites on every push
to `main` and every pull request, so the test discipline added an hour ago
becomes an enforced gate instead of a manual one.

`.github/workflows/ci.yml`:
- Two parallel jobs (`frontend`, `backend`) — independent, no cross-deps.
- `concurrency` group cancels superseded runs on the same ref so a fast
  PR-update loop doesn't pile up duplicate jobs.
- Frontend job: Node 20 (LTS), npm cache keyed on `frontend/package-lock.json`,
  `npm ci` → `npx tsc --noEmit` → `npm run test`. Type-check is included
  because CLAUDE.md already treats it as a gate; folding it into CI removes
  the manual step.
- Backend job: Python 3.10 (matches local pin), pip cache keyed on
  `backend/requirements-dev.txt`, `pip install -r requirements-dev.txt`
  → `python -m pytest -v`.

Env-var posture:
- Tests don't trigger env loading. `get_settings()` is `@lru_cache`d and only
  called inside `get_supabase()`, which the tests bypass by setting
  `monitor._supabase` directly. Verified locally by running pytest with
  GROQ_API_KEY / SUPABASE_URL / SUPABASE_KEY unset — 31/31 pass. So no CI
  secrets needed for this workflow.
- `npm run test` doesn't touch `import.meta.env` because `normalizeWsHost`
  was moved into its own `wsHost.ts` (no side-effect imports). Verified
  earlier today.

Hard constraints honoured:
- No production behaviour change.
- No new runtime dependencies.
- Realtime / voice / orchestrator — untouched.

How to read failures:
- The `Frontend` job covers TS errors and Vitest regressions in
  `normalizeWsHost`. Failures here usually mean a contract change in
  websocket.ts or a regression in URL parsing.
- The `Backend` job covers IntegrityMonitor / threshold / _finalize_status.
  Failures here usually mean someone shifted SEVERITY_WEIGHT, MAX_WARNINGS,
  or one of the completion paths in `interview_session.py` — re-read
  CHANGE 24/05/2026 17:30 (WS bypass close) before touching those.

Affected files:
- new: .github/workflows/ci.yml
- docs: PROJECT_STATE.md, CHANGELOG.md, IMPLEMENTATION_ROADMAP.md,
  CHANGE.md

Architectural impact: None on the runtime; adds a required-green gate on
the GitHub side. Future work that breaks `IntegrityMonitor.record_event`
or `_finalize_status` will visibly fail before merge instead of silently
shipping.

Future considerations:
- The workflow does NOT yet require itself as a branch-protection check.
  That's a one-click GitHub settings change once we've seen a couple of
  green runs. After that, no PR can merge with red CI.
- A coverage step (`pytest --cov` / `vitest --coverage`) would let us
  track which areas grow tests over time. Skipped here to keep this change
  minimal and production-safe per the user's brief.
- The two suites are fast (<1s pytest, <500ms vitest) — total CI wall time
  will be dominated by setup/install. If that becomes painful, the cache
  steps already in place should keep cold installs to ~30s.

## 24/05/2026 22:50 — first automated test suite (Vitest + pytest)
Type: Feature

Lands the first automated tests in the project. Scope strictly bounded to
four targets named in `IMPLEMENTATION_ROADMAP.md` (Vitest line + adjacent
roadmap items): `normalizeWsHost`, `IntegrityMonitor.record_event`, the
warning-threshold logic, and `_finalize_status` (interview-termination
logic). 45 tests total, all green.

Frontend (Vitest, 14 tests):
- Extracted `normalizeWsHost` from `services/websocket.ts` into a tiny new
  `services/wsHost.ts`. Pure helper, zero behaviour change — but websocket.ts
  imports the Supabase client at module load (it throws if VITE_SUPABASE_URL
  is unset), which would have made the test file fragile to env stubbing.
  Splitting the helper out is a single-purpose file with no side effects,
  testable without any env setup. websocket.ts now re-imports it.
- New `frontend/src/services/__tests__/wsHost.test.ts` covers: fallback on
  undefined / empty / whitespace; clean passthrough; whitespace + trailing-
  slash + trailing-newline strip; https→wss and http→ws rewrite (incl.
  case-insensitive); duplicate-host de-dup with the console.warn assertion;
  clean URLs do NOT warn; trailing-slash + dup combined.
- `frontend/package.json`: added `vitest: ^1.6.0` devDependency,
  `test: "vitest run"`, `test:watch: "vitest"`. Vite 5 / Vitest 1.x.

Backend (pytest, 31 tests):
- New `backend/requirements-dev.txt` (`-r requirements.txt` + `pytest==7.4.3`)
  kept separate from `requirements.txt` so the Render production build
  doesn't pull testing extras.
- New `backend/pytest.ini` pointing `testpaths` at `tests/`.
- `tests/test_integrity_monitor.py` — three test classes:
  - `TestSeverityMapping`: pins the `EVENT_TYPES` / `SEVERITY_WEIGHT` tables
    as the WS contract with the frontend (Phase A/B/C event types →
    documented severities; info=0, warning=1, critical=2).
  - `TestRecordEvent`: warning +1, critical +2, unknown event → info / 0,
    metadata default + pass-through, event_type carry-through, DB failure
    does not raise and still counts (the "in-memory counter is
    authoritative" invariant).
  - `TestWarningThreshold`: three warnings terminate; one critical + one
    warning terminate; two criticals terminate; one critical alone does
    NOT terminate (the explicit Phase C design decision); two warnings
    don't terminate; info events never contribute; terminate stays True
    after threshold is crossed.
  - `TestMarkTerminated`: writes `terminated_integrity`, targets the
    correct interview row, DB failure does not raise.
- `tests/test_interview_session.py` — two test classes:
  - `TestFinalizeStatus`: no monitor / below / one-below / at / over
    threshold; DB failure swallow; `completed_at='now()'` is written; row
    targeting via `.eq('id', ...)`; table is `interviews`.
  - `TestBypassPrevention`: explicit regression guards for the WS-disconnect
    bypass closed earlier today — end_interview path with threshold crossed
    → terminated_integrity; natural completion with threshold crossed →
    terminated_integrity; natural completion with a single stray warning
    → completed (markdown badge handles surfacing).
- Tests use `unittest.mock.MagicMock` for the Supabase client; no DB or
  network access. `IntegrityMonitor`'s lazy `_supabase` attribute is set
  directly to short-circuit `get_supabase()`. A tiny `_FakeIntegrity` is
  used in the session tests so they don't transitively depend on the real
  monitor's wiring (`_finalize_status` only reads two attributes).

How to run:
- Frontend: `cd frontend && npm run test` (one-shot) or
  `npm run test:watch` (TDD loop).
- Backend: `cd backend && python -m pytest` (autodiscovers `tests/`).

Hard constraints honoured:
- No production code behaviour change. `normalizeWsHost` was moved into a
  new file but is functionally identical; `websocket.ts` re-imports it.
- No new runtime dependencies. `vitest` is devDependencies; `pytest` is in
  `requirements-dev.txt`, NOT `requirements.txt`.
- Realtime / voice / orchestrator / WS contract — all untouched.

Verified:
- Frontend `npx tsc --noEmit` clean.
- `npm run test` — 14/14 pass in 378ms.
- `python -m pytest -v` — 31/31 pass in 0.73s.

Affected files:
- new: frontend/src/services/wsHost.ts,
  frontend/src/services/__tests__/wsHost.test.ts,
  backend/requirements-dev.txt, backend/pytest.ini,
  backend/tests/test_integrity_monitor.py,
  backend/tests/test_interview_session.py
- modified: frontend/src/services/websocket.ts,
  frontend/package.json, frontend/package-lock.json

Architectural impact: None on the runtime. The codebase now has a
test-running discipline — every future change to `IntegrityMonitor`,
`_finalize_status`, or `normalizeWsHost` should run these suites before
merge. Future agents: please add tests when touching code under
`integrity_monitor.py`, the completion paths in `interview_session.py`,
or `wsHost.ts`; the existing tests document the contracts those changes
must preserve.

Future considerations:
- Pre-commit / CI hook to run both suites would let us treat these as
  required-green gates instead of advisory. Currently a manual discipline.
- The orchestrator's scoring helpers (`compute_phase_scores`,
  `compute_final_score`, `score_interviews_bulk`) are the next-best
  targets for unit tests — pure functions, no side effects, and they
  drive the dashboard aggregates.
- `_finalize_status` is currently tested via direct import; an
  integration-style test that exercises a real WebSocket handshake would
  cover the call-site wiring, but needs `httpx` AsyncClient + a stubbed
  Supabase. Sized M.

## 24/05/2026 17:30 — close WS-disconnect integrity bypass
Type: Fix

Closes the last known integrity bypass from `PROJECT_STATE.md`: a candidate
could close the WebSocket (or send `end_interview` immediately after the
third warning) to land on `status='completed'` and skip
`terminated_integrity`. The in-memory integrity counter already had the
authoritative count, but no completion path consulted it.

Backend (`routers/interview_session.py`):
- New `_finalize_status(supabase, interview_id, integrity)` helper. Reads
  the in-memory counter; writes `terminated_integrity` when
  `warning_count >= MAX_WARNINGS`, else `completed`. Single source of truth
  for the terminal status, used by all four completion paths
  (early-end-by-keyword, natural final-question, `[Interview Complete]`
  marker, explicit `end_interview` message).
- New `_emit_interview_ended(websocket, status)` companion. When the helper
  upgrades to `terminated_integrity`, the `interview_ended` frame carries
  `reason='integrity_terminated'` so the client lands on the existing
  terminal screen instead of the normal report flow. Same WS message
  contract as Phase A — no new types.
- `WebSocketDisconnect` branch now calls `integrity.mark_terminated()` if
  the counter is at or above threshold. The `integrity` reference was
  hoisted to before the `try` so the disconnect handler can see it.
  Natural drops with no warnings stay un-finalised (ADR 0002: terminal).

Report markdown badge (`services/interview_orchestrator.py`,
`ReportGenerator.generate_markdown_report`):
- Inserts a "Flagged for integrity review" blockquote near the top of the
  report when `integrity_events.terminated` is true (stronger copy:
  "interview terminated by the integrity monitor") or `count >= 1`
  (singular/plural-aware event count). Reads the optional
  `integrity_events` field already added in Phase B; no new query.

Hard constraints honoured:
- No new WS message types, no new DB columns, no new endpoints. Only the
  set of values written to the existing `interviews.status` column.
- Realtime turn flow, voice pipeline, orchestrator, Matryoshka layer
  engine — all untouched.
- Aggregation queries already treat anything that isn't `completed` as
  non-completed for dashboard scoring; the bypass fix moves bypassed
  interviews from `completed` to `terminated_integrity`, which the
  scoring queries already ignore.

Verified:
- Backend imports clean.
- `_finalize_status` table-tested across five branches: no monitor,
  below/at/over threshold, DB failure.
- `generate_markdown_report` table-tested across no integrity / count=0 /
  count=1 / count=2 / terminated — all assertions pass.
- Frontend `npx tsc --noEmit` clean (no contract change).

Affected files:
- modified: backend/app/routers/interview_session.py,
  backend/app/services/interview_orchestrator.py
- docs: PROJECT_STATE.md, IMPLEMENTATION_ROADMAP.md, CHANGELOG.md,
  CHANGE.md

Architectural impact: None. Same WS channel, same termination path, same
status vocabulary. The new helper is the only completion-path writer for
`interviews.status` in the session router, which makes future audits
("how does an interview end up with status X?") a single grep away.

Future considerations:
- The two no-op `try/except Exception: pass` blocks that previously
  guarded each completion-path DB write are gone; `_finalize_status`
  swallows the DB error in one place. If we ever want telemetry on
  finalisation failures, that single point is where to add it.
- The four answer-handler completion paths are still structurally
  parallel (evaluate → save → maybe-finalise → break). They share the
  helper but not the call site. Worth folding into one terminal-state
  handler if a fifth path appears.

## 24/05/2026 — interview integrity / anti-cheating (Phase C)
Type: Feature

Phase C adds face presence + multi-person detection, plus severity-weighted
warning increments on the backend. Completes the integrity rollout per the
roadmap chosen on 2026-05-23 (native FaceDetector + MediaPipe BlazeFace
fallback for cross-browser parity). No architectural change — face events
ride the same `integrity_event` channel and reuse the same warning counter.

Face detection:
- New `useFaceMonitor` hook (`frontend/src/hooks/useFaceMonitor.ts`).
  Tries the native `FaceDetector` API first (Chromium / Edge / Opera, ~70 %
  of users — zero bundle weight). Falls back to MediaPipe BlazeFace via a
  lazy `import('@mediapipe/tasks-vision')` on Firefox / Safari — paid for
  only by users who need it. WASM + model loaded from pinned jsdelivr /
  Google Cloud Storage CDN paths (locked to MediaPipe 0.10.14, which is
  API-compatible with the npm-resolved 0.10.35 since 0.10.x is stable).
- Samples at 2 Hz. `multi_face` fires immediately (8 s cooldown);
  `no_face` fires only after the face has been absent for ≥5 s of
  continuous samples (10 s post-fire cooldown). Hysteresis tolerates a
  candidate glancing at notes / drinking water without producing a warning.
- Frames stay in the browser. Only the event type + a tiny `count` metadata
  number reach the backend — same privacy posture as Phases A and B.

Severity-weighted warning increments:
- `IntegrityMonitor.record_event` now increments `warning_count` by
  `SEVERITY_WEIGHT[severity]` instead of always +1. Weights: info=0,
  warning=1, critical=2.
- At `MAX_WARNINGS=3`: two critical events (or one critical + one warning,
  or three warnings) terminate. A single critical alone is below threshold,
  so an ambient hiccup cannot end the session.
- Backend already returned `severity` in the `integrity_warning` WS reply
  — frontend now uses it to render a clearer toast: `"Critical integrity
  warning · 2/3"` for criticals, so the +2 jump isn't confusing. New CSS
  variant `.integrity-warning-critical` (stronger left border + saturated
  icon, no gradient — design-system rule).

Dependencies:
- `frontend/package.json`: added `@mediapipe/tasks-vision: ^0.10.14`
  (resolved to 0.10.35). Caret on a 0.x version is bounded to the same
  minor by semver, so an unattended npm install can't pull a breaking
  0.11.x. Native-only browsers never load the module — Vite emits it as a
  separate chunk via the dynamic `import()`.
- No backend dependencies added.

Hard constraints honoured:
- Camera frames never leave the browser (MediaPipe runs WASM client-side).
- Reuses `integrity_event` / `integrity_warning` WS messages; no new types.
- No backend write changes; same DB migration as Phase A.
- `prefers-reduced-motion` respected on the new toast variant (no
  animation, just stronger border).
- No emojis in source.

Verified: frontend `npx tsc --noEmit` clean; backend imports + severity
weights asserted clean.

Affected files:
- new: frontend/src/hooks/useFaceMonitor.ts
- modified: frontend/src/components/InterviewRoom.tsx,
  frontend/src/components/integrity/IntegrityWarning.tsx,
  frontend/src/index.css, frontend/package.json,
  frontend/package-lock.json,
  backend/app/services/integrity_monitor.py
- docs: PROJECT_STATE.md, CHANGELOG.md, IMPLEMENTATION_ROADMAP.md,
  CHANGE.md

Architectural impact: None. Integrity Phase A/B/C share the same:
- WS channel and message types
- Backend `IntegrityMonitor` sibling class
- Audit table + RLS
- Termination path (`interview_ended` with `reason='integrity_terminated'`)

Future considerations:
- Brightness threshold (Phase B) and face hysteresis (Phase C) are
  defensible defaults but unvalidated. A 5-10 candidate lab pass in varied
  lighting / setups would tighten both — the audit table now has the data
  to drive that calibration empirically once enough sessions accumulate.
- "Close-WS-to-skip-terminate" loophole is still open. With Phase C
  landing, this is now the only obvious bypass left. Single backend-only
  fix: in the `end_interview` and `WebSocketDisconnect` paths, force
  `terminated_integrity` if `integrity.warning_count >= MAX_WARNINGS`.
  Sized S in `IMPLEMENTATION_ROADMAP.md`.
- MediaPipe model + WASM are fetched at first use from external CDNs
  (jsdelivr, storage.googleapis.com). If those become unreachable, face
  monitoring silently degrades to "off" (other integrity signals keep
  working). For air-gapped or offline-tolerant deployments, self-hosting
  these assets would be the next step — Vite can copy them to `dist/` and
  the URLs would point at the same origin.
- With three integrity signals plus tab/focus, false-positive rate could
  matter at scale. The audit table already records every event with
  metadata; building a small admin "integrity events" page (separate from
  the per-user view) to filter by event_type would let an operator triage
  noisy patterns and adjust thresholds.

## 23/05/2026 — interview integrity / anti-cheating (Phase B)
Type: Feature

Phase B layers camera-presence signals + report/admin surfacing on top of
the Phase A integrity baseline (commit `8aee82c`). Browser-only, zero new
dependencies, no architectural change. Per the Phase A handoff
(`HANDOFF_PHASE_B.md`), the four items shipped are:

- B1 — Live camera thumbnail in `InterviewRoom` (bottom-right, ~168×126,
  mirrored selfie preview, "Live" badge). Reuses the `MediaStream` already
  held by `InterviewRoom`; mounted only while the interview is running
  (hidden on preflight, terminated, and error screens). The component is a
  thin wrapper around a `<video>` — does NOT own the stream lifecycle.
- B2 — Brightness / camera-dark monitor. New `useCameraPresenceMonitor`
  hook samples the stream at 1 Hz into an offscreen 32×24 canvas, computes
  BT.601 luma, slides a 5-sample window, and fires `camera_dark` when the
  window stays below threshold (12/255 by default). 8 s cooldown prevents
  refiring while the candidate is still adjusting. Zero ML, zero new deps.
  Reuses the existing `integrity_event` WS channel and `IntegrityMonitor`
  counter; `EVENT_TYPES['camera_dark'] = 'warning'` was already in place.
- B3 — Integrity events on the candidate report. `ReportGenerator` now
  performs ONE additional bulk query against `interview_integrity_events`
  (ordered, swallowed on APIError so reports still render if the migration
  is missing). The payload gains an optional `integrity_events: { count,
  terminated, events: [{event_type, severity, metadata, created_at}] }`
  field. The frontend renders a new "Integrity events" panel below the
  phase breakdown, with a clear banner when `terminated == true`.
- B4 — Integrity warnings in the admin user-detail view. `admin_user_detail`
  does ONE additional bulk query for events across all of the user's
  interview IDs, then groups in Python — no per-row lookups. Each
  interview row now carries `integrity_warnings` (count) and
  `integrity_terminated` (bool). The frontend renders a small chip next to
  the score badge.

Hard constraints honoured (per the handoff):
- Camera frames never leave the browser. Only the event type plus a tiny
  `metadata.lum` number reach the backend for `camera_dark`.
- Reuses the existing `interview_ended` / `integrity_event` / `integrity_warning`
  WS message types. No new message types.
- Bulk queries on both B3 and B4 (single SELECT each, grouped in Python).
- No new npm or Python dependencies.
- `prefers-reduced-motion` respected on the new thumbnail "Live" dot.
- No emojis in source files.

Privacy posture is unchanged from Phase A: camera frames are analysed
client-side only; the OS camera indicator clears on unmount because
`InterviewRoom` still stops the tracks (Phase A behaviour).

Verified: frontend `npx tsc --noEmit` clean; backend imports clean.

Affected files:
- new: frontend/src/components/integrity/CameraThumbnail.tsx,
  frontend/src/hooks/useCameraPresenceMonitor.ts
- modified: frontend/src/components/InterviewRoom.tsx,
  frontend/src/components/Report.tsx,
  frontend/src/components/admin/AdminUserDetail.tsx,
  frontend/src/types/index.ts, frontend/src/index.css,
  backend/app/services/interview_orchestrator.py,
  backend/app/models/schemas.py, backend/app/routers/admin.py
- docs: PROJECT_STATE.md, CHANGELOG.md, IMPLEMENTATION_ROADMAP.md,
  HANDOFF_PHASE_B.md (Phase B row flipped to shipped), CHANGE.md

Architectural impact: None. Same WS channel, same backend monitor class,
same termination path, same auth gate.

Future considerations:
- Brightness threshold (`12/255`) and the 5-sample window are conservative
  defaults tuned for obvious tampering (palm over lens, lens cap). A lab
  calibration pass with 5-10 candidates in varied lighting would tighten
  both. Surface them in `IntegrityMonitor` config when that happens, not in
  the hook, so backend telemetry can drive future tuning.
- Phase C (face presence + multi-person) is now unblocked — see
  `IMPLEMENTATION_ROADMAP.md`. The chosen direction (MediaPipe BlazeFace
  fallback for non-Chromium) has not been validated against bundle-size
  budgets yet; that is the first thing to do in Phase C.
- The "close-WS-to-skip-terminate" cheating loophole (PROJECT_STATE.md) is
  still open. With per-interview integrity counts now visible in admin,
  enforcing "block status=completed when integrity count ≥ MAX_WARNINGS at
  end_interview" is a small backend-only addition worth doing alongside
  Phase C.

## 23/05/2026 — interview integrity / anti-cheating (Phase A)
Type: Feature

Adds a production-safe integrity layer over the existing realtime pipeline.
Phase A is intentionally scoped to the lowest-risk, highest-value signals —
camera-required preflight gate, tab/window/visibility monitoring, a warning
system that auto-terminates the interview at three warnings, and a per-event
audit log. Camera-frame analysis (black-frame check) and face detection
(no-face / multi-face) are planned as Phases B and C and are NOT in this
change. The chosen face-detection direction for Phase C is MediaPipe
BlazeFace fallback for cross-browser parity.

Architecture (sibling-class pattern, not orchestrator-bake-in):
- New `IntegrityMonitor` in `services/integrity_monitor.py` — sibling to
  `InterviewOrchestrator`, lives for the lifetime of the WebSocket (ADR 0002
  — non-resumable). Counts warnings in memory (DB persistence is best-effort
  so a transient outage can't let a candidate bypass the threshold), logs
  every event to `interview_integrity_events`, and at MAX_WARNINGS=3 marks
  the interview row `status='terminated_integrity'`.
- `routers/interview_session.py` handles a new client→server WS message type
  `integrity_event` and replies with `integrity_warning` (carrying count +
  event_type + severity + terminate flag). On terminate it emits the
  existing `interview_ended` with `reason='integrity_terminated'` and
  closes — reusing the existing terminal-state path, NOT inventing a new
  one. The realtime turn flow (question/answer/audio) is untouched;
  integrity messages are parallel and out-of-band.
- New DB migration `002_integrity_events.sql` — table + indexes + RLS
  scoped to user_id (same pattern as candidates/interviews). Idempotent.
  No client-side INSERT policy; only the service-role backend writes events.

Frontend:
- New `CameraPreflight` component — gates `/interview/:id` entirely; the WS
  does not open until `navigator.mediaDevices.getUserMedia({video:true})`
  resolves. Handles denied / unsupported / generic-error branches with
  retry. Frames stay on-device; only event types reach the backend
  (explicitly disclosed in the gate copy).
- New `useIntegrityMonitor` hook — browser APIs only (`visibilitychange` +
  `window.blur`), 3 s per-event-type cooldown to avoid spamming on rapid
  alt-tabbing. Zero ML, zero bundle weight.
- New `IntegrityWarning` toast component — auto-dismiss after 6 s, dismissible
  with keyboard, role="alert" + aria-live="assertive" for accessibility.
- `InterviewRoom.tsx` extended: holds the MediaStream (stops tracks on
  unmount so the OS camera indicator turns off cleanly), surfaces
  `camera_lost` if the video track ends mid-interview, renders the toast,
  and replaces the report-redirect with a terminal "interview terminated"
  screen when the close reason is `integrity_terminated`.
- WS service: `sendIntegrityEvent(type, metadata?)` helper added.
- Types: new `IntegrityEventType` union; `integrity_warning` added to the
  WebSocketMessage type discriminator with the relevant fields.
- CSS: ~110 lines appended to `index.css` for the toast / status pill /
  terminal-screen styling, matching the existing dark design tokens.
  Respects `prefers-reduced-motion`.

Privacy posture (stated in the gate copy and enforced by the code):
- Camera frames never leave the candidate's browser in any phase. Phase A
  doesn't even read them; Phases B/C analyse client-side only.
- Only the event type / severity / lightweight metadata reach the backend.
- Camera tracks are stopped on unmount so the OS indicator clears.

Verified: frontend `npx tsc --noEmit` clean; backend imports clean.

Affected files:
- new: backend/app/migrations/002_integrity_events.sql,
  backend/app/services/integrity_monitor.py,
  frontend/src/components/integrity/CameraPreflight.tsx,
  frontend/src/components/integrity/IntegrityWarning.tsx,
  frontend/src/hooks/useIntegrityMonitor.ts
- modified: backend/app/routers/interview_session.py,
  frontend/src/components/InterviewRoom.tsx,
  frontend/src/services/websocket.ts,
  frontend/src/types/index.ts,
  frontend/src/index.css

Architectural impact:
- New WS message types `integrity_event` (client→server) and
  `integrity_warning` (server→client). Termination reuses the existing
  `interview_ended` path with a new optional `reason` field.
- New DB table + status value `terminated_integrity`. Existing aggregation
  queries treat it as not-completed (it carries no `completed=true`-style
  flag the dashboard reads, only the status string).
- Realtime turn sequencing, Matryoshka layer engine, orchestrator
  structure, voice pipeline — all untouched.
- IntegrityMonitor is a sibling class to InterviewOrchestrator, NOT a
  feature of it — keeps the orchestrator from accreting unrelated state.

Future considerations:
- Phase B (next): camera thumbnail in the interview UI + black-frame /
  camera-covered detection. Reuses the same WS event channel.
- Phase C: face presence + multi-face detection. Per the chosen direction,
  native `FaceDetector` API where available with a lazy-loaded MediaPipe
  BlazeFace fallback (~1.5–3 MB) on Firefox/Safari.
- The integrity-event audit log is not yet surfaced in the report or admin
  dashboard. Worth wiring into the report endpoint as a small "integrity
  events" section once Phase B/C land — single bulk query, no per-row
  overhead.
- DB migration must be applied manually in Supabase SQL editor before this
  deploys; the backend's per-event INSERT will silently no-op (caught,
  logged) if the table is missing, so the integrity-termination still works
  in-memory — but the audit log will be empty.
- A determined cheater could close the WS, skipping the termination push.
  Once Phase C face checks land we should also enforce that the interview
  cannot be marked completed if its integrity history shows >MAX_WARNINGS.

---

## 23/05/2026 — interview drifted to ML questions regardless of selected domain
Type: Fix

User reported: selecting Marketing / Web Development / non-ML domains in the
CandidateUpload form, and uploading a matching resume, still produced an
interview that asked Machine Learning / Data Science questions.

Root cause: `routers/candidates.py:upload_resume` was overwriting the
user-selected `field_specialization` on every resume upload with the parser's
inferred value. The resume parser's prompt
(`services/resume_parser.py:_parse_text`) constrains its output to exactly
four labels — `nlp / cv / ml / research` — all ML-adjacent. There is no
"web_dev" / "marketing" / "design" label it can return for a matching resume,
and every failure path defaults to `"ml"`. Net effect: a Web Dev candidate
who picked "Web Development" in the form had `field_specialization` silently
clobbered to `"ml"` in the database; the orchestrator then resolved
`FIELD_PROMPTS["ml"]` (gradient descent, neural networks, MLOps) and steered
every prompt accordingly. The domain-aware routing further down the pipeline
(`_resolve_field_info` + curated `FIELD_PROMPTS` + `_derive_field_info` LLM
fallback for off-table domains) works correctly — it just never received the
user's real choice.

Two secondary defects compounded the symptom:
1. `_evaluate_technical` (the Phase 4 evaluator prompt) hardcoded
   "Evaluate this ML technical interview response rigorously" and probed for
   "ML terminology" regardless of the candidate's domain — so even if the
   prompt drift were fixed, Phase 4 scoring would still pull the answer
   toward an ML rubric.
2. `get_resume_context` injected `projects` and `experience` into the prompt
   but NOT the `skills` array the parser already extracts, so the user's
   specific ask ("React, JavaScript, HTML, CSS → frontend questions") could
   not land — those tokens never reached the LLM.

Fix (additive, minimal, architecture preserved):
- `routers/candidates.py` — resume upload no longer overwrites
  `field_specialization`. The form selection is authoritative; the parser's
  inference is adopted ONLY for legacy rows whose domain is empty/null.
- `services/interview_orchestrator.py:get_resume_context` — includes up to
  20 skills (handles both string-list and dict-list shapes); default field
  changed from "ml" to "general".
- `services/interview_orchestrator.py:_evaluate_technical` — domain-aware
  prompt: pulls role + topics from `_resolve_field_info()` and asks the
  evaluator to score "for this domain" instead of against ML terminology.

Verified: `python -c "from app.main import app; from
app.services.interview_orchestrator import InterviewOrchestrator"` clean.

Affected files: backend/app/routers/candidates.py,
backend/app/services/interview_orchestrator.py, CHANGE.md
Architectural impact: None — the realtime pipeline, Matryoshka layer engine
(ADR 0001), and orchestrator structure are untouched. The fix is a
boundary-level correction: stop mutating user input on the upload path, and
let already-extracted resume signals reach the prompt.
Future considerations:
- The resume parser's `field_specialization` output is now effectively dead
  for new candidates. Worth either (a) removing the inference entirely from
  the parser, or (b) expanding its allowed-label set to the full 26-option
  DOMAIN_OPTIONS list and using it as a *suggestion* to pre-fill the form,
  not an authoritative overwrite.
- The orchestrator never reads `resume_text` (only `resume_sections`). For
  off-curriculum domains the LLM-derived `_derive_field_info` path runs
  exactly once per orchestrator and is reasonable, but the closer the
  injected resume context tracks the candidate's actual stack, the less the
  generation LLM needs to extrapolate. Promoting "user input at API
  boundaries is authoritative; derived data is advisory" to a CLAUDE.md rule
  would lock this principle in beyond this single fix.

---

## 23/05/2026 — production WS connect failed ("Unable to connect")
Type: Fix

After resume upload and "Start Interview" the InterviewRoom panel reported
"Unable to connect — we couldn't reach the interview server." Browser console
revealed the WebSocket was being dialed at a hostname concatenated six times:
`wss://interview-web-app.onrender.comwss//…comwss://…comwss://…comwss://…comwss://…com/ws/interview/<id>?token=…`.
DNS for that hostname does not resolve, so all four cold-start retry attempts
in `websocket.ts:connect()` failed and the generic banner surfaced.

Root cause: the Vercel `VITE_WS_URL` env var was pasted multiple times into
the dashboard (one of the seams even lost its `:`, becoming `wss//`). The
frontend's `WS_HOST` const did only trailing-slash stripping — the mangled
value flowed straight into `new WebSocket(…)`. Same class as the
`VITE_API_URL` trailing slash (18:30) and the `SUPABASE_URL` trailing newline
(21:45) — the fourth env-var paste-mistake in this deploy.

Actual fix is in the Vercel dashboard: set `VITE_WS_URL` to exactly
`wss://interview-web-app.onrender.com` and redeploy (Vite inlines env vars at
build time).

Code hardening (this commit): `websocket.ts` now runs the env value through
`normalizeWsHost` — trims whitespace, coerces `http(s)://` → `ws(s)://`, and
if a second ws/wss scheme is present keeps only the first occurrence and
emits a `console.warn`. So a future paste mistake auto-recovers and surfaces
in the console instead of hiding behind the "Unable to connect" panel.

Affected files: frontend/src/services/websocket.ts, CHANGE.md
Architectural impact: None — defensive input normalisation at the env-var
boundary; realtime / WS lifecycle / auth gate untouched.
Future considerations: this is the 4th env-var paste-corruption incident
across Vercel/Render. The recurring pattern is now hardened at every
ingestion boundary (backend `config.py` strips whitespace from creds; this
frontend layer normalises the URL). Worth promoting a small `lockfile`-style
deploy preflight (e.g. a `/health` ping that round-trips the resolved
WS_HOST) before the user can reach the interview screen, so misconfig
surfaces at app boot rather than mid-session.

## 21/05/2026 21:45
Type: Fix

The post-login 401 persisted. The [auth] logging (19:15 entry) now reveals the
definitive cause: get_user() raises
"AuthRetryableError: Invalid non-printable ASCII character in URL".

Root cause: the SUPABASE_URL env var on Render carries a trailing newline (a
copy-paste artifact). create_client builds the request URL as
f"{supabase_url}/auth/v1/user", so the newline lands inside the URL and
httpx/h11 rejects it before the request is sent. Reproduced locally: a URL with
a trailing newline raises that exact error; .strip() resolves it.

This supersedes the 20:00 root-cause entry — "dependency drift" was an
unconfirmed hypothesis (the [auth] logging was not yet surfacing the real error
then). The dependency pinning (20:00 / 20:30 / 21:00) remains valid
build-reproducibility hardening, but the actual 401 cause is this newline.

Fix: config.py Settings strips whitespace from groq_api_key, openai_api_key,
supabase_url and supabase_key via a pydantic field_validator (mode="before").
The backend is now immune to stray whitespace in these env vars.

Affected files: backend/app/config.py
Architectural impact: None — defensive input normalisation at the config
boundary.
Future considerations: re-entering the Render SUPABASE_URL cleanly is now
optional (the code tolerates it). Recurring class: values pasted into hosting
dashboards picking up stray characters (cf. the VITE_API_URL trailing slash).

## 21/05/2026 21:00
Type: Fix

Render build failed with pip ResolutionImpossible: edge-tts 6.1.9 hard-pins
certifi==2023.07.22, but the lockfile pinned certifi==2026.2.25.

Root cause: edge-tts was mis-pinned. When it was first added to requirements.txt
it was pinned to 6.1.9 (a guessed "known stable"), but the actually-installed,
proven-working version is 7.2.8. The lockfile's transitive section was generated
from the installed 7.2.8 tree (certifi 2026.2.25, tabulate, etc.), so the direct
edge-tts==6.1.9 line contradicted its own transitive closure. Verified every
other direct pin matches its installed version — edge-tts was the only mismatch.

Fix: corrected edge-tts==6.1.9 -> edge-tts==7.2.8 (the proven-working version;
7.2.8 requires certifi>=2023.11.17, satisfied by the pinned certifi==2026.2.25).
No other change needed — the transitive section was already correct for 7.2.8.
Verified all 53 pins are mutually consistent: every dependency specifier in the
closure is satisfied by the pinned set.

Affected files: backend/requirements.txt
Architectural impact: None.
Future considerations: a lockfile must be generated from an environment whose
installed versions match the direct pins. Lockfile regeneration should first
assert direct-pin == installed-version, then walk the closure.

## 21/05/2026 20:30
Type: Refactor

Fully pinned backend/requirements.txt (lockfile). Every transitive dependency
is now pinned to the verified-working version, split into a "Direct" and a
"Transitive (pinned)" section. Previously only top-level packages were pinned
and their sub-dependencies resolved fresh on each install — the cause of the
auth-401 bug (drifted gotrue) and a contributor to the Python-3.14 build
failure. 53-package closure computed from the working environment.

uvloop (Linux-only uvicorn speed-up) is not pinnable from the Windows dev
machine and is left to uvicorn[standard] to resolve on Render; every app- and
auth-critical package is cross-platform and pinned.

Affected files: backend/requirements.txt
Architectural impact: None — reproducible-build hardening; closes the
dependency-drift class of deploy failures.
Future considerations: regenerate the Transitive section after any direct-dep
change. A platform-aware locker (uv, or pip-tools --universal, or locking
inside the Linux build) would additionally pin uvloop and is the longer-term
ideal.

## 21/05/2026 20:00
Type: Fix

Resolved the post-login 401 (see the 19:15 entry). The 19:15 hypothesis — a
SUPABASE_URL / SUPABASE_KEY mismatch — was DISPROVEN: the Render env vars are
correct (verified by decoding the service_role key and testing it against the
project's Auth API).

Actual root cause: dependency drift. requirements.txt pins supabase==2.3.4 but
its sub-dependencies (gotrue, postgrest, realtime, storage3, supafunc) and httpx
were left unpinned. Render's fresh May-2026 install resolved them to current
releases; the drifted gotrue auth client fails to validate Supabase's current
ES256-signed access tokens, so get_user() raises and get_current_user() returns
401. Proven by differential: the local environment (gotrue 2.5.5 / postgrest
0.15.1 / httpx 0.24.1) validates a real ES256 token through the identical
supabase 2.3.4 get_user() code path; the freshly-resolved stack does not.

Fix: pinned the full Supabase stack in requirements.txt to the verified-working
set — gotrue==2.5.5, postgrest==0.15.1, realtime==1.0.6, storage3==0.7.7,
supafunc==0.3.3, httpx==0.24.1, httpcore==0.17.3.

Affected files: backend/requirements.txt
Architectural impact: None — dependency pinning only.
Future considerations: third deploy bug from old, loosely-pinned dependencies
(after Python 3.14 / pydantic-core). A complete lockfile (pip freeze / pip-tools
/ uv) would prevent the whole class. The auth.py logging from the 19:15 entry
stays as the safety net — if a 401 persists after this deploys, the
[auth] log line in Render names the exact exception.

## 21/05/2026 19:15
Type: Fix

Production dashboard returns 401 after a successful Google OAuth login.
Diagnosis: the frontend attaches the token correctly (architecturally proven —
ProtectedRoute renders Dashboard only after /api/auth/me on the same token path
completes), so the backend is rejecting a valid token. Root cause is a
deployment misconfiguration: the Render backend's SUPABASE_URL / SUPABASE_KEY
do not match the frontend's Supabase project (gnylvnobdfzfynhwefrb) — so
get_user() validates the OAuth token against the wrong project and fails.

get_current_user previously swallowed the real exception, making this
indistinguishable from a genuinely bad token. Added server-side logging (never
sent to the client) so the exact cause is visible in the Render log stream:
"invalid JWT"/"bad_jwt" => wrong SUPABASE_URL; "API key" => wrong SUPABASE_KEY;
connection error => SUPABASE_URL unreachable.

Affected files: backend/app/auth.py
Architectural impact: None — observability only; auth logic unchanged.
Future considerations: no code regression seam — this is a deployment-config
error, not a code defect. The added logging is the durable safeguard (future
auth-config mistakes are now immediately visible in logs). The fix itself is to
correct the Render env vars; left a throwaway unconfirmed Supabase user
(diag-test-5066@gmail.com) from diagnosis — delete it.

## 21/05/2026 18:30
Type: Fix

Production dashboard failed after login ("Couldn't load your dashboard" /
"Failed to fetch"). Root cause: the Vercel VITE_API_URL was set with a
trailing slash, so API_BASE became `https://<host>//api` — every REST call
hit `//api/...`, which matches no route and 404s (and, against a cold
free-tier backend, the preflight can 502 without CORS headers, surfacing as
"Failed to fetch"). Backend CORS itself was verified correct.

Fix: api.ts and websocket.ts now strip a trailing slash from VITE_API_URL /
VITE_WS_URL before composing the base URL, so a misconfigured env var can no
longer double the slash. The Vercel VITE_API_URL value should also be
corrected to have no trailing slash; the frontend must be redeployed for
either change to take effect (Vite inlines env vars at build time).

Affected files: frontend/src/services/api.ts, frontend/src/services/websocket.ts
Architectural impact: None — defensive parsing only.
Future considerations: no test seam — API_BASE is a module-load const built
from import.meta.env; verifying it would need a Vitest setup with mocked env,
which the project does not have. The "Failed to fetch" cold-start variant is
mitigated by the keep-alive pinger (still pending post-deploy setup).

## 21/05/2026 17:40
Type: Fix

First Render build failed. Python 3.14.3 (Render's current default for new
accounts) has no prebuilt wheel for pydantic-core 2.16.2 (pinned transitively
by pydantic 2.6.1), so pip fell back to compiling it from Rust source, which
fails on Render's read-only build filesystem.

Pinned Python to 3.11.9 via a repo-root `.python-version` file — Render does
NOT read `runtime.txt` (confirmed in Render's own docs) — and kept the
PYTHON_VERSION key in render.yaml in sync. Removed the dead backend/runtime.txt.

Note: the failed build ran from `main` (commit 8f8dfa7). The deployment config
(render.yaml, edge-tts, CORS fix, WS auth) lives on the
deploy/vercel-render-production branch and must be merged into `main` — or the
Render service pointed at that branch — before a build includes any of it.

Affected files: .python-version (new), render.yaml, backend/runtime.txt (removed)
Architectural impact: None.
Future considerations: Python is now explicitly pinned. Bumping it later
requires confirming every pinned dependency (especially pydantic-core) ships a
wheel for the new version, or the build will attempt a Rust source compile.

## 21/05/2026 17:00
Type: Feature

Production deployment readiness — Vercel (frontend) + Render (backend, free
tier). Additive only; the realtime interview pipeline, voice flow and
orchestrator logic are unchanged (see docs/adr/0002).

Frontend:
- API/WS URLs are now environment-driven. api.ts builds API_BASE from
  VITE_API_URL; websocket.ts builds WS_HOST from VITE_WS_URL. Both fall back to
  the dev defaults (relative /api via the Vite proxy, ws://localhost:8000) when
  unset, so local dev is unchanged. New vars typed in vite-env.d.ts.
- websocket.ts reworked: connect() now retries ONLY during the cold-start
  window (a socket that never opens) — 4 attempts, 1s/2s/4s backoff. Once the
  socket has opened, a drop is terminal and emits a synthetic `disconnected`
  event instead of silently restarting the interview (ADR 0002). The Supabase
  JWT is attached as a `?token=` query param, refreshed per attempt.
- InterviewRoom.tsx handles `disconnected` with a terminal "Connection lost"
  screen (progress-saved messaging + back-to-dashboard).
- New frontend/vercel.json: SPA rewrite so deep-link refreshes resolve.
- New frontend/.env.example.

Backend:
- WebSocket auth: interview_session.py validates the Supabase JWT and interview
  ownership BEFORE accepting the socket (close codes 4401/4403/4404). It is a
  gate in front of the existing flow — the interview loop is untouched.
- CORS fixed: main.py replaced allow_origins=["*"] + allow_credentials=True
  (an invalid combo) with an explicit allowlist (localhost + FRONTEND_ORIGINS)
  plus FRONTEND_ORIGIN_REGEX for *.vercel.app; credentials disabled (Bearer
  auth uses no cookies).
- edge-tts added to requirements.txt (was imported by voice_service.py but
  missing — would have crashed the backend on Render at import time).
- Hardening: get_groq_client() now sets timeout=30s + max_retries=2 so a
  stalled Groq call cannot block the single-worker event loop indefinitely.
  Client-facing WS error messages (`error`, `voice_error`) no longer leak raw
  exception strings — the real error is logged server-side.
- New render.yaml blueprint: single uvicorn process (no --workers) with
  --ws-ping-interval/--ws-ping-timeout to keep idle interview sockets alive;
  healthCheckPath /health; Python pinned to 3.11.9.
- backend/.env.example documents the two new CORS vars.

Affected files:
- frontend: src/services/api.ts, src/services/websocket.ts,
  src/components/InterviewRoom.tsx, src/types/index.ts, src/vite-env.d.ts,
  vercel.json (new), .env.example (new)
- backend: app/main.py, app/config.py, app/routers/interview_session.py,
  requirements.txt, .env.example
- root: render.yaml (new), docs/adr/0002-interview-sessions-are-not-resumable.md
  (new)

Architectural impact:
- The frontend is now cross-origin to the backend in production; CORS and the
  WS auth gate are the new trust boundary. The WebSocket is authenticated for
  the first time.
- A dropped interview is explicitly non-resumable (ADR 0002). This is a
  deliberate, documented boundary — not a regression — replacing the previous
  silent-restart corruption path.
- Realtime turn sequencing, voice pipeline and orchestrator are unchanged.

Future considerations / known issues:
- Free tier cold start (~50-60s): mitigated by an external keep-alive pinger
  hitting /health every ~10 min — must be set up post-deploy (e.g. UptimeRobot
  / cron-job.org). Not in the repo.
- FRONTEND_ORIGIN_REGEX defaults to all *.vercel.app; tighten it to the
  project slug (https://<slug>-.*\.vercel\.app) once the Vercel project name
  is known.
- Synchronous Groq client still blocks the event loop per turn; with a single
  worker, concurrent interviews serialise their LLM calls. Acceptable for a
  low-concurrency free-tier deploy; revisit (wrap in a thread) if volume grows.
- Deploy-time config NOT in the repo: Supabase Site URL + Redirect URLs must
  include the production Vercel domain (+ /auth/callback); Render + Vercel env
  vars must be set in their dashboards.

## 21/05/2026 16:30
Type: Feature

Matryoshka layered-questioning system — deterministic, layer-aware interview
engine (see docs/adr/0001-matryoshka-layered-questioning.md).

Every topic is now drilled through a canonical 5-layer scale (L1 broad intro
-> L5 real-world/scaling). The orchestrator owns the layer as deterministic
Python state: a strong answer climbs a layer, a weak one runs a 3-strike
de-escalation cascade (step-down -> pivot -> end phase). The single generation
LLM call is told the exact layer/topic to ask — no extra LLM call, turn
latency unchanged.

Key changes:
- PhaseState gained current_layer / current_topic / max_layer_reached /
  struggle_streak / topic_count / topic_complete / pending_action. The
  superseded DrillState + ML-keyword _extract_topic_from_question are removed.
- New deterministic engine: _apply_layer_engine, _classify_answer,
  _deep_dive_transition (full L1-L5, phases 2-3), _mini_drill_transition
  (light 2-layer, phases 4-5), _build_question_directive + _deep_dive_directive
  + _mini_drill_directive. evaluate_answer now runs the engine after scoring.
- Interviewer prompt rewritten cold -> warm-professional; per-turn layer/topic
  directive is built in Python.
- Phase 4 reworked: the dead question-retriever path (ml_questions_retrieved,
  never populated) is replaced by per-area 2-question mini-drills.
- Hybrid domain handling: _resolve_field_info uses the 9 curated FIELD_PROMPTS
  as a fast path and LLM-derives + in-memory-caches any other domain, so any
  field works. types/index.ts field_specialization widened to string.
- Scoring: compute_phase_scores phase 2/3 gains a layer-depth term
  (min(max_layer,5)/5*10 * 0.2). Forward-only — applied ONLY when an
  evaluation row carries details.layer; historical interviews keep their
  original formula and their displayed scores never move.
- The Matryoshka layer is persisted in evaluations.details.layer and is
  internal-only — stripped from the client-facing WebSocket evaluation message.

Affected files:
- backend: services/interview_orchestrator.py (engine, prompt, scoring,
  domain handling), routers/interview_session.py (details.layer persistence,
  follow_up_score = layer, strip layer from the WS evaluation frame)
- frontend: src/types/index.ts (field_specialization -> string)
- docs: CONTEXT.md (new glossary), docs/adr/0001-matryoshka-layered-questioning.md

Architectural impact:
- Question selection is now a deterministic Python state machine; the LLM only
  phrases a fully-planned question. drill_level self-reporting is dropped.
- Interview scoring is layer-aware for new interviews only (forward-only),
  keeping dashboard/admin trend lines truthful across the change.
- Realtime WebSocket flow, voice pipeline and turn sequencing are unchanged;
  no new per-turn LLM call; no DB migration.

Future considerations:
- Phase 4/5 also stamp details.layer (harmless — the layer term is scored for
  phases 2-3 only); the curated/derived domain table and the CandidateUpload
  dropdown could still be reconciled.
- _derive_field_info adds one LLM call at interview start for non-curated
  domains; if interview volume grows, cache the result on the candidate row.
- PhaseState is still not restored on a mid-interview WebSocket reconnect
  (pre-existing limitation, unchanged by this work).

## 21/05/2026 10:00
Type: Decision

Short description:
Migrated the AI provider from OpenAI to Groq. All chat/LLM completions now use
`llama-3.3-70b-versatile`; speech-to-text now uses Groq Whisper
`whisper-large-v3`. Groq exposes an OpenAI-compatible API, so the existing
`openai` SDK is reused with `base_url=https://api.groq.com/openai/v1` — no new
dependency.

Affected files:
- backend: config.py (new GROQ_API_KEY setting + get_groq_client helper;
  OPENAI_API_KEY now optional), services/interview_orchestrator.py,
  services/resume_parser.py, services/voice_service.py, .env.example
- docs: CLAUDE.md, .claude/SKILLS/architecture.md

Architectural impact:
- Single LLM/STT provider (Groq) behind one `get_groq_client()` helper. The
  whole app runs on one GROQ_API_KEY.
- Backend now REQUIRES `GROQ_API_KEY` in backend/.env or it will not start.

Future considerations:
- Groq has no embeddings API. `question_retriever.get_embedding` /
  `seed_ml_questions` still reference OpenAI embeddings — only used by the
  offline seed script (not the runtime), so OPENAI_API_KEY is optional.
- `backend/CLAUDE.md` and `.claude/SKILLS/voice-ai.md` still name old models;
  refresh when convenient.

## 20/05/2026 17:00
Type: Refactor (Docs)

Phase 5 (SaaS extension) — engineering documentation.

Short description:
- `CLAUDE.md` rewritten as a full engineering operating document (~20 sections:
  architecture, folder structure, naming, standards, realtime/voice rules,
  testing, git, deployment, debugging workflow, review checklist, security,
  session-startup + working-memory rules).
- This `CHANGE.md` formalised as a working-memory system with a rules header
  and a fixed entry format.
- Specialized Claude agents added under `.claude/agents/`.
- `.claude/SKILLS/architecture.md` updated to the SaaS architecture; new
  `.claude/SKILLS/auth-saas.md` skill added.

Affected files:
- CLAUDE.md, CHANGE.md
- .claude/agents/*.md (new)
- .claude/SKILLS/architecture.md, .claude/SKILLS/auth-saas.md (new)

Architectural impact:
- None — documentation only.

Future considerations:
- Skill-file copies exist under frontend/.claude and backend/.claude; treat
  root .claude/SKILLS as canonical and re-sync or remove the copies.

## 20/05/2026 16:30
Type: Refactor (UI)

Phase 4 (SaaS extension) — premium UI/UX polish pass.

Short description:
A contained global polish of the shared design system (index.css only), so
every screen feels more premium with zero component/logic risk:
- Typography: Inter stylistic sets + optimised legibility + subtle negative
  letter-spacing on body and headings (the Linear/Stripe "crafted" look).
- Layered, softer shadow tokens.
- Crisp app-wide `:focus-visible` ring (keyboard accessibility + polish).
- Refined thin scrollbars and `::selection` styling.
- Subtle content settle-in animation on page/auth surfaces.
- `prefers-reduced-motion` honored globally.

Affected files:
- frontend: src/index.css

Architectural impact:
- None. Pure design-token / base-style refinement; no component or backend
  changes. Interview, voice, websocket, auth all untouched.

Decision:
- Phase 4 was scoped to a global polish pass rather than a screen-by-screen
  rebuild, given the app already had a consistent design system and the
  session length favored a contained, low-risk change.

## 20/05/2026 15:30
Type: Fix + Refactor

Short description:
- Admin overview hung on "Loading…" — it generated a full report per interview
  in a loop (3 blocking DB queries x 82 interviews = ~57s, blocking the event
  loop). The user dashboard had the same anti-pattern.
- Fixed: scoring is now computed from a SINGLE bulk evaluations query.
  82 interviews: 57s -> 0.26s.
- Also fixed an infinite-spinner: a failed `/api/auth/me` left the app loading
  forever; AuthContext now tracks `profileLoading` separately and degrades.

Affected files:
- backend: services/interview_orchestrator.py (new shared helpers
  compute_phase_scores / compute_final_score / recommendation_for /
  score_interviews_bulk; generate_report refactored to use them),
  routers/dashboard.py + routers/admin.py (rewritten to use
  score_interviews_bulk)
- frontend: contexts/AuthContext.tsx, components/auth/ProtectedRoute.tsx,
  App.tsx (profileLoading state)

Architectural impact:
- Interview score computation is now a pure, shared function over evaluation
  rows — one source of truth for the report, dashboard and admin views.
- Aggregation endpoints do O(1) queries instead of O(N) per-interview reports.

Decision:
- Backend started without `uvicorn --reload` — the reload watcher was making
  the dev server die mid-session. Backend is now restarted manually after
  backend code changes.

## 20/05/2026 14:10
Type: Fix + Decision

Short description:
- Profile/role is now read from the backend (`GET /api/auth/me`, service-role
  key) instead of a direct RLS-gated `profiles` query — the admin role was
  silently failing to load because client-side RLS could return nothing. The
  endpoint also creates a missing profile row on the fly.
- Role separation: admins are oversight-only. Admins can no longer access the
  interview-taking flow (/new, /interview/:id) or the candidate dashboard;
  they land on /admin and the header shows only the Admin nav. Candidates
  cannot reach /admin. Reports (/report/:id) remain viewable by both.

Affected files:
- backend (new): app/routers/profile.py  (modified): app/main.py
- frontend (modified): contexts/AuthContext.tsx, services/api.ts,
  components/auth/ProtectedRoute.tsx, App.tsx

Decision:
- ProtectedRoute gained a `restrictTo: 'user' | 'admin'` gate; `/` now routes
  each role to its correct home via a RoleHome redirect.
- Admin/candidate separation is enforced client-side via routing. Backend
  enforcement on interview creation is left as a future hardening item.

## 20/05/2026 13:00
Type: Feature

Phase 3 (SaaS extension) — Admin dashboard + role-based access.

Short description:
- Role-gated admin area. `profiles.role` ('user' | 'admin') now controls access;
  a user is promoted to admin manually via SQL.
- Admin overview (`/admin`): platform stats (total/active users, interviews,
  completion rate, average score), interview-category breakdown, and a users
  table with per-user interview counts and average scores.
- Admin user detail (`/admin/users/:userId`): a single user's profile, stats
  and full interview history (links through to each report).
- The "Admin" nav link appears only for admin accounts; non-admins hitting an
  admin route are redirected to their dashboard.

Affected files:
- backend (new): app/routers/admin.py
- backend (modified): app/auth.py (get_current_admin role guard),
  app/main.py (register admin router)
- frontend (new): components/admin/AdminDashboard.tsx,
  components/admin/AdminUserDetail.tsx
- frontend (modified): App.tsx (admin routes + conditional nav),
  services/api.ts (adminApi), types/index.ts, index.css

Architectural impact:
- `get_current_admin` is a nested FastAPI dependency: it resolves the user via
  get_current_user, then verifies role == 'admin' on the profiles table (403
  otherwise). The backend's service-role key lets admin endpoints aggregate
  across all users without needing admin RLS policies.
- ProtectedRoute already supported `requireAdmin`; it is now used for /admin*.

Decision:
- Admins are created by running, in the Supabase SQL editor:
  `update public.profiles set role = 'admin' where email = 'you@example.com';`
- Admin RLS policies remain deferred — admin reads go through the backend
  service-role key, so direct-client admin RLS is not needed yet.

## 20/05/2026 11:30
Type: Feature

Phase 2 (SaaS extension) — Post-interview results + User dashboard.

Short description:
- New `/dashboard` is the post-login landing page: aggregate stats (total,
  completed, average score, best score), a performance-trend bar chart, and
  the full interview history with per-interview scores and recommendations.
- The post-interview report screen (already auto-redirected to from the
  interview) was rebuilt: score hero, summary, strengths vs. areas-to-improve,
  per-phase breakdown, and a collapsible transcript replay.
- Routing restructured: `/` -> `/dashboard`, new interview setup moved to
  `/new`, header gains Dashboard / New Interview nav.

Affected files:
- backend (new): app/routers/dashboard.py
- backend (modified): app/main.py (register dashboard router),
  app/models/schemas.py (report now carries transcript/strengths/
  improvements/summary), app/services/interview_orchestrator.py
  (generate_report derives strengths, improvements and a summary)
- frontend (new): components/Dashboard.tsx
- frontend (modified): components/Report.tsx (full rebuild), App.tsx
  (routing + header nav), services/api.ts (dashboardApi), types/index.ts,
  index.css

Architectural impact:
- New aggregation endpoint GET /api/dashboard returns the signed-in user's
  interview summaries + stats + trend; reuses ReportGenerator per interview.
- Report generation is now richer but still fully deterministic (no extra
  LLM calls): strengths/improvements/summary derived from phase scores.
- Interview orchestration, websocket and voice pipeline unchanged.

Future considerations:
- Dashboard computes each interview's score via ReportGenerator (3 queries
  per interview). Fine for personal use; batch if interview counts grow large.

## 20/05/2026 09:40
Type: Fix + UI

Short description:
Hardened error reporting and redesigned the candidate onboarding screen.
- "Begin Interview" no longer shows "Unknown error". Root cause: the Phase 1
  migration had not been run, so `candidates` lacked a `user_id` column and the
  insert raised an unhandled error returned as a plain-text 500 the frontend
  could not parse. Fixed both layers: the backend now returns meaningful JSON
  for any database error, and the API client parses non-JSON error bodies.
- Google sign-in now returns a clear, actionable message when the provider is
  not enabled (the error is Supabase dashboard configuration, not code).
- Candidate onboarding redesigned: premium card, refined upload zone, two-column
  field grid, polished ready state, subtle cursor tilt + hover depth, responsive.

Affected files:
- backend: app/main.py (global APIError exception handler)
- frontend (new): hooks/useTilt.ts
- frontend (modified): services/api.ts, contexts/AuthContext.tsx,
  components/CandidateUpload.tsx, index.css

Architectural impact:
- All PostgREST/database errors now surface as JSON `{detail}` 500s app-wide;
  the frontend never shows an unparseable plain-text error again.
- No change to interview orchestration, websocket, voice pipeline or auth
  architecture.

Known issue / decision:
- Google OAuth and per-user persistence still require the Phase 1 Supabase
  dashboard setup: run migration 001_auth_and_ownership.sql and enable the
  Email + Google providers. Until the migration is run, "Begin Interview" now
  reports exactly that instead of failing opaquely.

## 20/05/2026 08:15
Type: Feature

Phase 1 (SaaS extension) — Authentication & data ownership.

Short description:
Added Supabase Auth (email/password + Google OAuth), persistent sessions,
secure logout, protected routes, and per-user data ownership so a returning
user's interviews, resumes and reports persist and reload under their account.

Affected files:
- frontend (new): contexts/AuthContext.tsx,
  components/auth/{Login,Signup,AuthCallback,ProtectedRoute}.tsx
- frontend (modified): App.tsx, services/api.ts, components/CandidateUpload.tsx,
  utils/supabase/client.ts, types/index.ts, index.css
- backend (new): app/auth.py, app/migrations/001_auth_and_ownership.sql
- backend (modified): routers/candidates.py, routers/interviews.py

Architectural impact:
- All app routes now require authentication; /login, /signup, /auth/callback
  are the only public routes.
- `candidates` and `interviews` carry a `user_id`; Row Level Security scopes
  every row to its owner. `evaluations` are owned transitively via interview.
- The backend verifies the Supabase JWT (Bearer token) via `get_current_user`
  and stamps `user_id` on all writes. It still uses the service-role key
  (bypasses RLS); RLS protects the direct client queries the dashboards use.

Future considerations:
- The WebSocket `/ws/interview/{id}` is not yet token-authenticated
  (interview_id is the capability) — harden in a later phase.
- `profiles.role` exists but admin RLS is deferred to Phase 3 (needs a
  SECURITY DEFINER `is_admin()` to avoid RLS policy recursion).
- Requires Supabase dashboard setup: run migration 001, enable the Email and
  Google providers, and whitelist the localhost redirect URL.

## 2026-05-20: CLAUDE.md Accuracy Rewrite

### Brief: Rewrite CLAUDE.md to match actual codebase reality

### Description
Regenerated `CLAUDE.md` via `/init`. The previous version described intended
design rather than the implemented system, which could mislead future work.
Corrected factual inaccuracies and documented setup gaps and architecture.

### Changes Made

#### 1. Tech Stack Corrections
- Clarified `gpt-4o-mini` is used for ALL live work (question generation,
  evaluation, resume parsing, empathy nudges)
- Noted `gpt-4o` only appears in `ResumeParser._parse_with_file_id` (dead code)
- Documented embeddings model (`text-embedding-3-small`, 1536-dim)

#### 2. Known Setup Issues (new section)
- `requirements.txt` missing `edge-tts` — backend fails to import without it
- Embedding dimension mismatch: `database.sql` declares `VECTOR(384)` but
  seed writes 1536-dim vectors
- `/voice/stt` and `/analyze` reject non-`audio/*` MIME types

#### 3. Architecture Documentation
- Documented the WebSocket state machine as the core (REST routers are thin)
- Documented in-memory orchestrator state and WS message protocol
- Flagged the two overlapping phase-advance mechanisms in InterviewOrchestrator
- Corrected "RAG" claim: question retrieval is keyword scoring, not vector search
- Documented schema-drift defensive code in `interview_session.py`

#### 4. Misc
- Fixed required header line, frontend dev port (3000), hardcoded WS host
- Noted absence of unit tests and the root-level e2e Node scripts
- Preserved UI/UX principles and added pointer to `.claude/SKILLS/` docs

### Files Changed
- `CLAUDE.md` - full rewrite for accuracy

### Known Issues
- `frontend/.env` and `backend/.env` contain live-looking credentials and are
  present in the repo — should be gitignored

## 2026-05-18: UI/UX Quality Improvements

### Brief: Fix field visibility, remove AI aesthetic, improve voice recognition, fix responsiveness

### Description
Major quality improvements to make the platform feel enterprise-grade and human-designed.

### Changes Made

#### 1. Field Selection Text Visibility (FIXED)
- Fixed select dropdown text visibility for all browsers
- Added explicit color overrides for :hover, :focus, :active states
- Firefox-specific fix for select element colors
- IE/Edge fallback styling
- Proper -webkit-text-fill-color and fill properties
- Ensure option elements always have visible text

#### 2. Remove AI-Generated Aesthetic
- Removed gradient text effects from hero
- Removed radial gradient background
- Simplified startup animation to minimal fade
- Replaced emoji icons with SVG icons in Report.tsx
- Removed excessive animations:
  - Voice wave: reduced height (32px -> 20px) and opacity
  - Recording pulse: changed from scale to ring effect
  - Mic pulse: reduced scale effect
- Removed gradient references in CSS
- Made animations subtle and purposeful

#### 3. Voice Recognition Quality Improvements
Frontend (useAudioRecorder.ts):
- Optimized MediaStream settings for speech recognition:
  - 16000 Hz sample rate (optimal for Whisper)
  - Mono channel (channelCount: 1)
  - Enhanced echo cancellation, noise suppression, auto-gain
- Added silence detection (isSilence state)
- Audio level visualization responds to actual input
- Better MIME type detection priority
- Proper cleanup on unmount (streams, audio context, timeouts)
- Focus on speech frequencies (85-255Hz) for level detection

Backend (voice_service.py):
- Added language hint ("en") to Whisper for faster, more accurate transcription
- Set temperature to 0.0 for deterministic output
- Added response_format optimization for text output

InterviewRoom.tsx:
- Dynamic listening state: shows "Listening..." / "Speech detected" / "Processing..."
- Voice wave bar heights respond to actual audio level
- Visual feedback for silence detection

#### 4. Device Responsiveness Improvements
Added comprehensive responsive breakpoints:
- 1600px+ (ultrawide): max-width 1400px, 4-column features, larger typography
- 1024px-1440px (laptop): max-width 960px, 2-column features
- 768px-1023px (tablet landscape): max-width 720px
- 768px (tablet portrait): full responsive collapse
- 640px (mobile landscape): chat/input optimizations
- 480px (mobile portrait): touch-friendly adjustments
- 360px (very small): font-size scaling

Fixed viewport issues:
- Added 100dvh (dynamic viewport height) for mobile browsers
- Fixed interview container height calculation
- Proper min-height with dvh fallback

#### 5. Documentation Updates
- Updated CLAUDE.md with UI/UX design principles
- Added form control guidelines (select visibility)
- Documented responsive breakpoints
- Updated voice service section with optimizations

### Files Changed

#### Frontend
- `frontend/src/index.css` - Select fixes, animation reductions, responsive breakpoints, viewport fixes
- `frontend/src/App.tsx` - Removed gradient text class
- `frontend/src/components/Report.tsx` - Replaced emojis with SVG icons
- `frontend/src/components/InterviewRoom.tsx` - Voice level visualization, dynamic states
- `frontend/src/hooks/useAudioRecorder.ts` - Complete rewrite for speech optimization

#### Backend
- `backend/app/services/voice_service.py` - Whisper optimization (language hint, temperature)

### Known Issues
- Whisper API requires stable internet connection
- Mobile Safari may have stricter microphone permissions
- Edge TTS latency varies (typically 1-3 seconds)

### Future Improvements
- Consider Web Speech API for real-time transcription
- Add offline-capable speech recognition fallback
- Test on more mobile devices
- Consider voice recording playback feature