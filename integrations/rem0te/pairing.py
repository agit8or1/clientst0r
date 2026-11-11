"""
A Rem0te connection's ticket-rmm-v1 pairing, Ed25519 only.

Where it lives (the connection's field_mappings; nothing here is secret —
Rem0te's keys are public, ClientSt0r's private keys are in Rem0teIdentity):

  ticket_rmm_enabled        approved (protected change) and switched on
  ticket_rmm_url            Rem0te's site; blank = the connection's address
  ticket_rmm_location       'hosted' | 'local'
  ticket_rmm_auth           'ed25519' (always, for Rem0te)
  rem0te_audience           Rem0te's own audience (peers[].audience)
  rem0te_signing_keys       [{kid, public_key_pem}] — Rem0te's event/request key(s)
  ticket_rmm_capabilities   the last Check pairing result
  ticket_rmm_needs_repair   set by migration 0035 for pairings made with HMAC
  ticket_rmm_legacy_hmac    what 0035 switched off, so reversing it restores it

The organization id Rem0te maps to a business is `organization_id()`
("org-<pk>"); technicians are "tech-<user pk>". Rem0te matches nothing by
name: an administrator maps both in Rem0te.

Check pairing (`check()`) makes one signed GET /capabilities and records
exactly why it failed, without secrets. Revisions (contract_revision in
/capabilities; absent = 1):

  1  Rem0te 0.26–0.29. The organization mapping is learned from a signed,
     side-effect-free GET /alerts/events probe (403 = not mapped). Nothing
     says which business the organization is bound to.
  2  Rem0te 0.30. `organizations` names every organization of this peer with
     its business id, name and containment pauses. ClientSt0r keeps only
     this connection's own entry (the others are other customers'), checks
     its business id against the business the connection's inventory API
     key belongs to (a mismatch stops the pairing: BUSINESS_MISMATCH), and
     shows the pauses. Alerts may carry `patch_summary`.
  >2 accepted with a warning: fields ClientSt0r does not know are tolerated
     in what Rem0te sends (logged by path, never by value) and never used.

Compatibility is pinned to the revision in contract/PIN.json; rev1/ keeps
the revision-1 schemas.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, List, Tuple

import logging

from . import client, identity, protocol, schema

logger = logging.getLogger('integrations.rem0te')

AUTH = 'ticket_rmm_auth'
AUDIENCE = 'rem0te_audience'
SIGNING_KEYS = 'rem0te_signing_keys'
NEEDS_REPAIR = 'ticket_rmm_needs_repair'
LEGACY = 'ticket_rmm_legacy_hmac'

MIN_VERSION = (0, 26, 0)      # analysis jobs + action proposals in the contract shape tested here
ALERTS_VERSION = (0, 29, 0)   # alert events
IMPLEMENTED_REVISION = schema.IMPLEMENTED_REVISION
_VERSION_RE = re.compile(r'^(\d+)\.(\d+)\.(\d+)')

# Catalog actions ClientSt0r knows how to propose (Rem0te's catalog decides
# everything else). params must equal Rem0te's catalog entry.
KNOWN_ACTIONS = {
    'windows.service.start@1': {'id': 'windows.service.start', 'version': 1, 'params': {'service': 'Spooler'},
                                'label': 'Start the Print Spooler service', 'risk': 'low'},
}


@lru_cache(maxsize=1)
def pin() -> dict:
    return json.loads((schema.CONTRACT_DIR / 'PIN.json').read_text())


def _now():
    return datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'


def is_rem0te(connection) -> bool:
    return getattr(connection, 'provider_type', '') == 'rem0te'


def organization_id(connection) -> str:
    return f'org-{connection.organization_id}'


def technician_id(user) -> str:
    return f'tech-{user.pk}'


def signing_keys(connection) -> List[dict]:
    keys = (connection.field_mappings or {}).get(SIGNING_KEYS) or []
    return [k for k in keys if isinstance(k, dict)] if isinstance(keys, list) else []


def parse_signing_keys(text: str) -> List[dict]:
    """Rem0te's public keys as pasted: `kid` lines each followed by a PEM
    block, or JSON — a list of {kid, public_key_pem} or a capabilities
    document's signing_keys. Raises ValueError with a reason."""
    text = (text or '').strip()
    if not text:
        return []
    entries = []
    if text[0] in '[{':
        try:
            doc = json.loads(text)
        except ValueError:
            raise ValueError('That is not valid JSON.')
        if isinstance(doc, dict):
            doc = doc.get('signing_keys')
        if not isinstance(doc, list):
            raise ValueError('Expected a list of {"kid", "public_key_pem"} or a capabilities document.')
        for e in doc:
            if not isinstance(e, dict):
                raise ValueError('Each key needs a "kid" and a "public_key_pem".')
            entries.append((str(e.get('kid') or ''), str(e.get('public_key_pem') or '')))
    else:
        kid, pem = None, None
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if pem is not None:
                pem.append(line)
                if line.startswith('-----END'):
                    entries.append((kid or '', '\n'.join(pem) + '\n'))
                    kid, pem = None, None
            elif line.startswith('-----BEGIN'):
                if 'PRIVATE' in line:
                    raise ValueError('That is a private key. Paste Rem0te\'s public key only — and replace that '
                                     'private key, since it has now been copied.')
                if kid is None:
                    raise ValueError('Put the key id on the line before each PEM block.')
                pem = [line]
            else:
                if kid is not None:
                    raise ValueError(f'Key id "{kid[:40]}" has no PEM block after it.')
                kid = line
        if pem is not None or kid is not None:
            raise ValueError('The last key is incomplete.')
    out, seen = [], set()
    for kid, pem in entries:
        if not protocol.KID_RE.match(kid):
            raise ValueError(f'"{kid[:40]}" is not a valid key id (letters, digits, ".", "_", "-").')
        if kid in seen:
            raise ValueError(f'Key id "{kid}" is listed twice.')
        try:
            key = protocol.load_public_key(pem)
        except protocol.ProtocolError as e:
            raise ValueError(f'Key "{kid}": {e}.')
        seen.add(kid)
        out.append({'kid': kid, 'public_key_pem': protocol.public_pem(key)})
    if len(out) > 4:
        raise ValueError('At most 4 keys (the current one and previous ones during rotation).')
    return out


