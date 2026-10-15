"""Staff catalog editor for guided service requests (form schema, portal
settings, availability) and its governance flow."""
import json

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role
from core.models import Organization, SystemSetting
from psa.models import Queue, ServiceCatalogChange, ServiceCatalogItem
from psa.tests._base import TEST_MIDDLEWARE, _setup_seed

SCHEMA = [
    {'key': 'who', 'label': 'Who', 'type': 'user', 'required': True},
    {'key': 'kind', 'label': 'Kind', 'type': 'multiselect', 'options': ['A', 'B']},
    {'key': 'admin', 'label': 'Admin access', 'type': 'checkbox'},
    {'key': 'why', 'label': 'Why', 'type': 'textarea', 'required': True,
     'show_if': {'field': 'admin', 'equals': True}},
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class GuidedCatalogEditorTests(TestCase):
    def setUp(self):
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.admin = User.objects.create_user('ge-admin', 'ge@x.com', 'pw',
                                              is_superuser=True, is_staff=True)
        self.c = Client(); self.c.force_login(self.admin)
        self.org_a = Organization.objects.create(name='GE A', slug='ge-a')
        self.org_b = Organization.objects.create(name='GE B', slug='ge-b')
        self.queue = Queue.objects.filter(is_active=True).first()

    def _post(self, url, **extra):
        data = {
            'name': 'Access thing', 'description': 'd', 'default_subject': 'Access {{who}}',
            'default_body': '', 'sort_order': '1', 'is_active': 'on',
            '_guided': '1', 'form_schema_json': json.dumps(SCHEMA),
            'portal_visible': 'on', 'category': 'Access', 'approval_policy': 'customer',
            'expected_turnaround_text': '', 'expected_turnaround_hours': '8',
            'default_queue': str(self.queue.pk),
            'include_organizations': [str(self.org_a.pk), str(self.org_b.pk)],
            'exclude_organizations': [str(self.org_b.pk)],
        }
        data.update(extra)
        return self.c.post(url, data)

    def test_editor_renders_builder(self):
        r = self.c.get('/psa/catalog/new/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'form_schema_json')
        self.assertContains(r, 'Request form')

    def test_create_with_guided_fields(self):
        r = self._post('/psa/catalog/new/')
        self.assertEqual(r.status_code, 302)
        item = ServiceCatalogItem.objects.get(name='Access thing')
        self.assertTrue(item.portal_visible)
        self.assertEqual(item.category, 'Access')
        self.assertEqual(item.approval_policy, 'customer')
        self.assertEqual(item.expected_turnaround_hours, 8)
        self.assertEqual(item.default_queue, self.queue)
        self.assertEqual([f['key'] for f in item.form_schema], ['who', 'kind', 'admin', 'why'])
        self.assertEqual(item.form_schema[3]['show_if'], {'field': 'admin', 'equals': True})
        self.assertEqual(set(item.include_organizations.all()), {self.org_a, self.org_b})
        self.assertEqual(list(item.exclude_organizations.all()), [self.org_b])
        # Legacy mirror for the staff ticket form: known types only, and the
        # conditional field isn't required there.
        legacy = {f['key']: f for f in item.fields_json}
        self.assertEqual(legacy['who']['type'], 'text')
        self.assertEqual(legacy['kind']['type'], 'text')
        self.assertFalse(legacy['why']['required'])

    def test_invalid_schema_rejected(self):
        bad = [{'key': 'x', 'label': 'X', 'show_if': {'field': 'nope', 'equals': 'y'}}]
        self._post('/psa/catalog/new/', form_schema_json=json.dumps(bad))
        self.assertFalse(ServiceCatalogItem.objects.filter(name='Access thing').exists())

    def test_legacy_post_keeps_working_and_fills_schema(self):
        self.c.post('/psa/catalog/new/', {
            'name': 'Legacy post', 'fields_json': '[{"key":"a","label":"A","type":"text"}]',
            'sort_order': '0',
        })
        item = ServiceCatalogItem.objects.get(name='Legacy post')
        self.assertEqual(item.get_form_schema()[0]['key'], 'a')

    def test_requires_approval_flag_survives_direct_edit(self):
        self._post('/psa/catalog/new/', requires_approval='on')
        item = ServiceCatalogItem.objects.get(name='Access thing')
        self.assertTrue(item.requires_approval)

    def test_staff_ticket_form_still_renders_item(self):
        self._post('/psa/catalog/new/')
        item = ServiceCatalogItem.objects.get(name='Access thing')
        org = Organization.objects.create(name='GE Client', slug='ge-client')
        s = self.c.session; s['current_organization_id'] = org.pk; s.save()
        r = self.c.get(f'/psa/new/?from_catalog={item.slug}')
        self.assertEqual(r.status_code, 200)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class GuidedCatalogGovernanceTests(TestCase):
    def setUp(self):
        from accounts.models import RoleTemplate
        _setup_seed()
        s = SystemSetting.get_settings(); s.psa_enabled = True; s.save()
        self.org = Organization.objects.create(name='GG Org', slug='gg-org')
        self.org_b = Organization.objects.create(name='GG B', slug='gg-b')
        role = RoleTemplate.objects.create(
            name='GGProposer', is_system_template=False,
            catalog_propose_change=True, catalog_approve_change=False, assets_create=True,
        )
        self.proposer = User.objects.create_user('gg-prop', 'gg@x.com', 'pw',
                                                 is_staff=True, is_superuser=True)
        Membership.objects.create(user=self.proposer, organization=self.org, role=Role.EDITOR,
                                  role_template=role, is_active=True)
        self.approver = User.objects.create_user('gg-appr', 'ga@x.com', 'pw',
                                                 is_staff=True, is_superuser=True)
        self.item = ServiceCatalogItem.objects.create(
            name='Governed', slug='governed', requires_approval=True,
            fields_json=[{'key': 'a', 'label': 'A', 'type': 'text'}],
        )

    def _client(self, user):
        c = Client(); c.force_login(user)
        s = c.session; s['current_organization_id'] = self.org.pk; s.save()
        return c

    def test_propose_guided_change_then_apply(self):
        c = self._client(self.proposer)
        r = c.post(f'/psa/catalog/{self.item.pk}/propose/', {
            'name': 'Governed', 'description': '', 'default_subject': '', 'default_body': '',
            'icon': '', 'sort_order': '0', 'is_active': 'on', 'reason': 'portal',
            '_guided': '1', 'form_schema_json': json.dumps(SCHEMA), 'portal_visible': 'on',
            'category': 'Access', 'approval_policy': 'none',
            'exclude_organizations': [str(self.org_b.pk)],
        })
        self.assertEqual(r.status_code, 302)
        self.item.refresh_from_db()
        self.assertFalse(self.item.portal_visible)  # not live yet
        change = ServiceCatalogChange.objects.get(catalog_item=self.item, status='pending')
        self.assertIn('form_schema', change.after_snapshot)
        self.assertTrue(change.after_snapshot['portal_visible'])
        self.assertEqual(change.after_snapshot['exclude_organization_ids'], [self.org_b.pk])
        # Fields that didn't change aren't in the proposal.
        self.assertNotIn('name', change.after_snapshot)
        self.assertNotIn('include_organization_ids', change.after_snapshot)

        change.apply(decided_by=self.approver)
        self.item.refresh_from_db()
        self.assertTrue(self.item.portal_visible)
        self.assertEqual(self.item.category, 'Access')
        self.assertEqual(len(self.item.form_schema), 4)
        self.assertEqual(list(self.item.exclude_organizations.all()), [self.org_b])

    def test_unchanged_form_is_not_a_change(self):
        c = self._client(self.proposer)
        c.post(f'/psa/catalog/{self.item.pk}/propose/', {
            'name': 'Governed', 'description': '', 'default_subject': '', 'default_body': '',
            'icon': '', 'sort_order': '0', 'is_active': 'on',
            '_guided': '1', 'form_schema_json': json.dumps(self.item.get_form_schema()),
            'approval_policy': 'none',
        })
        self.assertFalse(ServiceCatalogChange.objects.filter(catalog_item=self.item).exists())

    def test_direct_edit_redirects_non_approver_to_propose(self):
        from accounts.models import RoleTemplate
        from psa.tests._base import _make_msp_tech
        tech = _make_msp_tech(User.objects.create_user('gg-tech', 'gt@x.com', 'pw'))
        Membership.objects.create(
            user=tech, organization=self.org, role=Role.EDITOR, is_active=True,
            role_template=RoleTemplate.objects.get(name='GGProposer'))
        c = self._client(tech)
        r = c.get(f'/psa/catalog/{self.item.pk}/edit/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/propose/', r['Location'])
        r = c.get(f'/psa/catalog/{self.item.pk}/propose/')
        self.assertContains(r, 'form_schema_json')
