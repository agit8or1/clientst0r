"""
Auto-split fragment of the legacy `psa/tests.py` (v3.17.192).
See `psa/tests/__init__.py` for the rationale.
"""
from datetime import timedelta
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, Role
from audit.models import AuditLog
from core.models import Organization, SystemSetting
from psa.feature_flags import (
    is_psa_enabled,
    is_psa_enabled_for_client,
)
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
)


class Phase3FeaturesTests(TestCase):
    """
    Phase 3: Projects, Recurring Tickets, Approvals, KB linking.

    Each feature gets a smoke test:
      * model creation works (unique-together / save() helpers fire)
      * the runner command creates a ticket and rolls next_run_at
      * the approval decide() helper updates status/decided_at
      * KB link enforces uniqueness
    """

    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='ACME Phase3', slug='acme-p3')
        self.user = User.objects.create_user('p3-tech', password='pw', email='p3@x.com')
        Membership.objects.update_or_create(
            user=self.user, organization=self.org,
            defaults={'role': Role.OWNER, 'is_active': True},
        )
        from psa.models import (
            Queue, TicketPriority, TicketType, TicketStatus,
        )
        self.queue = Queue.objects.first()
        self.priority = TicketPriority.objects.first()
        self.ttype = TicketType.objects.first()
        self.status = TicketStatus.objects.filter(slug='new').first()

    def test_project_save_generates_slug(self):
        from psa.models import Project
        p = Project.objects.create(organization=self.org, name='ACME Onboarding 2026')
        self.assertTrue(p.slug.startswith('acme-onboarding-2026'))

    def test_project_completed_sets_completed_at(self):
        from psa.models import Project
        p = Project.objects.create(organization=self.org, name='Migration')
        self.assertIsNone(p.completed_at)
        p.status = 'completed'
        p.save()
        self.assertIsNotNone(p.completed_at)

    def test_recurring_advance_next_run_monthly(self):
        from psa.models import RecurringTicketSchedule
        from datetime import datetime
        s = RecurringTicketSchedule.objects.create(
            organization=self.org,
            name='Monthly patch',
            template_subject='Patch {{org}}',
            queue=self.queue, priority=self.priority, ticket_type=self.ttype,
            frequency='monthly', interval=1,
            next_run_at=timezone.make_aware(datetime(2026, 1, 15, 9, 0)),
        )
        s.advance_next_run()
        self.assertEqual(s.next_run_at.month, 2)
        self.assertEqual(s.next_run_at.day, 15)

    def test_recurring_runner_creates_ticket(self):
        from psa.models import RecurringTicketSchedule, Ticket
        from datetime import timedelta
        s = RecurringTicketSchedule.objects.create(
            organization=self.org,
            name='Daily backup check',
            template_subject='Daily backup verification',
            template_body='Verify the backup completed.',
            queue=self.queue, priority=self.priority, ticket_type=self.ttype,
            frequency='daily', interval=1,
            next_run_at=timezone.now() - timedelta(hours=1),  # overdue
        )
        before = Ticket.objects.filter(organization=self.org).count()
        call_command('psa_run_recurring_tickets', verbosity=0)
        after = Ticket.objects.filter(organization=self.org).count()
        self.assertEqual(after, before + 1)
        # next_run_at rolled forward past now
        s.refresh_from_db()
        self.assertGreater(s.next_run_at, timezone.now())
        # The created ticket links back to the schedule
        t = Ticket.objects.filter(recurring_schedule=s).first()
        self.assertIsNotNone(t)
        self.assertEqual(t.source, 'recurring')

    def test_approval_decide_updates_status_and_decided_at(self):
        from psa.models import PSAApproval
        a = PSAApproval.objects.create(
            organization=self.org, kind='time',
            object_type='psa.TicketTimeEntry', object_id=99,
            requested_by=self.user, request_comment='Need approval',
        )
        self.assertEqual(a.status, 'pending')
        a.decide(user=self.user, approved=True, comment='LGTM')
        self.assertEqual(a.status, 'approved')
        self.assertIsNotNone(a.decided_at)
        self.assertEqual(a.decision_comment, 'LGTM')

    def test_ticket_kb_link_uniqueness(self):
        from psa.models import Ticket, TicketKBLink
        from docs.models import Document
        ticket = Ticket.objects.create(
            organization=self.org, subject='TEST',
            queue=self.queue, priority=self.priority,
            ticket_type=self.ttype, status=self.status,
        )
        article = Document.objects.create(
            title='How to reset password', body='...', is_global=True,
        )
        TicketKBLink.objects.create(ticket=ticket, article=article, linked_by=self.user)
        # Second create with same pair should fail unique_together
        with self.assertRaises(Exception):
            TicketKBLink.objects.create(ticket=ticket, article=article, linked_by=self.user)