def format_signing_keys(keys) -> str:
    return '\n'.join(f"{k.get('kid', '')}\n{(k.get('public_key_pem') or '').strip()}" for k in keys or []
                     if isinstance(k, dict))


def keyring(connection):
    return protocol.keyring(signing_keys(connection))


def settings(connection) -> Dict[str, Any]:
    from integrations.ticket_rmm import ENABLED, LOCATION, URL, contract_site
    m = connection.field_mappings or {}
    site = contract_site(connection)
    location = 'local' if m.get(LOCATION) == 'local' else 'hosted'
    audience = str(m.get(AUDIENCE) or '')
    keys = signing_keys(connection)
    problems = []
    if m.get(NEEDS_REPAIR):
        problems.append('This pairing was made with shared secrets (HMAC) before ClientSt0r spoke Rem0te\'s '
                        'Ed25519 protocol. It must be paired again with Ed25519.')
    if not audience:
        problems.append("Rem0te's audience is not set.")
    if not keyring(connection):
        problems.append("Rem0te's public signing key is not set.")
    if not site:
        problems.append("Rem0te's address is not set.")
    elif not (site.startswith('https://') or (site.startswith('http://') and location == 'local')):
        problems.append("Rem0te's address must use https (plain http only for an on-premises Rem0te).")
    return {
        'requested': bool(m.get(ENABLED)),
        'enabled': bool(m.get(ENABLED)) and connection.is_active and not problems,
        'incomplete': ' '.join(problems),
        'needs_repair': bool(m.get(NEEDS_REPAIR)),
        'site': site, 'url': str(m.get(URL) or ''), 'location': location,
        'rem0te_audience': audience, 'signing_keys': keys,
        'organization_id': organization_id(connection),
    }


