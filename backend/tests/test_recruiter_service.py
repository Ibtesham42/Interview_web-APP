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
                    integrity=None, decisions=None, profiles=None):
    """Build a fake supabase client whose `.table('x')` routes per name."""
    table_rows = {
        "candidates": candidates or [],
        "interviews": interviews or [],
        "evaluations": evaluations or [],
        "interview_integrity_events": integrity or [],
        "recruiter_decisions": decisions or [],
        "profiles": profiles or [],
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


# ---------------------------------------------------------------------------
# Search (name / email / phone-in-resume / username) + status filter.
# These run in Python (the fake no-ops SQL), so they exercise the real
# matching logic rather than the push-down.
# ---------------------------------------------------------------------------

def _ids(result):
    return [r["candidate_id"] for r in result["items"]]


class TestRankCandidatesSearch:
    def _supabase(self):
        candidates = [
            {"id": "c1", "name": "Alice Smith", "email": "alice@acme.com",
             "field_specialization": "ml", "created_at": "2026-05-01T00:00:00Z",
             "user_id": "u1", "resume_text": "Python ML. Phone 8638278249."},
            {"id": "c2", "name": "Bob Jones", "email": "bob@globex.com",
             "field_specialization": "web_dev", "created_at": "2026-05-02T00:00:00Z",
             "user_id": "u2", "resume_text": "React dev. Call 5551234567."},
        ]
        return _fake_supabase(
            candidates=candidates,
            interviews=[_interview("iv1", "c1"), _interview("iv2", "c2")],
            profiles=[
                {"id": "u1", "username": "alice-handle"},
                {"id": "u2", "username": "bobby"},
            ],
        )

    def test_search_by_name(self):
        r = rank_candidates(self._supabase(), "rec", RankFilters(search="alice"))
        assert _ids(r) == ["c1"]

    def test_search_by_email_domain(self):
        r = rank_candidates(self._supabase(), "rec", RankFilters(search="globex"))
        assert _ids(r) == ["c2"]

    def test_search_by_phone_in_resume(self):
        r = rank_candidates(self._supabase(), "rec", RankFilters(search="8638278249"))
        assert _ids(r) == ["c1"]

    def test_search_by_username(self):
        r = rank_candidates(self._supabase(), "rec", RankFilters(search="bobby"))
        assert _ids(r) == ["c2"]

    def test_multi_token_and_of_ors(self):
        # "alice" (name) AND "ml" (field) — both must hit, possibly
        # different fields. Only c1 satisfies both.
        r = rank_candidates(self._supabase(), "rec", RankFilters(search="alice ml"))
        assert _ids(r) == ["c1"]

    def test_search_no_match_returns_empty(self):
        r = rank_candidates(self._supabase(), "rec", RankFilters(search="zzzznope"))
        assert _ids(r) == []


class TestRankCandidatesStatusFilter:
    def _supabase(self):
        candidates = [
            _candidate("c1", "Short"),     # shortlisted
            _candidate("c2", "Reject"),    # rejected
            _candidate("c3", "Held"),      # hold
            _candidate("c4", "Done"),      # completed, no decision
            _candidate("c5", "New"),       # no interview, no decision
        ]
        interviews = [
            _interview("iv1", "c1"), _interview("iv2", "c2"),
            _interview("iv3", "c3"), _interview("iv4", "c4"),
            # c5 has no interview → "invited"
        ]
        decisions = [
            {"candidate_id": "c1", "decision": "shortlisted", "bookmarked": False, "notes": ""},
            {"candidate_id": "c2", "decision": "rejected", "bookmarked": False, "notes": ""},
            {"candidate_id": "c3", "decision": "hold", "bookmarked": False, "notes": ""},
        ]
        return _fake_supabase(candidates=candidates, interviews=interviews,
                              decisions=decisions)

    def test_status_shortlisted(self):
        r = rank_candidates(self._supabase(), "rec", RankFilters(status="shortlisted"))
        assert _ids(r) == ["c1"]

    def test_status_rejected(self):
        r = rank_candidates(self._supabase(), "rec", RankFilters(status="rejected"))
        assert _ids(r) == ["c2"]

    def test_status_on_hold(self):
        r = rank_candidates(self._supabase(), "rec", RankFilters(status="on_hold"))
        assert _ids(r) == ["c3"]

    def test_status_interview_completed_excludes_decided(self):
        """Completed-but-undecided only — c1/c2/c3 have decisions, c5 has
        no interview, so only c4 is 'interview_completed'."""
        r = rank_candidates(self._supabase(), "rec", RankFilters(status="interview_completed"))
        assert _ids(r) == ["c4"]

    def test_status_invited_is_no_interview_no_decision(self):
        r = rank_candidates(self._supabase(), "rec", RankFilters(status="invited"))
        assert _ids(r) == ["c5"]

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError):
            RankFilters(status="pending").normalise()


class TestRankCandidatesInterviewDateRange:
    def _supabase(self):
        candidates = [_candidate("c1", "Early"), _candidate("c2", "Late"),
                      _candidate("c3", "NoIv")]
        interviews = [
            _interview("iv1", "c1", created_at="2026-05-05T00:00:00Z"),
            _interview("iv2", "c2", created_at="2026-05-20T00:00:00Z"),
            # c3 has no interview
        ]
        return _fake_supabase(candidates=candidates, interviews=interviews)

    def test_date_range_keeps_only_interviews_in_window(self):
        r = rank_candidates(
            self._supabase(), "rec",
            RankFilters(date_from="2026-05-01T00:00:00Z", date_to="2026-05-10T00:00:00Z"),
        )
        assert _ids(r) == ["c1"]

    def test_date_range_excludes_candidates_with_no_interview(self):
        r = rank_candidates(
            self._supabase(), "rec",
            RankFilters(date_from="2026-05-01T00:00:00Z", date_to="2026-12-31T00:00:00Z"),
        )
        assert "c3" not in _ids(r)
        assert set(_ids(r)) == {"c1", "c2"}


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
