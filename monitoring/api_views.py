"""
Monitoring API Views - REST endpoints for rack device management
"""
import logging
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_http_methods
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.db.models import Q
from django.contrib.auth.decorators import login_required
from core.middleware import get_request_organization
from core.tenancy import get_org_object_or_404
from .models import Rack, RackDevice, RackResource, RackConnection

logger = logging.getLogger('monitoring')


def _api_get_rack(pk, org):
    """get_object_or_404 for Rack, skipping org filter in global view."""
    if org:
        return get_object_or_404(Rack, pk=pk, organization=org)
    return get_object_or_404(Rack, pk=pk)
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
    rack = _api_get_rack(pk, org)

    devices = rack.rack_devices.select_related('asset', 'equipment_model').all()

    devices_data = []
    for device in devices:
        # Get equipment image if available
        equipment_image_url = None
        if device.asset and device.asset.equipment_model:
            image = device.asset.equipment_model.get_primary_image()
            if image:
                equipment_image_url = f'/files/attachments/{image.id}/'

        asset = device.asset
        devices_data.append({
            'id': device.id,
            'name': device.name,
            'start_unit': device.start_unit,
            'units': device.units,
            'end_unit': device.end_unit,
            'color': device.color,
            'power_draw_watts': device.power_draw_watts,
            'asset_id': device.asset_id,
            'asset_name': asset.name if asset else None,
            'asset_type': asset.asset_type if asset else 'other',
            'asset_type_display': asset.get_asset_type_display() if asset else None,
            'ip_address': str(asset.ip_address) if asset and asset.ip_address else None,
            'hostname': asset.hostname if asset else None,
            'serial_number': asset.serial_number if asset else None,
            'mac_address': asset.mac_address if asset else None,
            'port_count': asset.port_count if asset else None,
            'equipment_image_url': equipment_image_url,
            'board_position_x': device.board_position_x,
            'board_position_y': device.board_position_y,
            'board_width': device.board_width,
            'board_height': device.board_height,
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
    if request.content_type != 'application/json':
        return JsonResponse({'error': 'JSON required'}, status=400)
    org = get_request_organization(request)
    device = get_object_or_404(RackDevice, pk=pk) if not org else get_object_or_404(RackDevice, pk=pk, rack__organization=org)

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
            'error': 'Invalid value'
        }, status=400)
    except Http404:
        # A scoped lookup refusing another tenant's row is a 404, not a server
        # error. Without this the blanket handler below turns every refusal
        # into a 500 and logs a traceback for it.
        raise
    except Exception:
        logger.exception('API view error')
        return JsonResponse({
            'success': False,
            'error': 'An error occurred'
        }, status=500)


