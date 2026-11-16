import csv
import io
from datetime import timedelta
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, RoleTemplate
from assets.models import Contact
from core.models import Organization
from integrations.models import DistributorConnection, M365Connection

from .alerts import collect_alerts, renewal_window, send_alerts
from .models import (ExternalCustomerMap, LicenseAlertLog, LicenseAssignment, LicenseSubscription,
                     SoftwareProduct)
from .sync import sync_m365_connection, sync_pax8_connection

User = get_user_model()

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def make_sub(org, qty=10, consumed=None, **kw):
    product = SoftwareProduct.objects.get_or_create(vendor='Acme', name='Suite', vendor_sku=kw.pop('sku', ''))[0]
    return LicenseSubscription.objects.create(organization=org, product=product, quantity_purchased=qty,
                                              vendor_consumed=consumed, **kw)


def make_staff(username, org, **flags):
    """MSP staff member with a global role holding assets_view plus `flags`."""
    user = User.objects.create_user(username, f'{username}@example.com', 'pw')
    role = RoleTemplate.objects.create(name=f'role-{username}', assets_view=True, **flags)
    from accounts.models import UserType
    # The profile cached on `user` (post_save signal): force_login() re-saves
    # it, so editing a fresh copy would be undone.
    profile = user.profile
    profile.user_type = UserType.STAFF
    profile.global_role_template = role
    profile.save()
    return user


class CountsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Acme Co', slug='acme-co')

    def test_assignment_rows_drive_counts(self):
        sub = make_sub(self.org, qty=5)
        for i in range(3):
            LicenseAssignment.objects.create(subscription=sub, assigned_to=f'u{i}')
        sub = LicenseSubscription.objects.get(pk=sub.pk)
        self.assertEqual((sub.assigned, sub.available, sub.over_allocated), (3, 2, 0))
        self.assertEqual(sub.utilization_pct, 60.0)

    def test_vendor_consumed_used_without_assignments(self):
        sub = make_sub(self.org, qty=5, consumed=4)
        self.assertEqual((sub.assigned, sub.available, sub.unused), (4, 1, 1))
        self.assertTrue(sub.has_usage_data)

    def test_over_allocated(self):
        sub = make_sub(self.org, qty=2, consumed=5)
        self.assertEqual((sub.available, sub.over_allocated), (0, 3))
        self.assertEqual(sub.utilization_pct, 250.0)

    def test_zero_purchased_and_no_usage_data(self):
        sub = make_sub(self.org, qty=0)
        self.assertIsNone(sub.utilization_pct)
        self.assertFalse(sub.has_usage_data)

    def test_cost_hidden_unless_allowed(self):
        sub = make_sub(self.org, unit_cost='4.50')
        self.assertIsNone(sub.cost_for(False))
        self.assertEqual(str(sub.cost_for(True)), '4.50')


class FakeGraph:
    """Stands in for M365Provider: two pages of users, two SKUs."""
    def __init__(self, skus, users, fail=False):
        self.skus, self.users, self.fail = skus, users, fail
        self.calls = []

    def _get_all(self, path, params=None):
        self.calls.append(path)
        if self.fail:
            raise RuntimeError('graph down')
        return self.skus

    def get_licensed_users(self):
        return [u for u in self.users if u.get('assignedLicenses')]


SKUS = [
    {'skuId': 'AAAA-1', 'skuPartNumber': 'SPE_E3', 'consumedUnits': 2,
     'prepaidUnits': {'enabled': 10}, 'capabilityStatus': 'Enabled'},
    {'skuId': 'BBBB-2', 'skuPartNumber': 'POWER_BI_PRO', 'consumedUnits': 1,
     'prepaidUnits': {'enabled': 1}, 'capabilityStatus': 'Warning'},
]
USERS = [
    {'id': 'u1', 'userPrincipalName': 'ann@acme.example', 'mail': 'ann@acme.example',
     'assignedLicenses': [{'skuId': 'aaaa-1'}]},
    {'id': 'u2', 'userPrincipalName': 'bob@acme.example', 'mail': 'bob@acme.example',
     'assignedLicenses': [{'skuId': 'AAAA-1'}, {'skuId': 'BBBB-2'}]},
    {'id': 'u3', 'userPrincipalName': 'none@acme.example', 'assignedLicenses': []},
]


