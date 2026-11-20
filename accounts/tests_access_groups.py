"""Access groups (staff groups carrying a role at a customer scope) and the
tidied built-in role names.

Covers: a member holds the group's role at the group's customers and not at
others, on top of their own access; enforcement in the permission helpers,
the REST API and a background path with no request; revocation when a member
or the group is removed; customer users refused; privileged groups managed
only at that level; the audit trail; default groups seeded once; the role
renames keep everyone's permissions, keep an administrator's name, and
name-based lookups (RMM tiers, init_role_templates) still resolve; legacy
roles keep working and are grouped in pickers.
"""
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts import access_groups, authz_cache, role_order
from accounts.models import Membership, RoleReviewItem, RoleTemplate, UserType
from accounts.permission_utils import (navigable_org_ids, orgs_with_perm, staff_client_org_ids, user_has_org_perm, user_has_perm,
                                       user_has_perm_any_org)
from accounts.role_seeds import rename_builtin_roles, seed_builtin_roles
from accounts.tests_roles_access import TEST_MIDDLEWARE, builtin, in_org
from audit.models import AuditLog
from core.models import Organization
from tech_access.models import TechnicianGroup

User = get_user_model()


def staff(username, global_role=None, scope='all', scope_orgs=()):
    u = User.objects.create_user(username, f'{username}@example.com', 'pw-Strong-123')
    p = u.profile
    p.user_type = UserType.STAFF
    p.global_role_template = global_role
    p.client_scope = scope
    p.save()
    if scope_orgs:
        p.scope_organizations.set(scope_orgs)
    return User.objects.get(pk=u.pk)


def bare_role(name, **flags):
    """A role holding exactly `flags` (RoleTemplate defaults some view flags on)."""
    values = {k: False for k in RoleTemplate.permission_field_names()}
    values.update(flags)
    return RoleTemplate.objects.create(name=name, **values)


def customer(username, org):
    u = User.objects.create_user(username, f'{username}@example.com', 'pw-Strong-123')
    Membership.objects.create(user=u, organization=org, role='readonly',
                              role_template=builtin('customer_user'))
    return u


def group(name, role, customers=None, members=()):
    g = TechnicianGroup.objects.create(name=name, role_template=role, all_customers=customers is None)
    if customers:
        g.customers.set(customers)
    if members:
        g.members.add(*members)
    return g


def login(client, user, org=None):
    client.force_login(user)
    s = client.session
    s['2fa_prompted'] = True
    if org is not None:
        s['current_organization_id'] = org.pk
    s.save()


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = Organization.objects.create(name='AG Alpha', slug='ag-alpha')
        cls.a_child = Organization.objects.create(name='AG Alpha Branch', slug='ag-alpha-branch', parent=cls.a)
        cls.b = Organization.objects.create(name='AG Beta', slug='ag-beta')
        cls.l1 = builtin('tech_l1')
        cls.sales = builtin('sales_rep')


# --- resolution ------------------------------------------------------------------------------

