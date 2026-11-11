"""
A Rem0te connection's integration health and its one status.

Every Rem0te connection is in exactly one of five states, derived from real
checks (the signed capabilities check, the organization/business binding
Rem0te reports, inbound signature results and the reconciliation job's
outcome), never from configuration alone:

  connected        Rem0te answered the last check, ClientSt0r is paired for
                   this organization and nothing is failing.
  degraded         paired, but something works only partly: a containment
                   pause in Rem0te, an alert gap or failing ticket link, a
                   refused event, a stale check, a clock drifting towards the
                   limit, a capability Rem0te does not offer.
  disconnected     Rem0te cannot be reached (network, timeout, 5xx).
  auth_problem     a signature or key was refused, in either direction, or
                   the clocks are outside the ±120 s window.
  config_required  something has to be set up first, on either side: keys,
                   identity, approval, the peers file, the organization
                   mapping, a business binding that disagrees.

Operational failures are kept as issues on the connection's
IntegrationSyncHealth row with kind 'rem0te' (integrations.health; the
device-inventory sync of the same connection keeps its own 'rmm' row). One
issue per area, replaced by the next failure in that area and cleared by the
next success there, so nothing fails silently and nothing stays red after it
healed. Everything stored goes through integrations.health.redact().
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Dict, List, Optional

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger('integrations.rem0te')

KIND = 'rem0te'

CONNECTED = 'connected'
DEGRADED = 'degraded'
DISCONNECTED = 'disconnected'
AUTH = 'auth_problem'
CONFIG = 'config_required'

LABELS = {
    CONNECTED: 'Connected',
    DEGRADED: 'Degraded',
    DISCONNECTED: 'Disconnected',
    AUTH: 'Authentication Problem',
    CONFIG: 'Configuration Required',
}
BADGES = {CONNECTED: 'success', DEGRADED: 'warning', DISCONNECTED: 'danger', AUTH: 'danger', CONFIG: 'secondary'}
# The worst state wins when several reasons apply.
SEVERITY = {CONNECTED: 0, DEGRADED: 1, DISCONNECTED: 2, AUTH: 3, CONFIG: 4}

# Check-pairing failure codes (pairing.check) → state.
AUTH_CODES = {'KEY_UNKNOWN', 'CLOCK_SKEW', 'SIGNATURE_REJECTED', 'HEADERS_REJECTED', 'REPLAYED', 'CLIENT_CERT',
              'SIGNING_KEY_MISMATCH', 'DELEGATION_INVALID', 'UNAUTHENTICATED'}
NETWORK_CODES = {'UNREACHABLE', 'BLOCKED', 'HTTP_ERROR'}
DEGRADED_CODES = {'RATE_LIMITED'}
# Everything else (NOT_CONFIGURED_LOCAL, NOT_CONFIGURED, CONTRACT_MISMATCH,
# VERSION_INCOMPATIBLE, PEER_MISMATCH, BUSINESS_MISMATCH, INVALID_RESPONSE, …)
# needs a setting changed somewhere: config_required.

# Issue areas and the state an open issue there implies.
AREAS = {
    'inbound_auth': AUTH,        # a request signed with Rem0te's key id that did not verify
    'events': DEGRADED,          # a verified event ClientSt0r could not apply / understand
    'alerts_poll': DEGRADED,     # GET /alerts/events failed
    'alerts_gap': DEGRADED,      # events Rem0te sequenced that ClientSt0r still lacks
    'ticket_link': DEGRADED,     # POST /alerts/{id}/ticket keeps failing
    'jobs': DEGRADED,            # analysis jobs refused or retrying
    'actions': DEGRADED,         # action proposals refused or unreadable
    'technician': DEGRADED,      # a technician mapping Rem0te refused
}
MAX_ISSUES = 20
CHECK_STALE_AFTER = timedelta(hours=3)


def _content_type(connection):
    from django.contrib.contenttypes.models import ContentType
    return ContentType.objects.get_for_model(type(connection))


def row(connection):
    """This connection's Rem0te health row, or None."""
    from integrations.models import IntegrationSyncHealth
    if connection is None or not getattr(connection, 'pk', None):
        return None
    try:
        return IntegrationSyncHealth.objects.filter(content_type=_content_type(connection), object_id=connection.pk,
                                                    kind=KIND).first()
    except Exception:
        return None


