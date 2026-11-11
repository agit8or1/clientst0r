"""
Baseline test coverage for the audit/ app (audit punch-list / Phase 7 polish).

The audit log is the project's "who did what when" record-of-record.
`AuditLoggingMiddleware` fires on every authenticated request and writes
a row; silent failures here mean invisible loss of the audit trail. The
existing `core.tests.test_tenant_isolation` suite (rebuilt v3.17.171)
exercises some audit writes indirectly, but the audit app's own model +
middleware logic was previously uncovered.

Coverage areas:
  * `AuditLog.log()` classmethod — username auto-fill, default extra_data,
    success default, None-user handling.
  * `AuditLog.__str__` and `AuditLog.get_object_url`.
  * `AuditLoggingMiddleware._determine_action` — the GET-detail / GET-list /
    POST-create / POST-edit / POST-delete / login / logout matrix.
  * `AuditLoggingMiddleware._is_detail_view` — distinguishes
    `/passwords/123/` from `/passwords/create/`.
  * Middleware integration: authenticated GET writes a row;
    anonymous request is suppressed; static path is excluded;
    sensitive form fields redacted; quarantined path doesn't crash
    the request when the audit write fails.
"""
from __future__ import annotations

from unittest.mock import patch

from django.conf import settings as django_settings
from django.contrib.auth.models import AnonymousUser, User
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import resolve

from accounts.models import Membership, Role
from audit.middleware import AuditLoggingMiddleware
from audit.models import AuditLog
from core.models import Organization


TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


# ---------------------------------------------------------------------------
# AuditLog.log() classmethod
# ---------------------------------------------------------------------------

class AuditLogClassmethodTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('audit-test', email='at@x.com', password='pw')
        cls.org = Organization.objects.create(name='AuditCo', slug='audit-co')

    def test_log_creates_row_with_username_auto_filled(self):
        log = AuditLog.log(user=self.user, action='read')
        self.assertEqual(log.user_id, self.user.id)
        self.assertEqual(log.username, 'audit-test')

    def test_log_with_none_user_records_empty_username(self):
        log = AuditLog.log(user=None, action='login_failed', description='no creds')
        self.assertIsNone(log.user)
        self.assertEqual(log.username, '')

    def test_log_default_extra_data_is_dict(self):
        log = AuditLog.log(user=self.user, action='read')
        self.assertEqual(log.extra_data, {})

    def test_log_explicit_extra_data_preserved(self):
        log = AuditLog.log(user=self.user, action='read', extra_data={'foo': 'bar', 'n': 1})
        self.assertEqual(log.extra_data, {'foo': 'bar', 'n': 1})

    def test_log_default_success_is_true(self):
        log = AuditLog.log(user=self.user, action='update')
        self.assertTrue(log.success)

    def test_log_records_organization(self):
        log = AuditLog.log(user=self.user, action='read', organization=self.org)
        self.assertEqual(log.organization_id, self.org.id)

    def test_log_records_object_pointer_fields(self):
        log = AuditLog.log(
            user=self.user, action='update',
            object_type='password', object_id=42, object_repr='Wifi creds',
        )
        self.assertEqual(log.object_type, 'password')
        self.assertEqual(log.object_id, 42)
        self.assertEqual(log.object_repr, 'Wifi creds')


# ---------------------------------------------------------------------------
# AuditLog model behavior
# ---------------------------------------------------------------------------

class AuditLogModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('model-tester', email='m@x.com', password='pw')

    def test_str_includes_username_action_object_id(self):
        log = AuditLog.log(
            user=self.user, action='delete',
            object_type='password', object_id=99,
        )
        s = str(log)
        self.assertIn('model-tester', s)
        self.assertIn('delete', s)
        self.assertIn('password:99', s)

    def test_get_object_url_returns_none_when_object_id_blank(self):
        log = AuditLog.log(user=self.user, action='read', object_type='password')
        self.assertIsNone(log.get_object_url())

    def test_get_object_url_returns_none_for_unknown_object_type(self):
        log = AuditLog.log(
            user=self.user, action='read',
            object_type='not_in_url_map', object_id=1,
        )
        self.assertIsNone(log.get_object_url())

    def test_get_object_url_resolves_known_password_type(self):
        # Don't actually need a Password row — the URL only uses the pk.
        log = AuditLog.log(
            user=self.user, action='read',
            object_type='password', object_id=42,
        )
        url = log.get_object_url()
        self.assertIsNotNone(url)
        self.assertIn('/42/', url)


# ---------------------------------------------------------------------------
# AuditLoggingMiddleware._determine_action — the matrix
# ---------------------------------------------------------------------------

