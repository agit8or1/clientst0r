"""Phase 14 — visual workflow builder: branches, chained rules, flow view,
save-time validation and the engine's loop guard."""
import json

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from core.models import Organization, SystemSetting
from psa import workflow_graph
from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType, WorkflowRule
from psa.tests._base import TEST_MIDDLEWARE, _setup_seed


def _rule(name, actions=None, else_actions=None, conditions=None, **kw):
    return WorkflowRule.objects.create(name=name, trigger=kw.pop('trigger', 'ticket_created'),
                                       conditions=conditions or {}, actions=actions or [],
                                       else_actions=else_actions or [], is_active=True, **kw)


class WorkflowGraphTests(TestCase):
    def test_flow_includes_chained_rule_branches(self):
        _rule('Child', conditions={'priority': 'P1'}, actions=[{'type': 'add_tag', 'tag': 'urgent'}],
              else_actions=[{'type': 'add_tag', 'tag': 'normal'}])
        parent = _rule('Parent', actions=[{'type': 'fire_rule', 'name': 'Child'}],
                       else_actions=[{'type': 'add_internal_note', 'body': 'n'}])
        flow = workflow_graph.build_flow(parent)
        self.assertEqual(flow['conditions'], ['Always'])
        step = flow['then'][0]
        self.assertEqual(step['type'], 'fire_rule')
        self.assertEqual(step['sub']['rule'].name, 'Child')
        self.assertEqual(step['sub']['conditions'], ['Priority = P1'])
        self.assertEqual([s['label'] for s in step['sub']['else']], ['Add tag: normal'])
        self.assertEqual(workflow_graph.problems(flow), [])

    def test_flow_flags_missing_target_and_loop(self):
        _rule('A', actions=[{'type': 'fire_rule', 'name': 'B'}])
        b = _rule('B', actions=[{'type': 'fire_rule', 'name': 'A'}, {'type': 'fire_rule', 'name': 'Nope'}])
        probs = workflow_graph.problems(workflow_graph.build_flow(b))
        self.assertTrue(any('loops back to "B"' in p for p in probs), probs)
        self.assertTrue(any('no active rule named "Nope"' in p for p in probs), probs)

    def test_validate_rejects_unknown_types_missing_settings_and_loops(self):
        self.assertTrue(workflow_graph.validate('X', {}, [{'type': 'explode'}], []))
        self.assertTrue(workflow_graph.validate('X', {}, [{'type': 'set_priority'}], []))
        self.assertTrue(workflow_graph.validate('X', [], [], []))
        self.assertTrue(workflow_graph.validate('X', {}, [{'type': 'fire_rule', 'name': 'X'}], []))
        # Editing B so it runs A, while A already runs B, is a loop.
        _rule('A', actions=[{'type': 'fire_rule', 'name': 'B'}])
        b = _rule('B', actions=[{'type': 'add_tag', 'tag': 't'}])
        errs = workflow_graph.validate('B', {}, [], [{'type': 'fire_rule', 'name': 'A'}], rule=b)
        self.assertTrue(any('loops back' in e for e in errs), errs)
        # A plain, valid definition passes (a new rule C running A, which runs B).
        self.assertEqual(workflow_graph.validate('C', {'priority': 'P1'}, [{'type': 'add_tag', 'tag': 't'}],
                                                 [{'type': 'fire_rule', 'name': 'A'}]), [])

    def test_validate_new_rule_that_closes_a_loop(self):
        # A runs "New"; the new rule "New" runs A -> loop although "New" is unsaved.
        _rule('A', actions=[{'type': 'fire_rule', 'name': 'New'}])
        errs = workflow_graph.validate('New', {}, [{'type': 'fire_rule', 'name': 'A'}], [])
        self.assertTrue(any('loops back' in e for e in errs), errs)

    def test_describe_condition_combinators(self):
        lines = workflow_graph.describe_condition({'any': [{'priority': 'P1'}, {'queue': 'NOC'}]})
        self.assertEqual(lines, ['(Priority = P1 OR Queue = NOC)'])


