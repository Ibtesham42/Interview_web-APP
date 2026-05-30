import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { recruiterApi } from '../../services/api';
import { Button } from '../Button';
import { EmailComposerModal } from './EmailComposerModal';
import type {
  CandidateStatus,
  EmailOutboxRow,
  EmailTemplateKind,
  RecruiterCandidateDetail as DetailData,
  RecruiterDecision,
} from '../../types';

function scoreClass(score: number): string {
  if (score >= 7) return 'good';
  if (score >= 5.5) return 'mid';
  return 'low';
}

function fieldLabel(f: string | null): string {
  if (!f) return 'General';
  return f
    .split('_')
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(' ');
}

function formatDate(d: string | null): string {
  if (!d) return '—';
  return new Date(d).toLocaleDateString([], {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

function decisionLabel(decision: RecruiterDecision): string {
  if (decision === 'shortlisted') return 'Shortlisted';
  if (decision === 'rejected') return 'Rejected';
  if (decision === 'hold') return 'On Hold';
  return 'Undecided';
}

const STATUS_LABELS: Record<CandidateStatus, string> = {
  invited: 'Invited',
  interview_completed: 'Interview Completed',
  shortlisted: 'Shortlisted',
  rejected: 'Rejected',
  on_hold: 'On Hold',
};

// Status = the caller's terminal/parked Decision if any, else the funnel
// stage. Derived (not stored) so it always reflects the live decision.
function deriveStatus(decision: RecruiterDecision, hasCompletedInterview: boolean): CandidateStatus {
  if (decision === 'shortlisted') return 'shortlisted';
  if (decision === 'rejected') return 'rejected';
  if (decision === 'hold') return 'on_hold';
  return hasCompletedInterview ? 'interview_completed' : 'invited';
}

export function RecruiterCandidateDetail() {
  const { candidateId } = useParams<{ candidateId: string }>();
  const [data, setData] = useState<DetailData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [notesDraft, setNotesDraft] = useState('');
  const [notesSaving, setNotesSaving] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingShortlist, setPendingShortlist] = useState(false);

  // Composer modal + previous-emails panel (multi-tenant PR 7). The
  // template controls whether Shortlist/Reject pre-fills congrats vs decline.
  const [composerOpen, setComposerOpen] = useState(false);
  const [composerTemplate, setComposerTemplate] = useState<EmailTemplateKind>('shortlist');
  const [emails, setEmails] = useState<EmailOutboxRow[]>([]);
  const [emailsLoading, setEmailsLoading] = useState(false);

  const load = useCallback(() => {
    if (!candidateId) return;
    setLoading(true);
    setError(null);
    recruiterApi
      .detail(candidateId)
      .then((d) => {
        setData(d);
        setNotesDraft(d.my_notes ?? '');
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : 'Failed to load candidate');
        setData(null);
      })
      .finally(() => setLoading(false));
  }, [candidateId]);

  useEffect(() => {
    load();
  }, [load]);

  // Load the prior-emails panel alongside the candidate detail. Same
  // tenant scope as the rest of the detail page (backend enforces).
  const loadEmails = useCallback(() => {
    if (!candidateId) return;
    setEmailsLoading(true);
    recruiterApi
      .emailList(candidateId)
      .then((res) => setEmails(res.items))
      .catch(() => {
        // Email list is supplemental — don't blow up the whole detail
        // page if it fails. The composer still works.
        setEmails([]);
      })
      .finally(() => setEmailsLoading(false));
  }, [candidateId]);

  useEffect(() => {
    loadEmails();
  }, [loadEmails]);

  if (loading) {
    return (
      <div className="page">
        <div className="loading">
          <div className="spinner" />
          <div className="loading-text">Loading candidate…</div>
        </div>
      </div>
    );
  }

  if (error || !data || !candidateId) {
    return (
      <div className="page">
        <div className="empty-state">
          <h3>Couldn't load this candidate</h3>
          <p>{error || 'Candidate not found.'}</p>
          <Link to="/recruiter" className="btn btn-primary">
            Back to candidates
          </Link>
        </div>
      </div>
    );
  }

  const { candidate, interviews, decisions, my_notes, all_notes } = data;
  const myDecisionRow = decisions.find((d) => d.is_you);
  const myDecision: RecruiterDecision = myDecisionRow?.decision ?? 'undecided';
  const iAmBookmarked = !!myDecisionRow?.bookmarked;
  const integrityTotal = interviews.reduce((acc, iv) => acc + iv.integrity_warnings, 0);
  const hasCompletedInterview = interviews.some((iv) => iv.completed);
  const status = deriveStatus(myDecision, hasCompletedInterview);

  const writeDecision = async (next: RecruiterDecision) => {
    setActionError(null);
    try {
      await recruiterApi.setDecision(candidateId, next);
      load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Could not save decision');
    }
  };

  // Set the decision AND open the email composer pre-filled with the
  // matching template — the composer only opens if the status save
  // succeeds, and the recruiter can still close without sending.
  const decideAndCompose = async (
    decision: RecruiterDecision,
    template: EmailTemplateKind,
  ) => {
    setActionError(null);
    try {
      await recruiterApi.setDecision(candidateId, decision);
      setComposerTemplate(template);
      setComposerOpen(true);
      load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Could not save decision');
    }
  };

  const handleShortlistClick = () => {
    // Toggling OFF a shortlist is a silent status change — no email.
    if (myDecision === 'shortlisted') {
      void writeDecision('undecided');
      return;
    }
    if (integrityTotal > 0) {
      setPendingShortlist(true);
      return;
    }
    void decideAndCompose('shortlisted', 'shortlist');
  };

  const handleRejectClick = () => {
    if (myDecision === 'rejected') {
      void writeDecision('undecided');
      return;
    }
    void decideAndCompose('rejected', 'rejection');
  };

  // Hold is a parked, reversible state — no email is sent for it.
  const handleHoldClick = () => {
    void writeDecision(myDecision === 'hold' ? 'undecided' : 'hold');
  };

  const confirmShortlist = async () => {
    setPendingShortlist(false);
    await decideAndCompose('shortlisted', 'shortlist');
  };

  const handleBookmarkToggle = async () => {
    setActionError(null);
    try {
      await recruiterApi.setBookmark(candidateId, !iAmBookmarked);
      load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Could not save bookmark');
    }
  };

  const handleNotesSave = async () => {
    setNotesSaving(true);
    setActionError(null);
    try {
      await recruiterApi.setNotes(candidateId, notesDraft);
      load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Could not save notes');
    } finally {
      setNotesSaving(false);
    }
  };

  const notesDirty = notesDraft !== (my_notes ?? '');

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <Link to="/recruiter" className="back-link">
            ← Candidates
          </Link>
          <h1>
            {candidate.name}
            <span className={`status-chip status-${status}`}>{STATUS_LABELS[status]}</span>
          </h1>
          <p className="page-sub">
            {fieldLabel(candidate.field_specialization)}
            {' · '}
            {candidate.email || 'no email on file'}
            {' · '}joined {formatDate(candidate.created_at)}
          </p>
        </div>
        <div className="recruiter-detail-actions">
          <Button
            variant={myDecision === 'shortlisted' ? 'primary' : 'secondary'}
            onClick={handleShortlistClick}
            aria-pressed={myDecision === 'shortlisted'}
          >
            {myDecision === 'shortlisted' ? '✓ Shortlisted' : 'Shortlist'}
          </Button>
          <Button
            variant={myDecision === 'hold' ? 'primary' : 'secondary'}
            onClick={handleHoldClick}
            aria-pressed={myDecision === 'hold'}
            title="Park this candidate for later (no email sent)"
          >
            {myDecision === 'hold' ? '⏸ On Hold' : 'Hold'}
          </Button>
          <Button
            variant={myDecision === 'rejected' ? 'danger' : 'secondary'}
            onClick={handleRejectClick}
            aria-pressed={myDecision === 'rejected'}
          >
            {myDecision === 'rejected' ? '✗ Rejected' : 'Reject'}
          </Button>
          <Button
            variant="secondary"
            onClick={() => {
              setComposerTemplate('shortlist');
              setComposerOpen(true);
            }}
            title="Compose an email to this candidate"
          >
            ✉ Send email
          </Button>
          <button
            type="button"
            className={`icon-btn${iAmBookmarked ? ' active' : ''}`}
            onClick={() => void handleBookmarkToggle()}
            aria-label={iAmBookmarked ? 'Remove bookmark' : 'Bookmark candidate'}
            aria-pressed={iAmBookmarked}
            title={iAmBookmarked ? 'Bookmarked' : 'Bookmark'}
          >
            {iAmBookmarked ? '★' : '☆'}
          </button>
        </div>
      </div>

      {composerOpen && (
        <EmailComposerModal
          candidateId={candidateId}
          candidateName={candidate.name}
          template={composerTemplate}
          onSent={(row) => {
            // Optimistically prepend the new row so the recruiter sees
            // their send in the panel immediately. A subsequent fetch
            // overwrites with the server's canonical list.
            setEmails((prior) => [row, ...prior]);
            loadEmails();
          }}
          onClose={() => setComposerOpen(false)}
        />
      )}

      {actionError && (
        <div className="recruiter-action-error" role="alert">
          {actionError}
        </div>
      )}

      <div className="stat-grid auto">
        <div className="stat-card">
          <div className="stat-value">{interviews.length}</div>
          <div className="stat-label">Interviews</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">
            {interviews.filter((iv) => iv.completed).length}
          </div>
          <div className="stat-label">Completed</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{integrityTotal}</div>
          <div className="stat-label">Integrity warnings</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{decisions.length}</div>
          <div className="stat-label">Recruiter decisions</div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head">
          <h3>Interview history</h3>
        </div>
        {interviews.length === 0 ? (
          <p className="report-empty">No interviews yet.</p>
        ) : (
          <div className="iv-list">
            {interviews.map((iv) => {
              const inner = (
                <>
                  <div className="iv-row-main">
                    <div className="iv-row-title">{formatDate(iv.created_at)} interview</div>
                    <div className="iv-row-sub">
                      {iv.questions} question{iv.questions === 1 ? '' : 's'} · status: {iv.status}
                    </div>
                  </div>
                  <div className="iv-row-meta">
                    {iv.integrity_terminated ? (
                      <span className="integrity-flag-chip terminated">Terminated</span>
                    ) : iv.integrity_warnings > 0 ? (
                      <span className="integrity-flag-chip">
                        {iv.integrity_warnings} warning{iv.integrity_warnings === 1 ? '' : 's'}
                      </span>
                    ) : null}
                    {iv.completed ? (
                      <span className={`score-badge score-bg-${scoreClass(iv.score)}`}>
                        {iv.score.toFixed(1)} · {iv.recommendation}
                      </span>
                    ) : (
                      <span className="iv-status-chip">In progress</span>
                    )}
                  </div>
                </>
              );
              return iv.completed ? (
                <Link key={iv.interview_id} to={`/report/${iv.interview_id}`} className="iv-row">
                  {inner}
                </Link>
              ) : (
                <div key={iv.interview_id} className="iv-row iv-row-static">
                  {inner}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="panel">
        <div className="panel-head">
          <h3>Emails sent ({emails.length})</h3>
        </div>
        {emailsLoading ? (
          <p className="report-empty">Loading messages…</p>
        ) : emails.length === 0 ? (
          <p className="report-empty">
            No emails sent yet. Click <strong>Send email</strong> above to write
            the first one.
          </p>
        ) : (
          <div className="email-list">
            {emails.map((em) => (
              <div key={em.id} className="email-row">
                <div className="email-row-head">
                  <span className="email-row-subject">{em.subject}</span>
                  <span
                    className={`email-status-chip email-status-${em.status}`}
                    title={em.error_message || ''}
                  >
                    {em.status === 'sent' ? 'Sent' : 'Failed'}
                  </span>
                </div>
                <div className="email-row-meta">
                  to {em.to_email} · {formatDate(em.sent_at)}
                </div>
                {em.status === 'failed' && em.error_message && (
                  <div className="email-row-error">{em.error_message}</div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="panel">
        <div className="panel-head">
          <h3>Decisions</h3>
        </div>
        {decisions.length === 0 ? (
          <p className="report-empty">No recruiter has made a decision yet.</p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Recruiter</th>
                  <th>Decision</th>
                  <th>Bookmark</th>
                  <th>Decided</th>
                </tr>
              </thead>
              <tbody>
                {decisions.map((d) => (
                  <tr key={d.recruiter_id} className="iv-row-static">
                    <td>
                      {d.recruiter_name}
                      {d.is_you && <span className="cell-sub"> (you)</span>}
                    </td>
                    <td>
                      <span className={`decision-chip decision-${d.decision}`}>
                        {decisionLabel(d.decision)}
                      </span>
                    </td>
                    <td>{d.bookmarked ? '★' : <span className="cell-sub">—</span>}</td>
                    <td className="cell-sub">{formatDate(d.decided_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="panel">
        <div className="panel-head">
          <h3>Your notes</h3>
          <span className="cell-sub">Only you can read these</span>
        </div>
        <div className="recruiter-notes-editor recruiter-notes-detail">
          <textarea
            className="recruiter-notes-textarea"
            value={notesDraft}
            onChange={(e) => setNotesDraft(e.target.value)}
            rows={6}
            maxLength={4000}
            placeholder="Strengths, follow-ups, comparisons…"
          />
          <div className="recruiter-notes-actions">
            <Button
              variant="primary"
              size="sm"
              disabled={notesSaving || !notesDirty}
              onClick={() => void handleNotesSave()}
            >
              {notesSaving ? 'Saving…' : 'Save notes'}
            </Button>
          </div>
        </div>
      </div>

      {all_notes && all_notes.length > 0 && (
        <div className="panel">
          <div className="panel-head">
            <h3>All recruiters' notes</h3>
            <span className="cell-sub">Admin view</span>
          </div>
          <div className="all-notes-list">
            {all_notes.map((entry) => (
              <div key={entry.recruiter_id} className="all-notes-entry">
                <div className="all-notes-meta">
                  <strong>{entry.recruiter_name}</strong>
                  <span className="cell-sub">· {formatDate(entry.updated_at)}</span>
                </div>
                {entry.notes ? (
                  <p className="all-notes-body">{entry.notes}</p>
                ) : (
                  <p className="cell-sub">No notes written yet.</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {pendingShortlist && (
        <div
          className="modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-labelledby="detail-shortlist-confirm-title"
          onClick={() => setPendingShortlist(false)}
        >
          <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
            <h3 id="detail-shortlist-confirm-title">Shortlist a flagged candidate?</h3>
            <p>
              <strong>{candidate.name}</strong> has {integrityTotal} integrity warning
              {integrityTotal === 1 ? '' : 's'} on file. Shortlisting is your call —
              the signal is advisory, not a hard block. Review the interview report
              before deciding.
            </p>
            <div className="modal-actions">
              <Button variant="secondary" onClick={() => setPendingShortlist(false)}>
                Cancel
              </Button>
              <Button variant="primary" onClick={() => void confirmShortlist()}>
                Shortlist anyway
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
