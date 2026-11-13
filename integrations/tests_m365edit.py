"""Edit in Microsoft 365 (integrations/m365docs/editing.py).

Microsoft is the fake from tests_m365docs (office.net.fetch boundary), with
the extra Graph calls this feature makes: create a folder, read a child by
path, DELETE an item (If-Match honoured), and a content tag (cTag) that
changes when the content changes. Every clientst0r check above that layer
runs for real.

These prove clientst0r's side only; a real tenant has not been used.
"""
import hashlib
import io
import json
import logging
import re
import zipfile
from datetime import timedelta
from unittest import mock
from urllib.parse import parse_qs, unquote, urlsplit

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.template import Context, Template
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role, RoleTemplate
from audit.models import AuditLog
from integrations.m365docs import editing, http
from integrations.models import M365Connection, M365EditSession
from office import creation, storage
from office.models import FileRevision, QuarantinedSave

from .tests_m365docs import (BLANK_DOCX, DRIVE, TEST_MIDDLEWARE, FakeMicrosoft, M365DocsBase,
                             _item)


def edited_docx(text='Edited in Microsoft 365'):
    """The blank .docx with a paragraph of text: a different, valid package."""
    src = zipfile.ZipFile(io.BytesIO(BLANK_DOCX))
    out = io.BytesIO()
    with src, zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename == 'word/document.xml':
                data = re.sub(rb'(<w:body>)', rb'\1<w:p><w:r><w:t>' + text.encode() +
                              rb'</w:t></w:r></w:p>', data, count=1)
            dst.writestr(info, data)
    return out.getvalue()


class FakeMicrosoftEdit(FakeMicrosoft):
    def __init__(self):
        super().__init__()
        self.versions = {}           # item id -> content version (cTag / eTag counter)
        self.items[(self.my_drive_id, 'root')] = _item('ROOT-ME', 'root', None,
                                                       drive=self.my_drive_id, folder=True)
        self.items[(self.my_drive_id, 'ROOT-ME')] = self.items[(self.my_drive_id, 'root')]

    def _tags(self, item):
        v = self.versions.setdefault(item['id'], 1)
        item['eTag'] = f'"{{{item["id"]}}},{v}"'
        if 'file' in item:
            item['cTag'] = f'"c:{{{item["id"]}}},{v}"'
        return item

    def edit(self, item_id, data, by='Someone Else'):
        """A save in Office for the web: new content, new cTag and eTag."""
        self.contents[item_id] = data
        self.versions[item_id] = self.versions.get(item_id, 1) + 1
        for it in self.items.values():
            if it['id'] == item_id:
                it['size'] = len(data)
                it['lastModifiedBy'] = {'user': {'displayName': by}}

    def find(self, item_id):
        return next((it for it in self.items.values() if it['id'] == item_id), None)

    def _graph(self, url, method, parts, data):
        path = unquote(parts.path[len('/v1.0'):])
        m = re.match(r'^/drives/([^/]+)/(?:items/([^/:]+)|root)/children$', path)
        if m and method == 'POST':
            drive, parent = m.group(1), m.group(2) or 'root'
            body = json.loads(data)
            if body.get('@microsoft.graph.conflictBehavior') != 'fail':
                return self._err(url, 400, 'invalidRequest', 'test requires fail')
            pid = self.items[(drive, parent)]['id']
            for (d, _), it in self.items.items():
                if d == drive and it['name'] == body['name'] and \
                        it['parentReference'].get('id') == pid:
                    return self._err(url, 409, 'nameAlreadyExists')
            new_id = f'FOLDER{len(self.items)}'
            item = _item(new_id, body['name'], pid, drive=drive, folder=True)
            self.items[(drive, new_id)] = item
            return self._res(url, 201, item)
        m = re.match(r'^/drives/([^/]+)/(?:items/([^/:]+)|root):/([^/:]+)$', path)
        if m and method == 'GET':
            drive, parent, name = m.group(1), m.group(2) or 'root', m.group(3)
            pid = self.items[(drive, parent)]['id']
            for (d, _), it in self.items.items():
                if d == drive and it['name'] == name and it['parentReference'].get('id') == pid:
                    return self._res(url, 200, self._tags(dict(it)))
            return self._err(url, 404, 'itemNotFound')
        m = re.match(r'^/drives/([^/]+)/items/([^/]+)$', path)
        if m and method == 'DELETE':
            key = (m.group(1), m.group(2))
            item = self.items.get(key)
            if item is None:
                return self._err(url, 404, 'itemNotFound')
            want = (self.calls[-1]['headers'] or {}).get('If-Match')
            if want and want != self._tags(item)['eTag']:
                return self._err(url, 412, 'preconditionFailed')
            del self.items[key]
            return self._res(url, 204, b'')
        res = super()._graph(url, method, parts, data)
        try:
            body = json.loads(res.content)
        except ValueError:
            return res
        if isinstance(body, dict) and 'id' in body and 'parentReference' in body:
            stored = self.find(body['id'])
            if stored is not None:
                self._tags(stored)
                body['eTag'], body['size'] = stored['eTag'], stored['size']
                if 'cTag' in stored:
                    body['cTag'] = stored['cTag']
                if 'lastModifiedBy' in stored:
                    body['lastModifiedBy'] = stored['lastModifiedBy']
            return self._res(url, res.status_code, body)
        return res


