from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from uuid import UUID

from app.models.schemas import FinalReportResponse
from app.services.interview_orchestrator import ReportGenerator

router = APIRouter()


@router.get("/interview/{interview_id}/report", response_model=FinalReportResponse)
async def get_interview_report(interview_id: UUID):
    """Generate and retrieve the final evaluation report for an interview."""
    generator = ReportGenerator(interview_id)
    report = generator.generate_report()

    if "error" in report:
        raise HTTPException(status_code=404, detail=report["error"])

    return report


@router.get("/interview/{interview_id}/report/markdown")
async def get_interview_report_markdown(interview_id: UUID):
    """Get the interview report in markdown format."""
    generator = ReportGenerator(interview_id)
    report = generator.generate_report()

    if "error" in report:
        raise HTTPException(status_code=404, detail=report["error"])

    markdown = generator.generate_markdown_report(report)
    return JSONResponse({"markdown": markdown})
