"""Startup readiness validation.

Fails the process loudly with a single, clear, consolidated report when a
required production dependency is missing or still a placeholder — so a
misconfigured deploy breaks at boot rather than at the first interview or
signup. Risky-but-non-fatal config (wide-open CORS, disabled invite email,
a localhost invite base URL outside production) is surfaced as a warning
that's logged but does not block startup.

`check_readiness` is pure (no I/O) and duck-typed on the settings object,
so it is unit-tested directly. `assert_ready` is the side-effecting wrapper
the app calls during lifespan startup.
"""
from __future__ import annotations

from typing import List, Tuple

# Placeholder values shipped in backend/.env.example — "present but not
# actually configured" should be treated the same as missing.
_PLACEHOLDERS = {
    "",
    "gsk_your-key-here",
    "https://your-project.supabase.co",
    "sbp_your_key_here",
    "sb_your_key_here",
    "your-key-here",
}

# The wildcard CORS regex default from config.Settings — safe for first-run
# setup, too permissive for production.
_WILDCARD_CORS = r"https://.*\.vercel\.app"

# Values of FRONTEND_BASE_URL that mean "not a real deployed frontend".
_LOCAL_FRONTEND = {"", "http://localhost:3000", "http://127.0.0.1:3000"}


def _unset(value) -> bool:
    return not isinstance(value, str) or value.strip() in _PLACEHOLDERS


def check_readiness(settings) -> Tuple[List[str], List[str]]:
    """Return (fatal, warnings) for the given settings.

    Pure function — no logging, no environment reads — so the policy can be
    exercised exhaustively in tests by passing a settings-like object.
    """
    fatal: List[str] = []
    warnings: List[str] = []
    is_prod = str(getattr(settings, "environment", "development")).strip().lower() == "production"

    # --- Required for the app to function at all ---
    if _unset(settings.groq_api_key):
        fatal.append(
            "GROQ_API_KEY is not set. It powers the LLM (question generation + "
            "evaluation) and Whisper STT - interviews cannot run without it."
        )
    if _unset(settings.supabase_url):
        fatal.append(
            "SUPABASE_URL is not set. The backend has no database access or auth "
            "verification. Set it to https://<project-ref>.supabase.co."
        )
    if _unset(settings.supabase_key):
        fatal.append(
            "SUPABASE_KEY is not set. The backend cannot read or write the "
            "database. Set it to your project's service-role key."
        )

    # --- Production-only fatal: invite links embed FRONTEND_BASE_URL ---
    if is_prod and str(settings.frontend_base_url).strip() in _LOCAL_FRONTEND:
        fatal.append(
            "FRONTEND_BASE_URL is localhost while ENVIRONMENT=production. "
            "Candidate invite emails would ship links no recipient can open. "
            "Set it to your deployed frontend URL."
        )

    # --- Warnings (logged, non-blocking) ---
    cors_wide = not str(settings.frontend_origins).strip() and (
        not str(settings.frontend_origin_regex).strip()
        or str(settings.frontend_origin_regex).strip() == _WILDCARD_CORS
    )
    if cors_wide:
        warnings.append(
            "CORS is wide open: FRONTEND_ORIGIN_REGEX matches any *.vercel.app "
            "and no explicit FRONTEND_ORIGINS are set. Anchor it to your project "
            r"(e.g. ^https://my-app(-[a-z0-9-]+)?\.vercel\.app$) before production."
        )

    if _unset(settings.resend_api_key):
        warnings.append(
            "RESEND_API_KEY is not set: candidate invite emails will be recorded "
            "as 'failed' (the apply link still works if shared manually). Set "
            "RESEND_API_KEY + a verified RESEND_FROM_EMAIL to enable emailed invites."
        )

    if not is_prod and str(settings.frontend_base_url).strip() in _LOCAL_FRONTEND:
        warnings.append(
            "FRONTEND_BASE_URL is localhost (fine for local dev; must be your "
            "deployed URL in production so invite links resolve)."
        )

    return fatal, warnings


def format_report(fatal: List[str], warnings: List[str]) -> str:
    lines: List[str] = []
    if fatal:
        lines.append("=" * 72)
        lines.append("PRODUCTION READINESS CHECK FAILED - required configuration missing:")
        for i, msg in enumerate(fatal, 1):
            lines.append(f"  [FATAL {i}] {msg}")
        lines.append("=" * 72)
    if warnings:
        lines.append("Production readiness warnings:")
        for msg in warnings:
            lines.append(f"  [warn] {msg}")
    return "\n".join(lines)


class ReadinessError(RuntimeError):
    """Raised at startup when a required dependency is missing, so the ASGI
    server fails to start instead of serving a broken app."""


def assert_ready(settings, *, log=print) -> None:
    """Validate at startup: log warnings, raise on any fatal issue.

    Raising during lifespan startup makes uvicorn abort the boot with the
    report visible — the loud failure we want for a misconfigured deploy.
    """
    fatal, warnings = check_readiness(settings)
    report = format_report(fatal, warnings)
    if report:
        log(report)
    if fatal:
        raise ReadinessError(
            f"{len(fatal)} required configuration value(s) missing - see the "
            "readiness report above. Refusing to start."
        )
