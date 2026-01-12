"""
VLAN management views
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from core.middleware import get_request_organization
from core.decorators import require_write
from .models import VLAN
from .forms import VLANForm


@login_required
def vlan_list(request):
    """List all VLANs."""
    org = get_request_organization(request)
    vlans = VLAN.objects.filter(organization=org).order_by('vlan_id')

    return render(request, 'monitoring/vlan_list.html', {
        'vlans': vlans,
    })


@login_required
def vlan_detail(request, pk):
    """View VLAN details including associated subnets."""
    org = get_request_organization(request)
    vlan = get_object_or_404(VLAN, pk=pk, organization=org)

    # Get subnets assigned to this VLAN
    subnets = vlan.subnets.all()

    return render(request, 'monitoring/vlan_detail.html', {
        'vlan': vlan,
        'subnets': subnets,
    })


@login_required
@require_write
def vlan_create(request):
    """Create new VLAN."""
    org = get_request_organization(request)

    if request.method == 'POST':
        form = VLANForm(request.POST, organization=org)
        if form.is_valid():
            vlan = form.save(commit=False)
            vlan.organization = org
            vlan.save()
            messages.success(request, f'VLAN {vlan.vlan_id} - {vlan.name} created successfully.')
            return redirect('monitoring:vlan_detail', pk=vlan.pk)
    else:
        form = VLANForm(organization=org)

    return render(request, 'monitoring/vlan_form.html', {
        'form': form,
        'action': 'Create',
    })


@login_required
@require_write
def vlan_edit(request, pk):
    """Edit existing VLAN."""
    org = get_request_organization(request)
    vlan = get_object_or_404(VLAN, pk=pk, organization=org)

    if request.method == 'POST':
        form = VLANForm(request.POST, instance=vlan, organization=org)
        if form.is_valid():
            vlan = form.save()
            messages.success(request, f'VLAN {vlan.vlan_id} - {vlan.name} updated successfully.')
            return redirect('monitoring:vlan_detail', pk=vlan.pk)
    else:
        form = VLANForm(instance=vlan, organization=org)

    return render(request, 'monitoring/vlan_form.html', {
        'form': form,
        'vlan': vlan,
        'action': 'Edit',
    })


@login_required
@require_write
def vlan_delete(request, pk):
    """Delete VLAN."""
    org = get_request_organization(request)
    vlan = get_object_or_404(VLAN, pk=pk, organization=org)

    if request.method == 'POST':
        vlan_id = vlan.vlan_id
        name = vlan.name
        vlan.delete()
        messages.success(request, f'VLAN {vlan_id} - {name} deleted successfully.')
        return redirect('monitoring:vlan_list')

    return render(request, 'monitoring/vlan_confirm_delete.html', {
        'vlan': vlan,
    })
