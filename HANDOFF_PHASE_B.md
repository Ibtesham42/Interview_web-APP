# Handoff — Integrity Phase B

**From:** Phase A author (commit `8aee82c`, 2026-05-23)
**To:** the next agent picking up integrity work
**Goal:** ship Phase B (camera presence — thumbnail + black-frame check) without rewriting Phase A and without ML.

---

## TL;DR

Phase A is live in `main` (camera-required gate, tab/focus monitor, 3-warning auto-terminate, audit log). Phase B adds two things the candidate sees and one signal the backend counts:

1. A small live camera thumbnail (bottom-right of `InterviewRoom`) so the candidate cannot forget they're being watched.
2. A 1 Hz brightness check on the video stream → emits `camera_dark` when the average luminance stays below threshold for ≥5 s.
3. Wire integrity events into the candidate report and admin detail screens.

Everything you need is already in place: the `MediaStream` is held in `InterviewRoom.tsx`, the WS channel for `integrity_event` is open, the audit table exists, `IntegrityMonitor.record_event` accepts the `camera_dark` type, and CSS tokens for the status pill (`.integrity-status`) are already in `index.css`.

---

## Read first (in order)

1. [`PROJECT_STATE.md`](PROJECT_STATE.md) — current production state, deploy actions, invariants.
2. [`IMPLEMENTATION_ROADMAP.md`](IMPLEMENTATION_ROADMAP.md) — Phase B items + sizing, plus the locked Phase C direction (MediaPipe BlazeFace fallback).
3. The most recent entries in [`CHANGE.md`](CHANGE.md) — especially the **23/05/2026 integrity Phase A** entry: it documents the sibling-class pattern, the privacy posture, and the design constraints you should not break.
4. [`docs/adr/0002-interview-sessions-are-not-resumable.md`](docs/adr/0002-interview-sessions-are-not-resumable.md) — termination semantics. Integrity termination already reuses `interview_ended` with `reason='integrity_terminated'`; do NOT add a second termination path.
5. `frontend/src/components/InterviewRoom.tsx` (the gate, the hook wiring, the toast, the terminal screen) — this is your integration point.
6. `frontend/src/hooks/useIntegrityMonitor.ts` — Phase A pattern for cooldown + WS forwarding; mirror it for the brightness check.
7. `backend/app/services/integrity_monitor.py` — `EVENT_TYPES['camera_dark'] = 'warning'` already exists; you just need to fire the event from the client.

---

## What is already built (do not re-build)

- **DB table** `interview_integrity_events` — RLS scoped to `user_id`, indexes on `(interview_id, created_at)` and `(user_id, created_at desc)`.
- **Sibling backend class** `IntegrityMonitor` — owns warning count, persists every event, signals `terminate=true` at `MAX_WARNINGS=3`.
- **WS message types:** client → `integrity_event` (`event_type`, `metadata`); server → `integrity_warning` (`count`, `max`, `event_type`, `severity`, `terminate`) and on terminate the existing `interview_ended` with `reason='integrity_terminated'`.
- **Frontend gate** `CameraPreflight` — blocks WS open until camera is granted; the resulting `MediaStream` is held in `InterviewRoom`'s `cameraStream` state and stopped on unmount. **You already have the stream — do not re-request `getUserMedia`.**
- **Toast** `IntegrityWarning` — accessible, auto-dismiss; reused as-is.
- **Terminated screen** — already renders when `reason === 'integrity_terminated'`.
- **CSS** `.integrity-status` / `.integrity-warning*` / `.iv-terminated` — already in `index.css` (search for `INTEGRITY / ANTI-CHEATING`).

---

## Build list (Phase B)

Suggested order — each item is independently shippable.

### B1. Camera thumbnail (S)

- **New** `frontend/src/components/integrity/CameraThumbnail.tsx`
- Props: `{ stream: MediaStream }`
- Renders a `<video autoPlay muted playsInline>` with `srcObject = stream`. Position fixed, bottom-right, ~160×120 px, rounded corners, 1 px border, drop shadow. Add a `.camera-thumbnail` class to `index.css` (use existing tokens — `var(--bg-secondary)`, `var(--radius-md)`, `var(--shadow-lg)`).
- Mount inside `InterviewRoom`'s main render branch, only when `cameraStream && !integrityTerminated && !connectionError && !lostConnection`.

