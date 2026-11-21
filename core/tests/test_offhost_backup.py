"""Off-host backups (Phase 94.3, SR-17): encryption, archive contents, SFTP
with host-key pinning, retention, restore verification, scheduler, settings
page permissions, secrets kept out of logs.

Nothing here touches the production database or paths: archives are built
from a scratch SQLite file and a temporary media directory, staged in a
temporary directory, and uploaded to a temporary directory or to an
in-process SFTP server on 127.0.0.1.
"""
import gzip
import io
import logging
import os
import socket
import sqlite3
import tempfile
import threading
from datetime import timedelta
from pathlib import Path
from unittest import mock

import paramiko
from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import connection
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditLog
from core.models import OffhostBackupConfig, OffhostBackupRun, ScheduledTask
from core.offhost_backup import archive as arc
from core.offhost_backup import crypto, destinations, service
from netconfig import hostkeys

TEST_MIDDLEWARE = [m for m in django_settings.MIDDLEWARE
                   if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m]

SFTP_PASSWORD = 'sftp-pw-Zq83!unique'


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def make_sqlite(path, users=3):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE django_migrations (id INTEGER PRIMARY KEY, app TEXT, name TEXT, applied TEXT);
        CREATE TABLE auth_user (id INTEGER PRIMARY KEY, username TEXT);
        CREATE TABLE passwords (id INTEGER PRIMARY KEY, organization_id INT, encrypted_password TEXT);
    """)
    con.executemany('INSERT INTO django_migrations (app, name, applied) VALUES (?, ?, ?)',
                    [('core', '0001_initial', 'x'), ('core', '0119_offhost_backup', 'x')])
    con.executemany('INSERT INTO auth_user (username) VALUES (?)', [(f'u{i}',) for i in range(users)])
    con.commit()
    con.close()


class _Env:
    """Temp staging, media, scratch database and a local destination."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='offhost-test-')
        root = Path(self.tmp.name)
        self.staging = root / 'staging'
        self.media = root / 'media'
        self.dest = root / 'dest'
        self.db = root / 'scratch.sqlite3'
        (self.media / 'attachments').mkdir(parents=True)
        (self.media / 'attachments' / 'a.txt').write_text('attachment body')
        (self.media / 'logo.png').write_bytes(os.urandom(5000))
        self.dest.mkdir()
        make_sqlite(self.db)

    def cleanup(self):
        self.tmp.cleanup()


def configure_local(env, enabled=True):
    cfg = OffhostBackupConfig.get()
    cfg.destination_type = cfg.DEST_LOCAL
    cfg.local_path = str(env.dest)
    key = crypto.generate_key()
    cfg.backup_key = key
    cfg.backup_key_fingerprint = crypto.key_fingerprint(key)
    cfg.backup_key_acknowledged_at = timezone.now()
    cfg.enabled = enabled
    cfg.save()
    return cfg, key


def decrypt_to_bytes(path, key):
    buf = io.BytesIO()
    with open(path, 'rb') as f:
        crypto.decrypt_stream(f, buf, key)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# in-process SFTP server
# ---------------------------------------------------------------------------

class _Handle(paramiko.SFTPHandle):
    def stat(self):
        return paramiko.SFTPAttributes.from_stat(os.fstat(self.readfile.fileno()))

    def chattr(self, attr):
        return paramiko.SFTP_OK


