"""
Phase 22: internal / external KB separation (portal visibility set from the
editor, internal-only blocks removed from every customer surface: portal
page, portal search and request suggestions, customer-copy exports,
agreement snapshots, API flag) and KB analytics (least viewed, portal
views, dead links with an SSRF-safe external check).
"""
import io
import zipfile
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role
from core.models import Organization, SystemSetting

from .kb_link_models import KBDeadLink, KBExternalLink
from .kb_visibility import preprocess_markdown, strip_internal
from .models import Document
from .services import link_check
from .tests_lifecycle import TEST_MIDDLEWARE, _Base

HTML_BODY = ('<p>Restart the router.</p><div class="kb-internal"><p>Admin password is in vault item '
             '<b>zebrafish</b>.</p><div><p>nested</p></div></div><p>Then wait 2 minutes.</p>')
MD_BODY = 'Restart the router.\n\n:::internal\nUse the **zebrafish** console.\n:::\n\nThen wait.\n'


class StripInternalTests(TestCase):
    def test_html_block_and_nested_content_removed(self):
        out = strip_internal(HTML_BODY)
        self.assertNotIn('zebrafish', out)
        self.assertNotIn('nested', out)
        self.assertIn('Restart the router.', out)
        self.assertIn('Then wait 2 minutes.', out)

    def test_markdown_fence_becomes_internal_block(self):
        doc = Document(title='t', body=MD_BODY, content_type='markdown')
        staff_html = doc.render_content()
        self.assertIn('kb-internal', staff_html)
        self.assertIn('<strong>zebrafish</strong>', staff_html)  # still Markdown inside the block
        client_html = doc.render_for_client()
        self.assertNotIn('zebrafish', client_html)
        self.assertIn('Then wait.', client_html)

    def test_unclosed_fence_stays_internal(self):
        self.assertIn('</div>', preprocess_markdown(':::internal\nsecret'))
        doc = Document(title='t', body='ok\n\n:::internal\nsecret words', content_type='markdown')
        self.assertNotIn('secret', doc.render_for_client())

    def test_no_marker_is_untouched(self):
        self.assertEqual(strip_internal('<p>a &amp; b</p>'), '<p>a &amp; b</p>')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class PortalSeparationTests(TestCase):
    def setUp(self):
        from psa.models import ClientPSASettings
        s = SystemSetting.get_settings()
        s.psa_enabled = True
        s.save()
        self.org = Organization.objects.create(name='KB Co', slug='kbco')
        ClientPSASettings.objects.create(organization=self.org, portal_enabled=True)
        self.user = User.objects.create_user('cust', 'c@kb.test', 'pw')
        Membership.objects.create(user=self.user, organization=self.org, role=Role.READONLY, is_active=True)
        self.article = Document.objects.create(organization=self.org, title='Router restart', slug='router',
                                               body=HTML_BODY, is_published=True, is_client_visible=True)
        self.internal = Document.objects.create(organization=self.org, title='Router internals', slug='int',
                                                body='<p>zebrafish</p>', is_published=True)
        self.c = Client()
        self.c.force_login(self.user)
        s = self.c.session
        s['2fa_prompted'] = True
        s.save()

    def test_portal_page_hides_internal_blocks_and_sanitises(self):
        Document.objects.filter(pk=self.article.pk).update(
            body=HTML_BODY + '<script>alert(1)</script>')
        r = self.c.get('/portal/kb/router/')
        self.assertContains(r, 'Restart the router.')
        self.assertNotContains(r, 'zebrafish')
        self.assertNotContains(r, '<script>alert(1)</script>')
        self.assertEqual(self.c.get('/portal/kb/int/').status_code, 404)

    def test_portal_search_ignores_internal_only_words(self):
        r = self.c.get('/portal/kb/?q=zebrafish')
        self.assertNotContains(r, 'Router restart')
        self.assertNotContains(r, 'Router internals')
        r = self.c.get('/portal/kb/?q=wait+2+minutes')
        self.assertContains(r, 'Router restart')

    def test_request_suggestions_ignore_internal_only_words(self):
        from portal.request_views import suggest_kb_articles
        self.assertEqual(suggest_kb_articles(self.org, 'zebrafish'), [])
        self.assertEqual([d.title for d in suggest_kb_articles(self.org, 'minutes')], ['Router restart'])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class StaffSeparationTests(_Base):
    def test_publisher_sets_portal_visibility_editor_cannot(self):
        c = self.client_for(self.publisher)
        self.assertIn('is_client_visible', c.get('/docs/create/').context['form'].fields)
        c.post('/docs/create/', {'title': 'Ext', 'body': '<p>x</p>', 'content_type': 'html',
                                 'is_published': 'on', 'is_client_visible': 'on', 'kb_visibility_shown': '1'})
        self.assertTrue(Document.objects.get(title='Ext').is_client_visible)
        e = self.client_for(self.editor)
        self.assertNotIn('is_client_visible', e.get('/docs/create/').context['form'].fields)
        e.post('/docs/create/', {'title': 'Ed', 'body': '<p>x</p>', 'content_type': 'html',
                                 'is_client_visible': 'on', 'kb_visibility_shown': '1'})
        self.assertFalse(Document.objects.get(title='Ed').is_client_visible)

    def test_form_without_the_boxes_keeps_visibility(self):
        from .forms import DocumentForm
        doc = Document.objects.create(organization=self.org, title='Keep', slug='keep', body='x',
                                      is_published=True, is_client_visible=True)
        form = DocumentForm({'title': 'Keep 2', 'body': 'x', 'content_type': 'html', 'is_published': 'on',
                             'review_interval_days': 90}, instance=doc, organization=self.org)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        doc.refresh_from_db()
        self.assertTrue(doc.is_client_visible)

    def test_customer_copy_export_and_staff_export(self):
        doc = Document.objects.create(organization=self.org, title='Ext doc', slug='ext-doc', body=HTML_BODY,
                                      is_published=True, is_client_visible=True)
        Document.objects.create(organization=self.org, title='Int doc', slug='int-doc', body='<p>x</p>',
                                is_published=True)
        c = self.client_for(self.staff)
        staff_copy = c.get(f'/docs/{doc.slug}/export/html/').content.decode()
        self.assertIn('zebrafish', staff_copy)
        customer = c.get(f'/docs/{doc.slug}/export/html/?audience=customer').content.decode()
        self.assertNotIn('zebrafish', customer)
        self.assertIn('Restart the router.', customer)
        md = c.get(f'/docs/{doc.slug}/export/md/?audience=customer').content.decode()
        self.assertNotIn('zebrafish', md)
        self.assertEqual(c.get('/docs/int-doc/export/html/?audience=customer').status_code, 404)
        z = zipfile.ZipFile(io.BytesIO(c.get('/docs/export/html/?audience=customer').content))
        names = z.namelist()
        self.assertTrue(any('ext-doc' in n for n in names), names)
        self.assertFalse(any('int-doc' in n for n in names), names)
        self.assertNotIn(b'zebrafish', b''.join(z.read(n) for n in names))
        r = c.get(f'/docs/{doc.slug}/')
        self.assertContains(r, 'External · portal')

    def test_api_reports_visibility_read_only(self):
        from api.serializers import DocumentSerializer
        self.assertIn('is_client_visible', DocumentSerializer.Meta.fields)
        self.assertIn('is_client_visible', DocumentSerializer.Meta.read_only_fields)

    def test_agreement_snapshot_leaves_out_internal_blocks(self):
        from . import agreements
        doc = Document.objects.create(organization=self.org, title='MSA', slug='msa', body=HTML_BODY,
                                      is_published=True, created_by=self.staff, last_modified_by=self.staff)
        rev = agreements.make_agreement(doc, self.staff).latest_revision
        self.assertNotIn('zebrafish', rev.rendered_html)
        self.assertNotIn('zebrafish', rev.snapshot_html)
        self.assertIn('Restart the router.', rev.snapshot_html)