class Phase4FeaturesTests(TestCase):
    """
    Phase 4: Customer Portal, Email Ingestion, Contracts.

    Smoke + correctness tests:
      * Contract.for_ticket returns the active contract for the client org.
      * Time entry save() increments hours_used_minutes via the contract hook.
      * Email config password round-trips encrypted (no plaintext on disk).
      * Portal queryset filters out staff-only tickets and internal comments.
    """

    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='ACME P4', slug='acme-p4')
        self.user = User.objects.create_user('p4-tech', password='pw', email='p4t@x.com')
        Membership.objects.update_or_create(
            user=self.user, organization=self.org,
            defaults={'role': Role.OWNER, 'is_active': True},
        )
        from psa.models import Queue, TicketPriority, TicketType, TicketStatus
        self.queue = Queue.objects.first()
        self.priority = TicketPriority.objects.first()
        self.ttype = TicketType.objects.first()
        self.status = TicketStatus.objects.filter(slug='new').first()

    def test_contract_for_ticket_returns_active(self):
        from psa.models import Contract, Ticket
        from datetime import date, timedelta
        c = Contract.objects.create(
            organization=self.org, client_org=self.org,
            name='Block', start_date=date.today() - timedelta(days=1),
            status='active', total_hours=10,
        )
        t = Ticket.objects.create(
            organization=self.org, subject='X',
            queue=self.queue, priority=self.priority,
            ticket_type=self.ttype, status=self.status,
        )
        self.assertEqual(Contract.for_ticket(t), c)

    def test_contract_for_ticket_skips_draft_and_expired(self):
        from psa.models import Contract, Ticket
        from datetime import date, timedelta
        Contract.objects.create(
            organization=self.org, client_org=self.org,
            name='Draft', start_date=date.today(),
            status='draft', total_hours=10,
        )
        Contract.objects.create(
            organization=self.org, client_org=self.org,
            name='Expired', start_date=date.today() - timedelta(days=400),
            end_date=date.today() - timedelta(days=10),
            status='active', total_hours=10,
        )
        t = Ticket.objects.create(
            organization=self.org, subject='X',
            queue=self.queue, priority=self.priority,
            ticket_type=self.ttype, status=self.status,
        )
        self.assertIsNone(Contract.for_ticket(t))

    def test_time_entry_save_increments_contract_hours(self):
        from psa.models import Contract, Ticket, TicketTimeEntry
        from datetime import date, timedelta
        c = Contract.objects.create(
            organization=self.org, client_org=self.org,
            name='Block', start_date=date.today() - timedelta(days=1),
            status='active', total_hours=10,
        )
        t = Ticket.objects.create(
            organization=self.org, subject='Time',
            queue=self.queue, priority=self.priority,
            ticket_type=self.ttype, status=self.status,
        )
        TicketTimeEntry.objects.create(
            ticket=t, user=self.user,
            started_at=timezone.now() - timedelta(minutes=45),
            ended_at=timezone.now(),
            duration_minutes=45,
        )
        c.refresh_from_db()
        self.assertEqual(c.hours_used_minutes, 45)
        self.assertEqual(c.hours_used, 0.75)

    def test_email_config_password_encryption(self):
        from psa.models import EmailIngestionConfig
        cfg = EmailIngestionConfig.objects.create(
            organization=self.org, name='Helpdesk',
            imap_host='imap.example.com', username='help@example.com',
            default_queue=self.queue, default_priority=self.priority,
            default_type=self.ttype,
        )
        cfg.set_password('s3cr3t-imap-pw')
        cfg.save()
        reloaded = EmailIngestionConfig.objects.get(pk=cfg.pk)
        self.assertEqual(reloaded.get_password(), 's3cr3t-imap-pw')
        self.assertNotIn('s3cr3t-imap-pw', reloaded.encrypted_password)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CustomerPortalTests(TestCase):
    """
    Portal hard rules:
      1. 404 if PSA disabled globally.
      2. 404 if user has no active membership in a portal-enabled org.
      3. Tickets queryset filters to client_can_view=True only.
      4. Internal comments don't render in detail view.
    """

    def setUp(self):
        _setup_seed()
        from psa.models import (
            ClientPSASettings, Queue, Ticket, TicketComment,
            TicketPriority, TicketType, TicketStatus,
        )
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='Portal Co', slug='portal-co')
        self.user = User.objects.create_user('portal-user', password='pw', email='pu@x.com')
        Membership.objects.update_or_create(
            user=self.user, organization=self.org,
            defaults={'role': Role.READONLY, 'is_active': True},
        )
        ClientPSASettings.objects.update_or_create(
            organization=self.org, defaults={'enabled': True, 'portal_enabled': True},
        )
        q = Queue.objects.first()
        p = TicketPriority.objects.first()
        tt = TicketType.objects.first()
        st = TicketStatus.objects.filter(slug='new').first()
        # Public ticket — should be visible
        self.public = Ticket.objects.create(
            organization=self.org, subject='Public ticket',
            queue=q, priority=p, ticket_type=tt, status=st,
            client_can_view=True, visibility='client',
        )
        TicketComment.objects.create(ticket=self.public, body='public reply', is_internal=False)
        TicketComment.objects.create(ticket=self.public, body='STAFF SECRET', is_internal=True)
        # Staff-only ticket — should be hidden
        self.private = Ticket.objects.create(
            organization=self.org, subject='Internal ticket',
            queue=q, priority=p, ticket_type=tt, status=st,
            client_can_view=False, visibility='staff',
        )

    def test_portal_404_without_membership(self):
        # Use a NEW org with portal_enabled=False, then create a rando whose
        # auto-membership lands in that non-portal org.
        from psa.models import ClientPSASettings
        no_portal_org = Organization.objects.create(name='No Portal LLC', slug='no-portal')
        ClientPSASettings.objects.create(organization=no_portal_org, portal_enabled=False)
        # Disable portal_enabled on Portal Co so the default-membership
        # signal doesn't accidentally grant the rando user access.
        ClientPSASettings.objects.filter(organization=self.org).update(portal_enabled=False)

        c = Client()
        rando = User.objects.create_user('not-a-member', password='pw', email='nm@x.com')
        c.force_login(rando)
        resp = c.get('/portal/')
        self.assertEqual(resp.status_code, 404)

    def test_portal_lists_only_client_visible_tickets(self):
        c = Client()
        c.force_login(self.user)
        resp = c.get('/portal/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(self.public.ticket_number, body)
        self.assertNotIn(self.private.ticket_number, body)

    def test_portal_detail_hides_internal_comments(self):
        c = Client()
        c.force_login(self.user)
        resp = c.get(f'/portal/t/{self.public.ticket_number}/')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('public reply', body)
        self.assertNotIn('STAFF SECRET', body)

    def test_portal_detail_404_for_staff_only_ticket(self):
        c = Client()
        c.force_login(self.user)
        resp = c.get(f'/portal/t/{self.private.ticket_number}/')
        self.assertEqual(resp.status_code, 404)

    def test_portal_post_reply_creates_public_comment(self):
        from psa.models import TicketComment
        c = Client()
        c.force_login(self.user)
        before = TicketComment.objects.filter(ticket=self.public).count()
        resp = c.post(f'/portal/t/{self.public.ticket_number}/reply/',
                      {'body': 'I tried rebooting'})
        self.assertEqual(resp.status_code, 302)
        after = TicketComment.objects.filter(ticket=self.public).count()
        self.assertEqual(after, before + 1)
        comment = TicketComment.objects.filter(ticket=self.public).order_by('-created_at').first()
        self.assertFalse(comment.is_internal)
        self.assertEqual(comment.source, 'portal')
        self.assertEqual(comment.author, self.user)

    def test_portal_create_ticket(self):
        from psa.models import Ticket
        c = Client()
        c.force_login(self.user)
        before = Ticket.objects.filter(organization=self.org).count()
        resp = c.post('/portal/new/', {
            'subject': 'My laptop is on fire',
            'description': 'Smoke is coming out',
        })
        self.assertEqual(resp.status_code, 302)
        after = Ticket.objects.filter(organization=self.org).count()
        self.assertEqual(after, before + 1)
        new_ticket = Ticket.objects.filter(organization=self.org).order_by('-created_at').first()
        self.assertEqual(new_ticket.source, 'portal')
        self.assertTrue(new_ticket.client_can_view)


class Phase5QuotesExpensesTests(TestCase):
    """Phase 5: Quotes (with line items + accept→ticket) and Expenses."""

    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='ACME P5', slug='acme-p5')
        self.client_org = Organization.objects.create(name='Client P5', slug='client-p5')
        self.user = User.objects.create_user('p5-tech', password='pw', email='p5@x.com')
        Membership.objects.update_or_create(
            user=self.user, organization=self.org,
            defaults={'role': Role.OWNER, 'is_active': True},
        )
        from psa.models import Queue, TicketPriority, TicketType, TicketStatus
        self.queue = Queue.objects.first()
        self.priority = TicketPriority.objects.first()
        self.ttype = TicketType.objects.first()
        self.status = TicketStatus.objects.filter(slug='new').first()

    def test_quote_number_auto_assigned(self):
        from psa.models import Quote
        q = Quote.objects.create(
            organization=self.org, client_org=self.client_org,
            title='Network upgrade',
        )
        from datetime import date
        self.assertTrue(q.quote_number.startswith(f'Q-{date.today().year}-'))

    def test_quote_recompute_totals_with_line_items(self):
        from psa.models import Quote, QuoteLineItem
        from decimal import Decimal
        q = Quote.objects.create(
            organization=self.org, client_org=self.client_org,
            title='Setup', tax_rate=Decimal('0.10'),
        )
        QuoteLineItem.objects.create(quote=q, description='Switch', quantity=2, unit_price=500)
        QuoteLineItem.objects.create(quote=q, description='Labor', quantity=4, unit_price=100)
        q.recompute_totals()
        self.assertEqual(q.subtotal, Decimal('1400.00'))
        self.assertEqual(q.tax_amount, Decimal('140.00'))
        self.assertEqual(q.total, Decimal('1540.00'))

    def test_quote_accept_creates_ticket(self):
        from psa.models import Quote, Ticket
        q = Quote.objects.create(
            organization=self.org, client_org=self.client_org,
            title='Project Z', description='Big project',
        )
        before = Ticket.objects.filter(organization=self.client_org).count()
        q.mark_accepted(user=self.user, create_ticket=True,
                        queue=self.queue, priority=self.priority,
                        ticket_type=self.ttype, status=self.status)
        after = Ticket.objects.filter(organization=self.client_org).count()
        self.assertEqual(after, before + 1)
        self.assertEqual(q.status, 'accepted')
        self.assertIsNotNone(q.accepted_at)
        self.assertIsNotNone(q.converted_ticket)

    def test_quote_accept_without_ticket_creation(self):
        from psa.models import Quote, Ticket
        q = Quote.objects.create(
            organization=self.org, client_org=self.client_org,
            title='No-ticket quote',
        )
        before = Ticket.objects.filter(organization=self.client_org).count()
        q.mark_accepted(user=self.user, create_ticket=False)
        after = Ticket.objects.filter(organization=self.client_org).count()
        self.assertEqual(after, before)
        self.assertIsNone(q.converted_ticket)

    def test_quote_convert_to_project_creates_tasks_per_line_item(self):
        # v3.17.213: accepting a quote with `create_project=True` spins up
        # a Project and one ProjectTask per line item.
        from psa.models import Quote, QuoteLineItem, Project, ProjectTask
        q = Quote.objects.create(
            organization=self.org, client_org=self.client_org,
            title='Server refresh', description='Replace 4 hosts',
        )
        QuoteLineItem.objects.create(quote=q, description='Procure 4 servers', quantity=4, unit_price=2500, sort_order=0)
        QuoteLineItem.objects.create(quote=q, description='Rack & cable', quantity=8, unit_price=150, sort_order=1)
        QuoteLineItem.objects.create(quote=q, description='Migrate workloads', quantity=16, unit_price=200, sort_order=2)

        q.mark_accepted(user=self.user, create_ticket=False, create_project=True)

        self.assertEqual(q.status, 'accepted')
        self.assertIsNotNone(q.converted_project)
        proj = q.converted_project
        self.assertIsInstance(proj, Project)
        self.assertEqual(proj.organization, self.org)
        self.assertEqual(proj.client_org, self.client_org)
        self.assertEqual(proj.name, 'Server refresh')
        self.assertEqual(proj.tasks.count(), 3)
        titles = list(proj.tasks.order_by('sort_order').values_list('title', flat=True))
        self.assertEqual(titles, ['Procure 4 servers', 'Rack & cable', 'Migrate workloads'])

    def test_quote_convert_to_project_is_idempotent(self):
        # Calling convert_to_project twice should not create a second project.
        from psa.models import Quote, QuoteLineItem
        q = Quote.objects.create(
            organization=self.org, client_org=self.client_org,
            title='Idempotent test',
        )
        QuoteLineItem.objects.create(quote=q, description='Item', quantity=1, unit_price=10)
        first = q.convert_to_project(user=self.user)
        second = q.convert_to_project(user=self.user)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.tasks.count(), 1)

    def test_expense_creation_and_billable_flag(self):
        from psa.models import Ticket, TicketExpense
        t = Ticket.objects.create(
            organization=self.org, subject='Onsite',
            queue=self.queue, priority=self.priority,
            ticket_type=self.ttype, status=self.status,
        )
        from datetime import date
        e = TicketExpense.objects.create(
            ticket=t, user=self.user,
            category='mileage', description='Drive to client site',
            amount=42.50, currency='USD',
            incurred_on=date.today(),
            is_billable=True, is_reimbursable=True,
        )
        self.assertEqual(t.expenses.count(), 1)
        self.assertTrue(e.is_billable)
        self.assertEqual(float(e.amount), 42.50)


class Phase6PolishTests(TestCase):
    """Phase 6 polish: ProjectTask + ticket-detail contract/expense surfaces."""

    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='ACME P6', slug='acme-p6')
        self.user = User.objects.create_user('p6', password='pw', email='p6@x.com')
        Membership.objects.update_or_create(
            user=self.user, organization=self.org,
            defaults={'role': Role.OWNER, 'is_active': True},
        )
        from psa.models import Queue, TicketPriority, TicketType, TicketStatus
        self.queue = Queue.objects.first()
        self.priority = TicketPriority.objects.first()
        self.ttype = TicketType.objects.first()
        self.status = TicketStatus.objects.filter(slug='new').first()

    def test_project_task_done_sets_completed_at(self):
        from psa.models import Project, ProjectTask
        p = Project.objects.create(organization=self.org, name='Migration')
        t = ProjectTask.objects.create(project=p, title='Plan it')
        self.assertIsNone(t.completed_at)
        t.status = 'done'
        t.save()
        self.assertIsNotNone(t.completed_at)

    def test_project_task_re_open_clears_completed_at(self):
        from psa.models import Project, ProjectTask
        p = Project.objects.create(organization=self.org, name='Reopen')
        t = ProjectTask.objects.create(project=p, title='Setup', status='done')
        self.assertIsNotNone(t.completed_at)
        t.status = 'in_progress'
        t.save()
        self.assertIsNone(t.completed_at)

    def test_project_task_milestone_flag_persists(self):
        from psa.models import Project, ProjectTask
        p = Project.objects.create(organization=self.org, name='Big project')
        t = ProjectTask.objects.create(project=p, title='Go-live', is_milestone=True)
        t.refresh_from_db()
        self.assertTrue(t.is_milestone)


class Phase7WorkflowTests(TestCase):
    """Phase 7: SLA matrix override + WorkflowRule engine + sample workflows."""

    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='ACME P7', slug='acme-p7')
        self.user = User.objects.create_user('p7', password='pw', email='p7@x.com')
        Membership.objects.update_or_create(
            user=self.user, organization=self.org,
            defaults={'role': Role.OWNER, 'is_active': True},
        )
        from psa.models import Queue, TicketPriority, TicketType, TicketStatus
        self.queue = Queue.objects.first()
        self.priority = TicketPriority.objects.filter(code='P1').first() or TicketPriority.objects.first()
        self.ttype = TicketType.objects.first()
        self.status = TicketStatus.objects.filter(slug='new').first()

    def test_sla_matrix_overrides_priority_default(self):
        from psa.models import Contract, Ticket
        from psa.sla import compute_due_dates
        from datetime import date, timedelta
        # Contract pegs P1 response to 30 minutes (priority default is 240).
        Contract.objects.create(
            organization=self.org, client_org=self.org,
            name='Premium', start_date=date.today() - timedelta(days=1),
            status='active',
            sla_matrix={self.priority.code: {'response_minutes': 30, 'resolution_minutes': 120}},
        )
        t = Ticket.objects.create(
            organization=self.org, subject='SLA test',
            queue=self.queue, priority=self.priority,
            ticket_type=self.ttype, status=self.status,
        )
        fr, res = compute_due_dates(t)
        # Response should be 30 min after creation, not 240.
        delta = (fr - t.created_at).total_seconds() / 60
        self.assertAlmostEqual(delta, 30, delta=1)
        delta_res = (res - t.created_at).total_seconds() / 60
        self.assertAlmostEqual(delta_res, 120, delta=1)

    def test_workflow_rule_set_priority_on_create(self):
        from psa.models import Ticket, TicketPriority, WorkflowRule
        p2 = TicketPriority.objects.filter(code='P2').first()
        WorkflowRule.objects.create(
            organization=self.org,
            name='Outage → P1',
            trigger='ticket_created',
            conditions={'subject_contains': 'outage'},
            actions=[{'type': 'set_priority', 'code': 'P1'}],
            is_active=True,
        )
        t = Ticket.objects.create(
            organization=self.org, subject='Email outage',
            queue=self.queue, priority=p2,
            ticket_type=self.ttype, status=self.status,
        )
        t.refresh_from_db()
        self.assertEqual(t.priority.code, 'P1')

    def test_workflow_rule_skips_when_condition_false(self):
        from psa.models import Ticket, TicketPriority, WorkflowRule
        p3 = TicketPriority.objects.filter(code='P3').first()
        WorkflowRule.objects.create(
            organization=self.org,
            name='Outage → P1',
            trigger='ticket_created',
            conditions={'subject_contains': 'outage'},
            actions=[{'type': 'set_priority', 'code': 'P1'}],
            is_active=True,
        )
        t = Ticket.objects.create(
            organization=self.org, subject='Friendly hello',
            queue=self.queue, priority=p3,
            ticket_type=self.ttype, status=self.status,
        )
        t.refresh_from_db()
        # Condition was false — priority unchanged.
        self.assertEqual(t.priority.code, 'P3')

    def test_workflow_rule_add_tag_action(self):
        from psa.models import Ticket, WorkflowRule
        WorkflowRule.objects.create(
            organization=self.org,
            name='Tag VIP',
            trigger='ticket_created',
            conditions={},
            actions=[{'type': 'add_tag', 'tag': 'vip'}],
            is_active=True,
        )
        t = Ticket.objects.create(
            organization=self.org, subject='Anything',
            queue=self.queue, priority=self.priority,
            ticket_type=self.ttype, status=self.status,
        )
        t.refresh_from_db()
        self.assertIn('vip', t.tags or [])

    def test_workflow_rule_inactive_does_not_fire(self):
        from psa.models import Ticket, WorkflowRule
        rule = WorkflowRule.objects.create(
            organization=self.org,
            name='Tag Inactive',
            trigger='ticket_created',
            conditions={},
            actions=[{'type': 'add_tag', 'tag': 'should-not-appear'}],
            is_active=False,
        )
        t = Ticket.objects.create(
            organization=self.org, subject='Test',
            queue=self.queue, priority=self.priority,
            ticket_type=self.ttype, status=self.status,
        )
        t.refresh_from_db()
        self.assertNotIn('should-not-appear', t.tags or [])
        rule.refresh_from_db()
        self.assertEqual(rule.fire_count, 0)

    def test_workflow_rule_bad_action_recorded_on_rule(self):
        """A misconfigured action shouldn't break ticket save — error is
        captured on the rule row instead."""
        from psa.models import Ticket, WorkflowRule
        rule = WorkflowRule.objects.create(
            organization=self.org,
            name='Broken rule',
            trigger='ticket_created',
            conditions={},
            actions=[{'type': 'bogus_action'}],
            is_active=True,
        )
        Ticket.objects.create(
            organization=self.org, subject='x',
            queue=self.queue, priority=self.priority,
            ticket_type=self.ttype, status=self.status,
        )
        rule.refresh_from_db()
        self.assertIn('bogus_action', rule.last_error)

    def test_sample_workflows_seed_command(self):
        from psa.models import WorkflowRule
        from django.core.management import call_command
        before = WorkflowRule.objects.filter(organization=self.org).count()
        call_command('psa_seed_sample_workflows', '--org-id', str(self.org.id), verbosity=0)
        after = WorkflowRule.objects.filter(organization=self.org).count()
        self.assertGreater(after, before)


