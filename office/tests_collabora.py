"""Collabora Online connector: discovery, WOPI host, proof keys, locks,
editor page, diagnostics, round trip.

No real Collabora runs here. ``FakeCollaboraServer`` is a local HTTP server
answering /hosting/discovery, /hosting/capabilities, /cool/convert-to/<fmt>
and the WebSocket upgrade the way Collabora 26.04 does (shapes taken from its
source tree), and ``FakeCollaboraClient`` sends WOPI requests the way coolwsd
does: access_token in the query string, X-WOPI-Proof signed with the key the
fake server publishes, X-COOL-WOPI-Timestamp echoing the last
LastModifiedTime, LOCK/UNLOCK with one lock id, re-LOCK as refresh. These
prove the host side; they do not prove the real editor works.
``CollaboraRealServiceTests`` does that and is skipped unless
OFFICE_E2E_COLLABORA_URL is set; it has NOT been run.
"""
import base64
import hashlib
import http.server
import io
import json
import logging
import os
import re
import threading
import unittest
from datetime import timedelta
from unittest import mock
from urllib.parse import parse_qs, quote, unquote, urlsplit

from cryptography.hazmat.primitives.asymmetric import rsa
from django.core.cache import cache
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role
from docs.models import Document

from . import diagnostics, sessions, storage, targets, tokens
from .models import (AccessToken, EditorInstance, EditSession, FileRevision, OfficeSettings,
                     QuarantinedSave, WopiLock)
from .providers import FAIL, NOT_RUN, PASS, WARN, NotSupported, get_provider
from .providers.collabora import discovery as disco
from .providers.collabora import locks, options, proof
from .providers.collabora.wopi import iso_z, same_time
from .tests import TEST_MIDDLEWARE, OfficeTestBase, blank, docx_with_text

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OLD_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
CALLBACK = 'https://app.example.com'
ISO_Z = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$')


# ---------------------------------------------------------------------------
# Protocol-accurate fake Collabora server
# ---------------------------------------------------------------------------

class FakeState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.product = 'Collabora Online Development Edition'
        self.version = '26.04.6.1'
        self.proof_key = KEY
        self.old_key = OLD_KEY
        self.convert = True
        self.host = None          # host Collabora writes into urlsrc (None = as asked)
        self.ws_status = 101
        self.hits = []
        self.convert_out = None


STATE = FakeState()


def discovery_xml(host_origin):
    def actions(ext, names):
        return ''.join(f'<action name="{n}" ext="{ext}" '
                       f'urlsrc="{host_origin}/browser/0123abcd/cool.html?"/>' for n in names)
    pk = ''
    if STATE.proof_key is not None:
        n, e = proof.public_numbers_b64(STATE.proof_key)
        on, oe = proof.public_numbers_b64(STATE.old_key or STATE.proof_key)
        pk = f'<proof-key value="unused" modulus="{n}" exponent="{e}" oldvalue="unused" ' \
             f'oldmodulus="{on}" oldexponent="{oe}"/>'
    return (f'<?xml version="1.0" encoding="utf-8"?><wopi-discovery><net-zone name="external-http">'
            f'<app name="writer">{actions("docx", ["view", "edit"])}{actions("doc", ["view", "edit"])}'
            f'{actions("docm", ["view"])}</app>'
            f'<app name="calc">{actions("xlsx", ["view", "edit"])}{actions("xls", ["view", "edit"])}</app>'
            f'<app name="impress">{actions("pptx", ["view", "edit"])}</app>'
            f'<app name="Capabilities"><action name="getinfo" ext="" '
            f'urlsrc="{host_origin}/hosting/capabilities"/></app>'
            f'</net-zone>{pk}</wopi-discovery>').encode()


class FakeCollaboraHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def _send(self, status, body=b'', ctype='application/octet-stream', headers=None):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        STATE.hits.append(('GET', self.path))
        origin = STATE.host or f'http://{self.headers.get("Host")}'
        if self.path == '/hosting/discovery':
            return self._send(200, discovery_xml(origin), 'text/xml')
        if self.path == '/hosting/capabilities':
            body = json.dumps({'productName': STATE.product, 'productVersion': STATE.version,
                               'productVersionHash': 'abc123', 'hasWopiAccessCheck': True,
                               'convert-to': {'available': STATE.convert,
                                              'endpoint': '/cool/convert-to'}}).encode()
            return self._send(200, body, 'application/json')
        if self.path.startswith('/cool/') and self.path.endswith('/ws'):
            if STATE.ws_status == 101 and self.headers.get('Upgrade', '').lower() == 'websocket':
                accept = base64.b64encode(hashlib.sha1(
                    (self.headers['Sec-WebSocket-Key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11')
                    .encode()).digest()).decode()
                self.send_response(101)
                self.send_header('Upgrade', 'websocket')
                self.send_header('Connection', 'Upgrade')
                self.send_header('Sec-WebSocket-Accept', accept)
                self.end_headers()
                self.close_connection = True
                return
            return self._send(400, b'no upgrade')
        return self._send(404)

    def do_POST(self):
        STATE.hits.append(('POST', self.path))
        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(length)
        m = re.match(r'^/cool/convert-to/(\w+)$', self.path)
        if m and STATE.convert:
            if b'name="data"' not in body:
                return self._send(400, b'no data field')
            fmt = m.group(1)
            if fmt == 'pdf':
                return self._send(200, b'%PDF-1.7\n% fake collabora\n')
            return self._send(200, STATE.convert_out or docx_with_text('re-saved by fake'))
        return self._send(404)

    def log_message(self, *args):
        pass


class FakeCollaboraClient:
    """Sends WOPI requests to clientst0r the way coolwsd does."""

    def __init__(self, test_client, file_id, token, *, key=KEY, base=CALLBACK, lock_id=None):
        self.c = test_client
        self.file_id = file_id
        self.token = token
        self.key = key
        self.base = base
        self.lock_id = lock_id or 'cool-lock-' + file_id[:10]
        self.last_modified = None

    def path(self, contents=False):
        p = reverse('office:collabora_wopi_contents' if contents else 'office:collabora_wopi_file',
                    args=[self.file_id])
        return f'{p}?access_token={self.token}'

    def _sign(self, path, ticks=None):
        if self.key is None:
            return {}
        ticks = ticks or proof.ticks_from_datetime(timezone.now())
        sig = proof.sign(self.key, self.token, self.base + path, ticks)
        return {'HTTP_X_WOPI_TIMESTAMP': str(ticks), 'HTTP_X_WOPI_PROOF': sig,
                'HTTP_X_WOPI_PROOFOLD': sig}   # 26.04: ProofOld is a copy of Proof

    def get(self, contents=False, **meta):
        p = self.path(contents)
        return self.c.get(p, **{**self._sign(p), **meta})

    def post(self, override, contents=False, body=b'', **meta):
        p = self.path(contents)
        meta = {**self._sign(p), 'HTTP_X_WOPI_OVERRIDE': override, **meta}
        return self.c.post(p, data=body, content_type='application/octet-stream', **meta)

    def check_file_info(self):
        r = self.get()
        if r.status_code == 200:
            self.last_modified = r.json()['LastModifiedTime']
        return r

    def lock(self, lock_id=None):
        return self.post('LOCK', HTTP_X_WOPI_LOCK=lock_id or self.lock_id)

    def unlock(self, lock_id=None):
        return self.post('UNLOCK', HTTP_X_WOPI_LOCK=lock_id or self.lock_id)

    def get_file(self, **meta):
        return self.get(contents=True, **meta)

    def put_file(self, data, *, autosave=False, exit_save=False, forced=False, lock_id=None,
                 timestamp=None):
        meta = {'HTTP_X_WOPI_LOCK': lock_id or self.lock_id,
                'HTTP_X_COOL_WOPI_ISMODIFIEDBYUSER': 'true',
                'HTTP_X_COOL_WOPI_ISAUTOSAVE': 'true' if autosave else 'false',
                'HTTP_X_COOL_WOPI_ISEXITSAVE': 'true' if exit_save else 'false'}
        if not forced:
            meta['HTTP_X_COOL_WOPI_TIMESTAMP'] = timestamp or self.last_modified
        r = self.post('PUT', contents=True, body=data, **meta)
        if r.status_code == 200:
            self.last_modified = r.json()['LastModifiedTime']
        return r


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CollaboraBase(OfficeTestBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), FakeCollaboraHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        STATE.reset()
        cache.clear()
        self.inst = self.make_instance(
            provider='collabora', name='Collabora', mode='same_server',
            browser_url=f'http://127.0.0.1:{self.port}/', callback_base_url=CALLBACK + '/')
        cfg = OfficeSettings.get()
        cfg.default_instance = self.inst
        cfg.save()
        result = diagnostics.run_health_check(self.inst)
        self.assertEqual(result.status, 'ok', result.detail)
        self.inst.refresh_from_db()
        self.provider = get_provider('collabora')

    def open(self, user=None, mode='edit', target=None):
        target = target or self.target()
        session = sessions.open_session(target, user or self.editor, mode=mode, instance=self.inst)
        ops = ['read', 'write', 'lock', 'rename'] if mode == 'edit' else ['read']
        raw = tokens.issue(session, ops, purpose='wopi')
        return target, session, raw

    def wopi(self, session, raw, **kw):
        return FakeCollaboraClient(self.client, session.document_key, raw, **kw)


# ---------------------------------------------------------------------------
# Discovery, capabilities, health
# ---------------------------------------------------------------------------

class DiscoveryTests(CollaboraBase):
    def test_parses_actions_proof_key_and_caches(self):
        disc = disco.get_discovery(self.inst)
        self.assertTrue(disc.urlsrc('docx', 'edit').startswith(f'http://127.0.0.1:{self.port}/browser/'))
        self.assertTrue(disc.has('docm', 'view'))
        self.assertFalse(disc.has('docm', 'edit'))
        self.assertTrue(disc.proof_key.present)
        n = len([h for h in STATE.hits if h[1] == '/hosting/discovery'])
        disco.get_discovery(self.inst)
        self.assertEqual(len([h for h in STATE.hits if h[1] == '/hosting/discovery']), n)

    def test_urlsrc_naming_another_host_is_mapped_to_browser_origin(self):
        STATE.host = 'http://localhost:9980'
        disc = disco.get_discovery(self.inst, refresh=True)
        self.assertTrue(disc.rewritten)
        self.assertEqual(urlsplit(disc.urlsrc('xlsx', 'edit')).netloc, f'127.0.0.1:{self.port}')

    def test_bad_discovery_is_an_error(self):
        with self.assertRaises(disco.DiscoveryError):
            disco.parse_discovery(b'<html>nope</html>', self.inst)
        with self.assertRaises(disco.DiscoveryError):
            disco.parse_discovery(b'<!DOCTYPE x [<!ENTITY a "b">]><wopi-discovery/>', self.inst)

    def test_health_detects_code_and_capabilities(self):
        self.assertIn('Evaluation / development only', self.inst.detected_edition)
        self.assertEqual(self.inst.detected_version, '26.04.6.1')
        caps = self.provider.capabilities(self.inst)
        self.assertEqual(caps.edit_formats, {'docx', 'xlsx', 'pptx'})
        self.assertTrue(caps.can_view('docm'))
        self.assertTrue(caps.can_export_pdf('docx'))
        self.assertTrue(caps.can_convert('doc', 'docx'))
        self.assertTrue(caps.coauthoring)

    def test_licensed_product_and_no_convert(self):
        STATE.product = 'Collabora Online'
        STATE.convert = False
        diagnostics.run_health_check(self.inst)
        self.inst.refresh_from_db()
        self.assertEqual(self.inst.detected_edition, 'Collabora Online')
        caps = self.provider.capabilities(self.inst)
        self.assertFalse(caps.export_pdf)
        self.assertFalse(caps.can_convert('doc', 'docx'))

    def test_unreachable_is_down(self):
        self.inst.browser_url = 'http://127.0.0.1:1/'
        self.inst.save()
        cache.clear()
        self.assertEqual(diagnostics.run_health_check(self.inst).status, 'down')


# ---------------------------------------------------------------------------
# Proof keys
# ---------------------------------------------------------------------------

class ProofTests(CollaboraBase):
    def test_verify_current_old_and_age(self):
        pk = disco.get_discovery(self.inst).proof_key
        url = CALLBACK + '/office/api/wopi/files/abc?access_token=tok'
        ticks = proof.ticks_from_datetime(timezone.now())
        good = proof.sign(KEY, 'tok', url, ticks)
        self.assertTrue(proof.verify(pk, access_token='tok', urls=[url], timestamp=ticks,
                                     proof=good, proof_old=''))
        # Lower/upper case of the URL does not matter (the URL is upper-cased).
        self.assertTrue(proof.verify(pk, access_token='tok', urls=[url.lower()], timestamp=ticks,
                                     proof=good, proof_old=''))
        old_sig = proof.sign(OLD_KEY, 'tok', url, ticks)
        self.assertTrue(proof.verify(pk, access_token='tok', urls=[url], timestamp=ticks,
                                     proof=old_sig, proof_old='junk'))
        with self.assertRaises(proof.ProofError):
            proof.verify(pk, access_token='other', urls=[url], timestamp=ticks, proof=good,
                         proof_old=good)
        stale = proof.ticks_from_datetime(timezone.now() - timedelta(minutes=21))
        with self.assertRaises(proof.ProofError):
            proof.verify(pk, access_token='tok', urls=[url], timestamp=stale,
                         proof=proof.sign(KEY, 'tok', url, stale), proof_old='')
        self.assertLess(abs((proof.datetime_from_ticks(ticks) - timezone.now()).total_seconds()), 5)
        # Ticks of the Unix epoch, per .NET.
        from datetime import datetime, timezone as tz
        self.assertEqual(proof.ticks_from_datetime(datetime(1970, 1, 1, tzinfo=tz.utc)),
                         621355968000000000)

    def test_wopi_requires_valid_proof_when_key_published(self):
        _t, s, raw = self.open()
        self.assertEqual(self.wopi(s, raw).check_file_info().status_code, 200)
        self.assertEqual(self.wopi(s, raw, key=None).check_file_info().status_code, 500)
        forged = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.assertEqual(self.wopi(s, raw, key=forged).check_file_info().status_code, 500)
        c = self.wopi(s, raw)
        p = c.path()
        old = proof.ticks_from_datetime(timezone.now() - timedelta(minutes=25))
        r = self.client.get(p, **c._sign(p, ticks=old))
        self.assertEqual(r.status_code, 500)

    def test_require_proof_off_and_no_key(self):
        _t, s, raw = self.open()
        options.set_options(self.inst, require_proof=False)
        self.assertEqual(self.wopi(s, raw, key=None).check_file_info().status_code, 200)
        options.set_options(self.inst, require_proof=True)
        STATE.proof_key = None
        cache.clear()
        self.assertEqual(self.wopi(s, raw, key=None).check_file_info().status_code, 200)

    def test_rotated_key_triggers_one_discovery_refresh(self):
        _t, s, raw = self.open()
        disco.get_discovery(self.inst)
        key = disco._cache_key(self.inst)
        data = cache.get(key)
        data['fetched_at'] -= 3600
        cache.set(key, data)
        new = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        STATE.proof_key = new
        self.assertEqual(self.wopi(s, raw, key=new).check_file_info().status_code, 200)


# ---------------------------------------------------------------------------
# CheckFileInfo / GetFile
# ---------------------------------------------------------------------------

class CheckFileInfoTests(CollaboraBase):
    def test_fields(self):
        t, s, raw = self.open()
        sessions_state = EditSession.objects.get(pk=s.pk)
        from .providers.collabora.wopi import note
        note(sessions_state, host_origin='https://app.example.com')
        r = self.wopi(s, raw).check_file_info()
        self.assertEqual(r.status_code, 200)
        info = r.json()
        rev = storage.current(t)
        self.assertEqual(info['BaseFileName'], 'Plan.docx')
        self.assertEqual(info['Size'], rev.size)
        self.assertEqual(info['Version'], f'{rev.revision_number}-{rev.sha256[:16]}')
        self.assertRegex(info['LastModifiedTime'], ISO_Z)
        self.assertEqual(info['UserFriendlyName'], 'office-editor')
        self.assertTrue(info['UserCanWrite'])
        self.assertTrue(info['UserCanNotWriteRelative'])
        self.assertTrue(info['SupportsLocks'])
        self.assertTrue(info['SupportsRename'] and info['UserCanRename'])
        self.assertEqual(info['PostMessageOrigin'], 'https://app.example.com')
        self.assertEqual(info['OwnerId'], f'org-{self.org.pk}')
        self.assertFalse(info['DisablePrint'])
        self.assertFalse(info['EnableRemoteAIContent'])
        for k in ('BaseFileName', 'OwnerId', 'Size', 'UserId', 'Version'):
            self.assertIn(k, info)
        self.assertNotIn(raw, r.content.decode())

    def test_view_session_cannot_write_and_policy_flags(self):
        options.set_options(self.inst, disable_print=True, hide_export=True)
        _t, s, raw = self.open(user=self.reader, mode='view')
        info = self.wopi(s, raw).check_file_info().json()
        self.assertFalse(info['UserCanWrite'])
        self.assertFalse(info['UserCanRename'])
        self.assertTrue(info['DisablePrint'] and info['HideExportOption'])

    def test_read_only_format_is_not_writable(self):
        doc = self.make_doc(data=b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1' + b'\0' * 600, ext='doc')
        _t, s, raw = self.open(target=targets.target_for(doc))
        info = self.wopi(s, raw).check_file_info().json()
        self.assertFalse(info['UserCanWrite'])

    def test_get_file_and_limits(self):
        t, s, raw = self.open()
        c = self.wopi(s, raw)
        r = c.get_file()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b''.join(r.streaming_content), blank())
        self.assertEqual(c.get_file(HTTP_X_WOPI_MAXEXPECTEDSIZE='10').status_code, 412)
        with mock.patch('office.storage.max_bytes', return_value=10):
            self.assertEqual(c.get_file().status_code, 413)

    def test_file_id_is_not_a_path(self):
        _t, s, raw = self.open()
        self.assertEqual(self.client.get(f'/office/api/wopi/files/short?access_token={raw}').status_code, 404)
        self.assertEqual(self.client.get(
            f'/office/api/wopi/files/..%2F..%2Fetc%2Fpasswd?access_token={raw}').status_code, 404)
        self.assertEqual(self.client.get(f'/office/api/wopi/files/../../x?access_token={raw}').status_code, 404)


# ---------------------------------------------------------------------------
# Tokens and tenants
# ---------------------------------------------------------------------------

class TokenTests(CollaboraBase):
    def test_missing_unknown_expired_revoked(self):
        _t, s, raw = self.open()
        self.assertEqual(self.wopi(s, '').check_file_info().status_code, 401)
        self.assertEqual(self.wopi(s, 'x' * 43).check_file_info().status_code, 401)
        AccessToken.objects.filter(session=s).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.wopi(s, raw).check_file_info().status_code, 401)
        _t2, s2, raw2 = self.open()
        sessions.revoke(s2, 'test')
        self.assertEqual(self.wopi(s2, raw2).check_file_info().status_code, 401)

    def test_wrong_scope(self):
        t, s, raw = self.open(user=self.reader, mode='view')
        c = self.wopi(s, raw)
        c.check_file_info()
        self.assertEqual(c.lock().status_code, 401)
        r = c.put_file(docx_with_text('sneaky'))
        self.assertEqual(r.status_code, 401)
        self.assertEqual(storage.current(t).revision_number, 1)
        self.assertEqual(c.post('RENAME_FILE', HTTP_X_WOPI_REQUESTEDNAME='x').status_code, 401)

    def test_token_for_another_file_or_tenant(self):
        _t, s, raw = self.open()
        other_doc = self.make_doc(org=self.other_org, title='Theirs')
        _t2, s2, raw2 = self.open(user=self.outsider, target=targets.target_for(other_doc))
        # Org B's token against org A's file id, and vice versa.
        self.assertEqual(FakeCollaboraClient(self.client, s.document_key, raw2).check_file_info().status_code, 401)
        self.assertEqual(FakeCollaboraClient(self.client, s2.document_key, raw).check_file_info().status_code, 401)
        r = FakeCollaboraClient(self.client, s.document_key, raw2).put_file(
            docx_with_text('x'), timestamp='2020-01-01T00:00:00.000000Z')
        self.assertEqual(r.status_code, 401)
        self.assertEqual(QuarantinedSave.objects.filter(organization=self.org).count(), 0)

    def test_permission_lost_is_403_and_quarantined(self):
        t, s, raw = self.open()
        c = self.wopi(s, raw)
        c.check_file_info()
        c.lock()
        Membership.objects.filter(user=self.editor, organization=self.org).update(role=Role.READONLY)
        r = c.put_file(docx_with_text('after demotion'))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(storage.current(t).revision_number, 1)
        q = QuarantinedSave.objects.get(session=s)
        self.assertEqual(q.reason, 'permission')
        self.assertEqual(EditSession.objects.get(pk=s.pk).state, 'revoked')

    def test_revoked_session_put_is_quarantined(self):
        t, s, raw = self.open()
        c = self.wopi(s, raw)
        c.check_file_info()
        sessions.revoke(s, 'admin')
        self.assertEqual(c.put_file(docx_with_text('late')).status_code, 401)
        self.assertEqual(QuarantinedSave.objects.get(session=s).reason, 'revoked')

    def test_renew_endpoint_extends_tokens(self):
        _t, s, raw = self.open()
        AccessToken.objects.filter(session=s).update(expires_at=timezone.now() + timedelta(minutes=1))
        self.client.force_login(self.editor)
        r = self.client.post(reverse('office:collabora_renew', args=[s.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertGreater(AccessToken.objects.get(session=s).expires_at,
                           timezone.now() + timedelta(minutes=30))
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse('office:collabora_renew', args=[s.pk])).status_code, 404)

    def test_renew_needs_csrf(self):
        _t, s, _raw = self.open()
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.editor)
        self.assertEqual(c.post(reverse('office:collabora_renew', args=[s.pk])).status_code, 403)


