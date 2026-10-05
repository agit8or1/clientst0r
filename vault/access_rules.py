"""
Decision engine for VaultAccessRule (v3.17.163).

evaluate(password, user, request) -> {'allowed': bool, 'reason': str,
'matched_rule_id': int or None}.

Default policy when no rules match: ALLOW (back-compat). DENY rules
win over ALLOW rules. Priority breaks ties (lower priority number =
checked first; first matching ALLOW rule sets the verdict, but explicit
DENY always wins).
"""
import ipaddress
import logging
from datetime import datetime
import zoneinfo

logger = logging.getLogger('vault.access_rules')


def _client_ip(request):
    from core.client_ip import get_client_ip
    return get_client_ip(request)


def _country_for_ip(ip):
    """Returns ISO alpha-2 country code or None.

    First tries the bundled GeoIP2 db (django.contrib.gis.geoip2). If
    that's not configured, falls back to the firewall middleware's
    HTTP-API helper. Returns None if both fail.
    """
    if not ip:
        return None
    # Skip lookups for private / loopback IPs entirely.
    try:
        ip_obj = ipaddress.ip_address(ip)
        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
            return None
    except ValueError:
        return None

    # Try local GeoIP2 first.
    try:
        from django.contrib.gis.geoip2 import GeoIP2
        g = GeoIP2()
        c = g.country(ip)
        cc = (c.get('country_code') or '').upper()
        if cc:
            return cc
    except Exception as exc:
        logger.debug('GeoIP2 lookup failed for %s: %s', ip, exc)

    # Fall back to the firewall middleware's HTTP-API helper.
    try:
        from core.firewall_middleware import FirewallMiddleware
        cc, _ = FirewallMiddleware(get_response=lambda r: None).geoip_lookup(ip)
        return (cc or '').upper() or None
    except Exception as exc:
        logger.debug('country lookup fallback failed for %s: %s', ip, exc)
        return None


def _ip_in_cidrs(ip, cidrs):
    if not cidrs:
        return False
    try:
        ip_obj = ipaddress.ip_address(ip)
    except (ValueError, TypeError):
        return False
    for c in cidrs:
        try:
            if ip_obj in ipaddress.ip_network(c, strict=False):
                return True
        except ValueError:
            continue
    return False


def _check_rule_conditions(rule, ip, country_code, now_utc):
    """Return True if this rule's conditions match the current request.

    Semantics are effect-aware:
      * For ALLOW rules: conditions match when the request is in the
        rule's "allowed" patterns AND not in its "blocked" patterns.
      * For DENY rules: conditions match when the request hits any of
        the rule's "blocked" patterns OR (if allowed_* are set) the
        request is within the allowed-pattern target. In other words,
        a DENY rule "fires" when the request is in the surface area
        the admin painted with allowed_/blocked_*.

    Time-of-day window applies the same way to both effects: the rule
    only fires inside the allowed window.
    """
    # ----- Time first (gates BOTH effects identically) -----
    if rule.allowed_weekdays or rule.allowed_hour_start or rule.allowed_hour_end:
        try:
            tz = zoneinfo.ZoneInfo(rule.timezone or 'UTC')
        except Exception:
            tz = zoneinfo.ZoneInfo('UTC')
        local_now = now_utc.astimezone(tz)
        if rule.allowed_weekdays and local_now.weekday() not in rule.allowed_weekdays:
            return False
        if rule.allowed_hour_start and local_now.time() < rule.allowed_hour_start:
            return False
        if rule.allowed_hour_end and local_now.time() > rule.allowed_hour_end:
            return False

    is_deny = rule.effect == 'deny'

    # ----- GeoIP -----
    geoip_constrained = bool(rule.allowed_countries or rule.blocked_countries)
    geoip_match = False
    if geoip_constrained:
        in_blocked = bool(
            rule.blocked_countries and country_code
            and country_code in rule.blocked_countries
        )
        in_allowed = bool(
            rule.allowed_countries and country_code
            and country_code in rule.allowed_countries
        )
        if is_deny:
            # DENY fires if blocked-country hits, OR if allowed list set and
            # the country is in it (admin painted that surface as "deny here").
            geoip_match = in_blocked or in_allowed
            if not geoip_match:
                return False
        else:
            # ALLOW: must NOT be in blocked, and (if allowed set) must be in allowed
            if in_blocked:
                return False
            if rule.allowed_countries and not in_allowed:
                return False

    # ----- IP CIDRs -----
    cidr_constrained = bool(rule.allowed_cidrs or rule.blocked_cidrs)
    if cidr_constrained:
        in_blocked = _ip_in_cidrs(ip, rule.blocked_cidrs)
        in_allowed = _ip_in_cidrs(ip, rule.allowed_cidrs)
        if is_deny:
            cidr_match = in_blocked or in_allowed
            if not cidr_match:
                # If GeoIP already matched, that alone fires the DENY -- but
                # if a CIDR constraint was set and the IP doesn't match it,
                # only fire if there was NO geoip constraint either.
                if geoip_constrained:
                    # geoip already matched (we returned earlier otherwise);
                    # require CIDR to also match for combined intent.
                    return False
                return False
        else:
            if in_blocked:
                return False
            if rule.allowed_cidrs and not in_allowed:
                return False

    # If a DENY rule has NO geoip + NO cidr + NO time constraints, it is a
    # blanket DENY -> fires for everyone.
    if is_deny and not geoip_constrained and not cidr_constrained \
            and not (rule.allowed_weekdays or rule.allowed_hour_start
                     or rule.allowed_hour_end):
        return True

    return True


def evaluate(password, user, request):
    """
    Evaluate every active VaultAccessRule that targets `password` or `user`
    or the password's organization. Apply DENY-wins-then-priority logic.
    """
    from django.utils import timezone
    from .models import VaultAccessRule

    if password is None:
        return {'allowed': True, 'reason': '', 'matched_rule_id': None}

    rules = VaultAccessRule.objects.filter(
        is_active=True,
        organization=password.organization,
    ).order_by('priority', 'pk')
    applicable = [r for r in rules if r.matches_target(password, user)]
    if not applicable:
        return {
            'allowed': True,
            'reason': '(no rules apply)',
            'matched_rule_id': None,
        }

    ip = _client_ip(request)
    country = _country_for_ip(ip)
    now_utc = timezone.now()

    # Pass 1: any DENY rule whose conditions match -> deny immediately
    for rule in applicable:
        if rule.effect == 'deny':
            if _check_rule_conditions(rule, ip, country, now_utc):
                return {
                    'allowed': False,
                    'reason': (
                        f'Denied by rule "{rule.name}" '
                        f'(IP {ip}, country {country or "?"})'
                    ),
                    'matched_rule_id': rule.id,
                    'ip': ip,
                    'country': country,
                }

    # Pass 2: first ALLOW rule whose conditions match -> allow
    for rule in applicable:
        if rule.effect == 'allow':
            if _check_rule_conditions(rule, ip, country, now_utc):
                return {
                    'allowed': True,
                    'reason': f'Allowed by rule "{rule.name}"',
                    'matched_rule_id': rule.id,
                    'ip': ip,
                    'country': country,
                }

    # Applicable rules exist but none of the ALLOW rules conditions matched
    # -> conservative deny ("explicit allow required")
    return {
        'allowed': False,
        'reason': f'No matching ALLOW rule (IP {ip}, country {country or "?"})',
        'matched_rule_id': None,
        'ip': ip,
        'country': country,
    }