class Phase8BillingTests(TestCase):
    """Phase 8: Invoices, line items, payments, generate-from-ticket."""

    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='ACME P8', slug='acme-p8')
        self.client_org = Organization.objects.create(name='Client P8', slug='client-p8')
        self.user = User.objects.create_user('p8', password='pw', email='p8@x.com')
        Membership.objects.update_or_create(
            user=self.user, organization=self.org,
            defaults={'role': Role.OWNER, 'is_active': True},
        )
        from psa.models import Queue, TicketPriority, TicketType, TicketStatus
        self.queue = Queue.objects.first()
        self.priority = TicketPriority.objects.first()
        self.ttype = TicketType.objects.first()
        self.status = TicketStatus.objects.filter(slug='new').first()

    def test_invoice_auto_numbers(self):
        from psa.models import Invoice
        from datetime import date
        i = Invoice.objects.create(
            organization=self.org, client_org=self.client_org,
            title='January work', invoice_date=date.today(),
        )
        self.assertTrue(i.invoice_number.startswith(f'INV-{date.today().year}-'))

    def test_invoice_recompute_totals_with_payments_updates_status(self):
        from psa.models import Invoice, InvoiceLineItem, Payment
        from datetime import date
        from decimal import Decimal
        inv = Invoice.objects.create(
            organization=self.org, client_org=self.client_org,
            title='Onboarding', invoice_date=date.today(), status='sent',
        )
        InvoiceLineItem.objects.create(invoice=inv, description='Setup', quantity=1, unit_price=200)
        InvoiceLineItem.objects.create(invoice=inv, description='Training', quantity=2, unit_price=100)
        inv.recompute_totals()
        self.assertEqual(inv.total, Decimal('400.00'))
        Payment.objects.create(invoice=inv, amount=Decimal('150.00'), paid_on=date.today(), method='ach')
        inv.refresh_from_db()
        self.assertEqual(inv.amount_paid, Decimal('150.00'))
        self.assertEqual(inv.status, 'partial')
        Payment.objects.create(invoice=inv, amount=Decimal('250.00'), paid_on=date.today(), method='ach')
        inv.refresh_from_db()
        self.assertEqual(inv.amount_paid, Decimal('400.00'))
        self.assertEqual(inv.status, 'paid')

    def test_invoice_balance_computed(self):
        from psa.models import Invoice, InvoiceLineItem, Payment
        from datetime import date
        from decimal import Decimal
        inv = Invoice.objects.create(
            organization=self.org, client_org=self.client_org,
            title='X', invoice_date=date.today(), status='sent',
        )
        InvoiceLineItem.objects.create(invoice=inv, description='item', quantity=1, unit_price=500)
        inv.recompute_totals()
        Payment.objects.create(invoice=inv, amount=Decimal('200'), paid_on=date.today(), method='ach')
        inv.refresh_from_db()
        self.assertEqual(inv.balance, Decimal('300.00'))




# ---------------------------------------------------------------------------
# Phase 36 v2 — Pre-Invoice Approval Gate (v3.17.228)
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class InvoiceApprovalGateTests(TestCase):
    """Phase 36 v2: pre-invoice approval workflow."""

    def setUp(self):
        from accounts.models import Membership, Role
        _setup_seed()
        from core.models import SystemSetting
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='InvApprMSP', slug='inv-appr-msp')
        self.client_org = Organization.objects.create(name='InvApprClient', slug='inv-appr-c')
        self.admin = User.objects.create_user('inv-admin', password='pw', email='ia@x.com',
                                                is_superuser=True, is_staff=True)
        Membership.objects.update_or_create(
            user=self.admin, organization=self.org,
            defaults={'role': Role.OWNER, 'is_active': True},
        )

    def test_flag_for_approval_above_total_threshold(self):
        from psa.models import Invoice
        from datetime import date
        from decimal import Decimal as _D
        inv = Invoice.objects.create(
            organization=self.org, client_org=self.client_org,
            title='Big invoice', invoice_date=date.today(),
            total=_D('15000'),
        )
        flagged = inv.flag_for_approval(total_threshold=10000)
        self.assertTrue(flagged)
        self.assertTrue(inv.requires_approval)
        self.assertIn('total', inv.approval_reason)
        self.assertIn('15000', inv.approval_reason)

    def test_flag_for_approval_below_total_threshold(self):
        from psa.models import Invoice
        from datetime import date
        from decimal import Decimal as _D
        inv = Invoice.objects.create(
            organization=self.org, client_org=self.client_org,
            title='Small invoice', invoice_date=date.today(),
            total=_D('500'),
        )
        flagged = inv.flag_for_approval(total_threshold=10000)
        self.assertFalse(flagged)
        self.assertFalse(inv.requires_approval)

    def test_flag_for_approval_above_overage_threshold(self):
        from psa.models import Invoice, Contract
        from datetime import date
        from decimal import Decimal as _D
        contract = Contract.objects.create(
            organization=self.org, client_org=self.client_org,
            name='Block-overage', contract_type='block_hours',
            status='active', start_date=date.today(),
            total_hours=_D('100'), hours_used_minutes=130 * 60,  # 130% used
        )
        inv = Invoice.objects.create(
            organization=self.org, client_org=self.client_org,
            title='Inv with overage', invoice_date=date.today(),
            total=_D('500'), source_contract=contract,
        )
        flagged = inv.flag_for_approval(total_threshold=10000, overage_pct_threshold=110)
        self.assertTrue(flagged)
        self.assertIn('Block-overage', inv.approval_reason)

    def test_approve_clears_gate_and_records_user(self):
        from psa.models import Invoice
        from datetime import date
        from decimal import Decimal as _D
        inv = Invoice.objects.create(
            organization=self.org, client_org=self.client_org,
            title='Pending', invoice_date=date.today(), total=_D('500'),
            requires_approval=True, approval_reason='manual',
        )
        inv.approve(user=self.admin)
        inv.refresh_from_db()
        self.assertFalse(inv.requires_approval)
        self.assertEqual(inv.approved_by_id, self.admin.id)
        self.assertIsNotNone(inv.approved_at)

    def test_invoice_approve_view_201(self):
        from psa.models import Invoice
        from datetime import date
        from decimal import Decimal as _D
        from django.test import Client
        inv = Invoice.objects.create(
            organization=self.org, client_org=self.client_org,
            title='To approve', invoice_date=date.today(), total=_D('500'),
            requires_approval=True, approval_reason='over threshold',
        )
        c = Client()
        c.force_login(self.admin)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()
        r = c.post(f'/psa/invoices/{inv.pk}/approve/')
        self.assertEqual(r.status_code, 302)
        inv.refresh_from_db()
        self.assertFalse(inv.requires_approval)
        self.assertEqual(inv.approved_by_id, self.admin.id)

    def test_push_to_accounting_blocked_when_pending_approval(self):
        from psa.models import Invoice
        from datetime import date
        from decimal import Decimal as _D
        from django.test import Client
        inv = Invoice.objects.create(
            organization=self.org, client_org=self.client_org,
            title='Pending push', invoice_date=date.today(), total=_D('500'),
            requires_approval=True, approval_reason='hold',
        )
        c = Client()
        c.force_login(self.admin)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()
        # Should redirect with error and NOT touch accounting_external_id.
        r = c.post(f'/psa/invoices/{inv.pk}/push/')
        self.assertEqual(r.status_code, 302)
        inv.refresh_from_db()
        self.assertEqual(inv.accounting_external_id, '')

    # --- v3.17.526: double-push guard -------------------------------------
    # The provider creates a NEW invoice on every push_invoice() call, so the
    # button was one stray double-click away from putting two invoices in front
    # of a client's accounts payable. Deduplication existed only as a report
    # that found them after the fact.

    def _push_client(self):
        from django.test import Client
        c = Client()
        c.force_login(self.admin)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()
        return c

    def _pushed_invoice(self, **kwargs):
        from psa.models import Invoice
        from datetime import date
        from decimal import Decimal as _D
        from django.utils import timezone as _tz
        defaults = dict(
            organization=self.org, client_org=self.client_org,
            title='Already pushed', invoice_date=date.today(), total=_D('500'),
            accounting_provider='quickbooks_online',
            accounting_external_id='QBO-1001',
            pushed_to_accounting_at=_tz.now(),
        )
        defaults.update(kwargs)
        return Invoice.objects.create(**defaults)

    def test_second_push_is_refused(self):
        inv = self._pushed_invoice()
        with mock.patch(
            'integrations.providers.accounting.get_accounting_provider'
        ) as get_provider:
            r = self._push_client().post(f'/psa/invoices/{inv.pk}/push/')
        self.assertEqual(r.status_code, 302)
        get_provider.assert_not_called()
        inv.refresh_from_db()
        self.assertEqual(inv.accounting_external_id, 'QBO-1001')

    def test_refusal_names_the_existing_provider_id(self):
        """The operator has to be able to go look the invoice up."""
        inv = self._pushed_invoice()
        with mock.patch('integrations.providers.accounting.get_accounting_provider'):
            r = self._push_client().post(
                f'/psa/invoices/{inv.pk}/push/', follow=True)
        text = ' '.join(str(m) for m in r.context['messages'])
        self.assertIn('QBO-1001', text)
        self.assertIn('Quickbooks Online', text)

    def test_force_allows_a_deliberate_re_push(self):
        inv = self._pushed_invoice()
        with mock.patch(
            'integrations.providers.accounting.get_accounting_provider'
        ) as get_provider:
            get_provider.return_value = None      # stop before a real API call
            r = self._push_client().post(
                f'/psa/invoices/{inv.pk}/push/', {'force': '1'})
        self.assertEqual(r.status_code, 302)
        # Got past the guard: connection resolution ran and asked for a provider.
        self.assertTrue(
            get_provider.called,
            'force=1 must get past the double-push guard')

    def test_never_pushed_invoice_is_unaffected(self):
        """The guard must not block a genuine first push."""
        inv = self._pushed_invoice(
            title='Fresh', accounting_provider='', accounting_external_id='',
            pushed_to_accounting_at=None)
        with mock.patch(
            'integrations.providers.accounting.get_accounting_provider'
        ) as get_provider:
            get_provider.return_value = None
            self._push_client().post(f'/psa/invoices/{inv.pk}/push/')
        self.assertTrue(get_provider.called)

    def test_request_approval_view_sets_flag(self):
        from psa.models import Invoice
        from datetime import date
        from decimal import Decimal as _D
        from django.test import Client
        inv = Invoice.objects.create(
            organization=self.org, client_org=self.client_org,
            title='Manual flag', invoice_date=date.today(), total=_D('500'),
        )
        self.assertFalse(inv.requires_approval)
        c = Client()
        c.force_login(self.admin)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()
        r = c.post(f'/psa/invoices/{inv.pk}/request-approval/',
                   data={'reason': 'Customer dispute pending'})
        self.assertEqual(r.status_code, 302)
        inv.refresh_from_db()
        self.assertTrue(inv.requires_approval)
        self.assertIn('Customer dispute', inv.approval_reason)


