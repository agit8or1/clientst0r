"""
Ticket analysis, alerts → tickets and action proposals through Rem0te's
Ed25519 protocol (integrations/rem0te), against the in-process Rem0te in
integrations/rem0te/testing.py. Permissions: an L1 technician cannot
propose actions, reveal a restricted credential or send an AI draft.
"""
import json
import uuid
from unittest.mock import patch

from django.test import Client
from django.utils import timezone

from integrations.models import RMMConnection, RMMDevice
from integrations.rem0te import alerts, actions, identity, jobs, pairing, protocol, schema, testing as rt
from psa.models import Ticket, TicketComment
from tech_access.testing import grant, make_tech

from .models import AnalysisJob, AnalysisRun, Rem0teAlertEvent, Rem0teAlertTicket, RMMRequest
from .services import rmm_actions
from .tests_assist import AssistBase, sign_in

OUTPUT = json.dumps({
    'category': 'printing', 'summary': 'The front desk printer is offline.',
    'facts': [{'statement': 'The printer has been offline since Monday.', 'evidence_refs': ['REF_BODY']}],
    'hypotheses': [{'statement': 'The printer lost its network address.', 'confidence': 'medium',
                    'evidence_refs': ['REF_BODY']}],
    'draft_reply': 'Thanks for letting us know. We are checking the front desk printer now and will update you '
                   'within the hour with what we find.',
    'next_steps': ['Check the printer status page for an IP address.'],
})
INFER = '/api/integration/v1/inference'
EVENTS = '/api/integration/v1/events'


class Rem0teBase(AssistBase):
    def setUp(self):
        super().setUp()
        RMMConnection.objects.filter(pk__in=[self.conn_a.pk, self.conn_b.pk]).delete()
        self.ident = rt.setup_identity()
        self.conn_a = rt.make_connection(self.a, name='Rem0te alpha')
        self.conn_b = rt.make_connection(self.b, name='Rem0te beta')
        self.fake = rt.FakeRem0te()
        self.fake.caps = rt.capabilities(model_profiles=[pairing.profile_slug(self.cheap),
                                                         pairing.profile_slug(self.big)])
        cm = self.fake.running()
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        for conn in (self.conn_a, self.conn_b):
            self.assertTrue(pairing.check(conn)['compatible'])
            conn.refresh_from_db()
        self.rc = Client()

    def job_doc(self, job):
        return self.fake.jobs[job.idempotency_key]

    def inference(self, job, profile, request_id=None, segments=None):
        req = job.processor_request
        segs = segments if segments is not None else jobs.ticket_segments(req)
        body = {'contract': 'ticket-rmm-v1', 'request_id': request_id or str(uuid.uuid4()),
                'job_id': job.processor_job_id, 'organization_id': req['organization_id'],
                'model_profile': pairing.profile_slug(profile), 'task': 'ticket_triage_v1',
                'output_schema': 'analysis-output.v1', 'max_output_tokens': 2000,
                'input': {'instructions_ref': 'rem0te/ticket-triage/v1', 'untrusted_segments': segs,
                          'evidence_refs': [s['ref'] for s in segs]}}
        self.assertEqual(schema.errors('inference-request', body), [])
        return rt.signed_post(self.rc, INFER, body), body

    def output_for(self, job):
        ref = f'ticket:{job.processor_request["ticket"]["id"]}@{job.processor_request["ticket"]["revision"]}#body'
        return OUTPUT.replace('REF_BODY', ref)


