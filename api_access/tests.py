"""API access control (Phase 81): policy engine, enforcement, client address
resolution, admin pages and recovery."""
import io
import json
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import DatabaseError
from django.http import HttpResponse
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, Role
from api.models import APIKey
from api.tests_view_permissions import TEST_MIDDLEWARE as API_TEST_MIDDLEWARE
from audit.models import AuditLog
from core.models import Organization

from . import policy as P
from .enforce import ApiAccessMiddleware
from .groups import ENDPOINT_GROUPS, INTEGRATIONS, classify
from .models import ApiAccessDecision, ApiAccessRule as R, ApiAccessSettings as S, normalize_network

MIDDLEWARE = list(API_TEST_MIDDLEWARE)
MIDDLEWARE.insert(MIDDLEWARE.index('django.middleware.common.CommonMiddleware') + 1,
                  'api_access.enforce.ApiAccessMiddleware')

ip = P.parse_ip


def rule(network, action=R.ACTION_ALLOW, scope=R.SCOPE_GLOBAL, surface=R.SURFACE_API, **kw):
    row = {'id': kw.pop('id', 1), 'name': kw.pop('name', network), 'action': action,
           'surface': surface, 'scope': scope, 'organization_id': kw.pop('organization_id', None),
           'api_key_id': kw.pop('api_key_id', None), 'target': kw.pop('target', ''),
           'network': network, 'expires_at': kw.pop('expires_at', None)}
    assert not kw, kw
    return row


def policy(*rows, api=S.MODE_UNRESTRICTED, webhook=S.MODE_UNRESTRICTED):
    return P.build_policy({'policy_version': 7, 'api_mode': api, 'webhook_mode': webhook}, list(rows))


def api_ctx(address, **kw):
    return P.Context(ip=ip(address), surface='api', group=kw.pop('group', 'rest_api'), **kw)


class AddressParsingTests(TestCase):
    def test_parse(self):
        self.assertEqual(str(ip('203.0.113.9')), '203.0.113.9')
        self.assertEqual(str(ip('2001:db8::1')), '2001:db8::1')
        self.assertEqual(str(ip('::ffff:198.51.100.4')), '198.51.100.4')  # mapped → IPv4
        self.assertEqual(str(ip('fe80::1%eth0')), 'fe80::1')
        for bad in ('', None, 'nope', '10.0.0.0/8', '999.1.1.1'):
            self.assertIsNone(ip(bad))

    def test_normalize(self):
        self.assertEqual(normalize_network('192.168.22.10'), '192.168.22.10/32')
        self.assertEqual(normalize_network('10.0.0.5/24'), '10.0.0.0/24')
        self.assertEqual(normalize_network('2001:db8:1234::/48'), '2001:db8:1234::/48')
        self.assertEqual(normalize_network(' 2001:db8::1 '), '2001:db8::1/128')
        for bad in ('', 'example.com', '10.0.0.0/33', '1.2.3'):
            with self.assertRaises(ValidationError):
                normalize_network(bad)


class MatchingTests(TestCase):
    def check(self, pol, address, allowed, **kw):
        d = P.evaluate(pol, api_ctx(address, **kw))
        self.assertEqual(d.allowed, allowed, (address, d))
        return d

    def test_exact_ipv4_and_ipv6(self):
        pol = policy(rule('192.168.22.10'), rule('2001:db8::5', id=2), api=S.MODE_ALLOWLIST)
        self.check(pol, '192.168.22.10', True)
        self.check(pol, '192.168.22.11', False)
        self.check(pol, '2001:db8::5', True)
        self.check(pol, '2001:db8::6', False)

    def test_cidr_edges(self):
        pol = policy(rule('10.0.0.0/24'), api=S.MODE_ALLOWLIST)
        self.check(pol, '10.0.0.0', True)
        self.check(pol, '10.0.0.255', True)
        self.check(pol, '10.0.1.0', False)
        self.check(pol, '9.255.255.255', False)
        v6 = policy(rule('2001:db8:1234::/48'), api=S.MODE_ALLOWLIST)
        self.check(v6, '2001:db8:1234:ffff:ffff:ffff:ffff:ffff', True)
        self.check(v6, '2001:db8:1235::', False)

    def test_ipv4_rule_never_matches_ipv6(self):
        pol = policy(rule('0.0.0.0/0'), api=S.MODE_ALLOWLIST)
        self.check(pol, '2001:db8::1', False)

    def test_private_addresses_get_no_special_trust(self):
        pol = policy(rule('203.0.113.0/24'), api=S.MODE_ALLOWLIST)
        for private in ('10.1.2.3', '192.168.1.1', '172.16.0.1', '127.0.0.1', '::1', 'fd00::1'):
            self.check(pol, private, False)


