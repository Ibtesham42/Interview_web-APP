"""Async-friendly wrappers around the synchronous Groq SDK.

The Groq client (OpenAI-compatible SDK in `app.config.get_groq_client`) is
synchronous. Every call from inside `async def` was hitting the event
loop directly — each Groq round-trip (~1-2s typical, up to 30s on the
timeout boundary) would freeze the single uvicorn worker for the
duration. With concurrent interviews that meant strict serialisation:
candidate B's question generation waited on candidate A's, regardless
of what each was doing.

These two helpers push the sync call onto a worker thread via
`asyncio.to_thread`, so the event loop is free to handle other
interviews' WebSocket frames, REST requests, and timers in parallel.

Scope: only the IO-bound Groq calls. CPU-bound work in services
(prompt assembly, evaluation parsing) stays on the event loop —
moving those to threads would cost more in overhead than it saves.

Call sites: see the rollout-PR-7 entry in CHANGE.md.
"""
from __future__ import annotations

import asyncio
from typing import Any


async def acompletion(client, **kwargs) -> Any:
    """Run `client.chat.completions.create(**kwargs)` off the event loop.

    Returns whatever the SDK returns (an `openai.types.ChatCompletion`
    object in current versions). Exceptions from the sync call propagate
    untouched — callers retain the same try/except surface they had
    before this wrapper landed.
    """
    return await asyncio.to_thread(client.chat.completions.create, **kwargs)


async def atranscription(client, **kwargs) -> Any:
    """Run `client.audio.transcriptions.create(**kwargs)` off the event loop.

    Whisper transcription is the longest-latency Groq call in this
    project (audio upload + decode + STT). It was the most painful
    blocker before this wrapper.
    """
    return await asyncio.to_thread(client.audio.transcriptions.create, **kwargs)
