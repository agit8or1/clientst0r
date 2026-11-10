"""
The ticket's staff-only AI and automation history (services/history.py):
what is recorded (model, profile, prompt version, human decisions, approval
requirement and expiry, Rem0te outcome, routing), who may see it (MSP
technicians only, AI entries only with view_output, AI text only while AI is
on), redaction, retention, and that neither rendering it nor routing a
ticket ever calls an RMM / Rem0te endpoint.
"""
import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.template import Context, Template
from django.test import Client, RequestFactory, override_settings
from django.utils import timezone

from accounts.models import Membership, Role
from integrations.models import RMMDevice
from integrations.rem0te import actions, schema, testing as rt
from psa.models import ClientPSASettings, TicketComment
from tech_access.testing import grant, make_tech, make_ticket

from .models import (
    AIBusinessPolicy, AIDraftDecision, AIHistoryPurgeState, AISuggestion, AnalysisJob, AnalysisRun, RMMRequest,
)
from .services import history, prompt_versions, rmm_actions
from .tests_assist import sign_in
from .tests_rem0te import EVENTS, Rem0teBase

PANEL = 'ai-automation-history'
PANEL_END = '<!-- /ai-automation-history -->'


def panel_of(html):
    return html[html.index(PANEL):html.index(PANEL_END)]


def _no_remote_calls():
    """Patches for every way ClientSt0r reaches an RMM or Rem0te: the Rem0te
    signed client (sessions, launches, action proposals, jobs), the generic
    ticket-rmm-v1 request, remote launch and fix referral entry points."""
    return [patch('integrations.rem0te.client.request'),
            patch('integrations.rem0te.actions.send'),
            patch('integrations.rem0te.actions.refresh'),
            patch('psa_ai.services.rmm_actions.launch'),
            patch('psa_ai.services.rmm_actions.refer_fix'),
            patch('psa_ai.services.rmm_actions.send'),
            patch('psa_ai.services.processor.submit')]


class HistoryBase(Rem0teBase):
    def finished_job(self):
        job = self.start()
        job.refresh_from_db()
        with patch('psa_ai.services.gateway.call_provider', return_value=(self.output_for(job), 100, 50)):
            r, _ = self.inference(job, self.cheap)
            self.assertEqual(r.status_code, 200, r.content)
        result = json.loads((schema.FIXTURE_DIR / 'analysis-result.two-models.json').read_text())
        ev = self.fake.job_event(self.job_doc(job), 3, 'job.succeeded', 'succeeded', result=result,
                                 runs_status='succeeded')
        self.assertEqual(rt.signed_post(self.rc, EVENTS, ev).status_code, 200)
        job.refresh_from_db()
        return job, result

    def page(self, client=None, ticket=None):
        return (client or self.c).get(f'/psa/t/{(ticket or self.ticket).ticket_number}/')

    def entries(self, user=None, kind=None):
        data = history.build(self.ticket, user or self.tech)
        return [e for e in data.get('entries', []) if kind is None or e['kind'] == kind]