class WorkflowEngineLoopGuardTests(TestCase):
    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        self.org = Organization.objects.create(name='WfLoop', slug='wf-loop')

    def _ticket(self):
        return Ticket.objects.create(organization=self.org, subject='T', queue=Queue.objects.first(),
                                     priority=TicketPriority.objects.first(),
                                     ticket_type=TicketType.objects.first(),
                                     status=TicketStatus.objects.filter(slug='new').first())

    def test_loop_saved_before_validation_is_refused_not_recursed(self):
        a = _rule('Loop A', actions=[{'type': 'add_tag', 'tag': 'a'}, {'type': 'fire_rule', 'name': 'Loop B'}])
        _rule('Loop B', trigger='comment_added', actions=[{'type': 'fire_rule', 'name': 'Loop A'}])
        t = self._ticket()
        a.refresh_from_db()
        self.assertIn('already running in this chain', a.last_error)
        t.refresh_from_db()
        self.assertIn('a', t.tags or [])

    def test_chain_still_runs_and_state_is_clean_afterwards(self):
        _rule('Leaf', trigger='comment_added', actions=[{'type': 'add_tag', 'tag': 'leaf'}])
        root = _rule('Root', actions=[{'type': 'fire_rule', 'name': 'Leaf'}])
        t1 = self._ticket()
        t2 = self._ticket()
        t1.refresh_from_db()
        t2.refresh_from_db()
        self.assertIn('leaf', t1.tags or [])
        self.assertIn('leaf', t2.tags or [])
        root.refresh_from_db()
        self.assertEqual(root.last_error, '')
        from psa.workflow_engine import _chain
        self.assertEqual(_chain(), [])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WorkflowBuilderViewTests(TestCase):
    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        self.admin = User.objects.create_superuser('wfadmin', 'wf@x.com', 'pw')
        self.client = Client()
        self.client.force_login(self.admin)
        sess = self.client.session
        sess['2fa_prompted'] = True
        sess.save()

    def _post(self, url, **over):
        data = {'name': 'Branchy', 'trigger': 'ticket_created', 'is_active': 'on',
                'conditions': json.dumps({'priority': 'P1'}),
                'actions': json.dumps([{'type': 'add_tag', 'tag': 'hot'}]),
                'else_actions': json.dumps([{'type': 'add_tag', 'tag': 'cold'}])}
        data.update(over)
        return self.client.post(url, data)

    def test_create_saves_both_branches_and_once_flag(self):
        resp = self._post('/psa/rules/new/', fire_once_per_ticket='on')
        self.assertEqual(resp.status_code, 302)
        r = WorkflowRule.objects.get(name='Branchy')
        self.assertEqual(r.actions, [{'type': 'add_tag', 'tag': 'hot'}])
        self.assertEqual(r.else_actions, [{'type': 'add_tag', 'tag': 'cold'}])
        self.assertTrue(r.fire_once_per_ticket)

    def test_invalid_definition_is_refused_and_input_kept(self):
        resp = self._post('/psa/rules/new/', else_actions=json.dumps([{'type': 'fire_rule', 'name': 'Ghost'}]))
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(WorkflowRule.objects.filter(name='Branchy').exists())
        self.assertContains(resp, 'Ghost', status_code=400)
        self.assertContains(resp, 'value="Branchy"', status_code=400)

    def test_bad_json_is_refused(self):
        resp = self._post('/psa/rules/new/', actions='[not json')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(WorkflowRule.objects.exists())

    def test_edit_keeps_raw_json_compatible(self):
        r = _rule('Raw', conditions={'any': [{'priority': 'P1'}, {'priority': 'P2'}]},
                  actions=[{'type': 'create_charge', 'amount': '10.00', 'description': 'x'}])
        resp = self.client.get(f'/psa/rules/{r.pk}/edit/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'create_charge')
        self.assertContains(resp, 'json-else-actions')
        resp = self._post(f'/psa/rules/{r.pk}/edit/', name='Raw',
                          conditions=json.dumps(r.conditions), actions=json.dumps(r.actions),
                          else_actions='[]')
        self.assertEqual(resp.status_code, 302)
        r.refresh_from_db()
        self.assertEqual(r.conditions, {'any': [{'priority': 'P1'}, {'priority': 'P2'}]})
        self.assertEqual(r.actions[0]['type'], 'create_charge')

    def test_flow_pages_render_chain(self):
        _rule('Child', actions=[{'type': 'add_tag', 'tag': 'c'}])
        parent = _rule('Parent', actions=[{'type': 'fire_rule', 'name': 'Child'}])
        resp = self.client.get(f'/psa/rules/{parent.pk}/flow/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Runs rule')
        self.assertContains(resp, 'Child')
        resp = self.client.get('/psa/rules/flow/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Also run by other rules')
