"""
Smoke tests for resourcing — Phase 2.1.

Covers:
  1. UserSkill unique_together prevents duplicate names per user
  2. WorkingHours.clean() rejects end_time <= start_time
  3. UserCertification.is_expired flag works
  4. UserCertification.expires_soon flag works
  5. UserProfile.is_working_now() — empty / covers / doesn't cover
  6. View tech_roster is gated to staff/superuser
"""
from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    BillableTarget, Holiday, LeaveRequest,
    UserCertification, UserSkill, WorkingHours, working_days_in_period,
)

User = get_user_model()


class UserSkillTests(TestCase):
    def test_unique_together_prevents_duplicates(self):
        u = User.objects.create_user(username='alice', password='pw-test-12345')
        UserSkill.objects.create(user=u, name='Active Directory', proficiency='advanced')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UserSkill.objects.create(user=u, name='Active Directory', proficiency='expert')


class WorkingHoursTests(TestCase):
    def test_clean_rejects_end_before_start(self):
        u = User.objects.create_user(username='bob', password='pw-test-12345')
        wh = WorkingHours(user=u, weekday=0, start_time=time(17, 0), end_time=time(9, 0))
        with self.assertRaises(ValidationError):
            wh.clean()

    def test_clean_rejects_end_equal_to_start(self):
        u = User.objects.create_user(username='bob2', password='pw-test-12345')
        wh = WorkingHours(user=u, weekday=0, start_time=time(9, 0), end_time=time(9, 0))
        with self.assertRaises(ValidationError):
            wh.clean()


class UserCertificationTests(TestCase):
    def test_is_expired_when_past(self):
        u = User.objects.create_user(username='carol', password='pw-test-12345')
        yesterday = timezone.localdate() - timedelta(days=1)
        cert = UserCertification.objects.create(user=u, name='CCNA', expires_at=yesterday)
        self.assertTrue(cert.is_expired)
        self.assertFalse(cert.expires_soon)  # expired ≠ expires_soon

    def test_is_expired_when_no_expiry(self):
        u = User.objects.create_user(username='carol2', password='pw-test-12345')
        cert = UserCertification.objects.create(user=u, name='Lifetime cert')
        self.assertFalse(cert.is_expired)

    def test_expires_soon_within_60_days(self):
        u = User.objects.create_user(username='dave', password='pw-test-12345')
        in_30 = timezone.localdate() + timedelta(days=30)
        cert = UserCertification.objects.create(user=u, name='Microsoft 365 Admin', expires_at=in_30)
        self.assertTrue(cert.expires_soon)
        self.assertFalse(cert.is_expired)

    def test_expires_soon_false_when_far(self):
        u = User.objects.create_user(username='dave2', password='pw-test-12345')
        in_120 = timezone.localdate() + timedelta(days=120)
        cert = UserCertification.objects.create(user=u, name='AWS Solutions Architect', expires_at=in_120)
        self.assertFalse(cert.expires_soon)


class IsWorkingNowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='eve', password='pw-test-12345')
        # Profile is auto-created by post_save signal; pin to UTC for determinism.
        self.profile = self.user.profile
        self.profile.timezone = 'UTC'
        self.profile.save()

    def test_returns_true_when_no_rows(self):
        # No WorkingHours configured at all → backwards-compat "always working".
        self.assertTrue(self.profile.is_working_now())

    def test_returns_true_when_row_covers_now(self):
        now = timezone.now().astimezone(timezone.get_default_timezone())
        # Build a row that's certain to cover "now in UTC", with a wide window.
        import zoneinfo
        utc_now = timezone.now().astimezone(zoneinfo.ZoneInfo('UTC'))
        WorkingHours.objects.create(
            user=self.user,
            weekday=utc_now.weekday(),
            start_time=time(0, 0),
            end_time=time(23, 59),
        )
        self.assertTrue(self.profile.is_working_now())

    def test_returns_false_when_only_other_days_configured(self):
        # User has rows but none for today → assume not working today.
        import zoneinfo
        utc_now = timezone.now().astimezone(zoneinfo.ZoneInfo('UTC'))
        wrong_day = (utc_now.weekday() + 3) % 7
        WorkingHours.objects.create(
            user=self.user,
            weekday=wrong_day,
            start_time=time(9, 0),
            end_time=time(17, 0),
        )
        self.assertFalse(self.profile.is_working_now())


