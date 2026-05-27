import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { companiesApi } from '../../services/api';

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
  const { profile, refreshProfile } = useAuth();

  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const slugError = useMemo(() => slugProblem(slug), [slug]);
  const canSubmit = !submitting && name.trim().length >= 2 && slug.length >= 3 && !slugError;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (slugError) {
      setError(slugError);
      return;
    }

    setSubmitting(true);
    try {
      await companiesApi.create({ name: name.trim(), slug: slug.trim() });
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

  // Defensive: if the route's role gate is bypassed somehow, surface a
  // friendly message instead of letting the user trip the server-side
  // 403 silently.
  if (profile && profile.role !== 'user') {
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
