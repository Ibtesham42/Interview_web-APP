import type {
  ApplyLanding,
  Candidate,
  ClaimCompanyResponse,
  Company,
  CompanyOption,
  EmailDraft,
  EmailListResponse,
  EmailOutboxRow,
  EmailTemplateKind,
  InviteCandidateResponse,
  Interview,
  InterviewReport,
  Evaluation,
  DashboardData,
  AdminOverview,
  AdminUserDetail,
  CompanySignupResponse,
  Profile,
  HiringFunnelResponse,
  IntegrityVolumeResponse,
  RecruiterAnalyticsFilters,
  RecruiterAnalyticsSummary,
  RecruiterCandidateDetail,
  RecruiterDecision,
  RecruiterDecisionRow,
  RecruiterListParams,
  RecruiterListResponse,
  ScoresByFieldResponse,
} from '../types';
import { supabase } from '../utils/supabase/client';

// In production VITE_API_URL points at the Render backend; in local dev it is
// unset and requests stay relative, served through the Vite dev proxy.
// A trailing slash is stripped so the base never doubles up to "host//api",
// which would 404 every request.
const API_BASE = `${(import.meta.env.VITE_API_URL ?? '').replace(/\/+$/, '')}/api`;

/** Authorization header carrying the current Supabase access token, if signed in. */
async function authHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * sessionStorage key for the platform-admin "Act-as company" picker.
 * Stored as JSON `{id, slug, name}` so the Header can render the chip
 * without re-fetching. Per-tab by design (sessionStorage) — operator
 * actions feel deliberate; a new tab starts unset.
 *
 * The id is sent on every request via `X-Acting-As-Company`; the backend
 * IGNORES the header for non-admin callers (defense-in-depth — frontend
 * trust is verified, not assumed).
 */
const ACTING_AS_STORAGE_KEY = 'actingAsCompany';

/** Read the current act-as override id (if any). Surfaced as a function
 * so consumers don't all have to JSON.parse inline. */
