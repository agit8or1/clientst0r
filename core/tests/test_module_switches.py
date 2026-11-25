"""Settings → Modules: every optional module can be turned off.

For each module switch (core.feature_gates.MODULE_SWITCHES): off hides its
navigation entry and its main page answers 404; on (the default) shows it
again and the page opens. A fresh settings row has every switch on;
migration core 0125 keeps the values existing installs had; scheduled jobs
of a module that is off are skipped.
"""
import importlib
from io import StringIO

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import resolve, reverse

from core import feature_gates, modules, navigation
from core.models import Organization, ScheduledTask, SystemSetting

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

# switch -> the module's main page (url name). Webhooks has no page of its
# own (events are delivered by core.webhook_sender, which reads the switch)
# and location maps are a part of the location pages (locations.views).
MAIN_PAGE = {
    'psa_enabled': 'psa:ticket_list',
    'projects_enabled': 'psa:project_list',
    'quotes_enabled': 'psa:quote_list',
    'change_management_enabled': 'psa:change_request_list',
    'procurement_enabled': 'psa:requisition_list',
    'security_alerts_enabled': 'security_alerts:alert_list',
    'pulse_enabled': 'pulse:check_list',
    'client_health_enabled': 'health_score:list',
    'crm_enabled': 'crm:home',
    'contracts_enabled': 'contracts:dashboard',
    'licensing_enabled': 'licensing:overview',
    'monitoring_enabled': 'monitoring:website_monitor_list',
    'status_pages_enabled': 'statuspage:list',
    'netconfig_enabled': 'netconfig:device_list',
    'backup_monitoring_enabled': 'backup_monitoring:dashboard',
    'workflows_enabled': 'processes:process_list',
    'scheduling_enabled': 'scheduling:task_list',
    'inventory_enabled': 'inventory:inventory_dashboard',
    'vehicles_enabled': 'vehicles:vehicle_list',
    'field_ops_enabled': 'field_ops:dispatch_sharing',
    'onboarding_enabled': 'onboarding:start',
    'reports_enabled': 'reports:home',
    'global_kb_enabled': 'psa:kb_browse',
    'diagrams_enabled': 'docs:diagram_list',
    'readiness_enabled': 'readiness:overview',
    'secure_notes_enabled': 'core:secure_note_inbox',
}
NO_PAGE = {'webhooks_enabled', 'locations_map_enabled'}

# The switches that are not module switches keep their own default.
NOT_MODULES = {
    'psa_ai_enabled': False,          # OPTIONAL AI: explicit opt-in
    'psa_csat_enabled': False,
    'psa_portal_announcements_enabled': False,
    'psa_portal_voting_enabled': False,
    'psa_portal_escalation_enabled': False,
    'psa_portal_customer_approvals_enabled': False,
    'asset_age_warnings_enabled': False,
    'warranty_checks_enabled': False,
    'firmware_checks_enabled': False,
}


def _set(**values):
    s = SystemSetting.get_settings()
    for k, v in values.items():
        setattr(s, k, v)
    s.save()


