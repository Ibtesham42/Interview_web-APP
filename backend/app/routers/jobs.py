"""Job requisition endpoints (migration 013 — job-centric ATS keystone).

Tenant CRUD gated by the `manage_jobs` capability (hiring role + a tenant),
plus one public, un-authed lookup for the candidate apply page. Thin: auth +
tenant + validation + row->schema mapping; data access lives in
`services/jobs.py`. Tenant isolation is enforced in the service (every query
filtered by `company_id` from the capability-resolved context), so a recruiter
of company A can neither list nor fetch company B's jobs.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.capabilities import requires
from app.models.schemas import (
    JobCreate,
    JobListResponse,
    JobPublicResponse,
    JobResponse,
    JobUpdate,
)
from app.services import jobs as jobs_svc
from app.supabase_client import get_supabase

router = APIRouter()


def _job_response(row: Dict[str, Any]) -> JobResponse:
    """Map a raw `jobs` row to the response model — single source of truth for
    the field set so a newly-added column surfaces from every endpoint at once
    (avoids the SELECT-has-it / response-drops-it bug class)."""
    return JobResponse(
        id=row["id"],
        company_id=row["company_id"],
        title=row["title"],
        slug=row["slug"],
        description=row.get("description"),
        required_skills=row.get("required_skills") or [],
        employment_type=row.get("employment_type"),
        location=row.get("location"),
        status=row["status"],
        interview_config=row.get("interview_config") or {},
        created_by=row.get("created_by"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get("/", response_model=JobListResponse)
async def list_jobs(
    job_status: Optional[str] = Query(
        None, alias="status",
        description="Filter by job status: draft | open | closed",
    ),
    ctx=requires("manage_jobs"),
):
    """List the caller's company jobs, newest first."""
    rows = jobs_svc.list_for_company(get_supabase(), ctx.company_id, status=job_status)
    return JobListResponse(items=[_job_response(r) for r in rows])


@router.post("/", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(body: JobCreate, ctx=requires("manage_jobs")):
    """Create a job under the caller's company. Slug is unique per company."""
    supabase = get_supabase()
    slug = body.slug.strip().lower()
    if jobs_svc.slug_exists(supabase, ctx.company_id, slug):
        raise HTTPException(
            status_code=400,
            detail=f"A job with slug '{slug}' already exists in this company.",
        )
    data = body.model_dump()
    data["slug"] = slug
    row = jobs_svc.insert_job(
        supabase, company_id=ctx.company_id, created_by=ctx.id, data=data
    )
    return _job_response(row)


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, ctx=requires("manage_jobs")):
    """Fetch one job in the caller's tenant. 404 for missing OR cross-tenant."""
    row = jobs_svc.get_for_company(get_supabase(), job_id, ctx.company_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_response(row)


@router.patch("/{job_id}", response_model=JobResponse)
async def update_job(job_id: str, body: JobUpdate, ctx=requires("manage_jobs")):
    """Partial-update a job (title/slug/description/skills/status/etc.).
    Opening or closing a job is `status` here, not a separate endpoint."""
    supabase = get_supabase()
    if jobs_svc.get_for_company(supabase, job_id, ctx.company_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    data = body.model_dump(exclude_unset=True)
    if data.get("slug"):
        data["slug"] = data["slug"].strip().lower()
        if jobs_svc.slug_exists(supabase, ctx.company_id, data["slug"], exclude_id=job_id):
            raise HTTPException(
                status_code=400,
                detail=f"A job with slug '{data['slug']}' already exists in this company.",
            )
    row = jobs_svc.update_job(
        supabase, job_id=job_id, company_id=ctx.company_id, data=data
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_response(row)


@router.get("/public/{company_slug}/{job_slug}", response_model=JobPublicResponse)
async def get_public_job(company_slug: str, job_slug: str):
    """Public, no auth — the candidate apply landing for an OPEN job. Draft /
    closed jobs and unknown slugs 404 (same as a non-existent job)."""
    result = jobs_svc.get_public(
        get_supabase(),
        company_slug=company_slug.strip().lower(),
        job_slug=job_slug.strip().lower(),
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Job not found or not open")
    company, job = result["company"], result["job"]
    return JobPublicResponse(
        company_slug=company["slug"],
        company_name=company["name"],
        title=job["title"],
        slug=job["slug"],
        description=job.get("description"),
        employment_type=job.get("employment_type"),
        location=job.get("location"),
    )
