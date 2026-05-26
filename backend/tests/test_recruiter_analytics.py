"""Tests for the recruiter analytics aggregations (PR 6).

Pins the four contracts:
- 4-stage funnel counts collapse correctly: a Candidate appears in
  each stage they've reached, and only once (multiple interviews,
  multiple recruiters shortlisting → still one Candidate at that
  stage).
- Conversion rates are percent-of-prev-stage, rounded to 1dp, with 0
  on a zero denominator (never NaN).
- by_field carries the same arithmetic per field_specialization, with
  unset fields bucketed as 'general'.
- scores_by_field uses BEST completed score per Candidate (matches the
  dashboard rule).
- integrity_event_volume groups by event_type, sorted desc, swallows
  a missing table cleanly.

ADR 0004 is referenced by FUNNEL_STAGES order — if that ever drifts,
ADR 0004 needs an update first, then this test.
"""
from unittest.mock import MagicMock

from app.services.recruiter_analytics import (
    FUNNEL_STAGES,
    hiring_funnel,
    integrity_event_volume,
    scores_by_field,
)


# ---------------------------------------------------------------------------
# Per-table fake: candidates / interviews / recruiter_decisions /
# evaluations / interview_integrity_events. The recruiter_decisions
# chain needs eq() because hiring_funnel filters by decision.
# ---------------------------------------------------------------------------

class _FakeQueryChain:
    def __init__(self, rows, *, eq_filters=None):
        self._rows = rows
        self._eq = dict(eq_filters or {})

    def select(self, *_a, **_kw): return self
    def in_(self, *_a, **_kw): return self
    def order(self, *_a, **_kw): return self

    def eq(self, column, value):
        self._eq[column] = value
        return self

    def execute(self):
        rows = self._rows
        if self._eq:
            rows = [r for r in rows if all(r.get(k) == v
                    for k, v in self._eq.items())]
        return MagicMock(data=rows)


def _fake_supabase(*, candidates=None, interviews=None, decisions=None,
                    evaluations=None, integrity=None,
                    integrity_raises=False):
    table_rows = {
        "candidates": candidates or [],
        "interviews": interviews or [],
        "recruiter_decisions": decisions or [],
        "evaluations": evaluations or [],
        "interview_integrity_events": integrity or [],
    }
    supabase = MagicMock()

    def route(name):
        if name == "interview_integrity_events" and integrity_raises:
            raise RuntimeError("table missing")
        return _FakeQueryChain(table_rows[name])

    supabase.table.side_effect = route
    return supabase


# ---------------------------------------------------------------------------
# hiring_funnel
# ---------------------------------------------------------------------------