@override_settings(REQUIRE_2FA=False)
class TechRosterAccessTests(TestCase):
    """v3.17.145: tech_roster is gated on `resourcing_view_team`. Plain
    is_staff users no longer pass automatically (Editor fallback doesn't
    grant the new boolean) — only superusers or a role_template granting
    `resourcing_view_team`."""
    def setUp(self):
        self.client = Client()
        self.regular = User.objects.create_user(username='regular', password='pw-test-12345')
        # v3.17.145: switched from is_staff to is_superuser so the test
        # passes the new RoleTemplate gate.
        self.staff = User.objects.create_user(username='ops-tech', password='pw-test-12345',
                                              is_staff=True, is_superuser=True)

    def test_regular_user_blocked(self):
        """A non-staff user should NOT see the roster — either redirected away
        (e.g. to login/profile) or a 403. They must NOT see the rendered page
        with status 200."""
        self.client.force_login(self.regular)
        resp = self.client.get(reverse('resourcing:tech_roster'), follow=False)
        # 200 == they got the page, which would be the bug. 3xx redirect or 403 = ok.
        self.assertNotEqual(resp.status_code, 200)
        self.assertIn(resp.status_code, (301, 302, 303, 403))

    def test_staff_user_allowed(self):
        """A superuser can reach the roster (status 200, or — if 2FA-redirect
        middleware bounces them — at least *not* a 403)."""
        self.client.force_login(self.staff)
        resp = self.client.get(reverse('resourcing:tech_roster'), follow=False)
        self.assertNotEqual(resp.status_code, 403)
        # Final response after following any 2FA redirects should be 200.
        resp_final = self.client.get(reverse('resourcing:tech_roster'), follow=True)
        # Either the final rendered tech_roster (200) OR a redirect-chain that
        # ended at the 2FA setup page — both prove staff is not blocked by
        # @user_passes_test.
        self.assertEqual(resp_final.status_code, 200)


# ---------------------------------------------------------------------------
# Phase 2.2 — Holiday + LeaveRequest + BillableTarget tests
# ---------------------------------------------------------------------------

class HolidayTests(TestCase):
    def test_global_holiday_matches_any_org(self):
        from resourcing.models import Holiday
        from datetime import date
        Holiday.objects.create(name='New Year', date=date(2026, 1, 1), is_recurring_yearly=True)
        self.assertTrue(Holiday.is_holiday(date(2026, 1, 1)))
        self.assertTrue(Holiday.is_holiday(date(2027, 1, 1)))  # recurring yearly
        self.assertFalse(Holiday.is_holiday(date(2026, 1, 2)))


class LeaveRequestTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.user = User.objects.create_user('alice', 'a@x.com', 'pw')

    def test_clean_rejects_inverted_dates(self):
        from resourcing.models import LeaveRequest
        from datetime import date
        from django.core.exceptions import ValidationError
        lr = LeaveRequest(user=self.user, leave_type='vacation',
                          start_date=date(2026, 5, 10), end_date=date(2026, 5, 5))
        with self.assertRaises(ValidationError):
            lr.clean()

    def test_total_days_handles_half_day(self):
        from resourcing.models import LeaveRequest
        from datetime import date
        lr = LeaveRequest(user=self.user, leave_type='sick',
                          start_date=date(2026, 5, 10), end_date=date(2026, 5, 10),
                          is_half_day=True)
        self.assertEqual(lr.total_days, 0.5)

    def test_is_user_on_leave_only_approved(self):
        from resourcing.models import LeaveRequest
        from datetime import date
        LeaveRequest.objects.create(user=self.user, leave_type='vacation',
            start_date=date(2026, 6, 1), end_date=date(2026, 6, 5), status='approved')
        self.assertTrue(LeaveRequest.is_user_on_leave(self.user, date(2026, 6, 3)))
        # Pending doesn't count
        u2 = self._make_user('bob')
        LeaveRequest.objects.create(user=u2, leave_type='vacation',
            start_date=date(2026, 6, 1), end_date=date(2026, 6, 5), status='pending')
        self.assertFalse(LeaveRequest.is_user_on_leave(u2, date(2026, 6, 3)))

    def _make_user(self, username):
        from django.contrib.auth.models import User
        return User.objects.create_user(username, f'{username}@x.com', 'pw')


