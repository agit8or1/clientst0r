"""Refusals anyone can cause without credentials (QC-03).

A token request naming no connection, or an unknown one, and a wrong
pairing code are repeatable by anyone who can reach the Connect API. They
are not written to the append-only audit chain one row per request (which
an attacker could grow without bound, each write locking the installation
row). Instead:

  * each refusal is counted in the folded API access refusal log
    (api_access.ApiAccessDecision, endpoint group "connect_api"): one row per
    source address and reason per minute, with an exact ``count``;
  * once a minute, ``summarise()`` (run by the connect_deliver_events
    scheduled task) writes ONE aggregated chain record
    (``refusals.summary``) for the closed minutes since the last summary.

Refusals for a known connection, and the lock-out of open invitations, are
still recorded individually in the chain.
"""
from __future__ import annotations

import ipaddress
import logging
from datetime import datetime, timedelta, timezone as dt_tz

from django.core.cache import cache
from django.db import DatabaseError
from django.db.models import F
from django.utils import timezone

logger = logging.getLogger('connect')

GROUP = 'connect_api'
INTEGRATION = 'agit8or_connect'
PREFIX = 'connect_'
CODE_REJECTED = 'connect_wrong_pairing_code'
TOKEN_PREFIX = 'connect_token_'
PAIRING_PATH = '/connect/v1/pairing/requests'
SUMMARY_OPERATION = 'refusals.summary'

FOLD_SECONDS = 60          # one row per source and reason per minute
SUMMARY_INTERVAL = 60      # at most one chain record per minute
SETTLE_SECONDS = 5         # a fold window is closed this long after it ends


def token_reason(code: str) -> str:
    return (TOKEN_PREFIX + str(code or 'refused'))[:40]


def _ip(value):
    try:
        return str(ipaddress.ip_address(str(value or '').strip()))
    except ValueError:
        return None


def note(reason: str, *, source_ip: str = '', path: str = '', method: str = 'POST', detail: str = ''):
    """Count one refusal on the folded row for (source, reason) this minute."""
    from api_access.models import SURFACE_CONNECT, ApiAccessDecision
    now = timezone.now()
    ip = _ip(source_ip)
    key = f'connect:deny:{ip or "-"}:{reason}'
    fresh = now - timedelta(seconds=FOLD_SECONDS)
    try:
        row_id = cache.get(key)
        if row_id and ApiAccessDecision.objects.filter(pk=row_id, created_at__gt=fresh).update(
                count=F('count') + 1, last_seen_at=now):
            return
        row = (ApiAccessDecision.objects.filter(source_ip=ip, reason=reason, endpoint_group=GROUP,
                                                integration=INTEGRATION, created_at__gt=fresh)
               .order_by('-created_at').first())
        if row is not None:
            ApiAccessDecision.objects.filter(pk=row.pk).update(count=F('count') + 1, last_seen_at=now)
        else:
            row = ApiAccessDecision.objects.create(
                created_at=now, last_seen_at=now, source_ip=ip, surface=SURFACE_CONNECT, endpoint_group=GROUP,
                integration=INTEGRATION, method=(method or '')[:10], path=(path or '')[:255], reason=reason[:40],
                detail=(detail or '')[:255])
        cache.set(key, row.pk, FOLD_SECONDS)
    except DatabaseError:
        logger.warning('could not record a Connect refusal', exc_info=True)


def _last_summary():
    from .models import ConnectAuditEvent
    return ConnectAuditEvent.objects.filter(operation=SUMMARY_OPERATION).order_by('-seq').first()


def summarise(now=None):
    """Write one chain record for the refusals counted in minutes that have
    closed since the previous summary. Returns the record, or None (nothing
    new, or a summary was written less than a minute ago)."""
    from api_access.models import ApiAccessDecision
    from . import audit_log
    now = now or timezone.now()
    now_us = int(now.timestamp() * 1_000_000)
    last = _last_summary()
    if last is not None and now_us - last.ts_us < SUMMARY_INTERVAL * 1_000_000:
        return None
    through_us = int((last.detail or {}).get('through_us') or 0) if last is not None else 0
    cutoff = now - timedelta(seconds=FOLD_SECONDS + SETTLE_SECONDS)
    qs = ApiAccessDecision.objects.filter(integration=INTEGRATION, endpoint_group=GROUP,
                                          reason__startswith=PREFIX, created_at__lte=cutoff)
    if through_us:
        qs = qs.filter(created_at__gt=datetime.fromtimestamp(through_us / 1_000_000, tz=dt_tz.utc))
    counts, sources, total = {}, set(), 0
    for reason, ip, n in qs.values_list('reason', 'source_ip', 'count'):
        counts[reason] = counts.get(reason, 0) + n
        sources.add(ip)
        total += n
    if not total:
        return None
    cutoff_us = int(cutoff.timestamp() * 1_000_000)
    return audit_log.record(SUMMARY_OPERATION, 'denied', detail={
        'through_us': cutoff_us, 'since_us': through_us, 'total': total, 'sources': len(sources),
        'counts': [f'{r}={c}' for r, c in sorted(counts.items())]})
