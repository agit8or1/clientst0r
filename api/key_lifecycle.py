"""API key lifecycle: allowed sources, expiry and rotation (roadmap 81.4).

Allowed sources are API-key-scoped allow rules in API Access Control, so the
same policy engine enforces them and they show on that page too."""
from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.models import AuditLog

MAX_SOURCES = 50
EXPIRY_CHOICES = (('', 'Never'), ('30', '30 days'), ('90', '90 days'), ('180', '180 days'),
                  ('365', '1 year'), ('custom', 'On a date…'))
GRACE_CHOICES = (('0', 'Stop the old key now'), ('1', '1 hour'), ('24', '24 hours'),
                 ('72', '3 days'), ('168', '7 days'))
MAX_RATE_PER_MINUTE = 10000


def parse_sources(text):
    """Lines or commas of addresses / CIDR ranges -> sorted unique networks."""
    from api_access.models import normalize_network
    items = [part.strip() for line in (text or '').splitlines() for part in line.split(',')]
    items = [i for i in items if i and not i.startswith('#')]
    networks, errors = [], []
    for item in items:
        try:
            networks.append(normalize_network(item))
        except ValidationError as exc:
            errors.extend(exc.messages)
    if errors:
        raise ValidationError(errors)
    networks = sorted(set(networks))
    if len(networks) > MAX_SOURCES:
        raise ValidationError(f'At most {MAX_SOURCES} allowed sources per key.')
    return networks


def parse_expiry(choice, custom_date, current=None):
    """Return (expires_at or None). Raises ValidationError for bad input."""
    choice = (choice or '').strip()
    if choice == 'keep':
        return current
    if not choice:
        return None
    if choice == 'custom':
        try:
            day = datetime.strptime((custom_date or '').strip(), '%Y-%m-%d').date()
        except ValueError:
            raise ValidationError('Enter the expiry date as YYYY-MM-DD.')
        when = timezone.make_aware(datetime.combine(day, time(23, 59)))
        if when <= timezone.now():
            raise ValidationError('The expiry date must be in the future.')
        return when
    if choice.isdigit() and int(choice) in (30, 90, 180, 365):
        return timezone.now() + timedelta(days=int(choice))
    raise ValidationError('Choose an expiry.')


def parse_rate(value):
    value = (value or '').strip()
    if not value:
        return None
    if not value.isdigit() or not (1 <= int(value) <= MAX_RATE_PER_MINUTE):
        raise ValidationError(f'The rate limit must be a whole number from 1 to {MAX_RATE_PER_MINUTE}.')
    return int(value)


def parse_cert(value):
    from api_access.mtls import normalize_fingerprint
    try:
        return normalize_fingerprint(value)
    except ValueError as exc:
        raise ValidationError(str(exc))


def key_sources(key):
    from api_access.models import ApiAccessRule as R
    return sorted(R.objects.filter(scope=R.SCOPE_API_KEY, api_key=key, action=R.ACTION_ALLOW,
                                   is_active=True).values_list('network', flat=True).distinct())


def source_change_cuts_off(key, networks):
    """True when the key was last used from an address outside ``networks``."""
    import ipaddress
    if not networks or not key.last_used_ip:
        return False
    try:
        ip = ipaddress.ip_address(key.last_used_ip)
    except ValueError:
        return False
    return not any(ip.version == n.version and ip in n
                   for n in (ipaddress.ip_network(x) for x in networks))


def set_sources(key, networks, user):
    """Make ``networks`` the key's allowed sources (empty = no key restriction)."""
    from api_access import policy as P
    from api_access.models import ApiAccessRule as R, ApiAccessSettings
    before = key_sources(key)
    if before == sorted(networks):
        return False
    with transaction.atomic():
        R.objects.filter(scope=R.SCOPE_API_KEY, api_key=key, action=R.ACTION_ALLOW).delete()
        for network in networks:
            R.objects.create(name=f'{key.name[:90]} — allowed source', network=network,
                             action=R.ACTION_ALLOW, surface=R.SURFACE_API, scope=R.SCOPE_API_KEY,
                             api_key=key, created_by=user, updated_by=user,
                             description='Set on the API key')
    ApiAccessSettings.bump(user)
    P.reset_cache()
    AuditLog.log(user=user, action='update', organization=key.organization, object_type='APIKey',
                 object_id=key.pk, object_repr=str(key)[:200],
                 description=f'Allowed sources for API key {key.key_prefix}… changed',
                 extra_data={'before': before, 'after': sorted(networks)})
    return True


def rotate(key, user, grace_hours):
    """Issue a replacement for ``key`` and wind the old one down.

    The new key keeps the name, owner, level, scope, expiry, rate limit and
    every network rule of the old one. Returns (new_key, plaintext)."""
    from api.models import APIKey
    from api_access import policy as P
    from api_access.models import ApiAccessRule as R, ApiAccessSettings
    now = timezone.now()
    with transaction.atomic():
        new_key, plaintext = APIKey.create_key(organization=key.organization, user=key.user,
                                               name=key.name, role=key.role, scope=key.scope)
        new_key.expires_at = key.expires_at
        new_key.rate_limit_per_minute = key.rate_limit_per_minute
        new_key.client_cert_sha256 = key.client_cert_sha256
        new_key.rotated_from = key
        new_key.save(update_fields=['expires_at', 'rate_limit_per_minute', 'client_cert_sha256',
                                    'rotated_from'])
        rules = list(R.objects.filter(scope=R.SCOPE_API_KEY, api_key=key))
        for rule in rules:
            rule.pk = None
            rule.api_key = new_key
            rule.match_count, rule.last_matched_at = 0, None
            rule.created_by = rule.updated_by = user
            rule.save()
        key.rotated_at = now
        if grace_hours <= 0:
            key.is_active = False
        else:
            end = now + timedelta(hours=grace_hours)
            key.expires_at = min(end, key.expires_at) if key.expires_at else end
        key.save(update_fields=['rotated_at', 'is_active', 'expires_at'])
    if rules:
        ApiAccessSettings.bump(user)
        P.reset_cache()
    AuditLog.log(user=user, action='update', organization=key.organization, object_type='APIKey',
                 object_id=key.pk, object_repr=str(key)[:200],
                 description=f'API key {key.key_prefix}… rotated to {new_key.key_prefix}…',
                 extra_data={'new_key_id': new_key.pk, 'grace_hours': grace_hours,
                             'old_key_expires_at': key.expires_at.isoformat() if key.expires_at else None,
                             'network_rules_copied': len(rules)})
    return new_key, plaintext
