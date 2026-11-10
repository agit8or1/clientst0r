"""Release channels: what Stable and Preview point at, and what Apply would
install.

    Stable   the newest *published* GitHub release (not a draft, not a
             pre-release) whose tag is a version tag. Apply installs it only
             after verifying the tag's SSH signature locally
             (core.upgrade.revision). Version tags exist for every build;
             only the ones published as releases are recommended.
    Preview  the head of `main`: commits that are not part of any release.
             Opt-in (Settings -> Updates -> channel). Unsigned; pinned to the
             exact commit shown on the page.

There is no LTS channel: no release line currently has a support window or
a backport policy (see docs/UPGRADE_AND_RECOVERY.md, "Release channels").

Network failures never raise: the result carries `error` and, when there is
one, the last good answer marked `stale`.
"""
from __future__ import annotations

import os
import re
import subprocess

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from packaging import version as pversion

from .revision import TAG_RE, SHA_RE

CACHE_KEY = 'upgrade_channels_v1'
CACHE_KEY_LAST_GOOD = 'upgrade_channels_v1_last_good'
CACHE_TTL = 600
CACHE_TTL_ERROR = 120
CHANNELS = ('stable', 'preview')
API = 'https://api.github.com/repos'
RAW = 'https://raw.githubusercontent.com'
MAX_COMMITS_SHOWN = 15


def repo():
    return (getattr(settings, 'GITHUB_REPO_OWNER', 'agit8or1'),
            getattr(settings, 'GITHUB_REPO_NAME', 'clientst0r'))


def _headers():
    h = {'Accept': 'application/vnd.github+json'}
    token = os.getenv('GITHUB_TOKEN') or getattr(settings, 'GITHUB_TOKEN', None)
    if token:
        h['Authorization'] = f'Bearer {token}'
    return h


class GitHubError(Exception):
    pass


def _get(url, timeout=20, raw=False):
    try:
        r = requests.get(url, headers=None if raw else _headers(), timeout=timeout)
    except requests.Timeout:
        raise GitHubError('GitHub did not answer in time (timeout).')
    except requests.ConnectionError:
        raise GitHubError('Cannot connect to GitHub. Check internet access / firewall.')
    except requests.RequestException as e:
        raise GitHubError(f'GitHub request failed: {e}')
    if r.status_code == 403 and r.headers.get('X-RateLimit-Remaining') == '0':
        raise GitHubError('GitHub API rate limit reached. Try again later, or set GITHUB_TOKEN.')
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        raise GitHubError(f'GitHub answered HTTP {r.status_code} for {url.split("/repos/")[-1]}')
    return r.text if raw else r.json()


def _parse(v):
    try:
        return pversion.parse(str(v).lstrip('v'))
    except Exception:
        return None


