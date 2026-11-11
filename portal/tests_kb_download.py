"""Portal download of uploaded-file KB articles: customer-visible ones only,
scoped to the portal user's customer (or global), audited."""
import shutil
import tempfile

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, Role
from audit.models import AuditLog
from core.models import Organization, SystemSetting
from docs.models import Document
from psa.models import ClientPSASettings

TEST_MIDDLEWARE = [m for m in django_settings.MIDDLEWARE
                   if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m]
MEDIA = tempfile.mkdtemp(prefix='gapacc-kb-')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, MEDIA_ROOT=MEDIA)
class PortalKBDownloadTests(TestCase):

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        cls.org = Organization.objects.create(name='KBD', slug='kbd')
        cls.other = Organization.objects.create(name='KBD Other', slug='kbd-other')
        for o in (cls.org, cls.other):
            ClientPSASettings.objects.create(organization=o, portal_enabled=True)
        cls.user = User.objects.create_user('kbd-user', 'k@x.test', 'pw')
        Membership.objects.create(user=cls.user, organization=cls.org, role=Role.READONLY)

        def doc(org, slug, **kw):
            kw.setdefault('is_client_visible', True)
            kw.setdefault('is_published', True)
            return Document.objects.create(
                organization=org, title=slug.replace('-', ' ').title(), slug=slug,
                content_type='file', file_size=11, file_type='application/pdf',
                file=SimpleUploadedFile(f'{slug}.pdf', b'%PDF-1.4 hi'), **kw)

        with override_settings(MEDIA_ROOT=MEDIA):
            cls.visible = doc(cls.org, 'vpn-guide')
            cls.internal = doc(cls.org, 'internal-runbook', is_client_visible=False)
            cls.foreign = doc(cls.other, 'other-guide')
            cls.global_doc = doc(None, 'global-guide', is_global=True)
            cls.draft = doc(cls.org, 'draft-guide', is_published=False)

    def setUp(self):
        self.c = Client()
        self.c.force_login(self.user)
        s = self.c.session
        s['2fa_prompted'] = True
        s.save()

    def _get(self, doc):
        return self.c.get(reverse('portal:kb_download', args=[doc.slug]))

    def test_customer_visible_article_downloads_and_is_audited(self):
        r = self._get(self.visible)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b''.join(r.streaming_content), b'%PDF-1.4 hi')
        self.assertEqual(r['X-Content-Type-Options'], 'nosniff')
        log = AuditLog.objects.get(object_type='docs.Document', object_id=self.visible.pk)
        self.assertEqual(log.organization, self.org)
        self.assertEqual(log.extra_data['source'], 'portal_kb_download')

    def test_global_article_downloads(self):
        self.assertEqual(self._get(self.global_doc).status_code, 200)

    def test_internal_foreign_and_draft_articles_404(self):
        for doc in (self.internal, self.foreign, self.draft):
            with self.subTest(doc=doc.slug):
                self.assertEqual(self._get(doc).status_code, 404)
        self.assertFalse(AuditLog.objects.filter(
            object_type='docs.Document', object_id__in=[self.internal.pk, self.foreign.pk,
                                                        self.draft.pk]).exists())

    def test_detail_page_links_the_download(self):
        r = self.c.get(reverse('portal:kb_detail', args=[self.visible.slug]))
        self.assertContains(r, reverse('portal:kb_download', args=[self.visible.slug]))
        # The raw media URL is never handed to the portal user.
        self.assertNotContains(r, self.visible.file.url)

    def test_non_member_gets_nothing(self):
        stranger = User.objects.create_user('kbd-stranger', 's@x.test', 'pw')
        c = Client()
        c.force_login(stranger)
        self.assertEqual(c.get(reverse('portal:kb_download', args=[self.visible.slug])).status_code, 404)
