"""
Phase 34.3 (v3.17.546) — classifying a config change and shouting about it.

The point of the phase is "make unauthorized changes loud". Which means the
hard part is not detecting a change — that is a hash comparison — but deciding
which changes are worth waking someone for. A firewall rule edited during an
approved Tuesday-night maintenance is not an incident. The same edit at 3pm on
a Wednesday with no change request open is the thing this exists to catch.
"""
from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

# Statuses that mean "this change was signed off and is happening". `draft` and
# `pending_cab` deliberately do not count: a change nobody has approved yet is
# exactly the case that should still raise.
ACTIVE_CHANGE_STATUSES = ('approved', 'implementing')


def find_change_window(organization, at=None):
    """An approved change request covering `at` for this organization.

    Returns the ChangeRequest or None. A request with no schedule cannot cover
    anything — "approved, sometime" is not a window, and treating it as an
    open-ended licence would silence every alert for that client.
    """
    at = at or timezone.now()
    try:
        from psa.models import ChangeRequest
    except Exception:  # pragma: no cover - psa is always installed in practice
        return None

    return (ChangeRequest.objects
            .filter(organization=organization,
                    implementation_status__in=ACTIVE_CHANGE_STATUSES,
                    scheduled_start__isnull=False,
                    scheduled_end__isnull=False,
                    scheduled_start__lte=at,
                    scheduled_end__gte=at)
            .order_by('scheduled_start')
            .first())


def classify(backup):
    """Work out what kind of change `backup` represents.

    Returns `(state, change_request)`. Does not save; `classify_and_alert`
    does the writing so a caller can ask the question without side effects.
    """
    from .models import ConfigBackup

    baseline = ConfigBackup.approved_baseline(backup.asset)
    if baseline is None:
        # Nothing has been declared known-good, so there is no such thing as
        # drift yet. Alerting here would mean every device screams from its
        # first capture until somebody approves one, which trains people to
        # ignore the alerts.
        return 'no_baseline', None

    if baseline.content_hash == backup.content_hash:
        return 'baseline', None

    window = find_change_window(backup.organization, backup.captured_at)
    if window is not None:
        return 'expected', window

    return 'unauthorized', None


def classify_and_alert(backup, *, raise_alert=True):
    """Classify `backup`, store the verdict, and raise an alert if warranted.

    Returns the drift state. Alert creation failures are logged and swallowed:
    a broken alert path must not lose the snapshot or fail the backup run that
    produced it.
    """
    state, window = classify(backup)

    backup.drift_state = state
    backup.change_request = window
    backup.save(update_fields=['drift_state', 'change_request'])

    if state == 'unauthorized' and raise_alert:
        try:
            _raise_alert(backup)
        except Exception:
            logger.exception(
                'Could not raise a drift alert for backup %s', backup.pk)

    return state


def _raise_alert(backup):
    """Put an unauthorized change on the security dashboard."""
    from security_alerts.models import SecurityAlert

    from .models import ConfigBackup

    baseline = ConfigBackup.approved_baseline(backup.asset)
    stats = backup.diff_stats(baseline)

    device = backup.asset.name or f'asset {backup.asset_id}'
    SecurityAlert.objects.create(
        # No vendor connection and no SIEM endpoint: this alert is generated
        # here rather than ingested, and both FKs are nullable for exactly
        # that kind of source.
        organization=backup.organization,
        client_org=backup.organization,
        external_id=f'netconfig-drift-{backup.pk}',
        severity='high',
        title=f'Unauthorized config change on {device}',
        description=(
            f'The running configuration of {device} differs from the approved '
            f'baseline, and no approved change request covered the time it was '
            f'captured ({backup.captured_at:%Y-%m-%d %H:%M}). '
            f'{stats["added"]} line(s) added, {stats["removed"]} removed.'
        ),
        asset_hint=device,
        raw_payload={
            'source': 'netconfig',
            'asset_id': backup.asset_id,
            'backup_id': backup.pk,
            'baseline_id': baseline.pk if baseline else None,
            'added': stats['added'],
            'removed': stats['removed'],
            'captured_at': backup.captured_at.isoformat(),
        },
        status='new',
    )
