"""Roadmap 91.3: dry-run a workflow rule against a chosen ticket - condition
details, planned actions with resolved settings, and no side effects."""
import socket
import urllib.request
from contextlib import ExitStack
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from accounts.models import RoleTemplate
from audit.models import AuditLog
from core.models import Organization
from psa import workflow_dry_run, workflow_engine
from psa.models import (Charge, Queue, Ticket, TicketComment, TicketPriority, TicketStatus,
                        TicketTimeEntry, TicketType, TicketWatcher, WorkflowCharge, WorkflowRule,
                        WorkflowRuleFiring, WorkflowRuleRun)
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_global, _make_msp_tech, _setup_seed


def _ticket(org, subject='Printer down'):
    return Ticket.objects.create(
        organization=org, subject=subject, queue=Queue.objects.first(),
        priority=TicketPriority.objects.order_by('sort_order').last(), ticket_type=TicketType.objects.first(),
        status=TicketStatus.objects.filter(slug='new').first())


def _rule(name, org=None, actions=None, **kw):
    kw.setdefault('conditions', {})
    return WorkflowRule.objects.create(name=name, trigger=kw.pop('trigger', 'ticket_updated'),
                                       organization=org, actions=actions or [], is_active=True, **kw)


def _login(user):
    c = Client()
    c.force_login(user)
    s = c.session
    s['2fa_prompted'] = True
    s.save()
    return c


def _snapshot(ticket, *rules):
    ticket = Ticket.objects.get(pk=ticket.pk)
    counts = {m.__name__: m.objects.count() for m in (
        Ticket, Charge, TicketTimeEntry, TicketComment, TicketWatcher, WorkflowRuleRun,
        WorkflowCharge, WorkflowRuleFiring)}
    fields = (ticket.priority_id, ticket.queue_id, ticket.assigned_to_id, list(ticket.tags or []),
              ticket.updated_at, ticket.status_id)
    rule_state = [tuple(WorkflowRule.objects.filter(pk=r.pk).values_list(
        'fire_count', 'last_error', 'last_fired_at')[0]) for r in rules]
    return counts, fields, rule_state


def _no_network():
    """Context that fails the test on any outbound HTTP / socket use."""
    stack = ExitStack()
    boom = AssertionError('outbound network call during a dry run')
    stack.enter_context(mock.patch.object(urllib.request, 'urlopen', side_effect=boom))
    stack.enter_context(mock.patch.object(socket, 'create_connection', side_effect=boom))
    try:
        import requests
        stack.enter_context(mock.patch.object(requests.Session, 'request', side_effect=boom))
    except ImportError:
        pass
    return stack


