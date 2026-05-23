# Changelog

User-facing release notes for the AI Mock Interview platform.
For the full engineering log with root-cause detail, see [`CHANGE.md`](CHANGE.md).

Format: [Keep a Changelog](https://keepachangelog.com/) loose conventions.
Dates are DD/MM/YYYY (matches `CHANGE.md`).

---

## [Unreleased]
_Nothing pending — Phase B (camera thumbnail + black-frame detection) is the next planned tranche; see `IMPLEMENTATION_ROADMAP.md`._

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