class WorkingDaysTests(TestCase):
    def test_excludes_holidays_and_leave(self):
        from django.contrib.auth.models import User
        from resourcing.models import Holiday, LeaveRequest, WorkingHours, working_days_in_period
        from datetime import date, time
        u = User.objects.create_user('charlie', 'c@x.com', 'pw')
        # 5 weekday WorkingHours rows
        for wd in range(5):
            WorkingHours.objects.create(user=u, weekday=wd,
                                         start_time=time(9, 0), end_time=time(17, 0))
        # Period: Mon 2026-05-04 → Fri 2026-05-08 (5 working days base)
        # Holiday on Wed
        Holiday.objects.create(name='Mid-week', date=date(2026, 5, 6))
        # Approved leave Thu-Fri
        LeaveRequest.objects.create(user=u, leave_type='vacation',
            start_date=date(2026, 5, 7), end_date=date(2026, 5, 8), status='approved')
        days = working_days_in_period(u, date(2026, 5, 4), date(2026, 5, 8))
        # Mon + Tue only = 2 working days
        self.assertEqual(days, 2)


class BillableTargetTests(TestCase):
    def test_default_32_hours(self):
        from django.contrib.auth.models import User
        from resourcing.models import BillableTarget
        u = User.objects.create_user('dana', 'd@x.com', 'pw')
        bt = BillableTarget.objects.create(user=u)
        self.assertEqual(float(bt.target_hours_per_week), 32.0)


# v3.17.169 — billable target edit is now manager/admin-only.
# Even the target user themselves can NOT self-edit. Only users with the
# `resourcing_manage_cost_rates` perm (granted via RoleTemplate or by being
# a superuser) may edit a tech's billable target.
@override_settings(REQUIRE_2FA=False, SECURE_SSL_REDIRECT=False)
class BillableTargetPermissionTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.regular = User.objects.create_user('reg-bt', 'r@x.com', 'pw')
        self.admin = User.objects.create_user('admin-bt', 'a@x.com', 'pw',
                                               is_staff=True, is_superuser=True)

    def _bypass_2fa(self):
        session = self.client.session
        session['2fa_prompted'] = True
        session.save()

    def test_user_cannot_self_edit_billable_target(self):
        """Regular user with no resourcing_manage_cost_rates → 403 on POST
        to billable_target_edit even on their own user_id."""
        self.client.force_login(self.regular)
        self._bypass_2fa()
        r = self.client.post(
            reverse('resourcing:billable_target_edit', args=[self.regular.id]),
            {'target_hours_per_week': '40', 'is_active': 'on', 'notes': 'self-edit'},
        )
        # Either 403 (PermissionDenied) or a redirect-to-login style bounce.
        self.assertIn(r.status_code, [302, 303, 403])
        # And the change must NOT have persisted.
        from resourcing.models import BillableTarget
        bt = BillableTarget.objects.filter(user=self.regular).first()
        if bt is not None:
            self.assertNotEqual(float(bt.target_hours_per_week), 40.0)

    def test_manager_can_edit_anyones_target(self):
        """User with resourcing_manage_cost_rates → 200/302 OK."""
        self.client.force_login(self.admin)
        self._bypass_2fa()
        r = self.client.post(
            reverse('resourcing:billable_target_edit', args=[self.regular.id]),
            {'target_hours_per_week': '36', 'is_active': 'on', 'notes': 'manager set'},
            follow=True,
        )
        self.assertEqual(r.status_code, 200)
        from resourcing.models import BillableTarget
        bt = BillableTarget.objects.get(user=self.regular)
        self.assertEqual(float(bt.target_hours_per_week), 36.0)


