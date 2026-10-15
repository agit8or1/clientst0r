from datetime import timedelta
from io import StringIO
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, RoleTemplate, UserType
from assets.models import Asset, Contact, Relationship
from core.models import Organization, Tag
from docs.models import Document, DocumentCategory
from vault.models import Password

from readiness import scoring
from readiness.models import DocumentationStandard, StandardException, StandardRequirement as R
from readiness.params import validate_params
from readiness.relationships import (
    REASON_MISSING, REASON_OTHER_CUSTOMER, REASON_UNKNOWN_TYPE, find_broken_relationships,
)

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

User = get_user_model()


def make_standard(name='Std', scope=DocumentationStandard.SCOPE_ALL, scope_value='', reqs=()):
    std = DocumentationStandard.objects.create(name=name, scope=scope, scope_value=scope_value)
    for i, (kind, params, weight) in enumerate(reqs):
        R.objects.create(standard=std, title=f'{kind} {i}', kind=kind,
                         params=validate_params(kind, params), weight=weight,
                         description='Because auditors ask for it.', order=i)
    return std


def make_doc(org, title, tags=(), category=None, **kw):
    kw.setdefault('body', 'x')
    doc = Document.objects.create(organization=org, title=title, category=category, **kw)
    for t in tags:
        tag, _ = Tag.objects.get_or_create(organization=org, slug=t, defaults={'name': t})
        doc.tags.add(tag)
    return doc


def only_result(org, std=None, **kw):
    r = scoring.evaluate(org, standards=[std] if std else None, **kw)
    return r.standards[0].results[0]


class ParamValidationTests(TestCase):
    def test_document_kinds_need_a_matcher(self):
        with self.assertRaises(ValidationError):
            validate_params(R.KIND_DOCUMENT_EXISTS, {})
        self.assertEqual(validate_params(R.KIND_DOCUMENT_EXISTS, {'tag': ' dr ', 'junk': 1}),
                         {'tag': 'dr'})

    def test_fresh_needs_days(self):
        with self.assertRaises(ValidationError):
            validate_params(R.KIND_DOCUMENT_FRESH, {'tag': 'x'})
        p = validate_params(R.KIND_DOCUMENT_FRESH, {'tag': 'x', 'max_age_days': '30'})
        self.assertEqual(p['max_age_days'], 30)
        self.assertEqual(p['basis'], 'reviewed_or_updated')

    def test_asset_fields_validated_against_model(self):
        p = validate_params(R.KIND_ASSET_FIELDS, {'asset_type': 'server',
                                                  'fields': ['serial_number', 'warranty_expiry']})
        self.assertEqual(p['fields'], ['serial_number', 'warranty_expiry'])
        for bad in (['location'], ['id'], ['is_rackmount'], []):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                validate_params(R.KIND_ASSET_FIELDS, {'fields': bad})
        with self.assertRaises(ValidationError):
            validate_params(R.KIND_ASSET_FIELDS, {'asset_type': 'spaceship', 'fields': ['model']})

    def test_relationship_target_kinds(self):
        self.assertEqual(validate_params(R.KIND_RELATIONSHIP_PRESENT, {})['target_kinds'],
                         ['document', 'contact'])
        with self.assertRaises(ValidationError):
            validate_params(R.KIND_RELATIONSHIP_PRESENT, {'target_kinds': ['password']})


class RequirementKindTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Acme', slug='rd-acme')
        cls.owner = User.objects.create_user('rd_owner', 'o@x.com', 'pw', first_name='Olive', last_name='Owner')

    # -- document_exists ----------------------------------------------------
    def test_document_exists(self):
        std = make_standard(reqs=[(R.KIND_DOCUMENT_EXISTS,
                                   {'tag': 'dr', 'title_contains': 'recovery|disaster'}, 1)])
        res = only_result(self.org, std)
        self.assertEqual(res.status, scoring.UNMET)
        self.assertIn('No published document', res.explanation)
        self.assertIn('Because auditors ask for it.', res.explanation)
        self.assertIn('/docs/create/', res.fix.url)
        self.assertIn('tags=dr', res.fix.url)
        # wrong tag / archived / draft / template docs don't count
        make_doc(self.org, 'Disaster recovery', tags=['other'])
        make_doc(self.org, 'Recovery old', tags=['dr'], is_archived=True)
        make_doc(self.org, 'Recovery draft', tags=['dr'], is_draft=True)
        make_doc(self.org, 'Recovery tpl', tags=['dr'], is_template=True)
        make_doc(self.org, 'Recovery unpublished', tags=['dr'], is_published=False)
        self.assertEqual(only_result(self.org, std).status, scoring.UNMET)
        doc = make_doc(self.org, 'Disaster Recovery Plan', tags=['DR'], owner=self.owner)
        res = only_result(self.org, std)
        self.assertEqual(res.status, scoring.MET)
        self.assertEqual([r.id for r in res.records], [doc.id])
        self.assertEqual(res.owner, self.owner)

    def test_document_exists_by_category(self):
        cat = DocumentCategory.objects.create(organization=self.org, name='Network Diagrams')
        std = make_standard(reqs=[(R.KIND_DOCUMENT_EXISTS, {'category': 'network diagrams'}, 1)])
        self.assertEqual(only_result(self.org, std).status, scoring.UNMET)
        make_doc(self.org, 'Main site', category=cat)
        self.assertEqual(only_result(self.org, std).status, scoring.MET)

    def test_other_customers_docs_dont_count(self):
        other = Organization.objects.create(name='Other', slug='rd-other')
        make_doc(other, 'Recovery', tags=['dr'])
        std = make_standard(reqs=[(R.KIND_DOCUMENT_EXISTS, {'tag': 'dr'}, 1)])
        self.assertEqual(only_result(self.org, std).status, scoring.UNMET)

    # -- document_fresh -----------------------------------------------------
    def test_document_fresh(self):
        std = make_standard(reqs=[(R.KIND_DOCUMENT_FRESH,
                                   {'tag': 'net', 'max_age_days': 30, 'basis': 'reviewed'}, 1)])
        self.assertEqual(only_result(self.org, std).status, scoring.UNMET)
        doc = make_doc(self.org, 'Network', tags=['net'], owner=self.owner)
        res = only_result(self.org, std)
        self.assertEqual(res.status, scoring.UNMET)
        self.assertIn('never been reviewed', res.explanation)
        self.assertEqual(res.owner, self.owner)
        Document.objects.filter(pk=doc.pk).update(last_reviewed_at=timezone.now() - timedelta(days=45))
        res = only_result(self.org, std)
        self.assertEqual(res.status, scoring.UNMET)
        self.assertIn('45 days ago', res.explanation)
        Document.objects.filter(pk=doc.pk).update(last_reviewed_at=timezone.now() - timedelta(days=5))
        self.assertEqual(only_result(self.org, std).status, scoring.MET)

    def test_document_fresh_updated_counts_by_default(self):
        std = make_standard(reqs=[(R.KIND_DOCUMENT_FRESH, {'tag': 'net', 'max_age_days': 30}, 1)])
        make_doc(self.org, 'Network', tags=['net'])  # updated_at = now
        self.assertEqual(only_result(self.org, std).status, scoring.MET)
        later = timezone.now() + timedelta(days=60)
        self.assertEqual(only_result(self.org, std, now=later).status, scoring.UNMET)

    # -- document_owner -----------------------------------------------------
    def test_document_owner(self):
        std = make_standard(reqs=[(R.KIND_DOCUMENT_OWNER, {'tag': 'net'}, 1)])
        self.assertEqual(only_result(self.org, std).status, scoring.UNMET)
        doc = make_doc(self.org, 'Network', tags=['net'])
        res = only_result(self.org, std)
        self.assertEqual(res.status, scoring.UNMET)
        self.assertIn('no owner', res.explanation)
        Document.objects.filter(pk=doc.pk).update(owner=self.owner)
        res = only_result(self.org, std)
        self.assertEqual(res.status, scoring.MET)
        self.assertEqual(res.owner, self.owner)

    # -- asset_fields -------------------------------------------------------
    def test_asset_fields(self):
        std = make_standard(reqs=[(R.KIND_ASSET_FIELDS,
                                   {'asset_type': 'server', 'fields': ['serial_number', 'warranty_expiry']}, 1)])
        res = only_result(self.org, std)
        self.assertEqual(res.status, scoring.NOT_APPLICABLE)
        Asset.objects.create(organization=self.org, name='ws1', asset_type='workstation')
        self.assertEqual(only_result(self.org, std).status, scoring.NOT_APPLICABLE)
        a = Asset.objects.create(organization=self.org, name='srv1', asset_type='server',
                                 serial_number='S1')
        res = only_result(self.org, std)
        self.assertEqual(res.status, scoring.UNMET)
        self.assertEqual(res.records[0].id, a.id)
        self.assertIn('warranty expiry', res.records[0].note)
        self.assertNotIn('serial', res.records[0].note)
        Asset.objects.filter(pk=a.pk).update(warranty_expiry=timezone.now().date())
        self.assertEqual(only_result(self.org, std).status, scoring.MET)

    def test_asset_fields_inherits_standard_asset_type(self):
        std = make_standard(scope=DocumentationStandard.SCOPE_ASSET_TYPE, scope_value='firewall',
                            reqs=[(R.KIND_ASSET_FIELDS, {'fields': ['manufacturer']}, 1)])
        Asset.objects.create(organization=self.org, name='srv', asset_type='server')
        Asset.objects.create(organization=self.org, name='fw', asset_type='firewall', manufacturer='')
        res = only_result(self.org, std)
        self.assertEqual(res.status, scoring.UNMET)
        self.assertEqual([r.label for r in res.records], ['fw'])

    # -- contact_role -------------------------------------------------------
    def test_contact_role(self):
        std = make_standard(reqs=[(R.KIND_CONTACT_ROLE, {'title_contains': 'billing|finance'}, 1)])
        Contact.objects.create(organization=self.org, first_name='A', last_name='B', title='CEO')
        res = only_result(self.org, std)
        self.assertEqual(res.status, scoring.UNMET)
        self.assertIn('no contact', res.explanation)
        Contact.objects.create(organization=self.org, first_name='C', last_name='D', title='Finance Lead')
        res = only_result(self.org, std)
        self.assertEqual(res.status, scoring.MET)
        self.assertEqual(res.records[0].label, 'C D')

    def test_contact_role_min_count(self):
        std = make_standard(reqs=[(R.KIND_CONTACT_ROLE, {'title_contains': 'it', 'min_count': 2}, 1)])
        Contact.objects.create(organization=self.org, first_name='A', last_name='B', title='IT Manager')
        res = only_result(self.org, std)
        self.assertEqual(res.status, scoring.UNMET)
        self.assertIn('only 1 contact', res.explanation)

    # -- credential_reference -----------------------------------------------
    def test_credential_reference(self):
        std = make_standard(reqs=[(R.KIND_CREDENTIAL_REFERENCE, {'title_contains': 'global admin'}, 1)])
        Password.objects.create(organization=self.org, title='Global Admin (personal)',
                                encrypted_password='x', is_personal=True)
        self.assertEqual(only_result(self.org, std).status, scoring.UNMET)
        p = Password.objects.create(organization=self.org, title='M365 Global Admin',
                                    encrypted_password='x')
        res = only_result(self.org, std)
        self.assertEqual(res.status, scoring.MET)
        self.assertEqual(res.records[0].id, p.id)

    def test_credential_reference_by_tag(self):
        std = make_standard(reqs=[(R.KIND_CREDENTIAL_REFERENCE, {'tag': 'm365'}, 1)])
        p = Password.objects.create(organization=self.org, title='Admin', encrypted_password='x')
        self.assertEqual(only_result(self.org, std).status, scoring.UNMET)
        p.tags.add(Tag.objects.create(organization=self.org, name='M365', slug='m365'))
        self.assertEqual(only_result(self.org, std).status, scoring.MET)

    def test_credential_reference_never_decrypts_or_selects_secrets(self):
        std = make_standard(reqs=[(R.KIND_CREDENTIAL_REFERENCE, {'title_contains': 'admin'}, 1)])
        Password.objects.create(organization=self.org, title='Admin', username='SENSITIVE-USER',
                                notes='SENSITIVE-NOTE', encrypted_password='SENSITIVE-CIPHER')
        with mock.patch.object(Password, 'get_password', side_effect=AssertionError('decrypted')), \
                CaptureQueriesContext(connection) as ctx:
            res = only_result(self.org, std)
        self.assertEqual(res.status, scoring.MET)
        vault_sql = [q['sql'] for q in ctx.captured_queries if '"passwords"' in q['sql']]
        self.assertTrue(vault_sql)
        for sql in vault_sql:
            for col in ('encrypted_password', 'otp_secret', 'license_key', '"username"', '"notes"'):
                self.assertNotIn(col, sql)

    # -- relationship_present -----------------------------------------------
    def test_relationship_present(self):
        std = make_standard(reqs=[(R.KIND_RELATIONSHIP_PRESENT, {'asset_type': 'server'}, 1)])
        self.assertEqual(only_result(self.org, std).status, scoring.NOT_APPLICABLE)
        a1 = Asset.objects.create(organization=self.org, name='srv1', asset_type='server')
        a2 = Asset.objects.create(organization=self.org, name='srv2', asset_type='server')
        doc = make_doc(self.org, 'Runbook')
        contact = Contact.objects.create(organization=self.org, first_name='A', last_name='B')
        Relationship.objects.create(organization=self.org, source_type='asset', source_id=a1.pk,
                                    target_type='document', target_id=doc.pk)
        # a broken link doesn't count
        Relationship.objects.create(organization=self.org, source_type='contact', source_id=999999,
                                    target_type='asset', target_id=a2.pk)
        res = only_result(self.org, std)
        self.assertEqual(res.status, scoring.UNMET)
        self.assertEqual([r.id for r in res.records], [a2.id])
        self.assertIn('/assets/relationships/create/', res.fix.url)
        Relationship.objects.create(organization=self.org, source_type='contact', source_id=contact.pk,
                                    target_type='asset', target_id=a2.pk)
        self.assertEqual(only_result(self.org, std).status, scoring.MET)

    def test_relationship_target_kind_filter_and_primary_contact(self):
        std = make_standard(reqs=[(R.KIND_RELATIONSHIP_PRESENT,
                                   {'asset_type': 'server', 'target_kinds': ['contact']}, 1)])
        contact = Contact.objects.create(organization=self.org, first_name='A', last_name='B')
        a = Asset.objects.create(organization=self.org, name='srv', asset_type='server')
        doc = make_doc(self.org, 'Runbook')
        Relationship.objects.create(organization=self.org, source_type='asset', source_id=a.pk,
                                    target_type='document', target_id=doc.pk)
        self.assertEqual(only_result(self.org, std).status, scoring.UNMET)
        Asset.objects.filter(pk=a.pk).update(primary_contact=contact)
        self.assertEqual(only_result(self.org, std).status, scoring.MET)


class ExceptionScopeAndScoreTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.managed = Organization.objects.create(name='Managed', slug='rd-m', organization_type='fully_managed')
        cls.breakfix = Organization.objects.create(name='BreakFix', slug='rd-b', organization_type='break_fix')

    def test_exception_counts_as_excepted_until_it_expires(self):
        std = make_standard(reqs=[(R.KIND_DOCUMENT_EXISTS, {'tag': 'dr'}, 1)])
        req = std.requirements.get()
        exc = StandardException.objects.create(
            standard=std, organization=self.managed, requirement=req, reason='No on-prem kit',
            expires_at=timezone.now() + timedelta(days=10))
        res = only_result(self.managed, std)
        self.assertEqual(res.status, scoring.EXCEPTED)
        self.assertIn('No on-prem kit', res.explanation)
        self.assertIsNone(res.fix)
        self.assertEqual(res.exception, exc)
        self.assertEqual(scoring.evaluate(self.managed, [std]).score, 100.0)
        # other customer unaffected
        self.assertEqual(only_result(self.breakfix, std).status, scoring.UNMET)
        # expired
        later = timezone.now() + timedelta(days=11)
        self.assertEqual(only_result(self.managed, std, now=later).status, scoring.UNMET)

    def test_whole_standard_exception(self):
        std = make_standard(reqs=[(R.KIND_DOCUMENT_EXISTS, {'tag': 'a'}, 1),
                                  (R.KIND_CONTACT_ROLE, {'title_contains': 'cfo'}, 1)])
        StandardException.objects.create(standard=std, organization=self.managed, reason='n/a')
        r = scoring.evaluate(self.managed, [std])
        self.assertEqual({x.status for x in r.standards[0].results}, {scoring.EXCEPTED})

    def test_exception_does_not_override_met(self):
        std = make_standard(reqs=[(R.KIND_DOCUMENT_EXISTS, {'tag': 'dr'}, 1)])
        make_doc(self.managed, 'DR', tags=['dr'])
        StandardException.objects.create(standard=std, organization=self.managed, reason='x')
        self.assertEqual(only_result(self.managed, std).status, scoring.MET)

    def test_scope_by_org_type(self):
        std = make_standard(scope=DocumentationStandard.SCOPE_ORG_TYPE, scope_value='fully_managed',
                            reqs=[(R.KIND_DOCUMENT_EXISTS, {'tag': 'dr'}, 1)])
        res = scoring.evaluate_many([self.managed, self.breakfix], [std])
        self.assertEqual(len(res[self.managed.pk].standards), 1)
        self.assertEqual(len(res[self.breakfix.pk].standards), 0)
        self.assertIsNone(res[self.breakfix.pk].score)

    def test_scope_by_asset_type(self):
        std = make_standard(scope=DocumentationStandard.SCOPE_ASSET_TYPE, scope_value='firewall',
                            reqs=[(R.KIND_DOCUMENT_EXISTS, {'tag': 'fw'}, 1)])
        Asset.objects.create(organization=self.breakfix, name='fw', asset_type='firewall')
        Asset.objects.create(organization=self.managed, name='srv', asset_type='server')
        res = scoring.evaluate_many([self.managed, self.breakfix], [std])
        self.assertEqual(len(res[self.managed.pk].standards), 0)
        self.assertEqual(len(res[self.breakfix.pk].standards), 1)

    def test_standard_clean_validates_scope_value(self):
        std = DocumentationStandard(name='x', scope=DocumentationStandard.SCOPE_ORG_TYPE, scope_value='nope')
        with self.assertRaises(ValidationError):
            std.clean()

    def test_inactive_standard_ignored(self):
        std = make_standard(reqs=[(R.KIND_DOCUMENT_EXISTS, {'tag': 'dr'}, 1)])
        std.is_active = False
        std.save()
        self.assertEqual(scoring.evaluate(self.managed).standards, [])

    def test_score_math(self):
        # met (w3) + unmet (w1) + excepted (w2) + not applicable (w5) -> (3+2)/(3+1+2)
        std = make_standard(reqs=[
            (R.KIND_DOCUMENT_EXISTS, {'tag': 'have'}, 3),
            (R.KIND_DOCUMENT_EXISTS, {'tag': 'missing'}, 1),
            (R.KIND_CONTACT_ROLE, {'title_contains': 'cfo'}, 2),
            (R.KIND_ASSET_FIELDS, {'asset_type': 'server', 'fields': ['model']}, 5),
        ])
        make_doc(self.managed, 'Have', tags=['have'])
        StandardException.objects.create(
            standard=std, organization=self.managed, reason='no CFO',
            requirement=std.requirements.get(kind=R.KIND_CONTACT_ROLE))
        r = scoring.evaluate(self.managed, [std])
        s = r.standards[0]
        self.assertEqual([x.status for x in s.results],
                         [scoring.MET, scoring.UNMET, scoring.EXCEPTED, scoring.NOT_APPLICABLE])
        self.assertEqual(s.applicable_weight, 6)
        self.assertEqual(s.satisfied_weight, 5)
        self.assertEqual(s.score, 83.3)
        self.assertEqual(r.score, 83.3)
        for x in s.results:
            self.assertTrue(x.explanation.strip())
        self.assertEqual(len(r.unmet), 1)
        self.assertEqual(r.unmet[0][1].owner_label, 'Unassigned')

    def test_score_across_standards_is_weighted(self):
        a = make_standard('A', reqs=[(R.KIND_DOCUMENT_EXISTS, {'tag': 'x'}, 1)])
        b = make_standard('B', reqs=[(R.KIND_DOCUMENT_EXISTS, {'tag': 'y'}, 3)])
        make_doc(self.managed, 'Y', tags=['y'])
        r = scoring.evaluate(self.managed, [a, b])
        self.assertEqual(r.score, 75.0)

    def test_evaluate_is_read_only(self):
        std = make_standard(reqs=[(R.KIND_DOCUMENT_EXISTS, {'tag': 'x'}, 1)])
        with CaptureQueriesContext(connection) as ctx:
            scoring.evaluate(self.managed, [std])
        for q in ctx.captured_queries:
            self.assertTrue(q['sql'].lstrip().upper().startswith('SELECT'), q['sql'])


