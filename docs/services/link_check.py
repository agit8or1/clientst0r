"""
KB dead-link check.

Finds broken links in published KB articles (staff and global):

  * internal links — /docs/<slug>/, /docs/id/<pk>/…, /docs/kb/<slug>/ and
    /portal/kb/<slug>/ (relative, or absolute on this site's own host) — to a
    document that does not exist, is archived or is not published; and, from a
    customer-visible article, to a document customers cannot see;
  * external http(s) links that fail a HEAD check.

External checks go through core.safe_http: the URL text is validated
(`validate_public_url`) on the original URL and on every redirect hop, and the
connection itself is opened by the guarded session, which refuses non-public
addresses at socket-open time (no DNS rebinding). Links to internal or
non-public addresses are never fetched — they are recorded as "not checked",
not as dead. Each URL is checked at most once per RECHECK_DAYS and at most
MAX_EXTERNAL_PER_RUN URLs are fetched per run.

Run by the scheduler (`kb_link_check`); the analytics page can re-run the
internal half on demand (no outbound requests from a web request).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import timedelta
from html.parser import HTMLParser
from typing import Callable, Optional
from urllib.parse import urljoin, urlsplit

from django.utils import timezone

logger = logging.getLogger('docs.link_check')

MAX_EXTERNAL_PER_RUN = 200
RECHECK_DAYS = 7
USER_AGENT = 'ClientSt0r-LinkCheck/1.0 (+KB dead-link check)'
TIMEOUT = (5, 10)

# First path segments under /docs/ that are app pages, not document slugs.
_RESERVED = frozenset({
    'create', 'upload', 'import', 'ai', 'export', 'review-queue', 'approval-queue', 'lifecycle', 'id',
    'templates', 'kb', 'categories', 'diagrams', 'api',
})
_SLUG = re.compile(r'^[-a-zA-Z0-9_]+$')


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            for name, value in attrs:
                if name == 'href' and value:
                    self.hrefs.append(value.strip())


def extract_links(html: str) -> list[str]:
    p = _Links()
    try:
        p.feed(html or '')
        p.close()
    except Exception:  # noqa: BLE001 — malformed HTML: use what was parsed
        pass
    seen, out = set(), []
    for h in p.hrefs:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def _source_html(doc) -> str:
    """The article's HTML before sanitising. The sanitiser drops relative
    hrefs, but those are exactly the internal links authors write, so links
    are read from what the author wrote (HTML as is, Markdown rendered)."""
    if doc.content_type == 'markdown':
        import markdown
        from docs.kb_visibility import preprocess_markdown
        return markdown.markdown(preprocess_markdown(doc.body or ''), extensions=['extra'])
    return doc.body or ''


def _own_hosts() -> set:
    from django.conf import settings
    from core.models import SystemSetting
    hosts = set()
    try:
        site = SystemSetting.get_settings().site_url or ''
        if site:
            hosts.add((urlsplit(site).hostname or '').lower())
    except Exception:  # noqa: BLE001
        pass
    for h in getattr(settings, 'ALLOWED_HOSTS', []) or []:
        if h and h not in ('*',) and not h.startswith('.'):
            hosts.add(h.lower())
    hosts.discard('')
    return hosts


@dataclass
class Finding:
    url: str
    kind: str
    reason: str
    status_code: Optional[int] = None
    target: object = None


def _target_problem(source, target) -> Optional[str]:
    if target is None:
        return 'Document does not exist'
    if target.is_archived:
        return 'Document is archived'
    if not target.is_published or target.is_draft:
        return 'Document is not published'
    if source.is_client_visible and not target.is_client_visible:
        return 'Links a customer-visible article to an internal document'
    return None


def check_internal(source, path: str):
    """(is_internal_document_link, Finding or None) for a site path."""
    from docs.models import Document
    parts = [p for p in path.split('/') if p]
    if len(parts) < 2 or parts[0] not in ('docs', 'portal'):
        return False, None
    target = None
    if parts[0] == 'portal':
        if len(parts) < 3 or parts[1] != 'kb' or not _SLUG.match(parts[2]):
            return False, None
        from django.db.models import Q
        scope = Q(is_global=True)
        if source.organization_id:
            scope |= Q(organization_id=source.organization_id)
        target = Document.objects.filter(scope, slug=parts[2], is_template=False).order_by('-is_global').first()
        if target is not None and not target.is_client_visible:
            return True, Finding(path, 'internal', 'Portal link to a document customers cannot see', target=target)
    elif parts[1] == 'id':
        if len(parts) < 3 or not parts[2].isdigit():
            return False, None
        target = Document.objects.filter(pk=int(parts[2])).first()
    elif parts[1] == 'kb':
        if len(parts) < 3 or not _SLUG.match(parts[2]) or parts[2] == 'create':
            return False, None
        target = Document.objects.filter(slug=parts[2], is_global=True).first()
    else:
        slug = parts[1]
        if slug in _RESERVED or not _SLUG.match(slug):
            return False, None
        qs = Document.objects.filter(slug=slug, is_global=False)
        if source.organization_id:
            qs = qs.filter(organization_id=source.organization_id)
        target = qs.order_by('pk').first()
    problem = _target_problem(source, target)
    return True, (Finding(path, 'internal', problem, target=target) if problem else None)


def head_check(url: str) -> tuple[Optional[bool], Optional[int], str]:
    """HEAD a public URL through the SSRF guard. Returns (ok, status, error);
    ok is None when the URL was not checked (not a public address, or the
    server rate-limited us)."""
    import requests
    from core.safe_http import MAX_REDIRECTS, UnsafeURLError, build_guarded_session, validate_public_url
    current = url
    try:
        with build_guarded_session() as session:
            for _hop in range(MAX_REDIRECTS + 1):
                current = validate_public_url(current)
                response = session.head(current, headers={'User-Agent': USER_AGENT}, timeout=TIMEOUT,
                                        allow_redirects=False)
                response.close()
                if response.status_code in (405, 501):  # HEAD not supported: a streamed GET, body unread
                    response = session.get(current, headers={'User-Agent': USER_AGENT}, timeout=TIMEOUT,
                                           allow_redirects=False, stream=True)
                    response.close()
                if response.is_redirect and response.headers.get('Location'):
                    current = urljoin(current, response.headers['Location'])
                    continue
                code = response.status_code
                if code == 429:
                    return None, code, 'Rate limited; try later'
                if code in (401, 403):
                    return True, code, ''  # exists, needs a login
                return code < 400, code, '' if code < 400 else f'HTTP {code}'
            return False, None, 'Too many redirects'
    except UnsafeURLError:
        return None, None, 'Not checked: not a public web address'
    except requests.Timeout:
        return False, None, 'Timed out'
    except requests.RequestException as e:
        return False, None, f'Unreachable: {type(e).__name__}'[:255]


def run(*, check_external: bool = True, now=None, http: Callable = head_check,
        max_external: int = MAX_EXTERNAL_PER_RUN, recheck_days: int = RECHECK_DAYS) -> dict:
    """Check every published, non-template, non-file KB article and store
    the dead links. Returns counts."""
    from docs.kb_link_models import KBDeadLink, KBExternalLink, url_hash
    from docs.models import Document
    now = now or timezone.now()
    stale_before = now - timedelta(days=recheck_days)
    hosts = _own_hosts()
    budget = max_external
    counts = {'documents': 0, 'links': 0, 'internal_dead': 0, 'external_dead': 0, 'external_checked': 0,
              'external_skipped': 0}
    cache: dict[str, object] = {}
    seen_docs = []
    docs = (Document.objects.published().filter(is_template=False).exclude(content_type='file')
            .only('pk', 'title', 'slug', 'body', 'content_type', 'organization_id', 'is_global',
                  'is_client_visible'))
    for doc in docs.iterator():
        seen_docs.append(doc.pk)
        counts['documents'] += 1
        findings = []
        for href in extract_links(_source_html(doc)):
            if href.startswith(('#', 'mailto:', 'tel:')):
                continue
            parts = urlsplit(href)
            scheme = (parts.scheme or '').lower()
            if scheme and scheme not in ('http', 'https'):
                continue
            counts['links'] += 1
            host = (parts.hostname or '').lower()
            if not scheme or host in hosts:
                _is_doc, finding = check_internal(doc, parts.path or '')
                if finding is not None:
                    finding.url = href
                    findings.append(finding)
                continue
            # External.
            h = url_hash(href)
            rec = cache.get(h)
            if rec is None:
                rec = KBExternalLink.objects.filter(url_hash=h).first()
                due = rec is None or rec.last_checked_at is None or rec.last_checked_at < stale_before
                if check_external and due and budget > 0:
                    budget -= 1
                    ok, code, err = http(href)
                    counts['external_checked'] += 1
                    rec, _ = KBExternalLink.objects.update_or_create(url_hash=h, defaults={
                        'url': href, 'last_checked_at': now, 'ok': ok, 'status_code': code, 'error': err[:255]})
                elif due:
                    counts['external_skipped'] += 1
                cache[h] = rec or False
            if rec and rec.ok is False:
                findings.append(Finding(href, 'external', rec.error or f'HTTP {rec.status_code}',
                                        status_code=rec.status_code))
        _store(doc, findings, now)
        counts['internal_dead'] += sum(1 for f in findings if f.kind == 'internal')
        counts['external_dead'] += sum(1 for f in findings if f.kind == 'external')
    KBDeadLink.objects.exclude(document_id__in=seen_docs).delete()
    return counts


def _store(doc, findings, now):
    from docs.kb_link_models import KBDeadLink, url_hash
    existing = {d.url_hash: d for d in KBDeadLink.objects.filter(document=doc)}
    keep = set()
    for f in findings:
        h = url_hash(f.url)
        if h in keep:
            continue
        keep.add(h)
        row = existing.get(h)
        target_id = getattr(f.target, 'pk', None)
        if row is None:
            KBDeadLink.objects.create(document=doc, url=f.url, url_hash=h, kind=f.kind, reason=f.reason[:255],
                                      status_code=f.status_code, target_document_id=target_id,
                                      first_seen_at=now, last_seen_at=now)
        else:
            KBDeadLink.objects.filter(pk=row.pk).update(kind=f.kind, reason=f.reason[:255],
                                                        status_code=f.status_code,
                                                        target_document_id=target_id, last_seen_at=now)
    stale = [row.pk for h, row in existing.items() if h not in keep]
    if stale:
        KBDeadLink.objects.filter(pk__in=stale).delete()
