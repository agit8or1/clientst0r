"""SR-03: workflow assign/watch actions respect customer authorization."""
from django.contrib.auth.models import User
from django.test import TestCase

from accounts.models import Membership
from core.models import Organization
from psa import workflow_engine
from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType, TicketWatcher, WorkflowRule
from psa.routing.models import CustomerRoutingSettings
from psa.tests._base import _make_msp_tech, _setup_seed


class WorkflowAssignmentScopeTests(TestCase):
    def setUp(self):
        _setup_seed()
        self.org_a = Organization.objects.create(name='A', slug='wf-a')
        self.org_b = Organization.objects.create(name='B', slug='wf-b')
        self.ticket = Ticket.objects.create(
            organization=self.org_a, subject='T', queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(), ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first())
        self.portal_b = User.objects.create_user('portal_b', password='x')
        Membership.objects.create(user=self.portal_b, organization=self.org_b)

    def _fire(self, actions):
        rule = WorkflowRule.objects.create(name='R', trigger='ticket_updated', conditions={},
                                           actions=actions, is_active=True)
        workflow_engine.fire('ticket_updated', self.ticket)
        rule.refresh_from_db()
        return rule

    def test_portal_user_of_other_customer_is_not_added_as_watcher(self):
        rule = self._fire([{'type': 'add_watcher', 'username': 'portal_b'},
                           {'type': 'add_tag', 'tag': 'still-runs'}])
        self.assertFalse(TicketWatcher.objects.filter(ticket=self.ticket, user=self.portal_b).exists())
        self.assertIn('not a member of this customer', rule.last_error)
        self.ticket.refresh_from_db()
        self.assertIn('still-runs', self.ticket.tags)

    def test_portal_user_cannot_be_assigned(self):
        rule = self._fire([{'type': 'assign_to', 'username': 'portal_b'}])
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.assigned_to)
        self.assertIn('not an MSP technician', rule.last_error)

    def test_round_robin_skips_restricted_technician(self):
        allowed = _make_msp_tech(User.objects.create_user('tech_ok', password='x', is_staff=True))
        blocked = _make_msp_tech(User.objects.create_user('tech_no', password='x', is_staff=True))
        cust = CustomerRoutingSettings.objects.create(organization=self.org_a, restrict_technicians=True)
        cust.authorized_technicians.add(allowed)
        for _ in range(3):
            Ticket.objects.filter(pk=self.ticket.pk).update(assigned_to=None)
            self.ticket.refresh_from_db()
            workflow_engine.run_action(self.ticket, {'type': 'assign_round_robin'})
            self.ticket.refresh_from_db()
            self.assertEqual(self.ticket.assigned_to, allowed)
            self.assertNotEqual(self.ticket.assigned_to, blocked)

    def test_round_robin_with_nobody_allowed_is_reported(self):
        _make_msp_tech(User.objects.create_user('tech_no', password='x', is_staff=True))
        CustomerRoutingSettings.objects.create(organization=self.org_a, restrict_technicians=True)
        rule = self._fire([{'type': 'assign_round_robin'}])
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.assigned_to)
        self.assertIn('no technician in the pool', rule.last_error)