class QueryCountTests(TestCase):
    """Evaluating many customers costs a fixed number of queries."""

    @classmethod
    def setUpTestData(cls):
        cls.std = make_standard(reqs=[
            (R.KIND_DOCUMENT_EXISTS, {'tag': 'dr'}, 1),
            (R.KIND_DOCUMENT_FRESH, {'tag': 'dr', 'max_age_days': 90}, 1),
            (R.KIND_DOCUMENT_OWNER, {'tag': 'dr'}, 1),
            (R.KIND_ASSET_FIELDS, {'asset_type': 'server', 'fields': ['serial_number', 'model']}, 1),
            (R.KIND_CONTACT_ROLE, {'title_contains': 'it'}, 1),
            (R.KIND_CREDENTIAL_REFERENCE, {'title_contains': 'admin'}, 1),
            (R.KIND_RELATIONSHIP_PRESENT, {'asset_type': 'server'}, 1),
        ])
        cls.std2 = make_standard('Firewalls', scope=DocumentationStandard.SCOPE_ASSET_TYPE,
                                 scope_value='firewall',
                                 reqs=[(R.KIND_ASSET_FIELDS, {'fields': ['firmware_version']}, 1)])
        owner = User.objects.create_user('rd_q', 'q@x.com', 'pw')
        cls.orgs = []
        for i in range(12):
            org = Organization.objects.create(name=f'Q{i}', slug=f'rd-q{i}')
            cls.orgs.append(org)
            for j in range(3):
                doc = make_doc(org, f'DR {j}', tags=['dr'], owner=owner if j else None)
                a = Asset.objects.create(organization=org, name=f's{j}', asset_type='server',
                                         serial_number='x' if j else '')
                Asset.objects.create(organization=org, name=f'fw{j}', asset_type='firewall')
                Relationship.objects.create(organization=org, source_type='asset', source_id=a.pk,
                                            target_type='document', target_id=doc.pk)
                Contact.objects.create(organization=org, first_name='C', last_name=str(j), title='IT')
                Password.objects.create(organization=org, title=f'Admin {j}', encrypted_password='x')
            StandardException.objects.create(standard=cls.std, organization=org, reason='r',
                                             requirement=cls.std.requirements.first())

    def _count(self, orgs):
        standards = scoring.active_standards()
        with CaptureQueriesContext(connection) as ctx:
            res = scoring.evaluate_many(orgs, standards)
        return len(ctx.captured_queries), res

    def test_query_count_is_bounded_and_flat(self):
        few, _ = self._count(self.orgs[:2])
        many, res = self._count(self.orgs)
        self.assertLessEqual(many, 15)
        self.assertEqual(few, many)
        self.assertEqual(len(res), 12)
        self.assertTrue(all(len(r.standards) == 2 for r in res.values()))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organization.objects.create(name='Alpha', slug='rd-va')
        cls.org_b = Organization.objects.create(name='Bravo', slug='rd-vb')
        cls.std = make_standard('M365', reqs=[
            (R.KIND_DOCUMENT_EXISTS, {'tag': 'm365'}, 1),
            (R.KIND_CREDENTIAL_REFERENCE, {'title_contains': 'admin'}, 1),
        ])
        Password.objects.create(organization=cls.org_a, title='Tenant Admin', username='SENSITIVE-USER',
                                notes='SENSITIVE-NOTE', encrypted_password='SENSITIVE-CIPHER',
                                license_key='SENSITIVE-LICENSE')
        cls.role_docs = RoleTemplate.objects.create(name='Docs only', organization=cls.org_a,
                                                    vault_view=False, assets_view=False)
        cls.role_full = RoleTemplate.objects.create(name='Full', organization=cls.org_a)
        cls.role_nodocs = RoleTemplate.objects.create(name='No docs', organization=cls.org_a,
                                                      docs_view=False)
        cls.superuser = User.objects.create_user('rd_su', 'su@x.com', 'pw', is_superuser=True, is_staff=True)

    def _staff(self):
        user = User.objects.create_user('rd_staff', 's@x.com', 'pw')
        user.profile.user_type = UserType.STAFF
        user.profile.save()
        return user

    def _customer(self, name, org, role):
        user = User.objects.create_user(name, f'{name}@x.com', 'pw')
        Membership.objects.create(user=user, organization=org, role='readonly', role_template=role)
        return user

    def _get(self, user, url):
        self.client.force_login(user)
        return self.client.get(url)

    def url(self, org):
        return reverse('readiness:org_readiness', kwargs={'org_id': org.pk})

    def test_customer_cannot_view_other_customer(self):
        user = self._customer('rd_cust_b', self.org_b, self.role_full)
        self.assertEqual(self._get(user, self.url(self.org_a)).status_code, 404)

    def test_customer_without_docs_view_gets_404(self):
        user = self._customer('rd_cust_nodocs', self.org_a, self.role_nodocs)
        self.assertEqual(self._get(user, self.url(self.org_a)).status_code, 404)

    def test_customer_with_docs_view_sees_own_read_only(self):
        user = self._customer('rd_cust_a', self.org_a, self.role_docs)
        r = self._get(user, self.url(self.org_a))
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('Read-only view', body)
        self.assertNotIn('Create the document', body)
        self.assertNotIn('Accept a gap', body)
        # no vault_view: the credential is not named
        self.assertNotIn('Tenant Admin', body)
        self.assertIn('(hidden credential)', body)
        for secret in ('SENSITIVE-USER', 'SENSITIVE-NOTE', 'SENSITIVE-CIPHER', 'SENSITIVE-LICENSE'):
            self.assertNotIn(secret, body)
        # overview lists only their customer; staff pages are forbidden
        r = self._get(user, reverse('readiness:overview'))
        self.assertContains(r, 'Alpha')
        self.assertNotContains(r, 'Bravo')
        for name in ('repair_queue', 'standard_list', 'standard_create', 'broken_relationships'):
            with self.subTest(name=name):
                self.assertEqual(self._get(user, reverse(f'readiness:{name}')).status_code, 403)
        r = self.client.post(reverse('readiness:exception_add', kwargs={'org_id': self.org_a.pk}),
                             {'standard': self.std.pk, 'reason': 'x'})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(StandardException.objects.exists())

    def test_staff_sees_credential_title_but_no_secrets(self):
        r = self._get(self._staff(), self.url(self.org_a))
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('Tenant Admin', body)
        self.assertIn('Create the document', body)
        for secret in ('SENSITIVE-USER', 'SENSITIVE-NOTE', 'SENSITIVE-CIPHER', 'SENSITIVE-LICENSE'):
            self.assertNotIn(secret, body)

    def test_staff_pages_render(self):
        staff = self._staff()
        for name in ('overview', 'repair_queue', 'standard_list', 'standard_create', 'broken_relationships'):
            with self.subTest(name=name):
                self.assertEqual(self._get(staff, reverse(f'readiness:{name}')).status_code, 200)
        r = self._get(staff, reverse('readiness:repair_queue') + f'?customer={self.org_a.pk}')
        self.assertContains(r, 'M365')
        self.assertContains(r, 'Unassigned')
        r = self._get(staff, reverse('readiness:standard_edit', kwargs={'pk': self.std.pk}))
        self.assertEqual(r.status_code, 200)

    def test_exception_add_and_remove_is_audited(self):
        from audit.models import AuditLog
        staff = self._staff()
        self.client.force_login(staff)
        req = self.std.requirements.get(kind=R.KIND_DOCUMENT_EXISTS)
        r = self.client.post(reverse('readiness:exception_add', kwargs={'org_id': self.org_a.pk}),
                             {'standard': self.std.pk, 'requirement': req.pk, 'reason': 'Not on M365'})
        self.assertEqual(r.status_code, 302)
        exc = StandardException.objects.get()
        self.assertEqual(exc.created_by, staff)
        self.assertTrue(AuditLog.objects.filter(object_type='standardexception', action='create').exists())
        self.assertEqual(only_result(self.org_a, self.std).status, scoring.EXCEPTED)
        r = self.client.post(reverse('readiness:exception_delete', kwargs={'pk': exc.pk}))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(StandardException.objects.exists())
        self.assertTrue(AuditLog.objects.filter(object_type='standardexception', action='delete').exists())

    def test_exception_requires_reason(self):
        self.client.force_login(self._staff())
        self.client.post(reverse('readiness:exception_add', kwargs={'org_id': self.org_a.pk}),
                         {'standard': self.std.pk, 'reason': '  '})
        self.assertFalse(StandardException.objects.exists())

    def _formset_post(self, standard, reqs, extra=None):
        data = {'name': standard.get('name', 'New std'), 'description': '', 'scope': 'all',
                'is_active': 'on', 'req-TOTAL_FORMS': str(len(reqs)),
                'req-INITIAL_FORMS': str(sum(1 for r in reqs if r.get('id'))),
                'req-MIN_NUM_FORMS': '0', 'req-MAX_NUM_FORMS': '1000'}
        data.update(extra or {})
        for i, r in enumerate(reqs):
            for k, v in r.items():
                if isinstance(v, list):
                    data[f'req-{i}-{k}'] = v
                else:
                    data[f'req-{i}-{k}'] = v
        return data

    def test_create_and_edit_standard_bumps_version(self):
        self.client.force_login(self._staff())
        data = self._formset_post({'name': 'Servers'}, [{
            'title': 'Server fields', 'kind': R.KIND_ASSET_FIELDS, 'weight': '2', 'order': '0',
            'description': 'Warranty claims need it.', 'p_asset_type': 'server',
            'p_fields': ['serial_number', 'manufacturer'], 'p_basis': 'reviewed_or_updated'}])
        r = self.client.post(reverse('readiness:standard_create'), data)
        self.assertEqual(r.status_code, 302, getattr(r, 'context', None) and r.context['formset'].errors)
        std = DocumentationStandard.objects.get(name='Servers')
        self.assertEqual(std.version, 1)
        req = std.requirements.get()
        self.assertEqual(req.params, {'asset_type': 'server', 'fields': ['serial_number', 'manufacturer']})

        # unchanged re-save keeps the version
        base = {'id': str(req.pk), 'title': 'Server fields', 'kind': R.KIND_ASSET_FIELDS, 'weight': '2',
                'order': '0', 'description': 'Warranty claims need it.', 'p_asset_type': 'server',
                'p_fields': ['serial_number', 'manufacturer'], 'p_basis': 'reviewed_or_updated'}
        r = self.client.post(reverse('readiness:standard_edit', kwargs={'pk': std.pk}),
                             self._formset_post({'name': 'Servers'}, [base]))
        self.assertEqual(r.status_code, 302)
        std.refresh_from_db()
        self.assertEqual(std.version, 1)

        # changing a param bumps it, and keeps the requirement row (exceptions survive)
        changed = dict(base, p_fields=['serial_number'])
        r = self.client.post(reverse('readiness:standard_edit', kwargs={'pk': std.pk}),
                             self._formset_post({'name': 'Servers'}, [changed]))
        self.assertEqual(r.status_code, 302)
        std.refresh_from_db()
        self.assertEqual(std.version, 2)
        self.assertEqual(std.requirements.get().pk, req.pk)

    def test_invalid_params_rejected_in_form(self):
        self.client.force_login(self._staff())
        data = self._formset_post({'name': 'Bad'}, [{
            'title': 'x', 'kind': R.KIND_DOCUMENT_EXISTS, 'weight': '1', 'order': '0',
            'p_basis': 'reviewed_or_updated'}])
        r = self.client.post(reverse('readiness:standard_create'), data)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(DocumentationStandard.objects.filter(name='Bad').exists())


class BrokenRelationshipTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Alpha', slug='rd-ba')
        cls.other = Organization.objects.create(name='Other', slug='rd-bo')
        cls.asset = Asset.objects.create(organization=cls.org, name='srv', asset_type='server')
        cls.doc = make_doc(cls.org, 'Doc')
        cls.foreign_doc = make_doc(cls.other, 'Foreign')
        cls.ok = Relationship.objects.create(organization=cls.org, source_type='asset', source_id=cls.asset.pk,
                                             target_type='document', target_id=cls.doc.pk)
        cls.missing = Relationship.objects.create(organization=cls.org, source_type='asset',
                                                  source_id=cls.asset.pk, target_type='password',
                                                  target_id=987654)
        cls.cross = Relationship.objects.create(organization=cls.org, source_type='asset',
                                                source_id=cls.asset.pk, target_type='document',
                                                target_id=cls.foreign_doc.pk)
        cls.unknown = Relationship.objects.create(organization=cls.org, source_type='widget', source_id=1,
                                                  target_type='asset', target_id=cls.asset.pk)

    def test_detection(self):
        found = {b.relationship.pk: b for b in find_broken_relationships()}
        self.assertNotIn(self.ok.pk, found)
        self.assertEqual(found[self.missing.pk].reasons, {REASON_MISSING})
        self.assertEqual(found[self.cross.pk].reasons, {REASON_OTHER_CUSTOMER})
        self.assertEqual(found[self.unknown.pk].reasons, {REASON_UNKNOWN_TYPE})
        self.assertEqual(find_broken_relationships([self.other.pk]), [])

    def test_detection_after_source_deleted(self):
        a = Asset.objects.create(organization=self.org, name='gone', asset_type='server')
        rel = Relationship.objects.create(organization=self.org, source_type='asset', source_id=a.pk,
                                          target_type='document', target_id=self.doc.pk)
        a.delete()
        found = {b.relationship.pk: b for b in find_broken_relationships()}
        self.assertEqual(found[rel.pk].source_problem, REASON_MISSING)

    def test_command_reports_without_deleting(self):
        out = StringIO()
        call_command('readiness_find_broken_relationships', stdout=out)
        self.assertIn('3 broken relationship(s) found', out.getvalue())
        self.assertEqual(Relationship.objects.count(), 4)

    def test_command_delete(self):
        out = StringIO()
        call_command('readiness_find_broken_relationships', '--delete', stdout=out)
        self.assertEqual(set(Relationship.objects.values_list('pk', flat=True)),
                         {self.ok.pk, self.cross.pk, self.unknown.pk})
        call_command('readiness_find_broken_relationships', '--delete', '--include-other-customer', stdout=out)
        self.assertEqual(set(Relationship.objects.values_list('pk', flat=True)),
                         {self.ok.pk, self.unknown.pk})

    @override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
    def test_report_view_and_delete(self):
        staff = User.objects.create_user('rd_bstaff', 'b@x.com', 'pw')
        staff.profile.user_type = UserType.STAFF
        staff.profile.save()
        self.client.force_login(staff)
        url = reverse('readiness:broken_relationships')
        r = self.client.get(url)
        self.assertContains(r, 'Alpha')
        self.assertContains(r, 'no longer exists')
        r = self.client.post(url, {'ids': [self.missing.pk, self.ok.pk, self.unknown.pk]})
        self.assertEqual(r.status_code, 302)
        remaining = set(Relationship.objects.values_list('pk', flat=True))
        self.assertNotIn(self.missing.pk, remaining)
        self.assertIn(self.ok.pk, remaining)       # healthy rows are never deleted
        self.assertIn(self.unknown.pk, remaining)  # unknown types are never deleted


class SeedCommandTests(TestCase):
    def test_seed_is_idempotent(self):
        out = StringIO()
        call_command('readiness_seed_samples', stdout=out)
        call_command('readiness_seed_samples', stdout=out)
        std = DocumentationStandard.objects.get(name='Microsoft 365 tenant documentation')
        self.assertEqual(std.requirements.count(), 6)
        self.assertEqual(set(std.requirements.values_list('kind', flat=True)), {
            R.KIND_DOCUMENT_EXISTS, R.KIND_CONTACT_ROLE, R.KIND_CREDENTIAL_REFERENCE,
            R.KIND_DOCUMENT_FRESH})
        self.assertIn('already exists', out.getvalue())
        org = Organization.objects.create(name='Seeded', slug='rd-seed')
        r = scoring.evaluate(org)
        self.assertEqual(r.score, 0.0)
        self.assertTrue(all(x.explanation for x in r.standards[0].results))
