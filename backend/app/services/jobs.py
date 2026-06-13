"""Job requisitions data access (migration 013 — job-centric ATS keystone).

Tenant-scoped CRUD. Every read/write is filtered by `company_id`; the router
resolves the caller's tenant via the `manage_jobs` capability gate and passes it
here, so a recruiter can never touch another company's jobs. `get_public` is the
one un-authed path: it resolves a company by slug then an OPEN job by slug,
returning nothing for draft/closed jobs or unknown slugs.

Router -> Service -> Supabase: the router stays thin (auth + validation +
row->schema mapping); all table access lives here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_COLUMNS = (
    "id,company_id,title,slug,description,required_skills,employment_type,"
    "location,status,interview_config,created_by,created_at,updated_at"
)


def list_for_company(
    supabase, company_id: str, *, status: Optional[str] = None
) -> List[Dict[str, Any]]:
    """All jobs for a company, newest first; optional status filter."""
    q = (
        supabase.table("jobs")
        .select(_COLUMNS)
        .eq("company_id", company_id)
        .order("created_at", desc=True)
    )
    if status:
        q = q.eq("status", status)
    return q.execute().data or []


def get_for_company(
    supabase, job_id: str, company_id: str
) -> Optional[Dict[str, Any]]:
    """One job, tenant-scoped. None when it doesn't exist OR belongs to another
    company — the caller must not be able to tell those apart (no info leak)."""
    rows = (
        supabase.table("jobs")
        .select(_COLUMNS)
        .eq("id", job_id)
        .eq("company_id", company_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def slug_exists(
    supabase, company_id: str, slug: str, *, exclude_id: Optional[str] = None
) -> bool:
    """True if `slug` is already used by another job in this company. The DB
    also enforces UNIQUE(company_id, slug); this gives a clean 400 instead of a
    raw Postgres error."""
    rows = (
        supabase.table("jobs")
        .select("id")
        .eq("company_id", company_id)
        .eq("slug", slug)
        .execute()
        .data
        or []
    )
    if exclude_id is not None:
        rows = [r for r in rows if r.get("id") != exclude_id]
    return len(rows) > 0


def insert_job(
    supabase, *, company_id: str, created_by: Optional[str], data: Dict[str, Any]
) -> Dict[str, Any]:
    """Insert one job. `company_id` + `created_by` are stamped server-side; the
    DB defaults `created_at`/`updated_at`."""
    payload = {**data, "company_id": company_id, "created_by": created_by}
    rows = supabase.table("jobs").insert(payload).execute().data or []
    return rows[0] if rows else payload


def update_job(
    supabase, *, job_id: str, company_id: str, data: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Patch a tenant-scoped job. Returns the updated row, or None when no row
    matched (wrong tenant / missing). `updated_at` is bumped here with an
    explicit ISO timestamp — the column default only fires on INSERT."""
    if not data:
        return get_for_company(supabase, job_id, company_id)
    payload = {**data, "updated_at": datetime.now(timezone.utc).isoformat()}
    rows = (
        supabase.table("jobs")
        .update(payload)
        .eq("id", job_id)
        .eq("company_id", company_id)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def get_public(
    supabase, *, company_slug: str, job_slug: str
) -> Optional[Dict[str, Any]]:
    """Resolve an OPEN job by (company_slug, job_slug) for the public apply
    page. Returns {"company": {...}, "job": {...}} or None. Draft/closed jobs
    and unknown slugs return None (a 404 to the caller)."""
    company_rows = (
        supabase.table("companies")
        .select("id,slug,name")
        .eq("slug", company_slug)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not company_rows:
        return None
    company = company_rows[0]
    job_rows = (
        supabase.table("jobs")
        .select(_COLUMNS)
        .eq("company_id", company["id"])
        .eq("slug", job_slug)
        .eq("status", "open")
        .limit(1)
        .execute()
        .data
        or []
    )
    if not job_rows:
        return None
    return {"company": company, "job": job_rows[0]}
