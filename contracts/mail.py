"""Outgoing contract e-mail. Copy is editable in Contract Settings and uses
the same `{{field}}` placeholders as contracts (plain values, never code)."""
from __future__ import annotations

from django.conf import settings as django_settings
from django.core.mail import EmailMessage, get_connection

from .content import fmt_date, resolve_plain
from .models import ContractSettings


class MailNotConfigured(RuntimeError):
    pass


def _system():
    from core.models import SystemSetting
    return SystemSetting.get_settings()


def connection():
    from core import mailer
    conn = mailer.get_smtp_connection(_system())
    if conn is not None:
        return conn
    backend = getattr(django_settings, 'EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')
    if backend != 'django.core.mail.backends.smtp.EmailBackend':
        return get_connection()  # console / file / test backends
    raise MailNotConfigured('E-mail (SMTP) is not configured in Settings → System → E-mail.')


def from_email():
    from core import mailer
    return mailer.default_from_email(_system()) or getattr(django_settings, 'DEFAULT_FROM_EMAIL', None)


def base_url():
    """The site's public address for links in e-mails: Settings → site URL,
    else the SITE_URL setting. A signing link must be absolute, so with
    neither set the e-mail fails (and is retried) instead of sending a
    link that leads nowhere."""
    from django.conf import settings as django_settings

    from core import mailer
    url = mailer.site_url(_system()) or str(getattr(django_settings, 'SITE_URL', '') or '').rstrip('/')
    if not url.startswith(('https://', 'http://')):
        raise MailNotConfigured('Set the site URL (Settings → General) so signing links can be e-mailed.')
    return url


def _ctx(inv, settings, link=''):
    c = inv.contract
    return {
        'signer.name': inv.name, 'signer.email': inv.email, 'contract.title': c.title,
        'contract.reference': c.reference, 'client.name': c.client_name,
        'provider.name': settings.provider_display_name(), 'link': link,
        'invitation.expires': fmt_date(inv.expires_at.date()) if inv.expires_at else 'no set date',
        'contract.acceptance_deadline': fmt_date(c.acceptance_deadline),
    }


def _footer(settings):
    return f'\n\n{settings.email_footer}' if settings.email_footer else ''


def send_invitation(inv, raw_token, *, reminder=False):
    from django.urls import reverse
    settings = ContractSettings.for_organization(inv.contract.organization)
    link = base_url() + reverse('contract_sign:open', kwargs={'token': raw_token})
    ctx = _ctx(inv, settings, link)
    subject = resolve_plain(settings.reminder_subject if reminder else settings.invitation_subject, ctx)
    body = resolve_plain(settings.reminder_body if reminder else settings.invitation_body, ctx)
    if link not in body:  # the wording was edited without {{link}}: the link is still sent
        body += f'\n\nOpen the contract here:\n{link}'
    msg = EmailMessage(subject=subject[:200], body=body + _footer(settings), from_email=from_email(),
                       to=[inv.email], connection=connection())
    if not msg.send(fail_silently=False):
        raise RuntimeError('the mail server did not accept the message')


def send_code(inv, code):
    settings = ContractSettings.for_organization(inv.contract.organization)
    body = (f'Your verification code for "{inv.contract.title}" ({inv.contract.reference}) is:\n\n    {code}\n\n'
            'It expires in 10 minutes. If you did not ask for it, ignore this e-mail.'
            f'\n\n— {settings.provider_display_name()}')
    msg = EmailMessage(subject=f'Verification code for {inv.contract.reference}', body=body,
                       from_email=from_email(), to=[inv.email], connection=connection())
    if not msg.send(fail_silently=False):
        raise RuntimeError('the mail server did not accept the message')


def send_staff(to, subject, body, link_path=''):
    try:
        link = (base_url() + link_path) if link_path else ''
    except MailNotConfigured:   # staff can still find it in the app
        link = ''
    msg = EmailMessage(subject=subject, body=body + (f'\n\nOpen the contract: {link}' if link else ''),
                       from_email=from_email(), to=[to], connection=connection())
    if not msg.send(fail_silently=False):
        raise RuntimeError('the mail server did not accept the message')


def send_completed_copy(inv):
    from .pdf import final_filename
    settings = ContractSettings.for_organization(inv.contract.organization)
    ctx = _ctx(inv, settings)
    v = inv.version
    msg = EmailMessage(subject=resolve_plain(settings.completed_subject, ctx)[:200],
                       body=resolve_plain(settings.completed_body, ctx) + _footer(settings),
                       from_email=from_email(), to=[inv.email], connection=connection())
    msg.attach(final_filename(v), bytes(v.final_pdf), 'application/pdf')
    if not msg.send(fail_silently=False):
        raise RuntimeError('the mail server did not accept the message')
