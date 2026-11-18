"""Notifications for repeated API access refusals (roadmap 81.7).

A source refused 100 times within an hour triggers one e-mail to the install's
administrators (superusers with an address), at most once per source per day,
and the source is listed among the system warnings (and so in the daily
digest) while it keeps being refused. Addresses and counts only: no request
contents, headers or key secrets."""
import logging
import threading
from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

logger = logging.getLogger('api_access')

EMAIL_AT = 100          # refusals from one source within an hour
WARN_AT = 100           # refusals from one source within 24 hours
WARN_HIGH_AT = 1000


def warning_id(ip_text, day=None):
    return f'api_access_source:{ip_text}:{(day or timezone.localdate()).isoformat()}'[:200]


def notify_repeat_source(ip_text, count):
    """Called from the refusal recorder when a source crosses EMAIL_AT in an hour."""
    if not ip_text:
        return
    from core.models import SystemWarningNotification
    wid = warning_id(ip_text)
    try:
        _, created = SystemWarningNotification.objects.get_or_create(
            warning_id=wid, defaults={'severity': 'high', 'title': _title(ip_text, count)})
    except Exception:
        logger.warning('could not record an API access notification', exc_info=True)
        return
    if not created:
        return  # already sent today (by this or another worker)
    threading.Thread(target=_send, args=(ip_text, count, wid), daemon=True).start()


def _title(ip_text, count):
    return f'API access: {ip_text} refused {count}+ times in an hour'


def _send(ip_text, count, wid):
    from django.db import close_old_connections
    try:
        from core.mailer import (brand_name, default_from_email, get_smtp_connection,
                                 notification_recipients, send_to_recipients, site_url)
        from core.models import SystemSetting, SystemWarningNotification
        settings = SystemSetting.get_settings()
        if not settings.smtp_enabled or not settings.smtp_host:
            return
        recipients = notification_recipients()
        connection = get_smtp_connection(settings) if recipients else None
        if connection is None:
            return
        base = site_url(settings)
        body = '\n'.join([
            f'{brand_name(settings)} refused {count} API or webhook requests from {ip_text} within an hour.',
            '',
            'If this is one of your integrations, an access rule or key restriction may be blocking it.',
            'If you do not recognise the address, no action is needed: the requests were refused.',
            '',
            f'Refused requests from this address: {base}/settings/security/api-access/refused/?ip={ip_text}',
            '',
            'You get at most one of these per address per day.',
        ])
        sent = send_to_recipients(connection, default_from_email(settings), recipients,
                                  f'[{brand_name(settings)}] {_title(ip_text, count)}', body)
        SystemWarningNotification.objects.filter(warning_id=wid).update(recipients_count=sent or 0)
    except Exception:
        logger.warning('could not send the API access notification', exc_info=True)
    finally:
        close_old_connections()


def system_warnings():
    """Sources refused WARN_AT+ times in the last 24 hours, for core.system_warnings."""
    from .models import ApiAccessDecision
    since = timezone.now() - timedelta(hours=24)
    rows = (ApiAccessDecision.objects.filter(last_seen_at__gte=since).exclude(source_ip=None)
            .values('source_ip').annotate(total=Sum('count')).filter(total__gte=WARN_AT)
            .order_by('-total')[:10])
    out = []
    for row in rows:
        ip, total = row['source_ip'], row['total']
        out.append({
            'id': warning_id(ip),
            'severity': 'high' if total >= WARN_HIGH_AT else 'medium',
            'category': 'api_access',
            'title': f'API access: {ip} refused {total} times in 24 hours',
            'detail': 'A source keeps calling the API or a webhook and is refused. Check whether it is an '
                      'integration blocked by a rule, or unwanted traffic.',
            'action_url': f'/settings/security/api-access/refused/?ip={ip}',
            'action_label': 'Review refused requests',
            'source_date': None,
        })
    return out