class M365SyncTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Acme Co', slug='acme-co')
        cls.conn = M365Connection.objects.create(organization=cls.org, name='acme', tenant_id='t1')

    def test_creates_subscriptions_and_assignments(self):
        Contact.objects.create(organization=self.org, first_name='Ann', last_name='A', email='ann@acme.example')
        r = sync_m365_connection(self.conn, provider=FakeGraph(SKUS, USERS))
        self.assertTrue(r.ok)
        self.assertEqual(r.created, 2)
        e3 = LicenseSubscription.objects.get(organization=self.org, vendor_subscription_id='AAAA-1')
        self.assertEqual((e3.source, e3.quantity_purchased, e3.vendor_consumed, e3.status),
                         ('m365', 10, 2, 'active'))
        self.assertEqual(e3.product.vendor_sku, 'SPE_E3')
        self.assertEqual(e3.assignments.count(), 2)
        self.assertEqual(e3.assignments.get(external_id='u1').contact.email, 'ann@acme.example')
        bi = LicenseSubscription.objects.get(vendor_subscription_id='BBBB-2')
        self.assertEqual(bi.status, 'suspended')

    def test_resync_is_idempotent_and_keeps_manual_fields(self):
        fake = FakeGraph(SKUS, USERS)
        sync_m365_connection(self.conn, provider=fake)
        sub = LicenseSubscription.objects.get(vendor_subscription_id='AAAA-1')
        sub.unit_cost, sub.renewal_date, sub.notes = '12.00', timezone.localdate(), 'mine'
        sub.save()
        r = sync_m365_connection(self.conn, provider=fake)
        self.assertEqual((r.created, r.updated, r.assignments_created), (0, 2, 0))
        self.assertEqual(LicenseSubscription.objects.count(), 2)
        self.assertEqual(LicenseAssignment.objects.count(), 3)
        self.assertEqual(SoftwareProduct.objects.count(), 2)
        sub.refresh_from_db()
        self.assertEqual((str(sub.unit_cost), sub.notes), ('12.0000', 'mine'))

    def test_changes_are_reconciled(self):
        sync_m365_connection(self.conn, provider=FakeGraph(SKUS, USERS))
        manual = LicenseAssignment.objects.create(
            subscription=LicenseSubscription.objects.get(vendor_subscription_id='AAAA-1'),
            assigned_to='shared kiosk')
        users = [USERS[0]]  # bob lost both licenses
        r = sync_m365_connection(self.conn, provider=FakeGraph(SKUS[:1], users))
        self.assertEqual(r.assignments_removed, 1)
        self.assertTrue(LicenseAssignment.objects.filter(pk=manual.pk).exists())  # manual rows stay
        gone = LicenseSubscription.objects.get(vendor_subscription_id='BBBB-2')
        self.assertEqual(gone.status, 'expired')

    def test_failure_is_recorded_not_raised(self):
        sync_m365_connection(self.conn, provider=FakeGraph(SKUS, USERS))
        r = sync_m365_connection(self.conn, provider=FakeGraph(SKUS, USERS, fail=True))
        self.assertFalse(r.ok)
        self.assertIn('graph down', LicenseSubscription.objects.first().sync_error)
        self.assertEqual(LicenseSubscription.objects.count(), 2)

    def test_platform_connection_skipped(self):
        platform = M365Connection.objects.create(organization=None, name='msp', tenant_id='t0')
        r = sync_m365_connection(platform, provider=FakeGraph(SKUS, USERS))
        self.assertTrue(r.skipped)
        self.assertEqual(LicenseSubscription.objects.count(), 0)

    def test_provider_pages_users(self):
        """M365Provider.get_licensed_users follows @odata.nextLink."""
        from integrations.providers.m365 import M365Provider
        p = M365Provider('t', 'c', 's')
        pages = [{'value': [USERS[0], USERS[2]], '@odata.nextLink': 'https://graph/next'},
                 {'value': [USERS[1]]}]
        with mock.patch.object(M365Provider, '_get', side_effect=pages) as g:
            got = p.get_licensed_users()
        self.assertEqual([u['id'] for u in got], ['u1', 'u2'])
        self.assertEqual(g.call_count, 2)


