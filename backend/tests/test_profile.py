"""Tests for `GET /api/auth/me`.

The handler is small but load-bearing: every protected page in the
frontend reads its role/tenant context from this endpoint via
`profileApi.me()`. The capability gates (ADR 0006) feed off the
returned `company_id`, so a missing field here silently fails every
tenant-requiring capability for legit tenants.

Regression target: the 2026-05-29 fix that re-added `company_id` to
the payload after it was dropped in the original whitelist. See
CHANGE.md for the runtime trace.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from app.routers.profile import get_me


# ---------------------------------------------------------------------------
# Stub supabase — narrow shape: only `profiles.select("*").eq("id", _).execute`
# and `profiles.insert(_).execute` are exercised.
# ---------------------------------------------------------------------------

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

    def insert(self, payload):
        self._mode = "insert"
        self._payload = payload
        return self

    def execute(self):
        rows = self._store.get(self._table, [])
        if self._mode == "select":
            filtered = rows
            for col, val in self._eqs:
                filtered = [r for r in filtered if r.get(col) == val]
            result = MagicMock()
            result.data = filtered
            return result
        if self._mode == "insert":
            self._store.setdefault(self._table, []).append(self._payload)
            result = MagicMock()
            result.data = [self._payload]
            return result
        raise AssertionError(f"Unhandled mode in test stub: {self._mode}")


def _supabase(profiles: Optional[List[Dict]] = None):
    store = {"profiles": list(profiles or [])}
    supabase = MagicMock()
    supabase.table.side_effect = lambda name: _Chain(name, store)
    return supabase


def _user(user_id="u-1", email="caller@example.com"):
    user = MagicMock()
    user.id = user_id
    user.email = email
    user.user_metadata = {"full_name": "Caller Name"}
    return user


def _run(coro):
    return asyncio.run(coro)


class TestGetMe:
    def test_returns_company_id_for_tenanted_profile(self, monkeypatch):
        """Regression: `company_id` must round-trip through the response.

        Before 2026-05-29 the payload whitelist omitted it; every
        tenant-requiring capability gate on the frontend then evaluated
        to False because `profile.company_id` was undefined. A
        `company_admin` lost access to their own Settings + Invite
        surfaces despite the DB row being correct.
        """
        supabase = _supabase(profiles=[{
            "id": "u-1",
            "email": "admin@acme.com",
            "full_name": "Acme Admin",
            "role": "company_admin",
            "company_id": "co-acme",
            "created_at": "2026-05-29T00:00:00Z",
        }])
        monkeypatch.setattr("app.routers.profile.get_supabase", lambda: supabase)

        result = _run(get_me(user=_user()))
        assert result["company_id"] == "co-acme"
        assert result["role"] == "company_admin"

    def test_returns_null_company_id_for_platform_admin(self, monkeypatch):
        """Platform admin (`role='admin'`) is tenant-agnostic by ADR 0005
        grill C3 — the response carries the NULL explicitly so the
        frontend can distinguish 'not loaded' from 'no tenant'."""
        supabase = _supabase(profiles=[{
            "id": "u-1",
            "email": "ops@platform.com",
            "full_name": "Ops",
            "role": "admin",
            "company_id": None,
            "created_at": "2026-05-29T00:00:00Z",
        }])
        monkeypatch.setattr("app.routers.profile.get_supabase", lambda: supabase)

        result = _run(get_me(user=_user()))
        assert result["company_id"] is None
        assert result["role"] == "admin"

    def test_returns_null_company_id_for_b2c_user(self, monkeypatch):
        supabase = _supabase(profiles=[{
            "id": "u-1",
            "email": "candidate@example.com",
            "full_name": "Candidate",
            "role": "user",
            "company_id": None,
            "created_at": "2026-05-29T00:00:00Z",
        }])
        monkeypatch.setattr("app.routers.profile.get_supabase", lambda: supabase)

        result = _run(get_me(user=_user()))
        assert result["company_id"] is None
        assert result["role"] == "user"

    def test_creates_profile_when_missing(self, monkeypatch):
        """The auto-create branch should still return a complete payload
        shape — `company_id` defaults to None for the fresh row."""
        supabase = _supabase(profiles=[])
        monkeypatch.setattr("app.routers.profile.get_supabase", lambda: supabase)

        result = _run(get_me(user=_user()))
        assert "company_id" in result
        assert result["company_id"] is None
        assert result["role"] == "user"

    def test_response_shape_matches_frontend_profile_interface(self, monkeypatch):
        """Lock down the exact key set returned. Drift on either side
        (frontend `Profile` interface or this handler) should surface
        as a test failure rather than a silent UI breakage."""
        supabase = _supabase(profiles=[{
            "id": "u-1",
            "email": "u@example.com",
            "full_name": "U",
            "role": "company_admin",
            "company_id": "co-1",
            "created_at": "2026-05-29T00:00:00Z",
        }])
        monkeypatch.setattr("app.routers.profile.get_supabase", lambda: supabase)

        result = _run(get_me(user=_user()))
        assert set(result.keys()) == {
            "id", "email", "full_name", "username", "role", "company_id",
            "created_at",
        }

    def test_returns_username_for_existing_profile(self, monkeypatch):
        """`username` (migration 008 / ADR 0010) round-trips like
        company_id did — a display handle that must not be dropped from
        the payload even though the SELECT returns it."""
        supabase = _supabase(profiles=[{
            "id": "u-1", "email": "admin@acme.com", "full_name": "Acme Admin",
            "username": "acme-admin", "role": "company_admin",
            "company_id": "co-acme", "created_at": "2026-05-30T00:00:00Z",
        }])
        monkeypatch.setattr("app.routers.profile.get_supabase", lambda: supabase)

        result = _run(get_me(user=_user()))
        assert result["username"] == "acme-admin"

    def test_autocreate_copies_username_from_metadata(self, monkeypatch):
        """The auto-create branch mirrors the handle_new_user trigger:
        username is read from user_metadata so a backend-created fallback
        row carries it too."""
        supabase = _supabase(profiles=[])
        monkeypatch.setattr("app.routers.profile.get_supabase", lambda: supabase)

        user = _user()
        user.user_metadata = {"full_name": "Dana", "username": "dana"}
        result = _run(get_me(user=user))
        assert result["username"] == "dana"
