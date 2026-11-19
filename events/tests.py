"""Shared operational event layer (roadmap Phase 82, v3.17.719)."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, Role, RoleTemplate
from core.models import Organization
from psa.tests._base import TEST_MIDDLEWARE, _make_msp_tech, _setup_seed
from security_alerts.models import SecurityAlert, SecurityIncident, SecurityVendorConnection

from . import models as M
from . import projection


class _Base(TestCase):
    def setUp(self):
        self.a = Organization.objects.create(name='Events A', slug='events-a')
        self.b = Organization.objects.create(name='Events B', slug='events-b')
        self.conn = SecurityVendorConnection.objects.create(organization=self.a, name='EDR A',
                                                            provider='defender', category='edr')

    def alert(self, ext='x1', org=None, **kw):
        org = org or self.a
        conn = self.conn if org == self.a else SecurityVendorConnection.objects.create(
            organization=org, name=f'EDR {ext}', provider='defender', category='edr')
        with self.captureOnCommitCallbacks(execute=True):
            return SecurityAlert.objects.create(connection=conn, organization=org, external_id=ext,
                                                severity=kw.pop('severity', 'high'), title=f'alert {ext}',
                                                asset_hint=kw.pop('asset_hint', 'PC-01'), **kw)

    def tick(self):
        return projection.run(budget_seconds=30)

    def event_for(self, alert):
        return M.OperationalEvent.objects.get(source=M.SOURCE_SECURITY, source_id=alert.pk)


class ProjectionTests(_Base):
    def test_save_queues_and_tick_projects(self):
        a = self.alert(raw_payload={'mitre': ['T1059', 'T1003']})
        self.assertTrue(M.ProjectionQueueItem.objects.filter(source=M.SOURCE_SECURITY, source_id=a.pk).exists())
        self.tick()
        self.assertFalse(M.ProjectionQueueItem.objects.exists())
        e = self.event_for(a)
        self.assertEqual((e.organization_id, e.severity, e.status, e.asset_hint), (self.a.pk, 'high', 'open', 'PC-01'))
        self.assertEqual(e.mitre_techniques, ['T1059', 'T1003'])
        self.assertEqual(e.correlation_group, f'{self.a.pk}:pc-01')
        self.assertEqual(M.SourceHealth.objects.get(source=M.SOURCE_SECURITY).state, 'ok')

    def test_client_pin_is_the_customer_and_dismissed_is_suppressed(self):
        a = self.alert(client_org=self.b)
        self.tick()
        self.assertEqual(self.event_for(a).organization_id, self.b.pk)
        with self.captureOnCommitCallbacks(execute=True):
            a.status = 'dismissed'
            a.save()
        self.tick()
        self.assertEqual(self.event_for(a).status, M.STATUS_SUPPRESSED)

    def test_rerun_is_idempotent(self):
        a = self.alert()
        self.tick()
        projection.project(M.SOURCE_SECURITY, a.pk)
        projection.project(M.SOURCE_SECURITY, a.pk)
        self.assertEqual(M.OperationalEvent.objects.filter(source_id=a.pk).count(), 1)

    def test_bulk_update_reaches_event_through_recheck(self):
        a = self.alert()
        self.tick()
        SecurityAlert.objects.filter(pk=a.pk).update(status='resolved', resolved_at=timezone.now())
        self.assertFalse(M.ProjectionQueueItem.objects.exists())  # no signal
        self.tick()
        self.assertEqual(self.event_for(a).status, M.STATUS_RESOLVED)

    def test_bulk_created_rows_found_by_scan(self):
        SecurityAlert.objects.bulk_create([SecurityAlert(connection=self.conn, organization=self.a,
                                                         external_id=f'bulk{i}', title='bulk') for i in range(3)])
        self.tick()
        self.assertEqual(M.OperationalEvent.objects.filter(source=M.SOURCE_SECURITY).count(), 3)
        mark = M.SourceHealth.objects.get(source=M.SOURCE_SECURITY).scan_watermark
        self.assertEqual(mark, SecurityAlert.objects.order_by('-pk').first().pk)

    def test_deleted_source_closes_event(self):
        a = self.alert()
        self.tick()
        pk = a.pk
        a.delete()
        projection.project(M.SOURCE_SECURITY, pk)
        e = M.OperationalEvent.objects.get(source_id=pk)
        self.assertEqual((e.status, e.source_status), (M.STATUS_RESOLVED, 'deleted'))

    def test_raw_payload_is_capped(self):
        a = self.alert(raw_payload={'blob': 'x' * 20000})
        self.tick()
        raw = self.event_for(a).raw
        self.assertTrue(raw['_truncated'])
        self.assertLess(len(raw['head']), M.RAW_MAX_BYTES)

    def test_failures_retry_then_dead_letter(self):
        a = self.alert()
        with mock.patch.object(projection, 'project', side_effect=RuntimeError('boom')):
            for _ in range(projection.MAX_ATTEMPTS):
                self.tick()
        item = M.ProjectionQueueItem.objects.get(source_id=a.pk)
        self.assertTrue(item.dead)
        self.assertIn('boom', item.last_error)
        h = M.SourceHealth.objects.get(source=M.SOURCE_SECURITY)
        self.assertEqual(h.state, 'failing')
        self.assertEqual(projection.retry_dead_letters(), 1)
        self.tick()
        self.assertFalse(M.ProjectionQueueItem.objects.exists())
        self.assertEqual(M.SourceHealth.objects.get(source=M.SOURCE_SECURITY).state, 'ok')

    def test_switched_off_does_nothing(self):
        s = M.EventSettings.get()
        s.ingestion_enabled = False
        s.save()
        self.alert()
        self.assertTrue(self.tick().get('disabled'))
        self.assertFalse(M.OperationalEvent.objects.exists())

    def test_queue_cap_drops_but_scan_recovers(self):
        with mock.patch('events.queue.QUEUE_CAP', 0):
            a = self.alert()
        self.assertFalse(M.ProjectionQueueItem.objects.exists())
        self.tick()
        self.assertTrue(M.OperationalEvent.objects.filter(source_id=a.pk).exists())

    def test_tick_command_runs(self):
        self.alert()
        call_command('events_tick', verbosity=0)
        self.assertEqual(M.OperationalEvent.objects.count(), 1)


class LinkTests(_Base):
    def test_ticket_and_incident_links_follow_the_source(self):
        _setup_seed()
        from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
        t = Ticket.objects.create(organization=self.a, subject='s', description='x', queue=Queue.objects.first(),
                                  priority=TicketPriority.objects.first(), ticket_type=TicketType.objects.first(),
                                  status=TicketStatus.objects.filter(is_terminal=False).first())
        a = self.alert(auto_ticket=t)
        inc = SecurityIncident.objects.create(organization=self.a, title='inc')
        with self.captureOnCommitCallbacks(execute=True):
            inc.alerts.add(a)
        self.tick()
        e = self.event_for(a)
        self.assertEqual({(l.ticket_id, l.incident_id) for l in e.links.all()}, {(t.pk, None), (None, inc.pk)})
        manual = M.EventLink.objects.create(event=e, incident=SecurityIncident.objects.create(
            organization=self.a, title='other'), origin=M.EventLink.ORIGIN_MANUAL)
        with self.captureOnCommitCallbacks(execute=True):
            inc.alerts.remove(a)
        self.tick()
        self.assertEqual(set(e.links.values_list('pk', flat=True)) - {manual.pk},
                         set(e.links.filter(ticket=t).values_list('pk', flat=True)))
        self.assertTrue(M.EventLink.objects.filter(pk=manual.pk).exists())  # a person's link stays


class MonitorTests(_Base):
    def setUp(self):
        super().setUp()
        from monitoring.models import WebsiteMonitor
        self.m = WebsiteMonitor.objects.create(organization=self.a, name='Shop', url='https://shop.example.test')

    def set_state(self, state):
        with self.captureOnCommitCallbacks(execute=True):
            self.m.alert_state = state
            self.m.consecutive_failures = 3 if state == 'down' else 0
            self.m.save(update_fields=['alert_state', 'consecutive_failures'])
        self.tick()

    def test_each_outage_is_one_event(self):
        self.set_state('down')
        live = M.OperationalEvent.objects.get(source=M.SOURCE_MONITOR)
        self.assertEqual((live.status, live.severity, live.title), ('open', 'high', 'Shop is down'))
        self.tick()
        self.assertEqual(M.OperationalEvent.objects.filter(source=M.SOURCE_MONITOR).count(), 1)
        self.set_state('up')
        live.refresh_from_db()
        self.assertEqual(live.status, M.STATUS_RESOLVED)
        M.OperationalEvent.objects.filter(pk=live.pk).update(first_seen_at=timezone.now() - timedelta(hours=1),
                                                             dedup_key=f'monitor:{self.m.pk}:1')
        self.set_state('down')
        self.assertEqual(M.OperationalEvent.objects.filter(source=M.SOURCE_MONITOR).count(), 2)

    def test_down_without_signal_found_by_scan(self):
        type(self.m).objects.filter(pk=self.m.pk).update(alert_state='down')
        self.tick()
        self.assertTrue(M.OperationalEvent.objects.filter(source=M.SOURCE_MONITOR, status='open').exists())

    def test_ordinary_check_saves_are_not_queued(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.m.save(update_fields=['last_checked_at'])
        self.assertFalse(M.ProjectionQueueItem.objects.exists())


class RetentionTests(_Base):
    def test_closed_events_pruned_live_kept_and_quota(self):
        old = timezone.now() - timedelta(days=400)
        mk = lambda i, status: M.OperationalEvent.objects.create(  # noqa: E731
            source=M.SOURCE_SECURITY, source_id=i, dedup_key=f'k{i}', title='t', status=status,
            last_seen_at=old, raw={'a': 1})
        live, closed = mk(1, 'open'), mk(2, 'resolved')
        projection.prune()
        self.assertTrue(M.OperationalEvent.objects.filter(pk=live.pk).exists())
        self.assertFalse(M.OperationalEvent.objects.filter(pk=closed.pk).exists())
        live.refresh_from_db()
        self.assertEqual(live.raw, {})
        s = M.EventSettings.get()
        s.retention_days, s.max_events = 0, 1
        s.save()
        recent = [M.OperationalEvent.objects.create(source=M.SOURCE_SECURITY, source_id=10 + i,
                                                    dedup_key=f'r{i}', title='t', status='resolved')
                  for i in range(2)]
        projection.prune(s)
        self.assertTrue(M.OperationalEvent.objects.filter(pk=live.pk).exists())  # quota never takes live events
        self.assertEqual(M.OperationalEvent.objects.filter(pk__in=[r.pk for r in recent]).count(), 0)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ViewTests(_Base):
    def setUp(self):
        super().setUp()
        self.ea = self._event(self.a, 'a')
        self.eb = self._event(self.b, 'b')
        self.ew = self._event(None, 'msp')
        self.admin = User.objects.create_superuser('events-admin', 'a@example.test', 'pw')
        viewer = RoleTemplate.objects.create(name='events scoped', security_alerts_view=True,
                                             security_alerts_acknowledge=True, events_view=True, events_link=True)
        # A technician whose client scope is customer A only.
        self.tech = _make_msp_tech(User.objects.create_user('events-tech', password='pw'))
        self.tech.profile.global_role_template = viewer
        self.tech.profile.client_scope = 'selected'
        self.tech.profile.save()
        self.tech.profile.scope_organizations.add(self.a)
        Membership.objects.create(user=self.tech, organization=self.a, role=Role.EDITOR)

    def _event(self, org, key):
        return M.OperationalEvent.objects.create(organization=org, source=M.SOURCE_RMM, source_id=1,
                                                 dedup_key=f'rmm:{key}', title=f'event {key}')

    def client_for(self, user):
        c = Client()
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.a.pk
        s.save()
        return c

    def test_superuser_sees_every_customer_and_msp_wide(self):
        r = self.client_for(self.admin).get('/security/events/')
        self.assertEqual(r.status_code, 200)
        for t in ('event a', 'event b', 'event msp'):
            self.assertContains(r, t)

    def test_scoped_tech_sees_only_their_customer(self):
        from accounts.permission_utils import orgs_with_perm
        self.assertEqual(orgs_with_perm(self.tech, 'events_view'), {self.a.pk})
        c = self.client_for(self.tech)
        r = c.get('/security/events/')
        self.assertContains(r, 'event a')
        self.assertNotContains(r, 'event b')
        self.assertNotContains(r, 'event msp')
        self.assertEqual(c.get(f'/security/events/{self.eb.pk}/').status_code, 404)
        self.assertEqual(c.get(f'/security/events/{self.ew.pk}/').status_code, 404)

    def test_manual_link_refuses_other_customers_ticket(self):
        _setup_seed()
        from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
        mk = lambda org: Ticket.objects.create(  # noqa: E731
            organization=org, subject='s', description='x', queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(), ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(is_terminal=False).first())
        ta, tb = mk(self.a), mk(self.b)
        c = self.client_for(self.admin)
        c.post(f'/security/events/{self.ea.pk}/link/', {'ticket': tb.ticket_number})
        self.assertFalse(self.ea.links.exists())
        c.post(f'/security/events/{self.ea.pk}/link/', {'ticket': ta.ticket_number})
        link = self.ea.links.get()
        self.assertEqual((link.ticket_id, link.origin, link.created_by_id), (ta.pk, 'manual', self.admin.pk))
        r = c.get(f'/security/events/{self.ea.pk}/')
        self.assertContains(r, ta.ticket_number)
        c.post(f'/security/events/{self.ea.pk}/unlink/{link.pk}/')
        self.assertFalse(self.ea.links.exists())

    def test_ingestion_health_and_settings(self):
        c = self.client_for(self.admin)
        self.assertEqual(c.get('/security/events/ingestion/').status_code, 200)
        c.post('/security/events/ingestion/', {'action': 'settings', 'retention_days': '90',
                                               'raw_retention_days': '14', 'max_events': '1000'})
        s = M.EventSettings.get()
        self.assertEqual((s.ingestion_enabled, s.retention_days, s.max_events), (False, 90, 1000))
        c.post('/security/events/ingestion/', {'action': 'settings', 'ingestion_enabled': '1',
                                               'retention_days': '3', 'raw_retention_days': '14', 'max_events': '0'})
        self.assertEqual(M.EventSettings.get().retention_days, 90)  # below the 7-day floor: refused

    def test_settings_need_admin(self):
        r = self.client_for(self.tech).post('/security/events/ingestion/', {'action': 'retry'})
        self.assertIn(r.status_code, (403, 302))
        if r.status_code == 302:
            self.assertNotIn('/security/events/ingestion/', r.url)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PermissionTests(TestCase):
    """82.6: events_view / events_link / events_manage_ingestion (accounts 0064)."""

    def _tech(self, name, **flags):
        role = RoleTemplate.objects.create(name=f'role {name}', **flags)
        user = _make_msp_tech(User.objects.create_user(name, password='pw'))
        user.profile.global_role_template = role
        user.profile.save()
        c = Client()
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        s.save()
        return c

    def test_security_alert_view_alone_no_longer_opens_events(self):
        c = self._tech('ev-sec-only', security_alerts_view=True, events_view=False)
        self.assertEqual(c.get('/security/events/').status_code, 403)
        c = self._tech('ev-view', security_alerts_view=False, events_view=True)
        self.assertEqual(c.get('/security/events/').status_code, 200)

    def test_ingestion_settings_need_manage_ingestion(self):
        c = self._tech('ev-viewer', events_view=True, security_alerts_manage_connections=True)
        self.assertEqual(c.post('/security/events/ingestion/', {'action': 'retry'}).status_code, 403)
        c = self._tech('ev-admin', events_view=True, events_manage_ingestion=True)
        r = c.post('/security/events/ingestion/', {'action': 'settings', 'ingestion_enabled': '1',
                                                   'retention_days': '90', 'raw_retention_days': '30',
                                                   'max_events': '0', 'retention_backup': '14',
                                                   'retention_monitor': ''})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(M.EventSettings.get().source_retention_days, {'backup': 14})

    def test_registry_and_seeds(self):
        from accounts import permission_registry as R
        from accounts.role_seeds import definitions
        for key in ('events_view', 'events_link', 'events_manage_ingestion'):
            self.assertIn(key, R.STAFF_ONLY_KEYS)
            self.assertFalse(RoleTemplate._meta.get_field(key).default)
        defs = {d.key: d.flags for d in definitions()}
        for key, flags in defs.items():
            self.assertEqual(bool(flags.get('events_view')), bool(flags.get('security_alerts_view')), key)
            self.assertEqual(bool(flags.get('events_link')), bool(flags.get('security_alerts_acknowledge')), key)
        self.assertTrue(defs['security_admin']['events_manage_ingestion'])
        self.assertFalse(defs['security_analyst'].get('events_manage_ingestion'))
        self.assertFalse(defs['security_analyst'].get('vault_view_password'))
        # Seeded by the migration in the test database.
        analyst = RoleTemplate.objects.get(seed_key='security_analyst')
        self.assertTrue(analyst.events_view and analyst.events_link and not analyst.events_manage_ingestion)
        self.assertTrue(RoleTemplate.objects.get(seed_key='tech_l1').events_view)

    def test_migration_grant_keeps_existing_access(self):
        import importlib
        from django.apps import apps as live_apps
        mig = importlib.import_module('accounts.migrations.0064_roletemplate_events_permissions')
        custom = RoleTemplate.objects.create(name='custom sec', security_alerts_view=True,
                                             security_alerts_acknowledge=True)
        plain = RoleTemplate.objects.create(name='custom plain', security_alerts_view=False)
        mig.grant(live_apps, None)
        custom.refresh_from_db()
        plain.refresh_from_db()
        self.assertTrue(custom.events_view and custom.events_link)
        self.assertFalse(custom.events_manage_ingestion)
        self.assertFalse(plain.events_view)

    def test_simple_roles_follow_security_flags(self):
        from types import SimpleNamespace
        from accounts.models import derive_legacy_flags
        ns = derive_legacy_flags(SimpleNamespace(security_alerts_view=True, security_alerts_acknowledge=False,
                                                 security_alerts_manage_connections=False), Role.EDITOR)
        self.assertEqual((ns.events_view, ns.events_link, ns.events_manage_ingestion), (True, False, False))


class RetentionOverrideTests(_Base):
    def _ev(self, i, org, source, days_old):
        return M.OperationalEvent.objects.create(
            organization=org, source=source, source_id=i, dedup_key=f'ro{i}', title='t', status='resolved',
            last_seen_at=timezone.now() - timedelta(days=days_old))

    def test_customer_then_source_then_default(self):
        s = M.EventSettings.get()
        s.retention_days, s.raw_retention_days, s.max_events = 100, 0, 0
        s.source_retention_days = {M.SOURCE_BACKUP: 10}
        s.save()
        M.CustomerRetention.objects.create(organization=self.b, retention_days=0)  # keep forever
        backup_old = self._ev(1, self.a, M.SOURCE_BACKUP, 20)      # source rule: 10 days -> gone
        rmm_mid = self._ev(2, self.a, M.SOURCE_RMM, 50)            # default 100 -> kept
        rmm_old = self._ev(3, self.a, M.SOURCE_RMM, 150)           # default -> gone
        b_old = self._ev(4, self.b, M.SOURCE_BACKUP, 500)          # customer keeps
        projection.prune(s)
        left = set(M.OperationalEvent.objects.values_list('pk', flat=True))
        self.assertEqual(left, {rmm_mid.pk, b_old.pk})
        self.assertNotIn(backup_old.pk, left)
        self.assertNotIn(rmm_old.pk, left)
