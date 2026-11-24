"""
Email body cleanup + HTML sanitization helpers for the PSA email-to-ticket
pipeline (Phase 10.2).

These are pure functions — no DB, no network, no Django imports beyond
optional settings overrides — so they're trivially unit-testable. The
poller calls them after `_extract_bodies()` returns raw text and HTML.

Design choices:

- ``sanitize_html`` runs bleach with a tight allowlist suitable for
  rendering inside a sandboxed iframe in Phase 10.4's conversation panel.
  Scripts, styles, iframes, and remote images are stripped. Links survive
  but are tagged ``rel="noopener noreferrer"`` and ``target="_blank"``.

- ``strip_signature`` cuts at the RFC 3676 sentinel ``\\n-- \\n`` and
  falls back to a small set of mobile-client / canned-marketing prefaces.
  Conservative on purpose — false-positive strips are worse than leaving
  a signature in the body.

- ``strip_quoted_reply`` removes the trailing reply chain in three
  passes: an explicit "On ... wrote:" header (Apple Mail / Gmail), an
  Outlook "From: / Sent: / To: / Subject:" header block, and a tail of
  contiguous ``>``-prefixed lines. Each pass is independent and only
  trims from the bottom.
"""
from __future__ import annotations

import re

import bleach


# Tags allowed through the HTML sanitizer. Conservative — covers what an
# email client typically produces while ruling out the obvious vectors.
_ALLOWED_TAGS = frozenset({
    'a', 'b', 'blockquote', 'br', 'code', 'div', 'em', 'h1', 'h2', 'h3',
    'h4', 'h5', 'h6', 'hr', 'i', 'li', 'ol', 'p', 'pre', 'span', 'strong',
    'sub', 'sup', 'table', 'tbody', 'td', 'th', 'thead', 'tr', 'u', 'ul',
})

_ALLOWED_ATTRS = {
    'a': ['href', 'title'],
    'span': ['lang'],
    'td': ['colspan', 'rowspan'],
    'th': ['colspan', 'rowspan'],
}


def sanitize_html(html: str) -> str:
    """
    Return a sanitized HTML string safe to render in a sandboxed iframe.

    Removes <script>, <style>, <iframe>, <object>, <embed>, inline event
    handlers, ``style`` attributes, and embedded images (tracking pixels).
    Links are rewritten with ``rel="noopener noreferrer"`` and
    ``target="_blank"``.
    """
    if not html:
        return ''

    cleaned = bleach.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        protocols=['http', 'https', 'mailto', 'tel'],
        strip=True,
        strip_comments=True,
    )
    return bleach.linkify(
        cleaned,
        callbacks=[
            lambda attrs, new=False: {**attrs, (None, 'rel'): 'noopener noreferrer',
                                       (None, 'target'): '_blank'},
        ],
    )


# RFC 3676 §4.3 sentinel — the literal four bytes ``\n-- \n``. We also
# accept it on a line by itself at the very start of the text.
_SIG_SENTINEL = re.compile(r'(?:\n|\A)-- ?\n')

# Common mobile / marketing prefaces. Each is treated as the start of the
# signature and everything from there to the end of the body is stripped.
_SIG_PREFACES = [
    re.compile(r'\n[ \t]*Sent from my [A-Za-z0-9 ]+\n', re.IGNORECASE),
    re.compile(r'\n[ \t]*Get Outlook for (?:iOS|Android)\n', re.IGNORECASE),
    re.compile(r'\n[ \t]*Sent via [A-Za-z0-9 ]+\n', re.IGNORECASE),
]


def strip_signature(text: str) -> str:
    """
    Trim the trailing signature from a plain-text email body.

    Looks for the RFC 3676 ``-- `` sentinel first; falls back to a small
    set of mobile/canned marketing prefaces. Returns the input unchanged
    when nothing matches — false-positive strips are worse than a signature
    leaking into the ticket body.
    """
    if not text:
        return ''

    m = _SIG_SENTINEL.search(text)
    cut = m.start() if m else None

    for pattern in _SIG_PREFACES:
        match = pattern.search(text)
        if match and (cut is None or match.start() < cut):
            cut = match.start()

    if cut is None:
        return text
    return text[:cut].rstrip()


