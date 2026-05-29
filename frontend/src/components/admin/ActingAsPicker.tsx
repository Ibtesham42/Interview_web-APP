import { useEffect, useState } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { companiesApi } from '../../services/api';
import type { CompanyOption } from '../../types';

/**
 * Platform-admin "Act-as company" picker (Candidate C, 2026-05-29).
 *
 * Rendered in the Header for `role='admin'` only. Lets the platform
 * admin pick any Company on the platform; the selection is stored in
 * sessionStorage and transmitted on every API request as
 * `X-Acting-As-Company`. The backend mutates `TenantContext.company_id`
 * for the duration of each request, and the frontend `can()` composes
 * the same override — so tenant-requiring capabilities light up
 * automatically without touching the capability module.
 *
 * UX: a `<select>` element styled as a chip beside the role badge.
 * Includes a "— no tenant —" option that clears the override and
 * returns the admin to their cross-tenant default view.
 *
 * Data: companies are fetched once on mount (admin-only endpoint).
 * Lazy fetch is fine — the picker mounts only for platform admin, and
 * an admin who never opens the picker pays no cost beyond the GET.
 */
export function ActingAsPicker() {
  const { actingAs, setActingAs } = useAuth();
  const [options, setOptions] = useState<CompanyOption[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    companiesApi
      .listAll()
      .then((rows) => {
        if (!cancelled) setOptions(rows);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Could not load tenants');
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const id = e.target.value;
    if (!id) {
      setActingAs(null);
      return;
    }
    const picked = options?.find((c) => c.id === id);
    if (picked) setActingAs(picked);
  };

  // Render even before options arrive — the current selection is
  // already known from sessionStorage, so the chip is visible
  // immediately. Options populate on first open.
  return (
    <label
      className="acting-as-picker"
      title={
        error
          ? `Picker error: ${error}`
          : 'Pick a tenant to act on behalf of. Sent as X-Acting-As-Company on every request.'
      }
    >
      <span className="acting-as-label">Acting as</span>
      <select
        className="acting-as-select"
        value={actingAs?.id ?? ''}
        onChange={handleChange}
        disabled={!options && !actingAs}
        aria-label="Act as company"
      >
        <option value="">— no tenant —</option>
        {options?.map((c) => (
          <option key={c.id} value={c.id}>{c.name}</option>
        ))}
        {/* If the picker hasn't loaded options yet but a previous
            selection lives in sessionStorage, surface that as the only
            visible non-empty entry until the fetch lands. */}
        {!options && actingAs && (
          <option value={actingAs.id}>{actingAs.name}</option>
        )}
      </select>
    </label>
  );
}
