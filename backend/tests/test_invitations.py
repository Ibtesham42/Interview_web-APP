"""Tests for the candidate-invitation ledger (migration 011).

Covers:
- `services/invitations.py` — upsert (fresh / duplicate / declined
  revival / missing table), invited_company_ids status filtering,
  allowed_company_ids union, mark_accepted.
- `routers/invitations.py` — list joins company info, accept/decline
  ownership (404 for someone else's invitation).
- `routers/candidates.resolve_target_company` — the stamp-resolution
  used by both the candidate and interview create paths.

Reuses the filter-aware stub pattern from test_apply.py.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.auth import TenantContext
from app.routers.candidates import resolve_target_company
from app.routers.invitations import (
    accept_invitation,
    decline_invitation,
    list_my_invitations,
)
from app.services.invitations import (
    allowed_company_ids,
    invited_company_ids,
    mark_accepted,
    normalize_email,
    upsert_invitation,
)


class _Chain:
    def __init__(self, table_name: str, store: Dict[str, List[Dict[str, Any]]]):
        self._table = table_name
        self._store = store
        self._eqs: List = []
        self._neqs: List = []
        self._in: Optional[tuple] = None
        self._mode: Optional[str] = None
        self._payload: Any = None

    def select(self, *_a, **_kw):
        self._mode = "select"
        return self

    def eq(self, col, val):
        self._eqs.append((col, val))
        return self

    def neq(self, col, val):
        self._neqs.append((col, val))
        return self

    def in_(self, col, vals):
        self._in = (col, list(vals))
        return self

    def order(self, *_a, **_kw):
        return self

    def update(self, payload):
        self._mode = "update"
        self._payload = payload
        return self

    def insert(self, payload):
        self._mode = "insert"
        self._payload = payload
        return self

    def _matches(self, row) -> bool:
        if any(row.get(c) != v for c, v in self._eqs):
            return False
        if any(row.get(c) == v for c, v in self._neqs):
            return False
        if self._in is not None and row.get(self._in[0]) not in self._in[1]:
            return False
        return True

    def execute(self):
        if self._table not in self._store:
            raise RuntimeError(f"relation \"{self._table}\" does not exist")
        rows = self._store[self._table]
        resp = MagicMock()
        if self._mode == "select":
            resp.data = [dict(r) for r in rows if self._matches(r)]
            return resp
        if self._mode == "update":
            updated = []
            for row in rows:
                if self._matches(row):
                    row.update(self._payload)
                    updated.append(dict(row))
            resp.data = updated
            return resp
        if self._mode == "insert":
            row = {"id": str(uuid.uuid4()), "status": "pending", **self._payload}
            rows.append(row)
            resp.data = [dict(row)]
            return resp
        raise NotImplementedError(f"unsupported mode {self._mode}")


def _supabase(store: Dict[str, List[Dict[str, Any]]]):
    supabase = MagicMock()
    supabase.table.side_effect = lambda name: _Chain(name, store)
    supabase._store = store
    return supabase


def _user(user_id="u-1", email="cand@example.com"):
    user = MagicMock()
    user.id = user_id
    user.email = email
    return user


def _run(coro):
    return asyncio.run(coro)


COMPANY_A = str(uuid.uuid4())
COMPANY_B = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# services/invitations.py
# ---------------------------------------------------------------------------

class TestNormalizeEmail:
    def test_lowercases_and_trims(self):
        assert normalize_email("  Cand@Example.COM ") == "cand@example.com"

    def test_none_is_empty(self):
        assert normalize_email(None) == ""


class TestUpsertInvitation:
    def test_fresh_insert(self):
        supabase = _supabase({"candidate_invitations": []})
        row = upsert_invitation(
            supabase, company_id=COMPANY_A, email="Cand@Example.com",
            candidate_name="Jane", invited_by="admin-1",
        )
        assert row is not None
        store = supabase._store["candidate_invitations"]
        assert len(store) == 1
        assert store[0]["email"] == "cand@example.com"  # normalised
        assert store[0]["status"] == "pending"

    def test_reinvite_is_noop(self):
        supabase = _supabase({"candidate_invitations": [{
            "id": "inv-1", "company_id": COMPANY_A,
            "email": "cand@example.com", "status": "accepted",
        }]})
        row = upsert_invitation(supabase, company_id=COMPANY_A, email="cand@example.com")
        assert row["id"] == "inv-1"
        assert len(supabase._store["candidate_invitations"]) == 1
        # An accepted invitation is never demoted by a re-invite.
        assert supabase._store["candidate_invitations"][0]["status"] == "accepted"

    def test_reinvite_revives_declined(self):
        supabase = _supabase({"candidate_invitations": [{
            "id": "inv-1", "company_id": COMPANY_A,
            "email": "cand@example.com", "status": "declined",
        }]})
        row = upsert_invitation(supabase, company_id=COMPANY_A, email="cand@example.com")
        assert row["status"] == "pending"
        assert supabase._store["candidate_invitations"][0]["status"] == "pending"

    def test_missing_table_returns_none_without_raising(self):
        """Migration 011 not applied yet — the invite email must still go
        out, so the ledger write degrades to a logged no-op."""
        supabase = _supabase({})  # no candidate_invitations key -> raises
        row = upsert_invitation(supabase, company_id=COMPANY_A, email="cand@example.com")
        assert row is None

    def test_blank_email_is_noop(self):
        supabase = _supabase({"candidate_invitations": []})
        assert upsert_invitation(supabase, company_id=COMPANY_A, email="  ") is None
        assert supabase._store["candidate_invitations"] == []


class TestInvitedCompanyIds:
    def _store(self):
        return {"candidate_invitations": [
            {"id": "i1", "company_id": COMPANY_A, "email": "cand@example.com", "status": "pending"},
            {"id": "i2", "company_id": COMPANY_B, "email": "cand@example.com", "status": "declined"},
        ]}

    def test_pending_counts_declined_does_not(self):
        ids = invited_company_ids(_supabase(self._store()), "cand@example.com")
        assert ids == {COMPANY_A}

    def test_missing_table_degrades_to_empty(self):
        assert invited_company_ids(_supabase({}), "cand@example.com") == set()

    def test_allowed_union_includes_profile_company(self):
        allowed = allowed_company_ids(
            _supabase(self._store()),
            email="cand@example.com",
            profile_company_id=COMPANY_B,
        )
        assert allowed == {COMPANY_A, COMPANY_B}


class TestMarkAccepted:
    def test_flips_pending_and_stamps_user(self):
        supabase = _supabase({"candidate_invitations": [{
            "id": "inv-1", "company_id": COMPANY_A,
            "email": "cand@example.com", "status": "pending",
        }]})
        mark_accepted(supabase, company_id=COMPANY_A, email="cand@example.com", user_id="u-1")
        row = supabase._store["candidate_invitations"][0]
        assert row["status"] == "accepted"
        assert row["accepted_user_id"] == "u-1"

    def test_missing_table_does_not_raise(self):
        mark_accepted(_supabase({}), company_id=COMPANY_A, email="cand@example.com", user_id="u-1")


# ---------------------------------------------------------------------------
# routers/invitations.py
# ---------------------------------------------------------------------------

class TestListMyInvitations:
    def test_joins_company_info_and_orders(self, monkeypatch):
        supabase = _supabase({
            "candidate_invitations": [
                {"id": str(uuid.uuid4()), "company_id": COMPANY_A,
                 "email": "cand@example.com", "status": "pending"},
                {"id": str(uuid.uuid4()), "company_id": COMPANY_B,
                 "email": "cand@example.com", "status": "accepted"},
                {"id": str(uuid.uuid4()), "company_id": COMPANY_A,
                 "email": "other@example.com", "status": "pending"},
            ],
            "companies": [
                {"id": COMPANY_A, "name": "Acme", "slug": "acme"},
                {"id": COMPANY_B, "name": "Globex", "slug": "globex"},
            ],
        })
        monkeypatch.setattr("app.routers.invitations.get_supabase", lambda: supabase)

        result = _run(list_my_invitations(user=_user()))
        assert len(result.items) == 2  # other@example.com's invite excluded
        names = {i.company_name for i in result.items}
        assert names == {"Acme", "Globex"}

    def test_missing_table_returns_empty_list(self, monkeypatch):
        supabase = _supabase({"companies": []})
        monkeypatch.setattr("app.routers.invitations.get_supabase", lambda: supabase)
        result = _run(list_my_invitations(user=_user()))
        assert result.items == []


class TestAcceptDecline:
    def _store(self):
        return {
            "candidate_invitations": [{
                "id": "inv-1", "company_id": COMPANY_A,
                "email": "cand@example.com", "status": "pending",
            }],
        }

    def test_accept_marks_accepted(self, monkeypatch):
        supabase = _supabase(self._store())
        monkeypatch.setattr("app.routers.invitations.get_supabase", lambda: supabase)
        result = _run(accept_invitation("inv-1", user=_user()))
        assert result["status"] == "accepted"
        assert supabase._store["candidate_invitations"][0]["status"] == "accepted"

    def test_decline_marks_declined(self, monkeypatch):
        supabase = _supabase(self._store())
        monkeypatch.setattr("app.routers.invitations.get_supabase", lambda: supabase)
        result = _run(decline_invitation("inv-1", user=_user()))
        assert result["status"] == "declined"
        assert supabase._store["candidate_invitations"][0]["status"] == "declined"

    def test_someone_elses_invitation_404(self, monkeypatch):
        supabase = _supabase(self._store())
        monkeypatch.setattr("app.routers.invitations.get_supabase", lambda: supabase)
        with pytest.raises(HTTPException) as exc:
            _run(accept_invitation("inv-1", user=_user(email="intruder@example.com")))
        assert exc.value.status_code == 404
        assert supabase._store["candidate_invitations"][0]["status"] == "pending"


# ---------------------------------------------------------------------------
# routers/candidates.resolve_target_company (stamp resolution)
# ---------------------------------------------------------------------------

def _ctx(*, user_id="u-1", role="user", company_id=None):
    return TenantContext(user_id=user_id, role=role, company_id=company_id)


class TestResolveTargetCompany:
    def test_default_is_profile_company(self):
        supabase = _supabase({"candidate_invitations": []})
        assert resolve_target_company(supabase, _ctx(company_id=COMPANY_A), _user(), None) == COMPANY_A

    def test_default_is_none_for_b2c(self):
        supabase = _supabase({"candidate_invitations": []})
        assert resolve_target_company(supabase, _ctx(), _user(), None) is None

    def test_explicit_own_company_allowed(self):
        supabase = _supabase({"candidate_invitations": []})
        out = resolve_target_company(
            supabase, _ctx(company_id=COMPANY_A), _user(), uuid.UUID(COMPANY_A)
        )
        assert out == COMPANY_A

    def test_explicit_invited_company_allowed(self):
        supabase = _supabase({"candidate_invitations": [{
            "id": "inv-1", "company_id": COMPANY_B,
            "email": "cand@example.com", "status": "pending",
        }]})
        out = resolve_target_company(
            supabase, _ctx(company_id=COMPANY_A), _user(), uuid.UUID(COMPANY_B)
        )
        assert out == COMPANY_B

    def test_uninvited_company_403(self):
        supabase = _supabase({"candidate_invitations": []})
        with pytest.raises(HTTPException) as exc:
            resolve_target_company(
                supabase, _ctx(company_id=COMPANY_A), _user(), uuid.UUID(COMPANY_B)
            )
        assert exc.value.status_code == 403

    def test_declined_invitation_does_not_grant_access(self):
        supabase = _supabase({"candidate_invitations": [{
            "id": "inv-1", "company_id": COMPANY_B,
            "email": "cand@example.com", "status": "declined",
        }]})
        with pytest.raises(HTTPException) as exc:
            resolve_target_company(supabase, _ctx(), _user(), uuid.UUID(COMPANY_B))
        assert exc.value.status_code == 403

    def test_platform_admin_may_stamp_any_company(self):
        supabase = _supabase({"candidate_invitations": []})
        out = resolve_target_company(
            supabase, _ctx(role="admin"), _user(), uuid.UUID(COMPANY_B)
        )
        assert out == COMPANY_B
