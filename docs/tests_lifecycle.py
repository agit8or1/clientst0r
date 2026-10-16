"""
Document lifecycle: publish permissions + approval, ownership, version
history (view / diff / restore), archive, template lineage, KB analytics and
zero-result search logging.
"""
import io
import zipfile
from datetime import timedelta

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role
from core.models import Organization
from docs.models import Document, SearchQueryLog

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Lifecycle Co', slug='lc-co')
        cls.other_org = Organization.objects.create(name='Other Co', slug='lc-other')
        cls.editor = User.objects.create_user('lc-editor', 'e@x.com', 'pw')
        Membership.objects.create(user=cls.editor, organization=cls.org,
                                  role=Role.EDITOR, is_active=True)
        cls.publisher = User.objects.create_user('lc-publisher', 'p@x.com', 'pw')
        Membership.objects.create(user=cls.publisher, organization=cls.org,
                                  role=Role.ADMIN, is_active=True)
        cls.reader = User.objects.create_user('lc-reader', 'r@x.com', 'pw')
        Membership.objects.create(user=cls.reader, organization=cls.org,
                                  role=Role.READONLY, is_active=True)
        cls.outsider = User.objects.create_user('lc-outsider', 'o@x.com', 'pw')
        Membership.objects.create(user=cls.outsider, organization=cls.other_org,
                                  role=Role.ADMIN, is_active=True)
        cls.staff = User.objects.create_user('lc-staff', 's@x.com', 'pw',
                                             is_staff=True, is_superuser=True)

    def client_for(self, user, org=None):
        if user is self.staff or user.is_superuser:
            user.profile.user_type = 'staff'
            user.profile.save()
        c = Client()
        c.force_login(user)
        s = c.session
        s['2fa_prompted'] = True
        org = self.org if org is None else org
        if org:
            s['current_organization_id'] = org.id
        s.save()
        return c


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PublishPermissionTests(_Base):

    def test_editor_form_has_no_publish_controls(self):
        r = self.client_for(self.editor).get('/docs/create/')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('is_published', r.context['form'].fields)
        self.assertNotIn('requires_approval', r.context['form'].fields)
        r = self.client_for(self.publisher).get('/docs/create/')
        self.assertIn('is_published', r.context['form'].fields)

    def test_editor_without_docs_publish_cannot_publish_via_post(self):
        c = self.client_for(self.editor)
        r = c.post('/docs/create/', {
            'title': 'Editor doc', 'body': '<p>x</p>', 'content_type': 'html',
            'is_published': 'on',
        })
        self.assertEqual(r.status_code, 302)
        doc = Document.objects.get(title='Editor doc')
        self.assertFalse(doc.is_published)
        self.assertFalse(Document.objects.published().filter(pk=doc.pk).exists())
        # Editing with is_published=on doesn't publish it either.
        c.post(f'/docs/{doc.slug}/edit/', {
            'title': 'Editor doc', 'body': '<p>y</p>', 'content_type': 'html',
            'is_published': 'on',
        })
        doc.refresh_from_db()
        self.assertFalse(doc.is_published)
        self.assertEqual(doc.body, '<p>y</p>')

    def test_editor_cannot_approve_a_pending_draft(self):
        doc = Document.objects.create(organization=self.org, title='Pending',
                                      body='b', is_published=False, is_draft=True)
        self.client_for(self.editor).post(f'/docs/{doc.slug}/approve/', {'pk': doc.pk})
        doc.refresh_from_db()
        self.assertTrue(doc.is_draft)
        self.assertFalse(doc.is_published)

    def test_editor_cannot_republish_pending_draft_through_form(self):
        """The audit case: is_published=on in the form must not leave a
        pending draft with is_draft=True and is_published=True."""
        doc = Document.objects.create(organization=self.org, title='Pending two',
                                      body='b', is_published=False, is_draft=True)
        self.client_for(self.editor).post(f'/docs/{doc.slug}/edit/', {
            'title': 'Pending two', 'body': 'b2', 'content_type': 'html',
            'is_published': 'on',
        })
        doc.refresh_from_db()
        self.assertTrue(doc.is_draft)
        self.assertFalse(doc.is_published)

    def test_editor_edit_keeps_live_document_live(self):
        doc = Document.objects.create(organization=self.org, title='Live',
                                      body='b', is_published=True)
        self.client_for(self.editor).post(f'/docs/{doc.slug}/edit/', {
            'title': 'Live', 'body': 'changed', 'content_type': 'html',
        })
        doc.refresh_from_db()
        self.assertTrue(doc.is_live)
        self.assertEqual(doc.body, 'changed')

    def test_editor_upload_lands_as_draft(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client_for(self.editor).post('/docs/upload/', {
            'files': SimpleUploadedFile('notes.txt', b'hi', content_type='text/plain'),
        })
        doc = Document.objects.get(title='notes')
        self.assertFalse(doc.is_published)

    def test_publisher_can_publish(self):
        self.client_for(self.publisher).post('/docs/create/', {
            'title': 'Publisher doc', 'body': '<p>x</p>', 'content_type': 'html',
            'is_published': 'on',
        })
        doc = Document.objects.get(title='Publisher doc')
        self.assertTrue(doc.is_live)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RequiresApprovalTests(_Base):

    def test_requires_approval_goes_through_submit_then_approve(self):
        doc = Document.objects.create(organization=self.org, title='Change policy',
                                      body='v1', is_published=True,
                                      requires_approval=True, owner=self.editor)
        # Even a publisher's edit takes it offline.
        self.client_for(self.publisher).post(f'/docs/{doc.slug}/edit/', {
            'title': 'Change policy', 'body': 'v2', 'content_type': 'html',
            'is_published': 'on', 'requires_approval': 'on',
        })
        doc.refresh_from_db()
        self.assertFalse(doc.is_published)
        self.assertFalse(doc.is_draft)
        self.assertTrue(doc.requires_approval)

        # Detail page offers submit-for-review.
        editor = self.client_for(self.editor)
        r = editor.get(f'/docs/{doc.slug}/')
        self.assertContains(r, reverse('docs:kb_submit_for_review', args=[doc.slug]))

        editor.post(f'/docs/{doc.slug}/submit-for-review/', {'pk': doc.pk})
        doc.refresh_from_db()
        self.assertTrue(doc.is_draft)
        r = editor.get('/docs/approval-queue/')
        self.assertContains(r, 'Change policy')
        self.assertFalse(r.context['drafts'][0].user_can_publish)

        # Editor can't approve; publisher can.
        editor.post(f'/docs/{doc.slug}/approve/', {'pk': doc.pk})
        doc.refresh_from_db()
        self.assertFalse(doc.is_live)
        self.client_for(self.publisher).post(f'/docs/{doc.slug}/approve/', {'pk': doc.pk})
        doc.refresh_from_db()
        self.assertTrue(doc.is_live)
        self.assertEqual(doc.body, 'v2')

    def test_outsider_publisher_cannot_approve_other_customers_doc(self):
        doc = Document.objects.create(organization=self.org, title='Theirs',
                                      body='b', is_published=False, is_draft=True)
        self.client_for(self.outsider, org=self.other_org).post(
            f'/docs/{doc.slug}/approve/', {'pk': doc.pk})
        doc.refresh_from_db()
        self.assertTrue(doc.is_draft)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class DraftVisibilityTests(_Base):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from core.models import SystemSetting
        from psa.models import ClientPSASettings
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        ClientPSASettings.objects.create(organization=cls.org, portal_enabled=True)
        cls.portal_user = User.objects.create_user('lc-portal', 'pu@x.com', 'pw')
        Membership.objects.create(user=cls.portal_user, organization=cls.org,
                                  role=Role.READONLY, is_active=True)
        common = dict(organization=cls.org, body='zebracorn content',
                      is_client_visible=True)
        cls.live = Document.objects.create(title='zebracorn live', **common)
        # The inconsistent state the old form could produce.
        cls.pending = Document.objects.create(
            title='zebracorn pending', is_published=True, is_draft=True, **common)
        cls.draft = Document.objects.create(
            title='zebracorn draft', is_published=False, **common)

    def test_published_queryset(self):
        live = set(Document.objects.published().values_list('title', flat=True))
        self.assertIn('zebracorn live', live)
        self.assertNotIn('zebracorn pending', live)
        self.assertNotIn('zebracorn draft', live)

    def test_staff_list(self):
        r = self.client_for(self.staff).get('/docs/')
        titles = [d.title for d in r.context['org_docs']]
        self.assertIn('zebracorn live', titles)
        self.assertNotIn('zebracorn pending', titles)
        self.assertNotIn('zebracorn draft', titles)
        # Global view too.
        r = self.client_for(self.staff, org=False).get('/docs/')
        titles = [d.title for d in r.context['org_docs']]
        self.assertNotIn('zebracorn pending', titles)

    def test_global_search(self):
        r = self.client_for(self.staff).get(reverse('core:search'), {'q': 'zebracorn'})
        titles = [d.title for d in r.context['documents']]
        self.assertEqual(titles, ['zebracorn live'])

    def test_bulk_export(self):
        r = self.client_for(self.staff).get('/docs/export/md/')
        self.assertEqual(r.status_code, 200)
        names = ' '.join(zipfile.ZipFile(io.BytesIO(r.content)).namelist())
        self.assertIn('zebracorn-live', names)
        self.assertNotIn('pending', names)
        self.assertNotIn('draft', names)

    def test_portal(self):
        c = self.client_for(self.portal_user)
        r = c.get('/portal/kb/')
        self.assertContains(r, 'zebracorn live')
        self.assertNotContains(r, 'zebracorn pending')
        self.assertNotContains(r, 'zebracorn draft')
        self.assertEqual(c.get(f'/portal/kb/{self.pending.slug}/').status_code, 404)
        self.assertEqual(c.get(f'/portal/kb/{self.draft.slug}/').status_code, 404)

    def test_drafts_list_shows_them(self):
        r = self.client_for(self.editor).get('/docs/lifecycle/drafts/')
        titles = [d.title for d in r.context['documents']]
        self.assertIn('zebracorn pending', titles)
        self.assertIn('zebracorn draft', titles)
        self.assertNotIn('zebracorn live', titles)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class VersionHistoryTests(_Base):

    def setUp(self):
        self.doc = Document.objects.create(organization=self.org, title='Runbook',
                                           body='<p>one</p>', is_published=True,
                                           last_modified_by=self.editor)
        self.doc.body = '<p>two</p>'
        self.doc.save()  # -> v1 holds "one"

    def test_status_only_save_creates_no_version(self):
        self.doc.mark_reviewed(user=self.editor)
        self.assertEqual(self.doc.versions.count(), 1)

    def test_list_and_view_version(self):
        c = self.client_for(self.reader)
        r = c.get(reverse('docs:document_versions', args=[self.doc.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'v1')
        r = c.get(reverse('docs:document_version_detail', args=[self.doc.pk, 1]))
        self.assertContains(r, '<p>one</p>', html=True)

    def test_restore_creates_new_version_and_audits(self):
        from audit.models import AuditLog
        c = self.client_for(self.editor)
        r = c.post(reverse('docs:document_version_restore', args=[self.doc.pk, 1]))
        self.assertEqual(r.status_code, 302)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.body, '<p>one</p>')
        self.assertEqual(self.doc.versions.count(), 2)
        self.assertEqual(self.doc.versions.first().body, '<p>two</p>')
        self.assertTrue(self.doc.is_live)
        self.assertTrue(AuditLog.objects.filter(
            object_type='docs.Document', object_id=self.doc.pk,
            description__icontains='version 1').exists())

    def test_restore_requires_docs_edit(self):
        r = self.client_for(self.reader).post(
            reverse('docs:document_version_restore', args=[self.doc.pk, 1]))
        self.assertEqual(r.status_code, 403)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.body, '<p>two</p>')

    def test_restore_on_requires_approval_doc_goes_to_draft(self):
        Document.objects.filter(pk=self.doc.pk).update(requires_approval=True)
        self.client_for(self.publisher).post(
            reverse('docs:document_version_restore', args=[self.doc.pk, 1]))
        self.doc.refresh_from_db()
        self.assertFalse(self.doc.is_published)

    def test_other_customer_cannot_see_history(self):
        r = self.client_for(self.outsider, org=self.other_org).get(
            reverse('docs:document_versions', args=[self.doc.pk]))
        self.assertEqual(r.status_code, 404)

    def test_diff_output_is_escaped(self):
        self.doc.body = '<script>alert("pwn")</script><img src=x onerror=alert(1)>'
        self.doc.save()  # -> v2 holds "two", current is the payload
        r = self.client_for(self.reader).get(
            reverse('docs:document_version_diff', args=[self.doc.pk, 2]))
        self.assertEqual(r.status_code, 200)
        content = r.content.decode()
        self.assertNotIn('<script>alert("pwn")', content)
        self.assertNotIn('<img src=x onerror', content)
        self.assertIn('&lt;script&gt;alert(&quot;pwn&quot;)&lt;/script&gt;', content)
        self.assertIn('-&lt;p&gt;two&lt;/p&gt;', content)

    def test_version_view_is_sanitized(self):
        self.doc.body = '<script>alert(1)</script>'
        self.doc.save()
        self.doc.body = 'clean'
        self.doc.save()
        r = self.client_for(self.reader).get(
            reverse('docs:document_version_detail', args=[self.doc.pk, 3]))
        self.assertNotIn('<script>alert(1)</script>', r.content.decode())


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ArchiveTests(_Base):

    def test_archived_list_and_unarchive(self):
        doc = Document.objects.create(organization=self.org, title='Old SOP',
                                      body='b', is_archived=True)
        other = Document.objects.create(organization=self.other_org, title='Not mine',
                                        body='b', is_archived=True)
        r = self.client_for(self.reader).get('/docs/lifecycle/archived/')
        titles = [d.title for d in r.context['documents']]
        self.assertIn('Old SOP', titles)
        self.assertNotIn('Not mine', titles)
        # Read-only can't unarchive.
        r = self.client_for(self.reader).post(reverse('docs:document_unarchive', args=[doc.pk]))
        self.assertEqual(r.status_code, 403)
        self.client_for(self.editor).post(reverse('docs:document_unarchive', args=[doc.pk]))
        doc.refresh_from_db()
        self.assertFalse(doc.is_archived)
        self.assertTrue(doc.is_live)
        other.refresh_from_db()
        self.assertTrue(other.is_archived)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class OwnershipTests(_Base):

    def test_owner_choices_are_staff_and_org_members(self):
        doc = Document.objects.create(organization=self.org, title='Owned',
                                      body='b', owner=self.editor)
        r = self.client_for(self.publisher).get(f'/docs/{doc.slug}/edit/')
        owners = set(r.context['form'].fields['owner'].queryset.values_list('username', flat=True))
        self.assertIn('lc-editor', owners)
        self.assertIn('lc-staff', owners)
        self.assertNotIn('lc-outsider', owners)

    def test_outsider_cannot_be_assigned_owner(self):
        doc = Document.objects.create(organization=self.org, title='Owned2',
                                      body='b', owner=self.editor, is_published=True)
        r = self.client_for(self.publisher).post(f'/docs/{doc.slug}/edit/', {
            'title': 'Owned2', 'body': 'b', 'content_type': 'html',
            'is_published': 'on', 'owner': self.outsider.pk,
            'review_interval_days': 30,
        })
        self.assertEqual(r.status_code, 200)  # form error
        doc.refresh_from_db()
        self.assertEqual(doc.owner, self.editor)

    def test_owner_and_review_interval_saved_and_shown(self):
        doc = Document.objects.create(organization=self.org, title='Owned3',
                                      body='b', owner=self.editor, is_published=True)
        self.client_for(self.publisher).post(f'/docs/{doc.slug}/edit/', {
            'title': 'Owned3', 'body': 'b', 'content_type': 'html',
            'is_published': 'on', 'owner': self.reader.pk,
            'review_interval_days': 30,
        })
        doc.refresh_from_db()
        self.assertEqual(doc.owner, self.reader)
        self.assertEqual(doc.review_interval_days, 30)
        r = self.client_for(self.reader).get(f'/docs/{doc.slug}/')
        self.assertContains(r, 'lc-reader')
        self.assertContains(r, timezone.localtime(doc.next_review_due).strftime('%Y-%m-%d'))


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class TemplateDriftTests(_Base):

    def setUp(self):
        self.template = Document.objects.create(
            organization=self.org, title='Onboarding template',
            body='step one\nstep two', is_template=True)

    def test_create_from_template_records_lineage_and_drift_is_informational(self):
        self.client_for(self.publisher).post(
            f'/docs/create/?template={self.template.pk}', {
                'title': 'Acme onboarding', 'body': 'step one\nstep two\nacme',
                'content_type': 'markdown', 'is_published': 'on',
            })
        doc = Document.objects.get(title='Acme onboarding')
        self.assertEqual(doc.source_template, self.template)
        self.assertEqual(doc.source_template_version, 1)
        self.assertFalse(doc.is_behind_template)

        # Template changes -> version 2.
        self.template.body = 'step one\nstep two\nstep three'
        self.template.save()
        self.template.refresh_from_db()
        self.assertEqual(self.template.template_version, 2)
        self.assertTrue(self.template.versions.filter(template_version=1).exists())

        c = self.client_for(self.editor)
        r = c.get(reverse('docs:template_documents', args=[self.template.pk]))
        self.assertEqual(r.status_code, 200)
        rows = r.context['rows']
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['behind'])
        self.assertEqual(r.context['behind_count'], 1)

        r = c.get(reverse('docs:template_document_diff', args=[self.template.pk, doc.pk]))
        self.assertContains(r, '+step three')

        # Viewing drift never changes the document.
        doc.refresh_from_db()
        self.assertEqual(doc.body, 'step one\nstep two\nacme')
        versions_before = doc.versions.count()

        c.post(reverse('docs:template_document_mark_reviewed', args=[self.template.pk, doc.pk]))
        doc.refresh_from_db()
        self.assertEqual(doc.template_reviewed_version, 2)
        self.assertFalse(doc.is_behind_template)
        self.assertEqual(doc.body, 'step one\nstep two\nacme')
        self.assertEqual(doc.versions.count(), versions_before)

    def test_source_template_id_from_form(self):
        self.client_for(self.publisher).post('/docs/create/', {
            'title': 'Via loader', 'body': 'x', 'content_type': 'markdown',
            'source_template_id': str(self.template.pk),
        })
        doc = Document.objects.get(title='Via loader')
        self.assertEqual(doc.source_template_id, self.template.pk)

    def test_other_customer_template_cannot_be_linked(self):
        foreign = Document.objects.create(organization=self.other_org, title='Foreign tpl',
                                          body='x', is_template=True)
        self.client_for(self.publisher).post('/docs/create/', {
            'title': 'No foreign', 'body': 'x', 'content_type': 'markdown',
            'source_template_id': str(foreign.pk),
        })
        self.assertIsNone(Document.objects.get(title='No foreign').source_template_id)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SearchLoggingTests(_Base):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from vault.models import Password
        pw = Password(organization=cls.org, title='quasarvault router', username='admin')
        pw.set_password('not-logged-secret')
        pw.save()

    def test_zero_result_global_search_is_logged_normalized(self):
        self.client_for(self.staff).get(reverse('core:search'), {'q': '  Nothing   HERE  '})
        log = SearchQueryLog.objects.get()
        self.assertEqual(log.query, 'nothing here')
        self.assertEqual(log.source, 'global')
        self.assertEqual(log.result_count, 0)
        self.assertEqual(log.user, self.staff)
        self.assertEqual(log.organization, self.org)

    def test_searches_with_results_are_not_logged(self):
        Document.objects.create(organization=self.org, title='findable', body='b')
        self.client_for(self.staff).get(reverse('core:search'), {'q': 'findable'})
        self.assertFalse(SearchQueryLog.objects.exists())

    def test_vault_queries_are_never_logged(self):
        c = self.client_for(self.staff)
        # Matches only a password: total isn't zero, nothing stored.
        c.get(reverse('core:search'), {'q': 'quasarvault'})
        # The vault's own search endpoint never logs, hit or miss.
        c.get(reverse('vault:password_list_datatables'), {'search[value]': 'quasarvault'})
        c.get(reverse('vault:password_list_datatables'), {'search[value]': 'no-such-cred'})
        self.assertFalse(SearchQueryLog.objects.filter(query__contains='quasarvault').exists())
        self.assertFalse(SearchQueryLog.objects.filter(query__contains='no-such-cred').exists())
        self.assertFalse(SearchQueryLog.objects.exists())

    def test_docs_and_global_kb_searches_logged(self):
        c = self.client_for(self.staff)
        c.get('/docs/', {'q': 'missing doc topic'})
        c.get('/docs/kb/', {'q': 'missing kb topic'})
        self.assertEqual(
            set(SearchQueryLog.objects.values_list('source', 'query')),
            {('docs', 'missing doc topic'), ('global_kb', 'missing kb topic')})

    def test_prune_after_retention(self):
        old = SearchQueryLog.record('old query', result_count=0, source='global')
        SearchQueryLog.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=91))
        SearchQueryLog.record('new query', result_count=0, source='global')
        self.assertEqual(SearchQueryLog.prune(), 1)
        self.assertEqual(list(SearchQueryLog.objects.values_list('query', flat=True)),
                         ['new query'])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AnalyticsTests(_Base):

    def test_staff_views_counted_and_analytics_page(self):
        viewed = Document.objects.create(organization=self.org, title='Popular',
                                         body='b', is_published=True)
        Document.objects.create(organization=self.org, title='Lonely',
                                body='b', is_published=True)
        Document.objects.create(
            organization=self.org, title='Stale one', body='b', is_published=True,
            review_interval_days=10, last_reviewed_at=timezone.now() - timedelta(days=30))
        SearchQueryLog.record('vpn setup', result_count=0, source='docs')
        SearchQueryLog.record('vpn setup', result_count=0, source='global')

        c = self.client_for(self.staff)
        c.get(f'/docs/{viewed.slug}/')
        c.get(f'/docs/{viewed.slug}/')
        viewed.refresh_from_db()
        self.assertEqual(viewed.staff_view_count, 2)
        self.assertIsNotNone(viewed.last_viewed_at)
        self.assertEqual(viewed.versions.count(), 0)

        r = c.get(reverse('docs:kb_analytics'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual([d.title for d in r.context['most_viewed']], ['Popular'])
        never = [d.title for d in r.context['never_viewed']]
        self.assertIn('Lonely', never)
        self.assertNotIn('Popular', never)
        self.assertEqual([s['doc'].title for s in r.context['stale']], ['Stale one'])
        self.assertEqual(r.context['zero_queries'][0]['query'], 'vpn setup')
        self.assertEqual(r.context['zero_queries'][0]['n'], 2)

    def test_analytics_staff_only(self):
        r = self.client_for(self.publisher).get(reverse('docs:kb_analytics'))
        self.assertEqual(r.status_code, 403)
