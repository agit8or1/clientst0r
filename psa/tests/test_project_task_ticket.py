"""
Phase 35.4 (v3.17.550) — spawning a ticket from a project task.

A task and a ticket are not the same thing, and this does not merge them: the
task stays the unit of planning, the ticket becomes the unit of work that time,
SLA and comments hang off.
"""
from datetime import date, timedelta

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from core.models import Organization, SystemSetting
from psa.models import Project, ProjectTask, Ticket
from psa.tests._base import _enable_psa_for, _setup_seed

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ProjectTaskToTicketTests(TestCase):
    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        self.org = Organization.objects.create(name='SpawnCo', slug='spawn-co')
        _enable_psa_for(self.org)
        self.user = User.objects.create_superuser(
            'spawnadmin', 'sp@example.com', 'hunter2xyz')
        self.tech = User.objects.create_user('tech', 't@example.com', 'pw')
        self.client = Client()
        self.client.force_login(self.user)
        session = self.client.session
        session['current_organization_id'] = self.org.id
        session.save()
        self.project = Project.objects.create(
            organization=self.org, name='Migration', client_org=self.org)
        self.task = ProjectTask.objects.create(
            project=self.project, title='Provision tenant',
            description='Stand up the new tenant')

    def _spawn(self, task=None):
        task = task or self.task
        return self.client.post(f'/psa/project-task/{task.pk}/to-ticket/')

    def test_creates_a_ticket(self):
        self._spawn()
        self.assertEqual(Ticket.objects.count(), 1)

    def test_ticket_carries_the_task_title_and_description(self):
        self._spawn()
        ticket = Ticket.objects.get()
        self.assertEqual(ticket.subject, 'Provision tenant')
        self.assertEqual(ticket.description, 'Stand up the new tenant')

    def test_ticket_is_attached_to_the_project(self):
        """Otherwise time logged on it would not count towards the project's
        actuals, which is the entire reason to spawn it."""
        self._spawn()
        self.assertEqual(Ticket.objects.get().project, self.project)

    def test_task_links_back_to_the_ticket(self):
        self._spawn()
        self.task.refresh_from_db()
        self.assertEqual(self.task.related_ticket, Ticket.objects.get())

    def test_assignee_carries_over(self):
        self.task.assigned_to = self.tech
        self.task.save()
        self._spawn()
        self.assertEqual(Ticket.objects.get().assigned_to, self.tech)

    def test_due_date_becomes_a_resolution_target(self):
        """A task due Friday whose ticket has no date drops off every SLA
        view."""
        self.task.due_date = date.today() + timedelta(days=5)
        self.task.save()
        self._spawn()
        ticket = Ticket.objects.get()
        self.assertIsNotNone(ticket.resolution_due_at)
        self.assertEqual(ticket.resolution_due_at.date(), self.task.due_date)

    def test_no_due_date_means_no_resolution_target(self):
        self._spawn()
        self.assertIsNone(Ticket.objects.get().resolution_due_at)

    def test_spawning_twice_does_not_create_a_second_ticket(self):
        """Two tickets would split the time entries and quietly break the
        project's actual-hours figure."""
        self._spawn()
        self._spawn()
        self.assertEqual(Ticket.objects.count(), 1)

    def test_get_does_not_create_anything(self):
        self.client.get(f'/psa/project-task/{self.task.pk}/to-ticket/')
        self.assertEqual(Ticket.objects.count(), 0)

    def test_another_organizations_task_is_not_reachable(self):
        other_org = Organization.objects.create(name='NotUs', slug='not-us-spawn')
        _enable_psa_for(other_org)
        foreign_project = Project.objects.create(
            organization=other_org, name='Theirs')
        foreign_task = ProjectTask.objects.create(
            project=foreign_project, title='Theirs')
        resp = self._spawn(foreign_task)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_time_on_the_spawned_ticket_counts_towards_the_project(self):
        from django.utils import timezone
        from psa.models import TicketTimeEntry
        self._spawn()
        ticket = Ticket.objects.get()
        TicketTimeEntry.objects.create(
            ticket=ticket, user=self.user,
            started_at=timezone.now() - timedelta(minutes=90),
            ended_at=timezone.now(), duration_minutes=90, is_billable=True)
        self.assertEqual(float(self.project.actual_hours()), 1.5)
