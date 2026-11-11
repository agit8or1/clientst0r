"""Office documents: storage, quarantine, sessions, tokens, policy, network
guard, templates and views.

No real editor runs here. Provider behaviour is a FakeProvider registered for
the duration of a test; these tests prove the provider-independent core, not
that ONLYOFFICE or Collabora work.
"""
import hashlib
import http.server
import io
import os
import shutil
import socket
import tempfile
import threading
import zipfile
from datetime import timedelta
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role
from audit.models import AuditLog
from core.models import Organization
from docs.models import Document, DocumentVersion
from files.models import Attachment

from . import creation, formats, net, policy, quarantine, sessions, storage, targets, tokens
from .models import (AccessToken, EditorInstance, EditSession, FileRevision, OfficeFile,
                     OfficeSettings, OrganizationOfficePolicy, QuarantinedSave)
from .providers import (Capabilities, EditorPage, EditorProvider, HealthResult, all_providers,
                        register)

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

BLANKS = os.path.join(os.path.dirname(__file__), 'templates_files')


def blank(fmt='docx'):
    with open(os.path.join(BLANKS, f'blank.{fmt}'), 'rb') as fh:
        return fh.read()


def docx_with_text(text):
    """A different, still valid .docx: the blank with one paragraph of text."""
    src = zipfile.ZipFile(io.BytesIO(blank('docx')))
    out = io.BytesIO()
    with src, zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename == 'word/document.xml':
                data = data.replace(b'<w:p/>', f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p>'.encode())
            dst.writestr(info, data)
    return out.getvalue()


class FakeProvider(EditorProvider):
    key = 'onlyoffice'
    label = 'Fake editor'
    caps = Capabilities(edit_formats=frozenset({'docx', 'xlsx', 'pptx'}),
                        view_formats=frozenset({'doc', 'docm'}),
                        convert=frozenset({('doc', 'docx'), ('docx', 'pdf')}),
                        coauthoring=True)

    def capabilities(self, instance):
        return self.caps

    def editor_page_context(self, session, request):
        origin = session.instance.browser_url.rstrip('/')
        return EditorPage(config={'documentKey': session.document_key},
                          script_urls=[origin + '/web-apps/api.js', 'https://evil.example/x.js'],
                          csp={'script-src': [origin, 'https://evil.example'],
                               'frame-src': [origin], 'default-src': ['*']})

    def health_check(self, instance):
        return HealthResult(status='ok', version='10.0.0', edition='Community',
                            capabilities=self.caps)

    def diagnostics(self, instance):
        return []

    def convert(self, instance, revision, target_ext, *, user=None):
        return b'%PDF-1.4 fake' if target_ext == 'pdf' else blank(target_ext)


class OfficeTestBase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.mkdtemp(prefix='office-test-media-')
        cls._media_override = override_settings(MEDIA_ROOT=cls._media)
        cls._media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media_override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)
        super().tearDownClass()

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Org A', slug='org-a')
        cls.other_org = Organization.objects.create(name='Org B', slug='org-b')
        cls.su = User.objects.create_superuser('office-su', 'su@example.com', 'x')
        cls.editor = cls._member('office-editor', cls.org, Role.EDITOR)
        cls.reader = cls._member('office-reader', cls.org, Role.READONLY)
        cls.owner = cls._member('office-owner', cls.org, Role.OWNER)
        cls.outsider = cls._member('office-outsider', cls.other_org, Role.OWNER)

    @staticmethod
    def _member(name, org, role):
        user = User.objects.create_user(name, f'{name}@example.com', 'x')
        Membership.objects.create(user=user, organization=org, role=role, is_active=True)
        return user

    def setUp(self):
        self._saved_providers = all_providers()

    def tearDown(self):
        from . import providers
        providers._REGISTRY.clear()
        providers._REGISTRY.update(self._saved_providers)

    def use_fake_provider(self):
        register(FakeProvider(), replace=True)

    def make_instance(self, **kw):
        defaults = dict(provider='onlyoffice', name=f'Docs {EditorInstance.objects.count() + 1}',
                        mode='separate_server', browser_url='https://docs.example.com/',
                        callback_base_url='https://app.example.com/',
                        shared_secret='a-long-random-test-secret-123', enabled=True,
                        health_status='ok')
        defaults.update(kw)
        inst = EditorInstance.objects.create(**defaults)
        cfg = OfficeSettings.get()
        cfg.enabled_providers = ['onlyoffice', 'collabora']
        cfg.save()
        return inst

    def make_doc(self, org=None, title='Plan', data=None, ext='docx'):
        org = org or self.org
        data = data if data is not None else blank(ext)
        return Document.objects.create(
            organization=org, title=title, slug=f'{title.lower()}-{Document.objects.count()}',
            content_type='file', file=SimpleUploadedFile(f'{title}.{ext}', data),
            file_size=len(data), file_type=formats.mime_for(f'x.{ext}'), created_by=self.su)

    def target(self, obj=None):
        return targets.target_for(obj or self.make_doc())

    def open_edit(self, target, user=None):
        user = user or self.editor
        return sessions.open_session(target, user, mode='edit',
                                     instance=EditorInstance.objects.first() or self.make_instance())


# ---------------------------------------------------------------------------
# Blank templates
# ---------------------------------------------------------------------------

