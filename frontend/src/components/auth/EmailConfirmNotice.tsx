import { useState } from 'react';
import { useAuth } from '../../contexts/AuthContext';

interface EmailConfirmNoticeProps {
  /** The address the confirmation link was sent to. */
  email: string;
  /** Same redirect the original signup used, so the resent link lands the
   * user back in the right flow. */
  emailRedirectTo?: string;
  /** What happens after they confirm — e.g. "Then return here to name your
   * company." Flow-specific, supplied by the caller. */
  nextHint: string;
}

/**
 * Shown after signup when Supabase requires email confirmation. Replaces the
 * old one-line "check your email" message with a recoverable state: the
 * address is surfaced, spam/Google guidance is given, and a resend button
 * (with a cooldown) lets a user whose first mail never arrived retry without
 * re-entering the form. Addresses the production gap where a flaky/unconfigured
 * SMTP left founders/candidates permanently stuck.
 */
export function EmailConfirmNotice({ email, emailRedirectTo, nextHint }: EmailConfirmNoticeProps) {
  const { resendConfirmation } = useAuth();
  const [status, setStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(false);

  const handleResend = async () => {
    if (cooldown || status === 'sending') return;
    setStatus('sending');
    setErrorMsg(null);
    const { error } = await resendConfirmation(email, { emailRedirectTo });
    if (error) {
      setStatus('error');
      setErrorMsg(error);
      return;
    }
    setStatus('sent');
    setCooldown(true);
    // Supabase rate-limits resends; a short client cooldown stops a user
    // hammering the button into a 429.
    window.setTimeout(() => setCooldown(false), 30000);
  };

  return (
    <div className="email-confirm">
      <h2 className="email-confirm-title">Confirm your email</h2>
      <p className="email-confirm-body">
        We sent a confirmation link to <strong>{email}</strong>. {nextHint}
      </p>
      <ul className="email-confirm-hints">
        <li>It can take a minute — check your spam or promotions folder.</li>
        <li>
          Prefer not to wait? Go back and use <strong>Continue with Google</strong> —
          it skips email confirmation.
        </li>
      </ul>
      <button
        type="button"
        className="btn btn-secondary"
        onClick={handleResend}
        disabled={cooldown || status === 'sending'}
      >
        {status === 'sending'
          ? 'Resending…'
          : cooldown
            ? 'Sent — check your inbox'
            : 'Resend confirmation email'}
      </button>
      {status === 'sent' && (
        <p className="form-hint">A fresh confirmation link is on its way.</p>
      )}
      {status === 'error' && <p className="form-error">{errorMsg}</p>}
    </div>
  );
}
