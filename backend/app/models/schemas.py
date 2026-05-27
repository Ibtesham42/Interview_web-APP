from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID


class CandidateBase(BaseModel):
    name: str
    email: Optional[str] = None
    field_specialization: Optional[str] = "ml"


class CandidateCreate(CandidateBase):
    pass


class CandidateResponse(CandidateBase):
    id: UUID
    resume_text: Optional[str] = None
    resume_sections: Optional[Dict[str, Any]] = None
    field_specialization: Optional[str] = "general"
    created_at: datetime

    class Config:
        from_attributes = True


class ResumeUploadResponse(BaseModel):
    candidate_id: UUID
    name: str
    field_specialization: str
    sections_found: List[str]


class InterviewBase(BaseModel):
    candidate_id: UUID
    job_description: Optional[str] = None


class InterviewCreate(InterviewBase):
    pass


class MessageContent(BaseModel):
    role: str
    content: str


class InterviewResponse(InterviewBase):
    id: UUID
    status: str
    current_phase: int
    conversation_history: Optional[List[Dict[str, Any]]] = []
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class InterviewStateResponse(BaseModel):
    interview_id: UUID
    phase: int
    status: str
    last_message: Optional[str] = None
    evaluation_progress: Dict[str, float] = {}


class EvaluationBase(BaseModel):
    interview_id: UUID
    phase: int


class EvaluationCreate(EvaluationBase):
    depth_score: Optional[float] = None
    accuracy_score: Optional[float] = None
    clarity_score: Optional[float] = None
    follow_up_score: Optional[float] = None
    overall_score: Optional[float] = None
    details: Dict[str, Any] = {}


class EvaluationResponse(EvaluationBase):
    id: UUID
    depth_score: Optional[float]
    accuracy_score: Optional[float]
    clarity_score: Optional[float]
    follow_up_score: Optional[float]
    overall_score: Optional[float]
    details: Dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


class MLQuestionBase(BaseModel):
    category: str
    question: str
    answer: Optional[str] = None


class MLQuestionResponse(MLQuestionBase):
    id: UUID

    class Config:
        from_attributes = True


class RecruiterCandidateRow(BaseModel):
    """One Candidate as seen on the Recruiter dashboard list.

    Aggregates candidate-level facts (name, field, signup date) with
    interview-derived signals (best score, integrity warnings) and the
    current Recruiter's workflow state for this Candidate (decision,
    bookmarked).
    """
    candidate_id: UUID
    name: str
    email: Optional[str] = None
    field_specialization: Optional[str] = "general"
    created_at: Optional[datetime] = None
    interview_count: int = 0
    completed_count: int = 0
    final_score: float = 0.0
    recommendation: str = ""
    latest_interview_at: Optional[datetime] = None
    integrity_warnings: int = 0
    decision: str = "undecided"
    bookmarked: bool = False
    notes: str = ""


class FunnelStage(BaseModel):
    stage: str
    count: int


class FunnelConversionRates(BaseModel):
    signed_up_to_started: float
    started_to_completed: float
    completed_to_shortlisted: float


class FunnelFieldBreakdown(BaseModel):
    stages: List[FunnelStage]
    conversion_rates: FunnelConversionRates


class HiringFunnelResponse(BaseModel):
    stages: List[FunnelStage]
    conversion_rates: FunnelConversionRates
    by_field: Dict[str, FunnelFieldBreakdown] = {}


class ScoresByFieldEntry(BaseModel):
    field: str
    candidate_count: int
    average_score: float


class ScoresByFieldResponse(BaseModel):
    items: List[ScoresByFieldEntry]


class IntegrityVolumeEntry(BaseModel):
    event_type: str
    count: int


class IntegrityVolumeResponse(BaseModel):
    items: List[IntegrityVolumeEntry]
    total: int


class RecruiterDecisionUpdate(BaseModel):
    decision: str = Field(..., description="shortlisted | rejected | undecided")


class RecruiterBookmarkUpdate(BaseModel):
    bookmarked: bool


class RecruiterNotesUpdate(BaseModel):
    notes: str = Field(default="", max_length=4000)


class RecruiterCandidateInterview(BaseModel):
    interview_id: UUID
    status: str
    completed: bool
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    score: float
    questions: int
    recommendation: str
    integrity_warnings: int
    integrity_terminated: bool


class RecruiterCandidateHeader(BaseModel):
    id: UUID
    name: str
    email: Optional[str] = None
    field_specialization: Optional[str] = None
    created_at: Optional[datetime] = None
    resume_excerpt: Optional[str] = None


class RecruiterDecisionAttribution(BaseModel):
    recruiter_id: UUID
    recruiter_name: str
    decision: str
    bookmarked: bool
    decided_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_you: bool


class RecruiterNotesEntry(BaseModel):
    recruiter_id: UUID
    recruiter_name: str
    notes: str
    updated_at: Optional[datetime] = None


class RecruiterCandidateDetailResponse(BaseModel):
    candidate: RecruiterCandidateHeader
    interviews: List[RecruiterCandidateInterview]
    decisions: List[RecruiterDecisionAttribution]
    my_notes: str = ""
    # Only populated for Admin viewers per the B1 access matrix. `None` for
    # Recruiters; the client uses that as a "you cannot see other notes"
    # signal without round-tripping a separate role check.
    all_notes: Optional[List[RecruiterNotesEntry]] = None


