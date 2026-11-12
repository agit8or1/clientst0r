"""Staff pages: builder, autosave and conflicts, dashboard, templates,
clauses, settings, navigation, the client-record card and the mobile
signing page."""
from django.urls import reverse

from contracts import services
from contracts.models import (ContractClause, ContractDocument as D, ContractSettings, ContractTemplate,
                              ContractTemplateVersion)

from .base import BROWSER, ContractTestCase, links_in_outbox, make_org


def builder_post(c, **over):
    data = {'title': c.title, 'kind': c.kind, 'currency': 'USD', 'tax_rate': '0', 'billing_frequency': 'monthly',
            'payment_terms': 'Net 30', 'draft_revision': c.draft_revision, 'sections_present': '1'}
    for i, s in enumerate(c.sections):
        data.update({f'section-{i}-key': s.get('key', ''), f'section-{i}-title': s['title'],
                     f'section-{i}-type': s['type'], f'section-{i}-body': s['body'], f'section-{i}-order': i + 1,
                     f'section-{i}-include': 'on' if s.get('include', True) else ''})
    for i, li in enumerate(c.line_items):
        data.update({f'item-{i}-description': li['description'], f'item-{i}-kind': li['kind'],
                     f'item-{i}-quantity': li['quantity'], f'item-{i}-unit_price': li['unit_price'],
                     f'item-{i}-discount_percent': li.get('discount_percent', '0')})
    for i, s in enumerate(c.signers.all()):
        data.update({f'signer-{i}-role': s.role, f'signer-{i}-name': s.name, f'signer-{i}-email': s.email,
                     f'signer-{i}-order': s.order})
    data.update(over)
    return {k: v for k, v in data.items() if v is not None}


