"""Command palette (Ctrl+K) and the top bar's Favorites / Recent menus.

core/palette.py, core/palette_views.py, templates/core/_topbar_quick.html,
static/js/command_palette.js. What must hold:

* the shortcut and its button are in every signed-in page, nowhere else;
* every endpoint needs a sign-in;
* search never crosses a tenant boundary, gives customers no MSP-only
  groups, drops groups whose module is off, and never returns a secret
  (passwords are not searched at all);
* favorites and recent entries the user can no longer open (record gone,
  access revoked, module off) are not shown;
* search is rate-limited and its query is not written to the audit log;
* the destination list works with core.navigation.destinations_for and,
  when that does not exist, with the sidebar walk.
"""
import json
import re
from pathlib import Path
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role
from assets.models import Asset
from core import navigation, palette
from core.models import Organization, PageFavorite, RecentPage, SystemSetting
from docs.models import Document
from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
from psa.tests._base import _enable_psa_for, _enable_psa_global, _make_msp_tech, _setup_seed
from vault.models import Password

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]
SECRET = 'S3cr3t-hunter2-zz'


def _no_portal(org):
    from psa.models import ClientPSASettings
    cps, _ = ClientPSASettings.objects.get_or_create(organization=org)
    if hasattr(cps, 'portal_enabled'):
        cps.portal_enabled = False
        cps.save()


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PaletteBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        cls.a = Organization.objects.create(name='Palette Alpha', slug='pal-a')
        cls.b = Organization.objects.create(name='Palette Bravo', slug='pal-b')
        for org in (cls.a, cls.b):
            _enable_psa_for(org)
            _no_portal(org)
        cls.su = User.objects.create_superuser('pal_root', 'root@msp.test', 'pw-pal-123')
        cls.tech = _make_msp_tech(User.objects.create_user('pal_tech', 'tech@msp.test', 'pw-pal-123'))
        cls.cust_a = User.objects.create_user('pal_cust', 'c@a.test', 'pw-pal-123')
        Membership.objects.create(user=cls.cust_a, organization=cls.a, role=Role.OWNER, is_active=True)

        cls.asset_a = Asset.objects.create(organization=cls.a, name='zulu-alpha-server',
                                           serial_number='SNZULU1', hostname='zulu-a.local')
        cls.asset_b = Asset.objects.create(organization=cls.b, name='zulu-bravo-server',
                                           serial_number='SNZULU2', hostname='zulu-b.local')
        cls.doc_a = Document.objects.create(organization=cls.a, title='zulu alpha runbook', body='x',
                                            is_published=True, is_client_visible=True)
        cls.doc_b = Document.objects.create(organization=cls.b, title='zulu bravo runbook', body='x',
                                            is_published=True, is_client_visible=True)
        pw = Password(organization=cls.a, title='zulu alpha router', username='admin')
        if hasattr(pw, 'set_password'):
            pw.set_password(SECRET)
        pw.save()
        cls.pw = pw
        cls.ticket_a = cls._ticket(cls.a, 'zulu alpha printer')
        cls.ticket_b = cls._ticket(cls.b, 'zulu bravo printer')

    @classmethod
    def _ticket(cls, org, subject):
        return Ticket.objects.create(
            organization=org, subject=subject, description='x', client_can_view=True,
            ticket_type=TicketType.objects.first(), queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(),
            status=TicketStatus.objects.filter(is_terminal=False).first())

    def setUp(self):
        cache.clear()

    def c(self, user, org=None):
        c = Client()
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.pk
        else:
            s['global_view_mode'] = True
        s.save()
        return c

    def search(self, client, q='zulu'):
        r = client.get(reverse('core:palette_search'), HTTP_X_PALETTE_QUERY=q)
        self.assertEqual(r.status_code, 200, r.content[:300])
        return r.json()

    @staticmethod
    def flat(data):
        return [(g['key'], i['label'], i['href']) for g in data['groups'] for i in g['items']]


