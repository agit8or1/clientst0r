"""Contract terms, the e-signature rule (contracts that are not
month-to-month, and every quote) and viewed tracking for quote and invoice
links (psa.contract_terms, psa.Contract.esign_status, psa.doc_views)."""
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import Client, TestCase, override_settings

from core.models import Organization, SystemSetting
from psa import contract_terms as terms
from psa.contract_terms import ESignatureRequired
from psa.models import (ClientPSASettings, Contract, DocumentView, Invoice, InvoiceLineItem, Quote,
                        QuoteLineItem, QuoteSignature)

from ._base import TEST_MIDDLEWARE, _enable_psa_global, _make_msp_tech, _setup_seed

BROWSER = {
    'HTTP_USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/131.0 Safari/537.36',
    'HTTP_ACCEPT_LANGUAGE': 'en-US,en;q=0.9',
    'HTTP_SEC_FETCH_MODE': 'cors',
    'HTTP_SEC_FETCH_SITE': 'same-origin',
}
PNG = ('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9'
       'awAAAABJRU5ErkJggg==')


def _staff_client(user, org=None):
    c = Client()
    c.force_login(user)
    s = c.session
    s['2fa_prompted'] = True
    if org is not None:
        s['current_organization_id'] = org.pk
    s.save()
    return c


class TermMappingTests(TestCase):

    def test_infer_from_dates(self):
        d = date(2026, 1, 1)
        self.assertEqual(terms.infer(d, None), ('month_to_month', None))
        self.assertEqual(terms.infer(d, date(2026, 12, 31)), ('annual', 12))
        self.assertEqual(terms.infer(d, date(2028, 12, 31)), ('multi_year', 36))
        self.assertEqual(terms.infer(d, date(2026, 6, 30)), ('fixed', 6))
        self.assertEqual(terms.infer(d, date(2027, 6, 30)), ('fixed', 18))

    def test_normalize_and_errors(self):
        self.assertEqual(terms.normalize('annual', 7), ('annual', 12))
        self.assertEqual(terms.normalize('month_to_month', 12), ('month_to_month', None))
        self.assertEqual(terms.normalize('multi_year', None), ('multi_year', 36))
        self.assertEqual(terms.normalize('bogus', 3), ('month_to_month', None))
        self.assertTrue(terms.term_errors('fixed', None))
        self.assertTrue(terms.term_errors('multi_year', 12))
        self.assertEqual(terms.term_errors('annual', None), [])

    def test_upgrade_migration_maps_and_grandfathers(self):
        import importlib
        from django.apps import apps
        mig = importlib.import_module('psa.migrations.0099_contract_terms_esign_doc_views')
        msp = Organization.objects.create(name='MSP', slug='mig-msp')
        cust = Organization.objects.create(name='Cust', slug='mig-cust')
        # Rows as they were before the upgrade (no term, no fingerprint);
        # written with update() so the new save() rule does not apply.
        open_ended = Contract.objects.create(organization=msp, client_org=cust, name='Open',
                                             start_date=date(2025, 1, 1), status='draft')
        yearly = Contract.objects.create(organization=msp, client_org=cust, name='Year',
                                         start_date=date(2025, 1, 1), end_date=date(2025, 12, 31), status='draft',
                                         billing_frequency='monthly', recurring_amount=Decimal('500'))
        Contract.objects.filter(pk=yearly.pk).update(status='active')
        mig.map_existing_contracts(apps, None)
        open_ended.refresh_from_db()
        yearly.refresh_from_db()
        self.assertEqual((open_ended.term_type, open_ended.term_months), ('month_to_month', None))
        self.assertEqual((yearly.term_type, yearly.term_months), ('annual', 12))
        # billing untouched, and still billable
        self.assertEqual((yearly.status, yearly.recurring_amount), ('active', Decimal('500.00')))
        st = yearly.esign_status(for_billing=True)
        self.assertTrue(st['satisfied'])
        self.assertEqual(st['basis'], 'legacy')
        # a change to the commercial terms ends the grandfathering
        yearly.recurring_amount = Decimal('650')
        yearly.save()
        self.assertFalse(yearly.esign_status(for_billing=True)['satisfied'])


