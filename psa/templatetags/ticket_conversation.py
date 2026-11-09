"""Rendering helpers for the shared ticket conversation include
(templates/psa/_conversation.html)."""
import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

_INLINE_CODE = re.compile(r'`([^`\n]+)`')


def _text_html(lines):
    text = '\n'.join(lines).strip('\n')
    if not text.strip():
        return ''
    html = _INLINE_CODE.sub(r'<code>\1</code>', escape(text))
    return f'<div class="tc-text">{html}</div>'


def _code_html(lines):
    return f'<pre class="tc-code"><code>{escape(chr(10).join(lines))}</code></pre>'


@register.filter
def conversation_body(value):
    """Message body as HTML: everything escaped, line breaks kept (the
    .tc-text block is white-space: pre-wrap), ```fenced``` blocks become
    <pre><code>, `inline` spans become <code>. An unclosed fence runs to the
    end of the message, like most chat renderers."""
    lines = str(value or '').replace('\r\n', '\n').replace('\r', '\n').split('\n')
    parts, buf, in_code = [], [], False
    for line in lines:
        if line.lstrip().startswith('```'):
            parts.append(_code_html(buf) if in_code else _text_html(buf))
            buf, in_code = [], not in_code
            continue
        buf.append(line)
    parts.append(_code_html(buf) if in_code else _text_html(buf))
    return mark_safe(''.join(p for p in parts if p))
