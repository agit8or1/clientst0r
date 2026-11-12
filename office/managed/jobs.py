"""Background lifecycle operations for the managed ONLYOFFICE container.

The web request only enqueues (``enqueue``). The scheduler runs
``manage.py office_managed --run-pending`` every minute (core.ScheduledTask
``office_managed_operations``), which calls ``run_pending``. Each run works
on the active operation for at most ``OFFICE_MANAGED_SLICE_SECONDS`` and
then hands it back, so the shared scheduler loop is never blocked for long.

Guarantees:

* one active operation: a conditional unique constraint on
  ManagedOfficeOperation (lock_key, state in queued/draining/running/
  verifying) makes a second enqueue fail in the database, whatever the
  race;
* one runner: ``claim`` is a conditional UPDATE setting a fresh lease; a
  runner whose lease was taken over stops (LeaseLost) before writing more;
* crash recovery: an active operation whose heartbeat is older than
  ``OFFICE_MANAGED_LEASE_SECONDS`` is claimed again and continues from its
  stored state. The helper operation id is stored, so a resumed run polls
  the same helper operation instead of starting a second one. An operation
  the helper reports as *interrupted* (helper process killed, reboot) is
  resubmitted - every helper operation converges, so this is a safe retry -
  at most ``MAX_SUBMITS`` times;
* drain before stop / restart / update / rollback / uninstall: new sessions
  are blocked, saves are requested, and office.drain.verify must report
  everything durable. Unknown state is never treated as drained; after
  ``OFFICE_MANAGED_DRAIN_SECONDS`` the operation is *postponed* and the
  editor is opened for editing again;
* verification after install / start / restart / update / rollback: the
  provider is (re)configured from the helper status, the health check runs,
  and the server-driven round trip (open, edit, save, reopen through the
  real editor) must pass before the editor is opened to users again;
* every state change is audited.
"""
from __future__ import annotations

import logging
import secrets
import time
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone

from office import audit, drain
from office.models import ManagedOfficeOperation, ManagedOfficeService

from . import ipc

log = logging.getLogger('office.managed')

DRAIN_ACTIONS = ('stop', 'restart', 'update', 'rollback', 'uninstall')
VERIFY_ACTIONS = ('install', 'start', 'restart', 'update', 'rollback')
MAX_SUBMITS = 3


class LeaseLost(Exception):
    pass


class AlreadyActive(Exception):
    pass


def lease_seconds():
    return int(getattr(settings, 'OFFICE_MANAGED_LEASE_SECONDS', 300))


def slice_seconds():
    return float(getattr(settings, 'OFFICE_MANAGED_SLICE_SECONDS', 50))


def drain_seconds():
    return int(getattr(settings, 'OFFICE_MANAGED_DRAIN_SECONDS', 900))


def poll_seconds():
    return float(getattr(settings, 'OFFICE_MANAGED_POLL_SECONDS', 3))


def active():
    return ManagedOfficeOperation.objects.filter(
        state__in=ManagedOfficeOperation.ACTIVE_STATES).first()


def enqueue(action, *, user=None, release='', source='admin', request=None):
    """Queue `action`. Raises AlreadyActive when an operation is active."""
    if action not in dict(ManagedOfficeOperation.ACTIONS):
        raise ValueError(f'unknown action {action}')
    if action == 'update' and not release:
        raise ValueError('update needs a release')
    try:
        with transaction.atomic():
            op = ManagedOfficeOperation.objects.create(
                action=action, target_release=release if action == 'update' else '',
                requested_by=user, source=source,
                progress={'message': 'queued', 'steps': [{'at': timezone.now().isoformat(),
                                                          'message': 'queued'}]})
    except IntegrityError:
        current = active()
        raise AlreadyActive(f'{current.get_action_display() if current else "An operation"} is '
                            f'already in progress.')
    audit.log('managed_operation', user=user, request=request, object_type='office.managed',
              object_id=op.pk, object_repr=op.get_action_display(),
              description=f'Queued managed ONLYOFFICE operation: {op.get_action_display()}'
                          + (f' to {release}' if release else '') + f' ({source})',
              extra={'action': action, 'release': release, 'source': source})
    return op


def cancel(op, *, user=None, request=None):
    """Cancel a queued operation (one that has not started)."""
    n = ManagedOfficeOperation.objects.filter(pk=op.pk, state='queued').update(
        state='cancelled', finished_at=timezone.now(), lease='')
    if n:
        audit.log('managed_operation', user=user, request=request, object_type='office.managed',
                  object_id=op.pk, object_repr=op.get_action_display(),
                  description=f'Cancelled queued managed ONLYOFFICE operation {op.get_action_display()}')
    return bool(n)