class ContractESignTests(TestCase):

    def setUp(self):
        _enable_psa_global()
        self.msp = Organization.objects.create(name='MSP', slug='es-msp')
        self.cust = Organization.objects.create(name='Acme', slug='es-acme')

    def _contract(self, **kw):
        defaults = dict(organization=self.msp, client_org=self.cust, name='Agreement', status='draft',
                        start_date=date.today() - timedelta(days=1), billing_frequency='monthly',
                        recurring_amount=Decimal('1000'), next_billing_date=date.today())
        defaults.update(kw)
        return Contract.objects.create(**defaults)

    def test_month_to_month_activates_and_bills_without_signature(self):
        c = self._contract(term_type='month_to_month', status='active')
        self.assertEqual(c.esign_status()['basis'], 'not_required')
        inv = c.generate_invoice(on_date=date.today())
        self.assertIsNotNone(inv)
        self.assertEqual(inv.total, Decimal('1000.00'))

    def test_fixed_term_cannot_be_created_active_or_activated(self):
        with self.assertRaises(ESignatureRequired):
            self._contract(term_type='annual', status='active')
        c = self._contract(term_type='annual')
        c.status = 'active'
        with self.assertRaises(ESignatureRequired):
            c.save()
        self.assertEqual(Contract.objects.get(pk=c.pk).status, 'draft')

    def test_fixed_term_is_not_billed_by_any_path(self):
        c = self._contract(term_type='multi_year', term_months=36)
        Contract.objects.filter(pk=c.pk).update(status='active')  # e.g. activated before a later change
        c.refresh_from_db()
        with self.assertRaises(ESignatureRequired):
            c.generate_invoice(on_date=date.today())
        out = StringIO()
        with self.assertRaises(CommandError) as cm:
            call_command('psa_generate_recurring_invoices', '--no-catch-up', stdout=out)
        self.assertIn('not billed until the customer signs', str(cm.exception))
        self.assertFalse(Invoice.objects.filter(source_contract=c).exists())
        from psa.billing.consolidated import contract_fee_status
        self.assertIn('e-signature', contract_fee_status(c).reason)

    def test_exemption_setting(self):
        s = SystemSetting.get_settings()
        running = self._contract(term_type='month_to_month', status='active')
        s.contracts_esign_exempt_month_to_month = False
        s.save()
        with self.assertRaises(ESignatureRequired):
            self._contract(term_type='month_to_month', status='active', name='New')
        # billing that was already running is not stopped by the switch
        self.assertIsNotNone(running.generate_invoice(on_date=date.today()))

    def test_renewal_inherits_the_accepted_terms(self):
        c = self._contract(term_type='annual', term_months=12, auto_renew=True,
                           start_date=date.today() - timedelta(days=400),
                           end_date=date.today() - timedelta(days=35))
        Contract.objects.filter(pk=c.pk).update(status='active', legacy_terms_hash=terms.terms_hash(c))
        call_command('psa_auto_renew_contracts', stdout=StringIO())
        new = Contract.objects.get(parent_contract=c)
        self.assertEqual((new.status, new.term_type, new.term_months), ('active', 'annual', 12))
        self.assertEqual(new.esign_status()['basis'], 'renewal')

    def test_renewal_of_unaccepted_terms_is_skipped(self):
        c = self._contract(term_type='annual', auto_renew=True, start_date=date.today() - timedelta(days=400),
                           end_date=date.today() - timedelta(days=35))
        Contract.objects.filter(pk=c.pk).update(status='active')
        out = StringIO()
        call_command('psa_auto_renew_contracts', stdout=out)
        self.assertIn('Not renewing', out.getvalue())
        self.assertFalse(Contract.objects.filter(parent_contract=c).exists())

    @override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
    def test_form_refuses_activation_without_signature(self):
        _setup_seed()
        staff = _make_msp_tech(User.objects.create_superuser('es-boss', 'b@msp.test', 'pw'))
        cl = _staff_client(staff, self.msp)
        c = self._contract(term_type='month_to_month')
        r = cl.post(f'/psa/contracts/{c.pk}/edit/', {'name': 'Agreement', 'client_org': self.cust.pk,
                                                     'client_org_id': self.msp.pk, 'status': 'active',
                                                     'term_type': 'annual', 'start_date': str(c.start_date)},
                    follow=True)
        self.assertEqual(r.status_code, 200)
        c.refresh_from_db()
        self.assertEqual((c.term_type, c.status), ('annual', 'draft'))
        self.assertContains(r, 'Not activated')
        # month-to-month activates
        cl.post(f'/psa/contracts/{c.pk}/edit/', {'name': 'Agreement', 'client_org': self.cust.pk,
                                                 'client_org_id': self.msp.pk, 'status': 'active',
                                                 'term_type': 'month_to_month'})
        c.refresh_from_db()
        self.assertEqual(c.status, 'active')
        self.assertEqual(cl.get(f'/psa/contracts/{c.pk}/').status_code, 200)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class QuoteESignTests(TestCase):

    def setUp(self):
        _enable_psa_global()
        _setup_seed()
        cache.clear()
        self.msp = Organization.objects.create(name='MSP', slug='q-msp')
        self.cust = Organization.objects.create(name='Acme', slug='q-acme')
        self.staff = _make_msp_tech(User.objects.create_superuser('q-tech', 'tech@msp.test', 'pw'))
        self.quote = Quote.objects.create(organization=self.msp, client_org=self.cust, title='Firewall',
                                          status='sent', created_by=self.staff)
        QuoteLineItem.objects.create(quote=self.quote, description='Firewall', quantity=1,
                                     unit_price=Decimal('900'))
        self.quote.recompute_totals()

    def _sign(self, quote=None):
        quote = quote or self.quote
        r = Client(**BROWSER).post(f'/portal/quote/{quote.customer_token}/sign/', {
            'signed_by_name': 'Pat Lee', 'signed_by_email': 'pat@acme.test', 'signature_data': PNG,
            'content_hash': quote.content_hash()})
        self.assertEqual(r.status_code, 200)

    def test_no_acceptance_or_conversion_without_signature(self):
        with self.assertRaises(ESignatureRequired):
            self.quote.mark_accepted(user=self.staff, create_ticket=False)
        with self.assertRaises(ESignatureRequired):
            self.quote.convert_to_project(user=self.staff)
        self.quote.refresh_from_db()
        self.quote.status = 'accepted'
        with self.assertRaises(ESignatureRequired):
            self.quote.save()

    def test_staff_views_cannot_accept_for_the_customer(self):
        cl = _staff_client(self.staff, self.msp)
        r = cl.post(f'/psa/quotes/{self.quote.pk}/accept/', {'create_project': 'on'}, follow=True)
        self.assertContains(r, 'has not signed')
        r = cl.post(f'/psa/quotes/{self.quote.pk}/edit/', {'title': 'Firewall', 'client_org': self.cust.pk,
                                                           'client_org_id': self.msp.pk, 'status': 'accepted'})
        self.quote.refresh_from_db()
        self.assertEqual(self.quote.status, 'sent')
        self.assertIsNone(self.quote.converted_project)
        page = cl.get(f'/psa/quotes/{self.quote.pk}/')
        self.assertContains(page, 'Customer progress')
        self.assertNotContains(page, 'Mark accepted')

    def test_customer_signature_accepts(self):
        self._sign()
        self.quote.refresh_from_db()
        self.assertEqual(self.quote.status, 'accepted')
        self.assertTrue(self.quote.esign_status()['satisfied'])
        self.assertIsNotNone(self.quote.convert_to_project(user=self.staff))

    def test_changed_document_needs_a_new_signature(self):
        self._sign()
        QuoteSignature.objects.filter(quote=self.quote).update(content_hash='0' * 64)
        self.quote.refresh_from_db()
        st = self.quote.esign_status()
        self.assertFalse(st['satisfied'])
        self.assertIn('changed after it was signed', st['message'])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, WEBHOOK_DELIVERY_ASYNC=False)
