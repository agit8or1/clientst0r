"""Support workflow tests, including the two worked examples.

Rem0te is the in-process fake from integrations/rem0te/testing.py, plus the
read-only GET /alerts/{id} the contract defines. AI is off throughout.
"""
import time
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from integrations.rem0te import testing as rt
from psa.models import TicketComment
from psa.routing.models import AlertPolicyRule
from psa.routing.tests_alerts import AlertBase, policy_on
from psa.tests._base import TEST_MIDDLEWARE
from tech_access.testing import grant, make_tech

from . import engine
from .models import SupportWorkflowDefinition, WorkflowRun


class FakeRem0teWithAlerts(rt.FakeRem0te):
    """Adds GET /alerts/{id}: the latest state of an alert this fake sent."""

    def _route(self, method, route, body, q, claims):
        if method == 'GET' and route.startswith('/alerts/') and route.count('/') == 2 and route != '/alerts/events':
            alert_id = route.split('/')[2]
            mine = [e['alert_event'] for e in self.alert_events
                    if e['alert_event']['alert']['alert_id'] == alert_id
                    and e['alert_event']['organization_id'] == q.get('organization_id')]
            if not mine:
                return self._err(404, 'NOT_FOUND', 'no such alert')
            return self._respond(200, max(mine, key=lambda e: e['sequence'])['alert'])
        r = super()._route(method, route, body, q, claims)
        if method == 'POST' and route == '/action-proposals' and r.status_code == 201:
            # A real approval window lasts a while; the base fake ends it at once.
            p = self.proposals[body['idempotency_key']]
            p['window']['not_after'] = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime(time.time() + 3600))
            return self._respond(201, p)
        return r