class ModeAndPrecedenceTests(TestCase):
    def test_unrestricted_no_rules_allows(self):
        d = P.evaluate(policy(), api_ctx('198.51.100.1'))
        self.assertTrue(d.allowed)

    def test_global_rules_follow_the_mode(self):
        allow = rule('10.0.0.0/8')
        deny = rule('198.51.100.0/24', R.ACTION_DENY, id=2)
        for mode, outside_allowed, denied_allowed in (
                (S.MODE_UNRESTRICTED, True, True),
                (S.MODE_ALLOWLIST, False, False),
                (S.MODE_DENYLIST, True, False),
                (S.MODE_COMBINED, False, False)):
            pol = policy(allow, deny, api=mode)
            self.assertEqual(P.evaluate(pol, api_ctx('203.0.113.1')).allowed, outside_allowed, mode)
            self.assertEqual(P.evaluate(pol, api_ctx('198.51.100.7')).allowed, denied_allowed, mode)
            self.assertTrue(P.evaluate(pol, api_ctx('10.2.3.4')).allowed, mode)

    def test_allowlist_mode_without_allow_rules_refuses_everything(self):
        d = P.evaluate(policy(api=S.MODE_ALLOWLIST), api_ctx('10.0.0.1'))
        self.assertFalse(d.allowed)
        self.assertEqual(d.reason, P.ALLOWLIST_EMPTY)

    def test_explicit_deny_overrides_overlapping_allow(self):
        pol = policy(rule('10.0.0.0/8'), rule('10.1.0.0/16', R.ACTION_DENY, id=2), api=S.MODE_COMBINED)
        self.assertTrue(P.evaluate(pol, api_ctx('10.2.0.1')).allowed)
        d = P.evaluate(pol, api_ctx('10.1.2.3'))
        self.assertFalse(d.allowed)
        self.assertEqual((d.reason, d.rule.id), (P.DENY_RULE, 2))

    def test_scoped_deny_beats_key_allow(self):
        pol = policy(rule('10.0.0.0/8', scope=R.SCOPE_API_KEY, api_key_id=5),
                     rule('10.0.0.9', R.ACTION_DENY, scope=R.SCOPE_ENDPOINT_GROUP, target='rest_api', id=2))
        self.assertFalse(P.evaluate(pol, api_ctx('10.0.0.9', api_key_id=5)).allowed)
        self.assertTrue(P.evaluate(pol, api_ctx('10.0.0.8', api_key_id=5)).allowed)

    def test_every_scope_with_allow_rules_must_match(self):
        pol = policy(rule('10.0.0.0/8'),
                     rule('10.5.0.0/16', scope=R.SCOPE_API_KEY, api_key_id=5, id=2), api=S.MODE_ALLOWLIST)
        self.assertTrue(P.evaluate(pol, api_ctx('10.5.1.1', api_key_id=5)).allowed)
        d = P.evaluate(pol, api_ctx('10.6.1.1', api_key_id=5))
        self.assertEqual((d.allowed, d.reason, d.detail), (False, P.NOT_ALLOWLISTED, R.SCOPE_API_KEY))
        # Another key is only bound by the global allowlist.
        self.assertTrue(P.evaluate(pol, api_ctx('10.6.1.1', api_key_id=6)).allowed)

    def test_scoped_rules_apply_even_when_unrestricted(self):
        pol = policy(rule('192.168.22.10', scope=R.SCOPE_API_KEY, api_key_id=5))
        self.assertFalse(P.evaluate(pol, api_ctx('203.0.113.4', api_key_id=5)).allowed)
        self.assertTrue(P.evaluate(pol, api_ctx('203.0.113.4', api_key_id=9)).allowed)

    def test_expired_rules_are_ignored(self):
        past = timezone.now() - timedelta(minutes=1)
        future = timezone.now() + timedelta(hours=1)
        pol = policy(rule('10.0.0.0/8', R.ACTION_DENY, expires_at=past), api=S.MODE_DENYLIST)
        self.assertTrue(P.evaluate(pol, api_ctx('10.0.0.1')).allowed)
        pol = policy(rule('10.0.0.0/8', R.ACTION_DENY, expires_at=future), api=S.MODE_DENYLIST)
        self.assertFalse(P.evaluate(pol, api_ctx('10.0.0.1')).allowed)
        # A temporary allow that has lapsed leaves the allowlist empty → refused.
        pol = policy(rule('10.0.0.0/8', expires_at=past), api=S.MODE_ALLOWLIST)
        self.assertEqual(P.evaluate(pol, api_ctx('10.0.0.1')).reason, P.ALLOWLIST_EMPTY)

    def test_customer_rules_apply_only_to_that_customers_keys(self):
        pol = policy(rule('10.0.0.0/8', scope=R.SCOPE_CUSTOMER, organization_id=1))
        self.assertFalse(P.evaluate(pol, api_ctx('203.0.113.1', organization_id=1)).allowed)
        self.assertTrue(P.evaluate(pol, api_ctx('203.0.113.1', organization_id=2)).allowed)
        self.assertTrue(P.evaluate(pol, api_ctx('203.0.113.1')).allowed)

    def test_integration_and_endpoint_group_scopes(self):
        pol = policy(rule('198.51.100.0/24', scope=R.SCOPE_INTEGRATION, target='rem0te',
                          surface=R.SURFACE_BOTH),
                     rule('0.0.0.0/0', R.ACTION_DENY, scope=R.SCOPE_ENDPOINT_GROUP,
                          target='graphql', id=2))
        rem0te = dict(group='integration_api', integration='rem0te')
        self.assertTrue(P.evaluate(pol, api_ctx('198.51.100.3', **rem0te)).allowed)
        self.assertFalse(P.evaluate(pol, api_ctx('203.0.113.3', **rem0te)).allowed)
        self.assertTrue(P.evaluate(pol, api_ctx('203.0.113.3')).allowed)
        self.assertFalse(P.evaluate(pol, api_ctx('203.0.113.3', group='graphql')).allowed)

    def test_webhook_and_api_policies_are_separate(self):
        pol = policy(rule('10.0.0.0/8', surface=R.SURFACE_WEBHOOK), webhook=S.MODE_ALLOWLIST)
        hook = P.Context(ip=ip('203.0.113.1'), surface='webhook', group='siem_webhook', integration='siem')
        self.assertFalse(P.evaluate(pol, hook).allowed)
        self.assertTrue(P.evaluate(pol, api_ctx('203.0.113.1')).allowed)
        both = policy(rule('10.0.0.0/8', R.ACTION_DENY, surface=R.SURFACE_BOTH),
                      api=S.MODE_DENYLIST, webhook=S.MODE_DENYLIST)
        hook.ip = ip('10.0.0.1')
        self.assertFalse(P.evaluate(both, hook).allowed)
        self.assertFalse(P.evaluate(both, api_ctx('10.0.0.1')).allowed)

    def test_unreadable_address_fails_closed_only_under_restrictions(self):
        none = P.Context(ip=None, surface='api', group='rest_api')
        self.assertTrue(P.evaluate(policy(), none).allowed)
        d = P.evaluate(policy(rule('10.0.0.0/8', R.ACTION_DENY), api=S.MODE_DENYLIST), none)
        self.assertEqual((d.allowed, d.reason), (False, P.NO_ADDRESS))

    def test_stages_split_scopes(self):
        pol = policy(rule('10.0.0.0/8', scope=R.SCOPE_API_KEY, api_key_id=5))
        ctx = api_ctx('203.0.113.1', api_key_id=5)
        self.assertTrue(P.evaluate(pol, ctx, P.STAGE_NETWORK).allowed)
        self.assertFalse(P.evaluate(pol, ctx, P.STAGE_CREDENTIAL).allowed)