def issues(connection) -> List[dict]:
    r = row(connection)
    return list(r.issues or []) if r else []


def _clean(connection, text) -> str:
    from integrations.health import redact_for
    return redact_for(connection, text or '')


def _mutate(connection, fn, *, attempt=False, success=None):
    """Read-modify-write the row under a lock. Never raises."""
    from integrations.models import IntegrationSyncHealth
    if connection is None or not getattr(connection, 'pk', None):
        return None
    try:
        with transaction.atomic():
            ct = _content_type(connection)
            r, _ = IntegrationSyncHealth.objects.select_for_update().get_or_create(
                content_type=ct, object_id=connection.pk, kind=KIND,
                defaults={'organization_id': getattr(connection, 'organization_id', None)})
            current = [i for i in (r.issues or []) if isinstance(i, dict)]
            new = fn(current)
            changed = new is not None
            if changed:
                r.issues = new[:MAX_ISSUES]
            now = timezone.now()
            if attempt:
                r.last_attempt_at = now
                changed = True
            if success:
                r.last_success_at = now
                changed = True
            if changed:
                st = evaluate(connection, health_row=r)
                r.status = {CONNECTED: 'success', DEGRADED: 'partial'}.get(st['state'], 'error')
                r.error = _clean(connection, st['reasons'][0]['message'] if st['reasons'] else '')[:2000]
                r.corrective_action = _clean(connection, st['reasons'][0].get('action', '') if st['reasons']
                                             else '')[:1000]
                r.organization_id = getattr(connection, 'organization_id', None)
                r.save()
            return r
    except Exception:
        logger.exception('could not record Rem0te health for connection %s', getattr(connection, 'pk', None))
        return None


def note(connection, area: str, message: str, *, action: str = '', code: str = '', count: int = 1):
    """Record (or replace) the open issue for `area`. Also logged."""
    if area not in AREAS:
        raise ValueError(f'unknown Rem0te health area {area}')
    msg = _clean(connection, message)[:500]
    act = _clean(connection, action)[:500]
    # The same issue again within a minute is not written again: a flood of
    # (possibly unauthenticated) failures costs one row write per minute.
    current = row(connection)
    prev = next((i for i in (current.issues if current else None) or [] if i.get('area') == area), None)
    if prev and prev.get('message') == msg:
        at = parse_datetime(str(prev.get('at') or ''))
        if at is not None and timezone.now() - at < timedelta(seconds=60):
            return current
    logger.warning('Rem0te connection %s: %s: %s', getattr(connection, 'pk', None), area, msg)
    now = timezone.now().isoformat()

    def fn(current):
        prev = next((i for i in current if i.get('area') == area), None)
        rest = [i for i in current if i.get('area') != area]
        total = (prev.get('count', 1) if prev and prev.get('message') == msg else 0) + max(count, 1)
        first = prev.get('since') if prev else now
        return [{'area': area, 'code': str(code)[:64], 'message': msg, 'action': act, 'since': first, 'at': now,
                 'count': total, 'kind': AREAS[area]}] + rest
    return _mutate(connection, fn)


def clear(connection, area: str, code: Optional[str] = None):
    """The area works again: drop its issue (cheap no-op when there is none).
    With `code`, only an issue of that code (e.g. CONTAINED once Rem0te
    reports the pause lifted)."""
    r = row(connection)

    def match(i):
        return i.get('area') == area and (code is None or i.get('code') == code)
    if r is None or not any(match(i) for i in (r.issues or [])):
        return r

    def fn(current):
        return [i for i in current if not match(i)]
    return _mutate(connection, fn)


def touch(connection, *, success: bool):
    """Record that the reconciliation job (or a check) ran."""
    return _mutate(connection, lambda current: None, attempt=True, success=success)


# --- the status --------------------------------------------------------------

def _reason(state, message, action='', code=''):
    return {'state': state, 'message': message, 'action': action, 'code': code}


def _check_state(code: str) -> str:
    if code in AUTH_CODES:
        return AUTH
    if code in NETWORK_CODES:
        return DISCONNECTED
    if code in DEGRADED_CODES:
        return DEGRADED
    return CONFIG


