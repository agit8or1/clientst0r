"""Phase 11 — shift schedule in dispatch/routing, and geo-aware dispatch.

Shift side: routing availability and on-call read the weekly shift schedule;
the dispatch board shows shifts and PTO clashes; assignment conflicts flag a
due time outside the technician's shifts; mobile pings off shift are dropped.

Geo side: positions are kept only with the technician's consent and while an
administrator has the feature on; stale positions are ignored and expired ones
purged; the dispatch board and the travel endpoint show straight-line
estimates; the optional routing provider is mocked (no real network); the
"nearest eligible technician" routing destination; customers never see any of
it.
"""
import json
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role
from api_mobile.models import MobileAuthToken
from core.models import Organization
from field_ops import geo_dispatch
from field_ops.models import (
    ClientSiteGeofence, DispatchGeoSettings, DispatchLocationConsent, DispatchPosition,
    OrganizationFieldOpsSettings, TechnicianLocation,
)
from locations.models import Location
from psa.models import ClientPSASettings, Queue, Ticket, TicketPriority, TicketStatus, TicketType
from psa.routing import engine
from psa.routing.models import RoutingDecision, RoutingSettings
from psa.routing.tests import _login, _rule, _set_msp, _tech
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_global, _setup_seed
from resourcing.models import LeaveRequest, ShiftAssignment, ShiftTemplate

UTC = dt_timezone.utc
MON = date(2030, 1, 7)
NO_THROTTLE_REST = {**getattr(django_settings, 'REST_FRAMEWORK', {}),
                    'DEFAULT_THROTTLE_RATES': {}, 'DEFAULT_THROTTLE_CLASSES': []}

# Philadelphia City Hall and two points roughly 5 km and 40 km away.
SITE = (Decimal('39.952583'), Decimal('-75.165222'))
NEAR = (Decimal('39.990000'), Decimal('-75.140000'))
FAR = (Decimal('40.300000'), Decimal('-75.000000'))


def _at(day, hh, mm=0):
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=UTC)


def _utc(user):
    user.profile.timezone = 'UTC'
    user.profile.save()
    return user


def _geo_on(**kw):
    cfg = DispatchGeoSettings.load()
    cfg.enabled = True
    for k, v in kw.items():
        setattr(cfg, k, v)
    cfg.save()
    return cfg


def _share(user, lat_lon, minutes_ago=1, source='gps'):
    DispatchLocationConsent.objects.update_or_create(user=user, defaults={'share_with_dispatch': True})
    DispatchPosition.objects.update_or_create(user=user, defaults={
        'lat': lat_lon[0], 'lon': lat_lon[1], 'source': source,
        'recorded_at': timezone.now() - timedelta(minutes=minutes_ago)})


def _ticket(org, **kw):
    kw.setdefault('subject', 'Onsite job')
    return Ticket.objects.create(
        organization=org, status=TicketStatus.objects.get(slug='new'),
        priority=TicketPriority.objects.order_by('sort_order').first(),
        queue=Queue.objects.first(), ticket_type=TicketType.objects.first(), **kw)


class Fixture:
    @classmethod
    def build(cls):
        _setup_seed()
        _enable_psa_global()
        cls.admin = User.objects.create_superuser('geo-admin', 'ga@msp.example', 'pw')
        cls.team = Group.objects.create(name='Field')
        cls.near_tech = _utc(_tech('near-tech', cls.team))
        cls.far_tech = _utc(_tech('far-tech', cls.team))
        cls.idle_tech = _utc(_tech('no-share-tech', cls.team))
        cls.org = Organization.objects.create(name='Geo Co', slug='geo-co')
        ClientPSASettings.objects.create(organization=cls.org, portal_enabled=True)
        cls.site = Location.objects.create(organization=cls.org, name='City Hall', street_address='1 Penn Sq',
                                           city='Philadelphia', postal_code='19107', is_primary=True,
                                           latitude=SITE[0], longitude=SITE[1])
        cls.portal = User.objects.create_user('geo-portal', 'p@geo.example', 'pw')
        Membership.objects.create(user=cls.portal, organization=cls.org, role=Role.READONLY, is_active=True)


