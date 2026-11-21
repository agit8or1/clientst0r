"""Build and check the plaintext side of an off-host backup archive.

The archive is a gzip'd tar streamed straight into the encrypting writer —
no unencrypted archive is ever written to disk. Members, all under
``backup/``:

    database.sqlite3   SQLite: an online copy made with SQLite's backup API
    database.sql       MySQL/MariaDB: mysqldump --single-transaction
    media/...          every regular file under MEDIA_ROOT (symlinks skipped)
    manifest.json      versions, engine, row counts, applied migrations,
                       sha256 of every other member, key fingerprints

Never included: keys.env, .env, APP_MASTER_KEY, SECRET_KEY, API_KEY_SECRET,
the AI gateway keys, or the backup key itself. The database dump does hold
the secrets the application stores encrypted (vault entries, integration
credentials, this feature's own settings row) — as ciphertext under
APP_MASTER_KEY, which is why the master key must be escrowed separately.

The database dump reuses the routines of the verified pre-upgrade snapshot
(core.upgrade.snapshot): the same SQLite backup API copy and the same
mysqldump invocation with a 0600 option file for the password.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import time
from pathlib import Path

from django.conf import settings
from django.utils import timezone

FORMAT = 1
ROOT = 'backup'
# Key tables whose row counts verification compares with the manifest.
KEY_TABLES = ('django_migrations', 'auth_user', 'organizations', 'passwords', 'audit_logs')
# Names that must never be packed (checked again at verification).
FORBIDDEN_NAMES = ('keys.env', '.env', 'env.file', 'gateway_keys.tar')


class ArchiveError(Exception):
    pass


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


class _HashingReader:
    def __init__(self, f):
        self._f = f
        self.hash = hashlib.sha256()

    def read(self, n=-1):
        data = self._f.read(n)
        self.hash.update(data)
        return data


def _engine():
    from core.upgrade.snapshot import db_engine
    return db_engine()


def dump_sqlite(src_path, dst_path):
    """Consistent online copy plus the facts verification compares against."""
    src = sqlite3.connect(f'file:{src_path}?mode=ro', uri=True, timeout=60)
    dst = sqlite3.connect(str(dst_path))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.chmod(dst_path, 0o600)
    con = sqlite3.connect(f'file:{dst_path}?mode=ro', uri=True)
    try:
        cur = con.cursor()
        tables = sorted(r[0] for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
        counts = {}
        for t in tables:
            counts[t] = cur.execute('SELECT COUNT(*) FROM "%s"' % t.replace('"', '""')).fetchone()[0]
        try:
            migrations = sorted(f'{a}.{n}' for a, n in cur.execute('SELECT app, name FROM django_migrations'))
        except sqlite3.Error:
            migrations = []
    finally:
        con.close()
    return {'engine': 'sqlite', 'file': 'database.sqlite3', 'tables': tables,
            'row_counts': counts, 'applied_migrations': migrations}


def dump_mysql(dst_path):
    from core.upgrade import snapshot as s
    dump_bin, _ = s.mysql_tools()
    if not dump_bin:
        raise ArchiveError('mysqldump (or mariadb-dump) is not installed; install the MariaDB/MySQL client tools.')
    defaults = s._mysql_defaults_file(Path(dst_path).parent)
    try:
        tables = s._live_tables()
        migrations = s._live_applied_migrations()
        extra = []
        try:
            helptext = subprocess.run([dump_bin, '--help'], capture_output=True, text=True, timeout=30).stdout
            if '--column-statistics' in helptext and s._db_vendor_is_mariadb():
                extra.append('--column-statistics=0')
        except (OSError, subprocess.SubprocessError):
            pass
        r = subprocess.run(
            [dump_bin, f'--defaults-extra-file={defaults}', '--single-transaction', '--quick', '--routines',
             '--triggers', '--hex-blob', '--no-tablespaces', '--default-character-set=utf8mb4', *extra,
             f'--result-file={dst_path}', s._db()['NAME']],
            capture_output=True, text=True, timeout=6 * 3600)
    finally:
        os.unlink(defaults)
    if r.returncode != 0:
        # stderr of mysqldump never contains the password (it is in the option file).
        raise ArchiveError(f'mysqldump failed: {r.stderr.strip()[:500]}')
    os.chmod(dst_path, 0o600)
    from django.db import connection
    with connection.cursor() as cursor:
        counts = s._count_rows(cursor, [t for t in KEY_TABLES if t in tables], 'mysql')
    return {'engine': 'mysql', 'file': 'database.sql', 'tables': tables,
            'row_counts': counts, 'applied_migrations': migrations}


def dump_database(staging: Path, sqlite_source=None):
    """Dump the live database into ``staging``. ``sqlite_source`` overrides the
    SQLite file (tests use a scratch database, never the production one)."""
    if sqlite_source is not None:
        return dump_sqlite(sqlite_source, staging / 'database.sqlite3')
    engine = _engine()
    if engine == 'sqlite':
        return dump_sqlite(str(settings.DATABASES['default']['NAME']), staging / 'database.sqlite3')
    if engine == 'mysql':
        return dump_mysql(staging / 'database.sql')
    raise ArchiveError(f'Off-host backup does not support the database engine "{engine}" '
                       '(SQLite and MariaDB/MySQL are supported, as for manage.py backup).')


def _key_fingerprints():
    from core.upgrade.snapshot import REQUIRED_KEYS, _setting_or_env, key_fingerprint
    return {k: key_fingerprint(k, _setting_or_env(k)) for k in REQUIRED_KEYS}


def _add_bytes(tar, name, data, mtime):
    info = tarfile.TarInfo(f'{ROOT}/{name}')
    info.size, info.mtime, info.mode = len(data), mtime, 0o600
    tar.addfile(info, io.BytesIO(data))


def write_archive(fileobj, staging: Path, *, media_root=None, sqlite_source=None, backup_key_fingerprint=''):
    """Stream the archive (tar.gz) into ``fileobj``. Returns the manifest."""
    t0 = time.monotonic()
    from config.version import VERSION
    db = dump_database(staging, sqlite_source=sqlite_source)
    db_path = staging / db['file']
    t_db = time.monotonic()
    members = {}
    media_root = Path(media_root if media_root is not None else settings.MEDIA_ROOT)
    now = int(time.time())
    media_files = media_bytes = 0
    with tarfile.open(fileobj=fileobj, mode='w|gz') as tar:
        info = tar.gettarinfo(str(db_path), arcname=f'{ROOT}/{db["file"]}')
        with open(db_path, 'rb') as f:
            hr = _HashingReader(f)
            tar.addfile(info, hr)
        members[db['file']] = {'sha256': hr.hash.hexdigest(), 'size': info.size}
        db_path.unlink()   # not needed any more; keep staging small
        if media_root.is_dir():
            for p in sorted(media_root.rglob('*')):
                if p.is_symlink() or not p.is_file():
                    continue
                rel = 'media/' + p.relative_to(media_root).as_posix()
                try:
                    info = tar.gettarinfo(str(p), arcname=f'{ROOT}/{rel}')
                    with open(p, 'rb') as f:
                        hr = _HashingReader(f)
                        tar.addfile(info, hr)
                except (FileNotFoundError, PermissionError):
                    continue   # removed or unreadable mid-run; not worth failing the backup
                members[rel] = {'sha256': hr.hash.hexdigest(), 'size': info.size}
                media_files += 1
                media_bytes += info.size
        manifest = {
            'format': FORMAT,
            'kind': 'clientst0r-offhost-backup',
            'created_at': timezone.now().isoformat(),
            'app_version': VERSION,
            'db': {k: db[k] for k in ('engine', 'file')},
            'tables': db['tables'],
            'row_counts': db['row_counts'],
            'applied_migrations': db['applied_migrations'],
            'media': {'root': str(media_root), 'files': media_files, 'bytes': media_bytes},
            'members': members,
            # Fingerprints only: they tell a restorer whether the escrowed
            # keys are the right ones. The keys themselves are not here.
            'key_fingerprints': _key_fingerprints(),
            'backup_key_fingerprint': backup_key_fingerprint,
            'not_included': ['keys.env / .env (APP_MASTER_KEY, SECRET_KEY, API_KEY_SECRET, DB_*)',
                             'the backup encryption key', 'AI gateway keys', 'application code'],
            'timings': {'database_seconds': round(t_db - t0, 2),
                        'total_seconds': round(time.monotonic() - t0, 2)},
        }
        _add_bytes(tar, 'manifest.json', json.dumps(manifest, indent=2, sort_keys=True).encode(), now)
    return manifest


# ---------------------------------------------------------------------------
# verification of a decrypted archive
# ---------------------------------------------------------------------------

def _safe_extract(tar, dest: Path):
    for m in tar.getmembers():
        name = m.name
        if not name.startswith(ROOT + '/') or '..' in Path(name).parts or m.issym() or m.islnk():
            raise ArchiveError(f'unexpected member in archive: {name[:120]}')
        if Path(name).parent == Path(ROOT) and Path(name).name in FORBIDDEN_NAMES:
            raise ArchiveError(f'archive contains a key file ({Path(name).name}); it must never be packed')
    tar.extractall(str(dest), filter='data')


def check_extracted(plain_tar_path, work: Path):
    """Extract a decrypted tar.gz into ``work`` and check it. Never touches
    the live database. Returns (ok, checks, manifest)."""
    checks = []
    try:
        with tarfile.open(plain_tar_path, 'r:gz') as tar:
            names = tar.getnames()
            _safe_extract(tar, work)
    except (tarfile.TarError, OSError, EOFError, ArchiveError) as e:
        checks.append(('archive listing', False, f'cannot read archive: {e}'))
        return False, checks, {}
    checks.append(('archive listing', True, f'{len(names)} members'))
    root = work / ROOT
    try:
        manifest = json.loads((root / 'manifest.json').read_text())
    except (OSError, ValueError) as e:
        checks.append(('manifest', False, f'manifest.json missing or unreadable: {e.__class__.__name__}'))
        return False, checks, {}
    if manifest.get('kind') != 'clientst0r-offhost-backup':
        checks.append(('manifest', False, 'not a Client St0r off-host backup manifest'))
        return False, checks, manifest
    checks.append(('manifest', True, f"v{manifest.get('app_version')}, {manifest.get('created_at')}"))

    bad = []
    for rel, meta in (manifest.get('members') or {}).items():
        p = root / rel
        if not p.is_file():
            bad.append(f'{rel}: missing')
        elif _sha256_file(p) != meta.get('sha256'):
            bad.append(f'{rel}: checksum mismatch')
    if bad:
        checks.append(('checksums', False, '; '.join(bad[:5])))
        return False, checks, manifest
    checks.append(('checksums', True, f"{len(manifest.get('members') or {})} files match the manifest"))

    engine = (manifest.get('db') or {}).get('engine')
    db_file = root / (manifest.get('db') or {}).get('file', '')
    ok = verify_sqlite(db_file, manifest, checks) if engine == 'sqlite' else (
        verify_mysql_dump(db_file, manifest, checks) if engine == 'mysql' else False)
    if engine not in ('sqlite', 'mysql'):
        checks.append(('database', False, f'unknown engine {engine!r}'))
    return ok, checks, manifest


def verify_sqlite(db_file, manifest, checks):
    try:
        con = sqlite3.connect(f'file:{db_file}?mode=ro', uri=True)
    except sqlite3.Error as e:
        checks.append(('database integrity', False, f'cannot open: {e}'))
        return False
    try:
        cur = con.cursor()
        res = cur.execute('PRAGMA integrity_check').fetchone()[0]
        if res != 'ok':
            checks.append(('database integrity', False, f'PRAGMA integrity_check: {res[:200]}'))
            return False
        checks.append(('database integrity', True, 'PRAGMA integrity_check: ok'))
        expected = manifest.get('row_counts') or {}
        wrong, seen = [], []
        for t in KEY_TABLES:
            if t not in expected:
                continue
            try:
                n = cur.execute('SELECT COUNT(*) FROM "%s"' % t.replace('"', '""')).fetchone()[0]
            except sqlite3.Error as e:
                wrong.append(f'{t}: {e}')
                continue
            seen.append(f'{t}={n}')
            if n != expected[t]:
                wrong.append(f'{t}: {n} rows, manifest says {expected[t]}')
        if wrong:
            checks.append(('row counts', False, '; '.join(wrong[:5])))
            return False
        if 'django_migrations' in expected and not cur.execute('SELECT COUNT(*) FROM django_migrations').fetchone()[0]:
            checks.append(('row counts', False, 'django_migrations is empty'))
            return False
        checks.append(('row counts', True, ', '.join(seen) or 'no key tables in this database'))
        return True
    except sqlite3.DatabaseError as e:
        checks.append(('database integrity', False, f'not a readable SQLite database: {e}'))
        return False
    finally:
        con.close()


def verify_mysql_dump(path, manifest, checks):
    """Structural check of a mysqldump file: complete trailer, a CREATE TABLE
    for every table the manifest lists, and the migration history."""
    created, has_migrations, completed = set(), False, False
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                if line.startswith('CREATE TABLE `'):
                    created.add(line.split('`')[1])
                elif line.startswith('INSERT INTO `django_migrations`'):
                    has_migrations = True
                elif line.startswith('-- Dump completed'):
                    completed = True
    except OSError as e:
        checks.append(('database dump', False, f'cannot read: {e}'))
        return False
    if not completed:
        checks.append(('database dump', False, 'no "-- Dump completed" trailer: the dump was cut short'))
        return False
    missing = sorted(set(manifest.get('tables') or []) - created)
    if missing:
        checks.append(('database dump', False, f'dump does not create: {missing[:10]}'))
        return False
    if not has_migrations:
        checks.append(('database dump', False, 'dump has no django_migrations rows'))
        return False
    checks.append(('database dump', True, f'{len(created)} tables and the migration history present'))
    return True


def private_dir(path: Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return path


def rmtree(path):
    shutil.rmtree(path, ignore_errors=True)
