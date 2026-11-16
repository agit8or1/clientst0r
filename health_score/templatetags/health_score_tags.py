from django import template

register = template.Library()


@register.inclusion_tag('health_score/_panel.html', takes_context=True)
def client_health_panel(context, organization):
    """Health panel for the client workspace overview. MSP staff with access
    to the client only (a customer user gets nothing); shows the last stored
    snapshot and never computes on page view."""
    from health_score import permissions, present, scoring
    request = context.get('request')
    if request is None or organization is None or not permissions.can_view_client(request, organization):
        return {'show': False}
    snap = scoring.latest_snapshot(organization)
    return {'show': True, 'client': organization,
            'p': present.present(snap, request.user, organization) if snap else None}
