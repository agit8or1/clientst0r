"""Optional application switcher (roadmap 113.10).

docs/ux/CROSS_APP_UX_CONTRACT.md §3, docs/ux/STANDALONE_REQUIREMENTS.md S1:
no markup at all without a usable peer; entries only for active, verified
connections the user may open; status from stored results, never Connected
when stale; links are the stored origin only; no network while rendering.
"""
from __future__ import annotations

import socket
from datetime import timedelta
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.shortcuts import render
from django.test import TestCase, override_settings
from django.urls import path, reverse
from django.utils import timezone

from accounts.models import Membership, Role, RoleTemplate, UserProfile, UserType
from connect.models import Connection, InstallationIdentity, TenantGrant
from core import app_switcher
from core.models import Organization
from integrations.models import RMMConnection, RMMDevice

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def _probe(request):
    return render(request, 'core/_app_switcher.html')


def _page(request):
    return render(request, 'base.html')


from config.urls import urlpatterns as _real_urlpatterns  # noqa: E402

urlpatterns = [path('__app_switcher_probe__/', _probe), path('__app_switcher_page__/', _page)] \
    + list(_real_urlpatterns)

PROBE = '/__app_switcher_probe__/'
PAGE = '/__app_switcher_page__/'
URLCONF = 'core.tests.test_app_switcher'
MARKERS = ('appSwitcher', 'app-switcher', 'Switch application', 'data-app-entry')


def _staff(user, role=None):
    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=user)
    profile.user_type = UserType.STAFF
    profile.global_role_template = role
    profile.save()
    return user


def _no_network():
    def refuse(*a, **k):
        raise AssertionError('outbound network call while rendering')
    return mock.patch.multiple(socket.socket, connect=refuse, connect_ex=refuse)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, ROOT_URLCONF=URLCONF,
                   AGIT8OR_CONNECT_ENABLED=True)
class AppSwitcherTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Acme', slug='acme')
        cls.other = Organization.objects.create(name='Globex', slug='globex')
        cls.viewer_role = RoleTemplate.objects.create(name='Connect viewer', view_app_connections=True,
                                                      integrations_view=True)
        cls.plain_role = RoleTemplate.objects.create(name='Plain tech', view_app_connections=False,
                                                     integrations_view=False)
        cls.tech = _staff(User.objects.create_user('tech', 't@x.com', 'pw'), cls.viewer_role)
        cls.plain = _staff(User.objects.create_user('plain', 'p@x.com', 'pw'), cls.plain_role)
        cls.customer = User.objects.create_user('cust', 'c@x.com', 'pw')
        profile, _ = UserProfile.objects.get_or_create(user=cls.customer)
        profile.user_type = UserType.ORG_USER
        profile.save()
        Membership.objects.create(user=cls.customer, organization=cls.org, role=Role.ADMIN)

    def setUp(self):
        cache.delete(app_switcher.CACHE_KEY)

    # -- helpers --
    def _conn(self, **kw):
        defaults = dict(direction=Connection.OUTBOUND, state=Connection.ACTIVE, remote_app_type='rem0te',
                        remote_installation_id='peer-1', remote_display_name='Rem0te',
                        base_url='https://peer.example:8443/.well-known/agit8or-connect',
                        health=Connection.HEALTH_CONNECTED, last_check_at=timezone.now())
        defaults.update(kw)
        return Connection.objects.create(**defaults)

    def _get(self, user, url=PROBE, global_view=True, **extra):
        self.client.force_login(user)
        if global_view and user.is_authenticated and (user.is_superuser or getattr(user.profile, 'user_type', '')
                                                      == UserType.STAFF):
            # Global View: no customer selected (customer context is tested separately).
            self.client.get(reverse('accounts:switch_to_global_view'))
        return self.client.get(url, **extra).content.decode()

    def assertNoSwitcher(self, html):
        for m in MARKERS:
            self.assertNotIn(m, html)

    # -- standalone --
    def test_no_peers_no_markup(self):
        admin = User.objects.create_superuser('root', 'r@x.com', 'pw')
        self.assertNoSwitcher(self._get(admin))
        self.assertNoSwitcher(self._get(admin, PAGE))

    def test_connect_disabled_hides_active_connection(self):
        self._conn()
        with self.settings(AGIT8OR_CONNECT_ENABLED=False):
            self.assertNoSwitcher(self._get(self.tech))

    def test_kill_switch_hides_connect_entries(self):
        self._conn()
        InstallationIdentity.objects.create(kill_switch_engaged=True)
        self.assertNoSwitcher(self._get(self.tech))

    # -- entries and permissions --
    def test_active_peer_and_permitted_user_sees_stored_origin(self):
        c = self._conn()
        html = self._get(self.tech)
        self.assertIn(f'data-app-entry="connect:{c.pk}"', html)
        self.assertIn('href="https://peer.example:8443/"', html)
        self.assertIn('rel="noopener noreferrer"', html)
        self.assertIn('aria-haspopup="menu"', html)
        self.assertIn('data-app-status="connected"', html)

    def test_switcher_rendered_in_base_top_bar(self):
        self._conn()
        html = self._get(self.tech, PAGE)
        self.assertEqual(html.count('id="appSwitcher"'), 1)
        self.assertLess(html.index('navbar-brand'), html.index('id="appSwitcher"'))

    def test_user_without_permission_sees_nothing(self):
        self._conn()
        self.assertNoSwitcher(self._get(self.plain))

    def test_customer_user_sees_nothing(self):
        self._conn()
        self.assertNoSwitcher(self._get(self.customer))

    def test_revoked_suspended_blocked_pairings_hidden(self):
        for state in (Connection.REVOKED, Connection.SUSPENDED, Connection.SECURITY_BLOCKED,
                      Connection.FAILED, Connection.PENDING_PAIRING, Connection.TESTING):
            Connection.objects.all().delete()
            self._conn(state=state)
            self.assertNoSwitcher(self._get(self.tech))

    def test_revoking_drops_cached_entry(self):
        c = self._conn()
        self.assertIn('data-app-entry', self._get(self.tech))
        c.state = Connection.REVOKED
        c.save()
        self.assertNoSwitcher(self._get(self.tech))

    # -- status --
    def test_stale_health_not_shown_connected(self):
        self._conn(last_check_at=timezone.now() - timedelta(hours=3))
        html = self._get(self.tech)
        self.assertIn('data-app-status="unknown"', html)
        self.assertIn('Status unknown', html)
        self.assertNotIn('data-app-status="connected"', html)
        self.assertNotIn('Online', html)

    def test_never_checked_not_shown_connected(self):
        self._conn(last_check_at=None, health='')
        html = self._get(self.tech)
        self.assertIn('data-app-status="not_checked"', html)
        self.assertNotIn('data-app-status="connected"', html)

    def test_offline_peer_listed_with_link_and_time(self):
        self._conn(health=Connection.HEALTH_OFFLINE, last_check_at=timezone.now() - timedelta(minutes=2))
        html = self._get(self.tech)
        self.assertIn('data-app-status="offline"', html)
        self.assertIn('href="https://peer.example:8443/"', html)
        self.assertIn('<time datetime=', html)

    def test_no_outbound_network_during_render(self):
        self._conn(health=Connection.HEALTH_OFFLINE)
        RMMConnection.objects.create(provider_type='rem0te', name='Rem0te RMM',
                                     base_url='https://rmm.example.com/api/v1/pub/v1', last_sync_at=timezone.now(),
                                     last_sync_status='success')
        self.client.force_login(self.tech)
        with _no_network():
            html = self.client.get(PAGE).content.decode()
        self.assertIn('data-app-entry="connect:', html)
        self.assertIn('data-app-entry="rmm:', html)

    # -- link safety --
    def test_link_is_origin_only_no_query_or_userinfo(self):
        self._conn(base_url='https://peer.example/connect?token=abc&next=https://evil.example/#frag')
        html = self._get(self.tech, PROBE + '?next=https://evil.example/&target=https://evil.example/')
        self.assertIn('href="https://peer.example/"', html)
        self.assertNotIn('evil.example', html)
        self.assertNotIn('token=', html)
        self.assertNotIn('abc', html)

    def test_non_https_or_userinfo_base_url_hidden(self):
        self._conn(base_url='http://peer.example/')
        self.assertNoSwitcher(self._get(self.tech))
        Connection.objects.all().delete()
        self._conn(base_url='https://user:secret@peer.example/')
        self.assertNoSwitcher(self._get(self.tech))

    def test_safe_origin(self):
        so = app_switcher.safe_origin
        self.assertEqual(so('https://Peer.Example:443/x?y=1'), 'https://peer.example/')
        self.assertEqual(so('https://[2001:db8::1]:8443/a'), 'https://[2001:db8::1]:8443/')
        for bad in ('', 'javascript:alert(1)', 'http://a.example/', '//a.example/', 'https://u:p@a.example/',
                    'https://a.example:99999/'):
            self.assertEqual(so(bad), '', bad)

    # -- customer context --
    def test_customer_context_mapped_links_unmapped_explains(self):
        c = self._conn()
        TenantGrant.objects.create(connection=c, organization=self.org, remote_tenant_id='biz-7')
        mapped = app_switcher.entries_for(self.tech, self.org)
        self.assertEqual(mapped[0]['href'], 'https://peer.example:8443/')
        self.assertEqual(mapped[0]['disabled_reason'], '')
        self.assertFalse(mapped[0]['customer_context'])
        unmapped = app_switcher.entries_for(self.tech, self.other)
        self.assertEqual(unmapped[0]['href'], '')
        self.assertIn('Globex is not mapped on the Rem0te connection', unmapped[0]['disabled_reason'])

    def test_selected_unmapped_customer_renders_disabled_entry(self):
        self._conn()
        self.client.force_login(self.tech)
        self.client.get(reverse('accounts:switch_organization', args=[self.org.pk]))
        html = self.client.get(PROBE).content.decode()
        self.assertIn('aria-disabled="true"', html)
        self.assertIn('Acme is not mapped on the Rem0te connection', html)
        self.assertNotIn('href="https://peer.example', html)

    def test_revoked_mapping_is_not_a_mapping(self):
        c = self._conn()
        TenantGrant.objects.create(connection=c, organization=self.org, remote_tenant_id='biz-7', active=False)
        self.assertEqual(app_switcher.entries_for(self.tech, self.org)[0]['href'], '')

    def test_customer_deep_link_off_without_advertised_template(self):
        c = self._conn()
        TenantGrant.objects.create(connection=c, organization=self.org, remote_tenant_id='biz-7')
        with self.settings(APP_SWITCHER_CUSTOMER_LINKS=True):
            e = app_switcher.entries_for(self.tech, self.org)[0]
        self.assertEqual(e['href'], 'https://peer.example:8443/')
        self.assertFalse(e['customer_context'])

    def test_customer_deep_link_needs_flag_template_and_verified_mapping(self):
        c = self._conn()
        TenantGrant.objects.create(connection=c, organization=self.org, remote_tenant_id='biz-7')
        adv = mock.patch.object(app_switcher, 'advertised_ui_links', return_value={'customer': '/customers/{tenant}'})
        with adv:
            # Flag off: home page only.
            self.assertEqual(app_switcher.entries_for(self.tech, self.org)[0]['href'], 'https://peer.example:8443/')
            with self.settings(APP_SWITCHER_CUSTOMER_LINKS=True):
                e = app_switcher.entries_for(self.tech, self.org)[0]
                self.assertEqual(e['href'], 'https://peer.example:8443/customers/biz-7')
                self.assertTrue(e['customer_context'])
                # No mapping for this customer: no link at all.
                self.assertEqual(app_switcher.entries_for(self.tech, self.other)[0]['href'], '')
        for bad in ('//evil.example/{tenant}', 'https://evil.example/{tenant}', '/c/{tenant}?next=x', '/c/x'):
            with mock.patch.object(app_switcher, 'advertised_ui_links', return_value={'customer': bad}), \
                    self.settings(APP_SWITCHER_CUSTOMER_LINKS=True):
                self.assertEqual(app_switcher.entries_for(self.tech, self.org)[0]['href'],
                                 'https://peer.example:8443/', bad)

    # -- RMM connections --
    def test_rmm_entry_uses_validated_console_origin(self):
        conn = RMMConnection.objects.create(provider_type='rem0te', name='Rem0te RMM',
                                            base_url='https://rmm.example.com/api/v1/pub/v1',
                                            last_sync_at=timezone.now(), last_sync_status='success')
        html = self._get(self.tech)
        self.assertIn(f'data-app-entry="rmm:{conn.pk}"', html)
        self.assertIn('href="https://rmm.example.com/"', html)
        self.assertIn('data-app-status="connected"', html)

    def test_rmm_without_console_check_hidden(self):
        # Datto: API host is not a console host and no console address is stored.
        RMMConnection.objects.create(provider_type='datto_rmm', name='Datto',
                                     base_url='https://example.com/api')
        # Inactive connection.
        RMMConnection.objects.create(provider_type='rem0te', name='Old', base_url='https://old.example/',
                                     is_active=False)
        self.assertNoSwitcher(self._get(self.tech))

    def test_rmm_needs_integrations_view_and_customer_reach(self):
        RMMConnection.objects.create(provider_type='rem0te', name='Rem0te RMM',
                                     base_url='https://rmm.example.com/')
        self.assertNoSwitcher(self._get(self.plain))

    def test_rmm_stale_and_failed_sync(self):
        RMMConnection.objects.create(provider_type='rem0te', name='Stale', base_url='https://a.example/',
                                     last_sync_at=timezone.now() - timedelta(days=2), last_sync_status='success')
        RMMConnection.objects.create(provider_type='rem0te', name='Failing', base_url='https://b.example/',
                                     last_sync_at=timezone.now(), last_sync_status='error')
        statuses = {e['name']: e['status'] for e in app_switcher.entries_for(self.tech)}
        self.assertEqual(statuses, {'Stale': 'unknown', 'Failing': 'offline'})

    def test_rmm_customer_mapping_from_owner_or_devices(self):
        own = RMMConnection.objects.create(organization=self.org, provider_type='rem0te', name='Acme own',
                                           base_url='https://own.example/')
        plat = RMMConnection.objects.create(provider_type='rem0te', name='Platform',
                                            base_url='https://plat.example/')
        RMMDevice.objects.create(connection=plat, organization=self.other, external_id='d1', device_name='pc')
        e = {x['name']: x for x in app_switcher.entries_for(self.tech, self.other)}
        self.assertEqual(e['Platform']['href'], 'https://plat.example/')
        self.assertIn('not mapped', e['Acme own']['disabled_reason'])
        self.assertEqual(own.organization_id, self.org.pk)
