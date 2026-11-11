"""Customer operations: WAN, RMM alerts and SSL / domain expirations in the
uptime section, the one-click overdue invoice reminder, and the customer
page opening for MSP technicians.
"""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.tests.test_customer_ops import TEST_MIDDLEWARE, _make_msp_tech


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class UptimeAdditionsTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, RoleTemplate
        from core.models import Organization, SystemSetting
        from integrations.models import RMMAlert, RMMConnection, RMMDevice
        from locations.models import WAN, WANCheck, Location
        from monitoring.models import Expiration, WebsiteMonitor

        s = SystemSetting.get_settings()
        s.monitoring_enabled = True
        s.save()
        now = timezone.now()
        cls.a = Organization.objects.create(name='Uptime A', slug='up-a')
        cls.b = Organization.objects.create(name='Uptime B', slug='up-b')

        loc_a = Location.objects.create(organization=cls.a, name='HQ A')
        loc_b = Location.objects.create(organization=cls.b, name='HQ B')
        cls.wan_down = WAN.objects.create(organization=cls.a, location=loc_a, name='Fiber', isp_name='FastNet',
                                          monitoring_enabled=True, monitor_target='203.0.113.1',
                                          alert_state='down')
        flappy = WAN.objects.create(organization=cls.a, location=loc_a, name='Backup LTE',
                                    monitoring_enabled=True, monitor_target='203.0.113.2')
        WANCheck.objects.create(wan=flappy, checked_at=now - timedelta(days=1), result='down')
        WAN.objects.create(organization=cls.a, location=loc_a, name='Healthy cable',
                           monitoring_enabled=True, monitor_target='203.0.113.3')
        WAN.objects.create(organization=cls.b, location=loc_b, name='Other WAN', status='down')

        conn = RMMConnection.objects.create(organization=cls.a, provider_type='ninjaone', name='Ninja A')
        dev_a = RMMDevice.objects.create(connection=conn, organization=cls.a, external_id='d1',
                                         device_name='FRONTDESK')
        dev_b = RMMDevice.objects.create(connection=conn, organization=cls.b, external_id='d2',
                                         device_name='OTHERPC')
        RMMAlert.objects.create(connection=conn, organization=cls.a, device=dev_a, external_id='a1',
                                alert_type='Disk space', message='C: below 5%', severity='critical',
                                status='active', triggered_at=now - timedelta(hours=1))
        RMMAlert.objects.create(connection=conn, organization=cls.a, device=dev_a, external_id='a2',
                                alert_type='Old', message='done', severity='critical',
                                status='resolved', triggered_at=now - timedelta(hours=5))
        RMMAlert.objects.create(connection=conn, organization=cls.b, device=dev_b, external_id='b1',
                                alert_type='Other alert', message='x', severity='critical',
                                status='active', triggered_at=now)

        WebsiteMonitor.objects.create(organization=cls.a, name='Cert soon', url='https://cert.example',
                                      status='active', ssl_expires_at=now + timedelta(days=5, hours=1))
        WebsiteMonitor.objects.create(organization=cls.a, name='Domain gone', url='https://dom.example',
                                      status='active', domain_expires_at=now - timedelta(days=2))
        WebsiteMonitor.objects.create(organization=cls.a, name='Cert fine', url='https://fine.example',
                                      status='active', ssl_expires_at=now + timedelta(days=200))
        Expiration.objects.create(organization=cls.a, name='Wildcard cert', expiration_type='ssl_cert',
                                  expires_at=now + timedelta(days=20), warning_days=30)
        Expiration.objects.create(organization=cls.a, name='Far domain', expiration_type='domain',
                                  expires_at=now + timedelta(days=300), warning_days=30)
        Expiration.objects.create(organization=cls.a, name='Office lease', expiration_type='contract',
                                  expires_at=now + timedelta(days=3), warning_days=30)
        Expiration.objects.create(organization=cls.b, name='Other cert', expiration_type='ssl_cert',
                                  expires_at=now + timedelta(days=3), warning_days=30)

        cls.su = User.objects.create_superuser('upt_su', 'su@x.com', 'pw')
        cls.monitor_only = User.objects.create_user('upt_mon', 'm@x.com', 'pw')
        role = RoleTemplate.objects.create(name='Monitor only', monitoring_view=True, integrations_view=False)
        Membership.objects.create(user=cls.monitor_only, organization=cls.a, role='readonly', role_template=role)

    def build(self, user):
        from core import customer_ops
        return customer_ops.build_section(SimpleNamespace(user=user, is_staff_user=False), self.a, 'uptime')

    def test_wan_rmm_and_expiries_listed_for_this_customer_only(self):
        s = self.build(self.su)
        titles = {i.title for i in s.items}
        for expected in ('WAN Fiber', 'WAN Backup LTE', 'FRONTDESK: Disk space',
                         'Cert soon', 'Domain gone', 'Wildcard cert'):
            self.assertIn(expected, titles)
        for absent in ('WAN Healthy cable', 'WAN Other WAN', 'OTHERPC: Other alert', 'FRONTDESK: Old',
                       'Cert fine', 'Far domain', 'Office lease', 'Other cert'):
            self.assertNotIn(absent, titles)
        by_title = {i.title: i for i in s.items}
        self.assertEqual(by_title['WAN Fiber'].severity, 'danger')
        self.assertEqual(by_title['WAN Backup LTE'].severity, 'info')
        self.assertEqual(by_title['FRONTDESK: Disk space'].severity, 'danger')
        self.assertEqual(by_title['Cert soon'].severity, 'danger')        # 5 days left
        self.assertEqual(by_title['Domain gone'].severity, 'danger')      # expired
        self.assertIn('expired', by_title['Domain gone'].detail)
        self.assertEqual(by_title['Wildcard cert'].severity, 'warning')   # 20 days left
        self.assertIn(reverse('locations:wan_detail', args=[self.wan_down.location_id, self.wan_down.pk]),
                      [a.url for a in by_title['WAN Fiber'].actions])

    def test_rmm_alerts_need_integrations_view(self):
        titles = {i.title for i in self.build(self.monitor_only).items}
        self.assertNotIn('FRONTDESK: Disk space', titles)
        self.assertIn('WAN Fiber', titles)
        self.assertIn('Cert soon', titles)

    def test_customer_users_get_no_staff_only_links(self):
        items = self.build(self.monitor_only).items
        urls = [a.url for i in items for a in i.actions]
        self.assertFalse(any('/expirations/' in u for u in urls))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class InvoiceReminderTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, RoleTemplate
        from core.models import Organization, SystemSetting
        from psa.models import Invoice

        call_command('psa_seed_defaults', verbosity=0)
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        today = timezone.localdate()
        cls.a = Organization.objects.create(name='Remind A', slug='rem-a', primary_contact_email='ap@a.test')
        cls.b = Organization.objects.create(name='Remind B', slug='rem-b', email='ap@b.test')
        cls.no_mail = Organization.objects.create(name='Remind C', slug='rem-c')

        def invoice(org, title, status='sent', due_days=-20, total='100.00', paid='0'):
            inv = Invoice.objects.create(organization=org, client_org=org, title=title, status=status,
                                         invoice_date=today - timedelta(days=60),
                                         due_date=today + timedelta(days=due_days))
            Invoice.objects.filter(pk=inv.pk).update(total=Decimal(total), amount_paid=Decimal(paid))
            return Invoice.objects.get(pk=inv.pk)

        cls.overdue = invoice(cls.a, 'Overdue')
        cls.not_due = invoice(cls.a, 'Not due', due_days=10)
        cls.paid_up = invoice(cls.a, 'Paid up', status='partial', paid='100.00')
        cls.other = invoice(cls.b, 'Other customer')
        cls.no_mail_inv = invoice(cls.no_mail, 'No address')

        cls.su = User.objects.create_superuser('rem_su', 'su@x.com', 'pw')
        cls.tech = _make_msp_tech(User.objects.create_user('rem_tech', 't@x.com', 'pw'))
        cls.tech_view_only = _make_msp_tech(
            User.objects.create_user('rem_tech_vo', 'v@x.com', 'pw'),
            global_role=RoleTemplate.objects.create(name='Billing view', billing_view_invoices=True,
                                                    billing_send_invoices=False))
        cls.owner = User.objects.create_user('rem_owner', 'o@x.com', 'pw')
        Membership.objects.create(user=cls.owner, organization=cls.a, role='owner')

    def setUp(self):
        mail.outbox = []
        patcher = mock.patch('psa.pdf.render_invoice_pdf', return_value=b'%PDF-1.4 test')
        patcher.start()
        self.addCleanup(patcher.stop)

    def url(self, inv, org=None):
        return reverse('core:customer_ops_invoice_reminder', args=[(org or inv.client_org).pk, inv.pk])

    def post(self, user, url):
        self.client.force_login(user)
        return self.client.post(url)

    def _reminders(self, inv):
        from audit.models import AuditLog
        return AuditLog.objects.filter(object_type='psa.Invoice', object_id=inv.pk,
                                       extra_data__kind='overdue_reminder')

    def test_holder_sends_reminder_with_pdf_and_audit(self):
        for user in (self.su, self.tech):
            mail.outbox = []
            from audit.models import AuditLog
            AuditLog.objects.filter(extra_data__kind='overdue_reminder').delete()
            r = self.post(user, self.url(self.overdue))
            self.assertRedirects(r, reverse('core:customer_ops', args=[self.a.pk]) + '#ops-invoices',
                                 fetch_redirect_response=False)
            self.assertEqual(len(mail.outbox), 1, user.username)
            msg = mail.outbox[0]
            self.assertEqual(msg.to, ['ap@a.test'])
            self.assertIn('Reminder', msg.subject)
            self.assertIn(self.overdue.invoice_number, msg.subject)
            self.assertIn('100.00', msg.body)
            self.assertEqual(msg.attachments[0][0], f'{self.overdue.invoice_number}.pdf')
            log = self._reminders(self.overdue).get()
            self.assertTrue(log.success)
            self.assertEqual(log.user, user)
            self.assertEqual(log.extra_data['recipient'], 'ap@a.test')

    def test_double_click_sends_once(self):
        self.post(self.su, self.url(self.overdue))
        self.post(self.su, self.url(self.overdue))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(self._reminders(self.overdue).count(), 1)

    def test_get_is_not_allowed(self):
        self.client.force_login(self.su)
        self.assertEqual(self.client.get(self.url(self.overdue)).status_code, 405)
        self.assertEqual(len(mail.outbox), 0)

    def test_without_send_permission_is_403(self):
        for user in (self.tech_view_only, self.owner):
            r = self.post(user, self.url(self.overdue))
            self.assertEqual(r.status_code, 403, user.username)
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(self._reminders(self.overdue).exists())

    def test_not_overdue_or_other_customer_is_404(self):
        self.assertEqual(self.post(self.su, self.url(self.not_due)).status_code, 404)
        # B's invoice through A's page.
        self.assertEqual(self.post(self.su, self.url(self.other, org=self.a)).status_code, 404)
        self.assertEqual(len(mail.outbox), 0)

    def test_no_balance_or_no_address_sends_nothing(self):
        self.post(self.su, self.url(self.paid_up))
        self.post(self.su, self.url(self.no_mail_inv))
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(self._reminders(self.no_mail_inv).exists())

    def test_held_for_approval_sends_nothing(self):
        from psa.models import Invoice
        Invoice.objects.filter(pk=self.overdue.pk).update(requires_approval=True)
        self.post(self.su, self.url(self.overdue))
        self.assertEqual(len(mail.outbox), 0)

    def test_send_failure_is_logged_as_failed(self):
        with mock.patch('psa.pdf.email_invoice', side_effect=OSError('smtp down')):
            self.post(self.su, self.url(self.overdue))
        log = self._reminders(self.overdue).get()
        self.assertFalse(log.success)
        self.assertIn('smtp down', log.extra_data['error'])

    def test_button_is_a_post_form_for_holders_only(self):
        page = reverse('core:customer_ops', args=[self.a.pk])
        self.client.force_login(self.su)
        html = self.client.get(page).content.decode()
        self.assertIn(f'action="{self.url(self.overdue)}"', html)
        self.assertIn('data-action="send-reminder"', html)
        self.client.force_login(self.tech_view_only)
        html = self.client.get(page).content.decode()
        self.assertNotIn('data-action="send-reminder"', html)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CustomerPageAccessTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from accounts.models import Membership, RoleTemplate
        from core.models import Organization
        cls.a = Organization.objects.create(name='Page A', slug='page-a')
        cls.child = Organization.objects.create(name='Page A child', slug='page-a-child', parent=cls.a)
        cls.b = Organization.objects.create(name='Page B', slug='page-b')
        cls.tech = _make_msp_tech(User.objects.create_user('page_tech', 't@x.com', 'pw'))
        cls.tech_global = _make_msp_tech(User.objects.create_user('page_tech_g', 'g@x.com', 'pw'),
                                         global_role=RoleTemplate.objects.create(name='Page global',
                                                                                 tickets_view=True))
        cls.member_a = User.objects.create_user('page_member', 'm@x.com', 'pw')
        Membership.objects.create(user=cls.member_a, organization=cls.a, role='readonly')

    def get(self, user, org):
        self.client.force_login(user)
        return self.client.get(reverse('accounts:organization_detail', args=[org.pk]))

    def test_msp_techs_open_any_customer_page(self):
        for user in (self.tech, self.tech_global):
            for org in (self.a, self.b):
                with self.subTest(user=user.username, org=org.slug):
                    self.assertEqual(self.get(user, org).status_code, 200)

    def test_members_open_their_customer_and_its_subsidiaries(self):
        self.assertEqual(self.get(self.member_a, self.a).status_code, 200)
        self.assertEqual(self.get(self.member_a, self.child).status_code, 200)

    def test_other_customer_is_still_bounced(self):
        r = self.get(self.member_a, self.b)
        self.assertRedirects(r, reverse('accounts:organization_list'), fetch_redirect_response=False)
