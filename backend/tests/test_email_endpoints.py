"""Tests for the recruiter email endpoints (multi-tenant PR 7).

Three endpoints, all on `routers/recruiter.py`:
- `GET  /candidates/{id}/email/draft` — template-rendered draft.
- `POST /candidates/{id}/email/send`  — sends + records outbox row.
- `GET  /candidates/{id}/emails`      — prior outbox rows.

The stub supabase honours `.eq()` so tenant scoping is verifiable
(matches the pattern from test_tenant_scoping.py). Email service
internals are exercised separately in `test_email.py`; here we
verify the router-level auth + tenant gates and the response
shapes.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.auth import TenantContext
from app.models.schemas import EmailSendRequest
from app.routers import recruiter as recruiter_router
from app.routers.recruiter import email_draft, email_list, email_send


A = str(uuid.uuid4())
B = str(uuid.uuid4())

CANDIDATE_IN_A = "11111111-1111-1111-1111-111111111111"
CANDIDATE_IN_B = "22222222-2222-2222-2222-222222222222"
RECRUITER_ID = "33333333-3333-3333-3333-333333333333"


# ---------------------------------------------------------------------------
# Supabase stub — filter-aware select; insert and order are honoured.
# ---------------------------------------------------------------------------

class _Chain:
    def __init__(self, table: str, store: Dict[str, List[Dict[str, Any]]]):
        self._table = table
        self._store = store
        self._eqs: List = []
        self._mode: Optional[str] = None
        self._payload: Any = None
        self._order_col: Optional[str] = None
        self._order_desc: bool = False

    def select(self, *_a, **_kw):
        self._mode = "select"
        return self

    def eq(self, col, val):
        self._eqs.append((col, val))
        return self

    def order(self, col, desc=False):
        self._order_col = col
        self._order_desc = desc
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
            if self._order_col:
                filtered = sorted(
                    filtered,
                    key=lambda r: r.get(self._order_col) or "",
                    reverse=self._order_desc,
                )
            resp = MagicMock()
            resp.data = list(filtered)
            return resp
        if self._mode == "insert":
            payload = self._payload
            inserted = {**payload}
            inserted.setdefault("id", str(uuid.uuid4()))
            inserted.setdefault("sent_at", "2026-05-27T00:00:00Z")
            rows.append(inserted)
            resp = MagicMock()
            resp.data = [inserted]
            return resp
        raise NotImplementedError(self._mode)


def _supabase(*, candidates=None, companies=None, email_outbox=None):
    store: Dict[str, List[Dict[str, Any]]] = {
        "candidates": list(candidates or []),
        "companies": list(companies or []),
        "email_outbox": list(email_outbox or []),
    }
    supabase = MagicMock()
    supabase.table.side_effect = lambda name: _Chain(name, store)
    supabase._store = store
    return supabase


def _ctx(role="recruiter", company_id=A, user_id=None):
    return TenantContext(
        user_id=user_id or RECRUITER_ID,
        role=role,
        company_id=company_id,
    )


def _run(coro):
    return asyncio.run(coro)


def _two_tenant_supabase():
    return _supabase(
        candidates=[
            {"id": CANDIDATE_IN_A, "name": "Alice Smith",
             "email": "alice@x.com", "company_id": A},
            {"id": CANDIDATE_IN_B, "name": "Bob Jones",
             "email": "bob@x.com", "company_id": B},
        ],
        companies=[
            {"id": A, "slug": "acme", "name": "Acme Inc."},
            {"id": B, "slug": "wayne", "name": "Wayne Enterprises"},
        ],
        email_outbox=[
            # One historic email for candidate A so the list endpoint
            # has something to surface.
            {"id": str(uuid.uuid4()), "candidate_id": CANDIDATE_IN_A,
             "company_id": A, "sender_id": RECRUITER_ID,
             "to_email": "alice@x.com", "subject": "Welcome",
             "body": "Hi", "status": "sent", "resend_message_id": "re_1",
             "error_message": None, "sent_at": "2026-05-26T10:00:00Z"},
        ],
    )


# ---------------------------------------------------------------------------
# GET /email/draft
# ---------------------------------------------------------------------------

class TestEmailDraft:
    def test_returns_template_rendered_draft(self, monkeypatch):
        supabase = _two_tenant_supabase()
        monkeypatch.setattr(
            "app.routers.recruiter.get_supabase", lambda: supabase
        )
        result = _run(email_draft(uuid.UUID(CANDIDATE_IN_A), user=_ctx()))
        assert result.to == "alice@x.com"
        assert "Alice" in result.body
        assert "Acme" in result.subject

    def test_cross_tenant_candidate_404(self, monkeypatch):
        """Recruiter of A querying a candidate of B should see 404 —
        no existence leak across tenants."""
        supabase = _two_tenant_supabase()
        monkeypatch.setattr(
            "app.routers.recruiter.get_supabase", lambda: supabase
        )
        with pytest.raises(HTTPException) as exc:
            _run(email_draft(uuid.UUID(CANDIDATE_IN_B), user=_ctx(company_id=A)))
        assert exc.value.status_code == 404

    def test_rejection_template_returns_decline_copy(self, monkeypatch):
        """template='rejection' renders the courtesy-decline copy instead
        of the shortlist congrats (candidate status management)."""
        supabase = _two_tenant_supabase()
        monkeypatch.setattr(
            "app.routers.recruiter.get_supabase", lambda: supabase
        )
        result = _run(email_draft(
            uuid.UUID(CANDIDATE_IN_A), template="rejection", user=_ctx()
        ))
        assert result.to == "alice@x.com"
        assert "Update on your application" in result.subject
        assert "other candidates" in result.body

    def test_company_admin_cannot_draft_other_tenant(self, monkeypatch):
        """A company_admin of A drafting for a candidate of B gets 404 —
        the 'company admins manage only their own candidates' requirement
        holds on the email path too."""
        supabase = _two_tenant_supabase()
        monkeypatch.setattr(
            "app.routers.recruiter.get_supabase", lambda: supabase
        )
        with pytest.raises(HTTPException) as exc:
            _run(email_draft(
                uuid.UUID(CANDIDATE_IN_B),
                user=_ctx(role="company_admin", company_id=A),
            ))
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# POST /email/send
# ---------------------------------------------------------------------------

class TestEmailSend:
    def _stub_email_service(self, monkeypatch, *, status="sent",
                            resend_id="re_abc", error=None):
        """Replace the email service's send() with a deterministic stub
        that returns a fully-formed outbox row dict (same shape the real
        service would produce). The actual Resend HTTP call is exercised
        in test_email.py."""
        async def fake_send(supabase, **kwargs):
            return {
                "id": str(uuid.uuid4()),
                "to_email": kwargs["to"],
                "subject": kwargs["subject"],
                "body": kwargs["body"],
                "status": status,
                "resend_message_id": resend_id if status == "sent" else None,
                "error_message": error,
                "sent_at": "2026-05-27T00:00:00Z",
                "sender_id": kwargs["sender_id"],
                "company_id": kwargs["company_id"],
                "candidate_id": kwargs["candidate_id"],
            }
        monkeypatch.setattr(
            "app.routers.recruiter.email_svc.send", fake_send
        )

    def test_successful_send_returns_sent_row(self, monkeypatch):
        self._stub_email_service(monkeypatch)
        supabase = _two_tenant_supabase()
        monkeypatch.setattr(
            "app.routers.recruiter.get_supabase", lambda: supabase
        )

        result = _run(email_send(
            uuid.UUID(CANDIDATE_IN_A),
            body=EmailSendRequest(
                to="alice@x.com", subject="Next steps", body="Hi Alice."
            ),
            user=_ctx(),
        ))
        assert result.status == "sent"
        assert result.to_email == "alice@x.com"
        assert result.subject == "Next steps"
        assert result.resend_message_id == "re_abc"

    def test_failed_send_still_returns_row(self, monkeypatch):
        """Resend-rejected sends produce an outbox row with status=failed.
        Critical: endpoint does NOT raise — the row is the audit trail."""
        self._stub_email_service(
            monkeypatch, status="failed", resend_id=None,
            error="connection refused",
        )
        supabase = _two_tenant_supabase()
        monkeypatch.setattr(
            "app.routers.recruiter.get_supabase", lambda: supabase
        )

        result = _run(email_send(
            uuid.UUID(CANDIDATE_IN_A),
            body=EmailSendRequest(
                to="alice@x.com", subject="Next steps", body="Hi."
            ),
            user=_ctx(),
        ))
        assert result.status == "failed"
        assert result.error_message == "connection refused"
        assert result.resend_message_id is None

    def test_cross_tenant_candidate_404(self, monkeypatch):
        """Recruiter of A cannot send to a candidate of B — same 404
        as 'candidate doesn't exist'."""
        # Service stub never gets called since the candidate fetch 404s
        # first — but stub anyway so a regression in the order of
        # operations would surface as the stub returning something
        # rather than a NoneType crash.
        self._stub_email_service(monkeypatch)
        supabase = _two_tenant_supabase()
        monkeypatch.setattr(
            "app.routers.recruiter.get_supabase", lambda: supabase
        )

        with pytest.raises(HTTPException) as exc:
            _run(email_send(
                uuid.UUID(CANDIDATE_IN_B),
                body=EmailSendRequest(
                    to="bob@x.com", subject="Hi", body="Hi"
                ),
                user=_ctx(company_id=A),
            ))
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# GET /emails
# ---------------------------------------------------------------------------

class TestEmailList:
    def test_lists_previous_emails(self, monkeypatch):
        supabase = _two_tenant_supabase()
        monkeypatch.setattr(
            "app.routers.recruiter.get_supabase", lambda: supabase
        )
        result = _run(email_list(uuid.UUID(CANDIDATE_IN_A), user=_ctx()))
        assert len(result.items) == 1
        assert result.items[0].to_email == "alice@x.com"

    def test_cross_tenant_candidate_404(self, monkeypatch):
        supabase = _two_tenant_supabase()
        monkeypatch.setattr(
            "app.routers.recruiter.get_supabase", lambda: supabase
        )
        with pytest.raises(HTTPException) as exc:
            _run(email_list(uuid.UUID(CANDIDATE_IN_B), user=_ctx(company_id=A)))
        assert exc.value.status_code == 404
