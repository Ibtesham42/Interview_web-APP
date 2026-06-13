"""Tests for the AI hiring-recommendation endpoint (Phase 2).

The endpoint reuses the deterministic scoring functions; here we verify it
selects the best interview, maps to the right recommendation tier, and that the
per-phase contributions sum to the final score (the explainability invariant).
The tenant gate is monkeypatched out (covered by the recruiter tenant tests);
this isolates the recommendation logic.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from app.auth import TenantContext
from app.routers.recruiter import candidate_recommendation

CAND = "cccccccc-cccc-cccc-cccc-cccccccccccc"
IV = "11111111-1111-1111-1111-111111111111"


class _Resp:
    def __init__(self, data):
        self.data = data


class _Chain:
    def __init__(self, table, store):
        self._t, self._store = table, store
        self._eqs: List = []
        self._in: Optional[tuple] = None

    def select(self, *_a, **_k):
        return self

    def eq(self, c, v):
        self._eqs.append((c, v)); return self

    def in_(self, c, vals):
        self._in = (c, list(vals)); return self

    def execute(self):
        rows = self._store.get(self._t, [])
        out = []
        for r in rows:
            if any(r.get(c) != v for c, v in self._eqs):
                continue
            if self._in is not None and r.get(self._in[0]) not in self._in[1]:
                continue
            out.append(dict(r))
        return _Resp(out)


def _supabase(*, interviews, evaluations):
    store = {"interviews": interviews, "evaluations": evaluations}
    sb = MagicMock()
    sb.table.side_effect = lambda name: _Chain(name, store)
    return sb


def _run(coro):
    return asyncio.run(coro)


def _ctx():
    return TenantContext(user_id="u-1", role="recruiter", company_id="comp-1")


def _evals_scoring_eight():
    """Phases 2-5 each crafted to an 'overall' of 8.0 (non-layer-aware), so the
    final weighted score is 8.0 -> 'Hire'."""
    return [
        {"interview_id": IV, "phase": 2, "depth_score": 8, "accuracy_score": 8, "details": {"clarity": 8}},
        {"interview_id": IV, "phase": 3, "depth_score": 8, "accuracy_score": 8, "details": {"clarity": 8}},
        {"interview_id": IV, "phase": 4, "accuracy_score": 8, "details": {}},
        {"interview_id": IV, "phase": 5, "details": {
            "vision": 8, "team": 8, "self_awareness": 8, "proactivity": 8, "communication": 8}},
    ]


def test_breakdown_sums_to_final_and_maps_tier(monkeypatch):
    sb = _supabase(
        interviews=[{"id": IV, "candidate_id": CAND}],
        evaluations=_evals_scoring_eight(),
    )
    monkeypatch.setattr("app.routers.recruiter.get_supabase", lambda: sb)
    monkeypatch.setattr(
        "app.routers.recruiter._resolve_candidate_tenant", lambda *a, **k: "comp-1"
    )
    result = _run(candidate_recommendation(uuid.UUID(CAND), user=_ctx()))

    assert result.final_score == 8.0
    assert result.recommendation == "Hire"        # >=7.0, <8.5
    assert str(result.interview_id) == IV
    assert len(result.phase_breakdown) == 4
    # The explainability invariant: contributions sum to the final score.
    assert round(sum(b.contribution for b in result.phase_breakdown), 2) == result.final_score


def test_no_scored_interview_returns_empty(monkeypatch):
    sb = _supabase(interviews=[], evaluations=[])
    monkeypatch.setattr("app.routers.recruiter.get_supabase", lambda: sb)
    monkeypatch.setattr(
        "app.routers.recruiter._resolve_candidate_tenant", lambda *a, **k: "comp-1"
    )
    result = _run(candidate_recommendation(uuid.UUID(CAND), user=_ctx()))

    assert result.recommendation is None
    assert result.final_score is None
    assert result.phase_breakdown == []
    assert "No scored interview" in result.summary
