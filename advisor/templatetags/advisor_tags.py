"""Client workspace panel: the customer's open advisor findings (MSP staff
with the profitability permission only; empty for everyone else)."""
from django import template

register = template.Library()


@register.inclusion_tag('advisor/_org_advisor.html', takes_context=True)
def org_advisor(context, organization):
    request = context.get('request')
    user = getattr(request, 'user', None)
    from core.feature_gates import feature_on
    if not feature_on('reports_enabled'):  # the Pricing Advisor is part of Reports
        return {'show': False}
    from advisor import permissions as perms
    if user is None or organization is None or not perms.can_view_client(user, organization):
        return {'show': False}
    from advisor.models import Finding
    qs = Finding.objects.filter(client_org=organization, status='open')
    rows = sorted(qs, key=lambda f: (f.severity_rank, f.title))
    return {'show': True, 'organization': organization, 'findings': rows[:5], 'count': len(rows),
            'raised': sum(1 for f in rows if f.assessment == 'raised')}


@register.filter
def money(value):
    if value in (None, ''):
        return 'unknown'
    try:
        from decimal import Decimal
        return f'${Decimal(str(value)):,.2f}'
    except Exception:
        return value