class LoadingTests(TestCase):
    def setUp(self):
        P.reset_cache()

    def tearDown(self):
        P.reset_cache()

    def test_disabled_rules_are_not_loaded_and_bump_reloads(self):
        S.get()
        r = R.objects.create(name='x', network='10.0.0.0/8', action=R.ACTION_DENY)
        R.objects.create(name='off', network='0.0.0.0/0', action=R.ACTION_DENY, is_active=False)
        S.objects.filter(pk=1).update(api_mode=S.MODE_DENYLIST)
        S.bump()
        pol = P.current_policy()
        self.assertEqual([x.id for x in pol.rules], [r.pk])
        r.is_active = False
        r.save()
        self.assertIs(P.current_policy(), pol)  # unchanged version: cached
        S.bump()
        self.assertEqual(P.current_policy().rules, ())

    def test_evaluation_error_fails_closed_when_restrictive(self):
        S.get()
        R.objects.create(name='x', network='10.0.0.0/8')
        S.bump()
        with mock.patch.object(P, 'evaluate', side_effect=RuntimeError('boom')):
            d = P.decide(api_ctx('10.0.0.1'), P.ALL_SCOPES)
        self.assertEqual((d.allowed, d.reason), (False, P.POLICY_ERROR))

    def test_evaluation_error_without_restrictions_allows(self):
        with mock.patch.object(P, 'evaluate', side_effect=RuntimeError('boom')):
            self.assertTrue(P.decide(api_ctx('10.0.0.1'), P.ALL_SCOPES).allowed)

    def test_unreadable_database_with_no_cached_policy_refuses(self):
        with mock.patch.object(P, 'current_policy', side_effect=DatabaseError('down')):
            d = P.decide(api_ctx('10.0.0.1'), P.ALL_SCOPES)
        self.assertEqual((d.allowed, d.reason), (False, P.POLICY_UNAVAILABLE))

    def test_damaged_deny_rule_still_denies(self):
        pol = P.build_policy(None, [rule('not-a-network', R.ACTION_DENY, scope=R.SCOPE_ENDPOINT_GROUP,
                                         target='rest_api')])
        self.assertFalse(P.evaluate(pol, api_ctx('203.0.113.1')).allowed)
        self.assertFalse(P.evaluate(pol, api_ctx('2001:db8::1')).allowed)


