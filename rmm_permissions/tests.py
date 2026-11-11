"""
Phase 8 RMM permissions: role matrices, overrides, deny-wins, second-person
approval, tenant boundaries, Rem0te refusal, audit, upgrade safety, pages.
"""
import importlib
from datetime import timedelta
from unittest import mock

from django.apps import apps as django_apps
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, Role, RoleTemplate
from audit.models import AuditLog
from core.models import Organization
from psa.tests._base import TEST_MIDDLEWARE, _setup_seed
from tech_access import protected
from tech_access.models import Containment, ExplicitDeny
from tech_access.testing import grant, make_tech, make_ticket

from . import approvals, catalog, overrides
from .decision import RMMPermissionDenied, can, record_remote_refusal, require, rmm_action
from .models import RMMApproval, RMMPermissionOverride as O

# RMM capabilities need a paired RMM that advertises them; these tests are
# about the permission model, so the integration is taken as present.
AVAILABLE = mock.patch('tech_access.resolver.unavailable_reason', return_value='')


class _Req:
    def __init__(self, user):
        self.user, self.session, self.META, self.path = user, {}, {}, '/test'


def fresh(user):
    r = _Req(user)
    assert protected.reauthenticate(r, 'pw-' + user.username) == ''
    return r


def role(tier):
    return RoleTemplate.objects.get(rmm_tier=tier, organization__isnull=True)


def set_tier(user, tier):
    p = user.profile
    p.global_role_template = role(tier) if tier else None
    p.save()
    user.refresh_from_db()
    return user


class Base(TestCase):
    def setUp(self):
        _setup_seed()
        self.a = Organization.objects.create(name='Acme Dental', slug='acme')
        self.b = Organization.objects.create(name='Birch Law', slug='birch')
        AVAILABLE.start()
        self.addCleanup(AVAILABLE.stop)

    def tech(self, name, tier='', orgs=(), preset='l1', **kw):
        u = make_tech(name, **kw)
        set_tier(u, tier)
        for o in orgs:
            grant(u, o, preset)
        return u

    def device(self, org, dtype='workstation', provider='tactical', conn_org=None, name='FRONTDESK'):
        from integrations.models import RMMConnection, RMMDevice
        if provider == 'rem0te':
            from integrations.rem0te.testing import make_connection
            conn = make_connection(conn_org or org)
        else:
            conn = RMMConnection.objects.create(organization=conn_org or org, provider_type=provider,
                                                name=f'{provider} {org.slug} {name} {dtype}', base_url='https://rmm.example.com')
        return RMMDevice.objects.create(connection=conn, organization=org, external_id=f'{org.slug}-{dtype}',
                                        device_name=name, device_type=dtype)


class BuiltinTemplateTests(Base):
    def test_four_templates_with_tiers(self):
        got = dict(RoleTemplate.objects.exclude(rmm_tier='').values_list('rmm_tier', 'name'))
        self.assertEqual(set(got), {'l1', 'l2', 'l3', 'platform_admin'})
        for t in RoleTemplate.objects.exclude(rmm_tier=''):
            self.assertTrue(t.is_system_template)
            self.assertIsNone(t.organization_id)
            self.assertFalse(t.vault_view_password, t.name)  # reveal needs the vault permission

    def test_existing_templates_have_no_tier(self):
        from django.core.management import call_command
        call_command('init_role_templates', verbosity=0, stdout=open('/dev/null', 'w'))
        self.assertEqual(RoleTemplate.objects.exclude(rmm_tier='').count(), 4)
        for name in ('Owner', 'Administrator', 'Technician', 'Tech Manager', 'Full Admin', 'Read-Only'):
            self.assertEqual(RoleTemplate.objects.get(name=name, organization=None).rmm_tier, '', name)

    def test_migration_leaves_an_existing_template_of_the_same_name(self):
        t = role('l2')
        t.description, t.rmm_tier, t.assets_delete = 'site edit', '', True
        t.save()
        mig = importlib.import_module('accounts.migrations.0040_roletemplate_rmm_tier')
        mig.create_templates(django_apps, None)
        t.refresh_from_db()
        self.assertEqual((t.description, t.rmm_tier, t.assets_delete), ('site edit', '', True))
        self.assertEqual(RoleTemplate.objects.filter(name=t.name, organization=None).count(), 1)

    def test_role_editor_cannot_set_a_tier(self):
        """Custom roles never carry a tier (the editor doesn't post it)."""
        import inspect

        from accounts import roles_views
        self.assertNotIn('rmm_tier', inspect.getsource(roles_views))


