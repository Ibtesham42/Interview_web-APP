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

From the analysis-only HTML report. Three small, sequential PRs — not
batched. After each ships and is verified, the next begins.

| # | Candidate | Status |
|---|---|---|
| C4 | Heading scale &amp; typography rhythm | **Shipped 2026-05-25** (ADR 0003) |
| C5 | InterviewRoom inline-style purge | Pending |
| C1 | Button primitive | Pending |

Each gets its own `grill-with-docs` pass before any code lands.

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
