"""Customer operations pages (see core/customer_ops.py for the rules)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from . import customer_ops as ops
from .models import Organization


def _customer_or_404(request, org_id):
    org = get_object_or_404(Organization, pk=org_id)
    if not ops.can_open_customer(request, org):
        raise Http404
    return org


def _follow_customer(request, org):
    """Make the session's current customer this one, so the action links
    (asset, monitor, invoice pages scoped to the current customer) open the
    right record. Same steps and rule as core.org_handoff. Global View is
    left alone: from there every link already works."""
    current = getattr(request, 'current_organization', None)
    if current is None or current.pk == org.pk:
        return
    from .client_switcher import authorized_organizations
    from .org_handoff import switch_session_org
    if authorized_organizations(request).filter(pk=org.pk).exists():
        switch_session_org(request, org)
        messages.info(request, f'Switched to {org.name}.')


@login_required
def customer_ops_current(request):
    """The current customer's operations page; without one, a short picker."""
    org = getattr(request, 'current_organization', None)
    if org is not None and ops.can_open_customer(request, org):
        return redirect('core:customer_ops', org_id=org.pk)
    from .client_switcher import authorized_organizations
    customers = authorized_organizations(request).order_by('name')
    return render(request, 'core/customer_ops_pick.html', {
        'customers': customers[:50],
        'more': customers.count() > 50,
    })


@login_required
def customer_ops(request, org_id):
    org = _customer_or_404(request, org_id)
    _follow_customer(request, org)
    sections = ops.build(request, org)
    return render(request, 'core/customer_ops.html', {
        'organization': org,
        'sections': sections,
        'hidden_any': len(sections) < len(ops.SECTION_ORDER),
        'is_msp_staff': ops.is_msp_staff(request.user),
    })


@login_required
def customer_ops_section(request, org_id, section):
    org = _customer_or_404(request, org_id)
    if section not in ops.SECTION_ORDER:
        raise Http404
    built = ops.build_section(request, org, section)
    if built is None:
        raise PermissionDenied('Your role does not include this section for this customer.')
    _follow_customer(request, org)
    return render(request, 'core/customer_ops_section.html', {
        'organization': org,
        'section': built,
    })
