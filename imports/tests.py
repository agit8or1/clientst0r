"""
Baseline test coverage for the imports/ app (Phase 7 polish — survey #6).

This is the security-critical data ingestion pipeline (ITGlue / Hudu / CSV /
MagicPlan). Before this file existed the whole app had zero regression
coverage on disk despite handling customer data. The tests here are
deliberately tight: each focuses on one well-defined behavior. They cover
the org-matcher fuzzy logic, the ImportJob state-machine + rollback
guard rails, the unique-together constraints on the mapping models, and
the CSV preview helper.

Future test additions should target the per-source services
(`imports.services.{itglue,hudu,magicplan}`) — those wrap external HTTP
APIs and need mocked fixtures.
"""
from __future__ import annotations

import io

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from assets.models import Asset
from core.models import Organization
from imports.models import ImportJob, ImportMapping, OrganizationMapping
from imports.org_matcher import OrganizationMatcher
from imports.services.csv_importer import read_csv_preview


User = get_user_model()


# ---------------------------------------------------------------------------
# Org matcher — fuzzy name matching for ITGlue / Hudu org consolidation
# ---------------------------------------------------------------------------

class OrganizationMatcherNormalizationTests(TestCase):
    """`normalize_name` is the foundation of every match. If it's wrong,
    every downstream score is wrong."""

    def setUp(self):
        self.matcher = OrganizationMatcher()

    def test_lowercase_and_strip(self):
        self.assertEqual(self.matcher.normalize_name('  Acme Co  '), 'acme')

    def test_strips_common_company_suffixes(self):
        for variant in ['Acme LLC', 'Acme Inc', 'Acme Corp', 'Acme Ltd',
                        'Acme Limited', 'Acme Co', 'Acme Company',
                        'Acme L.L.C.', 'Acme Inc.', 'Acme Corp.', 'Acme Ltd.']:
            with self.subTest(variant=variant):
                self.assertEqual(self.matcher.normalize_name(variant), 'acme')

    def test_strips_comma_form_suffixes(self):
        for variant in ['Acme, LLC', 'Acme, Inc', 'Acme, Inc.', 'Acme, Ltd']:
            with self.subTest(variant=variant):
                self.assertEqual(self.matcher.normalize_name(variant), 'acme')

    def test_strips_special_characters(self):
        # `&` and `!` are stripped; the surrounding spaces collapse to one.
        self.assertEqual(self.matcher.normalize_name('Acme & Sons!'), 'acme sons')

    def test_collapses_whitespace(self):
        # Multiple internal spaces collapse to one. ` Co` is a stripped suffix.
        self.assertEqual(self.matcher.normalize_name('Acme   Widget   Co'), 'acme widget')

    def test_empty_input_returns_empty(self):
        self.assertEqual(self.matcher.normalize_name(''), '')
        self.assertEqual(self.matcher.normalize_name(None), '')


class OrganizationMatcherSimilarityTests(TestCase):
    def setUp(self):
        self.matcher = OrganizationMatcher()

    def test_identical_names_score_100(self):
        self.assertEqual(self.matcher.similarity_score('Acme', 'Acme'), 100)

    def test_suffix_variants_score_high(self):
        # "Acme LLC" vs "Acme Inc" both normalize to "acme" → identical post-normalize.
        self.assertEqual(self.matcher.similarity_score('Acme LLC', 'Acme Inc'), 100)

    def test_completely_different_names_score_low(self):
        self.assertLess(self.matcher.similarity_score('Acme', 'Globex'), 50)

    def test_empty_inputs_score_zero(self):
        self.assertEqual(self.matcher.similarity_score('', 'Acme'), 0)
        self.assertEqual(self.matcher.similarity_score('Acme', ''), 0)


