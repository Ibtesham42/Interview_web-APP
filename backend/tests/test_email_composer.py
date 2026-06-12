"""Tests for the email-composer improvements (2026-06-12).

Covers:
- Deliverability rules on all three default templates: professional
  subjects (no all-caps, no emojis), company name + clear purpose,
  reply line, contact footer that renders only what's on file.
- `render_email_html` — escape-first plain-text→HTML derivation
  (hostile content never becomes markup; apply links become anchors).
- `email.send` ships multipart text+HTML derived from the same body.
- Editable invites: GET /companies/invite/draft renders the template;
  POST /companies/invite honours edited subject/body and defaults
  field-by-field when absent.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from app.auth import TenantContext
from app.models.schemas import InviteCandidateRequest
from app.routers.companies import invite_candidate, invite_draft
from app.services import email as email_svc
from app.services.email_templates import (
    default_invite_template,
    default_rejection_template,
    default_shortlist_template,
    render_email_html,
)

COMPANY = {
    "id": "c-1", "slug": "acme", "name": "Acme Inc.",
    "email": "talent@acme.com", "phone": "+1 555 0100",
    "address": "1 Acme Way, Springfield",
}

_EMOJI_RANGES = ((0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2190, 0x21FF))


def _has_emoji(text: str) -> bool:
    return any(lo <= ord(ch) <= hi for ch in text for lo, hi in _EMOJI_RANGES)


def _all_templates():
    return [
        ("invite", default_invite_template(
            company=COMPANY, candidate_name="Alice Smith",
            apply_url="https://app.example.com/apply/acme")),
        ("shortlist", default_shortlist_template(
            candidate={"name": "Alice Smith"}, company=COMPANY)),
        ("rejection", default_rejection_template(
            candidate={"name": "Alice Smith"}, company=COMPANY)),
    ]


class TestDeliverabilityRules:
    @pytest.mark.parametrize("kind,out", _all_templates())
    def test_subject_is_not_all_caps_and_names_the_company(self, kind, out):
        subject = out["subject"]
        assert subject != subject.upper(), f"{kind}: all-caps subject"
        assert "Acme Inc." in subject, f"{kind}: subject must carry the company"
        assert "!" not in subject, f"{kind}: no urgency punctuation"

    @pytest.mark.parametrize("kind,out", _all_templates())
    def test_no_emojis_anywhere(self, kind, out):
        assert not _has_emoji(out["subject"] + out["body"]), kind

    @pytest.mark.parametrize("kind,out", _all_templates())
    def test_body_has_reply_line_and_contact_footer(self, kind, out):
        body = out["body"]
        assert "reply to this email" in body, f"{kind}: reply info missing"
        assert "talent@acme.com" in body, f"{kind}: contact email missing"
        assert "+1 555 0100" in body, f"{kind}: contact phone missing"
        assert "1 Acme Way, Springfield" in body, f"{kind}: address missing"

    def test_invite_states_purpose_and_carries_apply_link(self):
        out = default_invite_template(
            company=COMPANY, candidate_name="Alice",
            apply_url="https://app.example.com/apply/acme",
        )
        body = out["body"]
        assert "https://app.example.com/apply/acme" in body
        # Purpose is stated in the first paragraph, not buried.
        first_paragraph = body.split("\n\n")[1]
        assert "interview" in first_paragraph.lower()
        assert "hiring process" in first_paragraph.lower()

    def test_footer_renders_only_fields_on_file(self):
        sparse = {"name": "Acme Inc.", "email": "talent@acme.com"}
        out = default_shortlist_template(candidate={"name": "A"}, company=sparse)
        assert "talent@acme.com" in out["body"]
        assert "None" not in out["body"]
        # No dangling separators for the absent phone.
        assert " | \n" not in out["body"] and not out["body"].endswith("| ")


class TestRenderEmailHtml:
    def test_hostile_content_is_escaped_not_executed(self):
        html = render_email_html("Hi <script>alert(1)</script> & <b>bold</b>")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "<b>" not in html

    def test_urls_become_anchors(self):
        html = render_email_html("Start here:\nhttps://app.example.com/apply/acme")
        assert '<a href="https://app.example.com/apply/acme"' in html

    def test_url_with_query_ampersand_is_attribute_encoded(self):
        html = render_email_html("https://x.example.com/a?b=1&c=2")
        assert '<a href="https://x.example.com/a?b=1&amp;c=2"' in html

    def test_paragraphs_and_line_breaks(self):
        html = render_email_html("Para one\nstill one\n\nPara two")
        assert html.count("<p ") == 2
        assert "still one" in html and "<br/>" in html

    def test_no_images_or_tracking_markup(self):
        out = default_invite_template(
            company=COMPANY, candidate_name="A", apply_url="https://x.example.com/a")
        html = render_email_html(out["body"])
        assert "<img" not in html and "<table" not in html


class _OutboxChain:
    def __init__(self, store):
        self._store = store
        self._payload = None

    def insert(self, payload):
        self._payload = payload
        return self

    def execute(self):
        row = {"id": "outbox-1", **self._payload}
        self._store.setdefault("email_outbox", []).append(row)
        resp = MagicMock()
        resp.data = [row]
        return resp


def _run(coro):
    return asyncio.run(coro)


class TestSendMultipart:
    def test_payload_carries_text_and_matching_html(self, monkeypatch):
        captured: Dict[str, Any] = {}

        async def fake_post(api_key, payload, idempotency_key=None):
            captured.update(payload)
            return {"id": "re_1"}

        from app.config import get_settings
        get_settings.cache_clear()
        monkeypatch.setenv("RESEND_API_KEY", "test-key")
        monkeypatch.setenv("RESEND_FROM_EMAIL", "noreply@acme.com")
        monkeypatch.setattr(email_svc, "_post_to_resend", fake_post)

        store: Dict[str, List] = {}
        supabase = MagicMock()
        supabase.table.side_effect = (
            lambda name: _OutboxChain(store) if name == "email_outbox" else None
        )

        body = "Hi Alice,\n\nVisit https://x.example.com/apply/acme"
        _run(email_svc.send(
            supabase, company_id="c-1", candidate_id=None, sender_id="u-1",
            to="alice@example.com", subject="Next steps", body=body,
        ))
        assert captured["text"] == body
        assert '<a href="https://x.example.com/apply/acme"' in captured["html"]
        assert "Hi Alice," in captured["html"]


# ---------------------------------------------------------------------------
# Editable invites — draft endpoint + subject/body overrides
# ---------------------------------------------------------------------------

class _SelectChain:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_a, **_kw):
        return self

    def eq(self, col, val):
        self._rows = [r for r in self._rows if r.get(col) == val]
        return self

    def execute(self):
        resp = MagicMock()
        resp.data = list(self._rows)
        return resp


def _company_supabase():
    supabase = MagicMock()
    supabase.table.side_effect = lambda name: _SelectChain(
        [dict(COMPANY)] if name == "companies" else []
    )
    return supabase


def _ctx(company_id="c-1"):
    return TenantContext(user_id="u-1", role="company_admin", company_id=company_id)


def _patch_invite(monkeypatch, sent: Dict[str, Any]):
    monkeypatch.setattr("app.routers.companies.get_supabase", _company_supabase)
    monkeypatch.setattr(
        "app.routers.companies.upsert_invitation", lambda *a, **kw: None
    )

    async def fake_send(_supabase, **kwargs):
        sent.update(kwargs)
        return {
            "id": "11111111-1111-1111-1111-111111111111",
            "to_email": kwargs["to"], "subject": kwargs["subject"],
            "status": "sent", "error_message": None,
            "sent_at": "2026-06-12T10:00:00+00:00",
        }

    monkeypatch.setattr("app.routers.companies.email_svc.send", fake_send)


class TestInviteDraft:
    def test_renders_template_with_apply_link_and_footer(self, monkeypatch):
        monkeypatch.setattr("app.routers.companies.get_supabase", _company_supabase)
        result = _run(invite_draft(
            to_email="cand@example.com", candidate_name="Alice", ctx=_ctx(),
        ))
        assert result.to == "cand@example.com"
        assert "Acme Inc." in result.subject
        assert "/apply/acme" in result.body
        assert "talent@acme.com" in result.body  # footer present in the draft

    def test_requires_a_company(self, monkeypatch):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            _run(invite_draft(to_email="x@x.com", candidate_name="", ctx=_ctx(None)))
        assert exc.value.status_code == 400


class TestInviteOverrides:
    def test_edited_subject_and_body_are_sent_verbatim(self, monkeypatch):
        sent: Dict[str, Any] = {}
        _patch_invite(monkeypatch, sent)
        _run(invite_candidate(
            InviteCandidateRequest(
                to_email="cand@example.com", candidate_name="Alice",
                subject="A custom subject", body="A fully edited body.",
            ),
            ctx=_ctx(),
        ))
        assert sent["subject"] == "A custom subject"
        assert sent["body"] == "A fully edited body."

    def test_omitted_fields_fall_back_to_template(self, monkeypatch):
        sent: Dict[str, Any] = {}
        _patch_invite(monkeypatch, sent)
        _run(invite_candidate(
            InviteCandidateRequest(to_email="cand@example.com", candidate_name="Alice"),
            ctx=_ctx(),
        ))
        assert "Acme Inc." in sent["subject"]
        assert "/apply/acme" in sent["body"]

    def test_subject_only_override_keeps_template_body(self, monkeypatch):
        sent: Dict[str, Any] = {}
        _patch_invite(monkeypatch, sent)
        _run(invite_candidate(
            InviteCandidateRequest(
                to_email="cand@example.com", subject="Custom subject only",
            ),
            ctx=_ctx(),
        ))
        assert sent["subject"] == "Custom subject only"
        assert "/apply/acme" in sent["body"]