# ---------------------------------------------------------------------------
# Phase 12 v1 — CSAT Surveys (v3.17.231)
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class CSATSurveyTests(TestCase):
    """Phase 12 v1: post-close CSAT survey emailer + token response."""

    def setUp(self):
        from django.core import mail
        mail.outbox = []
        _setup_seed()
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.psa_csat_enabled = True
        s.save()
        self.org = Organization.objects.create(name='CSATCo', slug='csat-co')
        self.user = User.objects.create_user('csat-tech', password='pw', email='ct@x.com')
        Membership.objects.update_or_create(
            user=self.user, organization=self.org,
            defaults={'role': Role.OWNER, 'is_active': True},
        )
        from psa.models import Queue, TicketPriority, TicketType, TicketStatus
        self.queue = Queue.objects.first()
        self.priority = TicketPriority.objects.first()
        self.ttype = TicketType.objects.first()
        self.status_new = TicketStatus.objects.filter(slug='new').first()
        self.status_terminal = TicketStatus.objects.filter(is_terminal=True).first()

    def _make_ticket(self, **overrides):
        from psa.models import Ticket
        defaults = dict(
            organization=self.org, subject='CSAT pilot',
            queue=self.queue, priority=self.priority,
            ticket_type=self.ttype, status=self.status_new,
            requester_email='customer@example.com',
            requester_name='Casey Customer',
        )
        defaults.update(overrides)
        return Ticket.objects.create(**defaults)

    def test_survey_created_when_ticket_moves_to_terminal(self):
        from django.core import mail
        from psa.models import TicketCSATSurvey
        ticket = self._make_ticket()
        self.assertEqual(TicketCSATSurvey.objects.count(), 0)
        ticket.status = self.status_terminal
        ticket.save()
        self.assertEqual(TicketCSATSurvey.objects.count(), 1)
        survey = TicketCSATSurvey.objects.get(ticket=ticket)
        self.assertEqual(survey.recipient_email, 'customer@example.com')
        self.assertIsNotNone(survey.token)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(ticket.ticket_number, mail.outbox[0].subject)

    def test_survey_not_created_when_csat_disabled(self):
        from psa.models import TicketCSATSurvey
        s = SystemSetting.get_settings()
        s.psa_csat_enabled = False
        s.save()
        ticket = self._make_ticket()
        ticket.status = self.status_terminal
        ticket.save()
        self.assertEqual(TicketCSATSurvey.objects.count(), 0)

    def test_survey_idempotent_on_second_terminal_save(self):
        from psa.models import TicketCSATSurvey
        from django.core import mail
        ticket = self._make_ticket()
        ticket.status = self.status_terminal
        ticket.save()
        # Second save while still terminal — no transition, no new survey.
        ticket.save()
        # Re-open and re-close — still only one survey (OneToOne on ticket).
        ticket.status = self.status_new
        ticket.save()
        ticket.status = self.status_terminal
        ticket.save()
        self.assertEqual(TicketCSATSurvey.objects.count(), 1)
        # Only the first close sent an email; subsequent transitions
        # find the existing survey and short-circuit.
        self.assertEqual(len(mail.outbox), 1)

    def test_survey_skipped_when_no_recipient(self):
        from psa.models import TicketCSATSurvey
        from django.core import mail
        ticket = self._make_ticket(requester_email='')
        ticket.status = self.status_terminal
        ticket.save()
        self.assertEqual(TicketCSATSurvey.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_csat_respond_view_records_rating(self):
        from psa.models import TicketCSATSurvey
        from django.test import Client
        ticket = self._make_ticket()
        ticket.status = self.status_terminal
        ticket.save()
        survey = TicketCSATSurvey.objects.get(ticket=ticket)
        c = Client()
        r = c.post(f'/psa/csat/{survey.token}/', data={
            'rating': '5',
            'comment': 'Great work!',
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Thanks for your feedback')
        survey.refresh_from_db()
        self.assertEqual(survey.rating, 5)
        self.assertEqual(survey.comment, 'Great work!')
        self.assertIsNotNone(survey.responded_at)

    def test_csat_respond_view_rejects_invalid_rating(self):
        from psa.models import TicketCSATSurvey
        from django.test import Client
        ticket = self._make_ticket()
        ticket.status = self.status_terminal
        ticket.save()
        survey = TicketCSATSurvey.objects.get(ticket=ticket)
        c = Client()
        r = c.post(f'/psa/csat/{survey.token}/', data={'rating': '99'})
        self.assertEqual(r.status_code, 200)
        # Stays on the form, rating not persisted.
        survey.refresh_from_db()
        self.assertIsNone(survey.rating)

    def test_csat_respond_view_404_for_unknown_token(self):
        from django.test import Client
        c = Client()
        r = c.get('/psa/csat/this-token-does-not-exist/')
        self.assertEqual(r.status_code, 404)


# ---------------------------------------------------------------------------
# Phase 25 v1 — Mature Timesheet Approval Workflows (v3.17.242)
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TimesheetApprovalTests(TestCase):
    """Phase 25 v1: weekly timesheet submission + manager approval."""

    def setUp(self):
        from accounts.models import Membership, Role
        from datetime import datetime, timedelta as _td
        _setup_seed()
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        self.org = Organization.objects.create(name='TimeCo', slug='time-co')
        self.tech = User.objects.create_user('time-tech', password='pw', email='t@x.com')
        Membership.objects.update_or_create(
            user=self.tech, organization=self.org,
            defaults={'role': Role.OWNER, 'is_active': True},
        )
        self.staff = User.objects.create_user('time-staff', password='pw', email='s@x.com',
                                                is_staff=True, is_superuser=True)
        from psa.models import Queue, TicketPriority, TicketType, TicketStatus, Ticket, TicketTimeEntry
        ticket = Ticket.objects.create(
            organization=self.org, subject='X',
            queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
        )
        # Build 3 entries on Tuesday/Wednesday/Thursday of a known ISO week.
        # Pick a fixed Monday so test results are reproducible.
        self.monday = datetime(2026, 4, 27, 9, 0)
        for i, hours in enumerate([(2, 30), (3, 0), (4, 15)]):
            started = self.monday + _td(days=i + 1)  # Tue, Wed, Thu
            ended = started + _td(hours=hours[0], minutes=hours[1])
            TicketTimeEntry.objects.create(
                ticket=ticket, user=self.tech,
                started_at=timezone.make_aware(started),
                ended_at=timezone.make_aware(ended),
                duration_minutes=hours[0] * 60 + hours[1],
            )

    def _login(self, c, user):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()

    def _iso(self):
        return self.monday.date().isocalendar()[:2]

    def test_my_timesheet_renders_week_with_entries(self):
        c = Client()
        self._login(c, self.tech)
        year, week = self._iso()
        r = c.get(f'/psa/timesheet/{year}/{week}/')
        self.assertEqual(r.status_code, 200)
        ctx = r.context
        self.assertEqual(len(ctx['entries']), 3)
        # 2:30 + 3:00 + 4:15 = 9h45m = 585 min
        self.assertEqual(ctx['total_minutes'], 585)

    def test_submit_creates_pending_submission_and_attaches_entries(self):
        from psa.models import TimesheetSubmission, TicketTimeEntry
        c = Client()
        self._login(c, self.tech)
        year, week = self._iso()
        r = c.post(f'/psa/timesheet/{year}/{week}/', data={'notes': 'OK'})
        self.assertEqual(r.status_code, 302)
        sub = TimesheetSubmission.objects.get(user=self.tech)
        self.assertEqual(sub.status, 'pending')
        self.assertEqual(sub.submitter_notes, 'OK')
        attached = TicketTimeEntry.objects.filter(submission=sub).count()
        self.assertEqual(attached, 3)

    def test_approve_keeps_entries_attached(self):
        from psa.models import TimesheetSubmission, TicketTimeEntry
        c_tech = Client()
        self._login(c_tech, self.tech)
        year, week = self._iso()
        c_tech.post(f'/psa/timesheet/{year}/{week}/', data={})
        sub = TimesheetSubmission.objects.get(user=self.tech)

        c_staff = Client()
        self._login(c_staff, self.staff)
        c_staff.post(f'/psa/timesheet-approvals/{sub.pk}/decide/',
                     data={'decision': 'approve', 'notes': 'good'})
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'approved')
        self.assertEqual(sub.decided_by_id, self.staff.id)
        # Entries stay attached (audit trail).
        self.assertEqual(
            TicketTimeEntry.objects.filter(submission=sub).count(), 3,
        )

    def test_reject_detaches_entries_for_resubmit(self):
        from psa.models import TimesheetSubmission, TicketTimeEntry
        c_tech = Client()
        self._login(c_tech, self.tech)
        year, week = self._iso()
        c_tech.post(f'/psa/timesheet/{year}/{week}/', data={})
        sub = TimesheetSubmission.objects.get(user=self.tech)

        c_staff = Client()
        self._login(c_staff, self.staff)
        c_staff.post(f'/psa/timesheet-approvals/{sub.pk}/decide/',
                     data={'decision': 'reject', 'notes': 'fix entry 2'})
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'rejected')
        # Entries detached so the tech can fix + re-submit.
        self.assertEqual(
            TicketTimeEntry.objects.filter(submission=sub).count(), 0,
        )

    def test_resubmit_after_reject_revives_pending(self):
        from psa.models import TimesheetSubmission, TicketTimeEntry
        c_tech = Client()
        self._login(c_tech, self.tech)
        year, week = self._iso()
        c_tech.post(f'/psa/timesheet/{year}/{week}/', data={})
        sub = TimesheetSubmission.objects.get(user=self.tech)
        c_staff = Client()
        self._login(c_staff, self.staff)
        c_staff.post(f'/psa/timesheet-approvals/{sub.pk}/decide/',
                     data={'decision': 'reject'})
        # Tech re-submits.
        c_tech.post(f'/psa/timesheet/{year}/{week}/', data={'notes': 'fixed it'})
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'pending')
        self.assertEqual(sub.submitter_notes, 'fixed it')
        self.assertEqual(
            TicketTimeEntry.objects.filter(submission=sub).count(), 3,
        )

    def test_non_staff_cant_decide(self):
        from psa.models import TimesheetSubmission
        c_tech = Client()
        self._login(c_tech, self.tech)
        year, week = self._iso()
        c_tech.post(f'/psa/timesheet/{year}/{week}/', data={})
        sub = TimesheetSubmission.objects.get(user=self.tech)
        # Tech tries to approve their own.
        r = c_tech.post(f'/psa/timesheet-approvals/{sub.pk}/decide/',
                        data={'decision': 'approve'})
        self.assertEqual(r.status_code, 302)  # redirect to dashboard
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'pending')

    # --- Phase 25 v2 (v3.17.249) ---------------------------------------

    def test_approved_entry_locked_against_edit(self):
        # v3.17.249: TicketTimeEntry.save() must be a no-op when the entry
        # is attached to an APPROVED submission.
        from psa.models import TimesheetSubmission, TicketTimeEntry
        c_tech = Client()
        self._login(c_tech, self.tech)
        year, week = self._iso()
        c_tech.post(f'/psa/timesheet/{year}/{week}/', data={})
        sub = TimesheetSubmission.objects.get(user=self.tech)
        c_staff = Client()
        self._login(c_staff, self.staff)
        c_staff.post(f'/psa/timesheet-approvals/{sub.pk}/decide/',
                     data={'decision': 'approve'})

        entry = TicketTimeEntry.objects.filter(submission=sub).first()
        original = entry.notes
        entry.notes = 'tampered'
        entry.save()
        # Re-read; expect untouched.
        entry.refresh_from_db()
        self.assertEqual(entry.notes, original)

    def test_force_unlock_allows_admin_override(self):
        # _force_unlock=True must let an admin push an edit through.
        from psa.models import TimesheetSubmission, TicketTimeEntry
        c_tech = Client()
        self._login(c_tech, self.tech)
        year, week = self._iso()
        c_tech.post(f'/psa/timesheet/{year}/{week}/', data={})
        sub = TimesheetSubmission.objects.get(user=self.tech)
        c_staff = Client()
        self._login(c_staff, self.staff)
        c_staff.post(f'/psa/timesheet-approvals/{sub.pk}/decide/',
                     data={'decision': 'approve'})

        entry = TicketTimeEntry.objects.filter(submission=sub).first()
        entry.notes = 'admin override'
        entry.save(_force_unlock=True)
        entry.refresh_from_db()
        self.assertEqual(entry.notes, 'admin override')

    def test_bulk_decide_approves_selected(self):
        from psa.models import TimesheetSubmission, Ticket, TicketTimeEntry
        from datetime import datetime, timedelta as _td
        # Create a second tech + their submission.
        tech2 = User.objects.create_user('tech2', password='pw', email='t2@x.com')
        Membership.objects.update_or_create(
            user=tech2, organization=self.org,
            defaults={'role': Role.OWNER, 'is_active': True},
        )
        from psa.models import Queue, TicketPriority, TicketStatus, TicketType
        ticket = Ticket.objects.create(
            organization=self.org, subject='Y',
            queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.filter(slug='new').first(),
        )
        started = self.monday + _td(days=1)
        TicketTimeEntry.objects.create(
            ticket=ticket, user=tech2,
            started_at=timezone.make_aware(started),
            ended_at=timezone.make_aware(started + _td(minutes=30)),
            duration_minutes=30,
        )
        c_t1 = Client(); self._login(c_t1, self.tech)
        c_t2 = Client(); self._login(c_t2, tech2)
        year, week = self._iso()
        c_t1.post(f'/psa/timesheet/{year}/{week}/', data={})
        c_t2.post(f'/psa/timesheet/{year}/{week}/', data={})
        ids = list(TimesheetSubmission.objects.values_list('pk', flat=True))
        self.assertEqual(len(ids), 2)

        c_staff = Client()
        self._login(c_staff, self.staff)
        r = c_staff.post('/psa/timesheet-approvals/bulk/', data={
            'submission_ids': [str(i) for i in ids],
            'decision': 'approve',
            'notes': 'batch ok',
        })
        self.assertEqual(r.status_code, 302)
        for s in TimesheetSubmission.objects.all():
            self.assertEqual(s.status, 'approved')

    def test_payroll_csv_export_contains_approved(self):
        from psa.models import TimesheetSubmission
        c_tech = Client()
        self._login(c_tech, self.tech)
        year, week = self._iso()
        c_tech.post(f'/psa/timesheet/{year}/{week}/', data={})
        sub = TimesheetSubmission.objects.get(user=self.tech)
        c_staff = Client()
        self._login(c_staff, self.staff)
        c_staff.post(f'/psa/timesheet-approvals/{sub.pk}/decide/',
                     data={'decision': 'approve'})
        # Pull CSV with a wide window to be sure we capture it.
        r = c_staff.get('/psa/timesheet-approvals/payroll-export/?start=2026-01-01&end=2030-01-01')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'text/csv')
        body = r.content.decode('utf-8')
        self.assertIn('time-tech', body)  # username column
        self.assertIn('Total minutes', body.split('\n')[0])

    def test_payroll_csv_blocked_for_non_staff(self):
        c_tech = Client()
        self._login(c_tech, self.tech)
        r = c_tech.get('/psa/timesheet-approvals/payroll-export/')
        self.assertEqual(r.status_code, 302)