class AnalysisJobTests(Rem0teBase):
    def test_job_inference_and_signed_result(self):
        job = self.start()
        self.assertEqual(job.protocol, AnalysisJob.PROTOCOL_REM0TE)
        job.refresh_from_db()
        self.assertTrue(job.processor_job_id)
        sent = json.dumps(job.processor_request)
        for secret in ('hunter2', 'pat@alpha.test', 'vault entry 42'):
            self.assertNotIn(secret, sent)
        self.assertEqual(job.processor_request['organization_id'], f'org-{self.a.pk}')
        self.assertEqual(job.processor_request['technician_id'], f'tech-{self.tech.pk}')
        # One model run per profile; a Rem0te retry is answered from the run.
        with patch('psa_ai.services.gateway.call_provider', return_value=(self.output_for(job), 100, 50)) as cp:
            r, body = self.inference(job, self.cheap)
            self.assertEqual(r.status_code, 200, r.content)
            again, _ = self.inference(job, self.cheap)
        self.assertEqual(cp.call_count, 1)
        out = json.loads(r.content)
        self.assertEqual(schema.errors('inference-response', out), [])
        self.assertEqual((out['status'], out['request_id'], out['job_id']), ('ok', body['request_id'], body['job_id']))
        self.assertEqual(json.loads(again.content)['output'], out['output'])
        # The response is signed over the request nonce with ClientSt0r's request key.
        self.assertEqual(r.headers[protocol.H_KEY_ID], identity.request_key_id(self.ident))
        pub = protocol.load_public_key(protocol.public_pem(self.ident.request_private_key))
        nonce = [v for k, v in r.wsgi_request.META.items() if k == 'HTTP_REM0TE_NONCE'][0]
        self.assertTrue(protocol.verify(pub, protocol.response_signing_string(nonce, protocol.sha256_hex(r.content)),
                                        r.headers[protocol.H_RESPONSE_SIGNATURE]))
        # Rem0te closes the job with a signed terminal event; pushing it twice changes nothing.
        result = json.loads((schema.FIXTURE_DIR / 'analysis-result.two-models.json').read_text())
        ev = self.fake.job_event(self.job_doc(job), 3, 'job.succeeded', 'succeeded', result=result,
                                 runs_status='succeeded')
        self.assertEqual(rt.signed_post(self.rc, EVENTS, ev).status_code, 200)
        self.assertEqual(rt.signed_post(self.rc, EVENTS, ev).json()['status'], 'duplicate')
        job.refresh_from_db()
        self.assertEqual(job.status, 'completed')
        self.assertEqual(job.processor_result['visibility'], 'staff_only')
        d = self.c.get(f'/psa/ai/assist/job/{job.pk}/').json()
        self.assertEqual(d['processor']['result']['visibility'], 'staff_only')
        self.assertTrue(d['processor']['result']['draft_replies'])
        # Staff only: the customer portal never shows it, and nothing was posted.
        self.assertFalse(TicketComment.objects.filter(ticket=self.ticket, is_internal=False).exists())

    def test_inference_refusals(self):
        job = self.start()
        job.refresh_from_db()
        other = job.processor_request['ticket']
        bad = [{'ref': f'ticket:someone-else@{other["revision"]}#body', 'kind': 'ticket_body', 'text': 'x'}]
        r, _ = self.inference(job, self.cheap, segments=bad)
        self.assertEqual(json.loads(r.content)['error_code'], 'segment_unexpected')
        self.assertEqual(json.loads(r.content)['status'], 'refused')
        r, _ = self.inference(job, self.big)  # a profile the job never named
        self.assertEqual(json.loads(r.content)['error_code'], 'profile_not_in_job')

    def test_access_revoked_before_the_run_is_refused(self):
        job = self.start()
        job.refresh_from_db()
        from tech_access.models import AccessAssignment
        AccessAssignment.objects.filter(user=self.tech).delete()
        with patch('psa_ai.services.gateway.call_provider') as cp:
            r, _ = self.inference(job, self.cheap)
        out = json.loads(r.content)
        self.assertEqual((out['status'], out['error_code']), ('refused', 'actor_not_permitted'))
        cp.assert_not_called()

    def test_unknown_job_is_transient(self):
        job = self.start()
        job.refresh_from_db()
        job.processor_job_id = str(uuid.uuid4())
        r, _ = self.inference(job, self.cheap)
        self.assertEqual(r.status_code, 503)
        self.assertTrue(r.headers.get(protocol.H_RESPONSE_SIGNATURE))

    def test_unavailable_peer_then_retry_creates_one_job(self):
        self.fake.fail = lambda m, r: ('unreachable',) if r == '/jobs' else None
        job = self.start()
        job.refresh_from_db()
        self.assertEqual(job.status, 'created')
        self.assertIn('rem0te.example.com', job.error)
        self.assertEqual(self.fake.jobs, {})
        self.fake.fail = None
        jobs.poll(job, force=True)
        job.refresh_from_db()
        self.assertTrue(job.processor_job_id)
        jobs.poll(job, force=True)
        self.assertEqual(len(self.fake.jobs), 1)

    def test_lost_submit_response_bound_by_signed_event(self):
        # Rem0te created the job but its answer never arrived.
        self.fake.fail = lambda m, r: ('unreachable',) if r == '/jobs' else None
        job = self.start()
        job.refresh_from_db()
        self.fake.fail = None
        claims = {'scope': 'ticket_analysis:submit'}
        self.fake._route('POST', '/jobs', job.processor_request, {}, claims)
        doc = self.job_doc(job)
        ev = self.fake.job_event(doc, 2, 'job.running', 'running')
        self.assertEqual(rt.signed_post(self.rc, EVENTS, ev).status_code, 200)
        job.refresh_from_db()
        self.assertEqual(job.processor_job_id, doc['job_id'])
        self.assertEqual(job.status, 'running')
        jobs.submit(job)  # an idempotent re-send: still one job
        self.assertEqual(len(self.fake.jobs), 1)

    def test_revoked_technician_is_refused_by_rem0te(self):
        self.fake.fail = lambda m, r: (403, 'FORBIDDEN', 'Technician mapping revoked') if r == '/jobs' else None
        job = self.start()
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.processor_error_code, 'FORBIDDEN')
        self.assertIn('technician', job.error.lower())

    def test_event_for_other_organization_or_forged_is_refused(self):
        job = self.start()
        job.refresh_from_db()
        doc = dict(self.job_doc(job), organization_id=f'org-{self.b.pk}')
        ev = self.fake.job_event(doc, 2, 'job.running', 'running')
        self.assertEqual(rt.signed_post(self.rc, EVENTS, ev).status_code, 404)
        ev = self.fake.job_event(self.job_doc(job), 2, 'job.running', 'running')
        ev['signature'] = rt.sign_event(ev['event'], key=protocol.load_private_key(protocol.generate_private_key_pem()))
        self.assertEqual(rt.signed_post(self.rc, EVENTS, ev).status_code, 401)
        ev = self.fake.job_event(self.job_doc(job), 2, 'job.running', 'running')
        ev['signature'] = rt.sign_event(ev['event'], alert=True)  # wrong domain
        self.assertEqual(rt.signed_post(self.rc, EVENTS, ev).status_code, 401)


