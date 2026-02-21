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
from .models import Rack, RackDevice
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
