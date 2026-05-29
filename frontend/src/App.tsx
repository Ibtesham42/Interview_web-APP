import type { ReactNode } from 'react';
import { BrowserRouter, Routes, Route, Navigate, NavLink, useNavigate, Link } from 'react-router-dom';
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
import { RecruiterDashboard } from './components/recruiter/RecruiterDashboard';
import { RecruiterCandidateDetail } from './components/recruiter/RecruiterCandidateDetail';
import { RecruiterAnalytics } from './components/recruiter/RecruiterAnalytics';
import { CompanySignup } from './components/companies/CompanySignup';
import { Settings } from './components/companies/Settings';
import { Apply } from './components/apply/Apply';
import { ActingAsPicker } from './components/admin/ActingAsPicker';
import type { CapabilityName } from './services/capabilities';
import type { UserRole } from './types';

function Header() {
  const { user, session, profile, company, signOut, can } = useAuth();
  const navigate = useNavigate();

  const handleSignOut = async () => {
    await signOut();
    navigate('/login', { replace: true });
  };

  // Routes that AppShell-wrap may render in either an authenticated or
  // an unauthenticated state (currently only /companies/signup — Fix 2
  // 2026-05-29). Header degrades to a Sign-in CTA in the unauth case
  // so we never render a stale Sign-out button for a user with no
  // session.
  const isAuthed = Boolean(session);
  const displayName = profile?.full_name || user?.email || 'Account';
  const role = (profile?.role as UserRole | undefined) ?? 'user';
  const navClass = ({ isActive }: { isActive: boolean }) =>
    `header-link${isActive ? ' active' : ''}`;

  return (
    <header className="header">
      <div className="header-left">
        <div className="header-brand">
          <div className="header-logo">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle cx="9" cy="12" r="6" fill="#4f46e5" />
              <circle cx="15" cy="12" r="6" fill="#0891b2" opacity="0.85" />
            </svg>
          </div>
          <h1 className="header-title">Interview Platform</h1>
        </div>
        <nav className="header-nav">
          {/* Admin overview — TENANT_ADMINS see this. */}
          {can('see_admin_overview') && (
            <NavLink to="/admin" className={navClass}>Admin</NavLink>
          )}
          {/* Candidates + Analytics — anyone with hiring capabilities.
              Surfaces Candidates to `recruiter` (already worked) AND
              `company_admin` / `admin` (who inherit via HIRING_ROLES). */}
          {can('manage_candidates') && (
            <>
              <NavLink to="/recruiter" className={navClass} end>Candidates</NavLink>
              <NavLink to="/recruiter/analytics" className={navClass}>Analytics</NavLink>
            </>
          )}
          {/* Settings only visible when the caller can actually manage
              them — capability requires both role AND tenant. Platform
              admin (no tenant) sees nothing here. */}
          {can('manage_company_settings') && (
            <NavLink to="/admin/settings" className={navClass}>Settings</NavLink>
          )}
          {role === 'user' && (
            <>
              <NavLink to="/dashboard" className={navClass}>Dashboard</NavLink>
              <NavLink to="/new" className={navClass}>New Interview</NavLink>
            </>
          )}
        </nav>
      </div>
      <div className="header-user">
        {isAuthed ? (
          <>
            {/* Tenant chip — surfaces which Company the caller is acting on
                behalf of. Suppressed for platform admins (no tenant) and
                for B2C users (no tenant). Multi-tenant PR 5. */}
            {company && (role === 'company_admin' || role === 'recruiter') && (
              <span className="tenant-chip" title={`Acting on behalf of ${company.name}`}>
                {company.name}
              </span>
            )}
            {role === 'admin' && (
              <>
                <span className="role-badge role-admin">Admin</span>
                {/* Act-as picker (Candidate C). Platform admin only —
                    everyone else has exactly one tenant by design. */}
                <ActingAsPicker />
              </>
            )}
            {role === 'company_admin' && <span className="role-badge role-admin">Company admin</span>}
            {role === 'recruiter' && <span className="role-badge role-recruiter">Recruiter</span>}
            <span className="header-user-name">{displayName}</span>
            <button className="btn btn-secondary" onClick={handleSignOut}>Sign out</button>
          </>
        ) : (
          <Link to="/login" className="btn btn-secondary">Sign in</Link>
        )}
      </div>
    </header>
  );
}

function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="app">
      <Header />
      <main className="main-content">{children}</main>
    </div>
  );
}

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
          <Route path="/recruiter/candidates/:candidateId" element={protectedShell(<RecruiterCandidateDetail />, { requires: 'manage_candidates' })} />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
