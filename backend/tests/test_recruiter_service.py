"""Tests for the recruiter list/ranking service.

The service is the hybrid wrapper from grill A1 (RECRUITER_ROLLOUT.md):
SQL WHERE for non-score filters; bulk-score via the unchanged
`score_interviews_bulk`; Python sort + score-filter + paginate;
formula_mixed computed per-page. These tests pin:

- filter validation (sort/order/decision/integrity reject illegal values),
- the Python-side filters (score range, integrity, decision),
- sort key behaviour (final_score, name, decision rank, created_at None
  sorts last),
- pagination edge cases (page beyond range, page_size clamp at 100),
- formula_mixed (true only when the page mixes layer-aware + legacy),
- the "no recruiter_decisions row -> undecided/not bookmarked" default.

The fixtures fake the Supabase client by routing `.table(name)` to a
per-table builder whose `.execute().data` returns a queued list. Filter
methods are no-ops on the fake — that's the boundary the unit test
draws (the SQL composition itself is exercised by the existing pattern
elsewhere in the codebase and is hard to verify without a real PG).
"""
from unittest.mock import MagicMock

import pytest

from app.services.recruiter import RankFilters, rank_candidates


# ---------------------------------------------------------------------------
# A tiny in-memory fake of the supabase-py query builder. Each table has a
# fixed return value; the chain methods (.select/.eq/.in_/.gte/.lte/.or_)
# are no-ops that return the same chain so the call graph type-checks.
# ---------------------------------------------------------------------------

class _FakeQueryChain:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_a, **_kw): return self
    def eq(self, *_a, **_kw): return self
    def in_(self, *_a, **_kw): return self
    def gte(self, *_a, **_kw): return self
    def lte(self, *_a, **_kw): return self
    def or_(self, *_a, **_kw): return self

    def execute(self):
        resp = MagicMock()
        resp.data = self._rows
        return resp


def _fake_supabase(*, candidates=None, interviews=None, evaluations=None,
                    integrity=None, decisions=None):
    """Build a fake supabase client whose `.table('x')` routes per name."""
    table_rows = {
        "candidates": candidates or [],
        "interviews": interviews or [],
        "evaluations": evaluations or [],
        "interview_integrity_events": integrity or [],
        "recruiter_decisions": decisions or [],
    }
    supabase = MagicMock()
    supabase.table.side_effect = lambda name: _FakeQueryChain(table_rows[name])
    return supabase


# ---------------------------------------------------------------------------
# Filter normalisation
# ---------------------------------------------------------------------------

class TestRankFiltersNormalise:
    def test_defaults_normalise_clean(self):
        f = RankFilters().normalise()
        assert f.sort == "final_score"
        assert f.order == "desc"
        assert f.page == 1
        assert f.page_size == 50

    def test_invalid_sort_raises(self):
        with pytest.raises(ValueError):
            RankFilters(sort="loudness").normalise()

    def test_invalid_order_raises(self):
        with pytest.raises(ValueError):
            RankFilters(order="sideways").normalise()

    def test_invalid_decision_filter_raises(self):
        with pytest.raises(ValueError):
            RankFilters(decision="maybe").normalise()

    def test_invalid_integrity_filter_raises(self):
        with pytest.raises(ValueError):
            RankFilters(integrity="kinda").normalise()

    def test_page_size_clamped_to_100(self):
        """Grill A3: hard cap at 100 to avoid runaway pagination requests."""
        f = RankFilters(page_size=10_000).normalise()
        assert f.page_size == 100

    def test_page_size_floor_at_one(self):
        f = RankFilters(page_size=0).normalise()
        assert f.page_size == 1

    def test_page_floor_at_one(self):
        f = RankFilters(page=-5).normalise()
        assert f.page == 1

    def test_blank_search_collapses_to_none(self):
        """A trailing whitespace search input shouldn't turn into a
        wildcard match — collapse it."""
        f = RankFilters(search="   ").normalise()
        assert f.search is None


# ---------------------------------------------------------------------------
# rank_candidates — empty / no-candidates short circuit
# ---------------------------------------------------------------------------

class TestRankCandidatesEmpty:
    def test_no_candidates_returns_zero_page(self):
        supabase = _fake_supabase(candidates=[])
        result = rank_candidates(supabase, recruiter_id="rec-1", filters=RankFilters())
        assert result == {
            "items": [],
            "page": 1,
            "page_size": 50,
            "total_count": 0,
            "formula_mixed": False,
        }


# ---------------------------------------------------------------------------
# Per-row aggregation
# ---------------------------------------------------------------------------

def _candidate(cid, name, *, field="ml", created_at="2026-05-01T00:00:00Z"):
    return {
        "id": cid,
        "name": name,
        "email": f"{name.lower()}@x.com",
        "field_specialization": field,
        "created_at": created_at,
        "user_id": f"user-{cid}",
    }


