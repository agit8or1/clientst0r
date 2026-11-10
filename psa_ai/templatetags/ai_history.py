"""{% ai_history_panel ticket %} — the ticket's staff-only AI and automation
history (services/history.py). Renders nothing for anyone who is not an MSP
technician; never used by the customer portal."""
from django import template

register = template.Library()


@register.inclusion_tag('psa_ai/_ticket_history.html', takes_context=True)
def ai_history_panel(context, ticket):
    request = context.get('request')
    from psa_ai.services.history import build
    return build(ticket, getattr(request, 'user', None))