def _claimable(now):
    stale = now - timedelta(seconds=lease_seconds())
    return Q(state__in=ManagedOfficeOperation.ACTIVE_STATES) & (
        Q(lease='') | Q(heartbeat_at__lt=stale) | Q(heartbeat_at__isnull=True))


def claim(op_id):
    now = timezone.now()
    token = secrets.token_hex(16)
    n = (ManagedOfficeOperation.objects.filter(_claimable(now), pk=op_id)
         .update(lease=token, heartbeat_at=now, attempts=F('attempts') + 1))
    if not n:
        return None
    ManagedOfficeOperation.objects.filter(pk=op_id, started_at__isnull=True).update(started_at=now)
    return token


class Runner:
    """Moves one claimed operation forward until it finishes or the slice
    ends."""

    def __init__(self, op, token):
        self.op = op
        self.token = token
        self.deadline = time.monotonic() + slice_seconds()

    # -- persistence -------------------------------------------------------
    def save(self, **fields):
        fields['heartbeat_at'] = timezone.now()
        n = ManagedOfficeOperation.objects.filter(pk=self.op.pk, lease=self.token).update(**fields)
        if not n:
            raise LeaseLost(f'lease on managed operation {self.op.pk} lost')
        for k, v in fields.items():
            setattr(self.op, k, v)

    def say(self, message, **fields):
        steps = list((self.op.progress or {}).get('steps') or [])
        if not steps or steps[-1].get('message') != message:
            steps.append({'at': timezone.now().isoformat(), 'message': message[:300]})
        self.save(progress={'message': message[:300], 'steps': steps[-40:]}, **fields)

    def finish(self, state, *, error='', result=None):
        fields = dict(state=state, finished_at=timezone.now(), lease='', error=error[:4000])
        if result is not None:
            fields['result'] = dict(self.op.result or {}, **result)
        self.say(error[:300] if error else state, **fields)
        action = self.op.get_action_display()
        audit.log('managed_operation', user=self.op.requested_by, object_type='office.managed',
                  object_id=self.op.pk, object_repr=action, success=state == 'succeeded',
                  description=f'Managed ONLYOFFICE operation {action}: {state}'
                              + (f' - {error[:500]}' if error else ''),
                  extra={'action': self.op.action, 'state': state,
                         'release': self.op.target_release, 'source': self.op.source})

    def time_left(self):
        return self.deadline - time.monotonic()

    # -- the state machine --------------------------------------------------
    def run(self):
        while self.time_left() > 0:
            self.op.refresh_from_db()
            state = self.op.state
            if state not in ManagedOfficeOperation.ACTIVE_STATES:
                return state
            if self.op.lease != self.token:
                raise LeaseLost('lease taken over')
            if state == 'queued':
                self.start()
            elif state == 'draining':
                if not self.drain_step():
                    self.sleep()
            elif state == 'running':
                if not self.helper_step():
                    self.sleep()
            elif state == 'verifying':
                self.verify()
        # Slice over: release the lease so the next scheduler run continues.
        self.save(lease='')
        return self.op.state

    def sleep(self):
        time.sleep(max(0.0, min(poll_seconds(), self.time_left())))

    def instance(self):
        from .provision import managed_instance
        return managed_instance()

    def start(self):
        service = ManagedOfficeService.get()
        if not service.enabled:
            return self.finish('failed', error='Managed Local ONLYOFFICE is turned off in Settings.')
        # A queued operation runs later, from the scheduler: recheck that the
        # administrator who asked for it still may (active superuser) before
        # anything is touched. Maintenance-window updates are the system's
        # own job, authorised by the maintenance settings, not by a person.
        if self.op.source != 'maintenance':
            requester = self.op.requested_by
            if requester is None or not (requester.is_active and requester.is_superuser):
                return self.finish('failed', error='The administrator who queued this operation no '
                                                   'longer has platform administrator rights.')
        inst = self.instance()
        if self.op.action in DRAIN_ACTIONS and inst is not None:
            was = drain.block(inst)
            self.say('New editing sessions are blocked; asking the editor to save open documents.',
                     state='draining', drain_started_at=timezone.now(),
                     result=dict(self.op.result or {}, was_enabled=was))
            outcomes = drain.request_saves(inst)
            if outcomes:
                self.say(f'Save requested for {len(outcomes)} open editing group(s).')
            return
        if self.op.action in ('install', 'start', 'restart', 'update', 'rollback') and inst is not None:
            # No drain needed (nothing runs), but keep users out until verified.
            was = drain.block(inst)
            self.save(result=dict(self.op.result or {}, was_enabled=was))
        self.save(state='running')

    def drain_step(self):
        inst = self.instance()
        if inst is None:
            self.save(state='running')
            return True
        st = drain.verify(inst, self.op.drain_started_at)
        if st.drained:
            self.say('Drained: every edit is stored in clientst0r.', state='running')
            return True
        waited = (timezone.now() - (self.op.drain_started_at or timezone.now())).total_seconds()
        if waited >= drain_seconds():
            if (self.op.result or {}).get('was_enabled'):
                drain.unblock(inst)
            reason = ('Postponed: draining could not be verified within '
                      f'{drain_seconds() // 60} minutes. ' + '; '.join(st.pending[:10]))
            self.finish('postponed', error=reason, result={'pending': st.pending[:50]})
            return True
        self.say(f'Draining ({int(waited)} s): ' + ('; '.join(st.pending[:3]) or st.detail))
        return False

    def helper_step(self):
        """Submit the helper operation once, then poll it."""
        if not self.op.helper_op_id:
            return self.submit()
        try:
            status = ipc.call('status')
        except ipc.HelperError as e:
            self.say(f'Waiting for the Office service helper: {e}')
            return False
        _cache_status(status)
        hop = status.get('operation') or {}
        if hop.get('id') != self.op.helper_op_id:
            # Our operation is not the helper's latest any more: something
            # else ran in between (an administrator from the shell).
            return self.finish('failed', error='The server ran another operation in the meantime; '
                                                'check the status and retry.') or True
        if hop.get('state') == 'running':
            self.say(f'On the server: {hop.get("step") or "working"}')
            return False
        if hop.get('state') == 'interrupted':
            if self.op.helper_submits >= MAX_SUBMITS:
                return self.finish('failed', error=f'The server operation was interrupted '
                                                    f'{self.op.helper_submits} times: {hop.get("error")}') or True
            self.say(f'The server operation was interrupted ({hop.get("error")}); retrying.',
                     helper_op_id='')
            return True
        if hop.get('state') == 'failed':
            return self.finish('failed', error=f'On the server: {hop.get("error") or "failed"}',
                               result={'helper': hop.get('result') or {}}) or True
        # succeeded
        self.save(result=dict(self.op.result or {}, helper=hop.get('result') or {}))
        if self.op.action in VERIFY_ACTIONS:
            self.say('The server finished; verifying the editor.', state='verifying')
        else:
            self.after_down()
        return True

    def submit(self):
        args = {'release': self.op.target_release} if self.op.action == 'update' else None
        try:
            hop = ipc.submit(self.op.action, args)
        except ipc.HelperRefused as e:
            if e.busy:
                self.say('The server is busy with another operation; waiting.')
                return False
            self.finish('failed', error=f'The server refused: {e}')
            return True
        except ipc.HelperError as e:
            self.say(f'Waiting for the Office service helper: {e}')
            return False
        self.say(f'Running on the server ({hop.get("id")}).', helper_op_id=hop.get('id', ''),
                 helper_submits=self.op.helper_submits + 1)
        return True

    def after_down(self):
        """stop / uninstall finished: the editor stays closed to users."""
        inst = self.instance()
        if inst is not None:
            from office.models import EditorInstance
            EditorInstance.objects.filter(pk=inst.pk).update(
                enabled=False, health_status='down',
                health_detail='Stopped by the managed service.' if self.op.action == 'stop'
                else 'Uninstalled; documents and editor data are retained.')
        self.finish('succeeded')

    def verify(self):
        from office import diagnostics
        from .provision import ProvisionError, configure
        try:
            status = ipc.call('status')
            _cache_status(status)
            inst, health = configure(status, user=self.op.requested_by)
        except (ipc.HelperError, ProvisionError) as e:
            return self.finish('failed', error=f'Configuring the editor failed: {e}')
        if health.status != 'ok':
            return self.finish('failed', error=f'Health check after {self.op.action}: '
                                                f'{inst.get_health_status_display()} - {health.detail}'[:2000]
                               + _hint(self.op.action))
        user = self.op.requested_by or ManagedOfficeService.get().updated_by
        if user is None or not user.is_superuser:
            return self.finish('failed', error='Healthy, but the open/edit/save round trip needs a '
                                               'platform administrator account; run it from Diagnostics.')
        self.say('Healthy; running an open/edit/save round trip through the editor.')
        report = diagnostics.run_round_trip(inst, user, maintenance=True)
        must_pass = [s for s in report.steps if s.key != 'callback']
        failed = [s for s in must_pass if s.status != 'pass']
        steps = [{'key': s.key, 'label': s.label, 'status': s.status, 'detail': s.detail[:300]}
                 for s in report.steps]
        if failed:
            return self.finish('failed', result={'round_trip': steps},
                               error='Round trip failed: ' + '; '.join(
                                   f'{s.label}: {s.detail[:200]}' for s in failed) + _hint(self.op.action))
        ManagedOfficeService.objects.filter(pk=1).update(
            last_connection_ok_at=timezone.now(),
            last_connection_detail=f'{health.detail} Round trip passed after {self.op.action}.'[:2000])
        # Verified: open the editor to users (again). The managed instance's
        # availability follows the service; it has no separate switch.
        drain.unblock(inst)
        self.finish('succeeded', result={'round_trip': steps})


