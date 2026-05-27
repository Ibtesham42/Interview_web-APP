import { useState } from 'react';
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { applyApi } from '../../services/api';
import { Button } from '../Button';

const GoogleIcon = () => (
  <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
    <path d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.71-1.57 2.68-3.89 2.68-6.62z" fill="#4285F4" />
    <path d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.81.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18z" fill="#34A853" />
    <path d="M3.97 10.72A5.4 5.4 0 0 1 3.69 9c0-.6.1-1.18.28-1.72V4.95H.96A9 9 0 0 0 0 9c0 1.45.35 2.83.96 4.05l3.01-2.33z" fill="#FBBC05" />
    <path d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.59C13.46.89 11.43 0 9 0A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58z" fill="#EA4335" />
  </svg>
);

export function Login() {
  const { session, signIn, signInWithGoogle, refreshProfile } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const from = (location.state as { from?: string } | null)?.from ?? '/';

  // Multi-tenant PR 4: if a candidate clicked "Sign in" from an apply
  // landing page, the company slug is on the URL — claim it after the
  // session lands so the existing account becomes a member of that tenant.
  const companySlug = searchParams.get('company');

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (session) return <Navigate to={from} replace />;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    const { error: signInError } = await signIn(email.trim(), password);
    if (signInError) {
      setSubmitting(false);
      setError(signInError);
      return;
    }
    if (companySlug) {
      try {
        await applyApi.claimCompany(companySlug);
      } catch {
        // The user is signed in; staying B2C is recoverable.
      }
      await refreshProfile();
    }
    setSubmitting(false);
    navigate(from, { replace: true });
  };

  const handleGoogle = async () => {
    setError(null);
    const { error: oauthError } = await signInWithGoogle(
      companySlug ? `${window.location.origin}/auth/callback?company=${encodeURIComponent(companySlug)}` : undefined,
    );
    if (oauthError) setError(oauthError);
  };

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
        <h1 className="auth-title">Welcome back</h1>
        <p className="auth-subtitle">Sign in to continue to your interviews</p>

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label" htmlFor="login-email">Email</label>
            <input
              id="login-email"
              type="email"
              className="form-input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              autoComplete="email"
              required
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="login-password">Password</label>
            <input
              id="login-password"
              type="password"
              className="form-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="current-password"
              required
            />
          </div>

          {error && <div className="error-message">{error}</div>}

          <Button
            type="submit"
            size="lg"
            fullWidth
            disabled={submitting}
            style={{ marginTop: 'var(--space-sm)' }}
          >
            {submitting ? 'Signing in…' : 'Sign in'}
          </Button>
        </form>

        <div className="auth-divider">or</div>

        <button type="button" className="btn btn-google btn-lg" onClick={handleGoogle}>
          <GoogleIcon />
          Continue with Google
        </button>

        <p className="auth-switch">
          Don't have an account? <Link to="/signup">Create one</Link>
        </p>
      </div>
    </div>
  );
}
