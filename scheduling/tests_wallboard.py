"""
Phase 47 (v3.17.533) — public scheduler wallboard.

The board is unauthenticated on purpose: a wall-mounted screen has no keyboard.
That makes the URL the only control, so most of what is worth testing here is
about who can reach it and what leaks when they do.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Organization
from scheduling.models import ScheduledTask, SchedulerWallboard

# The board shows the installation's local day, so the tests pin the clock to
# mid-afternoon local time; "a few hours from now" is then always today.
AFTERNOON = datetime(2026, 11, 11, 14, 0, tzinfo=ZoneInfo(django_settings.TIME_ZONE))


class _FrozenAfternoon:
    @classmethod
    def setUpClass(cls):
        cls._clock = mock.patch('django.utils.timezone.now', return_value=AFTERNOON.astimezone(ZoneInfo('UTC')))
        cls._clock.start()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._clock.stop()


_TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WallboardAccessTests(_FrozenAfternoon, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Wall Co', slug='wall-co')
        cls.board = SchedulerWallboard.get_board()
        cls.board.is_enabled = True
        cls.board.save()
        cls.tech = User.objects.create_user('techie', 't@x.com', 'pw',
                                            first_name='Sam', last_name='Tech')
        cls.task = ScheduledTask.objects.create(
            organization=cls.org, title='Swap the firewall', status='pending',
            due_date=timezone.now() + timedelta(hours=3))
        cls.task.assigned_to.add(cls.tech)

    def url(self):
        return reverse('scheduling:wallboard_public', args=[self.board.token])

    def test_an_anonymous_visitor_can_read_an_enabled_board(self):
        """The whole point — a TV cannot log in."""
        r = self.client.get(self.url())
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Swap the firewall')

    def test_a_disabled_board_is_not_found(self):
        self.board.is_enabled = False
        self.board.save()
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_an_unknown_token_is_not_found(self):
        r = self.client.get(
            reverse('scheduling:wallboard_public', args=['no-such-token']))
        self.assertEqual(r.status_code, 404)

    def test_disabled_and_unknown_are_indistinguishable(self):
        """A 403 on a disabled board would confirm one exists at that address."""
        self.board.is_enabled = False
        self.board.save()
        disabled = self.client.get(self.url())
        unknown = self.client.get(
            reverse('scheduling:wallboard_public', args=['no-such-token']))
        self.assertEqual(disabled.status_code, unknown.status_code)

    def test_the_board_is_not_cached_or_indexed(self):
        r = self.client.get(self.url())
        self.assertIn('no-store', r['Cache-Control'])
        self.assertIn('noindex', r['X-Robots-Tag'])

    def test_every_clients_work_appears(self):
        """The board spans clients on purpose — an MSP's day does."""
        other = Organization.objects.create(name='Not Us', slug='not-us')
        ScheduledTask.objects.create(
            organization=other, title='Another client job', status='pending',
            due_date=timezone.now() + timedelta(hours=2))
        r = self.client.get(self.url())
        self.assertContains(r, 'Another client job')

    def test_completed_and_cancelled_work_is_hidden(self):
        ScheduledTask.objects.create(
            organization=self.org, title='Already done', status='completed',
            due_date=timezone.now() + timedelta(hours=1))
        r = self.client.get(self.url())
        self.assertNotContains(r, 'Already done')


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WallboardDisclosureTests(_FrozenAfternoon, TestCase):
    """Each toggle keeps something off an unauthenticated page."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Acme Holdings', slug='acme-h')
        cls.board = SchedulerWallboard.get_board()
        cls.board.is_enabled = True
        cls.board.save()
        cls.tech = User.objects.create_user('sam', 's@x.com', 'pw',
                                            first_name='Sam', last_name='Tech')
        cls.task = ScheduledTask.objects.create(
            organization=cls.org, title='Onsite visit', status='pending',
            due_date=timezone.now() + timedelta(hours=2))
        cls.task.assigned_to.add(cls.tech)

    def url(self):
        return reverse('scheduling:wallboard_public', args=[self.board.token])

    def test_client_names_can_be_withheld(self):
        self.board.show_client_names = False
        self.board.save()
        r = self.client.get(self.url())
        self.assertNotContains(r, 'Acme Holdings')
        self.assertContains(r, 'Onsite visit', msg_prefix='board still useful')

    def test_technician_names_can_be_withheld(self):
        self.board.show_technician_names = False
        self.board.save()
        self.assertNotContains(self.client.get(self.url()), 'Sam Tech')

    def test_defaults_show_the_useful_fields(self):
        r = self.client.get(self.url())
        self.assertContains(r, 'Acme Holdings')
        self.assertContains(r, 'Sam Tech')


class WallboardModelTests(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name='TokenCo', slug='token-co')

    def test_a_board_is_disabled_until_somebody_says_otherwise(self):
        board = SchedulerWallboard.get_board()
        self.assertFalse(board.is_enabled)

    def test_a_token_is_generated_and_long_enough_not_to_guess(self):
        board = SchedulerWallboard.get_board()
        self.assertGreaterEqual(len(board.token), 40)

    def test_there_is_exactly_one_board(self):
        """System-wide, not per-client: one screen shows the whole day."""
        first = SchedulerWallboard.get_board()
        second = SchedulerWallboard.get_board()
        self.assertEqual(SchedulerWallboard.objects.count(), 1)
        self.assertEqual(first.pk, second.pk)

    def test_rotating_replaces_the_token(self):
        board = SchedulerWallboard.get_board()
        before = board.token
        self.assertNotEqual(board.rotate_token(), before)

    def test_refresh_is_floored_so_a_screen_cannot_hammer_the_server(self):
        board = SchedulerWallboard.get_board()
        board.refresh_seconds = 1
        board.save()
        self.assertGreaterEqual(board.refresh_seconds, 15)

    def test_the_heading_has_a_sensible_default(self):
        self.assertEqual(SchedulerWallboard.get_board().display_title, 'Schedule')


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WallboardSettingsViewTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='SetCo', slug='set-co')
        cls.admin = User.objects.create_superuser('wbadmin', 'w@x.com', 'pw')

    def setUp(self):
        self.client.force_login(self.admin)
        session = self.client.session
        session['2fa_prompted'] = True
        session['current_organization_id'] = self.org.id
        session.save()

    def test_opening_settings_creates_a_disabled_board(self):
        self.assertEqual(SchedulerWallboard.objects.count(), 0)
        r = self.client.get(reverse('scheduling:wallboard_settings'))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(SchedulerWallboard.objects.get().is_enabled)

    def test_enabling_and_configuring(self):
        self.client.post(reverse('scheduling:wallboard_settings'), {
            'is_enabled': 'on', 'title': 'Workshop', 'days_ahead': '3',
            'refresh_seconds': '30', 'show_client_names': 'on',
        })
        board = SchedulerWallboard.get_board()
        self.assertTrue(board.is_enabled)
        self.assertEqual(board.title, 'Workshop')
        self.assertEqual(board.days_ahead, 3)
        self.assertFalse(board.show_technician_names, 'unchecked box means off')

    def test_days_ahead_is_clamped(self):
        self.client.post(reverse('scheduling:wallboard_settings'), {
            'is_enabled': 'on', 'days_ahead': '999', 'refresh_seconds': '60'})
        board = SchedulerWallboard.get_board()
        self.assertLessEqual(board.days_ahead, 14)

    def test_rotating_from_the_settings_page(self):
        board = SchedulerWallboard.get_board()
        before = board.token
        self.client.post(reverse('scheduling:wallboard_settings'),
                         {'action': 'rotate'})
        board.refresh_from_db()
        self.assertNotEqual(board.token, before)

    def test_an_anonymous_visitor_cannot_reach_the_settings_page(self):
        self.client.logout()
        r = self.client.get(reverse('scheduling:wallboard_settings'))
        self.assertIn(r.status_code, (302, 403))


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WallboardLocalDayTests(TestCase):
    """At 23:00 Eastern the UTC date is already tomorrow. The board used to
    take "today" from UTC, so the rest of the evening's jobs vanished from 19:00
    or 20:00 Eastern onward and late tasks were grouped under the next day."""

    LATE = datetime(2026, 11, 11, 23, 0, tzinfo=ZoneInfo('America/New_York'))

    def setUp(self):
        self.board = SchedulerWallboard.get_board()
        self.board.is_enabled = True
        self.board.days_ahead = 1
        self.board.save()
        org = Organization.objects.create(name='Late Co', slug='late-co')
        ScheduledTask.objects.create(organization=org, title='Late patch window', status='pending',
                                     due_date=self.LATE + timedelta(minutes=30))
        ScheduledTask.objects.create(organization=org, title='Tomorrow morning job', status='pending',
                                     due_date=self.LATE + timedelta(hours=10))

    @override_settings(TIME_ZONE='America/New_York')
    def test_evening_jobs_stay_on_tonights_board(self):
        with mock.patch('django.utils.timezone.now', return_value=self.LATE.astimezone(ZoneInfo('UTC'))):
            r = self.client.get(reverse('scheduling:wallboard_public', args=[self.board.token]))
        self.assertContains(r, 'Late patch window')
        self.assertNotContains(r, 'Tomorrow morning job')

    @override_settings(TIME_ZONE='America/New_York')
    def test_days_are_grouped_by_local_date(self):
        from scheduling.views import _wallboard_days
        with mock.patch('django.utils.timezone.now', return_value=self.LATE.astimezone(ZoneInfo('UTC'))):
            days = _wallboard_days(2)
        self.assertEqual([(d.isoformat(), [t.title for t in ts]) for d, ts in days],
                         [('2026-11-11', ['Late patch window']), ('2026-11-12', ['Tomorrow morning job'])])
