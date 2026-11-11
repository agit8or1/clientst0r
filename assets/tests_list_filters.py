"""The asset list's filters, sort, paging and saved-views bar
(assets/list_filters.py, assets.views.asset_list, core.workspace)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership
from assets.models import Asset
from core.models import Organization, SavedView
from integrations.models import RMMAlert, RMMConnection, RMMDevice
from psa.tests._base import TEST_MIDDLEWARE, _make_msp_tech

URL = reverse('assets:asset_list')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AssetListFilterTests(TestCase):

    def setUp(self):
        User = get_user_model()
        self.parent = Organization.objects.create(name='Filter Parent', slug='filter-parent')
        self.site = Organization.objects.create(name='Filter Site', slug='filter-site', parent=self.parent)
        self.other = Organization.objects.create(name='Filter Other', slug='filter-other')
        self.tech = _make_msp_tech(User.objects.create_user('alf_tech', 'alf@x.test', 'pw'))
        Membership.objects.create(user=self.tech, organization=self.parent, role='admin')
        self.cust = User.objects.create_user('alf_cust', 'alfc@x.test', 'pw')
        Membership.objects.create(user=self.cust, organization=self.parent, role='owner')

        self.srv = Asset.objects.create(organization=self.parent, name='alpha-srv', asset_type='server',
                                        serial_number='SN-ALPHA')
        self.ws = Asset.objects.create(organization=self.site, name='bravo-ws', asset_type='workstation',
                                       custom_fields={'location': 'Main Street'})
        self.stale = Asset.objects.create(organization=self.parent, name='charlie-nas', asset_type='server')
        self.bare = Asset.objects.create(organization=self.parent, name='delta-printer', asset_type='printer')
        self.foreign = Asset.objects.create(organization=self.other, name='zulu-foreign', asset_type='server')

        self.conn = RMMConnection.objects.create(organization=self.parent, name='Filter RMM',
                                                 provider_type='ninjaone', base_url='https://rmm.example',
                                                 sync_interval_minutes=60)
        now = timezone.now()

        def device(asset, ext, online, refreshed):
            return RMMDevice.objects.create(
                organization=asset.organization, connection=self.conn, external_id=ext,
                device_name=asset.name.upper(), is_online=online, last_seen=now,
                data_refreshed_at=refreshed, linked_asset=asset,
                ownership_status=RMMDevice.OWNERSHIP_RESOLVED)

        self.d_srv = device(self.srv, 'd1', True, now)
        self.d_ws = device(self.ws, 'd2', False, now)
        device(self.stale, 'd3', True, now - timedelta(days=2))
        RMMAlert.objects.create(organization=self.parent, connection=self.conn, device=self.d_ws,
                                external_id='a1', alert_type='Disk', message='Disk full',
                                severity='critical', status='active', triggered_at=now)
        # An unsettled device linked to the printer must not count for it.
        RMMDevice.objects.create(organization=self.parent, connection=self.conn, external_id='d4',
                                 device_name='PRN', is_online=True, data_refreshed_at=now,
                                 linked_asset=self.bare, ownership_status=RMMDevice.OWNERSHIP_UNRESOLVED)

    def login(self, user, org=None):
        self.client.force_login(user)
        s = self.client.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = (org or self.parent).pk
        s.save()

    def names(self, **params):
        r = self.client.get(URL, params)
        self.assertEqual(r.status_code, 200)
        return [a.name for a in r.context['assets']]

    def test_default_sort_is_by_name_and_scoped_to_the_customer_and_its_sites(self):
        self.login(self.tech)
        self.assertEqual(self.names(), ['alpha-srv', 'bravo-ws', 'charlie-nas', 'delta-printer'])

    def test_existing_parameters_keep_working(self):
        self.login(self.tech)
        self.assertEqual(self.names(type='server'), ['alpha-srv', 'charlie-nas'])
        self.assertEqual(self.names(location='main'), ['bravo-ws'])
        self.assertEqual(self.names(search='SN-ALPHA'), ['alpha-srv'])

    def test_customer_filter_accepts_only_customers_in_scope(self):
        self.login(self.tech)
        self.assertEqual(self.names(client=self.site.pk), ['bravo-ws'])
        # Another customer's id is ignored, never a way in.
        self.assertNotIn('zulu-foreign', self.names(client=self.other.pk))

    def test_rmm_state_and_alert_filters(self):
        self.login(self.tech)
        self.assertEqual(self.names(rmm='online'), ['alpha-srv'])
        self.assertEqual(self.names(rmm='offline'), ['bravo-ws'])
        self.assertEqual(self.names(rmm='stale'), ['charlie-nas'])
        self.assertEqual(self.names(rmm='unlinked'), ['delta-printer'])
        self.assertEqual(self.names(alerts='active'), ['bravo-ws'])

    def test_rmm_filters_are_staff_only(self):
        self.login(self.cust)
        self.assertEqual(self.names(rmm='online'), ['alpha-srv', 'bravo-ws', 'charlie-nas', 'delta-printer'])
        html = self.client.get(URL).content.decode()
        self.assertNotIn('name="rmm"', html)
        self.assertNotIn('RMM offline', html)  # staff preset

    def test_sort_and_paging(self):
        self.login(self.tech)
        self.assertEqual(self.names(sort='-name'), ['delta-printer', 'charlie-nas', 'bravo-ws', 'alpha-srv'])
        for i in range(30):
            Asset.objects.create(organization=self.parent, name=f'extra-{i:02d}', asset_type='other')
        r = self.client.get(URL, {'per_page': 25, 'page': 2, 'type': 'other'})
        self.assertEqual(len(r.context['assets']), 5)
        self.assertEqual(r.context['total_count'], 30)
        from django.http import QueryDict
        kept = QueryDict(r.context['page_query'])
        self.assertEqual(kept.get('per_page'), '25')
        self.assertNotIn('page', kept)  # pagination links add their own
        # An unknown page size falls back to the default.
        self.assertEqual(self.client.get(URL, {'per_page': 7}).context['per_page'], 50)

    def test_rmm_column_shows_status(self):
        self.login(self.tech)
        html = self.client.get(URL).content.decode()
        self.assertIn('>Online</span>', html)
        self.assertIn('>Stale</span>', html)
        self.assertIn('active alert', html)

    def test_saved_views_bar_with_presets(self):
        self.login(self.tech)
        html = self.client.get(URL, {'rmm': 'offline'}).content.decode()
        self.assertIn('id="savedViews"', html)
        self.assertIn('RMM offline', html)
        self.client.post(reverse('core:saved_view_save'), {
            'list_key': 'assets', 'name': 'Offline servers', 'query': 'rmm=offline&type=server&page=3',
            'is_default': '1'})
        view = SavedView.objects.get(user=self.tech, list_key='assets')
        self.assertEqual(view.query, 'type=server&rmm=offline')
        # The default view opens on a bare visit; ?view=all skips it.
        r = self.client.get(URL)
        self.assertRedirects(r, f'{URL}?type=server&rmm=offline', fetch_redirect_response=False)
        self.assertEqual(self.client.get(URL, {'view': 'all'}).status_code, 200)

    def test_empty_states(self):
        self.login(self.tech)
        html = self.client.get(URL, {'q': 'nothing-matches'}).content.decode()
        self.assertIn('No assets match these filters', html)
        empty = Organization.objects.create(name='Filter Empty', slug='filter-empty')
        Membership.objects.create(user=self.tech, organization=empty, role='admin')
        self.login(self.tech, empty)
        html = self.client.get(URL).content.decode()
        self.assertIn('No assets yet', html)
        self.assertIn('No saved views yet', html)