class BlankTemplateTests(TestCase):
    def test_blanks_are_valid_ooxml_with_the_right_main_part(self):
        from defusedxml import ElementTree as ET
        for fmt in ('docx', 'xlsx', 'pptx'):
            data = blank(fmt)
            formats.validate_file(io.BytesIO(data), f'x.{fmt}')
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                self.assertIsNone(zf.testzip(), fmt)
                names = set(zf.namelist())
                self.assertIn('[Content_Types].xml', names)
                self.assertFalse(any(n.lower().endswith('vbaproject.bin') for n in names))
                for name in names:
                    if name.endswith(('.xml', '.rels')):
                        ET.fromstring(zf.read(name))  # well-formed, no DTD
                # Every internal relationship target exists.
                for name in [n for n in names if n.endswith('.rels')]:
                    base = os.path.dirname(os.path.dirname(name))
                    root = ET.fromstring(zf.read(name))
                    for rel in root:
                        if rel.get('TargetMode') == 'External':
                            continue
                        target = os.path.normpath(os.path.join(base, rel.get('Target'))).lstrip('/')
                        self.assertIn(target, names, f'{fmt}: {name} -> {target}')
                types = formats._content_types(zf)
                main = formats.MAIN_PART_NAMES[formats.EDITABLE[fmt]]
                self.assertEqual(types[main], formats.MAIN_PART_TYPES[fmt])

    def test_validation_rejects_wrong_or_dangerous_content(self):
        with self.assertRaises(formats.InvalidOfficeFile):
            formats.validate_file(io.BytesIO(b'not a zip'), 'x.docx')
        with self.assertRaises(formats.InvalidOfficeFile):   # an xlsx is not a docx
            formats.validate_file(io.BytesIO(blank('xlsx')), 'x.docx')
        buf = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(blank('docx'))) as src, zipfile.ZipFile(buf, 'w') as dst:
            for info in src.infolist():
                dst.writestr(info, src.read(info))
            dst.writestr('word/vbaProject.bin', b'\x00')
        with self.assertRaises(formats.InvalidOfficeFile):
            formats.validate_file(io.BytesIO(buf.getvalue()), 'x.docx')
        formats.validate_file(io.BytesIO(formats.OLE_MAGIC + b'\x00' * 100), 'old.doc')
        with self.assertRaises(formats.InvalidOfficeFile):
            formats.validate_file(io.BytesIO(b'PK\x03\x04'), 'old.doc')

    def test_template_package_becomes_a_document(self):
        dotx = blank('docx').replace(b'', b'')
        src = zipfile.ZipFile(io.BytesIO(dotx))
        out = io.BytesIO()
        with src, zipfile.ZipFile(out, 'w') as dst:
            for info in src.infolist():
                data = src.read(info)
                if info.filename == '[Content_Types].xml':
                    data = data.replace(formats.MAIN_PART_TYPES['docx'].encode(),
                                        formats.MAIN_PART_TYPES['dotx'].encode())
                dst.writestr(info, data)
        formats.validate_file(io.BytesIO(out.getvalue()), 'x.dotx')
        converted = formats.template_to_document(out.getvalue(), 'dotx')
        formats.validate_file(io.BytesIO(converted), 'x.docx')


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

class StorageTests(OfficeTestBase):
    def test_seed_copies_existing_file_as_revision_one(self):
        doc = self.make_doc()
        original = doc.file.name
        t = targets.target_for(doc)
        rev = storage.ensure_current(t)
        self.assertEqual(rev.revision_number, 1)
        self.assertEqual(rev.source, 'upload')
        self.assertEqual(rev.sha256, hashlib.sha256(blank()).hexdigest())
        doc.refresh_from_db()
        self.assertEqual(doc.file.name, rev.file.name)
        self.assertTrue(rev.file.name.startswith(f'office/revisions/{self.org.pk}/document-{doc.pk}/'))
        self.assertTrue(os.path.exists(os.path.join(self._media, original)), 'original kept')
        self.assertEqual(storage.ensure_current(t).pk, rev.pk, 'idempotent')

    def test_save_new_revision_updates_target_without_text_snapshot(self):
        t = self.target()
        storage.ensure_current(t)
        data = docx_with_text('hello')
        rev = storage.save_new_revision(t, data, user=self.editor, source='upload',
                                        expected_base_revision=1)
        self.assertEqual(rev.revision_number, 2)
        self.assertFalse(rev.duplicate)
        doc = Document.objects.get(pk=t.pk)
        self.assertEqual(doc.file.name, rev.file.name)
        self.assertEqual(doc.file_size, len(data))
        self.assertEqual(doc.file_type, formats.MIME['docx'])
        self.assertEqual(rev.based_on_revision.revision_number, 1)
        with storage.open_revision(rev) as fh:
            self.assertEqual(fh.read(), data)
        self.assertEqual(DocumentVersion.objects.filter(document=doc).count(), 0)

    def test_stale_base_is_rejected_and_nothing_is_written(self):
        t = self.target()
        storage.ensure_current(t)
        storage.save_new_revision(t, docx_with_text('a'), user=self.editor, source='upload',
                                  expected_base_revision=1)
        before = set(self._files())
        with self.assertRaises(storage.StaleRevision) as cm:
            storage.save_new_revision(t, docx_with_text('b'), user=self.editor, source='upload',
                                      expected_base_revision=1)
        self.assertEqual((cm.exception.expected, cm.exception.current), (1, 2))
        self.assertEqual(storage.current(t).revision_number, 2)
        self.assertEqual(set(self._files()), before)

    def test_stale_editor_save_is_quarantined(self):
        t = self.target()
        session = self.open_edit(t)
        storage.restore(t, storage.current(t), self.su)          # someone else moved it on
        outcome = storage.save_or_quarantine(t, docx_with_text('late'), user=self.editor,
                                             source='editor_save', session=session)
        self.assertFalse(outcome.ok)
        q = outcome.quarantined
        self.assertEqual(q.reason, 'stale')
        self.assertEqual(q.document_id, t.pk)
        self.assertTrue(os.path.exists(os.path.join(self._media, q.file.name)))
        self.assertEqual(storage.current(t).revision_number, 2)
        self.assertTrue(AuditLog.objects.filter(extra_data__office_event='quarantine').exists())

    def test_duplicate_callback_is_idempotent(self):
        t = self.target()
        session = self.open_edit(t)
        data = docx_with_text('once')
        first = storage.save_new_revision(t, data, user=self.editor, source='editor_save',
                                          session=session)
        again = storage.save_new_revision(t, data, user=self.editor, source='editor_save',
                                          session=session)
        explicit = storage.save_new_revision(t, data, user=self.editor, source='editor_save',
                                             session=session, expected_base_revision=1)
        self.assertEqual(first.revision_number, 2)
        self.assertTrue(again.duplicate)
        self.assertTrue(explicit.duplicate)
        self.assertEqual(again.pk, first.pk)
        self.assertEqual(FileRevision.objects.filter(document_id=t.pk).count(), 2)
        # Force-saves of the same group chain on without a stale error.
        third = storage.save_new_revision(t, docx_with_text('twice'), user=self.editor,
                                          source='editor_save', session=session)
        self.assertEqual(third.revision_number, 3)

    def test_failure_inside_the_transaction_leaves_no_trace(self):
        t = self.target()
        storage.ensure_current(t)
        doc_file = Document.objects.get(pk=t.pk).file.name
        before = set(self._files())
        with mock.patch.object(targets.DocumentTarget, 'point_at', side_effect=RuntimeError('db')):
            with self.assertRaises(storage.StorageError):
                storage.save_new_revision(t, docx_with_text('x'), user=self.editor, source='upload')
        self.assertEqual(FileRevision.objects.filter(document_id=t.pk).count(), 1)
        self.assertEqual(Document.objects.get(pk=t.pk).file.name, doc_file)
        self.assertEqual(set(self._files()), before)

    def test_restore_adds_a_revision(self):
        t = self.target()
        r1 = storage.ensure_current(t)
        storage.save_new_revision(t, docx_with_text('v2'), user=self.editor, source='upload')
        r3 = storage.restore(t, r1, self.editor)
        self.assertEqual(r3.revision_number, 3)
        self.assertEqual(r3.source, 'restore')
        self.assertEqual(r3.restored_from_id, r1.pk)
        self.assertEqual(r3.sha256, r1.sha256)
        self.assertNotEqual(r3.file.name, r1.file.name)
        self.assertEqual(FileRevision.objects.filter(document_id=t.pk).count(), 3)

    def test_validation_size_and_scan(self):
        t = self.target()
        storage.ensure_current(t)
        with self.assertRaises(storage.RevisionRejected) as cm:
            storage.save_new_revision(t, b'garbage', user=self.editor, source='upload')
        self.assertEqual(cm.exception.code, 'invalid')
        with override_settings(OFFICE_MAX_FILE_MB=0):
            with self.assertRaises(storage.RevisionRejected) as cm:
                storage.save_new_revision(t, blank(), user=self.editor, source='upload')
        self.assertEqual(cm.exception.code, 'too_large')
        with override_settings(OFFICE_SCAN_HOOK='office.tests.refuse_scan'):
            with self.assertRaises(storage.RevisionRejected) as cm:
                storage.save_new_revision(t, docx_with_text('x'), user=self.editor, source='upload')
        self.assertEqual(cm.exception.code, 'scan')
        self.assertEqual(storage.current(t).revision_number, 1)

    def test_read_only_formats_refuse_editor_saves(self):
        doc = self.make_doc(title='Old', data=formats.OLE_MAGIC + b'\x00' * 64, ext='doc')
        t = targets.target_for(doc)
        session_rev = storage.ensure_current(t)
        self.assertEqual(session_rev.revision_number, 1)
        with self.assertRaises(storage.RevisionRejected) as cm:
            storage.save_new_revision(t, formats.OLE_MAGIC + b'\x01' * 64, user=self.editor,
                                      source='editor_save')
        self.assertEqual(cm.exception.code, 'read_only')

    def test_permission_and_session_rechecked_on_write(self):
        t = self.target()
        session = self.open_edit(t)
        sessions.revoke(session, 'test')
        with self.assertRaises(storage.SessionRevoked):
            storage.save_new_revision(t, docx_with_text('x'), user=self.editor,
                                      source='editor_save', session=session)
        with self.assertRaises(storage.PermissionRevoked):
            storage.save_new_revision(t, docx_with_text('x'), user=self.reader, source='upload')

    def test_safe_names(self):
        self.assertEqual(storage.safe_filename('../../etc/passwd.docx'), 'passwd.docx')
        self.assertEqual(storage.safe_filename('..\\..\\boot.ini'), 'boot.ini')
        self.assertEqual(storage.safe_filename('a\x00b<c>.docx'), 'abc.docx')
        self.assertEqual(storage.safe_filename('.docx'), 'document.docx')
        self.assertLessEqual(len(storage.safe_filename('x' * 400 + '.docx')), 255)
        self.assertTrue(storage.safe_filename('x' * 400 + '.docx').endswith('.docx'))
        with self.assertRaises(ValueError):
            storage._abs('../outside')

    def test_attachment_and_ticket_targets(self):
        att = Attachment.objects.create(
            organization=self.org, entity_type='asset', entity_id=1,
            file=SimpleUploadedFile('sheet.xlsx', blank('xlsx')), original_filename='sheet.xlsx',
            file_size=len(blank('xlsx')), content_type=formats.MIME['xlsx'], uploaded_by=self.su)
        t = targets.target_for(att)
        self.assertEqual(storage.ensure_current(t).revision_number, 1)
        self.assertTrue(t.can_edit(self.editor))
        self.assertFalse(t.can_edit(self.reader))
        self.assertTrue(t.can_view(self.reader))
        self.assertFalse(t.can_view(self.outsider))

    def _files(self):
        root = os.path.join(self._media, 'office')
        out = []
        for dirpath, _dirs, files in os.walk(root):
            out += [os.path.join(dirpath, f) for f in files]
        return out