class ResolutionTests(Base):
    def test_member_holds_role_at_scoped_customers_only(self):
        tech = staff('ag-tech1')
        self.assertFalse(user_has_org_perm(tech, self.a, 'tickets_edit'))
        group('AG L1 Alpha', self.l1, customers=[self.a], members=[tech])
        self.assertTrue(user_has_org_perm(tech, self.a, 'tickets_edit'))
        self.assertTrue(user_has_org_perm(tech, self.a_child, 'tickets_edit'))  # subsidiary
        self.assertFalse(user_has_org_perm(tech, self.b, 'tickets_edit'))
        self.assertFalse(user_has_org_perm(tech, self.a, 'billing_view_invoices'))  # not in the role
        self.assertEqual(orgs_with_perm(tech, 'tickets_view'), {self.a.pk, self.a_child.pk})
        # The role is not MSP-wide.
        self.assertFalse(user_has_org_perm(tech, None, 'tickets_view'))

    def test_all_customers_scope(self):
        tech = staff('ag-tech2')
        group('AG L1 All', self.l1, members=[tech])
        self.assertTrue(user_has_org_perm(tech, self.b, 'tickets_edit'))
        self.assertIsNone(orgs_with_perm(tech, 'tickets_view'))
        self.assertTrue(access_groups.holds_msp_wide(tech, 'tickets_view'))

    def test_union_with_global_role_keeps_each_grant_scope(self):
        tech = staff('ag-tech3', global_role=self.sales, scope='selected', scope_orgs=[self.b])
        group('AG L1 Alpha 2', self.l1, customers=[self.a], members=[tech])
        # The group's role at Alpha, the global role at Beta - never crossed.
        self.assertTrue(user_has_org_perm(tech, self.a, 'tickets_edit'))
        self.assertFalse(user_has_org_perm(tech, self.a, 'crm_view'))
        self.assertTrue(user_has_org_perm(tech, self.b, 'crm_view'))
        self.assertEqual(orgs_with_perm(tech, 'crm_view'), {self.b.pk})
        self.assertTrue(orgs_with_perm(tech, 'tickets_edit') >= {self.a.pk})
        # Navigation reaches both; row scope stays the client scope.
        self.assertEqual(navigable_org_ids(tech), {self.a.pk, self.a_child.pk, self.b.pk})
        self.assertEqual(staff_client_org_ids(tech), {self.b.pk})
        # With a customer selected the capability check answers for it.
        with in_org(tech, self.a):
            self.assertFalse(user_has_perm(tech, 'crm_view'))
            self.assertTrue(user_has_perm(tech, 'tickets_edit'))
        with in_org(tech, self.b):
            self.assertTrue(user_has_perm(tech, 'crm_view'))

    def test_row_scoping_one_grant_per_group(self):
        from accounts.scope import grants_for, reachable_org_ids
        tech = staff('ag-tech4')
        group('AG L1 Alpha 3', self.l1, customers=[self.a], members=[tech])
        kinds = [g.kind for g in grants_for(tech, 'tickets_view')]
        self.assertEqual(kinds, ['access_group'])
        self.assertEqual(reachable_org_ids(tech, 'tickets_view'), {self.a.pk, self.a_child.pk})
        # A staff account with no global role and no membership used to reach
        # every client for lists; a group member gets the group's reach only.
        self.assertEqual(reachable_org_ids(tech, 'assets_view'), {self.a.pk, self.a_child.pk})

    def test_group_without_role_or_members_grants_nothing(self):
        tech = staff('ag-tech5')
        group('AG presets only', None, members=[tech])
        self.assertFalse(access_groups.group_grants(tech))
        g = group('AG empty', self.l1)
        self.assertFalse(g.members.exists())
        self.assertFalse(user_has_org_perm(tech, self.a, 'tickets_edit'))

    def test_customer_user_never_holds_group_role(self):
        cu = customer('ag-cust0', self.a)
        g = group('AG L1 c', self.l1)
        # Even if a row slipped in (bypassing the add guard), it grants nothing.
        TechnicianGroup.members.through.objects.create(techniciangroup=g, user=cu)
        self.assertFalse(access_groups.group_grants(cu))
        self.assertFalse(user_has_org_perm(cu, self.a, 'tickets_view_internal'))

    def test_explain_names_the_group(self):
        from accounts.permission_utils import explain_access
        tech = staff('ag-tech6')
        group('AG Explain', self.l1, customers=[self.a], members=[tech])
        result = explain_access(tech, self.a, 'tickets_edit')
        self.assertTrue(result['allowed'])
        self.assertTrue(any('AG Explain' in s['label'] and s['grants'] for s in result['sources']))


class RevocationTests(Base):
    def test_removing_member_or_group_revokes_at_next_check(self):
        tech = staff('ag-rev1')
        g = group('AG Rev', self.l1, customers=[self.a], members=[tech])
        with in_org(tech, self.a):
            self.assertTrue(user_has_org_perm(tech, self.a, 'tickets_edit'))
            g.members.remove(tech)
            self.assertFalse(user_has_org_perm(tech, self.a, 'tickets_edit'))
            g.members.add(tech)
            self.assertTrue(user_has_org_perm(tech, self.a, 'tickets_edit'))
            g.customers.set([self.b])
            self.assertFalse(user_has_org_perm(tech, self.a, 'tickets_edit'))
            g.delete()
            self.assertFalse(user_has_org_perm(tech, self.b, 'tickets_edit'))
            self.assertFalse(user_has_perm_any_org(tech, 'tickets_edit'))

    def test_role_change_applies(self):
        tech = staff('ag-rev2')
        g = group('AG Rev2', self.l1, members=[tech])
        with in_org(tech, self.a):
            self.assertFalse(user_has_org_perm(tech, self.a, 'crm_view'))
            g.role_template = self.sales
            g.save()
            self.assertTrue(user_has_org_perm(tech, self.a, 'crm_view'))
            self.assertFalse(user_has_org_perm(tech, self.a, 'tickets_edit'))

    def test_deleting_the_role_leaves_group_granting_nothing(self):
        role = bare_role('AG temp role', tickets_view=True)
        tech = staff('ag-rev3')
        g = group('AG Rev3', role, members=[tech])
        role.delete()
        g.refresh_from_db()
        self.assertIsNone(g.role_template)
        self.assertFalse(user_has_org_perm(tech, self.a, 'tickets_view'))


