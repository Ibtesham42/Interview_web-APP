from fastapi import APIRouter, HTTPException, Depends
from typing import List
from uuid import UUID

from app.models.schemas import (
    InterviewCreate,
    InterviewResponse,
    InterviewStateResponse,
    EvaluationResponse
)
from app.supabase_client import get_supabase
from app.auth import get_current_user

router = APIRouter()


@router.post("/", response_model=InterviewResponse)
async def create_interview(interview: InterviewCreate, user=Depends(get_current_user)):
    supabase = get_supabase()

    result = supabase.table("interviews").insert({
        "candidate_id": str(interview.candidate_id),
        "job_description": interview.job_description,
        "status": "phase_1",
        "current_phase": 1,
        "conversation_history": [],
        "user_id": user.id,
    }).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create interview")

    return result.data[0]


@router.get("/", response_model=List[InterviewResponse])
async def list_interviews(user=Depends(get_current_user)):
    supabase = get_supabase()
    result = (
        supabase.table("interviews")
        .select("*")
        .eq("user_id", user.id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


@router.get("/{interview_id}", response_model=InterviewResponse)
async def get_interview(interview_id: UUID):
    supabase = get_supabase()
    result = supabase.table("interviews").select("*").eq("id", str(interview_id)).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Interview not found")

    return result.data[0]


@router.get("/{interview_id}/state", response_model=InterviewStateResponse)
async def get_interview_state(interview_id: UUID):
    supabase = get_supabase()
    result = supabase.table("interviews").select("*").eq("id", str(interview_id)).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Interview not found")

    interview = result.data[0]
    last_message = None
    if interview["conversation_history"]:
        last_msg = interview["conversation_history"][-1]
        last_message = last_msg.get("content", "")[:100]

    # Get evaluation progress
    eval_result = supabase.table("evaluations").select("*").eq("interview_id", str(interview_id)).execute()
    evaluation_progress = {}
    for eval_row in eval_result.data:
        evaluation_progress[f"phase_{eval_row['phase']}"] = eval_row.get("overall_score", 0)

    return InterviewStateResponse(
        interview_id=interview_id,
        phase=interview["current_phase"],
        status=interview["status"],
        last_message=last_message,
        evaluation_progress=evaluation_progress
    )


@router.patch("/{interview_id}/phase")
async def update_interview_phase(interview_id: UUID, phase: int, status: str):
    supabase = get_supabase()

    result = supabase.table("interviews").update({
        "current_phase": phase,
        "status": status
    }).eq("id", str(interview_id)).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Interview not found")

    return {"message": "Phase updated", "phase": phase, "status": status}


@router.patch("/{interview_id}/complete")
async def complete_interview(interview_id: UUID):
    supabase = get_supabase()

    result = supabase.table("interviews").update({
        "status": "completed",
        "completed_at": "now()"
    }).eq("id", str(interview_id)).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Interview not found")

    return {"message": "Interview completed"}


@router.get("/{interview_id}/evaluations", response_model=List[EvaluationResponse])
async def get_interview_evaluations(interview_id: UUID):
    supabase = get_supabase()
    result = supabase.table("evaluations").select("*").eq("interview_id", str(interview_id)).order("phase").execute()
    return result.data