def _fake_http(results):
    calls = []

    def http(url):
        calls.append(url)
        return results.get(url, (True, 200, ''))
    http.calls = calls
    return http


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class KBAnalyticsTests(_Base):
    def _doc(self, title, body='<p>b</p>', **kw):
        kw.setdefault('is_published', True)
        return Document.objects.create(organization=self.org, title=title, body=body, **kw)

    def test_least_viewed_and_portal_lists(self):
        self._doc('Often', staff_view_count=50)
        self._doc('Rarely', staff_view_count=1)
        self._doc('Customer fave', is_client_visible=True, portal_view_count=30)
        self._doc('Customer ignored', is_client_visible=True)
        r = self.client_for(self.staff).get(reverse('docs:kb_analytics'))
        self.assertEqual([d.title for d in r.context['least_viewed']][:2], ['Rarely', 'Customer fave'])
        self.assertEqual([d.title for d in r.context['portal_most']], ['Customer fave'])
        self.assertEqual([d.title for d in r.context['portal_least']][0], 'Customer ignored')
        self.assertEqual(r.context['portal_count'], 2)

    def test_dead_internal_links(self):
        archived = self._doc('Old', is_archived=True)
        internal = self._doc('Internal one')
        ok = self._doc('Fine')
        body = (f'<a href="/docs/{ok.slug}/">ok</a> <a href="/docs/no-such-doc/">missing</a> '
                f'<a href="/docs/id/{archived.pk}/versions/">archived</a> '
                f'<a href="/docs/{internal.slug}/">internal</a> <a href="#top">anchor</a> '
                f'<a href="mailto:x@y.test">mail</a> <a href="/docs/create/">app page</a>')
        src = self._doc('Source', body=body)
        ext_src = self._doc('Customer source', body=f'<a href="/docs/{internal.slug}/">internal</a>',
                            is_client_visible=True)
        counts = link_check.run(check_external=False)
        self.assertEqual(counts['internal_dead'], 3)
        reasons = dict(KBDeadLink.objects.filter(document=src).values_list('url', 'reason'))
        self.assertEqual(reasons, {'/docs/no-such-doc/': 'Document does not exist',
                                   f'/docs/id/{archived.pk}/versions/': 'Document is archived'})
        self.assertEqual(KBDeadLink.objects.get(document=ext_src).reason,
                         'Links a customer-visible article to an internal document')
        # Fixed links disappear on the next run.
        Document.objects.filter(pk=src.pk).update(body=f'<a href="/docs/{ok.slug}/">ok</a>')
        link_check.run(check_external=False)
        self.assertFalse(KBDeadLink.objects.filter(document=src).exists())
        # Shown on the analytics page, and re-checkable there (internal only, no outbound).
        c = self.client_for(self.staff)
        self.assertContains(c.get(reverse('docs:kb_analytics')), 'Links a customer-visible article')
        with mock.patch.object(link_check, 'head_check', side_effect=AssertionError('no outbound')):
            self.assertEqual(c.post(reverse('docs:kb_analytics'), {'action': 'recheck_internal'}).status_code, 302)

    def test_external_links_checked_throttled_and_capped(self):
        src = self._doc('Links', body='<a href="https://dead.example.com/x">a</a> '
                                       '<a href="https://ok.example.com/">b</a> '
                                       '<a href="https://third.example.com/">c</a>')
        http = _fake_http({'https://dead.example.com/x': (False, 404, 'HTTP 404')})
        counts = link_check.run(http=http, max_external=2)
        self.assertEqual(len(http.calls), 2)  # capped
        self.assertEqual(counts['external_skipped'], 1)
        link_check.run(http=http, max_external=10)
        self.assertEqual(len(http.calls), 3)  # only the one not yet checked
        dead = KBDeadLink.objects.get(document=src)
        self.assertEqual((dead.kind, dead.url, dead.reason), ('external', 'https://dead.example.com/x', 'HTTP 404'))
        # Recheck after the interval.
        KBExternalLink.objects.update(last_checked_at=timezone.now() - timedelta(days=8))
        link_check.run(http=http)
        self.assertEqual(len(http.calls), 6)

    def test_head_check_never_fetches_non_public_addresses(self):
        with mock.patch('core.safe_http.urllib3_connection.create_connection') as connect:
            for url in ('http://127.0.0.1/', 'http://10.0.0.5/admin', 'http://169.254.169.254/latest/',
                        'http://localhost:8000/', 'http://[::1]/', 'ftp://example.com/'):
                ok, code, err = link_check.head_check(url)
                self.assertIsNone(ok, url)
                self.assertIn('Not checked', err)
            connect.assert_not_called()
        # Private links are recorded as "not checked", never as dead.
        src = self._doc('LAN', body='<a href="http://192.168.1.1/">router</a>')
        link_check.run()
        self.assertFalse(KBDeadLink.objects.filter(document=src).exists())
        self.assertIsNone(KBExternalLink.objects.get().ok)

    def test_redirect_to_private_address_is_refused(self):
        from core import safe_http

        def validate(url):
            if '127.0.0.1' in url:
                raise safe_http.UnsafeURLError('private')
            return url

        class _Resp:
            def __init__(self, code, location=None):
                self.status_code, self.headers = code, ({'Location': location} if location else {})
                self.is_redirect = location is not None

            def close(self):
                pass

        session = mock.MagicMock()
        session.__enter__.return_value = session
        session.head.return_value = _Resp(302, 'http://127.0.0.1/secret')
        with mock.patch('core.safe_http.build_guarded_session', return_value=session), \
                mock.patch('core.safe_http.validate_public_url', side_effect=validate):
            ok, code, err = link_check.head_check('https://public.example.com/')
        self.assertIsNone(ok)  # not checked, and the private hop was never requested
        self.assertEqual(session.head.call_count, 1)

    def test_command_and_scheduler_registration(self):
        from core.management.commands.run_scheduler import COMMAND_TASKS
        from core.models import ScheduledTask
        self.assertEqual(COMMAND_TASKS['kb_link_check'], ('kb_link_check', []))
        self.assertEqual(COMMAND_TASKS['agreement_reminders'], ('agreement_reminders', []))
        ScheduledTask.get_or_create_defaults()
        self.assertTrue(ScheduledTask.objects.filter(task_type='kb_link_check').exists())
        self.assertTrue(ScheduledTask.objects.filter(task_type='agreement_reminders').exists())
        out = io.StringIO()
        call_command('kb_link_check', '--internal-only', stdout=out)
        self.assertIn('KB link check', out.getvalue())
