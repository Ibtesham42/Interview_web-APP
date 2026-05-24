"""Tests for IntegrityMonitor.record_event and the warning-threshold logic.

These cover the contract the WebSocket handler relies on:
- severity-weighted increment of warning_count (info=0, warning=1, critical=2),
- the `terminate` flag flips exactly at MAX_WARNINGS (3),
- the in-memory counter is the source of truth even when the DB insert fails,
- known event types map to their documented severities,
- unknown event types are accepted with severity='info'.
"""

from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from app.services.integrity_monitor import (
    EVENT_TYPES,
    SEVERITY_WEIGHT,
    IntegrityMonitor,
)


def make_monitor(supabase=None) -> IntegrityMonitor:
    """Build a monitor with the Supabase client stubbed out.

    record_event accesses `self.supabase` (which would otherwise call
    get_supabase() and require a live env). Setting `_supabase` short-circuits
    the lazy initialiser cleanly.
    """
    monitor = IntegrityMonitor(uuid4(), str(uuid4()))
    monitor._supabase = supabase if supabase is not None else MagicMock()
    return monitor


class TestSeverityMapping:
    """The EVENT_TYPES / SEVERITY_WEIGHT tables ARE the public contract with
    the frontend. If anyone reshuffles them, these tests should scream."""

    def test_severity_weights_match_documented_values(self):
        assert SEVERITY_WEIGHT == {"info": 0, "warning": 1, "critical": 2}

    def test_known_event_types_have_expected_severity(self):
        # Phase A
        assert EVENT_TYPES["tab_blur"] == "warning"
        assert EVENT_TYPES["window_blur"] == "warning"
        assert EVENT_TYPES["visibility_hidden"] == "warning"
        assert EVENT_TYPES["camera_lost"] == "critical"
        # Phase B
        assert EVENT_TYPES["camera_dark"] == "warning"
        # Phase C
        assert EVENT_TYPES["no_face"] == "warning"
        assert EVENT_TYPES["multi_face"] == "critical"


class TestRecordEvent:
    def test_warning_event_increments_count_by_one(self):
        monitor = make_monitor()
        result = monitor.record_event("tab_blur")
        assert result["severity"] == "warning"
        assert result["count"] == 1
        assert result["max"] == IntegrityMonitor.MAX_WARNINGS
        assert result["terminate"] is False

    def test_critical_event_increments_count_by_two(self):
        monitor = make_monitor()
        result = monitor.record_event("camera_lost")
        assert result["severity"] == "critical"
        assert result["count"] == 2
        assert result["terminate"] is False  # 2 < 3

    def test_unknown_event_type_is_info_and_does_not_increment(self):
        monitor = make_monitor()
        result = monitor.record_event("something_unexpected")
        assert result["severity"] == "info"
        assert result["count"] == 0
        assert result["terminate"] is False

    def test_result_dict_carries_event_type_through(self):
        monitor = make_monitor()
        result = monitor.record_event("multi_face")
        assert result["event_type"] == "multi_face"

    def test_metadata_defaults_to_empty_when_omitted(self):
        supabase = MagicMock()
        monitor = make_monitor(supabase)
        monitor.record_event("tab_blur")
        insert_call = supabase.table.return_value.insert.call_args
        assert insert_call.args[0]["metadata"] == {}

    def test_metadata_is_passed_through_to_insert(self):
        supabase = MagicMock()
        monitor = make_monitor(supabase)
        monitor.record_event("camera_dark", {"lum": 5.4})
        insert_call = supabase.table.return_value.insert.call_args
        assert insert_call.args[0]["metadata"] == {"lum": 5.4}

    def test_db_failure_does_not_raise_and_still_counts(self):
        """Persistence is best-effort; the in-memory counter is authoritative
        so a transient DB outage cannot let a candidate bypass the threshold.
        """
        supabase = MagicMock()
        supabase.table.side_effect = Exception("supabase down")
        monitor = make_monitor(supabase)
        result = monitor.record_event("tab_blur")
        assert result["count"] == 1
        assert monitor.warning_count == 1


class TestWarningThreshold:
    """MAX_WARNINGS=3 with severity-weighted increments. The cases below ARE
    the production contract — changing any of them is a UX-visible change."""

    def test_three_warnings_terminate(self):
        monitor = make_monitor()
        monitor.record_event("tab_blur")
        monitor.record_event("tab_blur")
        result = monitor.record_event("tab_blur")
        assert result["count"] == 3
        assert result["terminate"] is True

    def test_one_critical_plus_one_warning_terminate(self):
        monitor = make_monitor()
        monitor.record_event("camera_lost")  # +2
        result = monitor.record_event("tab_blur")  # +1 -> 3
        assert result["count"] == 3
        assert result["terminate"] is True

    def test_two_criticals_terminate(self):
        monitor = make_monitor()
        monitor.record_event("multi_face")  # +2
        result = monitor.record_event("multi_face")  # +2 -> 4
        assert result["count"] == 4
        assert result["terminate"] is True

    def test_single_critical_alone_does_not_terminate(self):
        """A single ambient hiccup must not end a session. Phase C design
        decision — see CHANGE 24/05/2026."""
        monitor = make_monitor()
        result = monitor.record_event("camera_lost")
        assert result["count"] == 2
        assert result["terminate"] is False

    def test_two_warnings_do_not_terminate(self):
        monitor = make_monitor()
        monitor.record_event("tab_blur")
        result = monitor.record_event("window_blur")
        assert result["count"] == 2
        assert result["terminate"] is False

    def test_info_events_never_contribute_to_termination(self):
        monitor = make_monitor()
        for _ in range(10):
            result = monitor.record_event("unknown_signal")
        assert result["count"] == 0
        assert result["terminate"] is False

    def test_terminate_remains_true_after_threshold_crossed(self):
        monitor = make_monitor()
        monitor.record_event("multi_face")  # +2
        monitor.record_event("tab_blur")  # +1 -> 3, terminate
        result = monitor.record_event("tab_blur")  # +1 -> 4, still terminate
        assert result["count"] == 4
        assert result["terminate"] is True


class TestMarkTerminated:
    def test_writes_terminated_integrity_status(self):
        supabase = MagicMock()
        monitor = make_monitor(supabase)
        monitor.mark_terminated()
        update_call = supabase.table.return_value.update.call_args
        assert update_call.args[0]["status"] == "terminated_integrity"

    def test_targets_the_correct_interview_row(self):
        supabase = MagicMock()
        iv_id = uuid4()
        monitor = IntegrityMonitor(iv_id, str(uuid4()))
        monitor._supabase = supabase
        monitor.mark_terminated()
        eq_call = supabase.table.return_value.update.return_value.eq.call_args
        assert eq_call.args == ("id", str(iv_id))

    def test_db_failure_does_not_raise(self):
        supabase = MagicMock()
        supabase.table.side_effect = Exception("supabase down")
        monitor = make_monitor(supabase)
        monitor.mark_terminated()  # must not raise
