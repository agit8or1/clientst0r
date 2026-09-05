"""
Tests for the mobile API auth endpoints (v3.17.346) and the
dashboard / organizations endpoints (v3.17.347).
"""
from __future__ import annotations

import json

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from rest_framework.authtoken.models import Token

from accounts.models import Membership, Role
from core.models import Organization

# Strip 2FA + Axes middleware so the test client doesn't get bounced by
# the redirect middleware on every endpoint that's behind it.
TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

# Disable DRF rate-throttling for tests — cumulative login attempts across
# multiple test classes sharing one IP otherwise trip the 10/hour login
# throttle and the test client gets 429 on `setUp` logins.
NO_THROTTLE_REST = dict(django_settings.REST_FRAMEWORK, DEFAULT_THROTTLE_CLASSES=[])


def _clear_throttle_cache():
    """Reset the DRF throttle cache between tests."""
    try:
        cache.clear()
    except Exception:
        pass


def _post(client, path, payload):
    return client.post(path, data=json.dumps(payload), content_type='application/json')


def _auth_get(client, path, token):
    return client.get(path, HTTP_AUTHORIZATION=f'Token {token}')


def _auth_post(client, path, token, payload=None):
    body = json.dumps(payload) if payload is not None else ''
    return client.post(
        path, data=body, content_type='application/json',
        HTTP_AUTHORIZATION=f'Token {token}',
    )


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileAuthLoginTests(TestCase):
    """Verifies happy-path login + wrong-password rejection + missing fields."""

    def setUp(self):
        _clear_throttle_cache()
        self.org = Organization.objects.create(name='OrgA-Mobile', slug='orga-mobile')
        self.user = User.objects.create_user('mobileuser', password='hunter2', email='m@x.com')
        Membership.objects.create(
            user=self.user, organization=self.org, role=Role.OWNER, is_active=True,
        )
        self.client = Client()

    def test_login_success_returns_token(self):
        resp = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'mobileuser', 'password': 'hunter2',
        })
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertIn('token', body)
        self.assertEqual(body['user']['username'], 'mobileuser')
        self.assertEqual(body['user']['organization_id'], self.org.id)
        # Token is real
        self.assertTrue(Token.objects.filter(key=body['token']).exists())

    def test_login_wrong_password_rejected(self):
        resp = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'mobileuser', 'password': 'WRONG',
        })
        self.assertEqual(resp.status_code, 401)

    def test_login_missing_fields_400(self):
        resp = _post(self.client, '/api/mobile/v1/auth/login/', {'username': 'x'})
        self.assertEqual(resp.status_code, 400)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileAuth2FAFlowTests(TestCase):
    """Users with 2FA must complete `/auth/mfa/` to get the API token."""

    def setUp(self):
        _clear_throttle_cache()
        self.user = User.objects.create_user('mfauser', password='hunter2')
        # Mark profile two_factor_enabled — that's how `user_has_2fa_enabled`
        # detects without a real TOTP device row.
        if hasattr(self.user, 'profile'):
            self.user.profile.two_factor_enabled = True
            self.user.profile.save(update_fields=['two_factor_enabled'])
        self.client = Client()

    def test_login_returns_mfa_required(self):
        resp = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'mfauser', 'password': 'hunter2',
        })
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertTrue(body.get('mfa_required'))
        self.assertIn('mfa_token', body)
        self.assertNotIn('token', body)

    def test_mfa_with_bad_token_rejected(self):
        resp = _post(self.client, '/api/mobile/v1/auth/mfa/', {
            'mfa_token': 'no-such-token', 'code': '123456',
        })
        self.assertEqual(resp.status_code, 401)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileAuthTokenLifecycleTests(TestCase):
    """Logout revokes the token; refresh issues a new one; me returns profile."""

    def setUp(self):
        _clear_throttle_cache()
        self.user = User.objects.create_user('luser', password='hunter2', email='l@x.com')
        self.client = Client()
        resp = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'luser', 'password': 'hunter2',
        })
        self.token = resp.json()['token']

    def test_me_unauthenticated_blocked(self):
        c = Client()
        resp = c.get('/api/mobile/v1/auth/me/')
        self.assertIn(resp.status_code, (401, 403))

    def test_me_authenticated_returns_profile(self):
        resp = _auth_get(self.client, '/api/mobile/v1/auth/me/', self.token)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['user']['username'], 'luser')

    def test_logout_revokes_token(self):
        resp = _auth_post(self.client, '/api/mobile/v1/auth/logout/', self.token)
        self.assertEqual(resp.status_code, 200)
        # Subsequent call with the old token now fails
        resp2 = _auth_get(self.client, '/api/mobile/v1/auth/me/', self.token)
        self.assertIn(resp2.status_code, (401, 403))

    def test_token_refresh_rotates(self):
        resp = _auth_post(self.client, '/api/mobile/v1/auth/refresh/', self.token)
        self.assertEqual(resp.status_code, 200)
        new_token = resp.json()['token']
        self.assertNotEqual(new_token, self.token)
        # Old token revoked
        resp2 = _auth_get(self.client, '/api/mobile/v1/auth/me/', self.token)
        self.assertIn(resp2.status_code, (401, 403))
        # New token works
        resp3 = _auth_get(self.client, '/api/mobile/v1/auth/me/', new_token)
        self.assertEqual(resp3.status_code, 200)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileDashboardShapeTests(TestCase):
    """
    v3.17.448: GET /api/mobile/v1/dashboard/ MUST return arrays for
    `recent_tickets` + `recent_assets` and a nested `security` object.
    Previously returned counts where the mobile client expected arrays,
    which crashed the React Native dashboard with "undefined is not a
    function" on `data.recent_assets.map(...)`.
    """

    def setUp(self):
        _clear_throttle_cache()
        self.org = Organization.objects.create(name='OrgD-Mobile', slug='orgd-mobile')
        self.user = User.objects.create_user('duser', password='hunter2', email='d@x.com')
        Membership.objects.create(
            user=self.user, organization=self.org, role=Role.OWNER, is_active=True,
        )
        self.client = Client()
        resp = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'duser', 'password': 'hunter2',
        })
        self.token = resp.json()['token']

    def test_dashboard_returns_expected_shape(self):
        """All keys the mobile DashboardSummary type expects are present."""
        resp = _auth_get(self.client, '/api/mobile/v1/dashboard/', self.token)
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        # Counts
        for key in (
            'open_tickets', 'critical_tickets', 'my_open_tickets',
            'expiring_soon', 'monitors_down',
        ):
            self.assertIn(key, body, f'missing count key: {key}')
            self.assertIsInstance(body[key], int, f'{key} must be int')
        # Arrays — the bug was that these were returned as ints
        self.assertIsInstance(body.get('recent_tickets'), list,
                              'recent_tickets must be a list (mobile calls .map() on it)')
        self.assertIsInstance(body.get('recent_assets'), list,
                              'recent_assets must be a list (mobile calls .map() on it)')
        # Nested security summary
        self.assertIsInstance(body.get('security'), dict,
                              'security must be a dict (mobile reads .open_alert_count)')
        for sev_key in (
            'open_alert_count', 'critical_alert_count', 'high_alert_count',
            'medium_alert_count', 'low_alert_count',
        ):
            self.assertIn(sev_key, body['security'])
        self.assertIsInstance(body['security'].get('recent_alerts'), list)

    def test_dashboard_unauthenticated_blocked(self):
        resp = Client().get('/api/mobile/v1/dashboard/')
        self.assertIn(resp.status_code, (401, 403))

    def test_dashboard_arrays_are_jsonable_when_empty(self):
        """Empty results still have list type (not None), so .map() works."""
        resp = _auth_get(self.client, '/api/mobile/v1/dashboard/', self.token)
        body = resp.json()
        self.assertEqual(body['recent_tickets'], [])
        self.assertEqual(body['recent_assets'], [])
        self.assertEqual(body['security']['recent_alerts'], [])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileVaultEndpointTests(TestCase):
    """
    v3.17.449: /api/mobile/v1/vault/{,<id>/,<id>/reveal/} are reachable,
    org-scoped, never leak the secret on list/detail, and successfully
    decrypt on reveal.
    """

    def setUp(self):
        from vault.models import Password
        from vault.encryption_v2 import encrypt_password
        _clear_throttle_cache()
        # Two orgs — user belongs to one only
        self.org_a = Organization.objects.create(name='OrgA-Vault', slug='orga-vault')
        self.org_b = Organization.objects.create(name='OrgB-Vault', slug='orgb-vault')
        self.user = User.objects.create_user('vuser', password='hunter2', email='v@x.com')
        Membership.objects.create(
            user=self.user, organization=self.org_a, role=Role.OWNER, is_active=True,
        )
        # Org-A entry the user CAN see
        self.entry_a = Password.objects.create(
            organization=self.org_a, title='Router admin', username='admin',
            encrypted_password=encrypt_password('s3cret-A', org_id=self.org_a.id),
        )
        # Org-B entry the user CANNOT see
        self.entry_b = Password.objects.create(
            organization=self.org_b, title='Other org switch', username='admin',
            encrypted_password=encrypt_password('s3cret-B', org_id=self.org_b.id),
        )
        self.client = Client()
        resp = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'vuser', 'password': 'hunter2',
        })
        self.token = resp.json()['token']

    def test_list_returns_only_my_org_entries(self):
        resp = _auth_get(self.client, '/api/mobile/v1/vault/', self.token)
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertIn('results', body)
        ids = {row['id'] for row in body['results']}
        self.assertIn(self.entry_a.id, ids)
        self.assertNotIn(self.entry_b.id, ids)

    def test_list_does_not_leak_secret(self):
        resp = _auth_get(self.client, '/api/mobile/v1/vault/', self.token)
        body = resp.json()
        for row in body['results']:
            self.assertNotIn('secret', row)
            self.assertNotIn('encrypted_password', row)
            self.assertNotIn('password', row)

    def test_detail_cross_org_returns_404(self):
        resp = _auth_get(
            self.client, f'/api/mobile/v1/vault/{self.entry_b.id}/', self.token,
        )
        self.assertEqual(resp.status_code, 404)

    def test_reveal_returns_plaintext_for_my_org(self):
        resp = _auth_post(
            self.client, f'/api/mobile/v1/vault/{self.entry_a.id}/reveal/',
            self.token,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body.get('secret'), 's3cret-A')

    def test_reveal_cross_org_blocked(self):
        resp = _auth_post(
            self.client, f'/api/mobile/v1/vault/{self.entry_b.id}/reveal/',
            self.token,
        )
        self.assertEqual(resp.status_code, 404)

    def test_unauthenticated_blocked(self):
        c = Client()
        resp = c.get('/api/mobile/v1/vault/')
        self.assertIn(resp.status_code, (401, 403))

    def test_search_filters_results(self):
        resp = self.client.get(
            '/api/mobile/v1/vault/?search=Router',
            HTTP_AUTHORIZATION=f'Token {self.token}',
        )
        self.assertEqual(resp.status_code, 200)
        ids = {row['id'] for row in resp.json()['results']}
        self.assertIn(self.entry_a.id, ids)

        resp2 = self.client.get(
            '/api/mobile/v1/vault/?search=zzznosuchterm',
            HTTP_AUTHORIZATION=f'Token {self.token}',
        )
        self.assertEqual(resp2.json()['count'], 0)


# v3.17.347 — dashboard + organizations endpoints
@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileDashboardOrgsTests(TestCase):
    """Dashboard counts + organization list + detail are org-scoped."""

    def setUp(self):
        _clear_throttle_cache()
        self.org_a = Organization.objects.create(name='OrgA-Dash', slug='orga-dash')
        self.org_b = Organization.objects.create(name='OrgB-Dash', slug='orgb-dash')
        self.user_a = User.objects.create_user('dashuser', password='hunter2')
        Membership.objects.create(
            user=self.user_a, organization=self.org_a, role=Role.OWNER, is_active=True,
        )
        # user_a is NOT in org_b
        self.client = Client()
        resp = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'dashuser', 'password': 'hunter2',
        })
        self.token = resp.json()['token']

    def test_dashboard_requires_auth(self):
        c = Client()
        self.assertIn(c.get('/api/mobile/v1/dashboard/').status_code, (401, 403))

    def test_dashboard_returns_counts(self):
        """v3.17.448 reshaped the dashboard payload — `offline_monitors`
        became `monitors_down`, `security_alerts_open` became
        `security.open_alert_count`, and `recent_assets` flipped from
        an int count to an array. `MobileDashboardShapeTests` covers
        the new shape exhaustively; this one just sanity-checks the
        endpoint responds 200 with the expected top-level keys."""
        resp = _auth_get(self.client, '/api/mobile/v1/dashboard/', self.token)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        for key in ('open_tickets', 'critical_tickets', 'expiring_soon',
                    'monitors_down', 'recent_assets', 'recent_tickets',
                    'security', 'my_open_tickets'):
            self.assertIn(key, body)

    def test_org_list_requires_auth(self):
        c = Client()
        self.assertIn(c.get('/api/mobile/v1/organizations/').status_code, (401, 403))

    def test_org_list_returns_only_user_orgs(self):
        resp = _auth_get(self.client, '/api/mobile/v1/organizations/', self.token)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        ids = [o['id'] for o in body['results']]
        self.assertIn(self.org_a.id, ids)
        self.assertNotIn(self.org_b.id, ids)
        self.assertEqual(body['count'], 1)

    def test_org_detail_returns_my_org(self):
        url = f'/api/mobile/v1/organizations/{self.org_a.id}/'
        resp = _auth_get(self.client, url, self.token)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['name'], 'OrgA-Dash')

    def test_org_detail_cross_org_blocked(self):
        url = f'/api/mobile/v1/organizations/{self.org_b.id}/'
        resp = _auth_get(self.client, url, self.token)
        self.assertEqual(resp.status_code, 404)


