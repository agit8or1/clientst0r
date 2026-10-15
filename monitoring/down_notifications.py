"""Website down / recovery notifications.

`WebsiteMonitor.notify_on_down` has been on the monitor form since the first
release and defaulted to on, but nothing ever read it: a site could be down for
a week and the only sign was a red badge on a page nobody was looking at.

This sends on *transitions*, not on every failed check:

* A monitor must fail `DOWN_ALERT_THRESHOLD` consecutive checks before the
  down alert goes out, so one dropped packet does not page anyone.
* Once the down alert has been sent, further failed checks send nothing.
* The first successful check after a down alert sends one recovery notice.

The declared state is stored on the monitor (`alert_state`), so a scheduler
restart neither re-sends a down alert nor loses the recovery notice. The
`monitor.down` / `monitor.up` webhooks fire on the same transitions, and
`monitor.check_failed` on every failed check.

Only `down` counts as a failure. `warning` (a redirect) means the site answered,
matching how uptime is computed. `error` is a configuration refusal (the SSRF
guard), not an outage, and leaves the counters where they were.

Recipients are the same as the expiry notifications: active superusers plus the
admins/owners of the monitor's organization (`core.mailer`). When SMTP is off or
unusable the email is skipped (logged) and the transition is still recorded,
so a later SMTP fix does not produce a stale "is DOWN" for an old outage.
"""
import logging

from django.conf import settings as django_settings

from core.mailer import (
    brand_name,
    default_from_email,
    get_smtp_connection,
    notification_recipients,
    send_to_recipients,
    site_url,
)

logger = logging.getLogger('core')

DOWN_ALERT_THRESHOLD = 2


def _threshold():
    try:
        return max(1, int(getattr(django_settings, 'WEBSITE_DOWN_ALERT_THRESHOLD', DOWN_ALERT_THRESHOLD)))
    except (TypeError, ValueError):
        return DOWN_ALERT_THRESHOLD


def _send(monitor, subject_tail, lines):
    """Email the monitor's recipients. Returns True if anyone accepted it."""
    from core.models import SystemSetting

    system = SystemSetting.get_settings()
    connection = get_smtp_connection(system)
    if connection is None:
        logger.info('SMTP not configured - website alert for monitor %s not sent', monitor.pk)
        return False

    recipients = notification_recipients(monitor.organization_id)
    if not recipients:
        logger.info('No recipients for website alert on monitor %s', monitor.pk)
        return False

    brand = brand_name(system)
    base = site_url(system)
    org_name = getattr(monitor.organization, 'name', None) or 'Global'
    path = f'/monitoring/websites/{monitor.pk}/'
    subject = f'[{brand}] {monitor.name} {subject_tail} - {org_name}'
    body = '\n'.join(lines + ['', f'Monitor: {base}{path}' if base else f'Monitor: {path}'])
    return send_to_recipients(
        connection, default_from_email(system), recipients, subject, body,
    ) > 0


def process_check_result(monitor):
    """Update the failure streak after a check and send any due notification.

    Called from `WebsiteMonitor.check_status()` after the result is saved.
    Never raises: a notification problem must not turn a check into a failure.
    """
    try:
        _process(monitor)
    except Exception:
        logger.exception('Website alert processing failed for monitor %s', monitor.pk)


def _process(monitor):
    from core import webhook_events

    status = monitor.status
    if status == 'error':
        return

    update = []
    if status == 'down':
        monitor.consecutive_failures = (monitor.consecutive_failures or 0) + 1
        update.append('consecutive_failures')
        webhook_events.fire('monitor.check_failed', monitor.organization_id,
                            webhook_events.monitor_data(monitor))
        if monitor.alert_state != 'down' and monitor.consecutive_failures >= _threshold():
            # The outage is declared once, whether or not the email goes out:
            # with SMTP off, re-trying on every check would turn the webhook
            # into one call per failed check and then send a stale email
            # whenever SMTP came back.
            monitor.alert_state = 'down'
            update.append('alert_state')
            webhook_events.fire('monitor.down', monitor.organization_id,
                                webhook_events.monitor_data(monitor))
            if monitor.notify_on_down:
                lines = [
                    f'{monitor.name} is DOWN.',
                    '',
                    f'  URL: {monitor.url}',
                    f'  Failed checks in a row: {monitor.consecutive_failures}',
                ]
                if monitor.last_status_code:
                    lines.append(f'  Last HTTP status: {monitor.last_status_code}')
                if monitor.last_error:
                    lines.append(f'  Error: {monitor.last_error[:500]}')
                if monitor.last_checked_at:
                    lines.append(f'  Checked at: {monitor.last_checked_at:%Y-%m-%d %H:%M %Z}')
                _send(monitor, 'is DOWN', lines)
    else:
        if monitor.consecutive_failures:
            monitor.consecutive_failures = 0
            update.append('consecutive_failures')
        if monitor.alert_state == 'down':
            monitor.alert_state = 'up'
            update.append('alert_state')
            webhook_events.fire('monitor.up', monitor.organization_id,
                                webhook_events.monitor_data(monitor))
            if monitor.notify_on_down:
                lines = [
                    f'{monitor.name} has RECOVERED and is responding again.',
                    '',
                    f'  URL: {monitor.url}',
                ]
                if monitor.last_status_code:
                    lines.append(f'  HTTP status: {monitor.last_status_code}')
                if monitor.last_response_time_ms is not None:
                    lines.append(f'  Response time: {monitor.last_response_time_ms} ms')
                _send(monitor, 'has RECOVERED', lines)

    if update:
        monitor.save(update_fields=update)