class DryRunPlanTests(TestCase):
    def setUp(self):
        _setup_seed()
        self.org = Organization.objects.create(name='Dry A', slug='dry-a')
        self.ticket = _ticket(self.org)
        self.p1 = TicketPriority.objects.order_by('sort_order').first()
        self.tech = User.objects.create_user('jdoe', 'jdoe@msp.example', 'pw', is_staff=True)
        _make_msp_tech(self.tech)

    def _run(self, rule, ticket=None, user=None):
        return workflow_dry_run.dry_run(rule, ticket or self.ticket, rule.trigger, user=user)

    def test_match_lists_each_condition_with_actual_value(self):
        rule = _rule('Printers', conditions={'subject_contains': 'printer', 'is_unassigned': True},
                     actions=[{'type': 'add_tag', 'tag': 'hw'}])
        res = self._run(rule)
        self.assertTrue(res['matched'])
        self.assertTrue(res['would_run'])
        leaves = res['conditions']['children']
        self.assertEqual([c['passed'] for c in leaves], [True, True])
        self.assertEqual(leaves[0]['actual'], 'Printer down')
        self.assertEqual(leaves[1]['actual'], 'yes')

    def test_no_match_shows_failing_condition(self):
        rule = _rule('P1 only', conditions={'priority': self.p1.code},
                     actions=[{'type': 'add_tag', 'tag': 'urgent'}])
        res = self._run(rule)
        self.assertFalse(res['matched'])
        self.assertFalse(res['would_run'])
        self.assertFalse(res['conditions']['passed'])
        self.assertEqual(res['conditions']['expected'], self.p1.code)
        self.assertEqual(res['conditions']['actual'], self.ticket.priority.code)
        self.assertEqual(res['steps'], [])

    def test_else_branch_and_any_combinator(self):
        rule = _rule('Either', conditions={'any': [{'priority': self.p1.code}, {'subject_contains': 'nope'}]},
                     actions=[{'type': 'add_tag', 'tag': 'then'}],
                     else_actions=[{'type': 'add_tag', 'tag': 'else'}])
        res = self._run(rule)
        self.assertEqual(res['branch'], 'else')
        self.assertEqual(res['conditions']['label'], 'Any of')
        self.assertEqual(len(res['conditions']['children']), 2)
        self.assertIn("'else'", res['steps'][0]['message'])

    def test_actions_listed_in_order_with_resolved_params(self):
        rule = _rule('Triage', actions=[
            {'type': 'set_priority', 'code': self.p1.code},
            {'type': 'assign_to', 'username': 'jdoe'},
            {'type': 'add_internal_note', 'body': 'Escalated by rule'},
            {'type': 'add_tag', 'tag': 'vip'},
        ])
        res = self._run(rule)
        self.assertEqual([s['type'] for s in res['steps']],
                         ['set_priority', 'assign_to', 'add_internal_note', 'add_tag'])
        self.assertEqual({s['status'] for s in res['steps']}, {'would'})
        self.assertIn(f'would set priority to {self.p1.code}', res['steps'][0]['message'])
        self.assertIn('would assign to jdoe', res['steps'][1]['message'])
        self.assertIn('Escalated by rule', res['steps'][2]['message'])
        self.assertEqual(res['steps'][1]['params'], 'username=jdoe')

    def test_chained_rule_sees_planned_changes_and_is_expanded(self):
        _rule('Child', conditions={'priority': self.p1.code}, actions=[{'type': 'add_tag', 'tag': 'from-child'}])
        rule = _rule('Parent', actions=[{'type': 'set_priority', 'code': self.p1.code},
                                        {'type': 'fire_rule', 'name': 'Child'}])
        res = self._run(rule)
        self.assertEqual([(s['type'], s['depth']) for s in res['steps']],
                         [('set_priority', 0), ('fire_rule', 0), ('add_tag', 1)])
        self.assertIn('would run rule "Child"', res['steps'][1]['message'])
        self.assertTrue(res['steps'][1]['conditions']['passed'])

    def test_no_side_effects_at_all(self):
        WorkflowCharge.objects.create(rule=_rule('Other'), ticket=self.ticket)  # unrelated key
        _rule('Child', actions=[{'type': 'add_watcher', 'username': 'jdoe'}])
        rule = _rule('Everything', fire_once_per_ticket=True, actions=[
            {'type': 'set_priority', 'code': self.p1.code},
            {'type': 'set_queue', 'name': Queue.objects.first().name},
            {'type': 'assign_to', 'username': 'jdoe'},
            {'type': 'add_watcher', 'username': 'jdoe'},
            {'type': 'add_internal_note', 'body': 'note'},
            {'type': 'add_tag', 'tag': 'x'},
            {'type': 'assign_round_robin'},
            {'type': 'assign_load_balanced'},
            {'type': 'create_charge', 'amount': '40.00'},
            {'type': 'fire_rule', 'name': 'Child'},
        ])
        before = _snapshot(self.ticket, rule)
        mail.outbox = []
        with _no_network(), CaptureQueriesContext(connection) as ctx:
            res = self._run(rule, ticket=Ticket.objects.get(pk=self.ticket.pk))
        writes = [q['sql'] for q in ctx.captured_queries
                  if q['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))]
        self.assertEqual(writes, [])
        self.assertEqual(_snapshot(self.ticket, rule), before)
        self.assertEqual(mail.outbox, [])
        self.assertEqual(len(res['steps']), 11)
        self.assertNotIn('error', {s['status'] for s in res['steps']})
        self.assertIn('would add charge 40.00 USD', res['steps'][8]['message'])

    def test_engine_refuses_to_run_actions_during_a_dry_run(self):
        with workflow_dry_run._dry_run_flag():
            with self.assertRaises(workflow_engine.DryRunViolation):
                workflow_engine.run_action(self.ticket, {'type': 'add_tag', 'tag': 'x'})
            self.assertEqual(workflow_engine.fire('ticket_updated', self.ticket), 0)
        self.assertFalse(workflow_engine.in_dry_run())

    def test_working_copy_cannot_be_saved(self):
        sim = workflow_dry_run._working_copy(self.ticket)
        with self.assertRaises(workflow_dry_run._ReadOnlyTicket):
            sim.save()

    def test_charge_once_shows_already_charged(self):
        rule = _rule('Bill', actions=[{'type': 'create_charge', 'amount': '125.00'},
                                      {'type': 'add_tag', 'tag': 'billed'}])
        WorkflowCharge.objects.create(rule=rule, ticket=self.ticket)
        res = self._run(rule)
        self.assertEqual(res['steps'][0]['status'], 'skipped')
        self.assertIn('already charged once', res['steps'][0]['message'])
        self.assertIn('125.00', res['steps'][0]['message'])
        self.assertEqual(res['steps'][1]['status'], 'would')  # the rule carries on

    def test_loop_is_refused_like_the_engine(self):
        _rule('Ping', actions=[{'type': 'fire_rule', 'name': 'Pong'}])
        _rule('Pong', actions=[{'type': 'fire_rule', 'name': 'Ping'}, {'type': 'add_tag', 'tag': 'x'}])
        res = self._run(WorkflowRule.objects.get(name='Ping'))
        statuses = [(s['type'], s['depth'], s['status']) for s in res['steps']]
        self.assertEqual(statuses, [('fire_rule', 0, 'would'), ('fire_rule', 1, 'error'),
                                    ('add_tag', 1, 'not_run')])
        self.assertIn('loop', res['stopped'])

    def test_chain_depth_limit(self):
        n = workflow_engine.MAX_CHAIN_DEPTH + 2
        for i in range(n):
            _rule(f'R{i}', actions=[{'type': 'fire_rule', 'name': f'R{i + 1}'}] if i < n - 1 else
                  [{'type': 'add_tag', 'tag': 'deep'}])
        res = self._run(WorkflowRule.objects.get(name='R0'))
        self.assertIn(f'deeper than {workflow_engine.MAX_CHAIN_DEPTH}', res['stopped'])
        self.assertEqual(max(s['depth'] for s in res['steps']), workflow_engine.MAX_CHAIN_DEPTH - 1)
        self.assertNotIn('deep', [s['params'] for s in res['steps']])

    def test_action_budget(self):
        limit = workflow_engine.MAX_ACTIONS_PER_EVENT
        _rule('Many', actions=[{'type': 'add_tag', 'tag': f'c{i}'} for i in range(limit)])
        rule = _rule('Top', actions=[{'type': 'fire_rule', 'name': 'Many'}, {'type': 'add_tag', 'tag': 'last'}])
        res = self._run(rule)
        planned = [s for s in res['steps'] if s['status'] != 'not_run']
        self.assertEqual(len(planned), limit)
        self.assertEqual([s['status'] for s in res['steps'][limit:]], ['not_run', 'not_run'])
        self.assertIn(f'more than {limit}', res['stopped'])

    def test_unknown_action_cannot_be_previewed_and_is_not_run(self):
        rule = _rule('Odd', actions=[{'type': 'send_sms', 'to': '+15550100'}, {'type': 'add_tag', 'tag': 'after'}])
        with mock.patch.object(workflow_engine, '_run_action', side_effect=AssertionError('executed')), \
                mock.patch.object(workflow_engine, 'run_action', side_effect=AssertionError('executed')):
            res = self._run(rule)
        self.assertEqual(res['steps'][0]['status'], 'cannot')
        self.assertIn('cannot preview', res['steps'][0]['message'])
        self.assertEqual(res['steps'][1]['status'], 'would')

    def test_assignment_refusal_is_reported(self):
        outsider = User.objects.create_user('cust', 'c@cust.example', 'pw')  # not MSP staff
        rule = _rule('Bad assign', actions=[{'type': 'assign_to', 'username': 'cust'}])
        res = self._run(rule)
        self.assertEqual(res['steps'][0]['status'], 'skipped')
        self.assertIn('not an MSP technician', res['steps'][0]['message'])
        self.assertTrue(outsider.pk)

    def test_blockers(self):
        other = Organization.objects.create(name='Dry B', slug='dry-b')
        rule = _rule('Elsewhere', org=other, actions=[{'type': 'add_tag', 'tag': 'x'}], fire_once_per_ticket=True)
        rule.is_active = False
        rule.save()
        WorkflowRuleFiring.objects.create(rule=rule, ticket=self.ticket)
        res = self._run(rule)
        self.assertFalse(res['would_run'])
        text = ' '.join(res['blockers'])
        self.assertIn('inactive', text)
        self.assertIn('only runs on Dry B', text)
        self.assertIn('once per ticket', text)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DryRunViewTests(TestCase):
    def setUp(self):
        _setup_seed()
        _enable_psa_global()
        self.a = Organization.objects.create(name='Cust A', slug='drv-a')
        self.b = Organization.objects.create(name='Cust B', slug='drv-b')
        self.ticket_a = _ticket(self.a, 'A printer')
        self.ticket_b = _ticket(self.b, 'B printer')
        self.role = RoleTemplate.objects.create(name='WF manager', psa_manage_workflow_rules=True,
                                                tickets_view=True)
        self.tech = User.objects.create_user('drv-tech', 'drv@msp.example', 'pw')
        _make_msp_tech(self.tech)
        p = self.tech.profile
        p.global_role_template = self.role
        p.client_scope = 'selected'
        p.save()
        p.scope_organizations.set([self.a])
        self.admin = User.objects.create_superuser('drv-admin', 'adm@msp.example', 'pw')
        self.rule_all = _rule('Tag all', actions=[{'type': 'add_tag', 'tag': 'seen'}])
        self.rule_b = _rule('Rule B', org=self.b, actions=[{'type': 'add_tag', 'tag': 'b'}])

    def _post(self, user, rule, ticket):
        return _login(user).post(f'/psa/rules/{rule.pk}/dry-run/',
                                 {'ticket': ticket.ticket_number, 'trigger': rule.trigger})

    def test_dry_run_page_and_result(self):
        c = _login(self.admin)
        self.assertEqual(c.get(f'/psa/rules/{self.rule_all.pk}/dry-run/').status_code, 200)
        flow = c.get(f'/psa/rules/{self.rule_all.pk}/flow/')
        self.assertContains(flow, f'/psa/rules/{self.rule_all.pk}/dry-run/')
        search = c.get(f'/psa/rules/{self.rule_all.pk}/dry-run/', {'q': 'printer'})
        self.assertContains(search, self.ticket_a.ticket_number)
        before = _snapshot(self.ticket_a, self.rule_all)
        mail.outbox = []
        with _no_network():
            resp = self._post(self.admin, self.rule_all, self.ticket_a)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "would add tag &#x27;seen&#x27;")
        self.assertEqual(_snapshot(self.ticket_a, self.rule_all), before)
        self.assertEqual(mail.outbox, [])
        log = AuditLog.objects.filter(object_type='psa.WorkflowRule', object_id=self.rule_all.pk).last()
        self.assertTrue(log.extra_data.get('dry_run'))

    def test_get_with_ticket_does_not_run(self):
        resp = _login(self.admin).get(f'/psa/rules/{self.rule_all.pk}/dry-run/',
                                      {'ticket': self.ticket_a.ticket_number})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context['result'])

    def test_wrong_trigger_rejected(self):
        resp = _login(self.admin).post(f'/psa/rules/{self.rule_all.pk}/dry-run/',
                                       {'ticket': self.ticket_a.ticket_number, 'trigger': 'comment_added'})
        self.assertEqual(resp.status_code, 400)

    def test_restricted_tech_in_scope(self):
        resp = self._post(self.tech, self.rule_all, self.ticket_a)
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(resp.context['result'])

    def test_restricted_tech_cannot_use_other_customers_ticket(self):
        before = AuditLog.objects.filter(object_type='psa.WorkflowRule').count()
        self.assertEqual(self._post(self.tech, self.rule_all, self.ticket_b).status_code, 404)
        search = _login(self.tech).get(f'/psa/rules/{self.rule_all.pk}/dry-run/', {'q': 'printer'})
        self.assertContains(search, self.ticket_a.ticket_number)
        self.assertNotContains(search, self.ticket_b.ticket_number)
        self.assertEqual(AuditLog.objects.filter(object_type='psa.WorkflowRule').count(), before)

    def test_restricted_tech_cannot_dry_run_other_customers_rule(self):
        self.assertEqual(_login(self.tech).get(f'/psa/rules/{self.rule_b.pk}/dry-run/').status_code, 404)
        self.assertEqual(self._post(self.tech, self.rule_b, self.ticket_b).status_code, 404)

    def test_other_customers_chained_rule_is_not_revealed(self):
        _rule('Secret B', org=self.b, actions=[{'type': 'add_tag', 'tag': 'b-only-secret'}])
        parent = _rule('Fan out', actions=[{'type': 'fire_rule', 'name': 'Secret B'}])
        resp = self._post(self.tech, parent, self.ticket_a)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'b-only-secret')
        # The lookup is limited to the ticket's customer and MSP-wide rules,
        # so customer B's rule is not found, let alone expanded.
        steps = resp.context['result']['steps']
        self.assertEqual([(s['type'], s['status']) for s in steps], [('fire_rule', 'error')])
        self.assertNotIn('rule', steps[0])

    def test_needs_permission_at_ticket_customer(self):
        no_perm = RoleTemplate.objects.create(name='Viewer', tickets_view=True)
        self.tech.profile.global_role_template = no_perm
        self.tech.profile.save()
        self.assertEqual(self._post(self.tech, self.rule_all, self.ticket_a).status_code, 403)

    def test_customer_user_refused(self):
        cust = User.objects.create_user('drv-cust', 'c@a.example', 'pw')
        self.assertEqual(self._post(cust, self.rule_all, self.ticket_a).status_code, 403)
