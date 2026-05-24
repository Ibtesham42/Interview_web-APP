import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { dashboardApi } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import type { DashboardData } from '../types';

const FIELD_LABELS: Record<string, string> = {
  ml: 'Machine Learning',
  nlp: 'NLP / LLMs',
  cv: 'Computer Vision',
  data_science: 'Data Science',
  web_dev: 'Web Development',
  devops: 'DevOps',
  backend: 'Backend',
  frontend: 'Frontend',
  qa: 'QA / Testing',
  general: 'General Software',
};

function fieldLabel(f: string): string {
  if (!f) return 'General';
  return (
    FIELD_LABELS[f] ||
    f.split('_').map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w)).join(' ')
  );
}

function scoreClass(score: number): string {
  if (score >= 7) return 'good';
  if (score >= 5.5) return 'mid';
  return 'low';
}

function formatDate(d: string): string {
  if (!d) return '';
  return new Date(d).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
}

export function Dashboard() {
  const { profile, user } = useAuth();
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    dashboardApi
      .get()
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load dashboard'))
      .finally(() => setLoading(false));
  }, []);

  const rawName = profile?.full_name || user?.email || '';
  const firstName = rawName.split('@')[0].split(' ')[0] || 'there';

  if (loading) {
    return (
      <div className="page">
        <div className="loading">
          <div className="spinner" />
          <div className="loading-text">Loading your dashboard…</div>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="page">
        <div className="empty-state">
          <h3>Couldn't load your dashboard</h3>
          <p>{error || 'Please try again.'}</p>
        </div>
      </div>
    );
  }

  const { stats, interviews, trend } = data;
  const hasInterviews = interviews.length > 0;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Welcome back, {firstName}</h1>
          <p className="page-sub">Track your interview performance and pick up where you left off.</p>
        </div>
        <Link to="/new" className="btn btn-primary btn-lg">New Interview</Link>
      </div>

      {!hasInterviews ? (
        <div className="empty-state">
          <div className="empty-state-icon">
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
              <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
              <line x1="12" y1="19" x2="12" y2="23" />
            </svg>
          </div>
          <h3>No interviews yet</h3>
          <p>Run your first voice interview to start building your performance history.</p>
          <Link to="/new" className="btn btn-primary btn-lg">Start your first interview</Link>
        </div>
      ) : (
        <>
          {/* Stats */}
          <div className="stat-grid">
            <div className="stat-card">
              <div className="stat-value">{stats.total_interviews}</div>
              <div className="stat-label">Total interviews</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{stats.completed_interviews}</div>
              <div className="stat-label">Completed</div>
            </div>
            <div className="stat-card">
              <div className={`stat-value score-${scoreClass(stats.average_score)}`}>
                {stats.average_score.toFixed(1)}
              </div>
              <div className="stat-label">Average score</div>
            </div>
            <div className="stat-card">
              <div className={`stat-value score-${scoreClass(stats.best_score)}`}>
                {stats.best_score.toFixed(1)}
              </div>
              <div className="stat-label">Best score</div>
            </div>
          </div>

          {/* Trend */}
          {trend.length > 1 && (
            <div className="panel">
              <div className="panel-head">
                <h3>Performance trend</h3>
                <span className="panel-meta">Last {Math.min(trend.length, 12)} completed</span>
              </div>
              <div className="trend-chart">
                {trend.slice(-12).map((p, i) => (
                  <div
                    key={i}
                    className="trend-bar-wrap"
                    title={`${p.score.toFixed(1)} · ${formatDate(p.date)}`}
                  >
                    <div
                      className={`trend-bar score-bg-${scoreClass(p.score)}`}
                      style={{ height: `${Math.max(8, (p.score / 10) * 100)}%` }}
                    />
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Interview history */}
          <div className="panel">
            <div className="panel-head">
              <h3>Interview history</h3>
            </div>
            <div className="iv-list">
              {interviews.map((iv) => {
                const inner = (
                  <>
                    <div className="iv-row-main">
                      <div className="iv-row-title">{fieldLabel(iv.field)} Interview</div>
                      <div className="iv-row-sub">
                        {iv.candidate_name} · {formatDate(iv.created_at)}
                        {iv.completed && ` · ${iv.questions} questions`}
                      </div>
                    </div>
                    <div className="iv-row-meta">
                      {iv.completed ? (
                        <>
                          {iv.recommendation && (
                            <span className="iv-rec">{iv.recommendation}</span>
                          )}
                          <span className={`score-badge score-bg-${scoreClass(iv.score)}`}>
                            {iv.score.toFixed(1)}
                          </span>
                        </>
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
          </div>
        </>
      )}
    </div>
  );
}
