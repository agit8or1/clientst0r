"""
Mobile API vehicle endpoints (v3.17.456).

Service-fleet vehicles. Every authenticated user can see and act on
every vehicle (the fleet isn't multi-tenant — it's the operator's own
trucks/vans):

  * View vehicle detail + on-vehicle inventory (`VehicleInventoryItem`)
  * Log a fuel fill-up (`VehicleFuelLog`)
  * Report damage (`VehicleDamageReport`)

Vehicles are not per-organization in the data model — they're the
company fleet that runs Client St0r — so no `accessible_org_ids` scope
applies.

v3.17.477 — dropped the "must have an active `VehicleAssignment`"
gate. Multiple drivers share vehicles; logs still attribute the
actual driver per entry (fuel.user / damage.reported_by).
"""
from __future__ import annotations

from datetime import date as date_cls
from decimal import Decimal, InvalidOperation

from django.utils import timezone
from rest_framework import status as drf_status
from .authentication import MobileTokenAuthentication
from rest_framework.decorators import (
    api_view, authentication_classes, parser_classes, permission_classes,
)
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .scoping import accessible_org_ids


def _save_attachment(user, file_obj, *, entity_type: str, entity_id: int):
    """
    Persist an uploaded file as an Attachment row. Vehicles aren't org-
    scoped, so we attribute the attachment to the uploader's primary
    accessible org. Returns the Attachment instance, or None on failure.
    """
    if file_obj is None:
        return None
    try:
        from files.models import Attachment
        org_ids = list(accessible_org_ids(user))
        if not org_ids:
            return None
        att = Attachment.objects.create(
            organization_id=org_ids[0],
            entity_type=entity_type,
            entity_id=entity_id,
            file=file_obj,
            original_filename=getattr(file_obj, 'name', 'photo.jpg')[:255],
            file_size=getattr(file_obj, 'size', 0) or 0,
            content_type=getattr(file_obj, 'content_type', 'image/jpeg')[:100],
            uploaded_by=user,
        )
        return att
    except Exception:
        return None


def _serialize_attachment(att) -> dict:
    return {
        'id': att.id,
        'entity_type': att.entity_type,
        'entity_id': att.entity_id,
        'original_filename': att.original_filename,
        'file_size': att.file_size,
        'content_type': att.content_type,
        'uploaded_at': att.created_at.isoformat()
            if hasattr(att, 'created_at') and att.created_at else None,
    }


def _serialize_vehicle(v, *, detail: bool = False) -> dict:
    out = {
        'id': v.id,
        'name': v.name,
        'vehicle_type': v.vehicle_type,
        'make': v.make,
        'model': v.model,
        'year': v.year,
        'license_plate': v.license_plate,
        'status': v.status,
        'condition': v.condition,
        'current_mileage': v.current_mileage,
    }
    if detail:
        out.update({
            'color': v.color or '',
            'vin': v.vin or '',
            'qr_code': v.qr_code or '',
            'insurance_provider': v.insurance_provider or '',
            'insurance_policy_number': v.insurance_policy_number or '',
            'insurance_expires_at': v.insurance_expires_at.isoformat()
                if v.insurance_expires_at else None,
        })
    return out


def _serialize_inventory_item(it) -> dict:
    return {
        'id': it.id,
        'vehicle_id': it.vehicle_id,
        'name': it.name,
        'category': it.category or '',
        'quantity': it.quantity,
        'unit': it.unit or '',
        'min_quantity': it.min_quantity,
        'reorder_quantity': it.reorder_quantity,
        'unit_cost': str(it.unit_cost) if it.unit_cost is not None else None,
        'description': it.description or '',
        'location_in_vehicle': it.location_in_vehicle or '',
        'qr_code': it.qr_code or '',
    }


def _serialize_fuel(f) -> dict:
    return {
        'id': f.id,
        'vehicle_id': f.vehicle_id,
        'date': f.date.isoformat() if f.date else None,
        'mileage': f.mileage,
        'gallons': str(f.gallons),
        'cost_per_gallon': str(f.cost_per_gallon),
        'total_cost': str(f.total_cost),
        'station': f.station or '',
        'miles_driven': f.miles_driven,
        'mpg': str(f.mpg) if f.mpg is not None else None,
        'notes': f.notes or '',
    }


