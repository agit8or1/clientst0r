"""SR-09 (re-delivery never lowers severity) and SR-08 (auto-ticket dedup,
hourly cap, unsigned webhooks on the Security Overview)."""
from django.test import TestCase
from django.utils import timezone

from audit.models import AuditLog
from psa.models import Ticket
from security_alerts.adapters import base as adapter_base
from security_alerts.ingest import upsert_alert
from security_alerts.models import SecurityAlert, SecurityAlertRule, SIEMWebhookEndpoint
from security_alerts.tests import _make_conn, _make_org, _seed_psa


class RedeliveryTests(TestCase):
    def setUp(self):
        self.org = _make_org()
        self.conn = _make_conn(self.org)

    def _deliver(self, severity, title='Ransomware'):
        return upsert_alert({'connection': self.conn, 'external_id': 'e-1'},
                            {'organization': self.org, 'severity': severity, 'title': title})

    def test_second_delivery_cannot_lower_severity_and_is_recorded(self):
        alert, created = self._deliver('critical')
        self.assertTrue(created)
        alert.status = 'acknowledged'
        alert.save()
        again, created = self._deliver('low', title='Ransomware (updated)')
        self.assertFalse(created)
        again.refresh_from_db()
        self.assertEqual(again.severity, 'critical')
        self.assertEqual(again.title, 'Ransomware (updated)')
        self.assertEqual(again.status, 'acknowledged')
        self.assertTrue(AuditLog.objects.filter(
            extra_data__event='security_alert_severity_downgrade_refused', object_id=alert.pk).exists())

    def test_raising_severity_is_allowed(self):
        self._deliver('low')
        alert, _ = self._deliver('high')
        alert.refresh_from_db()
        self.assertEqual(alert.severity, 'high')


class AutoTicketFloodTests(TestCase):
    def setUp(self):
        _seed_psa()
        self.org = _make_org()
        self.conn = _make_conn(self.org)
        SecurityAlertRule.objects.create(organization=self.org, name='all', match_severity_min='info')

    def _alert(self, ext, title='Malware found', asset='PC-1'):
        a = SecurityAlert.objects.create(connection=self.conn, organization=self.org, external_id=ext,
                                         severity='high', title=title, asset_hint=asset)
        adapter_base._maybe_auto_ticket(a)
        a.refresh_from_db()
        return a

    def test_same_asset_and_title_join_one_ticket(self):
        alerts = [self._alert(f'x-{i}') for i in range(50)]
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual({a.auto_ticket_id for a in alerts}, {alerts[0].auto_ticket_id})

    def test_hourly_cap_stops_new_tickets_but_keeps_alerts(self):
        cap = adapter_base.AUTO_TICKET_HOURLY_CAP
        for i in range(cap + 5):
            self._alert(f'c-{i}', title=f'Distinct {i}')
        self.assertEqual(Ticket.objects.count(), cap)
        self.assertEqual(SecurityAlert.objects.filter(connection=self.conn).count(), cap + 5)
        self.assertEqual(AuditLog.objects.filter(extra_data__event='security_auto_ticket_cap').count(), 1)

    def test_siem_alert_without_connection_does_not_crash(self):
        ep = SIEMWebhookEndpoint.objects.create(organization=self.org, name='SIEM')
        a = SecurityAlert.objects.create(siem_endpoint=ep, organization=self.org, external_id='s-1',
                                         severity='high', title='From SIEM')
        adapter_base._maybe_auto_ticket(a)
        a.refresh_from_db()
        self.assertIsNotNone(a.auto_ticket)


class UnsignedWebhookOverviewTests(TestCase):
    def test_unsigned_sources_are_listed(self):
        from security_alerts.overview import _alerts_widget
        org = _make_org()
        _make_conn(org, require_signature=False)
        SIEMWebhookEndpoint.objects.create(organization=org, name='Old SIEM', require_hmac=False)
        SIEMWebhookEndpoint.objects.create(organization=org, name='Signed SIEM', require_hmac=True)
        w = _alerts_widget([org], lambda *a, **k: '', timezone.now())
        self.assertEqual(sorted(w['unsigned']), ['Old SIEM', 'Test conn'])
