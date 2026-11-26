"""Phase 96.2–96.4: the first-install Setup Assistant.

Detection (fresh vs upgraded installs), who sees it, each step writing the
real settings idempotently, skip changing nothing, secrets never echoed, and
a complete run with no integration and no network.
"""
import importlib
import socket
from types import SimpleNamespace
from unittest import mock

from django.apps import apps as global_apps
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from audit.models import AuditLog
from core import setup_assistant as sa
from core.models import Organization, SystemSetting
from core.tests._r681_fixture import TEST_MIDDLEWARE
from onboarding.models import OnboardingSession as S, OnboardingStepState as St

PASSWORD = 'A-good-passphrase-91!'
SECRET = 'Sm7p-Secret-Value-Xq81'


def _client(user):
    c = Client()
    c.force_login(user)
    s = c.session
    s['2fa_prompted'] = True
    s.save()
    return c


def _state():
    return SystemSetting.objects.get(pk=1).setup_assistant_state


def _step_url(key):
    return reverse('core:setup_assistant_step', kwargs={'key': key})


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser('owner', 'owner@example.com', PASSWORD)
        self.ss = SystemSetting.get_settings()

    def start(self, c, path='advanced'):
        r = c.post(reverse('core:setup_assistant_action'), {'action': 'start', 'path': path})
        self.assertEqual(r.status_code, 302)
        return sa.open_session()


# ---------------------------------------------------------------------------
# 96.2 detection
# ---------------------------------------------------------------------------

