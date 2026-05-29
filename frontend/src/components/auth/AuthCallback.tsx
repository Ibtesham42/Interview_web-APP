import { useEffect, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { applyApi } from '../../services/api';
import { safeNext } from '../../utils/safeNext';

/**
 * Landing route for the Google OAuth redirect AND the email-confirm
 * link (both Supabase auth flows route here). The Supabase client
 * parses the session out of the URL automatically; this screen waits
 * for the session to settle and then forwards the user.
 *
 * Multi-tenant PR 4: if the URL carries `?company=slug` (the apply
 * link threaded its slug through the auth redirect), claim membership
 * in that company AFTER the session lands. The claim is idempotent on
 * the server, so a retry from a hot-reload or refresh is safe.
 */
export function AuthCallback() {
  const { session, loading, refreshProfile } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const claimedRef = useRef(false);

  useEffect(() => {
    if (loading) return;

    const company = searchParams.get('company');
    // `?next=/path` (2026-05-29 follow-up — company-setup round-trip).
    // safeNext rejects off-origin / protocol-relative values so a
    // malicious OAuth redirect can't ship the user off-platform.
    const target = safeNext(searchParams.get('next'));

    if (!session) {
      navigate('/login', { replace: true });
      return;
    }
    if (!company || claimedRef.current) {
      navigate(target, { replace: true });
      return;
    }
    // Claim the company once per mount. The ref guards against the
    // session/loading dependency re-firing this effect after we've
    // already done the work.
    claimedRef.current = true;
    applyApi
      .claimCompany(company)
      .catch(() => {
        // Surface nothing — the user already has a session; the worst
        // case is they remain a B2C user, which they can fix by
        // hitting /apply/{slug} again. Logging is server-side only.
      })
      .finally(() => {
        refreshProfile()
          .finally(() => navigate(target, { replace: true }));
      });
  }, [session, loading, searchParams, navigate, refreshProfile]);

  return (
    <div className="auth-loading">
      <div className="spinner" />
      <p>Signing you in…</p>
    </div>
  );
}
