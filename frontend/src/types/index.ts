// Roles after multi-tenant rollout PR 3:
//   user           - candidate (B2C if company_id is null, B2B applicant otherwise)
//   recruiter      - tenant-scoped recruiter (company_id always set post-rollout)
//   company_admin  - tenant-local admin who self-signed-up via /companies/signup
//   admin          - platform-wide super-admin (company_id always null)
export type UserRole = 'user' | 'admin' | 'recruiter' | 'company_admin';

export interface Profile {
  id: string;
  email: string | null;
  full_name: string | null;
  role: UserRole;
  // Multi-tenant PR 3 - present on every B2B profile; null for platform
  // admins and B2C users. Frontend uses it only for display (the backend
  // is the authoritative tenant filter).
  company_id?: string | null;
  created_at: string;
}

/** Thin Company shape used by the platform-admin "act-as" picker.
 * Mirrors `GET /api/companies/all` — id + slug + name only. */
export interface CompanyOption {
  id: string;
  slug: string;
  name: string;
}

export interface Company {
  id: string;
  slug: string;
  name: string;
  // Contact fields from migration 007. email is always present
  // (DB-side NOT NULL with default ''); phone + address are optional.
  email: string;
  phone?: string | null;
  address?: string | null;
  created_at: string;
}

export interface CompanySignupResponse {
  company: Company;
  profile: Profile;
}

export interface ApplyLanding {
  company_id: string;
  company_name: string;
  slug: string;
  signup_open: boolean;
  // Optional contact info — set when the company's admin provided
  // them at signup (PR 8). Empty string / null when not set; the
  // apply page only renders what's populated.
  company_email?: string;
  company_phone?: string | null;
  company_address?: string | null;
}

export interface ClaimCompanyResponse {
  claimed: boolean;
  company_id: string;
  reason?: string;
}

// POST /api/companies/invite — admin sends an apply-link invite to a
// candidate who hasn't signed up yet. Outbox row returned so the UI
// can show instant sent/failed feedback.
export interface InviteCandidateResponse {
  id: string;
  to_email: string;
  subject: string;
  status: 'sent' | 'failed';
  error_message?: string | null;
  sent_at: string;
}

// Recruiter email composer (PR 7 — multi-tenant rollout)
export interface EmailDraft {
  to: string;
  subject: string;
  body: string;
}

export interface EmailOutboxRow {
  id: string;
  to_email: string;
  subject: string;
  body: string;
  // 'sent' = Resend accepted; 'failed' = Resend rejected OR service is
  // disabled (no RESEND_API_KEY). error_message carries the reason.
  status: 'sent' | 'failed';
  resend_message_id?: string | null;
  error_message?: string | null;
  sent_at: string;
  sender_id?: string | null;
}

export interface EmailListResponse {
  items: EmailOutboxRow[];
}

export interface Candidate {
  id: string;
  user_id?: string;
  name: string;
  email?: string;
  resume_text?: string;
  resume_sections?: ResumeSections;
  // Any domain is supported — the backend resolves unknown fields dynamically
  // (curated table or LLM-derived). See ADR 0001.
  field_specialization: string;
  created_at: string;
}

export interface ResumeSections {
  education?: Education[];
  experience?: Experience[];
  projects?: Project[];
  skills?: string[];
}

export interface Education {
  degree: string;
  institution: string;
  field?: string;
  year?: string;
}

export interface Experience {
  company: string;
  role: string;
  duration?: string;
  responsibilities?: string[];
}

export interface Project {
  name: string;
  description: string;
  technologies?: string[];
  outcomes?: string;
}

export interface Interview {
  id: string;
  user_id?: string;
  candidate_id: string;
  job_description?: string;
  status: 'phase_1' | 'phase_2' | 'phase_3' | 'phase_4' | 'phase_5' | 'completed';
  current_phase: number;
  conversation_history: Message[];
  created_at: string;
  completed_at?: string;
}

export interface Message {
  role: 'assistant' | 'user';
  content: string;
}

export interface TranscriptMessage {
  id: string;
  role: 'assistant' | 'user';
  content: string;
  timestamp: number;
}

export interface Evaluation {
  id: string;
  interview_id: string;
  phase: number;
  depth_score?: number;
  accuracy_score?: number;
  clarity_score?: number;
  follow_up_score?: number;
  overall_score: number;
  details: Record<string, number>;
  created_at: string;
}

