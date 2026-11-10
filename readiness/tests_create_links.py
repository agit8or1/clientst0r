"""Readiness "Create it" links prefill the target form and carry the customer
they are for; asset-fields requirements can name custom asset fields
(v3.17.655)."""
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import Membership, RoleTemplate, UserType
from assets.models import Asset, AssetCustomField, Contact, Relationship
from core.models import Organization, Tag
from docs.models import Document, DocumentCategory
from vault.models import Password

from readiness import scoring
from readiness.models import DocumentationStandard, StandardRequirement as R
from readiness.params import validate_params
from readiness.tests import TEST_MIDDLEWARE, make_standard, only_result

User = get_user_model()

FULL = dict(vault_view=True, vault_create=True, vault_edit=True, assets_view=True,
            assets_create=True, assets_edit=True, docs_view=True, docs_create=True,
            docs_edit=True, docs_publish=True)


def _fix(org, kind, params):
    std = make_standard(f'{kind} std {org.pk}', reqs=[(kind, params, 1)])
    res = only_result(org, std)
    std.delete()
    return res.fix


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organization.objects.create(name='Alpha', slug='rdl-a')
        cls.org_b = Organization.objects.create(name='Bravo', slug='rdl-b')
        cls.cat_a = DocumentCategory.objects.create(organization=cls.org_a, name='Backups', slug='backups')
        cls.cat_b = DocumentCategory.objects.create(organization=cls.org_b, name='Backups', slug='backups')
        cls.tag_a = Tag.objects.create(organization=cls.org_a, name='DR', slug='dr')
        cls.tag_b = Tag.objects.create(organization=cls.org_b, name='DR', slug='dr')
        cls.only_b_tag = Tag.objects.create(organization=cls.org_b, name='Bravo only', slug='bravo-only')
        cls.staff = User.objects.create_user('rdl_staff', 's@x.com', 'pw', is_staff=True)
        cls.staff.profile.user_type = UserType.STAFF
        cls.staff.profile.global_role_template = RoleTemplate.objects.create(name='Tech (global)', **FULL)
        cls.staff.profile.save()

    def _login(self, user, org):
        self.client.force_login(user)
        session = self.client.session
        session['current_organization_id'] = org.pk
        session.save()

    def _session_org(self):
        return self.client.session.get('current_organization_id')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PrefillTests(_Base):
    def test_document_fix_prefills_title_category_tags_of_that_customer(self):
        fix = _fix(self.org_a, R.KIND_DOCUMENT_EXISTS,
                   {'title_contains': 'Backup plan|DR plan', 'category': 'backups', 'tag': 'dr'})
        self.assertIn(f'org={self.org_a.pk}', fix.url)
        self._login(self.staff, self.org_a)
        r = self.client.get(fix.url)
        self.assertEqual(r.status_code, 200)
        form = r.context['form']
        self.assertEqual(form.initial['title'], 'Backup plan')
        self.assertEqual(form.initial['category'], self.cat_a)
        self.assertEqual(list(form.initial['tags']), [self.tag_a])
        self.assertContains(r, 'value="Backup plan"')
        self.assertFalse(Document.objects.filter(title='Backup plan').exists())

    def test_category_and_tags_from_another_customer_are_not_used(self):
        self._login(self.staff, self.org_a)
        url = reverse('docs:document_create') + '?title=X&category=Backups&tags=Bravo+only'
        form = self.client.get(url).context['form']
        self.assertEqual(form.initial['category'], self.cat_a)
        self.assertNotIn('tags', form.initial)
        # the pickers only offer this customer's categories and tags either
        self.assertNotIn(self.cat_b, form.fields['category'].queryset)
        self.assertNotIn(self.only_b_tag, form.fields['tags'].queryset)
        # an unknown category is simply ignored
        url = reverse('docs:document_create') + f'?category={self.cat_b.pk}'
        self.assertNotIn('category', self.client.get(url).context['form'].initial)

    def test_prefill_is_length_limited_and_escaped(self):
        self._login(self.staff, self.org_a)
        r = self.client.get(reverse('docs:document_create'),
                            {'title': '<script>alert(1)</script>' + 'x' * 600})
        title = r.context['form'].initial['title']
        self.assertEqual(len(title), Document._meta.get_field('title').max_length)
        self.assertNotContains(r, '<script>alert(1)</script>xxx')
        self.assertContains(r, '&lt;script&gt;alert(1)&lt;/script&gt;')

    def test_contact_fix_prefills_title(self):
        fix = _fix(self.org_a, R.KIND_CONTACT_ROLE, {'title_contains': 'IT Manager|CTO'})
        self._login(self.staff, self.org_a)
        r = self.client.get(fix.url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['form'].initial['title'], 'IT Manager')
        self.assertContains(r, 'value="IT Manager"')
        # and the form saves (first / last name are on the page)
        r = self.client.post(reverse('assets:contact_create'), {
            'first_name': 'Ivy', 'last_name': 'Tee', 'title': 'IT Manager', '_org': self.org_a.pk})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Contact.objects.filter(organization=self.org_a, title='IT Manager').exists())

    def test_vault_fix_prefills_title_and_tags(self):
        fix = _fix(self.org_a, R.KIND_CREDENTIAL_REFERENCE, {'title_contains': 'Global admin', 'tag': 'dr'})
        self._login(self.staff, self.org_a)
        r = self.client.get(fix.url)
        self.assertEqual(r.status_code, 200)
        form = r.context['form']
        self.assertEqual(form.initial['title'], 'Global admin')
        self.assertEqual(list(form.initial['tags']), [self.tag_a])
        self.assertFalse(Password.objects.exists())

    def test_relationship_fix_preselects_source_and_target_kind(self):
        asset = Asset.objects.create(organization=self.org_a, name='srv1', asset_type='server')
        other = Asset.objects.create(organization=self.org_b, name='srv-b', asset_type='server')
        doc = Document.objects.create(organization=self.org_a, title='Runbook', body='x', is_published=True)
        fix = _fix(self.org_a, R.KIND_RELATIONSHIP_PRESENT,
                   {'asset_type': 'server', 'target_kinds': ['document']})
        self._login(self.staff, self.org_a)
        r = self.client.get(fix.url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['selected_source'], f'asset:{asset.pk}')
        self.assertEqual(r.context['target_type'], 'document')
        self.assertContains(r, f'value="asset:{asset.pk}" selected')
        self.assertNotContains(r, 'srv-b')
        # someone else's asset is never preselected
        r = self.client.get(reverse('assets:relationship_create'),
                            {'source_type': 'asset', 'source_id': other.pk})
        self.assertEqual(r.context['selected_source'], '')
        # saving links them
        r = self.client.post(reverse('assets:relationship_create'), {
            'source': f'asset:{asset.pk}', 'target': f'document:{doc.pk}', 'relation_type': 'documents',
            '_org': self.org_a.pk})
        self.assertRedirects(r, reverse('assets:asset_detail', kwargs={'pk': asset.pk}),
                             fetch_redirect_response=False)
        self.assertTrue(Relationship.objects.filter(organization=self.org_a, source_id=asset.pk,
                                                    target_type='document', target_id=doc.pk).exists())

    def test_relationship_to_contact_saves(self):
        asset = Asset.objects.create(organization=self.org_a, name='srv1', asset_type='server')
        contact = Contact.objects.create(organization=self.org_a, first_name='C', last_name='D')
        self._login(self.staff, self.org_a)
        self.client.post(reverse('assets:relationship_create'), {
            'source': f'asset:{asset.pk}', 'target': f'contact:{contact.pk}'})
        self.assertTrue(Relationship.objects.filter(target_type='contact', target_id=contact.pk).exists())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CrossCustomerLinkTests(_Base):
    def test_link_for_b_switches_from_a_and_creates_in_b(self):
        fix = _fix(self.org_b, R.KIND_DOCUMENT_EXISTS, {'title_contains': 'Bravo DR', 'tag': 'dr',
                                                         'category': 'Backups'})
        self._login(self.staff, self.org_a)
        r = self.client.get(fix.url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._session_org(), self.org_b.pk)
        self.assertContains(r, 'This will be saved in <strong>Bravo</strong>')
        form = r.context['form']
        self.assertEqual(form.initial['category'], self.cat_b)
        self.assertEqual(list(form.initial['tags']), [self.tag_b])
        self.assertContains(r, f'name="_org" value="{self.org_b.pk}"')
        r = self.client.post(fix.url, {
            'title': 'Bravo DR', 'body': 'plan', 'content_type': 'markdown', 'category': self.cat_b.pk,
            'tags': [self.tag_b.pk], 'is_published': 'on', '_org': self.org_b.pk})
        self.assertEqual(r.status_code, 302, getattr(r, 'context', None) and r.context['form'].errors)
        doc = Document.objects.get(title='Bravo DR')
        self.assertEqual(doc.organization, self.org_b)

    def test_form_opened_for_b_never_saves_into_a(self):
        self._login(self.staff, self.org_a)
        url = reverse('assets:contact_create') + f'?org={self.org_b.pk}&title=CTO'
        self.client.get(url)
        self.assertEqual(self._session_org(), self.org_b.pk)
        # another tab switches back to A before the form is submitted
        self.client.get(reverse('accounts:switch_organization', args=[self.org_a.pk]))
        self.assertEqual(self._session_org(), self.org_a.pk)
        r = self.client.post(reverse('assets:contact_create'),
                             {'first_name': 'X', 'last_name': 'Y', 'title': 'CTO', '_org': self.org_b.pk})
        self.assertEqual(r.status_code, 302)
        self.assertIn(f'org={self.org_b.pk}', r['Location'])
        self.assertFalse(Contact.objects.exists())
        # ?org= on the action URL is honoured the same way
        r = self.client.post(url, {'first_name': 'X', 'last_name': 'Y', 'title': 'CTO'})
        self.assertFalse(Contact.objects.exists())

    def test_user_without_access_to_b_cannot_use_the_link(self):
        customer = User.objects.create_user('rdl_cust', 'c@x.com', 'pw')
        role = RoleTemplate.objects.create(name='Cust A', organization=self.org_a, **FULL)
        Membership.objects.create(user=customer, organization=self.org_a, role='editor',
                                  role_template=role, is_active=True)
        self._login(customer, self.org_a)
        for url in (reverse('docs:document_create') + f'?org={self.org_b.pk}&title=x',
                    reverse('vault:password_create') + f'?org={self.org_b.pk}',
                    reverse('assets:contact_create') + f'?org={self.org_b.pk}'):
            self.assertEqual(self.client.get(url).status_code, 404, url)
            self.assertEqual(self._session_org(), self.org_a.pk)
        # their own customer works
        r = self.client.get(reverse('docs:document_create') + f'?org={self.org_a.pk}&title=x')
        self.assertEqual(r.status_code, 200)
        # a POST naming B is refused, nothing is created in A either
        self.client.post(reverse('assets:contact_create'),
                         {'first_name': 'X', 'last_name': 'Y', '_org': self.org_b.pk})
        self.assertFalse(Contact.objects.exists())
        self.assertEqual(self._session_org(), self.org_a.pk)

    def test_link_cannot_skip_a_section_the_role_in_b_lacks(self):
        user = User.objects.create_user('rdl_two', 't@x.com', 'pw')
        full = RoleTemplate.objects.create(name='Full A', organization=self.org_a, **FULL)
        no_vault = RoleTemplate.objects.create(name='No vault B', organization=self.org_b,
                                               **dict(FULL, vault_view=False, vault_create=False))
        Membership.objects.create(user=user, organization=self.org_a, role='editor', role_template=full)
        Membership.objects.create(user=user, organization=self.org_b, role='editor', role_template=no_vault)
        self._login(user, self.org_a)
        self.assertEqual(self.client.get(reverse('vault:password_create')).status_code, 200)
        r = self.client.get(reverse('vault:password_create') + f'?org={self.org_b.pk}&title=x')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self._session_org(), self.org_a.pk)
        # docs are fine in B, so that link switches
        r = self.client.get(reverse('docs:document_create') + f'?org={self.org_b.pk}&title=x')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._session_org(), self.org_b.pk)

    def test_malformed_org_param_is_404(self):
        self._login(self.staff, self.org_a)
        self.assertEqual(self.client.get(reverse('docs:document_create') + '?org=abc').status_code, 404)
        self.assertEqual(self.client.get(reverse('docs:document_create') + '?org=999999').status_code, 404)

    def test_all_fix_urls_name_the_customer(self):
        Asset.objects.create(organization=self.org_b, name='s', asset_type='server')
        doc = Document.objects.create(organization=self.org_b, title='Old DR', body='x', is_published=True)
        doc.tags.add(self.tag_b)
        cases = [
            (R.KIND_DOCUMENT_EXISTS, {'tag': 'nomatch'}),
            (R.KIND_DOCUMENT_FRESH, {'tag': 'dr', 'max_age_days': 1, 'basis': 'reviewed'}),
            (R.KIND_DOCUMENT_OWNER, {'tag': 'dr'}),
            (R.KIND_ASSET_FIELDS, {'fields': ['serial_number']}),
            (R.KIND_CONTACT_ROLE, {'title_contains': 'cto'}),
            (R.KIND_CREDENTIAL_REFERENCE, {'title_contains': 'admin'}),
            (R.KIND_RELATIONSHIP_PRESENT, {}),
        ]
        for kind, params in cases:
            fix = _fix(self.org_b, kind, params)
            self.assertIsNotNone(fix, kind)
            self.assertIn(f'org={self.org_b.pk}', fix.url, kind)
            self._login(self.staff, self.org_a)
            r = self.client.get(fix.url)
            self.assertEqual(r.status_code, 200, (kind, fix.url))
            self.assertEqual(self._session_org(), self.org_b.pk, kind)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CustomFieldRequirementTests(_Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.agent = AssetCustomField.objects.create(label='Backup agent', key='backup_agent',
                                                    asset_types=['server'])
        cls.owner_cf = AssetCustomField.objects.create(label='Business owner', key='biz_owner')
        cls.box = AssetCustomField.objects.create(label='Monitored', key='monitored', field_type='checkbox')

    def test_params_validation(self):
        p = validate_params(R.KIND_ASSET_FIELDS, {'asset_type': 'server', 'custom_fields': ['backup_agent']})
        self.assertEqual(p, {'asset_type': 'server', 'fields': [], 'custom_fields': ['backup_agent']})
        for bad in (['nope'], ['monitored']):
            with self.assertRaises(Exception):
                validate_params(R.KIND_ASSET_FIELDS, {'custom_fields': bad})
        with self.assertRaisesMessage(Exception, 'not used on Firewall assets'):
            validate_params(R.KIND_ASSET_FIELDS, {'asset_type': 'firewall', 'custom_fields': ['backup_agent']})
        with self.assertRaises(Exception):
            validate_params(R.KIND_ASSET_FIELDS, {'fields': [], 'custom_fields': []})

    def test_old_builtin_only_requirement_is_unchanged(self):
        params = validate_params(R.KIND_ASSET_FIELDS, {'asset_type': 'server', 'fields': ['serial_number']})
        self.assertEqual(params, {'asset_type': 'server', 'fields': ['serial_number']})
        std = DocumentationStandard.objects.create(name='Old')
        R.objects.create(standard=std, title='t', kind=R.KIND_ASSET_FIELDS, params=params)
        a = Asset.objects.create(organization=self.org_a, name='srv', asset_type='server',
                                 custom_fields={'backup_agent': ''})
        res = only_result(self.org_a, std)
        self.assertEqual(res.status, scoring.UNMET)
        self.assertEqual(res.explanation, '1 of 1 Server asset is missing some of: serial number.')
        self.assertEqual(res.records[0].url, reverse('assets:asset_edit', kwargs={'pk': a.pk}))
        self.assertEqual(res.records[0].note, 'missing serial number')
        a.serial_number = 'SN1'
        a.save()
        res = only_result(self.org_a, std)
        self.assertEqual((res.status, res.explanation),
                         (scoring.MET, 'All 1 Server asset have serial number filled in.'))

    def test_custom_field_met_and_unmet(self):
        std = make_standard('CF', reqs=[(R.KIND_ASSET_FIELDS, {'custom_fields': ['backup_agent']}, 1)])
        good = Asset.objects.create(organization=self.org_a, name='good', asset_type='server',
                                    custom_fields={'backup_agent': 'Veeam'})
        bad = Asset.objects.create(organization=self.org_a, name='bad', asset_type='server',
                                   custom_fields={'backup_agent': '  '})
        none = Asset.objects.create(organization=self.org_a, name='none', asset_type='server')
        # a workstation isn't a type the field is used on
        Asset.objects.create(organization=self.org_a, name='ws', asset_type='workstation')
        res = only_result(self.org_a, std)
        self.assertEqual(res.status, scoring.UNMET)
        self.assertEqual(sorted(r.id for r in res.records), sorted([bad.pk, none.pk]))
        self.assertIn('2 of 3 assets', res.explanation)
        self.assertEqual(res.records[0].note, 'missing Backup agent')
        self.assertIn('#custom-fields', res.fix.url)
        self.assertIn(f'org={self.org_a.pk}', res.fix.url)
        self.assertIn(reverse('assets:asset_edit', kwargs={'pk': res.records[0].id}), res.fix.url)
        Asset.objects.filter(pk__in=[bad.pk, none.pk]).update(custom_fields={'backup_agent': 'Veeam'})
        self.assertEqual(only_result(self.org_a, std).status, scoring.MET)
        self.assertNotIn(good.pk, [r.id for r in res.records])

    def test_custom_and_builtin_together_and_inactive_field_skipped(self):
        std = make_standard('Mixed', reqs=[(R.KIND_ASSET_FIELDS, {
            'asset_type': 'server', 'fields': ['serial_number'], 'custom_fields': ['biz_owner']}, 1)])
        a = Asset.objects.create(organization=self.org_a, name='s', asset_type='server', serial_number='1')
        res = only_result(self.org_a, std)
        self.assertEqual(res.status, scoring.UNMET)
        self.assertIn('serial number, Business owner', res.explanation)
        self.assertEqual(res.records[0].note, 'missing Business owner')
        AssetCustomField.objects.filter(pk=self.owner_cf.pk).update(is_active=False)
        self.assertEqual(only_result(self.org_a, std).status, scoring.MET)
        self.assertTrue(a.pk)

    def test_custom_only_rule_with_no_matching_assets_is_not_applicable(self):
        std = make_standard('NA', reqs=[(R.KIND_ASSET_FIELDS, {'custom_fields': ['backup_agent']}, 1)])
        Asset.objects.create(organization=self.org_a, name='ws', asset_type='workstation')
        self.assertEqual(only_result(self.org_a, std).status, scoring.NOT_APPLICABLE)

    def test_queries_stay_flat(self):
        make_standard('Q', reqs=[(R.KIND_ASSET_FIELDS, {'custom_fields': ['backup_agent', 'biz_owner']}, 1)])
        orgs = []
        for i in range(8):
            org = Organization.objects.create(name=f'CFQ{i}', slug=f'rdl-q{i}')
            orgs.append(org)
            for j in range(3):
                Asset.objects.create(organization=org, name=f's{j}', asset_type='server',
                                     custom_fields={'backup_agent': 'x'} if j else {})

        def count(o):
            standards = scoring.active_standards()
            with CaptureQueriesContext(connection) as ctx:
                scoring.evaluate_many(o, standards)
            return len(ctx.captured_queries)
        self.assertEqual(count(orgs[:2]), count(orgs))

    def test_editor_saves_custom_field_params(self):
        self.client.force_login(self.staff)
        data = {'name': 'Servers CF', 'description': '', 'scope': 'all', 'is_active': 'on',
                'req-TOTAL_FORMS': '1', 'req-INITIAL_FORMS': '0', 'req-MIN_NUM_FORMS': '0',
                'req-MAX_NUM_FORMS': '1000',
                'req-0-title': 'Backup agent recorded', 'req-0-kind': R.KIND_ASSET_FIELDS,
                'req-0-weight': '1', 'req-0-order': '0', 'req-0-p_asset_type': 'server',
                'req-0-p_custom_fields': ['backup_agent'], 'req-0-p_basis': 'reviewed_or_updated'}
        r = self.client.post(reverse('readiness:standard_create'), data)
        self.assertEqual(r.status_code, 302, getattr(r, 'context', None) and r.context['formset'].errors)
        req = DocumentationStandard.objects.get(name='Servers CF').requirements.get()
        self.assertEqual(req.params, {'asset_type': 'server', 'fields': [], 'custom_fields': ['backup_agent']})
        # the editor offers checkable custom fields only, and shows the saved one selected
        r = self.client.get(reverse('readiness:standard_edit', kwargs={'pk': req.standard_id}))
        field = r.context['formset'].forms[0]['p_custom_fields']
        keys = [k for k, _ in field.field.choices]
        self.assertIn('backup_agent', keys)
        self.assertNotIn('monitored', keys)
        self.assertEqual(field.initial, ['backup_agent'])
        # a checkbox field is refused
        data['req-0-p_custom_fields'] = ['monitored']
        data['name'] = 'Bad CF'
        r = self.client.post(reverse('readiness:standard_create'), data)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(DocumentationStandard.objects.filter(name='Bad CF').exists())