def _hint(action):
    if action == 'update':
        return ' The editor stays closed to users; use Roll back to return to the previous release.'
    return ' The editor stays closed to users until this is fixed.'


def _cache_status(status):
    ManagedOfficeService.objects.filter(pk=1).update(
        status=_public_status(status), status_at=timezone.now(), helper_reachable=True,
        status_error='')


def _public_status(status):
    """The helper's status minus anything we never store (it holds no
    secrets, but keep the stored copy to known keys)."""
    keys = ('helper_version', 'config', 'docker', 'installed', 'container', 'resources',
            'data_bytes', 'operation', 'update_available', 'backups', 'secrets_present')
    return {k: status.get(k) for k in keys if k in (status or {})}


def refresh_status(timeout=None):
    """Ask the helper for its status and cache it. Never raises."""
    ManagedOfficeService.get()
    try:
        status = ipc.call('status', timeout=timeout)
    except ipc.HelperError as e:
        ManagedOfficeService.objects.filter(pk=1).update(
            helper_reachable=False, status_error=str(e)[:500], status_at=timezone.now())
        return None
    _cache_status(status)
    return status


def run_pending():
    """Advance the active operation (if any) for one slice."""
    op = active()
    if op is None:
        return None
    token = claim(op.pk)
    if token is None:
        return (op.pk, 'held by another runner')
    try:
        state = Runner(op, token).run()
    except LeaseLost:
        return (op.pk, 'lease lost')
    except Exception as e:      # never leave an operation spinning silently
        log.exception('managed operation %s crashed', op.pk)
        ManagedOfficeOperation.objects.filter(pk=op.pk, lease=token).update(
            lease='', heartbeat_at=timezone.now(),
            error=f'Internal error ({type(e).__name__}); retrying at the next run.')
        return (op.pk, 'error')
    return (op.pk, state)