# Apple Mail / Gmail: ``On <date>, <person> wrote:`` followed by the
# quoted message. The pattern is permissive on date format and tolerates
# multi-line wrapping ("On Tue, Mar 4, 2026 at 10:00 AM\nAlice <a@b>\nwrote:").
_QUOTE_HEADER_LINE = re.compile(
    r'\n[ \t]*On [^\n]{1,200}(?:\n[^\n]{0,200}){0,3}\bwrote:\s*\n',
    re.IGNORECASE,
)

# Outlook desktop: "-----Original Message-----" or a "From: / Sent: /
# To: / Subject:" block. Either form starts the quoted section.
_OUTLOOK_HEADER = re.compile(
    r'\n[ \t]*(?:-----Original Message-----|'
    r'From:\s*[^\n]+\n[ \t]*Sent:\s*[^\n]+\n[ \t]*To:\s*[^\n]+'
    r'(?:\n[ \t]*Cc:\s*[^\n]+)?'
    r'\n[ \t]*Subject:[^\n]+)',
    re.IGNORECASE,
)


def strip_quoted_reply(text: str) -> str:
    """
    Trim the trailing quoted-reply chain from a plain-text email body.

    Three passes, each only ever trims from the bottom:
      (a) Apple/Gmail "On ... wrote:" header.
      (b) Outlook "-----Original Message-----" or From/Sent/To/Subject block.
      (c) Tail of contiguous ``>``-prefixed lines.

    Each pass uses the *earliest* match in the message body — once a
    quoted section starts, everything below it goes.
    """
    if not text:
        return ''

    cut = None
    for pattern in (_QUOTE_HEADER_LINE, _OUTLOOK_HEADER):
        m = pattern.search(text)
        if m and (cut is None or m.start() < cut):
            cut = m.start()

    # Find the start of the trailing block of ``>``-prefixed lines, allowing
    # blank lines between quoted blocks. Skip trailing blank lines first,
    # then walk backwards through quote and intermixed blank lines. Stop at
    # the first non-quote non-blank line we hit.
    lines = text.split('\n')
    i = len(lines) - 1
    while i >= 0 and lines[i].strip() == '':
        i -= 1
    quote_start = None
    seen_quote = False
    while i >= 0:
        stripped = lines[i].lstrip()
        if stripped.startswith('>'):
            quote_start = i
            seen_quote = True
            i -= 1
        elif seen_quote and stripped == '':
            quote_start = i
            i -= 1
        else:
            break
    if seen_quote and quote_start is not None and quote_start > 0:
        offset = sum(len(line) + 1 for line in lines[:quote_start])
        if cut is None or offset < cut:
            cut = offset

    if cut is None:
        return text
    return text[:cut].rstrip()


def clean_reply_body(text: str) -> str:
    """
    Convenience: strip quoted reply *then* signature. Order matters — the
    signature on the customer's reply comes BEFORE the quoted history,
    so cutting the quote first leaves the sig in place to be stripped.
    """
    return strip_signature(strip_quoted_reply(text))


# ---------------------------------------------------------------------------
# Phase 10.3 — Auto-responder detection, DMARC verdict gate, spam keywords
# ---------------------------------------------------------------------------

# RFC 3834 + common vendor-specific markers. Each is a (header_name, value
# regex) pair; presence of ANY pair classifies the message as an
# auto-responder loop.
_AUTO_RESPONDER_HEADERS = [
    ('Auto-Submitted', re.compile(r'^auto-(replied|generated|notified)', re.IGNORECASE)),
    ('X-Autoreply', re.compile(r'.+', re.IGNORECASE)),
    ('X-Autorespond', re.compile(r'.+', re.IGNORECASE)),
    ('X-Autoresponder', re.compile(r'.+', re.IGNORECASE)),
    ('Precedence', re.compile(r'^(bulk|list|junk)\b', re.IGNORECASE)),
    ('X-FC-MachineGenerated', re.compile(r'^true', re.IGNORECASE)),
    ('X-POST-MessageClass', re.compile(r'9;\s*Autoresponder', re.IGNORECASE)),
]

