"""Edit forms keep what a POST does not carry.

Issue #147's pattern, generalised: an edit view that reads a missing field as
"clear it" destroys data whenever a script that builds the field does not
run, a form renders a field conditionally, or another client posts a partial
form. Each view here is held to three cases:

* missing field  → the saved value is kept;
* malformed value → the saved value is kept, the save does not 500, and the
  user is told;
* explicit clear (blank value, unticked rendered checkbox, last row removed)
  → still clears.
"""
import json
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.models import Organization
from psa.models import (Contract, ContractBundleItem, Invoice, InvoiceLineItem, Quote, QuoteLineItem,
                        TicketPriority)
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_for, _enable_psa_global, _setup_seed


class _Base(TestCase):
    def setUp(self):
        _setup_seed()
        _enable_psa_global()
        self.org = Organization.objects.create(name='Frictionless Co', slug='ff-co')
        _enable_psa_for(self.org)
        self.admin = User.objects.create_superuser('ff_admin', 'ff@x.test', 'pw-ff-123')
        self.c = Client()
        self.c.force_login(self.admin)
        s = self.c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()

    def _warnings(self, response):
        return [str(m) for m in get_messages(response.wsgi_request) if m.level_tag == 'warning']


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ContractEditTests(_Base):
    def setUp(self):
        super().setUp()
        self.prio = TicketPriority.objects.order_by('sort_order').first()
        self.contract = Contract.objects.create(
            organization=self.org, client_org=self.org, name='Managed Gold',
            contract_type='managed_services', status='active', start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31), total_hours=Decimal('40'), hourly_rate=Decimal('150'),
            overage_rate=Decimal('175'), notes='Keep me', auto_renew=True, proration_enabled=True,
            rollover_percent=Decimal('25'), rollover_expiry_days=90, auto_renew_period_months=6,
            billable_role_codes=['T1', 'T2'], excluded_role_codes=['after_hours'],
            sla_matrix={self.prio.code: {'response_minutes': 15, 'resolution_minutes': 240}})
        self.bundle = ContractBundleItem.objects.create(
            contract=self.contract, name='Backup per server', quantity=Decimal('10'),
            unit_label='server', unit_price=Decimal('12.00'), recurring_period='monthly', sort_order=0)
        self.url = reverse('psa:contract_edit', kwargs={'pk': self.contract.pk})

    def _post(self, data):
        return self.c.post(self.url, data)

    def test_a_post_carrying_only_the_name_keeps_everything_else(self):
        r = self._post({'name': 'Managed Gold (renamed)'})
        self.assertEqual(r.status_code, 302)
        c = Contract.objects.get(pk=self.contract.pk)
        self.assertEqual(c.name, 'Managed Gold (renamed)')
        self.assertEqual(c.client_org_id, self.org.pk)
        self.assertEqual(c.status, 'active')
        self.assertEqual(c.contract_type, 'managed_services')
        self.assertEqual(c.end_date, date(2026, 12, 31))
        self.assertEqual(c.total_hours, Decimal('40'))
        self.assertEqual(c.hourly_rate, Decimal('150'))
        self.assertEqual(c.overage_rate, Decimal('175'))
        self.assertEqual(c.notes, 'Keep me')
        self.assertTrue(c.auto_renew)
        self.assertTrue(c.proration_enabled)
        self.assertEqual(c.rollover_percent, Decimal('25'))
        self.assertEqual(c.rollover_expiry_days, 90)
        self.assertEqual(c.auto_renew_period_months, 6)
        self.assertEqual(c.billable_role_codes, ['T1', 'T2'])
        self.assertEqual(c.excluded_role_codes, ['after_hours'])
        self.assertEqual(c.sla_matrix[self.prio.code], {'response_minutes': 15, 'resolution_minutes': 240})
        self.assertEqual(c.bundle_items.count(), 1)

    def test_an_empty_post_keeps_the_name_and_client(self):
        r = self._post({})
        self.assertEqual(r.status_code, 302)
        c = Contract.objects.get(pk=self.contract.pk)
        self.assertEqual((c.name, c.client_org_id), ('Managed Gold', self.org.pk))

    def test_a_blank_name_is_still_refused(self):
        r = self._post({'name': '', 'client_org': str(self.org.pk)})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Contract.objects.get(pk=self.contract.pk).name, 'Managed Gold')

    def test_malformed_values_keep_the_saved_ones_and_say_so(self):
        r = self._post({'name': 'Managed Gold', 'total_hours': 'abc', 'hourly_rate': '-5',
                        'end_date': 'not-a-date', 'status': 'bogus', 'rollover_expiry_days': 'x',
                        f'sla_{self.prio.code}_response': 'soon'})
        self.assertEqual(r.status_code, 302)
        c = Contract.objects.get(pk=self.contract.pk)
        self.assertEqual(c.total_hours, Decimal('40'))
        self.assertEqual(c.hourly_rate, Decimal('150'))
        self.assertEqual(c.end_date, date(2026, 12, 31))
        self.assertEqual(c.status, 'active')
        self.assertEqual(c.rollover_expiry_days, 90)
        self.assertEqual(c.sla_matrix[self.prio.code]['response_minutes'], 15)
        warning = ' '.join(self._warnings(r))
        self.assertIn('total hours', warning)
        self.assertIn('end date', warning)

    def test_intentional_clears_still_clear(self):
        r = self._post({'name': 'Managed Gold', 'client_org': str(self.org.pk),
                        'end_date': '', 'notes': '', 'total_hours': '',
                        'billable_role_codes': '', 'excluded_role_codes': '',
                        f'sla_{self.prio.code}_response': '', f'sla_{self.prio.code}_resolution': '',
                        'contract_flags': '1'})  # both checkboxes rendered, both unticked
        self.assertEqual(r.status_code, 302)
        c = Contract.objects.get(pk=self.contract.pk)
        self.assertIsNone(c.end_date)
        self.assertEqual(c.notes, '')
        self.assertEqual(c.total_hours, Decimal('0'))
        self.assertEqual(c.billable_role_codes, [])
        self.assertEqual(c.excluded_role_codes, [])
        self.assertNotIn(self.prio.code, c.sla_matrix)
        self.assertFalse(c.auto_renew)
        self.assertFalse(c.proration_enabled)

    def test_unticked_checkboxes_without_the_sentinel_are_kept(self):
        self._post({'name': 'Managed Gold'})
        c = Contract.objects.get(pk=self.contract.pk)
        self.assertTrue(c.auto_renew)
        self.assertTrue(c.proration_enabled)

    def test_one_sla_value_changes_without_dropping_the_other(self):
        self._post({'name': 'Managed Gold', f'sla_{self.prio.code}_response': '30'})
        c = Contract.objects.get(pk=self.contract.pk)
        self.assertEqual(c.sla_matrix[self.prio.code], {'response_minutes': 30, 'resolution_minutes': 240})

    def test_the_form_renders_sla_overrides_and_the_checkbox_sentinel_server_side(self):
        r = self.c.get(self.url)
        self.assertContains(r, f'name="sla_{self.prio.code}_response"')
        self.assertContains(r, 'value="15"')
        self.assertContains(r, 'value="240"')
        self.assertContains(r, 'name="contract_flags"')
        self.assertContains(r, 'data-unsaved-guard')

    # --- bundled services ---

    def test_a_blank_bundle_field_is_the_untouched_editor_not_a_clear(self):
        """The hidden field renders blank and stays blank until the editor
        serializes; a blank post must not delete the bundle (#147's shape)."""
        self._post({'name': 'Managed Gold', 'bundle_items_json': ''})
        self.assertTrue(ContractBundleItem.objects.filter(pk=self.bundle.pk).exists())

    def test_removing_every_row_posts_an_empty_list_and_clears(self):
        self._post({'name': 'Managed Gold', 'bundle_items_json': '[]'})
        self.assertEqual(self.contract.bundle_items.count(), 0)

    def test_add_one_and_remove_one(self):
        keep = ContractBundleItem.objects.create(contract=self.contract, name='AV per seat',
                                                 quantity=Decimal('25'), unit_price=Decimal('3'))
        rows = [{'pk': str(keep.pk), 'name': 'AV per seat', 'quantity': '30', 'unit_label': 'seat',
                 'unit_price': '3', 'recurring_period': 'monthly'},
                {'pk': '', 'name': 'Firewall', 'quantity': '1', 'unit_label': '', 'unit_price': '80',
                 'recurring_period': 'yearly'}]
        self._post({'name': 'Managed Gold', 'bundle_items_json': json.dumps(rows)})
        names = dict(self.contract.bundle_items.values_list('name', 'quantity'))
        self.assertEqual(names, {'AV per seat': Decimal('30.00'), 'Firewall': Decimal('1.00')})

    def test_a_malformed_quantity_keeps_the_saved_one(self):
        rows = [{'pk': str(self.bundle.pk), 'name': 'Backup per server', 'quantity': 'ten',
                 'unit_price': '13', 'recurring_period': 'monthly'}]
        r = self._post({'name': 'Managed Gold', 'bundle_items_json': json.dumps(rows)})
        self.bundle.refresh_from_db()
        self.assertEqual(self.bundle.quantity, Decimal('10'))
        self.assertEqual(self.bundle.unit_price, Decimal('13'))
        self.assertTrue(any('bundled service quantity' in w for w in self._warnings(r)))

    def test_a_row_naming_an_existing_line_without_a_name_keeps_it(self):
        rows = [{'pk': str(self.bundle.pk)}]
        self._post({'name': 'Managed Gold', 'bundle_items_json': json.dumps(rows)})
        self.bundle.refresh_from_db()
        self.assertEqual(self.bundle.name, 'Backup per server')

    def test_fields_left_out_of_a_row_keep_the_saved_values(self):
        rows = [{'pk': str(self.bundle.pk), 'name': 'Backup per server'}]
        self._post({'name': 'Managed Gold', 'bundle_items_json': json.dumps(rows)})
        self.bundle.refresh_from_db()
        self.assertEqual((self.bundle.quantity, self.bundle.unit_price, self.bundle.unit_label,
                          self.bundle.recurring_period),
                         (Decimal('10'), Decimal('12'), 'server', 'monthly'))

    def test_the_editor_keeps_its_field_current_and_binds_to_its_own_form(self):
        r = self.c.get(self.url)
        html = r.content.decode()
        self.assertIn("hidden.closest('form')", html)
        self.assertIn("tbody.addEventListener('change', changed)", html)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class InvoiceDraftEditTests(_Base):
    def setUp(self):
        super().setUp()
        self.inv = Invoice.objects.create(
            organization=self.org, client_org=self.org, title='October services',
            description='Monthly', invoice_date=date(2026, 10, 1), due_date=date(2026, 10, 31),
            currency='EUR', tax_rate=Decimal('0.0800'), notes='Net 30')
        self.l1 = InvoiceLineItem.objects.create(invoice=self.inv, description='Labour', quantity=Decimal('2'),
                                                 unit_price=Decimal('100'), sort_order=0, source='time_entry')
        self.l2 = InvoiceLineItem.objects.create(invoice=self.inv, description='Licence', quantity=Decimal('1'),
                                                 unit_price=Decimal('50'), sort_order=1)
        self.inv.recompute_totals()
        self.url = reverse('psa:invoice_edit', kwargs={'pk': self.inv.pk})

    def _lines(self, *rows):
        return {'li_id': [r[0] for r in rows], 'li_description': [r[1] for r in rows],
                'li_quantity': [r[2] for r in rows], 'li_unit_price': [r[3] for r in rows]}

    def _full(self):
        return dict(self._lines((str(self.l1.pk), 'Labour', '2', '100'), (str(self.l2.pk), 'Licence', '1', '50')),
                    title='October services', client_org=str(self.org.pk), status='draft',
                    invoice_date='2026-10-01', due_date='2026-10-31', currency='EUR', tax_rate='0.08',
                    description='Monthly', notes='Net 30')

    def test_a_post_carrying_only_the_title_keeps_everything(self):
        total = Invoice.objects.get(pk=self.inv.pk).total
        r = self.c.post(self.url, {'title': 'October services (v2)'})
        self.assertEqual(r.status_code, 302)
        inv = Invoice.objects.get(pk=self.inv.pk)
        self.assertEqual(inv.title, 'October services (v2)')
        self.assertEqual((inv.description, inv.currency, inv.tax_rate, inv.notes),
                         ('Monthly', 'EUR', Decimal('0.0800'), 'Net 30'))
        self.assertEqual((inv.invoice_date, inv.due_date), (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(inv.line_items.count(), 2)
        self.assertEqual(inv.total, total)
        self.assertEqual(inv.status, 'draft')

    def test_the_full_form_round_trips_unchanged(self):
        total = Invoice.objects.get(pk=self.inv.pk).total
        self.c.post(self.url, self._full())
        inv = Invoice.objects.get(pk=self.inv.pk)
        self.assertEqual(inv.total, total)
        self.assertEqual(set(inv.line_items.values_list('pk', flat=True)), {self.l1.pk, self.l2.pk})
        self.assertEqual(InvoiceLineItem.objects.get(pk=self.l1.pk).source, 'time_entry')

    def test_malformed_values_keep_the_saved_ones_without_a_500(self):
        data = self._full()
        data.update(tax_rate='eight percent', invoice_date='01/10/2026', due_date='soon')
        data.update(self._lines((str(self.l1.pk), 'Labour', 'two', '100'), (str(self.l2.pk), 'Licence', '1', '$50')))
        r = self.c.post(self.url, data)
        self.assertEqual(r.status_code, 302)
        inv = Invoice.objects.get(pk=self.inv.pk)
        self.assertEqual(inv.tax_rate, Decimal('0.0800'))
        self.assertEqual((inv.invoice_date, inv.due_date), (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(InvoiceLineItem.objects.get(pk=self.l1.pk).quantity, Decimal('2'))
        self.assertEqual(InvoiceLineItem.objects.get(pk=self.l2.pk).unit_price, Decimal('50'))
        warning = ' '.join(self._warnings(r))
        self.assertIn('tax rate', warning)
        self.assertIn('line quantity', warning)

    def test_line_columns_that_do_not_line_up_leave_the_lines_alone(self):
        data = self._full()
        data['li_quantity'] = ['2']  # one quantity for two rows
        self.c.post(self.url, data)
        self.assertEqual(self.inv.line_items.count(), 2)

    def test_removing_one_line_and_adding_another(self):
        data = self._full()
        data.update(self._lines((str(self.l1.pk), 'Labour', '3', '100'), ('', 'Travel', '1', '40')))
        self.c.post(self.url, data)
        inv = Invoice.objects.get(pk=self.inv.pk)
        self.assertEqual(sorted(inv.line_items.values_list('description', flat=True)), ['Labour', 'Travel'])
        self.assertFalse(InvoiceLineItem.objects.filter(pk=self.l2.pk).exists())
        self.assertEqual(inv.subtotal, Decimal('340'))

    def test_the_last_row_blanked_clears_every_line(self):
        data = self._full()
        data.update(self._lines(('', '', '1', '0')))
        self.c.post(self.url, data)
        self.assertEqual(self.inv.line_items.count(), 0)

    def test_blank_optional_fields_clear(self):
        data = self._full()
        data.update(due_date='', description='', notes='')
        self.c.post(self.url, data)
        inv = Invoice.objects.get(pk=self.inv.pk)
        self.assertIsNone(inv.due_date)
        self.assertEqual((inv.description, inv.notes), ('', ''))
        self.assertEqual(inv.currency, 'EUR')  # a blank currency is not "USD"

    def test_status_change_is_kept_with_lines_and_totals(self):
        total = Invoice.objects.get(pk=self.inv.pk).total
        data = self._full()
        data['status'] = 'sent'
        self.c.post(self.url, data)
        inv = Invoice.objects.get(pk=self.inv.pk)
        self.assertEqual(inv.status, 'sent')
        self.assertEqual(inv.total, total)
        self.assertEqual(inv.line_items.count(), 2)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class QuoteEditTests(_Base):
    def setUp(self):
        super().setUp()
        self.quote = Quote.objects.create(organization=self.org, client_org=self.org, title='Firewall refresh',
                                          description='Two sites', status='sent', tax_rate=Decimal('0.05'),
                                          valid_until=date.today() + timedelta(days=30))
        QuoteLineItem.objects.create(quote=self.quote, description='Firewall', quantity=2, unit_price=900)
        self.url = reverse('psa:quote_edit', kwargs={'pk': self.quote.pk})

    def test_a_post_without_status_does_not_revert_a_sent_quote_to_draft(self):
        self.c.post(self.url, {'title': 'Firewall refresh'})
        q = Quote.objects.get(pk=self.quote.pk)
        self.assertEqual(q.status, 'sent')
        self.assertEqual(q.description, 'Two sites')
        self.assertEqual(q.tax_rate, Decimal('0.05'))
        self.assertIsNotNone(q.valid_until)
        self.assertEqual(q.line_items.count(), 1)

    def test_a_malformed_line_keeps_the_saved_lines(self):
        r = self.c.post(self.url, {'title': 'Firewall refresh', 'li_description': ['Firewall', 'Install'],
                                   'li_quantity': ['2', 'one'], 'li_unit_price': ['900', '200'],
                                   'tax_rate': 'x'})
        self.assertEqual(r.status_code, 302)
        q = Quote.objects.get(pk=self.quote.pk)
        self.assertEqual(list(q.line_items.values_list('description', flat=True)), ['Firewall'])
        self.assertEqual(q.tax_rate, Decimal('0.05'))

    def test_lines_are_replaced_when_well_formed(self):
        self.c.post(self.url, {'title': 'Firewall refresh', 'li_description': ['Firewall', 'Install'],
                               'li_quantity': ['2', '1'], 'li_unit_price': ['900', '200']})
        self.assertEqual(self.quote.line_items.count(), 2)
