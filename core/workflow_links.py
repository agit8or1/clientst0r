"""Links between the sales records (v3.17.681, Phase 8 workflow E):
CRM opportunity -> quote -> contract -> client.

Each helper returns the URL of a related record's own page, or '' when that
page would refuse the user, using the page's own rule. A link never shows a
record the target page would not; the target page still checks again.

    client_url          accounts.views.organization_detail
                        (core.tenancy.accessible_org_ids or a membership)
    quote_url           psa.views.quote_detail (PSA on; the selected
                        customer's quotes)
    opportunity_links   crm.views.opportunity_detail (CRM on, MSP staff,
                        crm_view, crm.views._scope_qs)
    psa_contract_url    psa.views.contract_detail (PSA on; the selected
                        customer's contracts, or every one for MSP staff
                        with no customer selected)
    contract_doc_links  contracts.views.contract_detail
                        (contracts.permissions.scope)
"""
from __future__ import annotations

from django.urls import NoReverseMatch, reverse


def _url(name, *args):
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        return ''


def _org(request):
    from core.middleware import get_request_organization
    return get_request_organization(request)


def _psa_on():
    try:
        from psa.feature_flags import is_psa_enabled
        return bool(is_psa_enabled())
    except Exception:
        return False


def _staff(user):
    from psa.visibility import is_msp_staff
    return bool(is_msp_staff(user))


def client_url(request, org_id):
    if not org_id:
        return ''
    from accounts.models import Membership
    from core.tenancy import accessible_org_ids
    allowed = accessible_org_ids(request)
    if not (allowed is None or org_id in allowed
            or Membership.objects.filter(user=request.user, organization_id=org_id,
                                         is_active=True).exists()):
        return ''
    return _url('accounts:organization_detail', org_id)


def quote_url(request, quote):
    if quote is None or not _psa_on():
        return ''
    org = _org(request)
    if org is not None and quote.organization_id != org.pk:
        return ''
    return _url('psa:quote_detail', quote.pk)


def opportunity_links(request, quote):
    """[(name, url)] of the opportunities this quote was drafted from."""
    if quote is None or not _staff(request.user):
        return []
    from core.models import SystemSetting
    try:
        if not SystemSetting.get_settings().crm_enabled:
            return []
    except Exception:
        return []
    from accounts.permission_utils import user_has_perm
    if not user_has_perm(request.user, 'crm_view'):
        return []
    from crm.models import Opportunity
    from crm.views import _scope_qs
    rows = _scope_qs(request, Opportunity.objects.filter(quote=quote)).only('pk', 'name')[:5]
    return [(o.name, _url('crm:opportunity_detail', o.pk)) for o in rows]


def psa_contract_url(request, contract_id, contract_org_id):
    if not contract_id or not _psa_on():
        return ''
    org = _org(request)
    if org is not None:
        if contract_org_id != org.pk:
            return ''
    elif not (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
        return ''
    return _url('psa:contract_detail', contract_id)


def contract_doc_links(request, psa_contract):
    """[(label, url)] of the contract documents linked to this PSA contract
    that the user may open."""
    if psa_contract is None or not _staff(request.user):
        return []
    from contracts import permissions as cperms
    from contracts.models import ContractDocument
    qs = cperms.scope(ContractDocument.objects.filter(billing_contract=psa_contract), request.user)
    return [(f'{c.reference} {c.title}', _url('contracts:detail', c.pk))
            for c in qs.only('pk', 'reference', 'title').order_by('-created_at')[:5]]
