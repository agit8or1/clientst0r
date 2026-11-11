"""Reports & Analytics and Secure Notes switches (Settings → Features) now
gate their module; the six unused PSA surface switches are gone.

Before, `reports_enabled` and `secure_notes_enabled` were saved but read by
nothing. Off now means: every page of the module 404s, its menu entries and
shortcuts are hidden, and scheduled reports pause. On is the default, and
migration core 0085 keeps both on for existing installs.
"""
import importlib
from io import StringIO

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import resolve, reverse

from core.models import SystemSetting

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def _set(**values):
    s = SystemSetting.get_settings()
    for k, v in values.items():
        setattr(s, k, v)
    s.save()


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ReportsSwitchTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.su = User.objects.create_superuser('fg_su', 'su@x.test', 'pw')

    def setUp(self):
        self.client.force_login(self.su)

    def test_on_by_default_and_reachable(self):
        self.assertTrue(SystemSetting.get_settings().reports_enabled)
        self.assertNotEqual(self.client.get(reverse('reports:home')).status_code, 404)
        html = self.client.get(reverse('core:dashboard')).content.decode()
        self.assertIn(reverse('reports:home'), html)

    def test_off_404s_every_reports_route_and_hides_the_menu(self):
        _set(reports_enabled=False)
        for name in ('reports:home', 'reports:dashboard_list', 'reports:wallboard_list',
                     'reports:template_list', 'reports:generated_list', 'reports:psa_reports_list'):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 404)
        html = self.client.get(reverse('core:dashboard')).content.decode()
        self.assertNotIn(f'href="{reverse("reports:home")}"', html)

    def test_every_reports_route_is_gated(self):
        from reports import urls
        for p in urls.urlpatterns:
            self.assertEqual(getattr(p.callback, 'feature_gate', None), 'reports_enabled', p.name)

    def test_scheduled_reports_pause_while_off(self):
        _set(reports_enabled=False)
        out = StringIO()
        call_command('run_scheduled_reports', stdout=out)
        self.assertIn('turned off', out.getvalue())

    def test_shortcut_strip_drops_reports_pin_while_off(self):
        from core import shortcut_strip
        flags = shortcut_strip.feature_flags()
        self.assertTrue(flags['reports_enabled'])
        _set(reports_enabled=False)
        keys = [i['key'] for i in shortcut_strip.available_for_user(self.su)]
        self.assertNotIn('reports', keys)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SecureNotesSwitchTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.su = User.objects.create_superuser('fg_su2', 'su2@x.test', 'pw')

    def setUp(self):
        self.client.force_login(self.su)

    def test_off_404s_the_notes_pages_and_hides_the_menu(self):
        url = reverse('core:secure_note_inbox')
        self.assertEqual(self.client.get(url).status_code, 200)
        _set(secure_notes_enabled=False)
        for name in ('core:secure_note_inbox', 'core:secure_note_sent', 'core:secure_note_create',
                     'core:secure_note_links_dashboard'):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 404)
        html = self.client.get(reverse('core:dashboard')).content.decode()
        self.assertNotIn(f'href="{url}"', html)

    def test_link_view_is_not_gated(self):
        # Ticket secure messages are SecureNotes opened through this view.
        match = resolve(reverse('core:secure_note_view_link', args=['abc']))
        self.assertIsNone(getattr(match.func, 'feature_gate', None))
        self.assertEqual(getattr(resolve(reverse('core:secure_note_inbox')).func, 'feature_gate', None),
                         'secure_notes_enabled')


class UpgradeKeepsModulesOnTests(TestCase):

    def test_data_migration_turns_both_on(self):
        from django.apps import apps
        _set(reports_enabled=False, secure_notes_enabled=False)
        mod = importlib.import_module('core.migrations.0085_existing_installs_keep_reports_and_secure_notes')
        mod.keep_on(apps, None)
        s = SystemSetting.objects.get(pk=SystemSetting.get_settings().pk)
        self.assertTrue(s.reports_enabled)
        self.assertTrue(s.secure_notes_enabled)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RemovedPsaSwitchesTests(TestCase):

    def test_psa_settings_page_no_longer_offers_them(self):
        call_command('psa_seed_defaults', verbosity=0)
        _set(psa_enabled=True)
        su = User.objects.create_superuser('fg_su3', 'su3@x.test', 'pw')
        self.client.force_login(su)
        r = self.client.get('/psa/settings/')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        for name in ('psa_portal_enabled', 'psa_anonymous_ticket_form_enabled', 'psa_email_to_ticket_enabled',
                     'psa_sms_notifications_enabled', 'psa_desktop_alerts_enabled',
                     'psa_external_alert_ingest_enabled'):
            self.assertNotIn(f'name="{name}"', html)
        self.assertIn('name="psa_closeout_require_time"', html)
        # Saving the page still works without them.
        r = self.client.post('/psa/settings/', {'psa_closeout_require_time': 'on', 'psa_ai_min_confidence': '0.8'})
        self.assertIn(r.status_code, (200, 302))
        self.assertTrue(SystemSetting.get_settings().psa_closeout_require_time)
