import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';

/**
 * Landing route for the Google OAuth redirect. The Supabase client parses the
 * session out of the URL automatically; this screen just waits for the session
 * to settle and then forwards the user on.
 */
export function AuthCallback() {
  const { session, loading } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (loading) return;
    navigate(session ? '/' : '/login', { replace: true });
  }, [session, loading, navigate]);

  return (
    <div className="auth-loading">
      <div className="spinner" />
      <p>Signing you in…</p>
    </div>
  );
}
