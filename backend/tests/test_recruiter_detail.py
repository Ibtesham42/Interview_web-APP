"""Tests for `get_candidate_detail` — the detail view's data shape and
the B1 access-matrix enforcement.

The contract being pinned:
- Returns None when the candidate does not exist (so the router maps to
  404 without leaking existence).
- Interviews are scored via the same bulk path as the list endpoint
  (composes `score_interviews_bulk`).
- Every Recruiter's Decision row appears in `decisions` with author
  attribution and the viewer-relative `is_you` flag — both Admins and
  Recruiters read this. Accountability comes from attribution, not from
  hiding rows.
- `my_notes` is always the viewer's own notes string.
- `all_notes` is populated for `viewer_role == 'admin'` and is
  explicitly None for Recruiters — the client uses None vs [] as a
  signal of viewer role.
"""
from unittest.mock import MagicMock

from app.services.recruiter import get_candidate_detail


# Reuse the table-routing fake from the read-path tests.
class _FakeQueryChain:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_a, **_kw): return self
    def eq(self, *_a, **_kw): return self
    def in_(self, *_a, **_kw): return self
    def order(self, *_a, **_kw): return self

    def execute(self):
        resp = MagicMock()
        resp.data = self._rows
        return resp


def _fake_supabase(*, candidates=None, interviews=None, evaluations=None,
                    integrity=None, decisions=None, profiles=None):
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


def _candidate():
    return {
        "id": "cand-1",
        "name": "Alice",
        "email": "alice@example.com",
        "field_specialization": "ml",
        "created_at": "2026-05-01T00:00:00Z",
        "resume_text": "Built X. Did Y. Optimised Z.",
    }


class TestCandidateMissing:
    def test_unknown_candidate_returns_none(self):
        supabase = _fake_supabase(candidates=[])
        result = get_candidate_detail(supabase, "cand-missing",
                                      viewer_id="rec-1", viewer_role="recruiter")
        assert result is None


class TestCandidateShape:
    def test_header_includes_resume_excerpt(self):
        supabase = _fake_supabase(candidates=[_candidate()])
        result = get_candidate_detail(supabase, "cand-1",
                                      viewer_id="rec-1", viewer_role="recruiter")
        assert result["candidate"]["id"] == "cand-1"
        assert result["candidate"]["name"] == "Alice"
        assert result["candidate"]["resume_excerpt"] == "Built X. Did Y. Optimised Z."

    def test_resume_excerpt_is_truncated_at_1500_chars(self):
        big = _candidate()
        big["resume_text"] = "x" * 5000
        supabase = _fake_supabase(candidates=[big])
        result = get_candidate_detail(supabase, "cand-1",
                                      viewer_id="rec-1", viewer_role="recruiter")
        assert len(result["candidate"]["resume_excerpt"]) == 1500

    def test_missing_resume_text_yields_null_excerpt(self):
        cand = _candidate()
        cand["resume_text"] = None
        supabase = _fake_supabase(candidates=[cand])
        result = get_candidate_detail(supabase, "cand-1",
                                      viewer_id="rec-1", viewer_role="recruiter")
        assert result["candidate"]["resume_excerpt"] is None


class TestInterviewListing:
    def test_completed_interview_carries_score_and_recommendation(self):
        supabase = _fake_supabase(
            candidates=[_candidate()],
            interviews=[{
                "id": "iv-1",
                "status": "completed",
                "created_at": "2026-05-10T00:00:00Z",
                "completed_at": "2026-05-10T01:00:00Z",
            }],
            evaluations=[{
                "interview_id": "iv-1",
                "phase": 4,
                "depth_score": 0,
                "accuracy_score": 8,
                "details": {},
            }],
        )
        result = get_candidate_detail(supabase, "cand-1",
                                      viewer_id="rec-1", viewer_role="recruiter")
        iv = result["interviews"][0]
        assert iv["score"] == 8.0
        assert iv["recommendation"] == "Hire"
        assert iv["completed"] is True

    def test_in_progress_interview_has_no_recommendation(self):
        supabase = _fake_supabase(
            candidates=[_candidate()],
            interviews=[{
                "id": "iv-1",
                "status": "in_progress",
                "created_at": "2026-05-10T00:00:00Z",
                "completed_at": None,
            }],
        )
        result = get_candidate_detail(supabase, "cand-1",
                                      viewer_id="rec-1", viewer_role="recruiter")
        iv = result["interviews"][0]
        assert iv["recommendation"] == ""
        assert iv["completed"] is False

    def test_integrity_count_attaches_to_interview(self):
        supabase = _fake_supabase(
            candidates=[_candidate()],
            interviews=[{
                "id": "iv-1",
                "status": "completed",
                "created_at": "2026-05-10T00:00:00Z",
                "completed_at": "2026-05-10T01:00:00Z",
            }],
            integrity=[{"interview_id": "iv-1"}, {"interview_id": "iv-1"}],
        )
        result = get_candidate_detail(supabase, "cand-1",
                                      viewer_id="rec-1", viewer_role="recruiter")
        assert result["interviews"][0]["integrity_warnings"] == 2


