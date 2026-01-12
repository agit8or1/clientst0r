"""
Patch panel port configuration views.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from core.middleware import get_request_organization
from core.decorators import require_write
from .models import RackResource, Rack
import json


@login_required
def patch_panel_list(request):
    """List all patch panels."""
    org = get_request_organization(request)
    patch_panels = RackResource.objects.filter(
        rack__organization=org,
        resource_type='patch_panel'
    ).select_related('rack').order_by('rack__name', 'name')

    return render(request, 'monitoring/patch_panel_list.html', {
        'patch_panels': patch_panels,
    })


@login_required
def patch_panel_detail(request, pk):
    """View patch panel details with port configuration."""
    org = get_request_organization(request)
    patch_panel = get_object_or_404(
        RackResource.objects.select_related('rack', 'asset'),
        pk=pk,
        rack__organization=org,
        resource_type='patch_panel'
    )

    # Ensure port_configuration is initialized
    if not patch_panel.port_configuration:
        patch_panel.port_configuration = {'ports': []}

    return render(request, 'monitoring/patch_panel_detail.html', {
        'patch_panel': patch_panel,
    })


@login_required
@require_write
def patch_panel_create(request):
    """Create new patch panel."""
    org = get_request_organization(request)

    if request.method == 'POST':
        name = request.POST.get('name')
        rack_id = request.POST.get('rack')
        port_count = int(request.POST.get('port_count', 24))
        manufacturer = request.POST.get('manufacturer', '')
        model = request.POST.get('model', '')
        serial_number = request.POST.get('serial_number', '')
        rack_position = request.POST.get('rack_position')
        notes = request.POST.get('notes', '')

        # Determine rack units based on port count
        rack_units_map = {
            8: 1,
            12: 1,
            24: 1,
            48: 2,
        }
        rack_units = rack_units_map.get(port_count, 1)

        rack = get_object_or_404(Rack, pk=rack_id, organization=org)

        # Initialize port configuration
        ports = []
        for i in range(1, port_count + 1):
            ports.append({
                'port_number': i,
                'label': f'Port {i}',
                'destination': '',
                'cable_type': '',
                'notes': '',
                'status': 'available'
            })

        patch_panel = RackResource.objects.create(
            rack=rack,
            name=name,
            resource_type='patch_panel',
            manufacturer=manufacturer,
            model=model,
            serial_number=serial_number,
            port_count=port_count,
            rack_position=int(rack_position) if rack_position else None,
            rack_units=rack_units,
            port_configuration={'ports': ports},
            notes=notes
        )

        messages.success(request, f"Patch panel '{name}' created successfully.")
        return redirect('monitoring:patch_panel_detail', pk=patch_panel.pk)

    # Get racks for dropdown
    racks = Rack.objects.filter(organization=org).order_by('name')

    return render(request, 'monitoring/patch_panel_form.html', {
        'action': 'Create',
        'racks': racks,
    })


@login_required
@require_write
def patch_panel_edit(request, pk):
    """Edit patch panel configuration."""
    org = get_request_organization(request)
    patch_panel = get_object_or_404(
        RackResource,
        pk=pk,
        rack__organization=org,
        resource_type='patch_panel'
    )

    if request.method == 'POST':
        patch_panel.name = request.POST.get('name')
        patch_panel.manufacturer = request.POST.get('manufacturer', '')
        patch_panel.model = request.POST.get('model', '')
        patch_panel.serial_number = request.POST.get('serial_number', '')
        rack_position = request.POST.get('rack_position')
        patch_panel.rack_position = int(rack_position) if rack_position else None
        patch_panel.notes = request.POST.get('notes', '')

        # Update port configuration from JSON
        ports_json = request.POST.get('ports', '[]')
        try:
            ports = json.loads(ports_json)
            patch_panel.port_configuration = {'ports': ports}
        except json.JSONDecodeError:
            messages.error(request, "Invalid port configuration JSON")
            return redirect('monitoring:patch_panel_edit', pk=pk)

        patch_panel.save()

        messages.success(request, f"Patch panel '{patch_panel.name}' updated successfully.")
        return redirect('monitoring:patch_panel_detail', pk=patch_panel.pk)

    return render(request, 'monitoring/patch_panel_form.html', {
        'action': 'Edit',
        'patch_panel': patch_panel,
    })


@login_required
@require_write
def patch_panel_delete(request, pk):
    """Delete patch panel."""
    org = get_request_organization(request)
    patch_panel = get_object_or_404(
        RackResource,
        pk=pk,
        rack__organization=org,
        resource_type='patch_panel'
    )

    if request.method == 'POST':
        name = patch_panel.name
        patch_panel.delete()
        messages.success(request, f"Patch panel '{name}' deleted successfully.")
        return redirect('monitoring:patch_panel_list')

    return render(request, 'monitoring/patch_panel_confirm_delete.html', {
        'patch_panel': patch_panel,
    })


@login_required
def patch_panel_api_ports(request, pk):
    """API endpoint to get/update patch panel ports."""
    org = get_request_organization(request)
    patch_panel = get_object_or_404(
        RackResource,
        pk=pk,
        rack__organization=org,
        resource_type='patch_panel'
    )

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            ports = data.get('ports', [])
            patch_panel.port_configuration = {'ports': ports}
            patch_panel.save()
            return JsonResponse({'success': True, 'message': 'Ports updated'})
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    # Ensure port_configuration exists
    if not patch_panel.port_configuration:
        patch_panel.port_configuration = {'ports': []}

    return JsonResponse(patch_panel.port_configuration)


@login_required
@require_write
def patch_panel_quick_create(request):
    """Quick create multiple patch panels at once."""
    org = get_request_organization(request)

    if request.method == 'POST':
        rack_id = request.POST.get('rack')
        count = int(request.POST.get('count', 1))
        port_count = int(request.POST.get('port_count', 24))
        name_prefix = request.POST.get('name_prefix', 'PP')
        start_position = int(request.POST.get('start_position', 1))

        rack = get_object_or_404(Rack, pk=rack_id, organization=org)

        # Determine rack units based on port count
        rack_units_map = {8: 1, 12: 1, 24: 1, 48: 2}
        rack_units = rack_units_map.get(port_count, 1)

        created = 0
        current_position = start_position

        for i in range(count):
            # Initialize ports
            ports = []
            for j in range(1, port_count + 1):
                ports.append({
                    'port_number': j,
                    'label': f'Port {j}',
                    'destination': '',
                    'cable_type': '',
                    'notes': '',
                    'status': 'available'
                })

            RackResource.objects.create(
                rack=rack,
                name=f"{name_prefix}-{i+1:02d}",
                resource_type='patch_panel',
                port_count=port_count,
                rack_position=current_position,
                rack_units=rack_units,
                port_configuration={'ports': ports}
            )

            current_position += rack_units
            created += 1

        messages.success(request, f"Created {created} patch panels in {rack.name}.")
        return redirect('monitoring:patch_panel_list')

    racks = Rack.objects.filter(organization=org).order_by('name')

    return render(request, 'monitoring/patch_panel_quick_create.html', {
        'racks': racks,
    })