def _interview(iid, cid, *, status="completed", created_at="2026-05-10T00:00:00Z"):
    return {"id": iid, "candidate_id": cid, "status": status, "created_at": created_at}


def _phase4_eval(iid, *, accuracy, layer=None):
    """Build an eval row that yields a final_score derived from phase 4
    accuracy (phase 4 weight is 0.30; with only phase 4 present, the
    weighted average renormalises to the phase 4 overall)."""
    details = {}
    if layer is not None:
        details["layer"] = layer
    return {
        "interview_id": iid,
        "phase": 4,
        "depth_score": 0,
        "accuracy_score": accuracy,
        "details": details,
    }


class TestRankCandidatesAggregation:
    def test_one_candidate_one_completed_interview(self):
        supabase = _fake_supabase(
            candidates=[_candidate("cand-1", "Alice")],
            interviews=[_interview("iv-1", "cand-1", status="completed")],
            evaluations=[_phase4_eval("iv-1", accuracy=8)],
        )
        result = rank_candidates(supabase, "rec-1", RankFilters())
        assert result["total_count"] == 1
        row = result["items"][0]
        assert row["candidate_id"] == "cand-1"
        assert row["name"] == "Alice"
        assert row["final_score"] == 8.0
        assert row["recommendation"] == "Hire"  # 7.0 <= 8 < 8.5
        assert row["interview_count"] == 1
        assert row["completed_count"] == 1
        assert row["integrity_warnings"] == 0
        assert row["decision"] == "undecided"
        assert row["bookmarked"] is False
        assert row["notes"] == ""

    def test_best_score_used_when_multiple_completed_attempts(self):
        """A candidate with 2 completed interviews shows the BEST score —
        Recruiters care about the candidate's ceiling, not their median."""
        supabase = _fake_supabase(
            candidates=[_candidate("cand-1", "Alice")],
            interviews=[
                _interview("iv-good", "cand-1", status="completed"),
                _interview("iv-bad", "cand-1", status="completed"),
            ],
            evaluations=[
                _phase4_eval("iv-good", accuracy=9),
                _phase4_eval("iv-bad", accuracy=4),
            ],
        )
        result = rank_candidates(supabase, "rec-1", RankFilters())
        assert result["items"][0]["final_score"] == 9.0

    def test_incomplete_interview_does_not_set_score(self):
        supabase = _fake_supabase(
            candidates=[_candidate("cand-1", "Alice")],
            interviews=[_interview("iv-1", "cand-1", status="in_progress")],
            evaluations=[_phase4_eval("iv-1", accuracy=10)],
        )
        result = rank_candidates(supabase, "rec-1", RankFilters())
        row = result["items"][0]
        assert row["final_score"] == 0.0
        assert row["completed_count"] == 0
        assert row["recommendation"] == ""  # no score => no rec

    def test_integrity_warnings_aggregated_across_interviews(self):
        supabase = _fake_supabase(
            candidates=[_candidate("cand-1", "Alice")],
            interviews=[
                _interview("iv-1", "cand-1"),
                _interview("iv-2", "cand-1"),
            ],
            integrity=[
                {"interview_id": "iv-1"},
                {"interview_id": "iv-1"},
                {"interview_id": "iv-2"},
            ],
        )
        result = rank_candidates(supabase, "rec-1", RankFilters())
        assert result["items"][0]["integrity_warnings"] == 3

    def test_decision_row_populates_row(self):
        supabase = _fake_supabase(
            candidates=[_candidate("cand-1", "Alice")],
            interviews=[_interview("iv-1", "cand-1")],
            evaluations=[_phase4_eval("iv-1", accuracy=8)],
            decisions=[{
                "candidate_id": "cand-1",
                "decision": "shortlisted",
                "bookmarked": True,
                "notes": "strong systems thinker",
            }],
        )
        result = rank_candidates(supabase, "rec-1", RankFilters())
        row = result["items"][0]
        assert row["decision"] == "shortlisted"
        assert row["bookmarked"] is True
        assert row["notes"] == "strong systems thinker"


# ---------------------------------------------------------------------------
# Python-side filters
# ---------------------------------------------------------------------------

