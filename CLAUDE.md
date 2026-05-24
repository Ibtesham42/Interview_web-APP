# CLAUDE.md — AI Mock Interview Platform

Engineering operating document. Read this fully at the start of every session.

---

## Project Overview

A production-grade, voice-first **AI mock interview SaaS**. A candidate signs up,
uploads a resume, and is taken through a 5-phase voice interview driven over a
WebSocket. The AI interviewer speaks (TTS), the candidate answers by voice
(STT), every answer is scored, and a weighted report is produced. Users have a
dashboard of their history; admins have a platform analytics dashboard.

Two roles: **user** (candidate — runs interviews) and **admin** (oversight —
analytics only, blocked from the interview flow).

---

## Architecture

- **Frontend** — React 18 + TypeScript + Vite. SPA, React Router. Supabase JS
  client for auth/session.
- **Backend** — FastAPI (Python). Supabase service-role key for DB access.
- **Database/Auth** — Supabase (PostgreSQL + Supabase Auth). Row Level Security
  scopes data to its owner.
- **LLM** — Groq `llama-3.3-70b-versatile` via the OpenAI-compatible API
  (questions, evaluation, resume parsing).
- **Voice** — Microsoft Edge TTS (speech out), Groq Whisper `whisper-large-v3`
  (speech in).
- **Realtime** — one WebSocket per interview: `WS /ws/interview/{id}`.

**Request flow:** the interview runs entirely over the WebSocket
(`routers/interview_session.py` + `services/interview_orchestrator.py`). REST
routers are thin CRUD/aggregation layers. The frontend authenticates with
Supabase, sends the JWT as a Bearer token; the backend verifies it
(`app/auth.py`) and stamps `user_id` on writes.

**Auth model:** frontend reads its profile/role from `GET /api/auth/me`
(backend, service key — never RLS-gated). Dashboards aggregate via REST
endpoints. RLS protects any direct client-side table reads.

---

## Folder Structure

```
backend/app/
├── main.py              # FastAPI entry, router registration, error handlers
├── config.py            # Settings (env vars)
├── auth.py              # get_current_user / get_current_admin dependencies
├── supabase_client.py   # Supabase client (service-role key)
├── migrations/          # Ordered SQL migrations (run in Supabase SQL editor)
├── routers/             # HTTP + WebSocket endpoints, thin
├── services/            # Business logic (orchestrator, voice, parser, retriever)
└── models/schemas.py    # Pydantic request/response models

frontend/src/
├── App.tsx              # Router + role-aware shell
├── contexts/            # AuthContext (session, profile, role)
├── components/          # Feature components
│   ├── auth/            # Login, Signup, AuthCallback, ProtectedRoute
│   └── admin/           # AdminDashboard, AdminUserDetail
├── hooks/               # useAudioRecorder, useTilt
├── services/            # api.ts (REST client), websocket.ts
├── utils/supabase/      # Browser Supabase client
└── types/index.ts       # Shared TypeScript types
```

---

## Naming Conventions

- **Files** — React components `PascalCase.tsx`; hooks `useXxx.ts`; backend
  modules `snake_case.py`.
- **React** — components `PascalCase`, named exports only; props interface
  `ComponentNameProps`; handlers `handleXxx` internally, `onXxx` as props.
- **Python** — `snake_case` functions/vars, `PascalCase` classes.
- **Routes** — REST `kebab/snake` plural nouns; WebSocket `/ws/...`.
- **DB** — `snake_case` tables/columns; foreign keys `<table>_id`.
- **CSS** — `kebab-case` classes; design tokens are CSS variables in `:root`.

---

## Engineering Rules

- Read the relevant skill files (`.claude/SKILLS/`) before non-trivial work.
- Keep the realtime interview pipeline, voice flow, and WebSocket logic stable —
  change them only when a fix genuinely requires it.
- Additive changes over rewrites. Don't refactor beyond the task.
- No `any` types; no hardcoded secrets (env vars only).
- Trust framework guarantees; validate only at system boundaries.
- **User-provided input at API boundaries is authoritative; LLM/parser/heuristic-derived
  data is advisory.** Never silently overwrite a field the user has explicitly set.
  If you must persist inferred data alongside it, store it separately (e.g. an
  `inferred_*` column or a suggestion the UI can offer) — never blow away the user's
  choice. Code-review red flag: any `update({field: parsed_data[field]})` next to a
  `update({user_text: ...})` for the same row. *Origin: the resume-parser bug fixed
  in commit `b97597f` (a Web Dev candidate received ML questions because the
  parser's inference overwrote the user's form choice).*
