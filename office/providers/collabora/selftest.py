"""In-process WOPI host self-test for the diagnostics round trip.

Sends the requests Collabora would send — CheckFileInfo, LOCK, GetFile,
PutFile, CheckFileInfo, GetFile, UNLOCK — to clientst0r's own WOPI views,
in this process, with a real access token for the disposable round-trip
session. It proves the host side (tokens, locks, timestamps, validation,
durable storage) end to end. It does NOT prove that Collabora can reach the
WOPI endpoint over the network; the report says so.

The requests are built with Django's RequestFactory and carry a private
attribute that skips proof-key verification (they are not signed by
Collabora). The attribute cannot be set by anything arriving over HTTP.
"""
from __future__ import annotations

import hashlib
import json

from django.test import RequestFactory
from django.urls import reverse

from ... import storage, tokens
from ..base import FAIL, PASS

LABEL = ' (in-process, clientst0r WOPI host)'


def _req(factory, method, path, raw, *, body=None, headers=None):
    meta = {f'HTTP_{k.upper().replace("-", "_")}': v for k, v in (headers or {}).items()}
    url = f'{path}?access_token={raw}'
    if method == 'GET':
        request = factory.get(url, **meta)
    else:
        request = factory.post(url, data=body or b'', content_type='application/octet-stream',
                               **meta)
    request._office_wopi_selftest = True
    return request


def run(instance, session, report, new_bytes, source):
    from . import wopi
    from ...targets import target_of
    factory = RequestFactory()
    raw = tokens.issue(session, ['read', 'write', 'lock'], purpose='wopi-selftest')
    fid = session.document_key
    file_url = reverse('office:collabora_wopi_file', args=[fid])
    contents_url = reverse('office:collabora_wopi_contents', args=[fid])
    lock_id = 'clientst0r-round-trip-' + fid[:8]
    target = target_of(session)

    def step(key, label, ok, detail):
        report.step(key, label + LABEL, PASS if ok else FAIL, detail)
        return ok

    try:
        r = wopi.wopi_file(_req(factory, 'GET', file_url, raw), fid)
        info = json.loads(r.content) if r.status_code == 200 else {}
        ok = (r.status_code == 200 and info.get('UserFriendlyName')
              and str(info.get('LastModifiedTime', '')).endswith('Z') and info.get('UserCanWrite'))
        if not step('wopi_checkfileinfo', 'CheckFileInfo', bool(ok),
                    f'HTTP {r.status_code}, Version {info.get("Version")}, '
                    f'UserCanWrite {info.get("UserCanWrite")}'):
            return
        r = wopi.wopi_file(_req(factory, 'POST', file_url, raw,
                                headers={'X-WOPI-Override': 'LOCK', 'X-WOPI-Lock': lock_id}), fid)
        if not step('wopi_lock', 'LOCK', r.status_code == 200, f'HTTP {r.status_code}'):
            return
        r = wopi.wopi_contents(_req(factory, 'GET', contents_url, raw), fid)
        got = b''.join(r.streaming_content) if r.status_code == 200 else b''
        cur = storage.current(target)
        if not step('wopi_getfile', 'GetFile', r.status_code == 200 and
                    hashlib.sha256(got).hexdigest() == cur.sha256,
                    f'HTTP {r.status_code}, {len(got)} bytes'):
            return
        r = wopi.wopi_contents(_req(factory, 'POST', contents_url, raw, body=new_bytes, headers={
            'X-WOPI-Override': 'PUT', 'X-WOPI-Lock': lock_id,
            'X-COOL-WOPI-Timestamp': info['LastModifiedTime'],
            'X-COOL-WOPI-IsModifiedByUser': 'true'}), fid)
        new = storage.current(target)
        if not step('wopi_putfile', f'PutFile ({source})',
                    r.status_code == 200 and new.revision_number == cur.revision_number + 1,
                    f'HTTP {r.status_code}, now revision {new.revision_number}'):
            return
        r = wopi.wopi_file(_req(factory, 'GET', file_url, raw), fid)
        info2 = json.loads(r.content) if r.status_code == 200 else {}
        step('wopi_reopen', 'CheckFileInfo after save (Version changed)',
             r.status_code == 200 and info2.get('Version') != info.get('Version'),
             f'Version {info.get("Version")} -> {info2.get("Version")}')
        r = wopi.wopi_contents(_req(factory, 'GET', contents_url, raw), fid)
        got = b''.join(r.streaming_content) if r.status_code == 200 else b''
        step('wopi_compare', 'GetFile returns the saved bytes',
             hashlib.sha256(got).hexdigest() == hashlib.sha256(new_bytes).hexdigest(),
             f'sha256 {hashlib.sha256(got).hexdigest()[:12]}…')
        r = wopi.wopi_file(_req(factory, 'POST', file_url, raw,
                                headers={'X-WOPI-Override': 'UNLOCK', 'X-WOPI-Lock': lock_id}), fid)
        step('wopi_unlock', 'UNLOCK', r.status_code == 200, f'HTTP {r.status_code}')
    finally:
        tokens.revoke(raw)
