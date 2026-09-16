"""Shared outbound-notification plumbing.

Every scheduled task that emails an operator needs the same four things: an SMTP
connection built from `SystemSetting` (whose password is encrypted at rest), a
From address, a recipient list for an organization, and a send loop that does
not let one bad address stop the rest. Each task had been carrying its own copy
of all four, which is how `run_ssl_expiry_check` and `run_domain_expiry_check`
came to count what was expiring and then do nothing with it — the sending half
was the expensive half to write out for a fourth time.
"""
import logging

from django.contrib.auth import get_user_model
from django.core.mail import get_connection, send_mail
from django.db import models

logger = logging.getLogger('core')


def get_smtp_connection(settings):
    """Return a configured SMTP connection, or None if SMTP is not usable.

    None is the "don't send" signal and covers both "not configured" and
    "configured but the backend rejected the parameters" — callers treat those
    the same way, by skipping rather than failing the task.
    """
    if not settings.smtp_enabled or not settings.smtp_host:
        return None

    try:
        from vault.encryption import decrypt
        password = decrypt(settings.smtp_password) if settings.smtp_password else ''
    except Exception:
        # Pre-encryption rows store the password in the clear.
        password = settings.smtp_password or ''

    try:
        return get_connection(
            backend='django.core.mail.backends.smtp.EmailBackend',
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=password,
            use_tls=settings.smtp_use_tls,
            use_ssl=settings.smtp_use_ssl,
            timeout=15,
        )
    except Exception as e:
        logger.error(f'SMTP connection failed: {e}')
        return None


def default_from_email(settings):
    """From address, falling back to the SMTP username when none is set."""
    if settings.smtp_from_email:
        if settings.smtp_from_name:
            return f'{settings.smtp_from_name} <{settings.smtp_from_email}>'
        return settings.smtp_from_email
    return settings.smtp_username


def brand_name(settings):
    return settings.custom_company_name or settings.site_name or 'Client St0r'


def site_url(settings):
    return (settings.site_url or '').rstrip('/')


def notification_recipients(org_id=None):
    """Active superusers, plus the admins and owners of `org_id` if given.

    Superusers are always included: an expiring certificate is an operational
    problem for whoever runs the installation, not only for the tenant it
    belongs to. Addresses are de-duplicated, so a superuser who also
    administers the organization is mailed once.

    The reverse accessor is `memberships` (`accounts.Membership` sets it). The
    vault password expiry task, whose recipient query this replaces, asked for
    `organization_memberships`, which does not exist on any model — that query
    could only ever have raised FieldError. It had not yet been reached in
    production because the task returns early when no password carries an
    expiry date, so the failure was waiting on the first one that did.
    """
    User = get_user_model()
    qs = User.objects.filter(is_active=True, email__gt='')
    if org_id:
        qs = qs.filter(
            models.Q(is_superuser=True)
            | models.Q(
                memberships__organization_id=org_id,
                memberships__is_active=True,
                memberships__role__in=['admin', 'owner'],
            )
        )
    else:
        qs = qs.filter(is_superuser=True)
    return sorted(set(qs.values_list('email', flat=True)))


def send_to_recipients(connection, from_email, recipients, subject, body, on_error=None):
    """Send one message per recipient; return how many were accepted.

    One at a time rather than a single multi-recipient message, so that one
    address the server rejects does not take the whole notification with it —
    and so that recipients cannot see each other.
    """
    sent = 0
    for email in recipients:
        try:
            send_mail(
                subject=subject,
                message=body,
                from_email=from_email,
                recipient_list=[email],
                connection=connection,
                fail_silently=False,
            )
            sent += 1
        except Exception as e:
            logger.warning(f'Notification to {email} failed: {e}')
            if on_error:
                on_error(email, e)
    return sent