class MarkupTests(PaletteBase):

    def test_signed_in_page_has_shortcut_button_dialog_and_menus(self):
        html = self.c(self.tech, self.a).get(reverse('core:favorite_list')).content.decode()
        self.assertIn('id="cmdkOpen"', html)
        self.assertIn('aria-keyshortcuts="Control+K Meta+K"', html)
        self.assertIn('id="cmdkTemplate"', html)
        tpl = html.split('id="cmdkTemplate"', 1)[1].split('</template>', 1)[0]
        self.assertIn('role="dialog"', tpl)
        self.assertIn('aria-modal="true"', tpl)
        self.assertIn('role="listbox"', tpl)
        self.assertIn('role="combobox"', tpl)
        self.assertIn('id="favMenuToggle"', html)
        self.assertIn('id="recentMenuToggle"', html)
        self.assertIn('js/command_palette.js', html)
        self.assertIn('css/command_palette.css', html)
        # The include sits right before the search box.
        self.assertLess(html.index('id="topbarQuick"'), html.index('topbar-search-item'))
        # No record labels are rendered into the page: the menus load lazily.
        self.assertNotIn('zulu', html.split('id="topbarQuick"', 1)[1].split('topbar-search-item', 1)[0])

    def test_signed_out_page_has_none_of_it(self):
        html = Client().get(reverse('two_factor:login')).content.decode()
        self.assertNotIn('topbarQuick', html)
        self.assertNotIn('command_palette.js', html)

    def test_script_rules(self):
        js = (Path(django_settings.BASE_DIR) / 'static/js/command_palette.js').read_text()
        # Ctrl/Cmd+K, skipped inside rich editors; nothing parsed as HTML.
        self.assertIn("e.ctrlKey || e.metaKey", js)
        self.assertIn('isContentEditable', js)
        self.assertIn('.ql-editor', js)
        self.assertNotIn('innerHTML', js)
        self.assertNotIn('insertAdjacentHTML', js)
        self.assertNotIn('localStorage', js)
        self.assertIn('AbortController', js)
        self.assertIn('X-Palette-Query', js)


class AuthTests(PaletteBase):

    def test_anonymous_is_sent_to_sign_in(self):
        anon = Client()
        for name in ('core:palette_home', 'core:palette_search'):
            r = anon.get(reverse(name), HTTP_X_PALETTE_QUERY='zulu')
            self.assertEqual(r.status_code, 302, name)
            self.assertNotIn(b'zulu', r.content)
        r = anon.post(reverse('core:palette_favorite'), {'path': '/core/dashboard/'})
        self.assertIn(r.status_code, (302, 403))
        self.assertEqual(PageFavorite.objects.count(), 0)

    def test_favorite_toggle_is_post_only(self):
        r = self.c(self.tech).get(reverse('core:palette_favorite'))
        self.assertEqual(r.status_code, 405)


