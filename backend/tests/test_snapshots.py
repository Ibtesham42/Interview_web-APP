"""Tests for proctoring snapshots (migration 012).

Covers POST /api/interviews/{id}/snapshots (owner-only writes, tenant
stamp inherited from the interview, 503 when the table is missing) and
GET (report-gate parity: owner / same-tenant hiring roles / platform
admin read; cross-tenant 404; missing table degrades to empty).
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.auth import TenantContext
from app.models.schemas import SnapshotCreate
from app.routers.interviews import add_snapshot, list_snapshots


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

    def order(self, *_a, **_kw):
        return self

    def insert(self, payload):
        self._mode = "insert"
        self._payload = payload
        return self

    def execute(self):
        if self._table not in self._store:
            raise RuntimeError(f"relation \"{self._table}\" does not exist")
        rows = self._store[self._table]
        resp = MagicMock()
        if self._mode == "select":
            resp.data = [
                dict(r) for r in rows
                if all(r.get(c) == v for c, v in self._eqs)
            ]
            return resp
        if self._mode == "insert":
            row = {
                "id": str(uuid.uuid4()),
                "created_at": "2026-06-12T10:00:00+00:00",
                **self._payload,
            }
            rows.append(row)
            resp.data = [dict(row)]
            return resp
        raise NotImplementedError(f"unsupported mode {self._mode}")


def _supabase(store: Dict[str, List[Dict[str, Any]]]):
    supabase = MagicMock()
    supabase.table.side_effect = lambda name: _Chain(name, store)
    supabase._store = store
    return supabase


def _ctx(*, user_id="u-1", role="user", company_id=None):
    return TenantContext(user_id=user_id, role=role, company_id=company_id)


def _run(coro):
    return asyncio.run(coro)


COMPANY_A = str(uuid.uuid4())
COMPANY_B = str(uuid.uuid4())
IV_ID = uuid.uuid4()
IMG = "x" * 200  # passes the min_length=100 floor


def _store(*, with_snapshots=True):
    store: Dict[str, List[Dict[str, Any]]] = {
        "interviews": [{
            "id": str(IV_ID), "user_id": "u-1", "company_id": COMPANY_A,
            "status": "phase_1",
        }],
    }
    if with_snapshots:
        store["interview_snapshots"] = []
    return store


def _patch(monkeypatch, supabase):
    # add_snapshot/list_snapshots resolve their client in interviews.py;
    # the GET's auth gate resolves a second one inside reports.py.
    monkeypatch.setattr("app.routers.interviews.get_supabase", lambda: supabase)
    monkeypatch.setattr("app.routers.reports.get_supabase", lambda: supabase)


class TestAddSnapshot:
    def test_owner_stores_snapshot_with_tenant_stamp(self, monkeypatch):
        supabase = _supabase(_store())
        _patch(monkeypatch, supabase)

        result = _run(add_snapshot(IV_ID, SnapshotCreate(image_base64=IMG), user=_ctx()))
        assert result == {"stored": True}
        rows = supabase._store["interview_snapshots"]
        assert len(rows) == 1
        assert rows[0]["interview_id"] == str(IV_ID)
        assert rows[0]["company_id"] == COMPANY_A  # inherited from interview
        assert rows[0]["kind"] == "periodic"

    def test_integrity_kind_is_recorded(self, monkeypatch):
        supabase = _supabase(_store())
        _patch(monkeypatch, supabase)
        _run(add_snapshot(
            IV_ID, SnapshotCreate(image_base64=IMG, kind="integrity"), user=_ctx(),
        ))
        assert supabase._store["interview_snapshots"][0]["kind"] == "integrity"

    def test_non_owner_404(self, monkeypatch):
        supabase = _supabase(_store())
        _patch(monkeypatch, supabase)
        with pytest.raises(HTTPException) as exc:
            _run(add_snapshot(
                IV_ID, SnapshotCreate(image_base64=IMG), user=_ctx(user_id="intruder"),
            ))
        assert exc.value.status_code == 404
        assert supabase._store["interview_snapshots"] == []

    def test_missing_table_is_503(self, monkeypatch):
        supabase = _supabase(_store(with_snapshots=False))
        _patch(monkeypatch, supabase)
        with pytest.raises(HTTPException) as exc:
            _run(add_snapshot(IV_ID, SnapshotCreate(image_base64=IMG), user=_ctx()))
        assert exc.value.status_code == 503


class TestListSnapshots:
    def _seeded(self):
        store = _store()
        store["interview_snapshots"].append({
            "id": str(uuid.uuid4()), "interview_id": str(IV_ID),
            "kind": "periodic", "image_base64": IMG,
            "created_at": "2026-06-12T10:00:00+00:00",
        })
        return _supabase(store)

    def test_owner_reads_own_snapshots(self, monkeypatch):
        _patch(monkeypatch, self._seeded())
        result = _run(list_snapshots(IV_ID, user=_ctx()))
        assert len(result.items) == 1
        assert result.items[0].kind == "periodic"

    def test_same_tenant_company_admin_reads(self, monkeypatch):
        _patch(monkeypatch, self._seeded())
        result = _run(list_snapshots(
            IV_ID, user=_ctx(user_id="ca", role="company_admin", company_id=COMPANY_A),
        ))
        assert len(result.items) == 1

    def test_cross_tenant_recruiter_404(self, monkeypatch):
        _patch(monkeypatch, self._seeded())
        with pytest.raises(HTTPException) as exc:
            _run(list_snapshots(
                IV_ID, user=_ctx(user_id="rec", role="recruiter", company_id=COMPANY_B),
            ))
        assert exc.value.status_code == 404

    def test_platform_admin_reads(self, monkeypatch):
        _patch(monkeypatch, self._seeded())
        result = _run(list_snapshots(
            IV_ID, user=_ctx(user_id="adm", role="admin", company_id=None),
        ))
        assert len(result.items) == 1

    def test_missing_table_degrades_to_empty(self, monkeypatch):
        _patch(monkeypatch, _supabase(_store(with_snapshots=False)))
        result = _run(list_snapshots(IV_ID, user=_ctx()))
        assert result.items == []