def _serialize_damage(d) -> dict:
    return {
        'id': d.id,
        'vehicle_id': d.vehicle_id,
        'incident_date': d.incident_date.isoformat() if d.incident_date else None,
        'reported_by_id': d.reported_by_id,
        'description': d.description or '',
        'severity': d.severity,
        'repair_status': d.repair_status,
        'damage_location': d.damage_location or '',
        'estimated_cost': str(d.estimated_cost) if d.estimated_cost is not None else None,
        'insurance_claim_number': d.insurance_claim_number or '',
    }


def _my_vehicle_or_404(user, pk):
    """Return the ServiceVehicle if it exists. v3.17.477 — any authenticated
    user may access any vehicle (the fleet is shared)."""
    from vehicles.models import ServiceVehicle
    try:
        return ServiceVehicle.objects.get(pk=pk)
    except ServiceVehicle.DoesNotExist:
        return None


@api_view(['GET'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def my_vehicles_view(request):
    """
    GET /api/mobile/v1/vehicles/

    The whole service fleet. Vehicles aren't multi-tenant — every
    authenticated user can see every vehicle (v3.17.477).
    """
    from vehicles.models import ServiceVehicle
    qs = ServiceVehicle.objects.exclude(status='retired').order_by('name')
    return Response({
        'count': qs.count(),
        'results': [_serialize_vehicle(v, detail=True) for v in qs],
    })


@api_view(['GET'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def vehicle_detail_view(request, pk: int):
    """GET /api/mobile/v1/vehicles/<id>/  — any authenticated user."""
    v = _my_vehicle_or_404(request.user, pk)
    if v is None:
        return Response({'detail': 'Not found'}, status=404)
    return Response(_serialize_vehicle(v, detail=True))


@api_view(['GET'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def vehicle_inventory_view(request, pk: int):
    """GET /api/mobile/v1/vehicles/<id>/inventory/ — items stocked in the vehicle."""
    v = _my_vehicle_or_404(request.user, pk)
    if v is None:
        return Response({'detail': 'Not found'}, status=404)
    items = v.inventory_items.all().order_by('category', 'name')
    return Response({
        'count': items.count(),
        'results': [_serialize_inventory_item(i) for i in items],
    })


@api_view(['GET', 'POST'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def vehicle_fuel_view(request, pk: int):
    """
    GET  /api/mobile/v1/vehicles/<id>/fuel/        — fuel log history (last 50)
    POST /api/mobile/v1/vehicles/<id>/fuel/        — log a fuel fill-up

    POST body: `{date?, mileage, gallons, cost_per_gallon, total_cost?,
                 station?, notes?, photo?}`. `total_cost` defaults to
    gallons * cost_per_gallon when omitted. `date` defaults to today.
    Optional `photo` (multipart/form-data) attaches a receipt image.
    """
    from vehicles.models import VehicleFuelLog
    v = _my_vehicle_or_404(request.user, pk)
    if v is None:
        return Response({'detail': 'Not found'}, status=404)

    if request.method == 'GET':
        logs = v.fuel_logs.all().order_by('-date', '-mileage')[:50]
        return Response({
            'count': logs.count(),
            'results': [_serialize_fuel(f) for f in logs],
        })

    data = request.data or {}

    # Required: mileage, gallons, cost_per_gallon
    try:
        mileage = int(data.get('mileage'))
    except (TypeError, ValueError):
        return Response({'detail': 'mileage required (int)'}, status=400)
    if mileage < 0:
        return Response({'detail': 'mileage must be >= 0'}, status=400)

    try:
        gallons = Decimal(str(data.get('gallons')))
        cost_per_gallon = Decimal(str(data.get('cost_per_gallon')))
    except (InvalidOperation, TypeError, ValueError):
        return Response({'detail': 'gallons and cost_per_gallon required'}, status=400)
    if gallons <= 0 or cost_per_gallon <= 0:
        return Response({'detail': 'gallons and cost_per_gallon must be > 0'}, status=400)

    total_cost_raw = data.get('total_cost')
    if total_cost_raw is not None:
        try:
            total_cost = Decimal(str(total_cost_raw))
        except (InvalidOperation, TypeError, ValueError):
            return Response({'detail': 'invalid total_cost'}, status=400)
    else:
        total_cost = (gallons * cost_per_gallon).quantize(Decimal('0.01'))

    when_raw = data.get('date')
    if when_raw:
        try:
            when = date_cls.fromisoformat(str(when_raw))
        except (ValueError, TypeError):
            return Response({'detail': 'invalid date (use YYYY-MM-DD)'}, status=400)
    else:
        when = timezone.localdate()

    fuel_log = VehicleFuelLog.objects.create(
        vehicle=v,
        date=when,
        mileage=mileage,
        gallons=gallons,
        cost_per_gallon=cost_per_gallon,
        total_cost=total_cost,
        station=(data.get('station') or '')[:200],
        notes=(data.get('notes') or '')[:2000],
    )
    # Keep odometer in sync if this fillup is more recent than the
    # vehicle's recorded mileage.
    if mileage > v.current_mileage:
        v.current_mileage = mileage
        v.save(update_fields=['current_mileage', 'updated_at']
               if any(f.name == 'updated_at' for f in v._meta.fields)
               else ['current_mileage'])

    # Optional receipt photo (v3.17.460)
    photo = request.FILES.get('photo') if hasattr(request, 'FILES') else None
    photo_attachment = None
    if photo is not None:
        photo_attachment = _save_attachment(
            request.user, photo,
            entity_type='fuel_log', entity_id=fuel_log.id,
        )

    payload = _serialize_fuel(fuel_log)
    if photo_attachment is not None:
        payload['photo'] = _serialize_attachment(photo_attachment)
    return Response(payload, status=drf_status.HTTP_201_CREATED)


@api_view(['GET', 'POST'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def vehicle_damage_view(request, pk: int):
    """
    GET  /api/mobile/v1/vehicles/<id>/damage/  — damage report history
    POST /api/mobile/v1/vehicles/<id>/damage/  — file a damage report

    POST body: `{description, severity?, damage_location?, incident_date?,
                 estimated_cost?, photo?}`. Severity defaults to 'minor';
    incident_date defaults to today. Optional `photo` (multipart/form-data)
    attaches an evidence image.
    """
    from vehicles.models import VehicleDamageReport
    v = _my_vehicle_or_404(request.user, pk)
    if v is None:
        return Response({'detail': 'Not found'}, status=404)

    if request.method == 'GET':
        reports = v.damage_reports.all().order_by('-incident_date')[:50]
        return Response({
            'count': reports.count(),
            'results': [_serialize_damage(r) for r in reports],
        })

    data = request.data or {}
    description = (data.get('description') or '').strip()
    if not description:
        return Response({'detail': 'description required'}, status=400)

    severity = data.get('severity') or 'minor'
    if severity not in ('minor', 'moderate', 'major', 'total_loss'):
        return Response({'detail': 'invalid severity'}, status=400)

    when_raw = data.get('incident_date')
    if when_raw:
        try:
            when = date_cls.fromisoformat(str(when_raw))
        except (ValueError, TypeError):
            return Response({'detail': 'invalid incident_date'}, status=400)
    else:
        when = timezone.localdate()

    cost_raw = data.get('estimated_cost')
    estimated_cost = None
    if cost_raw is not None:
        try:
            estimated_cost = Decimal(str(cost_raw))
        except (InvalidOperation, TypeError, ValueError):
            return Response({'detail': 'invalid estimated_cost'}, status=400)

    report = VehicleDamageReport.objects.create(
        vehicle=v,
        incident_date=when,
        reported_by=request.user,
        description=description[:5000],
        severity=severity,
        damage_location=(data.get('damage_location') or '')[:200],
        estimated_cost=estimated_cost,
        condition_before=v.condition,
    )

    # Optional evidence photo (v3.17.460)
    photo = request.FILES.get('photo') if hasattr(request, 'FILES') else None
    photo_attachment = None
    if photo is not None:
        photo_attachment = _save_attachment(
            request.user, photo,
            entity_type='damage_report', entity_id=report.id,
        )

    payload = _serialize_damage(report)
    if photo_attachment is not None:
        payload['photo'] = _serialize_attachment(photo_attachment)
    return Response(payload, status=drf_status.HTTP_201_CREATED)
