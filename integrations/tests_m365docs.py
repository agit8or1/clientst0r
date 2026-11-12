"""Microsoft 365 documents (integrations/m365docs).

Microsoft is replaced at the HTTP layer: ``m365docs.http._net_fetch`` (the
office.net.fetch call every request goes through) is swapped for FakeMicrosoft,
which answers with the response shapes Microsoft documents for the
identity-platform token endpoint and the Graph v1.0 drive / driveItem / site
resources. Every check above that layer (hosts, sharing-endpoint refusal,
allowed locations, clientst0r permissions, PKCE, encryption) runs for real.

These tests prove clientst0r's side. They do not prove a real tenant accepts
the requests: that is tests_m365docs_e2e.py, which has NOT been run.
"""
import base64
import hashlib
import json
import re
import shutil
import tempfile
from datetime import timedelta
from unittest import mock
from urllib.parse import parse_qs, unquote, urlsplit

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.db import connection as db_connection
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role
from audit.models import AuditLog
from core.models import Organization
from docs.models import Document
from integrations.m365docs import access, graph, http, oauth, scopes, services
from integrations.models import (LinkedCloudDocument, M365AllowedLocation, M365Connection,
                                 M365DocsGrant)
from office import net, storage, targets
from office.models import FileRevision

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

with open(django_settings.BASE_DIR / 'office' / 'templates_files' / 'blank.docx', 'rb') as _fh:
    BLANK_DOCX = _fh.read()

SHARING_RE = re.compile(r'/(createLink|invite|permissions|grant|shares|preview)\b', re.I)
TENANT = '11111111-2222-3333-4444-555555555555'
DRIVE = 'b!drive-A_1'
OTHER_DRIVE = 'b!drive-B_2'
SITE = 'contoso.sharepoint.com,aaaa-1,bbbb-2'


def _item(item_id, name, parent_id, *, drive=DRIVE, folder=False, size=10, path=''):
    """A Graph driveItem as documented (only the properties we select)."""
    out = {'id': item_id, 'name': name, 'eTag': f'"{{{item_id}}},1"', 'size': size,
           'webUrl': f'https://contoso.sharepoint.com/sites/Finance/Shared%20Documents/{name}',
           'lastModifiedDateTime': '2026-11-01T10:00:00Z',
           'parentReference': {'driveId': drive, 'driveType': 'documentLibrary',
                               'path': f'/drives/{drive}/root:{path}'}}
    if parent_id:
        out['parentReference']['id'] = parent_id
    if folder:
        out['folder'] = {'childCount': 0}
    else:
        out['file'] = {'mimeType': 'application/vnd.openxmlformats-officedocument.'
                                   'wordprocessingml.document'}
    return out