# ---------------------------------------------------------------------------
# Phase 20 v1 — escalate idle PSAApprovals (v3.17.256)
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class PSAApprovalEscalationTests(TestCase):
    """v3.17.256 — Phase 20 v1: idle-approval escalation cron."""

    def setUp(self):
        from accounts.models import Membership, Role
        from datetime import timedelta as _td
        _setup_seed()
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        self.org = Organization.objects.create(name='EscalCo', slug='escal-co')
        self.user = User.objects.create_user('escal-user', 'eu@x.com', 'pw')
        Membership.objects.create(user=self.user, organization=self.org,
                                   role=Role.OWNER, is_active=True)
        self.admin = User.objects.create_user('escal-admin', 'admin@x.com', 'pw',
                                                is_staff=True, is_superuser=True)
        from psa.models import PSAApproval
        # Idle (60h old, 48h threshold) — should escalate
        idle = PSAApproval.objects.create(
            organization=self.org, kind='time',
            object_type='psa.TicketTimeEntry', object_id=1,
            requested_by=self.user, escalation_threshold_hours=48,
        )
        PSAApproval.objects.filter(pk=idle.pk).update(
            requested_at=timezone.now() - _td(hours=60),
        )
        self.idle = idle
        # Fresh (1h old, 48h threshold) — should NOT
        self.fresh = PSAApproval.objects.create(
            organization=self.org, kind='time',
            object_type='psa.TicketTimeEntry', object_id=2,
            requested_by=self.user, escalation_threshold_hours=48,
        )
        # Threshold=0 (never escalate) but old
        decay = PSAApproval.objects.create(
            organization=self.org, kind='time',
            object_type='psa.TicketTimeEntry', object_id=3,
            requested_by=self.user, escalation_threshold_hours=0,
        )
        PSAApproval.objects.filter(pk=decay.pk).update(
            requested_at=timezone.now() - _td(hours=200),
        )
        self.never = decay
        # Already escalated old approval — should NOT re-escalate
        already = PSAApproval.objects.create(
            organization=self.org, kind='time',
            object_type='psa.TicketTimeEntry', object_id=4,
            requested_by=self.user, escalation_threshold_hours=48,
        )
        PSAApproval.objects.filter(pk=already.pk).update(
            requested_at=timezone.now() - _td(hours=80),
            escalated_at=timezone.now() - _td(hours=20),
        )
        self.already = already

    def test_command_emails_admins_about_idle_approvals(self):
        from django.core import mail
        from django.core.management import call_command
        from psa.models import PSAApproval
        mail.outbox = []
        call_command('psa_escalate_idle_approvals', verbosity=0)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ['admin@x.com'])
        # Idle one referenced by pk
        self.assertIn(f'#{self.idle.pk}', msg.body)
        # Fresh / never / already-escalated absent
        self.assertNotIn(f'#{self.fresh.pk}', msg.body)
        self.assertNotIn(f'#{self.never.pk}', msg.body)
        self.assertNotIn(f'#{self.already.pk}', msg.body)
        # escalated_at stamped
        self.idle.refresh_from_db()
        self.assertIsNotNone(self.idle.escalated_at)

    def test_command_dedupe_runs_no_op_after_first(self):
        from django.core import mail
        from django.core.management import call_command
        mail.outbox = []
        call_command('psa_escalate_idle_approvals', verbosity=0)
        first_count = len(mail.outbox)
        # Re-fire — already-escalated row stays out, no other idle rows.
        call_command('psa_escalate_idle_approvals', verbosity=0)
        self.assertEqual(len(mail.outbox), first_count)  # no new email

    def test_dry_run_does_not_send_or_stamp(self):
        from django.core import mail
        from django.core.management import call_command
        mail.outbox = []
        call_command('psa_escalate_idle_approvals', '--dry-run', verbosity=0)
        self.assertEqual(len(mail.outbox), 0)
        self.idle.refresh_from_db()
        self.assertIsNone(self.idle.escalated_at)

    def test_no_admins_no_send(self):
        # Strip the admin's email, command bails out cleanly.
        from django.core import mail
        from django.core.management import call_command
        from django.contrib.auth.models import User as _U
        _U.objects.filter(is_superuser=True).update(email='')
        mail.outbox = []
        call_command('psa_escalate_idle_approvals', verbosity=0)
        self.assertEqual(len(mail.outbox), 0)


# ---------------------------------------------------------------------------
# Phase 20 v2 — auto-flag invoices over threshold (v3.17.259)
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class InvoiceAutoFlagTests(TestCase):
    """Phase 20 v2: SystemSetting thresholds auto-flag new invoices for approval."""

    def setUp(self):
        from accounts.models import Membership, Role
        _setup_seed()
        self.org = Organization.objects.create(name='AutoFlagCo', slug='af-co')
        self.user = User.objects.create_user('af-user', 'au@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        Membership.objects.create(user=self.user, organization=self.org,
                                   role=Role.OWNER, is_active=True)

    def _make_invoice(self, total='15000'):
        from psa.models import Invoice
        from datetime import date
        from decimal import Decimal as _D
        return Invoice.objects.create(
            organization=self.org, client_org=self.org,
            title='Auto-flag candidate',
            invoice_date=date.today(), total=_D(total),
        )

    def test_invoice_below_threshold_not_flagged(self):
        s = SystemSetting.get_settings()
        s.invoice_approval_threshold_total = 10000
        s.save()
        inv = self._make_invoice(total='5000')
        inv.refresh_from_db()
        self.assertFalse(inv.requires_approval)

    def test_invoice_above_threshold_auto_flagged(self):
        s = SystemSetting.get_settings()
        s.invoice_approval_threshold_total = 10000
        s.save()
        inv = self._make_invoice(total='15000')
        inv.refresh_from_db()
        self.assertTrue(inv.requires_approval)
        self.assertIn('total', inv.approval_reason)

    def test_threshold_zero_disables_auto_flag(self):
        # Default 0 = disabled; even huge invoices stay unflagged.
        s = SystemSetting.get_settings()
        s.invoice_approval_threshold_total = 0
        s.invoice_approval_overage_pct = 0
        s.save()
        inv = self._make_invoice(total='1000000')
        inv.refresh_from_db()
        self.assertFalse(inv.requires_approval)

    def test_already_approved_invoice_not_re_flagged(self):
        # An invoice approved by a manager (requires_approval=False,
        # approved_at set) should NOT be re-flagged on subsequent saves
        # even if it crosses the threshold.
        from psa.models import Invoice
        s = SystemSetting.get_settings()
        s.invoice_approval_threshold_total = 1
        s.save()
        inv = self._make_invoice(total='5000')
        inv.refresh_from_db()
        # Manager approves
        inv.approve(user=self.user)
        inv.refresh_from_db()
        self.assertFalse(inv.requires_approval)
        # Subsequent save (e.g. tweak title) shouldn't re-flag
        inv.title = 'tweaked'
        inv.save()
        inv.refresh_from_db()
        self.assertFalse(inv.requires_approval)


