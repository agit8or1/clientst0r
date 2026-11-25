"""Optional application switcher (roadmap 113.10; docs/ux/CROSS_APP_UX_CONTRACT.md §3).

Lists the other applications the signed-in user may open from here:

* Agit8or Connect connections that are ``active`` (so not Security Blocked,
  Suspended or Revoked), with ``AGIT8OR_CONNECT_ENABLED`` on and the kill
  switch off; the user needs ``view_app_connections`` (MSP staff only).
* Active RMM connections whose console address passes the same check the
  device console links use (``validated_console_url`` against the provider's
  ``console_hosts``); the user needs ``integrations_view`` and, for a
  customer's own connection, reach to that customer.

Nothing here talks to another application. Facts come from stored rows
(state, last health check, last sync) and are kept per process for
``CACHE_SECONDS``, dropped early when one of those rows is saved here. The
status shown is derived at render time from the stored time of the last
result, so an old result is never shown as Connected.

The link is always the origin approved at pairing / stored on the
connection, rebuilt on the server: never a value from the request, no
query string, no credential. A customer-context deep link needs a path
template advertised by the other application (proposal CX-1); nothing
advertises or stores one today, so ``customer_link()`` returns '' and the
entry links to the application's home page. See
docs/plans/coordination/clientst0r-response-2026-11-25.md.
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Optional
from urllib.parse import quote, urlsplit

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger('core')

CACHE_KEY = 'core.app_switcher.facts.v1'
CACHE_SECONDS = 30

# A Connect health result older than this is not shown as Connected (the
# monitor runs every monitor_interval_s, default 60 s).
CONNECT_STALE_FLOOR = timedelta(minutes=10)
# An RMM sync result older than this many sync intervals (plus slack) is stale.
RMM_STALE_INTERVALS = 2
RMM_STALE_SLACK = timedelta(minutes=15)

# Shared vocabulary (contract §2, §7.2). Labels only; no protocol meaning.
CONNECTED, DEGRADED, OFFLINE, UNKNOWN, NOT_CHECKED = 'connected', 'degraded', 'offline', 'unknown', 'not_checked'
LABELS = {
    CONNECTED: 'Connected',
    DEGRADED: 'Degraded',
    OFFLINE: 'Offline',
    UNKNOWN: 'Status unknown',
    NOT_CHECKED: 'Not checked yet',
}
SEVERITY = {CONNECTED: 'success', DEGRADED: 'warning', OFFLINE: 'danger', UNKNOWN: 'secondary',
            NOT_CHECKED: 'secondary'}
# Icon map concepts (docs/ux/design-tokens.json icon.concepts) -> FA 6 class.
ICONS = {
    'app-switcher': 'fa-solid fa-grip',
    'integration': 'fa-solid fa-plug',
    'device': 'fa-solid fa-desktop',
    'action-confirm': 'fa-solid fa-check',
    'action-external': 'fa-solid fa-arrow-up-right-from-square',
    'status-success': 'fa-solid fa-circle-check',
    'status-warning': 'fa-solid fa-triangle-exclamation',
    'status-danger': 'fa-solid fa-circle-exclamation',
    'status-unknown': 'fa-solid fa-circle-question',
}
STATUS_ICON = {CONNECTED: ICONS['status-success'], DEGRADED: ICONS['status-warning'],
               OFFLINE: ICONS['status-danger'], UNKNOWN: ICONS['status-unknown'],
               NOT_CHECKED: ICONS['status-unknown']}

# Capability flag for customer-context deep links (proposals CX-1/CX-2).
# Off by default; even when on, a link is built only from a template the
# other application advertised and only for an active customer mapping.
CUSTOMER_LINKS_SETTING = 'APP_SWITCHER_CUSTOMER_LINKS'
_SAFE_VALUE = re.compile(r'^[A-Za-z0-9_.:-]{1,100}$')


# -- links -------------------------------------------------------------------

def safe_origin(url: str) -> str:
    """'https://host[:port]/' of a stored URL, or '' if it is not plain https
    with a host and no user info. Path, query and fragment are dropped."""
    if not url or not isinstance(url, str):
        return ''
    try:
        p = urlsplit(url.strip())
        port = p.port
    except ValueError:
        return ''
    if p.scheme.lower() != 'https' or not p.hostname or p.username or p.password:
        return ''
    host = p.hostname.lower()
    if ':' in host:  # IPv6 literal
        host = f'[{host}]'
    return f'https://{host}{":%d" % port if port and port != 443 else ""}/'


def _rmm_origin(conn) -> str:
    """The RMM console's home page, if it passes the console-link check."""
    from integrations.providers.rmm import RMM_PROVIDER_REGISTRY
    from integrations.providers.rmm.console import validated_console_url
    provider = RMM_PROVIDER_REGISTRY.get(conn.provider_type)
    if provider is None or getattr(provider, 'console_link_mode', 'none') == 'none':
        return ''
    try:
        hosts = provider.console_hosts(conn)
    except Exception:
        logger.exception('console_hosts failed for RMM connection %s', conn.pk)
        return ''
    origin = safe_origin(conn.console_base_url or conn.base_url)
    return validated_console_url(origin, hosts) if origin else ''