def _make_staff(user):
    from accounts.models import UserProfile, UserType
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.user_type = UserType.STAFF
    profile.save()
    user.profile = profile
    return user


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class EditBase(M365DocsBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tech = cls._member('m365-tech', cls.org, Role.EDITOR)
        _make_staff(cls.tech)
        cls.tech2 = cls._member('m365-tech2', cls.org, Role.EDITOR)
        _make_staff(cls.tech2)

    def setUp(self):
        self.ms = FakeMicrosoftEdit()
        patcher = mock.patch.object(http, '_net_fetch', self.ms)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.conn = self.make_connection(self.org)
        self.loc = self.location('drive')
        M365Connection.objects.filter(pk=self.conn.pk).update(
            docs_edit_enabled=True, docs_edit_location=self.loc)
        self.conn.refresh_from_db()
        self.target = creation.new_document(self.org, 'docx', 'Runbook', self.owner)
        self.grant(self.tech)

    def tearDown(self):
        # No sharing, invitation or permission endpoint is ever called.
        self.assertEqual(self.ms.sharing_calls(), [])
        super().tearDown()

    def start(self, user=None, target=None, conn=None):
        self.login(user or self.tech)
        t = target or self.target
        return self.client.post(reverse('integrations:m365edit_start', args=[t.code, t.pk]),
                                {'connection': (conn or self.conn).pk})

    def session(self):
        return M365EditSession.objects.get(state='open')

    def post(self, name, session, **data):
        return self.client.post(reverse(f'integrations:m365edit_{name}', args=[session.pk]), data)

    def revisions(self):
        return list(FileRevision.objects.filter(document=self.target.obj)
                    .order_by('revision_number'))


class RoundTripTests(EditBase):
    def test_full_round_trip(self):
        resp = self.start()
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp['Location'].startswith('https://contoso.sharepoint.com/'))
        self.assertEqual(resp['Referrer-Policy'], 'no-referrer')
        s = self.session()
        base = storage.current(self.target)
        self.assertEqual((s.user, s.organization_id, s.connection, s.document_id),
                         (self.tech, self.org.pk, self.conn, self.target.pk))
        self.assertEqual((s.base_revision_number, s.base_sha256), (1, base.sha256))
        self.assertEqual(s.working_copy, 'present')
        self.assertTrue(s.item_id and s.uploaded_etag and s.synced_ctag)
        # The working copy went into a folder created with conflictBehavior=fail.
        posts = self.ms.graph_calls('POST')
        self.assertEqual(len(posts), 1)
        self.assertEqual(json.loads(posts[0]['data'])['name'], 'clientst0r working copies')
        put = self.ms.graph_calls('PUT')
        self.assertEqual(len(put), 1)
        self.assertEqual(parse_qs(urlsplit(put[0]['url']).query),
                         {'@microsoft.graph.conflictBehavior': ['fail']})
        self.assertIn(f'/items/{s.folder_id}:/Runbook (clientst0r edit).docx:/content',
                      unquote(put[0]['url']))
        with storage.open_revision(base) as fh:
            self.assertEqual(put[0]['data'], fh.read())

        # Someone edits in Office for the web.
        new = edited_docx()
        self.ms.edit(s.item_id, new)
        self.post('check', s)
        s.refresh_from_db()
        self.assertTrue(s.remote_changed)
        self.assertEqual(len(self.revisions()), 1)      # checking imports nothing

        resp = self.post('save', s)
        self.assertEqual(resp.status_code, 302)
        revs = self.revisions()
        self.assertEqual([r.revision_number for r in revs], [1, 2])
        self.assertEqual(revs[1].sha256, hashlib.sha256(new).hexdigest())
        self.assertEqual(revs[1].created_by, self.tech)
        s.refresh_from_db()
        self.assertEqual((s.last_saved_revision, s.save_count, s.remote_changed), (revs[1], 1, False))
        self.assertTrue(AuditLog.objects.filter(extra_data__office_event='m365_edit_save',
                                                success=True).exists())

        resp = self.post('finish', s)
        s.refresh_from_db()
        self.assertEqual((s.state, s.working_copy), ('closed', 'deleted'))
        delete = self.ms.graph_calls('DELETE')
        self.assertEqual(len(delete), 1)
        self.assertTrue(delete[0]['headers'].get('If-Match'))
        self.assertIsNone(self.ms.find(s.item_id))
        for event in ('m365_edit_start', 'm365_edit_finish'):
            self.assertTrue(AuditLog.objects.filter(extra_data__office_event=event).exists())

    def test_reopen_returns_the_same_session(self):
        self.start()
        self.start()
        self.assertEqual(M365EditSession.objects.count(), 1)
        self.assertEqual(len(self.ms.graph_calls('PUT')), 1)

    def test_finish_refuses_unsaved_changes_and_keep_policy(self):
        self.start()
        s = self.session()
        self.ms.edit(s.item_id, edited_docx())
        self.post('finish', s)
        s.refresh_from_db()
        self.assertEqual(s.state, 'open')               # changes not in clientst0r yet
        M365Connection.objects.filter(pk=self.conn.pk).update(docs_edit_cleanup='keep')
        self.post('finish', s, discard='1')
        s.refresh_from_db()
        self.assertEqual((s.state, s.working_copy), ('discarded', 'kept'))
        self.assertEqual(self.ms.graph_calls('DELETE'), [])
        self.assertEqual(len(self.revisions()), 1)

    def test_unchanged_save_back_creates_nothing(self):
        self.start()
        self.post('save', self.session())
        self.assertEqual(len(self.revisions()), 1)

    def test_own_onedrive_location(self):
        loc = self.location('my_onedrive')
        M365Connection.objects.filter(pk=self.conn.pk).update(docs_edit_location=loc,
                                                              docs_edit_folder_name='')
        self.start()
        s = self.session()
        self.assertEqual(s.drive_id, self.ms.my_drive_id)
        self.assertEqual(self.ms.graph_calls('POST'), [])

    def test_others_see_who_is_editing_and_editor_warns(self):
        self.start()
        self.login(self.tech2)
        resp = self.client.get(reverse('office:target_detail', args=['doc', self.target.pk]))
        self.assertContains(resp, 'Being edited in Microsoft 365 by')
        self.assertContains(resp, 'm365-tech')
        request = RequestFactory().get('/')
        request.user = self.tech2
        html = Template('{% load m365docs_tags %}{% m365_edit_notice target %}').render(
            Context({'target': self.target, 'request': request}))
        self.assertIn('Also being edited in Microsoft 365 by', html)

    def test_size_limit(self):
        with override_settings(OFFICE_MAX_FILE_MB=0):
            self.start()
        self.assertFalse(M365EditSession.objects.filter(state='open').exists())
        self.assertEqual(self.ms.graph_calls('PUT'), [])

    def test_save_back_refuses_download_off_tenant(self):
        self.start()
        s = self.session()
        self.ms.edit(s.item_id, edited_docx())
        self.ms.download_host = 'evil.example'
        self.post('save', s)
        self.assertEqual(len(self.revisions()), 1)
        self.assertFalse([c for c in self.ms.calls if 'evil.example' in c['url']])

    def test_checksum_mismatch_refuses_upload(self):
        FileRevision.objects.filter(document=self.target.obj).update(sha256='0' * 64)
        self.start()
        self.assertEqual(self.ms.graph_calls('PUT'), [])


