"""Roles, permission groups and access settings (roles & access program).

Covers the permission registry, the built-in role templates and their
seeding, data scope (action + scope, no combining across grants), per-
organization evaluation of user_has_perm, delegation / escalation
protection, last-owner protection and ownership transfer, revocation and
authorization cache invalidation, the migration mapping on a legacy
fixture, the contract and alert helpers, the role management pages and the
audit trail.
"""
from types import SimpleNamespace

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from accounts import authz_cache, permission_registry as registry
from accounts.delegation import (can_assign_role, can_manage_member, check_owner_change, count_active_owners,
                                 DelegationError, last_owner_orgs)
from accounts.models import Membership, OwnershipTransfer, RoleReviewItem, RoleTemplate, UserType
from accounts.permission_utils import (orgs_with_perm, user_has_org_perm, user_has_perm,
                                       user_has_perm_any_org)
from accounts.role_seeds import as_frozen, definitions, seed_builtin_roles
from audit.models import AuditLog
from core.models import Organization

User = get_user_model()

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def builtin(key):
    return RoleTemplate.objects.get(seed_key=key, organization__isnull=True)


def make_user(username, staff=False, **kw):
    user = User.objects.create_user(username, f'{username}@example.com', 'pw-Strong-123', **kw)
    if staff:
        user.profile.user_type = UserType.STAFF
        user.profile.save()
    return user


def member(user, org, role='readonly', template=None, **kw):
    return Membership.objects.create(user=user, organization=org, role=role, role_template=template, **kw)


class in_org:
    """Evaluate inside a request context bound to `org` (like the middleware)."""

    def __init__(self, user, org):
        self.request = SimpleNamespace(user=user, current_organization=org)

    def __enter__(self):
        self.token = authz_cache.bind_request(self.request)
        return self.request

    def __exit__(self, *exc):
        authz_cache.unbind(self.token)


# --- registry ---------------------------------------------------------------------------

class RegistryTests(TestCase):
    def test_every_role_flag_is_registered_and_back(self):
        fields = set(RoleTemplate.permission_field_names())
        self.assertEqual(fields, set(registry.ALL_KEYS))

    def test_registry_entries_are_complete(self):
        for p in registry.PERMISSIONS:
            self.assertIn(p.action, registry.ACTIONS, p.key)
            self.assertIn(p.module, registry.MODULES, p.key)
            self.assertTrue(p.description, p.key)
            self.assertIn(p.sensitivity, registry.SENSITIVITY_RANK, p.key)

    def test_new_sensitive_flags_default_false(self):
        for key in ('org_manage_privileged', 'roles_manage', 'org_owner', 'contracts_approve',
                    'contracts_countersign', 'portal_contract_sign', 'quotes_approve_discount'):
            self.assertFalse(RoleTemplate._meta.get_field(key).default, key)

    def test_staff_only_flags_are_not_customer_assignable(self):
        self.assertFalse(registry.STAFF_ONLY_KEYS & registry.CUSTOMER_ASSIGNABLE_KEYS)
        self.assertIn('org_owner', registry.PRIVILEGED_KEYS)

    def test_search(self):
        keys = {p.key for p in registry.search('contract')}
        self.assertIn('contracts_approve', keys)

    def test_frozen_seed_copy_matches_live_definitions(self):
        """accounts 0046 carries a frozen copy; a changed definition needs a new
        seed version and a new data migration, not a silent edit."""
        import importlib
        mig = importlib.import_module('accounts.migrations.0046_roles_access_seed_and_review')
        live = {d['key']: d for d in as_frozen()}
        frozen = {d['key']: d for d in mig.FROZEN_DEFS}
        self.assertEqual(set(live), set(frozen))
        for key, d in frozen.items():
            if live[key]['version'] == d['version']:
                self.assertEqual(live[key]['flags'], d['flags'], key)


# --- default roles -------------------------------------------------------------------------

