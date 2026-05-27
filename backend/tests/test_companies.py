"""Tests for the company endpoints (multi-tenant PRs 3 + 5).

Covers:
- `create_company` (PR 3): preconditions, slug validation, atomicity.
- `get_my_company` (PR 5): caller's company; 404 for platform admins
  (NULL company_id) and B2C users; 404 if profile points at a
  non-existent company.

The route handlers are async, so each test uses `asyncio.run`. The
stub supabase is a hand-rolled mock keyed by table name; supports
select.eq, insert, update, delete operations.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.auth import TenantContext
from app.models.schemas import CompanyCreate
from app.routers.companies import create_company, get_my_company


# ---------------------------------------------------------------------------
# Stub supabase — minimal builder that supports the four operations the
# endpoint uses: companies.select.eq().execute, companies.insert().execute,
# profiles.update().eq().execute, companies.delete().eq().execute.
# ---------------------------------------------------------------------------

class _Chain:
    """Records each call so the test can assert what the handler tried to do.

    Filters are honoured for `select`, so the uniqueness pre-check works
    with seeded `companies` rows. `insert`/`update`/`delete` mutate the
    backing list and return the affected rows on `.execute()`.
    """

    def __init__(self, table_name: str, store: Dict[str, List[Dict[str, Any]]]):
        self._table = table_name
        self._store = store
        self._eqs: List = []
        self._mode: Optional[str] = None
        self._payload: Any = None

    # SELECT path
    def select(self, *_a, **_kw):
        self._mode = "select"
        return self

    def eq(self, col, val):
        self._eqs.append((col, val))
        return self

    # INSERT path
    def insert(self, payload):
        self._mode = "insert"
        self._payload = payload
        return self

    # UPDATE path
    def update(self, payload):
        self._mode = "update"
        self._payload = payload
        return self

    # DELETE path
    def delete(self):
        self._mode = "delete"
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

        if self._mode == "insert":
            payload = self._payload
            if isinstance(payload, dict):
                inserted = {**payload}
                # Match Postgres defaults so the response shape works.
                # CompanyResponse.id is typed as UUID — generate a real one.
                inserted.setdefault("id", str(uuid.uuid4()))
                inserted.setdefault("created_at", "2026-05-27T00:00:00Z")
                rows.append(inserted)
                resp = MagicMock()
                resp.data = [inserted]
                return resp
            raise NotImplementedError("test stub only supports dict insert payload")

        if self._mode == "update":
            updated = []
            for row in rows:
                if all(row.get(c) == v for c, v in self._eqs):
                    row.update(self._payload)
                    updated.append(row)
            resp = MagicMock()
            resp.data = list(updated)
            return resp

        if self._mode == "delete":
            kept = [r for r in rows if not all(r.get(c) == v for c, v in self._eqs)]
            self._store[self._table] = kept
            resp = MagicMock()
            resp.data = []
            return resp

        raise NotImplementedError(f"unknown mode {self._mode}")


def _supabase(*, companies: Optional[List[Dict]] = None,
              profiles: Optional[List[Dict]] = None):
    store: Dict[str, List[Dict[str, Any]]] = {
        "companies": list(companies or []),
        "profiles": list(profiles or []),
    }
    supabase = MagicMock()
    supabase.table.side_effect = lambda name: _Chain(name, store)
    supabase._store = store  # exposed so the tests can assert post-state
    return supabase


def _ctx_user(*, company_id=None):
    return TenantContext(user_id="u-1", role="user", company_id=company_id)


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestCreateCompanyHappyPath:
    def test_creates_company_and_flips_role(self, monkeypatch):
        supabase = _supabase(profiles=[{"id": "u-1", "role": "user", "company_id": None}])
        monkeypatch.setattr("app.routers.companies.get_supabase", lambda: supabase)

        body = CompanyCreate(
            name="Acme", slug="acme", email="hr@acme.com",
            phone="+1 555 0100", address="123 Main St",
        )
        result = _run(create_company(body, ctx=_ctx_user()))

        # Company inserted with all fields
        companies = supabase._store["companies"]
        assert len(companies) == 1
        assert companies[0]["slug"] == "acme"
        assert companies[0]["name"] == "Acme"
        assert companies[0]["email"] == "hr@acme.com"
        assert companies[0]["phone"] == "+1 555 0100"
        assert companies[0]["address"] == "123 Main St"
        assert companies[0]["created_by"] == "u-1"

        # Profile flipped
        profile = supabase._store["profiles"][0]
        assert profile["role"] == "company_admin"
        assert profile["company_id"] == companies[0]["id"]

        # Response shape (PR 8 — contact fields surface back to the SPA)
        assert result.company.slug == "acme"
        assert result.company.name == "Acme"
        assert result.company.email == "hr@acme.com"
        assert result.company.phone == "+1 555 0100"
        assert result.profile["role"] == "company_admin"

    def test_optional_phone_address_omitted(self, monkeypatch):
        """Phone + address are optional. Empty strings should be stored
        as NULL so consumers can use `if company.phone` safely."""
        supabase = _supabase(profiles=[{"id": "u-1", "role": "user", "company_id": None}])
        monkeypatch.setattr("app.routers.companies.get_supabase", lambda: supabase)

        body = CompanyCreate(name="Acme", slug="acme", email="hr@acme.com")
        result = _run(create_company(body, ctx=_ctx_user()))

        assert result.company.email == "hr@acme.com"
        assert result.company.phone is None
        assert result.company.address is None

    def test_invalid_email_rejected(self):
        """Pydantic regex catches obviously-malformed emails before the
        endpoint runs. Plain string with no '@' fails."""
        import pytest as _pt
        with _pt.raises(Exception):  # ValidationError; broad to avoid pydantic-version churn
            CompanyCreate(name="Acme", slug="acme", email="not-an-email")


# ---------------------------------------------------------------------------
# Slug validation
# ---------------------------------------------------------------------------

class TestSlugValidation:
    def test_reserved_slug_rejected_400(self, monkeypatch):
        supabase = _supabase(profiles=[{"id": "u-1", "role": "user", "company_id": None}])
        monkeypatch.setattr("app.routers.companies.get_supabase", lambda: supabase)

        body = CompanyCreate(name="Acme", slug="default", email="hr@acme.com")
        with pytest.raises(HTTPException) as exc:
            _run(create_company(body, ctx=_ctx_user()))
        assert exc.value.status_code == 400
        assert "reserved" in exc.value.detail.lower()

    def test_taken_slug_rejected_400(self, monkeypatch):
        # Existing company with slug 'acme' already.
        supabase = _supabase(
            companies=[{"id": "c-existing", "slug": "acme", "name": "Acme Co"}],
            profiles=[{"id": "u-1", "role": "user", "company_id": None}],
        )
        monkeypatch.setattr("app.routers.companies.get_supabase", lambda: supabase)

        body = CompanyCreate(name="Acme Two", slug="acme", email="hr@acme.com")
        with pytest.raises(HTTPException) as exc:
            _run(create_company(body, ctx=_ctx_user()))
        assert exc.value.status_code == 400
        assert "taken" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# Precondition gates (role / company_id)
# ---------------------------------------------------------------------------

class TestPreconditions:
    def _supabase_with_profile(self):
        return _supabase(profiles=[{"id": "u-1", "role": "user", "company_id": None}])

    def test_already_admin_rejected_403(self, monkeypatch):
        monkeypatch.setattr("app.routers.companies.get_supabase",
                            lambda: self._supabase_with_profile())
        ctx = TenantContext(user_id="u-1", role="admin", company_id=None)
        with pytest.raises(HTTPException) as exc:
            _run(create_company(CompanyCreate(name="Acme", slug="acme", email="hr@acme.com"), ctx=ctx))
        assert exc.value.status_code == 403

    def test_already_company_admin_rejected_403(self, monkeypatch):
        monkeypatch.setattr("app.routers.companies.get_supabase",
                            lambda: self._supabase_with_profile())
        ctx = TenantContext(user_id="u-1", role="company_admin", company_id="c-other")
        with pytest.raises(HTTPException) as exc:
            _run(create_company(CompanyCreate(name="Acme", slug="acme", email="hr@acme.com"), ctx=ctx))
        assert exc.value.status_code == 403

    def test_already_recruiter_rejected_403(self, monkeypatch):
        """Recruiters creating a Company would split their identity across
        two tenants — disallow."""
        monkeypatch.setattr("app.routers.companies.get_supabase",
                            lambda: self._supabase_with_profile())
        ctx = TenantContext(user_id="u-1", role="recruiter", company_id="c-other")
        with pytest.raises(HTTPException) as exc:
            _run(create_company(CompanyCreate(name="Acme", slug="acme", email="hr@acme.com"), ctx=ctx))
        assert exc.value.status_code == 403

    def test_user_already_in_a_tenant_rejected_403(self, monkeypatch):
        """A B2B applicant (role='user' + company_id != None) can't break
        away from their tenant by creating a new Company."""
        monkeypatch.setattr("app.routers.companies.get_supabase",
                            lambda: self._supabase_with_profile())
        ctx = TenantContext(user_id="u-1", role="user", company_id="c-existing")
        with pytest.raises(HTTPException) as exc:
            _run(create_company(CompanyCreate(name="Acme", slug="acme", email="hr@acme.com"), ctx=ctx))
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/companies/mine (PR 5)
# ---------------------------------------------------------------------------

COMPANY_ID = str(uuid.uuid4())


def _user(user_id="u-1"):
    user = MagicMock()
    user.id = user_id
    return user


class TestGetMyCompany:
    def test_returns_caller_company(self, monkeypatch):
        supabase = _supabase(
            companies=[{
                "id": COMPANY_ID, "slug": "acme", "name": "Acme",
                "created_at": "2026-05-27T00:00:00Z",
            }],
            profiles=[{"id": "u-1", "role": "company_admin", "company_id": COMPANY_ID}],
        )
        monkeypatch.setattr("app.routers.companies.get_supabase", lambda: supabase)

        result = _run(get_my_company(user=_user()))
        assert str(result.id) == COMPANY_ID
        assert result.slug == "acme"
        assert result.name == "Acme"

    def test_caller_with_no_company_404(self, monkeypatch):
        """B2C users and platform admins both have NULL company_id."""
        supabase = _supabase(
            companies=[],
            profiles=[{"id": "u-1", "role": "user", "company_id": None}],
        )
        monkeypatch.setattr("app.routers.companies.get_supabase", lambda: supabase)

        with pytest.raises(HTTPException) as exc:
            _run(get_my_company(user=_user()))
        assert exc.value.status_code == 404

    def test_orphaned_company_id_404(self, monkeypatch):
        """Profile points at a company_id that no longer exists (e.g. ops
        manually deleted a Company row). Surface 404, not 500."""
        supabase = _supabase(
            companies=[],
            profiles=[{"id": "u-1", "role": "company_admin", "company_id": COMPANY_ID}],
        )
        monkeypatch.setattr("app.routers.companies.get_supabase", lambda: supabase)

        with pytest.raises(HTTPException) as exc:
            _run(get_my_company(user=_user()))
        assert exc.value.status_code == 404

    def test_missing_profile_404(self, monkeypatch):
        """Edge case: the auto-create trigger hasn't fired yet."""
        supabase = _supabase(companies=[], profiles=[])
        monkeypatch.setattr("app.routers.companies.get_supabase", lambda: supabase)

        with pytest.raises(HTTPException) as exc:
            _run(get_my_company(user=_user()))
        assert exc.value.status_code == 404
