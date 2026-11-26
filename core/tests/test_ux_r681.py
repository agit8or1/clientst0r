"""v3.17.681 workflow and UX polish.

* "Back to PSA-…" (core.return_to): only a same-site ticket path is accepted,
  rebuilt with reverse(); absolute, protocol-relative, scheme, query and
  dot-segment values are refused; core:open_device carries it (and the
  Device Workspace's ?ticket=) only when valid.
* Breadcrumb trails: ticket → Service Desk › Tickets › number; client
  workspace → Clients › client › tab; settings page → Administration ›
  category › page.
* Settings search: keyword/synonym markup (email, 2fa / mfa, geo, llm), the
  "All settings" way back and the "/" hint.
* Phone drawer markup and the return-to scope element.
* The 403 page is generic: it does not echo the URL, the reason or the
  resource.
"""
import re

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.return_to import clean_return_to, return_context
from core.tests.test_nav_overhaul import trail
from core.tests.test_navbar_grouping import TEST_MIDDLEWARE, NavbarTestBase
from core.tests.test_workspace import _Fixture, _login

User = get_user_model()


class CleanReturnToTests(TestCase):

    def test_accepts_a_ticket_path(self):
        got = clean_return_to('/psa/t/PSA-2026-000022/')
        self.assertEqual(got['href'], reverse('psa:ticket_detail', args=['PSA-2026-000022']))
        self.assertEqual(got['label'], 'PSA-2026-000022')

    def test_rejects_absolute_and_external_urls(self):
        for bad in ('https://evil.example/psa/t/PSA-1/', 'http://evil.example/psa/t/PSA-1/',
                    '//evil.example/psa/t/PSA-1/', '///evil.example/psa/t/PSA-1/',
                    '/\\evil.example/psa/t/PSA-1/', '\\\\evil.example\\x', 'javascript:alert(1)',
                    'data:text/html,x', 'psa/t/PSA-1/', ' https://evil.example/', '/%2F%2Fevil.example/'):
            with self.subTest(bad=bad):
                self.assertIsNone(clean_return_to(bad))

    def test_rejects_query_fragment_dots_and_other_pages(self):
        for bad in ('/psa/t/PSA-1/?next=https://evil.example', '/psa/t/PSA-1/#x', '/psa/t/../t/PSA-1/',
                    '/psa/t/./PSA-1/', '/core/dashboard/', '/accounts/organizations/1/', '',
                    None, '/psa/t/' + 'A' * 300 + '/', '/psa/t/PSA%0d%0aSet-Cookie:x/'):
            with self.subTest(bad=bad):
                self.assertIsNone(clean_return_to(bad))

    def test_context_is_empty_without_a_request(self):
        self.assertEqual(return_context(None), {'chip': None, 'origin': '', 'scope': ''})


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TicketWorkflowTests(_Fixture):
    """Workflow A: ticket → client → device and back."""

    def setUp(self):
        _login(self.client, self.tech, self.a)
        self.ticket_path = reverse('psa:ticket_detail', args=[self.t_a.ticket_number])

    def test_ticket_links_its_client_with_a_way_back(self):
        html = self.client.get(self.ticket_path).content.decode()
        self.assertIn('data-ticket-client', html)
        self.assertIn(reverse('accounts:organization_detail', args=[self.a.pk])
                      + '?return_to=' + self.ticket_path, html)

    def test_ticket_trail(self):
        html = self.client.get(self.ticket_path).content.decode()
        self.assertEqual(trail(html), ['Service Desk', 'Tickets', self.t_a.ticket_number])

    def test_client_page_shows_back_to_ticket(self):
        url = reverse('accounts:organization_detail', args=[self.a.pk])
        html = self.client.get(url, {'return_to': self.ticket_path}).content.decode()
        m = re.search(r'<a class="return-ctx__link" href="([^"]+)"[^>]*>(.*?)</a>', html, re.S)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), self.ticket_path)
        self.assertIn(f'Back to {self.t_a.ticket_number}', m.group(2))

    def test_external_return_to_is_ignored(self):
        url = reverse('accounts:organization_detail', args=[self.a.pk])
        for bad in ('https://evil.example/psa/t/X/', '//evil.example/psa/t/X/', '/core/dashboard/'):
            with self.subTest(bad=bad):
                html = self.client.get(url, {'return_to': bad}).content.decode()
                self.assertNotIn('return-ctx__link', html)
                ctx = re.search(r'<div class="return-ctx" id="returnCtx"[^>]*>', html).group(0)
                self.assertIn('data-return-origin=""', ctx)
                self.assertNotIn('evil.example', ctx)

    def test_client_workspace_trail(self):
        url = reverse('accounts:organization_detail', args=[self.a.pk])
        self.assertEqual(trail(self.client.get(url).content.decode()), ['Customers', self.a.name])
        html = self.client.get(url, {'tab': 'tickets'}).content.decode()
        self.assertEqual(trail(html), ['Customers', self.a.name, 'Tickets'])

    def test_open_device_carries_valid_ticket_context_only(self):
        from assets.models import Asset
        asset = Asset.objects.create(organization=self.a, name='UX laptop', asset_type='laptop')
        url = reverse('core:open_device', args=['asset', asset.pk])
        ws = reverse('assets:device_workspace', args=[asset.pk])
        r = self.client.get(url, {'to': 'workspace', 'ticket': self.t_a.ticket_number,
                                  'return_to': self.ticket_path})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r['Location'].startswith(ws + '?'))
        self.assertIn(f'ticket={self.t_a.ticket_number}', r['Location'])
        self.assertIn('return_to=' + self.ticket_path.replace('/', '%2F'), r['Location'])
        r = self.client.get(url, {'to': 'workspace', 'ticket': 'x"><script>',
                                  'return_to': 'https://evil.example/psa/t/X/'})
        self.assertEqual(r['Location'], ws)

    def test_customer_gets_no_chip_or_link_patterns(self):
        _login(self.client, self.customer, self.a)
        url = reverse('accounts:organization_detail', args=[self.a.pk])
        html = self.client.get(url, {'return_to': self.ticket_path}).content.decode()
        self.assertNotIn('returnCtx', html)
        self.assertNotIn('return-ctx__link', html)

    def test_page_carries_the_scope_for_links(self):
        html = self.client.get(self.ticket_path).content.decode()
        m = re.search(r'id="returnCtx" data-return-origin="([^"]*)" data-return-scope="([^"]*)" hidden', html)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), self.ticket_path)  # the ticket itself is the origin
        self.assertIn('/accounts/organizations/{id}/', m.group(2))
        self.assertIn('/assets/{id}/workspace/', m.group(2))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SettingsWorkflowTests(NavbarTestBase):
    """Workflow F: Administration → search → configure → return."""

    def setUp(self):
        super().setUp()
        self.su = self.make_superuser()

    @staticmethod
    def filters(html):
        return {re.sub(r'<[^>]+>', '', label).strip(): text.lower() for text, label in re.findall(
            r'<li data-filter="([^"]*)"><a href="[^"]*">(.*?)</a></li>', html, re.S)}

    def test_center_search_matches_synonyms(self):
        f = self.filters(self.page(self.su, 'core:settings_home'))
        for page, words in (('SMTP / Email', ('email', 'smtp', 'mail')),
                            ('Security Settings', ('2fa', 'mfa', 'two-factor')),
                            ('Firewall &amp; GeoIP', ('geo', 'geoip', 'country')),
                            ('AI &amp; LLM', ('llm', 'ai')),
                            ('SMS Provider', ('sms', 'text'))):
            with self.subTest(page=page):
                self.assertIn(page, f)
                for w in words:
                    self.assertIn(w, f[page])

    def test_center_search_shows_shortcut_hint(self):
        html = self.page(self.su, 'core:settings_home')
        self.assertRegex(html, r'id="settingsCenterSearch"[^>]*aria-keyshortcuts="/"')
        self.assertIn('Find a setting… ( / )', html)

    def test_settings_page_has_way_back_and_trail(self):
        html = self.page(self.su, 'core:settings_smtp')
        self.assertEqual(trail(html), ['Administration', 'Communications', 'SMTP / Email'])
        self.assertRegex(html, r'<a class="settings-ws__home" href="%s"' % re.escape(reverse('core:settings_home')))
        self.assertRegex(html, r'id="settingsSearch"[^>]*aria-keyshortcuts="/"')
        # The trail's first crumb is the settings center.
        self.assertIn(f'<a href="{reverse("core:settings_home")}">Administration</a>', html)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DrawerMarkupTests(NavbarTestBase):

    def test_drawer_controls(self):
        html = self.page(self.make_superuser())
        self.assertRegex(html, r'id="appNavOpen"\s+aria-controls="appNav" aria-expanded="false" aria-label="Open navigation"')
        self.assertIn('id="appNavClose" aria-label="Close navigation"', html)
        self.assertIn('<aside class="app-nav" id="appNav" aria-label="Primary"', html)
        self.assertIn('<div class="app-nav-backdrop" id="appNavBackdrop" hidden></div>', html)
        # The page behind the drawer is what app_nav.js makes inert.
        self.assertIn('<div class="app-main">', html)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PermissionDeniedPageTests(NavbarTestBase):

    def test_customer_403_is_generic(self):
        cust = self.make_customer(role='readonly', username='ux_cust')
        self.client.force_login(cust)
        s = self.client.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.pk
        s.save()
        for name in ('reports:home', 'core:settings_home'):
            with self.subTest(name=name):
                path = reverse(name)
                r = self.client.get(path)
                self.assertEqual(r.status_code, 403)
                html = r.content.decode()
                self.assertIn('data-permission-denied', html)
                self.assertIn("You don't have access to this page", html)
                main = html.split('data-permission-denied', 1)[1].split('</section>', 1)[0]
                self.assertNotIn(path, main)
                self.assertNotIn('MSP staff only', html)  # the exception text is not shown
                self.assertNotIn('Traceback', html)
