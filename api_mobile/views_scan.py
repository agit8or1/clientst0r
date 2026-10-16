"""
Mobile API code-scan resolver (v3.17.461).

A field tech scans a QR or barcode; the camera screen calls this with
the decoded text and we look it up across inventory.qr_code, then
asset.asset_tag, then asset.serial_number. Returns the first match so
the mobile app can deep-link to the right detail screen.
"""
from __future__ import annotations

from .authentication import MobileTokenAuthentication
from rest_framework.decorators import (
    api_view, authentication_classes, permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .scoping import accessible_org_ids, perm_org_ids


@api_view(['GET'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def scan_resolve_view(request):
    """
    GET /api/mobile/v1/scan/?code=<text>

    Returns `{kind, id, name, organization_id?, organization_name?}` on
    a hit, or 404 if nothing matches. Search order:
      1. `InventoryItem.qr_code` (exact)
      2. `Asset.asset_tag` (exact, case-insensitive)
      3. `Asset.serial_number` (exact)
      4. `VehicleInventoryItem.qr_code` (exact, only items in vehicles
         currently assigned to the caller)
    Each match is org-scoped to the caller's accessible orgs.
    """
    code = (request.query_params.get('code') or '').strip()
    if not code:
        return Response({'detail': 'code is required'}, status=400)

    org_ids = list(accessible_org_ids(request.user))

    # 1. Inventory by QR
    try:
        from inventory.models import InventoryItem
        item = (InventoryItem.objects
                .filter(qr_code__iexact=code, organization_id__in=org_ids)
                .select_related('organization')
                .first())
        if item:
            return Response({
                'kind': 'inventory',
                'id': item.id,
                'name': item.name,
                'organization_id': item.organization_id,
                'organization_name': item.organization.name if item.organization_id else None,
                'route': f'/inventory/{item.id}',
            })
    except Exception:
        pass

    # 2. Asset by asset_tag
    try:
        from assets.models import Asset
        asset_org_ids = perm_org_ids(request.user, 'assets_view')
        asset = (Asset.objects
                 .filter(asset_tag__iexact=code, organization_id__in=asset_org_ids)
                 .select_related('organization')
                 .first())
        if not asset:
            asset = (Asset.objects
                     .filter(serial_number__iexact=code,
                             organization_id__in=asset_org_ids)
                     .select_related('organization')
                     .first())
        if asset:
            return Response({
                'kind': 'asset',
                'id': asset.id,
                'name': asset.name,
                'organization_id': asset.organization_id,
                'organization_name': asset.organization.name if asset.organization_id else None,
                'route': f'/assets/{asset.id}',
            })
    except Exception:
        pass

    # 3. Vehicle inventory (caller's assigned vehicles)
    try:
        from vehicles.models import VehicleInventoryItem, VehicleAssignment
        my_vehicle_ids = list(VehicleAssignment.objects.filter(
            user=request.user, end_date__isnull=True,
        ).values_list('vehicle_id', flat=True))
        if my_vehicle_ids:
            vit = (VehicleInventoryItem.objects
                   .filter(qr_code__iexact=code, vehicle_id__in=my_vehicle_ids)
                   .select_related('vehicle')
                   .first())
            if vit:
                return Response({
                    'kind': 'vehicle_inventory',
                    'id': vit.id,
                    'name': vit.name,
                    'route': f'/vehicles/{vit.vehicle_id}',  # detail screen shows item list
                    'vehicle_id': vit.vehicle_id,
                })
    except Exception:
        pass

    return Response({'detail': 'No match'}, status=404)
