"""Ticket routing tests.

Acceptance scenarios run through the real intake paths: the email poller
(`psa_poll_email` with a fake IMAP server) and the portal ticket-creation and
reply views. Routing runs after the intake transaction commits, so intake
calls are wrapped in `captureOnCommitCallbacks(execute=True)`.
"""
import threading
from datetime import timedelta
from unittest import mock, skipIf

from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.management import call_command
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role, RoleTemplate
from core.models import Organization
from psa.models import (
    ClientPSASettings, EmailIngestionConfig, Queue, Ticket, TicketComment, TicketPriority,
    TicketStatus, TicketType, WorkflowRule,
)
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_global, _make_msp_tech, _setup_seed
from psa.tests.test_phase10_email import _build_raw_email, _FakeIMAP

from . import engine, service
from .models import (
    CustomerRoutingSettings, OnCallShift, RoundRobinPointer, RoutingDecision, RoutingRule,
    RoutingSettings,
)
from .views import publish


def _tech(username, *groups, skills=()):
    u = User.objects.create_user(username, f'{username}@msp.example', 'pw')
    _make_msp_tech(u)
    for g in groups:
        g.user_set.add(u)
    from resourcing.models import UserSkill
    for s in skills:
        UserSkill.objects.create(user=u, name=s, proficiency='advanced')
    return u


def _rule(name, org, priority, conditions, destination, fallback=None, active=True, user=None):
    rule = RoutingRule()
    payload = {'name': name, 'description': '', 'organization_id': org.pk if org else None,
               'priority': priority, 'conditions': conditions, 'destination': destination,
               'fallback': fallback or {'type': 'triage'}}
    from .review import summarize
    publish(rule, payload, user, summarize(org, conditions, destination, payload['fallback']))
    rule.is_active = active
    rule.save(update_fields=['is_active'])
    return rule


def _set_msp(**kw):
    msp = RoutingSettings.load()
    for k, v in kw.items():
        setattr(msp, k, v)
    msp.save()
    return msp


def _login(client, user):
    client.force_login(user)
    s = client.session
    s['2fa_prompted'] = True
    s.save()


