"""SLA breach persistence and pause accounting.

Two defects this pins.

**The breach report was always empty.** `Ticket.sla_breached_response` and
`sla_breached_resolution` are declared fields that no production code ever set.
`reports.generators.PSASLABreachesReport` filters on them, and the
`sla_breach_count_30d` KPI counts them, so both reported zero breaches no
matter what happened. Meanwhile `psa.sla.resolution_breached()` computed the
truth live for the ticket badge — so the badge said breached and the report
said none.

**Pausing the clock never moved the deadline.** `psa/sla.py` said in its own
module docstring that "we extend the due-date by the pause duration on resume",
and nothing did. `Ticket.sla_paused_until` was declared and never written by
any code. A ticket parked in Waiting on Client for three days came back with
its original deadline and breached immediately, through no fault of the tech.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from core.models import Organization
from psa.models import (Queue, Ticket, TicketPriority, TicketStatus,
                        TicketType)
from psa import sla


class SLATestBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='SLA Co', slug='sla-co')
        cls.open_status = TicketStatus.objects.create(
            name='In Progress', slug='sla-open')
        cls.waiting = TicketStatus.objects.create(
            name='Waiting on Client', slug='sla-waiting', pauses_sla=True)
        cls.closed = TicketStatus.objects.create(
            name='Resolved', slug='sla-closed', is_terminal=True)
        cls.priority = TicketPriority.objects.create(
            code='SLAP1', name='Critical', sort_order=0,
            response_target_minutes=30, resolution_target_minutes=240)
        cls.ttype = TicketType.objects.create(name='Incident-sla')
        cls.queue = Queue.objects.create(name='Helpdesk-sla')

    def _ticket(self, **kw):
        t = Ticket.objects.create(
            organization=self.org, subject='SLA ticket',
            status=kw.pop('status', self.open_status),
            priority=self.priority, ticket_type=self.ttype, queue=self.queue,
            **kw)
        sla.apply_due_dates(t)
        return t


class BreachFlagPersistenceTests(SLATestBase):

    def test_a_live_breach_is_persisted_to_the_flag(self):
        t = self._ticket()
        Ticket.objects.filter(pk=t.pk).update(
            resolution_due_at=timezone.now() - timedelta(hours=2))
        t.refresh_from_db()

        self.assertTrue(sla.resolution_breached(t),
                        'precondition: this ticket really is past due')
        sla.refresh_breach_flags(t)
        t.refresh_from_db()
        self.assertTrue(
            t.sla_breached_resolution,
            'the breach report reads this flag; it stayed False while the '
            'ticket badge said breached',
        )

    def test_an_on_track_ticket_is_not_flagged(self):
        t = self._ticket()
        sla.refresh_breach_flags(t)
        t.refresh_from_db()
        self.assertFalse(t.sla_breached_resolution)
        self.assertFalse(t.sla_breached_response)

    def test_response_breach_is_tracked_separately(self):
        t = self._ticket()
        Ticket.objects.filter(pk=t.pk).update(
            first_response_due_at=timezone.now() - timedelta(hours=1))
        t.refresh_from_db()
        sla.refresh_breach_flags(t)
        t.refresh_from_db()
        self.assertTrue(t.sla_breached_response)
        self.assertFalse(t.sla_breached_resolution)

    def test_a_flag_clears_when_the_breach_goes_away(self):
        """Reopening a ticket or extending a deadline must not leave a stale
        breach on the record."""
        t = self._ticket()
        Ticket.objects.filter(pk=t.pk).update(sla_breached_resolution=True)
        t.refresh_from_db()
        sla.refresh_breach_flags(t)
        t.refresh_from_db()
        self.assertFalse(t.sla_breached_resolution)

    def test_the_report_sees_what_the_badge_sees(self):
        """The defect in one assertion: report and badge must agree."""
        t = self._ticket()
        Ticket.objects.filter(pk=t.pk).update(
            resolution_due_at=timezone.now() - timedelta(hours=3))
        t.refresh_from_db()
        sla.refresh_breach_flags(t)

        badge_says_breached = sla.resolution_breached(t)
        report_finds_it = Ticket.objects.filter(
            pk=t.pk, sla_breached_resolution=True).exists()
        self.assertEqual(badge_says_breached, report_finds_it)


class PauseAccountingTests(SLATestBase):

    def test_pausing_and_resuming_pushes_the_deadline_out(self):
        t = self._ticket()
        original_due = t.resolution_due_at

        t.status = self.waiting
        t.save()
        t.refresh_from_db()
        self.assertIsNotNone(
            t.sla_paused_at, 'the pause start was not recorded')

        # Three hours parked waiting on the client.
        Ticket.objects.filter(pk=t.pk).update(
            sla_paused_at=timezone.now() - timedelta(hours=3))
        t.refresh_from_db()

        t.status = self.open_status
        t.save()
        t.refresh_from_db()

        self.assertIsNone(t.sla_paused_at, 'the pause was not closed out')
        moved = (t.resolution_due_at - original_due).total_seconds() / 3600
        self.assertAlmostEqual(
            moved, 3, delta=0.05,
            msg='time spent waiting on the client was charged against the SLA',
        )

    def test_a_ticket_that_never_paused_keeps_its_deadline(self):
        t = self._ticket()
        original_due = t.resolution_due_at
        t.subject = 'edited'
        t.save()
        t.refresh_from_db()
        self.assertEqual(t.resolution_due_at, original_due)

    def test_pause_time_accumulates_across_several_pauses(self):
        t = self._ticket()
        original_due = t.resolution_due_at

        for hours in (2, 1):
            t.status = self.waiting
            t.save()
            Ticket.objects.filter(pk=t.pk).update(
                sla_paused_at=timezone.now() - timedelta(hours=hours))
            t.refresh_from_db()
            t.status = self.open_status
            t.save()
            t.refresh_from_db()

        moved = (t.resolution_due_at - original_due).total_seconds() / 3600
        self.assertAlmostEqual(moved, 3, delta=0.05)
        self.assertAlmostEqual(t.sla_paused_minutes, 180, delta=3)

    def test_a_ticket_paused_past_its_deadline_is_not_breached_on_resume(self):
        """The whole point. Parked long enough to blow the deadline, then
        resumed — the tech gets the time back, not a breach."""
        t = self._ticket()
        t.status = self.waiting
        t.save()
        Ticket.objects.filter(pk=t.pk).update(
            sla_paused_at=timezone.now() - timedelta(hours=6))
        t.refresh_from_db()

        t.status = self.open_status
        t.save()
        t.refresh_from_db()
        self.assertFalse(
            sla.resolution_breached(t),
            'six hours waiting on the client produced a breach on resume',
        )

    def test_response_deadline_moves_too(self):
        t = self._ticket()
        original = t.first_response_due_at
        t.status = self.waiting
        t.save()
        Ticket.objects.filter(pk=t.pk).update(
            sla_paused_at=timezone.now() - timedelta(hours=2))
        t.refresh_from_db()
        t.status = self.open_status
        t.save()
        t.refresh_from_db()
        moved = (t.first_response_due_at - original).total_seconds() / 3600
        self.assertAlmostEqual(moved, 2, delta=0.05)


class SLATickTests(SLATestBase):
    """A ticket that quietly runs out of time is never saved, so the tick is
    the only thing that can notice it breached."""

    def test_the_tick_flags_a_ticket_that_ran_out_of_time(self):
        from django.core.management import call_command
        from io import StringIO

        t = self._ticket()
        Ticket.objects.filter(pk=t.pk).update(
            resolution_due_at=timezone.now() - timedelta(hours=1),
            sla_breached_resolution=False)

        out = StringIO()
        call_command('psa_sla_workflow_tick', stdout=out)
        t.refresh_from_db()
        self.assertTrue(
            t.sla_breached_resolution,
            'nothing saved this ticket, so nothing noticed it had breached',
        )
        self.assertIn('breach flag(s) updated', out.getvalue())

    def test_the_tick_skips_closed_tickets(self):
        from django.core.management import call_command
        from io import StringIO

        t = self._ticket()
        Ticket.objects.filter(pk=t.pk).update(
            resolution_due_at=timezone.now() - timedelta(hours=1),
            status=self.closed, resolved_at=timezone.now())
        call_command('psa_sla_workflow_tick', stdout=StringIO())
        t.refresh_from_db()
        self.assertFalse(t.sla_breached_resolution)


class ReportAgreementTests(SLATestBase):
    """The defect that started this: the report and the badge disagreed."""

    def test_the_breach_report_finds_a_breached_ticket(self):
        from reports.generators import PSASLABreachesReport

        t = self._ticket()
        Ticket.objects.filter(pk=t.pk).update(
            resolution_due_at=timezone.now() - timedelta(hours=3))
        t.refresh_from_db()
        sla.refresh_breach_flags(t)

        report = PSASLABreachesReport(
            parameters={'days': 30}, organization=self.org).generate()
        rows = report.get('rows', report.get('data', []))
        self.assertEqual(
            len(rows), 1,
            'the SLA breach report is empty while the ticket badge says '
            'breached',
        )
        self.assertTrue(rows[0]['resolution_breached'])


class BreachIsHistoryTests(SLATestBase):
    """A recorded breach is a fact about the past. Refreshing must not erase
    one just because the ticket can no longer be evaluated."""

    def test_a_ticket_with_no_sla_target_keeps_its_recorded_breach(self):
        """Caught by reports.tests.KPIDashboardTests: a ticket flagged by an
        import or integration, with no due-date of its own, had its flag wiped
        on the next save."""
        t = self._ticket()
        Ticket.objects.filter(pk=t.pk).update(
            first_response_due_at=None, resolution_due_at=None,
            sla_breached_resolution=True)
        t.refresh_from_db()

        sla.refresh_breach_flags(t)
        t.refresh_from_db()
        self.assertTrue(
            t.sla_breached_resolution,
            'a recorded breach was cleared because there was no deadline left '
            'to evaluate it against',
        )

    def test_a_breach_still_clears_when_the_deadline_is_extended(self):
        """The legitimate clear: there is a deadline, and it has not passed."""
        t = self._ticket()
        Ticket.objects.filter(pk=t.pk).update(sla_breached_resolution=True)
        t.refresh_from_db()
        sla.refresh_breach_flags(t)
        t.refresh_from_db()
        self.assertFalse(t.sla_breached_resolution)

    def test_resolved_late_stays_breached(self):
        t = self._ticket()
        Ticket.objects.filter(pk=t.pk).update(
            resolution_due_at=timezone.now() - timedelta(hours=2),
            resolved_at=timezone.now())
        t.refresh_from_db()
        sla.refresh_breach_flags(t)
        t.refresh_from_db()
        self.assertTrue(t.sla_breached_resolution)
