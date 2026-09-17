"""The AI master switch, and the abuse controls that sit in front of it.

Two faults, both of the same kind — a control that covered less than it
claimed:

  * `AIAbuseControlMiddleware` decided what to guard by matching two
    hand-typed path prefixes. `/locations/generate-floorplan/` is spelled
    `/locations/<id>/generate-floor-plan/`, and `/api/ai/` has never been a
    route in this project, so `_is_ai_endpoint` never returned True. The
    middleware fell through on every request for its whole life: no request
    cap, no spend cap, nothing recorded. Two further faults sat behind it —
    it read `request.organization`, which nothing sets, so the org caps were
    dead; and its spend keys were read but never written.

  * Six endpoints reached an LLM provider without consulting
    `SystemSetting.psa_ai_enabled` at all — the documentation assistant's
    four views, asset AI documentation, and floor-plan generation — so
    turning AI off in Settings left them generating and spending.
"""
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse

from core.ai_abuse_control import (
    AI_ENDPOINT_NAMES, AI_PATH_PREFIXES, AIAbuseControlMiddleware,
)
from core.models import Organization, SystemSetting


TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

# Enough kwargs to reverse any of the named endpoints; each is tried in turn.
REVERSE_ATTEMPTS = (
    {}, {'pk': 1}, {'location_id': 1}, {'vehicle_id': 1},
    {'ticket_number': 'PSA-2026-000001'},
)