class RecruiterDecisionRow(BaseModel):
    """Workflow state for one (Candidate, Recruiter) pair after an upsert."""
    candidate_id: UUID
    decision: str
    bookmarked: bool
    notes: str
    decided_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RecruiterCandidateListResponse(BaseModel):
    items: List[RecruiterCandidateRow]
    page: int
    page_size: int
    total_count: int
    # True when the page mixes layer-aware (post-Matryoshka) and legacy
    # formula interviews — see grill F5 in RECRUITER_ROLLOUT.md. The UI
    # renders a one-line advisory in that case so a Recruiter understands
    # the score column compares two slightly different formulas.
    formula_mixed: bool = False


class FinalReportResponse(BaseModel):
    interview_id: UUID
    candidate_name: str
    candidate_field: Optional[str] = None
    total_duration_minutes: float
    phase_scores: Dict[str, Any]  # phase -> scores mapping
    final_score: float
    recommendation: str
    total_questions_asked: int
    generated_at: str
    transcript: List[Dict[str, Any]] = []
    strengths: List[str] = []
    improvements: List[str] = []
    summary: str = ""
    # Phase B integrity events. Optional so historical reports (generated
    # before this field existed) still validate cleanly.
    integrity_events: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Multi-tenant (PR 3 — companies / self-serve company signup)
# ---------------------------------------------------------------------------

class CompanyCreate(BaseModel):
    """POST /api/companies/ body. Slug regex enforces the URL shape used
    by /apply/{slug} (PR 4): lowercase letters + digits + hyphens, 3–40
    chars, must start with a letter. Server-side checks layer on top:
    uniqueness (DB) and a reserved-name blocklist.

    Contact fields (migration 007): email is required; phone + address
    are optional. Email is validated as a deliverable address shape;
    phone is a free-form string (international formats vary too widely
    to lock down at this layer)."""
    name: str = Field(..., min_length=2, max_length=80)
    slug: str = Field(..., min_length=3, max_length=40, pattern=r"^[a-z][a-z0-9-]*$")
    email: str = Field(..., min_length=5, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: Optional[str] = Field(None, max_length=40)
    address: Optional[str] = Field(None, max_length=400)


class CompanyResponse(BaseModel):
    id: UUID
    slug: str
    name: str
    email: str = ""
    phone: Optional[str] = None
    address: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class CompanySignupResponse(BaseModel):
    """The POST response — returns the new Company plus the caller's
    updated profile so the frontend can refresh role + company_id
    without a separate /api/auth/me round-trip."""
    company: CompanyResponse
    profile: Dict[str, Any]


class InviteCandidateRequest(BaseModel):
    """POST /api/companies/invite body. The candidate hasn't signed up
    yet, so we only know their email + the name the admin typed. Sent
    by company_admin from /admin/settings; the platform emails the
    candidate an apply-link invitation via Resend."""
    to_email: str = Field(..., min_length=5, max_length=320,
                          pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    candidate_name: Optional[str] = Field(None, max_length=120)


class InviteCandidateResponse(BaseModel):
    """Returns the outbox row for the invite so the SPA can show
    instant feedback (sent / failed) without a follow-up query. Same
    shape as `EmailOutboxRow` for parity."""
    id: UUID
    to_email: str
    subject: str
    status: str
    error_message: Optional[str] = None
    sent_at: datetime


# ---------------------------------------------------------------------------
# Public apply route (PR 4 — /apply/{slug} landing page + claim)
# ---------------------------------------------------------------------------

class ApplyLandingResponse(BaseModel):
    """GET /api/apply/{slug} — public, no auth.

    `signup_open` is a forward-looking flag for when companies can close
    their application window. For PR 4 it's always True; a future
    settings endpoint can toggle it without breaking the response
    shape.

    Contact fields (PR 8) are surfaced publicly because they're the
    company's careers-page-equivalent contact info — the kind of thing
    that lives on the "About / Contact us" of any normal company page.
    Phone + address are optional; the frontend renders only what's
    set."""
    company_id: UUID
    company_name: str
    slug: str
    signup_open: bool = True
    company_email: str = ""
    company_phone: Optional[str] = None
    company_address: Optional[str] = None


class ClaimCompanyRequest(BaseModel):
    """POST /api/auth/claim-company body — slug to claim membership in.

    The endpoint stamps `company_id` on the caller's profile only when
    the caller currently has `company_id IS NULL` (i.e. they signed up
    via /apply/{slug} and the profile-create trigger left company_id
    unset). Idempotent on a no-op match; rejects with 403 if the caller
    already belongs to a different tenant — never silently overwrites.
    """
    slug: str = Field(..., min_length=3, max_length=40, pattern=r"^[a-z][a-z0-9-]*$")


# ---------------------------------------------------------------------------
# Recruiter email composer (PR 7 — Shortlist + Email outreach)
# ---------------------------------------------------------------------------

class EmailDraftResponse(BaseModel):
    """GET /api/recruiter/candidates/{id}/email/draft — returns the
    template-rendered draft for the composer modal. `to` may be empty
    when the candidate has no email on file (resume parser couldn't
    isolate one); the composer makes it editable."""
    to: str
    subject: str
    body: str


class EmailSendRequest(BaseModel):
    """POST body. The recruiter has edited the draft (or accepted it
    as-is); these are the values to actually send. `to` is a
    user-editable field — server validates non-empty + minimal shape."""
    to: str = Field(..., min_length=3, max_length=320)
    subject: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=20_000)


class EmailOutboxRow(BaseModel):
    """Single audit-log row. Returned by POST /send and listed by
    GET /emails. Body is included so the recruiter detail page can
    preview prior sends without a second fetch (grill E4 — full body
    persisted)."""
    id: UUID
    to_email: str
    subject: str
    body: str
    status: str
    resend_message_id: Optional[str] = None
    error_message: Optional[str] = None
    sent_at: datetime
    sender_id: Optional[UUID] = None


class EmailListResponse(BaseModel):
    items: List[EmailOutboxRow]
