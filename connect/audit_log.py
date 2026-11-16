"""Append-only, hash-chained Connect audit (models.ConnectAuditEvent).

`record()` never takes a secret: callers pass ids, operation names, scopes
and results. Writes are serialized on the InstallationIdentity row so two
workers cannot fork the chain.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Iterable, Optional

from django.db import transaction

from agit8or_connect import audit as chain

logger = logging.getLogger('connect')

_FORBIDDEN_DETAIL_KEYS = ('token', 'assertion', 'private', 'secret', 'code', 'proof', 'signature', 'password',
                          'jws', 'dpop')


def _clean(detail: Optional[dict]) -> dict:
    out = {}
    for k, v in (detail or {}).items():
        if any(f in k.lower() for f in _FORBIDDEN_DETAIL_KEYS):
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v if not isinstance(v, str) else v[:300]
        elif isinstance(v, (list, tuple)):
            out[k] = [str(x)[:120] for x in list(v)[:50]]
    return out


def actor_for(user=None, app: str = '') -> str:
    if user is not None and getattr(user, 'pk', None):
        return f'user:{user.pk}:{user.get_username()}'[:160]
    if app:
        return f'app:{app}'[:160]
    return 'system'


def record(operation: str, result: str = 'ok', *, connection=None, user=None, app: str = '', tenant: str = '',
           scopes: Iterable[str] = (), correlation_id: str = '', detail: Optional[dict] = None):
    from .identity import get as get_identity
    from .models import ConnectAuditEvent, InstallationIdentity
    ident = get_identity()
    with transaction.atomic():
        InstallationIdentity.objects.select_for_update().get(pk=ident.pk)
        last = ConnectAuditEvent.objects.order_by('-seq').only('seq', 'hash').first()
        ev = ConnectAuditEvent(
            seq=(last.seq + 1) if last else 1, ts_us=int(time.time() * 1_000_000),
            connection_id=str(getattr(connection, 'pk', connection) or ''), initiating_app=app[:128],
            tenant=str(tenant or '')[:128], actor=actor_for(user, app), operation=operation[:64],
            scopes=sorted(set(scopes or ())), result=str(result)[:32],
            correlation_id=(correlation_id or str(uuid.uuid4()))[:64], detail=_clean(detail),
            prev_hash=last.hash if last else chain.GENESIS, hash='')
        ev.hash = chain.entry_hash(ev.prev_hash, ev.record())
        ev.save()
    return ev


def verify() -> Optional[int]:
    """None if the chain is intact, else the seq of the first bad row."""
    from .models import ConnectAuditEvent
    rows = list(ConnectAuditEvent.objects.order_by('seq'))
    bad = chain.verify_chain((r.record(), r.prev_hash, r.hash) for r in rows)
    if bad is None:
        for i, r in enumerate(rows):
            if r.seq != i + 1:
                return r.seq   # a removed row leaves a gap
        return None
    return rows[bad].seq
