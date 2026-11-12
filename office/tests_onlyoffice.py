"""ONLYOFFICE connector tests.

Two suites:

* ``OnlyOffice*Tests`` run against ``FakeDocumentServer``: a protocol model of
  ONLYOFFICE Docs 10.0 built from the documented payloads (healthcheck,
  command service, conversion service, signed outbox callbacks and
  downloads). It is installed in place of ``office.net.fetch``, but every
  URL still goes through the real ``net.check_url`` first, so the SSRF
  policy is exercised. When the fake "downloads" a document from clientst0r
  it calls the real Django endpoint with an outbox-signed request. This
  proves the connector speaks the protocol as documented; it does NOT prove
  a real Document Server behaves the same.

* ``OnlyOfficeRealServiceTests`` runs only when OFFICE_E2E_ONLYOFFICE_URL and
  OFFICE_E2E_ONLYOFFICE_SECRET are set (plus OFFICE_E2E_CALLBACK_BASE, the
  address of this test run's live server as the Document Server sees it).
  See docs/office/ONLYOFFICE.md "Real-service tests".
"""
import hashlib
import io
import json
import os
import re
import time
import uuid
import zipfile
from datetime import timedelta
from unittest import mock, skipUnless
from urllib.parse import urlsplit

import jwt
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, LiveServerTestCase, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role
from audit.models import AuditLog
from office import diagnostics, net, sessions, storage, targets, tokens
from office import tests as core
from office.models import EditorInstance, EditSession, FileRevision, OfficeSettings, QuarantinedSave
from office.providers import get_provider
from office.providers.onlyoffice import OnlyOfficeProvider, build_capabilities, client, signing, state
from office.providers.onlyoffice import callback as cb

SECRET = 'a-long-random-test-secret-123'
DS = 'https://docs.example.com'
APP = 'https://app.example.com'


def outbox_token(payload, secret=SECRET, operation='callback', exp_delta=300, alg='HS256',
                 wrap=True):
    claims = {'payload': payload} if wrap else dict(payload)
    if operation:
        claims['operation'] = operation
    if exp_delta is not None:
        claims['exp'] = int(time.time()) + exp_delta
    if alg == 'none':
        return jwt.encode(claims, None, algorithm='none')
    return jwt.encode(claims, secret, algorithm=alg)


def docx_text(text):
    return core.docx_with_text(text)


class FakeDocumentServer:
    """ONLYOFFICE Docs 10.0 as seen over HTTP by clientst0r.

    Implements GET /healthcheck, POST /command (version, license, forcesave,
    drop, info) and POST /converter, each checking the inbox JWT the way
    Docs does; serves its own cache URLs; and can send outbox-signed
    callbacks and document downloads to clientst0r."""

    def __init__(self, secret=SECRET, version='10.0.0.169', origin=DS):
        self.secret = secret
        self.version = version
        self.origin = origin
        self.files = {}
        self.requests = []
        self.commands = []
        self.open_keys = set()
        self.healthy = True
        self.converter_enabled = True
        self.django = Client()

    # -- the fetch replacement ------------------------------------------
    def fetch(self, url, instance, max_bytes, *, method='GET', headers=None, data=None, timeout=None):
        net.check_url(url, instance)          # the real destination policy
        self.requests.append((method, url))
        parts = urlsplit(url)
        origin = f'{parts.scheme}://{parts.netloc}'
        if origin != self.origin:
            raise net.OfficeFetchError('fake: no such host')
        path = parts.path
        if path == '/healthcheck':
            body = b'true' if self.healthy else b'false'
            return self._result(url, 200, body, max_bytes)
        if path == '/command':
            return self._result(url, 200, json.dumps(self._command(headers, data)).encode(), max_bytes)
        if path == '/converter':
            if not self.converter_enabled:
                return self._result(url, 404, b'not found', max_bytes)
            return self._result(url, 200, json.dumps(self._convert(headers, data)).encode(), max_bytes)
        if path.startswith('/cache/files/'):
            if url not in self.files:
                return self._result(url, 404, b'', max_bytes)
            return self._result(url, 200, self.files[url], max_bytes)
        return self._result(url, 404, b'', max_bytes)

    def _result(self, url, status, body, max_bytes):
        if len(body) > max_bytes:
            raise net.OfficeFetchError(f'Response is larger than {max_bytes} bytes')
        return net.FetchResult(url, status, {}, body, peer_ip='192.0.2.10')

    def _inbox_ok(self, headers, body, operation):
        """Docs: header token (payload wrapper) with the inbox secret; the
        operation must not be an outgoing one."""
        raw = (headers or {}).get('Authorization', '')
        if not raw.startswith('Bearer '):
            return False
        try:
            claims = jwt.decode(raw[7:], self.secret, algorithms=['HS256'])
        except jwt.PyJWTError:
            return False
        if claims.get('operation') in ('callback', 'download'):
            return False
        if claims.get('operation') not in (None, operation):
            return False
        payload = claims.get('payload') or {}
        return all(payload.get(k) == v for k, v in body.items() if k != 'token')

    def _command(self, headers, data):
        body = json.loads(data)
        self.commands.append(body)
        if not self._inbox_ok(headers, body, 'command'):
            return {'error': 6}
        c = body.get('c')
        if c == 'version':
            return {'error': 0, 'version': self.version}
        if c == 'license':
            return {'error': 0, 'license': {}, 'server': {'packageType': 0, 'buildVersion': self.version}}
        if c in ('forcesave', 'info', 'drop'):
            if body.get('key') not in self.open_keys:
                return {'error': 1, 'key': body.get('key')}
            if c == 'forcesave' and getattr(self, 'no_changes', False):
                return {'error': 4, 'key': body['key']}
            return {'error': 0, 'key': body['key']}
        return {'error': 5}

    def outbox_get(self, url):
        """Docs downloading a URL from clientst0r (operation 'download')."""
        parts = urlsplit(url)
        path = parts.path + ('?' + parts.query if parts.query else '')
        return self.django.get(path, HTTP_AUTHORIZATION='Bearer ' + outbox_token(
            {'url': url}, self.secret, operation='download'))

    def _convert(self, headers, data):
        body = json.loads(data)
        if not self._inbox_ok(headers, body, 'converter'):
            return {'error': -8}
        resp = self.outbox_get(body['url'])
        if resp.status_code != 200:
            return {'error': -4}
        source = b''.join(resp.streaming_content) if resp.streaming else resp.content
        out = body['outputtype']
        if out == 'pdf':
            result = b'%PDF-1.7\n% fake conversion of ' + str(len(source)).encode() + b' bytes\n%%EOF'
        elif out == 'docx':
            result = docx_text('converted by fake Docs')
        else:
            result = core.blank(out)
        url = self.put_file(result, out)
        return {'endConvert': True, 'fileType': out, 'fileUrl': url, 'percent': 100}

    def put_file(self, data, ext='docx'):
        url = f'{self.origin}/cache/files/data/{uuid.uuid4().hex}/output.{ext}?md5=x&expires=9999999999'
        self.files[url] = data
        return url

    # -- callbacks -------------------------------------------------------
    def callback(self, test_client, session, status, *, key=None, data=None, users=None,
                 url=None, secret=None, token=None, extra_headers=None, body_extra=None,
                 **fields):
        key = key or (EditSession.objects.get(pk=session.pk).provider_state or {}).get('oo_key')
        payload = {'key': key, 'status': status}
        if users is not None:
            payload['users'] = users
        if data is not None:
            payload['url'] = self.put_file(data)
            payload.setdefault('filetype', 'docx')
        if url is not None:
            payload['url'] = url
        payload.update(fields)
        body = dict(payload)
        body.update(body_extra or {})
        headers = dict(extra_headers or {})
        if token is None:
            token = outbox_token(payload, secret or self.secret)
        if token:
            headers.setdefault('HTTP_AUTHORIZATION', 'Bearer ' + token)
        path = reverse('office:onlyoffice_callback', args=[session.pk])
        return test_client.post(path, data=json.dumps(body), content_type='application/json',
                                **headers)


