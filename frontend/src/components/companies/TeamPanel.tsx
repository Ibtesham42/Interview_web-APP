import { useCallback, useEffect, useState } from 'react';
import { teamApi } from '../../services/api';
import { Badge, EmptyState } from '../ui';
import { Button } from '../Button';
import type { TeamResponse, TeamRole } from '../../types';

function roleLabel(role: string): string {
  if (role === 'company_admin') return 'Admin';
  if (role === 'recruiter') return 'Recruiter';
  return role;
}

/**
 * Team management content for the Settings page (migration 014). Lists current
 * members (profiles with a hiring role) + pending invitations, lets a
 * company_admin invite a teammate to a hiring role, and revoke a pending
 * invite. The route + this whole card are gated by `manage_team`, so no
 * in-component capability check is needed.
 */
export function TeamPanel() {
  const [data, setData] = useState<TeamResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<TeamRole>('recruiter');
  const [inviting, setInviting] = useState(false);
  const [message, setMessage] = useState<{ kind: 'success' | 'error'; text: string } | null>(null);

  const load = useCallback(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    teamApi
      .get()
      .then((resp) => {
        if (!cancelled) setData(resp);
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Failed to load the team');
          setData(null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => load(), [load]);

  const emailLooksValid = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim());

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    setMessage(null);
    if (!emailLooksValid) {
      setMessage({ kind: 'error', text: "That doesn't look like a valid email." });
      return;
    }
    setInviting(true);
    try {
      const result = await teamApi.invite(email.trim(), role);
      if (result.email_status === 'sent') {
        setMessage({ kind: 'success', text: `Invitation sent to ${result.email}.` });
      } else {
        // The invitation is recorded regardless; the email just didn't go out.
        setMessage({
          kind: 'error',
          text:
            result.email_error ||
            `Invitation saved, but the email was ${result.email_status} — share the link manually.`,
        });
      }
      setEmail('');
      load();
    } catch (err) {
      setMessage({ kind: 'error', text: err instanceof Error ? err.message : 'Could not send the invitation' });
    } finally {
      setInviting(false);
    }
  };

  const handleRevoke = async (invitationId: string) => {
    setMessage(null);
    try {
      await teamApi.revoke(invitationId);
      load();
    } catch (err) {
      setMessage({ kind: 'error', text: err instanceof Error ? err.message : 'Could not revoke the invitation' });
    }
  };

  return (
    <div className="team-panel">
      {error ? (
        <EmptyState title="Couldn't load the team" description={error} />
      ) : loading ? (
        <p className="cell-sub">Loading team…</p>
      ) : (
        <>
          <div className="team-section">
            <h4 className="team-subhead">Members</h4>
            <ul className="team-list">
              {(data?.members ?? []).map((m) => (
                <li key={m.id} className="team-row">
                  <div>
                    <div className="cell-name">{m.full_name || m.email}</div>
                    {m.full_name && <div className="cell-sub">{m.email}</div>}
                  </div>
                  <Badge variant="neutral">{roleLabel(m.role)}</Badge>
                </li>
              ))}
            </ul>
          </div>

          {(data?.invitations.length ?? 0) > 0 && (
            <div className="team-section">
              <h4 className="team-subhead">Pending invitations</h4>
              <ul className="team-list">
                {data!.invitations.map((inv) => (
                  <li key={inv.id} className="team-row">
                    <div>
                      <div className="cell-name">{inv.email}</div>
                      <div className="cell-sub">Invited as {roleLabel(inv.role)}</div>
                    </div>
                    <Button variant="secondary" size="sm" onClick={() => void handleRevoke(inv.id)}>
                      Revoke
                    </Button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      <form className="team-invite-form" onSubmit={handleInvite}>
        <h4 className="team-subhead">Invite a teammate</h4>
        <div className="team-invite-row">
          <input
            type="email"
            className="form-input"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="teammate@company.com"
            aria-label="Teammate email"
          />
          <select
            className="form-input team-role-select"
            value={role}
            onChange={(e) => setRole(e.target.value as TeamRole)}
            aria-label="Role"
          >
            <option value="recruiter">Recruiter</option>
            <option value="company_admin">Admin</option>
          </select>
          <Button type="submit" variant="primary" disabled={inviting || !emailLooksValid}>
            {inviting ? 'Sending…' : 'Send invite'}
          </Button>
        </div>
        <p className="form-hint">
          They'll get an email to accept and set up access. Admins can manage the
          team and settings; recruiters review candidates and jobs.
        </p>
        {message && (
          <div
            className={message.kind === 'success' ? 'auth-info' : 'error-message'}
            role={message.kind === 'error' ? 'alert' : 'status'}
          >
            {message.text}
          </div>
        )}
      </form>
    </div>
  );
}
