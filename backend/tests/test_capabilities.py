"""Tests for the capability module.

Capabilities are pure functions of TenantContext, so the tests are
matrix-shaped: for each (role × company_id) input the predicate
returns a known bool. We assert this matrix directly. The factory
`requires(...)` gets a separate test for its 403-on-denial behaviour.

See `docs/adr/0006-capability-module.md` for the design rationale.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.auth import TenantContext
from app.capabilities import (
    CAPABILITIES,
    HIRING_ROLES,
    TENANT_ADMINS,
    can,
    requires,
)


def _ctx(role="user", company_id=None, user_id="u-1") -> TenantContext:
    """Helper — TenantContext with sensible defaults. role='user' +
    NULL company_id mirrors a fresh B2C signup."""
    return TenantContext(user_id=user_id, role=role, company_id=company_id)


# ---------------------------------------------------------------------------
# Role-set membership — sanity-check the constants haven't drifted.
# ---------------------------------------------------------------------------

class TestRoleSets:
    def test_tenant_admins_contains_both_admin_roles(self):
        assert "admin" in TENANT_ADMINS
        assert "company_admin" in TENANT_ADMINS
        assert "recruiter" not in TENANT_ADMINS
        assert "user" not in TENANT_ADMINS

    def test_hiring_roles_is_tenant_admins_plus_recruiter(self):
        assert HIRING_ROLES == TENANT_ADMINS | {"recruiter"}

    def test_role_sets_are_frozen(self):
        """Mutation at runtime would silently widen authorization —
        frozenset prevents that."""
        with pytest.raises(AttributeError):
            TENANT_ADMINS.add("hacker")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# `create_company` — only role='user' WITHOUT a tenant.
# ---------------------------------------------------------------------------

class TestCanCreateCompany:
    def test_b2c_user_can_create(self):
        assert can(_ctx(role="user", company_id=None), "create_company")

    def test_user_already_in_tenant_cannot(self):
        """A B2B applicant (user with a company) can't start a competing
        company through this endpoint."""
        assert not can(_ctx(role="user", company_id="c-1"), "create_company")

    def test_admin_cannot(self):
        assert not can(_ctx(role="admin", company_id=None), "create_company")

    def test_company_admin_cannot(self):
        assert not can(_ctx(role="company_admin", company_id="c-1"), "create_company")

    def test_recruiter_cannot(self):
        assert not can(_ctx(role="recruiter", company_id="c-1"), "create_company")


# ---------------------------------------------------------------------------
# `invite_candidate` — needs hiring role AND a tenant. The honest dead-end
# for platform admin (ADR 0006 D3) is captured here.
# ---------------------------------------------------------------------------

class TestCanInviteCandidate:
    def test_company_admin_in_tenant_can_invite(self):
        assert can(_ctx(role="company_admin", company_id="c-1"), "invite_candidate")

    def test_recruiter_in_tenant_can_invite(self):
        """Recruiter passes the capability gate even though the route
        gate currently blocks them — see D6. The capability says yes;
        the route gate is a UI affordance issue, not an authz issue."""
        assert can(_ctx(role="recruiter", company_id="c-1"), "invite_candidate")

    def test_platform_admin_no_tenant_cannot_invite(self):
        """The honest dead-end: admin role is in HIRING_ROLES but
        company_id is None, so the AND-predicate fails. This is the
        same behaviour the user reported as friction; the deepening
        makes it visible in one line instead of three layers."""
        assert not can(_ctx(role="admin", company_id=None), "invite_candidate")

    def test_b2c_user_cannot_invite(self):
        assert not can(_ctx(role="user", company_id=None), "invite_candidate")

    def test_b2b_applicant_cannot_invite(self):
        """User with a company is an applicant, not a recruiter."""
        assert not can(_ctx(role="user", company_id="c-1"), "invite_candidate")


# ---------------------------------------------------------------------------
# `manage_company_settings` — TENANT_ADMINS + a tenant.
# ---------------------------------------------------------------------------

class TestCanManageCompanySettings:
    def test_company_admin_can(self):
        assert can(_ctx(role="company_admin", company_id="c-1"), "manage_company_settings")

    def test_platform_admin_no_tenant_cannot(self):
        """Same dead-end pattern as invite_candidate."""
        assert not can(_ctx(role="admin", company_id=None), "manage_company_settings")

    def test_recruiter_cannot_manage_settings(self):
        """Recruiter inherits workflow capabilities (Shortlist etc.)
        but NOT settings management — that's the company_admin tier."""
        assert not can(_ctx(role="recruiter", company_id="c-1"), "manage_company_settings")


