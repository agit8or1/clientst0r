"""
Expo push notification dispatch (v3.17.463).

The mobile app registers its `ExponentPushToken[...]` via
`POST /api/mobile/v1/notifications/register/`. Server-side code calls
`send_push_to_user(user, ...)` from wherever it wants to notify — for
this release, only ticket-assignment changes trigger one push.

Routing is via Expo's relay (https://exp.host/--/api/v2/push/send),
which forwards to FCM on Android and APNS on iOS using the project's
EAS credentials. No per-deployment FCM project setup is required.
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request

logger = logging.getLogger('api_mobile.push')

EXPO_ENDPOINT = 'https://exp.host/--/api/v2/push/send'


def _post_to_expo(messages: list[dict], timeout: int = 8) -> None:
    """Single HTTP POST to Expo. Swallows errors — push delivery must
    never block the calling code path. Logs failures for triage."""
    if not messages:
        return
    try:
        body = json.dumps(messages).encode('utf-8')
        req = urllib.request.Request(
            EXPO_ENDPOINT, data=body,
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status >= 300:
                logger.warning('expo push non-200: %s', resp.status)
    except urllib.error.URLError as e:
        logger.warning('expo push failed: %s', e)
    except Exception as e:  # noqa: BLE001 — never raise
        logger.exception('expo push error: %s', e)


def send_push_to_user(
    user, title: str, body: str, data: dict | None = None,
) -> int:
    """
    Send a push to every active, opted-in mobile device for `user`.
    Returns the number of tokens dispatched. Returns 0 if the user has
    no devices, all are revoked, all are muted, or none have an Expo
    token registered.

    Async: actual HTTP call to Expo is fired-and-forgotten on a
    background thread so a slow Expo response never blocks the
    request that triggered the notification.
    """
    if user is None or not getattr(user, 'is_authenticated', True):
        return 0
    # A deactivated account gets nothing, even while still an assignee.
    if not getattr(user, 'is_active', True):
        return 0
    try:
        from field_ops.models import MobileDevice
        devices = MobileDevice.objects.filter(
            user=user, revoked=False, notifications_enabled=True,
        ).exclude(expo_push_token='')
        tokens = [d.expo_push_token for d in devices if d.expo_push_token]
    except Exception:
        return 0

    if not tokens:
        return 0

    messages = [
        {
            'to': t,
            'title': title[:120],
            'body': body[:240],
            'data': data or {},
            'sound': 'default',
            'priority': 'high',
        }
        for t in tokens
    ]

    # Fire and forget. Expo can sometimes take 1–3s on retry.
    threading.Thread(
        target=_post_to_expo, args=(messages,), daemon=True,
    ).start()
    return len(tokens)
