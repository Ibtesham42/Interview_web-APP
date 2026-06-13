import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { recruiterApi } from '../../services/api';
import { Badge, Card, EmptyState } from '../ui';
import type { BadgeVariant } from '../ui';
import type { JobMatchesResponse } from '../../types';

function matchVariant(score: number): BadgeVariant {
  if (score >= 70) return 'success';
  if (score >= 40) return 'warning';
  return 'danger';
}

/**
 * Resume-match view for a job (Phase 3) — applicants ranked by how well their
 * parsed resume covers the job's required skills, with matched/missing skill
 * chips (gap analysis). Deterministic + advisory; cards link to the candidate
 * detail. Self-fetching so the job page can mount it lazily on its tab.
 */
export function JobMatchesView({ jobId }: { jobId: string }) {
  const [data, setData] = useState<JobMatchesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    recruiterApi
      .jobMatches(jobId)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load matches');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  if (loading) return <p className="cell-sub">Matching resumes…</p>;
  if (error || !data) {
    return (
      <Card>
        <EmptyState title="Couldn't load matches" description={error || 'Unavailable.'} />
      </Card>
    );
  }
  if (data.required_skills.length === 0) {
    return (
      <Card>
        <EmptyState
          title="No required skills on this job"
          description="Edit the job and add required skills to score resume matches."
        />
      </Card>
    );
  }
  if (data.matches.length === 0) {
    return (
      <Card>
        <EmptyState
          title="No applicants yet"
          description="Resume matches appear once candidates interview for this job."
        />
      </Card>
    );
  }

  return (
    <Card>
      <p className="page-sub" style={{ marginBottom: 'var(--space-md)' }}>
        Ranked by how well each applicant's resume covers the {data.required_skills.length}{' '}
        required skill{data.required_skills.length === 1 ? '' : 's'}. Advisory — based on the
        parsed resume, not interview performance.
      </p>
      <div className="match-list">
        {data.matches.map((m) => (
          <Link
            key={m.candidate_id}
            to={`/recruiter/candidates/${m.candidate_id}`}
            className="match-row"
          >
            <div className="match-row-head">
              <span className="match-name">{m.name}</span>
              <Badge variant={matchVariant(m.match_score)}>{m.match_score}% match</Badge>
            </div>
            {(m.matched_skills.length > 0 || m.missing_skills.length > 0) && (
              <div className="match-skills">
                {m.matched_skills.map((s) => (
                  <span key={`m-${s}`} className="skill-chip matched" title="In resume">{s}</span>
                ))}
                {m.missing_skills.map((s) => (
                  <span key={`x-${s}`} className="skill-chip missing" title="Missing from resume">{s}</span>
                ))}
              </div>
            )}
          </Link>
        ))}
      </div>
    </Card>
  );
}