# ---------------------------------------------------------------------------
# `see_admin_overview` — role-only gate (TENANT_ADMINS), no tenant predicate.
# ---------------------------------------------------------------------------

class TestCanSeeAdminOverview:
    def test_platform_admin_can_even_without_tenant(self):
        """Platform admin sees the overview across all tenants — no
        tenant predicate. The handler's tenant_scope() returns None
        for platform admin, which the existing aggregation code
        already handles."""
        assert can(_ctx(role="admin", company_id=None), "see_admin_overview")

    def test_company_admin_can(self):
        assert can(_ctx(role="company_admin", company_id="c-1"), "see_admin_overview")

    def test_recruiter_cannot(self):
        """Recruiter sees the recruiter dashboard, not the admin
        overview — the dashboards serve different lenses."""
        assert not can(_ctx(role="recruiter", company_id="c-1"), "see_admin_overview")


# ---------------------------------------------------------------------------
# `manage_candidates` — HIRING_ROLES gate, tenant scope enforced by handler.
# ---------------------------------------------------------------------------

class TestCanManageCandidates:
    def test_all_hiring_roles_can(self):
        for role in HIRING_ROLES:
            company_id = None if role == "admin" else "c-1"
            assert can(_ctx(role=role, company_id=company_id), "manage_candidates"), \
                f"{role} should have manage_candidates"

    def test_b2c_user_cannot(self):
        assert not can(_ctx(role="user", company_id=None), "manage_candidates")


# ---------------------------------------------------------------------------
# can() error semantics — unknown capability raises KeyError.
# ---------------------------------------------------------------------------

class TestCanErrorSemantics:
    def test_unknown_capability_raises_keyerror(self):
        """Typo'd capability names surface at test time, not silently
        as `False`. See the can() docstring for rationale."""
        with pytest.raises(KeyError):
            can(_ctx(), "definitely_not_a_real_capability")


# ---------------------------------------------------------------------------
# requires() factory — 403 on denial, returns ctx on success.
#
# We construct the inner _dep function directly (the factory's return
# is a FastAPI Depends marker; the actual callable is wrapped inside).
# FastAPI normally invokes it via DI; in unit tests we call its
# underlying function manually.
# ---------------------------------------------------------------------------

def _resolve_dep(depends_marker):
    """FastAPI's Depends() wraps the dependency callable in a marker
    object. The actual function lives at `.dependency`."""
    return depends_marker.dependency


class TestRequiresFactory:
    def test_admit_when_capability_granted(self):
        dep = _resolve_dep(requires("see_admin_overview"))
        ctx = _ctx(role="admin", company_id=None)
        assert dep(ctx) is ctx  # passes through

    def test_403_when_capability_denied(self):
        dep = _resolve_dep(requires("see_admin_overview"))
        ctx = _ctx(role="user", company_id=None)
        with pytest.raises(HTTPException) as exc:
            dep(ctx)
        assert exc.value.status_code == 403
        assert "see_admin_overview" in exc.value.detail

    def test_factory_raises_on_unknown_capability_at_construction(self):
        """The typo-guard runs when the route module is imported, not
        at first request. A bad name fails fast."""
        with pytest.raises(KeyError):
            requires("not_a_real_capability")


# ---------------------------------------------------------------------------
# Matrix completeness — every capability has at least one allow and
# one deny test above. If a new capability lands without a test, this
# catches it.
# ---------------------------------------------------------------------------

class TestMatrixCompleteness:
    def test_every_capability_has_a_test(self):
        """Sanity check: each capability is covered by at least one
        test class above. Add a `TestCanX` class when adding a new
        capability."""
        tested = {
            "create_company", "invite_candidate", "manage_company_settings",
            "see_admin_overview", "manage_candidates",
        }
        missing = set(CAPABILITIES.keys()) - tested
        assert not missing, (
            f"Capabilities without dedicated tests: {sorted(missing)}. "
            f"Add a TestCan<Name> class in this file."
        )
