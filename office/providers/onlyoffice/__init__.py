"""ONLYOFFICE Docs connector (Document Server 10.x, Docs API + callback protocol).

Pieces:

    signing.py   HS256 JWTs: editor config, inbox (command/converter), outbox
                 (callbacks/downloads) verification
    client.py    healthcheck, command service, conversion service, downloads
                 (all through office.net.fetch)
    state.py     per-session provider_state: editor key per save generation,
                 editor user id, last callback / error / save
    callback.py  the save callback (statuses 1/2/3/4/6/7)
    views.py     callback, document URL, conversion source, browser helpers,
                 browser probe
    static/js/office-onlyoffice.js       DocEditor <-> window.ClientstorOffice
    static/js/office-onlyoffice-probe.js the diagnostics browser probe

See docs/office/ONLYOFFICE.md for the editor-side settings.
"""
from __future__ import annotations

import hashlib
import io
import re
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from office import formats, net, sessions, storage, tokens
from office.logging_filters import get_logger

from .. import register
from ..base import (FAIL, NOT_RUN, PASS, WARN, Capabilities, DiagnosticCheck, EditorPage,
                    EditorProvider, HealthResult, NotConfigured, NotSupported)
from . import client, signing, state

log = get_logger('office.onlyoffice')

MIN_VERSION = (10, 0, 0)
API_JS_PATH = '/web-apps/apps/api/documents/api.js'

EDIT_FORMATS = frozenset({'docx', 'xlsx', 'pptx'})
# Legacy and macro-enabled files: opened read-only (the core never stores an
# editor save for them), convertible to a new OOXML copy.
VIEW_FORMATS = frozenset({'doc', 'xls', 'ppt', 'docm', 'xlsm', 'pptm'})

# license command: server.packageType (0 open source, 1 enterprise,
# 2 developer) as described for the command service; unverified against 10.0.
PACKAGE_TYPES = {0: 'Community', 1: 'Enterprise', 2: 'Developer'}

EVIDENCE_DAYS = 30
MOBILE_UA = re.compile(r'Mobi|Android|iPhone|iPad', re.I)


def _origin(url):
    from office.views import _origin_str
    return _origin_str(url)


def _ago(iso):
    when = parse_datetime(iso) if isinstance(iso, str) else iso
    return when if when is not None else None


def build_capabilities(convert_ok: bool) -> Capabilities:
    convert = set()
    if convert_ok:
        for ext in EDIT_FORMATS | VIEW_FORMATS:
            convert.add((ext, 'pdf'))
        for ext in VIEW_FORMATS:
            convert.add((ext, formats.conversion_target('x.' + ext)))
    return Capabilities(edit_formats=EDIT_FORMATS, view_formats=VIEW_FORMATS,
                        convert=frozenset(convert), coauthoring=True, comments=True, review=True,
                        max_file_mb=None)


