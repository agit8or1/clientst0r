"""Background execution of rehearsal work (fetch, build, apply, rollback).

The web request only enqueues; the scheduler (``clientst0r-scheduler``, every
minute) runs ``manage.py run_migration_rehearsals``, which calls
``run_pending()``.

Guarantees:

* one task per plan: ``enqueue`` is a conditional UPDATE that only succeeds
  when the plan has no queued/running task, so two concurrent POSTs cannot
  queue two runs;
* one runner per task: ``claim`` is a conditional UPDATE that sets a fresh
  lease token; only the worker whose token is stored may heartbeat, report
  or finish. A second worker claiming the same plan gets zero rows and does
  nothing;
* a crashed run is recoverable: a "running" task whose heartbeat is older
  than ``IMPORT_REHEARSAL_LEASE_SECONDS`` may be claimed again. Fetch and
  build are rerun from scratch (they replace the staging/plan in one
  transaction); apply resumes - applied items are never touched again;
  rollback is one transaction, so a crash leaves nothing half-done;
* the lease is checked before every item / request, so a worker that lost
  its lease stops instead of racing the new one;
* long applies are sliced: a run stops between items after
  ``IMPORT_REHEARSAL_SLICE_SECONDS`` and re-queues itself, so the shared
  scheduler loop is not blocked by one big customer.
"""
from __future__ import annotations

import logging
import secrets
import time
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .redact import redact_text

logger = logging.getLogger('imports')

ACTIVE_STATES = ('queued', 'running')


class LeaseLost(Exception):
    """Another worker took over this task; stop without writing more."""


def lease_seconds():
    return int(getattr(settings, 'IMPORT_REHEARSAL_LEASE_SECONDS', 600))


def slice_seconds():
    return int(getattr(settings, 'IMPORT_REHEARSAL_SLICE_SECONDS', 50))


def enqueue(plan, action, user):
    """Queue ``action`` for ``plan``. Returns False if a task is already
    queued or running for it (nothing is changed then)."""
    from imports.models import MigrationPlan
    if action not in dict(MigrationPlan.TASK_ACTIONS):
        raise ValueError(f'unknown action {action}')
    now = timezone.now()
    updated = (MigrationPlan.objects.filter(pk=plan.pk).exclude(task_state__in=ACTIVE_STATES)
               .update(task_action=action, task_state='queued', task_requested_by=user,
                       task_queued_at=now, task_started_at=None, task_heartbeat_at=None,
                       task_finished_at=None, task_lease='', task_attempts=0,
                       task_progress={'message': 'queued'}, task_error='', task_result={}))
    plan.refresh_from_db()
    return bool(updated)


def _claimable(now):
    stale = now - timedelta(seconds=lease_seconds())
    return Q(task_state='queued') | Q(task_state='running', task_heartbeat_at__lt=stale) | \
        Q(task_state='running', task_heartbeat_at__isnull=True)


def claim(plan_id):
    """Take the task of ``plan_id``. Returns the lease token, or None if it
    is not claimable (idle, finished, or running with a fresh heartbeat)."""
    from imports.models import MigrationPlan
    from django.db.models import F
    now = timezone.now()
    token = secrets.token_hex(16)
    updated = (MigrationPlan.objects.filter(_claimable(now), pk=plan_id)
               .update(task_state='running', task_lease=token, task_heartbeat_at=now,
                       task_started_at=now, task_attempts=F('task_attempts') + 1))
    return token if updated else None


def _beat(plan_id, token, **progress):
    from imports.models import MigrationPlan
    updated = MigrationPlan.objects.filter(pk=plan_id, task_lease=token, task_state='running').update(
        task_heartbeat_at=timezone.now(), task_progress=progress)
    if not updated:
        raise LeaseLost(f'lease on rehearsal {plan_id} lost')


def _finish(plan_id, token, state, error='', result=None, progress=None):
    from imports.models import MigrationPlan
    fields = dict(task_state=state, task_error=error, task_result=result or {},
                  task_finished_at=timezone.now(), task_lease='')
    if state == 'queued':  # sliced apply: hand back to the queue
        fields.update(task_finished_at=None, task_heartbeat_at=None)
    if progress is not None:
        fields['task_progress'] = progress
    return MigrationPlan.objects.filter(pk=plan_id, task_lease=token).update(**fields)


