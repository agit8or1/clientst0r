"""
GPS auto-documentation engine — Sub-phase 8.2 (v3.17.412).

Runs every minute via cron. For each tech with `mode != 'off'` and a
recent (last 5 min) `TechnicianLocation`, it figures out whether they
are inside any `ClientSiteGeofence`. State transitions:

- ENTER — was outside, now inside:
  - `always_on` → auto-create + start a `TicketTimeEntry` against the
    user's last-active ticket for that org (or any open ticket).
  - `ask_first` → create a `PendingAutoTime` row and emit a Web Push
    notification. The TicketTimeEntry is only committed if the tech
    confirms (front-end POST handler — out of scope here).
- EXIT — was inside, now outside:
  - Close the most recent open `TicketTimeEntry` the engine started
    (we tag those entries with a marker in `notes` for traceability).

Every transition is audit-logged with `action='api_call'`,
`object_type='FieldOps'`, and `extra_data={'event': 'auto_time_*'}`.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from audit.models import AuditLog
from field_ops.models import (
    AutoTimePreference,
    ClientSiteGeofence,
    PendingAutoTime,
    TechnicianLocation,
)


AUTO_NOTE_MARKER = '[auto-time:field_ops]'


def _audit(user, event: str, extra: dict | None = None):
    try:
        AuditLog.objects.create(
            user=user,
            username=getattr(user, 'username', '') or '',
            action='api_call',
            object_type='FieldOps',
            extra_data={'event': event, **(extra or {})},
        )
    except Exception:
        pass


def _is_user_inside_geofence_now(user, latest_loc) -> ClientSiteGeofence | None:
    """Return the first active geofence (across all orgs) the user is
    currently inside, or None."""
    qs = ClientSiteGeofence.objects.filter(active=True)
    for fence in qs:
        if fence.contains(latest_loc.lat, latest_loc.lon):
            return fence
    return None


def _last_active_ticket(user, organization_id):
    """Return the user's most recent unsubmitted ticket for the org, or None."""
    try:
        from psa.models import TicketTimeEntry
    except Exception:
        return None
    tte = (
        TicketTimeEntry.objects.filter(
            user=user, ticket__organization_id=organization_id,
            submission__isnull=True,
        )
        .select_related('ticket')
        .order_by('-started_at')
        .first()
    )
    if tte is None:
        return None
    return tte.ticket


def _open_engine_entry(user, organization_id):
    """Find an engine-marked TicketTimeEntry that is still running for the
    user against any ticket in the given org."""
    try:
        from psa.models import TicketTimeEntry
    except Exception:
        return None
    return (
        TicketTimeEntry.objects.filter(
            user=user, ended_at__isnull=True,
            ticket__organization_id=organization_id,
            notes__contains=AUTO_NOTE_MARKER,
        )
        .order_by('-started_at')
        .first()
    )


def _may_log_time(user, organization_id) -> bool:
    """Re-check, at the moment the job acts, that `user` may still add time to
    this customer's tickets. Preferences are set once and the job runs every
    minute, so a later deactivation or role change must stop it."""
    if not user.is_active:
        return False
    from accounts.permission_utils import has_perm_for_org
    from psa.visibility import is_msp_staff
    return is_msp_staff(user) and has_perm_for_org(user, organization_id, 'tickets_edit')


def _push_to_user(user, *, title: str, body: str, url: str = ''):
    """Emit a Web Push to all of the user's active subscriptions. Best-
    effort — failures are recorded but never raised."""
    try:
        from psa.models import WebPushSubscription
    except Exception:
        return
    subs = WebPushSubscription.objects.filter(user=user, is_active=True)
    for sub in subs:
        try:
            sub.send(title=title, body=body, url=url)
        except Exception:
            pass