def last_check(connection) -> dict:
    from integrations.ticket_rmm import CAPS
    doc = (connection.field_mappings or {}).get(CAPS) or {}
    return doc if isinstance(doc, dict) and doc.get('protocol') == 'ed25519' else {}


def is_processor(connection) -> bool:
    s = settings(connection)
    doc = last_check(connection)
    return bool(s['enabled'] and doc.get('compatible'))


def advertised(connection) -> set:
    """ClientSt0r capability names this Rem0te supports, from its last
    compatible check. Rem0te's contract has no handoff, diagnostics or
    remote-launch routes, so those are never advertised for it."""
    if not is_processor(connection):
        return set()
    feats = last_check(connection).get('features') or {}
    out = set()
    if feats.get('ticket_analysis'):
        out.add('analysis.jobs')
    if proposable_actions(connection):
        out.add('signed_actions')
    if feats.get('alerts'):
        out.add('alerts')
    return out


def proposable_actions(connection) -> List[dict]:
    feats = last_check(connection).get('features') or {}
    return [dict(KNOWN_ACTIONS[a], key=a) for a in (feats.get('actions') or []) if a in KNOWN_ACTIONS]


def offered_profiles(connection) -> List[str]:
    return [p for p in (last_check(connection).get('model_profiles') or []) if isinstance(p, str)]


def profile_slug(profile) -> str:
    """The model profile name Rem0te knows a ClientSt0r AI profile by. Stable
    across renames; Rem0te never learns the model or the key behind it."""
    return f'cs-profile-{profile.pk}'


def version_tuple(v) -> Tuple[int, int, int] | None:
    m = _VERSION_RE.match(str(v or ''))
    return tuple(int(x) for x in m.groups()) if m else None


# --- Check pairing -------------------------------------------------------------

FAILURE_TEXT = {
    'NOT_CONFIGURED_LOCAL': 'ClientSt0r\'s side is incomplete: {detail}',
    'UNREACHABLE': '{detail}',
    'BLOCKED': '{detail}',
    'NOT_CONFIGURED': 'Rem0te says the integration is not configured on that server (404 NOT_CONFIGURED): '
                      'INTEGRATION_PEERS_FILE is not set, or it lists no enabled peers. Add ClientSt0r\'s entry '
                      'below to the peers file and restart the Rem0te API and worker.',
    'KEY_UNKNOWN': 'Rem0te does not know the key id "{key_id}" (401 Unknown key). The peers file must list peer '
                   '"{peer_id}" with request key "{kid}" — copy the entry below and restart Rem0te.',
    'CLOCK_SKEW': 'Rem0te refused the request timestamp (401: outside the allowed ±120 s window).{skew} Fix the '
                  'clock (NTP) on whichever side is wrong.',
    'SIGNATURE_REJECTED': 'Rem0te rejected the request signature (401). Either Rem0te\'s audience here '
                          '("{audience}") is not the peers file\'s peers[].audience for "{peer_id}", or the '
                          'request public key in the peers file is not ClientSt0r\'s (fingerprint {fp}).',
    'HEADERS_REJECTED': 'Rem0te refused the signature headers as malformed (401).',
    'REPLAYED': 'Rem0te refused the request as a replay (401 REPLAYED). Try again; if it repeats, two '
                'ClientSt0r instances may be sharing one identity.',
    'CLIENT_CERT': 'Rem0te requires a pinned client certificate for this peer (mTLS), and none was presented.',
    'RATE_LIMITED': 'Rem0te is rate limiting this peer (429). Try again shortly.',
    'CONTRACT_MISMATCH': 'Rem0te does not speak the contract revision ClientSt0r was tested against: {detail}',
    'VERSION_INCOMPATIBLE': '{detail}',
    'PEER_MISMATCH': '{detail}',
    'SIGNING_KEY_MISMATCH': '{detail}',
    'INVALID_RESPONSE': '{detail}',
    'HTTP_ERROR': 'Rem0te answered HTTP {status}{code}.',
    'BUSINESS_MISMATCH': '{detail}',
}
BUSINESS_MISMATCH = 'BUSINESS_MISMATCH'


