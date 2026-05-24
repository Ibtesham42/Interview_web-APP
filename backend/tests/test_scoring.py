"""Tests for the shared scoring helpers in `interview_orchestrator`.

These functions are pure (or pure-over-a-supabase-mock) and load-bearing:
the detailed report, the candidate dashboard, and the admin analytics all
score interviews via the same path. A regression here moves dashboard
numbers silently. The cases below pin the formula weights, the layer-aware
vs historical branching, the recommendation thresholds, and the bulk-query
invariant (PROJECT_STATE invariant #5 — one query for many interviews).
"""

from unittest.mock import MagicMock

import pytest

from app.services.interview_orchestrator import (
    PHASE_WEIGHTS,
    compute_final_score,
    compute_phase_scores,
    recommendation_for,
    score_interviews_bulk,
)


# ---------------------------------------------------------------------------
# Tiny builders so the tests read like specs, not data fixtures.
# ---------------------------------------------------------------------------

def _phase1_eval(*, relevance=0, specificity=0, clarity=0, depth=0):
    return {
        "phase": 1,
        "details": {
            "relevance": relevance,
            "specificity": specificity,
            "clarity": clarity,
            "depth": depth,
        },
    }


def _deep_dive_eval(phase, *, depth=0, accuracy=0, clarity=None, layer=None):
    details = {}
    if clarity is not None:
        details["clarity"] = clarity
    if layer is not None:
        details["layer"] = layer
    return {
        "phase": phase,
        "depth_score": depth,
        "accuracy_score": accuracy,
        "details": details,
    }


def _phase4_eval(*, accuracy):
    return {"phase": 4, "accuracy_score": accuracy, "details": {}}


def _phase5_eval(*, vision=0, team=0, self_awareness=0, proactivity=0, communication=0):
    return {
        "phase": 5,
        "details": {
            "vision": vision,
            "team": team,
            "self_awareness": self_awareness,
            "proactivity": proactivity,
            "communication": communication,
        },
    }


class TestComputePhaseScoresEmpty:
    def test_empty_input_returns_empty_dict(self):
        assert compute_phase_scores([]) == {}

    def test_phases_with_no_evals_are_omitted(self):
        """Only phases that have evaluations should appear in the result."""
        result = compute_phase_scores([_phase4_eval(accuracy=7)])
        assert set(result.keys()) == {4}

    def test_unknown_phase_numbers_are_silently_dropped(self):
        """Phase 0 / 6+ never come from real interviews; tolerate without raising."""
        evals = [
            {"phase": 0, "details": {}},
            {"phase": 99, "details": {}},
            _phase4_eval(accuracy=8),
        ]
        result = compute_phase_scores(evals)
        assert set(result.keys()) == {4}


class TestComputePhaseScoresPhase1:
    """Phase 1 (warm-up) weights: 0.25 relevance + 0.25 specificity
    + 0.2 clarity + 0.3 depth."""

    def test_single_perfect_eval(self):
        result = compute_phase_scores([
            _phase1_eval(relevance=10, specificity=10, clarity=10, depth=10),
        ])
        assert result[1]["overall"] == 10.0
        assert result[1]["relevance_score"] == 10.0
        assert result[1]["specificity_score"] == 10.0
        assert result[1]["clarity_score"] == 10.0
        assert result[1]["depth_score"] == 10.0

    def test_weights_sum_to_one(self):
        """A uniform 8 across all axes should give an 8 overall."""
        result = compute_phase_scores([
            _phase1_eval(relevance=8, specificity=8, clarity=8, depth=8),
        ])
        assert result[1]["overall"] == 8.0

    def test_explicit_weight_calculation(self):
        # 6*0.25 + 8*0.25 + 4*0.2 + 10*0.3 = 1.5 + 2.0 + 0.8 + 3.0 = 7.3
        result = compute_phase_scores([
            _phase1_eval(relevance=6, specificity=8, clarity=4, depth=10),
        ])
        assert result[1]["overall"] == 7.3

    def test_two_evals_are_averaged(self):
        result = compute_phase_scores([
            _phase1_eval(relevance=10, specificity=10, clarity=10, depth=10),
            _phase1_eval(relevance=0, specificity=0, clarity=0, depth=0),
        ])
        assert result[1]["overall"] == 5.0


