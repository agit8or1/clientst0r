"""113.9 part B: an invoice draft from approved charges in three clicks,
keeping the confirmation.

Billing Review (one click from the dashboard KPI "Ready to invoice" or the
Billing summary panel) → "Create draft" on the customer (the preview with
every line, coverage and total) → Confirm. The preview and the draft reuse
psa.billing.queue and the existing draft code; these tests compare the new
path against the old one ("tick tickets, Create draft invoices for selected,
confirm dialog") on the same data.
"""
import re
from decimal import Decimal

from django.db import transaction
from django.test import Client, override_settings
from django.urls import reverse

from audit.models import AuditLog
from psa.billing import queue as bq
from psa.billing import ticket_charges as tc
from psa.models import Charge, Invoice
from psa.tests._base import TEST_MIDDLEWARE
from psa.tests.test_billing_queue_102 import _QueueBase
from psa.tests.test_ticket_time_charges_101_5 import _login

D = Decimal


class _Rollback(Exception):
    pass


def _hidden(html, name):
    return re.findall(r'<input type="hidden" name="%s" value="([^"]*)">' % re.escape(name), html)


def _confirm_form(html):
    m = re.search(r'<form method="post" action="([^"]*draft/confirm/)"(.*?)</form>', html, re.S)
    assert m, 'no confirm form'
    body = m.group(2)
    data = {k: _hidden(body, k) for k in ('fingerprint', 'period', 'ticket', 'include_charges',
                                          'csrfmiddlewaretoken')}
    data = {k: (v if k == 'ticket' else (v[0] if v else '')) for k, v in data.items()}
    return m.group(1), {k: v for k, v in data.items() if v not in ('', [])}


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class _DraftBase(_QueueBase):

    def setUp(self):
        super().setUp()
        # Ticket A: prepaid block with overage (1 h covered, 2 h beyond it) and an item.
        self._contract(total_hours=D('1'))
        e = self._entry(180)
        self._approve(e)
        tc.add_item(self.ticket, self.admin, category='materials', description='Cable', unit_price='5')
        self._sent()
        # Ticket B: one item.
        self.ticket_b = self._ticket()
        tc.add_item(self.ticket_b, self.admin, category='materials', description='Patch lead', unit_price='7.5')
        self._sent(self.ticket_b)
        # Account charges: a charge and a credit; the charge is approved.
        self.charge = self._charge('10')
        self._charge('3', is_credit=True)
        bq.decide(self.cust, [f'charge:{self.charge.pk}'], 'approve', actor=self.admin)

    def _snapshot(self, invoices=None):
        qs = invoices if invoices is not None else Invoice.objects.all()
        out = []
        for inv in qs:
            lines = sorted((li.description, li.quantity, li.unit_price, li.source, li.source_id, li.line_total)
                           for li in inv.line_items.all())
            out.append((inv.source_ticket_id, inv.status, inv.subtotal, inv.tax_amount, inv.total, lines))
        return sorted(out, key=repr)

    def _old_path(self):
        """The 102.3 path: tick both tickets and the account charges,
        "Create draft invoices for selected" (after the confirm dialog)."""
        before = set(Invoice.objects.values_list('pk', flat=True))
        r = self._client().post(reverse('psa:billing_queue_draft', args=[self.cust.pk]),
                                {'ticket': [self.ticket.pk, self.ticket_b.pk], 'include_charges': '1'})
        self.assertEqual(r.status_code, 302)
        return self._snapshot(Invoice.objects.exclude(pk__in=before))

    def _three_clicks(self, c=None):
        """The requests a user makes: open Billing Review, Create draft, Confirm."""
        c = c or self._client()
        # Click 1: Billing Review (from the dashboard KPI / Billing summary link).
        r1 = c.get(reverse('psa:billing_review'))
        self.assertEqual(r1.status_code, 200)
        html = r1.content.decode()
        m = re.search(r'href="([^"]*draft/preview/[^"]*)" data-create-draft="%d"' % self.cust.pk, html)
        self.assertIsNotNone(m, 'no Create draft action on the customer row')
        # Click 2: Create draft -> the preview / confirmation page.
        r2 = c.get(m.group(1).replace('&amp;', '&'))
        self.assertEqual(r2.status_code, 200)
        action, data = _confirm_form(r2.content.decode())
        # Click 3: Confirm.
        r3 = c.post(action, dict(data, mode='separate'))
        return r1, r2, r3


