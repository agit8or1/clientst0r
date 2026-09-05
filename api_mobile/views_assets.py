"""
Mobile API assets endpoints (v3.17.348; create endpoint added v3.17.454).
"""
from __future__ import annotations

from django.db.models import Q
from rest_framework import status as drf_status
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import (
    api_view, authentication_classes, permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permission_utils import user_has_perm

from .scoping import accessible_org_ids


# Whitelist of fields the mobile create endpoint accepts. Anything not
# listed is silently dropped — keeps mobile from setting administrative
# fields like `organization_id` mismatching, audit-only metadata, etc.
_CREATABLE_FIELDS = (
    'name', 'asset_type', 'asset_tag', 'serial_number',
    'hostname', 'ip_address', 'mac_address',
    'os_name', 'os_version', 'manufacturer', 'model',
    'notes',
)

# v3.17.480 — whitelist for PATCH /assets/<id>/. Same shape as create
# minus `organization_id` (re-org would silently break vault relations).
_EDITABLE_FIELDS = _CREATABLE_FIELDS + (
    'cpu', 'ram_gb', 'storage', 'firmware_version', 'firmware_latest',
    'os_version', 'warranty_expiry', 'lifespan_years',
)


def _user_label(user):
    """Display name for a User FK — full name when set, username otherwise."""
    full = (user.get_full_name() or '').strip()
    return full or user.username


def _custom_fields(asset):
    """`Asset.custom_fields` is a JSONField that should hold a dict, but a
    bad CSV import can leave a list or a bare string in there. Anything
    that isn't a dict is treated as empty rather than blowing up the
    serializer for every asset in the org."""
    cf = getattr(asset, 'custom_fields', None)
    return cf if isinstance(cf, dict) else {}


def _cf_str(cf, key):
    """Read one custom field as a display string. JSON values can be
    numbers or booleans; the mobile client renders these as text."""
    val = cf.get(key)
    if val is None or val == '':
        return ''
    return val if isinstance(val, str) else str(val)


def _serialize_asset(asset, *, detail=False):
    # v3.17.536 — `status` and `location` are not columns on Asset. The web
    # asset list reads them out of `custom_fields` (see assets/views.py),
    # so mobile reads them from the same place instead of reporting them
    # as absent.
    cf = _custom_fields(asset)
    out = {
        'id': asset.id,
        'name': asset.name,
        'asset_type': asset.asset_type,
        'asset_tag': asset.asset_tag,
        'serial_number': asset.serial_number,
        'hostname': asset.hostname,
        'ip_address': asset.ip_address,
        'status': _cf_str(cf, 'status'),
        'location': _cf_str(cf, 'location'),
        'organization_id': asset.organization_id,
        'organization_name': asset.organization.name if asset.organization_id else None,
    }
    if detail:
        out.update({
            'mac_address': asset.mac_address,
            'os_name': asset.os_name,
            'os_version': asset.os_version,
            'manufacturer': asset.manufacturer,
            'model': asset.model,
            'cpu': asset.cpu,
            'ram_gb': asset.ram_gb,
            'storage': asset.storage,
            'firmware_version': asset.firmware_version,
            'firmware_latest': asset.firmware_latest,
            'purchase_date': asset.purchase_date.isoformat() if asset.purchase_date else None,
            'warranty_status': getattr(asset, 'warranty_status', '') or '',
            'warranty_expiry': asset.warranty_expiry.isoformat() if asset.warranty_expiry else None,
            'lifespan_years': asset.lifespan_years,
            'notes': asset.notes,
            'primary_contact_name': asset.primary_contact.full_name if asset.primary_contact_id else None,
            'created_at': asset.created_at.isoformat() if asset.created_at else None,
            'updated_at': asset.updated_at.isoformat() if asset.updated_at else None,
            # Everything else the org put on the record. `status` and
            # `location` are promoted above but stay in here too so the
            # client can render the remainder generically.
            'custom_fields': cf,
            'tags': [t.name for t in asset.tags.all()],
            'created_by_name': _user_label(asset.created_by)
                if asset.created_by_id else None,
        })
    return out


def _vault_entries_for_asset(asset, request_user):
    """Return Vault Password rows linked to this asset via PasswordRelation.

    Only returns metadata needed for a tappable list — title, username,
    URL, password_type — never the encrypted blob. The mobile app
    navigates to /vault/<id>/ for the full reveal flow.
    """
    try:
        from vault.models import Password, PasswordRelation
    except Exception:
        return []
    rel_ids = list(
        PasswordRelation.objects
        .filter(relation_type='asset', relation_id=asset.id)
        .values_list('password_id', flat=True)
    )
    if not rel_ids:
        return []
    org_ids = accessible_org_ids(request_user)
    pw_qs = (
        Password.objects
        .filter(id__in=rel_ids, organization_id__in=org_ids)
        .order_by('title')
    )
    return [{
        'id': p.id,
        'title': p.title,
        'username': p.username or '',
        'url': p.url or '',
        'password_type': p.password_type or '',
    } for p in pw_qs]


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def asset_list_view(request):
    """
    GET  /api/mobile/v1/assets/?search=&organization_id=&type=&status=&page=
         `asset_type` is accepted as an alias for `type`; `status`
         matches `custom_fields.status` (Asset has no status column).
    POST /api/mobile/v1/assets/   — create a new asset (v3.17.454)

    Paginated list scoped to the user's accessible organizations. POST
    body: `{organization_id, name, asset_type?, hostname?, ip_address?,
            mac_address?, serial_number?, asset_tag?, os_name?, model?,
            manufacturer?, notes?}`. `organization_id` must be one of the
    user's accessible orgs (403 otherwise); `name` required.
    """
    from assets.models import Asset

    if request.method == 'POST':
        return _create_asset(request)

    org_ids = accessible_org_ids(request.user)
    qs = Asset.objects.filter(organization_id__in=org_ids)

    search = (request.query_params.get('search') or '').strip()
    if search:
        qs = qs.filter(
            Q(name__icontains=search)
            | Q(hostname__icontains=search)
            | Q(ip_address__icontains=search)
            | Q(serial_number__icontains=search)
            | Q(asset_tag__icontains=search)
        )

    organization_id = request.query_params.get('organization_id')
    if organization_id:
        try:
            org_id = int(organization_id)
            if org_id in org_ids:
                qs = qs.filter(organization_id=org_id)
            else:
                qs = qs.none()  # asking for an org we don't have access to
        except ValueError:
            pass

    # v3.17.536 — the shipped mobile client sends `asset_type`, this view
    # only ever read `type`, so the Assets list "Type" box was accepted
    # and silently ignored. Accept both spellings; `type` stays first so
    # existing callers are unaffected.
    asset_type = (
        request.query_params.get('type')
        or request.query_params.get('asset_type')
    )
    if asset_type:
        qs = qs.filter(asset_type=asset_type)

    # v3.17.536 — same story for "Status", which was never implemented at
    # all. Asset has no status column; the web list filters
    # `custom_fields__status`, so match that. iexact rather than the web's
    # exact match because mobile types the value by hand instead of
    # picking it from a dropdown of known values.
    status_filter = (request.query_params.get('status') or '').strip()
    if status_filter:
        qs = qs.filter(custom_fields__status__iexact=status_filter)

    qs = qs.order_by('name')

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
        'results': [_serialize_asset(a) for a in rows],
    })