class SearchScopingTests(PaletteBase):

    def test_superuser_sees_both_customers(self):
        data = self.search(self.c(self.su))
        labels = ' '.join(l for _k, l, _h in self.flat(data))
        self.assertIn('zulu-alpha-server', labels)
        self.assertIn('zulu-bravo-server', labels)
        self.assertIn(self.ticket_b.ticket_number, labels)

    def test_customer_of_a_never_sees_b(self):
        data = self.search(self.c(self.cust_a, self.a))
        body = json.dumps(data)
        for leaked in ('zulu-bravo-server', 'zulu bravo runbook', self.ticket_b.ticket_number,
                       'zulu bravo printer', 'Palette Bravo'):
            self.assertNotIn(leaked, body)
        self.assertIn('zulu-alpha-server', body)
        self.assertIn(self.ticket_a.ticket_number, body)

    def test_internal_document_hidden_from_customer_in_both_searches(self):
        Document.objects.create(organization=self.a, title='zulu internal notes', body='x',
                                is_published=True, is_client_visible=False, created_by=self.tech)
        c = self.c(self.cust_a, self.a)
        self.assertNotIn('zulu internal notes', json.dumps(self.search(c)))
        page = c.get(reverse('core:search'), {'q': 'zulu'})
        self.assertNotIn(b'zulu internal notes', page.content)
        # Staff still find it.
        self.assertIn('zulu internal notes', json.dumps(self.search(self.c(self.su))))

    def test_customer_gets_no_msp_only_groups(self):
        data = self.search(self.c(self.cust_a, self.a))
        keys = {g['key'] for g in data['groups']}
        self.assertNotIn('clients', keys)
        self.assertNotIn('reports', keys)
        hrefs = [h for _k, _l, h in self.flat(data)]
        self.assertFalse([h for h in hrefs if h.startswith(('/reports/', '/integrations/rmm/', '/crm/'))])

    def test_ticket_number_and_serial_and_hostname(self):
        c = self.c(self.su)
        data = self.search(c, self.ticket_a.ticket_number)
        self.assertEqual(data['groups'][0]['key'], 'tickets')
        self.assertIn(self.ticket_a.ticket_number, data['groups'][0]['items'][0]['label'])
        for q in ('SNZULU1', 'zulu-a.local'):
            labels = [l for _k, l, _h in self.flat(self.search(c, q))]
            self.assertIn('zulu-alpha-server', labels, q)

    def test_passwords_and_secrets_never_returned(self):
        for user in (self.su, self.tech):
            data = self.search(self.c(user), 'zulu alpha router')
            body = json.dumps(data)
            self.assertNotIn('zulu alpha router', body)
            self.assertNotIn(SECRET, body)
            self.assertNotIn('/vault/', body)
        home = self.c(self.su).get(reverse('core:palette_home')).content.decode()
        self.assertNotIn(SECRET, home)

    def test_disabled_module_results_absent(self):
        row = SystemSetting.get_settings()
        row.psa_enabled = False
        row.save()
        data = self.search(self.c(self.su))
        keys = {g['key'] for g in data['groups']}
        self.assertNotIn('tickets', keys)
        self.assertNotIn('projects', keys)
        self.assertNotIn(self.ticket_a.ticket_number, json.dumps(data))

    def test_short_and_long_queries(self):
        c = self.c(self.su)
        self.assertEqual(self.search(c, 'z')['groups'], [])
        self.search(c, 'z' * 500)  # truncated, not an error

    def test_per_group_cap(self):
        for i in range(8):
            Asset.objects.create(organization=self.a, name=f'zulu-many-{i}')
        data = self.search(self.c(self.su), 'zulu-many')
        devices = next(g for g in data['groups'] if g['key'] == 'devices')
        self.assertLessEqual(len(devices['items']), palette.PER_GROUP * 2)  # assets + RMM devices
        self.assertLessEqual(sum(len(g['items']) for g in data['groups']), palette.TOTAL_LIMIT)

    def test_rate_limited(self):
        c = self.c(self.tech)
        with mock.patch('core.palette_views.SEARCH_RATE', '3/m'):
            codes = [c.get(reverse('core:palette_search'), HTTP_X_PALETTE_QUERY='zz').status_code
                     for _ in range(4)]
        self.assertEqual(codes[:3], [200, 200, 200])
        self.assertEqual(codes[3], 429)
        r = c.get(reverse('core:palette_search'), HTTP_X_PALETTE_QUERY='zz')
        self.assertIn(r.status_code, (200, 429))
        self.assertNotIn(b'zz', r.content)

    def test_query_not_in_audit_log(self):
        from audit.models import AuditLog
        c = self.c(self.su)
        self.search(c, 'needle-in-header')
        c.get(reverse('core:palette_search') + '?q=needle-in-param')
        for row in AuditLog.objects.all():
            blob = json.dumps(row.extra_data or {}) + (row.description or '') + (row.path or '')
            self.assertNotIn('needle', blob)

    def test_search_records_nothing(self):
        from docs.models import SearchQueryLog
        self.search(self.c(self.su), 'nothing-matches-this')
        self.assertFalse(SearchQueryLog.objects.filter(query__icontains='nothing-matches').exists())


class HomeTests(PaletteBase):

    def test_commands_only_for_permitted_targets(self):
        su = self.c(self.su).get(reverse('core:palette_home')).json()
        keys = {c['key'] for c in su['commands']}
        self.assertTrue({'create_ticket', 'create_client', 'my_queue', 'dispatch', 'settings'} <= keys, keys)
        cust = self.c(self.cust_a, self.a).get(reverse('core:palette_home')).json()
        ckeys = {c['key'] for c in cust['commands']}
        self.assertNotIn('create_client', ckeys)
        self.assertNotIn('dispatch', ckeys)
        # A customer-side owner may have an "Open Settings" (their
        # organization settings), never a staff-only one.
        from accounts.middleware import SectionPermissionMiddleware as M
        for cmd in cust['commands']:
            self.assertFalse(cmd['href'].startswith(M.STAFF_ONLY_PREFIXES), cmd)
            self.assertNotEqual(self.c(self.cust_a, self.a).get(cmd['href']).status_code, 403, cmd)
        # Navigation only: every command is a link to a page, nothing posts.
        for cmd in su['commands'] + cust['commands']:
            self.assertTrue(cmd['href'].startswith('/'))

    def test_commands_follow_module_switch(self):
        row = SystemSetting.get_settings()
        row.psa_enabled = False
        row.save()
        keys = {c['key'] for c in self.c(self.su).get(reverse('core:palette_home')).json()['commands']}
        self.assertFalse(keys & {'create_ticket', 'my_queue', 'log_time', 'dispatch'})

    def test_customer_destinations_have_no_staff_only_pages(self):
        from accounts.middleware import SectionPermissionMiddleware as M
        dests = self.c(self.cust_a, self.a).get(reverse('core:palette_home')).json()['destinations']
        self.assertTrue(dests)
        for d in dests:
            self.assertFalse(d['href'].startswith(M.STAFF_ONLY_PREFIXES), d)

    def test_destinations_open(self):
        """Every destination offered opens (no 403) — sampled across the list."""
        c = self.c(self.tech)
        dests = c.get(reverse('core:palette_home')).json()['destinations']
        for d in dests[::7]:
            r = c.get(d['href'])
            self.assertNotEqual(r.status_code, 403, d)


