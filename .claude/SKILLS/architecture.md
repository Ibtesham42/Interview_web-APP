# Architecture Standards

## System Overview

A voice-first AI mock interview **SaaS**. Authenticated users (candidates) run
5-phase voice interviews; admins see platform analytics.

| Component | Technology | Rationale |
|-----------|------------|-----------|
| Frontend | React + TypeScript + Vite | Fast dev, type safety, SPA |
| Backend | FastAPI (Python) | Async, modern, easy AI integration |
| Database | Supabase (PostgreSQL) | Postgres + RLS, managed |
| Auth | Supabase Auth | Email/password + Google OAuth, JWT sessions |
| LLM | Groq llama-3.3-70b-versatile | Fast, cost-effective reasoning |
| TTS / STT | Edge TTS / Groq Whisper (whisper-large-v3) | Free / fast |
| Realtime | WebSocket | Low-latency interview turns |

## Architecture Layers

### Presentation (Frontend)
- React components (presentational) + custom hooks (stateful logic).
- `AuthContext` — session, profile, role. `ProtectedRoute` — auth + role gating.
- `services/api.ts` — REST client (attaches Supabase JWT).
- `services/websocket.ts` — the interview socket.

### Application (Backend)
- FastAPI routers (HTTP + one WebSocket). Thin — delegate to services.
- Services: `interview_orchestrator` (5-phase state machine + shared scoring),
  `voice_service`, `resume_parser`, `question_retriever`.
- `auth.py` — JWT verification, role dependencies.

### Data
- Supabase Postgres: `profiles`, `candidates`, `interviews`, `evaluations`,
  `ml_questions`. RLS scopes rows to their owner.
- Backend connects with the service-role key (bypasses RLS — so it must
  explicitly scope every query by the authenticated user).

## Key Flows

### Authentication
- Frontend authenticates with Supabase Auth → JWT stored in the browser.
- REST calls send `Authorization: Bearer <jwt>`; the backend verifies it.
- Frontend reads its own profile/role from `GET /api/auth/me` (backend, service
  key) — never a direct RLS-gated query, so role detection is reliable.

### Interview (realtime)
- One WebSocket per interview. The socket is the single source of truth.
- Sequential turns: AI speaks → playback ends → user records → STT → next
  question. The orchestrator is a 5-phase adaptive state machine.

### Aggregation (dashboards)
- User and admin dashboards aggregate via REST endpoints.
- Scores are computed from a SINGLE bulk evaluations query
  (`score_interviews_bulk`) — never a per-interview report in a loop.

## Design Decisions

- **REST vs WebSocket** — REST for CRUD/aggregation; WebSocket for the live
  interview only.
- **Service-key backend** — the backend owns all writes and stamps `user_id`;
  RLS protects any direct client reads.
- **Shared scoring** — one pure scoring function feeds the report, the user
  dashboard and the admin dashboard, so scores are consistent everywhere.
- **Roles** — `user` (candidate) and `admin` (oversight). Admins are blocked
  from the interview-taking flow.

## Scalability Considerations

- In-memory orchestrator state per active interview — fine for current scale;
  move to durable state + a job queue for TTS to scale out.
- Aggregations are bulk-query based — O(1) queries regardless of interview
  count.
- Future: multiple WebSocket servers with Redis pub/sub; CDN for static assets.

## Security

- Secrets in env vars only. Frontend uses the anon key; backend the service-role
  key (never exposed).
- Every protected endpoint verifies the JWT; admin endpoints check the role.
- RLS enabled on all domain tables.
- Pending hardening: WebSocket token auth, CORS allowlist (currently `*`).

## Deployment

- Frontend: `vite build` → static host. Backend: ASGI (`uvicorn`/`gunicorn`).
- Database: apply `backend/app/migrations/*.sql` in order in Supabase.
- Environment: local `.env` in dev; environment variables in production.