ACTIONS = {
    'NOT_CONFIGURED_LOCAL': 'Complete the missing settings listed above, then press Test connection.',
    'NOT_CONFIGURED': "On the Rem0te server, add ClientSt0r's peers-file entry and restart the Rem0te API and worker.",
    'KEY_UNKNOWN': "Copy ClientSt0r's current peers-file entry into Rem0te's INTEGRATION_PEERS_FILE and restart Rem0te.",
    'SIGNATURE_REJECTED': "Compare Rem0te's audience and ClientSt0r's request key fingerprint with the peers file.",
    'SIGNING_KEY_MISMATCH': "Paste Rem0te's current public signing key (compare fingerprints) into this connection.",
    'CLOCK_SKEW': 'Fix the clock (NTP) on whichever server is wrong; requests fail beyond ±120 s.',
    'HEADERS_REJECTED': 'Update ClientSt0r; if it persists, report it with the Rem0te version.',
    'REPLAYED': 'Press Test connection again. If it repeats, two ClientSt0r instances share one identity.',
    'CLIENT_CERT': 'Remove clientCertSha256 from the peers entry, or terminate mTLS in front of ClientSt0r.',
    'UNREACHABLE': 'Check the Rem0te address, DNS, the firewall and that the Rem0te API is running.',
    'BLOCKED': 'Use an allowed address, or mark the connection on-premises if Rem0te runs on your LAN.',
    'HTTP_ERROR': "Check the Rem0te API's logs; ClientSt0r retries on its own.",
    'RATE_LIMITED': 'Nothing to do: ClientSt0r backs off and retries.',
    'CONTRACT_MISMATCH': 'Update Rem0te or ClientSt0r so both speak ticket-rmm-v1 (see the versions above).',
    'VERSION_INCOMPATIBLE': 'Update Rem0te.',
    'PEER_MISMATCH': "Make the peer id and audiences here match the peers file's entry.",
    'BUSINESS_MISMATCH': 'In Rem0te, map this organization to the business its inventory API key belongs to — '
                         'or use an inventory key for the mapped business.',
    'INVALID_RESPONSE': 'Check the Rem0te address: it must be the Rem0te site itself, not a proxy or login page.',
}


def evaluate(connection, health_row=None) -> Dict:
    """The connection's state, label and the reasons (worst first), each with
    what to do. Pure: reads the stored check and the health row only."""
    from integrations.rem0te import identity, pairing
    s = pairing.settings(connection)
    doc = pairing.last_check(connection)
    ident = identity.get(create=False)
    reasons: List[dict] = []
    pending = False
    if connection.pk and not s['requested']:
        try:
            from tech_access.models import ProtectedChange
            pending = any(c.payload.get('connection') == connection.pk for c in ProtectedChange.objects.filter(
                kind='business_mapping', status=ProtectedChange.PENDING))
        except Exception:
            pending = False
    if not connection.is_active:
        reasons.append(_reason(CONFIG, 'The connection is switched off.', 'Edit the connection and activate it.'))
    if s['needs_repair']:
        reasons.append(_reason(CONFIG, 'This pairing used shared secrets (HMAC); Rem0te accepts only Ed25519.',
                               'Pair again with Ed25519 (steps below).', 'NEEDS_REPAIR'))
    if not s['requested']:
        reasons.append(_reason(CONFIG, 'Waiting for a second administrator to approve the pairing.' if pending
                               else 'Ticket integration pairing is not switched on for this connection.',
                               'Settings → Security → Technician Access.' if pending else
                               'Edit the connection, switch on the ticket integration pairing and have a second '
                               'administrator approve it.', 'NOT_ENABLED'))
    elif s['incomplete']:
        reasons.append(_reason(CONFIG, s['incomplete'], 'Edit the connection.', 'NOT_CONFIGURED_LOCAL'))
    missing = identity.configured(ident)
    if missing:
        reasons.append(_reason(CONFIG, missing, "Settings → RMM → Rem0te: ClientSt0r's identity.",
                               'NOT_CONFIGURED_LOCAL'))
    if not reasons:
        if not doc:
            reasons.append(_reason(CONFIG, 'Not tested yet.', 'Press Test connection.', 'NOT_CHECKED'))
        elif doc.get('code'):
            code = doc['code']
            state = _check_state(code)
            reasons.append(_reason(state, doc.get('error') or code, ACTIONS.get(code, ''), code))
        if doc.get('compatible'):
            reasons.extend(_degradations(connection, doc))
    r = health_row if health_row is not None else row(connection)
    for i in (r.issues if r is not None else None) or []:
        if isinstance(i, dict) and i.get('area') in AREAS:
            reasons.append(_reason(AREAS[i['area']], i.get('message', ''), i.get('action', ''), i.get('code', '')))
    state = max((x['state'] for x in reasons), key=SEVERITY.get, default=CONNECTED)
    reasons.sort(key=lambda x: -SEVERITY[x['state']])
    return {'state': state, 'label': LABELS[state], 'badge': BADGES[state], 'reasons': reasons,
            'checked_at': doc.get('checked_at', ''), 'contract_revision': doc.get('contract_revision'),
            'last_attempt_at': getattr(r, 'last_attempt_at', None), 'last_success_at': getattr(r, 'last_success_at', None)}


