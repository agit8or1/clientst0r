"""
Revision 2 (Rem0te 0.30) on the ticket side: patch summaries on alert
tickets, events that cannot be applied are recorded and skipped (the cursor
never loops), replayed and duplicate deliveries, foreign events, containment
pauses on jobs and proposals (not "rejected"), expired approvals while
Rem0te is unreachable, and computers matched by Rem0te's id, never by name.
"""
from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone

from integrations.models import RMMDevice
from integrations.rem0te import actions, alerts, health, pairing, reconcile, testing as rt

from .models import AnalysisJob, Rem0teAlertEvent, Rem0teAlertTicket, RMMRequest
from .services import rmm_actions
from .tests_assist import sign_in  # noqa: F401  (Rem0teBase signs in through it)
from .tests_rem0te import EVENTS, Rem0teBase

EP_A = 'cmendpointa0000000000000001'


class Rev2Base(Rem0teBase):
    def setUp(self):
        super().setUp()
        from assets.models import Asset
        self.asset_a = Asset.objects.create(organization=self.a, name='Front desk', hostname='FRONTDESK-01',
                                            asset_type='desktop')
        self.device = RMMDevice.objects.create(organization=self.a, connection=self.conn_a, external_id=EP_A,
                                               device_name='FRONTDESK-01', device_type='workstation',
                                               linked_asset=self.asset_a, data_refreshed_at=timezone.now())
        self.revision(2)

    def revision(self, rev, paused_a=(), **over):
        orgs = [rt.organization(pairing.organization_id(self.conn_a), 'cmbizalpha000000000000001', 'Alpha Dental',
                                paused_a),
                rt.organization(pairing.organization_id(self.conn_b), 'cmbizbeta0000000000000001', 'Beta Law')]
        self.fake.caps = rt.capabilities(version='0.30.1', revision=rev, organizations=orgs,
                                         model_profiles=[pairing.profile_slug(self.cheap),
                                                         pairing.profile_slug(self.big)], **over)
        for conn in (self.conn_a, self.conn_b):
            doc = pairing.check(conn)
            self.assertTrue(doc['compatible'], doc)
            conn.refresh_from_db()

    def org(self, conn):
        return pairing.organization_id(conn)

    def state(self, conn):
        conn.refresh_from_db()
        return health.evaluate(conn)['state']


class PatchSummaryTests(Rev2Base):
    def test_reboot_pending_alert_carries_the_patch_summary(self):
        ps = rt.patch_summary(failed_kbs=['KB5043080'])
        ev = self.fake.alert_event(self.org(self.conn_a), 1, kind='REBOOT_PENDING', patch=ps, endpoint=EP_A)
        r = rt.signed_post(self.rc, EVENTS, ev)
        self.assertEqual(r.status_code, 200, r.content)
        row = Rem0teAlertTicket.objects.get()
        self.assertEqual(row.patch_summary, ps)
        desc = row.ticket.description
        for text in ('Patch status (from Rem0te)', 'KB5044284', 'Failed: KB5043080', 'Restart pending: yes',
                     'signed agent scan'):
            self.assertIn(text, desc)
        self.assertEqual(row.ticket.related_asset, self.asset_a)
        # An update refreshes the stored summary.
        upd = self.fake.alert_event(self.org(self.conn_a), 2, etype='alert.updated', kind='REBOOT_PENDING',
                                    patch=rt.patch_summary(pending_count=0, pending_kbs=[],
                                                           confirmed_kbs=['KB5044284']), endpoint=EP_A)
        rt.signed_post(self.rc, EVENTS, upd)
        row.refresh_from_db()
        self.assertEqual(row.patch_summary['confirmed_kbs'], ['KB5044284'])
        self.assertEqual(self.state(self.conn_a), health.CONNECTED)

    def test_other_alerts_carry_null(self):
        ev = self.fake.alert_event(self.org(self.conn_a), 1, patch=None, endpoint=EP_A)
        self.assertEqual(rt.signed_post(self.rc, EVENTS, ev).status_code, 200)
        self.assertEqual(Rem0teAlertTicket.objects.get().patch_summary, {})

    def test_revision_2_event_understood_before_any_revision_2_check(self):
        self.revision(None)  # last check: a revision-1 Rem0te (e.g. upgraded since)
        self.assertEqual(pairing.last_check(self.conn_a)['contract_revision'], 1)
        ev = self.fake.alert_event(self.org(self.conn_a), 1, kind='REBOOT_PENDING', patch=rt.patch_summary(),
                                   endpoint=EP_A)
        self.assertEqual(rt.signed_post(self.rc, EVENTS, ev).json()['status'], 'ticket opened')


