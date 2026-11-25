"""Standalone UI (docs/ux/STANDALONE_REQUIREMENTS.md P0-3, increment 113.6):
with no enabled RMM connection, RMM-only navigation, palette entries,
dashboard widgets, client workspace tab and figure, and the ticket page's
"No RMM reports this asset" line are absent. With one enabled connection
they appear; disabling or deleting the last one hides them again without
anyone clearing a cache. Saved dashboard layouts are never rewritten.
"""
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from core.tests.test_navbar_grouping import TEST_MIDDLEWARE, NavbarTestBase, sidebar
from integrations import presence
from integrations.models import RMMConnection, RMMDevice

User = get_user_model()

RMM_NAV = ('integrations:rmm_devices', 'integrations:rmm_alerts')
RMM_WIDGETS = ('kpi_rmm_alerts', 'rmm_alerts')
RMM_GLOBAL_WIDGETS = ('g_kpi_rmm', 'g_rmm_alerts')


def _hrefs(html):
    return [h for hrefs in sidebar(html).values() for h in hrefs]


def _rmm(org=None, **kw):
    kw.setdefault('name', 'Standalone RMM')
    return RMMConnection.objects.create(organization=org, provider_type='tactical_rmm',
                                        base_url='https://rmm.standalone.test', **kw)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class StandaloneUITests(NavbarTestBase):
    with_rmm = False

    def setUp(self):
        super().setUp()
        self.su = self.make_superuser()
        self.tech = self.make_technician()

    def login(self, user, org=None):
        self.client.force_login(user)
        s = self.client.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.pk
        else:
            s.pop('current_organization_id', None)
        s.save()

    def get(self, path, user, org=None):
        self.login(user, org)
        r = self.client.get(path, follow=True)
        self.assertEqual(r.status_code, 200, path)
        return r.content.decode()

    # -- navigation and palette ---------------------------------------------

    def assert_rmm_nav(self, user, shown):
        html = self.get(reverse('core:dashboard'), user, self.org)
        hrefs = _hrefs(html)
        self.assertTrue(hrefs, 'sidebar must not be empty')
        for name in RMM_NAV:
            (self.assertIn if shown else self.assertNotIn)(reverse(name), hrefs, (user.username, name))
        data = self.client.get(reverse('core:palette_home')).json()
        dests = [d['href'] for d in data.get('destinations', [])]
        for name in RMM_NAV:
            (self.assertIn if shown else self.assertNotIn)(reverse(name), dests, (user.username, 'palette', name))
        commands = {c.get('key'): c.get('href') for c in data.get('commands', [])}
        if not shown:
            self.assertNotEqual(commands.get('alerts'), reverse('integrations:rmm_alerts'))

    def test_navigation_and_palette_follow_the_rmm_connection(self):
        for user in (self.su, self.tech):
            self.assert_rmm_nav(user, shown=False)
        conn = _rmm()
        for user in (self.su, self.tech):
            self.assert_rmm_nav(user, shown=True)
        # Disabling the last connection hides them again (no cache cleared here).
        conn.is_active = False
        conn.save()
        for user in (self.su, self.tech):
            self.assert_rmm_nav(user, shown=False)
        conn.is_active = True
        conn.save()
        self.assert_rmm_nav(self.su, shown=True)
        conn.delete()
        self.assert_rmm_nav(self.su, shown=False)

    def test_rmm_pages_keep_their_own_empty_state(self):
        # Hiding is presentation only: the pages still open and point admins
        # to Administration → Integrations.
        for name in RMM_NAV:
            html = self.get(reverse(name), self.su, self.org)
            self.assertIn(reverse('integrations:integration_list'), html, name)

    def test_presence_ignores_disabled_connections_and_follows_saves(self):
        self.assertFalse(presence.rmm_configured())
        conn = _rmm(is_active=False)
        self.assertFalse(presence.rmm_configured())
        conn.is_active = True
        conn.save()
        self.assertTrue(presence.rmm_configured())
        # A save that changes nothing that matters does not bump the access generation.
        from accounts import authz_cache
        before = authz_cache.local_generation()
        conn.last_sync_status = 'ok'
        conn.save()
        self.assertEqual(authz_cache.local_generation(), before)

    # -- dashboards -----------------------------------------------------------

    def widget_keys(self, user, org):
        html = self.get(reverse('core:dashboard'), user, org)
        import re
        return set(re.findall(r'id="dash-w-([a-z0-9_]+)"', html)) | set(re.findall(r'data-kpi="([a-z0-9_]+)"', html)) \
            | set(re.findall(r'data-key="([a-z0-9_]+)"', html)), html

    def test_role_presets_drop_rmm_widgets_without_an_rmm(self):
        from core import dashboard_widgets as dw
        from django.test import RequestFactory
        for preset in (dw.PRESET_ADMIN, dw.PRESET_L3, dw.PRESET_L2):
            # The built-in lists still name them (they come back with an RMM) ...
            self.assertTrue(set(RMM_WIDGETS) & set(dw._PRESETS[preset]), preset)
        # ... but no layout offers them while no RMM is connected.
        rf = RequestFactory()
        for preset_user in (self.su, self.tech):
            req = rf.get('/')
            req.user = preset_user
            req.current_organization = self.org
            req.session = {}
            for key in RMM_WIDGETS:
                self.assertFalse(dw.widget_available(req, dw.get(key)), (preset_user.username, key))
        keys, html = self.widget_keys(self.su, self.org)
        for key in RMM_WIDGETS:
            self.assertNotIn(key, keys)
        self.assertNotIn('RMM alerts', html)
        _rmm()
        keys, _html = self.widget_keys(self.su, self.org)
        self.assertIn('kpi_rmm_alerts', keys)

    def test_l2_and_l3_presets(self):
        from core import dashboard_widgets as dw
        from django.test import RequestFactory
        rf = RequestFactory()
        req = rf.get('/')
        req.user = self.tech
        req.current_organization = self.org
        req.session = {}
        for preset in (dw.PRESET_L3, dw.PRESET_L2):
            layout = dw.preset_layout(preset)
            shown = [p.key for p in dw.visible_widgets(req, layout) if not p.hidden]
            for key in RMM_WIDGETS:
                self.assertNotIn(key, shown, preset)
        _rmm()
        req = rf.get('/')
        req.user = self.tech
        req.current_organization = self.org
        req.session = {}
        shown = [p.key for p in dw.visible_widgets(req, dw.preset_layout(dw.PRESET_L2)) if not p.hidden]
        self.assertIn('rmm_alerts', shown)

    def test_saved_layout_is_kept_and_rmm_widgets_come_back(self):
        profile = self.su.profile
        saved = {'order': ['rmm_alerts', 'kpi_rmm_alerts', 'my_queue'], 'hidden': [], 'sizes': {}}
        profile.dashboard_layout = saved
        profile.save()
        keys, _html = self.widget_keys(self.su, self.org)
        self.assertNotIn('rmm_alerts', keys)
        self.assertNotIn('kpi_rmm_alerts', keys)
        profile.refresh_from_db()
        self.assertEqual(profile.dashboard_layout, saved)
        _rmm()
        keys, _html = self.widget_keys(self.su, self.org)
        self.assertIn('rmm_alerts', keys)
        self.assertIn('kpi_rmm_alerts', keys)

    def global_keys(self):
        import re
        self.login(self.su)
        s = self.client.session
        s['global_view_mode'] = True
        s.save()
        html = self.client.get(reverse('core:dashboard')).content.decode()
        return (set(re.findall(r'id="dash-w-([a-z0-9_]+)"', html)) | set(re.findall(r'data-kpi="([a-z0-9_]+)"', html))
                | set(re.findall(r'data-key="([a-z0-9_]+)"', html)))

    def test_global_view_has_no_rmm_widgets(self):
        keys = self.global_keys()
        self.assertIn('g_kpi_open', keys)  # it is the Global View
        for key in RMM_GLOBAL_WIDGETS:
            self.assertNotIn(key, keys)
        _rmm()
        self.assertTrue(set(RMM_GLOBAL_WIDGETS) & self.global_keys())

    # -- client workspace -------------------------------------------------------

    def workspace(self, tab=None):
        url = reverse('accounts:organization_detail', args=[self.org.pk]) + (f'?tab={tab}' if tab else '')
        self.login(self.su, self.org)
        return self.client.get(url)

    def test_client_workspace_rmm_tab_and_figure(self):
        from accounts.tests_client_workspace import _tabs
        html = self.workspace().content.decode()
        self.assertNotIn('rmm', _tabs(html))
        self.assertNotIn('RMM offline', html)
        self.assertNotIn('RMM devices', html)
        self.assertEqual(self.workspace('rmm').status_code, 404)
        # A platform connection that brought in nothing for this client: still none.
        conn = _rmm()
        html = self.workspace().content.decode()
        self.assertNotIn('rmm', _tabs(html))
        # A device of this client from an enabled connection: tab, figure, honest button.
        RMMDevice.objects.create(organization=self.org, connection=conn, external_id='d-1', device_name='NAV-01',
                                 ownership_status=RMMDevice.OWNERSHIP_RESOLVED)
        presence.clear()  # device arrival is picked up by TTL; not waiting 30 s here
        html = self.workspace().content.decode()
        self.assertIn('rmm', _tabs(html))
        self.assertIn('RMM offline', html)
        tab = self.workspace('rmm').content.decode()
        self.assertIn('All RMM devices', tab)
        self.assertNotIn('Open in RMM', tab)
        # Disabled: hidden again.
        conn.is_active = False
        conn.save()
        self.assertNotIn('rmm', _tabs(self.workspace().content.decode()))

    def test_client_workspace_with_the_clients_own_connection(self):
        from accounts.tests_client_workspace import _tabs
        _rmm(org=self.org)
        self.assertIn('rmm', _tabs(self.workspace().content.decode()))

    # -- ticket page ----------------------------------------------------------------

    def test_ticket_page_says_nothing_about_rmm_without_one(self):
        from assets.models import Asset
        from psa.tests._base import _enable_psa_global, _setup_seed
        from psa.tests.test_ticket_site import _ticket
        _setup_seed()
        _enable_psa_global()
        asset = Asset.objects.create(organization=self.org, name='FRONT-01', asset_type='workstation')
        t = _ticket(self.org, related_asset=asset)
        html = self.get(reverse('psa:ticket_detail', args=[t.ticket_number]), self.su, self.org)
        self.assertIn('id="ticket-asset-card"', html)
        self.assertNotIn('No RMM reports this asset', html)
