"""{% load ai_troubleshoot %}{% ai_troubleshoot_panel ticket=ticket %} or
{% ai_troubleshoot_panel device=device %} — the AI Troubleshoot entry point
(templates/psa_ai/_troubleshoot_panel.html). Renders nothing when AI is off,
for anyone who isn't an MSP technician, or for a technician without access
to the record. Self-contained: a plain POST form plus links, no JS."""
import uuid

from django import template
from django.urls import reverse

register = template.Library()


def panel_context(user, ticket=None, device=None, next_url=''):
    from core.ai_gate import ai_features_enabled
    from psa_ai.models import TroubleshootSession
    from psa_ai.permissions import has_capability
    from psa_ai.services import troubleshoot
    from tech_access.resolver import is_technician
    hidden = {'show': False}
    if (ticket is None) == (device is None) or not ai_features_enabled() or not is_technician(user):
        return hidden
    if ticket is not None:
        if not has_capability(user, ticket.organization, 'view_output', ticket=ticket):
            return hidden
        start_url = reverse('psa_ai:troubleshoot_ticket', args=[ticket.ticket_number])
        recent = TroubleshootSession.objects.filter(ticket=ticket)
    else:
        if not troubleshoot.device_visible(user, device):
            return hidden
        start_url = reverse('psa_ai:troubleshoot_device', args=[device.pk])
        recent = TroubleshootSession.objects.filter(device=device, organization=device.organization)
    ok, reasons, chosen = troubleshoot.availability(user, ticket=ticket, device=device)
    multi_ok, multi_reasons, multi_plan = troubleshoot.availability(user, ticket=ticket, device=device, multi=True)
    return {
        'show': True, 'ticket': ticket, 'device': device, 'start_url': start_url, 'ok': ok, 'reasons': reasons,
        'models': [p.name for p, _ in chosen], 'multi_ok': multi_ok, 'multi_reasons': multi_reasons,
        'multi_models': [p.name for p, _ in multi_plan],
        'recent': [s for s in recent.select_related('actor').order_by('-created_at')[:3]],
        'key': uuid.uuid4().hex, 'next': next_url,
    }


@register.inclusion_tag('psa_ai/_troubleshoot_panel.html', takes_context=True)
def ai_troubleshoot_panel(context, ticket=None, device=None):
    request = context.get('request')
    user = getattr(request, 'user', None)
    out = panel_context(user, ticket=ticket, device=device,
                        next_url=getattr(request, 'get_full_path', lambda: '')())
    out['csrf_token'] = context.get('csrf_token')
    return out
