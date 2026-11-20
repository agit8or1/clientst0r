"""Install readiness (Phase 96.1): the default administrator password check
and one composite list of what a new install still needs.

Default password
    install.sh creates ``admin`` with the password ``ChangeMe123!``. Checking
    a password costs a deliberate hash, so it is never done per request on its
    own: the result is stored per superuser together with a fingerprint of the
    stored hash (``ReadinessResult`` key ``default_password:<id>``, plus a cache
    entry). A request only compares fingerprints; the hash runs again only after
    the password actually changed.

Readiness
    ``run_checks()`` builds a list of check dicts (the shape of
    core.system_warnings: id, severity, title, detail, action_url,
    action_label, plus ``ok``) from the upgrade preflight checks and a few
    settings, and stores it under key ``install``. ``latest()`` returns the
    stored list without running anything. The checks only read; nothing here
    changes a setting.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger('core')

INSTALLER_PASSWORD = 'ChangeMe123!'
SCHEDULER_STALE_MINUTES = 30
_CACHE_PREFIX = 'readiness:defpw:'


def _reverse(name):
    try:
        return reverse(name)
    except Exception:
        return ''


def _fingerprint(user):
    return hashlib.sha256((user.password or '').encode()).hexdigest()


def default_password_in_use(user):
    """True while this active superuser's password is the installer's default.

    Cheap after the first call for a given password: the answer is remembered
    against a fingerprint of the stored hash, so only a changed password costs
    a new hash."""
    if not (user and user.is_authenticated and user.is_active and user.is_superuser):
        return False
    if not user.has_usable_password():
        return False
    fp = _fingerprint(user)
    ck = f'{_CACHE_PREFIX}{user.pk}'
    hit = cache.get(ck)
    if hit and hit[0] == fp:
        return hit[1]
    from core.models import ReadinessResult
    key = f'default_password:{user.pk}'
    row = ReadinessResult.objects.filter(key=key).only('data').first()
    if row and row.data.get('fingerprint') == fp:
        in_use = bool(row.data.get('in_use'))
    else:
        # No setter: a hasher upgrade must not rewrite the password here.
        in_use = check_password(INSTALLER_PASSWORD, user.password)
        ReadinessResult.objects.update_or_create(
            key=key, defaults={'data': {'fingerprint': fp, 'in_use': in_use}})
    cache.set(ck, (fp, in_use), 3600)
    return in_use


def superusers_with_default_password():
    User = get_user_model()
    return [u for u in User.objects.filter(is_superuser=True, is_active=True).order_by('pk')
            if default_password_in_use(u)]


# ---------------------------------------------------------------------------
# Composite readiness
# ---------------------------------------------------------------------------

def _check(cid, ok, title, detail, *, severity='medium', url='', label=''):
    return {
        'id': cid, 'ok': bool(ok), 'severity': 'ok' if ok else severity,
        'title': title, 'detail': detail,
        'action_url': '' if ok else url, 'action_label': '' if ok else label,
    }


def _from_preflight(cid, title, fn, url='', label=''):
    try:
        c = fn()
    except Exception as e:  # a broken check must not hide the others
        logger.warning('readiness check %s failed: %s', cid, e)
        return _check(cid, False, title, f'The check could not run: {e.__class__.__name__}',
                      severity='medium')
    severity = {'ok': 'ok', 'warn': 'medium', 'fail': 'high'}.get(c.status, 'medium')
    detail = c.detail + (f' — {c.hint}' if c.hint and c.status != 'ok' else '')
    row = _check(cid, c.status == 'ok', title, detail, severity=severity, url=url, label=label)
    return row


def _check_default_password():
    names = [u.get_username() for u in superusers_with_default_password()]
    if names:
        return _check('default_password', False, 'Default administrator password',
                      'Still in use by: ' + ', '.join(names) + '. Anyone who knows the installer\'s '
                      'password can sign in as an administrator.',
                      severity='high', url=_reverse('accounts:password_change'),
                      label='Change password')
    return _check('default_password', True, 'Default administrator password',
                  'No administrator signs in with the installer\'s password.')


def _check_superuser_2fa(settings):
    from django_otp import user_has_device
    User = get_user_model()
    missing = [u.get_username() for u in User.objects.filter(is_superuser=True, is_active=True)
               if not user_has_device(u)]
    if missing:
        sev = 'high' if settings.require_2fa else 'medium'
        return _check('superuser_2fa', False, 'Two-factor sign-in for administrators',
                      'Not set up for: ' + ', '.join(missing) + '.', severity=sev,
                      url=_reverse('accounts:two_factor_setup'), label='Set up 2FA')
    return _check('superuser_2fa', True, 'Two-factor sign-in for administrators',
                  'Every administrator has an authenticator.')


def _check_site_url(settings):
    if (settings.site_url or '').strip():
        return _check('site_url', True, 'Site address', settings.site_url)
    return _check('site_url', False, 'Site address',
                  'Not set. Links in e-mails and the customer portal need it.',
                  url=_reverse('core:settings_general'), label='Set site address')


def _check_mail(settings):
    if settings.smtp_enabled and (settings.smtp_host or '').strip() and settings.smtp_from_email:
        return _check('mail', True, 'Outgoing e-mail',
                      f'{settings.smtp_host}:{settings.smtp_port} — use "Send test" on the e-mail '
                      'page to confirm delivery.')
    return _check('mail', False, 'Outgoing e-mail',
                  'Not configured. Notifications, password resets and ticket replies are not sent.',
                  url=_reverse('core:settings_smtp'), label='Configure e-mail')


def _check_scheduler():
    from core.models import ScheduledTask
    last = (ScheduledTask.objects.filter(enabled=True, last_run_at__isnull=False)
            .order_by('-last_run_at').values_list('last_run_at', flat=True).first())
    url, label = _reverse('core:system_status'), 'Open system status'
    if not last:
        return _check('scheduler', False, 'Scheduler',
                      'No scheduled task has run yet. Check that clientst0r-scheduler.timer is '
                      'enabled (or the scheduler container is running).', severity='high',
                      url=url, label=label)
    age = timezone.now() - last
    if age > timedelta(minutes=SCHEDULER_STALE_MINUTES):
        return _check('scheduler', False, 'Scheduler',
                      f'Last task ran {int(age.total_seconds() // 60)} minutes ago.', severity='high',
                      url=url, label=label)
    return _check('scheduler', True, 'Scheduler',
                  f'Last task ran {max(0, int(age.total_seconds() // 60))} minute(s) ago.')


def _check_app_version():
    try:
        from core.system_warnings import _warnings_from_app_version
        rows = _warnings_from_app_version()
    except Exception:
        rows = []
    if rows:
        return _check('app_version', False, 'Application version', rows[0]['title'],
                      severity='low', url=_reverse('core:system_updates'), label='Open updates')
    return _check('app_version', True, 'Application version',
                  'Up to date, or no newer release is known yet.')


def run_checks():
    """Run every readiness check, store the list, and return it."""
    from core.models import ReadinessResult, SystemSetting
    from core.upgrade import preflight

    settings = SystemSetting.get_settings()
    updates_url = _reverse('core:system_updates')
    checks = [
        _check_default_password(),
        _check_superuser_2fa(settings),
        _check_site_url(settings),
        _check_mail(settings),
        _from_preflight('backup_destination', 'Backup destination', preflight.check_backup_destination,
                        updates_url, 'Open updates'),
        _check_scheduler(),
        _from_preflight('migrations', 'Database migrations',
                        lambda: preflight.check_pending_migrations(None, ''),
                        updates_url, 'Open updates'),
        _from_preflight('disk', 'Disk space', preflight.check_disk, updates_url, 'Open updates'),
        _check_app_version(),
    ]
    ReadinessResult.objects.update_or_create(key='install', defaults={'data': {'checks': checks}})
    return checks


def latest():
    """The stored readiness list and when it ran, without running anything:
    ``(checks, checked_at)`` or ``([], None)``."""
    from core.models import ReadinessResult
    row = ReadinessResult.objects.filter(key='install').first()
    if not row:
        return [], None
    return row.data.get('checks', []), row.checked_at


def summary(checks):
    open_ = [c for c in checks if not c.get('ok')]
    return {'total': len(checks), 'open': len(open_),
            'worst': next((s for s in ('critical', 'high', 'medium', 'low')
                           if any(c['severity'] == s for c in open_)), 'ok')}
