"""The upgrade pipeline behind Settings -> Updates -> Apply and
`manage.py upgrade_apply`.

    1. the reviewed target (kind, ref, full sha) is checked against origin:
       if the ref moved since the admin looked, nothing happens
    2. fetch it; prove the fetched commit is the reviewed sha; for a release,
       verify the tag's SSH signature against the trusted signers file
    3. preflight checks (core.upgrade.preflight); any failure stops here
    4. take a pre-upgrade snapshot (database + uploads + keys) and verify it
       by restoring it into a scratch database; no verified backup, no upgrade
    5. run deploy/update_instructions.sh *as it exists in the reviewed
       revision* (extracted with `git show <sha>:...`, not the copy installed
       now, and not whatever `main` holds when the script is downloaded),
       pinned to the sha through CLIENTST0R_TARGET_SHA

Every stage is written to the journal (core.upgrade.journal) so an
interrupted upgrade is noticed and can be resumed (`--resume`) or rolled
back with `manage.py upgrade_restore`.
"""
from __future__ import annotations

import fcntl
import logging
import os
import subprocess
import sys
from contextlib import contextmanager

from django.conf import settings

from . import journal, preflight, snapshot
from .revision import RevisionError, Target, check_remote_unchanged, extract_to_private_file, \
    fetch, head_sha, is_git_install, verify_release_tag, version_at

logger = logging.getLogger('core')

PRE_STEPS = ('Verify Revision', 'Preflight Checks', 'Verified Backup')
SCRIPT_STEPS = ('Git Pull', 'Install Dependencies', 'Run Migrations', 'Collect Static Files',
                'Restart Service')
TOTAL_STEPS = len(PRE_STEPS) + len(SCRIPT_STEPS)

# Markers the update script prints -> progress steps the UI shows.
STEP_TRIGGERS = [
    ('Step 1/5: Fetching', 'start', 'Git Pull'),
    ('Step 1/5: Code updated', 'complete', 'Git Pull'),
    ('Step 2/5: Installing', 'start', 'Install Dependencies'),
    ('Step 2/5: Core dependencies', 'complete', 'Install Dependencies'),
    ('Step 3/5: Running database', 'start', 'Run Migrations'),
    ('Step 3/5: Migrations completed', 'complete', 'Run Migrations'),
    ('Step 4/5: Collecting static', 'start', 'Collect Static Files'),
    ('Step 4/5: Static files collected', 'complete', 'Collect Static Files'),
    ('Step 5/5: Scheduling', 'start', 'Restart Service'),
    ('Step 5/5: Marked progress', 'complete', 'Restart Service'),
    ('Step 5/5: Graceful reload', 'complete', 'Restart Service'),
    ('Update complete!', 'complete', 'Restart Service'),
]


class ApplyRefused(Exception):
    """Stopped before anything on disk changed."""


class ApplyFailed(Exception):
    """Stopped after code (and maybe the database) changed; see the journal."""


