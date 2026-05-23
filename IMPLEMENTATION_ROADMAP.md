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

### Integrity Phase B — shipped (2026-05-23)

✅ Camera thumbnail in `InterviewRoom`
✅ Brightness / black-frame check → `camera_dark` event (1 Hz, 5-sample window, browser-only)
✅ Integrity events on the candidate report (single bulk query)
✅ Integrity warnings + termination chip on `AdminUserDetail` (single bulk query)

Same SQL migration as Phase A — no additional deploy action.

### Integrity Phase C — shipped (2026-05-24)

✅ `useFaceMonitor` hook — native `FaceDetector` first, MediaPipe BlazeFace lazy fallback
✅ `multi_face` (immediate, 8 s cooldown) and `no_face` (≥5 s hysteresis, 10 s post-fire cooldown) events
✅ Severity-weighted warning increments (info=0, warning=1, critical=2)
✅ Toast variant for critical events so the +2 jump is clear

Same SQL migration as Phase A — no additional deploy action.

---

## Next — close the cheating loophole

Per `PROJECT_STATE.md` known-gap: a determined cheater could close the WS to skip the termination push.

| Item | Size | Notes |
|---|---|---|
| Block status `completed` for interviews whose integrity log shows ≥ MAX_WARNINGS at completion time | S | Backend `interview_session.py` `end_interview` handler + `WebSocketDisconnect` branch: read count, force `terminated_integrity` if over threshold. |
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
