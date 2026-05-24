# Changelog

User-facing release notes for the AI Mock Interview platform.
For the full engineering log with root-cause detail, see [`CHANGE.md`](CHANGE.md).

Format: [Keep a Changelog](https://keepachangelog.com/) loose conventions.
Dates are DD/MM/YYYY (matches `CHANGE.md`).

---

## [Unreleased]
_Nothing pending — two more incremental UI polish PRs (InterviewRoom inline-style cleanup, Button primitive) are queued in `CURRENT_TASKS.md`._

## [2026-05-25] — UI polish · heading scale &amp; typography rhythm

### Changed
- **Restrained premium-app heading scale across every in-app page.** Page headings drop from 1.5rem (or 2.5rem in some places) to a unified **1.75rem at weight 600** with tight letter-spacing. Section headings inside cards bump slightly from 1rem to 1.125rem. Auth screen titles ("Welcome back", "Create your account") gain presence at the larger size while keeping their centered card layout. The visual rhythm now matches Linear / Stripe / Notion app shells — restrained, not marketing-hero.
- **Retired five bespoke title classes** (`.page-title`, `.card-title`, `.onboard-title`, `.panel-title`, plus slimmed `.auth-title`). Semantic `<h1>`–`<h4>` tags carry their styling natively; future contributors get the right typography automatically. The decision is locked in `docs/adr/0003-in-app-heading-scale-is-restrained.md`.

## [2026-05-25] — Cold-start mitigation

### Operational
- **UptimeRobot keep-alive configured.** Render free tier sleeps after ~15 min idle; the first request after a sleep paid 50–60 s of cold-start latency. An external UptimeRobot HTTP(S) monitor now hits `/health` every 5 minutes, keeping the backend warm. Alerting on non-2xx is enabled. External infra; no code change.

## [2026-05-25] — CORS tightening

### Security
- **Production CORS allowlist tightened.** Previously the backend accepted requests from any `*.vercel.app` origin (a permissive default suitable for fresh setups but too broad for production). Now anchored to this project's slug — only `interview-web-app-*.vercel.app` origins are allowed. Updated `.env.example` and `config.py` comments so anyone forking the project sees the project-prefix pattern as the canonical template. The default value in code is unchanged (kept wildcard so first-time clones still work); the actual tightening is the Render `FRONTEND_ORIGIN_REGEX` env var.

## [2026-05-25] — Scoring helpers test coverage

### Added
- **41 pytest tests for the shared scoring helpers** (`compute_phase_scores`, `compute_final_score`, `recommendation_for`, `score_interviews_bulk`). These functions drive the report, the candidate dashboard, and the admin aggregations — a regression in any of them would silently move dashboard numbers. The suite pins phase weights, the layer-aware-vs-historical branching in phases 2/3, the `PHASE_WEIGHTS` sum-to-1 invariant, the recommendation thresholds (including exact boundaries), and the "N interviews → 1 SELECT" bulk-query invariant. Backend suite is now 72 tests total, still <1s wall time.

## [2026-05-25] — Resume-parser cleanup

### Removed
- **Dead `field_specialization` inference** from the resume parser. After the resume-parser fix in `b97597f` made the user's form choice authoritative, the parser's inferred field was no longer adopted on writes for any new candidate — but the inference itself, the legacy-row adoption branch, and the misleading exposure on the `parse-resume` diagnostic endpoint stuck around. All three are gone now. No wire-shape change; the upload endpoint still returns `field_specialization` but it's sourced from the candidate row (the authoritative user choice) instead of the parser.

## [2026-05-24] — CI workflow

### Added
- **GitHub Actions CI** at `.github/workflows/ci.yml`. Runs Vitest (frontend) and pytest (backend) on every push to `main` and every pull request. Type-check (`npx tsc --noEmit`) is folded into the frontend job. Concurrency control cancels superseded runs on the same ref. Pip and npm caches keyed on the lockfiles so re-runs are fast.

## [2026-05-24] — First automated tests

### Added
- **Vitest** for the frontend with a 14-test suite covering `normalizeWsHost` (the WebSocket URL normaliser that has caught several env-var paste mistakes in production). Run with `npm run test`.
- **pytest** for the backend with a 31-test suite covering `IntegrityMonitor.record_event`, the severity-weighted warning thresholds (info=0 / warning=1 / critical=2; terminate at 3), and `_finalize_status` — including explicit regression guards for the WS-disconnect bypass closed earlier today. Run with `python -m pytest`.

### Changed
- Extracted `normalizeWsHost` from `services/websocket.ts` into its own `services/wsHost.ts` so it can be unit-tested without pulling the Supabase client (which throws at import time on missing env vars). Pure refactor — behaviour is identical.

## [2026-05-24] — Integrity bypass closed

### Fixed
- **Closing the browser tab no longer skips integrity termination.** Previously a candidate could close the WebSocket immediately after the third integrity warning and the interview would still settle to `completed`. Now every completion path (natural end, explicit "end interview", and disconnect) consults the integrity counter and writes `terminated_integrity` when the threshold has been reached.

### Added
- **"Flagged for integrity review" badge** at the top of the markdown report — appears whenever the interview was integrity-terminated or any integrity events were logged. Singular / plural wording reflects the event count.

## [2026-05-24] — Integrity Phase C

### Added
- **Face presence detection.** The interview now monitors whether the candidate's face is visible. If the face is missing for more than 5 seconds (e.g. the candidate walks away from the screen), an integrity event is logged.
- **Multi-person detection.** If a second person appears in frame, an integrity event is logged immediately as a critical event.
- **Severity-weighted warnings.** Critical events (multiple people detected, camera disconnected) now count for 2 warnings each, so two such events end the interview. Ordinary warnings still count for 1 each. The toast labels critical events distinctly so the larger jump in the counter is clear.

### Changed
- The integrity toast now distinguishes critical events with a stronger left border and clearer wording (`"Critical integrity warning · 2/3"` vs. the ordinary `"Integrity warning 1 of 3"`).

### Browser support
- Chromium-family browsers (Chrome / Edge / Opera, ~70 % of users) use the built-in `FaceDetector` API — zero extra download.
- Firefox / Safari lazy-load MediaPipe BlazeFace from CDN on first use (~1 MB JS + ~3 MB WASM + ~230 KB model). Native browsers never load this — Vite emits it as a separate chunk.
- If MediaPipe fails to load (offline / CDN unreachable), face checks silently degrade to off — tab/focus and camera-dark monitoring still run.

## [2026-05-23] — Integrity Phase B

### Added
- **Live camera thumbnail** in the interview UI (bottom-right, mirrored selfie preview with a "Live" badge). Visible only while the interview is running; hidden on the preflight gate, the terminated screen, and any error state. Reuses the camera stream already held by the interview — no additional permission prompts.
- **Camera-dark / black-frame detection.** A new browser-only monitor samples the video at 1 Hz, computes brightness, and emits a `camera_dark` integrity event if the camera stays covered or pointed at darkness. Counts against the same 3-warning limit as Phase A. Zero ML, zero new dependencies — frames stay on the candidate's device.
- **Integrity events in the candidate report.** A new "Integrity events" section lists every event (with severity + time) and shows a banner when the interview was integrity-terminated.
- **Integrity warnings in the admin user-detail view.** Each interview row now shows a small "N warning(s)" chip, or a "Terminated" chip when the interview ended for integrity reasons.

## [2026-05-23] — Integrity + domain-targeting hardening

### Added
- **Interview integrity / anti-cheating — Phase A.** Mandatory camera-required preflight gate before any interview starts; tab / window / page-visibility monitoring during the interview; 3-warning auto-terminate with a clear terminal screen; per-event audit log persisted to the new `interview_integrity_events` table. Camera frames stay on the candidate's device — only event types reach the backend.
  - **Deploy action required:** run `backend/app/migrations/002_integrity_events.sql` in the Supabase SQL editor before this becomes fully active.
- Skill-aware question generation — the resume's extracted `skills` array is now injected into the interviewer prompt, so candidates with React / SEO / Figma / etc. get questions matched to their actual stack.

### Changed
- **Resume upload no longer overrides the candidate's domain choice.** Previously, uploading a resume silently clobbered the user-selected `field_specialization` with the parser's inference (constrained to `nlp / cv / ml / research`), so a Web Dev or Marketing candidate would end up with ML questions. The form selection is now authoritative; the parser's inference is adopted only when the candidate hasn't set a domain.
- Phase 4 (technical) evaluator is now domain-aware instead of hard-coding "ML technical interview" wording.

### Fixed
- WebSocket connection failure ("Unable to connect") when the Vercel `VITE_WS_URL` env var contained a duplicated host (e.g. pasted six times by mistake). The frontend now normalises the value at module load — strips whitespace, coerces `http(s)://` to `ws(s)://`, and trims to the first scheme + host when duplicates are detected, with a `console.warn` so the misconfiguration is visible. The actual fix is still to set a clean env var in Vercel and redeploy.

## [2026-05-21] — Production deployment hardening

### Added
- Vercel (frontend) + Render (backend, free tier) deployment configuration (`render.yaml`, `vercel.json`).
- WebSocket auth gate — Supabase JWT validated **before** `accept()`; close codes 4401 / 4403 / 4404.
- Cold-start retry loop on the client — 4 attempts × 1 s / 2 s / 4 s backoff for the very first socket open; once open a drop is terminal.
- ADR 0002: interview sessions are not resumable.

### Changed
- CORS: replaced invalid `allow_origins=["*"]` + `allow_credentials=True` combo with an explicit allowlist plus `FRONTEND_ORIGIN_REGEX` for Vercel deployments; credentials disabled (Bearer auth uses no cookies).
- Groq client: `timeout=30s`, `max_retries=2` so a stalled call cannot block the single-worker event loop indefinitely.

### Fixed
- Production 401 after Google OAuth login — root cause was Supabase dependency drift; full Supabase stack (`gotrue / postgrest / realtime / storage3 / supafunc / httpx / httpcore`) pinned. Full lockfile in `backend/requirements.txt`.
- Production dashboard "Failed to fetch" — Vercel `VITE_API_URL` trailing slash created `//api/...` 404s; `api.ts` + `websocket.ts` now strip trailing slashes.
- Render build failure on Python 3.14 (no `pydantic-core` wheel) — pinned Python to 3.11.9 via `.python-version` and `render.yaml`.
- Lockfile conflict: `edge-tts` was mis-pinned to `6.1.9` which required `certifi==2023.07.22`; corrected to `7.2.8` matching the installed version.
- `SUPABASE_URL` trailing-newline rejection by httpx — `config.py` now strips whitespace from credential / URL env vars via a Pydantic field validator.

## [2026-05-21] — Matryoshka layered questioning

### Added
- Deterministic 5-layer Matryoshka interview engine (ADR 0001). Each topic is drilled through L1 (broad) → L5 (real-world / scaling); the orchestrator owns the layer as Python state, the LLM only phrases the question. Strong answers climb a layer, weak answers run a 3-strike de-escalation cascade. No extra LLM call per turn.
- Layer-aware deep-dive scoring (`compute_phase_scores`); historical pre-Matryoshka interviews keep their original scores (forward-only scoring).

### Changed
- Interviewer prompt rewritten cold → warm-professional.
- Phase 4 reworked: per-area 2-question mini-drills replace the unused question-retriever path.
