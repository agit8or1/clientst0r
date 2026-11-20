"""Ticket reminders (roadmap 52.21): create, My Work, scheduler, privacy, scope."""
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from psa.models import Ticket, TicketReminder
from psa.reminders import fire_due
from psa.tests.test_my_work import _MyWorkFixture
from psa.tests._base import TEST_MIDDLEWARE, _make_msp_tech
from django.test import TestCase


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TicketReminderTests(_MyWorkFixture, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls._build()

    def setUp(self):
        _make_msp_tech(self.tech)
        _make_msp_tech(self.other_tech)
        self.c = self._client(self.tech)
        self.t = self.t_replied

    def _add(self, client=None, ticket=None, when=None, note='call back'):
        ticket = ticket or self.t
        when = when or (timezone.localtime() + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M')
        return (client or self.c).post(
            reverse('psa:reminder_create', args=[ticket.ticket_number]),
            {'remind_at': when, 'note': note})

    def _mk(self, user=None, minutes=-5, ticket=None):
        return TicketReminder.objects.create(
            ticket=ticket or self.t, user=user or self.tech,
            remind_at=timezone.now() + timedelta(minutes=minutes), note='n')

    def test_create_and_list_on_ticket_page(self):
        r = self._add()
        self.assertEqual(r.status_code, 302)
        rem = TicketReminder.objects.get()
        self.assertEqual((rem.user, rem.ticket, rem.note), (self.tech, self.t, 'call back'))
        page = self.c.get(reverse('psa:ticket_detail', args=[self.t.ticket_number]))
        self.assertContains(page, 'call back')

    def test_invalid_time_creates_nothing(self):
        self._add(when='garbage')
        self.assertEqual(TicketReminder.objects.count(), 0)

    def test_create_is_post_only(self):
        r = self.c.get(reverse('psa:reminder_create', args=[self.t.ticket_number]))
        self.assertEqual(r.status_code, 405)

    def test_my_work_lists_due_and_upcoming(self):
        self._mk(minutes=-5)
        self._mk(minutes=120)
        r = self.c.get(reverse('psa:my_work'))
        self.assertEqual(len(r.context['reminders']), 2)
        self.assertEqual(r.context['reminders_due'], 1)
        self.assertContains(r, self.t.ticket_number)

    def test_completed_hidden_from_my_work(self):
        rem = self._mk()
        self.c.post(reverse('psa:reminder_complete', args=[rem.pk]))
        rem.refresh_from_db()
        self.assertIsNotNone(rem.completed_at)
        r = self.c.get(reverse('psa:my_work'))
        self.assertEqual(r.context['reminders'], [])

    def test_owner_can_delete(self):
        rem = self._mk()
        self.c.post(reverse('psa:reminder_delete', args=[rem.pk]))
        self.assertFalse(TicketReminder.objects.filter(pk=rem.pk).exists())

    def test_scheduler_fires_once(self):
        due = self._mk(minutes=-1)
        later = self._mk(minutes=60)
        self.assertEqual(fire_due(), 1)
        due.refresh_from_db()
        first = due.fired_at
        self.assertIsNotNone(first)
        self.assertEqual(fire_due(), 0)
        call_command('psa_ticket_reminders', stdout=StringIO())
        due.refresh_from_db()
        self.assertEqual(due.fired_at, first)
        later.refresh_from_db()
        self.assertIsNone(later.fired_at)

    def test_fired_reminder_counts_in_bell(self):
        from core.notifications import _ticket_reminders
        from django.test import RequestFactory
        self._mk(minutes=-1)
        fire_due()
        rf = RequestFactory().get('/')
        rf.user = self.tech
        rf.is_staff_user = False
        n = _ticket_reminders(self.tech, {'psa_enabled': True, 'request': rf})
        self.assertEqual(n, 1)

    def test_other_user_cannot_see_or_delete(self):
        rem = self._mk()
        other = self._client(self.other_tech)
        r = other.get(reverse('psa:my_work'))
        self.assertEqual(r.context['reminders'], [])
        page = other.get(reverse('psa:ticket_detail', args=[self.t.ticket_number]))
        self.assertNotContains(page, 'data-reminder="%d"' % rem.pk)
        self.assertEqual(other.post(reverse('psa:reminder_delete', args=[rem.pk])).status_code, 404)
        self.assertEqual(other.post(reverse('psa:reminder_complete', args=[rem.pk])).status_code, 404)
        self.assertTrue(TicketReminder.objects.filter(pk=rem.pk, completed_at__isnull=True).exists())

    def test_customer_user_cannot_create(self):
        r = self._add(client=self._client(self.customer), ticket=self.t_cust_shared)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(TicketReminder.objects.count(), 0)

    def test_cannot_create_on_unknown_ticket(self):
        r = self.c.post(reverse('psa:reminder_create', args=['NOPE-1']),
                        {'remind_at': '2030-01-01T10:00'})
        self.assertEqual(r.status_code, 404)

    def test_out_of_scope_reminder_hidden_from_my_work(self):
        rem = self._mk()
        # Scope is re-applied on read: a ticket outside the technician's
        # visible set does not leak through an old reminder.
        from unittest import mock
        with mock.patch('psa.views._scoped_ticket_qs', return_value=Ticket.objects.none()):
            r = self.c.get(reverse('psa:my_work'))
        self.assertEqual(r.context['reminders'], [])
        self.assertTrue(TicketReminder.objects.filter(pk=rem.pk).exists())