class TestHiringFunnelStages:
    def test_empty_state_returns_zero_counts(self):
        supabase = _fake_supabase()
        result = hiring_funnel(supabase)
        assert result["stages"] == [{"stage": s, "count": 0} for s in FUNNEL_STAGES]
        assert result["by_field"] == {}

    def test_stage_order_matches_adr_0004(self):
        """If FUNNEL_STAGES drifts, the chart axis order silently
        flips - pin it."""
        assert FUNNEL_STAGES == [
            "signed_up", "interview_started",
            "interview_completed", "shortlisted",
        ]

    def test_candidate_only_signed_up(self):
        supabase = _fake_supabase(
            candidates=[{"id": "cand-1", "field_specialization": "ml"}],
        )
        result = hiring_funnel(supabase)
        counts = {s["stage"]: s["count"] for s in result["stages"]}
        assert counts == {
            "signed_up": 1,
            "interview_started": 0,
            "interview_completed": 0,
            "shortlisted": 0,
        }

    def test_started_includes_any_interview_status(self):
        """A Candidate who started ANY interview counts as started -
        the interview doesn't have to be completed."""
        supabase = _fake_supabase(
            candidates=[{"id": "cand-1", "field_specialization": "ml"}],
            interviews=[{"candidate_id": "cand-1", "status": "in_progress"}],
        )
        result = hiring_funnel(supabase)
        counts = {s["stage"]: s["count"] for s in result["stages"]}
        assert counts["interview_started"] == 1
        assert counts["interview_completed"] == 0

    def test_completed_requires_status_completed(self):
        supabase = _fake_supabase(
            candidates=[
                {"id": "cand-1", "field_specialization": "ml"},
                {"id": "cand-2", "field_specialization": "ml"},
            ],
            interviews=[
                {"candidate_id": "cand-1", "status": "completed"},
                {"candidate_id": "cand-2", "status": "in_progress"},
            ],
        )
        counts = {s["stage"]: s["count"] for s in hiring_funnel(supabase)["stages"]}
        assert counts["interview_completed"] == 1

    def test_multiple_interviews_per_candidate_count_once(self):
        """A Candidate with 3 interviews is still ONE candidate in the
        funnel - the funnel counts unique candidates per stage."""
        supabase = _fake_supabase(
            candidates=[{"id": "cand-1", "field_specialization": "ml"}],
            interviews=[
                {"candidate_id": "cand-1", "status": "completed"},
                {"candidate_id": "cand-1", "status": "completed"},
                {"candidate_id": "cand-1", "status": "in_progress"},
            ],
        )
        counts = {s["stage"]: s["count"] for s in hiring_funnel(supabase)["stages"]}
        assert counts["interview_started"] == 1
        assert counts["interview_completed"] == 1

    def test_shortlisted_collapses_across_recruiters(self):
        """Two recruiters shortlisting the same Candidate is still one
        Candidate at the shortlisted stage. The funnel is per-Candidate,
        not per-Decision."""
        supabase = _fake_supabase(
            candidates=[{"id": "cand-1", "field_specialization": "ml"}],
            decisions=[
                {"candidate_id": "cand-1", "decision": "shortlisted"},
                {"candidate_id": "cand-1", "decision": "shortlisted"},
            ],
        )
        counts = {s["stage"]: s["count"] for s in hiring_funnel(supabase)["stages"]}
        assert counts["shortlisted"] == 1

    def test_non_shortlisted_decisions_do_not_count(self):
        """Rejected and undecided rows must not bump the shortlist
        stage - the .eq('decision', 'shortlisted') filter at the SQL
        layer handles this; the test pins it across the fake too."""
        supabase = _fake_supabase(
            candidates=[{"id": "cand-1", "field_specialization": "ml"}],
            decisions=[{"candidate_id": "cand-1", "decision": "rejected"}],
        )
        counts = {s["stage"]: s["count"] for s in hiring_funnel(supabase)["stages"]}
        assert counts["shortlisted"] == 0


class TestHiringFunnelConversionRates:
    def test_zero_denominator_yields_zero_not_nan(self):
        """A funnel with 0 signed_up must report 0.0 conversion (never
        NaN, since that breaks the chart and JSON serialization)."""
        supabase = _fake_supabase()
        result = hiring_funnel(supabase)
        rates = result["conversion_rates"]
        assert rates["signed_up_to_started"] == 0.0
        assert rates["started_to_completed"] == 0.0
        assert rates["completed_to_shortlisted"] == 0.0

    def test_rates_are_percent_rounded_to_one_dp(self):
        # 3 signed_up, 2 started, 1 completed, 1 shortlisted
        # signed→started = 2/3 = 66.7
        # started→completed = 1/2 = 50.0
        # completed→shortlisted = 1/1 = 100.0
        supabase = _fake_supabase(
            candidates=[
                {"id": "cand-1", "field_specialization": "ml"},
                {"id": "cand-2", "field_specialization": "ml"},
                {"id": "cand-3", "field_specialization": "ml"},
            ],
            interviews=[
                {"candidate_id": "cand-1", "status": "completed"},
                {"candidate_id": "cand-2", "status": "in_progress"},
            ],
            decisions=[
                {"candidate_id": "cand-1", "decision": "shortlisted"},
            ],
        )
        rates = hiring_funnel(supabase)["conversion_rates"]
        assert rates["signed_up_to_started"] == 66.7
        assert rates["started_to_completed"] == 50.0
        assert rates["completed_to_shortlisted"] == 100.0


