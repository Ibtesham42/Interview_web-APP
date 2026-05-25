"""Test-environment bootstrap.

Pytest collection imports app modules that construct `Settings()` at
module-load time (`app/main.py`, `services/interview_orchestrator.py`,
`services/resume_parser.py`, `services/voice_service.py`). Production
deployments supply real credentials via env vars; CI runners do not.
Without the values below, pydantic raises `ValidationError` and pytest
cannot even collect the test files.

`os.environ.setdefault` only fills the gap when nothing else has set the
variable, so a developer who exports real `GROQ_API_KEY` / `SUPABASE_*`
in their shell still runs against their real values. The placeholder
strings here are obviously-bogus and never reach production (this file
lives under `tests/` and is loaded only by pytest).

Production validation in `app/config.py` is unchanged — required fields
stay required, and the `_strip_env` validator still runs.
"""
import os

os.environ.setdefault("GROQ_API_KEY", "test-groq-key-not-a-real-credential")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-supabase-key-not-a-real-credential")