@override_settings(MIDDLEWARE=core.TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class OnlyOfficeTestBase(core.OfficeTestBase):
    def setUp(self):
        super().setUp()
        cache.clear()
        from office import providers
        providers.register(OnlyOfficeProvider(), replace=True)
        self.ds = FakeDocumentServer()
        patcher = mock.patch('office.net.fetch', side_effect=self.ds.fetch)
        self.fetch_mock = patcher.start()
        self.addCleanup(patcher.stop)
        self.provider = get_provider('onlyoffice')
        self.rf = RequestFactory()

    def make_instance(self, **kw):
        kw.setdefault('browser_url', DS + '/')
        kw.setdefault('callback_base_url', APP + '/')
        kw.setdefault('shared_secret', SECRET)
        kw.setdefault('capabilities', build_capabilities(True).to_json())
        return super().make_instance(**kw)

    def setup_doc(self, user=None, org=None, instance=None):
        instance = instance or EditorInstance.objects.first() or self.make_instance()
        t = targets.target_for(self.make_doc(org=org))
        s = sessions.open_session(t, user or self.editor, mode='edit', instance=instance)
        page = self.page(s)
        self.ds.open_keys.add(page.config['docConfig']['document']['key'])
        return t, EditSession.objects.get(pk=s.pk), page

    def page(self, session):
        req = self.rf.get('/', HTTP_USER_AGENT='Mozilla/5.0 (X11; Linux x86_64)')
        req.user = session.user
        return self.provider.editor_page_context(EditSession.objects.get(pk=session.pk), req)

    def key(self, session):
        return EditSession.objects.get(pk=session.pk).provider_state['oo_key']


# ---------------------------------------------------------------------------
# Editor config
# ---------------------------------------------------------------------------

class OnlyOfficeConfigTests(OnlyOfficeTestBase):
    def test_config_is_signed_hs256_with_the_instance_secret(self):
        t, s, page = self.setup_doc()
        cfg = dict(page.config['docConfig'])
        token = cfg.pop('token')
        self.assertEqual(jwt.get_unverified_header(token)['alg'], 'HS256')
        self.assertEqual(jwt.decode(token, SECRET, algorithms=['HS256']), cfg)
        with self.assertRaises(jwt.InvalidSignatureError):
            jwt.decode(token, 'some-other-secret-value-0000', algorithms=['HS256'])
        self.assertNotIn(SECRET, json.dumps(page.config))

    def test_config_fields_edit_mode(self):
        t, s, page = self.setup_doc()
        cfg = page.config['docConfig']
        self.assertEqual(cfg['documentType'], 'word')
        doc = cfg['document']
        self.assertEqual(doc['fileType'], 'docx')
        self.assertEqual(doc['title'], t.filename)
        self.assertRegex(doc['key'], r'^[0-9A-Za-z._=-]{1,128}$')
        self.assertTrue(doc['url'].startswith(
            APP + reverse('office:onlyoffice_file', args=[s.pk]) + '?access_token='))
        self.assertTrue(doc['permissions']['edit'])
        self.assertTrue(doc['permissions']['comment'])
        self.assertTrue(doc['permissions']['review'])
        ed = cfg['editorConfig']
        self.assertEqual(ed['mode'], 'edit')
        self.assertEqual(ed['callbackUrl'], APP + reverse('office:onlyoffice_callback', args=[s.pk]))
        self.assertEqual(ed['user']['id'], state.oo_user_id(self.editor))
        self.assertNotIn(self.editor.username, ed['user']['id'])
        self.assertEqual(ed['coEditing'], {'mode': 'fast', 'change': True})
        self.assertFalse(ed['customization']['plugins'])
        self.assertFalse(ed['customization']['macros'])
        self.assertTrue(ed['customization']['ai']['disabled'])
        self.assertTrue(ed['customization']['forcesave'])
        self.assertEqual(page.script_urls, [DS + '/web-apps/apps/api/documents/api.js'])
        self.assertEqual(page.csp, {'script-src': [DS], 'frame-src': [DS], 'connect-src': [DS]})
        self.assertTrue(page.config['forcesaveUrl'])

    def test_view_mode_has_no_write_rights_or_callback(self):
        inst = self.make_instance()
        t = targets.target_for(self.make_doc())
        s = sessions.open_session(t, self.reader, mode='view', instance=inst)
        page = self.page(s)
        cfg = page.config['docConfig']
        self.assertEqual(cfg['editorConfig']['mode'], 'view')
        self.assertNotIn('callbackUrl', cfg['editorConfig'])
        perms = cfg['document']['permissions']
        self.assertFalse(perms['edit'] or perms['comment'] or perms['review'])
        self.assertEqual(page.config['forcesaveUrl'], '')
        tok = tokens._lookup(cfg['document']['url'].split('access_token=')[1])
        self.assertEqual(tok.ops, ['read'])

    def test_comments_follow_capabilities(self):
        caps = build_capabilities(True).to_json()
        caps['comments'] = False
        caps['review'] = False
        self.make_instance(capabilities=caps)
        t, s, page = self.setup_doc()
        perms = page.config['docConfig']['document']['permissions']
        self.assertTrue(perms['edit'])
        self.assertFalse(perms['comment'])
        self.assertFalse(perms['review'])

    def test_default_or_missing_secret_refuses_to_build_a_page(self):
        from office.providers import NotConfigured
        inst = self.make_instance(shared_secret='developer-only-not-a-real-secret')
        t = targets.target_for(self.make_doc())
        s = sessions.open_session(t, self.editor, mode='edit', instance=inst)
        with self.assertRaises(NotConfigured):
            self.page(s)

    def test_editor_page_view_pins_csp_to_the_editor_origin(self):
        t, s, _ = self.setup_doc()
        self.client.force_login(self.editor)
        resp = self.client.get(reverse('office:editor', args=[s.pk]))
        self.assertEqual(resp.status_code, 200)
        csp = resp.get('Content-Security-Policy') or resp.get('Content-Security-Policy-Report-Only')
        self.assertIn(DS, csp)
        self.assertNotIn('evil', csp)
        html = resp.content.decode()
        self.assertIn('src="https://docs.example.com/web-apps/apps/api/documents/api.js"', html)
        self.assertIn('office-onlyoffice.js', html)
        self.assertIn('id="onlyoffice-editor"', html)
        self.assertNotIn(SECRET, html)

    def test_key_is_stable_for_a_co_editing_group(self):
        t, s1, p1 = self.setup_doc()
        s2 = sessions.open_session(t.refresh(), self.owner, mode='edit', instance=s1.instance)
        p2 = self.page(s2)
        self.assertEqual(p1.config['docConfig']['document']['key'],
                         p2.config['docConfig']['document']['key'])
        # Reloading the page keeps the key.
        self.assertEqual(self.page(s1).config['docConfig']['document']['key'],
                         p1.config['docConfig']['document']['key'])


# ---------------------------------------------------------------------------
# Callback authentication
# ---------------------------------------------------------------------------

class OnlyOfficeCallbackAuthTests(OnlyOfficeTestBase):
    def assertRefused(self, resp, code=403):
        self.assertEqual(resp.status_code, code)
        self.assertEqual(resp.json()['error'], 1)

    def test_missing_token(self):
        t, s, _ = self.setup_doc()
        self.assertRefused(self.ds.callback(self.client, s, 1, token=''))

    def test_wrong_secret(self):
        t, s, _ = self.setup_doc()
        self.assertRefused(self.ds.callback(self.client, s, 1, secret='another-long-secret-value-xx'))

    def test_bad_algorithms(self):
        t, s, _ = self.setup_doc()
        payload = {'key': self.key(s), 'status': 1}
        for alg in ('HS512', 'none'):
            self.assertRefused(self.ds.callback(self.client, s, 1, token=outbox_token(payload, alg=alg)))

    def test_expired_or_no_expiry(self):
        t, s, _ = self.setup_doc()
        payload = {'key': self.key(s), 'status': 1}
        self.assertRefused(self.ds.callback(self.client, s, 1,
                                            token=outbox_token(payload, exp_delta=-600)))
        self.assertRefused(self.ds.callback(self.client, s, 1,
                                            token=outbox_token(payload, exp_delta=None)))

    def test_wrong_operation_or_no_payload_wrapper(self):
        t, s, _ = self.setup_doc()
        payload = {'key': self.key(s), 'status': 1}
        self.assertRefused(self.ds.callback(self.client, s, 1,
                                            token=outbox_token(payload, operation='download')))
        self.assertRefused(self.ds.callback(self.client, s, 1, token=outbox_token(payload, wrap=False)))

    def test_body_must_not_contradict_the_token(self):
        t, s, _ = self.setup_doc()
        self.assertRefused(self.ds.callback(self.client, s, 1, body_extra={'status': 2}))

    def test_body_token_only_when_configured(self):
        t, s, _ = self.setup_doc()
        payload = {'key': self.key(s), 'status': 1}
        body_token = outbox_token(payload, wrap=False)
        path = reverse('office:onlyoffice_callback', args=[s.pk])
        body = json.dumps({**payload, 'token': body_token})
        resp = self.client.post(path, data=body, content_type='application/json')
        self.assertRefused(resp)
        with override_settings(OFFICE_ONLYOFFICE_INSTANCE_OPTIONS={s.instance.name: {'body_token': True}}):
            resp = self.client.post(path, data=body, content_type='application/json')
        self.assertEqual(resp.json(), {'error': 0})

    def test_unknown_session_and_key_mismatch(self):
        t, s, _ = self.setup_doc()
        path = reverse('office:onlyoffice_callback', args=[uuid.uuid4()])
        resp = self.client.post(path, data='{}', content_type='application/json')
        self.assertRefused(resp, 404)
        self.assertRefused(self.ds.callback(self.client, s, 1, key='some-other-key.0'))

    def test_refusals_never_log_the_token(self):
        t, s, _ = self.setup_doc()
        token = outbox_token({'key': self.key(s), 'status': 1}, secret='wrong-secret-0123456789')
        with self.assertLogs('office.onlyoffice', level='WARNING') as cm:
            self.ds.callback(self.client, s, 1, token=token)
        self.assertNotIn(token, ''.join(cm.output))

    @override_settings(OFFICE_ONLYOFFICE_CALLBACK_RATE=2)
    def test_rate_limited_per_session(self):
        t, s, _ = self.setup_doc()
        self.assertEqual(self.ds.callback(self.client, s, 1).status_code, 200)
        self.assertEqual(self.ds.callback(self.client, s, 1).status_code, 200)
        self.assertEqual(self.ds.callback(self.client, s, 1).status_code, 429)
        t2, s2, _ = self.setup_doc()
        self.assertEqual(self.ds.callback(self.client, s2, 1).status_code, 200)


# ---------------------------------------------------------------------------
# Callback statuses
# ---------------------------------------------------------------------------

class OnlyOfficeCallbackStatusTests(OnlyOfficeTestBase):
    def ok(self, resp):
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json(), {'error': 0})

    def test_status_1_records_collaborators(self):
        t, s, _ = self.setup_doc()
        s2 = sessions.open_session(t.refresh(), self.owner, mode='edit', instance=s.instance)
        self.page(s2)
        users = [state.oo_user_id(self.editor), state.oo_user_id(self.owner)]
        self.ok(self.ds.callback(self.client, s2, 1, users=users, actions=[{'type': 1, 'userid': users[1]}]))
        self.client.force_login(self.editor)
        data = self.client.get(reverse('office:onlyoffice_status', args=[s.pk])).json()
        self.assertEqual(sorted(c['id'] for c in data['collaborators']), sorted(users))
        self.assertIsNone(data['editorError'])
        self.assertEqual(FileRevision.objects.filter(document_id=t.pk).count(), 1)

    def test_status_2_saves_closes_and_rotates_the_key(self):
        t, s, _ = self.setup_doc()
        old_key = self.key(s)
        sessions.close(s, reason='closed by user', pending_final_save=True)
        content = docx_text('final')
        self.ok(self.ds.callback(self.client, s, 2, data=content,
                                 users=[state.oo_user_id(self.editor)]))
        rev = storage.current(t)
        self.assertEqual(rev.revision_number, 2)
        self.assertEqual(rev.source, 'editor_save')
        self.assertEqual(rev.sha256, hashlib.sha256(content).hexdigest())
        self.assertEqual(rev.created_by, self.editor)
        s.refresh_from_db()
        self.assertEqual(s.state, 'closed')
        self.assertTrue(s.provider_state['oo_spent'])
        # The next open uses a new key.
        s2 = sessions.open_session(t.refresh(), self.editor, mode='edit', instance=s.instance)
        new_key = self.page(s2).config['docConfig']['document']['key']
        self.assertNotEqual(new_key, old_key)
        # And the document URL now serves revision 2.
        url = self.page(s2).config['docConfig']['document']['url']
        resp = self.ds.outbox_get(url)
        self.assertEqual(b''.join(resp.streaming_content), content)

    def test_duplicate_status_2_is_idempotent(self):
        t, s, _ = self.setup_doc()
        sessions.close(s, reason='closed by user', pending_final_save=True)
        content = docx_text('final')
        url = self.ds.put_file(content)
        self.ok(self.ds.callback(self.client, s, 2, url=url, filetype='docx'))
        self.ok(self.ds.callback(self.client, s, 2, url=url, filetype='docx'))
        self.assertEqual(storage.current(t).revision_number, 2)
        self.assertFalse(QuarantinedSave.objects.exists())

    def test_status_2_waits_for_spent_key_even_if_open_session_rejoins(self):
        """A session still open on the spent key gets a new key on reload."""
        t, s1, _ = self.setup_doc()
        s2 = sessions.open_session(t.refresh(), self.owner, mode='edit', instance=s1.instance)
        self.page(s2)
        k = self.key(s1)
        self.ok(self.ds.callback(self.client, s1, 2, data=docx_text('x')))
        self.assertNotEqual(self.page(s2).config['docConfig']['document']['key'], k)

    def test_status_6_forcesave_keeps_session_and_key(self):
        t, s, _ = self.setup_doc()
        key = self.key(s)
        self.ok(self.ds.callback(self.client, s, 6, data=docx_text('one'), forcesavetype=1))
        self.ok(self.ds.callback(self.client, s, 6, data=docx_text('two'), forcesavetype=0))
        s.refresh_from_db()
        self.assertEqual(s.state, 'open')
        self.assertEqual(self.key(s), key)
        self.assertEqual(storage.current(t).revision_number, 3)
        # A new co-editor joins the same group and key after force-saves.
        s2 = sessions.open_session(t.refresh(), self.owner, mode='edit', instance=s.instance)
        self.assertEqual(self.page(s2).config['docConfig']['document']['key'], key)
        # Final save builds on the force-saves.
        sessions.close(s, reason='closed by user', pending_final_save=True)
        sessions.close(s2, reason='closed by user', pending_final_save=True)
        self.ok(self.ds.callback(self.client, s2, 2, data=docx_text('three')))
        self.assertEqual(storage.current(t).revision_number, 4)
        self.assertEqual(EditSession.objects.get(pk=s.pk).state, 'closed')
        self.assertEqual(EditSession.objects.get(pk=s2.pk).state, 'closed')

    def test_editor_status_reports_saved_revision(self):
        t, s, _ = self.setup_doc()
        self.ok(self.ds.callback(self.client, s, 6, data=docx_text('one')))
        self.client.force_login(self.editor)
        data = self.client.get(reverse('office:editor_status', args=[s.pk])).json()
        self.assertEqual(data['lastSavedRevision'], 2)

    def test_stale_save_is_quarantined_not_overwriting(self):
        t, s, _ = self.setup_doc()
        newer = storage.save_new_revision(t, docx_text('uploaded meanwhile'), user=self.owner,
                                          source='upload')
        self.ok(self.ds.callback(self.client, s, 6, data=docx_text('stale')))
        self.assertEqual(storage.current(t).pk, newer.pk)
        q = QuarantinedSave.objects.get()
        self.assertEqual(q.reason, 'stale')
        self.assertEqual(q.session_id, s.pk)
        self.client.force_login(self.editor)
        status = self.client.get(reverse('office:editor_status', args=[s.pk])).json()
        self.assertEqual(status['lastFailure']['reason'], 'stale')

    def test_revoked_session_is_quarantined(self):
        t, s, _ = self.setup_doc()
        sessions.revoke(s, 'admin action')
        self.ok(self.ds.callback(self.client, s, 6, data=docx_text('late')))
        self.assertEqual(storage.current(t).revision_number, 1)
        self.assertEqual(QuarantinedSave.objects.get().reason, 'revoked')

    def test_lost_permission_is_quarantined(self):
        t, s, _ = self.setup_doc()
        Membership.objects.filter(user=self.editor, organization=self.org).update(role=Role.READONLY)
        self.ok(self.ds.callback(self.client, s, 6, data=docx_text('no longer allowed')))
        self.assertEqual(storage.current(t).revision_number, 1)
        self.assertIn(QuarantinedSave.objects.get().reason, ('permission', 'revoked'))

    def test_non_zip_and_wrong_format_are_quarantined(self):
        t, s, _ = self.setup_doc()
        self.ok(self.ds.callback(self.client, s, 6, data=b'<html>not a document</html>'))
        self.ok(self.ds.callback(self.client, s, 6, url=self.ds.put_file(core.blank('xlsx')),
                                 filetype='docx'))
        self.ok(self.ds.callback(self.client, s, 6, url=self.ds.put_file(core.blank('xlsx')),
                                 filetype='xlsx'))
        self.assertEqual(storage.current(t).revision_number, 1)
        self.assertEqual(list(QuarantinedSave.objects.values_list('reason', flat=True)),
                         ['validation'] * 3)

    def test_oversized_download_is_refused_for_retry(self):
        t, s, _ = self.setup_doc()
        EditorInstance.objects.filter(pk=s.instance_id).update(max_file_mb=1)
        big = b'PK' + os.urandom(1024 * 1024 + 10)
        resp = self.ds.callback(self.client, s, 6, data=big)
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()['error'], 1)
        self.assertEqual(storage.current(t).revision_number, 1)
        self.assertIn('size limit', EditSession.objects.get(pk=s.pk).provider_state['oo_last_error']['message'])

    def test_ssrf_foreign_host_and_metadata_ip_are_never_fetched(self):
        t, s, _ = self.setup_doc()
        for url in ('https://evil.example.com/file.docx', 'http://169.254.169.254/latest/meta-data/',
                    'https://docs.example.com@evil.example.com/x', 'file:///etc/passwd'):
            before = len(self.ds.requests)
            resp = self.ds.callback(self.client, s, 6, url=url)
            self.assertEqual(resp.status_code, 500, url)
            self.assertEqual(len(self.ds.requests), before, url)
        self.assertEqual(storage.current(t).revision_number, 1)

    def test_metadata_ip_refused_even_if_it_is_the_instance_host(self):
        inst = self.make_instance(name='meta', browser_url='http://169.254.169.254/')
        with self.assertRaises(net.DestinationNotAllowed):
            net.check_url('http://169.254.169.254/cache/files/x', inst)

    def test_status_3_and_7_record_a_visible_failure(self):
        t, s, _ = self.setup_doc()
        self.ok(self.ds.callback(self.client, s, 7, data=docx_text('broken'), forcesavetype=0))
        self.assertEqual(EditSession.objects.get(pk=s.pk).state, 'open')
        q = QuarantinedSave.objects.get()
        self.assertEqual(q.reason, 'storage_error')
        self.client.force_login(self.editor)
        data = self.client.get(reverse('office:onlyoffice_status', args=[s.pk])).json()
        self.assertIn('force-saving', data['editorError']['message'])
        self.ok(self.ds.callback(self.client, s, 3))
        data = self.client.get(reverse('office:onlyoffice_status', args=[s.pk])).json()
        self.assertIn('while saving', data['editorError']['message'])
        self.assertEqual(storage.current(t).revision_number, 1)

    def test_status_4_closes_without_a_revision(self):
        t, s, _ = self.setup_doc()
        sessions.close(s, reason='closed by user', pending_final_save=True)
        self.ok(self.ds.callback(self.client, s, 4))
        self.assertEqual(EditSession.objects.get(pk=s.pk).state, 'closed')
        self.assertEqual(storage.current(t).revision_number, 1)

    def test_save_is_attributed_to_the_last_editor_in_the_group(self):
        t, s1, _ = self.setup_doc()
        s2 = sessions.open_session(t.refresh(), self.owner, mode='edit', instance=s1.instance)
        self.page(s2)
        # Docs calls the last joiner's callbackUrl but names the last editor.
        self.ok(self.ds.callback(self.client, s2, 6, data=docx_text('by editor'),
                                 users=[state.oo_user_id(self.editor)]))
        rev = storage.current(t)
        self.assertEqual(rev.created_by, self.editor)
        self.assertEqual(rev.editor_session_id, s1.pk)

    def test_cross_tenant_callback_cannot_write_another_org(self):
        inst = self.make_instance()
        ta, sa, _ = self.setup_doc(instance=inst)
        tb, sb, _ = self.setup_doc(user=self.outsider, org=self.other_org, instance=inst)
        # Org A's key at org B's session URL (and the reverse): refused.
        self.assertEqual(self.ds.callback(self.client, sb, 6, key=self.key(sa),
                                          data=docx_text('A into B')).status_code, 403)
        self.assertEqual(self.ds.callback(self.client, sa, 6, key=self.key(sb),
                                          data=docx_text('B into A')).status_code, 403)
        self.assertEqual(storage.current(ta).revision_number, 1)
        self.assertEqual(storage.current(tb).revision_number, 1)
        # A user of org A named in Docs' users list for org B's session is ignored.
        self.ok(self.ds.callback(self.client, sb, 6, data=docx_text('B'),
                                 users=[state.oo_user_id(self.editor)]))
        self.assertEqual(storage.current(tb).created_by, self.outsider)
        self.assertEqual(storage.current(ta).revision_number, 1)

    def test_token_signed_for_another_instance_is_refused(self):
        other = self.make_instance(name='Other', shared_secret='second-instance-secret-0987')
        t, s, _ = self.setup_doc(instance=EditorInstance.objects.exclude(pk=other.pk).first()
                                 or self.make_instance())
        resp = self.ds.callback(self.client, s, 6, data=docx_text('x'),
                                secret='second-instance-secret-0987')
        self.assertEqual(resp.status_code, 403)

    def test_deleted_file_save_goes_to_quarantine(self):
        t, s, _ = self.setup_doc()
        from docs.models import Document
        Document.objects.filter(pk=t.pk).delete()
        self.ok(self.ds.callback(self.client, s, 6, data=docx_text('orphan')))
        q = QuarantinedSave.objects.get()
        self.assertEqual(q.reason, 'revoked')
        self.assertEqual(q.organization_id, self.org.pk)


