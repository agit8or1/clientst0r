"""
Ticket integration pairing (docs/contracts/ticket-rmm-v1), for any RMM.

Any RMM connection can be paired as a ticket-rmm-v1 processor, whatever
its provider type: the RMM only has to implement the contract. rem0te is
the reference implementation. An RMM that doesn't implement it never
becomes a processor — its capabilities check fails and the connection page
says why.

Where the pairing lives:

  encrypted credentials   integration_outbound_secret  ClientSt0r signs with it
                          integration_inbound_secret   the RMM signs with it
  field_mappings          ticket_rmm_enabled           approved and switched on
                          ticket_rmm_key_id            quoted by both sides
                          ticket_rmm_location          'hosted' | 'local'
                          ticket_rmm_url               contract address; blank =
                                                       the connection's address
                          ticket_rmm_tenant_id         the pinned remote tenant
                          ticket_rmm_capabilities      the last capabilities check

(Before v3.17.657 the field_mappings keys were rem0te_integration_enabled,
rem0te_integration_key_id, rem0te_processing_location and
rem0te_capabilities, and the pin was rem0te's inventory pin
rem0te_business_id. Migration integrations 0034 moved them.)

One pairing = one remote tenant = one ClientSt0r customer. The tenant is
pinned from the first successful, signed capabilities response (its
`tenant.id`); a later response naming a different tenant stops the pairing
instead of re-pinning. For rem0te, the tenant must also agree with the
business its inventory API key answers for, and rem0te's inventory pin
fills the tenant pin when the capabilities response predates `tenant`.

Turning the pairing on, or marking it on-premises, is a protected change a
second administrator approves (tech_access.services.propose_pairing).
Changing a secret, the key ID, the address or the provider of a live
pairing switches it off until it is approved again. Same rules for every
provider.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List

ENABLED = 'ticket_rmm_enabled'
KEY_ID = 'ticket_rmm_key_id'
LOCATION = 'ticket_rmm_location'
URL = 'ticket_rmm_url'
TENANT_PIN = 'ticket_rmm_tenant_id'
CAPS = 'ticket_rmm_capabilities'
OUTBOUND, INBOUND = 'integration_outbound_secret', 'integration_inbound_secret'

# Pre-3.17.657 field_mappings keys → current ones (migration 0034).
LEGACY_KEYS = {
    'rem0te_integration_enabled': ENABLED,
    'rem0te_integration_key_id': KEY_ID,
    'rem0te_processing_location': LOCATION,
    'rem0te_capabilities': CAPS,
}
REM0TE_BUSINESS_PIN = 'rem0te_business_id'

CONTRACT = 'ticket-rmm-v1'
LOCATIONS = (('hosted', 'Hosted / off-premises'), ('local', 'On-premises'))

# Capabilities a processor may advertise (anything else is ignored).
KNOWN_CAPABILITIES = {
    'analysis.jobs', 'rmm_handoff', 'diagnostics_readonly', 'diagnostics_advanced', 'remote_view',
    'remote_control', 'elevation', 'unattended_access', 'clipboard', 'file_transfer', 'fix_request_low',
    'fix_request_high', 'signed_actions',
}
TENANT_RE = re.compile(r'^[A-Za-z0-9_.:-]{1,100}$')
DIAG_KEY_RE = re.compile(r'^[a-z0-9][a-z0-9_.-]{0,63}$')
MAX_DIAGNOSTICS = 50


def _now():
    return datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'


def contract_site(connection) -> str:
    """Where the RMM's ticket-rmm-v1 routes live: the configured integration
    address, else the connection's own address (for rem0te, without its
    inventory API path)."""
    mappings = connection.field_mappings or {}
    url = str(mappings.get(URL) or '').strip()
    if not url:
        url = connection.base_url or ''
        if connection.provider_type == 'rem0te':
            from integrations.providers.rmm.rem0te import site_root
            return site_root(url)
    return url.strip().rstrip('/')


def single_customer(connection) -> bool:
    """One pairing serves one customer. A rem0te key belongs to one business
    by design; any other RMM must be a single-customer connection."""
    return connection.provider_type == 'rem0te' or connection.is_single_customer


def secrets(connection) -> Dict[str, str]:
    creds = connection.get_credentials() or {}
    return {'outbound': creds.get(OUTBOUND) or '', 'inbound': creds.get(INBOUND) or ''}


def settings(connection) -> Dict[str, Any]:
    """The pairing as configured. `enabled` means approved, switched on and
    complete; whether the RMM has answered yet is `is_processor()`."""
    mappings = connection.field_mappings or {}
    sec = secrets(connection)
    has_secrets = bool(sec['outbound'] and sec['inbound'])
    key_id = str(mappings.get(KEY_ID) or '')
    return {
        'enabled': (bool(mappings.get(ENABLED)) and has_secrets and bool(key_id) and connection.is_active
                    and single_customer(connection)),
        'requested': bool(mappings.get(ENABLED)),
        'has_secrets': has_secrets,
        'key_id': key_id,
        'location': 'local' if mappings.get(LOCATION) == 'local' else 'hosted',
        'site': contract_site(connection),
        'url': str(mappings.get(URL) or ''),
        'tenant_id': str(mappings.get(TENANT_PIN) or ''),
    }


def check(connection) -> Dict[str, Any]:
    doc = (connection.field_mappings or {}).get(CAPS) or {}
    return doc if isinstance(doc, dict) else {}


def is_processor(connection) -> bool:
    """Enabled, tenant pinned, and the RMM hasn't since named another tenant."""
    s = settings(connection)
    return bool(s['enabled'] and s['tenant_id'] and not check(connection).get('tenant_mismatch'))


