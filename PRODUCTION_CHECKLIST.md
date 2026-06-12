# PRODUCTION_CHECKLIST.md

> Production-readiness state of the live stack. Created 2026-06-12 during the
> stabilization pass; update whenever a deploy, migration, or config change
> lands. Verification method: scripted end-to-end battery against the LIVE
> stack (real accounts → real REST + WebSocket → cleanup), plus read-only DB
> probes. See CHANGE.md 12/06/2026 (c) for the run this file reflects.

## Stack

| Layer | Where | State |
|---|---|---|
| Frontend | Vercel — `interview-web-app-lyart.vercel.app` | ✅ serving current bundle (feature markers verified) |
| Backend | Render — `interview-web-app.onrender.com` | ✅ `/health` commit matches `origin/main` |
| Database | Supabase — project `gnylvnobdfzfynhwefrb` | ✅ migrations 001–012 applied |
| Keep-alive | UptimeRobot, 5-min `/health` monitor | ✅ active (warm responses ~600 ms) |

## Verified flows (live E2E battery, 2026-06-12 — 29/32; the 3 fails are 2× the RESEND blocker + 1 script artifact)

### 1. Candidate interview startup ("couldn't reach the interview server")
- [x] Root causes identified and fixed: ① `VITE_WS_URL` localhost fallback (fixed 10/06, `wsHost.ts`); ② NULL `company_id` stamps vs the WS tenant gate (fixed 12/06, migration 011 + create-path stamping)
- [x] Real `wss://` handshake as a tenant candidate: ACCEPTED, `init → question → audio` streamed (socket open ≈ 4.7 s warm)
- [x] Residual cold-start window hardened (12/06, pending deploy): connect budget 3 attempts/~7 s → 6 attempts/8 s-capped backoff (rides out a Render free-tier wake) + "Try again" button on the error panel

### 2. Company onboarding
- [x] `/companies/signup` → 201, company row created
- [x] Creator profile flips to `company_admin` + tenant stamped
- [x] `GET /companies/mine` returns the company
- [x] `company_admin` inherits recruiter access; plain candidates get 403

### 3. Invite flow
- [x] Invite endpoint writes outbox row + invitation ledger row
- [ ] **Invite email DELIVERY — BLOCKED: `RESEND_API_KEY` unset on Render** (recorded as `failed` in outbox; in-app invitation works regardless)
- [x] Public apply link resolves unauthenticated with company info
- [x] Candidate registration → claim → invitation accepted

### 4. Interview flow
- [x] Candidate password login
- [x] Camera/mic: preflight gate blocks the room until granted; `camera_lost` integrity event on revocation (browser-side — verified by code path + earlier manual walk; not scriptable from CI)
- [x] WebSocket connect, question + TTS audio, integrity warning round-trip
- [x] Interview completion (`end_interview` → `interview_ended`, status persisted)
- [x] Proctoring snapshot stored; report generates with scores + recommendation

### 5. Recruiter flow
- [x] Completed candidate appears on recruiter dashboard with interview count
- [x] Analytics update (funnel: signed_up/started/completed reflect the new interview; summary endpoint OK)
- [x] Shortlist decision persists; shortlist email drafts from template
- [ ] **Shortlist/reject email DELIVERY — BLOCKED: same `RESEND_API_KEY` gap** (outbox records the attempt as `failed`)

### 6. Super admin
- [x] Account active: role `admin`, `company_id NULL` (the non-NULL trap silently tenant-scopes platform views — see CHANGE.md 12/06 (b))
- [x] Total companies + platform totals visible
- [x] Company detail: registrations/invited counts, `interviews_total`, decision analytics

## Remaining blockers (ordered)

1. **`RESEND_API_KEY` + verified `RESEND_FROM_EMAIL` unset on Render** — the only functional gap found: no invite/shortlist/reject email leaves the platform. Set both in the Render dashboard, then register the Resend webhook (see RESEND_EMAIL.md). The outbox/UI already handle the rest.
2. **`ENVIRONMENT=production` unset on Render** — readiness gate runs in relaxed dev mode, so a future misconfig (e.g. localhost `FRONTEND_BASE_URL`) would not block boot. One env var.
3. **Cold-start hardening not yet deployed** — committed work on `main` needs a push to take effect (frontend-only).
4. Hygiene: root `secrets.md` is gitignored and was **never committed** (verified against all refs), but live keys belong in `.env`/a password manager, not a loose repo-root file one `git add -f` from a public repo. Move + delete.

## Known accepted limitations

- Render free tier: single instance; deploys restart it (the hardened cold-start window now covers this).
- STT quality depends on Groq Whisper; voice path not covered by the scripted battery (needs a real microphone — manual walk only).
- `interviews.job_id` does not exist yet (Jobs feature is designed but ON HOLD until this checklist is green).