class _SFTPServer:
    """A real SSH/SFTP server on 127.0.0.1 backed by a temp directory."""

    def __init__(self, root):
        self.root = root
        self.host_key = paramiko.ECDSAKey.generate()
        self.auth_attempts = 0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(5)
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self._stop = threading.Event()
        self.transports = []
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        outer = self
        root = self.root

        class SI(paramiko.SFTPServerInterface):
            def _p(self, path):
                return os.path.join(root, path.lstrip('/'))

            def list_folder(self, path):
                p = self._p(path)
                out = []
                for name in os.listdir(p):
                    a = paramiko.SFTPAttributes.from_stat(os.stat(os.path.join(p, name)))
                    a.filename = name
                    out.append(a)
                return out

            def stat(self, path):
                try:
                    return paramiko.SFTPAttributes.from_stat(os.stat(self._p(path)))
                except OSError as e:
                    return paramiko.SFTPServer.convert_errno(e.errno)

            lstat = stat

            def open(self, path, flags, attr):
                p = self._p(path)
                try:
                    fd = os.open(p, flags, 0o600)
                except OSError as e:
                    return paramiko.SFTPServer.convert_errno(e.errno)
                if flags & os.O_WRONLY:
                    mode = 'ab' if flags & os.O_APPEND else 'wb'
                elif flags & os.O_RDWR:
                    mode = 'a+b' if flags & os.O_APPEND else 'r+b'
                else:
                    mode = 'rb'
                f = os.fdopen(fd, mode)
                h = _Handle(flags)
                h.filename, h.readfile, h.writefile = p, f, f
                return h

            def remove(self, path):
                os.remove(self._p(path))
                return paramiko.SFTP_OK

            def rename(self, old, new):
                os.rename(self._p(old), self._p(new))
                return paramiko.SFTP_OK

            def posix_rename(self, old, new):
                os.replace(self._p(old), self._p(new))
                return paramiko.SFTP_OK

            def chattr(self, path, attr):
                return paramiko.SFTP_OK

        class Srv(paramiko.ServerInterface):
            def get_allowed_auths(self, username):
                return 'password'

            def check_auth_password(self, username, password):
                outer.auth_attempts += 1
                if username == 'backup' and password == SFTP_PASSWORD:
                    return paramiko.AUTH_SUCCESSFUL
                return paramiko.AUTH_FAILED

            def check_channel_request(self, kind, chanid):
                if kind == 'session':
                    return paramiko.OPEN_SUCCEEDED
                return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except (socket.timeout, OSError):
                continue
            t = paramiko.Transport(conn)
            t.add_server_key(self.host_key)
            t.set_subsystem_handler('sftp', paramiko.SFTPServer, SI)
            self.transports.append(t)
            try:
                t.start_server(server=Srv())
            except Exception:
                pass

    def approve_on(self, cfg):
        k = self.host_key
        cfg.host_key_type, cfg.host_key = k.get_name(), k.get_base64()
        cfg.host_key_fingerprint = hostkeys.fingerprint(k.asbytes())
        cfg.save()

    def stop(self):
        self._stop.set()
        for t in self.transports:
            t.close()
        self.sock.close()
        self.thread.join(2)


# ---------------------------------------------------------------------------
# encryption
# ---------------------------------------------------------------------------

class CryptoTests(SimpleTestCase):

    def _enc(self, data, key, seg=1024):
        buf = io.BytesIO()
        w = crypto.EncryptingWriter(buf, key, segment_size=seg)
        for i in range(0, len(data), 333):
            w.write(data[i:i + 333])
        w.close()
        return buf.getvalue()

    def _dec(self, blob, key):
        out = io.BytesIO()
        crypto.decrypt_stream(io.BytesIO(blob), out, key)
        return out.getvalue()

    def test_round_trip_various_sizes(self):
        key = crypto.generate_key()
        for n in (0, 1, 1023, 1024, 1025, 4096, 10_000):
            data = os.urandom(n)
            self.assertEqual(self._dec(self._enc(data, key), key), data, n)

    def test_ciphertext_differs_and_hides_plaintext(self):
        key = crypto.generate_key()
        data = b'SECRET-DATABASE-ROW ' * 200
        a, b = self._enc(data, key), self._enc(data, key)
        self.assertNotEqual(a, b)
        self.assertNotIn(b'SECRET-DATABASE-ROW', a)
        self.assertNotIn(key.encode(), a)
        self.assertNotIn(crypto.decode_key(key), a)

    def test_wrong_key_refused(self):
        blob = self._enc(b'x' * 3000, crypto.generate_key())
        with self.assertRaisesRegex(crypto.BackupCryptoError, 'different backup key'):
            self._dec(blob, crypto.generate_key())

    def test_tamper_truncate_extend_detected(self):
        key = crypto.generate_key()
        blob = self._enc(os.urandom(5000), key)
        flipped = bytearray(blob)
        flipped[crypto.HEADER_SIZE + 100] ^= 1
        seg = 1024 + crypto.TAG
        for bad in (bytes(flipped), blob[:crypto.HEADER_SIZE + 2 * seg], blob[:-5], blob + blob[-seg:]):
            with self.assertRaises(crypto.BackupCryptoError):
                self._dec(bad, key)
        header = bytearray(blob)
        header[-1 - (len(blob) - crypto.HEADER_SIZE)] ^= 1   # last byte of header (segment size)
        with self.assertRaises(crypto.BackupCryptoError):
            self._dec(bytes(header), key)

    def test_key_is_not_the_master_key_format(self):
        key = crypto.generate_key()
        self.assertTrue(key.startswith('csbk1_'))
        self.assertEqual(len(crypto.decode_key(key)), 32)
        with self.assertRaises(crypto.BackupCryptoError):
            crypto.decode_key('not-a-key')