class UpgradeTests(Base):
    """No tier and no overrides: the answers are the ones these paths gave
    before Phase 8."""

    def test_untiered_technician_matches_technician_access(self):
        from tech_access.resolver import decide
        old = self.tech('old', orgs=[self.a], preset='l2')
        Membership.objects.create(user=old, organization=self.a, role=Role.EDITOR,
                                  role_template=RoleTemplate.objects.filter(name='Technician').first())
        for key, spec in catalog.ACTIONS.items():
            if not spec.tech_capability:
                continue
            td = decide(old, self.a, spec.tech_capability)
            d = can(old, self.a, key)
            self.assertEqual(d.allowed, td.allowed or td.requestable, key)
            if d.allowed:
                self.assertFalse(d.needs_approval, key)
        for key in ('script.run_scoped', 'patch.deploy', 'device.administer', 'automation.deploy',
                    'workflow.run_approved'):
            self.assertFalse(can(old, self.a, key).allowed, key)
        self.assertFalse(can(old, self.b, 'rmm.handoff').allowed)

    def test_admin_actions_follow_existing_permissions(self):
        su = self.tech('root', superuser=True)
        plain = self.tech('plain')
        for key in ('policy.manage', 'security.settings', 'integration.configure', 'audit.review'):
            self.assertTrue(can(su, None, key).allowed, key)
            self.assertFalse(can(plain, None, key).allowed, key)

    def test_no_rows_are_changed_on_upgrade(self):
        old = self.tech('old', orgs=[self.a], preset='l2')
        m = Membership.objects.create(user=old, organization=self.a, role=Role.EDITOR)
        before = (m.role, m.role_template_id, old.profile.global_role_template_id)
        mig = importlib.import_module('accounts.migrations.0040_roletemplate_rmm_tier')
        mig.create_templates(django_apps, None)
        m.refresh_from_db()
        old.refresh_from_db()
        self.assertEqual((m.role, m.role_template_id, old.profile.global_role_template_id), before)
        self.assertEqual(O.objects.count(), 0)


