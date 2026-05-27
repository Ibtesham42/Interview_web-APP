# Capability module for cross-layer authorization checks

Status: accepted

Role + tenant gating today is expressed in three places per action: the
React route gate (`restrictTo: UserRole[]`), the component guard
(`if (!company)`), and the FastAPI handler precondition
(`if not ctx.company_id`). For most actions the three layers agree.
For `'invite_candidate'` and `'manage_company_settings'` they disagree —
producing the user-visible "I can see the button but it rejects me"
(or worse, "I see no button but the API would accept me") that
triggered the architecture review on 2026-05-27.

This ADR records the decisions taken in the grilling session for the
fix: a single `capabilities` module consumed by both layers, with the
shape and trade-offs that follow.

## D1: Capabilities are named after domain verbs

Capabilities are strings like `'invite_candidate'`, `'create_company'`,
`'manage_company_settings'`, `'see_admin_overview'`, `'manage_candidates'`.

Alternatives rejected:
- *Dotted-noun form* (`'candidates.invite'`, `'companies.create'`) —
  scales to a permission-toggle UI ("toggle candidates.invite for this
  role"), but no such UI is on the roadmap. Same scope-honesty
  principle as ADR 0004: build for the data you actually observe.
  Adding a parser today buys an option we have no plan to exercise.
- *ACTION_OBJECT constants* (`INVITE_CANDIDATE`) — Pythonic but
  TypeScript prefers string-literal unions; a string is portable across
  both layers.

The verb form matches the existing CONTEXT.md style (Shortlist, Reject,
Pivot, Step-down). The capability name reads as the *thing* the caller
is trying to do, in the same vocabulary as the rest of the domain.

## D2: Capability source-of-truth is a pure predicate function of TenantContext

The module exports a single lookup table:

```python
TENANT_ADMINS = frozenset({"admin", "company_admin"})
HIRING_ROLES  = TENANT_ADMINS | frozenset({"recruiter"})

CAPABILITIES = {
    'invite_candidate':        lambda ctx: ctx.role in HIRING_ROLES   and ctx.company_id is not None,
    'create_company':          lambda ctx: ctx.role == 'user'         and ctx.company_id is None,
    'manage_company_settings': lambda ctx: ctx.role in TENANT_ADMINS  and ctx.company_id is not None,
    'see_admin_overview':      lambda ctx: ctx.role in TENANT_ADMINS,
    'manage_candidates':       lambda ctx: ctx.role in HIRING_ROLES,
}

def can(ctx, capability_name: str) -> bool:
    return CAPABILITIES[capability_name](ctx)
```

Alternatives rejected:
- *Role-to-capability matrix* (`ROLE_CAPABILITIES['recruiter'] = [...]`)
  — discoverability of "what does role X do?" is better, but tenant
  predicates can't live in a role-only matrix. We have five
  capabilities and four of them care about the tenant predicate;
  off-loading that into a sidecar fragments the rule.
- *Hybrid Capability object* (roles + predicate + error-codes per
  capability) — Casbin / Authzed shape. Industrial-strength; overkill
  at our scale (6 capabilities, 3 error shapes).

The pure-predicate shape gives:
- *Locality*: the rule about "to invite, you need both a hiring role
  AND a tenant" lives on one line.
- *Testability*: capability is a pure function (ctx) → bool; no
  mocking needed.
- *Honest surface*: the predicate plainly says
  `ctx.company_id is not None`, so admin without a company correctly
  fails `'invite_candidate'` — see D3.

Named role-sets (`TENANT_ADMINS`, `HIRING_ROLES`) absorb the
discoverability hit somewhat: `grep HIRING_ROLES` shows every
capability a recruiter can perform.

## D3: Platform admin's tenant-requiring capabilities fail honestly

The user-reported friction was: `ibteshamakhtar1@gmail.com` (the
deployer's platform admin) cannot reach Settings or send invites.
Two paths were considered:

- *Path 1*: keep the dead-end visible. Admin's predicate for
  `'invite_candidate'` evaluates to False because they have no
  `company_id`. The capability gate honestly reflects what the schema
  can enforce.
- *Path 2*: `is_platform_admin` bypass — grant admin every capability.
  Rejected because the backend `email_outbox` schema has
  `company_id NOT NULL` (migration 006). Bypassing the capability gate
  trades the current 400 for a 500 inside the handler — hides the
  problem, doesn't fix it.

Path 1 is consistent with ADR 0005's grill C3 (platform admin is
intentionally tenant-agnostic). Path 1 also composes cleanly with a
future "act as" picker (Candidate 2 from the architecture review):
that feature would inject an `acting_as_company_id` into
`TenantContext`, at which point the capability lights up automatically
with zero changes to the predicate. The capability module becomes
the seam where that feature plugs in.

## D4: FastAPI dependency factory returns generic 403; specific 400s stay in handlers

The factory `requires(capability_name)` returns a `Depends(...)` that
raises 403 if `can(ctx, capability)` is False:

```python
def requires(capability_name: str):
    def _dep(ctx: TenantContext = Depends(get_tenant_context)) -> TenantContext:
        if not can(ctx, capability_name):
            raise HTTPException(403, detail=f"This action requires '{capability_name}'")
        return ctx
    return Depends(_dep)
```

The capability gate returns one bool, which is sufficient for the
frontend (`can()` hides UI controls so the user doesn't trigger the
403) but lossy for direct API consumers — they get a generic 403
instead of "Only company members can send invitations. Create a
company at /companies/signup first."

The two handlers that have intentionally specific 400-with-action
messages (`invite_candidate`, `create_company`) **keep their existing
check** as a second-line guard. Belt-and-braces: the capability is
the primary defense; the hand-written 400 preserves the actionable
message for the rare direct-API caller.

Alternatives rejected:
- *Rich CapabilityCheck tagged union* — heavier shape for a 6-capability
  surface.
- *`on_deny` callback parameter on `requires(...)`* — inline lambdas
  make route definitions noisy.

## D5: Existing role dependencies become wrappers over the role-sets

`get_current_admin` and `get_current_recruiter` in `auth.py` keep
their existing function signatures and call sites. Internally they
source their role-sets from `capabilities.py`:

```python
# auth.py
from app.capabilities import HIRING_ROLES, TENANT_ADMINS

def get_current_admin(ctx = Depends(get_tenant_context)):
    if ctx.role not in TENANT_ADMINS:
        raise HTTPException(403, "Admin access required")
    return ctx
```

Alternatives rejected:
- *Wholesale replacement* — every route in `admin.py` and
  `recruiter.py` switches to `Depends(requires(...))`. Touches stable
  code; violates the stability + scalability phase rule from
  CHANGE.md (2026-05-24 entry).
- *Parallel systems* — keep auth.py untouched; capabilities.py is
  a new way for new endpoints. Doesn't deepen the module — adds a
  pattern alongside.

The wrapper approach moves the role-set source-of-truth into
capabilities.py while preserving the call-site interface for stable
code. Two routers (admin, recruiter) keep their `Depends(get_current_admin)`
lines unchanged. New endpoints use `requires(capability)` directly.

## D6: Frontend uses can() at the component layer; route gates stay role-list

Frontend has the same three-layer structure but the layers play
different roles:

- *Route gate* = coarse admission ("is this user in the right ballpark
  for this workspace?") — admin and company_admin both fit
  `/admin/settings`.
- *Component gate* = fine-grained UI ("does this user have permission
  to perform this specific action?") — only the user with `company_id`
  can invite.
- *Backend handler* = authoritative enforcement.

`AuthContext` gains a `can(capability_name)` selector sourced from
`frontend/src/services/capabilities.ts` (a TypeScript mirror of the
Python module). Components consult `can()` to gate buttons, sections,
and nav links — `{can('invite_candidate') && <InviteCard />}`. This
is where the user-visible disconnects actually were, and where the
deepening collapses them.

Route gates keep their `restrictTo: UserRole[]` form on existing routes.
`protectedShell` learns to ALSO accept a capability for new routes,
but no bulk migration of App.tsx happens — that would change
user-visible behavior (admin redirected away from /admin/settings
instead of seeing an empty workspace) for no functional gain.

## Consequences

- Two new modules: `backend/app/capabilities.py` and
  `frontend/src/services/capabilities.ts`. Both sit beside
  `auth.py` / `AuthContext.tsx` respectively.
- `auth.py` updates: `get_current_admin` / `get_current_recruiter`
  internal-only change — they import role-sets from `capabilities.py`.
  No call-site changes.
- `AuthContext.tsx` gains a `can(capability)` selector + the
  `Company`-typed state added in PR 5 (no further changes).
- Component-level UI gating switches from ad-hoc role checks +
  presence checks to `can(...)` calls. Settings / CompanySignup /
  Header nav are the touch sites.
- New endpoints use `requires(capability)` instead of hand-rolled
  role checks. Existing endpoints can migrate opportunistically; not
  forced.
- The `'invite_candidate'` capability requires `company_id IS NOT NULL`.
  Platform admin without a tenant still cannot invite. The friction
  is honest and centrally located; the resolution is Candidate 2
  ("act as" picker) which would inject `acting_as_company_id` into
  the context — capability lights up automatically with no further
  changes here.
- ADR-0005's grill C3 (platform admin is tenant-agnostic) is preserved.
  This ADR does not re-litigate it.
- Future capabilities (e.g. `'bulk_invite_candidates'`,
  `'manage_company_team'`) add one entry to `CAPABILITIES`. Future
  roles add one row to the named role-sets.
