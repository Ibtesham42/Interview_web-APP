import type { ReactNode } from 'react';
import { BrowserRouter, Routes, Route, Navigate, NavLink, useNavigate } from 'react-router-dom';
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
import type { UserRole } from './types';

function Header() {
  const { user, profile, company, signOut } = useAuth();
  const navigate = useNavigate();

  const handleSignOut = async () => {
    await signOut();
    navigate('/login', { replace: true });
  };

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
          {(role === 'admin' || role === 'company_admin') && (
            <>
              <NavLink to="/admin" className={navClass}>Admin</NavLink>
              <NavLink to="/recruiter" className={navClass} end>Candidates</NavLink>
              <NavLink to="/recruiter/analytics" className={navClass}>Analytics</NavLink>
              {/* Settings only useful for tenant-scoped admins (PR 5). */}
              {role === 'company_admin' && (
                <NavLink to="/admin/settings" className={navClass}>Settings</NavLink>
              )}
            </>
          )}
          {role === 'recruiter' && (
            <>
              <NavLink to="/recruiter" className={navClass} end>Candidates</NavLink>
              <NavLink to="/recruiter/analytics" className={navClass}>Analytics</NavLink>
            </>
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
        {/* Tenant chip — surfaces which Company the caller is acting on
            behalf of. Suppressed for platform admins (no tenant) and
            for B2C users (no tenant). Multi-tenant PR 5. */}
        {company && (role === 'company_admin' || role === 'recruiter') && (
          <span className="tenant-chip" title={`Acting on behalf of ${company.name}`}>
            {company.name}
          </span>
        )}
        {role === 'admin' && <span className="role-badge role-admin">Admin</span>}
        {role === 'company_admin' && <span className="role-badge role-admin">Company admin</span>}
        {role === 'recruiter' && <span className="role-badge role-recruiter">Recruiter</span>}
        <span className="header-user-name">{displayName}</span>
        <button className="btn btn-secondary" onClick={handleSignOut}>Sign out</button>
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

function protectedShell(element: ReactNode, restrictTo?: UserRole | UserRole[]) {
  return (
    <ProtectedRoute restrictTo={restrictTo}>
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

          {/* Self-serve company signup — multi-tenant PR 3. Open to
              ANY authenticated user — the component itself renders a
              friendly "you're signed in as X, only standard users can
              create a company" message for non-'user' roles, and the
              backend rejects callers who are already in a tenant or
              already an admin. Keeping the route open means the
              discoverability link on /signup + /login doesn't bounce
              logged-in non-user accounts away. */}
          <Route path="/companies/signup" element={protectedShell(<CompanySignup />)} />

          {/* Admin (platform + company-admin per multi-tenant PR 3) */}
          <Route path="/admin" element={protectedShell(<AdminDashboard />, ['admin', 'company_admin'])} />
          <Route path="/admin/users/:userId" element={protectedShell(<AdminUserDetail />, ['admin', 'company_admin'])} />
          {/* Company settings — multi-tenant PR 5. company_admin only;
              platform admins land on the empty-state message inside. */}
          <Route path="/admin/settings" element={protectedShell(<Settings />, ['admin', 'company_admin'])} />

          {/* Recruiter (Admins + company-admins inherit per B1 + grill C2) */}
          <Route path="/recruiter" element={protectedShell(<RecruiterDashboard />, ['recruiter', 'admin', 'company_admin'])} />
          <Route path="/recruiter/analytics" element={protectedShell(<RecruiterAnalytics />, ['recruiter', 'admin', 'company_admin'])} />
          <Route path="/recruiter/candidates/:candidateId" element={protectedShell(<RecruiterCandidateDetail />, ['recruiter', 'admin', 'company_admin'])} />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