### B2. Brightness check + `camera_dark` event (S)

- **New** `frontend/src/hooks/useCameraPresenceMonitor.ts`
- Signature: `useCameraPresenceMonitor({ stream, enabled, onEvent })` mirroring `useIntegrityMonitor`'s shape.
- Implementation: create an offscreen `<canvas>`; once per second, draw a downscaled frame (e.g. 32×24), compute mean RGB luminance, slide a 5-sample window. If the window's max stays below ~12/255 → fire `onEvent('camera_dark', { lum: <avg> })`. Reset the window once luminance recovers.
- Reuse the same 3 s cooldown pattern from Phase A so a brief dim spell doesn't double-fire.
- Wire into `InterviewRoom` next to `useIntegrityMonitor`; reuse `handleIntegrityEvent`. Enable only when `integrityEnabled` (existing gate condition in Phase A).

### B3. Surface integrity events in reports (S)

- **Backend** `routers/reports.py` — extend the report payload (or add a sibling endpoint) with `integrity_events: { count, terminated, events: [{event_type, severity, created_at}] }`. **Single bulk query** by `interview_id` — DO NOT loop.
- **Frontend** `Report.tsx` — render a small "integrity events" section. If `terminated_integrity`, show a clear banner.

### B4. Surface integrity events in admin detail (S)

- **Backend** `routers/admin.py` — extend `AdminUserDetail` payload with per-interview integrity-event counts (single bulk query joined / grouped by `interview_id`).
- **Frontend** `AdminUserDetail.tsx` — add an "integrity" column to the interviews table.

---

## Hard constraints (do not break)

- **Camera frames never leave the browser.** Brightness analysis happens client-side; only the `camera_dark` event type + a tiny `metadata.lum` number reach the backend.
- **Reuse `interview_ended` for any termination.** Do not invent a new terminal message.
- **Reuse `integrity_event` / `integrity_warning`.** No new WS message types for B1–B4.
- **Bulk queries for B3 / B4.** Never per-row generation; that's a recurring code-review gate (see `CLAUDE.md`).
- **No new dependencies** for Phase B. (MediaPipe waits for Phase C.)
- **`prefers-reduced-motion`** — any new animation must respect it (existing CSS does).
- **No emojis in source files** unless the user asks for them (CLAUDE.md rule).

---

## Verification checklist (run before opening the PR)

- [ ] `cd frontend && npx tsc --noEmit` — clean
- [ ] `cd backend && python -c "from app.main import app; print('OK')"` — clean
- [ ] In a browser: cover the camera for 7 s → toast appears, audit row written with `event_type='camera_dark'`.
- [ ] Cover the camera 3 times in one interview → `interview_ended` fires with `reason='integrity_terminated'`, interview row status is `terminated_integrity`, terminal screen renders.
- [ ] Thumbnail appears bottom-right during the interview, disappears on the terminal/error screens.
- [ ] Report page shows the integrity-events section with the right count.
- [ ] Admin detail shows the integrity column.
- [ ] Append a `CHANGE.md` entry at the top with the standard header (Type / Affected / Architectural impact / Future considerations).
- [ ] Update `PROJECT_STATE.md` Phase B row to ✅, `CHANGELOG.md` `[Unreleased]` section, and `IMPLEMENTATION_ROADMAP.md` "In flight" / "Next" sections.

---

## Open questions to confirm with the user before shipping

- Should the integrity-events section on the candidate report be visible to the candidate themselves, or admin-only? (Phase A persists events keyed to `user_id` and RLS allows the candidate to read their own — so the candidate *can* see them. UX question is whether you want them to.)
- Brightness threshold (`~12/255`) and window (`5 s`) are guesses tuned for "obvious cover with palm/lens cap." Want to run a 10-candidate lab pass to calibrate, or ship the defaults and tune from telemetry?

---

## Pointers for Phase C (face detection) — for context only, do NOT start

- Native `FaceDetector` API where available (Chromium / Edge / Opera).
- Lazy `import()` of MediaPipe BlazeFace as fallback on Firefox / Safari (~1.5–3 MB chunk; pays zero cost on Chromium).
- New event types are already in `EVENT_TYPES`: `no_face` (warning), `multi_face` (critical).
- Hysteresis ≥5 s for `no_face`; immediate for `multi_face`.
- Severity-weighted warning increments worth implementing then (currently every event = 1 warning).
