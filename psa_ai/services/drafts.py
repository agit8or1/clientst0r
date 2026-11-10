"""
Recognising a reply that came from an AI draft.

AI drafts reach the composer through "Use reply", which also marks the
composer (`ai_draft`). Whether or not the marker survives, the server
compares the reply with the drafts this ticket has been given: a public
reply that contains one of them (or most of one) is AI-assisted. Sending an
AI-assisted reply needs the ai_send capability; L1 technicians can keep the
text as an internal note or rewrite it in their own words.
"""
from __future__ import annotations

import re
from datetime import timedelta

from django.utils import timezone

MIN_MATCH = 60
WINDOW = timedelta(days=14)


def _norm(text):
    return re.sub(r'\s+', ' ', (text or '')).strip().lower()


def draft_sources(ticket):
    """Every AI draft this ticket has been given in the window, with where it
    came from: [(source, suggestion_id, job_id, index, text)]."""
    from psa_ai.models import AIDraftDecision as D, AISuggestion, AnalysisJob, AnalysisRun
    since = timezone.now() - WINDOW
    out = [(D.SOURCE_SUGGESTION, pk, None, None, body) for pk, body in
           AISuggestion.objects.filter(native_ticket=ticket, kind='reply', created_at__gte=since)
           .values_list('pk', 'suggested_body') if body]
    for job_id, result in AnalysisRun.objects.filter(job__ticket=ticket, status='succeeded',
                                                     finished_at__gte=since).values_list('job_id', 'result'):
        out += [(D.SOURCE_ANALYSIS, None, job_id, i, r.get('text', ''))
                for i, r in enumerate((result or {}).get('customer_replies') or []) if r.get('text')]
    # Rem0te's aggregated result carries its own copy of the drafts.
    for job_id, result in AnalysisJob.objects.filter(ticket=ticket, protocol=AnalysisJob.PROTOCOL_REM0TE,
                                                     updated_at__gte=since).values_list('pk', 'processor_result'):
        out += [(D.SOURCE_REM0TE, None, job_id, i, d.get('text', ''))
                for i, d in enumerate((result or {}).get('draft_replies') or [])
                if isinstance(d, dict) and d.get('text')]
    return out


def drafts_for(ticket):
    return [text for *_, text in draft_sources(ticket)]


def _sentences(text):
    return [s for s in re.split(r'(?<=[.!?])\s+', _norm(text)) if len(s) >= 25]


def _contains(reply, draft):
    d = _norm(draft)
    if len(d) >= MIN_MATCH and d in reply:
        return True
    sentences = _sentences(draft)
    if sentences:
        hits = sum(1 for s in sentences if s in reply)
        if hits >= 2 and hits * 2 >= len(sentences):
            return True
    return False


def is_ai_assisted(ticket, body, marker=''):
    if marker:
        return True
    reply = _norm(body)
    if len(reply) < MIN_MATCH:
        return False
    return any(_contains(reply, draft) for draft in drafts_for(ticket))


_MARKER = re.compile(r'^(suggestion):(\d+)$|^(job|rem0te):([0-9a-f-]{36}):(\d{1,3})$')


def match_draft(ticket, body, marker=''):
    """Which of this ticket's drafts `body` came from, for the history:
    (source, suggestion_id, job_id, index, unchanged) or None.

    The composer's marker is a hint only: it is honoured when it names a
    draft of this very ticket, otherwise the text decides. `unchanged` is
    True when the posted text is the draft, whitespace and case aside."""
    from psa_ai.models import AIDraftDecision as D
    sources = draft_sources(ticket)
    reply = _norm(body)
    m = _MARKER.match((marker or '').strip())
    if m:
        if m.group(1):
            want = (D.SOURCE_SUGGESTION, int(m.group(2)), None, None)
        else:
            want = (D.SOURCE_ANALYSIS if m.group(3) == 'job' else D.SOURCE_REM0TE, None, m.group(4),
                    int(m.group(5)))
        for src, sid, jid, idx, text in sources:
            if (src, sid, str(jid) if jid else None, idx) == want:
                return src, sid, jid, idx, _norm(text) == reply
    best = None
    for src, sid, jid, idx, text in sources:
        if _norm(text) == reply:
            return src, sid, jid, idx, True
        if best is None and len(reply) >= MIN_MATCH and _contains(reply, text):
            best = (src, sid, jid, idx, False)
    return best
