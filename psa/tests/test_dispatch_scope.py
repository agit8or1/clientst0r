"""The dispatch board's grid follows the technician's customer scope.

With no customer selected, the grid used to list the newest tickets of every
customer, even for a technician whose client scope covers only some of them.
The sign-in middleware normally selects a customer for a scoped technician;
these tests take the "no customer selected" path directly, so the board's own
scoping is what is tested (seen on the 60-customer scale run).
"""
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from core.models import Organization
from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_for, _enable_psa_global, _make_msp_tech, _setup_seed


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DispatchScopeTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        cls.alpha = Organization.objects.create(name='Scope Alpha', slug='scope-alpha')
        cls.bravo = Organization.objects.create(name='Scope Bravo', slug='scope-bravo')
        cls.charlie = Organization.objects.create(name='Scope Charlie', slug='scope-charlie')
        for org in (cls.alpha, cls.bravo, cls.charlie):
            _enable_psa_for(org)
        cls.tech = _make_msp_tech(User.objects.create_user('scope_tech', 'st@msp.test', 'pw-scope-123'))
        cls.tech.profile.client_scope = 'selected'
        cls.tech.profile.save()
        # Two customers in scope, so Global View stays available (with one,
        # the app selects it).
        cls.tech.profile.scope_organizations.set([cls.alpha, cls.charlie])
        kw = dict(queue=Queue.objects.first(), priority=TicketPriority.objects.order_by('sort_order').first(),
                  ticket_type=TicketType.objects.first(), status=TicketStatus.objects.filter(slug='new').first(),
                  resolution_due_at=timezone.now() + timedelta(days=1))
        cls.t_alpha = Ticket.objects.create(organization=cls.alpha, subject='Alpha printer jammed', **kw)
        cls.t_bravo = Ticket.objects.create(organization=cls.bravo, subject='Bravo payroll server down', **kw)
        cls.t_charlie = Ticket.objects.create(organization=cls.charlie, subject='Charlie VPN drops', **kw)
        cls.su = User.objects.create_superuser('scope_su', 'su@msp.test', 'pw-scope-123')

    def _login(self, user):
        c = Client()
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        # Global View: no customer selected, which is where the grid ignored
        # the scope.
        s['global_view_mode'] = True
        s.pop('current_organization_id', None)
        s.save()
        return c

    def _board(self, user):
        with mock.patch('psa.views.get_request_organization', return_value=None):
            return self._login(user).get('/psa/dispatch/')

    def test_scoped_technician_sees_only_their_customers(self):
        resp = self._board(self.tech)
        self.assertEqual(resp.status_code, 200)
        # Both in-scope customers on one board: no single customer selected.
        self.assertContains(resp, self.t_alpha.subject)
        self.assertContains(resp, self.t_charlie.subject)
        self.assertNotContains(resp, self.t_bravo.subject)
        self.assertNotContains(resp, self.t_bravo.ticket_number)

    def test_superuser_still_sees_every_customer(self):
        resp = self._board(self.su)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.t_alpha.subject)
        self.assertContains(resp, self.t_bravo.subject)