class FakePax8:
    def __init__(self, rows, companies=(), fail=False):
        self.rows, self.companies, self.fail = rows, list(companies), fail

    def list_subscriptions(self):
        if self.fail:
            raise RuntimeError('pax8 down')
        return self.rows

    def list_companies(self):
        return self.companies

    def get_product(self, pid):
        return {'name': 'Microsoft 365 Business Premium', 'vendorName': 'Microsoft'}


PAX_ROWS = [
    {'id': 's1', 'companyId': 'c-acme', 'productId': 'p1', 'quantity': 12, 'status': 'Active',
     'billingTerm': 'Annual', 'startDate': '2026-01-01', 'endDate': '2027-01-01', 'partnerCost': 20.5},
    {'id': 's2', 'companyId': 'c-other', 'productId': 'p1', 'quantity': 3, 'status': 'Active'},
]


class Pax8SyncTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Acme Co', slug='acme-co')
        cls.conn = DistributorConnection.objects.create(organization=None, provider_type='pax8', name='p8')

    def test_mapped_company_imported_unmapped_reported(self):
        ExternalCustomerMap.objects.create(source='pax8', external_id='c-acme', organization=self.org)
        r = sync_pax8_connection(self.conn, provider=FakePax8(PAX_ROWS))
        self.assertEqual(r.created, 1)
        self.assertEqual(len(r.unmapped), 1)
        sub = LicenseSubscription.objects.get()
        self.assertEqual((sub.organization, sub.source, sub.quantity_purchased, sub.billing_frequency,
                          str(sub.renewal_date), str(sub.unit_cost)),
                         (self.org, 'pax8', 12, 'annual', '2027-01-01', '20.5000'))
        self.assertEqual(sub.product.vendor, 'Microsoft')

    def test_auto_map_by_exact_name(self):
        fake = FakePax8(PAX_ROWS, companies=[{'id': 'c-acme', 'name': 'acme co'}, {'id': 'c-other', 'name': 'X'}])
        sync_pax8_connection(self.conn, provider=fake)
        self.assertTrue(ExternalCustomerMap.objects.filter(external_id='c-acme', organization=self.org).exists())
        self.assertEqual(LicenseSubscription.objects.count(), 1)

    def test_idempotent(self):
        ExternalCustomerMap.objects.create(source='pax8', external_id='c-acme', organization=self.org)
        fake = FakePax8(PAX_ROWS)
        sync_pax8_connection(self.conn, provider=fake)
        sub = LicenseSubscription.objects.get()
        sub.unit_price = '30'
        sub.save()
        r = sync_pax8_connection(self.conn, provider=fake)
        self.assertEqual((r.created, r.updated), (0, 1))
        self.assertEqual((LicenseSubscription.objects.count(), SoftwareProduct.objects.count()), (1, 1))
        sub.refresh_from_db()
        self.assertEqual(str(sub.unit_price), '30.0000')

    def test_failure_recorded(self):
        r = sync_pax8_connection(self.conn, provider=FakePax8([], fail=True))
        self.assertFalse(r.ok)

    def test_adapter_pages_subscriptions(self):
        from integrations.providers.distributors.pax8 import Pax8Provider
        conn = DistributorConnection(provider_type='pax8', name='x')
        p = Pax8Provider(conn)
        p._token, p._token_expires_at = 'tok', 10 ** 12

        def resp(payload):
            m = mock.Mock(status_code=200)
            m.json.return_value = payload
            return m
        pages = [resp({'page': {'totalPages': 2}, 'content': [{'id': 'a'}]}),
                 resp({'page': {'totalPages': 2}, 'content': [{'id': 'b'}]})]
        with mock.patch.object(p.session, 'get', side_effect=pages) as g:
            rows = p.list_subscriptions()
        self.assertEqual([r['id'] for r in rows], ['a', 'b'])
        self.assertEqual([c.kwargs['params']['page'] for c in g.call_args_list], [0, 1])


class AlertTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Acme Co', slug='acme-co')
        cls.today = timezone.localdate()
        cls.admin = make_staff('lic-admin', cls.org, manage_licensing=True)

    def test_windows(self):
        self.assertEqual([renewal_window(d) for d in (-1, 0, 30, 31, 60, 90, 91)],
                         [None, 30, 30, 60, 60, 90, None])

    def test_collect(self):
        make_sub(self.org, qty=10, consumed=4, renewal_date=self.today + timedelta(days=20))
        make_sub(self.org, qty=2, consumed=5, sku='x')
        make_sub(self.org, qty=5, sku='y')                       # no usage data: not "unused"
        make_sub(self.org, qty=5, consumed=1, status='cancelled', sku='z')
        kinds = sorted(a.kind for a in collect_alerts())
        self.assertEqual(kinds, ['over_allocated', 'renewal', 'unused'])

    def test_renewal_alert_sent_once_then_again_in_closer_window(self):
        sub = make_sub(self.org, qty=3, renewal_date=self.today + timedelta(days=80))
        r = send_alerts()
        self.assertEqual((r['alerts'], r['sent']), (1, 1))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('lic-admin@example.com', mail.outbox[0].to)
        self.assertNotIn('cost', mail.outbox[0].body.lower())
        self.assertEqual(send_alerts()['alerts'], 0)               # dedup
        self.assertEqual(len(mail.outbox), 1)
        sub.renewal_date = self.today + timedelta(days=25)         # now inside the 30-day window
        sub.save()
        self.assertEqual(send_alerts()['alerts'], 1)
        self.assertEqual(LicenseAlertLog.objects.filter(kind='renewal').count(), 2)

    def test_dry_run_records_nothing(self):
        make_sub(self.org, qty=3, renewal_date=self.today + timedelta(days=10))
        send_alerts(dry_run=True)
        self.assertEqual((len(mail.outbox), LicenseAlertLog.objects.count()), (0, 0))

    def test_no_recipient_no_log(self):
        other = Organization.objects.create(name='Other', slug='other')
        User.objects.create_user('nobody', 'nobody@example.com', 'pw')
        make_sub(other, qty=3, renewal_date=self.today + timedelta(days=10))
        # the admin's global role covers every customer, so remove it
        self.admin.profile.global_role_template = None
        self.admin.profile.save()
        send_alerts()
        self.assertEqual(LicenseAlertLog.objects.count(), 0)

    def test_command(self):
        make_sub(self.org, qty=3, renewal_date=self.today + timedelta(days=10))
        out = io.StringIO()
        call_command('licensing_alerts', stdout=out)
        self.assertIn('1 new condition', out.getvalue())