class DefaultRoleMatrixTests(TestCase):
    """What each built-in role allows and denies (the matrix in docs/ROLES_AND_ACCESS.md)."""

    def test_all_builtins_seeded(self):
        for d in definitions():
            self.assertTrue(RoleTemplate.objects.filter(seed_key=d.key).exists(), d.key)

    def assertAllows(self, key, *perms):
        role = builtin(key)
        for p in perms:
            self.assertTrue(getattr(role, p), f'{key} should allow {p}')

    def assertDenies(self, key, *perms):
        role = builtin(key)
        for p in perms:
            self.assertFalse(getattr(role, p), f'{key} should deny {p}')

    def test_owner(self):
        self.assertAllows('org_owner', 'org_owner', 'org_manage_privileged', 'roles_manage', 'org_manage_settings',
                          'billing_view_invoices', 'contracts_countersign')
        self.assertDenies('org_owner', 'portal_contract_sign', 'portal_billing_contact')

    def test_org_admin(self):
        self.assertAllows('org_admin', 'org_manage_members', 'org_manage_privileged', 'roles_manage',
                          'integrations_configure')
        self.assertDenies('org_admin', 'org_owner', 'vault_view_password', 'billing_view_invoices',
                          'contracts_countersign')

    def test_service_manager(self):
        self.assertAllows('service_manager', 'tickets_assign', 'change_approve_cab', 'reports_view_sla')
        self.assertDenies('service_manager', 'billing_view_invoices', 'vault_view_password',
                          'org_manage_settings', 'org_manage_members')

    def test_technicians(self):
        for key, tier in (('tech_l1', 'l1'), ('tech_l2', 'l2'), ('tech_l3', 'l3')):
            role = builtin(key)
            self.assertEqual(role.rmm_tier, tier)
            self.assertTrue(role.tickets_view_internal)
            self.assertFalse(role.org_manage_members, key)
            self.assertFalse(role.org_manage_settings, key)
            self.assertFalse(role.org_owner, key)
        self.assertDenies('tech_l1', 'vault_view_password', 'assets_delete')

    def test_sales(self):
        self.assertAllows('sales_rep', 'crm_view', 'quotes_edit', 'contracts_edit_draft', 'contracts_submit_approval')
        self.assertDenies('sales_rep', 'vault_view_password', 'tickets_view_internal', 'quotes_approve_discount',
                          'contracts_send', 'contracts_countersign', 'contracts_approve')
        self.assertAllows('sales_manager', 'quotes_send', 'quotes_approve_discount')
        self.assertDenies('sales_manager', 'contracts_approve', 'contracts_send')

    def test_billing_and_auditor(self):
        self.assertAllows('billing_finance', 'billing_view_invoices', 'reports_view_financial', 'contracts_view')
        self.assertDenies('billing_finance', 'vault_view_password', 'org_manage_settings')
        self.assertAllows('auditor', 'audit_view', 'tickets_view_all')
        self.assertDenies('auditor', 'tickets_edit', 'docs_edit', 'assets_edit', 'vault_view_password')

    def test_customer_roles_hold_only_customer_permissions(self):
        for key in ('customer_admin', 'customer_manager', 'customer_user', 'customer_readonly',
                    'customer_billing_contact', 'customer_contract_reviewer', 'customer_contract_signer',
                    'customer_request_approver'):
            role = builtin(key)
            self.assertEqual(role.audience, 'customer')
            extra = registry.granted_keys(role) - registry.CUSTOMER_ASSIGNABLE_KEYS
            self.assertFalse(extra, f'{key}: {sorted(extra)}')

    def test_customer_admin_is_not_a_signer(self):
        self.assertAllows('customer_admin', 'org_manage_members', 'portal_tickets_view_org')
        self.assertDenies('customer_admin', 'portal_contract_sign', 'tickets_view_internal', 'vault_view_password')
        self.assertAllows('customer_contract_signer', 'portal_contract_sign')

    def test_portal_flags_read_by_the_portal(self):
        self.assertAllows('customer_user', 'portal_tickets_create', 'portal_tickets_reply')
        self.assertDenies('customer_user', 'portal_approve_requests', 'portal_agreements_view_org')
        self.assertDenies('customer_readonly', 'portal_tickets_create', 'portal_tickets_reply',
                          'portal_tickets_view_org')
        self.assertAllows('customer_admin', 'portal_approve_requests', 'portal_agreements_view_org')
        self.assertDenies('auditor', 'reports_export', 'vehicles_manage')
        # Built-in definition; an RMM L1 template that existed before keeps
        # fleet management (any technician could manage vehicles before).
        l1 = next(d for d in definitions() if d.key == 'tech_l1')
        self.assertFalse(l1.flags.get('vehicles_manage', False))

    def test_simple_roles_keep_portal_behaviour(self):
        for role in ('owner', 'admin', 'editor', 'readonly'):
            perms = Membership(role=role)._primary_permissions()
            for key in ('portal_tickets_view_org', 'portal_tickets_create', 'portal_tickets_reply',
                        'portal_approve_requests', 'portal_agreements_view_org', 'reports_export'):
                self.assertTrue(getattr(perms, key), f'{role} {key}')
            self.assertFalse(getattr(perms, 'portal_contract_sign', False), role)
        self.assertFalse(Membership(role='readonly')._primary_permissions().vehicles_manage)

    def test_customer_user_sees_own_tickets_only(self):
        self.assertDenies('customer_user', 'portal_tickets_view_org', 'org_manage_members')
        self.assertAllows('customer_manager', 'portal_tickets_view_org')
        self.assertDenies('customer_readonly', 'tickets_create', 'tickets_edit')


# --- seeding -----------------------------------------------------------------------------

class SeedingTests(TestCase):
    def test_reseeding_is_idempotent(self):
        before = RoleTemplate.objects.count()
        summary = seed_builtin_roles(RoleTemplate)
        self.assertEqual(RoleTemplate.objects.count(), before)
        self.assertFalse(summary['created'])
        self.assertFalse(summary['upgraded'])

    def test_customized_builtin_is_never_overwritten(self):
        role = builtin('sales_rep')
        role.contracts_send = True
        role.save()
        defs = as_frozen()
        for d in defs:
            if d['key'] == 'sales_rep':
                d['version'] += 1
                d['flags'] = dict(d['flags'], crm_view_forecast=True)
        summary = seed_builtin_roles(RoleTemplate, defs=defs)
        role.refresh_from_db()
        self.assertIn(role.name, summary['kept_customized'])
        self.assertTrue(role.contracts_send)
        self.assertFalse(role.crm_view_forecast)
        self.assertTrue(RoleReviewItem.objects.filter(reason='builtin_customized', role_template=role).exists())

    def test_unmodified_builtin_is_upgraded(self):
        role = builtin('sales_rep')
        defs = as_frozen()
        for d in defs:
            if d['key'] == 'sales_rep':
                d['version'] += 1
                d['flags'] = dict(d['flags'], crm_view_forecast=True)
        summary = seed_builtin_roles(RoleTemplate, defs=defs)
        role.refresh_from_db()
        self.assertIn(role.name, summary['upgraded'])
        self.assertTrue(role.crm_view_forecast)
        self.assertFalse(role.is_customized)

    def test_name_clash_is_not_overwritten(self):
        RoleTemplate.objects.filter(seed_key='auditor').delete()
        clash = RoleTemplate.objects.create(name='Internal Read-Only / Auditor', organization=None,
                                            docs_edit=True)
        summary = seed_builtin_roles(RoleTemplate)
        clash.refresh_from_db()
        self.assertIn('Internal Read-Only / Auditor', summary['skipped'])
        self.assertTrue(clash.docs_edit)
        self.assertEqual(clash.seed_key, '')

    def test_adoption_only_adds_permissions(self):
        RoleTemplate.objects.filter(seed_key='org_owner').update(seed_key='', seed_version=0)
        owner = RoleTemplate.objects.get(name='Owner', organization__isnull=True)
        owner.portal_billing_contact = True   # something the built-in does not set
        owner.save()
        seed_builtin_roles(RoleTemplate)
        owner.refresh_from_db()
        self.assertEqual(owner.seed_key, 'org_owner')
        self.assertTrue(owner.portal_billing_contact)
        self.assertTrue(owner.org_owner)

    def test_seed_command(self):
        call_command('seed_roles', verbosity=0)