# ---------------------------------------------------------------------------
# Document URL, commands, conversion, health, diagnostics, round trip
# ---------------------------------------------------------------------------

class OnlyOfficeServiceTests(OnlyOfficeTestBase):
    def test_document_url_needs_token_and_outbox_jwt(self):
        t, s, page = self.setup_doc()
        url = page.config['docConfig']['document']['url']
        path = urlsplit(url).path + '?' + urlsplit(url).query
        self.assertEqual(self.client.get(path).status_code, 403)                   # no JWT
        bad = outbox_token({'url': url}, secret='wrong-secret-0123456789', operation='download')
        self.assertEqual(self.client.get(path, HTTP_AUTHORIZATION='Bearer ' + bad).status_code, 403)
        cb_tok = outbox_token({'url': url}, operation='callback')
        self.assertEqual(self.client.get(path, HTTP_AUTHORIZATION='Bearer ' + cb_tok).status_code, 403)
        resp = self.ds.outbox_get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(b''.join(resp.streaming_content), core.blank())
        self.assertTrue(AuditLog.objects.filter(extra_data__office_event='download',
                                                extra_data__by='editor').exists())
        # A forged / other session's token is a 404.
        wrong = reverse('office:onlyoffice_file', args=[uuid.uuid4()]) + '?' + urlsplit(url).query
        self.assertEqual(self.client.get(wrong, HTTP_AUTHORIZATION='Bearer ' + outbox_token(
            {}, operation='download')).status_code, 404)
        sessions.revoke(s, 'test')
        self.assertEqual(self.ds.outbox_get(url).status_code, 404)

    def test_forcesave_button_calls_the_command_service(self):
        t, s, _ = self.setup_doc()
        self.client.force_login(self.editor)
        resp = self.client.post(reverse('office:onlyoffice_forcesave', args=[s.pk]))
        self.assertEqual(resp.json(), {'ok': True})
        cmd = self.ds.commands[-1]
        self.assertEqual((cmd['c'], cmd['key'], cmd['userdata']), ('forcesave', self.key(s), str(s.pk)))
        self.assertTrue(cmd['token'])
        self.ds.no_changes = True
        self.assertTrue(self.client.post(reverse('office:onlyoffice_forcesave', args=[s.pk])).json()['noChanges'])
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.post(reverse('office:onlyoffice_forcesave', args=[s.pk])).status_code, 404)

    def test_revocation_drops_the_user_from_the_editor(self):
        t, s, _ = self.setup_doc()
        with self.captureOnCommitCallbacks(execute=True):
            sessions.revoke(s, 'permission lost')
        cmd = self.ds.commands[-1]
        self.assertEqual(cmd['c'], 'drop')
        self.assertEqual(cmd['key'], self.key(s))
        self.assertEqual(cmd['users'], [state.oo_user_id(self.editor)])

    def test_save_as_copy_from_editor_url(self):
        t, s, _ = self.setup_doc()
        self.client.force_login(self.editor)
        url = self.ds.put_file(docx_text('copy'))
        resp = self.client.post(reverse('office:onlyoffice_save_as', args=[s.pk]),
                                {'url': url, 'fileType': 'docx', 'title': 'Plan v2.docx'})
        self.assertTrue(resp.json()['ok'], resp.content)
        self.assertEqual(resp.json()['name'], 'Plan v2.docx')
        resp = self.client.post(reverse('office:onlyoffice_save_as', args=[s.pk]),
                                {'url': 'https://evil.example.com/x.docx', 'fileType': 'docx'})
        self.assertEqual(resp.status_code, 400)

    def test_health_check_detects_version_edition_and_conversion(self):
        inst = self.make_instance(capabilities={})
        result = diagnostics.run_health_check(inst)
        self.assertEqual(result.status, 'ok', result.detail)
        inst.refresh_from_db()
        self.assertEqual(inst.detected_version, '10.0.0.169')
        self.assertEqual(inst.detected_edition, 'Community')
        caps = self.provider.capabilities(inst)
        self.assertTrue(caps.can_edit('docx') and caps.can_edit('xlsx') and caps.can_edit('pptx'))
        self.assertTrue(caps.can_export_pdf('docx'))
        self.assertTrue(caps.can_convert('doc', 'docx'))
        self.assertIsNone(caps.max_file_mb)

    def test_health_check_without_converter_advertises_no_conversion(self):
        self.ds.converter_enabled = False
        inst = self.make_instance(capabilities={})
        result = diagnostics.run_health_check(inst)
        self.assertEqual(result.status, 'ok')
        self.assertFalse(self.provider.capabilities(EditorInstance.objects.get(pk=inst.pk)).export_pdf)

    def test_health_check_degrades_on_old_version_or_bad_secret(self):
        self.ds.version = '9.4.0.1'
        inst = self.make_instance()
        self.assertEqual(self.provider.health_check(inst).status, 'degraded')
        self.ds.version = '10.0.0.169'
        self.ds.secret = 'the-server-has-another-secret'
        result = self.provider.health_check(inst)
        self.assertEqual(result.status, 'degraded')
        self.assertIn('JWT', result.detail)
        self.ds.healthy = False
        self.assertEqual(self.provider.health_check(inst).status, 'down')

    def test_diagnostics(self):
        inst = self.make_instance()
        checks = {c.key: c for c in self.provider.diagnostics(inst)}
        self.assertEqual(checks['oo.healthcheck'].status, 'pass')
        self.assertEqual(checks['oo.jwt'].status, 'pass')
        self.assertEqual(checks['oo.version'].status, 'pass')
        self.assertEqual(checks['oo.default_secret'].status, 'pass')
        self.assertEqual(checks['oo.download'].status, 'pass')
        self.assertEqual(checks['oo.callback'].status, 'not_run')
        self.assertEqual(checks['oo.websocket'].status, 'not_run')
        self.assertEqual(checks['oo.browser'].status, 'not_run')
        # Docs still on the vendor default secret (or not checking tokens).
        self.ds.secret = 'developer-only-not-a-real-secret'
        checks = {c.key: c for c in self.provider.diagnostics(inst)}
        self.assertEqual(checks['oo.default_secret'].status, 'fail')
        self.assertEqual(checks['oo.jwt'].status, 'fail')

    def test_diagnostics_use_callback_and_browser_evidence(self):
        t, s, _ = self.setup_doc()
        self.ds.callback(self.client, s, 1, users=[state.oo_user_id(self.editor)])
        self.client.force_login(self.su)
        resp = self.client.get(reverse('office:onlyoffice_browser_probe', args=[s.instance_id]))
        self.assertEqual(resp.status_code, 200)
        csp = resp.get('Content-Security-Policy') or resp.get('Content-Security-Policy-Report-Only')
        self.assertIn(DS, csp)
        self.client.post(reverse('office:onlyoffice_browser_probe_result', args=[s.instance_id]),
                         {'outcome': 'loaded', 'version': '10.0.0'})
        checks = {c.key: c for c in self.provider.diagnostics(s.instance)}
        self.assertEqual(checks['oo.callback'].status, 'pass')
        self.assertEqual(checks['oo.browser'].status, 'pass')
        self.assertIn('connected users', checks['oo.websocket'].detail)
        self.client.force_login(self.editor)
        self.assertEqual(self.client.get(
            reverse('office:onlyoffice_browser_probe', args=[s.instance_id])).status_code, 302)

    def test_round_trip_against_the_fake_server(self):
        inst = self.make_instance()
        report = diagnostics.run_round_trip(inst, self.su)
        steps = {st.key: st.status for st in report.steps}
        self.assertEqual(steps['create'], 'pass')
        self.assertEqual(steps['session'], 'pass')
        self.assertEqual(steps['open'], 'pass', report.steps)
        self.assertEqual(steps['edit'], 'pass')
        self.assertEqual(steps['save'], 'pass')
        self.assertEqual(steps['reopen'], 'pass')
        self.assertEqual(steps['callback'], 'not_run')
        self.assertEqual(steps['cleanup'], 'pass')
        self.assertFalse(report.passed)   # the callback step is honestly not run

    def test_convert_pdf_and_legacy(self):
        inst = self.make_instance()
        t = targets.target_for(self.make_doc())
        rev = storage.ensure_current(t)
        pdf = self.provider.convert(inst, rev, 'pdf')
        self.assertTrue(pdf.startswith(b'%PDF-'))
        from office.providers import NotSupported
        with self.assertRaises(NotSupported):
            self.provider.convert(inst, rev, 'xlsx')

    def test_signed_source_link_expires_and_needs_jwt(self):
        inst = self.make_instance()
        from office.providers.onlyoffice.views import source_link
        url = source_link(inst, probe_ext='docx')
        path = urlsplit(url).path
        self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(self.ds.outbox_get(url).status_code, 200)
        self.assertEqual(self.client.get(path[:-5] + 'xx/', HTTP_AUTHORIZATION='Bearer ' + outbox_token(
            {}, operation='download')).status_code, 404)
        with mock.patch('django.core.signing.time.time', return_value=time.time() + 3600):
            self.assertEqual(self.ds.outbox_get(url).status_code, 404)


