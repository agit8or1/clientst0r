"""Monitoring lists in Global View (no client selected), v3.17.681.

The website monitor, expiration, rack, subnet, network closet and WAN lists
returned every client's rows in Global View. The page middleware keeps a
client-scoped technician out of Global View (it auto-selects a client in
scope), so with today's middleware this was not reachable with the built-in
roles — but the views themselves did no scoping. They now narrow Global View
to the clients where the user holds monitoring_view, within their reach,
like every other cross-client list. Real roles only (accounts.role_seeds).
"""
from datetime import timedelta

from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from core.tests._r681_fixture import TEST_MIDDLEWARE, R681Base, staff


class _Data(R681Base):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from locations.models import WAN, Location
        from monitoring.models import Expiration, Rack, Subnet, WebsiteMonitor
        for org, tag in ((cls.a, 'alpha'), (cls.b, 'bravo')):
            WebsiteMonitor.objects.create(organization=org, name=f'mon-{tag}-qzx',
                                          url=f'https://{tag}-qzx.test')
            Expiration.objects.create(organization=org, name=f'exp-{tag}-qzx', expiration_type='domain',
                                      expires_at=timezone.now() + timedelta(days=20))
            Rack.objects.create(organization=org, name=f'rack-{tag}-qzx', units=42)
            Rack.objects.create(organization=org, name=f'closet-{tag}-qzx', units=12,
                                rack_type='network_closet')
            Subnet.objects.create(organization=org, name=f'net-{tag}-qzx', network='10.9.0.0/24')
            loc = Location.objects.create(organization=org, name=f'loc-{tag}-qzx')
            WAN.objects.create(organization=org, location=loc, name=f'wan-{tag}-qzx',
                               monitoring_enabled=True, monitor_target='203.0.113.9')
        cls.scoped = staff('r681_mon_scoped', 'service_manager')
        cls.scoped.profile.client_scope = 'selected'
        cls.scoped.profile.save()
        cls.scoped.profile.scope_organizations.set([cls.a])

    LISTS = ('monitoring:website_monitor_list', 'monitoring:expiration_list', 'monitoring:rack_list',
             'monitoring:subnet_list', 'monitoring:network_closet_list', 'monitoring:wan_monitor_list')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class GlobalViewPageTests(_Data):

    def test_scoped_technician_never_sees_other_clients(self):
        c = self.login(self.scoped)  # asks for Global View
        for name in self.LISTS:
            r = c.get(reverse(name))
            self.assertEqual(r.status_code, 200, name)
            self.assertNotIn(b'bravo-qzx', r.content, name)

    def test_unscoped_manager_global_view_sees_every_client(self):
        c = self.login(self.manager)
        r = c.get(reverse('monitoring:website_monitor_list'))
        self.assertContains(r, 'alpha-qzx')
        self.assertContains(r, 'bravo-qzx')
        r = c.get(reverse('monitoring:wan_monitor_list'))
        self.assertContains(r, 'wan-bravo-qzx')

    def test_role_without_monitoring_view_is_refused(self):
        c = self.login(self.sales)
        for name in self.LISTS:
            self.assertEqual(c.get(reverse(name)).status_code, 403, name)


class GlobalViewScopingTests(_Data):
    """The views' own scoping, without the middleware's client
    auto-selection in front of them."""

    def call(self, name, user):
        from django.urls import resolve
        req = RequestFactory().get(reverse(name))
        SessionMiddleware(lambda r: None).process_request(req)
        req.user = user
        req.current_organization = None
        req.is_staff_user = True
        return resolve(reverse(name)).func(req)

    def test_lists_are_narrowed_to_clients_with_monitoring_view(self):
        for name in self.LISTS:
            resp = self.call(name, self.scoped)
            self.assertEqual(resp.status_code, 200, name)
            self.assertNotIn(b'bravo-qzx', resp.content, name)

    def test_full_reach_unchanged(self):
        resp = self.call('monitoring:website_monitor_list', self.su)
        self.assertIn(b'mon-bravo-qzx', resp.content)
        resp = self.call('monitoring:expiration_list', self.su)
        self.assertIn(b'exp-bravo-qzx', resp.content)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WebsiteMonitorCustomerTests(_Data):
    """Each monitor belongs to one customer, shown on the list and detail."""

    def _mon(self, tag):
        from monitoring.models import WebsiteMonitor
        return WebsiteMonitor.objects.get(name=f'mon-{tag}-qzx')

    def test_list_shows_customer_and_searches_by_it(self):
        c = self.login(self.manager)
        r = c.get(reverse('monitoring:website_monitor_list'))
        self.assertContains(r, '<th>Customer</th>', html=True)
        self.assertContains(r, 'Alpha Qzx Co')
        self.assertContains(r, 'Bravo Qzx Co')
        r = c.get(reverse('monitoring:website_monitor_list'), {'q': 'Bravo Qzx'})
        self.assertContains(r, 'mon-bravo-qzx')
        self.assertNotContains(r, 'mon-alpha-qzx')

    def test_detail_shows_customer(self):
        c = self.login(self.manager)
        r = c.get(reverse('monitoring:website_monitor_detail', args=[self._mon('alpha').pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'data-monitor-customer')
        self.assertContains(r, 'Alpha Qzx Co')

    def test_scoped_technician_cannot_open_other_customers_monitor(self):
        c = self.login(self.scoped)
        r = c.get(reverse('monitoring:website_monitor_detail', args=[self._mon('bravo').pk]))
        self.assertEqual(r.status_code, 302)
        r = c.get(reverse('monitoring:website_monitor_detail', args=[self._mon('alpha').pk]), follow=True)
        self.assertContains(r, 'mon-alpha-qzx')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CreateFromGlobalViewTests(_Data):
    """The customer picked on the create form is used (v3.17.727)."""

    def _post(self, org_id):
        c = self.login(self.su)
        return c.post(reverse('monitoring:website_monitor_create'), {
            '_selected_organization_id': org_id, 'name': 'picked-qzx', 'url': 'https://picked-qzx.test',
            'check_interval_minutes': 10, 'is_enabled': 'on', 'ssl_warning_days': 30, 'domain_warning_days': 30,
        })

    def test_selected_customer_is_used(self):
        from monitoring.models import WebsiteMonitor
        self._post(self.b.pk)
        m = WebsiteMonitor.objects.filter(name='picked-qzx').first()
        self.assertIsNotNone(m)
        self.assertEqual(m.organization, self.b)

    def test_inactive_customer_is_refused(self):
        from monitoring.models import WebsiteMonitor
        r = self._post(self.gone.pk)
        self.assertEqual(r.status_code, 302)
        self.assertFalse(WebsiteMonitor.objects.filter(name='picked-qzx').exists())

    def test_picker_lists_only_reachable_customers_and_targets_page_form(self):
        c = self.login(self.su)
        r = c.get(reverse('monitoring:website_monitor_create'))
        self.assertContains(r, 'id="orgSelectorBanner"')
        self.assertContains(r, 'DOCUMENT_POSITION_FOLLOWING')
        self.assertNotContains(r, 'Gone Qzx Co')