# --- migration mapping -------------------------------------------------------------------

class MigrationMappingTests(TestCase):
    """The 0046 mapping on a legacy fixture: templates without a seed key and
    memberships on simple roles."""

    @classmethod
    def setUpTestData(cls):
        from accounts.role_migration import find_review_items, preserve_existing_access  # noqa: F401
        cls.org = Organization.objects.create(name='Legacy Co', slug='rc-legacy')
        cls.orphan = Organization.objects.create(name='No Owner Co', slug='rc-noowner')
        cls.settings_role = RoleTemplate.objects.create(name='Legacy settings', organization=cls.org,
                                                        org_manage_settings=True, org_manage_members=True,
                                                        docs_edit=True, docs_create=True)
        cls.reader = RoleTemplate.objects.create(name='Legacy reader', organization=cls.org,
                                                 docs_edit=False, assets_edit=False)
        for f in RoleTemplate.permission_field_names():
            if f.endswith(('_edit', '_create', '_delete')):
                setattr(cls.reader, f, False)
        cls.reader.save()
        cls.owner = make_user('rc_leg_owner')
        cls.editor = make_user('rc_leg_editor')
        cls.staff = make_user('rc_leg_staff', staff=True)
        member(cls.owner, cls.org, 'owner')
        cls.editor_m = member(cls.editor, cls.org, 'editor')
        member(cls.staff, cls.orphan, 'editor')

    def test_preserve_existing_access(self):
        from accounts.role_migration import preserve_existing_access
        preserve_existing_access(RoleTemplate)
        self.settings_role.refresh_from_db()
        self.reader.refresh_from_db()
        self.assertTrue(self.settings_role.roles_manage)
        self.assertTrue(self.settings_role.org_manage_privileged)
        self.assertTrue(self.settings_role.tickets_view_internal)
        self.assertTrue(self.settings_role.quotes_edit)
        self.assertFalse(self.settings_role.org_owner)
        self.assertFalse(self.settings_role.contracts_approve)
        self.assertFalse(self.reader.roles_manage)
        self.assertFalse(self.reader.quotes_edit)
        self.assertTrue(self.reader.quotes_view)
        self.assertTrue(self.reader.portal_tickets_create)
        self.assertTrue(self.reader.reports_export)
        self.assertFalse(self.reader.vehicles_manage)
        self.assertFalse(self.reader.portal_contract_sign)
        self.assertTrue(self.settings_role.psa_manage_workflow_rules)
        self.assertFalse(self.settings_role.resourcing_view_payroll)
        # Built-in (seeded) roles are not touched.
        self.assertFalse(builtin('customer_user').tickets_view_internal)

    def test_review_items_never_grant(self):
        from accounts.role_migration import find_review_items, record_review_items
        from accounts.models import UserProfile
        items = find_review_items(Membership, UserProfile, RoleTemplate, Organization, User)
        reasons = {(r, d.get('user_id'), d.get('organization_id')) for r, d in items}
        self.assertIn(('staff_no_global_role', self.staff.pk, None), reasons)
        self.assertIn(('customer_legacy_write_role', self.editor.pk, self.org.pk), reasons)
        self.assertIn(('no_active_owner', None, self.orphan.pk), reasons)
        self.assertNotIn(('no_active_owner', None, self.org.pk), reasons)
        before = list(Membership.objects.values_list('pk', 'role', 'role_template_id').order_by('pk'))
        created = record_review_items(RoleReviewItem, items, 'test')
        self.assertEqual(created, record_review_items(RoleReviewItem, items, 'test') + created)  # idempotent
        self.assertEqual(before, list(Membership.objects.values_list('pk', 'role', 'role_template_id')
                                      .order_by('pk')))

    def test_report_command(self):
        from io import StringIO
        out = StringIO()
        call_command('roles_migration_report', '--refresh', stdout=out)
        self.assertIn('customer_legacy_write_role', out.getvalue())


# --- per-organization evaluation ----------------------------------------------------------