class OrganizationMatcherMatchTests(TestCase):
    def setUp(self):
        self.matcher = OrganizationMatcher(threshold=85)
        Organization.objects.create(name='Widget Co', slug='widget-co')
        Organization.objects.create(name='Globex Industries', slug='globex')

    def test_find_best_match_returns_existing_above_threshold(self):
        # "Widget Company LLC" normalizes to "widget" → matches "Widget Co" → "widget".
        match, score = self.matcher.find_best_match('Widget Company LLC')
        self.assertIsNotNone(match)
        self.assertEqual(match.name, 'Widget Co')
        self.assertGreaterEqual(score, 85)

    def test_find_best_match_returns_none_below_threshold(self):
        match, _score = self.matcher.find_best_match('Completely Unrelated XYZ')
        self.assertIsNone(match)

    def test_match_or_create_returns_existing_match(self):
        org, was_created, score = self.matcher.match_or_create('Widget Company LLC')
        self.assertEqual(org.name, 'Widget Co')
        self.assertFalse(was_created)
        self.assertIsNotNone(score)

    def test_match_or_create_creates_when_no_match(self):
        before = Organization.objects.count()
        org, was_created, _score = self.matcher.match_or_create(
            'Brand New Company', source_id='it-glue-9999',
        )
        self.assertTrue(was_created)
        self.assertEqual(Organization.objects.count(), before + 1)
        self.assertEqual(org.name, 'Brand New Company')
        self.assertIn('Imported from it-glue-9999', org.description)

    def test_match_or_create_dry_run_does_not_save(self):
        before = Organization.objects.count()
        org, was_created, _score = self.matcher.match_or_create(
            'Dry Run Co', dry_run=True,
        )
        self.assertTrue(was_created)
        self.assertIsNone(org.pk)  # unsaved Organization instance
        self.assertEqual(Organization.objects.count(), before)


# ---------------------------------------------------------------------------
# ImportJob model lifecycle
# ---------------------------------------------------------------------------

class ImportJobLifecycleTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Target Co', slug='target-co')
        self.user = User.objects.create_user('importer', password='pw', email='i@x.com')
        self.job = ImportJob.objects.create(
            source_type='itglue', target_organization=self.org,
            started_by=self.user, dry_run=False,
        )

    def test_str_includes_target_and_status(self):
        self.assertIn('IT Glue', str(self.job))
        self.assertIn('Target Co', str(self.job))
        self.assertIn('Pending', str(self.job))

    def test_str_with_no_target_says_all_organizations(self):
        j = ImportJob.objects.create(source_type='itglue', dry_run=True)
        self.assertIn('All Organizations', str(j))

    def test_mark_running_sets_status_and_started_at(self):
        self.assertIsNone(self.job.started_at)
        self.job.mark_running()
        self.assertEqual(self.job.status, 'running')
        self.assertIsNotNone(self.job.started_at)

    def test_mark_completed_sets_completed_at(self):
        self.job.mark_completed()
        self.assertEqual(self.job.status, 'completed')
        self.assertIsNotNone(self.job.completed_at)

    def test_mark_failed_records_error_message(self):
        self.job.mark_failed('boom: connection refused')
        self.assertEqual(self.job.status, 'failed')
        self.assertEqual(self.job.error_message, 'boom: connection refused')
        self.assertIsNotNone(self.job.completed_at)

    def test_add_log_appends_with_timestamp(self):
        self.job.add_log('starting')
        self.job.add_log('next step')
        self.assertIn('starting', self.job.import_log)
        self.assertIn('next step', self.job.import_log)
        # Each line wraps with [YYYY-MM-DD ...] prefix.
        self.assertEqual(self.job.import_log.count('['), 2)

    def test_can_rollback_only_when_completed_non_dryrun(self):
        # pending → no
        self.assertFalse(self.job.can_rollback())
        # completed + non-dry-run → yes
        self.job.mark_completed()
        self.assertTrue(self.job.can_rollback())
        # dry-run + completed → no
        dry = ImportJob.objects.create(source_type='itglue', dry_run=True)
        dry.mark_completed()
        self.assertFalse(dry.can_rollback())

    def test_can_rollback_false_when_already_rolled_back(self):
        from django.utils import timezone
        self.job.mark_completed()
        self.job.rolled_back_at = timezone.now()
        self.job.save(update_fields=['rolled_back_at'])
        self.assertFalse(self.job.can_rollback())


