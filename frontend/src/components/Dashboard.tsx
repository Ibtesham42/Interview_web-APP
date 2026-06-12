import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { dashboardApi, invitationsApi } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import { Badge, Card, CardHeader, CardTitle, EmptyState } from './ui';
import type { BadgeVariant } from './ui';
import type { CandidateInvitation, DashboardData } from '../types';

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

function scoreVariant(score: number): BadgeVariant {
  if (score >= 7) return 'success';
  if (score >= 5.5) return 'warning';
  return 'danger';
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
  const [invitations, setInvitations] = useState<CandidateInvitation[]>([]);
  const [decliningId, setDecliningId] = useState<string | null>(null);

  useEffect(() => {
    dashboardApi
      .get()
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load dashboard'))
      .finally(() => setLoading(false));
  }, []);

  // Company invitations addressed to this candidate (migration 011).
  // Non-blocking: a failure (e.g. backend not yet migrated) just hides
  // the panel — the rest of the dashboard is unaffected.
  useEffect(() => {
    invitationsApi
      .mine()
      .then(({ items }) => setInvitations(items.filter((i) => i.status !== 'declined')))
      .catch(() => setInvitations([]));
  }, []);

  const handleDecline = async (invitation: CandidateInvitation) => {
    setDecliningId(invitation.id);
    try {
      await invitationsApi.decline(invitation.id);
      setInvitations((prev) => prev.filter((i) => i.id !== invitation.id));
    } catch {
      // Leave the card in place; the candidate can retry.
    } finally {
      setDecliningId(null);
    }
  };

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
        <Card>
          <EmptyState
            title="Couldn't load your dashboard"
            description={error || 'Please try again.'}
          />
        </Card>
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

      {invitations.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Company invitations</CardTitle>
          </CardHeader>
          <p className="page-sub" style={{ marginBottom: 'var(--space-md)' }}>
            Companies that invited you to interview. Each interview is shared only with
            the company it's for.
          </p>
          <ul className="grid gap-3" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
            {invitations.map((inv) => (
              <li
                key={inv.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-md border p-3"
              >
                <div>
                  <div className="font-medium text-ink">{inv.company_name}</div>
                  <div className="mt-1 flex items-center gap-2 text-xs text-ink-subtle">
                    <Badge variant={inv.status === 'accepted' ? 'success' : 'info'}>
                      {inv.status === 'accepted' ? 'Accepted' : 'Invited'}
                    </Badge>
                    {inv.created_at && <span>Invited {formatDate(inv.created_at)}</span>}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Link
                    to={`/new?company=${encodeURIComponent(inv.company_id)}`}
                    className="btn btn-primary btn-sm"
                  >
                    Start interview
                  </Link>
                  {inv.status === 'pending' && (
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => handleDecline(inv)}
                      disabled={decliningId === inv.id}
                    >
                      {decliningId === inv.id ? 'Declining…' : 'Decline'}
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {!hasInterviews ? (
        <Card>
          <EmptyState
            icon={
              <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                <line x1="12" y1="19" x2="12" y2="23" />
              </svg>
            }
            title="No interviews yet"
            description="Run your first voice interview to start building your performance history."
            action={
              <Link to="/new" className="btn btn-primary btn-lg">
                Start your first interview
              </Link>
            }
          />
        </Card>
      ) : (
        <>
          {/* Stats */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Card padding="md">
              <div className="text-2xl font-semibold text-ink">{stats.total_interviews}</div>
              <div className="mt-1 text-xs text-ink-subtle">Total interviews</div>
            </Card>
            <Card padding="md">
              <div className="text-2xl font-semibold text-ink">{stats.completed_interviews}</div>
              <div className="mt-1 text-xs text-ink-subtle">Completed</div>
            </Card>
            <Card padding="md">
              <div className={`text-2xl font-semibold score-${scoreClass(stats.average_score)}`}>
                {stats.average_score.toFixed(1)}
              </div>
              <div className="mt-1 text-xs text-ink-subtle">Average score</div>
            </Card>
            <Card padding="md">
              <div className={`text-2xl font-semibold score-${scoreClass(stats.best_score)}`}>
                {stats.best_score.toFixed(1)}
              </div>
              <div className="mt-1 text-xs text-ink-subtle">Best score</div>
            </Card>
          </div>

          {/* Trend */}
          {trend.length > 1 && (
            <Card>
              <CardHeader>
                <CardTitle>Performance trend</CardTitle>
                <span className="text-xs text-ink-subtle">Last {Math.min(trend.length, 12)} completed</span>
              </CardHeader>
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
            </Card>
          )}

          {/* Interview history */}
          <Card>
            <CardHeader>
              <CardTitle>Interview history</CardTitle>
            </CardHeader>
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
                          <Badge variant={scoreVariant(iv.score)}>{iv.score.toFixed(1)}</Badge>
                        </>
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
          </Card>
        </>
      )}
    </div>
  );
}
