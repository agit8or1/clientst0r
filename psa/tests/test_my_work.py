"""
My Work (/psa/my-work/) — the technician workspace — plus the ticket list's
work-queue filters it links to, the email poller's customer-reply bookkeeping,
and the dashboard schedule's ticket links.

Queue definitions are in psa/my_work.py; these tests pin them.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role
from core.models import Organization
from psa.models import (
    Queue, Ticket, TicketComment, TicketPriority, TicketStatus, TicketTimeEntry,
    TicketType,
)
from psa.tests._base import (
    TEST_MIDDLEWARE, _enable_psa_for, _enable_psa_global, _make_msp_tech,
    _setup_seed,
)


def _status(slug):
    return TicketStatus.objects.get(slug=slug)


def _comment(ticket, *, author=None, internal=False, minutes_ago=0, body='x'):
    c = TicketComment.objects.create(
        ticket=ticket, author=author, body=body, is_internal=internal)
    TicketComment.objects.filter(pk=c.pk).update(
        created_at=timezone.now() - timedelta(minutes=minutes_ago))
    return c


class _MyWorkFixture:
    @classmethod
    def _build(cls):
        _setup_seed()
        _enable_psa_global()
        cls.org = Organization.objects.create(name='Work Co', slug='work-co')
        _enable_psa_for(cls.org)

        cls.tech = User.objects.create_user('mw_tech', 'tech@msp.test', 'pw-mw-123')
        cls.other_tech = User.objects.create_user('mw_other', 'other@msp.test', 'pw-mw-123')
        cls.customer = User.objects.create_user('mw_cust', 'cust@work.test', 'pw-mw-123')
        for u in (cls.tech, cls.other_tech):
            Membership.objects.create(user=u, organization=cls.org,
                                      role=Role.EDITOR, is_active=True)
        Membership.objects.create(user=cls.customer, organization=cls.org,
                                  role=Role.EDITOR, is_active=True)

        now = timezone.now()

        def ticket(subject, slug, assignee, due_hours=None, shared=True, **kw):
            t = Ticket.objects.create(
                organization=cls.org, subject=subject, client_can_view=shared,
                queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
                ticket_type=TicketType.objects.first(), status=_status(slug),
                assigned_to=assignee, **kw)
            Ticket.objects.filter(pk=t.pk).update(
                resolution_due_at=(now + timedelta(hours=due_hours)
                                   if due_hours is not None else None),
                first_response_due_at=None)
            t.refresh_from_db()
            return t

        T = cls.tech
        # Open, mine; customer spoke after our last public reply.
        cls.t_replied = ticket('MW replied', 'in-progress', T, due_hours=1)
        _comment(cls.t_replied, author=T, minutes_ago=60)
        _comment(cls.t_replied, author=cls.customer, minutes_ago=5)
        # Open, mine; we replied last -> neither waiting queue.
        cls.t_staff_last = ticket('MW staff last', 'in-progress', T, due_hours=5)
        _comment(cls.t_staff_last, author=cls.customer, minutes_ago=60)
        _comment(cls.t_staff_last, author=T, minutes_ago=5)
        # Open, mine; only an internal note -> nothing sent yet -> waiting on us.
        cls.t_internal_only = ticket('MW internal only', 'new', T, due_hours=3)
        _comment(cls.t_internal_only, author=T, internal=True, minutes_ago=5,
                 body='SECRET-INTERNAL-NOTE')
        # Customer emailed (author-less comment + last_client_response_at),
        # after an internal note: the note must not count as our reply.
        cls.t_email_reply = ticket('MW email reply', 'in-progress', T)
        _comment(cls.t_email_reply, author=T, minutes_ago=90)
        _comment(cls.t_email_reply, author=T, internal=True, minutes_ago=1)
        Ticket.objects.filter(pk=cls.t_email_reply.pk).update(
            last_client_response_at=now - timedelta(minutes=10))
        # Waiting on the client; waiting on a vendor; closed.
        cls.t_wait_client = ticket('MW waiting client', 'waiting-on-client', T, due_hours=2)
        _comment(cls.t_wait_client, author=T, minutes_ago=30)
        cls.t_wait_vendor = ticket('MW waiting vendor', 'waiting-on-vendor', T)
        cls.t_closed = ticket('MW closed', 'closed', T)
        # Somebody else's tickets.
        cls.t_other = ticket('MW other tech', 'in-progress', cls.other_tech, due_hours=1)
        cls.t_other_wait = ticket('MW other waiting', 'waiting-on-client', cls.other_tech)

        # Customer-user tickets: one shared, one not.
        cls.t_cust_shared = ticket('MW cust shared', 'in-progress', cls.customer, due_hours=4)
        _comment(cls.t_cust_shared, author=T, internal=True,
                 body='CUSTOMER-SHOULD-NOT-SEE')
        cls.t_cust_hidden = ticket('MW cust hidden', 'in-progress', cls.customer,
                                   shared=False)

    def _client(self, user):
        c = Client()
        c.force_login(user)
        s = c.session
        s['current_organization_id'] = self.org.id
        s.save()
        return c


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class MyWorkStaffTests(_MyWorkFixture, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls._build()

    def setUp(self):
        _make_msp_tech(self.tech)
        _make_msp_tech(self.other_tech)
        self.c = self._client(self.tech)

    def _get(self, **params):
        r = self.c.get(reverse('psa:my_work'), params)
        self.assertEqual(r.status_code, 200)
        return r

    @staticmethod
    def _subjects(sec):
        return [t.subject for t in sec['tickets']]

    def test_open_tickets_are_mine_non_terminal_and_sla_sorted(self):
        sec = self._get().context['open_sec']
        subjects = self._subjects(sec)
        self.assertEqual(set(subjects), {
            'MW replied', 'MW staff last', 'MW internal only', 'MW email reply',
            'MW waiting client', 'MW waiting vendor'})
        self.assertEqual(sec['count'], 6)
        # Soonest SLA first, no-SLA tickets last.
        self.assertEqual(subjects[:4], ['MW replied', 'MW waiting client',
                                        'MW internal only', 'MW staff last'])
        self.assertNotIn('MW other tech', subjects)
        self.assertNotIn('MW closed', subjects)

    def test_customer_replied(self):
        sec = self._get().context['replied_sec']
        self.assertEqual(set(self._subjects(sec)), {'MW replied', 'MW email reply'})
        self.assertEqual(sec['count'], 2)

    def test_waiting_on_us_and_on_customer(self):
        ctx = self._get().context
        self.assertEqual(set(self._subjects(ctx['waiting_us'])),
                         {'MW replied', 'MW internal only', 'MW email reply'})
        self.assertEqual(self._subjects(ctx['waiting_customer']), ['MW waiting client'])
        self.assertEqual(ctx['waiting_customer']['count'], 1)

    def test_all_tickets_toggle_for_staff(self):
        ctx = self._get(scope='all', tab='waiting_customer').context
        self.assertTrue(ctx['scope_all'])
        self.assertEqual(set(self._subjects(ctx['waiting_customer'])),
                         {'MW waiting client', 'MW other waiting'})
        self.assertIn('MW other tech', self._subjects(ctx['waiting_us']))
        self.assertNotIn('assigned=me', ctx['waiting_us']['url'])

    def test_running_timers_are_mine_and_stop_returns_here(self):
        mine = TicketTimeEntry.objects.create(
            ticket=self.t_replied, user=self.tech,
            started_at=timezone.now() - timedelta(minutes=75))
        TicketTimeEntry.objects.create(
            ticket=self.t_other, user=self.other_tech, started_at=timezone.now())
        r = self._get()
        timers = r.context['timers']
        self.assertEqual([t['entry'].pk for t in timers], [mine.pk])
        self.assertEqual(timers[0]['elapsed'], '1:15')
        stop_url = reverse('psa:timer_stop', args=[self.t_replied.ticket_number])
        self.assertContains(r, stop_url)

        r = self.c.post(stop_url, {'next': reverse('psa:my_work')})
        self.assertRedirects(r, reverse('psa:my_work'), fetch_redirect_response=False)
        mine.refresh_from_db()
        self.assertIsNotNone(mine.ended_at)

    def test_timer_stop_ignores_offsite_next(self):
        TicketTimeEntry.objects.create(
            ticket=self.t_replied, user=self.tech, started_at=timezone.now())
        stop_url = reverse('psa:timer_stop', args=[self.t_replied.ticket_number])
        r = self.c.post(stop_url, {'next': 'https://evil.example/'})
        self.assertEqual(r.url, reverse('psa:ticket_detail',
                                        args=[self.t_replied.ticket_number]))

    def test_pending_approvals(self):
        from psa.models import PSAApproval
        PSAApproval.objects.create(
            organization=self.org, kind='expense', object_type='psa.TicketExpense',
            object_id=1, object_repr='Taxi to site', requested_by=self.other_tech)
        PSAApproval.objects.create(
            organization=self.org, kind='expense', object_type='psa.TicketExpense',
            object_id=2, status='approved')
        ctx = self._get().context
        psa_q = next(q for q in ctx['approvals'] if q['key'] == 'psa')
        self.assertEqual(psa_q['count'], 1)
        self.assertEqual(psa_q['items'][0]['title'], 'Taxi to site')

    def test_appointments(self):
        from scheduling.models import ScheduledTask, TaskAssignment
        soon = ScheduledTask.objects.create(
            organization=self.org, title='Onsite at Work Co', status='pending',
            due_date=timezone.now() + timedelta(days=2))
        TaskAssignment.objects.create(task=soon, user=self.tech)
        far = ScheduledTask.objects.create(
            organization=self.org, title='Next month', status='pending',
            due_date=timezone.now() + timedelta(days=30))
        TaskAssignment.objects.create(task=far, user=self.tech)
        theirs = ScheduledTask.objects.create(
            organization=self.org, title='Not mine', status='pending',
            due_date=timezone.now() + timedelta(days=1))
        TaskAssignment.objects.create(task=theirs, user=self.other_tech)
        titles = [a['task'].title for a in self._get().context['appointments']]
        self.assertEqual(titles, ['Onsite at Work Co'])

    def test_counts_match_the_linked_ticket_lists(self):
        ctx = self._get().context
        for key in ('open_sec', 'replied_sec', 'waiting_us', 'waiting_customer'):
            sec = ctx[key]
            r = self.c.get(sec['url'])
            self.assertEqual(r.status_code, 200, sec['url'])
            self.assertEqual(len(r.context['tickets']), sec['count'], key)
            self.assertEqual({t.pk for t in r.context['tickets']},
                             {t.pk for t in sec['tickets']}, key)

    def test_nav_and_dashboard_link_to_my_work(self):
        r = self.c.get(reverse('psa:ticket_list'))
        self.assertContains(r, reverse('psa:my_work'))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TicketListWorkQueueFilterTests(_MyWorkFixture, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls._build()

    def setUp(self):
        _make_msp_tech(self.tech)
        self.c = self._client(self.tech)

    def _subjects(self, **params):
        r = self.c.get(reverse('psa:ticket_list'), params)
        self.assertEqual(r.status_code, 200)
        return {t.subject for t in r.context['tickets']}

    def test_waiting_customer_queue(self):
        self.assertEqual(self._subjects(queue='waiting_customer'),
                         {'MW waiting client', 'MW other waiting'})
        self.assertEqual(self._subjects(queue='waiting_customer', assigned='me'),
                         {'MW waiting client'})

    def test_waiting_us_queue(self):
        subjects = self._subjects(queue='waiting_us', assigned='me')
        self.assertEqual(subjects, {'MW replied', 'MW internal only', 'MW email reply'})
        self.assertNotIn('MW waiting vendor', subjects)

    def test_numeric_queue_filter_still_works_and_junk_is_ignored(self):
        q = Queue.objects.first()
        self.assertIn('MW replied', self._subjects(queue=str(q.pk)))
        self.assertIn('MW replied', self._subjects(queue='nonsense'))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class MyWorkCustomerUserTests(_MyWorkFixture, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls._build()

    def test_customer_sees_only_shared_tickets_and_no_internal_items(self):
        c = self._client(self.customer)
        r = c.get(reverse('psa:my_work'), {'scope': 'all', 'tab': 'waiting_us'})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.context['is_staff_view'])
        self.assertFalse(r.context['scope_all'], 'all-tickets toggle is staff only')
        self.assertEqual([t.subject for t in r.context['open_sec']['tickets']],
                         ['MW cust shared'])
        self.assertEqual(r.context['open_sec']['count'], 1)
        self.assertNotContains(r, 'MW cust hidden')
        self.assertNotContains(r, 'CUSTOMER-SHOULD-NOT-SEE')
        self.assertNotContains(r, 'SECRET-INTERNAL-NOTE')
        self.assertNotContains(r, 'MW other tech')
        self.assertEqual(r.context['approvals'], [])
        self.assertNotContains(r, 'id="mw-approvals"')
        # The ticket list behind the link agrees.
        r = c.get(r.context['open_sec']['url'])
        self.assertEqual([t.subject for t in r.context['tickets']], ['MW cust shared'])


class CustomerReplyBookkeepingTests(TestCase):
    """Inbound customer email replies now do what portal replies do."""

    def setUp(self):
        from psa.tests.test_phase10_email import _EmailPollerSetup
        self.helper = _EmailPollerSetup()
        _setup_seed()
        self.org, self.cfg = self.helper._make_org_with_config('mwmail')

    def _ticket(self, slug):
        from psa.models import EmailMessage
        t = self.helper._make_ticket(self.org, status=_status(slug))
        EmailMessage.objects.create(
            organization=self.org, ticket=t, ingestion_config=self.cfg,
            direction='out', message_id=f'<out-{t.pk}@msp.test>',
            from_email='help@mwmail.example.com', subject='Re: ticket')
        return t

    def _poll(self, ticket, sender='customer@example.com'):
        from psa.management.commands import psa_poll_email
        from django.core.management import call_command
        from psa.tests.test_phase10_email import _FakeIMAP, _build_raw_email
        raw = _build_raw_email(
            message_id=f'<in-{ticket.pk}-{sender}>', from_addr=sender,
            to_addr='help@mwmail.example.com', subject='Re: your ticket',
            in_reply_to=f'<out-{ticket.pk}@msp.test>', body='Here is the info.')
        original = psa_poll_email.imaplib.IMAP4_SSL
        psa_poll_email.imaplib.IMAP4_SSL = lambda *a, **kw: _FakeIMAP([(b'1', raw)])
        try:
            call_command('psa_poll_email', config_id=self.cfg.pk, verbosity=0)
        finally:
            psa_poll_email.imaplib.IMAP4_SSL = original
        ticket.refresh_from_db()

    def test_customer_email_reply_leaves_waiting_on_client(self):
        t = self._ticket('waiting-on-client')
        self.assertIsNone(t.last_client_response_at)
        self._poll(t)
        self.assertIsNotNone(t.last_client_response_at)
        self.assertEqual(t.status.slug, 'in-progress')
        self.assertTrue(t.comments.filter(is_system=True, is_internal=True).exists())

    def test_customer_email_reply_on_open_ticket_keeps_status(self):
        t = self._ticket('new')
        self._poll(t)
        self.assertIsNotNone(t.last_client_response_at)
        self.assertEqual(t.status.slug, 'new')

    def test_vendor_wait_is_not_a_customer_wait(self):
        t = self._ticket('waiting-on-vendor')
        self._poll(t)
        self.assertIsNotNone(t.last_client_response_at)
        self.assertEqual(t.status.slug, 'waiting-on-vendor')

    def test_reply_from_a_staff_address_is_not_a_customer_reply(self):
        staff = User.objects.create_user('mw_mailtech', 'tech@msp.test', 'pw')
        _make_msp_tech(staff)
        t = self._ticket('waiting-on-client')
        self._poll(t, sender='tech@msp.test')
        self.assertIsNone(t.last_client_response_at)
        self.assertEqual(t.status.slug, 'waiting-on-client')
        self.assertEqual(t.comments.filter(source='email').count(), 1)

    def test_portal_reply_uses_the_same_rule(self):
        from psa.my_work import record_customer_reply
        t = self._ticket('waiting-on-client')
        moved = record_customer_reply(t, via='portal')
        t.refresh_from_db()
        self.assertEqual(moved.slug, 'in-progress')
        self.assertIsNotNone(t.last_client_response_at)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DashboardTicketLinkTests(TestCase):
    """The dashboard schedule linked tickets by pk; the route takes the
    ticket number, so every link 404'd."""

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        cls.org = Organization.objects.create(name='Dash Co', slug='dash-co')
        _enable_psa_for(cls.org)
        cls.staff = User.objects.create_superuser('mw_dash', 'd@msp.test', 'pw-mw-123')
        cls.ticket = Ticket.objects.create(
            organization=cls.org, subject='Dash ticket',
            queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(), status=_status('in-progress'))
        Ticket.objects.filter(pk=cls.ticket.pk).update(
            resolution_due_at=timezone.now() + timedelta(days=1))

    def test_schedule_ticket_link_opens_the_ticket(self):
        from core.dashboard_panels import get_schedule
        items = [i for d in get_schedule(self.staff, self.org) for i in d.items
                 if i['kind'] == 'ticket']
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertIsInstance(item['priority'], str)
        c = Client()
        c.force_login(self.staff)
        s = c.session
        s['current_organization_id'] = self.org.id
        s.save()
        r = c.get(item['url'])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['ticket'].pk, self.ticket.pk)

        r = c.get(reverse('core:dashboard'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, item['url'])
        self.assertContains(r, reverse('psa:my_work'))

    def test_schedule_hides_unshared_tickets_from_customer_users(self):
        from core.dashboard_panels import get_schedule
        cust = User.objects.create_user('mw_dash_cust', 'c@dash.test', 'pw')
        Membership.objects.create(user=cust, organization=self.org,
                                  role=Role.EDITOR, is_active=True)
        items = [i for d in get_schedule(cust, self.org) for i in d.items
                 if i['kind'] == 'ticket']
        self.assertEqual(items, [])
