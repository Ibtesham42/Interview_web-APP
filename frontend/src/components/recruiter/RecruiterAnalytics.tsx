import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { recruiterApi } from '../../services/api';
import type {
  CandidateStatus,
  FunnelFieldBreakdown,
  HiringFunnelResponse,
  IntegrityVolumeResponse,
  RecruiterAnalyticsSummary,
  ScoresByFieldResponse,
} from '../../types';

const STATUS_LABELS: Record<CandidateStatus, string> = {
  invited: 'Invited',
  interview_completed: 'Interview Completed',
  shortlisted: 'Shortlisted',
  rejected: 'Rejected',
  on_hold: 'On Hold',
};

function formatDate(d: string | null): string {
  if (!d) return '—';
  return new Date(d).toLocaleDateString([], {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

function fieldLabel(f: string): string {
  if (!f) return 'General';
  return f
    .split('_')
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(' ');
}

function eventTypeLabel(t: string): string {
  if (!t) return 'Unknown';
  return t
    .split('_')
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(' ');
}

function scoreClass(s: number): string {
  if (s >= 7) return 'good';
  if (s >= 5.5) return 'mid';
  return 'low';
}

const STAGE_LABELS: Record<string, string> = {
  signed_up: 'Signed up',
  interview_started: 'Started',
  interview_completed: 'Completed',
  shortlisted: 'Shortlisted',
};

const RATE_LABELS: { key: keyof HiringFunnelResponse['conversion_rates']; label: string }[] = [
  { key: 'signed_up_to_started', label: 'Signed up → Started' },
  { key: 'started_to_completed', label: 'Started → Completed' },
  { key: 'completed_to_shortlisted', label: 'Completed → Shortlisted' },
];

interface FunnelProps {
  data: { stages: HiringFunnelResponse['stages']; conversion_rates: HiringFunnelResponse['conversion_rates'] };
  variant?: 'main' | 'compact';
}

function FunnelBars({ data, variant = 'main' }: FunnelProps) {
  const max = Math.max(...data.stages.map((s) => s.count), 1);
  return (
    <div className={`funnel-bars${variant === 'compact' ? ' compact' : ''}`}>
      {data.stages.map((stage) => {
        const widthPct = (stage.count / max) * 100;
        return (
          <div key={stage.stage} className="funnel-row">
            <span className="funnel-label">{STAGE_LABELS[stage.stage] ?? stage.stage}</span>
            <div className="funnel-track">
              <div
                className="funnel-fill"
                style={{ width: `${Math.max(widthPct, stage.count > 0 ? 2 : 0)}%` }}
              />
            </div>
            <span className="funnel-count">{stage.count}</span>
          </div>
        );
      })}
    </div>
  );
}

interface ByFieldEntry {
  field: string;
  breakdown: FunnelFieldBreakdown;
}

function byFieldEntries(byField: Record<string, FunnelFieldBreakdown>): ByFieldEntry[] {
  return Object.entries(byField)
    .map(([field, breakdown]) => ({ field, breakdown }))
    .sort(
      (a, b) =>
        (b.breakdown.stages[0]?.count ?? 0) - (a.breakdown.stages[0]?.count ?? 0),
    );
}

export function RecruiterAnalytics() {
  const [funnel, setFunnel] = useState<HiringFunnelResponse | null>(null);
  const [scores, setScores] = useState<ScoresByFieldResponse | null>(null);
  const [integrity, setIntegrity] = useState<IntegrityVolumeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Summary KPIs (company all-time) + filterable recent activity.
  const [summary, setSummary] = useState<RecruiterAnalyticsSummary | null>(null);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [statusFilter, setStatusFilter] = useState<CandidateStatus | ''>('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  useEffect(() => {
    let cancelled = false;
    Promise.all([recruiterApi.funnel(), recruiterApi.scores(), recruiterApi.integrity()])
      .then(([f, s, i]) => {
        if (cancelled) return;
        setFunnel(f);
        setScores(s);
        setIntegrity(i);
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Failed to load analytics');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Summary refetches (debounced) whenever a filter changes. Totals are
  // company-wide and don't move with the filters; the recent-activity
  // list does. Failures are swallowed — the summary is supplemental to
  // the funnel/scores/integrity panels above.
  useEffect(() => {
    const handle = window.setTimeout(() => {
      recruiterApi
        .summary({
          name: name || undefined,
          email: email || undefined,
          status: statusFilter || undefined,
          date_from: dateFrom ? `${dateFrom}T00:00:00Z` : undefined,
          date_to: dateTo ? `${dateTo}T23:59:59Z` : undefined,
        })
        .then(setSummary)
        .catch(() => {
          /* keep prior summary; supplemental panel */
        });
    }, 300);
    return () => window.clearTimeout(handle);
  }, [name, email, statusFilter, dateFrom, dateTo]);

  if (loading) {
    return (
      <div className="page">
        <div className="loading">
          <div className="spinner" />
          <div className="loading-text">Loading analytics…</div>
        </div>
      </div>
    );
  }

  if (error || !funnel || !scores || !integrity) {
    return (
      <div className="page">
        <div className="empty-state">
          <h3>Couldn't load analytics</h3>
          <p>{error || 'Try refreshing the page.'}</p>
        </div>
      </div>
    );
  }

  const fieldEntries = byFieldEntries(funnel.by_field);
  const maxScoreAvg = Math.max(...scores.items.map((i) => i.average_score), 1);
  const maxIntegrityCount = Math.max(...integrity.items.map((i) => i.count), 1);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Recruiter analytics</h1>
          <p className="page-sub">
            Candidate pipeline, hiring funnel, scores, and integrity volume.
          </p>
        </div>
      </div>

      {summary && (
        <div className="stat-grid auto">
          <div className="stat-card">
            <div className="stat-value">{summary.totals.invited}</div>
            <div className="stat-label">Invited</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{summary.totals.registrations}</div>
            <div className="stat-label">Registrations</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{summary.totals.interviews_completed}</div>
            <div className="stat-label">Interviews completed</div>
          </div>
          <div className="stat-card">
            <div className="stat-value score-good">{summary.totals.shortlisted}</div>
            <div className="stat-label">Shortlisted</div>
          </div>
          <div className="stat-card">
            <div className="stat-value score-low">{summary.totals.rejected}</div>
            <div className="stat-label">Rejected</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{summary.totals.on_hold}</div>
            <div className="stat-label">On hold</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{summary.totals.completion_rate}%</div>
            <div className="stat-label">Completion rate</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{summary.totals.shortlist_rate}%</div>
            <div className="stat-label">Shortlist rate</div>
          </div>
        </div>
      )}

      <div className="panel">
        <div className="panel-head">
          <h3>Hiring funnel</h3>
          <span className="cell-sub">
            Terminates at Shortlisted — the platform doesn't observe hire events
            (ADR 0004).
          </span>
        </div>
        <div className="funnel-panel">
          <FunnelBars data={funnel} />
          <div className="conversion-grid">
            {RATE_LABELS.map(({ key, label }) => (
              <div key={key} className="conversion-card">
                <div className="conversion-rate">{funnel.conversion_rates[key]}%</div>
                <div className="conversion-label">{label}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {fieldEntries.length > 0 && (
        <div className="panel">
          <div className="panel-head">
            <h3>Funnel by field</h3>
          </div>
          <div className="funnel-field-grid">
            {fieldEntries.map(({ field, breakdown }) => (
              <div key={field} className="funnel-field-card">
                <div className="funnel-field-title">{fieldLabel(field)}</div>
                <FunnelBars data={breakdown} variant="compact" />
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="panel">
        <div className="panel-head">
          <h3>Score distribution by field</h3>
          <span className="cell-sub">Average of each candidate's best completed score</span>
        </div>
        {scores.items.length === 0 ? (
          <p className="report-empty">No completed interviews yet.</p>
        ) : (
          <div className="score-bars">
            {scores.items.map((item) => {
              const widthPct = (item.average_score / maxScoreAvg) * 100;
              return (
                <div key={item.field} className="score-bar-row">
                  <span className="score-bar-label">{fieldLabel(item.field)}</span>
                  <div className="score-bar-track">
                    <div
                      className={`score-bar-fill score-bg-${scoreClass(item.average_score)}`}
                      style={{ width: `${Math.max(widthPct, 2)}%` }}
                    />
                  </div>
                  <span className="score-bar-value">
                    {item.average_score.toFixed(1)}
                    <span className="cell-sub"> · {item.candidate_count} candidate{item.candidate_count === 1 ? '' : 's'}</span>
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="panel">
        <div className="panel-head">
          <h3>Integrity events</h3>
          <span className="cell-sub">{integrity.total} total · by event type</span>
        </div>
        {integrity.items.length === 0 ? (
          <p className="report-empty">No integrity events recorded.</p>
        ) : (
          <div className="score-bars">
            {integrity.items.map((item) => {
              const widthPct = (item.count / maxIntegrityCount) * 100;
              return (
                <div key={item.event_type} className="score-bar-row">
                  <span className="score-bar-label">{eventTypeLabel(item.event_type)}</span>
                  <div className="score-bar-track">
                    <div
                      className="score-bar-fill score-bg-integrity"
                      style={{ width: `${Math.max(widthPct, 2)}%` }}
                    />
                  </div>
                  <span className="score-bar-value">{item.count}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="panel">
        <div className="panel-head">
          <h3>Recent candidate activity</h3>
          <span className="cell-sub">
            {summary?.recent_total ?? 0} matching · filters apply to this list
          </span>
        </div>

        <div className="analytics-filter-bar">
          <input
            className="form-input"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Filter by name"
            aria-label="Filter by candidate name"
          />
          <input
            className="form-input"
            type="text"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Filter by email"
            aria-label="Filter by candidate email"
          />
          <select
            className="form-input"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as CandidateStatus | '')}
            aria-label="Filter by status"
          >
            <option value="">All statuses</option>
            <option value="invited">Invited</option>
            <option value="interview_completed">Interview Completed</option>
            <option value="shortlisted">Shortlisted</option>
            <option value="rejected">Rejected</option>
            <option value="on_hold">On Hold</option>
          </select>
          <input
            className="form-input"
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            aria-label="Interviews from date"
          />
          <input
            className="form-input"
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            aria-label="Interviews to date"
          />
        </div>

        {!summary ? (
          <p className="report-empty">Loading activity…</p>
        ) : summary.recent_activity.length === 0 ? (
          <p className="report-empty">No candidates match these filters.</p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Candidate</th>
                  <th>Status</th>
                  <th>Best score</th>
                  <th>Last interview</th>
                </tr>
              </thead>
              <tbody>
                {summary.recent_activity.map((row) => (
                  <tr key={row.candidate_id}>
                    <td>
                      <Link to={`/recruiter/candidates/${row.candidate_id}`} className="cell-name">
                        {row.name || 'Unnamed candidate'}
                      </Link>
                      <div className="cell-sub">{row.email || '—'}</div>
                    </td>
                    <td>
                      <span className={`status-chip status-${row.status}`}>
                        {STATUS_LABELS[row.status]}
                      </span>
                    </td>
                    <td>
                      {row.best_score > 0 ? (
                        <span className={`score-${scoreClass(row.best_score)}`}>
                          {row.best_score.toFixed(1)}
                        </span>
                      ) : (
                        <span className="cell-sub">—</span>
                      )}
                    </td>
                    <td className="cell-sub">{formatDate(row.last_interview_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
