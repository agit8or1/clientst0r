"""113.7: dispatch reads every technician's shifts and ranking facts in a
fixed number of queries. ShiftBook and RankingFacts must give exactly the
answers of the per-user functions they replace."""
from datetime import date, datetime, time, timedelta, timezone as dt_tz

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from accounts.models import Membership, Role, UserType
from core.models import Organization

from . import shifts
from .models import LeaveRequest, ShiftAssignment, ShiftTemplate, UserSkill, WorkingHours
from .views import RankingFacts, rank_techs_for_ticket

User = get_user_model()
MON = date(2030, 1, 7)


def _tech(username, tz='UTC'):
    u = User.objects.create_user(username=username, password='pw-test-12345')
    u.profile.user_type = UserType.STAFF
    u.profile.timezone = tz
    u.profile.save()
    return u


class BulkShiftAndRankingTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from psa.tests._base import _setup_seed
        _setup_seed()
        cls.org = Organization.objects.create(name='Rank Co', slug='rank-co')
        cls.other_org = Organization.objects.create(name='Other Co', slug='other-co')
        day = ShiftTemplate.objects.create(name='Day', start_time=time(8), end_time=time(16))
        night = ShiftTemplate.objects.create(name='Night', start_time=time(22), end_time=time(6), is_on_call=True)
        off = ShiftTemplate.objects.create(name='Retired', start_time=time(9), end_time=time(10), is_active=False)
        team = Group.objects.create(name='Nights')
        cls.direct = _tech('r-direct')
        ShiftAssignment.objects.create(template=day, user=cls.direct, weekdays=[0, 1, 2, 3, 4], effective_from=MON)
        cls.teamed = _tech('r-team', tz='America/New_York')
        team.user_set.add(cls.teamed)
        ShiftAssignment.objects.create(template=night, team=team, weekdays=[0, 2, 4], effective_from=MON)
        cls.ended = _tech('r-ended')
        ShiftAssignment.objects.create(template=day, user=cls.ended, weekdays=[0], effective_from=MON,
                                       effective_until=MON + timedelta(days=2))
        cls.inactive_tpl = _tech('r-inactive-template')
        ShiftAssignment.objects.create(template=off, user=cls.inactive_tpl, weekdays=[0], effective_from=MON)
        WorkingHours.objects.create(user=cls.inactive_tpl, weekday=0, start_time=time(9), end_time=time(12))
        cls.hours = _tech('r-hours')
        WorkingHours.objects.create(user=cls.hours, weekday=0, start_time=time(9), end_time=time(17))
        WorkingHours.objects.create(user=cls.hours, weekday=1, start_time=time(9), end_time=time(17),
                                    is_active=False)
        cls.free = _tech('r-free')
        cls.users = [cls.direct, cls.teamed, cls.ended, cls.inactive_tpl, cls.hours, cls.free]
        UserSkill.objects.create(user=cls.direct, name='Printer', proficiency='expert')
        UserSkill.objects.create(user=cls.direct, name='Active Directory', proficiency='advanced')
        UserSkill.objects.create(user=cls.hours, name='printer', proficiency='basic')
        Membership.objects.create(user=cls.direct, organization=cls.org, role=Role.ADMIN, is_active=True)
        Membership.objects.create(user=cls.teamed, organization=cls.org, role=Role.ADMIN, is_active=False)
        Membership.objects.create(user=cls.hours, organization=cls.other_org, role=Role.ADMIN, is_active=True)
        today = date.today()
        LeaveRequest.objects.create(user=cls.free, leave_type='vacation', start_date=today, end_date=today,
                                    status='approved')
        LeaveRequest.objects.create(user=cls.hours, leave_type='vacation', start_date=today, end_date=today,
                                    status='pending')
        from tech_access.testing import make_ticket
        for _ in range(5):
            make_ticket(cls.org, assigned_to=cls.hours)
        cls.ticket = make_ticket(cls.org, subject='Printer offline in Active Directory site')
        cls.other_ticket = make_ticket(cls.other_org, subject='Nothing matches')

    def whens(self):
        for d in range(0, 10):
            for hh in (3, 8, 9, 13, 15, 16, 21, 23):
                yield datetime.combine(MON + timedelta(days=d), time(hh), tzinfo=dt_tz.utc)

    def test_shift_book_matches_the_per_user_functions(self):
        book = shifts.ShiftBook(self.users)
        for u in self.users:
            self.assertEqual([a.pk for a in book.rows(u)], [a.pk for a in shifts.assignments_qs(u)], u.username)
            for when in self.whens():
                with self.subTest(user=u.username, when=when):
                    self.assertEqual(book.is_working(u, when), shifts.is_working(u, when))
                    self.assertEqual(shifts.is_working(u, when, book=book), shifts.is_working(u, when))
                    a, b = book.shift_at(u, when), shifts.shift_at(u, when)
                    self.assertEqual(a and (a.assignment.pk, a.starts_at), b and (b.assignment.pk, b.starts_at))
                    on = when.date()
                    self.assertEqual(book.has_schedule(u, on=on), shifts.has_schedule(u, on=on))

    def test_week_grid_with_a_book_is_identical(self):
        def flat(rows):
            return [(r['user'].pk, [(c['day'], [(s.assignment.pk, s.starts_at) for s in c['shifts']],
                                     c['conflict']) for c in r['cells']]) for r in rows]
        book = shifts.ShiftBook(self.users)
        self.assertEqual(flat(shifts.week_grid(self.users, MON, 7, book=book)),
                         flat(shifts.week_grid(self.users, MON, 7)))

    def test_ranking_with_shared_facts_is_identical(self):
        facts = RankingFacts()
        for t in (self.ticket, self.other_ticket):
            plain = rank_techs_for_ticket(t)
            shared = rank_techs_for_ticket(t, facts=facts)
            self.assertEqual([(r['user'].pk, r['score'], r['reasons'], r['available_now']) for r in shared],
                             [(r['user'].pk, r['score'], r['reasons'], r['available_now']) for r in plain])
        reasons = {r['user'].pk: r['reasons'] for r in rank_techs_for_ticket(self.ticket, facts=facts)}
        self.assertIn('matches skills: Active Directory, Printer', reasons[self.direct.pk])
        self.assertIn('on leave today', reasons[self.free.pk])
        self.assertIn('5 open tickets', reasons[self.hours.pk])

    def test_facts_cost_does_not_grow_with_technicians(self):
        def count():
            from django.db import connection
            from django.test.utils import CaptureQueriesContext
            with CaptureQueriesContext(connection) as ctx:
                facts = RankingFacts()
                for _ in range(5):
                    rank_techs_for_ticket(self.ticket, facts=facts)
            return len(ctx.captured_queries)
        few = count()
        for i in range(12):
            u = _tech(f'r-extra-{i}')
            UserSkill.objects.create(user=u, name=f'Skill {i}', proficiency='basic')
            WorkingHours.objects.create(user=u, weekday=i % 7, start_time=time(9), end_time=time(17))
        self.assertEqual(count(), few)
