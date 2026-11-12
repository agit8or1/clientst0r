"""E-mail alerts to every active superuser through the SMTP server configured
in Settings -> Email.

This is the alert path of the automated security scan (`run_security_scan`),
moved here so other admin alerts (the Snyk CLI update check) reach the same
people the same way instead of growing a second mechanism.
"""
import logging

from django.contrib.auth import get_user_model

logger = logging.getLogger('core')


def email_superusers(subject, body, settings=None, log_prefix='superuser_alerts', write=None):
    """Send `subject`/`body` to every active superuser with an e-mail address.

    Returns the number of messages sent. Returns 0 without raising when SMTP is
    not configured, the connection cannot be built, or there is nobody to mail.
    `write`, when given, is called with a short line per recipient (the
    management commands pass their stdout writer).
    """
    from django.core.mail import get_connection, send_mail
    from core.models import SystemSetting

    if settings is None:
        settings = SystemSetting.get_settings()

    if not settings.smtp_enabled or not settings.smtp_host:
        logger.warning(f'[{log_prefix}] SMTP not configured — cannot send alerts')
        return 0

    # EncryptedTextField: the attribute is already the plaintext.
    password = settings.smtp_password or ''
    try:
        connection = get_connection(
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
        logger.error(f'[{log_prefix}] SMTP connection failed: {e}')
        return 0

    from_email = (
        f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
        if settings.smtp_from_name and settings.smtp_from_email
        else settings.smtp_from_email or settings.smtp_username
    )

    User = get_user_model()
    superusers = User.objects.filter(
        is_superuser=True, is_active=True, email__isnull=False,
    ).exclude(email='')
    sent = 0
    for user in superusers:
        try:
            send_mail(
                subject=subject,
                message=body,
                from_email=from_email,
                recipient_list=[user.email],
                connection=connection,
                fail_silently=False,
            )
            sent += 1
            if write:
                write(f'    Sent to {user.email}')
        except Exception as e:
            if write:
                write(f'    Failed to send to {user.email}: {e}')
            logger.error(f'[{log_prefix}] Email to {user.email} failed: {e}')
    return sent