class MatrixTests(Base):
    def test_l1(self):
        u = self.tech('l1', 'l1', [self.a])
        ok = {'device.view', 'alert.view', 'diagnostics.view', 'remote.request_support', 'remediation.request_low'}
        for key in catalog.ACTIONS:
            self.assertEqual(can(u, self.a, key).allowed, key in ok, key)
        self.assertEqual(can(u, self.a, 'remote.request_support').grant, catalog.REQUEST)
        for key in catalog.LOCKED:
            self.assertFalse(can(u, self.a, key).allowed)

    def test_l1_credential_reveal_needs_the_vault_permission(self):
        u = self.tech('l1', 'l1', [self.a, self.b])
        self.assertFalse(can(u, self.a, 'credential.reveal').allowed)
        vault = RoleTemplate.objects.create(name='Vault reveal', organization=self.a, vault_view_password=True)
        Membership.objects.create(user=u, organization=self.a, role=Role.EDITOR, role_template=vault)
        self.assertTrue(can(u, self.a, 'credential.reveal').allowed)
        self.assertFalse(can(u, self.b, 'credential.reveal').allowed)

    def test_l2(self):
        u = self.tech('l2', 'l2', [self.a])
        ws, srv = self.device(self.a), self.device(self.a, 'server', name='DC01')
        for key in ('device.view', 'diagnostics.run', 'workflow.run_approved', 'rmm.handoff',
                    'remote.request_control', 'remediation.request_low'):
            self.assertTrue(can(u, self.a, key).allowed, key)
        for key in ('script.run_scoped', 'device.administer', 'automation.deploy', 'diagnostics.run_advanced',
                    'remediation.request_high', 'policy.manage', 'security.settings'):
            self.assertFalse(can(u, self.a, key).allowed, key)
        self.assertTrue(can(u, self.a, 'diagnostics.run', device=ws).allowed)
        self.assertFalse(can(u, self.a, 'diagnostics.run', device=srv).allowed)
        p = can(u, self.a, 'patch.deploy', device=ws)
        self.assertTrue(p.allowed)
        self.assertTrue(p.needs_approval)
        self.assertEqual(p.approval_level, catalog.L3)
        self.assertFalse(p.permitted_now)
        self.assertFalse(can(u, self.a, 'patch.deploy', device=srv).allowed)

    def test_l2_scoped_script_only_when_specifically_granted(self):
        u = self.tech('l2', 'l2', [self.a])
        admin1, admin2 = self.tech('admin1', superuser=True), self.tech('admin2', superuser=True)
        self.assertFalse(can(u, self.a, 'script.run_scoped').allowed)
        o = overrides.create(admin1, action='script.run_scoped', effect=O.ALLOW, organization=self.a, user=u)
        self.assertEqual(o.status, O.PENDING)
        self.assertFalse(can(u, self.a, 'script.run_scoped').allowed)
        ok, _ = overrides.review(o, fresh(admin2))
        self.assertTrue(ok)
        d = can(u, self.a, 'script.run_scoped')
        self.assertTrue(d.allowed)
        self.assertEqual(d.approval_level, catalog.L3)
        self.assertFalse(can(u, self.b, 'script.run_scoped').allowed)

    def test_l3(self):
        u = self.tech('l3', 'l3', [self.a])
        srv = self.device(self.a, 'server', name='DC01')
        for key in ('diagnostics.run_advanced', 'remediation.request_high', 'remediation.refer',
                    'remote.request_elevation'):
            d = can(u, self.a, key)
            self.assertTrue(d.allowed, key)
            self.assertFalse(d.needs_approval, key)
        for key in ('device.administer', 'automation.deploy', 'script.run_scoped', 'patch.deploy'):
            d = can(u, self.a, key, device=srv)
            self.assertTrue(d.allowed, key)
            self.assertEqual(d.approval_level, catalog.PEER, key)
        self.assertTrue(can(u, self.a, 'diagnostics.run', device=srv).allowed)
        for key in ('policy.manage', 'security.settings', 'integration.configure', 'audit.review',
                    'shell.unrestricted', 'tenant.all_access'):
            self.assertFalse(can(u, self.a, key).allowed, key)

    def test_l3_has_no_all_tenant_access(self):
        u = self.tech('l3', 'l3', [self.a])
        for key in ('device.view', 'alert.view', 'rmm.handoff', 'device.administer'):
            self.assertTrue(can(u, self.a, key).allowed, key)
            d = can(u, self.b, key)
            self.assertFalse(d.allowed, key)
        nowhere = self.tech('l3b', 'l3')
        self.assertFalse(can(nowhere, self.a, 'device.view').allowed)

    def test_l1_l2_tier_covers_own_tickets_only(self):
        u = self.tech('l2', 'l2', [self.a])
        other = self.tech('other', 'l2', [self.a])
        mine, theirs = make_ticket(self.a, assigned_to=u), make_ticket(self.a, assigned_to=other)
        self.assertTrue(can(u, self.a, 'workflow.run_approved', ticket=mine).allowed)
        self.assertFalse(can(u, self.a, 'workflow.run_approved', ticket=theirs).allowed)
        senior = self.tech('l3', 'l3', [self.a])
        self.assertTrue(can(senior, self.a, 'workflow.run_approved', ticket=theirs).allowed)

    def test_platform_admin(self):
        u = self.tech('pa', 'platform_admin', [self.a])
        for key in ('integration.configure', 'policy.manage', 'security.settings', 'audit.review'):
            self.assertTrue(can(u, None, key).allowed, key)
            self.assertTrue(can(u, self.b, key).allowed, key)
        for key in ('device.administer', 'patch.deploy', 'script.run_scoped', 'diagnostics.run'):
            self.assertFalse(can(u, self.a, key).allowed, key)

    def test_non_technicians_and_containment(self):
        from django.contrib.auth.models import User
        portal = User.objects.create_user('portal', password='x')
        Membership.objects.create(user=portal, organization=self.a, role=Role.OWNER)
        for key in ('device.view', 'policy.manage'):
            self.assertFalse(can(portal, self.a, key).allowed)
        u = self.tech('l3', 'l3', [self.a])
        Containment.objects.create(user=u, reason='bulk reads')
        d = can(u, self.a, 'device.view')
        self.assertFalse(d.allowed)
        self.assertEqual(d.source, 'containment')


