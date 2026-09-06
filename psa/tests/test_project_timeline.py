"""
Phase 35.5 (v3.17.554) — project timeline, scheduling and dependencies.

The dependency tests carry the weight here: a cycle makes "what can start now"
unanswerable and sends any scheduling walk into an infinite loop, so it has to be
refused at the point of creation rather than defended against everywhere after.
"""
from datetime import date, timedelta

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from core.models import Organization, SystemSetting
from psa.models import Project, ProjectTask
from psa.tests._base import _enable_psa_for, _setup_seed

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


class TaskSchedulingTests(TestCase):
    def setUp(self):
        _setup_seed()
        self.org = Organization.objects.create(name='PlanCo', slug='plan-co')
        self.project = Project.objects.create(organization=self.org, name='Rollout')

    def _task(self, title, start=None, due=None, **kw):
        return ProjectTask.objects.create(
            project=self.project, title=title,
            start_date=start, due_date=due, **kw)

    def test_a_task_with_both_dates_spans_them(self):
        t = self._task('Build', date(2026, 3, 2), date(2026, 3, 6))
        self.assertEqual(t.bar_start, date(2026, 3, 2))
        self.assertEqual(t.bar_end, date(2026, 3, 6))

    def test_a_task_with_only_a_due_date_is_a_single_day_marker(self):
        """A deadline-only task must still appear rather than vanish from the
        plan."""
        t = self._task('Go live', due=date(2026, 3, 6))
        self.assertEqual(t.bar_start, date(2026, 3, 6))
        self.assertEqual(t.bar_end, date(2026, 3, 6))
        self.assertTrue(t.is_scheduled)

    def test_a_task_with_only_a_start_date_works_too(self):
        t = self._task('Kickoff', start=date(2026, 3, 2))
        self.assertEqual(t.bar_start, t.bar_end)

    def test_a_task_with_no_dates_is_not_scheduled(self):
        self.assertFalse(self._task('Someday').is_scheduled)