class ClassifyTests(TestCase):
    def test_routes(self):
        cases = {
            '/api/assets/': ('rest_api', '', 'api'),
            '/api/v2/graphql/': ('graphql', '', 'api'),
            '/api/mobile/v1/tickets/': ('mobile_api', '', 'api'),
            '/api/integration/v1/events': ('integration_api', 'rem0te', 'api'),
            '/connect/v1/token': ('connect_api', 'agit8or_connect', 'api'),
            '/security/siem/webhook/abc/': ('siem_webhook', 'siem', 'webhook'),
            '/security/webhook/abc/': ('security_webhook', 'security_vendor', 'webhook'),
            '/payments/webhooks/stripe/3/': ('payment_webhook', 'stripe', 'webhook'),
            '/integrations/distributors/webhooks/t/': ('distributor_webhook', 'distributor', 'webhook'),
            '/psa/partners/webhook/4/': ('partner_webhook', 'ticket_partner', 'webhook'),
            '/core/emergency-restart/': ('emergency_restart', '', 'webhook'),
        }
        for path, expected in cases.items():
            r = classify(path)
            self.assertEqual((r.group, r.integration, r.surface), expected, path)
        for web in ('/', '/core/dashboard/', '/security/alerts/', '/apix/', '/accounts/login/'):
            self.assertIsNone(classify(web), web)

    def test_every_group_and_integration_is_routable(self):
        from .groups import _ROUTES
        self.assertEqual({g for _p, g, _i in _ROUTES}, set(ENDPOINT_GROUPS))
        self.assertEqual({i for _p, _g, i in _ROUTES if i}, set(INTEGRATIONS))


