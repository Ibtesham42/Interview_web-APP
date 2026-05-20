import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { adminApi } from '../../services/api';
import type { AdminOverview } from '../../types';

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

export function AdminDashboard() {
  const navigate = useNavigate();
  const [data, setData] = useState<AdminOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    adminApi
      .overview()
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load admin data'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="page">
        <div className="loading">
          <div className="spinner" />
          <div className="loading-text">Loading admin overview…</div>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="page">
        <div className="empty-state">
          <h3>Couldn't load the admin dashboard</h3>
          <p>{error || 'Please try again.'}</p>
        </div>
      </div>
    );
  }

  const { stats, by_category, users } = data;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Admin overview</h1>
          <p className="page-sub">Platform-wide users, interviews and performance analytics.</p>
        </div>
      </div>

      {/* Platform stats */}
      <div className="stat-grid auto">
        <div className="stat-card">
          <div className="stat-value">{stats.total_users}</div>
          <div className="stat-label">Total users</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{stats.active_users}</div>
          <div className="stat-label">Active users</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{stats.total_interviews}</div>
          <div className="stat-label">Interviews</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{stats.completed_interviews}</div>
          <div className="stat-label">Completed</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{stats.completion_rate}%</div>
          <div className="stat-label">Completion rate</div>
        </div>
        <div className="stat-card">
          <div className={`stat-value score-${scoreClass(stats.average_score)}`}>
            {stats.average_score.toFixed(1)}
          </div>
          <div className="stat-label">Avg score</div>
        </div>
      </div>

      {/* Categories */}
      {by_category.length > 0 && (
        <div className="panel">
          <div className="panel-head">
            <h3 className="panel-title">Interview categories</h3>
          </div>
          <div className="cat-list">
            {by_category.map((c) => (
              <div key={c.field} className="cat-row">
                <span className="cat-name">{fieldLabel(c.field)}</span>
                <span className="cat-count">{c.count} interview{c.count === 1 ? '' : 's'}</span>
                <span className={`score-badge score-bg-${scoreClass(c.average_score)}`}>
                  {c.average_score.toFixed(1)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Users */}
      <div className="panel">
        <div className="panel-head">
          <h3 className="panel-title">Users ({users.length})</h3>
        </div>
        {users.length === 0 ? (
          <p className="report-empty">No users yet.</p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>User</th>
                  <th>Role</th>
                  <th>Interviews</th>
                  <th>Completed</th>
                  <th>Avg score</th>
                  <th>Last active</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.user_id} onClick={() => navigate(`/admin/users/${u.user_id}`)}>
                    <td>
                      <div className="cell-name">{u.full_name || 'Unnamed user'}</div>
                      <div className="cell-sub">{u.email || '—'}</div>
                    </td>
                    <td>
                      <span className={`role-badge role-${u.role}`}>{u.role}</span>
                    </td>
                    <td>{u.interview_count}</td>
                    <td>{u.completed_count}</td>
                    <td>
                      {u.average_score > 0 ? (
                        <span className={`score-${scoreClass(u.average_score)}`}>
                          {u.average_score.toFixed(1)}
                        </span>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="cell-sub">{formatDate(u.last_interview_at)}</td>
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