def _bind_business(connection, organizations, doc, pins, warnings) -> str:
    """Revision 2's `organizations`: record this organization's own entry and
    check its business against the one this connection is pinned to (the
    business its inventory API key answers for). Returns why the pairing
    must stop, or ''. Never stores another organization's entry."""
    from integrations.ticket_rmm import REM0TE_BUSINESS_PIN, TENANT_PIN
    own_id = organization_id(connection)
    own = next((o for o in organizations if isinstance(o, dict) and o.get('organization_id') == own_id), None)
    doc['organizations_count'] = len(organizations)
    if own is None:
        doc['org_mapped'] = False
        doc.pop('organization', None)
        warnings.append(f'Rem0te has no business mapped to this organization ("{own_id}"). A Platform Admin maps '
                        'it in Rem0te (POST /api/v1/admin/integration/mappings/organizations); analysis jobs and '
                        'alerts are refused until then.')
        return ''
    paused = sorted({p for p in own.get('paused') or [] if p in ('actions', 'remote', 'updates', 'integration')})
    business_id = client.safe_text(own.get('business_id'), 64)
    doc['org_mapped'] = True
    doc['organization'] = {'organization_id': own_id, 'business_id': business_id,
                           'business_name': client.safe_text(own.get('business_name'), 120), 'paused': paused}
    m = connection.field_mappings or {}
    pinned = str(m.get(REM0TE_BUSINESS_PIN) or m.get(TENANT_PIN) or '')
    if pinned and pinned != business_id:
        doc['business_binding'] = {
            'status': 'mismatch', 'pinned': pinned, 'reported': business_id,
            'detail': f'Rem0te binds organization "{own_id}" to business {business_id}, but this connection belongs '
                      f'to business {pinned} (its inventory API key). ClientSt0r stopped the pairing so one '
                      "customer's alerts and computers are never filed under another."}
        return doc['business_binding']['detail']
    if not pinned:
        pins[TENANT_PIN] = business_id  # the inventory sync now refuses a key for any other business
    doc['business_binding'] = {'status': 'match', 'pinned': pinned or business_id, 'reported': business_id,
                               'detail': f'Organization "{own_id}" is bound to business {business_id}'
                                         + (' (pinned now).' if not pinned else ', the same business as the '
                                            'inventory API key.')}
    if paused:
        warnings.append('Rem0te reports a containment pause for this business: ' + ', '.join(paused) + '.')
    return ''


def _classify(r: client.Result, ctx: dict) -> Tuple[str, str]:
    if r.transport in ('unreachable', 'timeout', 'read'):
        return 'UNREACHABLE', r.message
    if r.transport == 'blocked':
        return 'BLOCKED', r.message
    if r.transport:
        return 'INVALID_RESPONSE', r.message
    if r.status == 404 and r.code == 'NOT_CONFIGURED':
        return 'NOT_CONFIGURED', ''
    if r.status == 401:
        msg = r.message.lower()
        if r.code == 'REPLAYED':
            return 'REPLAYED', ''
        if 'unknown key' in msg:
            return 'KEY_UNKNOWN', ''
        if 'timestamp' in msg:
            return 'CLOCK_SKEW', ''
        if 'malformed' in msg or 'missing' in msg:
            return 'HEADERS_REJECTED', ''
        if 'certificate' in msg:
            return 'CLIENT_CERT', ''
        if r.clock_skew_s is not None and abs(r.clock_skew_s) > protocol.MAX_CLOCK_SKEW_S:
            return 'CLOCK_SKEW', ''
        return 'SIGNATURE_REJECTED', ''
    if r.status == 429:
        return 'RATE_LIMITED', ''
    return 'HTTP_ERROR', ''