class SkippedEventTests(Rev2Base):
    def bad_event(self, seq, **alert_over):
        ev = self.fake.alert_event(self.org(self.conn_a), seq, alert_id=f'cmalertbad000000000000{seq:04d}', patch=None,
                                   endpoint=EP_A)
        ev['alert_event']['alert'].update(alert_over)
        ev['signature'] = rt.sign_event(ev['alert_event'], alert=True)
        self.fake.alert_events[-1] = ev
        return ev

    def test_not_understood_event_is_recorded_skipped_and_reprocessed(self):
        bad = self.bad_event(1, future_field={'x': 1})
        r = rt.signed_post(self.rc, EVENTS, bad)
        self.assertEqual((r.status_code, r.json()['status']), (200, 'skipped'))
        # A re-delivery (Rem0te retries until it sees a 2xx) is a duplicate.
        self.assertEqual(rt.signed_post(self.rc, EVENTS, bad).json()['status'], 'duplicate')
        rec = Rem0teAlertEvent.objects.get()
        self.assertFalse(rec.applied)
        self.assertIn('future_field', rec.problem)
        self.assertFalse(Rem0teAlertTicket.objects.exists())
        self.assertEqual(alerts.cursor(self.conn_a), 1)  # the cursor moved past it
        st = health.evaluate(self.conn_a)
        self.assertEqual(st['state'], health.DEGRADED)
        self.assertTrue(any(x['code'] == 'EVENT_NOT_UNDERSTOOD' for x in st['reasons']))
        self.conn_a.refresh_from_db()
        self.assertTrue(pairing.last_check(self.conn_a)['recheck'])
        # The next event is not blocked behind it.
        self.fake.alert_event(self.org(self.conn_a), 2, alert_id='cmalertgood00000000000002', endpoint=EP_A)
        self.assertEqual(alerts.poll(self.conn_a), 1)
        self.assertEqual(alerts.cursor(self.conn_a), 2)
        # Rem0te now declares revision 3 ("revisions only add fields"):
        # reconciliation re-checks at once and applies the skipped event.
        self.fake.caps = dict(self.fake.caps, contract_revision=3)
        self.assertTrue(reconcile.check_due(self.conn_a))
        out = reconcile.reconcile(self.conn_a)
        self.assertTrue(out['checked'])
        self.assertGreaterEqual(out['events'], 1)
        self.assertTrue(Rem0teAlertEvent.objects.get(sequence=1).applied)
        self.assertTrue(Rem0teAlertTicket.objects.filter(alert_id='cmalertbad0000000000000001').exists())
        self.assertEqual(self.state(self.conn_a), health.CONNECTED)

    def test_poll_never_loops_on_a_refused_event(self):
        for seq in (1, 2, 3):
            if seq == 2:
                self.bad_event(seq, severity='catastrophic')
            else:
                self.fake.alert_event(self.org(self.conn_a), seq, alert_id=f'cmalertpoll0000000000000{seq}',
                                      endpoint=EP_A)
        self.assertEqual(alerts.poll(self.conn_a), 3)
        self.assertEqual(alerts.cursor(self.conn_a), 3)
        self.assertEqual(Rem0teAlertTicket.objects.count(), 2)
        before = len(self.fake.calls)
        alerts.poll(self.conn_a)
        polls = [c for c in self.fake.calls[before:] if c[1] == '/alerts/events']
        self.assertEqual(len(polls), 1)
        self.assertEqual(self.state(self.conn_a), health.DEGRADED)

    def test_foreign_event_in_the_feed_is_never_applied(self):
        ev = self.fake.alert_event(self.org(self.conn_b), 1, endpoint='cmendpointb0000000000000001')
        ev['alert_event']['organization_id'] = self.org(self.conn_a)  # in A's feed…
        ev['alert_event']['peer_id'] = 'someone-else'  # …for another peer
        ev['signature'] = rt.sign_event(ev['alert_event'], alert=True)
        self.fake.alert_events[-1] = ev
        alerts.poll(self.conn_a)
        rec = Rem0teAlertEvent.objects.get()
        self.assertFalse(rec.applied)
        self.assertTrue(rec.problem.startswith(alerts.FOREIGN))
        self.assertFalse(Rem0teAlertTicket.objects.exists())
        self.assertEqual(alerts.reprocess_skipped(self.conn_a), 0)
        self.assertEqual(self.state(self.conn_a), health.DEGRADED)
        self.fake.alert_event(self.org(self.conn_a), 2, endpoint=EP_A)
        alerts.poll(self.conn_a)
        self.assertEqual(self.state(self.conn_a), health.CONNECTED)  # healed by the next good event

    def test_replayed_request_nonce_is_refused(self):
        ev = self.fake.alert_event(self.org(self.conn_a), 1, endpoint=EP_A)
        first = rt.signed_post(self.rc, EVENTS, ev, nonce='n' * 24)
        self.assertEqual(first.status_code, 200)
        again = rt.signed_post(self.rc, EVENTS, ev, nonce='n' * 24)
        self.assertEqual(again.status_code, 401)
        self.assertEqual(Rem0teAlertTicket.objects.count(), 1)

    def test_gap_reported_by_rem0te_is_visible(self):
        self.fake.alert_event(self.org(self.conn_a), 1, endpoint=EP_A)
        self.fake.alert_event(self.org(self.conn_a), 3, alert_id='cmalertgap00000000000003', endpoint=EP_A)
        alerts.poll(self.conn_a)
        st = health.evaluate(self.conn_a)
        self.assertTrue(any(x['code'] == 'ALERT_GAP' for x in st['reasons']))
        self.fake.alert_event(self.org(self.conn_a), 2, alert_id='cmalertgap00000000000002', endpoint=EP_A)
        alerts.poll(self.conn_a)
        self.assertEqual(alerts.cursor(self.conn_a), 3)
        self.assertEqual(self.state(self.conn_a), health.CONNECTED)

    def test_same_name_computers_match_by_rem0te_id_only(self):
        from assets.models import Asset
        Asset.objects.create(organization=self.b, name='Front desk', hostname='FRONTDESK-01', asset_type='desktop')
        # Unknown Rem0te id, same computer name as an asset in this customer: no asset.
        ev = self.fake.alert_event(self.org(self.conn_a), 1, endpoint='cmendpointunknown000000001',
                                   computer='FRONTDESK-01')
        rt.signed_post(self.rc, EVENTS, ev)
        self.assertIsNone(Rem0teAlertTicket.objects.get().ticket.related_asset)
        ev = self.fake.alert_event(self.org(self.conn_a), 2, alert_id='cmalertknown0000000000002', endpoint=EP_A,
                                   computer='SOMETHING-ELSE')
        rt.signed_post(self.rc, EVENTS, ev)
        self.assertEqual(Rem0teAlertTicket.objects.get(alert_id='cmalertknown0000000000002').ticket.related_asset,
                         self.asset_a)


