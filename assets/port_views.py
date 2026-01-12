"""
Port configuration views for network equipment
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from core.middleware import get_request_organization
from core.decorators import require_write
from .models import Asset
from monitoring.models import VLAN
import json


@login_required
def asset_port_config(request, pk):
    """Configure ports for switches, routers, firewalls, patch panels."""
    org = get_request_organization(request)
    asset = get_object_or_404(Asset, pk=pk, organization=org)

    # Check if asset supports ports
    if not asset.has_ports():
        messages.error(request, f"Asset type '{asset.get_asset_type_display()}' does not support port configuration.")
        return redirect('assets:asset_detail', pk=asset.pk)

    # Get available VLANs for this organization
    vlans = VLAN.objects.filter(organization=org).order_by('vlan_id')

    # Initialize ports if not yet configured
    if not asset.ports and asset.port_count:
        port_type = 'patch_panel' if asset.asset_type in ['patch_panel', 'fiber_panel'] else 'switch'
        asset.initialize_ports(asset.port_count, port_type)
        asset.save()

    return render(request, 'assets/asset_port_config.html', {
        'asset': asset,
        'vlans': vlans,
        'is_patch_panel': asset.asset_type in ['patch_panel', 'fiber_panel'],
    })


@login_required
@require_write
def asset_port_config_save(request, pk):
    """Save port configuration via AJAX."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    org = get_request_organization(request)
    asset = get_object_or_404(Asset, pk=pk, organization=org)

    if not asset.has_ports():
        return JsonResponse({'error': 'Asset does not support ports'}, status=400)

    try:
        # Parse JSON data
        data = json.loads(request.body)
        ports = data.get('ports', [])
        vlans = data.get('vlans', [])

        # Update asset
        asset.ports = ports
        asset.vlans = vlans
        asset.save()

        messages.success(request, f"Port configuration for '{asset.name}' saved successfully.")
        return JsonResponse({'success': True, 'message': 'Configuration saved'})

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
