from django import template

register = template.Library()


@register.inclusion_tag('tax/_document_panel.html', takes_context=True)
def tax_panel(context, document, doc_type):
    """Sales tax status / breakdown / actions for a quote or invoice page."""
    from accounts.permission_utils import user_has_org_perm
    from tax import services
    from tax.models import TaxSettings
    request = context.get('request')
    user = getattr(request, 'user', None)
    flag = 'billing_send_invoices' if doc_type == 'invoice' else 'crm_manage_pipeline'
    try:
        settings_row = services.settings_for(document.organization_id)
        mode = settings_row.mode if settings_row else TaxSettings.MODE_FLAT
        calc = services.current_calculation(document)
        stale = bool(calc and services.is_stale(document))
        lines = {li.pk: li for li in document.line_items.all()}
        breakdown = []
        for ln in (calc.line_breakdown if calc else []):
            li = lines.get(int(ln['number'])) if str(ln.get('number', '')).isdigit() else None
            breakdown.append(dict(ln, description=getattr(li, 'description', '')))
        cats = services.categories_for(document.organization_id)
        line_cats = [(li, services.resolve_line_category(li, document, cats)) for li in lines.values()]
        exemption = services.active_exemption(document.client_org, services.document_date(document),
                                              services.ship_to_for(document))
        error = ''
    except Exception as exc:  # the panel must never break the page
        settings_row, mode, calc, stale, breakdown, cats, line_cats, exemption = None, '?', None, False, [], {}, [], None
        error = exc.__class__.__name__
    can_edit = bool(user and user.is_authenticated and (
        user_has_org_perm(user, document.organization_id, flag)
        or user_has_org_perm(user, document.client_org_id, flag)))
    return {
        'request': request,
        'document': document, 'doc_type': doc_type, 'mode': mode,
        'mode_label': dict(TaxSettings.MODES).get(mode, mode),
        'calc': calc, 'stale': stale, 'breakdown': breakdown,
        'not_configured': mode == TaxSettings.MODE_NONE or (calc is not None and calc.status == 'not_configured')
                          or (mode == TaxSettings.MODE_FLAT and not document.tax_rate),
        'is_draft': services._document_applies(document),
        'can_edit': can_edit,
        'can_override': bool(user and services.may_manage_tax(user, document.organization_id)),
        'categories': sorted(cats.values(), key=lambda c: c.name),
        'line_cats': line_cats,
        'exemption': exemption,
        'history': services.calculation_history(document)[:5],
        'panel_error': error,
    }


@register.inclusion_tag('tax/_client_panel.html', takes_context=True)
def client_tax_panel(context, organization):
    from tax import services
    from tax.models import CustomerTaxExemption
    request = context.get('request')
    user = getattr(request, 'user', None)
    if not (user and services.may_manage_tax(user, organization)):
        return {'show': False}
    exemptions = list(CustomerTaxExemption.objects.filter(client=organization, is_active=True)[:5])
    return {'show': True, 'organization': organization, 'exemptions': exemptions}
