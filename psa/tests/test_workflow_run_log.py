"""Roadmap 91.2: every workflow rule firing is recorded with its trigger, rule
version, each action's result, actor and duration, and shown on the rule page
(scoped to the tickets the viewer can see)."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import RoleTemplate
from core.models import Organization
from psa import workflow_engine, workflow_runs
from psa.models import (Queue, Ticket, TicketPriority, TicketStatus, TicketType, WorkflowRule,
                        WorkflowRuleRun)
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_global, _make_msp_tech, _setup_seed


def _ticket(org, subject='T'):
    return Ticket.objects.create(
        organization=org, subject=subject, queue=Queue.objects.first(),
        priority=TicketPriority.objects.first(), ticket_type=TicketType.objects.first(),
        status=TicketStatus.objects.filter(slug='new').first())


def _touch(ticket):
    ticket.refresh_from_db()
    ticket.subject = ticket.subject + '.'
    ticket.save()


class WorkflowRunRecordingTests(TestCase):
    def setUp(self):
        _setup_seed()
        self.org = Organization.objects.create(name='Run A', slug='wfrun-a')
        self.ticket = _ticket(self.org)

    def _rule(self, actions, **kw):
        defaults = dict(name='Logger', trigger='ticket_updated', conditions={}, is_active=True,
                        actions=actions)
        defaults.update(kw)
        return WorkflowRule.objects.create(**defaults)

    def test_firing_records_run_with_action_results(self):
        rule = self._rule([{'type': 'add_tag', 'tag': 'vip'},
                           {'type': 'add_internal_note', 'body': 'flagged'}])
        _touch(self.ticket)
        runs = list(WorkflowRuleRun.objects.filter(rule=rule))
        self.assertEqual(len(runs), 1)
        run = runs[0]
        self.assertEqual(run.outcome, 'ok')
        self.assertEqual(run.trigger, 'ticket_updated')
        self.assertEqual(run.ticket_id, self.ticket.pk)
        self.assertEqual(run.organization_id, self.org.pk)
        self.assertEqual(run.rule_name, 'Logger')
        self.assertEqual(run.rule_fingerprint, workflow_runs.fingerprint(rule))
        self.assertEqual(run.actor_label, 'system')
        self.assertIsNotNone(run.finished_at)
        self.assertEqual([a['type'] for a in run.actions], ['add_tag', 'add_internal_note'])
        self.assertEqual({a['result'] for a in run.actions}, {'ok'})
        self.assertIn('tag=vip', run.actions[0]['summary'])
        # add_tag saved the ticket, re-firing ticket_updated: the re-entry was
        # prevented and counted on this run, not logged as a separate run.
        self.assertGreaterEqual(run.reentry_blocked, 1)

    def test_fingerprint_changes_with_definition(self):
        rule = self._rule([{'type': 'add_tag', 'tag': 'a'}])
        before = workflow_runs.fingerprint(rule)
        rule.actions = [{'type': 'add_tag', 'tag': 'b'}]
        self.assertNotEqual(before, workflow_runs.fingerprint(rule))

    def test_error_in_action_recorded(self):
        rule = self._rule([{'type': 'add_tag', 'tag': 'x'}, {'type': 'no_such_action'},
                           {'type': 'add_tag', 'tag': 'y'}])
        _touch(self.ticket)
        run = WorkflowRuleRun.objects.get(rule=rule)
        self.assertEqual(run.outcome, 'error')
        self.assertIn('Unknown action type', run.message)
        self.assertEqual([a['result'] for a in run.actions], ['ok', 'error', 'skip'])

    def test_refused_step_is_partial(self):
        rule = self._rule([{'type': 'create_charge', 'amount': '10'}])
        _touch(self.ticket)
        _touch(self.ticket)  # second time: already charged -> refused
        runs = list(WorkflowRuleRun.objects.filter(rule=rule).order_by('id'))
        self.assertEqual([r.outcome for r in runs], ['ok', 'partial'])
        self.assertEqual(runs[1].actions[0]['result'], 'refused')
        self.assertIn('already charged', runs[1].actions[0]['message'])

    def test_budget_exceeded_recorded(self):
        n = workflow_engine.MAX_ACTIONS_PER_EVENT + 5
        rule = self._rule([{'type': 'add_tag', 'tag': f't{i}'} for i in range(n)])
        _touch(self.ticket)
        run = WorkflowRuleRun.objects.get(rule=rule)
        self.assertEqual(run.outcome, 'budget')
        results = [a['result'] for a in run.actions]
        self.assertEqual(results.count('ok'), workflow_engine.MAX_ACTIONS_PER_EVENT)
        self.assertEqual(results.count('error'), 1)

    def test_loop_guard_recorded(self):
        # B chains back into A, which is still running: refused as a loop.
        WorkflowRule.objects.create(name='B', trigger='comment_added', conditions={}, is_active=True,
                                    actions=[{'type': 'fire_rule', 'name': 'A'}])
        a = WorkflowRule.objects.create(name='A', trigger='ticket_updated', conditions={}, is_active=True,
                                        actions=[{'type': 'fire_rule', 'name': 'B'}])
        _touch(self.ticket)
        run = WorkflowRuleRun.objects.get(rule=a)
        self.assertEqual(run.outcome, 'loop_guard')
        self.assertIn('loop', run.message)
        # The chained step is in the same run, one level deeper.
        self.assertEqual([(s['type'], s['depth']) for s in run.actions],
                         [('fire_rule', 0), ('fire_rule', 1)])

    def test_logging_failure_does_not_break_event(self):
        rule = self._rule([{'type': 'add_tag', 'tag': 'still'}])
        with mock.patch.object(WorkflowRuleRun.objects, 'create', side_effect=RuntimeError('db down')):
            _touch(self.ticket)
        self.ticket.refresh_from_db()
        self.assertIn('still', self.ticket.tags)
        rule.refresh_from_db()
        self.assertEqual(rule.fire_count, 1)
        self.assertEqual(rule.last_error, '')
        self.assertFalse(WorkflowRuleRun.objects.exists())
        # The recorder stack is left clean for the next event.
        self.assertEqual(workflow_runs._stack(), [])

    def test_summary_drops_secret_like_settings(self):
        s = workflow_runs.summarize({'type': 'x', 'api_key': 'abc', 'password': 'p', 'tag': 'ok'})
        self.assertEqual(s, 'tag=ok')

    def test_actor_from_request_context(self):
        from types import SimpleNamespace
        from accounts import authz_cache
        user = User.objects.create_user('wfrun-actor', 'a@msp.example', 'pw')
        req = SimpleNamespace(user=user, session={}, META={})
        rule = self._rule([{'type': 'add_tag', 'tag': 'z'}])
        with mock.patch.object(authz_cache, 'current_context',
                               return_value=SimpleNamespace(user_id=user.pk, request=req)):
            _touch(self.ticket)
        run = WorkflowRuleRun.objects.get(rule=rule)
        self.assertEqual(run.actor_id, user.pk)
        self.assertEqual(run.actor_label, 'user')


class WorkflowRunRetentionTests(TestCase):
    def setUp(self):
        _setup_seed()
        self.org = Organization.objects.create(name='Ret', slug='wfrun-ret')
        self.rule = WorkflowRule.objects.create(name='R', trigger='ticket_updated', conditions={},
                                                is_active=False, actions=[])

    def _run(self, age_days=0):
        return WorkflowRuleRun.objects.create(rule=self.rule, rule_name='R', organization=self.org,
                                              started_at=timezone.now() - timedelta(days=age_days))

    def test_prunes_old_runs(self):
        old = self._run(age_days=40)
        new = self._run(age_days=1)
        removed = workflow_runs.prune(days=30, per_rule=0)
        self.assertEqual(removed, 1)
        self.assertFalse(WorkflowRuleRun.objects.filter(pk=old.pk).exists())
        self.assertTrue(WorkflowRuleRun.objects.filter(pk=new.pk).exists())

    def test_caps_runs_per_rule(self):
        ids = [self._run(age_days=i).pk for i in range(6)]
        workflow_runs.prune(days=0, per_rule=4)
        self.assertEqual(set(WorkflowRuleRun.objects.values_list('pk', flat=True)), set(ids[:4]))

    def test_defaults(self):
        self.assertEqual(workflow_runs.DEFAULT_RETENTION_DAYS, 30)
        self.assertEqual(workflow_runs.DEFAULT_RUNS_PER_RULE, 500)
        self._run(age_days=31)
        self.assertEqual(workflow_runs.prune(), 1)


def _login(user):
    c = Client()
    c.force_login(user)
    s = c.session
    s['2fa_prompted'] = True
    s.save()
    return c


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WorkflowRunPageTests(TestCase):
    def setUp(self):
        _setup_seed()
        _enable_psa_global()
        self.a = Organization.objects.create(name='Cust A', slug='wfrun-pa')
        self.b = Organization.objects.create(name='Cust B', slug='wfrun-pb')
        self.rule_all = WorkflowRule.objects.create(name='Everyone', trigger='ticket_updated',
                                                    conditions={}, is_active=True,
                                                    actions=[{'type': 'add_tag', 'tag': 'seen'}])
        self.ta = _ticket(self.a, 'Ticket in A')
        self.tb = _ticket(self.b, 'Ticket in B')
        _touch(self.ta)
        _touch(self.tb)
        self.ta.refresh_from_db()
        self.tb.refresh_from_db()

        role = RoleTemplate.objects.create(name='WF run viewer', psa_manage_workflow_rules=True,
                                           tickets_view=True)
        self.tech = User.objects.create_user('wfrun-tech', 'wfrun@msp.example', 'pw')
        _make_msp_tech(self.tech)
        p = self.tech.profile
        p.global_role_template = role
        p.client_scope = 'selected'
        p.save()
        p.scope_organizations.set([self.a])
        self.admin = User.objects.create_superuser('wfrun-admin', 'adm@msp.example', 'pw')

    def test_admin_sees_all_runs_with_steps(self):
        self.assertEqual(WorkflowRuleRun.objects.filter(rule=self.rule_all).count(), 2)
        resp = _login(self.admin).get(f'/psa/rules/{self.rule_all.pk}/flow/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['runs']), 2)
        self.assertContains(resp, self.ta.ticket_number)
        self.assertContains(resp, self.tb.ticket_number)
        self.assertContains(resp, 'tag=seen')

    def test_restricted_tech_sees_only_runs_on_their_customers(self):
        resp = _login(self.tech).get(f'/psa/rules/{self.rule_all.pk}/flow/')
        self.assertEqual(resp.status_code, 200)
        runs = resp.context['runs']
        self.assertEqual([r.ticket_id for r in runs], [self.ta.pk])
        self.assertContains(resp, self.ta.ticket_number)
        self.assertNotContains(resp, self.tb.ticket_number)

    def test_flow_map_has_no_runs(self):
        resp = _login(self.admin).get('/psa/rules/flow/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['runs'], [])