class TestHiringFunnelByField:
    def test_unset_field_buckets_to_general(self):
        supabase = _fake_supabase(
            candidates=[
                {"id": "cand-1", "field_specialization": None},
                {"id": "cand-2", "field_specialization": ""},
            ],
        )
        result = hiring_funnel(supabase)
        assert "general" in result["by_field"]
        general = result["by_field"]["general"]
        assert general["stages"][0] == {"stage": "signed_up", "count": 2}

    def test_per_field_funnel_arithmetic_is_isolated(self):
        supabase = _fake_supabase(
            candidates=[
                {"id": "cand-1", "field_specialization": "ml"},
                {"id": "cand-2", "field_specialization": "web_dev"},
            ],
            interviews=[
                {"candidate_id": "cand-1", "status": "completed"},
            ],
            decisions=[
                {"candidate_id": "cand-2", "decision": "shortlisted"},
            ],
        )
        result = hiring_funnel(supabase)
        ml = {s["stage"]: s["count"] for s in result["by_field"]["ml"]["stages"]}
        web = {s["stage"]: s["count"] for s in result["by_field"]["web_dev"]["stages"]}
        assert ml == {
            "signed_up": 1, "interview_started": 1,
            "interview_completed": 1, "shortlisted": 0,
        }
        assert web == {
            "signed_up": 1, "interview_started": 0,
            "interview_completed": 0, "shortlisted": 1,
        }


# ---------------------------------------------------------------------------
# scores_by_field
# ---------------------------------------------------------------------------

def _phase4_eval(iid, accuracy):
    return {"interview_id": iid, "phase": 4, "depth_score": 0,
            "accuracy_score": accuracy, "details": {}}


class TestScoresByField:
    def test_empty_state(self):
        result = scores_by_field(_fake_supabase())
        assert result == {"items": []}

    def test_best_completed_score_per_candidate(self):
        """Average per field is over per-candidate BEST scores, not over
        every completed interview - matches the dashboard rule."""
        supabase = _fake_supabase(
            candidates=[{"id": "cand-1", "field_specialization": "ml"}],
            interviews=[
                {"id": "iv-low", "candidate_id": "cand-1", "status": "completed"},
                {"id": "iv-high", "candidate_id": "cand-1", "status": "completed"},
            ],
            evaluations=[
                _phase4_eval("iv-low", 4),
                _phase4_eval("iv-high", 9),
            ],
        )
        items = scores_by_field(supabase)["items"]
        assert items == [
            {"field": "ml", "candidate_count": 1, "average_score": 9.0},
        ]

    def test_in_progress_runs_excluded(self):
        supabase = _fake_supabase(
            candidates=[{"id": "cand-1", "field_specialization": "ml"}],
            interviews=[
                {"id": "iv-1", "candidate_id": "cand-1", "status": "in_progress"},
            ],
            evaluations=[_phase4_eval("iv-1", 10)],
        )
        assert scores_by_field(supabase)["items"] == []

    def test_sorted_descending_by_average(self):
        supabase = _fake_supabase(
            candidates=[
                {"id": "cand-a", "field_specialization": "ml"},
                {"id": "cand-b", "field_specialization": "web_dev"},
            ],
            interviews=[
                {"id": "iv-a", "candidate_id": "cand-a", "status": "completed"},
                {"id": "iv-b", "candidate_id": "cand-b", "status": "completed"},
            ],
            evaluations=[_phase4_eval("iv-a", 6), _phase4_eval("iv-b", 9)],
        )
        items = scores_by_field(supabase)["items"]
        assert [item["field"] for item in items] == ["web_dev", "ml"]


# ---------------------------------------------------------------------------
# integrity_event_volume
# ---------------------------------------------------------------------------

class TestIntegrityEventVolume:
    def test_empty_state(self):
        result = integrity_event_volume(_fake_supabase())
        assert result == {"items": [], "total": 0}

    def test_groups_by_event_type_sorted_desc(self):
        supabase = _fake_supabase(
            integrity=[
                {"event_type": "tab_blur"},
                {"event_type": "tab_blur"},
                {"event_type": "no_face"},
                {"event_type": "tab_blur"},
            ],
        )
        result = integrity_event_volume(supabase)
        assert result["items"] == [
            {"event_type": "tab_blur", "count": 3},
            {"event_type": "no_face", "count": 1},
        ]
        assert result["total"] == 4

    def test_missing_table_swallowed_cleanly(self):
        """Migration 002 may not have been applied yet; the analytics
        screen still has to render rather than 500."""
        supabase = _fake_supabase(integrity_raises=True)
        result = integrity_event_volume(supabase)
        assert result == {"items": [], "total": 0}

    def test_null_event_type_bucketed_as_unknown(self):
        supabase = _fake_supabase(
            integrity=[{"event_type": None}, {"event_type": None}],
        )
        result = integrity_event_volume(supabase)
        assert result["items"] == [{"event_type": "unknown", "count": 2}]