class PerOrganizationTests(TestCase):
    """A permission from one customer's membership no longer applies while
    another customer is selected."""

    @classmethod
    def setUpTestData(cls):
        cls.a = Organization.objects.create(name='Org A', slug='rc-a')
        cls.b = Organization.objects.create(name='Org B', slug='rc-b')
        cls.user = make_user('rc_two_orgs')
        member(cls.user, cls.a, template=builtin('customer_admin'))
        member(cls.user, cls.b, template=builtin('customer_readonly'))

    def test_org_perm(self):
        self.assertTrue(user_has_org_perm(self.user, self.a, 'org_manage_members'))
        self.assertFalse(user_has_org_perm(self.user, self.b, 'org_manage_members'))

    def test_user_has_perm_uses_selected_org(self):
        with in_org(self.user, self.a):
            self.assertTrue(user_has_perm(self.user, 'org_manage_members'))
        with in_org(self.user, self.b):
            self.assertFalse(user_has_perm(self.user, 'org_manage_members'))
        with in_org(self.user, None):   # no organization selected (API token request)
            self.assertTrue(user_has_perm(self.user, 'org_manage_members'))
        # The cross-organization helper is explicit.
        self.assertTrue(user_has_perm_any_org(self.user, 'org_manage_members'))

    def test_orgs_with_perm(self):
        self.assertEqual(set(orgs_with_perm(self.user, 'org_manage_members')), {self.a.pk})

    def test_staff_only_flag_never_effective_for_customer(self):
        role = RoleTemplate.objects.create(name='Leaky', organization=self.a, resourcing_view_team=True,
                                           crm_view=True)
        Membership.objects.filter(user=self.user, organization=self.a).update(role_template=role)
        self.assertFalse(user_has_org_perm(self.user, self.a, 'crm_view'))
        self.assertFalse(user_has_org_perm(self.user, self.a, 'resourcing_view_team'))


# --- scope ------------------------------------------------------------------------------

class ScopeTests(TestCase):
    """Action + scope, applied per grant: two narrow grants never combine
    into a wide one."""

    @classmethod
    def setUpTestData(cls):
        from psa.models import Ticket  # noqa: F401
        cls.a = Organization.objects.create(name='Scope A', slug='rc-sa')
        cls.b = Organization.objects.create(name='Scope B', slug='rc-sb')
        cls.user = make_user('rc_scope')
        cls.other = make_user('rc_scope_other')
        # Org A: may edit tickets, but only their own. Org B: sees all, edits none.
        editor = RoleTemplate.objects.create(name='Own editor', organization=cls.a, tickets_view=True,
                                             tickets_edit=True)
        viewer = RoleTemplate.objects.create(name='Viewer', organization=cls.b, tickets_view=True,
                                             tickets_edit=False)
        member(cls.user, cls.a, template=editor, record_scope='own')
        member(cls.user, cls.b, template=viewer, record_scope='organization')

    def _obj(self, org, created_by):
        return SimpleNamespace(organization_id=org.pk, created_by_id=created_by.pk, assigned_to_id=None)

    def test_can_access_object(self):
        from accounts.scope import can_access_object
        self.assertTrue(can_access_object(self.user, 'tickets_edit', self._obj(self.a, self.user)))
        self.assertFalse(can_access_object(self.user, 'tickets_edit', self._obj(self.a, self.other)))
        # Org B grants view of everything but no edit: no combining.
        self.assertFalse(can_access_object(self.user, 'tickets_edit', self._obj(self.b, self.other)))
        self.assertTrue(can_access_object(self.user, 'tickets_view', self._obj(self.b, self.other)))
        self.assertFalse(can_access_object(self.user, 'tickets_view', self._obj(self.a, self.other)))

    def test_scoped_queryset(self):
        from accounts.scope import scoped_queryset
        from audit.models import AuditLog as Rows  # any model with organization + user FKs
        r1 = Rows.objects.create(organization=self.a, user=self.user, action='create', object_type='x')
        r2 = Rows.objects.create(organization=self.a, user=self.other, action='create', object_type='x')
        r3 = Rows.objects.create(organization=self.b, user=self.other, action='create', object_type='x')
        qs = Rows.objects.filter(pk__in=[r1.pk, r2.pk, r3.pk])
        edit = set(scoped_queryset(qs, self.user, 'tickets_edit', owner_fields=('user',))
                   .values_list('pk', flat=True))
        self.assertEqual(edit, {r1.pk})
        view = set(scoped_queryset(qs, self.user, 'tickets_view', owner_fields=('user',))
                   .values_list('pk', flat=True))
        self.assertEqual(view, {r1.pk, r3.pk})

    def test_staff_client_scope(self):
        staff = make_user('rc_scoped_staff', staff=True)
        staff.profile.global_role_template = builtin('service_manager')
        staff.profile.client_scope = 'selected'
        staff.profile.save()
        staff.profile.scope_organizations.set([self.a])
        self.assertTrue(user_has_org_perm(staff, self.a, 'tickets_assign'))
        self.assertFalse(user_has_org_perm(staff, self.b, 'tickets_assign'))
        from core.tenancy import accessible_org_ids
        ids = accessible_org_ids(SimpleNamespace(user=staff, is_staff_user=True))
        self.assertIn(self.a.pk, ids)
        self.assertNotIn(self.b.pk, ids)


# --- delegation -------------------------------------------------------------------------

class DelegationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Deleg Co', slug='rc-deleg')
        cls.other_org = Organization.objects.create(name='Other Co', slug='rc-deleg-o')
        cls.owner = make_user('rc_d_owner')
        cls.cadmin = make_user('rc_d_cadmin')
        cls.cuser = make_user('rc_d_cuser')
        cls.staff_admin = make_user('rc_d_staffadmin', staff=True)
        cls.tech = make_user('rc_d_tech', staff=True)
        cls.owner_m = member(cls.owner, cls.org, 'owner')
        cls.cadmin_m = member(cls.cadmin, cls.org, template=builtin('customer_admin'))
        cls.cuser_m = member(cls.cuser, cls.org, template=builtin('customer_user'))
        cls.staff_admin.profile.global_role_template = builtin('org_admin')
        cls.staff_admin.profile.save()
        cls.tech_m = member(cls.tech, cls.org, template=builtin('service_manager'))
        cls.su = make_user('rc_d_su', is_superuser=True, is_staff=True)

    def test_no_self_promotion(self):
        v = can_assign_role(self.cadmin, self.org, builtin('customer_admin'), target_membership=self.cadmin_m)
        self.assertFalse(v)

    def test_customer_admin_assigns_customer_roles_only(self):
        self.assertTrue(can_assign_role(self.cadmin, self.org, builtin('customer_manager'),
                                        target_membership=self.cuser_m))
        self.assertFalse(can_assign_role(self.cadmin, self.org, builtin('service_manager'),
                                         target_membership=self.cuser_m))
        self.assertFalse(can_assign_role(self.cadmin, self.org, builtin('customer_user'),
                                         target_membership=self.tech_m))

    def test_subset_rule(self):
        # The customer admin lacks portal_contract_sign, so cannot hand it out.
        self.assertFalse(can_assign_role(self.cadmin, self.org, builtin('customer_contract_signer'),
                                         target_membership=self.cuser_m))
        # ... also not as an additional role.
        self.assertFalse(can_assign_role(self.cadmin, self.org, builtin('customer_user'),
                                         target_membership=self.cuser_m,
                                         additional_roles=[builtin('customer_contract_signer')]))

    def test_ownership_only_by_transfer(self):
        self.assertFalse(can_assign_role(self.owner, self.org, builtin('org_owner'),
                                         target_membership=self.cuser_m))
        self.assertFalse(can_assign_role(self.owner, self.org, 'owner', target_membership=self.cuser_m))
        self.assertFalse(can_assign_role(self.staff_admin, self.org, builtin('org_owner'),
                                         target_membership=self.cuser_m))

    def test_rmm_tier_roles_are_platform_roles(self):
        self.assertFalse(can_assign_role(self.owner, self.org, builtin('tech_l1'),
                                         target_membership=self.cuser_m))

    def test_privileged_needs_manage_privileged(self):
        limited = RoleTemplate.objects.create(name='Member manager', organization=self.org,
                                              org_manage_members=True, org_invite_members=True,
                                              org_view_members=True, org_manage_settings=True)
        boss = make_user('rc_d_boss', staff=True)
        boss.profile.global_role_template = limited
        boss.profile.save()
        self.assertFalse(can_assign_role(boss, self.org, builtin('org_admin'), target_membership=self.cuser_m))

    def test_cannot_edit_a_member_with_more_access(self):
        self.assertFalse(can_manage_member(self.cadmin, self.org, self.owner_m))
        self.assertFalse(can_manage_member(self.cadmin, self.org, self.tech_m))

    def test_foreign_and_archived_roles(self):
        foreign = RoleTemplate.objects.create(name='Foreign', organization=self.other_org)
        archived = RoleTemplate.objects.create(name='Old', organization=self.org, is_archived=True)
        self.assertFalse(can_assign_role(self.su, self.org, foreign, target_membership=self.cuser_m))
        self.assertFalse(can_assign_role(self.su, self.org, archived, target_membership=self.cuser_m))

    def test_superuser_target_protected(self):
        su_m = member(self.su, self.org, template=builtin('customer_user'))
        self.assertFalse(can_assign_role(self.owner, self.org, builtin('customer_user'), target_membership=su_m))

    def test_no_access_in_another_org(self):
        target = member(make_user('rc_d_other'), self.other_org, template=builtin('customer_user'))
        self.assertFalse(can_assign_role(self.cadmin, self.other_org, builtin('customer_readonly'),
                                         target_membership=target))


class LastOwnerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Owner Co', slug='rc-owner')
        cls.owner = make_user('rc_o_owner')
        cls.other = make_user('rc_o_other')
        cls.owner_m = member(cls.owner, cls.org, 'owner')
        cls.other_m = member(cls.other, cls.org, template=builtin('customer_user'))

    def test_count(self):
        self.assertEqual(count_active_owners(self.org), 1)

    def test_last_owner_cannot_be_removed_or_demoted(self):
        self.assertFalse(check_owner_change(self.owner_m, deactivate=True))
        self.assertFalse(check_owner_change(self.owner_m, new_template=builtin('customer_admin'),
                                            template_given=True))
        self.assertTrue(check_owner_change(self.other_m, deactivate=True))
        self.assertEqual(last_owner_orgs(self.owner), [self.org])

    def test_second_owner_frees_the_first(self):
        member(make_user('rc_o_second'), self.org, 'owner')
        self.assertTrue(check_owner_change(self.owner_m, deactivate=True))

    def test_transfer(self):
        from accounts.ownership import transfer_ownership
        with self.assertRaises(DelegationError):
            transfer_ownership(self.owner, self.org, self.other, password='wrong', confirm_name=self.org.name)
        with self.assertRaises(DelegationError):
            transfer_ownership(self.owner, self.org, self.other, password='pw-Strong-123', confirm_name='nope')
        with self.assertRaises(DelegationError):
            transfer_ownership(self.other, self.org, self.other, password='pw-Strong-123',
                               confirm_name=self.org.name)
        transfer_ownership(self.owner, self.org, self.other, password='pw-Strong-123',
                           confirm_name=self.org.name, previous_owner_role=builtin('customer_admin'))
        self.other_m.refresh_from_db()
        self.owner_m.refresh_from_db()
        self.assertTrue(self.other_m.is_owner())
        self.assertFalse(self.owner_m.is_owner())
        self.assertEqual(count_active_owners(self.org), 1)
        self.assertTrue(OwnershipTransfer.objects.filter(organization=self.org, to_user=self.other).exists())
        self.assertTrue(AuditLog.objects.filter(extra_data__event='ownership.transferred').exists())