# ---------------------------------------------------------------------------
# PutFile
# ---------------------------------------------------------------------------

class PutFileTests(CollaboraBase):
    def test_save_creates_revision_after_durable_commit(self):
        t, s, raw = self.open()
        c = self.wopi(s, raw)
        c.check_file_info()
        self.assertEqual(c.lock().status_code, 200)
        r = c.put_file(docx_with_text('hello'), autosave=True)
        self.assertEqual(r.status_code, 200, r.content)
        rev = storage.current(t)
        self.assertEqual(rev.revision_number, 2)
        self.assertEqual(rev.source, 'editor_save')
        self.assertEqual(rev.editor_session_id, s.pk)
        self.assertEqual(r.json()['LastModifiedTime'], iso_z(rev.created_at))
        self.assertEqual(r['X-WOPI-ItemVersion'], f'2-{rev.sha256[:16]}')
        last = EditSession.objects.get(pk=s.pk).provider_state['collabora']['last_put']
        self.assertTrue(last['autosave'])
        self.assertFalse(last['exit_save'])
        # Next save chains on the timestamp the previous reply gave.
        self.assertEqual(c.put_file(docx_with_text('hello again')).status_code, 200)
        self.assertEqual(storage.current(t).revision_number, 3)

    def test_csrf_middleware_does_not_block_wopi(self):
        t, s, raw = self.open()
        c = FakeCollaboraClient(Client(enforce_csrf_checks=True), s.document_key, raw)
        c.check_file_info()
        self.assertEqual(c.lock().status_code, 200)
        self.assertEqual(c.put_file(docx_with_text('csrf')).status_code, 200)

    def test_duplicate_put_is_idempotent(self):
        t, s, raw = self.open()
        c = self.wopi(s, raw)
        c.check_file_info()
        c.lock()
        first_stamp = c.last_modified
        data = docx_with_text('dup')
        self.assertEqual(c.put_file(data).status_code, 200)
        # Retry with the old timestamp (the reply was lost) and with the new one.
        self.assertEqual(c.put_file(data, timestamp=first_stamp).status_code, 200)
        self.assertEqual(c.put_file(data).status_code, 200)
        self.assertEqual(storage.revisions(t).count(), 2)
        self.assertEqual(QuarantinedSave.objects.count(), 0)

    def test_document_changed_in_storage_is_1010_and_quarantined(self):
        t, s, raw = self.open()
        c = self.wopi(s, raw)
        c.check_file_info()
        c.lock()
        storage.save_new_revision(t, docx_with_text('uploaded meanwhile'), user=self.owner,
                                  source='upload')
        r = c.put_file(docx_with_text('editor copy'))
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json(), {'COOLStatusCode': 1010})
        self.assertEqual(storage.current(t).revision_number, 2)
        q = QuarantinedSave.objects.get(session=s)
        self.assertEqual(q.reason, 'stale')
        self.assertEqual(q.sha256, hashlib.sha256(docx_with_text('editor copy')).hexdigest())
        # The user chooses "overwrite": Collabora retries without a timestamp.
        self.assertEqual(c.put_file(docx_with_text('editor copy'), forced=True).status_code, 200)
        self.assertEqual(storage.current(t).revision_number, 3)

    def test_invalid_content_and_too_large(self):
        t, s, raw = self.open()
        c = self.wopi(s, raw)
        c.check_file_info()
        c.lock()
        self.assertEqual(c.put_file(b'this is not a docx').status_code, 400)
        self.assertEqual(QuarantinedSave.objects.get(session=s).reason, 'validation')
        with mock.patch('office.storage.max_bytes', return_value=100):
            self.assertEqual(c.put_file(docx_with_text('big')).status_code, 413)
        self.assertEqual(storage.current(t).revision_number, 1)

    def test_put_relative_and_unknown_override(self):
        _t, s, raw = self.open()
        c = self.wopi(s, raw)
        self.assertEqual(c.post('PUT_RELATIVE').status_code, 501)
        self.assertEqual(c.post('DELETE').status_code, 501)
        self.assertEqual(c.post('').status_code, 400)


