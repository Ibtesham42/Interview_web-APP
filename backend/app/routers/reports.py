from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from uuid import UUID

from app.auth import get_current_user
from app.models.schemas import FinalReportResponse
from app.services.interview_orchestrator import ReportGenerator
from app.supabase_client import get_supabase

router = APIRouter()


def _authorize_report_access(interview_id: UUID, user) -> None:
    """Allow the report to be read only by its owner, an admin, or a recruiter.

    Before rollout PR 0 (recruiter rollout, 2026-05-26) these endpoints
    were UNAUTHENTICATED — anyone holding an interview_id UUID could pull
    a candidate's full report including the transcript. This gate closes
    that leak.

    The 'recruiter' arm was added in rollout PR 2 per the B1 access matrix
    (Recruiters need report read for the candidate-detail view).
    """
    supabase = get_supabase()

    interview_resp = supabase.table("interviews").select("user_id").eq(
        "id", str(interview_id)
    ).execute()
    if not interview_resp.data:
        # Surface as 404 rather than 403 so we don't leak the existence
        # of interviews the caller cannot see.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")

    owner_id = interview_resp.data[0].get("user_id")
    if owner_id == user.id:
        return

    # Non-owner: must be admin or recruiter.
    profile_resp = supabase.table("profiles").select("role").eq(
        "id", user.id
    ).execute()
    role = profile_resp.data[0].get("role") if profile_resp.data else None
    if role not in ("admin", "recruiter"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


@router.get("/interview/{interview_id}/report", response_model=FinalReportResponse)
async def get_interview_report(interview_id: UUID, user=Depends(get_current_user)):
    """Generate and retrieve the final evaluation report for an interview."""
    _authorize_report_access(interview_id, user)

    generator = ReportGenerator(interview_id)
    report = generator.generate_report()

    if "error" in report:
        raise HTTPException(status_code=404, detail=report["error"])

    return report


@router.get("/interview/{interview_id}/report/markdown")
async def get_interview_report_markdown(interview_id: UUID, user=Depends(get_current_user)):
    """Get the interview report in markdown format."""
    _authorize_report_access(interview_id, user)

    generator = ReportGenerator(interview_id)
    report = generator.generate_report()

    if "error" in report:
        raise HTTPException(status_code=404, detail=report["error"])

    markdown = generator.generate_markdown_report(report)
    return JSONResponse({"markdown": markdown})