def _text(code, ctx, detail='') -> str:
    skew = ctx.get('skew')
    return FAILURE_TEXT[code].format(
        detail=detail, skew=(f' Rem0te\'s clock is {skew:+d} s from ClientSt0r\'s.' if isinstance(skew, int) else ''),
        **{k: v for k, v in ctx.items() if k != 'skew'})


def validate_capabilities(doc, connection, ident, meta=None) -> Tuple[str, str, List[str]]:
    """(failure code or '', detail, warnings) for a capabilities response.
    `meta` (a dict) receives the revision Rem0te reports and the unknown
    field paths that were tolerated."""
    warnings: List[str] = []
    meta = meta if meta is not None else {}
    if not isinstance(doc, dict):
        return 'INVALID_RESPONSE', 'The capabilities response is not a JSON object.', warnings
    if doc.get('contract') != protocol.CONTRACT:
        return 'CONTRACT_MISMATCH', f'it reports contract "{client.safe_text(doc.get("contract"), 40)}", ' \
                                    f'ClientSt0r speaks "{protocol.CONTRACT}".', warnings
    raw_rev = doc.get('contract_revision', 1)
    if not isinstance(raw_rev, int) or isinstance(raw_rev, bool) or raw_rev < 1:
        return 'CONTRACT_MISMATCH', 'its contract_revision is not a positive integer.', warnings
    errs, unknown, validated = schema.errors_from_peer('capabilities', doc, raw_rev)
    meta.update(contract_revision=raw_rev, validated_revision=validated, unknown_fields=unknown)
    if errs:
        return 'CONTRACT_MISMATCH', f'its capabilities (revision {raw_rev}) do not match the pinned schema (' + \
            '; '.join(client.safe_text(e, 80) for e in errs[:3]) + ').', warnings
    if validated != raw_rev and raw_rev <= IMPLEMENTED_REVISION:
        return 'CONTRACT_MISMATCH', (f'it reports revision {raw_rev} but sends a revision-{validated} document.'), \
            warnings
    if raw_rev > IMPLEMENTED_REVISION:
        logger.warning('Rem0te speaks ticket-rmm-v1 revision %s (ClientSt0r implements %s); tolerated unknown '
                    'capabilities fields: %s', raw_rev, IMPLEMENTED_REVISION, ', '.join(unknown) or 'none')
        warnings.append(f'Rem0te speaks contract revision {raw_rev}; this ClientSt0r implements revision '
                        f'{IMPLEMENTED_REVISION} and uses nothing newer'
                        + (f' (ignored: {", ".join(unknown[:6])})' if unknown else '') + '.')
    version = version_tuple(doc.get('rem0te_version'))
    tested = version_tuple(pin()['rem0te_version'])
    if version is None:
        warnings.append(f'Rem0te reports its version as "{client.safe_text(doc.get("rem0te_version"), 40)}"; '
                        f'ClientSt0r was tested against {pin()["rem0te_version"]}.')
    elif version < MIN_VERSION:
        return 'VERSION_INCOMPATIBLE', (f'Rem0te {doc["rem0te_version"]} is older than the oldest revision this '
                                        f'ClientSt0r supports ({".".join(map(str, MIN_VERSION))}). Update Rem0te.'), \
            warnings
    elif version[:2] != tested[:2]:
        warnings.append(f'Rem0te {doc["rem0te_version"]} is a different release from the one this ClientSt0r was '
                        f'tested against ({pin()["rem0te_version"]}, {pin()["rem0te_sha"][:12]}). The contract '
                        'check passed; run the cross-peer tests before relying on new behaviour.')
    if doc.get('peer_id') != ident.peer_id:
        return 'PEER_MISMATCH', (f'Rem0te accepted the request as peer "{client.safe_text(doc.get("peer_id"), 64)}", '
                                 f'but ClientSt0r is "{ident.peer_id}".'), warnings
    s = settings(connection)
    if doc.get('audience') != s['rem0te_audience']:
        return 'PEER_MISMATCH', (f'Rem0te calls itself "{client.safe_text(doc.get("audience"), 100)}", but this '
                                 f'connection has "{s["rem0te_audience"]}".'), warnings
    advertised_keys = {k.get('kid'): k.get('public_key_pem') for k in doc.get('signing_keys') or []}
    for k in s['signing_keys']:
        pem = advertised_keys.get(k.get('kid'))
        if pem is None:
            return 'SIGNING_KEY_MISMATCH', (f'Rem0te does not advertise the signing key "{k.get("kid")}" configured '
                                            'here. Advertised: ' + ', '.join(
                                                f'{kid} ({_fp(pem)})' for kid, pem in advertised_keys.items())
                                            + '. Compare the fingerprint with Rem0te\'s key and update this '
                                              'connection.'), warnings
        if not protocol.same_public_key(pem, k.get('public_key_pem') or ''):
            return 'SIGNING_KEY_MISMATCH', (f'Rem0te advertises a different public key under "{k.get("kid")}" '
                                            f'({_fp(pem)}) than the one configured here '
                                            f'({_fp(k.get("public_key_pem"))}).'), warnings
    if not doc['features'].get('ticket_analysis'):
        warnings.append('Rem0te does not offer ticket analysis to this peer.')
    if not doc['features'].get('alerts') and version and version >= ALERTS_VERSION:
        warnings.append('Rem0te does not offer alert events to this peer.')
    return '', '', warnings


