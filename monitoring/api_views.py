"""
Monitoring API Views - REST endpoints for rack device management
"""
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.contrib.auth.decorators import login_required
from core.middleware import get_request_organization
from .models import Rack, RackDevice, RackResource
from assets.models import Asset
import json


@login_required
@require_http_methods(["GET"])
def rack_devices_list(request, pk):
    """
    GET /api/racks/<id>/devices/
    Return JSON list of all devices in rack.
    """
    org = get_request_organization(request)
    rack = get_object_or_404(Rack, pk=pk, organization=org)

    devices = rack.rack_devices.select_related('asset', 'equipment_model').all()

    devices_data = []
    for device in devices:
        devices_data.append({
            'id': device.id,
            'name': device.name,
            'start_unit': device.start_unit,
            'units': device.units,
            'end_unit': device.end_unit,
            'color': device.color,
            'power_draw_watts': device.power_draw_watts,
            'asset_id': device.asset_id,
            'asset_name': device.asset.name if device.asset else None,
            'notes': device.notes,
        })

    return JsonResponse({
        'success': True,
        'devices': devices_data,
        'rack': {
            'id': rack.id,
            'name': rack.name,
            'units': rack.units,
        }
    })


@login_required
@require_http_methods(["POST"])
def update_rack_device_position(request, pk):
    """
    POST /api/rack-devices/<id>/update-position/
    Update device position and/or size.
    Request body: {"start_unit": 15, "units": 2}
    """
    org = get_request_organization(request)
    device = get_object_or_404(RackDevice, pk=pk, rack__organization=org)

    try:
        data = json.loads(request.body)
        start_unit = int(data.get('start_unit', device.start_unit))
        units = int(data.get('units', device.units))

        # Validate units is positive
        if units < 1:
            return JsonResponse({
                'success': False,
                'error': 'Device must be at least 1U in height'
            }, status=400)

        # Calculate end unit
        end_unit = start_unit + units - 1

        # Validate bounds
        if start_unit < 1:
            return JsonResponse({
                'success': False,
                'error': f'Start unit must be at least 1'
            }, status=400)

        if end_unit > device.rack.units:
            return JsonResponse({
                'success': False,
                'error': f'Device extends beyond rack capacity (U{device.rack.units})'
            }, status=400)

        # Check for overlaps with other devices
        overlapping = RackDevice.objects.filter(
            rack=device.rack
        ).exclude(
            id=device.id
        ).filter(
            start_unit__lt=end_unit + 1,  # Other device starts before this one ends
        ).filter(
            start_unit__gte=start_unit - 100  # Rough filter for performance
        )

        # More precise overlap check
        for other in overlapping:
            other_end = other.start_unit + other.units - 1
            # Check if ranges overlap
            if not (end_unit < other.start_unit or start_unit > other_end):
                return JsonResponse({
                    'success': False,
                    'error': f'Device overlaps with "{other.name}" at U{other.start_unit}-U{other_end}'
                }, status=400)

        # Update device with transaction
        with transaction.atomic():
            device.start_unit = start_unit
            device.units = units
            device.save()

        return JsonResponse({
            'success': True,
            'device': {
                'id': device.id,
                'name': device.name,
                'start_unit': device.start_unit,
                'units': device.units,
                'end_unit': device.end_unit,
                'color': device.color,
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON in request body'
        }, status=400)
    except ValueError as e:
        return JsonResponse({
            'success': False,
            'error': f'Invalid value: {str(e)}'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Server error: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["PATCH"])
def rack_device_detail(request, pk):
    """
    PATCH /api/rack-devices/<id>/
    Partial update for any field (color, name, etc.)
    """
    org = get_request_organization(request)
    device = get_object_or_404(RackDevice, pk=pk, rack__organization=org)

    try:
        data = json.loads(request.body)

        # Allow updating specific fields
        allowed_fields = ['name', 'color', 'power_draw_watts', 'notes']

        with transaction.atomic():
            for field in allowed_fields:
                if field in data:
                    setattr(device, field, data[field])
            device.save()

        return JsonResponse({
            'success': True,
            'device': {
                'id': device.id,
                'name': device.name,
                'color': device.color,
                'power_draw_watts': device.power_draw_watts,
                'notes': device.notes,
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON in request body'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Server error: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def create_rack_device(request, pk):
    """
    POST /api/racks/<id>/devices/create/
    Create device from drag-and-drop.
    Request body: {"asset_id": 123, "start_unit": 10, "units": 1}
    """
    org = get_request_organization(request)
    rack = get_object_or_404(Rack, pk=pk, organization=org)

    try:
        data = json.loads(request.body)
        asset_id = data.get('asset_id')
        start_unit = int(data.get('start_unit'))
        units = int(data.get('units', 1))

        # Validate required fields
        if not asset_id:
            return JsonResponse({
                'success': False,
                'error': 'asset_id is required'
            }, status=400)

        # Get asset
        asset = get_object_or_404(Asset, pk=asset_id, organization=org)

        # Use asset's rack_units if available
        if asset.rack_units:
            units = asset.rack_units

        # Calculate end unit
        end_unit = start_unit + units - 1

        # Validate bounds
        if start_unit < 1 or end_unit > rack.units:
            return JsonResponse({
                'success': False,
                'error': f'Device position (U{start_unit}-U{end_unit}) is outside rack bounds (U1-U{rack.units})'
            }, status=400)

        # Check for overlaps
        overlapping = RackDevice.objects.filter(
            rack=rack,
            start_unit__lt=end_unit + 1,
        ).filter(
            start_unit__gte=start_unit - 100
        )

        for other in overlapping:
            other_end = other.start_unit + other.units - 1
            if not (end_unit < other.start_unit or start_unit > other_end):
                return JsonResponse({
                    'success': False,
                    'error': f'Position overlaps with "{other.name}" at U{other.start_unit}-U{other_end}'
                }, status=400)

        # Create device
        with transaction.atomic():
            device = RackDevice.objects.create(
                rack=rack,
                asset=asset,
                name=asset.name,
                start_unit=start_unit,
                units=units,
                power_draw_watts=asset.power_draw_watts if hasattr(asset, 'power_draw_watts') else None,
                color=data.get('color', '#0d6efd'),  # Default Bootstrap primary color
            )

        return JsonResponse({
            'success': True,
            'device': {
                'id': device.id,
                'name': device.name,
                'start_unit': device.start_unit,
                'units': device.units,
                'end_unit': device.end_unit,
                'color': device.color,
                'power_draw_watts': device.power_draw_watts,
                'asset_id': device.asset_id,
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON in request body'
        }, status=400)
    except ValueError as e:
        return JsonResponse({
            'success': False,
            'error': f'Invalid value: {str(e)}'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Server error: {str(e)}'
        }, status=500)

# ============================================================================
# Patch Panel Port Management API
# ============================================================================

@login_required
@require_http_methods(["GET"])
def patch_panel_ports_list(request, pk):
    """
    GET /api/patch-panels/<id>/ports/
    Return JSON list of all ports in patch panel.
    """
    org = get_request_organization(request)
    patch_panel = get_object_or_404(
        RackResource,
        pk=pk,
        rack__organization=org,
        resource_type__in=['patch_panel', 'fiber_panel', 'switch']
    )

    # Initialize port configuration if not exists
    if not patch_panel.port_configuration:
        patch_panel.port_configuration = {'ports': []}
        
    # Ensure ports list exists and has correct count
    ports = patch_panel.port_configuration.get('ports', [])
    port_count = patch_panel.port_count or 24  # Default to 24 if not set
    
    # Initialize ports if needed
    if len(ports) < port_count:
        for i in range(len(ports), port_count):
            ports.append({
                'port_number': i + 1,
                'label': f'Port {i + 1}',
                'status': 'available',
                'connected_to': None,
                'cable_color': '#0d6efd',
                'notes': ''
            })
        patch_panel.port_configuration['ports'] = ports
        patch_panel.save()

    return JsonResponse({
        'success': True,
        'patch_panel': {
            'id': patch_panel.id,
            'name': patch_panel.name,
            'port_count': port_count,
        },
        'ports': ports
    })


@login_required
@require_http_methods(["POST"])
def patch_panel_port_connect(request, pk, port_num):
    """
    POST /api/patch-panels/<id>/ports/<port_num>/connect/
    Connect a port to another location.
    Request body: {"connected_to": "Room 101", "cable_color": "#ff0000", "label": "Server A"}
    """
    org = get_request_organization(request)
    patch_panel = get_object_or_404(
        RackResource,
        pk=pk,
        rack__organization=org,
        resource_type__in=['patch_panel', 'fiber_panel', 'switch']
    )

    try:
        data = json.loads(request.body)
        port_num = int(port_num)

        # Validate port number
        if port_num < 1 or port_num > (patch_panel.port_count or 24):
            return JsonResponse({
                'success': False,
                'error': f'Invalid port number. Must be between 1 and {patch_panel.port_count or 24}'
            }, status=400)

        # Initialize or get port configuration
        if not patch_panel.port_configuration:
            patch_panel.port_configuration = {'ports': []}
        
        ports = patch_panel.port_configuration.get('ports', [])
        
        # Ensure port exists
        while len(ports) < port_num:
            ports.append({
                'port_number': len(ports) + 1,
                'label': f'Port {len(ports) + 1}',
                'status': 'available',
                'connected_to': None,
                'cable_color': '#0d6efd',
                'notes': ''
            })

        # Update port
        port_index = port_num - 1
        ports[port_index].update({
            'status': 'in-use',
            'connected_to': data.get('connected_to', ''),
            'cable_color': data.get('cable_color', '#0d6efd'),
            'label': data.get('label', ports[port_index].get('label', f'Port {port_num}')),
            'notes': data.get('notes', '')
        })

        patch_panel.port_configuration['ports'] = ports
        
        with transaction.atomic():
            patch_panel.save()

        return JsonResponse({
            'success': True,
            'port': ports[port_index]
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON in request body'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Server error: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def patch_panel_port_disconnect(request, pk, port_num):
    """
    POST /api/patch-panels/<id>/ports/<port_num>/disconnect/
    Disconnect a port.
    """
    org = get_request_organization(request)
    patch_panel = get_object_or_404(
        RackResource,
        pk=pk,
        rack__organization=org,
        resource_type__in=['patch_panel', 'fiber_panel', 'switch']
    )

    try:
        port_num = int(port_num)

        if not patch_panel.port_configuration:
            return JsonResponse({
                'success': False,
                'error': 'Patch panel has no port configuration'
            }, status=400)

        ports = patch_panel.port_configuration.get('ports', [])
        
        if port_num < 1 or port_num > len(ports):
            return JsonResponse({
                'success': False,
                'error': f'Invalid port number'
            }, status=400)

        # Update port
        port_index = port_num - 1
        ports[port_index].update({
            'status': 'available',
            'connected_to': None,
            'notes': ''
        })

        patch_panel.port_configuration['ports'] = ports
        
        with transaction.atomic():
            patch_panel.save()

        return JsonResponse({
            'success': True,
            'port': ports[port_index]
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Server error: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["PATCH"])
def patch_panel_port_update(request, pk, port_num):
    """
    PATCH /api/patch-panels/<id>/ports/<port_num>/
    Update port label, color, or notes.
    """
    org = get_request_organization(request)
    patch_panel = get_object_or_404(
        RackResource,
        pk=pk,
        rack__organization=org,
        resource_type__in=['patch_panel', 'fiber_panel', 'switch']
    )

    try:
        data = json.loads(request.body)
        port_num = int(port_num)

        if not patch_panel.port_configuration:
            patch_panel.port_configuration = {'ports': []}
        
        ports = patch_panel.port_configuration.get('ports', [])
        
        if port_num < 1 or port_num > len(ports):
            return JsonResponse({
                'success': False,
                'error': f'Invalid port number'
            }, status=400)

        # Update allowed fields
        port_index = port_num - 1
        allowed_fields = ['label', 'cable_color', 'notes']
        
        for field in allowed_fields:
            if field in data:
                ports[port_index][field] = data[field]

        patch_panel.port_configuration['ports'] = ports
        
        with transaction.atomic():
            patch_panel.save()

        return JsonResponse({
            'success': True,
            'port': ports[port_index]
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON in request body'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Server error: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["GET"])
def rack_resources_list(request, pk):
    """
    GET /api/racks/<id>/resources/
    Return JSON list of all rack resources (patch panels, switches, etc.) with positions.
    """
    org = get_request_organization(request)
    rack = get_object_or_404(Rack, pk=pk, organization=org)

    resources = rack.resources.filter(rack_position__isnull=False)

    resources_data = []
    for resource in resources:
        resources_data.append({
            'id': resource.id,
            'name': resource.name,
            'resource_type': resource.resource_type,
            'resource_type_display': resource.get_resource_type_display(),
            'rack_position': resource.rack_position,
            'port_count': resource.port_count,
            'color': '#9b59b6',  # Purple for resources
        })

    return JsonResponse({
        'success': True,
        'resources': resources_data
    })


@login_required
@require_http_methods(["POST"])
def update_device_board_position(request, pk):
    """
    POST /api/rack-devices/<id>/update-board-position/
    Update device position on wall-mounted board.
    Request body: {"x": 100, "y": 200, "width": 300, "height": 150}
    """
    org = get_request_organization(request)
    device = get_object_or_404(RackDevice, pk=pk, rack__organization=org)

    try:
        data = json.loads(request.body)
        x = int(data.get('x', device.board_position_x or 0))
        y = int(data.get('y', device.board_position_y or 0))
        width = int(data.get('width', device.board_width or 100))
        height = int(data.get('height', device.board_height or 100))

        # Validate positions are non-negative
        if x < 0 or y < 0 or width < 1 or height < 1:
            return JsonResponse({
                'success': False,
                'error': 'Invalid position or dimensions'
            }, status=400)

        # Update device
        with transaction.atomic():
            device.board_position_x = x
            device.board_position_y = y
            device.board_width = width
            device.board_height = height
            device.save()

        return JsonResponse({
            'success': True,
            'device': {
                'id': device.id,
                'name': device.name,
                'x': device.board_position_x,
                'y': device.board_position_y,
                'width': device.board_width,
                'height': device.board_height,
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON in request body'
        }, status=400)
    except ValueError as e:
        return JsonResponse({
            'success': False,
            'error': f'Invalid value: {str(e)}'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Server error: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def update_resource_board_position(request, pk):
    """
    POST /api/rack-resources/<id>/update-board-position/
    Update resource position on wall-mounted board.
    Request body: {"x": 100, "y": 200, "width": 300, "height": 150}
    """
    org = get_request_organization(request)
    resource = get_object_or_404(RackResource, pk=pk, rack__organization=org)

    try:
        data = json.loads(request.body)
        x = int(data.get('x', resource.board_position_x or 0))
        y = int(data.get('y', resource.board_position_y or 0))
        width = int(data.get('width', resource.board_width or 100))
        height = int(data.get('height', resource.board_height or 100))

        # Validate positions
        if x < 0 or y < 0 or width < 1 or height < 1:
            return JsonResponse({
                'success': False,
                'error': 'Invalid position or dimensions'
            }, status=400)

        # Update resource
        with transaction.atomic():
            resource.board_position_x = x
            resource.board_position_y = y
            resource.board_width = width
            resource.board_height = height
            resource.save()

        return JsonResponse({
            'success': True,
            'resource': {
                'id': resource.id,
                'name': resource.name,
                'resource_type': resource.resource_type,
                'x': resource.board_position_x,
                'y': resource.board_position_y,
                'width': resource.board_width,
                'height': resource.board_height,
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON in request body'
        }, status=400)
    except ValueError as e:
        return JsonResponse({
            'success': False,
            'error': f'Invalid value: {str(e)}'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Server error: {str(e)}'
        }, status=500)
