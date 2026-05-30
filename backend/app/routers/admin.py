"""Admin / client analytics endpoints.

All routes are gated by `get_current_admin`. The backend uses the Supabase
service-role key, so these aggregations can read across all users. Interview
scores come from a single bulk evaluation query, not per-interview reports.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.supabase_client import get_supabase
from app.auth import get_current_admin, tenant_scope
from app.services.interview_orchestrator import score_interviews_bulk
from app.services.recruiter_analytics import integrity_event_volume

router = APIRouter()


@router.get("/overview")
async def admin_overview(admin=Depends(get_current_admin)):
    supabase = get_supabase()
    tenant = tenant_scope(admin)

    profiles_q = supabase.table("profiles").select("*").order("created_at", desc=True)
    if tenant is not None:
        profiles_q = profiles_q.eq("company_id", tenant)
    profiles = profiles_q.execute().data or []

    iv_q = supabase.table("interviews").select("id,user_id,candidate_id,status,created_at")
    if tenant is not None:
        iv_q = iv_q.eq("company_id", tenant)
    interviews = iv_q.execute().data or []

    candidate_ids = list({iv["candidate_id"] for iv in interviews if iv.get("candidate_id")})
    candidates = {}
    if candidate_ids:
        rows = (
            supabase.table("candidates").select("id,field_specialization")
            .in_("id", candidate_ids).execute().data or []
        )
        candidates = {c["id"]: c for c in rows}

    iv_scores = score_interviews_bulk(supabase, [iv["id"] for iv in interviews])

    users = {p["id"]: {
        "user_id": p["id"],
        "email": p.get("email"),
        "full_name": p.get("full_name"),
        "role": p.get("role", "user"),
        "created_at": p.get("created_at"),
        "interview_count": 0,
        "completed_count": 0,
        "scores": [],
        "last_interview_at": None,
    } for p in profiles}

    categories: dict = {}
    completed_total = 0
    platform_scores = []

    for iv in interviews:
        completed = iv.get("status") == "completed"
        score = iv_scores.get(iv["id"], {}).get("score", 0)
        if completed:
            completed_total += 1
            if score > 0:
                platform_scores.append(score)

        user = users.get(iv.get("user_id"))
        if user:
            user["interview_count"] += 1
            if completed:
                user["completed_count"] += 1
                if score > 0:
                    user["scores"].append(score)
            ts = iv.get("created_at")
            if ts and (user["last_interview_at"] is None or ts > user["last_interview_at"]):
                user["last_interview_at"] = ts

        field = candidates.get(iv.get("candidate_id"), {}).get("field_specialization") or "general"
        cat = categories.setdefault(field, {"count": 0, "scores": []})
        cat["count"] += 1
        if completed and score > 0:
            cat["scores"].append(score)

    user_list = []
    for user in users.values():
        scores = user.pop("scores")
        user["average_score"] = round(sum(scores) / len(scores), 1) if scores else 0
        user_list.append(user)
    user_list.sort(key=lambda u: u["interview_count"], reverse=True)

    by_category = [
        {
            "field": field,
            "count": data["count"],
            "average_score": round(sum(data["scores"]) / len(data["scores"]), 1)
            if data["scores"] else 0,
        }
        for field, data in sorted(categories.items(), key=lambda kv: kv[1]["count"], reverse=True)
    ]

    stats = {
        "total_users": len(profiles),
        "active_users": sum(1 for u in user_list if u["interview_count"] > 0),
        "total_interviews": len(interviews),
        "completed_interviews": completed_total,
        "completion_rate": round(completed_total / len(interviews) * 100) if interviews else 0,
        "average_score": round(sum(platform_scores) / len(platform_scores), 1)
        if platform_scores else 0,
    }

    # Integrity-event volume by type — one bulk query, tenant-scoped (None for
    # platform admin = cross-tenant). Reuses the recruiter-analytics helper,
    # which swallows a missing migration-002 table cleanly. Lets an operator
    # triage noise patterns and tune thresholds straight from the overview.
    integrity_volume = integrity_event_volume(supabase, company_id=tenant)

    return {
        "stats": stats,
        "by_category": by_category,
        "integrity_volume": integrity_volume,
        "users": user_list,
    }


@router.get("/users/{user_id}")
async def admin_user_detail(user_id: UUID, admin=Depends(get_current_admin)):
    supabase = get_supabase()
    tenant = tenant_scope(admin)

    # If the caller is tenant-scoped (post-PR 3 company_admin), the target
    # user must belong to the same tenant — cross-tenant id falls through
    # to 404 without leaking existence.
    profile_q = supabase.table("profiles").select("*").eq("id", str(user_id))
    if tenant is not None:
        profile_q = profile_q.eq("company_id", tenant)
    profile_rows = profile_q.execute().data
    if not profile_rows:
        raise HTTPException(status_code=404, detail="User not found")
    profile = profile_rows[0]

    iv_q = (
        supabase.table("interviews").select("*")
        .eq("user_id", str(user_id)).order("created_at", desc=True)
    )
    if tenant is not None:
        iv_q = iv_q.eq("company_id", tenant)
    interviews = iv_q.execute().data or []

    candidate_ids = list({iv["candidate_id"] for iv in interviews if iv.get("candidate_id")})
    candidates = {}
    if candidate_ids:
        rows = (
            supabase.table("candidates").select("id,name,field_specialization")
            .in_("id", candidate_ids).execute().data or []
        )
        candidates = {c["id"]: c for c in rows}

    iv_scores = score_interviews_bulk(supabase, [iv["id"] for iv in interviews])

    # Phase B integrity counts — ONE bulk query across all interviews, then
    # group in Python. Swallow if the migration hasn't been applied yet so the
    # admin view still renders without the integrity column populated.
    integrity_counts: dict = {}
    iv_ids = [iv["id"] for iv in interviews]
    if iv_ids:
        try:
            rows = (
                supabase.table("interview_integrity_events")
                .select("interview_id")
                .in_("interview_id", iv_ids)
                .execute()
                .data
                or []
            )
            for row in rows:
                iv_id = row.get("interview_id")
                if iv_id:
                    integrity_counts[iv_id] = integrity_counts.get(iv_id, 0) + 1
        except Exception:
            integrity_counts = {}

    items = []
    for iv in interviews:
        cand = candidates.get(iv.get("candidate_id"), {})
        items.append({
            "interview_id": iv["id"],
            "field": cand.get("field_specialization") or "general",
            "candidate_name": cand.get("name", "Candidate"),
            "status": iv.get("status", ""),
            "completed": iv.get("status") == "completed",
            "created_at": iv.get("created_at"),
            "score": iv_scores.get(iv["id"], {}).get("score", 0),
            "integrity_warnings": integrity_counts.get(iv["id"], 0),
            "integrity_terminated": iv.get("status") == "terminated_integrity",
        })

    completed_scores = [i["score"] for i in items if i["completed"] and i["score"] > 0]

    return {
        "user": {
            "user_id": profile["id"],
            "email": profile.get("email"),
            "full_name": profile.get("full_name"),
            "role": profile.get("role", "user"),
            "created_at": profile.get("created_at"),
            "interview_count": len(items),
            "completed_count": sum(1 for i in items if i["completed"]),
            "average_score": round(sum(completed_scores) / len(completed_scores), 1)
            if completed_scores else 0,
        },
        "interviews": items,
    }