@login_required
@require_http_methods(["PATCH", "DELETE"])
def rack_device_detail(request, pk):
    """
    PATCH  /api/rack-devices/<id>/  — partial update
    DELETE /api/rack-devices/<id>/  — remove device from rack/board
    """
    org = get_request_organization(request)
    device = get_object_or_404(RackDevice, pk=pk) if not org else get_object_or_404(RackDevice, pk=pk, rack__organization=org)

    if request.method == 'DELETE':
        name = device.name
        device.delete()
        return JsonResponse({'success': True, 'deleted': name})

    try:
        data = json.loads(request.body)

        # Allow updating specific fields
        allowed_fields = ['name', 'color', 'power_draw_watts', 'notes', 'start_unit', 'units']

        with transaction.atomic():
            for field in allowed_fields:
                if field in data:
                    setattr(device, field, data[field])

            # Handle asset_id separately (foreign key)
            if 'asset_id' in data:
                asset_id = data['asset_id']
                if asset_id:
                    asset = get_org_object_or_404(Asset, org, pk=asset_id) if org else get_object_or_404(Asset, pk=asset_id)
                    device.asset = asset
                else:
                    device.asset = None

            device.save()

        return JsonResponse({
            'success': True,
            'device': {
                'id': device.id,
                'name': device.name,
                'color': device.color,
                'power_draw_watts': device.power_draw_watts,
                'notes': device.notes,
                'start_unit': device.start_unit,
                'units': device.units,
                'asset_id': device.asset_id,
                'asset_name': device.asset.name if device.asset else None,
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON in request body'
        }, status=400)
    except Http404:
        # A scoped lookup refusing another tenant's row is a 404, not a server
        # error. Without this the blanket handler below turns every refusal
        # into a 500 and logs a traceback for it.
        raise
    except Exception:
        logger.exception('API view error')
        return JsonResponse({
            'success': False,
            'error': 'An error occurred'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def create_rack_device(request, pk):
    """
    POST /api/racks/<id>/devices/create/
    Create device from drag-and-drop.
    Request body: {"asset_id": 123, "start_unit": 10, "units": 1}
    """
    if request.content_type != 'application/json':
        return JsonResponse({'error': 'JSON required'}, status=400)
    org = get_request_organization(request)
    rack = _api_get_rack(pk, org)

    try:
        data = json.loads(request.body)
        asset_id   = data.get('asset_id')
        start_unit = data.get('start_unit')
        units      = int(data.get('units', 1))
        board_only = start_unit is None  # board-only drop — no rack unit needed

        if not asset_id:
            return JsonResponse({'success': False, 'error': 'asset_id is required'}, status=400)

        # Get asset — skip org filter in global view mode
        asset = get_org_object_or_404(Asset, org, pk=asset_id) if org else get_object_or_404(Asset, pk=asset_id)

        if asset.rack_units:
            units = asset.rack_units

        if board_only:
            # Find first unused start_unit (board devices still need a unique slot)
            used = set(RackDevice.objects.filter(rack=rack).values_list('start_unit', flat=True))
            start_unit = 1
            while start_unit in used:
                start_unit += 1
        else:
            start_unit = int(start_unit)
            end_unit   = start_unit + units - 1

            if start_unit < 1 or end_unit > rack.units:
                return JsonResponse({
                    'success': False,
                    'error': f'Device position (U{start_unit}-U{end_unit}) is outside rack bounds (U1-U{rack.units})'
                }, status=400)

            # Check for overlaps
            overlapping = RackDevice.objects.filter(rack=rack, start_unit__lt=end_unit + 1,
                                                    start_unit__gte=start_unit - 100)
            for other in overlapping:
                other_end = other.start_unit + other.units - 1
                if not (end_unit < other.start_unit or start_unit > other_end):
                    return JsonResponse({
                        'success': False,
                        'error': f'Position overlaps with "{other.name}" at U{other.start_unit}-U{other_end}'
                    }, status=400)

        # Create device, saving board position if provided
        with transaction.atomic():
            device = RackDevice.objects.create(
                rack=rack,
                asset=asset,
                name=asset.name,
                start_unit=start_unit,
                units=units,
                power_draw_watts=getattr(asset, 'power_draw_watts', None),
                color=data.get('color', '#0d6efd'),
                board_position_x=data.get('board_position_x') or 0,
                board_position_y=data.get('board_position_y') or 0,
                board_width=data.get('board_width') or 150,
                board_height=data.get('board_height') or 100,
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
                'asset_type': asset.asset_type,
                'port_count': asset.port_count,
                'board_position_x': device.board_position_x,
                'board_position_y': device.board_position_y,
                'board_width': device.board_width,
                'board_height': device.board_height,
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
            'error': 'Invalid value'
        }, status=400)
    except Http404:
        # A scoped lookup refusing another tenant's row is a 404, not a server
        # error. Without this the blanket handler below turns every refusal
        # into a 500 and logs a traceback for it.
        raise
    except Exception:
        logger.exception('API view error')
        return JsonResponse({
            'success': False,
            'error': 'An error occurred'
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
    if request.content_type != 'application/json':
        return JsonResponse({'error': 'JSON required'}, status=400)
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
    except Http404:
        # A scoped lookup refusing another tenant's row is a 404, not a server
        # error. Without this the blanket handler below turns every refusal
        # into a 500 and logs a traceback for it.
        raise
    except Exception:
        logger.exception('API view error')
        return JsonResponse({
            'success': False,
            'error': 'An error occurred'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def patch_panel_port_disconnect(request, pk, port_num):
    """
    POST /api/patch-panels/<id>/ports/<port_num>/disconnect/
    Disconnect a port.
    """
    if request.content_type != 'application/json':
        return JsonResponse({'error': 'JSON required'}, status=400)
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

    except Http404:
        # A scoped lookup refusing another tenant's row is a 404, not a server
        # error. Without this the blanket handler below turns every refusal
        # into a 500 and logs a traceback for it.
        raise
    except Exception:
        logger.exception('API view error')
        return JsonResponse({
            'success': False,
            'error': 'An error occurred'
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
    except Http404:
        # A scoped lookup refusing another tenant's row is a 404, not a server
        # error. Without this the blanket handler below turns every refusal
        # into a 500 and logs a traceback for it.
        raise
    except Exception:
        logger.exception('API view error')
        return JsonResponse({
            'success': False,
            'error': 'An error occurred'
        }, status=500)


# ============================================================================
# Rack Device Port Management API
# ============================================================================

@login_required
@require_http_methods(["GET"])
def rack_device_ports_list(request, pk):
    """
    GET /api/rack-devices/<id>/ports/
    Return JSON list of all ports for the linked asset.
    """
    org = get_request_organization(request)
    device = get_object_or_404(RackDevice, pk=pk)
    if org and device.rack.organization != org:
        from django.http import Http404
        raise Http404

    if not device.asset:
        return JsonResponse({'success': False, 'error': 'This device has no linked asset'}, status=404)

    asset = device.asset

    # Initialize ports if asset has port_count but no ports configured yet
    if not asset.ports and asset.port_count:
        asset.initialize_ports(asset.port_count, asset.asset_type)
        asset.save(update_fields=['ports', 'port_count'])

    return JsonResponse({
        'success': True,
        'device': {
            'id': device.id,
            'name': device.name,
            'asset_id': asset.id,
            'asset_name': asset.name,
            'asset_type': asset.asset_type,
            'port_count': asset.port_count or len(asset.ports or []),
        },
        'ports': asset.ports or [],
    })


@login_required
@require_http_methods(["PATCH"])
def rack_device_port_update(request, pk, port_num):
    """
    PATCH /api/rack-devices/<id>/ports/<port_num>/
    Update a single port's configuration on the linked asset.
    """
    org = get_request_organization(request)
    device = get_object_or_404(RackDevice, pk=pk)
    if org and device.rack.organization != org:
        from django.http import Http404
        raise Http404

    if not device.asset:
        return JsonResponse({'success': False, 'error': 'No linked asset'}, status=404)

    try:
        data = json.loads(request.body)
        port_num = int(port_num)
        asset = device.asset
        ports = list(asset.ports or [])

        # Auto-grow ports list if needed
        while len(ports) < port_num:
            i = len(ports) + 1
            ports.append({
                'port_number': i,
                'description': f'Port {i}',
                'type': 'access',
                'vlan': '',
                'speed': '',
                'status': 'inactive',
                'connected_to': '',
                'notes': '',
            })

        if port_num < 1:
            return JsonResponse({'success': False, 'error': 'Invalid port number'}, status=400)

        port_index = port_num - 1
        allowed_fields = ['description', 'type', 'vlan', 'speed', 'status', 'connected_to', 'notes']
        for field in allowed_fields:
            if field in data:
                ports[port_index][field] = data[field]

        asset.ports = ports
        with transaction.atomic():
            asset.save(update_fields=['ports'])

        return JsonResponse({'success': True, 'port': ports[port_index]})

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception:
        logger.exception('API view error')
        return JsonResponse({'success': False, 'error': 'An error occurred'}, status=500)


@login_required
@require_http_methods(["GET"])
def rack_resources_list(request, pk):
    """
    GET /api/racks/<id>/resources/
    Return JSON list of all rack resources (patch panels, switches, etc.) with positions.
    """
    org = get_request_organization(request)
    rack = _api_get_rack(pk, org)

    resources = rack.resources.filter(rack_position__isnull=False)

    resources_data = []
    for resource in resources:
        resources_data.append({
            'id': resource.id,
            'name': resource.name,
            'resource_type': resource.resource_type,
            'resource_type_display': resource.get_resource_type_display(),
            'asset_type': resource.resource_type,  # Use resource_type as asset_type for consistency
            'rack_position': resource.rack_position,
            'port_count': resource.port_count,
            'color': '#9b59b6',  # Purple for resources
            'board_position_x': resource.board_position_x,
            'board_position_y': resource.board_position_y,
            'board_width': resource.board_width,
            'board_height': resource.board_height,
            'equipment_image_url': None,  # Resources don't have equipment models
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
    if request.content_type != 'application/json':
        return JsonResponse({'error': 'JSON required'}, status=400)
    org = get_request_organization(request)
    device = get_object_or_404(RackDevice, pk=pk) if not org else get_object_or_404(RackDevice, pk=pk, rack__organization=org)

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
            'error': 'Invalid value'
        }, status=400)
    except Http404:
        # A scoped lookup refusing another tenant's row is a 404, not a server
        # error. Without this the blanket handler below turns every refusal
        # into a 500 and logs a traceback for it.
        raise
    except Exception:
        logger.exception('API view error')
        return JsonResponse({
            'success': False,
            'error': 'An error occurred'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def update_resource_board_position(request, pk):
    """
    POST /api/rack-resources/<id>/update-board-position/
    Update resource position on wall-mounted board.
    Request body: {"x": 100, "y": 200, "width": 300, "height": 150}
    """
    if request.content_type != 'application/json':
        return JsonResponse({'error': 'JSON required'}, status=400)
    org = get_request_organization(request)
    resource = get_object_or_404(RackResource, pk=pk) if not org else get_object_or_404(RackResource, pk=pk, rack__organization=org)

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
            'error': 'Invalid value'
        }, status=400)
    except Http404:
        # A scoped lookup refusing another tenant's row is a 404, not a server
        # error. Without this the blanket handler below turns every refusal
        # into a 500 and logs a traceback for it.
        raise
    except Exception:
        logger.exception('API view error')
        return JsonResponse({
            'success': False,
            'error': 'An error occurred'
        }, status=500)


@login_required
def rack_connections_list(request, pk):
    """
    GET /api/racks/<id>/connections/
    Return JSON list of all connections in a rack.
    """
    org = get_request_organization(request)
    rack = _api_get_rack(pk, org)
    
    # Get all connections where either from_device or to_device is in this rack
    connections = RackConnection.objects.filter(
        Q(from_device__rack=rack) | Q(to_device__rack=rack)
    ).select_related('from_device', 'to_device')
    
    connections_data = []
    for conn in connections:
        connections_data.append({
            'id': conn.id,
            'from_device_id': conn.from_device.id,
            'from_device_name': conn.from_device.name,
            'from_device_unit': conn.from_device.start_unit,
            'to_device_id': conn.to_device.id,
            'to_device_name': conn.to_device.name,
            'to_device_unit': conn.to_device.start_unit,
            'connection_type': conn.connection_type,
            'from_port': conn.from_port,
            'to_port': conn.to_port,
            'cable_color': conn.cable_color,
            'speed': conn.speed,
        })
    
    return JsonResponse({'connections': connections_data})


@login_required
def device_connections_list(request, pk):
    """
    GET /api/rack-devices/<id>/connections/
    Return JSON list of all connections for a specific device.
    """
    org = get_request_organization(request)
    device = get_object_or_404(RackDevice, pk=pk) if not org else get_object_or_404(RackDevice, pk=pk, rack__organization=org)
    
    # Get all connections where this device is either from or to
    connections = RackConnection.objects.filter(
        Q(from_device=device) | Q(to_device=device)
    ).select_related('from_device', 'to_device')
    
    connections_data = []
    for conn in connections:
        connections_data.append({
            'id': conn.id,
            'from_device_id': conn.from_device.id,
            'from_device_name': conn.from_device.name,
            'to_device_id': conn.to_device.id,
            'to_device_name': conn.to_device.name,
            'connection_type': conn.connection_type,
            'connection_type_display': conn.get_connection_type_display(),
            'from_port': conn.from_port,
            'to_port': conn.to_port,
            'cable_color': conn.cable_color,
            'speed': conn.speed,
            'is_from': conn.from_device.id == device.id,
        })
    
    return JsonResponse({'connections': connections_data})
