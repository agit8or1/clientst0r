"""
Fixture-driven tests for the IT Glue / Hudu / CSV importers and rollback.

The HTTP layer (`BaseImportService._make_request`) is replaced with a fake that
serves small, realistic payloads spanning two source organizations, so these
tests exercise the real importer code paths end to end against the test DB.

Covers the defects fixed together:
  1. records land in the organization of their *source* org (all-orgs import)
  2. CSV password rows are stored encrypted (title / encrypted_password)
  3. real counts + completed / completed_with_errors / failed outcomes
  4. dry runs write nothing but the job row
  5. rollback keeps edited / referenced records, removes created orgs only
     when unreferenced, is transactional and never claims full success
     when something was left behind
  6. re-running a CSV import does not duplicate rows (natural keys)
"""
from __future__ import annotations

import copy
import shutil
import tempfile
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from assets.models import Asset, Contact
from core.models import Organization
from docs.models import Document
from imports.models import ImportJob, ImportMapping, OrganizationMapping
from imports.services import get_import_service
from vault.models import Password

User = get_user_model()

_TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return copy.deepcopy(self._payload)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ITGLUE = {
    '/organizations': {'data': [
        {'id': '101', 'type': 'organizations', 'attributes': {'name': 'Acme Dental'}},
        {'id': '102', 'type': 'organizations', 'attributes': {'name': 'Globex Logistics'}},
    ], 'meta': {'next-page': None}},
    '/configurations': {'data': [
        {'id': '9001', 'type': 'configurations', 'attributes': {
            'organization-id': 101, 'organization-name': 'Acme Dental',
            'name': 'ACME-DC01', 'configuration-type-name': 'Server',
            'serial-number': 'SN-ACME-1', 'primary-ip': '10.0.0.10',
            'hostname': 'acme-dc01.acme.local'}},
        {'id': '9002', 'type': 'configurations', 'attributes': {
            'organization-id': 102, 'organization-name': 'Globex Logistics',
            'name': 'GLX-FW', 'configuration-type-name': 'Firewall',
            'primary-ip': 'not-an-ip'}},
    ], 'links': {}},
    '/passwords': {'data': [
        {'id': '7001', 'type': 'passwords', 'attributes': {
            'organization-id': 101, 'name': 'Domain Admin',
            'username': 'ACME\\administrator', 'password': 'Acme-S3cret!',
            'url': 'https://acme-dc01.acme.local'}},
        {'id': '7002', 'type': 'passwords', 'attributes': {
            'organization-id': 102, 'name': 'Firewall admin',
            'username': 'admin', 'password': 'Gl0bex#fw'}},
    ], 'links': {}},
    '/documents': {'data': [
        {'id': '5001', 'type': 'documents', 'attributes': {
            'organization-id': 101, 'name': 'Backup procedure', 'body': '# Backups'}},
        {'id': '5002', 'type': 'documents', 'attributes': {
            'organization-id': 102, 'name': 'Backup procedure', 'body': '# Backups'}},
    ], 'links': {}},
}

HUDU = {
    '/api/v1/companies': {'companies': [
        {'id': 1, 'name': 'Initech'},
        {'id': 2, 'name': 'Umbrella Labs'},
    ]},
    '/api/v1/assets': {'assets': [
        {'id': 301, 'company_id': 1, 'company_name': 'Initech', 'name': 'INI-SQL01',
         'asset_layout_name': 'Server', 'asset_fields': [
             {'label': 'Serial Number', 'value': 'INI-123'},
             {'label': 'IP Address', 'value': '192.168.1.5'}]},
        {'id': 302, 'company_id': 2, 'company_name': 'Umbrella Labs', 'name': 'UMB-LAPTOP-7',
         'asset_layout_name': 'Laptop', 'asset_fields': []},
    ]},
    '/api/v1/asset_passwords': {'asset_passwords': [
        {'id': 401, 'company_id': 1, 'name': 'SQL sa', 'username': 'sa', 'password': 'Ini!sa'},
        {'id': 402, 'company_id': 2, 'name': 'Wi-Fi', 'username': '', 'password': 'Umb-wifi'},
    ]},
    '/api/v1/articles': {'articles': [
        {'id': 501, 'company_id': 1, 'name': 'Onboarding', 'content': 'steps'},
        {'id': 502, 'company_id': 2, 'name': 'Offboarding', 'content': 'steps'},
    ]},
}


