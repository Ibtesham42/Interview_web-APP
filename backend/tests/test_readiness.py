"""Tests for the startup readiness policy (app/readiness.py).

`check_readiness` is pure, so the whole fatal/warning matrix is exercised
here with settings-like stubs — no environment, no server boot needed.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.readiness import (
    ReadinessError,
    assert_ready,
    check_readiness,
)


def _settings(**over):
    base = dict(
        environment="development",
        groq_api_key="gsk_real_key",
        supabase_url="https://abc.supabase.co",
        supabase_key="service_role_key",
        frontend_base_url="https://app.example.com",
        frontend_origins="https://app.example.com",
        frontend_origin_regex="",
        resend_api_key="re_real_key",
    )
    base.update(over)
    return SimpleNamespace(**base)


class TestFatal:
    def test_fully_configured_has_no_issues(self):
        fatal, warnings = check_readiness(_settings())
        assert fatal == []
        assert warnings == []

    def test_missing_groq_is_fatal(self):
        fatal, _ = check_readiness(_settings(groq_api_key=""))
        assert any("GROQ_API_KEY" in m for m in fatal)

    def test_missing_supabase_url_and_key_both_fatal(self):
        fatal, _ = check_readiness(_settings(supabase_url="", supabase_key=""))
        assert any("SUPABASE_URL" in m for m in fatal)
        assert any("SUPABASE_KEY" in m for m in fatal)

    def test_placeholder_values_treated_as_missing(self):
        fatal, _ = check_readiness(_settings(
            groq_api_key="gsk_your-key-here",
            supabase_url="https://your-project.supabase.co",
            supabase_key="sbp_your_key_here",
        ))
        assert len(fatal) == 3

    def test_localhost_frontend_base_url_fatal_in_production(self):
        fatal, _ = check_readiness(_settings(
            environment="production",
            frontend_base_url="http://localhost:3000",
        ))
        assert any("FRONTEND_BASE_URL" in m for m in fatal)

    def test_localhost_frontend_base_url_only_warns_in_dev(self):
        fatal, warnings = check_readiness(_settings(
            environment="development",
            frontend_base_url="http://localhost:3000",
        ))
        assert not any("FRONTEND_BASE_URL" in m for m in fatal)
        assert any("FRONTEND_BASE_URL" in m for m in warnings)


class TestWarnings:
    def test_wildcard_cors_warns(self):
        _, warnings = check_readiness(_settings(
            frontend_origins="",
            frontend_origin_regex=r"https://.*\.vercel\.app",
        ))
        assert any("CORS is wide open" in m for m in warnings)

    def test_explicit_origins_suppresses_cors_warning(self):
        _, warnings = check_readiness(_settings(
            frontend_origins="https://app.example.com",
            frontend_origin_regex=r"https://.*\.vercel\.app",
        ))
        assert not any("CORS" in m for m in warnings)

    def test_missing_resend_warns_not_fatal(self):
        fatal, warnings = check_readiness(_settings(resend_api_key=""))
        assert fatal == []
        assert any("RESEND_API_KEY" in m for m in warnings)


class TestAssertReady:
    def test_raises_on_fatal(self):
        logs = []
        with pytest.raises(ReadinessError):
            assert_ready(_settings(groq_api_key=""), log=logs.append)
        # The report is logged before the raise, so a misconfigured boot
        # shows the actionable message, not just a traceback.
        assert any("GROQ_API_KEY" in line for line in logs)

    def test_passes_with_warnings_only(self):
        logs = []
        # Warnings present (no resend) but nothing fatal — must not raise.
        assert_ready(_settings(resend_api_key=""), log=logs.append)
        assert any("RESEND_API_KEY" in line for line in logs)

    def test_silent_when_fully_ready(self):
        logs = []
        assert_ready(_settings(), log=logs.append)
        assert logs == []