- After backend code changes, restart the backend manually (see Commands).
- Every meaningful change is logged in `CHANGE.md` (see CHANGE.md Rules).

---

## Frontend Standards

- TypeScript-first; strict mode; no `any`.
- Side effects/state live in custom hooks; components stay presentational.
- Local state `useState`; global/auth state via `AuthContext`; server state via
  `services/api.ts` fetch helpers (no React Query).
- All REST calls go through `services/api.ts` (`fetchJson` attaches the Supabase
  JWT and parses errors meaningfully — never surface "Unknown error").
- Routing/role gating via `components/auth/ProtectedRoute.tsx` (`restrictTo`).
- Styling: the design system in `index.css` (CSS variables). No inline layout.
- See skills: `frontend.md`, `ui-ux.md`, `accessibility.md`, `performance.md`.

---

## Backend Standards

- FastAPI, async endpoints, Pydantic v2 models.
- Auth via `Depends(get_current_user)` / `Depends(get_current_admin)`.
- Router → Service → Supabase. Routers stay thin.
- Writes stamp `user_id`; list/detail endpoints filter by the caller.
- Aggregations (dashboard/admin) use bulk queries — never N per-row report
  generation. Shared scoring lives in `interview_orchestrator.py`
  (`compute_phase_scores`, `compute_final_score`, `score_interviews_bulk`).
- DB errors surface as JSON via the `APIError` handler in `main.py`.
- See skills: `backend.md`, `architecture.md`.

---

## Realtime Rules

- One WebSocket per interview: `WS /ws/interview/{interview_id}`.
- The WebSocket is the **single source of truth** for interview state.
- Strict sequential turn flow: AI speaks → playback ends → user records →
  transcription completes → next question generates. No overlap.
- Client messages: `answer`, `voice`, `end_interview`. Server messages: `init`,
  `question`, `audio`, `evaluation`, `phase_update`, `empathy_nudge`,
  `voice_transcript`, `voice_error`, `interview_ended`, `error`.
- Backend always emits an `audio` frame after a `question` (empty if TTS fails)
  so the client state machine is deterministic.
- Frontend reconnect: exponential backoff, max 3 attempts; no reconnect after
  an intentional disconnect.
- See skill: `realtime.md`.

---

## Voice Rules

- **STT** — Groq Whisper (`whisper-large-v3`), `language="en"`,
  `temperature=0.0`, `response_format="text"` (returns a plain string — do not
  access `.text`).
- **TTS** — Edge TTS, voice `en-US-JennyNeural`, MP3, base64 over the socket.
- **Recording** — `useAudioRecorder`: webm/opus, mono, RMS level metering, one
  complete blob per recording (no timeslice), reject too-short clips.
- Never overlap audio playback; revoke object URLs.
- See skill: `voice-ai.md`.

---

## UI/UX Principles

- Dark, understated, enterprise — **no gradients, glows, mesh, or flashy
  animation**. Inspiration: Linear, Stripe, Notion.
- Inter font; design tokens (color, space, radius, shadow) in `index.css`.
- Subtle motion only (120–300ms, purposeful). Respect `prefers-reduced-motion`.
- Polished empty / loading / error states everywhere.
- WCAG 2.1 AA: visible `:focus-visible` ring, 44px touch targets, semantic HTML.
- Responsive: 360 / 480 / 640 / 768 / 1024 / 1440 / 1600px+.
- See skills: `ui-ux.md`, `accessibility.md`.

---

## Testing Standards

- No automated suite yet. Root-level `test_e2e*.js` are Playwright smoke flows.
- Verify every change before reporting done:
  - Frontend: `npx tsc --noEmit` must pass; exercise the feature in the browser.
  - Backend: `python -c "from app.main import app"` must import cleanly.
- For UI work, test golden path + edge cases in a browser. If you cannot, say so.

---