class TestRankCandidatesFilters:
    def test_min_score_filters_below(self):
        supabase = _fake_supabase(
            candidates=[
                _candidate("cand-1", "Alice"),
                _candidate("cand-2", "Bob"),
            ],
            interviews=[
                _interview("iv-1", "cand-1"),
                _interview("iv-2", "cand-2"),
            ],
            evaluations=[
                _phase4_eval("iv-1", accuracy=9),
                _phase4_eval("iv-2", accuracy=4),
            ],
        )
        result = rank_candidates(supabase, "rec-1", RankFilters(min_score=7.0))
        names = [r["name"] for r in result["items"]]
        assert names == ["Alice"]

    def test_max_score_filters_above(self):
        supabase = _fake_supabase(
            candidates=[
                _candidate("cand-1", "Alice"),
                _candidate("cand-2", "Bob"),
            ],
            interviews=[
                _interview("iv-1", "cand-1"),
                _interview("iv-2", "cand-2"),
            ],
            evaluations=[
                _phase4_eval("iv-1", accuracy=9),
                _phase4_eval("iv-2", accuracy=4),
            ],
        )
        result = rank_candidates(supabase, "rec-1", RankFilters(max_score=6.0))
        names = [r["name"] for r in result["items"]]
        assert names == ["Bob"]

    def test_integrity_with_warnings_keeps_only_flagged(self):
        supabase = _fake_supabase(
            candidates=[
                _candidate("cand-1", "Alice"),
                _candidate("cand-2", "Bob"),
            ],
            interviews=[
                _interview("iv-1", "cand-1"),
                _interview("iv-2", "cand-2"),
            ],
            integrity=[{"interview_id": "iv-1"}],
        )
        result = rank_candidates(supabase, "rec-1", RankFilters(integrity="with_warnings"))
        assert [r["name"] for r in result["items"]] == ["Alice"]

    def test_integrity_without_warnings_drops_flagged(self):
        supabase = _fake_supabase(
            candidates=[
                _candidate("cand-1", "Alice"),
                _candidate("cand-2", "Bob"),
            ],
            interviews=[
                _interview("iv-1", "cand-1"),
                _interview("iv-2", "cand-2"),
            ],
            integrity=[{"interview_id": "iv-1"}],
        )
        result = rank_candidates(supabase, "rec-1", RankFilters(integrity="without_warnings"))
        assert [r["name"] for r in result["items"]] == ["Bob"]

    def test_decision_filter_matches_string(self):
        supabase = _fake_supabase(
            candidates=[
                _candidate("cand-1", "Alice"),
                _candidate("cand-2", "Bob"),
            ],
            decisions=[
                {"candidate_id": "cand-1", "decision": "shortlisted",
                 "bookmarked": False, "notes": ""},
                {"candidate_id": "cand-2", "decision": "rejected",
                 "bookmarked": False, "notes": ""},
            ],
        )
        result = rank_candidates(supabase, "rec-1", RankFilters(decision="shortlisted"))
        assert [r["name"] for r in result["items"]] == ["Alice"]

    def test_decision_filter_bookmarked_is_independent_of_decision_string(self):
        """A bookmarked 'undecided' candidate must surface in the bookmarked
        filter — bookmarks are an independent signal, not a decision value."""
        supabase = _fake_supabase(
            candidates=[
                _candidate("cand-1", "Alice"),
                _candidate("cand-2", "Bob"),
            ],
            decisions=[
                {"candidate_id": "cand-1", "decision": "undecided",
                 "bookmarked": True, "notes": ""},
                {"candidate_id": "cand-2", "decision": "rejected",
                 "bookmarked": False, "notes": ""},
            ],
        )
        result = rank_candidates(supabase, "rec-1", RankFilters(decision="bookmarked"))
        assert [r["name"] for r in result["items"]] == ["Alice"]


# ---------------------------------------------------------------------------
# Sort
# ---------------------------------------------------------------------------

