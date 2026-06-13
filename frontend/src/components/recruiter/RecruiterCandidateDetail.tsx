import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { recruiterApi } from '../../services/api';
import { emailStatusIsPositive, emailStatusLabel } from '../../utils/emailStatus';
import { Button } from '../Button';
import {
  Badge,
  Card,
  CardHeader,
  CardTitle,
  EmptyState,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from '../ui';
import type { BadgeVariant } from '../ui';
import { EmailComposerModal } from './EmailComposerModal';
import { RecommendationCard } from './RecommendationCard';
import type {
  CandidateStatus,
  EmailOutboxRow,
  EmailTemplateKind,
  RecruiterCandidateDetail as DetailData,
  RecruiterDecision,
} from '../../types';

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

// Map domain states to Badge variants so colour meaning is consistent with
// the rest of the design system (Phase 3 primitive adoption).
function statusVariant(s: CandidateStatus): BadgeVariant {
  if (s === 'shortlisted') return 'success';
  if (s === 'rejected') return 'danger';
  if (s === 'on_hold') return 'warning';
  if (s === 'invited') return 'info';
  return 'neutral';
}

function decisionVariant(d: RecruiterDecision): BadgeVariant {
  if (d === 'shortlisted') return 'success';
  if (d === 'rejected') return 'danger';
  if (d === 'hold') return 'warning';
  return 'neutral';
}

function scoreVariant(score: number): BadgeVariant {
  if (score >= 7) return 'success';
  if (score >= 5.5) return 'warning';
  return 'danger';
}

function emailStatusVariant(s: EmailOutboxRow['status']): BadgeVariant {
  if (s === 'sent' || s === 'delivered') return 'success';
  if (s === 'failed' || s === 'bounced') return 'danger';
  if (s === 'suppressed' || s === 'complained') return 'warning';
  return 'neutral';
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
          <div className="flex flex-wrap items-center gap-2">
            <h1>{candidate.name}</h1>
            <Badge variant={statusVariant(status)}>{STATUS_LABELS[status]}</Badge>
          </div>
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

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Card padding="md">
          <div className="text-2xl font-semibold text-ink">{interviews.length}</div>
          <div className="mt-1 text-xs text-ink-subtle">Interviews</div>
        </Card>
        <Card padding="md">
          <div className="text-2xl font-semibold text-ink">
            {interviews.filter((iv) => iv.completed).length}
          </div>
          <div className="mt-1 text-xs text-ink-subtle">Completed</div>
        </Card>
        <Card padding="md">
          <div className="text-2xl font-semibold text-ink">{integrityTotal}</div>
          <div className="mt-1 text-xs text-ink-subtle">Integrity warnings</div>
        </Card>
        <Card padding="md">
          <div className="text-2xl font-semibold text-ink">{decisions.length}</div>
          <div className="mt-1 text-xs text-ink-subtle">Recruiter decisions</div>
        </Card>
      </div>

      <RecommendationCard candidateId={candidateId} />

      <Card>
        <CardHeader>
          <CardTitle>Interview history</CardTitle>
        </CardHeader>
        {interviews.length === 0 ? (
          <EmptyState
            title="No interviews yet"
            description="This candidate hasn't completed an interview."
          />
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
                      <Badge variant="danger">Terminated</Badge>
                    ) : iv.integrity_warnings > 0 ? (
                      <Badge variant="warning">
                        {iv.integrity_warnings} warning{iv.integrity_warnings === 1 ? '' : 's'}
                      </Badge>
                    ) : null}
                    {iv.completed ? (
                      <Badge variant={scoreVariant(iv.score)}>
                        {iv.score.toFixed(1)} · {iv.recommendation}
                      </Badge>
                    ) : (
                      <Badge variant="neutral">In progress</Badge>
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
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Emails sent ({emails.length})</CardTitle>
        </CardHeader>
        {emailsLoading ? (
          <p className="text-sm text-ink-muted">Loading messages…</p>
        ) : emails.length === 0 ? (
          <EmptyState
            title="No emails sent yet"
            description="Use the Send email button above to contact this candidate."
          />
        ) : (
          <div className="email-list">
            {emails.map((em) => (
              <div key={em.id} className="email-row">
                <div className="email-row-head">
                  <span className="email-row-subject">{em.subject}</span>
                  <Badge variant={emailStatusVariant(em.status)} title={em.error_message || ''}>
                    {emailStatusLabel(em.status)}
                  </Badge>
                </div>
                <div className="email-row-meta">
                  to {em.to_email} · {formatDate(em.sent_at)}
                  {em.last_event_at && ` · updated ${formatDate(em.last_event_at)}`}
                </div>
                {!emailStatusIsPositive(em.status) && em.error_message && (
                  <div className="email-row-error">{em.error_message}</div>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Decisions</CardTitle>
        </CardHeader>
        {decisions.length === 0 ? (
          <EmptyState
            title="No decisions yet"
            description="No recruiter has made a decision on this candidate."
          />
        ) : (
          <Table>
            <TableHead>
              <TableRow>
                <TableHeaderCell>Recruiter</TableHeaderCell>
                <TableHeaderCell>Decision</TableHeaderCell>
                <TableHeaderCell>Bookmark</TableHeaderCell>
                <TableHeaderCell>Decided</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {decisions.map((d) => (
                <TableRow key={d.recruiter_id}>
                  <TableCell>
                    {d.recruiter_name}
                    {d.is_you && <span className="text-ink-subtle"> (you)</span>}
                  </TableCell>
                  <TableCell>
                    <Badge variant={decisionVariant(d.decision)}>{decisionLabel(d.decision)}</Badge>
                  </TableCell>
                  <TableCell>
                    {d.bookmarked ? '★' : <span className="text-ink-subtle">—</span>}
                  </TableCell>
                  <TableCell className="text-ink-subtle">{formatDate(d.decided_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Your notes</CardTitle>
          <span className="text-xs text-ink-subtle">Only you can read these</span>
        </CardHeader>
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
      </Card>

      {all_notes && all_notes.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>All recruiters' notes</CardTitle>
            <span className="text-xs text-ink-subtle">Admin view</span>
          </CardHeader>
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
        </Card>
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
