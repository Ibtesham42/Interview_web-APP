# Project State Snapshot

Snapshot of the AI Mock Interview platform as of **2026-05-23**.
For the rolling, append-only engineering log see [`CHANGE.md`](CHANGE.md).
For deployment / planning context see [`IMPLEMENTATION_ROADMAP.md`](IMPLEMENTATION_ROADMAP.md).

---

## What ships today

A production-deployed, voice-first AI mock interview SaaS.

- **Frontend** — Vercel (React 18 + TypeScript + Vite)
- **Backend** — Render free tier (FastAPI, single uvicorn worker, `--ws-ping-interval 20`)
- **Database / Auth** — Supabase (Postgres + Supabase Auth, RLS scoped to `user_id`)
- **LLM** — Groq `llama-3.3-70b-versatile` (questions, evaluation, resume parsing)
- **Voice** — Microsoft Edge TTS (`en-US-JennyNeural`) + Groq Whisper `whisper-large-v3`
- **Realtime** — one `WS /ws/interview/{id}` per interview, in-memory orchestrator (ADR 0002 — non-resumable)

Two roles: **user** (candidate) and **admin** (oversight only).

## Active feature matrix

| Area | Status | Notes |
|---|---|---|
| 5-phase Matryoshka interview (1=warm-up, 2/3=project deep-dive, 4=technical, 5=behavioral) | ✅ Production | ADR 0001 |
| Resume upload + Groq parsing | ✅ Production | Inferred `field_specialization` is now **advisory only** — user's form choice is authoritative (commit `b97597f`) |
| Domain-aware question generation (26 frontend options; 9 curated FIELD_PROMPTS + LLM fallback) | ✅ Production | Web Dev / Marketing / Design etc. no longer drift to ML |
| Skill-aware prompting (resume `skills` injected into prompt context) | ✅ Production | Commit `b97597f` |
| Domain-aware Phase 4 evaluator | ✅ Production | Commit `b97597f` |
| WebSocket auth gate (Supabase JWT via `?token=`) | ✅ Production | `interview_session.py:_authenticate_ws_token` |
| WebSocket URL normalisation (whitespace / scheme / duplicate-host) | ✅ Production | Commit `b97597f` (`normalizeWsHost`) |
| Cold-start retry budget (4 attempts × 1s/2s/4s) | ✅ Production | `websocket.ts:connect()` |
| Dashboard (candidate) + admin analytics | ✅ Production | bulk-query aggregation (`score_interviews_bulk`) |
| Reports (per-interview detailed + markdown) | ✅ Production | `routers/reports.py` |
| Voice — TTS / STT / pace empathy nudge | ✅ Production | `voice_service.py`, `useAudioRecorder` |
| **Integrity Phase A** — camera gate + tab/focus + 3-warning auto-terminate + audit log | ✅ Production (code) | Commit `8aee82c`. **Requires manual SQL migration in Supabase.** |
| **Integrity Phase B** — camera thumbnail + black-frame detection + report/admin surfacing | ✅ Production (code) | See `CHANGE.md`. Same migration as Phase A. |
| **Integrity Phase C** — face / multi-person detection + severity-weighted warnings | ✅ Production (code) | Native `FaceDetector` on Chromium/Edge/Opera; lazy MediaPipe BlazeFace on Firefox/Safari. Same migration as Phase A. |

## Outstanding deploy actions

1. **Apply `backend/app/migrations/002_integrity_events.sql`** in the Supabase SQL editor before Phase A is fully active. Code is defensive — termination still works in-memory if the table is missing — but the audit log will be empty.
2. **Vercel `VITE_WS_URL`** — verify the value is exactly `wss://interview-web-app.onrender.com` (no duplicates / whitespace). The `normalizeWsHost` defence will auto-correct most paste mistakes but the env var should still be clean.
3. **Keep-alive pinger** — Render free tier sleeps after ~15 min idle. Not in repo. External cron (UptimeRobot / cron-job.org) hitting `/health` every ~10 min recommended.
4. **`FRONTEND_ORIGIN_REGEX`** on Render currently `https://.*\.vercel\.app` — tighten to the project slug once Vercel project name is stable.

## Known gaps / acknowledged debt

- **Mid-interview disconnects are terminal** (ADR 0002). Drops surface "Connection lost" + back-to-dashboard. Resumability deferred until interview volume justifies persisting orchestrator state.
- **CORS** still permissive via `FRONTEND_ORIGIN_REGEX` for all `*.vercel.app`.
- **Sync Groq client** blocks the event loop per turn; with one worker, concurrent interviews serialise LLM calls. Acceptable at free-tier volume; wrap in a thread when traffic grows.
- **No automated test suite** — root-level `test_e2e*.js` Playwright smoke flows only. Every change requires manual browser verification.
- **Resume parser's `field_specialization`** output is effectively dead for new candidates (commit `b97597f` made user choice authoritative). Either remove the parser inference entirely or expand its allowed-label set and use it as a *suggestion* to pre-fill the form.
- **Integrity-event audit log** not yet surfaced in the report or admin dashboard. Worth wiring in once Phases B/C land.
- **Determined cheater could close the WS** to skip the termination push. Phase C has landed; the next-step fix is a small backend addition — in `end_interview` and `WebSocketDisconnect` paths, force `terminated_integrity` when `integrity.warning_count >= MAX_WARNINGS`. Sized S in `IMPLEMENTATION_ROADMAP.md`.

## Architecture invariants (do not violate)

These are load-bearing decisions; revisit only with an ADR.

1. **WebSocket is the single source of truth for interview state.** REST is thin CRUD/aggregation. (CLAUDE.md)
2. **One WebSocket per interview; sessions are not resumable** once opened. (ADR 0002)
3. **The interviewer LLM only phrases — Python plans the layer/topic.** No extra LLM call per turn. (ADR 0001)
4. **Backend writes stamp `user_id`; list/detail endpoints filter by caller.** RLS protects direct client reads.
5. **Aggregations use bulk queries** — never N per-row report generation. (`score_interviews_bulk`)
6. **User-provided input at API boundaries is authoritative; LLM-derived data is advisory.** *Promoted to a project principle after commit `b97597f` — see CHANGE.md.*

## Working files for next agent

- [`CHANGE.md`](CHANGE.md) — engineering working memory, append-only, newest first
- [`IMPLEMENTATION_ROADMAP.md`](IMPLEMENTATION_ROADMAP.md) — what's next, in what order, with rationale
- [`CHANGELOG.md`](CHANGELOG.md) — user-facing release notes
- [`HANDOFF_PHASE_B.md`](HANDOFF_PHASE_B.md) — concrete Phase B brief (camera thumbnail + black-frame)
- [`docs/adr/0001-matryoshka-layered-questioning.md`](docs/adr/0001-matryoshka-layered-questioning.md) — Matryoshka engine rationale
- [`docs/adr/0002-interview-sessions-are-not-resumable.md`](docs/adr/0002-interview-sessions-are-not-resumable.md) — why drops are terminal
