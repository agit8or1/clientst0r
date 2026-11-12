"""The verified upgrade pipeline (core/upgrade/).

Covers: the journal and how an interrupted upgrade is recognised; snapshots
(owner-only, keys inside, restore-tested, tamper-evident, restorable,
exportable); pinned revisions and release-tag signatures in a throwaway git
repository; the Stable/Preview channel decision and GitHub failures; the
preflight checks; the migration doctor on a migration that ran but was not
recorded (issues #128, #129); the Apply pipeline end to end with a stand-in
update script; and the Settings -> Updates endpoints.

Nothing here touches the real install: every path (backups, media, .env,
database files, git repositories) is a temporary directory.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.upgrade import apply as upgrade_apply
from core.upgrade import channels, doctor, journal, preflight, revision, snapshot
from core.upgrade.revision import RevisionError, Target

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]

KEY_A = base64.b64encode(b'A' * 32).decode()
KEY_B = base64.b64encode(b'B' * 32).decode()
SHA1 = '1' * 40
SHA2 = '2' * 40


def _mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


class _TmpMixin:
    def make_tmp(self):
        tmp = Path(tempfile.mkdtemp(prefix='cs0r-upgrade-test-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        return tmp


# ---------------------------------------------------------------------------
# journal
# ---------------------------------------------------------------------------

class JournalTests(_TmpMixin, SimpleTestCase):
    def setUp(self):
        self.tmp = self.make_tmp()
        o = override_settings(UPGRADE_BACKUP_DIR=self.tmp / 'backups')
        o.enable()
        self.addCleanup(o.disable)

    def test_journal_is_private(self):
        journal.begin(target={'kind': 'release', 'ref': 'v1.2.3', 'sha': SHA1})
        self.assertEqual(_mode(journal.journal_path()), 0o600)
        self.assertEqual(_mode(journal.backup_root()), 0o700)
        self.assertEqual(journal.read()['status'], 'running')

    def test_live_process_means_running(self):
        journal.begin()
        journal.write({**journal.read(), 'pid': os.getpid()})
        a = journal.assess()
        self.assertEqual(a['state'], 'running')
        self.assertFalse(a['needs_recovery'])

    def _dead(self, stage):
        journal.begin()
        journal.stage(stage)
        journal.write({**journal.read(), 'pid': 999999999, 'script_pid': 999999998})
        return journal.assess()

    def test_killed_during_migration_needs_recovery(self):
        a = self._dead('migrating')
        self.assertEqual(a['state'], 'interrupted')
        self.assertTrue(a['needs_recovery'])
        self.assertTrue(a['db_touched'])
        self.assertIn('UPGRADE_AND_RECOVERY', a['message'])

    def test_killed_before_touching_anything_needs_nothing(self):
        a = self._dead('preflight_ok')
        self.assertEqual(a['state'], 'interrupted')
        self.assertFalse(a['needs_recovery'])

    def test_killed_after_checkout_before_migrate(self):
        a = self._dead('deps_installed')
        self.assertTrue(a['needs_recovery'])
        self.assertFalse(a['db_touched'])

    def test_completed_and_recovered(self):
        journal.begin()
        journal.stage('complete')
        journal.finish('complete')
        self.assertFalse(journal.assess()['needs_recovery'])
        journal.finish('recovered')
        self.assertFalse(journal.assess()['needs_recovery'])


# ---------------------------------------------------------------------------
# snapshots
# ---------------------------------------------------------------------------

class SnapshotTests(_TmpMixin, SimpleTestCase):
    """A disposable SQLite database with a vault table, uploads and .env."""

    def setUp(self):
        self.tmp = self.make_tmp()
        self.base = self.tmp / 'base'
        self.base.mkdir()
        (self.base / '.env').write_text(f"APP_MASTER_KEY={KEY_A}\nSECRET_KEY=s\n")
        self.media = self.tmp / 'media'
        (self.media / 'attachments').mkdir(parents=True)
        (self.media / 'attachments' / 'a.txt').write_bytes(b'hello attachment')
        self.db = self.tmp / 'db.sqlite3'
        self._make_db(KEY_A)
        o = override_settings(
            BASE_DIR=self.base, MEDIA_ROOT=str(self.media), UPGRADE_BACKUP_DIR=self.tmp / 'backups',
            APP_MASTER_KEY=KEY_A, APP_MASTER_KEY_PREVIOUS='', SECRET_KEY='test-secret-key-xyz',
            API_KEY_SECRET='test-api-secret', EMERGENCY_RESTART_SECRET='', AI_GATEWAY_KEY_DIR='')
        o.enable()
        self.addCleanup(o.disable)
        p = mock.patch.object(snapshot, '_db', return_value={
            'ENGINE': 'django.db.backends.sqlite3', 'NAME': str(self.db)})
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(snapshot, 'current_revision', return_value=SHA1)
        p.start()
        self.addCleanup(p.stop)

    def _make_db(self, key):
        from vault.encryption import using_master_keys
        from vault.encryption_v2 import encrypt_password
        with using_master_keys(key, [key]):
            blob = encrypt_password('s3cret', org_id=7)
        con = sqlite3.connect(str(self.db))
        con.executescript(
            'CREATE TABLE django_migrations (id INTEGER PRIMARY KEY, app TEXT, name TEXT, applied TEXT);'
            "INSERT INTO django_migrations (app, name, applied) VALUES ('core', '0001_initial', 'x');"
            'CREATE TABLE passwords (id INTEGER PRIMARY KEY, organization_id INTEGER, '
            'encrypted_password TEXT, encrypted_notes TEXT);'
            'CREATE TABLE tickets (id INTEGER PRIMARY KEY, subject TEXT);'
            "INSERT INTO tickets (subject) VALUES ('before upgrade');")
        con.execute("INSERT INTO passwords (organization_id, encrypted_password, encrypted_notes) "
                    "VALUES (7, ?, '')", (blob,))
        con.commit()
        con.close()

    def _snap(self):
        snap = snapshot.create(reason='test')
        report = snapshot.verify(snap)
        return snap, report

    def test_backup_is_owner_only_and_carries_the_keys(self):
        snap, report = self._snap()
        self.assertTrue(report['ok'], report)
        self.assertEqual(report['level'], 'restore-test')
        self.assertEqual(_mode(snap), 0o700)
        for p in snap.iterdir():
            self.assertEqual(_mode(p), 0o600, p.name)
        keys = snapshot.parse_env_file(snap / 'keys.env')
        self.assertEqual(keys['APP_MASTER_KEY'], KEY_A)
        self.assertEqual(keys['SECRET_KEY'], 'test-secret-key-xyz')
        self.assertTrue((snap / 'env.file').is_file())
        names = {c['name']: c for c in report['checks']}
        self.assertIn('1 password(s)', names['vault']['detail'])
        self.assertIn('1 uploaded file(s)', names['media']['detail'])
        self.assertEqual(snapshot.load_manifest(snap)['git_sha'], SHA1)
        self.assertTrue(snapshot.is_verified(snap)[0])

    def test_backup_records_the_revision_that_matches_the_database(self):
        snap = snapshot.create(reason='legacy', code_sha=SHA2, code_version='3.17.640')
        m = snapshot.load_manifest(snap)
        self.assertEqual(m['git_sha'], SHA2)
        self.assertEqual(m['app_version'], '3.17.640')

    def test_vault_that_the_stored_key_cannot_read_fails_verification(self):
        self.db.unlink()
        self._make_db(KEY_B)            # encrypted with another key than APP_MASTER_KEY
        snap, report = self._snap()
        self.assertFalse(report['ok'])
        self.assertFalse(snapshot.is_verified(snap)[0])

    def test_tampering_after_verification_is_detected(self):
        snap, _ = self._snap()
        with open(snap / 'media.tar', 'ab') as f:
            f.write(b'junk')
        ok, detail = snapshot.is_verified(snap)
        self.assertFalse(ok)
        self.assertIn('checksum', detail)

    def test_quick_check_skips_hashing_but_catches_size_changes(self):
        snap, _ = self._snap()
        with mock.patch.object(snapshot, '_sha256', wraps=snapshot._sha256) as h:
            self.assertTrue(snapshot.is_verified(snap, quick=True)[0])
        hashed = {Path(c.args[0]).name for c in h.call_args_list}
        self.assertEqual(hashed, {'manifest.json'})
        with open(snap / 'media.tar', 'ab') as f:
            f.write(b'junk')
        ok, detail = snapshot.is_verified(snap, quick=True)
        self.assertFalse(ok)
        self.assertIn('size changed', detail)

    def test_world_readable_backup_fails_verification(self):
        snap = snapshot.create(reason='test')
        os.chmod(snap / 'keys.env', 0o644)
        report = snapshot.verify(snap)
        self.assertFalse(report['ok'])
        self.assertIn('permissions', [c['name'] for c in report['checks'] if not c['ok']])

    def test_restore_puts_database_and_uploads_back(self):
        snap, _ = self._snap()
        con = sqlite3.connect(str(self.db))
        con.execute("INSERT INTO tickets (subject) VALUES ('half-migrated junk')")
        con.execute('CREATE TABLE psa_new_table (id INTEGER)')   # what a partial migration leaves
        con.commit()
        con.close()
        (self.media / 'attachments' / 'a.txt').unlink()
        (self.media / 'stray.bin').write_bytes(b'x')
        with mock.patch('django.db.connections.close_all'):
            snapshot.restore(snap, code=False)
        con = sqlite3.connect(str(self.db))
        self.assertEqual(con.execute('SELECT subject FROM tickets').fetchall(), [('before upgrade',)])
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        con.close()
        self.assertNotIn('psa_new_table', tables)
        self.assertEqual((self.media / 'attachments' / 'a.txt').read_bytes(), b'hello attachment')
        self.assertFalse((self.media / 'stray.bin').exists())
        self.assertTrue(list(self.tmp.glob('db.sqlite3.before-restore-*')))
        self.assertTrue(list(self.tmp.glob('media.before-restore-*')))

    def test_restore_refuses_when_the_instance_key_differs(self):
        snap, _ = self._snap()
        with override_settings(APP_MASTER_KEY=KEY_B):
            with self.assertRaisesMessage(snapshot.SnapshotError, '--restore-keys'):
                snapshot.restore(snap, code=False)

    def test_restore_refuses_an_unverified_backup(self):
        snap = snapshot.create(reason='test')
        with self.assertRaisesMessage(snapshot.SnapshotError, 'not a verified backup'):
            snapshot.restore(snap, code=False)

    def test_export_and_import_round_trip(self):
        snap, _ = self._snap()
        dest = self.tmp / 'off-host.cs0r'
        snapshot.export(snap, dest, 'correct horse battery')
        self.assertEqual(_mode(dest), 0o600)
        self.assertNotIn(KEY_A.encode(), dest.read_bytes())
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.import_export(dest, 'wrong passphrase!!')
        shutil.rmtree(snap)
        back = snapshot.import_export(dest, 'correct horse battery')
        self.assertEqual(back.name, snap.name)
        self.assertTrue(snapshot.verify(back)['ok'])


# ---------------------------------------------------------------------------
# pinned revisions and signed release tags
# ---------------------------------------------------------------------------

def _run(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True,
                   env={**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@x.invalid',
                        'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@x.invalid',
                        'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'})


@mock.patch.dict(os.environ, {'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'})
class RevisionTests(_TmpMixin, SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not shutil.which('git') or not shutil.which('ssh-keygen'):
            raise __import__('unittest').SkipTest('git and ssh-keygen required')

    def setUp(self):
        t = self.make_tmp()
        keys = t / 'keys'
        keys.mkdir()
        for k in ('trusted', 'other'):
            _run('ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', k, '-f', str(keys / k))
        self.signers = keys / 'allowed_signers'
        self.signers.write_text('releases@test namespaces="git" ' + (keys / 'trusted.pub').read_text())
        src = t / 'src'
        src.mkdir()
        _run('git', 'init', '-q', '-b', 'main', cwd=src)
        (src / 'config').mkdir()
        (src / 'config' / 'version.py').write_text("VERSION = '3.99.0'\n")
        _run('git', 'add', '-A', cwd=src)
        _run('git', 'commit', '-q', '-m', 'release', cwd=src)
        self.sha = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=src, capture_output=True,
                                  text=True).stdout.strip()

        def tag(name, key=None):
            if key:
                _run('git', '-c', 'gpg.format=ssh', '-c', f'user.signingkey={keys / key}.pub',
                     'tag', '-s', '-m', name, name, cwd=src)
            else:
                _run('git', 'tag', '-a', '-m', name, name, cwd=src)
        tag('v3.99.0', 'trusted')
        tag('v3.99.1')
        tag('v3.99.2', 'other')
        bare = t / 'origin.git'
        _run('git', 'clone', '-q', '--bare', str(src), str(bare))
        self.clone = t / 'install'
        _run('git', 'clone', '-q', '--no-tags', str(bare), str(self.clone))
        o = override_settings(BASE_DIR=self.clone, RELEASE_SIGNERS_FILE=str(self.signers))
        o.enable()
        self.addCleanup(o.disable)

    def _fetched(self, ref):
        t = Target('release', ref, self.sha)
        revision.check_remote_unchanged(t)
        revision.fetch(t)
        return t

    def test_signed_release_by_a_trusted_key_verifies(self):
        t = self._fetched('v3.99.0')
        revision.verify_release_tag(t)
        self.assertEqual(revision.version_at(self.sha), '3.99.0')

    def test_unsigned_tag_is_refused(self):
        t = self._fetched('v3.99.1')
        with self.assertRaisesMessage(RevisionError, 'not signed by a trusted release key'):
            revision.verify_release_tag(t)

    def test_tag_signed_by_an_untrusted_key_is_refused(self):
        t = self._fetched('v3.99.2')
        with self.assertRaisesMessage(RevisionError, 'not signed by a trusted release key'):
            revision.verify_release_tag(t)

    def test_moved_ref_is_refused_before_anything_changes(self):
        with self.assertRaisesMessage(RevisionError, 'Nothing was changed'):
            revision.check_remote_unchanged(Target('release', 'v3.99.0', SHA1))
        with self.assertRaisesMessage(RevisionError, 'not the reviewed'):
            revision.check_remote_unchanged(Target('preview', 'main', SHA1))

    def test_fetch_checks_the_sha(self):
        with self.assertRaisesMessage(RevisionError, 'not the reviewed'):
            revision.fetch(Target('release', 'v3.99.0', SHA1))

    def test_target_validation(self):
        for bad in (Target('release', 'v3.99.0', 'abc'), Target('release', 'main', SHA1),
                    Target('preview', 'v3.99.0', SHA1), Target('lts', 'v1.0.0', SHA1)):
            with self.assertRaises(RevisionError):
                bad.validate()
        Target('release', 'v3.99.0', SHA1).validate()
        Target('preview', 'main', SHA1).validate()


# ---------------------------------------------------------------------------
# channels
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, status, data=None, text='', headers=None):
        self.status_code, self._data, self.text, self.headers = status, data, text, headers or {}

    def json(self):
        return self._data


def _github(stable='3.17.640', main_version='3.17.659', ahead=19, extra_releases=()):
    tag_obj = 'a' * 40
    releases = [{'tag_name': f'v{stable}', 'name': f'v{stable}', 'draft': False, 'prerelease': False,
                 'published_at': '2026-11-07T00:00:00Z', 'html_url': 'https://example.invalid/r'},
                *extra_releases]

    def get(url, headers=None, timeout=None):
        if '/releases?' in url:
            return _Resp(200, releases)
        if '/git/ref/tags/' in url:
            return _Resp(200, {'object': {'type': 'tag', 'sha': tag_obj}})
        if f'/git/tags/{tag_obj}' in url:
            return _Resp(200, {'object': {'sha': SHA1}, 'verification': {'signature': 'sig'}})
        if url.endswith('/commits/main'):
            return _Resp(200, {'sha': SHA2, 'commit': {'message': 'feat: newest\n\nbody',
                                                       'committer': {'date': '2026-11-10'}}})
        if url.endswith('/config/version.py'):
            return _Resp(200, text=f"VERSION = '{main_version}'\n")
        if '/compare/' in url:
            return _Resp(200, {'ahead_by': ahead, 'behind_by': 0,
                               'commits': [{'sha': SHA2, 'commit': {'message': 'feat: newest'}}]})
        return _Resp(404)
    return get


class ChannelTests(TestCase):
    def setUp(self):
        channels.clear_cache()
        from django.core.cache import cache
        cache.delete(channels.CACHE_KEY_LAST_GOOD)

    def _resolve(self, installed_version, channel='stable', get=None, installed_sha=SHA1):
        from core.models import SystemSetting
        SystemSetting.get_settings()
        SystemSetting.objects.filter(pk=1).update(update_channel=channel)
        inst = {'version': installed_version, 'sha': installed_sha, 'branch': 'main',
                'clean': True, 'is_git': True}
        with mock.patch.object(channels, 'installed', return_value=inst), \
                mock.patch.object(channels.requests, 'get', side_effect=get or _github()):
            return channels.resolve(force_refresh=True)

    def test_behind_stable_offers_the_signed_release(self):
        r = self._resolve('3.17.558', installed_sha='9' * 40)
        self.assertEqual(r['target'], {'kind': 'release', 'ref': 'v3.17.640', 'sha': SHA1,
                                       'version': '3.17.640'})
        self.assertEqual(r['relation_to_stable'], 'behind')
        self.assertEqual(r['preview']['ahead_of_stable'], 19)
        self.assertEqual(r['preview']['message'], 'feat: newest')
        self.assertTrue(r['stable']['has_signature'])
        from core.models import SystemSetting
        self.assertEqual(SystemSetting.objects.get(pk=1).latest_release_version, '3.17.640')

    def test_ahead_of_stable_on_stable_offers_nothing(self):
        r = self._resolve('3.17.659', installed_sha='9' * 40)
        self.assertIsNone(r['target'])
        self.assertEqual(r['relation_to_stable'], 'ahead')

    def test_preview_channel_offers_main_by_sha(self):
        r = self._resolve('3.17.650', channel='preview', installed_sha='9' * 40)
        self.assertEqual(r['target']['kind'], 'preview')
        self.assertEqual(r['target']['ref'], 'main')
        self.assertEqual(r['target']['sha'], SHA2)
        r = self._resolve('3.17.659', channel='preview', installed_sha=SHA2)
        self.assertIsNone(r['target'], 'already on main HEAD')

    def test_drafts_prereleases_and_odd_tags_are_not_stable(self):
        extra = [{'tag_name': 'v3.17.700', 'draft': True}, {'tag_name': 'v3.17.701', 'prerelease': True},
                 {'tag_name': 'nightly-9'}]
        r = self._resolve('3.17.558', get=_github(extra_releases=extra))
        self.assertEqual(r['stable']['tag'], 'v3.17.640')

    def test_github_down_is_reported_not_raised(self):
        import requests

        def down(*a, **k):
            raise requests.ConnectionError('no route')
        r = self._resolve('3.17.558', get=down)
        self.assertIsNone(r['target'])
        self.assertIn('Cannot connect to GitHub', r['error'])
        self.assertFalse(r['stale'])

    def test_rate_limit_falls_back_to_the_last_good_answer(self):
        self._resolve('3.17.558')
        limited = (lambda *a, **k: _Resp(403, {}, headers={'X-RateLimit-Remaining': '0'}))
        r = self._resolve('3.17.558', get=limited)
        self.assertIn('rate limit', r['error'])
        self.assertTrue(r['stale'])
        self.assertEqual(r['target']['ref'], 'v3.17.640')


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------

class PreflightTests(_TmpMixin, TestCase):
    def setUp(self):
        self.tmp = self.make_tmp()
        o = override_settings(MEDIA_ROOT=str(self.tmp / 'media'), UPGRADE_BACKUP_DIR=self.tmp / 'b')
        o.enable()
        self.addCleanup(o.disable)
        (self.tmp / 'media').mkdir()

    def test_media_and_backup_destination_writable(self):
        self.assertEqual(preflight.check_media().status, 'ok')
        self.assertEqual(preflight.check_backup_destination().status, 'ok')

    def test_unwritable_media_fails(self):
        if os.geteuid() == 0:
            self.skipTest('root can write anywhere')
        os.chmod(self.tmp / 'media', 0o500)
        self.addCleanup(os.chmod, self.tmp / 'media', 0o700)
        c = preflight.check_media()
        self.assertEqual(c.status, 'fail')

    def test_missing_or_invalid_master_key_fails(self):
        with override_settings(APP_MASTER_KEY='not-a-key'):
            with mock.patch.dict(os.environ, {'APP_MASTER_KEY': ''}):
                self.assertEqual(preflight.check_keys().status, 'fail')

    def test_database_reachable(self):
        self.assertEqual(preflight.check_database().status, 'ok')

    def test_a_crashing_check_fails_closed(self):
        with mock.patch.object(preflight, 'check_disk', side_effect=RuntimeError('boom')), \
                mock.patch.object(preflight, 'check_git',
                                  return_value=preflight.Check('code checkout', 'ok', '')), \
                mock.patch.object(preflight, 'check_pending_migrations',
                                  return_value=preflight.Check('pending migrations', 'ok', '')):
            checks = preflight.run(None, installed_sha='', deps=False)
        bad = preflight.failed(checks)
        self.assertTrue(any('boom' in c.detail for c in bad), [c.as_dict() for c in checks])


# ---------------------------------------------------------------------------
# migration doctor
# ---------------------------------------------------------------------------

class MigrationDoctorTests(TestCase):
    def test_applied_but_unrecorded_migration_is_recognised(self):
        """#128/#129: the schema change is in, the django_migrations row is not."""
        from django.db.migrations.recorder import MigrationRecorder
        MigrationRecorder.Migration.objects.filter(
            app='core', name='0082_systemsetting_update_channel').delete()
        findings = {f.label: f for f in doctor.diagnose()}
        f = findings['core.0082_systemsetting_update_channel']
        self.assertEqual(f.state, 'applied_unrecorded')
        self.assertIn('--fake', f.advice)
        self.assertIn('upgrade_restore', f.advice)
        lines = '\n'.join(doctor.report_lines([f]))
        self.assertIn('[present] add column', lines)

    def test_check_mode_fails_on_a_migration_already_in_the_schema(self):
        """The update script refuses to back up or migrate on top of this."""
        from io import StringIO
        from django.core.management import call_command
        from django.db.migrations.recorder import MigrationRecorder
        call_command('migration_doctor', '--check', stdout=StringIO())   # clean: no exit
        MigrationRecorder.Migration.objects.filter(
            app='core', name='0082_systemsetting_update_channel').delete()
        out = StringIO()
        with self.assertRaises(SystemExit) as cm:
            call_command('migration_doctor', '--check', stdout=out)
        self.assertEqual(cm.exception.code, 1)
        self.assertIn('core.0082_systemsetting_update_channel: applied unrecorded', out.getvalue())

    def test_missing_column_is_reported_missing(self):
        from django.db import connection, models
        from django.db.migrations import operations as ops
        from django.db.migrations.loader import MigrationLoader
        state = MigrationLoader(connection).project_state(('core', '0082_systemsetting_update_channel'))
        op = ops.AddField('systemsetting', 'not_there_yet', models.CharField(max_length=3, default=''))
        tables = doctor._schema()
        desc, present = doctor._check_operation(op, 'core', state, tables)
        self.assertFalse(present, desc)
        self.assertEqual(doctor.diagnose(), [])   # everything else is applied

    def test_partial_advice_never_offers_fake(self):
        advice = doctor._advice('psa', '0027_x', 'partial', False, 'mysql')
        self.assertIn('Do not --fake', advice)
        self.assertNotIn('migrate psa', advice)
        self.assertIn('MySQL/MariaDB', advice)