def advertised(connection) -> set:
    """What the RMM said it supports at its last successful check. Empty
    until the pairing is a live processor."""
    if not is_processor(connection):
        return set()
    caps = check(connection).get('capabilities')
    return {c for c in (caps or []) if isinstance(c, str)}


def diagnostics(connection) -> List[Dict[str, Any]]:
    """The read-only diagnostics the RMM advertised, already cleaned."""
    if 'diagnostics_readonly' not in advertised(connection):
        return []
    return list(check(connection).get('diagnostics') or [])


def paired_connections(organization):
    from integrations.models import RMMConnection
    return [c for c in RMMConnection.objects.filter(organization=organization, is_active=True).order_by('pk')
            if is_processor(c)]


def processor_for(organization):
    """The customer's first live ticket-rmm-v1 pairing, or None."""
    conns = paired_connections(organization)
    return conns[0] if conns else None


def find_by_key_id(key_id):
    """The enabled pairing quoting this key ID, any provider, or None."""
    from integrations.models import RMMConnection
    if not key_id:
        return None
    for conn in RMMConnection.objects.filter(is_active=True):
        if str((conn.field_mappings or {}).get(KEY_ID) or '') == key_id:
            return conn if settings(conn)['enabled'] else None
    return None


def launch_hosts(connection) -> set:
    """Hosts a remote-launch URL from this RMM may point at: the provider's
    console hosts (providers/rmm/console.py) and the contract address."""
    from integrations.providers.rmm import RMM_PROVIDER_REGISTRY
    from integrations.providers.rmm.console import host_of
    hosts = set()
    provider = RMM_PROVIDER_REGISTRY.get(connection.provider_type)
    if provider is not None:
        try:
            hosts |= set(provider.console_hosts(connection))
        except Exception:
            pass
    site_host = host_of(contract_site(connection))
    if site_host:
        hosts.add(site_host)
    return {h for h in hosts if h}


def _clean_diagnostics(raw) -> List[Dict[str, Any]]:
    out, seen = [], set()
    for d in (raw or [])[:MAX_DIAGNOSTICS * 2]:
        if not isinstance(d, dict):
            continue
        key = str(d.get('key') or '')
        if not DIAG_KEY_RE.match(key) or key in seen:
            continue
        seen.add(key)
        classes = [str(c)[:30] for c in (d.get('device_classes') or []) if isinstance(c, str)][:10]
        out.append({'key': key, 'label': str(d.get('label') or key)[:100],
                    'description': str(d.get('description') or '')[:300], 'device_classes': classes})
        if len(out) >= MAX_DIAGNOSTICS:
            break
    return out


def _save(connection, mappings):
    from integrations.models import RMMConnection
    connection.field_mappings = mappings
    RMMConnection.objects.filter(pk=connection.pk).update(field_mappings=mappings)


def record_failure(connection, error: str):
    """A capabilities check that didn't succeed. A pairing that was never
    checked stays un-paired; one that was keeps its last good capabilities
    (an outage doesn't revoke them), with the error shown beside them."""
    mappings = dict(connection.field_mappings or {})
    doc = dict(check(connection))
    doc.update({'ok': False, 'error': str(error)[:300], 'checked_at': _now()})
    mappings[CAPS] = doc
    _save(connection, mappings)