class FakeMicrosoft:
    """Token endpoint + Graph, at the office.net.fetch call boundary."""

    def __init__(self):
        self.calls = []
        self.items = {
            (DRIVE, 'root'): _item('ROOT-A', 'root', None, folder=True),
            (DRIVE, 'F1'): _item('F1', 'Contracts', 'ROOT-A', folder=True, path=''),
            (DRIVE, 'F2'): _item('F2', '2026', 'F1', folder=True, path='/Contracts'),
            (DRIVE, 'D1'): _item('D1', 'Plan.docx', 'F2', path='/Contracts/2026'),
            (DRIVE, 'D2'): _item('D2', 'Outside.docx', 'ROOT-A', path=''),
            (DRIVE, 'F3'): _item('F3', 'HR', 'ROOT-A', folder=True, path=''),
            (OTHER_DRIVE, 'root'): _item('ROOT-B', 'root', None, drive=OTHER_DRIVE, folder=True),
            (OTHER_DRIVE, 'X1'): _item('X1', 'Secret.docx', 'ROOT-B', drive=OTHER_DRIVE),
        }
        self.items[(DRIVE, 'ROOT-A')] = self.items[(DRIVE, 'root')]
        self.items[(OTHER_DRIVE, 'ROOT-B')] = self.items[(OTHER_DRIVE, 'root')]
        self.contents = {'D1': BLANK_DOCX, 'D2': BLANK_DOCX}
        self.revoked = set()          # item ids Microsoft now refuses (403)
        self.download_host = 'contoso.sharepoint.com'
        self.web_url_override = {}
        self.codes = {}               # code -> challenge
        self.refresh_tokens = {'RT-1'}
        self.token_counter = 0
        self.token_error = None
        self.my_drive_id = 'b!onedrive-me'
        self.site_drives = {SITE: [DRIVE]}

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _res(url, status, body, headers=None):
        content = body if isinstance(body, bytes) else json.dumps(body).encode()
        return net.FetchResult(url, status, {'Content-Type': 'application/json', **(headers or {})},
                               content)

    def _err(self, url, status, code, message='error'):
        return self._res(url, status, {'error': {'code': code, 'message': message}})

    def sharing_calls(self):
        return [c for c in self.calls if SHARING_RE.search(urlsplit(c['url']).path)]

    def graph_calls(self, method=None):
        return [c for c in self.calls if urlsplit(c['url']).hostname == http.GRAPH_HOST
                and (method is None or c['method'] == method)]

    def _new_tokens(self, scope):
        self.token_counter += 1
        rt = f'RT-{self.token_counter + 1}'
        self.refresh_tokens.add(rt)
        return {'token_type': 'Bearer', 'scope': scope, 'expires_in': 3599,
                'ext_expires_in': 3599, 'access_token': f'AT-{self.token_counter}',
                'refresh_token': rt}

    # -- the fetch boundary ------------------------------------------------
    def __call__(self, url, endpoint, max_bytes, *, method='GET', headers=None, data=None,
                 timeout=None):
        # The endpoint office.net would use must be the URL's own host and public-only.
        assert endpoint.public_only and endpoint.verify_tls
        assert urlsplit(endpoint.browser_url).hostname == urlsplit(url).hostname
        self.calls.append({'method': method, 'url': url, 'headers': dict(headers or {}),
                           'data': data})
        parts = urlsplit(url)
        if parts.hostname == http.LOGIN_HOST:
            return self._token(url, parse_qs((data or b'').decode()))
        if parts.hostname == http.GRAPH_HOST:
            auth = (headers or {}).get('Authorization', '')
            if not auth.startswith('Bearer '):
                return self._err(url, 401, 'InvalidAuthenticationToken')
            return self._graph(url, method, parts, data)
        if parts.hostname.endswith('.sharepoint.com'):
            assert 'Authorization' not in (headers or {}), 'downloadUrl needs no bearer token'
            item_id = parse_qs(parts.query).get('UniqueId', [''])[0]
            return self._res(url, 200, self.contents.get(item_id, b''))
        raise AssertionError(f'unexpected host {parts.hostname}')

    def _token(self, url, form):
        g = form.get('grant_type', [''])[0]
        if self.token_error:
            return self._res(url, 400, {'error': self.token_error,
                                        'error_description': 'AADSTS70000: test.\r\nTrace ID: x'})
        if g == 'authorization_code':
            code = form['code'][0]
            challenge = self.codes.get(code)
            verifier = form.get('code_verifier', [''])[0]
            calc = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()) \
                .rstrip(b'=').decode()
            if challenge is None or calc != challenge:
                return self._res(url, 400, {'error': 'invalid_grant',
                                            'error_description': 'AADSTS501481: verifier'})
            del self.codes[code]
            return self._res(url, 200, self._new_tokens(form['scope'][0]))
        if g == 'refresh_token':
            rt = form['refresh_token'][0]
            if rt not in self.refresh_tokens:
                return self._res(url, 400, {'error': 'invalid_grant',
                                            'error_description': 'AADSTS70008: expired'})
            self.refresh_tokens.discard(rt)
            return self._res(url, 200, self._new_tokens(form['scope'][0]))
        if g == 'client_credentials':
            return self._res(url, 200, {'token_type': 'Bearer', 'expires_in': 3599,
                                        'access_token': 'APP-TOKEN'})
        return self._res(url, 400, {'error': 'unsupported_grant_type'})

    def _graph(self, url, method, parts, data):
        path = unquote(parts.path[len('/v1.0'):])
        if path == '/me/drive':
            return self._res(url, 200, {
                'id': self.my_drive_id, 'driveType': 'business', 'name': 'OneDrive',
                'webUrl': 'https://contoso-my.sharepoint.com/personal/tech_contoso_com/Documents',
                'owner': {'user': {'id': 'oid-1', 'displayName': 'Tech One'}}})
        m = re.match(r'^/sites/([^/]+)/drives$', path)
        if m:
            ids = self.site_drives.get(m.group(1), [])
            return self._res(url, 200, {'value': [{'id': d, 'name': f'Lib {d}',
                                                   'driveType': 'documentLibrary',
                                                   'webUrl': 'https://contoso.sharepoint.com/x'}
                                                  for d in ids]})
        m = re.match(r'^/sites/([^/:]+)(?::(/.*))?$', path)
        if m:
            return self._res(url, 200, {'id': SITE, 'displayName': 'Finance', 'name': 'Finance',
                                        'webUrl': 'https://contoso.sharepoint.com/sites/Finance'})
        m = re.match(r'^/drives/([^/]+)/(?:items/([^/:]+)|root):/([^/]+):/content$', path)
        if m and method == 'PUT':
            drive, parent, name = m.group(1), m.group(2) or 'root', m.group(3)
            q = parse_qs(parts.query)
            if q.get('@microsoft.graph.conflictBehavior') != ['fail']:
                return self._err(url, 400, 'invalidRequest', 'test requires fail')
            parent_item = self.items.get((drive, parent))
            if parent_item is None:
                return self._err(url, 404, 'itemNotFound')
            pid = parent_item['id']
            for (d, _), it in list(self.items.items()):
                if d == drive and it['name'] == name and \
                        it['parentReference'].get('id') == pid:
                    return self._err(url, 409, 'nameAlreadyExists',
                                     'The specified item name already exists.')
            new_id = f'N{len(self.items)}'
            item = _item(new_id, name, pid, drive=drive, size=len(data or b''))
            self.items[(drive, new_id)] = item
            self.contents[new_id] = data
            return self._res(url, 201, item)
        m = re.match(r'^/drives/([^/]+)(?:/(root|items/([^/]+)))?(/children)?$', path)
        if m and method == 'GET':
            drive = m.group(1)
            if m.group(2) is None:
                return self._res(url, 200, {'id': drive, 'name': f'Lib {drive}',
                                            'driveType': 'documentLibrary',
                                            'webUrl': 'https://contoso.sharepoint.com/lib'})
            key = (drive, 'root' if m.group(2) == 'root' else m.group(3))
            item = self.items.get(key)
            if item is None:
                return self._err(url, 404, 'itemNotFound')
            if item['id'] in self.revoked:
                return self._err(url, 403, 'accessDenied', 'Access denied')
            if m.group(4):
                kids = [it for (d, k), it in self.items.items()
                        if d == drive and k == it['id'] and
                        it['parentReference'].get('id') == item['id']]
                return self._res(url, 200, {'@odata.context': 'x', 'value': kids})
            out = dict(item)
            if item['id'] in self.web_url_override:
                out['webUrl'] = self.web_url_override[item['id']]
            if 'file' in item:
                out['@microsoft.graph.downloadUrl'] = (
                    f'https://{self.download_host}/sites/Finance/_layouts/15/download.aspx'
                    f'?UniqueId={item["id"]}&tempauth=TEMP')
            return self._res(url, 200, out)
        raise AssertionError(f'unexpected Graph call {method} {path}')


