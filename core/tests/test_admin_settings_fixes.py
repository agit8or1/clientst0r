"""Fixes found while documenting Administration settings (roadmap 112.8).

Package scanner access, fail2ban address handling, firewall rule validation,
firewall/fail2ban audit entries and the AI & LLM page's saved keys. Nothing
here touches the host: the root helper and process signalling are mocked.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from audit.models import AuditLog
from core.models import FirewallIPRule, FirewallSettings, SystemPackageScan


TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
    and 'FirewallMiddleware' not in m
]


def _login(client, user):
    client.force_login(user)
    s = client.session
    s['2fa_prompted'] = True
    s.save()


class _Base(TestCase):

    def setUp(self):
        self.su = User.objects.create_user('fix-su', password='pw', is_superuser=True, is_staff=True)
        self.staff = User.objects.create_user('fix-staff', password='pw', is_staff=True)
        self.client = Client()


# ---------------------------------------------------------------------------
# 1. OS package scanner: superusers only
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PackageScannerSuperuserOnlyTests(_Base):

    def setUp(self):
        super().setUp()
        self.scan = SystemPackageScan.objects.create(
            package_manager='apt', total_packages=100, upgradeable_packages=4, security_updates=2)

    def test_staff_flag_alone_cannot_open_the_scanner_pages(self):
        _login(self.client, self.staff)
        for url in (reverse('core:package_scanner_dashboard'),
                    reverse('core:scan_detail', args=[self.scan.pk])):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertEqual(r['Location'], reverse('core:dashboard'))
        r = self.client.get(reverse('core:package_scanner_widget_data'))
        self.assertEqual(r.status_code, 403)

    def test_staff_flag_alone_cannot_scan_or_update_packages(self):
        _login(self.client, self.staff)
        with mock.patch('core.security_views.call_command') as cc:
            r = self.client.post(reverse('core:update_packages'), {'security_only': 'true'})
            self.assertEqual(r.status_code, 403)
            r = self.client.post(reverse('core:run_package_scan'))
            self.assertEqual(r.status_code, 403)
        cc.assert_not_called()

    def test_superuser_sees_the_page_and_update_buttons(self):
        _login(self.client, self.su)
        r = self.client.get(reverse('core:package_scanner_dashboard'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="updateSecurityBtn"')
        self.assertContains(r, 'id="updateAllBtn"')

    def test_superuser_can_run_update(self):
        _login(self.client, self.su)
        with mock.patch('core.security_views.call_command') as cc:
            r = self.client.post(reverse('core:update_packages'), {'dry_run': 'true'})
        self.assertEqual(r.status_code, 200)
        cc.assert_called_once()

    def test_python_scanner_hides_os_link_for_staff_flag(self):
        _login(self.client, self.staff)
        r = self.client.get(reverse('core:python_scanner_dashboard'))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, reverse('core:package_scanner_dashboard'))


# ---------------------------------------------------------------------------
# 2 + 4. Fail2ban: exact address match, IPv6 unban, audit entries
# ---------------------------------------------------------------------------

STATUS = 'Status\n|- Number of jail:\t1\n`- Jail list:\tsshd\n'
JAIL = ('Status for the jail: sshd\n|- Filter\n|  `- Total failed: 3\n`- Actions\n'
        '   |- Currently banned:\t2\n   |- Total banned:\t2\n'
        '   `- Banned IP list:\t11.2.3.45 2001:db8::5\n')


class _FakeHelper:
    """Stands in for core.root_helper: records argv, never runs anything."""

    def __init__(self):
        self.calls = []

    def run(self, args, timeout=None):
        self.calls.append(list(args))
        out = STATUS if args == ['fail2ban', 'status'] else JAIL if args[:2] == ['fail2ban', 'status'] else ''
        return subprocess.CompletedProcess(args, 0, stdout=out, stderr='')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class Fail2banAddressTests(_Base):

    def setUp(self):
        super().setUp()
        self.helper = _FakeHelper()
        patches = [
            mock.patch('core.fail2ban_views._fail2ban_client_path', return_value='/usr/bin/fail2ban-client'),
            mock.patch('core.fail2ban_views.root_helper.is_installed', return_value=True),
            mock.patch('core.fail2ban_views.root_helper.run', side_effect=self.helper.run),
            mock.patch('core.fail2ban_views.subprocess.run',
                       side_effect=AssertionError('must not shell out in tests')),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        _login(self.client, self.su)

    def check(self, ip):
        return self.client.get(reverse('core:fail2ban_check_ip'), {'ip': ip})

    def test_check_does_not_match_a_substring(self):
        r = self.check('1.2.3.4')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['is_banned'])

    def test_check_matches_the_exact_address_ipv4_and_ipv6(self):
        self.assertEqual(self.check('11.2.3.45').json()['jails'], ['sshd'])
        # Another spelling of the same IPv6 address still matches.
        r = self.check('2001:0db8:0:0::5')
        self.assertTrue(r.json()['is_banned'])
        self.assertEqual(r.json()['ip_address'], '2001:db8::5')
        self.assertFalse(self.check('2001:db8::50').json()['is_banned'])

    def test_check_rejects_garbage(self):
        self.assertEqual(self.check('1.2.3.4; rm -rf /').status_code, 400)

    def test_unban_accepts_ipv6_and_audits(self):
        r = self.client.post(reverse('core:fail2ban_unban_ip'),
                             {'ip_address': '2001:0DB8::5', 'jail_name': 'sshd'})
        self.assertEqual(r.status_code, 302)
        self.assertIn(['fail2ban', 'unban', 'sshd', '2001:db8::5'], self.helper.calls)
        entry = AuditLog.objects.filter(object_type='core.Fail2ban').latest('id')
        self.assertEqual(entry.user, self.su)
        self.assertEqual(entry.extra_data['ip_address'], '2001:db8::5')
        self.assertIn('Unbanned 2001:db8::5', entry.description)

    def test_unban_rejects_invalid_before_the_helper(self):
        for bad in ('999.1.1.1', 'not-an-ip', '1.2.3.4 5.6.7.8', '::g'):
            self.client.post(reverse('core:fail2ban_unban_ip'), {'ip_address': bad, 'jail_name': 'sshd'})
        self.assertFalse([c for c in self.helper.calls if 'unban' in c])
        self.assertFalse(AuditLog.objects.filter(object_type='core.Fail2ban').exists())

    def test_unban_all_handles_ipv6_and_audits(self):
        self.client.post(reverse('core:fail2ban_unban_all'), {'jail_name': 'sshd'})
        unbans = [c for c in self.helper.calls if 'unban' in c]
        self.assertEqual(unbans, [['fail2ban', 'unban', 'sshd', '11.2.3.45'],
                                  ['fail2ban', 'unban', 'sshd', '2001:db8::5']])
        entry = AuditLog.objects.filter(object_type='core.Fail2ban').latest('id')
        self.assertEqual(entry.extra_data['ip_addresses'], ['11.2.3.45', '2001:db8::5'])

    def test_start_is_audited(self):
        self.client.post(reverse('core:fail2ban_start'))
        self.assertTrue(AuditLog.objects.filter(object_type='core.Fail2ban',
                                                description='Started fail2ban').exists())


# ---------------------------------------------------------------------------
# 3 + 4. Firewall IP rules: validation, invalid rows flagged, audit entries
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class FirewallIPRuleTests(_Base):

    def setUp(self):
        super().setUp()
        _login(self.client, self.su)
        self.url = reverse('core:firewall_ip_rules')

    def test_invalid_entries_are_refused_with_a_form_error(self):
        for bad in ('not an ip', '10.0.0.300', '10.0.0.0/33', '1.2.3.4-1.2.3.9', 'fe80::zz'):
            r = self.client.post(self.url, {'ip_address': bad, 'description': 'x'})
            self.assertEqual(r.status_code, 400, bad)
            self.assertContains(r, 'is not an IP address or CIDR range', status_code=400)
            self.assertContains(r, 'is-invalid', status_code=400)
        self.assertFalse(FirewallIPRule.objects.exists())
        self.assertFalse(AuditLog.objects.filter(object_type='core.FirewallIPRule').exists())

    def test_ipv4_ipv6_and_cidr_are_saved_in_canonical_form(self):
        for entry, stored in (('203.0.113.50', '203.0.113.50'),
                              ('10.0.0.5/24', '10.0.0.0/24'),
                              ('2001:0DB8::1', '2001:db8::1'),
                              ('2001:db8::/32', '2001:db8::/32')):
            r = self.client.post(self.url, {'ip_address': entry})
            self.assertEqual(r.status_code, 302, entry)
            self.assertTrue(FirewallIPRule.objects.filter(ip_address=stored).exists(), stored)
        rule = FirewallIPRule.objects.get(ip_address='2001:db8::1')
        self.assertTrue(rule.matches_ip('2001:db8:0::1'))
        self.assertTrue(FirewallIPRule.objects.get(ip_address='2001:db8::/32').matches_ip('2001:db8:1::9'))

    def test_model_clean_validates(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            FirewallIPRule(ip_address='garbage').full_clean()

    def test_existing_invalid_rows_are_flagged_not_deleted(self):
        bad = FirewallIPRule.objects.create(ip_address='office router')
        FirewallIPRule.objects.create(ip_address='192.168.1.0/24')
        r = self.client.get(self.url)
        self.assertContains(r, f'data-invalid-rule="{bad.pk}"')
        self.assertContains(r, 'never matches any request')
        self.assertContains(r, 'office router')
        self.assertTrue(FirewallIPRule.objects.filter(pk=bad.pk).exists())
        self.assertFalse(bad.matches_ip('10.0.0.1'))

    def test_add_toggle_delete_are_audited(self):
        self.client.post(self.url, {'ip_address': '198.51.100.7', 'description': 'VPN'})
        rule = FirewallIPRule.objects.get()
        self.client.post(reverse('core:firewall_ip_rule_toggle', args=[rule.pk]))
        self.client.post(reverse('core:firewall_ip_rule_delete', args=[rule.pk]))
        rows = list(AuditLog.objects.filter(object_type='core.FirewallIPRule').order_by('id'))
        self.assertEqual([r.action for r in rows], ['create', 'update', 'delete'])
        self.assertTrue(all(r.user == self.su for r in rows))
        self.assertIn('Disabled', rows[1].description)
        self.assertEqual(rows[2].extra_data['ip_address'], '198.51.100.7')

    def test_enabling_the_firewall_is_audited(self):
        FirewallSettings.get_settings()
        self.client.post(reverse('core:firewall_settings'), {
            'ip_firewall_enabled': 'on', 'ip_firewall_mode': 'blocklist',
            'geoip_firewall_mode': 'blocklist', 'log_blocked_requests': 'on', 'bypass_for_staff': 'on'})
        entry = AuditLog.objects.filter(object_type='core.FirewallSettings').latest('id')
        self.assertEqual(entry.extra_data['changed']['ip_firewall_enabled'], {'from': False, 'to': True})

    def test_country_rule_changes_are_audited(self):
        from core.models import FirewallCountryRule
        self.client.post(reverse('core:firewall_country_rules'),
                         {'country_code': 'fr', 'country_name': 'France'})
        rule = FirewallCountryRule.objects.get(country_code='FR')
        self.client.post(reverse('core:firewall_country_rule_toggle', args=[rule.pk]))
        self.client.post(reverse('core:firewall_country_rule_delete', args=[rule.pk]))
        actions = list(AuditLog.objects.filter(object_type='core.FirewallCountryRule')
                       .order_by('id').values_list('action', flat=True))
        self.assertEqual(actions, ['create', 'update', 'delete'])


# ---------------------------------------------------------------------------
# 5. AI & LLM: saved keys never reach the page
# ---------------------------------------------------------------------------

SECRET = 'sk-ant-api03-SECRET-VALUE-do-not-render-1234567890'
MAPS = 'AIzaSECRETMAPSKEY0987654321'


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AISettingsKeyTests(_Base):

    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / '.env').write_text(
            f'ANTHROPIC_API_KEY={SECRET}\nGOOGLE_MAPS_API_KEY={MAPS}\nOTHER=keep\n')
        o = override_settings(BASE_DIR=self.tmp)
        o.enable()
        self.addCleanup(o.disable)
        # Saving signals gunicorn: make sure nothing real is found or signalled.
        for p in (mock.patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0, stdout='', stderr='')),
                  mock.patch('os.kill')):
            p.start()
            self.addCleanup(p.stop)
        _login(self.client, self.su)
        self.url = reverse('core:settings_ai')

    def env(self):
        return dict(line.split('=', 1) for line in (self.tmp / '.env').read_text().splitlines() if '=' in line)

    def test_saved_keys_never_appear_in_the_page(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertNotIn(SECRET, html)
        self.assertNotIn(MAPS, html)
        self.assertIn('A key is set', html)
        self.assertIn('name="clear_anthropic_api_key"', html)
        self.assertNotIn('name="clear_openai_api_key"', html)  # no key saved there

    def test_blank_submission_keeps_the_key(self):
        self.client.post(self.url, {'llm_provider': 'anthropic', 'anthropic_api_key': '',
                                    'google_maps_api_key': ''})
        env = self.env()
        self.assertEqual(env['ANTHROPIC_API_KEY'], SECRET)
        self.assertEqual(env['GOOGLE_MAPS_API_KEY'], MAPS)
        self.assertEqual(env['OTHER'], 'keep')

    def test_new_value_replaces_and_clear_removes(self):
        self.client.post(self.url, {'llm_provider': 'anthropic', 'anthropic_api_key': 'sk-ant-new',
                                    'clear_google_maps_api_key': '1'})
        env = self.env()
        self.assertEqual(env['ANTHROPIC_API_KEY'], 'sk-ant-new')
        self.assertEqual(env['GOOGLE_MAPS_API_KEY'], '')

    def test_line_breaks_cannot_add_env_lines(self):
        self.client.post(self.url, {'llm_provider': 'anthropic', 'anthropic_api_key': 'abc\nDEBUG=True'})
        self.assertNotIn('DEBUG', self.env())

    def test_test_button_with_blank_field_uses_the_saved_key(self):
        with mock.patch('core.services.api_key_validator.APIKeyValidator.validate_anthropic',
                        return_value=(True, 'ok', {})) as v:
            r = self.client.post(reverse('core:validate_anthropic_key'), '{"api_key": ""}',
                                 content_type='application/json')
        self.assertEqual(r.status_code, 200)
        v.assert_called_once_with(SECRET)
        self.assertNotIn(SECRET, r.content.decode())
