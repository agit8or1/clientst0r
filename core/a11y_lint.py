"""Test-time accessibility checker: form controls without a label and
icon-only links/buttons without an accessible name.

Parses rendered HTML with the standard library only. Used by
core/tests/test_a11y_names.py (113.4). Not imported at runtime by the app.

Findings are dicts: {'kind': 'unlabelled-control' | 'unnamed-control', 'tag', 'snippet'}.
"""
import re
from html.parser import HTMLParser

VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source',
        'track', 'wbr'}
NON_CONTROL_INPUT = {'hidden', 'submit', 'button', 'reset', 'image'}
HIDDEN_STYLE = re.compile(r'display\s*:\s*none|visibility\s*:\s*hidden', re.I)


class _El:
    __slots__ = ('tag', 'attrs', 'text', 'has_img_alt', 'hidden', 'label_depth', 'line')

    def __init__(self, tag, attrs, hidden, line):
        self.tag, self.attrs, self.hidden, self.line = tag, attrs, hidden, line
        self.text = ''
        self.has_img_alt = False
        self.label_depth = False


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []          # open elements (non-void)
        self.skip_depth = 0      # inside <template>/<script>/<style>
        self.controls = []       # (el, wrapped_in_label)
        self.names = []          # finished <a>/<button>/role=button elements
        self.label_for = set()
        self.ids_text = {}       # id -> text (for aria-labelledby validity)
        self.labels_open = 0
        self.findings_raw = []

    # -- helpers
    def _hidden_now(self, attrs):
        if 'hidden' in attrs or attrs.get('aria-hidden') == 'true':
            return True
        if attrs.get('style') and HIDDEN_STYLE.search(attrs['style']):
            return True
        return False

    def handle_starttag(self, tag, attrs_list):
        attrs = {k: (v if v is not None else '') for k, v in attrs_list}
        if tag in ('template', 'script', 'style', 'noscript'):
            if tag not in VOID:
                self.skip_depth += 1
                self.stack.append(_El(tag, attrs, True, self.getpos()[0]))
            return
        parent_hidden = bool(self.stack and self.stack[-1].hidden)
        hidden = parent_hidden or self._hidden_now(attrs)
        if tag == 'img' and self.stack and not self.skip_depth:
            if attrs.get('alt', '').strip():
                for el in self.stack:
                    if el.tag in ('a', 'button') or el.attrs.get('role') == 'button':
                        el.has_img_alt = True
        if tag == 'label' and attrs.get('for'):
            self.label_for.add(attrs['for'])
        if tag in VOID:
            if tag == 'input' and not self.skip_depth and not hidden:
                if attrs.get('type', 'text').lower() not in NON_CONTROL_INPUT:
                    self.controls.append((_El(tag, attrs, hidden, self.getpos()[0]), self.labels_open > 0))
            return
        el = _El(tag, attrs, hidden, self.getpos()[0])
        self.stack.append(el)
        if tag == 'label':
            self.labels_open += 1
        if tag in ('select', 'textarea') and not self.skip_depth and not hidden:
            self.controls.append((el, self.labels_open > 0))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_data(self, data):
        if self.skip_depth:
            return
        if self.stack and any(e.hidden for e in self.stack):
            return
        for el in self.stack:
            if el.tag in ('a', 'button') or el.attrs.get('role') == 'button':
                el.text += data

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i].tag == tag:
                break
        else:
            return
        while len(self.stack) > i:
            el = self.stack.pop()
            if el.tag in ('template', 'script', 'style', 'noscript'):
                self.skip_depth -= 1
            elif el.tag == 'label':
                self.labels_open -= 1
            if (el.tag in ('a', 'button') or el.attrs.get('role') == 'button') and not el.hidden \
                    and not self.skip_depth:
                self.names.append(el)


def _snippet(el):
    keep = ('type', 'name', 'id', 'class', 'href', 'placeholder', 'title')
    attrs = ' '.join(f'{k}="{el.attrs[k]}"' for k in keep if k in el.attrs)
    return f'<{el.tag} {attrs}> line {el.line}'[:200]


def _has_name_attrs(attrs):
    return any(attrs.get(k, '').strip() for k in ('aria-label', 'aria-labelledby', 'title'))


def check_html(html):
    p = _Parser()
    p.feed(html)
    p.close()
    findings = []
    for el, wrapped in p.controls:
        if el.attrs.get('type', '').lower() in NON_CONTROL_INPUT:
            continue
        if wrapped or _has_name_attrs(el.attrs):
            continue
        if el.attrs.get('id') and el.attrs['id'] in p.label_for:
            continue
        findings.append({'kind': 'unlabelled-control', 'tag': el.tag, 'snippet': _snippet(el)})
    for el in p.names:
        if el.tag == 'a' and 'href' not in el.attrs and el.attrs.get('role') != 'button':
            continue  # placeholder anchor, not a control
        if el.tag == 'button' and el.attrs.get('type') == 'submit' and el.attrs.get('value'):
            continue
        if el.text.strip() or el.has_img_alt or _has_name_attrs(el.attrs):
            continue
        findings.append({'kind': 'unnamed-control', 'tag': el.tag, 'snippet': _snippet(el)})
    return findings


def summarize(findings):
    return '\n'.join(f"  {f['kind']}: {f['snippet']}" for f in findings)
