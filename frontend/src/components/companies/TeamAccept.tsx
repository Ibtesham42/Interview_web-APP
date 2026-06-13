import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { applyApi, teamApi } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';

/**
 * Team-invitation accept landing: /team/accept?company={slug} (migration 014).
 *
 * Public route (a fresh teammate may not be signed in yet). Resolves the
 * company name via the public apply landing for display, then:
 *   - signed-in plain 'user' → an explicit "Accept" button that stamps their
 *     profile with the invited role (the backend matches the pending invite to
 *     their email).
 *   - signed-in hiring account → can't accept (already part of a company).
 *   - signed-out → sign-in / create-account CTAs; reopen this link afterwards.
 *
 * The accept is explicit (a button, not on-mount) so a role change is never a
 * silent side effect — mirrors the candidate Apply.tsx claim flow.
 */
export function TeamAccept() {
  const [params] = useSearchParams();
  const slug = params.get('company') ?? '';
  const navigate = useNavigate();
  const { session, profile, refreshProfile } = useAuth();

  const [companyName, setCompanyName] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [accepting, setAccepting] = useState(false);

  useEffect(() => {
    if (!slug) {
      setLoading(false);
      setError('Missing invitation link.');
      return;
    }
    let cancelled = false;
    applyApi
      .landing(slug)
      .then((data) => {
        if (!cancelled) setCompanyName(data.company_name);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load this invitation');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  const handleAccept = async () => {
    setAccepting(true);
    setError(null);
    try {
      await teamApi.accept(slug);
      await refreshProfile();
      navigate('/', { replace: true }); // RoleHome routes to the right home
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not accept the invitation');
      setAccepting(false);
    }
  };

  if (loading) {
    return (
      <div className="auth-loading">
        <div className="spinner" />
        <p>Loading…</p>
      </div>
    );
  }

  const company = companyName ?? 'this company';
  const isHiringAccount = Boolean(session && profile && profile.role !== 'user');

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1 className="auth-title">Join {company}'s team</h1>

        {error && <div className="error-message" role="alert">{error}</div>}

        {!session ? (
          <>
            <p className="auth-subtitle">
              You've been invited to join {company} on the hiring platform. Sign
              in or create your account, then reopen this invitation link to
              accept.
            </p>
            <Link to="/login" className="btn btn-primary btn-lg btn-block">Sign in</Link>
            <p className="auth-switch" style={{ marginTop: 'var(--space-md)' }}>
              New here? <Link to="/signup">Create an account</Link>
            </p>
          </>
        ) : isHiringAccount ? (
          <p className="auth-subtitle">
            This account already manages a company. Team invitations are accepted
            from a personal account.
          </p>
        ) : (
          <>
            <p className="auth-subtitle">
              Accept to join {company} as a member of their hiring team. You'll be
              able to review their candidates and jobs.
            </p>
            <button
              type="button"
              className="btn btn-primary btn-lg btn-block"
              onClick={handleAccept}
              disabled={accepting}
            >
              {accepting ? 'Accepting…' : 'Accept invitation'}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