class TestComputePhaseScoresDeepDiveHistorical:
    """Phases 2/3 WITHOUT any `details.layer` use the historical formula.
    Default branch: 0.5 depth + 0.3 accuracy + 0.2 clarity (any clarity
    missing scores as 0, NOT as a different formula). Degenerate branch:
    when BOTH depth_score and details are absent across every eval, falls
    back to 0.7 depth + 0.3 accuracy."""

    def test_with_clarity_uses_the_three_axis_formula(self):
        # 8*0.5 + 6*0.3 + 10*0.2 = 4.0 + 1.8 + 2.0 = 7.8
        result = compute_phase_scores([
            _deep_dive_eval(2, depth=8, accuracy=6, clarity=10),
        ])
        assert result[2]["overall"] == 7.8

    def test_without_clarity_still_uses_three_axis_with_clarity_zero(self):
        """Subtle: an eval with depth_score but no `details.clarity` does
        NOT trip the 0.7/0.3 fallback — it runs the three-axis formula
        with avg_clarity=0. The fallback is gated on `depths or clarities`
        being empty, and `depth_score=8` populates `depths`."""
        # 8*0.5 + 6*0.3 + 0*0.2 = 4.0 + 1.8 + 0 = 5.8
        result = compute_phase_scores([_deep_dive_eval(2, depth=8, accuracy=6)])
        assert result[2]["overall"] == 5.8

    def test_degenerate_fallback_when_only_accuracy_present(self):
        """The only realistic shape that triggers the 0.7/0.3 fallback:
        an old eval row with `depth_score=None` and a falsy `details`."""
        evals = [{"phase": 2, "depth_score": None, "accuracy_score": 10,
                  "details": {}}]
        result = compute_phase_scores(evals)
        # 0*0.7 + 10*0.3 = 3.0
        assert result[2]["overall"] == 3.0

    def test_phase_3_uses_the_same_formula_as_phase_2(self):
        result_2 = compute_phase_scores([_deep_dive_eval(2, depth=8, accuracy=6)])
        result_3 = compute_phase_scores([_deep_dive_eval(3, depth=8, accuracy=6)])
        assert result_2[2]["overall"] == result_3[3]["overall"]

    def test_no_max_layer_key_when_historical(self):
        result = compute_phase_scores([_deep_dive_eval(2, depth=8, accuracy=6)])
        assert "max_layer" not in result[2]


class TestComputePhaseScoresDeepDiveLayerAware:
    """One eval with `details.layer` flips the layer-aware formula on for
    ALL phase 2/3 evals (ADR 0001 — forward-only scoring; the layer field
    only appears on post-Matryoshka interviews)."""

    def test_layer_aware_formula_explicit_weights(self):
        # depth=8, accuracy=6, clarity=10, max_layer=5 -> layer_score = 10.0
        # 8*0.4 + 6*0.25 + 10*0.15 + 10*0.2 = 3.2 + 1.5 + 1.5 + 2.0 = 8.2
        result = compute_phase_scores([
            _deep_dive_eval(2, depth=8, accuracy=6, clarity=10, layer=5),
        ])
        assert result[2]["overall"] == 8.2
        assert result[2]["max_layer"] == 5

    def test_max_layer_is_clamped_at_5(self):
        """Historical drill_level data could exceed 5; layer_score must clamp."""
        # max_layer=7 -> clamped to 5 -> layer_score = 10
        # 5*0.4 + 5*0.25 + 5*0.15 + 10*0.2 = 2.0 + 1.25 + 0.75 + 2.0 = 6.0
        result = compute_phase_scores([
            _deep_dive_eval(2, depth=5, accuracy=5, clarity=5, layer=7),
        ])
        assert result[2]["overall"] == 6.0
        assert result[2]["max_layer"] == 7  # raw layer is reported as-is

    def test_max_layer_is_the_max_of_all_layer_values(self):
        result = compute_phase_scores([
            _deep_dive_eval(2, depth=5, accuracy=5, layer=2),
            _deep_dive_eval(2, depth=5, accuracy=5, layer=4),
            _deep_dive_eval(2, depth=5, accuracy=5, layer=3),
        ])
        assert result[2]["max_layer"] == 4

    def test_single_layer_eval_flips_formula_for_the_whole_phase(self):
        """Any eval with details.layer triggers the layer-aware formula
        across the entire result — by design."""
        result = compute_phase_scores([
            _deep_dive_eval(2, depth=5, accuracy=5),
            _deep_dive_eval(2, depth=5, accuracy=5, layer=3),
        ])
        # If historical formula had run, "max_layer" wouldn't appear.
        assert "max_layer" in result[2]


