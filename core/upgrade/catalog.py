"""Available Versions: every discovered version as one row, with what it is
relative to the installed build and whether it can be installed.

Three separate questions, never mixed:

    visible       every published stable release, every published
                  pre-release, and the head of main, whatever the channel
    recommended   the channel's target (core.upgrade.channels._decide)
    installable   this module: signature state, compatibility with the
                  database (for anything older than what is installed),
                  recovery state, git checkout. Apply checks it all again on
                  the server (core.views.apply_update, core.upgrade.apply).

Installing a version outside the channel is allowed after confirmation and
never changes the configured channel.
"""
from __future__ import annotations

import functools
import hashlib
import logging

from . import discovery
from .discovery import INSTALLABLE_SIGNATURES, parse_version

logger = logging.getLogger('core')

TYPE_LABELS = {'stable': 'Stable', 'prerelease': 'Prerelease', 'development': 'Development'}
# Marker of an update script that installs exactly CLIENTST0R_TARGET_SHA.
# Older revisions' scripts fetched and installed main instead; never run one.
PINNED_SCRIPT_MARKER = 'reset --hard "$TARGET_SHA"'


# ---------------------------------------------------------------------------
# installing something older: is the database compatible?
# ---------------------------------------------------------------------------

def _local_apps():
    """{app_label: 'path/relative/to/BASE_DIR'} for this project's own apps."""
    from pathlib import Path
    from django.apps import apps
    from django.conf import settings
    base = Path(settings.BASE_DIR).resolve()
    out = {}
    for cfg in apps.get_app_configs():
        try:
            rel = Path(cfg.path).resolve().relative_to(base)
        except ValueError:
            continue
        if rel.parts and rel.parts[0] in ('venv', '.venv', 'node_modules'):
            continue
        out[cfg.label] = rel.as_posix()
    return out


def applied_local_migrations():
    """Sorted (app_label, migration_name) the database records for this
    project's own apps."""
    from django.db import connection
    from django.db.migrations.recorder import MigrationRecorder
    local = _local_apps()
    applied = MigrationRecorder(connection).applied_migrations()
    return sorted((app, name) for app, name in applied if app in local)


@functools.lru_cache(maxsize=512)
def _compat(sha, applied_digest, applied):
    from .revision import commit_available, migration_files_at, show_file, RevisionError
    if not commit_available(sha):
        return 'unchecked', ('the commit is not in this checkout yet; compatibility is checked when '
                             'you review it'), ()
    files = migration_files_at(sha)
    if files is None:
        return 'unchecked', 'could not list the migrations of that revision', ()
    local = _local_apps()
    present = set()
    for path in files:
        d, _, mod = path.rpartition('/migrations/')
        present.add((d, mod[:-3]))
    missing = tuple(f'{app}.{name}' for app, name in applied
                    if (local.get(app), name) not in present)
    if missing:
        return 'unsafe', (f'the database has {len(missing)} migration(s) that version does not have '
                          f'({", ".join(missing[:4])}{" ..." if len(missing) > 4 else ""}); going '
                          'back would need reverse migrations. Restore a backup taken on that '
                          'version instead.'), missing
    try:
        script = show_file(sha, 'deploy/update_instructions.sh')
    except RevisionError:
        script = ''
    if PINNED_SCRIPT_MARKER not in script:
        return 'unsafe', ('that version\'s update script cannot install a pinned revision (it '
                          'predates verified installs and would install main instead)'), ()
    return 'safe', 'no schema change: the database has no migration that version lacks', ()


def downgrade_compatibility(sha):
    """('safe' | 'unsafe' | 'unchecked', detail, missing migrations) for
    installing revision `sha` over the current database."""
    try:
        applied = tuple(applied_local_migrations())
    except Exception as e:
        return 'unchecked', f'could not read the applied migrations ({e})', ()
    digest = hashlib.sha256(repr(applied).encode()).hexdigest()
    try:
        return _compat(sha, digest, applied)
    except Exception as e:   # a broken check never makes something installable
        logger.exception('downgrade compatibility check failed')
        return 'unsafe', f'the compatibility check failed ({e})', ()


# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------

def _relation(row_version, row_sha, inst, *, development=False):
    if row_sha and row_sha == inst.get('sha'):
        return 'installed'
    rv, iv = parse_version(row_version), parse_version(inst.get('version'))
    if rv is None or iv is None:
        return 'newer' if development else 'unknown'
    if rv > iv:
        return 'newer'
    if rv < iv:
        return 'older'
    # Same version string, different commit: a build of main between two
    # version bumps, or a release re-tagged. Not older.
    return 'same_version'


