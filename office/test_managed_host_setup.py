"""Server setup for the managed editor from Settings (office.managed.host_setup).

The web request only records what the deployment administrator asked for;
the scheduler starts the setup in its own process, which runs the root
helper's office-setup (and, for the same-host layout, office-site-include).
The root helper is mocked here; its own checks are in
core.tests.test_root_helper."""
import subprocess
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditLog
from office import tests as core
from office.managed import host_setup
from office.models import ManagedOfficeService

APP_HOST = 'docs.example.com'


def done(rc=0, out='ok', err=''):
    return subprocess.CompletedProcess([], rc, out, err)


@override_settings(MIDDLEWARE=core.TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   ALLOWED_HOSTS=[APP_HOST, 'testserver'])
class HostSetupViewTests(TestCase):

    def setUp(self):
        User = get_user_model()
        self.su = User.objects.create_superuser('hs-su', 'su@example.com', 'x')
        self.staff = User.objects.create_user('hs-staff', 'st@example.com', 'x', is_staff=True)
        self.client = Client(HTTP_HOST=APP_HOST)
        p = mock.patch.object(host_setup, 'available', return_value=True)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch('office.managed.jobs.refresh_status', return_value=None)
        p.start()
        self.addCleanup(p.stop)

    def post(self, **data):
        base = {'engine': 'collabora', 'layout': 'same-host', 'deployment_id': 'docs-prod',
                'accept_same_host': '1', 'allow_untested': '1'}
        base.update(data)
        return self.client.post(reverse('office:managed_host_setup'), {k: v for k, v in base.items()
                                                                       if v is not None})

    def test_only_deployment_administrators(self):
        self.client.force_login(self.staff)
        r = self.post()
        self.assertIn(r.status_code, (302, 403))
        self.assertEqual(ManagedOfficeService.get().host_setup_state, '')

    def test_queues_with_the_request_host(self):
        self.client.force_login(self.su)
        page = self.client.get(reverse('office:managed'))
        self.assertContains(page, 'Set up this server')
        self.assertContains(page, 'value="docs-example-com"')
        r = self.post(app_host='evil.example.com')       # ignored: the host is the request's
        self.assertEqual(r.status_code, 302)
        s = ManagedOfficeService.get()
        self.assertEqual(s.host_setup_state, 'queued')
        self.assertEqual(s.host_setup_request, {
            'engine': 'collabora', 'layout': 'same-host', 'app_host': APP_HOST,
            'deployment_id': 'docs-prod', 'office_host': '', 'allow_untested': True})
        self.assertEqual(s.same_host_acknowledged_by, self.su)
        self.assertEqual(s.engine, 'collabora')
        self.assertTrue(AuditLog.objects.filter(description__startswith='Server setup queued').exists())
        # a second request while one is queued is refused
        self.post()
        self.assertEqual(ManagedOfficeService.get().host_setup_requested_at, s.host_setup_requested_at)

    def test_same_host_needs_the_acknowledgement(self):
        self.client.force_login(self.su)
        self.post(accept_same_host=None)
        self.assertEqual(ManagedOfficeService.get().host_setup_state, '')

    def test_bad_values_are_refused(self):
        self.client.force_login(self.su)
        for bad in ({'deployment_id': 'x;id'}, {'engine': 'docker'}, {'layout': 'dedicated'},
                    {'layout': 'dedicated', 'office_host': APP_HOST},
                    {'engine': 'onlyoffice', 'layout': 'same-host'}):
            self.post(**bad)
            self.assertEqual(ManagedOfficeService.get().host_setup_state, '', bad)

    def test_without_the_root_helper_only_the_commands_are_shown(self):
        self.client.force_login(self.su)
        with mock.patch.object(host_setup, 'available', return_value=False):
            page = self.client.get(reverse('office:managed'))
            self.assertNotContains(page, 'Set up this server</h2>')
            self.post()
        self.assertEqual(ManagedOfficeService.get().host_setup_state, '')


class HostSetupRunTests(TestCase):

    def setUp(self):
        self.su = get_user_model().objects.create_superuser('hs-su2', 'su2@example.com', 'x')
        p = mock.patch('office.managed.jobs.refresh_status', return_value=None)
        p.start()
        self.addCleanup(p.stop)

    def queue(self, **kw):
        fields = dict(engine='collabora', layout='same-host', app_host=APP_HOST, deployment_id='docs-prod')
        fields.update(kw)
        host_setup.request_setup(self.su, allow_untested=True, **fields)

    def start(self):
        with mock.patch('subprocess.Popen') as popen:
            lease = host_setup.maybe_start()
        return lease, popen

    def test_scheduler_starts_it_once_in_its_own_process(self):
        self.queue()
        lease, popen = self.start()
        self.assertTrue(lease)
        argv = popen.call_args.args[0]
        self.assertEqual(argv[-3:], ['office_managed', '--host-setup-run', lease])
        self.assertTrue(popen.call_args.kwargs['start_new_session'])
        self.assertEqual(ManagedOfficeService.get().host_setup_state, 'running')
        self.assertIsNone(self.start()[0])

    def test_same_host_runs_setup_then_the_include(self):
        self.queue()
        lease, _ = self.start()
        with mock.patch('core.root_helper.run', side_effect=[done(out='installed'), done(out='included')]) as run:
            self.assertTrue(host_setup.run(lease))
        self.assertEqual(run.call_args_list[0].args[0],
                         ['office-setup', 'collabora', 'same-host', APP_HOST, 'docs-prod', '-', 'untested'])
        self.assertEqual(run.call_args_list[1].args[0], ['office-site-include', 'on'])
        s = ManagedOfficeService.get()
        self.assertEqual(s.host_setup_state, 'succeeded')
        self.assertTrue(s.enabled)
        self.assertIn('installed', s.host_setup_output)
        self.assertIn('included', s.host_setup_output)

    def test_dedicated_has_no_include(self):
        self.queue(layout='dedicated', office_host='office.example.com')
        lease, _ = self.start()
        with mock.patch('core.root_helper.run', return_value=done()) as run:
            self.assertTrue(host_setup.run(lease))
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][5], 'office.example.com')

    def test_failure_is_recorded_and_service_stays_off(self):
        self.queue()
        lease, _ = self.start()
        with mock.patch('core.root_helper.run', return_value=done(rc=1, out='', err='refused: x')) as run:
            self.assertFalse(host_setup.run(lease))
        self.assertEqual(run.call_count, 1)
        s = ManagedOfficeService.get()
        self.assertEqual(s.host_setup_state, 'failed')
        self.assertFalse(s.enabled)
        self.assertIn('refused: x', s.host_setup_output)

    def test_wrong_lease_does_nothing(self):
        self.queue()
        self.start()
        with mock.patch('core.root_helper.run') as run:
            self.assertFalse(host_setup.run('not-the-lease'))
        run.assert_not_called()

    def test_stale_run_is_failed(self):
        self.queue()
        self.start()
        ManagedOfficeService.objects.filter(pk=1).update(
            host_setup_started_at=timezone.now() - timezone.timedelta(hours=2))
        self.assertIsNone(host_setup.maybe_start())
        self.assertEqual(ManagedOfficeService.get().host_setup_state, 'failed')

    def test_run_pending_command_starts_it(self):
        self.queue()
        with mock.patch('subprocess.Popen'), mock.patch('office.managed.jobs.run_pending', return_value=None), \
                mock.patch('office.managed.jobs.maybe_schedule_update'):
            call_command('office_managed', run_pending=True, stdout=open('/dev/null', 'w'))
        self.assertEqual(ManagedOfficeService.get().host_setup_state, 'running')