class TestComputePhaseScoresPhase4:
    """Phase 4 (technical) reports a count of correct answers (accuracy >= 7)
    plus the average accuracy as the overall score."""

    def test_correct_answer_threshold_is_seven(self):
        result = compute_phase_scores([
            _phase4_eval(accuracy=7),
            _phase4_eval(accuracy=6),
            _phase4_eval(accuracy=10),
        ])
        assert result[4]["correct_answers"] == 2
        assert result[4]["total_questions"] == 3

    def test_overall_is_average_accuracy(self):
        result = compute_phase_scores([
            _phase4_eval(accuracy=8),
            _phase4_eval(accuracy=4),
        ])
        # (8 + 4) / 2 = 6.0; but the filter `if e.get("accuracy_score")`
        # excludes 0 values, so this also pins the falsy-filter behaviour.
        assert result[4]["overall"] == 6.0


class TestComputePhaseScoresPhase5:
    """Phase 5 (behavioral) averages five facets and overall = mean of all values."""

    def test_uniform_facets_give_clean_overall(self):
        result = compute_phase_scores([
            _phase5_eval(vision=8, team=8, self_awareness=8, proactivity=8, communication=8),
        ])
        assert result[5]["vision"] == 8
        assert result[5]["team"] == 8
        assert result[5]["self_awareness"] == 8
        assert result[5]["proactivity"] == 8
        assert result[5]["communication"] == 8
        assert result[5]["overall"] == 8.0

    def test_overall_is_mean_of_all_facet_values_across_evals(self):
        # Two evals × five facets = 10 values; sum=50; mean=5.0
        result = compute_phase_scores([
            _phase5_eval(vision=10, team=10, self_awareness=10, proactivity=10, communication=10),
            _phase5_eval(vision=0, team=0, self_awareness=0, proactivity=0, communication=0),
        ])
        assert result[5]["overall"] == 5.0


class TestComputeFinalScore:
    """Final score is a weighted average over phases 2-5 (phase 1 is NOT
    weighted into the final). Weights MUST sum to 1.0 across all four."""

    def test_phase_weights_sum_to_one(self):
        """If this ever drifts, every final score in the system moves silently.
        Pinning the invariant guards against an accidental retune."""
        assert round(sum(PHASE_WEIGHTS.values()), 4) == 1.0

    def test_phase_1_is_not_weighted_into_the_final(self):
        """Warm-up by design doesn't drag the score."""
        phase_scores = {1: {"overall": 0.0}}
        assert compute_final_score(phase_scores) == 0

    def test_empty_phase_scores_returns_zero(self):
        assert compute_final_score({}) == 0

    def test_uniform_ten_across_assessed_phases_returns_ten(self):
        phase_scores = {p: {"overall": 10} for p in (2, 3, 4, 5)}
        assert compute_final_score(phase_scores) == 10.0

    def test_explicit_weighted_average(self):
        # 8*0.30 + 7*0.25 + 6*0.30 + 5*0.15 = 2.40 + 1.75 + 1.80 + 0.75 = 6.70
        phase_scores = {
            2: {"overall": 8},
            3: {"overall": 7},
            4: {"overall": 6},
            5: {"overall": 5},
        }
        assert compute_final_score(phase_scores) == 6.70

    def test_partial_phases_renormalise_over_present_weights(self):
        """If only phase 5 ran (weight 0.15), the final equals that phase's
        score — the divisor is total_weight, not 1.0."""
        phase_scores = {5: {"overall": 8.4}}
        assert compute_final_score(phase_scores) == 8.4

    def test_missing_overall_treated_as_zero(self):
        """A malformed phase_scores entry must not crash the helper."""
        phase_scores = {2: {}, 3: {"overall": 10}}
        # phase 2 contributes 0*0.30; phase 3 contributes 10*0.25
        # total_weight = 0.55; weighted = 2.5; result = 2.5/0.55 ≈ 4.55
        assert compute_final_score(phase_scores) == 4.55


