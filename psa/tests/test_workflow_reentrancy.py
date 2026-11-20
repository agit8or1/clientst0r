"""SR-01: a workflow rule cannot re-enter itself through ticket.save(), and
create_charge bills a ticket at most once per rule."""
from decimal import Decimal

from django.test import TestCase

from core.models import Organization
from psa import workflow_engine
from psa.models import (Charge, Queue, Ticket, TicketPriority, TicketStatus, TicketType,
                        WorkflowCharge, WorkflowRule)
from psa.tests._base import _setup_seed


class WorkflowReentrancyTests(TestCase):
    def setUp(self):
        _setup_seed()
        self.org = Organization.objects.create(name='A', slug='wf-re-a')
        self.ticket = Ticket.objects.create(
            organization=self.org, subject='T', queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(), ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first())
        self.prio = TicketPriority.objects.exclude(pk=self.ticket.priority_id).first()

    def _rule(self, **kw):
        defaults = dict(name='Bill it', trigger='ticket_updated', conditions={}, is_active=True,
                        actions=[{'type': 'set_priority', 'code': self.prio.code},
                                 {'type': 'create_charge', 'amount': '125.00',
                                  'description': 'After-hours'}])
        defaults.update(kw)
        return WorkflowRule.objects.create(**defaults)

    def _touch(self):
        self.ticket.refresh_from_db()
        self.ticket.subject = self.ticket.subject + '.'
        self.ticket.save()

    def test_one_update_fires_once_and_charges_once(self):
        rule = self._rule()
        self._touch()
        rule.refresh_from_db()
        self.assertEqual(rule.fire_count, 1)
        self.assertNotIn('Recursion', rule.last_error)
        self.assertEqual(Charge.objects.filter(client_org=self.org).count(), 1)
        self.assertEqual(Charge.objects.get(client_org=self.org).amount, Decimal('125.00'))
        self.assertEqual(WorkflowCharge.objects.filter(rule=rule, ticket=self.ticket).count(), 1)

    def test_later_updates_do_not_bill_again(self):
        rule = self._rule()
        for _ in range(3):
            self._touch()
        rule.refresh_from_db()
        self.assertEqual(Charge.objects.filter(client_org=self.org).count(), 1)
        self.assertIn('already charged', rule.last_error)

    def test_fire_once_per_ticket_rule_does_nothing_on_second_update(self):
        rule = self._rule(fire_once_per_ticket=True)
        self._touch()
        self._touch()
        rule.refresh_from_db()
        self.assertEqual(rule.fire_count, 1)
        self.assertEqual(Charge.objects.filter(client_org=self.org).count(), 1)

    def test_two_rules_reacting_to_each_other_stop(self):
        a = WorkflowRule.objects.create(name='A', trigger='ticket_updated', conditions={}, is_active=True,
                                        actions=[{'type': 'add_tag', 'tag': 'a'}])
        b = WorkflowRule.objects.create(name='B', trigger='ticket_updated', conditions={}, is_active=True,
                                        actions=[{'type': 'add_tag', 'tag': 'b'}])
        self._touch()
        a.refresh_from_db(); b.refresh_from_db()
        self.assertNotIn('Recursion', a.last_error + b.last_error)
        # Each runs at most once per enclosing chain: bounded, not thousands.
        self.assertLessEqual(a.fire_count + b.fire_count, 4)

    def test_action_budget_per_event(self):
        rule = WorkflowRule.objects.create(
            name='Many', trigger='ticket_updated', conditions={}, is_active=True,
            actions=[{'type': 'add_tag', 'tag': f't{i}'} for i in range(workflow_engine.MAX_ACTIONS_PER_EVENT + 5)])
        self._touch()
        rule.refresh_from_db()
        self.assertIn('workflow actions for one ticket event', rule.last_error)
        # A second, separate event gets a fresh budget (no leak between events).
        WorkflowRule.objects.create(name='One', trigger='ticket_updated', conditions={}, is_active=True,
                                    actions=[{'type': 'add_tag', 'tag': 'fresh'}], sort_order=0)
        rule.is_active = False
        rule.save()
        self._touch()
        self.ticket.refresh_from_db()
        self.assertIn('fresh', self.ticket.tags)

    def test_charge_outside_a_rule_is_refused(self):
        with self.assertRaises(workflow_engine.ActionSkipped):
            workflow_engine.run_action(self.ticket, {'type': 'create_charge', 'amount': '10'})
        self.assertFalse(Charge.objects.exists())
