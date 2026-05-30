import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { companiesApi } from '../../services/api';

const GoogleIcon = () => (
  <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
    <path d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.71-1.57 2.68-3.89 2.68-6.62z" fill="#4285F4" />
    <path d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.81.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18z" fill="#34A853" />
    <path d="M3.97 10.72A5.4 5.4 0 0 1 3.69 9c0-.6.1-1.18.28-1.72V4.95H.96A9 9 0 0 0 0 9c0 1.45.35 2.83.96 4.05l3.01-2.33z" fill="#FBBC05" />
    <path d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.59C13.46.89 11.43 0 9 0A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58z" fill="#EA4335" />
  </svg>
);

// Same regex the backend enforces (Pydantic + the inner re-check in
// routers/companies.py). Duplicated client-side so the form gives
// immediate feedback rather than waiting on a 400 round-trip.
const SLUG_RE = /^[a-z][a-z0-9-]*$/;

// Reserved slugs match the _RESERVED_SLUGS list in backend/app/routers/
// companies.py. If a server-side rejection slips through (the list
// drifts), the backend's 400 message still surfaces — this is just for
// the live error state on the form.
const RESERVED = new Set([
  'default', 'admin', 'api', 'auth', 'login', 'signup', 'settings',
  'companies', 'apply', 'recruiter', 'report', 'reports', 'dashboard',
  'interview', 'interviews', 'www', 'support', 'help',
]);

function slugProblem(slug: string): string | null {
  if (!slug) return null;
  if (slug.length < 3) return 'Slug must be at least 3 characters.';
  if (slug.length > 40) return 'Slug must be 40 characters or fewer.';
  if (!SLUG_RE.test(slug)) {
    return 'Use lowercase letters, digits, and hyphens. Must start with a letter.';
  }
  if (RESERVED.has(slug)) return `'${slug}' is reserved — pick a different slug.`;
  return null;
}

