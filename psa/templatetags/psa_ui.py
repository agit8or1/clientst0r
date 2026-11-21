"""Presentation helpers for the PSA templates.

These map *configured* semantics onto the shared badge tones in ui.css. They
deliberately read the operator's own data — TicketStatus.is_terminal,
TicketStatus.pauses_sla, TicketPriority.sort_order — rather than pattern
matching on names like "P1" or "Closed", which are free text an operator is
free to change.
"""
from django import template

register = template.Library()


@register.filter
def status_tone(status):
    """Tone for a TicketStatus, from its configuration.

    terminal  -> done     (resolved / closed / cancelled-style states)
    pauses SLA-> warn     (waiting on somebody, clock stopped)
    otherwise -> open     (live work)

    Anything unrecognised falls back to a neutral chip rather than guessing.
    """
    if status is None:
        return 'neutral'
    if getattr(status, 'is_terminal', False):
        return 'done'
    if getattr(status, 'pauses_sla', False):
        return 'warn'
    return 'open'


_PRIORITY_ORDER_KEY = ('psa_priority_order',)


def _read_priority_order():
    from psa.models import TicketPriority
    return list(TicketPriority.objects.order_by('sort_order', 'id').values_list('id', flat=True))


def _priority_order():
    """Priority ids by rank, read once per request (a ticket list asks for
    every row); a priority save or delete drops it (_forget_priority_order)."""
    from accounts import authz_cache
    return authz_cache.memo(_PRIORITY_ORDER_KEY, _read_priority_order)


def _forget_priority_order(*_args, **_kwargs):
    from accounts import authz_cache
    authz_cache.forget(_PRIORITY_ORDER_KEY)


def _connect_priority_signals():
    from django.db.models.signals import post_delete, post_save

    from psa.models import TicketPriority
    post_save.connect(_forget_priority_order, sender=TicketPriority, dispatch_uid='psa_ui_priority_order_save')
    post_delete.connect(_forget_priority_order, sender=TicketPriority, dispatch_uid='psa_ui_priority_order_delete')


_connect_priority_signals()


@register.filter
def priority_tone(priority):
    """Tone for a TicketPriority, from where it sits in the operator's own set.

    Rank is taken from sort_order across the configured priorities, so an
    install that renamed or re-ordered its priorities still gets sensible
    emphasis. The top-ranked priority reads as danger, the second as warn, and
    everything below that stays neutral — urgency is not inferred from the
    code string.
    """
    if priority is None:
        return 'neutral'
    order = _priority_order()
    try:
        rank = order.index(priority.id)
    except (ValueError, AttributeError):
        return 'neutral'
    if rank == 0:
        return 'danger'
    if rank == 1:
        return 'warn'
    return 'neutral'


@register.filter
def priority_label(priority):
    """Readable priority text: the name, with the short code as support.

    Falls back to the code alone when no name is configured.
    """
    if priority is None:
        return ''
    name = (getattr(priority, 'name', '') or '').strip()
    return name or getattr(priority, 'code', '')


@register.simple_tag(takes_context=True)
def ticket_query_without(context, *drop, **override):
    """The current query string minus ``drop`` keys, with ``override`` set
    (empty values removed): links that change one filter and keep the rest
    (the ticket list's SLA chips). urlencode escapes every value."""
    from urllib.parse import urlencode
    request = context.get('request')
    params = request.GET.copy() if request is not None else {}
    pairs = [(k, v) for k in params for v in params.getlist(k)
             if k not in drop and k not in override and v != '']
    pairs += [(k, str(v)) for k, v in override.items() if v not in ('', None)]
    return urlencode(pairs)


@register.filter
def count_for(counts, key):
    """counts[key] for a dict of counts; '' when missing."""
    try:
        return counts.get(key, '')
    except AttributeError:
        return ''
