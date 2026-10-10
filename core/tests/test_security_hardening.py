"""
Regression tests for the v3.17.593 security hardening pass: emergency restart
webhook, secure-note link passwords, outbound webhook SSRF + role gate,
attachment delivery types, package-name validation, ping targets, and
client-IP resolution in the remaining hand-rolled helpers.
"""
from unittest.mock import MagicMock, patch

from django.conf import settings as django_settings
from django.contrib.auth.hashers import identify_hasher
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management.base import CommandError
from django.test import Client, RequestFactory, TestCase, override_settings

from accounts.models import Membership, Role
from core.models import Organization, SecureNote, Webhook, WebhookDelivery


TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def _login_in_org(client, user, org):
    client.force_login(user)
    s = client.session
    s['2fa_prompted'] = True
    s['current_organization_id'] = org.id
    s.save()


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class EmergencyRestartWebhookTests(TestCase):
    URL = '/core/emergency-restart/'

    def setUp(self):
        cache.clear()

    @override_settings(EMERGENCY_RESTART_SECRET='')
    def test_disabled_without_explicit_secret(self):
        self.assertEqual(Client().post(self.URL, HTTP_X_EMERGENCY_SECRET='x').status_code, 404)

    @override_settings(EMERGENCY_RESTART_SECRET='right-secret')
    def test_get_not_allowed(self):
        self.assertEqual(Client().get(self.URL, {'secret': 'right-secret'}).status_code, 405)

    @override_settings(EMERGENCY_RESTART_SECRET='right-secret')
    def test_query_string_secret_ignored(self):
        self.assertEqual(Client().post(self.URL + '?secret=right-secret').status_code, 403)

    @override_settings(EMERGENCY_RESTART_SECRET='right-secret')
    def test_wrong_secret_rejected(self):
        self.assertEqual(Client().post(self.URL, HTTP_X_EMERGENCY_SECRET='nope').status_code, 403)

    @override_settings(EMERGENCY_RESTART_SECRET='right-secret')
    @patch('subprocess.run')
    def test_right_secret_runs_without_leaking_output(self, run):
        run.return_value = MagicMock(returncode=0, stdout='internal paths', stderr='')
        resp = Client().post(self.URL, HTTP_X_EMERGENCY_SECRET='right-secret')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True})

    @override_settings(EMERGENCY_RESTART_SECRET='right-secret')
    def test_rate_limited(self):
        c = Client()
        codes = [c.post(self.URL, HTTP_X_EMERGENCY_SECRET='nope').status_code for _ in range(11)]
        self.assertEqual(codes[-1], 429)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SecureNoteLinkPasswordTests(TestCase):
    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(name='NoteCo', slug='note-co')
        self.sender = User.objects.create_user('note-sender', password='pw')
        Membership.objects.create(user=self.sender, organization=self.org,
                                  role=Role.OWNER, is_active=True)

    def _note(self, access_password):
        note = SecureNote(sender=self.sender, organization=self.org, title='t',
                          link_only=True, require_password=True,
                          access_password=access_password)
        note.set_content('the secret')
        note.generate_access_token()
        note.save()
        return note

    def test_create_stores_hash(self):
        c = Client()
        _login_in_org(c, self.sender, self.org)
        c.post('/core/secure-notes/create/', {
            'title': 'x', 'content': 'y', 'link_only': 'on',
            'require_password': 'on', 'access_password': 'hunter22',
        })
        note = SecureNote.objects.get(title='x')
        self.assertNotEqual(note.access_password, 'hunter22')
        identify_hasher(note.access_password)  # raises if not a hash

    def test_legacy_plaintext_upgraded_on_success(self):
        note = self._note('legacy-pw')
        resp = Client().post(f'/core/secret/{note.access_token}/', {'password': 'legacy-pw'})
        self.assertContains(resp, 'the secret')
        note.refresh_from_db()
        identify_hasher(note.access_password)

    def test_wrong_password_attempts_lock_out(self):
        note = self._note('right-pw')
        c = Client()
        for _ in range(10):
            c.post(f'/core/secret/{note.access_token}/', {'password': 'wrong'})
        resp = c.post(f'/core/secret/{note.access_token}/', {'password': 'right-pw'})
        self.assertNotContains(resp, 'the secret')
        self.assertContains(resp, 'Too many incorrect attempts')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class OutboundWebhookTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='HookCo', slug='hook-co')
        self.reader = User.objects.create_user('hook-reader', password='pw')
        Membership.objects.create(user=self.reader, organization=self.org,
                                  role=Role.READONLY, is_active=True)

    def test_readonly_member_cannot_create_webhook(self):
        c = Client()
        _login_in_org(c, self.reader, self.org)
        c.post('/core/webhooks/create/', {
            'name': 'probe', 'url': 'http://169.254.169.254/latest/meta-data/',
            'events': ['asset.created'], 'is_active': 'on',
        })
        self.assertFalse(Webhook.objects.filter(name='probe').exists())

    @override_settings(ALLOW_PRIVATE_IP_INTEGRATIONS=False)
    def test_delivery_to_internal_address_blocked(self):
        from core.webhook_sender import deliver_webhook
        hook = Webhook.objects.create(organization=self.org, name='internal',
                                      url='http://127.0.0.1:8000/', events=['asset.created'])
        self.assertFalse(deliver_webhook(hook, 'asset.created', {'id': 1}))
        delivery = WebhookDelivery.objects.get(webhook=hook)
        self.assertEqual(delivery.status, WebhookDelivery.STATUS_FAILED)
        self.assertIsNone(delivery.response_code)
        # Refused by the guard, not merely a closed port.
        self.assertIn('may not use', delivery.error_message)


