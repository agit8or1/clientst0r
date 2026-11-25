"""Per-feature permissions on access groups (accounts.group_features).

Covers: the level -> permission mapping; resolution at the group's customers
only, on top of the role, revoked when the member leaves, never granting
critical / ownership / portal keys even when stored; defaults of the default
groups (a subset of their built-in roles; the migration never widens); the
group page (levels, Advanced, refusal for permissions the editor lacks, no
protected change, reset to defaults) and its audit entries; the "why"
explanation.
"""
import importlib

from django.apps import apps as django_apps
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts import access_groups, group_features as gf, permission_registry as registry
from accounts.permission_utils import explain_access, orgs_with_perm, user_has_org_perm, user_has_perm_any_org
from accounts.role_seeds import definitions
from accounts.scope import grants_for
from accounts.tests_access_groups import Base, bare_role, builtin, group, login, staff
from accounts.tests_roles_access import TEST_MIDDLEWARE
from audit.models import AuditLog
from tech_access.models import ProtectedChange, TechnicianGroup


class LevelMappingTests(TestCase):
    def test_levels_are_cumulative_and_follow_actions(self):
        for module, _label, _desc in gf.modules():
            view, edit, full = (gf.level_keys(module, lv) for lv in (gf.VIEW, gf.EDIT, gf.FULL))
            self.assertTrue(view <= edit <= full, module)
            for k in view:
                self.assertEqual(gf.key_level(k), gf.VIEW)
        self.assertEqual(gf.level_keys('tickets', gf.VIEW), {'tickets_view', 'tickets_view_internal'})
        self.assertEqual(gf.level_keys('tickets', gf.EDIT) - gf.level_keys('tickets', gf.VIEW),
                         {'tickets_create', 'tickets_edit', 'tickets_close'})
        self.assertIn('tickets_delete', gf.level_keys('tickets', gf.FULL))
        self.assertIn('tickets_view_all', gf.level_keys('tickets', gf.FULL))
        self.assertNotIn('tickets_view_all', gf.level_keys('tickets', gf.EDIT))
        self.assertEqual(gf.level_keys('billing', gf.NONE), frozenset())

    def test_never_grantable(self):
        for k in registry.PRIVILEGED_KEYS | registry.TRANSFER_ONLY_KEYS:
            self.assertNotIn(k, gf.GRANTABLE_KEYS)
        for p in registry.PERMISSIONS:
            if p.module == 'portal' or p.status == registry.UNIMPLEMENTED:
                self.assertNotIn(p.key, gf.GRANTABLE_KEYS)
        self.assertNotIn('docs_view_internal', gf.GRANTABLE_KEYS)
        self.assertNotIn('portal', [m for m, _l, _d in gf.modules()])
        for module, _l, _d in gf.modules():
            self.assertFalse(gf.level_keys(module, gf.FULL) & registry.PRIVILEGED_KEYS)

    def test_user_admin_keys_are_advanced_only(self):
        self.assertIsNone(gf.key_level('org_manage_members'))
        self.assertNotIn('org_manage_members', gf.level_keys('org', gf.FULL))
        self.assertIn('org_manage_members', gf.module_keys('org'))

    def test_module_level_and_custom(self):
        keys = list(gf.level_keys('assets', gf.EDIT))
        self.assertEqual(gf.module_level(keys, 'assets'), gf.EDIT)
        self.assertEqual(gf.module_level(['assets_view', 'assets_delete'], 'assets'), gf.CUSTOM)
        self.assertEqual(gf.module_level([], 'assets'), gf.NONE)
        self.assertEqual(gf.clean(['roles_manage', 'tickets_view', 'tickets_view', 'nope']), ['tickets_view'])


