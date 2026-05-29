import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import type { CapabilityName } from '../../services/capabilities';
import type { UserRole } from '../../types';

interface ProtectedRouteProps {
  children: ReactNode;
  /**
   * Role-class gate. Pass a single role for tightest scope, or an array
   * when a route is open to multiple roles (e.g. ['recruiter', 'admin']).
   * `undefined` lets any authenticated user through.
   *
   * Use this when the admission rule is genuinely "this kind of
   * identity" (e.g. /dashboard is for candidates regardless of action).
   * For action-shaped gates ("the caller can do X"), prefer `requires`
   * (ADR 0007).
   */
  restrictTo?: UserRole | UserRole[];
  /**
   * Capability gate (ADR 0007 — amends ADR 0006 D6). Pass a single
   * capability name or an array; array semantics is OR ("admitted if
   * the caller has any of these"). The predicate body is the same
   * `can()` from services/capabilities.ts that the components consult,
   * so route admission and in-component UI gating read from one
   * source.
   *
   * Coexists with `restrictTo`: a route picks the gate matching its
   * admission shape. Both can be set simultaneously (rare); both must
   * pass for admission. The intended idiom is one or the other.
   */
  requires?: CapabilityName | CapabilityName[];
}

function LoadingScreen() {
  return (
    <div className="auth-loading">
      <div className="spinner" />
      <p>Loading…</p>
    </div>
  );
}

export function ProtectedRoute({ children, restrictTo, requires }: ProtectedRouteProps) {
  const { session, loading, profileLoading, profile, can } = useAuth();
  const location = useLocation();

  if (loading) return <LoadingScreen />;
  if (!session) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }

  // Wait on the profile before either gate evaluates — otherwise `can()`
  // and the role check both fire with stale defaults and may bounce a
  // valid user to /. Same posture as the previous restrictTo branch.
  if (restrictTo || requires) {
    if (profileLoading) return <LoadingScreen />;
  }

  if (restrictTo) {
    const role: UserRole = (profile?.role as UserRole) ?? 'user';
    const allowed = Array.isArray(restrictTo) ? restrictTo : [restrictTo];
    if (!allowed.includes(role)) {
      return <Navigate to="/" replace />;
    }
  }

  if (requires) {
    const needed = Array.isArray(requires) ? requires : [requires];
    // OR semantics — admitted if any one capability admits the caller.
    // AND composition is intentionally not introduced (ADR 0007 A1).
    if (!needed.some((cap) => can(cap))) {
      return <Navigate to="/" replace />;
    }
  }

  return <>{children}</>;
}
