import { Fragment, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { recruiterApi } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import { Button } from '../Button';
import { InviteCandidateModal } from './InviteCandidateModal';
import type {
  RecruiterCandidate,
  RecruiterDecision,
  RecruiterDecisionFilter,
  RecruiterIntegrityFilter,
  RecruiterListParams,
  RecruiterListResponse,
  RecruiterSortField,
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

interface PillProps {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}

function Pill({ active, onClick, children }: PillProps) {
  return (
    <button
      type="button"
      className={`filter-pill${active ? ' active' : ''}`}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

const SORT_OPTIONS: { value: RecruiterSortField; label: string }[] = [
  { value: 'final_score', label: 'Score' },
  { value: 'created_at', label: 'Signed up' },
  { value: 'name', label: 'Name' },
  { value: 'decision', label: 'Decision' },
  { value: 'integrity_warnings', label: 'Integrity' },
];

const DECISION_OPTIONS: { value: RecruiterDecisionFilter | ''; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'shortlisted', label: 'Shortlisted' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'undecided', label: 'Undecided' },
  { value: 'bookmarked', label: 'Bookmarked' },
];

const INTEGRITY_OPTIONS: { value: RecruiterIntegrityFilter | ''; label: string }[] = [
  { value: '', label: 'Any integrity' },
  { value: 'with_warnings', label: 'Flagged only' },
  { value: 'without_warnings', label: 'Clean only' },
];

const DEFAULT_PAGE_SIZE = 25;

// Workflow signals the actions mutate locally before/without a refetch.
type RowOverride = Partial<Pick<RecruiterCandidate, 'decision' | 'bookmarked' | 'notes'>>;

interface PendingShortlist {
  candidateId: string;
  name: string;
  warnings: number;
}

export function RecruiterDashboard() {
  const navigate = useNavigate();
  const { can } = useAuth();

  // Invite-candidate modal — opened from the `+ Invite candidate` button
  // in the page header. Gated by `can('invite_candidate')` which requires
  // a hiring role AND a tenant (ADR 0006). A recruiter with NULL
  // company_id (legacy / orphaned profile) sees no button.
  const [inviteOpen, setInviteOpen] = useState(false);

  const [searchInput, setSearchInput] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [field, setField] = useState('');
  const [decision, setDecision] = useState<RecruiterDecisionFilter | ''>('');
  const [integrity, setIntegrity] = useState<RecruiterIntegrityFilter | ''>('');
  const [sort, setSort] = useState<RecruiterSortField>('final_score');
  const [order, setOrder] = useState<'asc' | 'desc'>('desc');
  const [page, setPage] = useState(1);

  const [data, setData] = useState<RecruiterListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Optimistic local overrides per candidate. The server is the source of
  // truth, but the user shouldn't wait a round-trip to see their own click
  // land. On API failure we revert; on success we keep the override until
  // the next fetch refreshes the row anyway.
  const [overrides, setOverrides] = useState<Record<string, RowOverride>>({});
  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingShortlist, setPendingShortlist] = useState<PendingShortlist | null>(null);
  const [expandedNotes, setExpandedNotes] = useState<string | null>(null);
  const [notesDraft, setNotesDraft] = useState('');
  const [notesSaving, setNotesSaving] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchInput.trim()), 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, field, decision, integrity, sort, order]);

  const params: RecruiterListParams = useMemo(
    () => ({
      search: debouncedSearch || undefined,
      field: field || undefined,
      decision: decision || undefined,
      integrity: integrity || undefined,
      sort,
      order,
      page,
      page_size: DEFAULT_PAGE_SIZE,
    }),
    [debouncedSearch, field, decision, integrity, sort, order, page],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    recruiterApi
      .candidates(params)
      .then((resp) => {
        if (!cancelled) {
          setData(resp);
          // A fresh fetch wins over stale overrides - the server reflects
          // every committed change at this point.
          setOverrides({});
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Failed to load candidates');
          setData(null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [params]);

  const rows: RecruiterCandidate[] = useMemo(() => {
    if (!data) return [];
    return data.items.map((row) => {
      const override = overrides[row.candidate_id];
      return override ? { ...row, ...override } : row;
    });
  }, [data, overrides]);

  const fieldOptions = useMemo(() => {
    const seen = new Set<string>();
    for (const row of rows) {
      if (row.field_specialization) seen.add(row.field_specialization);
    }
    if (seen.size === 0) return ['ml', 'web_dev', 'general'];
    return Array.from(seen).sort();
  }, [rows]);

  const hasActiveFilters =
    !!debouncedSearch || !!field || !!decision || !!integrity;

  const handleClearFilters = () => {
    setSearchInput('');
    setField('');
    setDecision('');
    setIntegrity('');
  };

  const handleSortChange = (value: RecruiterSortField) => {
    if (value === sort) {
      setOrder((prev) => (prev === 'desc' ? 'asc' : 'desc'));
    } else {
      setSort(value);
      setOrder(value === 'name' ? 'asc' : 'desc');
    }
  };

  // Apply an override immediately, fire the API call, roll back on error.
  const applyOverride = (candidateId: string, patch: RowOverride) =>
    setOverrides((prev) => ({
      ...prev,
      [candidateId]: { ...prev[candidateId], ...patch },
    }));

  const rollbackOverride = (candidateId: string, previous: RowOverride) =>
    setOverrides((prev) => ({
      ...prev,
      [candidateId]: { ...prev[candidateId], ...previous },
    }));

  const writeDecision = async (row: RecruiterCandidate, next: RecruiterDecision) => {
    setActionError(null);
    const previous: RowOverride = { decision: row.decision };
    applyOverride(row.candidate_id, { decision: next });
    try {
      await recruiterApi.setDecision(row.candidate_id, next);
    } catch (e) {
      rollbackOverride(row.candidate_id, previous);
      setActionError(e instanceof Error ? e.message : 'Could not save decision');
    }
  };

  const handleShortlistClick = (row: RecruiterCandidate) => {
    // B2: soft-warn on shortlisting an integrity-flagged Candidate.
    if (row.integrity_warnings > 0) {
      setPendingShortlist({
        candidateId: row.candidate_id,
        name: row.name,
        warnings: row.integrity_warnings,
      });
      return;
    }
    void writeDecision(row, 'shortlisted');
  };

  const confirmPendingShortlist = async () => {
    if (!pendingShortlist) return;
    const row = rows.find((r) => r.candidate_id === pendingShortlist.candidateId);
    setPendingShortlist(null);
    if (row) await writeDecision(row, 'shortlisted');
  };

  const handleReject = (row: RecruiterCandidate) => {
    void writeDecision(row, row.decision === 'rejected' ? 'undecided' : 'rejected');
  };

  const handleBookmarkToggle = async (row: RecruiterCandidate) => {
    setActionError(null);
    const previous: RowOverride = { bookmarked: row.bookmarked };
    const next = !row.bookmarked;
    applyOverride(row.candidate_id, { bookmarked: next });
    try {
      await recruiterApi.setBookmark(row.candidate_id, next);
    } catch (e) {
      rollbackOverride(row.candidate_id, previous);
      setActionError(e instanceof Error ? e.message : 'Could not save bookmark');
    }
  };

  const handleNotesToggle = (row: RecruiterCandidate) => {
    if (expandedNotes === row.candidate_id) {
      setExpandedNotes(null);
      return;
    }
    setExpandedNotes(row.candidate_id);
    setNotesDraft(row.notes ?? '');
  };

  const handleNotesSave = async (row: RecruiterCandidate) => {
    setActionError(null);
    setNotesSaving(true);
    const previous: RowOverride = { notes: row.notes };
    applyOverride(row.candidate_id, { notes: notesDraft });
    try {
      await recruiterApi.setNotes(row.candidate_id, notesDraft);
      setExpandedNotes(null);
    } catch (e) {
      rollbackOverride(row.candidate_id, previous);
      setActionError(e instanceof Error ? e.message : 'Could not save notes');
    } finally {
      setNotesSaving(false);
    }
  };

  const totalPages = data
    ? Math.max(1, Math.ceil(data.total_count / data.page_size))
    : 1;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Candidates</h1>
          <p className="page-sub">
            Search, filter and shortlist candidates across the platform.
          </p>
        </div>
        {/* Capability gate: HIRING_ROLES + tenant. A recruiter with no
            company_id (legacy / orphaned) sees nothing here. */}
        {can('invite_candidate') && (
          <Button variant="primary" onClick={() => setInviteOpen(true)}>
            + Invite candidate
          </Button>
        )}
      </div>

      <div className="recruiter-filter-bar">
        <input
          type="search"
          className="recruiter-search"
          placeholder="Search by name, field or resume…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          aria-label="Search candidates"
        />

        <div className="recruiter-pill-row" role="group" aria-label="Field">
          <Pill active={field === ''} onClick={() => setField('')}>
            All fields
          </Pill>
          {fieldOptions.map((f) => (
            <Pill key={f} active={field === f} onClick={() => setField(f)}>
              {fieldLabel(f)}
            </Pill>
          ))}
        </div>

        <div className="recruiter-pill-row" role="group" aria-label="Decision">
          {DECISION_OPTIONS.map((opt) => (
            <Pill
              key={opt.value || 'all-decisions'}
              active={decision === opt.value}
              onClick={() => setDecision(opt.value)}
            >
              {opt.label}
            </Pill>
          ))}
        </div>

        <div className="recruiter-pill-row" role="group" aria-label="Integrity">
          {INTEGRITY_OPTIONS.map((opt) => (
            <Pill
              key={opt.value || 'any-integrity'}
              active={integrity === opt.value}
              onClick={() => setIntegrity(opt.value)}
            >
              {opt.label}
            </Pill>
          ))}
        </div>

        {hasActiveFilters && (
          <Button variant="secondary" size="sm" onClick={handleClearFilters}>
            Clear filters
          </Button>
        )}
      </div>

      <div className="recruiter-result-line">
        {loading ? (
          <span>Loading candidates…</span>
        ) : data ? (
          <span>
            {data.total_count} candidate{data.total_count === 1 ? '' : 's'}
            {hasActiveFilters ? ' match' : ''}
          </span>
        ) : null}
        {data?.formula_mixed && (
          <span className="formula-mixed-advisory" role="note">
            Mixed scoring formulas on this page — older interviews use the
            pre-Matryoshka formula. Scores are still comparable as
            recommendation tiers.
          </span>
        )}
      </div>

      {actionError && (
        <div className="recruiter-action-error" role="alert">
          {actionError}
        </div>
      )}

      {error ? (
        <div className="empty-state">
          <h3>Couldn't load candidates</h3>
          <p>{error}</p>
        </div>
      ) : !loading && data && data.items.length === 0 ? (
        <div className="empty-state">
          <h3>No candidates {hasActiveFilters ? 'match these filters' : 'yet'}</h3>
          {hasActiveFilters ? (
            <p>Try clearing a filter to widen the search.</p>
          ) : (
            <p>Candidates appear here as soon as they sign up.</p>
          )}
        </div>
      ) : (
        <div className="panel">
          <div className="table-wrap">
            <table className="data-table recruiter-table">
              <thead>
                <tr>
                  {SORT_OPTIONS.map((opt) => {
                    const active = sort === opt.value;
                    return (
                      <th key={opt.value}>
                        <button
                          type="button"
                          className={`sort-header${active ? ' active' : ''}`}
                          onClick={() => handleSortChange(opt.value)}
                          aria-label={`Sort by ${opt.label}`}
                        >
                          {opt.label}
                          <span className="sort-arrow" aria-hidden="true">
                            {active ? (order === 'desc' ? '↓' : '↑') : ''}
                          </span>
                        </button>
                      </th>
                    );
                  })}
                  <th>Field</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const isExpanded = expandedNotes === row.candidate_id;
                  return (
                    <Fragment key={row.candidate_id}>
                      <tr
                        onClick={() => navigate(`/recruiter/candidates/${row.candidate_id}`)}
                        aria-label={`Open ${row.name}`}
                      >
                        <td>
                          <div className="cell-score">
                            {row.final_score > 0 ? (
                              <>
                                <span
                                  className={`score-dot score-bg-${scoreClass(row.final_score)}`}
                                  aria-hidden="true"
                                />
                                <span className={`score-${scoreClass(row.final_score)}`}>
                                  {row.final_score.toFixed(1)}
                                </span>
                                <span className="score-rec">{row.recommendation}</span>
                              </>
                            ) : (
                              <span className="cell-sub">—</span>
                            )}
                          </div>
                        </td>
                        <td className="cell-sub">{formatDate(row.created_at)}</td>
                        <td>
                          <div className="cell-name">
                            {row.name}
                            {row.bookmarked && (
                              <span
                                className="bookmark-flag"
                                aria-label="Bookmarked"
                                title="Bookmarked"
                              >
                                ★
                              </span>
                            )}
                          </div>
                          <div className="cell-sub">{row.email || '—'}</div>
                        </td>
                        <td>
                          <span className={`decision-chip decision-${row.decision}`}>
                            {decisionLabel(row.decision)}
                          </span>
                        </td>
                        <td>
                          {row.integrity_warnings > 0 ? (
                            <span className="integrity-flag-chip">
                              {row.integrity_warnings} warning
                              {row.integrity_warnings === 1 ? '' : 's'}
                            </span>
                          ) : (
                            <span className="cell-sub">—</span>
                          )}
                        </td>
                        <td className="cell-sub">{fieldLabel(row.field_specialization)}</td>
                        <td
                          className="recruiter-actions-cell"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <div className="recruiter-actions">
                            <Button
                              variant={row.decision === 'shortlisted' ? 'primary' : 'secondary'}
                              size="sm"
                              onClick={() =>
                                row.decision === 'shortlisted'
                                  ? void writeDecision(row, 'undecided')
                                  : handleShortlistClick(row)
                              }
                              aria-pressed={row.decision === 'shortlisted'}
                              title={
                                row.decision === 'shortlisted'
                                  ? 'Remove from shortlist'
                                  : 'Shortlist'
                              }
                            >
                              {row.decision === 'shortlisted' ? '✓ Shortlisted' : 'Shortlist'}
                            </Button>
                            <Button
                              variant={row.decision === 'rejected' ? 'danger' : 'secondary'}
                              size="sm"
                              onClick={() => handleReject(row)}
                              aria-pressed={row.decision === 'rejected'}
                              title={row.decision === 'rejected' ? 'Clear rejection' : 'Reject'}
                            >
                              {row.decision === 'rejected' ? '✗ Rejected' : 'Reject'}
                            </Button>
                            <button
                              type="button"
                              className={`icon-btn${row.bookmarked ? ' active' : ''}`}
                              onClick={() => void handleBookmarkToggle(row)}
                              aria-label={
                                row.bookmarked ? 'Remove bookmark' : 'Bookmark candidate'
                              }
                              aria-pressed={row.bookmarked}
                              title={row.bookmarked ? 'Bookmarked' : 'Bookmark'}
                            >
                              {row.bookmarked ? '★' : '☆'}
                            </button>
                            <Button
                              variant="secondary"
                              size="sm"
                              onClick={() => handleNotesToggle(row)}
                              aria-expanded={isExpanded}
                              title={row.notes ? 'View / edit notes' : 'Add notes'}
                            >
                              {row.notes ? `Notes (${row.notes.length})` : 'Notes'}
                            </Button>
                          </div>
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr
                          className="recruiter-notes-row"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <td colSpan={7}>
                            <div className="recruiter-notes-editor">
                              <label
                                className="recruiter-notes-label"
                                htmlFor={`notes-${row.candidate_id}`}
                              >
                                Notes about {row.name}
                                <span className="cell-sub">
                                  {' '}
                                  · only you can read these
                                </span>
                              </label>
                              <textarea
                                id={`notes-${row.candidate_id}`}
                                className="recruiter-notes-textarea"
                                value={notesDraft}
                                onChange={(e) => setNotesDraft(e.target.value)}
                                rows={4}
                                maxLength={4000}
                                placeholder="Strengths, follow-ups, comparisons…"
                              />
                              <div className="recruiter-notes-actions">
                                <Button
                                  variant="secondary"
                                  size="sm"
                                  onClick={() => setExpandedNotes(null)}
                                >
                                  Cancel
                                </Button>
                                <Button
                                  variant="primary"
                                  size="sm"
                                  disabled={notesSaving || notesDraft === (row.notes ?? '')}
                                  onClick={() => void handleNotesSave(row)}
                                >
                                  {notesSaving ? 'Saving…' : 'Save notes'}
                                </Button>
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>

          {data && data.total_count > data.page_size && (
            <div className="recruiter-pagination">
              <Button
                variant="secondary"
                size="sm"
                disabled={page <= 1 || loading}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                Previous
              </Button>
              <span className="recruiter-page-label">
                Page {data.page} of {totalPages}
              </span>
              <Button
                variant="secondary"
                size="sm"
                disabled={page >= totalPages || loading}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          )}
        </div>
      )}

      {pendingShortlist && (
        <div
          className="modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-labelledby="shortlist-confirm-title"
          onClick={() => setPendingShortlist(null)}
        >
          <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
            <h3 id="shortlist-confirm-title">Shortlist a flagged candidate?</h3>
            <p>
              <strong>{pendingShortlist.name}</strong> has{' '}
              {pendingShortlist.warnings} integrity warning
              {pendingShortlist.warnings === 1 ? '' : 's'} on file. Shortlisting
              is your call — the signal is advisory, not a hard block. Review
              the interview report before deciding.
            </p>
            <div className="modal-actions">
              <Button variant="secondary" onClick={() => setPendingShortlist(null)}>
                Cancel
              </Button>
              <Button variant="primary" onClick={() => void confirmPendingShortlist()}>
                Shortlist anyway
              </Button>
            </div>
          </div>
        </div>
      )}

      {inviteOpen && (
        <InviteCandidateModal onClose={() => setInviteOpen(false)} />
      )}
    </div>
  );
}
