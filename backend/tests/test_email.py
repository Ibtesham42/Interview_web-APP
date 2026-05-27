"""Tests for the email service + templates (multi-tenant PR 6).

Two surfaces:
1. `services/email_templates.py` — pure-logic template renderers.
   Verified by passing candidate/company dicts and asserting the
   subject + body shape. No mocks needed.
2. `services/email.py::send` — Resend HTTP wrapper + outbox writer.
   The Resend POST is stubbed via monkeypatching the inner thread
   call so tests never hit the network. The outbox insert uses the
   same _Chain fake from test_companies.py.

`list_for_candidate` is exercised in PR 7's recruiter endpoint tests
(it's a thin SELECT helper; the filter-aware fake already covers it
elsewhere in the suite).
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from app.services import email as email_svc
from app.services.email_templates import (
    default_rejection_template,
    default_shortlist_template,
)


# ---------------------------------------------------------------------------
# Templates — pure logic
# ---------------------------------------------------------------------------

class TestShortlistTemplate:
    def test_uses_first_name_and_company_name(self):
        out = default_shortlist_template(
            candidate={"name": "Alice Smith", "email": "alice@example.com"},
            company={"name": "Acme"},
        )
        assert "Hi Alice," in out["body"]
        assert "Acme" in out["subject"]
        assert "Acme" in out["body"]

    def test_missing_candidate_name_falls_back(self):
        """Resume parser sometimes leaves `name` blank — template
        falls back to a neutral greeting rather than 'Hi ,'."""
        out = default_shortlist_template(
            candidate={"name": "", "email": "x@example.com"},
            company={"name": "Acme"},
        )
        assert "Hi there," in out["body"]

    def test_missing_company_name_falls_back(self):
        out = default_shortlist_template(
            candidate={"name": "Alice", "email": "x@example.com"},
            company={"name": ""},
        )
        # 'our team' is the fallback wording.
        assert "our team" in out["body"]
        assert "our team" in out["subject"]

    def test_single_word_name_returns_intact(self):
        """A name with no space ('Cher', 'Madonna') still works as a
        first-name fallback — the splitter returns the whole string."""
        out = default_shortlist_template(
            candidate={"name": "Cher", "email": "x@example.com"},
            company={"name": "Acme"},
        )
        assert "Hi Cher," in out["body"]


class TestRejectionTemplate:
    def test_is_respectful_and_neutral(self):
        out = default_rejection_template(
            candidate={"name": "Alice Smith"},
            company={"name": "Acme"},
        )
        assert "Alice" in out["body"]
        assert "Acme" in out["body"]
        # Sanity check: no over-feedback language that would invite a
        # back-and-forth — keep the templated body neutral.
        assert "specific" not in out["body"].lower()


# ---------------------------------------------------------------------------
# email.send — outbox persistence + Resend stub
# ---------------------------------------------------------------------------

class _OutboxChain:
    """Smallest possible insert-only fake for the email_outbox table.
    Captures the inserted payload for assertions and returns it via
    `.execute().data`."""

    def __init__(self, store: Dict[str, List[Dict[str, Any]]]):
        self._store = store
        self._payload: Optional[Dict[str, Any]] = None

    def insert(self, payload):
        self._payload = payload
        return self

    def execute(self):
        row = {"id": "outbox-1", **self._payload}
        self._store.setdefault("email_outbox", []).append(row)
        resp = MagicMock()
        resp.data = [row]
        return resp


def _fake_supabase():
    store: Dict[str, List[Dict[str, Any]]] = {}
    supabase = MagicMock()
    supabase.table.side_effect = lambda name: _OutboxChain(store) if name == "email_outbox" else None
    supabase._store = store
    return supabase


def _run(coro):
    return asyncio.run(coro)


class TestSend:
    def test_sent_when_api_key_present_and_http_ok(self, monkeypatch):
        # Stub the network: pretend Resend accepted the message.
        async def fake_post(api_key, payload):
            assert payload["from"] == "noreply@acme.com"
            assert payload["to"] == ["alice@example.com"]
            return {"id": "re_abc123"}

        # Wire a key into settings so the disabled branch doesn't fire.
        from app.config import get_settings
        get_settings.cache_clear()
        monkeypatch.setenv("RESEND_API_KEY", "test-key")
        monkeypatch.setenv("RESEND_FROM_EMAIL", "noreply@acme.com")
        monkeypatch.setattr(email_svc, "_post_to_resend", fake_post)

        supabase = _fake_supabase()
        row = _run(email_svc.send(
            supabase,
            company_id="c-1",
            candidate_id="cand-1",
            sender_id="rec-1",
            to="alice@example.com",
            subject="Next steps",
            body="Hi Alice,\n\nGreat interview.",
        ))

        assert row["status"] == "sent"
        assert row["resend_message_id"] == "re_abc123"
        assert row["error_message"] is None
        assert supabase._store["email_outbox"][0]["status"] == "sent"
        get_settings.cache_clear()

    def test_failed_status_when_resend_raises(self, monkeypatch):
        async def fake_post(api_key, payload):
            raise RuntimeError("connection refused")

        from app.config import get_settings
        get_settings.cache_clear()
        monkeypatch.setenv("RESEND_API_KEY", "test-key")
        monkeypatch.setattr(email_svc, "_post_to_resend", fake_post)

        supabase = _fake_supabase()
        row = _run(email_svc.send(
            supabase,
            company_id="c-1",
            candidate_id="cand-1",
            sender_id="rec-1",
            to="alice@example.com",
            subject="Next steps",
            body="Hi.",
        ))

        # Critical invariant: failure does NOT raise. Outbox row is
        # still written with status='failed' so the audit trail is
        # never silently lost.
        assert row["status"] == "failed"
        assert row["resend_message_id"] is None
        assert "RuntimeError" in row["error_message"]
        get_settings.cache_clear()

    def test_disabled_mode_when_no_api_key(self, monkeypatch):
        """Empty RESEND_API_KEY writes a failed-outbox row without
        ever calling the network. Sentinel string lets the UI surface
        a clear 'email not configured' state to the recruiter."""
        from app.config import get_settings
        get_settings.cache_clear()
        monkeypatch.setenv("RESEND_API_KEY", "")

        # Stub _post_to_resend to a sentinel that would fail loudly if
        # it accidentally got called — proving the disabled branch
        # short-circuits before the network.
        async def explode(*_a, **_kw):
            raise AssertionError("Resend HTTP should not be called in disabled mode")

        monkeypatch.setattr(email_svc, "_post_to_resend", explode)

        supabase = _fake_supabase()
        row = _run(email_svc.send(
            supabase,
            company_id="c-1",
            candidate_id="cand-1",
            sender_id="rec-1",
            to="alice@example.com",
            subject="s",
            body="b",
        ))
        assert row["status"] == "failed"
        assert "not configured" in row["error_message"].lower()
        get_settings.cache_clear()
