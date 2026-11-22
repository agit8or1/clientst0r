"""Phase 102.8: Settings → Billing (core:settings_billing, /settings/billing/).

GET                     the settings, the overrides the user may manage and,
                        with ?customer=<id>[&contract=<id>], the effective
                        value of each setting for that customer / contract and
                        where it comes from.
POST action=save_global      install-wide values (every customer's reach)
POST action=save_override    a customer's or a contract's overrides (blank = inherit)
POST action=delete_override  remove one override row

Rules and permissions: psa.billing.config. Every change is audited.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .billing import config as cfg


def _customers(user):
    from core.models import Organization
    allowed = cfg.manageable_customers(user)
    qs = Organization.objects.filter(is_active=True).order_by('name')
    if allowed is not None:
        qs = qs.filter(pk__in=allowed)
    return qs


def _int(raw):
    raw = str(raw or '').strip()
    return int(raw) if raw.isdigit() else None


def _target(request, data):
    """(customer, contract or None) from customer / contract ids the user may
    manage; 404 otherwise."""
    from psa.models import Contract
    customer = get_object_or_404(_customers(request.user), pk=_int(data.get('customer')) or 0)
    contract = None
    if _int(data.get('contract')):
        contract = get_object_or_404(Contract.objects.filter(client_org=customer), pk=_int(data.get('contract')))
    return customer, contract


def _url(customer=None, contract=None):
    url = reverse('core:settings_billing')
    if customer is not None:
        url += f'?customer={customer.pk}' + (f'&contract={contract.pk}' if contract is not None else '')
    return url + '#effective'


@login_required
@require_http_methods(['GET', 'POST'])
def settings_billing(request):
    from core.models import SystemSetting
    from psa.models import BillingSettingOverride, Contract
    user = request.user
    if not cfg.can_view(user):
        raise Http404
    errors = []
    posted = None
    if request.method == 'POST':
        action = request.POST.get('action') or ''
        if action == 'save_global':
            try:
                changed = cfg.save_global(request.POST, actor=user, request=request)
            except cfg.SettingError as exc:
                errors.append(str(exc))
                posted = request.POST
            else:
                messages.success(request, f'Billing settings saved ({len(changed)} change(s)). '
                                          'Existing invoices are not changed.' if changed else 'Nothing changed.')
                return redirect('core:settings_billing')
        elif action in ('save_override', 'delete_override'):
            customer, contract = _target(request, request.POST)
            values = request.POST if action == 'save_override' else {}
            try:
                changed = cfg.save_override(customer, contract, values, actor=user,
                                            note=request.POST.get('note') or '', request=request)
            except cfg.SettingError as exc:
                messages.error(request, str(exc))
                return redirect(_url(customer, contract))
            except PermissionDenied:
                raise
            if action == 'delete_override':
                messages.success(request, 'Override removed; the inherited values apply.')
            else:
                messages.success(request, f'Overrides saved ({len(changed)} change(s)).' if changed
                                 else 'Nothing changed.')
            return redirect(_url(customer, contract))
        else:
            messages.error(request, 'Unknown action.')
            return redirect('core:settings_billing')

    ss = SystemSetting.get_settings()
    customers = _customers(user)
    customer = contract = None
    cid = _int(request.GET.get('customer'))
    if cid:
        customer = customers.filter(pk=cid).first()
        if customer is None:
            raise Http404
        kid = _int(request.GET.get('contract'))
        if kid:
            contract = Contract.objects.filter(client_org=customer, pk=kid).first()
            if contract is None:
                raise Http404
    rows = []
    for title, specs in cfg.sections():
        rows.append((title, [{
            'spec': s,
            'value': (posted.get(s.key, '') if posted is not None and s.kind != 'bool'
                      else (posted.get(s.key) in ('1', 'on') if posted is not None else None)),
            'stored': getattr(ss, s.key),
            'shown': cfg.display(s.key, getattr(ss, s.key)),
        } for s in specs]))
    effective = None
    current = {}
    if customer is not None:
        effective = list(cfg.resolve(customer, contract, ss=ss).values())
        row = BillingSettingOverride.objects.filter(
            scope_key=f'contract:{contract.pk}' if contract else f'customer:{customer.pk}').first()
        current = {k: cfg.form_value(k, getattr(row, k)) for k in cfg.OVERRIDABLE} if row else {}
        if row:
            current['note'] = row.note
    overrides = BillingSettingOverride.objects.select_related('client_org', 'contract')
    allowed = cfg.manageable_customers(user)
    if allowed is not None:
        overrides = overrides.filter(client_org_id__in=allowed)
    override_rows = [{'row': o, 'values': [(cfg.BY_KEY[k], cfg.display(k, getattr(o, k)))
                                           for k in cfg.OVERRIDABLE]} for o in overrides[:500]]
    return render(request, 'psa/billing_settings.html', {
        'sections': rows, 'errors': errors, 'can_edit_global': cfg.can_edit_global(user),
        'customers': customers, 'customer': customer, 'contract': contract,
        'contracts': (Contract.objects.filter(client_org=customer).order_by('name') if customer else []),
        'effective': effective, 'current': current,
        'override_specs': [cfg.BY_KEY[k] for k in cfg.OVERRIDABLE],
        'override_fields': [(cfg.BY_KEY[k], current.get(k, '')) for k in cfg.OVERRIDABLE],
        'override_rows': override_rows,
    })