# Subject-line heuristics. These fire only when the headers don't already
# tell us — the headers are authoritative; the subject is a backstop for
# clients that don't set them properly.
_OOO_SUBJECT_PATTERNS = [
    re.compile(r'\bout\s+of\s+(the\s+)?office\b', re.IGNORECASE),
    re.compile(r'\bvacation\s+(auto[\s-]?reply|notice|response)\b', re.IGNORECASE),
    re.compile(r'\bauto[\s-]?reply\b', re.IGNORECASE),
    re.compile(r'\bautomatic(ally)?\s+generated\b', re.IGNORECASE),
    re.compile(r'\b(undeliver|delivery\s+(failure|status))\b', re.IGNORECASE),
]


def detect_auto_responder(msg) -> str:
    """
    Inspect ``msg`` (an ``email.message.Message``) for auto-responder /
    NDR / out-of-office markers. Returns a one-line reason string when
    detected, or '' when the message looks like a normal human reply.

    The poller treats any non-empty return as "quarantine, do not create
    or update a ticket". The reason string lands on
    ``EmailMessage.quarantine_reason``.
    """
    # 1. Authoritative: explicit auto-responder headers.
    for header, pattern in _AUTO_RESPONDER_HEADERS:
        value = msg.get(header)
        if value and pattern.search(str(value)):
            return f'auto-responder header: {header}: {str(value)[:80]}'

    # 2. Bounce / NDR — multipart/report with delivery-status.
    ctype = (msg.get_content_type() or '').lower()
    if ctype == 'multipart/report':
        report_type = (msg.get_param('report-type') or '').lower()
        if report_type in ('delivery-status', 'disposition-notification'):
            return f'NDR / delivery-status report (report-type={report_type})'

    # 3. Subject-line heuristics — only used when no header signal fired.
    subject = msg.get('Subject') or ''
    for pattern in _OOO_SUBJECT_PATTERNS:
        if pattern.search(subject):
            return f'auto-responder subject heuristic: {pattern.pattern}'
    return ''


def parse_authentication_results(msg):
    """
    Parse the upstream MTA's ``Authentication-Results`` header and return a
    dict like ``{'spf': 'pass', 'dkim': 'fail', 'dmarc': 'pass'}``. Verdicts
    not present in the header are omitted.

    Trusts the upstream MTA to have written the header — no inline crypto
    or DNS lookups happen here. If the deployment fronts Clientst0r with
    Postfix / Exchange / M365 / Mailcow / iRedMail, that header is set
    automatically.
    """
    out: dict[str, str] = {}
    for header_value in msg.get_all('Authentication-Results') or []:
        for tok in str(header_value).split(';'):
            tok = tok.strip().lower()
            for method in ('spf', 'dkim', 'dmarc', 'arc'):
                if tok.startswith(f'{method}='):
                    verdict = tok.split('=', 1)[1].split()[0]
                    out[method] = verdict
    return out


# Common spammy n-grams. Score = number of distinct hits. Threshold-tuned
# to be conservative — we'd rather let one spam in than auto-ticket on a
# legitimate "winning" customer email (e.g. a partner congratulating us
# on a sale uses many of these innocently).
_SPAM_KEYWORDS = [
    re.compile(r'\bclaim\s+your\s+(prize|winnings)\b', re.IGNORECASE),
    re.compile(r'\b(act|reply)\s+(now|today)\b.{0,40}(limited|urgent)', re.IGNORECASE),
    re.compile(r'\bcongratulations\b.{0,40}\b(winner|selected|chosen)\b', re.IGNORECASE),
    re.compile(r'\bguaranteed\s+(loan|approval|income)\b', re.IGNORECASE),
    re.compile(r'\b(viagra|cialis|levitra)\b', re.IGNORECASE),
    re.compile(r'\b(nigerian|bank)\s+prince\b', re.IGNORECASE),
    re.compile(r'\bcrypto(currency)?\s+(invest|investment|trading)\s+platform\b', re.IGNORECASE),
    re.compile(r'\b(wire|bank)\s+transfer\s+from\s+\$\d', re.IGNORECASE),
]


def spam_keyword_score(text: str) -> int:
    """Number of distinct spam-keyword pattern hits in ``text``. Caller
    decides what threshold is "spam"."""
    if not text:
        return 0
    return sum(1 for pat in _SPAM_KEYWORDS if pat.search(text))