class ThreeClickPathTests(_DraftBase):

    def test_three_requests_create_the_drafts(self):
        before = Invoice.objects.count()
        r1, r2, r3 = self._three_clicks()
        self.assertEqual(r3.status_code, 302)
        self.assertEqual(Invoice.objects.count(), before + 3)     # two tickets + the account charges
        self.assertTrue(all(i.status == 'draft' for i in Invoice.objects.all()))
        self.assertTrue(AuditLog.objects.filter(extra_data__event='billing_queue_draft_confirm').exists())

    def test_list_shows_counts_and_create_draft(self):
        r = self._client().get(reverse('psa:billing_review'))
        g = next(g for g in r.context['ready_queue'] if g.client.pk == self.cust.pk)
        # time (2 lines) + item on A, item on B, two charges = 6 lines; 1 approved.
        self.assertEqual((g.ready_count, g.approved_count), (6, 1))
        self.assertContains(r, '6 lines not invoiced, 1 approved')
        self.assertContains(r, f'data-create-draft="{self.cust.pk}"')

    def test_preview_shows_every_line_coverage_and_totals(self):
        r = self._client().get(reverse('psa:billing_queue_draft_preview', args=[self.cust.pk]))
        p = r.context['preview']
        self.assertEqual(sorted(p.ticket_ids), sorted([self.ticket.pk, self.ticket_b.pk]))
        self.assertEqual(len(p.charges), 2)
        self.assertEqual(p.charges_total, D('7.00'))
        self.assertEqual(p.total, D('300.00') + D('5.00') + D('7.50') + D('7.00'))
        for cov in ('prepaid', 'overage', 'billable', 'credit'):
            self.assertContains(r, f'data-coverage="{cov}"')
        for ln in [ln for t in p.tickets for ln in t.lines] + p.charges:
            self.assertContains(r, ln.description)
        self.assertContains(r, '319.50')
        self.assertFalse(Invoice.objects.exists())     # a preview creates nothing

    def test_golden_new_path_equals_old_path(self):
        try:
            with transaction.atomic():
                old = self._old_path()
                raise _Rollback
        except _Rollback:
            pass
        self.assertFalse(Invoice.objects.exists())
        self.assertEqual(len(old), 3)
        preview = bq.draft_preview(self.admin, self.cust, msp_org=self.cust)
        self._three_clicks()
        new = self._snapshot()
        self.assertEqual(new, old)
        self.assertEqual(sum(s[2] for s in new), preview.total)
        by_ticket = {s[0]: s[2] for s in new}
        for t in preview.tickets:
            self.assertEqual(by_ticket[t.ticket.pk], t.total)
        self.assertEqual(by_ticket[None], preview.charges_total)

    def test_consolidated_confirm_matches_the_preview_total(self):
        c = self._client()
        r = c.get(reverse('psa:billing_queue_draft_preview', args=[self.cust.pk]))
        action, data = _confirm_form(r.content.decode())
        r = c.post(action, dict(data, mode='consolidated'))
        inv = Invoice.objects.get()
        self.assertRedirects(r, reverse('psa:invoice_detail', args=[inv.pk]), fetch_redirect_response=False)
        self.assertEqual(inv.subtotal, D('319.50'))

    def test_double_submit_creates_one_set_of_drafts(self):
        c = self._client()
        r = c.get(reverse('psa:billing_queue_draft_preview', args=[self.cust.pk]))
        action, data = _confirm_form(r.content.decode())
        c.post(action, dict(data, mode='separate'))
        n = Invoice.objects.count()
        r = c.post(action, dict(data, mode='separate'), follow=True)
        self.assertEqual(Invoice.objects.count(), n)
        self.assertEqual(n, 3)
        self.assertTrue(any('Nothing is left' in str(m) for m in r.context['messages']))

    def test_change_after_preview_drafts_nothing(self):
        c = self._client()
        r = c.get(reverse('psa:billing_queue_draft_preview', args=[self.cust.pk]))
        action, data = _confirm_form(r.content.decode())
        tc.add_item(self.ticket_b, self.admin, category='materials', description='Late addition', unit_price='99')
        r = c.post(action, dict(data, mode='separate'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/draft/preview/', r['Location'])
        self.assertFalse(Invoice.objects.exists())
        data['fingerprint'] = 'x' * 64
        c.post(action, dict(data, mode='separate'))
        self.assertFalse(Invoice.objects.exists())

    def test_confirm_is_post_only_and_needs_csrf(self):
        url = reverse('psa:billing_queue_draft_confirm', args=[self.cust.pk])
        self.assertEqual(self._client().get(url).status_code, 405)
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.admin)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.cust.pk
        s.save()
        fp = bq.draft_preview(self.admin, self.cust, msp_org=self.cust).fingerprint
        r = c.post(url, {'fingerprint': fp, 'ticket': [self.ticket.pk], 'mode': 'separate'})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Invoice.objects.exists())

    def test_explicit_selection(self):
        r = self._client().get(reverse('psa:billing_queue_draft_preview', args=[self.cust.pk]),
                               {'sel': '1', 'ticket': [self.ticket_b.pk]})
        p = r.context['preview']
        self.assertEqual((p.ticket_ids, p.charges, p.total), ([self.ticket_b.pk], [], D('7.50')))


