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