def refuse_scan(path, *, name, target, user):
    from .scanning import ScanResult
    return ScanResult(clean=False, scanner='test', detail='EICAR')


# ---------------------------------------------------------------------------
# Quarantine retention
# ---------------------------------------------------------------------------

class QuarantineTests(OfficeTestBase):
    def test_purge_removes_only_expired_entries(self):
        t = self.target()
        old = quarantine.keep_bytes(t, b'old bytes', reason='stale')
        new = quarantine.keep_bytes(t, b'new bytes', reason='revoked')
        QuarantinedSave.objects.filter(pk=old.pk).update(expires_at=timezone.now() - timedelta(days=1))
        old_path = os.path.join(self._media, old.file.name)
        self.assertTrue(os.path.exists(old_path))
        result = quarantine.purge_expired()
        self.assertEqual(result['quarantine_removed'], 1)
        self.assertFalse(QuarantinedSave.objects.filter(pk=old.pk).exists())
        self.assertFalse(os.path.exists(old_path))
        self.assertTrue(QuarantinedSave.objects.filter(pk=new.pk).exists())

    def test_retention_follows_settings(self):
        cfg = OfficeSettings.get()
        cfg.quarantine_retention_days = 7
        cfg.save()
        q = quarantine.keep_bytes(self.target(), b'x', reason='stale')
        self.assertAlmostEqual((q.expires_at - timezone.now()).total_seconds(), 7 * 86400, delta=60)

    def test_scheduled_task_is_registered(self):
        from core.management.commands.run_scheduler import COMMAND_TASKS
        from core.models import ScheduledTask
        self.assertEqual(COMMAND_TASKS['office_purge_quarantine'][0], 'office_purge_quarantine')
        ScheduledTask.get_or_create_defaults()
        self.assertTrue(ScheduledTask.objects.filter(task_type='office_purge_quarantine').exists())
        from django.core.management import call_command
        out = io.StringIO()
        call_command('office_purge_quarantine', stdout=out)
        self.assertIn('Removed', out.getvalue())

    def test_expired_diagnostic_files_are_purged(self):
        f = OfficeFile.objects.create(purpose='diagnostic', name='rt.docx',
                                      expires_at=timezone.now() - timedelta(hours=1))
        storage.store_initial(targets.OfficeFileTarget(f), blank(), user=self.su, source='create')
        self.assertEqual(quarantine.purge_expired()['diagnostic_files_removed'], 1)
        self.assertFalse(OfficeFile.objects.filter(pk=f.pk).exists())


