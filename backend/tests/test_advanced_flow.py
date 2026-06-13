"""Tests for the advanced interview flow — per-job system-prompt emphasis (Phase 3).

The load-bearing property is STRICT ADDITIVITY: an empty interview_config must
leave the interviewer prompt byte-identical to the pre-feature shape (no
ROLE-SPECIFIC FOCUS block), and a set config only APPENDS emphasis. The phase
structure / layer engine / scoring / turn flow are never touched (ADR 0001).

`interview_id=None` so no DB load runs; field 'general' is curated, so
_resolve_field_info never calls Groq.
"""
from __future__ import annotations

import asyncio

from app.services.interview_orchestrator import InterviewOrchestrator


def _orch(config):
    o = InterviewOrchestrator(
        interview_id=None,
        candidate_data={"field_specialization": "general", "resume_sections": {}},
    )
    o.interview_config = config
    return o


def test_focus_block_empty_without_config():
    assert _orch({})._job_focus_block() == ""
    # Present-but-empty fields are also a no-op.
    assert _orch({"focus_areas": [], "instructions": ""})._job_focus_block() == ""


def test_focus_block_renders_focus_and_instructions():
    block = _orch({
        "focus_areas": ["GraphQL", "caching"],
        "instructions": "Probe system-design depth.",
    })._job_focus_block()
    assert "GraphQL" in block and "caching" in block
    assert "Probe system-design depth." in block
    assert "does NOT replace" in block  # the guard-rail framing is present


def test_prompt_is_strictly_additive():
    base = asyncio.run(_orch({}).get_interviewer_prompt(2))
    tuned = asyncio.run(_orch({"focus_areas": ["GraphQL"]}).get_interviewer_prompt(2))

    # Empty config -> no focus block at all (unchanged from before the feature).
    assert "ROLE-SPECIFIC FOCUS" not in base
    assert "GraphQL" not in base

    # Configured -> the SAME base prompt with the focus emphasis appended.
    assert "ROLE-SPECIFIC FOCUS" in tuned
    assert "GraphQL" in tuned
    # The phase-2 structure is intact in both (additive, not a rewrite).
    assert "PHASE 2" in base and "PHASE 2" in tuned
    assert "MATRYOSHKA DEPTH MODEL" in base and "MATRYOSHKA DEPTH MODEL" in tuned
