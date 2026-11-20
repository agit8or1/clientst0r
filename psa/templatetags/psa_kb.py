from django import template

register = template.Library()


@register.simple_tag
def kb_suggestions(ticket, user):
    """Deterministic knowledge suggestions for the ticket page (psa.kb_suggest)."""
    from psa.kb_suggest import suggest_for_ticket
    try:
        return suggest_for_ticket(ticket, user)
    except Exception:  # a suggestion card must never break the ticket page
        import logging
        logging.getLogger(__name__).exception('kb suggestions failed for %s', getattr(ticket, 'pk', '?'))
        return []
