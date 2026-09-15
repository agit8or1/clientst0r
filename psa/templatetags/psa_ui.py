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
    from psa.models import TicketPriority

    order = list(
        TicketPriority.objects.order_by('sort_order', 'id').values_list('id', flat=True)
    )
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