def advertised_ui_links(entry: dict) -> dict:
    """Deep-link path templates the other application advertised (CX-1).

    No protocol field carries them yet and nothing stores them, so this is
    always empty: the switcher links to the application's home page. It is
    the single place to read them once the proposal is agreed."""
    return {}


def customer_link(entry: dict, organization) -> str:
    """A link that opens `organization` in the other application, or ''.

    Requires the capability flag, an advertised ``customer`` template with a
    ``{tenant}`` placeholder, a same-origin absolute path and an active
    customer mapping on this connection. Off today (see module docstring)."""
    if not getattr(settings, CUSTOMER_LINKS_SETTING, False) or organization is None:
        return ''
    template = (advertised_ui_links(entry) or {}).get('customer') or ''
    if not isinstance(template, str) or not template.startswith('/') or template.startswith('//') \
            or '{tenant}' not in template or '?' in template or '#' in template or '\\' in template:
        return ''
    tenant = (entry.get('tenants') or {}).get(organization.pk)
    if not tenant or not _SAFE_VALUE.match(tenant):
        return ''
    url = entry['origin'].rstrip('/') + template.replace('{tenant}', quote(tenant, safe=''))
    return url if safe_origin(url) == entry['origin'] and len(url) <= 2000 else ''


# -- stored facts (no network) -----------------------------------------------

def _connect_facts() -> list:
    if not getattr(settings, 'AGIT8OR_CONNECT_ENABLED', False):
        return []
    from connect.models import Connection, InstallationIdentity, TenantGrant
    if InstallationIdentity.objects.filter(kill_switch_engaged=True).exists():
        return []
    conns = list(Connection.objects.filter(state=Connection.ACTIVE).only(
        'id', 'remote_app_type', 'remote_display_name', 'base_url', 'health', 'last_check_at',
        'monitor_interval_s', 'state'))
    if not conns:
        return []
    tenants = {}
    for cid, org_id, remote in TenantGrant.objects.filter(
            connection__in=conns, active=True).values_list('connection_id', 'organization_id', 'remote_tenant_id'):
        tenants.setdefault(cid, {})[org_id] = remote
    out = []
    for c in conns:
        origin = safe_origin(c.base_url)
        if not origin:
            continue
        out.append({
            'key': f'connect:{c.pk}', 'source': 'connect', 'id': str(c.pk),
            'name': c.remote_display_name or (c.remote_app_type or 'Application').title(),
            'icon': ICONS['integration'], 'origin': origin,
            'health': c.health or '', 'checked_at': c.last_check_at,
            'interval_s': c.monitor_interval_s or 60,
            'tenants': tenants.get(c.pk, {}), 'owner_org_id': None,
        })
    return out


def _rmm_facts() -> list:
    from django.contrib.contenttypes.models import ContentType
    from integrations.health import SUBSYSTEM_KINDS
    from integrations.models import IntegrationSyncHealth, RMMConnection, RMMDevice
    conns = [c for c in RMMConnection.objects.filter(is_active=True).order_by('name')]
    if not conns:
        return []
    usable = [(c, _rmm_origin(c)) for c in conns]
    usable = [(c, o) for c, o in usable if o]
    if not usable:
        return []
    ids = [c.pk for c, _ in usable]
    rows = {}
    ct = ContentType.objects.get_for_model(RMMConnection)
    for r in (IntegrationSyncHealth.objects.filter(content_type=ct, object_id__in=ids)
              .exclude(kind__in=SUBSYSTEM_KINDS).order_by('updated_at')
              .only('object_id', 'status', 'last_attempt_at', 'last_success_at')):
        rows[r.object_id] = r  # newest wins
    # Customers a platform-owned connection maps: those its devices were
    # settled under (rmm_association never files a device without one).
    mapped = {}
    for cid, org_id in (RMMDevice.objects.filter(connection_id__in=ids, organization__isnull=False)
                        .values_list('connection_id', 'organization_id').distinct()):
        mapped.setdefault(cid, set()).add(org_id)
    out = []
    for c, origin in usable:
        r = rows.get(c.pk)
        if r is not None:
            status, attempt, success = r.status, r.last_attempt_at, r.last_success_at
        else:
            legacy = (c.last_sync_status or '').strip().lower()
            attempt = c.last_sync_at
            if legacy in ('partial', 'degraded'):
                status = 'partial'
            elif legacy in ('error', 'failed', 'failure') or (c.last_error and legacy not in
                                                             ('ok', 'success', 'completed', 'complete')):
                status = 'error'
            elif attempt:
                status = 'success'
            else:
                status = 'never'
            success = attempt if status in ('success', 'partial') else None
        org_ids = {c.organization_id} if c.organization_id else mapped.get(c.pk, set())
        out.append({
            'key': f'rmm:{c.pk}', 'source': 'rmm', 'id': c.pk,
            'name': c.name or c.get_provider_type_display(),
            'provider': c.get_provider_type_display(),
            'icon': ICONS['device'], 'origin': origin,
            'sync_status': status, 'attempt_at': attempt, 'success_at': success,
            'interval_s': max(int(c.sync_interval_minutes or 60), 1) * 60,
            'owner_org_id': c.organization_id, 'mapped_org_ids': org_ids, 'tenants': {},
        })
    return out