# v3.17.348 — assets endpoints
@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileAssetsTests(TestCase):
    """Asset list + detail respect org-scoping; search + filters work."""

    def setUp(self):
        _clear_throttle_cache()
        from assets.models import Asset
        self.org_a = Organization.objects.create(name='OrgA-Asset', slug='orga-asset')
        self.org_b = Organization.objects.create(name='OrgB-Asset', slug='orgb-asset')
        self.user_a = User.objects.create_user('assetuser', password='hunter2')
        Membership.objects.create(
            user=self.user_a, organization=self.org_a, role=Role.OWNER, is_active=True,
        )
        self.asset_a = Asset.objects.create(
            organization=self.org_a, name='ServerA', hostname='srv-a.local',
            asset_type='server',
        )
        self.asset_b = Asset.objects.create(
            organization=self.org_b, name='ServerB', hostname='srv-b.local',
            asset_type='workstation',
        )
        self.client = Client()
        resp = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'assetuser', 'password': 'hunter2',
        })
        self.token = resp.json()['token']

    def test_asset_list_scoped_to_user_orgs(self):
        resp = _auth_get(self.client, '/api/mobile/v1/assets/', self.token)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        names = [a['name'] for a in body['results']]
        self.assertIn('ServerA', names)
        self.assertNotIn('ServerB', names)

    def test_asset_detail_returns_my_asset(self):
        url = f'/api/mobile/v1/assets/{self.asset_a.id}/'
        resp = _auth_get(self.client, url, self.token)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['hostname'], 'srv-a.local')

    def test_asset_detail_cross_org_blocked(self):
        url = f'/api/mobile/v1/assets/{self.asset_b.id}/'
        resp = _auth_get(self.client, url, self.token)
        self.assertEqual(resp.status_code, 404)

    def test_asset_list_search_by_hostname(self):
        url = '/api/mobile/v1/assets/?search=srv-a'
        resp = _auth_get(self.client, url, self.token)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()['results']), 1)

    def test_asset_list_filter_by_type(self):
        from assets.models import Asset
        Asset.objects.create(
            organization=self.org_a, name='LaptopA', asset_type='laptop',
        )
        url = '/api/mobile/v1/assets/?type=server'
        resp = _auth_get(self.client, url, self.token)
        self.assertEqual(resp.status_code, 200)
        types = {a['asset_type'] for a in resp.json()['results']}
        self.assertEqual(types, {'server'})

    def test_asset_list_filter_by_asset_type_alias(self):
        """v3.17.536 — the shipped mobile client sends `asset_type`, not
        `type`. Both spellings must narrow the list."""
        from assets.models import Asset
        Asset.objects.create(
            organization=self.org_a, name='LaptopB', asset_type='laptop',
        )
        url = '/api/mobile/v1/assets/?asset_type=server'
        resp = _auth_get(self.client, url, self.token)
        self.assertEqual(resp.status_code, 200)
        types = {a['asset_type'] for a in resp.json()['results']}
        self.assertEqual(types, {'server'})

    def test_asset_list_filter_by_status(self):
        """v3.17.536 — status lives in custom_fields, same as the web list.
        Before this the param was accepted and ignored."""
        from assets.models import Asset
        Asset.objects.create(
            organization=self.org_a, name='RetiredBox',
            custom_fields={'status': 'retired'},
        )
        self.asset_a.custom_fields = {'status': 'active'}
        self.asset_a.save(update_fields=['custom_fields'])

        resp = _auth_get(
            self.client, '/api/mobile/v1/assets/?status=retired', self.token,
        )
        self.assertEqual(resp.status_code, 200)
        names = [a['name'] for a in resp.json()['results']]
        self.assertEqual(names, ['RetiredBox'])

    def test_asset_list_status_filter_is_case_insensitive(self):
        from assets.models import Asset
        Asset.objects.create(
            organization=self.org_a, name='RetiredBox',
            custom_fields={'status': 'Retired'},
        )
        resp = _auth_get(
            self.client, '/api/mobile/v1/assets/?status=retired', self.token,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            [a['name'] for a in resp.json()['results']], ['RetiredBox'],
        )

    def test_asset_rows_carry_status_and_location(self):
        """List rows render a status pill, so status must be on the list
        serializer and not only on detail."""
        self.asset_a.custom_fields = {'status': 'active', 'location': 'Rack 3'}
        self.asset_a.save(update_fields=['custom_fields'])
        resp = _auth_get(self.client, '/api/mobile/v1/assets/', self.token)
        row = next(a for a in resp.json()['results'] if a['name'] == 'ServerA')
        self.assertEqual(row['status'], 'active')
        self.assertEqual(row['location'], 'Rack 3')

    def test_asset_detail_returns_custom_fields_tags_and_creator(self):
        from core.models import Tag
        self.asset_a.custom_fields = {
            'status': 'active', 'location': 'Rack 3', 'owner': 'Finance',
        }
        self.asset_a.created_by = self.user_a
        self.asset_a.save(update_fields=['custom_fields', 'created_by'])
        tag = Tag.objects.create(organization=self.org_a, name='critical')
        self.asset_a.tags.add(tag)

        url = f'/api/mobile/v1/assets/{self.asset_a.id}/'
        body = _auth_get(self.client, url, self.token).json()
        self.assertEqual(body['status'], 'active')
        self.assertEqual(body['location'], 'Rack 3')
        self.assertEqual(body['custom_fields']['owner'], 'Finance')
        self.assertEqual(body['tags'], ['critical'])
        self.assertEqual(body['created_by_name'], 'assetuser')

    def test_asset_serializer_survives_non_dict_custom_fields(self):
        """A bad import can leave a list in the JSONField — that must not
        500 the whole list endpoint."""
        self.asset_a.custom_fields = ['junk']
        self.asset_a.save(update_fields=['custom_fields'])
        resp = _auth_get(self.client, '/api/mobile/v1/assets/', self.token)
        self.assertEqual(resp.status_code, 200)
        row = next(a for a in resp.json()['results'] if a['name'] == 'ServerA')
        self.assertEqual(row['status'], '')

    def test_asset_list_requires_auth(self):
        c = Client()
        self.assertIn(c.get('/api/mobile/v1/assets/').status_code, (401, 403))