class ImportJobRollbackTests(TestCase):
    """Exercises the actual rollback flow with real assets + mappings.

    Confirms two load-bearing properties:
      1. Assets created during import are deleted on rollback.
      2. Organizations that were *matched* (already existed) are NEVER
         deleted — only orgs that the import created itself.
    """

    def setUp(self):
        self.user = User.objects.create_user('rollback-user', password='pw', email='r@x.com')

        # Pre-existing org that should survive rollback.
        self.existing_org = Organization.objects.create(name='Already Here', slug='already-here')

        self.job = ImportJob.objects.create(
            source_type='itglue', dry_run=False, status='completed',
            started_by=self.user,
        )

        # Org that was created *during* the import — should be deleted on rollback.
        self.created_org = Organization.objects.create(name='Made By Import', slug='made-by-import')

        OrganizationMapping.objects.create(
            import_job=self.job, source_id='itglue-100',
            source_name='Already Here', organization=self.existing_org,
            was_created=False, match_score=92,
        )
        OrganizationMapping.objects.create(
            import_job=self.job, source_id='itglue-101',
            source_name='Made By Import', organization=self.created_org,
            was_created=True,
        )
        # Two assets that should be deleted on rollback, one per org.
        self.asset_existing = Asset.objects.create(
            organization=self.existing_org, name='Survivor Server',
            asset_type='server',
        )
        self.asset_created = Asset.objects.create(
            organization=self.created_org, name='New Server', asset_type='server',
        )
        ImportMapping.objects.create(
            import_job=self.job, source_type='asset',
            source_id='itglue-asset-1', target_model='Asset',
            target_id=self.asset_existing.id,
            target_organization=self.existing_org,
        )
        ImportMapping.objects.create(
            import_job=self.job, source_type='asset',
            source_id='itglue-asset-2', target_model='Asset',
            target_id=self.asset_created.id,
            target_organization=self.created_org,
        )
        # Org-mapping rollback rows so the rollback's was_created handling fires.
        ImportMapping.objects.create(
            import_job=self.job, source_type='organization',
            source_id='itglue-100', target_model='Organization',
            target_id=self.existing_org.id,
        )
        ImportMapping.objects.create(
            import_job=self.job, source_type='organization',
            source_id='itglue-101', target_model='Organization',
            target_id=self.created_org.id,
        )

    def test_rollback_deletes_imported_assets_and_created_orgs_only(self):
        stats = self.job.rollback(self.user)

        # Both assets gone.
        self.assertFalse(Asset.objects.filter(pk=self.asset_existing.pk).exists())
        self.assertFalse(Asset.objects.filter(pk=self.asset_created.pk).exists())
        # Pre-existing org survived.
        self.assertTrue(Organization.objects.filter(pk=self.existing_org.pk).exists())
        # Org created by the import is gone.
        self.assertFalse(Organization.objects.filter(pk=self.created_org.pk).exists())

        # Stats reflect the split. Django's QuerySet.delete() returns the
        # total of (target rows + cascading rows), so we don't assert exact
        # numbers — just that each bucket is populated and the matched-org
        # row count matches what we set up (1 mapping for the existing org).
        self.assertEqual(stats['by_type'].get('Asset'), 2)
        self.assertGreaterEqual(stats['by_type'].get('Organization (created)', 0), 1)
        self.assertEqual(stats['by_type'].get('Organization (skipped)'), 1)

    def test_rollback_marks_job_rolled_back(self):
        self.job.rollback(self.user)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'rolled_back')
        self.assertEqual(self.job.rolled_back_by, self.user)
        self.assertIsNotNone(self.job.rolled_back_at)

    def test_rollback_raises_when_not_eligible(self):
        bad = ImportJob.objects.create(source_type='itglue', dry_run=False, status='pending')
        with self.assertRaises(ValueError):
            bad.rollback(self.user)


# ---------------------------------------------------------------------------
# Mapping models — unique-together constraints are the dedupe contract
# ---------------------------------------------------------------------------