class Command(BaseCommand):
    help = 'Process geofence enter/exit transitions for all techs (cron every 1 min).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--window-minutes', type=int, default=5,
            help='Only consider GPS pings from the last N minutes (default 5).',
        )

    def handle(self, *args, **options):
        window = options.get('window_minutes') or 5
        cutoff = timezone.now() - timezone.timedelta(minutes=window)

        prefs = AutoTimePreference.objects.exclude(mode='off').select_related('user')
        enter_count = 0
        exit_count = 0
        skipped = 0

        for pref in prefs:
            user = pref.user
            latest = (
                TechnicianLocation.objects
                .filter(tech=user, timestamp__gte=cutoff)
                .order_by('-timestamp')
                .first()
            )
            if latest is None:
                skipped += 1
                continue

            fence = _is_user_inside_geofence_now(user, latest)

            if fence is not None and not _may_log_time(user, fence.organization_id):
                # The tech's access changed since they opted in (deactivated,
                # no longer MSP staff, or their role lost ticket editing for
                # this customer): don't start time on their behalf.
                skipped += 1
                continue

            if fence is not None:
                # Possible ENTER. Check whether we already have an open
                # auto-engine entry for this org.
                existing = _open_engine_entry(user, fence.organization_id)
                if existing is not None:
                    continue  # still inside, nothing to do

                # Also no pending if ask_first mode
                pending_exists = PendingAutoTime.objects.filter(
                    user=user, organization_id=fence.organization_id,
                    confirmed_at__isnull=True, cancelled_at__isnull=True,
                ).exists()
                if pending_exists:
                    continue

                if pref.mode == 'always_on':
                    self._enter_always_on(user, fence)
                    enter_count += 1
                elif pref.mode == 'ask_first':
                    self._enter_ask_first(user, fence)
                    enter_count += 1
            else:
                # Possible EXIT — check every org we might have open.
                from psa.models import TicketTimeEntry
                open_entries = TicketTimeEntry.objects.filter(
                    user=user, ended_at__isnull=True,
                    notes__contains=AUTO_NOTE_MARKER,
                )
                for entry in open_entries:
                    entry.ended_at = timezone.now()
                    entry.save()
                    _audit(user, 'auto_time_exit', {
                        'ticket_id': entry.ticket_id,
                        'time_entry_id': entry.id,
                    })
                    exit_count += 1

        self.stdout.write(self.style.SUCCESS(
            f'auto_document_field_visits: enter={enter_count} exit={exit_count} '
            f'skipped={skipped} (no recent ping)'
        ))

    def _enter_always_on(self, user, fence):
        ticket = _last_active_ticket(user, fence.organization_id)
        if ticket is None:
            # No active ticket — record the enter event but defer entry creation.
            _audit(user, 'auto_time_enter_no_ticket', {
                'geofence_id': fence.id, 'organization_id': fence.organization_id,
            })
            return
        try:
            from psa.models import TicketTimeEntry
            tte = TicketTimeEntry.objects.create(
                ticket=ticket, user=user,
                started_at=timezone.now(),
                notes=f'{AUTO_NOTE_MARKER} entered geofence #{fence.id}',
                is_billable=True,
            )
            _audit(user, 'auto_time_enter_always_on', {
                'geofence_id': fence.id, 'ticket_id': ticket.id,
                'time_entry_id': tte.id,
            })
        except Exception as e:
            _audit(user, 'auto_time_enter_failed', {
                'geofence_id': fence.id, 'error': str(e)[:200],
            })

    def _enter_ask_first(self, user, fence):
        suggested = _last_active_ticket(user, fence.organization_id)
        pending = PendingAutoTime.objects.create(
            user=user,
            organization_id=fence.organization_id,
            geofence=fence,
            suggested_ticket=suggested,
        )
        _audit(user, 'auto_time_enter_ask_first', {
            'geofence_id': fence.id, 'pending_id': pending.id,
            'suggested_ticket_id': suggested.id if suggested else None,
        })
        title = 'Confirm time tracking?'
        body = f'You arrived at {fence.name}. Tap to start time on your active ticket.'
        _push_to_user(user, title=title, body=body, url='/timeclock/')
