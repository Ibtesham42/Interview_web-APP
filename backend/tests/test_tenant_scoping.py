"""Tenant-scoping tests for multi-tenant PR 1.

These tests pin the bulk-query tenant filter behaviour added to
`services/recruiter.py` and `services/recruiter_analytics.py`:

- `rank_candidates`, `get_candidate_detail`, `candidate_tenant`,
  `hiring_funnel`, `scores_by_field`, `integrity_event_volume` all accept
  a `company_id` / `scope` keyword.
- When non-None: results include only rows whose `company_id` matches.
- When None: no filter is applied (platform-admin path).

The fakes here are smarter than the ones in `test_recruiter_service.py`
on purpose: those fakes treat `.eq()` as a no-op (the production SQL
composition is what's being unit-tested over there). Here we need the
fake to honour `.eq("company_id", X)` so the assertion "only A's data
came back" is actually meaningful — otherwise the filter could be
silently dropped and the test would still pass. The fake records every
`.eq()` call and, at `execute()` time, filters the queued rows by every
applied predicate.
"""
from unittest.mock import MagicMock

from app.services.recruiter import (
    RankFilters,
    candidate_tenant,
    get_candidate_detail,
    rank_candidates,
)
from app.services.recruiter_analytics import (
    hiring_funnel,
    integrity_event_volume,
    scores_by_field,
)


# Sentinels for the two tenants.
A = "company-a"
B = "company-b"


class _FilterAwareChain:
    """Fake supabase query chain that honours `.eq()` predicates.

    Each `.eq(col, val)` is recorded; at `execute()` time, the queued rows
    are filtered by all recorded predicates. Other chain methods
    (`.in_`, `.gte`, `.lte`, `.or_`, `.order`, `.select`) are no-ops so
    the call graph type-checks but tenancy is what the tests assert on.
    """

    def __init__(self, rows):
        self._rows = rows
        self._eqs = []
        self._ins = []

    def select(self, *_a, **_kw): return self
    def order(self, *_a, **_kw): return self
    def gte(self, *_a, **_kw): return self
    def lte(self, *_a, **_kw): return self
    def or_(self, *_a, **_kw): return self

    def eq(self, column, value):
        self._eqs.append((column, value))
        return self

    def in_(self, column, values):
        self._ins.append((column, list(values)))
        return self

    def execute(self):
        rows = self._rows
        for col, val in self._eqs:
            rows = [r for r in rows if r.get(col) == val]
        for col, allowed in self._ins:
            rows = [r for r in rows if r.get(col) in allowed]
        resp = MagicMock()
        resp.data = list(rows)
        return resp


def _two_tenant_supabase():
    """Two candidates, two interviews, two decisions, two integrity rows —
    one in each tenant. Score data wired in evaluations so
    `score_interviews_bulk` produces non-zero per-interview scores."""
    candidates = [
        {"id": "c-a", "name": "Alice", "email": "a@x", "field_specialization": "ml",
         "created_at": "2026-01-01T00:00:00Z", "user_id": "u-a", "company_id": A,
         "resume_text": "ml"},
        {"id": "c-b", "name": "Bob", "email": "b@x", "field_specialization": "ml",
         "created_at": "2026-01-01T00:00:00Z", "user_id": "u-b", "company_id": B,
         "resume_text": "ml"},
    ]
    interviews = [
        {"id": "iv-a", "candidate_id": "c-a", "status": "completed",
         "created_at": "2026-01-02T00:00:00Z", "completed_at": "2026-01-02T01:00:00Z",
         "company_id": A},
        {"id": "iv-b", "candidate_id": "c-b", "status": "completed",
         "created_at": "2026-01-02T00:00:00Z", "completed_at": "2026-01-02T01:00:00Z",
         "company_id": B},
    ]
    # One evaluation row per interview so the bulk scorer has data to work
    # with; the actual score doesn't matter for tenant-scoping assertions.
    evaluations = [
        {"interview_id": "iv-a", "phase": 2, "depth_score": 8, "accuracy_score": 8,
         "details": {}, "company_id": A},
        {"interview_id": "iv-b", "phase": 2, "depth_score": 8, "accuracy_score": 8,
         "details": {}, "company_id": B},
    ]
    decisions = [
        {"id": "d-a", "candidate_id": "c-a", "recruiter_id": "rec",
         "decision": "shortlisted", "bookmarked": False, "notes": "",
         "decided_at": None, "updated_at": "2026-01-03T00:00:00Z",
         "company_id": A},
        {"id": "d-b", "candidate_id": "c-b", "recruiter_id": "rec",
         "decision": "shortlisted", "bookmarked": False, "notes": "",
         "decided_at": None, "updated_at": "2026-01-03T00:00:00Z",
         "company_id": B},
    ]
    integrity = [
        {"interview_id": "iv-a", "event_type": "tab_blur", "company_id": A},
        {"interview_id": "iv-b", "event_type": "tab_blur", "company_id": B},
    ]
    table_rows = {
        "candidates": candidates,
        "interviews": interviews,
        "evaluations": evaluations,
        "interview_integrity_events": integrity,
        "recruiter_decisions": decisions,
        "profiles": [],
    }
    supabase = MagicMock()
    supabase.table.side_effect = lambda name: _FilterAwareChain(table_rows[name])
    return supabase


# ---------------------------------------------------------------------------
# rank_candidates
# ---------------------------------------------------------------------------

