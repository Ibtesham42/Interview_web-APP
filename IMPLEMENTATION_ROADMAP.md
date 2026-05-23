# Implementation Roadmap

Forward-looking plan for the AI Mock Interview platform.
Current snapshot in [`PROJECT_STATE.md`](PROJECT_STATE.md). Historical detail in [`CHANGE.md`](CHANGE.md).

Items are sized as **S** (≤ half day), **M** (1–2 days), **L** (3+ days).
Phase letters carry over from the integrity rollout already in flight.

---

## In flight

### Integrity Phase A — shipped (2026-05-23, commit `8aee82c`)

✅ Camera-required preflight gate
✅ Tab / window / page-visibility monitoring
✅ 3-warning auto-terminate
✅ Per-event audit log table + RLS

**Remaining deploy action:** apply `backend/app/migrations/002_integrity_events.sql` in Supabase SQL editor.

---

## Next — Integrity Phase B (camera presence, browser-only)

**Goal:** the candidate sees the camera is on, and we detect obvious tampering (camera covered / pointed at the ceiling / pointed at a black screen) without ML.

| Item | Size | Notes |
|---|---|---|
| Persistent camera thumbnail in the interview UI (small bottom-right preview from the existing `MediaStream`) | S | Reuse the stream already held in `InterviewRoom`. New `<CameraThumbnail stream={…}>` component. Tokens already in `index.css`. |
| Black-frame / brightness check (1 Hz sample, average luminance under threshold for >5 s → `camera_dark` event) | S | Canvas sample of the video element, no ML. Hand off via existing `sendIntegrityEvent('camera_dark')`. Threshold tunable. |
| `MediaStream` track-ended → `camera_lost` event | ✅ already shipped in Phase A | — |
| "Camera connected" status pill in interview header | S | CSS class `.integrity-status` already in `index.css` from Phase A. |
| Surface integrity events in the candidate report | S | Read `interview_integrity_events` in the existing report endpoint; render a small "integrity events" section. Bulk single query, no per-row overhead. |
| Surface integrity events in the admin dashboard (`AdminUserDetail`) | S | Same source. Bulk query. |

**Architectural change:** none. All Phase B signals ride the same `integrity_event` WS message; backend `IntegrityMonitor` already counts them.

**Acceptance:** with the candidate physically covering the camera for >5 s, an `integrity_warning` toast appears; the audit log row records `camera_dark`. The thumbnail shows the actual camera feed in the corner.

---

## Then — Integrity Phase C (face / multi-person detection)

**Goal:** detect the candidate stepping out of frame, looking away for long stretches, or a second person appearing.

**Direction chosen** (confirmed 2026-05-23): **MediaPipe BlazeFace fallback** for cross-browser parity — native `FaceDetector` API where available (Chromium / Edge / Opera, ~70 % of users), lazy-loaded MediaPipe BlazeFace on Firefox / Safari. Frames stay client-side.

| Item | Size | Notes |
|---|---|---|
| Wrap `FaceDetector` API into a unified `useFaceMonitor(stream)` hook | M | Browser-API path: zero bundle. Returns `{ faceCount, lastSeenMs }`. |
| Lazy-load MediaPipe BlazeFace fallback (~1.5–3 MB chunk; dynamic `import()`) for non-Chromium browsers | M | Only loads when the native API is missing — most users pay zero cost. |
| Hysteresis: `no_face` fires only after face missing for ≥5 s; `multi_face` fires immediately | S | Avoids spamming on a candidate glancing at notes. |
| Wire into `useIntegrityMonitor` and `sendIntegrityEvent` | S | Existing channel. |
| Update report "integrity events" section to label face-related events distinctly | S | — |
| Tune MAX_WARNINGS per event severity (currently every event = 1 warning; `multi_face` may warrant 2) | S | `IntegrityMonitor.record_event` accepts severity; minor refactor to weight by severity. |

**Risk:** false positives in poor lighting. Mitigation: hysteresis + visible thumbnail so candidate self-corrects before a warning fires.

**Acceptance:** stepping out of frame for >5 s, or a second person sitting next to the candidate, fires the appropriate event; lab testing on Chromium / Firefox / Safari produces the expected severities.

---

## After Phase C — closing the cheating loophole

Per `PROJECT_STATE.md` known-gap: a determined cheater could close the WS to skip the termination push.

| Item | Size | Notes |
|---|---|---|
| Block status `completed` for interviews whose integrity log shows ≥ MAX_WARNINGS at completion time | S | Backend `interview_session.py` `end_interview` handler: read count, force `terminated_integrity`. |
| Report markdown badge: "Flagged for integrity review" when status is `terminated_integrity` or warning count ≥ 1 | S | `interview_orchestrator.py:generate_markdown_report`. |

---

## Independent backlog (parallelisable, not on the integrity track)

| Item | Size | Why |
|---|---|---|
| Render keep-alive pinger (external cron hitting `/health` every ~10 min) | S | Free-tier cold start is 50–60 s; documented in `PROJECT_STATE.md`. Not in repo. |
| Tighten `FRONTEND_ORIGIN_REGEX` to the actual Vercel project slug | S | Currently allows all `*.vercel.app`. |
| Wrap synchronous Groq client in a thread executor | M | Currently blocks the single-worker event loop per turn; serialises concurrent interviews. Only matters above ~5 simultaneous candidates. |
| Remove dead `resume_parser.field_specialization` inference (or expand its allowed-label set + use to pre-fill the form) | S | After commit `b97597f` the inferred value is unused for new candidates. Either delete or repurpose. |
| Add Vitest setup + a test for `normalizeWsHost` and `IntegrityMonitor.record_event` thresholds | M | First automated tests in the project. Both are pure / easily testable. |
| Persist orchestrator state to enable interview resume after a drop | L | Requires careful design — see ADR 0002 for why we explicitly chose NOT to ship this initially. Revisit only if drop-rate telemetry justifies it. |
| Promote "user-provided input at API boundaries is authoritative; LLM-derived data is advisory" to a CLAUDE.md rule | S | Captures the recurring class behind the resume-overwrite bug. |

---

## Architecture invariants (do NOT violate without an ADR)

These are load-bearing. Listed here so a future planner knows what's expensive to change.

1. WebSocket is the single source of truth for interview state.
2. Sessions are not resumable (ADR 0002).
3. Interviewer LLM only phrases — Python plans the layer/topic (ADR 0001).
4. Writes stamp `user_id`; RLS scopes reads.
5. Aggregations are bulk queries (`score_interviews_bulk`).
6. Integrity events use the existing WS channel; integrity termination uses the existing `interview_ended` path with `reason='integrity_terminated'`.