class MigrationMarkTests(TestCase):
    """core 0126: rows that existed before (upgrades) are never 'offered'."""

    def setUp(self):
        self.mod = importlib.import_module('core.migrations.0126_systemsetting_setup_assistant')
        self.editor = SimpleNamespace(connection=SimpleNamespace(alias='default'))

    def test_new_row_defaults_to_offered(self):
        SystemSetting.objects.all().delete()
        self.assertEqual(SystemSetting.get_settings().setup_assistant_state, 'offered')

    def test_upgrade_with_users_and_row_is_not_offered(self):
        User.objects.create_user('existing')
        SystemSetting.objects.update_or_create(pk=1, defaults={'setup_assistant_state': 'offered'})
        self.mod.mark_install(global_apps, self.editor)
        self.assertEqual(_state(), 'not_offered')

    def test_upgrade_with_users_but_no_row_creates_it_not_offered(self):
        User.objects.create_user('existing')
        SystemSetting.objects.all().delete()
        self.mod.mark_install(global_apps, self.editor)
        self.assertEqual(_state(), 'not_offered')

    def test_fresh_database_stays_offered(self):
        SystemSetting.objects.all().delete()
        self.mod.mark_install(global_apps, self.editor)
        self.assertFalse(SystemSetting.objects.exists())   # created later by get_settings: 'offered'
        SystemSetting.objects.create(pk=1, setup_assistant_state='not_offered')
        self.mod.mark_install(global_apps, self.editor)
        self.assertEqual(_state(), 'offered')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DetectionTests(_Base):
    def test_fresh_install_is_offered(self):
        self.assertEqual(_state(), 'offered')
        self.assertTrue(sa.should_offer(self.admin))

    def test_setup_py_org_alone_still_fresh(self):
        Organization.objects.create(name='Our MSP', slug='our-msp')
        self.assertTrue(sa.looks_fresh())

    def test_second_user_fails_guard_for_good(self):
        User.objects.create_user('tech')
        self.assertFalse(sa.should_offer(self.admin))
        self.assertEqual(_state(), 'not_offered')
        User.objects.filter(username='tech').delete()
        self.assertFalse(sa.should_offer(self.admin))   # stays off

    def test_customers_fail_guard(self):
        Organization.objects.create(name='A', slug='a')
        Organization.objects.create(name='B', slug='b')
        self.assertFalse(sa.should_offer(self.admin))

    def test_tickets_fail_guard(self):
        from psa.models import Ticket
        with mock.patch.object(type(Ticket.objects), 'exists', return_value=True):
            self.assertFalse(sa.looks_fresh())

    def test_other_states_never_offered(self):
        for state in ('not_offered', 'completed', 'dismissed'):
            SystemSetting.objects.filter(pk=1).update(setup_assistant_state=state)
            self.assertFalse(sa.should_offer(self.admin), state)

    def test_in_progress_is_offered_even_after_customers_exist(self):
        SystemSetting.objects.filter(pk=1).update(setup_assistant_state='in_progress')
        Organization.objects.create(name='A', slug='a')
        Organization.objects.create(name='B', slug='b')
        self.assertTrue(sa.should_offer(self.admin))

    def test_non_superusers_never(self):
        staff = User.objects.create_user('staff', password=PASSWORD, is_staff=True)
        self.assertFalse(sa.should_offer(staff))
        c = _client(staff)
        self.assertEqual(c.get(reverse('core:setup_assistant')).status_code, 403)
        self.assertEqual(c.get(_step_url('setup_msp')).status_code, 403)
        self.assertEqual(c.post(reverse('core:setup_assistant_action'),
                                {'action': 'start'}).status_code, 403)
        s = c.session
        s[sa.SESSION_DUE_KEY] = True
        s.save()
        r = c.get(reverse('core:dashboard'))
        self.assertNotIn(reverse('core:setup_assistant'), r.get('Location', ''))

    def test_offer_once_per_sign_in_after_dashboard(self):
        c = _client(self.admin)
        s = c.session
        s[sa.SESSION_DUE_KEY] = True
        s.save()
        r = c.get(reverse('core:dashboard'))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], reverse('core:setup_assistant') + '?offer=1')
        r = c.get(reverse('core:dashboard'))
        self.assertNotIn(reverse('core:setup_assistant'), r.get('Location', ''))

    def test_upgraded_install_never_redirected(self):
        SystemSetting.objects.filter(pk=1).update(setup_assistant_state='not_offered')
        c = _client(self.admin)
        s = c.session
        s[sa.SESSION_DUE_KEY] = True
        s.save()
        r = c.get(reverse('core:dashboard'))
        self.assertNotIn(reverse('core:setup_assistant'), r.get('Location', ''))

    def test_force_login_does_not_arm_but_a_real_sign_in_does(self):
        from django.contrib.auth.signals import user_logged_in
        from django.test import RequestFactory
        c = _client(self.admin)
        self.assertNotIn(sa.SESSION_DUE_KEY, c.session)
        req = RequestFactory().post('/account/login/')
        req.session = {}
        user_logged_in.send(sender=User, request=req, user=self.admin)
        self.assertTrue(req.session.get(sa.SESSION_DUE_KEY))

    def test_later_dismisses_and_reopen_still_works(self):
        c = _client(self.admin)
        r = c.post(reverse('core:setup_assistant_action'), {'action': 'later'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(_state(), 'dismissed')
        self.assertFalse(sa.should_offer(self.admin))
        self.assertEqual(c.get(reverse('core:setup_assistant')).status_code, 200)
        self.start(c)
        self.assertEqual(_state(), 'dismissed')   # opening by hand never re-arms the offer

    def test_reachable_from_administration_general(self):
        from core import navigation
        tabs = [t for sec in navigation.SECTIONS if sec.key == 'settings_general' for t in sec.tabs]
        self.assertIn('core:setup_assistant', [t.url_name for t in tabs])


@override_settings(SECURE_SSL_REDIRECT=False)
class TwoFactorOrderingTests(TestCase):
    """Real middleware: no assistant page before 2FA enrolment."""

    def test_unenrolled_superuser_goes_to_2fa_setup_first(self):
        cache.clear()
        admin = User.objects.create_superuser('owner', 'owner@example.com', PASSWORD)
        SystemSetting.objects.filter(pk=1).update(require_2fa=True)
        from core import security_policy
        security_policy.invalidate()
        c = Client()
        c.force_login(admin)
        for url in (reverse('core:setup_assistant'), _step_url('setup_msp')):
            r = c.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertEqual(r['Location'], reverse('two_factor:setup'), url)


# ---------------------------------------------------------------------------
# 96.3 / 96.4 steps
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SessionTests(_Base):
    def test_install_session_has_no_tenant_and_stays_out_of_customer_onboarding(self):
        c = _client(self.admin)
        session = self.start(c, 'basic')
        self.assertEqual((session.kind, session.organization_id, session.client_id), ('install', None, None))
        self.assertEqual(_state(), 'in_progress')
        from onboarding import access
        self.assertFalse(access.sessions_for(self.admin).filter(pk=session.pk).exists())
        self.assertEqual(c.get(reverse('onboarding:session', args=[session.pk])).status_code, 404)

    def test_basic_path_skips_advanced_steps_without_changes(self):
        c = _client(self.admin)
        session = self.start(c, 'basic')
        skipped = set(session.step_states.filter(status=St.SKIPPED).values_list('step_key', flat=True))
        self.assertEqual(skipped, {'setup_modules', 'setup_team', 'setup_routing', 'setup_integrations'})
        c.post(reverse('core:setup_assistant_action'), {'action': 'path', 'path': 'advanced'})
        self.assertFalse(session.step_states.filter(status=St.SKIPPED).exists())

    def test_every_step_renders(self):
        c = _client(self.admin)
        self.start(c)
        from core import setup_assistant_steps as steps
        for step in steps.ordered():
            r = c.get(_step_url(step.key))
            self.assertEqual(r.status_code, 200, step.key)
            self.assertContains(r, 'id="stepTitle"')

    def test_constraint_keeps_tenant_for_other_kinds(self):
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError), transaction.atomic():
            S.objects.create(organization=None, kind=S.NEW_CUSTOMER)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class StepSaveTests(_Base):
    def setUp(self):
        super().setUp()
        self.c = _client(self.admin)
        self.session = self.start(self.c)

    def msp_post(self, **over):
        data = {'action': 'save', 'site_name': 'Acme IT', 'custom_company_name': 'Acme IT Ltd',
                'site_url': 'https://msp.example.com', 'default_timezone': 'Europe/London'}
        data.update(over)
        return self.c.post(_step_url('setup_msp'), data)

    def test_msp_step_writes_settings_and_is_idempotent(self):
        r = self.msp_post()
        self.assertEqual(r.status_code, 302)
        ss = SystemSetting.objects.get(pk=1)
        self.assertEqual((ss.site_name, ss.site_url, ss.default_timezone, ss.custom_company_name),
                         ('Acme IT', 'https://msp.example.com', 'Europe/London', 'Acme IT Ltd'))
        stamp = ss.updated_at
        self.msp_post()
        self.assertEqual(SystemSetting.objects.get(pk=1).updated_at, stamp)
        last = AuditLog.objects.filter(object_type='OnboardingSession').order_by('-pk').first()
        self.assertIn('nothing changed', last.description)
        # Reopen shows the current values.
        self.assertContains(self.c.get(_step_url('setup_msp')), 'value="https://msp.example.com"')

    def test_required_step_cannot_be_skipped(self):
        self.c.post(_step_url('setup_msp'), {'action': 'skip'})
        self.assertNotEqual(self.session.step_states.get(step_key='setup_msp').status, St.SKIPPED)

    def test_skip_leaves_settings_unchanged(self):
        before = SystemSetting.objects.filter(pk=1).values().first()
        orgs = Organization.objects.count()
        for key in ('setup_modules', 'setup_customer', 'setup_mail', 'setup_routing', 'setup_integrations'):
            self.c.post(_step_url(key), {'action': 'skip'})
            self.assertEqual(self.session.step_states.get(step_key=key).status, St.SKIPPED, key)
        after = SystemSetting.objects.filter(pk=1).values().first()
        before.pop('updated_at'), after.pop('updated_at')
        self.assertEqual(before, after)
        self.assertEqual(Organization.objects.count(), orgs)

    def security_post(self, **over):
        from core import security_policy
        data = {'action': 'save'}
        for k, v in security_policy.describe().items():
            if isinstance(v['value'], bool):
                if v['value']:
                    data[k] = 'on'
            else:
                data[k] = str(v['value'])
        data.update(over)
        return self.c.post(_step_url('setup_security'), data)

    def test_security_only_tightens(self):
        r = self.security_post(session_idle_timeout_minutes='120')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(SystemSetting.objects.get(pk=1).session_idle_timeout_minutes, 60)
        from core import security_policy
        before_2fa = SystemSetting.objects.get(pk=1).require_2fa
        r = self.security_post(require_2fa='')
        if security_policy.is_env_locked('require_2fa'):
            # Set by REQUIRE_2FA on the server: shown read-only, never written.
            self.assertContains(self.c.get(_step_url('setup_security')), 'environment variable')
        else:
            self.assertEqual(r.status_code, 400)
        self.assertEqual(SystemSetting.objects.get(pk=1).require_2fa, before_2fa)
        # Turning 2FA off is never accepted, whatever the environment says.
        with self.settings(REQUIRE_2FA=None):
            r = self.security_post(require_2fa='')
            self.assertEqual(r.status_code, 400)
            self.assertTrue(SystemSetting.objects.get(pk=1).require_2fa)
        r = self.security_post(session_idle_timeout_minutes='30', password_min_length='14')
        self.assertEqual(r.status_code, 302)
        ss = SystemSetting.objects.get(pk=1)
        self.assertEqual((ss.session_idle_timeout_minutes, ss.password_min_length), (30, 14))
        self.assertEqual(self.session.step_states.get(step_key='setup_security').status, St.DONE)

    def test_security_requires_default_password_change(self):
        from core import readiness
        self.admin.set_password(readiness.INSTALLER_PASSWORD)
        self.admin.save()
        c = _client(self.admin)
        self.assertContains(c.get(_step_url('setup_security')), 'default password')
        self.security_post()
        self.assertNotEqual(self.session.step_states.get(step_key='setup_security').status, St.DONE)

    def test_modules_step_switches_through_core_modules(self):
        from core import setup_assistant_steps as steps
        form = steps.ModulesForm()
        data = {'action': 'save'}
        for name in form.fields:
            data[name] = 'on'
        data.pop('module_crm')
        self.c.post(_step_url('setup_modules'), data)
        self.assertFalse(SystemSetting.objects.get(pk=1).crm_enabled)
        self.assertTrue(AuditLog.objects.filter(object_repr__startswith='Optional module:',
                                                description__contains='Turned off').exists())
        n = AuditLog.objects.filter(object_repr__startswith='Optional module:').count()
        self.c.post(_step_url('setup_modules'), data)
        self.assertEqual(AuditLog.objects.filter(object_repr__startswith='Optional module:').count(), n)

    def test_customer_step_creates_once(self):
        data = {'action': 'save', 'name': 'First Customer', 'organization_type': 'fully_managed'}
        self.c.post(_step_url('setup_customer'), data)
        org = Organization.objects.get(name='First Customer')
        self.assertTrue(org.memberships.filter(user=self.admin, role='owner').exists())
        self.c.post(_step_url('setup_customer'), data)
        self.assertEqual(Organization.objects.filter(name='First Customer').count(), 1)

    def test_routing_and_notifications(self):
        data = {'action': 'save', 'routing_mode': 'suggest', 'notify_on_ssl_expiry': 'on',
                'ssl_expiry_warning_days': '21', 'domain_expiry_warning_days': '30',
                'password_expiry_warning_days': '30'}
        r = self.c.post(_step_url('setup_routing'), data)
        self.assertEqual(r.status_code, 302)
        from psa.routing.models import RoutingSettings
        self.assertEqual(RoutingSettings.load().mode, 'suggest')
        ss = SystemSetting.objects.get(pk=1)
        self.assertEqual((ss.notify_on_ssl_expiry, ss.ssl_expiry_warning_days), (True, 21))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SecretTests(_Base):
    def test_smtp_password_saved_but_never_echoed(self):
        c = _client(self.admin)
        session = self.start(c)
        data = {'action': 'save', 'smtp_enabled': 'on', 'smtp_host': 'mail.example.com', 'smtp_port': '587',
                'smtp_username': 'desk', 'smtp_password': SECRET, 'smtp_use_tls': 'on',
                'smtp_from_email': 'desk@example.com', 'smtp_from_name': 'Desk'}
        r = c.post(_step_url('setup_mail'), data)
        self.assertEqual(r.status_code, 302)
        ss = SystemSetting.objects.get(pk=1)
        self.assertEqual(ss.smtp_password, SECRET)
        self.assertEqual(ss.smtp_host, 'mail.example.com')
        page = c.get(_step_url('setup_mail'))
        self.assertNotContains(page, SECRET)
        self.assertContains(page, 'A password is saved')
        # A form error re-renders without the password either.
        bad = dict(data, smtp_host='')
        r = c.post(_step_url('setup_mail'), bad)
        self.assertEqual(r.status_code, 400)
        self.assertNotContains(r, SECRET, status_code=400)
        session.refresh_from_db()
        self.assertNotIn(SECRET, str(session.data))
        self.assertIn('smtp_password', session.step_data('setup_mail').get('changed', []))
        for row in AuditLog.objects.all():
            self.assertNotIn(SECRET, f'{row.description} {row.extra_data} {row.object_repr}')
        review = c.get(_step_url('setup_review'))
        self.assertNotContains(review, SECRET)
        self.assertNotContains(review, 'mail.example.com')   # configured / not configured only

    def test_smtp_test_button_returns_to_the_assistant_only(self):
        c = _client(self.admin)
        self.start(c)
        nxt = _step_url('setup_mail')
        r = c.post(reverse('core:test_smtp_email'), {'test_email': 'x@example.com', 'next': nxt})
        self.assertEqual(r['Location'], nxt)
        r = c.post(reverse('core:test_smtp_email'), {'test_email': 'x@example.com', 'next': '/core/dashboard/'})
        self.assertEqual(r['Location'], reverse('core:settings_smtp'))


def _no_network(*args, **kwargs):
    raise OSError('network disabled in this test')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CompleteRunTests(_Base):
    def test_finish_with_no_integration_and_no_network(self):
        c = _client(self.admin)
        with mock.patch.object(socket.socket, 'connect', _no_network), \
                mock.patch.object(socket, 'create_connection', _no_network), \
                mock.patch.object(socket, 'getaddrinfo', _no_network):
            session = self.start(c, 'advanced')
            r = c.post(_step_url('setup_review'), {'action': 'save'})
            self.assertNotEqual(_state(), 'completed')   # required steps first
            c.post(_step_url('setup_msp'), {'action': 'save', 'site_name': 'Acme IT',
                                            'site_url': 'https://msp.example.com',
                                            'default_timezone': 'UTC'})
            c.post(_step_url('setup_security'), {'action': 'save', **_security_defaults()})
            for key in ('setup_modules', 'setup_team', 'setup_customer', 'setup_mail', 'setup_routing',
                        'setup_integrations'):
                c.post(_step_url(key), {'action': 'skip'})
            r = c.post(_step_url('setup_readiness'), {'action': 'save'})
            self.assertEqual(r.status_code, 302)
            r = c.post(_step_url('setup_review'), {'action': 'save'})
            self.assertEqual(r.status_code, 302)
        session.refresh_from_db()
        self.assertEqual(session.status, S.COMPLETED)
        ss = SystemSetting.objects.get(pk=1)
        self.assertEqual(ss.setup_assistant_state, 'completed')
        self.assertEqual(ss.setup_assistant_completed_by, self.admin)
        self.assertFalse(sa.should_offer(self.admin))
        # Reopening starts a fresh run that shows, and does not change, the values.
        page = c.get(reverse('core:setup_assistant'))
        self.assertContains(page, 'Setup was finished')
        self.start(c)
        self.assertEqual(_state(), 'completed')
        self.assertContains(c.get(_step_url('setup_msp')), 'value="Acme IT"')
        self.assertEqual(SystemSetting.objects.get(pk=1).site_name, 'Acme IT')


def _security_defaults():
    from core import security_policy
    data = {}
    for k, v in security_policy.describe().items():
        if isinstance(v['value'], bool):
            if v['value']:
                data[k] = 'on'
        else:
            data[k] = str(v['value'])
    return data

