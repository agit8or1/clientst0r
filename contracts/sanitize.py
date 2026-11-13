"""HTML sanitising for contract text.

Everything that ends up in a contract — template sections, clauses, typed
edits — passes through `clean_html` on save and again when a version is
issued. The allow-list is small on purpose:

* no images, iframes, objects, forms, scripts, styles or style attributes,
  so nothing in a contract can load a remote or local resource, in the
  browser or in the PDF renderer;
* links only to http(s) and mailto, opened with rel="noopener noreferrer";
* classes only from a fixed list (alignment, indentation, page breaks).
"""
from __future__ import annotations

import re

import bleach

ALLOWED_TAGS = [
    'p', 'br', 'h1', 'h2', 'h3', 'h4', 'strong', 'b', 'em', 'i', 'u', 's', 'sub', 'sup',
    'ul', 'ol', 'li', 'blockquote', 'pre', 'code', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'hr', 'a', 'span', 'div',
]
ALLOWED_CLASSES = {
    'page-break', 'ql-align-center', 'ql-align-right', 'ql-align-justify',
    *(f'ql-indent-{n}' for n in range(1, 9)),
}
ALLOWED_PROTOCOLS = ['http', 'https', 'mailto']
_TABLE_ROW = re.compile(r'^row-[a-z0-9]{1,12}$')
PAGE_BREAK = '<hr class="page-break">'
_PAGE_BREAK_RE = re.compile(r'<hr\s+class="page-break"\s*/?>', re.I)


def _attr_ok(tag, name, value):
    if name == 'class':
        return all(c in ALLOWED_CLASSES for c in (value or '').split())
    if tag == 'a' and name in ('href', 'title'):
        return True
    if tag in ('td', 'th') and name in ('colspan', 'rowspan'):
        return (value or '').isdigit() and 0 < int(value) <= 20
    if tag == 'td' and name == 'data-row':
        return bool(_TABLE_ROW.match(value or ''))
    return False


def _link_attrs(attrs, new=False):
    href = attrs.get((None, 'href'), '')
    if href and not href.lower().startswith(('http://', 'https://', 'mailto:')):
        attrs.pop((None, 'href'), None)
        return attrs
    attrs[(None, 'rel')] = 'noopener noreferrer'
    attrs[(None, 'target')] = '_blank'
    return attrs


_cleaner = bleach.sanitizer.Cleaner(tags=ALLOWED_TAGS, attributes=_attr_ok, protocols=ALLOWED_PROTOCOLS,
                                    strip=True, strip_comments=True)


_linker = bleach.Linker(callbacks=[_link_attrs], url_re=re.compile(r'(?!x)x'), parse_email=False)


def clean_html(html: str) -> str:
    if not html:
        return ''
    # Content of dangerous containers goes entirely (bleach strip=True keeps text).
    html = re.sub(r'(?is)<(script|style|iframe|object|embed|template|noscript|svg|math)\b.*?</\1\s*>', '', html)
    html = re.sub(r'(?i)<div\s+class="page-break"\s*>\s*</div>', PAGE_BREAK, html)
    # Non-breaking spaces (rich-text editors emit one for every space) would
    # stop text wrapping on the signing page and in the PDF.
    html = html.replace('&nbsp;', ' ').replace('\u00a0', ' ').replace('&#160;', ' ')
    cleaned = _cleaner.clean(html)
    # Existing links get rel/target attributes; bare text is never turned into
    # a link (a merge field such as {{client.name}} looks like a host name).
    cleaned = _linker.linkify(cleaned)
    return cleaned.strip()


def split_page_breaks(html: str) -> list[str]:
    return _PAGE_BREAK_RE.split(html or '')


def plain_text(value: str, limit: int = 2000) -> str:
    """A single-line or multi-line text field: strip markup and control
    characters (escaping happens when the value is shown)."""
    from django.utils.html import strip_tags
    value = strip_tags(value or '').replace('\r\n', '\n')
    value = ''.join(ch for ch in value if ch == '\n' or ch == '\t' or ord(ch) >= 32)
    return value[:limit].strip()
