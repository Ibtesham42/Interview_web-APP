import { useEffect, useState } from 'react';
import { recruiterApi } from '../../services/api';
import { Badge, Card, CardHeader, CardTitle, EmptyState } from '../ui';
import type { BadgeVariant } from '../ui';
import type { Recommendation } from '../../types';

function tierVariant(rec: string | null): BadgeVariant {
  if (rec === 'Strong Hire' || rec === 'Hire') return 'success';
  if (rec === 'Hold') return 'warning';
  if (rec === 'No Hire') return 'danger';
  return 'neutral';
}

/**
 * Explainable AI recommendation for a candidate (Phase 2). Fetches its own
 * data so the detail page stays simple. Shows the recommendation tier + final
 * weighted score and a per-phase breakdown whose `contribution`s sum to the
 * final — the "why" behind the number. Advisory only; it never writes a
 * decision (the recruiter's Shortlist/Reject buttons own that).
 */
export function RecommendationCard({ candidateId }: { candidateId: string }) {
  const [data, setData] = useState<Recommendation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    recruiterApi
      .recommendation(candidateId)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load the recommendation');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [candidateId]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>AI recommendation</CardTitle>
        <span className="text-xs text-ink-subtle">Advisory · from interview scores</span>
      </CardHeader>

      {loading ? (
        <p className="text-sm text-ink-muted">Scoring…</p>
      ) : error ? (
        <EmptyState title="Couldn't load the recommendation" description={error} />
      ) : !data || data.final_score === null ? (
        <p className="text-sm text-ink-muted">{data?.summary ?? 'No scored interview yet.'}</p>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-3">
            <Badge variant={tierVariant(data.recommendation)}>{data.recommendation}</Badge>
            <span className="text-2xl font-semibold text-ink">{data.final_score.toFixed(1)}</span>
            <span className="text-xs text-ink-subtle">/ 10 weighted</span>
          </div>
          <p className="text-sm text-ink-muted">{data.summary}</p>

          <div className="flex flex-col gap-3">
            {data.phase_breakdown.map((p) => (
              <div key={p.phase} className="flex flex-col gap-1">
                <div className="flex items-baseline justify-between text-sm">
                  <span className="text-ink">{p.phase_name}</span>
                  <span className="text-ink-subtle">
                    {p.overall.toFixed(1)} · weight {Math.round(p.weight * 100)}% · +{p.contribution.toFixed(2)}
                  </span>
                </div>
                <div className="rec-bar-track" aria-hidden="true">
                  <div
                    className="rec-bar-fill"
                    style={{ width: `${Math.max(0, Math.min(100, p.overall * 10))}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}
