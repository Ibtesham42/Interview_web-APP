import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { adminApi } from '../../services/api';
import type { AdminUserDetail as AdminUserDetailData } from '../../types';

function scoreClass(s: number): string {
  if (s >= 7) return 'good';
  if (s >= 5.5) return 'mid';
  return 'low';
}

function fieldLabel(f: string): string {
  if (!f) return 'General';
  return f.split('_').map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w)).join(' ');
}

function formatDate(d?: string | null): string {
  if (!d) return '—';
  return new Date(d).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
}

export function AdminUserDetail() {
  const { userId } = useParams<{ userId: string }>();
  const [data, setData] = useState<AdminUserDetailData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!userId) return;
    adminApi
      .userDetail(userId)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load user'))
      .finally(() => setLoading(false));
  }, [userId]);

  if (loading) {
    return (
      <div className="page">
        <div className="loading">
          <div className="spinner" />
          <div className="loading-text">Loading user…</div>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="page">
        <div className="empty-state">
          <h3>Couldn't load this user</h3>
          <p>{error || 'User not found.'}</p>
          <Link to="/admin" className="btn btn-primary">Back to Admin</Link>
        </div>
      </div>
    );
  }

  const { user, interviews } = data;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <Link to="/admin" className="back-link">← Admin overview</Link>
          <h1 className="page-title">{user.full_name || 'Unnamed user'}</h1>
          <p className="page-sub">{user.email || '—'}</p>
        </div>
        <span className={`role-badge role-${user.role}`}>{user.role}</span>
      </div>

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-value">{user.interview_count}</div>
          <div className="stat-label">Interviews</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{user.completed_count}</div>
          <div className="stat-label">Completed</div>
        </div>
        <div className="stat-card">
          <div className={`stat-value score-${scoreClass(user.average_score)}`}>
            {user.average_score > 0 ? user.average_score.toFixed(1) : '—'}
          </div>
          <div className="stat-label">Avg score</div>
        </div>
        <div className="stat-card">
          <div className="stat-value" style={{ fontSize: '1.125rem' }}>{formatDate(user.created_at)}</div>
          <div className="stat-label">Joined</div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head">
          <h3 className="panel-title">Interview history</h3>
        </div>
        {interviews.length === 0 ? (
          <p className="report-empty">This user has not run any interviews.</p>
        ) : (
          <div className="iv-list">
            {interviews.map((iv) => {
              const inner = (
                <>
                  <div className="iv-row-main">
                    <div className="iv-row-title">{fieldLabel(iv.field)} Interview</div>
                    <div className="iv-row-sub">
                      {iv.candidate_name} · {formatDate(iv.created_at)}
                    </div>
                  </div>
                  <div className="iv-row-meta">
                    {iv.integrity_terminated ? (
                      <span className="integrity-flag-chip terminated">Terminated</span>
                    ) : (iv.integrity_warnings ?? 0) > 0 ? (
                      <span className="integrity-flag-chip">
                        {iv.integrity_warnings} warning{iv.integrity_warnings === 1 ? '' : 's'}
                      </span>
                    ) : null}
                    {iv.completed ? (
                      <span className={`score-badge score-bg-${scoreClass(iv.score)}`}>
                        {iv.score.toFixed(1)}
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
                <div key={iv.interview_id} className="iv-row iv-row-static">{inner}</div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
