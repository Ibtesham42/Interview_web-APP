"""Admin-overview response-shape tests.

Guards the `integrity_volume` field added to `GET /api/admin/overview`
(reliability task — surface integrity-event volume by type so an operator
can triage noise patterns from the overview without opening each user).

The risk pattern these tests pin: a handler runs the SELECT but the
response dict drops the field (or applies the wrong tenant scope). A
plain key-presence + count assertion catches that fast. The grouping /
sorting / missing-table behaviour itself lives in `integrity_event_volume`
and is covered by `test_recruiter_analytics.py` — not re-tested here.

The fake supabase honours `.eq("company_id", X)` so "only A's events came
back" is a meaningful assertion, mirroring `test_tenant_scoping.py`.
"""
import asyncio
from unittest.mock import MagicMock

from app.auth import TenantContext
from app.routers import admin as admin_router


A = "company-a"
B = "company-b"


class _FilterAwareChain:
    """Minimal supabase query chain that honours `.eq()` / `.in_()`."""

    def __init__(self, rows):
        self._rows = rows
        self._eqs = []
        self._ins = []

    def select(self, *_a, **_kw):
        return self

    def order(self, *_a, **_kw):
        return self

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
    table_rows = {
        "profiles": [],
        "interviews": [
            {"id": "iv-a", "candidate_id": "c-a", "user_id": "u-a",
             "status": "completed", "created_at": "2026-01-02T00:00:00Z",
             "company_id": A},
            {"id": "iv-b", "candidate_id": "c-b", "user_id": "u-b",
             "status": "completed", "created_at": "2026-01-02T00:00:00Z",
             "company_id": B},
        ],
        "candidates": [
            {"id": "c-a", "field_specialization": "ml", "company_id": A},
            {"id": "c-b", "field_specialization": "ml", "company_id": B},
        ],
        "evaluations": [
            {"interview_id": "iv-a", "phase": 2, "depth_score": 8,
             "accuracy_score": 8, "details": {}, "company_id": A},
            {"interview_id": "iv-b", "phase": 2, "depth_score": 8,
             "accuracy_score": 8, "details": {}, "company_id": B},
        ],
        "interview_integrity_events": [
            {"interview_id": "iv-a", "event_type": "tab_blur", "company_id": A},
            {"interview_id": "iv-a", "event_type": "tab_blur", "company_id": A},
            {"interview_id": "iv-a", "event_type": "multi_face", "company_id": A},
            {"interview_id": "iv-b", "event_type": "tab_blur", "company_id": B},
        ],
    }
    supabase = MagicMock()
    supabase.table.side_effect = lambda name: _FilterAwareChain(table_rows[name])
    return supabase


def _run(ctx, monkeypatch):
    fake = _two_tenant_supabase()
    monkeypatch.setattr(admin_router, "get_supabase", lambda: fake)
    return asyncio.run(admin_router.admin_overview(admin=ctx))


def _admin(company_id):
    return TenantContext(user_id="admin", role="admin", company_id=company_id)


class TestAdminOverviewIntegrityVolume:
    def test_response_carries_integrity_volume_field(self, monkeypatch):
        result = _run(_admin(None), monkeypatch)
        assert "integrity_volume" in result
        assert set(result["integrity_volume"]) == {"items", "total"}

    def test_platform_admin_sees_all_tenants_events(self, monkeypatch):
        result = _run(_admin(None), monkeypatch)
        vol = result["integrity_volume"]
        assert vol["total"] == 4
        # Sorted by count desc: tab_blur (3) before multi_face (1).
        assert vol["items"] == [
            {"event_type": "tab_blur", "count": 3},
            {"event_type": "multi_face", "count": 1},
        ]

    def test_scoped_admin_sees_only_own_tenant_events(self, monkeypatch):
        result = _run(_admin(A), monkeypatch)
        vol = result["integrity_volume"]
        assert vol["total"] == 3
        assert {i["event_type"] for i in vol["items"]} == {"tab_blur", "multi_face"}

    def test_other_tenant_admin_isolated(self, monkeypatch):
        result = _run(_admin(B), monkeypatch)
        vol = result["integrity_volume"]
        assert vol["total"] == 1
        assert vol["items"] == [{"event_type": "tab_blur", "count": 1}]
