"""
Invoice billing integrity (audit fixes).

1. Ticket invoices never bill the same time entry / expense twice, and under
   a contract with an hours allowance bill only the overage.
2. The approval gate holds on the invoice form, on email, and on the
   recurring generator's auto-push; sent/paid invoices are not rewritable.
3. Editing an invoice keeps each line's source / source_id.
4. charge_invoice reports how many charges it bundled.
"""
import io
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from audit.models import AuditLog
from core.models import Organization, SystemSetting
from psa.models import (
    Charge, Contract, Invoice, InvoiceLineItem, Queue, Ticket, TicketExpense,
    TicketPriority, TicketStatus, TicketTimeEntry, TicketType,
)
from psa.tests._base import TEST_MIDDLEWARE, _enable_psa_for, _enable_psa_global, _setup_seed


class _Base(TestCase):

    def setUp(self):
        _setup_seed()
        _enable_psa_global()
        self.client_org = Organization.objects.create(name='Billco', slug='bi-billco')
        _enable_psa_for(self.client_org)
        self.admin = User.objects.create_superuser('bi_admin', 'a@x.test', 'pw-bi-123')
        self.ticket = Ticket.objects.create(
            organization=self.client_org, subject='Fix printer',
            queue=Queue.objects.first(),
            priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(),
            status=TicketStatus.objects.first(),
        )

    def _client(self):
        c = Client()
        c.force_login(self.admin)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.client_org.id
        s.save()
        return c

    def _entry(self, minutes, *, days_ago=0, notes='work', billable=True):
        start = timezone.now() - timedelta(days=days_ago, minutes=minutes)
        return TicketTimeEntry.objects.create(
            ticket=self.ticket, user=self.admin, started_at=start,
            ended_at=start + timedelta(minutes=minutes),
            duration_minutes=minutes, notes=notes, is_billable=billable)

    def _invoice_ticket(self):
        before = set(Invoice.objects.values_list('pk', flat=True))
        r = self._client().post(f'/psa/invoices/from-ticket/{self.ticket.ticket_number}/')
        self.assertEqual(r.status_code, 302)
        new = Invoice.objects.exclude(pk__in=before)
        return new.first()


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TicketInvoiceDoubleBillingTests(_Base):

    def test_second_invoice_does_not_rebill_time_or_expenses(self):
        Contract.objects.create(
            organization=self.client_org, client_org=self.client_org, name='T&M',
            contract_type='per_incident', status='active',
            start_date=date.today() - timedelta(days=10), hourly_rate=Decimal('100'))
        te = self._entry(60)
        TicketExpense.objects.create(ticket=self.ticket, description='Cable',
                                     amount=Decimal('15'), incurred_on=date.today())
        first = self._invoice_ticket()
        self.assertIsNotNone(first)
        self.assertEqual(first.subtotal, Decimal('115.00'))

        # Nothing new: no second invoice at all.
        self.assertIsNone(self._invoice_ticket())

        # New work after the first invoice: only that is billed.
        te2 = self._entry(30)
        second = self._invoice_ticket()
        self.assertEqual(
            list(second.line_items.values_list('source', 'source_id')),
            [('time', str(te2.pk))])
        self.assertEqual(second.subtotal, Decimal('50.00'))
        self.assertTrue(first.line_items.filter(source_id=str(te.pk)).exists())

    def test_voided_invoice_releases_its_entries(self):
        te = self._entry(60)
        first = self._invoice_ticket()
        Invoice.objects.filter(pk=first.pk).update(status='void')
        again = self._invoice_ticket()
        self.assertIsNotNone(again)
        self.assertTrue(again.line_items.filter(source='time', source_id=str(te.pk)).exists())

    def test_entry_billed_on_project_invoice_not_rebilled_on_ticket(self):
        te = self._entry(60)
        other = Invoice.objects.create(organization=self.client_org, client_org=self.client_org,
                                       title='Elsewhere', invoice_date=date.today())
        InvoiceLineItem.objects.create(invoice=other, description='x', quantity=1,
                                       unit_price=1, source='time', source_id=str(te.pk))
        self.assertIsNone(self._invoice_ticket())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TicketInvoiceBlockHoursTests(_Base):

    def _contract(self, **kw):
        defaults = dict(
            organization=self.client_org, client_org=self.client_org, name='Block 10h',
            contract_type='block_hours', status='active',
            start_date=date.today() - timedelta(days=10),
            total_hours=Decimal('10'), hourly_rate=Decimal('100'),
            overage_rate=Decimal('150'))
        defaults.update(kw)
        return Contract.objects.create(**defaults)

    def _set_used(self, contract, minutes):
        # Set explicitly: the counter is maintained by TicketTimeEntry.save(),
        # which is not what these tests are about.
        Contract.objects.filter(pk=contract.pk).update(hours_used_minutes=minutes)

    def test_time_within_allowance_is_covered_not_charged(self):
        c = self._contract()
        te = self._entry(120)
        self._set_used(c, 120)
        inv = self._invoice_ticket()
        lines = list(inv.line_items.all())
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].unit_price, Decimal('0'))
        self.assertEqual(lines[0].quantity, Decimal('2.00'))
        self.assertEqual(lines[0].source_id, str(te.pk))
        self.assertIn('covered', lines[0].description)
        self.assertEqual(inv.total, Decimal('0'))

    def test_only_overage_billed_at_overage_rate(self):
        c = self._contract()
        early = self._entry(9 * 60, days_ago=2)
        late = self._entry(120, days_ago=1)
        self._set_used(c, 11 * 60)  # 1h over the 10h block
        inv = self._invoice_ticket()
        priced = list(inv.line_items.filter(unit_price__gt=0))
        self.assertEqual(len(priced), 1)
        # The overage is attributed to the latest entry.
        self.assertEqual(priced[0].source_id, str(late.pk))
        self.assertEqual(priced[0].quantity, Decimal('1.00'))
        self.assertEqual(priced[0].unit_price, Decimal('150.00'))
        self.assertEqual(inv.subtotal, Decimal('150.00'))
        covered = inv.line_items.filter(unit_price=0)
        self.assertEqual(sum(l.quantity for l in covered), Decimal('10.00'))
        self.assertTrue(covered.filter(source_id=str(early.pk)).exists())

    def test_overage_falls_back_to_hourly_rate(self):
        c = self._contract(overage_rate=Decimal('0'))
        self._entry(11 * 60)
        self._set_used(c, 11 * 60)
        inv = self._invoice_ticket()
        self.assertEqual(inv.subtotal, Decimal('100.00'))

    def test_overage_billed_once_across_tickets(self):
        c = self._contract()
        self._entry(11 * 60)
        self._set_used(c, 11 * 60)
        self._invoice_ticket()  # bills 1h overage
        other = Ticket.objects.create(
            organization=self.client_org, subject='Other',
            queue=Queue.objects.first(), priority=TicketPriority.objects.first(),
            ticket_type=TicketType.objects.first(), status=TicketStatus.objects.first())
        self.ticket = other
        self._entry(30)
        self._set_used(c, 11 * 60 + 30)
        inv = self._invoice_ticket()
        # Only the new 30 minutes are overage; the earlier hour is not re-billed.
        self.assertEqual(inv.subtotal, Decimal('75.00'))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TicketInvoiceContractTypeTests(_Base):
    """Flat-fee contracts cover ticket time (product decision 2026-10-15)."""

    def _contract(self, contract_type, total_hours='0', **kw):
        return Contract.objects.create(
            organization=self.client_org, client_org=self.client_org,
            name=f'{contract_type} plan', contract_type=contract_type,
            status='active', start_date=date.today() - timedelta(days=10),
            total_hours=Decimal(total_hours), hourly_rate=Decimal('100'), **kw)

    def test_managed_services_without_allowance_covers_time_bills_expenses(self):
        self._contract('managed_services')
        te = self._entry(90)
        exp = TicketExpense.objects.create(ticket=self.ticket, description='Toner',
                                           amount=Decimal('40'), incurred_on=date.today())
        inv = self._invoice_ticket()
        time_lines = inv.line_items.filter(source='time')
        self.assertEqual(time_lines.count(), 1)
        self.assertEqual(time_lines.get().unit_price, Decimal('0'))
        self.assertEqual(time_lines.get().quantity, Decimal('1.50'))
        self.assertEqual(time_lines.get().source_id, str(te.pk))
        exp_line = inv.line_items.get(source='expense')
        self.assertEqual(exp_line.source_id, str(exp.pk))
        self.assertEqual(inv.subtotal, Decimal('40.00'))
        # Covered entries are recorded as invoiced: never billed later.
        self.assertIsNone(self._invoice_ticket())

    def test_retainer_with_allowance_keeps_overage_logic(self):
        c = self._contract('retainer', total_hours='10', overage_rate=Decimal('150'))
        self._entry(11 * 60)
        Contract.objects.filter(pk=c.pk).update(hours_used_minutes=11 * 60)
        inv = self._invoice_ticket()
        self.assertEqual(inv.subtotal, Decimal('150.00'))
        self.assertEqual(
            sum(l.quantity for l in inv.line_items.filter(unit_price=0)), Decimal('10.00'))

    def test_per_incident_bills_hourly(self):
        self._contract('per_incident')
        self._entry(120)
        inv = self._invoice_ticket()
        line = inv.line_items.get()
        self.assertEqual(line.unit_price, Decimal('100.00'))
        self.assertEqual(inv.subtotal, Decimal('200.00'))

    def test_block_hours_without_allowance_bills_hourly(self):
        self._contract('block_hours')
        self._entry(60)
        inv = self._invoice_ticket()
        self.assertEqual(inv.subtotal, Decimal('100.00'))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class InvoiceApprovalGateTests(_Base):

    def _held_invoice(self, **kw):
        defaults = dict(organization=self.client_org, client_org=self.client_org,
                        title='Held', invoice_date=date.today(),
                        requires_approval=True, approval_reason='over threshold')
        defaults.update(kw)
        inv = Invoice.objects.create(**defaults)
        InvoiceLineItem.objects.create(invoice=inv, description='Work', quantity=1,
                                       unit_price=Decimal('500'))
        inv.recompute_totals()
        return inv

    def _form_post(self, inv, **overrides):
        data = {
            'client_org_id': str(self.client_org.pk), 'client_org': str(self.client_org.pk),
            'title': inv.title, 'status': inv.status,
            'invoice_date': inv.invoice_date.isoformat(), 'currency': 'USD',
            'tax_rate': '0', 'notes': '',
        }
        lines = list(inv.line_items.all())
        data['li_id'] = [str(l.pk) for l in lines]
        data['li_description'] = [l.description for l in lines]
        data['li_quantity'] = [str(l.quantity) for l in lines]
        data['li_unit_price'] = [str(l.unit_price) for l in lines]
        data.update(overrides)
        return self._client().post(f'/psa/invoices/{inv.pk}/edit/', data)

    def test_form_cannot_mark_unapproved_invoice_sent_or_paid(self):
        inv = self._held_invoice()
        for status in ('sent', 'paid'):
            self._form_post(inv, status=status)
            inv.refresh_from_db()
            self.assertEqual(inv.status, 'draft')

    def test_form_can_send_after_approval(self):
        inv = self._held_invoice()
        inv.approve(user=self.admin)
        self._form_post(inv, status='sent')
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'sent')
        self.assertIsNotNone(inv.sent_at)

    def test_threshold_flag_blocks_status_on_first_save(self):
        ss = SystemSetting.get_settings()
        ss.invoice_approval_threshold_total = Decimal('1000')
        ss.save()
        self._client().post('/psa/invoices/new/', {
            'client_org_id': str(self.client_org.pk), 'client_org': str(self.client_org.pk),
            'title': 'Big', 'status': 'sent', 'invoice_date': date.today().isoformat(),
            'currency': 'USD', 'tax_rate': '0',
            'li_description': ['Server'], 'li_quantity': ['1'], 'li_unit_price': ['5000'],
        })
        inv = Invoice.objects.get(title='Big')
        self.assertTrue(inv.requires_approval)
        self.assertEqual(inv.status, 'draft')

    def test_editing_total_after_approval_reinstates_hold(self):
        inv = self._held_invoice()
        inv.approve(user=self.admin)
        self._form_post(inv, li_unit_price=['50000'], status='sent')
        inv.refresh_from_db()
        self.assertTrue(inv.requires_approval)
        self.assertIsNone(inv.approved_at)
        self.assertEqual(inv.status, 'draft')

    def test_email_refused_while_approval_pending(self):
        inv = self._held_invoice()
        with mock.patch('psa.pdf.email_invoice', return_value=True) as sent:
            self._client().post(f'/psa/invoices/{inv.pk}/email/',
                                {'recipient': 'ap@billco.test'})
        sent.assert_not_called()
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'draft')

    def test_email_sends_approved_invoice(self):
        inv = self._held_invoice()
        inv.approve(user=self.admin)
        with mock.patch('psa.pdf.email_invoice', return_value=True) as sent:
            self._client().post(f'/psa/invoices/{inv.pk}/email/',
                                {'recipient': 'ap@billco.test'})
        sent.assert_called_once()
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'sent')

    def test_recurring_auto_push_skips_invoices_needing_approval(self):
        ss = SystemSetting.get_settings()
        ss.psa_auto_push_recurring_invoices = True
        ss.invoice_approval_threshold_total = Decimal('100')
        ss.save()
        Contract.objects.create(
            organization=self.client_org, client_org=self.client_org, name='Managed',
            contract_type='managed_services', status='active',
            start_date=date.today() - timedelta(days=30),
            recurring_amount=Decimal('500'), billing_frequency='monthly',
            next_billing_date=date.today())
        from psa.management.commands.psa_generate_recurring_invoices import Command
        pushed = []
        out = io.StringIO()
        with mock.patch.object(Command, '_auto_push',
                               side_effect=lambda inv: pushed.append(inv)):
            call_command('psa_generate_recurring_invoices', stdout=out)
        inv = Invoice.objects.get(source_contract__name='Managed')
        self.assertTrue(inv.requires_approval)
        self.assertEqual(pushed, [])
        self.assertIn('held for approval', out.getvalue())
        self.assertIn(inv.invoice_number, out.getvalue())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class LockedInvoiceEditTests(_Base):

    def _sent_invoice(self):
        inv = Invoice.objects.create(organization=self.client_org, client_org=self.client_org,
                                     title='Sent one', invoice_date=date.today(), status='sent')
        InvoiceLineItem.objects.create(invoice=inv, description='Work', quantity=1,
                                       unit_price=Decimal('200'))
        inv.recompute_totals()
        return inv

    def test_sent_invoice_lines_and_amounts_cannot_be_changed(self):
        inv = self._sent_invoice()
        li = inv.line_items.get()
        self._client().post(f'/psa/invoices/{inv.pk}/edit/', {
            'status': 'sent', 'title': 'Rewritten',
            'li_id': [str(li.pk)], 'li_description': ['Work'],
            'li_quantity': ['1'], 'li_unit_price': ['1'],
        })
        inv.refresh_from_db()
        self.assertEqual(inv.title, 'Sent one')
        self.assertEqual(inv.total, Decimal('200.00'))
        self.assertEqual(inv.line_items.get().unit_price, Decimal('200.00'))

    def test_sent_invoice_can_be_marked_paid_and_is_audited(self):
        inv = self._sent_invoice()
        # What the browser posts: locked inputs are disabled, so only status + notes.
        r = self._client().post(f'/psa/invoices/{inv.pk}/edit/',
                                {'status': 'paid', 'notes': 'cheque 1042'})
        self.assertEqual(r.status_code, 302)
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'paid')
        log = AuditLog.objects.filter(object_type='psa.Invoice', object_id=inv.pk).latest('pk')
        self.assertIn('sent → paid', log.description)
        self.assertEqual(log.extra_data['before']['status'], 'sent')
        self.assertEqual(log.extra_data['after']['status'], 'paid')

    def test_sent_invoice_cannot_return_to_draft(self):
        inv = self._sent_invoice()
        self._client().post(f'/psa/invoices/{inv.pk}/edit/', {'status': 'draft'})
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'sent')

    def test_locked_form_renders_read_only(self):
        inv = self._sent_invoice()
        r = self._client().get(f'/psa/invoices/{inv.pk}/edit/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context['locked'])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class InvoiceEditProvenanceTests(_Base):

    def test_edit_preserves_source_of_existing_lines(self):
        te = self._entry(60)
        inv = Invoice.objects.create(organization=self.client_org, client_org=self.client_org,
                                     title='Prov', invoice_date=date.today())
        time_line = InvoiceLineItem.objects.create(
            invoice=inv, description='Time: work', quantity=1, unit_price=100,
            source='time', source_id=str(te.pk), is_taxable=False, gl_account_code='4000')
        drop = InvoiceLineItem.objects.create(invoice=inv, description='Drop me',
                                              quantity=1, unit_price=5)
        inv.recompute_totals()
        r = self._client().post(f'/psa/invoices/{inv.pk}/edit/', {
            'client_org_id': str(self.client_org.pk), 'client_org': str(self.client_org.pk),
            'title': 'Prov', 'status': 'draft', 'invoice_date': date.today().isoformat(),
            'currency': 'USD', 'tax_rate': '0',
            'li_id': [str(time_line.pk), ''],
            'li_description': ['Time: onsite work', 'New thing'],
            'li_quantity': ['1.5', '1'],
            'li_unit_price': ['100', '20'],
        })
        self.assertEqual(r.status_code, 302)
        time_line.refresh_from_db()
        self.assertEqual(time_line.source, 'time')
        self.assertEqual(time_line.source_id, str(te.pk))
        self.assertEqual(time_line.description, 'Time: onsite work')
        self.assertEqual(time_line.quantity, Decimal('1.50'))
        self.assertFalse(time_line.is_taxable)
        self.assertEqual(time_line.gl_account_code, '4000')
        self.assertFalse(InvoiceLineItem.objects.filter(pk=drop.pk).exists())
        new = inv.line_items.exclude(pk=time_line.pk).get()
        self.assertEqual((new.source, new.source_id), ('manual', ''))
        # Edited time is still recognised as billed.
        self.assertIsNone(self._invoice_ticket())

    def test_foreign_line_id_is_not_hijacked(self):
        other = Invoice.objects.create(organization=self.client_org, client_org=self.client_org,
                                       title='Other', invoice_date=date.today())
        foreign = InvoiceLineItem.objects.create(invoice=other, description='Theirs',
                                                 quantity=1, unit_price=9,
                                                 source='time', source_id='999')
        inv = Invoice.objects.create(organization=self.client_org, client_org=self.client_org,
                                     title='Mine', invoice_date=date.today())
        self._client().post(f'/psa/invoices/{inv.pk}/edit/', {
            'client_org_id': str(self.client_org.pk), 'client_org': str(self.client_org.pk),
            'title': 'Mine', 'status': 'draft', 'invoice_date': date.today().isoformat(),
            'li_id': [str(foreign.pk)], 'li_description': ['Mine now'],
            'li_quantity': ['1'], 'li_unit_price': ['1'],
        })
        foreign.refresh_from_db()
        self.assertEqual(foreign.invoice_id, other.pk)
        self.assertEqual(foreign.description, 'Theirs')
        self.assertEqual(inv.line_items.get().source, 'manual')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ChargeInvoiceMessageTests(_Base):

    def test_message_reports_bundled_count(self):
        for amt in ('10', '20', '5'):
            Charge.objects.create(organization=self.client_org, client_org=self.client_org,
                                  description=f'c{amt}', amount=Decimal(amt),
                                  charge_date=date.today())
        r = self._client().post(f'/psa/clients/{self.client_org.pk}/charge/invoice/', follow=True)
        msgs = [str(m) for m in r.context['messages']]
        self.assertTrue(any('Bundled 3 item(s)' in m for m in msgs), msgs)
        self.assertEqual(Charge.objects.filter(invoiced=True).count(), 3)