# ---------------------------------------------------------------------------
# Phase 2.3 — Capacity report + skill ranking tests
# ---------------------------------------------------------------------------

@override_settings(REQUIRE_2FA=False, SECURE_SSL_REDIRECT=False)
class CapacityReportTests(TestCase):
    """v3.17.138: capacity report renders with target/scheduled/actual."""

    def setUp(self):
        from django.contrib.auth.models import User
        from resourcing.models import WorkingHours, BillableTarget
        from datetime import time
        self.staff = User.objects.create_user('admin1', 'a@x.com', 'pw', is_staff=True, is_superuser=True)
        self.tech = User.objects.create_user('alice', 'al@x.com', 'pw')
        for wd in range(5):
            WorkingHours.objects.create(user=self.tech, weekday=wd, start_time=time(9), end_time=time(17))
        BillableTarget.objects.create(user=self.tech, target_hours_per_week=32)

    def test_capacity_renders_for_staff(self):
        self.client.force_login(self.staff)
        # Mark 2FA prompt as already shown so the optional-2FA middleware
        # doesn't bounce the request.
        session = self.client.session
        session['2fa_prompted'] = True
        session.save()
        r = self.client.get('/resourcing/capacity/')
        # Either 200 directly, or after following any 2FA-related redirect.
        if r.status_code != 200:
            r = self.client.get('/resourcing/capacity/', follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'alice', r.content)

    def test_non_staff_denied(self):
        u = self.tech
        self.client.force_login(u)
        session = self.client.session
        session['2fa_prompted'] = True
        session.save()
        r = self.client.get('/resourcing/capacity/')
        # @user_passes_test redirects unauthorized users
        self.assertIn(r.status_code, [302, 403])


class SkillRankingTests(TestCase):
    """v3.17.138: rank_techs_for_ticket ranks by skill + availability."""

    def setUp(self):
        from django.contrib.auth.models import User
        from accounts.models import Membership, Role
        from core.models import Organization
        from resourcing.models import UserSkill
        from psa.models import Queue, TicketStatus, TicketPriority, TicketType, Ticket
        # Seed PSA defaults if tests need them
        from django.core.management import call_command
        call_command('psa_seed_defaults', verbosity=0)
        self.org = Organization.objects.create(name='SkillCo', slug='skill-co')
        from psa.tests._base import _make_msp_tech
        self.tech_a = _make_msp_tech(User.objects.create_user('alice', 'a@x.com', 'pw'))
        Membership.objects.create(user=self.tech_a, organization=self.org, role=Role.OWNER, is_active=True)
        UserSkill.objects.create(user=self.tech_a, name='Cisco', proficiency='expert')
        self.tech_b = _make_msp_tech(User.objects.create_user('bob', 'b@x.com', 'pw'))
        Membership.objects.create(user=self.tech_b, organization=self.org, role=Role.OWNER, is_active=True)

        self.ticket = Ticket.objects.create(
            organization=self.org,
            subject='Cisco switch port flapping',
            description='Switch port reset needed',
            queue=Queue.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
        )

    def test_skill_holder_ranks_above(self):
        from resourcing.views import rank_techs_for_ticket
        ranking = rank_techs_for_ticket(self.ticket)
        # alice (skill=Cisco) should be ranked at or above bob (no skills)
        names = [r['user'].username for r in ranking]
        self.assertIn('alice', names)
        a_score = next(r['score'] for r in ranking if r['user'].username == 'alice')
        b_score = next(r['score'] for r in ranking if r['user'].username == 'bob')
        self.assertGreater(a_score, b_score)