class AlertTicketTests(Rem0teBase):
    def setUp(self):
        super().setUp()
        from assets.models import Asset
        now = timezone.now()
        # Two customers, same computer name, different Rem0te computers.
        self.asset_a = Asset.objects.create(organization=self.a, name='Front desk', hostname='FRONTDESK-01',
                                            asset_type='desktop')
        self.asset_b = Asset.objects.create(organization=self.b, name='Front desk', hostname='FRONTDESK-01',
                                            asset_type='desktop')
        RMMDevice.objects.create(organization=self.a, connection=self.conn_a, external_id='cmendpointa0000000000000001',
                                 device_name='FRONTDESK-01', linked_asset=self.asset_a, data_refreshed_at=now)
        RMMDevice.objects.create(organization=self.b, connection=self.conn_b, external_id='cmendpointb0000000000000001',
                                 device_name='FRONTDESK-01', linked_asset=self.asset_b, data_refreshed_at=now)

    def org(self, conn):
        return pairing.organization_id(conn)

    def test_raised_opens_exactly_one_staff_ticket_and_links_back(self):
        before = Ticket.objects.count()
        ev = self.fake.alert_event(self.org(self.conn_a), 1, endpoint='cmendpointa0000000000000001')
        self.assertEqual(rt.signed_post(self.rc, EVENTS, ev).status_code, 200)
        self.assertEqual(rt.signed_post(self.rc, EVENTS, ev).json()['status'], 'duplicate')
        # The same alert raised again (e.g. re-sent after a restart under a new event id): no second ticket.
        again = self.fake.alert_event(self.org(self.conn_a), 2, endpoint='cmendpointa0000000000000001')
        self.assertEqual(rt.signed_post(self.rc, EVENTS, again).status_code, 200)
        alerts.poll(self.conn_a)  # polling the same events changes nothing
        self.assertEqual(Ticket.objects.count(), before + 1)
        row = Rem0teAlertTicket.objects.get()
        t = row.ticket
        self.assertEqual((t.organization_id, t.visibility, t.client_can_view, t.source), (self.a.pk, 'staff', False, 'rmm'))
        self.assertEqual(t.related_asset, self.asset_a)
        self.assertEqual(row.link_status, 'linked')
        link = self.fake.links[row.alert_id]
        self.assertEqual(link['ticket_url'], f'https://cs.example.com/psa/t/{t.ticket_number}/')
        # Updated / resolved change the alert row only.
        status_before = t.status_id
        upd = self.fake.alert_event(self.org(self.conn_a), 3, etype='alert.resolved',
                                    endpoint='cmendpointa0000000000000001')
        rt.signed_post(self.rc, EVENTS, upd)
        row.refresh_from_db()
        t.refresh_from_db()
        self.assertEqual(row.state, 'resolved')
        self.assertEqual(t.status_id, status_before)
        self.assertFalse(TicketComment.objects.filter(ticket=t).exists())

    def test_same_computer_name_in_two_customers_never_mixes(self):
        rt.signed_post(self.rc, EVENTS, self.fake.alert_event(self.org(self.conn_a), 1, alert_id='cmalerta000000000000000001',
                                                              endpoint='cmendpointa0000000000000001'))
        rt.signed_post(self.rc, EVENTS, self.fake.alert_event(self.org(self.conn_b), 1, alert_id='cmalertb000000000000000001',
                                                              endpoint='cmendpointb0000000000000001'))
        ta = Rem0teAlertTicket.objects.get(connection=self.conn_a).ticket
        tb = Rem0teAlertTicket.objects.get(connection=self.conn_b).ticket
        self.assertEqual((ta.organization_id, ta.related_asset), (self.a.pk, self.asset_a))
        self.assertEqual((tb.organization_id, tb.related_asset), (self.b.pk, self.asset_b))
        # An alert naming the other customer's computer gets no asset.
        rt.signed_post(self.rc, EVENTS, self.fake.alert_event(self.org(self.conn_a), 2, alert_id='cmalertx000000000000000001',
                                                              endpoint='cmendpointb0000000000000001'))
        tx = Rem0teAlertTicket.objects.get(alert_id='cmalertx000000000000000001').ticket
        self.assertEqual(tx.organization_id, self.a.pk)
        self.assertIsNone(tx.related_asset)

    def test_gap_recovered_by_polling_and_link_retried(self):
        for seq in (1, 2):
            self.fake.alert_event(self.org(self.conn_a), seq, alert_id=f'cmalertgap00000000000000{seq:02d}',
                                  endpoint='cmendpointa0000000000000001')
        self.fake.fail = lambda m, r: (503, 'UNAVAILABLE', 'later') if r.endswith('/ticket') else None
        self.assertEqual(alerts.poll(self.conn_a), 2)
        self.assertEqual(Rem0teAlertTicket.objects.filter(link_status='failed').count(), 2)
        self.assertTrue(all('later' in r.link_error for r in Rem0teAlertTicket.objects.all()))
        self.fake.fail = None
        Rem0teAlertTicket.objects.update(next_link_at=timezone.now())
        alerts.poll(self.conn_a)
        self.assertEqual(Rem0teAlertTicket.objects.filter(link_status='linked').count(), 2)
        self.assertEqual(Rem0teAlertEvent.objects.filter(connection=self.conn_a).count(), 2)
        self.assertEqual(alerts.cursor(self.conn_a), 2)

    def test_link_conflict_is_kept(self):
        self.fake.links['cmalert0000000000000000001'] = {'ticket_id': 'someone-elses'}
        rt.signed_post(self.rc, EVENTS, self.fake.alert_event(self.org(self.conn_a), 1))
        self.assertEqual(Rem0teAlertTicket.objects.get().link_status, 'conflict')

    def test_example_alert_for_another_peer_is_not_applied(self):
        # Rem0te's recorded revision-2 exchange, signed by its TEST-ONLY key
        # for peer clientst0r-example.
        ex = json.loads((schema.EXAMPLE_DIR / 'alert-event.raised-with-patch-summary.json').read_text())
        signed = ex['request']['body']
        self.conn_a.field_mappings = dict(self.conn_a.field_mappings, **{pairing.SIGNING_KEYS: [
            {'kid': 'rem0te-example-1',
             'public_key_pem': (schema.EXAMPLE_DIR / 'keys' / 'rem0te-self.pub.pem').read_text()}]})
        self.conn_a.save()
        status, outcome = alerts.apply_signed_alert_event(self.conn_a, signed)
        self.assertEqual(status, 404)  # signature good, peer/organization not ours
        signed['alert_event']['alert']['severity'] = 'info'
        self.assertEqual(alerts.apply_signed_alert_event(self.conn_a, signed)[0], 401)
        self.assertFalse(Rem0teAlertTicket.objects.exists())