class ResolutionTests(Base):
    def test_feature_grant_only_at_group_customers(self):
        tech = staff('gf-tech1')
        self.assertFalse(user_has_org_perm(tech, self.a, 'billing_view_invoices'))
        g = group('GF Billing view', None, customers=[self.a], members=[tech])
        g.feature_permissions = sorted(gf.level_keys('billing', gf.VIEW))
        g.save()
        self.assertTrue(user_has_org_perm(tech, self.a, 'billing_view_invoices'))
        self.assertTrue(user_has_org_perm(tech, self.a_child, 'billing_view_aging'))
        self.assertFalse(user_has_org_perm(tech, self.b, 'billing_view_invoices'))
        self.assertFalse(user_has_org_perm(tech, None, 'billing_view_invoices'))
        self.assertFalse(user_has_org_perm(tech, self.a, 'billing_send_invoices'))
        self.assertEqual(orgs_with_perm(tech, 'billing_view_invoices'), {self.a.pk, self.a_child.pk})
        self.assertTrue(any(gr.kind == 'access_group' for gr in grants_for(tech, 'billing_view_invoices')))
        # Leaving the group removes it at the next check.
        g.members.remove(tech)
        self.assertFalse(user_has_org_perm(tech, self.a, 'billing_view_invoices'))
        self.assertFalse(user_has_perm_any_org(tech, 'billing_view_invoices'))

    def test_union_with_role(self):
        tech = staff('gf-tech2')
        g = group('GF L1 plus CRM', self.l1, customers=[self.a], members=[tech])
        g.feature_permissions = ['crm_view']
        g.save()
        self.assertTrue(user_has_org_perm(tech, self.a, 'tickets_edit'))  # role
        self.assertTrue(user_has_org_perm(tech, self.a, 'crm_view'))      # feature
        self.assertFalse(user_has_org_perm(tech, self.b, 'crm_view'))
        grant = access_groups.group_grants(tech)[0]
        self.assertEqual(grant.via('crm_view'), 'feature')
        self.assertEqual(grant.via('tickets_edit'), 'role')

    def test_stored_privileged_keys_never_grant(self):
        tech = staff('gf-tech3')
        g = group('GF tampered', None, members=[tech])
        # Written straight to the row, past every form check.
        TechnicianGroup.objects.filter(pk=g.pk).update(
            feature_permissions=['org_owner', 'roles_manage', 'org_manage_privileged', 'api_keys_manage',
                                 'portal_billing_contact', 'tickets_view'])
        for k in ('org_owner', 'roles_manage', 'org_manage_privileged', 'api_keys_manage',
                  'portal_billing_contact'):
            self.assertFalse(user_has_org_perm(tech, self.a, k), k)
            self.assertFalse(user_has_perm_any_org(tech, k), k)
        self.assertTrue(user_has_org_perm(tech, self.a, 'tickets_view'))

    def test_customer_user_never_holds_feature_grants(self):
        from accounts.tests_access_groups import customer
        cu = customer('gf-cust', self.a)
        g = TechnicianGroup.objects.create(name='GF cust', feature_permissions=['crm_view'])
        TechnicianGroup.members.through.objects.bulk_create(  # bypass the staff-only signal
            [TechnicianGroup.members.through(techniciangroup_id=g.pk, user_id=cu.pk)])
        self.assertFalse(access_groups.group_grants(cu))
        self.assertFalse(user_has_org_perm(cu, self.a, 'crm_view'))

    def test_explain_names_feature_grant(self):
        tech = staff('gf-tech4')
        g = group('GF Explain', None, customers=[self.a], members=[tech])
        g.feature_permissions = ['crm_view']
        g.save()
        result = explain_access(tech, self.a, 'crm_view')
        self.assertTrue(result['allowed'])
        row = next(s for s in result['sources'] if 'GF Explain' in s['label'])
        self.assertTrue(row['grants'])
        self.assertEqual(row['via'], 'feature')
        self.assertIn('per-feature', row['note'])
        self.assertIn('per-feature', row['label'])
        self.assertFalse(explain_access(tech, self.b, 'crm_view')['allowed'])