# --- enforcement outside views -----------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class APIEnforcementTests(Base):
    def test_rest_api_lists_only_group_customers(self):
        from assets.models import Asset
        Asset.objects.create(organization=self.a, name='ag-asset-alpha', asset_type='server')
        Asset.objects.create(organization=self.b, name='ag-asset-beta', asset_type='server')
        # A global role without assets_view: the group is the only source.
        tech = staff('ag-api1', global_role=bare_role('AG api none'))
        g = group('AG API', self.l1, customers=[self.a], members=[tech])
        c = Client()
        login(c, tech, self.a)

        def names():
            resp = c.get('/api/assets/?organization=all')
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            rows = data['results'] if isinstance(data, dict) and 'results' in data else data
            return {r['name'] for r in rows}

        self.assertEqual(names(), {'ag-asset-alpha'})
        g.members.remove(tech)
        self.assertEqual(names(), set())


class BackgroundPathTests(Base):
    def test_ticket_assignment_check_without_request(self):
        """psa.routing (used by the routing engine and workflow rules, which
        run as background jobs): who may be given a customer's tickets."""
        from psa.routing.engine import _authorization_problem
        self.assertIsNone(authz_cache.current_context())
        tech = staff('ag-job1', global_role=self.sales, scope='selected', scope_orgs=[self.b])
        self.assertIsNotNone(_authorization_problem(tech, self.a, None, set()))
        g = group('AG Job', self.l1, customers=[self.a], members=[tech])
        self.assertIsNone(_authorization_problem(tech, self.a, None, set()))
        g.members.remove(tech)
        self.assertIsNotNone(_authorization_problem(tech, self.a, None, set()))

    def test_msp_wide_checks_need_all_customers(self):
        from core.dashboard_views import can_manage_role_defaults
        from reports.access import has_msp_wide_perm
        tech = staff('ag-job2', global_role=bare_role('AG nothing'))
        g = group('AG Wide', builtin('org_admin'), customers=[self.a], members=[tech])
        self.assertFalse(can_manage_role_defaults(tech))
        self.assertFalse(has_msp_wide_perm(tech, 'reports_export'))
        g.all_customers = True
        g.save()
        g.customers.clear()
        self.assertTrue(can_manage_role_defaults(tech))
        self.assertTrue(has_msp_wide_perm(tech, 'reports_export'))

    def test_group_never_grants_rmm_tier(self):
        from rmm_permissions.decision import tier_of
        tech = staff('ag-job3')
        group('AG Tier', builtin('tech_l2'), members=[tech])
        self.assertEqual(tier_of(tech), '')
        holder = staff('ag-job4', global_role=builtin('tech_l2'))
        self.assertEqual(tier_of(holder), 'l2')


# --- membership rules ------------------------------------------------------------------------