# ---------------------------------------------------------------------------
# Shift schedule in routing + dispatch
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ShiftDispatchRoutingTests(Fixture, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.build()
        cls.day = ShiftTemplate.objects.create(name='Day', start_time=time(8), end_time=time(16))
        cls.night = ShiftTemplate.objects.create(name='Night on-call', start_time=time(22), end_time=time(6),
                                                 is_on_call=True)
        ShiftAssignment.objects.create(template=cls.day, user=cls.near_tech, weekdays=[0, 1, 2, 3, 4],
                                       effective_from=MON)
        ShiftAssignment.objects.create(template=cls.night, team=cls.team, weekdays=[0], effective_from=MON)

    def test_routing_availability_reads_schedule(self):
        msp = RoutingSettings.load()
        dest = {'type': 'least_loaded', 'team_id': self.team.pk, 'require_available': True}
        t = Ticket(organization=self.org)
        eligible, skipped = engine.candidates(t, dest, _at(MON, 10), msp)
        self.assertIn(self.near_tech, eligible)
        eligible, skipped = engine.candidates(t, dest, _at(MON, 17), msp)
        self.assertNotIn(self.near_tech, eligible)
        self.assertEqual(next(s['reason'] for s in skipped if s['user_id'] == self.near_tech.pk),
                         'outside their scheduled shifts')

    def test_on_call_template_counts_as_on_call(self):
        msp = RoutingSettings.load()
        dest = {'type': 'least_loaded', 'team_id': self.team.pk, 'require_on_call': True}
        t = Ticket(organization=self.org)
        eligible, _ = engine.candidates(t, dest, _at(MON, 23), msp)
        self.assertEqual(set(eligible), {self.near_tech, self.far_tech, self.idle_tech})
        eligible, skipped = engine.candidates(t, dest, _at(MON, 12), msp)
        self.assertEqual(eligible, [])
        # Approved leave still excludes an on-call technician.
        LeaveRequest.objects.create(user=self.far_tech, start_date=MON, end_date=MON, status='approved')
        eligible, _ = engine.candidates(t, dest, _at(MON, 23), msp)
        self.assertNotIn(self.far_tech, eligible)

    def test_dispatch_conflict_for_due_time_outside_shift(self):
        from psa.views import _dispatch_conflicts
        t = _ticket(self.org, resolution_due_at=_at(MON, 20))
        self.assertTrue(any('Shift conflict' in w for w in _dispatch_conflicts(self.near_tech, t)))
        t.resolution_due_at = _at(MON, 9)
        self.assertFalse(any('Shift conflict' in w for w in _dispatch_conflicts(self.near_tech, t)))
        # Technicians without their own schedule (or team schedule) are not checked.
        lone = _utc(_tech('lone-tech'))
        self.assertFalse(any('Shift conflict' in w for w in _dispatch_conflicts(lone, t)))

    def test_board_shows_shifts_and_pto_clash(self):
        today = timezone.localdate()
        tpl = ShiftTemplate.objects.create(name='Board shift', start_time=time(0), end_time=time(23, 59))
        ShiftAssignment.objects.create(template=tpl, user=self.far_tech, weekdays=list(range(7)),
                                       effective_from=today - timedelta(days=1))
        LeaveRequest.objects.create(user=self.far_tech, start_date=today, end_date=today, status='approved')
        c = Client()
        _login(c, self.admin)
        resp = c.get(reverse('psa:dispatch_board'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Board shift')
        self.assertContains(resp, 'Scheduled while on approved vacation')

    def test_mobile_ping_off_shift_is_dropped(self):
        cache.clear()
        token = MobileAuthToken.issue(self.near_tech)[0]

        def ping(when):
            body = {'lat': '1', 'lon': '2', 'timestamp': when.isoformat()}
            with override_settings(REST_FRAMEWORK=NO_THROTTLE_REST):
                return self.client.post('/api/mobile/v1/locations/', data=json.dumps(body),
                                        content_type='application/json', HTTP_AUTHORIZATION=f'Token {token}')
        self.assertEqual(ping(_at(MON, 20)).status_code, 204)   # between the day and night shifts
        self.assertEqual(ping(_at(MON, 9)).status_code, 201)    # on the day shift
        self.assertEqual(ping(_at(MON, 23)).status_code, 201)   # on the team's night shift


# ---------------------------------------------------------------------------
# Geo-aware dispatch
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REST_FRAMEWORK=NO_THROTTLE_REST)
class GeoPrivacyTests(Fixture, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.build()

    def setUp(self):
        cache.clear()

    def _ping(self, user, lat, lon):
        token = MobileAuthToken.issue(user)[0]
        return self.client.post('/api/mobile/v1/locations/', data=json.dumps({'lat': str(lat), 'lon': str(lon)}),
                                content_type='application/json', HTTP_AUTHORIZATION=f'Token {token}')

    def test_off_by_default_and_without_consent_nothing_is_kept(self):
        self.assertFalse(DispatchGeoSettings.objects.exists())
        self.assertFalse(DispatchGeoSettings.load().enabled)
        DispatchLocationConsent.objects.create(user=self.near_tech, share_with_dispatch=True)
        self.assertEqual(self._ping(self.near_tech, *NEAR).status_code, 201)
        self.assertFalse(DispatchPosition.objects.exists())          # feature off
        _geo_on()
        self._ping(self.far_tech, *FAR)
        self.assertFalse(DispatchPosition.objects.filter(user=self.far_tech).exists())  # no consent
        self._ping(self.near_tech, *NEAR)
        pos = DispatchPosition.objects.get(user=self.near_tech)
        self.assertEqual((pos.lat, pos.source), (NEAR[0], 'gps'))
        self.assertEqual(TechnicianLocation.objects.filter(tech=self.near_tech).count(), 2)

    def test_customer_users_are_never_kept_and_cannot_consent(self):
        _geo_on()
        with self.assertRaises(PermissionError):
            geo_dispatch.set_consent(self.portal, True)
        DispatchLocationConsent.objects.create(user=self.portal, share_with_dispatch=True)
        self.assertFalse(geo_dispatch.record_ping(self.portal, 1, 2))
        token = MobileAuthToken.issue(self.portal)[0]
        resp = self.client.post('/api/mobile/v1/dispatch-sharing/', data=json.dumps({'share': True}),
                                content_type='application/json', HTTP_AUTHORIZATION=f'Token {token}')
        self.assertEqual(resp.status_code, 403)

    def test_geofence_only_mode_keeps_the_centre_not_the_raw_position(self):
        _geo_on()
        DispatchLocationConsent.objects.create(user=self.near_tech, share_with_dispatch=True)
        OrganizationFieldOpsSettings.objects.create(organization=self.org, geofence_only_mode=True)
        ClientSiteGeofence.objects.create(organization=self.org, name='Hall', center_lat=SITE[0],
                                          center_lon=SITE[1], radius_meters=500)
        resp = self._ping(self.near_tech, Decimal('39.953000'), Decimal('-75.165000'))
        self.assertEqual(resp.json()['mode'], 'geofence_only')
        pos = DispatchPosition.objects.get(user=self.near_tech)
        self.assertEqual((pos.lat, pos.lon, pos.source), (SITE[0], SITE[1], 'geofence'))

    def test_consent_page_and_api_withdrawal_deletes_position(self):
        _geo_on()
        c = Client()
        _login(c, self.near_tech)
        self.assertEqual(c.get(reverse('field_ops:dispatch_sharing')).status_code, 200)
        c.post(reverse('field_ops:dispatch_sharing'), {'share': 'on'})
        self.assertTrue(geo_dispatch.has_consent(self.near_tech))
        self._ping(self.near_tech, *NEAR)
        page = c.get(reverse('field_ops:dispatch_sharing'))
        self.assertContains(page, str(NEAR[0]))      # the technician sees what dispatch sees
        token = MobileAuthToken.issue(self.near_tech)[0]
        resp = self.client.post('/api/mobile/v1/dispatch-sharing/', data=json.dumps({'share': False}),
                                content_type='application/json', HTTP_AUTHORIZATION=f'Token {token}')
        self.assertEqual(resp.json()['sharing'], False)
        self.assertFalse(DispatchPosition.objects.filter(user=self.near_tech).exists())
        portal = Client()
        _login(portal, self.portal)
        # Customer portal users never reach staff pages: sent to the portal.
        r = portal.get(reverse('field_ops:dispatch_sharing'))
        self.assertEqual((r.status_code, r.get('Location')), (302, '/portal/'))

    def test_freshness_and_retention(self):
        cfg = _geo_on(freshness_minutes=30, retention_hours=2)
        _share(self.near_tech, NEAR, minutes_ago=10)
        _share(self.far_tech, FAR, minutes_ago=45)       # stale, still within retention
        _share(self.idle_tech, FAR, minutes_ago=180)     # past retention
        self.assertEqual(set(geo_dispatch.positions([self.near_tech, self.far_tech, self.idle_tech])),
                         {self.near_tech.pk})
        out = StringIO()
        call_command('prune_technician_locations', stdout=out)
        self.assertIn('1 expired dispatch position', out.getvalue())
        self.assertEqual(set(DispatchPosition.objects.values_list('user_id', flat=True)),
                         {self.near_tech.pk, self.far_tech.pk})
        # Switching the feature off deletes every position.
        c = Client()
        _login(c, self.admin)
        c.post(reverse('field_ops:dispatch_geo_settings'), {'freshness_minutes': '30', 'retention_hours': '2'})
        cfg.refresh_from_db()
        self.assertFalse(cfg.enabled)
        self.assertFalse(DispatchPosition.objects.exists())

    def test_settings_page_superuser_only_and_url_policy(self):
        c = Client()
        _login(c, self.near_tech)
        self.assertEqual(c.get(reverse('field_ops:dispatch_geo_settings')).status_code, 404)
        _login(c, self.admin)
        self.assertEqual(c.get(reverse('field_ops:dispatch_geo_settings')).status_code, 200)
        c.post(reverse('field_ops:dispatch_geo_settings'), {
            'enabled': 'on', 'routing_provider': 'osrm', 'routing_base_url': 'http://169.254.169.254/latest'})
        cfg = DispatchGeoSettings.load()
        self.assertTrue(cfg.enabled)
        self.assertEqual((cfg.routing_base_url, cfg.routing_provider), ('', 'none'))
        c.post(reverse('field_ops:dispatch_geo_settings'), {
            'enabled': 'on', 'routing_provider': 'osrm', 'routing_base_url': 'https://router.example.com'})
        cfg = DispatchGeoSettings.load()
        self.assertEqual((cfg.routing_base_url, cfg.routing_provider), ('https://router.example.com', 'osrm'))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class GeoDispatchTests(Fixture, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.build()

    def setUp(self):
        _geo_on()
        _share(self.near_tech, NEAR)
        _share(self.far_tech, FAR)

    def test_estimates(self):
        pos = geo_dispatch.positions([self.near_tech])[self.near_tech.pk]
        est = geo_dispatch.estimate(pos, (float(SITE[0]), float(SITE[1])))
        self.assertAlmostEqual(est.distance_km, 4.7, delta=0.5)
        self.assertEqual(est.unit, 'mi')
        # 4.7 km × 1.3 at 30 mph (48.3 km/h) ≈ 8 minutes.
        self.assertTrue(6 <= est.minutes <= 9, est.minutes)
        self.assertIn('~', est.label)

    def test_site_point_prefers_ticket_site_then_primary(self):
        branch = Location.objects.create(organization=self.org, name='Branch', street_address='x', city='y',
                                         postal_code='1', latitude=FAR[0], longitude=FAR[1])
        t = _ticket(self.org, site=branch)
        self.assertEqual(geo_dispatch.site_point(t)[2], 'Branch')
        t2 = _ticket(self.org)
        t2.site = None
        self.assertIn('primary site', geo_dispatch.site_point(t2)[2])
        other = Organization.objects.create(name='No coords', slug='no-coords')
        self.assertIsNone(geo_dispatch.site_point(_ticket(other)))

    def test_board_shows_nearest_and_positions_staff_only(self):
        t = _ticket(self.org, subject='Printer onsite', site=self.site)
        c = Client()
        _login(c, self.admin)
        resp = c.get(reverse('psa:dispatch_board'))
        self.assertContains(resp, 'Travel estimates on')
        self.assertContains(resp, f'near-tech · ')
        self.assertContains(resp, 'dispatch-position')
        # Customers: the portal ticket page carries no position or travel data.
        t.client_can_view = True
        t.save()
        portal = Client()
        _login(portal, self.portal)
        page = portal.get(reverse('portal:ticket_detail', args=[t.ticket_number]))
        self.assertNotContains(page, 'near-tech')
        self.assertNotContains(page, 'dispatch-nearest')
        travel = portal.get(reverse('psa:dispatch_travel', args=[t.ticket_number]))
        self.assertIn(travel.status_code, (302, 403, 404))

    def test_travel_endpoint_straight_line_and_mocked_road_estimate(self):
        t = _ticket(self.org, site=self.site)
        c = Client()
        _login(c, self.admin)
        data = c.get(reverse('psa:dispatch_travel', args=[t.ticket_number])).json()
        self.assertEqual([r['username'] for r in data['technicians']], ['near-tech', 'far-tech'])
        self.assertEqual(data['technicians'][0]['method'], 'straight_line')
        self.assertEqual(data['without_position'], 2)    # the non-sharing technician and the admin
        # Road estimates: the routing provider is mocked; no network.
        _geo_on(routing_provider='osrm', routing_base_url='https://router.example.com')
        fake = mock.Mock()
        fake.json.return_value = {'routes': [{'distance': 6100.0, 'duration': 720.0}]}
        fake.raise_for_status.return_value = None
        with mock.patch('requests.Session.get', return_value=fake) as get:
            data = c.get(reverse('psa:dispatch_travel', args=[t.ticket_number]), {'road': '1'}).json()
        self.assertEqual(data['technicians'][0]['method'], 'routing')
        self.assertEqual(data['technicians'][0]['minutes'], 12)
        self.assertTrue(get.call_args[0][0].startswith('https://router.example.com/route/v1/driving/'))
        # Provider failure falls back to the straight-line estimate.
        with mock.patch('requests.Session.get', side_effect=OSError('down')):
            data = c.get(reverse('psa:dispatch_travel', args=[t.ticket_number]), {'road': '1'}).json()
        self.assertEqual(data['technicians'][0]['method'], 'straight_line')

    def test_page_render_and_routing_never_call_the_provider(self):
        _geo_on(routing_provider='osrm', routing_base_url='https://router.example.com')
        t = _ticket(self.org, site=self.site)
        c = Client()
        _login(c, self.admin)
        with mock.patch('requests.Session.get') as get:
            c.get(reverse('psa:dispatch_board'))
            engine.evaluate(t, ignore_mode=True)
        get.assert_not_called()

    def test_nearest_destination_routes_to_nearest_eligible(self):
        _set_msp(mode='auto')
        _rule('Nearest field tech', self.org, 10, {}, {'type': 'nearest', 'team_id': self.team.pk,
                                                       'require_available': False})
        with self.captureOnCommitCallbacks(execute=True):
            t = _ticket(self.org, subject='Onsite printer', site=self.site)
        t.refresh_from_db()
        self.assertEqual(t.assigned_to, self.near_tech)
        d = RoutingDecision.objects.get(ticket=t)
        self.assertIn('nearest to City Hall', d.reason)
        self.assertIn({'user_id': self.idle_tech.pk, 'username': 'no-share-tech',
                       'reason': 'no recent shared position'}, d.skipped_candidates)
        # Routing never changed customer, site or SLA.
        self.assertEqual((t.organization, t.site), (self.org, self.site))

    def test_nearest_falls_back_without_site_or_when_off(self):
        rule = _rule('Nearest', self.org, 10, {}, {'type': 'nearest', 'require_available': False},
                     fallback={'type': 'triage'})
        other = Organization.objects.create(name='Nowhere', slug='nowhere')
        ev = engine.evaluate(_ticket(other), ignore_mode=True)
        self.assertNotEqual(ev.rule, rule)   # rule is for Geo Co only
        t = _ticket(self.org)
        self.assertEqual(t.site, self.site)      # the customer's only site
        self.site.latitude = None
        self.site.save()
        t = Ticket.objects.get(pk=t.pk)
        ev = engine.evaluate(t, ignore_mode=True)
        self.assertTrue(ev.used_fallback)
        self.assertIn('no site with coordinates', ev.reason)
        self.site.latitude = SITE[0]
        self.site.save()
        cfg = DispatchGeoSettings.load()
        cfg.enabled = False
        cfg.save()
        ev = engine.evaluate(t, ignore_mode=True)
        self.assertTrue(ev.used_fallback)
        self.assertIn('switched off', ev.reason)

    def test_builder_offers_nearest_and_reviews_it(self):
        c = Client()
        _login(c, self.admin)
        self.assertContains(c.get(reverse('ticket_routing:rule_new')), 'Nearest eligible technician')
        resp = c.post(reverse('ticket_routing:rule_new'), {
            'step': 'review', 'name': 'Closest', 'organization': str(self.org.pk), 'priority': '5',
            'destination_type': 'nearest', 'dest_team_id': str(self.team.pk), 'fallback_type': 'triage'})
        self.assertContains(resp, "nearest to the ticket&#x27;s site")
        self.assertContains(resp, 'share their position with dispatch')
