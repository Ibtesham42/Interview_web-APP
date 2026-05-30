"""Tests for `upsert_recruiter_decision` — the shared write path behind
the three workflow endpoints (decision / bookmark / notes).

The contract being pinned:
- A single (candidate_id, recruiter_id) row holds all three workflow
  fields. Any one field can be updated without disturbing the others
  (a Bookmark toggle must never clear Notes).
- An invalid decision value raises ValueError (router maps to 400).
- A terminal decision (shortlisted / rejected) stamps `decided_at`;
  reverting to 'undecided' clears it so funnel analytics in PR 6 do
  not double-count.
- The first write for a (candidate, recruiter) pair INSERTs with
  defaults for the unspecified fields; subsequent writes UPDATE.

These are the invariants that several future PRs lean on, so they get
their own test file.
"""
from unittest.mock import MagicMock

import pytest

from app.services.recruiter import (
    TERMINAL_DECISIONS,
    WRITABLE_DECISIONS,
    candidate_exists,
    upsert_recruiter_decision,
)


# ---------------------------------------------------------------------------
# A writable fake — tracks an internal recruiter_decisions store and
# routes .select/.update/.insert through it. Different from the read-only
# fake in test_recruiter_service.py because this one needs to thread the
# eq() filters into a real lookup so we can verify partial-update semantics.
# ---------------------------------------------------------------------------

class _FakeRecruiterDecisionsTable:
    def __init__(self, initial_rows=None):
        # The store is the source of truth across the chain.
        self.rows = list(initial_rows or [])
        self._mode = None          # 'select' | 'update' | 'insert' | 'delete'
        self._payload = None       # for update/insert
        self._filters = {}         # eq() filters accumulated for select/update

    # query-builder chain
    def select(self, *_a, **_kw):
        self._mode = "select"
        self._filters = {}
        return self

    def insert(self, payload):
        self._mode = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._mode = "update"
        self._payload = payload
        self._filters = {}
        return self

    def eq(self, column, value):
        self._filters[column] = value
        return self

    def execute(self):
        if self._mode == "select":
            matching = [r for r in self.rows if all(r.get(k) == v
                        for k, v in self._filters.items())]
            return MagicMock(data=matching)
        if self._mode == "insert":
            payload = dict(self._payload)
            payload.setdefault("id", f"dec-{len(self.rows) + 1}")
            self.rows.append(payload)
            return MagicMock(data=[payload])
        if self._mode == "update":
            for row in self.rows:
                if all(row.get(k) == v for k, v in self._filters.items()):
                    row.update(self._payload)
                    return MagicMock(data=[dict(row)])
            return MagicMock(data=[])
        raise AssertionError(f"unsupported mode {self._mode}")


def _supabase_with_store(initial_rows=None):
    """Build a fake supabase whose recruiter_decisions table is writable
    and persists across calls within the test."""
    store = _FakeRecruiterDecisionsTable(initial_rows)
    supabase = MagicMock()

    def route(name):
        if name == "recruiter_decisions":
            return store
        raise AssertionError(f"unexpected table {name}")

    supabase.table.side_effect = route
    return supabase, store


# ---------------------------------------------------------------------------
# Insert path (first write for the (candidate, recruiter) pair)
# ---------------------------------------------------------------------------

class TestUpsertInsertPath:
    def test_first_decision_write_inserts_a_new_row(self):
        supabase, store = _supabase_with_store()
        row = upsert_recruiter_decision(supabase, "cand-1", "rec-1",
                                        decision="shortlisted")
        assert row["decision"] == "shortlisted"
        assert row["bookmarked"] is False
        assert row["notes"] == ""
        assert len(store.rows) == 1

    def test_terminal_decision_on_insert_stamps_decided_at(self):
        supabase, _ = _supabase_with_store()
        row = upsert_recruiter_decision(supabase, "cand-1", "rec-1",
                                        decision="rejected")
        assert row["decided_at"] is not None

    def test_undecided_insert_does_not_stamp_decided_at(self):
        """The default 'undecided' value should not have decided_at —
        the funnel analytics in PR 6 use decided_at as 'has the
        recruiter actually decided on this candidate?'"""
        supabase, _ = _supabase_with_store()
        row = upsert_recruiter_decision(supabase, "cand-1", "rec-1",
                                        decision="undecided")
        assert row.get("decided_at") is None

    def test_bookmark_only_insert_defaults_decision_to_undecided(self):
        supabase, _ = _supabase_with_store()
        row = upsert_recruiter_decision(supabase, "cand-1", "rec-1",
                                        bookmarked=True)
        assert row["bookmarked"] is True
        assert row["decision"] == "undecided"
        assert row["notes"] == ""

    def test_notes_only_insert_defaults_other_fields(self):
        supabase, _ = _supabase_with_store()
        row = upsert_recruiter_decision(supabase, "cand-1", "rec-1",
                                        notes="strong systems thinker")
        assert row["notes"] == "strong systems thinker"
        assert row["bookmarked"] is False
        assert row["decision"] == "undecided"


# ---------------------------------------------------------------------------
# Update path (existing row for the pair)
# ---------------------------------------------------------------------------

