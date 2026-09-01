"""
Baseline test coverage for the docs/ app.

Knowledge base + Diagrams. KB articles surface to clients via the
portal — bug here can leak internal docs externally OR break the
slug routing on customer-visible URLs. Every other app links here
(PSA→KB-link, processes→linked_document, vault→linked_document).

Coverage areas:
  * `Document.save()` slug auto-generation; version snapshots on
    update.
  * `DocumentCategory` slug auto-generation.
  * `Diagram.save()` slug auto-generation.
  * Tenant-isolation contract via `organization` FK.
  * `is_global` for cross-tenant KB articles.
"""
from __future__ import annotations

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.models import Organization
from docs.models import (
    Diagram,
    Document,
    DocumentCategory,
    DocumentVersion,
)


class DocumentCategoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='DocCo', slug='doc-co')

    def test_slug_auto_generated_from_name(self):
        cat = DocumentCategory.objects.create(
            organization=self.org, name='Network Documentation',
        )
        self.assertEqual(cat.slug, 'network-documentation')

    def test_explicit_slug_preserved(self):
        cat = DocumentCategory.objects.create(
            organization=self.org, name='X', slug='custom-slug',
        )
        self.assertEqual(cat.slug, 'custom-slug')

    def test_str_includes_name(self):
        cat = DocumentCategory.objects.create(
            organization=self.org, name='Onboarding',
        )
        self.assertIn('Onboarding', str(cat))


class DocumentSlugTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='SlugCo', slug='slug-co')
        cls.user = User.objects.create_user('doc-user', email='d@x.com', password='pw')

    def test_slug_auto_generated_from_title_on_create(self):
        d = Document.objects.create(
            organization=self.org, title='How to Reboot the Server',
            body='step 1: ...', created_by=self.user,
        )
        self.assertEqual(d.slug, 'how-to-reboot-the-server')

    def test_explicit_slug_preserved(self):
        d = Document.objects.create(
            organization=self.org, title='X', slug='custom-doc-slug',
            body='b', created_by=self.user,
        )
        self.assertEqual(d.slug, 'custom-doc-slug')

    def test_str_returns_title(self):
        d = Document.objects.create(
            organization=self.org, title='My Doc',
            body='', created_by=self.user,
        )
        # Document.__str__ returns title (line 111-112 in models.py).
        self.assertIn('My Doc', str(d))