class DestinationSourceTests(PaletteBase):
    """Both ways of getting the destination list."""

    def dests(self, user):
        return self.c(user).get(reverse('core:palette_home'), {'parts': 'destinations'}).json()['destinations']

    def test_sidebar_walk_when_destinations_for_is_missing(self):
        with mock.patch.object(navigation, 'destinations_for', None, create=True):
            dests = self.dests(self.su)
        hrefs = {d['href'] for d in dests}
        self.assertIn(reverse('psa:ticket_list'), hrefs)
        self.assertIn(reverse('core:dashboard'), hrefs)
        # Settings pages come along (Administration categories' tabs).
        self.assertTrue(any(h.startswith('/core/settings/') or h.startswith('/settings/') for h in hrefs))
        self.assertEqual(len(hrefs), len(dests))

    def test_destinations_for_is_used_when_present(self):
        fake = [{'label': 'Only page', 'href': '/core/dashboard/', 'icon': 'fa-house',
                 'group': 'Dashboard', 'section': 'Overview'},
                {'label': 'Bad', 'href': '//evil.example/', 'icon': '', 'group': '', 'section': ''}]
        with mock.patch.object(navigation, 'destinations_for', lambda c: fake, create=True):
            dests = self.dests(self.su)
        self.assertEqual([d['label'] for d in dests], ['Only page'])
        self.assertEqual(dests[0]['icon'], 'fas fa-house')


