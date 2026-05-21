import type {
  Candidate,
  Interview,
  InterviewReport,
  Evaluation,
  DashboardData,
  AdminOverview,
  AdminUserDetail,
  Profile,
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
  const response = await fetch(`${API_BASE}${url}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...auth,
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
