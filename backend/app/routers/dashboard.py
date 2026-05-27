"""User dashboard aggregation.

Returns a signed-in user's interview history with computed scores plus
aggregate stats and a score trend. Interview scores come from a single bulk
evaluation query (see `score_interviews_bulk`), not per-interview reports.

Tenant note (multi-tenant PR 2): the dashboard is already self-scoped via
`user_id` — a candidate only sees their own interviews. The added
`company_id` filter is defense-in-depth: if a profile's `company_id` is
ever changed manually, the dashboard refuses to display interviews from
the prior tenant. Platform admins (NULL `company_id`) skip the filter via
the `tenant_scope` helper.
"""
from fastapi import APIRouter, Depends

from app.supabase_client import get_supabase
from app.auth import get_tenant_context, tenant_scope
from app.services.interview_orchestrator import score_interviews_bulk, recommendation_for

router = APIRouter()


@router.get("/")
async def get_dashboard(user=Depends(get_tenant_context)):
    supabase = get_supabase()
    tenant = tenant_scope(user)

    iv_q = (
        supabase.table("interviews")
        .select("*")
        .eq("user_id", user.id)
        .order("created_at", desc=True)
    )
    if tenant is not None:
        iv_q = iv_q.eq("company_id", tenant)
    interviews = iv_q.execute().data or []

    candidate_ids = list({iv["candidate_id"] for iv in interviews if iv.get("candidate_id")})
    candidates: dict = {}
    if candidate_ids:
        rows = (
            supabase.table("candidates")
            .select("id,name,field_specialization")
            .in_("id", candidate_ids)
            .execute()
            .data
            or []
        )
        candidates = {c["id"]: c for c in rows}

    iv_scores = score_interviews_bulk(supabase, [iv["id"] for iv in interviews])

    items = []
    for iv in interviews:
        cand = candidates.get(iv.get("candidate_id"), {})
        scored = iv_scores.get(iv["id"], {"score": 0, "questions": 0})
        completed = iv.get("status") == "completed"
        items.append({
            "interview_id": iv["id"],
            "candidate_name": cand.get("name", "Candidate"),
            "field": cand.get("field_specialization") or "general",
            "status": iv.get("status", ""),
            "completed": completed,
            "created_at": iv.get("created_at"),
            "score": scored["score"],
            "recommendation": recommendation_for(scored["score"]) if completed else "",
            "questions": scored["questions"],
        })

    completed = [i for i in items if i["completed"]]
    scores = [i["score"] for i in completed if i["score"] > 0]

    stats = {
        "total_interviews": len(items),
        "completed_interviews": len(completed),
        "average_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "best_score": round(max(scores), 1) if scores else 0,
        "latest_score": scores[0] if scores else 0,  # items are newest-first
    }

    trend = [
        {"date": i["created_at"], "score": i["score"]}
        for i in reversed(items)
        if i["completed"] and i["score"] > 0
    ]

    return {"stats": stats, "interviews": items, "trend": trend}