# v3.17.349 — tickets endpoints
@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileTicketsTests(TestCase):
    """Ticket list/detail/create/patch/comment respect org scope."""

    def setUp(self):
        _clear_throttle_cache()
        from psa.models import (
            Ticket, TicketStatus, TicketPriority, TicketType, Queue,
        )
        self.org_a = Organization.objects.create(name='OrgA-Tk', slug='orga-tk')
        self.org_b = Organization.objects.create(name='OrgB-Tk', slug='orgb-tk')
        self.user_a = User.objects.create_user('tkuser', password='hunter2')
        # v3.17.477 — use Role.EDITOR (no tickets_view_all in the simple-
        # role fallback) so the cross-org scope assertions below still
        # exercise the org-membership filter. Owner gets view_all = True
        # by design and is covered separately in MobileTicketAssignPermTests.
        Membership.objects.create(
            user=self.user_a, organization=self.org_a, role=Role.EDITOR, is_active=True,
        )
        # Seed minimal PSA workflow rows
        self.status_new = TicketStatus.objects.create(name='New', slug='new', sort_order=1)
        self.status_closed = TicketStatus.objects.create(
            name='Closed', slug='closed', sort_order=99, is_terminal=True,
        )
        self.priority = TicketPriority.objects.create(code='P3', name='Normal')
        self.priority_p1 = TicketPriority.objects.create(code='P1', name='Critical')
        self.ttype = TicketType.objects.create(name='Incident', slug='incident')
        self.queue = Queue.objects.create(name='Default', slug='default')
        self.ticket_a = Ticket.objects.create(
            organization=self.org_a, subject='OrgA ticket',
            status=self.status_new, priority=self.priority,
            ticket_type=self.ttype, queue=self.queue,
        )
        self.ticket_b = Ticket.objects.create(
            organization=self.org_b, subject='OrgB ticket',
            status=self.status_new, priority=self.priority,
            ticket_type=self.ttype, queue=self.queue,
        )
        self.client = Client()
        resp = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'tkuser', 'password': 'hunter2',
        })
        self.token = resp.json()['token']

    def test_ticket_list_scoped_to_user_orgs(self):
        resp = _auth_get(self.client, '/api/mobile/v1/tickets/', self.token)
        self.assertEqual(resp.status_code, 200)
        ids = [t['id'] for t in resp.json()['results']]
        self.assertIn(self.ticket_a.id, ids)
        self.assertNotIn(self.ticket_b.id, ids)

    def test_ticket_detail_returns_my_ticket_with_comments(self):
        url = f'/api/mobile/v1/tickets/{self.ticket_a.id}/'
        resp = _auth_get(self.client, url, self.token)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['subject'], 'OrgA ticket')
        self.assertIn('comments', body)

    def test_ticket_detail_cross_org_blocked(self):
        url = f'/api/mobile/v1/tickets/{self.ticket_b.id}/'
        resp = _auth_get(self.client, url, self.token)
        self.assertEqual(resp.status_code, 404)

    def test_ticket_create(self):
        resp = _auth_post(self.client, '/api/mobile/v1/tickets/', self.token, {
            'organization_id': self.org_a.id,
            'subject': 'New ticket from mobile',
            'description': 'Help.',
        })
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()['subject'], 'New ticket from mobile')

    def test_ticket_create_cross_org_rejected(self):
        resp = _auth_post(self.client, '/api/mobile/v1/tickets/', self.token, {
            'organization_id': self.org_b.id,  # not accessible
            'subject': 'Bad attempt',
        })
        self.assertEqual(resp.status_code, 403)

    def test_ticket_patch_status(self):
        url = f'/api/mobile/v1/tickets/{self.ticket_a.id}/'
        resp = self.client.patch(
            url, data=json.dumps({'status_id': self.status_closed.id}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Token {self.token}',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'Closed')

    def test_ticket_patch_status_by_slug(self):
        """v3.17.450: mobile sends `status` (slug), not `status_id`."""
        url = f'/api/mobile/v1/tickets/{self.ticket_a.id}/'
        resp = self.client.patch(
            url, data=json.dumps({'status': 'closed'}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Token {self.token}',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['status'], 'Closed')

    def test_ticket_patch_status_unknown_slug_400(self):
        url = f'/api/mobile/v1/tickets/{self.ticket_a.id}/'
        resp = self.client.patch(
            url, data=json.dumps({'status': 'no-such-status'}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Token {self.token}',
        )
        self.assertEqual(resp.status_code, 400)

    def test_ticket_patch_priority_by_label(self):
        """v3.17.450: mobile sends `priority: 'critical'`, server maps to P1."""
        url = f'/api/mobile/v1/tickets/{self.ticket_a.id}/'
        resp = self.client.patch(
            url, data=json.dumps({'priority': 'critical'}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Token {self.token}',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        # Backend's _serialize_ticket returns the P-code, not the label,
        # so a successful 'critical' PATCH lands as 'P1' in the response.
        self.assertEqual(resp.json()['priority'], 'P1')

    def test_ticket_add_comment(self):
        url = f'/api/mobile/v1/tickets/{self.ticket_a.id}/comments/'
        resp = _auth_post(self.client, url, self.token, {
            'body': 'On site now', 'is_internal': True,
        })
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['body'], 'On site now')
        self.assertTrue(resp.json()['is_internal'])

    def test_ticket_list_requires_auth(self):
        c = Client()
        self.assertIn(c.get('/api/mobile/v1/tickets/').status_code, (401, 403))


# v3.17.350 — KB endpoints
@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileKBTests(TestCase):
    """KB list/search/detail respect global + org-scope visibility."""

    def setUp(self):
        _clear_throttle_cache()
        from docs.models import Document
        self.org_a = Organization.objects.create(name='OrgA-KB', slug='orga-kb')
        self.org_b = Organization.objects.create(name='OrgB-KB', slug='orgb-kb')
        self.user_a = User.objects.create_user('kbuser', password='hunter2')
        Membership.objects.create(
            user=self.user_a, organization=self.org_a, role=Role.OWNER, is_active=True,
        )
        self.global_doc = Document.objects.create(
            title='Global KB Article', slug='global-kb',
            body='# Global content\n\nUseful for all.',
            content_type='markdown', is_global=True, is_published=True,
        )
        self.org_a_doc = Document.objects.create(
            organization=self.org_a, title='OrgA Runbook', slug='orga-runbook',
            body='Org A specific.', content_type='markdown', is_published=True,
        )
        self.org_b_doc = Document.objects.create(
            organization=self.org_b, title='OrgB Internal', slug='orgb-internal',
            body='Secret to OrgB.', content_type='markdown', is_published=True,
        )
        self.client = Client()
        resp = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'kbuser', 'password': 'hunter2',
        })
        self.token = resp.json()['token']

    def test_kb_list_requires_auth(self):
        c = Client()
        self.assertIn(c.get('/api/mobile/v1/kb/').status_code, (401, 403))

    def test_kb_list_returns_global_and_my_org(self):
        resp = _auth_get(self.client, '/api/mobile/v1/kb/', self.token)
        self.assertEqual(resp.status_code, 200)
        ids = [d['id'] for d in resp.json()['results']]
        self.assertIn(self.global_doc.id, ids)
        self.assertIn(self.org_a_doc.id, ids)
        self.assertNotIn(self.org_b_doc.id, ids)

    def test_kb_list_search(self):
        resp = _auth_get(self.client, '/api/mobile/v1/kb/?search=Runbook', self.token)
        self.assertEqual(resp.status_code, 200)
        ids = [d['id'] for d in resp.json()['results']]
        self.assertEqual(ids, [self.org_a_doc.id])

    def test_kb_detail_returns_body_and_html(self):
        url = f'/api/mobile/v1/kb/{self.global_doc.id}/'
        resp = _auth_get(self.client, url, self.token)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['body'], '# Global content\n\nUseful for all.')
        self.assertIn('Global content</h1>', body['body_html'])

    def test_kb_detail_cross_org_blocked(self):
        url = f'/api/mobile/v1/kb/{self.org_b_doc.id}/'
        resp = _auth_get(self.client, url, self.token)
        self.assertEqual(resp.status_code, 404)


# ---------------------------------------------------------------------------
# Phase 8 — Field Ops endpoints (v3.17.410)
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileFieldOpsTests(TestCase):
    """Locations + timeclock + active-ticket endpoints."""

    def setUp(self):
        from datetime import time
        from resourcing.models import WorkingHours

        _clear_throttle_cache()
        self.org = Organization.objects.create(name='FOPS', slug='fops')
        self.user = User.objects.create_user('fops-tech', password='hunter2')
        Membership.objects.create(
            user=self.user, organization=self.org, role=Role.OWNER, is_active=True,
        )
        # Configure 9-5 weekday WorkingHours so off-shift suppression has
        # something to test against.
        for wd in range(0, 7):  # all 7 weekdays so the test is deterministic
            WorkingHours.objects.create(
                user=self.user, weekday=wd,
                start_time=time(9, 0), end_time=time(17, 0),
            )
        self.client = Client()
        resp = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'fops-tech', 'password': 'hunter2',
        })
        self.token = resp.json()['token']

    def test_location_ping_during_workhours_stored(self):
        # Build a timestamp inside 9-5 (12:00 UTC noon)
        from django.utils import timezone as tz
        when = tz.now().replace(hour=12, minute=0, second=0, microsecond=0)
        resp = _auth_post(
            self.client, '/api/mobile/v1/locations/', self.token,
            {'lat': '40.123456', 'lon': '-73.987654', 'accuracy': 10,
             'timestamp': when.isoformat()},
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        from field_ops.models import TechnicianLocation
        self.assertEqual(TechnicianLocation.objects.filter(tech=self.user).count(), 1)

    def test_location_ping_off_shift_dropped(self):
        # 02:00 UTC — outside 9-5 — should return 204 + no row
        from django.utils import timezone as tz
        when = tz.now().replace(hour=2, minute=0, second=0, microsecond=0)
        resp = _auth_post(
            self.client, '/api/mobile/v1/locations/', self.token,
            {'lat': '40.0', 'lon': '-73.0', 'timestamp': when.isoformat()},
        )
        self.assertEqual(resp.status_code, 204)
        from field_ops.models import TechnicianLocation
        self.assertEqual(TechnicianLocation.objects.filter(tech=self.user).count(), 0)
        # And an audit row was written (SQLite-safe Python filter)
        from audit.models import AuditLog
        rows = AuditLog.objects.filter(user=self.user)
        self.assertTrue(any(
            (r.extra_data or {}).get('event') == 'locations_dropped_offshift'
            for r in rows
        ))

    def test_clock_in_then_clock_out(self):
        resp = _auth_post(
            self.client, '/api/mobile/v1/timeclock/clock-in/', self.token,
            {'organization_id': self.org.id, 'notes': 'on site'},
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertIsNone(body['clocked_out_at'])

        # Second clock-in fails
        resp2 = _auth_post(
            self.client, '/api/mobile/v1/timeclock/clock-in/', self.token,
            {'organization_id': self.org.id},
        )
        self.assertEqual(resp2.status_code, 400)

        # Clock out
        resp3 = _auth_post(
            self.client, '/api/mobile/v1/timeclock/clock-out/', self.token,
            {'notes': 'done'},
        )
        self.assertEqual(resp3.status_code, 200, resp3.content)
        self.assertIsNotNone(resp3.json()['clocked_out_at'])

    def test_clock_out_without_open_returns_400(self):
        resp = _auth_post(
            self.client, '/api/mobile/v1/timeclock/clock-out/', self.token, {},
        )
        self.assertEqual(resp.status_code, 400)

    def test_timeclock_me_returns_open_or_null(self):
        resp = _auth_get(self.client, '/api/mobile/v1/timeclock/me/', self.token)
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()['entry'])
        # Now clock in
        _auth_post(
            self.client, '/api/mobile/v1/timeclock/clock-in/', self.token,
            {'organization_id': self.org.id},
        )
        resp2 = _auth_get(self.client, '/api/mobile/v1/timeclock/me/', self.token)
        self.assertIsNotNone(resp2.json()['entry'])
        self.assertEqual(resp2.json()['entry']['organization_id'], self.org.id)

    def test_active_ticket_returns_last_unsubmitted(self):
        from psa.models import (
            Queue, Ticket, TicketPriority, TicketStatus, TicketTimeEntry, TicketType,
        )
        from django.utils import timezone as tz
        sn = TicketStatus.objects.create(name='New', slug='new', sort_order=1)
        pr = TicketPriority.objects.create(code='P3', name='Normal')
        tt = TicketType.objects.create(name='Incident', slug='incident')
        qu = Queue.objects.create(name='Default', slug='default')
        ticket = Ticket.objects.create(
            organization=self.org, subject='Active', status=sn,
            priority=pr, ticket_type=tt, queue=qu,
        )
        TicketTimeEntry.objects.create(
            ticket=ticket, user=self.user,
            started_at=tz.now(), ended_at=tz.now(), is_billable=True,
        )
        resp = _auth_get(self.client, '/api/mobile/v1/active-ticket/', self.token)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsNotNone(body['ticket'])
        self.assertEqual(body['ticket']['id'], ticket.id)

    # === Geofence — v3.17.452 ===

    def _make_radius_geofence(self, lat, lon, radius=100):
        from field_ops.models import ClientSiteGeofence
        return ClientSiteGeofence.objects.create(
            organization=self.org, name='HQ',
            kind='radius', center_lat=lat, center_lon=lon,
            radius_meters=radius, active=True,
        )

    def test_clock_in_inside_geofence_no_override(self):
        self._make_radius_geofence(lat='40.000000', lon='-73.000000', radius=200)
        resp = _auth_post(
            self.client, '/api/mobile/v1/timeclock/clock-in/', self.token,
            {'organization_id': self.org.id,
             'lat': '40.000100', 'lon': '-73.000100',  # ~14m offset, inside 200m
             'accuracy': 8},
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertFalse(body['geofence_override'])
        self.assertIsNotNone(body['geofence_match_id'])

    def test_clock_in_outside_geofence_warn_but_allow(self):
        self._make_radius_geofence(lat='40.000000', lon='-73.000000', radius=100)
        resp = _auth_post(
            self.client, '/api/mobile/v1/timeclock/clock-in/', self.token,
            {'organization_id': self.org.id,
             'lat': '41.000000', 'lon': '-74.000000',  # ~140km away
             'accuracy': 12},
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertTrue(body['geofence_override'])
        self.assertIsNone(body['geofence_match_id'])
        # Audit row records the override
        from audit.models import AuditLog
        rows = AuditLog.objects.filter(user=self.user)
        self.assertTrue(any(
            (r.extra_data or {}).get('event') == 'timeclock_in'
            and (r.extra_data or {}).get('geofence_override') is True
            for r in rows
        ))

    def test_clock_in_no_active_geofence_no_override(self):
        # Org has no fences → cannot be "outside" — override stays False
        resp = _auth_post(
            self.client, '/api/mobile/v1/timeclock/clock-in/', self.token,
            {'organization_id': self.org.id,
             'lat': '40.0', 'lon': '-73.0', 'accuracy': 10},
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertFalse(body['geofence_override'])
        self.assertIsNone(body['geofence_match_id'])

    def test_clock_in_without_gps_no_override(self):
        # No coords → server can't evaluate fence; override stays False
        self._make_radius_geofence(lat='40.0', lon='-73.0', radius=100)
        resp = _auth_post(
            self.client, '/api/mobile/v1/timeclock/clock-in/', self.token,
            {'organization_id': self.org.id, 'notes': 'gps off'},
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertFalse(body['geofence_override'])
        self.assertIsNone(body['geofence_match_id'])

    def test_clock_in_invalid_gps_400(self):
        resp = _auth_post(
            self.client, '/api/mobile/v1/timeclock/clock-in/', self.token,
            {'organization_id': self.org.id,
             'lat': 'not-a-number', 'lon': '-73.0'},
        )
        self.assertEqual(resp.status_code, 400)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileAssetCreateTests(TestCase):
    """v3.17.454 — POST /api/mobile/v1/assets/ creates an asset, org-scoped."""

    def setUp(self):
        _clear_throttle_cache()
        self.org_a = Organization.objects.create(name='OrgA-Acreate', slug='orga-acreate')
        self.org_b = Organization.objects.create(name='OrgB-Acreate', slug='orgb-acreate')
        self.user = User.objects.create_user('auser', password='hunter2')
        Membership.objects.create(
            user=self.user, organization=self.org_a, role=Role.OWNER, is_active=True,
        )
        self.client = Client()
        resp = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'auser', 'password': 'hunter2',
        })
        self.token = resp.json()['token']

    def test_create_asset_in_my_org(self):
        resp = _auth_post(self.client, '/api/mobile/v1/assets/', self.token, {
            'organization_id': self.org_a.id,
            'name': 'srv-01',
            'asset_type': 'server',
            'hostname': 'srv-01.local',
            'ip_address': '10.0.0.5',
        })
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['name'], 'srv-01')
        self.assertEqual(body['organization_id'], self.org_a.id)
        from assets.models import Asset
        self.assertEqual(Asset.objects.filter(name='srv-01').count(), 1)

    def test_create_asset_other_org_forbidden(self):
        resp = _auth_post(self.client, '/api/mobile/v1/assets/', self.token, {
            'organization_id': self.org_b.id, 'name': 'cross',
        })
        self.assertEqual(resp.status_code, 403)

    def test_create_asset_missing_org_400(self):
        resp = _auth_post(self.client, '/api/mobile/v1/assets/', self.token, {
            'name': 'no-org',
        })
        self.assertEqual(resp.status_code, 400)

    def test_create_asset_missing_name_400(self):
        resp = _auth_post(self.client, '/api/mobile/v1/assets/', self.token, {
            'organization_id': self.org_a.id,
        })
        self.assertEqual(resp.status_code, 400)

    def test_create_drops_unknown_fields(self):
        resp = _auth_post(self.client, '/api/mobile/v1/assets/', self.token, {
            'organization_id': self.org_a.id, 'name': 'q',
            'evil_field': 'pwn', 'organization_id_actual': 999,
        })
        self.assertEqual(resp.status_code, 201)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileTicketTimeEntryTests(TestCase):
    """v3.17.454 — POST /api/mobile/v1/tickets/<id>/time/ logs time."""

    def setUp(self):
        from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
        _clear_throttle_cache()
        self.org = Organization.objects.create(name='OrgT-Time', slug='orgt-time')
        self.user = User.objects.create_user('tuser', password='hunter2')
        Membership.objects.create(
            user=self.user, organization=self.org, role=Role.OWNER, is_active=True,
        )
        sn = TicketStatus.objects.create(name='New', slug='new', sort_order=1)
        pr = TicketPriority.objects.create(code='P3', name='Normal')
        tt = TicketType.objects.create(name='Incident', slug='incident')
        qu = Queue.objects.create(name='Default', slug='default')
        self.ticket = Ticket.objects.create(
            organization=self.org, subject='Time test', status=sn,
            priority=pr, ticket_type=tt, queue=qu,
        )
        self.client = Client()
        resp = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'tuser', 'password': 'hunter2',
        })
        self.token = resp.json()['token']

    def test_log_time_by_duration(self):
        url = f'/api/mobile/v1/tickets/{self.ticket.id}/time/'
        resp = _auth_post(self.client, url, self.token, {
            'duration_minutes': 30, 'notes': 'phone troubleshoot',
            'is_billable': True,
        })
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['duration_minutes'], 30)
        self.assertTrue(body['is_billable'])
        from psa.models import TicketTimeEntry
        entry = TicketTimeEntry.objects.get(pk=body['id'])
        self.assertEqual(entry.user_id, self.user.id)
        self.assertEqual(entry.duration_minutes, 30)

    def test_log_time_by_started_ended(self):
        url = f'/api/mobile/v1/tickets/{self.ticket.id}/time/'
        resp = _auth_post(self.client, url, self.token, {
            'started_at': '2026-05-09T09:00:00Z',
            'ended_at':   '2026-05-09T10:30:00Z',
        })
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['duration_minutes'], 90)

    def test_log_time_missing_inputs_400(self):
        url = f'/api/mobile/v1/tickets/{self.ticket.id}/time/'
        resp = _auth_post(self.client, url, self.token, {'notes': 'no data'})
        self.assertEqual(resp.status_code, 400)

    def test_list_time_entries(self):
        url = f'/api/mobile/v1/tickets/{self.ticket.id}/time/'
        _auth_post(self.client, url, self.token, {'duration_minutes': 15})
        _auth_post(self.client, url, self.token, {'duration_minutes': 45})
        resp = _auth_get(self.client, url, self.token)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertGreaterEqual(len(body['results']), 2)

    def test_log_time_cross_org_404(self):
        other_org = Organization.objects.create(name='Other', slug='other')
        from psa.models import (
            Queue, Ticket, TicketPriority, TicketStatus, TicketType,
        )
        sn = TicketStatus.objects.filter(slug='new').first()
        pr = TicketPriority.objects.first()
        tt = TicketType.objects.first()
        qu = Queue.objects.first()
        other_ticket = Ticket.objects.create(
            organization=other_org, subject='Other org', status=sn,
            priority=pr, ticket_type=tt, queue=qu,
        )
        resp = _auth_post(
            self.client, f'/api/mobile/v1/tickets/{other_ticket.id}/time/',
            self.token, {'duration_minutes': 10},
        )
        self.assertEqual(resp.status_code, 404)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileWorkflowsTests(TestCase):
    """v3.17.455 — workflow list/detail/start + execution stage completion."""

    def setUp(self):
        from processes.models import Process, ProcessStage
        _clear_throttle_cache()
        self.org = Organization.objects.create(name='OrgW', slug='orgw')
        self.user = User.objects.create_user('wuser', password='hunter2')
        Membership.objects.create(
            user=self.user, organization=self.org, role=Role.OWNER, is_active=True,
        )
        self.proc = Process.objects.create(
            organization=self.org, title='Onboard tech',
            slug='onboard-tech', description='Welcome packet',
            category='onboarding', is_published=True,
        )
        for i, t in enumerate(['Issue laptop', 'Email setup', 'Tour']):
            ProcessStage.objects.create(
                process=self.proc, order=i, title=t,
                description=f'Step {i}',
            )
        self.client = Client()
        resp = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'wuser', 'password': 'hunter2',
        })
        self.token = resp.json()['token']

    def test_list_workflows_includes_org_process(self):
        resp = _auth_get(self.client, '/api/mobile/v1/workflows/', self.token)
        self.assertEqual(resp.status_code, 200)
        ids = [w['id'] for w in resp.json()['results']]
        self.assertIn(self.proc.id, ids)

    def test_workflow_detail_returns_stages(self):
        resp = _auth_get(
            self.client, f'/api/mobile/v1/workflows/{self.proc.id}/', self.token,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()['stages']), 3)

    def test_start_workflow_creates_execution(self):
        resp = _auth_post(
            self.client, f'/api/mobile/v1/workflows/{self.proc.id}/start/',
            self.token, {'notes': 'first run'},
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['process_id'], self.proc.id)
        self.assertEqual(body['status'], 'in_progress')
        self.assertEqual(len(body['stages']), 3)

    def test_complete_stage_then_finish_workflow(self):
        # Start
        start_resp = _auth_post(
            self.client, f'/api/mobile/v1/workflows/{self.proc.id}/start/',
            self.token, {},
        )
        exe_id = start_resp.json()['id']
        stage_ids = [s['stage_id'] for s in start_resp.json()['stages']]

        # Complete first two stages — execution still in_progress
        for sid in stage_ids[:2]:
            url = f'/api/mobile/v1/workflows/executions/{exe_id}/stages/{sid}/complete/'
            r = _auth_post(self.client, url, self.token, {})
            self.assertEqual(r.status_code, 200)

        body = _auth_get(
            self.client, f'/api/mobile/v1/workflows/executions/{exe_id}/', self.token,
        ).json()
        self.assertEqual(body['status'], 'in_progress')

        # Complete last → execution flips to completed
        last_url = f'/api/mobile/v1/workflows/executions/{exe_id}/stages/{stage_ids[2]}/complete/'
        last = _auth_post(self.client, last_url, self.token, {'notes': 'done'})
        self.assertEqual(last.json()['status'], 'completed')

    def test_complete_stage_idempotent(self):
        start = _auth_post(
            self.client, f'/api/mobile/v1/workflows/{self.proc.id}/start/',
            self.token, {},
        )
        exe_id = start.json()['id']
        sid = start.json()['stages'][0]['stage_id']
        url = f'/api/mobile/v1/workflows/executions/{exe_id}/stages/{sid}/complete/'
        r1 = _auth_post(self.client, url, self.token, {'notes': 'first'})
        r2 = _auth_post(self.client, url, self.token, {'notes': 'second'})
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        # Second wins
        for s in r2.json()['stages']:
            if s['stage_id'] == sid:
                self.assertEqual(s['notes'], 'second')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileVehiclesTests(TestCase):
    """v3.17.456 — vehicles list/detail/inventory/fuel/damage."""

    def setUp(self):
        from datetime import date
        from vehicles.models import (
            ServiceVehicle, VehicleAssignment, VehicleInventoryItem,
        )
        _clear_throttle_cache()
        self.org = Organization.objects.create(name='OrgV', slug='orgv')
        self.user = User.objects.create_user('vuser', password='hunter2')
        Membership.objects.create(
            user=self.user, organization=self.org, role=Role.OWNER, is_active=True,
        )
        self.other = User.objects.create_user('other', password='x')
        self.vehicle = ServiceVehicle.objects.create(
            name='Van 1', vehicle_type='van', make='Ford', model='Transit',
            year=2024, license_plate='ABC123', current_mileage=15000,
        )
        VehicleAssignment.objects.create(
            vehicle=self.vehicle, user=self.user,
            start_date=date.today(), starting_mileage=14500,
        )
        VehicleInventoryItem.objects.create(
            vehicle=self.vehicle, name='CAT6 cable', category='Cables',
            quantity=2, min_quantity=10, unit='box',
        )
        # Other vehicle, not assigned to me
        self.other_vehicle = ServiceVehicle.objects.create(
            name='Van 2', vehicle_type='van', make='Ford', model='Transit',
            year=2023, license_plate='XYZ999', current_mileage=80000,
        )
        VehicleAssignment.objects.create(
            vehicle=self.other_vehicle, user=self.other,
            start_date=date.today(), starting_mileage=80000,
        )
        self.client = Client()
        self.token = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'vuser', 'password': 'hunter2',
        }).json()['token']

    def test_my_vehicles_returns_full_fleet(self):
        # v3.17.477 — vehicles aren't multi-tenant; any authenticated
        # user sees every active vehicle. Previously this test asserted
        # the OTHER user's vehicle was hidden, which was the wrong shape.
        resp = _auth_get(self.client, '/api/mobile/v1/vehicles/', self.token)
        self.assertEqual(resp.status_code, 200)
        ids = {v['id'] for v in resp.json()['results']}
        self.assertIn(self.vehicle.id, ids)
        self.assertIn(self.other_vehicle.id, ids)

    def test_other_vehicle_detail_accessible(self):
        # v3.17.477 — see test_my_vehicles_returns_full_fleet.
        resp = _auth_get(
            self.client, f'/api/mobile/v1/vehicles/{self.other_vehicle.id}/',
            self.token,
        )
        self.assertEqual(resp.status_code, 200)

    def test_inventory_list(self):
        resp = _auth_get(
            self.client, f'/api/mobile/v1/vehicles/{self.vehicle.id}/inventory/',
            self.token,
        )
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()['results']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['name'], 'CAT6 cable')

    def test_log_fuel_creates_record_and_updates_mileage(self):
        resp = _auth_post(
            self.client, f'/api/mobile/v1/vehicles/{self.vehicle.id}/fuel/',
            self.token,
            {'mileage': 15300, 'gallons': '12.5', 'cost_per_gallon': '3.799',
             'station': 'Shell on Main'},
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['mileage'], 15300)
        # total_cost auto-computed
        self.assertEqual(body['total_cost'], '47.49')
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.current_mileage, 15300)

    def test_log_fuel_invalid_400(self):
        resp = _auth_post(
            self.client, f'/api/mobile/v1/vehicles/{self.vehicle.id}/fuel/',
            self.token, {'mileage': 1000, 'gallons': 'bad', 'cost_per_gallon': '3'},
        )
        self.assertEqual(resp.status_code, 400)

    def test_log_damage_creates_record(self):
        resp = _auth_post(
            self.client, f'/api/mobile/v1/vehicles/{self.vehicle.id}/damage/',
            self.token,
            {'description': 'Cracked windshield', 'severity': 'minor',
             'damage_location': 'Windshield'},
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['severity'], 'minor')
        self.assertEqual(body['damage_location'], 'Windshield')

    def test_log_damage_missing_description_400(self):
        resp = _auth_post(
            self.client, f'/api/mobile/v1/vehicles/{self.vehicle.id}/damage/',
            self.token, {'severity': 'minor'},
        )
        self.assertEqual(resp.status_code, 400)

    def test_unauthorized_blocked(self):
        c = Client()
        resp = c.get('/api/mobile/v1/vehicles/')
        self.assertIn(resp.status_code, (401, 403))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileDispatchTests(TestCase):
    """v3.17.457 — dispatch board buckets + sign-off flow."""

    def setUp(self):
        from datetime import datetime, timedelta
        from django.utils import timezone as tz
        from scheduling.models import ScheduledTask, TaskAssignment
        _clear_throttle_cache()
        self.org = Organization.objects.create(name='OrgD', slug='orgd')
        self.user = User.objects.create_user('duser', password='hunter2')
        Membership.objects.create(
            user=self.user, organization=self.org, role=Role.OWNER, is_active=True,
        )
        self.client = Client()
        self.token = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'duser', 'password': 'hunter2',
        }).json()['token']

        # 3 tasks: overdue (yesterday), today (in a few hrs), upcoming (next week)
        now = tz.now()
        self.overdue = ScheduledTask.objects.create(
            organization=self.org, title='Backup check',
            due_date=now - timedelta(hours=18), status='pending',
        )
        self.today = ScheduledTask.objects.create(
            organization=self.org, title='Patch deployment',
            due_date=now.replace(hour=23, minute=0), status='pending',
        )
        self.upcoming = ScheduledTask.objects.create(
            organization=self.org, title='Audit review',
            due_date=now + timedelta(days=5), status='pending',
        )
        for t in (self.overdue, self.today, self.upcoming):
            TaskAssignment.objects.create(task=t, user=self.user)

    def test_board_buckets_assignments(self):
        resp = _auth_get(self.client, '/api/mobile/v1/dispatch/', self.token)
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        overdue_ids = {a['task_id'] for a in body['overdue']}
        upcoming_ids = {a['task_id'] for a in body['upcoming']}
        self.assertIn(self.overdue.id, overdue_ids)
        self.assertIn(self.upcoming.id, upcoming_ids)
        self.assertEqual(body['tickets']['open_count'], 0)

    def test_acknowledge_assignment(self):
        from scheduling.models import TaskAssignment
        a = TaskAssignment.objects.get(task=self.today, user=self.user)
        resp = _auth_post(
            self.client, f'/api/mobile/v1/dispatch/assignments/{a.id}/ack/',
            self.token, {'notes': 'all set'},
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertTrue(body['acknowledged'])
        self.assertEqual(body['notes'], 'all set')
        a.refresh_from_db()
        self.assertTrue(a.acknowledged)

    def test_acknowledge_other_user_assignment_404(self):
        other = User.objects.create_user('eve', password='x')
        from scheduling.models import TaskAssignment
        a = TaskAssignment.objects.create(task=self.today, user=other)
        resp = _auth_post(
            self.client, f'/api/mobile/v1/dispatch/assignments/{a.id}/ack/',
            self.token, {},
        )
        self.assertEqual(resp.status_code, 404)

    def test_add_task_comment(self):
        resp = _auth_post(
            self.client,
            f'/api/mobile/v1/dispatch/tasks/{self.today.id}/comments/',
            self.token, {'body': 'On site, starting now'},
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        from scheduling.models import TaskComment
        self.assertEqual(
            TaskComment.objects.filter(task=self.today).count(), 1,
        )

    def test_comment_on_unassigned_task_404(self):
        other_org = Organization.objects.create(name='X', slug='x')
        from scheduling.models import ScheduledTask
        unassigned = ScheduledTask.objects.create(
            organization=other_org, title='Not mine',
        )
        resp = _auth_post(
            self.client, f'/api/mobile/v1/dispatch/tasks/{unassigned.id}/comments/',
            self.token, {'body': 'should fail'},
        )
        self.assertEqual(resp.status_code, 404)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileInventoryTests(TestCase):
    """v3.17.458 — inventory list/detail/transactions, org-scoped."""

    def setUp(self):
        from inventory.models import InventoryItem
        _clear_throttle_cache()
        self.org_a = Organization.objects.create(name='OrgA-Inv', slug='orga-inv')
        self.org_b = Organization.objects.create(name='OrgB-Inv', slug='orgb-inv')
        self.user = User.objects.create_user('iuser', password='hunter2')
        Membership.objects.create(
            user=self.user, organization=self.org_a, role=Role.OWNER, is_active=True,
        )
        self.item_a = InventoryItem.objects.create(
            organization=self.org_a, name='RJ45 connectors', sku='RJ45-100',
            quantity=50, min_quantity=20, unit='pack',
        )
        self.item_low = InventoryItem.objects.create(
            organization=self.org_a, name='Cat6 cable', sku='CAT6-1000',
            quantity=2, min_quantity=10, unit='box',
        )
        self.item_b = InventoryItem.objects.create(
            organization=self.org_b, name='Other org item', sku='OO-1',
            quantity=1, min_quantity=0,
        )
        self.client = Client()
        self.token = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'iuser', 'password': 'hunter2',
        }).json()['token']

    def test_list_returns_only_my_org(self):
        resp = _auth_get(self.client, '/api/mobile/v1/inventory/', self.token)
        self.assertEqual(resp.status_code, 200, resp.content)
        ids = {i['id'] for i in resp.json()['results']}
        self.assertIn(self.item_a.id, ids)
        self.assertIn(self.item_low.id, ids)
        self.assertNotIn(self.item_b.id, ids)

    def test_low_stock_filter(self):
        resp = self.client.get(
            '/api/mobile/v1/inventory/?low_stock=true',
            HTTP_AUTHORIZATION=f'Token {self.token}',
        )
        ids = {i['id'] for i in resp.json()['results']}
        self.assertIn(self.item_low.id, ids)
        self.assertNotIn(self.item_a.id, ids)

    def test_other_org_detail_404(self):
        resp = _auth_get(
            self.client, f'/api/mobile/v1/inventory/{self.item_b.id}/', self.token,
        )
        self.assertEqual(resp.status_code, 404)

    def test_stock_in_increments_quantity(self):
        url = f'/api/mobile/v1/inventory/{self.item_a.id}/transactions/'
        resp = _auth_post(self.client, url, self.token, {
            'transaction_type': 'stock_in',
            'quantity_change': 10,
            'notes': 'received from vendor',
        })
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['quantity_change'], 10)
        self.assertEqual(body['quantity_after'], 60)
        self.item_a.refresh_from_db()
        self.assertEqual(self.item_a.quantity, 60)

    def test_stock_out_negates_sign(self):
        # Sending +5 with stock_out should be coerced to -5
        url = f'/api/mobile/v1/inventory/{self.item_a.id}/transactions/'
        resp = _auth_post(self.client, url, self.token, {
            'transaction_type': 'stock_out',
            'quantity_change': 5,
        })
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()['quantity_change'], -5)
        self.assertEqual(resp.json()['quantity_after'], 45)

    def test_negative_stock_blocked(self):
        url = f'/api/mobile/v1/inventory/{self.item_low.id}/transactions/'
        resp = _auth_post(self.client, url, self.token, {
            'transaction_type': 'stock_out',
            'quantity_change': 99,
        })
        self.assertEqual(resp.status_code, 400)

    def test_invalid_type_rejected(self):
        url = f'/api/mobile/v1/inventory/{self.item_a.id}/transactions/'
        resp = _auth_post(self.client, url, self.token, {
            'transaction_type': 'fake_action',
            'quantity_change': 1,
        })
        self.assertEqual(resp.status_code, 400)

    def test_zero_change_rejected(self):
        url = f'/api/mobile/v1/inventory/{self.item_a.id}/transactions/'
        resp = _auth_post(self.client, url, self.token, {
            'transaction_type': 'adjustment',
            'quantity_change': 0,
        })
        self.assertEqual(resp.status_code, 400)

    def test_cross_org_transactions_404(self):
        url = f'/api/mobile/v1/inventory/{self.item_b.id}/transactions/'
        resp = _auth_post(self.client, url, self.token, {
            'transaction_type': 'stock_in',
            'quantity_change': 1,
        })
        self.assertEqual(resp.status_code, 404)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileScanTests(TestCase):
    """v3.17.461 — /api/mobile/v1/scan/?code=X resolves to inventory / asset."""

    def setUp(self):
        from inventory.models import InventoryItem
        from assets.models import Asset
        _clear_throttle_cache()
        self.org_a = Organization.objects.create(name='OrgA-Scan', slug='orga-scan')
        self.org_b = Organization.objects.create(name='OrgB-Scan', slug='orgb-scan')
        self.user = User.objects.create_user('suser', password='hunter2')
        Membership.objects.create(
            user=self.user, organization=self.org_a, role=Role.OWNER, is_active=True,
        )
        self.inv = InventoryItem.objects.create(
            organization=self.org_a, name='Cable spool', qr_code='INV-CABLE-001',
            quantity=10, unit='ea',
        )
        self.inv_other = InventoryItem.objects.create(
            organization=self.org_b, name='Other org spool', qr_code='INV-OTHER-001',
            quantity=5,
        )
        self.asset = Asset.objects.create(
            organization=self.org_a, name='Server 01', asset_tag='SRV-01',
            serial_number='SN12345',
        )
        self.client = Client()
        self.token = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'suser', 'password': 'hunter2',
        }).json()['token']

    def test_scan_inventory_qr(self):
        resp = self.client.get(
            '/api/mobile/v1/scan/?code=INV-CABLE-001',
            HTTP_AUTHORIZATION=f'Token {self.token}',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body['kind'], 'inventory')
        self.assertEqual(body['id'], self.inv.id)
        self.assertEqual(body['route'], f'/inventory/{self.inv.id}')

    def test_scan_inventory_cross_org_404(self):
        resp = self.client.get(
            '/api/mobile/v1/scan/?code=INV-OTHER-001',
            HTTP_AUTHORIZATION=f'Token {self.token}',
        )
        self.assertEqual(resp.status_code, 404)

    def test_scan_asset_tag(self):
        resp = self.client.get(
            '/api/mobile/v1/scan/?code=SRV-01',
            HTTP_AUTHORIZATION=f'Token {self.token}',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body['kind'], 'asset')
        self.assertEqual(body['id'], self.asset.id)

    def test_scan_asset_serial(self):
        resp = self.client.get(
            '/api/mobile/v1/scan/?code=SN12345',
            HTTP_AUTHORIZATION=f'Token {self.token}',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['kind'], 'asset')

    def test_scan_unknown_404(self):
        resp = self.client.get(
            '/api/mobile/v1/scan/?code=NOPE',
            HTTP_AUTHORIZATION=f'Token {self.token}',
        )
        self.assertEqual(resp.status_code, 404)

    def test_scan_missing_code_400(self):
        resp = self.client.get(
            '/api/mobile/v1/scan/',
            HTTP_AUTHORIZATION=f'Token {self.token}',
        )
        self.assertEqual(resp.status_code, 400)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileDispatchCalendarTests(TestCase):
    """v3.17.462 — /dispatch/calendar/ buckets assignments by date."""

    def setUp(self):
        from datetime import datetime, timezone as stdlib_tz
        from scheduling.models import ScheduledTask, TaskAssignment
        _clear_throttle_cache()
        self.org = Organization.objects.create(name='OrgC', slug='orgc')
        self.user = User.objects.create_user('cuser', password='hunter2')
        Membership.objects.create(
            user=self.user, organization=self.org, role=Role.OWNER, is_active=True,
        )
        # 2 tasks in May 2026, 1 in June (out of month)
        may1 = datetime(2026, 5, 5, 14, 0, tzinfo=stdlib_tz.utc)
        may2 = datetime(2026, 5, 5, 17, 0, tzinfo=stdlib_tz.utc)
        may3 = datetime(2026, 5, 20, 9, 0, tzinfo=stdlib_tz.utc)
        jun1 = datetime(2026, 6, 1, 9, 0, tzinfo=stdlib_tz.utc)
        for d in (may1, may2, may3, jun1):
            t = ScheduledTask.objects.create(
                organization=self.org, title=f'Task at {d}', due_date=d,
            )
            TaskAssignment.objects.create(task=t, user=self.user)
        self.client = Client()
        self.token = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'cuser', 'password': 'hunter2',
        }).json()['token']

    def test_calendar_returns_month(self):
        resp = self.client.get(
            '/api/mobile/v1/dispatch/calendar/?month=2026-05',
            HTTP_AUTHORIZATION=f'Token {self.token}',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body['month'], '2026-05')
        days = body['days']
        self.assertEqual(len(days['2026-05-05']), 2)  # two same-day tasks
        self.assertIn('2026-05-20', days)
        self.assertNotIn('2026-06-01', days)  # out of month

    def test_calendar_invalid_month_400(self):
        resp = self.client.get(
            '/api/mobile/v1/dispatch/calendar/?month=bogus',
            HTTP_AUTHORIZATION=f'Token {self.token}',
        )
        self.assertEqual(resp.status_code, 400)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileNotificationRegisterTests(TestCase):
    """v3.17.463 — push token registration + deregistration."""

    def setUp(self):
        _clear_throttle_cache()
        self.org = Organization.objects.create(name='OrgN', slug='orgn')
        self.user = User.objects.create_user('nuser', password='hunter2')
        Membership.objects.create(
            user=self.user, organization=self.org, role=Role.OWNER, is_active=True,
        )
        self.client = Client()
        self.token = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'nuser', 'password': 'hunter2',
        }).json()['token']

    def test_register_creates_device(self):
        from field_ops.models import MobileDevice
        device_id = 'a' * 8 + '-' + 'b' * 4 + '-4cdb-' + '9' + 'c' * 3 + '-' + 'd' * 12
        resp = _auth_post(
            self.client, '/api/mobile/v1/notifications/register/', self.token,
            {
                'token': 'ExponentPushToken[xxxxxxxx]',
                'platform': 'android',
                'device_id': device_id,
                'name': 'Pixel 8',
            },
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['device_id'], device_id)
        self.assertTrue(body['created'])
        device = MobileDevice.objects.get(device_id=device_id)
        self.assertEqual(device.user_id, self.user.id)
        self.assertEqual(device.expo_push_token, 'ExponentPushToken[xxxxxxxx]')

    def test_register_missing_token_400(self):
        resp = _auth_post(
            self.client, '/api/mobile/v1/notifications/register/', self.token,
            {'platform': 'android'},
        )
        self.assertEqual(resp.status_code, 400)

    def test_register_idempotent(self):
        # Same device_id twice → second call updates in place, not created
        device_id = 'a' * 8 + '-' + 'b' * 4 + '-4cdb-' + '9' + 'c' * 3 + '-' + 'd' * 12
        r1 = _auth_post(
            self.client, '/api/mobile/v1/notifications/register/', self.token,
            {'token': 'ExponentPushToken[a]', 'device_id': device_id},
        )
        r2 = _auth_post(
            self.client, '/api/mobile/v1/notifications/register/', self.token,
            {'token': 'ExponentPushToken[b]', 'device_id': device_id},
        )
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 200)
        self.assertFalse(r2.json()['created'])
        from field_ops.models import MobileDevice
        self.assertEqual(
            MobileDevice.objects.get(device_id=device_id).expo_push_token,
            'ExponentPushToken[b]',
        )

    def test_deregister_revokes(self):
        from field_ops.models import MobileDevice
        device_id = 'a' * 8 + '-' + 'b' * 4 + '-4cdb-' + '9' + 'c' * 3 + '-' + 'd' * 12
        _auth_post(
            self.client, '/api/mobile/v1/notifications/register/', self.token,
            {'token': 'ExponentPushToken[x]', 'device_id': device_id},
        )
        resp = _auth_post(
            self.client, '/api/mobile/v1/notifications/deregister/', self.token,
            {'device_id': device_id},
        )
        self.assertEqual(resp.status_code, 200)
        d = MobileDevice.objects.get(device_id=device_id)
        self.assertTrue(d.revoked)
        self.assertEqual(d.expo_push_token, '')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileOcrEndpointTests(TestCase):
    """
    v3.17.465 — /api/mobile/v1/ocr/receipt/ returns 503 unless
    OCR_PROVIDER is set. The actual OCR pipeline isn't tested here
    (requires a Cloud Vision SDK + credentials); we only verify the
    "off by default" contract and the regex parser.
    """

    def setUp(self):
        _clear_throttle_cache()
        self.org = Organization.objects.create(name='OrgO', slug='orgo')
        self.user = User.objects.create_user('ouser', password='hunter2')
        Membership.objects.create(
            user=self.user, organization=self.org, role=Role.OWNER, is_active=True,
        )
        self.client = Client()
        self.token = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'ouser', 'password': 'hunter2',
        }).json()['token']

    def test_ocr_disabled_returns_503(self):
        import os
        old = os.environ.pop('OCR_PROVIDER', None)
        try:
            from django.core.files.uploadedfile import SimpleUploadedFile
            photo = SimpleUploadedFile('receipt.jpg', b'fake-bytes',
                                       content_type='image/jpeg')
            resp = self.client.post(
                '/api/mobile/v1/ocr/receipt/',
                data={'photo': photo},
                HTTP_AUTHORIZATION=f'Token {self.token}',
            )
            self.assertEqual(resp.status_code, 503)
            self.assertIn('OCR not configured', resp.json()['detail'])
        finally:
            if old is not None:
                os.environ['OCR_PROVIDER'] = old

    def test_regex_parser_extracts_fuel_fields(self):
        """Direct test of the receipt parser against synthetic OCR text."""
        from api_mobile.views_ocr import _parse_receipt_text
        text = """
        SHELL
        123 Main St
        Date: 2026-05-09
        Gallons: 12.5
        Price/gal: $3.799
        Total: $47.49
        """
        out = _parse_receipt_text(text)
        self.assertEqual(out.get('gallons'), '12.5')
        self.assertEqual(out.get('cost_per_gallon'), '3.799')
        self.assertEqual(out.get('total_cost'), '47.49')
        self.assertEqual(out.get('station'), 'Shell')
        self.assertEqual(out.get('date_raw'), '2026-05-09')

    def test_regex_parser_handles_partial_receipt(self):
        from api_mobile.views_ocr import _parse_receipt_text
        # Only gallons + total — no price-per-gal, no station match
        text = "Gallons 8.0  Total $24.00"
        out = _parse_receipt_text(text)
        self.assertEqual(out.get('gallons'), '8.0')
        self.assertEqual(out.get('total_cost'), '24.00')
        self.assertNotIn('station', out)
        self.assertNotIn('cost_per_gallon', out)

    def test_ocr_status_reports_disabled(self):
        import os
        old = os.environ.pop('OCR_PROVIDER', None)
        try:
            resp = _auth_get(self.client, '/api/mobile/v1/ocr/status/', self.token)
            self.assertEqual(resp.status_code, 200, resp.content)
            body = resp.json()
            self.assertFalse(body['configured'])
            self.assertIsNone(body['provider'])
        finally:
            if old is not None:
                os.environ['OCR_PROVIDER'] = old


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, REST_FRAMEWORK=NO_THROTTLE_REST)
class MobilePushSignalsTests(TestCase):
    """
    v3.17.467 — verify the expanded signal coverage triggers
    `send_push_to_user`. Mocks the actual HTTP delivery via patching
    `api_mobile.push.send_push_to_user`. We only assert the call
    happened with the right user — payload shape is the receiver's
    business.
    """

    def setUp(self):
        from unittest.mock import patch
        _clear_throttle_cache()
        self.org = Organization.objects.create(name='OrgP', slug='orgp')
        self.assignee = User.objects.create_user('assignee', password='x')
        self.commenter = User.objects.create_user('commenter', password='x')
        Membership.objects.create(
            user=self.assignee, organization=self.org, role=Role.OWNER, is_active=True,
        )
        Membership.objects.create(
            user=self.commenter, organization=self.org, role=Role.OWNER, is_active=True,
        )
        # Patch the single egress point in api_mobile.signals so we don't
        # have to chase the per-receiver `from .push import ...` imports.
        self._patcher = patch('api_mobile.signals._dispatch_push')
        self.mock_push = self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def _make_ticket(self):
        from psa.models import (
            Queue, Ticket, TicketPriority, TicketStatus, TicketType,
        )
        sn = TicketStatus.objects.create(name='New', slug='new', sort_order=1)
        pr = TicketPriority.objects.create(code='P3', name='Normal')
        tt = TicketType.objects.create(name='Incident', slug='incident')
        qu = Queue.objects.create(name='Default', slug='default')
        return Ticket.objects.create(
            organization=self.org, subject='Test', status=sn,
            priority=pr, ticket_type=tt, queue=qu, assigned_to=self.assignee,
        )

    def test_ticket_comment_pushes_assignee(self):
        from psa.models import TicketComment
        ticket = self._make_ticket()
        self.mock_push.reset_mock()
        TicketComment.objects.create(
            ticket=ticket, author=self.commenter, body='Status?',
        )
        # First call should target the assignee
        self.mock_push.assert_called()
        called_user = self.mock_push.call_args.args[0]
        self.assertEqual(called_user.pk, self.assignee.pk)

    def test_ticket_comment_does_not_push_self(self):
        """Author == assignee → no push (tech commenting on their own)."""
        from psa.models import TicketComment
        ticket = self._make_ticket()
        self.mock_push.reset_mock()
        TicketComment.objects.create(
            ticket=ticket, author=self.assignee, body='Working on it',
        )
        for call in self.mock_push.call_args_list:
            self.assertNotEqual(call.args[0].pk, self.assignee.pk)

    def test_task_assignment_pushes_user(self):
        from scheduling.models import ScheduledTask, TaskAssignment
        t = ScheduledTask.objects.create(
            organization=self.org, title='Patch the server',
        )
        self.mock_push.reset_mock()
        TaskAssignment.objects.create(task=t, user=self.assignee)
        self.mock_push.assert_called()
        self.assertEqual(self.mock_push.call_args.args[0].pk, self.assignee.pk)

    def test_process_execution_assigned_by_other_pushes(self):
        from processes.models import Process, ProcessExecution
        p = Process.objects.create(
            organization=self.org, title='Onboarding', slug='onboarding',
            is_published=True,
        )
        self.mock_push.reset_mock()
        ProcessExecution.objects.create(
            process=p, organization=self.org,
            assigned_to=self.assignee, started_by=self.commenter,
            status='in_progress',
        )
        self.mock_push.assert_called()
        self.assertEqual(self.mock_push.call_args.args[0].pk, self.assignee.pk)

    def test_process_self_started_does_not_push(self):
        from processes.models import Process, ProcessExecution
        p = Process.objects.create(
            organization=self.org, title='X', slug='x', is_published=True,
        )
        self.mock_push.reset_mock()
        ProcessExecution.objects.create(
            process=p, organization=self.org,
            assigned_to=self.assignee, started_by=self.assignee,
            status='in_progress',
        )
        # No push — user already at the screen
        self.assertEqual(self.mock_push.call_count, 0)

    def test_receipt_uploaded_with_image_creates_record(self):
        """v3.17.470 — POST /receipts/ stores a VehicleReceipt + Attachment.
        OCR is off in tests so amount stays at the default 0; we just
        verify the row + image got persisted."""
        from datetime import date
        from django.core.files.uploadedfile import SimpleUploadedFile
        from vehicles.models import ServiceVehicle, VehicleAssignment, VehicleReceipt
        from files.models import Attachment

        vehicle = ServiceVehicle.objects.create(
            name='Van A', vehicle_type='van', make='Ford', model='Transit',
            year=2024, license_plate='RX1', current_mileage=5000,
        )
        VehicleAssignment.objects.create(
            vehicle=vehicle, user=self.assignee,
            start_date=date.today(), starting_mileage=4500,
        )
        token = _post(Client(), '/api/mobile/v1/auth/login/', {
            'username': 'assignee', 'password': 'x',
        }).json()['token']

        photo = SimpleUploadedFile('receipt.jpg', b'\xff\xd8\xff\xe0fake-jpeg',
                                   content_type='image/jpeg')
        client = Client()
        resp = client.post(
            '/api/mobile/v1/receipts/',
            data={
                'photo': photo,
                'vehicle_id': str(vehicle.id),
                'category': 'fuel',
                'notes': 'paid cash',
            },
            HTTP_AUTHORIZATION=f'Token {token}',
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertFalse(body.get('duplicate', False))
        self.assertEqual(body['receipt']['category'], 'fuel')
        self.assertEqual(body['receipt']['notes'], 'paid cash')

        r = VehicleReceipt.objects.get(pk=body['receipt']['id'])
        self.assertEqual(r.vehicle_id, vehicle.id)
        self.assertEqual(r.created_by_id, self.assignee.pk)
        self.assertNotEqual(r.image_hash, '')

        att = Attachment.objects.filter(
            entity_type='vehicle_receipt', entity_id=r.pk,
        ).first()
        self.assertIsNotNone(att, 'attachment should be created')

    def test_receipt_dedup_returns_existing(self):
        """Same image_hash → 200 with duplicate: true; no new row."""
        from datetime import date
        from django.core.files.uploadedfile import SimpleUploadedFile
        from vehicles.models import ServiceVehicle, VehicleAssignment, VehicleReceipt

        vehicle = ServiceVehicle.objects.create(
            name='Van B', vehicle_type='van', make='Ford', model='E-Series',
            year=2023, license_plate='RX2', current_mileage=80000,
        )
        VehicleAssignment.objects.create(
            vehicle=vehicle, user=self.assignee,
            start_date=date.today(), starting_mileage=79000,
        )
        token = _post(Client(), '/api/mobile/v1/auth/login/', {
            'username': 'assignee', 'password': 'x',
        }).json()['token']

        client = Client()
        # First upload — creates
        client.post(
            '/api/mobile/v1/receipts/',
            data={
                'photo': SimpleUploadedFile('r.jpg', b'identical-bytes-payload', 'image/jpeg'),
                'vehicle_id': str(vehicle.id),
                'category': 'other',
            },
            HTTP_AUTHORIZATION=f'Token {token}',
        )
        before = VehicleReceipt.objects.count()
        # Second upload, same bytes → duplicate
        resp = client.post(
            '/api/mobile/v1/receipts/',
            data={
                'photo': SimpleUploadedFile('r.jpg', b'identical-bytes-payload', 'image/jpeg'),
                'vehicle_id': str(vehicle.id),
                'category': 'other',
            },
            HTTP_AUTHORIZATION=f'Token {token}',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.json()['duplicate'])
        self.assertEqual(VehicleReceipt.objects.count(), before)

    def test_receipt_llm_extraction_fills_fields(self):
        """v3.17.471 — when the configured LLM provider returns parsed
        receipt fields, the upload flow uses them to populate the
        VehicleReceipt + auto-create a VehicleFuelLog."""
        from datetime import date
        from unittest.mock import patch, MagicMock
        from django.core.files.uploadedfile import SimpleUploadedFile
        from vehicles.models import ServiceVehicle, VehicleAssignment, VehicleReceipt, VehicleFuelLog

        vehicle = ServiceVehicle.objects.create(
            name='Van LLM', vehicle_type='van', make='Ford', model='Transit',
            year=2024, license_plate='LLM1', current_mileage=10000,
        )
        VehicleAssignment.objects.create(
            vehicle=vehicle, user=self.assignee,
            start_date=date.today(), starting_mileage=9900,
        )
        token = _post(Client(), '/api/mobile/v1/auth/login/', {
            'username': 'assignee', 'password': 'x',
        }).json()['token']

        fake_provider = MagicMock()
        fake_provider.extract_receipt_fields.return_value = {
            'success': True,
            'extracted': {
                'vendor': 'Shell Station #4499',
                'amount_total': 47.49,
                'amount_tax': 3.50,
                'date': '2026-05-11',
                'gallons': 12.5,
                'cost_per_gallon': 3.799,
                'odometer': 10250,
                'category_hint': 'fuel',
                'line_items': ['Regular gasoline 12.5 gal'],
                'raw_text': 'SHELL\nGallons: 12.5\nTotal $47.49',
            },
        }
        with patch(
            'docs.services.llm_providers.get_configured_provider',
            return_value=fake_provider,
        ):
            client = Client()
            resp = client.post(
                '/api/mobile/v1/receipts/',
                data={
                    'photo': SimpleUploadedFile('r.jpg', b'\xff\xd8\xff\xe0fake', 'image/jpeg'),
                    'vehicle_id': str(vehicle.id),
                    'category': 'fuel',
                },
                HTTP_AUTHORIZATION=f'Token {token}',
            )

        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['receipt']['vendor'], 'Shell Station #4499')
        self.assertEqual(body['receipt']['amount'], '47.49')
        self.assertEqual(body['receipt']['receipt_date'], '2026-05-11')
        self.assertIn(body['receipt']['ai_confidence'], ('low', 'medium', 'high'))
        self.assertIsNotNone(body['fuel_log_id'])
        # The fuel log row was actually created
        fl = VehicleFuelLog.objects.get(pk=body['fuel_log_id'])
        self.assertEqual(str(fl.gallons), '12.50')
        self.assertEqual(str(fl.cost_per_gallon), '3.799')
        self.assertEqual(fl.station, 'Shell Station #4499')

    def test_receipt_llm_no_provider_still_saves(self):
        """No LLM configured → receipt still saved with image; just no
        extracted fields. Falls through gracefully."""
        from datetime import date
        from unittest.mock import patch
        from django.core.files.uploadedfile import SimpleUploadedFile
        from vehicles.models import ServiceVehicle, VehicleAssignment, VehicleReceipt

        vehicle = ServiceVehicle.objects.create(
            name='Van Nollm', vehicle_type='van', make='X', model='Y',
            year=2023, license_plate='NLM', current_mileage=0,
        )
        VehicleAssignment.objects.create(
            vehicle=vehicle, user=self.assignee,
            start_date=date.today(), starting_mileage=0,
        )
        token = _post(Client(), '/api/mobile/v1/auth/login/', {
            'username': 'assignee', 'password': 'x',
        }).json()['token']

        with patch('docs.services.llm_providers.get_configured_provider',
                   return_value=None), \
             patch('api_mobile.views_ocr._ocr_provider', return_value=''):
            client = Client()
            resp = client.post(
                '/api/mobile/v1/receipts/',
                data={
                    'photo': SimpleUploadedFile('x.jpg', b'unique-bytes-nollm', 'image/jpeg'),
                    'vehicle_id': str(vehicle.id),
                    'category': 'other',
                },
                HTTP_AUTHORIZATION=f'Token {token}',
            )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        # Receipt persisted but no extraction
        self.assertFalse(body['receipt']['ai_processed'])
        self.assertEqual(body['receipt']['vendor'], '')
        self.assertIsNone(body['fuel_log_id'])

    def test_receipt_other_vehicle_404(self):
        """Receipt for someone else's vehicle is rejected."""
        from datetime import date
        from django.core.files.uploadedfile import SimpleUploadedFile
        from vehicles.models import ServiceVehicle, VehicleAssignment

        other = User.objects.create_user('other_tech', password='x')
        other_v = ServiceVehicle.objects.create(
            name='Other van', vehicle_type='van', make='X', model='Y',
            year=2024, license_plate='OTH', current_mileage=0,
        )
        VehicleAssignment.objects.create(
            vehicle=other_v, user=other,
            start_date=date.today(), starting_mileage=0,
        )
        token = _post(Client(), '/api/mobile/v1/auth/login/', {
            'username': 'assignee', 'password': 'x',
        }).json()['token']

        client = Client()
        resp = client.post(
            '/api/mobile/v1/receipts/',
            data={
                'photo': SimpleUploadedFile('r.jpg', b'data', 'image/jpeg'),
                'vehicle_id': str(other_v.id),
                'category': 'fuel',
            },
            HTTP_AUTHORIZATION=f'Token {token}',
        )
        self.assertEqual(resp.status_code, 404)

    def test_vault_reveal_approved_pushes_requester(self):
        from vault.models import Password, VaultRevealRequest
        from vault.encryption_v2 import encrypt_password
        pw = Password.objects.create(
            organization=self.org, title='Router',
            encrypted_password=encrypt_password('secret', org_id=self.org.id),
            requires_reveal_approval=True,
        )
        # Create pending — should not push yet
        self.mock_push.reset_mock()
        vrr = VaultRevealRequest.objects.create(
            password=pw, requester=self.assignee, status='pending',
        )
        # Approve — should push
        vrr.status = 'approved'
        vrr.save()
        self.mock_push.assert_called()
        self.assertEqual(self.mock_push.call_args.args[0].pk, self.assignee.pk)