def _audit(plan, user, action, description, extra=None, success=True):
    from audit.models import AuditLog
    AuditLog.log(user=user, action=action, organization=plan.organization,
                 object_type='migration_rehearsal', object_id=plan.pk, object_repr=str(plan)[:255],
                 description=description, path='scheduler:run_migration_rehearsals',
                 extra_data=extra or {}, success=success)


def _run_stage(plan, user, beat):
    from . import planner
    from .sources import stager_for
    stager = stager_for(plan)
    stager.heartbeat = lambda message='': beat(message=message)
    stager.stage()
    beat(message='building plan')
    planner.build_plan(plan)
    plan.import_job.add_log(f'Staged {plan.staged.count()} source record(s) and built the plan')
    return {'staged': plan.staged.count(), 'items': plan.items.count()}


def _run_build(plan, user, beat):
    from . import planner
    planner.build_plan(plan)
    return {'items': plan.items.count()}


def _run_apply(plan, user, beat):
    from .applier import apply_plan
    deadline = time.monotonic() + slice_seconds()
    counts = apply_plan(plan, user, heartbeat=lambda done, total: beat(
        done=done, total=total, message=f'applying {done}/{total}'), deadline=deadline)
    if counts.get('paused'):
        return counts
    _audit(plan, user, 'import', f"Applied migration rehearsal: {counts['applied']} applied, "
                                 f"{counts['skipped']} skipped, {counts['failed']} failed",
           extra={'counts': counts, 'plan_hash': plan.reviewed_plan_hash})
    return counts


def _run_rollback(plan, user, beat):
    from .undo import rollback_plan
    report = rollback_plan(plan, user)
    summary = {k: len(v) for k, v in report.items() if isinstance(v, list)}
    summary['complete'] = report['complete']
    summary['kept'] = report['kept'][:50]
    _audit(plan, user, 'delete', 'Rolled back migration rehearsal'
           + ('' if report['complete'] else ' (partial - later edits kept)'), extra=summary)
    return summary


RUNNERS = {'stage': _run_stage, 'build': _run_build, 'apply': _run_apply, 'rollback': _run_rollback}


def run_claimed(plan_id, token):
    """Run the claimed task of ``plan_id``. Returns the final task state."""
    from imports.models import MigrationPlan
    from .planner import PlanChanged
    plan = MigrationPlan.objects.select_related('import_job').get(pk=plan_id)
    user = plan.task_requested_by
    action = plan.task_action

    def beat(**progress):
        _beat(plan_id, token, **progress)

    try:
        beat(message=f'{action} started')
        result = RUNNERS[action](plan, user, beat)
    except LeaseLost:
        logger.warning('Rehearsal %s: lease lost during %s; another worker continues', plan_id, action)
        return 'lost'
    except Exception as exc:  # noqa: BLE001 - recorded on the plan
        message = redact_text(f'{type(exc).__name__}: {exc}',
                              secrets=(plan.import_job.source_api_key,))[:2000]
        if isinstance(exc, PlanChanged):
            _audit(plan, user, 'import', f'Apply refused: {exc}', success=False)
        else:
            logger.exception('Rehearsal %s: %s failed', plan_id, action)
        _finish(plan_id, token, 'failed', error=message, progress={'message': f'{action} failed'})
        return 'failed'
    if isinstance(result, dict) and result.get('paused'):
        _finish(plan_id, token, 'queued', result=result,
                progress={'done': result['done'], 'total': result['total'],
                          'message': f"applying {result['done']}/{result['total']} (continues next run)"})
        return 'queued'
    _finish(plan_id, token, 'done', result=result, progress={'message': f'{action} finished'})
    return 'done'


def run_pending(limit=10, budget_seconds=None):
    """Claim and run queued (or stale running) tasks. Returns [(plan_id, state)]."""
    from imports.models import MigrationPlan
    budget_end = time.monotonic() + (budget_seconds if budget_seconds is not None else slice_seconds())
    out = []
    ids = list(MigrationPlan.objects.filter(_claimable(timezone.now()))
               .order_by('task_queued_at', 'pk').values_list('pk', flat=True)[:limit])
    for plan_id in ids:
        if out and time.monotonic() >= budget_end:
            break
        token = claim(plan_id)
        if token is None:
            continue  # someone else has it
        out.append((plan_id, run_claimed(plan_id, token)))
    return out
