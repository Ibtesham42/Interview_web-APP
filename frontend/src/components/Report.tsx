import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { reportApi } from '../services/api';
import type { InterviewReport, PhaseScores, Phase2Score, Phase4Score, Phase5Score } from '../types';

const PHASE_NAMES: Record<number, string> = {
  2: 'Project Deep-Dive #1',
  3: 'Project Deep-Dive #2',
  4: 'Technical Assessment',
  5: 'Behavioral Questions',
};

function scoreClass(s: number): string {
  if (s >= 7) return 'good';
  if (s >= 5.5) return 'mid';
  return 'low';
}

function scoreLabel(s: number): string {
  if (s >= 8.5) return 'Outstanding';
  if (s >= 7) return 'Strong';
  if (s >= 5.5) return 'Developing';
  return 'Needs Improvement';
}

function recClass(rec: string): string {
  if (rec === 'Strong Hire' || rec === 'Hire') return 'hire';
  if (rec === 'Hold') return 'hold';
  return 'no-hire';
}

function StatChip({ label, value }: { label: string; value: number }) {
  return (
    <div className="metric-chip">
      <div className="metric-chip-value">{value.toFixed(1)}</div>
      <div className="metric-chip-label">{label}</div>
    </div>
  );
}

function renderPhase(phase: number, scores: PhaseScores[number]) {
  if (!scores) return null;
  const overall = (scores as { overall: number }).overall ?? 0;

  let body: React.ReactNode = null;
  if (phase === 2 || phase === 3) {
    const p = scores as Phase2Score;
    body = (
      <div className="metric-row">
        <StatChip label="Depth" value={p.depth_score} />
        <StatChip label="Accuracy" value={p.accuracy_score} />
        <StatChip label="Clarity" value={p.clarity_score} />
      </div>
    );
  } else if (phase === 4) {
    const p = scores as Phase4Score;
    const pct = p.total_questions ? (p.correct_answers / p.total_questions) * 100 : 0;
    body = (
      <div className="phase-bar-row">
        <div className="phase-bar-track">
          <div className="phase-bar-fill" style={{ width: `${pct}%` }} />
        </div>
        <span className="phase-bar-text">{p.correct_answers}/{p.total_questions} correct</span>
      </div>
    );
  } else if (phase === 5) {
    const p = scores as Phase5Score;
    body = (
      <div className="metric-row">
        <StatChip label="Vision" value={p.vision} />
        <StatChip label="Team" value={p.team} />
        <StatChip label="Self-Aware" value={p.self_awareness} />
        <StatChip label="Proactive" value={p.proactivity} />
        <StatChip label="Comm." value={p.communication} />
      </div>
    );
  }

  return (
    <div key={phase} className="phase-card">
      <div className="phase-card-head">
        <h4>{PHASE_NAMES[phase]}</h4>
        <span className={`phase-pill score-bg-${scoreClass(overall)}`}>{overall.toFixed(1)}</span>
      </div>
      {body}
    </div>
  );
}

export function Report() {
  const { interviewId } = useParams<{ interviewId: string }>();
  const [report, setReport] = useState<InterviewReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showTranscript, setShowTranscript] = useState(false);

  useEffect(() => {
    if (!interviewId) return;
    reportApi
      .get(interviewId)
      .then(setReport)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load report'))
      .finally(() => setLoading(false));
  }, [interviewId]);

  if (loading) {
    return (
      <div className="page">
        <div className="loading">
          <div className="spinner" />
          <div className="loading-text">Generating your report…</div>
        </div>
      </div>
    );
  }

  if (error || !report) {
    return (
      <div className="page">
        <div className="empty-state">
          <h3>Couldn't load this report</h3>
          <p>{error || 'The report is not available.'}</p>
          <Link to="/dashboard" className="btn btn-primary">Back to Dashboard</Link>
        </div>
      </div>
    );
  }

  const transcript = report.transcript ?? [];
  const strengths = report.strengths ?? [];
  const improvements = report.improvements ?? [];

  return (
    <div className="page report-page">
      {/* Score hero */}
      <div className="report-hero">
        <div className={`report-score score-${scoreClass(report.final_score)}`}>
          {report.final_score.toFixed(1)}
        </div>
        <div className="report-hero-body">
          <div className="report-hero-label">{scoreLabel(report.final_score)}</div>
          <h1 className="report-hero-title">Interview Report</h1>
          <p className="report-hero-meta">
            {report.candidate_name} · {(report.candidate_field || 'general').toUpperCase()} ·{' '}
            {report.total_duration_minutes.toFixed(0)} min · {report.total_questions_asked} questions
          </p>
          <span className={`recommendation ${recClass(report.recommendation)}`}>
            {report.recommendation}
          </span>
        </div>
      </div>

      {/* Summary */}
      {report.summary && (
        <div className="panel">
          <h3 className="panel-title">Summary</h3>
          <p className="report-summary">{report.summary}</p>
        </div>
      )}

      {/* Strengths & improvements */}
      {(strengths.length > 0 || improvements.length > 0) && (
        <div className="report-cols">
          <div className="panel">
            <h3 className="panel-title">Strengths</h3>
            {strengths.length > 0 ? (
              <ul className="report-list good">
                {strengths.map((s) => <li key={s}>{s}</li>)}
              </ul>
            ) : (
              <p className="report-empty">No standout strengths in this interview yet.</p>
            )}
          </div>
          <div className="panel">
            <h3 className="panel-title">Areas to improve</h3>
            {improvements.length > 0 ? (
              <ul className="report-list low">
                {improvements.map((s) => <li key={s}>{s}</li>)}
              </ul>
            ) : (
              <p className="report-empty">No major weak areas — keep it up.</p>
            )}
          </div>
        </div>
      )}

      {/* Phase breakdown */}
      <div className="panel">
        <h3 className="panel-title">Phase breakdown</h3>
        <div className="phase-grid">
          {[2, 3, 4, 5].map((phase) => renderPhase(phase, report.phase_scores[phase]))}
        </div>
      </div>

      {/* Transcript replay */}
      {transcript.length > 0 && (
        <div className="panel">
          <button
            className="transcript-toggle"
            onClick={() => setShowTranscript((v) => !v)}
            aria-expanded={showTranscript}
          >
            <span className="panel-title">Transcript ({transcript.length} turns)</span>
            <span className="transcript-chevron">{showTranscript ? '−' : '+'}</span>
          </button>
          {showTranscript && (
            <div className="transcript-replay">
              {transcript.map((turn, i) => (
                <div key={i} className={`tr-turn tr-${turn.role === 'assistant' ? 'ai' : 'user'}`}>
                  <span className="tr-role">{turn.role === 'assistant' ? 'Interviewer' : 'You'}</span>
                  <p className="tr-text">{turn.content}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="report-actions">
        <Link to="/dashboard" className="btn btn-secondary btn-lg">Back to Dashboard</Link>
        <Link to="/new" className="btn btn-primary btn-lg">New Interview</Link>
      </div>

      <p className="report-generated">
        Generated {new Date(report.generated_at).toLocaleString()}
      </p>
    </div>
  );
}
