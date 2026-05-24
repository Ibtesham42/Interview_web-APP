# Current Tasks

Active task board for the **stability + scalability** phase declared on
**2026-05-24** (see [`CHANGE.md`](CHANGE.md) and
[`PROJECT_STATE.md`](PROJECT_STATE.md)).

> **Phase policy.** No large new feature branches. Work is bounded to
> maintainability, scaling safety, reliability, and production hardening.
> Each task names which of those four buckets it serves, and is small
> enough to ship in an existing-system-shaped PR — not a feature-shaped
> one.
>
> The forward backlog still lives in
> [`IMPLEMENTATION_ROADMAP.md`](IMPLEMENTATION_ROADMAP.md); this file is
> only the **prioritised slice we are willing to do now**.

Sizing: **S** ≤ half-day, **M** 1–2 days, **L** 3+ days. Anything **L** is
deferred unless explicitly promoted out of the deferred section.

---

## Now — pick from these

### Maintainability

_All items burned down this phase — see "Done" section below._

### Scaling safety

| Item | Size | Notes |
|---|---|---|
| Wrap the synchronous Groq client in a thread executor | M | Currently blocks the single-worker event loop per turn; serialises concurrent interviews. Known scaling cliff above ~5 simultaneous candidates. |
| Audit `score_interviews_bulk` and admin aggregations for N+1 regressions | S | Invariant #5 ("aggregations are bulk queries") is load-bearing; a one-time read-through is cheap insurance. |

### Reliability

| Item | Size | Notes |
|---|---|---|
| Surface integrity-event volume in admin dashboard | S | Audit table now has data. A small "integrity events by type" view would let an operator triage noise patterns and tune thresholds (Phase B/C followup). |

### Production hardening

| Item | Size | Notes |
|---|---|---|
| Self-host MediaPipe BlazeFace WASM + model in Vercel `dist/` | S | Phase C currently lazy-loads from jsdelivr / GCS. Air-gap-friendly and removes a silent-degradation failure mode. |

---

## Deferred — needs an explicit decision before pickup

| Item | Size | Why deferred |
|---|---|---|
| Persist orchestrator state to enable interview resume after a drop | L | ADR 0002 says don't ship this until drop-rate telemetry justifies it. Revisit only when reliability data is in hand. |
| Coverage steps in CI (`pytest --cov`, `vitest --coverage`) | S | Wait until at least one round of "add tests when touching code" has happened; coverage gates introduced too early ossify the test surface around what we *already* test. |

---

## UI polish track (architecture review 2026-05-25)

From the analysis-only HTML report run via `improve-codebase-architecture`.
Three small, sequential PRs — not batched. Each gets its own
`grill-with-docs` pass before any code lands.

| # | Candidate | Status |
|---|---|---|
| C4 | Heading scale &amp; typography rhythm | **Shipped 2026-05-25** (ADR 0003) |
| C5 | InterviewRoom inline-style purge | **Next** |
| C1 | Button primitive | After C5 |

### C5 — InterviewRoom inline-style purge (next)

**Scope:** `frontend/src/components/InterviewRoom.tsx` only. Replace
inline `style={{...}}` attributes with named CSS classes. No
architecture change. Mechanical cleanup.

**Confirmed offenders** (from the 2026-05-25 audit):

| Line | What | Replacement direction |
|---|---|---|
| 435 | Inline `marginTop` on button | CSS class |
| 457 | Inline `marginTop` on button | CSS class |
| 481-486 | Heading + subtitle inline `fontSize`/`color` | `.interview-heading` + `.interview-subtitle` |
| 490 | Inline `display: flex; gap: 1rem; flexWrap` | `.interview-header-row` |
| 511 | Inline button `padding` + `fontSize` | `.btn-end-interview` (or reuse Button primitive once C1 lands — but C5 ships first) |
| 604 | Inline `background: var(--accent-green)` | CSS class on the dot/badge |
| 617 | Inline `background: var(--accent-rose)` | CSS class on the dot/badge |

**Leave alone** (data-driven, NOT inline-style cruft):
- `:626-630` voice-wave-bar inline `height`/`opacity` — calculated from
  live audio level, must stay inline.
- `Dashboard.tsx:146` trend-bar dynamic `height` percentage — same
  reason.

**Open grilling questions for tomorrow** (do these in the `grill-with-docs` pass):
- Should the inline accent-colour spots (`:604`, `:617`) be class-based
  *now*, or wait for C1 (Button primitive) since they're button
  backgrounds anyway?
- Is the inline `fontSize: '0.9375rem'` on `:481` an h4-sized heading
  that should just be `<h4>`, or a "label" needing a new class?
- Should the new CSS classes live as a new `interview-room.css` partial
  or stay in the existing `src/index.css`? Project convention is single
  index.css; lean toward keeping it.

**Sizing:** S. One file modified, ~30 lines of CSS added, ~7 JSX style
attributes removed.

