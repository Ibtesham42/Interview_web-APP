import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';

interface ProtectedRouteProps {
  children: ReactNode;
  /**
   * Role gate:
   * - 'admin' — only admins (others sent to their dashboard)
   * - 'user'  — only non-admins (admins sent to the admin area)
   * - undefined — any authenticated user
   */
  restrictTo?: 'user' | 'admin';
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
  const { session, loading, profileLoading, isAdmin } = useAuth();
  const location = useLocation();

  if (loading) return <LoadingScreen />;
  if (!session) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }

  // Role-restricted routes need the profile fetch to finish to know the role.
  if (restrictTo) {
    if (profileLoading) return <LoadingScreen />;
    if (restrictTo === 'admin' && !isAdmin) return <Navigate to="/dashboard" replace />;
    if (restrictTo === 'user' && isAdmin) return <Navigate to="/admin" replace />;
  }

  return <>{children}</>;
}