class CreditMemoTests(TestCase):
    """Phase 27 v3 (v3.17.264): credit-memo workflow on Invoice."""

    def setUp(self):
        _setup_seed()
        self.org = Organization.objects.create(name='CreditCo', slug='credit-co')
        self.client_org = Organization.objects.create(name='ClientCo', slug='client-co')
        self.user = User.objects.create_user('cm-user', 'cm@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        Membership.objects.create(user=self.user, organization=self.org,
                                   role=Role.OWNER, is_active=True)

    def _make_invoice_with_lines(self):
        from psa.models import Invoice, InvoiceLineItem
        from datetime import date
        from decimal import Decimal as _D
        inv = Invoice.objects.create(
            organization=self.org, client_org=self.client_org,
            title='Source invoice', invoice_date=date.today(),
            tax_rate=_D('0.10'),
        )
        InvoiceLineItem.objects.create(invoice=inv, description='Hours',
                                       quantity=10, unit_price=_D('100.00'))
        InvoiceLineItem.objects.create(invoice=inv, description='Travel',
                                       quantity=1, unit_price=_D('50.00'))
        inv.recompute_totals()
        return inv

    def test_full_credit_memo_negates_all_lines(self):
        inv = self._make_invoice_with_lines()
        memo = inv.create_credit_memo(user=self.user, reason='RMA refund')
        self.assertTrue(memo.is_credit_memo)
        self.assertEqual(memo.credits_invoice, inv)
        self.assertTrue(memo.invoice_number.startswith('CN-'))
        self.assertEqual(memo.line_items.count(), 2)
        # Every line should have negative unit_price
        for li in memo.line_items.all():
            self.assertLess(li.unit_price, 0)
        # Total should be negative (sum: -1050 minus credit 0 = -1050 + tax)
        self.assertLess(memo.total, 0)

    def test_partial_lump_sum_credit(self):
        from decimal import Decimal as _D
        inv = self._make_invoice_with_lines()
        memo = inv.create_credit_memo(user=self.user, reason='Service credit',
                                       amount=_D('25.00'))
        self.assertEqual(memo.line_items.count(), 1)
        li = memo.line_items.get()
        self.assertEqual(li.unit_price, _D('-25.00'))
        self.assertEqual(memo.subtotal, _D('-25.00'))

    def test_cannot_credit_a_credit_memo(self):
        inv = self._make_invoice_with_lines()
        memo = inv.create_credit_memo(user=self.user, reason='first credit')
        with self.assertRaises(ValueError):
            memo.create_credit_memo(user=self.user, reason='nested')

    def test_credit_memo_numbers_are_sequential(self):
        inv = self._make_invoice_with_lines()
        memo1 = inv.create_credit_memo(user=self.user, reason='one')
        memo2 = inv.create_credit_memo(user=self.user, reason='two')
        # CN-YYYY-NNNNN — second should be one greater
        n1 = int(memo1.invoice_number.rsplit('-', 1)[-1])
        n2 = int(memo2.invoice_number.rsplit('-', 1)[-1])
        self.assertEqual(n2, n1 + 1)

    def test_view_creates_memo_via_post(self):
        inv = self._make_invoice_with_lines()
        c = Client()
        c.force_login(self.user)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()
        # Enable PSA gate so @require_psa_enabled lets us through
        ss = SystemSetting.get_settings()
        ss.psa_enabled = True
        ss.save()
        with override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False):
            r = c.post(f'/psa/invoices/{inv.pk}/credit-memo/',
                       {'reason': 'service credit', 'amount': '40.00'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(inv.credit_memos.count(), 1)
        memo = inv.credit_memos.get()
        self.assertEqual(memo.subtotal, -40)
        self.assertTrue(memo.invoice_number.startswith('CN-'))


class MultiStageApprovalTests(TestCase):
    """Phase 20 v3 (v3.17.265): chained PSAApproval stages."""

    def setUp(self):
        _setup_seed()
        self.org = Organization.objects.create(name='ChainCo', slug='chain-co')
        self.user = User.objects.create_user('chain-user', 'cu@x.com', 'pw')
        self.user2 = User.objects.create_user('chain-user-2', 'cu2@x.com', 'pw')

    def _stages(self, **base):
        return [
            {'request_comment': 'Stage 1 — manager'},
            {'request_comment': 'Stage 2 — director'},
            {'request_comment': 'Stage 3 — CFO'},
        ]

    def test_create_chain_marks_first_pending_rest_blocked(self):
        from psa.models import PSAApproval
        chain = PSAApproval.create_chain(
            organization=self.org, kind='quote',
            object_type='psa.Quote', object_id=42,
            stages=self._stages(),
        )
        self.assertEqual(len(chain), 3)
        self.assertEqual(chain[0].status, 'pending')
        self.assertEqual(chain[1].status, 'blocked')
        self.assertEqual(chain[2].status, 'blocked')
        # parent links
        self.assertIsNone(chain[0].parent_approval)
        self.assertEqual(chain[1].parent_approval, chain[0])
        self.assertEqual(chain[2].parent_approval, chain[1])
        # stage_index
        self.assertEqual([s.stage_index for s in chain], [1, 2, 3])

    def test_approving_first_unblocks_second(self):
        from psa.models import PSAApproval
        chain = PSAApproval.create_chain(
            organization=self.org, kind='quote',
            object_type='psa.Quote', object_id=42,
            stages=self._stages(),
        )
        chain[0].decide(user=self.user, approved=True, comment='ok')
        chain[1].refresh_from_db()
        chain[2].refresh_from_db()
        self.assertEqual(chain[1].status, 'pending')
        # Stage 3 still blocked — only the immediate next stage moves.
        self.assertEqual(chain[2].status, 'blocked')

    def test_approving_each_stage_walks_to_completion(self):
        from psa.models import PSAApproval
        chain = PSAApproval.create_chain(
            organization=self.org, kind='quote',
            object_type='psa.Quote', object_id=42,
            stages=self._stages(),
        )
        chain[0].decide(user=self.user, approved=True)
        chain[1].refresh_from_db()
        chain[1].decide(user=self.user, approved=True)
        chain[2].refresh_from_db()
        chain[2].decide(user=self.user, approved=True)
        for stage in chain:
            stage.refresh_from_db()
        self.assertEqual([s.status for s in chain], ['approved', 'approved', 'approved'])

    def test_denying_a_stage_cancels_downstream(self):
        from psa.models import PSAApproval
        chain = PSAApproval.create_chain(
            organization=self.org, kind='quote',
            object_type='psa.Quote', object_id=42,
            stages=self._stages(),
        )
        chain[0].decide(user=self.user, approved=False, comment='nope')
        chain[1].refresh_from_db()
        chain[2].refresh_from_db()
        self.assertEqual(chain[0].status, 'denied')
        self.assertEqual(chain[1].status, 'cancelled')
        self.assertEqual(chain[2].status, 'cancelled')
        self.assertIn('prior stage', chain[1].decision_comment)

    def test_blocked_stage_cannot_be_decided_directly(self):
        from psa.models import PSAApproval
        chain = PSAApproval.create_chain(
            organization=self.org, kind='quote',
            object_type='psa.Quote', object_id=42,
            stages=self._stages(),
        )
        with self.assertRaises(ValueError):
            chain[2].decide(user=self.user, approved=True)

    def test_single_stage_chain_works_like_solo_approval(self):
        from psa.models import PSAApproval
        chain = PSAApproval.create_chain(
            organization=self.org, kind='change',
            object_type='psa.Quote', object_id=99,
            stages=[{'request_comment': 'just the one'}],
        )
        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0].status, 'pending')
        chain[0].decide(user=self.user, approved=True)
        self.assertEqual(chain[0].status, 'approved')


class RecurringPurchaseTemplateTests(TestCase):
    """Phase 13 v7 (v3.17.266) — RecurringPurchaseTemplate spawn flow."""

    def setUp(self):
        _setup_seed()
        self.org = Organization.objects.create(name='RecPurchCo', slug='rec-pur-co')

    def _make(self, **overrides):
        from psa.models import RecurringPurchaseTemplate
        from datetime import date, timedelta
        defaults = dict(
            organization=self.org,
            name='Monthly Toner',
            recurrence='monthly',
            next_run_at=date.today() - timedelta(days=1),
            line_items_snapshot=[
                {'description': 'HP Toner CF410X', 'sku': 'CF410X',
                 'quantity': 4, 'unit_price': 89.99,
                 'distributor_provider': 'ingram'},
                {'description': 'HP Toner CF411X', 'sku': 'CF411X',
                 'quantity': 1, 'unit_price': 95.00},
            ],
        )
        defaults.update(overrides)
        return RecurringPurchaseTemplate.objects.create(**defaults)

    def test_spawn_pr_creates_draft_with_lines(self):
        from psa.models import PurchaseRequisition
        tpl = self._make()
        pr = tpl.spawn_pr()
        self.assertIsInstance(pr, PurchaseRequisition)
        self.assertEqual(pr.status, 'draft')
        self.assertEqual(pr.organization, self.org)
        self.assertEqual(pr.line_items.count(), 2)
        # 4 * 89.99 + 1 * 95 = 454.96
        from decimal import Decimal as _D
        self.assertEqual(pr.subtotal, _D('454.96'))
        self.assertEqual(pr.total, _D('454.96'))

    def test_spawn_advances_next_run_and_stamps_last_run(self):
        from datetime import date, timedelta
        tpl = self._make()
        before = tpl.next_run_at
        tpl.spawn_pr()
        tpl.refresh_from_db()
        self.assertEqual(tpl.last_run_at, date.today())
        # next_run_at should be ~1 month after the OLD next_run_at
        self.assertGreater(tpl.next_run_at, before)
        self.assertGreaterEqual((tpl.next_run_at - before).days, 28)

    def test_advance_recurrence_variants(self):
        from psa.models import RecurringPurchaseTemplate
        from datetime import date
        d = date(2026, 1, 15)
        self.assertEqual(RecurringPurchaseTemplate._advance(d, 'weekly'),
                          date(2026, 1, 22))
        self.assertEqual(RecurringPurchaseTemplate._advance(d, 'biweekly'),
                          date(2026, 1, 29))
        self.assertEqual(RecurringPurchaseTemplate._advance(d, 'monthly'),
                          date(2026, 2, 15))
        self.assertEqual(RecurringPurchaseTemplate._advance(d, 'quarterly'),
                          date(2026, 4, 15))
        self.assertEqual(RecurringPurchaseTemplate._advance(d, 'yearly'),
                          date(2027, 1, 15))

    def test_management_command_spawns_due_templates(self):
        from django.core.management import call_command
        from psa.models import PurchaseRequisition
        self._make(name='Due now')
        # Future template — should NOT spawn
        from datetime import date, timedelta
        self._make(name='Future', next_run_at=date.today() + timedelta(days=30))
        # Disabled template — should NOT spawn even if due
        self._make(name='Disabled', enabled=False)

        call_command('psa_run_recurring_purchases', verbosity=0)
        prs = PurchaseRequisition.objects.filter(organization=self.org)
        titles = list(prs.values_list('title', flat=True))
        self.assertIn('Due now', titles)
        self.assertNotIn('Future', titles)
        self.assertNotIn('Disabled', titles)

    def test_dry_run_does_not_create_prs(self):
        from django.core.management import call_command
        from psa.models import PurchaseRequisition
        tpl = self._make(name='Dry')
        call_command('psa_run_recurring_purchases', '--dry-run', verbosity=0)
        self.assertEqual(
            PurchaseRequisition.objects.filter(organization=self.org).count(), 0,
        )
        # Dry-run must NOT persist the next_run_at advance either.
        tpl.refresh_from_db()
        from datetime import date, timedelta
        self.assertEqual(tpl.next_run_at, date.today() - timedelta(days=1))


