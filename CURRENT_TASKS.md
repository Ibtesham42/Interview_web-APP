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

| Item | Size | Notes |
|---|---|---|
| Remove (or repurpose as a form-prefill *suggestion*) `resume_parser.field_specialization` | S | Dead since commit `b97597f` (user form choice is authoritative). Carries cost in confusion; zero benefit. |
| Add pytest for `compute_phase_scores` / `compute_final_score` / `score_interviews_bulk` | S | Pure helpers; drive dashboard aggregates. Next-best test targets after the integrity surfaces already covered. |

### Scaling safety

| Item | Size | Notes |
|---|---|---|
| Wrap the synchronous Groq client in a thread executor | M | Currently blocks the single-worker event loop per turn; serialises concurrent interviews. Known scaling cliff above ~5 simultaneous candidates. |
| Audit `score_interviews_bulk` and admin aggregations for N+1 regressions | S | Invariant #5 ("aggregations are bulk queries") is load-bearing; a one-time read-through is cheap insurance. |

### Reliability

| Item | Size | Notes |
|---|---|---|
| Render keep-alive pinger (external cron hitting `/health` every ~10 min) | S | Free-tier cold start is 50–60 s; documented in `PROJECT_STATE.md`. External config (UptimeRobot / cron-job.org), no code change. |
| Surface integrity-event volume in admin dashboard | S | Audit table now has data. A small "integrity events by type" view would let an operator triage noise patterns and tune thresholds (Phase B/C followup). |

### Production hardening

| Item | Size | Notes |
|---|---|---|
| Tighten `FRONTEND_ORIGIN_REGEX` on Render to the actual Vercel project slug | S | Currently allows all `*.vercel.app`. Deploy-only change. |
| Self-host MediaPipe BlazeFace WASM + model in Vercel `dist/` | S | Phase C currently lazy-loads from jsdelivr / GCS. Air-gap-friendly and removes a silent-degradation failure mode. |

---

## Deferred — needs an explicit decision before pickup

| Item | Size | Why deferred |
|---|---|---|
| Persist orchestrator state to enable interview resume after a drop | L | ADR 0002 says don't ship this until drop-rate telemetry justifies it. Revisit only when reliability data is in hand. |
| Coverage steps in CI (`pytest --cov`, `vitest --coverage`) | S | Wait until at least one round of "add tests when touching code" has happened; coverage gates introduced too early ossify the test surface around what we *already* test. |

---

## Done in this phase

(Update as items land. Newest at the top.)

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
