import { useState } from 'react';
import { toPreviewParagraphs } from '../../utils/emailPreview';
import type { EmailDraft } from '../../types';

interface EmailEditorProps {
  draft: EmailDraft;
  onChange: (draft: EmailDraft) => void;
  /** Hide the To field when the host form owns the recipient (invite flow). */
  showTo?: boolean;
  /** Sender identity line shown in Preview so the sender sees the whole
   * envelope, e.g. `Acme via Rehearsify`. Optional — omitted renders none. */
  fromLabel?: string;
}

/**
 * Shared subject/body editor with an Edit ↔ Preview toggle. Used by the
 * recruiter EmailComposerModal and the editable-invite flow — one editor,
 * no duplicate email UIs.
 *
 * Preview intentionally mirrors the backend's render_email_html output
 * (paragraphs, line breaks, clickable links) via the segment helpers in
 * utils/emailPreview — rendered as React elements, never as an HTML
 * string, so typed content cannot become live markup.
 */
export function EmailEditor({ draft, onChange, showTo = true, fromLabel }: EmailEditorProps) {
  const [mode, setMode] = useState<'edit' | 'preview'>('edit');

  return (
    <div className="email-editor">
      <div className="email-editor-tabs" role="tablist" aria-label="Email editor mode">
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'edit'}
          className={`email-editor-tab${mode === 'edit' ? ' active' : ''}`}
          onClick={() => setMode('edit')}
        >
          Edit
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'preview'}
          className={`email-editor-tab${mode === 'preview' ? ' active' : ''}`}
          onClick={() => setMode('preview')}
        >
          Preview
        </button>
      </div>

      {mode === 'edit' ? (
        <>
          {showTo && (
            <div className="form-group">
              <label className="form-label" htmlFor="email-to">To</label>
              <input
                id="email-to"
                type="email"
                className="form-input"
                value={draft.to}
                onChange={(e) => onChange({ ...draft, to: e.target.value })}
                placeholder="candidate@example.com"
                required
              />
              {!draft.to && (
                <p className="form-hint">
                  No email on file for this candidate — add one to send.
                </p>
              )}
            </div>
          )}

          <div className="form-group">
            <label className="form-label" htmlFor="email-subject">Subject</label>
            <input
              id="email-subject"
              type="text"
              className="form-input"
              value={draft.subject}
              onChange={(e) => onChange({ ...draft, subject: e.target.value })}
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
              onChange={(e) => onChange({ ...draft, body: e.target.value })}
              rows={10}
              required
            />
            <p className="form-hint">
              Plain text — line breaks are preserved and links become
              clickable. The AI draft is a starting point; edit freely,
              then check Preview before sending.
            </p>
          </div>
        </>
      ) : (
        <div className="email-preview" aria-label="Email preview">
          <div className="email-preview-envelope">
            {fromLabel && (
              <div className="email-preview-row">
                <span className="email-preview-label">From</span>
                <span>{fromLabel}</span>
              </div>
            )}
            <div className="email-preview-row">
              <span className="email-preview-label">To</span>
              <span>{draft.to || '—'}</span>
            </div>
            <div className="email-preview-row">
              <span className="email-preview-label">Subject</span>
              <strong>{draft.subject || '(no subject)'}</strong>
            </div>
          </div>
          <div className="email-preview-body">
            {toPreviewParagraphs(draft.body).map((paragraph, pi) => (
              <p key={pi}>
                {paragraph.map((line, li) => (
                  <span key={li}>
                    {li > 0 && <br />}
                    {line.map((segment, si) =>
                      segment.kind === 'link' ? (
                        <a
                          key={si}
                          href={segment.value}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {segment.value}
                        </a>
                      ) : (
                        <span key={si}>{segment.value}</span>
                      ),
                    )}
                  </span>
                ))}
              </p>
            ))}
            {!draft.body.trim() && <p className="report-empty">Nothing to preview yet.</p>}
          </div>
        </div>
      )}
    </div>
  );
}