class PromptVersionTests(HistoryBase):
    def test_identifier_is_file_name_and_content_hash(self):
        v = prompt_versions.prompt_version('system_reply.md')
        self.assertRegex(v, r'^system_reply\.md@[0-9a-f]{12}$')
        self.assertEqual(v, prompt_versions.prompt_version('system_reply.md'))
        self.assertNotEqual(v.split('@')[1], prompt_versions.prompt_version('system_triage.md').split('@')[1])
        self.assertTrue(prompt_versions.is_hashed(v))
        self.assertFalse(prompt_versions.is_hashed('1'))

    def test_identifier_changes_with_the_file(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d, patch.object(prompt_versions, 'PROMPTS_DIR', Path(d)):
            p = Path(d) / 'x.md'
            p.write_text('one')
            first = prompt_versions.prompt_version('x.md')
            p.write_text('two, longer')
            self.assertNotEqual(first, prompt_versions.prompt_version('x.md'))

    def test_generators_record_the_hashed_version(self):
        from .services import action_generator, reply_generator, triage_generator
        for mod, name in ((reply_generator, 'system_reply.md'), (triage_generator, 'system_triage.md'),
                          (action_generator, 'system_action.md')):
            self.assertEqual(mod._prompt_version(), prompt_versions.prompt_version(name))

    def test_each_run_records_resolved_model_and_prompt_version(self):
        job, _ = self.finished_job()
        run = AnalysisRun.objects.get(job=job, profile=self.cheap)
        self.assertEqual(run.resolved_model, 'anthropic/test-model')
        self.assertEqual(run.prompt_version, prompt_versions.prompt_version('rem0te_ticket_triage_v1.md'))
        other = AnalysisRun.objects.filter(job=job).exclude(pk=run.pk)
        self.assertTrue(all(not r.prompt_version for r in other))  # never ran: nothing claimed


class TimelineTests(HistoryBase):
    def test_analysis_drafts_decisions_and_rem0te_outcome(self):
        job, result = self.finished_job()
        draft = result['draft_replies'][0]['text']
        url = f'/psa/t/{self.ticket.ticket_number}/comment/'
        self.c.post(url, {'body': draft, 'ai_draft': f'rem0te:{job.pk}:0'})
        self.c.post(url, {'body': 'Hi Pat,\n\n' + draft + '\n\nThanks, Lee'})  # edited, marker stripped
        self.c.post(url, {'body': draft, 'is_internal': '1', 'ai_draft': f'rem0te:{job.pk}:0'})
        self.c.post(url, {'body': 'I am on my way to look at the printer now.'})  # manual: not recorded
        got = list(AIDraftDecision.objects.filter(ticket=self.ticket).values_list('decision', 'source', 'job_id'))
        self.assertEqual(got, [('sent', 'rem0te', job.pk), ('sent_edited', 'rem0te', job.pk),
                               ('kept_internal', 'rem0te', job.pk)])
        self.assertTrue(all(d.comment_id for d in AIDraftDecision.objects.all()))

        [e] = self.entries(kind='ai_analysis')
        self.assertEqual([d['text'] for d in e['decisions']],
                         ['Sent to the customer unchanged', 'Edited, then sent to the customer',
                          'Kept as an internal note'])
        self.assertTrue(all(d['by'] == 'lee' for d in e['decisions']))
        run = next(r for r in e['runs'] if r['profile'] == self.cheap.name)
        self.assertEqual(run['model'], 'anthropic/test-model')
        self.assertRegex(run['prompt_version'], r'^rem0te_ticket_triage_v1\.md@[0-9a-f]{12}$')
        self.assertIn(('Status', 'Completed'), e['facts'])

        html = self.page().content.decode()
        self.assertIn(PANEL, html)
        self.assertIn(run['prompt_version'], html)
        self.assertIn('Edited, then sent to the customer', html)

    def test_failed_rem0te_job_shows_error_code(self):
        self.fake.fail = lambda m, r: (403, 'FORBIDDEN', 'technician not mapped') if r == '/jobs' else None
        job = self.start()
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        [e] = self.entries(kind='ai_analysis')
        self.assertEqual(e['error_code'], 'FORBIDDEN')
        self.assertIn('Rem0te refused', e['outcome'])

    def test_l1_refused_send_is_recorded(self):
        job, result = self.finished_job()
        l1 = make_tech('helpdesk')
        grant(l1, self.a, 'l1')
        self.ticket.assigned_to = l1
        self.ticket.save()
        sign_in(l1, self.a).post(f'/psa/t/{self.ticket.ticket_number}/comment/',
                                 {'body': result['draft_replies'][0]['text']})
        d = AIDraftDecision.objects.get()
        self.assertEqual((d.decision, d.actor, d.comment), ('send_refused', l1, None))

    def test_marker_for_another_tickets_draft_is_not_trusted(self):
        other = make_ticket(self.a, assigned_to=self.tech, subject='Other')
        s = AISuggestion.objects.create(organization=self.a, native_ticket=other, kind='reply', model_name='m',
                                        confidence=Decimal('0.5'), suggested_body='x' * 80, requested_by=self.tech)
        self.c.post(f'/psa/t/{self.ticket.ticket_number}/comment/',
                    {'body': 'I rebooted the printer and it works.', 'is_internal': '1',
                     'ai_draft': f'suggestion:{s.pk}'})
        self.assertFalse(AIDraftDecision.objects.exists())

    def test_suggestion_review_trail_and_redacted_excerpt(self):
        s = AISuggestion.objects.create(
            organization=self.a, native_ticket=self.ticket, kind='action', action_type='set_priority',
            model_name='claude-x', prompt_version='1', confidence=Decimal('0.70'),
            suggested_body='Raise priority. Their password: hunter2 and mail pat@alpha.test',
            context_snapshot={'subject': 'SNAPSHOT-ONLY-TEXT'}, requested_by=self.tech,
            review_state='pending_review', requested_review_at=timezone.now(), requested_review_by=self.tech)
        [e] = self.entries(kind='ai_suggestion')
        self.assertIn(('Prompt version', '1 (legacy, no content hash)'), e['facts'])
        self.assertEqual(e['decisions'][0]['text'], 'Approval requested')
        self.assertIn('Awaiting approval', e['approval'])
        self.assertTrue(e['excerpt'])
        html = self.page().content.decode()
        panel = panel_of(html)
        for secret in ('hunter2', 'pat@alpha.test', 'SNAPSHOT-ONLY-TEXT'):
            self.assertNotIn(secret, panel)
        s.review_state, s.reviewer, s.reviewed_at, s.reviewer_note = 'rejected', self.tech, timezone.now(), 'wrong'
        s.save()
        [e] = self.entries(kind='ai_suggestion')
        self.assertEqual(e['decisions'][-1]['text'], 'Rejected — "wrong"')

    def test_never_shows_evidence_or_request_sent(self):
        job, _ = self.finished_job()
        html = self.page().content.decode()
        panel = panel_of(html)
        for secret in ('hunter2', 'pat@alpha.test', 'vault entry 42', job.evidence_digest,
                       job.processor_request['idempotency_key']):
            self.assertNotIn(secret, panel)


class ActionProposalHistoryTests(HistoryBase):
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

    def test_approval_requirement_expiry_and_observed_result(self):
        req, _ = rmm_actions.refer_fix(self.tech, self.ticket, self.device.pk, 'key-spooler-1',
                                       description='The Print Spooler service is stopped.',
                                       action_key='windows.service.start@1')
        req.refresh_from_db()
        self.assertEqual((req.approvals_required, req.customer_signoff), (1, False))
        self.assertIsNotNone(req.approval_expires_at)
        [e] = self.entries(kind='rmm_request')
        self.assertTrue(e['title'].startswith('Rem0te action proposal'))
        self.assertIn('1 approval(s) required', e['approval'])
        self.assertIn('never approves or runs anything', e['approval'])
        self.assertEqual(e['approval_expires_at'], req.approval_expires_at)
        self.assertTrue(e['link'].startswith('https://approve.example.com/'))
        p = next(iter(self.fake.proposals.values()))
        p.update(status='succeeded', outcome='succeeded', observed={'before': 'stopped', 'after10s': 'running'})
        actions.refresh(req, force=True)
        req.refresh_from_db()
        self.assertEqual((req.remote_outcome, req.observed), ('succeeded', {'before': 'stopped', 'after10s': 'running'}))
        [e] = self.entries(kind='rmm_request')
        self.assertIn(('RMM status', 'succeeded'), e['facts'])
        self.assertIn('Outcome: succeeded', e['outcome'])
        self.assertIn('after10s=running', e['outcome'])
        self.assertEqual(e['link'], '')  # no approval link once decided

    def test_rendering_history_never_calls_rem0te_or_the_rmm(self):
        rmm_actions.refer_fix(self.tech, self.ticket, self.device.pk, 'key-spooler-2',
                              description='The Print Spooler service is stopped.',
                              action_key='windows.service.start@1')
        self.finished_job()
        AIDraftDecision.objects.create(organization=self.a, ticket=self.ticket, source='rem0te', decision='sent',
                                       actor=self.tech)
        patchers = _no_remote_calls()
        mocks = [p.start() for p in patchers]
        try:
            calls_before = len(self.calls)
            fake_before = len(self.fake.calls)
            request = RequestFactory().get('/')
            request.user = self.tech
            html = Template('{% load ai_history %}{% ai_history_panel ticket %}').render(
                Context({'request': request, 'ticket': self.ticket}))
            self.assertIn(PANEL, html)
            history.record_draft_decision(self.ticket, self.tech, 'unrelated text that matches no draft at all')
            for m in mocks:
                m.assert_not_called()
            self.assertEqual(len(self.calls), calls_before)
            self.assertEqual(len(self.fake.calls), fake_before)
        finally:
            for p in patchers:
                p.stop()

    def test_full_ticket_page_sends_nothing_that_acts(self):
        rmm_actions.refer_fix(self.tech, self.ticket, self.device.pk, 'key-spooler-3',
                              description='The Print Spooler service is stopped.',
                              action_key='windows.service.start@1')
        before = len(self.fake.calls)
        with patch('psa_ai.services.rmm_actions.launch') as launch:
            self.assertEqual(self.page().status_code, 200)
        launch.assert_not_called()
        # The RMM panel may read an open proposal's status (GET); nothing is posted.
        new = self.fake.calls[before:]
        self.assertFalse([c for c in new if c[0] != 'GET'], new)
        self.assertFalse([c for c in new if 'launch' in c[1] or 'session' in c[1]], new)


class RoutingHistoryTests(HistoryBase):
    def test_routing_entry_and_routing_never_touches_remote_endpoints(self):
        from psa.models import Queue
        from psa.routing import service
        from psa.routing.models import RoutingDecision, RoutingSettings
        from psa.routing.review import summarize
        from psa.routing.views import publish
        from psa.routing.models import RoutingRule
        queue = Queue.objects.create(name='Printers', slug='printers') if not Queue.objects.filter(
            slug='printers').exists() else Queue.objects.get(slug='printers')
        msp = RoutingSettings.load()
        msp.mode = 'auto'
        msp.save()
        dest, fallback = {'type': 'queue', 'queue_id': queue.pk}, {'type': 'triage'}
        rule = RoutingRule()
        publish(rule, {'name': 'Printers', 'description': '', 'organization_id': self.a.pk, 'priority': 1,
                       'conditions': {}, 'destination': dest, 'fallback': fallback}, None,
                summarize(self.a, {}, dest, fallback))
        rule.is_active = True
        rule.save(update_fields=['is_active'])
        ticket = make_ticket(self.a, subject='Printer jam')
        patchers = _no_remote_calls()
        mocks = [p.start() for p in patchers]
        try:
            calls_before, fake_before = len(self.calls), len(self.fake.calls)
            decision = service.route(ticket.pk, 'created', 'created')
            self.assertIsNotNone(decision)
            for m in mocks:
                m.assert_not_called()
            self.assertEqual((len(self.calls), len(self.fake.calls)), (calls_before, fake_before))
            self.assertFalse(RMMRequest.objects.filter(ticket=ticket).exists())
            self.assertFalse(AnalysisJob.objects.filter(ticket=ticket).exists())
        finally:
            for p in patchers:
                p.stop()
        decision = RoutingDecision.objects.get(ticket=ticket)
        [e] = [x for x in history.build(ticket, self.tech)['entries'] if x['kind'] == 'routing']
        self.assertIn(decision.get_status_display(), e['title'])
        self.assertEqual(e['note'], history.ROUTING_ASSURANCE)
        self.assertIn('never started a remote session or authorized an endpoint action', e['note'])


class VisibilityTests(HistoryBase):
    def setUp(self):
        super().setUp()
        self.job, _ = self.finished_job()
        AISuggestion.objects.create(organization=self.a, native_ticket=self.ticket, kind='reply', model_name='m',
                                    confidence=Decimal('0.5'), requested_by=self.tech,
                                    suggested_body='We are looking into the printer and will update you soon.')

    def test_customer_user_and_portal_get_nothing(self):
        cust = User.objects.create_user('pat', 'pat@alpha.test', 'pw')
        Membership.objects.create(user=cust, organization=self.a, role=Role.READONLY, is_active=True)
        ClientPSASettings.objects.filter(organization=self.a).update(portal_enabled=True)
        self.ticket.client_can_view = True
        self.ticket.save()
        self.assertEqual(history.build(self.ticket, cust), {'show': False})
        c = Client()
        c.force_login(cust)
        s = c.session
        s['current_organization_id'] = self.a.pk
        s['2fa_prompted'] = True
        s.save()
        r = c.get(f'/portal/t/{self.ticket.ticket_number}/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertNotIn(PANEL, body)
        self.assertNotIn('AI and automation history', body)
        self.assertNotRegex(body, r'\.md@[0-9a-f]{12}')
        r = c.get(f'/psa/t/{self.ticket.ticket_number}/')
        self.assertNotIn(PANEL, r.content.decode())
        self.assertEqual(c.get(f'/psa/ai/assist/{self.ticket.ticket_number}/history/').status_code, 404)

    def test_other_customers_technician_is_refused(self):
        tech_b = make_tech('bea')
        grant(tech_b, self.b, 'l3')
        c = sign_in(tech_b, self.b)
        r = c.get(f'/psa/ai/assist/{self.ticket.ticket_number}/history/')
        self.assertIn(r.status_code, (403, 404))
        self.assertNotIn('entries', r.content.decode())
        self.assertEqual(history.build(self.ticket, tech_b), {'show': False})
        # PSA lets MSP staff open any ticket page; the history is not on it.
        r = self.page(client=c)
        self.assertNotIn(PANEL, r.content.decode())
        # The ticket's own technician gets the same entries as JSON.
        r = self.c.get(f'/psa/ai/assist/{self.ticket.ticket_number}/history/')
        self.assertEqual(r.status_code, 200)
        kinds = {e['kind'] for e in r.json()['entries']}
        self.assertEqual(kinds, {'ai_analysis', 'ai_suggestion'})

    def test_without_view_output_ai_entries_are_hidden(self):
        RMMRequest.objects.create(organization=self.a, ticket=self.ticket, connection=self.conn_a,
                                  device_external_id='dev-1', device_name='FRONTDESK-01', tenant_id='t',
                                  actor=self.tech, kind='handoff', payload={}, payload_digest='d',
                                  idempotency_key='k-handoff-1', status='sent')
        other = make_tech('sam')
        grant(other, self.a, 'l2')  # L2, but not this ticket's assignee: no ai_* here without review_others
        data = history.build(self.ticket, other)
        self.assertFalse(data['ai_visible'])
        self.assertEqual({e['kind'] for e in data['entries']}, {'rmm_request'})

    def test_ai_off_keeps_metadata_but_hides_ai_text(self):
        data = history.build(self.ticket, self.tech)
        self.assertTrue(data['ai_text'])
        self.assertTrue(any(e['excerpt'] for e in data['entries'] if e['ai']))
        AIBusinessPolicy.objects.filter(organization=self.a).update(analysis_enabled=False)
        data = history.build(self.ticket, self.tech)
        self.assertFalse(data['ai_text'])
        ai = [e for e in data['entries'] if e['ai']]
        self.assertEqual({e['kind'] for e in ai}, {'ai_analysis', 'ai_suggestion'})
        self.assertFalse(any(e['excerpt'] for e in ai))
        self.assertTrue(all(r['prompt_version'] for e in ai for r in e['runs']))
        html = self.page().content.decode()
        self.assertIn('AI is off for this customer', html)
        self.assertNotIn('We are looking into the printer', panel_of(html))
        from core.models import SystemSetting
        AIBusinessPolicy.objects.filter(organization=self.a).update(analysis_enabled=True)
        s = SystemSetting.get_settings()
        s.psa_ai_enabled = False
        s.save()
        self.assertFalse(history.build(self.ticket, self.tech)['ai_text'])


class RetentionTests(HistoryBase):
    def _age(self, model, pk, days):
        model.objects.filter(pk=pk).update(created_at=timezone.now() - timedelta(days=days))

    def test_purge_respects_customer_window_and_keeps_open_and_routing_rows(self):
        from psa.routing.models import RoutingDecision
        job, _ = self.finished_job()
        old_s = AISuggestion.objects.create(organization=self.a, native_ticket=self.ticket, kind='reply',
                                            model_name='m', confidence=Decimal('0.5'), suggested_body='old')
        pending = AISuggestion.objects.create(organization=self.a, native_ticket=self.ticket, kind='action',
                                              model_name='m', confidence=Decimal('0.5'),
                                              review_state='pending_review')
        open_job = AnalysisJob.objects.create(
            organization=self.a, ticket=self.ticket, ticket_revision='r', actor=self.tech, kind='analyze',
            connection=self.conn_a, business_id='b', evidence={}, evidence_digest='e', payload_digest='p',
            idempotency_key='open-1', expires_at=timezone.now() + timedelta(hours=1), status='running')
        req = RMMRequest.objects.create(organization=self.a, ticket=self.ticket, connection=self.conn_a,
                                        device_external_id='d', tenant_id='t', actor=self.tech, kind='handoff',
                                        payload={}, payload_digest='d', idempotency_key='k-old', status='sent')
        dec = AIDraftDecision.objects.create(organization=self.a, ticket=self.ticket, source='rem0te', job=job,
                                             decision='sent', actor=self.tech)
        routing = RoutingDecision.objects.create(ticket=self.ticket, trigger='manual', idempotency_key='old',
                                                 status='override')
        recent = AISuggestion.objects.create(organization=self.a, native_ticket=self.ticket, kind='reply',
                                             model_name='m', confidence=Decimal('0.5'), suggested_body='recent')
        for model, pk in ((AISuggestion, old_s.pk), (AISuggestion, pending.pk), (AnalysisJob, job.pk),
                          (AnalysisJob, open_job.pk), (RMMRequest, req.pk), (AIDraftDecision, dec.pk),
                          (RoutingDecision, routing.pk)):
            self._age(model, pk, 40)
        AIBusinessPolicy.objects.filter(organization=self.a).update(history_retention_days=30)
        # Before the purge runs, old entries are already out of the timeline.
        kinds = [e['kind'] for e in history.build(self.ticket, self.tech)['entries']]
        self.assertNotIn('routing', kinds)
        self.assertNotIn('rmm_request', kinds)
        counts = history.purge_expired()
        self.assertEqual(counts, {'suggestions': 1, 'analysis_jobs': 1, 'rmm_requests': 1, 'draft_decisions': 1})
        self.assertEqual(set(AISuggestion.objects.values_list('pk', flat=True)), {pending.pk, recent.pk})
        self.assertEqual(list(AnalysisJob.objects.values_list('pk', flat=True)), [open_job.pk])
        self.assertFalse(AnalysisRun.objects.filter(job_id=job.pk).exists())
        self.assertTrue(RoutingDecision.objects.filter(pk=routing.pk).exists())
        # Customer B keeps the default window: nothing of A's rules applies there.
        self.assertEqual(history.retention_days(self.b), 365)

    @override_settings(PSA_AI_HISTORY_RETENTION_DAYS=0)
    def test_zero_keeps_everything(self):
        s = AISuggestion.objects.create(organization=self.b, kind='reply', model_name='m',
                                        confidence=Decimal('0.5'), suggested_body='x')
        self._age(AISuggestion, s.pk, 4000)
        self.assertEqual(history.purge_expired()['suggestions'], 0)
        self.assertTrue(AISuggestion.objects.filter(pk=s.pk).exists())

    def test_scheduled_task_purges_at_most_every_six_hours(self):
        s = AISuggestion.objects.create(organization=self.a, native_ticket=self.ticket, kind='reply',
                                        model_name='m', confidence=Decimal('0.5'), suggested_body='x')
        self._age(AISuggestion, s.pk, 400)
        with patch('psa_ai.management.commands.poll_analysis_jobs.Command._refresh_capabilities'), \
                patch('psa_ai.management.commands.poll_analysis_jobs.Command._rem0te'):
            call_command('poll_analysis_jobs', stdout=open('/dev/null', 'w'))
            self.assertFalse(AISuggestion.objects.filter(pk=s.pk).exists())
            state = AIHistoryPurgeState.objects.get(pk=1)
            self.assertEqual(state.last_deleted['suggestions'], 1)
            s2 = AISuggestion.objects.create(organization=self.a, native_ticket=self.ticket, kind='reply',
                                             model_name='m', confidence=Decimal('0.5'), suggested_body='y')
            self._age(AISuggestion, s2.pk, 400)
            self.assertIsNone(history.purge_if_due())
            self.assertTrue(AISuggestion.objects.filter(pk=s2.pk).exists())
            self.assertIsNotNone(history.purge_if_due(now=timezone.now() + timedelta(hours=7)))
            self.assertFalse(AISuggestion.objects.filter(pk=s2.pk).exists())

    def test_policy_form_sets_the_window(self):
        admin = make_tech('root', superuser=True)
        c = sign_in(admin, self.a)
        pol = AIBusinessPolicy.objects.get(organization=self.a)
        r = c.post(f'/psa/ai/profiles/policy/{self.a.pk}/', {
            'analysis_enabled': 'on', 'daily_budget_cents': '500', 'history_retention_days': '90',
            'allowed_profiles': [self.cheap.pk]})
        self.assertIn(r.status_code, (200, 302))
        pol.refresh_from_db()
        self.assertEqual(pol.history_retention_days, 90)
        self.assertEqual(history.retention_days(self.a), 90)
