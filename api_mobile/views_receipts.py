"""
Mobile receipt upload (v3.17.470).

Tech takes a photo of a gas / repair / parts receipt; the SERVER:
  1. Stores the image (`Attachment` with `entity_type='vehicle_receipt'`)
  2. SHA-256 hashes the image to short-circuit re-uploads
  3. OCRs the image (if `OCR_PROVIDER` is set; no-op otherwise)
  4. Creates a `VehicleReceipt` row with parsed `vendor`, `amount`,
     `tax`, `receipt_date`, `odometer`
  5. For category `fuel`, ALSO creates a `VehicleFuelLog` from the
     extracted gallons / cpg / total
  6. For category `maintenance` or `repair`, ALSO creates a
     `VehicleMaintenanceRecord` skeleton (description + date + total
     cost) — the tech can edit on web for `maintenance_type` etc.

This is the inverse of the v3.17.465 design — upload first, server
keeps everything, structured records derive from the receipt.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import date as date_cls
from decimal import Decimal, InvalidOperation

from django.utils import timezone
from rest_framework import status as drf_status
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import (
    api_view, authentication_classes, parser_classes, permission_classes,
)
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .scoping import accessible_org_ids

logger = logging.getLogger('api_mobile.receipts')

# Categories the mobile UI sends. Maps onto VehicleReceipt.CATEGORY_CHOICES.
_VALID_CATEGORIES = {
    'fuel', 'maintenance', 'repair', 'insurance',
    'registration', 'toll', 'cleaning', 'inspection', 'other',
}


def _my_vehicle_or_none(user, vehicle_id):
    """Active assignment check — same rule as views_vehicles."""
    if vehicle_id is None:
        return None
    try:
        from vehicles.models import ServiceVehicle, VehicleAssignment
        v = ServiceVehicle.objects.get(pk=int(vehicle_id))
    except (ValueError, TypeError, Exception):
        return None
    if not VehicleAssignment.objects.filter(
        vehicle=v, user=user, end_date__isnull=True,
    ).exists():
        return None
    return v


def _extract_with_llm(image_bytes, image_mime='image/jpeg', hint=None):
    """
    v3.17.471 — extract receipt fields using the LLM provider currently
    configured in Settings → AI. Whatever the user picked (Anthropic
    Claude, OpenAI GPT-4o, Ollama llava, etc.) does the OCR + parsing
    in one vision call.

    Returns `(raw_text, parsed_dict)` where parsed_dict uses the same
    keys the regex parser used so the rest of the upload flow doesn't
    have to care which path produced them. Both empty on failure /
    no-LLM-configured.
    """
    # The master AI switch (Settings -> PSA (AI)) governs every LLM call.
    # With it off, the receipt is still stored; the LLM extraction is skipped
    # and only the env-configured, non-LLM OCR fallback below may run.
    from core.ai_gate import ai_features_enabled
    if not ai_features_enabled():
        provider = None
    else:
        try:
            from docs.services.llm_providers import get_configured_provider
            provider = get_configured_provider()
        except Exception as exc:
            logger.warning('LLM provider load failed: %s', exc)
            return ('', {})

    if provider is None:
        # Fall back to legacy Cloud Vision path (OCR_PROVIDER env) so
        # deployments that already wired that up still work.
        try:
            from .views_ocr import _run_ocr, _parse_receipt_text, _ocr_provider
            if _ocr_provider():
                text = _run_ocr(image_bytes) or ''
                return (text, _parse_receipt_text(text)) if text else ('', {})
        except Exception as exc:
            logger.warning('fallback Cloud Vision OCR failed: %s', exc)
        return ('', {})

    try:
        result = provider.extract_receipt_fields(image_bytes, image_mime, hint=hint)
    except Exception as exc:
        logger.warning('LLM receipt extract raised: %s', exc)
        return ('', {})

    if not result.get('success'):
        logger.info('LLM receipt extract returned not-success: %s',
                    result.get('error'))
        return ('', {})

    ex = result.get('extracted') or {}
    raw_text = (ex.get('raw_text') or '')[:5000]

    # Map LLM's friendlier field names onto the keys the rest of
    # views_receipts already speaks.
    def _str_or_empty(v):
        return '' if v is None else str(v)

    return (raw_text, {
        'gallons':         _str_or_empty(ex.get('gallons')),
        'cost_per_gallon': _str_or_empty(ex.get('cost_per_gallon')),
        'total_cost':      _str_or_empty(ex.get('amount_total')),
        'amount_tax':      _str_or_empty(ex.get('amount_tax')),
        'station':         ex.get('vendor') or '',
        'date_raw':        ex.get('date') or '',
        'odometer':        _str_or_empty(ex.get('odometer')),
        'category_hint':   ex.get('category_hint') or '',
        'line_items':      ex.get('line_items') or [],
    })


def _serialize_receipt(r):
    from files.models import Attachment
    att = Attachment.objects.filter(
        entity_type='vehicle_receipt', entity_id=r.pk,
    ).order_by('-created_at').first()
    return {
        'id': r.id,
        'vehicle_id': r.vehicle_id,
        'category': r.category,
        'vendor': r.vendor or '',
        'amount': str(r.amount) if r.amount is not None else None,
        'tax_amount': str(r.tax_amount) if r.tax_amount is not None else None,
        'receipt_date': r.receipt_date.isoformat() if r.receipt_date else None,
        'odometer': r.odometer,
        'description': r.description or '',
        'notes': r.notes or '',
        'ai_processed': r.ai_processed,
        'ai_confidence': r.ai_confidence or '',
        'created_at': r.created_at.isoformat()
            if hasattr(r, 'created_at') and r.created_at else None,
        'attachment_id': att.id if att else None,
        'attachment_filename': att.original_filename if att else None,
    }


def _confidence_from(extracted):
    n = sum(1 for v in extracted.values() if v)
    if n >= 4:
        return 'high'
    if n >= 2:
        return 'medium'
    if n >= 1:
        return 'low'
    return ''


# ============================================================
@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser])
def receipt_list_view(request):
    """
    GET  /api/mobile/v1/receipts/                 last 50 of caller's receipts
    POST /api/mobile/v1/receipts/  (multipart)    upload a new receipt

    POST fields:
      - `photo` (file, required)
      - `vehicle_id` (int, required) — must be a vehicle assigned to caller
      - `category` (str, default 'other') — one of fuel/maintenance/repair/
        insurance/registration/toll/cleaning/inspection/other
      - `notes` (str, optional)
      - `receipt_date` (YYYY-MM-DD, optional; defaults to today or to
        OCR-extracted date)

    Response 201:
      `{receipt, fuel_log_id?, maintenance_record_id?}`

    Response 200 (duplicate, same image_hash already on this vehicle):
      `{receipt, duplicate: true}`
    """
    from vehicles.models import VehicleReceipt
    from files.models import Attachment

    if request.method == 'GET':
        qs = (VehicleReceipt.objects
              .filter(created_by=request.user)
              .order_by('-receipt_date', '-created_at')[:50])
        return Response({
            'count': qs.count(),
            'results': [_serialize_receipt(r) for r in qs],
        })

    # POST
    photo = request.FILES.get('photo')
    if photo is None:
        return Response({'detail': 'photo required'}, status=400)
    if photo.size > 20 * 1024 * 1024:
        return Response({'detail': 'photo too large (max 20 MB)'}, status=400)

    vehicle_id = request.data.get('vehicle_id')
    vehicle = _my_vehicle_or_none(request.user, vehicle_id)
    if vehicle is None:
        return Response(
            {'detail': 'vehicle_id required + must be assigned to you'},
            status=400 if not vehicle_id else 404,
        )

    category = (request.data.get('category') or 'other').strip().lower()
    if category not in _VALID_CATEGORIES:
        category = 'other'

    # Hash the photo for dedup. Read once, reuse.
    image_bytes = photo.read()
    photo.seek(0)
    image_hash = hashlib.sha256(image_bytes).hexdigest()

    # Dedup check — same image already uploaded for this vehicle?
    existing = VehicleReceipt.objects.filter(
        vehicle=vehicle, image_hash=image_hash,
    ).first()
    if existing:
        return Response({
            'receipt': _serialize_receipt(existing),
            'duplicate': True,
        }, status=200)

    # AI receipt extraction (LLM vision via the configured provider).
    # No-op if no LLM is set up; receipt still saved with image.
    image_mime = (getattr(photo, 'content_type', None) or 'image/jpeg').split(';')[0]
    raw_text, extracted = _extract_with_llm(
        image_bytes, image_mime=image_mime, hint=category if category != 'other' else None,
    )

    # Extract date from raw_text or default to today
    parsed_date = None
    date_raw = extracted.get('date_raw') or ''
    if date_raw:
        for fmt_re in (r'(\d{4})-(\d{1,2})-(\d{1,2})',
                       r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})'):
            m = re.match(fmt_re, date_raw)
            if m:
                try:
                    a, b, c = m.groups()
                    if len(a) == 4:
                        parsed_date = date_cls(int(a), int(b), int(c))
                    else:
                        year = int(c)
                        if year < 100:
                            year += 2000
                        parsed_date = date_cls(year, int(a), int(b))
                    break
                except (ValueError, TypeError):
                    pass

    raw_date_from_client = request.data.get('receipt_date')
    if raw_date_from_client:
        try:
            parsed_date = date_cls.fromisoformat(str(raw_date_from_client))
        except (ValueError, TypeError):
            pass
    if parsed_date is None:
        parsed_date = timezone.localdate()

    # Numeric extracts
    def _dec(key):
        raw = extracted.get(key)
        if not raw:
            return None
        try:
            return Decimal(str(raw))
        except (InvalidOperation, TypeError, ValueError):
            return None

    total_cost = _dec('total_cost')
    gallons = _dec('gallons')
    cost_per_gallon = _dec('cost_per_gallon')
    station = extracted.get('station') or ''

    # Build the receipt row
    receipt = VehicleReceipt.objects.create(
        vehicle=vehicle,
        receipt_date=parsed_date,
        vendor=station[:255],
        category=category,
        amount=total_cost if total_cost is not None else Decimal('0.00'),
        description=raw_text[:5000] if raw_text else '',
        notes=(request.data.get('notes') or '')[:5000],
        ai_processed=bool(raw_text),
        ai_confidence=_confidence_from(extracted),
        image_hash=image_hash,
        created_by=request.user,
    )

    # Attach the photo to this receipt via the existing Attachment flow.
    try:
        from .views_vehicles import _save_attachment
        photo.seek(0)
        _save_attachment(
            request.user, photo,
            entity_type='vehicle_receipt', entity_id=receipt.id,
        )
    except Exception as exc:
        logger.warning('attachment save failed for receipt %s: %s', receipt.id, exc)

    # Auto-create the typed downstream record
    fuel_log_id = None
    maintenance_record_id = None

    if category == 'fuel' and gallons and cost_per_gallon:
        try:
            from vehicles.models import VehicleFuelLog
            fl = VehicleFuelLog.objects.create(
                vehicle=vehicle,
                date=parsed_date,
                mileage=max(0, receipt.odometer or vehicle.current_mileage or 0),
                gallons=gallons,
                cost_per_gallon=cost_per_gallon,
                total_cost=total_cost or (gallons * cost_per_gallon).quantize(Decimal('0.01')),
                station=station[:200],
                notes=f'Auto-created from receipt #{receipt.id}',
            )
            fuel_log_id = fl.id
        except Exception as exc:
            logger.warning('fuel log auto-create failed: %s', exc)

    elif category in ('maintenance', 'repair') and total_cost:
        try:
            from vehicles.models import VehicleMaintenanceRecord
            mr = VehicleMaintenanceRecord.objects.create(
                vehicle=vehicle,
                maintenance_type='repair' if category == 'repair' else 'other',
                description=f'Auto-created from receipt #{receipt.id}'
                            + (f' — {station}' if station else ''),
                service_date=parsed_date,
                mileage_at_service=max(0, vehicle.current_mileage or 0),
                total_cost=total_cost,
            )
            maintenance_record_id = mr.id
        except Exception as exc:
            logger.warning('maintenance record auto-create failed: %s', exc)

    from core.ai_gate import ai_features_enabled
    return Response({
        'receipt': _serialize_receipt(receipt),
        'fuel_log_id': fuel_log_id,
        'maintenance_record_id': maintenance_record_id,
        'duplicate': False,
        # Lets the app explain empty fields: AI extraction is switched off.
        'ai_extraction_enabled': ai_features_enabled(),
    }, status=drf_status.HTTP_201_CREATED)


@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def receipt_detail_view(request, pk: int):
    """GET /api/mobile/v1/receipts/<id>/ — own receipts only."""
    from vehicles.models import VehicleReceipt
    try:
        r = VehicleReceipt.objects.get(pk=pk, created_by=request.user)
    except VehicleReceipt.DoesNotExist:
        return Response({'detail': 'Not found'}, status=404)
    return Response(_serialize_receipt(r))
