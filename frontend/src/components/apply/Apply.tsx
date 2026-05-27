import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { applyApi } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import type { ApplyLanding } from '../../types';

/**
 * Public landing page for /apply/{slug} (multi-tenant rollout PR 4).
 *
 * No auth required. Resolves the slug → company info via the public
 * GET /api/apply/{slug}. Three rendered states:
 *
 *   - Loading — spinner while the GET is in flight.
 *   - Found — company name + "Apply" CTA that routes to
 *     /signup?company={slug}. The Signup page passes the slug
 *     through and POSTs to /auth/claim-company after the session
 *     lands.
 *   - Not found / closed / error — friendly message + a link home.
 *
 * If the visitor is already signed in, the "Apply" CTA becomes a
 * "Claim this invite" button — calls claim-company directly instead
 * of routing through signup. Keeps the flow short for a candidate
 * who already has an account.
 */
export function Apply() {
  const { slug = '' } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const { session, profile, refreshProfile } = useAuth();

  const [landing, setLanding] = useState<ApplyLanding | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [claiming, setClaiming] = useState(false);

  useEffect(() => {
    if (!slug) {
      setLoading(false);
      setError('Missing apply slug.');
      return;
    }
    let cancelled = false;
    setLoading(true);
    applyApi
      .landing(slug)
      .then((data) => {
        if (!cancelled) setLanding(data);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load this apply link');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  const handleApply = () => {
    // Pass the slug as a query param so the signup flow can claim the
    // company after the session is established. The same param is read
    // by AuthCallback.tsx for the email-confirm + Google OAuth paths.
    navigate(`/signup?company=${encodeURIComponent(slug)}`);
  };

  const handleClaim = async () => {
    if (!landing) return;
    setClaiming(true);
    setError(null);
    try {
      await applyApi.claimCompany(slug);
      await refreshProfile();
      navigate('/dashboard', { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not claim this invite');
      setClaiming(false);
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

  if (error || !landing) {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <div className="auth-brand">
            <div className="auth-brand-logo">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <circle cx="9" cy="12" r="6" fill="#4f46e5" />
                <circle cx="15" cy="12" r="6" fill="#0891b2" opacity="0.85" />
              </svg>
            </div>
          </div>
          <h1 className="auth-title">Invite not valid</h1>
          <p className="auth-subtitle">
            {error ?? 'This apply link could not be loaded.'}
          </p>
          <p className="auth-switch">
            <Link to="/">Back to the homepage</Link>
          </p>
        </div>
      </div>
    );
  }

  // Already-signed-in branch — show a single-step claim CTA so the
  // candidate doesn't repeat signup.
  if (session) {
    const alreadyHere =
      profile?.role !== 'user' || (profile?.company_id ?? null) !== null;
    return (
      <div className="auth-page">
        <div className="auth-card">
          <div className="auth-brand">
            <div className="auth-brand-logo">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <circle cx="9" cy="12" r="6" fill="#4f46e5" />
                <circle cx="15" cy="12" r="6" fill="#0891b2" opacity="0.85" />
              </svg>
            </div>
          </div>
          <h1 className="auth-title">Apply to {landing.company_name}</h1>
          <p className="auth-subtitle">
            {alreadyHere
              ? 'You are already signed in. Claim this invite if you want to apply with the account you are using.'
              : `Signed in as ${profile?.email ?? 'your account'}.`}
          </p>
          {alreadyHere && profile?.company_id ? (
            <div className="error-message">
              Your account already belongs to another company. Sign out and apply
              with a different email.
            </div>
          ) : null}
          <button
            type="button"
            className="btn btn-primary btn-lg"
            onClick={handleClaim}
            disabled={claiming || Boolean(profile?.company_id)}
            style={{ width: '100%' }}
          >
            {claiming ? 'Claiming…' : `Claim this invite`}
          </button>
          <p className="auth-switch" style={{ marginTop: 'var(--space-md)' }}>
            Wrong account? <Link to="/login">Sign in with a different one</Link>
          </p>
        </div>
      </div>
    );
  }

  // Not signed in — the standard apply flow.
  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-brand">
          <div className="auth-brand-logo">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle cx="9" cy="12" r="6" fill="#4f46e5" />
              <circle cx="15" cy="12" r="6" fill="#0891b2" opacity="0.85" />
            </svg>
          </div>
        </div>
        <h1 className="auth-title">Apply to {landing.company_name}</h1>
        <p className="auth-subtitle">
          Create an account to start your AI-led interview for {landing.company_name}.
          Your application is reviewed by {landing.company_name}'s hiring team.
        </p>
        <button
          type="button"
          className="btn btn-primary btn-lg"
          onClick={handleApply}
          style={{ width: '100%' }}
        >
          Apply now
        </button>
        <p className="auth-switch" style={{ marginTop: 'var(--space-md)' }}>
          Already have an account? <Link to={`/login?company=${encodeURIComponent(slug)}`}>Sign in</Link>
        </p>
      </div>
    </div>
  );
}