class QuoteApprovalRoutingTests(TestCase):
    """Phase 20 v4 (v3.17.270) — Quote.send_for_approval()."""

    def setUp(self):
        _setup_seed()
        self.org = Organization.objects.create(name='QARCo', slug='qar-co')
        self.client_org = Organization.objects.create(name='QARClient', slug='qar-client')
        self.user = User.objects.create_user('qar-user', 'qa@x.com', 'pw')

    def _make_quote(self, total='5000'):
        from psa.models import Quote
        from datetime import date
        from decimal import Decimal as _D
        return Quote.objects.create(
            organization=self.org, client_org=self.client_org,
            title='Test quote', status='draft',
            total=_D(total),
        )

    def test_default_single_stage_chain(self):
        from psa.models import PSAApproval
        q = self._make_quote(total='1000')
        chain = q.send_for_approval(user=self.user)
        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0].kind, 'quote')
        self.assertEqual(chain[0].object_type, 'psa.Quote')
        self.assertEqual(chain[0].object_id, q.pk)
        self.assertEqual(chain[0].status, 'pending')
        self.assertEqual(chain[0].requested_by, self.user)

    def test_threshold_creates_two_stage_chain(self):
        q = self._make_quote(total='15000')
        chain = q.send_for_approval(user=self.user,
                                     default_threshold_total=10000)
        self.assertEqual(len(chain), 2)
        self.assertEqual(chain[0].status, 'pending')
        self.assertEqual(chain[1].status, 'blocked')

    def test_below_threshold_stays_single_stage(self):
        q = self._make_quote(total='5000')
        chain = q.send_for_approval(user=self.user,
                                     default_threshold_total=10000)
        self.assertEqual(len(chain), 1)

    def test_explicit_stages_override_default(self):
        q = self._make_quote(total='100')
        chain = q.send_for_approval(user=self.user, stages=[
            {'request_comment': 's1'},
            {'request_comment': 's2'},
            {'request_comment': 's3'},
        ])
        self.assertEqual(len(chain), 3)

    def test_skips_when_open_chain_exists(self):
        from psa.models import PSAApproval
        q = self._make_quote()
        first = q.send_for_approval(user=self.user)
        # Resending while pending should return the existing chain
        second = q.send_for_approval(user=self.user)
        self.assertEqual([s.pk for s in first], [s.pk for s in second])
        # Only one chain in DB
        self.assertEqual(
            PSAApproval.objects.filter(object_type='psa.Quote',
                                        object_id=q.pk).count(),
            1,
        )

    def test_view_routes_quote_for_approval(self):
        from psa.models import PSAApproval
        q = self._make_quote(total='100')
        ss = SystemSetting.get_settings()
        ss.psa_enabled = True
        ss.save()
        # Make user able to view this org
        Membership.objects.create(user=self.user, organization=self.org,
                                   role=Role.OWNER, is_active=True)
        c = Client()
        c.force_login(self.user)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()
        with override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False):
            r = c.post(f'/psa/quotes/{q.pk}/send-for-approval/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(
            PSAApproval.objects.filter(object_type='psa.Quote',
                                        object_id=q.pk).count(),
            1,
        )


class ConditionalQuoteApprovalAutoRouteTests(TestCase):
    """Phase 20 v5 (v3.17.273): post_save signal auto-routes large
    quotes through a PSAApproval chain when the system threshold is set."""

    def setUp(self):
        _setup_seed()
        self.org = Organization.objects.create(name='AutoRouteCo', slug='autoroute-co')
        self.client_org = Organization.objects.create(name='AutoRouteClient',
                                                       slug='autoroute-client')

    def _make(self, total='5000'):
        from psa.models import Quote
        from datetime import date
        from decimal import Decimal as _D
        return Quote.objects.create(
            organization=self.org, client_org=self.client_org,
            title='Conditional', status='draft',
            total=_D(total),
        )

    def test_below_threshold_no_chain_created(self):
        from psa.models import PSAApproval
        ss = SystemSetting.get_settings()
        ss.quote_approval_threshold_total = 10000
        ss.save()
        q = self._make(total='5000')
        self.assertEqual(
            PSAApproval.objects.filter(object_type='psa.Quote',
                                        object_id=q.pk).count(),
            0,
        )

    def test_above_threshold_auto_creates_chain(self):
        from psa.models import PSAApproval
        ss = SystemSetting.get_settings()
        ss.quote_approval_threshold_total = 10000
        ss.save()
        q = self._make(total='15000')
        self.assertEqual(
            PSAApproval.objects.filter(object_type='psa.Quote',
                                        object_id=q.pk).count(),
            2,  # 2-stage chain because total >= threshold
        )

    def test_threshold_zero_disables_auto_route(self):
        from psa.models import PSAApproval
        ss = SystemSetting.get_settings()
        ss.quote_approval_threshold_total = 0
        ss.save()
        q = self._make(total='999999')
        self.assertEqual(
            PSAApproval.objects.filter(object_type='psa.Quote',
                                        object_id=q.pk).count(),
            0,
        )

    def test_idempotent_on_subsequent_saves(self):
        from psa.models import PSAApproval
        ss = SystemSetting.get_settings()
        ss.quote_approval_threshold_total = 1000
        ss.save()
        q = self._make(total='5000')
        n_before = PSAApproval.objects.filter(
            object_type='psa.Quote', object_id=q.pk).count()
        q.title = 'tweaked'
        q.save()
        n_after = PSAApproval.objects.filter(
            object_type='psa.Quote', object_id=q.pk).count()
        self.assertEqual(n_before, n_after)

    def test_only_draft_and_sent_statuses_route(self):
        from psa.models import PSAApproval
        ss = SystemSetting.get_settings()
        ss.quote_approval_threshold_total = 1000
        ss.save()
        # Create at status='accepted' — should NOT auto-route
        from psa.models import Quote
        from datetime import date
        from decimal import Decimal as _D
        q = Quote.objects.create(
            organization=self.org, client_org=self.client_org,
            title='Already accepted', status='accepted', total=_D('5000'),
        )
        self.assertEqual(
            PSAApproval.objects.filter(object_type='psa.Quote',
                                        object_id=q.pk).count(),
            0,
        )


class ApprovalAuditTrailTests(TestCase):
    """Phase 20 v6 (v3.17.274): every PSAApproval transition lands in
    AuditLog automatically — no manual logging required at the call site."""

    def setUp(self):
        _setup_seed()
        self.org = Organization.objects.create(name='AuditApprCo', slug='audit-appr-co')
        self.user = User.objects.create_user('auditor', 'au@x.com', 'pw')

    def test_chain_creation_logs(self):
        from psa.models import PSAApproval
        chain = PSAApproval.create_chain(
            organization=self.org, kind='quote',
            object_type='psa.Quote', object_id=1,
            requested_by=self.user,
            stages=[{'request_comment': 's1'}, {'request_comment': 's2'}],
        )
        rows = AuditLog.objects.filter(
            object_type='psa.PSAApproval', object_id=chain[0].pk,
        )
        self.assertGreaterEqual(rows.count(), 1)
        self.assertIn('2-stage approval chain', rows.first().description)

    def test_decide_approve_logs_and_unblocks_next(self):
        from psa.models import PSAApproval
        chain = PSAApproval.create_chain(
            organization=self.org, kind='quote',
            object_type='psa.Quote', object_id=2,
            requested_by=self.user,
            stages=[{'request_comment': 's1'}, {'request_comment': 's2'}],
        )
        chain[0].decide(user=self.user, approved=True, comment='ok')
        # Stage 1: 1 create + 1 update = 2 rows.
        rows1 = AuditLog.objects.filter(
            object_type='psa.PSAApproval', object_id=chain[0].pk)
        self.assertGreaterEqual(rows1.count(), 2)
        # Stage 2: should have an Auto-unblocked entry.
        rows2 = AuditLog.objects.filter(
            object_type='psa.PSAApproval', object_id=chain[1].pk)
        self.assertGreaterEqual(rows2.count(), 1)
        self.assertTrue(any('Auto-unblocked' in r.description for r in rows2))

    def test_decide_deny_logs_cascade_cancellations(self):
        from psa.models import PSAApproval
        chain = PSAApproval.create_chain(
            organization=self.org, kind='quote',
            object_type='psa.Quote', object_id=3,
            requested_by=self.user,
            stages=[{'request_comment': 's1'},
                    {'request_comment': 's2'},
                    {'request_comment': 's3'}],
        )
        chain[0].decide(user=self.user, approved=False, comment='nope')
        # Each downstream stage should have an Auto-cancelled entry.
        for s in chain[1:]:
            rows = AuditLog.objects.filter(
                object_type='psa.PSAApproval', object_id=s.pk)
            self.assertTrue(any('Auto-cancelled' in r.description for r in rows),
                             f'Missing cascade log on stage {s.stage_index}')

    def test_history_method_returns_chronological(self):
        from psa.models import PSAApproval
        chain = PSAApproval.create_chain(
            organization=self.org, kind='quote',
            object_type='psa.Quote', object_id=4,
            requested_by=self.user,
            stages=[{'request_comment': 's1'}],
        )
        chain[0].decide(user=self.user, approved=True)
        history = chain[0].history()
        self.assertGreaterEqual(len(history), 2)
        # Newest-first: most recent entry should be the decision
        self.assertIn('Approved', history[0].description)