class TestRecommendationFor:
    """Boundary inputs are the failure mode — a 7.0 candidate must be 'Hire',
    not 'Hold'. Pinning every edge."""

    @pytest.mark.parametrize("score,expected", [
        (10.0, "Strong Hire"),
        (8.5, "Strong Hire"),     # boundary
        (8.49, "Hire"),
        (7.0, "Hire"),            # boundary
        (6.99, "Hold"),
        (5.5, "Hold"),            # boundary
        (5.49, "No Hire"),
        (0.0, "No Hire"),
    ])
    def test_thresholds(self, score, expected):
        assert recommendation_for(score) == expected


class TestScoreInterviewsBulk:
    """The dashboard / admin aggregations MUST issue exactly one SELECT to
    score N interviews (PROJECT_STATE invariant #5). These cases regression-
    guard that contract."""

    @staticmethod
    def _supabase_with_evals(eval_rows):
        """Wire a MagicMock so `supabase.table(..).select(..).in_(..).execute().data`
        returns the supplied rows."""
        supabase = MagicMock()
        chain = supabase.table.return_value
        chain.select.return_value = chain
        chain.in_.return_value = chain
        chain.execute.return_value.data = eval_rows
        return supabase

    def test_empty_id_list_short_circuits_without_db_call(self):
        supabase = MagicMock()
        assert score_interviews_bulk(supabase, []) == {}
        supabase.table.assert_not_called()

    def test_single_select_for_many_interviews(self):
        """The defining invariant: N interviews -> 1 SELECT."""
        supabase = self._supabase_with_evals([])
        score_interviews_bulk(supabase, ["iv-1", "iv-2", "iv-3", "iv-4"])
        assert supabase.table.call_count == 1
        assert supabase.table.call_args.args == ("evaluations",)

    def test_in_filter_is_keyed_on_the_full_id_list(self):
        supabase = self._supabase_with_evals([])
        score_interviews_bulk(supabase, ["iv-1", "iv-2"])
        in_call = supabase.table.return_value.in_.call_args
        assert in_call.args == ("interview_id", ["iv-1", "iv-2"])

    def test_returns_score_and_question_count_per_interview(self):
        # iv-A: one phase-4 row, accuracy=8 -> phase 4 overall=8 -> final=8*0.30/0.30=8
        # iv-B: no rows -> 0/0 questions
        eval_rows = [
            {"interview_id": "iv-A", "phase": 4, "depth_score": 0,
             "accuracy_score": 8, "details": {}},
        ]
        supabase = self._supabase_with_evals(eval_rows)
        result = score_interviews_bulk(supabase, ["iv-A", "iv-B"])
        assert set(result.keys()) == {"iv-A", "iv-B"}
        assert result["iv-A"] == {"score": 8.0, "questions": 1}
        assert result["iv-B"] == {"score": 0, "questions": 0}

    def test_grouping_is_per_interview_not_global(self):
        """Two interviews with their own rows must not bleed into each other."""
        eval_rows = [
            {"interview_id": "iv-A", "phase": 4, "depth_score": 0,
             "accuracy_score": 10, "details": {}},
            {"interview_id": "iv-B", "phase": 4, "depth_score": 0,
             "accuracy_score": 2, "details": {}},
        ]
        supabase = self._supabase_with_evals(eval_rows)
        result = score_interviews_bulk(supabase, ["iv-A", "iv-B"])
        assert result["iv-A"]["score"] == 10.0
        assert result["iv-B"]["score"] == 2.0

    def test_unrequested_interview_ids_in_evals_are_ignored(self):
        """If the DB returns rows for an id we didn't ask about (shouldn't
        happen, but the helper must not crash), they're dropped."""
        eval_rows = [
            {"interview_id": "iv-stray", "phase": 4, "depth_score": 0,
             "accuracy_score": 9, "details": {}},
        ]
        supabase = self._supabase_with_evals(eval_rows)
        result = score_interviews_bulk(supabase, ["iv-A"])
        assert set(result.keys()) == {"iv-A"}
        assert result["iv-A"] == {"score": 0, "questions": 0}
