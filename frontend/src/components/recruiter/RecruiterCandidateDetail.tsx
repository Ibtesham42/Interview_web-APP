import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { recruiterApi } from '../../services/api';
import { Button } from '../Button';
import type {
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
  return 'Undecided';
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

  const writeDecision = async (next: RecruiterDecision) => {
    setActionError(null);
    try {
      await recruiterApi.setDecision(candidateId, next);
      load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Could not save decision');
    }
  };

  const handleShortlistClick = () => {
    if (myDecision === 'shortlisted') {
      void writeDecision('undecided');
      return;
    }
    if (integrityTotal > 0) {
      setPendingShortlist(true);
      return;
    }
    void writeDecision('shortlisted');
  };

  const handleRejectClick = () => {
    void writeDecision(myDecision === 'rejected' ? 'undecided' : 'rejected');
  };

  const confirmShortlist = async () => {
    setPendingShortlist(false);
    await writeDecision('shortlisted');
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
          <h1>{candidate.name}</h1>
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
            variant={myDecision === 'rejected' ? 'danger' : 'secondary'}
            onClick={handleRejectClick}
            aria-pressed={myDecision === 'rejected'}
          >
            {myDecision === 'rejected' ? '✗ Rejected' : 'Reject'}
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