class FreshInstallTests(TestCase):

    def test_every_module_switch_is_on_for_a_new_install(self):
        SystemSetting.objects.all().delete()
        s = SystemSetting.get_settings()  # what a new install creates
        for name in feature_gates.MODULE_SWITCHES:
            with self.subTest(name=name):
                self.assertIs(SystemSetting._meta.get_field(name).default, True)
                self.assertTrue(getattr(s, name))

    def test_settings_that_are_not_modules_keep_their_defaults(self):
        for name, default in NOT_MODULES.items():
            with self.subTest(name=name):
                self.assertNotIn(name, feature_gates.MODULE_SWITCHES)
                self.assertIs(SystemSetting._meta.get_field(name).default, default)

    def test_every_switch_is_in_the_registry_and_covered_here(self):
        registry = {m.field for m in modules.MODULES if m.field}
        self.assertLessEqual(set(feature_gates.MODULE_SWITCHES), registry)
        self.assertEqual(set(feature_gates.MODULE_SWITCHES), set(MAIN_PAGE) | NO_PAGE)

    def test_scheduled_job_map_names_real_jobs_and_switches(self):
        types = {k for k, _l in ScheduledTask.TASK_TYPES}
        for task_type, field in feature_gates.TASK_SWITCHES.items():
            self.assertIn(task_type, types)
            self.assertIn(field, feature_gates.MODULE_SWITCHES)
        # Retention jobs keep running whatever the switch says.
        for keep in ('prune_technician_locations', 'prune_monitor_checks', 'psa_purge_secure_replies'):
            self.assertNotIn(keep, feature_gates.TASK_SWITCHES)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class EachSwitchTests(TestCase):
    """Off: no navigation link, the main page is a 404. On: both back."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Switch Co', slug='switch-co')
        cls.su = get_user_model().objects.create_user(
            'ms_su', 'ms@x.test', 'pw', is_staff=True, is_superuser=True)

    def setUp(self):
        self.client.force_login(self.su)
        s = self.client.session
        s['2fa_prompted'] = True
        s.save()
        self.client.get(reverse('accounts:switch_organization', args=[self.org.id]))

    def _hrefs(self):
        request = RequestFactory().get('/')
        request.user = self.su
        request.current_organization = self.org
        request.is_staff_user = True
        request.session = {}
        ctx = navigation.request_context(request)
        return {d['href'].split('?', 1)[0] for d in navigation.destinations_for(ctx)}

    def test_each_switch(self):
        for field, url_name in MAIN_PAGE.items():
            with self.subTest(field=field):
                url = reverse(url_name)
                self.assertIn(field, feature_gates.path_gates(url) or (field,))
                _set(**{field: False})
                self.assertNotIn(url, self._hrefs(), 'still linked while off')
                self.assertEqual(self.client.get(url).status_code, 404)
                _set(**{field: True})
                self.assertIn(url, self._hrefs(), 'not linked while on')
                self.assertNotEqual(self.client.get(url).status_code, 404)

    def test_every_route_of_a_whole_app_module_is_gated(self):
        for field, namespace in (('crm_enabled', 'crm'), ('licensing_enabled', 'licensing'),
                                 ('client_health_enabled', 'health_score'),
                                 ('backup_monitoring_enabled', 'backup_monitoring'),
                                 ('status_pages_enabled', 'statuspage'),
                                 ('netconfig_enabled', 'netconfig'), ('contracts_enabled', 'contracts'),
                                 ('readiness_enabled', 'readiness'), ('onboarding_enabled', 'onboarding'),
                                 ('workflows_enabled', 'processes'), ('inventory_enabled', 'inventory'),
                                 ('scheduling_enabled', 'scheduling')):
            mod = importlib.import_module(f'{namespace}.urls')
            for p in mod.urlpatterns:
                with self.subTest(field=field, name=p.name):
                    self.assertIn(field, feature_gates.gates_of(p.callback))

    def test_links_people_already_have_keep_working(self):
        # Signing links, digest unsubscribe, expense receipts and a user's
        # own location history are not gated.
        for name, args in (('security_alerts:digest_unsubscribe', ('tok',)),
                           ('vehicles:receipt_quick', ()),
                           ('field_ops:my_location_history', ()),
                           ('field_ops:settings', ())):
            with self.subTest(name=name):
                self.assertEqual(feature_gates.gates_of(resolve(reverse(name, args=args)).func), ())

    def test_turning_off_keeps_the_data(self):
        from crm.models import Lead
        lead = Lead.objects.create(organization=self.org, company_name='Kept Ltd')
        _set(crm_enabled=False)
        self.assertEqual(self.client.get(reverse('crm:lead_list')).status_code, 404)
        self.assertTrue(Lead.objects.filter(pk=lead.pk).exists())
        _set(crm_enabled=True)
        self.assertContains(self.client.get(reverse('crm:lead_list')), 'Kept Ltd')

    def test_portal_status_link_follows_status_pages(self):
        url = reverse('portal:status')
        self.assertIn('status_pages_enabled', feature_gates.path_gates(url))

    def test_mobile_api_module_endpoints_are_gated(self):
        for name, field in (('api_mobile:project_list', 'projects_enabled'),
                            ('api_mobile:inventory_list', 'inventory_enabled'),
                            ('api_mobile:vehicle_list', 'vehicles_enabled'),
                            ('api_mobile:workflow_list', 'workflows_enabled'),
                            ('api_mobile:clock_in', 'field_ops_enabled'),
                            ('api_mobile:location_ping', 'field_ops_enabled'),
                            ('api_mobile:netconfig_devices', 'netconfig_enabled')):
            with self.subTest(name=name):
                self.assertIn(field, feature_gates.path_gates(reverse(name)))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class FeatureTogglesPageTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.su = get_user_model().objects.create_superuser('ft_su', 'ft@x.test', 'pw')
        cls.staff = get_user_model().objects.create_user('ft_staff', 'fs@x.test', 'pw', is_staff=True)

    def test_page_lists_every_module_switch(self):
        self.client.force_login(self.su)
        html = self.client.get(reverse('core:settings_features')).content.decode()
        for name in feature_gates.MODULE_SWITCHES:
            self.assertIn(f'name="{name}"', html, name)
        self.assertNotIn('name="psa_ai_enabled"', html)

    def test_saving_switches_one_off_and_the_rest_stay_on(self):
        self.client.force_login(self.su)
        post = {name: 'on' for name in feature_gates.MODULE_SWITCHES if name != 'licensing_enabled'}
        r = self.client.post(reverse('core:settings_features'), post)
        self.assertEqual(r.status_code, 302)
        s = SystemSetting.get_settings()
        self.assertFalse(s.licensing_enabled)
        self.assertTrue(s.projects_enabled and s.crm_enabled and s.reports_enabled)
        self.assertFalse(s.psa_ai_enabled)  # never touched by this page

    def test_superuser_only(self):
        self.client.force_login(self.staff)
        r = self.client.get(reverse('core:settings_features'))
        self.assertNotEqual(r.status_code, 200)
        self.client.post(reverse('core:settings_features'), {})
        self.assertTrue(SystemSetting.get_settings().crm_enabled)  # nothing was switched off


class SchedulerSkipsJobsOfModulesThatAreOffTests(TestCase):

    def test_job_of_a_module_that_is_off_is_skipped_and_not_claimed(self):
        ScheduledTask.objects.all().delete()
        task = ScheduledTask.objects.create(task_type='licensing_alerts', enabled=True, interval_minutes=60)
        _set(licensing_enabled=False)
        out = StringIO()
        call_command('run_scheduler', stdout=out)
        self.assertIn('module turned off', out.getvalue())
        task.refresh_from_db()
        self.assertIsNone(task.last_run_at)
        self.assertFalse(feature_gates.task_allowed('licensing_alerts'))
        _set(licensing_enabled=True)
        self.assertTrue(feature_gates.task_allowed('licensing_alerts'))
        self.assertTrue(feature_gates.task_allowed('update_check'))  # not a module job

    def test_website_checks_stop_while_monitoring_is_off(self):
        _set(monitoring_enabled=False)
        out = StringIO()
        call_command('check_websites', stdout=out)
        self.assertIn('turned off', out.getvalue())


class UpgradeKeepsExistingValuesTests(SimpleTestCase):
    """Migration core 0125 must not change an existing install's switches.

    Checked on the migration itself rather than by migrating the shared test
    database back and forth (that broke later serialized-rollback tests):
    new switches are added with default True (existing rows filled with True,
    so those modules stay on), the PSA/CRM/pulse switches only get a new
    default (AlterField never rewrites existing rows), and nothing runs data
    changes."""

    NEW = {'projects_enabled', 'quotes_enabled', 'change_management_enabled', 'procurement_enabled',
           'security_alerts_enabled', 'client_health_enabled', 'contracts_enabled', 'licensing_enabled',
           'status_pages_enabled', 'netconfig_enabled', 'backup_monitoring_enabled', 'field_ops_enabled',
           'onboarding_enabled', 'diagrams_enabled', 'readiness_enabled'}
    DEFAULT_ONLY = {'psa_enabled', 'crm_enabled', 'pulse_enabled'}

    def test_existing_row_keeps_its_values_and_new_switches_are_on(self):
        from importlib import import_module
        from django.db.migrations import AddField, AlterField
        mig = import_module('core.migrations.0125_module_switches_on_by_default').Migration
        added, altered = {}, {}
        for op in mig.operations:
            self.assertIsInstance(op, (AddField, AlterField), f'unexpected operation {op!r}')
            self.assertEqual(op.model_name, 'systemsetting')
            (added if isinstance(op, AddField) else altered)[op.name] = op.field
        self.assertEqual(set(added), self.NEW)
        self.assertEqual(set(altered), self.DEFAULT_ONLY)
        for name, field in {**added, **altered}.items():
            self.assertIs(field.default, True, name)
            self.assertFalse(field.null, name)
