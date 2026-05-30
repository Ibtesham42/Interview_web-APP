import { useState } from 'react';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { applyApi } from '../../services/api';

const GoogleIcon = () => (
  <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
    <path d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.71-1.57 2.68-3.89 2.68-6.62z" fill="#4285F4" />
    <path d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.81.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18z" fill="#34A853" />
    <path d="M3.97 10.72A5.4 5.4 0 0 1 3.69 9c0-.6.1-1.18.28-1.72V4.95H.96A9 9 0 0 0 0 9c0 1.45.35 2.83.96 4.05l3.01-2.33z" fill="#FBBC05" />
    <path d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.59C13.46.89 11.43 0 9 0A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58z" fill="#EA4335" />
  </svg>
);

export function Signup() {
  const { session, signUp, signInWithGoogle, refreshProfile } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  // Multi-tenant PR 4: when the signup URL carries ?company=slug
  // (set by the /apply/{slug} landing page or by clicking "Apply
  // now"), the slug is threaded through the auth flow so the new
  // candidate is stamped with the company on first session.
  const companySlug = searchParams.get('company');

  // ADR 0008 (Candidate signup is invite-only) + ADR 0009 (company
  // registration is self-contained in /companies/signup). The ONLY
  // intent that surfaces this form is an applicant who arrived via
  // /apply/{slug} (?company=slug). Company founders now create their
  // admin account inside /companies/signup and never reach here.
  // Anything else → the invite-only explainer card. The grandfathered
  // B2C accounts already exist; this gate is prospective only (D2).
  const hasSignupIntent = Boolean(companySlug);

  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (session) return <Navigate to="/" replace />;

  // Build the email-confirm redirect URL. The apply-link flow rides one
  // payload through the round-trip: `company=slug` triggers claim-company
  // in AuthCallback so the new candidate is stamped with the tenant.
  const callbackParams = new URLSearchParams();
  if (companySlug) callbackParams.set('company', companySlug);
  const qs = callbackParams.toString();
  const emailRedirectTo = qs
    ? `${window.location.origin}/auth/callback?${qs}`
    : `${window.location.origin}/auth/callback`;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setInfo(null);

    if (password.length < 6) {
      setError('Password must be at least 6 characters.');
      return;
    }

    setSubmitting(true);
    const { error: signUpError, needsEmailConfirm } = await signUp(
      email.trim(),
      password,
      fullName.trim(),
      { emailRedirectTo },
    );

    if (signUpError) {
      setSubmitting(false);
      setError(signUpError);
      return;
    }
    if (needsEmailConfirm) {
      setSubmitting(false);
      setInfo('Account created. Check your email to confirm, then sign in.');
      return;
    }

    // Immediate-session path (Supabase project with email-confirm
    // disabled). Claim the company before navigating so the SPA's
    // role-aware routing sees the stamp on first render.
    if (companySlug) {
      try {
        await applyApi.claimCompany(companySlug);
      } catch {
        // Surface nothing — the user is signed up; staying B2C is
        // recoverable by re-visiting /apply/{slug}.
      }
    }
    await refreshProfile();
    setSubmitting(false);
    // Candidate signup lands on the role-aware home (RoleHome routes by
    // role). Company founders no longer route through here (ADR 0009).
    navigate('/', { replace: true });
  };

  const handleGoogle = async () => {
    setError(null);
    // Google OAuth: same payload as the email-confirm path. company
    // triggers claim-company; next routes the post-callback landing.
    const oauthRedirect = qs
      ? `${window.location.origin}/auth/callback?${qs}`
      : undefined;
    const { error: oauthError } = await signInWithGoogle(oauthRedirect);
    if (oauthError) setError(oauthError);
  };

  // Explainer for the no-intent case (ADR 0008). A wandering visitor
  // hitting /signup directly sees this and is routed to the two real
  // signup paths: an apply link (which they'd get from their hiring
  // company) or company-founder signup.
  if (!hasSignupIntent) {
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
          <h1 className="auth-title">Sign-up is invite-only</h1>
          <p className="auth-subtitle">
            Candidates join through their hiring company. Pick whichever
            path matches you.
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)', marginTop: 'var(--space-lg)' }}>
            <Link
              to="/companies/signup"
              className="btn btn-primary btn-lg"
              style={{ width: '100%' }}
            >
              Set up your own company
            </Link>
            <div style={{ fontSize: '0.8125rem', color: 'var(--text-tertiary)', textAlign: 'center' }}>
              You're a candidate? Ask your hiring company for an apply
              link (it looks like <code>/apply/&lt;company&gt;</code>) or
              check your email for an invite.
            </div>
          </div>

          <p className="auth-switch" style={{ marginTop: 'var(--space-lg)' }}>
            Already have an account? <Link to="/login">Sign in</Link>
          </p>
        </div>
      </div>
    );
  }

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
        <h1 className="auth-title">Create your account</h1>
        <p className="auth-subtitle">
          Apply to {companySlug ?? 'this company'} — create your candidate account
        </p>

        {info && <div className="auth-info">{info}</div>}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label" htmlFor="signup-name">Full name</label>
            <input
              id="signup-name"
              type="text"
              className="form-input"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="Your full name"
              autoComplete="name"
              required
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="signup-email">Email</label>
            <input
              id="signup-email"
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
            <label className="form-label" htmlFor="signup-password">Password</label>
            <input
              id="signup-password"
              type="password"
              className="form-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 6 characters"
              autoComplete="new-password"
              required
            />
          </div>

          {error && <div className="error-message">{error}</div>}

          <button
            type="submit"
            className="btn btn-primary btn-lg"
            style={{ width: '100%', marginTop: 'var(--space-sm)' }}
            disabled={submitting}
          >
            {submitting ? 'Creating account…' : 'Create account'}
          </button>
        </form>

        <div className="auth-divider">or</div>

        <button type="button" className="btn btn-google btn-lg" onClick={handleGoogle}>
          <GoogleIcon />
          Continue with Google
        </button>

        <p className="auth-switch">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
        <p className="auth-switch auth-switch-secondary">
          Setting up your company instead? <Link to="/companies/signup">Create one →</Link>
        </p>
      </div>
    </div>
  );
}