def facts() -> list:
    """Install-wide switcher candidates from stored rows, cached per process."""
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached
    try:
        data = _connect_facts() + _rmm_facts()
    except Exception:  # the switcher never breaks a page
        logger.exception('Building application switcher entries failed')
        data = []
    cache.set(CACHE_KEY, data, CACHE_SECONDS)
    return data


def invalidate(*_args, **_kwargs):
    cache.delete(CACHE_KEY)


def connect_signals():
    from django.db.models.signals import post_delete, post_save
    from connect.models import Connection, InstallationIdentity, TenantGrant
    from integrations.models import RMMConnection
    for model in (Connection, TenantGrant, InstallationIdentity, RMMConnection):
        for sig in (post_save, post_delete):
            sig.connect(invalidate, sender=model, dispatch_uid=f'core.app_switcher.{model.__name__}.{sig}')


# -- per user, per render ----------------------------------------------------

def _connect_status(f, now):
    checked = f['checked_at']
    if checked is None:
        return NOT_CHECKED, None
    if f['health'] == 'offline':
        return OFFLINE, checked
    stale_after = max(CONNECT_STALE_FLOOR, timedelta(seconds=3 * f['interval_s']))
    if now - checked > stale_after:
        return UNKNOWN, checked
    return (DEGRADED if f['health'] == 'degraded' else CONNECTED), checked


def _rmm_status(f, now):
    status = f['sync_status']
    if status == 'never' or f['attempt_at'] is None:
        return NOT_CHECKED, None
    if status == 'error':
        return OFFLINE, f['attempt_at']
    stale_after = timedelta(seconds=RMM_STALE_INTERVALS * f['interval_s']) + RMM_STALE_SLACK
    at = f['success_at'] or f['attempt_at']
    if now - at > stale_after:
        return UNKNOWN, at
    return (DEGRADED if status == 'partial' else CONNECTED), at


def _may_open(user, f) -> bool:
    from accounts.permission_utils import client_org_ids_for_perm, user_has_perm
    if f['source'] == 'connect':
        return user_has_perm(user, 'view_app_connections')
    if not user_has_perm(user, 'integrations_view'):
        return False
    if f['owner_org_id'] is None:
        return True
    scope = client_org_ids_for_perm(user, 'integrations_view')
    return scope is None or f['owner_org_id'] in scope


def _unmapped_reason(f, organization) -> str:
    if f['source'] == 'connect':
        mapped = organization.pk in f['tenants']
    else:
        mapped = organization.pk in f['mapped_org_ids']
    if mapped:
        return ''
    return (f'{organization.name} is not mapped on the {f["name"]} connection. An administrator can add it '
            f'under Settings → Integrations → {f["name"]}.')


def entries_for(user, organization=None, now=None) -> list:
    """Switcher entries the user may open, in display order; [] hides it."""
    from psa.visibility import is_msp_staff
    if user is None or not getattr(user, 'is_authenticated', False) or not is_msp_staff(user):
        return []
    candidates = facts()
    if not candidates:
        return []
    now = now or timezone.now()
    out = []
    for f in candidates:
        try:
            if not _may_open(user, f):
                continue
        except Exception:
            logger.exception('Application switcher permission check failed')
            continue
        key, at = (_connect_status if f['source'] == 'connect' else _rmm_status)(f, now)
        reason = _unmapped_reason(f, organization) if organization is not None else ''
        href = '' if reason else (customer_link(f, organization) or f['origin'])
        out.append({
            'key': f['key'], 'name': f['name'], 'icon': f['icon'],
            'kind': 'Connected application' if f['source'] == 'connect' else f'RMM · {f["provider"]}',
            'href': href, 'disabled_reason': reason,
            'customer_context': bool(href and href != f['origin']),
            'status': key, 'status_label': LABELS[key], 'status_severity': SEVERITY[key],
            'status_icon': STATUS_ICON[key], 'status_at': at,
            'status_verb': 'last successful sync' if f['source'] == 'rmm' and key in (CONNECTED, DEGRADED)
            else ('last sync attempt' if f['source'] == 'rmm' else 'last checked'),
        })
    return out


def switcher_context(user, organization=None) -> Optional[dict]:
    entries = entries_for(user, organization)
    if not entries:
        return None
    return {'entries': entries, 'icon': ICONS['app-switcher'], 'confirm_icon': ICONS['action-confirm'],
            'external_icon': ICONS['action-external']}