@contextmanager
def _exclusive():
    root = journal.ensure_private_dir(journal.backup_root())
    fd = os.open(str(root / 'apply.lock'), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ApplyRefused('Another upgrade is running.')
        yield
    finally:
        os.close(fd)


def _service_name():
    try:
        from core.updater import UpdateService
        return UpdateService()._detect_gunicorn_service_name() or ''
    except Exception:
        return ''


class _Reporter:
    def __init__(self, emit, progress):
        self.emit, self.progress, self.lines = emit, progress, []

    def __call__(self, line, level='info'):
        self.lines.append(line)
        logger.info('upgrade: %s', line)
        if self.emit:
            self.emit(line)
        if self.progress:
            self.progress.process_log_line(line, STEP_TRIGGERS)

    def start(self, step):
        if self.progress:
            self.progress.step_start(step)

    def done(self, step):
        if self.progress:
            self.progress.step_complete(step)


def run(target: Target | None, *, user=None, progress=None, emit=None, resume=False,
        deps_check=True, allow_preview=False, env_extra=None) -> dict:
    """Run the pipeline. Returns {success, refused, error, output, backup}.
    Never raises for an ordinary failure: the result and the journal say
    what happened."""
    say = _Reporter(emit, progress)
    result = {'success': False, 'refused': False, 'error': None, 'output': say.lines,
              'backup': None, 'target': target.as_dict() if target else None}
    try:
        with _exclusive():
            _run(target, say, result, user=user, resume=resume, deps_check=deps_check,
                 allow_preview=allow_preview, env_extra=env_extra or {})
    except ApplyRefused as e:
        result.update(refused=True, error=str(e))
        say(f'REFUSED: {e}')
    except ApplyFailed as e:
        result['error'] = str(e)
        say(f'ERROR: {e}')
    except Exception as e:  # unexpected: record it, never leave the journal "running"
        logger.exception('upgrade pipeline crashed')
        result['error'] = f'{e.__class__.__name__}: {e}'
        say(f'ERROR: {result["error"]}')
        data = journal.read()
        if data and data.get('status') == 'running':
            idx = journal.stage_index(data)
            journal.finish('failed' if idx >= journal.CODE_TOUCHED_FROM else 'aborted',
                           error=result['error'])
    if progress:
        progress.finish(success=result['success'], error=result['error'])
    _audit(user, result)
    return result


def _run(target, say, result, *, user, resume, deps_check, allow_preview, env_extra):
    if not is_git_install():
        raise ApplyRefused('This install is not a git checkout (Docker?). Upgrade a Docker install '
                           'by pulling the new image; see docs/UPGRADE_AND_RECOVERY.md.')
    assessment = journal.assess()
    prev = None
    if resume:
        prev = assessment.get('journal') or {}
        if assessment['state'] == 'running':
            raise ApplyRefused(assessment['message'])
        if not prev or not prev.get('target'):
            raise ApplyRefused('There is no unfinished upgrade to resume.')
        target = Target(**prev['target'])
        say(f"Resuming the upgrade to {target.ref} @ {target.sha[:12]} "
            f"(stopped at stage {prev.get('stage')}).")
    else:
        if assessment['state'] == 'running' or assessment['needs_recovery']:
            raise ApplyRefused(assessment['message'])
        if target is None:
            raise ApplyRefused('No target: nothing newer to install on this channel.')
    target.validate()
    result['target'] = target.as_dict()
    # Resuming finishes the revision someone already chose to install, even if
    # the channel setting has changed since.
    if target.kind == 'preview' and not allow_preview and not resume:
        from .channels import current_channel
        if current_channel() != 'preview':
            raise ApplyRefused('This instance follows the Stable channel. Switch to Preview in '
                               'Settings -> Updates to install unreleased commits from main.')

    from config.version import VERSION as installed_version
    installed_sha = (prev or {}).get('prev_sha') if resume else head_sha()
    installed_ver = (prev or {}).get('prev_version') if resume else installed_version
    if resume:
        journal.write({**prev, 'status': 'running', 'pid': os.getpid(), 'script_pid': None,
                       'resumed': (prev.get('resumed') or 0) + 1})
    else:
        journal.begin(target=target.as_dict(), prev_sha=installed_sha, prev_version=installed_ver,
                      user=getattr(user, 'username', None) or 'system')

    # 1-2: the reviewed revision, exactly
    say.start('Verify Revision')
    say(f'Target: {target.kind} {target.ref} @ {target.sha}')
    try:
        from .revision import git
        have_it = git('cat-file', '-e', f'{target.sha}^{{commit}}').returncode == 0
        if resume and have_it:
            # Resuming the same reviewed sha: origin may have moved on since,
            # which is fine -- what matters is the commit we already fetched.
            say(f'Resuming with the already-fetched commit {target.sha[:12]}')
        else:
            check_remote_unchanged(target)
            say(f'origin still has {target.ref} at {target.sha[:12]}')
            fetch(target)
            say(f'Fetched {target.sha[:12]}; the commit matches the reviewed revision')
        if target.kind == 'release':
            msg = verify_release_tag(target)
            say(f'Release tag signature verified: {msg}')
        else:
            say('Preview build: unsigned commit on main, pinned by sha (not a release)')
        target_version = version_at(target.sha)
    except RevisionError as e:
        journal.finish('aborted', error=str(e))
        raise ApplyRefused(str(e))
    from packaging import version as pv
    try:
        if pv.parse(target_version) < pv.parse(installed_ver or '0'):
            journal.finish('aborted', error='downgrade')
            raise ApplyRefused(f'{target.ref} is v{target_version}, older than the installed '
                               f'v{installed_ver}. Downgrades are not supported (migrations only go '
                               'forward); restore a backup instead.')
    except pv.InvalidVersion:
        pass
    journal.stage('revision_verified', target_version=target_version)
    say.done('Verify Revision')

    # 3: preflight
    say.start('Preflight Checks')
    checks = preflight.run(target, installed_sha=installed_sha, deps=deps_check)
    if resume:   # the unfinished journal is the point of resuming
        checks = [c for c in checks if c.name != 'previous upgrade']
    for c in checks:
        say(f'  [{c.status.upper():4}] {c.name}: {c.detail}' + (f' -- {c.hint}' if c.hint and c.status != 'ok' else ''))
    bad = preflight.failed(checks)
    if bad:
        journal.finish('aborted', error='preflight failed: ' + ', '.join(c.name for c in bad),
                       preflight=[c.as_dict() for c in checks])
        raise ApplyRefused('Preflight checks failed: ' + '; '.join(f'{c.name}: {c.detail}' for c in bad))
    journal.stage('preflight_ok', preflight=[c.as_dict() for c in checks])
    say.done('Preflight Checks')

    # 4: verified backup
    say.start('Verified Backup')
    backup = (prev or {}).get('backup') if resume else None
    if backup:
        ok, detail = snapshot.is_verified(backup)
        if not ok:
            raise ApplyFailed(f'The pre-upgrade backup {backup} is no longer intact ({detail}); '
                              'not resuming. See docs/UPGRADE_AND_RECOVERY.md.')
        say(f'Reusing the pre-upgrade backup {backup} ({detail})')
    else:
        try:
            snap = snapshot.create(reason=f'before upgrade to {target.ref}', target=target.as_dict(),
                                   out=say)
            report = snapshot.verify(snap, out=say)
        except Exception as e:
            journal.finish('aborted', error=f'backup failed: {e}')
            raise ApplyRefused(f'Could not take a verified backup, so nothing was changed: {e}')
        if not report['ok']:
            journal.finish('aborted', error='backup verification failed', backup=str(snap))
            raise ApplyRefused(f'The backup {snap} did not verify, so nothing was changed: ' +
                               '; '.join(c['name'] + ': ' + c['detail'] for c in report['checks'] if not c['ok']))
        backup = str(snap)
        journal.stage('backup_verified', backup=backup, backup_level=report['level'])
        say(f"Verified backup ({report['level']}): {backup}")
    result['backup'] = backup
    say.done('Verified Backup')

    # 5: the reviewed revision's own update script
    script = extract_to_private_file(target.sha, 'deploy/update_instructions.sh')
    try:
        if not script.read_text().startswith('#!'):
            raise ApplyFailed('the update script in the target revision is not a shell script')
        env = {**os.environ,
               'CLIENTST0R_BASE_DIR': str(settings.BASE_DIR),
               'CLIENTST0R_SERVICE_NAME': _service_name(),
               'CLIENTST0R_TARGET_SHA': target.sha,
               'CLIENTST0R_TARGET_REF': target.ref,
               'CLIENTST0R_TARGET_KIND': target.kind,
               'CLIENTST0R_PREV_SHA': installed_sha or '',
               'CLIENTST0R_VERIFIED_BACKUP': backup,
               'CLIENTST0R_JOURNAL': str(journal.journal_path()),
               'CLIENTST0R_PYTHON': sys.executable,
               **env_extra}
        proc = subprocess.Popen(['/bin/bash', str(script)], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1, env=env,
                                cwd=str(settings.BASE_DIR), start_new_session=True)
        data = journal.read() or {}
        journal.write({**data, 'script_pid': proc.pid})
        for line in iter(proc.stdout.readline, ''):
            if line.rstrip():
                say(line.rstrip())
        proc.wait()
    finally:
        try:
            script.unlink()
        except OSError:
            pass
    data = journal.read() or {}
    if proc.returncode != 0:
        status = data.get('status')
        if status == 'running':
            idx = journal.stage_index(data)
            status = 'failed' if idx >= journal.CODE_TOUCHED_FROM else 'aborted'
            journal.finish(status, error=f'update script exited with {proc.returncode}')
        if status in ('aborted', 'rolled_back'):
            raise ApplyFailed(f'The update stopped at "{data.get("stage")}" and was rolled back '
                              f'({status}); the database was not changed. See the log above.')
        raise ApplyFailed(f'The update failed at "{data.get("stage")}" (exit {proc.returncode}). '
                          f'Pre-upgrade backup: {backup}. Recovery: `manage.py upgrade_status`, '
                          'docs/UPGRADE_AND_RECOVERY.md.')
    if data.get('status') != 'complete':
        journal.stage('complete')
    result['success'] = True


def _audit(user, result):
    try:
        from audit.models import AuditLog
        tail = '\n'.join(result['output'][-200:])[-50_000:]
        AuditLog.objects.create(
            action='system_update' if result['success'] else 'system_update_failed',
            description=('System upgraded to ' if result['success'] else
                         ('Upgrade refused: ' if result['refused'] else 'Upgrade failed: '))
            + (f"{result['target']['ref']} @ {result['target']['sha'][:12]}"
               if result.get('target') else '') + ('' if result['success'] else f" ({result['error']})"),
            user=user, username=getattr(user, 'username', None) or 'system',
            success=result['success'],
            extra_data={'target': result.get('target'), 'backup': result.get('backup'),
                        'error': result.get('error'), 'output_tail': tail},
        )
    except Exception:
        logger.exception('could not write the upgrade audit entry')
