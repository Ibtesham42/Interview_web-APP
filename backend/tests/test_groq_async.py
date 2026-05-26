"""Tests for the asyncio.to_thread wrappers around the sync Groq SDK.

The contracts being pinned:
- `acompletion` and `atranscription` forward every kwarg to the sync
  call and return its result untouched.
- Exceptions raised by the sync call propagate to the awaiter (so
  callers retain their existing try/except surface).
- The sync call executes on a worker thread, NOT the event loop's
  thread. This is the load-bearing claim of PR 7 — it's why
  concurrent interviews stop serialising on Groq round-trips. The
  test verifies it via `threading.get_ident()` rather than wall-clock
  measurement (timing-based tests flake under CI load).

`asyncio.run` is used directly instead of `pytest-asyncio` (not in
requirements-dev) — the wrappers are a thin shim, a fixture for them
would be overkill.
"""
import asyncio
import threading
from types import SimpleNamespace

import pytest

from app.services.groq_async import acompletion, atranscription


class _FakeGroqClient:
    """Minimal stand-in for the Groq SDK shape we touch. Records every
    invocation so tests can assert on kwargs without instantiating the
    real OpenAI client."""

    def __init__(self, *, raises=None, return_value=None, on_call=None):
        self.calls: list[dict] = []
        self._raises = raises
        self._return_value = return_value
        self._on_call = on_call

        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._record("chat"))
        )
        self.audio = SimpleNamespace(
            transcriptions=SimpleNamespace(create=self._record("audio"))
        )

    def _record(self, surface):
        def _call(**kwargs):
            self.calls.append({"surface": surface, "kwargs": kwargs})
            if self._on_call:
                self._on_call()
            if self._raises:
                raise self._raises
            return self._return_value

        return _call


# ---------------------------------------------------------------------------
# acompletion
# ---------------------------------------------------------------------------

class TestAcompletion:
    def test_kwargs_forwarded_unchanged(self):
        client = _FakeGroqClient(return_value=SimpleNamespace(id="resp-1"))
        result = asyncio.run(acompletion(
            client,
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.2,
        ))
        assert result.id == "resp-1"
        assert client.calls == [{
            "surface": "chat",
            "kwargs": {
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "hi"}],
                "temperature": 0.2,
            },
        }]

    def test_exception_propagates(self):
        client = _FakeGroqClient(raises=RuntimeError("groq down"))
        with pytest.raises(RuntimeError, match="groq down"):
            asyncio.run(acompletion(client, model="x", messages=[]))

    def test_runs_on_worker_thread_not_event_loop(self):
        """The whole point of PR 7: the sync call must NOT execute on
        the asyncio event loop thread. Verified via thread identity
        rather than wall-clock (timing tests flake under CI load)."""
        sync_call_thread: dict = {}

        def record_thread():
            sync_call_thread["id"] = threading.get_ident()

        client = _FakeGroqClient(on_call=record_thread)

        async def runner():
            loop_thread_id = threading.get_ident()
            await acompletion(client, model="x", messages=[])
            return loop_thread_id

        loop_thread_id = asyncio.run(runner())
        assert sync_call_thread["id"] != loop_thread_id


# ---------------------------------------------------------------------------
# atranscription
# ---------------------------------------------------------------------------

class TestAtranscription:
    def test_kwargs_forwarded_unchanged(self):
        client = _FakeGroqClient(return_value="transcribed text")
        result = asyncio.run(atranscription(
            client,
            model="whisper-large-v3",
            file=b"audio-bytes",
            language="en",
            response_format="text",
            temperature=0.0,
        ))
        assert result == "transcribed text"
        assert client.calls[0]["surface"] == "audio"
        assert client.calls[0]["kwargs"]["model"] == "whisper-large-v3"
        assert client.calls[0]["kwargs"]["language"] == "en"
        assert client.calls[0]["kwargs"]["response_format"] == "text"

    def test_exception_propagates(self):
        client = _FakeGroqClient(raises=ValueError("bad audio"))
        with pytest.raises(ValueError, match="bad audio"):
            asyncio.run(atranscription(
                client, model="whisper-large-v3", file=b"",
            ))

    def test_runs_on_worker_thread_not_event_loop(self):
        sync_call_thread: dict = {}

        def record_thread():
            sync_call_thread["id"] = threading.get_ident()

        client = _FakeGroqClient(on_call=record_thread)

        async def runner():
            loop_thread_id = threading.get_ident()
            await atranscription(client, model="whisper-large-v3", file=b"")
            return loop_thread_id

        loop_thread_id = asyncio.run(runner())
        assert sync_call_thread["id"] != loop_thread_id


# ---------------------------------------------------------------------------
# Concurrency — the real reason this PR exists
# ---------------------------------------------------------------------------

class TestConcurrency:
    def test_two_concurrent_acompletions_run_in_parallel(self):
        """Two interviews shouldn't serialise on Groq calls. With the
        sync target sleeping 100ms each, two concurrent awaits should
        finish in roughly one sleep period — not two.

        Threshold of 180ms (vs 200ms naive serial) leaves headroom for
        thread-pool spin-up under CI, while still catching a regression
        if someone replaces the wrapper with a sync await."""
        import time

        def slow_call():
            time.sleep(0.1)
            return SimpleNamespace(ok=True)

        client_a = _FakeGroqClient(return_value=None)
        client_a.chat.completions.create = lambda **_: slow_call()
        client_b = _FakeGroqClient(return_value=None)
        client_b.chat.completions.create = lambda **_: slow_call()

        async def runner():
            return await asyncio.gather(
                acompletion(client_a, model="x", messages=[]),
                acompletion(client_b, model="x", messages=[]),
            )

        start = time.monotonic()
        results = asyncio.run(runner())
        elapsed = time.monotonic() - start

        assert len(results) == 2
        assert elapsed < 0.18, (
            f"two 100ms calls took {elapsed:.3f}s — wrapper appears to be "
            f"serialising (expected ~0.1s with thread-pool concurrency)"
        )