class OnlyOfficeProvider(EditorProvider):
    key = 'onlyoffice'
    label = 'ONLYOFFICE Docs'

    # ------------------------------------------------------------------
    def capabilities(self, instance) -> Capabilities:
        return Capabilities.from_json(instance.capabilities)

    def _require_secret(self, instance):
        from office.models import secret_problem
        problem = secret_problem(instance.shared_secret)
        if problem:
            raise NotConfigured(f'The ONLYOFFICE instance "{instance.name}" has no usable JWT '
                                f'secret: {problem}')

    # ------------------------------------------------------------------
    def editor_page_context(self, session, request) -> EditorPage:
        from office.targets import target_of
        from office import creation
        instance = session.instance
        if instance is None:
            raise NotConfigured('The editor instance of this session no longer exists.')
        self._require_secret(instance)
        target = target_of(session)
        if target is None:
            raise NotConfigured('The file no longer exists.')
        ext = target.extension
        kind = formats.kind_for(target.filename)
        caps = self.capabilities(instance)
        if not caps.can_view(ext) or kind is None:
            raise NotConfigured(f'{self.label} cannot open .{ext} files on this instance.')
        edit = session.mode == 'edit' and caps.can_edit(ext)

        key = state.editor_key(session)
        raw = tokens.issue(session, ops=['read'], purpose='onlyoffice-file')
        base = instance.callback_base_url.rstrip('/')
        doc_url = base + reverse('office:onlyoffice_file', args=[session.pk]) + '?access_token=' + raw

        permissions = {
            'edit': edit,
            'comment': edit and caps.comments,
            'review': edit and caps.review and kind == formats.KIND_WORD,
            'fillForms': edit,
            'modifyFilter': edit,
            'modifyContentControl': edit,
            'chat': edit,
            'protect': edit,
            # The user may already download / print the file from clientst0r.
            'download': True,
            'print': True,
            'copy': True,
        }
        lang = (getattr(request, 'LANGUAGE_CODE', '') or 'en').split('-')[0][:5] or 'en'
        editor_config = {
            'mode': 'edit' if edit else 'view',
            'lang': lang,
            'user': {'id': state.oo_user_id(session.user), 'name': state.display_name(session.user)},
            'coEditing': {'mode': 'fast', 'change': True},
            'customization': {
                # The editor's own Save button force-saves to clientst0r.
                'forcesave': edit,
                # Plugins, macros and the editor's AI integration are off;
                # clientst0r offers no AI features here.
                'plugins': False,
                'macros': False,
                'macrosMode': 'disable',
                'ai': {'disabled': True},
            },
        }
        if edit:
            editor_config['callbackUrl'] = base + reverse('office:onlyoffice_callback',
                                                          args=[session.pk])
        ua = request.META.get('HTTP_USER_AGENT', '')
        config = {
            'documentType': kind,
            'type': 'mobile' if MOBILE_UA.search(ua) else 'desktop',
            'width': '100%',
            'height': '100%',
            'document': {
                'fileType': ext,
                'key': key,
                'title': target.filename[:128],
                'url': doc_url,
                'permissions': permissions,
            },
            'editorConfig': editor_config,
        }
        config['token'] = signing.sign_config(config, instance.shared_secret)

        origin = _origin(instance.browser_url)
        sid = [session.pk]
        page_config = {
            'docConfig': config,
            'placeholder': 'onlyoffice-editor',
            'statusUrl': reverse('office:onlyoffice_status', args=sid),
            'forcesaveUrl': reverse('office:onlyoffice_forcesave', args=sid) if edit else '',
            'saveAsUrl': (reverse('office:onlyoffice_save_as', args=sid)
                          if creation.can_copy(target, session.user) else ''),
        }
        return EditorPage(
            template='office/providers/onlyoffice/editor.html',
            context={'edit': edit},
            config=page_config,
            script_urls=[client.browser_base(instance) + API_JS_PATH],
            csp={'script-src': [origin], 'frame-src': [origin], 'connect-src': [origin]},
            static_js=['js/office-onlyoffice.js'],
        )

    # ------------------------------------------------------------------
    def _version(self, instance):
        data = client.command(instance, 'version')
        return str(data.get('version') or '')

    def _edition(self, instance):
        try:
            data = client.command(instance, 'license')
        except (client.DocsError, net.OfficeFetchError):
            return ''
        server = data.get('server') if isinstance(data.get('server'), dict) else {}
        ptype = server.get('packageType')
        try:
            return PACKAGE_TYPES.get(int(ptype), '')
        except (TypeError, ValueError):
            return ''

    def probe_conversion(self, instance):
        """Convert clientst0r's blank .docx to PDF through the conversion
        service. Proves: the converter is enabled, Docs reached clientst0r's
        source link with a valid outbox token, and the result downloads.
        Returns (ok, detail, error code)."""
        from .views import source_link
        try:
            answer = client.convert(instance, url=source_link(instance, probe_ext='docx'),
                                    filetype='docx', outputtype='pdf', title='probe.docx',
                                    key=client.new_conversion_key('probe'))
            data = client.download(instance, answer['fileUrl'], 20 * 1024 * 1024)
        except client.DocsError as e:
            return False, str(e), e.code
        except net.OfficeFetchError as e:
            return False, str(e)[:300], None
        if not data.startswith(b'%PDF-'):
            return False, 'The conversion result is not a PDF.', None
        return True, f'A .docx was converted to PDF ({len(data)} bytes).', 0

    def health_check(self, instance) -> HealthResult:
        try:
            self._require_secret(instance)
        except NotConfigured as e:
            return HealthResult(status='down', detail=str(e))
        try:
            hc = client.healthcheck(instance)
        except net.OfficeFetchError as e:
            return HealthResult(status='down', detail=f'Healthcheck failed: {str(e)[:300]}')
        if hc.status_code != 200 or hc.content.strip().lower() != b'true':
            return HealthResult(status='down', detail=f'/healthcheck answered HTTP {hc.status_code} '
                                                      f'without "true".')
        try:
            version = self._version(instance)
        except client.DocsError as e:
            if e.code == 6:
                return HealthResult(status='degraded', detail='The Document Server rejected the '
                                    'signed request: the JWT secret does not match its inbox secret.')
            return HealthResult(status='degraded', detail=f'Version query failed: {e}')
        except net.OfficeFetchError as e:
            return HealthResult(status='degraded', detail=f'Command service unreachable: {str(e)[:300]}')
        edition = self._edition(instance)
        if client.version_tuple(version) < MIN_VERSION:
            return HealthResult(status='degraded', version=version, edition=edition,
                                detail=f'Version {version or "unknown"} is older than 10.0.0; this '
                                       f'connector needs 10.0 or later.')
        ok, detail, code = self.probe_conversion(instance)
        caps = build_capabilities(ok)
        if not ok and code == -4:
            return HealthResult(status='degraded', version=version, edition=edition,
                                capabilities=caps,
                                detail='The Document Server could not download a file from '
                                       'clientst0r (callback address). Editing would fail too: '
                                       'check the callback URL, the editor\'s request-filtering '
                                       'settings and TLS trust. ' + detail)
        text = f'ONLYOFFICE Docs {version}' + (f' ({edition})' if edition else '') + ' is ready.'
        text += (' PDF export and conversion available.' if ok else
                 f' Conversion is not advertised: {detail}')
        return HealthResult(status='ok', version=version, edition=edition, capabilities=caps,
                            detail=text)

    # ------------------------------------------------------------------
    def diagnostics(self, instance) -> list:
        checks = []
        add = checks.append
        try:
            self._require_secret(instance)
        except NotConfigured as e:
            add(DiagnosticCheck('oo.jwt', 'Signed requests (JWT)', NOT_RUN, str(e),
                                'Set the instance secret first.'))
            return checks

        # Healthcheck through the internal (server-to-server) address.
        try:
            hc = client.healthcheck(instance)
            good = hc.status_code == 200 and hc.content.strip().lower() == b'true'
            add(DiagnosticCheck('oo.healthcheck', 'Document Server /healthcheck', PASS if good else FAIL,
                                f'HTTP {hc.status_code} from {client.base_url(instance)}/healthcheck.',
                                '' if good else 'Check the Document Server service and its logs '
                                '(/var/log/onlyoffice/documentserver/).'))
        except net.OfficeFetchError as e:
            add(DiagnosticCheck('oo.healthcheck', 'Document Server /healthcheck', FAIL, str(e)[:300],
                                'Check the internal URL, the firewall and that the service runs.'))

        # TLS of the browser address when the internal address differs.
        if instance.internal_url and _origin(instance.internal_url) != _origin(instance.browser_url):
            try:
                client.healthcheck(instance, url=client.browser_base(instance))
                add(DiagnosticCheck('oo.tls_browser', 'Browser address reachable over verified TLS',
                                    PASS, f'{_origin(instance.browser_url)} answered from this server.'))
            except net.OfficeFetchError as e:
                add(DiagnosticCheck('oo.tls_browser', 'Browser address reachable over verified TLS',
                                    WARN, str(e)[:300],
                                    'This server need not reach the browser address, but its '
                                    'certificate must be trusted by users\' browsers.'))

        # JWT + version.
        version = ''
        try:
            version = self._version(instance)
            add(DiagnosticCheck('oo.jwt', 'Signed requests (JWT, inbox secret)', PASS,
                                'The command service accepted a signed "version" request.'))
            new_enough = client.version_tuple(version) >= MIN_VERSION
            add(DiagnosticCheck('oo.version', 'Document Server version', PASS if new_enough else FAIL,
                                f'Detected {version or "unknown"}. No connection or user limit is '
                                f'assumed; it depends on the edition and licence deployed.',
                                '' if new_enough else 'Upgrade to ONLYOFFICE Docs 10.0 or later.'))
        except client.DocsError as e:
            add(DiagnosticCheck('oo.jwt', 'Signed requests (JWT, inbox secret)', FAIL, str(e),
                                'Set services.CoAuthoring.secret.inbox/outbox/browser in '
                                'local.json to the secret stored here, then restart Docs.'
                                if e.code == 6 else 'Check the Document Server logs.'))
        except net.OfficeFetchError as e:
            add(DiagnosticCheck('oo.jwt', 'Signed requests (JWT, inbox secret)', FAIL, str(e)[:300],
                                'The command service (/command) is unreachable.'))

        # Default secret on the server side.
        try:
            client.command(instance, 'version', secret=client.DEFAULT_SECRET)
            add(DiagnosticCheck('oo.default_secret', 'Server rejects the published default secret',
                                FAIL, 'The Document Server accepted a request signed with '
                                '"developer-only-not-a-real-secret" (or does not check inbox tokens).',
                                'Replace every secret in local.json with a random one and keep '
                                'token.enable.request.inbox/outbox and token.enable.browser on.'))
        except client.DocsError as e:
            if e.code == 6:
                add(DiagnosticCheck('oo.default_secret', 'Server rejects the published default secret',
                                    PASS, 'A request signed with the vendor default secret was refused.'))
            else:
                add(DiagnosticCheck('oo.default_secret', 'Server rejects the published default secret',
                                    NOT_RUN, str(e)))
        except net.OfficeFetchError as e:
            add(DiagnosticCheck('oo.default_secret', 'Server rejects the published default secret',
                                NOT_RUN, str(e)[:300]))

        # Docs -> clientst0r downloads (the same path document.url uses).
        ok, detail, code = self.probe_conversion(instance)
        if ok:
            add(DiagnosticCheck('oo.download', 'Editor reaches clientst0r (document download)', PASS,
                                'The Document Server downloaded a file from the callback address with '
                                'a valid outbox token and converted it. ' + detail))
        else:
            add(DiagnosticCheck(
                'oo.download', 'Editor reaches clientst0r (document download)', FAIL, detail,
                'From the editor host, the callback address must resolve and be reachable '
                '(firewall), its certificate trusted (NODE_EXTRA_CA_CERTS for a private CA), and '
                'for a private address request-filtering-agent.allowIPAddressList must list the '
                'clientst0r address.' if code == -4 else
                'The conversion service failed; check services.CoAuthoring.server.convertServiceEnable '
                'and the converter log.'))

        # Callbacks: only an editing session makes Docs call back.
        at, status = state.last_callback_evidence(instance)
        when = _ago(at)
        if when and when > timezone.now() - timedelta(days=EVIDENCE_DAYS):
            add(DiagnosticCheck('oo.callback', 'Editor reaches clientst0r (save callback)', PASS,
                                f'Last callback received {when:%Y-%m-%d %H:%M} UTC (status {status}).'))
        else:
            add(DiagnosticCheck(
                'oo.callback', 'Editor reaches clientst0r (save callback)', NOT_RUN,
                f'No callback received in the last {EVIDENCE_DAYS} days.',
                'Docs sends callbacks only for documents open in a browser. Open any document in '
                'the editor, change it and press Save (or close it); this check then shows the '
                'time the callback arrived. The document-download check above already proves '
                'the editor can reach clientst0r.'))

        # WebSocket through the reverse proxy.
        seen = state.last_value(instance, 'oo_users_at')
        add(DiagnosticCheck(
            'oo.websocket', 'WebSocket through the reverse proxy', NOT_RUN,
            'Not probed from the server: the co-editing connection is made by the browser.'
            + (f' An editing session last reported connected users at {seen[:16]} UTC, so the '
               'co-editing connection worked then (it may have fallen back to long polling).'
               if seen else ''),
            'Every proxy in front of the Document Server must pass "Upgrade" and '
            '"Connection: upgrade" headers (proxy_http_version 1.1) and allow long-lived '
            'connections. In the browser developer tools, the editor\'s socket request should '
            'answer 101 Switching Protocols.'))

        # Browser reachability: what an administrator's browser saw.
        from .views import last_browser_probe
        probe = last_browser_probe(instance)
        url = reverse('office:onlyoffice_browser_probe', args=[instance.pk])
        if probe and probe.timestamp > timezone.now() - timedelta(days=EVIDENCE_DAYS):
            outcome = (probe.extra_data or {}).get('outcome')
            add(DiagnosticCheck(
                'oo.browser', 'Browser loads the editor (api.js)', PASS if probe.success else FAIL,
                f'Browser probe {probe.timestamp:%Y-%m-%d %H:%M} UTC by {probe.username}: {outcome}.',
                '' if probe.success else
                f'Users\' browsers must reach {client.browser_base(instance)} over trusted https. '
                f'Re-run the probe at {url}.'))
        else:
            add(DiagnosticCheck('oo.browser', 'Browser loads the editor (api.js)', NOT_RUN,
                                'This server cannot see what users\' browsers reach.',
                                f'Open {url} in a browser on the users\' network; it loads api.js '
                                f'from the editor and records the result here.'))
        return checks

    # ------------------------------------------------------------------
    def round_trip(self, instance, session, report) -> None:
        from office.targets import target_of
        from . import callback
        self._require_secret(instance)
        target = target_of(session)
        state.editor_key(session)
        base = storage.current(target)
        raw = tokens.issue(session, ops=['read'], purpose='onlyoffice-file')
        doc_url = (instance.callback_base_url.rstrip('/')
                   + reverse('office:onlyoffice_file', args=[session.pk]) + '?access_token=' + raw)
        try:
            answer = client.convert(instance, url=doc_url, filetype='docx', outputtype='docx',
                                    title=target.filename, key=client.new_conversion_key('rt'))
        except (client.DocsError, net.OfficeFetchError) as e:
            code = getattr(e, 'code', None)
            report.step('open', 'Document Server loads the document from clientst0r', FAIL,
                        str(e)[:300],
                        'Docs could not download from the callback address; see the '
                        '"document download" diagnostic.' if code == -4 else '')
            tokens.revoke(raw)
            return
        session.refresh_from_db()
        fetched = (session.provider_state or {}).get('oo_file_fetched_at')
        report.step('open', 'Document Server loads the document from clientst0r',
                    PASS if fetched else FAIL,
                    f'Docs fetched revision {base.revision_number} through the session\'s document '
                    f'URL (token + outbox JWT checked).' if fetched else
                    'The conversion finished but clientst0r did not record the download.')
        try:
            data = client.download(instance, answer['fileUrl'], storage.max_bytes(instance))
            formats.validate_file(io.BytesIO(data), 'x.docx')
        except (net.OfficeFetchError, formats.InvalidOfficeFile) as e:
            report.step('edit', 'Document Server rewrites and returns the document', FAIL, str(e)[:300])
            tokens.revoke(raw)
            return
        sha = hashlib.sha256(data).hexdigest()
        report.step('edit', 'Document Server rewrites and returns the document', PASS,
                    f'Docs re-saved the document ({len(data)} bytes, sha256 {sha[:12]}…; the '
                    f'original was {base.sha256[:12]}…).')
        outcome = callback.persist(session, data, status=6, filetype='docx')
        if outcome is None or not outcome.ok:
            reason = getattr(outcome.error, 'message', '') if outcome else 'nothing stored'
            report.step('save', 'Save back to clientst0r (callback persistence path)', FAIL, reason)
            tokens.revoke(raw)
            return
        rev = outcome.revision
        expected_no = base.revision_number + (0 if outcome.duplicate else 1)
        good = rev.revision_number == expected_no and rev.sha256 == sha
        report.step('save', 'Save back to clientst0r (callback persistence path)',
                    PASS if good else FAIL,
                    f'Stored as revision {rev.revision_number}' +
                    (' (identical to the original: recorded as a duplicate)' if outcome.duplicate else '')
                    + f', sha256 {rev.sha256[:12]}….')
        with storage.open_revision(rev) as fh:
            stored = hashlib.sha256(fh.read()).hexdigest()
        report.step('reopen', 'Reopen the stored revision and compare checksums',
                    PASS if stored == sha else FAIL,
                    'The stored bytes match the bytes the editor returned.' if stored == sha else
                    'The stored bytes differ from what the editor returned.')
        at, status = state.last_callback_evidence(instance)
        when = _ago(at)
        if when and when > timezone.now() - timedelta(days=EVIDENCE_DAYS):
            report.step('callback', 'Editor save callback reaches clientst0r', PASS,
                        f'Last real callback received {when:%Y-%m-%d %H:%M} UTC (status {status}).')
        else:
            report.step('callback', 'Editor save callback reaches clientst0r', NOT_RUN,
                        'Docs sends save callbacks only for documents open in a browser editor, so '
                        'this server-driven test cannot trigger one.',
                        'Open a document in the editor, change it and press Save; then run the '
                        'diagnostics again.')
        tokens.revoke(raw)
        report.step('cleanup', 'Clean up', PASS,
                    'Read token revoked. The disposable file is removed by the scheduled purge '
                    'after a day; Docs discards conversion results itself (storage.fs.urlExpires).')

    # ------------------------------------------------------------------
    def convert(self, instance, revision, target_ext, *, user=None) -> bytes:
        from .views import source_link
        src = formats.extension(revision.original_name)
        if not self.capabilities(instance).can_convert(src, target_ext):
            raise NotSupported(f'{self.label} cannot convert .{src} to .{target_ext} here.')
        self._require_secret(instance)
        try:
            answer = client.convert(instance, url=source_link(instance, revision), filetype=src,
                                    outputtype=target_ext, title=revision.original_name)
            data = client.download(instance, answer['fileUrl'], storage.max_bytes(instance))
        except client.DocsError as e:
            raise NotSupported(f'The conversion failed: {e}')
        except net.OfficeFetchError as e:
            raise NotConfigured(f'The editor could not be reached for the conversion: {str(e)[:200]}')
        if target_ext == 'pdf':
            if not data.startswith(b'%PDF-'):
                raise NotSupported('The conversion result is not a PDF.')
        else:
            try:
                formats.validate_file(io.BytesIO(data), 'x.' + target_ext)
            except formats.InvalidOfficeFile as e:
                raise NotSupported(f'The conversion result is not a valid .{target_ext}: {e}')
        return data

    # ------------------------------------------------------------------
    def force_save(self, session) -> bool:
        """Command service ``forcesave`` for this session's editor key (used
        by ``office_sessions --drain``). The save itself still arrives as a
        status 6 callback. Error 4 ("no changes") counts as success."""
        key = (session.provider_state or {}).get('oo_key')
        if not key or session.instance is None:
            return True  # never opened in the editor: nothing to save
        try:
            client.command(session.instance, 'forcesave', key=key, userdata=str(session.pk))
        except client.DocsError as e:
            if e.code == 4:
                return True
            log.warning('ONLYOFFICE forcesave (drain) failed for session %s: %s', session.pk, e)
            return False
        return True

    def on_session_revoked(self, session) -> None:
        ps = session.provider_state or {}
        key, user = ps.get('oo_key'), ps.get('oo_user')
        if not key or not user or session.instance is None:
            return
        try:
            client.command(session.instance, 'drop', key=key, users=[user])
        except Exception as e:  # must not raise
            log.info('ONLYOFFICE drop for revoked session %s: %s', session.pk, e)


register(OnlyOfficeProvider(), replace=True)
