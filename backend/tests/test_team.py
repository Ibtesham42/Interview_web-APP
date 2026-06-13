"""Tests for the team-management endpoints (migration 014).

Endpoints are called directly (same style as test_jobs.py) with a filter-aware
fake Supabase. The `manage_team` capability gate is covered in
test_capabilities.py; here we verify the router/service logic: invite, revoke
(tenant-scoped), accept (identity + role guards), and the members listing.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.auth import TenantContext
from app.models.schemas import AcceptTeamInviteRequest, TeamInviteRequest
from app.routers.team import (
    accept_team_invite,
    get_team,
    invite_member,
    revoke_member_invite,
)

A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
ADMIN = "33333333-3333-3333-3333-333333333333"
INV1 = "11111111-1111-1111-1111-111111111111"
USER_ID = "55555555-5555-5555-5555-555555555555"


class _Resp:
    def __init__(self, data):
        self.data = data


class _Chain:
    def __init__(self, table, store):
        self._t, self._store = table, store
        self._eqs: List = []
        self._in: Optional[tuple] = None
        self._mode = "select"
        self._payload: Any = None
        self._limit: Optional[int] = None
        self._order: Optional[str] = None
        self._desc = False

    def select(self, *_a, **_k):
        self._mode = "select"; return self

    def eq(self, c, v):
        self._eqs.append((c, v)); return self

    def in_(self, c, vals):
        self._in = (c, list(vals)); return self

    def order(self, c, desc=False):
        self._order, self._desc = c, desc; return self

    def limit(self, n):
        self._limit = n; return self

    def insert(self, p):
        self._mode, self._payload = "insert", p; return self

    def update(self, p):
        self._mode, self._payload = "update", p; return self

    def _match(self, r):
        if any(r.get(c) != v for c, v in self._eqs):
            return False
        if self._in is not None and r.get(self._in[0]) not in self._in[1]:
            return False
        return True

    def execute(self):
        rows = self._store.setdefault(self._t, [])
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


def _supabase(*, profiles=None, team_invitations=None, companies=None):
    store = {
        "profiles": list(profiles or []),
        "team_invitations": list(team_invitations or []),
        "companies": list(companies or []),
    }
    sb = MagicMock()
    sb.table.side_effect = lambda name: _Chain(name, store)
    sb._store = store
    return sb


def _ctx(role="company_admin", company_id=A):
    return TenantContext(user_id=ADMIN, role=role, company_id=company_id)


def _user(user_id=USER_ID, email="new@acme.com"):
    u = MagicMock()
    u.id = user_id
    u.email = email
    return u


def _run(coro):
    return asyncio.run(coro)


def _company_a():
    return {"id": A, "slug": "acme", "name": "Acme Inc.", "email": "hr@acme.com",
            "phone": None, "address": None}


def _stub_email(monkeypatch, status="sent"):
    async def fake_send(supabase, **kwargs):
        return {"id": str(uuid.uuid4()), "status": status, "error_message": None}
    monkeypatch.setattr("app.routers.team.email_svc.send", fake_send)


# ---------------------------------------------------------------------------
# Invite
# ---------------------------------------------------------------------------

class TestInviteMember:
    def test_invite_creates_pending_and_emails(self, monkeypatch):
        _stub_email(monkeypatch)
        sb = _supabase(companies=[_company_a()])
        monkeypatch.setattr("app.routers.team.get_supabase", lambda: sb)
        result = _run(invite_member(
            TeamInviteRequest(email="New@Acme.com", role="recruiter"), ctx=_ctx(),
        ))
        assert result.role == "recruiter"
        assert result.status == "pending"
        assert result.email_status == "sent"
        rows = sb._store["team_invitations"]
        assert len(rows) == 1
        assert rows[0]["email"] == "new@acme.com"  # normalised

    def test_reinvite_updates_role_not_duplicate(self, monkeypatch):
        _stub_email(monkeypatch)
        sb = _supabase(
            companies=[_company_a()],
            team_invitations=[{
                "id": INV1, "company_id": A, "email": "new@acme.com",
                "role": "recruiter", "status": "revoked", "invited_by": ADMIN,
                "created_at": "2026-06-13T00:00:00Z",
            }],
        )
        monkeypatch.setattr("app.routers.team.get_supabase", lambda: sb)
        result = _run(invite_member(
            TeamInviteRequest(email="new@acme.com", role="company_admin"), ctx=_ctx(),
        ))
        assert result.role == "company_admin"
        assert result.status == "pending"
        assert len(sb._store["team_invitations"]) == 1  # revived, not duplicated


# ---------------------------------------------------------------------------
# Revoke — tenant-scoped
# ---------------------------------------------------------------------------

class TestRevoke:
    def _pending(self, company_id=A):
        return {"id": INV1, "company_id": company_id, "email": "x@acme.com",
                "role": "recruiter", "status": "pending", "invited_by": ADMIN,
                "created_at": "2026-06-13T00:00:00Z"}

    def test_revoke_pending(self, monkeypatch):
        sb = _supabase(team_invitations=[self._pending()])
        monkeypatch.setattr("app.routers.team.get_supabase", lambda: sb)
        result = _run(revoke_member_invite(INV1, ctx=_ctx(company_id=A)))
        assert result["status"] == "revoked"
        assert sb._store["team_invitations"][0]["status"] == "revoked"

    def test_revoke_cross_tenant_404(self, monkeypatch):
        # Invitation belongs to company B; admin of A can't revoke it.
        sb = _supabase(team_invitations=[self._pending(company_id=B)])
        monkeypatch.setattr("app.routers.team.get_supabase", lambda: sb)
        with pytest.raises(HTTPException) as exc:
            _run(revoke_member_invite(INV1, ctx=_ctx(company_id=A)))
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Accept — identity + role guards
# ---------------------------------------------------------------------------

class TestAccept:
    def _sb(self):
        return _supabase(
            companies=[_company_a()],
            profiles=[{"id": USER_ID, "email": "new@acme.com", "role": "user", "company_id": None}],
            team_invitations=[{
                "id": INV1, "company_id": A, "email": "new@acme.com",
                "role": "recruiter", "status": "pending", "invited_by": ADMIN,
                "created_at": "2026-06-13T00:00:00Z",
            }],
        )

    def test_accept_stamps_profile_and_marks_accepted(self, monkeypatch):
        sb = self._sb()
        monkeypatch.setattr("app.routers.team.get_supabase", lambda: sb)
        result = _run(accept_team_invite(
            AcceptTeamInviteRequest(company_slug="acme"),
            user=_user(email="new@acme.com"), ctx=_ctx(role="user", company_id=None),
        ))
        assert str(result.company_id) == A
        assert result.role == "recruiter"
        profile = sb._store["profiles"][0]
        assert profile["role"] == "recruiter"
        assert profile["company_id"] == A
        assert sb._store["team_invitations"][0]["status"] == "accepted"

    def test_email_mismatch_404(self, monkeypatch):
        sb = self._sb()
        monkeypatch.setattr("app.routers.team.get_supabase", lambda: sb)
        with pytest.raises(HTTPException) as exc:
            _run(accept_team_invite(
                AcceptTeamInviteRequest(company_slug="acme"),
                user=_user(email="someone-else@acme.com"), ctx=_ctx(role="user", company_id=None),
            ))
        assert exc.value.status_code == 404

    def test_already_hiring_account_400(self, monkeypatch):
        sb = self._sb()
        monkeypatch.setattr("app.routers.team.get_supabase", lambda: sb)
        with pytest.raises(HTTPException) as exc:
            _run(accept_team_invite(
                AcceptTeamInviteRequest(company_slug="acme"),
                user=_user(email="new@acme.com"),
                ctx=_ctx(role="company_admin", company_id=B),
            ))
        assert exc.value.status_code == 400

    def test_unknown_company_404(self, monkeypatch):
        sb = self._sb()
        monkeypatch.setattr("app.routers.team.get_supabase", lambda: sb)
        with pytest.raises(HTTPException) as exc:
            _run(accept_team_invite(
                AcceptTeamInviteRequest(company_slug="nope"),
                user=_user(email="new@acme.com"), ctx=_ctx(role="user", company_id=None),
            ))
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Members listing
# ---------------------------------------------------------------------------

class TestGetTeam:
    def test_lists_members_and_pending(self, monkeypatch):
        sb = _supabase(
            profiles=[
                {"id": ADMIN, "email": "admin@acme.com", "full_name": "Admin", "role": "company_admin", "company_id": A},
                {"id": "44444444-4444-4444-4444-444444444444", "email": "rec@acme.com", "full_name": None, "role": "recruiter", "company_id": A},
                {"id": "66666666-6666-6666-6666-666666666666", "email": "c@acme.com", "full_name": None, "role": "user", "company_id": A},
                {"id": "77777777-7777-7777-7777-777777777777", "email": "o@b.com", "full_name": None, "role": "recruiter", "company_id": B},
            ],
            team_invitations=[
                {"id": INV1, "company_id": A, "email": "pending@acme.com", "role": "recruiter",
                 "status": "pending", "invited_by": ADMIN, "created_at": "2026-06-13T00:00:00Z"},
                {"id": "inv-rev", "company_id": A, "email": "rev@acme.com", "role": "recruiter",
                 "status": "revoked", "invited_by": ADMIN, "created_at": "2026-06-13T00:00:00Z"},
            ],
        )
        monkeypatch.setattr("app.routers.team.get_supabase", lambda: sb)
        result = _run(get_team(ctx=_ctx(company_id=A)))
        member_emails = {m.email for m in result.members}
        # Only hiring roles of company A (not the candidate, not company B).
        assert member_emails == {"admin@acme.com", "rec@acme.com"}
        # Only pending invitations.
        assert [i.email for i in result.invitations] == ["pending@acme.com"]
