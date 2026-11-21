"""Sample contract library (seeding, "Use this sample"), contract terms in
documents and billing contracts, the e-signature link between a signed
document and its billing contract, and view-tracking rules for contract
links."""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import Client

from contracts import services, starter_templates
from contracts.content import merge_context, resolve
from contracts.models import ContractDocument as D, ContractTemplate, ContractTemplateVersion

from .base import BROWSER, ContractTestCase, links_in_outbox


class SampleLibraryTests(ContractTestCase):

    def test_library_seeded_with_keys(self):
        keys = set(ContractTemplate.objects.filter(organization__isnull=True, is_sample=True)
                   .values_list('sample_key', flat=True))
        for k in ('msa_month_to_month', 'managed_services_12m', 'msa_36_month', 'block_hours_prepaid', 'sow',
                  'break_fix_tm', 'msa_with_schedule'):
            self.assertIn(k, keys)
        m2m = ContractTemplate.objects.get(sample_key='msa_month_to_month')
        self.assertEqual(m2m.latest_version.data['defaults']['term_type'], 'month_to_month')
        body = ' '.join(s['body'] for s in m2m.latest_version.data['sections'])
        self.assertIn('not legal advice', body)
        self.assertIn('counsel', body)

    def test_seed_is_idempotent_and_never_overwrites_edits(self):
        tpl = ContractTemplate.objects.get(sample_key='msa_36_month')
        ContractTemplateVersion.objects.create(template=tpl, version_number=2, data={'sections': [], 'defaults': {}},
                                               note='edited')
        ContractTemplate.objects.filter(pk=tpl.pk).update(name='Our 3-year MSA', is_active=False)
        before = ContractTemplate.objects.count()
        self.assertEqual(starter_templates.seed(), 0)
        self.assertEqual(starter_templates.seed(), 0)
        self.assertEqual(ContractTemplate.objects.count(), before)
        tpl.refresh_from_db()
        self.assertEqual((tpl.name, tpl.is_active, tpl.latest_version.version_number),
                         ('Our 3-year MSA', False, 2))
        # a deleted sample comes back; a pre-key row is recognised by its name
        ContractTemplate.objects.filter(sample_key='break_fix_tm').delete()
        legacy = ContractTemplate.objects.get(sample_key='sow')
        ContractTemplate.objects.filter(pk=legacy.pk).update(sample_key='')
        self.assertEqual(starter_templates.seed(), 1)
        legacy.refresh_from_db()
        self.assertEqual(legacy.sample_key, 'sow')
        self.assertEqual(ContractTemplate.objects.filter(name=legacy.name).count(), 1)

    def test_use_this_sample_makes_an_editable_copy(self):
        sample = ContractTemplate.objects.get(sample_key='msa_month_to_month')
        page = self.client.get('/contracts/templates/')
        self.assertContains(page, 'Use this sample')
        self.assertContains(page, 'not legal advice')
        r = self.client.post(f'/contracts/templates/{sample.pk}/clone/', {'organization': 'all'})
        self.assertEqual(r.status_code, 302)
        copy = ContractTemplate.objects.exclude(pk=sample.pk).get(cloned_from=sample)
        self.assertIsNone(copy.organization)
        self.assertFalse(copy.is_sample)
        self.assertEqual(copy.sample_key, '')
        self.assertEqual(copy.name, 'Managed services agreement — month-to-month')
        edit = self.client.get(f'/contracts/templates/{copy.pk}/')
        self.assertContains(edit, 'Based on a sample')
        r = self.client.post(f'/contracts/templates/{copy.pk}/', {
            'name': 'Our month-to-month MSA', 'kind': 'managed_services', 'term_type': 'month_to_month',
            'billing_frequency': 'monthly', 'section-0-title': 'Agreement', 'section-0-type': 'text',
            'section-0-body': '<p>Our wording for {{client.name}}.</p>', 'section-0-include': 'on'})
        self.assertEqual(r.status_code, 302)
        copy.refresh_from_db()
        self.assertEqual(copy.latest_version.version_number, 2)
        self.assertEqual(copy.latest_version.data['defaults']['term_type'], 'month_to_month')
        sample.refresh_from_db()
        self.assertEqual(sample.latest_version.version_number, 1)   # the shipped sample is untouched

    def test_use_this_sample_needs_global_template_rights(self):
        from .base import make_staff
        tech = make_staff('limited')
        cl = Client()
        cl.force_login(tech)
        s = cl.session
        s['2fa_prompted'] = True
        s.save()
        sample = ContractTemplate.objects.get(sample_key='msa_month_to_month')
        r = cl.post(f'/contracts/templates/{sample.pk}/clone/', {'organization': 'all'})
        self.assertIn(r.status_code, (403, 404))
        self.assertFalse(ContractTemplate.objects.filter(cloned_from=sample).exists())

    def test_placeholders_are_escaped_plain_substitution(self):
        self.org.name = '<script>alert(1)</script> & Co'
        self.org.save()
        c = self.new_contract(term_type='annual', duration_months=12)
        ctx = merge_context(c, services.settings_for(c))
        out, unresolved = resolve('<p>{{client.name}} — {{contract.term}} {{ __import__ }}</p>', ctx)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt; &amp; Co', out)
        self.assertNotIn('<script>', out)
        self.assertIn('Annual (12 months)', out)
        self.assertTrue(unresolved)  # unknown / malformed fields are left for a person, never evaluated