def _fake_make_request(fixture):
    def _request(self, method, endpoint, **kwargs):
        params = kwargs.get('params') or {}
        page = params.get('page[number]', params.get('page', 1))
        if page != 1:
            # Every fixture fits on one page.
            empty = {k: [] for k in fixture[endpoint]}
            return FakeResponse(empty)
        return FakeResponse(fixture[endpoint])
    return _request


class _ImporterTestBase(TestCase):
    source_type = 'itglue'
    fixture = ITGLUE

    def setUp(self):
        self.user = User.objects.create_user('importer', 'imp@example.com', 'pw')
        self.fixture = copy.deepcopy(type(self).fixture)
        patcher = mock.patch(
            'imports.services.base.BaseImportService._make_request',
            _fake_make_request(self.fixture))
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_job(self, **kwargs):
        defaults = dict(
            source_type=self.source_type, source_url='https://api.example.test',
            source_api_key='k', dry_run=False, started_by=self.user,
            import_assets=True, import_passwords=True, import_documents=True,
        )
        defaults.update(kwargs)
        return ImportJob.objects.create(**defaults)

    def run_job(self, job):
        get_import_service(job).run_import()
        job.refresh_from_db()
        return job

    def assertCountsAddUp(self, job, source_total):
        self.assertEqual(job.items_imported + job.items_skipped + job.items_failed, source_total)
        self.assertEqual(job.total_items, source_total)


# ---------------------------------------------------------------------------
# IT Glue
# ---------------------------------------------------------------------------