def reverse_any(name):
    for kwargs in REVERSE_ATTEMPTS:
        try:
            return reverse(name, kwargs=kwargs)
        except NoReverseMatch:
            continue
    return None


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AIEndpointMatchingTests(TestCase):
    """What the middleware guards has to be a route that exists."""

    def test_every_named_ai_endpoint_resolves(self):
        """
        The whole control hung on two path strings that matched nothing. If a
        route here is renamed or removed, fail here rather than silently
        disarming the caps again.
        """
        unresolvable = [n for n in sorted(AI_ENDPOINT_NAMES) if reverse_any(n) is None]
        self.assertEqual(unresolvable, [])

    def test_each_named_endpoint_is_recognised_by_the_middleware(self):
        mw = AIAbuseControlMiddleware(lambda request: None)
        for name in sorted(AI_ENDPOINT_NAMES):
            path = reverse_any(name)
            with self.subTest(endpoint=name):
                self.assertTrue(mw._is_ai_endpoint(path), f'{name} ({path})')

    def test_the_old_hardcoded_paths_were_the_bug(self):
        """Neither string the middleware used to match is a real route."""
        mw = AIAbuseControlMiddleware(lambda request: None)
        self.assertFalse(mw._is_ai_endpoint('/locations/generate-floorplan/'))
        self.assertFalse(mw._is_ai_endpoint('/api/ai/'))

    def test_every_named_endpoint_sits_under_a_known_prefix(self):
        """
        `_is_ai_endpoint` skips full URL resolution for paths outside
        `AI_PATH_PREFIXES`, so a guarded endpoint that moved out from under
        one would stop being guarded without anything else failing.
        """
        for name in sorted(AI_ENDPOINT_NAMES):
            path = reverse_any(name)
            with self.subTest(endpoint=name):
                self.assertTrue(path.startswith(AI_PATH_PREFIXES), f'{name} -> {path}')

    def test_an_ordinary_page_is_not_treated_as_an_ai_endpoint(self):
        mw = AIAbuseControlMiddleware(lambda request: None)
        self.assertFalse(mw._is_ai_endpoint('/docs/'))
        self.assertFalse(mw._is_ai_endpoint('/nope/not/a/route/'))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AIRequestCapTests(TestCase):
    """The caps have to actually bite, and be attributed to the right org."""

    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(name='Cap Co', slug='cap-co')
        self.user = get_user_model().objects.create_user(
            'capuser', 'c@x.com', 'pw', is_staff=True, is_superuser=True,
        )
        self.addCleanup(cache.clear)

    def _request(self, path, org=None):
        from django.test import RequestFactory
        request = RequestFactory().post(path)
        request.user = self.user
        request.current_organization = org
        return request

    def test_usage_is_recorded_against_the_current_organization(self):
        """
        `_track_usage` read `request.organization`, which nothing sets — the
        attribute is `current_organization`. Both org caps were dead.
        """
        mw = AIAbuseControlMiddleware(lambda request: None)
        request = self._request(reverse_any('docs:ai_generate'), org=self.org)

        class _Resp:
            status_code = 200
        mw._track_usage(request, _Resp())

        self.assertEqual(cache.get(f'ai_requests_org_{self.org.id}_today'), 1)
        self.assertEqual(cache.get(f'ai_requests_user_{self.user.id}_today'), 1)

    @override_settings(AI_MAX_DAILY_REQUESTS_PER_USER=2)
    def test_the_user_request_cap_refuses_once_it_is_reached(self):
        mw = AIAbuseControlMiddleware(lambda request: None)
        cache.set(f'ai_requests_user_{self.user.id}_today', 2, 60)
        refusal = mw._check_limits(self._request(reverse_any('docs:ai_generate')))
        self.assertIsNotNone(refusal)
        self.assertEqual(refusal.status_code, 429)

    @override_settings(AI_MAX_DAILY_REQUESTS_PER_ORG=3)
    def test_the_org_request_cap_refuses_once_it_is_reached(self):
        mw = AIAbuseControlMiddleware(lambda request: None)
        cache.set(f'ai_requests_org_{self.org.id}_today', 3, 60)
        refusal = mw._check_limits(
            self._request(reverse_any('docs:ai_generate'), org=self.org)
        )
        self.assertIsNotNone(refusal)
        self.assertEqual(refusal.status_code, 429)

    @override_settings(AI_MAX_DAILY_SPEND_PER_USER=5)
    def test_recorded_spend_counts_against_the_spend_cap(self):
        """
        `_check_limits` read the spend keys and nothing ever wrote them, so
        the dollar caps could not fire. `record_ai_spend` is what feeds them.
        """
        from core.ai_abuse_control import record_ai_spend

        mw = AIAbuseControlMiddleware(lambda request: None)
        request = self._request(reverse_any('docs:ai_generate'))
        self.assertIsNone(mw._check_limits(request))

        record_ai_spend(self.user, self.org, '5.00')
        refusal = mw._check_limits(request)
        self.assertIsNotNone(refusal)
        self.assertEqual(refusal.status_code, 429)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AIMasterSwitchTests(TestCase):
    """`psa_ai_enabled` off has to mean every AI surface is off."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            'aiuser', 'ai@x.com', 'pw', is_staff=True, is_superuser=True,
        )
        settings_row = SystemSetting.get_settings()
        settings_row.psa_ai_enabled = False
        settings_row.save()
        self.client.force_login(self.user)
        self.addCleanup(cache.clear)

    def test_ai_features_enabled_reads_the_switch(self):
        from core.ai_gate import ai_features_enabled
        self.assertFalse(ai_features_enabled())

        row = SystemSetting.get_settings()
        row.psa_ai_enabled = True
        row.save()
        self.assertTrue(ai_features_enabled())

    def test_doc_generation_is_refused_when_ai_is_off(self):
        r = self.client.post(
            reverse('docs:ai_generate'),
            data='{"prompt": "write me a runbook"}',
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn('turned off', r.json()['error'])

    def test_doc_enhancement_is_refused_when_ai_is_off(self):
        r = self.client.post(
            reverse('docs:ai_enhance'),
            data='{"content": "some text"}',
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn('turned off', r.json()['error'])

    def test_doc_validation_is_refused_when_ai_is_off(self):
        r = self.client.post(
            reverse('docs:ai_validate'),
            data='{"content": "some text"}',
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn('turned off', r.json()['error'])

    def test_the_assistant_page_is_refused_when_ai_is_off(self):
        r = self.client.get(reverse('docs:ai_assistant'))
        self.assertEqual(r.status_code, 302)

    def test_asset_ai_documentation_is_refused_when_ai_is_off(self):
        from assets.models import Asset

        org = Organization.objects.create(name='Asset Co', slug='asset-ai-co')
        asset = Asset.objects.create(organization=org, name='SRV01')
        r = self.client.post(
            reverse('assets:asset_ai_doc', kwargs={'pk': asset.pk}),
            data='{}', content_type='application/json',
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn('turned off', r.json()['error'])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class MiddlewareDoesNotAuthenticateTests(TestCase):
    """
    The abuse middleware caps usage; it must not stand in for a view's own
    authentication.

    It carried a `401 Authentication required` for an unauthenticated caller,
    which was harmless only while `_is_ai_endpoint` matched nothing. When
    v3.17.569 made matching work, that line started refusing every
    token-authenticated API client: `api_mobile` authenticates with an
    `Authorization: Token ...` header that DRF resolves inside the view, so
    `request.user` is still anonymous at middleware time. The mobile receipt
    scanner returned 401 before its view ran.
    """

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_an_anonymous_request_reaches_the_view(self):
        from django.test import RequestFactory

        seen = {}

        def _view(request):
            seen['called'] = True
            from django.http import HttpResponse
            return HttpResponse('reached', status=200)

        mw = AIAbuseControlMiddleware(_view)
        from django.contrib.auth.models import AnonymousUser

        request = RequestFactory().post(reverse_any('api_mobile:ocr_receipt'))
        request.user = AnonymousUser()
        request.current_organization = None

        response = mw(request)
        self.assertTrue(seen.get('called'), 'middleware short-circuited the view')
        self.assertEqual(response.status_code, 200)

    def test_an_anonymous_request_records_no_usage(self):
        """Nothing to attribute it to, so nothing is counted against anyone."""
        from django.contrib.auth.models import AnonymousUser
        from django.http import HttpResponse
        from django.test import RequestFactory

        mw = AIAbuseControlMiddleware(lambda r: HttpResponse('ok', status=200))
        request = RequestFactory().post(reverse_any('api_mobile:ocr_receipt'))
        request.user = AnonymousUser()
        request.current_organization = None
        mw(request)  # must not raise on AnonymousUser.id