@override_settings(TRUSTED_PROXY_CIDRS=['127.0.0.1/32', '::1/128'])
class MiddlewareTests(TestCase):
    def setUp(self):
        P.reset_cache()
        cache.clear()
        S.get()
        self.rf = RequestFactory()
        self.mw = ApiAccessMiddleware(lambda request: HttpResponse('ok'))

    def tearDown(self):
        P.reset_cache()

    def allowlist(self, network='10.0.0.0/8', surface=R.SURFACE_BOTH):
        R.objects.create(name='office', network=network, surface=surface)
        S.objects.filter(pk=1).update(api_mode=S.MODE_ALLOWLIST, webhook_mode=S.MODE_ALLOWLIST)
        S.bump()

    def call(self, path, remote, xff=None, method='get'):
        extra = {'REMOTE_ADDR': remote}
        if xff is not None:
            extra['HTTP_X_FORWARDED_FOR'] = xff
        return self.mw(getattr(self.rf, method)(path, **extra))

    def test_existing_installs_are_unrestricted(self):
        self.assertEqual(self.call('/api/assets/', '203.0.113.1').status_code, 200)
        self.assertEqual(ApiAccessDecision.objects.count(), 0)

    def test_web_pages_are_never_touched(self):
        self.allowlist()
        self.assertEqual(self.call('/core/dashboard/', '203.0.113.1').status_code, 200)

    def test_refusal_is_403_json_and_logged_without_secrets(self):
        self.allowlist()
        r = self.mw(self.rf.get('/api/assets/?token=s3cret', REMOTE_ADDR='203.0.113.1',
                                HTTP_AUTHORIZATION='Bearer itdocs_live_s3cret'))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(json.loads(r.content)['detail'], 'Access from this network address is not allowed.')
        d = ApiAccessDecision.objects.get()
        self.assertEqual((d.source_ip, d.reason, d.endpoint_group, d.path),
                         ('203.0.113.1', P.NOT_ALLOWLISTED, 'rest_api', '/api/assets/'))
        self.assertGreater(d.policy_version, 1)
        blob = json.dumps({f.name: str(getattr(d, f.name)) for f in d._meta.fields})
        self.assertNotIn('s3cret', blob)

    def test_inside_allowlist_passes(self):
        self.allowlist()
        self.assertEqual(self.call('/api/assets/', '10.20.30.40').status_code, 200)

    def test_repeats_fold_into_one_row(self):
        self.allowlist()
        for _ in range(60):
            self.call('/api/assets/', '203.0.113.1')
        self.assertEqual(ApiAccessDecision.objects.count(), 1)
        self.assertGreaterEqual(ApiAccessDecision.objects.get().count, 50)

    def test_spoofed_forwarded_for_from_untrusted_peer_is_ignored(self):
        self.allowlist()
        r = self.call('/api/assets/', '203.0.113.9', xff='10.0.0.1')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(ApiAccessDecision.objects.get().source_ip, '203.0.113.9')

    def test_forged_prefix_through_trusted_proxy_is_ignored(self):
        self.allowlist()
        # The client sends "10.0.0.1" itself; nginx appends the real address.
        r = self.call('/api/assets/', '127.0.0.1', xff='10.0.0.1, 203.0.113.50')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(ApiAccessDecision.objects.get().source_ip, '203.0.113.50')

    @override_settings(TRUSTED_PROXY_CIDRS=['127.0.0.1/32', '172.18.0.0/16'])
    def test_multi_hop_trusted_chain(self):
        self.allowlist()
        self.assertEqual(self.call('/api/assets/', '127.0.0.1', xff='10.9.8.7, 172.18.0.5').status_code, 200)

    def test_reverse_proxy_address_is_not_a_pass(self):
        # Behind the local nginx every request arrives from 127.0.0.1; an
        # allowlist containing 127.0.0.1 must not let outside clients in.
        self.allowlist('127.0.0.1')
        self.assertEqual(self.call('/api/assets/', '127.0.0.1', xff='203.0.113.7').status_code, 403)

    def test_malformed_forwarding_header_fails_closed(self):
        self.allowlist()
        r = self.call('/api/assets/', '127.0.0.1', xff='not-an-ip')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(ApiAccessDecision.objects.get().reason, P.NO_ADDRESS)

    def test_webhooks_have_their_own_mode(self):
        R.objects.create(name='vendor', network='198.51.100.0/24', surface=R.SURFACE_WEBHOOK)
        S.objects.filter(pk=1).update(webhook_mode=S.MODE_ALLOWLIST)
        S.bump()
        self.assertEqual(self.call('/security/siem/webhook/t/', '203.0.113.1', method='post').status_code, 403)
        self.assertEqual(self.call('/security/siem/webhook/t/', '198.51.100.9', method='post').status_code, 200)
        self.assertEqual(self.call('/api/assets/', '203.0.113.1').status_code, 200)

    def test_oversized_event_flood_is_logged_compactly(self):
        R.objects.create(name='block', network='0.0.0.0/0', action=R.ACTION_DENY, surface=R.SURFACE_WEBHOOK)
        S.objects.filter(pk=1).update(webhook_mode=S.MODE_DENYLIST)
        S.bump()
        for n in range(30):
            self.call('/security/siem/webhook/t/', f'203.0.113.{n % 3}', method='post')
        self.assertEqual(ApiAccessDecision.objects.count(), 3)