class BuilderTests(ContractTestCase):

    def test_builder_renders_with_editor_assets(self):
        c = self.new_contract()
        r = self.client.get(f'/contracts/{c.pk}/edit/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'vendor/quill/2.0.3/quill.js')
        self.assertContains(r, 'js/contract-builder.js')
        self.assertContains(r, 'data-autosave-url')
        self.assertContains(r, 'id="cd-save-state"')
        self.assertContains(r, 'data-merge="client.name"')
        self.assertNotContains(r, 'onclick=')

    def test_autosave_and_conflict(self):
        c = self.new_contract()
        rev = c.draft_revision
        r = self.client.post(f'/contracts/{c.pk}/autosave/', builder_post(c, title='Renamed'))
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertTrue(j['ok'])
        self.assertEqual(j['revision'], rev + 1)
        self.assertEqual(j['one_time_total'], '500.00')
        self.assertEqual(j['recurring_total'], '250.00')
        c.refresh_from_db()
        self.assertEqual(c.title, 'Renamed')
        # Another tab still holding the old revision is refused, not merged.
        r = self.client.post(f'/contracts/{c.pk}/autosave/', builder_post(c, title='Stale', draft_revision=rev))
        self.assertEqual(r.status_code, 409)
        c.refresh_from_db()
        self.assertEqual(c.title, 'Renamed')
        r = self.client.post(f'/contracts/{c.pk}/autosave/', builder_post(c, tax_rate='abc'))
        self.assertEqual(r.status_code, 400)

    def test_sections_reorder_remove_and_add(self):
        c = self.new_contract()
        post = builder_post(c)
        post['section-0-order'], post['section-1-order'] = '2', '1'
        post['section-2-deleted'] = '1'
        post.update({'section-3-title': 'Extra', 'section-3-type': 'text', 'section-3-body': '<p>new</p>',
                     'section-3-order': '3', 'section-3-include': 'on'})
        self.client.post(f'/contracts/{c.pk}/edit/', post)
        c.refresh_from_db()
        self.assertEqual([s['title'] for s in c.sections], ['Fees', 'Services', 'Extra'])

    def test_expiration_from_duration(self):
        c = self.new_contract()
        self.client.post(f'/contracts/{c.pk}/edit/', builder_post(c, effective_date='2027-01-01',
                                                                   duration_months='12', expiration_date=''))
        c.refresh_from_db()
        self.assertEqual(str(c.expiration_date), '2027-12-31')

    def test_issued_contract_is_not_editable(self):
        c = self.new_contract()
        services.submit(c, self.staff)
        r = self.client.post(f'/contracts/{c.pk}/autosave/', builder_post(c, title='Sneaky'))
        self.assertIn(r.status_code, (400, 409))
        c.refresh_from_db()
        self.assertNotEqual(c.title, 'Sneaky')
        r = self.client.get(f'/contracts/{c.pk}/edit/')
        self.assertEqual(r.status_code, 302)

    def test_attachments(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        c = self.new_contract()
        f = SimpleUploadedFile('exhibit-a.pdf', b'%PDF-1.4 exhibit', content_type='application/pdf')
        self.client.post(f'/contracts/{c.pk}/attachments/', {'file': f})
        a = c.attachments.get()
        self.assertEqual(a.size, len(b'%PDF-1.4 exhibit'))
        services.submit(c, self.staff)
        c.refresh_from_db()
        self.assertEqual(c.current_version.content['attachments'][0]['sha256'], a.sha256)
        services.send(c, self.staff)
        inv = c.invitations.get()
        cl, page = self.signer_client(links_in_outbox()[0])
        r = cl.get(f'/sign/i/{inv.public_id}/attachments/{a.pk}/')
        self.assertEqual(r.content, b'%PDF-1.4 exhibit')
        self.assertEqual(r['Content-Type'], 'application/octet-stream')

    def test_all_staff_pages_render(self):
        c = self.new_contract()
        urls = ['/contracts/', '/contracts/new/', f'/contracts/{c.pk}/', f'/contracts/{c.pk}/preview/',
                '/contracts/templates/', '/contracts/templates/new/', '/contracts/clauses/', '/contracts/clauses/new/',
                '/contracts/settings/', f'/contracts/settings/?org={self.org.pk}', f'/contracts/{c.pk}/void/']
        for u in urls:
            with self.subTest(u):
                self.assertEqual(self.client.get(u).status_code, 200, u)
        services.submit(c, self.staff)
        for u in (f'/contracts/{c.pk}/send/', f'/contracts/{c.pk}/revise/'):
            with self.subTest(u):
                self.assertEqual(self.client.get(u).status_code, 200, u)

    def test_dashboard_filters_and_value_split(self):
        c1 = self.new_contract(title='Alpha')
        c2 = self.new_contract(make_org('Beta Corp', 'b@beta.test'), title='Beta deal',
                               signers=[{'name': 'B', 'email': 'b@beta.test'}])
        r = self.client.get('/contracts/', {'q': 'Alpha'})
        self.assertContains(r, c1.reference)
        self.assertNotContains(r, c2.reference)
        r = self.client.get('/contracts/', {'status': 'draft', 'client': c2.organization_id})
        self.assertContains(r, c2.reference)
        self.assertNotContains(r, c1.reference)
        r = self.client.get('/contracts/', {'client': self.org.pk})
        self.assertEqual(r.context['sums']['one'], 500)     # one-time and recurring kept apart
        self.assertEqual(r.context['sums']['rec'], 250)
        self.assertContains(r, c1.reference)

    def test_client_record_card(self):
        c = self.new_contract()
        r = self.client.get(reverse('accounts:organization_detail', args=[self.org.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="client-contracts"')
        self.assertContains(r, c.reference)

    def test_navigation_entry(self):
        r = self.client.get('/contracts/')
        self.assertContains(r, 'href="/contracts/"')
        self.assertContains(r, 'Contract Documents')


class TemplateTests(ContractTestCase):

    def test_seven_sample_templates(self):
        names = set(ContractTemplate.objects.filter(is_sample=True, organization__isnull=True)
                    .values_list('name', flat=True))
        self.assertEqual(len(names), 7)
        for tpl in ContractTemplate.objects.filter(is_sample=True):
            data = tpl.latest_version.data
            self.assertTrue(any('[[' in s['body'] for s in data['sections']), tpl.name)

    def test_saving_a_template_creates_a_version_and_leaves_contracts(self):
        tpl = ContractTemplate.objects.filter(is_sample=True).first()
        c = services.create_contract(self.org, self.staff, template=tpl)
        before = c.sections
        n = tpl.versions.count()
        post = {'name': tpl.name, 'kind': tpl.kind, 'billing_frequency': 'monthly', 'sections_present': '1',
                'section-0-title': 'Only section', 'section-0-type': 'text', 'section-0-body': '<p>New text</p>',
                'section-0-include': 'on', 'section-0-order': '1'}
        r = self.client.post(f'/contracts/templates/{tpl.pk}/', post)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(tpl.versions.count(), n + 1)
        c.refresh_from_db()
        self.assertEqual(c.sections, before)
        self.assertEqual(self.client.get(f'/contracts/templates/{tpl.pk}/versions/1/').status_code, 200)

    def test_customer_private_template_and_clone(self):
        tpl = ContractTemplate.objects.filter(is_sample=True).first()
        r = self.client.post(f'/contracts/templates/{tpl.pk}/clone/', {'organization': self.org.pk})
        copy = ContractTemplate.objects.get(cloned_from=tpl)
        self.assertEqual(copy.organization, self.org)
        other = make_org('Other', 'o@o.test')
        with self.assertRaises(services.ContractError):
            services.create_contract(other, self.staff, template=copy)

    def test_clause_library_and_default_clauses(self):
        cl = ContractClause.objects.create(title='Data protection', body='<p>We protect data.</p>')
        s = ContractSettings.deployment_default()
        s.default_clauses.add(cl)
        c = services.create_contract(self.org, self.staff)
        titles = [x['title'] for x in c.sections]
        self.assertIn('Data protection', titles)
        self.assertLess(titles.index('Data protection'), titles.index('Signatures'))
        r = self.client.post('/contracts/clauses/new/', {'title': 'Liability', 'body': '<p>Cap <script>x</script></p>',
                                                       'scope': '', 'is_active': 'on'})
        self.assertEqual(r.status_code, 302)
        self.assertNotIn('<script', ContractClause.objects.get(title='Liability').body)


class SettingsTests(ContractTestCase):

    def test_deployment_default_and_customer_override(self):
        post = {'brand_color': '#112233', 'consent_text': 'I agree to e-sign.', 'intent_text': 'I intend to sign.',
                'invitation_subject': 'Sign {{contract.title}}', 'invitation_body': 'Hi {{signer.name}} {{link}}',
                'reminder_subject': 'R', 'reminder_body': 'R {{link}}', 'completed_subject': 'C',
                'completed_body': 'C', 'signing_order': 'sequential', 'invitation_expiry_days': '10',
                'acceptance_deadline_days': '20', 'repeat_view_cooldown_minutes': '60',
                'reminder_first_after_days': '2', 'reminder_interval_days': '2', 'reminder_max': '3',
                'renewal_alert_days': '30', 'expiration_alert_days': '7', 'access_log_retention_days': '0',
                'require_email_verification': 'on'}
        post['org'] = 'global'
        r = self.client.post('/contracts/settings/', post)
        self.assertEqual(r.status_code, 302)
        s = ContractSettings.deployment_default()
        self.assertTrue(s.require_email_verification)
        self.assertEqual(s.signing_order, 'sequential')
        r = self.client.post('/contracts/settings/', dict(post, org=self.org.pk, brand_color='#445566',
                                                         require_email_verification=''))
        o = ContractSettings.objects.get(organization=self.org)
        self.assertFalse(o.require_email_verification)
        self.assertEqual(ContractSettings.for_organization(self.org).brand_color, '#445566')
        self.assertEqual(ContractSettings.for_organization(make_org('Z', 'z@z.test')).brand_color, '#112233')
        self.client.post('/contracts/settings/', {'org': self.org.pk, 'action': 'reset'})
        self.assertFalse(ContractSettings.objects.filter(organization=self.org).exists())
        r = self.client.post('/contracts/settings/', dict(post, brand_color='red'))
        self.assertEqual(r.status_code, 200)


class MobileSigningPageTests(ContractTestCase):

    def test_signing_page_is_mobile_ready_and_self_contained(self):
        c = self.new_contract()
        self.issue_and_send(c)
        inv = c.invitations.get()
        cl, page = self.signer_client(links_in_outbox()[0],
                                      HTTP_USER_AGENT='Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) '
                                                      'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 '
                                                      'Mobile/15E148 Safari/604.1')
        r = cl.get(page)
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('name="viewport" content="width=device-width, initial-scale=1"', html)
        self.assertIn('css/contract-sign.css', html)
        self.assertIn('js/contract-sign.js', html)
        self.assertIn('class="cs-pad"', html)
        self.assertIn('autocomplete="name"', html)
        import re
        for src in re.findall(r'(?:src|href)="([^"]+)"', html):
            self.assertFalse(src.startswith(('http://', 'https://', '//')), src)
        self.assertNotIn('onclick', html)
        self.assertEqual(r['X-Robots-Tag'], 'noindex, nofollow')

    def test_sign_page_head_request_does_not_bind(self):
        c = self.new_contract()
        self.issue_and_send(c)
        token = links_in_outbox()[0]
        cl = self.client_class(**BROWSER)
        r = cl.head(f'/sign/t/{token}/')
        self.assertEqual(r.status_code, 200)
        inv = c.invitations.get()
        self.assertEqual(cl.get(f'/sign/i/{inv.public_id}/').status_code, 403)
