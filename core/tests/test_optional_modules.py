"""Settings → System → Optional modules (core/modules.py).

Pins the registry (every switch is a real SystemSetting boolean, every
dependency and settings link resolves), that defaults are untouched, that
turning a module on while what it needs is off is refused, that turning a
dependency off says what stops, and that the page is superuser-only.
"""
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.db import models as dj_models
from django.test import TestCase, override_settings
from django.urls import reverse

from core import modules
from core.models import SystemSetting

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

# What these switches defaulted to before the page existed. The page must not
# change any of them.
EXPECTED_DEFAULTS = {
    'psa_enabled': False, 'psa_ai_enabled': False, 'crm_enabled': False,
    'monitoring_enabled': True, 'workflows_enabled': True, 'inventory_enabled': True,
    'scheduling_enabled': True, 'vehicles_enabled': True, 'webhooks_enabled': True,
    'global_kb_enabled': True, 'psa_csat_enabled': False,
    'psa_portal_announcements_enabled': False, 'psa_portal_voting_enabled': False,
    'psa_portal_escalation_enabled': False, 'psa_portal_customer_approvals_enabled': False,
    'asset_age_warnings_enabled': False, 'warranty_checks_enabled': False,
    'firmware_checks_enabled': False,
    'reports_enabled': True, 'secure_notes_enabled': True,
}


