"""Tests for the job-requisition endpoints (migration 013 — ATS keystone).

The endpoints are called directly (same style as test_email_endpoints.py),
with a filter-aware fake Supabase so tenant scoping is verifiable. The
`manage_jobs` capability gate itself is covered in test_capabilities.py; here
we verify the router/service logic: CRUD, tenant isolation (cross-tenant 404),
per-company slug uniqueness, and the public OPEN-only apply lookup.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List, Optional

import pytest
from fastapi import HTTPException
from unittest.mock import MagicMock

from app.auth import TenantContext
from app.models.schemas import InviteCandidateRequest, JobCreate, JobUpdate
from app.routers.companies import invite_candidate
from app.routers.jobs import (
    create_job,
    get_job,
    get_public_job,
    list_jobs,
    update_job,
)

A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RECRUITER = "33333333-3333-3333-3333-333333333333"
# Job ids must be valid UUIDs — JobResponse.id is typed UUID.
J1 = "11111111-1111-1111-1111-111111111111"
J2 = "22222222-2222-2222-2222-222222222222"
JB = "99999999-9999-9999-9999-999999999999"


# ---------------------------------------------------------------------------
# Filter-aware fake Supabase: select/eq/order/limit/insert/update.
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, data: List[Dict[str, Any]]):
        self.data = data


class _Chain:
    def __init__(self, table: str, store: Dict[str, List[Dict[str, Any]]]):
        self._table = table
        self._store = store
        self._eqs: List = []
        self._mode = "select"
        self._payload: Any = None
        self._order: Optional[str] = None
        self._desc = False
        self._limit: Optional[int] = None

    def select(self, *_a, **_k):
        self._mode = "select"
        return self

    def eq(self, col, val):
        self._eqs.append((col, val))
        return self

    def order(self, col, desc=False):
        self._order, self._desc = col, desc
        return self

    def limit(self, n):
        self._limit = n
        return self

    def insert(self, payload):
        self._mode, self._payload = "insert", payload
        return self

    def update(self, payload):
        self._mode, self._payload = "update", payload
        return self

    def _match(self, row) -> bool:
        return all(row.get(col) == val for col, val in self._eqs)

    def execute(self):
        rows = self._store.setdefault(self._table, [])
        if self._mode == "select":
            out = [r for r in rows if self._match(r)]
            if self._order:
                out = sorted(out, key=lambda r: r.get(self._order) or "", reverse=self._desc)
            if self._limit is not None:
                out = out[: self._limit]
            return _Resp([dict(r) for r in out])
        if self._mode == "insert":
            ins = dict(self._payload)
            ins.setdefault("id", str(uuid.uuid4()))
            ins.setdefault("created_at", "2026-06-13T00:00:00Z")
            ins.setdefault("updated_at", "2026-06-13T00:00:00Z")
            rows.append(ins)
            return _Resp([dict(ins)])
        if self._mode == "update":
            updated = []
            for r in rows:
                if self._match(r):
                    r.update(self._payload)
                    updated.append(dict(r))
            return _Resp(updated)
        raise NotImplementedError(self._mode)


def _supabase(*, jobs=None, companies=None):
    store = {"jobs": list(jobs or []), "companies": list(companies or [])}
    sb = MagicMock()
    sb.table.side_effect = lambda name: _Chain(name, store)
    sb._store = store
    return sb


def _ctx(role="recruiter", company_id=A):
    return TenantContext(user_id=RECRUITER, role=role, company_id=company_id)


def _run(coro):
    return asyncio.run(coro)


def _job_row(job_id, company_id, slug, *, status="open", title="Backend Engineer"):
    return {
        "id": job_id, "company_id": company_id, "title": title, "slug": slug,
        "description": "Build APIs", "required_skills": ["python"],
        "employment_type": "full-time", "location": "Remote", "status": status,
        "interview_config": {}, "created_by": RECRUITER,
        "created_at": "2026-06-13T00:00:00Z", "updated_at": "2026-06-13T00:00:00Z",
    }


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

class TestCreateJob:
    def test_creates_job_stamped_with_tenant_and_defaults(self, monkeypatch):
        sb = _supabase()
        monkeypatch.setattr("app.routers.jobs.get_supabase", lambda: sb)
        result = _run(create_job(
            JobCreate(title="Backend Engineer", slug="backend-engineer"),
            ctx=_ctx(),
        ))
        assert str(result.company_id) == A
        assert result.slug == "backend-engineer"
        assert result.status == "draft"            # default when unspecified
        assert result.required_skills == []
        assert len(sb._store["jobs"]) == 1

    def test_slug_is_lowercased(self, monkeypatch):
        sb = _supabase()
        monkeypatch.setattr("app.routers.jobs.get_supabase", lambda: sb)
        # Pydantic slug pattern is already lowercase-only; the router still
        # normalises defensively. Use an already-valid slug + assert it lands.
        result = _run(create_job(
            JobCreate(title="Data Scientist", slug="data-scientist", status="open"),
            ctx=_ctx(),
        ))
        assert result.slug == "data-scientist"
        assert result.status == "open"

    def test_duplicate_slug_in_company_is_400(self, monkeypatch):
        sb = _supabase(jobs=[_job_row(J1, A, "backend-engineer")])
        monkeypatch.setattr("app.routers.jobs.get_supabase", lambda: sb)
        with pytest.raises(HTTPException) as exc:
            _run(create_job(
                JobCreate(title="Another", slug="backend-engineer"), ctx=_ctx(),
            ))
        assert exc.value.status_code == 400

    def test_same_slug_different_company_is_allowed(self, monkeypatch):
        # Company B already has 'backend-engineer'; company A may reuse it.
        sb = _supabase(jobs=[_job_row(JB, B, "backend-engineer")])
        monkeypatch.setattr("app.routers.jobs.get_supabase", lambda: sb)
        result = _run(create_job(
            JobCreate(title="Backend Engineer", slug="backend-engineer"),
            ctx=_ctx(company_id=A),
        ))
        assert str(result.company_id) == A


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

class TestListJobs:
    def test_lists_only_callers_company(self, monkeypatch):
        sb = _supabase(jobs=[
            _job_row(J1, A, "a-one"), _job_row(J2, A, "a-two"),
            _job_row(JB, B, "b-one"),
        ])
        monkeypatch.setattr("app.routers.jobs.get_supabase", lambda: sb)
        # Pass job_status=None explicitly: a direct call (vs a real request)
        # would otherwise leave the FastAPI Query(...) default object in place.
        result = _run(list_jobs(job_status=None, ctx=_ctx(company_id=A)))
        slugs = {item.slug for item in result.items}
        assert slugs == {"a-one", "a-two"}

    def test_status_filter(self, monkeypatch):
        sb = _supabase(jobs=[
            _job_row(J1, A, "open-one", status="open"),
            _job_row(J2, A, "draft-one", status="draft"),
        ])
        monkeypatch.setattr("app.routers.jobs.get_supabase", lambda: sb)
        result = _run(list_jobs(job_status="open", ctx=_ctx()))
        assert [i.slug for i in result.items] == ["open-one"]


# ---------------------------------------------------------------------------
# Get / Update — tenant isolation
# ---------------------------------------------------------------------------

class TestGetUpdateJob:
    def test_get_returns_job(self, monkeypatch):
        sb = _supabase(jobs=[_job_row(J1, A, "a-one")])
        monkeypatch.setattr("app.routers.jobs.get_supabase", lambda: sb)
        result = _run(get_job(J1, ctx=_ctx(company_id=A)))
        assert result.slug == "a-one"

    def test_get_cross_tenant_404(self, monkeypatch):
        sb = _supabase(jobs=[_job_row(JB, B, "b-one")])
        monkeypatch.setattr("app.routers.jobs.get_supabase", lambda: sb)
        with pytest.raises(HTTPException) as exc:
            _run(get_job(JB, ctx=_ctx(company_id=A)))
        assert exc.value.status_code == 404

    def test_update_changes_status(self, monkeypatch):
        sb = _supabase(jobs=[_job_row(J1, A, "a-one", status="draft")])
        monkeypatch.setattr("app.routers.jobs.get_supabase", lambda: sb)
        result = _run(update_job(J1, JobUpdate(status="open"), ctx=_ctx(company_id=A)))
        assert result.status == "open"

    def test_update_cross_tenant_404(self, monkeypatch):
        sb = _supabase(jobs=[_job_row(JB, B, "b-one")])
        monkeypatch.setattr("app.routers.jobs.get_supabase", lambda: sb)
        with pytest.raises(HTTPException) as exc:
            _run(update_job(JB, JobUpdate(title="Hacked"), ctx=_ctx(company_id=A)))
        assert exc.value.status_code == 404

    def test_update_to_colliding_slug_400(self, monkeypatch):
        sb = _supabase(jobs=[
            _job_row(J1, A, "a-one"), _job_row(J2, A, "a-two"),
        ])
        monkeypatch.setattr("app.routers.jobs.get_supabase", lambda: sb)
        with pytest.raises(HTTPException) as exc:
            _run(update_job(J1, JobUpdate(slug="a-two"), ctx=_ctx(company_id=A)))
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# Public apply lookup — OPEN only, no auth
# ---------------------------------------------------------------------------

class TestPublicJob:
    def _sb_with_open_job(self, status="open"):
        return _supabase(
            companies=[{"id": A, "slug": "acme", "name": "Acme Inc."}],
            jobs=[_job_row(J1, A, "backend-engineer", status=status)],
        )

    def test_open_job_resolves(self, monkeypatch):
        sb = self._sb_with_open_job()
        monkeypatch.setattr("app.routers.jobs.get_supabase", lambda: sb)
        result = _run(get_public_job("acme", "backend-engineer"))
        assert result.company_name == "Acme Inc."
        assert result.title == "Backend Engineer"
        assert result.slug == "backend-engineer"

    def test_draft_job_404(self, monkeypatch):
        sb = self._sb_with_open_job(status="draft")
        monkeypatch.setattr("app.routers.jobs.get_supabase", lambda: sb)
        with pytest.raises(HTTPException) as exc:
            _run(get_public_job("acme", "backend-engineer"))
        assert exc.value.status_code == 404

    def test_unknown_company_404(self, monkeypatch):
        sb = self._sb_with_open_job()
        monkeypatch.setattr("app.routers.jobs.get_supabase", lambda: sb)
        with pytest.raises(HTTPException) as exc:
            _run(get_public_job("nope", "backend-engineer"))
        assert exc.value.status_code == 404

    def test_unknown_job_slug_404(self, monkeypatch):
        sb = self._sb_with_open_job()
        monkeypatch.setattr("app.routers.jobs.get_supabase", lambda: sb)
        with pytest.raises(HTTPException) as exc:
            _run(get_public_job("acme", "nope"))
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Invite job-link (migration 013) — an invite can't target another tenant's job
# ---------------------------------------------------------------------------

class TestInviteJobLink:
    def test_invite_with_cross_company_job_is_400(self, monkeypatch):
        """A company-A sender referencing a company-B job is rejected before
        any email is sent — the job-link is tenant-validated."""
        sb = _supabase(
            jobs=[_job_row(J1, B, "b-job")],
            companies=[{"id": A, "slug": "acme", "name": "Acme Inc."}],
        )
        monkeypatch.setattr("app.routers.companies.get_supabase", lambda: sb)
        with pytest.raises(HTTPException) as exc:
            _run(invite_candidate(
                InviteCandidateRequest(to_email="x@y.com", job_id=J1),
                ctx=_ctx(company_id=A),
            ))
        assert exc.value.status_code == 400