class M365DocsBase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.mkdtemp(prefix='m365docs-test-media-')
        cls._media_override = override_settings(MEDIA_ROOT=cls._media)
        cls._media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media_override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)
        super().tearDownClass()

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Org A', slug='m365-org-a')
        cls.other_org = Organization.objects.create(name='Org B', slug='m365-org-b')
        cls.owner = cls._member('m365-owner', cls.org, Role.OWNER)
        cls.editor = cls._member('m365-editor', cls.org, Role.EDITOR)
        cls.reader = cls._member('m365-reader', cls.org, Role.READONLY)
        cls.outsider = cls._member('m365-outsider', cls.other_org, Role.OWNER)

    @staticmethod
    def _member(name, org, role):
        user = User.objects.create_user(name, f'{name}@example.com', 'x')
        Membership.objects.create(user=user, organization=org, role=role, is_active=True)
        return user

    def setUp(self):
        self.ms = FakeMicrosoft()
        patcher = mock.patch.object(http, '_net_fetch', self.ms)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.conn = self.make_connection(self.org)

    def make_connection(self, org, **kw):
        c = M365Connection(organization=org, name=f'M365 {org.slug}', tenant_id=TENANT,
                           cached_data={'users': [1]}, docs_enabled=True,
                           docs_access='readwrite', docs_sharepoint='all',
                           docs_sharepoint_host='contoso.sharepoint.com')
        for k, v in kw.items():
            setattr(c, k, v)
        c.set_credentials({'client_id': 'app-id', 'client_secret': 'app-secret-value'})
        c.save()
        return c

    def grant(self, user, conn=None, **kw):
        conn = conn or self.conn
        g = M365DocsGrant(connection=conn, user=user, refresh_token='RT-1',
                          access_token='AT-0',
                          access_expires_at=timezone.now() + timedelta(minutes=30),
                          scopes='Files.ReadWrite Files.ReadWrite.All')
        for k, v in kw.items():
            setattr(g, k, v)
        g.save()
        return g

    def location(self, kind='folder', conn=None, **kw):
        conn = conn or self.conn
        defaults = {'folder': {'drive_id': DRIVE, 'item_id': 'F1', 'display_name': 'Contracts'},
                    'drive': {'drive_id': DRIVE, 'display_name': 'Finance docs'},
                    'site': {'site_id': SITE, 'display_name': 'Finance'},
                    'my_onedrive': {'display_name': 'OneDrive'}}[kind]
        defaults.update(kw)
        return M365AllowedLocation.objects.create(connection=conn,
                                                  organization_id=conn.organization_id,
                                                  kind=kind, **defaults)

    def login(self, user, org=None, client=None):
        client = client or self.client
        client.force_login(user)
        s = client.session
        s['current_organization_id'] = (org or self.org).pk
        s.save()
        return client


# ---------------------------------------------------------------------------
# Scopes never touch the tenant-read / mail token
# ---------------------------------------------------------------------------

class ScopeTests(M365DocsBase):
    def test_scope_sets_per_mode(self):
        self.assertEqual(scopes.short_scopes('read', 'none'), ['Files.Read', 'offline_access'])
        self.assertEqual(scopes.short_scopes('readwrite', 'none'),
                         ['Files.ReadWrite', 'offline_access'])
        self.assertEqual(scopes.short_scopes('read', 'all'),
                         ['Files.Read', 'Files.Read.All', 'offline_access'])
        self.assertEqual(scopes.short_scopes('readwrite', 'all'),
                         ['Files.ReadWrite', 'Files.ReadWrite.All', 'offline_access'])
        self.assertEqual(scopes.short_scopes('read', 'selected'),
                         ['Files.Read', 'Sites.Selected', 'offline_access'])
        for mode in scopes.all_modes():
            joined = ' '.join(mode['scopes'])
            self.assertNotIn('.Selected ', joined.replace('Sites.Selected', ''))
            for never in scopes.NEVER_REQUESTED + ('.default', 'Mail.', 'User.Read',
                                                   'Directory.', 'Sites.Read.All'):
                self.assertNotIn(never, joined)

    def test_request_scope_string_is_fully_qualified_and_has_no_default(self):
        s = scopes.request_scopes(self.conn)
        self.assertEqual(s, 'https://graph.microsoft.com/Files.ReadWrite '
                            'https://graph.microsoft.com/Files.ReadWrite.All offline_access')
        self.assertNotIn(scopes.TENANT_READ_SCOPE, s)

    def test_tenant_read_provider_still_requests_default_scope_only(self):
        from integrations.providers.m365 import M365Provider
        with mock.patch('integrations.providers.m365.requests.post') as post:
            post.return_value.json.return_value = {'access_token': 'x'}
            post.return_value.raise_for_status.return_value = None
            M365Provider(TENANT, 'app-id', 'secret')._get_token()
        self.assertEqual(post.call_args.kwargs['data']['scope'],
                         'https://graph.microsoft.com/.default')
        self.assertEqual(post.call_args.kwargs['data']['grant_type'], 'client_credentials')

    def test_missing_scopes(self):
        self.assertEqual(scopes.missing(self.conn, {'Files.ReadWrite'}), ['Files.ReadWrite.All'])
        self.assertEqual(scopes.missing(self.conn, {'files.readwrite', 'files.readwrite.all'}), [])
        ro = self.make_connection(self.other_org, docs_access='read', docs_sharepoint='all')
        self.assertEqual(scopes.missing(ro, {'Files.ReadWrite', 'Files.ReadWrite.All'}), [])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SettingsViewTests(M365DocsBase):
    def url(self, conn=None):
        return reverse('integrations:m365docs_settings', args=[(conn or self.conn).pk])

    def test_enabling_shows_exact_permissions_before_saving(self):
        conn = self.make_connection(self.other_org, docs_enabled=False)
        self.login(self.outsider, self.other_org)
        resp = self.client.post(self.url(conn), {'docs_enabled': 'on', 'docs_access': 'read',
                                                 'docs_sharepoint': 'selected'})
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        for s in ('Files.Read', 'Sites.Selected', 'offline_access'):
            self.assertIn(f'<code>{s}</code>', body)
        self.assertNotIn('<code>Files.ReadWrite</code>', body)
        self.assertIn('Sites.FullControl.All', body)
        conn.refresh_from_db()
        self.assertFalse(conn.docs_enabled)        # nothing saved yet

    def test_confirm_saves_only_document_columns(self):
        conn = self.make_connection(self.other_org, docs_enabled=False)
        before = (conn.encrypted_credentials, conn.tenant_id, conn.cached_data, conn.name)
        self.login(self.outsider, self.other_org)
        resp = self.client.post(self.url(conn), {
            'step': 'confirm', 'docs_enabled': 'on', 'docs_access': 'read',
            'docs_sharepoint': 'none', 'docs_sharepoint_host': 'contoso-my.sharepoint.com'})
        self.assertEqual(resp.status_code, 302)
        conn.refresh_from_db()
        self.assertTrue(conn.docs_enabled)
        self.assertEqual((conn.docs_access, conn.docs_sharepoint), ('read', 'none'))
        self.assertEqual(conn.docs_sharepoint_host, 'contoso.sharepoint.com')
        self.assertEqual((conn.encrypted_credentials, conn.tenant_id, conn.cached_data,
                          conn.name), before)
        self.assertEqual(conn.get_credentials()['client_secret'], 'app-secret-value')
        self.assertTrue(AuditLog.objects.filter(extra_data__office_event='m365_settings',
                                                object_id=conn.pk).exists())
        self.assertEqual(self.ms.calls, [])

    def test_disabling_deletes_stored_sign_ins(self):
        self.grant(self.owner)
        self.login(self.owner)
        self.client.post(self.url(), {'docs_access': 'read', 'docs_sharepoint': 'none'})
        self.conn.refresh_from_db()
        self.assertFalse(self.conn.docs_enabled)
        self.assertFalse(M365DocsGrant.objects.filter(connection=self.conn).exists())

    def test_bad_host_refused(self):
        self.login(self.owner)
        self.client.post(self.url(), {'step': 'confirm', 'docs_enabled': 'on',
                                      'docs_access': 'read', 'docs_sharepoint': 'none',
                                      'docs_sharepoint_host': 'evil.example.com'})
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.docs_sharepoint_host, 'contoso.sharepoint.com')

    def test_only_org_admins_with_configure(self):
        self.login(self.editor)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.login(self.outsider, self.other_org)
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.login(self.owner)
        resp = self.client.get(self.url())
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(b'onclick', resp.content)
        self.assertIn(b'Cloud Storage Partner Program', resp.content)

    def test_location_add_site_by_url_and_remove(self):
        self.grant(self.owner)
        self.login(self.owner)
        resp = self.client.post(reverse('integrations:m365docs_location_add', args=[self.conn.pk]),
                                {'kind': 'site_url',
                                 'site_url': 'https://contoso.sharepoint.com/sites/Finance'})
        self.assertEqual(resp.status_code, 302)
        loc = M365AllowedLocation.objects.get(connection=self.conn, kind='site')
        self.assertEqual(loc.site_id, SITE)
        self.assertEqual(loc.organization_id, self.org.pk)
        resp = self.client.post(reverse('integrations:m365docs_location_add', args=[self.conn.pk]),
                                {'kind': 'site_url', 'site_url': 'https://evil.example/sites/x'})
        self.assertEqual(M365AllowedLocation.objects.filter(connection=self.conn).count(), 1)
        self.client.post(reverse('integrations:m365docs_location_delete',
                                 args=[self.conn.pk, loc.pk]))
        self.assertFalse(M365AllowedLocation.objects.filter(pk=loc.pk).exists())
        events = set(AuditLog.objects.values_list('extra_data__office_event', flat=True))
        self.assertTrue({'m365_location_add', 'm365_location_remove'} <= events)

    def test_location_add_folder_must_be_a_folder(self):
        self.grant(self.owner)
        self.login(self.owner)
        url = reverse('integrations:m365docs_location_add', args=[self.conn.pk])
        self.client.post(url, {'kind': 'folder', 'drive_id': DRIVE, 'item_id': 'D1'})
        self.assertFalse(M365AllowedLocation.objects.exists())
        self.client.post(url, {'kind': 'folder', 'drive_id': DRIVE, 'item_id': 'F2'})
        self.assertTrue(M365AllowedLocation.objects.filter(kind='folder', item_id='F2').exists())
        resp = self.client.post(url, {'kind': 'folder', 'drive_id': DRIVE,
                                      'item_id': '../../me'})
        self.assertEqual(resp.status_code, 404)


