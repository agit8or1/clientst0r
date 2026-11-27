"""
"Visible to customer" on staff-created tickets: a switch on the create form
and a share / hide action on the ticket page (tickets_edit, audit-logged).
Staff-created tickets stay hidden from the portal unless the switch is on.
"""
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role
from audit.models import AuditLog
from core.models import Organization
from psa.models import Queue, Ticket, TicketComment, TicketPriority, TicketStatus, TicketType
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_for, _enable_psa_global, _setup_seed
from psa.tests.test_authz_ops import _staff_with_role


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TicketCustomerVisibleTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        cls.org = Organization.objects.create(name='Share Co', slug='share-co')
        _enable_psa_for(cls.org)
        cls.tech = User.objects.create_superuser('share_tech', 't@msp.test', 'pw-share-123')

    def _c(self, user):
        c = Client()
        c.force_login(user)
        s = c.session
        s['current_organization_id'] = self.org.id
        s.save()
        return c

    def _create_post(self, subject, **extra):
        data = {
            'client': self.org.pk, 'subject': subject, 'description': 'd',
            'queue': Queue.objects.first().pk, 'status': TicketStatus.objects.first().pk,
            'priority': TicketPriority.objects.first().pk, 'ticket_type': TicketType.objects.first().pk,
        }
        data.update(extra)
        return self._c(self.tech).post(reverse('psa:ticket_create'), data)

    def _ticket(self, shared=False):
        return Ticket.objects.create(
            organization=self.org, subject='Existing', client_can_view=shared,
            visibility='client' if shared else 'staff',
            queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(), status=TicketStatus.objects.filter(is_terminal=False).first())

    def test_create_form_shows_switch(self):
        r = self._c(self.tech).get(reverse('psa:ticket_create'))
        self.assertContains(r, 'name="client_can_view"')
        self.assertContains(r, 'Visible to customer')

    def test_create_defaults_to_not_shared(self):
        self._create_post('Internal by default')
        t = Ticket.objects.get(subject='Internal by default')
        self.assertFalse(t.client_can_view)
        self.assertEqual(t.visibility, 'staff')

    def test_create_with_switch_shares(self):
        self._create_post('Shared at create', client_can_view='1')
        t = Ticket.objects.get(subject='Shared at create')
        self.assertTrue(t.client_can_view)
        self.assertEqual(t.visibility, 'client')
        log = AuditLog.objects.filter(object_type='psa.Ticket', object_id=t.pk, action='create').get()
        self.assertTrue(log.extra_data.get('client_can_view'))

    def test_toggle_on_ticket_page(self):
        t = self._ticket()
        page = self._c(self.tech).get(reverse('psa:ticket_detail', args=[t.ticket_number]))
        self.assertContains(page, 'Share with customer')
        r = self._c(self.tech).post(reverse('psa:ticket_quick_action', args=[t.ticket_number]),
                                    {'action': 'set_customer_visible', 'visible': '1'})
        self.assertEqual(r.status_code, 302)
        t.refresh_from_db()
        self.assertTrue(t.client_can_view)
        self.assertEqual(t.visibility, 'client')
        self.assertTrue(AuditLog.objects.filter(
            object_type='psa.Ticket', object_id=t.pk,
            extra_data__action='set_customer_visible', extra_data__to=True).exists())
        self.assertTrue(TicketComment.objects.filter(ticket=t, is_internal=True, is_system=True,
                                                     body__startswith='Shared with the customer').exists())
        # And back off again.
        self._c(self.tech).post(reverse('psa:ticket_quick_action', args=[t.ticket_number]),
                                {'action': 'set_customer_visible', 'visible': '0'})
        t.refresh_from_db()
        self.assertFalse(t.client_can_view)
        self.assertEqual(t.visibility, 'staff')

    def test_toggle_needs_tickets_edit(self):
        t = self._ticket()
        viewer = _staff_with_role(User.objects.create_user('share_viewer', 'v@msp.test', 'pw'),
                                  self.org, tickets_view=True)
        page = self._c(viewer).get(reverse('psa:ticket_detail', args=[t.ticket_number]))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'Share with customer')
        r = self._c(viewer).post(reverse('psa:ticket_quick_action', args=[t.ticket_number]),
                                 {'action': 'set_customer_visible', 'visible': '1'})
        self.assertEqual(r.status_code, 403)
        t.refresh_from_db()
        self.assertFalse(t.client_can_view)

    def test_customer_user_cannot_toggle(self):
        t = self._ticket(shared=True)
        cust = User.objects.create_user('share_cust', 'c@share.test', 'pw-share-123')
        Membership.objects.create(user=cust, organization=self.org, role=Role.ADMIN, is_active=True)
        r = self._c(cust).post(reverse('psa:ticket_quick_action', args=[t.ticket_number]),
                               {'action': 'set_customer_visible', 'visible': '0'})
        self.assertEqual(r.status_code, 403)
        t.refresh_from_db()
        self.assertTrue(t.client_can_view)

    def test_shared_ticket_reaches_portal_list(self):
        from psa.visibility import customer_visible_tickets
        cust = User.objects.create_user('share_cust2', 'c2@share.test', 'pw-share-123')
        t = self._ticket()
        self.assertFalse(customer_visible_tickets(Ticket.objects.filter(pk=t.pk), cust).exists())
        self._c(self.tech).post(reverse('psa:ticket_quick_action', args=[t.ticket_number]),
                                {'action': 'set_customer_visible', 'visible': '1'})
        self.assertTrue(customer_visible_tickets(Ticket.objects.filter(pk=t.pk), cust).exists())
