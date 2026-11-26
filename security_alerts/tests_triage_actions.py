"""Alert and incident triage actions (the Security Alerts guide).

- Bulk actions report the right word ("dismissed", not "dismissd") and only
  touch alerts that are still open.
- A resolved or dismissed alert is not reopened, and an acknowledged alert
  keeps its first acknowledge time (the response-time report reads it).
- An acknowledged alert can still be resolved or dismissed from its page.
- An alert that came in through a SIEM endpoint names the endpoint.
- A resolved or closed incident ignores status buttons, but still takes notes.
- Incident SLA targets can be set in the admin.
"""
from datetime import timedelta

from django.contrib import admin
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import RoleTemplate
from core.models import Organization
from psa.tests._base import TEST_MIDDLEWARE, _make_msp_tech
from security_alerts.models import (
    SecurityAlert, SecurityIncident, SecurityIncidentSLAPolicy, SIEMWebhookEndpoint,
)

_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, STORAGES=_STORAGES)
class TriageActionTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Triage Org', slug='triage-docs-org')
        user = _make_msp_tech(User.objects.create_user('triage-tech', password='pw'))
        user.profile.global_role_template = RoleTemplate.objects.create(
            name='triage role', security_alerts_view=True, security_alerts_acknowledge=True)
        user.profile.save()
        self.client = Client()
        self.client.force_login(user)
        s = self.client.session
        s['2fa_prompted'] = True
        s.save()

    def _alert(self, ext, **kw):
        return SecurityAlert.objects.create(
            organization=self.org, external_id=ext, severity='high', title=f'Alert {ext}', **kw)

    def test_bulk_dismiss_message_and_only_open_alerts(self):
        new = self._alert('a')
        done = self._alert('b', status='resolved', resolved_at=timezone.now())
        resp = self.client.post(reverse('security_alerts:alert_bulk_decide'),
                                {'decision': 'dismiss', 'alert_ids': [new.pk, done.pk]}, follow=True)
        self.assertContains(resp, '1 alert dismissed.')
        new.refresh_from_db(); done.refresh_from_db()
        self.assertEqual(new.status, 'dismissed')
        self.assertEqual(done.status, 'resolved')

    def test_bulk_resolve_keeps_earlier_resolved_time(self):
        earlier = timezone.now() - timedelta(days=2)
        done = self._alert('c', status='resolved', resolved_at=earlier)
        self.client.post(reverse('security_alerts:alert_bulk_decide'),
                         {'decision': 'resolve', 'alert_ids': [done.pk]})
        done.refresh_from_db()
        self.assertEqual(done.resolved_at, earlier)

    def test_resolved_alert_is_not_reopened_by_acknowledge(self):
        a = self._alert('d', status='resolved', resolved_at=timezone.now())
        self.client.post(reverse('security_alerts:alert_decide', args=[a.pk]), {'decision': 'acknowledge'})
        a.refresh_from_db()
        self.assertEqual(a.status, 'resolved')
        self.assertIsNone(a.acknowledged_at)

    def test_second_acknowledge_keeps_first_time(self):
        first = timezone.now() - timedelta(hours=3)
        a = self._alert('e', status='acknowledged', acknowledged_at=first)
        self.client.post(reverse('security_alerts:alert_decide', args=[a.pk]), {'decision': 'acknowledge'})
        a.refresh_from_db()
        self.assertEqual(a.acknowledged_at, first)

    def test_acknowledged_alert_can_be_resolved_from_its_page(self):
        a = self._alert('f', status='acknowledged', acknowledged_at=timezone.now())
        page = self.client.get(reverse('security_alerts:alert_detail', args=[a.pk]))
        self.assertContains(page, 'value="resolve"')
        self.assertNotContains(page, 'value="acknowledge"')
        self.client.post(reverse('security_alerts:alert_decide', args=[a.pk]), {'decision': 'resolve'})
        a.refresh_from_db()
        self.assertEqual(a.status, 'resolved')
        self.assertIsNotNone(a.resolved_at)

    def test_siem_alert_names_its_endpoint(self):
        ep = SIEMWebhookEndpoint.objects.create(organization=self.org, name='Graylog edge')
        a = self._alert('g', siem_endpoint=ep)
        page = self.client.get(reverse('security_alerts:alert_detail', args=[a.pk]))
        self.assertContains(page, 'SIEM — Graylog edge')
        lst = self.client.get(reverse('security_alerts:alert_list'))
        self.assertContains(lst, '<td>SIEM</td>', html=True)

    def test_closed_incident_ignores_status_buttons_but_takes_notes(self):
        inc = SecurityIncident.objects.create(organization=self.org, title='t', status='closed')
        url = reverse('security_alerts:incident_decide', args=[inc.pk])
        self.client.post(url, {'decision': 'acknowledge'})
        inc.refresh_from_db()
        self.assertEqual(inc.status, 'closed')
        self.client.post(url, {'decision': 'note', 'note': 'late note'})
        self.assertTrue(inc.events.filter(kind='note', message='late note').exists())

    def test_open_incident_still_moves_through_its_states(self):
        inc = SecurityIncident.objects.create(organization=self.org, title='t')
        url = reverse('security_alerts:incident_decide', args=[inc.pk])
        for decision, expected in (('acknowledge', 'investigating'), ('contain', 'contained'),
                                   ('resolve', 'resolved')):
            self.client.post(url, {'decision': decision})
            inc.refresh_from_db()
            self.assertEqual(inc.status, expected)


class SLAPolicyAdminTests(TestCase):
    def test_sla_policy_is_registered_in_the_admin(self):
        self.assertTrue(admin.site.is_registered(SecurityIncidentSLAPolicy))