# ---------------------------------------------------------------------------
# the Apply pipeline (stand-in update script, real journal and audit)
# ---------------------------------------------------------------------------

# What the real update script does before migrating: record the stage.
MIGRATING = ('"$CLIENTST0R_PYTHON" -c "import json, sys; p = sys.argv[1]; d = json.load(open(p)); '
             'd[\'stage\'] = \'migrating\'; json.dump(d, open(p, \'w\'))" "$CLIENTST0R_JOURNAL"\n')


class ApplyPipelineTests(_TmpMixin, TestCase):
    def setUp(self):
        self.tmp = self.make_tmp()
        o = override_settings(UPGRADE_BACKUP_DIR=self.tmp / 'backups')
        o.enable()
        self.addCleanup(o.disable)
        self.snap = self.tmp / 'backups' / 'snapshot-x'
        self.patches = {
            'is_git_install': mock.patch.object(upgrade_apply, 'is_git_install', return_value=True),
            'head_sha': mock.patch.object(upgrade_apply, 'head_sha', return_value=SHA1),
            'check_remote_unchanged': mock.patch.object(upgrade_apply, 'check_remote_unchanged'),
            'fetch': mock.patch.object(upgrade_apply, 'fetch'),
            'verify_release_tag': mock.patch.object(upgrade_apply, 'verify_release_tag',
                                                    return_value='Good "git" signature'),
            'version_at': mock.patch.object(upgrade_apply, 'version_at', return_value='99.0.0'),
            'preflight': mock.patch.object(upgrade_apply.preflight, 'run', return_value=[
                preflight.Check('disk space', 'ok', 'plenty')]),
            'create': mock.patch.object(upgrade_apply.snapshot, 'create', return_value=self.snap),
            'verify': mock.patch.object(upgrade_apply.snapshot, 'verify', return_value={
                'ok': True, 'level': 'restore-test', 'checks': []}),
        }
        self.m = {k: p.start() for k, p in self.patches.items()}
        for p in self.patches.values():
            self.addCleanup(p.stop)
        self.target = Target('release', 'v99.0.0', SHA2)

    def _script(self, body):
        path = self.tmp / f'update-{len(list(self.tmp.iterdir()))}.sh'
        path.write_text('#!/bin/bash\n' + body)
        os.chmod(path, 0o700)
        return mock.patch.object(upgrade_apply, 'extract_to_private_file', return_value=path)

    def test_success_runs_the_target_revisions_script_with_the_pinned_sha(self):
        with self._script('echo "sha=$CLIENTST0R_TARGET_SHA backup=$CLIENTST0R_VERIFIED_BACKUP"\n'
                          'echo "Update complete!"\n'):
            r = upgrade_apply.run(self.target)
        self.assertTrue(r['success'], r)
        out = '\n'.join(r['output'])
        self.assertIn(f'sha={SHA2} backup={self.snap}', out)
        self.assertIn('Release tag signature verified', out)
        self.m['check_remote_unchanged'].assert_called_once()
        self.assertEqual(journal.read()['status'], 'complete')
        from audit.models import AuditLog
        self.assertTrue(AuditLog.objects.filter(action='system_update', success=True).exists())

    def test_failed_script_output_lands_in_the_audit_log(self):
        """#128 (v3.17.284) kept: superusers diagnose from the audit log."""
        with self._script(MIGRATING + 'echo "Step 3/5: Running database migrations..."\n'
                          'echo "django.db.utils.OperationalError: (1060, Duplicate column name)"\n'
                          'exit 3\n'):
            r = upgrade_apply.run(self.target)
        self.assertFalse(r['success'])
        self.assertIn(str(self.snap), r['error'])
        from audit.models import AuditLog
        row = AuditLog.objects.get(action='system_update_failed')
        self.assertIn('Duplicate column name', row.extra_data['output_tail'])
        self.assertEqual(row.extra_data['backup'], str(self.snap))

    def test_output_tail_is_capped(self):
        with self._script('for i in $(seq 1 600); do printf "noisy %0200d\\n" $i; done; exit 1\n'):
            upgrade_apply.run(self.target)
        from audit.models import AuditLog
        self.assertLessEqual(len(AuditLog.objects.get(action='system_update_failed')
                                 .extra_data['output_tail']), 50_000)

    def test_unsigned_release_is_refused_and_nothing_runs(self):
        self.m['verify_release_tag'].side_effect = RevisionError('v99.0.0 is not signed')
        with self._script('touch "$0.ran"\n') as m:
            r = upgrade_apply.run(self.target)
        self.assertTrue(r['refused'])
        m.assert_not_called()
        self.m['create'].assert_not_called()
        self.assertEqual(journal.read()['status'], 'aborted')

    def test_backup_that_does_not_verify_stops_before_any_change(self):
        self.m['verify'].return_value = {'ok': False, 'level': 'restore-test',
                                         'checks': [{'name': 'vault', 'ok': False, 'detail': 'bad key'}]}
        with self._script('exit 0\n') as m:
            r = upgrade_apply.run(self.target)
        self.assertTrue(r['refused'])
        self.assertIn('did not verify', r['error'])
        m.assert_not_called()

    def test_the_runs_own_journal_entry_does_not_block_its_preflight(self):
        """Regression (found by the rehearsal): preflight's journal check saw
        the entry this run had just begun and refused as 'already running'."""
        self.m['preflight'].side_effect = lambda *a, **k: [preflight.check_journal()]
        with self._script('exit 0\n'):
            r = upgrade_apply.run(self.target)
        self.assertTrue(r['success'], r)

    def test_failed_preflight_refuses(self):
        self.m['preflight'].return_value = [preflight.Check('disk space', 'fail', '10 MB free')]
        r = upgrade_apply.run(self.target)
        self.assertTrue(r['refused'])
        self.assertIn('disk space', r['error'])
        self.m['create'].assert_not_called()

    def test_downgrade_is_refused(self):
        self.m['version_at'].return_value = '0.0.1'
        r = upgrade_apply.run(self.target)
        self.assertTrue(r['refused'])
        self.assertIn('older than the installed', r['error'])

    def test_preview_needs_the_preview_channel(self):
        r = upgrade_apply.run(Target('preview', 'main', SHA2))
        self.assertTrue(r['refused'])
        self.assertIn('Stable channel', r['error'])
        self.m['fetch'].assert_not_called()

    def test_unfinished_upgrade_blocks_a_new_one(self):
        journal.begin(target=self.target.as_dict(), prev_sha=SHA1, prev_version='3.17.640')
        journal.stage('migrating')
        journal.write({**journal.read(), 'pid': 999999999})
        r = upgrade_apply.run(self.target)
        self.assertTrue(r['refused'])
        self.m['fetch'].assert_not_called()

    def test_resume_reuses_the_verified_backup(self):
        journal.begin(target=Target('preview', 'main', SHA2).as_dict(), prev_sha=SHA1,
                      prev_version='3.17.640', backup=str(self.snap))
        journal.stage('migrating', backup=str(self.snap))
        journal.write({**journal.read(), 'pid': 999999999})
        with mock.patch.object(upgrade_apply.snapshot, 'is_verified', return_value=(True, 'verified')), \
                mock.patch('core.upgrade.revision.git',
                           return_value=subprocess.CompletedProcess([], 0, '', '')), \
                self._script('echo resumed\n'):
            r = upgrade_apply.run(None, resume=True)   # Stable channel: resume still finishes it
        self.assertTrue(r['success'], r)
        self.m['create'].assert_not_called()
        self.assertIn('Reusing the pre-upgrade backup', '\n'.join(r['output']))

    def test_not_a_git_checkout(self):
        self.m['is_git_install'].return_value = False
        r = upgrade_apply.run(self.target)
        self.assertTrue(r['refused'])
        self.assertIn('Docker', r['error'])


