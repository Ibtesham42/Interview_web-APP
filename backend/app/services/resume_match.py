"""Resume -> job skill matching (Phase 3).

Deterministic skill-overlap matching with gap analysis: compares a job's
`required_skills` against a candidate's parsed `resume_sections.skills` +
`resume_text`. Returns a 0-100 score plus the matched and missing skills.

Why not embeddings: the platform's vector path (`ml_questions.embedding`) is a
non-operational stub — the column is VECTOR(384) while the only embed helper
uses OpenAI text-embedding-3-small (1536-dim), gated on an often-unset
OPENAI_API_KEY, and `config.py` calls it "the (unused) embedding seed". Building
matching on it would be building on sand. This transparent, dependency-free
overlap is honest and explainable; semantic/LLM matching (reusing the operational
Groq client) is a documented follow-up. Matching is advisory and never writes to
the candidate (user-input-authoritative rule).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _haystack(candidate_skills: Any, resume_text: Optional[str]) -> str:
    """Lowercased text to search a required skill against — the candidate's
    parsed skills (strings, or `{name}`-shaped dicts) plus the full resume."""
    parts: List[str] = []
    if isinstance(candidate_skills, list):
        for s in candidate_skills:
            if isinstance(s, str):
                parts.append(s)
            elif isinstance(s, dict):
                parts.append(str(s.get("name") or s.get("skill") or ""))
    parts.append(resume_text or "")
    return " ".join(parts).lower()


def skill_match(
    required_skills: Any, candidate_skills: Any, resume_text: Optional[str]
) -> Dict[str, Any]:
    """A required skill counts as matched when it appears (case-insensitive
    substring) in the candidate's parsed skills or resume text. Returns
    `{score 0-100, matched, missing, required_count}`. Pure + deterministic."""
    req = [
        s.strip()
        for s in (required_skills or [])
        if isinstance(s, str) and s.strip()
    ]
    if not req:
        return {"score": 0, "matched": [], "missing": [], "required_count": 0}
    hay = _haystack(candidate_skills, resume_text)
    matched, missing = [], []
    for skill in req:
        (matched if skill.lower() in hay else missing).append(skill)
    score = round(len(matched) / len(req) * 100)
    return {
        "score": score,
        "matched": matched,
        "missing": missing,
        "required_count": len(req),
    }


def job_matches(
    supabase, *, job: Dict[str, Any], company_id: Optional[str]
) -> List[Dict[str, Any]]:
    """Rank a job's applicants by resume skill match, best first.

    Applicants = candidates with an interview for this job (interviews.job_id) —
    the same bounded set the pipeline uses, so resume screening sits beside the
    interview view. Tenant scope: the router validates the job belongs to the
    caller's company; `company_id` filters the candidate fetch as defense-in-depth.
    """
    required = job.get("required_skills") or []
    interviews = (
        supabase.table("interviews")
        .select("candidate_id")
        .eq("job_id", job["id"])
        .execute()
        .data
        or []
    )
    candidate_ids = list({iv["candidate_id"] for iv in interviews if iv.get("candidate_id")})
    if not candidate_ids:
        return []

    cand_q = (
        supabase.table("candidates")
        .select("id,name,email,resume_sections,resume_text")
        .in_("id", candidate_ids)
    )
    if company_id is not None:
        cand_q = cand_q.eq("company_id", company_id)
    candidates = cand_q.execute().data or []

    result: List[Dict[str, Any]] = []
    for c in candidates:
        sections = c.get("resume_sections") or {}
        m = skill_match(required, sections.get("skills"), c.get("resume_text") or "")
        result.append({
            "candidate_id": c["id"],
            "name": c.get("name", "Candidate"),
            "email": c.get("email"),
            "match_score": m["score"],
            "matched_skills": m["matched"],
            "missing_skills": m["missing"],
        })
    result.sort(key=lambda r: r["match_score"], reverse=True)
    return result
