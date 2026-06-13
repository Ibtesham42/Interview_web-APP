import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { interviewApi, reportApi } from '../services/api';
import { Badge, Card, EmptyState } from './ui';
import type { BadgeVariant } from './ui';
import type { InterviewReport, InterviewSnapshot } from '../types';

const PHASE_NAMES: Record<number, string> = {
  2: 'Project #1',
  3: 'Project #2',
  4: 'Technical',
  5: 'Behavioral',
};

function tierVariant(rec: string): BadgeVariant {
  if (rec === 'Strong Hire' || rec === 'Hire') return 'success';
  if (rec === 'Hold') return 'warning';
  if (rec === 'No Hire') return 'danger';
  return 'neutral';
}

function scoreClass(s: number): string {
  if (s >= 7) return 'good';
  if (s >= 5.5) return 'mid';
  return 'low';
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

/**
 * Interview Replay — step through the recorded interview turn by turn, with the
 * proctoring snapshot from around that point and the phase/score context. Pure
 * re-presentation of data ALREADY persisted (the report transcript + snapshots),
 * so it adds no backend surface and never touches the realtime pipeline.
 *
 * Note: conversation turns aren't timestamped yet, so the snapshot is matched to
 * the current turn PROPORTIONALLY (turn fraction -> snapshot index) and labelled
 * with its real capture time — an honest approximation. Exact per-turn sync is a
 * follow-up that needs a small orchestrator change (stamp each appended turn).
 */
export function InterviewReplay() {
  const { interviewId } = useParams<{ interviewId: string }>();
  const [report, setReport] = useState<InterviewReport | null>(null);
  const [snapshots, setSnapshots] = useState<InterviewSnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (!interviewId) return;
    reportApi
      .get(interviewId)
      .then(setReport)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load the interview'))
      .finally(() => setLoading(false));
  }, [interviewId]);

  useEffect(() => {
    if (!interviewId) return;
    interviewApi
      .listSnapshots(interviewId)
      .then(({ items }) => setSnapshots(items))
      .catch(() => setSnapshots([]));
  }, [interviewId]);

  const transcript = useMemo(() => report?.transcript ?? [], [report]);

  // Proportional snapshot for the current turn (turns aren't timestamped).
  const snap = useMemo<InterviewSnapshot | null>(() => {
    if (snapshots.length === 0) return null;
    if (transcript.length <= 1) return snapshots[0];
    const frac = index / (transcript.length - 1);
    const si = Math.min(snapshots.length - 1, Math.round(frac * (snapshots.length - 1)));
    return snapshots[si];
  }, [snapshots, transcript.length, index]);

  if (loading) {
    return (
      <div className="page">
        <div className="loading">
          <div className="spinner" />
          <div className="loading-text">Loading replay…</div>
        </div>
      </div>
    );
  }

  if (error || !report) {
    return (
      <div className="page">
        <Card>
          <EmptyState
            title="Couldn't load this interview"
            description={error || 'The interview is not available.'}
            action={<Link to="/dashboard" className="btn btn-primary">Back to Dashboard</Link>}
          />
        </Card>
      </div>
    );
  }

  if (transcript.length === 0) {
    return (
      <div className="page">
        <Card>
          <EmptyState
            title="Nothing to replay"
            description="This interview has no recorded conversation."
            action={<Link to={`/report/${interviewId}`} className="btn btn-primary">View report</Link>}
          />
        </Card>
      </div>
    );
  }

  const current = transcript[index];
  const isAi = current.role === 'assistant';
  const last = transcript.length - 1;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <Link to={`/report/${interviewId}`} className="back-link">← Report</Link>
          <h1>Interview replay</h1>
          <p className="page-sub">
            {report.candidate_name} · {(report.candidate_field || 'general').toUpperCase()} ·{' '}
            {report.total_duration_minutes.toFixed(0)} min · {report.total_questions_asked} questions
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Badge variant={tierVariant(report.recommendation)}>{report.recommendation}</Badge>
          <span className="text-2xl font-semibold text-ink">{report.final_score.toFixed(1)}</span>
        </div>
      </div>

      <Card>
        <div className="replay-stage">
          <div className="replay-convo">
            <div className={`tr-turn tr-${isAi ? 'ai' : 'user'}`}>
              <span className="tr-role">{isAi ? 'Interviewer' : 'You'}</span>
              <p className="tr-text">{current.content}</p>
            </div>
          </div>
          <div className="replay-camera">
            {snap ? (
              <figure className="replay-camera-fig">
                <img
                  src={`data:image/jpeg;base64,${snap.image_base64}`}
                  alt={`Webcam around turn ${index + 1}`}
                  loading="lazy"
                  className="replay-camera-img"
                />
                <figcaption className="replay-camera-cap">
                  <span>camera ~ {formatTime(snap.created_at)}</span>
                  {snap.kind === 'integrity' && (
                    <span className="integrity-report-severity warning">flagged</span>
                  )}
                </figcaption>
              </figure>
            ) : (
              <div className="replay-camera-empty">No snapshots captured</div>
            )}
          </div>
        </div>

        <div className="replay-controls">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => setIndex((i) => Math.max(0, i - 1))}
            disabled={index === 0}
          >
            ‹ Prev
          </button>
          <input
            type="range"
            className="replay-slider"
            min={0}
            max={last}
            value={index}
            onChange={(e) => setIndex(Number(e.target.value))}
            aria-label="Replay position"
          />
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => setIndex((i) => Math.min(last, i + 1))}
            disabled={index === last}
          >
            Next ›
          </button>
          <span className="replay-pos">Turn {index + 1} / {transcript.length}</span>
        </div>
      </Card>

      <Card>
        <div className="replay-meta">
          <div className="replay-phases">
            {[2, 3, 4, 5].map((phase) => {
              const ps = report.phase_scores[phase] as { overall?: number } | undefined;
              if (!ps) return null;
              const overall = ps.overall ?? 0;
              return (
                <div key={phase} className="replay-phase">
                  <span className="replay-phase-name">{PHASE_NAMES[phase]}</span>
                  <span className={`phase-pill score-bg-${scoreClass(overall)}`}>{overall.toFixed(1)}</span>
                </div>
              );
            })}
          </div>
          {report.integrity_events && (
            <div className="replay-integrity">
              {report.integrity_events.count === 0
                ? 'No integrity events'
                : `${report.integrity_events.count} integrity event${report.integrity_events.count === 1 ? '' : 's'}`}
              {report.integrity_events.terminated && ' · terminated'}
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
