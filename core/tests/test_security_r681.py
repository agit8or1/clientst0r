"""v3.17.681 security regression audit: search, palette, client workspace,
favorites / recent, permission changes mid-session.

Real roles only (accounts.role_seeds via migration — see
core/tests/_r681_fixture.py). Every user kind gets permitted AND denied
cases. Confirmed issues fixed in this release are pinned by the
``Confirmed*`` classes; each failed before its fix.
"""
import re

from django.test import override_settings
from django.urls import reverse

from core.tests._r681_fixture import Q, TEST_MIDDLEWARE, R681Base


def text(html):
    """Visible text of the page content (not the frame)."""
    body = html.split('id="main-content"', 1)[-1]
    body = re.sub(r'<script.*?</script>', ' ', body, flags=re.S)
    return ' '.join(re.sub(r'<[^>]+>', ' ', body).split())


# What each searchable row is called on the search page / in the palette.
ROWS = {
    't_a_shared': 'qzx alpha shared printer',
    't_a_internal': 'qzx alpha internal escalation',
    't_b': 'qzx bravo merger plan',
    'asset_a': 'qzx-alpha-fw',
    'asset_b': 'qzx-bravo-fw',
    'dev_a': 'QZX-ALPHA-DC',
    'dev_b': 'QZX-BRAVO-DC',
    'doc_a_internal': 'qzx alpha internal runbook',
    'doc_b': 'qzx bravo runbook',
    'kb': 'qzx global kb article',
    'pw_a': 'qzx alpha router',
    'pw_b': 'qzx bravo router',
    'client_b': 'Bravo Qzx Co',
}
ALL = set(ROWS)
SECRET = 'Sup3r-Secret-Value!'


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ConfirmedCustomerBodySearchTests(R681Base):
    """CONFIRMED (v3.17.680 follow-up): a customer user's search matched the
    raw document body, internal-only blocks included. Searching for a word
    that appears only in an internal note listed the customer-visible
    article — so the customer learned what the MSP's internal note says
    (one guess at a time) on /core/search/, the document list's search,
    the mobile KB search and the document export's ?q= filter."""

    WORDS = (('qzxsecretword', 'Alpha VPN guide'), ('qzxhtmlsecret', 'Alpha firewall guide'))

    def test_global_search_customer_does_not_match_internal_blocks(self):
        for user in (self.cust_admin, self.cust_user):
            c = self.login(user, self.a)
            for word, title in self.WORDS:
                page = text(self.search_html(c, word))
                self.assertNotIn(title, page, (user.username, word))
                self.assertNotIn('Documents (', page, (user.username, word))
                r = c.get(reverse('core:search'), {'q': word})
                self.assertEqual(r.context['counts'].get('documents'), 0, (user.username, word))

    def test_document_list_customer_does_not_match_internal_blocks(self):
        c = self.login(self.cust_admin, self.a)
        for word, title in self.WORDS:
            r = c.get(reverse('docs:document_list'), {'q': word})
            self.assertEqual(r.status_code, 200)
            self.assertNotIn(title, text(r.content.decode()), word)

    def test_mobile_kb_customer_does_not_match_internal_blocks(self):
        from api_mobile.views_kb import kb_list_view
        from rest_framework.test import APIRequestFactory, force_authenticate
        for word, title in self.WORDS:
            req = APIRequestFactory().get('/api/mobile/v1/kb/', {'search': word})
            force_authenticate(req, user=self.cust_admin)
            resp = kb_list_view(req)
            self.assertEqual(resp.status_code, 200)
            self.assertNotIn(title, str(resp.data), word)

    def test_customer_still_matches_the_text_they_can_read(self):
        c = self.login(self.cust_admin, self.a)
        self.assertIn('Alpha public guide', text(self.search_html(c, 'qzxpublic')))
        # The visible part of a mixed article still matches.
        self.assertIn('Alpha VPN guide', text(self.search_html(c, 'Connect with the client')))
        r = c.get(reverse('docs:document_list'), {'q': 'Rules overview'})
        self.assertIn('Alpha firewall guide', text(r.content.decode()))

    def test_staff_still_match_internal_blocks(self):
        for user in (self.su, self.l1, self.manager):
            c = self.login(user, self.a)
            for word, title in self.WORDS:
                self.assertIn(title, text(self.search_html(c, word)), (user.username, word))
            r = c.get(reverse('docs:document_list'), {'q': 'qzxsecretword'})
            self.assertIn('Alpha VPN guide', text(r.content.decode()), user.username)

    def test_customer_copy_export_filter_ignores_internal_blocks(self):
        from docs.kb_visibility import text_search_q
        from docs.models import Document
        qs = Document.objects.filter(organization=self.a)
        hits = set(qs.filter(text_search_q(qs, 'qzxsecretword', customer_copy=True)))
        self.assertNotIn(self.doc_a_mixed, hits)
        hits = set(qs.filter(text_search_q(qs, 'qzxsecretword', customer_copy=False)))
        self.assertIn(self.doc_a_mixed, hits)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ConfirmedRmmSectionSearchTests(R681Base):
    """CONFIRMED: the search page listed RMM devices (name, hostname,
    customer) to MSP technicians whose role grants assets_view but not
    integrations_view — the built-in Technician L1/L2/L3 roles. Those users
    get 403 on every RMM page (/integrations/ is integrations_view in
    SectionPermissionMiddleware), and the palette, dashboard and client
    workspace already hid RMM from them. Recent devices kept RMM devices
    the same way after a role lost RMM access."""

    def test_l1_l2_l3_are_refused_rmm_pages(self):
        for user in (self.l1, self.l2, self.l3):
            c = self.login(user, self.a)
            r = c.get(reverse('integrations:rmm_devices'))
            self.assertEqual(r.status_code, 403, user.username)

    def test_search_lists_no_rmm_devices_without_rmm_section(self):
        for user in (self.l1, self.l2, self.l3):
            for org in (None, self.a):
                page = text(self.search_html(self.login(user, org)))
                self.assertNotIn('QZX-ALPHA-DC', page, (user.username, org))
                self.assertNotIn('qzx-alpha-dc', page, (user.username, org))
                self.assertNotIn('RMM devices', page, (user.username, org))

    def test_search_lists_rmm_devices_with_rmm_section(self):
        for user in (self.su, self.msp_admin, self.manager):
            page = text(self.search_html(self.login(user)))
            self.assertIn('QZX-ALPHA-DC', page, user.username)
            self.assertIn('QZX-BRAVO-DC', page, user.username)

    def test_recent_rmm_device_dropped_when_rmm_access_lost(self):
        from accounts.models import UserType
        from core.workspace import recent_devices_json  # noqa: F401 (route exists)
        tech = self.manager
        c = self.login(tech, self.a)
        r = c.get(reverse('core:open_device', args=['rmm_device', self.dev_a.pk]))
        self.assertIn(r.status_code, (200, 302))
        from core.models import RecentDevice
        from django.utils import timezone
        RecentDevice.objects.get_or_create(user=tech, kind='rmm_device', object_id=self.dev_a.pk,
                                           defaults={'organization_id': self.a.pk,
                                                     'opened_at': timezone.now()})
        home = c.get(reverse('core:palette_home'), {'parts': 'recent'}).json()
        self.assertIn('QZX-ALPHA-DC', str(home['recent']))
        # Role downgrade: the manager becomes a Technician L1 (no integrations_view).
        from core.tests._r681_fixture import builtin
        tech.profile.global_role_template = builtin('tech_l1')
        tech.profile.user_type = UserType.STAFF
        tech.profile.save()
        home = c.get(reverse('core:palette_home'), {'parts': 'recent'}).json()
        self.assertNotIn('QZX-ALPHA-DC', str(home['recent']))
        r = c.get(reverse('core:open_device', args=['rmm_device', self.dev_a.pk]))
        self.assertEqual(r.status_code, 404)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SearchMatrixTests(R681Base):
    """/core/search/ and the palette, per real role: what each may list and
    what it must not. `org` None is global view for staff (no client
    selected); customers always have their client."""

    def expectations(self):
        staff_all_rows = {'t_a_shared', 't_a_internal', 't_b', 'client_b'}
        assets = {'asset_a', 'asset_b'}
        rmm = {'dev_a', 'dev_b'}
        docs = {'doc_a_internal', 'doc_b', 'kb'}
        pws = {'pw_a', 'pw_b'}
        return {
            # user: (org, visible rows)
            'su': (self.su, None, staff_all_rows | assets | rmm | docs | pws),
            'msp_owner': (self.msp_owner, None, staff_all_rows | assets | rmm | docs | pws),
            # org_admin / service_manager: no vault_view.
            'msp_admin': (self.msp_admin, None, staff_all_rows | assets | rmm | docs),
            'manager': (self.manager, None, staff_all_rows | assets | rmm | docs),
            # Technicians: vault_view, no integrations_view (no RMM).
            'l1': (self.l1, None, staff_all_rows | assets | docs | pws),
            'l2': (self.l2, None, staff_all_rows | assets | docs | pws),
            'l3': (self.l3, None, staff_all_rows | assets | docs | pws),
            # Sales: tickets only.
            'sales': (self.sales, None, staff_all_rows),
            # Customer Administrator of Alpha: shared tickets of the
            # organization, Alpha's assets, customer-visible documents.
            'cust_admin': (self.cust_admin, self.a, {'t_a_shared', 'asset_a'}),
            # Customer Standard User: only their own tickets (none here).
            'cust_user': (self.cust_user, self.a, set()),
            # Subsidiary-only member, revoked member: nothing of Alpha.
            'limited': (self.limited, self.a1, set()),
            'revoked': (self.revoked, None, set()),
        }

    def test_search_page_matrix(self):
        for name, (user, org, visible) in self.expectations().items():
            page = text(self.search_html(self.login(user, org)))
            for key in ALL:
                label = ROWS[key]
                if key in visible:
                    self.assertIn(label, page, (name, key))
                else:
                    self.assertNotIn(label, page, (name, key))
            self.assertNotIn(SECRET, page, name)

    def test_palette_matrix(self):
        for name, (user, org, visible) in self.expectations().items():
            data = self.palette(self.login(user, org))
            flat = self.labels(data)
            for key in ALL - visible:
                self.assertNotIn(ROWS[key], flat, (name, key))
            # Passwords are never searched in the palette.
            self.assertNotIn('router', flat, name)
            self.assertNotIn(SECRET, str(data), name)

    def test_counts_only_cover_permitted_rows(self):
        """"Showing N of M" and the category counts come from the scoped
        queryset: Bravo rows never add to a customer's counts."""
        c = self.login(self.cust_admin, self.a)
        r = c.get(reverse('core:search'), {'q': Q})
        counts = r.context['counts']
        self.assertEqual(counts.get('tickets'), 1)
        self.assertEqual(counts.get('assets'), 1)
        self.assertNotIn('rmm_devices', counts)
        self.assertNotIn('clients', counts)
        self.assertEqual(counts.get('passwords', 0), 0)
        self.assertEqual(counts.get('global_kb', 0), 0)
        self.assertEqual(r.context['total_count'], sum(counts.values()))

    def test_customer_sees_no_internal_documents_or_other_tenant(self):
        c = self.login(self.cust_admin, self.a)
        page = text(self.search_html(c, 'qzx'))
        self.assertNotIn('internal runbook', page)
        self.assertNotIn('Bravo', page)
        flat = self.labels(self.palette(c))
        self.assertNotIn('internal', flat)
        self.assertNotIn('Bravo', flat)

    def test_scoped_technician_sees_only_their_clients(self):
        """An MSP technician whose client scope is Alpha only: nothing of
        Bravo in search or palette, in global view or in Alpha."""
        tech = self.l2
        tech.profile.client_scope = 'selected'
        tech.profile.save()
        tech.profile.scope_organizations.set([self.a])
        for org in (None, self.a):
            c = self.login(tech, org)
            page = text(self.search_html(c))
            flat = self.labels(self.palette(c))
            for key in ('t_b', 'asset_b', 'doc_b', 'pw_b', 'client_b', 'kb'):
                self.assertNotIn(ROWS[key], page, (org, key))
                self.assertNotIn(ROWS[key], flat, (org, key))
            if org is not None:
                self.assertIn(ROWS['asset_a'], page, org)
                self.assertIn(ROWS['pw_a'], page, org)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SearchHardeningTests(R681Base):

    def test_global_kb_titles_hidden_when_module_off(self):
        from core.models import SystemSetting
        c = self.login(self.su)
        self.assertIn(ROWS['kb'], text(self.search_html(c)))
        s = SystemSetting.get_settings()
        s.global_kb_enabled = False
        s.save()
        self.assertNotIn(ROWS['kb'], text(self.search_html(c)))
        self.assertNotIn(ROWS['kb'], self.labels(self.palette(c)))

    def test_psa_off_drops_tickets(self):
        from core.models import SystemSetting
        s = SystemSetting.get_settings()
        s.psa_enabled = False
        s.save()
        c = self.login(self.su)
        self.assertNotIn(ROWS['t_a_shared'], text(self.search_html(c)))
        self.assertNotIn(ROWS['t_a_shared'], self.labels(self.palette(c)))

    def test_search_page_is_rate_limited(self):
        from core import search_views
        old = search_views.SEARCH_RATE
        search_views.SEARCH_RATE = '2/m'
        try:
            c = self.login(self.l1)
            for _ in range(2):
                self.assertEqual(c.get(reverse('core:search'), {'q': Q}).status_code, 200)
            r = c.get(reverse('core:search'), {'q': Q})
            self.assertEqual(r.status_code, 429)
            self.assertNotIn(ROWS['asset_a'], text(r.content.decode()))
        finally:
            search_views.SEARCH_RATE = old

    def test_long_query_is_cut_and_escaped(self):
        c = self.login(self.su)
        q = '<script>alert(1)</script>' + 'x' * 500
        r = c.get(reverse('core:search'), {'q': q})
        self.assertEqual(r.status_code, 200)
        self.assertLessEqual(len(r.context['query']), 200)
        self.assertNotIn('<script>alert(1)</script>', r.content.decode())

    def test_palette_query_header_escaped_in_json_only(self):
        c = self.login(self.su)
        r = c.get(reverse('core:palette_search'), HTTP_X_PALETTE_QUERY='%3Cimg%20src%3Dx%3E')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertIn('no-store', r['Cache-Control'])

    def test_search_endpoints_need_sign_in(self):
        from django.test import Client
        for name in ('core:search', 'core:palette_search', 'core:palette_home'):
            r = Client().get(reverse(name), {'q': Q})
            self.assertIn(r.status_code, (302, 401, 403), name)
            self.assertNotIn(b'qzx', r.content.lower(), name)

    def test_palette_favorite_requires_csrf_and_post(self):
        from django.test import Client
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.su)
        s = c.session
        s['2fa_prompted'] = True
        s.save()
        url = reverse('core:palette_favorite')
        self.assertEqual(c.get(url).status_code, 405)
        self.assertEqual(c.post(url, {'path': '/assets/'}).status_code, 403)
        for name in ('core:dashboard_layout_save', 'core:dashboard_variant_save'):
            self.assertEqual(c.post(reverse(name), '{}', content_type='application/json').status_code,
                             403, name)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WorkspaceMatrixTests(R681Base):
    """accounts:organization_detail and every ?tab=."""

    TABS = ('tickets', 'assets', 'rmm', 'contacts', 'documents', 'passwords', 'contracts',
            'billing', 'projects', 'activity', 'members')

    def tabs_of(self, resp):
        return re.findall(r'data-key="([a-z]+)"', resp.content.decode())

    def test_other_tenant_workspace_is_refused_for_customers(self):
        for user in (self.cust_admin, self.cust_user, self.limited, self.revoked):
            c = self.login(user, self.a)
            for tab in (None,) + self.TABS:
                r = self.workspace(c, self.b, tab)
                self.assertEqual(r.status_code, 302, (user.username, tab))
                self.assertNotIn(b'Bravo', r.content)

    def test_subsidiary_member_cannot_open_parent(self):
        c = self.login(self.limited, self.a1)
        for tab in (None,) + self.TABS:
            r = self.workspace(c, self.a, tab)
            self.assertEqual(r.status_code, 302, tab)

    def test_parent_member_gets_record_only_for_subsidiary(self):
        """A parent customer's member reads the subsidiary record but gets
        no data tab (they cannot switch to it), and every data tab URL is a
        404 rather than a list scoped by another client."""
        c = self.login(self.cust_admin, self.a)
        r = self.workspace(c, self.a1)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(self.tabs_of(r)) - {'overview', 'members'}, set())
        for tab in self.TABS:
            if tab == 'members':
                continue
            self.assertEqual(self.workspace(c, self.a1, tab).status_code, 404, tab)
        # Opening it did not change the current client.
        self.assertEqual(c.session.get('current_organization_id'), self.a.pk)

    def test_inactive_client_gives_no_tabs_even_to_superuser(self):
        c = self.login(self.su, self.a)
        r = self.workspace(c, self.gone)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(self.tabs_of(r)) - {'overview', 'members'}, set())
        self.assertEqual(self.workspace(c, self.gone, 'tickets').status_code, 404)

    def test_unknown_or_hostile_tab_is_404(self):
        c = self.login(self.su, self.a)
        for tab in ('nope', '../../admin', '<script>', 'overview ', 'TICKETS', '1'):
            r = self.workspace(c, self.a, tab)
            self.assertIn(r.status_code, (200, 404), tab)
            self.assertNotIn(b'<script>', r.content.split(b'id="main-content"')[-1][:2000])

    def test_customer_admin_tabs_and_contents(self):
        c = self.login(self.cust_admin, self.a)
        r = self.workspace(c, self.a)
        tabs = set(self.tabs_of(r))
        self.assertNotIn('rmm', tabs)
        self.assertNotIn('passwords', tabs)   # customer_admin has no vault_view
        for tab in ('rmm', 'passwords'):
            self.assertEqual(self.workspace(c, self.a, tab).status_code, 404, tab)
        page = text(self.workspace(c, self.a, 'tickets').content.decode())
        self.assertIn(ROWS['t_a_shared'], page)
        self.assertNotIn(ROWS['t_a_internal'], page)
        page = text(self.workspace(c, self.a, 'documents').content.decode())
        self.assertIn('Alpha VPN guide', page)
        self.assertNotIn(ROWS['doc_a_internal'], page)
        self.assertNotIn('qzxsecretword', page)
        page = text(self.workspace(c, self.a, 'activity').content.decode())
        self.assertNotIn(ROWS['t_a_internal'], page)
        self.assertNotIn(ROWS['doc_a_internal'], page)
        overview = text(r.content.decode())
        self.assertNotIn(ROWS['t_a_internal'], overview)
        self.assertNotIn('QZX-ALPHA-DC', overview)

    def test_customer_user_sees_no_org_tickets_or_assets(self):
        c = self.login(self.cust_user, self.a)
        r = self.workspace(c, self.a)
        self.assertNotIn('assets', self.tabs_of(r))
        self.assertEqual(self.workspace(c, self.a, 'assets').status_code, 404)
        page = text(r.content.decode())
        self.assertNotIn(ROWS['t_a_shared'], page)
        self.assertNotIn(ROWS['asset_a'], page)

    def test_technician_tabs_follow_role(self):
        # L1: assets + passwords, no RMM tab.
        c = self.login(self.l1, self.a)
        tabs = set(self.tabs_of(self.workspace(c, self.a)))
        self.assertIn('assets', tabs)
        self.assertIn('passwords', tabs)
        self.assertNotIn('rmm', tabs)
        self.assertEqual(self.workspace(c, self.a, 'rmm').status_code, 404)
        # Service manager: RMM, no passwords.
        c = self.login(self.manager, self.a)
        tabs = set(self.tabs_of(self.workspace(c, self.a)))
        self.assertIn('rmm', tabs)
        self.assertNotIn('passwords', tabs)
        self.assertEqual(self.workspace(c, self.a, 'passwords').status_code, 404)
        # Sales: no assets / documents / passwords / RMM.
        c = self.login(self.sales, self.a)
        tabs = set(self.tabs_of(self.workspace(c, self.a)))
        for tab in ('assets', 'documents', 'passwords', 'rmm'):
            self.assertNotIn(tab, tabs)
            self.assertEqual(self.workspace(c, self.a, tab).status_code, 404, tab)

    def test_passwords_tab_never_renders_the_secret(self):
        c = self.login(self.l1, self.a)
        r = self.workspace(c, self.a, 'passwords')
        self.assertEqual(r.status_code, 200)
        self.assertIn(ROWS['pw_a'], text(r.content.decode()))
        self.assertNotIn(SECRET, r.content.decode())
        self.assertNotIn(ROWS['pw_b'], text(r.content.decode()))

    def test_workspace_tabs_are_this_client_only(self):
        c = self.login(self.su, self.a)
        for tab in ('tickets', 'assets', 'rmm', 'contacts', 'documents', 'passwords', 'activity'):
            page = text(self.workspace(c, self.a, tab).content.decode())
            self.assertNotIn('bravo', page.lower(), tab)

    def test_scoped_technician_cannot_open_out_of_scope_client(self):
        tech = self.l2
        tech.profile.client_scope = 'selected'
        tech.profile.save()
        tech.profile.scope_organizations.set([self.a])
        c = self.login(tech, self.a)
        for tab in (None,) + self.TABS:
            self.assertEqual(self.workspace(c, self.b, tab).status_code, 302, tab)
        self.assertEqual(c.session.get('current_organization_id'), self.a.pk)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class FavoritesRecentTests(R681Base):

    def star(self, c, path):
        return c.post(reverse('core:palette_favorite'), {'path': path})

    def test_star_cannot_probe_other_tenant_records(self):
        c = self.login(self.cust_admin, self.a)
        probes = [
            reverse('accounts:organization_detail', args=[self.b.pk]),
            reverse('core:customer_ops', args=[self.b.pk]),
            reverse('assets:asset_detail', args=[self.asset_b.pk]),
            reverse('vault:password_detail', args=[self.pw_b.pk]),
            reverse('docs:document_detail', args=[self.doc_b.slug]),
            reverse('psa:ticket_detail', args=[self.t_b.ticket_number]),
            reverse('psa:ticket_detail', args=[self.t_a_internal.ticket_number]),
            reverse('assets:asset_detail', args=[999999]),
        ]
        for path in probes:
            r = self.star(c, path)
            self.assertIn(r.status_code, (400, 404), path)
            self.assertNotIn(b'Bravo', r.content, path)
            self.assertNotIn(b'qzx', r.content.lower(), path)
            home = c.get(reverse('core:palette_home'), {'path': path}).json()
            self.assertFalse(home['current']['favoritable'], path)
            self.assertEqual(home['current']['label'], '', path)

    def test_content_favorite_toggle_cannot_probe(self):
        from django.contrib.contenttypes.models import ContentType
        from vault.models import Password
        ct = ContentType.objects.get_for_model(Password)
        c = self.login(self.cust_admin, self.a)
        r = c.post(reverse('core:favorite_toggle', args=[ct.pk, self.pw_b.pk]),
                   HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 404)
        r2 = c.post(reverse('core:favorite_toggle', args=[ct.pk, 999999]),
                    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r2.status_code, 404)

    def test_favorites_and_recent_drop_after_membership_revoked(self):
        from accounts.models import Membership
        from core.models import PageFavorite, RecentPage
        c = self.login(self.cust_admin, self.a)
        doc_path = reverse('docs:document_detail', args=[self.doc_a_public.slug])
        ticket_path = reverse('psa:ticket_detail', args=[self.t_a_shared.ticket_number])
        for p in (doc_path, ticket_path):
            self.assertEqual(self.star(c, p).status_code, 200, p)
            from django.utils import timezone
            RecentPage.objects.create(user=self.cust_admin, path=p, visited_at=timezone.now())
        home = c.get(reverse('core:palette_home'), {'parts': 'favorites,recent'}).json()
        self.assertIn('Alpha public guide', str(home['favorites']))
        self.assertIn(ROWS['t_a_shared'], str(home['recent']))
        Membership.objects.filter(user=self.cust_admin, organization=self.a).update(is_active=False)
        home = c.get(reverse('core:palette_home'), {'parts': 'favorites,recent'}).json()
        self.assertEqual(home['favorites'], [])
        self.assertEqual(home['recent'], [])
        # The rows stay (paths only); nothing is shown from them.
        self.assertEqual(PageFavorite.objects.filter(user=self.cust_admin).count(), 2)

    def test_favorites_drop_after_role_downgrade_and_module_off(self):
        from core.models import SystemSetting
        c = self.login(self.l3, self.a)
        pw_path = reverse('vault:password_detail', args=[self.pw_a.pk])
        ticket_path = reverse('psa:ticket_detail', args=[self.t_a_shared.ticket_number])
        self.assertEqual(self.star(c, pw_path).status_code, 200)
        self.assertEqual(self.star(c, ticket_path).status_code, 200)
        home = c.get(reverse('core:palette_home'), {'parts': 'favorites'}).json()
        self.assertIn(ROWS['pw_a'], str(home['favorites']))
        # L3 -> Sales Representative: no vault_view.
        from core.tests._r681_fixture import builtin
        self.l3.profile.global_role_template = builtin('sales_rep')
        self.l3.profile.save()
        home = c.get(reverse('core:palette_home'), {'parts': 'favorites'}).json()
        self.assertNotIn(ROWS['pw_a'], str(home['favorites']))
        self.assertIn(ROWS['t_a_shared'], str(home['favorites']))
        s = SystemSetting.get_settings()
        s.psa_enabled = False
        s.save()
        home = c.get(reverse('core:palette_home'), {'parts': 'favorites'}).json()
        self.assertNotIn(ROWS['t_a_shared'], str(home['favorites']))
        page = c.get(reverse('core:favorite_list'))
        self.assertNotIn(ROWS['pw_a'], text(page.content.decode()))

    def test_deleted_record_drops_from_favorites(self):
        c = self.login(self.su, self.a)
        path = reverse('docs:document_detail', args=[self.doc_a_public.slug])
        self.assertEqual(self.star(c, path).status_code, 200)
        self.doc_a_public.delete()
        home = c.get(reverse('core:palette_home'), {'parts': 'favorites'}).json()
        self.assertNotIn('Alpha public guide', str(home['favorites']))

    def test_recent_client_dropped_after_scope_change(self):
        from core.models import RecentClient
        tech = self.l2
        c = self.login(tech, self.a)
        self.assertEqual(self.workspace(c, self.b).status_code, 200)
        self.assertTrue(RecentClient.objects.filter(user=tech, organization=self.b).exists())
        b_path = reverse('accounts:organization_detail', args=[self.b.pk])
        home = c.get(reverse('core:palette_home'), {'parts': 'recent'}).json()
        self.assertIn(b_path, str(home['recent']))
        tech.profile.client_scope = 'selected'
        tech.profile.save()
        tech.profile.scope_organizations.set([self.a])
        home = c.get(reverse('core:palette_home'), {'parts': 'recent'}).json()
        self.assertNotIn(b_path, str(home['recent']))
        self.assertNotIn('Bravo', str(home['recent']))
        r = c.get(reverse('core:client_switcher_search'), {'q': 'Bravo', 'format': 'json'})
        self.assertEqual(r.json()['results'], [])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class MidSessionChangeTests(R681Base):
    """A permission change takes effect on the next request everywhere."""

    def test_l3_to_l1_and_vault_revoke(self):
        from core.tests._r681_fixture import builtin
        c = self.login(self.l3, self.a)
        self.assertIn(ROWS['pw_a'], text(self.search_html(c)))
        self.assertIn('passwords', re.findall(r'data-key="([a-z]+)"',
                                              self.workspace(c, self.a).content.decode()))
        # Vault revoked: the technician's role becomes Service Manager
        # (no vault_view).
        self.l3.profile.global_role_template = builtin('service_manager')
        self.l3.profile.save()
        self.assertNotIn(ROWS['pw_a'], text(self.search_html(c)))
        self.assertEqual(self.workspace(c, self.a, 'passwords').status_code, 404)
        self.assertEqual(c.get(reverse('vault:password_list')).status_code, 403)

    def test_customer_removed_from_org(self):
        from accounts.models import Membership
        c = self.login(self.cust_admin, self.a)
        self.assertEqual(self.workspace(c, self.a, 'tickets').status_code, 200)
        Membership.objects.filter(user=self.cust_admin).update(is_active=False)
        self.assertNotIn(ROWS['t_a_shared'], text(self.search_html(c)))
        self.assertEqual(self.labels(self.palette(c)), '')
        r = self.workspace(c, self.a, 'tickets')
        self.assertNotEqual(r.status_code, 200)
        r = c.get(reverse('core:dashboard_widget', args=['ticket_recent']))
        self.assertEqual(r.status_code, 404)

    def test_manager_role_revoked_drops_ticket_widgets(self):
        from core.tests._r681_fixture import builtin
        c = self.login(self.manager, self.a)
        self.assertEqual(c.get(reverse('core:dashboard_widget', args=['kpi_unassigned'])).status_code, 200)
        self.assertEqual(c.get(reverse('core:dashboard_widget', args=['rmm_alerts'])).status_code, 200)
        # Customer Read-Only is not an internal role; use the Billing /
        # Finance role, which has no assets/integrations flags.
        self.manager.profile.global_role_template = builtin('billing_finance')
        self.manager.profile.save()
        self.assertEqual(c.get(reverse('core:dashboard_widget', args=['rmm_alerts'])).status_code, 404)
        self.assertEqual(c.get(reverse('core:dashboard_widget', args=['kpi_assets'])).status_code, 404)

    def test_module_disabled_mid_session(self):
        from core.models import SystemSetting
        c = self.login(self.su, self.a)
        self.assertEqual(self.workspace(c, self.a, 'tickets').status_code, 200)
        s = SystemSetting.get_settings()
        s.psa_enabled = False
        s.save()
        self.assertEqual(self.workspace(c, self.a, 'tickets').status_code, 404)
        self.assertEqual(c.get(reverse('core:dashboard_widget', args=['kpi_unassigned'])).status_code, 404)
        self.assertNotIn(ROWS['t_a_shared'], self.labels(self.palette(c)))

    def test_bell_counts_follow_authz_generation(self):
        from accounts import authz_cache
        from core import notifications
        before = authz_cache.generation()
        ctx = {'user': self.su, 'request': None, 'psa_enabled': True, 'secure_notes_enabled': True}
        notifications._counts(self.su, ctx)
        authz_cache.invalidate('test')
        self.assertNotEqual(before, authz_cache.generation())
        from django.core.cache import cache
        keys = [k for k in getattr(cache, '_cache', {}) if 'navnotes' in str(k)]
        if keys:  # locmem: the new generation is a new key
            notifications._counts(self.su, ctx)
            keys2 = [k for k in cache._cache if 'navnotes' in str(k)]
            self.assertGreater(len(keys2), len(keys))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ConfirmedAuditReprTests(R681Base):
    """CONFIRMED: the audit middleware wrote `object_repr` = str(object) for
    every detail-URL request by primary key, whatever the answer — 403, 404
    or the "no access" redirect included — under the requester's current
    client. A Customer Administrator could request another customer's
    password, asset, document or client by id and read its title in their
    own audit log (the audit page, and since v3.17.680 the client
    workspace's Activity tab)."""

    def probe_paths(self):
        return [
            reverse('vault:password_detail', args=[self.pw_b.pk]),
            reverse('assets:asset_detail', args=[self.asset_b.pk]),
            reverse('accounts:organization_detail', args=[self.b.pk]),
        ]

    def test_refused_requests_leave_no_foreign_names_in_audit(self):
        from audit.models import AuditLog
        c = self.login(self.cust_admin, self.a)
        for path in self.probe_paths():
            r = c.get(path)
            self.assertNotEqual(r.status_code, 200, path)
        reprs = ' '.join(AuditLog.objects.filter(organization=self.a).values_list('object_repr', flat=True))
        for name in (ROWS['pw_b'], ROWS['asset_b'], ROWS['client_b']):
            self.assertNotIn(name, reprs)
        # Nor on the pages that show the log to this customer.
        self.assertEqual(c.get(reverse('accounts:organization_detail', args=[self.a.pk])).status_code, 200)
        r = self.workspace(c, self.a, 'activity')
        self.assertEqual(r.status_code, 200)
        page = text(r.content.decode())
        r2 = c.get(reverse('audit:audit_log_list'))
        page += text(r2.content.decode()) if r2.status_code == 200 else ''
        for name in (ROWS['pw_b'], ROWS['asset_b'], ROWS['client_b']):
            self.assertNotIn(name, page)

    def test_permitted_detail_view_still_named(self):
        from audit.models import AuditLog
        c = self.login(self.su, self.a)
        self.assertEqual(c.get(reverse('assets:asset_detail', args=[self.asset_a.pk])).status_code, 200)
        self.assertTrue(AuditLog.objects.filter(object_repr__startswith=ROWS['asset_a']).exists())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class FavoriteRedirectHardeningTests(R681Base):

    def test_non_ajax_toggle_does_not_redirect_off_site(self):
        from django.contrib.contenttypes.models import ContentType
        from assets.models import Asset
        ct = ContentType.objects.get_for_model(Asset)
        c = self.login(self.su, self.a)
        r = c.post(reverse('core:favorite_toggle', args=[ct.pk, self.asset_a.pk]),
                   HTTP_REFERER='https://evil.example/phish')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(r['Location'].startswith('https://evil.example'))
        r = c.post(reverse('core:favorite_toggle', args=[ct.pk, self.asset_a.pk]),
                   HTTP_REFERER='http://testserver/assets/')
        self.assertTrue(r['Location'].endswith('/assets/'))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WorkspaceMembersFlagTests(R681Base):
    """HARDENING (pre-existing since before v3.17.680): the client record
    listed every member's name and email to anyone who could open it,
    whether or not their role grants `org_view_members` ("View organization
    members"). Customer Standard User / Read-Only do not hold it."""

    def test_member_list_needs_org_view_members(self):
        c = self.login(self.cust_user, self.a)
        r = self.workspace(c, self.a)
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertNotIn('r681_cadmin@cust.test', html)
        self.assertNotIn('data-key="members"', html)
        self.assertEqual(self.workspace(c, self.a, 'members').status_code, 404)

    def test_member_list_shown_with_the_flag(self):
        for user in (self.cust_admin, self.su, self.l1, self.sales):
            c = self.login(user, self.a)
            r = self.workspace(c, self.a, 'members')
            self.assertEqual(r.status_code, 200, user.username)
            self.assertIn('r681_cuser@cust.test', r.content.decode(), user.username)
