"""
Port configuration views for network equipment.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from core.middleware import get_request_organization
from core.decorators import require_write
from .models import Asset, NetworkPortConfiguration, EquipmentModel
import json


@login_required
def port_config_list(request):
    """List all port configurations for the organization."""
    org = get_request_organization(request)
    configs = NetworkPortConfiguration.objects.filter(
        organization=org
    ).select_related('equipment_model', 'asset').order_by('-created_at')

    return render(request, 'assets/port_config_list.html', {
        'configs': configs,
    })


@login_required
def port_config_detail(request, pk):
    """View port configuration details."""
    org = get_request_organization(request)
    config = get_object_or_404(
        NetworkPortConfiguration.objects.select_related('equipment_model', 'asset'),
        pk=pk,
        organization=org
    )

    return render(request, 'assets/port_config_detail.html', {
        'config': config,
    })


@login_required
@require_write
def port_config_create(request):
    """Create new port configuration."""
    org = get_request_organization(request)

    if request.method == 'POST':
        equipment_model_id = request.POST.get('equipment_model')
        asset_id = request.POST.get('asset')
        configuration_name = request.POST.get('configuration_name')
        is_template = request.POST.get('is_template') == 'on'
        ports_json = request.POST.get('ports', '[]')
        vlans_json = request.POST.get('vlans', '[]')
        notes = request.POST.get('notes', '')

        try:
            ports = json.loads(ports_json)
            vlans = json.loads(vlans_json)
        except json.JSONDecodeError:
            messages.error(request, "Invalid JSON format for ports or VLANs")
            return redirect('assets:port_config_create')

        equipment_model = get_object_or_404(EquipmentModel, pk=equipment_model_id)
        asset = None
        if asset_id:
            asset = get_object_or_404(Asset, pk=asset_id, organization=org)

        config = NetworkPortConfiguration.objects.create(
            organization=org,
            equipment_model=equipment_model,
            asset=asset,
            configuration_name=configuration_name,
            ports=ports,
            vlans=vlans,
            notes=notes,
            is_template=is_template
        )

        messages.success(request, f"Port configuration '{configuration_name}' created successfully.")
        return redirect('assets:port_config_detail', pk=config.pk)

    # Get equipment models for dropdowns
    equipment_models = EquipmentModel.objects.filter(
        equipment_type__in=['switch', 'router', 'firewall'],
        is_active=True
    ).select_related('vendor').order_by('vendor__name', 'model_name')

    # Get assets with network equipment types
    assets = Asset.objects.filter(
        organization=org,
        asset_type__in=['network', 'server']
    ).order_by('name')

    return render(request, 'assets/port_config_form.html', {
        'action': 'Create',
        'equipment_models': equipment_models,
        'assets': assets,
    })


@login_required
@require_write
def port_config_edit(request, pk):
    """Edit existing port configuration."""
    org = get_request_organization(request)
    config = get_object_or_404(NetworkPortConfiguration, pk=pk, organization=org)

    if request.method == 'POST':
        configuration_name = request.POST.get('configuration_name')
        is_template = request.POST.get('is_template') == 'on'
        ports_json = request.POST.get('ports', '[]')
        vlans_json = request.POST.get('vlans', '[]')
        notes = request.POST.get('notes', '')

        try:
            ports = json.loads(ports_json)
            vlans = json.loads(vlans_json)
        except json.JSONDecodeError:
            messages.error(request, "Invalid JSON format for ports or VLANs")
            return redirect('assets:port_config_edit', pk=pk)

        config.configuration_name = configuration_name
        config.ports = ports
        config.vlans = vlans
        config.notes = notes
        config.is_template = is_template
        config.save()

        messages.success(request, f"Port configuration '{configuration_name}' updated successfully.")
        return redirect('assets:port_config_detail', pk=config.pk)

    return render(request, 'assets/port_config_form.html', {
        'action': 'Edit',
        'config': config,
    })


@login_required
@require_write
def port_config_delete(request, pk):
    """Delete port configuration."""
    org = get_request_organization(request)
    config = get_object_or_404(NetworkPortConfiguration, pk=pk, organization=org)

    if request.method == 'POST':
        name = config.configuration_name
        config.delete()
        messages.success(request, f"Port configuration '{name}' deleted successfully.")
        return redirect('assets:port_config_list')

    return render(request, 'assets/port_config_confirm_delete.html', {
        'config': config,
    })


@login_required
def port_config_api_ports(request, pk):
    """API endpoint to get/update ports for a configuration."""
    org = get_request_organization(request)
    config = get_object_or_404(NetworkPortConfiguration, pk=pk, organization=org)

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            config.ports = data.get('ports', [])
            config.save()
            return JsonResponse({'success': True, 'message': 'Ports updated'})
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    return JsonResponse({'ports': config.ports, 'vlans': config.vlans})


@login_required
def equipment_model_image_api(request, pk):
    """API endpoint to get equipment model image."""
    model = get_object_or_404(EquipmentModel, pk=pk)

    # Check if model has an image in custom_fields
    image_url = None
    if model.custom_fields and 'image_url' in model.custom_fields:
        image_url = model.custom_fields['image_url']

    # Generate placeholder image based on equipment type
    if not image_url:
        equipment_type = model.equipment_type
        placeholder_images = {
            'switch': '/static/img/equipment/switch-placeholder.svg',
            'router': '/static/img/equipment/router-placeholder.svg',
            'firewall': '/static/img/equipment/firewall-placeholder.svg',
            'server': '/static/img/equipment/server-placeholder.svg',
            'workstation': '/static/img/equipment/workstation-placeholder.svg',
            'laptop': '/static/img/equipment/laptop-placeholder.svg',
        }
        image_url = placeholder_images.get(equipment_type, '/static/img/equipment/generic-placeholder.svg')

    return JsonResponse({
        'image_url': image_url,
        'model_name': model.model_name,
        'vendor': model.vendor.name,
        'equipment_type': model.equipment_type,
    })
