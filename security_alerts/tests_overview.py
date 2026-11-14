"""v3.17.681 — operational Security Overview (/security/overview/) and the
alert -> incident -> device -> RMM links on the detail pages.

Authorization follows the pages the overview summarises: the view is
require_perm('security_alerts_view') under the staff-only /security/
prefix; each widget and drill-down link is drawn only where its own page
would open. Counts are scoped like the source lists, and a source with
nothing set up says "Not configured", never a fake 0.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role, RoleTemplate, UserType
from core.models import Organization, SystemSetting
from psa.tests._base import TEST_MIDDLEWARE
from security_alerts.models import (
    SecurityAlert, SecurityIncident, SecurityVendorConnection,
)

URL = '/security/overview/'


def _staff(username, **perms):
    u = User.objects.create_user(username, f'{username}@x.test', 'pw')
    u.profile.user_type = UserType.STAFF
    if perms:
        u.profile.global_role_template = RoleTemplate.objects.create(name=f'role {username}', **perms)
    u.profile.save()
    return u


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class OverviewBase(TestCase):
    def setUp(self):
        cache.clear()
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.monitoring_enabled = True
        s.save()
        self.a = Organization.objects.create(name='Sec Ov A', slug='secov-a')
        self.b = Organization.objects.create(name='Sec Ov B', slug='secov-b')
        self.su = User.objects.create_user('secov_su', 'su@x.test', 'pw', is_superuser=True, is_staff=True)

    def login(self, user, org=None):
        self.client.force_login(user)
        s = self.client.session
        s['2fa_prompted'] = True
        if org == 'global':
            # No client selected (the middleware otherwise picks one).
            s.pop('current_organization_id', None)
            s['global_view_mode'] = True
        elif org is not None:
            s['current_organization_id'] = org.pk
            s.pop('global_view_mode', None)
        s.save()

    def conn(self, org, name='Defender', **kw):
        return SecurityVendorConnection.objects.create(
            organization=org, name=name, provider='defender', category='edr', **kw)

    def alert(self, org, ext, conn=None, **kw):
        conn = conn or SecurityVendorConnection.objects.filter(organization=org).first() or self.conn(org)
        kw.setdefault('severity', 'high')
        return SecurityAlert.objects.create(connection=conn, organization=org, external_id=ext,
                                            title=f'alert {ext}', **kw)

    def get(self, user, org=None):
        self.login(user, org)
        return self.client.get(URL)


class AuthorizationMatrixTests(OverviewBase):
    def test_anonymous_redirects_to_login(self):
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r['Location'])

    def test_superuser_sees_every_widget(self):
        self.alert(self.a, 'x1')
        r = self.get(self.su)
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        for heading in ('Security Alerts', 'Incidents', 'RMM Security', 'Monitoring', 'Response Performance'):
            self.assertIn(heading, html)
        self.assertIn(reverse('reports:security_alert_mtta'), html)

    def test_msp_admin_with_view_and_sla_reports(self):
        admin = _staff('secov_admin', security_alerts_view=True, reports_view_sla=True,
                       integrations_view=True, monitoring_view=True)
        self.alert(self.a, 'x1')
        r = self.get(admin)
        self.assertEqual(r.status_code, 200)
        self.assertIn('MTTA', r.content.decode())

    def test_technician_without_security_alerts_view_gets_403(self):
        tech = _staff('secov_noview', security_alerts_view=False)
        self.assertEqual(self.get(tech).status_code, 403)

    def test_customer_user_gets_403_even_with_the_flag(self):
        # Customer roles grant security_alerts_view by default; /security/ is
        # staff-only (SectionPermissionMiddleware).
        cust = User.objects.create_user('secov_cust', 'c@x.test', 'pw')
        Membership.objects.create(user=cust, organization=self.a, role=Role.OWNER,
                                  role_template=RoleTemplate.objects.create(name='secov cust', security_alerts_view=True))
        self.assertEqual(self.get(cust, self.a).status_code, 403)

    def test_page_is_read_only(self):
        self.alert(self.a, 'x1')
        html = self.get(self.su).content.decode()
        # The page body (the frame's own forms, e.g. the client switcher, aside).
        body = html.split('<div class="ui-page-head">', 1)[1].split('<!-- /security-overview -->', 1)[0]
        self.assertIn('Response Performance', body)
        self.assertNotIn('<form', body)
        self.assertNotIn('method="post"', body.lower())

    def test_monitoring_module_off_hides_the_monitoring_widget(self):
        s = SystemSetting.get_settings()
        s.monitoring_enabled = False
        s.save()
        html = self.get(self.su).content.decode()
        self.assertNotIn('id="so-mon"', html)
        self.assertNotIn(reverse('monitoring:website_monitor_list'), html.split('id="main-content"', 1)[1])

    def test_widgets_follow_their_own_pages(self):
        # security_alerts_view only: no MTTA report (reports_view_sla across
        # every customer), no RMM widget (integrations_view), no monitoring
        # widget (monitoring_view).
        tech = _staff('secov_viewonly', security_alerts_view=True, reports_view_sla=False,
                      integrations_view=False, monitoring_view=False)
        self.alert(self.a, 'x1', acknowledged_at=timezone.now())
        r = self.get(tech, self.a)
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        main = html.split('id="main-content"', 1)[1]
        self.assertNotIn(reverse('reports:security_alert_mtta'), main)
        self.assertNotIn('id="so-rmm"', main)
        self.assertNotIn('id="so-mon"', main)
        self.assertIn('needs the SLA reports permission', main)
        # The pages this user may open are linked.
        self.assertIn(reverse('security_alerts:alert_list'), main)
        self.assertIn(reverse('security_alerts:incident_list'), main)


class ScopingTests(OverviewBase):
    def test_org_a_user_does_not_count_org_b(self):
        tech = _staff('secov_scoped', security_alerts_view=True)
        tech.profile.client_scope = 'selected'
        tech.profile.save()
        tech.profile.scope_organizations.add(self.a)
        self.alert(self.a, 'a1', severity='critical')
        for i in range(5):
            self.alert(self.b, f'b{i}', severity='critical')
        SecurityIncident.objects.create(organization=self.b, title='B incident', severity='critical')
        r = self.get(tech, self.a)
        self.assertEqual(r.status_code, 200)
        alerts = r.context['alerts']['counts']
        self.assertEqual(alerts['critical'], 1)
        self.assertEqual(alerts['active'], 1)
        self.assertEqual(r.context['incidents']['counts']['open'], 0)
        # The superuser sees both customers.
        r = self.get(self.su)
        self.assertEqual(r.context['alerts']['counts']['critical'], 6)
        self.assertEqual(r.context['incidents']['counts']['open'], 1)

    def test_counts(self):
        c = self.conn(self.a)
        self.alert(self.a, '1', conn=c, severity='critical', status='new')
        self.alert(self.a, '2', conn=c, severity='high', status='acknowledged', asset_hint='WS-1')
        self.alert(self.a, '3', conn=c, severity='high', status='resolved')
        ctx = self.get(self.su).context
        counts = ctx['alerts']['counts']
        self.assertEqual((counts['active'], counts['critical'], counts['high'], counts['unacked'], counts['device']),
                         (2, 1, 1, 1, 1))


class StateTests(OverviewBase):
    def test_not_configured_when_no_alert_source(self):
        ctx = self.get(self.su).context
        self.assertEqual(ctx['alerts']['state'], 'not_configured')
        self.assertEqual(ctx['incidents']['state'], 'not_configured')
        self.assertContains(self.client.get(URL), 'Not configured')

    def test_configured_source_with_no_alerts_shows_zero_and_no_data(self):
        self.conn(self.a, last_sync_status='ok', last_sync_at=timezone.now())
        r = self.get(self.su)
        self.assertEqual(r.context['alerts']['state'], '')
        self.assertEqual(r.context['alerts']['counts']['active'], 0)
        # No acknowledged alert: MTTA cannot be derived, so "No data", not 0.
        self.assertIsNone(r.context['response']['alert']['mtta'])
        self.assertIsNone(r.context['response']['incident']['tta'])
        self.assertContains(r, 'No data')

    def test_mtta_matches_report_definition(self):
        a = self.alert(self.a, 'm1')
        SecurityAlert.objects.filter(pk=a.pk).update(acknowledged_at=a.seen_at + timedelta(minutes=30))
        b = self.alert(self.a, 'm2')
        SecurityAlert.objects.filter(pk=b.pk).update(acknowledged_at=b.seen_at + timedelta(minutes=10))
        r = self.get(self.su)
        self.assertEqual(r.context['response']['alert']['mtta'], '20 min')
        from reports.queries import security_alert_mtta
        today = timezone.localdate()
        rows = security_alert_mtta(today - timedelta(days=1), today + timedelta(days=1))
        self.assertAlmostEqual(rows[0]['avg_mtta_minutes'], 20, delta=1)

    def test_rmm_not_configured_then_select_client(self):
        r = self.get(self.su)
        self.assertEqual(r.context['rmm']['state'], 'not_configured')
        from integrations.models import RMMConnection
        RMMConnection.objects.create(organization=self.a, provider_type='tactical_rmm', name='RMM',
                                     base_url='https://rmm.example.test')
        r = self.get(self.su, 'global')
        self.assertEqual(r.context['rmm']['state'], 'select_client')
        r = self.get(self.su, self.a)
        self.assertEqual(r.context['rmm']['state'], '')
        self.assertEqual(r.context['rmm']['counts']['active'], 0)

    def test_monitoring_not_configured(self):
        html = self.get(self.su, self.a).content.decode()
        self.assertIn('no website monitors here', html)


class NavTests(OverviewBase):
    def sidebar_has(self, user, org=None):
        self.login(user, org)
        html = self.client.get(reverse('core:dashboard'), follow=True).content.decode()
        head = html.split('id="main-content"', 1)[0]
        return 'href="/security/overview/"' in head

    def test_in_nav_only_for_permitted_users(self):
        self.assertTrue(self.sidebar_has(self.su))
        self.assertTrue(self.sidebar_has(_staff('secov_nav_ok', security_alerts_view=True)))
        self.assertFalse(self.sidebar_has(_staff('secov_nav_no', security_alerts_view=False)))
        cust = User.objects.create_user('secov_nav_cust', 'nc@x.test', 'pw')
        Membership.objects.create(user=cust, organization=self.a, role=Role.OWNER)
        self.assertFalse(self.sidebar_has(cust, self.a))

    def test_psa_off_hides_the_entry_like_the_security_sections(self):
        s = SystemSetting.get_settings()
        s.psa_enabled = False
        s.save()
        self.assertFalse(self.sidebar_has(self.su))

    def test_first_in_security_group(self):
        from core.tests.test_navbar_grouping import sidebar
        self.login(self.su)
        nav = sidebar(self.client.get(reverse('core:dashboard'), follow=True).content.decode())
        self.assertEqual(nav['security'][0], URL)


class WorkflowLinkTests(OverviewBase):
    """Alert -> incident -> related device -> RMM device."""

    def setUp(self):
        super().setUp()
        from assets.models import Asset
        from integrations.models import RMMConnection, RMMDevice
        self.asset = Asset.objects.create(organization=self.a, name='ACME-WS-01', asset_type='desktop')
        rc = RMMConnection.objects.create(organization=self.a, provider_type='tactical_rmm', name='RMM',
                                          base_url='https://rmm.example.test')
        self.device = RMMDevice.objects.create(connection=rc, organization=self.a, external_id='d1',
                                               device_name='ACME-WS-01', linked_asset=self.asset)
        self.alert_a = self.alert(self.a, 'w1', client_org=self.a, asset_hint='acme-ws-01')
        self.incident = SecurityIncident.objects.create(organization=self.a, client_org=self.a,
                                                        title='Incident', asset_hint='ACME-WS-01')
        self.incident.alerts.add(self.alert_a)

    def test_alert_links_incident_device_and_rmm(self):
        self.login(self.su, self.a)
        html = self.client.get(reverse('security_alerts:alert_detail', args=[self.alert_a.pk])).content.decode()
        self.assertIn(reverse('security_alerts:incident_detail', args=[self.incident.pk]), html)
        self.assertIn(reverse('assets:device_workspace', args=[self.asset.pk]), html)
        self.assertIn(reverse('integrations:rmm_device_detail', args=[self.device.pk]), html)
        # The links open.
        self.assertEqual(self.client.get(reverse('integrations:rmm_device_detail', args=[self.device.pk])).status_code, 200)

    def test_incident_links_device(self):
        self.login(self.su, self.a)
        html = self.client.get(reverse('security_alerts:incident_detail', args=[self.incident.pk])).content.decode()
        self.assertIn(reverse('assets:device_workspace', args=[self.asset.pk]), html)
        self.assertIn(reverse('integrations:rmm_device_detail', args=[self.device.pk]), html)

    def test_no_device_links_without_asset_or_integration_access(self):
        tech = _staff('secov_wf', security_alerts_view=True, assets_view=False, integrations_view=False)
        self.login(tech, self.a)
        r = self.client.get(reverse('security_alerts:alert_detail', args=[self.alert_a.pk]))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertNotIn(reverse('assets:device_workspace', args=[self.asset.pk]), html)
        self.assertNotIn(reverse('integrations:rmm_device_detail', args=[self.device.pk]), html)

    def test_rmm_permission_block_withholds_rmm_link(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        self.login(self.su, self.a)
        with patch('rmm_permissions.decision.can', return_value=SimpleNamespace(blocked=True)):
            html = self.client.get(reverse('security_alerts:alert_detail', args=[self.alert_a.pk])).content.decode()
        self.assertNotIn(reverse('integrations:rmm_device_detail', args=[self.device.pk]), html)

    def test_other_customers_device_with_same_name_not_linked(self):
        from assets.models import Asset
        other = Asset.objects.create(organization=self.b, name='ACME-WS-01', asset_type='desktop')
        self.login(self.su)
        html = self.client.get(reverse('security_alerts:alert_detail', args=[self.alert_a.pk])).content.decode()
        self.assertNotIn(reverse('assets:device_workspace', args=[other.pk]), html)
        self.assertIn(reverse('assets:device_workspace', args=[self.asset.pk]), html)

    def test_incident_from_another_customer_not_listed_on_alert(self):
        tech = _staff('secov_inc', security_alerts_view=True)
        tech.profile.client_scope = 'selected'
        tech.profile.save()
        tech.profile.scope_organizations.add(self.a)
        foreign = SecurityIncident.objects.create(organization=self.b, title='Foreign incident')
        foreign.alerts.add(self.alert_a)
        self.login(tech, self.a)
        html = self.client.get(reverse('security_alerts:alert_detail', args=[self.alert_a.pk])).content.decode()
        self.assertNotIn(reverse('security_alerts:incident_detail', args=[foreign.pk]), html)
        self.assertIn(reverse('security_alerts:incident_detail', args=[self.incident.pk]), html)