export interface TranscriptTurn {
  role: string;
  content: string;
}

export interface InterviewReport {
  interview_id: string;
  candidate_name: string;
  candidate_field: string;
  total_duration_minutes: number;
  phase_scores: PhaseScores;
  final_score: number;
  recommendation: 'Strong Hire' | 'Hire' | 'Hold' | 'No Hire';
  total_questions_asked: number;
  generated_at: string;
  transcript?: TranscriptTurn[];
  strengths?: string[];
  improvements?: string[];
  summary?: string;
  integrity_events?: IntegrityEventsSection;
}

export interface IntegrityEventRow {
  event_type: IntegrityEventType | string;
  severity: 'info' | 'warning' | 'critical';
  metadata?: Record<string, unknown>;
  created_at: string;
}

export interface IntegrityEventsSection {
  count: number;
  terminated: boolean;
  events: IntegrityEventRow[];
}

export interface DashboardStats {
  total_interviews: number;
  completed_interviews: number;
  average_score: number;
  best_score: number;
  latest_score: number;
}

export interface DashboardInterview {
  interview_id: string;
  candidate_name: string;
  field: string;
  status: string;
  completed: boolean;
  created_at: string;
  score: number;
  recommendation: string;
  questions: number;
}

export interface DashboardTrendPoint {
  date: string;
  score: number;
}

export interface DashboardData {
  stats: DashboardStats;
  interviews: DashboardInterview[];
  trend: DashboardTrendPoint[];
}

export interface AdminStats {
  total_users: number;
  active_users: number;
  total_interviews: number;
  completed_interviews: number;
  completion_rate: number;
  average_score: number;
}

export interface AdminCategory {
  field: string;
  count: number;
  average_score: number;
}

export interface AdminUser {
  user_id: string;
  email: string | null;
  full_name: string | null;
  role: string;
  created_at: string;
  interview_count: number;
  completed_count: number;
  average_score: number;
  last_interview_at?: string | null;
}

export interface AdminOverview {
  stats: AdminStats;
  by_category: AdminCategory[];
  integrity_volume: IntegrityVolumeResponse;
  users: AdminUser[];
}

export interface AdminUserInterview {
  interview_id: string;
  field: string;
  candidate_name: string;
  status: string;
  completed: boolean;
  created_at: string;
  score: number;
  // Phase B integrity surfacing — optional so older admin payloads still
  // deserialise cleanly during the deploy window.
  integrity_warnings?: number;
  integrity_terminated?: boolean;
}

export interface AdminUserDetail {
  user: AdminUser;
  interviews: AdminUserInterview[];
}

// ---------------------------------------------------------------------------
// Recruiter dashboard (PR 3 — recruiter rollout)
// ---------------------------------------------------------------------------

export type RecruiterDecision = 'shortlisted' | 'rejected' | 'undecided';

export interface RecruiterDecisionRow {
  candidate_id: string;
  decision: RecruiterDecision;
  bookmarked: boolean;
  notes: string;
  decided_at: string | null;
  updated_at: string | null;
}

export interface RecruiterCandidate {
  candidate_id: string;
  name: string;
  email: string | null;
  field_specialization: string | null;
  created_at: string | null;
  interview_count: number;
  completed_count: number;
  final_score: number;
  recommendation: string;
  latest_interview_at: string | null;
  integrity_warnings: number;
  decision: RecruiterDecision;
  bookmarked: boolean;
  notes: string;
}

export interface RecruiterCandidateHeader {
  id: string;
  name: string;
  email: string | null;
  field_specialization: string | null;
  created_at: string | null;
  resume_excerpt: string | null;
}

export interface RecruiterCandidateInterview {
  interview_id: string;
  status: string;
  completed: boolean;
  created_at: string | null;
  completed_at: string | null;
  score: number;
  questions: number;
  recommendation: string;
  integrity_warnings: number;
  integrity_terminated: boolean;
}

export interface RecruiterDecisionAttribution {
  recruiter_id: string;
  recruiter_name: string;
  decision: RecruiterDecision;
  bookmarked: boolean;
  decided_at: string | null;
  updated_at: string | null;
  is_you: boolean;
}

export interface RecruiterNotesEntry {
  recruiter_id: string;
  recruiter_name: string;
  notes: string;
  updated_at: string | null;
}

