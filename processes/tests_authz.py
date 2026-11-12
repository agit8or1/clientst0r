"""Server-side authorization regressions for processes / runbooks (roles/
permissions program): docs_* flags gate editing, launching a run is bounded to
the caller's own clients, stage completion needs the run or ticket editing, and
cloning a global template never carries another organization's links."""
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role
from core.models import Organization
from processes.models import Process, ProcessExecution, ProcessStage, ProcessStageCompletion
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_global, _setup_seed


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ProcessAuthzTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.a = Organization.objects.create(name='P Cust A', slug='authz-proc-a')
        cls.b = Organization.objects.create(name='P Cust B', slug='authz-proc-b')
        cls.ro = User.objects.create_user('proc-ro', 'r@a.test', 'pw')
        Membership.objects.create(user=cls.ro, organization=cls.a, role=Role.READONLY)
        cls.editor = User.objects.create_user('proc-ed', 'e@a.test', 'pw')
        Membership.objects.create(user=cls.editor, organization=cls.a, role=Role.EDITOR)
        cls.proc = Process.objects.create(organization=cls.a, title='Onboard', slug='onboard',
                                          is_published=True)
        cls.stage = ProcessStage.objects.create(process=cls.proc, order=1, title='Step 1')
        cls.execution = ProcessExecution.objects.create(process=cls.proc, organization=cls.a,
                                                  assigned_to=cls.editor, status='in_progress')
        cls.completion = ProcessStageCompletion.objects.create(execution=cls.execution, stage=cls.stage)

    def _client(self, user):
        c = Client()
        c.force_login(user)
        s = c.session
        s['current_organization_id'] = self.a.pk
        s.save()
        return c

    def test_read_only_member_can_view_but_not_change(self):
        c = self._client(self.ro)
        self.assertEqual(c.get(reverse('processes:process_detail', args=['onboard'])).status_code, 200)
        self.assertEqual(c.get(reverse('processes:process_edit', args=['onboard'])).status_code, 403)
        self.assertEqual(c.post(reverse('processes:process_delete', args=['onboard'])).status_code, 403)
        self.assertTrue(Process.objects.filter(pk=self.proc.pk).exists())
        self.assertEqual(c.get(reverse('processes:process_create')).status_code, 403)
        r = c.post(reverse('processes:stage_complete', args=[self.completion.pk]))
        self.assertEqual(r.status_code, 403)
        self.completion.refresh_from_db()
        self.assertFalse(self.completion.is_completed)

    def test_assignee_completes_stage(self):
        r = self._client(self.editor).post(reverse('processes:stage_complete', args=[self.completion.pk]))
        self.assertEqual(r.status_code, 200)

    def test_launch_cannot_target_another_customer(self):
        from psa.models import Ticket
        _setup_seed()
        _enable_psa_global()
        c = self._client(self.editor)
        r = c.get(reverse('processes:execution_create', args=['onboard']))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'P Cust B')
        c.post(reverse('processes:execution_create', args=['onboard']),
               {'client_org_id': self.b.pk, 'notes': 'x'})
        self.assertFalse(Ticket.objects.filter(organization=self.b).exists())
        self.assertFalse(ProcessExecution.objects.filter(organization=self.b).exists())

    def test_clone_of_global_template_drops_foreign_links(self):
        from vault.models import Password
        foreign_pw = Password.objects.create(organization=self.b, title='B admin', encrypted_password='x')
        tpl = Process.objects.create(organization=self.b, title='Tpl', slug='tpl', is_global=True,
                                     is_template=True, is_published=True)
        ProcessStage.objects.create(process=tpl, order=1, title='Use B pw', linked_password=foreign_pw)
        r = self._client(self.editor).post(reverse('processes:process_clone_template', args=['tpl']))
        self.assertEqual(r.status_code, 302)
        clone = Process.objects.filter(organization=self.a, title__endswith='Tpl').get()
        self.assertIsNone(clone.stages.get().linked_password)
