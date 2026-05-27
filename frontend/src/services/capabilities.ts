// Capability gates for the React UI — mirror of `backend/app/capabilities.py`.
//
// Single source of truth for "does this user see this control?" Consumed by
// AuthContext's `can(capability)` selector, then by components that gate
// buttons / nav links / sections. Mirrors the backend so the UI hides
// controls the API would reject (avoiding the 3-layer-disagreement
// scenario that triggered this refactor — see docs/adr/0006).
//
// Keep this file in lockstep with the Python module. To add a capability:
//   1. Add the entry to `backend/app/capabilities.py::CAPABILITIES`.
//   2. Add the matching entry below.
//   3. Add a TestCan<Name> in `backend/tests/test_capabilities.py`.

export const TENANT_ADMINS = new Set(['admin', 'company_admin']);
export const HIRING_ROLES = new Set([...TENANT_ADMINS, 'recruiter']);

// Capability inputs are the same shape as the backend TenantContext:
// just `role` and `company_id`. The `Profile` type from `types/index.ts`
// satisfies this; we accept the minimum surface so test fixtures don't
// need to construct full profiles.
export interface CapabilityCtx {
  role: string | null | undefined;
  company_id: string | null | undefined;
}

type Predicate = (ctx: CapabilityCtx) => boolean;

// Helpers — Set.has requires the literal type, but `role` is a string
// at runtime. Wrapping in a function keeps the call sites readable.
const inTenantAdmins = (role: string | null | undefined) =>
  role !== null && role !== undefined && TENANT_ADMINS.has(role);

const inHiringRoles = (role: string | null | undefined) =>
  role !== null && role !== undefined && HIRING_ROLES.has(role);

const hasCompany = (companyId: string | null | undefined) =>
  companyId !== null && companyId !== undefined;

// Capability table — each predicate must match the Python version
// exactly. Comments cross-reference the Python entries.
export const CAPABILITIES: Record<string, Predicate> = {
  // create_company — role='user' AND company_id IS NULL
  create_company: (ctx) => ctx.role === 'user' && !hasCompany(ctx.company_id),

  // invite_candidate — HIRING_ROLES AND company_id IS NOT NULL.
  // Platform admin without a tenant honestly fails (ADR 0006 D3).
  invite_candidate: (ctx) => inHiringRoles(ctx.role) && hasCompany(ctx.company_id),

  // manage_company_settings — TENANT_ADMINS AND company_id IS NOT NULL.
  manage_company_settings: (ctx) =>
    inTenantAdmins(ctx.role) && hasCompany(ctx.company_id),

  // see_admin_overview — TENANT_ADMINS, no tenant predicate.
  see_admin_overview: (ctx) => inTenantAdmins(ctx.role),

  // manage_candidates — HIRING_ROLES, tenant scope enforced by handler.
  manage_candidates: (ctx) => inHiringRoles(ctx.role),
};

export type CapabilityName = keyof typeof CAPABILITIES;

/**
 * Return true if the caller has the named capability.
 *
 * Throws on unknown capability names (mirrors the Python `can()`
 * raising KeyError). A typo at a call site would silently hide a
 * button forever; throwing surfaces the bug in dev.
 */
export function can(ctx: CapabilityCtx, capability: CapabilityName): boolean {
  const predicate = CAPABILITIES[capability];
  if (!predicate) {
    throw new Error(
      `Unknown capability '${capability}'. Known: ${Object.keys(CAPABILITIES).join(', ')}`,
    );
  }
  return predicate(ctx);
}
