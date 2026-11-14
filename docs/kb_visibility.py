"""
Internal / external KB separation.

An article reaches customers only when staff mark it **Visible in customer
portal** (`Document.is_client_visible`) and it is live (published, approved,
not archived). Inside a customer-visible article, staff can keep notes for
technicians only:

    HTML:      <div class="kb-internal"> ... </div>
    Markdown:  :::internal
               ...
               :::

Those blocks are shown to staff (highlighted, labelled "Internal only") and
removed from everything a customer receives: the portal article page, the
portal search, customer-copy exports and agreement snapshots.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

INTERNAL_CLASS = 'kb-internal'

_MD_OPEN = re.compile(r'^[ \t]*:::[ \t]*internal[ \t]*$', re.MULTILINE | re.IGNORECASE)
_MD_CLOSE = re.compile(r'^[ \t]*:::[ \t]*$', re.MULTILINE)

_VOID = frozenset({'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param',
                   'source', 'track', 'wbr'})


def preprocess_markdown(body: str) -> str:
    """Turn `:::internal` ... `:::` fences into an internal div that
    Markdown keeps rendering inside (md_in_html, part of `extra`)."""
    if not body or ':::' not in body:
        return body
    out, pos, depth = [], 0, 0
    tokens = sorted([(m.start(), m.end(), 'open') for m in _MD_OPEN.finditer(body)]
                    + [(m.start(), m.end(), 'close') for m in _MD_CLOSE.finditer(body)])
    for start, end, kind in tokens:
        if kind == 'close' and depth == 0:
            continue  # a stray ::: is left as text
        out.append(body[pos:start])
        if kind == 'open':
            out.append(f'\n<div class="{INTERNAL_CLASS}" markdown="1">\n')
            depth += 1
        else:
            out.append('\n</div>\n')
            depth -= 1
        pos = end
    out.append(body[pos:])
    out.append('\n</div>\n' * depth)  # an unclosed block runs to the end, and stays internal
    return ''.join(out)


def _is_internal(attrs) -> bool:
    for name, value in attrs:
        if name == 'class' and value and INTERNAL_CLASS in value.split():
            return True
    return False


class _Stripper(HTMLParser):
    """Re-emits HTML unchanged except for elements carrying the internal
    class, which are dropped with everything inside them."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.out = []
        self.skip_tag = None
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if self.skip_depth:
            if tag == self.skip_tag and tag not in _VOID:
                self.skip_depth += 1
            return
        if _is_internal(attrs) and tag not in _VOID:
            self.skip_tag, self.skip_depth = tag, 1
            return
        if _is_internal(attrs):
            return
        self.out.append(self.get_starttag_text())

    def handle_startendtag(self, tag, attrs):
        if self.skip_depth or _is_internal(attrs):
            return
        self.out.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if self.skip_depth:
            if tag == self.skip_tag:
                self.skip_depth -= 1
            return
        self.out.append(f'</{tag}>')

    def _text(self, text):
        if not self.skip_depth:
            self.out.append(text)

    def handle_data(self, data):
        self._text(data)

    def handle_entityref(self, name):
        self._text(f'&{name};')

    def handle_charref(self, name):
        self._text(f'&#{name};')

    def handle_comment(self, data):
        pass  # comments never reach customers

    def handle_decl(self, decl):
        self._text(f'<!{decl}>')


def strip_internal(html: str) -> str:
    """Remove internal-only blocks from rendered (sanitised) HTML."""
    if not html or INTERNAL_CLASS not in html:
        return html or ''
    p = _Stripper()
    p.feed(html)
    p.close()
    return ''.join(p.out)


def has_internal_blocks(document) -> bool:
    body = document.body or ''
    return INTERNAL_CLASS in body or bool(_MD_OPEN.search(body))


def client_body_matches(qs, terms, limit=500):
    """pks of documents in `qs` whose customer-visible text contains any of
    `terms`. The database narrows by raw body first; documents with
    internal blocks are then re-checked against what a customer sees, so a
    word that only appears in an internal note never surfaces an article."""
    from django.db.models import Q
    terms = [t.lower() for t in terms if t]
    if not terms:
        return []
    body_q = Q()
    for t in terms:
        body_q |= Q(body__icontains=t)
    pks = []
    for doc in qs.filter(body_q).only('pk', 'body', 'content_type', 'title')[:limit]:
        if not has_internal_blocks(doc):
            pks.append(doc.pk)
            continue
        text = client_text(doc).lower()
        if any(t in text for t in terms):
            pks.append(doc.pk)
    return pks


_TAGS = re.compile(r'<[^>]+>')


def client_text(document) -> str:
    """Plain text of what a customer sees (for portal search)."""
    import html as _html
    return _html.unescape(_TAGS.sub(' ', document.render_for_client()))


# Rows re-checked in Python per text search: documents whose raw body
# matches *and* carries an internal-block marker. Anything past this many is
# left out (an under-return, never a disclosure).
TEXT_RECHECK_LIMIT = 500


def text_search_q(qs, query, *, customer_copy, fields=('title', 'body')):
    """Q narrowing `qs` to documents matching `query` in `fields`.

    For staff (``customer_copy=False``) a plain ``icontains`` on each field.
    For a reader who gets the customer copy (customer users; staff exporting
    a customer copy) the body only counts for the text they would actually
    receive: a word that appears only inside an internal-only block
    (``:::internal`` / ``class="kb-internal"``) must not make the document
    match — the match itself would reveal that the internal note says it.
    Documents without internal markers keep the database match; the few
    whose raw body matches and carries a marker are re-checked against
    `client_text`.
    """
    from django.db.models import Q
    cond = Q(pk__in=[])
    query = (query or '').strip()
    if not query:
        return cond
    for f in fields:
        if f != 'body':
            cond |= Q(**{f'{f}__icontains': query})
    if 'body' not in fields:
        return cond
    if not customer_copy:
        return cond | Q(body__icontains=query)
    marker = Q(body__icontains=INTERNAL_CLASS) | Q(body__icontains=':::')
    cond |= Q(body__icontains=query) & ~marker
    needle = query.lower()
    ok = []
    # A plain queryset over the candidates' pks: the caller's may carry
    # select_related / prefetches that `.only()` cannot combine with.
    candidates = qs.model._default_manager.filter(
        pk__in=qs.filter(Q(body__icontains=query) & marker).values('pk'))
    for doc in candidates.only('pk', 'body', 'content_type', 'title')[:TEXT_RECHECK_LIMIT]:
        if not has_internal_blocks(doc) or needle in client_text(doc).lower():
            ok.append(doc.pk)
    if ok:
        cond |= Q(pk__in=ok)
    return cond
