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


def drafts_for(ticket):
    from psa_ai.models import AISuggestion, AnalysisRun
    since = timezone.now() - WINDOW
    out = [s for s in AISuggestion.objects.filter(native_ticket=ticket, kind='reply', created_at__gte=since)
           .values_list('suggested_body', flat=True) if s]
    for result in AnalysisRun.objects.filter(job__ticket=ticket, status='succeeded',
                                             finished_at__gte=since).values_list('result', flat=True):
        out += [r.get('text', '') for r in (result or {}).get('customer_replies') or [] if r.get('text')]
    # Rem0te's aggregated result carries its own copy of the drafts.
    from psa_ai.models import AnalysisJob
    for result in AnalysisJob.objects.filter(ticket=ticket, protocol=AnalysisJob.PROTOCOL_REM0TE,
                                             updated_at__gte=since).values_list('processor_result', flat=True):
        out += [d.get('text', '') for d in (result or {}).get('draft_replies') or []
                if isinstance(d, dict) and d.get('text')]
    return out


def _sentences(text):
    return [s for s in re.split(r'(?<=[.!?])\s+', _norm(text)) if len(s) >= 25]


def is_ai_assisted(ticket, body, marker=''):
    if marker:
        return True
    reply = _norm(body)
    if len(reply) < MIN_MATCH:
        return False
    for draft in drafts_for(ticket):
        d = _norm(draft)
        if len(d) >= MIN_MATCH and d in reply:
            return True
        sentences = _sentences(draft)
        if sentences:
            hits = sum(1 for s in sentences if s in reply)
            if hits >= 2 and hits * 2 >= len(sentences):
                return True
    return False