class ITGlueAllOrgsImportTests(_ImporterTestBase):

    def test_records_land_in_their_source_organization(self):
        job = self.run_job(self.make_job())

        self.assertEqual(job.status, 'completed')
        self.assertCountsAddUp(job, 6)
        self.assertEqual(job.items_imported, 6)

        acme = Organization.objects.get(name='Acme Dental')
        globex = Organization.objects.get(name='Globex Logistics')
        self.assertEqual(Asset.objects.get(name='ACME-DC01').organization, acme)
        self.assertEqual(Asset.objects.get(name='GLX-FW').organization, globex)
        self.assertIsNone(Asset.objects.get(name='GLX-FW').ip_address)  # invalid IP dropped
        self.assertEqual(Password.objects.get(title='Domain Admin').organization, acme)
        self.assertEqual(Password.objects.get(title='Firewall admin').organization, globex)
        self.assertEqual(Document.objects.get(title='Backup procedure', organization=acme).organization, acme)
        self.assertTrue(Document.objects.filter(title='Backup procedure', organization=globex).exists())
        self.assertFalse(Document.objects.filter(organization__isnull=True).exists())

        # Passwords are encrypted and decrypt to the source value.
        pw = Password.objects.get(title='Domain Admin')
        self.assertNotIn('Acme-S3cret!', pw.encrypted_password)
        self.assertEqual(pw.get_password(), 'Acme-S3cret!')

        # Mappings carry the organization + an updated_at snapshot.
        for m in job.mappings.exclude(target_model='Organization'):
            self.assertIsNotNone(m.target_organization_id, m)
            self.assertIsNotNone(m.target_updated_at, m)
        # Created orgs are recorded so rollback can remove them.
        self.assertEqual(job.mappings.filter(target_model='Organization').count(), 2)
        self.assertEqual(job.organizations_created, 2)

    def test_existing_org_is_matched_not_duplicated(self):
        existing = Organization.objects.create(name='Acme Dental', slug='acme-dental')
        job = self.run_job(self.make_job())
        self.assertEqual(Asset.objects.get(name='ACME-DC01').organization, existing)
        self.assertEqual(job.organizations_matched, 1)
        self.assertEqual(job.organizations_created, 1)

    def test_exact_name_matching_without_fuzzy(self):
        existing = Organization.objects.create(name='acme dental', slug='acme-dental-lc')
        job = self.run_job(self.make_job(use_fuzzy_matching=False))
        self.assertEqual(job.status, 'completed')
        self.assertEqual(Asset.objects.get(name='ACME-DC01').organization, existing)

    def test_partial_failure_is_completed_with_errors(self):
        # A password with no organization cannot be placed in an all-orgs import.
        del self.fixture['/passwords']['data'][1]['attributes']['organization-id']
        job = self.run_job(self.make_job())

        self.assertEqual(job.status, 'completed_with_errors')
        self.assertEqual(job.items_imported, 5)
        self.assertEqual(job.items_failed, 1)
        self.assertCountsAddUp(job, 6)
        self.assertIn('no source organization', job.import_log)

    def test_every_record_failing_is_failed(self):
        for endpoint in ('/configurations', '/passwords', '/documents'):
            for item in self.fixture[endpoint]['data']:
                item['attributes'].pop('organization-id', None)
                item['attributes'].pop('organization-name', None)
        job = self.run_job(self.make_job())

        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.items_imported, 0)
        self.assertEqual(job.items_failed, 6)
        self.assertCountsAddUp(job, 6)
        self.assertTrue(job.error_message)

    def test_rerun_skips_already_imported_records(self):
        self.run_job(self.make_job())
        second = self.run_job(self.make_job())
        self.assertEqual(second.status, 'completed')
        self.assertEqual(second.items_imported, 0)
        self.assertEqual(second.items_skipped, 6)
        self.assertEqual(Asset.objects.count(), 2)

    def test_single_org_import_uses_target_org(self):
        target = Organization.objects.create(name='Target', slug='target')
        job = self.run_job(self.make_job(target_organization=target))
        self.assertEqual(job.status, 'completed')
        self.assertEqual(Asset.objects.filter(organization=target).count(), 2)
        self.assertFalse(Organization.objects.filter(name='Acme Dental').exists())


class DryRunWritesNothingTests(_ImporterTestBase):

    def test_multi_org_dry_run_completes_and_writes_nothing(self):
        orgs_before = Organization.objects.count()
        job = self.run_job(self.make_job(dry_run=True))

        self.assertEqual(job.status, 'completed')
        self.assertEqual(job.items_imported, 6)
        self.assertCountsAddUp(job, 6)
        self.assertEqual(job.organizations_created, 2)
        self.assertIn('DRY RUN', job.import_log)  # log survived the rollback

        self.assertEqual(Organization.objects.count(), orgs_before)
        self.assertEqual(OrganizationMapping.objects.count(), 0)
        self.assertEqual(ImportMapping.objects.count(), 0)
        self.assertEqual(Asset.objects.count(), 0)
        self.assertEqual(Password.objects.count(), 0)
        self.assertEqual(Document.objects.count(), 0)

    def test_dry_run_reports_failures_a_real_run_would_hit(self):
        del self.fixture['/documents']['data'][0]['attributes']['organization-id']
        job = self.run_job(self.make_job(dry_run=True))
        self.assertEqual(job.status, 'completed_with_errors')
        self.assertEqual(job.items_failed, 1)
        self.assertEqual(Document.objects.count(), 0)

    def test_completed_with_errors_dry_run_can_be_promoted(self):
        del self.fixture['/documents']['data'][0]['attributes']['organization-id']
        job = self.run_job(self.make_job(dry_run=True))
        self.user.is_superuser = True
        self.user.save()
        with override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False):
            c = Client()
            c.force_login(self.user)
            c.post(reverse('imports:import_promote', args=[job.pk]))
        job.refresh_from_db()
        self.assertFalse(job.dry_run)
        self.assertEqual(job.status, 'pending')