### C1 — Button primitive (after C5)

**Scope:** introduce `src/components/ui/Button.tsx` exposing
`variant: "primary" | "secondary" | "ghost" | "danger"`,
`size: "sm" | "md" | "lg"`, plus an `as="a"` escape hatch for
link-styled buttons and a `loading` prop. The CSS classes
(`.btn`, `.btn-primary`, etc.) already exist — the component composes
them. Migrate call sites file-by-file over follow-up PRs if needed.

**Call sites to migrate** (from audit):
- `Dashboard.tsx` (1+ buttons, link-styled CTA)
- `Login.tsx` (submit + Google OAuth + inline `style={{ width: '100%' }}` cleanup)
- `Signup.tsx` (submit + Google OAuth)
- `CandidateUpload.tsx` (submit)
- `InterviewRoom.tsx` (end-interview, mic — note: C5 may already have CSS'd these)
- `Report.tsx` (back-to-dashboard CTA)
- `AdminDashboard.tsx`, `AdminUserDetail.tsx` (any CTAs)

**Open grilling questions for tomorrow:**
- Does the `loading` prop replace label-with-spinner, or render a spinner
  *next to* the label?
- `as="a"` escape hatch vs. a separate `LinkButton` component?
- Where does the file live — `src/components/ui/` (new directory) or
  `src/components/Button.tsx`? Project hasn't established a `ui/`
  convention yet; consider whether to introduce one with this PR.
- Should we add a Vitest test for Button render variants? Would extend
  the existing test discipline.

**Sizing:** S for the primitive + 1 file migration. Subsequent
file-by-file migrations are XS each; consider whether to ship them in
this PR or as follow-ups.

### How to pick up tomorrow

1. Read this section first to recall the agreed scope.
2. Invoke `grill-with-docs` for C5 with the scope above as input.
3. Settle the open questions one-by-one.
4. Implement, verify in browser per CLAUDE.md, commit + push.
5. After CI is green and visual verification passes, repeat for C1.

The architecture review HTML at
`C:\Users\ibtes\AppData\Local\Temp\architecture-review-2026-05-25-frontend.html`
is in the OS temp directory and may be cleaned by Windows before
tomorrow — re-run `improve-codebase-architecture` if you want the
visual report back, or just work from this section.

## Done in this phase

(Update as items land. Newest at the top.)

- 2026-05-25 — Shipped UI polish C4 (heading scale + typography rhythm).
  Global h1–h4 scale dropped to premium-app sizes (1.75 / 1.375 / 1.125
  / 0.9375 rem at weight 600). Retired bespoke `.page-title`,
  `.card-title`, `.onboard-title`, `.panel-title` classes; slimmed
  `.auth-title` to just centering. Decision locked in ADR 0003.
- 2026-05-25 — Configured UptimeRobot keep-alive pinger (HTTP(S)
  monitor on `/health`, 5-min interval, alerting email enabled).
  Eliminates the 50–60 s Render free-tier cold start on first user
  hit. External infra; documented in
  `reference_uptimerobot_keepalive.md` memory and `PROJECT_STATE.md`.
- 2026-05-25 — Tightened `FRONTEND_ORIGIN_REGEX` on Render to
  `^https://interview-web-app(-[a-z0-9-]+)?\.vercel\.app$` — only this
  project's production + preview deployments are now valid CORS origins.
  Updated `.env.example` and `config.py` comments to match. The default
  in code stays wildcard for template friendliness.
- 2026-05-25 — Added 41 pytest tests for the shared scoring helpers
  (`compute_phase_scores`, `compute_final_score`, `recommendation_for`,
  `score_interviews_bulk`). Backend suite now 72 tests; bulk-query
  invariant + PHASE_WEIGHTS-sum-to-1 invariant are regression-guarded.
- 2026-05-25 — Removed the dead `resume_parser.field_specialization`
  inference (prompts, fallback dicts, return shape, the legacy-row
  adoption branch in `upload_resume`). The DB column + all read paths
  + the user-form write path are unchanged.
- 2026-05-24 — Promoted "user input authoritative; LLM-derived data
  advisory" to a formal Engineering Rule in `CLAUDE.md`. The memory entry
  is kept as a historical pointer.
- 2026-05-24 — Branch protection enabled on `main`: required checks
  `Frontend (tsc + vitest)` + `Backend (pytest)`, up-to-date branches
  required, force-pushes blocked.
- 2026-05-24 — CI workflow at `.github/workflows/ci.yml` running both
  suites on push to `main` and every PR.
- 2026-05-24 — First automated test suites (14 Vitest + 31 pytest).
- 2026-05-24 — WS-disconnect integrity bypass closed
  (`_finalize_status` helper) + "Flagged for integrity review" markdown
  badge.
- 2026-05-24 — Supabase migration `002_integrity_events.sql` applied;
  audit log live.
