import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import type { UserRole } from '../../types';

interface ProtectedRouteProps {
  children: ReactNode;
  /**
   * Role gate. Pass a single role for tightest scope, or an array when a
   * route is open to multiple roles (e.g. ['recruiter', 'admin'] — the
   * B1 access matrix in RECRUITER_ROLLOUT.md). `undefined` lets any
   * authenticated user through.
   *
   * When a signed-in user fails the gate they're sent home (`/`), which
   * resolves to their role-appropriate dashboard via `RoleHome` —
   * avoids hard-coding "admins go here, users go there" in every gate.
   */
  restrictTo?: UserRole | UserRole[];
}

function LoadingScreen() {
  return (
    <div className="auth-loading">
      <div className="spinner" />
      <p>Loading…</p>
    </div>
  );
}

export function ProtectedRoute({ children, restrictTo }: ProtectedRouteProps) {
  const { session, loading, profileLoading, profile } = useAuth();
  const location = useLocation();

  if (loading) return <LoadingScreen />;
  if (!session) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }

  if (restrictTo) {
    if (profileLoading) return <LoadingScreen />;
    const role: UserRole = (profile?.role as UserRole) ?? 'user';
    const allowed = Array.isArray(restrictTo) ? restrictTo : [restrictTo];
    if (!allowed.includes(role)) {
      return <Navigate to="/" replace />;
    }
  }

  return <>{children}</>;
}
