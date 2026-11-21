"""The Connect monitor job (Quick Connect increment D; DESIGN.md §8.1).

``connect_monitor`` is a ScheduledTask that runs every minute. Each run:

1. upkeep: rolls back expired Quick Connect attempts, schedules connections
   that have no check yet, dead-letters events past the age limit, prunes
   delivered history (90 days) and old diagnostic runs, and summarises
   unauthenticated refusals into the audit chain;
2. loops for at most ``BUDGET`` seconds of wall time: picks connections
   whose ``next_check_at`` is due (oldest first, at most ``PER_PASS``),
   claims each with a compare-and-set on ``next_check_at`` and checks it,
   drains due events in order, then sleeps until the next due time
   (minimum 1 s) or exits when nothing is due within the budget;
3. per-connection exceptions are caught, logged and rescheduled on the
   backoff ladder, so one bad connection never stops the others and the
   run always returns (a crashed run would block the task for hours).
4. a full diagnostics run (the fifteen steps) every 15 minutes for each
   active, healthy connection, and once on recovery from Offline: at most
   ``FULL_PER_PASS`` per pass and only while ``FULL_MIN_REMAINING`` seconds
   of the budget are left, so it never pushes the light checks out. A
   security failure it finds blocks the connection (§7.3); anything else is
   left to the light checks' hysteresis;
5. the Connect audit chain head is anchored into the main audit log once an
   hour (C-05, connect/audit_anchor.py).

Concurrency is bounded: ScheduledTask.claim() gives one runner, checks run
one after another, at most ``PER_PASS`` per pass, and the compare-and-set
keeps a manual retest or a second runner from double-checking a
connection. Everything is in the database, so a restart resumes from
``next_check_at`` / ``retry_step`` instead of starting the ladder over.

Never selected: suspended, revoked, failed and Security Blocked connections,
and nothing at all while the kill switch is engaged.
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger('connect')

BUDGET = 50.0
PER_PASS = 20
DIAGNOSTIC_RETENTION = timedelta(days=30)
DIAGNOSTIC_KEEP = 50
FULL_PER_PASS = 1
FULL_MIN_REMAINING = 20.0


def upkeep(now=None) -> dict:
    from .models import Connection as C
    from . import denials, events, quick_connect
    now = now or timezone.now()
    out = {'reaped': 0, 'expired_events': 0, 'pruned_events': 0, 'pruned_runs': 0, 'scheduled': 0}
    for name, fn in (('reaped', quick_connect.reap), ('expired_events', events.expire_aged),
                     ('pruned_events', events.prune_delivered), ('pruned_runs', prune_diagnostics)):
        try:
            out[name] = fn(now) or 0
        except Exception:
            logger.exception('connect monitor upkeep step %s failed', name)
    # Active connections without a schedule (existing before this release,
    # or committed by an older code path) get their first check now.
    out['scheduled'] = C.objects.filter(state=C.ACTIVE, next_check_at__isnull=True).update(next_check_at=now)
    for pk in C.objects.filter(state=C.TESTING, next_check_at__isnull=True, retest_until__isnull=True
                               ).values_list('pk', flat=True):
        from . import health
        health.arm_retests(pk, now)
        out['scheduled'] += 1
    try:
        denials.summarise()
    except Exception:
        logger.exception('connect monitor could not summarise refusals')
    from . import audit_anchor
    out['anchored'] = 1 if audit_anchor.maybe_anchor(now) is not None else 0
    from . import incidents
    try:
        out['settled'] = incidents.settle(now)
    except Exception:
        logger.exception('connect monitor could not settle incident tickets')
    return out


def prune_diagnostics(now=None) -> int:
    from .models import DiagnosticRun
    now = now or timezone.now()
    n = DiagnosticRun.objects.filter(started_at__lt=now - DIAGNOSTIC_RETENTION).delete()[0]
    for cid in DiagnosticRun.objects.values_list('connection_id', flat=True).distinct():
        keep = list(DiagnosticRun.objects.filter(connection_id=cid).order_by('-started_at')
                    .values_list('pk', flat=True)[:DIAGNOSTIC_KEEP])
        n += DiagnosticRun.objects.filter(connection_id=cid).exclude(pk__in=keep).delete()[0]
    return n


def _due(now, exclude):
    from .models import Connection as C
    return list(C.objects.filter(state__in=(C.ACTIVE, C.TESTING), next_check_at__lte=now)
                .exclude(pk__in=exclude).order_by('next_check_at')[:PER_PASS])


def run_pass(now=None, rng=None, remaining=None) -> dict:
    """One pass: check each due connection once (claimed), then the
    periodic full diagnostics (bounded), then drain."""
    from . import events, health, identity
    now = now or timezone.now()
    out = {'checked': 0, 'errors': 0, 'delivered': 0, 'full_runs': 0}
    if identity.kill_switch_engaged():
        return out
    seen, full = set(), []
    for conn in _due(now, seen):
        seen.add(conn.pk)
        if not health.claim(conn, now):
            continue
        was = conn.health
        try:
            health.check_one(conn, now, rng)
            out['checked'] += 1
        except Exception:
            out['errors'] += 1
            logger.exception('connect monitor check of %s failed', conn.pk)
            _reschedule_after_error(conn, now)
            continue
        full.append((conn, was))
    # Only the scheduled job (run(), which knows its budget) adds full runs.
    if remaining is not None and remaining() >= FULL_MIN_REMAINING:
        out['full_runs'] = full_diagnostics(full, now)
    try:
        out['delivered'] = events.deliver_due()['delivered']
    except Exception:
        logger.exception('connect monitor event drain failed')
    return out


def full_diagnostics(checked, now=None, limit=FULL_PER_PASS) -> int:
    """The fifteen steps for connections just checked that are due a full
    run (every 15 minutes) or just recovered from Offline. Read-only runs;
    a security failure in steps 1-13 is acted on here (the monitor acts,
    diagnostics only report)."""
    from .models import Connection as C, DiagnosticRun
    from . import diagnostics, health, identity
    now = now or timezone.now()
    n = 0
    for conn, was in checked:
        if n >= limit or identity.kill_switch_engaged():
            break
        conn.refresh_from_db()
        recovered = was == C.HEALTH_OFFLINE and conn.health == C.HEALTH_CONNECTED
        if conn.state != C.ACTIVE or not (recovered or diagnostics.periodic_due(conn, now)):
            continue
        if recovered and DiagnosticRun.objects.filter(connection=conn, trigger=DiagnosticRun.MONITOR,
                                                      started_at__gt=now - timedelta(minutes=5)).exists():
            continue
        n += 1
        try:
            row = diagnostics.run(conn, None, trigger=DiagnosticRun.MONITOR)
        except diagnostics.DiagnosticsRefused:
            continue
        except Exception:
            logger.exception('connect monitor full diagnostics of %s failed', conn.pk)
            continue
        code = _security_code(row)
        if code:
            conn.refresh_from_db()
            if conn.state == C.ACTIVE:
                health.security_failure(conn, code, {'run': row.pk})
    return n


def _security_code(row) -> str:
    from . import diagnostics, health
    for s in row.steps or []:
        if s.get('status') != 'fail' or s.get('id') not in diagnostics.REQUIRED:
            continue
        code = s.get('code') or ''
        if s.get('id') == 'token' and code in health.PEER_REVOKED_CODES:
            return 'peer_revoked'
        if health.classify(code) == 'security' or code == 'identity_changed':
            return code
    return ''


def _reschedule_after_error(conn, now):
    from .models import Connection as C
    from . import health
    step = conn.retry_step or 0
    C.objects.filter(pk=conn.pk, state__in=(C.ACTIVE, C.TESTING)).update(
        next_check_at=now + timedelta(seconds=health.backoff_delay(step)),
        retry_step=min(step + 1, len(health.LADDER) - 1))


def next_due():
    from .models import Connection as C
    return (C.objects.filter(state__in=(C.ACTIVE, C.TESTING), next_check_at__isnull=False)
            .order_by('next_check_at').values_list('next_check_at', flat=True).first())


def run(budget=BUDGET, *, clock=time.monotonic, sleep=time.sleep, rng=None) -> dict:
    """The scheduled job. Returns totals; never raises for a connection."""
    from . import identity
    started = clock()
    totals = {'passes': 0, 'checked': 0, 'errors': 0, 'delivered': 0, 'full_runs': 0}
    totals.update(upkeep())
    while True:
        if identity.kill_switch_engaged():
            totals['kill_switch'] = True
            break
        res = run_pass(rng=rng, remaining=lambda: budget - (clock() - started))
        totals['passes'] += 1
        for k in ('checked', 'errors', 'delivered', 'full_runs'):
            totals[k] += res[k]
        remaining = budget - (clock() - started)
        nxt = next_due()
        if remaining <= 1 or nxt is None:
            break
        wait = (nxt - timezone.now()).total_seconds()
        if wait > remaining - 1:
            break
        sleep(max(1.0, wait))
    return totals