class ConflictAndIdempotencyTests(EditBase):
    def test_stale_base_is_kept_as_conflict(self):
        self.start()
        s = self.session()
        # Someone saves a newer clientst0r revision meanwhile.
        storage.save_new_revision(self.target, edited_docx('local change'), user=self.owner,
                                  source='upload', expected_base_revision=1)
        self.ms.edit(s.item_id, edited_docx('microsoft change'))
        resp = self.post('save', s)
        self.assertEqual([r.revision_number for r in self.revisions()], [1, 2])
        q = QuarantinedSave.objects.get(document=self.target.obj)
        self.assertEqual(q.reason, 'stale')
        self.assertEqual(q.sha256, hashlib.sha256(edited_docx('microsoft change')).hexdigest())
        s.refresh_from_db()
        self.assertEqual(s.last_conflict, q)
        msgs = [str(m) for m in resp.wsgi_request._messages]
        self.assertTrue(any('changed while you were editing' in m for m in msgs), msgs)

    def test_double_save_back_is_idempotent(self):
        self.start()
        s = self.session()
        self.ms.edit(s.item_id, edited_docx())
        self.post('save', s)
        resp = self.post('save', s)
        self.assertEqual([r.revision_number for r in self.revisions()], [1, 2])
        msgs = [str(m) for m in resp.wsgi_request._messages]
        self.assertTrue(any('Already saved' in m for m in msgs), msgs)
        # A save-back still running refuses a second one.
        M365EditSession.objects.filter(pk=s.pk).update(saving_since=timezone.now())
        s.refresh_from_db()
        with self.assertRaises(editing.EditError):
            editing.save_back(self.tech, s)
        self.assertEqual(len(self.revisions()), 2)

    def test_later_edit_saves_on_top_of_own_save(self):
        self.start()
        s = self.session()
        self.ms.edit(s.item_id, edited_docx('one'))
        self.post('save', s)
        self.ms.edit(s.item_id, edited_docx('two'))
        self.post('save', s)
        self.assertEqual([r.revision_number for r in self.revisions()], [1, 2, 3])
        self.assertFalse(QuarantinedSave.objects.exists())