def build(state, *, upgrade_state=None, check_compat=True):
    """Rows for the Available Versions table, newest first by real date."""
    inst = state.get('installed') or {}
    channel = state.get('channel') or 'stable'
    target = state.get('target') or {}
    from .channels import CHANNEL_TYPES
    in_channel_types = CHANNEL_TYPES.get(channel, ('stable',))
    blocked = None
    if upgrade_state and (upgrade_state.get('state') == 'running' or upgrade_state.get('needs_recovery')):
        blocked = upgrade_state.get('message') or 'an upgrade is running or needs recovery'
    if not inst.get('is_git'):
        blocked = blocked or ('this install is not a git checkout (Docker installs upgrade by '
                              'pulling a new image)')

    rows = []
    for e in state.get('releases') or []:
        rows.append({
            'type': e['type'], 'kind': e['kind'], 'ref': e['tag'], 'tag': e['tag'],
            'version': e['version'], 'sha': e.get('sha') or '', 'name': e.get('name') or e['tag'],
            'date': e.get('published_at'), 'date_kind': 'Released',
            'url': e.get('url') or '', 'notes': e.get('notes') or '',
            'notes_truncated': e.get('notes_truncated'), 'assets': e.get('assets') or [],
            'signature': e.get('signature') or discovery.SIG_UNKNOWN,
            'signature_detail': e.get('signature_detail') or '',
            'is_latest': bool(e.get('is_latest')), 'security': bool(e.get('security')),
            'commits': [],
        })
    preview = state.get('preview')
    if preview and preview.get('sha'):
        rows.append({
            'type': 'development', 'kind': 'preview', 'ref': 'main', 'tag': '',
            'version': preview.get('version') or '', 'sha': preview['sha'],
            'name': preview.get('message') or 'main', 'date': preview.get('date'),
            'date_kind': 'Committed', 'url': '', 'notes': '', 'assets': [],
            'signature': 'none', 'signature_detail': 'not a release: unsigned, pinned to this exact commit',
            'is_latest': True, 'security': False,
            'commits': preview.get('commits') or [], 'ahead_of_stable': preview.get('ahead_of_stable'),
            'since_tag': preview.get('since_tag') or (state.get('stable') or {}).get('tag'),
        })

    owner, name = discovery.repo()
    for r in rows:
        r['type_label'] = TYPE_LABELS[r['type']]
        r['relation'] = _relation(r['version'], r['sha'], inst, development=r['type'] == 'development')
        r['in_channel'] = r['type'] in in_channel_types
        r['recommended'] = bool(target) and (target.get('kind'), target.get('ref'), target.get('sha')) \
            == (r['kind'], r['ref'], r['sha'])
        r['commit_url'] = f'https://github.com/{owner}/{name}/commit/{r["sha"]}' if r['sha'] else ''
        labels = []
        if r['relation'] == 'installed':
            labels.append('Installed')
        if r['is_latest']:
            labels.append({'stable': 'Latest Stable', 'prerelease': 'Latest Prerelease',
                           'development': 'Latest Development'}[r['type']])
        if r['recommended']:
            labels.append('Recommended')
        r['labels'] = labels
        r['compat'] = None
        installable, reason = True, ''
        if r['relation'] == 'installed':
            installable, reason = False, 'installed'
        elif blocked:
            installable, reason = False, blocked
        elif not r['sha']:
            installable, reason = False, (r['signature_detail'] or "the commit this version points at "
                                          "is unknown")
        elif r['type'] != 'development' and r['signature'] not in INSTALLABLE_SIGNATURES:
            installable, reason = False, r['signature_detail'] or 'its tag is not signed by a trusted release key'
        elif r['relation'] == 'older':
            if check_compat:
                state_, detail, _ = downgrade_compatibility(r['sha'])
            else:
                state_, detail = 'unchecked', 'compatibility is checked when you review it'
            r['compat'] = {'state': state_, 'detail': detail}
            if state_ == 'unsafe':
                installable, reason = False, detail
        r['installable'] = installable
        r['reason'] = reason
        r['reason_short'] = _short_reason(r, reason)
        if r['relation'] == 'installed':
            r['status'], r['status_tone'] = 'Installed', 'success'
        elif not installable:
            r['status'], r['status_tone'] = ('Incompatible' if (r['compat'] or {}).get('state') == 'unsafe'
                                             else 'Unavailable'), 'danger'
        elif r['relation'] == 'older':
            r['status'], r['status_tone'] = 'Older version', 'muted'
        elif r['recommended']:
            r['status'], r['status_tone'] = 'Recommended update', 'primary'
        elif r['relation'] in ('newer', 'same_version'):
            r['status'], r['status_tone'] = ('Newer' if r['relation'] == 'newer' else 'Other build'), 'info'
        else:
            r['status'], r['status_tone'] = 'Available', 'muted'
        r['action'] = ('install' if r['relation'] in ('newer', 'same_version', 'unknown')
                       else 'install_older' if r['relation'] == 'older' else '')
    return discovery.sort_newest_first(rows)