class RetentionTests(SimpleTestCase):

    def _names(self, days):
        now = timezone.now()
        return [service.archive_name(now - timedelta(days=d)) for d in days]

    def test_keeps_daily_and_weekly_and_newest(self):
        names = self._names(range(60))
        doomed = service.plan_retention(names, keep_daily=7, keep_weekly=4)
        kept = sorted(set(names) - set(doomed), reverse=True)
        self.assertIn(max(names), kept)
        self.assertTrue(set(sorted(names, reverse=True)[:7]) <= set(kept))
        self.assertLessEqual(len(kept), 7 + 4)
        self.assertGreater(len(doomed), 40)

    def test_never_deletes_newest_verified(self):
        names = self._names(range(60))
        verified = min(names)   # very old, would otherwise be pruned
        doomed = service.plan_retention(names, keep_daily=1, keep_weekly=0, protect=[verified])
        self.assertNotIn(verified, doomed)
        self.assertNotIn(max(names), doomed)
        self.assertEqual(len(names) - len(doomed), 2)

    def test_ignores_foreign_files(self):
        names = self._names(range(3)) + ['notes.txt', 'clientst0r-offhost-bogus.csbk']
        doomed = service.plan_retention(names, keep_daily=1, keep_weekly=0)
        self.assertNotIn('notes.txt', doomed)
        self.assertNotIn('clientst0r-offhost-bogus.csbk', doomed)


# ---------------------------------------------------------------------------
# service with a local destination
# ---------------------------------------------------------------------------