class PermissionAndIsolationTests(EditBase):
    def _customer(self, flag):
        role = RoleTemplate.objects.create(
            name=f'Customer editor {flag}', docs_view=True, docs_edit=True, docs_create=True,
            files_view=True, files_upload=True, office_edit_in_m365=flag)
        user = User.objects.create_user(f'cust-{flag}', f'cust{flag}@example.com', 'x')
        Membership.objects.create(user=user, organization=self.org, role=Role.EDITOR,
                                  role_template=role, is_active=True)
        self.grant(user)
        return user, role

    def test_customer_needs_explicit_permission(self):
        user, _ = self._customer(False)
        self.assertFalse(editing.edit_connections(user, self.target))
        self.login(user)
        page = self.client.get(reverse('office:target_detail', args=['doc', self.target.pk]))
        self.assertNotContains(page, 'Edit in Microsoft 365')
        self.assertEqual(self.start(user).status_code, 404)
        allowed, _ = self._customer(True)
        self.assertTrue(editing.edit_connections(allowed, self.target))
        self.assertEqual(self.start(allowed).status_code, 302)

    def test_permission_revoked_mid_session(self):
        user, role = self._customer(True)
        self.start(user)
        s = self.session()
        self.ms.edit(s.item_id, edited_docx())
        role.office_edit_in_m365 = False
        with self.captureOnCommitCallbacks(execute=True):
            role.save()
        s.refresh_from_db()
        self.assertEqual((s.state, s.working_copy), ('revoked', 'delete_pending'))
        calls = len(self.ms.calls)
        self.post('save', s)
        self.assertEqual(len(self.revisions()), 1)
        self.assertEqual(len(self.ms.calls), calls)     # nothing fetched from Microsoft
        # The cleanup task deletes the working copy.
        editing.run_maintenance()
        s.refresh_from_db()
        self.assertEqual(s.working_copy, 'deleted')

    def test_permission_lost_without_signal_is_caught_at_save(self):
        user, role = self._customer(True)
        self.start(user)
        s = self.session()
        self.ms.edit(s.item_id, edited_docx())
        RoleTemplate.objects.filter(pk=role.pk).update(docs_edit=False)    # no signal
        downloads = [c for c in self.ms.calls if 'download.aspx' in c['url']]
        self.post('save', s)
        s.refresh_from_db()
        self.assertEqual(s.state, 'revoked')
        self.assertEqual(len(self.revisions()), 1)
        self.assertEqual([c for c in self.ms.calls if 'download.aspx' in c['url']], downloads)

    def test_cross_customer_refused(self):
        other = self.make_connection(self.other_org, docs_edit_enabled=True)
        other_loc = self.location('drive', conn=other)
        M365Connection.objects.filter(pk=other.pk).update(docs_edit_location=other_loc)
        other.refresh_from_db()
        # Another customer's connection is never used for this file.
        self.assertEqual(self.start(conn=other).status_code, 404)
        with self.assertRaises(PermissionDenied):
            editing.start(self.tech, self.target, other)
        # A platform-owned connection: MSP staff only, never a customer user.
        M365Connection.objects.filter(pk=other.pk).update(organization=None)
        other.refresh_from_db()
        self.assertFalse(editing.connection_allowed_for(other, self.target, self.editor))
        self.assertTrue(editing.connection_allowed_for(other, self.target, self.tech))
        M365Connection.objects.filter(pk=other.pk).update(organization=self.other_org)
        other.refresh_from_db()
        # Someone of another organization cannot reach the file at all.
        self.grant(self.outsider)
        self.assertEqual(self.start(self.outsider).status_code, 404)
        self.assertEqual(self.ms.graph_calls('PUT'), [])
        # Nobody else can act on a session.
        self.start()
        s = self.session()
        self.login(self.tech2)
        for name in ('open', 'save', 'check', 'finish'):
            self.assertEqual(self.post(name, s).status_code, 404, name)

    def test_feature_switched_off_ends_sessions(self):
        self.start()
        s = self.session()
        self.login(self.owner)
        self.client.post(reverse('integrations:m365edit_settings', args=[self.conn.pk]),
                         {'docs_edit_location': self.loc.pk, 'docs_edit_cleanup': 'delete',
                          'docs_edit_stale_hours': '72'})
        self.conn.refresh_from_db()
        self.assertFalse(self.conn.docs_edit_enabled)
        s.refresh_from_db()
        self.assertEqual(s.state, 'revoked')
        self.assertTrue(AuditLog.objects.filter(extra_data__office_event='m365_edit_settings')
                        .exists())

    def test_settings_refuse_a_whole_site_and_need_admin(self):
        site = self.location('site')
        self.login(self.owner)
        self.client.post(reverse('integrations:m365edit_settings', args=[self.conn.pk]),
                         {'docs_edit_enabled': 'on', 'docs_edit_location': site.pk,
                          'docs_edit_cleanup': 'delete', 'docs_edit_stale_hours': '72'})
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.docs_edit_location, self.loc)
        self.login(self.editor)
        resp = self.client.post(reverse('integrations:m365edit_settings', args=[self.conn.pk]),
                                {'docs_edit_location': self.loc.pk, 'docs_edit_cleanup': 'keep',
                                 'docs_edit_stale_hours': '1'})
        self.assertIn(resp.status_code, (302, 403))
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.docs_edit_cleanup, 'delete')