export interface RecruiterCandidateDetail {
  candidate: RecruiterCandidateHeader;
  interviews: RecruiterCandidateInterview[];
  decisions: RecruiterDecisionAttribution[];
  my_notes: string;
  // Admin-only per the B1 matrix. `null` for Recruiters - the client
  // uses null vs [] as the role signal without a separate profile fetch.
  all_notes: RecruiterNotesEntry[] | null;
}

export interface RecruiterListResponse {
  items: RecruiterCandidate[];
  page: number;
  page_size: number;
  total_count: number;
  formula_mixed: boolean;
}

// ---------------------------------------------------------------------------
// Recruiter analytics (PR 6 - hiring funnel + scores + integrity)
// ---------------------------------------------------------------------------

export interface FunnelStage {
  stage: string;
  count: number;
}

export interface FunnelConversionRates {
  signed_up_to_started: number;
  started_to_completed: number;
  completed_to_shortlisted: number;
}

export interface FunnelFieldBreakdown {
  stages: FunnelStage[];
  conversion_rates: FunnelConversionRates;
}

export interface HiringFunnelResponse {
  stages: FunnelStage[];
  conversion_rates: FunnelConversionRates;
  by_field: Record<string, FunnelFieldBreakdown>;
}

export interface ScoresByFieldEntry {
  field: string;
  candidate_count: number;
  average_score: number;
}

export interface ScoresByFieldResponse {
  items: ScoresByFieldEntry[];
}

export interface IntegrityVolumeEntry {
  event_type: string;
  count: number;
}

export interface IntegrityVolumeResponse {
  items: IntegrityVolumeEntry[];
  total: number;
}

export type RecruiterSortField =
  | 'final_score'
  | 'created_at'
  | 'name'
  | 'decision'
  | 'integrity_warnings';

export type RecruiterIntegrityFilter = 'any' | 'with_warnings' | 'without_warnings';

// 'bookmarked' is a workflow filter (independent of decision string) per
// grill F3 — Recruiters can bookmark an 'undecided' Candidate.
export type RecruiterDecisionFilter = RecruiterDecision | 'bookmarked';

export interface RecruiterListParams {
  search?: string;
  field?: string;
  decision?: RecruiterDecisionFilter;
  min_score?: number;
  max_score?: number;
  integrity?: RecruiterIntegrityFilter;
  date_from?: string;
  date_to?: string;
  sort?: RecruiterSortField;
  order?: 'asc' | 'desc';
  page?: number;
  page_size?: number;
}

export interface PhaseScores {
  2?: Phase2Score;
  3?: Phase2Score;
  4?: Phase4Score;
  5?: Phase5Score;
  [key: number]: Phase2Score | Phase4Score | Phase5Score | undefined;
}

export interface Phase2Score {
  depth_score: number;
  accuracy_score: number;
  clarity_score: number;
  overall: number;
}

export interface Phase4Score {
  correct_answers: number;
  total_questions: number;
  overall: number;
}

export interface Phase5Score {
  vision: number;
  team: number;
  self_awareness: number;
  proactivity: number;
  communication: number;
  overall: number;
}

export interface WebSocketMessage {
  // 'disconnected' is a client-side synthetic event emitted when an
  // already-open interview socket drops and cannot be resumed (see ADR 0002).
  // 'integrity_warning' is a server-side reply to a client integrity_event.
  type: 'init' | 'question' | 'answer' | 'voice' | 'audio' |
        'evaluation' | 'phase_update' | 'empathy_nudge' |
        'voice_transcript' | 'voice_error' | 'analysis_result' |
        'interview_ended' | 'end_interview' | 'error' | 'disconnected' |
        'integrity_warning';
  content?: string;
  phase?: number;
  data?: Record<string, unknown>;
  transcript?: string;
  pace?: PaceAnalysis;
  duration?: number;
  audio?: string;
  candidate_name?: string;
  candidate_field?: string;
  current_phase?: number;
  message?: string;
  // integrity_warning fields
  event_type?: IntegrityEventType;
  severity?: 'info' | 'warning' | 'critical';
  count?: number;
  max?: number;
  terminate?: boolean;
  reason?: string;
}

export type IntegrityEventType =
  | 'tab_blur'
  | 'window_blur'
  | 'visibility_hidden'
  | 'camera_lost'
  | 'no_face'
  | 'multi_face'
  | 'camera_dark';

export interface PaceAnalysis {
  words_per_minute: number;
  is_too_fast: boolean;
  is_too_slow: boolean;
  recommendation: string;
}
