"""
Ticket sidebar vault card and "View all" vault context honour the role's
vault_view permission, and the unaudited sidebar shows titles only.
"""
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role, RoleTemplate
from core.models import Organization
from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_for, _enable_psa_global, _setup_seed
from vault.models import Password


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TicketVaultSidebarTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        cls.org = Organization.objects.create(name='Sidebar Co', slug='sidebar-co')
        _enable_psa_for(cls.org)
        cls.ticket = Ticket.objects.create(
            organization=cls.org, subject='Printer down', client_can_view=True,
            queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
        )
        Password.objects.create(
            organization=cls.org, title='Firewall admin', username='fw-root-user',
            encrypted_password='dummy',
        )
        cls.tech = User.objects.create_user('sb_tech', 't@x.test', 'pw-sb-123')
        Membership.objects.create(user=cls.tech, organization=cls.org,
                                  role=Role.EDITOR, is_active=True)
        no_vault = RoleTemplate.objects.create(
            name='No vault', organization=cls.org, vault_view=False)
        cls.no_vault_user = User.objects.create_user('sb_novault', 'n@x.test', 'pw-sb-123')
        Membership.objects.create(user=cls.no_vault_user, organization=cls.org,
                                  role=Role.EDITOR, role_template=no_vault, is_active=True)

    def _client(self, user):
        c = Client()
        c.force_login(user)
        session = c.session
        session['current_organization_id'] = self.org.id
        session.save()
        return c

    def test_sidebar_shows_titles_but_not_usernames(self):
        r = self._client(self.tech).get(f'/psa/t/{self.ticket.ticket_number}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Firewall admin')
        self.assertNotContains(r, 'fw-root-user')

    def test_sidebar_hides_vault_without_vault_view(self):
        r = self._client(self.no_vault_user).get(f'/psa/t/{self.ticket.ticket_number}/')
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'Firewall admin')
        self.assertContains(r, "doesn't include vault access")

    def test_view_all_requires_vault_view(self):
        url = f'/psa/t/{self.ticket.ticket_number}/context/'
        self.assertEqual(self._client(self.no_vault_user).get(url).status_code, 403)
        r = self._client(self.tech).get(url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Firewall admin')