# === v3.17.477 follow-up tests ====================================
#
# Cover: PSA tickets_assign permission gate on PATCH, /users/assignable/
# endpoint, /auth/me/ permission map, /dashboard/ new_tickets count,
# /vehicles/ returning the whole fleet, and the serializer surfacing
# `organization_name` + `assigned_to_name`.


def _seed_psa_baseline():
    """Helper for v3.17.477 ticket-perm tests — minimal PSA reference rows."""
    from psa.models import TicketStatus, TicketPriority, TicketType, Queue
    status_new, _ = TicketStatus.objects.get_or_create(
        slug='new', defaults={'name': 'New', 'sort_order': 1},
    )
    priority_p1, _ = TicketPriority.objects.get_or_create(
        code='P1', defaults={'name': 'Critical'},
    )
    priority_p3, _ = TicketPriority.objects.get_or_create(
        code='P3', defaults={'name': 'Normal'},
    )
    ttype, _ = TicketType.objects.get_or_create(
        slug='incident', defaults={'name': 'Incident'},
    )
    queue, _ = Queue.objects.get_or_create(
        slug='default', defaults={'name': 'Default'},
    )
    return status_new, priority_p1, priority_p3, ttype, queue


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileTicketAssignPermTests(TestCase):
    """v3.17.477 — PATCH assigned_to_id requires tickets_assign, except for
    self-claim and unassign."""

    def setUp(self):
        _clear_throttle_cache()
        from psa.models import Ticket
        from accounts.models import RoleTemplate
        self.org = Organization.objects.create(name='AsgOrg', slug='asg')
        self.tech = User.objects.create_user('tech1', password='hunter2')
        self.tech_other = User.objects.create_user('tech2', password='hunter2')
        self.manager = User.objects.create_user('mgr1', password='hunter2')
        # Tech: no tickets_assign perm. Manager: has tickets_assign.
        tech_tpl = RoleTemplate.objects.create(
            name='Tech-NoAssign', is_system_template=False,
            tickets_view=True, tickets_create=True, tickets_edit=True,
            tickets_assign=False,
        )
        mgr_tpl = RoleTemplate.objects.create(
            name='Mgr-Assign', is_system_template=False,
            tickets_view=True, tickets_create=True, tickets_edit=True,
            tickets_assign=True,
        )
        Membership.objects.create(
            user=self.tech, organization=self.org, role=Role.ADMIN,
            role_template=tech_tpl, is_active=True,
        )
        Membership.objects.create(
            user=self.tech_other, organization=self.org, role=Role.ADMIN,
            role_template=tech_tpl, is_active=True,
        )
        Membership.objects.create(
            user=self.manager, organization=self.org, role=Role.OWNER,
            role_template=mgr_tpl, is_active=True,
        )
        status_new, _p1, p3, ttype, queue = _seed_psa_baseline()
        self.ticket = Ticket.objects.create(
            organization=self.org, subject='Assignable ticket',
            status=status_new, priority=p3, ticket_type=ttype, queue=queue,
        )
        self.client = Client()
        self.tech_token = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'tech1', 'password': 'hunter2',
        }).json()['token']
        self.mgr_token = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'mgr1', 'password': 'hunter2',
        }).json()['token']

    def _patch(self, token, body):
        return self.client.patch(
            f'/api/mobile/v1/tickets/{self.ticket.id}/',
            data=json.dumps(body), content_type='application/json',
            HTTP_AUTHORIZATION=f'Token {token}',
        )

    def test_self_claim_allowed_without_assign_perm(self):
        resp = self._patch(self.tech_token, {'assigned_to_id': self.tech.id})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['assigned_to_id'], self.tech.id)

    def test_reassign_to_other_user_blocked_without_perm(self):
        resp = self._patch(self.tech_token, {'assigned_to_id': self.tech_other.id})
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_unassign_allowed_without_assign_perm(self):
        # First assign as manager so we have someone to unassign.
        self._patch(self.mgr_token, {'assigned_to_id': self.tech_other.id})
        resp = self._patch(self.tech_token, {'assigned_to_id': None})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIsNone(resp.json()['assigned_to_id'])

    def test_reassign_allowed_with_assign_perm(self):
        resp = self._patch(self.mgr_token, {'assigned_to_id': self.tech_other.id})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['assigned_to_id'], self.tech_other.id)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileAssignableUsersTests(TestCase):
    """v3.17.477 — /users/assignable/ scopes the picker to peers, and to
    just the caller when they lack tickets_assign."""

    def setUp(self):
        _clear_throttle_cache()
        from accounts.models import RoleTemplate
        self.org = Organization.objects.create(name='AsgListOrg', slug='asglist')
        self.tech = User.objects.create_user('atech', password='hunter2')
        self.peer = User.objects.create_user('apeer', password='hunter2')
        self.outsider = User.objects.create_user('aout', password='hunter2')
        self.manager = User.objects.create_user('amgr', password='hunter2')
        tech_tpl = RoleTemplate.objects.create(
            name='Tech-NoAssign-AL', is_system_template=False,
            tickets_assign=False,
        )
        mgr_tpl = RoleTemplate.objects.create(
            name='Mgr-Assign-AL', is_system_template=False,
            tickets_assign=True,
        )
        for u in (self.tech, self.peer, self.manager):
            Membership.objects.create(
                user=u, organization=self.org, role=Role.ADMIN,
                role_template=tech_tpl if u is not self.manager else mgr_tpl,
                is_active=True,
            )
        # `outsider` belongs to a different org — should not appear in
        # the manager's assignable list.
        other_org = Organization.objects.create(name='Other-AL', slug='other-al')
        Membership.objects.create(
            user=self.outsider, organization=other_org, role=Role.ADMIN,
            role_template=tech_tpl, is_active=True,
        )
        self.client = Client()
        self.tech_token = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'atech', 'password': 'hunter2',
        }).json()['token']
        self.mgr_token = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'amgr', 'password': 'hunter2',
        }).json()['token']

    def test_no_assign_perm_returns_self_only(self):
        resp = _auth_get(
            self.client, '/api/mobile/v1/users/assignable/', self.tech_token,
        )
        self.assertEqual(resp.status_code, 200)
        ids = [u['id'] for u in resp.json()['results']]
        self.assertEqual(ids, [self.tech.id])

    def test_with_assign_perm_returns_peers_only(self):
        resp = _auth_get(
            self.client, '/api/mobile/v1/users/assignable/', self.mgr_token,
        )
        self.assertEqual(resp.status_code, 200)
        ids = set(u['id'] for u in resp.json()['results'])
        self.assertIn(self.tech.id, ids)
        self.assertIn(self.peer.id, ids)
        self.assertIn(self.manager.id, ids)
        self.assertNotIn(self.outsider.id, ids)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileAuthMePermissionsTests(TestCase):
    """v3.17.477 — /auth/me/ payload includes a `permissions` map."""

    def setUp(self):
        _clear_throttle_cache()
        from accounts.models import RoleTemplate
        self.org = Organization.objects.create(name='MePerm', slug='meperm')
        tpl = RoleTemplate.objects.create(
            name='Mgr-MePerm', is_system_template=False,
            tickets_view=True, tickets_assign=True, tickets_view_all=False,
        )
        self.user = User.objects.create_user('meuser', password='hunter2')
        Membership.objects.create(
            user=self.user, organization=self.org, role=Role.OWNER,
            role_template=tpl, is_active=True,
        )
        self.client = Client()
        self.token = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'meuser', 'password': 'hunter2',
        }).json()['token']

    def test_me_returns_permissions_map(self):
        resp = _auth_get(self.client, '/api/mobile/v1/auth/me/', self.token)
        self.assertEqual(resp.status_code, 200)
        perms = resp.json()['user']['permissions']
        self.assertTrue(perms['tickets_assign'])
        self.assertFalse(perms['tickets_view_all'])
        self.assertIn('tickets_create', perms)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileDashboardNewTicketsCountTests(TestCase):
    """v3.17.477 — dashboard payload now exposes `new_tickets`."""

    def setUp(self):
        _clear_throttle_cache()
        from psa.models import Ticket
        self.org = Organization.objects.create(name='DashNT', slug='dashnt')
        self.user = User.objects.create_user('dashntuser', password='hunter2')
        Membership.objects.create(
            user=self.user, organization=self.org, role=Role.OWNER, is_active=True,
        )
        status_new, _p1, p3, ttype, queue = _seed_psa_baseline()
        # Two tickets in `new`, one in a different open status.
        Ticket.objects.create(
            organization=self.org, subject='New A',
            status=status_new, priority=p3, ticket_type=ttype, queue=queue,
        )
        Ticket.objects.create(
            organization=self.org, subject='New B',
            status=status_new, priority=p3, ticket_type=ttype, queue=queue,
        )
        from psa.models import TicketStatus
        in_progress = TicketStatus.objects.create(
            name='In Progress', slug='in-progress', sort_order=2,
        )
        Ticket.objects.create(
            organization=self.org, subject='Active',
            status=in_progress, priority=p3, ticket_type=ttype, queue=queue,
        )
        self.client = Client()
        self.token = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'dashntuser', 'password': 'hunter2',
        }).json()['token']

    def test_dashboard_includes_new_tickets_count(self):
        resp = _auth_get(self.client, '/api/mobile/v1/dashboard/', self.token)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['new_tickets'], 2)
        self.assertEqual(body['open_tickets'], 3)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileVehiclesFleetWideTests(TestCase):
    """v3.17.477 — /vehicles/ now returns every active vehicle for any
    authenticated user (the fleet isn't multi-tenant)."""

    def setUp(self):
        _clear_throttle_cache()
        from vehicles.models import ServiceVehicle
        self.org = Organization.objects.create(name='FleetOrg', slug='fleetorg')
        self.user = User.objects.create_user('fleetuser', password='hunter2')
        Membership.objects.create(
            user=self.user, organization=self.org, role=Role.ADMIN, is_active=True,
        )
        self.v1 = ServiceVehicle.objects.create(
            name='Van 1', make='Ford', model='Transit', year=2024,
            license_plate='AAA-111', status='active',
        )
        self.v2 = ServiceVehicle.objects.create(
            name='Van 2', make='Ford', model='Transit', year=2024,
            license_plate='AAA-222', status='active',
        )
        self.retired = ServiceVehicle.objects.create(
            name='Old Van', make='Ford', model='E150', year=2008,
            license_plate='AAA-999', status='retired',
        )
        self.client = Client()
        self.token = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'fleetuser', 'password': 'hunter2',
        }).json()['token']

    def test_list_returns_active_fleet_without_assignment(self):
        resp = _auth_get(self.client, '/api/mobile/v1/vehicles/', self.token)
        self.assertEqual(resp.status_code, 200)
        ids = {v['id'] for v in resp.json()['results']}
        self.assertIn(self.v1.id, ids)
        self.assertIn(self.v2.id, ids)
        self.assertNotIn(self.retired.id, ids)

    def test_detail_accessible_without_assignment(self):
        resp = _auth_get(
            self.client, f'/api/mobile/v1/vehicles/{self.v1.id}/', self.token,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['license_plate'], 'AAA-111')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileTicketSerializerFieldsTests(TestCase):
    """v3.17.477 — serialized tickets expose `organization_name`,
    `assigned_to_name`, `number`, and `updated_at`."""

    def setUp(self):
        _clear_throttle_cache()
        from psa.models import Ticket
        self.org = Organization.objects.create(name='Serializer Org', slug='ser-org')
        self.user = User.objects.create_user(
            'seruser', password='hunter2',
            first_name='Sara', last_name='Reuser',
        )
        Membership.objects.create(
            user=self.user, organization=self.org, role=Role.OWNER, is_active=True,
        )
        status_new, _p1, p3, ttype, queue = _seed_psa_baseline()
        self.t = Ticket.objects.create(
            organization=self.org, subject='Serialize me',
            status=status_new, priority=p3, ticket_type=ttype, queue=queue,
            assigned_to=self.user,
        )
        self.client = Client()
        self.token = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'seruser', 'password': 'hunter2',
        }).json()['token']

    def test_list_row_includes_extended_fields(self):
        resp = _auth_get(self.client, '/api/mobile/v1/tickets/', self.token)
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()['results']
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['organization_name'], 'Serializer Org')
        self.assertEqual(row['assigned_to_name'], 'Sara Reuser')
        self.assertIsNotNone(row['updated_at'])
        # `number` should be a copy of ticket_number.
        self.assertEqual(row['number'], row['ticket_number'])