def _degradations(connection, doc) -> List[dict]:
    from integrations.rem0te import pairing
    out = []
    org = doc.get('organization') or {}
    if doc.get('org_mapped') is False:
        out.append(_reason(CONFIG, f'Rem0te has no business mapped to organization "{pairing.organization_id(connection)}".',
                           'In Rem0te (Platform Admin, step-up): POST /api/v1/admin/integration/mappings/organizations '
                           f'for "{pairing.organization_id(connection)}".', 'ORG_NOT_MAPPED'))
    paused = [p for p in org.get('paused') or [] if isinstance(p, str)]
    if paused:
        what = {'integration': 'ticket analysis and alerts work', 'actions': 'action proposals',
                'remote': 'remote sessions', 'updates': 'update deployments'}
        out.append(_reason(DEGRADED, 'Rem0te has paused ' + ', '.join(what.get(p, p) for p in paused)
                           + ' for this business (containment). Rem0te refuses that work until it is lifted.',
                           'A Rem0te administrator lifts the pause once the review is done.', 'CONTAINED'))
    feats = doc.get('features') or {}
    if not feats.get('ticket_analysis'):
        out.append(_reason(DEGRADED, 'The connected Rem0te does not offer ticket analysis to this peer.', '',
                           'CAPABILITY'))
    if not feats.get('alerts'):
        out.append(_reason(DEGRADED, 'Alert events are not supported by the connected Rem0te.',
                           'Update Rem0te to 0.29 or later for alert tickets.', 'CAPABILITY'))
    skew = doc.get('clock_skew_s')
    if isinstance(skew, int) and abs(skew) > 60:
        out.append(_reason(DEGRADED, f"Rem0te's clock is {skew:+d} s from ClientSt0r's (requests fail beyond ±120 s).",
                           'Fix NTP on whichever server drifts.', 'CLOCK_DRIFT'))
    when = parse_datetime(str(doc.get('fetched_at') or '').replace('Z', '+00:00'))
    if when is not None and timezone.is_aware(when) and timezone.now() - when > CHECK_STALE_AFTER:
        out.append(_reason(DEGRADED, f'Not verified since {doc.get("fetched_at")}: the hourly check has not succeeded.',
                           'Check that the scheduler runs (task poll_analysis_jobs), then press Test connection.',
                           'STALE'))
    if doc.get('code') in NETWORK_CODES | DEGRADED_CODES:
        pass  # already the primary reason
    return out


def summary(connection) -> Optional[Dict]:
    """Status for lists and badges; None for a connection that is not Rem0te."""
    from integrations.rem0te import pairing
    if not pairing.is_rem0te(connection):
        return None
    try:
        return evaluate(connection)
    except Exception:
        logger.exception('evaluating Rem0te status for connection %s failed', connection.pk)
        return {'state': CONFIG, 'label': LABELS[CONFIG], 'badge': BADGES[CONFIG],
                'reasons': [_reason(CONFIG, 'The status could not be evaluated.', 'See the server log.')]}