class RegistryTests(TestCase):

    def test_every_switch_is_a_systemsetting_boolean(self):
        for m in modules.MODULES:
            if m.field:
                f = SystemSetting._meta.get_field(m.field)
                self.assertIsInstance(f, dj_models.BooleanField, m.key)

    def test_defaults_unchanged(self):
        fields = {m.field for m in modules.MODULES if m.field}
        self.assertEqual(fields, set(EXPECTED_DEFAULTS))
        for name, default in EXPECTED_DEFAULTS.items():
            self.assertIs(SystemSetting._meta.get_field(name).default, default, name)

    def test_dependencies_and_links_resolve(self):
        for m in modules.MODULES:
            for k in m.requires + m.works_better_with:
                self.assertIn(k, modules.MODULES_BY_KEY, m.key)
            for _label, name in m.settings_links:
                self.assertTrue(reverse(name), name)

    def test_known_dependencies(self):
        for key in ('ticket_ai', 'portal', 'routing', 'csat', 'security_alerts',
                    'portal_announcements', 'portal_voting', 'portal_escalation', 'portal_approvals'):
            self.assertIn('psa', modules.MODULES_BY_KEY[key].requires, key)
        self.assertIn('monitoring', modules.MODULES_BY_KEY['status_pages'].requires)
        self.assertTrue(modules.MODULES_BY_KEY['ticket_ai'].optional_ai)

    def test_no_saved_but_unused_switch_list_is_left(self):
        # Every switch the old "saved but not used" list named is now either
        # enforced (reports, secure notes: listed as modules) or removed.
        self.assertFalse(hasattr(modules, 'UNENFORCED_SWITCHES'))
        for removed in ('psa_portal_enabled', 'psa_anonymous_ticket_form_enabled',
                        'psa_email_to_ticket_enabled', 'psa_sms_notifications_enabled',
                        'psa_desktop_alerts_enabled', 'psa_external_alert_ingest_enabled'):
            with self.assertRaises(Exception):
                SystemSetting._meta.get_field(removed)
        self.assertEqual(modules.MODULES_BY_KEY['reports'].field, 'reports_enabled')
        self.assertEqual(modules.MODULES_BY_KEY['secure_notes'].field, 'secure_notes_enabled')

    def test_fresh_install_states(self):
        s = SystemSetting.get_settings()
        rows = {r['module'].key: r for _g, rs in modules.describe(s) for r in rs}
        self.assertFalse(rows['psa']['on'])
        self.assertFalse(rows['routing']['on'])      # no RoutingSettings row = Off
        self.assertFalse(rows['portal']['on'])
        self.assertTrue(rows['monitoring']['active'])
        self.assertEqual([d.key for d in rows['ticket_ai']['missing']], ['psa'])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ModulesPageTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.su = User.objects.create_superuser('mod_su', 'su@x.com', 'pw')
        cls.tech = User.objects.create_user('mod_tech', 't@x.com', 'pw', is_staff=True)
        cls.url = reverse('core:settings_modules')

    def setUp(self):
        self.client.force_login(self.su)

    def _post(self, module, enabled):
        return self.client.post(self.url, {'module': module, 'enabled': enabled}, follow=True)

    def test_page_lists_every_module(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        for m in modules.MODULES:
            self.assertIn(f'data-module="{m.key}"', html)
        self.assertIn('OPTIONAL AI', html)
        self.assertNotIn('id="unenforced-switches"', html)

    def test_page_is_superuser_only(self):
        self.client.force_login(self.tech)
        r = self.client.get(self.url)
        self.assertNotEqual(r.status_code, 200)
        self.client.post(self.url, {'module': 'psa', 'enabled': 'on'})
        self.assertFalse(SystemSetting.get_settings().psa_enabled)

    def test_turning_on_ai_while_psa_is_off_is_refused(self):
        r = self._post('ticket_ai', 'on')
        self.assertFalse(SystemSetting.get_settings().psa_ai_enabled)
        self.assertContains(r, 'needs PSA / Service desk turned on first')

    def test_turn_on_psa_then_ai(self):
        self._post('psa', 'on')
        self._post('ticket_ai', 'on')
        s = SystemSetting.get_settings()
        self.assertTrue(s.psa_enabled)
        self.assertTrue(s.psa_ai_enabled)
        from audit.models import AuditLog
        self.assertTrue(AuditLog.objects.filter(object_repr='Optional module: Ticket AI').exists())

    def test_turning_off_psa_warns_about_dependents_and_keeps_their_switch(self):
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.psa_ai_enabled = True
        s.save()
        r = self._post('psa', 'off')
        s = SystemSetting.get_settings()
        self.assertFalse(s.psa_enabled)
        self.assertTrue(s.psa_ai_enabled)
        self.assertContains(r, 'stop working until PSA / Service desk is on again: Ticket AI')
        self.assertContains(r, 'data-module="ticket_ai" data-state="inactive"')

    def test_soft_dependency_warns(self):
        self._post('psa', 'on')
        r = self._post('portal_voting', 'on')
        self.assertTrue(SystemSetting.get_settings().psa_portal_voting_enabled)
        self.assertContains(r, 'does little until Customer portal is on as well')

    def test_managed_elsewhere_modules_cannot_be_switched_here(self):
        r = self._post('routing', 'on')
        self.assertContains(r, 'Nothing was changed')

    def test_bad_action_changes_nothing(self):
        self.client.post(self.url, {'module': 'psa', 'enabled': 'maybe'})
        self.assertFalse(SystemSetting.get_settings().psa_enabled)

    def test_routing_state_follows_routing_mode(self):
        from psa.routing.models import RoutingSettings
        rs = RoutingSettings.load()
        rs.mode = 'suggest'
        rs.save()
        html = self.client.get(self.url).content.decode()
        self.assertIn('data-module="routing" data-state="inactive"', html)   # PSA still off
        self.assertIn('Mode: Suggest only', html)

    def test_in_settings_menu(self):
        html = self.client.get(reverse('core:settings_features')).content.decode()
        self.assertIn(self.url, html)

    def test_features_page_warns_when_psa_turned_off_under_dependents(self):
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.psa_ai_enabled = True
        s.save()
        r = self.client.post(reverse('core:settings_features'), {
            'monitoring_enabled': 'on', 'workflows_enabled': 'on'}, follow=True)
        self.assertContains(r, 'Ticket AI')
        self.assertContains(r, 'Optional modules')