class MembershipRuleTests(Base):
    def test_customer_user_can_not_be_added(self):
        cu = customer('ag-cust1', self.a)
        g = group('AG Staff only', self.l1)
        with self.assertRaises(ValidationError), transaction.atomic():
            g.members.add(cu)
        with self.assertRaises(ValidationError), transaction.atomic():
            cu.technician_groups.add(g)
        self.assertFalse(g.members.exists())
        self.assertTrue(access_groups.member_refusal(None, cu))

    def test_groups_never_set_account_flags(self):
        tech = staff('ag-flags')
        group('AG Owners test', builtin('org_owner'), members=[tech])
        tech.refresh_from_db()
        self.assertFalse(tech.is_superuser)
        self.assertFalse(tech.is_staff)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ManagementViewTests(Base):
    def setUp(self):
        self.su = User.objects.create_superuser('ag-su', 'ag-su@example.com', 'pw-Strong-123')
        self.tech = staff('ag-member')
        self.c = Client()

    def _post(self, url, **data):
        payload = {'name': 'AG New', 'description': '', 'scope': 'all', 'members_present': '1'}
        payload.update(data)
        return self.c.post(url, payload)

    def test_superuser_creates_edits_and_deletes_with_audit(self):
        login(self.c, self.su, self.a)
        self.assertEqual(self.c.get(reverse('accounts:access_group_list')).status_code, 200)
        self.assertEqual(self.c.get(reverse('accounts:access_group_create')).status_code, 200)
        self._post(reverse('accounts:access_group_create'), role=str(self.l1.pk), scope='selected',
                   customers=[str(self.a.pk)], members=[str(self.tech.pk)])
        g = TechnicianGroup.objects.get(name='AG New')
        self.assertEqual(g.role_template, self.l1)
        self.assertFalse(g.all_customers)
        self.assertEqual(list(g.members.all()), [self.tech])
        self.assertTrue(user_has_org_perm(self.tech, self.a, 'tickets_edit'))
        created = AuditLog.objects.filter(extra_data__event='access_group.created', object_id=g.pk).first()
        self.assertIsNotNone(created)
        self.assertEqual(created.extra_data['after']['role'], self.l1.name)
        self.assertEqual(self.c.get(reverse('accounts:access_group_edit', args=[g.pk])).status_code, 200)
        # Remove the member and widen the scope.
        self._post(reverse('accounts:access_group_edit', args=[g.pk]), role=str(self.l1.pk), scope='all')
        self.assertFalse(g.members.exists())
        self.assertFalse(user_has_org_perm(self.tech, self.a, 'tickets_edit'))
        updated = AuditLog.objects.filter(extra_data__event='access_group.updated', object_id=g.pk).first()
        self.assertEqual(updated.extra_data['before']['members'], ['ag-member'])
        self.assertEqual(updated.extra_data['after']['members'], [])
        self.assertTrue(updated.extra_data['after']['all_customers'])
        self.c.post(reverse('accounts:access_group_delete', args=[g.pk]))
        self.assertFalse(TechnicianGroup.objects.filter(pk=g.pk).exists())
        self.assertTrue(AuditLog.objects.filter(extra_data__event='access_group.deleted', object_id=g.pk).exists())

    def test_customer_user_refused_by_the_page(self):
        cu = customer('ag-cust2', self.a)
        login(self.c, self.su, self.a)
        self._post(reverse('accounts:access_group_create'), role=str(self.l1.pk), members=[str(cu.pk)])
        self.assertFalse(TechnicianGroup.objects.filter(name='AG New').exists())

    def test_plain_staff_can_not_open_pages(self):
        login(self.c, self.tech, self.a)
        self.assertEqual(self.c.get(reverse('accounts:access_group_list')).status_code, 302)
        self._post(reverse('accounts:access_group_create'), role=str(self.l1.pk))
        self.assertFalse(TechnicianGroup.objects.filter(name='AG New').exists())

    def test_administrator_can_not_manage_owner_level_group(self):
        admin = staff('ag-admin', global_role=builtin('org_admin'))
        login(self.c, admin, self.a)
        self.assertEqual(self.c.get(reverse('accounts:access_group_list')).status_code, 200)
        owner_role = builtin('org_owner')
        self._post(reverse('accounts:access_group_create'), role=str(owner_role.pk),
                   members=[str(self.tech.pk)])
        self.assertFalse(TechnicianGroup.objects.filter(name='AG New').exists())
        self.assertFalse(user_has_org_perm(self.tech, self.a, 'org_owner'))
        owners = TechnicianGroup.objects.get(seed_key='owners')
        self._post(reverse('accounts:access_group_edit', args=[owners.pk]), name='Owners',
                   role=str(owner_role.pk), members=[str(self.tech.pk)])
        self.assertFalse(owners.members.exists())
        self.c.post(reverse('accounts:access_group_delete', args=[owners.pk]))
        self.assertTrue(TechnicianGroup.objects.filter(pk=owners.pk).exists())
        self.assertTrue(AuditLog.objects.filter(extra_data__event='delegation.denied').exists())
        # A group with a role inside the administrator's own permissions is fine.
        small = bare_role('AG tickets only', tickets_view=True)
        self._post(reverse('accounts:access_group_create'), role=str(small.pk), members=[str(self.tech.pk)])
        self.assertTrue(TechnicianGroup.objects.filter(name='AG New', members=self.tech).exists())

    def test_roles_manage_without_privileged_level_refused_for_admin_group(self):
        manager_role = bare_role('AG role manager', roles_manage=True, tickets_view=True)
        mgr = staff('ag-mgr', global_role=manager_role)
        self.assertTrue(access_groups.can_manage(mgr))
        self.assertTrue(access_groups.role_refusal(mgr, builtin('org_admin')))
        self.assertTrue(access_groups.role_refusal(mgr, builtin('customer_user')))
        login(self.c, mgr, self.a)
        admins = TechnicianGroup.objects.get(seed_key='administrators')
        self._post(reverse('accounts:access_group_edit', args=[admins.pk]), name='Administrators',
                   role=str(admins.role_template_id), members=[str(self.tech.pk)])
        self.assertFalse(admins.members.exists())

    def test_no_self_service(self):
        manager_role = bare_role('AG role manager 2', roles_manage=True, tickets_view=True)
        mgr = staff('ag-mgr2', global_role=manager_role)
        role = bare_role('AG tickets only 2', tickets_view=True)
        self.assertTrue(access_groups.member_refusal(mgr, mgr))
        g = group('AG mine', role, members=[mgr])
        self.assertTrue(access_groups.group_refusal(mgr, g))

    def test_user_page_and_role_page_show_groups(self):
        g = group('AG Shown', self.l1, members=[self.tech])
        login(self.c, self.su, self.a)
        page = self.c.get(reverse('accounts:user_detail', args=[self.tech.pk])).content.decode()
        self.assertIn('AG Shown', page)
        page = self.c.get(reverse('accounts:role_detail', args=[self.l1.pk])).content.decode()
        self.assertIn('AG Shown', page)
        self.assertTrue(g.pk)


