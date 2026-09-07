"""
Mobile API network config endpoints (v3.17.558).

Phase 34 stores versioned device configurations. The field use is narrow and
specific: a technician standing in front of a switch wants to read what it was
configured to do, and to capture what it is doing now before they change
anything.

What is deliberately absent: no editing, and no vault credentials leave the
server. "Collect now" runs the same server-side collector the web UI does — the
phone never holds a device password or opens an SSH session.
"""
from __future__ import annotations

from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import (
    api_view, authentication_classes, permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permission_utils import user_has_perm

from .scoping import accessible_org_ids

# Same set the web device list uses. A config backup of a laptop is not a thing.
NETWORK_ASSET_TYPES = [
    'switch', 'router', 'firewall', 'load_balancer',
    'wireless_ap', 'wireless_controller', 'modem', 'gateway',
    'bridge', 'console_server',
]

# A running-config runs to thousands of lines. Sending the whole thing to a
# phone on a client's guest wifi is a slow way to answer a question that is
# usually about one VLAN, so the body is capped and the client is told.
MAX_BODY_CHARS = 200_000


def _serialize_backup(backup, *, include_body=False):
    out = {
        'id': backup.id,
        'captured_at': backup.captured_at.isoformat(),
        'last_seen_at': backup.last_seen_at.isoformat(),
        'source': backup.source,
        'source_label': backup.get_source_display(),
        'firmware_version': backup.firmware_version,
        'line_count': backup.line_count,
        'is_approved': backup.is_approved,
        'drift_state': backup.drift_state,
        'note': backup.note,
    }
    if include_body:
        body = backup.body or ''
        out['body'] = body[:MAX_BODY_CHARS]
        out['truncated'] = len(body) > MAX_BODY_CHARS
    return out


@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def device_list_view(request):
    """
    GET /api/mobile/v1/netconfig/devices/?organization_id=&search=

    Network devices with how recently each was captured.
    """
    from django.db.models import Count, Max
    from assets.models import Asset

    org_ids = accessible_org_ids(request.user)
    qs = (Asset.objects
          .filter(organization_id__in=org_ids,
                  asset_type__in=NETWORK_ASSET_TYPES)
          .select_related('organization'))

    search = (request.query_params.get('search') or '').strip()
    if search:
        from django.db.models import Q
        qs = qs.filter(Q(name__icontains=search)
                       | Q(hostname__icontains=search)
                       | Q(ip_address__icontains=search))

    organization_id = request.query_params.get('organization_id')
    if organization_id:
        try:
            oid = int(organization_id)
            qs = qs.filter(organization_id=oid) if oid in org_ids else qs.none()
        except ValueError:
            pass

    # Annotated rather than a query per device — a comms room full of switches
    # would otherwise be a hundred round trips.
    qs = qs.annotate(
        backup_count=Count('config_backups'),
        latest_capture=Max('config_backups__last_seen_at'),
    ).order_by('name')[:200]

    return Response({'results': [{
        'id': a.id,
        'name': a.name,
        'asset_type': a.asset_type,
        'hostname': a.hostname,
        'ip_address': a.ip_address,
        'organization_id': a.organization_id,
        'organization_name': a.organization.name if a.organization_id else None,
        'backup_count': a.backup_count,
        'latest_capture': (a.latest_capture.isoformat()
                           if a.latest_capture else None),
    } for a in qs]})


@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def device_detail_view(request, pk: int):
    """GET /api/mobile/v1/netconfig/devices/<asset_id>/ — snapshot history."""
    from assets.models import Asset
    from netconfig.models import BackupTarget, ConfigBackup

    org_ids = accessible_org_ids(request.user)
    try:
        asset = Asset.objects.select_related('organization').get(
            pk=pk, organization_id__in=org_ids,
            asset_type__in=NETWORK_ASSET_TYPES)
    except Asset.DoesNotExist:
        return Response({'detail': 'Not found'}, status=404)

    backups = ConfigBackup.objects.filter(asset=asset).order_by('-captured_at')[:50]
    target = BackupTarget.objects.filter(asset=asset).select_related(
        'credential').first()

    return Response({
        'id': asset.id,
        'name': asset.name,
        'asset_type': asset.asset_type,
        'hostname': asset.hostname,
        'ip_address': asset.ip_address,
        'organization_name': asset.organization.name if asset.organization_id else None,
        'current_firmware': ConfigBackup.current_firmware(asset),
        'can_collect': target is not None and target.blocking_reason() is None,
        # Why not, when not. A greyed-out button with no explanation is the
        # thing that generates the support call.
        'collect_blocked_reason': target.blocking_reason() if target else
            'No SSH connection configured for this device.',
        'backups': [_serialize_backup(b) for b in backups],
    })


@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def backup_detail_view(request, pk: int):
    """GET /api/mobile/v1/netconfig/backups/<id>/ — the stored config text."""
    from netconfig.models import ConfigBackup

    org_ids = accessible_org_ids(request.user)
    try:
        backup = ConfigBackup.objects.select_related('asset').get(
            pk=pk, organization_id__in=org_ids)
    except ConfigBackup.DoesNotExist:
        return Response({'detail': 'Not found'}, status=404)

    payload = _serialize_backup(backup, include_body=True)
    payload['asset_id'] = backup.asset_id
    payload['asset_name'] = backup.asset.name
    return Response(payload)


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def collect_view(request, pk: int):
    """
    POST /api/mobile/v1/netconfig/devices/<asset_id>/collect/

    Runs the server-side collector. The phone never holds a device credential
    and never opens an SSH session — it asks the server to, which is the only
    reason this is safe to expose to a device on a client's guest wifi.
    """
    from assets.models import Asset
    from netconfig.collector import collect_target
    from netconfig.models import BackupTarget

    org_ids = accessible_org_ids(request.user)
    try:
        asset = Asset.objects.get(pk=pk, organization_id__in=org_ids,
                                  asset_type__in=NETWORK_ASSET_TYPES)
    except Asset.DoesNotExist:
        return Response({'detail': 'Not found'}, status=404)

    if not user_has_perm(request.user, 'assets_edit'):
        return Response(
            {'detail': "You don't have permission to capture device configs."},
            status=403)

    target = BackupTarget.objects.filter(asset=asset).select_related(
        'credential').first()
    if target is None:
        return Response(
            {'detail': 'No SSH connection is configured for this device.'},
            status=400)

    result = collect_target(target, user=request.user)
    return Response({
        'ok': result['ok'],
        'changed': result['changed'],
        'message': result['message'],
        'backup_id': result['backup'].pk if result['backup'] else None,
    }, status=200 if result['ok'] else 400)
