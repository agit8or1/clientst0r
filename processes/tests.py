"""
Baseline test coverage for the processes/ app.

Workflow engine — defines reusable Process templates with sequential
stages, executed against tickets. Bug here = silent workflow run
failure (a tech "completes" a runbook but a stage didn't actually
record). Touches PSA tickets via `ProcessExecution.native_psa_ticket`.

Coverage areas:
  * `Process` model — slug auto-generation, OrganizationManager,
    `is_global` vs org-specific.
  * `ProcessStage` ordering + linked-entity contract.
  * `ProcessExecution` lifecycle — `completion_percentage` math,
    `is_overdue` property.
  * `ProcessStageCompletion` unique-together (execution, stage)
    constraint — guards against double-completion of one stage.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from core.models import Organization
from processes.models import (
    Process,
    ProcessExecution,
    ProcessStage,
    ProcessStageCompletion,
)


# ---------------------------------------------------------------------------
# Process model
# ---------------------------------------------------------------------------

class ProcessModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='ProcCo', slug='proc-co')
        cls.user = User.objects.create_user('proc-user', email='p@x.com', password='pw')

    def test_slug_auto_generated_from_title(self):
        p = Process.objects.create(
            organization=self.org, title='Onboarding New Hire',
            created_by=self.user,
        )
        self.assertEqual(p.slug, 'onboarding-new-hire')

    def test_explicit_slug_preserved(self):
        p = Process.objects.create(
            organization=self.org, title='Foo Bar', slug='custom-slug',
            created_by=self.user,
        )
        self.assertEqual(p.slug, 'custom-slug')

    def test_str_marks_global_and_template_prefixes(self):
        normal = Process.objects.create(
            organization=self.org, title='Normal',
            created_by=self.user,
        )
        glob = Process.objects.create(
            organization=self.org, title='Global one', slug='g',
            is_global=True, created_by=self.user,
        )
        templ = Process.objects.create(
            organization=self.org, title='Template one', slug='t',
            is_template=True, created_by=self.user,
        )
        self.assertNotIn('[GLOBAL]', str(normal))
        self.assertIn('[GLOBAL]', str(glob))
        self.assertIn('[TEMPLATE]', str(templ))

    def test_unique_slug_per_organization(self):
        Process.objects.create(
            organization=self.org, title='X', slug='x',
            created_by=self.user,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Process.objects.create(
                organization=self.org, title='X-dup', slug='x',
                created_by=self.user,
            )

    def test_same_slug_in_different_org_allowed(self):
        Process.objects.create(
            organization=self.org, title='X', slug='x',
            created_by=self.user,
        )
        org_b = Organization.objects.create(name='Other', slug='proc-other')
        # Same slug in different org — must NOT raise.
        Process.objects.create(
            organization=org_b, title='X', slug='x',
            created_by=self.user,
        )

    def test_for_organization_filtering(self):
        org_b = Organization.objects.create(name='ProcOther', slug='proc-other2')
        Process.objects.create(
            organization=self.org, title='A', slug='a',
            created_by=self.user,
        )
        Process.objects.create(
            organization=org_b, title='B', slug='b',
            created_by=self.user,
        )
        for_a = list(Process.objects.for_organization(self.org))
        self.assertEqual(len(for_a), 1)
        self.assertEqual(for_a[0].title, 'A')


# ---------------------------------------------------------------------------
# ProcessStage
# ---------------------------------------------------------------------------

class ProcessStageOrderingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='StageCo', slug='stage-co')
        cls.user = User.objects.create_user('stage-user', email='s@x.com', password='pw')
        cls.process = Process.objects.create(
            organization=cls.org, title='Multi-step', slug='multi-step',
            created_by=cls.user,
        )

    def test_stages_default_to_order_zero(self):
        s = ProcessStage.objects.create(process=self.process, title='step')
        self.assertEqual(s.order, 0)

    def test_explicit_order_preserved(self):
        ProcessStage.objects.create(process=self.process, title='first', order=10)
        ProcessStage.objects.create(process=self.process, title='second', order=20)
        ProcessStage.objects.create(process=self.process, title='middle', order=15)
        ordered = list(self.process.stages.order_by('order').values_list('title', flat=True))
        self.assertEqual(ordered, ['first', 'middle', 'second'])


# ---------------------------------------------------------------------------
# ProcessExecution lifecycle
# ---------------------------------------------------------------------------

class ProcessExecutionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='ExecCo', slug='exec-co')
        cls.user = User.objects.create_user('exec-user', email='e@x.com', password='pw')
        cls.process = Process.objects.create(
            organization=cls.org, title='Three-step', slug='three-step',
            created_by=cls.user,
        )
        cls.stage1 = ProcessStage.objects.create(process=cls.process, title='1', order=1)
        cls.stage2 = ProcessStage.objects.create(process=cls.process, title='2', order=2)
        cls.stage3 = ProcessStage.objects.create(process=cls.process, title='3', order=3)

    def _execution(self):
        return ProcessExecution.objects.create(
            process=self.process, organization=self.org,
            assigned_to=self.user, started_by=self.user,
        )

    def test_execution_starts_not_started(self):
        e = self._execution()
        self.assertEqual(e.status, 'not_started')

    def test_completion_percentage_is_zero_when_no_stages_completed(self):
        e = self._execution()
        self.assertEqual(e.completion_percentage, 0)

    def test_completion_percentage_one_third_when_one_of_three(self):
        e = self._execution()
        ProcessStageCompletion.objects.create(
            execution=e, stage=self.stage1, is_completed=True, completed_by=self.user,
        )
        self.assertEqual(e.completion_percentage, 33)

    def test_completion_percentage_full_when_all_done(self):
        e = self._execution()
        for stage in (self.stage1, self.stage2, self.stage3):
            ProcessStageCompletion.objects.create(
                execution=e, stage=stage, is_completed=True, completed_by=self.user,
            )
        self.assertEqual(e.completion_percentage, 100)

    def test_completion_percentage_handles_zero_stages(self):
        # Process with no stages at all — must not divide by zero.
        empty_proc = Process.objects.create(
            organization=self.org, title='Empty', slug='empty',
            created_by=self.user,
        )
        e = ProcessExecution.objects.create(
            process=empty_proc, organization=self.org,
            assigned_to=self.user, started_by=self.user,
        )
        self.assertEqual(e.completion_percentage, 0)

    def test_is_overdue_true_when_past_due_and_not_completed(self):
        e = self._execution()
        e.due_date = timezone.now() - timedelta(hours=1)
        e.save()
        self.assertTrue(e.is_overdue)

    def test_is_overdue_false_when_completed_even_if_past_due(self):
        e = self._execution()
        e.due_date = timezone.now() - timedelta(hours=1)
        e.status = 'completed'
        e.save()
        self.assertFalse(e.is_overdue)

    def test_is_overdue_false_when_no_due_date(self):
        e = self._execution()
        # No due_date set — the property must short-circuit, not raise on
        # `None > timezone.now()`.
        self.assertFalse(e.is_overdue)


# ---------------------------------------------------------------------------
# ProcessStageCompletion unique constraint — load-bearing for completion %
# ---------------------------------------------------------------------------

class ProcessStageCompletionConstraintTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='CompCo', slug='comp-co')
        cls.user = User.objects.create_user('comp-user', email='c@x.com', password='pw')
        cls.process = Process.objects.create(
            organization=cls.org, title='P', slug='p',
            created_by=cls.user,
        )
        cls.stage = ProcessStage.objects.create(process=cls.process, title='S', order=1)
        cls.execution = ProcessExecution.objects.create(
            process=cls.process, organization=cls.org,
            assigned_to=cls.user, started_by=cls.user,
        )

    def test_same_stage_in_same_execution_rejected(self):
        ProcessStageCompletion.objects.create(
            execution=self.execution, stage=self.stage, is_completed=True,
            completed_by=self.user,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProcessStageCompletion.objects.create(
                execution=self.execution, stage=self.stage, is_completed=True,
                completed_by=self.user,
            )

    def test_str_marks_completed_with_check(self):
        c_done = ProcessStageCompletion.objects.create(
            execution=self.execution, stage=self.stage, is_completed=True,
            completed_by=self.user,
        )
        self.assertIn('✓', str(c_done))

    def test_str_marks_uncompleted_with_circle(self):
        # Different stage so the unique-together doesn't fire.
        stage2 = ProcessStage.objects.create(process=self.process, title='S2', order=2)
        c_open = ProcessStageCompletion.objects.create(
            execution=self.execution, stage=stage2, is_completed=False,
        )
        self.assertIn('○', str(c_open))


# ---------------------------------------------------------------------------
# Phase 38 — Runbook clone-template + spawn-ticket
# ---------------------------------------------------------------------------

from django.conf import settings as django_settings
from django.test import Client, override_settings
from accounts.models import Membership, Role


_TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ProcessCloneTemplateTests(TestCase):
    """Phase 38: clone an is_template=True Process into a runnable copy."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='RunbookCo', slug='rb-co')
        cls.user = User.objects.create_user('rb-user', 'rb@x.com', 'pw')
        Membership.objects.create(
            user=cls.user, organization=cls.org, role=Role.OWNER, is_active=True,
        )
        cls.tpl = Process.objects.create(
            organization=cls.org, title='Client Onboarding Template',
            description='Standard new-client onboarding',
            is_template=True, category='client_onboarding',
            created_by=cls.user,
        )
        ProcessStage.objects.create(process=cls.tpl, title='Provision M365', order=1,
                                     description='Create accounts')
        ProcessStage.objects.create(process=cls.tpl, title='Set up vault', order=2,
                                     description='Add credentials')
        ProcessStage.objects.create(process=cls.tpl, title='Schedule kickoff', order=3,
                                     description='Send invite')

    def _login(self, c):
        c.force_login(self.user)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()

    def test_clone_creates_new_process_with_all_stages(self):
        c = Client()
        self._login(c)
        before = Process.objects.count()
        r = c.post(f'/processes/{self.tpl.slug}/clone-template/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Process.objects.count(), before + 1)
        clone = Process.objects.exclude(pk=self.tpl.pk).get(organization=self.org)
        self.assertFalse(clone.is_template)
        self.assertIn('Client Onboarding Template', clone.title)
        self.assertEqual(clone.category, 'client_onboarding')
        self.assertEqual(clone.stages.count(), 3)
        titles = list(clone.stages.order_by('order').values_list('title', flat=True))
        self.assertEqual(titles, ['Provision M365', 'Set up vault', 'Schedule kickoff'])

    def test_clone_rejects_non_template_source(self):
        # Create a NON-template Process and try to clone it.
        non_tpl = Process.objects.create(
            organization=self.org, title='Ad-hoc workflow',
            is_template=False, created_by=self.user,
        )
        c = Client()
        self._login(c)
        before = Process.objects.count()
        r = c.post(f'/processes/{non_tpl.slug}/clone-template/')
        self.assertEqual(r.status_code, 302)
        # No new Process created.
        self.assertEqual(Process.objects.count(), before)

    def test_new_categories_accept_client_onboarding(self):
        # The Process model's CATEGORY_CHOICES gained client_*
        # values in v3.17.223 — make sure they save without ValidationError.
        for cat in ('client_onboarding', 'client_offboarding', 'client_termination'):
            p = Process.objects.create(
                organization=self.org, title=f'Cat {cat}',
                category=cat, created_by=self.user,
                last_modified_by=self.user,
            )
            p.full_clean()
            self.assertEqual(p.category, cat)


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ProcessStageSpawnTicketTests(TestCase):
    """Phase 38: spawn a PSA Ticket from a runbook stage in a running execution."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command('psa_seed_defaults', verbosity=0)
        cls.org = Organization.objects.create(name='SpawnCo', slug='spawn-co')
        cls.user = User.objects.create_user('spawn-user', 'sp@x.com', 'pw')
        Membership.objects.create(
            user=cls.user, organization=cls.org, role=Role.OWNER, is_active=True,
        )
        cls.process = Process.objects.create(
            organization=cls.org, title='Onboard',
            category='client_onboarding', created_by=cls.user,
        )
        cls.stage = ProcessStage.objects.create(
            process=cls.process, title='Provision endpoint',
            description='Deploy laptop + image', order=1,
        )
        cls.execution = ProcessExecution.objects.create(
            process=cls.process, organization=cls.org,
            assigned_to=cls.user, status='in_progress',
        )

    def _login(self, c):
        c.force_login(self.user)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()

    def test_spawn_creates_ticket_and_links_completion(self):
        from psa.models import Ticket
        c = Client()
        self._login(c)
        before = Ticket.objects.filter(organization=self.org).count()
        r = c.post(
            f'/processes/execution/{self.execution.pk}/stage/{self.stage.pk}/spawn-ticket/'
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Ticket.objects.filter(organization=self.org).count(), before + 1)
        completion = ProcessStageCompletion.objects.get(
            execution=self.execution, stage=self.stage,
        )
        self.assertIsNotNone(completion.spawned_ticket)
        self.assertIn('Provision endpoint', completion.spawned_ticket.subject)

    def test_spawn_is_idempotent(self):
        # First call creates; second call must NOT create another ticket.
        from psa.models import Ticket
        c = Client()
        self._login(c)
        c.post(f'/processes/execution/{self.execution.pk}/stage/{self.stage.pk}/spawn-ticket/')
        first_count = Ticket.objects.filter(organization=self.org).count()
        c.post(f'/processes/execution/{self.execution.pk}/stage/{self.stage.pk}/spawn-ticket/')
        second_count = Ticket.objects.filter(organization=self.org).count()
        self.assertEqual(first_count, second_count)

    def test_spawn_rejects_get(self):
        c = Client()
        self._login(c)
        r = c.get(f'/processes/execution/{self.execution.pk}/stage/{self.stage.pk}/spawn-ticket/')
        self.assertEqual(r.status_code, 405)


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RunbookDashboardTests(TestCase):
    """Phase 38 v2 (v3.17.227): per-org runbook completion dashboard."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='DashCo', slug='dash-co')
        cls.outsider_org = Organization.objects.create(name='OutsideCo', slug='dash-out')
        cls.user = User.objects.create_user('dash-user', 'd@x.com', 'pw')
        Membership.objects.create(
            user=cls.user, organization=cls.org, role=Role.OWNER, is_active=True,
        )
        cls.staff = User.objects.create_user('dash-staff', 's@x.com', 'pw',
                                              is_superuser=True, is_staff=True)
        # Two processes, two executions, with stages partially completed.
        cls.proc_a = Process.objects.create(
            organization=cls.org, title='Onboarding A',
            category='client_onboarding', created_by=cls.user,
            last_modified_by=cls.user,
        )
        cls.proc_b = Process.objects.create(
            organization=cls.org, title='Termination B',
            category='client_termination', created_by=cls.user,
            last_modified_by=cls.user,
        )
        ProcessStage.objects.create(process=cls.proc_a, title='S1', order=1)
        ProcessStage.objects.create(process=cls.proc_a, title='S2', order=2)
        ProcessStage.objects.create(process=cls.proc_b, title='S1', order=1)
        cls.exec_a = ProcessExecution.objects.create(
            process=cls.proc_a, organization=cls.org,
            assigned_to=cls.user, status='in_progress',
        )
        cls.exec_b = ProcessExecution.objects.create(
            process=cls.proc_b, organization=cls.org,
            assigned_to=cls.user, status='not_started',
        )
        # Mark one of exec_a's stages complete so completion_percentage = 50.
        ProcessStageCompletion.objects.create(
            execution=cls.exec_a, stage=cls.proc_a.stages.order_by('order').first(),
            is_completed=True, completed_by=cls.user,
        )

    def _login(self, c, user, org=None):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        if org is not None:
            s['current_organization_id'] = org.id
        s.save()

    def test_dashboard_shows_active_executions_grouped_by_category(self):
        from django.test import Client
        c = Client()
        self._login(c, self.user, self.org)
        r = c.get('/processes/dashboard/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Onboarding A')
        self.assertContains(r, 'Termination B')
        self.assertContains(r, 'Client Onboarding')
        self.assertContains(r, 'Client Termination')

    def test_dashboard_overall_completion_aggregates(self):
        from django.test import Client
        c = Client()
        self._login(c, self.user, self.org)
        r = c.get('/processes/dashboard/')
        ctx = r.context
        # 3 stages total (2 in proc_a + 1 in proc_b); 1 completed → 33.3%
        self.assertEqual(ctx['total_stages'], 3)
        self.assertEqual(ctx['completed_stages'], 1)
        self.assertAlmostEqual(ctx['overall_pct'], 33.3, places=1)
        self.assertEqual(ctx['total_executions'], 2)

    def test_dashboard_excludes_cancelled_and_failed(self):
        from django.test import Client
        # Mark exec_b as cancelled — should disappear from the dashboard.
        self.exec_b.status = 'cancelled'
        self.exec_b.save(update_fields=['status'])
        c = Client()
        self._login(c, self.user, self.org)
        r = c.get('/processes/dashboard/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Onboarding A')
        self.assertNotContains(r, 'Termination B')

    def test_dashboard_org_url_blocks_non_member(self):
        from django.test import Client
        c = Client()
        # Non-staff user is NOT a member of outsider_org → 404.
        self._login(c, self.user, self.org)
        r = c.get(f'/processes/dashboard/{self.outsider_org.id}/')
        self.assertEqual(r.status_code, 404)

    def test_dashboard_org_url_allows_staff(self):
        from django.test import Client
        c = Client()
        self._login(c, self.staff, self.org)
        r = c.get(f'/processes/dashboard/{self.outsider_org.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'OutsideCo')


# ---------------------------------------------------------------------------
# v3.17.567 — the PSA note posted when the last stage of a workflow completes
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class StageCompletePSANoteTests(TestCase):
    """
    Completing the final stage of a PSA-linked execution posts a summary note to
    the ticket. The view used to discard the result of that call and log
    "completed execution and updated PSA ticket X" unconditionally, so the audit
    trail asserted the note had landed whether or not one ever did — and nothing
    reached the tech either.
    """

    @classmethod
    def setUpTestData(cls):
        from integrations.models import PSAConnection, PSATicket

        cls.org = Organization.objects.create(name='NoteCo', slug='note-co')
        cls.user = User.objects.create_user('note-user', 'n@x.com', 'pw')
        Membership.objects.create(
            user=cls.user, organization=cls.org, role=Role.OWNER, is_active=True,
        )
        cls.proc = Process.objects.create(
            organization=cls.org, title='Onboarding', created_by=cls.user,
        )
        cls.stage = ProcessStage.objects.create(
            process=cls.proc, title='Provision M365', order=1,
        )
        conn = PSAConnection(
            organization=cls.org, provider_type='connectwise_manage',
            name='CW', base_url='https://psa.example.com',
        )
        conn.set_credentials({'company_id': 'a', 'public_key': 'b', 'private_key': 'c'})
        conn.save()
        cls.ticket = PSATicket.objects.create(
            organization=cls.org, connection=conn,
            external_id='4242', ticket_number='T-4242', subject='Onboard',
        )

    def setUp(self):
        self.execution = ProcessExecution.objects.create(
            organization=self.org, process=self.proc, status='in_progress',
            psa_ticket=self.ticket, assigned_to=self.user, started_by=self.user,
        )
        self.completion = ProcessStageCompletion.objects.create(
            execution=self.execution, stage=self.stage,
        )
        self.client = Client()
        self.client.force_login(self.user)
        s = self.client.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()

    def _complete(self):
        return self.client.post(f'/processes/completion/{self.completion.pk}/complete/')

    def _psa_log(self):
        return self.execution.audit_logs.filter(
            action_type='execution_completed', description__contains='PSA ticket',
        ).first()

    def test_successful_note_is_logged_as_an_update(self):
        from unittest import mock
        from integrations.psa_manager import PSANoteResult

        with mock.patch('integrations.psa_manager.PSAManager.add_ticket_note',
                        return_value=PSANoteResult(PSANoteResult.OK, 'posted')):
            r = self._complete()

        self.assertEqual(r.status_code, 200)
        self.assertNotIn('psa_note_error', r.json())
        log = self._psa_log()
        self.assertIsNotNone(log)
        self.assertIn('updated PSA ticket T-4242', log.description)
        self.assertTrue(log.new_value['psa_note_posted'])

    def test_failed_note_is_not_logged_as_an_update(self):
        from unittest import mock
        from integrations.psa_manager import PSANoteResult

        with mock.patch('integrations.psa_manager.PSAManager.add_ticket_note',
                        return_value=PSANoteResult(PSANoteResult.FAILED, 'connection refused')):
            r = self._complete()

        self.assertEqual(r.status_code, 200)
        log = self._psa_log()
        self.assertIsNotNone(log)
        self.assertIn('NOT posted', log.description)
        self.assertIn('connection refused', log.description)
        self.assertFalse(log.new_value['psa_note_posted'])

    def test_failed_note_is_reported_to_the_tech(self):
        from unittest import mock
        from integrations.psa_manager import PSANoteResult

        with mock.patch('integrations.psa_manager.PSAManager.add_ticket_note',
                        return_value=PSANoteResult(PSANoteResult.UNSUPPORTED, 'no note API')):
            r = self._complete()

        body = r.json()
        self.assertTrue(body['success'])
        self.assertFalse(body['psa_note_posted'])
        self.assertIn('no note API', body['psa_note_error'])

    def test_stage_still_completes_when_the_psa_call_raises(self):
        from unittest import mock

        with mock.patch('integrations.psa_manager.PSAManager.add_ticket_note',
                        side_effect=Exception('boom')):
            r = self._complete()

        self.assertEqual(r.status_code, 200)
        self.completion.refresh_from_db()
        self.execution.refresh_from_db()
        self.assertTrue(self.completion.is_completed)
        self.assertEqual(self.execution.status, 'completed')
        self.assertIn('boom', r.json()['psa_note_error'])

    def test_execution_without_a_psa_ticket_reports_nothing(self):
        self.execution.psa_ticket = None
        self.execution.save(update_fields=['psa_ticket'])
        r = self._complete()
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('psa_note_error', r.json())
