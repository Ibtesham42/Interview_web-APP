import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { adminApi } from '../../services/api';
import {
  Badge,
  Card,
  CardHeader,
  CardTitle,
  EmptyState,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from '../ui';
import type { BadgeVariant } from '../ui';
import type { AdminCompanyDetail as DetailData, CandidateStatus } from '../../types';

const STATUS_LABELS: Record<CandidateStatus, string> = {
  invited: 'Invited',
  interview_completed: 'Interview Completed',
  shortlisted: 'Shortlisted',
  rejected: 'Rejected',
  on_hold: 'On Hold',
};

function statusVariant(s: CandidateStatus): BadgeVariant {
  if (s === 'shortlisted') return 'success';
  if (s === 'rejected') return 'danger';
  if (s === 'on_hold') return 'warning';
  if (s === 'invited') return 'info';
  return 'neutral';
}

function scoreVariant(score: number): BadgeVariant {
  if (score >= 7) return 'success';
  if (score >= 5.5) return 'warning';
  return 'danger';
}

function formatDate(d: string | null): string {
  if (!d) return '—';
  return new Date(d).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
}

/** Read-only company profile + stats + candidate list for Super-Admin review.
 * No company-admin actions (invite/shortlist) — this is platform oversight,
 * not the company workflow. Reuses /api/admin/companies/{id}. */
export function AdminCompanyDetail() {
  const { companyId } = useParams<{ companyId: string }>();
  const [data, setData] = useState<DetailData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!companyId) return;
    setLoading(true);
    setError(null);
    adminApi
      .companyDetail(companyId)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load company'))
      .finally(() => setLoading(false));
  }, [companyId]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <div className="page">
        <div className="loading">
          <div className="spinner" />
          <div className="loading-text">Loading company…</div>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="page">
        <Card>
          <EmptyState
            title="Couldn't load this company"
            description={error || 'Company not found.'}
            action={<Link to="/admin" className="btn btn-primary">Back to overview</Link>}
          />
        </Card>
      </div>
    );
  }

  const { company, stats, candidates } = data;
  const addressParts = [company.address, company.city, company.state, company.country, company.postal_code]
    .map((p) => (p || '').trim())
    .filter(Boolean);
  const address = addressParts.join(', ');

  const profile: { label: string; value: React.ReactNode }[] = [
    { label: 'Contact person', value: company.contact_person || '—' },
    { label: 'Email', value: company.email || '—' },
    { label: 'Phone', value: company.phone || '—' },
    { label: 'Address', value: address || '—' },
    {
      label: 'Website',
      value: company.website ? (
        <a href={company.website} target="_blank" rel="noreferrer" className="text-primary">
          {company.website}
        </a>
      ) : '—',
    },
    { label: 'Company size', value: company.company_size || '—' },
    { label: 'Registered', value: formatDate(company.registration_date) },
  ];

  const statCards: { label: string; value: number; tone?: BadgeVariant }[] = [
    { label: 'Candidates', value: stats.registrations },
    { label: 'Total interviews', value: stats.interviews_total },
    { label: 'Completed', value: stats.interviews_completed },
    { label: 'Shortlisted', value: stats.shortlisted, tone: 'success' },
    { label: 'Rejected', value: stats.rejected, tone: 'danger' },
    { label: 'On hold', value: stats.on_hold, tone: 'warning' },
  ];
  const toneClass = (t?: BadgeVariant) =>
    t === 'success' ? 'text-success' : t === 'danger' ? 'text-danger' : t === 'warning' ? 'text-warning' : 'text-ink';

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <Link to="/admin" className="back-link">← Overview</Link>
          <h1>{company.name || 'Company'}</h1>
          <p className="page-sub">/{company.slug} · platform admin view (read-only)</p>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {statCards.map((s) => (
          <Card key={s.label} padding="md">
            <div className={`text-2xl font-semibold ${toneClass(s.tone)}`}>{s.value}</div>
            <div className="mt-1 text-xs text-ink-subtle">{s.label}</div>
          </Card>
        ))}
      </div>

      {/* Company profile */}
      <Card>
        <CardHeader>
          <CardTitle>Company details</CardTitle>
        </CardHeader>
        <dl className="grid grid-cols-1 gap-x-8 gap-y-3 sm:grid-cols-2">
          {profile.map((row) => (
            <div key={row.label} className="flex flex-col gap-0.5">
              <dt className="text-xs uppercase tracking-wide text-ink-subtle">{row.label}</dt>
              <dd className="text-sm text-ink">{row.value}</dd>
            </div>
          ))}
        </dl>
      </Card>

      {/* Candidates (read-only) */}
      <Card>
        <CardHeader>
          <CardTitle>Candidates ({candidates.length})</CardTitle>
        </CardHeader>
        {candidates.length === 0 ? (
          <EmptyState
            title="No candidates yet"
            description="Candidates appear here once this company invites and interviews them."
          />
        ) : (
          <Table>
            <TableHead>
              <TableRow>
                <TableHeaderCell>Candidate</TableHeaderCell>
                <TableHeaderCell>Status</TableHeaderCell>
                <TableHeaderCell>Best score</TableHeaderCell>
                <TableHeaderCell>Last interview</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {candidates.map((c) => (
                <TableRow key={c.candidate_id}>
                  <TableCell>
                    <div className="font-medium text-ink">{c.name || 'Unnamed candidate'}</div>
                    <div className="text-xs text-ink-subtle">{c.email || '—'}</div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={statusVariant(c.status)}>{STATUS_LABELS[c.status]}</Badge>
                  </TableCell>
                  <TableCell>
                    {c.best_score > 0 ? (
                      <span className={`font-medium ${toneClass(scoreVariant(c.best_score))}`}>
                        {c.best_score.toFixed(1)}
                      </span>
                    ) : (
                      <span className="text-ink-subtle">—</span>
                    )}
                  </TableCell>
                  <TableCell className="text-ink-subtle">{formatDate(c.last_interview_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>
    </div>
  );
}
