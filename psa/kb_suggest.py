"""Knowledge suggestions for a ticket, with no AI involved (roadmap 52.23).

Deterministic and always available. For a ticket it returns up to
MAX_SUGGESTIONS knowledge base articles and runbooks (processes), each with a
short plain-language reason. The rules, strongest first:

  alert kind    the ticket was opened from an alert (tag ``alert:<kind>``, set
                by the alert policy) and the article or runbook carries that
                kind as a tag or category name (a runbook's category too).
  ticket tag    a plain ticket tag equals an article tag or category name.
  asset type    the type of the ticket's primary or affected devices (for
                example "Printer") equals an article tag or category name.
  ticket type / queue
                the ticket type or queue name equals an article tag or
                category name (weakest named match).
  title words   shared words with the ticket subject; only a tie-break among
                articles that already matched on something above.

Access is decided here, never in the template. Only MSP staff get
suggestions. An article is offered only when it is published (not a draft, not
pending review, not archived), is not already linked to the ticket, and is
either one of this ticket's own customer's documents or a global article whose
audience includes this customer. Another customer's documents are never
queried. Runbooks follow the same published/archived rules and are the
customer's own or global.

Cost: a fixed handful of queries per call (affected devices, documents,
document tags, runbooks, runbook tags, already linked articles), independent
of how many articles exist.
"""
import re
from dataclasses import dataclass, field
from typing import List

from django.db.models import Q
from django.urls import reverse
from django.utils.text import slugify

MAX_SUGGESTIONS = 5
CANDIDATE_LIMIT = 60

W_ALERT = 40
W_TAG = 30
W_ASSET = 20
W_TYPE = 10
W_TITLE_EACH = 1
W_TITLE_MAX = 4

_WORD = re.compile(r'[a-z0-9]{4,}')
_STOP = frozenset('with that this from have your they there their what when will been were about into '
                  'issue ticket please error cannot'.split())


@dataclass
class Suggestion:
    kind: str                     # 'article' or 'runbook'
    title: str
    url: str
    score: int
    why: List[str] = field(default_factory=list)

    @property
    def reason(self):
        return '; '.join(self.why)


def _norm(value):
    return (value or '').strip().lower()


def _terms(ticket):
    """[(weight, label, kind_of_match, key)] describing what the ticket is about."""
    from .affected import ticket_assets
    from assets.custom_types import asset_type_label

    terms, seen = [], set()

    def add(weight, why, value):
        key = _norm(value)
        if key and (why, key) not in seen:
            seen.add((why, key))
            terms.append((weight, why, key))

    tags = [t for t in (ticket.tags or []) if isinstance(t, str)]
    alert_cat = ((ticket.custom_fields or {}).get('alert_policy') or {}).get('category')
    for t in tags:
        if t.lower().startswith('alert:'):
            add(W_ALERT, 'alert kind', t.split(':', 1)[1])
        elif t.lower() != 'alert':
            add(W_TAG, 'ticket tag', t)
    if alert_cat:
        add(W_ALERT, 'alert kind', alert_cat)
    for asset in ticket_assets(ticket):
        code = asset.asset_type
        for name in (code.replace('_', ' '), asset_type_label(code)):
            add(W_ASSET, 'asset type', name)
            if not _norm(name).endswith('s'):
                add(W_ASSET, 'asset type', _norm(name) + 's')   # "Printer" also finds a "Printers" tag
    add(W_TYPE, 'ticket type', ticket.ticket_type.name)
    add(W_TYPE, 'ticket queue', ticket.queue.name)
    return terms


def _db_filter(terms, cat='category', tag='tags'):
    q = Q()
    for _w, _why, key in terms:
        slug = slugify(key)
        q |= Q(**{f'{cat}__name__iexact': key}) | Q(**{f'{cat}__slug': slug})
        q |= Q(**{f'{tag}__name__iexact': key}) | Q(**{f'{tag}__slug': slug})
    return q


