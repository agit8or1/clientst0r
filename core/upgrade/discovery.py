"""Version discovery: every published release of this repository, by type,
and the head of `main`, kept apart.

    stable       a published GitHub release (not a draft) that GitHub does
                 not mark as a pre-release, whose tag is vX.Y.Z
    prerelease   a published release GitHub marks as a pre-release, or whose
                 tag carries a pre-release suffix (vX.Y.Z-rc.1, -beta2, ...).
                 Always a real published release, never a commit on main.
    development  the head of `main` (core.upgrade.channels calls it Preview):
                 unreleased, unsigned, pinned to the exact commit

Drafts are never listed; tags that are not release tags are counted and
left out. Nothing here is invented: a value GitHub (or origin) did not give
is left empty, and the page says it is unknown.

Where each fact comes from:

    releases           GET /repos/{o}/{n}/releases, every page (Link: next),
                       100 per page, with ETag / If-None-Match so an
                       unchanged list costs a 304
    tag -> commit      `git ls-remote origin refs/tags/*`: one call, no API
                       rate limit, the same source Apply checks against.
                       The GitHub API is the fallback for the newest stable
                       release and pre-release when origin cannot be asked.
    signatures         `git verify-tag` against the trusted signers file
                       (core.upgrade.revision) for tags already present
                       locally as the same tag object origin has; any other
                       signed-looking tag is verified when it is installed.
                       A lightweight tag cannot carry a signature.
    main               GET /commits/main (ETag), its config/version.py from
                       raw.githubusercontent.com, and compare/<stable>...main
                       for the commits since the latest stable release

A failure part way (one page of releases, say) fails the whole discovery:
an incomplete list is never presented as the list. channels.resolve() then
shows the error and, if there is one, the last complete answer marked stale.

The ETag cache is one private JSON file next to the channel state
(<UPGRADE_BACKUP_DIR>/github_http_cache.json), shared by every process.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone as dt_timezone

import requests
from django.conf import settings
from packaging import version as pversion

from .revision import RELEASE_TAG_RE, SHA_RE, TAG_RE

API = 'https://api.github.com/repos'
API_HOST = 'https://api.github.com/'
RAW = 'https://raw.githubusercontent.com'
PER_PAGE = 100
MAX_PAGES = 20               # 2000 releases; more than that is reported, not truncated silently
NOTES_MAX = 20000            # characters of release notes kept per release
HTTP_CACHE_FILE = 'github_http_cache.json'
HTTP_CACHE_FORMAT = 1
MAX_COMMITS_SHOWN = 15

# What a signature state means for installing (see describe_signature()).
SIG_VERIFIED = 'verified'      # verified here against the trusted signers file
SIG_PENDING = 'pending'        # signed-tag object; verified when installed
SIG_INVALID = 'invalid'        # verify-tag failed here: unsigned or untrusted key
SIG_UNSIGNED = 'unsigned'      # lightweight tag: cannot carry a signature
SIG_UNKNOWN = 'unknown'        # the tag's commit could not be resolved
INSTALLABLE_SIGNATURES = (SIG_VERIFIED, SIG_PENDING)


class GitHubError(Exception):
    """A GitHub call failed. Messages are written here (never raw exception
    text), so they are shown as they are; callers read ``public_message``."""

    def __init__(self, message='The GitHub request failed.'):
        super().__init__(message)
        self.public_message = str(message)[:500]


def repo():
    return (getattr(settings, 'GITHUB_REPO_OWNER', 'agit8or1'),
            getattr(settings, 'GITHUB_REPO_NAME', 'clientst0r'))


def _headers():
    h = {'Accept': 'application/vnd.github+json'}
    token = os.getenv('GITHUB_TOKEN') or getattr(settings, 'GITHUB_TOKEN', None)
    if token:
        h['Authorization'] = f'Bearer {token}'
    return h


def parse_version(v):
    try:
        return pversion.parse(str(v).lstrip('v'))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# HTTP with ETags
# ---------------------------------------------------------------------------

def _cache_path():
    from .journal import backup_root
    return backup_root() / HTTP_CACHE_FILE


def load_http_cache() -> dict:
    try:
        with open(_cache_path(), encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {'urls': {}, 'tags': {}, 'signatures': {}}
    if not isinstance(data, dict) or data.get('format') != HTTP_CACHE_FORMAT:
        return {'urls': {}, 'tags': {}, 'signatures': {}}
    for k in ('urls', 'tags', 'signatures'):
        if not isinstance(data.get(k), dict):
            data[k] = {}
    return data


def save_http_cache(cache: dict, used_urls=None) -> None:
    """Atomic, private, best effort. Only the URLs this run used are kept, so
    the file does not grow with every release page ever seen."""
    from .journal import ensure_private_dir
    data = dict(cache)
    if used_urls is not None:
        data['urls'] = {u: v for u, v in (cache.get('urls') or {}).items() if u in used_urls}
    data['format'] = HTTP_CACHE_FORMAT
    tmp = None
    try:
        directory = ensure_private_dir(_cache_path().parent)
        fd, tmp = tempfile.mkstemp(dir=str(directory), prefix='.github_http_cache.', suffix='.tmp')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, _cache_path())
        tmp = None
    except OSError:
        pass
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _rate_limit_message(r):
    reset = r.headers.get('X-RateLimit-Reset') if r.headers else None
    when = ''
    try:
        when = ' It resets at ' + datetime.fromtimestamp(int(reset), tz=dt_timezone.utc) \
            .strftime('%H:%M UTC') + '.'
    except (TypeError, ValueError):
        pass
    return ('GitHub API rate limit reached.' + when +
            ' Try again later, or set GITHUB_TOKEN for a higher limit.')


def _next_link(r):
    link = (r.headers or {}).get('Link') or ''
    m = re.search(r'<([^>]+)>\s*;\s*rel="next"', link)
    # Never follow a link off the API host: the request carries the token.
    if m and m.group(1).startswith(API_HOST):
        return m.group(1)
    return None


def get_json(url, cache, used, *, normalize=None, timeout=20):
    """GET an API URL with If-None-Match. Returns (data, next_link); data is
    None for a 404. A 304 returns what was stored for the URL. Raises
    GitHubError for everything else that is not a success."""
    used.add(url)
    entry = (cache.setdefault('urls', {})).get(url)
    h = _headers()
    if entry and entry.get('etag'):
        h['If-None-Match'] = entry['etag']
    try:
        r = requests.get(url, headers=h, timeout=timeout)
    except requests.Timeout:
        raise GitHubError('GitHub did not answer in time (timeout).')
    except requests.ConnectionError:
        raise GitHubError('Cannot connect to GitHub. Check internet access / firewall.')
    except requests.RequestException as e:
        raise GitHubError(f'GitHub request failed ({e.__class__.__name__}).')
    if r.status_code == 304 and entry and 'data' in entry:
        return entry['data'], entry.get('next')
    headers = r.headers or {}
    if r.status_code == 429 or (r.status_code == 403 and headers.get('X-RateLimit-Remaining') == '0'):
        raise GitHubError(_rate_limit_message(r))
    if r.status_code == 404:
        return None, None
    if r.status_code >= 400 or r.status_code == 304:
        raise GitHubError(f'GitHub answered HTTP {r.status_code} for {url.split("/repos/")[-1]}')
    try:
        data = r.json()
    except ValueError:
        raise GitHubError(f'GitHub sent an unreadable answer for {url.split("/repos/")[-1]}')
    if normalize:
        data = normalize(data)
    nxt = _next_link(r)
    etag = headers.get('ETag')
    if etag:
        cache['urls'][url] = {'etag': etag, 'data': data, 'next': nxt}
    else:
        cache['urls'].pop(url, None)
    return data, nxt


def get_raw(url, timeout=20):
    try:
        r = requests.get(url, headers=None, timeout=timeout)
    except requests.RequestException as e:
        raise GitHubError(f'GitHub request failed ({e.__class__.__name__}).')
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        raise GitHubError(f'GitHub answered HTTP {r.status_code}')
    return r.text


# ---------------------------------------------------------------------------
# releases
# ---------------------------------------------------------------------------

def _normalize_release(rel):
    if not isinstance(rel, dict):
        return None
    notes = rel.get('body') or ''
    return {
        'id': rel.get('id'),
        'tag': rel.get('tag_name') or '',
        'name': rel.get('name') or '',
        'draft': bool(rel.get('draft')),
        'prerelease': bool(rel.get('prerelease')),
        'published_at': rel.get('published_at'),
        'created_at': rel.get('created_at'),
        'url': rel.get('html_url') or '',
        'notes': notes[:NOTES_MAX],
        'notes_truncated': len(notes) > NOTES_MAX,
        'assets': [{'name': a.get('name') or '', 'size': a.get('size') or 0,
                    'url': a.get('browser_download_url') or ''}
                   for a in (rel.get('assets') or []) if isinstance(a, dict)],
    }


def list_releases(owner, name, cache, used):
    """Every release on every page. Returns (releases, pages)."""
    url = f'{API}/{owner}/{name}/releases?per_page={PER_PAGE}&page=1'
    out, pages = [], 0
    while url:
        if pages >= MAX_PAGES:
            raise GitHubError(f'The release list has more than {MAX_PAGES * PER_PAGE} entries; '
                              'not showing a partial list.')
        try:
            data, url = get_json(url, cache, used,
                                 normalize=lambda d: [x for x in map(_normalize_release, d or []) if x]
                                 if isinstance(d, list) else d)
        except GitHubError as e:
            if pages:
                raise GitHubError(f'The release list is incomplete: page {pages + 1} could not be '
                                  f'read ({e}). Not showing a partial list.')
            raise
        pages += 1
        if data is None and pages == 1:
            raise GitHubError(f'Repository {owner}/{name} not found on GitHub (or not public).')
        if not isinstance(data, list):
            raise GitHubError(f'GitHub sent an unexpected answer for page {pages} of the releases.')
        out.extend(data)
    return out, pages


def classify(rel) -> str | None:
    """'stable', 'prerelease', or None (draft, or not a release tag)."""
    if rel.get('draft'):
        return None
    m = RELEASE_TAG_RE.match(rel.get('tag') or '')
    if not m:
        return None
    if rel.get('prerelease') or m.group(4):
        return 'prerelease'
    return 'stable'


# ---------------------------------------------------------------------------
# tags and signatures
# ---------------------------------------------------------------------------

def remote_tags():
    """{tag: {'object': sha, 'commit': sha, 'annotated': bool}} from origin."""
    from .revision import ls_remote
    refs = ls_remote('refs/tags/*')
    tags = {}
    for name, sha in refs.items():
        if not name.startswith('refs/tags/'):
            continue
        tag = name[len('refs/tags/'):]
        if tag.endswith('^{}'):
            t = tags.setdefault(tag[:-3], {})
            t['commit'], t['annotated'] = sha, True
        else:
            t = tags.setdefault(tag, {})
            t['object'] = sha
            t.setdefault('commit', sha)
            t.setdefault('annotated', False)
    return {k: v for k, v in tags.items() if v.get('object') and RELEASE_TAG_RE.match(k)}


def api_tag(owner, name, tag, cache, used):
    """The GitHub API's view of one tag: {'object', 'commit', 'annotated',
    'github_signature'}. Tag objects are immutable, so the second lookup is
    cached by object sha for good."""
    ref, _ = get_json(f'{API}/{owner}/{name}/git/ref/tags/{tag}', cache, used,
                      normalize=lambda d: {'object': {'type': (d.get('object') or {}).get('type'),
                                                      'sha': (d.get('object') or {}).get('sha')}}
                      if isinstance(d, dict) else d)
    if not ref or not isinstance(ref.get('object'), dict):
        return None
    obj = ref['object']
    if obj.get('type') != 'tag':
        return {'object': obj.get('sha', ''), 'commit': obj.get('sha', ''), 'annotated': False,
                'github_signature': False}
    known = cache.setdefault('tags', {}).get(obj.get('sha', ''))
    if not known:
        tag_obj, _ = get_json(f'{API}/{owner}/{name}/git/tags/{obj["sha"]}', cache, used)
        tag_obj = tag_obj or {}
        known = {'commit': (tag_obj.get('object') or {}).get('sha', ''),
                 # GitHub's own view; this server verifies locally regardless.
                 'github_signature': bool((tag_obj.get('verification') or {}).get('signature'))}
        if SHA_RE.match(known['commit'] or ''):
            cache['tags'][obj['sha']] = known
    return {'object': obj.get('sha', ''), 'annotated': True, **known}


def _signers_digest():
    from .revision import _Signers
    try:
        with _Signers() as path:
            if not path:
                return ''
            with open(path, 'rb') as f:
                return hashlib.sha256(f.read()).hexdigest()[:16]
    except OSError:
        return ''


def signature_states(entries, cache):
    """Fill entry['signature'] (+ 'signature_detail') for every release."""
    digest = _signers_digest()
    sigs = cache.setdefault('signatures', {})
    todo = {}
    for e in entries:
        if not e.get('sha'):
            e['signature'], e['signature_detail'] = SIG_UNKNOWN, "the tag's commit could not be resolved"
        elif not e.get('annotated'):
            e['signature'], e['signature_detail'] = SIG_UNSIGNED, 'lightweight tag: it cannot carry a signature'
        else:
            key = f"{e['tag_object']}:{digest}"
            if digest and key in sigs:
                ok, msg = sigs[key]
                e['signature'] = SIG_VERIFIED if ok else SIG_INVALID
                e['signature_detail'] = msg
            else:
                e['signature'] = SIG_PENDING
                e['signature_detail'] = 'signed-tag object; its signature is verified when it is installed'
                if digest and e.get('tag_object'):
                    todo[e['tag']] = e['tag_object']
    if todo:
        from .revision import local_tag_signatures
        try:
            found = local_tag_signatures(todo)
        except Exception:
            found = {}
        for e in entries:
            if e['tag'] in found:
                ok, msg = found[e['tag']]
                sigs[f"{e['tag_object']}:{digest}"] = [ok, msg]
                e['signature'] = SIG_VERIFIED if ok else SIG_INVALID
                e['signature_detail'] = msg if ok else f'not signed by a trusted release key ({msg})'


def describe_signature(state):
    return {
        SIG_VERIFIED: 'Verified',
        SIG_PENDING: 'Signed tag (verified at install)',
        SIG_INVALID: 'Not trusted',
        SIG_UNSIGNED: 'Unsigned',
        SIG_UNKNOWN: 'Unknown',
    }.get(state, 'Unknown')


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main_head(owner, name, cache, used):
    c, _ = get_json(f'{API}/{owner}/{name}/commits/main', cache, used,
                    normalize=lambda d: {'sha': d.get('sha', ''), 'commit': {
                        'message': ((d.get('commit') or {}).get('message') or ''),
                        'committer': {'date': (((d.get('commit') or {}).get('committer') or {})
                                               .get('date'))}}} if isinstance(d, dict) else d)
    if not c:
        return None
    sha = c.get('sha', '')
    if not SHA_RE.match(sha or ''):
        raise GitHubError('GitHub sent no commit sha for main.')
    version = ''
    try:
        text = get_raw(f'{RAW}/{owner}/{name}/{sha}/config/version.py') or ''
        m = re.search(r"^VERSION\s*=\s*['\"]([^'\"]+)['\"]", text, re.M)
        version = m.group(1) if m else ''
    except GitHubError:
        pass
    commit = c.get('commit') or {}
    return {'sha': sha, 'version': version,
            'date': (commit.get('committer') or {}).get('date'),
            'message': (commit.get('message') or '').splitlines()[0][:200]
            if commit.get('message') else ''}


def compare(owner, name, base, head, cache, used):
    def slim(d):
        # The full answer carries every changed file's diff: keep the summary.
        if not isinstance(d, dict):
            return d
        commits = d.get('commits') or []
        return {
            'ahead_by': d.get('ahead_by'),
            'behind_by': d.get('behind_by'),
            'commits': [{'sha': c.get('sha', ''),
                         'message': ((c.get('commit') or {}).get('message') or '').splitlines()[0][:160]
                         if (c.get('commit') or {}).get('message') else '',
                         'date': ((c.get('commit') or {}).get('committer') or {}).get('date')}
                        for c in reversed(commits[-MAX_COMMITS_SHOWN:])],
        }
    data, _ = get_json(f'{API}/{owner}/{name}/compare/{base}...{head}', cache, used, normalize=slim)
    return data or None


# ---------------------------------------------------------------------------
# putting it together
# ---------------------------------------------------------------------------

def _ts(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (TypeError, ValueError):
        return 0.0


def sort_newest_first(entries):
    """By the real timestamp (publish date for a release, commit date for
    main), then by version: never by version alone."""
    return sorted(entries, key=lambda e: (_ts(e.get('date')), parse_version(e.get('version'))
                                          or pversion.parse('0')), reverse=True)


def discover(owner=None, name=None):
    """Everything the Updates page lists. Raises GitHubError on any failure
    that would leave the list incomplete."""
    if owner is None:
        owner, name = repo()
    cache = load_http_cache()
    used = set()
    releases, pages = list_releases(owner, name, cache, used)

    tags, tags_error = {}, ''
    try:
        tags = remote_tags()
    except Exception as e:      # git missing, origin unreachable, ...
        tags_error = f'origin could not be asked for its tags ({e})'

    entries, drafts, ignored = [], 0, []
    for rel in releases:
        kind = classify(rel)
        if kind is None:
            if rel.get('draft'):
                drafts += 1
            else:
                ignored.append(rel.get('tag') or '?')
            continue
        tag = rel['tag']
        t = tags.get(tag) or {}
        entries.append({
            'type': kind, 'kind': 'release' if kind == 'stable' else 'prerelease',
            'tag': tag, 'ref': tag, 'version': tag.lstrip('v'),
            'name': rel.get('name') or tag, 'date': rel.get('published_at'),
            'published_at': rel.get('published_at'), 'url': rel.get('url'),
            'notes': rel.get('notes') or '', 'notes_truncated': rel.get('notes_truncated'),
            'assets': rel.get('assets') or [],
            'sha': t.get('commit', '') if SHA_RE.match(t.get('commit', '') or '') else '',
            'tag_object': t.get('object', ''), 'annotated': bool(t.get('annotated')),
            'security': _is_security(rel),
        })

    # Newest of each type by version, as Apply decides; the API also says
    # what GitHub thinks of their signatures (kept for the badge / CLI).
    def newest(kind):
        best = None
        for e in entries:
            if e['type'] != kind:
                continue
            v = parse_version(e['version'])
            if v is not None and (best is None or v > best[0]):
                best = (v, e)
        return best[1] if best else None

    for e in filter(None, (newest('stable'), newest('prerelease'))):
        e['is_latest'] = True
        info = api_tag(owner, name, e['tag'], cache, used)
        if info:
            e['github_signature'] = info.get('github_signature', False)
            if not e['sha']:
                e['sha'] = info.get('commit') if SHA_RE.match(info.get('commit') or '') else ''
                e['tag_object'], e['annotated'] = info.get('object', ''), info.get('annotated', False)
            elif info.get('commit') and info['commit'] != e['sha']:
                e['sha'] = ''
                e['mismatch'] = (f"origin says {e['tag']} is {(tags.get(e['tag']) or {}).get('commit', '')[:12]} but the "
                                 f"GitHub API says {info['commit'][:12]}")
    signature_states(entries, cache)
    for e in entries:
        if e.get('mismatch'):
            e['signature'], e['signature_detail'] = SIG_UNKNOWN, e['mismatch']

    preview = main_head(owner, name, cache, used)
    stable = newest('stable')
    if preview and stable and stable.get('tag'):
        cmp = compare(owner, name, stable['tag'], preview['sha'], cache, used)
        if cmp:
            preview['ahead_of_stable'] = cmp['ahead_by']
            preview['commits'] = cmp['commits']
            preview['since_tag'] = stable['tag']

    save_http_cache(cache, used)
    entries = sort_newest_first(entries)
    return {
        'releases': entries,
        'preview': preview,
        'meta': {'pages': pages, 'release_count': len(releases), 'drafts': drafts,
                 'ignored': ignored[:20], 'ignored_count': len(ignored),
                 'stable_count': sum(1 for e in entries if e['type'] == 'stable'),
                 'prerelease_count': sum(1 for e in entries if e['type'] == 'prerelease'),
                 'tags_error': tags_error, 'complete': True},
    }


_SECURITY_HEADING_RE = re.compile(r'^\s{0,3}#{2,4}\s*security\b', re.IGNORECASE | re.MULTILINE)


def _is_security(rel) -> bool:
    if _SECURITY_HEADING_RE.search(rel.get('notes') or rel.get('body') or ''):
        return True
    return 'security' in (rel.get('name') or '').lower()
