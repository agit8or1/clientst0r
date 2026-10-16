"""
v3.17.611 — mobile API tokens are hashed, per sign-in, and revocable.
"""
import importlib
from types import SimpleNamespace
import json
from datetime import timedelta
from io import StringIO

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from api_mobile.models import MobileAuthToken

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]
NO_THROTTLE_REST = dict(django_settings.REST_FRAMEWORK, DEFAULT_THROTTLE_CLASSES=[])
ME = '/api/mobile/v1/auth/me/'


def _login(client, username='tok-user', password='pw-tok-123'):
    resp = client.post('/api/mobile/v1/auth/login/',
                       data=json.dumps({'username': username, 'password': password}),
                       content_type='application/json')
    assert resp.status_code == 200, resp.content
    return resp.json()['token']


def _get(token, path=ME):
    return Client().get(path, HTTP_AUTHORIZATION=f'Token {token}')


def _post(token, path):
    return Client().post(path, data='', content_type='application/json',
                         HTTP_AUTHORIZATION=f'Token {token}')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   REST_FRAMEWORK=NO_THROTTLE_REST)
class MobileTokenStorageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('tok-user', password='pw-tok-123')

    def test_db_never_holds_raw_token(self):
        token = _login(Client())
        with connection.cursor() as cur:
            cur.execute('SELECT * FROM api_mobile_auth_tokens')
            rows = cur.fetchall()
        self.assertEqual(len(rows), 1)
        for value in rows[0]:
            self.assertNotEqual(str(value), token)
            if isinstance(value, str):
                self.assertNotIn(token, value)
        row = MobileAuthToken.objects.get()
        self.assertEqual(row.key_hash, MobileAuthToken.hash(token))
        self.assertEqual(row.key_prefix, token[:8])

    def test_each_login_gets_own_token_and_logout_revokes_only_that_one(self):
        phone = _login(Client())
        tablet = _login(Client())
        self.assertNotEqual(phone, tablet)
        self.assertEqual(_get(phone).status_code, 200)
        self.assertEqual(_post(phone, '/api/mobile/v1/auth/logout/').status_code, 200)
        self.assertEqual(_get(phone).status_code, 401)
        self.assertEqual(_get(tablet).status_code, 200)

    def test_revoked_expired_and_inactive_rejected(self):
        raw, row = MobileAuthToken.issue(self.user)
        self.assertEqual(_get(raw).status_code, 200)
        row.expires_at = timezone.now() - timedelta(seconds=1)
        row.save()
        self.assertEqual(_get(raw).status_code, 401)
        row.expires_at = None
        row.save()
        self.user.is_active = False
        self.user.save()
        self.assertEqual(_get(raw).status_code, 401)
        self.user.is_active = True
        self.user.save()
        self.assertEqual(_get(raw).status_code, 200)
        row.revoke()
        self.assertEqual(_get(raw).status_code, 401)

    def test_unknown_and_malformed_rejected(self):
        self.assertEqual(_get('nope').status_code, 401)
        r = Client().get(ME, HTTP_AUTHORIZATION='Token a b')
        self.assertEqual(r.status_code, 401)

    def test_last_used_bumped(self):
        raw, row = MobileAuthToken.issue(self.user)
        _get(raw)
        row.refresh_from_db()
        self.assertIsNotNone(row.last_used_at)

    def test_sessions_and_revoke_all_endpoint(self):
        a = _login(Client())
        b = _login(Client())
        resp = _get(a, '/api/mobile/v1/auth/sessions/')
        self.assertEqual(resp.status_code, 200)
        sessions = resp.json()['sessions']
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sum(1 for s in sessions if s['current']), 1)
        self.assertNotIn(a, json.dumps(sessions))
        resp = _post(a, '/api/mobile/v1/auth/revoke-all/')
        self.assertEqual(resp.json()['revoked'], 2)
        self.assertEqual(_get(a).status_code, 401)
        self.assertEqual(_get(b).status_code, 401)

    def test_refresh_rotates_hash(self):
        old = _login(Client())
        resp = _post(old, '/api/mobile/v1/auth/refresh/')
        new = resp.json()['token']
        self.assertEqual(_get(old).status_code, 401)
        self.assertEqual(_get(new).status_code, 200)
        self.assertFalse(MobileAuthToken.objects.filter(key_hash=new).exists())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class WebRevokeMobileSessionsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('web-user', password='pw')
        self.other = User.objects.create_user('other-user', password='pw')
        self.admin = User.objects.create_superuser('root-user', password='pw')

    def test_user_revokes_own_sessions(self):
        raw, _row = MobileAuthToken.issue(self.user)
        c = Client()
        c.force_login(self.user)
        page = c.get('/accounts/profile/')
        self.assertContains(page, 'Sign out all mobile sessions')
        resp = c.post('/accounts/profile/mobile-sessions/revoke/')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(_get(raw).status_code, 401)

    def test_admin_revokes_another_users_sessions(self):
        raw, _row = MobileAuthToken.issue(self.other)
        mine, _ = MobileAuthToken.issue(self.admin)
        c = Client()
        c.force_login(self.admin)
        resp = c.post(f'/accounts/users/{self.other.pk}/mobile-sessions/revoke/')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(_get(raw).status_code, 401)
        self.assertEqual(_get(mine).status_code, 200)
        from audit.models import AuditLog
        self.assertTrue(AuditLog.objects.filter(
            user=self.admin, object_id=self.other.pk,
            extra_data__op='revoke_all_mobile_sessions').exists())

    def test_non_admin_cannot_revoke_others(self):
        raw, _row = MobileAuthToken.issue(self.other)
        c = Client()
        c.force_login(self.user)
        c.post(f'/accounts/users/{self.other.pk}/mobile-sessions/revoke/')
        self.assertEqual(_get(raw).status_code, 200)

    def test_get_not_allowed(self):
        c = Client()
        c.force_login(self.user)
        self.assertEqual(c.get('/accounts/profile/mobile-sessions/revoke/').status_code, 405)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class LegacyAuthtokenMigrationTests(TestCase):
    """api_mobile 0001/0002: raw DRF tokens become hashes; apps stay signed in."""

    def setUp(self):
        self.user = User.objects.create_user('legacy-user', password='pw')

    def _run(self, module, func):
        from django.apps import apps
        mod = importlib.import_module(module)
        getattr(mod, func)(apps, SimpleNamespace(connection=connection))

    def test_existing_token_keeps_working_and_raw_row_removed(self):
        from rest_framework.authtoken.models import Token
        legacy = Token.objects.create(user=self.user)
        raw_key = legacy.key
        self.assertEqual(_get(raw_key).status_code, 401)  # not readable before migrating

        self._run('api_mobile.migrations.0001_initial', 'copy_authtokens')
        self.assertEqual(_get(raw_key).status_code, 200)
        row = MobileAuthToken.lookup(raw_key)
        self.assertNotEqual(row.key_hash, raw_key)

        out = StringIO()
        with self.assertRaises(SystemExit):
            call_command('check_secrets_storage', stdout=out)
        self.assertIn('authtoken.Token', out.getvalue())

        self._run('api_mobile.migrations.0002_delete_raw_authtokens', 'delete_raw')
        self.assertFalse(Token.objects.exists())
        self.assertEqual(_get(raw_key).status_code, 200)
        # idempotent
        self._run('api_mobile.migrations.0001_initial', 'copy_authtokens')
        self.assertEqual(MobileAuthToken.objects.count(), 1)
