"""Settings → General → Customer portal (core.portal_settings_views) and the
branding / layout it applies to portal pages (core.portal_branding,
portal/templatetags/portal_theme.py)."""
import io
import re
import shutil
import tempfile
from pathlib import Path

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from core import portal_branding
from core.models import FirewallSettings, Organization, SystemSetting

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]
URL = '/core/settings/portal/'
TMP_MEDIA = tempfile.mkdtemp(prefix='portal-settings-media-')


def _png(size=(40, 20), mode='RGBA', fmt='PNG', name='logo.png'):
    from PIL import Image
    buf = io.BytesIO()
    Image.new(mode, size, (10, 120, 200, 255) if mode == 'RGBA' else (10, 120, 200)).save(buf, format=fmt)
    return SimpleUploadedFile(name, buf.getvalue(), content_type=f'image/{fmt.lower()}')


def _base_post(**extra):
    data = {
        'portal_hostname': '', 'portal_login_background': 'none',
        'portal_navigation': 'top', 'portal_content_width': 'standard',
        'portal_default_theme': 'system',
    }
    data.update(extra)
    return data


def tearDownModule():
    shutil.rmtree(TMP_MEDIA, ignore_errors=True)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, MEDIA_ROOT=TMP_MEDIA)
class PortalSettingsPageTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.su = User.objects.create_superuser('ps-su', 'su@x.com', 'pw')
        cls.staff = User.objects.create_user('ps-staff', 's@x.com', 'pw', is_staff=True)
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.site_url = 'https://staff.example.com'
        s.save()
        cls.org_a = Organization.objects.create(name='Alpha Co', slug='ps-alpha')
        cls.org_b = Organization.objects.create(name='Beta Co', slug='ps-beta')

    def setUp(self):
        self.client.force_login(self.su)

    def post(self, **extra):
        return self.client.post(URL, _base_post(**extra))

    def ss(self):
        return SystemSetting.get_settings()

    # -- access --------------------------------------------------------------

    def test_non_superuser_is_refused(self):
        self.client.force_login(self.staff)
        self.assertNotEqual(self.client.get(URL).status_code, 200)
        self.client.post(URL, _base_post(portal_name='Hijack'))
        self.assertEqual(self.ss().portal_name, '')
        self.client.post(URL, {'action': 'customers', 'org_ids': [self.org_a.pk],
                               f'portal_{self.org_a.pk}': 'on'})
        from psa.models import ClientPSASettings
        self.assertFalse(ClientPSASettings.objects.filter(organization=self.org_a).exists())

    def test_anonymous_is_sent_to_sign_in(self):
        self.client.logout()
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 302)

    def test_page_renders_sections_and_links(self):
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        for anchor in ('portal-address', 'portal-branding', 'portal-layout', 'portal-features',
                       'portal-customers', 'portal-country'):
            self.assertIn(f'id="{anchor}"', html)
        self.assertIn('data-effective-url>https://staff.example.com/portal/', html)
        self.assertRegex(html, r'href="[^"]*/portal/login/" target="_blank" rel="noopener" data-open-portal')
        self.assertIn(reverse('core:firewall_settings'), html)
        self.assertIn(reverse('accounts:organization_edit', args=[self.org_a.pk]), html)

    def test_workspace_lists_the_new_tab(self):
        html = self.client.get(reverse('core:settings_general')).content.decode()
        ws = re.search(r'<nav class="settings-ws"[^>]*>(.*?)</nav>', html, re.S).group(1)
        self.assertIn(f'href="{URL}"', ws)
        self.assertRegex(ws, r'data-label="Customer Portal" data-where="General" '
                             r'data-filter="Customer Portal portal customer client branding logo')
        own = self.client.get(URL).content.decode()
        self.assertIn(f'class="nav-link settings-menu-item active" href="{URL}" aria-current="page"', own)

    # -- address -------------------------------------------------------------

    @override_settings(ALLOWED_HOSTS=['testserver', 'portal.example.com', 'staff.example.com'])
    def test_hostname_saves_and_validates(self):
        r = self.post(portal_hostname='Portal.Example.com')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.ss().portal_hostname, 'portal.example.com')
        r = self.post(portal_hostname='staff.example.com', portal_name='Not saved')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'must differ from the host staff use')
        self.assertEqual(self.ss().portal_hostname, 'portal.example.com')
        self.assertEqual(self.ss().portal_name, '')   # nothing saved on an error
        html = self.client.get(URL).content.decode()
        self.assertIn('data-effective-url>https://portal.example.com/portal/', html)

    @override_settings(PORTAL_HOSTNAME='env-portal.example.com',
                       ALLOWED_HOSTS=['testserver', 'env-portal.example.com'])
    def test_env_hostname_is_read_only(self):
        s = self.ss()
        s.portal_hostname = 'kept.example.com'
        s.save()
        html = self.client.get(URL).content.decode()
        self.assertIn('data-hostname-env', html)
        self.assertIn('value="env-portal.example.com" readonly', html)
        self.assertNotIn('name="portal_hostname"', html)
        self.post(portal_hostname='other.example.com')
        self.assertEqual(self.ss().portal_hostname, 'kept.example.com')

    def test_general_page_links_here_and_no_longer_saves_hostname(self):
        s = self.ss()
        s.portal_hostname = 'portal.example.com'
        s.save()
        html = self.client.get(reverse('core:settings_general')).content.decode()
        self.assertNotIn('name="portal_hostname"', html)
        self.assertIn(f'href="{URL}"', html.split('data-portal-settings-link', 1)[1][:600])
        self.client.post(reverse('core:settings_general'), {
            'site_name': 'MSP', 'site_url': 'https://staff.example.com',
            'default_timezone': 'UTC', 'portal_hostname': '',
        })
        s = self.ss()
        self.assertEqual(s.portal_hostname, 'portal.example.com')   # value kept
        self.assertEqual(s.site_name, 'MSP')                        # General still saves

    # -- branding ------------------------------------------------------------

    def test_branding_fields_save(self):
        r = self.post(portal_name='NorthStar', portal_accent_custom='on', portal_accent_color='#7C3AED',
                      portal_login_message='Hello\nthere', portal_support_email='help@northstar.example',
                      portal_support_phone='+1 (555) 010-2000 ext 12',
                      portal_support_url='https://northstar.example/help',
                      portal_login_background='color', portal_login_background_color='#112233')
        self.assertEqual(r.status_code, 302)
        s = self.ss()
        self.assertEqual(s.portal_name, 'NorthStar')
        self.assertEqual(s.portal_accent_color, '#7c3aed')
        self.assertEqual(s.portal_login_message, 'Hello\nthere')
        self.assertEqual(s.portal_support_email, 'help@northstar.example')
        self.assertEqual(s.portal_support_phone, '+1 (555) 010-2000 ext 12')
        self.assertEqual(s.portal_support_url, 'https://northstar.example/help')
        self.assertEqual(s.portal_login_background, 'color')
        self.assertEqual(s.portal_login_background_color, '#112233')
        self.assertEqual(s.updated_by, self.su)
        from audit.models import AuditLog
        log = AuditLog.objects.filter(object_type='core.SystemSetting',
                                      object_repr='Customer portal settings').latest('timestamp')
        self.assertIn('portal_name', log.extra_data['changed_fields'])

    def test_accent_unticked_clears_it(self):
        self.post(portal_accent_custom='on', portal_accent_color='#123456')
        self.post(portal_accent_color='#123456')
        self.assertEqual(self.ss().portal_accent_color, '')

    def test_bad_values_are_refused(self):
        cases = [
            {'portal_accent_custom': 'on', 'portal_accent_color': 'red'},
            {'portal_accent_custom': 'on', 'portal_accent_color': '#12345'},
            {'portal_login_background': 'color', 'portal_login_background_color': 'url(x)'},
            {'portal_support_email': 'not-an-email'},
            {'portal_support_phone': 'call me maybe'},
            {'portal_support_url': 'javascript:alert(1)'},
            {'portal_support_url': 'ftp://example.com/'},
            {'portal_login_message': 'x' * 501},
            {'portal_navigation': 'floating'},
            {'portal_content_width': 'huge'},
            {'portal_default_theme': 'neon'},
            {'portal_login_background': 'video'},
            {'portal_login_background': 'image'},   # no image uploaded
        ]
        for extra in cases:
            with self.subTest(extra=extra):
                r = self.post(portal_name='Should not save', **extra)
                self.assertEqual(r.status_code, 200)
                self.assertContains(r, 'Nothing was saved')
                self.assertEqual(self.ss().portal_name, '')

    def test_logo_upload_is_reencoded_and_ordered(self):
        r = self.post(portal_logo=_png())
        self.assertEqual(r.status_code, 302)
        name = self.ss().portal_logo.name
        self.assertTrue(name.startswith('branding/portal/'))
        self.assertRegex(name, r'^branding/portal/[0-9a-f]{32}\.png$')
        # Remove it again.
        self.post(clear_portal_logo='on')
        self.assertFalse(self.ss().portal_logo)

    def test_wrong_type_and_oversize_images_are_refused(self):
        fake = SimpleUploadedFile('logo.png', b'<svg xmlns="http://www.w3.org/2000/svg"></svg>',
                                  content_type='image/png')
        r = self.post(portal_logo=fake)
        self.assertContains(r, 'Upload a PNG, JPEG or WebP image.')
        r = self.post(portal_logo=_png(fmt='GIF', mode='RGB', name='a.gif'))
        self.assertContains(r, 'Upload a PNG, JPEG or WebP image.')
        from core import portal_settings_views
        big = SimpleUploadedFile('big.png', b'\0' * (portal_settings_views.LOGO_MAX_BYTES + 1),
                                 content_type='image/png')
        r = self.post(portal_logo=big)
        self.assertContains(r, 'at most 2 MB')
        self.assertFalse(self.ss().portal_logo)

    def test_background_image_saves(self):
        r = self.post(portal_login_background='image',
                      portal_login_background_image=_png(size=(64, 36), mode='RGB', fmt='JPEG', name='bg.jpg'))
        self.assertEqual(r.status_code, 302)
        s = self.ss()
        self.assertEqual(s.portal_login_background, 'image')
        self.assertRegex(s.portal_login_background_image.name, r'^branding/portal/backgrounds/[0-9a-f]{32}\.jpg$')
        # Keeping image mode without a new upload keeps the image.
        self.assertEqual(self.post(portal_login_background='image').status_code, 302)
        self.assertTrue(self.ss().portal_login_background_image)

    def test_portal_images_are_public_media(self):
        self.post(portal_logo=_png())
        url = self.ss().portal_logo.url
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 200)

    # -- layout --------------------------------------------------------------

    def test_layout_fields_save(self):
        self.post(portal_navigation='side', portal_content_width='wide', portal_default_theme='dark')
        s = self.ss()
        self.assertEqual((s.portal_navigation, s.portal_content_width, s.portal_default_theme),
                         ('side', 'wide', 'dark'))

    # -- features ------------------------------------------------------------

    def test_feature_switches_save_here(self):
        self.post(psa_portal_announcements_enabled='on', psa_portal_customer_approvals_enabled='on')
        s = self.ss()
        self.assertTrue(s.psa_portal_announcements_enabled)
        self.assertFalse(s.psa_portal_voting_enabled)
        self.assertFalse(s.psa_portal_escalation_enabled)
        self.assertTrue(s.psa_portal_customer_approvals_enabled)
        self.post(psa_portal_voting_enabled='on')
        s = self.ss()
        self.assertFalse(s.psa_portal_announcements_enabled)
        self.assertTrue(s.psa_portal_voting_enabled)

    def test_psa_off_hides_features_and_customers_and_keeps_switches(self):
        s = self.ss()
        s.psa_enabled = False
        s.psa_portal_voting_enabled = True
        s.save()
        html = self.client.get(URL).content.decode()
        self.assertEqual(html.count('data-psa-off'), 2)
        self.assertNotIn('name="psa_portal_voting_enabled"', html)
        self.assertNotIn('name="org_ids"', html)
        self.post(portal_name='Saved')
        self.assertTrue(self.ss().psa_portal_voting_enabled)   # not cleared
        self.client.post(URL, {'action': 'customers', 'org_ids': [self.org_a.pk],
                               f'portal_{self.org_a.pk}': 'on'})
        from psa.models import ClientPSASettings
        self.assertFalse(ClientPSASettings.objects.filter(organization=self.org_a).exists())

    # -- customers -----------------------------------------------------------

    def test_bulk_customer_toggles(self):
        from psa.models import ClientPSASettings
        ClientPSASettings.objects.create(organization=self.org_b, portal_enabled=True, enabled=False)
        r = self.client.post(URL, {'action': 'customers',
                                   'org_ids': [self.org_a.pk, self.org_b.pk],
                                   f'portal_{self.org_a.pk}': 'on'})
        self.assertRedirects(r, URL + '#portal-customers', fetch_redirect_response=False)
        a = ClientPSASettings.objects.get(organization=self.org_a)    # created
        self.assertTrue(a.portal_enabled)
        self.assertTrue(a.enabled)
        b = ClientPSASettings.objects.get(organization=self.org_b)
        self.assertFalse(b.portal_enabled)
        self.assertFalse(b.enabled)   # its PSA opt-out untouched
        from audit.models import AuditLog
        self.assertEqual(AuditLog.objects.filter(object_type='psa.ClientPSASettings').count(), 2)
        html = self.client.get(URL).content.decode()
        self.assertRegex(html, r'name="portal_%d" id="portal_%d" checked' % (self.org_a.pk, self.org_a.pk))

    def test_customers_not_listed_are_left_alone(self):
        from psa.models import ClientPSASettings
        ClientPSASettings.objects.create(organization=self.org_b, portal_enabled=True)
        self.client.post(URL, {'action': 'customers', 'org_ids': [self.org_a.pk]})
        self.assertTrue(ClientPSASettings.objects.get(organization=self.org_b).portal_enabled)
        self.assertFalse(ClientPSASettings.objects.filter(organization=self.org_a).exists())
        r = self.client.post(URL, {'action': 'customers', 'org_ids': ['x']}, follow=True)
        self.assertContains(r, 'Nothing was changed')

    # -- country policy ------------------------------------------------------

    def test_country_policy_summary(self):
        fw = FirewallSettings.get_settings()
        fw.portal_geoip_mode = FirewallSettings.PORTAL_GEOIP_OFF
        fw.save()
        html = self.client.get(URL).content.decode()
        self.assertIn('data-geoip-mode="off">No country restriction', html)
        self.assertNotIn('name="portal_geoip_mode"', html)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, MEDIA_ROOT=TMP_MEDIA)
