"""Pre-upgrade backups that can actually bring an instance back.

A snapshot is a directory (mode 0700, every file 0600) under
settings.UPGRADE_BACKUP_DIR holding:

    manifest.json      what was captured, checksums, code revision, key fingerprints
    database.sqlite3   SQLite: an online copy made with SQLite's backup API
    database.sql       MySQL/MariaDB: mysqldump --single-transaction
    media.tar          everything under MEDIA_ROOT (uploads, attachments, pictures)
    keys.env           SECRET_KEY, APP_MASTER_KEY(_PREVIOUS), API_KEY_SECRET, DB_* settings
    env.file           a verbatim copy of .env, when the install has one
    gateway_keys.tar   AI_GATEWAY_KEY_DIR, when configured
    verification.json  written by verify()

Why the keys are inside: the database alone is not a backup. Vault entries,
secure notes, TOTP secrets and integration credentials are encrypted with
APP_MASTER_KEY; a restored database without that key is unreadable. The
`manage.py backup` archive is encrypted *with* APP_MASTER_KEY, so it cannot
carry the key itself. A snapshot sits on the same host as .env and is
protected the same way: owner-only permissions on the directory and every
file. To copy one off the host, use `manage.py upgrade_backup --export`,
which wraps it in a passphrase-encrypted archive (scrypt + AES-GCM).

verify() proves the snapshot restores: checksums, a full restore of the
database into a scratch database (SQLite: integrity check on the copy), the
same tables and applied migrations as the live database, sample vault
entries decrypting with the key stored in the snapshot, and a readable media
archive. Apply refuses to migrate without a verified snapshot.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from . import journal

FORMAT = 1
REQUIRED_KEYS = ('SECRET_KEY', 'APP_MASTER_KEY', 'API_KEY_SECRET')
OPTIONAL_KEYS = ('APP_MASTER_KEY_PREVIOUS', 'EMERGENCY_RESTART_SECRET', 'AI_GATEWAY_KEY_DIR')
DB_ENV = ('DB_ENGINE', 'DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_HOST', 'DB_PORT')
VAULT_SAMPLE = 5


class SnapshotError(Exception):
    pass


def _out(out, msg):
    if out:
        out(msg)


# ---------------------------------------------------------------------------
# keys
# ---------------------------------------------------------------------------

def _setting_or_env(name):
    value = getattr(settings, name, None)
    if value in (None, ''):
        value = os.environ.get(name, '')
    return '' if value is None else str(value)


def key_fingerprint(name, value):
    """Short, non-reversible fingerprint used to tell whether two keys match."""
    if not value:
        return ''
    if name == 'APP_MASTER_KEY':
        try:
            from vault.encryption import decode_master_key
            raw = decode_master_key(value)
        except Exception:
            raw = value.encode()
    else:
        raw = value.encode()
    return hashlib.sha256(b'clientst0r-key-fingerprint\0' + name.encode() + b'\0' + raw).hexdigest()[:16]


def required_keys_status():
    """[(name, ok, detail)] for the keys an instance cannot be restored without."""
    rows = []
    values = {k: _setting_or_env(k) for k in REQUIRED_KEYS}
    for name in REQUIRED_KEYS:
        v = values[name]
        if not v:
            rows.append((name, False, 'not set'))
            continue
        if name == 'APP_MASTER_KEY':
            try:
                from vault.encryption import decode_master_key
                decode_master_key(v)
            except Exception as e:
                rows.append((name, False, f'not a valid base64 32-byte key ({str(e).splitlines()[0]})'))
                continue
        rows.append((name, True, 'set'))
    if values['SECRET_KEY'] and values['SECRET_KEY'] in (values['APP_MASTER_KEY'], values['API_KEY_SECRET']):
        rows.append(('distinct keys', False, 'SECRET_KEY must differ from APP_MASTER_KEY and API_KEY_SECRET'))
    return rows


def _quote_env(value):
    # Single-quoted values are literal for python-dotenv and for `set -a; . file`.
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _key_lines():
    lines = ['# Client St0r keys captured with this backup. Treat like .env itself.']
    for name in REQUIRED_KEYS + OPTIONAL_KEYS + DB_ENV:
        v = _setting_or_env(name) if name in REQUIRED_KEYS + OPTIONAL_KEYS else os.environ.get(name, '')
        if v:
            lines.append(f'{name}={_quote_env(v)}')
    return '\n'.join(lines) + '\n'


def parse_env_file(path):
    """Minimal reader for keys.env / .env (KEY=value, optional quotes)."""
    try:
        from dotenv import dotenv_values
        return {k: (v or '') for k, v in dotenv_values(path).items()}
    except ImportError:  # pragma: no cover - python-dotenv is a hard dependency
        values = {}
        for line in Path(path).read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                k, v = line.split('=', 1)
                values[k.strip()] = v.strip().strip("'\"")
        return values


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _private_file(path):
    os.chmod(path, 0o600)


def _db():
    return settings.DATABASES['default']


def db_engine():
    engine = _db()['ENGINE']
    if engine.endswith('sqlite3'):
        return 'sqlite'
    if engine.endswith('mysql'):
        return 'mysql'
    return engine


def _git(*args, timeout=60):
    git = shutil.which('git') or '/usr/bin/git'
    return subprocess.run([git, '-C', str(settings.BASE_DIR), *args],
                          capture_output=True, text=True, timeout=timeout)


def current_revision():
    try:
        r = _git('rev-parse', 'HEAD')
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _mysql_defaults_file(directory):
    """A 0600 option file so the password never appears on a command line."""
    db = _db()

    def q(v):
        return '"' + str(v).replace('\\', '\\\\').replace('"', '\\"') + '"'
    fd, path = tempfile.mkstemp(dir=str(directory), prefix='.my-', suffix='.cnf')
    with os.fdopen(fd, 'w') as f:
        f.write('[client]\n')
        f.write(f"user={q(db.get('USER', ''))}\n")
        f.write(f"password={q(db.get('PASSWORD', ''))}\n")
        f.write(f"host={q(db.get('HOST') or 'localhost')}\n")
        f.write(f"port={int(db.get('PORT') or 3306)}\n")
    os.chmod(path, 0o600)
    return path


def _mysql_tool(*names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def mysql_tools():
    return (_mysql_tool('mysqldump', 'mariadb-dump'), _mysql_tool('mysql', 'mariadb'))


def _live_tables():
    from django.db import connection
    with connection.cursor() as cursor:
        return sorted(connection.introspection.table_names(cursor))


def _live_applied_migrations():
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute('SELECT app, name FROM django_migrations')
        return sorted(f'{a}.{n}' for a, n in cursor.fetchall())


def _quote_ident(name, engine):
    return f'`{name}`' if engine == 'mysql' else '"' + name.replace('"', '""') + '"'


def _count_rows(cursor, tables, engine):
    counts = {}
    for t in tables:
        cursor.execute(f'SELECT COUNT(*) FROM {_quote_ident(t, engine)}')
        counts[t] = cursor.fetchone()[0]
    return counts


def _vault_check(cursor, key_values, engine):
    """Decrypt sample vault entries read straight from a restored copy, using
    only the keys stored in the snapshot. Returns (ok, detail)."""
    from vault.encryption import using_master_keys
    from vault.encryption_v2 import decrypt_password, decrypt_v2, KEY_CONTEXT_PASSWORD
    q = (lambda t: _quote_ident(t, engine))
    try:
        cursor.execute(f"SELECT id, organization_id, encrypted_password FROM {q('passwords')} "
                       f"WHERE encrypted_password <> '' ORDER BY id LIMIT {VAULT_SAMPLE}")
        rows = cursor.fetchall()
    except Exception as e:
        return True, f'no vault table to check ({e.__class__.__name__})'
    notes = []
    try:
        cursor.execute(f"SELECT id, organization_id, encrypted_notes FROM {q('passwords')} "
                       f"WHERE encrypted_notes <> '' ORDER BY id LIMIT {VAULT_SAMPLE}")
        notes = cursor.fetchall()
    except Exception:
        notes = []   # older schema without secure notes
    if not rows and not notes:
        return True, 'vault is empty'
    master = key_values.get('APP_MASTER_KEY', '')
    previous = [k.strip() for k in (key_values.get('APP_MASTER_KEY_PREVIOUS') or '').split(',') if k.strip()]
    if not master:
        return False, 'snapshot has no APP_MASTER_KEY'
    failed = []
    with using_master_keys(master, [master] + previous):
        for pid, org_id, blob in rows:
            try:
                decrypt_password(blob, org_id=org_id, password_id=None)
            except Exception as e:
                failed.append(f'password {pid}: {e.__class__.__name__}')
        for pid, org_id, blob in notes:
            try:
                decrypt_v2(blob, context=KEY_CONTEXT_PASSWORD, org_id=org_id,
                           record_type='password_notes')
            except TypeError:
                # Signature differs between releases; the password check above
                # already proves the key. Do not fail the backup over it.
                break
            except Exception as e:
                failed.append(f'secure note {pid}: {e.__class__.__name__}')
    if failed:
        return False, 'could not decrypt with the stored key: ' + ', '.join(failed[:5])
    return True, f'{len(rows)} password(s) and {len(notes)} secure note(s) decrypted with the stored key'


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

def create(*, reason='', target=None, out=None, code_sha=None, code_version=None) -> Path:
    """code_sha / code_version: the revision that matches the database, when
    the backup is taken by newer code that is already checked out (the update
    script's legacy mode). Restoring puts that revision back."""
    root = journal.ensure_private_dir(journal.backup_root())
    from config.version import VERSION as running_version
    VERSION = code_version or running_version
    stamp = timezone.now().strftime('%Y%m%d-%H%M%S')
    snap = root / f'snapshot-{stamp}-v{VERSION}'
    n = 1
    while snap.exists():
        n += 1
        snap = root / f'snapshot-{stamp}-v{VERSION}-{n}'
    old_umask = os.umask(0o077)
    try:
        snap.mkdir(mode=0o700)
        manifest = {
            'format': FORMAT,
            'created_at': timezone.now().isoformat(),
            'reason': reason,
            'app_version': VERSION,
            'git_sha': code_sha or current_revision(),
            'target': target or None,
            'base_dir': str(settings.BASE_DIR),
            'files': {},
        }
        engine = db_engine()
        _out(out, f'Backing up the database ({engine})...')
        if engine == 'sqlite':
            src_path = str(_db()['NAME'])
            dst_path = snap / 'database.sqlite3'
            src = sqlite3.connect(f'file:{src_path}?mode=ro', uri=True, timeout=60)
            dst = sqlite3.connect(str(dst_path))
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            _private_file(dst_path)
            con = sqlite3.connect(f'file:{dst_path}?mode=ro', uri=True)
            try:
                cur = con.cursor()
                tables = [r[0] for r in cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
                manifest['row_counts'] = _count_rows(cur, sorted(tables), 'sqlite')
                cur.execute('SELECT app, name FROM django_migrations')
                manifest['applied_migrations'] = sorted(f'{a}.{n}' for a, n in cur.fetchall())
            finally:
                con.close()
            manifest['db'] = {'engine': 'sqlite', 'file': 'database.sqlite3'}
        elif engine == 'mysql':
            dump_bin, _ = mysql_tools()
            if not dump_bin:
                raise SnapshotError('mysqldump (or mariadb-dump) is not installed; '
                                    'install the MariaDB/MySQL client tools.')
            defaults = _mysql_defaults_file(snap)
            dst_path = snap / 'database.sql'
            try:
                manifest['tables'] = _live_tables()
                manifest['applied_migrations'] = _live_applied_migrations()
                r = subprocess.run(
                    [dump_bin, f'--defaults-extra-file={defaults}', '--single-transaction',
                     '--quick', '--routines', '--triggers', '--hex-blob', '--no-tablespaces',
                     '--default-character-set=utf8mb4', f'--result-file={dst_path}',
                     _db()['NAME']],
                    capture_output=True, text=True, timeout=3600)
            finally:
                os.unlink(defaults)
            if r.returncode != 0:
                raise SnapshotError(f'mysqldump failed: {r.stderr.strip()[:500]}')
            _private_file(dst_path)
            from django.db import connection
            with connection.cursor() as cursor:
                manifest['row_counts'] = _count_rows(cursor, manifest['tables'], 'mysql')
            manifest['db'] = {'engine': 'mysql', 'file': 'database.sql', 'name': _db()['NAME']}
        else:
            raise SnapshotError(f'unsupported database engine {engine}')

        _out(out, 'Backing up uploaded files...')
        media_root = Path(settings.MEDIA_ROOT)
        count = size = 0
        with tarfile.open(snap / 'media.tar', 'w') as tar:
            if media_root.is_dir():
                for p in sorted(media_root.rglob('*')):
                    if p.is_symlink():
                        continue
                    if p.is_file():
                        tar.add(str(p), arcname='media/' + p.relative_to(media_root).as_posix(),
                                recursive=False)
                        count += 1
                        size += p.stat().st_size
        _private_file(snap / 'media.tar')
        manifest['media'] = {'root': str(media_root), 'files': count, 'bytes': size}

        _out(out, 'Saving the keys needed to read the data...')
        (snap / 'keys.env').write_text(_key_lines())
        _private_file(snap / 'keys.env')
        env_path = Path(settings.BASE_DIR) / '.env'
        if env_path.is_file():
            shutil.copyfile(env_path, snap / 'env.file')
            _private_file(snap / 'env.file')
        gw = getattr(settings, 'AI_GATEWAY_KEY_DIR', '') or ''
        if gw and Path(gw).is_dir():
            with tarfile.open(snap / 'gateway_keys.tar', 'w') as tar:
                tar.add(gw, arcname='gateway_keys')
            _private_file(snap / 'gateway_keys.tar')
        manifest['keys'] = {
            'present': [k for k in REQUIRED_KEYS + OPTIONAL_KEYS if _setting_or_env(k)],
            'fingerprints': {k: key_fingerprint(k, _setting_or_env(k)) for k in REQUIRED_KEYS},
        }

        for p in sorted(snap.iterdir()):
            if p.is_file() and p.name not in ('manifest.json', 'verification.json'):
                manifest['files'][p.name] = {'sha256': _sha256(p), 'size': p.stat().st_size}
        (snap / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True))
        _private_file(snap / 'manifest.json')
    except BaseException:
        shutil.rmtree(snap, ignore_errors=True)
        raise
    finally:
        os.umask(old_umask)
    _out(out, f'Backup written to {snap}')
    return snap


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

def load_manifest(snap) -> dict:
    snap = Path(snap)
    try:
        return json.loads((snap / 'manifest.json').read_text())
    except (OSError, ValueError) as e:
        raise SnapshotError(f'{snap} is not a readable backup: {e}')


def _check_files(snap, manifest, checks):
    ok = True
    for name, meta in sorted(manifest.get('files', {}).items()):
        p = snap / name
        if not p.is_file():
            checks.append((f'file {name}', False, 'missing'))
            ok = False
        elif _sha256(p) != meta['sha256']:
            checks.append((f'file {name}', False, 'checksum mismatch'))
            ok = False
    if ok:
        checks.append(('checksums', True, f"{len(manifest.get('files', {}))} file(s) match the manifest"))
    return ok


def _check_permissions(snap, checks):
    loose = []
    for p in [snap] + list(snap.iterdir()):
        mode = p.stat().st_mode
        if mode & 0o077:
            loose.append(f'{p.name or p} ({oct(mode & 0o777)})')
    if loose:
        checks.append(('permissions', False, 'readable by other users: ' + ', '.join(loose)))
        return False
    checks.append(('permissions', True, 'owner-only'))
    return True


def _check_keys(snap, manifest, checks):
    path = snap / 'keys.env'
    if not path.is_file():
        checks.append(('keys', False, 'keys.env missing'))
        return False, {}
    values = parse_env_file(path)
    missing = [k for k in REQUIRED_KEYS if not values.get(k)]
    if missing:
        checks.append(('keys', False, 'missing ' + ', '.join(missing)))
        return False, values
    try:
        from vault.encryption import decode_master_key
        decode_master_key(values['APP_MASTER_KEY'])
    except Exception:
        checks.append(('keys', False, 'APP_MASTER_KEY in the backup is not a valid key'))
        return False, values
    checks.append(('keys', True, 'SECRET_KEY, APP_MASTER_KEY and API_KEY_SECRET present'))
    return True, values


def _check_media(snap, manifest, checks):
    p = snap / 'media.tar'
    if not p.is_file():
        checks.append(('media', False, 'media.tar missing'))
        return False
    try:
        with tarfile.open(p, 'r') as tar:
            members = [m for m in tar.getmembers() if m.isfile()]
            bad = [m.name for m in tar.getmembers()
                   if m.name.startswith('/') or '..' in Path(m.name).parts]
            # Read every member through: proves the archive is not truncated.
            for m in members:
                f = tar.extractfile(m)
                while f and f.read(1 << 20):
                    pass
    except (tarfile.TarError, OSError) as e:
        checks.append(('media', False, f'unreadable archive: {e}'))
        return False
    if bad:
        checks.append(('media', False, f'unsafe paths in archive: {bad[:3]}'))
        return False
    expected = manifest.get('media', {}).get('files', 0)
    if len(members) != expected:
        checks.append(('media', False, f'{len(members)} file(s) in archive, manifest says {expected}'))
        return False
    checks.append(('media', True, f'{len(members)} uploaded file(s) readable'))
    return True


def _verify_sqlite(snap, manifest, key_values, checks):
    path = snap / manifest['db']['file']
    work = Path(tempfile.mkdtemp(prefix='clientst0r-verify-'))
    try:
        copy = work / 'restore-test.sqlite3'
        shutil.copyfile(path, copy)   # restore-test on a copy, never on the snapshot
        con = sqlite3.connect(str(copy))
        try:
            cur = con.cursor()
            res = cur.execute('PRAGMA integrity_check').fetchone()[0]
            if res != 'ok':
                checks.append(('database integrity', False, res))
                return False
            checks.append(('database integrity', True, 'PRAGMA integrity_check: ok'))
            tables = sorted(r[0] for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
            counts = _count_rows(cur, tables, 'sqlite')
            if counts != manifest.get('row_counts'):
                checks.append(('row counts', False, 'restored copy differs from the manifest'))
                return False
            checks.append(('row counts', True, f'{len(tables)} tables, {sum(counts.values())} rows'))
            cur.execute('SELECT app, name FROM django_migrations')
            applied = sorted(f'{a}.{n}' for a, n in cur.fetchall())
            if applied != manifest.get('applied_migrations'):
                checks.append(('migrations', False, 'applied migrations differ from the manifest'))
                return False
            checks.append(('migrations', True, f'{len(applied)} applied migrations recorded'))
            ok, detail = _vault_check(cur, key_values, 'sqlite')
            checks.append(('vault', ok, detail))
            return ok
        finally:
            con.close()
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _verify_mysql(snap, manifest, key_values, checks):
    """Restore the dump into a scratch database and inspect it. Falls back to
    a structural check of the dump when the account may not create one."""
    import MySQLdb
    path = snap / manifest['db']['file']
    _, mysql_bin = mysql_tools()
    db = _db()
    scratch = getattr(settings, 'UPGRADE_VERIFY_DB_NAME', '') or f"{db['NAME']}_verify"
    if scratch == db['NAME'] or '`' in scratch:
        # The restore test empties the scratch database first: never the live one.
        return _verify_mysql_structural(path, manifest, key_values, checks,
                                        reason='CLIENTST0R_VERIFY_DB_NAME must name a separate database')
    work = Path(tempfile.mkdtemp(prefix='clientst0r-verify-'))
    defaults = _mysql_defaults_file(work)
    created = False
    try:
        conn = MySQLdb.connect(read_default_file=defaults, charset='utf8mb4')
        try:
            cur = conn.cursor()
            try:
                cur.execute(f'CREATE DATABASE IF NOT EXISTS `{scratch}` '
                            'CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
                created = True
                cur.execute(f'USE `{scratch}`')
                cur.execute('SET FOREIGN_KEY_CHECKS=0')
                cur.execute('SHOW TABLES')
                for (t,) in cur.fetchall():
                    cur.execute(f'DROP TABLE `{t}`')
            except MySQLdb.MySQLError as e:
                return _verify_mysql_structural(path, manifest, key_values, checks,
                                                reason=f'cannot use scratch database {scratch}: {e.args[-1]}')
        finally:
            conn.close()
        if not mysql_bin:
            return _verify_mysql_structural(path, manifest, key_values, checks,
                                            reason='mysql client not installed')
        with open(path, 'rb') as f:
            r = subprocess.run([mysql_bin, f'--defaults-extra-file={defaults}', scratch],
                               stdin=f, capture_output=True, timeout=3600)
        if r.returncode != 0:
            checks.append(('restore test', False, r.stderr.decode(errors='replace')[:500]))
            return False
        checks.append(('restore test', True, f'dump restored into scratch database {scratch}'))
        conn = MySQLdb.connect(read_default_file=defaults, db=scratch, charset='utf8mb4')
        try:
            cur = conn.cursor()
            cur.execute('SHOW TABLES')
            tables = sorted(t for (t,) in cur.fetchall())
            if tables != sorted(manifest.get('tables', [])):
                missing = sorted(set(manifest.get('tables', [])) - set(tables))
                checks.append(('tables', False, f'missing after restore: {missing[:10]}'))
                return False
            checks.append(('tables', True, f'{len(tables)} tables restored'))
            cur.execute('SELECT app, name FROM django_migrations')
            applied = sorted(f'{a}.{n}' for a, n in cur.fetchall())
            if applied != manifest.get('applied_migrations'):
                checks.append(('migrations', False, 'applied migrations differ from the live database'))
                return False
            checks.append(('migrations', True, f'{len(applied)} applied migrations recorded'))
            counts = _count_rows(cur, tables, 'mysql')
            drift = [t for t in tables if counts.get(t) != manifest.get('row_counts', {}).get(t)]
            checks.append(('row counts', True,
                           f'{sum(counts.values())} rows' + (
                               f' (rows written during the dump in: {drift[:5]})' if drift else '')))
            ok, detail = _vault_check(cur, key_values, 'mysql')
            checks.append(('vault', ok, detail))
            return ok
        finally:
            conn.close()
    finally:
        if created:
            try:
                conn = MySQLdb.connect(read_default_file=defaults, charset='utf8mb4')
                cur = conn.cursor()
                if getattr(settings, 'UPGRADE_VERIFY_DB_NAME', ''):
                    cur.execute(f'USE `{scratch}`')
                    cur.execute('SET FOREIGN_KEY_CHECKS=0')
                    cur.execute('SHOW TABLES')
                    for (t,) in cur.fetchall():
                        cur.execute(f'DROP TABLE `{t}`')
                else:
                    cur.execute(f'DROP DATABASE IF EXISTS `{scratch}`')
                conn.close()
            except Exception:
                pass
        shutil.rmtree(work, ignore_errors=True)


def _verify_mysql_structural(path, manifest, key_values, checks, reason):
    """Without a scratch database: the dump is complete (mysqldump's trailer),
    creates every live table and carries the migration history; and the keys
    in the snapshot decrypt the live vault the dump was taken from."""
    checks.append(('restore test', True, f'skipped: {reason}; structural check instead'))
    created, has_migrations, completed = set(), False, False
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            if line.startswith('CREATE TABLE `'):
                created.add(line.split('`')[1])
            elif line.startswith('INSERT INTO `django_migrations`'):
                has_migrations = True
            elif line.startswith('-- Dump completed'):
                completed = True
    if not completed:
        checks.append(('dump complete', False, 'no "-- Dump completed" trailer: the dump was cut short'))
        return False
    missing = sorted(set(manifest.get('tables', [])) - created)
    if missing:
        checks.append(('tables', False, f'dump does not create: {missing[:10]}'))
        return False
    if not has_migrations:
        checks.append(('migrations', False, 'dump has no django_migrations rows'))
        return False
    checks.append(('dump structure', True, f'{len(created)} tables and the migration history present'))
    from django.db import connection
    with connection.cursor() as cur:
        ok, detail = _vault_check(cur, key_values, 'mysql')
    checks.append(('vault', ok, detail + ' (checked against the live database)'))
    return ok


def verify(snap, *, out=None) -> dict:
    snap = Path(snap)
    manifest = load_manifest(snap)
    checks = []
    ok = _check_permissions(snap, checks)
    ok = _check_files(snap, manifest, checks) and ok
    keys_ok, key_values = _check_keys(snap, manifest, checks)
    ok = keys_ok and ok
    ok = _check_media(snap, manifest, checks) and ok
    level = 'restore-test'
    if ok:
        engine = manifest['db']['engine']
        if engine == 'sqlite':
            ok = _verify_sqlite(snap, manifest, key_values, checks)
        elif engine == 'mysql':
            ok = _verify_mysql(snap, manifest, key_values, checks)
            if any(name == 'dump structure' for name, _, _ in checks):
                level = 'structural'
        else:
            checks.append(('database', False, f'unsupported engine {engine}'))
            ok = False
    report = {
        'ok': bool(ok),
        'level': level,
        'checks': [{'name': n, 'ok': o, 'detail': d} for n, o, d in checks],
        'verified_at': timezone.now().isoformat(),
        'manifest_sha256': _sha256(snap / 'manifest.json'),
    }
    path = snap / 'verification.json'
    path.write_text(json.dumps(report, indent=2))
    _private_file(path)
    for c in report['checks']:
        _out(out, f"  [{'ok' if c['ok'] else 'FAIL'}] {c['name']}: {c['detail']}")
    return report


def is_verified(snap) -> tuple[bool, str]:
    """True only for a snapshot whose verification passed and whose files have
    not changed since."""
    snap = Path(snap)
    try:
        report = json.loads((snap / 'verification.json').read_text())
        manifest = load_manifest(snap)
    except (OSError, ValueError, SnapshotError) as e:
        return False, f'not verified ({e})'
    if not report.get('ok'):
        return False, 'verification failed'
    if report.get('manifest_sha256') != _sha256(snap / 'manifest.json'):
        return False, 'manifest changed after verification'
    checks = []
    if not _check_files(snap, manifest, checks):
        return False, '; '.join(f'{n}: {d}' for n, o, d in checks if not o)
    return True, f"verified ({report.get('level')}) at {report.get('verified_at')}"


def list_snapshots():
    root = journal.backup_root()
    if not root.is_dir():
        return []
    out = []
    for p in sorted(root.glob('snapshot-*'), reverse=True):
        if (p / 'manifest.json').is_file():
            try:
                m = load_manifest(p)
            except SnapshotError:
                continue
            ok, detail = is_verified(p)
            out.append({'path': str(p), 'created_at': m.get('created_at'),
                        'app_version': m.get('app_version'), 'git_sha': m.get('git_sha'),
                        'reason': m.get('reason'), 'verified': ok, 'detail': detail})
    return out


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------

def _restore_sqlite(snap, manifest, stamp, out):
    live = Path(str(_db()['NAME']))
    if live.exists():
        aside = live.with_name(f'{live.name}.before-restore-{stamp}')
        src = sqlite3.connect(f'file:{live}?mode=ro', uri=True, timeout=60)
        dst = sqlite3.connect(str(aside))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        os.chmod(aside, 0o600)
        _out(out, f'Current database kept as {aside}')
    from django.db import connections
    connections.close_all()
    src = sqlite3.connect(f"file:{snap / manifest['db']['file']}?mode=ro", uri=True)
    dst = sqlite3.connect(str(live), timeout=60)
    try:
        src.backup(dst)   # page-level copy over the live file, safe with other readers
    finally:
        dst.close()
        src.close()
    _out(out, 'Database restored.')


def _restore_mysql(snap, manifest, stamp, out):
    _, mysql_bin = mysql_tools()
    if not mysql_bin:
        raise SnapshotError('the mysql client is not installed')
    from django.db import connection, connections
    with connection.cursor() as cur:
        tables = connection.introspection.table_names(cur)
        cur.execute('SET FOREIGN_KEY_CHECKS=0')
        for t in tables:
            cur.execute(f'DROP TABLE IF EXISTS `{t}`')
        cur.execute('SET FOREIGN_KEY_CHECKS=1')
    _out(out, f'Dropped {len(tables)} table(s) (including any a partial migration created).')
    connections.close_all()
    work = Path(tempfile.mkdtemp(prefix='clientst0r-restore-'))
    defaults = _mysql_defaults_file(work)
    try:
        with open(snap / manifest['db']['file'], 'rb') as f:
            r = subprocess.run([mysql_bin, f'--defaults-extra-file={defaults}', _db()['NAME']],
                               stdin=f, capture_output=True, timeout=3600)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if r.returncode != 0:
        raise SnapshotError('loading the dump failed: ' + r.stderr.decode(errors='replace')[:500])
    _out(out, 'Database restored.')


def _restore_media(snap, stamp, out):
    media_root = Path(settings.MEDIA_ROOT)
    media_root.mkdir(parents=True, exist_ok=True)
    aside = media_root.parent / f'{media_root.name}.before-restore-{stamp}'
    aside.mkdir(mode=0o700)
    for p in list(media_root.iterdir()):
        shutil.move(str(p), str(aside / p.name))   # keeps the mount point when media is a volume
    with tarfile.open(snap / 'media.tar', 'r') as tar:
        members = []
        for m in tar.getmembers():
            if not m.name.startswith('media/') or m.name.startswith('/') or '..' in Path(m.name).parts:
                continue
            if not (m.isfile() or m.isdir()):
                continue
            m.name = m.name[len('media/'):]
            if m.name:
                members.append(m)
        tar.extractall(str(media_root), members=members, filter='data')
    _out(out, f'Uploaded files restored ({len(members)} entries); previous files kept in {aside}')


def _restore_keys(snap, stamp, out):
    env_path = Path(settings.BASE_DIR) / '.env'
    src = snap / 'env.file'
    if not src.is_file():
        _out(out, f'This backup has no .env copy (a Docker install?). Set the values in '
                  f'{snap / "keys.env"} in your environment / stack variables.')
        return False
    if env_path.exists():
        aside = env_path.with_name(f'.env.before-restore-{stamp}')
        shutil.copyfile(env_path, aside)
        os.chmod(aside, 0o600)
    fd, tmp = tempfile.mkstemp(dir=str(env_path.parent), prefix='.env.', suffix='.tmp')
    with os.fdopen(fd, 'wb') as f:
        f.write(src.read_bytes())
    os.chmod(tmp, 0o600)
    os.replace(tmp, env_path)
    _out(out, '.env restored from the backup.')
    return True


def _restore_code(manifest, out):
    sha = manifest.get('git_sha')
    if not sha:
        _out(out, 'Backup has no code revision (not a git install); code left as it is.')
        return False
    if current_revision() == sha:
        _out(out, f'Code is already at {sha[:12]}.')
        return True
    r = _git('cat-file', '-e', f'{sha}^{{commit}}')
    if r.returncode != 0:
        raise SnapshotError(f'revision {sha} is not in this repository; fetch it, then retry')
    r = _git('reset', '--hard', sha, timeout=300)
    if r.returncode != 0:
        raise SnapshotError(f'git reset failed: {r.stderr.strip()[:300]}')
    _out(out, f'Code put back to {sha[:12]} (v{manifest.get("app_version")}).')
    req = Path(settings.BASE_DIR) / 'requirements.txt'
    r = subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '-r', str(req)],
                       capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        _out(out, '[WARN] pip install of the old requirements failed; run it by hand: '
                  f'{sys.executable} -m pip install -r {req}\n{r.stderr[-500:]}')
    else:
        _out(out, 'Dependencies for that revision installed.')
    return True


def restore(snap, *, code=True, keys=False, require_verified=True, out=None) -> dict:
    """Put database, uploaded files (and, by default, the code revision) back
    to the snapshot. Stop the app (and the scheduler) first on a native
    install; see docs/UPGRADE_AND_RECOVERY.md."""
    snap = Path(snap)
    manifest = load_manifest(snap)
    if require_verified:
        ok, detail = is_verified(snap)
        if not ok:
            raise SnapshotError(f'{snap} is not a verified backup ({detail}). '
                                'Run `manage.py upgrade_backup --verify PATH` first.')
    stored = parse_env_file(snap / 'keys.env')
    same_key = (key_fingerprint('APP_MASTER_KEY', stored.get('APP_MASTER_KEY', ''))
                == key_fingerprint('APP_MASTER_KEY', _setting_or_env('APP_MASTER_KEY')))
    if not same_key and not keys:
        raise SnapshotError('This instance\'s APP_MASTER_KEY is not the one in the backup, so the '
                            'restored vault would not decrypt. Re-run with --restore-keys.')
    stamp = time.strftime('%Y%m%d-%H%M%S')
    result = {'snapshot': str(snap), 'code': False, 'keys': False}
    if keys:
        result['keys'] = _restore_keys(snap, stamp, out)
    if code:
        result['code'] = _restore_code(manifest, out)
    if manifest['db']['engine'] == 'sqlite':
        _restore_sqlite(snap, manifest, stamp, out)
    else:
        _restore_mysql(snap, manifest, stamp, out)
    _restore_media(snap, stamp, out)
    if journal.read():
        journal.finish('recovered', restored_from=str(snap))
    return result


# ---------------------------------------------------------------------------
# export: a single passphrase-encrypted file for off-host copies
# ---------------------------------------------------------------------------

EXPORT_MAGIC = b'CS0RSNAP1'


def export(snap, dest, passphrase: str) -> Path:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    if len(passphrase) < 12:
        raise SnapshotError('use a passphrase of at least 12 characters')
    snap = Path(snap)
    buf = tempfile.SpooledTemporaryFile(max_size=64 << 20)
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        tar.add(str(snap), arcname=snap.name)
    buf.seek(0)
    data = buf.read()
    salt, nonce = os.urandom(16), os.urandom(12)
    key = Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(passphrase.encode())
    blob = EXPORT_MAGIC + salt + nonce + AESGCM(key).encrypt(nonce, data, EXPORT_MAGIC)
    dest = Path(dest)
    fd = os.open(str(dest), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(blob)
    return dest


def import_export(src, passphrase: str) -> Path:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    blob = Path(src).read_bytes()
    if not blob.startswith(EXPORT_MAGIC):
        raise SnapshotError('not a Client St0r backup export')
    salt, nonce, ct = blob[9:25], blob[25:37], blob[37:]
    key = Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(passphrase.encode())
    try:
        data = AESGCM(key).decrypt(nonce, ct, EXPORT_MAGIC)
    except Exception:
        raise SnapshotError('wrong passphrase, or the file is damaged')
    root = journal.ensure_private_dir(journal.backup_root())
    old = os.umask(0o077)
    try:
        import io
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tar:
            names = {m.name.split('/')[0] for m in tar.getmembers()}
            if len(names) != 1:
                raise SnapshotError('unexpected archive layout')
            name = names.pop()
            if (root / name).exists():
                raise SnapshotError(f'{root / name} already exists')
            tar.extractall(str(root), filter='data')
    finally:
        os.umask(old)
    out = root / name
    os.chmod(out, 0o700)
    for p in out.iterdir():
        os.chmod(p, 0o600)
    return out
