import type { ReactNode } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { ProtectedRoute } from './components/auth/ProtectedRoute';
import { Login } from './components/auth/Login';
import { Signup } from './components/auth/Signup';
import { AuthCallback } from './components/auth/AuthCallback';
import { Dashboard } from './components/Dashboard';
import { CandidateUpload } from './components/CandidateUpload';
import { InterviewRoom } from './components/InterviewRoom';
import { Report } from './components/Report';
import { AdminDashboard } from './components/admin/AdminDashboard';
import { AdminUserDetail } from './components/admin/AdminUserDetail';
import { AdminCompanyDetail } from './components/admin/AdminCompanyDetail';
import { RecruiterDashboard } from './components/recruiter/RecruiterDashboard';
import { RecruiterCandidateDetail } from './components/recruiter/RecruiterCandidateDetail';
import { RecruiterAnalytics } from './components/recruiter/RecruiterAnalytics';
import { JobsPage } from './components/jobs/JobsPage';
import { CompanySignup } from './components/companies/CompanySignup';
import { Settings } from './components/companies/Settings';
import { Apply } from './components/apply/Apply';
import { JobApply } from './components/apply/JobApply';
import { TeamAccept } from './components/companies/TeamAccept';
import { AppShell } from './components/layout/AppShell';
import { UiShowcase } from './components/ui/UiShowcase';
import type { CapabilityName } from './services/capabilities';
import type { UserRole } from './types';

function NewInterview() {
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>New interview</h1>
          <p className="page-sub">Set up a fresh voice interview session.</p>
        </div>
      </div>
      <div className="onboard-wrap">
        <CandidateUpload />
      </div>
    </div>
  );
}

// Sends each user to the right home for their role.
function RoleHome() {
  const { profileLoading, profile } = useAuth();
  if (profileLoading) {
    return (
      <div className="auth-loading">
        <div className="spinner" />
        <p>Loading…</p>
      </div>
    );
  }
  const role = profile?.role ?? 'user';
  if (role === 'admin' || role === 'company_admin') return <Navigate to="/admin" replace />;
  if (role === 'recruiter') return <Navigate to="/recruiter" replace />;
  return <Navigate to="/dashboard" replace />;
}

// Route helper. The second argument can be:
//   - undefined           → any authenticated user
//   - UserRole | UserRole[] → role-class gate (kept for genuinely
//                            role-shaped admission, e.g. 'is candidate')
//   - { requires: Capability | Capability[] } → capability gate
//                            (ADR 0007 — preferred when an action
//                            capability exists for the rule)
type ShellGate =
  | UserRole
  | UserRole[]
  | { requires: CapabilityName | CapabilityName[] };

function protectedShell(element: ReactNode, gate?: ShellGate) {
  const isCapabilityGate =
    gate !== undefined && !Array.isArray(gate) && typeof gate === 'object';
  return (
    <ProtectedRoute
      restrictTo={isCapabilityGate ? undefined : (gate as UserRole | UserRole[] | undefined)}
      requires={isCapabilityGate ? (gate as { requires: CapabilityName | CapabilityName[] }).requires : undefined}
    >
      <AppShell>{element}</AppShell>
    </ProtectedRoute>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route path="/auth/callback" element={<AuthCallback />} />

          {/* Public apply link — multi-tenant PR 4. No auth required;
              loads the company info and routes to /signup?company=slug.
              If a signed-in visitor lands here, they get a one-click
              claim CTA instead. */}
          <Route path="/apply/:slug" element={<Apply />} />
          {/* Per-job public apply landing — migration 013. Two path segments,
              so it never collides with the one-segment company /apply/:slug. */}
          <Route path="/apply/:companySlug/:jobSlug" element={<JobApply />} />
          {/* Team-invitation accept landing — migration 014. Public (a fresh
              teammate may not be signed in); handles both states internally. */}
          <Route path="/team/accept" element={<TeamAccept />} />

          <Route path="/" element={<ProtectedRoute><RoleHome /></ProtectedRoute>} />

          {/* Candidate-only — admins are redirected to /admin */}
          <Route path="/dashboard" element={protectedShell(<Dashboard />, 'user')} />
          <Route path="/new" element={protectedShell(<NewInterview />, 'user')} />
          <Route path="/interview/:interviewId" element={protectedShell(<InterviewRoom />, 'user')} />

          {/* Reports — viewable by candidates (own) and admins (oversight) */}
          <Route path="/report/:interviewId" element={protectedShell(<Report />)} />

          {/* Self-serve company signup — multi-tenant PR 3. Reachable
              by ANY visitor including signed-out (Fix 2, 2026-05-29):
              the discoverability links on /signup + /login point here,
              and a user-without-an-account-yet must be able to land on
              the page rather than bouncing back to /login. The
              component renders three branches:
                - !session            → "create account first" CTA
                - session && eligible → the form
                - session && !elig.   → "you're signed in as X" message
              The backend rejects ineligible callers as a second line
              of defense. */}
          <Route path="/companies/signup" element={<AppShell><CompanySignup /></AppShell>} />

          {/* Admin (platform + company-admin) — capability-gated per
              ADR 0007. `see_admin_overview` admits TENANT_ADMINS. */}
          <Route path="/admin" element={protectedShell(<AdminDashboard />, { requires: 'see_admin_overview' })} />
          <Route path="/admin/users/:userId" element={protectedShell(<AdminUserDetail />, { requires: 'see_admin_overview' })} />
          {/* Super-admin read-only company drill-down (review, not the
              company-admin workflow). */}
          <Route path="/admin/companies/:companyId" element={protectedShell(<AdminCompanyDetail />, { requires: 'see_admin_overview' })} />
          {/* Company settings — multi-tenant PR 5 + ADR 0007 widening.
              Admits anyone who can manage settings OR invite candidates
              (OR semantics). This lets `recruiter` reach the page and
              see the Invite card — the apply-link + meta cards are
              gated inside the component by `manage_company_settings`,
              which recruiter fails, so they see only what they can
              act on. */}
          <Route path="/admin/settings" element={protectedShell(<Settings />, { requires: ['manage_company_settings', 'invite_candidate'] })} />

          {/* Recruiter — capability-gated per ADR 0007. `manage_candidates`
              admits HIRING_ROLES (recruiter + tenant admins). */}
          <Route path="/recruiter" element={protectedShell(<RecruiterDashboard />, { requires: 'manage_candidates' })} />
          <Route path="/recruiter/analytics" element={protectedShell(<RecruiterAnalytics />, { requires: 'manage_candidates' })} />
          {/* Job requisitions — manage_jobs (hiring role + tenant), migration 013. */}
          <Route path="/recruiter/jobs" element={protectedShell(<JobsPage />, { requires: 'manage_jobs' })} />
          <Route path="/recruiter/candidates/:candidateId" element={protectedShell(<RecruiterCandidateDetail />, { requires: 'manage_candidates' })} />

          {/* Dev-only design-system showcase (Phase 1). Gated to DEV so it is
              never reachable in production. */}
          {import.meta.env.DEV && <Route path="/__ui" element={<UiShowcase />} />}

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