class PortalRenderingTests(TestCase):
    """What the settings do to portal pages."""

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, Role
        from psa.models import ClientPSASettings
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.require_2fa = False
        s.custom_company_name = 'Fallback MSP'
        s.save()
        cls.org = Organization.objects.create(name='RenderCo', slug='ps-render')
        ClientPSASettings.objects.create(organization=cls.org, portal_enabled=True)
        cls.user = User.objects.create_user('ps-portal', 'p@x.com', 'pw')
        Membership.objects.create(user=cls.user, organization=cls.org, role=Role.READONLY, is_active=True)

    def setUp(self):
        from core import security_policy
        security_policy.invalidate()

    def set(self, **fields):
        s = SystemSetting.get_settings()
        for k, v in fields.items():
            setattr(s, k, v)
        s.save()
        return s

    def portal(self, path='/portal/'):
        self.client.force_login(self.user)
        session = self.client.session
        session['2fa_prompted'] = True
        session.save()
        r = self.client.get(path)
        self.assertEqual(r.status_code, 200)
        return r.content.decode()

    def login_page(self):
        self.client.logout()
        r = self.client.get('/portal/login/')
        self.assertEqual(r.status_code, 200)
        return r.content.decode()

    def _store(self, field, name):
        from django.core.files.base import ContentFile
        s = SystemSetting.get_settings()
        getattr(s, field).save(name, ContentFile(_png().read()), save=True)
        return getattr(SystemSetting.get_settings(), field).url

    def test_defaults_render_as_before(self):
        html = self.portal()
        self.assertIn('portal-nav-top portal-width-standard', html)
        self.assertNotIn('data-portal-theme=', html)
        self.assertNotIn('--portal-accent:', html)
        self.assertNotIn('data-portal-contact', html)
        self.assertIn('portal-brand-mark', html)
        login = self.login_page()
        self.assertIn('portal-login-bg-none', login)
        self.assertNotIn('data-portal-welcome', login)
        self.assertIn('Fallback MSP', login)

    def test_logo_order(self):
        custom = self._store('custom_logo', 'c.png')
        self.assertIn(f'src="{custom}"', self.portal())
        portal_logo = self._store('portal_logo', 'p.png')
        html = self.portal()
        self.assertIn(f'src="{portal_logo}"', html)
        self.assertNotIn(f'src="{custom}"', html)
        self.assertIn(f'src="{portal_logo}"', self.login_page())
        from django.core.files.base import ContentFile
        self.org.logo.save('org.png', ContentFile(_png().read()), save=True)
        html = self.portal()
        self.assertIn(f'src="{self.org.logo.url}" alt="RenderCo"', html)
        self.assertNotIn(f'src="{portal_logo}"', html)
        # No customer on the sign-in page: the portal logo.
        self.assertIn(f'src="{portal_logo}"', self.login_page())

    def test_accent_default_and_customer_colour(self):
        self.set(portal_accent_color='#0055aa')
        html = self.portal()
        self.assertIn('--portal-accent: #0055aa', html)
        self.assertIn('--portal-accent: #0055aa', self.login_page())
        self.org.portal_primary_color = '#ff7700'
        self.org.save(update_fields=['portal_primary_color'])
        html = self.portal()
        self.assertIn('#ff7700', html)
        self.assertNotIn('#0055aa', html)

    def test_accent_is_never_unvalidated(self):
        self.set(portal_accent_color='red;}x{')
        self.assertNotIn('red;}', self.portal())

    def test_layout_classes(self):
        self.set(portal_navigation='side', portal_content_width='wide')
        html = self.portal()
        self.assertIn('class="portal-body portal-app portal-nav-side portal-width-wide"', html)
        self.assertIn('<span class="portal-nav-label">Notification preferences</span>', html)
        self.assertIn('class="portal-skip-link" href="#portal-main"', html)
        css = (Path(django_settings.BASE_DIR) / 'static/css/portal.css').read_text()
        self.assertIn('.portal-nav-side .portal-header', css)
        self.assertIn('.portal-width-wide .portal-wrap', css)

    def test_theme_default(self):
        self.set(portal_default_theme='dark')
        self.assertIn('data-portal-theme="dark"', self.portal())
        self.assertIn('data-portal-theme="dark"', self.login_page())
        # A user's explicit light theme still wins.
        profile = self.user.profile
        profile.theme = 'light'
        profile.save()
        self.assertIn('data-portal-theme="light"', self.portal())

    def test_signin_background_and_message(self):
        self.set(portal_login_background='color', portal_login_background_color='#223344',
                 portal_login_message='Hi <b>there</b>\nSecond line')
        html = self.login_page()
        self.assertIn('.portal-auth { background: #223344; }', html)
        self.assertIn('Hi &lt;b&gt;there&lt;/b&gt;<br>Second line', html)
        self.assertNotIn('<b>there</b>', html)
        # Background only on sign-in pages.
        self.assertNotIn('#223344', self.portal())
        # Other sign-in pages share the background, not the message.
        self.client.logout()
        reset = self.client.get('/portal/password-reset/').content.decode()
        self.assertIn('#223344', reset)
        self.assertNotIn('data-portal-welcome', reset)

    def test_signin_background_image(self):
        url = self._store('portal_login_background_image', 'bg.png')
        self.set(portal_login_background='image')
        self.assertIn(f'url("{url}") center / cover', self.login_page())

    def test_support_contact_in_footer_and_signin(self):
        self.set(portal_support_email='help@msp.example', portal_support_phone='+1 555 010 2000',
                 portal_support_url='https://msp.example/help')
        html = self.portal()
        footer = html.split('data-portal-contact', 1)[1]
        self.assertIn('href="mailto:help@msp.example"', footer)
        self.assertIn('href="tel:+15550102000"', footer)
        self.assertIn('href="https://msp.example/help" target="_blank" rel="noopener noreferrer"', footer)
        login = self.login_page()
        self.assertIn('data-portal-signin-contact', login)
        self.assertIn('data-portal-contact', login)

    def test_unsafe_contact_values_are_dropped(self):
        self.set(portal_support_url='javascript:alert(1)', portal_support_phone='not a phone')
        html = self.portal()
        self.assertNotIn('javascript:', html)
        self.assertNotIn('not a phone', html)

    def test_portal_name(self):
        self.set(portal_name='NorthStar Help')
        self.assertIn('Support provided by NorthStar Help', self.portal())
        self.assertIn('NorthStar Help customer portal', self.login_page())