# ---------------------------------------------------------------------------
# B1 access matrix — the load-bearing test class for this PR
# ---------------------------------------------------------------------------

class TestB1AccessMatrix:
    def _seed_two_recruiter_decisions(self):
        return _fake_supabase(
            candidates=[_candidate()],
            decisions=[
                {
                    "recruiter_id": "rec-self",
                    "decision": "shortlisted",
                    "bookmarked": True,
                    "notes": "MY private notes",
                    "decided_at": "2026-05-20T00:00:00Z",
                    "updated_at": "2026-05-20T00:00:00Z",
                },
                {
                    "recruiter_id": "rec-other",
                    "decision": "rejected",
                    "bookmarked": False,
                    "notes": "Other recruiter's private notes",
                    "decided_at": "2026-05-21T00:00:00Z",
                    "updated_at": "2026-05-21T00:00:00Z",
                },
            ],
            profiles=[
                {"id": "rec-self", "full_name": "Self Recruiter", "email": "self@x.com"},
                {"id": "rec-other", "full_name": "Other Recruiter", "email": "other@x.com"},
            ],
        )

    def test_recruiter_sees_only_own_notes(self):
        """The B1 rule: Recruiter↔Recruiter Notes are private."""
        supabase = self._seed_two_recruiter_decisions()
        result = get_candidate_detail(supabase, "cand-1",
                                      viewer_id="rec-self", viewer_role="recruiter")
        assert result["my_notes"] == "MY private notes"
        assert result["all_notes"] is None

    def test_recruiter_still_sees_every_decision_with_attribution(self):
        """B1: Decisions are NOT private — only Notes are. The attribution
        list must include every Recruiter so accountability is visible."""
        supabase = self._seed_two_recruiter_decisions()
        result = get_candidate_detail(supabase, "cand-1",
                                      viewer_id="rec-self", viewer_role="recruiter")
        decision_ids = {d["recruiter_id"] for d in result["decisions"]}
        assert decision_ids == {"rec-self", "rec-other"}

    def test_decisions_carry_is_you_flag(self):
        supabase = self._seed_two_recruiter_decisions()
        result = get_candidate_detail(supabase, "cand-1",
                                      viewer_id="rec-self", viewer_role="recruiter")
        is_you = {d["recruiter_id"]: d["is_you"] for d in result["decisions"]}
        assert is_you == {"rec-self": True, "rec-other": False}

    def test_admin_sees_all_notes_with_attribution(self):
        """B1: Admins see every Recruiter's Notes — needed to investigate
        why a Candidate was shortlisted/rejected, even after attrition."""
        supabase = self._seed_two_recruiter_decisions()
        result = get_candidate_detail(supabase, "cand-1",
                                      viewer_id="admin-1", viewer_role="admin")
        assert result["all_notes"] is not None
        notes_by_recruiter = {n["recruiter_id"]: n["notes"] for n in result["all_notes"]}
        assert notes_by_recruiter == {
            "rec-self": "MY private notes",
            "rec-other": "Other recruiter's private notes",
        }

    def test_admin_my_notes_reflects_their_own_row_only(self):
        """An Admin with their own Decision row sees those as my_notes;
        otherwise my_notes is empty even though all_notes is populated."""
        supabase = self._seed_two_recruiter_decisions()
        result = get_candidate_detail(supabase, "cand-1",
                                      viewer_id="admin-novote", viewer_role="admin")
        assert result["my_notes"] == ""
        assert len(result["all_notes"]) == 2

    def test_author_name_falls_back_to_email_then_label(self):
        """Profiles without a full_name should still surface readably."""
        supabase = _fake_supabase(
            candidates=[_candidate()],
            decisions=[
                {"recruiter_id": "rec-1", "decision": "shortlisted",
                 "bookmarked": False, "notes": "", "decided_at": None,
                 "updated_at": None},
                {"recruiter_id": "rec-2", "decision": "rejected",
                 "bookmarked": False, "notes": "", "decided_at": None,
                 "updated_at": None},
            ],
            profiles=[
                {"id": "rec-1", "full_name": None, "email": "first@x.com"},
                # rec-2 missing from profiles entirely
            ],
        )
        result = get_candidate_detail(supabase, "cand-1",
                                      viewer_id="someone", viewer_role="admin")
        names = {d["recruiter_id"]: d["recruiter_name"] for d in result["decisions"]}
        assert names["rec-1"] == "first@x.com"
        assert names["rec-2"] == "Recruiter"


class TestNoDecisionsYet:
    def test_brand_new_candidate_has_clean_empty_state(self):
        """A Candidate nobody has touched: empty decisions, empty
        my_notes, all_notes empty list (admin) or None (recruiter)."""
        supabase = _fake_supabase(candidates=[_candidate()])
        recruiter_view = get_candidate_detail(
            supabase, "cand-1", viewer_id="rec-1", viewer_role="recruiter",
        )
        assert recruiter_view["decisions"] == []
        assert recruiter_view["my_notes"] == ""
        assert recruiter_view["all_notes"] is None

        admin_view = get_candidate_detail(
            supabase, "cand-1", viewer_id="admin-1", viewer_role="admin",
        )
        assert admin_view["decisions"] == []
        assert admin_view["all_notes"] == []
