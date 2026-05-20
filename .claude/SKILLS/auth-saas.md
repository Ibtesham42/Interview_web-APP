# Authentication & SaaS Standards

Standards for the authentication, session, role, and dashboard layers.

## Authentication

- **Provider** — Supabase Auth: email/password + Google OAuth.
- **Sessions** — Supabase JS client persists the session (localStorage),
  auto-refreshes tokens, and detects the OAuth callback in the URL.
- **Frontend** — `AuthContext` exposes `session`, `user`, `profile`, `loading`,
  `profileLoading`, `isAdmin`, and the `signUp` / `signIn` / `signInWithGoogle`
  / `signOut` actions. It subscribes to `onAuthStateChange`.
- **Profile/role** — read from the backend `GET /api/auth/me` (service-role
  key), never a direct client query — this is immune to RLS misconfiguration
  and creates the profile row if missing.
- **Backend** — `get_current_user` verifies the Bearer JWT via Supabase;
  `get_current_admin` additionally checks `profiles.role == 'admin'`.

## Routing & Roles

- Two roles: `user` (candidate) and `admin` (oversight).
- `ProtectedRoute` gates routes: `restrictTo: 'user' | 'admin' | undefined`.
  - Unauthenticated → `/login`.
  - Role mismatch → redirected to the correct home.
- Admins are blocked from `/new` and `/interview/:id`; candidates from `/admin`.
- Reports (`/report/:id`) are viewable by both.
- Loading vs failed-load are distinct states — never spin forever on a failed
  profile fetch (`profileLoading` settles regardless of outcome).

## Data Ownership & Persistence

- `candidates` and `interviews` carry `user_id`. The backend stamps it on every
  write; list/detail endpoints filter by the caller.
- RLS scopes every domain table to its owner; `evaluations` are owned
  transitively via their interview.
- A returning user's interviews, reports, transcripts and resumes reload
  correctly because every row is tied to their account.

## Dashboards & Analytics

- **User dashboard** — that user's interview history, scores, trend, stats.
- **Admin dashboard** — platform-wide users, interview counts, completion rate,
  category breakdown, per-user metrics; drill into a single user.
- Scores come from `score_interviews_bulk` — one evaluations query, then pure
  in-memory scoring. Never generate a report per interview in a loop.
- The report, user dashboard and admin dashboard all use the SAME scoring
  helpers, so a given interview shows the same score everywhere.

## Database Migrations

- Migrations live in `backend/app/migrations/`, numbered and ordered.
- Run them in the Supabase SQL editor. Write them idempotent (`if not exists`,
  `drop policy if exists`, `on conflict`) and tolerant of partial base schema.
- Promote an admin manually:
  `update public.profiles set role = 'admin' where id = '<auth-user-id>';`

## SaaS Hygiene

- Polished empty / loading / error states on every data-driven screen.
- Meaningful errors end-to-end — backend returns JSON `{detail}`, the API
  client parses non-JSON bodies, the UI shows the message (never "Unknown
  error").
- New accounts must work end to end: sign up → onboard → interview → report →
  it persists and reloads on next login.
