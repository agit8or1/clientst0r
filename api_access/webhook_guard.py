"""Shared checks for inbound webhook receivers (roadmap 81.5).

Every receiver keeps its own credential (URL token and / or HMAC secret). This
module adds what they share:

* ``read_body`` — a size cap checked against the declared length before the
  body is read, and against the bytes actually read (413).
* ``timestamp`` — the optional ``X-Cst0r-Timestamp`` header (Unix seconds).
  When a sender includes it, the signature must cover ``"<ts>." + body`` and
  the time must be within ``TOLERANCE`` seconds of ours, so a captured request
  cannot be replayed later. Senders that sign only the body keep working.
* ``claim`` / ``release`` — replay protection. A delivery is claimed by a
  digest of the signed material; a second identical delivery inside the
  window is a replay and is acknowledged without being processed again.
  Release the claim when processing fails so the sender's retry is accepted.
"""
import hashlib
import random
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone

TIMESTAMP_HEADER = 'HTTP_X_CST0R_TIMESTAMP'
TOLERANCE = 300                      # seconds either side
WINDOW_TIMESTAMPED = TOLERANCE * 2 + 60
WINDOW_UNTIMESTAMPED = 24 * 3600     # identical body within a day = replay


class Refused(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message

    def response(self):
        return JsonResponse({'ok': False, 'error': self.message}, status=self.status)


def read_body(request, max_bytes):
    try:
        declared = int(request.META.get('CONTENT_LENGTH') or 0)
    except ValueError:
        declared = 0
    if declared > max_bytes:
        raise Refused(413, 'request body too large')
    body = request.body or b''
    if len(body) > max_bytes:
        raise Refused(413, 'request body too large')
    return body


def timestamp(request, now=None):
    """The sender's timestamp (int) if it sent one; Refused if it is bad or stale."""
    raw = (request.META.get(TIMESTAMP_HEADER) or '').strip()
    if not raw:
        return None
    if not raw.isdigit() or len(raw) > 12:
        raise Refused(401, 'invalid timestamp')
    ts = int(raw)
    now = int((now or timezone.now()).timestamp())
    if abs(now - ts) > TOLERANCE:
        raise Refused(401, 'timestamp outside the allowed window')
    return ts


def signed_material(ts, body, *parts):
    """What the signature covers: body alone, or "<ts>.<parts...>.<body>"."""
    if ts is None:
        return body
    prefix = '.'.join([str(ts), *parts]) + '.'
    return prefix.encode('utf-8') + body


def digest(receiver, material):
    return hashlib.sha256(receiver.encode('utf-8') + b'\0' + material).hexdigest()


def claim(receiver, material, timestamped):
    """True for a first delivery; False for a replay inside the window."""
    from .models import WebhookDelivery
    now = timezone.now()
    window = WINDOW_TIMESTAMPED if timestamped else WINDOW_UNTIMESTAMPED
    key = digest(receiver, material)
    if random.random() < 0.01:
        WebhookDelivery.objects.filter(expires_at__lt=now).delete()
    WebhookDelivery.objects.filter(receiver=receiver, digest=key, expires_at__lt=now).delete()
    try:
        with transaction.atomic():
            WebhookDelivery.objects.create(receiver=receiver, digest=key,
                                           expires_at=now + timedelta(seconds=window))
    except IntegrityError:
        return False
    return True


def release(receiver, material):
    from .models import WebhookDelivery
    WebhookDelivery.objects.filter(receiver=receiver, digest=digest(receiver, material)).delete()


def duplicate_response():
    """Replays are acknowledged (2xx) so a sender's retry loop stops, but not processed."""
    return JsonResponse({'ok': True, 'duplicate': True})