class OrganizationMappingConstraintTests(TestCase):
    def setUp(self):
        self.job = ImportJob.objects.create(source_type='itglue', dry_run=True)
        self.org = Organization.objects.create(name='X', slug='x')

    def test_unique_per_job_and_source_id(self):
        OrganizationMapping.objects.create(
            import_job=self.job, source_id='abc', source_name='X',
            organization=self.org,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrganizationMapping.objects.create(
                import_job=self.job, source_id='abc', source_name='X-dup',
                organization=self.org,
            )

    def test_same_source_id_in_different_job_is_allowed(self):
        OrganizationMapping.objects.create(
            import_job=self.job, source_id='abc', source_name='X',
            organization=self.org,
        )
        other_job = ImportJob.objects.create(source_type='itglue', dry_run=True)
        OrganizationMapping.objects.create(
            import_job=other_job, source_id='abc', source_name='X',
            organization=self.org,
        )  # must not raise


class ImportMappingConstraintTests(TestCase):
    def setUp(self):
        self.job = ImportJob.objects.create(source_type='itglue', dry_run=True)
        self.org = Organization.objects.create(name='Y', slug='y')

    def test_unique_per_job_and_source_type_and_source_id(self):
        ImportMapping.objects.create(
            import_job=self.job, source_type='asset', source_id='999',
            target_model='Asset', target_id=1,
            target_organization=self.org,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ImportMapping.objects.create(
                import_job=self.job, source_type='asset', source_id='999',
                target_model='Asset', target_id=2,
                target_organization=self.org,
            )

    def test_same_source_id_for_different_type_is_allowed(self):
        ImportMapping.objects.create(
            import_job=self.job, source_type='asset', source_id='999',
            target_model='Asset', target_id=1,
            target_organization=self.org,
        )
        ImportMapping.objects.create(
            import_job=self.job, source_type='password', source_id='999',
            target_model='Password', target_id=1,
            target_organization=self.org,
        )  # must not raise


# ---------------------------------------------------------------------------
# CSV preview helper
# ---------------------------------------------------------------------------

class CSVImportPreviewTests(TestCase):
    def test_reads_headers_and_first_rows(self):
        csv_bytes = b'name,email,role\nAlice,a@x.com,admin\nBob,b@x.com,user\n'
        headers, rows = read_csv_preview(io.BytesIO(csv_bytes), max_rows=5)
        self.assertEqual(headers, ['name', 'email', 'role'])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['name'], 'Alice')
        self.assertEqual(rows[1]['email'], 'b@x.com')

    def test_max_rows_caps_preview(self):
        body = b'name\n' + b'\n'.join(f'row{i}'.encode() for i in range(50)) + b'\n'
        _headers, rows = read_csv_preview(io.BytesIO(body), max_rows=3)
        self.assertEqual(len(rows), 3)

    def test_handles_utf8_bom(self):
        # Excel exports often start with a UTF-8 BOM. The reader decodes
        # with utf-8-sig so the first header isn't corrupted.
        csv_bytes = '﻿name,email\nAlice,a@x.com\n'.encode('utf-8')
        headers, _rows = read_csv_preview(io.BytesIO(csv_bytes), max_rows=5)
        self.assertEqual(headers[0], 'name')

    def test_rewinds_file_object(self):
        # The preview seeks to 0 internally so a subsequent caller can re-read.
        buf = io.BytesIO(b'name\nAlice\n')
        buf.read()  # caller already consumed the buffer
        headers, _rows = read_csv_preview(buf, max_rows=1)
        self.assertEqual(headers, ['name'])


# ---------------------------------------------------------------------------
# Who may open the legacy import screens
# ---------------------------------------------------------------------------

from django.conf import settings as _django_settings  # noqa: E402
from django.test import override_settings  # noqa: E402

_TEST_MIDDLEWARE = [m for m in _django_settings.MIDDLEWARE
                    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m]


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ImportScreensAreSuperuserOnlyTests(TestCase):
    """The rule is superuser-only. The old check also looked at
    `user.is_staff_user`, which no User has, so it never let anyone else in;
    these tests pin that, so widening it is a visible decision."""

    def test_check_is_superuser_only(self):
        from types import SimpleNamespace
        from imports.views import is_import_admin
        su = User.objects.create_superuser('imp_su', 's@x.test', 'pw')
        plain = User.objects.create_user('imp_plain', 'p@x.test', 'pw')
        self.assertTrue(is_import_admin(su))
        self.assertFalse(is_import_admin(plain))
        # Even an object that does carry is_staff_user is not let in.
        self.assertFalse(is_import_admin(SimpleNamespace(is_authenticated=True, is_superuser=False,
                                                         is_staff_user=True)))

    def test_msp_staff_and_django_staff_are_redirected_superuser_gets_page(self):
        from django.urls import reverse
        from accounts.models import UserProfile, UserType
        tech = User.objects.create_user('imp_tech', 't@x.test', 'pw', is_staff=True)
        profile, _ = UserProfile.objects.get_or_create(user=tech)
        profile.user_type = UserType.STAFF
        profile.save()
        su = User.objects.create_superuser('imp_su2', 's2@x.test', 'pw')
        url = reverse('imports:import_list')
        self.client.force_login(tech)
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(su)
        self.assertEqual(self.client.get(url).status_code, 200)
