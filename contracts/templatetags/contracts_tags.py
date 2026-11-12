from django import template
from django.utils.html import format_html

from contracts.content import fmt_money

register = template.Library()

_BADGE = {
    'draft': 'secondary', 'pending_approval': 'warning', 'ready_to_send': 'info', 'sent': 'primary',
    'viewed': 'primary', 'partially_signed': 'warning', 'signed': 'success', 'declined': 'danger',
    'expired': 'dark', 'voided': 'dark', 'superseded': 'secondary',
    # invitation / version states
    'waiting': 'light', 'active': 'primary', 'revoked': 'dark', 'ready': 'info', 'rejected': 'danger',
}


@register.filter
def status_badge(obj):
    status = getattr(obj, 'status', obj)
    label = obj.get_status_display() if hasattr(obj, 'get_status_display') else str(status)
    color = _BADGE.get(status, 'secondary')
    text = ' text-dark' if color in ('warning', 'light', 'info') else ''
    return format_html('<span class="badge text-bg-{}{}">{}</span>', color, text, label)


@register.filter
def money(value, currency='USD'):
    return fmt_money(value or 0, currency or 'USD')


@register.filter
def get_item(d, key):
    try:
        return d.get(key)
    except AttributeError:
        return None


@register.inclusion_tag('contracts/_org_contracts.html', takes_context=True)
def org_contracts(context, organization):
    """Contracts card for a client record (empty for people who may not see contracts)."""
    from contracts import permissions as perms
    from contracts.models import ContractDocument
    request = context.get('request')
    user = getattr(request, 'user', None)
    if user is None or organization is None or not perms.has(user, perms.VIEW, organization.pk):
        return {'show': False}
    qs = ContractDocument.objects.filter(organization=organization).order_by('-updated_at')
    return {'show': True, 'organization': organization, 'contracts': qs[:8], 'count': qs.count(),
            'can_create': perms.has(user, perms.EDIT, organization.pk)}