# ---------------------------------------------------------------------------
# Sessions and tokens
# ---------------------------------------------------------------------------

class SessionTokenTests(OfficeTestBase):
    def setUp(self):
        super().setUp()
        self.instance = self.make_instance()
        self.t = self.target()

    def test_document_key_shared_then_renewed_after_outside_revision(self):
        a = sessions.open_session(self.t, self.editor, mode='edit', instance=self.instance)
        b = sessions.open_session(self.t, self.owner, mode='edit', instance=self.instance)
        self.assertEqual(a.document_key, b.document_key)
        self.assertRegex(a.document_key, r'^[0-9A-Za-z._=-]{1,128}$')
        # A force-save by the group keeps the group's key for newcomers.
        storage.save_new_revision(self.t, docx_with_text('fs'), user=self.editor,
                                  source='editor_save', session=a)
        c = sessions.open_session(self.t, self.su, mode='view', instance=self.instance)
        self.assertEqual(c.document_key, a.document_key)
        # A revision written outside the group: the next session gets a new key.
        storage.restore(self.t, storage.revisions(self.t).last(), self.su)
        d = sessions.open_session(self.t, self.su, mode='edit', instance=self.instance)
        self.assertNotEqual(d.document_key, a.document_key)
        # Closed groups don't hand out their key.
        for s in (a, b, c, d):
            sessions.close(s)
        e = sessions.open_session(self.t, self.su, mode='edit', instance=self.instance)
        self.assertNotIn(e.document_key, {a.document_key, d.document_key})

    def test_open_requires_permission_for_the_mode(self):
        from django.core.exceptions import PermissionDenied
        sessions.open_session(self.t, self.reader, mode='view', instance=self.instance)
        with self.assertRaises(PermissionDenied):
            sessions.open_session(self.t, self.reader, mode='edit', instance=self.instance)
        with self.assertRaises(PermissionDenied):
            sessions.open_session(self.t, self.outsider, mode='view', instance=self.instance)

    def test_token_scope_and_hashing(self):
        s = sessions.open_session(self.t, self.editor, mode='edit', instance=self.instance)
        raw = tokens.issue(s)
        row = AccessToken.objects.get(session=s)
        self.assertNotEqual(row.token_hash, raw)
        self.assertNotIn(raw, str(AccessToken.objects.values_list()))
        ok = tokens.validate(raw, op='write', session_id=s.pk, target=self.t)
        self.assertEqual(ok.session_id, s.pk)
        with self.assertRaises(tokens.TokenError) as cm:
            tokens.validate(raw, op='export')
        self.assertEqual(cm.exception.reason, 'scope')
        other = sessions.open_session(self.make_doc_target(), self.editor, mode='edit',
                                      instance=self.instance)
        with self.assertRaises(tokens.TokenError):
            tokens.validate(raw, op='read', session_id=other.pk)
        with self.assertRaises(tokens.TokenError):
            tokens.validate(raw, op='read', target=targets.target_for(other.document))
        with self.assertRaises(tokens.TokenError) as cm:
            tokens.validate('nope' * 10, op='read')
        self.assertEqual(cm.exception.reason, 'unknown')

    def make_doc_target(self):
        return targets.target_for(self.make_doc(title='Other'))

    def test_view_session_tokens_cannot_write(self):
        s = sessions.open_session(self.t, self.reader, mode='view', instance=self.instance)
        with self.assertRaises(ValueError):
            tokens.issue(s, ['read', 'write'])
        raw = tokens.issue(s)
        with self.assertRaises(tokens.TokenError):
            tokens.validate(raw, op='write')

    def test_expiry_renewal_and_revocation(self):
        s = sessions.open_session(self.t, self.editor, mode='edit', instance=self.instance)
        raw = tokens.issue(s, ttl_minutes=5)
        AccessToken.objects.filter(session=s).update(expires_at=timezone.now() + timedelta(seconds=30))
        new_exp = tokens.renew(raw, ttl_minutes=60)
        self.assertGreater(new_exp, timezone.now() + timedelta(minutes=50))
        self.assertLessEqual(new_exp, EditSession.objects.get(pk=s.pk).max_expires_at)
        AccessToken.objects.filter(session=s).update(expires_at=timezone.now() - timedelta(seconds=1))
        with self.assertRaises(tokens.TokenError) as cm:
            tokens.validate(raw, op='read')
        self.assertEqual(cm.exception.reason, 'expired')
        raw2 = tokens.issue(s)
        sessions.close(s)
        with self.assertRaises(tokens.TokenError) as cm:
            tokens.validate(raw2, op='read')
        self.assertEqual(cm.exception.reason, 'revoked')

    def test_permission_loss_revokes_on_next_call_and_via_signal(self):
        s = sessions.open_session(self.t, self.editor, mode='edit', instance=self.instance)
        raw = tokens.issue(s)
        # Check-on-call: a bulk update fires no signal.
        Membership.objects.filter(user=self.editor).update(role=Role.READONLY)
        with self.assertRaises(tokens.TokenError) as cm:
            tokens.validate(raw, op='write')
        self.assertEqual(cm.exception.reason, 'permission')
        self.assertEqual(EditSession.objects.get(pk=s.pk).state, 'revoked')

        Membership.objects.filter(user=self.editor).update(role=Role.EDITOR)
        s2 = sessions.open_session(self.t, self.editor, mode='edit', instance=self.instance)
        with self.captureOnCommitCallbacks(execute=True):
            m = Membership.objects.get(user=self.editor)
            m.is_active = False
            m.save()
        self.assertEqual(EditSession.objects.get(pk=s2.pk).state, 'revoked')

    def test_document_deletion_revokes_and_late_save_is_quarantined(self):
        s = sessions.open_session(self.t, self.editor, mode='edit', instance=self.instance)
        raw = tokens.issue(s)
        Document.objects.filter(pk=self.t.pk).delete()
        s.refresh_from_db()
        self.assertEqual(s.state, 'revoked')
        self.assertIsNone(s.document_id)
        with self.assertRaises(tokens.TokenError):
            tokens.validate(raw, op='write')
        q = quarantine.keep_bytes(None, docx_with_text('late'), session=s, user=self.editor,
                                  reason='revoked')
        self.assertEqual(q.organization_id, self.org.pk)
        self.assertTrue(q.target_label)

    def test_session_expiry(self):
        s = sessions.open_session(self.t, self.editor, mode='edit', instance=self.instance)
        EditSession.objects.filter(pk=s.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        with self.assertRaises(storage.SessionRevoked):
            storage.save_new_revision(self.t, docx_with_text('x'), user=self.editor,
                                      source='editor_save', session=EditSession.objects.get(pk=s.pk))


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

class PolicyTests(OfficeTestBase):
    def test_instance_resolution(self):
        self.assertIsNone(policy.instance_for(self.org))
        a = self.make_instance(name='Alpha')
        b = self.make_instance(name='Beta')
        dedicated = self.make_instance(name='Dedicated', shared=False)
        dedicated.organizations.add(self.other_org)
        self.assertEqual(policy.instance_for(self.org), a)
        self.assertEqual(policy.instance_for(self.other_org), dedicated)
        cfg = OfficeSettings.get()
        cfg.default_instance = b
        cfg.save()
        self.assertEqual(policy.instance_for(self.org), b)
        pol = OrganizationOfficePolicy.objects.create(organization=self.org, preferred_instance=a)
        self.assertEqual(policy.instance_for(self.org), b, 'override not allowed')
        cfg.allow_org_override = True
        cfg.save()
        self.assertEqual(policy.instance_for(self.org), a)
        pol.preferred_instance = dedicated   # not available to this org
        pol.save()
        self.assertEqual(policy.instance_for(self.org), b)
        pol.office_enabled = False
        pol.save()
        self.assertIsNone(policy.instance_for(self.org))
        cfg.enabled_providers = []
        cfg.save()
        self.assertIsNone(policy.instance_for(self.other_org))

    def test_availability_is_honest(self):
        t = self.target()
        av = policy.availability(self.editor, t)
        self.assertFalse(av.can_edit)
        self.assertIn('No Office editor', av.reason)
        inst = self.make_instance()
        av = policy.availability(self.editor, t)
        self.assertFalse(av.can_edit, 'stub connector must not enable editing')
        self.assertIn('not installed', av.reason)
        self.use_fake_provider()
        self.assertTrue(policy.availability(self.editor, t).can_edit)
        av = policy.availability(self.reader, t)
        self.assertFalse(av.can_edit)
        self.assertTrue(av.can_view_in_editor)
        inst.health_status = 'down'
        inst.save()
        av = policy.availability(self.editor, t)
        self.assertFalse(av.can_edit)
        self.assertIn('not healthy', av.reason)

    def test_legacy_files_are_read_only_with_conversion(self):
        self.make_instance()
        self.use_fake_provider()
        doc = self.make_doc(title='Old', data=formats.OLE_MAGIC + b'\x00' * 64, ext='doc')
        av = policy.availability(self.editor, targets.target_for(doc))
        self.assertFalse(av.can_edit)
        self.assertTrue(av.can_view_in_editor)
        self.assertTrue(av.read_only_format)
        self.assertTrue(av.can_convert)
        self.assertFalse(policy.availability(self.reader, targets.target_for(doc)).can_convert)

    def test_default_secrets_are_refused(self):
        from .forms import EditorInstanceForm
        from .models import secret_problem
        for bad in ('developer-only-not-a-real-secret', 'verysecretstring', 'short'):
            self.assertTrue(secret_problem(bad), bad)
        self.assertEqual(secret_problem('Zq8x-very-random-secret-value'), '')
        form = EditorInstanceForm(data={
            'provider': 'onlyoffice', 'name': 'X', 'mode': 'separate_server',
            'browser_url': 'https://docs.example.com', 'callback_base_url': 'https://app.example.com',
            'shared_secret': 'developer-only-not-a-real-secret', 'max_file_mb': 100,
            'connect_timeout_s': 5, 'request_timeout_s': 30, 'conversion_timeout_s': 60,
            'shared': 'on'})
        self.assertFalse(form.is_valid())
        self.assertIn('shared_secret', form.errors)

    def test_instance_form_requires_https_and_rejects_private_keys(self):
        from .forms import EditorInstanceForm
        base = {'provider': 'onlyoffice', 'name': 'X', 'mode': 'separate_server',
                'callback_base_url': 'https://app.example.com',
                'shared_secret': 'Zq8x-very-random-secret-value', 'max_file_mb': 100,
                'connect_timeout_s': 5, 'request_timeout_s': 30, 'conversion_timeout_s': 60,
                'shared': 'on'}
        form = EditorInstanceForm(data={**base, 'browser_url': 'http://docs.example.com'})
        self.assertIn('browser_url', form.errors)
        form = EditorInstanceForm(data={**base, 'browser_url': 'https://docs.example.com',
                                        'ca_bundle': '-----BEGIN PRIVATE KEY-----\nabc'})
        self.assertIn('ca_bundle', form.errors)
        form = EditorInstanceForm(data={**base, 'mode': 'same_server',
                                        'browser_url': 'https://docs.example.com',
                                        'internal_url': 'http://127.0.0.1:8083'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertNotIn('verify_tls', form.fields)


# ---------------------------------------------------------------------------
# Outbound HTTP guard
# ---------------------------------------------------------------------------

def _addrinfo(*ips):
    def fake(host, port, *args, **kwargs):
        return [(2 if ':' not in ip else 10, 1, 6, '', (ip, port)) for ip in ips]
    return fake


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/redirect-same':
            self.send_response(302)
            self.send_header('Location', '/ok')
            self.end_headers()
            return
        if self.path == '/redirect-away':
            self.send_response(302)
            self.send_header('Location', 'http://evil.test/steal')
            self.end_headers()
            return
        if self.path == '/big':
            body = b'x' * 5000
        else:
            body = b'hello from the editor'
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class NetGuardTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = http.server.HTTPServer(('127.0.0.1', 0), _Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        super().tearDownClass()

    def inst(self, **kw):
        defaults = dict(provider='onlyoffice', name='n', mode='separate_server',
                        browser_url='https://docs.example.com/',
                        internal_url='', callback_base_url='https://app.example.com/')
        defaults.update(kw)
        return EditorInstance(**defaults)

    def test_only_the_approved_origin(self):
        i = self.inst(internal_url='https://docs.lan:8443/')
        self.assertTrue(net.allowed_fetch('https://docs.example.com/cache/files/x.docx', i))
        self.assertTrue(net.allowed_fetch('https://docs.lan:8443/healthcheck', i))
        for url in ('https://evil.example.com/x', 'http://docs.example.com/x',
                    'https://docs.example.com:444/x', 'https://user:pw@docs.example.com/x',
                    'file:///etc/passwd', 'https://docs.example.com\\@evil/x', ''):
            self.assertFalse(net.allowed_fetch(url, i), url)

    def test_metadata_and_link_local_always_blocked(self):
        for url in ('http://169.254.169.254/latest/meta-data/', 'https://[fd00:ec2::254]/'):
            i = self.inst(browser_url=url, mode='same_server')
            self.assertFalse(net.allowed_fetch(url, i), url)
        i = self.inst(mode='same_server')
        for ip in ('169.254.169.254', '169.254.10.1', 'fe80::1', 'fd00:ec2::254',
                   '100.100.100.200', '0.0.0.0', '224.0.0.1', '::ffff:169.254.169.254'):
            self.assertFalse(net.ip_allowed(ip, i), ip)
        self.assertTrue(net.ip_allowed('10.1.2.3', i), 'private allowed for the approved host')
        self.assertTrue(net.ip_allowed('127.0.0.1', i), 'loopback for same-server')
        self.assertFalse(net.ip_allowed('127.0.0.1', self.inst()), 'no loopback for a remote editor')
        self.assertFalse(net.ip_allowed('192.0.2.5', i), 'documentation range')

    def test_resolution_refuses_any_bad_record(self):
        i = self.inst()
        with mock.patch.object(net, '_getaddrinfo', _addrinfo('93.184.216.34', '169.254.169.254')):
            with self.assertRaises(net.DestinationNotAllowed):
                net.resolve('docs.example.com', 443, i)
        with mock.patch.object(net, '_getaddrinfo', _addrinfo('10.0.0.5')):
            self.assertEqual(net.resolve('docs.example.com', 443, i), ['10.0.0.5'])

    def test_dns_rebinding_cannot_switch_the_address(self):
        """The name resolves once; the connection goes to that address even if
        a second lookup would now say 169.254.169.254."""
        i = self.inst(browser_url=f'http://editor.test:{self.port}/', mode='same_server')
        answers = [_addrinfo('127.0.0.1'), _addrinfo('169.254.169.254')]
        calls = []

        def resolver(host, port, *a, **kw):
            calls.append(host)
            return answers[min(len(calls) - 1, 1)](host, port)

        real_getaddrinfo = socket.getaddrinfo

        def literal_only(host, *a, **kw):
            # urllib3 calls getaddrinfo on the pinned IP literal (no DNS);
            # any lookup of the *name* would be a second resolution.
            if host == 'editor.test':
                raise AssertionError('second lookup')
            return real_getaddrinfo(host, *a, **kw)

        with mock.patch.object(net, '_getaddrinfo', resolver), \
                mock.patch('socket.getaddrinfo', side_effect=literal_only):
            result = net.fetch(f'http://editor.test:{self.port}/ok', i, 1024)
        self.assertEqual(result.content, b'hello from the editor')
        self.assertEqual(result.peer_ip, '127.0.0.1')
        self.assertEqual(calls, ['editor.test'])

    def test_rebinding_to_metadata_on_first_lookup_is_refused(self):
        i = self.inst(browser_url=f'http://editor.test:{self.port}/', mode='same_server')
        with mock.patch.object(net, '_getaddrinfo', _addrinfo('169.254.169.254')):
            with self.assertRaises(net.DestinationNotAllowed):
                net.fetch(f'http://editor.test:{self.port}/ok', i, 1024)

    def test_redirects(self):
        i = self.inst(browser_url=f'http://editor.test:{self.port}/', mode='same_server')
        with mock.patch.object(net, '_getaddrinfo', _addrinfo('127.0.0.1')):
            r = net.fetch(f'http://editor.test:{self.port}/redirect-same', i, 1024)
            self.assertEqual(r.content, b'hello from the editor')
            self.assertEqual(len(r.redirects), 1)
            with self.assertRaises(net.DestinationNotAllowed):
                net.fetch(f'http://editor.test:{self.port}/redirect-away', i, 1024)
            with self.assertRaises(net.OfficeFetchError):
                net.fetch(f'http://editor.test:{self.port}/big', i, 100)

    def test_unapproved_host_is_never_resolved(self):
        i = self.inst()
        with mock.patch.object(net, '_getaddrinfo', side_effect=AssertionError('resolved')):
            with self.assertRaises(net.DestinationNotAllowed):
                net.fetch('https://attacker.example/x', i, 1024)


# ---------------------------------------------------------------------------
# Log redaction
# ---------------------------------------------------------------------------

class RedactionTests(TestCase):
    def test_tokens_and_jwts_are_redacted(self):
        from .logging_filters import RedactSecretsFilter, get_logger, redact
        jwt = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl'
        text = (f'GET /wopi/files/1?access_token=abc123secret&x=1 token=zzz '
                f'Authorization: Bearer {jwt} {{"token": "qqq"}}')
        out = redact(text)
        for secret in ('abc123secret', 'zzz', jwt, 'qqq'):
            self.assertNotIn(secret, out)
        self.assertIn('x=1', out)
        log = get_logger('office.onlyoffice')
        self.assertTrue(any(isinstance(f, RedactSecretsFilter) for f in log.filters))
        with self.assertLogs('office.onlyoffice', level='INFO') as cm:
            log.info('callback url %s', 'https://x/cb?access_token=SECRET1')
        self.assertNotIn('SECRET1', ''.join(cm.output))


# ---------------------------------------------------------------------------
# Views: tenant isolation, permissions, settings gates
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ViewTests(OfficeTestBase):
    def login(self, user, org=None):
        self.client.force_login(user)
        if org is not None:
            s = self.client.session
            s['current_organization_id'] = org.pk
            s.save()

    def url(self, name, t, *args):
        return reverse(f'office:{name}', args=[t.code, t.pk, *args])

    def test_other_tenants_files_are_404_everywhere(self):
        t = targets.target_for(self.make_doc())
        storage.ensure_current(t)
        self.login(self.outsider, self.other_org)
        for name, args, method in (('target_detail', (), 'get'), ('target_versions', (), 'get'),
                                   ('download', (), 'get'), ('download_revision', (1,), 'get'),
                                   ('rename', (), 'post'), ('copy', (), 'post'),
                                   ('open', (), 'post'), ('restore', (1,), 'post'),
                                   ('export_pdf', (), 'post'), ('convert', (), 'post'),
                                   ('quarantine_download', (1,), 'get')):
            resp = getattr(self.client, method)(self.url(name, t, *args), {'name': 'x', 'mode': 'view'})
            self.assertEqual(resp.status_code, 404, name)
        self.assertEqual(Document.objects.get(pk=t.pk).title, 'Plan')

    def test_reader_can_view_not_edit(self):
        t = targets.target_for(self.make_doc())
        self.login(self.reader, self.org)
        self.assertEqual(self.client.get(self.url('target_detail', t)).status_code, 200)
        resp = self.client.get(self.url('download', t))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(b''.join(resp.streaming_content), blank())
        self.assertEqual(self.client.post(self.url('rename', t), {'name': 'New'}).status_code, 404)
        self.assertEqual(self.client.post(self.url('restore', t, 1)).status_code, 404)
        self.assertEqual(Document.objects.get(pk=t.pk).title, 'Plan')

    def test_editor_rename_copy_restore(self):
        t = targets.target_for(self.make_doc())
        self.login(self.editor, self.org)
        self.client.post(self.url('rename', t), {'name': '../Budget 2027.exe'})
        self.assertEqual(Document.objects.get(pk=t.pk).title, 'Budget 2027.exe')
        self.assertEqual(targets.target_for(Document.objects.get(pk=t.pk)).filename,
                         'Budget 2027.exe.docx')
        before = Document.objects.count()
        resp = self.client.post(self.url('copy', t))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Document.objects.count(), before + 1)
        copy = Document.objects.order_by('-pk').first()
        self.assertEqual(copy.organization_id, self.org.pk)
        self.assertEqual(FileRevision.objects.get(document=copy).source, 'copy')
        storage.save_new_revision(t, docx_with_text('v2'), user=self.editor, source='upload')
        self.client.post(self.url('restore', t, 1))
        self.assertEqual(storage.current(t).revision_number, 3)
        events = set(AuditLog.objects.values_list('extra_data__office_event', flat=True))
        self.assertTrue({'rename', 'copy', 'restore'} <= events)

    def test_new_blank_document_is_stored_before_opening(self):
        self.login(self.editor, self.org)
        resp = self.client.post(reverse('office:new_document', args=['xlsx']), {'title': 'Q3 numbers'})
        self.assertEqual(resp.status_code, 302)
        doc = Document.objects.get(title='Q3 numbers')
        self.assertEqual(doc.organization_id, self.org.pk)
        rev = FileRevision.objects.get(document=doc)
        self.assertEqual((rev.revision_number, rev.source), (1, 'create'))
        self.assertEqual(doc.file.name, rev.file.name)
        self.login(self.reader, self.org)
        self.client.post(reverse('office:new_document', args=['docx']), {'title': 'nope'})
        self.assertFalse(Document.objects.filter(title='nope').exists())
        self.assertEqual(self.client.post(reverse('office:new_document', args=['exe'])).status_code, 404)

    def test_new_attachment_on_asset(self):
        from assets.models import Asset
        asset = Asset.objects.create(organization=self.org, name='Server 1')
        other = Asset.objects.create(organization=self.other_org, name='Theirs')
        self.login(self.editor, self.org)
        self.client.post(reverse('office:new_attachment', args=['docx']),
                         {'entity_type': 'asset', 'entity_id': asset.pk, 'title': 'Runbook'})
        att = Attachment.objects.get(entity_type='asset', entity_id=asset.pk)
        self.assertEqual(att.original_filename, 'Runbook.docx')
        resp = self.client.post(reverse('office:new_attachment', args=['docx']),
                                {'entity_type': 'asset', 'entity_id': other.pk, 'title': 'x'})
        self.assertEqual(resp.status_code, 404)

    def test_document_page_shows_disabled_edit_with_reason(self):
        doc = self.make_doc()
        self.login(self.editor, self.org)
        resp = self.client.get(reverse('docs:document_detail', args=[doc.slug]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'No Office editor is configured')
        self.assertContains(resp, 'disabled aria-disabled="true"')
        self.assertNotContains(resp, reverse('office:open', args=['doc', doc.pk]))

    def test_open_and_editor_page(self):
        inst = self.make_instance()
        self.use_fake_provider()
        doc = self.make_doc()
        self.login(self.editor, self.org)
        resp = self.client.get(reverse('docs:document_detail', args=[doc.slug]))
        self.assertContains(resp, reverse('office:open', args=['doc', doc.pk]))
        resp = self.client.post(reverse('office:open', args=['doc', doc.pk]), {'mode': 'edit'})
        session = EditSession.objects.get(document=doc)
        self.assertRedirects(resp, reverse('office:editor', args=[session.pk]),
                             fetch_redirect_response=False)
        resp = self.client.get(reverse('office:editor', args=[session.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'office-save-status')
        self.assertContains(resp, 'https://docs.example.com/web-apps/api.js')
        self.assertNotContains(resp, 'evil.example')
        csp = resp.get('Content-Security-Policy') or resp.get('Content-Security-Policy-Report-Only')
        self.assertIn('https://docs.example.com', csp)
        self.assertNotIn('evil.example', csp)
        status = self.client.get(reverse('office:editor_status', args=[session.pk])).json()
        self.assertEqual(status['state'], 'open')
        self.assertEqual(status['currentRevision'], 1)
        # Someone else's session is a 404.
        self.login(self.owner, self.org)
        self.assertEqual(self.client.get(reverse('office:editor', args=[session.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('office:editor_status', args=[session.pk])).status_code, 404)
        # Reader can open read-only but not edit.
        self.login(self.reader, self.org)
        self.client.post(reverse('office:open', args=['doc', doc.pk]), {'mode': 'edit'})
        self.assertFalse(EditSession.objects.filter(document=doc, user=self.reader).exists())
        self.client.post(reverse('office:open', args=['doc', doc.pk]), {'mode': 'view'})
        self.assertEqual(EditSession.objects.get(document=doc, user=self.reader).mode, 'view')
        self.assertEqual(inst.sessions.count(), 2)

    def test_editor_page_with_stub_connector_fails_honestly(self):
        inst = self.make_instance()
        t = targets.target_for(self.make_doc())
        s = sessions.open_session(t, self.editor, mode='edit', instance=inst)
        self.login(self.editor, self.org)
        resp = self.client.get(reverse('office:editor', args=[s.pk]))
        self.assertContains(resp, 'The editor cannot be opened')
        self.assertEqual(EditSession.objects.get(pk=s.pk).state, 'failed')

    def test_export_pdf_only_when_supported(self):
        doc = self.make_doc()
        self.login(self.editor, self.org)
        resp = self.client.post(reverse('office:export_pdf', args=['doc', doc.pk]))
        self.assertEqual(resp.status_code, 302)
        self.make_instance()
        self.use_fake_provider()
        resp = self.client.post(reverse('office:export_pdf', args=['doc', doc.pk]))
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertTrue(AuditLog.objects.filter(extra_data__office_event='export').exists())

    def test_convert_legacy_to_new_copy(self):
        self.make_instance()
        self.use_fake_provider()
        doc = self.make_doc(title='Legacy', data=formats.OLE_MAGIC + b'\x00' * 64, ext='doc')
        self.login(self.editor, self.org)
        self.client.post(reverse('office:convert', args=['doc', doc.pk]))
        new = Document.objects.get(title='Legacy', file_type=formats.MIME['docx'])
        self.assertEqual(FileRevision.objects.get(document=new).source, 'convert')
        self.assertEqual(Document.objects.get(pk=doc.pk).file_type, formats.MIME['doc'])

    def test_settings_gates(self):
        inst = self.make_instance()
        # Organization admin: no platform settings, no secrets.
        self.login(self.owner, self.org)
        for name, args in (('settings', ()), ('instance_edit', (inst.pk,)),
                           ('instance_diagnostics', (inst.pk,)), ('install', ()),
                           ('quarantine_list', ())):
            resp = self.client.get(reverse(f'office:{name}', args=args))
            self.assertIn(resp.status_code, (302, 403), name)
        resp = self.client.get(reverse('office:org_policy'))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        for secret in ('a-long-random-test-secret-123', 'docs.example.com', 'app.example.com'):
            self.assertNotIn(secret, body)
        self.assertContains(resp, inst.name)
        self.client.post(reverse('office:org_policy'), {'office_enabled': ''})
        self.assertFalse(OrganizationOfficePolicy.objects.get(organization=self.org).office_enabled)
        # A reader cannot change the policy.
        self.login(self.reader, self.org)
        self.assertEqual(self.client.get(reverse('office:org_policy')).status_code, 403)
        # Superuser: the secret is never rendered back.
        self.login(self.su, self.org)
        resp = self.client.get(reverse('office:instance_edit', args=[inst.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'a-long-random-test-secret-123')

    def test_superuser_instance_edit_is_audited_without_the_secret(self):
        self.login(self.su, self.org)
        resp = self.client.post(reverse('office:instance_new'), {
            'provider': 'onlyoffice', 'name': 'New docs', 'mode': 'separate_server',
            'browser_url': 'https://docs.example.org', 'callback_base_url': 'https://app.example.org',
            'shared_secret': 'Xy7-super-random-new-secret', 'max_file_mb': 50,
            'connect_timeout_s': 5, 'request_timeout_s': 30, 'conversion_timeout_s': 60,
            'shared': 'on'})
        self.assertEqual(resp.status_code, 302)
        inst = EditorInstance.objects.get(name='New docs')
        self.assertEqual(inst.shared_secret, 'Xy7-super-random-new-secret')
        self.assertTrue(inst.verify_tls)
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute('SELECT shared_secret FROM office_editor_instances WHERE id=%s', [inst.pk])
            self.assertTrue(cur.fetchone()[0].startswith('enc2$'))
        for row in AuditLog.objects.all():
            self.assertNotIn('Xy7-super-random-new-secret', str(row.extra_data) + row.description)

    def test_diagnostics_and_round_trip_report_not_run_for_stub(self):
        inst = self.make_instance()
        self.login(self.su)
        with mock.patch.object(net, '_getaddrinfo', _addrinfo('93.184.216.34')), \
                mock.patch.object(net, 'fetch', side_effect=net.OfficeFetchError('Timed out')):
            resp = self.client.post(reverse('office:instance_diagnostics', args=[inst.pk]),
                                    {'action': 'diagnostics'})
        self.assertContains(resp, 'not run')
        self.assertContains(resp, 'No malware scanner is configured')
        resp = self.client.post(reverse('office:instance_diagnostics', args=[inst.pk]),
                                {'action': 'round_trip'})
        self.assertContains(resp, 'Create a disposable document')
        self.assertContains(resp, 'not passed')
        f = OfficeFile.objects.get(purpose='diagnostic')
        self.assertIsNone(f.organization_id)
        self.assertFalse(targets.OfficeFileTarget(f).can_view(self.owner))
        self.assertTrue(AuditLog.objects.filter(extra_data__office_event='round_trip').exists())
        resp = self.client.post(reverse('office:instance_health', args=[inst.pk]))
        inst.refresh_from_db()
        self.assertEqual(inst.health_status, 'down')

    def test_install_guidance_is_sanitised(self):
        self.login(self.su)
        resp = self.client.get(reverse('office:install'), {
            'provider': 'onlyoffice', 'mode': 'same_server',
            'editor_host': 'docs.example.com; rm -rf /'})
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'rm -rf')
        self.assertContains(resp, 'office_setup')
        self.assertContains(resp, '--secret-file')

    def test_templates_flow(self):
        self.login(self.owner, self.org)
        upload = SimpleUploadedFile('Letter.docx', blank('docx'))
        self.client.post(reverse('office:template_list'), {'file': upload, 'scope': 'org',
                                                           'description': 'Letterhead'})
        tpl = OfficeFile.objects.get(purpose='template', name='Letter.docx')
        self.assertEqual(tpl.organization_id, self.org.pk)
        bad = SimpleUploadedFile('Evil.docx', b'not a zip')
        self.client.post(reverse('office:template_list'), {'file': bad, 'scope': 'org'})
        self.assertFalse(OfficeFile.objects.filter(name='Evil.docx').exists())
        self.client.post(reverse('office:template_list'),
                         {'file': SimpleUploadedFile('G.docx', blank()), 'scope': 'global'})
        self.assertFalse(OfficeFile.objects.filter(name='G.docx').exists(), 'global is superuser-only')
        self.login(self.editor, self.org)
        self.client.post(reverse('office:new_from_template'), {'template': tpl.pk, 'title': 'To ACME'})
        doc = Document.objects.get(title='To ACME')
        self.assertEqual(doc.organization_id, self.org.pk)
        self.login(self.outsider, self.other_org)
        resp = self.client.post(reverse('office:new_from_template'), {'template': tpl.pk})
        self.assertEqual(resp.status_code, 404)

    def test_audit_middleware_redacts_secret_fields(self):
        from audit.middleware import _SENSITIVE_KEY
        for key in ('shared_secret', 'access_token', 'client_secret', 'password'):
            self.assertTrue(_SENSITIVE_KEY.search(key), key)
        self.assertFalse(_SENSITIVE_KEY.search('title'))


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------

class MigrationTests(TestCase):
    def test_no_conflicts_and_no_missing_migrations(self):
        from django.core.management import call_command
        from django.db.migrations.loader import MigrationLoader
        self.assertEqual(MigrationLoader(None, ignore_no_migrations=True).detect_conflicts(), {})
        out = io.StringIO()
        try:
            call_command('makemigrations', '--check', '--dry-run', stdout=out, stderr=out)
        except SystemExit:
            self.fail('Missing migrations:\n' + out.getvalue())

    def test_secret_columns_are_protected(self):
        from django.core.management import call_command
        out = io.StringIO()
        try:
            call_command('check_secrets_storage', '--schema-only', stdout=out)
        except SystemExit:
            self.fail(out.getvalue())
