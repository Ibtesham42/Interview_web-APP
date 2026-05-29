import { useState } from 'react';
import { companiesApi } from '../../services/api';
import type { InviteCandidateResponse } from '../../types';

interface InviteCandidateFormProps {
  /** Fired after the request completes — including the audit-row-with-
   * status='failed' path, where the parent may want to refresh a
   * future "previous invites" list. Optional: Settings doesn't pass
   * one; the recruiter modal does so the dashboard can react.
   *
   * The form ALWAYS shows the inline success/error banner regardless
   * of whether onSent is supplied (per grill G5 — uniform behavior
   * across both adapters: embedded card AND modal). */
  onSent?: (row: InviteCandidateResponse) => void;
}

/**
 * Per-candidate invite form. Single adapter consumed by two seams
 * (per ADR-0006-style cross-layer reuse):
 *   - Settings card on /admin/settings — embedded inline.
 *   - InviteCandidateModal on /recruiter — wrapped in a modal.
 *
 * Owns its own state (email, name, sending, message). Reuses the
 * shared `companiesApi.invite` client; the underlying endpoint is
 * gated by `'invite_candidate'` on the backend (HIRING_ROLES + tenant
 * — see backend/app/capabilities.py), and callers gate this whole
 * component with `can('invite_candidate')` so we never render in a
 * context that would 403.
 *
 * Failure semantics mirror the email composer: a Resend-rejected
 * send still produces an outbox row (status='failed') and surfaces
 * the error_message inline. Network/500 throws into the catch and
 * shows the thrown message.
 */
export function InviteCandidateForm({ onSent }: InviteCandidateFormProps) {
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [sending, setSending] = useState(false);
  const [message, setMessage] = useState<
    { kind: 'success' | 'error'; text: string } | null
  >(null);

  // Cheap shape check — mirrors the backend Pydantic regex. The server
  // is still authoritative; this just avoids submitting obvious garbage.
  const emailLooksValid = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim());

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setMessage(null);
    if (!emailLooksValid) {
      setMessage({ kind: 'error', text: "That doesn't look like a valid email." });
      return;
    }
    setSending(true);
    try {
      const row = await companiesApi.invite({
        to_email: email.trim(),
        candidate_name: name.trim() || undefined,
      });
      onSent?.(row);
      if (row.status === 'failed') {
        // Resend rejected the send (or service disabled). Surface the
        // reason; keep the form populated so the user can copy the
        // address or try again.
        setMessage({
          kind: 'error',
          text: row.error_message || 'The invite could not be delivered.',
        });
      } else {
        setMessage({
          kind: 'success',
          text: `Invite sent to ${row.to_email}.`,
        });
        setEmail('');
        setName('');
      }
    } catch (err) {
      setMessage({
        kind: 'error',
        text: err instanceof Error ? err.message : 'Failed to send invite',
      });
    } finally {
      setSending(false);
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <div className="form-group">
        <label className="form-label" htmlFor="invite-email">Email</label>
        <input
          id="invite-email"
          type="email"
          className="form-input"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
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
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Alice Smith"
          maxLength={120}
        />
        <p className="form-hint">
          Used in the email greeting. Blank is fine — we'll say "Hi
          there,".
        </p>
      </div>

      {message && (
        <div
          className={message.kind === 'success' ? 'auth-info' : 'error-message'}
          role={message.kind === 'error' ? 'alert' : undefined}
        >
          {message.text}
        </div>
      )}

      <button
        type="submit"
        className="btn btn-primary"
        disabled={sending || !emailLooksValid}
      >
        {sending ? 'Sending…' : 'Send invite'}
      </button>
    </form>
  );
}
