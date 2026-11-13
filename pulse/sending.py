"""Sending a pulse check round, and the scheduled sends.

A send creates one PulseResponse per recipient (each with its own link
token), then e-mails the links. Without outgoing e-mail (Settings → Email /
SMTP) the responses are still created: portal users answer from the portal's
Feedback page, and the send records that nothing was e-mailed.
"""
from __future__ import annotations

import logging

from django.core import signing
from django.core.mail import EmailMessage
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from core.mailer import brand_name, default_from_email, get_smtp_connection

from . import audience
from .models import PulseCheck, PulseResponse, PulseSend, default_expiry

logger = logging.getLogger('pulse')

OPT_OUT_SALT = 'pulse.optout'


def pulse_enabled():
    try:
        from core.models import SystemSetting
        return bool(SystemSetting.get_settings().pulse_enabled)
    except Exception:
        return False


def opt_out_token(email):
    return signing.dumps({'e': (email or '').strip().lower()}, salt=OPT_OUT_SALT, compress=True)


def opt_out_email(token):
    try:
        return signing.loads(token, salt=OPT_OUT_SALT).get('e') or None
    except (signing.BadSignature, AttributeError):
        return None


def _base_url(ss):
    from core.portal_surface import portal_site_url
    return portal_site_url(ss)


def _render_email(response, raw_token, *, brand, base):
    send = response.send
    link = base + reverse('portal:pulse_respond', kwargs={'token': raw_token})
    unsub = base + reverse('portal:pulse_opt_out', kwargs={'token': opt_out_token(response.email)})
    subject = f'{brand}: {send.pulse_check.name} — a minute of feedback?'
    lines = [f'Hi {response.name},' if response.name else 'Hello,', '']
    if send.intro:
        lines += [send.intro.strip(), '']
    lines += [
        f'We would like to hear how our service is going for {response.organization.name}. '
        f'There are {len(send.questions)} short question(s):',
        '',
        f'  {link}',
        '',
        f'The link is just for you and stays open until {timezone.localtime(send.expires_at):%B %d, %Y}.',
    ]
    if response.user_id:
        lines += ['You can also answer from the Feedback page of the customer portal.']
    lines += ['', 'Thank you,', brand, '', f'Don\'t want these feedback requests? {unsub}']
    return subject, '\n'.join(lines), unsub


def send_check(check, *, by=None, trigger=PulseSend.TRIGGER_MANUAL, period_key=None,
               now=None, connection=None, request=None):
    """Create and e-mail one round of `check`. Returns the PulseSend, or None
    when `period_key` was already sent (scheduled sends are idempotent)."""
    from core.models import SystemSetting
    now = now or timezone.now()
    recipients, opted_out = audience.resolve(check)
    created = []
    try:
        with transaction.atomic():
            send = PulseSend.objects.create(
                pulse_check=check, trigger=trigger, period_key=period_key,
                questions=check.question_snapshot(), intro=check.intro, sent_by=by,
                expires_at=default_expiry(check, now), recipient_count=len(recipients),
                opted_out_count=opted_out,
            )
            for r in recipients:
                resp = PulseResponse(send=send, organization=r.organization, user=r.user,
                                     contact=r.contact, email=r.email, name=r.name[:255])
                resp.issue_token()
                resp.save()
                created.append(resp)
    except IntegrityError:
        if period_key:
            return None
        raise

    ss = SystemSetting.get_settings()
    if connection is None and created:
        connection = get_smtp_connection(ss)
    emailed = 0
    if connection is not None:
        brand, base, from_email = brand_name(ss), _base_url(ss), default_from_email(ss)
        for resp in created:
            subject, body, unsub = _render_email(resp, resp.raw_token, brand=brand, base=base)
            msg = EmailMessage(subject=subject, body=body, from_email=from_email, to=[resp.email],
                               connection=connection,
                               headers={'List-Unsubscribe': f'<{unsub}>'})
            try:
                msg.send(fail_silently=False)
                resp.email_status = PulseResponse.EMAIL_SENT
                emailed += 1
            except Exception as exc:
                logger.warning('pulse check e-mail to %s failed: %s', resp.email, exc)
                resp.email_status = PulseResponse.EMAIL_FAILED
            resp.save(update_fields=['email_status'])
    send.emailed_count = emailed
    send.save(update_fields=['emailed_count'])
    _audit_send(send, created, by=by, request=request)
    return send


def _audit_send(send, responses, *, by=None, request=None):
    from audit.models import AuditLog
    per_org = {}
    for r in responses:
        per_org.setdefault(r.organization_id, [r.organization, 0])
        per_org[r.organization_id][1] += 1
    path = getattr(request, 'path', '') if request is not None else ''
    common = {'event': 'pulse_send', 'send_id': send.pk, 'check_id': send.pulse_check_id,
              'trigger': send.trigger, 'period_key': send.period_key}
    AuditLog.log(
        user=by, action='create', object_type='pulse.PulseSend', object_id=send.pk,
        object_repr=str(send)[:255],
        description=(f'Pulse check "{send.pulse_check.name}" sent to {send.recipient_count} '
                     f'recipient(s) in {len(per_org)} organization(s), {send.emailed_count} e-mailed'),
        path=path, extra_data={**common, 'organizations': list(per_org)},
    )
    for org, count in per_org.values():
        AuditLog.log(
            user=by, action='create', organization=org, object_type='pulse.PulseSend',
            object_id=send.pk, object_repr=str(send)[:255],
            description=f'Pulse check "{send.pulse_check.name}" sent to {count} person(s) at {org.name}',
            path=path, extra_data={**common, 'recipients': count},
        )


def send_due(now=None, connection=None):
    """Scheduled sends: one per recurring check per period. Safe to run any
    number of times — a period already sent is skipped (unique period key)."""
    out = {'sent': 0, 'skipped': 0, 'disabled': False}
    if not pulse_enabled():
        out['disabled'] = True
        return out
    now = now or timezone.now()
    today = timezone.localdate(now)
    checks = PulseCheck.objects.filter(is_active=True).exclude(schedule=PulseCheck.SCHEDULE_NONE)
    for check in checks:
        if not check.is_due(today):
            continue
        key = check.period_key(today)
        if PulseSend.objects.filter(pulse_check=check, period_key=key).exists():
            out['skipped'] += 1
            continue
        send = send_check(check, trigger=PulseSend.TRIGGER_SCHEDULE, period_key=key,
                          now=now, connection=connection)
        if send is None:
            out['skipped'] += 1
        else:
            out['sent'] += 1
    return out
