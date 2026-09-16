"""SSL and domain expiry checks actually send the notification they promise.

Both scheduled tasks ended at `# TODO: Send email notifications`. They counted
what was expiring, wrote the count to the scheduler log and returned success —
enabled by default, reporting a healthy green check every day while sending
nothing.

Alongside the send, three narrower faults in the counting version are covered
here: already-expired items were filtered out entirely (`expires_at__gte=now`),
per-monitor warning windows and notify toggles were ignored in favour of the
global setting, and there was no re-arm, so a daily task had no way to tell a
renewed certificate from one it had already reported.
"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.mail import get_connection
from django.test import TestCase
from django.utils import timezone

from accounts.models import Membership
from core.models import Organization, SystemSetting
from monitoring.expiry_notifications import check_domain_expiry, check_ssl_expiry
from monitoring.models import Expiration, WebsiteMonitor


def locmem():
    return get_connection(backend='django.core.mail.backends.locmem.EmailBackend')


class ExpiryNotificationBase(TestCase):

    def setUp(self):
        mail.outbox = []
        self.org = Organization.objects.create(name='Acme', slug='acme')
        self.admin = User.objects.create_user(
            username='orgadmin', email='admin@acme.test', password='x',
        )
        Membership.objects.create(user=self.admin, organization=self.org, role='admin')
        self.settings = SystemSetting.get_settings()
        self.settings.notify_on_ssl_expiry = True
        self.settings.notify_on_domain_expiry = True
        self.settings.ssl_expiry_warning_days = 30
        self.settings.domain_expiry_warning_days = 30
        self.settings.smtp_enabled = True
        self.settings.smtp_host = 'smtp.test'
        self.settings.smtp_port = 587
        self.settings.smtp_username = 'mailer@acme.test'
        self.settings.smtp_from_email = 'mailer@acme.test'
        self.settings.smtp_from_name = 'Client St0r'
        self.settings.site_url = 'https://example.test'
        self.settings.save()

    def run_ssl(self):
        with patch('monitoring.expiry_notifications.get_smtp_connection', lambda s: locmem()):
            return check_ssl_expiry(self.settings)

    def run_domain(self):
        with patch('monitoring.expiry_notifications.get_smtp_connection', lambda s: locmem()):
            return check_domain_expiry(self.settings)

    def monitor(self, **kwargs):
        defaults = dict(
            organization=self.org, name='acme.test', url='https://acme.test',
            ssl_enabled=True,
        )
        defaults.update(kwargs)
        return WebsiteMonitor.objects.create(**defaults)


class SslExpiryNotificationTests(ExpiryNotificationBase):

    def test_an_email_is_actually_sent(self):
        self.monitor(ssl_expires_at=timezone.now() + timedelta(days=5))
        counts = self.run_ssl()

        self.assertEqual(counts['due'], 1)
        self.assertEqual(counts['notified'], 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('admin@acme.test', mail.outbox[0].to)
        self.assertIn('acme.test', mail.outbox[0].body)
        self.assertIn('expires in 5 days', mail.outbox[0].body)  # not 4: rounds up

    def test_an_already_expired_certificate_is_reported(self):
        """The old query excluded these outright: the one state that takes a
        site down produced no notification at all."""
        self.monitor(ssl_expires_at=timezone.now() - timedelta(days=2))
        counts = self.run_ssl()

        self.assertEqual(counts['notified'], 1)
        self.assertIn('EXPIRED', mail.outbox[0].subject)
        self.assertIn('EXPIRED 2 days ago', mail.outbox[0].body)

    def test_a_certificate_outside_the_window_is_left_alone(self):
        self.monitor(ssl_expires_at=timezone.now() + timedelta(days=90))
        counts = self.run_ssl()
        self.assertEqual(counts['due'], 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_a_wider_per_monitor_window_is_honoured(self):
        """`ssl_warning_days` is on the monitor's own edit form. The counting
        version read only the global setting."""
        self.monitor(
            ssl_expires_at=timezone.now() + timedelta(days=60),
            ssl_warning_days=90,
        )
        counts = self.run_ssl()
        self.assertEqual(counts['notified'], 1)

    def test_a_monitor_that_opted_out_is_not_notified(self):
        self.monitor(
            ssl_expires_at=timezone.now() + timedelta(days=5),
            notify_on_ssl_expiry=False,
        )
        counts = self.run_ssl()
        self.assertEqual(counts['due'], 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_the_same_certificate_is_not_reported_twice(self):
        self.monitor(ssl_expires_at=timezone.now() + timedelta(days=5))
        self.run_ssl()
        mail.outbox = []

        counts = self.run_ssl()
        self.assertEqual(counts['skipped'], 1)
        self.assertEqual(counts['notified'], 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_renewing_the_certificate_re_arms_the_warning(self):
        """The reason the key stores the expiry rather than a boolean: a
        renewed certificate has to be able to warn again next cycle."""
        m = self.monitor(ssl_expires_at=timezone.now() + timedelta(days=5))
        self.run_ssl()
        mail.outbox = []

        m.refresh_from_db()
        first_key = m.ssl_expiry_notified_key
        self.assertTrue(first_key)

        # Renewed, and now inside the window again 88 days later.
        m.ssl_expires_at = timezone.now() + timedelta(days=20)
        m.save(update_fields=['ssl_expires_at'])

        counts = self.run_ssl()
        self.assertEqual(counts['notified'], 1)
        self.assertEqual(len(mail.outbox), 1)
        m.refresh_from_db()
        self.assertNotEqual(m.ssl_expiry_notified_key, first_key)

    def test_expiring_escalates_to_expired(self):
        """A warning already sent must not silence the expiry itself."""
        m = self.monitor(ssl_expires_at=timezone.now() + timedelta(days=1))
        self.run_ssl()
        mail.outbox = []

        m.ssl_expires_at = timezone.now() - timedelta(hours=1)
        m.save(update_fields=['ssl_expires_at'])

        counts = self.run_ssl()
        self.assertEqual(counts['notified'], 1)
        self.assertIn('EXPIRED', mail.outbox[0].subject)

    def test_nothing_is_marked_notified_when_smtp_is_down(self):
        m = self.monitor(ssl_expires_at=timezone.now() + timedelta(days=5))
        with patch('monitoring.expiry_notifications.get_smtp_connection', lambda s: None):
            counts = check_ssl_expiry(self.settings)

        self.assertEqual(counts['notified'], 0)
        m.refresh_from_db()
        self.assertEqual(m.ssl_expiry_notified_key, '')

    def test_the_global_toggle_still_disables_the_check(self):
        self.monitor(ssl_expires_at=timezone.now() + timedelta(days=5))
        self.settings.notify_on_ssl_expiry = False
        self.settings.save()

        counts = self.run_ssl()
        self.assertEqual(counts['due'], 0)
        self.assertEqual(len(mail.outbox), 0)


class DomainExpiryNotificationTests(ExpiryNotificationBase):

    def test_a_manually_tracked_domain_is_reported(self):
        Expiration.objects.create(
            organization=self.org, name='acme.test',
            expiration_type='domain',
            expires_at=timezone.now() + timedelta(days=10),
        )
        counts = self.run_domain()

        self.assertEqual(counts['notified'], 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('acme.test', mail.outbox[0].body)

    def test_the_legacy_notification_sent_flag_is_kept_in_step(self):
        """Nothing had ever set it; it is exposed over GraphQL."""
        e = Expiration.objects.create(
            organization=self.org, name='acme.test',
            expiration_type='domain',
            expires_at=timezone.now() + timedelta(days=10),
        )
        self.run_domain()
        e.refresh_from_db()
        self.assertTrue(e.notification_sent)
        self.assertTrue(e.notification_key)

    def test_a_domain_date_held_on_a_monitor_is_reported(self):
        """`domain_expires_at` is writable through the monitor form and the
        API; the old check only ever looked at Expiration rows."""
        self.monitor(
            ssl_enabled=False,
            domain_expires_at=timezone.now() + timedelta(days=10),
        )
        counts = self.run_domain()
        self.assertEqual(counts['notified'], 1)

    def test_an_expiration_of_another_type_is_ignored(self):
        Expiration.objects.create(
            organization=self.org, name='Some licence',
            expiration_type='license',
            expires_at=timezone.now() + timedelta(days=3),
        )
        counts = self.run_domain()
        self.assertEqual(counts['due'], 0)


class RecipientTests(ExpiryNotificationBase):

    def test_superusers_and_org_admins_are_both_mailed_once(self):
        root = User.objects.create_superuser(
            username='root', email='root@acme.test', password='x',
        )
        # Also an admin of the same org: must not receive two copies.
        Membership.objects.create(user=root, organization=self.org, role='admin')
        User.objects.create_user(
            username='reader', email='reader@acme.test', password='x',
        ).memberships.create(organization=self.org, role='readonly')

        self.monitor(ssl_expires_at=timezone.now() + timedelta(days=5))
        self.run_ssl()

        addressed = sorted(m.to[0] for m in mail.outbox)
        self.assertEqual(addressed, ['admin@acme.test', 'root@acme.test'])

    def test_an_admin_of_another_organization_is_not_mailed(self):
        other = Organization.objects.create(name='Other', slug='other')
        User.objects.create_user(
            username='otheradmin', email='other@other.test', password='x',
        ).memberships.create(organization=other, role='admin')

        self.monitor(ssl_expires_at=timezone.now() + timedelta(days=5))
        self.run_ssl()

        self.assertEqual([m.to[0] for m in mail.outbox], ['admin@acme.test'])

    def test_the_recipient_query_resolves(self):
        """It asked for `organization_memberships`, which no model defines, so
        it could only ever have raised FieldError."""
        from core.mailer import notification_recipients
        self.assertEqual(notification_recipients(self.org.pk), ['admin@acme.test'])
