import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { applyApi, jobsApi } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import type { JobPublic } from '../../types';

/**
 * Public landing for a specific OPEN job: /apply/{companySlug}/{jobSlug}
 * (migration 013). No auth required. Resolves the pair via the public
 * GET /api/jobs/public/... and shows the role on top of the same apply funnel
 * as the company landing (Apply.tsx):
 *
 *   - signed out  → "Apply now" routes to /signup?company={companySlug}
 *   - signed-in candidate → one-click claim of the company, then dashboard
 *   - draft/closed/unknown → friendly "not available" message
 *
 * Threading the job onto the eventual interview (interviews.job_id) is a
 * follow-up; this slice gets the candidate into the company via the existing,
 * working claim/signup path while showing them the specific role.
 */
export function JobApply() {
  const { companySlug = '', jobSlug = '' } = useParams<{ companySlug: string; jobSlug: string }>();
  const navigate = useNavigate();
  const { session, profile, refreshProfile } = useAuth();

  const [job, setJob] = useState<JobPublic | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [claiming, setClaiming] = useState(false);

  useEffect(() => {
    if (!companySlug || !jobSlug) {
      setLoading(false);
      setError('Missing job link.');
      return;
    }
    let cancelled = false;
    setLoading(true);
    jobsApi
      .publicLookup(companySlug, jobSlug)
      .then((data) => {
        if (!cancelled) setJob(data);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load this job');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [companySlug, jobSlug]);

  const handleApply = () => {
    navigate(`/signup?company=${encodeURIComponent(companySlug)}`);
  };

  const handleClaim = async () => {
    setClaiming(true);
    setError(null);
    try {
      await applyApi.claimCompany(companySlug);
      await refreshProfile();
      navigate('/dashboard', { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not apply to this job');
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

  if (error || !job) {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <h1 className="auth-title">Job not available</h1>
          <p className="auth-subtitle">
            {error ?? 'This job is not currently open for applications.'}
          </p>
          <p className="auth-switch">
            <Link to="/">Back to the homepage</Link>
          </p>
        </div>
      </div>
    );
  }

  const meta = [job.employment_type, job.location].filter(Boolean).join(' · ');
  const isHiringAccount = Boolean(session && profile && profile.role !== 'user');

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1 className="auth-title">{job.title}</h1>
        <p className="auth-subtitle">
          at {job.company_name}
          {meta ? ` · ${meta}` : ''}
        </p>

        {job.description && <div className="job-apply-description">{job.description}</div>}

        {isHiringAccount ? (
          <div className="error-message">
            This account manages a company and cannot apply as a candidate. Sign in
            with a personal account to apply.
          </div>
        ) : null}

        {session ? (
          <button
            type="button"
            className="btn btn-primary btn-lg btn-block"
            onClick={handleClaim}
            disabled={claiming || isHiringAccount}
          >
            {claiming ? 'Applying…' : 'Apply now'}
          </button>
        ) : (
          <button type="button" className="btn btn-primary btn-lg btn-block" onClick={handleApply}>
            Apply now
          </button>
        )}

        <p className="auth-switch" style={{ marginTop: 'var(--space-md)' }}>
          {session ? (
            <>Wrong account? <Link to="/login">Sign in with a different one</Link></>
          ) : (
            <>Already have an account?{' '}
              <Link to={`/login?company=${encodeURIComponent(companySlug)}`}>Sign in</Link></>
          )}
        </p>
      </div>
    </div>
  );
}
