"""SR-05: files stored as documents are checked (type, size, content)."""
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from . import upload_check
from .forms import DocumentForm
from .models import Document
from .tests_lifecycle import TEST_MIDDLEWARE, _Base

PDF = b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n'
HTML = b'<html><script>alert(1)</script></html>'


class CheckTests(TestCase):
    def f(self, name, data, ctype='application/octet-stream'):
        return SimpleUploadedFile(name, data, content_type=ctype)

    def test_pdf_accepted_with_type_from_name(self):
        f = self.f('runbook.pdf', PDF, 'text/html')
        self.assertEqual(upload_check.check(f), '')
        self.assertEqual(upload_check.stored_type(f), 'application/pdf')

    def test_html_and_scripts_refused(self):
        for name in ('page.html', 'page.htm', 'run.ps1', 'x.exe', 'invoice.pdf.exe', 'evil.exe.txt', 'noext'):
            self.assertEqual(upload_check.check(self.f(name, b'data')), 'file type not allowed', name)

    def test_html_declared_as_image_refused(self):
        self.assertIn('does not match', upload_check.check(self.f('photo.png', HTML, 'image/png')))

    def test_oversize_refused(self):
        f = self.f('big.txt', b'x')
        f.size = upload_check.MAX_DOCUMENT_BYTES + 1
        self.assertIn('limit', upload_check.check(f))

    def test_common_office_types_still_allowed(self):
        for name in ('notes.txt', 'diagram.vsdx', 'mail.msg', 'sheet.ods', 'config.yaml'):
            self.assertEqual(upload_check.check(self.f(name, b'data')), '', name)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, MEDIA_ROOT=tempfile.mkdtemp())
class BulkUploadTests(_Base):
    def test_bulk_upload_stores_good_and_refuses_bad(self):
        c = self.client_for(self.publisher)
        files = [SimpleUploadedFile('good.pdf', PDF, content_type='application/pdf'),
                 SimpleUploadedFile('bad.html', HTML, content_type='text/html'),
                 SimpleUploadedFile('fake.png', HTML, content_type='image/png')]
        r = c.post('/docs/upload/', {'files': files}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['uploaded'], 1)
        self.assertEqual(len(data['failed']), 2)
        doc = Document.objects.get(organization=self.org, title='good')
        self.assertEqual(doc.file_type, 'application/pdf')
        self.assertFalse(Document.objects.filter(title__in=['bad', 'fake']).exists())


class FormTests(_Base):
    def test_form_refuses_html_file(self):
        form = DocumentForm(data={'title': 'T', 'content_type': 'file', 'body': ''},
                            files={'file': SimpleUploadedFile('x.html', HTML, content_type='text/html')},
                            organization=self.org)
        form.is_valid()
        self.assertIn('file', form.errors)