class TermTests(ContractTestCase):

    def test_template_sets_term_and_builder_saves_it(self):
        tpl = ContractTemplate.objects.get(sample_key='msa_36_month')
        c = services.create_contract(self.org, self.staff, template=tpl)
        self.assertEqual((c.term_type, c.duration_months), ('multi_year', 36))
        content, _u = __import__('contracts.content', fromlist=['build_content']).build_content(
            c, services.settings_for(c), services.signing_config(c))
        self.assertEqual(content['terms']['term_type'], 'multi_year')
        self.assertIn(('Term', 'Multi-year (36 months)'),
                      __import__('contracts.content', fromlist=['key_terms']).key_terms(content))

    def test_old_template_without_term_infers_it(self):
        tpl = ContractTemplate.objects.get(sample_key='backup_dr')
        c = services.create_contract(self.org, self.staff, template=tpl)
        self.assertEqual((c.term_type, c.duration_months), ('annual', 12))


class SignedBillingContractTests(ContractTestCase):

    def _signed(self, **fields):
        fields.setdefault('term_type', 'annual')
        fields.setdefault('duration_months', 12)
        fields.setdefault('effective_date', date.today())
        c = self.new_contract(**fields)
        self.issue_and_send(c)
        inv = c.invitations.get()
        cl, _page = self.signer_client(links_in_outbox('pat@acme.test')[0])
        self.sign_post(cl, inv)
        c.refresh_from_db()
        self.assertEqual(c.status, D.SIGNED)
        return c

    def test_billing_contract_from_signed_document_can_activate_and_bill(self):
        c = self._signed()
        bc = services.create_billing_contract(c, self.staff)
        self.assertEqual((bc.term_type, bc.term_months, bc.billing_frequency), ('annual', 12, 'monthly'))
        st = bc.esign_status()
        self.assertTrue(st['satisfied'], st)
        self.assertEqual(st['basis'], 'signed')
        bc.status = 'active'
        bc.next_billing_date = date.today()
        bc.save()
        inv = bc.generate_invoice(on_date=date.today())
        self.assertEqual(inv.total, Decimal('250.00'))   # 10 users x 25, what the customer signed

    def test_changed_terms_need_a_new_signature(self):
        bc = services.create_billing_contract(self._signed(), self.staff)
        bc.recurring_amount = Decimal('400')
        bc.save()
        st = bc.esign_status()
        self.assertFalse(st['satisfied'])
        self.assertIn('recurring amount', st['message'])
        bc.status = 'active'
        from psa.contract_terms import ESignatureRequired
        with self.assertRaises(ESignatureRequired):
            bc.save()

    def test_unsigned_document_gives_no_billing_contract(self):
        c = self.new_contract(term_type='annual', duration_months=12)
        with self.assertRaises(services.ContractError):
            services.create_billing_contract(c, self.staff)


class ContractViewTrackingTests(ContractTestCase):

    def test_staff_opening_a_client_link_is_not_a_view_and_webhook_fires_for_customer(self):
        c = self.new_contract()
        self.issue_and_send(c)
        inv = c.invitations.get()
        token = links_in_outbox('pat@acme.test')[0]
        # the signed-in staff member opens the customer's link
        r = self.client.get(f'/sign/t/{token}/', **BROWSER)
        page = self.client.get(r['Location'], **BROWSER)
        self.client.post(f'/sign/i/{inv.public_id}/seen/', {'nonce': page.context['nonce'], 'interacted': '1'},
                         **BROWSER)
        c.refresh_from_db()
        self.assertEqual(c.view_count, 0)
        # the customer does
        cl, page_url = self.signer_client(token)
        nonce = cl.get(page_url).context['nonce']
        with mock.patch('core.webhook_events.fire') as fire:
            cl.post(f'/sign/i/{inv.public_id}/seen/', {'nonce': nonce, 'interacted': '1'})
        c.refresh_from_db()
        self.assertEqual((c.view_count, c.status), (1, D.VIEWED))
        self.assertEqual([call.args[0] for call in fire.call_args_list], ['contract.viewed'])
