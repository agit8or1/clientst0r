"""Phase 9.4: weekly digest of unresolved security alerts to a customer's
opted-in contacts — subscriptions, portal preference, signed unsubscribe,
scheduler task, customer scoping and the customer-safe content."""
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.mail import get_connection
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Membership, Role
from assets.models import Contact
from core.models import Organization, ScheduledTask, SystemSetting
from psa.models import ClientPSASettings
from psa.tests._base import TEST_MIDDLEWARE, _make_msp_tech
from security_alerts import digest
from security_alerts.models import SecurityAlert, SecurityDigestSubscription, SecurityVendorConnection


def _locmem(*_a, **_k):
    return get_connection('django.core.mail.backends.locmem.EmailBackend')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class DigestTests(TestCase):
    def setUp(self):
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.site_url = 'https://msp.example.com'
        s.save()
        self.acme = Organization.objects.create(name='Acme Dental', slug='acme-digest')
        self.other = Organization.objects.create(name='Other Clinic', slug='other-digest')
        conn = SecurityVendorConnection.objects.create(
            organization=self.acme, name='EDR', provider='huntress', category='edr')
        other_conn = SecurityVendorConnection.objects.create(
            organization=self.other, name='EDR2', provider='huntress', category='edr')
        self.a1 = SecurityAlert.objects.create(
            connection=conn, organization=self.acme, external_id='1', severity='critical',
            title='Ransomware behaviour blocked', asset_hint='FRONTDESK-01',
            description='INTERNAL: analyst says check share \\\\nas01', raw_payload={'secret': 'payload-xyz'})
        SecurityAlert.objects.create(connection=conn, organization=self.acme, external_id='2',
                                     severity='low', title='Old resolved thing', status='resolved')
        SecurityAlert.objects.create(connection=conn, organization=self.acme, external_id='3',
                                     severity='medium', title='Suspicious login', status='acknowledged')
        SecurityAlert.objects.create(connection=other_conn, organization=self.other, external_id='9',
                                     severity='high', title='OTHER CUSTOMER ALERT')
        self.sub = SecurityDigestSubscription.objects.create(organization=self.acme, email='office@acme.example')
        self.sub.set_subscribed(True, via='staff')

    def _send(self, **kw):
        with mock.patch('security_alerts.digest.get_smtp_connection', side_effect=_locmem):
            return digest.send_digests(**kw)

    def test_digest_lists_only_the_customers_unresolved_alerts_without_internal_data(self):
        out = self._send()
        self.assertEqual(out['sent'], 1)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ['office@acme.example'])
        self.assertIn('Ransomware behaviour blocked on FRONTDESK-01', msg.body)
        self.assertIn('Suspicious login', msg.body)
        self.assertIn('being investigated', msg.body)
        for leaked in ('Old resolved thing', 'OTHER CUSTOMER ALERT', 'INTERNAL', 'payload-xyz', 'huntress', 'EDR'):
            self.assertNotIn(leaked, msg.body + msg.subject)
        # Critical first.
        self.assertLess(msg.body.index('Ransomware'), msg.body.index('Suspicious login'))
        self.assertIn('https://msp.example.com/security/digest/unsubscribe/', msg.extra_headers['List-Unsubscribe'])
        self.assertEqual(msg.extra_headers['List-Unsubscribe-Post'], 'List-Unsubscribe=One-Click')

    def test_opt_in_only_and_no_mail_without_open_alerts_or_smtp(self):
        self.sub.set_subscribed(False, via='staff')
        SecurityDigestSubscription.objects.create(organization=self.acme, email='never@acme.example')
        self.assertEqual(self._send()['sent'], 0)
        self.sub.set_subscribed(True, via='staff')
        SecurityAlert.objects.filter(organization=self.acme).update(status='resolved')
        out = self._send()
        self.assertEqual((out['sent'], out['empty']), (0, 1))
        SecurityAlert.objects.filter(pk=self.a1.pk).update(status='new')
        self.assertTrue(digest.send_digests()['no_smtp'])  # SMTP not configured: nothing sent
        self.assertEqual(len(mail.outbox), 0)

    def test_weekly_guard_and_force(self):
        self._send()
        self.assertEqual(self._send()['skipped_recent'], 1)
        SecurityDigestSubscription.objects.filter(pk=self.sub.pk).update(
            last_sent_at=timezone.now() - timedelta(days=7))
        self.assertEqual(self._send()['sent'], 1)
        self.assertEqual(self._send(force=True)['sent'], 1)
        self.assertEqual(len(mail.outbox), 3)

    def test_signed_unsubscribe_link(self):
        c = Client()
        url = digest.unsubscribe_url(self.sub)
        r = c.get(url)
        self.assertContains(r, 'Stop the weekly security alert digest?')
        self.sub.refresh_from_db()
        self.assertTrue(self.sub.is_subscribed)  # a GET (mail scanner) changes nothing
        c.post(url)
        self.sub.refresh_from_db()
        self.assertFalse(self.sub.is_subscribed)
        self.assertEqual(self.sub.changed_via, 'unsubscribe_link')
        tampered = url.rstrip('/')[:-3] + 'abc/'
        self.assertEqual(c.get(tampered).status_code, 404)

    def test_unsubscribe_works_for_a_signed_in_customer_user(self):
        cust = User.objects.create_user('digest-cust', password='pw', email='office@acme.example')
        Membership.objects.create(user=cust, organization=self.acme, role=Role.EDITOR, is_active=True)
        c = Client()
        c.force_login(cust)
        r = c.post(digest.unsubscribe_url(self.sub))
        self.assertEqual(r.status_code, 200)
        self.sub.refresh_from_db()
        self.assertFalse(self.sub.is_subscribed)

    def test_portal_preferences_opt_in_and_out(self):
        ClientPSASettings.objects.update_or_create(organization=self.acme, defaults={'portal_enabled': True,
                                                                                     'enabled': True})
        cust = User.objects.create_user('digest-portal', password='pw', email='Pat@Acme.example')
        Membership.objects.create(user=cust, organization=self.acme, role=Role.EDITOR, is_active=True)
        c = Client()
        c.force_login(cust)
        self.assertContains(c.get('/portal/preferences/'), 'Weekly security alert digest')
        c.post('/portal/preferences/', {'security_digest': 'on'})
        sub = SecurityDigestSubscription.objects.get(organization=self.acme, email='pat@acme.example')
        self.assertTrue(sub.is_subscribed)
        self.assertEqual((sub.user, sub.changed_via), (cust, 'portal'))
        c.post('/portal/preferences/', {})
        sub.refresh_from_db()
        self.assertFalse(sub.is_subscribed)

    def test_staff_page_manages_contacts_and_previews(self):
        staff = _make_msp_tech(User.objects.create_user('digest-staff', password='pw', is_superuser=True))
        contact = Contact.objects.create(organization=self.acme, first_name='Ann', last_name='Lee',
                                         email='ann@acme.example')
        c = Client()
        c.force_login(staff)
        r = c.get(f'/security/digest/?org={self.acme.pk}')
        self.assertContains(r, 'office@acme.example')
        self.assertContains(r, 'Ransomware behaviour blocked')
        c.post('/security/digest/', {'org': self.acme.pk, 'action': 'add', 'contact': contact.pk})
        sub = SecurityDigestSubscription.objects.get(organization=self.acme, email='ann@acme.example')
        self.assertTrue(sub.is_subscribed)
        self.assertEqual(sub.contact, contact)
        c.post('/security/digest/', {'org': self.acme.pk, 'action': 'off', 'sub': sub.pk})
        sub.refresh_from_db()
        self.assertFalse(sub.is_subscribed)

    def test_customer_users_cannot_open_the_staff_page(self):
        cust = User.objects.create_user('digest-cust2', password='pw')
        Membership.objects.create(user=cust, organization=self.acme, role=Role.OWNER, is_active=True)
        c = Client()
        c.force_login(cust)
        self.assertEqual(c.get('/security/digest/').status_code, 403)

    def test_command_and_scheduler_task(self):
        out = StringIO()
        with mock.patch('security_alerts.digest.get_smtp_connection', side_effect=_locmem):
            call_command('send_security_digests', stdout=out)
        self.assertIn('sent: 1', out.getvalue())
        ScheduledTask.get_or_create_defaults()
        task = ScheduledTask.objects.get(task_type='send_security_digests')
        self.assertEqual(task.interval_minutes, 10080)
