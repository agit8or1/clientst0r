"""
Phase 11 — Advanced Dispatch & Technician Scheduling tests.

11.1 — Dispatch prioritization (priority + SLA proximity sort) + SLA-burn
panel (open tickets due within 4 hours surface above the grid).

Subsequent sub-phases (PTO conflict awareness, calendar conflict
detection, recurring onsite, geo-aware routing, etc.) will append to
this module.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, Role
from core.models import Organization, SystemSetting
from psa.models import (
    ClientPSASettings,
    Queue,
    Ticket,
    TicketPriority,
    TicketStatus,
    TicketType,
)
from psa.tests._base import (
    TEST_MIDDLEWARE,
    _setup_seed,
    _enable_psa_global,
    _enable_psa_for,
    _make_msp_tech,
)


def _make_ticket(*, org, priority, status, queue, ttype,
                  subject='t', resolution_due_at=None, first_response_due_at=None,
                  assigned_to=None):
    return Ticket.objects.create(
        organization=org, subject=subject,
        queue=queue, priority=priority, ticket_type=ttype, status=status,
        resolution_due_at=resolution_due_at,
        first_response_due_at=first_response_due_at,
        assigned_to=assigned_to,
    )


class DispatchPriorityKeyTests(TestCase):
    """The pure-function sort key — no view rendering, just the ordering
    contract."""

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        cls.org = Organization.objects.create(name='Sort', slug='sort')
        cls.queue = Queue.objects.first()
        cls.status = TicketStatus.objects.filter(slug='new').first()
        cls.ttype = TicketType.objects.first()
        # Two priorities at known sort-orders. Seed defaults already include P1-P5.
        cls.p_high = TicketPriority.objects.order_by('sort_order').first()
        cls.p_low = TicketPriority.objects.order_by('-sort_order').first()
        cls.now = timezone.now()

    def test_higher_priority_sorts_before_lower(self):
        from psa.views import _dispatch_priority_key
        t_high = _make_ticket(
            org=self.org, priority=self.p_high, status=self.status,
            queue=self.queue, ttype=self.ttype,
            resolution_due_at=self.now + timedelta(days=1),
        )
        t_low = _make_ticket(
            org=self.org, priority=self.p_low, status=self.status,
            queue=self.queue, ttype=self.ttype,
            resolution_due_at=self.now + timedelta(hours=1),
        )
        # `t_low` is due sooner but has lower priority — `t_high` still wins.
        ordered = sorted([t_low, t_high], key=_dispatch_priority_key)
        self.assertEqual(ordered[0], t_high)

    def test_within_priority_sooner_due_sorts_first(self):
        from psa.views import _dispatch_priority_key
        t_far = _make_ticket(
            org=self.org, priority=self.p_high, status=self.status,
            queue=self.queue, ttype=self.ttype,
            resolution_due_at=self.now + timedelta(days=3),
        )
        t_near = _make_ticket(
            org=self.org, priority=self.p_high, status=self.status,
            queue=self.queue, ttype=self.ttype,
            resolution_due_at=self.now + timedelta(hours=2),
        )
        ordered = sorted([t_far, t_near], key=_dispatch_priority_key)
        self.assertEqual(ordered[0], t_near)

    def test_no_due_date_sorts_last_within_priority(self):
        from psa.views import _dispatch_priority_key
        t_due = _make_ticket(
            org=self.org, priority=self.p_high, status=self.status,
            queue=self.queue, ttype=self.ttype,
            resolution_due_at=self.now + timedelta(days=1),
        )
        t_no_due = _make_ticket(
            org=self.org, priority=self.p_high, status=self.status,
            queue=self.queue, ttype=self.ttype,
        )
        ordered = sorted([t_no_due, t_due], key=_dispatch_priority_key)
        self.assertEqual(ordered[0], t_due)
        self.assertEqual(ordered[1], t_no_due)

    def test_first_response_due_used_when_no_resolution_due(self):
        from psa.views import _dispatch_priority_key
        t_resolution = _make_ticket(
            org=self.org, priority=self.p_high, status=self.status,
            queue=self.queue, ttype=self.ttype,
            resolution_due_at=self.now + timedelta(hours=10),
        )
        t_response = _make_ticket(
            org=self.org, priority=self.p_high, status=self.status,
            queue=self.queue, ttype=self.ttype,
            first_response_due_at=self.now + timedelta(hours=2),
        )
        ordered = sorted([t_resolution, t_response], key=_dispatch_priority_key)
        self.assertEqual(ordered[0], t_response)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DispatchSlaBurnPanelTests(TestCase):
    """Open tickets whose due time is within the next 4 hours surface in
    the SLA-burn panel above the grid. Already-overdue tickets stay in
    the existing overdue panel (not duplicated). Closed tickets are
    excluded."""

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        cls.org = Organization.objects.create(name='Burn', slug='burn')
        _enable_psa_for(cls.org)
        cls.queue = Queue.objects.first()
        cls.priority = TicketPriority.objects.order_by('sort_order').first()
        cls.ttype = TicketType.objects.first()
        cls.new_status = TicketStatus.objects.filter(slug='new').first()
        cls.closed_status = (TicketStatus.objects
                             .filter(is_terminal=True).first())

        cls.user = User.objects.create_user(
            'burn-user', password='pw', email='burn@x.com', is_staff=True,
        )
        Membership.objects.create(
            user=cls.user, organization=cls.org, role=Role.OWNER, is_active=True,
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.user)
        s = self.client.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()

    def test_in_window_open_ticket_appears_in_sla_burn(self):
        now = timezone.now()
        t = _make_ticket(
            org=self.org, priority=self.priority, status=self.new_status,
            queue=self.queue, ttype=self.ttype, subject='due in 2h',
            resolution_due_at=now + timedelta(hours=2),
        )
        resp = self.client.get('/psa/dispatch/')
        self.assertEqual(resp.status_code, 200)
        sla_burn = list(resp.context['sla_burn'])
        self.assertIn(t, sla_burn)

    def test_already_overdue_does_not_appear_in_sla_burn(self):
        # The view's overdue logic compares due-date to today via
        # `d_local < today` (date-only). Use yesterday so the ticket is
        # unambiguously overdue regardless of wall-clock hour at test time.
        now = timezone.now()
        t_overdue = _make_ticket(
            org=self.org, priority=self.priority, status=self.new_status,
            queue=self.queue, ttype=self.ttype, subject='already overdue',
            resolution_due_at=now - timedelta(days=1),
        )
        resp = self.client.get('/psa/dispatch/')
        self.assertNotIn(t_overdue, list(resp.context['sla_burn']))
        self.assertIn(t_overdue, list(resp.context['overdue']))

    def test_outside_window_does_not_appear_in_sla_burn(self):
        now = timezone.now()
        t_far = _make_ticket(
            org=self.org, priority=self.priority, status=self.new_status,
            queue=self.queue, ttype=self.ttype, subject='due in 8h',
            resolution_due_at=now + timedelta(hours=8),
        )
        resp = self.client.get('/psa/dispatch/')
        self.assertNotIn(t_far, list(resp.context['sla_burn']))

    def test_closed_ticket_does_not_appear_in_sla_burn(self):
        if self.closed_status is None:
            self.skipTest('no terminal TicketStatus in seed defaults')
        now = timezone.now()
        t_closed = _make_ticket(
            org=self.org, priority=self.priority, status=self.closed_status,
            queue=self.queue, ttype=self.ttype, subject='in window but closed',
            resolution_due_at=now + timedelta(hours=2),
        )
        resp = self.client.get('/psa/dispatch/')
        self.assertNotIn(t_closed, list(resp.context['sla_burn']))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DispatchBoardSortingTests(TestCase):
    """Within each lane (overdue, sla_burn, unassigned-by-day, assigned
    cells), tickets sort by `_dispatch_priority_key`. Verifies the
    higher-priority ticket lands at the head of the unassigned lane."""

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        cls.org = Organization.objects.create(name='Sortlane', slug='sortlane')
        _enable_psa_for(cls.org)
        cls.queue = Queue.objects.first()
        cls.ttype = TicketType.objects.first()
        cls.new_status = TicketStatus.objects.filter(slug='new').first()
        cls.p_high = TicketPriority.objects.order_by('sort_order').first()
        cls.p_low = TicketPriority.objects.order_by('-sort_order').first()
        cls.user = User.objects.create_user(
            'sort-user', password='pw', email='sort@x.com', is_staff=True,
        )
        Membership.objects.create(
            user=cls.user, organization=cls.org, role=Role.OWNER, is_active=True,
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.user)
        s = self.client.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()

    def test_higher_priority_unassigned_ticket_sorts_first(self):
        # Both tickets due ~24h from now — well within the 7-day window
        # but not overdue, regardless of wall-clock hour at test time.
        due = timezone.now() + timedelta(hours=24)
        t_low = _make_ticket(
            org=self.org, priority=self.p_low, status=self.new_status,
            queue=self.queue, ttype=self.ttype, subject='low',
            resolution_due_at=due,
        )
        t_high = _make_ticket(
            org=self.org, priority=self.p_high, status=self.new_status,
            queue=self.queue, ttype=self.ttype, subject='high',
            resolution_due_at=due,
        )
        resp = self.client.get('/psa/dispatch/')
        # The two unassigned tickets should land in the same day-bucket
        # within the unassigned_by_day list. Find the bucket that contains
        # both, then assert ordering.
        for lane in resp.context['unassigned_by_day']:
            lane_list = list(lane)
            if t_high in lane_list and t_low in lane_list:
                self.assertLess(lane_list.index(t_high), lane_list.index(t_low))
                return
        self.fail('expected t_high and t_low to share an unassigned-by-day bucket')


# ---------------------------------------------------------------------------
# Phase 11.2 — PTO + calendar conflict awareness
# ---------------------------------------------------------------------------

class DispatchConflictDetectionTests(TestCase):
    """`_dispatch_conflicts(tech, ticket)` returns advisory warnings when
    assigning would overlap with PTO or another ticket's due window."""

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        cls.org = Organization.objects.create(name='Conflict-Co', slug='conflict-co')
        cls.alice = User.objects.create_user('alice-conf', email='ac@x.com', password='pw')
        cls.queue = Queue.objects.first()
        cls.priority = TicketPriority.objects.order_by('sort_order').first()
        cls.ttype = TicketType.objects.first()
        cls.new_status = TicketStatus.objects.filter(slug='new').first()

    def _ticket(self, **overrides):
        defaults = dict(
            organization=self.org, subject='probe',
            queue=self.queue, priority=self.priority,
            ticket_type=self.ttype, status=self.new_status,
        )
        defaults.update(overrides)
        return Ticket.objects.create(**defaults)

    def test_no_warnings_when_unassigned(self):
        from psa.views import _dispatch_conflicts
        t = self._ticket(resolution_due_at=timezone.now() + timedelta(hours=4))
        self.assertEqual(_dispatch_conflicts(None, t), [])

    def test_no_warnings_when_no_due_date(self):
        from psa.views import _dispatch_conflicts
        t = self._ticket(resolution_due_at=None, first_response_due_at=None)
        # Without a due date there's no schedule to conflict with.
        self.assertEqual(_dispatch_conflicts(self.alice, t), [])

    def test_no_warnings_when_clean(self):
        from psa.views import _dispatch_conflicts
        t = self._ticket(resolution_due_at=timezone.now() + timedelta(hours=4))
        # No PTO + no other tickets → empty warnings.
        self.assertEqual(_dispatch_conflicts(self.alice, t), [])

    def test_pto_warning_when_tech_on_approved_leave(self):
        from psa.views import _dispatch_conflicts
        from resourcing.models import LeaveRequest
        # Approved leave covering the ticket's due date.
        future = timezone.now() + timedelta(days=2)
        LeaveRequest.objects.create(
            user=self.alice, leave_type='vacation',
            start_date=future.date(), end_date=future.date() + timedelta(days=2),
            status='approved',
        )
        t = self._ticket(resolution_due_at=future + timedelta(hours=8))
        warnings = _dispatch_conflicts(self.alice, t)
        self.assertTrue(any('PTO conflict' in w for w in warnings),
                        f'expected PTO warning in {warnings!r}')

    def test_no_pto_warning_when_leave_unapproved(self):
        from psa.views import _dispatch_conflicts
        from resourcing.models import LeaveRequest
        future = timezone.now() + timedelta(days=2)
        LeaveRequest.objects.create(
            user=self.alice, leave_type='vacation',
            start_date=future.date(), end_date=future.date() + timedelta(days=2),
            status='pending',  # NOT approved
        )
        t = self._ticket(resolution_due_at=future + timedelta(hours=8))
        warnings = _dispatch_conflicts(self.alice, t)
        self.assertFalse(any('PTO conflict' in w for w in warnings),
                         f'pending leave should NOT trigger conflict, got {warnings!r}')

    def test_calendar_overlap_within_two_hour_window(self):
        from psa.views import _dispatch_conflicts
        due = timezone.now() + timedelta(hours=8)
        # Existing assigned ticket due 1 hour later.
        Ticket.objects.create(
            organization=self.org, subject='other',
            queue=self.queue, priority=self.priority,
            ticket_type=self.ttype, status=self.new_status,
            assigned_to=self.alice,
            resolution_due_at=due + timedelta(hours=1),
        )
        new = self._ticket(resolution_due_at=due)
        warnings = _dispatch_conflicts(self.alice, new)
        self.assertTrue(any('Calendar conflict' in w for w in warnings),
                        f'expected calendar conflict in {warnings!r}')

    def test_no_calendar_overlap_outside_window(self):
        from psa.views import _dispatch_conflicts
        due = timezone.now() + timedelta(hours=8)
        # Existing ticket due 5 hours later — outside the ±2-hour window.
        Ticket.objects.create(
            organization=self.org, subject='far',
            queue=self.queue, priority=self.priority,
            ticket_type=self.ttype, status=self.new_status,
            assigned_to=self.alice,
            resolution_due_at=due + timedelta(hours=5),
        )
        new = self._ticket(resolution_due_at=due)
        warnings = _dispatch_conflicts(self.alice, new)
        self.assertFalse(any('Calendar conflict' in w for w in warnings),
                         f'5h-out should NOT conflict, got {warnings!r}')

    def test_closed_ticket_does_not_count_as_calendar_conflict(self):
        from psa.views import _dispatch_conflicts
        due = timezone.now() + timedelta(hours=8)
        closed_status = TicketStatus.objects.filter(is_terminal=True).first()
        if closed_status is None:
            self.skipTest('no terminal TicketStatus seeded')
        Ticket.objects.create(
            organization=self.org, subject='done',
            queue=self.queue, priority=self.priority,
            ticket_type=self.ttype, status=closed_status,
            assigned_to=self.alice,
            resolution_due_at=due + timedelta(hours=1),
        )
        new = self._ticket(resolution_due_at=due)
        self.assertEqual(_dispatch_conflicts(self.alice, new), [])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DispatchAssignWarningResponseTests(TestCase):
    """`/psa/dispatch/assign/` returns a `conflict_warnings` array in the
    JSON response when assigning a tech with PTO or a calendar overlap."""

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        cls.org = Organization.objects.create(name='Resp-Co', slug='resp-co')
        _enable_psa_for(cls.org)
        cls.queue = Queue.objects.first()
        cls.priority = TicketPriority.objects.order_by('sort_order').first()
        cls.ttype = TicketType.objects.first()
        cls.new_status = TicketStatus.objects.filter(slug='new').first()

        cls.bob = _make_msp_tech(User.objects.create_user('bob-resp', email='br@x.com', password='pw'))
        cls.staff = User.objects.create_user(
            'dispatcher', email='d@x.com', password='pw', is_staff=True,
        )
        Membership.objects.create(
            user=cls.staff, organization=cls.org, role=Role.OWNER, is_active=True,
        )
        Membership.objects.create(
            user=cls.bob, organization=cls.org, role=Role.OWNER, is_active=True,
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.staff)
        s = self.client.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()

    def test_clean_assignment_has_empty_warnings_array(self):
        from psa.models import Ticket
        t = Ticket.objects.create(
            organization=self.org, subject='clean',
            queue=self.queue, priority=self.priority,
            ticket_type=self.ttype, status=self.new_status,
            resolution_due_at=timezone.now() + timedelta(days=2),
        )
        resp = self.client.post('/psa/dispatch/assign/', {
            'ticket_number': t.ticket_number,
            'assignee': str(self.bob.id),
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['ok'])
        self.assertEqual(body['conflict_warnings'], [])

    def test_pto_conflict_appears_in_warnings_array(self):
        from psa.models import Ticket
        from resourcing.models import LeaveRequest
        future = timezone.now() + timedelta(days=2)
        LeaveRequest.objects.create(
            user=self.bob, leave_type='sick',
            start_date=future.date(), end_date=future.date() + timedelta(days=1),
            status='approved',
        )
        t = Ticket.objects.create(
            organization=self.org, subject='conflict',
            queue=self.queue, priority=self.priority,
            ticket_type=self.ttype, status=self.new_status,
            resolution_due_at=future + timedelta(hours=4),
        )
        resp = self.client.post('/psa/dispatch/assign/', {
            'ticket_number': t.ticket_number,
            'assignee': str(self.bob.id),
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['ok'])  # not blocked, just warned
        self.assertTrue(
            any('PTO conflict' in w for w in body['conflict_warnings']),
            f'expected PTO warning in {body["conflict_warnings"]!r}',
        )


# ---------------------------------------------------------------------------
# Phase 11.3 — Dispatch heatmap
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DispatchHeatmapTests(TestCase):
    """`/psa/dispatch/heatmap/` aggregates open assigned tickets by
    (tech, due-date) over a ±7-day window. Color intensity 0..4."""

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        cls.org = Organization.objects.create(name='HeatCo', slug='heat-co')
        _enable_psa_for(cls.org)
        cls.queue = Queue.objects.first()
        cls.priority = TicketPriority.objects.order_by('sort_order').first()
        cls.ttype = TicketType.objects.first()
        cls.new_status = TicketStatus.objects.filter(slug='new').first()

        cls.alice = User.objects.create_user('alice-heat', email='ah@x.com', password='pw', is_staff=True)
        cls.bob = User.objects.create_user('bob-heat', email='bh@x.com', password='pw', is_staff=True)
        Membership.objects.create(
            user=cls.alice, organization=cls.org, role=Role.OWNER, is_active=True,
        )
        Membership.objects.create(
            user=cls.bob, organization=cls.org, role=Role.OWNER, is_active=True,
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.alice)
        s = self.client.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()

    def _ticket(self, *, assigned_to, due, **overrides):
        defaults = dict(
            organization=self.org, subject='probe',
            queue=self.queue, priority=self.priority,
            ticket_type=self.ttype, status=self.new_status,
            assigned_to=assigned_to,
            resolution_due_at=due,
        )
        defaults.update(overrides)
        return Ticket.objects.create(**defaults)

    def test_view_returns_200_for_authenticated_user(self):
        resp = self.client.get('/psa/dispatch/heatmap/')
        self.assertEqual(resp.status_code, 200)

    def test_window_spans_15_days(self):
        # ±7 days inclusive of today = 15 columns.
        resp = self.client.get('/psa/dispatch/heatmap/')
        self.assertEqual(len(list(resp.context['days'])), 15)

    def test_assigned_ticket_with_due_date_appears_in_aggregation(self):
        due = timezone.now() + timedelta(days=2)
        self._ticket(assigned_to=self.alice, due=due)
        resp = self.client.get('/psa/dispatch/heatmap/')
        rows = list(resp.context['rows'])
        # Alice's row should exist with at least one cell having count > 0.
        alice_row = next((r for r in rows if r['tech'] == self.alice), None)
        self.assertIsNotNone(alice_row, 'alice missing from heatmap rows')
        self.assertGreaterEqual(sum(c['count'] for c in alice_row['cells']), 1)

    def test_unassigned_ticket_not_in_heatmap(self):
        # Heatmap only counts assigned tickets — an unassigned one with
        # a due date in window should NOT show up.
        self._ticket(assigned_to=None, due=timezone.now() + timedelta(days=2))
        resp = self.client.get('/psa/dispatch/heatmap/')
        # Row count: techs with at least one assigned in-window ticket.
        # We have 0 assignees, so rows is empty.
        self.assertEqual(len(list(resp.context['rows'])), 0)

    def test_ticket_outside_window_not_counted(self):
        # 30 days out — outside the ±7-day window.
        self._ticket(assigned_to=self.alice, due=timezone.now() + timedelta(days=30))
        resp = self.client.get('/psa/dispatch/heatmap/')
        # Alice has zero in-window assignments → no row.
        self.assertEqual(len(list(resp.context['rows'])), 0)

    def test_ticket_without_due_date_not_counted(self):
        self._ticket(assigned_to=self.alice, due=None, first_response_due_at=None)
        resp = self.client.get('/psa/dispatch/heatmap/')
        self.assertEqual(len(list(resp.context['rows'])), 0)

    def test_max_count_reflects_busiest_cell(self):
        # 3 tickets for alice on the same day, 1 for bob.
        due = timezone.now() + timedelta(days=1)
        for i in range(3):
            self._ticket(assigned_to=self.alice, due=due, subject=f'a{i}')
        self._ticket(assigned_to=self.bob, due=due, subject='b1')
        resp = self.client.get('/psa/dispatch/heatmap/')
        # max_count across all (tech, day) cells is 3.
        self.assertEqual(resp.context['max_count'], 3)

    def test_tenant_isolation_filters_other_org_tickets(self):
        # Alice is in HeatCo; create a ticket in a different org assigned
        # to her — it should NOT appear in HeatCo's heatmap.
        other_org = Organization.objects.create(name='HeatOther', slug='heat-other')
        Ticket.objects.create(
            organization=other_org, subject='other-org',
            queue=self.queue, priority=self.priority,
            ticket_type=self.ttype, status=self.new_status,
            assigned_to=self.alice,
            resolution_due_at=timezone.now() + timedelta(days=1),
        )
        resp = self.client.get('/psa/dispatch/heatmap/')
        # No tickets in HeatCo → no rows.
        self.assertEqual(len(list(resp.context['rows'])), 0)
