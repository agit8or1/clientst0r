"""
Mobile API inventory endpoints (v3.17.458).

Wraps the `inventory` app — `InventoryItem` org-scoped stock with
`InventoryTransaction` history. Lets a tech list / search items, see
stock levels, and adjust stock from the field (stock_in / stock_out /
adjustment).
"""
from __future__ import annotations

from django.db.models import Q
from rest_framework import status as drf_status
from .authentication import MobileTokenAuthentication
from rest_framework.decorators import (
    api_view, authentication_classes, permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .scoping import accessible_org_ids


def _serialize_item(it, *, detail: bool = False) -> dict:
    out = {
        'id': it.id,
        'name': it.name,
        'sku': it.sku or '',
        'manufacturer_part_number': it.manufacturer_part_number or '',
        'item_type': it.item_type,
        'organization_id': it.organization_id,
        'organization_name': it.organization.name if it.organization_id else None,
        'category_id': it.category_id,
        'category_name': it.category.name if it.category_id else None,
        'storage_location_id': it.storage_location_id,
        'storage_location_name': it.storage_location.name if it.storage_location_id else None,
        'quantity': it.quantity,
        'unit': it.unit or 'ea',
        'min_quantity': it.min_quantity,
        'is_low_stock': it.is_low_stock,
        'qr_code': it.qr_code or '',
    }
    if detail:
        out.update({
            'description': it.description or '',
            'notes': it.notes or '',
            'reorder_quantity': it.reorder_quantity,
            'unit_cost': str(it.unit_cost) if it.unit_cost is not None else None,
            'reorder_link': it.reorder_link or '',
        })
    return out


def _serialize_transaction(tx) -> dict:
    return {
        'id': tx.id,
        'item_id': tx.item_id,
        'transaction_type': tx.transaction_type,
        'quantity_change': tx.quantity_change,
        'quantity_after': tx.quantity_after,
        'notes': tx.notes or '',
        'performed_by_id': tx.performed_by_id,
        'created_at': tx.created_at.isoformat() if hasattr(tx, 'created_at') and tx.created_at else None,
    }


@api_view(['GET'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def inventory_list_view(request):
    """
    GET /api/mobile/v1/inventory/?search=&organization_id=&item_type=&low_stock=true&page=

    Paginated list, org-scoped. `low_stock=true` returns only items
    where quantity <= min_quantity (the existing `is_low_stock`
    property). Search hits name / sku / manufacturer_part_number /
    qr_code.
    """
    from inventory.models import InventoryItem
    org_ids = list(accessible_org_ids(request.user))
    qs = (InventoryItem.objects
          .filter(organization_id__in=org_ids)
          .select_related('organization', 'category', 'storage_location'))

    search = (request.query_params.get('search') or '').strip()
    if search:
        qs = qs.filter(
            Q(name__icontains=search)
            | Q(sku__icontains=search)
            | Q(manufacturer_part_number__icontains=search)
            | Q(qr_code__iexact=search)
        )

    item_type = request.query_params.get('item_type')
    if item_type:
        qs = qs.filter(item_type=item_type)

    organization_id = request.query_params.get('organization_id')
    if organization_id:
        try:
            oid = int(organization_id)
            if oid in org_ids:
                qs = qs.filter(organization_id=oid)
            else:
                qs = qs.none()
        except ValueError:
            pass

    if (request.query_params.get('low_stock') or '').lower() == 'true':
        # quantity <= min_quantity using F lookup
        from django.db.models import F
        qs = qs.filter(quantity__lte=F('min_quantity'))

    qs = qs.order_by('organization__name', 'name')

    try:
        page = max(int(request.query_params.get('page', 1)), 1)
    except ValueError:
        page = 1
    page_size = 50
    start = (page - 1) * page_size
    total = qs.count()
    rows = qs[start:start + page_size]

    return Response({
        'count': total,
        'page': page,
        'page_size': page_size,
        'results': [_serialize_item(i) for i in rows],
    })


@api_view(['GET'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def inventory_detail_view(request, pk: int):
    """GET /api/mobile/v1/inventory/<id>/  — 404 cross-org."""
    from inventory.models import InventoryItem
    org_ids = list(accessible_org_ids(request.user))
    try:
        it = (InventoryItem.objects
              .select_related('organization', 'category', 'storage_location')
              .get(pk=pk, organization_id__in=org_ids))
    except InventoryItem.DoesNotExist:
        return Response({'detail': 'Not found'}, status=404)
    return Response(_serialize_item(it, detail=True))


@api_view(['GET', 'POST'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def inventory_transactions_view(request, pk: int):
    """
    GET  /api/mobile/v1/inventory/<id>/transactions/  — last 50 transactions
    POST /api/mobile/v1/inventory/<id>/transactions/  — adjust stock

    POST body: `{transaction_type, quantity_change, notes?}`. Allowed
    types: `stock_in` / `stock_out` / `adjustment`. `quantity_change` is
    signed: positive for additions, negative for removals. `stock_in`
    auto-coerces to positive; `stock_out` auto-coerces to negative.
    `adjustment` accepts whatever sign you provide. Updates the item's
    `quantity` atomically.
    """
    from django.db import transaction
    from inventory.models import InventoryItem, InventoryTransaction

    org_ids = list(accessible_org_ids(request.user))
    try:
        item = InventoryItem.objects.get(pk=pk, organization_id__in=org_ids)
    except InventoryItem.DoesNotExist:
        return Response({'detail': 'Not found'}, status=404)

    if request.method == 'GET':
        rows = item.transactions.all().order_by('-created_at')[:50]
        return Response({
            'count': rows.count(),
            'results': [_serialize_transaction(t) for t in rows],
        })

    data = request.data or {}
    ttype = (data.get('transaction_type') or '').strip()
    if ttype not in ('stock_in', 'stock_out', 'adjustment'):
        return Response(
            {'detail': 'transaction_type must be stock_in / stock_out / adjustment'},
            status=400,
        )

    try:
        change = int(data.get('quantity_change'))
    except (TypeError, ValueError):
        return Response({'detail': 'quantity_change required (int)'}, status=400)
    if change == 0:
        return Response({'detail': 'quantity_change must be non-zero'}, status=400)

    # Coerce sign for the directional types
    if ttype == 'stock_in' and change < 0:
        change = -change
    elif ttype == 'stock_out' and change > 0:
        change = -change

    new_qty = item.quantity + change
    if new_qty < 0:
        return Response(
            {'detail': f'would result in negative stock (current {item.quantity}, change {change})'},
            status=400,
        )

    notes = (data.get('notes') or '')[:2000]

    with transaction.atomic():
        item.quantity = new_qty
        item.save(update_fields=['quantity', 'updated_at']
                  if any(f.name == 'updated_at' for f in item._meta.fields)
                  else ['quantity'])
        tx = InventoryTransaction.objects.create(
            item=item,
            transaction_type=ttype,
            quantity_change=change,
            quantity_after=new_qty,
            notes=notes,
            performed_by=request.user,
        )

    return Response(_serialize_transaction(tx),
                    status=drf_status.HTTP_201_CREATED)
