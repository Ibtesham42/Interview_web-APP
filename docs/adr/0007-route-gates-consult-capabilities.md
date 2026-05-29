# Route gates consult capabilities (amends ADR 0006 D6)

Status: accepted

## Context

ADR 0006 D6 (2026-05-28) recorded the decision that **route gates keep
their `restrictTo: UserRole[]` form on existing routes** and only the
component layer would consume the new capability module. The stated
reasoning: "routes are coarse admission gates" and "no bulk migration
of App.tsx happens — that would change user-visible behavior (admin
redirected away from /admin/settings instead of seeing an empty
workspace) for no functional gain."

That premise rested on the assumption that route admission shapes and
capability gate shapes are different. The 2026-05-29 architecture
review (Candidate B grill + Fix verification) demonstrated they are
not — at least for the capability-shaped routes:

- `recruiter` evaluates `can('invite_candidate') === true` in
  `capabilities.ts`. The only UI surface for that action,
  `/admin/settings`, was route-gated to `['admin','company_admin']` in
  `App.tsx`. Direct three-layer disagreement that 0006 was meant to
  dissolve, surviving at the route layer because of D6.
- `/companies/signup` was wrapped in `protectedShell`, bouncing
  unauthenticated visitors back to `/login` despite the discoverability
  links on `/login` and `/signup` targeting that exact audience. Fix 2
  (2026-05-29) moved capability gating INSIDE the component as an
  opportunistic one-off — confirming that route-level capability
  awareness is the natural shape.

The pattern across both incidents: when a capability exists for the
action, the role-list at the route gate drifts from the capability
predicate, and the disagreement surfaces as user-visible bugs. D6's
"no functional gain" was wrong — the functional gain is closing the
last shallow seam ADR 0006 set out to close.

## Decision

### A1: `ProtectedRoute` gains a `requires` prop that consults `can()`

Signature:

```ts
requires?: CapabilityName | CapabilityName[]
```

OR semantics on the array form: the caller is admitted if they have
**any** of the listed capabilities. AND composition is not observed in
practice and is not introduced speculatively.

The predicate body is exactly the existing `can()` from
`services/capabilities.ts` — the same predicate the components
already consult. Route admission and component gating now read from a
single source.

A failing capability check sends the user to `/` (same target as a
failing `restrictTo` check), which `RoleHome` then routes to the
caller's appropriate dashboard. No new redirect targets.

### A2: `restrictTo` and `requires` coexist

Routes pick the gate that matches the admission shape:

- **Capability-shaped routes** use `requires`. The rule is "the caller
  can perform X." These are: `/admin`, `/admin/users/:id`,
  `/admin/settings`, `/recruiter`, `/recruiter/analytics`,
  `/recruiter/candidates/:id`.
- **Role-class routes** keep `restrictTo`. The rule is "the caller is
  this kind of identity, regardless of any specific action." Today:
  `/dashboard`, `/new`, `/interview/:id` all restrict to `'user'` —
  there is no `is_candidate` capability and inventing one would be a
  pseudo-capability (capabilities name *actions*, not *role types*).
- **Mixed admission** (`/report/:interviewId`) stays open — viewable
  by candidate-owner OR by admin-oversight. This is enforced at the
  backend, not at the route gate. No route-level gating needed.

The deletion test: removing `restrictTo` would force inventing pseudo-
capabilities for the role-class routes; removing `requires` would
re-create the drift D6 was closing the door on. Both belong.

### A3: This ADR amends ADR 0006 D6; ADR 0006 D1–D5 are unchanged

D6 was correct *under its assumptions* — but those assumptions did
not survive the next user-visible incident. The amendment is scoped
to D6 only:

> *Route gates use capability-aware admission when a capability fits;
> they keep `restrictTo` when the admission rule is genuinely a
> role-class. ADR 0006 D1–D5 (capability naming, predicate shape,
> honest dead-end for platform admin, generic 403 with handler-specific
> 400s, role deps as wrappers) all stand unchanged.*

D3's "honest dead-end for platform admin" specifically still holds:
the route gate now uses `requires`, but the predicate body is
identical to the one the component layer uses, so the platform admin
without a tenant still cannot reach `/admin/settings` for invite
purposes — same dead-end, just centrally enforced.

### A4: Migration is mechanical and one-shot

Five route declarations in `App.tsx` migrate from `restrictTo` to
`requires`. No new endpoints, no new components, no schema change.
Backend completely untouched.

Pre-migration: `/admin/settings` admits only `['admin','company_admin']`
at the route — recruiter is denied even though their capability admits
them.

Post-migration: `/admin/settings` admits anyone with
`['manage_company_settings', 'invite_candidate']`. Inside the
component, the Invite card is the only section currently capability-
gated (`can('invite_candidate')`). The apply-link card and the
company-meta card render unconditionally for any caller who reaches
the page — they're read-only, the apply URL is public by design (it's
the broadcast handle), and a recruiter often shares it. This v1
composition is "the page renders the cards each caller can use,"
with section-level gates added if and when a card grows a
manage-only edit affordance.

## Consequences

- `ProtectedRoute.tsx` learns the new prop. ~10 lines of new code.
- `App.tsx`'s `protectedShell` helper widens its signature: it now
  accepts either a `restrictTo` or a `requires` argument.
- Five route declarations change in `App.tsx`. Existing ones stay.
- The Invite card on `/admin/settings` becomes recruiter-reachable;
  the recruiter-dashboard modal from Candidate B remains the primary
  surface for that role, but a recruiter directly visiting Settings
  now sees the Invite card instead of getting redirected away.
- ADR 0006 D6 is amended in scope; D1–D5 untouched.
- The Candidate B fork in CHANGE.md's "Future considerations" — "would
  let recruiter reach /admin/settings directly" — is resolved here.

## Open follow-ups (deferred, not decided here)

- **Candidate C — platform-admin "act-as company" picker.** The
  honest dead-end for platform admin without a tenant is unchanged by
  this ADR; Candidate C is the right resolution for that, and it
  plugs into the same capability module as the seam.
- **Codegen for the Python/TypeScript capability mirror.** Speculative
  per the 2026-05-29 architecture review (E); not on the roadmap.
