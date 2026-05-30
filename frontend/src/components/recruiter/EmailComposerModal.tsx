import { useEffect, useState } from 'react';
import { recruiterApi } from '../../services/api';
import type { EmailDraft, EmailOutboxRow, EmailTemplateKind } from '../../types';

interface EmailComposerModalProps {
  candidateId: string;
  candidateName: string;
  /** Which default template to pre-fill (candidate status management).
   * 'shortlist' (default) for advance-to-next-round; 'rejection' for a
   * courtesy decline. The recruiter edits freely before Send either way. */
  template?: EmailTemplateKind;
  /** Fired after a successful send so the parent can refresh the
   * "previous messages" list. The argument is the outbox row that
   * was written — `status` reflects what actually happened (a
   * Resend-failed send still produces a row + invokes onSent, so
   * the parent can surface the failure in-line). */
  onSent: (row: EmailOutboxRow) => void;
  onClose: () => void;
}

/**
 * Composer modal for the recruiter Shortlist + Email flow (multi-
 * tenant PR 7). Loads a template-rendered draft from the backend,
 * lets the recruiter edit `to` / subject / body, then POSTs to
 * `/email/send`.
 *
 * Per grill E3, drafts are client-side only — closing the modal
 * discards any edits. The same modal mounts fresh each open, so the
 * server template is the source of truth on every Send.
 *
 * Failure handling:
 *   - Draft fetch error → in-modal error banner; Send disabled.
 *   - Send returns `status='failed'` (Resend rejected or service
 *     disabled) → modal stays open, error_message rendered as a
 *     prominent banner. Caller's onSent is still fired so the
 *     previous-messages list refreshes.
 *   - Send threw (network blip, 500) → in-modal error; modal stays
 *     open so the recruiter can retry without losing edits.
 */
export function EmailComposerModal({
  candidateId,
  candidateName,
  template = 'shortlist',
  onSent,
  onClose,
}: EmailComposerModalProps) {
  const [draft, setDraft] = useState<EmailDraft | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    recruiterApi
      .emailDraft(candidateId, template)
      .then((d) => {
        if (!cancelled) setDraft(d);
      })
      .catch((err) => {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : 'Could not load draft');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [candidateId, template]);

  // Close on Escape — standard modal-dismiss UX. Click-outside also
  // closes (handled in the backdrop's onClick below).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const handleSend = async () => {
    if (!draft) return;
    if (!draft.to.trim()) {
      setSendError('Recipient email is required.');
      return;
    }
    setSending(true);
    setSendError(null);
    try {
      const row = await recruiterApi.emailSend(candidateId, {
        to: draft.to.trim(),
        subject: draft.subject.trim(),
        body: draft.body,
      });
      onSent(row);
      if (row.status === 'failed') {
        // The server wrote an audit row but Resend rejected the send
        // (or the service is disabled). Surface the reason in the
        // modal so the recruiter knows the candidate did NOT receive
        // the email. Don't auto-close — the user has to acknowledge.
        setSendError(row.error_message || 'Email could not be delivered.');
        setSending(false);
        return;
      }
      onClose();
    } catch (err) {
      setSendError(err instanceof Error ? err.message : 'Send failed');
      setSending(false);
    }
  };

  return (
    <div className="email-composer-backdrop" onClick={onClose}>
      <div
        className="email-composer-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={`Send email to ${candidateName}`}
      >
        <div className="email-composer-head">
          <h3>Send email to {candidateName}</h3>
          <button
            type="button"
            className="icon-btn"
            onClick={onClose}
            aria-label="Close"
            title="Close"
          >
            ✕
          </button>
        </div>

        {loading ? (
          <div className="email-composer-loading">
            <div className="spinner" />
            <p>Preparing draft…</p>
          </div>
        ) : loadError ? (
          <div className="email-composer-body">
            <div className="error-message">{loadError}</div>
          </div>
        ) : draft ? (
          <div className="email-composer-body">
            <div className="form-group">
              <label className="form-label" htmlFor="email-to">To</label>
              <input
                id="email-to"
                type="email"
                className="form-input"
                value={draft.to}
                onChange={(e) => setDraft({ ...draft, to: e.target.value })}
                placeholder="candidate@example.com"
                required
              />
              {!draft.to && (
                <p className="form-hint">
                  No email on file for this candidate — add one to send.
                </p>
              )}
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="email-subject">Subject</label>
              <input
                id="email-subject"
                type="text"
                className="form-input"
                value={draft.subject}
                onChange={(e) => setDraft({ ...draft, subject: e.target.value })}
                maxLength={200}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="email-body">Message</label>
              <textarea
                id="email-body"
                className="form-input email-composer-textarea"
                value={draft.body}
                onChange={(e) => setDraft({ ...draft, body: e.target.value })}
                rows={10}
                required
              />
              <p className="form-hint">
                Plain text. Line breaks are preserved. Edit as much as you
                like before sending — the template is just a starting point.
              </p>
            </div>

            {sendError && <div className="error-message">{sendError}</div>}
          </div>
        ) : null}

        <div className="email-composer-foot">
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onClose}
            disabled={sending}
          >
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleSend}
            disabled={!draft || sending || loading || !!loadError}
          >
            {sending ? 'Sending…' : 'Send email'}
          </button>
        </div>
      </div>
    </div>
  );
}
