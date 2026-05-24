"""Tests for the interview-termination logic in routers/interview_session.

`_finalize_status` is the single writer for `interviews.status` across all
four completion paths in the WebSocket handler. It also closes the
WS-disconnect bypass (CHANGE 24/05/2026 17:30) by consulting the in-memory
IntegrityMonitor counter and upgrading 'completed' to 'terminated_integrity'
when the threshold has been crossed.
"""

from unittest.mock import MagicMock

import pytest

from app.routers.interview_session import _finalize_status


class _FakeIntegrity:
    """Stand-in for IntegrityMonitor exposing the two attributes
    `_finalize_status` reads. Keeping a tiny local fake (rather than
    instantiating IntegrityMonitor) makes intent explicit and avoids
    coupling these tests to the real monitor's lazy supabase wiring.
    """

    MAX_WARNINGS = 3

    def __init__(self, warning_count: int):
        self.warning_count = warning_count


def _last_status_written(supabase: MagicMock) -> str:
    """Pull the `status` value from the most recent .update({...}) call."""
    update_call = supabase.table.return_value.update.call_args
    return update_call.args[0]["status"]


class TestFinalizeStatus:
    def test_completed_when_no_integrity_monitor_attached(self):
        """Older code paths (or sessions that never created a monitor) must
        still finalise cleanly as a normal completion."""
        supabase = MagicMock()
        status = _finalize_status(supabase, "iv-1", None)
        assert status == "completed"
        assert _last_status_written(supabase) == "completed"

    def test_completed_when_integrity_below_threshold(self):
        supabase = MagicMock()
        status = _finalize_status(supabase, "iv-2", _FakeIntegrity(0))
        assert status == "completed"
        assert _last_status_written(supabase) == "completed"

    def test_completed_when_integrity_one_below_threshold(self):
        """The off-by-one case: 2 warnings is still 'completed', 3 isn't."""
        supabase = MagicMock()
        status = _finalize_status(supabase, "iv-3", _FakeIntegrity(2))
        assert status == "completed"

    def test_terminated_integrity_exactly_at_threshold(self):
        supabase = MagicMock()
        status = _finalize_status(supabase, "iv-4", _FakeIntegrity(3))
        assert status == "terminated_integrity"
        assert _last_status_written(supabase) == "terminated_integrity"

    def test_terminated_integrity_over_threshold(self):
        """Two criticals (weight 4) is the realistic over-threshold case."""
        supabase = MagicMock()
        status = _finalize_status(supabase, "iv-5", _FakeIntegrity(4))
        assert status == "terminated_integrity"
        assert _last_status_written(supabase) == "terminated_integrity"

    def test_db_failure_does_not_raise_and_returns_intended_status(self):
        """The helper swallows DB errors in a single place so callers don't
        each need a try/except. Behaviour must be identical to a successful
        write from the caller's perspective."""
        supabase = MagicMock()
        supabase.table.side_effect = Exception("supabase down")
        status_no_int = _finalize_status(supabase, "iv-6", None)
        status_term = _finalize_status(supabase, "iv-7", _FakeIntegrity(3))
        assert status_no_int == "completed"
        assert status_term == "terminated_integrity"

    def test_completed_at_timestamp_is_written(self):
        """Dashboards key off `completed_at` for the duration column."""
        supabase = MagicMock()
        _finalize_status(supabase, "iv-8", None)
        update_call = supabase.table.return_value.update.call_args
        assert update_call.args[0]["completed_at"] == "now()"

    def test_update_targets_the_correct_interview_row(self):
        supabase = MagicMock()
        _finalize_status(supabase, "iv-9-specific", None)
        eq_call = supabase.table.return_value.update.return_value.eq.call_args
        assert eq_call.args == ("id", "iv-9-specific")

    def test_supabase_table_target_is_interviews(self):
        supabase = MagicMock()
        _finalize_status(supabase, "iv-10", None)
        assert supabase.table.call_args.args == ("interviews",)


class TestBypassPrevention:
    """The reason `_finalize_status` exists at all: a candidate must not be
    able to land on 'completed' by closing the WS or sending end_interview
    after crossing the integrity threshold. These cases are the regression
    guards for that bypass."""

    def test_threshold_crossed_then_end_interview_path_terminates(self):
        """Caller is the explicit end_interview message handler."""
        supabase = MagicMock()
        status = _finalize_status(supabase, "iv-bypass-1", _FakeIntegrity(3))
        assert status == "terminated_integrity"

    def test_threshold_crossed_then_natural_completion_terminates(self):
        """Caller is the natural-end (final_question_asked) branch."""
        supabase = MagicMock()
        status = _finalize_status(supabase, "iv-bypass-2", _FakeIntegrity(5))
        assert status == "terminated_integrity"

    def test_under_threshold_then_natural_completion_completes(self):
        """A natural completion with one stray warning is still 'completed';
        the markdown badge / events panel surface the warning separately."""
        supabase = MagicMock()
        status = _finalize_status(supabase, "iv-bypass-3", _FakeIntegrity(1))
        assert status == "completed"
