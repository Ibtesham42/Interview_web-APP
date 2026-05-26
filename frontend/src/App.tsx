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
import type { UserRole } from './types';

function Header() {
  const { user, profile, signOut } = useAuth();
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
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10" />
              <path d="M12 6v6l4 2" />
            </svg>
          </div>
          <h1 className="header-title">Interview Platform</h1>
        </div>
        <nav className="header-nav">
          {role === 'admin' && (
            <>
              <NavLink to="/admin" className={navClass}>Admin</NavLink>
              <NavLink to="/recruiter" className={navClass}>Candidates</NavLink>
            </>
          )}
          {role === 'recruiter' && (
            <NavLink to="/recruiter" className={navClass}>Candidates</NavLink>
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
        {role === 'admin' && <span className="role-badge role-admin">Admin</span>}
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
  if (role === 'admin') return <Navigate to="/admin" replace />;
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

          <Route path="/" element={<ProtectedRoute><RoleHome /></ProtectedRoute>} />

          {/* Candidate-only — admins are redirected to /admin */}
          <Route path="/dashboard" element={protectedShell(<Dashboard />, 'user')} />
          <Route path="/new" element={protectedShell(<NewInterview />, 'user')} />
          <Route path="/interview/:interviewId" element={protectedShell(<InterviewRoom />, 'user')} />

          {/* Reports — viewable by candidates (own) and admins (oversight) */}
          <Route path="/report/:interviewId" element={protectedShell(<Report />)} />

          {/* Admin-only */}
          <Route path="/admin" element={protectedShell(<AdminDashboard />, 'admin')} />
          <Route path="/admin/users/:userId" element={protectedShell(<AdminUserDetail />, 'admin')} />

          {/* Recruiter (Admins inherit per the B1 access matrix) */}
          <Route path="/recruiter" element={protectedShell(<RecruiterDashboard />, ['recruiter', 'admin'])} />
          <Route path="/recruiter/candidates/:candidateId" element={protectedShell(<RecruiterCandidateDetail />, ['recruiter', 'admin'])} />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
