"""Phase 25: an approver sends individual entries back with a reason while the
rest of the week is approved; the technician sees why, fixes them and
resubmits them without disturbing what was already approved."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, Role
from core.models import Organization, SystemSetting
from psa.models import (Queue, Ticket, TicketPriority, TicketStatus, TicketTimeEntry, TicketType,
                        TimeEntryAuditEvent, TimesheetSubmission)
from psa.tests._base import TEST_MIDDLEWARE, _make_msp_tech, _setup_seed


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TimesheetEntryRejectionTests(TestCase):
    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='Return Co', slug='return-co-25')
        self.tech = _make_msp_tech(User.objects.create_user('ret-tech', password='pw'))
        self.manager = _make_msp_tech(User.objects.create_user('ret-mgr', password='pw', is_staff=True))
        for u in (self.tech, self.manager):
            Membership.objects.create(user=u, organization=self.org, role=Role.OWNER, is_active=True)
        self.ticket = Ticket.objects.create(
            organization=self.org, subject='Server', description='x',
            queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(), status=TicketStatus.objects.first())
        start = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)
        self.e1 = TicketTimeEntry.objects.create(ticket=self.ticket, user=self.tech, started_at=start,
                                                 ended_at=start + timedelta(minutes=30), notes='patching')
        self.e2 = TicketTimeEntry.objects.create(ticket=self.ticket, user=self.tech,
                                                 started_at=start + timedelta(hours=1),
                                                 ended_at=start + timedelta(hours=2), notes='lunch?')

    def _login(self, user):
        c = Client()
        c.force_login(user)
        s = c.session
        s['current_organization_id'] = self.org.id
        s.save()
        return c

    def _submit(self, client=None):
        r = (client or self._login(self.tech)).post('/psa/timesheet/', {'notes': 'week done'})
        self.assertEqual(r.status_code, 302)
        return TimesheetSubmission.objects.filter(user=self.tech).order_by('-revision').first()

    def _return_e2(self, sub, reason='Not billable - that was lunch', notes=''):
        return self._login(self.manager).post(
            f'/psa/timesheet-approvals/{sub.pk}/decide/',
            {'decision': 'approve', 'notes': notes, 'return_entry_ids': [self.e2.pk],
             f'return_reason_{self.e2.pk}': reason})

    def test_returned_entry_is_detached_with_reason_and_the_rest_approved(self):
        sub = self._submit()
        self._return_e2(sub)
        sub.refresh_from_db(); self.e1.refresh_from_db(); self.e2.refresh_from_db()
        self.assertEqual(sub.status, 'approved')
        self.assertEqual(self.e1.submission_id, sub.pk)
        self.assertIsNone(self.e2.submission_id)
        self.assertEqual(self.e2.rejection_reason, 'Not billable - that was lunch')
        self.assertEqual(self.e2.rejected_by, self.manager)
        self.assertIsNotNone(self.e2.rejected_at)
        self.assertEqual(sub.total_minutes, 30)

        ev = TimeEntryAuditEvent.objects.get(entry_ref=self.e2.pk, action='rejected')
        self.assertEqual((ev.actor, ev.note, ev.submission), (self.manager, 'Not billable - that was lunch', sub))
        self.assertFalse(TimeEntryAuditEvent.objects.filter(entry_ref=self.e2.pk, action='approved').exists())
        self.assertTrue(TimeEntryAuditEvent.objects.filter(entry_ref=self.e1.pk, action='approved').exists())

    def test_returned_entry_is_editable_and_the_approved_one_stays_locked(self):
        sub = self._submit()
        self._return_e2(sub)
        self.e2.refresh_from_db()
        self.e2.is_billable = False
        self.e2.save()
        self.e2.refresh_from_db()
        self.assertFalse(self.e2.is_billable)

        self.e1.refresh_from_db()
        self.e1.duration_minutes = 999
        self.e1.save()
        self.e1.refresh_from_db()
        self.assertEqual(self.e1.duration_minutes, 30)

    def test_technician_sees_the_reason_and_can_resubmit_only_returned_entries(self):
        sub = self._submit()
        self._return_e2(sub)
        tech = self._login(self.tech)
        page = tech.get('/psa/timesheet/')
        self.assertContains(page, 'Not billable - that was lunch')
        self.assertContains(page, 'Resubmit 1 entry')

        rev2 = self._submit(tech)
        self.assertEqual(rev2.revision, 2)
        self.assertEqual(rev2.status, 'pending')
        self.e1.refresh_from_db(); self.e2.refresh_from_db()
        self.assertEqual(self.e1.submission_id, sub.pk)        # still in the approved revision
        self.assertEqual(self.e2.submission_id, rev2.pk)
        self.assertEqual(self.e2.rejection_reason, '')
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'approved')
        self.assertEqual(
            list(TimeEntryAuditEvent.objects.filter(entry_ref=self.e2.pk).values_list('action', flat=True)),
            ['submitted', 'rejected', 'submitted'])

        self._login(self.manager).post(f'/psa/timesheet-approvals/{rev2.pk}/decide/',
                                       {'decision': 'approve'})
        rev2.refresh_from_db()
        self.assertEqual(rev2.status, 'approved')

    def test_approved_week_with_nothing_unsubmitted_cannot_be_resubmitted(self):
        sub = self._submit()
        sub.approve(user=self.manager)
        self._login(self.tech).post('/psa/timesheet/', {'notes': 'again'})
        self.assertEqual(TimesheetSubmission.objects.filter(user=self.tech).count(), 1)

    def test_reason_is_required(self):
        sub = self._submit()
        self._return_e2(sub, reason='')
        sub.refresh_from_db(); self.e2.refresh_from_db()
        self.assertEqual(sub.status, 'pending')
        self.assertEqual(self.e2.submission_id, sub.pk)

    def test_decision_notes_stand_in_for_a_blank_reason(self):
        sub = self._submit()
        self._return_e2(sub, reason='', notes='split the travel out')
        self.e2.refresh_from_db()
        self.assertEqual(self.e2.rejection_reason, 'split the travel out')

    def test_returning_every_entry_rejects_the_submission(self):
        sub = self._submit()
        self._login(self.manager).post(
            f'/psa/timesheet-approvals/{sub.pk}/decide/',
            {'decision': 'approve', 'return_entry_ids': [self.e1.pk, self.e2.pk],
             f'return_reason_{self.e1.pk}': 'wrong ticket',
             f'return_reason_{self.e2.pk}': 'lunch'})
        sub.refresh_from_db(); self.e1.refresh_from_db()
        self.assertEqual(sub.status, 'rejected')
        self.assertEqual(self.e1.rejection_reason, 'wrong ticket')
        # One rejected event per entry, not a second from reject().
        self.assertEqual(TimeEntryAuditEvent.objects.filter(entry_ref=self.e1.pk, action='rejected').count(), 1)

    def test_entry_from_another_submission_is_ignored(self):
        other = TimesheetSubmission.objects.create(
            user=self.manager, period_start=timezone.now().date(),
            period_end=timezone.now().date(), status='pending')
        stray = TicketTimeEntry.objects.create(
            ticket=self.ticket, user=self.manager, started_at=timezone.now(),
            ended_at=timezone.now() + timedelta(minutes=5), submission=other)
        sub = self._submit()
        self._login(self.manager).post(
            f'/psa/timesheet-approvals/{sub.pk}/decide/',
            {'decision': 'approve', 'return_entry_ids': [stray.pk],
             f'return_reason_{stray.pk}': 'x'})
        stray.refresh_from_db()
        self.assertEqual(stray.submission_id, other.pk)
        self.assertEqual(stray.rejection_reason, '')

    def test_queue_renders_send_back_controls(self):
        self._submit()
        r = self._login(self.manager).get('/psa/timesheet-approvals/')
        self.assertContains(r, 'name="return_entry_ids"')
        self.assertContains(r, f'name="return_reason_{self.e1.pk}"')
