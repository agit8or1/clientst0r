"""
Reconciliation for Rem0te connections: heal whatever a missed push, an
outage or a restart left behind, and record the outcome where an
administrator sees it (integrations.rem0te.health).

Run every minute by the scheduler task `poll_analysis_jobs` (and by hand
with `manage.py rem0te_reconcile`). Per connection:

  1. Capabilities re-check when due: hourly after a good check; after a
     failure 1, 2, 4 … minutes up to an hour (exponential backoff, kept in
     the check document as `failures`); at once when an event arrived that
     this ClientSt0r could not understand (`recheck` flag).
  2. Alert events after the gap-free cursor (GET /alerts/events), applied
     exactly once; an event that cannot be applied is recorded and skipped
     so the cursor never loops on it, with a visible health issue.
  3. Ticket links that are due (POST /alerts/{id}/ticket, own backoff).
  4. Open action proposals' status (GET /action-proposals/{id}).

Analysis jobs are polled by the same task (psa_ai.services.processor.poll).
Nothing here raises: one broken connection never stops the others.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from . import health

logger = logging.getLogger('integrations.rem0te')

CHECK_EVERY = timedelta(hours=1)
RETRY_BASE = timedelta(minutes=1)
RETRY_MAX = timedelta(hours=1)


def next_check_at(doc):
    """When the next capabilities check is due (None = now)."""
    when = parse_datetime(str((doc or {}).get('checked_at') or '').replace('Z', '+00:00'))
    if when is None or (doc or {}).get('recheck'):
        return None
    if timezone.is_naive(when):
        when = timezone.make_aware(when, timezone.utc)
    if doc.get('ok'):
        return when + CHECK_EVERY
    failures = max(1, int(doc.get('failures') or 1))
    return when + min(RETRY_MAX, RETRY_BASE * 2 ** (failures - 1))


def check_due(connection, now=None) -> bool:
    from . import pairing
    at = next_check_at(pairing.last_check(connection))
    return at is None or (now or timezone.now()) >= at


def reconcile(connection, force_check=False) -> dict:
    """One pass for one connection. Returns counts."""
    from . import actions, alerts, pairing
    out = {'checked': False, 'events': 0, 'links': 0, 'proposals': 0, 'error': ''}
    s = pairing.settings(connection)
    if not s['enabled']:
        health.touch(connection, success=False)
        return out
    try:
        if force_check or check_due(connection):
            pairing.check(connection)
            connection.refresh_from_db()
            out['checked'] = True
        if pairing.is_processor(connection):
            if out['checked']:
                out['events'] += alerts.reprocess_skipped(connection)
            out['events'] += alerts.poll(connection)
            out['proposals'] = actions.poll_open(connection=connection)
    except Exception as e:  # pragma: no cover - defensive
        logger.exception('reconciling Rem0te connection %s failed', connection.pk)
        out['error'] = e.__class__.__name__
    ok = pairing.last_check(connection).get('ok') and not out['error']
    health.touch(connection, success=bool(ok))
    return out


def reconcile_all(stdout=None) -> int:
    from integrations.models import RMMConnection
    n = 0
    for conn in RMMConnection.objects.filter(is_active=True, provider_type='rem0te').order_by('pk'):
        try:
            r = reconcile(conn)
            n += 1
            if stdout and (r['events'] or r['error']):
                stdout.write(f'Rem0te {conn.name}: {r["events"]} alert event(s) recovered'
                             + (f', error {r["error"]}' if r['error'] else '') + '.')
        except Exception:
            logger.exception('reconciling Rem0te connection %s failed', conn.pk)
    return n
