"""Client workspace (accounts/client_workspace.py, accounts:organization_detail).

Pins that the workspace grants nothing: another tenant's workspace and tabs
stay closed (the same bounce as before), a customer user or limited role sees
only the tabs their role opens, tabs need the client to be the current
client (set the client switcher's way), and the Passwords tab never renders
a secret.
"""
import re

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def _make_msp_tech(user, global_role=None):
    from accounts.models import UserProfile, UserType
    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=user)
    profile.user_type = UserType.STAFF
    profile.global_role_template = global_role
    profile.save()
    return user


def _actions(html):
    """The quick-action strip of the workspace."""
    m = re.search(r'aria-label="Quick actions">(.*?)</div>', html, re.S)
    return m.group(1) if m else ''


def _tabs(html):
    """Tab keys in the workspace tab strip."""
    m = re.search(r'data-cw-tabs>(.*?)data-cw-more', html, re.S)
    return re.findall(r'data-key="([a-z]+)"', m.group(1)) if m else []


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ClientWorkspaceTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, RoleTemplate
        from assets.models import Asset, Contact
        from core.models import Organization, SystemSetting
        from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
        from vault.models import Password

        call_command('psa_seed_defaults', verbosity=0)
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()

        cls.a = Organization.objects.create(name='Acme WS', slug='acme-ws')
        cls.child = Organization.objects.create(name='Acme WS branch', slug='acme-ws-branch', parent=cls.a)
        cls.b = Organization.objects.create(name='Beta WS', slug='beta-ws')

        status = TicketStatus.objects.filter(is_terminal=False).first()
        base = dict(status=status, priority=TicketPriority.objects.first(),
                    ticket_type=TicketType.objects.first(), queue=Queue.objects.first())
        cls.ticket_a = Ticket.objects.create(organization=cls.a, subject='Acme printer jam', **base)
        cls.ticket_b = Ticket.objects.create(organization=cls.b, subject='Beta secret project', **base)

        Asset.objects.create(organization=cls.a, name='acme-fw01')
        Asset.objects.create(organization=cls.b, name='beta-fw01')
        Contact.objects.create(organization=cls.a, first_name='Ada', last_name='Acme')
        Contact.objects.create(organization=cls.b, first_name='Bob', last_name='Beta')

        cls.pw = Password.objects.create(organization=cls.a, title='Acme core switch', username='netadmin-x',
                                         notes='plain note do-not-render')
        cls.pw.set_password('Sup3r-Secret-Value!')
        cls.pw.set_secure_notes('secure note do-not-render')
        cls.pw.save()
        cls.pw_b = Password.objects.create(organization=cls.b, title='Beta firewall admin')
        cls.pw_b.set_password('beta-secret')
        cls.pw_b.save()

        cls.su = User.objects.create_superuser('ws_su', 'su@x.test', 'pw')
        cls.tech = _make_msp_tech(User.objects.create_user('ws_tech', 't@x.test', 'pw'))
        cls.owner_b = User.objects.create_user('ws_owner_b', 'b@x.test', 'pw')
        Membership.objects.create(user=cls.owner_b, organization=cls.b, role='owner')

        # A customer user at Acme whose role opens assets only.
        cls.limited_role = RoleTemplate.objects.create(
            name='WS assets only', assets_view=True, vault_view=False, vault_view_password=False,
            docs_view=False, tickets_view=False, tickets_create=False, billing_view_invoices=False,
            integrations_view=False, docs_create=False)
        cls.limited = User.objects.create_user('ws_limited', 'l@x.test', 'pw')
        Membership.objects.create(user=cls.limited, organization=cls.a, role='readonly',
                                  role_template=cls.limited_role)

    def _get(self, user, org, tab=None, current=None):
        self.client.force_login(user)
        if current is not None:
            session = self.client.session
            session['current_organization_id'] = current.pk
            session.save()
        url = reverse('accounts:organization_detail', args=[org.pk])
        return self.client.get(url + (f'?tab={tab}' if tab else ''))

    # -- opening the workspace and client context --------------------------

    def test_opening_sets_current_client_and_records_recent(self):
        from core.models import RecentClient
        r = self._get(self.tech, self.a, current=self.b)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.session['current_organization_id'], self.a.pk)
        self.assertTrue(RecentClient.objects.filter(user=self.tech, organization=self.a).exists())
        html = r.content.decode()
        self.assertIn('id="cw-context"', html)
        self.assertIn('data-cw="all-clients"', html)
        self.assertIn('data-cw="msp-wide"', html)          # every-client technician

    def test_msp_staff_sees_module_tabs(self):
        tabs = _tabs(self._get(self.su, self.a).content.decode())
        for key in ('overview', 'tickets', 'assets', 'rmm', 'contacts', 'documents', 'passwords',
                    'contracts', 'billing', 'projects', 'activity', 'members'):
            self.assertIn(key, tabs)

    def test_psa_tabs_hidden_when_psa_is_off(self):
        from core.models import SystemSetting
        s = SystemSetting.get_settings()
        s.psa_enabled = False
        s.save()
        tabs = _tabs(self._get(self.su, self.a).content.decode())
        for key in ('tickets', 'billing', 'projects'):
            self.assertNotIn(key, tabs)
        self.assertEqual(self._get(self.su, self.a, 'tickets').status_code, 404)

    # -- tenant isolation ---------------------------------------------------

    def test_other_tenant_workspace_and_tabs_are_bounced(self):
        for tab in (None, 'tickets', 'assets', 'passwords', 'contacts', 'activity', 'members'):
            with self.subTest(tab=tab):
                r = self._get(self.owner_b, self.a, tab, current=self.b)
                self.assertRedirects(r, reverse('accounts:organization_list'), fetch_redirect_response=False)
                self.assertEqual(self.client.session['current_organization_id'], self.b.pk)

    def test_tabs_show_only_this_clients_rows(self):
        pages = {
            'tickets': ('Acme printer jam', 'Beta secret project'),
            'assets': ('acme-fw01', 'beta-fw01'),
            'contacts': ('Ada', 'Bob'),
            'passwords': ('Acme core switch', 'Beta firewall admin'),
        }
        for tab, (mine, theirs) in pages.items():
            with self.subTest(tab=tab):
                html = self._get(self.su, self.a, tab).content.decode()
                self.assertIn(mine, html)
                self.assertNotIn(theirs, html)

    def test_parent_member_sees_subsidiary_record_without_tabs(self):
        from accounts.models import Membership
        member = User.objects.create_user('ws_parent_member', 'p@x.test', 'pw')
        Membership.objects.create(user=member, organization=self.a, role='readonly')
        r = self._get(member, self.child, current=self.a)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(_tabs(r.content.decode()), ['overview', 'members'])
        # Not switchable: the session stays where it was.
        self.assertEqual(self.client.session['current_organization_id'], self.a.pk)
        self.assertEqual(self._get(member, self.child, 'tickets').status_code, 404)

    # -- limited roles --------------------------------------------------------

    def test_limited_customer_user_sees_only_permitted_tabs(self):
        r = self._get(self.limited, self.a)
        self.assertEqual(r.status_code, 200)
        tabs = _tabs(r.content.decode())
        self.assertIn('assets', tabs)
        for key in ('passwords', 'rmm', 'documents', 'billing', 'tickets'):
            self.assertNotIn(key, tabs)
        for key in ('passwords', 'rmm', 'documents', 'billing'):
            with self.subTest(tab=key):
                self.assertEqual(self._get(self.limited, self.a, key).status_code, 404)
        self.assertEqual(self._get(self.limited, self.a, 'assets').status_code, 200)

    def test_limited_user_overview_has_no_unpermitted_panels(self):
        html = self._get(self.limited, self.a).content.decode()
        self.assertNotIn('id="cw-tickets"', html)
        self.assertNotIn('id="cw-invoices"', html)
        self.assertNotIn('Acme printer jam', html)
        self.assertNotIn('Open RMM', html)

    def test_unknown_tab_is_404(self):
        self.assertEqual(self._get(self.su, self.a, 'nope').status_code, 404)

    # -- passwords ------------------------------------------------------------

    def test_passwords_tab_never_renders_secrets(self):
        self.pw.refresh_from_db()
        html = self._get(self.su, self.a, 'passwords').content.decode()
        self.assertIn('Acme core switch', html)
        self.assertIn(reverse('vault:password_detail', args=[self.pw.pk]), html)
        for secret in ('Sup3r-Secret-Value!', 'plain note do-not-render', 'secure note do-not-render',
                       self.pw.encrypted_password, 'netadmin-x'):
            self.assertNotIn(secret, html)

    def test_passwords_queryset_loads_no_secret_columns(self):
        from types import SimpleNamespace
        from accounts.client_workspace import Workspace
        req = SimpleNamespace(user=self.su, is_staff_user=False, current_organization=self.a, session={})
        ws = Workspace(req, self.a, in_context=True)
        row = ws.passwords_qs().get(pk=self.pw.pk)
        deferred = row.get_deferred_fields()
        for name in ('encrypted_password', 'encrypted_notes', 'otp_secret', 'notes', 'username'):
            self.assertIn(name, deferred)

    # -- quick actions -------------------------------------------------------

    def test_quick_actions_follow_permissions(self):
        html = _actions(self._get(self.su, self.a).content.decode())
        self.assertIn(reverse('psa:ticket_create') + f'?client={self.a.pk}', html)
        self.assertIn('Create quote', html)
        html = _actions(self._get(self.limited, self.a).content.decode())
        self.assertNotIn('Create ticket', html)
        self.assertNotIn('Create quote', html)
        self.assertNotIn('Add document', html)

    def test_organization_list_links_to_workspace(self):
        r = self._get(self.su, self.a)
        self.assertEqual(r.status_code, 200)
        self.client.force_login(self.su)
        html = self.client.get(reverse('accounts:organization_list')).content.decode()
        self.assertIn(reverse('accounts:organization_detail', args=[self.a.pk]), html)
