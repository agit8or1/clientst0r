"""Recurring-invoice period uniqueness and the permissioned force re-push."""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import Permission, User
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from accounts.models import Membership, Role
from core.models import Organization, SystemSetting
from psa.models import Contract, Invoice
from psa.tests._base import TEST_MIDDLEWARE, _setup_seed


class ContractPeriodUniquenessTests(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name='UniqMSP')
        self.client_org = Organization.objects.create(name='UniqClient')
        self.contract = Contract.objects.create(
            organization=self.org, client_org=self.client_org,
            name='Managed', contract_type='managed_services', status='active',
            start_date=date(2026, 1, 1), billing_frequency='monthly',
            recurring_amount=Decimal('1000'),
            next_billing_date=date(2026, 11, 1))

    def _period_invoice(self, **kw):
        return Invoice.objects.create(**dict(dict(
            organization=self.org, client_org=self.client_org, title='P',
            invoice_date=date(2026, 11, 1), billing_period_start=date(2026, 11, 1),
            source_contract=self.contract), **kw))

    def test_key_is_populated_for_contract_period_invoices(self):
        inv = self._period_invoice()
        self.assertEqual(inv.contract_period_key, f'{self.contract.pk}:2026-11-01')
        other = Invoice.objects.create(
            organization=self.org, client_org=self.client_org, title='Ad hoc',
            invoice_date=date(2026, 11, 1))
        self.assertIsNone(other.contract_period_key)

    def test_database_rejects_second_invoice_for_same_period(self):
        self._period_invoice()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._period_invoice()

    def test_credit_memo_for_the_period_is_allowed(self):
        self._period_invoice()
        memo = self._period_invoice(is_credit_memo=True)
        self.assertIsNone(memo.contract_period_key)

    def test_generate_invoice_treats_race_as_already_generated(self):
        """Both workers pass the lookup; the loser's insert hits the unique
        key and gets the winner's invoice back instead of an error."""
        winner = self._period_invoice()
        real_filter = Invoice.objects.filter
        calls = {'n': 0}

        def racing_filter(*a, **kw):
            calls['n'] += 1
            if calls['n'] == 1:
                return real_filter(pk__in=[])   # the pre-check sees nothing
            return real_filter(*a, **kw)

        with mock.patch.object(Invoice.objects, 'filter', side_effect=racing_filter):
            got = self.contract.generate_invoice(on_date=date(2026, 11, 1))
        self.assertEqual(got.pk, winner.pk)
        self.assertEqual(Invoice.objects.filter(source_contract=self.contract).count(), 1)

    def test_generate_twice_creates_one(self):
        a = self.contract.generate_invoice(on_date=date(2026, 11, 1))
        b = self.contract.generate_invoice(on_date=date(2026, 11, 1))
        self.assertEqual(a.pk, b.pk)

    def test_find_duplicates_command_clean(self):
        self._period_invoice()
        call_command('find_duplicate_contract_invoices', stdout=mock.MagicMock())

    def test_migration_refuses_when_duplicates_exist(self):
        import importlib
        mig = importlib.import_module('psa.migrations.0086_invoice_contract_period_key')
        apps = mock.MagicMock()
        with mock.patch.object(mig, 'find_duplicates',
                               return_value=[(7, date(2026, 1, 1), [10, 11])]):
            with self.assertRaises(RuntimeError) as ctx:
                mig.check_and_backfill(apps, None)
        msg = str(ctx.exception)
        self.assertIn('contract #7', msg)
        self.assertIn('find_duplicate_contract_invoices', msg)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ForceRepushPermissionTests(TestCase):

    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='ForceMSP', slug='force-msp')
        self.client_org = Organization.objects.create(name='ForceClient', slug='force-c')
        self.staff = User.objects.create_user('force-staff', password='pw',
                                              email='fs@x.com', is_staff=True)
        Membership.objects.update_or_create(
            user=self.staff, organization=self.org,
            defaults={'role': Role.OWNER, 'is_active': True})
        self.inv = Invoice.objects.create(
            organization=self.org, client_org=self.client_org, title='Pushed',
            invoice_date=date.today(), accounting_provider='quickbooks_online',
            accounting_external_id='QBO-9')

    def _post(self):
        from django.test import Client
        c = Client()
        c.force_login(self.staff)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()
        with mock.patch('integrations.providers.accounting.get_accounting_provider') as gp:
            gp.return_value = None
            r = c.post(f'/psa/invoices/{self.inv.pk}/push/', {'force': '1'}, follow=True)
        return r, gp

    def test_force_without_permission_is_refused(self):
        r, gp = self._post()
        gp.assert_not_called()
        text = ' '.join(str(m) for m in r.context['messages'])
        self.assertIn('force re-push', text)

    def test_force_with_permission_proceeds_to_reconciling_push(self):
        from integrations.models import AccountingConnection
        AccountingConnection.objects.create(
            organization=self.org, provider_type='quickbooks_online',
            name='Books', sync_enabled=True, is_active=True)
        self.staff.user_permissions.add(
            Permission.objects.get(codename='force_repush_invoice'))
        self.staff = User.objects.get(pk=self.staff.pk)
        r, gp = self._post()
        self.assertTrue(gp.called)

    def test_view_force_goes_through_reconciliation(self):
        """With a provider, force reaches the safe service, which refuses while
        the recorded invoice still exists."""
        from integrations.models import AccountingConnection
        AccountingConnection.objects.create(
            organization=self.org, provider_type='quickbooks_online',
            name='Books', sync_enabled=True, is_active=True)
        self.staff.user_permissions.add(
            Permission.objects.get(codename='force_repush_invoice'))
        from django.test import Client
        c = Client()
        c.force_login(self.staff)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()
        provider = mock.MagicMock()
        provider.fetch_invoice.return_value = {
            'success': True, 'invoice': {'external_id': 'QBO-9', 'voided': False}}
        with mock.patch('integrations.providers.accounting.get_accounting_provider',
                        return_value=provider):
            c.post(f'/psa/invoices/{self.inv.pk}/push/', {'force': '1'})
        provider.fetch_invoice.assert_called_once_with('QBO-9')
        provider.push_invoice.assert_not_called()