# --- revocation + cache -----------------------------------------------------------------

class RevocationCacheTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Cache Co', slug='rc-cache')
        cls.user = make_user('rc_cache')
        cls.role = RoleTemplate.objects.create(name='Docs editor', organization=cls.org, docs_edit=True)
        cls.m = member(cls.user, cls.org, template=cls.role)

    def test_role_change_invalidates_within_request(self):
        with in_org(self.user, self.org):
            self.assertTrue(user_has_perm(self.user, 'docs_edit'))
            self.role.docs_edit = False
            self.role.save()
            self.assertFalse(user_has_perm(self.user, 'docs_edit'))

    def test_suspend_revokes(self):
        with in_org(self.user, self.org):
            self.assertTrue(user_has_org_perm(self.user, self.org, 'docs_edit'))
            self.m.is_active = False
            self.m.save()
            self.assertFalse(user_has_org_perm(self.user, self.org, 'docs_edit'))

    def test_deactivated_account(self):
        self.user.is_active = False
        self.user.save()
        self.assertFalse(user_has_org_perm(self.user, self.org, 'docs_edit'))

    def test_generation_bumps(self):
        g = authz_cache.generation()
        self.role.save()
        self.assertNotEqual(g, authz_cache.generation())

    def test_additional_role_change_invalidates(self):
        extra = RoleTemplate.objects.create(name='Extra', organization=self.org, assets_edit=True)
        with in_org(self.user, self.org):
            self.assertFalse(user_has_org_perm(self.user, self.org, 'assets_edit'))
            self.m.additional_roles.add(extra)
            self.assertTrue(user_has_org_perm(self.user, self.org, 'assets_edit'))
            self.m.additional_roles.remove(extra)
            self.assertFalse(user_has_org_perm(self.user, self.org, 'assets_edit'))


class MultiRoleTests(TestCase):
    def test_additional_roles_are_additive_within_the_membership_only(self):
        a = Organization.objects.create(name='MR A', slug='rc-mra')
        b = Organization.objects.create(name='MR B', slug='rc-mrb')
        user = make_user('rc_multi')
        m = member(user, a, template=builtin('customer_user'))
        m.additional_roles.add(builtin('customer_contract_signer'))
        member(user, b, template=builtin('customer_readonly'))
        self.assertTrue(user_has_org_perm(user, a, 'portal_contract_sign'))
        self.assertTrue(user_has_org_perm(user, a, 'tickets_create'))
        self.assertFalse(user_has_org_perm(user, b, 'portal_contract_sign'))
        self.assertFalse(user_has_org_perm(user, b, 'tickets_create'))


# --- contracts + alerts -------------------------------------------------------------------

class ContractAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Contract Co', slug='rc-contract')
        cls.rep = make_user('rc_c_rep', staff=True)
        cls.rep.profile.global_role_template = builtin('sales_rep')
        cls.rep.profile.save()
        cls.approver = make_user('rc_c_appr', staff=True)
        role = RoleTemplate.objects.create(name='Contract approver', contracts_view=True, contracts_approve=True)
        cls.approver.profile.global_role_template = role
        cls.approver.profile.save()
        cls.cadmin = make_user('rc_c_cadmin')
        member(cls.cadmin, cls.org, template=builtin('customer_admin'))
        cls.signer = make_user('rc_c_signer')
        m = member(cls.signer, cls.org, template=builtin('customer_user'))
        m.additional_roles.add(builtin('customer_contract_signer'))

    def test_staff_actions(self):
        from accounts.contract_access import can_contract
        self.assertTrue(can_contract(self.rep, self.org, 'edit_draft'))
        self.assertFalse(can_contract(self.rep, self.org, 'approve'))
        self.assertFalse(can_contract(self.rep, self.org, 'send'))
        self.assertTrue(can_contract(self.approver, self.org, 'approve'))
        own = SimpleNamespace(created_by_id=self.approver.pk, submitted_by_id=None)
        self.assertFalse(can_contract(self.approver, self.org, 'approve', contract=own))

    def test_portal_actions(self):
        from accounts.contract_access import can_contract
        self.assertFalse(can_contract(self.cadmin, self.org, 'portal_sign'))
        self.assertTrue(can_contract(self.signer, self.org, 'portal_sign'))
        self.assertFalse(can_contract(self.signer, self.org, 'view'))
        self.assertFalse(can_contract(self.rep, self.org, 'portal_sign'))

    def test_alert_recipients(self):
        from accounts.alert_access import may_receive_alert
        from accounts.contract_access import contract_alert_recipients
        recipients = set(u.pk for u in contract_alert_recipients([self.rep, self.cadmin, self.signer], self.org))
        self.assertIn(self.rep.pk, recipients)
        self.assertNotIn(self.cadmin.pk, recipients)
        self.assertTrue(may_receive_alert(self.cadmin, 'tickets_view', organization=self.org))
        self.assertFalse(may_receive_alert(self.cadmin, 'tickets_view_internal', organization=self.org))
        self.cadmin.is_active = False
        self.assertFalse(may_receive_alert(self.cadmin, 'tickets_view', organization=self.org))


