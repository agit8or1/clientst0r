"""What a proposed change would do, before it is saved, and how the client
address of a request was read."""
import ipaddress
from datetime import timedelta

from django.conf import settings as dj_settings
from django.utils import timezone

from . import policy as P
from .groups import Route
from .models import ApiAccessRule, ApiAccessSettings

RECENT_KEY_DAYS = 90


def settings_row(**override):
    s = ApiAccessSettings.get()
    row = {'policy_version': s.policy_version, 'api_mode': s.api_mode,
           'webhook_mode': s.webhook_mode}
    row.update(override)
    return row


def rule_rows(exclude_id=None, extra=None):
    qs = ApiAccessRule.objects.filter(is_active=True)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    rows = list(qs.values(*P._RULE_FIELDS))
    if extra is not None:
        rows.append(extra)
    return rows


def row_for(rule):
    """A compiled-rule row from an unsaved ApiAccessRule (or None if inactive)."""
    if not rule.is_active:
        return None
    return {'id': rule.pk or 0, 'name': rule.name, 'action': rule.action,
            'surface': rule.surface, 'scope': rule.scope,
            'organization_id': rule.organization_id if rule.scope == rule.SCOPE_CUSTOMER else None,
            'api_key_id': rule.api_key_id if rule.scope == rule.SCOPE_API_KEY else None,
            'target': rule.target if rule.scope in (rule.SCOPE_INTEGRATION, rule.SCOPE_ENDPOINT_GROUP) else '',
            'network': rule.network, 'expires_at': rule.expires_at}


def build_policy_for_rule(rule, exclude_id=None):
    """The policy as it would be with ``rule`` saved (replacing ``exclude_id``)."""
    return P.build_policy(settings_row(), rule_rows(exclude_id=exclude_id, extra=row_for(rule)))


def impact(proposed, viewer_ip_text):
    """Compare the live policy with ``proposed`` (a Policy).

    Returns {'viewer': {...}, 'keys': [...], 'webhook_restrictive': bool, 'high_impact': bool}.
    Keys are judged by the address they were last used from; that is the only
    record of where API traffic comes from today."""
    from api.models import APIKey
    current = P.build_policy(settings_row(), rule_rows())
    route = Route('rest_api', '')
    viewer_ip = P.parse_ip(viewer_ip_text)

    def judge(policy, ctx):
        return P.evaluate(policy, ctx)

    viewer_ctx = P.Context(ip=viewer_ip, surface=route.surface, group=route.group)
    viewer_now = judge(current, viewer_ctx)
    viewer_after = judge(proposed, viewer_ctx)

    since = timezone.now() - timedelta(days=RECENT_KEY_DAYS)
    newly_refused = []
    keys = (APIKey.objects.filter(is_active=True, last_used_at__gte=since)
            .exclude(last_used_ip__isnull=True).select_related('organization'))
    for key in keys[:500]:
        ctx = P.Context(ip=P.parse_ip(key.last_used_ip), surface=route.surface,
                        group=route.group, organization_id=key.organization_id, api_key_id=key.pk)
        if judge(current, ctx).allowed and not judge(proposed, ctx).allowed:
            newly_refused.append({'name': key.name, 'prefix': key.key_prefix,
                                  'organization': str(key.organization), 'ip': key.last_used_ip,
                                  'last_used_at': key.last_used_at})
    webhook_restrictive = (
        proposed.webhook_mode != ApiAccessSettings.MODE_UNRESTRICTED
        and proposed.webhook_mode != current.webhook_mode)
    viewer_cut = viewer_now.allowed and not viewer_after.allowed
    return {
        'viewer': {'ip': viewer_ip_text, 'now': viewer_now.allowed, 'after': viewer_after.allowed,
                   'reason': P.REASONS.get(viewer_after.reason, '')},
        'keys': newly_refused,
        'webhook_restrictive': webhook_restrictive,
        'high_impact': bool(newly_refused) or viewer_cut or webhook_restrictive or (
            proposed.api_mode != current.api_mode
            and proposed.api_mode in (ApiAccessSettings.MODE_ALLOWLIST, ApiAccessSettings.MODE_COMBINED)),
    }


def explain_client_address(request):
    """How core.client_ip read this request's address, hop by hop."""
    from core import client_ip as C
    networks = C._trusted_networks()
    peer = request.META.get('REMOTE_ADDR', '')
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    real_ip = request.META.get('HTTP_X_REAL_IP', '')
    peer_trusted = C.is_trusted_peer(request)
    hops = []
    if forwarded and peer_trusted:
        for part in reversed([p.strip() for p in forwarded.split(',')]):
            try:
                addr = ipaddress.ip_address(part)
            except ValueError:
                hops.append({'address': part, 'note': 'not an address — the whole header is refused'})
                break
            trusted = C._is_trusted(addr, networks)
            hops.append({'address': part, 'trusted': trusted,
                         'note': 'trusted proxy — keep walking' if trusted else 'first untrusted hop — the client'})
            if not trusted:
                break
    return {
        'resolved': C.get_client_ip(request) or '(unreadable — refused when restrictions apply)',
        'peer': peer or '(unix socket — local nginx)',
        'peer_trusted': peer_trusted,
        'forwarded': forwarded,
        'forwarded_used': bool(forwarded) and peer_trusted,
        'real_ip': real_ip,
        'trusted_proxies': [str(n) for n in networks],
        'trusted_source': 'TRUSTED_PROXY_CIDRS' if getattr(dj_settings, 'TRUSTED_PROXY_CIDRS', None) else 'default',
        'hops': hops,
    }