def record_capabilities(connection, document: Dict[str, Any]) -> Dict[str, Any]:
    """Store a signed capabilities response and pin the tenant. Returns the
    stored check. A response for a different tenant than the pin (or, for
    rem0te, than the business its inventory key answers for) is recorded as
    a mismatch: the pairing stops being a processor and nothing is re-pinned."""
    document = document if isinstance(document, dict) else {}
    mappings = dict(connection.field_mappings or {})
    tenant = document.get('tenant')
    tenant_id = str((tenant or {}).get('id') or '') if isinstance(tenant, dict) else ''
    tenant_name = str((tenant or {}).get('name') or '')[:200] if isinstance(tenant, dict) else ''
    pinned = str(mappings.get(TENANT_PIN) or '')
    inventory_pin = str(mappings.get(REM0TE_BUSINESS_PIN) or '') if connection.provider_type == 'rem0te' else ''
    caps = sorted({c for c in (document.get('capabilities') or []) if isinstance(c, str)} & KNOWN_CAPABILITIES)
    doc = {'ok': True, 'error': '', 'checked_at': _now(), 'fetched_at': _now(),
           'contract': str(document.get('contract') or '')[:40], 'capabilities': caps,
           'diagnostics': _clean_diagnostics(document.get('diagnostics')) if 'diagnostics_readonly' in caps else [],
           'tenant_id': tenant_id, 'tenant_name': tenant_name, 'tenant_mismatch': False}
    if tenant_id and not TENANT_RE.match(tenant_id):
        doc.update(ok=False, error='The RMM named its tenant with characters the contract does not allow.',
                   capabilities=[], diagnostics=[])
    elif tenant_id:
        expected = pinned or inventory_pin
        if expected and expected != tenant_id:
            doc.update(ok=False, tenant_mismatch=True, capabilities=[], diagnostics=[],
                       error='The RMM now answers for a different tenant than the one this pairing is '
                             'pinned to. The pairing is stopped; pair a separate connection for that tenant.')
        elif not pinned:
            mappings[TENANT_PIN] = tenant_id
    elif not pinned and inventory_pin:
        # rem0te before the `tenant` field: its inventory pin is the tenant.
        mappings[TENANT_PIN] = inventory_pin
    elif not pinned:
        doc.update(ok=False, capabilities=[], diagnostics=[],
                   error='The RMM did not say which tenant this pairing answers for (capabilities '
                         '"tenant.id"), so it cannot be paired.')
    mappings[CAPS] = doc
    _save(connection, mappings)
    return doc


def status(connection) -> Dict[str, Any]:
    """Plain-words pairing state for the connection page."""
    s = settings(connection)
    doc = check(connection)
    pending = False
    if connection.pk:
        from tech_access.models import ProtectedChange
        pending = any(c.payload.get('connection') == connection.pk for c in ProtectedChange.objects.filter(
            kind='business_mapping', status=ProtectedChange.PENDING))
    if not s['requested'] and not pending:
        state, label = 'off', 'Not paired'
        detail = 'Ticket integration pairing is off for this connection.'
    elif not s['enabled']:
        state, label = 'pending', 'Waiting for approval' if pending else 'Incomplete'
        detail = ('A second administrator has to approve this pairing (Settings → Security → Technician '
                  'Access).' if pending else
                  'The pairing is missing its key ID or secrets, the connection is inactive, or it is not '
                  'a single-customer connection.')
    elif doc.get('tenant_mismatch'):
        state, label, detail = 'error', 'Stopped — tenant changed', doc.get('error', '')
    elif not s['tenant_id']:
        state, label = 'error' if doc.get('error') else 'checking', 'Not paired yet'
        detail = (f'The capabilities check failed: {doc["error"]}' if doc.get('error') else
                  'Approved. Waiting for the first successful capabilities check (Check pairing below).')
    elif doc.get('error'):
        state, label = 'warning', 'Paired — last check failed'
        detail = f'The last capabilities check failed: {doc["error"]} The capabilities below are from the ' \
                 f'last successful check.'
    else:
        state, label, detail = 'ok', 'Paired', 'This RMM processes ticket-rmm-v1 requests for this customer.'
    return {'state': state, 'label': label, 'detail': detail, 'pending_approval': pending, 'settings': s,
            'capabilities': sorted(advertised(connection)), 'diagnostics': diagnostics(connection),
            'checked_at': doc.get('checked_at', ''), 'tenant_name': doc.get('tenant_name', '')}