def _fp(pem) -> str:
    try:
        return protocol.fingerprint(pem or '')
    except protocol.ProtocolError:
        return 'unreadable key'


def check(connection) -> dict:
    """Check pairing: signed capabilities + organization-mapping probe.
    Stores and returns the result (never raises for a remote failure)."""
    from integrations.ticket_rmm import CAPS, _save
    ident = identity.get(create=False)
    s = settings(connection)
    ctx = {'peer_id': getattr(ident, 'peer_id', ''), 'kid': getattr(ident, 'request_kid', ''),
           'key_id': identity.request_key_id(ident) if ident else '', 'audience': s['rem0te_audience'],
           'fp': (identity.public_view(ident) or {}).get('request', {}).get('fingerprint', '—') if ident else '—',
           'status': '', 'code': ''}
    previous = last_check(connection)
    doc: Dict[str, Any] = {'protocol': 'ed25519', 'checked_at': _now(), 'ok': False, 'compatible': False,
                           'code': '', 'error': '', 'warnings': [],
                           'tested_against': {'contract': pin()['contract'], 'rem0te_version': pin()['rem0te_version'],
                                              'rem0te_sha': pin()['rem0te_sha']}}

    pins = {}

    def done(code='', detail=''):
        if code:
            doc.update(code=code, error=_text(code, ctx, detail)[:600])
            # An outage after a good check keeps the last good capabilities
            # (shown with the error); a protocol failure does not.
            if code in ('UNREACHABLE', 'RATE_LIMITED') and previous.get('compatible'):
                for k in ('features', 'model_profiles', 'limits', 'rem0te_version', 'signing_keys',
                          'org_mapped', 'fetched_at', 'contract_revision', 'validated_revision', 'organization',
                          'business_binding', 'technicians'):
                    if k in previous:
                        doc[k] = previous[k]
                doc['compatible'] = True
            doc['failures'] = int(previous.get('failures') or 0) + 1 if not previous.get('ok') else 1
        else:
            doc['failures'] = 0
            if previous.get('technicians'):
                doc['technicians'] = previous['technicians']
        mappings = dict(connection.field_mappings or {})
        mappings.update(pins)
        mappings[CAPS] = doc
        _save(connection, mappings)
        return doc

    if not s['requested']:
        return done('NOT_CONFIGURED_LOCAL', 'the pairing is not switched on and approved yet.')
    if s['incomplete']:
        return done('NOT_CONFIGURED_LOCAL', s['incomplete'])
    missing = identity.configured(ident)
    if missing:
        return done('NOT_CONFIGURED_LOCAL', missing)
    try:
        r = client.request(connection, 'GET', '/capabilities')
    except client.NotSent as e:
        return done('NOT_CONFIGURED_LOCAL', e.message)
    ctx['skew'] = r.clock_skew_s
    if not r.ok:
        code, detail = _classify(r, ctx)
        ctx['status'] = r.status
        ctx['code'] = f' ({r.code})' if r.code and not r.code.startswith('HTTP_') else ''
        return done(code, detail)
    meta: Dict[str, Any] = {}
    code, detail, warnings = validate_capabilities(r.data, connection, ident, meta)
    doc['warnings'] = warnings
    doc.update(meta)
    if isinstance(r.clock_skew_s, int):
        doc['clock_skew_s'] = r.clock_skew_s
    if code:
        return done(code, detail)
    cap = r.data
    doc.update(ok=True, compatible=True, fetched_at=_now(), rem0te_version=cap['rem0te_version'],
               features=cap['features'], model_profiles=cap['model_profiles'], limits=cap['limits'],
               signing_keys=[{'kid': k['kid'], 'fingerprint': _fp(k['public_key_pem'])} for k in cap['signing_keys']])
    if isinstance(r.clock_skew_s, int) and abs(r.clock_skew_s) > 60:
        warnings.append(f'Rem0te\'s clock is {r.clock_skew_s:+d} s from ClientSt0r\'s; requests fail beyond ±120 s.')
    if isinstance(cap.get('organizations'), list):
        # Revision 2: the binding, stated by Rem0te. Only this organization's
        # own entry is kept: the others are other customers' businesses.
        problem = _bind_business(connection, cap['organizations'], doc, pins, warnings)
        if problem:
            # Not a processor for this connection until the binding agrees.
            doc.update(ok=False, compatible=False)
            return done(BUSINESS_MISMATCH, problem)
        from . import health
        paused = (doc.get('organization') or {}).get('paused') or []
        # A refusal recorded during a pause is history once Rem0te says the
        # pause is lifted; the next job or proposal shows any new problem.
        if 'integration' not in paused:
            health.clear(connection, 'jobs', code='CONTAINED')
        if 'actions' not in paused:
            health.clear(connection, 'actions', code='CONTAINED')
    elif cap['features'].get('alerts'):
        # Revision 1: is this organization mapped to a business in Rem0te?
        # Alert polling answers 403 for an unmapped organization and is
        # service-level (no technician token): a side-effect-free probe.
        probe = client.request(connection, 'GET', '/alerts/events',
                               query={'organization_id': organization_id(connection), 'after': 999999999})
        if probe.ok:
            doc['org_mapped'] = True
        elif probe.status == 403:
            doc['org_mapped'] = False
            warnings.append(f'Rem0te has no business mapped to this organization ("{organization_id(connection)}"). '
                            'A Platform Admin maps it in Rem0te (POST /api/v1/admin/integration/mappings/'
                            'organizations); analysis jobs and alerts are refused until then.')
        else:
            doc['org_mapped'] = None
            warnings.append(f'Could not confirm the organization mapping ({probe.code or probe.status}).')
    profiles = usable_profile_slugs(connection)
    missing_profiles = [p for p in profiles if p not in cap['model_profiles']]
    if missing_profiles:
        warnings.append('Rem0te does not offer these ClientSt0r model profiles to this peer: '
                        + ', '.join(missing_profiles) + '. Add them to modelProfiles in the peers file.')
    return done()