class LocalBackupTests(TestCase):

    def setUp(self):
        self.env = _Env()
        self.addCleanup(self.env.cleanup)
        ov = override_settings(OFFHOST_BACKUP_STAGING_DIR=str(self.env.staging), MEDIA_ROOT=str(self.env.media))
        ov.enable()
        self.addCleanup(ov.disable)

    def _backup(self):
        return service.run_backup(trigger='test', sqlite_source=str(self.env.db), media_root=str(self.env.media))

    def test_disabled_by_default_does_nothing(self):
        cfg = OffhostBackupConfig.get()
        self.assertFalse(cfg.enabled)
        self.assertEqual(service.tick(), 'disabled')
        self.assertEqual(OffhostBackupRun.objects.count(), 0)
        self.assertEqual(list(self.env.dest.iterdir()), [])
        self.assertEqual(service.health()['state'], 'not_configured')

    def test_enabled_without_destination_refuses_and_reports(self):
        cfg = OffhostBackupConfig.get()
        cfg.enabled = True
        cfg.save()
        with self.assertRaises(service.NotReady):
            service.tick()
        self.assertEqual(OffhostBackupRun.objects.count(), 0)

    def test_backup_round_trip_and_contents(self):
        cfg, key = configure_local(self.env)
        run = self._backup()
        self.assertEqual(run.status, 'success')
        files = list(self.env.dest.iterdir())
        self.assertEqual([f.name for f in files], [run.remote_name])
        self.assertEqual(oct(files[0].stat().st_mode & 0o777), '0o600')
        blob = files[0].read_bytes()
        plain_gz = decrypt_to_bytes(files[0], key)
        plain = gzip.decompress(plain_gz)
        import tarfile
        with tarfile.open(fileobj=io.BytesIO(plain_gz), mode='r:gz') as tar:
            names = tar.getnames()
        self.assertIn('backup/database.sqlite3', names)
        self.assertIn('backup/manifest.json', names)
        self.assertIn('backup/media/attachments/a.txt', names)
        # Never the key files, the master key, other app keys or the backup key.
        for n in names:
            self.assertNotIn(Path(n).name, ('keys.env', '.env', 'env.file', 'gateway_keys.tar'))
        secrets = [key, crypto.decode_key(key).hex(), django_settings.APP_MASTER_KEY, django_settings.SECRET_KEY,
                   getattr(django_settings, 'API_KEY_SECRET', '') or 'unset-api-key-secret-xyz']
        for s in secrets:
            self.assertTrue(s)
            self.assertNotIn(s.encode(), plain)
            self.assertNotIn(s.encode(), blob)
        self.assertNotIn(crypto.decode_key(key), plain)
        self.assertEqual(crypto.archive_key_fingerprint(files[0]), cfg.backup_key_fingerprint)
        # Staging is cleaned up and nothing unencrypted is left behind.
        self.assertEqual([p for p in self.env.staging.rglob('*') if p.is_file()], [])
        self.assertTrue(AuditLog.objects.filter(object_type='offhost_backup', action='export', success=True).exists())

    def test_verification_passes_then_detects_corruption(self):
        configure_local(self.env)
        run = self._backup()
        v = service.run_verify(trigger='test')
        self.assertEqual(v.status, 'success', v.detail)
        cfg = OffhostBackupConfig.get()
        self.assertEqual(cfg.last_verified_name, run.remote_name)
        checks = {c['check']: c['ok'] for c in v.checks}
        for name in ('download hash', 'decrypt', 'archive listing', 'checksums', 'database integrity', 'row counts'):
            self.assertTrue(checks.get(name), name)

        path = self.env.dest / run.remote_name
        data = bytearray(path.read_bytes())
        data[len(data) // 2] ^= 0xFF
        path.write_bytes(bytes(data))
        with self.assertRaises(Exception):
            service.run_verify(trigger='test')
        cfg = OffhostBackupConfig.get()
        self.assertEqual(cfg.last_verify_status, 'failed')
        self.assertEqual(service.health()['state'], 'verify_failed')
        from core.system_warnings import collect_system_warnings
        self.assertTrue(any(w['category'] == 'offhost_backup' for w in collect_system_warnings()))

    def test_verification_detects_damaged_database_with_valid_encryption(self):
        """A database that is corrupt before encryption is caught by the integrity check."""
        _cfg, key = configure_local(self.env)
        with open(self.env.db, 'r+b') as f:      # corrupt a b-tree page of the scratch DB copy source
            f.seek(4096 + 10)
            f.write(b'\xff' * 200)
        try:
            run = self._backup()
        except Exception:
            return   # the copy itself refused the damaged file: also a detection
        work = Path(tempfile.mkdtemp(dir=self.env.tmp.name))
        ok, checks = service.verify_file(self.env.dest / run.remote_name, key, work)
        self.assertFalse(ok, checks)

    def test_tick_runs_backup_then_verification(self):
        configure_local(self.env)
        with mock.patch.object(arc, 'dump_database', wraps=lambda staging, sqlite_source=None:
                               arc.dump_sqlite(str(self.env.db), staging / 'database.sqlite3')):
            self.assertEqual(service.tick(media_root=str(self.env.media)), 'backup, verify')
            self.assertEqual(service.tick(media_root=str(self.env.media)), 'nothing due')
        self.assertEqual(service.health()['state'], 'ok')

    def test_retention_applied_after_upload_keeps_verified(self):
        cfg, _ = configure_local(self.env)
        old = [service.archive_name(timezone.now() - timedelta(days=d)) for d in (40, 50, 60)]
        for n in old:
            (self.env.dest / n).write_bytes(b'old')
        (self.env.dest / 'unrelated.txt').write_text('keep me')
        OffhostBackupConfig.objects.filter(pk=1).update(keep_daily=1, keep_weekly=0, last_verified_name=old[2])
        self._backup()
        left = sorted(p.name for p in self.env.dest.iterdir())
        self.assertIn(old[2], left)            # newest verified survives
        self.assertNotIn(old[0], left)
        self.assertNotIn(old[1], left)
        self.assertIn('unrelated.txt', left)

    def test_stale_backup_raises_warning_and_readiness(self):
        configure_local(self.env)
        OffhostBackupConfig.objects.filter(pk=1).update(
            last_success_at=timezone.now() - timedelta(days=5), last_backup_status='failed',
            last_backup_detail='disk full', last_verified_ok_at=timezone.now())
        self.assertEqual(service.health()['state'], 'stale')
        from core.system_warnings import collect_system_warnings
        w = [w for w in collect_system_warnings() if w['category'] == 'offhost_backup']
        self.assertEqual(w[0]['severity'], 'high')
        from core.readiness import _check_offhost_backup
        self.assertFalse(_check_offhost_backup()['ok'])

    def test_local_destination_refuses_app_directory(self):
        with self.assertRaises(destinations.DestinationError):
            destinations.LocalDirDestination(str(Path(django_settings.BASE_DIR) / 'backups'))

    def test_backup_key_stored_sealed(self):
        configure_local(self.env)
        qn = connection.ops.quote_name
        with connection.cursor() as cur:
            cur.execute(f'SELECT {qn("backup_key")} FROM {qn("core_offhost_backup_config")} WHERE id = 1')
            raw = cur.fetchone()[0]
        self.assertTrue(raw.startswith('enc2$'))


# ---------------------------------------------------------------------------
# SFTP
# ---------------------------------------------------------------------------

@override_settings(ALLOW_PRIVATE_IP_INTEGRATIONS=True)
class SFTPTests(TestCase):

    def setUp(self):
        self.env = _Env()
        self.addCleanup(self.env.cleanup)
        (Path(self.env.tmp.name) / 'sftproot' / 'backups').mkdir(parents=True)
        self.srv = _SFTPServer(str(Path(self.env.tmp.name) / 'sftproot'))
        self.addCleanup(self.srv.stop)
        ov = override_settings(OFFHOST_BACKUP_STAGING_DIR=str(self.env.staging), MEDIA_ROOT=str(self.env.media))
        ov.enable()
        self.addCleanup(ov.disable)
        cfg, self.key = configure_local(self.env)
        cfg.destination_type = cfg.DEST_SFTP
        cfg.sftp_host, cfg.sftp_port = '127.0.0.1', self.srv.port
        cfg.sftp_username, cfg.sftp_password, cfg.sftp_path = 'backup', SFTP_PASSWORD, '/backups'
        cfg.save()

    def test_no_approved_key_refuses_without_connecting(self):
        with self.assertRaisesRegex(destinations.DestinationError, 'No approved SSH host key'):
            destinations.SFTPDestination(OffhostBackupConfig.get())
        self.assertEqual(self.srv.auth_attempts, 0)

    def test_fetch_records_pending_and_does_not_approve(self):
        cfg = OffhostBackupConfig.get()
        key_type, fp, approved = destinations.fetch_host_key(cfg)
        self.assertFalse(approved)
        cfg.refresh_from_db()
        self.assertEqual(cfg.pending_host_key_fingerprint, hostkeys.fingerprint(self.srv.host_key.asbytes()))
        self.assertEqual(cfg.host_key, '')
        self.assertEqual(self.srv.auth_attempts, 0)
        hostkeys.approve_pending(cfg, None, fp)
        cfg.refresh_from_db()
        self.assertEqual(cfg.host_key_fingerprint, fp)
        self.assertTrue(AuditLog.objects.filter(object_type='offhost_backup', description__contains=fp).exists())

    def test_host_key_mismatch_refused_before_auth(self):
        cfg = OffhostBackupConfig.get()
        other = paramiko.ECDSAKey.generate()
        cfg.host_key_type, cfg.host_key = other.get_name(), other.get_base64()
        cfg.host_key_fingerprint = hostkeys.fingerprint(other.asbytes())
        cfg.save()
        with self.assertRaisesRegex(destinations.DestinationError, 'HOST KEY MISMATCH'):
            destinations.SFTPDestination(cfg)
        self.assertEqual(self.srv.auth_attempts, 0, 'credentials were sent to an unverified server')
        cfg.refresh_from_db()
        self.assertEqual(cfg.pending_host_key_fingerprint, hostkeys.fingerprint(self.srv.host_key.asbytes()))
        with self.assertRaises(destinations.DestinationError):
            service.run_backup(trigger='test', sqlite_source=str(self.env.db), media_root=str(self.env.media))
        self.assertEqual(list((Path(self.env.tmp.name) / 'sftproot' / 'backups').iterdir()), [])

    def test_backup_and_verify_over_sftp(self):
        self.srv.approve_on(OffhostBackupConfig.get())
        run = service.run_backup(trigger='test', sqlite_source=str(self.env.db), media_root=str(self.env.media))
        remote = Path(self.env.tmp.name) / 'sftproot' / 'backups'
        self.assertEqual([p.name for p in remote.iterdir()], [run.remote_name])
        v = service.run_verify(trigger='test')
        self.assertEqual(v.status, 'success', v.detail)

    def test_secrets_not_in_logs_audit_or_run_detail(self):
        self.srv.approve_on(OffhostBackupConfig.get())
        cfg = OffhostBackupConfig.get()
        cfg.sftp_password = 'wrong-' + SFTP_PASSWORD
        cfg.save()
        root = logging.getLogger()
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        root.addHandler(handler)
        old_level = root.level
        root.setLevel(logging.DEBUG)
        try:
            with self.assertRaises(destinations.DestinationError):
                service.run_backup(trigger='test', sqlite_source=str(self.env.db), media_root=str(self.env.media))
            cfg.sftp_password = SFTP_PASSWORD
            cfg.save()
            service.run_backup(trigger='test', sqlite_source=str(self.env.db), media_root=str(self.env.media))
        finally:
            root.removeHandler(handler)
            root.setLevel(old_level)
        logs = stream.getvalue()
        texts = [logs] + [r.detail for r in OffhostBackupRun.objects.all()] + [
            f'{a.description} {a.extra_data}' for a in AuditLog.objects.filter(object_type='offhost_backup')]
        for t in texts:
            self.assertNotIn(SFTP_PASSWORD, t)
            self.assertNotIn(self.key, t)
        self.assertIn('refused', OffhostBackupRun.objects.filter(status='failed').first().detail)


# ---------------------------------------------------------------------------
# scheduler registration
# ---------------------------------------------------------------------------

class SchedulerRegistrationTests(TestCase):

    def test_task_registered(self):
        from core.management.commands.run_scheduler import COMMAND_TASKS
        self.assertEqual(COMMAND_TASKS['offhost_backup'], ('offhost_backup', ['tick']))
        self.assertIn('offhost_backup', dict(ScheduledTask.TASK_TYPES))
        ScheduledTask.get_or_create_defaults()
        t = ScheduledTask.objects.get(task_type='offhost_backup')
        self.assertTrue(t.enabled)

    def test_scheduled_command_is_a_noop_when_unconfigured(self):
        out = io.StringIO()
        call_command('offhost_backup', 'tick', stdout=out)
        self.assertIn('disabled', out.getvalue())
        self.assertEqual(OffhostBackupRun.objects.count(), 0)

    def test_readiness_lists_offhost_backup_until_set_up(self):
        from core.readiness import _check_offhost_backup
        c = _check_offhost_backup()
        self.assertFalse(c['ok'])
        self.assertEqual(c['id'], 'offhost_backup')
        self.assertIn('keys.env', c['detail'])


# ---------------------------------------------------------------------------
# settings page
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SettingsViewTests(TestCase):

    def setUp(self):
        self.url = reverse('core:offhost_backup')
        self.admin = User.objects.create_superuser('root1', 'r@example.com', 'pw-Root-1234!')
        self.staff = User.objects.create_user('tech1', 't@example.com', 'pw-Tech-1234!', is_staff=True)

    def test_anonymous_and_non_superuser_refused(self):
        r = Client().get(self.url)
        self.assertEqual(r.status_code, 302)
        c = Client()
        c.force_login(self.staff)
        self.assertNotEqual(c.get(self.url).status_code, 200)
        r = c.post(self.url, {'action': 'set_enabled', 'enabled': '1'})
        self.assertNotEqual(r.status_code, 200)
        r = c.post(self.url, {'action': 'generate_key'})
        self.assertFalse(OffhostBackupConfig.objects.filter(pk=1).exclude(backup_key='').exists())

    def test_post_requires_csrf(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.admin)
        self.assertEqual(c.get(self.url).status_code, 200)
        r = c.post(self.url, {'action': 'generate_key'})
        self.assertEqual(r.status_code, 403)

    def test_key_shown_once_and_acknowledge_flow(self):
        c = Client()
        c.force_login(self.admin)
        r = c.post(self.url, {'action': 'generate_key'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('no-store', r['Cache-Control'])
        cfg = OffhostBackupConfig.get()
        self.assertContains(r, cfg.backup_key)
        r2 = c.get(self.url)
        self.assertNotContains(r2, cfg.backup_key)
        # Cannot switch on before destination and acknowledgement.
        c.post(self.url, {'action': 'set_enabled', 'enabled': '1'})
        self.assertFalse(OffhostBackupConfig.get().enabled)
        c.post(self.url, {'action': 'acknowledge_key', 'key_tail': 'zzzzzz'})
        self.assertIsNone(OffhostBackupConfig.get().backup_key_acknowledged_at)
        c.post(self.url, {'action': 'acknowledge_key', 'key_tail': cfg.backup_key[-6:]})
        self.assertIsNotNone(OffhostBackupConfig.get().backup_key_acknowledged_at)
        # Rotating needs explicit confirmation.
        c.post(self.url, {'action': 'generate_key'})
        self.assertEqual(OffhostBackupConfig.get().backup_key, cfg.backup_key)
        events = list(AuditLog.objects.filter(object_type='offhost_backup').values_list('extra_data', flat=True))
        self.assertTrue(events)
        for e in events:
            self.assertNotIn(cfg.backup_key, str(e))

    def test_save_destination_and_run_now(self):
        with tempfile.TemporaryDirectory() as d:
            c = Client()
            c.force_login(self.admin)
            c.post(self.url, {'action': 'save_destination', 'destination_type': 'local', 'local_path': d})
            cfg = OffhostBackupConfig.get()
            self.assertEqual(cfg.local_path, d)
            c.post(self.url, {'action': 'generate_key'})
            cfg = OffhostBackupConfig.get()
            c.post(self.url, {'action': 'acknowledge_key', 'key_tail': cfg.backup_key[-6:]})
            c.post(self.url, {'action': 'set_enabled', 'enabled': '1'})
            self.assertTrue(OffhostBackupConfig.get().enabled)
            ScheduledTask.get_or_create_defaults()
            c.post(self.url, {'action': 'run_backup_now'})
            self.assertIsNotNone(OffhostBackupConfig.get().backup_requested_at)
            t = ScheduledTask.objects.get(task_type='offhost_backup')
            self.assertLessEqual(t.next_run_at, timezone.now())
            self.assertTrue(AuditLog.objects.filter(object_type='offhost_backup',
                                                    description__contains='destination saved').exists())

    def test_sftp_password_never_rendered(self):
        c = Client()
        c.force_login(self.admin)
        c.post(self.url, {'action': 'save_destination', 'destination_type': 'sftp', 'sftp_host': 'nas.example.com',
                          'sftp_port': '22', 'sftp_username': 'backup', 'sftp_password': SFTP_PASSWORD,
                          'sftp_path': '/backups'})
        self.assertEqual(OffhostBackupConfig.get().sftp_password, SFTP_PASSWORD)
        r = c.get(self.url)
        self.assertNotContains(r, SFTP_PASSWORD)
        for a in AuditLog.objects.filter(object_type='offhost_backup'):
            self.assertNotIn(SFTP_PASSWORD, f'{a.description} {a.extra_data}')
