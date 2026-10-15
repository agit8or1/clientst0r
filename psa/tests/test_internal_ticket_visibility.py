"""
Customer users get the portal's rule everywhere they see tickets: only tickets
shared with the client, no internal comments, no internal attachments. MSP
staff see everything. `tickets_view_all` only widens reach for MSP staff.
"""
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from rest_framework.authtoken.models import Token

from accounts.models import Membership, Role
from core.models import Organization
from psa.models import (
    Queue, Ticket, TicketAttachment, TicketComment, TicketPriority, TicketStatus, TicketType,
)
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_for, _enable_psa_global, _setup_seed

NO_THROTTLE_REST = dict(django_settings.REST_FRAMEWORK, DEFAULT_THROTTLE_CLASSES=[])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   REST_FRAMEWORK=NO_THROTTLE_REST)
class InternalTicketVisibilityTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        cls.cust = Organization.objects.create(name='Visible Co', slug='vis-co')
        cls.other = Organization.objects.create(name='Other Co', slug='vis-other')
        for org in (cls.cust, cls.other):
            _enable_psa_for(org)

        def ticket(org, subject, shared):
            return Ticket.objects.create(
                organization=org, subject=subject, client_can_view=shared,
                queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
                ticket_type=TicketType.objects.first(),
                status=TicketStatus.objects.filter(slug='new').first(),
            )

        cls.shared = ticket(cls.cust, 'Shared ticket', True)
        cls.unshared = ticket(cls.cust, 'Internal-only ticket', False)
        cls.other_ticket = ticket(cls.other, 'Other customer ticket', True)

        TicketComment.objects.create(ticket=cls.shared, body='Public reply text')
        internal = TicketComment.objects.create(
            ticket=cls.shared, body='Internal note text', is_internal=True)
        TicketAttachment.objects.create(
            ticket=cls.shared, file=SimpleUploadedFile('public.txt', b'x'))
        TicketAttachment.objects.create(
            ticket=cls.shared, is_internal=True, file=SimpleUploadedFile('secret.txt', b'x'))
        TicketAttachment.objects.create(
            ticket=cls.shared, comment=internal, file=SimpleUploadedFile('oncomment.txt', b'x'))

        # Customer Admin: the simple Admin role carries tickets_view_all.
        cls.customer_admin = User.objects.create_user('vis_admin', 'a@vis.test', 'pw-vis-123')
        Membership.objects.create(user=cls.customer_admin, organization=cls.cust,
                                  role=Role.ADMIN, is_active=True)
        cls.staff = User.objects.create_superuser('vis_staff', 's@msp.test', 'pw-vis-123')

    def _web(self, user):
        c = Client()
        c.force_login(user)
        session = c.session
        session['current_organization_id'] = self.cust.id
        session.save()
        return c

    def _mobile(self, user):
        token = Token.objects.get_or_create(user=user)[0]
        return lambda path: Client().get(path, HTTP_AUTHORIZATION=f'Token {token.key}')

    # Staff web UI

    def test_customer_sees_only_public_items_on_ticket_page(self):
        r = self._web(self.customer_admin).get(f'/psa/t/{self.shared.ticket_number}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Public reply text')
        self.assertNotContains(r, 'Internal note text')
        self.assertEqual([a.file.name.rsplit('/', 1)[-1].split('_')[0].split('.')[0]
                          for a in r.context['attachments']], ['public'])

    def test_customer_cannot_open_unshared_ticket(self):
        r = self._web(self.customer_admin).get(f'/psa/t/{self.unshared.ticket_number}/')
        self.assertEqual(r.status_code, 404)

    def test_customer_ticket_list_hides_unshared(self):
        r = self._web(self.customer_admin).get('/psa/')
        self.assertContains(r, 'Shared ticket')
        self.assertNotContains(r, 'Internal-only ticket')

    def test_staff_see_everything(self):
        r = self._web(self.staff).get(f'/psa/t/{self.shared.ticket_number}/')
        self.assertContains(r, 'Internal note text')
        self.assertEqual(len(r.context['attachments']), 3)
        self.assertEqual(
            self._web(self.staff).get(f'/psa/t/{self.unshared.ticket_number}/').status_code, 200)

    # Mobile API

    def test_mobile_customer_admin_stays_in_own_customer(self):
        get = self._mobile(self.customer_admin)
        r = get('/api/mobile/v1/tickets/')
        self.assertEqual(r.status_code, 200)
        subjects = {t['subject'] for t in r.json()['results']}
        self.assertEqual(subjects, {'Shared ticket'})
        self.assertEqual(get(f'/api/mobile/v1/tickets/{self.other_ticket.pk}/').status_code, 404)
        self.assertEqual(get(f'/api/mobile/v1/tickets/{self.unshared.pk}/').status_code, 404)

    def test_mobile_detail_hides_internal_comments_from_customer(self):
        r = self._mobile(self.customer_admin)(f'/api/mobile/v1/tickets/{self.shared.pk}/')
        bodies = [c['body'] for c in r.json()['comments']]
        self.assertEqual(bodies, ['Public reply text'])

    def test_mobile_staff_detail_includes_internal_comments(self):
        r = self._mobile(self.staff)(f'/api/mobile/v1/tickets/{self.shared.pk}/')
        self.assertIn('Internal note text', [c['body'] for c in r.json()['comments']])

    def test_mobile_assignee_picker_not_global_for_customer_admin(self):
        r = self._mobile(self.customer_admin)('/api/mobile/v1/users/assignable/')
        self.assertEqual(r.status_code, 200)
        names = {u.get('username') for u in r.json().get('results', r.json())} \
            if isinstance(r.json(), (list, dict)) else set()
        self.assertNotIn('vis_staff', names)
