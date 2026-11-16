"""Release channels: which version is *recommended*, and what the nightly
timer and "Update now" install. A channel never hides anything: every
published release and the head of main are discovered and listed whatever
the channel (core.upgrade.discovery), and an admin can install any eligible
one by hand after verification and confirmation. Visibility, recommendation
and eligibility are kept separate:

    visibility    discovery: every published release (official, or a GitHub
                  pre-release, which is a testing build) and main
    recommended   the channel policy below (badge, "update available",
                  "Update now", `upgrade_apply --auto`)
    eligible      core.upgrade.catalog: signature, compatibility, recovery
                  state; checked again by Apply on the server

    Official release ('stable')
                the newest *published* GitHub release (not a draft, not a
                pre-release) whose tag is a version tag. Apply installs it
                only after verifying the tag's SSH signature locally
                (core.upgrade.revision). Version tags exist for every build;
                only the ones published as releases are recommended.
    Preview / testing ('preview')
                the head of `main`: commits that are not part of any release.
                Opt-in (Settings -> Updates -> channel). Unsigned; pinned to
                the exact commit shown on the page. Published GitHub
                pre-releases are testing builds too: listed with it, never
                called official, installable only with a signed tag.

A stored 'prerelease' setting (v3.17.697-700 had a separate Prerelease
channel) is read as Preview / testing (current_channel; migration core 0112).

A channel only ever recommends something newer than what is installed: an
install that is ahead of its channel (a development build on Stable) is
never offered a downgrade as an update.

There is no LTS channel: no release line currently has a support window or
a backport policy (see docs/UPGRADE_AND_RECOVERY.md, "Release channels").

Network failures never raise: the result carries `error` and, when there is
one, the last good answer marked `stale`.

Where the answer is kept (v3.17.667): one small JSON file,
<UPGRADE_BACKUP_DIR>/channel_state.json, written atomically (temp file +
rename). It used to live in Django's default cache, which on most installs
is LocMemCache: one copy per gunicorn worker, so a page served by one worker
could offer a release that the worker handling Apply had never heard of,
and "Check for updates now" refreshed only the worker that served it. The
file is shared by every process on the host (workers, the scheduler,
manage.py) and needs nothing an install might lack: the backup directory
already holds the upgrade journal for the same reason. Redis is optional,
and a database row would add a write to the shared database on every check.
If the directory cannot be written the answer is simply not kept, and every
process asks GitHub itself: slower, never inconsistent.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time

import requests
from django.conf import settings
from django.utils import timezone
from packaging import version as pversion

from . import discovery
from .discovery import GitHubError, repo, _headers   # noqa: F401 (re-exported)
from .revision import TAG_RE, SHA_RE

STATE_FILE = 'channel_state.json'
STATE_FORMAT = 1
CACHE_TTL = 600          # a good answer is reused for this long
CACHE_TTL_ERROR = 120    # a failed check is not retried for this long
LAST_GOOD_TTL = 24 * 3600
CHANNELS = ('stable', 'preview')
# The release types that belong to each channel (never what it shows). What a
# channel *recommends* is narrower: _candidates (Preview recommends main only).
CHANNEL_TYPES = {
    'stable': ('stable',),
    'preview': ('development', 'prerelease'),
}
CHANNEL_LABELS = {'stable': 'Official release', 'preview': 'Preview / testing'}
# Settings saved before the two-channel layout.
LEGACY_CHANNELS = {'prerelease': 'preview'}
API = 'https://api.github.com/repos'
RAW = 'https://raw.githubusercontent.com'
MAX_COMMITS_SHOWN = 15


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
    ch = LEGACY_CHANNELS.get(ch, ch)
    return ch if ch in CHANNELS else 'stable'


_SECURITY_HEADING_RE = re.compile(r'^\s{0,3}#{2,4}\s*security\b', re.IGNORECASE | re.MULTILINE)


def is_security_release(rel) -> bool:
    """A published release that carries security fixes: its notes (the
    CHANGELOG section) have a "### Security" heading, or its title says so."""
    if not isinstance(rel, dict):
        return False
    if _SECURITY_HEADING_RE.search(rel.get('body') or ''):
        return True
    return 'security' in (rel.get('name') or '').lower()


def _stable_release(owner, name):
    releases = _get(f'{API}/{owner}/{name}/releases?per_page=30') or []
    best = None
    security = None   # newest published release carrying security fixes
    for rel in releases:
        if rel.get('draft') or rel.get('prerelease'):
            continue
        tag = rel.get('tag_name') or ''
        if not TAG_RE.match(tag):
            continue
        v = _parse(tag)
        if v and (best is None or v > best[0]):
            best = (v, rel)
        if v and is_security_release(rel) and (security is None or v > security[0]):
            security = (v, tag.lstrip('v'))
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
        # The newest release (of the last 30) with security fixes; the navbar
        # badge turns red while the running version is older than it.
        'security_version': security[1] if security else '',
    }


def _fetch_remote_state():
    """Discovery (every release, by type, and main) plus the legacy keys:
    `stable` (the newest stable release, as before) and `prerelease`."""
    found = discovery.discover()
    releases = found['releases']

    def newest(kind):
        best = None
        for e in releases:
            if e['type'] != kind:
                continue
            v = _parse(e['version'])
            if v is not None and (best is None or v > best[0]):
                best = (v, e)
        return best[1] if best else None

    def legacy(e, security=None):
        if not e:
            return None
        return {'tag': e['tag'], 'version': e['version'], 'sha': e.get('sha') or '',
                'name': e.get('name') or e['tag'], 'published_at': e.get('published_at'),
                'url': e.get('url'), 'notes': e.get('notes') or '',
                'has_signature': e.get('github_signature'),
                'signature': e.get('signature'),
                'security_version': security or ''}

    sec = None
    for e in releases:
        if e['type'] == 'stable' and e.get('security'):
            v = _parse(e['version'])
            if v is not None and (sec is None or v > sec[0]):
                sec = (v, e['version'])
    return {'stable': legacy(newest('stable'), sec[1] if sec else ''),
            'prerelease': legacy(newest('prerelease')),
            'preview': found['preview'],
            'releases': releases,
            'discovery': found['meta']}


def _candidates(remote, channel):
    """Targets the channel may *recommend*, as (version, target) pairs."""
    out = []
    if channel == 'preview':
        preview = remote.get('preview')
        if preview and preview.get('sha'):
            out.append((_parse(preview.get('version')) if preview.get('version') else None,
                        {'kind': 'preview', 'ref': 'main', 'sha': preview['sha'],
                         'version': preview.get('version') or ''}))
        return out
    releases = remote.get('releases')
    if releases is None:     # an answer stored before discovery (v3.17.694 and older)
        stable = remote.get('stable')
        releases = [{'type': 'stable', 'kind': 'release', 'tag': stable['tag'],
                     'version': stable['version'], 'sha': stable.get('sha'),
                     'signature': discovery.SIG_PENDING}] if stable else []
    allowed = CHANNEL_TYPES.get(channel, ('stable',))
    for e in releases:
        if e.get('type') not in allowed or not e.get('sha'):
            continue
        if e.get('type') == 'prerelease' and e.get('signature') not in discovery.INSTALLABLE_SIGNATURES:
            continue   # an untrusted pre-release is shown, never recommended
        if e.get('type') == 'stable' and e.get('signature') in (discovery.SIG_INVALID,
                                                                 discovery.SIG_UNSIGNED):
            continue
        v = _parse(e.get('version'))
        if v is not None:
            out.append((v, {'kind': e['kind'], 'ref': e['tag'], 'sha': e['sha'],
                            'version': e['version']}))
    return out


def _decide(remote, inst, channel):
    """What the channel recommends (and Apply / --auto would install), given
    the installed build: only ever something newer. Never a downgrade."""
    iv = _parse(inst['version'])
    stable = remote.get('stable')
    target, relation = None, 'unknown'
    if stable and iv:
        sv = _parse(stable['version'])
        if sv:
            relation = 'behind' if iv < sv else ('current' if iv == sv else 'ahead')
    if channel == 'preview':
        for pv, t in _candidates(remote, channel):
            newer_or_same = (pv is None or iv is None or pv >= iv)
            if t['sha'] != inst.get('sha') and newer_or_same:
                target = t
        return target, relation
    if not iv:
        return None, relation
    best = None
    for v, t in _candidates(remote, channel):
        if v > iv and (best is None or v > best[0]):
            best = (v, t)
    return (best[1] if best else None), relation


def state_path():
    from .journal import backup_root
    return backup_root() / STATE_FILE


def _read_state() -> dict:
    try:
        with open(state_path(), encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get('format') != STATE_FORMAT:
        return {}
    return data


def _write_state(data: dict) -> None:
    """Atomic replace, so a reader never sees half a file. Best effort."""
    from .journal import ensure_private_dir
    tmp = None
    try:
        directory = ensure_private_dir(state_path().parent)
        fd, tmp = tempfile.mkstemp(dir=str(directory), prefix='.channel_state.', suffix='.tmp')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump({**data, 'format': STATE_FORMAT}, f, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, state_path())
        tmp = None
    except OSError:
        pass
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _fresh(stamp, ttl, now):
    try:
        return 0 <= now - float(stamp) < ttl
    except (TypeError, ValueError):
        return False


def resolve(*, force_refresh=False):
    """Channel state for Settings -> Updates, the badge and `upgrade_apply`.

    force_refresh asks GitHub now (Apply, "Check for updates now"); the answer
    is then what every other process sees too."""
    inst = installed()
    channel = current_channel()
    now = time.time()
    state = _read_state()
    remote, error, stale, from_cache = None, None, False, False
    fetched = False
    if not force_refresh:
        if state.get('remote') and _fresh(state.get('fetched_at'), CACHE_TTL, now) \
                and not _fresh(state.get('error_at'), CACHE_TTL_ERROR, now):
            remote, from_cache = state['remote'], True
        elif state.get('error') and _fresh(state.get('error_at'), CACHE_TTL_ERROR, now):
            # A check failed moments ago: do not hammer GitHub on every page.
            error, from_cache = state['error'], True
    if remote is None and error is None:
        try:
            remote = _fetch_remote_state()
            remote['checked_at'] = timezone.now().isoformat()
            _write_state({'remote': remote, 'fetched_at': now,
                          'last_good': remote, 'last_good_at': now})
            fetched = True
        except GitHubError as e:
            error = str(e)
            _write_state({'error': error, 'error_at': now,
                          'last_good': state.get('last_good'),
                          'last_good_at': state.get('last_good_at')})
    if remote is None:
        if state.get('last_good') and _fresh(state.get('last_good_at'), LAST_GOOD_TTL, now):
            remote, stale = state['last_good'], True
        else:
            remote = {'stable': None, 'preview': None, 'checked_at': timezone.now().isoformat()}
    target, relation = _decide(remote, inst, channel)
    if fetched:
        _record_stable(remote.get('stable'), recommended=target, channel=channel)
    return {
        'installed': inst,
        'channel': channel,
        'stable': remote.get('stable'),
        'prerelease': remote.get('prerelease'),
        'preview': remote.get('preview'),
        # Every discovered release (None: never discovered, i.e. GitHub was
        # not reached and there is no earlier answer to show).
        'releases': remote.get('releases'),
        'discovery': remote.get('discovery'),
        'target': target,
        'update_available': target is not None,
        'relation_to_stable': relation,
        'checked_at': remote.get('checked_at'),
        'error': error,
        'stale': stale,
        'from_cache': from_cache,
    }


def _record_stable(stable, *, recommended=None, channel='stable'):
    """Persist what the channel recommends for the navbar badge (every
    process). The badge follows the channel: on Stable the newest stable
    release, on Prerelease / Preview the channel's own recommendation. Only
    something newer than what is installed is ever recorded as "available"
    (the badge compares versions), so an install ahead of Stable shows none.
    The security marker always comes from the published stable releases."""
    if recommended is not None or channel != 'stable':
        version = (recommended or {}).get('version') or ''
    else:
        version = (stable or {}).get('version') or ''
    try:
        from core.models import SystemSetting
        SystemSetting.get_settings()
        SystemSetting.objects.filter(pk=1).update(
            latest_release_version=str(version)[:32],
            latest_security_release_version=str((stable or {}).get('security_version') or '')[:32],
            latest_release_checked_at=timezone.now())
    except Exception:
        pass


def clear_cache(*, last_good=False):
    """Forget the current answer (for every process), so the next resolve()
    asks GitHub. last_good=True also forgets the fallback copy."""
    state = _read_state()
    if not state:
        return
    if last_good:
        try:
            os.unlink(state_path())
        except OSError:
            pass
        return
    _write_state({'last_good': state.get('last_good'), 'last_good_at': state.get('last_good_at')})