class CleanupJobTests(EditBase):
    def _idle(self, s, hours=100):
        M365EditSession.objects.filter(pk=s.pk).update(
            last_activity_at=timezone.now() - timedelta(hours=hours))

    def test_idle_unchanged_session_is_ended_and_copy_deleted(self):
        self.start()
        s = self.session()
        self._idle(s)
        result = editing.run_maintenance()
        s.refresh_from_db()
        self.assertEqual((s.state, s.working_copy), ('ended', 'deleted'))
        self.assertEqual(result['ended_unchanged'], 1)

    def test_idle_changed_session_is_reminded_never_imported(self):
        self.tech.email = 'tech@example.com'
        self.tech.save()
        self.start()
        s = self.session()
        self.ms.edit(s.item_id, edited_docx())
        self._idle(s)
        result = editing.run_maintenance()
        s.refresh_from_db()
        self.assertEqual(s.state, 'open')
        self.assertIsNotNone(s.reminded_at)
        self.assertEqual(result['reminded'], 1)
        self.assertEqual(len(self.revisions()), 1)
        self.assertEqual(self.ms.graph_calls('DELETE'), [])
        self.assertFalse([c for c in self.ms.calls if 'download.aspx' in c['url']])
        # Not reminded again within the idle period.
        self.assertEqual(editing.run_maintenance()['reminded'], 0)

    def test_recent_session_untouched(self):
        self.start()
        self.assertEqual(editing.run_maintenance()['ended_unchanged'], 0)
        self.assertEqual(self.session().state, 'open')

    def test_scheduler_knows_the_task(self):
        from core.management.commands.run_scheduler import COMMAND_TASKS
        self.assertEqual(COMMAND_TASKS['m365_edit_sessions'][0], 'm365_edit_sessions')
        from django.core.management import call_command
        out = io.StringIO()
        call_command('m365_edit_sessions', stdout=out)
        self.assertIn('reminded=', out.getvalue())


