"""
Phase 34.2 (v3.17.545) — running a collection and recording what happened.

Kept apart from the adapters (which know vendor commands) and from the views
(which know HTML) so the management command, the scheduler and a hand-run
collection all take exactly the same path.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from .adapters import CollectionError, collect_over_ssh
from .models import ConfigBackup

logger = logging.getLogger(__name__)


def collect_target(target, *, user=None, timeout=30):
    """Collect one device. Returns a result dict; never raises for a device
    problem, because one unreachable switch must not stop a nightly run over
    two hundred of them.

    Result: `{ok, created, changed, message, backup}`.
    """
    blocked = target.blocking_reason()
    if blocked:
        _record_failure(target, blocked)
        return {'ok': False, 'created': False, 'changed': False,
                'message': blocked, 'backup': None}

    target.last_attempt_at = timezone.now()
    target.save(update_fields=['last_attempt_at', 'updated_at'])

    # Decrypting here rather than inside the transport keeps the decision about
    # whether a credential may be used unattended in one place —
    # `blocking_reason` above — instead of spread across the SSH code.
    try:
        secret = target.credential.get_password()
    except Exception as exc:
        message = f'Could not read the vault credential: {exc}'
        _record_failure(target, message)
        return {'ok': False, 'created': False, 'changed': False,
                'message': message, 'backup': None}

    if not secret:
        message = 'The linked vault entry has no password stored.'
        _record_failure(target, message)
        return {'ok': False, 'created': False, 'changed': False,
                'message': message, 'backup': None}

    try:
        config, firmware = collect_over_ssh(target, secret, timeout=timeout)
    except CollectionError as exc:
        _record_failure(target, str(exc))
        return {'ok': False, 'created': False, 'changed': False,
                'message': str(exc), 'backup': None}
    except Exception as exc:  # noqa: BLE001 - a device can fail in any way
        message = f'Unexpected failure: {exc}'
        logger.exception('Config collection failed for target %s', target.pk)
        _record_failure(target, message)
        return {'ok': False, 'created': False, 'changed': False,
                'message': message, 'backup': None}
    finally:
        # The plaintext lives no longer than it has to.
        secret = None

    backup, created = ConfigBackup.record_for_asset(
        target.asset, config,
        source='ssh',
        captured_at=timezone.now(),
        firmware_version=firmware,
        captured_by=user,
    )

    # Phase 34.3 — classify against the approved baseline. Only a genuinely
    # new snapshot is worth classifying; an unchanged capture cannot have
    # drifted since the one before it.
    if created:
        from .drift import classify_and_alert
        classify_and_alert(backup)

    target.last_success_at = timezone.now()
    target.last_error = ''
    target.save(update_fields=['last_success_at', 'last_error', 'updated_at'])

    _audit(target, user, success=True, description=(
        'Config collected and stored as a new snapshot' if created
        else 'Config collected; unchanged from the previous snapshot'))

    return {
        'ok': True,
        'created': created,
        'changed': created,
        'message': ('Stored a new snapshot.' if created
                    else 'Unchanged since the last capture.'),
        'backup': backup,
    }


def _record_failure(target, message):
    target.last_error = (message or '')[:2000]
    target.last_attempt_at = target.last_attempt_at or timezone.now()
    target.save(update_fields=['last_error', 'last_attempt_at', 'updated_at'])
    _audit(target, None, success=False, description=message)


def _audit(target, user, *, success, description):
    """Every collection is logged. Reading a stored credential and opening an
    administrative session to a firewall is not something that should happen
    without a trace, whether it worked or not."""
    try:
        from audit.models import AuditLog
        AuditLog.log(
            user=user,
            action='update' if success else 'error',
            organization=target.organization,
            object_type='netconfig.BackupTarget',
            object_id=target.pk,
            object_repr=f'{target.asset} ({target.host})',
            description=description[:1000],
            success=success,
        )
    except Exception:
        # Auditing must not be the thing that breaks a backup run.
        logger.exception('Could not write audit log for target %s', target.pk)


def collect_due(*, limit=None, force=False, user=None):
    """Collect every enabled target that is due. Returns a summary dict."""
    from .models import BackupTarget

    targets = BackupTarget.objects.filter(is_enabled=True).select_related(
        'asset', 'credential', 'organization')
    if not force:
        targets = [t for t in targets if t.is_due]
    else:
        targets = list(targets)
    if limit:
        targets = targets[:limit]

    summary = {'attempted': 0, 'ok': 0, 'failed': 0, 'changed': 0, 'results': []}
    for target in targets:
        result = collect_target(target, user=user)
        summary['attempted'] += 1
        summary['ok'] += 1 if result['ok'] else 0
        summary['failed'] += 0 if result['ok'] else 1
        summary['changed'] += 1 if result['changed'] else 0
        summary['results'].append((target, result))
    return summary