class TestUpsertUpdatePath:
    def _seed(self):
        return _supabase_with_store([
            {
                "id": "dec-1",
                "candidate_id": "cand-1",
                "recruiter_id": "rec-1",
                "decision": "undecided",
                "bookmarked": False,
                "notes": "starting note",
                "decided_at": None,
                "updated_at": "2026-05-25T00:00:00Z",
            },
        ])

    def test_setting_decision_does_not_clear_notes(self):
        """The defining invariant — three write endpoints sharing one
        row must NOT accidentally blow each other away."""
        supabase, store = self._seed()
        upsert_recruiter_decision(supabase, "cand-1", "rec-1",
                                  decision="shortlisted")
        row = store.rows[0]
        assert row["decision"] == "shortlisted"
        assert row["notes"] == "starting note"
        assert row["bookmarked"] is False

    def test_setting_bookmark_does_not_clear_notes(self):
        supabase, store = self._seed()
        upsert_recruiter_decision(supabase, "cand-1", "rec-1", bookmarked=True)
        row = store.rows[0]
        assert row["bookmarked"] is True
        assert row["notes"] == "starting note"
        assert row["decision"] == "undecided"

    def test_setting_notes_does_not_clear_bookmark_or_decision(self):
        supabase, store = _supabase_with_store([{
            "id": "dec-1",
            "candidate_id": "cand-1",
            "recruiter_id": "rec-1",
            "decision": "shortlisted",
            "bookmarked": True,
            "notes": "old",
            "decided_at": "2026-05-25T00:00:00Z",
            "updated_at": "2026-05-25T00:00:00Z",
        }])
        upsert_recruiter_decision(supabase, "cand-1", "rec-1",
                                  notes="updated commentary")
        row = store.rows[0]
        assert row["notes"] == "updated commentary"
        assert row["decision"] == "shortlisted"
        assert row["bookmarked"] is True
        assert row["decided_at"] == "2026-05-25T00:00:00Z"

    def test_reverting_to_undecided_clears_decided_at(self):
        """Funnel analytics use `decided_at IS NOT NULL` as the signal —
        un-shortlisting must clear the stamp so we don't double-count."""
        supabase, store = _supabase_with_store([{
            "id": "dec-1",
            "candidate_id": "cand-1",
            "recruiter_id": "rec-1",
            "decision": "shortlisted",
            "bookmarked": False,
            "notes": "",
            "decided_at": "2026-05-25T00:00:00Z",
            "updated_at": "2026-05-25T00:00:00Z",
        }])
        upsert_recruiter_decision(supabase, "cand-1", "rec-1",
                                  decision="undecided")
        assert store.rows[0]["decided_at"] is None
        assert store.rows[0]["decision"] == "undecided"

    def test_switching_terminal_decisions_re_stamps_decided_at(self):
        """Recruiter changes their mind from Shortlisted to Rejected:
        decided_at should re-stamp (it's "when did you last decide")."""
        supabase, store = _supabase_with_store([{
            "id": "dec-1",
            "candidate_id": "cand-1",
            "recruiter_id": "rec-1",
            "decision": "shortlisted",
            "bookmarked": False,
            "notes": "",
            "decided_at": "2026-05-25T00:00:00Z",
            "updated_at": "2026-05-25T00:00:00Z",
        }])
        upsert_recruiter_decision(supabase, "cand-1", "rec-1",
                                  decision="rejected")
        assert store.rows[0]["decision"] == "rejected"
        assert store.rows[0]["decided_at"] != "2026-05-25T00:00:00Z"
        assert store.rows[0]["decided_at"] is not None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestUpsertValidation:
    def test_invalid_decision_raises_value_error(self):
        supabase, _ = _supabase_with_store()
        with pytest.raises(ValueError):
            upsert_recruiter_decision(supabase, "cand-1", "rec-1",
                                      decision="maybe")

    def test_terminal_decisions_constant_lists_both_terminals(self):
        """If this ever drifts, decided_at semantics drift with it."""
        assert TERMINAL_DECISIONS == {"shortlisted", "rejected"}


# ---------------------------------------------------------------------------
# 'hold' decision (migration 009 — candidate status management)
# ---------------------------------------------------------------------------

class TestHoldDecision:
    def test_hold_is_writable(self):
        supabase, store = _supabase_with_store()
        row = upsert_recruiter_decision(supabase, "cand-1", "rec-1", decision="hold")
        assert row["decision"] == "hold"
        assert len(store.rows) == 1

    def test_hold_is_non_terminal_no_decided_at(self):
        """'On Hold' is a parked, reversible state — it must NOT stamp
        decided_at, so funnel analytics don't count it as a terminal
        decision."""
        assert "hold" in WRITABLE_DECISIONS
        assert "hold" not in TERMINAL_DECISIONS
        supabase, _ = _supabase_with_store()
        row = upsert_recruiter_decision(supabase, "cand-1", "rec-1", decision="hold")
        assert row.get("decided_at") is None

    def test_shortlist_then_hold_clears_decided_at(self):
        supabase, store = _supabase_with_store([{
            "id": "dec-1",
            "candidate_id": "cand-1",
            "recruiter_id": "rec-1",
            "decision": "shortlisted",
            "bookmarked": False,
            "notes": "",
            "decided_at": "2026-05-25T00:00:00Z",
            "updated_at": "2026-05-25T00:00:00Z",
        }])
        upsert_recruiter_decision(supabase, "cand-1", "rec-1", decision="hold")
        assert store.rows[0]["decision"] == "hold"
        assert store.rows[0]["decided_at"] is None


# ---------------------------------------------------------------------------
# candidate_exists helper
# ---------------------------------------------------------------------------

class TestCandidateExists:
    def test_returns_true_when_row_present(self):
        supabase = MagicMock()
        chain = supabase.table.return_value
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value.data = [{"id": "cand-1"}]
        assert candidate_exists(supabase, "cand-1") is True

    def test_returns_false_when_row_absent(self):
        supabase = MagicMock()
        chain = supabase.table.return_value
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value.data = []
        assert candidate_exists(supabase, "cand-1") is False