class RoutingFixture:
    """Customer A (routing rules), Customer B (routing Off), technicians."""

    @classmethod
    def build(cls):
        _setup_seed()
        _enable_psa_global()
        cls.admin = User.objects.create_superuser('route-admin', 'admin@msp.example', 'pw')
        cls.helpdesk = Group.objects.create(name='Helpdesk')
        cls.network = Group.objects.create(name='Network')
        cls.tech1 = _tech('tech1', cls.helpdesk)
        cls.tech2 = _tech('tech2', cls.helpdesk)
        cls.tech3 = _tech('tech3', cls.helpdesk)
        cls.outsider = _tech('outsider', cls.helpdesk)  # not authorized for Customer A
        cls.net_on_call = _tech('net-oncall', cls.network, skills=['Networking'])
        cls.net_off = _tech('net-off', cls.network, skills=['Networking'])

        cls.cust_a = Organization.objects.create(name='Customer A', slug='cust-a')
        cls.cust_b = Organization.objects.create(name='Customer B', slug='cust-b')
        for org in (cls.cust_a, cls.cust_b):
            ClientPSASettings.objects.create(organization=org, portal_enabled=True)
        cls.portal_a = User.objects.create_user('portal-a', 'jane@cust-a.example', 'pw')
        Membership.objects.create(user=cls.portal_a, organization=cls.cust_a, role=Role.READONLY, is_active=True)
        cls.portal_b = User.objects.create_user('portal-b', 'bob@cust-b.example', 'pw')
        Membership.objects.create(user=cls.portal_b, organization=cls.cust_b, role=Role.READONLY, is_active=True)

        cls.escalations = Queue.objects.get(name='Escalations')
        cls.p1 = TicketPriority.objects.get(code='P1')
        a = CustomerRoutingSettings.objects.create(organization=cls.cust_a, mode='inherit',
                                                   restrict_technicians=True)
        a.authorized_technicians.set([cls.tech1, cls.tech2, cls.tech3, cls.net_on_call, cls.net_off])
        CustomerRoutingSettings.objects.create(organization=cls.cust_b, mode='off')

        cls.outage_rule = _rule(
            'A after-hours P1 network outage', cls.cust_a, 10,
            {'priorities': ['P1'], 'hours': 'after', 'keywords_any': ['outage']},
            {'type': 'skill_match', 'skills': ['Networking'], 'team_id': cls.network.pk,
             'require_on_call': True, 'require_available': True},
            {'type': 'queue', 'queue_id': cls.escalations.pk})
        cls.rr_rule = _rule(
            'A portal and email round-robin', cls.cust_a, 50,
            {'sources': ['portal', 'email']},
            {'type': 'round_robin', 'team_id': cls.helpdesk.pk, 'require_available': True},
            {'type': 'triage'})

    def make_shift(self, user=None):
        now = timezone.now()
        return OnCallShift.objects.create(user=user or self.net_on_call, team=self.network,
                                          starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=8))

    def make_email_config(self, org, priority=None):
        cfg = EmailIngestionConfig.objects.create(
            organization=org, name=f'{org.slug}-helpdesk', imap_host='imap.example.com',
            username=f'help@{org.slug}.example',
            default_queue=Queue.objects.get(name='Helpdesk') if Queue.objects.filter(name='Helpdesk').exists()
            else Queue.objects.first(),
            default_priority=priority or TicketPriority.objects.order_by('-sort_order').first(),
            default_type=TicketType.objects.first())
        cfg.set_password('pw')
        cfg.save()
        return cfg

    def poll(self, cfg, *raws):
        from psa.management.commands import psa_poll_email
        fake = _FakeIMAP([(str(i + 1).encode(), raw) for i, raw in enumerate(raws)])
        original = psa_poll_email.imaplib.IMAP4_SSL
        psa_poll_email.imaplib.IMAP4_SSL = lambda *a, **kw: fake
        try:
            with self.captureOnCommitCallbacks(execute=True):
                call_command('psa_poll_email', config_id=cfg.pk, verbosity=0)
        finally:
            psa_poll_email.imaplib.IMAP4_SSL = original

    def portal_ticket(self, user, subject='Printer is jammed', description='Paper stuck'):
        c = Client()
        _login(c, user)
        with self.captureOnCommitCallbacks(execute=True):
            resp = c.post(reverse('portal:ticket_create'), {'subject': subject, 'description': description})
        self.assertEqual(resp.status_code, 302, getattr(resp, 'content', b'')[:300])
        return Ticket.objects.filter(subject=subject).latest('pk')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DefaultsTests(TestCase):
    """Fresh installs and upgrades start Off; nothing routes."""

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        cls.org = Organization.objects.create(name='Plain Co', slug='plain-co')
        ClientPSASettings.objects.create(organization=cls.org, portal_enabled=True)
        cls.portal = User.objects.create_user('plain-portal', 'p@plain.example', 'pw')
        Membership.objects.create(user=cls.portal, organization=cls.org, role=Role.READONLY, is_active=True)
        cls.tech = _tech('plain-tech')

    def test_no_settings_row_means_off(self):
        self.assertFalse(RoutingSettings.objects.exists())
        self.assertEqual(RoutingSettings.load().mode, 'off')
        self.assertEqual(RoutingSettings._meta.get_field('mode').default, 'off')
        self.assertEqual(CustomerRoutingSettings._meta.get_field('mode').default, 'inherit')
        self.assertEqual(engine.effective_mode(self.org), ('off', 'msp'))

    def test_off_portal_ticket_is_legacy(self):
        # Even with an active matching rule, Off means nothing routes.
        _rule('everything', None, 1, {}, {'type': 'least_loaded'})
        c = Client()
        _login(c, self.portal)
        with self.captureOnCommitCallbacks(execute=True):
            c.post(reverse('portal:ticket_create'), {'subject': 'Off test', 'description': 'x'})
        t = Ticket.objects.get(subject='Off test')
        self.assertIsNone(t.assigned_to_id)
        self.assertFalse(RoutingDecision.objects.exists())
        self.assertFalse(RoundRobinPointer.objects.exists())

    def test_role_flags_default_off(self):
        for name in ('routing_manage_rules', 'routing_test', 'routing_override'):
            self.assertFalse(RoleTemplate._meta.get_field(name).default)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AcceptanceTests(RoutingFixture, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.build()

    def setUp(self):
        # Automatic, always after hours (no business days) so the outage rule's
        # time condition is deterministic.
        _set_msp(mode='auto', business_days=[])

    # -- Customer A: round-robin for normal portal requests ------------------

    def test_portal_round_robin_in_turn(self):
        tickets = [self.portal_ticket(self.portal_a, subject=f'Normal request {i}') for i in range(4)]
        got = [t.assigned_to for t in Ticket.objects.filter(pk__in=[t.pk for t in tickets]).order_by('pk')]
        self.assertEqual(got, [self.tech1, self.tech2, self.tech3, self.tech1])
        d = RoutingDecision.objects.filter(ticket=tickets[0]).get()
        self.assertEqual(d.status, 'applied')
        self.assertEqual(d.rule, self.rr_rule)
        self.assertEqual(d.rule_version, self.rr_rule.current_version)
        self.assertEqual(d.trigger, 'created')
        self.assertIsNone(d.previous_assignee_id)
        self.assertEqual(d.new_assignee, self.tech1)
        self.assertIn('round-robin', d.reason)
        # The not-authorized technician is in the team but is skipped, with a reason.
        self.assertIn({'user_id': self.outsider.pk, 'username': 'outsider',
                       'reason': "not on this customer's authorized technician list"},
                      d.skipped_candidates)

    def test_unauthorized_technician_never_selected(self):
        for i in range(8):
            self.portal_ticket(self.portal_a, subject=f'Spread {i}')
        self.assertFalse(Ticket.objects.filter(assigned_to=self.outsider).exists())
        # A technician whose global role has no ticket access is not a candidate either.
        nope = RoleTemplate.objects.create(name='No tickets', tickets_view=False)
        self.outsider.profile.global_role_template = nope
        self.outsider.profile.save()
        cust = CustomerRoutingSettings.objects.get(organization=self.cust_a)
        cust.authorized_technicians.add(self.outsider)
        eligible, skipped = engine.candidates(
            Ticket(organization=self.cust_a), {'type': 'least_loaded', 'team_id': self.helpdesk.pk},
            timezone.now(), RoutingSettings.load(), cust)
        self.assertNotIn(self.outsider, eligible)
        self.assertIn('not authorized for this customer', next(
            s['reason'] for s in skipped if s['user_id'] == self.outsider.pk))
        # Customer users never enter the pool at all.
        self.assertNotIn(self.portal_a, eligible)
        self.assertNotIn(self.portal_a.pk, [s['user_id'] for s in skipped])

    # -- Customer A: after-hours P1 network outage → on-call network tech --------

    def test_after_hours_p1_outage_email_goes_to_on_call_network_tech(self):
        self.make_shift()
        cfg = self.make_email_config(self.cust_a, priority=self.p1)
        self.poll(cfg, _build_raw_email(message_id='<outage-1@cust-a.example>',
                                        from_addr='ops@cust-a.example', to_addr='help@cust-a.example',
                                        subject='Network outage at HQ', body='Everything is down'))
        t = Ticket.objects.get(subject='Network outage at HQ')
        self.assertEqual(t.source, 'email')
        self.assertEqual(t.assigned_to, self.net_on_call)
        d = t.routing_decisions.get()
        self.assertEqual(d.rule, self.outage_rule)
        reasons = {s['username']: s['reason'] for s in d.skipped_candidates}
        self.assertEqual(reasons['net-off'], 'not on call now')
        self.assertIn('tech1', reasons)  # not in the Network team / no skill

    def test_outage_with_nobody_on_call_falls_back_to_escalations(self):
        cfg = self.make_email_config(self.cust_a, priority=self.p1)
        self.poll(cfg, _build_raw_email(message_id='<outage-2@cust-a.example>',
                                        from_addr='ops@cust-a.example', to_addr='help@cust-a.example',
                                        subject='Router outage', body='Down'))
        t = Ticket.objects.get(subject='Router outage')
        self.assertIsNone(t.assigned_to_id)
        self.assertEqual(t.queue, self.escalations)
        d = t.routing_decisions.get()
        self.assertEqual(d.status, 'fallback')
        self.assertIn('nobody qualifies', d.reason)
        self.assertIn('Escalations', d.reason)
        # Visible in triage.
        c = Client()
        _login(c, self.tech1)
        resp = c.get(reverse('ticket_routing:triage'))
        self.assertContains(resp, t.ticket_number)

    # -- Customer B: routing Off → unchanged legacy behavior ---------------------

    def test_customer_b_off_is_legacy(self):
        legacy = WorkflowRule.objects.create(
            organization=self.cust_b, name='B legacy assign', trigger='ticket_created',
            conditions={}, actions=[{'type': 'assign_to', 'username': 'tech2'}])
        t = self.portal_ticket(self.portal_b, subject='B request')
        self.assertEqual(t.assigned_to, self.tech2)  # the legacy workflow rule, untouched
        self.assertFalse(RoutingDecision.objects.filter(ticket=t).exists())
        legacy.delete()
        t2 = self.portal_ticket(self.portal_b, subject='B request 2')
        self.assertIsNone(t2.assigned_to_id)
        self.assertEqual(t2.queue_id, Queue.objects.filter(is_active=True).first().pk)
        self.assertFalse(RoutingDecision.objects.filter(ticket=t2).exists())

    def test_legacy_workflow_assignment_is_preserved_when_on(self):
        WorkflowRule.objects.create(
            organization=self.cust_a, name='A legacy assign', trigger='ticket_created',
            conditions={}, actions=[{'type': 'assign_to', 'username': 'tech3'}])
        t = self.portal_ticket(self.portal_a, subject='Legacy first')
        self.assertEqual(t.assigned_to, self.tech3)
        d = t.routing_decisions.get()
        self.assertEqual(d.status, 'skipped')
        self.assertIn('Already assigned', d.reason)

    # -- Duplicate email: one ticket, one assignment, one notification -----------

    def test_duplicate_message_id_one_ticket_one_assignment_one_notification(self):
        cfg = self.make_email_config(self.cust_a)
        raw = _build_raw_email(message_id='<dup-1@cust-a.example>', from_addr='jane@cust-a.example',
                               to_addr='help@cust-a.example', subject='Need a new mouse')
        with mock.patch('psa.notifications.notify_tech_assigned') as notify:
            self.poll(cfg, raw, raw)          # same message twice in one poll
            self.poll(cfg, raw)               # and again on the next poll
        self.assertEqual(Ticket.objects.filter(subject='Need a new mouse').count(), 1)
        t = Ticket.objects.get(subject='Need a new mouse')
        self.assertEqual(RoutingDecision.objects.filter(ticket=t).count(), 1)
        self.assertEqual(t.assigned_to, self.tech1)
        self.assertEqual(notify.call_count, 1)
        self.assertEqual(TicketComment.objects.filter(ticket=t).count(), 0)
        self.assertEqual(RoundRobinPointer.objects.get(key=f'rule:{self.rr_rule.pk}').counter, 1)

    def test_repeated_trigger_is_idempotent(self):
        t = self.portal_ticket(self.portal_a, subject='Once only')
        self.assertIsNone(service.route(t.pk, 'created', 'created'))
        self.assertEqual(RoutingDecision.objects.filter(ticket=t).count(), 1)

    # -- Customer reply after a dispatcher's manual assignment → preserved -------

    def test_reply_after_manual_assignment_keeps_assignment(self):
        _set_msp(mode='auto', business_days=[], reroute_on_reply=True)
        t = self.portal_ticket(self.portal_a, subject='Please call me')
        self.assertEqual(t.assigned_to, self.tech1)
        # Dispatcher drags it to tech3 on the dispatch board (real endpoint).
        c = Client()
        _login(c, self.admin)
        resp = c.post(reverse('psa:dispatch_assign'),
                      {'ticket_number': t.ticket_number, 'assignee': str(self.tech3.pk)})
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        override = t.routing_decisions.get(status='override')
        self.assertEqual(override.previous_assignee, self.tech1)
        self.assertEqual(override.new_assignee, self.tech3)
        # Customer replies in the portal.
        pc = Client()
        _login(pc, self.portal_a)
        with self.captureOnCommitCallbacks(execute=True):
            pc.post(reverse('portal:post_reply', args=[t.ticket_number]), {'body': 'Any update?'})
        t.refresh_from_db()
        self.assertEqual(t.assigned_to, self.tech3)
        reply = t.routing_decisions.get(trigger='reply')
        self.assertEqual(reply.status, 'skipped')
        self.assertIn('manual assignments are preserved', reply.reason)

    def test_email_reply_reroutes_only_when_enabled_and_routed(self):
        _set_msp(mode='auto', business_days=[], reroute_on_reply=True)
        cfg = self.make_email_config(self.cust_a)
        self.poll(cfg, _build_raw_email(message_id='<thread-1@cust-a.example>', from_addr='jane@cust-a.example',
                                        to_addr='help@cust-a.example', subject='VPN slow'))
        t = Ticket.objects.get(subject='VPN slow')
        first = t.assigned_to
        self.poll(cfg, _build_raw_email(message_id='<thread-2@cust-a.example>', from_addr='jane@cust-a.example',
                                        to_addr='help@cust-a.example', subject='Re: VPN slow',
                                        in_reply_to='<thread-1@cust-a.example>'))
        t.refresh_from_db()
        # Routing set it, the assignee still qualifies → stays.
        self.assertEqual(t.assigned_to, first)
        self.assertIn('still qualifies', t.routing_decisions.get(trigger='reply').reason)

    # -- Invariants ------------------------------------------------------------

    def test_routing_never_changes_customer_or_sla(self):
        due1, due2 = timezone.now() + timedelta(hours=4), timezone.now() + timedelta(days=2)
        status = TicketStatus.objects.get(slug='new')
        with self.captureOnCommitCallbacks(execute=True):
            t = Ticket.objects.create(
                organization=self.cust_a, subject='SLA check', source='portal', status=status,
                priority=self.p1, queue=Queue.objects.first(), ticket_type=TicketType.objects.first(),
                first_response_due_at=due1, resolution_due_at=due2, sla_paused_minutes=7)
        t.refresh_from_db()
        self.assertEqual(t.assigned_to, self.tech1)
        self.assertEqual(t.organization, self.cust_a)
        self.assertEqual((t.first_response_due_at, t.resolution_due_at, t.sla_paused_minutes), (due1, due2, 7))

    def test_unverified_customer_is_not_routed(self):
        from assets.models import Contact
        Contact.objects.create(organization=self.cust_b, first_name='Bob', last_name='B',
                               email='bob@cust-b.example')
        status = TicketStatus.objects.get(slug='new')
        with self.captureOnCommitCallbacks(execute=True):
            t = Ticket.objects.create(
                organization=self.cust_a, subject='Who am I', source='email', status=status,
                requester_email='bob@cust-b.example', priority=self.p1,
                queue=Queue.objects.first(), ticket_type=TicketType.objects.first())
        t.refresh_from_db()
        self.assertIsNone(t.assigned_to_id)
        self.assertEqual(t.organization, self.cust_a)
        d = t.routing_decisions.get()
        self.assertEqual(d.status, 'fallback')
        self.assertIn('Customer not verified', d.reason)

    def test_publishing_a_rule_never_reassigns_existing_tickets(self):
        _set_msp(mode='off')
        existing = self.portal_ticket(self.portal_a, subject='Before the rule')
        _set_msp(mode='auto', business_days=[])
        c = Client()
        _login(c, self.admin)
        post = {'step': 'review', 'name': 'Everything to tech2', 'organization': str(self.cust_a.pk),
                'priority': '1', 'destination_type': 'technician', 'dest_user_id': str(self.tech2.pk),
                'dest_require_available': 'on', 'fallback_type': 'triage', 'activate': 'on'}
        review = c.post(reverse('ticket_routing:rule_new'), post)
        self.assertContains(review, 'For tickets from Customer A: assign it to tech2')
        payload = review.context['payload_json']
        resp = c.post(reverse('ticket_routing:rule_new'), {'step': 'confirm', 'payload': payload})
        self.assertEqual(resp.status_code, 302)
        rule = RoutingRule.objects.get(name='Everything to tech2')
        self.assertTrue(rule.is_active)
        self.assertEqual(rule.current_version.number, 1)
        existing.refresh_from_db()
        self.assertIsNone(existing.assigned_to_id)
        self.assertFalse(RoutingDecision.objects.filter(ticket=existing).exists())
        # New tickets use it (customer rule, priority 1 → evaluated first).
        t = self.portal_ticket(self.portal_a, subject='After the rule')
        self.assertEqual(t.assigned_to, self.tech2)
        self.assertEqual(t.routing_decisions.get().rule_version, rule.current_version)

    def test_sla_threshold_reroute_once(self):
        _set_msp(mode='auto', business_days=[], reroute_on_sla=True, sla_reroute_pct=50,
                 preserve_manual_assignment=True)
        t = self.portal_ticket(self.portal_a, subject='Slow burn')
        # Routed to tech1; make tech1 unavailable (leave) and push the SLA past 50%.
        from resourcing.models import LeaveRequest
        # Leave is checked in the technician's own time zone, which differs
        # from the server's local date for part of every day.
        from resourcing.shifts import user_tz
        today = timezone.now().astimezone(user_tz(self.tech1)).date()
        LeaveRequest.objects.create(user=self.tech1, leave_type='vacation', start_date=today,
                                    end_date=today, status='approved')
        Ticket.objects.filter(pk=t.pk).update(created_at=timezone.now() - timedelta(hours=10),
                                              resolution_due_at=timezone.now() + timedelta(hours=1))
        call_command('psa_sla_workflow_tick', verbosity=0)
        call_command('psa_sla_workflow_tick', verbosity=0)
        t.refresh_from_db()
        self.assertNotEqual(t.assigned_to, self.tech1)
        self.assertEqual(t.routing_decisions.filter(trigger='sla').count(), 1)

    def test_reopen_reroutes_when_enabled(self):
        _set_msp(mode='auto', business_days=[], reroute_on_reopen=True)
        t = self.portal_ticket(self.portal_a, subject='Comes back')
        closed = TicketStatus.objects.filter(is_terminal=True, requires_signoff=False).first()
        reopen = TicketStatus.objects.get(slug='new')
        t.status = closed
        t.save()
        t.assigned_to = None
        t.status = reopen
        with self.captureOnCommitCallbacks(execute=True):
            t.save()
        t.refresh_from_db()
        self.assertTrue(t.routing_decisions.filter(trigger='reopen').exists())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SuggestAndPermissionTests(RoutingFixture, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.build()
        cls.dispatcher = _tech('dispatcher')
        role = RoleTemplate.objects.create(name='Dispatcher', routing_override=True, tickets_view=True)
        cls.dispatcher.profile.global_role_template = role
        cls.dispatcher.profile.save()
        cls.tester = _tech('tester')
        trole = RoleTemplate.objects.create(name='Tester', routing_test=True, tickets_view=True)
        cls.tester.profile.global_role_template = trole
        cls.tester.profile.save()

    def setUp(self):
        _set_msp(mode='suggest', business_days=[])

    def test_suggest_only_changes_nothing_until_accepted(self):
        with mock.patch('psa.notifications.notify_tech_assigned') as notify:
            t = self.portal_ticket(self.portal_a, subject='Suggest me')
        t.refresh_from_db()
        self.assertIsNone(t.assigned_to_id)
        self.assertEqual(notify.call_count, 0)
        d = t.routing_decisions.get()
        self.assertEqual((d.status, d.new_assignee), ('suggested', self.tech1))
        # Technician without routing_override cannot accept.
        c = Client()
        _login(c, self.tech2)
        self.assertEqual(c.post(reverse('ticket_routing:decide', args=[d.pk]),
                                {'decision': 'accept'}).status_code, 403)
        # Ticket page shows the suggestion to staff only.
        _login(c, self.dispatcher)
        page = c.get(reverse('psa:ticket_detail', args=[t.ticket_number]))
        self.assertContains(page, 'routing-history')
        resp = c.post(reverse('ticket_routing:decide', args=[d.pk]), {'decision': 'accept'})
        self.assertEqual(resp.status_code, 302)
        t.refresh_from_db()
        d.refresh_from_db()
        self.assertEqual(t.assigned_to, self.tech1)
        self.assertEqual((d.status, d.decided_by), ('accepted', self.dispatcher))
        # Accepting twice does nothing more.
        c.post(reverse('ticket_routing:decide', args=[d.pk]), {'decision': 'accept'})
        self.assertEqual(RoundRobinPointer.objects.get(key=f'rule:{self.rr_rule.pk}').counter, 1)

    def test_reject(self):
        t = self.portal_ticket(self.portal_a, subject='No thanks')
        d = t.routing_decisions.get()
        c = Client()
        _login(c, self.dispatcher)
        c.post(reverse('ticket_routing:decide', args=[d.pk]), {'decision': 'reject'})
        d.refresh_from_db()
        t.refresh_from_db()
        self.assertEqual(d.status, 'rejected')
        self.assertIsNone(t.assigned_to_id)

    def test_routing_history_never_in_portal(self):
        t = self.portal_ticket(self.portal_a, subject='Portal view')
        c = Client()
        _login(c, self.portal_a)
        resp = c.get(reverse('portal:ticket_detail', args=[t.ticket_number]))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'routing-history')
        self.assertNotContains(resp, 'round-robin')
        self.assertNotContains(resp, 'Suggested')

    def test_permissions_are_separate(self):
        c = Client()
        _login(c, self.tester)
        self.assertEqual(c.get(reverse('ticket_routing:test')).status_code, 200)
        self.assertEqual(c.get(reverse('ticket_routing:overview')).status_code, 403)
        _login(c, self.dispatcher)
        self.assertEqual(c.get(reverse('ticket_routing:test')).status_code, 403)
        _login(c, self.tech1)
        self.assertEqual(c.get(reverse('ticket_routing:overview')).status_code, 403)
        # A customer user holding every routing flag still gets nothing.
        role = RoleTemplate.objects.create(name='Sneaky', routing_manage_rules=True, routing_test=True,
                                           routing_override=True)
        m = Membership.objects.get(user=self.portal_a)
        m.role_template = role
        m.save()
        _login(c, self.portal_a)
        # Customer portal users are sent to the portal before any routing page.
        for name in ('ticket_routing:overview', 'ticket_routing:test'):
            r = c.get(reverse(name))
            self.assertIn(r.status_code, (302, 403))
            if r.status_code == 302:
                self.assertEqual(r['Location'], '/portal/')
        _login(c, self.admin)
        self.assertEqual(c.get(reverse('ticket_routing:overview')).status_code, 200)

    def test_test_routing_changes_nothing_and_sends_nothing(self):
        _set_msp(mode='auto', business_days=[])
        self.make_shift()
        existing = Ticket.objects.create(
            organization=self.cust_a, subject='Historical outage', description='core switch',
            source='email', status=TicketStatus.objects.get(slug='new'), priority=self.p1,
            queue=Queue.objects.first(), ticket_type=TicketType.objects.first())
        # (created outside captureOnCommitCallbacks: never routed)
        before = {
            'tickets': list(Ticket.objects.values_list('pk', 'assigned_to_id', 'queue_id', 'updated_at')),
            'decisions': RoutingDecision.objects.count(),
            'pointers': list(RoundRobinPointer.objects.values_list('key', 'counter')),
            'comments': TicketComment.objects.count(),
        }
        mail.outbox = []
        c = Client()
        _login(c, self.tester)
        with mock.patch('psa.notifications.notify_tech_assigned') as notify, \
                self.captureOnCommitCallbacks(execute=True) as callbacks:
            resp = c.get(reverse('ticket_routing:test'), {'ticket_number': existing.ticket_number})
            sample = c.get(reverse('ticket_routing:test'), {
                'organization': self.cust_a.pk, 'source': 'portal', 'priority': 'P3',
                'subject': 'printer'})
        self.assertContains(resp, 'A after-hours P1 network outage')
        self.assertContains(resp, 'net-oncall')
        self.assertContains(resp, 'not on call now')       # skipped candidate + reason
        self.assertContains(resp, 'No data changed')
        self.assertContains(sample, 'A portal and email round-robin')
        self.assertContains(sample, 'tech1')
        self.assertEqual(callbacks, [])
        self.assertEqual(notify.call_count, 0)
        self.assertEqual(mail.outbox, [])
        after = {
            'tickets': list(Ticket.objects.values_list('pk', 'assigned_to_id', 'queue_id', 'updated_at')),
            'decisions': RoutingDecision.objects.count(),
            'pointers': list(RoundRobinPointer.objects.values_list('key', 'counter')),
            'comments': TicketComment.objects.count(),
        }
        self.assertEqual(before, after)

    def test_rule_review_flags_conflicts_and_blocks_activation(self):
        c = Client()
        _login(c, self.admin)
        post = {'step': 'review', 'name': 'Bad tech', 'organization': str(self.cust_a.pk), 'priority': '50',
                'destination_type': 'technician', 'dest_user_id': str(self.outsider.pk),
                'fallback_type': 'triage', 'activate': 'on', 'sources': ['portal']}
        resp = c.post(reverse('ticket_routing:rule_new'), post)
        self.assertContains(resp, 'outsider is not on this customer')
        self.assertContains(resp, 'same scope and priority')     # same priority as the round-robin rule
        self.assertContains(resp, 'never win')                    # shadowed by the earlier rule
        c.post(reverse('ticket_routing:rule_new'), {'step': 'confirm', 'payload': resp.context['payload_json']})
        rule = RoutingRule.objects.get(name='Bad tech')
        self.assertFalse(rule.is_active)
        resp = c.post(reverse('ticket_routing:rule_toggle', args=[rule.pk]), {'activate': '1'})
        rule.refresh_from_db()
        self.assertFalse(rule.is_active)

    def test_editing_creates_a_new_version(self):
        c = Client()
        _login(c, self.admin)
        post = {'step': 'review', 'name': 'A portal and email round-robin', 'organization': str(self.cust_a.pk),
                'priority': '60', 'destination_type': 'least_loaded', 'dest_require_available': 'on',
                'fallback_type': 'triage', 'activate': 'on', 'sources': ['portal']}
        resp = c.post(reverse('ticket_routing:rule_edit', args=[self.rr_rule.pk]), post)
        c.post(reverse('ticket_routing:rule_edit', args=[self.rr_rule.pk]),
               {'step': 'confirm', 'payload': resp.context['payload_json']})
        self.rr_rule.refresh_from_db()
        self.assertEqual(self.rr_rule.current_version.number, 2)
        self.assertEqual(self.rr_rule.versions.count(), 2)
        self.assertEqual(self.rr_rule.versions.get(number=1).destination['type'], 'round_robin')

    def test_every_page_renders(self):
        self.make_shift()
        c = Client()
        _login(c, self.admin)
        for url in (reverse('ticket_routing:overview'), reverse('ticket_routing:rule_new'),
                    reverse('ticket_routing:rule_detail', args=[self.outage_rule.pk]),
                    reverse('ticket_routing:rule_edit', args=[self.outage_rule.pk]),
                    reverse('ticket_routing:customer', args=[self.cust_a.pk]),
                    reverse('ticket_routing:on_call'), reverse('ticket_routing:test'),
                    reverse('ticket_routing:triage'), reverse('psa:workflow_rule_list')):
            self.assertEqual(c.get(url).status_code, 200, url)
        edit = c.get(reverse('ticket_routing:rule_edit', args=[self.outage_rule.pk]))
        self.assertContains(edit, 'value="outage"', html=False)
        detail = c.get(reverse('ticket_routing:rule_detail', args=[self.outage_rule.pk]))
        self.assertContains(detail, 'outside business hours')
        # Adding and removing an on-call shift.
        resp = c.post(reverse('ticket_routing:on_call'), {
            'user': self.tech1.pk, 'team': '', 'starts_at': '2030-01-01T08:00', 'ends_at': '2030-01-01T18:00'})
        self.assertEqual(resp.status_code, 302)
        shift = OnCallShift.objects.get(user=self.tech1)
        c.post(reverse('ticket_routing:on_call'), {'delete': shift.pk})
        self.assertFalse(OnCallShift.objects.filter(pk=shift.pk).exists())
        # Settings save keeps business hours valid.
        resp = c.post(reverse('ticket_routing:overview'), {
            'mode': 'auto', 'business_days': ['0', '1'], 'business_start': '09:00', 'business_end': '17:30',
            'sla_reroute_pct': '80', 'max_reroutes': '3', 'preserve_manual_assignment': 'on'})
        self.assertEqual(resp.status_code, 302)
        msp = RoutingSettings.load()
        self.assertEqual((msp.mode, msp.business_days, msp.max_reroutes), ('auto', [0, 1], 3))

    def test_psa_settings_card_and_quick_mode(self):
        c = Client()
        _login(c, self.admin)
        resp = c.get(reverse('psa:settings'))
        self.assertContains(resp, 'ticket-routing-card')
        c.post(reverse('ticket_routing:quick_mode'), {'mode': 'off', 'next': reverse('psa:settings')})
        self.assertEqual(RoutingSettings.load().mode, 'off')
        c.post(reverse('ticket_routing:customer', args=[self.cust_b.pk]), {'mode': 'auto'})
        self.assertEqual(engine.effective_mode(self.cust_b), ('auto', 'customer'))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class LegacyWorkflowBuilderTests(TestCase):
    """The visual builder offers the existing round-robin / skill / least-loaded
    actions; raw JSON rules and existing workflows keep working."""

    @classmethod
    def setUpTestData(cls):
        _setup_seed()
        _enable_psa_global()
        cls.admin = User.objects.create_superuser('wf-admin', 'wf@x.example', 'pw')
        cls.grp = Group.objects.create(name='L1')
        cls.t1 = _tech('wf-t1', cls.grp)
        cls.t2 = _tech('wf-t2', cls.grp)
        # The legacy engine actions only consider Django is_staff accounts.
        User.objects.filter(pk__in=[cls.t1.pk, cls.t2.pk]).update(is_staff=True)
        cls.org = Organization.objects.create(name='WF Co', slug='wf-co')

    def test_builder_offers_actions(self):
        c = Client()
        _login(c, self.admin)
        resp = c.get(reverse('psa:workflow_rule_create'))
        for value in ('assign_round_robin', 'assign_skill_match', 'assign_load_balanced'):
            self.assertContains(resp, f'value="{value}"')
        self.assertContains(resp, '<option value="L1">')

    def test_raw_json_rules_round_trip_unchanged(self):
        c = Client()
        _login(c, self.admin)
        actions = ('[{"type": "assign_round_robin", "group": "L1"}, '
                   '{"type": "assign_skill_match", "skill_group": "L1"}, '
                   '{"type": "assign_load_balanced"}, {"type": "create_charge", "amount": "5"}]')
        c.post(reverse('psa:workflow_rule_create'), {
            'name': 'json rule', 'trigger': 'ticket_created', 'conditions': '{"priority__in": ["P1"]}',
            'actions': actions, 'is_active': 'on'})
        rule = WorkflowRule.objects.get(name='json rule')
        self.assertEqual(rule.actions[0], {'type': 'assign_round_robin', 'group': 'L1'})
        self.assertEqual(rule.actions[1], {'type': 'assign_skill_match', 'skill_group': 'L1'})
        self.assertEqual(rule.conditions, {'priority__in': ['P1']})
        edit = c.get(reverse('psa:workflow_rule_edit', args=[rule.pk]))
        self.assertContains(edit, 'assign_skill_match')

    def test_legacy_actions_still_assign_with_routing_off(self):
        WorkflowRule.objects.create(name='rr', trigger='ticket_created', conditions={},
                                    actions=[{'type': 'assign_load_balanced', 'group': 'L1'}])
        t = Ticket.objects.create(
            organization=self.org, subject='legacy', status=TicketStatus.objects.get(slug='new'),
            priority=TicketPriority.objects.first(), queue=Queue.objects.first(),
            ticket_type=TicketType.objects.first())
        t.refresh_from_db()
        self.assertIn(t.assigned_to, (self.t1, self.t2))
        self.assertFalse(RoutingDecision.objects.exists())


class SafetyTests(TestCase):
    def test_routing_code_has_no_remote_or_endpoint_paths(self):
        import pathlib
        root = pathlib.Path(__file__).parent
        imports = [line.strip().lower() for p in root.rglob('*.py') if not p.name.startswith('tests')
                   for line in p.read_text().splitlines()
                   if line.strip().startswith(('import ', 'from '))]
        self.assertTrue(imports)
        # The one exception: the RMM permission *decision* (rmm_permissions
        # .can), which reads permission rows and never calls an RMM. The
        # alert policy asks it before assigning an alert ticket to someone.
        allowed = {'from rmm_permissions import can'}
        self.assertTrue({i for i in imports if 'rmm_permissions' in i} <= allowed)
        for needle in ('psa_ai', 'integrations', 'rmm', 'remote', 'handoff', 'endpoint'):
            self.assertFalse([i for i in imports if needle in i and i not in allowed], needle)


def _file_db():
    name = str(connection.settings_dict.get('NAME') or '')
    return not (connection.vendor == 'sqlite' and (':memory:' in name or 'mode=memory' in name))


@skipIf(not _file_db(), 'needs a file-backed or server database for real concurrency')
@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ConcurrencyTests(RoutingFixture, TransactionTestCase):
    """Two tickets routed at the same moment by two workers."""

    # Restore migration-seeded rows (e.g. built-in access presets) after the
    # flush, so suites that run later still find them.
    serialized_rollback = True

    def setUp(self):
        type(self).build()

    def test_simultaneous_round_robin_no_double_assignment(self):
        _set_msp(mode='off')
        status = TicketStatus.objects.get(slug='new')
        tickets = [Ticket.objects.create(
            organization=self.cust_a, subject=f'Concurrent {i}', source='portal', status=status,
            priority=TicketPriority.objects.order_by('-sort_order').first(),
            queue=Queue.objects.first(), ticket_type=TicketType.objects.first()) for i in range(2)]
        _set_msp(mode='auto')
        barrier = threading.Barrier(4)
        errors = []

        def work(ticket_id):
            from django.db import connection as conn
            try:
                barrier.wait(timeout=10)
                service.route(ticket_id, 'created', 'created')
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                conn.close()

        # Each ticket delivered twice, all four at once.
        threads = [threading.Thread(target=work, args=(t.pk,)) for t in tickets for _ in range(2)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(30)
        self.assertEqual(errors, [])
        assigned = [Ticket.objects.get(pk=t.pk).assigned_to_id for t in tickets]
        self.assertEqual(sorted(assigned), sorted([self.tech1.pk, self.tech2.pk]))
        self.assertEqual(RoutingDecision.objects.filter(ticket__in=tickets).count(), 2)
        self.assertEqual(RoundRobinPointer.objects.get(key=f'rule:{self.rr_rule.pk}').counter, 2)