class ContainmentTests(Rev2Base):
    def setUp(self):
        super().setUp()
        self.ticket.related_asset = self.asset_a
        self.ticket.save()

    def test_paused_business_job_fails_once_with_no_free_text(self):
        self.revision(2, paused_a=['integration'])
        self.assertEqual(self.state(self.conn_a), health.DEGRADED)
        self.fake.paused[self.org(self.conn_a)] = {'integration'}
        job = self.start()
        job.refresh_from_db()
        self.assertEqual((job.status, job.processor_error_code), ('failed', 'CONTAINED'))
        self.assertIn('paused', job.error)
        self.assertNotIn('under review', job.error)  # Rem0te's pause reason is not kept
        submits = [c for c in self.fake.calls if c[:2] == ('POST', '/jobs')]
        self.assertEqual(len(submits), 1)  # not retried until it expires
        st = health.evaluate(self.conn_a)
        self.assertEqual(st['state'], health.DEGRADED)
        self.assertFalse(any('under review' in x['message'] for x in st['reasons']))
        # Lifted in Rem0te: the next check clears the recorded refusal.
        self.fake.paused = {}
        self.revision(2)
        self.assertEqual(self.state(self.conn_a), health.CONNECTED)

    def test_paused_actions_are_unavailable_not_rejected(self):
        self.fake.paused[self.org(self.conn_a)] = {'actions'}
        req, _ = rmm_actions.refer_fix(self.tech, self.ticket, self.device.pk, 'key-contained-1',
                                       description='Spooler stopped.', action_key='windows.service.start@1')
        req.refresh_from_db()
        self.assertEqual((req.status, req.remote_status), ('unavailable', 'CONTAINED'))
        self.assertNotIn('under review', req.error)
        self.assertNotEqual(req.status, 'rejected')
        # Not polled again (terminal for this proposal).
        before = len(self.fake.calls)
        actions.poll_open(connection=self.conn_a)
        self.assertEqual(len(self.fake.calls), before)