# ---------------------------------------------------------------------------
# Locks
# ---------------------------------------------------------------------------

class LockTests(CollaboraBase):
    def two_groups(self):
        t, a, raw_a = self.open()
        _t, b, raw_b = self.open(user=self.owner, target=t)
        EditSession.objects.filter(pk=b.pk).update(document_key='other-group-key-0123456789')
        b.refresh_from_db()
        return t, self.wopi(a, raw_a, lock_id='A-lock'), self.wopi(b, raw_b, lock_id='B-lock'), a, b

    def test_lock_conflict_refresh_unlock(self):
        t, ca, cb, a, b = self.two_groups()
        ca.check_file_info()
        cb.check_file_info()
        self.assertEqual(ca.lock().status_code, 200)
        r = cb.lock()
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r['X-WOPI-Lock'], 'A-lock')
        # Re-LOCK with the same id is a refresh (what Collabora does every 900 s).
        before = WopiLock.objects.get().expires_at
        self.assertEqual(ca.lock().status_code, 200)
        self.assertGreaterEqual(WopiLock.objects.get().expires_at, before)
        self.assertEqual(ca.post('REFRESH_LOCK', HTTP_X_WOPI_LOCK='A-lock').status_code, 200)
        r = ca.post('REFRESH_LOCK', HTTP_X_WOPI_LOCK='nope')
        self.assertEqual((r.status_code, r['X-WOPI-Lock']), (409, 'A-lock'))
        self.assertEqual(ca.post('GET_LOCK')['X-WOPI-Lock'], 'A-lock')
        r = cb.unlock()
        self.assertEqual((r.status_code, r['X-WOPI-Lock']), (409, 'A-lock'))
        # PutFile with the wrong lock: 409 + current lock, body quarantined.
        r = cb.put_file(docx_with_text('B'))
        self.assertEqual((r.status_code, r['X-WOPI-Lock']), (409, 'A-lock'))
        self.assertEqual(QuarantinedSave.objects.get(session=b).reason, 'stale')
        self.assertEqual(ca.unlock().status_code, 200)
        self.assertEqual(ca.post('GET_LOCK')['X-WOPI-Lock'], '')
        self.assertEqual(cb.lock().status_code, 200)

    def test_unlock_and_relock(self):
        _t, ca, _cb, _a, _b = self.two_groups()
        ca.lock()
        r = ca.post('LOCK', HTTP_X_WOPI_LOCK='A2', HTTP_X_WOPI_OLDLOCK='wrong')
        self.assertEqual((r.status_code, r['X-WOPI-Lock']), (409, 'A-lock'))
        self.assertEqual(ca.post('LOCK', HTTP_X_WOPI_LOCK='A2', HTTP_X_WOPI_OLDLOCK='A-lock').status_code, 200)
        self.assertEqual(ca.post('GET_LOCK')['X-WOPI-Lock'], 'A2')

    def test_expired_lock_and_crashed_holder(self):
        _t, ca, cb, a, _b = self.two_groups()
        ca.lock()
        WopiLock.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(cb.lock().status_code, 200)
        cb.unlock()
        ca.lock()
        sessions.revoke(a, 'editor crashed')
        self.assertEqual(cb.lock().status_code, 200)

    def test_put_without_lock_on_nonempty_file(self):
        _t, s, raw = self.open()
        c = self.wopi(s, raw)
        c.check_file_info()
        r = c.put_file(docx_with_text('no lock'))
        self.assertEqual((r.status_code, r['X-WOPI-Lock']), (409, ''))

    def test_lock_id_rules(self):
        t = self.target()
        self.assertFalse(locks.lock(t, 'x' * 1025, None).ok)
        self.assertFalse(locks.lock(t, 'bad\nid', None).ok)
        self.assertTrue(locks.lock(t, 'x' * 1024, None).ok)

    def test_unlock_after_page_closed_ends_session(self):
        _t, s, raw = self.open()
        c = self.wopi(s, raw)
        c.check_file_info()
        c.lock()
        sessions.close(s, pending_final_save=True)
        self.assertEqual(c.put_file(docx_with_text('exit'), exit_save=True).status_code, 200)
        self.assertEqual(c.unlock().status_code, 200)
        self.assertEqual(EditSession.objects.get(pk=s.pk).state, 'closed')


