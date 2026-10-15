"""
Global dashboard is MSP-staff only; vault reveal and break-glass approval
emails are actually sent; /media/ is not exempt from 2FA enrolment.
"""
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core import mail
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role
from core.models import Organization
from vault.models import Password, VaultRevealRequest

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class GlobalDashboardAccessTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Dash Co', slug='dash-co')
        cls.customer = User.objects.create_user('dash_cust', 'c@dash.test', 'pw-dash-123')
        Membership.objects.create(user=cls.customer, organization=cls.org,
                                  role=Role.OWNER, is_active=True)
        cls.staff = User.objects.create_superuser('dash_staff', 's@dash.test', 'pw-dash-123')

    def _get(self, user):
        c = Client()
        c.force_login(user)
        return c.get('/core/global-dashboard/')

    def test_customer_user_is_refused(self):
        self.assertEqual(self._get(self.customer).status_code, 403)

    def test_staff_can_open(self):
        self.assertEqual(self._get(self.staff).status_code, 200)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class VaultApprovalEmailTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Mail Co', slug='mail-co')
        User.objects.create_superuser('mail_admin', 'admin@mail.test', 'pw-mail-123')
        cls.requester = User.objects.create_user('mail_req', 'r@mail.test', 'pw-mail-123')
        cls.password = Password.objects.create(
            organization=cls.org, title='Core switch', encrypted_password='dummy')

    def test_reveal_request_emails_admins(self):
        from vault.views import _notify_admins_of_reveal_request
        req = VaultRevealRequest.objects.create(
            password=self.password, requester=self.requester, justification='outage')
        _notify_admins_of_reveal_request(req)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('admin@mail.test', mail.outbox[0].to)

    def test_break_glass_emails_admins(self):
        from vault.views import _notify_admins_of_break_glass
        req = VaultRevealRequest.objects.create(
            password=self.password, requester=self.requester, justification='outage')
        _notify_admins_of_break_glass(req)
        self.assertEqual(len(mail.outbox), 1)


class TwoFactorMediaExemptionTests(TestCase):

    def test_media_not_in_unenrolled_allowlist(self):
        from accounts.middleware import Enforce2FAMiddleware
        self.assertFalse(any(p.startswith('/media') for p in Enforce2FAMiddleware.ALLOWED_PATHS))
