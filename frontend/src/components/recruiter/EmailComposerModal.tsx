import { useEffect, useState } from 'react';
import { recruiterApi } from '../../services/api';
import { emailStatusLabel } from '../../utils/emailStatus';
import {
  clearEmailDraft,
  loadEmailDraft,
  saveEmailDraft,
} from '../../utils/emailDrafts';
import { EmailEditor } from '../email/EmailEditor';
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
 * Drafts (2026-06-12): still client-side only per grill E3 — but edits
 * can now be explicitly kept via Save Draft (localStorage, keyed by
 * candidate + template). A saved draft is restored on the next open
 * with a visible banner + a "discard" action that reloads the server
 * template; a successful send clears it. Closing without saving still
 * discards, unchanged.
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
  // The server-rendered template, kept so "discard saved draft" can
  // reset without a refetch.
  const [templateDraft, setTemplateDraft] = useState<EmailDraft | null>(null);
  const [restoredFromSave, setRestoredFromSave] = useState(false);
  const [draftSavedAt, setDraftSavedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  // One idempotency key per composer open (ADR 0012): a double-click or
  // retry reuses the prior send instead of emailing the candidate twice.
  const [idempotencyKey] = useState(() => crypto.randomUUID());

  const draftStorageKey = `recruiter:${candidateId}:${template}`;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    recruiterApi
      .emailDraft(candidateId, template)
      .then((d) => {
        if (cancelled) return;
        setTemplateDraft(d);
        // A previously saved draft wins over the fresh template — the
        // recruiter explicitly chose to keep those edits.
        const saved = loadEmailDraft(draftStorageKey);
        if (saved) {
          setDraft({ to: saved.to ?? d.to, subject: saved.subject, body: saved.body });
          setRestoredFromSave(true);
        } else {
          setDraft(d);
        }
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
    // draftStorageKey is derived from candidateId + template (both deps).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candidateId, template]);

  const handleSaveDraft = () => {
    if (!draft) return;
    const record = saveEmailDraft(draftStorageKey, draft);
    setDraftSavedAt(record ? record.savedAt : null);
  };

  const handleDiscardSaved = () => {
    clearEmailDraft(draftStorageKey);
    setRestoredFromSave(false);
    setDraftSavedAt(null);
    if (templateDraft) setDraft(templateDraft);
  };

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
        idempotency_key: idempotencyKey,
      });
      onSent(row);
      if (row.status !== 'sent') {
        // The server wrote an audit row but the candidate did NOT receive
        // the email — Resend rejected it, the service is disabled
        // ('failed'), or the address is on the suppression list
        // ('suppressed'). Surface the reason and don't auto-close so the
        // recruiter has to acknowledge it.
        setSendError(
          row.error_message ||
            `Email ${emailStatusLabel(row.status).toLowerCase()} — not delivered.`,
        );
        setSending(false);
        return;
      }
      clearEmailDraft(draftStorageKey);
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
            {restoredFromSave && (
              <div className="auth-info email-draft-banner">
                Restored your saved draft.{' '}
                <button type="button" className="link-btn" onClick={handleDiscardSaved}>
                  Discard and reload the template
                </button>
              </div>
            )}

            <EmailEditor draft={draft} onChange={setDraft} />

            {draftSavedAt && (
              <p className="form-hint" role="status">
                Draft saved{' '}
                {new Date(draftSavedAt).toLocaleTimeString([], {
                  hour: '2-digit',
                  minute: '2-digit',
                })}
                . It will be restored next time you open this composer.
              </p>
            )}
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
            className="btn btn-secondary"
            onClick={handleSaveDraft}
            disabled={!draft || sending || loading}
          >
            Save draft
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