class QuoteViewTrackingTests(TestCase):

    def setUp(self):
        _enable_psa_global()
        cache.clear()
        mail.outbox = []
        self.msp = Organization.objects.create(name='MSP', slug='v-msp')
        self.cust = Organization.objects.create(name='Acme', slug='v-acme')
        self.owner = _make_msp_tech(User.objects.create_user('v-owner', 'owner@msp.test', 'pw'))
        self.quote = Quote.objects.create(organization=self.msp, client_org=self.cust, title='Laptops',
                                          status='sent', created_by=self.owner)
        self.sign_url = f'/portal/quote/{self.quote.customer_token}/sign/'
        self.seen_url = f'/portal/quote/{self.quote.customer_token}/seen/'

    def _page(self, client):
        r = client.get(self.sign_url)
        self.assertEqual(r.status_code, 200)
        return r.context['view_nonce']

    def test_bare_get_records_nothing(self):
        cl = Client(**BROWSER)
        r = cl.get(self.sign_url)
        self.assertContains(r, 'data-doc-view-url')
        self.quote.refresh_from_db()
        self.assertEqual(self.quote.view_count, 0)
        self.assertFalse(DocumentView.objects.exists())

    def test_beacon_records_first_last_and_count(self):
        cl = Client(**BROWSER)
        with mock.patch('core.webhook_events.fire') as fire:
            n1 = self._page(cl)
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(cl.post(self.seen_url, {'nonce': n1, 'interacted': '1'}).status_code, 204)
            # the same page load again counts once
            cl.post(self.seen_url, {'nonce': n1, 'interacted': '1'})
            self.quote.refresh_from_db()
            self.assertEqual(self.quote.view_count, 1)
            first = self.quote.first_viewed_at
            self.assertIsNotNone(first)
            n2 = self._page(cl)
            cl.post(self.seen_url, {'nonce': n2, 'interacted': '1'})
        self.quote.refresh_from_db()
        self.assertEqual(self.quote.view_count, 2)
        self.assertEqual(self.quote.first_viewed_at, first)
        self.assertGreaterEqual(self.quote.last_viewed_at, first)
        row = DocumentView.objects.get(doc_type='quote', object_id=self.quote.pk)
        self.assertEqual((row.viewer_key, row.view_count), ('link', 2))
        events = [c.args[0] for c in fire.call_args_list]
        self.assertEqual(events, ['quote.viewed'])
        # the owner is told once, by e-mail
        self.assertEqual(len([m for m in mail.outbox if 'owner@msp.test' in m.to]), 1)
        # nothing else about the quote changed
        self.assertEqual(self.quote.status, 'sent')
        from audit.models import AuditLog
        self.assertTrue(AuditLog.objects.filter(object_type='psa.Quote', object_id=self.quote.pk,
                                                action='read').exists())

    def test_ignored_requests(self):
        n = self._page(Client(**BROWSER))
        cases = {
            'no interaction': (Client(**BROWSER), {'nonce': n}),
            'bot': (Client(**{**BROWSER, 'HTTP_USER_AGENT': 'Mozilla/5.0 (compatible; SafeLinks scanner)'}),
                    {'nonce': n, 'interacted': '1'}),
            'bad nonce': (Client(**BROWSER), {'nonce': 'forged', 'interacted': '1'}),
        }
        for name, (cl, data) in cases.items():
            with self.subTest(name):
                self.assertEqual(cl.post(self.seen_url, data).status_code, 204)
        self.assertNotEqual(Client(**BROWSER).head(self.seen_url).status_code, 204)
        self.assertEqual(Client(**BROWSER).get(self.seen_url).status_code, 405)
        staff = _staff_client(_make_msp_tech(User.objects.create_superuser('v-boss', 'x@msp.test', 'pw')))
        staff.post(self.seen_url, {'nonce': n, 'interacted': '1'}, **BROWSER)
        self.quote.refresh_from_db()
        self.assertEqual(self.quote.view_count, 0)
        self.assertFalse(DocumentView.objects.exists())

    def test_cross_quote_nonce_and_unknown_token(self):
        other = Quote.objects.create(organization=self.msp, client_org=self.cust, title='Other', status='sent')
        from psa import doc_views
        n_other = doc_views.nonce('quote', other.pk)
        cl = Client(**BROWSER)
        self.assertEqual(cl.post(self.seen_url, {'nonce': n_other, 'interacted': '1'}).status_code, 204)
        self.assertEqual(cl.post('/portal/quote/not-a-token/seen/', {'nonce': n_other, 'interacted': '1'})
                         .status_code, 204)
        self.assertFalse(DocumentView.objects.exists())

    def test_list_badge_and_progress(self):
        cl = Client(**BROWSER)
        cl.post(self.seen_url, {'nonce': self._page(cl), 'interacted': '1'})
        boss = _staff_client(_make_msp_tech(User.objects.create_superuser('v-boss2', 'y@msp.test', 'pw')),
                             self.msp)
        self.assertContains(boss.get('/psa/quotes/'), 'Viewed')
        page = boss.get(f'/psa/quotes/{self.quote.pk}/')
        self.assertContains(page, 'Link holder (identity not verified)')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class InvoiceViewTrackingTests(TestCase):

    def setUp(self):
        _enable_psa_global()
        cache.clear()
        from accounts.models import Membership, Role, RoleTemplate
        self.acme = Organization.objects.create(name='Acme', slug='iv-acme')
        self.globex = Organization.objects.create(name='Globex', slug='iv-globex')
        role = RoleTemplate.objects.create(name='Billing (iv test)', portal_billing_contact=True)
        for o in (self.acme, self.globex):
            ClientPSASettings.objects.create(organization=o, portal_enabled=True, enabled=True)
        self.alice = User.objects.create_user('iv-alice', 'alice@acme.test', 'pw', first_name='Alice')
        Membership.objects.create(user=self.alice, organization=self.acme, role=Role.READONLY,
                                  role_template=role, is_active=True)
        self.inv_a = self._invoice(self.acme)
        self.inv_b = self._invoice(self.globex)

    @staticmethod
    def _invoice(org):
        inv = Invoice.objects.create(organization=org, client_org=org, title='Managed services',
                                     invoice_date=date.today(), status='sent', currency='USD')
        InvoiceLineItem.objects.create(invoice=inv, description='Monthly', quantity=1, unit_price=Decimal('100'))
        inv.recompute_totals()
        return inv

    def _alice(self):
        c = Client(**BROWSER)
        c.force_login(self.alice)
        s = c.session
        s['2fa_prompted'] = True
        s.save()
        return c

    def test_portal_view_recorded_per_user(self):
        cl = self._alice()
        r = cl.get(f'/portal/billing/invoices/{self.inv_a.pk}/')
        self.assertEqual(r.status_code, 200)
        total = self.inv_a.total
        self.assertEqual(cl.post(f'/portal/billing/invoices/{self.inv_a.pk}/seen/',
                                 {'nonce': r.context['view_nonce'], 'interacted': '1'}).status_code, 204)
        self.inv_a.refresh_from_db()
        self.assertEqual(self.inv_a.view_count, 1)
        self.assertEqual((self.inv_a.total, self.inv_a.status), (total, 'sent'))
        row = DocumentView.objects.get(doc_type='invoice', object_id=self.inv_a.pk)
        self.assertEqual(row.viewer_user, self.alice)
        self.assertIn('alice@acme.test', row.viewer_label)

    def test_other_customer_invoice_refused_silently(self):
        from psa import doc_views
        cl = self._alice()
        r = cl.post(f'/portal/billing/invoices/{self.inv_b.pk}/seen/',
                    {'nonce': doc_views.nonce('invoice', self.inv_b.pk), 'interacted': '1'})
        self.assertEqual(r.status_code, 204)
        self.assertEqual(cl.get(f'/portal/billing/invoices/{self.inv_b.pk}/').status_code, 404)
        self.inv_b.refresh_from_db()
        self.assertEqual(self.inv_b.view_count, 0)
        anon = Client(**BROWSER).post(f'/portal/billing/invoices/{self.inv_a.pk}/seen/',
                                      {'nonce': doc_views.nonce('invoice', self.inv_a.pk), 'interacted': '1'})
        self.assertEqual(anon.status_code, 204)
        self.assertFalse(DocumentView.objects.exists())

    def test_staff_list_badge(self):
        DocumentView.objects.create(doc_type='invoice', object_id=self.inv_a.pk, client_org=self.acme,
                                    viewer_key=f'user:{self.alice.pk}', viewer_label='Alice')
        Invoice.objects.filter(pk=self.inv_a.pk).update(view_count=1, first_viewed_at=self.inv_a.created_at)
        boss = _staff_client(_make_msp_tech(User.objects.create_superuser('iv-boss', 'z@msp.test', 'pw')))
        self.assertContains(boss.get('/psa/invoices/'), 'fa-eye')
        self.assertContains(boss.get(f'/psa/invoices/{self.inv_a.pk}/'), 'Customer progress')