## Git Workflow

- Not a git repository currently. If initialized: feature branches off `main`,
  small focused commits, imperative messages ("fix", "add", "update").
- Never commit secrets (`.env`, keys). Never force-push shared branches.
- Create commits only when the user explicitly asks.

---

## Deployment Notes

- **Frontend** — `npm run build` → static files → any static host. Set
  `VITE_SUPABASE_URL` / `VITE_SUPABASE_PUBLISHABLE_KEY`.
- **Backend** — ASGI (`uvicorn`/`gunicorn`). Env: `GROQ_API_KEY` (required),
  `SUPABASE_URL`, `SUPABASE_KEY` (service role). `OPENAI_API_KEY` optional.
- **Database** — apply `backend/app/migrations/*.sql` in order in Supabase.
- Tighten CORS (currently `*`) and add WebSocket token auth before production.

---

## Agents

Specialized agents live in `.claude/agents/`. Use them for focused work:
`frontend-engineer`, `backend-engineer`, `realtime-voice-engineer`,
`code-reviewer`, `debugger`. Each follows this document and the skill files.

---

## Commands

```bash
# Frontend (port 3000)
cd frontend && npm install && npm run dev
npx tsc --noEmit          # type-check (must pass before "done")

# Backend (port 8000) — run WITHOUT --reload (the watcher is unstable here)
cd backend && pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# restart manually after backend code changes

# Database — run each migration in the Supabase SQL editor, in order
backend/app/migrations/001_auth_and_ownership.sql
```

Required deps not in `requirements.txt`: `edge-tts` (`pip install edge-tts`).

---

## Session Startup Rules

1. Read this `CLAUDE.md` fully.
2. Read `CHANGE.md` top-to-bottom — it is the working memory: recent changes,
   decisions, known issues, technical debt, TODOs.
3. Confirm both servers run; check health endpoints.
4. Load the skill files relevant to the task before writing code.

---

## Working Memory Rules

- `CHANGE.md` is the project's persistent memory across sessions. Treat its
  Known Issue / TODO / Decision entries as authoritative context.
- Do not rely on prior chat history; rely on `CHANGE.md` + the code.
- When a decision is made, record it in `CHANGE.md` so it survives the session.

---

## CHANGE.md Rules

Log **every meaningful change**. Append a new entry at the **top** of
`CHANGE.md` using:

```
## DD/MM/YYYY HH:MM
Type: Feature | Fix | Refactor | Decision | Known Issue | TODO

<short description>

Affected files: <paths>
Architectural impact: <how it changes the system, or "None">
Future considerations: <follow-ups, risks, debt>
```

Track: architecture decisions, implemented features, future-impacting
decisions, unresolved bugs, technical debt, pending improvements.

---

## Debugging Workflow

1. Reproduce; capture the exact error.
2. Read logs first — backend log file, browser console, network tab.
3. Find the **root cause** before changing code; never paper over with
   `--no-verify`-style shortcuts.
4. Make the smallest correct fix; replace generic errors with meaningful ones.
5. Verify (tsc / import check / browser); confirm the original symptom is gone.
6. Log the fix and root cause in `CHANGE.md`.

---

## Code Review Checklist

- Does it match this document and the skill files?
- Realtime/voice/websocket pipeline untouched unless required?
- No `any`, no dead code, no secrets, no unhandled promise rejections.
- Errors are meaningful (no "Unknown error"); empty/loading/error states exist.
- Auth: writes stamped with `user_id`; endpoints role-gated correctly.
- Aggregations use bulk queries, not per-row loops.
- Frontend type-checks; backend imports cleanly.
- `CHANGE.md` updated.

---

## Security Rules

- Secrets in env vars only — never in code, commits, or the frontend bundle.
- Frontend uses the Supabase **anon/publishable** key; backend uses the
  **service-role** key (never expose it).
- Verify the Supabase JWT on every protected endpoint (`get_current_user`).
- Role-gate admin endpoints (`get_current_admin`) and admin routes.
- RLS scopes every domain table to its owner; admins read via the
  service-key backend, not direct client queries.
- Validate/parameterize all external input. Don't leak internal errors.
- Pending hardening: WebSocket token auth, CORS allowlist (see Deployment).