class ExpiredApprovalTests(Rev2Base):
    def setUp(self):
        super().setUp()
        self.ticket.related_asset = self.asset_a
        self.ticket.save()

    def test_approval_window_over_while_rem0te_is_unreachable(self):
        req, _ = rmm_actions.refer_fix(self.tech, self.ticket, self.device.pk, 'key-expire-1',
                                       description='Spooler stopped.', action_key='windows.service.start@1')
        req.refresh_from_db()
        self.assertEqual(req.remote_status, 'awaiting_approval')
        RMMRequest.objects.filter(pk=req.pk).update(approval_expires_at=timezone.now() - timedelta(minutes=30))
        req.refresh_from_db()
        self.fake.fail = lambda m, r: ('unreachable',)
        actions.refresh(req, force=True)
        req.refresh_from_db()
        self.assertEqual((req.status, req.remote_status), ('expired', 'expired'))
        self.assertIn('approval window ended', req.status_note)

    def test_within_grace_stays_open(self):
        req, _ = rmm_actions.refer_fix(self.tech, self.ticket, self.device.pk, 'key-expire-2',
                                       description='Spooler stopped.', action_key='windows.service.start@1')
        RMMRequest.objects.filter(pk=req.pk).update(approval_expires_at=timezone.now() - timedelta(minutes=2))
        req.refresh_from_db()
        self.fake.fail = lambda m, r: ('unreachable',)
        actions.refresh(req, force=True)
        req.refresh_from_db()
        self.assertEqual(req.remote_status, 'awaiting_approval')
        self.assertTrue(req.error)

    def test_rem0te_reports_expired(self):
        req, _ = rmm_actions.refer_fix(self.tech, self.ticket, self.device.pk, 'key-expire-3',
                                       description='Spooler stopped.', action_key='windows.service.start@1')
        next(iter(self.fake.proposals.values())).update(status='expired')
        actions.refresh(req, force=True)
        req.refresh_from_db()
        self.assertEqual(req.status, 'expired')


class OutageRecoveryTests(Rev2Base):
    def test_jobs_retry_through_an_outage_without_duplicates(self):
        self.ticket.related_asset = self.asset_a
        self.ticket.save()
        self.fake.fail = lambda m, r: (503, 'UNAVAILABLE', 'maintenance') if r == '/jobs' else None
        job = self.start()
        job.refresh_from_db()
        self.assertNotEqual(job.status, 'failed')
        self.assertEqual(self.state(self.conn_a), health.DEGRADED)
        self.fake.fail = None
        from integrations.rem0te import jobs
        jobs.submit(job)
        job.refresh_from_db()
        self.assertTrue(job.processor_job_id)
        jobs.submit(job)  # a second send after recovery is answered by Rem0te's idempotency
        self.assertEqual(len(self.fake.jobs), 1)
        self.assertEqual(self.state(self.conn_a), health.CONNECTED)
