"""seed_module_samples --only documents / vault / assets (v3.17.659): real
Word, Excel, PDF and CSV files that open, render a preview and download;
safe previews (escaped, zip-bomb and DTD refusal); idempotent seeding."""
import io
import shutil
import tempfile
import zipfile
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role
from core.demo_samples import CUSTOMER_SLUGS, MSP_SLUG
from core.demo_samples.sample_files import build_csv, build_docx, build_xlsx
from core.models import Organization
from psa.tests._base import TEST_MIDDLEWARE

MEDIA_TMP = tempfile.mkdtemp(prefix='clientst0r-sample-docs-test-')


def tearDownModule():
    shutil.rmtree(MEDIA_TMP, ignore_errors=True)


def _seed(*groups):
    out = StringIO()
    call_command('seed_module_samples', only=list(groups), stdout=out)
    return out.getvalue()


def _login(client, user, org):
    client.force_login(user)
    s = client.session
    s['2fa_prompted'] = True
    s['current_organization_id'] = org.id
    s.save()


def _body(resp):
    return b''.join(resp.streaming_content) if resp.streaming else resp.content


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, MEDIA_ROOT=MEDIA_TMP)
class DocumentSamplesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        for slug in CUSTOMER_SLUGS + (MSP_SLUG,):
            Organization.objects.create(name=slug.replace('-', ' ').title(), slug=slug)
        cls.admin = get_user_model().objects.create_superuser('admin', 'admin@example.com', 'pw-not-used')
        _seed('documents')

    def _docs(self):
        from docs.models import Document
        return Document.objects.filter(organization__slug__in=CUSTOMER_SLUGS)

    def test_every_customer_gets_each_file_type_and_second_run_adds_nothing(self):
        docs = self._docs()
        files = docs.filter(content_type='file')
        self.assertEqual(files.count(), 6 * len(CUSTOMER_SLUGS))
        exts = {d.file.name.rsplit('.', 1)[-1] for d in files}
        self.assertEqual(exts, {'docx', 'xlsx', 'pdf', 'csv'})
        self.assertEqual(docs.filter(content_type='html').count(), len(CUSTOMER_SLUGS))
        self.assertEqual(docs.filter(content_type='markdown').count(), len(CUSTOMER_SLUGS))
        for d in files:
            self.assertTrue(d.file.name.startswith('documents/files/'), d.file.name)
            self.assertEqual(d.file_size, d.file.size)
            self.assertTrue(d.file_type)
        before = docs.count()
        out = _seed('documents')
        self.assertEqual(self._docs().count(), before)
        self.assertIn('0 rows created', out)

    def test_detail_page_and_file_download_work_and_the_bytes_open(self):
        import openpyxl
        c = Client()
        for d in self._docs():
            _login(c, self.admin, d.organization)
            page = c.get(reverse('docs:document_detail', args=[d.slug]))
            self.assertEqual(page.status_code, 200, d.title)
            if d.content_type != 'file':
                continue
            resp = c.get(d.file.url)
            self.assertEqual(resp.status_code, 200, d.file.url)
            data = _body(resp)
            ext = d.file.name.rsplit('.', 1)[-1]
            if ext == 'xlsx':
                wb = openpyxl.load_workbook(io.BytesIO(data))
                ws = wb.active
                self.assertTrue(ws['A1'].value)
                self.assertTrue(any(isinstance(c.value, str) and c.value.startswith('=SUM(')
                                    for row in ws.iter_rows() for c in row))
            elif ext == 'docx':
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    self.assertIsNone(zf.testzip())
                    names = set(zf.namelist())
                    self.assertTrue({'[Content_Types].xml', '_rels/.rels', 'word/document.xml',
                                     'word/styles.xml'} <= names)
                    self.assertIn(b'<w:tbl>', zf.read('word/document.xml'))
            elif ext == 'pdf':
                self.assertTrue(data.startswith(b'%PDF-'))
                self.assertIn(b'%%EOF', data[-1024:])
            elif ext == 'csv':
                self.assertTrue(data.decode('utf-8').startswith('Name,Extension'))

    def test_previews_render_for_word_excel_and_csv(self):
        from docs.models import Document
        org = Organization.objects.get(slug=CUSTOMER_SLUGS[0])
        c = Client()
        _login(c, self.admin, org)
        expect = {
            'new-starter-it-checklist': ['Before day one', 'doc-file-preview', '<table'],
            'hardware-inventory': ['Asset tag', 'Warranty (3 yr)', '=SUM(H2:H25)'],
            'licence-renewals': ['Renewal date', 'Microsoft 365 Business Premium'],
            'phone-extensions': ['Extension', 'Reception (main line)'],
        }
        for slug, needles in expect.items():
            doc = Document.objects.get(organization=org, slug=slug)
            html = c.get(reverse('docs:document_detail', args=[doc.slug])).content.decode()
            for needle in needles:
                self.assertIn(needle, html, slug)
            self.assertIn('Download File', html)

    def test_the_other_customer_cannot_download(self):
        from docs.models import Document
        doc = Document.objects.filter(organization__slug=CUSTOMER_SLUGS[0], content_type='file').first()
        other = Organization.objects.get(slug=CUSTOMER_SLUGS[1])
        user = get_user_model().objects.create_user('docs-outsider', password='pw-657-out!')
        Membership.objects.create(user=user, organization=other, role=Role.READONLY, is_active=True)
        c = Client()
        _login(c, user, other)
        self.assertEqual(c.get(doc.file.url).status_code, 404)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, MEDIA_ROOT=MEDIA_TMP)
class FilePreviewSafetyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Preview Org', slug='preview-org-657')
        cls.admin = get_user_model().objects.create_superuser('prev-admin', 'p@example.com', 'pw-not-used')

    def setUp(self):
        self.c = Client()
        _login(self.c, self.admin, self.org)

    def _doc(self, filename, data, mime):
        from docs.models import Document
        from django.utils.text import slugify
        doc = Document(organization=self.org, title=filename, slug=slugify(filename), content_type='file',
                       file_size=len(data), file_type=mime, is_published=True, created_by=self.admin)
        doc.file.save(filename, ContentFile(data), save=False)
        doc.save()
        return doc

    def _page(self, doc):
        resp = self.c.get(reverse('docs:document_detail', args=[doc.slug]))
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def test_cell_and_paragraph_content_is_escaped(self):
        evil = '<script>alert(1)</script>'
        img = '<img src=x onerror=alert(2)>'
        pages = [
            self._page(self._doc('evil.csv', build_csv(['Name', 'Value'], [[evil, img]]), 'text/csv')),
            self._page(self._doc('evil.xlsx', build_xlsx('S', ['Name', 'Value'], [[evil, img]]),
                                 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')),
            self._page(self._doc('evil.docx', build_docx('t', [('h1', evil), ('p', img), ('table', [(evil, img)])]),
                                 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')),
        ]
        for html in pages:
            self.assertNotIn(evil, html)
            self.assertNotIn(img, html)
            self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)

    def test_zip_bomb_is_refused_before_decompressing(self):
        from docs.services import file_preview
        data = build_docx('big', [('p', 'x' * 5000)])
        doc = self._doc('big.docx', data,
                        'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        with patch.object(file_preview, 'MAX_UNCOMPRESSED_BYTES', 4096), \
                patch.object(file_preview, '_read_member', side_effect=AssertionError('read')):
            result = file_preview.build_preview(doc.file)
        self.assertIn('too large', result['error'])
        # And a real bomb: 70 MB of zeros declared in one member.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('word/document.xml', b'\0' * (70 * 1024 * 1024))
        bomb = self._doc('bomb.docx', buf.getvalue(),
                         'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        self.assertLess(bomb.file_size, 1024 * 1024)
        html = self._page(bomb)
        self.assertIn('Preview not available', html)
        self.assertIn('Download File', html)

    def test_docx_with_a_doctype_is_refused(self):
        buf = io.BytesIO()
        xml = (b'<?xml version="1.0"?><!DOCTYPE w [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
               b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
               b'<w:body><w:p><w:r><w:t>&b;</w:t></w:r></w:p></w:body></w:document>')
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('word/document.xml', xml)
        doc = self._doc('dtd.docx', buf.getvalue(),
                        'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        from docs.services.file_preview import build_preview
        self.assertIn('DTD', build_preview(doc.file)['error'])
        html = self._page(doc)
        self.assertIn('Preview not available', html)
        self.assertNotIn('aaaaaaaaaa', html)

    def test_corrupt_files_fall_back_to_download(self):
        for name in ('broken.xlsx', 'broken.docx'):
            html = self._page(self._doc(name, b'PK\x03\x04 not really a zip', 'application/octet-stream'))
            self.assertIn('Preview not available', html)
            self.assertIn('Download File', html)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, MEDIA_ROOT=MEDIA_TMP)
class VaultAndAssetSamplesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from hardware.models import HardwareModel, Manufacturer
        for slug in CUSTOMER_SLUGS + (MSP_SLUG,):
            Organization.objects.create(name=slug.replace('-', ' ').title(), slug=slug)
        cls.admin = get_user_model().objects.create_superuser('admin', 'admin@example.com', 'pw-not-used')
        mfr = Manufacturer.objects.create(name='Fortinet', slug='fortinet')
        HardwareModel.objects.create(manufacturer=mfr, model='FortiGate 60F', slug='fortigate-60f',
                                     category='firewall')
        _seed('vault', 'assets')

    def test_vault_samples_have_notes_secure_notes_and_totp(self):
        from vault.models import Password
        rows = Password.objects.filter(organization__slug__in=CUSTOMER_SLUGS[:2])
        self.assertEqual(rows.count(), 8)
        for pw in rows:
            self.assertTrue(pw.notes)
            self.assertTrue(pw.otp_secret)
            self.assertTrue(pw.generate_otp())
            self.assertTrue(pw.get_password())
        noted = [pw for pw in rows if pw.has_secure_notes]
        self.assertEqual(len(noted), 6)
        for pw in noted:
            self.assertTrue(pw.get_secure_notes())
            self.assertNotIn('Recovery', pw.encrypted_notes)
        self.assertFalse(Password.objects.filter(organization__slug__in=CUSTOMER_SLUGS[2:]).exists())

    def test_asset_samples_use_catalog_artwork_and_rerun_adds_nothing(self):
        from assets.models import Asset
        rows = Asset.objects.filter(image_source='artwork')
        self.assertEqual(rows.count(), 2)  # one catalog model × two customers
        for a in rows:
            self.assertEqual(a.artwork_model.model, 'FortiGate 60F')
            self.assertEqual(a.image_kind, 'artwork')
        from vault.models import Password
        before = (Asset.objects.count(), Password.objects.count())
        self.assertIn('0 rows created', _seed('vault', 'assets'))
        self.assertEqual((Asset.objects.count(), Password.objects.count()), before)
