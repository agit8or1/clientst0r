"""Licensing pages (MSP staff only; see licensing.access)."""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core import csv_safe

from . import access
from .alerts import collect_alerts
from .forms import AssignmentForm, CustomerMapForm, SubscriptionForm
from .models import ExternalCustomerMap, LicenseAssignment, LicenseSubscription
from .sync import sync_all


def _audit(request, action, obj, description, organization=None):
    try:
        from audit.models import AuditLog
        AuditLog.log(
            user=request.user, action=action, organization=organization,
            object_type=obj._meta.model_name, object_id=obj.pk, object_repr=str(obj)[:255],
            description=description, ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500], path=request.path)
    except Exception:  # auditing must never break the action itself
        pass


def _subs_for(user, org=None):
    qs = LicenseSubscription.objects.select_related('organization', 'product').prefetch_related('assignments')
    if org is not None:
        return qs.filter(organization=org)
    allowed = access.viewable_org_ids(user)
    return qs if allowed is None else qs.filter(organization_id__in=allowed)


def _get_sub(request, pk, *, manage=False):
    sub = get_object_or_404(LicenseSubscription.objects.select_related('organization', 'product'), pk=pk)
    if not access.can_view(request.user, sub.organization):
        raise Http404
    if manage and not access.can_manage(request.user, sub.organization):
        raise PermissionDenied
    return sub


def _totals(subs):
    live = [s for s in subs if s.is_live]
    purchased = sum(s.quantity_purchased for s in live)
    assigned = sum(s.assigned for s in live)
    return {
        'subscriptions': len(live), 'purchased': purchased, 'assigned': assigned,
        'unused': sum(s.available for s in live if s.has_usage_data),
        'over': sum(s.over_allocated for s in live),
    }


# ---------------------------------------------------------------------------

@login_required
def overview(request):
    subs = list(_subs_for(request.user))
    by_org = {}
    for s in subs:
        by_org.setdefault(s.organization, []).append(s)
    rows = []
    for org, group in sorted(by_org.items(), key=lambda kv: kv[0].name.lower()):
        t = _totals(group)
        upcoming = sorted(s.renewal_date for s in group if s.is_live and s.renewal_date
                          and s.renewal_date >= timezone.localdate())
        rows.append({'org': org, 'next_renewal': upcoming[0] if upcoming else None, **t})
    alerts = collect_alerts(_subs_for(request.user))
    return render(request, 'licensing/overview.html', {
        'rows': rows, 'alerts': alerts[:50], 'alert_total': len(alerts), 'active': 'overview',
        'totals': _totals(subs),
    })


@login_required
def customer(request, org_id):
    org = access.get_viewable_org(request.user, org_id)
    subs = list(_subs_for(request.user, org))
    return render(request, 'licensing/customer.html', {
        'org': org, 'subs': subs, 'totals': _totals(subs),
        'alerts': collect_alerts(_subs_for(request.user, org)),
        'can_manage': access.can_manage(request.user, org),
        'can_cost': access.can_see_cost(request.user, org), 'active': 'overview',
    })


@login_required
def subscription_edit(request, org_id=None, pk=None):
    if pk:
        sub = _get_sub(request, pk, manage=True)
        org = sub.organization
    else:
        org = access.get_viewable_org(request.user, org_id)
        if not access.can_manage(request.user, org):
            raise PermissionDenied
        sub = None
    can_cost = access.can_see_cost(request.user, org)
    form = SubscriptionForm(request.POST or None, instance=sub, organization=org, can_see_cost=can_cost)
    if request.method == 'POST' and form.is_valid():
        obj = form.save()
        _audit(request, 'update' if sub else 'create', obj, f'License subscription {obj}', org)
        messages.success(request, 'Subscription saved.')
        return redirect('licensing:subscription_detail', pk=obj.pk)
    return render(request, 'licensing/subscription_form.html', {'form': form, 'org': org, 'sub': sub})


@login_required
def subscription_detail(request, pk):
    sub = _get_sub(request, pk)
    org = sub.organization
    return render(request, 'licensing/subscription_detail.html', {
        'sub': sub, 'org': org, 'assignments': sub.assignments.select_related('contact', 'asset'),
        'form': AssignmentForm(organization=org),
        'can_manage': access.can_manage(request.user, org),
        'can_cost': access.can_see_cost(request.user, org),
    })


@login_required
@require_POST
def subscription_delete(request, pk):
    sub = _get_sub(request, pk, manage=True)
    org = sub.organization
    _audit(request, 'delete', sub, f'License subscription {sub} deleted', org)
    sub.delete()
    messages.success(request, 'Subscription deleted.')
    return redirect('licensing:customer', org_id=org.pk)


