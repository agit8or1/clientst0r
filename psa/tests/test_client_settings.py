"""Per-customer PSA settings page (psa:client_settings): only the two
switches something reads (native PSA opt-out, customer portal) remain."""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role
from audit.models import AuditLog
from core.models import Organization
from psa.models import ClientPSASettings
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_global, _make_msp_tech

DEAD = ('anonymous_ticket_form_enabled', 'email_to_ticket_enabled', 'sms_notifications_enabled',
        'desktop_alerts_enabled', 'external_alert_ingest_enabled')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ClientPSASettingsPageTests(TestCase):

    def setUp(self):
        _enable_psa_global()
        self.org = Organization.objects.create(name='CS Acme', slug='cs-acme')
        self.admin = User.objects.create_superuser('cs_admin', 'a@x.test', 'pw')
        self.url = reverse('psa:client_settings')

    def _login(self, user, org=None):
        self.client.force_login(user)
        s = self.client.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.pk
        s.save()

    def test_dead_switches_are_gone_from_model_and_page(self):
        fields = {f.name for f in ClientPSASettings._meta.get_fields()}
        for name in DEAD:
            self.assertNotIn(name, fields)
        self._login(self.admin, self.org)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'name="portal_enabled"')
        self.assertContains(r, 'name="enabled"')
        for name in DEAD:
            self.assertNotContains(r, name)

    def test_portal_switch_saves_audits_and_opens_the_portal(self):
        member = User.objects.create_user('cs_member', 'm@x.test', 'pw')
        Membership.objects.create(user=member, organization=self.org, role=Role.EDITOR)
        from portal.views import _portal_memberships
        self.assertEqual(_portal_memberships(member), [])

        self._login(self.admin, self.org)
        r = self.client.post(self.url, {'enabled': 'on', 'portal_enabled': 'on'})
        self.assertEqual(r.status_code, 302)
        cps = ClientPSASettings.objects.get(organization=self.org)
        self.assertTrue(cps.portal_enabled and cps.enabled)
        self.assertEqual([m.organization for m in _portal_memberships(member)], [self.org])
        log = AuditLog.objects.get(object_type='psa.ClientPSASettings', object_id=cps.pk)
        self.assertEqual(log.extra_data['changed_fields']['portal_enabled']['to'], True)

    def test_opt_out_and_reset_keep_the_portal_switch(self):
        self._login(self.admin, self.org)
        self.client.post(self.url, {'portal_enabled': 'on'})  # enabled unticked = opt out
        cps = ClientPSASettings.objects.get(organization=self.org)
        self.assertFalse(cps.enabled)
        self.client.post(self.url, {'reset_to_auto': '1'})
        cps.refresh_from_db()
        self.assertTrue(cps.enabled)
        self.assertTrue(cps.portal_enabled)

    def test_global_page_remove_opt_out_keeps_the_portal_switch(self):
        ClientPSASettings.objects.create(organization=self.org, enabled=False, portal_enabled=True)
        self._login(self.admin, self.org)
        self.client.post(reverse('psa:settings'), {'action': 'remove_opt_out',
                                                   'organization_id': self.org.pk})
        cps = ClientPSASettings.objects.get(organization=self.org)
        self.assertTrue(cps.enabled)
        self.assertTrue(cps.portal_enabled)

    def test_only_superusers(self):
        tech = _make_msp_tech(User.objects.create_user('cs_tech', 't@x.test', 'pw'))
        self._login(tech, self.org)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url, {'portal_enabled': 'on'}).status_code, 404)
        self.assertFalse(ClientPSASettings.objects.filter(organization=self.org).exists())

    def test_no_customer_selected_redirects(self):
        self._login(self.admin)
        s = self.client.session
        s['global_view_mode'] = True
        s.save()
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)