def _words(text):
    return {w for w in _WORD.findall(_norm(text)) if w not in _STOP}


def _evaluate(terms, subject_words, labels, title):
    """(score, why list) for an item described by lowercase labels (category
    name/slug, tag names/slugs, runbook category)."""
    best = {}
    for weight, why, key in terms:
        if key in labels or slugify(key) in labels:
            shown = key
            prev = best.get(why)
            if prev is None or weight > prev[0]:
                best[why] = (weight, shown)
    if not best:
        return 0, []
    score = sum(w for w, _ in best.values())
    why = [f'matches {name} {val}' for name, (_w, val) in
           sorted(best.items(), key=lambda kv: -kv[1][0])]
    shared = sorted(subject_words & _words(title))
    if shared:
        score += min(len(shared) * W_TITLE_EACH, W_TITLE_MAX)
        why.append('title shares: ' + ', '.join(shared[:3]))
    return score, why


def suggest_for_ticket(ticket, user, limit=MAX_SUGGESTIONS) -> List[Suggestion]:
    from psa.visibility import is_msp_staff
    if not is_msp_staff(user):
        return []
    terms = _terms(ticket)
    if not terms:
        return []
    from docs.models import Document, kb_audience_q
    from processes.models import Process
    from .models import TicketKBLink

    org = ticket.organization
    subject_words = _words(ticket.subject)
    linked = set(TicketKBLink.objects.filter(ticket=ticket).values_list('article_id', flat=True))
    if ticket.related_kb_article_id:
        linked.add(ticket.related_kb_article_id)
    if ticket.related_documentation_id:
        linked.add(ticket.related_documentation_id)

    out = []

    # Articles: this customer's own, or global articles shared with this customer.
    scope = Q(organization=org, is_global=False) | kb_audience_q(org)
    docs = (Document.objects.published().filter(is_template=False).filter(scope)
            .filter(_db_filter(terms)).exclude(pk__in=linked).distinct()
            .select_related('category').prefetch_related('tags')[:CANDIDATE_LIMIT])
    for d in docs:
        labels = set()
        if d.category_id:
            labels |= {_norm(d.category.name), d.category.slug}
        for t in d.tags.all():
            labels |= {_norm(t.name), t.slug}
        score, why = _evaluate(terms, subject_words, labels, d.title)
        if score:
            url = (reverse('docs:global_kb_detail', args=[d.slug]) if d.is_global
                   else reverse('docs:document_detail', args=[d.slug]))
            out.append(Suggestion('article', d.title, url, score, why))

    # Runbooks: this customer's own or global ones, matched by tag or category.
    cat_labels = {}
    for code, label in Process.CATEGORY_CHOICES:
        cat_labels[code] = {code, code.replace('_', ' '), _norm(label), slugify(label)}
    cat_q = Q()
    for _w, _why, key in terms:
        for code, ls in cat_labels.items():
            if key in ls or slugify(key) in ls:
                cat_q |= Q(category=code)
    procs = (Process.objects.filter(is_published=True, is_archived=False, is_template=False)
             .filter(Q(organization=org) | Q(is_global=True))
             .filter(cat_q | Q(tags__in=_tags_for(terms)))
             .distinct().prefetch_related('tags')[:CANDIDATE_LIMIT])
    for p in procs:
        labels = set(cat_labels.get(p.category, ()))
        for t in p.tags.all():
            labels |= {_norm(t.name), t.slug}
        score, why = _evaluate(terms, subject_words, labels, p.title)
        if score:
            out.append(Suggestion('runbook', p.title,
                                  reverse('processes:process_detail', args=[p.slug]), score, why))

    out.sort(key=lambda s: (-s.score, s.kind, s.title.lower()))
    return out[:limit]


def _tags_for(terms):
    from core.models import Tag
    q = Q()
    for _w, _why, key in terms:
        q |= Q(name__iexact=key) | Q(slug=slugify(key))
    return Tag.objects.filter(q).values('pk')