class DefaultTests(TestCase):
    def test_defaults_are_inside_the_builtin_role(self):
        defs = {d.key: d for d in definitions()}
        for seed_key, _name, role_key, _desc in access_groups.DEFAULT_GROUPS:
            on = {k for k, v in defs[role_key].flags.items() if v}
            keys = set(gf.default_keys(seed_key))
            self.assertTrue(keys, seed_key)
            self.assertFalse(keys - on, seed_key)
            self.assertFalse(keys - gf.GRANTABLE_KEYS, seed_key)

    def test_seeded_groups_have_their_defaults(self):
        for seed_key, *_ in access_groups.DEFAULT_GROUPS:
            g = TechnicianGroup.objects.get(seed_key=seed_key)
            self.assertEqual(sorted(g.feature_permissions), gf.default_keys(seed_key), seed_key)
            # Never wider than the group's role today.
            for k in g.feature_permissions:
                self.assertTrue(getattr(g.role_template, k), (seed_key, k))

    def test_purpose_shaped(self):
        summary = gf.summary(gf.default_keys('l1_tech'))
        self.assertEqual(summary['Tickets & queues'], 'Edit')
        self.assertNotIn('Billing & finance', summary)
        billing = gf.summary(gf.default_keys('billing'))
        self.assertIn('Billing & finance', billing)
        self.assertEqual(billing['Pricing & rate cards'], 'Full')
        self.assertEqual(gf.summary(gf.default_keys('auditors'))['Assets & inventory'], 'View')
        self.assertEqual(gf.default_keys('custom-thing'), [])

    def test_migration_skips_groups_it_would_widen(self):
        mig = importlib.import_module('tech_access.migrations.0011_default_group_feature_permissions')
        l1 = TechnicianGroup.objects.get(seed_key='l1_tech')
        sales = TechnicianGroup.objects.get(seed_key='sales')
        billing = TechnicianGroup.objects.get(seed_key='billing')
        TechnicianGroup.objects.filter(seed_key__in=['l1_tech', 'sales', 'billing']).update(feature_permissions=[])
        # An administrator changed the role: the defaults would widen.
        TechnicianGroup.objects.filter(pk=l1.pk).update(role_template=builtin('auditor'))
        TechnicianGroup.objects.filter(pk=billing.pk).update(role_template=None)
        mig.forwards(django_apps, None)
        l1.refresh_from_db()
        sales.refresh_from_db()
        billing.refresh_from_db()
        self.assertEqual(l1.feature_permissions, [])
        self.assertEqual(billing.feature_permissions, [])
        self.assertEqual(sorted(sales.feature_permissions), gf.default_keys('sales'))
        # A group an administrator already set is left alone.
        TechnicianGroup.objects.filter(pk=sales.pk).update(feature_permissions=['tickets_view'])
        mig.forwards(django_apps, None)
        sales.refresh_from_db()
        self.assertEqual(sales.feature_permissions, ['tickets_view'])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class EditViewTests(Base):
    def setUp(self):
        from django.contrib.auth import get_user_model
        self.su = get_user_model().objects.create_superuser('gf-su', 'gf-su@example.com', 'pw-Strong-123')
        self.tech = staff('gf-member')
        self.c = Client()

    def _post(self, url, levels=None, keys=(), **data):
        payload = {'name': 'GF New', 'description': '', 'scope': 'all', 'members_present': '1',
                   'features_present': '1'}
        for module, _l, _d in gf.modules():
            payload[f'feat_level_{module}'] = (levels or {}).get(module, gf.NONE)
        payload['feat_key'] = list(keys)
        payload.update(data)
        return self.c.post(url, payload)

    def test_superuser_sets_levels_and_advanced_with_audit(self):
        login(self.c, self.su, self.a)
        changes = ProtectedChange.objects.count()
        self._post(reverse('accounts:access_group_create'), scope='selected', customers=[str(self.a.pk)],
                   members=[str(self.tech.pk)],
                   levels={'operations': gf.EDIT, 'procurement': gf.VIEW, 'assets': gf.CUSTOM},
                   keys=['assets_view', 'assets_delete', 'crm_view'])  # crm_view ignored: sales is None
        g = TechnicianGroup.objects.get(name='GF New')
        expected = sorted(gf.level_keys('operations', gf.EDIT) | gf.level_keys('procurement', gf.VIEW)
                          | {'assets_view', 'assets_delete'})
        self.assertEqual(sorted(g.feature_permissions), expected)
        self.assertTrue(user_has_org_perm(self.tech, self.a, 'vehicles_manage'))
        self.assertFalse(user_has_org_perm(self.tech, self.b, 'vehicles_manage'))
        self.assertFalse(user_has_org_perm(self.tech, self.a, 'crm_view'))
        self.assertEqual(ProtectedChange.objects.count(), changes)  # same rule as a group's role
        entry = AuditLog.objects.filter(extra_data__event='access_group.created', object_id=g.pk).first()
        self.assertEqual(entry.extra_data['after']['feature_permissions'], expected)
        self.assertEqual(entry.extra_data['feature_permissions_added'], expected)
        page = self.c.get(reverse('accounts:access_group_edit', args=[g.pk])).content.decode()
        self.assertIn('Permissions by feature', page)
        # Narrow it: before / after in the audit trail.
        self._post(reverse('accounts:access_group_edit', args=[g.pk]), scope='selected',
                   customers=[str(self.a.pk)], members=[str(self.tech.pk)], levels={'procurement': gf.VIEW})
        g.refresh_from_db()
        self.assertEqual(sorted(g.feature_permissions), sorted(gf.level_keys('procurement', gf.VIEW)))
        self.assertFalse(user_has_org_perm(self.tech, self.a, 'vehicles_manage'))
        upd = AuditLog.objects.filter(extra_data__event='access_group.updated', object_id=g.pk).first()
        self.assertEqual(upd.extra_data['before']['feature_permissions'], expected)
        self.assertIn('vehicles_manage', upd.extra_data['feature_permissions_removed'])

    def test_privileged_key_refused(self):
        login(self.c, self.su, self.a)
        self._post(reverse('accounts:access_group_create'), levels={'org': gf.CUSTOM}, keys=['roles_manage'])
        self.assertFalse(TechnicianGroup.objects.filter(name='GF New').exists())

    def test_post_without_matrix_keeps_features(self):
        login(self.c, self.su, self.a)
        g = group('GF Keep', None)
        g.feature_permissions = ['crm_view']
        g.save()
        self.c.post(reverse('accounts:access_group_edit', args=[g.pk]),
                    {'name': 'GF Keep', 'scope': 'all', 'members_present': '1'})
        g.refresh_from_db()
        self.assertEqual(g.feature_permissions, ['crm_view'])

    def test_editor_can_only_give_what_they_hold(self):
        role = bare_role('GF manager', roles_manage=True, tickets_view=True, tickets_view_internal=True)
        mgr = staff('gf-mgr', global_role=role)
        login(self.c, mgr, self.a)
        self._post(reverse('accounts:access_group_create'), levels={'billing': gf.VIEW})
        self.assertFalse(TechnicianGroup.objects.filter(name='GF New').exists())
        self.assertTrue(AuditLog.objects.filter(extra_data__event='delegation.denied').exists())
        self._post(reverse('accounts:access_group_create'), levels={'tickets': gf.VIEW},
                   members=[str(self.tech.pk)])
        g = TechnicianGroup.objects.get(name='GF New')
        self.assertEqual(sorted(g.feature_permissions), ['tickets_view', 'tickets_view_internal'])
        # A group holding features the editor lacks is read-only for them.
        other = group('GF Billing', None)
        other.feature_permissions = ['billing_view_invoices']
        other.save()
        self.assertTrue(access_groups.group_refusal(mgr, other))
        self._post(reverse('accounts:access_group_edit', args=[other.pk]), name='GF Billing')
        other.refresh_from_db()
        self.assertEqual(other.feature_permissions, ['billing_view_invoices'])

    def test_reset_to_defaults(self):
        login(self.c, self.su, self.a)
        l1 = TechnicianGroup.objects.get(seed_key='l1_tech')
        l1.feature_permissions = ['tickets_view']
        l1.save()
        page = self.c.get(reverse('accounts:access_group_edit', args=[l1.pk])).content.decode()
        self.assertIn('Reset to defaults', page)
        self.c.post(reverse('accounts:access_group_reset_defaults', args=[l1.pk]))
        l1.refresh_from_db()
        self.assertEqual(sorted(l1.feature_permissions), gf.default_keys('l1_tech'))
        entry = AuditLog.objects.filter(extra_data__event='access_group.features_reset', object_id=l1.pk).first()
        self.assertEqual(entry.extra_data['before']['feature_permissions'], ['tickets_view'])
        self.assertEqual(entry.extra_data['after']['feature_permissions'], gf.default_keys('l1_tech'))
        # Custom groups have no defaults.
        mine = group('GF custom', None)
        self.c.post(reverse('accounts:access_group_reset_defaults', args=[mine.pk]))
        mine.refresh_from_db()
        self.assertEqual(mine.feature_permissions, [])

    def test_reset_refused_without_management_rights(self):
        login(self.c, self.tech, self.a)
        l1 = TechnicianGroup.objects.get(seed_key='l1_tech')
        TechnicianGroup.objects.filter(pk=l1.pk).update(feature_permissions=[])
        self.c.post(reverse('accounts:access_group_reset_defaults', args=[l1.pk]))
        l1.refresh_from_db()
        self.assertEqual(l1.feature_permissions, [])
