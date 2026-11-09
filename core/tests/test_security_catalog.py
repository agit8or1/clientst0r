"""Security Features catalog and the administrators' effective-state page (v3.17.651).

The public pages describe what ships; only superusers see what is in effect
at a customer, read from the same settings the code enforces.
"""
import os
from pathlib import Path

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role
from core import security_features as sf
from core.models import Organization, SystemSetting

TEST_MIDDLEWARE = [m for m in django_settings.MIDDLEWARE
                   if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m]
REPO = Path(django_settings.BASE_DIR)


class CatalogShapeTests(TestCase):
    def test_every_entry_is_complete_and_grouped(self):
        groups = {k for k, _ in sf.GROUPS}
        keys = [f['key'] for f in sf.FEATURES]
        self.assertEqual(len(keys), len(set(keys)))
        for f in sf.FEATURES:
            with self.subTest(f['key']):
                self.assertIn(f['group'], groups)
                self.assertIn(f['status'], sf.STATUS_LABELS)
                for field in ('title', 'protects', 'default', 'prerequisites', 'doc'):
                    self.assertTrue(f[field].strip(), field)
                self.assertTrue(f['tests'])
                self.assertIn(f['key'], sf.EFFECTIVE)
                if f['link']:
                    reverse(f['link'])

    def test_docs_and_tests_named_by_the_catalog_exist(self):
        for f in sf.FEATURES:
            with self.subTest(f['key']):
                doc, _, anchor = f['doc'].partition('#')
                path = REPO / doc
                self.assertTrue(path.exists(), doc)
                if anchor:
                    headings = [line.lstrip('#').strip().lower() for line in path.read_text().splitlines()
                                if line.startswith('#')]
                    slugs = {''.join(c for c in h.replace(' ', '-') if c.isalnum() or c == '-') for h in headings}
                    self.assertIn(anchor, slugs, f['doc'])
                for label in f['tests']:
                    parts = label.split('.')
                    candidates = [REPO.joinpath(*parts).with_suffix('.py'), REPO.joinpath(*parts, '__init__.py'),
                                  REPO.joinpath(*parts)]
                    self.assertTrue(any(c.exists() for c in candidates), label)

    def test_ai_entries_are_tagged_optional_ai(self):
        self.assertIn('OPTIONAL AI', sf.FEATURES[[f['key'] for f in sf.FEATURES].index('ai_opt_in')]['title'])

    def test_no_planned_items_in_the_shipped_catalog(self):
        for f in sf.FEATURES:
            text = ' '.join(str(f[k]) for k in ('title', 'default', 'detail')).lower()
            self.assertNotIn('(planned)', text, f['key'])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SecurityFeaturesPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Example Accounting', slug='ex-acct')
        cls.other = Organization.objects.create(name='Example Clinic', slug='ex-clinic')
        cls.su = User.objects.create_user('sf_su', 'su@msp.test', 'pw-sf-123!', is_superuser=True, is_staff=True)
        cls.owner = User.objects.create_user('sf_owner', 'o@acct.test', 'pw-sf-123!')
        Membership.objects.create(user=cls.owner, organization=cls.org, role=Role.OWNER, is_active=True)
        cls.reader = User.objects.create_user('sf_reader', 'r@acct.test', 'pw-sf-123!')
        Membership.objects.create(user=cls.reader, organization=cls.org, role=Role.READONLY, is_active=True)

    def _get(self, user, **params):
        self.client.force_login(user)
        return self.client.get(reverse('core:security_features'), params)

    def test_superuser_sees_every_group_and_the_selected_customer(self):
        r = self._get(self.su, org=self.org.pk)
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        for _, label in sf.GROUPS:
            self.assertIn(label, html)
        self.assertIn('At Example Accounting', html)
        self.assertNotIn('Could not be read', html)

    def test_customer_users_get_403_by_direct_url(self):
        for user in (self.owner, self.reader):
            self.assertEqual(self._get(user, org=self.org.pk).status_code, 403)

    def test_effective_state_follows_the_customer(self):
        states = {f['key']: f['effective'] for f in sf.effective_states(self.org)}
        self.assertIn('1 of 2 members here may reveal', states['reveal_permission']['text'])
        self.assertEqual(states['per_route_authorization']['state'], 'off')
        self.assertEqual(states['ai_opt_in']['state'], 'off')
        other = {f['key']: f['effective'] for f in sf.effective_states(self.other)}
        self.assertIn('0 of 0 members', other['reveal_permission']['text'])

    def test_ai_state_needs_global_switch_and_customer_policy(self):
        from psa_ai.models import AIBusinessPolicy
        AIBusinessPolicy.objects.create(organization=self.org, analysis_enabled=True, daily_budget_cents=500)
        state = lambda: {f['key']: f['effective'] for f in sf.effective_states(self.org)}['ai_opt_in']
        self.assertEqual(state()['state'], 'off')  # AI off for the install
        s = SystemSetting.get_settings()
        s.psa_ai_enabled = True
        s.save()
        self.assertEqual(state()['state'], 'on')
        self.assertIn('budget $5.00/day', state()['text'])

    def test_environment_override_is_named(self):
        with override_settings(REQUIRE_2FA=False):
            two_fa = {f['key']: f['effective'] for f in sf.effective_states(self.org)}['two_factor']
        self.assertEqual(two_fa['env'], ['REQUIRE_2FA'])
        self.assertEqual(two_fa['state'], 'off')
        self.assertIn('Optional', two_fa['text'])

    def test_a_failing_check_shows_unknown_not_on(self):
        with self.settings():
            original = sf.EFFECTIVE['access_rules']
            sf.EFFECTIVE['access_rules'] = lambda org: 1 / 0
            try:
                state = {f['key']: f['effective'] for f in sf.effective_states(self.org)}['access_rules']
            finally:
                sf.EFFECTIVE['access_rules'] = original
        self.assertEqual(state['state'], 'unknown')

    def test_menu_shows_the_page_to_superusers_only(self):
        url = reverse('core:security_features')
        self.client.force_login(self.su)
        self.assertIn(url, self.client.get(reverse('core:security_dashboard')).content.decode())
        self.client.force_login(self.owner)
        self.assertNotIn(url, self.client.get(reverse('core:about')).content.decode())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PublicPagesTests(TestCase):
    def test_about_lists_groups_without_effective_state_or_overclaims(self):
        html = self.client.get(reverse('core:about')).content.decode()
        for _, label in sf.GROUPS:
            self.assertIn(label, html)
        for claim in ('military-grade', 'Suite B', 'ASVS', 'Logs immutable', '1-hour cooldown', 'No Docker'):
            self.assertNotIn(claim, html)
        self.assertNotIn('members here may reveal', html)

    def test_about_2fa_status_reflects_the_user(self):
        u = User.objects.create_user('sf_plain', 'p@x.test', 'pw-sf-123!')
        self.client.force_login(u)
        self.assertIn('Not set up', self.client.get(reverse('core:about')).content.decode())

    def test_documentation_page_lists_groups(self):
        u = User.objects.create_user('sf_doc', 'd@x.test', 'pw-sf-123!')
        self.client.force_login(u)
        html = self.client.get(reverse('core:documentation')).content.decode()
        for _, label in sf.GROUPS:
            self.assertIn(label, html)
        self.assertNotIn('1-hour cooldown', html)
        self.assertNotIn('Logs immutable', html)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AuditCleanupIsRecordedTests(TestCase):
    def test_maintenance_cleanup_and_admin_delete_leave_a_record(self):
        from datetime import timedelta
        from django.utils import timezone
        from audit.models import AuditLog
        su = User.objects.create_user('sf_purge', 'p@msp.test', 'pw-sf-123!', is_superuser=True, is_staff=True)
        old = AuditLog.log(user=su, action='read', description='old entry')
        AuditLog.objects.filter(pk=old.pk).update(timestamp=timezone.now() - timedelta(days=400))
        self.client.force_login(su)
        self.client.post(reverse('core:maintenance'), {'action': 'cleanup_audit_logs', 'days': '90'})
        self.assertFalse(AuditLog.objects.filter(pk=old.pk).exists())
        rec = AuditLog.objects.get(extra_data__event='audit_log_cleanup')
        self.assertEqual(rec.extra_data['deleted'], 1)
        victim = AuditLog.log(user=su, action='read', description='to delete')
        self.client.post(reverse('admin:audit_auditlog_delete', args=[victim.pk]), {'post': 'yes'})
        self.assertFalse(AuditLog.objects.filter(pk=victim.pk).exists())
        self.assertTrue(AuditLog.objects.filter(extra_data__event='audit_log_admin_delete').exists())
