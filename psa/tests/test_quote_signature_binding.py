"""Quote signatures are bound to the exact quote revision signed: the
signature records a hash of the quote's content (number, client, lines, tax,
totals, validity), a stale page cannot sign changed content, a signed quote
cannot be edited, and the evidence is downloadable and hash-verifiable."""
import hashlib
import io
import json
import zipfile
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from core.models import Organization
from psa.models import Quote, QuoteLineItem, QuoteSignature, SignedQuoteLocked

from ._base import TEST_MIDDLEWARE, _enable_psa_global, _make_msp_tech, _setup_seed

PNG = ('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9'
       'awAAAABJRU5ErkJggg==')


def _sha(b):
    return hashlib.sha256(b).hexdigest()


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class QuoteSignatureBindingTests(TestCase):
    def setUp(self):
        _enable_psa_global()
        _setup_seed()
        self.msp = Organization.objects.create(name='MSP', slug='msp')
        self.client_org = Organization.objects.create(name='Acme', slug='acme')
        self.quote = Quote.objects.create(organization=self.msp, client_org=self.client_org,
                                          title='Firewall refresh', description='Terms: net 30.',
                                          tax_rate=Decimal('0.0800'), status='sent')
        QuoteLineItem.objects.create(quote=self.quote, sort_order=0, description='Firewall',
                                     quantity=Decimal('1'), unit_price=Decimal('1200.00'))
        QuoteLineItem.objects.create(quote=self.quote, sort_order=1, description='Install',
                                     quantity=Decimal('3'), unit_price=Decimal('150'), is_taxable=False)
        self.quote.recompute_totals()
        self.url = f'/portal/quote/{self.quote.customer_token}/sign/'
        self.staff = _make_msp_tech(User.objects.create_superuser('tech', 't@msp.test', 'pw'))
        self.staff_client = Client()
        self.staff_client.force_login(self.staff)
        s = self.staff_client.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.msp.pk  # the quote's MSP tenant
        s.save()

    def _post(self, content_hash, **extra):
        data = {'signed_by_name': 'Pat Lee', 'signed_by_email': 'pat@acme.test', 'signed_by_title': 'CEO',
                'signature_data': PNG, 'content_hash': content_hash}
        data.update(extra)
        return Client(HTTP_USER_AGENT='QuoteTest/1.0').post(self.url, data, REMOTE_ADDR='203.0.113.9')

    def _page_hash(self):
        r = Client().get(self.url)
        self.assertEqual(r.status_code, 200)
        return r.context['content_hash']

    def test_signature_records_the_exact_revision(self):
        page_hash = self._page_hash()
        self.assertEqual(page_hash, self.quote.content_hash())
        self._post(page_hash)
        sig = QuoteSignature.objects.get(quote=self.quote)
        self.assertEqual(sig.content_hash, page_hash)
        content = json.loads(sig.content_json)
        self.assertEqual(content['total'], '1746.00')  # 1200 + 8% tax on 1200 + 450 untaxed
        self.assertEqual([li['description'] for li in content['lines']], ['Firewall', 'Install'])
        self.assertEqual(content['description'], 'Terms: net 30.')
        self.assertEqual(_sha(sig.content_json.encode()), sig.content_hash)
        self.assertTrue(sig.evidence_hash)
        checks = sig.verify()
        self.assertTrue(all(checks.values()), checks)
        self.quote.refresh_from_db()
        self.assertEqual(self.quote.status, 'accepted')

    def test_stale_page_cannot_sign_changed_quote(self):
        stale = self._page_hash()
        li = self.quote.line_items.get(description='Install')
        li.unit_price = Decimal('175.00')
        li.save()
        self.quote.recompute_totals()
        self._post(stale)
        self.assertFalse(QuoteSignature.objects.exists())
        self._post(self._page_hash())
        self.assertEqual(QuoteSignature.objects.get().content_hash, self.quote.content_hash())

    def test_signed_quote_cannot_be_edited(self):
        self._post(self._page_hash())
        sig = QuoteSignature.objects.get()
        # Through the staff form: refused, nothing changes.
        r = self.staff_client.post(f'/psa/quotes/{self.quote.pk}/edit/', {
            'title': 'Firewall refresh (cheaper)', 'client_org': self.client_org.pk,
            'client_org_id': self.msp.pk, 'li_description': ['Firewall'], 'li_quantity': ['1'],
            'li_unit_price': ['1.00']})
        self.assertEqual(r.status_code, 302)
        self.quote.refresh_from_db()
        self.assertEqual(self.quote.title, 'Firewall refresh')
        self.assertEqual(self.quote.line_items.count(), 2)
        # At the model level: content changes raise; status bookkeeping still saves.
        self.quote.total = Decimal('1.00')
        with self.assertRaises(SignedQuoteLocked):
            self.quote.save()
        self.quote.refresh_from_db()
        with self.assertRaises(SignedQuoteLocked):
            self.quote.line_items.first().delete()
        with self.assertRaises(SignedQuoteLocked):
            QuoteLineItem.objects.create(quote=self.quote, description='Extra', unit_price=1)
        self.quote.status = 'expired'
        self.quote.save()
        # The signature record itself is immutable.
        sig.signed_by_name = 'Someone else'
        with self.assertRaises(SignedQuoteLocked):
            sig.save()
        self.assertTrue(QuoteSignature.objects.get().verify()['current'])
        # A second signing attempt does not overwrite the evidence.
        self.quote.status = 'sent'
        self.quote.save()
        self._post(self.quote.content_hash(), signed_by_name='Mallory')
        self.assertEqual(QuoteSignature.objects.get().signed_by_name, 'Pat Lee')

    def test_changed_after_signing_shows_earlier_revision(self):
        self._post(self._page_hash())
        # A change that bypasses the model (raw SQL / queryset update).
        Quote.objects.filter(pk=self.quote.pk).update(title='Edited behind the lock')
        r = self.staff_client.get(f'/psa/quotes/{self.quote.pk}/')
        self.assertContains(r, 'signed an earlier revision')
        self.assertFalse(QuoteSignature.objects.get().verify()['current'])

    def test_evidence_download(self):
        self._post(self._page_hash())
        sig = QuoteSignature.objects.get()
        r = self.staff_client.get(f'/psa/quotes/{self.quote.pk}/signature/evidence/')
        self.assertEqual(r.status_code, 200)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        files = {n: z.read(n) for n in z.namelist()}
        self.assertEqual(_sha(files['content.json']), sig.content_hash)
        self.assertEqual(_sha(files['evidence.json']), sig.evidence_hash)
        evidence = json.loads(files['evidence.json'])
        self.assertEqual(evidence['quote']['content_hash'], sig.content_hash)
        self.assertEqual(evidence['ip_address'], '203.0.113.9')
        self.assertEqual(evidence['user_agent'], 'QuoteTest/1.0')
        if 'quote.pdf' in files:
            self.assertEqual(_sha(files['quote.pdf']), sig.pdf_hash)
        self.assertIn('signature.png', files)
        self.assertIn(sig.content_hash, files['SHA256SUMS'].decode())
        # Customers (non-staff) cannot download it.
        customer = User.objects.create_user('cust', 'c@acme.test', 'pw')
        c = Client()
        c.force_login(customer)
        self.assertNotEqual(c.get(f'/psa/quotes/{self.quote.pk}/signature/evidence/').status_code, 200)

    def test_legacy_signature_without_hash_locks_nothing(self):
        QuoteSignature.objects.create(quote=self.quote, signed_by_name='Old', signed_by_email='o@acme.test',
                                      signature_data=PNG)
        self.quote.title = 'Still editable'
        self.quote.save()
        self.assertEqual(self.staff_client.get(f'/psa/quotes/{self.quote.pk}/signature/evidence/').status_code,
                         404)