class DraftPermissionTests(_DraftBase):

    def _assert_no_draft(self):
        self.assertFalse(Invoice.objects.exists())
        self.assertEqual(Charge.objects.filter(invoiced=True).count(), 0)

    def _steps(self, user):
        c = _login(user, self.cust)
        fp = bq.draft_preview(self.admin, self.cust, msp_org=self.cust).fingerprint
        r = c.get(reverse('psa:billing_review'))
        self._list_location = r.get('Location', '')
        return (r.status_code,
                c.get(reverse('psa:billing_queue_draft_preview', args=[self.cust.pk])).status_code,
                c.post(reverse('psa:billing_queue_draft_confirm', args=[self.cust.pk]),
                       {'fingerprint': fp, 'ticket': [self.ticket.pk, self.ticket_b.pk],
                        'include_charges': '1', 'mode': 'separate'}).status_code)

    def test_no_billing_permission_403_at_each_step(self):
        nobody = self._tech_with()
        list_status, preview_status, confirm_status = self._steps(nobody)
        # The list keeps its existing guard (psa.views.billing_review,
        # @require_admin): a technician with no admin membership is sent to
        # the home page, never shown the queue. The new steps answer 403.
        self.assertIn(list_status, (302, 403))
        if list_status == 302:
            self.assertNotIn('billing-review', self._list_location)
        self.assertEqual((preview_status, confirm_status), (403, 403))
        self._assert_no_draft()

    def test_no_billing_permission_admin_member_403_on_the_list(self):
        from accounts.models import Membership, Role
        nobody = self._tech_with()
        Membership.objects.create(user=nobody, organization=self.cust, role=Role.ADMIN, is_active=True)
        self.assertEqual(self._steps(nobody), (403, 403, 403))
        self._assert_no_draft()

    def test_viewer_sees_the_list_but_cannot_draft(self):
        viewer = self._tech_with(billing_view_invoices=True)
        list_status, preview_status, confirm_status = self._steps(viewer)
        self.assertEqual((preview_status, confirm_status), (403, 403))
        self._assert_no_draft()

    def test_draft_permission_is_enough(self):
        u = self._tech_with(billing_view_invoices=True, billing_send_invoices=True)
        c = _login(u, self.cust)
        r = c.get(reverse('psa:billing_queue_draft_preview', args=[self.cust.pk]))
        self.assertEqual(r.status_code, 200)
        action, data = _confirm_form(r.content.decode())
        self.assertEqual(c.post(action, dict(data, mode='separate')).status_code, 302)
        self.assertEqual(Invoice.objects.count(), 3)

    def test_out_of_scope_customer_is_404(self):
        from core.models import Organization
        other = Organization.objects.create(name='Elsewhere', slug='d-elsewhere')
        u = self._tech_with(scope=[self.cust], billing_view_invoices=True, billing_send_invoices=True)
        c = _login(u, self.cust)
        self.assertEqual(c.get(reverse('psa:billing_queue_draft_preview', args=[other.pk])).status_code, 404)

    def test_customer_user_gets_nothing(self):
        from django.contrib.auth.models import User

        from accounts.models import Membership, Role
        cust = User.objects.create_user('d_cust', 'c@c.test', 'pw')
        Membership.objects.create(user=cust, organization=self.cust, role=Role.ADMIN, is_active=True)
        c = _login(cust, self.cust)
        r = c.get(reverse('psa:billing_queue_draft_preview', args=[self.cust.pk]))
        self.assertIn(r.status_code, (403, 404))
        self._assert_no_draft()


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DashboardEntryTests(_DraftBase):

    def _req(self, user):
        from core.tests.test_dashboard_widgets import _req
        return _req(user, self.cust)

    def test_kpi_links_to_billing_review_with_the_queue_count(self):
        from core import dashboard_widgets as dw
        w = dw.BY_KEY['kpi_ready_to_invoice']
        req = self._req(self.admin)
        self.assertTrue(w.allowed(req))
        out = w.build(req, self.cust)
        self.assertEqual(out['value'], 1)
        self.assertEqual(out['href'], reverse('psa:billing_review') + '#ready-for-billing')
        self.assertIn(str(bq.summary(bq.build_queue(self.admin))['ready_total']), out['sub'])
        self.assertIn('kpi_ready_to_invoice', dw.MSP_ONLY)

    def test_kpi_and_link_hidden_without_billing_permission(self):
        from core import dashboard_widgets as dw
        nobody = self._tech_with()
        self.assertFalse(dw.BY_KEY['kpi_ready_to_invoice'].allowed(self._req(nobody)))
        viewer = self._tech_with(billing_view_invoices=True)
        out = dw.build_billing_summary(self._req(viewer), self.cust)
        self.assertEqual(out['ready_url'] != '', dw.gate_billing_review(self._req(viewer)))

    def test_billing_summary_links_to_ready_for_billing(self):
        from core import dashboard_widgets as dw
        out = dw.build_billing_summary(self._req(self.admin), self.cust)
        self.assertEqual(out['ready_url'], reverse('psa:billing_review') + '#ready-for-billing')