# ---------------------------------------------------------------------------
# Settings -> Updates
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class UpdatesViewTests(_TmpMixin, TestCase):
    def setUp(self):
        self.tmp = self.make_tmp()
        o = override_settings(UPGRADE_BACKUP_DIR=self.tmp / 'backups')
        o.enable()
        self.addCleanup(o.disable)
        User = get_user_model()
        self.su = User.objects.create_user('upd_su', 'su@x.invalid', 'pw', is_superuser=True,
                                           is_staff=True)
        self.client.force_login(self.su)
        channels.clear_cache()
        # Never write the real progress file that a running install's UI reads.
        p = mock.patch('core.update_progress.UpdateProgress')
        p.start()
        self.addCleanup(p.stop)

    def _info(self, target):
        return {'update_available': bool(target), 'target': target, 'current_version': '1',
                'latest_version': '2', 'channels': {}}

    def _post_apply(self, body):
        return self.client.post(reverse('core:apply_update'), data=json.dumps(body) if body else '',
                                content_type='application/json')

    def test_apply_without_a_reviewed_revision_is_rejected(self):
        self.assertEqual(self._post_apply(None).status_code, 400)

    def test_apply_with_a_revision_other_than_the_one_offered_is_rejected(self):
        offered = {'kind': 'release', 'ref': 'v9.9.9', 'sha': SHA1, 'version': '9.9.9'}
        with mock.patch('core.updater.UpdateService.check_for_updates', return_value=self._info(offered)), \
                mock.patch('core.updater.UpdateService.perform_update') as perform:
            r = self._post_apply({'kind': 'release', 'ref': 'v9.9.9', 'sha': SHA2})
        self.assertEqual(r.status_code, 409)
        perform.assert_not_called()

    def test_apply_is_blocked_while_recovery_is_needed(self):
        offered = {'kind': 'release', 'ref': 'v9.9.9', 'sha': SHA1, 'version': '9.9.9'}
        journal.begin(target=offered)
        journal.stage('migrating')
        journal.write({**journal.read(), 'pid': 999999999})
        with mock.patch('core.updater.UpdateService.check_for_updates', return_value=self._info(offered)), \
                mock.patch('core.updater.UpdateService.perform_update') as perform:
            r = self._post_apply(offered)
        self.assertEqual(r.status_code, 409)
        perform.assert_not_called()

    def test_apply_starts_the_reviewed_revision(self):
        offered = {'kind': 'release', 'ref': 'v9.9.9', 'sha': SHA1, 'version': '9.9.9'}
        with mock.patch('core.updater.UpdateService.check_for_updates', return_value=self._info(offered)), \
                mock.patch('core.updater.UpdateService.perform_update') as perform, \
                mock.patch('threading.Thread') as thread:
            r = self._post_apply(offered)
            thread.call_args.kwargs['target']()
        self.assertEqual(r.json()['status'], 'started')
        target = perform.call_args.kwargs['target']
        self.assertEqual((target.kind, target.ref, target.sha), ('release', 'v9.9.9', SHA1))

    def test_set_channel(self):
        from core.models import SystemSetting
        self.client.post(reverse('core:set_update_channel'), {'channel': 'preview'})
        self.assertEqual(SystemSetting.get_settings().update_channel, 'preview')
        self.client.post(reverse('core:set_update_channel'), {'channel': 'lts'})
        self.assertEqual(SystemSetting.get_settings().update_channel, 'preview')
        self.client.post(reverse('core:set_update_channel'), {'channel': 'stable'})
        self.assertEqual(SystemSetting.get_settings().update_channel, 'stable')

    def test_only_superusers(self):
        User = get_user_model()
        plain = User.objects.create_user('upd_plain', 'p@x.invalid', 'pw')
        self.client.force_login(plain)
        r = self.client.post(reverse('core:set_update_channel'), {'channel': 'preview'})
        self.assertNotEqual(r.status_code, 200)
        from core.models import SystemSetting
        self.assertEqual(SystemSetting.get_settings().update_channel, 'stable')
        self.assertEqual(self._post_apply({'kind': 'release', 'ref': 'v1.0.0', 'sha': SHA1}).status_code, 302)

    def test_preflight_api_returns_the_checks(self):
        with mock.patch('core.updater.UpdateService.check_for_updates', return_value=self._info(None)), \
                mock.patch('core.upgrade.preflight.run',
                           return_value=[preflight.Check('disk space', 'fail', '1 MB free', 'free space')]):
            r = self.client.post(reverse('core:upgrade_preflight_api'))
        data = r.json()
        self.assertFalse(data['ok'])
        self.assertEqual(data['checks'][0]['name'], 'disk space')

    def test_updates_page_shows_installed_stable_and_unreleased_main(self):
        from django.core.cache import cache
        cache.delete(channels.CACHE_KEY_LAST_GOOD)
        inst = {'version': '3.17.558', 'sha': '9' * 40, 'branch': 'main', 'clean': True, 'is_git': True}
        with mock.patch.object(channels, 'installed', return_value=inst), \
                mock.patch.object(channels.requests, 'get', side_effect=_github()):
            html = self.client.get(reverse('core:system_updates')).content.decode()
        self.assertIn('v3.17.640', html)
        self.assertIn(SHA1[:12], html)              # the sha Apply would install
        self.assertIn('not a release', html)
        self.assertIn('19', html)                    # commits on main since the release
        self.assertIn('feat: newest', html)
        self.assertIn('no LTS', html.replace('There is no LTS', 'no LTS'))

    def test_updates_page_survives_github_being_down(self):
        import requests
        from django.core.cache import cache
        cache.delete(channels.CACHE_KEY_LAST_GOOD)

        def down(*a, **k):
            raise requests.Timeout('slow')
        with mock.patch.object(channels.requests, 'get', side_effect=down):
            r = self.client.get(reverse('core:system_updates'))
        self.assertEqual(r.status_code, 200)
        self.assertIn('timeout', r.content.decode())