def _short_reason(row, reason):
    """A few words for the table; the full reason is under Details."""
    if not reason or reason == 'installed':
        return ''
    if (row.get('compat') or {}).get('state') == 'unsafe':
        detail = row['compat']['detail']
        if 'migration(s)' in detail:
            n = detail.split('the database has ', 1)[-1].split(' ', 1)[0]
            return f'needs {n} reverse migration(s)'
        return 'cannot install a pinned revision'
    sig = row.get('signature')
    if sig == discovery.SIG_INVALID:
        return 'tag not signed by a trusted key'
    if sig == discovery.SIG_UNSIGNED:
        return 'unsigned (lightweight) tag'
    if sig == discovery.SIG_UNKNOWN or not row.get('sha'):
        return 'commit unknown'
    return reason if len(reason) <= 60 else reason[:57] + '...'


def find(rows, kind, ref, sha):
    for r in rows:
        if (r['kind'], r['ref'], r['sha']) == (kind, ref, sha):
            return r
    return None


def installed_summary(state, rows):
    """What the instance runs, in words that never call a development build
    a release or an older release an update."""
    inst = state.get('installed') or {}
    stable = state.get('stable') or {}
    row = next((r for r in rows if r['relation'] == 'installed'), None)
    iv, sv = parse_version(inst.get('version')), parse_version(stable.get('version'))
    ahead = bool(iv and sv and iv > sv)
    if row:
        kind = row['type']
    elif ahead:
        kind = 'development'
    elif stable and inst.get('version') == stable.get('version'):
        kind = 'stable'
    else:
        kind = 'unknown'
    return {
        'type': kind,
        'type_label': {'stable': 'Stable release', 'prerelease': 'Prerelease',
                       'development': 'Development build'}.get(kind, 'Unrecognised build'),
        'matches_row': bool(row),
        'ahead_of_stable': ahead,
        'behind_stable': bool(iv and sv and iv < sv),
    }


# ---------------------------------------------------------------------------
# rollback: restore points
# ---------------------------------------------------------------------------

def restore_points(backups_summary=None):
    """Pre-upgrade snapshots, each with whether it is a genuine way back.

    Rollback is not "install an older version": it puts back the database,
    uploaded files and code exactly as they were when the snapshot was taken
    (core.upgrade.snapshot.restore, `manage.py upgrade_restore`), so no
    migration ever runs backwards; everything changed since is lost.

    Offered only when the snapshot verified (quick check here; the restore
    verifies fully again), recorded its code revision and that commit is in
    this checkout, was taken from the same database engine, and retention
    keeps it through the next upgrade's cleanup (so it is not removed while
    it is offered). A snapshot whose APP_MASTER_KEY differs from this
    instance's needs its keys restored too, and says so."""
    from pathlib import Path
    from . import retention, snapshot
    from .revision import commit_available
    try:
        summary = backups_summary or retention.summary()
        rows = summary['backups']
        survivors = {r['path'] for r, _ in retention.plan(reserve=1, rows=rows, full_check=False)['keep']}
    except Exception:
        logger.exception('could not list restore points')
        return []
    engine = snapshot.db_engine()
    try:
        current_key = snapshot.key_fingerprint('APP_MASTER_KEY', snapshot._setting_or_env('APP_MASTER_KEY'))
    except Exception:
        current_key = None
    out = []
    for b in rows:
        point = {'name': b['name'], 'path': b['path'], 'version': b.get('app_version') or '',
                 'sha': b.get('git_sha') or '', 'created_dt': b.get('created_dt'),
                 'size_human': b.get('size_human') or '', 'reason_taken': b.get('reason') or '',
                 'eligible': False, 'why_not': '', 'needs_keys': False}
        try:
            manifest = snapshot.load_manifest(b['path'])
        except Exception:
            manifest = {}
        if not b.get('verified'):
            point['why_not'] = 'not verified' if not b.get('in_progress') else 'still being written'
        elif not point['sha']:
            point['why_not'] = 'it did not record a code revision'
        elif not commit_available(point['sha']):
            point['why_not'] = f"its code revision {point['sha'][:12]} is not in this checkout"
        elif (manifest.get('db') or {}).get('engine') not in (None, engine):
            point['why_not'] = f"taken from a {(manifest.get('db') or {}).get('engine')} database, this one is {engine}"
        elif b['path'] not in survivors:
            point['why_not'] = 'retention removes it at the next upgrade'
        else:
            point['eligible'] = True
            try:
                stored = snapshot.parse_env_file(Path(b['path']) / 'keys.env')
                point['needs_keys'] = current_key is not None and snapshot.key_fingerprint(
                    'APP_MASTER_KEY', stored.get('APP_MASTER_KEY', '')) != current_key
            except Exception:
                point['needs_keys'] = False
            point['command'] = ('venv/bin/python manage.py upgrade_restore ' + b['path']
                                + (' --restore-keys' if point['needs_keys'] else ''))
        out.append(point)
    return out