export function getActingAsCompanyId(): string | null {
  try {
    const raw = sessionStorage.getItem(ACTING_AS_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { id?: string };
    return parsed.id ?? null;
  } catch {
    return null;
  }
}

/**
 * Extract a meaningful message from a failed response. Handles JSON error
 * bodies, plain-text 500s, and empty bodies — never produces "Unknown error".
 */
async function extractError(response: Response): Promise<string> {
  const raw = await response.text().catch(() => '');
  if (raw) {
    try {
      const parsed = JSON.parse(raw);
      if (parsed?.detail) {
        return typeof parsed.detail === 'string'
          ? parsed.detail
          : JSON.stringify(parsed.detail);
      }
    } catch {
      /* body is not JSON — fall through to the raw text */
    }
    return raw.slice(0, 300);
  }
  return `Request failed (HTTP ${response.status})`;
}

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const auth = await authHeaders();
  const actingAsId = getActingAsCompanyId();
  const actingAsHeader: Record<string, string> = actingAsId
    ? { 'X-Acting-As-Company': actingAsId }
    : {};
  const response = await fetch(`${API_BASE}${url}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...auth,
      ...actingAsHeader,
      ...(options?.headers as Record<string, string> | undefined),
    },
  });

  if (!response.ok) {
    throw new Error(await extractError(response));
  }

  return response.json();
}

// Candidate APIs
export const candidateApi = {
  create: (data: { name: string; email?: string; field_specialization?: string }) =>
    fetchJson<Candidate>('/candidates/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  list: () => fetchJson<Candidate[]>('/candidates/'),

  get: (id: string) => fetchJson<Candidate>(`/candidates/${id}`),

  uploadResume: async (id: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);

    const auth = await authHeaders();
    const response = await fetch(`${API_BASE}/candidates/upload-resume/${id}`, {
      method: 'POST',
      headers: auth,
      body: formData,
    });

    if (!response.ok) {
      throw new Error(await extractError(response));
    }

    return response.json();
  },
};

// Interview APIs
export const interviewApi = {
  create: (data: { candidate_id: string; job_description?: string }) =>
    fetchJson<Interview>('/interviews/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  list: () => fetchJson<Interview[]>('/interviews/'),

  get: (id: string) => fetchJson<Interview>(`/interviews/${id}`),

  getState: (id: string) =>
    fetchJson<{
      interview_id: string;
      phase: number;
      status: string;
      last_message?: string;
      evaluation_progress: Record<string, number>;
    }>(`/interviews/${id}/state`),

  getEvaluations: (id: string) =>
    fetchJson<Evaluation[]>(`/interviews/${id}/evaluations`),
};

// Report APIs
export const reportApi = {
  get: (interviewId: string) =>
    fetchJson<InterviewReport>(`/reports/interview/${interviewId}/report`),

  getMarkdown: (interviewId: string) =>
    fetchJson<{ markdown: string }>(`/reports/interview/${interviewId}/report/markdown`),
};

// Dashboard API
export const dashboardApi = {
  get: () => fetchJson<DashboardData>('/dashboard/'),
};

// Admin API
export const adminApi = {
  overview: () => fetchJson<AdminOverview>('/admin/overview'),
  userDetail: (userId: string) => fetchJson<AdminUserDetail>(`/admin/users/${userId}`),
};

// Profile API — current user's profile (incl. role), read via the backend
// so it never depends on client-side RLS.
export const profileApi = {
  me: () => fetchJson<Profile>('/auth/me'),
};

// Recruiter API — list endpoint backs the recruiter dashboard. Write
// endpoints (Shortlist / Reject / Bookmark / Notes) come in PR 4.
export const recruiterApi = {
  candidates: (params: RecruiterListParams = {}) => {
    const qs = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null || value === '') continue;
      qs.append(key, String(value));
    }
    const query = qs.toString();
    return fetchJson<RecruiterListResponse>(
      `/recruiter/candidates${query ? `?${query}` : ''}`,
    );
  },

  detail: (candidateId: string) =>
    fetchJson<RecruiterCandidateDetail>(`/recruiter/candidates/${candidateId}`),

  setDecision: (candidateId: string, decision: RecruiterDecision) =>
    fetchJson<RecruiterDecisionRow>(
      `/recruiter/candidates/${candidateId}/decision`,
      { method: 'PUT', body: JSON.stringify({ decision }) },
    ),

  setBookmark: (candidateId: string, bookmarked: boolean) =>
    fetchJson<RecruiterDecisionRow>(
      `/recruiter/candidates/${candidateId}/bookmark`,
      { method: 'PUT', body: JSON.stringify({ bookmarked }) },
    ),

  setNotes: (candidateId: string, notes: string) =>
    fetchJson<RecruiterDecisionRow>(
      `/recruiter/candidates/${candidateId}/notes`,
      { method: 'PUT', body: JSON.stringify({ notes }) },
    ),

  funnel: () => fetchJson<HiringFunnelResponse>('/recruiter/analytics/funnel'),
  scores: () => fetchJson<ScoresByFieldResponse>('/recruiter/analytics/scores'),
  integrity: () =>
    fetchJson<IntegrityVolumeResponse>('/recruiter/analytics/integrity'),
  summary: (filters: RecruiterAnalyticsFilters = {}) => {
    const qs = new URLSearchParams();
    if (filters.name) qs.set('name', filters.name);
    if (filters.email) qs.set('email', filters.email);
    if (filters.status) qs.set('status', filters.status);
    if (filters.date_from) qs.set('date_from', filters.date_from);
    if (filters.date_to) qs.set('date_to', filters.date_to);
    const q = qs.toString();
    return fetchJson<RecruiterAnalyticsSummary>(
      `/recruiter/analytics/summary${q ? `?${q}` : ''}`,
    );
  },

  // Email composer (PR 7) — draft + send + list. The composer opens
  // a draft, the recruiter optionally edits, then sends. The list is
  // shown as a "previous messages" panel on the candidate detail page.
  emailDraft: (candidateId: string, template: EmailTemplateKind = 'shortlist') =>
    fetchJson<EmailDraft>(
      `/recruiter/candidates/${candidateId}/email/draft?template=${template}`,
    ),
  emailSend: (candidateId: string, payload: EmailDraft) =>
    fetchJson<EmailOutboxRow>(
      `/recruiter/candidates/${candidateId}/email/send`,
      { method: 'POST', body: JSON.stringify(payload) },
    ),
  emailList: (candidateId: string) =>
    fetchJson<EmailListResponse>(`/recruiter/candidates/${candidateId}/emails`),
};

// Companies API — multi-tenant rollout PRs 3 + 5.
//   create   - POST /api/companies/ (self-serve signup, PR 3).
//   getMine  - GET /api/companies/mine (read caller's tenant, PR 5).
// Settings PATCH + invite-member endpoints are deferred follow-ups.
export const companiesApi = {
  // Phone + address optional; email required at the schema level (a
  // regex catches the obvious malformed cases server-side too). The
  // SPA passes raw user input; the backend trims + validates.
  create: (data: {
    name: string;
    slug: string;
    email: string;
    phone?: string;
    address?: string;
    city?: string;
    state?: string;
    country?: string;
    postal_code?: string;
    website?: string;
    company_size?: string;
  }) =>
    fetchJson<CompanySignupResponse>('/companies/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  getMine: () => fetchJson<Company>('/companies/mine'),

  // List every Company on the platform — platform-admin-only (the
  // backend role-gates this). Powers the act-as picker in the SPA
  // header (Candidate C, 2026-05-29).
  listAll: () => fetchJson<CompanyOption[]>('/companies/all'),

  // Send a pre-application invitation email to a candidate. Backend
  // constructs the apply URL from FRONTEND_BASE_URL + the caller's
  // company slug — frontend just supplies the recipient + optional
  // name. Used by the "Invite a candidate" card on /admin/settings.
  invite: (data: { to_email: string; candidate_name?: string }) =>
    fetchJson<InviteCandidateResponse>('/companies/invite', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
};

// Apply API — multi-tenant rollout PR 4. Public landing route + post-signup
// tenant claim. The landing GET is intentionally callable WITHOUT a session
// (the candidate hasn't signed up yet); fetchJson degrades gracefully on the
// missing Authorization header.
export const applyApi = {
  landing: (slug: string) =>
    fetchJson<ApplyLanding>(`/apply/${encodeURIComponent(slug)}`),
  claimCompany: (slug: string) =>
    fetchJson<ClaimCompanyResponse>('/auth/claim-company', {
      method: 'POST',
      body: JSON.stringify({ slug }),
    }),
};