@login_required
@require_POST
def assignment_add(request, pk):
    sub = _get_sub(request, pk, manage=True)
    form = AssignmentForm(request.POST, organization=sub.organization)
    if form.is_valid():
        a = form.save(commit=False)
        a.subscription = sub
        a.assigned_to = form.cleaned_data['assigned_to']
        a.save()
        _audit(request, 'create', a, f'License assigned to {a.assigned_to}', sub.organization)
        messages.success(request, 'Assignment added.')
        if sub.over_allocated:
            messages.warning(request, f'{sub.over_allocated} more assigned than purchased.')
    else:
        messages.error(request, ' '.join(e for errs in form.errors.values() for e in errs))
    return redirect('licensing:subscription_detail', pk=sub.pk)


@login_required
@require_POST
def assignment_delete(request, pk):
    a = get_object_or_404(LicenseAssignment.objects.select_related('subscription__organization'), pk=pk)
    sub = _get_sub(request, a.subscription_id, manage=True)
    _audit(request, 'delete', a, f'License assignment {a.assigned_to} removed', sub.organization)
    a.delete()
    messages.success(request, 'Assignment removed.')
    return redirect('licensing:subscription_detail', pk=sub.pk)


@login_required
@require_POST
def sync_now(request, org_id):
    org = access.get_viewable_org(request.user, org_id)
    if not access.can_manage(request.user, org):
        raise PermissionDenied
    results = sync_all(org)
    if not results:
        messages.info(request, 'This customer has no active Microsoft 365 connection to sync.')
    for r in results:
        (messages.error if r.errors else messages.success)(request, str(r))
    return redirect('licensing:customer', org_id=org.pk)


@login_required
def renewals(request):
    try:
        days = int(request.GET.get('days', 90))
    except ValueError:
        days = 90
    days = max(1, min(days, 730))
    today = timezone.localdate()
    org = None
    if request.GET.get('customer', '').isdigit():
        org = access.get_viewable_org(request.user, int(request.GET['customer']))
    subs = _subs_for(request.user, org).filter(
        status__in=LicenseSubscription.LIVE_STATUSES, renewal_date__isnull=False,
        renewal_date__gte=today, renewal_date__lte=today + timedelta(days=days)).order_by('renewal_date')
    return render(request, 'licensing/renewals.html', {
        'subs': subs, 'days': days, 'org': org, 'orgs': access.viewable_orgs(request.user),
        'active': 'renewals', 'can_cost_orgs': _cost_orgs(request.user, subs),
    })


def _cost_orgs(user, subs):
    cache = {}
    for s in subs:
        if s.organization_id not in cache:
            cache[s.organization_id] = access.can_see_cost(user, s.organization)
    return {k for k, v in cache.items() if v}


@login_required
def export_csv(request):
    org = None
    if request.GET.get('customer', '').isdigit():
        org = access.get_viewable_org(request.user, int(request.GET['customer']))
    subs = list(_subs_for(request.user, org))
    cost_orgs = _cost_orgs(request.user, subs)
    resp = HttpResponse(content_type='text/csv')
    resp['Content-Disposition'] = 'attachment; filename="licenses.csv"'
    w = csv_safe.writer(resp)
    header = ['Customer', 'Vendor', 'Product', 'SKU', 'Source', 'Status', 'Purchased', 'Assigned',
              'Unused', 'Over-allocated', 'Utilization %', 'Unit price', 'Currency', 'Billing',
              'Renewal date', 'Auto-renew']
    include_cost = bool(cost_orgs)
    if include_cost:
        header.insert(11, 'Unit cost')
    w.writerow(header)
    for s in subs:
        row = [s.organization.name, s.product.vendor, s.product.name, s.product.vendor_sku,
               s.get_source_display(), s.get_status_display(), s.quantity_purchased, s.assigned,
               s.available if s.has_usage_data else '', s.over_allocated,
               '' if s.utilization_pct is None else s.utilization_pct,
               '' if s.unit_price is None else s.unit_price, s.currency, s.get_billing_frequency_display(),
               s.renewal_date or '', 'yes' if s.auto_renew else 'no']
        if include_cost:
            cost = s.cost_for(s.organization_id in cost_orgs)
            row.insert(11, '' if cost is None else cost)
        w.writerow(row)
    return resp


@login_required
def mappings(request):
    orgs = access.viewable_orgs(request.user)
    maps = ExternalCustomerMap.objects.filter(organization__in=orgs).select_related('organization')
    form = CustomerMapForm(request.POST or None, organizations=orgs)
    if request.method == 'POST' and form.is_valid():
        org = form.cleaned_data['organization']
        if not access.can_manage(request.user, org):
            raise PermissionDenied
        obj = form.save()
        _audit(request, 'create', obj, f'License customer mapping {obj}', org)
        messages.success(request, 'Mapping saved.')
        return redirect('licensing:mappings')
    return render(request, 'licensing/mappings.html', {'maps': maps, 'form': form, 'active': 'mappings'})


@login_required
@require_POST
def mapping_delete(request, pk):
    m = get_object_or_404(ExternalCustomerMap.objects.select_related('organization'), pk=pk)
    if not access.can_view(request.user, m.organization):
        raise Http404
    if not access.can_manage(request.user, m.organization):
        raise PermissionDenied
    m.delete()
    messages.success(request, 'Mapping removed.')
    return redirect('licensing:mappings')