@override_settings(MIDDLEWARE=MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   TRUSTED_PROXY_CIDRS=['127.0.0.1/32'])
class ApiKeyEnforcementTests(TestCase):
    def setUp(self):
        P.reset_cache()
        cache.clear()
        S.get()
        self.org = Organization.objects.create(name='AK-A', slug='ak-a')
        self.other = Organization.objects.create(name='AK-B', slug='ak-b')
        self.user = User.objects.create_user('ak-user', password='pw')
        Membership.objects.create(user=self.user, organization=self.org, role=Role.OWNER, is_active=True)
        Membership.objects.create(user=self.user, organization=self.other, role=Role.OWNER, is_active=True)
        self.key, self.plain = APIKey.create_key(self.org, self.user, 'SIEM-WAZUH-PRODUCTION')
        self.key2, self.plain2 = APIKey.create_key(self.other, self.user, 'other')

    def tearDown(self):
        P.reset_cache()

    def get(self, plain, remote):
        return Client(HTTP_AUTHORIZATION=f'Bearer {plain}', REMOTE_ADDR=remote).get('/api/assets/')

    def restrict_key(self, *networks):
        for n in networks:
            R.objects.create(name='k', network=normalize_network(n), scope=R.SCOPE_API_KEY, api_key=self.key)
        S.bump()

    def test_key_restricted_to_its_networks(self):
        self.restrict_key('192.168.22.10', '10.0.0.0/24', '2001:db8:1234::/48')
        self.assertEqual(self.get(self.plain, '192.168.22.10').status_code, 200)
        self.assertEqual(self.get(self.plain, '10.0.0.77').status_code, 200)
        self.assertEqual(self.get(self.plain, '2001:db8:1234::9').status_code, 200)
        r = self.get(self.plain, '203.0.113.5')
        self.assertEqual(r.status_code, 403)
        d = ApiAccessDecision.objects.get()
        self.assertEqual((d.api_key_id, d.api_key_prefix, d.organization_id, d.reason),
                         (self.key.pk, self.key.key_prefix, self.org.pk, P.NOT_ALLOWLISTED))
        self.assertNotIn(self.plain, str(list(ApiAccessDecision.objects.values())))

    def test_other_keys_and_customers_are_unaffected(self):
        self.restrict_key('192.168.22.10')
        self.assertEqual(self.get(self.plain2, '203.0.113.5').status_code, 200)

    def test_customer_rule_binds_only_that_customers_keys(self):
        R.objects.create(name='c', network='10.0.0.0/8', scope=R.SCOPE_CUSTOMER, organization=self.org)
        S.bump()
        self.assertEqual(self.get(self.plain, '203.0.113.5').status_code, 403)
        self.assertEqual(self.get(self.plain2, '203.0.113.5').status_code, 200)

    def test_refused_key_does_not_record_use(self):
        self.restrict_key('192.168.22.10')
        self.get(self.plain, '203.0.113.5')
        self.key.refresh_from_db()
        self.assertIsNone(self.key.last_used_ip)

    def test_restriction_never_replaces_authentication(self):
        R.objects.create(name='office', network='10.0.0.0/8')
        S.objects.filter(pk=1).update(api_mode=S.MODE_ALLOWLIST)
        S.bump()
        r = Client(HTTP_AUTHORIZATION='Bearer itdocs_live_wrong', REMOTE_ADDR='10.0.0.1').get('/api/assets/')
        self.assertIn(r.status_code, (401, 403))
        self.assertIn(Client(REMOTE_ADDR='10.0.0.1').get('/api/assets/').status_code, (401, 403))