# === v3.17.478 follow-up tests ====================================
# Calendar + upcoming endpoints now mix scheduled tasks and tickets.


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileDispatchCalendarMixedTests(TestCase):
    """v3.17.478 — `/dispatch/calendar/` includes both tasks and tickets;
    `/dispatch/upcoming/` returns N day buckets mixing both."""

    def setUp(self):
        from datetime import datetime, time as dtime, timedelta, timezone as stdlib_tz
        from django.utils import timezone
        from psa.models import Ticket
        from scheduling.models import ScheduledTask, TaskAssignment
        _clear_throttle_cache()
        self.org = Organization.objects.create(name='CalMixOrg', slug='calmix')
        self.user = User.objects.create_user('caluser', password='hunter2')
        Membership.objects.create(
            user=self.user, organization=self.org, role=Role.OWNER, is_active=True,
        )
        today = timezone.localdate()
        # A task due today.
        task_today = ScheduledTask.objects.create(
            organization=self.org, title='Patch firewall',
            description='', priority='high', status='pending',
            due_date=datetime.combine(today, dtime(9, 0), tzinfo=stdlib_tz.utc),
        )
        TaskAssignment.objects.create(
            task=task_today, user=self.user,
        )
        # A ticket due tomorrow.
        status_new, _p1, p3, ttype, queue = _seed_psa_baseline()
        tomorrow = today + timedelta(days=1)
        self.ticket = Ticket.objects.create(
            organization=self.org, subject='Onsite visit',
            status=status_new, priority=p3, ticket_type=ttype, queue=queue,
            assigned_to=self.user,
            resolution_due_at=datetime.combine(tomorrow, dtime(14, 0),
                                               tzinfo=stdlib_tz.utc),
        )
        self.today_iso = today.isoformat()
        self.tomorrow_iso = tomorrow.isoformat()
        self.month_str = today.strftime('%Y-%m')
        self.client = Client()
        self.token = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'caluser', 'password': 'hunter2',
        }).json()['token']

    def test_calendar_includes_tasks_and_tickets(self):
        resp = _auth_get(
            self.client,
            f'/api/mobile/v1/dispatch/calendar/?month={self.month_str}',
            self.token,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        days = resp.json()['days']
        # Today's bucket has the task; tomorrow's has the ticket — but
        # only if both fall in the same month (cross-month tomorrow is
        # skipped from this assertion).
        today_items = days.get(self.today_iso, [])
        self.assertTrue(any(it.get('kind') == 'task' for it in today_items),
                        f'expected a task entry for {self.today_iso}, got {today_items}')
        if self.tomorrow_iso[:7] == self.month_str:
            tom_items = days.get(self.tomorrow_iso, [])
            self.assertTrue(
                any(it.get('kind') == 'ticket' for it in tom_items),
                f'expected a ticket entry for {self.tomorrow_iso}, got {tom_items}',
            )

    def test_upcoming_returns_seven_day_window_mixed(self):
        resp = _auth_get(
            self.client, '/api/mobile/v1/dispatch/upcoming/', self.token,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body['today'], self.today_iso)
        self.assertEqual(len(body['days']), 7)
        # Day 0 = today should contain the task.
        day0 = body['days'][0]
        self.assertEqual(day0['date'], self.today_iso)
        self.assertTrue(any(it.get('kind') == 'task' for it in day0['items']))
        # Day 1 = tomorrow should contain the ticket.
        day1 = body['days'][1]
        self.assertEqual(day1['date'], self.tomorrow_iso)
        self.assertTrue(any(it.get('kind') == 'ticket' for it in day1['items']))

    def test_upcoming_clamps_days_param(self):
        resp = _auth_get(
            self.client, '/api/mobile/v1/dispatch/upcoming/?days=999', self.token,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()['days']), 14)


