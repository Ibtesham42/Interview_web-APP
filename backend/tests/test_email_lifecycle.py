"""Tests for the ADR 0012 email delivery lifecycle (migration 010):
suppression, idempotency, per-tenant rate limiting, tenant send identity,
and the Svix-verified Resend webhook ingester.

These exercise the new pre-send guards in `services/email.py` and the event
ingestion in `routers/webhooks.py` against a richer in-memory Supabase fake
than test_email.py's insert-only chain — this one supports select/eq/gte/
insert/update + count + the unique constraints the logic relies on.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict, List, Optional

import pytest

from app.config import get_settings
from app.services import email as email_svc


# ---------------------------------------------------------------------------
# In-memory Supabase fake
# ---------------------------------------------------------------------------

class _DupError(Exception):
    """Mimics a Postgres unique-violation as surfaced by PostgREST."""


class _Resp:
    def __init__(self, data: List[Dict[str, Any]], count: Optional[int] = None):
        self.data = data
        self.count = count


class _Query:
    def __init__(self, store: Dict[str, List[Dict[str, Any]]], name: str):
        self._store = store
        self._name = name
        self._action = "select"
        self._payload: Any = None
        self._filters: List[tuple] = []
        self._count_exact = False

    # builder ---------------------------------------------------------------
    def select(self, *_cols, count=None):
        self._action = "select"
        self._count_exact = count == "exact"
        return self

    def insert(self, payload):
        self._action, self._payload = "insert", payload
        return self

    def update(self, payload):
        self._action, self._payload = "update", payload
        return self

    def eq(self, col, val):
        self._filters.append((col, "eq", val))
        return self

    def gte(self, col, val):
        self._filters.append((col, "gte", val))
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, _n):
        return self

    # execution -------------------------------------------------------------
    def _rows(self) -> List[Dict[str, Any]]:
        return self._store.setdefault(self._name, [])

    def _match(self, row) -> bool:
        for col, op, val in self._filters:
            cell = row.get(col)
            if op == "eq" and str(cell) != str(val):
                return False
            if op == "gte" and (cell is None or not (cell >= val)):
                return False
        return True

    def _enforce_unique(self, item):
        if self._name == "email_suppressions":
            addr = (item.get("email") or "").lower()
            if any((r.get("email") or "").lower() == addr for r in self._rows()):
                raise _DupError("duplicate key value violates unique constraint")
        if self._name == "email_events":
            sid = item.get("svix_id")
            if sid and any(r.get("svix_id") == sid for r in self._rows()):
                raise _DupError("duplicate key value violates unique constraint")

    def execute(self):
        rows = self._rows()
        if self._action == "insert":
            items = self._payload if isinstance(self._payload, list) else [self._payload]
            out = []
            for it in items:
                self._enforce_unique(it)
                row = {"id": it.get("id") or f"{self._name}-{len(rows) + 1}", **it}
                rows.append(row)
                out.append(row)
            return _Resp(out)
        if self._action == "update":
            matched = [r for r in rows if self._match(r)]
            for r in matched:
                r.update(self._payload)
            return _Resp(matched)
        matched = [r for r in rows if self._match(r)]
        if self._count_exact:
            return _Resp(matched, count=len(matched))
        return _Resp(matched)


class _FakeSupabase:
    def __init__(self, store: Optional[Dict[str, List[Dict[str, Any]]]] = None):
        self.store = store if store is not None else {}

    def table(self, name):
        return _Query(self.store, name)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Suppression
# ---------------------------------------------------------------------------

class TestSuppression:
    def test_suppressed_recipient_is_not_sent(self, monkeypatch):
        monkeypatch.setenv("RESEND_API_KEY", "test-key")

        async def explode(*_a, **_kw):
            raise AssertionError("network must not be hit for a suppressed address")

        monkeypatch.setattr(email_svc, "_post_to_resend", explode)

        sb = _FakeSupabase({
            "email_suppressions": [
                {"id": "s1", "email": "bounced@example.com", "reason": "bounce"}
            ]
        })
        row = _run(email_svc.send(
            sb, company_id="c-1", candidate_id="cand-1", sender_id="rec-1",
            to="Bounced@Example.com", subject="hi", body="b",
        ))
        assert row["status"] == "suppressed"
        assert "suppressed" in row["error_message"].lower()
        # The audit row is still written.
        assert sb.store["email_outbox"][0]["status"] == "suppressed"

    def test_record_suppression_is_idempotent(self):
        sb = _FakeSupabase()
        email_svc.record_suppression(sb, email="x@y.com", reason="bounce")
        email_svc.record_suppression(sb, email="X@Y.com", reason="complaint")
        # Second insert is a duplicate (lower(email)) and swallowed.
        assert len(sb.store["email_suppressions"]) == 1


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_replays_prior_row_without_second_send(self, monkeypatch):
        monkeypatch.setenv("RESEND_API_KEY", "test-key")
        calls = {"n": 0}

        async def fake_post(api_key, payload, idempotency_key=None):
            calls["n"] += 1
            return {"id": f"re_{calls['n']}"}

        monkeypatch.setattr(email_svc, "_post_to_resend", fake_post)

        sb = _FakeSupabase()
        first = _run(email_svc.send(
            sb, company_id="c-1", candidate_id="cand-1", sender_id="rec-1",
            to="a@b.com", subject="s", body="b", idempotency_key="key-123",
        ))
        second = _run(email_svc.send(
            sb, company_id="c-1", candidate_id="cand-1", sender_id="rec-1",
            to="a@b.com", subject="s", body="b", idempotency_key="key-123",
        ))
        assert calls["n"] == 1                     # network hit exactly once
        assert second["id"] == first["id"]         # same outbox row returned
        assert len(sb.store["email_outbox"]) == 1  # no duplicate audit row


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

class TestRateLimit:
    def test_raises_when_over_limit(self, monkeypatch):
        monkeypatch.setenv("RESEND_API_KEY", "test-key")
        monkeypatch.setenv("EMAIL_RATE_LIMIT_PER_HOUR", "2")

        # Two recent sends already on the books (far-future sent_at so the
        # rolling-hour >= comparison always counts them).
        sb = _FakeSupabase({
            "email_outbox": [
                {"id": "o1", "company_id": "c-1", "sent_at": "2099-01-01T00:00:00+00:00"},
                {"id": "o2", "company_id": "c-1", "sent_at": "2099-01-01T00:00:00+00:00"},
            ]
        })
        with pytest.raises(email_svc.EmailRateLimited):
            _run(email_svc.send(
                sb, company_id="c-1", candidate_id=None, sender_id="rec-1",
                to="a@b.com", subject="s", body="b",
            ))

    def test_other_tenant_not_affected(self, monkeypatch):
        monkeypatch.setenv("RESEND_API_KEY", "test-key")
        monkeypatch.setenv("EMAIL_RATE_LIMIT_PER_HOUR", "2")

        async def fake_post(api_key, payload, idempotency_key=None):
            return {"id": "re_x"}

        monkeypatch.setattr(email_svc, "_post_to_resend", fake_post)

        sb = _FakeSupabase({
            "email_outbox": [
                {"id": "o1", "company_id": "c-1", "sent_at": "2099-01-01T00:00:00+00:00"},
                {"id": "o2", "company_id": "c-1", "sent_at": "2099-01-01T00:00:00+00:00"},
            ]
        })
        # Company c-2 has no history — its send goes through.
        row = _run(email_svc.send(
            sb, company_id="c-2", candidate_id=None, sender_id="rec-1",
            to="a@b.com", subject="s", body="b",
        ))
        assert row["status"] == "sent"


# ---------------------------------------------------------------------------
# Tenant send identity
# ---------------------------------------------------------------------------

class TestSendIdentity:
    def test_from_is_tenant_branded_and_reply_to_set(self, monkeypatch):
        monkeypatch.setenv("RESEND_API_KEY", "test-key")
        monkeypatch.setenv("RESEND_FROM_EMAIL", "noreply@platform.com")
        monkeypatch.setenv("PLATFORM_FROM_NAME", "Rehearsify")
        captured = {}

        async def fake_post(api_key, payload, idempotency_key=None):
            captured.update(payload)
            return {"id": "re_x"}

        monkeypatch.setattr(email_svc, "_post_to_resend", fake_post)

        sb = _FakeSupabase()
        _run(email_svc.send(
            sb, company_id="c-1", candidate_id="cand-1", sender_id="rec-1",
            to="a@b.com", subject="s", body="b",
            from_name="Acme", reply_to="hiring@acme.com",
        ))
        assert captured["from"] == '"Acme via Rehearsify" <noreply@platform.com>'
        assert captured["reply_to"] == "hiring@acme.com"

    def test_from_falls_back_to_bare_address_without_name(self, monkeypatch):
        monkeypatch.setenv("RESEND_FROM_EMAIL", "noreply@platform.com")
        assert email_svc._build_from(None) == "noreply@platform.com"
        assert email_svc._build_from("") == "noreply@platform.com"


# ---------------------------------------------------------------------------
# Webhook: signature verification
# ---------------------------------------------------------------------------

def _sign(secret_b64_key: bytes, svix_id: str, ts: str, body: bytes) -> str:
    signed = b"%s.%s.%s" % (svix_id.encode(), ts.encode(), body)
    sig = base64.b64encode(
        hmac.new(secret_b64_key, signed, hashlib.sha256).digest()
    ).decode()
    return f"v1,{sig}"


class TestWebhookSignature:
    def _setup(self):
        from app.routers import webhooks
        raw_key = b"super-secret-key-bytes"
        secret = "whsec_" + base64.b64encode(raw_key).decode()
        return webhooks, raw_key, secret

    def test_valid_signature_accepted(self):
        webhooks, raw_key, secret = self._setup()
        body = b'{"type":"email.delivered"}'
        svix_id, ts = "msg_1", str(int(time.time()))
        headers = {
            "svix-id": svix_id,
            "svix-timestamp": ts,
            "svix-signature": _sign(raw_key, svix_id, ts, body),
        }
        assert webhooks._verify_svix_signature(secret, headers, body) is True

    def test_tampered_body_rejected(self):
        webhooks, raw_key, secret = self._setup()
        svix_id, ts = "msg_1", str(int(time.time()))
        sig = _sign(raw_key, svix_id, ts, b'{"type":"email.delivered"}')
        headers = {"svix-id": svix_id, "svix-timestamp": ts, "svix-signature": sig}
        # Different body than what was signed.
        assert webhooks._verify_svix_signature(secret, headers, b'{"type":"email.bounced"}') is False

    def test_stale_timestamp_rejected(self):
        webhooks, raw_key, secret = self._setup()
        body = b"{}"
        svix_id, ts = "msg_1", str(int(time.time()) - 10_000)  # outside tolerance
        headers = {
            "svix-id": svix_id,
            "svix-timestamp": ts,
            "svix-signature": _sign(raw_key, svix_id, ts, body),
        }
        assert webhooks._verify_svix_signature(secret, headers, body) is False

    def test_missing_headers_rejected(self):
        webhooks, _raw, secret = self._setup()
        assert webhooks._verify_svix_signature(secret, {}, b"{}") is False


# ---------------------------------------------------------------------------
# Webhook: status precedence ladder
# ---------------------------------------------------------------------------

class TestStatusPrecedence:
    def test_advance_only_forward(self):
        from app.routers import webhooks
        # delivered outranks sent
        assert webhooks._advance_status("sent", "delivered") == "delivered"
        # a late 'sent' never clobbers 'delivered'
        assert webhooks._advance_status("delivered", "sent") is None
        # bounce outranks delivered (a real delivery problem must surface)
        assert webhooks._advance_status("delivered", "bounced") == "bounced"
        # informational event => no change
        assert webhooks._advance_status("sent", None) is None


# ---------------------------------------------------------------------------
# Webhook: end-to-end ingestion (bounce -> suppression + status)
# ---------------------------------------------------------------------------

class _FakeRequest:
    def __init__(self, headers: Dict[str, str], body: bytes):
        self.headers = headers
        self._body = body

    async def body(self) -> bytes:
        return self._body


class TestWebhookIngestion:
    def test_bounce_updates_status_and_suppresses(self, monkeypatch):
        from app.routers import webhooks

        raw_key = b"webhook-key"
        secret = "whsec_" + base64.b64encode(raw_key).decode()
        monkeypatch.setenv("RESEND_WEBHOOK_SECRET", secret)
        get_settings.cache_clear()

        sb = _FakeSupabase({
            "email_outbox": [
                {"id": "o1", "company_id": "c-1", "to_email": "a@b.com",
                 "status": "sent", "resend_message_id": "re_1"}
            ]
        })
        monkeypatch.setattr(webhooks, "get_supabase", lambda: sb)

        event = {
            "type": "email.bounced",
            "created_at": "2026-06-10T00:00:00Z",
            "data": {"email_id": "re_1", "to": ["a@b.com"]},
        }
        body = json.dumps(event).encode()
        svix_id, ts = "evt_1", str(int(time.time()))
        req = _FakeRequest(
            {
                "svix-id": svix_id,
                "svix-timestamp": ts,
                "svix-signature": _sign(raw_key, svix_id, ts, body),
            },
            body,
        )

        resp = _run(webhooks.resend_webhook(req))
        assert resp.status_code == 200

        # Outbox row advanced to bounced.
        assert sb.store["email_outbox"][0]["status"] == "bounced"
        # Recipient suppressed.
        assert sb.store["email_suppressions"][0]["email"] == "a@b.com"
        # Event recorded.
        assert sb.store["email_events"][0]["event_type"] == "email.bounced"

    def test_duplicate_svix_id_is_noop(self, monkeypatch):
        from app.routers import webhooks

        raw_key = b"webhook-key"
        secret = "whsec_" + base64.b64encode(raw_key).decode()
        monkeypatch.setenv("RESEND_WEBHOOK_SECRET", secret)
        get_settings.cache_clear()

        sb = _FakeSupabase({
            "email_events": [{"id": "e0", "svix_id": "dup_1"}],
        })
        monkeypatch.setattr(webhooks, "get_supabase", lambda: sb)

        event = {"type": "email.delivered", "data": {"email_id": "re_9"}}
        body = json.dumps(event).encode()
        ts = str(int(time.time()))
        req = _FakeRequest(
            {
                "svix-id": "dup_1",
                "svix-timestamp": ts,
                "svix-signature": _sign(raw_key, "dup_1", ts, body),
            },
            body,
        )
        resp = _run(webhooks.resend_webhook(req))
        assert resp.status_code == 200
        # No new event row appended.
        assert len(sb.store["email_events"]) == 1

    def test_unsigned_when_secret_missing_is_rejected(self, monkeypatch):
        from app.routers import webhooks

        monkeypatch.setenv("RESEND_WEBHOOK_SECRET", "")
        get_settings.cache_clear()
        monkeypatch.setattr(webhooks, "get_supabase", lambda: _FakeSupabase())

        req = _FakeRequest({}, b"{}")
        resp = _run(webhooks.resend_webhook(req))
        assert resp.status_code == 503  # fail closed
