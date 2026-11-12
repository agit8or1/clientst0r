"""Collabora Online connector: a WOPI host plus the editor page.

Pieces (see docs/office/COLLABORA.md):

    discovery.py   /hosting/discovery + /hosting/capabilities, cached, parsed
    proof.py       X-WOPI-Proof verification (RSA-SHA256 over token+URL+ticks)
    locks.py       WOPI locks (office.models.WopiLock), compare-and-set
    wopi.py        CheckFileInfo, GetFile, PutFile, Lock family, RenameFile
    views.py       browser helpers: token renewal, load events
    options.py     per-instance admin options (require_proof, print/export)

The editor page form-POSTs the access token to the discovery ``urlsrc`` into
a named iframe (the token is never put in a URL clientst0r builds), and
static/js/office-collabora.js speaks Collabora's postMessage protocol.

Facts are taken from Collabora's 26.04 source tree (research notes; the
official SDK pages could not be read). Points that are not verified are
marked "unverified" where they are used.
"""
from __future__ import annotations

import base64
import io
import logging
import os
import secrets
import zipfile
from urllib.parse import quote, urlencode, urlsplit

from django.urls import reverse
from django.utils import timezone

from ... import formats, net, storage, tokens
from ...logging_filters import RedactSecretsFilter, get_logger
from .. import register
from ..base import (FAIL, NOT_RUN, PASS, WARN, Capabilities, DiagnosticCheck, EditorPage,
                    EditorProvider, HealthResult, NotConfigured, NotSupported)
from . import discovery as disco
from . import options

logger = get_logger('office.collabora')

# Django's request logging and the WSGI server's access log carry the WOPI
# query string (access_token=...). Redact it there too.
for _name in ('django.request', 'django.server', 'gunicorn.access', 'gunicorn.error'):
    _lg = logging.getLogger(_name)
    if not any(isinstance(f, RedactSecretsFilter) for f in _lg.filters):
        _lg.addFilter(RedactSecretsFilter())

EDIT_EXTS = ('docx', 'xlsx', 'pptx')
EVIDENCE_DAYS = 30


def build_capabilities(disc, info) -> Capabilities:
    """Only what discovery and /hosting/capabilities actually advertise."""
    edit = frozenset(e for e in EDIT_EXTS if disc.has(e, 'edit'))
    view = frozenset(e for e in disco.WANTED_EXTS if disc.has(e, 'view') or disc.has(e, 'edit'))
    convert = set()
    if info is not None and info.convert_available and info.convert_endpoint:
        for src in view:
            convert.add((src, 'pdf'))
            dst = formats.conversion_target('x.' + src)
            if dst and src in formats.READ_ONLY:
                convert.add((src, dst))
    return Capabilities(edit_formats=edit, view_formats=view - edit, convert=frozenset(convert),
                        coauthoring=bool(edit), comments=bool(edit), review='docx' in edit)


def _origin(url):
    parts = urlsplit(url)
    return f'{parts.scheme}://{parts.netloc}'


def wopi_src(instance, session) -> str:
    """The WOPISrc Collabora calls back on: the callback origin plus our path."""
    return _origin(instance.callback_base_url) + reverse('office:collabora_wopi_file',
                                                         args=[session.document_key])


