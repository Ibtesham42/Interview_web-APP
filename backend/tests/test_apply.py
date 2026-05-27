"""Tests for the public apply landing + tenant-claim endpoints (PR 4).

Covers:
- `apply_landing(slug)` — happy path (returns company info), unknown
  slug (404).
- `claim_company` — fresh claim (NULL → tenant), idempotent re-claim,
  cross-tenant rejection (403), unknown slug (404).

The stub supabase honours `select.eq()` filters and `update.eq()`
mutations, mirroring the pattern from `test_companies.py`. A
`MagicMock` user object stands in for the Supabase `User` (only `.id`
is read by the endpoint).
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.models.schemas import ClaimCompanyRequest
from app.routers.apply import apply_landing, claim_company


class _Chain:
    def __init__(self, table_name: str, store: Dict[str, List[Dict[str, Any]]]):
        self._table = table_name
        self._store = store
        self._eqs: List = []
        self._mode: Optional[str] = None
        self._payload: Any = None

    def select(self, *_a, **_kw):
        self._mode = "select"
        return self

    def eq(self, col, val):
        self._eqs.append((col, val))
        return self

    def update(self, payload):
        self._mode = "update"
        self._payload = payload
        return self

    def execute(self):
        rows = self._store.get(self._table, [])
        if self._mode == "select":
            filtered = rows
            for col, val in self._eqs:
                filtered = [r for r in filtered if r.get(col) == val]
            resp = MagicMock()
            resp.data = list(filtered)
            return resp
        if self._mode == "update":
            updated = []
            for row in rows:
                if all(row.get(c) == v for c, v in self._eqs):
                    row.update(self._payload)
                    updated.append(row)
            resp = MagicMock()
            resp.data = list(updated)
            return resp
        raise NotImplementedError(f"unsupported mode {self._mode}")


def _supabase(*, companies=None, profiles=None):
    store: Dict[str, List[Dict[str, Any]]] = {
        "companies": list(companies or []),
        "profiles": list(profiles or []),
    }
    supabase = MagicMock()
    supabase.table.side_effect = lambda name: _Chain(name, store)
    supabase._store = store
    return supabase


def _user(user_id="u-1"):
    user = MagicMock()
    user.id = user_id
    return user


def _run(coro):
    return asyncio.run(coro)


COMPANY_A_ID = str(uuid.uuid4())
COMPANY_B_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# GET /api/apply/{slug}
# ---------------------------------------------------------------------------

class TestApplyLanding:
    def test_known_slug_returns_company_info(self, monkeypatch):
        supabase = _supabase(companies=[
            {"id": COMPANY_A_ID, "slug": "acme", "name": "Acme Inc."},
        ])
        monkeypatch.setattr("app.routers.apply.get_supabase", lambda: supabase)

        result = _run(apply_landing("acme"))
        assert str(result.company_id) == COMPANY_A_ID
        assert result.company_name == "Acme Inc."
        assert result.slug == "acme"
        assert result.signup_open is True

    def test_unknown_slug_404(self, monkeypatch):
        supabase = _supabase(companies=[])
        monkeypatch.setattr("app.routers.apply.get_supabase", lambda: supabase)

        with pytest.raises(HTTPException) as exc:
            _run(apply_landing("ghost"))
        assert exc.value.status_code == 404

    def test_slug_is_lowercased(self, monkeypatch):
        """The DB stores lowercase slugs (regex on create). The endpoint
        defensively lowercases the URL param so /apply/ACME still
        resolves to /apply/acme."""
        supabase = _supabase(companies=[
            {"id": COMPANY_A_ID, "slug": "acme", "name": "Acme Inc."},
        ])
        monkeypatch.setattr("app.routers.apply.get_supabase", lambda: supabase)

        result = _run(apply_landing("ACME"))
        assert result.slug == "acme"


# ---------------------------------------------------------------------------
# POST /api/auth/claim-company
# ---------------------------------------------------------------------------

class TestClaimCompany:
    def _supabase_for_claim(self, *, profile_company_id=None):
        return _supabase(
            companies=[{"id": COMPANY_A_ID, "slug": "acme", "name": "Acme Inc."}],
            profiles=[{"id": "u-1", "role": "user", "company_id": profile_company_id}],
        )

    def test_fresh_claim_stamps_company(self, monkeypatch):
        supabase = self._supabase_for_claim(profile_company_id=None)
        monkeypatch.setattr("app.routers.apply.get_supabase", lambda: supabase)

        result = _run(claim_company(ClaimCompanyRequest(slug="acme"), user=_user()))
        assert result["claimed"] is True
        assert result["company_id"] == COMPANY_A_ID
        # Profile actually updated in the store.
        assert supabase._store["profiles"][0]["company_id"] == COMPANY_A_ID

    def test_idempotent_reclaim_is_noop(self, monkeypatch):
        """Calling twice with the same slug is safe — the second call
        sees company_id already matches and returns claimed=False."""
        supabase = self._supabase_for_claim(profile_company_id=COMPANY_A_ID)
        monkeypatch.setattr("app.routers.apply.get_supabase", lambda: supabase)

        result = _run(claim_company(ClaimCompanyRequest(slug="acme"), user=_user()))
        assert result["claimed"] is False
        assert result["company_id"] == COMPANY_A_ID
        assert result.get("reason") == "already_member"

    def test_cross_tenant_claim_rejected_403(self, monkeypatch):
        """User already in Company B cannot claim Company A — that
        would silently move them between tenants."""
        supabase = self._supabase_for_claim(profile_company_id=COMPANY_B_ID)
        monkeypatch.setattr("app.routers.apply.get_supabase", lambda: supabase)

        with pytest.raises(HTTPException) as exc:
            _run(claim_company(ClaimCompanyRequest(slug="acme"), user=_user()))
        assert exc.value.status_code == 403
        # Critically — the existing company_id stays put.
        assert supabase._store["profiles"][0]["company_id"] == COMPANY_B_ID

    def test_unknown_slug_404(self, monkeypatch):
        supabase = _supabase(
            companies=[],
            profiles=[{"id": "u-1", "role": "user", "company_id": None}],
        )
        monkeypatch.setattr("app.routers.apply.get_supabase", lambda: supabase)

        with pytest.raises(HTTPException) as exc:
            _run(claim_company(ClaimCompanyRequest(slug="ghost"), user=_user()))
        assert exc.value.status_code == 404

    def test_missing_profile_treated_as_fresh_claim(self, monkeypatch):
        """A user with NULL company_id whose profile row is missing
        (edge case — auto-create trigger hasn't fired yet) is treated
        the same as a NULL-company profile: stamp succeeds."""
        supabase = _supabase(
            companies=[{"id": COMPANY_A_ID, "slug": "acme", "name": "Acme Inc."}],
            profiles=[],
        )
        monkeypatch.setattr("app.routers.apply.get_supabase", lambda: supabase)

        result = _run(claim_company(ClaimCompanyRequest(slug="acme"), user=_user()))
        assert result["claimed"] is True
        assert result["company_id"] == COMPANY_A_ID
