"""Phase 25: per-entry timesheet approval trail — who approved or rejected
each entry, when, with what note, and every change after approval."""
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
class TimesheetAuditTrailTests(TestCase):
    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='Trail Co', slug='trail-co-25')
        self.tech = _make_msp_tech(User.objects.create_user('trail-tech', password='pw'))
        self.manager = _make_msp_tech(User.objects.create_user('trail-mgr', password='pw', is_staff=True))
        self.root = User.objects.create_user('trail-root', password='pw', is_superuser=True, is_staff=True)
        self.other = User.objects.create_user('trail-other', password='pw')  # a customer user
        for u in (self.tech, self.manager, self.root, self.other):
            Membership.objects.create(user=u, organization=self.org, role=Role.OWNER, is_active=True)
        self.ticket = Ticket.objects.create(
            organization=self.org, subject='Printer', description='x',
            queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(), status=TicketStatus.objects.first())
        start = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)
        self.e1 = TicketTimeEntry.objects.create(ticket=self.ticket, user=self.tech, started_at=start,
                                                 ended_at=start + timedelta(minutes=30), notes='first')
        self.e2 = TicketTimeEntry.objects.create(ticket=self.ticket, user=self.tech,
                                                 started_at=start + timedelta(hours=1),
                                                 ended_at=start + timedelta(hours=2), notes='second')

    def _login(self, user):
        c = Client()
        c.force_login(user)
        s = c.session
        s['current_organization_id'] = self.org.id
        s.save()
        return c

    def _submit(self):
        r = self._login(self.tech).post('/psa/timesheet/', {'notes': 'week done'})
        self.assertEqual(r.status_code, 302)
        return TimesheetSubmission.objects.get(user=self.tech)

    def _actions(self, entry):
        return list(TimeEntryAuditEvent.objects.filter(entry_ref=entry.pk).values_list('action', flat=True))

    def test_submit_and_approve_are_recorded_per_entry_with_actor_and_note(self):
        sub = self._submit()
        self._login(self.manager).post(f'/psa/timesheet-approvals/{sub.pk}/decide/',
                                       {'decision': 'approve', 'notes': 'looks right'})
        for e in (self.e1, self.e2):
            self.assertEqual(self._actions(e), ['submitted', 'approved'])
        ev = TimeEntryAuditEvent.objects.get(entry_ref=self.e1.pk, action='approved')
        self.assertEqual(ev.actor, self.manager)
        self.assertEqual(ev.note, 'looks right')
        self.assertEqual(ev.submission, sub)
        submitted = TimeEntryAuditEvent.objects.get(entry_ref=self.e1.pk, action='submitted')
        self.assertEqual(submitted.actor, self.tech)

    def test_rejection_is_kept_on_each_entry_after_it_is_detached(self):
        sub = self._submit()
        self._login(self.manager).post('/psa/timesheet-approvals/bulk/',
                                       {'decision': 'reject', 'submission_ids': [sub.pk],
                                        'notes': 'reclassify the printer time'})
        self.e1.refresh_from_db()
        self.assertIsNone(self.e1.submission_id)
        ev = TimeEntryAuditEvent.objects.get(entry_ref=self.e1.pk, action='rejected')
        self.assertEqual((ev.actor, ev.note), (self.manager, 'reclassify the printer time'))

    def test_refused_edit_and_forced_change_after_approval_are_recorded(self):
        sub = self._submit()
        sub.approve(user=self.manager)
        e = TicketTimeEntry.objects.get(pk=self.e1.pk)
        e.duration_minutes = 90
        e.save(_audit_user=self.tech)
        e.refresh_from_db()
        self.assertEqual(e.duration_minutes, 30)  # still locked
        refused = TimeEntryAuditEvent.objects.get(entry_ref=e.pk, action='edit_refused')
        self.assertEqual(refused.changes, {'duration_minutes': [30, 90]})

        e.duration_minutes = 45
        e.save(_force_unlock=True, _audit_user=self.root, _audit_note='customer call was 45 min')
        changed = TimeEntryAuditEvent.objects.get(entry_ref=e.pk, action='changed_after_approval')
        self.assertEqual(changed.changes, {'duration_minutes': [30, 45]})
        self.assertEqual((changed.actor, changed.note), (self.root, 'customer call was 45 min'))

    def test_saving_an_unchanged_approved_entry_records_nothing(self):
        sub = self._submit()
        sub.approve(user=self.manager)
        TicketTimeEntry.objects.get(pk=self.e1.pk).save()
        self.assertEqual(self._actions(self.e1), ['submitted', 'approved'])

    def test_delete_after_approval_is_recorded_and_trail_survives(self):
        sub = self._submit()
        sub.approve(user=self.manager)
        pk = self.e2.pk
        TicketTimeEntry.objects.get(pk=pk).delete()
        self.assertEqual(self._actions(type('E', (), {'pk': pk})), ['submitted', 'approved', 'deleted_after_approval'])
        r = self._login(self.manager).get(f'/psa/time-entries/{pk}/history/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Deleted after approval')

    def test_history_page_and_approval_screen_show_the_trail(self):
        sub = self._submit()
        r = self._login(self.manager).get('/psa/timesheet-approvals/')
        self.assertContains(r, 'Submitted for approval')
        self.assertContains(r, f'/psa/time-entries/{self.e1.pk}/history/')
        sub.approve(user=self.manager, notes='ok for payroll')
        r = self._login(self.tech).get(f'/psa/time-entries/{self.e1.pk}/history/')
        self.assertContains(r, 'ok for payroll')
        self.assertContains(r, 'trail-mgr')
        self.assertNotContains(r, 'Change this approved entry')  # superuser only
        # A customer user cannot read a technician's entry trail.
        self.assertEqual(self._login(self.other).get(f'/psa/time-entries/{self.e1.pk}/history/').status_code, 404)

    def test_superuser_correction_needs_a_reason_and_is_recorded(self):
        sub = self._submit()
        sub.approve(user=self.manager)
        c = self._login(self.root)
        c.post(f'/psa/time-entries/{self.e1.pk}/correct/', {'duration_minutes': '40', 'is_billable': '1'})
        self.e1.refresh_from_db()
        self.assertEqual(self.e1.duration_minutes, 30)
        c.post(f'/psa/time-entries/{self.e1.pk}/correct/',
               {'duration_minutes': '40', 'is_billable': '1', 'notes': 'first', 'reason': 'typo'})
        self.e1.refresh_from_db()
        self.assertEqual(self.e1.duration_minutes, 40)
        ev = TimeEntryAuditEvent.objects.get(entry_ref=self.e1.pk, action='changed_after_approval')
        self.assertEqual((ev.actor, ev.note, ev.changes), (self.root, 'typo', {'duration_minutes': [30, 40]}))
        # Non-superusers cannot use the correction endpoint.
        r = self._login(self.manager).post(f'/psa/time-entries/{self.e1.pk}/correct/',
                                           {'duration_minutes': '5', 'reason': 'x'})
        self.assertEqual(r.status_code, 404)
