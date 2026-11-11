"""Alert → ticket policy tests (psa/routing/alert_policy.py).

Rem0te alerts go through the real intake (integrations/rem0te/alerts.py,
signed events against the in-process Rem0te); synced alerts through
RMMSync._upsert_alert. AI is switched off throughout.
"""
import itertools
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import Organization, SystemSetting
from integrations.models import RMMAlert, RMMConnection, RMMDevice
from integrations.rem0te import alerts, pairing, testing as rt
from psa.models import Queue, Ticket, TicketComment, TicketPriority
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_global, _setup_seed

from . import alert_policy
from .models import (
    AlertIncident, AlertMaintenanceWindow, AlertPolicyRule, AlertPolicySettings, AlertTicketLink,
)

_seq = itertools.count(1)


def _ai_off():
    s = SystemSetting.get_settings()
    s.psa_enabled = True
    s.psa_ai_enabled = False
    s.save()


def policy_on(**kw):
    s = AlertPolicySettings.load()
    s.mode = 'policy'
    for k, v in kw.items():
        setattr(s, k, v)
    s.save()
    return s


class AlertBase(TestCase):
    """Customer Alpha with a paired Rem0te, a site 'HQ' and devices on it."""

    def setUp(self):
        _setup_seed()
        _enable_psa_global()
        _ai_off()
        from assets.models import Asset
        from tech_access.testing import make_tech
        self.org = Organization.objects.create(name='Alpha Dental', slug='alpha')
        self.other = Organization.objects.create(name='Beta Law', slug='beta')
        rt.setup_identity()
        self.conn = rt.make_connection(self.org, name='Rem0te alpha')
        self.fake = rt.FakeRem0te()
        cm = self.fake.running()
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        self.assertTrue(pairing.check(self.conn)['compatible'])
        self.conn.refresh_from_db()
        self.tech = make_tech('lee')
        self.asset = Asset.objects.create(organization=self.org, name='Server', hostname='SRV-01', asset_type='server')
        self.device = self.make_device('srv01', 'SRV-01', asset=self.asset)
        self.org_ref = pairing.organization_id(self.conn)

    def make_device(self, ext, name, asset=None, site='HQ', site_id='hq', **kw):
        return RMMDevice.objects.create(organization=self.org, connection=self.conn, external_id=f'cmendpoint{ext}',
                                        device_name=name, linked_asset=asset, site_name=site, site_id=site_id,
                                        device_type=kw.pop('device_type', 'server'), is_online=kw.pop('online', True),
                                        data_refreshed_at=timezone.now(), **kw)

    def event(self, alert_id, kind, title, endpoint, etype='alert.raised', severity='warning', site='HQ',
              outage=None, occurrences=1):
        signed = self.fake.alert_event(self.org_ref, next(_seq), etype=etype, alert_id=alert_id,
                                       endpoint=f'cmendpoint{endpoint}', computer=endpoint.upper(), severity=severity)
        ev = signed['alert_event']
        ev['alert'].update(kind=kind, title=title, site_name=site, outage_alert_id=outage, occurrences=occurrences)
        signed['signature'] = rt.sign_event(ev, alert=True)
        return signed

    def deliver(self, signed):
        status, outcome = alerts.apply_signed_alert_event(self.conn, signed)
        self.assertEqual(status, 200, outcome)
        return outcome

    def raise_alert(self, alert_id, kind='DISK_FREE', title='SRV-01: C: 4% free (3.2 GB)', endpoint='srv01', **kw):
        signed = self.event(alert_id, kind, title, endpoint, **kw)
        self.deliver(signed)
        return signed

    def resolve(self, alert_id, kind='DISK_FREE', title='SRV-01: C: 4% free (3.2 GB)', endpoint='srv01', **kw):
        return self.deliver(self.event(alert_id, kind, title, endpoint, etype='alert.resolved', **kw))

    def link(self, alert_id):
        return AlertTicketLink.objects.get(connection=self.conn, external_id=alert_id)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class LegacyAndDedupTests(AlertBase):

    def test_legacy_mode_is_unchanged(self):
        self.assertEqual(AlertPolicySettings.load().mode, 'legacy')
        self.raise_alert('cmalert0001')
        self.raise_alert('cmalert0002')
        self.assertEqual(Ticket.objects.filter(source='rmm').count(), 2)  # one per alert, as before
        self.assertFalse(AlertTicketLink.objects.exists())
        self.resolve('cmalert0001')
        self.assertFalse(TicketComment.objects.exists())

    def test_duplicate_deliveries_open_one_ticket(self):
        policy_on()
        signed = self.raise_alert('cmalert0001')
        self.assertEqual(alerts.apply_signed_alert_event(self.conn, signed), (200, 'duplicate'))
        self.raise_alert('cmalert0001')  # re-raised under a new event id
        alerts.poll(self.conn)           # and polled again
        self.assertEqual(Ticket.objects.filter(source='rmm').count(), 1)
        self.assertEqual(AlertTicketLink.objects.count(), 1)
        link = self.link('cmalert0001')
        self.assertEqual(link.disposition, 'created')
        t = link.ticket
        self.assertEqual((t.organization, t.related_asset, t.visibility, t.client_can_view),
                         (self.org, self.asset, 'staff', False))
        self.assertIsNotNone(t.resolution_due_at)  # SLA from the priority
        from psa_ai.models import Rem0teAlertTicket
        self.assertEqual(Rem0teAlertTicket.objects.get(alert_id='cmalert0001').ticket, t)
        self.assertEqual(self.fake.links['cmalert0001']['ticket_id'], t.ticket_number)

    def test_same_device_same_issue_joins_the_open_ticket(self):
        policy_on()
        self.raise_alert('cmalert0001')
        self.raise_alert('cmalert0002', title='SRV-01: C: 3% free (2.4 GB)')
        self.assertEqual(Ticket.objects.filter(source='rmm').count(), 1)
        first, second = self.link('cmalert0001'), self.link('cmalert0002')
        self.assertEqual((second.disposition, second.ticket), ('attached', first.ticket))
        self.assertTrue(TicketComment.objects.filter(ticket=first.ticket, is_internal=True,
                                                     body__startswith='Repeat alert').exists())
        # A different issue on the same computer is a different ticket.
        self.raise_alert('cmalert0003', kind='SERVICE_STOPPED', title='SRV-01: service Spooler is Stopped')
        self.assertEqual(Ticket.objects.filter(source='rmm').count(), 2)
        # After the ticket is closed, the issue opens a new one.
        resolved = first.ticket.status.__class__.objects.get(slug='resolved')
        Ticket.objects.filter(pk=first.ticket_id).update(status=resolved)
        self.raise_alert('cmalert0004')
        self.assertEqual(self.link('cmalert0004').disposition, 'created')

    def test_alert_for_another_customers_computer_gets_no_device(self):
        policy_on()
        from integrations.models import RMMDevice as D
        other_conn = rt.make_connection(self.other, name='Rem0te beta')
        D.objects.create(organization=self.other, connection=other_conn, external_id='cmendpointtheirs',
                         device_name='SRV-01')
        self.raise_alert('cmalertx', endpoint='theirs')
        link = self.link('cmalertx')
        self.assertEqual(link.organization, self.org)
        self.assertIsNone(link.device)
        self.assertIsNone(link.ticket.related_asset)

    def test_ignore_rule_and_rule_snapshot(self):
        policy_on()
        rule = AlertPolicyRule.objects.create(name='Ignore CPU', conditions={'categories': ['cpu']}, action='ignore')
        self.raise_alert('cmalertcpu', kind='CPU_HIGH', title='SRV-01: CPU 97%')
        link = self.link('cmalertcpu')
        self.assertEqual((link.disposition, link.ticket), ('ignored', None))
        self.assertEqual(link.rule_snapshot['name'], 'Ignore CPU')
        rule.name = 'Renamed'
        rule.save()
        link.refresh_from_db()
        self.assertEqual(link.rule_snapshot['name'], 'Ignore CPU')
        self.assertFalse(Ticket.objects.filter(source='rmm').exists())

    def test_rule_queue_priority_and_named_technician(self):
        policy_on()
        from tech_access.testing import grant
        grant(self.tech, self.org, 'l2')
        q = Queue.objects.get(name='Escalations')
        p1 = TicketPriority.objects.get(code='P1')
        AlertPolicyRule.objects.create(name='Alpha disks to Lee', organization=self.org,
                                       conditions={'categories': ['disk']}, queue=q, ticket_priority=p1,
                                       assign_mode='technician', assign_user=self.tech)
        self.raise_alert('cmalert0001')
        t = self.link('cmalert0001').ticket
        self.assertEqual((t.queue, t.priority, t.assigned_to), (q, p1, self.tech))
        self.assertEqual(t.resolution_due_at, t.created_at + timedelta(minutes=p1.resolution_target_minutes))

    def test_named_technician_not_authorized_is_not_assigned(self):
        policy_on()
        outsider = User.objects.create_user('cust', 'c@x.test', 'pw')  # not MSP staff
        AlertPolicyRule.objects.create(name='Bad', conditions={}, assign_mode='technician', assign_user=outsider)
        self.raise_alert('cmalert0001')
        link = self.link('cmalert0001')
        self.assertIsNone(link.ticket.assigned_to)
        self.assertIn('not an MSP technician', link.reason)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class OutageHoldMaintenanceTests(AlertBase):

    def test_site_outage_of_50_computers_is_one_ticket(self):
        policy_on(site_outage_threshold=5, offline_hold_minutes=5)
        for i in range(50):
            self.make_device(f'pc{i:02d}', f'PC-{i:02d}', device_type='workstation')
        before = Ticket.objects.count()
        for i in range(50):
            self.raise_alert(f'cmoff{i:02d}', kind='OFFLINE', title=f'PC-{i:02d} is offline', endpoint=f'pc{i:02d}',
                             severity='critical')
        alert_policy.tick(now=timezone.now() + timedelta(minutes=30))  # nothing left to release
        self.assertEqual(Ticket.objects.count(), before + 1)
        inc = AlertIncident.objects.get()
        self.assertEqual(inc.member_count, 50)
        self.assertTrue(inc.ticket.subject.startswith('[Alert] Site outage: HQ'))
        self.assertIsNone(inc.ticket.related_asset)
        self.assertEqual(AlertTicketLink.objects.filter(disposition='outage_member', ticket=inc.ticket).count(), 50)
        # Every computer back: the incident resolves, the ticket gets one note and stays open.
        for i in range(50):
            self.resolve(f'cmoff{i:02d}', kind='OFFLINE', title=f'PC-{i:02d} is offline', endpoint=f'pc{i:02d}')
        inc.refresh_from_db()
        self.assertEqual(inc.status, 'resolved')
        inc.ticket.refresh_from_db()
        self.assertFalse(inc.ticket.status.is_terminal)
        self.assertEqual(TicketComment.objects.filter(ticket=inc.ticket, body__contains='back').count(), 1)

    def test_rmm_reported_site_outage_groups_members(self):
        policy_on()
        self.raise_alert('cmsite', kind='SITE_OUTAGE', title='HQ: 12 computers offline', endpoint='srv01',
                         severity='critical')
        parent = self.link('cmsite')
        self.assertEqual(parent.disposition, 'created')
        self.raise_alert('cmmember', kind='OFFLINE', title='PC-01 is offline', endpoint='srv01', outage='cmsite')
        self.assertEqual(self.link('cmmember').ticket, parent.ticket)
        self.assertEqual(Ticket.objects.filter(source='rmm').count(), 1)

    def test_one_offline_computer_is_held_then_opened(self):
        policy_on(offline_hold_minutes=5)
        self.raise_alert('cmoff', kind='OFFLINE', title='SRV-01 is offline')
        link = self.link('cmoff')
        self.assertEqual((link.disposition, link.ticket), ('held', None))
        alert_policy.tick(now=timezone.now() + timedelta(minutes=1))
        self.assertEqual(self.link('cmoff').disposition, 'held')
        alert_policy.tick(now=timezone.now() + timedelta(minutes=6))
        link = self.link('cmoff')
        self.assertEqual(link.disposition, 'created')
        from psa_ai.models import Rem0teAlertTicket
        self.assertEqual(Rem0teAlertTicket.objects.get(alert_id='cmoff').ticket, link.ticket)

    def test_offline_that_recovers_during_the_hold_opens_nothing(self):
        policy_on(offline_hold_minutes=5)
        self.raise_alert('cmoff', kind='OFFLINE', title='SRV-01 is offline')
        self.resolve('cmoff', kind='OFFLINE', title='SRV-01 is offline')
        alert_policy.tick(now=timezone.now() + timedelta(minutes=10))
        link = self.link('cmoff')
        self.assertEqual((link.disposition, link.state, link.ticket), ('held', 'resolved', None))
        self.assertFalse(Ticket.objects.filter(source='rmm').exists())

    def test_maintenance_suppresses_then_applies_policy_if_still_open(self):
        policy_on()
        now = timezone.now()
        w = AlertMaintenanceWindow.objects.create(organization=self.org, site_name='HQ', starts_at=now - timedelta(minutes=5),
                                                  ends_at=now + timedelta(hours=1), reason='Server patching')
        self.raise_alert('cmalert0001')
        self.raise_alert('cmalert0002', endpoint='srv01', kind='SERVICE_STOPPED', title='SRV-01: service X is Stopped')
        self.assertFalse(Ticket.objects.filter(source='rmm').exists())
        self.assertEqual(self.link('cmalert0001').disposition, 'suppressed')
        self.resolve('cmalert0002', kind='SERVICE_STOPPED', title='SRV-01: service X is Stopped')
        alert_policy.tick(now=now + timedelta(minutes=30))  # window still open
        self.assertFalse(Ticket.objects.filter(source='rmm').exists())
        alert_policy.tick(now=w.ends_at + timedelta(minutes=1))
        self.assertEqual(self.link('cmalert0001').disposition, 'created')   # still open → ticket
        self.assertEqual(self.link('cmalert0002').disposition, 'suppressed')  # recovered → nothing
        self.assertEqual(Ticket.objects.filter(source='rmm').count(), 1)

    def test_maintenance_drop(self):
        policy_on()
        now = timezone.now()
        AlertMaintenanceWindow.objects.create(organization=self.org, starts_at=now - timedelta(minutes=5),
                                              ends_at=now + timedelta(minutes=10), after_window='drop')
        self.raise_alert('cmalert0001')
        alert_policy.tick(now=now + timedelta(minutes=11))
        self.assertEqual(self.link('cmalert0001').disposition, 'ignored')
        self.assertFalse(Ticket.objects.filter(source='rmm').exists())

    def test_after_hours_hold_and_critical_is_never_held(self):
        policy_on()
        AlertPolicyRule.objects.create(name='Hold at night', conditions={}, after_hours='hold')
        with mock.patch.object(alert_policy, 'in_business_hours', return_value=False):
            self.raise_alert('cmalert0001')
            self.raise_alert('cmalertcrit', kind='SERVICE_STOPPED', title='SRV-01: service Y is Stopped',
                             severity='critical')
            alert_policy.tick()
        self.assertEqual(self.link('cmalert0001').disposition, 'held')
        self.assertEqual(self.link('cmalertcrit').disposition, 'created')
        with mock.patch.object(alert_policy, 'in_business_hours', return_value=True):
            alert_policy.tick()
        self.assertEqual(self.link('cmalert0001').disposition, 'created')

    def test_escalation_when_nobody_responds(self):
        policy_on()
        p1 = TicketPriority.objects.get(code='P1')
        AlertPolicyRule.objects.create(name='Escalate', conditions={}, escalate_after_minutes=30,
                                       escalation_priority=p1)
        self.raise_alert('cmalert0001')
        t = self.link('cmalert0001').ticket
        alert_policy.tick(now=timezone.now() + timedelta(minutes=10))
        t.refresh_from_db()
        self.assertIsNone(t.escalated_at)
        alert_policy.tick(now=timezone.now() + timedelta(minutes=31))
        t.refresh_from_db()
        self.assertIsNotNone(t.escalated_at)
        self.assertEqual(t.priority, p1)
        self.assertTrue(TicketComment.objects.filter(ticket=t, body__startswith='Escalated').exists())
        alert_policy.tick(now=timezone.now() + timedelta(minutes=90))  # once only
        self.assertEqual(TicketComment.objects.filter(ticket=t, body__startswith='Escalated').count(), 1)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RecoveryTests(AlertBase):

    def close_rule(self, **kw):
        return AlertPolicyRule.objects.create(name='Close when sole', conditions={}, on_recovery='close_if_sole', **kw)

    def test_recovery_note_by_default_and_ticket_stays_open(self):
        policy_on()
        self.raise_alert('cmalert0001')
        t = self.link('cmalert0001').ticket
        self.resolve('cmalert0001')
        t.refresh_from_db()
        self.assertFalse(t.status.is_terminal)
        note = TicketComment.objects.get(ticket=t, body__startswith='Monitoring reports the alert recovered')
        self.assertTrue(note.is_internal)
        self.assertEqual(self.link('cmalert0001').state, 'resolved')
        self.resolve('cmalert0001')  # a repeated resolve adds nothing
        self.assertEqual(TicketComment.objects.filter(ticket=t, body__startswith='Monitoring reports').count(), 1)

    def test_recovery_resolves_a_ticket_only_this_alert_opened(self):
        policy_on()
        self.close_rule()
        self.raise_alert('cmalert0001')
        t = self.link('cmalert0001').ticket
        self.resolve('cmalert0001')
        t.refresh_from_db()
        self.assertTrue(t.status.is_terminal)
        self.assertEqual(t.closure_category, 'no_action')

    def test_recovery_never_closes_an_unrelated_ticket(self):
        """The alert joined a ticket a person opened: recovery only notes it."""
        policy_on()
        self.close_rule(action='attach')
        from tech_access.testing import make_ticket
        human = make_ticket(self.org, assigned_to=self.tech, subject='Server is slow', related_asset=self.asset)
        other = make_ticket(self.org, subject='Unrelated printer issue')
        self.raise_alert('cmalert0001')
        link = self.link('cmalert0001')
        self.assertEqual((link.disposition, link.ticket), ('attached', human))
        self.resolve('cmalert0001')
        human.refresh_from_db()
        other.refresh_from_db()
        self.assertFalse(human.status.is_terminal)
        self.assertFalse(other.status.is_terminal)
        self.assertTrue(TicketComment.objects.filter(ticket=human, body__contains='Ticket left open').exists())
        self.assertFalse(TicketComment.objects.filter(ticket=other).exists())

    def test_recovery_keeps_a_ticket_someone_worked_on(self):
        policy_on()
        self.close_rule()
        self.raise_alert('cmalert0001')
        t = self.link('cmalert0001').ticket
        TicketComment.objects.create(ticket=t, author=self.tech, body='Looking at it', is_internal=True)
        self.resolve('cmalert0001')
        t.refresh_from_db()
        self.assertFalse(t.status.is_terminal)
        self.assertTrue(TicketComment.objects.filter(ticket=t, body__contains='people have worked on it').exists())

    def test_recovery_keeps_a_ticket_other_alerts_joined(self):
        policy_on()
        self.close_rule()
        self.raise_alert('cmalert0001')
        self.raise_alert('cmalert0002')
        t = self.link('cmalert0001').ticket
        self.resolve('cmalert0001')
        t.refresh_from_db()
        self.assertFalse(t.status.is_terminal)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SyncedAlertTests(TestCase):
    """Alerts synced from another RMM provider (no Rem0te)."""

    def setUp(self):
        _setup_seed()
        _enable_psa_global()
        _ai_off()
        self.org = Organization.objects.create(name='Gamma', slug='gamma')
        self.conn = RMMConnection.objects.create(organization=self.org, provider_type='tactical_rmm', name='TRMM',
                                                 base_url='https://trmm.example.com')
        self.device = RMMDevice.objects.create(organization=self.org, connection=self.conn, external_id='agent-1',
                                               device_name='WS-1', site_name='Main')
        self.unowned = RMMDevice.objects.create(organization=None, connection=self.conn, external_id='agent-2',
                                                device_name='WS-2', ownership_status=RMMDevice.OWNERSHIP_UNRESOLVED)

    def sync(self, ext, device, message='Disk C: 95% used', status='active', severity='warning'):
        from integrations.sync import RMMSync
        sync = RMMSync.__new__(RMMSync)
        sync.connection, sync.stats = self.conn, {'alerts': {'created': 0, 'updated': 0, 'errors': 0}}
        return sync._upsert_alert({'external_id': ext, 'device_id': device.external_id, 'alert_type': 'diskspace',
                                   'message': message, 'severity': severity, 'status': status})

    def test_off_unless_enabled_for_synced_alerts(self):
        policy_on()
        self.sync('a1', self.device)
        self.assertFalse(AlertTicketLink.objects.exists())

    def test_synced_alert_ticket_and_recovery(self):
        policy_on(include_rmm_sync=True)
        self.sync('a1', self.device)
        link = AlertTicketLink.objects.get(external_id='a1')
        self.assertEqual((link.source, link.category, link.disposition), ('rmm', 'disk', 'created'))
        self.sync('a1', self.device)  # re-synced: nothing new
        self.assertEqual(Ticket.objects.filter(source='rmm').count(), 1)
        self.sync('a1', self.device, status='resolved')
        link.refresh_from_db()
        self.assertEqual(link.state, 'resolved')
        self.assertTrue(TicketComment.objects.filter(ticket=link.ticket, body__contains='recovered').exists())

    def test_unowned_device_opens_nothing(self):
        policy_on(include_rmm_sync=True)
        self.sync('a2', self.unowned)
        link = AlertTicketLink.objects.get(external_id='a2')
        self.assertEqual((link.disposition, link.ticket), ('unmatched', None))

    def test_classification(self):
        c = alert_policy.classify
        self.assertEqual(c('', 'diskspace', 'Disk C: 95% used'), 'disk')
        self.assertEqual(c('', 'agent', 'Agent not checking in (overdue)'), 'offline')
        self.assertEqual(c('', 'winupdate', 'Failed to install update KB5031356'), 'windows_update')
        self.assertEqual(c('', 'av', 'Defender detected a threat'), 'security')
        self.assertEqual(c('', 'job', 'Backup job failed'), 'backup')
        self.assertEqual(c('REBOOT_PENDING', 'x'), 'reboot_pending')
        self.assertEqual(c('EVENT_MATCH', 'Application error: Outlook crashed'), 'application')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PagesTests(AlertBase):
    def test_admin_pages_need_manage_permission(self):
        from django.test import Client
        from psa.tests._base import _make_msp_tech
        admin = User.objects.create_superuser('boss', 'b@x.test', 'pw')
        c = Client()
        c.force_login(admin)
        s = c.session
        s['2fa_prompted'] = True
        s.save()
        for name in ('alerts', 'alert_rule_new', 'alert_maintenance'):
            from django.urls import reverse
            r = c.get(reverse(f'ticket_routing:{name}'))
            self.assertEqual(r.status_code, 200, name)
        # Legacy mode: the page says the policy is off and how to set it up.
        self.assertContains(c.get(reverse('ticket_routing:alerts')), 'The alert policy is off')
        r = c.post(reverse('ticket_routing:alerts'), {'mode': 'policy', 'default_action': 'create',
                                                      'offline_hold_minutes': '3', 'site_outage_threshold': '4',
                                                      'site_outage_window_minutes': '10'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(AlertPolicySettings.load().mode, 'policy')
        self.assertNotContains(c.get(reverse('ticket_routing:alerts')), 'The alert policy is off')
        r = c.post(reverse('ticket_routing:alert_rule_new'), {'name': 'Disks', 'categories': ['disk'],
                                                              'action': 'create', 'assign_mode': 'routing',
                                                              'after_hours': 'create', 'on_recovery': 'note',
                                                              'priority': '10', 'is_active': 'on'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(AlertPolicyRule.objects.get().conditions['categories'], ['disk'])
        tech = _make_msp_tech(User.objects.create_user('plain', 'p@x.test', 'pw'))
        c2 = Client()
        c2.force_login(tech)
        s = c2.session
        s['2fa_prompted'] = True
        s.save()
        self.assertEqual(c2.get(reverse('ticket_routing:alerts')).status_code, 403)