# === v3.17.479 follow-up tests ====================================
# Vault create / edit / rotate, ticket billing rollup, schedule-on-day.


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileVaultEditTests(TestCase):
    """v3.17.479 — POST /vault/ + PATCH /vault/<id>/ gated on perms."""

    def setUp(self):
        from accounts.models import RoleTemplate
        from vault.models import Password
        from vault.encryption_v2 import encrypt_password
        _clear_throttle_cache()
        self.org = Organization.objects.create(name='VaultEditOrg', slug='vedit')
        # Two users: one with vault_create + vault_edit, one with neither.
        tpl_full = RoleTemplate.objects.create(
            name='Vault-Full', is_system_template=False,
            vault_view=True, vault_create=True, vault_edit=True,
        )
        tpl_view = RoleTemplate.objects.create(
            name='Vault-View', is_system_template=False,
            vault_view=True, vault_create=False, vault_edit=False,
        )
        self.editor = User.objects.create_user('veditor', password='hunter2')
        self.viewer = User.objects.create_user('vviewer', password='hunter2')
        Membership.objects.create(
            user=self.editor, organization=self.org, role=Role.ADMIN,
            role_template=tpl_full, is_active=True,
        )
        Membership.objects.create(
            user=self.viewer, organization=self.org, role=Role.READONLY,
            role_template=tpl_view, is_active=True,
        )
        self.entry = Password.objects.create(
            organization=self.org, title='Router',
            encrypted_password=encrypt_password('s3cret', org_id=self.org.id),
        )
        self.client = Client()
        self.editor_tok = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'veditor', 'password': 'hunter2',
        }).json()['token']
        self.viewer_tok = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'vviewer', 'password': 'hunter2',
        }).json()['token']

    def test_create_with_perm_201(self):
        resp = _auth_post(
            self.client, '/api/mobile/v1/vault/', self.editor_tok,
            {
                'organization_id': self.org.id,
                'title': 'New API key',
                'password': 'super-secret',
                'category': 'api_key',
                'username': 'admin',
            },
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['title'], 'New API key')
        self.assertEqual(body['username'], 'admin')
        self.assertEqual(body['category'], 'api_key')

    def test_create_without_perm_403(self):
        resp = _auth_post(
            self.client, '/api/mobile/v1/vault/', self.viewer_tok,
            {
                'organization_id': self.org.id,
                'title': 'Bad attempt',
                'password': 'noway',
            },
        )
        self.assertEqual(resp.status_code, 403)

    def test_create_requires_password_field(self):
        resp = _auth_post(
            self.client, '/api/mobile/v1/vault/', self.editor_tok,
            {
                'organization_id': self.org.id,
                'title': 'No secret',
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_patch_updates_fields_with_perm(self):
        resp = self.client.patch(
            f'/api/mobile/v1/vault/{self.entry.id}/',
            data=json.dumps({'title': 'Renamed Router', 'username': 'admin2'}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Token {self.editor_tok}',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['title'], 'Renamed Router')
        self.assertEqual(resp.json()['username'], 'admin2')

    def test_patch_without_perm_403(self):
        resp = self.client.patch(
            f'/api/mobile/v1/vault/{self.entry.id}/',
            data=json.dumps({'title': 'No way'}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Token {self.viewer_tok}',
        )
        self.assertEqual(resp.status_code, 403)

    def test_rotate_password_changes_ciphertext(self):
        from vault.models import Password
        orig_cipher = self.entry.encrypted_password
        resp = self.client.patch(
            f'/api/mobile/v1/vault/{self.entry.id}/',
            data=json.dumps({'password': 'rotated-plaintext'}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Token {self.editor_tok}',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        fresh = Password.objects.get(pk=self.entry.id)
        self.assertNotEqual(fresh.encrypted_password, orig_cipher)
        # Round-trip: the new ciphertext should decrypt to the new plaintext.
        self.assertEqual(fresh.get_password(), 'rotated-plaintext')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileTicketBillingRollupTests(TestCase):
    """v3.17.479 — ticket detail returns total/billable/non-billable plus
    contract block status when applicable."""

    def setUp(self):
        from datetime import date as _d, timedelta, datetime as _dt
        from django.utils import timezone
        from psa.models import (
            Ticket, TicketTimeEntry, Contract,
        )
        _clear_throttle_cache()
        self.org = Organization.objects.create(name='BillOrg', slug='billorg')
        self.user = User.objects.create_user('billuser', password='hunter2')
        Membership.objects.create(
            user=self.user, organization=self.org, role=Role.OWNER, is_active=True,
        )
        status_new, _p1, p3, ttype, queue = _seed_psa_baseline()
        self.ticket = Ticket.objects.create(
            organization=self.org, subject='Billable work',
            status=status_new, priority=p3, ticket_type=ttype, queue=queue,
        )
        # Active block-hours contract — must exist BEFORE time entries so
        # the TicketTimeEntry.save() post-hook can deduct via Contract.for_ticket().
        Contract.objects.create(
            organization=self.org, client_org=self.org, name='Test Block',
            contract_type='block_hours', status='active',
            start_date=_d.today() - timedelta(days=30),
            total_hours=5,
        )
        # Two billable entries (45m + 30m) and one non-billable (15m).
        now = timezone.now()
        TicketTimeEntry.objects.create(
            ticket=self.ticket, user=self.user,
            started_at=now - timedelta(minutes=45),
            ended_at=now,
            duration_minutes=45, is_billable=True,
        )
        TicketTimeEntry.objects.create(
            ticket=self.ticket, user=self.user,
            started_at=now - timedelta(minutes=30),
            ended_at=now,
            duration_minutes=30, is_billable=True,
        )
        TicketTimeEntry.objects.create(
            ticket=self.ticket, user=self.user,
            started_at=now - timedelta(minutes=15),
            ended_at=now,
            duration_minutes=15, is_billable=False,
        )
        self.client = Client()
        self.token = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'billuser', 'password': 'hunter2',
        }).json()['token']

    def test_detail_includes_rollup_and_contract(self):
        resp = _auth_get(
            self.client, f'/api/mobile/v1/tickets/{self.ticket.id}/', self.token,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body['total_minutes'], 90)
        self.assertEqual(body['billable_minutes'], 75)
        self.assertEqual(body['non_billable_minutes'], 15)
        c = body['contract']
        self.assertIsNotNone(c)
        self.assertEqual(c['type'], 'block_hours')
        # 5h allowance = 300 minutes.
        self.assertEqual(c['total_minutes'], 300)
        # All three entries (45 + 30 + 15) auto-deducted via the post_save
        # hook. Note: Contract.hours_used_minutes does NOT filter on
        # is_billable today — every TicketTimeEntry consumes the bucket.
        self.assertEqual(c['used_minutes'], 90)
        self.assertEqual(c['remaining_minutes'], 210)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileScheduleTaskTests(TestCase):
    """v3.17.479 — POST /dispatch/tasks/ creates a ScheduledTask + assigns
    the caller; PATCH /tickets/<id>/ accepts resolution_due_at."""

    def setUp(self):
        _clear_throttle_cache()
        self.org = Organization.objects.create(name='SchOrg', slug='schorg')
        self.user = User.objects.create_user('schuser', password='hunter2')
        Membership.objects.create(
            user=self.user, organization=self.org, role=Role.OWNER, is_active=True,
        )
        self.client = Client()
        self.token = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'schuser', 'password': 'hunter2',
        }).json()['token']

    def test_create_scheduled_task_attaches_caller(self):
        from scheduling.models import ScheduledTask, TaskAssignment
        resp = _auth_post(
            self.client, '/api/mobile/v1/dispatch/tasks/', self.token,
            {
                'organization_id': self.org.id,
                'title': 'Patch the firewall',
                'due_at': '2026-06-15T09:00:00',
                'priority': 'high',
            },
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['kind'], 'task')
        self.assertEqual(body['task_title'], 'Patch the firewall')
        self.assertEqual(body['task_priority'], 'high')
        # Server actually created the row + assignment.
        task = ScheduledTask.objects.get(title='Patch the firewall')
        self.assertTrue(
            TaskAssignment.objects.filter(task=task, user=self.user).exists()
        )

    def test_create_scheduled_task_blocks_cross_org(self):
        other = Organization.objects.create(name='OtherSchOrg', slug='otherorg')
        resp = _auth_post(
            self.client, '/api/mobile/v1/dispatch/tasks/', self.token,
            {
                'organization_id': other.id,
                'title': 'Should fail',
                'due_at': '2026-06-15T09:00:00',
            },
        )
        self.assertEqual(resp.status_code, 403)

    def test_patch_ticket_due_date(self):
        from psa.models import Ticket
        status_new, _p1, p3, ttype, queue = _seed_psa_baseline()
        t = Ticket.objects.create(
            organization=self.org, subject='Schedule me',
            status=status_new, priority=p3, ticket_type=ttype, queue=queue,
        )
        resp = self.client.patch(
            f'/api/mobile/v1/tickets/{t.id}/',
            data=json.dumps({'resolution_due_at': '2026-06-20T14:00:00'}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Token {self.token}',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        t.refresh_from_db()
        self.assertIsNotNone(t.resolution_due_at)
        self.assertEqual(t.resolution_due_at.year, 2026)
        self.assertEqual(t.resolution_due_at.month, 6)
        self.assertEqual(t.resolution_due_at.day, 20)


# === v3.17.480 follow-up tests ====================================
# Asset PATCH + asset ↔ vault link/unlink endpoints.


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileAssetEditTests(TestCase):
    """v3.17.480 — PATCH /assets/<id>/ honors the whitelist + assets_edit gate."""

    def setUp(self):
        from accounts.models import RoleTemplate
        from assets.models import Asset
        _clear_throttle_cache()
        self.org = Organization.objects.create(name='AsetEdit', slug='aedit')
        tpl_edit = RoleTemplate.objects.create(
            name='Asset-Edit', is_system_template=False,
            assets_view=True, assets_create=True, assets_edit=True,
        )
        tpl_view = RoleTemplate.objects.create(
            name='Asset-View', is_system_template=False,
            assets_view=True, assets_edit=False,
        )
        self.editor = User.objects.create_user('aeditor', password='hunter2')
        self.viewer = User.objects.create_user('aviewer', password='hunter2')
        Membership.objects.create(
            user=self.editor, organization=self.org, role=Role.ADMIN,
            role_template=tpl_edit, is_active=True,
        )
        Membership.objects.create(
            user=self.viewer, organization=self.org, role=Role.READONLY,
            role_template=tpl_view, is_active=True,
        )
        self.asset = Asset.objects.create(
            organization=self.org, name='ServerEdit',
            hostname='old.local', asset_type='server',
        )
        self.client = Client()
        self.editor_tok = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'aeditor', 'password': 'hunter2',
        }).json()['token']
        self.viewer_tok = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'aviewer', 'password': 'hunter2',
        }).json()['token']

    def _patch(self, token, body):
        return self.client.patch(
            f'/api/mobile/v1/assets/{self.asset.id}/',
            data=json.dumps(body), content_type='application/json',
            HTTP_AUTHORIZATION=f'Token {token}',
        )

    def test_patch_updates_whitelisted_fields(self):
        resp = self._patch(self.editor_tok, {
            'hostname': 'new.local',
            'notes': 'Renamed via mobile',
            'os_name': 'Ubuntu',
        })
        self.assertEqual(resp.status_code, 200, resp.content)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.hostname, 'new.local')
        self.assertEqual(self.asset.notes, 'Renamed via mobile')
        self.assertEqual(self.asset.os_name, 'Ubuntu')

    def test_patch_blocks_organization_change(self):
        other = Organization.objects.create(name='Other', slug='aother')
        resp = self._patch(self.editor_tok, {'organization_id': other.id})
        self.assertEqual(resp.status_code, 400)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.organization_id, self.org.id)

    def test_patch_without_perm_403(self):
        resp = self._patch(self.viewer_tok, {'hostname': 'should-fail'})
        self.assertEqual(resp.status_code, 403)

    def test_patch_blank_name_rejected(self):
        resp = self._patch(self.editor_tok, {'name': '   '})
        self.assertEqual(resp.status_code, 400)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileAssetVaultLinkTests(TestCase):
    """v3.17.480 — POST/DELETE /assets/<id>/vault-links/ creates and
    removes PasswordRelation rows; cross-org link is rejected."""

    def setUp(self):
        from accounts.models import RoleTemplate
        from assets.models import Asset
        from vault.models import Password, PasswordRelation
        from vault.encryption_v2 import encrypt_password
        _clear_throttle_cache()
        self.org = Organization.objects.create(name='AVL-A', slug='avla')
        self.other_org = Organization.objects.create(name='AVL-B', slug='avlb')
        tpl = RoleTemplate.objects.create(
            name='AVL-Full', is_system_template=False,
            assets_view=True, assets_edit=True, vault_view=True,
        )
        self.user = User.objects.create_user('avluser', password='hunter2')
        Membership.objects.create(
            user=self.user, organization=self.org, role=Role.ADMIN,
            role_template=tpl, is_active=True,
        )
        Membership.objects.create(
            user=self.user, organization=self.other_org, role=Role.ADMIN,
            role_template=tpl, is_active=True,
        )
        self.asset = Asset.objects.create(
            organization=self.org, name='AVL-host', hostname='avl.local',
        )
        self.password_same_org = Password.objects.create(
            organization=self.org, title='Same-org secret',
            encrypted_password=encrypt_password('shh', org_id=self.org.id),
        )
        self.password_other_org = Password.objects.create(
            organization=self.other_org, title='Other-org secret',
            encrypted_password=encrypt_password('shh', org_id=self.other_org.id),
        )
        self.client = Client()
        self.token = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'avluser', 'password': 'hunter2',
        }).json()['token']
        self.PasswordRelation = PasswordRelation

    def test_link_same_org_creates_relation(self):
        resp = _auth_post(
            self.client, f'/api/mobile/v1/assets/{self.asset.id}/vault-links/',
            self.token, {'password_id': self.password_same_org.id},
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertTrue(
            self.PasswordRelation.objects.filter(
                password=self.password_same_org,
                relation_type='asset', relation_id=self.asset.id,
            ).exists()
        )

    def test_link_cross_org_rejected(self):
        resp = _auth_post(
            self.client, f'/api/mobile/v1/assets/{self.asset.id}/vault-links/',
            self.token, {'password_id': self.password_other_org.id},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(
            self.PasswordRelation.objects.filter(
                password=self.password_other_org,
                relation_type='asset', relation_id=self.asset.id,
            ).exists()
        )

    def test_link_then_unlink(self):
        self.PasswordRelation.objects.create(
            password=self.password_same_org,
            relation_type='asset', relation_id=self.asset.id,
        )
        resp = self.client.delete(
            f'/api/mobile/v1/assets/{self.asset.id}/vault-links/'
            f'?password_id={self.password_same_org.id}',
            HTTP_AUTHORIZATION=f'Token {self.token}',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(
            self.PasswordRelation.objects.filter(
                password=self.password_same_org,
                relation_type='asset', relation_id=self.asset.id,
            ).exists()
        )

    def test_link_without_perm_403(self):
        from accounts.models import RoleTemplate
        viewer_tpl = RoleTemplate.objects.create(
            name='AVL-View', is_system_template=False,
            assets_view=True, assets_edit=False,
        )
        viewer = User.objects.create_user('avlviewer', password='hunter2')
        Membership.objects.create(
            user=viewer, organization=self.org, role=Role.READONLY,
            role_template=viewer_tpl, is_active=True,
        )
        tok = _post(self.client, '/api/mobile/v1/auth/login/', {
            'username': 'avlviewer', 'password': 'hunter2',
        }).json()['token']
        resp = _auth_post(
            self.client, f'/api/mobile/v1/assets/{self.asset.id}/vault-links/',
            tok, {'password_id': self.password_same_org.id},
        )
        self.assertEqual(resp.status_code, 403)