class TaskDependencyTests(TestCase):
    def setUp(self):
        _setup_seed()
        self.org = Organization.objects.create(name='DepCo', slug='dep-co')
        self.project = Project.objects.create(organization=self.org, name='Rollout')
        self.a = ProjectTask.objects.create(project=self.project, title='A')
        self.b = ProjectTask.objects.create(project=self.project, title='B')
        self.c = ProjectTask.objects.create(project=self.project, title='C')

    def test_a_simple_dependency_is_added(self):
        self.assertTrue(self.b.add_dependency(self.a))
        self.assertIn(self.a, self.b.depends_on.all())

    def test_dependencies_are_not_symmetrical(self):
        """"B depends on A" says nothing about A."""
        self.b.add_dependency(self.a)
        self.assertEqual(list(self.a.depends_on.all()), [])

    def test_a_task_cannot_depend_on_itself(self):
        self.assertFalse(self.a.add_dependency(self.a))
        self.assertEqual(list(self.a.depends_on.all()), [])

    def test_a_direct_cycle_is_refused(self):
        self.b.add_dependency(self.a)
        self.assertFalse(self.a.add_dependency(self.b))
        self.assertEqual(list(self.a.depends_on.all()), [])

    def test_an_indirect_cycle_is_refused(self):
        """A ← B ← C, then C ← A would close the loop."""
        self.b.add_dependency(self.a)
        self.c.add_dependency(self.b)
        self.assertFalse(self.a.add_dependency(self.c))

    def test_a_long_chain_is_still_allowed(self):
        """Depth is not a cycle."""
        self.b.add_dependency(self.a)
        self.c.add_dependency(self.b)
        d = ProjectTask.objects.create(project=self.project, title='D')
        self.assertTrue(d.add_dependency(self.c))

    def test_a_diamond_is_allowed(self):
        """B and C both wait for A, D waits for both. Not a cycle."""
        self.b.add_dependency(self.a)
        self.c.add_dependency(self.a)
        d = ProjectTask.objects.create(project=self.project, title='D')
        self.assertTrue(d.add_dependency(self.b))
        self.assertTrue(d.add_dependency(self.c))

    def test_cross_project_dependencies_are_refused(self):
        """Nothing else in the model supports one project's timeline depending
        on another's."""
        other_project = Project.objects.create(
            organization=self.org, name='Different')
        foreign = ProjectTask.objects.create(
            project=other_project, title='Elsewhere')
        self.assertFalse(self.a.add_dependency(foreign))

    def test_blocked_while_a_dependency_is_unfinished(self):
        self.b.add_dependency(self.a)
        self.assertTrue(self.b.is_blocked)
        self.assertEqual(self.b.blocking_dependencies, [self.a])

    def test_not_blocked_once_dependencies_are_done(self):
        self.a.status = 'done'
        self.a.save(update_fields=['status'])
        self.b.add_dependency(self.a)
        self.assertFalse(self.b.is_blocked)

    def test_a_task_with_no_dependencies_is_not_blocked(self):
        self.assertFalse(self.a.is_blocked)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TimelineViewTests(TestCase):
    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        self.org = Organization.objects.create(name='TlCo', slug='tl-co')
        _enable_psa_for(self.org)
        self.user = User.objects.create_superuser(
            'tladmin', 'tl@example.com', 'hunter2xyz')
        self.client = Client()
        self.client.force_login(self.user)
        session = self.client.session
        session['current_organization_id'] = self.org.id
        session.save()
        self.project = Project.objects.create(organization=self.org, name='Rollout')

    def _task(self, title, start=None, due=None, **kw):
        return ProjectTask.objects.create(
            project=self.project, title=title,
            start_date=start, due_date=due, **kw)

    def test_timeline_renders(self):
        self._task('Build', date(2026, 3, 2), date(2026, 3, 6))
        resp = self.client.get(f'/psa/projects/{self.project.pk}/timeline/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Build')

    def test_bars_are_positioned_across_the_span(self):
        self._task('First', date(2026, 3, 1), date(2026, 3, 5))
        self._task('Second', date(2026, 3, 6), date(2026, 3, 10))
        resp = self.client.get(f'/psa/projects/{self.project.pk}/timeline/')
        rows = resp.context['rows']
        self.assertEqual(rows[0]['left_percent'], 0.0)
        self.assertGreater(rows[1]['left_percent'], rows[0]['left_percent'])

    def test_a_single_day_project_does_not_divide_by_zero(self):
        self._task('One day', date(2026, 3, 2), date(2026, 3, 2))
        resp = self.client.get(f'/psa/projects/{self.project.pk}/timeline/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['days'], 1)

    def test_unscheduled_tasks_are_listed_not_hidden(self):
        """A task missing from a plan is easy to forget entirely."""
        self._task('Scheduled', date(2026, 3, 2), date(2026, 3, 3))
        self._task('No dates')
        resp = self.client.get(f'/psa/projects/{self.project.pk}/timeline/')
        self.assertEqual(
            [t.title for t in resp.context['unscheduled']], ['No dates'])

    def test_a_project_with_nothing_scheduled_still_renders(self):
        self._task('No dates')
        resp = self.client.get(f'/psa/projects/{self.project.pk}/timeline/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['rows'], [])

    def test_edges_are_emitted_between_row_positions(self):
        a = self._task('A', date(2026, 3, 1), date(2026, 3, 3))
        b = self._task('B', date(2026, 3, 4), date(2026, 3, 6))
        b.add_dependency(a)
        resp = self.client.get(f'/psa/projects/{self.project.pk}/timeline/')
        self.assertEqual(resp.context['edges'], [{'from': 0, 'to': 1}])

    def test_an_edge_to_an_unscheduled_task_is_dropped(self):
        """Drawing an arrow to nothing is worse than drawing no arrow."""
        ghost = self._task('No dates')
        b = self._task('B', date(2026, 3, 4), date(2026, 3, 6))
        b.add_dependency(ghost)
        resp = self.client.get(f'/psa/projects/{self.project.pk}/timeline/')
        self.assertEqual(resp.context['edges'], [])

    def test_reschedule_moves_the_task(self):
        t = self._task('Build', date(2026, 3, 2), date(2026, 3, 6))
        self.client.post(f'/psa/project-task/{t.pk}/reschedule/', {
            'start_date': '2026-03-09', 'due_date': '2026-03-13'})
        t.refresh_from_db()
        self.assertEqual(t.start_date, date(2026, 3, 9))
        self.assertEqual(t.due_date, date(2026, 3, 13))

    def test_due_before_start_is_refused(self):
        t = self._task('Build', date(2026, 3, 2), date(2026, 3, 6))
        self.client.post(f'/psa/project-task/{t.pk}/reschedule/', {
            'start_date': '2026-03-09', 'due_date': '2026-03-01'})
        t.refresh_from_db()
        self.assertEqual(t.start_date, date(2026, 3, 2))

    def test_garbage_dates_are_refused(self):
        t = self._task('Build', date(2026, 3, 2), date(2026, 3, 6))
        self.client.post(f'/psa/project-task/{t.pk}/reschedule/', {
            'start_date': 'not-a-date', 'due_date': 'nonsense'})
        t.refresh_from_db()
        self.assertEqual(t.start_date, date(2026, 3, 2))

    def test_the_drag_endpoint_answers_json(self):
        t = self._task('Build', date(2026, 3, 2), date(2026, 3, 6))
        resp = self.client.post(
            f'/psa/project-task/{t.pk}/reschedule/',
            {'start_date': '2026-03-09', 'due_date': '2026-03-13'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['start_date'], '2026-03-09')

    def test_adding_a_dependency_through_the_view(self):
        a = self._task('A', date(2026, 3, 1), date(2026, 3, 3))
        b = self._task('B', date(2026, 3, 4), date(2026, 3, 6))
        self.client.post(f'/psa/project-task/{b.pk}/dependency/',
                         {'depends_on': a.pk})
        self.assertIn(a, b.depends_on.all())

    def test_a_cycle_through_the_view_is_refused(self):
        a = self._task('A', date(2026, 3, 1), date(2026, 3, 3))
        b = self._task('B', date(2026, 3, 4), date(2026, 3, 6))
        b.add_dependency(a)
        self.client.post(f'/psa/project-task/{a.pk}/dependency/',
                         {'depends_on': b.pk})
        self.assertEqual(list(a.depends_on.all()), [])

    def test_removing_a_dependency(self):
        a = self._task('A', date(2026, 3, 1), date(2026, 3, 3))
        b = self._task('B', date(2026, 3, 4), date(2026, 3, 6))
        b.add_dependency(a)
        self.client.post(f'/psa/project-task/{b.pk}/dependency/',
                         {'action': 'remove', 'depends_on': a.pk})
        self.assertEqual(list(b.depends_on.all()), [])

    def test_another_organizations_project_is_not_reachable(self):
        other = Organization.objects.create(name='NotUs', slug='not-us-tl')
        _enable_psa_for(other)
        foreign = Project.objects.create(organization=other, name='Theirs')
        resp = self.client.get(f'/psa/projects/{foreign.pk}/timeline/')
        self.assertEqual(resp.status_code, 404)
