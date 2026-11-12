"""Calendar days are the installation's local days (TIME_ZONE).

From 19:00/20:00 Eastern until midnight the UTC date is already tomorrow.
"Today" used to come from `timezone.now().date()` (the UTC date), so every
evening contracts ending today read as expired, invoices due today turned
overdue, the timesheet jumped to next week on Sunday night, and on New Year's
Eve numbers took next year's prefix. The clock is pinned to a UTC-aware value,
as Django's real now() returns; a local-aware mock would hide the bug.
"""
from datetime import date, datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from core.models import SystemSetting
from psa.models import Contract, Invoice, Ticket
from psa.tests._base import TEST_MIDDLEWARE, _make_msp_tech, _setup_seed

EASTERN = ZoneInfo('America/New_York')


def _clock(local):
    return mock.patch('django.utils.timezone.now', return_value=local.astimezone(ZoneInfo('UTC')))


EVENING = datetime(2026, 11, 11, 23, 0, tzinfo=EASTERN)
TODAY = date(2026, 11, 11)


@override_settings(TIME_ZONE='America/New_York')
class LocalDayModelTests(TestCase):

    def test_contract_ending_today_is_still_active_in_the_evening(self):
        contract = Contract(status='active', start_date=TODAY - timedelta(days=30), end_date=TODAY)
        with _clock(EVENING):
            self.assertTrue(contract.is_currently_active)

    def test_rollover_expiring_today_still_counts_in_the_evening(self):
        contract = Contract(total_hours=1, rolled_over_minutes=30, rollover_expires_at=TODAY)
        with _clock(EVENING):
            self.assertEqual(contract.effective_total_minutes(), 90)

    def test_invoice_due_today_reopens_as_sent_not_overdue(self):
        invoice = Invoice(status='paid', amount_paid=0, due_date=TODAY)
        with _clock(EVENING), mock.patch.object(Invoice, 'save'):
            invoice.reopen_if_unpaid()
        self.assertEqual(invoice.status, 'sent')

    def test_new_years_eve_numbers_keep_this_years_prefix(self):
        nye = datetime(2026, 12, 31, 23, 0, tzinfo=EASTERN)
        with _clock(nye):
            self.assertTrue(Ticket._generate_ticket_number().startswith('PSA-2026-'))
            self.assertTrue(Invoice()._next_number().startswith('INV-2026-'))


@override_settings(TIME_ZONE='America/New_York')
class DispatchLeaveConflictTests(TestCase):

    def test_leave_today_is_a_conflict_for_a_ticket_due_tonight(self):
        from psa.views import _dispatch_conflicts
        from resourcing.models import LeaveRequest
        tech = _make_msp_tech(User.objects.create_user('leave-tech', password='pw'))
        # Leave is read in the technician's own zone, as the router does.
        tech.profile.timezone = 'America/New_York'
        tech.profile.save()
        LeaveRequest.objects.create(user=tech, start_date=TODAY, end_date=TODAY, status='approved')
        # Rows come back from the database in UTC.
        ticket = Ticket(resolution_due_at=(EVENING + timedelta(minutes=30)).astimezone(ZoneInfo('UTC')))
        with _clock(EVENING):
            warnings = _dispatch_conflicts(tech, ticket)
        self.assertTrue(any(w.startswith('PTO conflict') for w in warnings), warnings)


@override_settings(TIME_ZONE='America/New_York', MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TimesheetLocalWeekTests(TestCase):

    def test_sunday_night_shows_this_week(self):
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        tech = _make_msp_tech(User.objects.create_user('sunday-tech', password='pw'))
        client = Client()
        client.force_login(tech)
        sunday_night = datetime(2026, 11, 15, 23, 0, tzinfo=EASTERN)
        with _clock(sunday_night):
            resp = client.get('/psa/timesheet/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['period_start'], date(2026, 11, 9))
