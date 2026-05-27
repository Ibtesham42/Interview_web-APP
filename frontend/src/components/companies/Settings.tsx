import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { companiesApi } from '../../services/api';

/**
 * Company settings — /admin/settings (multi-tenant PR 5).
 *
 * Today this page does ONE thing: surface the company's shareable
 * apply URL with a copy-to-clipboard button. A company_admin sends
 * this URL to candidates; visiting it routes them through the
 * /apply/{slug} signup flow that stamps `company_id` on first
 * sign-in (PR 4).
 *
 * Deferred for follow-up PRs:
 * - Rename company / change slug (immutable for the rollout).
 * - Invite teammates as company_admin / recruiter.
 * - Toggle `signup_open` to pause new applicants without breaking
 *   the URL.
 * - Email-from address override (Resend domain configuration).
 *
 * Auth: route-gated to company_admin (App.tsx). A platform admin who
 * navigates here directly sees the empty-state message — they don't
 * have a company.
 */
export function Settings() {
  const { company, profile } = useAuth();
  const [copied, setCopied] = useState(false);

  // Invite-a-candidate card state. Email is required; name is the
  // optional friendly name shown in the email greeting. After a
  // successful send we surface a transient confirmation; failure keeps
  // the form populated so the admin can retry without retyping.
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteName, setInviteName] = useState('');
  const [inviteSending, setInviteSending] = useState(false);
  const [inviteMessage, setInviteMessage] = useState<
    { kind: 'success' | 'error'; text: string } | null
  >(null);

  const inviteEmailLooksValid = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(inviteEmail.trim());

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    setInviteMessage(null);
    if (!inviteEmailLooksValid) {
      setInviteMessage({ kind: 'error', text: "That doesn't look like a valid email." });
      return;
    }
    setInviteSending(true);
    try {
      const row = await companiesApi.invite({
        to_email: inviteEmail.trim(),
        candidate_name: inviteName.trim() || undefined,
      });
      if (row.status === 'failed') {
        // Resend rejected the send (or service disabled). Surface the
        // reason; keep the form populated so the admin can copy the
        // address or try again.
        setInviteMessage({
          kind: 'error',
          text: row.error_message || 'The invite could not be delivered.',
        });
      } else {
        setInviteMessage({
          kind: 'success',
          text: `Invite sent to ${row.to_email}.`,
        });
        setInviteEmail('');
        setInviteName('');
      }
    } catch (err) {
      setInviteMessage({
        kind: 'error',
        text: err instanceof Error ? err.message : 'Failed to send invite',
      });
    } finally {
      setInviteSending(false);
    }
  };

  // Platform admin (NULL company_id) and B2C users land here only if
  // the route gate is misconfigured; surface a friendly message
  // instead of an empty page.
  if (!company) {
    return (
      <div className="page">
        <div className="page-head">
          <h1>Company settings</h1>
        </div>
        <div className="card">
          <p>
            {profile?.role === 'admin'
              ? 'Platform admins do not belong to a company. Manage companies via the database directly until an admin-of-admins surface ships.'
              : 'You are not a member of any company. Visit an apply link or create your own company to manage settings.'}
          </p>
          {profile?.role === 'user' && (
            <p style={{ marginTop: 'var(--space-md)' }}>
              <Link to="/companies/signup" className="btn btn-secondary">Create a company</Link>
            </p>
          )}
        </div>
      </div>
    );
  }

  // Build the candidate-facing URL. `window.location.origin` gives the
  // domain the company_admin is currently looking at, which is the
  // domain they'll share — same origin avoids the "the link doesn't
  // match the email I'd send" friction.
  const applyUrl = `${window.location.origin}/apply/${company.slug}`;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(applyUrl);
      setCopied(true);
      // Reset the "Copied!" state after a beat so subsequent copies
      // still surface affordance.
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      // Clipboard write can fail on insecure (http) origins or older
      // browsers. The URL is still visible in the input so users can
      // select-and-copy manually — no error state needed.
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Company settings</h1>
          <p className="page-sub">
            Managing <strong>{company.name}</strong>. These settings only affect
            your company's candidates.
          </p>
        </div>
      </div>

      <div className="settings-grid">
        <div className="card">
          <h3>Shareable apply link</h3>
          <p className="page-sub" style={{ marginTop: 'var(--space-xs)' }}>
            Send this URL to candidates. They'll create an account from there
            and land directly in your candidates list. The URL is permanent —
            anyone with it can apply, so share it the same way you share a
            jobs-page link.
          </p>
          <div className="settings-link-row">
            <input
              type="text"
              className="form-input"
              value={applyUrl}
              readOnly
              onFocus={(e) => e.currentTarget.select()}
              aria-label="Apply link URL"
            />
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleCopy}
            >
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
        </div>

        <div className="card">
          <h3>Invite a candidate</h3>
          <p className="page-sub" style={{ marginTop: 'var(--space-xs)' }}>
            We'll email them a personalized invite with your apply link.
            Use this when you want to nudge a specific person instead of
            sharing the public URL broadly.
          </p>
          <form onSubmit={handleInvite}>
            <div className="form-group">
              <label className="form-label" htmlFor="invite-email">Email</label>
              <input
                id="invite-email"
                type="email"
                className="form-input"
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                placeholder="candidate@example.com"
                required
              />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="invite-name">
                Name <span className="form-optional">(optional)</span>
              </label>
              <input
                id="invite-name"
                type="text"
                className="form-input"
                value={inviteName}
                onChange={(e) => setInviteName(e.target.value)}
                placeholder="Alice Smith"
                maxLength={120}
              />
              <p className="form-hint">
                Used in the email greeting. Blank is fine — we'll say "Hi
                there,".
              </p>
            </div>

            {inviteMessage && (
              <div
                className={
                  inviteMessage.kind === 'success'
                    ? 'auth-info'
                    : 'error-message'
                }
                role={inviteMessage.kind === 'error' ? 'alert' : undefined}
              >
                {inviteMessage.text}
              </div>
            )}

            <button
              type="submit"
              className="btn btn-primary"
              disabled={inviteSending || !inviteEmailLooksValid}
            >
              {inviteSending ? 'Sending…' : 'Send invite'}
            </button>
          </form>
        </div>

        <div className="card">
          <h3>Company</h3>
          <dl className="settings-meta">
            <div>
              <dt>Name</dt>
              <dd>{company.name}</dd>
            </div>
            <div>
              <dt>Slug</dt>
              <dd><code>{company.slug}</code></dd>
            </div>
            <div>
              <dt>Contact email</dt>
              <dd>{company.email || <span className="cell-sub">—</span>}</dd>
            </div>
            {company.phone && (
              <div>
                <dt>Phone</dt>
                <dd>{company.phone}</dd>
              </div>
            )}
            {company.address && (
              <div>
                <dt>Address</dt>
                <dd>{company.address}</dd>
              </div>
            )}
            <div>
              <dt>Created</dt>
              <dd>{new Date(company.created_at).toLocaleDateString()}</dd>
            </div>
          </dl>
        </div>
      </div>
    </div>
  );
}
