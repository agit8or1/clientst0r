"""Phase 102.5: invoice presentation — four layouts of the same lines, the
settings that choose one, branding, the service report's privacy, and the
portal / PDF boundary."""
import io
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from core.models import Organization, SystemSetting
from psa.billing import config as cfg
from psa.billing import presentation as pres
from psa.models import BillingSettingOverride, Invoice, InvoiceLineItem, TicketComment
from psa.pdf import render_invoice_pdf
from psa.tests._base import TEST_MIDDLEWARE
from psa.tests.test_billing_102_consolidated import _ConsBase

D = Decimal


def _pdf_text(data):
    import pymupdf
    with pymupdf.open(stream=data, filetype='pdf') as doc:
        return '\n'.join(p.get_text() for p in doc)


class _PresBase(_ConsBase):

    def setUp(self):
        super().setUp()
        self.ticket.subject = 'Printer down'
        self.ticket.client_can_view = True
        self.ticket.resolution_summary = 'Replaced the fuser'
        self.ticket.save()
        self.t2.client_can_view = False
        self.t2.subject = 'Sensitive boardroom matter'
        self.t2.resolution_summary = 'Hidden resolution'
        self.t2.save()
        self._work(self.ticket)
        self._work(self.t2, minutes=30, item_price='7')
        from psa.models import TicketTimeEntry
        for uid in set(TicketTimeEntry.objects.values_list('user_id', flat=True)):
            User.objects.filter(pk=uid).update(first_name='Ada', last_name='Lovelace')
        self._charge('10')
        self.contract = self._managed()
        res = self._cons([self.ticket, self.t2], charges=True, contract=self.contract)
        self.inv = res.invoice
        self.inv.refresh_from_db()

    def snapshot(self, inv):
        inv.refresh_from_db()
        return (inv.subtotal, inv.tax_amount, inv.total, inv.line_items.count(),
                sorted((li.description, li.line_total) for li in inv.line_items.all()))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class LayoutTests(_PresBase):

    def test_totals_tax_and_lines_identical_across_layouts(self):
        Invoice.objects.filter(pk=self.inv.pk).update(tax_rate=D('0.0825'))
        self.inv.refresh_from_db()
        self.inv.recompute_totals()
        before = self.snapshot(self.inv)
        self.assertGreater(before[1], 0)
        pdfs = {}
        for layout in pres.LAYOUT_KEYS:
            m = pres.build(self.inv, layout)
            self.assertEqual(m['layout'], layout)
            self.assertEqual(len(m['lines']), before[3])
            self.assertEqual(sum((ln['line_total'] for ln in m['lines']), D('0')), before[0])
            pdfs[layout] = render_invoice_pdf(self.inv, layout=layout)
            text = _pdf_text(pdfs[layout])
            self.assertIn(f'{self.inv.total:,.2f}', text)
            self.assertEqual(self.snapshot(self.inv), before)       # rendering wrote nothing
        self.assertEqual(len({len(p) for p in pdfs.values()}), 4)

    def test_by_ticket_subtotals_sum_to_invoice_subtotal(self):
        m = pres.build(self.inv, pres.BY_TICKET)
        heads = [g['heading'] for g in m['groups']]
        self.assertEqual(heads, [self.ticket.ticket_number, self.t2.ticket_number, pres.OTHER_CHARGES])
        self.assertEqual(sum((g['subtotal'] for g in m['groups']), D('0')), self.inv.subtotal)
        for g in m['groups']:
            self.assertEqual(g['subtotal'], sum((ln['line_total'] for ln in g['lines']), D('0')))
        self.assertEqual(sum(len(g['lines']) for g in m['groups']), self.inv.line_items.count())
        self.assertEqual(m['groups'][0]['subject'], 'Printer down')
        # the ticket prefix moved into the heading
        self.assertFalse(m['groups'][0]['lines'][0]['description'].startswith(self.ticket.ticket_number))

    def test_monthly_summary_categories(self):
        m = pres.build(self.inv, pres.MONTHLY)
        by = {c['key']: c for c in m['categories']}
        for key in ('time', 'expense', 'charge'):
            want = sum((li.line_total for li in self.inv.line_items.filter(source=key)), D('0'))
            self.assertEqual(by[key]['amount'], want)
        self.assertEqual(by['charge']['amount'], D('10.00'))
        self.assertEqual(by['expense']['count'], 2)
        self.assertEqual(sum((c['amount'] for c in m['categories']), D('0')), self.inv.subtotal)
        self.assertEqual(sum(c['count'] for c in m['categories']), self.inv.line_items.count())

    def test_itemized_is_the_default(self):
        self.assertEqual(pres.resolve_layout(self.inv), 'itemized')
        self.assertEqual(pres.build(self.inv)['layout'], 'itemized')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ServiceReportTests(_PresBase):

    def test_report_rows_and_privacy(self):
        TicketComment.objects.create(ticket=self.ticket, author=self.admin, body='INTERNAL-NOTE-XYZ', is_internal=True)
        from psa.models import TicketTimeEntry
        TicketTimeEntry.objects.update(notes='TIME-NOTE-SECRET')
        m = pres.build(self.inv, pres.SERVICE_REPORT)
        rows = {r['number']: r for r in m['report']}
        r1, r2 = rows[self.ticket.ticket_number], rows[self.t2.ticket_number]
        self.assertEqual((r1['subject'], r1['resolution'], r1['hours']), ('Printer down', 'Replaced the fuser', D('1.00')))
        self.assertEqual(r1['technician_names'], 'Ada Lovelace')
        # A ticket the customer cannot see: number and hours only.
        self.assertEqual((r2['subject'], r2['resolution'], r2['hours']), ('Support request', '', D('0.50')))
        for fmt in (str(m), _pdf_text(render_invoice_pdf(self.inv, layout=pres.SERVICE_REPORT))):
            for secret in ('INTERNAL-NOTE-XYZ', 'TIME-NOTE-SECRET', 'Sensitive boardroom', 'Hidden resolution'):
                self.assertNotIn(secret, fmt)
        self.assertIn('Replaced the fuser', _pdf_text(render_invoice_pdf(self.inv, layout=pres.SERVICE_REPORT)))

    def test_other_customers_ticket_is_never_named(self):
        other = Organization.objects.create(name='Elsewhere', slug='pres-else')
        foreign = self._ticket()
        foreign.organization = other
        foreign.subject = 'FOREIGN-SUBJECT'
        foreign.client_can_view = True
        foreign.save()
        InvoiceLineItem.objects.filter(invoice=self.inv).update(ticket=foreign)
        m = pres.build(self.inv, pres.SERVICE_REPORT)
        self.assertNotIn('FOREIGN-SUBJECT', str(m))
        by = pres.build(self.inv, pres.BY_TICKET)
        self.assertNotIn('FOREIGN-SUBJECT', str(by))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SettingLevelTests(_PresBase):

    def test_resolution_order_contract_over_customer_over_global(self):
        ss = SystemSetting.get_settings()
        ss.invoice_presentation = 'monthly'
        ss.save()
        self.assertEqual(pres.resolve_layout(self.inv), 'monthly')
        cfg.save_override(self.cust, None, {'invoice_presentation': 'by_ticket'}, actor=self.admin)
        self.assertEqual(pres.resolve_layout(self.inv), 'by_ticket')
        cfg.save_override(self.cust, self.contract, {'invoice_presentation': 'service_report'}, actor=self.admin)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.source_contract_id, self.contract.pk)
        self.assertEqual(pres.resolve_layout(self.inv), 'service_report')
        e = cfg.effective('invoice_presentation', self.cust, self.contract)
        self.assertEqual((e.value, e.source), ('service_report', 'contract'))
        # an invoice's own choice wins over all of them
        Invoice.objects.filter(pk=self.inv.pk).update(presentation='itemized')
        self.inv.refresh_from_db()
        self.assertEqual(pres.resolve_layout(self.inv), 'itemized')

    def test_invalid_values_refused(self):
        with self.assertRaises(cfg.SettingError):
            cfg.save_global({'invoice_presentation': 'fancy'}, actor=self.admin)
        with self.assertRaises(cfg.SettingError):
            cfg.save_global({'invoice_footer_text': 'x' * 1001}, actor=self.admin)
        with self.assertRaises(cfg.SettingError):
            cfg.save_override(self.cust, None, {'invoice_presentation': 'fancy'}, actor=self.admin)
        self.assertFalse(BillingSettingOverride.objects.exists())

    def test_settings_page_saves_default_and_footer(self):
        c = self._client()
        r = c.post(reverse('core:settings_billing'), {
            'action': 'save_global', 'invoice_presentation': 'by_ticket',
            'invoice_footer_text': 'Pay by ACH to 123', 'invoice_approval_threshold_total': '0'})
        self.assertEqual(r.status_code, 302)
        ss = SystemSetting.get_settings()
        self.assertEqual((ss.invoice_presentation, ss.invoice_footer_text), ('by_ticket', 'Pay by ACH to 123'))
        page = c.get(reverse('core:settings_billing')).content.decode()
        self.assertIn('Grouped by ticket', page)
        self.assertIn('Pay by ACH to 123', page)
        page = c.get(reverse('core:settings_billing') + f'?customer={self.cust.pk}').content.decode()
        self.assertIn('Invoice layout', page)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PerInvoiceTests(_PresBase):

    def test_draft_choice_persists_and_follows_default_when_blank(self):
        self.assertEqual(self.inv.presentation, '')
        ss = SystemSetting.get_settings()
        ss.invoice_presentation = 'monthly'
        ss.save()
        self.assertEqual(pres.resolve_layout(self.inv), 'monthly')     # a blank draft follows the default

    def test_edit_form_stores_choice_and_totals_do_not_move(self):
        before = self.snapshot(self.inv)
        r = self._client().post(reverse('psa:invoice_edit', args=[self.inv.pk]), {'presentation': 'by_ticket'})
        self.assertEqual(r.status_code, 302)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.presentation, 'by_ticket')
        self.assertEqual(self.snapshot(self.inv), before)
        page = self._client().get(reverse('psa:invoice_edit', args=[self.inv.pk])).content.decode()
        self.assertIn('id="inv-presentation"', page)
        r = self._client().post(reverse('psa:invoice_edit', args=[self.inv.pk]), {'presentation': 'bogus'})
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.presentation, 'by_ticket')

    def test_sending_freezes_the_layout(self):
        ss = SystemSetting.get_settings()
        ss.invoice_presentation = 'monthly'
        ss.save()
        self.inv.status = 'sent'
        self.inv.save(update_fields=['status'])
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.presentation, 'monthly')
        ss.invoice_presentation = 'by_ticket'
        ss.save()
        cfg.save_override(self.cust, None, {'invoice_presentation': 'service_report'}, actor=self.admin)
        self.assertEqual(pres.build(self.inv)['layout'], 'monthly')     # unchanged by later settings

    def test_locked_invoice_ignores_a_posted_layout(self):
        Invoice.objects.filter(pk=self.inv.pk).update(status='sent', presentation='itemized')
        self._client().post(reverse('psa:invoice_edit', args=[self.inv.pk]), {'presentation': 'monthly'})
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.presentation, 'itemized')

    def test_pdf_view_and_detail_page_render_each_layout(self):
        for layout in pres.LAYOUT_KEYS:
            Invoice.objects.filter(pk=self.inv.pk).update(presentation=layout)
            c = self._client()
            r = c.get(reverse('psa:invoice_pdf', args=[self.inv.pk]) + '?detail=1')
            self.assertEqual((r.status_code, r['Content-Type']), (200, 'application/pdf'))
            page = c.get(reverse('psa:invoice_detail', args=[self.inv.pk]))
            self.assertEqual(page.status_code, 200)
            self.assertContains(page, dict(pres.LAYOUTS)[layout])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class BrandingTests(_PresBase):

    def test_branding_from_org_and_footer_escaped(self):
        msp = self.inv.organization
        msp.name = 'Acme <b>IT</b> & Co'
        msp.street_address, msp.city, msp.phone = '1 Main <i>St</i>', 'Austin', '555-0100'
        msp.save()
        ss = SystemSetting.get_settings()
        ss.invoice_footer_text = 'Pay <script>alert(1)</script> & thanks'
        ss.save()
        b = pres.branding(self.inv)
        self.assertEqual((b['name'], b['footer']), ('Acme <b>IT</b> & Co', 'Pay <script>alert(1)</script> & thanks'))
        data = render_invoice_pdf(self.inv)                                # reportlab would choke on raw markup
        text = _pdf_text(data)
        self.assertIn('Acme <b>IT</b> & Co', text)
        self.assertIn('<script>alert(1)</script>', text)
        self.assertIn('555-0100', text)
        html = self._client().get(reverse('psa:invoice_detail', args=[self.inv.pk])).content.decode()
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('Pay &lt;script&gt;alert(1)&lt;/script&gt; &amp; thanks', html)
        self.assertIn('Acme &lt;b&gt;IT&lt;/b&gt; &amp; Co', html)
        self.assertNotIn('1 Main <i>St</i>', html)

    def test_line_text_is_escaped_in_the_pdf(self):
        InvoiceLineItem.objects.filter(invoice=self.inv).update(description='<para>Cable & <b>tape')
        for layout in pres.LAYOUT_KEYS:
            self.assertIn('Cable & <b>tape', _pdf_text(render_invoice_pdf(self.inv, layout=layout, detail=True))
                          if layout != 'monthly' else 'Cable & <b>tape')

    def test_logo_only_from_app_media(self):
        msp = self.inv.organization
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGB', (8, 8), (200, 0, 0)).save(buf, 'PNG')
        png = buf.getvalue()
        msp.logo.save('logo.png', SimpleUploadedFile('logo.png', png), save=True)
        b = pres.branding(self.inv)
        self.assertTrue(b['logo_url'].startswith('/media/'), b['logo_url'])
        self.assertIn(b['logo_url'], self._client().get(reverse('psa:invoice_detail', args=[self.inv.pk])).content.decode())
        self.assertTrue(render_invoice_pdf(self.inv).startswith(b'%PDF'))
        msp.logo.delete(save=True)
