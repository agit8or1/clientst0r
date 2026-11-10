"""Fetch the exact revision an admin reviewed, and prove it is that one.

A target is (kind, ref, sha):

    release  ref is a release tag (vX.Y.Z); the tag must carry a valid SSH
             signature from a key in the trusted allowed_signers file, the
             signed tag object must be named after the ref, and the commit
             it points at must be the reviewed sha.
    preview  ref is `main`; there is no signature (main commits are not
             signed releases), so what is pinned is the sha: origin's main
             must still point at the reviewed sha, and the fetched commit
             must be it.

The trusted signers file is, in order: settings.RELEASE_SIGNERS_FILE;
/etc/clientst0r/allowed_signers (root-owned, installed by the root helper);
deploy/root-helper/allowed_signers as committed in the revision that is
installed now (read from git, not the working tree). It is never taken from
the revision being installed, so a revision cannot vouch for itself.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from django.conf import settings

TAG_RE = re.compile(r'^v(\d{1,4})\.(\d{1,4})\.(\d{1,6})$')
SHA_RE = re.compile(r'^[0-9a-f]{40}$')
SYSTEM_SIGNERS = '/etc/clientst0r/allowed_signers'
REPO_SIGNERS = 'deploy/root-helper/allowed_signers'
PREVIEW_REF = 'main'


class RevisionError(Exception):
    pass


@dataclass
class Target:
    kind: str          # 'release' | 'preview'
    ref: str           # 'v3.17.660' | 'main'
    sha: str           # full commit sha that was reviewed
    version: str = ''

    def validate(self):
        if self.kind not in ('release', 'preview'):
            raise RevisionError(f'unknown target kind {self.kind!r}')
        if not SHA_RE.match(self.sha or ''):
            raise RevisionError('the target must be a full 40-character commit sha')
        if self.kind == 'release' and not TAG_RE.match(self.ref or ''):
            raise RevisionError(f'not a release tag: {self.ref!r}')
        if self.kind == 'preview' and self.ref != PREVIEW_REF:
            raise RevisionError(f'preview targets track {PREVIEW_REF!r}, not {self.ref!r}')
        return self

    def as_dict(self):
        return asdict(self)


def _git_bin():
    return shutil.which('git') or '/usr/bin/git'


def git(*args, timeout=120, check=False, base_dir=None):
    r = subprocess.run([_git_bin(), '-C', str(base_dir or settings.BASE_DIR), *args],
                       capture_output=True, text=True, timeout=timeout,
                       env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
    if check and r.returncode != 0:
        raise RevisionError(f"git {' '.join(args[:2])} failed: {(r.stderr or r.stdout).strip()[:400]}")
    return r


def is_git_install():
    try:
        return git('rev-parse', '--is-inside-work-tree', timeout=10).stdout.strip() == 'true'
    except (OSError, subprocess.SubprocessError):
        return False


def head_sha():
    r = git('rev-parse', 'HEAD', timeout=10)
    return r.stdout.strip() if r.returncode == 0 else ''


def ls_remote(*refs):
    """{refname: sha} for the given refs on origin (no rate limit, no API)."""
    r = git('ls-remote', 'origin', *refs, timeout=60)
    if r.returncode != 0:
        raise RevisionError(f'cannot reach origin: {r.stderr.strip()[:300]}')
    out = {}
    for line in r.stdout.splitlines():
        if '\t' in line:
            sha, name = line.split('\t', 1)
            out[name.strip()] = sha.strip()
    return out


def remote_commit(target: Target) -> str:
    """The commit origin's ref points at right now."""
    if target.kind == 'release':
        refs = ls_remote(f'refs/tags/{target.ref}', f'refs/tags/{target.ref}^{{}}')
        return refs.get(f'refs/tags/{target.ref}^{{}}') or refs.get(f'refs/tags/{target.ref}', '')
    refs = ls_remote(f'refs/heads/{PREVIEW_REF}')
    return refs.get(f'refs/heads/{PREVIEW_REF}', '')


def check_remote_unchanged(target: Target):
    actual = remote_commit(target)
    if not actual:
        raise RevisionError(f'{target.ref} no longer exists on origin')
    if actual != target.sha:
        raise RevisionError(
            f'{target.ref} on origin now points at {actual[:12]}, not the reviewed '
            f'{target.sha[:12]}. Nothing was changed. Check for updates again and '
            're-review before applying.')