class SecretsTests(EditBase):
    def test_no_tokens_or_download_urls_in_urls_logs_audit_or_rows(self):
        records = []

        class Grab(logging.Handler):
            def emit(self, record):
                records.append(self.format(record))
        handler = Grab(level=logging.DEBUG)
        root = logging.getLogger()
        root.addHandler(handler)
        old = root.level
        root.setLevel(logging.DEBUG)
        try:
            resp = self.start()
            s = self.session()
            self.ms.edit(s.item_id, edited_docx())
            self.post('check', s)
            self.post('save', s)
            self.post('finish', s)
        finally:
            root.removeHandler(handler)
            root.setLevel(old)
        self.assertNotIn('AT-', resp['Location'])
        for c in self.ms.graph_calls():
            self.assertNotRegex(c['url'], r'AT-\d|RT-\d|access_token|tempauth')
        blobs = [json.dumps(e.extra_data) + e.description for e in AuditLog.objects.all()]
        s.refresh_from_db()
        blobs.append(json.dumps({f.name: str(getattr(s, f.attname))
                                 for f in M365EditSession._meta.concrete_fields}))
        blobs.extend(records)
        for blob in blobs:
            for secret in ('AT-1', 'AT-0', 'RT-1', 'RT-2', 'tempauth', 'Bearer', 'app-secret-value'):
                self.assertNotIn(secret, blob)


class RoleRegistryTests(EditBase):
    def test_permission_is_registered_customer_assignable_and_off(self):
        from accounts import permission_registry as reg
        from accounts.role_seeds import definitions
        p = reg.get('office_edit_in_m365')
        self.assertTrue(p.customer_assignable)
        self.assertFalse(p.staff_only)
        self.assertFalse(RoleTemplate._meta.get_field('office_edit_in_m365').default)
        for d in definitions():
            self.assertFalse(d.flags.get('office_edit_in_m365'), d.key)

    def test_builtin_roles_stay_uncustomized(self):
        for rt in RoleTemplate.objects.exclude(seed_key=''):
            self.assertEqual(rt.compute_checksum(), rt.seed_checksum, rt.name)


