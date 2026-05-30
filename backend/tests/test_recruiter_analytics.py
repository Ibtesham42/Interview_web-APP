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
    candidate_analytics_summary,
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
                    evaluations=None, integrity=None, email_outbox=None,
                    integrity_raises=False):
    table_rows = {
        "candidates": candidates or [],
        "interviews": interviews or [],
        "recruiter_decisions": decisions or [],
        "evaluations": evaluations or [],
        "interview_integrity_events": integrity or [],
        "email_outbox": email_outbox or [],
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


# ---------------------------------------------------------------------------
# candidate_analytics_summary (recruiter/company analytics dashboard)
# ---------------------------------------------------------------------------

def _summary_fixture():
    """Three candidates: one shortlisted (completed), one rejected
    (completed), one on-hold (not completed), plus a 4th invited-only
    (signed up, no interview). Two invite emails. All in company A."""
    A = "co-a"
    candidates = [
        {"id": "c1", "name": "Alice Smith", "email": "alice@x.com",
         "created_at": "2026-05-01T00:00:00Z", "company_id": A},
        {"id": "c2", "name": "Bob Jones", "email": "bob@x.com",
         "created_at": "2026-05-02T00:00:00Z", "company_id": A},
        {"id": "c3", "name": "Carol Lee", "email": "carol@x.com",
         "created_at": "2026-05-03T00:00:00Z", "company_id": A},
        {"id": "c4", "name": "Dan Roe", "email": "dan@x.com",
         "created_at": "2026-05-04T00:00:00Z", "company_id": A},
    ]
    interviews = [
        {"id": "iv1", "candidate_id": "c1", "status": "completed",
         "created_at": "2026-05-10T00:00:00Z", "company_id": A},
        {"id": "iv2", "candidate_id": "c2", "status": "completed",
         "created_at": "2026-05-11T00:00:00Z", "company_id": A},
        {"id": "iv3", "candidate_id": "c3", "status": "in_progress",
         "created_at": "2026-05-12T00:00:00Z", "company_id": A},
    ]
    decisions = [
        {"candidate_id": "c1", "decision": "shortlisted", "company_id": A},
        {"candidate_id": "c2", "decision": "rejected", "company_id": A},
        {"candidate_id": "c3", "decision": "hold", "company_id": A},
    ]
    email_outbox = [
        {"to_email": "alice@x.com", "candidate_id": None, "company_id": A},
        {"to_email": "newperson@x.com", "candidate_id": None, "company_id": A},
        # A shortlist email (candidate_id set) must NOT count as an invite.
        {"to_email": "alice@x.com", "candidate_id": "c1", "company_id": A},
    ]
    return _fake_supabase(candidates=candidates, interviews=interviews,
                          decisions=decisions, email_outbox=email_outbox)


class TestCandidateAnalyticsSummaryTotals:
    def test_empty_state(self):
        result = candidate_analytics_summary(_fake_supabase())
        t = result["totals"]
        assert t == {
            "invited": 0, "registrations": 0, "interviews_completed": 0,
            "shortlisted": 0, "rejected": 0, "on_hold": 0,
            "completion_rate": 0.0, "shortlist_rate": 0.0,
        }
        assert result["recent_activity"] == []

    def test_totals_counts(self):
        result = candidate_analytics_summary(_summary_fixture())
        t = result["totals"]
        assert t["registrations"] == 4
        assert t["interviews_completed"] == 2          # iv1 + iv2
        assert t["shortlisted"] == 1
        assert t["rejected"] == 1
        assert t["on_hold"] == 1
        assert t["invited"] == 2                        # distinct invite recipients
        # 2 of 4 candidates completed → 50%
        assert t["completion_rate"] == 50.0
        # 1 shortlisted of 2 completed → 50%
        assert t["shortlist_rate"] == 50.0

    def test_status_precedence_shortlist_wins(self):
        """A candidate both shortlisted and rejected counts once, as
        shortlisted (mirrors deriveStatus / ADR 0011)."""
        supabase = _fake_supabase(
            candidates=[{"id": "c1", "name": "X", "email": "x@x.com",
                         "created_at": "2026-05-01T00:00:00Z"}],
            interviews=[{"id": "iv1", "candidate_id": "c1",
                         "status": "completed", "created_at": "2026-05-10T00:00:00Z"}],
            decisions=[
                {"candidate_id": "c1", "decision": "shortlisted"},
                {"candidate_id": "c1", "decision": "rejected"},
            ],
        )
        t = candidate_analytics_summary(supabase)["totals"]
        assert t["shortlisted"] == 1
        assert t["rejected"] == 0


class TestCandidateAnalyticsSummaryActivity:
    def test_recent_activity_shape_and_order(self):
        result = candidate_analytics_summary(_summary_fixture())
        rows = result["recent_activity"]
        # 4 candidates; ordered by latest interview desc, the
        # interview-less candidate (Dan) sorts last.
        assert [r["candidate_id"] for r in rows] == ["c3", "c2", "c1", "c4"]
        assert rows[-1]["candidate_id"] == "c4"
        assert rows[0]["status"] == "on_hold"

    def test_name_filter(self):
        result = candidate_analytics_summary(_summary_fixture(), name="alice")
        assert [r["candidate_id"] for r in result["recent_activity"]] == ["c1"]

    def test_email_filter(self):
        result = candidate_analytics_summary(_summary_fixture(), email="bob@")
        assert [r["candidate_id"] for r in result["recent_activity"]] == ["c2"]

    def test_status_filter(self):
        result = candidate_analytics_summary(_summary_fixture(), status="rejected")
        ids = [r["candidate_id"] for r in result["recent_activity"]]
        assert ids == ["c2"]

    def test_interview_date_range_filter(self):
        # Only iv1 (c1) falls in this window.
        result = candidate_analytics_summary(
            _summary_fixture(),
            date_from="2026-05-10T00:00:00Z",
            date_to="2026-05-10T23:59:59Z",
        )
        assert [r["candidate_id"] for r in result["recent_activity"]] == ["c1"]

    def test_totals_unaffected_by_activity_filters(self):
        """KPI totals are company all-time — a name filter narrows the
        activity table but not the headline numbers."""
        result = candidate_analytics_summary(_summary_fixture(), name="alice")
        assert result["totals"]["registrations"] == 4
        assert len(result["recent_activity"]) == 1


class TestCandidateAnalyticsSummaryTenantScope:
    def _two_tenant(self):
        return _fake_supabase(
            candidates=[
                {"id": "a1", "name": "A One", "email": "a1@x.com",
                 "created_at": "2026-05-01T00:00:00Z", "company_id": "co-a"},
                {"id": "b1", "name": "B One", "email": "b1@x.com",
                 "created_at": "2026-05-01T00:00:00Z", "company_id": "co-b"},
            ],
            interviews=[
                {"id": "ia", "candidate_id": "a1", "status": "completed",
                 "created_at": "2026-05-10T00:00:00Z", "company_id": "co-a"},
                {"id": "ib", "candidate_id": "b1", "status": "completed",
                 "created_at": "2026-05-10T00:00:00Z", "company_id": "co-b"},
            ],
        )

    def test_scoped_to_own_company(self):
        result = candidate_analytics_summary(self._two_tenant(), company_id="co-a")
        assert result["totals"]["registrations"] == 1
        assert [r["candidate_id"] for r in result["recent_activity"]] == ["a1"]

    def test_platform_admin_sees_all(self):
        result = candidate_analytics_summary(self._two_tenant(), company_id=None)
        assert result["totals"]["registrations"] == 2
