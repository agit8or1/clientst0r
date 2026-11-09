"""Navbar shortcut strip: up to three pinned pages for MSP staff.

Pins come from a fixed whitelist (core/shortcut_strip.py) and are re-checked
on every request, so a pin the user may no longer open never renders.
"""
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, RoleTemplate, UserProfile, UserType
from core import shortcut_strip
from core.models import Favorite, Organization, SystemSetting

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

EDIT_URL = '/accounts/profile/shortcuts/'


def _make_tech(user, role=None):
    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=user)
    profile.user_type = UserType.STAFF
    profile.global_role_template = role
    profile.save()
    return user


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ShortcutStripTests(TestCase):

    def setUp(self):
        row = SystemSetting.get_settings()
        row.psa_enabled = True
        row.save()
        User = get_user_model()
        self.org = Organization.objects.create(name='Strip Co', slug='strip-co')
        self.role = RoleTemplate.objects.create(name='Strip tech', reports_view_dashboards=True)
        self.tech = _make_tech(User.objects.create_user('strip_tech', 't@x.com', 'pw'), self.role)
        self.customer = User.objects.create_user('strip_cust', 'c@x.com', 'pw')
        Membership.objects.create(user=self.customer, organization=self.org)
        self.factory = RequestFactory()

    # -- helpers ------------------------------------------------------------

    def _fresh(self, user):
        return get_user_model().objects.get(pk=user.pk)

    def _strip(self, user):
        request = self.factory.get('/')
        request.user = self._fresh(user)
        return render_to_string('core/_shortcut_strip.html', {}, request=request)

    def _set_pins(self, user, pins):
        UserProfile.objects.filter(user=user).update(shortcut_pins=pins)

    def _pins(self, user):
        return [p['key'] for p in shortcut_strip.resolve_pins(self._fresh(user))]

    # -- defaults -------------------------------------------------------------

    def test_technician_gets_my_work_and_tickets_by_default(self):
        self.assertEqual(self._pins(self.tech), ['my_work', 'tickets'])
        html = self._strip(self.tech)
        self.assertIn(f'href="{reverse("psa:my_work")}"', html)
        self.assertIn(f'href="{reverse("psa:ticket_list")}"', html)
        self.assertIn('My Work', html)

    def test_customer_user_gets_no_strip(self):
        self.client.force_login(self.customer)
        self._set_pins(self.customer, ['tickets', 'assets'])
        self.assertEqual(self._pins(self.customer), [])
        self.assertEqual(self._strip(self.customer).strip(), '')
        self.assertEqual(self.client.get(EDIT_URL).status_code, 403)
        r = self.client.post(EDIT_URL, {'pins': ['tickets']})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(UserProfile.objects.get(user=self.customer).shortcut_pins, ['tickets', 'assets'])

    def test_no_pins_renders_only_the_add_link(self):
        self._set_pins(self.tech, [])
        html = self._strip(self.tech)
        self.assertNotIn('data-shortcut=', html)
        self.assertIn(reverse('accounts:shortcut_pins_edit'), html)
        self.assertIn('Add shortcuts', html)

    def test_anonymous_renders_nothing(self):
        from django.contrib.auth.models import AnonymousUser
        request = self.factory.get('/')
        request.user = AnonymousUser()
        self.assertEqual(render_to_string('core/_shortcut_strip.html', {}, request=request).strip(), '')

    # -- editing ----------------------------------------------------------------

    def test_save_up_to_three(self):
        self.client.force_login(self.tech)
        r = self.client.post(EDIT_URL, {'pins': ['assets', 'tickets', 'reports'], 'next': '/psa/'})
        self.assertRedirects(r, '/psa/', fetch_redirect_response=False)
        self.assertEqual(UserProfile.objects.get(user=self.tech).shortcut_pins,
                         ['assets', 'tickets', 'reports'])
        self.assertEqual(self._pins(self.tech), ['assets', 'tickets', 'reports'])

    def test_more_than_three_rejected(self):
        self.client.force_login(self.tech)
        r = self.client.post(EDIT_URL, {'pins': ['assets', 'tickets', 'my_work', 'documents']})
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(UserProfile.objects.get(user=self.tech).shortcut_pins)
        # Even a stored list longer than three renders at most three.
        self._set_pins(self.tech, ['assets', 'tickets', 'my_work', 'documents'])
        self.assertEqual(len(self._pins(self.tech)), 3)

    def test_whitelist_enforced(self):
        self.client.force_login(self.tech)
        for bad in (['core:settings_general'], ['tickets', 'evil'], ['https://evil.example/']):
            r = self.client.post(EDIT_URL, {'pins': bad})
            self.assertEqual(r.status_code, 400, bad)
        self.assertIsNone(UserProfile.objects.get(user=self.tech).shortcut_pins)
        # Not-yet-permitted entries are rejected too (CRM is off).
        r = self.client.post(EDIT_URL, {'pins': ['crm_pipeline']})
        self.assertEqual(r.status_code, 400)

    def test_open_redirect_ignored(self):
        self.client.force_login(self.tech)
        r = self.client.post(EDIT_URL, {'pins': ['tickets'], 'next': 'https://evil.example/'})
        self.assertRedirects(r, EDIT_URL, fetch_redirect_response=False)

    def test_reset_returns_to_defaults(self):
        self._set_pins(self.tech, ['assets'])
        self.client.force_login(self.tech)
        self.client.post(EDIT_URL, {'reset': '1'})
        self.assertEqual(self._pins(self.tech), ['my_work', 'tickets'])

    def test_edit_page_requires_csrf(self):
        from django.test import Client
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.tech)
        r = c.post(EDIT_URL, {'pins': ['assets']})
        self.assertEqual(r.status_code, 403)
        self.assertIsNone(UserProfile.objects.get(user=self.tech).shortcut_pins)
        page = c.get(EDIT_URL)
        self.assertContains(page, 'csrfmiddlewaretoken')

    # -- stale pins ---------------------------------------------------------------

    def test_stale_pin_hidden_after_permission_revoked(self):
        self._set_pins(self.tech, ['reports', 'assets'])
        self.assertIn(reverse('reports:home'), self._strip(self.tech))
        RoleTemplate.objects.filter(pk=self.role.pk).update(reports_view_dashboards=False)
        html = self._strip(self.tech)
        self.assertNotIn(reverse('reports:home'), html)
        self.assertIn(reverse('assets:asset_list'), html)

    def test_stale_pins_hidden_after_staff_status_revoked(self):
        self._set_pins(self.tech, ['tickets', 'knowledge_base'])
        UserProfile.objects.filter(user=self.tech).update(user_type=UserType.ORG_USER)
        self.assertEqual(self._strip(self.tech).strip(), '')

    def test_stale_pin_hidden_after_module_disabled(self):
        self._set_pins(self.tech, ['tickets', 'my_work', 'assets'])
        row = SystemSetting.get_settings()
        row.psa_enabled = False
        row.save()
        html = self._strip(self.tech)
        self.assertNotIn(reverse('psa:ticket_list'), html)
        self.assertNotIn(reverse('psa:my_work'), html)
        self.assertIn(reverse('assets:asset_list'), html)

    def test_pin_hidden_when_route_or_entry_removed(self):
        self._set_pins(self.tech, ['gone_entry', 'tickets', 'assets'])
        broken = [dict(e, url_name='psa:no_such_route') if e['key'] == 'tickets' else e
                  for e in shortcut_strip.SHORTCUT_REGISTRY]
        with mock.patch.object(shortcut_strip, '_BY_KEY', {e['key']: e for e in broken}):
            self.assertEqual(self._pins(self.tech), ['assets'])

    # -- favorites untouched ------------------------------------------------------

    def test_favorites_still_render(self):
        self.client.force_login(self.tech)
        Favorite.objects.create(user=self.tech, organization=self.org,
                                content_type=ContentType.objects.get_for_model(Organization),
                                object_id=self.org.pk)
        r = self.client.get(reverse('core:favorite_list'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['total_count'], 1)
        dash = self.client.get(reverse('core:dashboard')).content.decode()
        self.assertIn(reverse('core:favorite_list'), dash)
