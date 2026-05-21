# Interview sessions are not resumable

Status: accepted

The interview orchestrator holds all live session state — current phase,
Matryoshka layer, conversation history, struggle streak — in memory in the
backend process, keyed by `interview_id`
(`InterviewConnectionManager.orchestrators`). It is created fresh on every
WebSocket connection and destroyed on any disconnect; nothing is persisted
mid-interview.

We decided **not** to build orchestrator state-restore for the initial
production deployment. The alternatives were: (a) persist orchestrator state to
the database and rehydrate on reconnect — a significant change to the realtime
core; (b) let the WebSocket auto-reconnect as it did, which silently builds a
*new* orchestrator and restarts the interview from Phase 1 onto the candidate's
existing transcript — a corruption bug; or (c) accept that a session is not
resumable.

We chose (c). The frontend WebSocket client now retries only while the socket
has never opened (cold-start tolerance); once the interview is running, a
dropped connection is terminal — the candidate sees a clear "connection lost"
screen, and the per-answer evaluations already written to the database are
preserved. This keeps the realtime architecture untouched and makes the failure
honest instead of corrupting.

Resumability is deferred until interview volume or drop rate justifies
persisting orchestrator state. Until then, a backend deploy or process eviction
during an interview ends that interview.
