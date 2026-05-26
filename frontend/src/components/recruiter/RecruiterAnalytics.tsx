import { useEffect, useState } from 'react';
import { recruiterApi } from '../../services/api';
import type {
  FunnelFieldBreakdown,
  HiringFunnelResponse,
  IntegrityVolumeResponse,
  ScoresByFieldResponse,
} from '../../types';

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
            Hiring funnel, score distribution, and integrity-event volume across
            the platform.
          </p>
        </div>
      </div>

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
    </div>
  );
}
