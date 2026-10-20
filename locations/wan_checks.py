"""Scheduled WAN connection checks and down / recovery alerts.

Until v3.17.617 a WAN connection was only checked when someone clicked
Check Status, although the form offered a check interval and said the target
would be pinged "at the specified interval". `check_wans` (run every minute
by the scheduler) now pings every due WAN and alerts on transitions, the same
way website monitors do (monitoring.down_notifications):

* A check sends 3 pings; any answer counts as up. A WAN must fail
  `WAN_DOWN_ALERT_THRESHOLD` (default 2) checks in a row before it is
  declared down: its status becomes Down, one email goes to the
  organization's admins and owners plus superusers, and `wan.down` fires.
* Further failed checks send nothing. The first check that gets an answer
  after that sets the status back to Active, emails once and fires `wan.up`.
* `wan.check_failed` fires on every failed check.
* A check that could not run (no ping binary, a bad target) is an `error`:
  it is recorded but neither counts as a failure nor clears one, because a
  missing binary is not an outage.
* WANs an operator has marked Inactive, Planned or Under Maintenance are not
  checked on the schedule. A manual check on one records its result but
  leaves the status alone and sends nothing.

The ping runs from the server with an absolute path to the binary: the
scheduler's systemd unit sets PATH to the virtualenv only.
"""
import logging
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings as django_settings
from django.utils import timezone

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
PING_COUNT = 3
MAX_PARALLEL = 16
# Must start alphanumeric so a target can't be read as a ping option.
TARGET_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9.\-]*$')


@dataclass
class PingResult:
    result: str               # 'up', 'down' or 'error'
    response_time_ms: int | None = None
    error: str = ''


def validate_target(target):
    if not TARGET_RE.match(str(target or '')):
        raise ValueError(f'Invalid monitor target: {target}')


def _ping_binary():
    found = shutil.which('ping')
    if found:
        return found
    for path in ('/usr/bin/ping', '/bin/ping', '/usr/sbin/ping', '/sbin/ping'):
        if shutil.which(path):
            return path
    return None


def ping_target(target):
    """Ping `target` and return a PingResult. Never raises, touches no DB,
    so it can run in a worker thread."""
    try:
        validate_target(target)
    except ValueError as e:
        return PingResult('error', error=str(e))
    binary = _ping_binary()
    if not binary:
        return PingResult('error', error='The ping command is not installed on the server.')
    try:
        proc = subprocess.run(
            [binary, '-n', '-c', str(PING_COUNT), '-i', '0.2', '-W', '2', str(target)],
            capture_output=True, timeout=15,
        )
    except subprocess.TimeoutExpired:
        return PingResult('down', error='No answer (timed out).')
    except OSError as e:
        return PingResult('error', error=f'Could not run ping: {e}')

    out = proc.stdout.decode('utf-8', 'replace')
    err = proc.stderr.decode('utf-8', 'replace').strip()
    if proc.returncode == 0:
        avg = re.search(r'= [\d.]+/([\d.]+)/', out)
        first = re.search(r'time[=<]([\d.]+)', out)
        rtt = avg or first
        return PingResult('up', response_time_ms=int(float(rtt.group(1))) if rtt else None)
    if proc.returncode == 1:
        return PingResult('down', error='No answer to ping.')
    # 2 and above: name resolution failure or a ping error. An unresolvable
    # name is an outage from the user's point of view only if it used to
    # resolve; treat a resolver failure as down, other errors as check errors.
    message = err or out.strip() or f'ping exited with status {proc.returncode}'
    if re.search(r'unknown host|name or service not known|temporary failure in name resolution',
                 message, re.I):
        return PingResult('down', error=message[:500])
    return PingResult('error', error=message[:500])


def _threshold():
    try:
        return max(1, int(getattr(django_settings, 'WAN_DOWN_ALERT_THRESHOLD', DOWN_ALERT_THRESHOLD)))
    except (TypeError, ValueError):
        return DOWN_ALERT_THRESHOLD


def wan_data(wan):
    return {
        'wan_id': wan.pk,
        'name': wan.name,
        'location_id': wan.location_id,
        'location': getattr(wan.location, 'name', None),
        'isp': wan.isp_name or '',
        'monitor_target': wan.monitor_target,
        'status': wan.status,
        'last_check_result': wan.last_check_result,
        'response_time_ms': wan.last_response_time_ms,
        'consecutive_failures': wan.consecutive_failures,
        'error': (wan.last_error or '')[:500],
        'checked_at': wan.last_checked_at.isoformat() if wan.last_checked_at else None,
    }


