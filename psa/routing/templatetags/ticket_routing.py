"""Staff-only routing panels for pages owned by other apps.

{% routing_ticket_panel ticket %}   ticket page: history + suggestion buttons
{% routing_settings_card %}         Settings → PSA: mode + links
Both render nothing for anyone who is not an MSP technician.
"""
from django import template

register = template.Library()


@register.inclusion_tag('ticket_routing/_ticket_panel.html', takes_context=True)
def routing_ticket_panel(context, ticket):
    request = context.get('request')
    user = getattr(request, 'user', None)
    from psa.visibility import is_msp_staff
    if ticket is None or not is_msp_staff(user):
        return {'show': False}
    from ..models import RoutingDecision
    from ..permissions import can_override
    decisions = list(RoutingDecision.objects.filter(ticket_id=ticket.pk)
                     .select_related('rule_version', 'previous_assignee', 'new_assignee',
                                     'previous_queue', 'new_queue', 'decided_by')[:20])
    from ..alert_policy import links_for_ticket
    alert_links = links_for_ticket(ticket)
    return {'show': bool(decisions or alert_links), 'decisions': decisions, 'ticket': ticket,
            'alert_links': alert_links[:10],
            'can_override': can_override(user), 'csrf_token': context.get('csrf_token'),
            'next': request.get_full_path() if request else ''}


@register.inclusion_tag('ticket_routing/_settings_card.html', takes_context=True)
def routing_settings_card(context):
    request = context.get('request')
    user = getattr(request, 'user', None)
    from ..models import MODE_CHOICES, CustomerRoutingSettings, RoutingRule, RoutingSettings
    from ..permissions import can_manage
    if not can_manage(user):
        return {'show': False}
    msp = RoutingSettings.load()
    return {'show': True, 'msp': msp, 'mode_choices': MODE_CHOICES,
            'override_count': CustomerRoutingSettings.objects.exclude(mode='inherit').count(),
            'active_rules': RoutingRule.objects.filter(is_active=True).count(),
            'csrf_token': context.get('csrf_token'),
            'next': request.get_full_path() if request else ''}
