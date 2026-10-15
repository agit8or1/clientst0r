"""
Effective security policy: environment override > saved Security setting > default.

Settings → Security (core.SystemSetting) used to be saved and never read;
the real values came only from environment variables. Every consumer now asks
this module instead:

  item                 env var (operator override)   saved field
  -------------------  ----------------------------  ----------------------------
  idle timeout         SESSION_IDLE_TIMEOUT (sec)    session_idle_timeout_minutes
  max session length   SESSION_COOKIE_AGE (sec)      session_timeout_minutes
  require 2FA          REQUIRE_2FA                   require_2fa
  password min length  PASSWORD_MIN_LENGTH           password_min_length
  password special ch  PASSWORD_REQUIRE_SPECIAL      password_require_special
  lockout attempts     AXES_FAILURE_LIMIT            failed_login_attempts
  lockout duration     AXES_COOLOFF_TIME (hours)     lockout_duration_minutes

config/settings.py exposes each env value as a Django setting that is None
unless the variable is explicitly set (see SECURITY_POLICY_ENV below). When
it is set, it wins outright and the UI shows the field read-only ("set by
environment"), so the UI can never weaken an operator-configured value.

Saved values are cached for CACHE_SECONDS per process and the cache is
dropped whenever SystemSetting is saved, so a change in the UI applies within
a few seconds on every worker.
"""
import re
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _, ngettext

CACHE_KEY = 'core:security_policy:saved:v1'
CACHE_SECONDS = 30


@dataclass(frozen=True)
class PolicyItem:
    key: str          # SystemSetting field
    setting: str      # Django setting holding the env override (None = unset)
    env: str          # environment variable name shown in the UI
    default: object
    minimum: int = None
    maximum: int = None
    scale: float = 1  # env setting unit -> policy unit (minutes for times)


ITEMS = {
    'session_idle_timeout_minutes': PolicyItem(
        'session_idle_timeout_minutes', 'SESSION_IDLE_TIMEOUT', 'SESSION_IDLE_TIMEOUT', 60, 5, 1440,
        scale=1 / 60),
    'session_timeout_minutes': PolicyItem(
        'session_timeout_minutes', 'SESSION_ABSOLUTE_TIMEOUT', 'SESSION_COOKIE_AGE', 480, 15, 10080,
        scale=1 / 60),
    'require_2fa': PolicyItem('require_2fa', 'REQUIRE_2FA', 'REQUIRE_2FA', True),
    'password_min_length': PolicyItem(
        'password_min_length', 'PASSWORD_MIN_LENGTH', 'PASSWORD_MIN_LENGTH', 12, 8, 128),
    'password_require_special': PolicyItem(
        'password_require_special', 'PASSWORD_REQUIRE_SPECIAL', 'PASSWORD_REQUIRE_SPECIAL', True),
    'failed_login_attempts': PolicyItem(
        'failed_login_attempts', 'LOCKOUT_FAILURE_LIMIT', 'AXES_FAILURE_LIMIT', 5, 3, 20),
    'lockout_duration_minutes': PolicyItem(
        'lockout_duration_minutes', 'LOCKOUT_COOLOFF_HOURS', 'AXES_COOLOFF_TIME', 30, 5, 1440,
        scale=60),
}


def invalidate(**kwargs):
    cache.delete(CACHE_KEY)


def _saved_values():
    values = cache.get(CACHE_KEY)
    if values is not None:
        return values
    values = {}
    try:
        from core.models import SystemSetting
        row = SystemSetting.objects.filter(pk=1).values(*ITEMS.keys()).first()
        if row:
            values = row
    except Exception:
        # Table missing (fresh install / mid-migration) — use defaults, and
        # don't cache so the real values are picked up once it exists.
        return {}
    cache.set(CACHE_KEY, values, CACHE_SECONDS)
    return values


def env_override(key):
    """The operator's environment value for this item (in policy units), or None."""
    item = ITEMS[key]
    value = getattr(settings, item.setting, None)
    if value is None:
        return None
    if isinstance(item.default, bool):
        return bool(value)
    return value * item.scale if item.scale != 1 else value


def is_env_locked(key):
    return env_override(key) is not None


def _clamp(item, value):
    if item.minimum is not None:
        value = max(int(value), item.minimum)
    if item.maximum is not None:
        value = min(int(value), item.maximum)
    return value


def get(key):
    """Effective value: env override, else saved setting, else default."""
    item = ITEMS[key]
    override = env_override(key)
    if override is not None:
        return override
    value = _saved_values().get(key)
    if value is None:
        return item.default
    if isinstance(item.default, bool):
        return bool(value)
    try:
        return _clamp(item, value)
    except (TypeError, ValueError):
        return item.default


def describe():
    """For the settings page: {key: {'value', 'locked', 'env'}}."""
    return {
        key: {'value': get(key), 'locked': is_env_locked(key), 'env': item.env}
        for key, item in ITEMS.items()
    }


# ---- convenience accessors ------------------------------------------------

def idle_timeout_seconds():
    return int(get('session_idle_timeout_minutes') * 60)


def session_max_age_seconds():
    return int(get('session_timeout_minutes') * 60)


def require_2fa():
    return bool(get('require_2fa'))


def lockout_failure_limit():
    return int(get('failed_login_attempts'))


def lockout_cooloff():
    return timedelta(minutes=get('lockout_duration_minutes'))


# ---- django-axes hooks (AXES_FAILURE_LIMIT / AXES_COOLOFF_TIME) ------------

def axes_failure_limit(request, credentials):
    return lockout_failure_limit()


def axes_cool_off():
    return lockout_cooloff()


# ---- password validator (AUTH_PASSWORD_VALIDATORS) -------------------------

SPECIAL_RE = re.compile(r'[^A-Za-z0-9]')


class SystemPasswordPolicyValidator:
    """Minimum length + special-character rule from the Security settings."""

    def validate(self, password, user=None):
        errors = []
        min_length = int(get('password_min_length'))
        if len(password) < min_length:
            errors.append(ValidationError(
                ngettext(
                    'This password is too short. It must contain at least %(min_length)d character.',
                    'This password is too short. It must contain at least %(min_length)d characters.',
                    min_length,
                ),
                code='password_too_short',
                params={'min_length': min_length},
            ))
        if get('password_require_special') and not SPECIAL_RE.search(password):
            errors.append(ValidationError(
                _('This password must contain at least one special character (e.g. !@#$%^&*).'),
                code='password_no_special',
            ))
        if errors:
            raise ValidationError(errors)

    def get_help_text(self):
        min_length = int(get('password_min_length'))
        text = ngettext(
            'Your password must contain at least %(min_length)d character.',
            'Your password must contain at least %(min_length)d characters.',
            min_length,
        ) % {'min_length': min_length}
        if get('password_require_special'):
            text += ' ' + _('It must include at least one special character.')
        return text


def _connect_signals():
    from django.db.models.signals import post_save
    from core.models import SystemSetting
    post_save.connect(invalidate, sender=SystemSetting, dispatch_uid='security_policy_invalidate')
