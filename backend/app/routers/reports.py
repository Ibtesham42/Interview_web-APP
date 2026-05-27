from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from uuid import UUID

from app.auth import get_tenant_context, tenant_scope
from app.models.schemas import FinalReportResponse
from app.services.interview_orchestrator import ReportGenerator
from app.supabase_client import get_supabase

router = APIRouter()


def _authorize_report_access(interview_id: UUID, ctx) -> None:
    """Allow the report to be read only by its owner, a tenant-scoped
    recruiter/admin of the same tenant, or a platform admin.

    Pre-rollout PR 0 (recruiter rollout, 2026-05-26) these endpoints were
    UNAUTHENTICATED — anyone holding an interview_id UUID could pull a
    candidate's full report including the transcript. That gate is now
    closed at every layer:

    - Owner path: caller is the user who created the interview.
    - Platform admin path: `role='admin'` (NULL `company_id`) reads any
      report (grill C3).
    - Tenant-scoped recruiter / company-admin path: caller has the
      `recruiter` (or future `company_admin`) role AND the interview's
      `company_id` matches the caller's. A recruiter of tenant A cannot
      read reports from tenant B — surfaced as 404, indistinguishable
      from 'missing'.
    """
    supabase = get_supabase()

    interview_resp = (
        supabase.table("interviews")
        .select("user_id,company_id")
        .eq("id", str(interview_id))
        .execute()
    )
    if not interview_resp.data:
        # Surface as 404 rather than 403 so we don't leak existence.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")

    row = interview_resp.data[0]
    owner_id = row.get("user_id")
    interview_company = row.get("company_id")

    # Owner path — every caller can read their own report.
    if owner_id == ctx.id:
        return

    # Platform admin path — cross-tenant access by design.
    if ctx.is_platform_admin:
        return

    # Recruiter path — role gate + tenant-match. Same 404 on tenant
    # mismatch as on role mismatch so the API never tells a recruiter
    # whether the interview exists in some other tenant.
    if ctx.role != "recruiter":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    if tenant_scope(ctx) is not None and interview_company != tenant_scope(ctx):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")


@router.get("/interview/{interview_id}/report", response_model=FinalReportResponse)
async def get_interview_report(interview_id: UUID, user=Depends(get_tenant_context)):
    """Generate and retrieve the final evaluation report for an interview."""
    _authorize_report_access(interview_id, user)

    generator = ReportGenerator(interview_id)
    report = generator.generate_report()

    if "error" in report:
        raise HTTPException(status_code=404, detail=report["error"])

    return report


@router.get("/interview/{interview_id}/report/markdown")
async def get_interview_report_markdown(interview_id: UUID, user=Depends(get_tenant_context)):
    """Get the interview report in markdown format."""
    _authorize_report_access(interview_id, user)

    generator = ReportGenerator(interview_id)
    report = generator.generate_report()

    if "error" in report:
        raise HTTPException(status_code=404, detail=report["error"])

    markdown = generator.generate_markdown_report(report)
    return JSONResponse({"markdown": markdown})
