from django import template

register = template.Library()


@register.inclusion_tag('pulse/_org_pulse.html', takes_context=True)
def org_pulse(context, organization):
    """Pulse check trend for a client record: MSP staff only, and only while
    pulse checks are on. Last six sends that reached this organization."""
    from psa.visibility import is_msp_staff
    from pulse import results
    from pulse.models import PulseResponse, PulseSend
    from pulse.sending import pulse_enabled
    request = context.get('request')
    user = getattr(request, 'user', None)
    if organization is None or not is_msp_staff(user) or not pulse_enabled():
        return {'show': False}
    from core.tenancy import accessible_org_ids
    allowed = accessible_org_ids(request)
    if allowed is not None and organization.pk not in allowed:
        return {'show': False}
    sends = list(PulseSend.objects.filter(responses__organization=organization)
                 .select_related('pulse_check').distinct().order_by('-created_at')[:6])
    rows = []
    for s in sends:
        resp = list(PulseResponse.objects.filter(send=s, organization=organization).select_related('send'))
        rows.append({'send': s, 'summary': results.summarize(resp)})
    return {'show': True, 'organization': organization, 'rows': rows}


@register.filter
def posted_value(posted, qid):
    """The value posted for question `qid` (to redraw a form after an error)."""
    try:
        return posted.get(f'q_{qid}', '')
    except AttributeError:
        return ''


@register.simple_tag
def scale(lo, hi):
    return [str(i) for i in range(int(lo), int(hi) + 1)]