@api_view(['GET', 'PATCH'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def asset_detail_view(request, pk: int):
    """
    GET   /api/mobile/v1/assets/<id>/
    PATCH /api/mobile/v1/assets/<id>/   (edit — v3.17.480; assets_edit-gated)

    Cross-org reads return 404. PATCH accepts the same whitelist as
    create plus a few additional hardware/lifecycle fields. Setting
    `organization_id` is intentionally rejected so a re-org doesn't
    silently break vault relations.
    """
    from assets.models import Asset

    org_ids = accessible_org_ids(request.user)
    try:
        asset = Asset.objects.select_related(
            'organization', 'primary_contact', 'created_by',
        ).prefetch_related('tags').get(pk=pk, organization_id__in=org_ids)
    except Asset.DoesNotExist:
        return Response({'detail': 'Not found'}, status=404)

    if request.method == 'PATCH':
        if not user_has_perm(request.user, 'assets_edit'):
            return Response(
                {'detail': "You don't have permission to edit assets."},
                status=drf_status.HTTP_403_FORBIDDEN,
            )
        data = request.data or {}
        if 'organization_id' in data:
            return Response(
                {'detail': 'organization_id is not editable on mobile'},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )
        update_fields: list[str] = []
        for key in _EDITABLE_FIELDS:
            if key in data:
                val = data[key]
                # GenericIPAddressField rejects '' but accepts NULL.
                if key == 'ip_address' and val == '':
                    val = None
                # `name` cannot become blank — guard.
                if key == 'name':
                    if not isinstance(val, str) or not val.strip():
                        return Response({'detail': 'name cannot be blank'},
                                        status=drf_status.HTTP_400_BAD_REQUEST)
                    val = val.strip()
                setattr(asset, key, val)
                update_fields.append(key)
        if not update_fields:
            return Response(_serialize_asset(asset, detail=True))
        try:
            asset.save(update_fields=update_fields + ['updated_at']
                       if any(f.name == 'updated_at'
                              for f in asset._meta.fields)
                       else update_fields)
        except Exception as exc:
            return Response({'detail': f'Could not update asset: {exc}'},
                            status=drf_status.HTTP_400_BAD_REQUEST)
        payload = _serialize_asset(asset, detail=True)
        payload['vault_entries'] = _vault_entries_for_asset(asset, request.user)
        return Response(payload)

    payload = _serialize_asset(asset, detail=True)
    payload['vault_entries'] = _vault_entries_for_asset(asset, request.user)
    return Response(payload)


@api_view(['POST', 'DELETE'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def asset_vault_link_view(request, pk: int):
    """
    POST   /api/mobile/v1/assets/<id>/vault-links/         body: {password_id}
    DELETE /api/mobile/v1/assets/<id>/vault-links/?password_id=N

    Link / unlink a Vault Password to this asset via the existing
    `PasswordRelation(relation_type='asset')` row. Both sides must live
    in an org the caller has access to (so techs can't fish secrets out
    of another tenant by attaching them to one of their own assets).

    Gated on `assets_edit` (mutates the asset's relationships).
    """
    from assets.models import Asset
    from vault.models import Password, PasswordRelation

    org_ids = list(accessible_org_ids(request.user))
    try:
        asset = Asset.objects.get(pk=pk, organization_id__in=org_ids)
    except Asset.DoesNotExist:
        return Response({'detail': 'Not found'},
                        status=drf_status.HTTP_404_NOT_FOUND)
    if not user_has_perm(request.user, 'assets_edit'):
        return Response(
            {'detail': "You don't have permission to edit assets."},
            status=drf_status.HTTP_403_FORBIDDEN,
        )

    # password_id can come from POST body or DELETE query string.
    if request.method == 'POST':
        pwd_id = (request.data or {}).get('password_id')
    else:
        pwd_id = request.query_params.get('password_id')
    try:
        pwd_id = int(pwd_id) if pwd_id is not None else None
    except (TypeError, ValueError):
        return Response({'detail': 'password_id must be an integer'},
                        status=drf_status.HTTP_400_BAD_REQUEST)
    if pwd_id is None:
        return Response({'detail': 'password_id is required'},
                        status=drf_status.HTTP_400_BAD_REQUEST)

    try:
        password = Password.objects.get(pk=pwd_id, organization_id__in=org_ids)
    except Password.DoesNotExist:
        return Response({'detail': 'password not found / not accessible'},
                        status=drf_status.HTTP_404_NOT_FOUND)

    # Cross-org link prevention: refuse to link a vault entry from a
    # different org than the asset.
    if password.organization_id != asset.organization_id:
        return Response(
            {'detail': 'Cannot link across organizations'},
            status=drf_status.HTTP_400_BAD_REQUEST,
        )

    if request.method == 'POST':
        PasswordRelation.objects.get_or_create(
            password=password, relation_type='asset', relation_id=asset.id,
        )
        return Response(
            {'detail': 'linked',
             'asset_id': asset.id,
             'password_id': password.id},
            status=drf_status.HTTP_201_CREATED,
        )

    # DELETE
    PasswordRelation.objects.filter(
        password=password, relation_type='asset', relation_id=asset.id,
    ).delete()
    return Response(
        {'detail': 'unlinked',
         'asset_id': asset.id,
         'password_id': password.id},
    )


def _create_asset(request):
    """v3.17.454: backing for `POST /assets/`. Helper kept private to
    this module so the public surface stays a single `asset_list_view`."""
    from assets.models import Asset

    org_ids = list(accessible_org_ids(request.user))
    data = request.data or {}

    # organization_id required + must be accessible
    org_id_raw = data.get('organization_id')
    try:
        org_id = int(org_id_raw) if org_id_raw is not None else None
    except (TypeError, ValueError):
        return Response({'detail': 'invalid organization_id'},
                        status=drf_status.HTTP_400_BAD_REQUEST)
    if org_id is None:
        return Response({'detail': 'organization_id is required'},
                        status=drf_status.HTTP_400_BAD_REQUEST)
    if org_id not in org_ids:
        return Response({'detail': 'organization not accessible'},
                        status=drf_status.HTTP_403_FORBIDDEN)

    # name required
    name = (data.get('name') or '').strip()
    if not name:
        return Response({'detail': 'name is required'},
                        status=drf_status.HTTP_400_BAD_REQUEST)

    # Build kwargs from the whitelist; coerce empty strings to ''
    fields = {'organization_id': org_id, 'name': name}
    for key in _CREATABLE_FIELDS:
        if key == 'name':
            continue
        if key in data and data[key] is not None:
            fields[key] = data[key]

    # ip_address: model field is GenericIPAddressField with null=True; '' is invalid
    if fields.get('ip_address') == '':
        fields.pop('ip_address')

    try:
        asset = Asset.objects.create(**fields)
    except Exception as exc:
        return Response(
            {'detail': f'Could not create asset: {exc}'},
            status=drf_status.HTTP_400_BAD_REQUEST,
        )

    return Response(_serialize_asset(asset, detail=True),
                    status=drf_status.HTTP_201_CREATED)