# ---------------------------------------------------------------------------
# Hudu
# ---------------------------------------------------------------------------

class HuduAllOrgsImportTests(_ImporterTestBase):
    source_type = 'hudu'
    fixture = HUDU

    def test_every_record_type_lands_in_its_company(self):
        job = self.run_job(self.make_job())
        self.assertEqual(job.status, 'completed')
        self.assertCountsAddUp(job, 6)

        initech = Organization.objects.get(name='Initech')
        umbrella = Organization.objects.get(name='Umbrella Labs')
        self.assertEqual(Asset.objects.get(name='INI-SQL01').organization, initech)
        self.assertEqual(str(Asset.objects.get(name='INI-SQL01').ip_address), '192.168.1.5')
        self.assertEqual(Asset.objects.get(name='UMB-LAPTOP-7').organization, umbrella)
        self.assertEqual(Password.objects.get(title='SQL sa').organization, initech)
        self.assertEqual(Password.objects.get(title='Wi-Fi').organization, umbrella)
        self.assertEqual(Password.objects.get(title='Wi-Fi').get_password(), 'Umb-wifi')
        self.assertEqual(Document.objects.get(title='Onboarding').organization, initech)
        self.assertEqual(Document.objects.get(title='Offboarding').organization, umbrella)

    def test_global_article_fails_instead_of_orphan_document(self):
        self.fixture['/api/v1/articles']['articles'][1]['company_id'] = None
        job = self.run_job(self.make_job())
        self.assertEqual(job.status, 'completed_with_errors')
        self.assertEqual(job.items_failed, 1)
        self.assertCountsAddUp(job, 6)
        self.assertFalse(Document.objects.filter(organization__isnull=True).exists())

    def test_dry_run_writes_nothing(self):
        job = self.run_job(self.make_job(dry_run=True))
        self.assertEqual(job.status, 'completed')
        self.assertEqual(Organization.objects.count(), 0)
        self.assertEqual(ImportMapping.objects.count() + OrganizationMapping.objects.count(), 0)


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------