# ---------------------------------------------------------------------------
# Phase 3.2 — TechCostRate UI access gates
# ---------------------------------------------------------------------------

@override_settings(REQUIRE_2FA=False, SECURE_SSL_REDIRECT=False)
class TechCostRateViewTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.staff = User.objects.create_user('admin1', 'a@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        self.regular = User.objects.create_user('reg', 'r@x.com', 'pw')

    def test_list_blocked_for_regular(self):
        self.client.force_login(self.regular)
        session = self.client.session
        session['2fa_prompted'] = True
        session.save()
        r = self.client.get(reverse('resourcing:tech_cost_rate_list'))
        self.assertIn(r.status_code, [301, 302, 303, 403])

    def test_list_allowed_for_staff(self):
        self.client.force_login(self.staff)
        session = self.client.session
        session['2fa_prompted'] = True
        session.save()
        r = self.client.get(reverse('resourcing:tech_cost_rate_list'), follow=True)
        self.assertEqual(r.status_code, 200)

    def test_edit_creates_rate_row(self):
        from resourcing.models import TechCostRate
        from datetime import date
        self.client.force_login(self.staff)
        session = self.client.session
        session['2fa_prompted'] = True
        session.save()
        r = self.client.post(
            reverse('resourcing:tech_cost_rate_edit', args=[self.regular.id]),
            {'rate_per_hour': '75.50', 'effective_from': date.today().isoformat(),
             'notes': 'unit test'},
            follow=True,
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(TechCostRate.objects.filter(user=self.regular,
                                                    rate_per_hour='75.50').exists())


# ---------------------------------------------------------------------------
# Phase 11 — shift templates + weekly shift schedule
# ---------------------------------------------------------------------------

from datetime import date as _date, datetime as _dt, timezone as _utc_mod  # noqa: E402

from django.conf import settings as _settings  # noqa: E402
from django.contrib.auth.models import Group  # noqa: E402

from . import shifts as shift_svc  # noqa: E402
from .models import ShiftAssignment, ShiftTemplate  # noqa: E402

_UTC = _utc_mod.utc
_MON = _date(2030, 1, 7)  # a Monday
_SHIFT_MIDDLEWARE = [m for m in _settings.MIDDLEWARE
                     if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m]


def _at(day, hh, mm=0):
    return _dt(day.year, day.month, day.day, hh, mm, tzinfo=_UTC)


def _shift_tech(username):
    from accounts.models import UserType
    u = User.objects.create_user(username=username, password='pw-test-12345')
    u.profile.user_type = UserType.STAFF
    u.profile.timezone = 'UTC'
    u.profile.save()
    return u


class ShiftScheduleTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.tech = _shift_tech('shifty')
        cls.other = _shift_tech('teammate')
        cls.team = Group.objects.create(name='Nights')
        cls.team.user_set.add(cls.other)
        cls.day = ShiftTemplate.objects.create(name='Day', start_time=time(8), end_time=time(16))
        cls.night = ShiftTemplate.objects.create(name='Night on-call', start_time=time(22), end_time=time(6),
                                                 is_on_call=True)

    def test_template_overnight_and_duration(self):
        self.assertFalse(self.day.overnight)
        self.assertTrue(self.night.overnight)
        self.assertEqual(self.day.duration_minutes, 480)
        self.assertEqual(self.night.duration_minutes, 480)

    def test_assignment_xor_constraint(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            ShiftAssignment.objects.create(template=self.day, weekdays=[0], effective_from=_MON)
        a = ShiftAssignment(template=self.day, user=self.tech, team=self.team, weekdays=[0], effective_from=_MON)
        with self.assertRaises(ValidationError):
            a.clean()

    def test_day_shift_and_effective_dates(self):
        ShiftAssignment.objects.create(template=self.day, user=self.tech, weekdays=[0, 1, 2, 3, 4],
                                       effective_from=_MON, effective_until=_MON + timedelta(days=7))
        self.assertIsNotNone(shift_svc.shift_at(self.tech, _at(_MON, 9)))
        self.assertIsNone(shift_svc.shift_at(self.tech, _at(_MON, 17)))
        self.assertIsNone(shift_svc.shift_at(self.tech, _at(_MON + timedelta(days=5), 9)))  # Saturday
        self.assertIsNone(shift_svc.shift_at(self.tech, _at(_MON - timedelta(days=7), 9)))  # before start
        self.assertIsNone(shift_svc.shift_at(self.tech, _at(_MON + timedelta(days=14), 9)))  # after end
        self.assertTrue(shift_svc.has_schedule(self.tech, on=_MON))
        self.assertFalse(shift_svc.has_schedule(self.tech, on=_MON + timedelta(days=30)))

    def test_overnight_team_shift_runs_into_next_day(self):
        ShiftAssignment.objects.create(template=self.night, team=self.team, weekdays=[0], effective_from=_MON)
        tue = _MON + timedelta(days=1)
        self.assertIsNotNone(shift_svc.shift_at(self.other, _at(_MON, 23)))
        self.assertIsNotNone(shift_svc.shift_at(self.other, _at(tue, 5, 59)))
        self.assertIsNone(shift_svc.shift_at(self.other, _at(tue, 6)))
        self.assertIsNone(shift_svc.shift_at(self.tech, _at(_MON, 23)))  # not in the team
        self.assertIsNotNone(shift_svc.on_call_shift(self.other, _at(tue, 1), team_id=self.team.pk))
        other_team = Group.objects.create(name='Days')
        self.assertIsNone(shift_svc.on_call_shift(self.other, _at(tue, 1), team_id=other_team.pk))
        self.assertIsNotNone(shift_svc.on_call_shift(self.other, _at(tue, 1)))

    def test_switched_off_template_is_ignored(self):
        ShiftAssignment.objects.create(template=self.day, user=self.tech, weekdays=[0], effective_from=_MON)
        self.day.is_active = False
        self.day.save()
        self.assertIsNone(shift_svc.shift_at(self.tech, _at(_MON, 9)))
        self.assertFalse(shift_svc.has_schedule(self.tech, on=_MON))

    def test_availability_order(self):
        # Neither schedule nor working hours: available (unchanged behaviour).
        self.assertIsNone(shift_svc.availability_problem(self.tech, _at(_MON, 3)))
        # Working hours only: the old rule.
        WorkingHours.objects.create(user=self.tech, weekday=0, start_time=time(9), end_time=time(12))
        self.assertEqual(shift_svc.availability_problem(self.tech, _at(_MON, 13)), 'outside their working hours')
        # A schedule takes over from working hours.
        ShiftAssignment.objects.create(template=self.day, user=self.tech, weekdays=[0], effective_from=_MON)
        self.assertIsNone(shift_svc.availability_problem(self.tech, _at(_MON, 13)))
        self.assertEqual(shift_svc.availability_problem(self.tech, _at(_MON, 17)), 'outside their scheduled shifts')
        # Approved leave beats everything.
        LeaveRequest.objects.create(user=self.tech, start_date=_MON, end_date=_MON, status='approved')
        self.assertEqual(shift_svc.availability_problem(self.tech, _at(_MON, 10)), 'on approved leave today')
        self.assertTrue(shift_svc.is_working(self.tech, _at(_MON, 10)))  # leave is not "off shift"

    def test_week_grid_flags_pto_conflicts(self):
        ShiftAssignment.objects.create(template=self.day, user=self.tech, weekdays=[0, 1, 2], effective_from=_MON)
        LeaveRequest.objects.create(user=self.tech, start_date=_MON, end_date=_MON, status='approved')
        LeaveRequest.objects.create(user=self.tech, start_date=_MON + timedelta(days=1),
                                    end_date=_MON + timedelta(days=1), status='pending')
        LeaveRequest.objects.create(user=self.tech, start_date=_MON + timedelta(days=4),
                                    end_date=_MON + timedelta(days=4), status='approved')  # no shift that day
        Holiday.objects.create(name='Founders day', date=_MON + timedelta(days=2))
        row = shift_svc.week_grid([self.tech], _MON)[0]
        conflicts = [c['conflict'] for c in row['cells']]
        self.assertIn('approved vacation', conflicts[0])
        self.assertIn('Pending', conflicts[1])
        self.assertIn('Founders day', conflicts[2])
        self.assertEqual(conflicts[4], '')
        self.assertEqual(row['conflicts'], 3)
        self.assertEqual(len(shift_svc.pto_conflicts(self.tech, _MON, _MON + timedelta(days=6))), 3)

    def test_is_working_follows_schedule(self):
        ShiftAssignment.objects.create(template=self.day, user=self.tech, weekdays=[0], effective_from=_MON)
        from unittest import mock
        with mock.patch('django.utils.timezone.now', return_value=_at(_MON, 20)):
            self.assertFalse(shift_svc.is_working(self.tech))
        with mock.patch('django.utils.timezone.now', return_value=_at(_MON, 9)):
            self.assertTrue(shift_svc.is_working(self.tech))


@override_settings(MIDDLEWARE=_SHIFT_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REQUIRE_2FA=False)
class ShiftViewTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser('shift-admin', 'sa@example.com', 'pw-test-12345')
        cls.tech = _shift_tech('plain-shift-tech')
        cls.tech2 = _shift_tech('second-shift-tech')
        cls.customer = User.objects.create_user('shift-customer', password='pw-test-12345')
        cls.tpl = ShiftTemplate.objects.create(name='Early', start_time=time(7), end_time=time(15))

    def _login(self, user):
        c = Client()
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        s.save()
        return c

    def test_manager_creates_template_and_assignment_with_pto_warning(self):
        c = self._login(self.admin)
        self.assertEqual(c.get(reverse('resourcing:shift_templates')).status_code, 200)
        c.post(reverse('resourcing:shift_templates'), {'name': 'Late', 'start_time': '14:00', 'end_time': '22:00',
                                                      'is_active': 'on'})
        late = ShiftTemplate.objects.get(name='Late')
        start = timezone.localdate()
        LeaveRequest.objects.create(user=self.tech, start_date=start, end_date=start + timedelta(days=6),
                                    status='approved')
        resp = c.post(reverse('resourcing:shift_assign'), {
            'template': late.pk, 'user': self.tech.pk, 'weekdays': [str(i) for i in range(7)],
            'effective_from': start.isoformat()}, follow=True)
        self.assertContains(resp, 'clashes with leave')
        a = ShiftAssignment.objects.get(user=self.tech)
        self.assertEqual(a.weekdays, list(range(7)))
        page = c.get(reverse('resourcing:shift_schedule'))
        self.assertContains(page, 'Late')
        self.assertContains(page, 'shift-pto-conflicts')
        c.post(reverse('resourcing:shift_assignment_delete', args=[a.pk]))
        self.assertFalse(ShiftAssignment.objects.filter(pk=a.pk).exists())
        # Deleting a used template switches it off instead.
        ShiftAssignment.objects.create(template=late, user=self.tech, weekdays=[0], effective_from=start)
        c.post(reverse('resourcing:shift_templates'), {'delete': late.pk})
        late.refresh_from_db()
        self.assertFalse(late.is_active)

    def test_empty_schedule_explains_how_to_start(self):
        page = self._login(self.admin).get(reverse('resourcing:shift_schedule'))
        self.assertContains(page, 'id="shiftSetup"')
        self.assertContains(page, 'No shifts scheduled yet')
        self.assertNotContains(page, 'Create a shift template')  # a template exists: assign it
        ShiftTemplate.objects.all().delete()
        page = self._login(self.admin).get(reverse('resourcing:shift_schedule'))
        self.assertContains(page, 'Create a shift template')
        page = self._login(self.tech).get(reverse('resourcing:shift_schedule'))
        self.assertContains(page, 'Your dispatcher has not scheduled any shifts')
        self.assertNotContains(page, 'Create a shift template')
        ShiftAssignment.objects.create(template=ShiftTemplate.objects.create(
            name='Day', start_time=time(8), end_time=time(16)), user=self.tech, weekdays=[0],
            effective_from=timezone.localdate())
        self.assertNotContains(self._login(self.tech).get(reverse('resourcing:shift_schedule')),
                               'id="shiftSetup"')

    def test_invalid_assignment_is_refused(self):
        c = self._login(self.admin)
        c.post(reverse('resourcing:shift_assign'), {'template': self.tpl.pk, 'weekdays': ['0']})
        c.post(reverse('resourcing:shift_assign'), {'template': self.tpl.pk, 'user': self.tech.pk})
        c.post(reverse('resourcing:shift_assign'), {'template': self.tpl.pk, 'user': self.customer.pk,
                                                   'weekdays': ['0']})  # not a technician
        self.assertFalse(ShiftAssignment.objects.exists())

    def test_permissions(self):
        self.assertEqual(self._login(self.customer).get(reverse('resourcing:shift_schedule')).status_code, 404)
        tech = self._login(self.tech)
        ShiftAssignment.objects.create(template=self.tpl, user=self.tech2, weekdays=list(range(7)),
                                       effective_from=timezone.localdate() - timedelta(days=7))
        page = tech.get(reverse('resourcing:shift_schedule'))
        self.assertEqual(page.status_code, 200)
        # A technician without team rights sees only their own row and cannot manage.
        self.assertEqual([r['user'] for r in page.context['rows']], [self.tech])
        self.assertFalse(page.context['can_manage'])
        self.assertEqual(tech.get(reverse('resourcing:shift_templates')).status_code, 404)
        tech.post(reverse('resourcing:shift_assign'), {'template': self.tpl.pk, 'user': self.tech.pk,
                                                      'weekdays': ['0']})
        self.assertFalse(ShiftAssignment.objects.filter(user=self.tech).exists())


# ---------------------------------------------------------------------------
# Local calendar days. At 23:00 Eastern the UTC date is already tomorrow;
# "today" used to come from UTC, so a certificate expiring today read as
# expired and leave ending today dropped out of "upcoming" every evening.
# ---------------------------------------------------------------------------

from unittest import mock as _mock  # noqa: E402
from zoneinfo import ZoneInfo as _ZoneInfo  # noqa: E402

_EVENING = _dt(2026, 11, 11, 23, 0, tzinfo=_ZoneInfo('America/New_York'))
_EVENING_DAY = _date(2026, 11, 11)


def _evening_clock():
    # Django's now() is UTC-aware; returning a local-aware value would hide the bug.
    return _mock.patch('django.utils.timezone.now',
                       return_value=_EVENING.astimezone(_ZoneInfo('UTC')))


@override_settings(TIME_ZONE='America/New_York', MIDDLEWARE=_SHIFT_MIDDLEWARE,
                   SECURE_SSL_REDIRECT=False)
class LocalDayTests(TestCase):

    def test_certificate_expiring_today_is_not_expired_in_the_evening(self):
        cert = UserCertification(name='CCNA', expires_at=_EVENING_DAY)
        with _evening_clock():
            self.assertFalse(cert.is_expired)
            self.assertTrue(cert.expires_soon)

    def test_leave_ending_today_is_still_upcoming_in_the_evening(self):
        u = User.objects.create_user(username='evening-leave', password='pw-test-12345')
        LeaveRequest.objects.create(user=u, start_date=_EVENING_DAY - timedelta(days=2),
                                    end_date=_EVENING_DAY, status='approved')
        self.client.force_login(u)
        with _evening_clock():
            resp = self.client.get(reverse('resourcing:my_leave'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['upcoming']), 1)
