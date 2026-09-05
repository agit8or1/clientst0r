"""
Phase 35.1 (v3.17.548) — project templates.

The behaviour that matters most is that applying a template *copies*. A project
that silently changed shape when somebody edited the template months later would
be worse than having no templates at all.
"""
from datetime import date, timedelta

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from core.models import Organization, SystemSetting
from psa.models import (
    Project, ProjectTask, ProjectTemplate, ProjectTemplateTask,
)
from psa.tests._base import _enable_psa_for, _setup_seed

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


class ProjectTemplateModelTests(TestCase):
    def setUp(self):
        _setup_seed()
        self.org = Organization.objects.create(name='TplCo', slug='tpl-co')
        self.template = ProjectTemplate.objects.create(
            organization=self.org, name='M365 cutover')
        self.project = Project.objects.create(
            organization=self.org, name='Acme cutover',
            start_date=date(2026, 3, 2))

    def _tt(self, title, **kw):
        kw.setdefault('sort_order', self.template.template_tasks.count())
        return ProjectTemplateTask.objects.create(
            template=self.template, title=title, **kw)

    def test_apply_copies_tasks_onto_the_project(self):
        self._tt('Provision tenant')
        self._tt('Migrate mailboxes')
        created = self.template.apply_to(self.project)
        self.assertEqual(len(created), 2)
        self.assertEqual(self.project.tasks.count(), 2)

    def test_copies_are_independent_of_the_template(self):
        """Editing the template later must not reshape a project already
        built from it."""
        tt = self._tt('Provision tenant')
        self.template.apply_to(self.project)
        tt.title = 'Renamed after the fact'
        tt.save()
        self.assertEqual(self.project.tasks.first().title, 'Provision tenant')

    def test_deleting_the_template_leaves_the_project_alone(self):
        self._tt('Provision tenant')
        self.template.apply_to(self.project)
        self.template.delete()
        self.assertEqual(self.project.tasks.count(), 1)

    def test_offsets_become_dates_from_the_project_start(self):
        self._tt('Kickoff', due_offset_days=0)
        self._tt('Go live', due_offset_days=14)
        self.template.apply_to(self.project)
        dates = sorted(t.due_date for t in self.project.tasks.all())
        self.assertEqual(dates, [date(2026, 3, 2), date(2026, 3, 16)])

    def test_a_task_without_an_offset_has_no_date(self):
        self._tt('Someday')
        self.template.apply_to(self.project)
        self.assertIsNone(self.project.tasks.first().due_date)

    def test_offset_zero_is_the_start_date_not_no_date(self):
        """0 and None mean different things and must not collapse."""
        self._tt('Kickoff', due_offset_days=0)
        self.template.apply_to(self.project)
        self.assertEqual(self.project.tasks.first().due_date, date(2026, 3, 2))

    def test_explicit_start_date_overrides_the_projects(self):
        self._tt('Kickoff', due_offset_days=0)
        self.template.apply_to(self.project, start_date=date(2026, 11, 9))
        self.assertEqual(self.project.tasks.first().due_date, date(2026, 11, 9))

    def test_a_project_with_no_start_date_anchors_on_today(self):
        self.project.start_date = None
        self.project.save()
        self._tt('Kickoff', due_offset_days=0)
        self.template.apply_to(self.project)
        self.assertEqual(self.project.tasks.first().due_date, date.today())

    def test_applying_appends_rather_than_replaces(self):
        """Applying a template to a project that already has work must not
        delete it."""
        ProjectTask.objects.create(project=self.project, title='Existing work')
        self._tt('From template')
        self.template.apply_to(self.project)
        self.assertEqual(self.project.tasks.count(), 2)

    def test_appended_tasks_sort_after_existing_ones(self):
        ProjectTask.objects.create(
            project=self.project, title='Existing', sort_order=5)
        self._tt('From template')
        self.template.apply_to(self.project)
        added = self.project.tasks.get(title='From template')
        self.assertGreater(added.sort_order, 5)

    def test_appending_after_a_single_task_at_order_zero(self):
        """An only task at sort_order 0 is still a task; the first copied
        task must not land on top of it."""
        ProjectTask.objects.create(
            project=self.project, title='Existing', sort_order=0)
        self._tt('From template')
        self.template.apply_to(self.project)
        added = self.project.tasks.get(title='From template')
        self.assertGreater(added.sort_order, 0)

    def test_milestones_survive_the_copy(self):
        self._tt('Go live', is_milestone=True)
        self.template.apply_to(self.project)
        self.assertTrue(self.project.tasks.first().is_milestone)

    def test_estimated_hours_survive_the_copy(self):
        self._tt('Migrate', estimated_hours=8)
        self.template.apply_to(self.project)
        self.assertEqual(float(self.project.tasks.first().estimated_hours), 8.0)

    def test_child_tasks_are_copied_under_their_parent(self):
        parent = self._tt('Migration')
        ProjectTemplateTask.objects.create(
            template=self.template, parent=parent, title='Mailboxes', sort_order=0)
        self.template.apply_to(self.project)
        child = self.project.tasks.get(title='Mailboxes')
        self.assertEqual(child.parent.title, 'Migration')

    def test_total_estimated_hours(self):
        self._tt('A', estimated_hours=3)
        self._tt('B', estimated_hours=4.5)
        self.assertEqual(float(self.template.total_estimated_hours), 7.5)

    def test_total_hours_with_no_estimates_is_zero_not_none(self):
        self._tt('A')
        self.assertEqual(self.template.total_estimated_hours, 0)

    def test_names_are_unique_per_organization(self):
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProjectTemplate.objects.create(
                    organization=self.org, name='M365 cutover')

    def test_the_same_name_is_fine_in_another_organization(self):
        other = Organization.objects.create(name='Other', slug='other-tpl')
        ProjectTemplate.objects.create(organization=other, name='M365 cutover')
        self.assertEqual(ProjectTemplate.objects.filter(name='M365 cutover').count(), 2)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ProjectTemplateViewTests(TestCase):
    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        self.org = Organization.objects.create(name='TplView', slug='tpl-view')
        self.other_org = Organization.objects.create(name='TplOther', slug='tpl-other')
        _enable_psa_for(self.org)
        _enable_psa_for(self.other_org)
        self.user = User.objects.create_superuser(
            'tpladmin', 'tpl@example.com', 'hunter2xyz')
        self.client = Client()
        self.client.force_login(self.user)
        session = self.client.session
        session['current_organization_id'] = self.org.id
        session.save()
        self.project = Project.objects.create(
            organization=self.org, name='Acme cutover', start_date=date(2026, 3, 2))

    def test_create_a_template(self):
        self.client.post('/psa/project-templates/new/', {'name': 'Server migration'})
        self.assertTrue(
            ProjectTemplate.objects.filter(
                organization=self.org, name='Server migration').exists())

    def test_duplicate_name_is_refused(self):
        ProjectTemplate.objects.create(organization=self.org, name='Dup')
        self.client.post('/psa/project-templates/new/', {'name': 'Dup'})
        self.assertEqual(ProjectTemplate.objects.filter(name='Dup').count(), 1)

    def test_add_a_task_to_a_template(self):
        t = ProjectTemplate.objects.create(organization=self.org, name='T')
        self.client.post(f'/psa/project-templates/{t.pk}/', {
            'action': 'add_task', 'title': 'Provision', 'due_offset_days': '3'})
        task = t.template_tasks.get()
        self.assertEqual(task.title, 'Provision')
        self.assertEqual(task.due_offset_days, 3)

    def test_offset_zero_is_kept_not_read_as_blank(self):
        t = ProjectTemplate.objects.create(organization=self.org, name='T')
        self.client.post(f'/psa/project-templates/{t.pk}/', {
            'action': 'add_task', 'title': 'Kickoff', 'due_offset_days': '0'})
        self.assertEqual(t.template_tasks.get().due_offset_days, 0)

    def test_a_task_needs_a_title(self):
        t = ProjectTemplate.objects.create(organization=self.org, name='T')
        self.client.post(f'/psa/project-templates/{t.pk}/', {
            'action': 'add_task', 'title': '   '})
        self.assertEqual(t.template_tasks.count(), 0)

    def test_apply_a_template_from_the_project_page(self):
        t = ProjectTemplate.objects.create(organization=self.org, name='T')
        ProjectTemplateTask.objects.create(template=t, title='Provision')
        self.client.post(f'/psa/projects/{self.project.pk}/apply-template/',
                         {'template': t.pk})
        self.assertEqual(self.project.tasks.count(), 1)

    def test_cannot_apply_another_organizations_template(self):
        foreign = ProjectTemplate.objects.create(
            organization=self.other_org, name='Theirs')
        ProjectTemplateTask.objects.create(template=foreign, title='Sneaky')
        self.client.post(f'/psa/projects/{self.project.pk}/apply-template/',
                         {'template': foreign.pk})
        self.assertEqual(self.project.tasks.count(), 0)

    def test_retired_templates_are_not_offered_on_the_project_page(self):
        ProjectTemplate.objects.create(
            organization=self.org, name='Retired', is_active=False)
        active = ProjectTemplate.objects.create(organization=self.org, name='Active')
        resp = self.client.get(f'/psa/projects/{self.project.pk}/')
        offered = list(resp.context['project_templates'])
        self.assertEqual(offered, [active])

    def test_delete_a_template_keeps_project_tasks(self):
        t = ProjectTemplate.objects.create(organization=self.org, name='T')
        ProjectTemplateTask.objects.create(template=t, title='Provision')
        t.apply_to(self.project)
        self.client.post(f'/psa/project-templates/{t.pk}/', {'action': 'delete'})
        self.assertEqual(self.project.tasks.count(), 1)
