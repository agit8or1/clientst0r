"""
A customer user who opens the staff ticket page (/psa/t/<n>/) gets the
portal's view of the ticket (v3.17.650): the shared conversation, never
technician working data, and none of the technician operations — whether
they click a button or post to the URL directly.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role
from core.models import Organization
from psa.models import (Queue, Ticket, TicketAttachment, TicketExpense, TicketPriority, TicketStatus,
                        TicketTimeEntry as TimeEntry, TicketType)
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_for, _enable_psa_global, _make_msp_tech, _setup_seed


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CustomerOnStaffTicketPageTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        cls.org = Organization.objects.create(name='Example Dental', slug='ex-dental')
        _enable_psa_for(cls.org)

        def ticket(subject, shared):
            return Ticket.objects.create(
                organization=cls.org, subject=subject, client_can_view=shared,
                queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
                ticket_type=TicketType.objects.first(),
                status=TicketStatus.objects.filter(slug='new').first())

        cls.shared = ticket('Printer offline at front desk', True)
        cls.unshared = ticket('Printer offline at front desk (internal follow-up)', False)
        cls.tech = _make_msp_tech(User.objects.create_user('ex_tech', 't@msp.test', 'pw-ex-123'))
        Membership.objects.create(user=cls.tech, organization=cls.org, role=Role.EDITOR, is_active=True)
        cls.customer = User.objects.create_user('ex_cust', 'c@dental.test', 'pw-ex-123')
        Membership.objects.create(user=cls.customer, organization=cls.org, role=Role.ADMIN, is_active=True)

        now = timezone.now()
        TimeEntry.objects.create(ticket=cls.shared, user=cls.tech, started_at=now - timedelta(hours=1),
                                 ended_at=now, notes='TECH-ONLY time note')
        TicketExpense.objects.create(ticket=cls.shared, user=cls.tech, amount=Decimal('42.00'),
                                     description='TECH-ONLY expense', incurred_on=now.date())

    def _web(self, user):
        c = Client()
        c.force_login(user)
        s = c.session
        s['current_organization_id'] = self.org.id
        s.save()
        return c

    def _url(self, name, ticket=None):
        return reverse(name, kwargs={'ticket_number': (ticket or self.shared).ticket_number})

    def test_customer_page_has_no_technician_working_data(self):
        html = self._web(self.customer).get(self._url('psa:ticket_detail')).content.decode()
        self.assertIn('Printer offline at front desk', html)
        for leaked in ('TECH-ONLY time note', 'TECH-ONLY expense', '(internal follow-up)',
                       'Kit to take', 'fa-stopwatch', 'fa-receipt'):
            self.assertNotIn(leaked, html, leaked)
        ctx = self._web(self.customer).get(self._url('psa:ticket_detail')).context
        self.assertEqual(list(ctx['time_entries']), [])
        self.assertEqual(list(ctx['similar_tickets']), [])

    def test_technician_still_sees_working_data(self):
        html = self._web(self.tech).get(self._url('psa:ticket_detail')).content.decode()
        self.assertIn('TECH-ONLY time note', html)
        self.assertIn('TECH-ONLY expense', html)

    def test_technician_operations_refused_by_direct_url(self):
        c = self._web(self.customer)
        posts = {
            'psa:ticket_quick_action': {'action': 'close'},
            'psa:ticket_merge': {'target': self.unshared.ticket_number},
            'psa:ticket_expense_add': {'amount': '9.99', 'description': 'x', 'category': 'other'},
            'psa:ticket_kit_add': {'name': 'ladder'},
            'psa:ticket_launch_workflow': {'process': '1'},
            'psa:ticket_kb_link': {'article': '1'},
        }
        for name, data in posts.items():
            with self.subTest(name=name):
                self.assertEqual(c.post(self._url(name), data).status_code, 403, name)
        self.assertEqual(c.get(self._url('psa:ticket_launch_workflow', self.unshared)).status_code, 403)
        self.assertEqual(c.get(self._url('psa:ticket_route_urls')).status_code, 403)
        self.shared.refresh_from_db()
        self.assertIsNone(self.shared.closed_at)
        self.assertEqual(TicketExpense.objects.filter(ticket=self.shared).count(), 1)

    def test_customer_attachment_is_always_public(self):
        f = SimpleUploadedFile('photo.png', b'\x89PNG\r\n\x1a\n' + b'0' * 32, content_type='image/png')
        self._web(self.customer).post(self._url('psa:ticket_attach'), {'file': f, 'is_internal': '1'})
        att = TicketAttachment.objects.get(ticket=self.shared, uploaded_by=self.customer)
        self.assertFalse(att.is_internal)

    def test_customer_can_still_reply_and_watch(self):
        c = self._web(self.customer)
        self.assertEqual(c.post(self._url('psa:ticket_post_comment'), {'body': 'Still offline today.'}).status_code, 302)
        self.assertEqual(c.post(self._url('psa:ticket_watch_toggle')).status_code, 302)