# ---------------------------------------------------------------------------
# RenameFile
# ---------------------------------------------------------------------------

class RenameTests(CollaboraBase):
    def test_rename_utf7_and_lock(self):
        t, s, raw = self.open()
        c = self.wopi(s, raw)
        c.lock()
        name = 'Budget Ü/../2027'.encode('utf-7').decode('ascii')
        r = c.post('RENAME_FILE', HTTP_X_WOPI_REQUESTEDNAME=name, HTTP_X_WOPI_LOCK=c.lock_id)
        self.assertEqual(r.status_code, 200, r.content)
        doc = Document.objects.get(pk=t.pk)
        self.assertNotIn('/', doc.title)
        self.assertEqual(r.json()['Name'], doc.title)
        r = c.post('RENAME_FILE', HTTP_X_WOPI_REQUESTEDNAME='x', HTTP_X_WOPI_LOCK='wrong')
        self.assertEqual(r.status_code, 409)
        r = c.post('RENAME_FILE', HTTP_X_WOPI_REQUESTEDNAME='', HTTP_X_WOPI_LOCK=c.lock_id)
        self.assertEqual(r.status_code, 400)


# ---------------------------------------------------------------------------
# Editor page, diagnostics, round trip, conversion, logging
# ---------------------------------------------------------------------------

