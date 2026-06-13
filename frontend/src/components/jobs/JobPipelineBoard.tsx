import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { recruiterApi } from '../../services/api';
import { Badge, Card, EmptyState } from '../ui';
import type { BadgeVariant } from '../ui';
import { JobMatchesView } from './JobMatchesView';
import type { CandidateStatus, JobPipelineCandidate, JobPipelineResponse } from '../../types';

// Pipeline columns, left -> right. Labels are board-friendly; the values are
// the derived candidate statuses the backend returns.
const COLUMNS: { status: CandidateStatus; label: string }[] = [
  { status: 'invited', label: 'In progress' },
  { status: 'interview_completed', label: 'Interviewed' },
  { status: 'shortlisted', label: 'Shortlisted' },
  { status: 'on_hold', label: 'On hold' },
  { status: 'rejected', label: 'Rejected' },
];

function scoreVariant(score: number): BadgeVariant {
  if (score >= 7) return 'success';
  if (score >= 5.5) return 'warning';
  return 'danger';
}

function fieldLabel(f: string): string {
  return f
    .split('_')
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(' ');
}

function PipelineCard({ c }: { c: JobPipelineCandidate }) {
  return (
    <Link to={`/recruiter/candidates/${c.candidate_id}`} className="pipeline-card">
      <div className="pipeline-card-name">{c.name}</div>
      <div className="pipeline-card-meta">
        {c.final_score > 0 ? (
          <Badge variant={scoreVariant(c.final_score)}>
            {c.final_score.toFixed(1)} · {c.recommendation}
          </Badge>
        ) : (
          <span className="pipeline-card-field">Not scored</span>
        )}
        {c.integrity_warnings > 0 && (
          <Badge variant="warning">
            {c.integrity_warnings} flag{c.integrity_warnings === 1 ? '' : 's'}
          </Badge>
        )}
      </div>
      <div className="pipeline-card-field">{fieldLabel(c.field_specialization)}</div>
    </Link>
  );
}

/**
 * Per-job ATS pipeline board (Phase 2). Shows a job's candidates (those who
 * interviewed for it) in columns by derived status. Read-only Kanban — the
 * decision actions live on the candidate detail (a card links there). Route is
 * gated by `manage_candidates`; the endpoint tenant-scopes the job.
 */
export function JobPipelineBoard() {
  const { jobId } = useParams<{ jobId: string }>();
  const [data, setData] = useState<JobPipelineResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<'pipeline' | 'matches'>('pipeline');

  useEffect(() => {
    if (!jobId) return;
    setLoading(true);
    setError(null);
    recruiterApi
      .jobPipeline(jobId)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load the pipeline'))
      .finally(() => setLoading(false));
  }, [jobId]);

  const grouped = useMemo(() => {
    const map: Record<CandidateStatus, JobPipelineCandidate[]> = {
      invited: [], interview_completed: [], shortlisted: [], on_hold: [], rejected: [],
    };
    for (const c of data?.candidates ?? []) map[c.status]?.push(c);
    return map;
  }, [data]);

  if (loading) {
    return (
      <div className="page">
        <div className="loading">
          <div className="spinner" />
          <div className="loading-text">Loading pipeline…</div>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="page">
        <Card>
          <EmptyState
            title="Couldn't load this pipeline"
            description={error || 'The job is not available.'}
            action={<Link to="/recruiter/jobs" className="btn btn-primary">Back to jobs</Link>}
          />
        </Card>
      </div>
    );
  }

  const total = data.candidates.length;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <Link to="/recruiter/jobs" className="back-link">← Jobs</Link>
          <h1>{data.job.title}</h1>
          <p className="page-sub">
            {total} candidate{total === 1 ? '' : 's'} · job is {data.job.status}
          </p>
        </div>
      </div>

      <div className="job-tabs" role="tablist" aria-label="Job views">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'pipeline'}
          className={`job-tab${tab === 'pipeline' ? ' active' : ''}`}
          onClick={() => setTab('pipeline')}
        >
          Pipeline
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'matches'}
          className={`job-tab${tab === 'matches' ? ' active' : ''}`}
          onClick={() => setTab('matches')}
        >
          Resume match
        </button>
      </div>

      {tab === 'matches' ? (
        jobId && <JobMatchesView jobId={jobId} />
      ) : total === 0 ? (
        <Card>
          <EmptyState
            title="No candidates yet"
            description="Candidates appear here once they interview for this job. Share the job's apply link or send invites tied to it."
          />
        </Card>
      ) : (
        <div className="pipeline-board">
          {COLUMNS.map((col) => {
            const items = grouped[col.status];
            return (
              <div key={col.status} className="pipeline-col">
                <div className="pipeline-col-head">
                  <span>{col.label}</span>
                  <span className="pipeline-col-count">{items.length}</span>
                </div>
                {items.length === 0 ? (
                  <div className="pipeline-empty-col">—</div>
                ) : (
                  items.map((c) => <PipelineCard key={c.candidate_id} c={c} />)
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
