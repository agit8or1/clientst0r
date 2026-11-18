"""API key lifecycle (v3.17.714, roadmap 81.4): expiry, per-key rate limit,
allowed sources set on the key, and rotation with a grace period."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, Role
from api import key_lifecycle as L
from api.models import APIKey
from api_access import policy as P
from api_access.models import ApiAccessRule as R
from api_access.tests import MIDDLEWARE
from audit.models import AuditLog
from core.models import Organization


@override_settings(MIDDLEWARE=MIDDLEWARE, SECURE_SSL_REDIRECT=False, TRUSTED_PROXY_CIDRS=['127.0.0.1/32'])
class _Base(TestCase):
    def setUp(self):
        P.reset_cache()
        cache.clear()
        self.org = Organization.objects.create(name='LC-A', slug='lc-a')
        self.user = User.objects.create_user('lc-owner', password='pw')
        self.other = User.objects.create_user('lc-other', password='pw')
        for u in (self.user, self.other):
            Membership.objects.create(user=u, organization=self.org, role=Role.OWNER, is_active=True)
        self.key, self.plain = APIKey.create_key(self.org, self.user, 'integration')

    def tearDown(self):
        P.reset_cache()

    def api(self, plain=None, remote='198.51.100.1'):
        return Client(HTTP_AUTHORIZATION=f'Bearer {plain or self.plain}', REMOTE_ADDR=remote).get('/api/assets/')

    def web(self, user=None):
        c = Client()
        c.force_login(user or self.user)
        s = c.session
        s['current_organization_id'] = self.org.pk
        s.save()
        return c


class ParsingTests(TestCase):
    def test_sources(self):
        self.assertEqual(L.parse_sources('192.168.22.10\n10.0.0.5/24, 2001:db8:1234::/48\n# comment\n\n'),
                         ['10.0.0.0/24', '192.168.22.10/32', '2001:db8:1234::/48'])
        self.assertEqual(L.parse_sources(''), [])
        with self.assertRaises(ValidationError):
            L.parse_sources('10.0.0.1\nnot-an-address')
        with self.assertRaises(ValidationError):
            L.parse_sources('\n'.join(f'10.0.{i}.0/24' for i in range(L.MAX_SOURCES + 1)))

    def test_expiry_and_rate(self):
        self.assertIsNone(L.parse_expiry('', ''))
        self.assertAlmostEqual((L.parse_expiry('30', '') - timezone.now()).days, 29, delta=1)
        future = (timezone.now() + timedelta(days=10)).strftime('%Y-%m-%d')
        self.assertIsNotNone(L.parse_expiry('custom', future))
        for bad in (('custom', '2001-01-01'), ('custom', 'soon'), ('7', '')):
            with self.assertRaises(ValidationError):
                L.parse_expiry(*bad)
        self.assertIsNone(L.parse_rate(''))
        self.assertEqual(L.parse_rate('120'), 120)
        for bad in ('0', '-1', 'x', '10001'):
            with self.assertRaises(ValidationError):
                L.parse_rate(bad)


class ExpiryTests(_Base):
    def test_expired_key_is_refused_and_not_marked_used(self):
        APIKey.objects.filter(pk=self.key.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        r = self.api()
        self.assertEqual(r.status_code, 401)
        self.assertIn('expired', r.json()['detail'])
        self.key.refresh_from_db()
        self.assertIsNone(self.key.last_used_at)

    def test_unexpired_key_works(self):
        APIKey.objects.filter(pk=self.key.pk).update(expires_at=timezone.now() + timedelta(days=1))
        self.assertEqual(self.api().status_code, 200)


class RateLimitTests(_Base):
    def test_per_key_limit(self):
        APIKey.objects.filter(pk=self.key.pk).update(rate_limit_per_minute=3)
        codes = [self.api().status_code for _ in range(5)]
        self.assertEqual(codes, [200, 200, 200, 429, 429])

    def test_no_limit_means_standard_limits_only(self):
        codes = {self.api().status_code for _ in range(5)}
        self.assertEqual(codes, {200})

    def test_limit_is_per_key(self):
        APIKey.objects.filter(pk=self.key.pk).update(rate_limit_per_minute=1)
        _, other_plain = APIKey.create_key(self.org, self.user, 'second')
        self.assertEqual(self.api().status_code, 200)
        self.assertEqual(self.api().status_code, 429)
        self.assertEqual(self.api(other_plain).status_code, 200)


class SourcesTests(_Base):
    def test_create_with_sources_restricts_the_key(self):
        c = self.web()
        r = c.post('/api/keys/create/', {'name': 'SIEM-WAZUH-PRODUCTION', 'role': 'readonly', 'scope': 'single',
                                         'expiry': '90', 'rate_limit_per_minute': '600',
                                         'allowed_sources': '192.168.22.10\n10.0.0.0/24\n2001:db8:1234::/48'})
        self.assertEqual(r.status_code, 200)
        key = APIKey.objects.get(name='SIEM-WAZUH-PRODUCTION')
        self.assertEqual(key.rate_limit_per_minute, 600)
        self.assertIsNotNone(key.expires_at)
        self.assertEqual(L.key_sources(key), ['10.0.0.0/24', '192.168.22.10/32', '2001:db8:1234::/48'])
        plain = r.context['plaintext_key']
        self.assertEqual(self.api(plain, '10.0.0.9').status_code, 200)
        self.assertEqual(self.api(plain, '203.0.113.9').status_code, 403)
        # the secret never reaches the refusal log or the audit log
        from api_access.models import ApiAccessDecision
        self.assertNotIn(plain, str(list(ApiAccessDecision.objects.values())))
        self.assertNotIn(plain, str(list(AuditLog.objects.values('description', 'extra_data'))))

    def test_bad_source_refuses_the_whole_form(self):
        c = self.web()
        c.post('/api/keys/create/', {'name': 'bad', 'role': 'readonly', 'scope': 'single',
                                     'allowed_sources': '10.0.0.1\nexample.com'})
        self.assertFalse(APIKey.objects.filter(name='bad').exists())

    def test_edit_that_cuts_off_last_address_needs_confirmation(self):
        APIKey.objects.filter(pk=self.key.pk).update(last_used_ip='198.51.100.1', last_used_at=timezone.now())
        c = self.web()
        data = {'name': 'integration', 'expiry': 'keep', 'allowed_sources': '10.0.0.0/8'}
        r = c.post(f'/api/keys/{self.key.pk}/edit/', data)
        self.assertContains(r, 'Save anyway')
        self.assertEqual(L.key_sources(self.key), [])
        c.post(f'/api/keys/{self.key.pk}/edit/', dict(data, confirm='1'))
        self.assertEqual(L.key_sources(self.key), ['10.0.0.0/8'])
        self.assertEqual(self.api(remote='198.51.100.1').status_code, 403)
        # clearing the sources lifts the key restriction
        c.post(f'/api/keys/{self.key.pk}/edit/', {'name': 'integration', 'expiry': 'keep', 'allowed_sources': ''})
        self.assertEqual(self.api(remote='198.51.100.1').status_code, 200)

    def test_customer_user_cannot_edit_someone_elses_key(self):
        stranger = User.objects.create_user('lc-stranger', password='pw')
        Membership.objects.create(user=stranger, organization=self.org, role=Role.READONLY, is_active=True)
        c = self.web(stranger)
        c.post(f'/api/keys/{self.key.pk}/edit/', {'name': 'x', 'expiry': 'keep', 'allowed_sources': '10.0.0.0/8'})
        self.key.refresh_from_db()
        self.assertEqual(self.key.name, 'integration')
        self.assertEqual(L.key_sources(self.key), [])


class RotationTests(_Base):
    def test_rotation_with_grace_period(self):
        L.set_sources(self.key, ['198.51.100.0/24'], self.user)
        APIKey.objects.filter(pk=self.key.pk).update(rate_limit_per_minute=50)
        c = self.web()
        r = c.post(f'/api/keys/{self.key.pk}/rotate/', {'grace': '24'})
        self.assertEqual(r.status_code, 200)
        new_plain = r.context['plaintext_key']
        new = APIKey.objects.get(rotated_from=self.key)
        self.key.refresh_from_db()
        self.assertTrue(self.key.is_active)
        self.assertIsNotNone(self.key.rotated_at)
        self.assertAlmostEqual((self.key.expires_at - timezone.now()).total_seconds(), 86400, delta=60)
        self.assertEqual((new.name, new.role, new.scope, new.rate_limit_per_minute, new.user),
                         (self.key.name, self.key.role, self.key.scope, 50, self.user))
        self.assertEqual(L.key_sources(new), ['198.51.100.0/24'])
        self.assertEqual(self.api(new_plain).status_code, 200)
        self.assertEqual(self.api().status_code, 200)  # old key still inside its grace period
        self.assertEqual(self.api(new_plain, '203.0.113.1').status_code, 403)
        self.assertTrue(AuditLog.objects.filter(object_type='APIKey', object_id=self.key.pk,
                                                description__contains='rotated').exists())

    def test_rotation_without_grace_stops_old_key(self):
        c = self.web()
        c.post(f'/api/keys/{self.key.pk}/rotate/', {'grace': '0'})
        self.key.refresh_from_db()
        self.assertFalse(self.key.is_active)
        self.assertEqual(self.api().status_code, 401)

    def test_grace_never_extends_an_earlier_expiry(self):
        soon = timezone.now() + timedelta(hours=2)
        APIKey.objects.filter(pk=self.key.pk).update(expires_at=soon)
        self.key.refresh_from_db()
        L.rotate(self.key, self.user, 168)
        self.key.refresh_from_db()
        self.assertLessEqual(self.key.expires_at, soon)

    def test_only_the_owner_can_rotate(self):
        c = self.web(self.other)  # manages the customer's keys, but is not the owner
        r = c.post(f'/api/keys/{self.key.pk}/rotate/', {'grace': '24'})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(APIKey.objects.filter(rotated_from=self.key).exists())
