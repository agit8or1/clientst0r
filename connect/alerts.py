"""Connection status changes into the existing notification channels
(DESIGN.md §10; the full alert set with muting, tickets and the shared event
layer is increment E / roadmap 79.19).

Reused, nothing new built:

  * e-mail: core.mailer (notification_recipients: superusers + org admins),
    sent after the transaction commits, never more than once per connection
    and status in 30 minutes;
  * the at-most-once marker: core.models.SystemWarningNotification
    (unique warning_id ``connect:<id>:<status>:<30-minute window>``), safe
    across workers, the same pattern as api_access/alerts.py;
  * system warnings (core.system_warnings, and so the daily digest):
    Security Blocked, Offline and Degraded connections;
  * the notification bell (core.notifications SOURCES): connections that
    need attention, for users who may view Connected Applications.

Every status change is also a ConnectAuditEvent (``connection.status``).
Alerts carry the connection's name, status and failure code only: never a
token, key, assertion, address list or customer data.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from . import status as st

logger = logging.getLogger('connect')

WINDOW = timedelta(minutes=30)
# Transitions that notify (DESIGN §10 rule 1). Suspended only when the kill
# switch did it; Revoked only when the other side did it.
ALERT_ON = frozenset({st.DEGRADED, st.OFFLINE, st.SECURITY_BLOCKED})
SEVERITY = {st.SECURITY_BLOCKED: 'critical', st.OFFLINE: 'high', st.DEGRADED: 'medium',
            st.SUSPENDED: 'high', st.REVOKED: 'medium', st.CONNECTED: 'info'}


def _alertable(conn, key) -> bool:
    if key in ALERT_ON:
        return True
    if key == st.SUSPENDED:
        return conn.suspended_reason == 'kill_switch'
    if key == st.REVOKED:
        return conn.suspended_reason in ('peer_disconnected', 'peer_revoked')
    return False


def warning_id(conn_id, key, now=None) -> str:
    slot = int((now or timezone.now()).timestamp() // WINDOW.total_seconds())
    return f'connect:{conn_id}:{key}:{slot}'[:200]


def _name(conn) -> str:
    return (conn.remote_display_name or conn.remote_app_type or str(conn.pk))[:120]


def observe(conn, code: str = '', user=None) -> str:
    """Record a displayed-status transition (compare-and-set on
    ``status_key``, so two workers report it once) and notify when it is
    one of the alerting transitions or a recovery. Returns the new key."""
    from .models import Connection as C
    from . import audit_log
    conn.refresh_from_db(fields=['state', 'health', 'status_key', 'alerted_status', 'suspended_reason',
                                 'remote_display_name', 'remote_app_type', 'security_block_code'])
    key = st.display(conn).key
    old = conn.status_key
    if key == old:
        return key
    if not C.objects.filter(pk=conn.pk, status_key=old).update(status_key=key):
        return key        # another worker recorded this transition
    conn.status_key = key
    if old:
        audit_log.record('connection.status', key, connection=conn, user=user, app=conn.remote_installation_id,
                         detail={'from': old, 'to': key, 'code': (code or (conn.security_block_code
                                                                          if key == st.SECURITY_BLOCKED else ''))})
    if _alertable(conn, key):
        C.objects.filter(pk=conn.pk).update(alerted_status=key)
        conn.alerted_status = key
        notify(conn, key, code or (conn.security_block_code if key == st.SECURITY_BLOCKED else ''))
    elif key == st.CONNECTED and conn.alerted_status:
        if C.objects.filter(pk=conn.pk, alerted_status=conn.alerted_status).update(alerted_status=''):
            notify(conn, st.CONNECTED, '', recovered_from=conn.alerted_status)
        conn.alerted_status = ''
    return key


def notify(conn, key, code='', recovered_from='') -> bool:
    """At most once per (connection, status) per 30 minutes, across workers."""
    from core.models import SystemWarningNotification
    now = timezone.now()
    prefix = f'connect:{conn.pk}:{key}:'
    try:
        if SystemWarningNotification.objects.filter(warning_id__startswith=prefix,
                                                    notified_at__gte=now - WINDOW).exists():
            return False
        title = _title(conn, key, recovered_from)
        _, created = SystemWarningNotification.objects.get_or_create(
            warning_id=warning_id(conn.pk, key, now), defaults={'severity': SEVERITY.get(key, 'medium'),
                                                                'title': title})
    except Exception:
        logger.warning('could not record a Connect alert marker', exc_info=True)
        return False
    if not created:
        return False
    args = (str(conn.pk), title, _body(conn, key, code, recovered_from), warning_id(conn.pk, key, now))
    transaction.on_commit(lambda: threading.Thread(target=_send, args=args, daemon=True).start())
    return True


def _title(conn, key, recovered_from=''):
    if key == st.CONNECTED:
        return f'Connected application "{_name(conn)}" is connected again'
    return f'Connected application "{_name(conn)}" is {st.LABELS[key]}'


def _body(conn, key, code, recovered_from):
    lines = [_title(conn, key, recovered_from) + '.', '']
    if key == st.SECURITY_BLOCKED:
        lines += [f'Reason: {code or "security check failed"}.',
                  'Nothing is exchanged with it and it does not reconnect by itself. Review the evidence on the '
                  'connection page, confirm the change with the other application\'s administrator, then retest.']
    elif key == st.OFFLINE:
        lines += ['The other application cannot be reached. Clientst0r retries with increasing waits (up to every '
                  '15 minutes); queued events wait and are delivered in order when it is back.']
    elif key == st.DEGRADED:
        lines += [f'Some checks fail ({code or "see the connection page"}); the connection is still in use.']
    elif key == st.SUSPENDED:
        lines += ['The emergency kill switch suspended it. Resume it after releasing the kill switch.']
    elif key == st.REVOKED:
        lines += ['The other application ended the connection.']
    elif key == st.CONNECTED:
        lines += [f'It was {st.LABELS.get(recovered_from, recovered_from)} before; every check passes again.']
    lines += ['', 'You get at most one of these per connection and status every 30 minutes.']
    return '\n'.join(lines)


def _send(conn_id, title, body, wid):
    from django.db import close_old_connections
    try:
        from core.mailer import (brand_name, default_from_email, get_smtp_connection, notification_recipients,
                                 send_to_recipients, site_url)
        from core.models import SystemSetting, SystemWarningNotification
        settings = SystemSetting.get_settings()
        if not settings.smtp_enabled or not settings.smtp_host:
            return
        recipients = notification_recipients()
        connection = get_smtp_connection(settings) if recipients else None
        if connection is None:
            return
        text = body + f'\n\nConnection: {site_url(settings)}/settings/integrations/connected-apps/{conn_id}/'
        sent = send_to_recipients(connection, default_from_email(settings), recipients,
                                  f'[{brand_name(settings)}] {title}', text)
        SystemWarningNotification.objects.filter(warning_id=wid).update(recipients_count=sent or 0)
    except Exception:
        logger.warning('could not send the Connect alert', exc_info=True)
    finally:
        close_old_connections()


# --- system warnings and the bell ----------------------------------------------------------

def attention_queryset():
    """Connections that need attention: Security Blocked, Degraded, Offline."""
    from django.db.models import Q
    from .models import Connection as C
    return C.objects.filter(Q(state=C.SECURITY_BLOCKED) |
                            Q(state=C.ACTIVE, health__in=(C.HEALTH_DEGRADED, C.HEALTH_OFFLINE)))


def system_warnings():
    """For core.system_warnings (and so the daily digest)."""
    from . import identity
    if not identity.enabled():
        return []
    out = []
    for conn in attention_queryset().order_by('remote_display_name')[:20]:
        d = st.display(conn)
        since = conn.security_block_at if d.key == st.SECURITY_BLOCKED else conn.last_failure_at
        out.append({
            'id': f'connect_{d.key}:{conn.pk}:{since:%Y%m%d%H}' if since else f'connect_{d.key}:{conn.pk}',
            'severity': {st.SECURITY_BLOCKED: 'critical', st.OFFLINE: 'high'}.get(d.key, 'medium'),
            'category': 'connect',
            'title': f'Connected application "{_name(conn)}" is {d.label}',
            'detail': (f'Reason: {conn.security_block_code}. It does not reconnect by itself.'
                       if d.key == st.SECURITY_BLOCKED else
                       'Clientst0r keeps retrying with backoff; events wait in the queue.'),
            'action_url': f'/settings/integrations/connected-apps/{conn.pk}/',
            'action_label': 'Open connection',
            'source_date': since,
        })
    return out


def bell_count(user, ctx):
    """core.notifications source: connections that need attention."""
    from accounts.permission_utils import user_has_perm
    from . import identity
    if not identity.enabled() or not user_has_perm(user, 'view_app_connections'):
        return None
    return attention_queryset().count()