class TenantTests(Base):
    def test_cross_tenant_records_are_denied(self):
        u = self.tech('l3', 'l3', [self.a, self.b])
        dev_b = self.device(self.b)
        self.assertFalse(can(u, self.a, 'device.view', device=dev_b).allowed)
        self.assertFalse(can(u, self.a, 'diagnostics.run', ticket=make_ticket(self.b, assigned_to=u)).allowed)
        crossed = self.device(self.a, conn_org=self.b, name='X')
        d = can(u, self.a, 'device.view', device=crossed)
        self.assertFalse(d.allowed)
        self.assertEqual(d.source, 'tenant')
        crossed.organization = None
        crossed.save()
        self.assertFalse(can(u, self.a, 'device.view', device=crossed).allowed)
        self.assertFalse(can(u, None, 'device.view').allowed)


class OverrideTests(Base):
    def setUp(self):
        super().setUp()
        self.admin1 = self.tech('admin1', superuser=True)
        self.admin2 = self.tech('admin2', superuser=True)

    def test_deny_wins_over_tier_preset_and_allow(self):
        u = self.tech('l3', 'l3', [self.a], preset='l3')
        overrides.create(self.admin1, action='rmm.handoff', effect=O.DENY, organization=self.a, user=u,
                         reason='incident')
        d = can(u, self.a, 'rmm.handoff')
        self.assertFalse(d.allowed)
        self.assertEqual(d.source, 'override')
        self.assertTrue(can(u, self.b, 'device.view').allowed is False)  # not assigned at B anyway
        self.assertTrue(can(u, self.a, 'diagnostics.run').allowed)       # other actions unaffected
        allow = overrides.create(self.admin1, action='script.run_scoped', effect=O.ALLOW, organization=self.a,
                                 user=u)
        overrides.review(allow, fresh(self.admin2))
        self.assertTrue(can(u, self.a, 'script.run_scoped').allowed)
        overrides.create(self.admin1, action='*', effect=O.DENY, role_template=role('l3'))
        for key in ('script.run_scoped', 'device.view', 'diagnostics.run'):
            self.assertFalse(can(u, self.a, key).allowed, key)

    def test_tech_access_explicit_deny_and_restriction_still_apply(self):
        u = self.tech('l3', 'l3', [self.a])
        ExplicitDeny.objects.create(user=u, capability='rmm_handoff', organization=self.a)
        self.assertFalse(can(u, self.a, 'rmm.handoff').allowed)
        ExplicitDeny.objects.create(user=u, capability='*')
        self.assertFalse(can(u, self.a, 'device.administer').allowed)

    def test_per_org_and_per_action(self):
        u = self.tech('l1', 'l1', [self.a, self.b])
        overrides.create(self.admin1, action='device.view', effect=O.REQUIRE_APPROVAL, organization=self.a,
                         approval_level=catalog.L3)
        d = can(u, self.a, 'device.view')
        self.assertTrue(d.allowed)
        self.assertEqual(d.approval_level, catalog.L3)
        self.assertFalse(can(u, self.b, 'device.view').needs_approval)
        self.assertFalse(can(u, self.a, 'alert.view').needs_approval)
        overrides.create(self.admin1, action='alert.view', effect=O.DENY, organization=self.b)
        self.assertFalse(can(u, self.b, 'alert.view').allowed)
        self.assertTrue(can(u, self.a, 'alert.view').allowed)

    def test_require_approval_raises_level_never_lowers(self):
        u = self.tech('l2', 'l2', [self.a])
        overrides.create(self.admin1, action='patch.deploy', effect=O.REQUIRE_APPROVAL, organization=self.a,
                         approval_level=catalog.PEER)
        self.assertEqual(can(u, self.a, 'patch.deploy').approval_level, catalog.L3)
        overrides.create(self.admin1, action='*', effect=O.REQUIRE_APPROVAL,
                         approval_level=catalog.PLATFORM_ADMIN)
        self.assertEqual(can(u, self.a, 'patch.deploy').approval_level, catalog.PLATFORM_ADMIN)

    def test_allow_needs_a_second_admin_and_never_self(self):
        target = self.tech('target', 'l2', [self.a])
        o = overrides.create(self.admin1, action='script.run_scoped', effect=O.ALLOW, organization=self.a,
                             user=target)
        self.assertEqual(overrides.review(o, fresh(self.admin1))[0], False)
        self.assertEqual(overrides.review(o, _Req(self.admin2)), (False, 'Confirm your password first.'))
        plain = self.tech('plain')
        with self.assertRaises(PermissionDenied):
            overrides.create(plain, action='device.view', effect=O.DENY)
        self.assertTrue(overrides.review(o, fresh(self.admin2))[0])
        o.refresh_from_db()
        self.assertEqual(o.status, O.ACTIVE)

    def test_validation(self):
        for kw in ({'action': 'shell.unrestricted', 'effect': O.ALLOW, 'organization': self.a},
                   {'action': '*', 'effect': O.ALLOW, 'organization': self.a},
                   {'action': 'device.view', 'effect': O.ALLOW},
                   {'action': 'credential.reveal', 'effect': O.ALLOW, 'organization': self.a},
                   {'action': 'nope', 'effect': O.DENY}):
            with self.assertRaises(ValidationError, msg=kw):
                overrides.create(self.admin1, **kw)

    def test_high_impact_allow_needs_a_tier_listing_it(self):
        u = self.tech('l1', 'l1', [self.a])
        o = overrides.create(self.admin1, action='device.administer', effect=O.ALLOW, organization=self.a,
                             user=u)
        overrides.review(o, fresh(self.admin2))
        self.assertFalse(can(u, self.a, 'device.administer').allowed)

    def test_lifting_a_deny_needs_a_second_admin(self):
        u = self.tech('l2', 'l2', [self.a])
        o = overrides.create(self.admin1, action='rmm.handoff', effect=O.DENY, organization=self.a, user=u)
        overrides.revoke(o, self.admin1)
        self.assertFalse(can(u, self.a, 'rmm.handoff').allowed)  # still in force
        self.assertFalse(overrides.review_lift(o, fresh(self.admin1))[0])
        self.assertTrue(overrides.review_lift(o, fresh(self.admin2))[0])
        self.assertTrue(can(u, self.a, 'rmm.handoff').allowed)

    def test_expired_override_is_ignored(self):
        u = self.tech('l1', 'l1', [self.a])
        o = overrides.create(self.admin1, action='device.view', effect=O.DENY, organization=self.a,
                             expires_at=timezone.now() + timedelta(hours=1))
        self.assertFalse(can(u, self.a, 'device.view').allowed)
        O.objects.filter(pk=o.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertTrue(can(u, self.a, 'device.view').allowed)


class ApprovalTests(Base):
    def setUp(self):
        super().setUp()
        self.req = self.tech('req', 'l2', [self.a])
        self.peer = self.tech('peer', 'l2', [self.a])
        self.senior = self.tech('senior', 'l3', [self.a])
        self.far = self.tech('far', 'l3', [self.b])
        self.ws = self.device(self.a)

    def test_second_person_approval_flow(self):
        d = rmm_action(self.req, self.a, 'patch.deploy', device=self.ws, digest='kb5031')
        self.assertFalse(d.permitted_now)
        self.assertTrue(d.needs_approval)
        a = approvals.request_approval(self.req, self.a, 'patch.deploy', device=self.ws, digest='kb5031',
                                       summary='Patch Tuesday')
        self.assertEqual(a.approval_level, catalog.L3)
        self.assertEqual(approvals.request_approval(self.req, self.a, 'patch.deploy', device=self.ws,
                                                    digest='kb5031').pk, a.pk)
        self.assertEqual(approvals.approve(a, fresh(self.req))[1], catalog.LOCKED['approval.self'])
        self.assertFalse(approvals.approve(a, fresh(self.peer))[0])       # L2 can't approve an L3-level
        self.assertFalse(approvals.approve(a, fresh(self.far))[0])        # L3 elsewhere can't either
        self.assertFalse(approvals.approve(a, _Req(self.senior))[0])      # needs a fresh password
        ok, msg = approvals.approve(a, fresh(self.senior), note='ok')
        self.assertTrue(ok, msg)
        self.assertFalse(rmm_action(self.req, self.a, 'patch.deploy', device=self.ws,
                                    digest='other').permitted_now)        # bound to the digest
        d = rmm_action(self.req, self.a, 'patch.deploy', device=self.ws, digest='kb5031')
        self.assertTrue(d.permitted_now)
        self.assertEqual(d.approval_id, a.pk)
        a.refresh_from_db()
        self.assertEqual(a.status, RMMApproval.CONSUMED)
        self.assertFalse(rmm_action(self.req, self.a, 'patch.deploy', device=self.ws,
                                    digest='kb5031').permitted_now)       # single use

    def test_peer_level_and_requester_losing_access(self):
        senior2 = self.tech('senior2', 'l3', [self.a])
        a = approvals.request_approval(self.senior, self.a, 'device.administer', device=self.ws, digest='x')
        self.assertEqual(a.approval_level, catalog.PEER)
        self.assertFalse(approvals.approve(a, fresh(self.peer))[0])       # L2 may not administer devices
        set_tier(self.senior, 'l2')
        self.assertIn('no longer', approvals.approve(a, fresh(senior2))[1])
        set_tier(self.senior, 'l3')
        self.assertTrue(approvals.approve(a, fresh(senior2))[0])

    def test_require_raises_and_reject(self):
        with self.assertRaises(RMMPermissionDenied):
            require(self.req, self.a, 'patch.deploy', device=self.ws)
        a = approvals.request_approval(self.req, self.a, 'patch.deploy', device=self.ws)
        self.assertTrue(approvals.reject(a, fresh(self.senior), 'not tonight')[0])
        a.refresh_from_db()
        self.assertEqual(a.status, RMMApproval.REJECTED)
        with self.assertRaises(RMMPermissionDenied):
            require(self.req, self.a, 'patch.deploy', device=self.ws)

    def test_request_refused_when_not_allowed(self):
        with self.assertRaises(RMMPermissionDenied):
            approvals.request_approval(self.req, self.a, 'device.administer')
        with self.assertRaises(ValueError):
            approvals.request_approval(self.req, self.a, 'device.view')


class Rem0teTests(Base):
    def test_scopes_are_rem0tes_own(self):
        from integrations.rem0te.protocol import SCOPES
        for key in catalog.ACTIONS:
            s = catalog.rem0te_scope(key)
            self.assertTrue(s is None or s == '' or s in SCOPES, key)

    def test_rem0te_refusal_overrides_a_clientst0r_allow(self):
        u = self.tech('l1', 'l1', [self.a])
        d = rmm_action(u, self.a, 'remediation.request_low')
        self.assertTrue(d.permitted_now)
        self.assertEqual(d.rem0te_scope, 'actions:propose')
        with mock.patch('integrations.rem0te.actions.REFUSAL_TEXT',
                        {'ACTION_NOT_GRANTED': 'Rem0te says no.'}):
            out = record_remote_refusal(d, u, self.a, code='ACTION_NOT_GRANTED')
        self.assertFalse(out.allowed)
        self.assertFalse(out)
        self.assertEqual(out.source, 'rem0te')
        self.assertIn('Rem0te says no.', out.reason)
        log = AuditLog.objects.filter(object_type='rmm_permission').order_by('-pk').first()
        self.assertFalse(log.success)
        self.assertIn('refused by the RMM', log.description)

    def test_no_rem0te_route_means_no(self):
        u = self.tech('l3', 'l3', [self.a])
        dev = self.device(self.a, provider='rem0te')
        for key in ('patch.deploy', 'script.run_scoped', 'device.administer', 'diagnostics.run'):
            d = can(u, self.a, key, device=dev)
            self.assertFalse(d.allowed, key)
            self.assertEqual(d.source, 'rem0te', key)
        self.assertTrue(can(u, self.a, 'device.view', device=dev).allowed)
        self.assertTrue(can(u, self.a, 'remediation.request_low', device=dev).allowed)


class AuditTests(Base):
    def test_rmm_action_audits_allow_and_deny_can_does_not(self):
        u = self.tech('l1', 'l1', [self.a])
        n = AuditLog.objects.filter(object_type='rmm_permission').count()
        can(u, self.a, 'device.view')
        self.assertEqual(AuditLog.objects.filter(object_type='rmm_permission').count(), n)
        rmm_action(u, self.a, 'device.view')
        rmm_action(u, self.b, 'device.view')
        logs = list(AuditLog.objects.filter(object_type='rmm_permission').order_by('pk'))[n:]
        self.assertEqual([lg.success for lg in logs], [True, False])
        self.assertEqual(logs[0].organization, self.a)
        self.assertEqual(logs[1].extra_data['action'], 'device.view')
        self.assertTrue(logs[1].extra_data['steps'])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PageTests(Base):
    URL = '/settings/security/rmm-permissions/'

    def setUp(self):
        super().setUp()
        self.admin1 = self.tech('admin1', superuser=True)
        self.admin2 = self.tech('admin2', superuser=True)
        self.l2 = self.tech('l2', 'l2', [self.a])
        self.senior = self.tech('senior', 'l3', [self.a])

    def client_for(self, user):
        c = Client()
        c.force_login(user)
        return c

    def test_gate(self):
        self.assertEqual(self.client_for(self.l2).get(self.URL).status_code, 403)
        self.assertEqual(self.client_for(self.admin1).get(self.URL).status_code, 200)
        pa = self.tech('pa', 'platform_admin')
        self.assertEqual(self.client_for(pa).get(self.URL).status_code, 200)

    def test_effective_pages(self):
        c = self.client_for(self.admin1)
        r = c.get(f'{self.URL}technician/{self.l2.pk}/', {'organization': self.a.pk})
        self.assertContains(r, 'patch.deploy')
        self.assertContains(r, 'Needs approval')
        self.assertContains(r, 'RMM L2')
        r = c.get(f'{self.URL}customer/{self.a.pk}/')
        self.assertContains(r, 'senior')
        self.assertContains(r, 'Deploy patches')

    def test_create_override_and_review_through_the_page(self):
        c1, c2 = self.client_for(self.admin1), self.client_for(self.admin2)
        c1.post(self.URL, {'op': 'create', 'effect': 'allow', 'action': 'script.run_scoped',
                           'organization': self.a.pk, 'user': self.l2.pk, 'reason': 'printer scripts'})
        o = O.objects.get()
        self.assertEqual(o.status, O.PENDING)
        c2.post(self.URL, {'op': 'approve', 'override': o.pk, 'password': 'wrong'})
        o.refresh_from_db()
        self.assertEqual(o.status, O.PENDING)
        c2.post(self.URL, {'op': 'approve', 'override': o.pk, 'password': 'pw-admin2'})
        o.refresh_from_db()
        self.assertEqual(o.status, O.ACTIVE)
        self.assertEqual(self.client_for(self.l2).post(self.URL, {'op': 'create', 'effect': 'deny',
                                                                  'action': '*'}).status_code, 403)

    def test_approvals_page(self):
        ws = self.device(self.a)
        a = approvals.request_approval(self.l2, self.a, 'patch.deploy', device=ws)
        r = self.client_for(self.l2).get(f'{self.URL}approvals/')
        self.assertContains(r, 'Cancel my request')
        cs = self.client_for(self.senior)
        self.assertContains(cs.get(f'{self.URL}approvals/'), 'Approve')
        cs.post(f'{self.URL}approvals/', {'approval': a.pk, 'op': 'approve', 'password': 'pw-senior'})
        a.refresh_from_db()
        self.assertEqual(a.status, RMMApproval.APPROVED)
        self.assertEqual(a.decided_by, self.senior)