# --- default groups -----------------------------------------------------------------------

class DefaultGroupTests(TestCase):
    EXPECTED = {'L1 Tech': 'tech_l1', 'L2 Tech': 'tech_l2', 'L3 Tech': 'tech_l3', 'Managers': 'service_manager',
                'Sales': 'sales_rep', 'Sales Managers': 'sales_manager', 'Owners': 'org_owner',
                'Administrators': 'org_admin', 'Billing': 'billing_finance', 'Auditors': 'auditor'}

    def test_seeded_empty_all_customers(self):
        for name, key in self.EXPECTED.items():
            g = TechnicianGroup.objects.get(name=name)
            self.assertEqual(g.role_template.seed_key, key)
            self.assertTrue(g.all_customers)
            self.assertFalse(g.members.exists())

    def test_reseed_is_idempotent_and_keeps_edits(self):
        g = TechnicianGroup.objects.get(seed_key='l1_tech')
        g.name = 'Help desk'
        g.role_template = builtin('auditor')
        g.save()
        before = TechnicianGroup.objects.count()
        summary = access_groups.seed_default_groups(TechnicianGroup, RoleTemplate)
        self.assertEqual(summary['created'], [])
        self.assertEqual(TechnicianGroup.objects.count(), before)
        g.refresh_from_db()
        self.assertEqual((g.name, g.role_template.seed_key), ('Help desk', 'auditor'))

    def test_existing_group_with_the_name_is_left_alone(self):
        TechnicianGroup.objects.filter(seed_key='billing').delete()
        mine = TechnicianGroup.objects.create(name='Billing')
        access_groups.seed_default_groups(TechnicianGroup, RoleTemplate)
        mine.refresh_from_db()
        self.assertIsNone(mine.role_template)
        self.assertEqual(TechnicianGroup.objects.filter(name='Billing').count(), 1)


# --- role tidy-up --------------------------------------------------------------------------

OLD_NAMES = {'tech_l1': 'RMM L1 — Help Desk', 'tech_l2': 'RMM L2 — Technician',
             'tech_l3': 'RMM L3 — Senior Technician', 'service_manager': 'Service Manager',
             'sales_rep': 'Sales Representative', 'auditor': 'Internal Read-Only / Auditor'}
NEW_NAMES = {'tech_l1': 'L1 Tech', 'tech_l2': 'L2 Tech', 'tech_l3': 'L3 Tech', 'service_manager': 'Manager',
             'sales_rep': 'Sales', 'auditor': 'Auditor'}