class TenantIsolationTests(TestCase):
    def test_manager_scoping(self):
        a = Organization.objects.create(name='A', slug='a')
        b = Organization.objects.create(name='B', slug='b')
        sa, sb = make_sub(a), make_sub(b, sku='b')
        self.assertEqual(list(LicenseSubscription.objects.for_organization(a, include_descendants=False)), [sa])
        self.assertNotIn(sb, LicenseSubscription.objects.for_organization(a))

    def test_same_vendor_id_in_two_customers_allowed_but_not_twice_in_one(self):
        from django.db import IntegrityError, transaction
        a = Organization.objects.create(name='A', slug='a')
        b = Organization.objects.create(name='B', slug='b')
        make_sub(a, source='m365', vendor_subscription_id='X')
        make_sub(b, source='m365', vendor_subscription_id='X')
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_sub(a, source='m365', vendor_subscription_id='X')
        make_sub(a, vendor_subscription_id='')                    # blank ids never clash
        make_sub(a, vendor_subscription_id='')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Acme Co', slug='acme-co')
        cls.other = Organization.objects.create(name='Rival Inc', slug='rival')
        cls.sub = make_sub(cls.org, qty=10, consumed=3, unit_cost='7.25', unit_price='9.00',
                           renewal_date=timezone.localdate() + timedelta(days=15))
        cls.rival_sub = make_sub(cls.other, qty=4, unit_cost='1.11', sku='r')
        cls.viewer = make_staff('viewer', cls.org)
        cls.manager = make_staff('manager', cls.org, manage_licensing=True)
        cls.coster = make_staff('coster', cls.org, manage_licensing=True, view_internal_cost_rates=True)

    def login(self, user):
        self.client.force_login(user)

    def test_cost_hidden_without_permission(self):
        self.login(self.viewer)
        for url in (reverse('licensing:customer', args=[self.org.pk]),
                    reverse('licensing:subscription_detail', args=[self.sub.pk])):
            body = self.client.get(url).content.decode()
            self.assertIn('Suite', body)
            self.assertNotIn('7.25', body)
            self.assertNotIn('Unit cost', body)
        csv_body = self.client.get(reverse('licensing:export_csv')).content.decode()
        self.assertNotIn('7.25', csv_body)
        self.assertNotIn('Unit cost', csv_body)

    def test_cost_shown_with_permission(self):
        self.login(self.coster)
        body = self.client.get(reverse('licensing:customer', args=[self.org.pk])).content.decode()
        self.assertIn('7.25', body)
        rows = list(csv.reader(io.StringIO(self.client.get(reverse('licensing:export_csv')).content.decode())))
        self.assertIn('Unit cost', rows[0])
        self.assertIn('7.2500', rows[1] + rows[2])

    def test_cost_field_absent_from_form_and_not_overwritten(self):
        self.login(self.manager)
        url = reverse('licensing:subscription_edit', args=[self.sub.pk])
        self.assertNotContains(self.client.get(url), 'unit_cost')
        data = {'product_vendor': 'Acme', 'product_name': 'Suite', 'license_type': 'subscription',
                'quantity_purchased': 10, 'unit_price': '9.00', 'currency': 'USD',
                'billing_frequency': 'monthly', 'status': 'active', 'auto_renew': 'on',
                'unit_cost': '0.01'}
        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)
        self.sub.refresh_from_db()
        self.assertEqual(str(self.sub.unit_cost), '7.2500')

    def test_viewer_cannot_manage(self):
        self.login(self.viewer)
        self.assertEqual(self.client.get(reverse('licensing:subscription_create', args=[self.org.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse('licensing:subscription_delete', args=[self.sub.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse('licensing:sync_now', args=[self.org.pk])).status_code, 403)
        self.assertTrue(LicenseSubscription.objects.filter(pk=self.sub.pk).exists())

    def test_create_assign_delete(self):
        self.login(self.manager)
        data = {'product_vendor': 'Adobe', 'product_name': 'Acrobat', 'license_type': 'per_user',
                'quantity_purchased': 2, 'unit_price': '15', 'currency': 'usd', 'billing_frequency': 'annual',
                'status': 'active', 'auto_renew': 'on'}
        r = self.client.post(reverse('licensing:subscription_create', args=[self.org.pk]), data)
        sub = LicenseSubscription.objects.get(product__name='Acrobat')
        self.assertRedirects(r, reverse('licensing:subscription_detail', args=[sub.pk]))
        self.assertEqual((sub.source, sub.currency, sub.organization), ('manual', 'USD', self.org))
        contact = Contact.objects.create(organization=self.org, first_name='Ann', last_name='A')
        self.client.post(reverse('licensing:assignment_add', args=[sub.pk]), {'contact': contact.pk, 'assigned_at': '2026-01-01'})
        a = sub.assignments.get()
        self.assertEqual(a.assigned_to, 'Ann A')
        self.client.post(reverse('licensing:assignment_delete', args=[a.pk]))
        self.assertEqual(sub.assignments.count(), 0)
        self.client.post(reverse('licensing:subscription_delete', args=[sub.pk]))
        self.assertFalse(LicenseSubscription.objects.filter(pk=sub.pk).exists())

    def test_other_customers_contact_rejected(self):
        self.login(self.manager)
        foreign = Contact.objects.create(organization=self.other, first_name='Eve', last_name='E')
        self.client.post(reverse('licensing:assignment_add', args=[self.sub.pk]), {'contact': foreign.pk})
        self.assertEqual(self.sub.assignments.count(), 0)

    def test_pages_render(self):
        self.login(self.coster)
        for name, args in (('overview', []), ('customer', [self.org.pk]), ('renewals', []),
                           ('mappings', []), ('subscription_detail', [self.sub.pk]),
                           ('subscription_create', [self.org.pk]), ('subscription_edit', [self.sub.pk])):
            self.assertEqual(self.client.get(reverse(f'licensing:{name}', args=args)).status_code, 200, name)
        body = self.client.get(reverse('licensing:renewals')).content.decode()
        self.assertIn('Acme Co', body)

    def test_csv_escapes_formulas(self):
        make_sub(self.org, sku='f').product.__class__.objects.filter(vendor_sku='f').update(name='=HYPERLINK("x")')
        self.login(self.viewer)
        body = self.client.get(reverse('licensing:export_csv')).content.decode()
        self.assertIn("'=HYPERLINK", body)

    def test_scoped_staff_cannot_reach_other_customer(self):
        scoped = make_staff('scoped', self.org, manage_licensing=True)
        scoped.profile.client_scope = 'selected'      # a global role reaching one customer only
        scoped.profile.save()
        scoped.profile.scope_organizations.add(self.org)
        self.login(scoped)
        self.assertEqual(self.client.get(reverse('licensing:customer', args=[self.org.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('licensing:customer', args=[self.other.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('licensing:subscription_detail', args=[self.rival_sub.pk])).status_code, 404)
        body = self.client.get(reverse('licensing:overview')).content.decode()
        # (the page chrome's customer switcher may list names; the licensing rows must not)
        self.assertNotIn(reverse('licensing:customer', args=[self.other.pk]), body)
        self.assertIn(reverse('licensing:customer', args=[self.org.pk]), body)
        csv_body = self.client.get(reverse('licensing:export_csv')).content.decode()
        self.assertNotIn('Rival', csv_body)
        self.assertEqual(self.client.get(reverse('licensing:export_csv') + f'?customer={self.other.pk}').status_code, 404)

    def test_anonymous_redirected(self):
        self.assertEqual(self.client.get(reverse('licensing:overview')).status_code, 302)


class PermissionDefinitionTests(TestCase):
    def test_registered_staff_only_and_default_off(self):
        from accounts import permission_registry as reg
        for key in ('manage_licensing', 'view_internal_cost_rates'):
            self.assertIn(key, reg.ALL_KEYS)
            self.assertIn(key, reg.STAFF_ONLY_KEYS)
            self.assertNotIn(key, reg.CUSTOMER_ASSIGNABLE_KEYS)
            self.assertFalse(RoleTemplate._meta.get_field(key).default)

    def test_builtin_roles(self):
        owner = RoleTemplate.objects.get(seed_key='org_owner')
        admin = RoleTemplate.objects.get(seed_key='org_admin')
        tech = RoleTemplate.objects.get(seed_key='tech_l2')
        self.assertTrue(owner.manage_licensing and owner.view_internal_cost_rates)
        self.assertTrue(admin.manage_licensing and admin.view_internal_cost_rates)
        self.assertFalse(tech.manage_licensing or tech.view_internal_cost_rates)

    def test_customer_user_never_holds_them(self):
        from accounts.permission_utils import user_has_org_perm
        org = Organization.objects.create(name='C', slug='c')
        u = User.objects.create_user('cust', 'c@example.com', 'pw')
        role = RoleTemplate.objects.create(name='cust-all', manage_licensing=True, view_internal_cost_rates=True)
        Membership.objects.create(user=u, organization=org, role_template=role, is_active=True)
        self.assertFalse(user_has_org_perm(u, org, 'view_internal_cost_rates'))
        self.assertFalse(user_has_org_perm(u, org, 'manage_licensing'))

    def test_scheduler_registered(self):
        from core.management.commands.run_scheduler import COMMAND_TASKS
        self.assertIn('sync_licenses', COMMAND_TASKS)
        self.assertIn('licensing_alerts', COMMAND_TASKS)