def _multipart(field, filename, data):
    boundary = 'clientst0r-' + secrets.token_hex(16)
    head = (f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; '
            f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()
    return head + data + f'\r\n--{boundary}--\r\n'.encode(), f'multipart/form-data; boundary={boundary}'


def _evidence(instance, key):
    """The newest session of `instance` carrying provider_state.collabora.<key>."""
    from datetime import timedelta
    from ...models import EditSession
    since = timezone.now() - timedelta(days=EVIDENCE_DAYS)
    for s in (EditSession.objects.filter(instance=instance, provider='collabora',
                                         opened_at__gte=since)
              .order_by('-opened_at').only('provider_state', 'opened_at')[:200]):
        st = (s.provider_state or {}).get('collabora') or {}
        if st.get(key):
            return st
    return None


class CollaboraProvider(EditorProvider):
    key = 'collabora'
    label = 'Collabora Online'

    # -- capabilities -------------------------------------------------------
    def capabilities(self, instance):
        return Capabilities.from_json(instance.capabilities)

    # -- editor page --------------------------------------------------------
    def editor_page_context(self, session, request):
        from ...targets import target_of
        from .wopi import note
        instance = session.instance
        target = target_of(session)
        if instance is None or target is None:
            raise NotConfigured('The editing session has no editor or file.')
        try:
            disc = disco.get_discovery(instance)
        except disco.DiscoveryError as e:
            raise NotConfigured(f'Collabora Online is not reachable: {e}')
        ext = target.extension
        caps = self.capabilities(instance)
        edit = (session.mode == 'edit' and caps.can_edit(ext)
                and not formats.is_read_only_format(target.filename))
        urlsrc = disc.urlsrc(ext, 'edit' if edit else 'view') or disc.urlsrc(ext, 'edit') \
            or disc.urlsrc(ext, 'view')
        if not urlsrc:
            raise NotConfigured(f'This Collabora server does not offer .{ext} files.')
        browser_origin = _origin(instance.browser_url)
        if _origin(urlsrc) != browser_origin:
            raise NotConfigured('Collabora discovery points at another host.')
        ops = ['read', 'write', 'lock', 'rename'] if edit else ['read']
        raw = tokens.issue(session, ops, purpose='wopi')
        ttl_ms = int(session.max_expires_at.timestamp() * 1000)
        host_origin = _origin(request.build_absolute_uri('/'))
        note(session, host_origin=host_origin, page_opened_at=timezone.now().isoformat())
        lang = (getattr(request, 'LANGUAGE_CODE', '') or 'en')[:10]
        action = disco.clean_urlsrc(urlsrc) + urlencode({'WOPISrc': wopi_src(instance, session),
                                                         'lang': lang})
        from ...models import OfficeSettings
        token_minutes = OfficeSettings.get().token_ttl_minutes or 60
        is_code = disco.is_code_product(instance.detected_edition)
        frame = 'collabora-' + secrets.token_hex(8)
        return EditorPage(
            template='office/collabora/editor.html',
            context={'action_url': action, 'access_token': raw, 'access_token_ttl': ttl_ms,
                     'frame_name': frame, 'form_id': frame + '-form', 'is_code': is_code,
                     'code_label': disco.CODE_LABEL, 'editor_origin': browser_origin,
                     'can_save': edit},
            config={'editorOrigin': browser_origin, 'frameName': frame,
                    'formId': frame + '-form', 'readOnly': not edit, 'isCode': is_code,
                    'renewUrl': reverse('office:collabora_renew', args=[session.pk]),
                    'eventUrl': reverse('office:collabora_event', args=[session.pk]),
                    'renewIntervalMs': max(60000, token_minutes * 60000 // 3)},
            csp={'frame-src': [browser_origin], 'child-src': [browser_origin],
                 'form-action': [browser_origin]},
            static_js=['js/office-collabora.js'])

    # -- health ---------------------------------------------------------------
    def health_check(self, instance):
        try:
            disc = disco.get_discovery(instance, refresh=True)
        except disco.DiscoveryError as e:
            return HealthResult(status='down', detail=str(e))
        notes = []
        try:
            info = disco.get_server_info(instance, disc)
        except disco.DiscoveryError as e:
            info = None
            notes.append(str(e))
        caps = build_capabilities(disc, info)
        status = 'ok'
        if not caps.edit_formats:
            status = 'degraded'
            notes.append('Discovery lists no edit action for .docx/.xlsx/.pptx.')
        if info is None:
            status = 'degraded'
        else:
            notes.insert(0, f'{info.product_name or "Collabora Online"} {info.version}'.strip())
            if info.is_code:
                notes.append(f'CODE: {disco.CODE_LABEL}. Use a licensed Collabora Online '
                             'build for production.')
        notes.append('Proof key published.' if disc.proof_key.present else
                     'No proof key published (requests are not signed).')
        if disc.rewritten:
            notes.append('Discovery named another host; its URLs were mapped to the browser '
                         'address.')
        return HealthResult(status=status, detail=' '.join(notes)[:2000],
                            version=info.version if info else '',
                            edition=info.edition if info else '', capabilities=caps)

    # -- diagnostics ----------------------------------------------------------
    def diagnostics(self, instance):
        checks = []
        opts = options.get(instance)
        try:
            disc = disco.get_discovery(instance, refresh=True)
        except disco.DiscoveryError as e:
            checks.append(DiagnosticCheck(
                'collabora.discovery', 'Discovery (/hosting/discovery)', FAIL, str(e),
                'Check that coolwsd is running and that this server can reach it over https '
                '(the "Internal URL", or the browser URL when none is set).'))
            for key, label in (('collabora.capabilities', 'Server capabilities'),
                               ('collabora.proof', 'WOPI proof key'),
                               ('collabora.websocket', 'WebSocket upgrade through the proxy'),
                               ('collabora.wopi', 'Collabora → clientst0r WOPI'),
                               ('collabora.browser', 'Browser loads the editor')):
                checks.append(DiagnosticCheck(key, label, NOT_RUN, 'Discovery failed first.'))
            return checks
        exts = ', '.join(sorted(e for e in disc.actions if disc.has(e, 'edit'))) or 'none'
        checks.append(DiagnosticCheck(
            'collabora.discovery', 'Discovery (/hosting/discovery)', PASS,
            f'Net zone {disc.zone}; edit actions for: {exts}.'))
        if disc.rewritten:
            checks.append(DiagnosticCheck(
                'collabora.server_name', 'Editor address in discovery', WARN,
                'Discovery named a host other than the browser URL; clientst0r maps it to the '
                'browser URL.', 'Set server_name in coolwsd.xml to the browser host name.'))
        server = instance.server_url()
        if server.startswith('https://'):
            checks.append(DiagnosticCheck(
                'collabora.tls', 'TLS', PASS,
                'Certificate verified' + (' against the instance CA bundle and the system '
                                          'trust store.' if instance.ca_bundle else
                                          ' against the system trust store.')))
        else:
            checks.append(DiagnosticCheck(
                'collabora.tls', 'TLS', WARN, 'Plain http on loopback (same-server install).',
                'Acceptable only for an editor on this server behind a local TLS proxy.'))
        try:
            info = disco.get_server_info(instance, disc)
            label = info.edition
            status = WARN if info.is_code else PASS
            conv = 'convert-to available' if info.convert_available else 'convert-to not offered'
            checks.append(DiagnosticCheck(
                'collabora.capabilities', 'Server capabilities', status,
                f'{label}, version {info.version or "?"}; {conv}.',
                f'CODE is {disco.CODE_LABEL.lower()}; use licensed Collabora Online in '
                'production.' if info.is_code else ''))
        except disco.DiscoveryError as e:
            checks.append(DiagnosticCheck(
                'collabora.capabilities', 'Server capabilities', WARN, str(e),
                'Version and conversion cannot be detected; PDF export stays off.'))
        if disc.proof_key.present:
            checks.append(DiagnosticCheck(
                'collabora.proof', 'WOPI proof key', PASS if opts['require_proof'] else WARN,
                'Published; WOPI requests must carry a valid proof.' if opts['require_proof'] else
                'Published, but require_proof is OFF for this instance.',
                '' if opts['require_proof'] else
                'manage.py office_collabora --instance %s --require-proof on' % instance.pk))
        else:
            checks.append(DiagnosticCheck(
                'collabora.proof', 'WOPI proof key', WARN,
                'Discovery publishes no proof key, so clientst0r cannot tell Collabora\'s '
                'requests from anyone else holding a token.',
                'On the Collabora server: sudo coolconfig generate-proof-key, then '
                'sudo systemctl restart coolwsd, then run diagnostics again.'))
        checks.append(self._websocket_probe(instance))
        seen = _evidence(instance, 'wopi_seen_at')
        if seen:
            checks.append(DiagnosticCheck(
                'collabora.wopi', 'Collabora → clientst0r WOPI', PASS,
                f'Collabora fetched file info at {seen["wopi_seen_at"]} '
                f'(proof: {seen.get("proof", "?")}).'))
        else:
            checks.append(DiagnosticCheck(
                'collabora.wopi', 'Collabora → clientst0r WOPI', NOT_RUN,
                'Collabora has not called the WOPI endpoint in the last '
                f'{EVIDENCE_DAYS} days, so reachability is not proven.',
                f'Open any Office file in the editor and run diagnostics again. Collabora must '
                f'reach {_origin(instance.callback_base_url)} and list it in '
                'storage.wopi.alias_groups (mode="groups").'))
        loaded = _evidence(instance, 'browser')
        loaded_at = (loaded or {}).get('browser', {}).get('document_loaded') if loaded else None
        if loaded_at:
            checks.append(DiagnosticCheck(
                'collabora.browser', 'Browser loads the editor', PASS,
                f'A browser reported the document loaded at {loaded_at}.'))
        else:
            checks.append(DiagnosticCheck(
                'collabora.browser', 'Browser loads the editor', NOT_RUN,
                'No browser has reported a loaded document yet; this server cannot test '
                'what users\' browsers can reach.',
                f'Open an Office file in the editor from a user\'s network; '
                f'{_origin(instance.browser_url)} must be reachable and allow framing by '
                'clientst0r (net.content_security_policy frame-ancestors).'))
        return checks

    def _websocket_probe(self, instance):
        """HTTP/1.1 Upgrade to Collabora's legacy /cool/<WOPISrc>/ws path
        through the browser address (so through the reverse proxy). 101 means
        the proxy passes WebSocket upgrades. The path form is the one the
        26.04 source still accepts; other answers are reported, not judged."""
        label = 'WebSocket upgrade through the proxy'
        src = _origin(instance.callback_base_url) + reverse(
            'office:collabora_wopi_file', args=['diagnostics-websocket-probe'])
        url = instance.browser_url.rstrip('/') + '/cool/' + quote(src, safe='') + '/ws'
        headers = {'Connection': 'Upgrade', 'Upgrade': 'websocket',
                   'Sec-WebSocket-Version': '13',
                   'Sec-WebSocket-Key': base64.b64encode(os.urandom(16)).decode(),
                   'Origin': _origin(instance.callback_base_url)}
        try:
            result = net.fetch(url, instance, 64 * 1024, headers=headers,
                               timeout=min(15, instance.request_timeout_s or 15))
        except net.OfficeFetchError as e:
            return DiagnosticCheck('collabora.websocket', label, NOT_RUN,
                                   f'Probe could not run: {e}'[:400],
                                   'Open a document in a browser: a failed WebSocket shows as '
                                   'an endless "Loading" in the editor.')
        if result.status_code == 101:
            return DiagnosticCheck('collabora.websocket', label, PASS,
                                   'The proxy answered 101 Switching Protocols.')
        return DiagnosticCheck(
            'collabora.websocket', label, WARN,
            f'Expected 101 Switching Protocols, got HTTP {result.status_code}.',
            'Pass Upgrade/Connection headers for /cool/ in the reverse proxy '
            '(see docs/office/COLLABORA.md).')

    # -- round trip ---------------------------------------------------------------
    def round_trip(self, instance, session, report):
        from ...targets import target_of
        from . import selftest
        target = target_of(session)
        try:
            disc = disco.get_discovery(instance, refresh=True)
            report.step('discovery', 'Fetch discovery from Collabora', PASS,
                        f'{len(disc.actions)} formats listed.')
        except disco.DiscoveryError as e:
            report.step('discovery', 'Fetch discovery from Collabora', FAIL, str(e))
            disc = None
        rev = storage.current(target)
        info = None
        if disc is not None:
            try:
                info = disco.get_server_info(instance, disc)
            except disco.DiscoveryError:
                info = None
        resaved = None
        if info is not None and info.convert_available:
            try:
                pdf = self._convert_bytes(instance, rev, 'pdf', info)
                report.step('convert_pdf', 'Collabora renders the document (convert-to pdf)',
                            PASS, f'{len(pdf)} bytes of PDF.')
            except Exception as e:
                report.step('convert_pdf', 'Collabora renders the document (convert-to pdf)',
                            FAIL, str(e)[:300],
                            'Check net.post_allow in coolwsd.xml includes this server.')
            try:
                resaved = self._convert_bytes(instance, rev, 'docx', info)
                report.step('resave', 'Collabora loads and re-saves the .docx (convert-to docx)',
                            PASS, f'{len(resaved)} bytes, valid .docx.')
            except Exception as e:
                report.step('resave', 'Collabora loads and re-saves the .docx (convert-to docx)',
                            FAIL, str(e)[:300])
        else:
            for key, label in (('convert_pdf', 'Collabora renders the document (convert-to pdf)'),
                               ('resave', 'Collabora loads and re-saves the .docx')):
                report.step(key, label, NOT_RUN, 'The server does not offer convert-to.',
                            'Enable convert-to and allow this server in net.post_allow.')
        source = 'Collabora-re-saved bytes'
        if resaved is None:
            with storage.open_revision(rev) as fh:
                resaved = _touched_docx(fh.read())
            source = 'locally modified bytes (no Collabora output available)'
        selftest.run(instance, session, report, resaved, source)
        seen = _evidence(instance, 'wopi_seen_at')
        report.step('editor_to_wopi', 'Collabora reaches clientst0r\'s WOPI endpoint',
                    PASS if seen else NOT_RUN,
                    f'Last seen {seen["wopi_seen_at"]}.' if seen else
                    'Needs a browser: Collabora only calls WOPI while a user has the document '
                    'open.',
                    '' if seen else 'Open an Office file in the editor, then run diagnostics.')
        report.step('browser', 'Open, type and save in a browser', NOT_RUN,
                    'Collabora edits only through its browser client (WebSocket). This step '
                    'cannot be driven from the server.',
                    'Open the file, type a word, wait for "Saved to clientst0r", reopen it.')

    # -- conversion ---------------------------------------------------------------
    def _convert_bytes(self, instance, revision, target_ext, info=None):
        if info is None:
            info = disco.get_server_info(instance)
        if not (info.convert_available and info.convert_endpoint):
            raise NotSupported('This Collabora server does not offer conversion.')
        src_ext = formats.extension(revision.original_name)
        with storage.open_revision(revision) as fh:
            data = fh.read(storage.max_bytes(instance) + 1)
        if len(data) > storage.max_bytes(instance):
            raise NotSupported('The file is larger than the conversion limit.')
        body, ctype = _multipart('data', f'document.{src_ext}', data)
        url = instance.server_url().rstrip('/') + info.convert_endpoint.rstrip('/') + '/' + target_ext
        try:
            result = net.fetch(url, instance, storage.max_bytes(instance), method='POST',
                               headers={'Content-Type': ctype}, data=body,
                               timeout=instance.conversion_timeout_s or 120)
        except net.OfficeFetchError as e:
            raise NotSupported(f'Collabora conversion failed: {e}'[:300])
        if result.status_code != 200:
            raise NotSupported(f'Collabora conversion answered HTTP {result.status_code}.')
        out = result.content
        if target_ext == 'pdf':
            if not out.startswith(b'%PDF-'):
                raise NotSupported('Collabora did not return a PDF.')
        else:
            try:
                formats.validate_ooxml(io.BytesIO(out), target_ext)
            except formats.InvalidOfficeFile as e:
                raise NotSupported(f'Collabora returned an invalid .{target_ext}: {e}')
        return out

    def convert(self, instance, revision, target_ext, *, user=None):
        src = formats.extension(revision.original_name)
        if not self.capabilities(instance).can_convert(src, target_ext):
            raise NotSupported(f'Collabora cannot convert .{src} to .{target_ext} here.')
        return self._convert_bytes(instance, revision, target_ext)


def _touched_docx(data):
    """`data` (a .docx) with a zip comment changed: different bytes, same document."""
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with src, zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            dst.writestr(item, src.read(item))
        dst.comment = f'clientst0r round trip {timezone.now().isoformat()}'.encode()
    return out.getvalue()


register(CollaboraProvider())