class WorkflowEnforcementTests(TestCase):
    """Phase 20 v7 (v3.17.275): block forward transitions while an
    approval chain is still open."""

    def setUp(self):
        _setup_seed()
        self.org = Organization.objects.create(name='WfeCo', slug='wfe-co')
        self.client_org = Organization.objects.create(name='WfeClient',
                                                       slug='wfe-client')
        self.user = User.objects.create_user('wfe-user', 'wu@x.com', 'pw')

    def _make_quote(self, total='1000'):
        from psa.models import Quote
        from decimal import Decimal as _D
        return Quote.objects.create(
            organization=self.org, client_org=self.client_org,
            title='Q', status='draft', total=_D(total),
        )

    def test_has_open_approvals_property(self):
        from psa.models import PSAApproval
        q = self._make_quote()
        self.assertFalse(q.has_open_approvals)
        PSAApproval.objects.create(
            organization=self.org, kind='quote',
            object_type='psa.Quote', object_id=q.pk, status='pending',
        )
        self.assertTrue(q.has_open_approvals)

    def test_mark_accepted_refuses_when_open_approval(self):
        from psa.models import PSAApproval
        q = self._make_quote()
        PSAApproval.objects.create(
            organization=self.org, kind='quote',
            object_type='psa.Quote', object_id=q.pk, status='pending',
        )
        with self.assertRaises(ValueError):
            q.mark_accepted(user=self.user, create_ticket=False)

    def test_mark_accepted_works_after_approval_decided(self):
        from psa.models import PSAApproval
        q = self._make_quote()
        appr = PSAApproval.objects.create(
            organization=self.org, kind='quote',
            object_type='psa.Quote', object_id=q.pk, status='pending',
        )
        appr.decide(user=self.user, approved=True)
        # Now should accept
        q.mark_accepted(user=self.user, create_ticket=False)
        q.refresh_from_db()
        self.assertEqual(q.status, 'accepted')

    def test_blocked_stage_also_counts_as_open(self):
        from psa.models import PSAApproval
        q = self._make_quote()
        PSAApproval.objects.create(
            organization=self.org, kind='quote',
            object_type='psa.Quote', object_id=q.pk, status='blocked',
        )
        self.assertTrue(q.has_open_approvals)

    def test_view_redirects_with_error_when_open(self):
        from psa.models import PSAApproval, Quote
        q = self._make_quote()
        PSAApproval.objects.create(
            organization=self.org, kind='quote',
            object_type='psa.Quote', object_id=q.pk, status='pending',
        )
        ss = SystemSetting.get_settings()
        ss.psa_enabled = True
        ss.save()
        Membership.objects.create(user=self.user, organization=self.org,
                                   role=Role.OWNER, is_active=True)
        c = Client()
        c.force_login(self.user)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()
        with override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False):
            r = c.post(f'/psa/quotes/{q.pk}/accept/')
        self.assertEqual(r.status_code, 302)
        q.refresh_from_db()
        # Quote must NOT have advanced
        self.assertEqual(q.status, 'draft')


class ChangeRequestTransitionTests(TestCase):
    """Phase 20 v8 (v3.17.276): ChangeRequest transition history."""

    def setUp(self):
        _setup_seed()
        self.org = Organization.objects.create(name='ChCo', slug='ch-co')
        self.user = User.objects.create_user('chu', 'ch@x.com', 'pw')

    def _make_change(self):
        from psa.models import (
            Ticket, TicketType, ChangeRequest, Queue, TicketStatus, TicketPriority,
        )
        # Need a change-type ticket since ChangeRequest is OneToOne to Ticket
        change_type, _ = TicketType.objects.get_or_create(
            slug='change', defaults={'name': 'Change', 'organization': self.org},
        )
        queue = Queue.objects.first()
        priority = TicketPriority.objects.first()
        status = TicketStatus.objects.filter(slug='new').first() or TicketStatus.objects.first()
        ticket = Ticket.objects.create(
            organization=self.org, subject='Change ticket',
            queue=queue, priority=priority, ticket_type=change_type,
            status=status,
        )
        # Auto-spawn signal already created the ChangeRequest; fetch it
        return ChangeRequest.objects.get(ticket=ticket)

    def test_transition_status_records_row(self):
        from psa.models import ChangeRequestTransition
        cr = self._make_change()
        cr.transition_status('pending_cab', by_user=self.user, note='ready')
        rows = ChangeRequestTransition.objects.filter(change_request=cr)
        self.assertEqual(rows.count(), 1)
        row = rows.first()
        self.assertEqual(row.from_status, 'draft')
        self.assertEqual(row.to_status, 'pending_cab')
        self.assertEqual(row.by_user, self.user)
        self.assertIn('ready', row.note)

    def test_transition_stamps_submitted_at(self):
        cr = self._make_change()
        self.assertIsNone(cr.submitted_at)
        cr.transition_status('pending_cab', by_user=self.user)
        cr.refresh_from_db()
        self.assertIsNotNone(cr.submitted_at)

    def test_transition_stamps_decided_at_on_approve(self):
        cr = self._make_change()
        cr.transition_status('pending_cab', by_user=self.user)
        cr.transition_status('approved', by_user=self.user)
        cr.refresh_from_db()
        self.assertIsNotNone(cr.decided_at)
        self.assertEqual(cr.decided_by, self.user)

    def test_transition_stamps_actual_start_on_implementing(self):
        cr = self._make_change()
        cr.transition_status('implementing', by_user=self.user)
        cr.refresh_from_db()
        self.assertIsNotNone(cr.actual_start)

    def test_transition_to_unknown_status_raises(self):
        cr = self._make_change()
        with self.assertRaises(ValueError):
            cr.transition_status('mars-bound', by_user=self.user)

    def test_no_op_transition_returns_none(self):
        cr = self._make_change()
        result = cr.transition_status(cr.implementation_status, by_user=self.user)
        self.assertIsNone(result)
        from psa.models import ChangeRequestTransition
        self.assertEqual(
            ChangeRequestTransition.objects.filter(change_request=cr).count(),
            0,
        )

    def test_signal_captures_direct_field_edit(self):
        """Direct ORM edits should still produce a transition row even
        if the caller didn't use transition_status()."""
        from psa.models import ChangeRequestTransition
        cr = self._make_change()
        cr.implementation_status = 'cancelled'
        cr.save()
        rows = ChangeRequestTransition.objects.filter(change_request=cr)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().from_status, 'draft')
        self.assertEqual(rows.first().to_status, 'cancelled')
        # by_user is None for signal-captured edits
        self.assertIsNone(rows.first().by_user)


class OperationalSignoffTests(TestCase):
    """Phase 20 v9 (v3.17.277): block transitions into
    `TicketStatus.requires_signoff=True` until the ticket is signed off."""

    def setUp(self):
        from psa.models import (
            TicketStatus, TicketPriority, TicketType, Queue,
        )
        _setup_seed()
        self.org = Organization.objects.create(name='SignCo', slug='sign-co')
        self.user = User.objects.create_user('signer', 'sn@x.com', 'pw')
        self.queue = Queue.objects.first()
        self.priority = TicketPriority.objects.first()
        self.ticket_type = TicketType.objects.first()
        self.status_open = TicketStatus.objects.filter(slug='new').first() or \
                           TicketStatus.objects.first()
        # Mark the 'closed' status as requiring sign-off
        self.status_closed, _ = TicketStatus.objects.update_or_create(
            slug='closed-signoff',
            defaults={
                'name': 'Closed (sign-off required)',
                'is_terminal': True, 'requires_signoff': True,
            },
        )

    def _make_ticket(self):
        from psa.models import Ticket
        return Ticket.objects.create(
            organization=self.org, subject='Needs sign-off',
            queue=self.queue, priority=self.priority,
            ticket_type=self.ticket_type, status=self.status_open,
        )

    def test_sign_off_method_stamps_fields(self):
        t = self._make_ticket()
        result = t.sign_off(by_user=self.user, note='looks good')
        self.assertTrue(result)
        t.refresh_from_db()
        self.assertIsNotNone(t.signed_off_at)
        self.assertEqual(t.signed_off_by, self.user)
        self.assertEqual(t.signoff_note, 'looks good')

    def test_double_sign_off_is_noop(self):
        t = self._make_ticket()
        t.sign_off(by_user=self.user)
        result = t.sign_off(by_user=self.user)
        self.assertFalse(result)

    def test_transition_blocked_without_signoff(self):
        from django.core.exceptions import ValidationError
        t = self._make_ticket()
        t.status = self.status_closed
        with self.assertRaises(ValidationError):
            t.save()

    def test_transition_allowed_after_signoff(self):
        t = self._make_ticket()
        t.sign_off(by_user=self.user, note='approved')
        t.status = self.status_closed
        t.save()  # should not raise
        t.refresh_from_db()
        self.assertEqual(t.status_id, self.status_closed.pk)

    def test_status_without_requires_signoff_unaffected(self):
        from psa.models import TicketStatus
        plain_terminal, _ = TicketStatus.objects.update_or_create(
            slug='resolved-plain',
            defaults={'name': 'Resolved (plain)', 'is_terminal': True},
        )
        t = self._make_ticket()
        t.status = plain_terminal
        t.save()  # no sign-off, but status doesn't require one
        t.refresh_from_db()
        self.assertEqual(t.status_id, plain_terminal.pk)


class MultiEntityInvoiceRoutingTests(TestCase):
    """Phase 27 v7 (v3.17.279): Invoice.target_connection routes pushes
    to a specific AccountingConnection when set."""

    def setUp(self):
        from integrations.models import AccountingConnection
        from psa.models import Invoice
        from datetime import date
        from decimal import Decimal as _D
        _setup_seed()
        self.org = Organization.objects.create(name='MEC', slug='mec-co')
        self.client_org = Organization.objects.create(name='MECC', slug='mec-cc')
        self.user = User.objects.create_user('me', 'me@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        ss = SystemSetting.get_settings()
        ss.psa_enabled = True
        ss.save()
        Membership.objects.create(user=self.user, organization=self.org,
                                   role=Role.OWNER, is_active=True)

        # Two AccountingConnections — one entity per book.
        self.conn_us = AccountingConnection.objects.create(
            organization=self.org, provider_type='quickbooks_online',
            name='US-Books', is_active=True, sync_enabled=True,
        )
        self.conn_uk = AccountingConnection.objects.create(
            organization=self.org, provider_type='xero',
            name='UK-Books', is_active=True, sync_enabled=True,
        )
        self.invoice = Invoice.objects.create(
            organization=self.org, client_org=self.client_org,
            title='Multi-entity test', invoice_date=date.today(),
            total=_D('500'),
        )

    def test_pinned_connection_used_when_set(self):
        from unittest import mock
        self.invoice.target_connection = self.conn_uk
        self.invoice.save(update_fields=['target_connection'])

        c = Client()
        c.force_login(self.user)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()

        captured_conn = {}

        def fake_get_provider(conn):
            captured_conn['name'] = conn.name
            mp = mock.MagicMock()
            mp.push_invoice.return_value = {'success': True, 'invoice_id': 'X-1'}
            return mp

        with override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False), \
             mock.patch('integrations.providers.accounting.get_accounting_provider',
                         side_effect=fake_get_provider):
            r = c.post(f'/psa/invoices/{self.invoice.pk}/push/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(captured_conn['name'], 'UK-Books')

    def test_unpinned_falls_back_to_first_sync_enabled(self):
        from unittest import mock
        # invoice.target_connection is None
        c = Client()
        c.force_login(self.user)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()

        captured_conn = {}

        def fake_get_provider(conn):
            captured_conn['name'] = conn.name
            mp = mock.MagicMock()
            mp.push_invoice.return_value = {'success': True, 'invoice_id': 'X-1'}
            return mp

        with override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False), \
             mock.patch('integrations.providers.accounting.get_accounting_provider',
                         side_effect=fake_get_provider):
            r = c.post(f'/psa/invoices/{self.invoice.pk}/push/')
        self.assertEqual(r.status_code, 302)
        # Should pick the first sync-enabled connection on the org.
        self.assertIn(captured_conn['name'], ('US-Books', 'UK-Books'))

    def test_pinned_inactive_connection_blocks_push(self):
        # Disable the pinned connection and confirm push refuses
        self.invoice.target_connection = self.conn_uk
        self.invoice.save(update_fields=['target_connection'])
        self.conn_uk.is_active = False
        self.conn_uk.save()

        c = Client()
        c.force_login(self.user)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()
        with override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False):
            r = c.post(f'/psa/invoices/{self.invoice.pk}/push/')
        self.assertEqual(r.status_code, 302)
        # Invoice should NOT have been pushed (no accounting_external_id)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.accounting_external_id, '')
