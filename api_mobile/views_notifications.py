"""
Mobile API push-notification registration (v3.17.463).
"""
from __future__ import annotations

import uuid

from .authentication import MobileTokenAuthentication
from rest_framework.decorators import (
    api_view, authentication_classes, permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


@api_view(['POST'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def register_push_view(request):
    """
    POST /api/mobile/v1/notifications/register/

    Body: `{token, platform?, device_id?, name?, enabled?}`. Idempotent —
    same `device_id` updates in place. If `device_id` is omitted, looks
    for an existing device with the same token; if none, creates one.

    `token` is an Expo push token (format `ExponentPushToken[...]`).
    """
    from field_ops.models import MobileDevice

    data = request.data or {}
    token = (data.get('token') or '').strip()
    if not token:
        return Response({'detail': 'token is required'}, status=400)

    platform = (data.get('platform') or 'android').lower()
    if platform not in ('android', 'ios'):
        return Response({'detail': 'platform must be android or ios'}, status=400)

    device_id_raw = data.get('device_id')
    if device_id_raw:
        try:
            device_id = uuid.UUID(str(device_id_raw))
        except (ValueError, TypeError):
            return Response({'detail': 'device_id must be a UUID'}, status=400)
    else:
        # No device_id — try to find an existing record by token.
        existing = MobileDevice.objects.filter(
            user=request.user, expo_push_token=token, revoked=False,
        ).first()
        device_id = existing.device_id if existing else uuid.uuid4()

    name = (data.get('name') or '')[:200]
    enabled = bool(data.get('enabled', True))

    device, created = MobileDevice.objects.update_or_create(
        device_id=device_id,
        defaults={
            'user': request.user,
            'platform': platform,
            'name': name,
            'expo_push_token': token,
            'notifications_enabled': enabled,
            'revoked': False,
        },
    )
    return Response({
        'device_id': str(device.device_id),
        'created': created,
        'notifications_enabled': device.notifications_enabled,
    }, status=201 if created else 200)


@api_view(['POST'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def deregister_push_view(request):
    """
    POST /api/mobile/v1/notifications/deregister/

    Body: `{device_id}`. Mark the device revoked so no further pushes
    are sent. Idempotent.
    """
    from field_ops.models import MobileDevice

    device_id_raw = (request.data.get('device_id') or '').strip() if request.data else ''
    if not device_id_raw:
        return Response({'detail': 'device_id is required'}, status=400)
    try:
        device_id = uuid.UUID(device_id_raw)
    except (ValueError, TypeError):
        return Response({'detail': 'device_id must be a UUID'}, status=400)

    MobileDevice.objects.filter(
        user=request.user, device_id=device_id,
    ).update(revoked=True, expo_push_token='')
    return Response({'detail': 'ok'})