def usable_profile_slugs(connection) -> List[str]:
    try:
        from psa_ai.models import AIBusinessPolicy
        policy = AIBusinessPolicy.objects.filter(organization_id=connection.organization_id).first()
        if policy is None:
            return []
        return [profile_slug(p) for p in policy.allowed_profiles.filter(enabled=True).order_by('pk')]
    except Exception:
        return []


def status(connection) -> Dict[str, Any]:
    """Plain-words pairing state and the to-do list for the connection page."""
    s = settings(connection)
    doc = last_check(connection)
    ident = identity.get(create=False)
    pending = False
    if connection.pk:
        from tech_access.models import ProtectedChange
        pending = any(c.payload.get('connection') == connection.pk for c in ProtectedChange.objects.filter(
            kind='business_mapping', status=ProtectedChange.PENDING))
    if s['needs_repair']:
        state, label = 'error', 'Needs re-pairing (Ed25519)'
        detail = ('This Rem0te pairing used shared secrets (HMAC). Rem0te authenticates ClientSt0r only with '
                  'Ed25519 signatures, so ClientSt0r has stopped all traffic to and from it. Follow the steps '
                  'below, then press Check pairing.')
    elif not s['requested'] and not pending:
        state, label, detail = 'off', 'Not paired', 'Ticket integration pairing is off for this connection.'
    elif not s['requested'] and pending:
        state, label = 'pending', 'Waiting for approval'
        detail = 'A second administrator has to approve this pairing (Settings → Security → Technician Access).'
    elif s['incomplete'] or identity.configured(ident):
        state, label = 'pending', 'Incomplete'
        detail = ' '.join(x for x in (s['incomplete'], identity.configured(ident)) if x)
    elif not doc:
        state, label, detail = 'checking', 'Not checked yet', 'Approved. Press Check pairing.'
    elif not doc.get('compatible'):
        state, label, detail = 'error', 'Not paired yet', doc.get('error') or 'The last check failed.'
    elif doc.get('error'):
        state, label = 'warning', 'Paired — last check failed'
        detail = doc['error'] + ' The capabilities below are from the last successful check.'
    else:
        state, label, detail = 'ok', 'Paired', 'Rem0te processes ticket-rmm-v1 requests for this organization.'
    from . import health
    return {
        'health': health.evaluate(connection),
        'protocol': 'ed25519', 'state': state, 'label': label, 'detail': detail, 'pending_approval': pending,
        'settings': s, 'check': doc, 'warnings': doc.get('warnings') or [],
        'capabilities': sorted(advertised(connection)), 'diagnostics': [],
        'checked_at': doc.get('checked_at', ''), 'tenant_name': '',
        'identity': identity.public_view(ident),
        'peer_entry': identity.peer_entry_json(connection, usable_profile_slugs(connection)),
        'organization_id': organization_id(connection),
        'proposable_actions': proposable_actions(connection),
        'pin': pin(),
        'steps': [
            "Generate ClientSt0r's Rem0te keys (below) and set ClientSt0r's audience and the address Rem0te "
            'reaches ClientSt0r at.',
            'On the Rem0te server (root), add the peers-file entry shown below to INTEGRATION_PEERS_FILE — '
            'public keys, audiences and the two URLs — and restart the Rem0te API and integration worker.',
            "Enter Rem0te's audience and Rem0te's public signing key (and its key id) on this connection; save. "
            'A second administrator approves the pairing.',
            f'In Rem0te (Platform Admin, step-up), map organization "{organization_id(connection)}" to its '
            'business, and each technician ("tech-<ClientSt0r user id>") to their Rem0te user; grant them '
            '"Ticket analysis (ClientSt0r)" there.',
            'Press Check pairing.',
        ],
    }