def fetch(target: Target):
    if target.kind == 'release':
        git('fetch', '--no-tags', '--force', 'origin',
            f'+refs/tags/{target.ref}:refs/tags/{target.ref}', timeout=600, check=True)
        fetched = git('rev-parse', f'refs/tags/{target.ref}^{{commit}}', check=True).stdout.strip()
    else:
        git('fetch', '--no-tags', 'origin',
            f'+refs/heads/{PREVIEW_REF}:refs/remotes/origin/{PREVIEW_REF}', timeout=600, check=True)
        fetched = git('rev-parse', f'refs/remotes/origin/{PREVIEW_REF}^{{commit}}', check=True).stdout.strip()
    if fetched != target.sha:
        raise RevisionError(f'fetched {target.ref} is {fetched[:12]}, not the reviewed {target.sha[:12]}')
    if git('cat-file', '-e', f'{target.sha}^{{commit}}').returncode != 0:
        raise RevisionError(f'commit {target.sha[:12]} is not available after fetching')


def signers_file():
    """Path to the trusted allowed_signers file (see module docstring), or None."""
    configured = getattr(settings, 'RELEASE_SIGNERS_FILE', '') or ''
    if configured:
        return configured if os.path.isfile(configured) else None
    if os.path.isfile(SYSTEM_SIGNERS):
        return SYSTEM_SIGNERS
    r = git('show', f'HEAD:{REPO_SIGNERS}', timeout=10)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    fd, path = tempfile.mkstemp(prefix='clientst0r-signers-')
    with os.fdopen(fd, 'w') as f:
        f.write(r.stdout)
    return path


def verify_release_tag(target: Target) -> str:
    """Raise unless the tag is signed by a trusted key, named after itself
    and points at the reviewed commit. Returns the verify-tag message."""
    signers = signers_file()
    if not signers:
        raise RevisionError('no trusted release signers file; cannot verify a release')
    try:
        r = git('-c', 'gpg.format=ssh', '-c', f'gpg.ssh.allowedSignersFile={signers}',
                'verify-tag', target.ref, timeout=60)
    finally:
        if signers.startswith(tempfile.gettempdir()) and 'clientst0r-signers-' in signers:
            os.unlink(signers)
    if r.returncode != 0:
        raise RevisionError(f'{target.ref} is not signed by a trusted release key; refusing to '
                            f'install it ({(r.stderr or "").strip().splitlines()[-1:] or ["no signature"]})')
    obj = git('cat-file', 'tag', target.ref, check=True).stdout
    if f'\ntag {target.ref}\n' not in '\n' + obj:
        raise RevisionError(f'the signed tag object behind {target.ref} is named differently')
    commit = git('rev-parse', f'{target.ref}^{{commit}}', check=True).stdout.strip()
    if commit != target.sha:
        raise RevisionError(f'{target.ref} points at {commit[:12]}, not the reviewed {target.sha[:12]}')
    return (r.stderr or '').strip().splitlines()[0] if r.stderr else 'signature ok'


def show_file(sha, path) -> str:
    r = git('show', f'{sha}:{path}', timeout=30)
    if r.returncode != 0:
        raise RevisionError(f'{path} not found at {sha[:12]}')
    return r.stdout


def version_at(sha) -> str:
    m = re.search(r"^VERSION\s*=\s*['\"]([^'\"]+)['\"]", show_file(sha, 'config/version.py'), re.M)
    return m.group(1) if m else ''


def new_migrations(from_sha, to_sha):
    """Migration files the target adds relative to the installed revision."""
    r = git('diff', '--name-only', '--diff-filter=A', f'{from_sha}', f'{to_sha}', '--',
            '*/migrations/0*.py', timeout=60)
    if r.returncode != 0:
        return None
    return [p for p in r.stdout.splitlines() if p.strip()]


def extract_to_private_file(sha, path) -> Path:
    """Write a file from the target revision to a fresh 0700 temp file."""
    content = show_file(sha, path)
    fd, tmp = tempfile.mkstemp(prefix='clientst0r-update-', suffix='.sh')
    with os.fdopen(fd, 'w') as f:
        f.write(content)
    os.chmod(tmp, 0o700)
    return Path(tmp)