class WorkflowBase(AlertBase):
    def setUp(self):
        super().setUp()
        # Swap in the fake that also answers GET /alerts/{id}.
        self.fake.__class__ = FakeRem0teWithAlerts
        # A front-desk workstation: read-only diagnostics cover standard workstations.
        type(self.asset).objects.filter(pk=self.asset.pk).update(asset_type='desktop')
        self.asset.refresh_from_db()
        grant(self.tech, self.org, 'l2')
        policy_on()
        AlertPolicyRule.objects.create(name='Alpha to Lee', organization=self.org, conditions={},
                                       assign_mode='technician', assign_user=self.tech)

    def notes(self, ticket):
        return list(TicketComment.objects.filter(ticket=ticket).order_by('created_at', 'pk')
                    .values_list('body', flat=True))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WorkedExampleTests(WorkflowBase):

    def test_disk_space_alert_end_to_end(self):
        """Rem0te disk alert → org + device matched → ticket per policy →
        disk use + freshness shown → cleanup suggested → routed to the
        assigned tech → read-only diagnostics → (no Rem0te cleanup action,
        so manual cleanup) → recovery confirmed by the next alert state →
        ticket history updated."""
        self.raise_alert('cmdisk01', title='SRV-01: C: 4% free (3.2 GB)')
        link = self.link('cmdisk01')
        # Customer and computer matched; the ticket created per policy and routed.
        self.assertEqual((link.organization, link.device, link.category), (self.org, self.device, 'disk'))
        t = link.ticket
        self.assertEqual((t.organization, t.related_asset, t.assigned_to), (self.org, self.asset, self.tech))
        # A repeat delivery finds the same ticket.
        self.raise_alert('cmdisk01', title='SRV-01: C: 3% free (2.9 GB)')
        self.assertEqual(self.link('cmdisk01').ticket, t)

        options = {d['slug']: (ok, l) for d, l, ok, _why in engine.for_ticket(t)}
        self.assertEqual(options['disk-nearly-full'], (True, link))
        run = engine.start(self.tech, t, 'disk-nearly-full')
        ev = {i['key']: i for i in run.evidence}
        self.assertEqual(ev['disk']['value'], {'disk_free_pct': 3.0, 'disk_free_gb': 2.9})
        self.assertTrue(ev['disk']['fresh'])
        self.assertIsNotNone(ev['disk']['age_minutes'])
        # Read-only diagnostic: Rem0te's current state of the alert.
        self.assertEqual(ev['alert_now']['value'].get('state'), 'open', ev['alert_now'])
        self.assertTrue(any(c['text'].startswith('Very little free space') for c in run.causes))
        self.assertTrue(any('Recycle Bin' in c['text'] for c in run.causes))
        self.assertEqual(run.remediations, [])  # Rem0te advertises no disk cleanup
        self.assertIn('Disk Cleanup', run.definition['manual_steps'][0])
        self.assertTrue(any(b.startswith('Support workflow "Disk nearly full" started') for b in self.notes(t)))

        engine.manual_done(self.tech, run, 'Cleared 14 GB of temp files.')
        run.refresh_from_db()
        self.assertEqual(run.status, 'verifying')
        # The next alert state from monitoring confirms it.
        self.resolve('cmdisk01', title='SRV-01: C: 31% free (24.0 GB)')
        run.refresh_from_db()
        self.assertEqual(run.status, 'verified')
        t.refresh_from_db()
        self.assertEqual(t.custom_fields['support_workflows']['disk-nearly-full']['status'], 'verified')
        history = self.notes(t)
        self.assertTrue(any(b.startswith('Monitoring reports the alert recovered') for b in history))
        tech_note = TicketComment.objects.get(ticket=t, body__startswith='Technician note')
        self.assertEqual((tech_note.author, tech_note.is_internal), (self.tech, True))
        self.assertIn('did the manual steps', tech_note.body)
        self.assertFalse(t.status.is_terminal)  # the policy rule only notes recovery

    def test_service_stopped_with_approval_job_and_recovery(self):
        """The same path where Rem0te advertises the fix: approval requested
        → job result recorded → recovery confirmed."""
        self.raise_alert('cmsvc01', kind='SERVICE_STOPPED', title='SRV-01: service Spooler is Stopped')
        t = self.link('cmsvc01').ticket
        run = engine.start(self.tech, t, 'service-stopped')
        rem = {r['action']: r for r in run.remediations}
        self.assertTrue(rem['windows.service.start@1']['offered'], rem)
        self.assertIn('Starts the Print Spooler once', rem['windows.service.start@1']['impact'])

        engine.propose(self.tech, run, 'windows.service.start@1', 'wf-spooler-1')
        run.refresh_from_db()
        self.assertEqual(run.status, 'awaiting_approval')
        self.assertTrue(run.rmm_request.approval_url.startswith('https://approve.example.com/'))
        sent = run.rmm_request.payload['rem0te_proposal']
        self.assertEqual(sent['params'], {'service': 'Spooler'})
        with self.assertRaises(engine.WorkflowRefused):  # one action at a time
            engine.propose(self.tech, run, 'windows.service.start@1', 'wf-spooler-2')

        p = next(iter(self.fake.proposals.values()))
        p.update(status='succeeded', outcome='succeeded', observed={'before': 'stopped', 'after10s': 'running'})
        engine.refresh(run, force=True)
        run.refresh_from_db()
        self.assertEqual(run.status, 'verifying')  # Rem0te's "succeeded" is recorded, not taken as the fix
        self.assertTrue(any('after10s=running' in b for b in self.notes(t)))

        self.resolve('cmsvc01', kind='SERVICE_STOPPED', title='SRV-01: service Spooler is Stopped')
        run.refresh_from_db()
        self.assertEqual(run.status, 'verified')
        note = TicketComment.objects.get(ticket=t, body__startswith='Technician note')
        self.assertIn('requested windows.service.start@1 through Rem0te (succeeded)', note.body)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class OutcomeTests(WorkflowBase):

    def started(self):
        self.raise_alert('cmsvc01', kind='SERVICE_STOPPED', title='SRV-01: service Spooler is Stopped')
        t = self.link('cmsvc01').ticket
        run = engine.start(self.tech, t, 'service-stopped')
        engine.propose(self.tech, run, 'windows.service.start@1', 'wf-spooler-1')
        run.refresh_from_db()
        return t, run, next(iter(self.fake.proposals.values()))

    def test_expired_approval(self):
        t, run, p = self.started()
        p.update(status='expired', status_reason='No approver within the window')
        engine.refresh(run, force=True)
        run.refresh_from_db()
        self.assertEqual(run.status, 'approval_expired')
        self.assertIsNotNone(run.finished_at)
        t.refresh_from_db()
        self.assertFalse(t.status.is_terminal)
        self.assertTrue(any('the ticket stays open' in b for b in self.notes(t)))
        # A fresh request may be made after expiry.
        engine.propose(self.tech, run, 'windows.service.start@1', 'wf-spooler-2')
        run.refresh_from_db()
        self.assertEqual(run.status, 'awaiting_approval')

    def test_approval_window_passing_locally_counts_as_expired(self):
        t, run, p = self.started()
        type(run.rmm_request).objects.filter(pk=run.rmm_request_id).update(
            approval_expires_at=timezone.now() - timedelta(minutes=1))
        engine.refresh(run, fetch=False)
        run.refresh_from_db()
        self.assertEqual(run.status, 'approval_expired')

    def test_failed_job(self):
        t, run, p = self.started()
        p.update(status='failed', outcome='failed', status_reason='Service did not start',
                 observed={'before': 'stopped', 'after10s': 'stopped'})
        engine.refresh(run, force=True)
        run.refresh_from_db()
        self.assertEqual(run.status, 'failed')
        self.assertTrue(any('Nothing was changed by ClientSt0r' in b for b in self.notes(t)))
        # Recovery later does not mark the failed run verified.
        self.resolve('cmsvc01', kind='SERVICE_STOPPED', title='SRV-01: service Spooler is Stopped')
        run.refresh_from_db()
        self.assertEqual(run.status, 'failed')
        self.assertFalse(TicketComment.objects.filter(ticket=t, body__startswith='Technician note').exists())

    def test_succeeded_but_alert_never_recovers(self):
        t, run, p = self.started()
        p.update(status='succeeded', outcome='succeeded', observed={'after10s': 'running'})
        engine.refresh(run, force=True)
        run.refresh_from_db()
        engine.refresh(run, now=timezone.now() + timedelta(minutes=31))
        run.refresh_from_db()
        self.assertEqual(run.status, 'not_verified')
        self.assertTrue(any('not confirmed' in b for b in self.notes(t)))

    def test_rem0te_not_advertising_the_action_means_not_offered(self):
        from integrations.rem0te import pairing
        self.fake.caps = rt.capabilities(features={'ticket_analysis': True, 'model_comparison': True,
                                                   'endpoint_evidence': [], 'actions': [], 'alerts': True})
        pairing.check(self.conn)
        self.raise_alert('cmsvc01', kind='SERVICE_STOPPED', title='SRV-01: service Spooler is Stopped')
        run = engine.start(self.tech, self.link('cmsvc01').ticket, 'service-stopped')
        self.assertFalse(run.remediations[0]['offered'])
        self.assertIn('does not advertise', run.remediations[0]['why_not'])
        with self.assertRaises(engine.WorkflowRefused):
            engine.propose(self.tech, run, 'windows.service.start@1', 'k1')
        self.assertEqual(self.fake.proposals, {})

    def test_other_service_gets_no_spooler_action(self):
        self.raise_alert('cmsvc02', kind='SERVICE_STOPPED', title='SRV-01: service W32Time is Stopped')
        run = engine.start(self.tech, self.link('cmsvc02').ticket, 'service-stopped')
        self.assertFalse(run.remediations[0]['offered'])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AccessAndDefinitionTests(WorkflowBase):

    def test_l1_can_gather_but_not_propose(self):
        self.raise_alert('cmsvc01', kind='SERVICE_STOPPED', title='SRV-01: service Spooler is Stopped')
        t = self.link('cmsvc01').ticket
        l1 = make_tech('helpdesk')
        grant(l1, self.org, 'l1')
        run = engine.start(l1, t, 'service-stopped')
        self.assertFalse(run.remediations[0]['offered'])
        with self.assertRaises(engine.WorkflowRefused):
            engine.propose(l1, run, 'windows.service.start@1', 'k1')
        self.assertEqual(self.fake.proposals, {})

    def test_servers_need_advanced_diagnostics_for_the_live_read(self):
        type(self.asset).objects.filter(pk=self.asset.pk).update(asset_type='server')
        self.raise_alert('cmdisk01')
        run = engine.start(self.tech, self.link('cmdisk01').ticket, 'disk-nearly-full')
        ev = {i['key']: i for i in run.evidence}
        self.assertIn('Not read', ev['alert_now']['value']['note'])
        self.assertFalse(any(c[1] == '/alerts/cmdisk01' for c in self.fake.calls))
        self.assertIn('disk', ev)  # what ClientSt0r already holds is still shown

    def test_customer_user_gets_404(self):
        self.raise_alert('cmdisk01')
        t = self.link('cmdisk01').ticket
        cust = User.objects.create_user('cust', 'c@alpha.test', 'pw')
        from accounts.models import Membership
        Membership.objects.create(user=cust, organization=self.org, role='owner')
        self.assertFalse(engine.can_view(cust, t))
        c = Client()
        c.force_login(cust)
        s = c.session
        s['2fa_prompted'] = True
        s.save()
        self.assertEqual(c.get(reverse('support_workflows:ticket', args=[t.ticket_number])).status_code, 404)
        with self.assertRaises(engine.WorkflowRefused):
            engine.start(cust, t, 'disk-nearly-full')

    def test_validate_definition(self):
        good = dict(engine.builtin('service-stopped'))
        self.assertEqual(engine.validate_definition(good), [])
        bad = dict(good, remediations=[{'action': 'windows.disk.cleanup@1', 'impact': 'x'}])
        self.assertTrue(engine.validate_definition(bad))
        bad = dict(good, remediations=[{'action': 'windows.service.start@1', 'command': 'net start spooler'}])
        self.assertTrue(engine.validate_definition(bad))
        bad = dict(good, causes=[{'text': 'x', 'when': {'fact': 'shell', 'op': 'eq', 'value': 1}}])
        self.assertTrue(engine.validate_definition(bad))

    def test_admin_customisation_overrides_builtin(self):
        d = dict(engine.builtin('disk-nearly-full'), name='Disk full (Alpha style)', freshness_minutes=5)
        SupportWorkflowDefinition.objects.create(slug='disk-nearly-full', name=d['name'], definition=d)
        self.assertEqual(engine.definition('disk-nearly-full')['name'], 'Disk full (Alpha style)')
        SupportWorkflowDefinition.objects.filter(slug='disk-nearly-full').update(is_active=False)
        self.assertIsNone(engine.definition('disk-nearly-full'))

    def test_backup_workflow_needs_a_backup_integration(self):
        self.raise_alert('cmdisk01')
        t = self.link('cmdisk01').ticket
        avail = {d['slug']: ok for d, _l, ok, _w in engine.for_ticket(t)}
        self.assertFalse(avail['backup-failure'])
        with self.assertRaises(engine.WorkflowRefused):
            engine.start(self.tech, t, 'backup-failure')

    def test_twelve_builtins_are_valid(self):
        self.assertEqual(len(engine.definitions()), 12)
        for d in engine.definitions():
            self.assertEqual(engine.validate_definition(d), [], d['slug'])

    def test_pages(self):
        self.raise_alert('cmdisk01')
        t = self.link('cmdisk01').ticket
        admin = make_tech('boss', superuser=True)
        c = Client()
        c.force_login(admin)
        s = c.session
        s['2fa_prompted'] = True
        s.save()
        url = reverse('support_workflows:ticket', args=[t.ticket_number])
        self.assertContains(c.get(url), 'Disk nearly full')
        r = c.post(url, {'workflow': 'disk-nearly-full'})
        self.assertEqual(r.status_code, 302)
        run = WorkflowRun.objects.get()
        r = c.get(reverse('support_workflows:run', args=[run.pk]))
        self.assertContains(r, 'Disk Cleanup')
        r = c.post(reverse('support_workflows:run', args=[run.pk]), {'op': 'manual', 'note': 'done'})
        self.assertEqual(r.status_code, 302)
        run.refresh_from_db()
        self.assertEqual(run.status, 'verifying')
        self.assertEqual(c.get(reverse('support_workflows:admin')).status_code, 200)
        self.assertEqual(c.get(reverse('support_workflows:admin_edit', args=['disk-nearly-full'])).status_code, 200)
        self.assertContains(c.get(reverse('psa:ticket_detail', args=[t.ticket_number])), 'Monitoring alerts')
