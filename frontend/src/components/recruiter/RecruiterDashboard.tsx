import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { recruiterApi } from '../../services/api';
import { Button } from '../Button';
import type {
  RecruiterCandidate,
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

function decisionLabel(decision: RecruiterCandidate['decision']): string {
  if (decision === 'shortlisted') return 'Shortlisted';
  if (decision === 'rejected') return 'Rejected';
  return 'Undecided';
}

interface PillProps<T extends string> {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  label?: T;
}

function Pill<T extends string>({ active, onClick, children }: PillProps<T>) {
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

export function RecruiterDashboard() {
  const navigate = useNavigate();

  // Filter state — held in component-local state so a single user keystroke
  // doesn't refetch immediately (search is debounced; pill clicks are
  // immediate).
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

  // Debounce the search box — 300ms per RECRUITER_ROLLOUT spec. The debounce
  // is intentionally local to this component since search-as-you-type isn't a
  // pattern used elsewhere in the app yet.
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchInput.trim()), 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  // Reset to page 1 whenever the result-shape changes — otherwise a user
  // sitting on page 3 with a new filter applied sees a blank page.
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
        if (!cancelled) setData(resp);
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

  // Collect the distinct fields seen in the current page so the field-filter
  // pills surface what's actually present. Falls back to a small fixed set
  // when no data has loaded yet, so the row of pills doesn't pop in.
  const fieldOptions = useMemo(() => {
    const seen = new Set<string>();
    for (const row of data?.items ?? []) {
      if (row.field_specialization) seen.add(row.field_specialization);
    }
    if (seen.size === 0) return ['ml', 'web_dev', 'general'];
    return Array.from(seen).sort();
  }, [data]);

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
                </tr>
              </thead>
              <tbody>
                {data?.items.map((row) => (
                  <tr
                    key={row.candidate_id}
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
                  </tr>
                ))}
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
    </div>
  );
}
