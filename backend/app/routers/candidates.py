from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from fastapi.responses import JSONResponse
from typing import List
from uuid import UUID

from app.models.schemas import (
    CandidateCreate,
    CandidateResponse,
    ResumeUploadResponse,
)
from app.supabase_client import get_supabase
from app.services.resume_parser import ResumeParser, PDFExtractor
from app.services.invitations import allowed_company_ids, mark_accepted
from app.auth import get_current_user, get_tenant_context

router = APIRouter()


def resolve_target_company(
    supabase, ctx, user, requested_company_id
) -> "str | None":
    """Which company a new candidate/interview row should be stamped with.

    Explicit `company_id` in the request body wins (the invitation flow —
    the candidate chose which inviting company to interview for) but must
    be one the caller belongs to or was invited by; anything else is 403.
    Omitted = the caller's primary company (NULL for B2C users). Platform
    admins may stamp any company.
    """
    if requested_company_id is None:
        return ctx.company_id
    requested = str(requested_company_id)
    if ctx.is_platform_admin or requested == (ctx.company_id or ""):
        return requested
    allowed = allowed_company_ids(
        supabase,
        email=getattr(user, "email", "") or "",
        profile_company_id=ctx.company_id,
    )
    if requested not in allowed:
        raise HTTPException(
            status_code=403,
            detail="You don't have an invitation from this company.",
        )
    return requested


def _require_owned_candidate(supabase, candidate_id: UUID, user_id: str) -> dict:
    """Fetch a candidate and ensure it belongs to the current user."""
    result = supabase.table("candidates").select("*").eq("id", str(candidate_id)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Candidate not found")
    candidate = result.data[0]
    if candidate.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="You do not have access to this candidate")
    return candidate


@router.post("/parse-resume", response_model=ResumeUploadResponse)
async def parse_resume_only(file: UploadFile = File(...), user=Depends(get_current_user)):
    """Parse a resume PDF without saving to the database. Useful for testing."""
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    pdf_content = await file.read()

    extraction = PDFExtractor.extract_text(pdf_content)
    if extraction.get("success"):
        return JSONResponse({
            "status": "extracted",
            "page_count": extraction.get("page_count"),
            "preview": extraction.get("full_text", "")[:500],
            "message": "PDF text extracted. Configure OpenAI for full AI parsing.",
        })

    parser = ResumeParser()
    parsed_data = await parser.parse_resume(pdf_content)

    return JSONResponse({
        "status": "ai_parsed",
        "name": parsed_data["name"],
        "sections_found": list(parsed_data["sections"].keys()),
        "preview": parsed_data["full_text"][:500],
    })


@router.post("/", response_model=CandidateResponse)
async def create_candidate(
    candidate: CandidateCreate,
    user=Depends(get_current_user),
    ctx=Depends(get_tenant_context),
):
    supabase = get_supabase()
    # Tenant stamp at insert time. This was missing before 2026-06-12: rows
    # landed with company_id NULL, which failed the WebSocket tenant gate
    # ("Cannot connect to interview") and hid invited candidates from the
    # inviting company's recruiter views.
    company_id = resolve_target_company(supabase, ctx, user, candidate.company_id)

    result = supabase.table("candidates").insert({
        "name": candidate.name,
        "email": candidate.email,
        "field_specialization": candidate.field_specialization or "ml",
        "user_id": user.id,
        "company_id": company_id,
    }).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create candidate")

    # Acting on an invitation accepts it — the candidate is now visibly in
    # this company's pipeline. Best-effort ledger write.
    if company_id and not ctx.is_platform_admin:
        mark_accepted(
            supabase,
            company_id=company_id,
            email=getattr(user, "email", "") or "",
            user_id=user.id,
        )

    return result.data[0]


@router.get("/", response_model=List[CandidateResponse])
async def list_candidates(user=Depends(get_current_user)):
    supabase = get_supabase()
    result = (
        supabase.table("candidates")
        .select("*")
        .eq("user_id", user.id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


@router.get("/{candidate_id}", response_model=CandidateResponse)
async def get_candidate(candidate_id: UUID, user=Depends(get_current_user)):
    supabase = get_supabase()
    return _require_owned_candidate(supabase, candidate_id, user.id)


@router.post("/upload-resume/{candidate_id}", response_model=ResumeUploadResponse)
async def upload_resume(
    candidate_id: UUID,
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    supabase = get_supabase()
    candidate = _require_owned_candidate(supabase, candidate_id, user.id)

    pdf_content = await file.read()

    parser = ResumeParser()
    parsed_data = await parser.parse_resume(pdf_content)

    # The parser no longer infers field_specialization; the user's form
    # choice (set during create_candidate) is the only source. See the
    # "user input authoritative" Engineering Rule in CLAUDE.md.
    update_payload: dict = {
        "resume_text": parsed_data["full_text"],
        "resume_sections": parsed_data["sections"],
    }

    supabase.table("candidates").update(update_payload).eq("id", str(candidate_id)).execute()

    return ResumeUploadResponse(
        candidate_id=candidate_id,
        name=candidate["name"],
        field_specialization=candidate.get("field_specialization") or "general",
        sections_found=list(parsed_data["sections"].keys()),
    )