class FavoritesRecentTests(PaletteBase):

    def home(self, client, **params):
        return client.get(reverse('core:palette_home'), params).json()

    def test_star_a_page_and_a_ticket(self):
        c = self.c(self.tech)
        ticket_path = reverse('psa:ticket_detail', args=[self.ticket_a.ticket_number])
        for path in (reverse('psa:ticket_list'), ticket_path):
            r = c.post(reverse('core:palette_favorite'), {'path': path})
            self.assertEqual(r.status_code, 200, r.content)
            self.assertTrue(r.json()['current']['favorited'])
        favs = self.home(c, parts='favorites')['favorites']
        self.assertIn(ticket_path, [f['href'] for f in favs])
        state = self.home(c, parts='favorites', path=ticket_path)['current']
        self.assertTrue(state['favoritable'] and state['favorited'])
        # Toggle off.
        c.post(reverse('core:palette_favorite'), {'path': ticket_path})
        self.assertNotIn(ticket_path, [f['href'] for f in self.home(c, parts='favorites')['favorites']])

    def test_cannot_star_what_you_cannot_open(self):
        c = self.c(self.cust_a, self.a)
        for path in (reverse('psa:ticket_detail', args=[self.ticket_b.ticket_number]),
                     reverse('reports:home'), '/nowhere/at/all/', 'https://evil.example/x'):
            r = c.post(reverse('core:palette_favorite'), {'path': path})
            self.assertIn(r.status_code, (400, 404), path)
        self.assertEqual(PageFavorite.objects.filter(user=self.cust_a).count(), 0)

    def test_star_asset_uses_existing_favorite_model(self):
        from core.models import Favorite
        c = self.c(self.su)
        path = reverse('assets:asset_detail', args=[self.asset_a.pk])
        r = c.post(reverse('core:palette_favorite'), {'path': path})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Favorite.objects.filter(user=self.su, object_id=self.asset_a.pk).exists())
        self.assertIn(path, [f['href'] for f in self.home(c, parts='favorites')['favorites']])

    def test_revoked_access_drops_favorites_and_recent(self):
        user = User.objects.create_user('pal_rev', 'r@a.test', 'pw-pal-123')
        m = Membership.objects.create(user=user, organization=self.a, role=Role.OWNER, is_active=True)
        tpath = reverse('psa:ticket_detail', args=[self.ticket_a.ticket_number])
        dpath = reverse('docs:document_detail', args=[self.doc_a.slug])
        PageFavorite.objects.create(user=user, path=tpath)
        PageFavorite.objects.create(user=user, path=dpath)
        palette.record_recent_page(user, tpath)
        palette.record_recent_page(user, dpath)
        c = self.c(user, self.a)
        before = self.home(c, parts='favorites,recent')
        self.assertEqual({f['href'] for f in before['favorites']}, {tpath, dpath})
        self.assertEqual({f['href'] for f in before['recent']}, {tpath, dpath})
        m.is_active = False
        m.save()
        after = self.home(self.c(user), parts='favorites,recent')
        self.assertEqual(after['favorites'], [])
        self.assertEqual(after['recent'], [])
        body = json.dumps(after)
        self.assertNotIn('zulu', body)

    def test_deleted_record_and_disabled_module_drop_entries(self):
        c = self.c(self.su)
        tpath = reverse('psa:ticket_detail', args=[self.ticket_a.ticket_number])
        dpath = reverse('docs:document_detail', args=[self.doc_b.slug])
        lpath = reverse('psa:ticket_list')
        for p in (tpath, dpath, lpath):
            PageFavorite.objects.create(user=self.su, path=p)
            palette.record_recent_page(self.su, p)
        self.doc_b.delete()
        got = self.home(c, parts='favorites,recent')
        self.assertNotIn(dpath, [f['href'] for f in got['favorites']])
        self.assertNotIn(dpath, [f['href'] for f in got['recent']])
        row = SystemSetting.get_settings()
        row.psa_enabled = False
        row.save()
        got = self.home(c, parts='favorites,recent')
        hrefs = [f['href'] for f in got['favorites'] + got['recent']]
        self.assertNotIn(tpath, hrefs)
        self.assertNotIn(lpath, hrefs)
        # The rows stay: turning PSA back on brings them back.
        self.assertTrue(PageFavorite.objects.filter(user=self.su, path=tpath).exists())

    def test_middleware_records_pages_and_records_without_query(self):
        c = self.c(self.su)
        c.get(reverse('psa:ticket_list') + '?q=secret-ish')
        c.get(reverse('psa:ticket_detail', args=[self.ticket_a.ticket_number]))
        c.get(reverse('core:palette_home'))  # JSON: not recorded
        paths = set(RecentPage.objects.filter(user=self.su).values_list('path', flat=True))
        self.assertIn(reverse('psa:ticket_list'), paths)
        self.assertIn(reverse('psa:ticket_detail', args=[self.ticket_a.ticket_number]), paths)
        self.assertFalse([p for p in paths if '?' in p or p.startswith('/core/palette')])

    def test_refused_page_is_not_recorded(self):
        c = self.c(self.cust_a, self.a)
        c.get(reverse('psa:ticket_detail', args=[self.ticket_b.ticket_number]))
        self.assertFalse(RecentPage.objects.filter(user=self.cust_a, path__contains=self.ticket_b.ticket_number).exists())

    def test_recent_is_capped(self):
        for i in range(palette.RECENT_KEEP + 5):
            palette.record_recent_page(self.su, f'/psa/t/PSA-X-{i}/')
        self.assertEqual(RecentPage.objects.filter(user=self.su).count(), palette.RECENT_KEEP)
        self.assertLessEqual(len(self.home(self.c(self.su), parts='recent')['recent']), palette.RECENT_SHOW)

    def test_clean_path(self):
        self.assertEqual(palette.clean_path('/a/b/?x=1#f'), '/a/b/')
        for bad in ('//evil/x', 'http://x/', '', 'a/b', '/' + 'x' * 300, '/a\\b'):
            self.assertEqual(palette.clean_path(bad), '', bad)


class NoSecretsInMarkupTests(PaletteBase):

    def test_home_rows_are_labels_and_links_only(self):
        from core.models import Favorite
        from django.contrib.contenttypes.models import ContentType
        Favorite.objects.create(user=self.su, organization=self.a,
                                content_type=ContentType.objects.get_for_model(Password),
                                object_id=self.pw.pk)
        data = self.c(self.su).get(reverse('core:palette_home')).json()
        self.assertNotIn(SECRET, json.dumps(data))
        allowed = {'label', 'href', 'icon', 'type', 'detail', 'path'}
        for row in data['favorites'] + data['recent']:
            self.assertLessEqual(set(row), allowed, row)
        self.assertFalse(re.search(r'encrypted|password_hash|secret', json.dumps(data['favorites']), re.I))