class RollbackSafetyTests(_ImporterTestBase):

    def test_full_rollback_removes_records_and_created_orgs(self):
        pre_existing = Organization.objects.create(name='Acme Dental', slug='acme-dental')
        job = self.run_job(self.make_job())
        stats = job.rollback(self.user)
        job.refresh_from_db()

        self.assertTrue(stats['complete'], stats)
        self.assertEqual(job.status, 'rolled_back')
        self.assertIsNotNone(job.rolled_back_at)
        self.assertEqual(Asset.objects.count(), 0)
        self.assertEqual(Password.objects.count(), 0)
        self.assertEqual(Document.objects.count(), 0)
        # Created org removed, matched (pre-existing) org kept.
        self.assertFalse(Organization.objects.filter(name='Globex Logistics').exists())
        self.assertTrue(Organization.objects.filter(pk=pre_existing.pk).exists())

    def test_record_edited_after_import_is_kept_and_reported(self):
        job = self.run_job(self.make_job())
        edited = Asset.objects.get(name='ACME-DC01')
        edited.notes = 'Tech added warranty info after the import'
        edited.save()

        stats = job.rollback(self.user)
        job.refresh_from_db()

        self.assertTrue(Asset.objects.filter(pk=edited.pk).exists())
        self.assertFalse(Asset.objects.filter(name='GLX-FW').exists())
        self.assertEqual(Password.objects.count(), 0)
        self.assertEqual(len(stats['kept_modified']), 1)
        self.assertIn('ACME-DC01', stats['kept_modified'][0])
        self.assertFalse(stats['complete'])
        self.assertEqual(job.status, 'partially_rolled_back')
        self.assertIsNone(job.rolled_back_at)
        self.assertIn('ACME-DC01', job.import_log)
        # Its org still holds the kept asset, so it stays; the other goes.
        self.assertTrue(Organization.objects.filter(name='Acme Dental').exists())
        self.assertFalse(Organization.objects.filter(name='Globex Logistics').exists())
        self.assertTrue(any('Acme Dental' in k for k in stats['kept_organizations']))
        # The kept record still blocks re-import of the same source record.
        self.assertTrue(job.mappings.filter(target_id=edited.pk, target_model='Asset').exists())

    def test_created_org_referenced_by_new_data_is_kept(self):
        job = self.run_job(self.make_job())
        globex = Organization.objects.get(name='Globex Logistics')
        Contact.objects.create(organization=globex, first_name='New', last_name='Customer')

        stats = job.rollback(self.user)
        job.refresh_from_db()
        self.assertTrue(Organization.objects.filter(pk=globex.pk).exists())
        self.assertFalse(Organization.objects.filter(name='Acme Dental').exists())
        self.assertEqual(job.status, 'partially_rolled_back')
        self.assertTrue(any('Globex' in k for k in stats['kept_organizations']))

    def test_unknown_model_type_is_not_marked_rolled_back(self):
        job = self.run_job(self.make_job())
        ImportMapping.objects.create(
            import_job=job, source_type='widget', source_id='w1',
            target_model='Widget', target_id=1)
        stats = job.rollback(self.user)
        job.refresh_from_db()
        self.assertEqual(job.status, 'partially_rolled_back')
        self.assertTrue(any('Widget' in e for e in stats['errors']))

    def test_rollback_is_atomic(self):
        job = self.run_job(self.make_job())
        with mock.patch('imports.rollback._Dependents.find', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                job.rollback(self.user)
        job.refresh_from_db()
        self.assertEqual(job.status, 'completed')
        self.assertEqual(Asset.objects.count(), 2)
        self.assertEqual(job.mappings.exclude(target_model='Organization').count(), 6)

    def test_partial_import_can_be_rolled_back(self):
        del self.fixture['/passwords']['data'][1]['attributes']['organization-id']
        job = self.run_job(self.make_job())
        self.assertEqual(job.status, 'completed_with_errors')
        self.assertTrue(job.can_rollback())
        job.rollback(self.user)
        job.refresh_from_db()
        self.assertEqual(job.status, 'rolled_back')
        self.assertEqual(Asset.objects.count(), 0)


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

class _CSVTestBase(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp(prefix='imports-test-')
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user('csvuser', 'csv@example.com', 'pw')
        self.org = Organization.objects.create(name='CSV Co', slug='csv-co')

    def make_job(self, target, mappings, body, **kwargs):
        defaults = dict(
            source_type='csv', csv_target_model=target, field_mappings=mappings,
            target_organization=self.org, started_by=self.user, dry_run=False,
            source_file=SimpleUploadedFile('data.csv', body.encode('utf-8'), content_type='text/csv'),
        )
        defaults.update(kwargs)
        return ImportJob.objects.create(**defaults)

    def run_job(self, job):
        get_import_service(job).run_import()
        job.refresh_from_db()
        return job


PASSWORD_CSV = (
    'Name,User,Secret,Link\n'
    'Router admin,admin,R0uter!pass,https://192.168.1.1\n'
    'Office 365,it@csvco.example,M365-pass,https://portal.office.com/\n'
    'Printer,,pr1nt,\n'
)
PASSWORD_MAP = {'Name': 'name', 'User': 'username', 'Secret': 'password', 'Link': 'url'}


class CSVPasswordImportTests(_CSVTestBase):

    def test_rows_import_encrypted_and_decrypt_to_original(self):
        job = self.run_job(self.make_job('password', PASSWORD_MAP, PASSWORD_CSV))
        self.assertEqual(job.status, 'completed')
        self.assertEqual(job.items_imported, 3)
        self.assertEqual(job.total_items, 3)

        expected = {'Router admin': 'R0uter!pass', 'Office 365': 'M365-pass', 'Printer': 'pr1nt'}
        for title, plaintext in expected.items():
            pw = Password.objects.get(organization=self.org, title=title)
            self.assertTrue(pw.encrypted_password)
            self.assertNotIn(plaintext, pw.encrypted_password)
            self.assertEqual(pw.get_password(), plaintext)
        self.assertEqual(Password.objects.get(title='Router admin').username, 'admin')

    def test_rerun_of_same_csv_creates_no_new_rows(self):
        self.run_job(self.make_job('password', PASSWORD_MAP, PASSWORD_CSV))
        second = self.run_job(self.make_job('password', PASSWORD_MAP, PASSWORD_CSV))
        self.assertEqual(Password.objects.count(), 3)
        self.assertEqual(second.items_imported, 0)
        self.assertEqual(second.items_skipped, 3)
        self.assertEqual(second.status, 'completed')

    def test_rerun_with_cosmetic_differences_is_still_a_duplicate(self):
        self.run_job(self.make_job('password', PASSWORD_MAP, PASSWORD_CSV))
        altered = PASSWORD_CSV.replace('Router admin,admin', '  router ADMIN ,Admin').replace(
            'https://portal.office.com/', 'http://portal.office.com')
        second = self.run_job(self.make_job('password', PASSWORD_MAP, altered))
        self.assertEqual(second.items_imported, 0)
        self.assertEqual(Password.objects.count(), 3)

    def test_deleted_record_is_reimported(self):
        self.run_job(self.make_job('password', PASSWORD_MAP, PASSWORD_CSV))
        Password.objects.get(title='Printer').delete()
        second = self.run_job(self.make_job('password', PASSWORD_MAP, PASSWORD_CSV))
        self.assertEqual(second.items_imported, 1)
        self.assertEqual(Password.objects.count(), 3)

    def test_duplicate_rows_within_one_file_import_once(self):
        body = PASSWORD_CSV + 'Router admin,admin,other,https://192.168.1.1\n'
        job = self.run_job(self.make_job('password', PASSWORD_MAP, body))
        self.assertEqual(Password.objects.count(), 3)
        self.assertEqual(job.items_skipped, 1)
        self.assertEqual(job.total_items, 4)

    def test_partial_failure_is_completed_with_errors(self):
        body = PASSWORD_CSV + ',someone,secret,\n'   # no name
        job = self.run_job(self.make_job('password', PASSWORD_MAP, body))
        self.assertEqual(job.status, 'completed_with_errors')
        self.assertEqual(job.items_imported, 3)
        self.assertEqual(job.items_failed, 1)
        self.assertEqual(job.total_items, 4)
        self.assertIn("missing required field 'name'", job.import_log)

    def test_all_rows_failing_is_failed(self):
        body = 'Name,User,Secret,Link\n,a,b,\n,c,d,\n'
        job = self.run_job(self.make_job('password', PASSWORD_MAP, body))
        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.items_failed, 2)
        self.assertEqual(Password.objects.count(), 0)

    def test_dry_run_writes_nothing(self):
        job = self.run_job(self.make_job('password', PASSWORD_MAP, PASSWORD_CSV, dry_run=True))
        self.assertEqual(job.status, 'completed')
        self.assertEqual(job.items_imported, 3)
        self.assertEqual(Password.objects.count(), 0)
        self.assertEqual(ImportMapping.objects.count(), 0)

    def test_rollback_after_edit_keeps_edited_password(self):
        job = self.run_job(self.make_job('password', PASSWORD_MAP, PASSWORD_CSV))
        pw = Password.objects.get(title='Printer')
        pw.notes = 'changed'
        pw.save()
        stats = job.rollback(self.user)
        job.refresh_from_db()
        self.assertEqual(list(Password.objects.values_list('title', flat=True)), ['Printer'])
        self.assertEqual(job.status, 'partially_rolled_back')
        self.assertEqual(len(stats['kept_modified']), 1)
        # The pre-existing target organization is never touched.
        self.assertTrue(Organization.objects.filter(pk=self.org.pk).exists())


class CSVOtherTargetsTests(_CSVTestBase):

    def test_asset_rerun_dedupes_on_serial(self):
        body = 'Name,Serial\nLaptop 1,ABC123\nLaptop 2,DEF456\n'
        mapping = {'Name': 'name', 'Serial': 'serial_number'}
        self.run_job(self.make_job('asset', mapping, body))
        renamed = body.replace('Laptop 1', 'Laptop One')   # same serial = same asset
        second = self.run_job(self.make_job('asset', mapping, renamed))
        self.assertEqual(Asset.objects.count(), 2)
        self.assertEqual(second.items_skipped, 2)

    def test_contact_import_splits_name_and_dedupes_on_email(self):
        body = 'Name,Email\nJane Q Public,jane@example.com\nBob,bob@example.com\n'
        mapping = {'Name': 'name', 'Email': 'email'}
        job = self.run_job(self.make_job('contact', mapping, body))
        self.assertEqual(job.status, 'completed', job.import_log)
        jane = Contact.objects.get(email='jane@example.com')
        self.assertEqual((jane.first_name, jane.last_name), ('Jane', 'Q Public'))
        second = self.run_job(self.make_job('contact', mapping, body))
        self.assertEqual(second.items_skipped, 2)
        self.assertEqual(Contact.objects.count(), 2)

    def test_documents_with_existing_title_get_unique_slug(self):
        Document.objects.create(organization=self.org, title='Runbook', slug='runbook')
        job = self.run_job(self.make_job('document', {'T': 'title', 'B': 'body'}, 'T,B\nRunbook,x\n'))
        self.assertEqual(job.status, 'completed', job.import_log)
        self.assertEqual(Document.objects.filter(title='Runbook').count(), 2)

    def test_shop_inventory_import_rolls_back_fully(self):
        from vehicles.models import ShopInventoryItem
        body = 'Name,Qty\nCAT6,10\nRJ45,500\n'
        job = self.run_job(self.make_job('shop_inventory', {'Name': 'name', 'Qty': 'quantity'}, body))
        self.assertEqual(ShopInventoryItem.objects.count(), 2)
        stats = job.rollback(self.user)
        job.refresh_from_db()
        self.assertTrue(stats['complete'], stats)
        self.assertEqual(job.status, 'rolled_back')
        self.assertEqual(ShopInventoryItem.objects.count(), 0)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ImportOutcomeViewTests(_CSVTestBase):

    def setUp(self):
        super().setUp()
        self.user.is_superuser = True
        self.user.save()
        self.client = Client()
        self.client.force_login(self.user)

    def _start(self, job):
        resp = self.client.post(reverse('imports:import_start', args=[job.pk]))
        return [(m.level_tag, str(m)) for m in get_messages(resp.wsgi_request)]

    def test_partial_import_shows_warning_not_success(self):
        body = PASSWORD_CSV + ',x,y,\n'
        job = self.make_job('password', PASSWORD_MAP, body)
        msgs = self._start(job)
        self.assertTrue(any(level == 'warning' and 'completed with errors' in text
                            for level, text in msgs), msgs)
        self.assertFalse(any(level == 'success' for level, _ in msgs), msgs)

        detail = self.client.get(reverse('imports:import_detail', args=[job.pk]))
        self.assertContains(detail, 'Completed with errors')
        self.assertNotContains(detail, 'badge bg-success">Completed<')

    def test_failed_import_shows_error(self):
        job = self.make_job('password', PASSWORD_MAP, 'Name,User,Secret,Link\n,a,b,\n')
        msgs = self._start(job)
        self.assertTrue(any(level == 'error' for level, _ in msgs), msgs)
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')

    def test_clean_import_shows_success(self):
        job = self.make_job('password', PASSWORD_MAP, PASSWORD_CSV)
        msgs = self._start(job)
        self.assertTrue(any(level == 'success' for level, _ in msgs), msgs)
