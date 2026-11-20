"""Roadmap 51.23: workflow rules follow the technician's client scope and the
psa_manage_workflow_rules role permission (replacing @require_admin)."""
import json

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, RoleTemplate
from core.models import Organization
from psa.models import WorkflowRule, WorkflowRuleTemplate
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_global, _make_msp_tech, _setup_seed


def _login(user):
    c = Client()
    c.force_login(user)
    s = c.session
    s['2fa_prompted'] = True
    s.save()
    return c


def _rule(name, org=None, **kw):
    return WorkflowRule.objects.create(name=name, trigger='ticket_created', organization=org,
                                       conditions={}, actions=kw.pop('actions', [{'type': 'add_tag', 'tag': 't'}]),
                                       is_active=True, **kw)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WorkflowRuleScopeTests(TestCase):
    def setUp(self):
        _setup_seed()
        _enable_psa_global()
        self.a = Organization.objects.create(name='Cust A', slug='wrs-a')
        self.b = Organization.objects.create(name='Cust B', slug='wrs-b')
        self.rule_a = _rule('Rule A', self.a)
        self.rule_b = _rule('Rule B', self.b)
        self.rule_all = _rule('Rule All')

        self.manager_role = RoleTemplate.objects.create(name='WF manager', psa_manage_workflow_rules=True,
                                                        tickets_view=True)
        # Technician restricted to customer A, holding the workflow permission.
        self.tech = User.objects.create_user('wrs-tech', 'wrs@msp.example', 'pw')
        _make_msp_tech(self.tech)
        p = self.tech.profile
        p.global_role_template = self.manager_role
        p.client_scope = 'selected'
        p.save()
        p.scope_organizations.set([self.a])

        # Unrestricted technician with the same role.
        self.lead = User.objects.create_user('wrs-lead', 'lead@msp.example', 'pw')
        _make_msp_tech(self.lead)
        self.lead.profile.global_role_template = self.manager_role
        self.lead.profile.save()

        self.admin = User.objects.create_superuser('wrs-admin', 'adm@msp.example', 'pw')

    def _post_rule(self, c, url, org='', **over):
        data = {'name': 'New one', 'trigger': 'ticket_created', 'is_active': 'on', 'organization': org,
                'conditions': '{}', 'actions': json.dumps([{'type': 'add_tag', 'tag': 'x'}]),
                'else_actions': '[]'}
        data.update(over)
        return c.post(url, data)

    # --- seeing -------------------------------------------------------------
    def test_restricted_tech_sees_only_in_scope_and_msp_wide_rules(self):
        resp = _login(self.tech).get('/psa/rules/')
        self.assertEqual(resp.status_code, 200)
        names = {r.name for r in resp.context['rules']}
        self.assertEqual(names, {'Rule A', 'Rule All'})
        self.assertNotContains(resp, 'Rule B')
        self.assertEqual(resp.context['editable_ids'], {self.rule_a.pk})

    def test_flow_pages_are_scoped(self):
        c = _login(self.tech)
        self.assertEqual(c.get(f'/psa/rules/{self.rule_b.pk}/flow/').status_code, 404)
        self.assertEqual(c.get(f'/psa/rules/{self.rule_a.pk}/flow/').status_code, 200)
        resp = c.get('/psa/rules/flow/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Rule B')

    def test_msp_wide_flow_does_not_reveal_other_customers_chained_rule(self):
        chained = _rule('Secret B', self.b, actions=[{'type': 'add_tag', 'tag': 'b-only'}])
        parent = _rule('Fan out', actions=[{'type': 'fire_rule', 'name': chained.name}])
        resp = _login(self.tech).get(f'/psa/rules/{parent.pk}/flow/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Secret B')
        self.assertNotContains(resp, 'b-only')

    def test_workflow_report_is_scoped(self):
        from django.urls import reverse
        self.manager_role.reports_view_dashboards = True
        self.manager_role.save()
        resp = _login(self.tech).get(reverse('reports:workflow_performance_report') + '?format=csv')
        if resp.status_code == 200:
            self.assertIn(b'Rule A', resp.content)
        self.assertNotIn(b'Rule B', resp.content)

    # --- changing -------------------------------------------------------------
    def test_other_customers_rule_edit_and_delete_are_404(self):
        c = _login(self.tech)
        self.assertEqual(c.get(f'/psa/rules/{self.rule_b.pk}/edit/').status_code, 404)
        self.assertEqual(self._post_rule(c, f'/psa/rules/{self.rule_b.pk}/edit/', org=self.a.pk).status_code, 404)
        self.assertEqual(c.post(f'/psa/rules/{self.rule_b.pk}/delete/').status_code, 404)
        self.assertTrue(WorkflowRule.objects.filter(pk=self.rule_b.pk).exists())
        self.rule_b.refresh_from_db()
        self.assertEqual(self.rule_b.organization_id, self.b.pk)

    def test_msp_wide_rule_is_read_only_for_restricted_tech(self):
        c = _login(self.tech)
        self.assertEqual(c.get(f'/psa/rules/{self.rule_all.pk}/edit/').status_code, 403)
        self.assertEqual(c.post(f'/psa/rules/{self.rule_all.pk}/delete/').status_code, 403)
        self.assertTrue(WorkflowRule.objects.filter(pk=self.rule_all.pk).exists())

    def test_restricted_tech_manages_own_customers_rule(self):
        c = _login(self.tech)
        self.assertEqual(c.get(f'/psa/rules/{self.rule_a.pk}/edit/').status_code, 200)
        resp = self._post_rule(c, '/psa/rules/new/', org=self.a.pk)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(WorkflowRule.objects.get(name='New one').organization_id, self.a.pk)
        self.assertEqual(c.post(f'/psa/rules/{self.rule_a.pk}/delete/').status_code, 302)
        self.assertFalse(WorkflowRule.objects.filter(pk=self.rule_a.pk).exists())

    def test_cannot_create_rule_for_out_of_scope_customer_or_msp_wide(self):
        c = _login(self.tech)
        self.assertEqual(self._post_rule(c, '/psa/rules/new/', org=self.b.pk).status_code, 400)
        self.assertEqual(self._post_rule(c, '/psa/rules/new/', org='').status_code, 400)
        self.assertFalse(WorkflowRule.objects.filter(name='New one').exists())
        # Nor move an in-scope rule to another customer.
        self.assertEqual(self._post_rule(c, f'/psa/rules/{self.rule_a.pk}/edit/', org=self.b.pk).status_code, 400)
        self.rule_a.refresh_from_db()
        self.assertEqual(self.rule_a.organization_id, self.a.pk)

    def test_form_offers_only_scope(self):
        resp = _login(self.tech).get('/psa/rules/new/')
        self.assertEqual(list(resp.context['client_orgs']), [self.a])
        self.assertFalse(resp.context['can_msp_wide'])
        self.assertNotIn('Rule B', resp.context['rule_names'])

    def test_actions_cannot_name_other_customers_people(self):
        portal_b = User.objects.create_user('wrs-portal-b', password='x')
        Membership.objects.create(user=portal_b, organization=self.b)
        tech_b = User.objects.create_user('wrs-tech-b', password='x')
        _make_msp_tech(tech_b)
        tech_b.profile.global_role_template = RoleTemplate.objects.create(name='B tech', tickets_view=True)
        tech_b.profile.client_scope = 'selected'
        tech_b.profile.save()
        tech_b.profile.scope_organizations.set([self.b])
        c = _login(self.tech)
        for action in ({'type': 'add_watcher', 'username': 'wrs-portal-b'},
                       {'type': 'assign_to', 'username': 'wrs-tech-b'},
                       {'type': 'assign_to', 'username': 'nobody-here'}):
            with self.subTest(action=action):
                resp = self._post_rule(c, '/psa/rules/new/', org=self.a.pk, actions=json.dumps([action]))
                self.assertEqual(resp.status_code, 400)
        self.assertFalse(WorkflowRule.objects.filter(name='New one').exists())
        # A customer-A contact and a technician who can work A are fine.
        portal_a = User.objects.create_user('wrs-portal-a', password='x')
        Membership.objects.create(user=portal_a, organization=self.a)
        resp = self._post_rule(c, '/psa/rules/new/', org=self.a.pk, actions=json.dumps([
            {'type': 'add_watcher', 'username': 'wrs-portal-a'},
            {'type': 'assign_to', 'username': 'wrs-lead'}]))
        self.assertEqual(resp.status_code, 302)

    def test_template_instantiation_is_scoped(self):
        tpl = WorkflowRuleTemplate.objects.create(name='Tpl', trigger='ticket_created', conditions={},
                                                  actions=[{'type': 'add_tag', 'tag': 'tpl'}])
        c = _login(self.tech)
        resp = c.get('/psa/rules/templates/')
        self.assertEqual(list(resp.context['organizations']), [self.a])
        self.assertEqual(self._instantiate(c, tpl, self.b.pk), 404)
        self.assertEqual(self._instantiate(c, tpl, ''), 403)
        self.assertEqual(self._instantiate(c, tpl, self.a.pk), 302)
        self.assertEqual(WorkflowRule.objects.filter(organization=self.b, name__startswith='Tpl').count(), 0)

    def _instantiate(self, c, tpl, org):
        from django.urls import reverse
        return c.post(reverse('psa:workflow_template_instantiate', args=[tpl.pk]),
                      {'organization': org}).status_code

    # --- permission -------------------------------------------------------------
    def test_staff_without_permission_cannot_write(self):
        plain = User.objects.create_user('wrs-plain', password='x')
        _make_msp_tech(plain)
        plain.profile.global_role_template = RoleTemplate.objects.create(name='Plain', tickets_view=True)
        plain.profile.save()
        c = _login(plain)
        self.assertEqual(c.get('/psa/rules/').status_code, 200)  # read-only list, as before
        self.assertEqual(c.get('/psa/rules/new/').status_code, 403)
        self.assertEqual(self._post_rule(c, '/psa/rules/new/', org=self.a.pk).status_code, 403)
        self.assertEqual(c.post(f'/psa/rules/{self.rule_a.pk}/delete/').status_code, 403)
        self.assertEqual(c.get('/psa/rules/flow/').status_code, 403)

    def test_unrestricted_manager_and_superuser_keep_full_access(self):
        for user in (self.lead, self.admin):
            with self.subTest(user=user.username):
                c = _login(user)
                resp = c.get('/psa/rules/')
                self.assertTrue({'Rule A', 'Rule B', 'Rule All'} <= {r.name for r in resp.context['rules']})
                self.assertEqual(c.get(f'/psa/rules/{self.rule_b.pk}/edit/').status_code, 200)
                self.assertEqual(c.get(f'/psa/rules/{self.rule_all.pk}/edit/').status_code, 200)
                resp = self._post_rule(c, '/psa/rules/new/', org='', name=f'Wide {user.pk}')
                self.assertEqual(resp.status_code, 302)
                self.assertIsNone(WorkflowRule.objects.get(name=f'Wide {user.pk}').organization_id)

    def test_builtin_admin_roles_hold_the_permission(self):
        # Existing installs: the seeded administrator roles keep rule editing.
        from accounts.role_seeds import definitions
        flags = {d.key: d.flags.get('psa_manage_workflow_rules') for d in definitions()}
        held = [k for k, v in flags.items() if v]
        self.assertTrue(held)
        from accounts import permission_registry as reg
        self.assertEqual(reg.get('psa_manage_workflow_rules').status, reg.ENFORCED)
