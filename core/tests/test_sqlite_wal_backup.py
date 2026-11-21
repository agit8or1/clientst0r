"""Backups of a SQLite database in WAL mode (core/sqlite_copy.py).

In WAL mode a commit sits in db.sqlite3-wal until the next checkpoint, so a
file copy of db.sqlite3 can miss it. Every backup path copies through
SQLite's backup API instead; these tests take a backup while the live
database has commits that only the -wal holds, and restore over a live WAL
database that has an open connection.
"""
import shutil
import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from core.sqlite_copy import copy_database, restore_database


class _Live:
    def make_live(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='wal-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.live = self.tmp / 'db.sqlite3'
        con = sqlite3.connect(str(self.live))
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('PRAGMA wal_autocheckpoint=0')
        con.execute('CREATE TABLE t (x TEXT)')
        con.execute("INSERT INTO t VALUES ('checkpointed')")
        con.commit()
        con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        con.execute("INSERT INTO t VALUES ('only in the wal')")
        con.commit()
        self.addCleanup(con.close)
        self.writer = con
        return con

    def rows(self, path):
        con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        try:
            return [r[0] for r in con.execute('SELECT x FROM t ORDER BY rowid')]
        finally:
            con.close()


class CopyTests(_Live, SimpleTestCase):

    def test_a_file_copy_would_miss_the_wal(self):
        """Why: the premise of everything below."""
        self.make_live()
        raw = self.tmp / 'raw.sqlite3'
        shutil.copyfile(self.live, raw)
        self.assertEqual(self.rows(raw), ['checkpointed'])

    def test_copy_holds_wal_commits_and_stands_alone(self):
        self.make_live()
        out = copy_database(self.live, self.tmp / 'copy.sqlite3')
        self.assertEqual(self.rows(out), ['checkpointed', 'only in the wal'])
        self.assertEqual(open(out, 'rb').read(20)[18:20], b'\x01\x01')  # rollback journal, not WAL
        self.assertFalse((self.tmp / 'copy.sqlite3-wal').exists())

    def test_restore_over_a_live_wal_database(self):
        self.make_live()
        src = self.tmp / 'src.sqlite3'
        con = sqlite3.connect(str(src))
        con.execute('CREATE TABLE t (x TEXT)')
        con.execute("INSERT INTO t VALUES ('restored')")
        con.commit()
        con.close()
        restore_database(src, self.live)
        self.assertEqual([r[0] for r in self.writer.execute('SELECT x FROM t')], ['restored'])
        self.assertEqual(self.writer.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(self.rows(self.live), ['restored'])


class OffhostDumpTests(_Live, SimpleTestCase):

    def test_offhost_dump_holds_wal_commits(self):
        """The off-host archive's read-only backup-API dump must include
        commits that are still only in the WAL file."""
        from core.offhost_backup.archive import dump_sqlite
        self.make_live()
        out = self.tmp / 'offhost.sqlite3'
        dump_sqlite(self.live, out)
        self.assertEqual(self.rows(out), ['checkpointed', 'only in the wal'])


class BackupCommandTests(_Live, SimpleTestCase):
    """manage.py backup / restore on SQLite."""

    def db(self):
        return {**settings.DATABASES['default'], 'ENGINE': 'django.db.backends.sqlite3',
                'NAME': str(self.live)}

    def test_backup_command_copies_wal_commits(self):
        from core.management.commands.backup import Command
        self.make_live()
        work = self.tmp / 'work'
        work.mkdir()
        with override_settings(DATABASES={'default': self.db()}):
            out = Command()._backup_database(work)
        self.assertEqual(self.rows(out), ['checkpointed', 'only in the wal'])

    def test_restore_command_restores_through_sqlite(self):
        from core.management.commands.restore import Command
        self.make_live()
        backup_dir = self.tmp / 'bk'
        backup_dir.mkdir()
        con = sqlite3.connect(str(backup_dir / 'database.sql'))
        con.execute('CREATE TABLE t (x TEXT)')
        con.execute("INSERT INTO t VALUES ('from backup')")
        con.commit()
        con.close()
        cmd = Command()
        with override_settings(DATABASES={'default': self.db()}), \
                mock.patch('django.db.connections.close_all'):
            cmd._restore_database(backup_dir)
        self.assertEqual(self.rows(self.live), ['from backup'])
        self.assertEqual([r[0] for r in self.writer.execute('SELECT x FROM t')], ['from backup'])
        # The database it replaced was kept, WAL commit included.
        self.assertEqual(self.rows(self.tmp / 'db.bak'), ['checkpointed', 'only in the wal'])


class SettingsTests(SimpleTestCase):

    def test_sqlite_settings(self):
        db = settings.DATABASES['default']
        if not db['ENGINE'].endswith('sqlite3'):
            self.skipTest('MySQL / MariaDB install')
        self.assertIn('PRAGMA journal_mode=WAL', db['OPTIONS']['init_command'])
        self.assertIn('busy_timeout', db['OPTIONS']['init_command'])
        self.assertEqual(db['OPTIONS']['transaction_mode'], 'IMMEDIATE')
        self.assertTrue(db['CONN_HEALTH_CHECKS'])