class AttachmentDeliveryTypeTests(TestCase):
    def test_active_content_downloads_as_octet_stream(self):
        from files.views import _delivery_type
        for name in ('x.svg', 'x.html', 'x.xml', 'x.htm', 'noext'):
            self.assertEqual(_delivery_type(name), ('application/octet-stream', False), name)

    def test_safe_types_inline(self):
        from files.views import _delivery_type
        self.assertEqual(_delivery_type('a.png'), ('image/png', True))
        self.assertEqual(_delivery_type('a.pdf'), ('application/pdf', True))


class PackageNameValidationTests(TestCase):
    def test_option_injection_rejected(self):
        from core.management.commands.update_system_packages import parse_package_list
        for value in ('-oDPkg::Pre-Invoke=touch /tmp/x', 'curl,--allow-downgrades', 'a b'):
            with self.assertRaises(CommandError, msg=value):
                parse_package_list(value)

    def test_valid_names_accepted(self):
        from core.management.commands.update_system_packages import parse_package_list
        self.assertEqual(parse_package_list('openssl, libc6:amd64,g++'),
                         ['openssl', 'libc6:amd64', 'g++'])


class PingTargetTests(TestCase):
    def test_leading_dash_rejected(self):
        from locations.models import WAN
        wan = WAN(monitor_target='-fc100000', monitoring_enabled=True)
        with patch('subprocess.run') as run, self.assertRaises(ValueError):
            wan.check_status()
        run.assert_not_called()


@override_settings(TRUSTED_PROXY_CIDRS=['127.0.0.1/32'])
class SpoofedForwardedForTests(TestCase):
    """Helpers that used to trust the first X-Forwarded-For hop verbatim."""

    def test_untrusted_peer_cannot_choose_its_ip(self):
        from api.authentication import APIKeyAuthentication
        from api_mobile.auth_utils import client_ip
        from network_discovery.views import _client_ip as discovery_ip
        from psa.views import _client_ip as psa_ip
        request = RequestFactory().get('/', REMOTE_ADDR='203.0.113.9',
                                       HTTP_X_FORWARDED_FOR='10.0.0.1')
        for resolve in (APIKeyAuthentication().get_client_ip, client_ip, discovery_ip, psa_ip):
            self.assertEqual(resolve(request), '203.0.113.9')