class OnlyOfficeSigningTests(core.OfficeTestBase):
    def test_inbox_request_shape(self):
        headers, body = signing.inbox_request({'c': 'version'}, SECRET, 'command')
        claims = jwt.decode(headers['Authorization'][7:], SECRET, algorithms=['HS256'])
        self.assertEqual(claims['payload'], {'c': 'version'})
        self.assertEqual(claims['operation'], 'command')
        self.assertEqual(jwt.decode(body['token'], SECRET, algorithms=['HS256'])['c'], 'version')

    def test_decode_rejects(self):
        good = outbox_token({'key': 'k'})
        self.assertEqual(signing.decode(good, SECRET, operation='callback')['payload'], {'key': 'k'})
        for token, reason in ((outbox_token({'k': 1}, alg='none'), 'algorithm'),
                              (outbox_token({'k': 1}, alg='HS384'), 'algorithm'),
                              (outbox_token({'k': 1}, secret='x' * 20), 'signature'),
                              (outbox_token({'k': 1}, exp_delta=-100), 'expired'),
                              ('not.a.jwt', 'malformed'), ('', 'missing')):
            with self.assertRaises(signing.InvalidToken) as cm:
                signing.decode(token, SECRET, operation='callback')
            self.assertEqual(cm.exception.reason, reason)
        with self.assertRaises(signing.InvalidToken):
            signing.decode(outbox_token({'k': 1}, operation='download'), SECRET, operation='callback')