class RoleRenameTests(TestCase):
    def test_builtin_names_after_migration(self):
        for key, name in NEW_NAMES.items():
            self.assertEqual(builtin(key).name, name)
        self.assertEqual(builtin('org_owner').name, 'Owner')
        self.assertEqual(builtin('org_admin').name, 'Organization Administrator')
        self.assertEqual(builtin('sales_manager').name, 'Sales Manager')
        self.assertEqual(builtin('billing_finance').name, 'Billing / Finance')

    def test_rename_from_old_names_keeps_every_permission(self):
        from accounts.permission_utils import effective_permissions
        for key, old in OLD_NAMES.items():
            RoleTemplate.objects.filter(seed_key=key, organization__isnull=True).update(name=old)
        org = Organization.objects.create(name='AG Rename', slug='ag-rename')
        tech = staff('ag-ren1', global_role=builtin('tech_l1'))
        member = User.objects.create_user('ag-ren2', 'r2@example.com', 'pw-Strong-123')
        Membership.objects.create(user=member, organization=org, role='readonly',
                                  role_template=builtin('service_manager'))
        Membership.objects.get(user=member).additional_roles.add(builtin('auditor'))
        before = (effective_permissions(tech, org), effective_permissions(member, org))
        sums = {k: builtin(k).seed_checksum for k in OLD_NAMES}
        summary = seed_builtin_roles(RoleTemplate)
        self.assertEqual(len(summary['renamed']), len(OLD_NAMES))
        for key, name in NEW_NAMES.items():
            role = builtin(key)
            self.assertEqual(role.name, name)
            self.assertEqual(role.seed_checksum, sums[key])
            self.assertFalse(role.is_customized)
        tech, member = User.objects.get(pk=tech.pk), User.objects.get(pk=member.pk)
        self.assertEqual((effective_permissions(tech, org), effective_permissions(member, org)), before)

    def test_admin_renamed_role_keeps_its_name(self):
        RoleTemplate.objects.filter(seed_key='tech_l2').update(name='Field Engineer')
        seed_builtin_roles(RoleTemplate)
        self.assertEqual(builtin('tech_l2').name, 'Field Engineer')

    def test_new_name_taken_is_reviewed_not_renamed(self):
        RoleTemplate.objects.filter(seed_key='service_manager').update(name='Service Manager')
        RoleTemplate.objects.create(name='Manager', organization=None)
        done = rename_builtin_roles(RoleTemplate)
        self.assertNotIn('Service Manager -> Manager', done)
        self.assertEqual(builtin('service_manager').name, 'Service Manager')

    def test_migration_rename_reviews_clash(self):
        import importlib

        from django.apps import apps
        mig = importlib.import_module('accounts.migrations.0065_builtin_role_display_names')
        RoleTemplate.objects.filter(seed_key='sales_rep').update(name='Sales Representative')
        RoleTemplate.objects.create(name='Sales', organization=None)
        mig.forwards(apps, None)
        self.assertEqual(builtin('sales_rep').name, 'Sales Representative')
        self.assertTrue(RoleReviewItem.objects.filter(role_template=builtin('sales_rep'), reason='other').exists())
        RoleTemplate.objects.filter(name='Sales', seed_key='').delete()
        mig.forwards(apps, None)
        self.assertEqual(builtin('sales_rep').name, 'Sales')
        mig.backwards(apps, None)
        self.assertEqual(builtin('sales_rep').name, 'Sales Representative')

    def test_rmm_tiers_still_resolve(self):
        from core import dashboard_widgets as dw
        from rmm_permissions.decision import tier_of
        for key, tier, preset in (('tech_l1', 'l1', dw.PRESET_L1), ('tech_l2', 'l2', dw.PRESET_L2),
                                  ('tech_l3', 'l3', dw.PRESET_L3)):
            role = builtin(key)
            self.assertEqual(role.rmm_tier, tier)
            u = staff(f'ag-tier-{tier}', global_role=role)
            self.assertEqual(tier_of(u), tier)
            self.assertEqual(dw.preset_for_user(u), preset)

    def test_init_role_templates_does_not_recreate_old_rmm_names(self):
        RoleTemplate.get_or_create_system_templates()
        for old in ('RMM L1 — Help Desk', 'RMM L2 — Technician', 'RMM L3 — Senior Technician'):
            self.assertFalse(RoleTemplate.objects.filter(name=old).exists(), old)
        for tier in ('l1', 'l2', 'l3'):
            self.assertEqual(RoleTemplate.objects.filter(organization=None, rmm_tier=tier).count(), 1)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RoleOrderTests(TestCase):
    def setUp(self):
        self.legacy = RoleTemplate.objects.create(name='AG Legacy Editor', is_system_template=True,
                                                  docs_view=True, docs_edit=True)

    def test_order_and_legacy_bucket(self):
        roles = list(RoleTemplate.objects.filter(organization__isnull=True))
        keys = [r.seed_key for r in role_order.ordered(roles) if r.seed_key]
        want = ['org_owner', 'org_admin', 'service_manager', 'tech_l1', 'tech_l2', 'tech_l3', 'sales_rep',
                'sales_manager', 'billing_finance', 'security_analyst', 'security_admin', 'auditor']
        self.assertEqual(keys[:len(want)], want)
        self.assertTrue(all(k.startswith('customer_') for k in keys[len(want):]))
        self.assertEqual(role_order.bucket(self.legacy), role_order.LEGACY)
        self.assertEqual(role_order.ordered(roles)[-1].seed_key, '')

    def test_legacy_role_still_works(self):
        org = Organization.objects.create(name='AG Legacy', slug='ag-legacy')
        u = User.objects.create_user('ag-leg', 'leg@example.com', 'pw-Strong-123')
        Membership.objects.create(user=u, organization=org, role='readonly', role_template=self.legacy)
        self.assertTrue(user_has_org_perm(u, org, 'docs_edit'))

    def test_global_role_picker_grouped(self):
        from accounts.forms import UserEditForm
        u = staff('ag-form')
        form = UserEditForm(instance=u)
        html = str(form['global_role_template'])
        self.assertIn('<optgroup label="Built-in roles">', html)
        self.assertIn('<optgroup label="Legacy roles">', html)
        self.assertLess(html.index('>Owner<'), html.index('>L1 Tech<'))
        self.assertLess(html.index('>L1 Tech<'), html.index('AG Legacy Editor'))

    def test_member_role_page_shows_legacy_section(self):
        org = Organization.objects.create(name='AG Picker', slug='ag-picker')
        su = User.objects.create_superuser('ag-su2', 'su2@example.com', 'pw-Strong-123')
        target = User.objects.create_user('ag-target', 't@example.com', 'pw-Strong-123')
        Membership.objects.create(user=target, organization=org, role='readonly')
        c = Client()
        login(c, su, org)
        page = c.get(reverse('accounts:member_role_assign', args=[target.pk])).content.decode()
        self.assertIn('Legacy roles', page)
        self.assertIn('AG Legacy Editor', page)
        page = c.get(reverse('accounts:role_list')).content.decode()
        self.assertIn('Legacy roles', page)