# ---------------------------------------------------------------------------
# PKCE sign-in, token storage, refresh, disconnect
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class OAuthTests(M365DocsBase):
    def start(self, user=None, client=None):
        client = self.login(user or self.editor, client=client)
        resp = client.post(reverse('integrations:m365docs_connect', args=[self.conn.pk]))
        self.assertEqual(resp.status_code, 302)
        loc = urlsplit(resp['Location'])
        self.assertEqual(loc.hostname, 'login.microsoftonline.com')
        self.assertEqual(loc.path, f'/{TENANT}/oauth2/v2.0/authorize')
        return {k: v[0] for k, v in parse_qs(loc.query).items()}

    def callback(self, client=None, **params):
        return (client or self.client).get(reverse('integrations:m365docs_callback'), params)

    def test_authorize_request(self):
        q = self.start()
        self.assertEqual(q['response_type'], 'code')
        self.assertEqual(q['code_challenge_method'], 'S256')
        self.assertEqual(q['client_id'], 'app-id')
        self.assertEqual(q['scope'], scopes.request_scopes(self.conn))
        self.assertNotIn('.default', q['scope'])
        self.assertGreaterEqual(len(q['state']), 40)
        self.assertTrue(q['redirect_uri'].endswith('/integrations/m365/documents/callback/'))
        self.assertNotIn('client_secret', q)
        self.assertEqual(self.ms.calls, [])

    def test_full_flow_stores_encrypted_tokens(self):
        q = self.start()
        self.ms.codes['CODE-1'] = q['code_challenge']
        resp = self.callback(code='CODE-1', state=q['state'])
        self.assertEqual(resp.status_code, 302)
        grant = M365DocsGrant.objects.get(connection=self.conn, user=self.editor)
        self.assertEqual(grant.refresh_token, 'RT-2')
        self.assertEqual(grant.access_token, 'AT-1')
        self.assertIn('Files.ReadWrite.All', grant.scope_set)
        self.assertEqual(grant.ms_display_name, 'Tech One')
        token_call = [c for c in self.ms.calls if c['url'].endswith('/oauth2/v2.0/token')][0]
        form = parse_qs(token_call['data'].decode())
        self.assertEqual(form['grant_type'], ['authorization_code'])
        self.assertIn('code_verifier', form)
        with db_connection.cursor() as cur:
            cur.execute('SELECT refresh_token, access_token FROM m365_docs_grants WHERE id=%s',
                        [grant.pk])
            raw_rt, raw_at = cur.fetchone()
        self.assertTrue(raw_rt.startswith('enc2$') and raw_at.startswith('enc2$'))
        self.assertNotIn('RT-2', raw_rt)
        self.assertTrue(AuditLog.objects.filter(extra_data__office_event='m365_connect').exists())
        self.assertFalse(any('RT-2' in json.dumps(a.extra_data) or 'RT-2' in a.description
                             for a in AuditLog.objects.all()))

    def test_state_is_single_use_and_bound(self):
        q = self.start()
        self.ms.codes['CODE-1'] = q['code_challenge']
        self.callback(code='CODE-1', state='not-the-state')
        self.assertFalse(M365DocsGrant.objects.exists())
        self.assertEqual(self.ms.calls, [])          # no token request on a bad state
        self.callback(code='CODE-1', state=q['state'])
        self.assertTrue(M365DocsGrant.objects.exists())
        M365DocsGrant.objects.all().delete()
        self.ms.codes['CODE-1'] = q['code_challenge']
        self.callback(code='CODE-1', state=q['state'])   # replay
        self.assertFalse(M365DocsGrant.objects.exists())

    def test_state_from_another_session_is_refused(self):
        q = self.start()
        self.ms.codes['CODE-1'] = q['code_challenge']
        other = self.login(self.owner, client=Client())
        self.callback(client=other, code='CODE-1', state=q['state'])
        self.assertFalse(M365DocsGrant.objects.exists())

    def test_expired_state_and_wrong_verifier(self):
        q = self.start()
        self.ms.codes['CODE-1'] = q['code_challenge']
        s = self.client.session
        s[oauth.SESSION_KEY][q['state']]['t'] -= oauth.STATE_TTL + 5
        s.save()
        self.callback(code='CODE-1', state=q['state'])
        self.assertFalse(M365DocsGrant.objects.exists())
        q = self.start()
        self.ms.codes['CODE-2'] = 'a-different-challenge'
        self.callback(code='CODE-2', state=q['state'])
        self.assertFalse(M365DocsGrant.objects.exists())

    def test_microsoft_error_is_shown_without_token_call(self):
        q = self.start()
        resp = self.callback(state=q['state'], error='access_denied',
                             error_description='AADSTS65004: User declined to consent.')
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(M365DocsGrant.objects.exists())
        self.assertEqual(self.ms.calls, [])

    def test_connect_requires_post_with_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        self.login(self.editor, client=csrf_client)
        url = reverse('integrations:m365docs_connect', args=[self.conn.pk])
        self.assertEqual(csrf_client.get(url).status_code, 405)
        self.assertEqual(csrf_client.post(url).status_code, 403)

    def test_connect_needs_docs_view_in_that_org(self):
        self.login(self.outsider, self.other_org)
        resp = self.client.post(reverse('integrations:m365docs_connect', args=[self.conn.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_refresh_rotates_and_invalid_grant_disconnects(self):
        g = self.grant(self.editor, access_expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(oauth.access_token(g), 'AT-1')
        g.refresh_from_db()
        self.assertEqual(g.refresh_token, 'RT-2')
        form = parse_qs(self.ms.calls[-1]['data'].decode())
        self.assertEqual(form['grant_type'], ['refresh_token'])
        self.assertEqual(form['scope'], [scopes.request_scopes(self.conn)])
        # Valid access token: no call.
        n = len(self.ms.calls)
        self.assertEqual(oauth.access_token(g), 'AT-1')
        self.assertEqual(len(self.ms.calls), n)
        # Revoked at Microsoft.
        g.access_expires_at = timezone.now() - timedelta(seconds=1)
        g.refresh_token = 'RT-unknown'
        g.save()
        with self.assertRaises(oauth.NotConnected):
            oauth.access_token(g)
        self.assertFalse(M365DocsGrant.objects.filter(pk=g.pk).exists())

    def test_disconnect_deletes_tokens(self):
        g = self.grant(self.editor)
        self.login(self.editor)
        resp = self.client.post(reverse('integrations:m365docs_disconnect', args=[self.conn.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(M365DocsGrant.objects.filter(pk=g.pk).exists())
        self.assertTrue(AuditLog.objects.filter(extra_data__office_event='m365_disconnect',
                                                user=self.editor).exists())


# ---------------------------------------------------------------------------
# Allowed locations
# ---------------------------------------------------------------------------

class AllowedLocationTests(M365DocsBase):
    def client_for(self, user=None):
        return graph.GraphClient(self.grant(user or self.editor))

    def test_folder_allows_descendants_only(self):
        loc = self.location('folder')
        c = self.client_for()
        found, meta = access.locate(c, self.conn, DRIVE, 'D1')
        self.assertEqual((found, meta['id']), (loc, 'D1'))
        for outside in ('D2', 'F3', 'root'):
            with self.assertRaises(access.NotPermitted):
                access.locate(c, self.conn, DRIVE, outside)
        with self.assertRaises(access.NotPermitted):
            access.locate(c, self.conn, OTHER_DRIVE, 'X1')

    def test_drive_and_site_and_onedrive(self):
        c = self.client_for()
        with self.assertRaises(access.NotPermitted):
            access.locate(c, self.conn, DRIVE, 'D2')
        site = self.location('site')
        self.assertEqual(access.locate(c, self.conn, DRIVE, 'D2')[0], site)
        with self.assertRaises(access.NotPermitted):
            access.locate(c, self.conn, OTHER_DRIVE, 'X1')
        site.delete()
        self.location('my_onedrive')
        with self.assertRaises(access.NotPermitted):
            access.locate(c, self.conn, DRIVE, 'D2')
        self.ms.my_drive_id = OTHER_DRIVE
        c = graph.GraphClient(M365DocsGrant.objects.get(user=self.editor))
        self.assertEqual(access.locate(c, self.conn, OTHER_DRIVE, 'X1')[0].kind, 'my_onedrive')

    def test_ids_are_validated_before_any_call(self):
        self.location('drive')
        c = self.client_for()
        for bad in ('../root', 'a/b', 'x:/y', 'a?b', '', 'é', 'a' * 301, 'a..b'):
            with self.assertRaises(ValueError, msg=bad):
                access.locate(c, self.conn, bad if bad else '', 'D1')
            with self.assertRaises(ValueError, msg=bad):
                access.locate(c, self.conn, DRIVE, bad or '..')
        self.assertEqual(self.ms.graph_calls(), [])

    def test_location_of_another_connection_is_ignored(self):
        other = self.make_connection(self.other_org)
        foreign = self.location('drive', conn=other)
        c = self.client_for()
        with self.assertRaises(access.NotPermitted):
            access.locate(c, self.conn, DRIVE, 'D1')
        with self.assertRaises(access.NotPermitted):
            access.locate(c, self.conn, DRIVE, 'D1', location=foreign)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class BrowseViewTests(M365DocsBase):
    def test_browse_lists_permitted_folder_and_refuses_outside(self):
        loc = self.location('folder')
        self.grant(self.editor)
        self.login(self.editor)
        url = reverse('integrations:m365docs_browse', args=[self.conn.pk])
        resp = self.client.get(url, {'loc': loc.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '2026')
        self.assertNotContains(resp, 'HR')
        self.assertNotContains(resp, 'onclick')
        resp = self.client.get(url, {'loc': loc.pk, 'drive': DRIVE, 'item': 'F2'})
        self.assertContains(resp, 'Plan.docx')
        # Outside the folder: refused, nothing listed.
        before = len(self.ms.calls)
        resp = self.client.get(url, {'loc': loc.pk, 'drive': DRIVE, 'item': 'F3'})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse([c for c in self.ms.calls[before:] if c['url'].endswith('/children')
                          or '/children?' in c['url']])
        resp = self.client.get(url, {'loc': loc.pk, 'drive': OTHER_DRIVE, 'item': 'root'})
        self.assertEqual(resp.status_code, 302)
        resp = self.client.get(url, {'loc': loc.pk, 'drive': DRIVE, 'item': '../F3'})
        self.assertEqual(resp.status_code, 404)

    def test_other_tenant_cannot_browse_or_use_locations(self):
        loc = self.location('drive')
        self.grant(self.outsider)
        self.login(self.outsider, self.other_org)
        resp = self.client.get(reverse('integrations:m365docs_browse', args=[self.conn.pk]),
                               {'loc': loc.pk})
        self.assertEqual(resp.status_code, 404)
        other = self.make_connection(self.other_org)
        self.grant(self.outsider, conn=other)
        resp = self.client.get(reverse('integrations:m365docs_browse', args=[other.pk]),
                               {'loc': loc.pk})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(self.ms.graph_calls(), [])

    def test_disabled_capability_hides_everything(self):
        self.location('drive')
        self.grant(self.editor)
        M365Connection.objects.filter(pk=self.conn.pk).update(docs_enabled=False)
        self.login(self.editor)
        resp = self.client.get(reverse('integrations:m365docs_browse', args=[self.conn.pk]),
                               {'loc': 1})
        self.assertEqual(resp.status_code, 404)
        resp = self.client.get(reverse('docs:document_list'))
        self.assertNotContains(resp, reverse('integrations:m365docs_home'))


# ---------------------------------------------------------------------------
# Link, open, unlink
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class LinkOpenTests(M365DocsBase):
    def setUp(self):
        super().setUp()
        self.loc = self.location('folder')
        self.grant(self.editor)
        # Written by the customer's editor: customer users only reach their
        # own or client-visible articles (authz-tech).
        self.doc = Document.objects.create(organization=self.org, title='Runbook', slug='runbook',
                                           body='x', content_type='html', created_by=self.editor)

    def link(self, item='D1', parent='org', user=None):
        self.login(user or self.editor)
        return self.client.post(reverse('integrations:m365docs_link', args=[self.conn.pk]),
                                {'drive': DRIVE, 'item': item, 'for': parent})

    def test_link_stores_reference_only(self):
        resp = self.link(parent=f'doc:{self.doc.pk}')
        self.assertEqual(resp.status_code, 302)
        row = LinkedCloudDocument.objects.get()
        self.assertEqual((row.drive_id, row.item_id, row.name, row.document_id, row.organization_id),
                         (DRIVE, 'D1', 'Plan.docx', self.doc.pk, self.org.pk))
        self.assertTrue(row.etag)
        self.assertTrue(row.web_url.startswith('https://contoso.sharepoint.com/'))
        self.assertEqual(self.ms.graph_calls('PUT'), [])
        self.assertTrue(AuditLog.objects.filter(extra_data__office_event='m365_link',
                                                action='create').exists())
        resp = self.client.get(reverse('docs:document_detail', args=[self.doc.slug]))
        self.assertContains(resp, 'Open in Microsoft 365')
        self.assertContains(resp, 'target="_blank"')
        self.assertNotContains(resp, 'onclick')

    def test_link_outside_allowlist_refused(self):
        self.link(item='D2')
        self.assertFalse(LinkedCloudDocument.objects.exists())

    def test_link_needs_edit_permission_on_parent(self):
        self.grant(self.reader)
        self.link(user=self.reader)
        self.assertFalse(LinkedCloudDocument.objects.exists())

    def test_parent_from_other_org_is_404(self):
        foreign = Document.objects.create(organization=self.other_org, title='B', slug='b',
                                          body='x', content_type='html')
        resp = self.link(parent=f'doc:{foreign.pk}')
        self.assertEqual(resp.status_code, 404)

    def test_open_fetches_fresh_web_url(self):
        self.link()
        row = LinkedCloudDocument.objects.get()
        self.ms.web_url_override['D1'] = 'https://contoso.sharepoint.com/:w:/r/sites/Finance/new'
        resp = self.client.post(reverse('integrations:m365docs_open', args=[row.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], 'https://contoso.sharepoint.com/:w:/r/sites/Finance/new')
        # core.security_headers_middleware sets the site-wide Referrer-Policy;
        # the form's rel="noreferrer" keeps the referrer off the new tab.
        self.assertEqual(resp['Cache-Control'], 'no-store')
        self.assertTrue(AuditLog.objects.filter(extra_data__office_event='m365_open',
                                                action='read', success=True).exists())

    def test_open_fails_when_microsoft_revokes_access(self):
        self.link()
        row = LinkedCloudDocument.objects.get()
        self.ms.revoked.add('D1')
        resp = self.client.post(reverse('integrations:m365docs_open', args=[row.pk]),
                                HTTP_REFERER='/docs/')
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(resp['Location'].startswith('https://contoso'))
        self.assertTrue(AuditLog.objects.filter(extra_data__office_event='m365_open',
                                                success=False).exists())

    def test_open_refuses_web_url_off_tenant(self):
        self.link()
        row = LinkedCloudDocument.objects.get()
        self.ms.web_url_override['D1'] = 'https://evil.example/phish'
        resp = self.client.post(reverse('integrations:m365docs_open', args=[row.pk]))
        self.assertNotIn('evil.example', resp['Location'])
        self.ms.web_url_override['D1'] = 'https://fabrikam.sharepoint.com/x'
        resp = self.client.post(reverse('integrations:m365docs_open', args=[row.pk]))
        self.assertNotIn('fabrikam', resp['Location'])

    def test_open_rechecks_allowlist(self):
        self.link()
        row = LinkedCloudDocument.objects.get()
        self.loc.delete()
        resp = self.client.post(reverse('integrations:m365docs_open', args=[row.pk]))
        self.assertNotIn('sharepoint.com', resp['Location'])

    def test_other_tenant_cannot_open_or_unlink(self):
        self.link()
        row = LinkedCloudDocument.objects.get()
        self.grant(self.outsider)
        self.login(self.outsider, self.other_org)
        for name in ('m365docs_open', 'm365docs_unlink'):
            self.assertEqual(self.client.post(reverse(f'integrations:{name}', args=[row.pk]))
                             .status_code, 404)
        self.assertTrue(LinkedCloudDocument.objects.filter(pk=row.pk).exists())

    def test_unlink_leaves_microsoft_untouched(self):
        self.link()
        row = LinkedCloudDocument.objects.get()
        n = len(self.ms.calls)
        self.client.post(reverse('integrations:m365docs_unlink', args=[row.pk]))
        self.assertFalse(LinkedCloudDocument.objects.exists())
        self.assertEqual(len(self.ms.calls), n)
        self.assertTrue(AuditLog.objects.filter(extra_data__office_event='m365_unlink',
                                                action='delete').exists())

    def test_ticket_links_are_staff_only(self):
        from psa.models import Ticket
        ticket = mock.Mock(pk=1, organization_id=self.org.pk, ticket_number='PSA-1')
        p = access.Parent('ticket', self.org.pk, ticket)
        self.assertFalse(p.can_view(self.reader))
        su = User.objects.create_superuser('m365-su', 'su@example.com', 'x')
        self.assertTrue(p.can_view(su))
        self.assertTrue(Ticket)  # model importable; full ticket pages are covered by psa tests

    def test_never_calls_sharing_endpoints(self):
        self.link()
        row = LinkedCloudDocument.objects.get()
        self.client.post(reverse('integrations:m365docs_open', args=[row.pk]))
        self.client.get(reverse('integrations:m365docs_browse', args=[self.conn.pk]),
                        {'loc': self.loc.pk})
        self.assertTrue(self.ms.calls)
        self.assertEqual(self.ms.sharing_calls(), [])
        for path in ('/drives/x/items/y/createLink', '/drives/x/items/y/invite',
                     '/drives/x/items/y/permissions', '/shares/u!abc/driveItem',
                     '/drives/x/items/y/preview', '/sites/s/permissions'):
            with self.assertRaises(http.RefusedURL):
                http.check(http.GRAPH_BASE + path, {http.GRAPH_HOST})


# ---------------------------------------------------------------------------
# Create, import, export
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class CreateImportExportTests(M365DocsBase):
    def setUp(self):
        super().setUp()
        self.loc = self.location('folder')
        self.grant(self.editor)
        self.login(self.editor)

    def as_owner(self):
        self.grant(self.owner)
        self.login(self.owner)

    def create(self, title='Budget', folder='F2', fmt='docx'):
        return self.client.post(reverse('integrations:m365docs_create', args=[self.conn.pk]),
                                {'loc': self.loc.pk, 'drive': DRIVE, 'folder': folder,
                                 'fmt': fmt, 'title': title, 'for': 'org'})

    def test_create_uses_conflict_fail_and_blank_template(self):
        resp = self.create()
        self.assertEqual(resp.status_code, 302)
        put = self.ms.graph_calls('PUT')
        self.assertEqual(len(put), 1)
        parts = urlsplit(put[0]['url'])
        self.assertEqual(unquote(parts.path), f'/v1.0/drives/{DRIVE}/items/F2:/Budget.docx:/content')
        self.assertEqual(parse_qs(parts.query), {'@microsoft.graph.conflictBehavior': ['fail']})
        self.assertEqual(put[0]['data'], BLANK_DOCX)
        link = LinkedCloudDocument.objects.get()
        self.assertEqual(link.name, 'Budget.docx')
        self.assertTrue(AuditLog.objects.filter(extra_data__office_event='m365_create',
                                                extra_data__conflict_behavior='fail').exists())

    def test_create_never_replaces(self):
        self.create()
        self.create()
        self.assertEqual(len(self.ms.graph_calls('PUT')), 2)
        self.assertEqual(LinkedCloudDocument.objects.count(), 1)
        self.assertEqual(sum(1 for it in self.ms.items.values() if it['name'] == 'Budget.docx'), 1)

    def test_create_outside_allowlist_or_read_only_refused(self):
        self.create(folder='F3')
        self.assertEqual(self.ms.graph_calls('PUT'), [])
        M365Connection.objects.filter(pk=self.conn.pk).update(docs_access='read')
        self.create()
        self.assertEqual(self.ms.graph_calls('PUT'), [])
        self.assertFalse(LinkedCloudDocument.objects.exists())

    def test_names_cannot_change_the_graph_path(self):
        for bad in ('a/b.docx', '..', 'x:y.docx', 'con<t.docx', '.hidden', 'a#b.docx',
                    '~$lock.docx', 'a%2fb.docx', ''):
            with self.assertRaises(ValueError, msg=bad):
                graph.valid_name(bad)
        self.create(title='../../me/drive/root:/x')     # sanitised to a plain name
        put = self.ms.graph_calls('PUT')
        self.assertEqual(len(put), 1)
        path = unquote(urlsplit(put[0]['url']).path)
        self.assertEqual(path, f'/v1.0/drives/{DRIVE}/items/F2:/x.docx:/content')

    def test_import_shows_destination_then_creates_revision(self):
        url = reverse('integrations:m365docs_import', args=[self.conn.pk])
        resp = self.client.get(url, {'drive': DRIVE, 'item': 'D1'})
        self.assertContains(resp, 'Org A')
        self.assertContains(resp, 'Contracts / Plan.docx')
        self.assertFalse(Document.objects.filter(content_type='file').exists())
        resp = self.client.post(url, {'drive': DRIVE, 'item': 'D1', 'title': 'Plan.docx'})
        self.assertEqual(resp.status_code, 302)
        doc = Document.objects.get(content_type='file')
        self.assertEqual(doc.organization, self.org)
        rev = FileRevision.objects.get(document=doc)
        self.assertEqual((rev.revision_number, rev.source), (1, 'import'))
        self.assertEqual(rev.sha256, hashlib.sha256(BLANK_DOCX).hexdigest())
        dl = [c for c in self.ms.calls if urlsplit(c['url']).hostname == 'contoso.sharepoint.com']
        self.assertEqual(len(dl), 1)
        self.assertNotIn('Authorization', dl[0]['headers'])
        entry = AuditLog.objects.get(extra_data__office_event='m365_import')
        self.assertEqual(entry.action, 'import')
        self.assertNotIn('tempauth', json.dumps(entry.extra_data))

    def test_import_refuses_download_url_off_tenant(self):
        self.ms.download_host = 'evil.example'
        self.client.post(reverse('integrations:m365docs_import', args=[self.conn.pk]),
                         {'drive': DRIVE, 'item': 'D1'})
        self.assertFalse(Document.objects.filter(content_type='file').exists())
        self.assertFalse([c for c in self.ms.calls if 'evil.example' in c['url']])

    def test_import_outside_allowlist_or_without_docs_create(self):
        url = reverse('integrations:m365docs_import', args=[self.conn.pk])
        self.client.post(url, {'drive': DRIVE, 'item': 'D2'})
        self.assertFalse(Document.objects.filter(content_type='file').exists())
        self.grant(self.reader)
        self.login(self.reader)
        self.client.post(url, {'drive': DRIVE, 'item': 'D1'})
        self.assertFalse(Document.objects.filter(content_type='file').exists())

    def _local_doc(self):
        # Created by an owner, so it is published and visible to the exporter.
        from office import creation
        self.as_owner()
        return creation.new_document(self.org, 'docx', 'Local', self.owner)

    def test_export_shows_destination_and_uploads_copy(self):
        target = self._local_doc()
        url = reverse('integrations:m365docs_export', args=[self.conn.pk])
        params = {'export': f'doc:{target.pk}', 'loc': self.loc.pk, 'drive': DRIVE,
                  'folder': 'F2'}
        resp = self.client.get(url, params)
        self.assertContains(resp, '2026')
        self.assertContains(resp, 'Local.docx')
        self.assertEqual(self.ms.graph_calls('PUT'), [])
        resp = self.client.post(url, {**params, 'name': 'Local.docx'})
        self.assertEqual(resp.status_code, 302)
        put = self.ms.graph_calls('PUT')
        self.assertEqual(len(put), 1)
        self.assertIn('conflictBehavior=fail', put[0]['url'])
        with storage.open_revision(storage.current(target)) as fh:
            self.assertEqual(put[0]['data'], fh.read())
        entry = AuditLog.objects.get(extra_data__office_event='m365_export')
        self.assertEqual(entry.action, 'export')

    def test_export_outside_allowlist_or_other_tenant_refused(self):
        target = self._local_doc()
        url = reverse('integrations:m365docs_export', args=[self.conn.pk])
        self.client.post(url, {'export': f'doc:{target.pk}', 'loc': self.loc.pk,
                               'drive': DRIVE, 'folder': 'F3', 'name': 'x.docx'})
        self.assertEqual(self.ms.graph_calls('PUT'), [])
        # A file of another organization cannot be exported through this connection.
        from office import creation
        foreign = creation.new_document(self.other_org, 'docx', 'Foreign', self.outsider)
        resp = self.client.post(url, {'export': f'doc:{foreign.pk}', 'loc': self.loc.pk,
                                      'drive': DRIVE, 'folder': 'F2', 'name': 'x.docx'})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(self.ms.graph_calls('PUT'), [])
        self.assertEqual(self.ms.sharing_calls(), [])

    def test_office_file_page_offers_export(self):
        target = self._local_doc()
        resp = self.client.get(reverse('office:target_detail', args=['doc', target.pk]))
        self.assertContains(resp, 'Export a copy to Microsoft 365')


# ---------------------------------------------------------------------------
# Network rules
# ---------------------------------------------------------------------------

class HttpRuleTests(TestCase):
    def test_hosts(self):
        self.assertTrue(http.is_allowed('https://graph.microsoft.com/v1.0/me/drive',
                                        {http.GRAPH_HOST}))
        for bad in ('http://graph.microsoft.com/v1.0/me', 'https://graph.microsoft.com:8443/x',
                    'https://user@graph.microsoft.com/x', 'https://graph.microsoft.com.evil/x',
                    'https://evil.example/x', 'https://169.254.169.254/latest'):
            self.assertFalse(http.is_allowed(bad, {http.GRAPH_HOST}), bad)

    def test_sharepoint_hosts(self):
        conn = M365Connection(docs_sharepoint_host='contoso.sharepoint.com')
        self.assertEqual(http.sharepoint_hosts(conn),
                         {'contoso.sharepoint.com', 'contoso-my.sharepoint.com'})
        self.assertEqual(http.sharepoint_hosts(M365Connection(docs_sharepoint_host='')), set())
        self.assertFalse(http.valid_sharepoint_host('contoso.sharepoint.com.evil.net'))
        self.assertEqual(http.tenant_prefix('contoso-my.sharepoint.com'), 'contoso')

    def test_private_dns_answer_for_graph_is_refused(self):
        def fake_dns(host, port, *a, **k):
            return [(2, 1, 6, '', ('10.0.0.5', port))]
        with mock.patch.object(net, '_getaddrinfo', fake_dns):
            with self.assertRaises(net.DestinationNotAllowed):
                http.send('GET', 'https://graph.microsoft.com/v1.0/me/drive',
                          allowed_hosts={http.GRAPH_HOST})

    def test_public_only_flag_does_not_change_editor_instances(self):
        editor = mock.Mock(mode='separate_server', spec=['mode'])
        self.assertTrue(net.ip_allowed('10.0.0.5', editor))
        self.assertFalse(net.ip_allowed('10.0.0.5', http.MicrosoftEndpoint('graph.microsoft.com')))
        self.assertFalse(net.ip_allowed('127.0.0.1', http.MicrosoftEndpoint('graph.microsoft.com')))