class ActionProposalTests(Rem0teBase):
    def setUp(self):
        super().setUp()
        from assets.models import Asset
        self.asset = Asset.objects.create(organization=self.a, name='Front desk', hostname='FRONTDESK-01',
                                          asset_type='desktop')
        self.device = RMMDevice.objects.create(organization=self.a, connection=self.conn_a,
                                               external_id='cmendpointa0000000000000001', device_name='FRONTDESK-01',
                                               device_type='workstation', linked_asset=self.asset,
                                               data_refreshed_at=timezone.now())
        self.ticket.related_asset = self.asset
        self.ticket.save()

    def propose(self, user, key='key-spooler-1'):
        return rmm_actions.refer_fix(user, self.ticket, self.device.pk, key, description='Nothing prints; the '
                                     'Print Spooler service is stopped.', action_key='windows.service.start@1')

    def test_l2_proposes_rem0te_approves(self):
        req, repeat = self.propose(self.tech)
        self.assertFalse(repeat)
        req.refresh_from_db()
        self.assertEqual((req.status, req.remote_status), ('received', 'awaiting_approval'))
        self.assertTrue(req.approval_url.startswith('https://approve.example.com/'))
        sent = req.payload['rem0te_proposal']
        self.assertEqual(sent['params'], {'service': 'Spooler'})
        self.assertNotIn('command', json.dumps(sent))
        again, repeat = self.propose(self.tech)
        self.assertTrue(repeat)
        self.assertEqual(len(self.fake.proposals), 1)
        # ClientSt0r only reflects Rem0te's status.
        p = next(iter(self.fake.proposals.values()))
        p.update(status='succeeded', outcome='succeeded', observed={'before': 'stopped', 'after10s': 'running'})
        actions.refresh(req, force=True)
        req.refresh_from_db()
        self.assertEqual(req.status, 'succeeded')
        self.assertIn('after10s=running', req.status_note)
        self.ticket.refresh_from_db()
        self.assertNotEqual(self.ticket.status.slug, 'closed')

    def test_computer_of_another_business_is_not_a_target(self):
        from integrations.ticket_rmm import REM0TE_BUSINESS_PIN
        self.conn_a.field_mappings = dict(self.conn_a.field_mappings, **{REM0TE_BUSINESS_PIN: 'biz-alpha'})
        self.conn_a.save()
        RMMDevice.objects.filter(pk=self.device.pk).update(client_id='biz-alpha')
        RMMDevice.objects.create(organization=self.a, connection=self.conn_a, external_id='cmendpointother00000000001',
                                 device_name='THEIRS', client_id='biz-other', linked_asset=self.asset,
                                 data_refreshed_at=timezone.now())
        self.assertEqual([t.device.pk for t in rmm_actions.targets(self.ticket)], [self.device.pk])

    def test_l1_cannot_propose(self):
        l1 = make_tech('helpdesk')
        grant(l1, self.a, 'l1')
        with self.assertRaises(rmm_actions.ActionRefused):
            self.propose(l1)
        self.assertEqual(self.fake.proposals, {})

    def test_rem0te_refusal_reason(self):
        self.fake.fail = lambda m, r: (403, 'ACTION_NOT_GRANTED', 'no') if r == '/action-proposals' else None
        req, _ = self.propose(self.tech)
        req.refresh_from_db()
        self.assertEqual(req.status, 'rejected')
        self.assertIn('may not request that action', req.error)

    def test_unknown_action_refused_locally(self):
        with self.assertRaises(rmm_actions.ActionRefused):
            rmm_actions.refer_fix(self.tech, self.ticket, self.device.pk, 'key-x-00001', description='run a script',
                                  action_key='shell.exec@1')