# --- views ------------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RoleViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='View Co', slug='rc-view')
        cls.other = Organization.objects.create(name='View Other', slug='rc-view-o')
        cls.owner = make_user('rc_v_owner')
        cls.cadmin = make_user('rc_v_cadmin')
        cls.cuser = make_user('rc_v_cuser')
        cls.su = make_user('rc_v_su', is_superuser=True, is_staff=True)
        cls.owner_m = member(cls.owner, cls.org, 'owner')
        cls.cadmin_m = member(cls.cadmin, cls.org, template=builtin('customer_admin'))
        cls.cuser_m = member(cls.cuser, cls.org, template=builtin('customer_user'))
        cls.other_owner = make_user('rc_v_oowner')
        member(cls.other_owner, cls.other, 'owner')

    def login(self, user, org=None):
        self.client.force_login(user)
        s = self.client.session
        s['current_organization_id'] = (org or self.org).pk
        s.save()

    def test_pages_render_for_owner(self):
        self.login(self.owner)
        role = builtin('customer_user')
        for name, kw, query in (('role_list', {}, ''), ('role_detail', {'pk': role.pk}, ''),
                                ('role_create', {}, ''), ('role_compare', {}, f'?roles={role.pk}'),
                                ('access_explain', {}, f'?user={self.cuser.pk}&perm=tickets_view'),
                                ('permission_catalog', {}, ''), ('portal_access', {}, ''),
                                ('member_role_assign', {'user_id': self.cuser.pk}, '')):
            resp = self.client.get(reverse(f'accounts:{name}', kwargs=kw) + query)
            self.assertEqual(resp.status_code, 200, name)

    def test_review_list_superuser_only(self):
        self.login(self.owner)
        self.assertNotEqual(self.client.get(reverse('accounts:role_review')).status_code, 200)
        self.login(self.su)
        self.assertEqual(self.client.get(reverse('accounts:role_review')).status_code, 200)

    def test_create_previews_then_saves(self):
        self.login(self.owner)
        data = {'name': 'Ticket helper', 'audience': 'customer', 'tickets_view': 'on'}
        resp = self.client.post(reverse('accounts:role_create'), data)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(RoleTemplate.objects.filter(name='Ticket helper').exists())
        resp = self.client.post(reverse('accounts:role_create'), dict(data, action='save'))
        self.assertEqual(resp.status_code, 302)
        role = RoleTemplate.objects.get(name='Ticket helper')
        self.assertEqual(role.organization, self.org)
        self.assertTrue(AuditLog.objects.filter(extra_data__event='role.created').exists())

    def test_customer_admin_cannot_create_roles_beyond_own(self):
        self.login(self.cadmin)
        resp = self.client.post(reverse('accounts:role_create'),
                                {'name': 'Sneaky', 'action': 'save', 'vault_view_password': 'on'})
        self.assertFalse(RoleTemplate.objects.filter(name='Sneaky').exists())
        self.assertIn(resp.status_code, (200, 302))

    def test_builtin_edit_needs_superuser(self):
        self.login(self.owner)
        role = builtin('customer_user')
        self.client.post(reverse('accounts:role_edit', kwargs={'pk': role.pk}),
                         {'name': role.name, 'action': 'save', 'tickets_view': 'on', 'tickets_close': 'on'})
        role.refresh_from_db()
        self.assertFalse(role.tickets_close)

    def test_clone_and_archive(self):
        self.login(self.owner)
        role = builtin('customer_user')
        self.client.post(reverse('accounts:role_clone', kwargs={'pk': role.pk}))
        clone = RoleTemplate.objects.filter(cloned_from=role, organization=self.org).first()
        self.assertIsNotNone(clone)
        self.client.post(reverse('accounts:role_archive', kwargs={'pk': clone.pk}))
        clone.refresh_from_db()
        self.assertTrue(clone.is_archived)

    def test_assign_role_respects_delegation(self):
        self.login(self.cadmin)
        url = reverse('accounts:member_role_assign', kwargs={'user_id': self.cuser.pk})
        self.client.post(url, {'role_template_id': builtin('service_manager').pk})
        self.cuser_m.refresh_from_db()
        self.assertEqual(self.cuser_m.role_template, builtin('customer_user'))
        self.client.post(url, {'role_template_id': builtin('customer_manager').pk})
        self.cuser_m.refresh_from_db()
        self.assertEqual(self.cuser_m.role_template, builtin('customer_manager'))
        self.assertTrue(AuditLog.objects.filter(extra_data__event='delegation.denied').exists())

    def test_cannot_self_assign(self):
        self.login(self.cadmin)
        url = reverse('accounts:member_role_assign', kwargs={'user_id': self.cadmin.pk})
        self.client.post(url, {'role_template_id': builtin('org_owner').pk})
        self.cadmin_m.refresh_from_db()
        self.assertEqual(self.cadmin_m.role_template, builtin('customer_admin'))

    def test_url_org_is_authorized_not_session_org(self):
        """Owner of View Co must not edit View Other through its URL."""
        self.login(self.owner)
        resp = self.client.post(reverse('accounts:organization_edit', kwargs={'org_id': self.other.pk}),
                                {'name': 'Hijacked', 'slug': self.other.slug})
        self.other.refresh_from_db()
        self.assertEqual(self.other.name, 'View Other')
        self.assertIn(resp.status_code, (302, 403, 404))
        resp = self.client.post(reverse('accounts:member_add', kwargs={'org_id': self.other.pk}),
                                {'email': 'x@example.com', 'role': 'owner'})
        self.assertFalse(Membership.objects.filter(organization=self.other, user__email='x@example.com').exists())
        resp = self.client.post(reverse('accounts:organization_delete', kwargs={'org_id': self.other.pk}))
        self.assertTrue(Organization.objects.filter(pk=self.other.pk).exists())

    def test_suspend_is_post_only_and_keeps_last_owner(self):
        self.login(self.su)
        url = reverse('accounts:member_suspend', kwargs={'member_id': self.cuser_m.pk})
        self.client.get(url)
        self.cuser_m.refresh_from_db()
        self.assertTrue(self.cuser_m.is_active)
        self.client.post(reverse('accounts:member_suspend', kwargs={'member_id': self.owner_m.pk}))
        self.owner_m.refresh_from_db()
        self.assertTrue(self.owner_m.is_active)
        self.client.post(url)
        self.cuser_m.refresh_from_db()
        self.assertFalse(self.cuser_m.is_active)

    def test_customer_cannot_create_organizations(self):
        self.login(self.cadmin)
        self.client.post(reverse('accounts:organization_create'), {'name': 'Mine', 'slug': 'rc-mine'})
        self.assertFalse(Organization.objects.filter(slug='rc-mine').exists())

    def test_ownership_transfer_view(self):
        self.login(self.owner)
        url = reverse('accounts:ownership_transfer', kwargs={'org_id': self.org.pk})
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.post(url, {'to_user': self.cadmin.pk, 'confirm_name': self.org.name,
                               'password': 'pw-Strong-123', 'previous_owner_role': builtin('customer_admin').pk})
        self.cadmin_m.refresh_from_db()
        self.assertTrue(self.cadmin_m.is_owner())
        self.login(self.cuser)
        self.assertEqual(self.client.get(url).status_code, 302)


