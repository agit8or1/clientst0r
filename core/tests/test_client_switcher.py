"""Navbar client switcher: current context, recents, search, bounded markup.

The switcher lives in templates/core/_client_switcher.html (included from
base.html). These tests render it through a probe view behind the full
middleware + context-processor stack, so they don't depend on where base.html
places the include.
"""
from __future__ import annotations

import re
from datetime import timedelta

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.shortcuts import render
from django.test import TestCase, override_settings
from django.urls import path, reverse
from django.utils import timezone

from accounts.models import Membership, Role, UserProfile, UserType
from core.client_switcher import RECENT_LIMIT, SEARCH_LIMIT, record_recent_client
from core.models import Organization, RecentClient

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def _probe(request):
    return render(request, 'core/_client_switcher.html')


from config.urls import urlpatterns as _real_urlpatterns  # noqa: E402

urlpatterns = [path('__switcher_probe__/', _probe)] + list(_real_urlpatterns)

PROBE = '/__switcher_probe__/'
URLCONF = 'core.tests.test_client_switcher'


def _set_user_type(user, user_type):
    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=user)
    profile.user_type = user_type
    profile.save()
    return user


def _switch_links(html):
    return set(int(i) for i in re.findall(r'/accounts/switch/(\d+)/', html))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, ROOT_URLCONF=URLCONF)
class ClientSwitcherTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.orgs = [
            Organization.objects.create(name=f'Client {i:03d}', slug=f'client-{i:03d}')
            for i in range(85)
        ]
        cls.internal = Organization.objects.create(
            name='MSP Internal', slug='msp-internal',
            organization_type=Organization.TYPE_INTERNAL,
        )
        cls.admin = User.objects.create_superuser('root', 'r@x.com', 'pw')

        # Restricted technician: plain member of three clients only.
        cls.tech = User.objects.create_user('tech', 't@x.com', 'pw')
        for org in cls.orgs[:3]:
            Membership.objects.create(user=cls.tech, organization=org, role=Role.EDITOR)

        # Customer portal user: member of one client.
        cls.customer = User.objects.create_user('cust', 'c@x.com', 'pw')
        _set_user_type(cls.customer, UserType.ORG_USER)
        Membership.objects.create(user=cls.customer, organization=cls.orgs[10], role=Role.READONLY)

    def _login(self, user):
        self.client.force_login(user)

    # ── Rendering ──────────────────────────────────────────────────────

    def test_superuser_sees_global_view_search_and_view_all(self):
        self._login(self.admin)
        self.client.get(reverse('accounts:switch_to_global_view'))
        html = self.client.get(PROBE).content.decode()
        self.assertIn('Current context', html)
        self.assertIn(reverse('accounts:switch_to_global_view'), html)
        self.assertIn('id="clientSwitcherSearch"', html)
        self.assertIn(reverse('accounts:organization_list'), html)
        self.assertIn('View all clients', html)

    def test_80_plus_clients_render_bounded_markup(self):
        self._login(self.admin)
        for i, org in enumerate(self.orgs[:8]):
            RecentClient.objects.create(
                user=self.admin, organization=org,
                switched_at=timezone.now() - timedelta(minutes=i))
        html = self.client.get(PROBE).content.decode()
        links = _switch_links(html)
        self.assertLessEqual(len(links), RECENT_LIMIT)
        self.assertEqual(links, {o.id for o in self.orgs[:RECENT_LIMIT]})
        # The 85 client names are not in the markup.
        self.assertNotIn('Client 050', html)

    def test_restricted_technician_sees_only_own_clients(self):
        self._login(self.tech)
        resp = self.client.get(PROBE)
        html = resp.content.decode()
        self.assertEqual(_switch_links(html), {o.id for o in self.orgs[:3]})
        self.assertNotIn(reverse('accounts:switch_to_global_view'), html)
        self.assertNotIn('MSP Internal', html)
        # Not an owner: the organizations list would be empty, so no link.
        self.assertNotIn('View all clients', html)

    def test_owner_gets_view_all_link(self):
        Membership.objects.filter(user=self.tech, organization=self.orgs[0]).update(role=Role.OWNER)
        self._login(self.tech)
        html = self.client.get(PROBE).content.decode()
        self.assertIn(reverse('accounts:organization_list'), html)

    def test_customer_user_sees_only_their_client(self):
        self._login(self.customer)
        html = self.client.get(PROBE).content.decode()
        self.assertEqual(_switch_links(html), {self.orgs[10].id})
        self.assertIn('Client 010', html)
        self.assertNotIn('MSP Internal', html)
        self.assertNotIn(reverse('accounts:switch_to_global_view'), html)
        self.assertNotIn('id="clientSwitcherSearch"', html)

    # ── Search ────────────────────────────────────────────────────────

    def _search(self, q):
        resp = self.client.get(reverse('core:client_switcher_search'), {'q': q, 'format': 'json'})
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_search_requires_login(self):
        resp = self.client.get(reverse('core:client_switcher_search'), {'q': 'Client', 'format': 'json'})
        self.assertEqual(resp.status_code, 302)

    def test_search_is_bounded_for_superuser(self):
        self._login(self.admin)
        data = self._search('Client')
        self.assertEqual(len(data['results']), SEARCH_LIMIT)
        self.assertTrue(data['truncated'])
        data = self._search('internal')
        self.assertEqual([r['name'] for r in data['results']], ['MSP Internal'])

    def test_search_returns_only_authorized_clients(self):
        self._login(self.tech)
        data = self._search('Client')
        self.assertEqual({r['id'] for r in data['results']}, {o.id for o in self.orgs[:3]})
        self.assertEqual(self._search('internal')['results'], [])

        self._login(self.customer)
        self.assertEqual({r['id'] for r in self._search('')['results']}, {self.orgs[10].id})

    def test_search_html_fallback_only_authorized(self):
        self._login(self.tech)
        resp = self.client.get(reverse('core:client_switcher_search'), {'q': 'Client'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_switch_links(resp.content.decode()) & {o.id for o in self.orgs},
                         {o.id for o in self.orgs[:3]})

    # ── Switching and recents ─────────────────────────────────────────

    def test_switch_updates_active_client_and_records_recent(self):
        self._login(self.admin)
        target = self.orgs[42]
        resp = self.client.get(reverse('accounts:switch_organization', args=[target.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(RecentClient.objects.filter(user=self.admin, organization=target).exists())

        page = self.client.get(reverse('core:dashboard'))
        self.assertEqual(page.context['current_organization'], target)
        self.assertContains(page, target.name)

        html = self.client.get(PROBE).content.decode()
        self.assertIn(f'title="{target.name}"', html)
        self.assertIn(reverse('accounts:switch_organization', args=[target.id]), html)
        self.assertIn('aria-current="true"', html)

    def test_recents_most_recent_first_and_capped(self):
        self._login(self.admin)
        for org in self.orgs[20:27]:
            self.client.get(reverse('accounts:switch_organization', args=[org.id]))
        html = self.client.get(PROBE).content.decode()
        ids = [int(i) for i in re.findall(r'/accounts/switch/(\d+)/', html)]
        expected = [o.id for o in reversed(self.orgs[22:27])]
        self.assertEqual(ids, expected)

    def test_revoked_access_removes_client_from_recents_and_search(self):
        # Give the technician enough clients that recents (not the full list) render.
        for org in self.orgs[3:15]:
            Membership.objects.create(user=self.tech, organization=org, role=Role.EDITOR)
        self._login(self.tech)
        revoked = self.orgs[5]
        kept = self.orgs[6]
        self.client.get(reverse('accounts:switch_organization', args=[revoked.id]))
        self.client.get(reverse('accounts:switch_organization', args=[kept.id]))
        html = self.client.get(PROBE).content.decode()
        self.assertEqual(_switch_links(html), {revoked.id, kept.id})

        Membership.objects.filter(user=self.tech, organization=revoked).update(is_active=False)
        html = self.client.get(PROBE).content.decode()
        self.assertEqual(_switch_links(html), {kept.id})
        self.assertNotIn(revoked.id, {r['id'] for r in self._search(revoked.name)['results']})

        Membership.objects.filter(user=self.tech, organization=kept).delete()
        html = self.client.get(PROBE).content.decode()
        self.assertEqual(_switch_links(html), set())

    def test_switch_to_unauthorized_client_refused(self):
        self._login(self.tech)
        resp = self.client.get(reverse('accounts:switch_organization', args=[self.orgs[50].id]))
        self.assertRedirects(resp, reverse('core:dashboard'), fetch_redirect_response=False)
        self.assertNotEqual(self.client.session.get('current_organization_id'), self.orgs[50].id)
        self.assertFalse(RecentClient.objects.filter(user=self.tech, organization=self.orgs[50]).exists())
        page = self.client.get(reverse('core:dashboard'))
        self.assertNotEqual(page.context['current_organization'], self.orgs[50])

    def test_customer_cannot_switch_to_internal_client(self):
        self._login(self.customer)
        self.client.get(reverse('accounts:switch_organization', args=[self.internal.id]))
        self.assertFalse(RecentClient.objects.filter(user=self.customer).exists())
        page = self.client.get(reverse('core:dashboard'))
        self.assertEqual(page.context['current_organization'], self.orgs[10])

    def test_record_recent_prunes_old_rows(self):
        for org in self.orgs[:30]:
            record_recent_client(self.admin, org)
        self.assertLessEqual(RecentClient.objects.filter(user=self.admin).count(), 20)
