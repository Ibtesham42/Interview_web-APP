import { useCallback, useEffect, useState } from 'react';
import { jobsApi } from '../../services/api';
import { Button } from '../Button';
import { Badge, Card, EmptyState } from '../ui';
import type { BadgeVariant } from '../ui';
import { JobFormModal } from './JobFormModal';
import type { Job, JobStatus } from '../../types';

const STATUS_FILTERS: { value: JobStatus | ''; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'open', label: 'Open' },
  { value: 'draft', label: 'Draft' },
  { value: 'closed', label: 'Closed' },
];

function statusVariant(status: JobStatus): BadgeVariant {
  if (status === 'open') return 'success';
  if (status === 'closed') return 'warning';
  return 'neutral';
}

function formatDate(d: string): string {
  return new Date(d).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
}

/**
 * Recruiter / company-admin job board. Lists the company's requisitions with a
 * status filter, a create/edit modal, and a one-click open/close toggle. The
 * route is gated by `manage_jobs`, so reaching here implies the capability —
 * no in-page gate needed. Data access is tenant-scoped server-side.
 */
export function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<JobStatus | ''>('');
  const [formOpen, setFormOpen] = useState(false);
  const [editingJob, setEditingJob] = useState<Job | undefined>(undefined);
  const [actionError, setActionError] = useState<string | null>(null);

  const load = useCallback(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    jobsApi
      .list(statusFilter || undefined)
      .then((resp) => {
        if (!cancelled) setJobs(resp.items);
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Failed to load jobs');
          setJobs([]);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [statusFilter]);

  useEffect(() => load(), [load]);

  const openCreate = () => {
    setEditingJob(undefined);
    setFormOpen(true);
  };

  const openEdit = (job: Job) => {
    setEditingJob(job);
    setFormOpen(true);
  };

  const handleSaved = () => {
    setFormOpen(false);
    setEditingJob(undefined);
    load();
  };

  const toggleStatus = async (job: Job) => {
    setActionError(null);
    const next: JobStatus = job.status === 'open' ? 'closed' : 'open';
    try {
      const updated = await jobsApi.update(job.id, { status: next });
      setJobs((prev) => prev.map((j) => (j.id === updated.id ? updated : j)));
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Could not update the job');
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Jobs</h1>
          <p className="page-sub">Post and manage the roles you're hiring for.</p>
        </div>
        <Button variant="primary" onClick={openCreate}>+ New job</Button>
      </div>

      <div className="recruiter-pill-row" role="group" aria-label="Status filter">
        {STATUS_FILTERS.map((opt) => (
          <button
            key={opt.value || 'all'}
            type="button"
            className={`filter-pill${statusFilter === opt.value ? ' active' : ''}`}
            onClick={() => setStatusFilter(opt.value)}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {actionError && (
        <div className="recruiter-action-error" role="alert">{actionError}</div>
      )}

      {error ? (
        <Card>
          <EmptyState title="Couldn't load jobs" description={error} />
        </Card>
      ) : loading ? (
        <div className="recruiter-result-line"><span>Loading jobs…</span></div>
      ) : jobs.length === 0 ? (
        <Card>
          <EmptyState
            title={statusFilter ? `No ${statusFilter} jobs` : 'No jobs yet'}
            description={
              statusFilter
                ? 'Try a different status filter.'
                : 'Create your first job to start inviting and interviewing candidates against it.'
            }
            action={
              statusFilter ? (
                <Button variant="secondary" size="sm" onClick={() => setStatusFilter('')}>
                  Show all
                </Button>
              ) : (
                <Button variant="primary" size="sm" onClick={openCreate}>+ New job</Button>
              )
            }
          />
        </Card>
      ) : (
        <div className="panel">
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Status</th>
                  <th>Location</th>
                  <th>Type</th>
                  <th>Updated</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={job.id}>
                    <td>
                      <div className="cell-name">{job.title}</div>
                      <div className="cell-sub">/{job.slug}</div>
                    </td>
                    <td>
                      <Badge variant={statusVariant(job.status)}>
                        {job.status[0].toUpperCase() + job.status.slice(1)}
                      </Badge>
                    </td>
                    <td className="cell-sub">{job.location || '—'}</td>
                    <td className="cell-sub">{job.employment_type || '—'}</td>
                    <td className="cell-sub">{formatDate(job.updated_at)}</td>
                    <td className="recruiter-actions-cell">
                      <div className="recruiter-actions">
                        <Button variant="secondary" size="sm" onClick={() => openEdit(job)}>
                          Edit
                        </Button>
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => void toggleStatus(job)}
                          title={job.status === 'open' ? 'Close this job' : 'Open this job'}
                        >
                          {job.status === 'open' ? 'Close' : 'Open'}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {formOpen && (
        <JobFormModal job={editingJob} onClose={() => setFormOpen(false)} onSaved={handleSaved} />
      )}
    </div>
  );
}