export function CompanySignup() {
  const navigate = useNavigate();
  const { session, profile, refreshProfile, can, signUp, signInWithGoogle } = useAuth();

  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [address, setAddress] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Step 1 (signed-out founder) — the admin account that will own the
  // Company. Kept distinct from the company-details state above; the two
  // forms never render at the same time, but separate names avoid the
  // "is this the account email or the company contact email?" trap.
  const [accountName, setAccountName] = useState('');
  const [accountEmail, setAccountEmail] = useState('');
  const [accountPassword, setAccountPassword] = useState('');
  const [accountError, setAccountError] = useState<string | null>(null);
  const [accountInfo, setAccountInfo] = useState<string | null>(null);
  const [accountSubmitting, setAccountSubmitting] = useState(false);

  // Both the email-confirm link and the Google OAuth round-trip return
  // here via /auth/callback; `next` brings the founder back to this page
  // (now signed in) to finish at step 2. safeNext on the callback side
  // rejects anything off-origin.
  const companySetupRedirect =
    `${window.location.origin}/auth/callback?next=${encodeURIComponent('/companies/signup')}`;

  const handleAccountSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setAccountError(null);
    setAccountInfo(null);

    if (accountPassword.length < 6) {
      setAccountError('Password must be at least 6 characters.');
      return;
    }

    setAccountSubmitting(true);
    const { error: signUpError, needsEmailConfirm } = await signUp(
      accountEmail.trim(),
      accountPassword,
      accountName.trim(),
      { emailRedirectTo: companySetupRedirect },
    );

    if (signUpError) {
      setAccountSubmitting(false);
      setAccountError(signUpError);
      return;
    }
    if (needsEmailConfirm) {
      setAccountSubmitting(false);
      setAccountInfo(
        'Account created. Check your email to confirm, then return here to name your company.',
      );
      return;
    }

    // Immediate-session path (email-confirm disabled). Refresh the profile
    // so `can('create_company')` is ready, then the component re-renders
    // straight into step 2 (the session branch below) — no navigation, no
    // /signup detour.
    await refreshProfile();
    setAccountSubmitting(false);
  };

  const handleAccountGoogle = async () => {
    setAccountError(null);
    const { error: oauthError } = await signInWithGoogle(companySetupRedirect);
    if (oauthError) setAccountError(oauthError);
  };

  const slugError = useMemo(() => slugProblem(slug), [slug]);
  // Cheap email shape check — same shape regex the backend uses. Server is
  // still authoritative; this just avoids submitting an obviously-bad value.
  const emailLooksValid = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim());
  const canSubmit =
    !submitting &&
    name.trim().length >= 2 &&
    slug.length >= 3 &&
    !slugError &&
    emailLooksValid;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (slugError) {
      setError(slugError);
      return;
    }

    setSubmitting(true);
    try {
      await companiesApi.create({
        name: name.trim(),
        slug: slug.trim(),
        email: email.trim(),
        // Send phone/address only when provided — keeps the API payload
        // clean and the backend collapse-to-null logic stays simple.
        phone: phone.trim() || undefined,
        address: address.trim() || undefined,
      });
      // Server flipped our role to company_admin + stamped company_id.
      // Refresh local profile so the SPA's role-aware routing picks up
      // the new state on the next render.
      await refreshProfile();
      navigate('/admin', { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create company');
      setSubmitting(false);
    }
  };

  // Step 1 — signed-out founder (ADR 0009). Company registration is a
  // dedicated, self-contained flow: the founder creates their admin
  // account RIGHT HERE rather than detouring through the candidate
  // `/signup` form. On success the session lands and the component
  // re-renders into step 2 (the company-details form below). The
  // "already have one" path still round-trips through /login?next=… so
  // an existing user is returned here to finish setup.
  if (!session) {
    const LOGIN_NEXT = encodeURIComponent('/companies/signup');
    return (
      <div className="page">
        <div className="page-head">
          <div>
            <h1>Set up your company</h1>
            <p className="page-sub">
              Step 1 of 2 — create the admin account that will own your
              company.
            </p>
          </div>
        </div>
        <div className="onboard-wrap">
          <div className="card">
            {accountInfo && <div className="auth-info">{accountInfo}</div>}
            <form onSubmit={handleAccountSubmit}>
              <div className="form-group">
                <label className="form-label" htmlFor="founder-name">Full name</label>
                <input
                  id="founder-name"
                  type="text"
                  className="form-input"
                  value={accountName}
                  onChange={(e) => setAccountName(e.target.value)}
                  placeholder="Your full name"
                  autoComplete="name"
                  required
                />
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="founder-email">Work email</label>
                <input
                  id="founder-email"
                  type="email"
                  className="form-input"
                  value={accountEmail}
                  onChange={(e) => setAccountEmail(e.target.value)}
                  placeholder="you@company.com"
                  autoComplete="email"
                  required
                />
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="founder-password">Password</label>
                <input
                  id="founder-password"
                  type="password"
                  className="form-input"
                  value={accountPassword}
                  onChange={(e) => setAccountPassword(e.target.value)}
                  placeholder="At least 6 characters"
                  autoComplete="new-password"
                  required
                />
              </div>

              {accountError && <div className="error-message">{accountError}</div>}

              <button
                type="submit"
                className="btn btn-primary btn-lg"
                style={{ width: '100%', marginTop: 'var(--space-sm)' }}
                disabled={accountSubmitting}
              >
                {accountSubmitting ? 'Creating account…' : 'Create account & continue'}
              </button>
            </form>

            <div className="auth-divider">or</div>

            <button type="button" className="btn btn-google btn-lg" onClick={handleAccountGoogle}>
              <GoogleIcon />
              Continue with Google
            </button>

            <p className="auth-switch" style={{ marginTop: 'var(--space-md)' }}>
              Already have an account?{' '}
              <Link to={`/login?next=${LOGIN_NEXT}`}>Sign in →</Link>
            </p>
          </div>
        </div>
      </div>
    );
  }

  // Capability gate (ADR 0006) — `create_company` requires role='user'
  // AND company_id IS NULL. Any other caller (admin / company_admin /
  // recruiter / B2B applicant) gets the friendly explanation instead
  // of the form. Backend re-checks on submit; this is UX, not auth.
  if (profile && !can('create_company')) {
    return (
      <div className="page">
        <div className="page-head">
          <h1>Set up your company</h1>
        </div>
        <div className="card">
          <p>
            You're signed in as <strong>{profile.role}</strong>. Only standard
            users can create a company. Sign in with a different account, or
            ask the platform admin to provision a company for you.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Set up your company</h1>
          <p className="page-sub">
            Become this company's admin. You'll get a shareable link your
            candidates can use to apply.
          </p>
        </div>
      </div>

      <div className="onboard-wrap">
        <div className="card">
          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label className="form-label" htmlFor="company-name">Company name</label>
              <input
                id="company-name"
                type="text"
                className="form-input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Acme Inc."
                maxLength={80}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="company-slug">Slug</label>
              <input
                id="company-slug"
                type="text"
                className="form-input"
                value={slug}
                onChange={(e) => setSlug(e.target.value.toLowerCase())}
                placeholder="acme"
                maxLength={40}
                autoCapitalize="none"
                autoCorrect="off"
                required
              />
              <p className="form-hint">
                Your apply link will be <code>/apply/{slug || 'your-slug'}</code>.
                Lowercase letters, digits, and hyphens; must start with a letter.
              </p>
              {slug && slugError && (
                <p className="form-error">{slugError}</p>
              )}
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="company-email">Contact email</label>
              <input
                id="company-email"
                type="email"
                className="form-input"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="hr@acme.com"
                maxLength={200}
                required
              />
              <p className="form-hint">
                Surfaced on your apply page so candidates can reach you with
                questions.
              </p>
              {email && !emailLooksValid && (
                <p className="form-error">That doesn't look like a valid email address.</p>
              )}
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="company-phone">Phone <span className="form-optional">(optional)</span></label>
              <input
                id="company-phone"
                type="tel"
                className="form-input"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="+1 555 0100"
                maxLength={40}
              />
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="company-address">Address <span className="form-optional">(optional)</span></label>
              <textarea
                id="company-address"
                className="form-input"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                placeholder="Street, City, Country"
                maxLength={400}
                rows={2}
              />
            </div>

            {error && <div className="error-message">{error}</div>}

            <button
              type="submit"
              className="btn btn-primary btn-lg"
              disabled={!canSubmit}
            >
              {submitting ? 'Creating company…' : 'Create company'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