@override_settings(MIDDLEWARE=API_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AdminPageTests(TestCase):
    def setUp(self):
        P.reset_cache()
        self.admin = User.objects.create_superuser('aa-admin', 'a@example.test', 'pw')
        self.staff = User.objects.create_user('aa-staff', password='pw', is_staff=True)
        self.c = Client(REMOTE_ADDR='10.0.0.1')
        self.c.force_login(self.admin)
        self.org = Organization.objects.create(name='AP-A', slug='ap-a')
        self.key, _ = APIKey.create_key(self.org, self.admin, 'busy key')
        APIKey.objects.filter(pk=self.key.pk).update(last_used_at=timezone.now(), last_used_ip='198.51.100.20')

    def tearDown(self):
        P.reset_cache()

    def test_superuser_only(self):
        other = Client()
        other.force_login(self.staff)
        for name in ('', 'rules/new/', 'test/', 'refused/', 'diagnostics/', 'export/', 'import/'):
            r = other.get(f'/settings/security/api-access/{name}')
            self.assertIn(r.status_code, (302, 403), name)
        for name in ('', 'rules/new/', 'test/', 'refused/', 'diagnostics/', 'import/'):
            self.assertEqual(self.c.get(f'/settings/security/api-access/{name}').status_code, 200, name)

    def post_rule(self, **data):
        base = {'name': 'r', 'network': '10.0.0.0/8', 'action': 'allow', 'surface': 'api',
                'scope': 'global', 'target': '', 'description': '', 'is_active': 'on'}
        base.update(data)
        return self.c.post('/settings/security/api-access/rules/new/', base)

    def test_create_rule_audited_and_version_bumped(self):
        v = S.get().policy_version
        r = self.post_rule(network='10.0.0.5/24')
        self.assertEqual(r.status_code, 302)
        rule = R.objects.get()
        self.assertEqual((rule.network, rule.created_by), ('10.0.0.0/24', self.admin))
        self.assertGreater(S.get().policy_version, v)
        self.assertTrue(AuditLog.objects.filter(object_type='ApiAccessRule', object_id=rule.pk).exists())

    def test_invalid_network_is_refused(self):
        r = self.post_rule(network='example.com')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(R.objects.exists())

    def test_rule_that_would_cut_off_a_busy_key_needs_confirmation(self):
        r = self.post_rule(scope='api_key', api_key=self.key.pk, network='10.0.0.0/8')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'busy key')
        self.assertFalse(R.objects.exists())
        r = self.post_rule(scope='api_key', api_key=self.key.pk, network='10.0.0.0/8', confirm='1')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(R.objects.exists())

    def test_allowlist_mode_needs_confirmation(self):
        R.objects.create(name='office', network='10.0.0.0/8')
        r = self.c.post('/settings/security/api-access/mode/', {'api_mode': 'allowlist', 'webhook_mode': 'unrestricted'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'busy key')
        self.assertEqual(S.get().api_mode, 'unrestricted')
        self.c.post('/settings/security/api-access/mode/',
                    {'api_mode': 'allowlist', 'webhook_mode': 'unrestricted', 'confirm': 'on'})
        self.assertEqual(S.get().api_mode, 'allowlist')

    def test_toggle_and_delete(self):
        rule = R.objects.create(name='x', network='203.0.113.0/24', action='deny')
        self.c.post(f'/settings/security/api-access/rules/{rule.pk}/toggle/')
        rule.refresh_from_db()
        self.assertFalse(rule.is_active)
        self.c.post(f'/settings/security/api-access/rules/{rule.pk}/delete/')
        self.assertFalse(R.objects.exists())
        self.assertTrue(AuditLog.objects.filter(object_type='ApiAccessRule', action='delete').exists())

    def test_test_an_address(self):
        R.objects.create(name='office', network='10.0.0.0/8')
        S.objects.filter(pk=1).update(api_mode='allowlist')
        r = self.c.get('/settings/security/api-access/test/', {'ip': '203.0.113.1', 'group': 'rest_api'})
        self.assertContains(r, 'Refused')
        r = self.c.get('/settings/security/api-access/test/', {'ip': '10.1.1.1', 'group': 'rest_api'})
        self.assertContains(r, 'Allowed')
        r = self.c.get('/settings/security/api-access/test/', {'ip': 'nope', 'group': 'rest_api'})
        self.assertContains(r, 'single IPv4 or IPv6 address')

    def test_export_import_round_trip(self):
        R.objects.create(name='a', network='10.0.0.0/8')
        R.objects.create(name='b', network='2001:db8::/32', action='deny', surface='both',
                         scope='integration', target='rem0te')
        body = self.c.get('/settings/security/api-access/export/').content
        R.objects.all().delete()
        upload = SimpleUploadedFile('rules.json', body, content_type='application/json')
        r = self.c.post('/settings/security/api-access/import/', {'file': upload})
        self.assertContains(r, '2 rules validated')
        self.assertFalse(R.objects.exists())
        self.c.post('/settings/security/api-access/import/', {'apply_saved': '1'})
        self.assertEqual(sorted(R.objects.values_list('network', flat=True)), ['10.0.0.0/8', '2001:db8::/32'])

    def test_import_rejects_bad_files_whole(self):
        bad = json.dumps({'format': 'clientst0r-api-access-rules', 'version': 1, 'rules': [
            {'name': 'ok', 'network': '10.0.0.0/8', 'action': 'allow', 'surface': 'api', 'scope': 'global'},
            {'name': 'bad', 'network': 'nope', 'action': 'allow', 'surface': 'api', 'scope': 'global'}]})
        r = self.c.post('/settings/security/api-access/import/',
                        {'file': SimpleUploadedFile('r.json', bad.encode(), content_type='application/json')})
        self.assertContains(r, 'Nothing was imported')
        self.assertFalse(R.objects.exists())

    @override_settings(TRUSTED_PROXY_CIDRS=['127.0.0.1/32'])
    def test_diagnostics_explains_ignored_header(self):
        c = Client(REMOTE_ADDR='203.0.113.4', HTTP_X_FORWARDED_FOR='10.0.0.1')
        c.force_login(self.admin)
        r = c.get('/settings/security/api-access/diagnostics/')
        self.assertContains(r, '203.0.113.4')
        self.assertContains(r, 'ignored')


class RecoveryCommandTests(TestCase):
    def setUp(self):
        P.reset_cache()

    def test_unrestrict_and_disable(self):
        S.get()
        S.objects.filter(pk=1).update(api_mode='allowlist', webhook_mode='combined')
        a = R.objects.create(name='a', network='10.0.0.0/8')
        R.objects.create(name='b', network='10.0.0.0/8')
        v = S.get().policy_version
        out = io.StringIO()
        call_command('api_access_recover', '--unrestrict', '--surface', 'api', stdout=out)
        s = S.get()
        self.assertEqual((s.api_mode, s.webhook_mode), ('unrestricted', 'combined'))
        self.assertGreater(s.policy_version, v)
        call_command('api_access_recover', '--disable-rule', str(a.pk), stdout=out)
        a.refresh_from_db()
        self.assertFalse(a.is_active)
        call_command('api_access_recover', '--disable-all-rules', stdout=out)
        self.assertFalse(R.objects.filter(is_active=True).exists())
        self.assertEqual(AuditLog.objects.filter(object_type='ApiAccessSettings').count(), 3)

    def test_status_is_read_only(self):
        out = io.StringIO()
        call_command('api_access_recover', stdout=out)
        self.assertIn('API mode', out.getvalue())


@override_settings(TRUSTED_PROXY_CIDRS=['127.0.0.1/32'])
class ConnectRateLimitAddressTests(TestCase):
    def test_uses_trusted_proxy_resolution(self):
        from connect.ratelimit import client_ip
        rf = RequestFactory()
        self.assertEqual(client_ip(rf.get('/', REMOTE_ADDR='', HTTP_X_FORWARDED_FOR='203.0.113.8')),
                         '203.0.113.8')
        self.assertEqual(client_ip(rf.get('/', REMOTE_ADDR='198.51.100.2', HTTP_X_FORWARDED_FOR='10.0.0.1')),
                         '198.51.100.2')


@override_settings(TRUSTED_PROXY_CIDRS=['127.0.0.1/32'])
class AddressLimitTests(TestCase):
    """Per-address rate and body-size limits (v3.17.714)."""

    def setUp(self):
        P.reset_cache()
        cache.clear()
        S.get()
        self.mw = ApiAccessMiddleware(lambda request: HttpResponse('ok'))
        self.rf = RequestFactory()

    def tearDown(self):
        P.reset_cache()

    def limits(self, **kw):
        S.objects.filter(pk=1).update(**kw)
        S.bump()

    def test_off_by_default(self):
        for _ in range(20):
            self.assertEqual(self.mw(self.rf.get('/api/assets/', REMOTE_ADDR='203.0.113.1')).status_code, 200)

    def test_rate_per_address(self):
        self.limits(api_rate_per_address=3)
        codes = [self.mw(self.rf.get('/api/assets/', REMOTE_ADDR='203.0.113.1')).status_code for _ in range(5)]
        self.assertEqual(codes, [200, 200, 200, 429, 429])
        r = self.mw(self.rf.get('/api/assets/', REMOTE_ADDR='203.0.113.1'))
        self.assertEqual(r['Retry-After'], '60')
        self.assertEqual(self.mw(self.rf.get('/api/assets/', REMOTE_ADDR='203.0.113.2')).status_code, 200)
        # webhooks have their own limit (off here)
        self.assertEqual(self.mw(self.rf.post('/security/siem/webhook/t/', REMOTE_ADDR='203.0.113.1')).status_code, 200)
        self.assertEqual(ApiAccessDecision.objects.get().reason, P.RATE_LIMITED)

    def test_body_size(self):
        self.limits(webhook_max_body_kb=1)
        small = self.rf.post('/security/siem/webhook/t/', data='x' * 500, content_type='text/plain',
                             REMOTE_ADDR='203.0.113.1')
        self.assertEqual(self.mw(small).status_code, 200)
        big = self.rf.post('/security/siem/webhook/t/', data='x' * 5000, content_type='text/plain',
                           REMOTE_ADDR='203.0.113.1')
        self.assertEqual(self.mw(big).status_code, 413)
        self.assertEqual(ApiAccessDecision.objects.get().reason, P.TOO_LARGE)
        # the API surface has no size limit set
        api = self.rf.post('/api/assets/', data='x' * 5000, content_type='text/plain', REMOTE_ADDR='203.0.113.1')
        self.assertEqual(self.mw(api).status_code, 200)

    def test_network_refusal_comes_before_limits(self):
        R.objects.create(name='block', network='203.0.113.0/24', action=R.ACTION_DENY)
        self.limits(api_mode=S.MODE_DENYLIST, api_rate_per_address=1)
        self.assertEqual(self.mw(self.rf.get('/api/assets/', REMOTE_ADDR='203.0.113.1')).status_code, 403)


@override_settings(MIDDLEWARE=API_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class LimitsPageTests(TestCase):
    def test_limits_saved_and_audited(self):
        admin = User.objects.create_superuser('al-admin', 'a@example.test', 'pw')
        c = Client()
        c.force_login(admin)
        r = c.post('/settings/security/api-access/limits/', {
            'api_rate_per_address': '600', 'webhook_rate_per_address': '120',
            'api_max_body_kb': '0', 'webhook_max_body_kb': '256'})
        self.assertEqual(r.status_code, 302)
        s = S.get()
        self.assertEqual((s.api_rate_per_address, s.webhook_rate_per_address, s.webhook_max_body_kb), (600, 120, 256))
        self.assertTrue(AuditLog.objects.filter(description='API access limits changed').exists())
        c.post('/settings/security/api-access/limits/', {
            'api_rate_per_address': '-1', 'webhook_rate_per_address': '0',
            'api_max_body_kb': '0', 'webhook_max_body_kb': '0'})
        self.assertEqual(S.get().api_rate_per_address, 600)