def _send(wan, subject_tail, lines):
    from core.models import SystemSetting

    system = SystemSetting.get_settings()
    connection = get_smtp_connection(system)
    if connection is None:
        logger.info('SMTP not configured - WAN alert for %s not sent', wan.pk)
        return False
    recipients = notification_recipients(wan.organization_id)
    if not recipients:
        logger.info('No recipients for WAN alert on %s', wan.pk)
        return False
    base = site_url(system)
    path = f'/locations/{wan.location_id}/wan/{wan.pk}/'
    org_name = getattr(wan.organization, 'name', None) or 'Global'
    subject = f'[{brand_name(system)}] {wan.location.name} - {wan.name} {subject_tail} - {org_name}'
    body = '\n'.join(lines + ['', f'WAN connection: {base}{path}' if base else f'WAN connection: {path}'])
    return send_to_recipients(connection, default_from_email(system), recipients, subject, body) > 0


def apply_result(wan, ping):
    """Record a check on `wan` and send any due notification."""
    from core import webhook_events
    from locations.models import WANCheck

    now = timezone.now()
    wan.last_checked_at = now
    wan.last_check_result = ping.result
    wan.last_error = ping.error
    if ping.result == 'up':
        wan.last_response_time_ms = ping.response_time_ms
    fields = ['last_checked_at', 'last_check_result', 'last_error', 'last_response_time_ms']

    try:
        WANCheck.objects.create(wan=wan, checked_at=now, result=ping.result,
                                response_time_ms=ping.response_time_ms, error=ping.error[:1000])
    except Exception:
        logger.exception('Could not record WANCheck for %s', wan.pk)

    manual_status = wan.status in wan.MANUAL_STATUSES
    if ping.result != 'error' and not manual_status:
        if ping.result == 'down':
            wan.consecutive_failures = (wan.consecutive_failures or 0) + 1
            fields.append('consecutive_failures')
            webhook_events.fire('wan.check_failed', wan.organization_id, wan_data(wan))
            if wan.alert_state != 'down' and wan.consecutive_failures >= _threshold():
                wan.alert_state = 'down'
                wan.status = 'down'
                wan.last_down_at = now
                fields += ['alert_state', 'status', 'last_down_at']
                webhook_events.fire('wan.down', wan.organization_id, wan_data(wan))
                if wan.notify_on_down:
                    lines = [
                        f'{wan.location.name} - {wan.name} is not answering.',
                        '',
                        f'  Target: {wan.monitor_target}',
                        f'  ISP: {wan.isp_name or "-"}',
                        f'  Failed checks in a row: {wan.consecutive_failures}',
                    ]
                    if wan.isp_support_phone:
                        lines.append(f'  ISP support: {wan.isp_support_phone}')
                    if wan.circuit_id:
                        lines.append(f'  Circuit ID: {wan.circuit_id}')
                    if ping.error:
                        lines.append(f'  Error: {ping.error[:500]}')
                    _send(wan, 'is DOWN', lines)
        else:
            if wan.consecutive_failures:
                wan.consecutive_failures = 0
                fields.append('consecutive_failures')
            if wan.status == 'down':
                wan.status = 'active'
                fields.append('status')
            if wan.alert_state == 'down':
                wan.alert_state = 'up'
                fields.append('alert_state')
                webhook_events.fire('wan.up', wan.organization_id, wan_data(wan))
                if wan.notify_on_down:
                    lines = [f'{wan.location.name} - {wan.name} is answering again.', '',
                             f'  Target: {wan.monitor_target}']
                    if ping.response_time_ms is not None:
                        lines.append(f'  Response time: {ping.response_time_ms} ms')
                    if wan.last_down_at:
                        lines.append(f'  Down since: {wan.last_down_at:%Y-%m-%d %H:%M %Z}')
                    _send(wan, 'has RECOVERED', lines)

    up = wan.uptime(30)['percent']
    wan.uptime_percentage = None if up is None else round(up, 2)
    fields.append('uptime_percentage')
    wan.save(update_fields=sorted(set(fields + ['updated_at'])))


def due_wans(now=None):
    from locations.models import WAN

    now = now or timezone.now()
    qs = (WAN.objects.filter(monitoring_enabled=True)
          .exclude(monitor_target='')
          .exclude(status__in=WAN.MANUAL_STATUSES)
          .select_related('location', 'organization'))
    return [w for w in qs
            if not w.last_checked_at
            or w.last_checked_at <= now - timedelta(minutes=max(1, w.monitor_interval_minutes or 5))
            + timedelta(seconds=30)]


def run_due_checks(force=False):
    """Ping every due WAN (in parallel) and apply the results (serially, so
    the database work stays on this thread). Returns {result: count}."""
    from locations.models import WAN

    if force:
        wans = list(WAN.objects.filter(monitoring_enabled=True).exclude(monitor_target='')
                    .exclude(status__in=WAN.MANUAL_STATUSES)
                    .select_related('location', 'organization'))
    else:
        wans = due_wans()
    counts = {'up': 0, 'down': 0, 'error': 0}
    if not wans:
        return counts
    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(wans))) as pool:
        results = list(pool.map(lambda w: ping_target(w.monitor_target), wans))
    for wan, ping in zip(wans, results):
        try:
            apply_result(wan, ping)
            counts[ping.result] += 1
        except Exception:
            logger.exception('Applying WAN check result failed for %s', wan.pk)
            counts['error'] += 1
    return counts
