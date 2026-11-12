"""Checks that must pass before an upgrade changes anything.

Each check returns a Check(name, status, detail, hint) where status is
'ok', 'warn' or 'fail'. Any 'fail' stops Apply before code, database or
files are touched. The same checks run from Settings -> Updates ("Run
preflight checks"), from `manage.py upgrade_preflight` and at the start of
every Apply, and their output is logged.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from django.conf import settings

from . import journal, snapshot
from .revision import Target, git, is_git_install, new_migrations

logger = logging.getLogger('core')

MIN_FREE_BYTES = 500 * 1024 * 1024


@dataclass
class Check:
    name: str
    status: str      # ok | warn | fail
    detail: str
    hint: str = ''

    def as_dict(self):
        return asdict(self)


def _size_of(path: Path) -> int:
    total = 0
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        for p in path.rglob('*'):
            try:
                if p.is_file() and not p.is_symlink():
                    total += p.stat().st_size
            except OSError:
                pass
    return total


def _human(n):
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024:
            return f'{n:.0f} {unit}'
        n /= 1024
    return f'{n:.1f} PB'


def check_journal():
    a = journal.assess()
    if a['state'] == 'running':
        return Check('previous upgrade', 'fail', a['message'], 'Wait for it to finish.')
    if a['needs_recovery']:
        return Check('previous upgrade', 'fail', a['message'],
                     'Run `manage.py upgrade_status` and follow docs/UPGRADE_AND_RECOVERY.md '
                     '(resume with `manage.py upgrade_apply --resume`, or restore the backup).')
    return Check('previous upgrade', 'ok', a['message'])


def check_git(target: Target | None):
    if not is_git_install():
        return Check('code checkout', 'fail', f'{settings.BASE_DIR} is not a git checkout',
                     'Docker installs upgrade by pulling a new image; see docs/UPGRADE_AND_RECOVERY.md.')
    r = git('remote', 'get-url', 'origin', timeout=10)
    if r.returncode != 0:
        return Check('code checkout', 'fail', 'no "origin" remote', 'git remote add origin <repo url>')
    st = git('status', '--porcelain', '--untracked-files=no', timeout=30)
    changed = [line[3:] for line in st.stdout.splitlines() if line.strip()]
    if changed:
        return Check('code checkout', 'warn',
                     f'{len(changed)} locally modified tracked file(s) will be replaced by the '
                     f'reviewed revision: {", ".join(changed[:8])}',
                     'Commit or copy any local edits you want to keep before applying.')
    return Check('code checkout', 'ok', f'git checkout, origin {r.stdout.strip()}')


def measure_sizes():
    """(database bytes, uploaded-files bytes): what a backup has to copy."""
    db = settings.DATABASES['default']
    db_size = _size_of(Path(str(db['NAME']))) if snapshot.db_engine() == 'sqlite' else 0
    if snapshot.db_engine() == 'mysql':
        try:
            from django.db import connection
            with connection.cursor() as c:
                c.execute('SELECT COALESCE(SUM(data_length + index_length), 0) FROM '
                          'information_schema.tables WHERE table_schema = DATABASE()')
                db_size = int(c.fetchone()[0])
        except Exception:
            db_size = 0
    return db_size, _size_of(Path(settings.MEDIA_ROOT))


def check_disk():
    db_size, media = measure_sizes()
    need = 2 * (db_size + media) + MIN_FREE_BYTES
    rows = []
    for label, path in (('install directory', Path(settings.BASE_DIR)),
                        ('backup directory', journal.backup_root())):
        probe = path
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        free = shutil.disk_usage(probe).free
        rows.append((label, free))
    short = [f'{label}: {_human(free)} free' for label, free in rows if free < need]
    detail = (f'database {_human(db_size)}, uploads {_human(media)}; need about {_human(need)} '
              f'free for the backup and the new release. ' +
              '; '.join(f'{label}: {_human(free)} free' for label, free in rows))
    if short:
        return Check('disk space', 'fail', detail,
                     'Free some space. Old pre-upgrade backups can be removed under Settings -> '
                     'Updates -> Pre-upgrade backups ("Clean up now", or delete one; lower '
                     '"Backups to keep"), or with `manage.py upgrade_backup --prune` / '
                     f'`--delete PATH`. They live in {journal.backup_root()}.')
    return Check('disk space', 'ok', detail)


def check_database():
    from django.db import connection
    try:
        connection.ensure_connection()
        with connection.cursor() as c:
            c.execute('SELECT 1')
            c.fetchone()
    except Exception as e:
        return Check('database', 'fail', f'cannot query the database: {e}',
                     'Check DB_* in .env and that the database server is running.')
    return Check('database', 'ok', f"{connection.vendor} reachable")


def check_pending_migrations(target: Target | None, installed_sha: str):
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    try:
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    except Exception as e:
        return Check('migrations', 'fail', f'cannot read the migration state: {e}',
                     'Run `manage.py migration_doctor`.')
    unapplied_now = [f'{m.app_label}.{m.name}' for m, backwards in plan if not backwards]
    parts = []
    status = 'ok'
    if unapplied_now:
        status = 'warn'
        parts.append(f'{len(unapplied_now)} migration(s) of the INSTALLED code are not applied yet '
                     f'({", ".join(unapplied_now[:5])}): an earlier upgrade did not finish migrating')
    if target and installed_sha:
        added = new_migrations(installed_sha, target.sha)
        if added is None:
            parts.append('could not list the migrations the new revision adds')
        elif added:
            parts.append(f'the new revision adds {len(added)} migration(s): ' +
                         ', '.join(p.replace('/migrations/', '.').removesuffix('.py') for p in added[:12])
                         + (' ...' if len(added) > 12 else ''))
        else:
            parts.append('the new revision adds no migrations')
    if not parts:
        parts.append('all migrations of the installed code are applied')
    return Check('migrations', status, '; '.join(parts),
                 'Run `manage.py migration_doctor` before applying.' if unapplied_now else '')


def check_media():
    root = Path(settings.MEDIA_ROOT)
    try:
        root.mkdir(parents=True, exist_ok=True)
        fd, probe = tempfile.mkstemp(dir=str(root), prefix='.write-test-')
        os.close(fd)
        os.unlink(probe)
    except OSError as e:
        return Check('uploads directory', 'fail', f'{root} is not writable: {e}',
                     f'sudo chown -R $(whoami) {root}')
    return Check('uploads directory', 'ok', f'{root} writable')


def check_keys():
    rows = snapshot.required_keys_status()
    bad = [f'{n}: {d}' for n, ok, d in rows if not ok]
    env_path = Path(settings.BASE_DIR) / '.env'
    where = '.env' if env_path.is_file() else 'environment'
    if bad:
        return Check('required keys', 'fail', '; '.join(bad),
                     f'Set them in {where}. Without APP_MASTER_KEY the vault cannot be read.')
    detail = f'SECRET_KEY, APP_MASTER_KEY, API_KEY_SECRET present ({where})'
    if env_path.is_file():
        mode = env_path.stat().st_mode & 0o777
        if mode & 0o077:
            return Check('required keys', 'warn', detail + f'; .env is mode {oct(mode)}',
                         f'chmod 600 {env_path}')
    return Check('required keys', 'ok', detail)


def check_backup_destination():
    root = journal.backup_root()
    try:
        journal.ensure_private_dir(root)
        fd, probe = tempfile.mkstemp(dir=str(root), prefix='.write-test-')
        os.close(fd)
        os.unlink(probe)
    except OSError as e:
        return Check('backup destination', 'fail', f'{root} not writable: {e}',
                     'Set CLIENTST0R_BACKUP_DIR to a writable directory.')
    if snapshot.db_engine() == 'mysql':
        dump_bin, client = snapshot.mysql_tools()
        if not dump_bin:
            return Check('backup destination', 'fail', 'mysqldump / mariadb-dump not installed',
                         'sudo apt-get install mariadb-client')
        if not client:
            return Check('backup destination', 'warn', 'mysql client not installed: backups can be '
                         'taken but not restore-tested', 'sudo apt-get install mariadb-client')
    return Check('backup destination', 'ok', f'{root} (owner-only)')


def check_dependencies(target: Target | None, timeout=300):
    """`pip install --dry-run` of the target's requirements into this venv."""
    req_text = None
    if target:
        try:
            from .revision import show_file
            req_text = show_file(target.sha, 'requirements.txt')
        except Exception as e:
            return Check('python dependencies', 'fail', f'cannot read requirements.txt at the target: {e}')
    req = Path(settings.BASE_DIR) / 'requirements.txt'
    tmp = None
    if req_text is not None:
        fd, tmp = tempfile.mkstemp(prefix='clientst0r-req-', suffix='.txt')
        with os.fdopen(fd, 'w') as f:
            f.write(req_text)
        req = Path(tmp)
    try:
        r = subprocess.run([sys.executable, '-m', 'pip', 'install', '--dry-run', '--quiet',
                            '--disable-pip-version-check', '-r', str(req)],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return Check('python dependencies', 'warn', f'pip did not finish within {timeout}s',
                     'Check PyPI connectivity; the update will retry the install.')
    except OSError as e:
        return Check('python dependencies', 'fail', f'cannot run pip: {e}')
    finally:
        if tmp:
            os.unlink(tmp)
    if r.returncode != 0:
        if 'no such option: --dry-run' in r.stderr:
            return Check('python dependencies', 'warn', 'pip is too old for --dry-run (needs 22.2+)',
                         f'{sys.executable} -m pip install --upgrade pip')
        tail = (r.stderr or r.stdout).strip().splitlines()[-6:]
        return Check('python dependencies', 'fail', 'the new requirements cannot be installed: ' +
                     ' | '.join(tail),
                     'Usually a missing build library (see the error) or no route to PyPI.')
    return Check('python dependencies', 'ok', 'requirements resolve and are installable')


def run(target: Target | None = None, *, installed_sha: str = '', deps=True) -> list[Check]:
    checks = []
    for fn in (check_journal,
               lambda: check_git(target),
               check_disk,
               check_database,
               lambda: check_pending_migrations(target, installed_sha),
               check_media,
               check_keys,
               check_backup_destination):
        try:
            checks.append(fn())
        except Exception as e:   # a broken check must fail closed, not crash Apply
            logger.exception('preflight check crashed')
            checks.append(Check(getattr(fn, '__name__', 'check'), 'fail', f'check crashed: {e}'))
    if deps:
        checks.append(check_dependencies(target))
    for c in checks:
        (logger.warning if c.status != 'ok' else logger.info)(
            'upgrade preflight %s: %s %s', c.name, c.status, c.detail)
    return checks


def failed(checks):
    return [c for c in checks if c.status == 'fail']