class EditorPageTests(CollaboraBase):
    def test_page_posts_token_into_iframe(self):
        t = self.target()
        self.client.force_login(self.editor)
        s = self.client.session
        s['current_organization_id'] = self.org.pk
        s.save()
        r = self.client.post(reverse('office:open', args=[t.code, t.pk]), {'mode': 'edit'})
        self.assertEqual(r.status_code, 302, r.content[:500])
        r = self.client.get(r['Location'])
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        origin = f'http://127.0.0.1:{self.port}'
        form = re.search(r'<form id="([^"]+)"[^>]*action="([^"]+)" target="([^"]+)"', html)
        self.assertIsNotNone(form)
        action = form.group(2).replace('&amp;', '&')
        self.assertTrue(action.startswith(origin + '/browser/'))
        q = parse_qs(urlsplit(action).query)
        session = EditSession.objects.filter(user=self.editor).latest('opened_at')
        self.assertEqual(q['WOPISrc'], [CALLBACK + f'/office/api/wopi/files/{session.document_key}'])
        self.assertNotIn('access_token', action)
        token = re.search(r'name="access_token" value="([^"]+)"', html).group(1)
        tokens.validate(token, op='write', session_id=session.pk)
        self.assertIn(f'name="{form.group(3)}"', html)
        self.assertIn('Evaluation / development only', html)
        self.assertIn('js/office-collabora.js', html)
        csp = r.get('Content-Security-Policy') or r.get('Content-Security-Policy-Report-Only', '')
        frame_src = re.search(r'frame-src ([^;]+)', csp).group(1)
        self.assertIn(origin, frame_src)
        self.assertIn(origin, re.search(r'form-action ([^;]+)', csp).group(1))
        self.assertNotIn(origin, re.search(r'connect-src ([^;]+)', csp).group(1))
        self.assertEqual(r['Cache-Control'], 'no-store')
        st = EditSession.objects.get(pk=session.pk).provider_state['collabora']
        self.assertEqual(st['host_origin'], 'http://testserver')
        self.assertNotIn(token, json.dumps(st))

    def test_event_and_diagnostics(self):
        checks = {c.key: c for c in self.provider.diagnostics(self.inst)}
        self.assertEqual(checks['collabora.discovery'].status, PASS)
        self.assertEqual(checks['collabora.capabilities'].status, WARN)   # CODE
        self.assertIn('evaluation / development only', checks['collabora.capabilities'].remedy)
        self.assertEqual(checks['collabora.proof'].status, PASS)
        self.assertEqual(checks['collabora.websocket'].status, PASS)
        self.assertEqual(checks['collabora.wopi'].status, NOT_RUN)
        self.assertEqual(checks['collabora.browser'].status, NOT_RUN)
        _t, s, raw = self.open()
        self.wopi(s, raw).check_file_info()
        self.client.force_login(self.editor)
        self.assertEqual(self.client.post(reverse('office:collabora_event', args=[s.pk]),
                                          {'event': 'document_loaded'}).status_code, 200)
        checks = {c.key: c for c in self.provider.diagnostics(self.inst)}
        self.assertEqual(checks['collabora.wopi'].status, PASS)
        self.assertIn('verified', checks['collabora.wopi'].detail)
        self.assertEqual(checks['collabora.browser'].status, PASS)

    def test_diagnostics_without_proof_key_or_websocket(self):
        STATE.proof_key = None
        STATE.ws_status = 400
        checks = {c.key: c for c in self.provider.diagnostics(self.inst)}
        self.assertEqual(checks['collabora.proof'].status, WARN)
        self.assertIn('generate-proof-key', checks['collabora.proof'].remedy)
        self.assertEqual(checks['collabora.websocket'].status, WARN)

    def test_round_trip(self):
        report = diagnostics.run_round_trip(self.inst, self.su)
        steps = {s.key: s.status for s in report.steps}
        for key in ('create', 'session', 'discovery', 'convert_pdf', 'resave', 'wopi_checkfileinfo',
                    'wopi_lock', 'wopi_getfile', 'wopi_putfile', 'wopi_reopen', 'wopi_compare',
                    'wopi_unlock'):
            self.assertEqual(steps.get(key), PASS, (key, [(s.key, s.status, s.detail) for s in report.steps]))
        self.assertEqual(steps['browser'], NOT_RUN)
        self.assertFalse(report.passed)   # a browser step could not run
        self.assertTrue(any(h == ('POST', '/cool/convert-to/pdf') for h in STATE.hits))

    def test_convert(self):
        t = self.target()
        rev = storage.ensure_current(t)
        self.assertTrue(self.provider.convert(self.inst, rev, 'pdf').startswith(b'%PDF-'))
        with self.assertRaises(NotSupported):
            self.provider.convert(self.inst, rev, 'xlsx')
        STATE.convert_out = b'garbage'
        doc = self.make_doc(data=b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1' + b'\0' * 600, ext='doc')
        with self.assertRaises(NotSupported):
            self.provider.convert(self.inst, storage.ensure_current(targets.target_for(doc)), 'docx')

    def test_tokens_redacted_from_request_logs(self):
        for name in ('django.request', 'django.server', 'gunicorn.access'):
            with self.assertLogs(name, level='WARNING') as cm:
                logging.getLogger(name).warning('"GET /office/api/wopi/files/x?access_token=%s" 401',
                                                'SECRETTOKEN')
            self.assertNotIn('SECRETTOKEN', ''.join(cm.output))

    def test_iso_and_timestamp_matching(self):
        from datetime import datetime, timezone as tz
        dt = datetime(2026, 11, 11, 10, 0, 0, 123456, tzinfo=tz.utc)
        self.assertEqual(iso_z(dt), '2026-11-11T10:00:00.123456Z')
        self.assertTrue(same_time('2026-11-11T10:00:00.123456Z', dt))
        self.assertTrue(same_time('2026-11-11T10:00:00.123Z', dt))
        self.assertTrue(same_time('2026-11-11T10:00:00.123456000Z', dt))
        self.assertFalse(same_time('2026-11-11T10:00:00.124Z', dt))
        self.assertFalse(same_time('2026-11-11T10:00:01Z', dt))
        self.assertFalse(same_time('garbage', dt))


class CommandTests(CollaboraBase):
    def test_office_collabora_command(self):
        from django.core.management import call_command
        out = io.StringIO()
        call_command('office_collabora', '--instance', str(self.inst.pk), '--require-proof', 'off',
                     stdout=out)
        self.assertIn('require_proof: False', out.getvalue())
        self.inst.refresh_from_db()
        self.assertFalse(options.get(self.inst)['require_proof'])


# ---------------------------------------------------------------------------
# Opt-in real-service suite (SPEC §9). NOT RUN in this repository: no
# Collabora server is available. Set OFFICE_E2E_COLLABORA_URL (https URL of a
# coolwsd that can reach OFFICE_E2E_CALLBACK_URL) to run it.
# ---------------------------------------------------------------------------

E2E_URL = os.environ.get('OFFICE_E2E_COLLABORA_URL', '')


@unittest.skipUnless(E2E_URL, 'NOT RUN: set OFFICE_E2E_COLLABORA_URL to test a real Collabora')
@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CollaboraRealServiceTests(OfficeTestBase):
    """Against a real coolwsd: discovery, capabilities, proof key, WebSocket
    probe, convert-to (pdf and docx re-save) and the WOPI self-test. The
    browser half of SPEC §9 (type/save/reopen DOCX/XLSX/PPTX, two users,
    read-only, outage recovery) needs a browser driver and is listed in
    docs/office/COLLABORA.md as a manual checklist."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.inst = self.make_instance(
            provider='collabora', name='Collabora E2E', mode='separate_server',
            browser_url=E2E_URL, callback_base_url=os.environ.get(
                'OFFICE_E2E_CALLBACK_URL', 'https://clientstor.invalid/'),
            ca_bundle=open(os.environ['OFFICE_E2E_CA_BUNDLE']).read()
            if os.environ.get('OFFICE_E2E_CA_BUNDLE') else '')

    def test_health_diagnostics_round_trip(self):
        result = diagnostics.run_health_check(self.inst)
        self.assertEqual(result.status, 'ok', result.detail)
        self.inst.refresh_from_db()
        checks = {c.key: c for c in get_provider('collabora').diagnostics(self.inst)}
        self.assertEqual(checks['collabora.discovery'].status, PASS)
        self.assertNotEqual(checks['collabora.websocket'].status, FAIL)
        report = diagnostics.run_round_trip(self.inst, self.su)
        steps = {s.key: s.status for s in report.steps}
        for key in ('discovery', 'convert_pdf', 'resave', 'wopi_putfile', 'wopi_compare'):
            self.assertEqual(steps.get(key), PASS, [(s.key, s.status, s.detail) for s in report.steps])

    def test_export_each_format(self):
        diagnostics.run_health_check(self.inst)
        self.inst.refresh_from_db()
        for ext in ('docx', 'xlsx', 'pptx'):
            t = self.target(self.make_doc(title=f'E2E{ext}', ext=ext))
            pdf = get_provider('collabora').convert(self.inst, storage.ensure_current(t), 'pdf')
            self.assertTrue(pdf.startswith(b'%PDF-'))
