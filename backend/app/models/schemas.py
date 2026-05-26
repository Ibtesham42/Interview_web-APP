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