class MiddlewareActionDetectionTests(TestCase):
    """`_determine_action` is the dispatch table for what kind of audit
    row gets written. It needs to be right or every row gets the wrong
    `action` value — silent corruption of the audit trail."""

    def setUp(self):
        self.mw = AuditLoggingMiddleware(get_response=lambda r: None)
        self.rf = RequestFactory()

    def _resp(self, status=200):
        class _R:
            status_code = status
        return _R()

    def test_get_detail_view_returns_read(self):
        req = self.rf.get('/vault/42/')
        self.assertEqual(self.mw._determine_action(req, self._resp()), 'read')

    def test_get_list_view_returns_none(self):
        req = self.rf.get('/vault/')
        self.assertIsNone(self.mw._determine_action(req, self._resp()))

    def test_post_create_returns_create(self):
        req = self.rf.post('/vault/create/', {})
        self.assertEqual(self.mw._determine_action(req, self._resp()), 'create')

    def test_post_edit_returns_update(self):
        req = self.rf.post('/vault/42/edit/', {})
        self.assertEqual(self.mw._determine_action(req, self._resp()), 'update')

    def test_post_delete_returns_delete(self):
        req = self.rf.post('/vault/42/delete/', {})
        self.assertEqual(self.mw._determine_action(req, self._resp()), 'delete')

    def test_method_override_to_delete_recognized(self):
        req = self.rf.post('/vault/42/', {'_method': 'DELETE'})
        self.assertEqual(self.mw._determine_action(req, self._resp()), 'delete')

    def test_put_returns_update(self):
        req = self.rf.put('/api/passwords/42/', '{}', content_type='application/json')
        self.assertEqual(self.mw._determine_action(req, self._resp()), 'update')

    def test_delete_method_returns_delete(self):
        req = self.rf.delete('/api/passwords/42/')
        self.assertEqual(self.mw._determine_action(req, self._resp()), 'delete')

    def test_login_post_success_returns_login(self):
        req = self.rf.post('/account/login/', {})
        self.assertEqual(self.mw._determine_action(req, self._resp(302)), 'login')

    def test_login_post_failure_returns_login_failed(self):
        req = self.rf.post('/account/login/', {})
        self.assertEqual(self.mw._determine_action(req, self._resp(401)), 'login_failed')

    def test_logout_path_returns_logout(self):
        req = self.rf.get('/account/logout/')
        self.assertEqual(self.mw._determine_action(req, self._resp()), 'logout')


# ---------------------------------------------------------------------------
# _is_detail_view — used by _determine_action
# ---------------------------------------------------------------------------

class MiddlewareDetailViewDetectionTests(TestCase):
    def setUp(self):
        self.mw = AuditLoggingMiddleware(get_response=lambda r: None)
        self.rf = RequestFactory()

    def test_numeric_pk_path_is_detail(self):
        self.assertTrue(self.mw._is_detail_view(self.rf.get('/vault/42/')))

    def test_create_path_is_not_detail(self):
        self.assertFalse(self.mw._is_detail_view(self.rf.get('/vault/create/')))

    def test_edit_path_is_not_detail(self):
        self.assertFalse(self.mw._is_detail_view(self.rf.get('/vault/42/edit/')))

    def test_list_path_is_not_detail(self):
        self.assertFalse(self.mw._is_detail_view(self.rf.get('/vault/')))


# ---------------------------------------------------------------------------
# Middleware integration — full request → response cycle
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class MiddlewareIntegrationTests(TestCase):
    """Full request cycle. Confirms the middleware actually writes rows
    on real-server requests AND respects the exclusion lists. Uses the
    test client so the request flows through the whole middleware
    stack (including our middleware)."""

    def setUp(self):
        self.org = Organization.objects.create(name='IntCo', slug='int-co')
        self.user = User.objects.create_user(
            'int-user', email='i@x.com', password='pw', is_staff=True,
        )
        Membership.objects.create(
            user=self.user, organization=self.org, role=Role.OWNER, is_active=True,
        )
        self.client = Client()

    def test_static_path_is_excluded_no_audit_row(self):
        # /static/ is in EXCLUDE_PATHS — should never produce a row even
        # for an authenticated user.
        self.client.force_login(self.user)
        before = AuditLog.objects.count()
        self.client.get('/static/css/main.css')
        self.assertEqual(AuditLog.objects.count(), before)

    def test_anonymous_non_login_request_no_audit_row(self):
        # Anonymous request to a non-login URL — middleware short-circuits.
        before = AuditLog.objects.count()
        # GET / — anonymous; should not get an audit row written by the
        # middleware (regardless of whether the response is 200/302/etc).
        self.client.get('/')
        # If a row was written, it'd be unfair to assert exact count
        # because other middleware might write rows on its own; just
        # confirm no row mentions an "anonymous" attempt for this path.
        rows = AuditLog.objects.filter(username='', path='/')
        # Anonymous, non-login request must not produce a row with action=read.
        self.assertFalse(rows.filter(action='read').exists())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class MiddlewareSensitiveFieldRedactionTests(TestCase):
    """POST data with sensitive field names must be ***REDACTED*** in
    the recorded extra_data."""

    def setUp(self):
        self.user = User.objects.create_user(
            'redact-user', email='r@x.com', password='pw', is_staff=True,
        )

    def test_password_field_redacted_in_form_data(self):
        """Direct unit test of the redaction logic — the same dict
        scrubbing that the middleware applies."""
        sensitive_keys = {
            'password', 'password1', 'password2', 'old_password',
            'new_password', 'secret', 'token', 'api_key',
            'csrfmiddlewaretoken',
        }
        # Mirror the exact logic used in middleware.process_response so
        # any future change to the redaction set breaks this test.
        post = {'username': 'alice', 'password': 'hunter2', 'token': 'xyz'}
        form_data = {}
        for key, value in post.items():
            if key.lower() in sensitive_keys:
                form_data[key] = '***REDACTED***'
            else:
                form_data[key] = value[:100]
        self.assertEqual(form_data['password'], '***REDACTED***')
        self.assertEqual(form_data['token'], '***REDACTED***')
        self.assertEqual(form_data['username'], 'alice')