class AuditTests(TestCase):
    def test_role_change_audited_with_before_after_and_no_secrets(self):
        from accounts import role_audit
        org = Organization.objects.create(name='Audit Co', slug='rc-audit')
        role = RoleTemplate.objects.create(name='Audited', organization=org)
        role.docs_edit = not role.docs_edit
        role.save()
        entry = AuditLog.objects.filter(extra_data__event='role.updated').order_by('-pk').first()
        self.assertIsNotNone(entry)
        self.assertIn('docs_edit', entry.extra_data['after'])
        safe = role_audit._safe({'password': 'x', 'api_key': 'y', 'name': 'ok'})
        self.assertEqual(safe, {'name': 'ok'})

    def test_matrix_command_check(self):
        call_command('roles_matrix', '--check')


class RequestFactorySmoke(TestCase):
    def test_middleware_binds_context(self):
        from core.middleware import CurrentOrganizationMiddleware
        seen = {}

        def view(request):
            seen['ctx'] = authz_cache.current_context()
            from django.http import HttpResponse
            return HttpResponse('ok')
        request = RequestFactory().get('/')
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()
        request.session = {}
        CurrentOrganizationMiddleware(view)(request)
        self.assertIsNotNone(seen['ctx'])
        self.assertIsNone(authz_cache.current_context())


class StaffRuleTests(TestCase):
    """HELPER_ISSUES: one rule for MSP staff across user_has_perm,
    user_has_org_perm and orgs_with_perm."""

    @classmethod
    def setUpTestData(cls):
        cls.a = Organization.objects.create(name='Staff A', slug='rc-sta')
        cls.b = Organization.objects.create(name='Staff B', slug='rc-stb')

    def test_global_role_reach_is_authoritative(self):
        staff = make_user('rc_st_global', staff=True)
        staff.profile.global_role_template = builtin('tech_l1')
        staff.profile.save()
        member(staff, self.a, 'owner')
        self.assertFalse(builtin('tech_l1').reports_view_financial)
        # Row reach comes from the global role only ...
        self.assertEqual(orgs_with_perm(staff, 'reports_view_financial'), set())
        self.assertFalse(user_has_org_perm(staff, self.b, 'reports_view_financial'))
        # ... while the capability check keeps the membership grant (unchanged).
        self.assertTrue(user_has_perm_any_org(staff, 'reports_view_financial'))

    def test_staff_without_global_role_one_rule(self):
        from accounts.scope import reachable_org_ids
        staff = make_user('rc_st_legacy', staff=True)
        member(staff, self.a, 'editor')
        for perm in ('docs_edit', 'org_manage_settings'):
            held = bool(getattr(Membership(role='editor')._primary_permissions(), perm, False))
            self.assertEqual(user_has_perm(staff, perm), held, perm)
            self.assertEqual(user_has_org_perm(staff, self.b, perm), held, perm)
            self.assertEqual(orgs_with_perm(staff, perm) is None, held, perm)
            self.assertEqual(reachable_org_ids(staff, perm) is None, held, perm)
        # Neither a global role nor a membership: list reach as before
        # (orgs_with_perm), no capability.
        bare = make_user('rc_st_bare', staff=True)
        self.assertIsNone(orgs_with_perm(bare, 'docs_view'))
        self.assertFalse(user_has_org_perm(bare, self.a, 'docs_view'))
        self.assertEqual(orgs_with_perm(bare, 'vault_view'), set())
        # Vault permissions stay per membership.
        self.assertTrue(user_has_org_perm(staff, self.a, 'vault_view_password'))
        self.assertFalse(user_has_org_perm(staff, self.b, 'vault_view_password'))

    def test_require_org_perm_with_getter(self):
        from django.core.exceptions import PermissionDenied
        from accounts.permission_utils import require_org_perm
        user = make_user('rc_st_cust')
        member(user, self.a, template=builtin('customer_admin'))

        @require_org_perm('org_manage_members', org_getter=lambda request, pk: Organization.objects.get(pk=pk))
        def view(request, pk):
            return 'ok'
        req = SimpleNamespace(user=user, current_organization=self.a, path='/', META={})
        self.assertEqual(view(req, self.a.pk), 'ok')
        with self.assertRaises(PermissionDenied):
            view(req, self.b.pk)
