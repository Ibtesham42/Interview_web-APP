"""Tests for the per-job ATS pipeline endpoint (Phase 2).

Verifies the board groups a job's candidates (via interviews.job_id) by the
caller's derived status, reuses the scoring, and is tenant-gated. Endpoint
called directly with a filter-aware fake Supabase (test_jobs.py style).
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.auth import TenantContext
from app.routers.recruiter import job_pipeline_endpoint

A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
J1 = "10000000-0000-0000-0000-000000000001"
C1 = "c1000000-0000-0000-0000-000000000001"
C2 = "c2000000-0000-0000-0000-000000000002"
IV1 = "i1000000-0000-0000-0000-000000000001"
IV2 = "i2000000-0000-0000-0000-000000000002"
REC = "33333333-3333-3333-3333-333333333333"


class _Resp:
    def __init__(self, data):
        self.data = data


class _Chain:
    def __init__(self, table, store):
        self._t, self._store = table, store
        self._eqs: List = []
        self._in: Optional[tuple] = None
        self._limit: Optional[int] = None

    def select(self, *_a, **_k):
        return self

    def eq(self, c, v):
        self._eqs.append((c, v)); return self

    def in_(self, c, vals):
        self._in = (c, list(vals)); return self

    def limit(self, n):
        self._limit = n; return self

    def order(self, *_a, **_k):
        return self

    def execute(self):
        rows = self._store.get(self._t, [])
        out = []
        for r in rows:
            if any(r.get(c) != v for c, v in self._eqs):
                continue
            if self._in is not None and r.get(self._in[0]) not in self._in[1]:
                continue
            out.append(dict(r))
        if self._limit is not None:
            out = out[: self._limit]
        return _Resp(out)


def _supabase(store):
    sb = MagicMock()
    sb.table.side_effect = lambda name: _Chain(name, store)
    return sb


def _ctx(company_id=A):
    return TenantContext(user_id=REC, role="recruiter", company_id=company_id)


def _run(coro):
    return asyncio.run(coro)


def _evals_for(iv_id, overall=8):
    return [
        {"interview_id": iv_id, "phase": 2, "depth_score": overall, "accuracy_score": overall, "details": {"clarity": overall}},
        {"interview_id": iv_id, "phase": 3, "depth_score": overall, "accuracy_score": overall, "details": {"clarity": overall}},
        {"interview_id": iv_id, "phase": 4, "accuracy_score": overall, "details": {}},
        {"interview_id": iv_id, "phase": 5, "details": {
            "vision": overall, "team": overall, "self_awareness": overall, "proactivity": overall, "communication": overall}},
    ]


def _store_two_candidates():
    return {
        "jobs": [{"id": J1, "company_id": A, "title": "Backend Engineer", "slug": "backend", "status": "open"}],
        "interviews": [
            {"id": IV1, "candidate_id": C1, "job_id": J1, "status": "completed", "created_at": "2026-06-13T00:00:00Z"},
            {"id": IV2, "candidate_id": C2, "job_id": J1, "status": "completed", "created_at": "2026-06-13T00:00:00Z"},
        ],
        "candidates": [
            {"id": C1, "name": "Alice", "email": "a@x.com", "field_specialization": "ml", "company_id": A, "created_at": "2026-06-01T00:00:00Z"},
            {"id": C2, "name": "Bob", "email": "b@x.com", "field_specialization": "web_dev", "company_id": A, "created_at": "2026-06-02T00:00:00Z"},
        ],
        "evaluations": _evals_for(IV1, 8),  # C1 scores 8; C2 has none
        "recruiter_decisions": [
            {"candidate_id": C2, "recruiter_id": REC, "decision": "shortlisted"},
        ],
    }


def test_pipeline_groups_by_derived_status(monkeypatch):
    sb = _supabase(_store_two_candidates())
    monkeypatch.setattr("app.routers.recruiter.get_supabase", lambda: sb)
    result = _run(job_pipeline_endpoint(J1, user=_ctx(company_id=A)))

    assert result.job.title == "Backend Engineer"
    by_id = {str(c.candidate_id): c for c in result.candidates}
    assert len(by_id) == 2
    # C1: completed, no decision -> interview_completed; score reuses the bulk path.
    assert by_id[C1].status == "interview_completed"
    assert by_id[C1].final_score == 8.0
    assert by_id[C1].recommendation == "Hire"
    # C2: shortlisted decision -> status shortlisted (overrides funnel).
    assert by_id[C2].status == "shortlisted"


def test_pipeline_cross_tenant_job_404(monkeypatch):
    # Job belongs to company B; a recruiter of A can't open its pipeline.
    store = _store_two_candidates()
    store["jobs"][0]["company_id"] = B
    sb = _supabase(store)
    monkeypatch.setattr("app.routers.recruiter.get_supabase", lambda: sb)
    with pytest.raises(HTTPException) as exc:
        _run(job_pipeline_endpoint(J1, user=_ctx(company_id=A)))
    assert exc.value.status_code == 404


def test_pipeline_empty_when_no_interviews(monkeypatch):
    store = _store_two_candidates()
    store["interviews"] = []
    sb = _supabase(store)
    monkeypatch.setattr("app.routers.recruiter.get_supabase", lambda: sb)
    result = _run(job_pipeline_endpoint(J1, user=_ctx(company_id=A)))
    assert result.candidates == []