# ---------------------------------------------------------------------------
# Maintenance-window updates (off by default)
# ---------------------------------------------------------------------------

def in_window(service, now=None):
    now = timezone.localtime(now or timezone.now())
    if service.maintenance_weekday is not None and now.weekday() != service.maintenance_weekday:
        return False
    start = now.replace(hour=service.maintenance_hour, minute=0, second=0, microsecond=0)
    return start <= now < start + timedelta(hours=max(1, min(6, service.maintenance_hours)))


def maybe_schedule_update(now=None):
    """Queue an update inside the maintenance window when both the app
    setting and the root-owned MAINTENANCE_UPDATES=yes allow it. Returns the
    queued operation or None."""
    service = ManagedOfficeService.get()
    if not (service.enabled and service.maintenance_updates) or not in_window(service, now):
        return None
    if active() is not None:
        return None
    status = service.status or {}
    if not (status.get('config') or {}).get('maintenance_updates'):
        return None
    candidates = [u for u in status.get('update_available') or [] if u.get('installable')]
    if not candidates:
        return None
    release = sorted(candidates, key=lambda u: [int(x) for x in u['version'].split('.')])[-1]['id']
    recent = ManagedOfficeOperation.objects.filter(
        action='update', target_release=release, source='maintenance',
        queued_at__gte=(now or timezone.now()) - timedelta(hours=12)).exists()
    if recent:
        return None     # one attempt per window
    try:
        return enqueue('update', user=service.updated_by, release=release, source='maintenance')
    except AlreadyActive:
        return None