class TestRankCandidatesTenantScoping:
    def test_scoped_caller_sees_only_their_tenant(self):
        result = rank_candidates(
            _two_tenant_supabase(), "rec", RankFilters(), company_id=A
        )
        assert {item["candidate_id"] for item in result["items"]} == {"c-a"}
        assert result["total_count"] == 1

    def test_other_tenant_caller_sees_only_their_tenant(self):
        result = rank_candidates(
            _two_tenant_supabase(), "rec", RankFilters(), company_id=B
        )
        assert {item["candidate_id"] for item in result["items"]} == {"c-b"}

    def test_unscoped_caller_sees_both(self):
        result = rank_candidates(
            _two_tenant_supabase(), "rec", RankFilters(), company_id=None
        )
        assert {item["candidate_id"] for item in result["items"]} == {"c-a", "c-b"}
        assert result["total_count"] == 2

    def test_unknown_tenant_returns_empty(self):
        result = rank_candidates(
            _two_tenant_supabase(), "rec", RankFilters(), company_id="ghost"
        )
        assert result["items"] == []
        assert result["total_count"] == 0


# ---------------------------------------------------------------------------
# get_candidate_detail
# ---------------------------------------------------------------------------

class TestGetCandidateDetailTenantScoping:
    def test_scoped_caller_can_open_own_candidate(self):
        detail = get_candidate_detail(
            _two_tenant_supabase(), "c-a", viewer_id="rec",
            viewer_role="recruiter", company_id=A,
        )
        assert detail is not None
        assert detail["candidate"]["id"] == "c-a"

    def test_scoped_caller_cannot_open_other_tenants_candidate(self):
        """Cross-tenant candidate id is indistinguishable from 'missing'
        by design — no existence leak across tenant boundaries."""
        detail = get_candidate_detail(
            _two_tenant_supabase(), "c-b", viewer_id="rec",
            viewer_role="recruiter", company_id=A,
        )
        assert detail is None

    def test_unscoped_caller_can_open_any_candidate(self):
        detail = get_candidate_detail(
            _two_tenant_supabase(), "c-b", viewer_id="admin",
            viewer_role="admin", company_id=None,
        )
        assert detail is not None
        assert detail["candidate"]["id"] == "c-b"


# ---------------------------------------------------------------------------
# candidate_tenant — used by the write endpoints
# ---------------------------------------------------------------------------

class TestCandidateTenant:
    def test_scoped_lookup_returns_own_company_id(self):
        exists, cid = candidate_tenant(_two_tenant_supabase(), "c-a", scope=A)
        assert exists is True
        assert cid == A

    def test_cross_tenant_lookup_reports_missing(self):
        """A recruiter of A asking about a candidate of B sees `(False, None)`
        — same shape as 'candidate doesn't exist anywhere'."""
        exists, cid = candidate_tenant(_two_tenant_supabase(), "c-b", scope=A)
        assert exists is False
        assert cid is None

    def test_unscoped_lookup_returns_candidates_own_tenant(self):
        exists, cid = candidate_tenant(_two_tenant_supabase(), "c-b", scope=None)
        assert exists is True
        assert cid == B

    def test_truly_missing_returns_false_none(self):
        exists, cid = candidate_tenant(_two_tenant_supabase(), "ghost", scope=None)
        assert exists is False
        assert cid is None


# ---------------------------------------------------------------------------
# Analytics — hiring_funnel, scores_by_field, integrity_event_volume
# ---------------------------------------------------------------------------

class TestHiringFunnelTenantScoping:
    def test_scoped_funnel_counts_only_own_tenant(self):
        result = hiring_funnel(_two_tenant_supabase(), company_id=A)
        counts = {s["stage"]: s["count"] for s in result["stages"]}
        # Only one candidate / interview / shortlist in tenant A.
        assert counts["signed_up"] == 1
        assert counts["interview_started"] == 1
        assert counts["interview_completed"] == 1
        assert counts["shortlisted"] == 1

    def test_unscoped_funnel_counts_both(self):
        result = hiring_funnel(_two_tenant_supabase(), company_id=None)
        counts = {s["stage"]: s["count"] for s in result["stages"]}
        assert counts["signed_up"] == 2
        assert counts["interview_started"] == 2
        assert counts["interview_completed"] == 2
        assert counts["shortlisted"] == 2


class TestScoresByFieldTenantScoping:
    def test_scoped_view_lists_only_own_tenants_fields(self):
        result = scores_by_field(_two_tenant_supabase(), company_id=A)
        # Both candidates are in field 'ml'; tenant A has exactly one of them.
        candidate_counts = {item["field"]: item["candidate_count"]
                            for item in result["items"]}
        assert candidate_counts == {"ml": 1}

    def test_unscoped_view_lists_both_tenants_data(self):
        result = scores_by_field(_two_tenant_supabase(), company_id=None)
        candidate_counts = {item["field"]: item["candidate_count"]
                            for item in result["items"]}
        assert candidate_counts == {"ml": 2}


class TestIntegrityVolumeTenantScoping:
    def test_scoped_view_only_counts_own_events(self):
        result = integrity_event_volume(_two_tenant_supabase(), company_id=A)
        assert result["total"] == 1

    def test_unscoped_view_counts_all(self):
        result = integrity_event_volume(_two_tenant_supabase(), company_id=None)
        assert result["total"] == 2