class UpdateScriptOrderTests(SimpleTestCase):
    """Static guarantees of deploy/update_instructions.sh."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.script = (Path(django_settings.BASE_DIR) / 'deploy' / 'update_instructions.sh').read_text()

    def test_no_migration_without_a_verified_backup(self):
        s = self.script
        self.assertLess(s.index('upgrade_backup --check-verified'), s.index('manage.py" migrate --noinput'))
        self.assertLess(s.index('upgrade_backup --reason'), s.index('manage.py" migrate --noinput'))

    def test_pinned_mode_resets_to_the_reviewed_sha(self):
        self.assertIn('reset --hard "$TARGET_SHA"', self.script)

    def test_reload_does_not_signal_every_gunicorn_on_the_host(self):
        self.assertNotIn("pkill -HUP -f 'gunicorn", self.script)

    def test_sandbox_leaves_the_host_alone(self):
        self.assertIn('.update_progress_sandbox.json', self.script)
        self.assertIn('[sandbox] skipping root helper', self.script)


class ChannelUpgradeDefaultTests(TestCase):
    """Installs upgraded into channels keep following main (Preview); a fresh
    install starts on Stable."""

    def _run(self):
        import importlib
        from django.apps import apps as live_apps
        mod = importlib.import_module('core.migrations.0083_existing_installs_follow_main')
        mod.keep_existing_installs_on_main(live_apps, None)

    def test_fresh_install_stays_stable(self):
        from django.contrib.auth.models import User
        from core.models import SystemSetting
        User.objects.all().delete()
        SystemSetting.get_settings()
        self._run()
        self.assertEqual(SystemSetting.get_settings().update_channel, 'stable')

    def test_existing_install_keeps_following_main(self):
        from django.contrib.auth.models import User
        from core.models import SystemSetting
        User.objects.create_user('existing-admin', password='pw-existing-660!')
        SystemSetting.get_settings()
        self._run()
        self.assertEqual(SystemSetting.get_settings().update_channel, 'preview')


class BackupPruneTests(TestCase):
    """After a successful upgrade only the newest verified backups are kept;
    the journal's backup and unverified ones are never removed."""

    def test_prune_keeps_newest_pinned_and_unverified(self):
        from unittest import mock
        from core.upgrade import snapshot
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        snaps = []
        for i in range(5):
            d = root / f'snapshot-2026111{i}'
            d.mkdir()
            snaps.append({'path': str(d), 'verified': i != 1})
        snaps.reverse()  # newest first, like list_snapshots()
        pinned = str(root / 'snapshot-20261110')  # oldest, but the journal points at it
        with mock.patch.object(snapshot, 'list_snapshots', return_value=snaps), \
                mock.patch.object(snapshot.journal, 'read', return_value={'backup': pinned}):
            removed = snapshot.prune(keep=2)
        self.assertEqual(removed, [str(root / 'snapshot-20261112')])
        left = sorted(p.name for p in root.iterdir())
        self.assertEqual(left, ['snapshot-20261110', 'snapshot-20261111', 'snapshot-20261113',
                                'snapshot-20261114'])
