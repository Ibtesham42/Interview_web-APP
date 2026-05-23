"""Per-interview integrity / anti-cheating state.

Sibling to InterviewOrchestrator. Lives for the lifetime of the WebSocket
(ADR 0002 — interviews are not resumable). Receives integrity events from
the client over the existing WebSocket, persists each one to the audit log,
counts warnings, and signals the WS handler when the threshold is reached so
the existing `interview_ended` flow can terminate the session.

Privacy posture: camera/microphone frames never leave the candidate's
browser. Only event-type / severity / lightweight metadata reach the
backend.
"""

from typing import Dict, Optional, Any
from uuid import UUID

from app.supabase_client import get_supabase


# Recognised event types. Unknown event types are still accepted (recorded
# as-is) but tagged 'info' severity. Keeping the set explicit here makes the
# contract with the frontend visible from one place.
EVENT_TYPES = {
    "tab_blur": "warning",            # tab lost foreground
    "window_blur": "warning",         # app/window lost focus
    "visibility_hidden": "warning",   # tab/window hidden (minimised, switched)
    "camera_lost": "critical",        # MediaStream track ended unexpectedly
    "no_face": "warning",             # face missing for >hysteresis (Phase C)
    "multi_face": "critical",         # >1 face detected (Phase C)
    "camera_dark": "warning",         # video frame near-black (Phase B)
}


class IntegrityMonitor:
    """Track and persist integrity events; flag termination at threshold."""

    MAX_WARNINGS = 3

    def __init__(self, interview_id: UUID, user_id: str):
        self.interview_id = interview_id
        self.user_id = user_id
        self.warning_count = 0
        self._supabase = None

    @property
    def supabase(self):
        if self._supabase is None:
            self._supabase = get_supabase()
        return self._supabase

    def record_event(
        self,
        event_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record one integrity event. Returns the updated counter snapshot.

        Persistence is best-effort: a DB failure must not crash the WS turn.
        The in-memory counter is the source of truth for termination so a
        transient DB outage cannot let a candidate bypass the threshold.
        """
        severity = EVENT_TYPES.get(event_type, "info")
        self.warning_count += 1

        try:
            self.supabase.table("interview_integrity_events").insert({
                "interview_id": str(self.interview_id),
                "user_id": str(self.user_id),
                "event_type": event_type,
                "severity": severity,
                "metadata": metadata or {},
            }).execute()
        except Exception as e:
            print(f"[Integrity] event log failed: {e}")

        return {
            "event_type": event_type,
            "severity": severity,
            "count": self.warning_count,
            "max": self.MAX_WARNINGS,
            "terminate": self.warning_count >= self.MAX_WARNINGS,
        }

    def mark_terminated(self) -> None:
        """Mark the interview row as integrity-terminated.

        Uses a dedicated status so dashboards / reports can distinguish a
        natural completion from an integrity termination.
        """
        try:
            self.supabase.table("interviews").update({
                "status": "terminated_integrity",
                "completed_at": "now()",
            }).eq("id", str(self.interview_id)).execute()
        except Exception as e:
            print(f"[Integrity] termination mark failed: {e}")
