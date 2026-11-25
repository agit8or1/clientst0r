"""P0-1 (docs/ux/STANDALONE_REQUIREMENTS.md): Clientst0r alone.

A fresh database with every integration at its default (no Rem0te, no
Connect pairing, no RMM, no SSO). Signed in as a superuser MSP technician and
as a customer-portal user, every navigation landing page
(core/tests/nav_landing_routes.py) is fetched under no_network(): no 5xx, and
not one outbound connection attempt. With no network reachable, a page that
tried to call out would fail at once, so "no attempts" is also "response time
not dominated by the network".

All failures are collected and reported in one assertion message.
"""
import time

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse

from accounts.models import Membership, Role
from core.models import Organization, SystemSetting
from core.tests.nav_landing_routes import landing_routes
from core.tests.standalone import no_network
from core.tests.test_navbar_grouping import ALL_FLAGS, TEST_MIDDLEWARE

User = get_user_model()

# Known defects and known GitHub update checks, reported in docs/ux/STANDALONE_REQUIREMENTS.md.
# Tolerated here by name so that anything NEW still fails the test.
KNOWN_5XX = {
    'assets:relationship_map': 'template assets/relationship_map.html does not exist (also in test_nav_reachability)',
}
# Pages that ask GitHub (the update source, not a peer) for releases. The answer is
# cached and an unreachable GitHub is handled, but the request happens on GET.
GITHUB_UPDATE_CHECK = {'core:system_updates', 'core:security_dashboard'}

# A page that renders slower than this under no_network() is doing work it
# should not do on a plain GET (a network-bound call would have failed above).
SLOW_SECONDS = 60.0


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class StandaloneSmokeTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from psa.tests._base import _enable_psa_for, _make_msp_tech, _setup_seed
        _setup_seed()
        cls.org = Organization.objects.create(name='Standalone Smoke Co', slug='standalone-smoke')
        _enable_psa_for(cls.org)
        cls.tech = _make_msp_tech(User.objects.create_user('smoke_tech', 'tech@x.test', 'pw',
                                                           is_staff=True, is_superuser=True))
        Membership.objects.create(user=cls.tech, organization=cls.org, role=Role.OWNER, is_active=True)
        # A customer-portal user: a membership only, no staff profile.
        cls.portal = User.objects.create_user('smoke_portal', 'portal@x.test', 'pw')
        Membership.objects.create(user=cls.portal, organization=cls.org, role=Role.READONLY, is_active=True)

    def _client(self, user):
        self.client.force_login(user)
        s = self.client.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.pk
        s.save()
        return self.client

    def _walk(self, user):
        client = self._client(user)
        failures, slow, unresolved = [], [], []
        names = sorted(landing_routes())
        self.assertGreater(len(names), 100, 'landing route discovery returned too few pages')
        with no_network() as net:
            for name in names:
                try:
                    path = reverse(name)
                except NoReverseMatch:
                    unresolved.append(name)
                    continue
                before = len(net.attempts)
                t0 = time.monotonic()
                try:
                    response = client.get(path)
                    status = response.status_code
                except Exception as exc:  # a view that raises is a 500 in production
                    status = f'exception {type(exc).__name__}: {str(exc)[:160]}'
                took = time.monotonic() - t0
                if (not isinstance(status, int) or status >= 500) and name not in KNOWN_5XX:
                    failures.append(f'{name} {path}: {status}')
                new = net.attempts[before:]
                if name in GITHUB_UPDATE_CHECK:
                    new = [a for a in new if 'api.github.com/' not in a[2]]
                if new:
                    failures.append(f'{name} {path}: outbound attempt {new}')
                if took > SLOW_SECONDS:
                    slow.append(f'{name} {path}: {took:.1f}s')
        return failures + [f'SLOW {s}' for s in slow], len(names) - len(unresolved)

    def test_superuser_technician_sees_no_5xx_and_no_outbound_call(self):
        failures, n = self._walk(self.tech)
        self.assertEqual(failures, [], f'{len(failures)} problem(s) over {n} pages:\n' + '\n'.join(failures))

    def test_superuser_with_every_module_on(self):
        row = SystemSetting.get_settings()
        for flag in ALL_FLAGS:
            setattr(row, flag, True)
        row.save()
        failures, n = self._walk(self.tech)
        self.assertEqual(failures, [], f'{len(failures)} problem(s) over {n} pages:\n' + '\n'.join(failures))

    def test_customer_portal_user_sees_no_5xx_and_no_outbound_call(self):
        failures, n = self._walk(self.portal)
        self.assertEqual(failures, [], f'{len(failures)} problem(s) over {n} pages:\n' + '\n'.join(failures))