class PortalBrandingUnitTests(TestCase):

    def test_text_on_picks_readable_text(self):
        self.assertEqual(portal_branding.text_on('#000000'), '#ffffff')
        self.assertEqual(portal_branding.text_on('#ffff00'), '#111418')

    def test_readable_on_reaches_four_point_five(self):
        for colour in ('#7c3aed', '#ff7700', '#ffff00', '#0f766e', '#000000'):
            for bg in (portal_branding.LIGHT_SURFACE, portal_branding.DARK_SURFACE):
                adj = portal_branding.readable_on(colour, bg)
                self.assertGreaterEqual(portal_branding.contrast_ratio(adj, bg), 4.5, (colour, bg))

    def test_tel_href(self):
        self.assertEqual(portal_branding.tel_href('+1 (555) 010-2000 ext 12'), 'tel:+15550102000')
        self.assertEqual(portal_branding.tel_href('call me'), '')


class OrganizationPortalColourFormTests(TestCase):
    """A customer's own portal colour is edited on its customer settings."""

    def _form(self, colour):
        from accounts.forms import OrganizationForm
        return OrganizationForm(data={'name': 'Colour Co', 'portal_primary_color': colour,
                                      'is_active': 'on', 'location_name': ''})

    def test_valid_and_blank(self):
        for colour, stored in (('#FF7700', '#ff7700'), ('', '')):
            form = self._form(colour)
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.cleaned_data['portal_primary_color'], stored)

    def test_invalid(self):
        for colour in ('orange', '#ff77', 'url(x)'):
            self.assertIn('portal_primary_color', self._form(colour).errors)
