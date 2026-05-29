import { useEffect } from 'react';
import { InviteCandidateForm } from '../companies/InviteCandidateForm';
import type { InviteCandidateResponse } from '../../types';

interface InviteCandidateModalProps {
  onClose: () => void;
  /** Optional — fired after the underlying request completes (success
   * or audit-with-failed). A future "Previous invites" panel on the
   * recruiter dashboard could use this to refresh; today no caller
   * passes one. */
  onSent?: (row: InviteCandidateResponse) => void;
}

/**
 * Modal wrapper around <InviteCandidateForm/> for the recruiter
 * dashboard's "+ Invite candidate" action.
 *
 * Shape mirrors EmailComposerModal for visual + behavioral
 * consistency across recruiter-surface modals (ESC + backdrop click
 * dismiss; reuses .email-composer-* CSS).
 *
 * Per grill G5: the modal stays open after a send. The form's inline
 * banner conveys success/failure; the user dismisses the modal
 * manually. No auto-close, no toast system.
 */
export function InviteCandidateModal({ onClose, onSent }: InviteCandidateModalProps) {
  // ESC closes the modal — matches EmailComposerModal.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="email-composer-backdrop" onClick={onClose}>
      <div
        className="email-composer-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Invite a candidate"
      >
        <div className="email-composer-head">
          <h3>Invite a candidate</h3>
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

        <div className="email-composer-body">
          <p className="page-sub" style={{ marginTop: 0 }}>
            We'll email them a personalized invite with your apply link.
            Use this when you want to nudge a specific person instead of
            sharing the public URL broadly.
          </p>
          <InviteCandidateForm onSent={onSent} />
        </div>
      </div>
    </div>
  );
}