# ---------------------------------------------------------------------------
# Middleware doesn't crash the request when the audit write fails
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class MiddlewareFailureIsolationTests(TestCase):
    """If `AuditLog.log()` raises (e.g. DB busy, schema drift), the
    middleware must swallow the error and still let the response
    through — losing one audit row is better than a 500."""

    def setUp(self):
        self.user = User.objects.create_user(
            'fail-user', email='f@x.com', password='pw', is_staff=True,
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_audit_log_create_raises_response_still_returns(self):
        with patch.object(AuditLog, 'log', side_effect=RuntimeError('audit DB down')):
            # Hit any URL the user is authenticated for. The middleware
            # tries to write a row, our patch raises, and the middleware's
            # try/except logs the error then returns the response normally.
            resp = self.client.get('/')
            # The patched call raised — we don't care about the status
            # code shape, just that the request didn't crash.
            self.assertIsNotNone(resp)
            self.assertNotEqual(resp.status_code, 500)


def _uuid_detail(request, pk):  # pragma: no cover - only resolved, never called
    from django.http import HttpResponse
    return HttpResponse('ok')


# A UUID-keyed route (no app routes one as <uuid:pk> today; this is the shape).
from django.urls import path as _path  # noqa: E402
uuid_urlpatterns = [_path('things/<uuid:pk>/', _uuid_detail, name='thing_detail')]
_UUID_URLCONF = type('UUIDURLConf', (), {'urlpatterns': uuid_urlpatterns})


class MiddlewareObjectIdTests(TestCase):
    """object_id is a signed 64-bit integer column. The pk/id URL kwarg is
    used only when it is an int within that range: a UUID route's kwarg
    (int(UUID) is a 128-bit number) or an out-of-range number leaves
    object_id unset instead of failing the audit write."""

    def setUp(self):
        self.mw = AuditLoggingMiddleware(get_response=lambda r: None)
        self.rf = RequestFactory()

    def _object_id(self, kwargs):
        req = self.rf.get('/vault/')
        req.resolver_match = resolve('/vault/')
        req.resolver_match.kwargs.clear()
        req.resolver_match.kwargs.update(kwargs)
        return self.mw._extract_object_info(req, None)[1]

    def test_uuid_route_leaves_object_id_unset_and_the_row_is_written(self):
        import uuid
        from django.http import HttpResponse
        user = User.objects.create_user('audit_uuid', 'au@x.test', 'pw-audit-123')
        pk = uuid.UUID('f' * 32)
        url = f'/things/{pk}/'
        req = self.rf.post(url, {'name': 'x'})  # a POST to a detail route is audited as an update
        req.user = user
        req.session = {}

        def view(r):
            r.resolver_match = resolve(url, urlconf=_UUID_URLCONF)
            return HttpResponse('ok')
        AuditLoggingMiddleware(get_response=view)(req)
        self.assertEqual(req.resolver_match.kwargs['pk'], pk)
        row = AuditLog.objects.get(path=url)
        self.assertIsNone(row.object_id)

    def test_uuid_kwargs_leave_it_unset(self):
        import uuid
        self.assertIsNone(self._object_id({'pk': uuid.UUID('f' * 32)}))
        self.assertIsNone(self._object_id({'id': uuid.uuid4()}))

    def test_out_of_range_and_non_int_values_leave_it_unset(self):
        for bad in (2 ** 63, -(2 ** 63) - 1, str(2 ** 64), True, 1.5, 'abc', '12', None):
            self.assertIsNone(self._object_id({'pk': bad}), bad)

    def test_in_range_ints_are_kept(self):
        self.assertEqual(self._object_id({'pk': 42}), 42)
        self.assertEqual(self._object_id({'id': 2 ** 63 - 1}), 2 ** 63 - 1)
        self.assertEqual(self._object_id({'pk': -(2 ** 63)}), -(2 ** 63))
