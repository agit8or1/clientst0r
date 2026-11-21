"""Customer follow-up and confirm-or-close (roadmap 52.24)."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role
from audit.models import AuditLog
from core.models import Organization
from psa import followup
from psa.models import (
    ClientPSASettings, FollowUpPolicy, Queue, Ticket, TicketComment,
    TicketPriority, TicketStatus, TicketType,
)
from psa.my_work import record_customer_reply
from psa.tests._base import (
    TEST_MIDDLEWARE, _enable_psa_for, _enable_psa_global, _make_msp_tech, _setup_seed,
)

LOCMEM = 'django.core.mail.backends.locmem.EmailBackend'


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, EMAIL_BACKEND=LOCMEM)
class CustomerFollowUpTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        cls.org = Organization.objects.create(name='Fu Co', slug='fu-co')
        cls.other_org = Organization.objects.create(name='Other Co', slug='other-co')
        for o in (cls.org, cls.other_org):
            _enable_psa_for(o)
        cls.tech = User.objects.create_user('fu_tech', 'tech@msp.test', 'pw-fu-123')
        cls.outsider = User.objects.create_user('fu_out', 'out@other.test', 'pw-fu-123')
        Membership.objects.create(user=cls.outsider, organization=cls.other_org,
                                  role=Role.EDITOR, is_active=True)
        Membership.objects.create(user=cls.tech, organization=cls.org,
                                  role=Role.EDITOR, is_active=True)
        _make_msp_tech(cls.tech)

    def setUp(self):
        mail.outbox = []
        self.now = timezone.now()
        self.policy = FollowUpPolicy.get()
        self.policy.enabled = True
        self.policy.save()

    def _ticket(self, slug='waiting-on-client', days=0, email='cust@fu.test', **kw):
        t = Ticket.objects.create(
            organization=self.org, subject='Printer jam', requester_email=email,
            queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.get(slug=slug), **kw)
        Ticket.objects.filter(pk=t.pk).update(
            sla_paused_at=self.now - timedelta(days=days, minutes=1))
        t.refresh_from_db()
        return t

    def _login(self, user):
        c = Client()
        c.force_login(user)
        s = c.session
        s['current_organization_id'] = self.org.id
        s.save()
        return c

    def _run(self, **kw):
        return followup.run(now=self.now + timedelta(**kw) if kw else self.now)

    def test_disabled_by_default_sends_nothing(self):
        FollowUpPolicy.objects.all().delete()
        self.assertFalse(FollowUpPolicy.get().enabled)
        self._ticket(days=30)
        self.assertEqual(self._run(), {'followup': 0, 'reminder': 0, 'closed': 0})
        self.assertEqual(len(mail.outbox), 0)

    def test_not_due_before_n_days(self):
        self._ticket(days=2)
        self._run()
        self.assertEqual(len(mail.outbox), 0)

    def test_followup_sent_once_at_n_days(self):
        t = self._ticket(days=3)
        self.assertEqual(self._run()['followup'], 1)
        self.assertEqual(self._run()['followup'], 0)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['cust@fu.test'])
        self.assertIn(t.ticket_number, mail.outbox[0].body)
        c = TicketComment.objects.get(ticket=t, source='followup')
        self.assertFalse(c.is_internal)
        self.assertTrue(c.is_system)
        self.assertTrue(AuditLog.objects.filter(
            object_id=t.pk, extra_data__event='followup_sent').exists())

    def test_second_reminder_then_close(self):
        t = self._ticket(days=3)
        self._run()                                  # first follow-up
        self.assertEqual(self._run(days=1)['reminder'], 0)
        self.assertEqual(self._run(days=2)['reminder'], 1)
        self.assertEqual(self._run(days=2)['reminder'], 0)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(self._run(days=5)['closed'], 1)
        t.refresh_from_db()
        self.assertTrue(t.status.is_terminal)
        self.assertIsNotNone(t.closed_at)

    def test_close_records_reason_on_timeline_and_audit(self):
        t = self._ticket(days=3)
        self._run()
        self._run(days=4)  # 7 days since the wait began
        t.refresh_from_db()
        self.assertEqual(t.status.slug, 'closed')
        self.assertIn('without a reply from the customer', t.resolution_summary)
        self.assertTrue(TicketComment.objects.filter(
            ticket=t, is_internal=True, body__startswith='Closed after ').exists())
        self.assertTrue(AuditLog.objects.filter(
            object_id=t.pk, extra_data__event='followup_closed').exists())
        # follow-up, closure notice
        self.assertEqual(len(mail.outbox), 2)

    def test_customer_reply_resets_the_clock(self):
        t = self._ticket(days=3)
        self._run()
        t.refresh_from_db()
        record_customer_reply(t, via='portal')
        t.refresh_from_db()
        self.assertFalse(followup.ticket_in_cycle(t))  # moved out of waiting
        # Back to waiting later: a fresh period, nothing is due yet.
        t.status = TicketStatus.objects.get(slug='waiting-on-client')
        t.save()
        mail.outbox = []
        self._run(days=1)
        self.assertEqual(len(mail.outbox), 0)
        t.refresh_from_db()
        self.assertNotEqual(t.status.slug, 'closed')

    def test_reply_without_status_change_resets_stamps(self):
        t = self._ticket(days=3)
        self._run()
        Ticket.objects.filter(pk=t.pk).update(last_client_response_at=self.now + timedelta(hours=1))
        self.assertEqual(self._run(days=2)['closed'], 0)
        t.refresh_from_db()
        self.assertIsNone(t.followup_first_at)

    def test_pause_works(self):
        t = self._ticket(days=30)
        c = self._login(self.tech)
        r = c.post(reverse('psa:followup_pause', args=[t.ticket_number]), {'pause': '1'})
        self.assertEqual(r.status_code, 302)
        t.refresh_from_db()
        self.assertTrue(t.followup_paused)
        self._run()
        self.assertEqual(len(mail.outbox), 0)
        c.post(reverse('psa:followup_pause', args=[t.ticket_number]), {'pause': '0'})
        self._run()
        self.assertEqual(len(mail.outbox), 1)

    def test_pause_is_post_only_and_staff_only(self):
        t = self._ticket(days=30)
        c = self._login(self.tech)
        # GET never changes anything (405, or bounced by the write guard).
        self.assertIn(c.get(reverse('psa:followup_pause', args=[t.ticket_number])).status_code, (302, 405))
        t.refresh_from_db()
        self.assertFalse(t.followup_paused)
        out = self._login(self.outsider)
        r = out.post(reverse('psa:followup_pause', args=[t.ticket_number]), {'pause': '1'})
        self.assertIn(r.status_code, (403, 404))
        t.refresh_from_db()
        self.assertFalse(t.followup_paused)

    def test_no_contact_sends_nothing(self):
        self._ticket(days=30, email='')
        self.assertEqual(self._run()['followup'], 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_staff_requester_sends_nothing(self):
        self._ticket(days=30, email='tech@msp.test')
        self._run()
        self.assertEqual(len(mail.outbox), 0)

    def test_notification_opt_out_respected(self):
        u = User.objects.create_user('quiet', 'quiet@fu.test', 'pw-fu-123')
        u.profile.email_notifications = False
        u.profile.save()
        self._ticket(days=30, email='quiet@fu.test')
        self._run()
        self.assertEqual(len(mail.outbox), 0)

    def test_cc_addresses_included(self):
        self._ticket(days=3, cc_emails=['boss@fu.test'])
        self._run()
        self.assertEqual(mail.outbox[0].cc, ['boss@fu.test'])

    def test_vendor_and_active_tickets_ignored(self):
        self._ticket(slug='waiting-on-vendor', days=30)
        self._ticket(slug='in-progress', days=30)
        self._run()
        self.assertEqual(len(mail.outbox), 0)

    def test_overlapping_runs_do_not_double_send(self):
        t = self._ticket(days=3)
        followup.process_ticket(Ticket.objects.select_related('status').get(pk=t.pk),
                                self.policy, self.now)
        stale = Ticket.objects.select_related('status').get(pk=t.pk)
        stale.followup_first_at = None  # a second run that read the row earlier
        self.assertIsNone(followup.process_ticket(stale, self.policy, self.now))
        self.assertEqual(len(mail.outbox), 1)

    def test_psa_opted_out_customer_never_messaged(self):
        ClientPSASettings.objects.update_or_create(
            organization=self.org,
            defaults={'enabled': False, 'followup_override': ClientPSASettings.FOLLOWUP_ON})
        t = self._ticket(days=30)
        self.assertEqual(self._run(), {'followup': 0, 'reminder': 0, 'closed': 0})
        self.assertEqual(len(mail.outbox), 0)
        self.assertIsNone(followup.schedule_for(t))

    def test_rerun_same_instant_is_idempotent(self):
        self._ticket(days=3)
        self._run()
        self._run()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(AuditLog.objects.filter(
            description__startswith='Customer follow-up sent').count(), 1)

    def test_customer_override(self):
        self.policy.enabled = False
        self.policy.save()
        self._ticket(days=3)
        self._run()
        self.assertEqual(len(mail.outbox), 0)
        ClientPSASettings.objects.update_or_create(
            organization=self.org, defaults={'followup_override': 'on'})
        self._run()
        self.assertEqual(len(mail.outbox), 1)
        self.policy.enabled = True
        self.policy.save()
        ClientPSASettings.objects.filter(organization=self.org).update(followup_override='off')
        mail.outbox = []
        self._ticket(days=3)
        self._run()
        self.assertEqual(len(mail.outbox), 0)

    def test_business_days_skip_weekends(self):
        from datetime import datetime, timezone as tz
        fri = datetime(2026, 11, 20, 9, 0, tzinfo=tz.utc)  # a Friday
        self.assertEqual(followup.add_days(fri, 3, business=True).weekday(), 2)  # Wednesday
        self.assertEqual(followup.add_days(fri, 3).weekday(), 0)  # Monday

    def test_ticket_page_shows_cycle(self):
        t = self._ticket(days=1)
        c = self._login(self.tech)
        r = c.get(reverse('psa:ticket_detail', args=[t.ticket_number]))
        self.assertContains(r, 'Closes automatically')
        self.assertContains(r, 'Pause follow-up')

    def test_settings_save_audited(self):
        su = User.objects.create_superuser('fu_root', 'root@msp.test', 'pw-fu-123')
        c = Client()
        c.force_login(su)
        r = c.post(reverse('psa:settings'), {
            'action': 'save_followup', 'followup_enabled': 'on',
            'followup_first_after_days': '4', 'followup_second_after_days': '0',
            'followup_close_after_days': '9', 'followup_message': 'Hi {ticket_number}',
            'closure_message': ''})
        self.assertEqual(r.status_code, 302)
        p = FollowUpPolicy.get()
        self.assertEqual((p.enabled, p.first_after_days, p.second_after_days, p.close_after_days),
                         (True, 4, 0, 9))
        self.assertTrue(AuditLog.objects.filter(object_type='psa.FollowUpPolicy').exists())
