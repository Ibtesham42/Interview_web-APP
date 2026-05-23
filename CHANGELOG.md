# Changelog

User-facing release notes for the AI Mock Interview platform.
For the full engineering log with root-cause detail, see [`CHANGE.md`](CHANGE.md).

Format: [Keep a Changelog](https://keepachangelog.com/) loose conventions.
Dates are DD/MM/YYYY (matches `CHANGE.md`).

---

## [Unreleased]
_Nothing pending — the integrity rollout (Phases A → C) is now complete. The remaining "close-the-cheating-loophole" backend polish is sized S in `IMPLEMENTATION_ROADMAP.md`._

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
