"""v3.17.620 — readers can't open drafts or documents pending review by
link; editors and publishers can. Archived documents stay readable."""
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from accounts.models import Membership
from core.models import Organization
from docs.models import Document

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DraftAccessTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='DA', slug='da')
        self.live = Document.objects.create(
            organization=self.org, title='Live', slug='live', body='LIVEBODY')
        self.draft = Document.objects.create(
            organization=self.org, title='Draft', slug='draft', body='DRAFTBODY',
            is_published=False)
        self.pending = Document.objects.create(
            organization=self.org, title='Pending', slug='pending', body='PENDINGBODY',
            is_published=False, is_draft=True)
        self.archived = Document.objects.create(
            organization=self.org, title='Old', slug='old', body='OLDBODY',
            is_archived=True)

    def _client(self, role):
        user = User.objects.create_user(f'u-{role}', password='pw')
        Membership.objects.create(user=user, organization=self.org, role=role)
        c = Client()
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.pk
        s.save()
        return c

    def _paths(self, doc):
        return (f'/docs/{doc.slug}/', f'/docs/{doc.slug}/export/md/',
                f'/docs/id/{doc.pk}/versions/')

    def test_reader_blocked_from_unpublished(self):
        c = self._client('readonly')
        for doc in (self.draft, self.pending):
            for path in self._paths(doc):
                self.assertEqual(c.get(path).status_code, 404, path)

    def test_reader_opens_live_and_archived(self):
        c = self._client('readonly')
        self.assertContains(c.get('/docs/live/'), 'LIVEBODY')
        self.assertContains(c.get('/docs/old/'), 'OLDBODY')

    def test_editor_opens_unpublished(self):
        c = self._client('editor')
        for doc, body in ((self.draft, 'DRAFTBODY'), (self.pending, 'PENDINGBODY'),
                          (self.archived, 'OLDBODY')):
            self.assertContains(c.get(f'/docs/{doc.slug}/'), body)