class TestRankCandidatesSort:
    def _two_score_candidates(self):
        return _fake_supabase(
            candidates=[
                _candidate("cand-1", "Alice"),
                _candidate("cand-2", "Bob"),
            ],
            interviews=[
                _interview("iv-1", "cand-1"),
                _interview("iv-2", "cand-2"),
            ],
            evaluations=[
                _phase4_eval("iv-1", accuracy=4),
                _phase4_eval("iv-2", accuracy=9),
            ],
        )

    def test_default_sort_is_final_score_desc(self):
        result = rank_candidates(self._two_score_candidates(), "rec-1", RankFilters())
        assert [r["name"] for r in result["items"]] == ["Bob", "Alice"]

    def test_sort_final_score_asc(self):
        result = rank_candidates(self._two_score_candidates(), "rec-1",
                                 RankFilters(sort="final_score", order="asc"))
        assert [r["name"] for r in result["items"]] == ["Alice", "Bob"]

    def test_sort_by_name_asc(self):
        result = rank_candidates(self._two_score_candidates(), "rec-1",
                                 RankFilters(sort="name", order="asc"))
        assert [r["name"] for r in result["items"]] == ["Alice", "Bob"]

    def test_sort_by_decision_ranks_shortlisted_before_undecided(self):
        supabase = _fake_supabase(
            candidates=[
                _candidate("cand-1", "Alice"),
                _candidate("cand-2", "Bob"),
                _candidate("cand-3", "Carol"),
            ],
            decisions=[
                {"candidate_id": "cand-1", "decision": "rejected",
                 "bookmarked": False, "notes": ""},
                {"candidate_id": "cand-3", "decision": "shortlisted",
                 "bookmarked": False, "notes": ""},
            ],
        )
        result = rank_candidates(supabase, "rec-1",
                                 RankFilters(sort="decision", order="asc"))
        # shortlisted (rank 0) < undecided (rank 1) < rejected (rank 2)
        assert [r["name"] for r in result["items"]] == ["Carol", "Bob", "Alice"]

    def test_none_created_at_sorts_last_regardless_of_direction(self):
        """A candidate row with no created_at must not jump above real
        dates in a desc sort — it's not "more recent than 2025"."""
        supabase = _fake_supabase(
            candidates=[
                _candidate("cand-1", "Alice", created_at="2026-05-01T00:00:00Z"),
                _candidate("cand-2", "Bob", created_at=None),
                _candidate("cand-3", "Carol", created_at="2026-05-20T00:00:00Z"),
            ],
        )
        desc = rank_candidates(supabase, "rec-1",
                               RankFilters(sort="created_at", order="desc"))
        assert [r["name"] for r in desc["items"]] == ["Carol", "Alice", "Bob"]

        asc = rank_candidates(supabase, "rec-1",
                              RankFilters(sort="created_at", order="asc"))
        assert [r["name"] for r in asc["items"]] == ["Alice", "Carol", "Bob"]


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class TestRankCandidatesPagination:
    def _five_candidates(self):
        cands = [_candidate(f"cand-{i}", f"User{i}") for i in range(1, 6)]
        return _fake_supabase(candidates=cands)

    def test_first_page_returns_requested_size(self):
        result = rank_candidates(self._five_candidates(), "rec-1",
                                 RankFilters(page=1, page_size=2))
        assert len(result["items"]) == 2
        assert result["total_count"] == 5

    def test_last_page_returns_remainder(self):
        result = rank_candidates(self._five_candidates(), "rec-1",
                                 RankFilters(page=3, page_size=2))
        assert len(result["items"]) == 1
        assert result["total_count"] == 5

    def test_page_beyond_range_returns_empty_but_keeps_total(self):
        """A Recruiter who deep-paginates past the end still gets the
        accurate total so the UI can show "no more results"."""
        result = rank_candidates(self._five_candidates(), "rec-1",
                                 RankFilters(page=99, page_size=2))
        assert result["items"] == []
        assert result["total_count"] == 5


# ---------------------------------------------------------------------------
# formula_mixed
# ---------------------------------------------------------------------------

class TestRankCandidatesFormulaMixed:
    def test_all_layer_aware_is_not_mixed(self):
        supabase = _fake_supabase(
            candidates=[_candidate("cand-1", "Alice")],
            interviews=[_interview("iv-1", "cand-1")],
            evaluations=[_phase4_eval("iv-1", accuracy=8, layer=3)],
        )
        result = rank_candidates(supabase, "rec-1", RankFilters())
        assert result["formula_mixed"] is False

    def test_all_legacy_is_not_mixed(self):
        supabase = _fake_supabase(
            candidates=[_candidate("cand-1", "Alice")],
            interviews=[_interview("iv-1", "cand-1")],
            evaluations=[_phase4_eval("iv-1", accuracy=8)],  # no layer
        )
        result = rank_candidates(supabase, "rec-1", RankFilters())
        assert result["formula_mixed"] is False

    def test_mix_of_legacy_and_layer_aware_flips_mixed_true(self):
        supabase = _fake_supabase(
            candidates=[
                _candidate("cand-1", "Alice"),
                _candidate("cand-2", "Bob"),
            ],
            interviews=[
                _interview("iv-1", "cand-1"),
                _interview("iv-2", "cand-2"),
            ],
            evaluations=[
                _phase4_eval("iv-1", accuracy=8, layer=3),  # layer-aware
                _phase4_eval("iv-2", accuracy=6),           # legacy
            ],
        )
        result = rank_candidates(supabase, "rec-1", RankFilters())
        assert result["formula_mixed"] is True

    def test_no_completed_interviews_means_not_mixed(self):
        """formula_mixed is per-page over COMPLETED interviews — a page of
        candidates with only in-progress runs cannot be 'mixed'."""
        supabase = _fake_supabase(
            candidates=[_candidate("cand-1", "Alice")],
            interviews=[_interview("iv-1", "cand-1", status="in_progress")],
            evaluations=[_phase4_eval("iv-1", accuracy=8, layer=3)],
        )
        result = rank_candidates(supabase, "rec-1", RankFilters())
        assert result["formula_mixed"] is False