class L1PermissionTests(Rem0teBase):
    def test_l1_cannot_send_rem0te_draft_or_reveal_restricted_credential(self):
        job = self.start()
        job.refresh_from_db()
        result = json.loads((schema.FIXTURE_DIR / 'analysis-result.two-models.json').read_text())
        rt.signed_post(self.rc, EVENTS, self.fake.job_event(self.job_doc(job), 3, 'job.succeeded', 'succeeded',
                                                            result=result, runs_status='succeeded'))
        draft = result['draft_replies'][0]['text']
        l1 = make_tech('helpdesk')
        grant(l1, self.a, 'l1')
        c = sign_in(l1, self.a)
        self.ticket.assigned_to = l1
        self.ticket.save()
        c.post(f'/psa/t/{self.ticket.ticket_number}/comment/', {'body': draft, 'ai_draft': f'rem0te:{job.pk}:0'})
        self.assertFalse(TicketComment.objects.filter(ticket=self.ticket, is_internal=False, body=draft).exists())
        c.post(f'/psa/t/{self.ticket.ticket_number}/comment/', {'body': draft})  # marker stripped: still caught
        self.assertFalse(TicketComment.objects.filter(ticket=self.ticket, is_internal=False, body=draft).exists())
        # The assigned L2 can, through the normal Send (ai_send is ticket-scoped).
        self.ticket.assigned_to = self.tech
        self.ticket.save()
        self.c.post(f'/psa/t/{self.ticket.ticket_number}/comment/', {'body': draft, 'ai_draft': f'rem0te:{job.pk}:0'})
        self.assertTrue(TicketComment.objects.filter(ticket=self.ticket, is_internal=False, body=draft).exists())
        # A credential that requires approval is never revealed to L1.
        from vault.models import Password
        pw = Password(organization=self.a, title='Domain admin', username='admin', requires_reveal_approval=True)
        pw.set_password('S3cret-value!')
        pw.save()
        r = c.post(f'/vault/{pw.pk}/reveal/')
        self.assertIn(r.status_code, (403, 404))
        self.assertNotIn('S3cret-value!', r.content.decode())