# ---------------------------------------------------------------------------
# Real Document Server (opt-in; NOT run unless the variables are set)
# ---------------------------------------------------------------------------

E2E_URL = os.environ.get('OFFICE_E2E_ONLYOFFICE_URL', '')
E2E_SECRET = os.environ.get('OFFICE_E2E_ONLYOFFICE_SECRET', '')
E2E_CALLBACK = os.environ.get('OFFICE_E2E_CALLBACK_BASE', '')


@skipUnless(E2E_URL and E2E_SECRET,
            'Real ONLYOFFICE tests: set OFFICE_E2E_ONLYOFFICE_URL, OFFICE_E2E_ONLYOFFICE_SECRET '
            'and OFFICE_E2E_CALLBACK_BASE')
@override_settings(MIDDLEWARE=core.TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=['*'])
class OnlyOfficeRealServiceTests(LiveServerTestCase):
    """SPEC §9 checklist against a real Document Server.

    The server-driven parts run here: health/version/JWT/default-secret,
    Docs downloading from clientst0r through the session URL, Docs-produced
    DOCX/XLSX/PPTX revisions stored and reopened, PDF export, revoked and
    expired tokens refused when Docs fetches, tenant isolation, SSRF.
    Parts that need a person in a browser (typing in the editor, two-user
    co-editing, the save callback after closing, outage and recovery of a
    live session) are listed in docs/office/ONLYOFFICE.md as a manual
    checklist; ``test_browser_checklist`` reports them as skipped.
    """
    host = os.environ.get('OFFICE_E2E_BIND', '0.0.0.0')
    port = int(os.environ.get('OFFICE_E2E_PORT', '0') or 0)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import tempfile
        cls._media = tempfile.mkdtemp(prefix='office-e2e-media-')
        cls._media_override = override_settings(MEDIA_ROOT=cls._media)
        cls._media_override.enable()

    @classmethod
    def tearDownClass(cls):
        import shutil
        cls._media_override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        from core.models import Organization
        self.org = Organization.objects.create(name='E2E A', slug='e2e-a')
        self.other_org = Organization.objects.create(name='E2E B', slug='e2e-b')
        self.su = User.objects.create_superuser('e2e-su', 'e2e@example.com', 'x')
        self.editor = User.objects.create_user('e2e-editor', 'ed@example.com', 'x')
        Membership.objects.create(user=self.editor, organization=self.org, role=Role.EDITOR,
                                  is_active=True)
        self.instance = EditorInstance.objects.create(
            provider='onlyoffice', name='E2E Docs',
            mode=os.environ.get('OFFICE_E2E_MODE', 'separate_server'),
            browser_url=E2E_URL, internal_url=os.environ.get('OFFICE_E2E_ONLYOFFICE_INTERNAL_URL', ''),
            callback_base_url=E2E_CALLBACK or self.live_server_url,
            shared_secret=E2E_SECRET, ca_bundle=os.environ.get('OFFICE_E2E_CA_BUNDLE_PEM', ''),
            enabled=True)
        cfg = OfficeSettings.get()
        cfg.enabled_providers = ['onlyoffice']
        cfg.save()
        self.provider = get_provider('onlyoffice')

    def _doc(self, fmt, org=None):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from docs.models import Document
        data = core.blank(fmt)
        doc = Document.objects.create(
            organization=org or self.org, title=f'E2E {fmt}', slug=f'e2e-{fmt}-{uuid.uuid4().hex[:6]}',
            content_type='file', file=SimpleUploadedFile(f'e2e.{fmt}', data), file_size=len(data),
            created_by=self.su)
        return targets.target_for(doc)

    def test_health_version_and_diagnostics(self):
        result = diagnostics.run_health_check(self.instance)
        self.assertEqual(result.status, 'ok', result.detail)
        self.assertGreaterEqual(client.version_tuple(result.version), (10, 0, 0))
        checks = {c.key: c.status for c in self.provider.diagnostics(
            EditorInstance.objects.get(pk=self.instance.pk))}
        for key in ('oo.healthcheck', 'oo.jwt', 'oo.version', 'oo.default_secret', 'oo.download'):
            self.assertEqual(checks[key], 'pass', key)

    def test_round_trip(self):
        diagnostics.run_health_check(self.instance)
        report = diagnostics.run_round_trip(EditorInstance.objects.get(pk=self.instance.pk), self.su)
        steps = {s.key: s for s in report.steps}
        for key in ('create', 'session', 'open', 'edit', 'save', 'reopen', 'cleanup'):
            self.assertEqual(steps[key].status, 'pass', f'{key}: {steps[key].detail}')

    def test_each_format_saved_from_docs_and_reopened(self):
        diagnostics.run_health_check(self.instance)
        inst = EditorInstance.objects.get(pk=self.instance.pk)
        for fmt in ('docx', 'xlsx', 'pptx'):
            with self.subTest(fmt=fmt):
                t = self._doc(fmt)
                s = sessions.open_session(t, self.editor, mode='edit', instance=inst)
                state.editor_key(s)
                raw = tokens.issue(s, ops=['read'])
                url = (inst.callback_base_url.rstrip('/')
                       + reverse('office:onlyoffice_file', args=[s.pk]) + '?access_token=' + raw)
                answer = client.convert(inst, url=url, filetype=fmt, outputtype=fmt, title=t.filename)
                data = client.download(inst, answer['fileUrl'], storage.max_bytes(inst))
                outcome = cb.persist(EditSession.objects.get(pk=s.pk), data, status=6, filetype=fmt)
                self.assertTrue(outcome and outcome.ok)
                rev = storage.current(t)
                self.assertEqual(rev.revision_number, 2)
                with storage.open_revision(rev) as fh:
                    self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), hashlib.sha256(data).hexdigest())
                pdf = self.provider.convert(inst, rev, 'pdf')
                self.assertTrue(pdf.startswith(b'%PDF-'))

    def test_revoked_and_expired_tokens_are_refused_to_docs(self):
        diagnostics.run_health_check(self.instance)
        inst = EditorInstance.objects.get(pk=self.instance.pk)
        t = self._doc('docx')
        s = sessions.open_session(t, self.editor, mode='edit', instance=inst)
        raw = tokens.issue(s, ops=['read'])
        url = inst.callback_base_url.rstrip('/') + reverse('office:onlyoffice_file', args=[s.pk]) \
            + '?access_token=' + raw
        tokens.revoke(raw)
        with self.assertRaises(client.DocsError) as cm:
            client.convert(inst, url=url, filetype='docx', outputtype='pdf', title='x.docx')
        self.assertEqual(cm.exception.code, -4)

    def test_ssrf_and_tenant_isolation(self):
        with self.assertRaises(net.DestinationNotAllowed):
            client.download(self.instance, 'http://169.254.169.254/latest/meta-data/', 1024)
        with self.assertRaises(net.DestinationNotAllowed):
            client.download(self.instance, 'https://example.org/file.docx', 1024)

    def test_browser_checklist(self):
        self.skipTest('Needs a person in a browser: open/edit/save/close, two-user co-editing, '
                      'read-only view, Save now, restore while open, outage + recovery. '
                      'See docs/office/ONLYOFFICE.md "Manual browser checklist".')
