"""Tests for resume -> job skill matching (Phase 3).

Pure `skill_match` coverage + the endpoint (ranking + gap analysis +
tenant gate). Deterministic, so the assertions are exact.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, List, Optional
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.auth import TenantContext
from app.routers.recruiter import job_matches_endpoint
from app.services.resume_match import skill_match

A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
J1 = "10000000-0000-0000-0000-000000000001"
C1 = "c1000000-0000-0000-0000-000000000001"
C2 = "c2000000-0000-0000-0000-000000000002"
REC = "33333333-3333-3333-3333-333333333333"


# ---------------------------------------------------------------------------
# Pure skill_match
# ---------------------------------------------------------------------------

class TestSkillMatch:
    def test_partial_overlap(self):
        m = skill_match(["python", "fastapi"], ["Python"], "")
        assert m["matched"] == ["python"]
        assert m["missing"] == ["fastapi"]
        assert m["score"] == 50

    def test_resume_text_fallback(self):
        m = skill_match(["python"], [], "I built REST APIs in Python and Go")
        assert m["score"] == 100
        assert m["matched"] == ["python"]

    def test_no_required_is_zero(self):
        m = skill_match([], ["python"], "python")
        assert m["score"] == 0
        assert m["required_count"] == 0

    def test_none_matched(self):
        m = skill_match(["rust"], ["python"], "python developer")
        assert m["score"] == 0
        assert m["missing"] == ["rust"]

    def test_dict_shaped_skills_tolerated(self):
        m = skill_match(["python"], [{"name": "Python"}], "")
        assert m["score"] == 100


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

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

    def execute(self):
        out = []
        for r in self._store.get(self._t, []):
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


def _store():
    return {
        "jobs": [{"id": J1, "company_id": A, "title": "Backend Engineer", "slug": "backend",
                  "status": "open", "required_skills": ["python", "fastapi", "sql"]}],
        "interviews": [
            {"id": "iv-1", "candidate_id": C1, "job_id": J1},
            {"id": "iv-2", "candidate_id": C2, "job_id": J1},
        ],
        "candidates": [
            {"id": C1, "name": "Alice", "email": "a@x.com", "company_id": A,
             "resume_sections": {"skills": ["Python", "FastAPI", "SQL"]}, "resume_text": ""},
            {"id": C2, "name": "Bob", "email": "b@x.com", "company_id": A,
             "resume_sections": {"skills": ["Java"]}, "resume_text": "some SQL experience"},
        ],
    }


def test_matches_ranked_with_gap(monkeypatch):
    sb = _supabase(_store())
    monkeypatch.setattr("app.routers.recruiter.get_supabase", lambda: sb)
    result = _run(job_matches_endpoint(J1, user=_ctx(company_id=A)))

    assert result.required_skills == ["python", "fastapi", "sql"]
    assert [str(m.candidate_id) for m in result.matches] == [C1, C2]  # ranked by score
    top = result.matches[0]
    assert top.match_score == 100
    assert set(top.matched_skills) == {"python", "fastapi", "sql"}
    second = result.matches[1]
    assert second.match_score == 33  # only 'sql' (from resume_text) of 3
    assert second.matched_skills == ["sql"]
    assert set(second.missing_skills) == {"python", "fastapi"}


def test_matches_cross_tenant_404(monkeypatch):
    store = _store()
    store["jobs"][0]["company_id"] = B
    sb = _supabase(store)
    monkeypatch.setattr("app.routers.recruiter.get_supabase", lambda: sb)
    with pytest.raises(HTTPException) as exc:
        _run(job_matches_endpoint(J1, user=_ctx(company_id=A)))
    assert exc.value.status_code == 404
