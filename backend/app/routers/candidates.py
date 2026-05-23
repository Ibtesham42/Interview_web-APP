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
from app.auth import get_current_user

router = APIRouter()


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
        "field_specialization": parsed_data["field_specialization"],
        "sections_found": list(parsed_data["sections"].keys()),
        "preview": parsed_data["full_text"][:500],
    })


@router.post("/", response_model=CandidateResponse)
async def create_candidate(candidate: CandidateCreate, user=Depends(get_current_user)):
    supabase = get_supabase()
    result = supabase.table("candidates").insert({
        "name": candidate.name,
        "email": candidate.email,
        "field_specialization": candidate.field_specialization or "ml",
        "user_id": user.id,
    }).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create candidate")

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

    # The candidate's domain choice (from the CandidateUpload form) is
    # AUTHORITATIVE. The resume parser's inferred field is advisory only —
    # its prompt can return just four ML-adjacent labels (nlp/cv/ml/research),
    # and it falls back to "ml" on failure, so blindly persisting it would
    # silently clobber a Web Dev / Marketing / Design / etc. selection back
    # to "ml" and make the interviewer ask gradient-descent questions to a
    # frontend candidate. Only adopt the inference for legacy rows that have
    # no domain set yet.
    update_payload: dict = {
        "resume_text": parsed_data["full_text"],
        "resume_sections": parsed_data["sections"],
    }
    if not candidate.get("field_specialization"):
        update_payload["field_specialization"] = parsed_data["field_specialization"]

    supabase.table("candidates").update(update_payload).eq("id", str(candidate_id)).execute()

    return ResumeUploadResponse(
        candidate_id=candidate_id,
        name=candidate["name"],
        field_specialization=parsed_data["field_specialization"],
        sections_found=list(parsed_data["sections"].keys()),
    )