class PlatformConnectionTests(EditBase):
    """The MSP's own (platform-owned) Microsoft 365 tenant."""

    def setUp(self):
        super().setUp()
        self.platform = M365Connection(organization=None, name='MSP tenant',
                                       tenant_id='99999999-8888-7777-6666-555555555555',
                                       docs_enabled=True, docs_access='readwrite',
                                       docs_sharepoint='all',
                                       docs_sharepoint_host='contoso.sharepoint.com')
        self.platform.set_credentials({'client_id': 'msp-app', 'client_secret': 'msp-secret'})
        self.platform.save()
        self.ploc = self.location('my_onedrive', conn=self.platform)
        M365Connection.objects.filter(pk=self.platform.pk).update(
            docs_edit_enabled=True, docs_edit_location=self.ploc, docs_edit_folder_name='')
        self.platform.refresh_from_db()
        self.grant(self.tech, conn=self.platform)

    def test_staff_round_trip_through_platform_connection(self):
        conns = editing.edit_connections(self.tech, self.target)
        self.assertEqual([c.pk for c in conns], [self.platform.pk, self.conn.pk])   # default
        resp = self.start(conn=self.platform)
        self.assertEqual(resp.status_code, 302)
        s = self.session()
        self.assertEqual((s.connection, s.drive_id, s.organization_id),
                         (self.platform, self.ms.my_drive_id, self.org.pk))
        self.ms.edit(s.item_id, edited_docx())
        self.post('save', s)
        self.assertEqual([r.revision_number for r in self.revisions()], [1, 2])
        self.post('finish', s)
        s.refresh_from_db()
        self.assertEqual(s.state, 'closed')
        for event in ('m365_edit_start', 'm365_edit_save', 'm365_edit_finish'):
            entry = AuditLog.objects.get(extra_data__office_event=event)
            self.assertEqual(entry.extra_data['connection'], self.platform.pk)
            self.assertEqual(entry.extra_data['connection_name'], 'MSP tenant')
            self.assertEqual(entry.extra_data['connection_owner'], 'Platform (MSP)')
            self.assertEqual(entry.organization_id, self.org.pk)

    def test_customer_preference_puts_customer_tenant_first(self):
        M365Connection.objects.filter(pk=self.conn.pk).update(docs_edit_staff_tenant='customer')
        conns = editing.edit_connections(self.tech, self.target)
        self.assertEqual([c.pk for c in conns], [self.conn.pk, self.platform.pk])

    def test_confirm_step_names_the_tenant_before_upload(self):
        self.login(self.tech)
        resp = self.client.get(reverse('integrations:m365edit_start', args=['doc', self.target.pk]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('Platform (MSP)', body)
        self.assertIn(self.platform.tenant_id, body)
        self.assertIn('Your own OneDrive in this tenant', body)
        self.assertIn(self.org.name, body)               # the customer's own option
        self.assertLess(body.index('MSP tenant'), body.index(self.conn.name))
        self.assertEqual(self.ms.graph_calls('PUT'), [])
        self.assertFalse(M365EditSession.objects.exists())

    def test_confirm_step_offers_connect_when_not_signed_in(self):
        self.login(self.tech2)
        resp = self.client.get(reverse('integrations:m365edit_start', args=['doc', self.target.pk]))
        self.assertContains(resp, 'Connect my Microsoft 365 documents first')

    def test_customer_user_never_uses_platform_connection(self):
        role = RoleTemplate.objects.create(
            name='Customer M365 editor', docs_view=True, docs_edit=True, files_view=True,
            files_upload=True, office_edit_in_m365=True)
        user = User.objects.create_user('cust-plat', 'cp@example.com', 'x')
        Membership.objects.create(user=user, organization=self.org, role=Role.EDITOR,
                                  role_template=role, is_active=True)
        self.grant(user, conn=self.platform)
        self.grant(user)
        self.assertEqual([c.pk for c in editing.edit_connections(user, self.target)],
                         [self.conn.pk])
        self.assertEqual(self.start(user, conn=self.platform).status_code, 404)
        with self.assertRaises(PermissionDenied):
            editing.start(user, self.target, self.platform)
        self.assertEqual(self.ms.graph_calls('PUT'), [])

    def test_staff_refused_on_another_customers_connection(self):
        other = self.make_connection(self.other_org, docs_edit_enabled=True)
        loc = self.location('drive', conn=other)
        M365Connection.objects.filter(pk=other.pk).update(docs_edit_location=loc)
        other.refresh_from_db()
        self.grant(self.tech, conn=other)
        self.assertNotIn(other.pk, [c.pk for c in editing.edit_connections(self.tech, self.target)])
        self.assertEqual(self.start(conn=other).status_code, 404)
        with self.assertRaises(PermissionDenied):
            editing.start(self.tech, self.target, other)
        self.assertEqual(self.ms.graph_calls('PUT'), [])

    def test_platform_settings_need_a_platform_admin_in_global_view(self):
        url = reverse('integrations:m365edit_settings', args=[self.platform.pk])
        data = {'docs_edit_location': self.ploc.pk, 'docs_edit_cleanup': 'keep',
                'docs_edit_stale_hours': '5'}
        # A customer's owner, inside the customer: refused.
        self.login(self.owner)
        resp = self.client.post(url, data)
        self.assertIn(resp.status_code, (403, 404))
        self.platform.refresh_from_db()
        self.assertTrue(self.platform.docs_edit_enabled)
        # A platform administrator in global view.
        admin = User.objects.create_superuser('plat-admin', 'pa@example.com', 'x')
        self.client.force_login(admin)
        s = self.client.session
        s.pop('current_organization_id', None)
        s['global_view_mode'] = True
        s.save()
        resp = self.client.post(url, {**data, 'docs_edit_enabled': 'on'})
        self.assertEqual(resp.status_code, 302)
        self.platform.refresh_from_db()
        self.assertEqual((self.platform.docs_edit_cleanup, self.platform.docs_edit_stale_hours),
                         ('keep', 5))
        entry = AuditLog.objects.get(extra_data__office_event='m365_edit_settings')
        self.assertEqual(entry.extra_data['owner'], 'Platform (MSP)')