class DocumentVersionSnapshotTests(TestCase):
    """`Document._create_version` snapshots the previous body/title BEFORE
    a save when the document already exists. Bug here = no audit trail
    of edits, customers can't roll back."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='VerCo', slug='ver-co')
        cls.user = User.objects.create_user('ver-user', email='v@x.com', password='pw')

    def test_no_versions_on_initial_create(self):
        d = Document.objects.create(
            organization=self.org, title='Doc', body='v1',
            created_by=self.user,
        )
        self.assertEqual(d.versions.count(), 0)

    def test_version_recorded_on_first_edit(self):
        d = Document.objects.create(
            organization=self.org, title='Doc', body='v1',
            created_by=self.user, last_modified_by=self.user,
        )
        d.title = 'Doc-renamed'
        d.body = 'v2'
        d.save()
        # The pre-save snapshot recorded the v1 state.
        self.assertEqual(d.versions.count(), 1)
        version = d.versions.first()
        self.assertEqual(version.title, 'Doc')
        self.assertEqual(version.body, 'v1')
        self.assertEqual(version.version_number, 1)

    def test_version_numbers_increment_on_each_edit(self):
        d = Document.objects.create(
            organization=self.org, title='Doc', body='v1',
            created_by=self.user, last_modified_by=self.user,
        )
        for i in range(2, 5):
            d.body = f'v{i}'
            d.save()
        # We made 3 edits → 3 version snapshots, numbered 1..3.
        nums = sorted(d.versions.values_list('version_number', flat=True))
        self.assertEqual(nums, [1, 2, 3])


class DiagramSlugTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='DiagCo', slug='diag-co')
        cls.user = User.objects.create_user('diag-user', email='dg@x.com', password='pw')

    def test_slug_auto_generated_from_title(self):
        d = Diagram.objects.create(
            organization=self.org, title='Network Topology',
            created_by=self.user,
        )
        self.assertEqual(d.slug, 'network-topology')

    def test_str_returns_title(self):
        d = Diagram.objects.create(
            organization=self.org, title='Rack Layout',
            created_by=self.user,
        )
        self.assertIn('Rack Layout', str(d))


class GlobalKBVisibilityTests(TestCase):
    """Documents with `is_global=True` are visible across tenants. This
    is the cross-tenant KB story; querysets in views need to OR
    (organization=current OR is_global=True)."""

    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organization.objects.create(name='KBA', slug='kba')
        cls.org_b = Organization.objects.create(name='KBB', slug='kbb')
        cls.user = User.objects.create_user('kb-user', email='kb@x.com', password='pw')

    def test_global_doc_can_have_no_organization(self):
        # is_global docs may be org-scoped (MSP-internal) OR fully global
        # (organization=None). The model permits both — confirm a
        # null-org global doc round-trips.
        d = Document.objects.create(
            organization=None, title='Global FAQ', body='b',
            is_global=True, created_by=self.user,
        )
        self.assertIsNone(d.organization)
        self.assertTrue(d.is_global)

    def test_org_scoped_doc_with_global_flag(self):
        # An MSP-internal doc with is_global=True is visible to staff
        # across tenants but tied to the MSP org for ownership/audit.
        d = Document.objects.create(
            organization=self.org_a, title='MSP runbook', body='b',
            is_global=True, created_by=self.user,
        )
        self.assertEqual(d.organization, self.org_a)
        self.assertTrue(d.is_global)


# ---------------------------------------------------------------------------
# Phase 22 v1 — KB review reminders + mark-reviewed (v3.17.245)
# ---------------------------------------------------------------------------

from datetime import timedelta as _td

from django.conf import settings as django_settings
from django.test import Client, override_settings


_TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class KBReviewQueueTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from core.models import Organization
        cls.org = Organization.objects.create(name='KBReviewCo', slug='kb-rev-co')
        cls.owner = User.objects.create_user('kb-owner', 'kbo@x.com', 'pw')
        cls.staff = User.objects.create_user('kb-staff', 'kbs@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        # An article owned by `owner`, last reviewed 200 days ago — overdue.
        cls.overdue = Document.objects.create(
            organization=cls.org, title='Overdue article', body='...',
            is_published=True, owner=cls.owner,
            review_interval_days=90,
            last_reviewed_at=timezone.now() - _td(days=200),
        )
        # An article last reviewed 5 days ago — due in (90-5) = 85d. Current.
        cls.current = Document.objects.create(
            organization=cls.org, title='Current article', body='...',
            is_published=True, owner=cls.owner,
            review_interval_days=90,
            last_reviewed_at=timezone.now() - _td(days=5),
        )
        # 86 days ago → due_soon (within 7 days of due).
        cls.due_soon = Document.objects.create(
            organization=cls.org, title='Due soon article', body='...',
            is_published=True, owner=cls.owner,
            review_interval_days=90,
            last_reviewed_at=timezone.now() - _td(days=86),
        )
        # review_interval_days=0 → never review.
        cls.no_review = Document.objects.create(
            organization=cls.org, title='No review article', body='...',
            is_published=True, owner=cls.owner,
            review_interval_days=0,
        )

    def _login(self, c, user):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        s.save()

    def test_review_status_classifies_correctly(self):
        self.assertEqual(self.overdue.review_status, 'overdue')
        self.assertEqual(self.current.review_status, 'current')
        self.assertEqual(self.due_soon.review_status, 'due_soon')
        self.assertEqual(self.no_review.review_status, 'no_review')

    def test_is_review_overdue_property(self):
        self.assertTrue(self.overdue.is_review_overdue)
        self.assertFalse(self.current.is_review_overdue)
        self.assertFalse(self.due_soon.is_review_overdue)
        self.assertFalse(self.no_review.is_review_overdue)

    def test_mark_reviewed_resets_clock(self):
        before = self.overdue.last_reviewed_at
        self.overdue.mark_reviewed(user=self.staff)
        self.overdue.refresh_from_db()
        self.assertGreater(self.overdue.last_reviewed_at, before)
        self.assertFalse(self.overdue.is_review_overdue)

    def test_review_queue_for_owner_lists_overdue_and_due_soon(self):
        c = Client()
        self._login(c, self.owner)
        r = c.get('/docs/review-queue/')
        self.assertEqual(r.status_code, 200)
        ctx = r.context
        overdue_titles = [d.title for d in ctx['overdue']]
        due_soon_titles = [d.title for d in ctx['due_soon']]
        self.assertIn('Overdue article', overdue_titles)
        self.assertIn('Due soon article', due_soon_titles)
        self.assertNotIn('Current article', overdue_titles + due_soon_titles)
        self.assertNotIn('No review article', overdue_titles + due_soon_titles)

    def test_mark_reviewed_view_works_for_owner(self):
        c = Client()
        self._login(c, self.owner)
        before = self.overdue.last_reviewed_at
        c.post(f'/docs/{self.overdue.slug}/mark-reviewed/')
        self.overdue.refresh_from_db()
        self.assertGreater(self.overdue.last_reviewed_at, before)

    def test_mark_reviewed_view_blocked_for_non_owner_non_staff(self):
        peer = User.objects.create_user('peer', 'p@x.com', 'pw')
        c = Client()
        self._login(c, peer)
        before = self.overdue.last_reviewed_at
        c.post(f'/docs/{self.overdue.slug}/mark-reviewed/')
        self.overdue.refresh_from_db()
        self.assertEqual(self.overdue.last_reviewed_at, before)


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class KBApprovalQueueTests(TestCase):
    """Phase 22 v2 (v3.17.250) — editorial approval queue."""

    @classmethod
    def setUpTestData(cls):
        from core.models import Organization
        cls.org = Organization.objects.create(name='ApprovalCo', slug='kb-app-co')
        cls.staff = User.objects.create_user('kb-app-staff', 'kas@x.com', 'pw',
                                              is_staff=True, is_superuser=True)
        cls.owner = User.objects.create_user('kb-app-owner', 'kao@x.com', 'pw')
        cls.draft = Document.objects.create(
            organization=cls.org, title='Draft article', body='New content',
            is_published=False, is_draft=True, owner=cls.owner,
        )
        cls.published = Document.objects.create(
            organization=cls.org, title='Live article', body='Live',
            is_published=True, is_draft=False, owner=cls.owner,
        )

    def _login(self, c, user):
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        s.save()

    def test_queue_lists_drafts_only(self):
        c = Client()
        self._login(c, self.staff)
        r = c.get('/docs/approval-queue/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Draft article')
        self.assertNotContains(r, 'Live article')

    def test_approve_flips_to_published(self):
        c = Client()
        self._login(c, self.staff)
        r = c.post(f'/docs/{self.draft.slug}/approve/')
        self.assertEqual(r.status_code, 302)
        self.draft.refresh_from_db()
        self.assertFalse(self.draft.is_draft)
        self.assertTrue(self.draft.is_published)

    def test_reject_keeps_draft_and_appends_note(self):
        c = Client()
        self._login(c, self.staff)
        c.post(f'/docs/{self.draft.slug}/reject/', data={
            'note': 'Tone is too informal',
        })
        self.draft.refresh_from_db()
        self.assertTrue(self.draft.is_draft)
        self.assertFalse(self.draft.is_published)
        self.assertIn('Tone is too informal', self.draft.body)
        self.assertIn('[Rejected by', self.draft.body)

    def test_submit_for_review_sets_draft(self):
        c = Client()
        self._login(c, self.owner)
        c.post(f'/docs/{self.published.slug}/submit-for-review/')
        self.published.refresh_from_db()
        self.assertTrue(self.published.is_draft)
        self.assertFalse(self.published.is_published)

    def test_submit_for_review_blocked_for_non_owner(self):
        peer = User.objects.create_user('kb-peer', 'p@x.com', 'pw')
        c = Client()
        self._login(c, peer)
        c.post(f'/docs/{self.published.slug}/submit-for-review/')
        self.published.refresh_from_db()
        self.assertFalse(self.published.is_draft)

    def test_approve_blocked_for_non_staff(self):
        c = Client()
        self._login(c, self.owner)
        c.post(f'/docs/{self.draft.slug}/approve/')
        self.draft.refresh_from_db()
        self.assertTrue(self.draft.is_draft)


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False,
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class KBReviewReminderCommandTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from core.models import Organization
        cls.org = Organization.objects.create(name='ReminderCo', slug='kb-rem-co')
        cls.owner = User.objects.create_user('rem-owner', 'remo@x.com', 'pw')
        Document.objects.create(
            organization=cls.org, title='Stale 1', body='...',
            is_published=True, owner=cls.owner,
            review_interval_days=30,
            last_reviewed_at=timezone.now() - _td(days=120),
        )
        Document.objects.create(
            organization=cls.org, title='Stale 2', body='...',
            is_published=True, owner=cls.owner,
            review_interval_days=30,
            last_reviewed_at=timezone.now() - _td(days=90),
        )
        # Current — should NOT trigger
        Document.objects.create(
            organization=cls.org, title='Fresh', body='...',
            is_published=True, owner=cls.owner,
            review_interval_days=30,
            last_reviewed_at=timezone.now() - _td(days=5),
        )

    def test_command_sends_one_digest_per_owner(self):
        from django.core import mail
        from django.core.management import call_command
        mail.outbox = []
        call_command('kb_review_reminders', verbosity=0)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ['remo@x.com'])
        self.assertIn('2 article', msg.subject)
        self.assertIn('Stale 1', msg.body)
        self.assertIn('Stale 2', msg.body)
        self.assertNotIn('Fresh', msg.body)

    def test_dry_run_does_not_send(self):
        from django.core import mail
        from django.core.management import call_command
        mail.outbox = []
        call_command('kb_review_reminders', '--dry-run', verbosity=0)
        self.assertEqual(len(mail.outbox), 0)


# ---------------------------------------------------------------------------
# Issue #138 — AI document generation returned an HTML 500 ("Server returned
# HTML instead of JSON") whenever the LLM call outran the gunicorn worker
# --timeout, because provider HTTP timeouts were ABOVE the worker timeout so
# the worker was SIGKILLed before the provider could time out cleanly. These
# tests lock the invariant that provider timeouts stay below the worker budget
# and that a slow model surfaces as a caught JSON error, never an exception.
# ---------------------------------------------------------------------------
from unittest import mock

import requests as _requests

from docs.services.llm_providers import AI_HTTP_TIMEOUT, OllamaProvider


class AIProviderTimeoutTests(TestCase):
    # The gunicorn worker --timeout configured in Dockerfile / the systemd
    # unit. Provider HTTP timeouts must stay strictly under this.
    GUNICORN_WORKER_TIMEOUT = 300

    def test_provider_timeout_is_below_worker_timeout(self):
        self.assertLess(
            AI_HTTP_TIMEOUT, self.GUNICORN_WORKER_TIMEOUT,
            'Provider HTTP timeout must stay below the gunicorn worker '
            '--timeout, or a slow model kills the worker and the browser '
            'gets an HTML 500 instead of a JSON error (issue #138).',
        )

    def test_ollama_passes_bounded_timeout(self):
        provider = OllamaProvider(base_url='http://ollama:11434', model='llama3.2')
        fake = mock.Mock(status_code=200)
        fake.json.return_value = {'message': {'content': 'hello'}}
        fake.raise_for_status.return_value = None
        with mock.patch('docs.services.llm_providers.requests.post', return_value=fake) as post:
            result = provider.generate('sys', 'user', max_tokens=256)
        self.assertTrue(result['success'])
        self.assertEqual(post.call_args.kwargs['timeout'], AI_HTTP_TIMEOUT)

    def test_ollama_timeout_returns_json_error_not_exception(self):
        """A slow model must yield a clean {'success': False, ...} dict — the
        view turns that into a JSON response — rather than raising and letting
        an HTML 500 escape to the browser."""
        provider = OllamaProvider(base_url='http://ollama:11434', model='llama3.2')
        with mock.patch(
            'docs.services.llm_providers.requests.post',
            side_effect=_requests.exceptions.Timeout('timed out'),
        ):
            result = provider.generate('sys', 'user')
        self.assertFalse(result['success'])
        self.assertIn('did not respond', result['error'].lower())


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DocumentFileUploadTests(TestCase):
    """Issue #139 — uploading a file document raised AttributeError:
    'FieldFile' object has no attribute 'content_type'. The MIME type must be
    read from the in-request UploadedFile (request.FILES), never off the model's
    FieldFile."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='UploadCo', slug='upload-co')
        cls.staff = User.objects.create_user(
            'upload-staff', 'us@x.com', 'pw', is_staff=True, is_superuser=True)

    def _login(self, c):
        c.force_login(self.staff)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()

    def test_create_file_document_records_mime_type(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        c = Client()
        self._login(c)
        upload = SimpleUploadedFile(
            'report.pdf', b'%PDF-1.4 fake', content_type='application/pdf')
        r = c.post('/docs/create/', {
            'title': 'Report',
            'body': '',
            'content_type': 'file',
            'is_published': 'on',
            'file': upload,
        })
        # Must not 500 with AttributeError; a valid create redirects (302).
        self.assertEqual(r.status_code, 302)
        doc = Document.objects.get(title='Report')
        self.assertEqual(doc.content_type, 'file')
        self.assertEqual(doc.file_type, 'application/pdf')
        self.assertEqual(doc.file_size, len(b'%PDF-1.4 fake'))

    def test_edit_replacing_file_records_mime_type(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        c = Client()
        self._login(c)
        doc = Document.objects.create(
            organization=self.org, title='Existing', content_type='file',
            file=SimpleUploadedFile('a.txt', b'hi', content_type='text/plain'),
            created_by=self.staff, last_modified_by=self.staff)
        new_upload = SimpleUploadedFile(
            'b.png', b'\x89PNG fake', content_type='image/png')
        r = c.post(f'/docs/{doc.slug}/edit/', {
            'title': 'Existing',
            'body': '',
            'content_type': 'file',
            'is_published': 'on',
            'file': new_upload,
        })
        self.assertEqual(r.status_code, 302)
        doc.refresh_from_db()
        self.assertEqual(doc.file_type, 'image/png')


# ---------------------------------------------------------------------------
# Issue #140 — DOCX/PDF import + AI review
# ---------------------------------------------------------------------------

import io
import zipfile as _zipfile
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile


def _make_docx_bytes(paragraphs):
    """Build a minimal but valid .docx (a ZIP whose word/document.xml holds
    the body) for extraction tests — avoids a python-docx test dependency."""
    ns = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    body = ''.join(
        f'<w:p><w:r><w:t>{p}</w:t></w:r></w:p>' for p in paragraphs
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>'
    )
    buf = io.BytesIO()
    with _zipfile.ZipFile(buf, 'w', _zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('word/document.xml', document_xml)
    return buf.getvalue()


def _make_pdf_bytes(text):
    """Build a one-page PDF with the given text using PyMuPDF."""
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


class DocumentExtractionTests(TestCase):
    """Text extraction from uploaded DOCX / PDF / TXT files (issue #140)."""

    def test_extract_docx_paragraphs(self):
        from docs.services.document_import import extract_document_text
        f = SimpleUploadedFile(
            'guide.docx', _make_docx_bytes(['First line', 'Second line']))
        res = extract_document_text(f)
        self.assertTrue(res['success'], res.get('error'))
        self.assertEqual(res['kind'], 'docx')
        self.assertIn('First line', res['text'])
        self.assertIn('Second line', res['text'])

    def test_extract_pdf_text(self):
        from docs.services.document_import import extract_document_text
        f = SimpleUploadedFile(
            'runbook.pdf', _make_pdf_bytes('Reboot the router'),
            content_type='application/pdf')
        res = extract_document_text(f)
        self.assertTrue(res['success'], res.get('error'))
        self.assertEqual(res['kind'], 'pdf')
        self.assertIn('Reboot the router', res['text'])

    def test_extract_txt(self):
        from docs.services.document_import import extract_document_text
        f = SimpleUploadedFile('notes.txt', b'plain text notes')
        res = extract_document_text(f)
        self.assertTrue(res['success'])
        self.assertEqual(res['kind'], 'text')
        self.assertEqual(res['text'], 'plain text notes')

    def test_unsupported_extension_rejected(self):
        from docs.services.document_import import extract_document_text
        f = SimpleUploadedFile('image.xyz', b'\x00\x01')
        res = extract_document_text(f)
        self.assertFalse(res['success'])

    def test_legacy_doc_rejected_with_hint(self):
        from docs.services.document_import import extract_document_text
        f = SimpleUploadedFile('old.doc', b'\xd0\xcf\x11\xe0')
        res = extract_document_text(f)
        self.assertFalse(res['success'])
        self.assertIn('.docx', res['error'])

    def test_corrupt_docx_rejected(self):
        from docs.services.document_import import extract_document_text
        f = SimpleUploadedFile('broken.docx', b'not a zip file at all')
        res = extract_document_text(f)
        self.assertFalse(res['success'])

    def test_truncation_flagged(self):
        from docs.services import document_import
        big = ('x' * (document_import.MAX_EXTRACTED_CHARS + 500)).encode()
        f = SimpleUploadedFile('big.txt', big)
        res = document_import.extract_document_text(f)
        self.assertTrue(res['success'])
        self.assertTrue(res['truncated'])
        self.assertEqual(len(res['text']), document_import.MAX_EXTRACTED_CHARS)


class ReviewImportedParseTests(TestCase):
    """review_imported_document splits reformatted body from gap analysis."""

    def _generator(self):
        with override_settings(LLM_PROVIDER='ollama'):
            from docs.services.ai_documentation_generator import AIDocumentationGenerator
            return AIDocumentationGenerator()

    def _stub(self, gen, content):
        gen.provider = mock.Mock()
        gen.provider.generate.return_value = {'success': True, 'content': content}

    def test_parses_body_and_gaps(self):
        gen = self._generator()
        self._stub(gen, '<h2>Doc</h2><p>Body</p>\n<!--GAP-ANALYSIS-->\n- Missing DR section\n- No contacts')
        res = gen.review_imported_document('T', 'raw text')
        self.assertTrue(res['success'])
        self.assertIn('<h2>Doc</h2>', res['content'])
        self.assertNotIn('GAP-ANALYSIS', res['content'])
        self.assertEqual(res['gaps'], ['Missing DR section', 'No contacts'])

    def test_no_marker_returns_all_as_body(self):
        gen = self._generator()
        self._stub(gen, '<p>Just a body, no gaps section</p>')
        res = gen.review_imported_document('T', 'raw')
        self.assertTrue(res['success'])
        self.assertIn('Just a body', res['content'])
        self.assertEqual(res['gaps'], [])

    def test_strips_code_fences(self):
        gen = self._generator()
        self._stub(gen, '```html\n<p>Fenced</p>\n```\n<!--GAP-ANALYSIS-->\n- one')
        res = gen.review_imported_document('T', 'raw')
        self.assertEqual(res['content'], '<p>Fenced</p>')
        self.assertEqual(res['gaps'], ['one'])

    def test_provider_failure_propagates(self):
        gen = self._generator()
        gen.provider = mock.Mock()
        gen.provider.generate.return_value = {'success': False, 'error': 'boom'}
        res = gen.review_imported_document('T', 'raw')
        self.assertFalse(res['success'])


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DocumentImportViewTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from core.models import Organization
        cls.org = Organization.objects.create(name='ImportCo', slug='import-co')
        cls.staff = User.objects.create_user(
            'import-staff', 'imp@x.com', 'pw', is_staff=True, is_superuser=True)

    def _login(self, c):
        c.force_login(self.staff)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()

    def test_import_page_loads(self):
        c = Client()
        self._login(c)
        r = c.get('/docs/import/')
        self.assertEqual(r.status_code, 200)

    def test_bulk_import_creates_editable_documents(self):
        c = Client()
        self._login(c)
        docx = SimpleUploadedFile('policy.docx', _make_docx_bytes(['Password policy']))
        txt = SimpleUploadedFile('notes.txt', b'onboarding steps')
        r = c.post('/docs/import/', {'files': [docx, txt]})
        self.assertEqual(r.status_code, 200)
        policy = Document.objects.get(organization=self.org, title='policy')
        self.assertEqual(policy.content_type, 'markdown')
        self.assertIn('Password policy', policy.body)
        notes = Document.objects.get(organization=self.org, title='notes')
        self.assertIn('onboarding steps', notes.body)

    def test_import_no_files_redirects(self):
        c = Client()
        self._login(c)
        r = c.post('/docs/import/', {})
        self.assertEqual(r.status_code, 302)

    def test_ai_review_blocked_when_ai_disabled(self):
        from core.models import SystemSetting
        ss = SystemSetting.get_settings()
        ss.psa_ai_enabled = False
        ss.save()
        c = Client()
        self._login(c)
        doc = Document.objects.create(
            organization=self.org, title='Imported', body='raw',
            content_type='markdown', created_by=self.staff, last_modified_by=self.staff)
        r = c.post('/docs/ai/review-import/',
                   data={'document_id': doc.id, 'standard': 'general'},
                   content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_ai_review_reformats_and_saves(self):
        from core.models import SystemSetting
        ss = SystemSetting.get_settings()
        ss.psa_ai_enabled = True
        ss.save()
        c = Client()
        self._login(c)
        doc = Document.objects.create(
            organization=self.org, title='Imported', body='raw text',
            content_type='markdown', created_by=self.staff, last_modified_by=self.staff)
        fake = {'success': True, 'title': 'Imported',
                'content': '<h2>Imported</h2>', 'gaps': ['Add owner']}
        with override_settings(LLM_PROVIDER='ollama'), \
                mock.patch('docs.services.ai_documentation_generator.'
                           'AIDocumentationGenerator.review_imported_document',
                           return_value=fake):
            r = c.post('/docs/ai/review-import/',
                       data={'document_id': doc.id, 'standard': 'security'},
                       content_type='application/json')
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['gaps'], ['Add owner'])
        doc.refresh_from_db()
        self.assertEqual(doc.content_type, 'html')
        self.assertIn('<h2>Imported</h2>', doc.body)

    def test_ai_review_markdown_output_stored_as_markdown(self):
        """Issue #140: models often return Markdown despite the HTML prompt.
        Storing that as content_type='html' makes the reader see literal '##'
        markup ('goes to MD format instead of html'). The view must detect the
        real format and store 'markdown' so render_content converts it."""
        from core.models import SystemSetting
        ss = SystemSetting.get_settings()
        ss.psa_ai_enabled = True
        ss.save()
        c = Client()
        self._login(c)
        doc = Document.objects.create(
            organization=self.org, title='SOP', body='raw text',
            content_type='markdown', created_by=self.staff, last_modified_by=self.staff)
        fake = {'success': True, 'title': 'SOP',
                'content': '## Purpose\n\n**Scope**: all servers\n\n- step one',
                'gaps': []}
        with override_settings(LLM_PROVIDER='ollama'), \
                mock.patch('docs.services.ai_documentation_generator.'
                           'AIDocumentationGenerator.review_imported_document',
                           return_value=fake):
            r = c.post('/docs/ai/review-import/',
                       data={'document_id': doc.id, 'standard': 'process'},
                       content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['content_type'], 'markdown')
        doc.refresh_from_db()
        self.assertEqual(doc.content_type, 'markdown')


class LooksLikeHtmlTests(TestCase):
    """_looks_like_html distinguishes AI-returned HTML from Markdown (issue #140)."""

    def _fn(self):
        from docs.views import _looks_like_html
        return _looks_like_html

    def test_html_block_tags_detected(self):
        f = self._fn()
        self.assertTrue(f('<h2>Title</h2><p>Body</p>'))
        self.assertTrue(f('\n\n  <div class="alert">note</div>'))
        self.assertTrue(f('<table class="table"><tr><td>x</td></tr></table>'))

    def test_markdown_not_detected_as_html(self):
        f = self._fn()
        self.assertFalse(f('## Heading\n\n**bold** and a `<code>` snippet'))
        self.assertFalse(f('- item one\n- item two'))
        self.assertFalse(f(''))
        self.assertFalse(f(None))


# ---------------------------------------------------------------------------
# Issue #144 — document export (Markdown / print-ready HTML / DOCX / PDF)
# ---------------------------------------------------------------------------

_SAMPLE_HTML = (
    '<h2>Network Overview</h2>'
    '<p>The <strong>core switch</strong> lives in <em>Rack 3</em> and is '
    '<a href="https://example.com/switch">documented here</a>.</p>'
    '<ul><li>VLAN 10 — users</li><li>VLAN 20 — servers</li></ul>'
    '<ol><li>First</li><li>Second</li></ol>'
    '<blockquote>Escalate to the NOC before a reboot.</blockquote>'
    '<pre><code>show running-config\nwrite mem</code></pre>'
    '<table><thead><tr><th>Host</th><th>IP</th></tr></thead>'
    '<tbody><tr><td>sw-core</td><td>10.0.0.1</td></tr></tbody></table>'
    '<hr>'
)


class DocumentExportParserTests(TestCase):
    """`parse_blocks` is the spine every writer sits on — cover it directly."""

    def setUp(self):
        from docs.services.document_export import parse_blocks
        self.blocks = parse_blocks(_SAMPLE_HTML)
        self.kinds = [b['type'] for b in self.blocks]

    def test_block_kinds_in_document_order(self):
        self.assertEqual(self.kinds, [
            'heading', 'paragraph',
            'list_item', 'list_item', 'list_item', 'list_item',
            'quote', 'code', 'table', 'rule',
        ])

    def test_heading_level_preserved(self):
        self.assertEqual(self.blocks[0]['level'], 2)
        self.assertEqual(
            ''.join(r['text'] for r in self.blocks[0]['runs']), 'Network Overview')

    def test_inline_formatting_and_links_survive(self):
        runs = self.blocks[1]['runs']
        self.assertTrue(any(r['bold'] and 'core switch' in r['text'] for r in runs))
        self.assertTrue(any(r['italic'] and 'Rack 3' in r['text'] for r in runs))
        self.assertTrue(any(r['href'] == 'https://example.com/switch' for r in runs))

    def test_ordered_flag_distinguishes_ul_from_ol(self):
        items = [b for b in self.blocks if b['type'] == 'list_item']
        self.assertEqual([b['ordered'] for b in items], [False, False, True, True])

    def test_code_block_keeps_newlines(self):
        code = next(b for b in self.blocks if b['type'] == 'code')
        self.assertEqual(code['text'], 'show running-config\nwrite mem')

    def test_table_rows_and_header_flag(self):
        table = next(b for b in self.blocks if b['type'] == 'table')
        self.assertTrue(table['has_header'])
        self.assertEqual(table['rows'], [['Host', 'IP'], ['sw-core', '10.0.0.1']])

    def test_script_content_is_dropped(self):
        from docs.services.document_export import parse_blocks
        blocks = parse_blocks('<p>keep</p><script>alert("x")</script>')
        self.assertNotIn('alert', str(blocks))

    def test_empty_html_yields_no_blocks(self):
        from docs.services.document_export import parse_blocks
        self.assertEqual(parse_blocks(''), [])
        self.assertEqual(parse_blocks(None), [])


class DocumentExportWriterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='ExportCo', slug='export-co')
        cls.cat = DocumentCategory.objects.create(organization=cls.org, name='Network')
        cls.doc = Document.objects.create(
            organization=cls.org, title='Network Overview', body=_SAMPLE_HTML,
            content_type='html', category=cls.cat, is_published=True,
        )
        cls.md_doc = Document.objects.create(
            organization=cls.org, title='Runbook',
            body='# Runbook\n\n- step one\n- step two\n',
            content_type='markdown', is_published=True,
        )

    # -- Markdown ---------------------------------------------------------
    def test_markdown_export_structure(self):
        from docs.services.document_export import export_markdown
        text = export_markdown(self.doc).decode('utf-8')
        self.assertIn('# Network Overview', text)
        self.assertIn('**Organization:** ExportCo', text)
        self.assertIn('**Category:** Network', text)
        self.assertIn('## Network Overview', text)
        self.assertIn('- VLAN 10', text)
        self.assertIn('1. First', text)
        self.assertIn('> Escalate to the NOC', text)
        self.assertIn('```', text)
        self.assertIn('[documented here](https://example.com/switch)', text)
        self.assertIn('| Host | IP |', text)

    def test_markdown_source_documents_round_trip_verbatim(self):
        """A doc authored as Markdown exports its own source, not a re-render."""
        from docs.services.document_export import export_markdown
        text = export_markdown(self.md_doc).decode('utf-8')
        self.assertIn('- step one\n- step two', text)

    # -- HTML -------------------------------------------------------------
    def test_html_export_is_standalone_and_print_ready(self):
        from docs.services.document_export import export_html
        text = export_html(self.doc).decode('utf-8')
        self.assertTrue(text.startswith('<!DOCTYPE html>'))
        self.assertIn('<title>Network Overview</title>', text)
        self.assertIn('@media print', text)
        # The issue asked for background images gone on the printed page.
        self.assertIn('background-image: none !important', text)
        self.assertIn('Rack 3', text)
        self.assertIn('ExportCo', text)

    def test_html_export_escapes_metadata(self):
        from docs.services.document_export import export_html
        doc = Document.objects.create(
            organization=self.org, title='<script>x</script>', body='<p>hi</p>',
            content_type='html',
        )
        text = export_html(doc).decode('utf-8')
        self.assertIn('&lt;script&gt;x&lt;/script&gt;', text)
        self.assertNotIn('<title><script>', text)

    # -- DOCX -------------------------------------------------------------
    def _docx_parts(self, payload):
        import io as _io
        import zipfile
        with zipfile.ZipFile(_io.BytesIO(payload)) as zf:
            return {name: zf.read(name).decode('utf-8') for name in zf.namelist()}

    def test_docx_export_is_a_valid_ooxml_package(self):
        from docs.services.document_export import export_docx
        parts = self._docx_parts(export_docx(self.doc))
        for required in ('[Content_Types].xml', '_rels/.rels', 'word/document.xml',
                         'word/_rels/document.xml.rels', 'word/styles.xml',
                         'word/numbering.xml', 'docProps/core.xml'):
            self.assertIn(required, parts)

    def test_docx_document_xml_is_well_formed_and_carries_content(self):
        import xml.etree.ElementTree as ET
        from docs.services.document_export import export_docx
        parts = self._docx_parts(export_docx(self.doc))
        body = parts['word/document.xml']
        ET.fromstring(body)  # raises if malformed
        self.assertIn('Network Overview', body)
        self.assertIn('sw-core', body)
        self.assertIn('<w:tbl>', body)
        self.assertIn('Heading2', body)
        self.assertIn('<w:numPr>', body)

    def test_docx_hyperlinks_get_external_relationships(self):
        from docs.services.document_export import export_docx
        parts = self._docx_parts(export_docx(self.doc))
        self.assertIn('https://example.com/switch', parts['word/_rels/document.xml.rels'])
        self.assertIn('TargetMode="External"', parts['word/_rels/document.xml.rels'])
        self.assertIn('<w:hyperlink', parts['word/document.xml'])

    def test_docx_escapes_xml_metacharacters(self):
        import xml.etree.ElementTree as ET
        from docs.services.document_export import export_docx
        doc = Document.objects.create(
            organization=self.org, title='Fish & Chips <v2>',
            body='<p>a &lt; b &amp; c</p>', content_type='html',
        )
        parts = self._docx_parts(export_docx(doc))
        ET.fromstring(parts['word/document.xml'])
        self.assertIn('Fish &amp; Chips &lt;v2&gt;', parts['word/document.xml'])

    # -- PDF --------------------------------------------------------------
    def test_pdf_export_produces_a_pdf(self):
        from docs.services.document_export import export_pdf
        payload = export_pdf(self.doc)
        self.assertTrue(payload.startswith(b'%PDF'))
        self.assertIn(b'%%EOF', payload[-2048:])
        self.assertGreater(len(payload), 1500)

    def test_pdf_export_handles_an_empty_document(self):
        from docs.services.document_export import export_pdf
        doc = Document.objects.create(
            organization=self.org, title='Empty', body='', content_type='html')
        self.assertTrue(export_pdf(doc).startswith(b'%PDF'))

    # -- dispatch + archive ----------------------------------------------
    def test_export_document_returns_filename_and_mime(self):
        from docs.services.document_export import export_document
        payload, filename, mime = export_document(self.doc, 'docx')
        self.assertEqual(filename, 'network-overview.docx')
        self.assertIn('wordprocessingml', mime)
        self.assertTrue(payload)

    def test_unknown_format_raises(self):
        from docs.services.document_export import export_document
        with self.assertRaises(ValueError):
            export_document(self.doc, 'rtf')

    def test_archive_bundles_every_document_plus_an_index(self):
        import io as _io
        import zipfile
        from docs.services.document_export import export_archive
        payload = export_archive([self.doc, self.md_doc], 'md',
                                 archive_title='ExportCo documentation')
        with zipfile.ZipFile(_io.BytesIO(payload)) as zf:
            names = zf.namelist()
            self.assertIn('index.md', names)
            self.assertIn('network-overview.md', names)
            self.assertIn('runbook.md', names)
            index = zf.read('index.md').decode('utf-8')
        self.assertIn('# ExportCo documentation', index)
        self.assertIn('[Network Overview](network-overview.md)', index)
        self.assertIn('## Network', index)

    def test_archive_deduplicates_colliding_filenames(self):
        import io as _io
        import zipfile
        from docs.services.document_export import export_archive
        twin = Document.objects.create(
            organization=self.org, title='Network Overview', slug='network-overview-2',
            body='<p>copy</p>', content_type='html')
        payload = export_archive([self.doc, twin], 'md')
        with zipfile.ZipFile(_io.BytesIO(payload)) as zf:
            names = set(zf.namelist())
        self.assertIn('network-overview.md', names)
        self.assertIn('network-overview-1.md', names)


@override_settings(MIDDLEWARE=_TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DocumentExportViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='ExportViewCo', slug='export-view-co')
        cls.other_org = Organization.objects.create(name='OtherCo', slug='other-co-exp')
        cls.staff = User.objects.create_user(
            'exp-staff', 'exp@x.com', 'pw', is_staff=True, is_superuser=True)
        cls.doc = Document.objects.create(
            organization=cls.org, title='Firewall Rules', body=_SAMPLE_HTML,
            content_type='html', is_published=True)
        cls.foreign = Document.objects.create(
            organization=cls.other_org, title='Foreign Doc', body='<p>secret</p>',
            content_type='html', is_published=True)
        cls.global_article = Document.objects.create(
            organization=None, title='Global Playbook', body='<p>global</p>',
            content_type='html', is_global=True, is_published=True)

    def _login(self, c):
        c.force_login(self.staff)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.id
        s.save()

    def test_every_format_downloads(self):
        c = Client()
        self._login(c)
        expected = {
            'md': 'text/markdown',
            'html': 'text/html',
            'docx': 'wordprocessingml',
            'pdf': 'application/pdf',
        }
        for fmt, mime in expected.items():
            with self.subTest(fmt=fmt):
                r = c.get(f'/docs/{self.doc.slug}/export/{fmt}/')
                self.assertEqual(r.status_code, 200)
                self.assertIn(mime, r['Content-Type'])
                self.assertIn('attachment;', r['Content-Disposition'])
                self.assertIn(f'firewall-rules.{fmt}', r['Content-Disposition'])
                self.assertTrue(r.content)

    def test_html_inline_renders_in_browser(self):
        c = Client()
        self._login(c)
        r = c.get(f'/docs/{self.doc.slug}/export/html/?inline=1')
        self.assertEqual(r.status_code, 200)
        self.assertIn('inline;', r['Content-Disposition'])

    def test_exports_are_not_cached_by_proxies(self):
        c = Client()
        self._login(c)
        r = c.get(f'/docs/{self.doc.slug}/export/pdf/')
        self.assertIn('no-store', r['Cache-Control'])

    def test_unknown_format_404s(self):
        c = Client()
        self._login(c)
        self.assertEqual(c.get(f'/docs/{self.doc.slug}/export/rtf/').status_code, 404)

    def test_other_org_document_is_not_exportable(self):
        """Tenant isolation — the export path must not become a data leak."""
        c = Client()
        self._login(c)
        r = c.get(f'/docs/{self.foreign.slug}/export/md/')
        self.assertEqual(r.status_code, 404)

    def test_export_requires_login(self):
        r = Client().get(f'/docs/{self.doc.slug}/export/pdf/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login', r['Location'])

    def test_global_kb_export(self):
        c = Client()
        self._login(c)
        r = c.get(f'/docs/kb/{self.global_article.slug}/export/docx/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('global-playbook.docx', r['Content-Disposition'])

    def test_bulk_export_returns_zip_of_current_org(self):
        import io as _io
        import zipfile
        c = Client()
        self._login(c)
        r = c.get('/docs/export/md/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/zip')
        with zipfile.ZipFile(_io.BytesIO(r.content)) as zf:
            names = zf.namelist()
        self.assertIn('index.md', names)
        self.assertIn('firewall-rules.md', names)
        self.assertNotIn('foreign-doc.md', names)

    def test_bulk_export_honours_the_search_filter(self):
        import io as _io
        import zipfile
        Document.objects.create(
            organization=self.org, title='Backup Policy', body='<p>nightly</p>',
            content_type='html', is_published=True)
        c = Client()
        self._login(c)
        r = c.get('/docs/export/md/?q=Backup')
        with zipfile.ZipFile(_io.BytesIO(r.content)) as zf:
            names = zf.namelist()
        self.assertIn('backup-policy.md', names)
        self.assertNotIn('firewall-rules.md', names)

    def test_bulk_export_with_no_matches_redirects(self):
        c = Client()
        self._login(c)
        r = c.get('/docs/export/md/?q=nothing-matches-this')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/docs/', r['Location'])

    def test_bulk_export_unknown_format_404s(self):
        c = Client()
        self._login(c)
        self.assertEqual(c.get('/docs/export/rtf/').status_code, 404)

    def test_export_menu_rendered_on_detail_page(self):
        c = Client()
        self._login(c)
        r = c.get(f'/docs/{self.doc.slug}/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, f'/docs/{self.doc.slug}/export/pdf/')
        self.assertContains(r, f'/docs/{self.doc.slug}/export/docx/')