def installed():
    from config.version import VERSION
    from .revision import is_git_install, git
    info = {'version': VERSION, 'sha': '', 'branch': '', 'clean': None, 'is_git': False}
    try:
        if is_git_install():
            info['is_git'] = True
            info['sha'] = git('rev-parse', 'HEAD', timeout=10).stdout.strip()
            info['branch'] = git('rev-parse', '--abbrev-ref', 'HEAD', timeout=10).stdout.strip()
            st = git('status', '--porcelain', '--untracked-files=no', timeout=20)
            info['clean'] = (st.returncode == 0 and not st.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return info


def current_channel():
    try:
        from core.models import SystemSetting
        ch = SystemSetting.get_settings().update_channel
    except Exception:
        ch = 'stable'
    return ch if ch in CHANNELS else 'stable'


def _stable_release(owner, name):
    releases = _get(f'{API}/{owner}/{name}/releases?per_page=30') or []
    best = None
    for rel in releases:
        if rel.get('draft') or rel.get('prerelease'):
            continue
        tag = rel.get('tag_name') or ''
        if not TAG_RE.match(tag):
            continue
        v = _parse(tag)
        if v and (best is None or v > best[0]):
            best = (v, rel)
    if not best:
        return None
    rel = best[1]
    tag = rel['tag_name']
    ref = _get(f'{API}/{owner}/{name}/git/ref/tags/{tag}')
    sha, signed = '', None
    if ref and ref.get('object'):
        obj = ref['object']
        if obj.get('type') == 'tag':
            tag_obj = _get(f'{API}/{owner}/{name}/git/tags/{obj["sha"]}') or {}
            sha = (tag_obj.get('object') or {}).get('sha', '')
            # GitHub's own view; Apply verifies locally against the trusted
            # signers file regardless of what this says.
            signed = bool((tag_obj.get('verification') or {}).get('signature'))
        else:
            sha = obj.get('sha', '')
            signed = False   # a lightweight tag cannot carry a signature
    return {
        'tag': tag, 'version': tag.lstrip('v'), 'sha': sha if SHA_RE.match(sha or '') else '',
        'name': rel.get('name') or tag, 'published_at': rel.get('published_at'),
        'url': rel.get('html_url'), 'notes': rel.get('body') or '',
        'has_signature': signed,
    }


def _main_head(owner, name):
    c = _get(f'{API}/{owner}/{name}/commits/main')
    if not c:
        return None
    sha = c.get('sha', '')
    version = ''
    try:
        text = _get(f'{RAW}/{owner}/{name}/{sha}/config/version.py', raw=True) or ''
        m = re.search(r"^VERSION\s*=\s*['\"]([^'\"]+)['\"]", text, re.M)
        version = m.group(1) if m else ''
    except GitHubError:
        pass
    commit = c.get('commit') or {}
    return {'sha': sha, 'version': version,
            'date': (commit.get('committer') or {}).get('date'),
            'message': (commit.get('message') or '').splitlines()[0][:200]}


def _compare(owner, name, base, head):
    data = _get(f'{API}/{owner}/{name}/compare/{base}...{head}')
    if not data:
        return None
    commits = data.get('commits') or []
    return {
        'ahead_by': data.get('ahead_by'),
        'behind_by': data.get('behind_by'),
        'commits': [{'sha': c.get('sha', ''),
                     'message': ((c.get('commit') or {}).get('message') or '').splitlines()[0][:160],
                     'date': ((c.get('commit') or {}).get('committer') or {}).get('date')}
                    for c in reversed(commits[-MAX_COMMITS_SHOWN:])],
    }


def _fetch_remote_state():
    owner, name = repo()
    stable = _stable_release(owner, name)
    preview = _main_head(owner, name)
    if preview and stable and stable.get('tag'):
        cmp = _compare(owner, name, stable['tag'], preview['sha'])
        if cmp:
            preview['ahead_of_stable'] = cmp['ahead_by']
            preview['commits'] = cmp['commits']
    return {'stable': stable, 'preview': preview}


def _decide(remote, inst, channel):
    """What Apply would install for this channel, given the installed build."""
    iv = _parse(inst['version'])
    stable, preview = remote.get('stable'), remote.get('preview')
    target, relation = None, 'unknown'
    if stable and iv:
        sv = _parse(stable['version'])
        if sv:
            relation = 'behind' if iv < sv else ('current' if iv == sv else 'ahead')
    if channel == 'stable' and stable and stable.get('sha') and iv:
        sv = _parse(stable['version'])
        if sv and sv > iv:
            target = {'kind': 'release', 'ref': stable['tag'], 'sha': stable['sha'],
                      'version': stable['version']}
    elif channel == 'preview' and preview and preview.get('sha'):
        pv = _parse(preview.get('version')) if preview.get('version') else None
        newer_or_same = (pv is None or iv is None or pv >= iv)
        if preview['sha'] != inst.get('sha') and newer_or_same:
            target = {'kind': 'preview', 'ref': 'main', 'sha': preview['sha'],
                      'version': preview.get('version') or ''}
    return target, relation


def resolve(*, force_refresh=False):
    """Channel state for Settings -> Updates, the badge and `upgrade_apply`."""
    inst = installed()
    channel = current_channel()
    remote, error, stale, from_cache = None, None, False, False
    if not force_refresh:
        remote = cache.get(CACHE_KEY)
        from_cache = remote is not None
    if remote is None:
        try:
            remote = _fetch_remote_state()
            remote['checked_at'] = timezone.now().isoformat()
            cache.set(CACHE_KEY, remote, CACHE_TTL)
            cache.set(CACHE_KEY_LAST_GOOD, remote, 24 * 3600)
            _record_stable(remote.get('stable'))
        except GitHubError as e:
            error = str(e)
            remote = cache.get(CACHE_KEY_LAST_GOOD)
            stale = remote is not None
            if remote is None:
                remote = {'stable': None, 'preview': None, 'checked_at': timezone.now().isoformat()}
            cache.set(CACHE_KEY, {**remote, '_error': error}, CACHE_TTL_ERROR)
    error = error or remote.get('_error')
    target, relation = _decide(remote, inst, channel)
    return {
        'installed': inst,
        'channel': channel,
        'stable': remote.get('stable'),
        'preview': remote.get('preview'),
        'target': target,
        'update_available': target is not None,
        'relation_to_stable': relation,
        'checked_at': remote.get('checked_at'),
        'error': error,
        'stale': stale,
        'from_cache': from_cache,
    }


def _record_stable(stable):
    """Persist the recommended release for the navbar badge (every process)."""
    try:
        from core.models import SystemSetting
        SystemSetting.get_settings()
        SystemSetting.objects.filter(pk=1).update(
            latest_release_version=str((stable or {}).get('version') or '')[:32],
            latest_release_checked_at=timezone.now())
    except Exception:
        pass


def clear_cache():
    cache.delete(CACHE_KEY)