# --- review: group customers never widen another permission's row scope ------------------------

class _Req:
    """A request-shaped object for core.tenancy (staff, a customer selected)."""

    def __init__(self, user, org):
        self.user = user
        self.is_staff_user = True
        self.current_organization = org


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class GroupRowScopeTests(Base):
    """L1 technician: global role L1 (vault_view, assets_view) with client
    scope {A}; member of a "Sales" group (sales_rep: no vault / assets) at X."""

    def setUp(self):
        self.x = Organization.objects.create(name='AG Xray', slug='ag-xray')
        self.tech = staff('ag-scope-tech', global_role=self.l1, scope='selected', scope_orgs=[self.a])
        self.sales_group = group('AG Sales X', self.sales, customers=[self.x], members=[self.tech])
        self.tech = User.objects.get(pk=self.tech.pk)

    def test_tenancy_row_scope_is_direct_unless_perm_given(self):
        from core.tenancy import accessible_org_ids, scope_to_request
        from vault.models import Password
        Password.objects.create(organization=self.a, title='AG pw alpha')
        Password.objects.create(organization=self.x, title='AG pw xray')
        req = _Req(self.tech, self.a)
        with in_org(self.tech, self.a):
            self.assertTrue(user_has_perm(self.tech, 'vault_view'))
            reach = accessible_org_ids(req)
            self.assertNotIn(self.x.pk, reach)
            titles = set(scope_to_request(Password.objects.all(), req).values_list('title', flat=True))
            self.assertEqual(titles, {'AG pw alpha'})
            titles = set(scope_to_request(Password.objects.all(), req, perm='vault_view')
                         .values_list('title', flat=True))
            self.assertEqual(titles, {'AG pw alpha'})
            # (c) a permission the group does grant reaches X.
            self.assertIn(self.x.pk, accessible_org_ids(req, perm='crm_view'))
            self.assertIn(self.x.pk, accessible_org_ids(req, perm='tickets_view'))
        self.assertEqual(orgs_with_perm(self.tech, 'vault_view'), {self.a.pk, self.a_child.pk})
        self.assertIn(self.x.pk, orgs_with_perm(self.tech, 'crm_view'))
        self.assertNotIn(self.a.pk, orgs_with_perm(self.tech, 'crm_view'))
        self.assertEqual(staff_client_org_ids(self.tech), {self.a.pk, self.a_child.pk})

    def test_api_list_with_alpha_selected_never_shows_xray(self):
        from assets.models import Asset
        Asset.objects.create(organization=self.a, name='ag-scope-alpha', asset_type='server')
        Asset.objects.create(organization=self.x, name='ag-scope-xray', asset_type='server')
        c = Client()
        login(c, self.tech, self.a)
        for url in ('/api/assets/', '/api/assets/?organization=all'):
            resp = c.get(url)
            self.assertEqual(resp.status_code, 200, url)
            data = resp.json()
            rows = data['results'] if isinstance(data, dict) and 'results' in data else data
            self.assertNotIn('ag-scope-xray', {r['name'] for r in rows}, url)

    def test_xray_selected_only_group_role_applies(self):
        from core.client_switcher import authorized_organizations
        self.assertFalse(user_has_org_perm(self.tech, self.x, 'vault_view'))
        self.assertFalse(user_has_org_perm(self.tech, self.x, 'assets_view'))
        self.assertTrue(user_has_org_perm(self.tech, self.x, 'crm_view'))
        with in_org(self.tech, self.x):
            self.assertFalse(user_has_perm(self.tech, 'vault_view'))
            self.assertFalse(user_has_perm(self.tech, 'assets_view'))
            self.assertTrue(user_has_perm(self.tech, 'crm_view'))
        # X can be selected (navigation), but row scope stays direct.
        req = _Req(self.tech, self.x)
        self.assertIn(self.x, list(authorized_organizations(req)))
        from core.tenancy import accessible_org_ids
        self.assertNotIn(self.x.pk, accessible_org_ids(req))

    def test_selecting_xray_through_the_middleware(self):
        c = Client()
        login(c, self.tech, self.a)
        resp = c.get(reverse('accounts:switch_organization', args=[self.x.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(c.session.get('current_organization_id'), self.x.pk)

    def test_workflow_rules_need_the_rule_permission_from_the_group(self):
        from psa.models import WorkflowRule
        from psa.workflow_access import visible_org_ids, visible_rules

        def rule(name, org):
            return WorkflowRule.objects.create(name=name, trigger='ticket_created', organization=org,
                                               conditions={}, actions=[{'type': 'add_tag', 'tag': 't'}],
                                               is_active=True)
        rule('AG rule alpha', self.a)
        rule('AG rule xray', self.x)
        names = set(visible_rules(WorkflowRule.objects.all(), self.tech).values_list('name', flat=True))
        self.assertIn('AG rule alpha', names)
        self.assertNotIn('AG rule xray', names)
        self.assertNotIn(self.x.pk, visible_org_ids(self.tech))
        rule_role = bare_role('AG workflow editor', psa_manage_workflow_rules=True, tickets_view=True)
        self.sales_group.role_template = rule_role
        self.sales_group.save()
        names = set(visible_rules(WorkflowRule.objects.all(), self.tech).values_list('name', flat=True))
        self.assertIn('AG rule xray', names)

    def test_report_scope_and_background_assignment(self):
        from psa.routing.engine import _authorization_problem
        from reports.access import viewer_client_scope
        # MSP-wide report figures: the technician's own client scope only.
        self.assertEqual(viewer_client_scope(self.tech), sorted({self.a.pk, self.a_child.pk}))
        # Background (no request): Sales grants tickets_view at X, so the
        # routing engine may give X's tickets; a customer outside both is refused.
        other = Organization.objects.create(name='AG Other', slug='ag-other')
        self.assertIsNone(_authorization_problem(self.tech, self.x, None, set()))
        self.assertIsNotNone(_authorization_problem(self.tech, other, None, set()))

    def test_workspace_device_ids_per_permission(self):
        from core import workspace
        from assets.models import Asset
        alpha = Asset.objects.create(organization=self.a, name='ag-ws-alpha', asset_type='server')
        xray = Asset.objects.create(organization=self.x, name='ag-ws-xray', asset_type='server')
        kind = next(k for k, v in workspace.DEVICE_KINDS.items() if v[2] == 'assets_view')
        req = _Req(self.tech, self.a)
        with in_org(self.tech, self.a):
            ids = set(workspace._visible_device_ids(req, kind, [alpha.pk, xray.pk]).values_list('pk', flat=True))
        self.assertEqual(ids, {alpha.pk})
