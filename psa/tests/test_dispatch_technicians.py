"""
Only MSP technicians (superuser, Django staff, User Type Staff) appear as
dispatch rows, get suggested, or can be assigned tickets — on the web board,
the heatmap, drag-and-drop, "assign to me", problems, process launch and the
mobile API. A customer's own users never do. A ticket already assigned to a
non-technician still shows, on a flagged row.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, Role
from api_mobile.models import MobileAuthToken
from core.models import Organization
from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
from psa.tests._base import (
    TEST_MIDDLEWARE, _enable_psa_for, _enable_psa_global, _make_msp_tech, _setup_seed,
)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DispatchTechnicianTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        cls.org = Organization.objects.create(name='Disp Cust', slug='disp-cust')
        cls.other = Organization.objects.create(name='Disp Other', slug='disp-other')
        _enable_psa_for(cls.org)
        cls.queue = Queue.objects.first()
        cls.priority = TicketPriority.objects.order_by('sort_order').first()
        cls.ttype = TicketType.objects.first()
        cls.status = TicketStatus.objects.filter(slug='new').first()

        cls.dispatcher = User.objects.create_superuser(
            'disp_admin', 'da@msp.test', 'pw-disp-123')
        cls.tech = _make_msp_tech(User.objects.create_user('disp_tech', 'dt@msp.test', 'pw-disp-123'))
        cls.customer = User.objects.create_user('disp_cust_user', 'cu@c.test', 'pw-disp-123')
        Membership.objects.create(user=cls.customer, organization=cls.org,
                                  role=Role.OWNER, is_active=True)
        cls.other_customer = User.objects.create_user('disp_other_user', 'ou@o.test', 'pw-disp-123')
        Membership.objects.create(user=cls.other_customer, organization=cls.other,
                                  role=Role.OWNER, is_active=True)

    def _ticket(self, **kw):
        return Ticket.objects.create(
            organization=self.org, subject=kw.pop('subject', 'disp'), queue=self.queue,
            priority=self.priority, ticket_type=self.ttype, status=self.status,
            resolution_due_at=timezone.now() + timedelta(days=1), **kw)

    def _login(self, user):
        c = Client()
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()
        return c

    def _row_ids(self, resp):
        return [r['tech'].id for r in resp.context['rows']]

    # --- web board -------------------------------------------------------

    def test_board_rows_are_technicians_only(self):
        resp = self._login(self.dispatcher).get('/psa/dispatch/')
        self.assertEqual(resp.status_code, 200)
        ids = self._row_ids(resp)
        self.assertIn(self.tech.id, ids)
        self.assertIn(self.dispatcher.id, ids)
        self.assertNotIn(self.customer.id, ids)
        self.assertNotIn(self.other_customer.id, ids)
        self.assertNotContains(resp, 'Not a technician')

    def test_ticket_assigned_to_customer_user_shows_on_flagged_row(self):
        t = self._ticket(assigned_to=self.customer, subject='legacy assignment')
        resp = self._login(self.dispatcher).get('/psa/dispatch/')
        rows = {r['tech'].id: r for r in resp.context['rows']}
        self.assertIn(self.customer.id, rows)
        self.assertFalse(rows[self.customer.id]['is_tech'])
        self.assertTrue(rows[self.tech.id]['is_tech'])
        # Flagged rows sort after technicians and accept no drops.
        self.assertEqual(resp.context['rows'][-1]['tech'], self.customer)
        self.assertContains(resp, 'Not a technician')
        self.assertContains(resp, t.ticket_number)
        self.assertContains(resp, 'dispatch-cell dispatch-cell-locked')
        self.assertNotContains(resp, f'class="dispatch-cell" data-tech="{self.customer.id}"')

    def test_heatmap_flags_non_technician(self):
        self._ticket(assigned_to=self.customer)
        self._ticket(assigned_to=self.tech)
        resp = self._login(self.dispatcher).get('/psa/dispatch/heatmap/')
        flags = {r['tech'].id: r['is_tech'] for r in resp.context['rows']}
        self.assertEqual(flags, {self.customer.id: False, self.tech.id: True})

    def test_drag_assign_rejects_customer_user_and_accepts_tech(self):
        t = self._ticket()
        c = self._login(self.dispatcher)
        resp = c.post('/psa/dispatch/assign/', {'ticket_number': t.ticket_number,
                                                'assignee': str(self.customer.id)})
        self.assertEqual(resp.status_code, 400)
        t.refresh_from_db()
        self.assertIsNone(t.assigned_to_id)
        resp = c.post('/psa/dispatch/assign/', {'ticket_number': t.ticket_number,
                                                'assignee': str(self.tech.id)})
        self.assertEqual(resp.status_code, 200)
        t.refresh_from_db()
        self.assertEqual(t.assigned_to, self.tech)

    def test_skill_suggestions_are_technicians_only(self):
        from resourcing.views import rank_techs_for_ticket
        ids = {r['user'].id for r in rank_techs_for_ticket(self._ticket())}
        self.assertIn(self.tech.id, ids)  # User Type Staff, no membership
        self.assertNotIn(self.customer.id, ids)
        self.assertNotIn(self.other_customer.id, ids)

    def test_customer_user_cannot_assign_ticket_to_self(self):
        t = self._ticket(client_can_view=True)
        self._login(self.customer).post(f'/psa/t/{t.ticket_number}/action/',
                                        {'action': 'assign_me'})
        t.refresh_from_db()
        self.assertIsNone(t.assigned_to_id)

    def test_tech_can_assign_ticket_to_self(self):
        t = self._ticket()
        Membership.objects.create(user=self.tech, organization=self.org,
                                  role=Role.EDITOR, is_active=True)
        self._login(self.tech).post(f'/psa/t/{t.ticket_number}/action/',
                                    {'action': 'assign_me'})
        t.refresh_from_db()
        self.assertEqual(t.assigned_to, self.tech)

    # --- mobile API ------------------------------------------------------

    def _mobile(self, user):
        c = Client()
        c.defaults['HTTP_AUTHORIZATION'] = f'Token {MobileAuthToken.issue(user)[0]}'
        return c

    def test_mobile_assignable_users_are_technicians_only(self):
        resp = self._mobile(self.dispatcher).get('/api/mobile/v1/users/assignable/')
        self.assertEqual(resp.status_code, 200)
        ids = {r['id'] for r in resp.json()['results']}
        self.assertIn(self.tech.id, ids)
        self.assertNotIn(self.customer.id, ids)
        self.assertNotIn(self.other_customer.id, ids)

    def test_mobile_patch_rejects_customer_assignee(self):
        t = self._ticket()
        c = self._mobile(self.dispatcher)
        resp = c.patch(f'/api/mobile/v1/tickets/{t.pk}/',
                       data={'assigned_to_id': self.other_customer.id},
                       content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        t.refresh_from_db()
        self.assertIsNone(t.assigned_to_id)
        resp = c.patch(f'/api/mobile/v1/tickets/{t.pk}/',
                       data={'assigned_to_id': self.tech.id},
                       content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        t.refresh_from_db()
        self.assertEqual(t.assigned_to, self.tech)
