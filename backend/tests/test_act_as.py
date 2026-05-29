"""Tests for the act-as-company override (Candidate C, 2026-05-29).

Covers:
- Platform admin sending `X-Acting-As-Company` gets `ctx.company_id`
  mutated to the acted-on tenant.
- Non-admin callers' headers are ignored (defense-in-depth).
- Unknown company id is silently ignored — admin falls back to
  tenant-less.
- `tenant_scope` returns the acted-on id when an admin is acting-as,
  preserving the cross-tenant view when no override is set.
- `GET /api/companies/all` is platform-admin-only.

The handler shape is: FastAPI extracts the header and the user from
the request; both are passed as parameters to `get_tenant_context`.
We test the dependency function directly by passing constructed
arguments.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.auth import TenantContext, get_tenant_context, tenant_scope
from app.routers.companies import list_all_companies


COMPANY_A = "00000000-0000-0000-0000-00000000000a"
COMPANY_B = "00000000-0000-0000-0000-00000000000b"


# ---------------------------------------------------------------------------
# Minimal stub for the Supabase chain — supports
# `companies.select.eq(id, X).execute` (lookup in act-as) and
# `companies.select.order.execute` (list-all).
# ---------------------------------------------------------------------------

class _Chain:
    def __init__(self, table: str, store: Dict[str, List[Dict[str, Any]]]):
        self._table = table
        self._store = store
        self._eqs: List = []
        self._mode: Optional[str] = None

    def select(self, *_a, **_kw):
        self._mode = "select"
        return self

    def eq(self, col, val):
        self._eqs.append((col, val))
        return self

    def order(self, *_a, **_kw):
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
        raise AssertionError(f"Unhandled mode: {self._mode}")


def _supabase(*, companies=None, profiles=None):
    store = {
        "companies": list(companies or []),
        "profiles": list(profiles or []),
    }
    supabase = MagicMock()
    supabase.table.side_effect = lambda name: _Chain(name, store)
    return supabase


def _user(uid="u-1"):
    user = MagicMock()
    user.id = uid
    return user


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# get_tenant_context — act-as override semantics
# ---------------------------------------------------------------------------

class TestActAsOverride:
    def test_admin_with_valid_header_acts_as_target(self, monkeypatch):
        """Platform admin sending a valid X-Acting-As-Company → ctx
        carries the acted-on tenant id."""
        supabase = _supabase(
            companies=[{"id": COMPANY_A, "slug": "acme", "name": "Acme"}],
            profiles=[{"id": "u-1", "role": "admin", "company_id": None}],
        )
        monkeypatch.setattr("app.auth.get_supabase", lambda: supabase)

        ctx = get_tenant_context(user=_user(), x_acting_as_company=COMPANY_A)
        assert ctx.role == "admin"
        assert ctx.company_id == COMPANY_A

    def test_admin_without_header_remains_tenantless(self, monkeypatch):
        supabase = _supabase(
            companies=[{"id": COMPANY_A, "slug": "acme", "name": "Acme"}],
            profiles=[{"id": "u-1", "role": "admin", "company_id": None}],
        )
        monkeypatch.setattr("app.auth.get_supabase", lambda: supabase)

        ctx = get_tenant_context(user=_user(), x_acting_as_company=None)
        assert ctx.role == "admin"
        assert ctx.company_id is None

    def test_admin_with_unknown_target_silently_ignored(self, monkeypatch):
        """Unknown company id → admin stays tenantless. No 4xx surface
        (mirrors the apply-link 404 posture)."""
        supabase = _supabase(
            companies=[{"id": COMPANY_A, "slug": "acme", "name": "Acme"}],
            profiles=[{"id": "u-1", "role": "admin", "company_id": None}],
        )
        monkeypatch.setattr("app.auth.get_supabase", lambda: supabase)

        ctx = get_tenant_context(user=_user(), x_acting_as_company="not-a-real-id")
        assert ctx.company_id is None

    def test_company_admin_header_ignored(self, monkeypatch):
        """Defense-in-depth: a tenant admin cannot impersonate another
        tenant by sending the header. Override is admin-role-only."""
        supabase = _supabase(
            companies=[
                {"id": COMPANY_A, "slug": "acme", "name": "Acme"},
                {"id": COMPANY_B, "slug": "wayne", "name": "Wayne"},
            ],
            profiles=[{"id": "u-1", "role": "company_admin", "company_id": COMPANY_A}],
        )
        monkeypatch.setattr("app.auth.get_supabase", lambda: supabase)

        ctx = get_tenant_context(user=_user(), x_acting_as_company=COMPANY_B)
        assert ctx.role == "company_admin"
        # company_id stays as the caller's own tenant — the header is dropped.
        assert ctx.company_id == COMPANY_A

    def test_recruiter_header_ignored(self, monkeypatch):
        supabase = _supabase(
            companies=[
                {"id": COMPANY_A, "slug": "acme", "name": "Acme"},
                {"id": COMPANY_B, "slug": "wayne", "name": "Wayne"},
            ],
            profiles=[{"id": "u-1", "role": "recruiter", "company_id": COMPANY_A}],
        )
        monkeypatch.setattr("app.auth.get_supabase", lambda: supabase)

        ctx = get_tenant_context(user=_user(), x_acting_as_company=COMPANY_B)
        assert ctx.company_id == COMPANY_A

    def test_user_header_ignored(self, monkeypatch):
        supabase = _supabase(
            companies=[{"id": COMPANY_A, "slug": "acme", "name": "Acme"}],
            profiles=[{"id": "u-1", "role": "user", "company_id": None}],
        )
        monkeypatch.setattr("app.auth.get_supabase", lambda: supabase)

        ctx = get_tenant_context(user=_user(), x_acting_as_company=COMPANY_A)
        # B2C user stays tenantless regardless of header.
        assert ctx.company_id is None


# ---------------------------------------------------------------------------
# tenant_scope — interaction with act-as
# ---------------------------------------------------------------------------

class TestTenantScopeWithActAs:
    def test_admin_acting_as_scopes_to_target(self):
        """Admin acting-as a tenant gets scoped like any member."""
        ctx = TenantContext(user_id="u-1", role="admin", company_id=COMPANY_A)
        assert tenant_scope(ctx) == COMPANY_A

    def test_admin_no_act_as_returns_none(self):
        """Tenantless platform admin sees across all tenants."""
        ctx = TenantContext(user_id="u-1", role="admin", company_id=None)
        assert tenant_scope(ctx) is None

    def test_company_admin_scopes_to_own_tenant(self):
        ctx = TenantContext(user_id="u-1", role="company_admin", company_id=COMPANY_A)
        assert tenant_scope(ctx) == COMPANY_A


# ---------------------------------------------------------------------------
# GET /api/companies/all — platform-admin-only listing for the picker
# ---------------------------------------------------------------------------

class TestListAllCompanies:
    def test_admin_sees_every_company(self, monkeypatch):
        supabase = _supabase(companies=[
            {"id": COMPANY_A, "slug": "acme", "name": "Acme"},
            {"id": COMPANY_B, "slug": "wayne", "name": "Wayne"},
        ])
        monkeypatch.setattr("app.routers.companies.get_supabase", lambda: supabase)

        ctx = TenantContext(user_id="u-1", role="admin", company_id=None)
        result = _run(list_all_companies(ctx=ctx))
        assert len(result) == 2
        assert {c["slug"] for c in result} == {"acme", "wayne"}
        # Thin payload — no contact info or counts leaked.
        assert set(result[0].keys()) == {"id", "slug", "name"}

    def test_company_admin_rejected_403(self, monkeypatch):
        """company_admin has one tenant — cross-tenant listing isn't theirs."""
        supabase = _supabase(companies=[])
        monkeypatch.setattr("app.routers.companies.get_supabase", lambda: supabase)

        ctx = TenantContext(user_id="u-1", role="company_admin", company_id=COMPANY_A)
        with pytest.raises(HTTPException) as exc:
            _run(list_all_companies(ctx=ctx))
        assert exc.value.status_code == 403

    def test_recruiter_rejected_403(self, monkeypatch):
        supabase = _supabase(companies=[])
        monkeypatch.setattr("app.routers.companies.get_supabase", lambda: supabase)

        ctx = TenantContext(user_id="u-1", role="recruiter", company_id=COMPANY_A)
        with pytest.raises(HTTPException) as exc:
            _run(list_all_companies(ctx=ctx))
        assert exc.value.status_code == 403

    def test_user_rejected_403(self, monkeypatch):
        supabase = _supabase(companies=[])
        monkeypatch.setattr("app.routers.companies.get_supabase", lambda: supabase)

        ctx = TenantContext(user_id="u-1", role="user", company_id=None)
        with pytest.raises(HTTPException) as exc:
            _run(list_all_companies(ctx=ctx))
        assert exc.value.status_code == 403
