"""
The Rem0te setup wizard's checks (Settings → RMM → Rem0te): one checklist per
connection that says exactly what is missing — keys, identity, mapping,
clock skew, capability, network — from the stored check plus the live Test
connection.

Test connection = Check pairing (signed GET /capabilities, and for a
revision-1 Rem0te the organization probe) + a technician-mapping probe for
the administrator pressing the button: a delegated GET /jobs/{nil uuid}.
Rem0te verifies the delegation and the technician's live access *before*
looking the job up, so 404 means "mapped and allowed" and 403 carries
Rem0te's reason ("Technician is not mapped", "… has no current access",
"… lacks integration:ticket_analysis"). The probe reads nothing and creates
nothing (it spends one single-use delegation id). A side-effect-free,
documented route for this is requested from Rem0te (R3).
"""
from __future__ import annotations

from typing import Dict, List

from django.utils import timezone

from . import client, health, identity, pairing, protocol

PROBE_JOB = '00000000-0000-4000-8000-000000000000'
OK, WARN, FAIL, UNKNOWN, NA = 'ok', 'warn', 'fail', 'unknown', 'n/a'


def technician_probe(connection, user) -> Dict:
    """Is `user` mapped (and allowed) in Rem0te for this organization?"""
    tech = pairing.technician_id(user)
    out = {'technician_id': tech, 'status': UNKNOWN, 'message': '', 'at': timezone.now().isoformat()}
    try:
        r = client.request(connection, 'GET', f'/jobs/{PROBE_JOB}',
                           delegation=('ticket_analysis:read', tech, None))
    except (client.NotSent, protocol.ProtocolError, identity.IdentityError) as e:
        out['message'] = f'Not sent: {getattr(e, "message", e)}'
        return out
    if r.status == 404:
        out.update(status=OK, message=f'{tech} is mapped in Rem0te and may use ticket analysis for this business.')
        health.clear(connection, 'technician')
    elif r.status == 403:
        out.update(status=FAIL, message=f'Rem0te refused {tech}: {r.message or "forbidden"}. Map the technician '
                                        '(Platform Admin → integration mappings) and grant "Ticket analysis '
                                        '(ClientSt0r)".')
        health.note(connection, 'technician', out['message'], code='TECHNICIAN_NOT_MAPPED',
                    action='Map the technician in Rem0te and grant integration:ticket_analysis.')
    elif r.status == 401:
        out.update(status=FAIL, message=f'Rem0te refused the delegation ({r.code}: {r.message}).')
    else:
        out['message'] = r.message or f'Rem0te answered HTTP {r.status}.'
    mappings = dict(connection.field_mappings or {})
    from integrations.ticket_rmm import CAPS, _save
    doc = dict(mappings.get(CAPS) or {})
    if doc.get('protocol') == 'ed25519':
        techs = dict(doc.get('technicians') or {})
        techs[tech] = {k: out[k] for k in ('status', 'message', 'at')}
        doc['technicians'] = dict(list(techs.items())[-20:])
        mappings[CAPS] = doc
        _save(connection, mappings)
    return out


def test_connection(connection, user) -> Dict:
    doc = pairing.check(connection)
    connection.refresh_from_db()
    probe = None
    if doc.get('compatible') and doc.get('features', {}).get('ticket_analysis'):
        probe = technician_probe(connection, user)
        connection.refresh_from_db()
    health.touch(connection, success=bool(doc.get('ok')))
    return {'check': doc, 'technician': probe}


def _item(key, label, status, detail='', action=''):
    return {'key': key, 'label': label, 'status': status, 'detail': detail, 'action': action}


def checklist(connection) -> List[Dict]:
    """What is in place and what is missing, in setup order."""
    ident = identity.get(create=False)
    s = pairing.settings(connection)
    doc = pairing.last_check(connection)
    code = doc.get('code', '')
    items = []
    items.append(_item('keys', "ClientSt0r's Ed25519 keys", OK if identity.has_keys(ident) else FAIL,
                       '' if identity.has_keys(ident) else 'Not generated yet.', 'Generate keys (superuser).'))
    miss = identity.configured(ident) if identity.has_keys(ident) else ''
    items.append(_item('identity', "ClientSt0r's peer id, audience and public address", FAIL if miss else
                       (OK if ident else FAIL), miss, 'Save the identity (superuser).'))
    conn_missing = [m for m, bad in ((
        "Rem0te's audience", not s['rem0te_audience']), ("Rem0te's public signing key", not pairing.keyring(connection)),
        ("Rem0te's address", not s['site'])) if bad]
    items.append(_item('connection', "Rem0te's audience, signing key and address on this connection",
                       FAIL if conn_missing or s['needs_repair'] else OK,
                       ('Missing: ' + ', '.join(conn_missing) + '.') if conn_missing else
                       (s['incomplete'] if s['needs_repair'] else ''), 'Edit the connection.'))
    items.append(_item('approval', 'Pairing switched on and approved by a second administrator',
                       OK if s['requested'] else FAIL, '' if s['requested'] else 'Not switched on / approved.',
                       'Edit the connection; a second administrator approves it.'))
    if not doc:
        items.append(_item('tested', 'Tested against Rem0te', UNKNOWN, 'Not tested yet.', 'Press Test connection.'))
        return items
    net = FAIL if code in health.NETWORK_CODES else OK
    items.append(_item('network', 'Rem0te reachable', net, doc.get('error', '') if net == FAIL else '',
                       health.ACTIONS.get(code, '')))
    if net == FAIL:
        return items
    auth = FAIL if code in health.AUTH_CODES and code != 'CLOCK_SKEW' else OK
    items.append(_item('auth', 'Signatures accepted (request key known to Rem0te, audiences and signing key agree)',
                       auth, doc.get('error', '') if auth == FAIL else '', health.ACTIONS.get(code, '')))
    skew = doc.get('clock_skew_s')
    if code == 'CLOCK_SKEW':
        items.append(_item('clock', 'Clocks within ±120 s', FAIL, doc.get('error', ''), health.ACTIONS['CLOCK_SKEW']))
    elif isinstance(skew, int):
        items.append(_item('clock', 'Clocks within ±120 s', WARN if abs(skew) > 60 else OK, f'Skew {skew:+d} s.'))
    else:
        items.append(_item('clock', 'Clocks within ±120 s', UNKNOWN, 'Rem0te sent no Date header.'))
    contract_ok = code not in ('CONTRACT_MISMATCH', 'VERSION_INCOMPATIBLE', 'PEER_MISMATCH')
    rev = doc.get('contract_revision')
    items.append(_item('contract', 'Contract ticket-rmm-v1 and version', OK if contract_ok else FAIL,
                       (f'Rem0te {doc.get("rem0te_version", "?")}, contract revision {rev or 1} '
                        f'(ClientSt0r implements {pairing.IMPLEMENTED_REVISION}).') if contract_ok else doc.get('error', ''),
                       health.ACTIONS.get(code, '')))
    if not doc.get('compatible'):
        return items
    feats = doc.get('features') or {}
    missing_caps = [n for n, on in (('ticket analysis', feats.get('ticket_analysis')), ('alert events', feats.get('alerts')),
                                    ('catalog actions', bool(feats.get('actions')))) if not on]
    items.append(_item('capabilities', 'Capabilities', WARN if missing_caps else OK,
                       ('Not supported by the connected Rem0te: ' + ', '.join(missing_caps) + '.') if missing_caps
                       else 'Ticket analysis, alert events and catalog actions.'))
    mapped = doc.get('org_mapped')
    items.append(_item('organization', f'Organization "{pairing.organization_id(connection)}" mapped to a business',
                       OK if mapped else (FAIL if mapped is False else UNKNOWN),
                       (f'Business {doc.get("organization", {}).get("business_name") or "?"} '
                        f'({doc.get("organization", {}).get("business_id") or "?"}).') if mapped and doc.get('organization')
                       else ('' if mapped else 'Map it in Rem0te (Platform Admin, step-up).')))
    if (rev or 1) >= 2:
        b = doc.get('business_binding') or {}
        items.append(_item('business', "Business binding agrees with the inventory API key's business",
                           FAIL if b.get('status') == 'mismatch' else (OK if b.get('status') == 'match' else UNKNOWN),
                           b.get('detail', ''), health.ACTIONS['BUSINESS_MISMATCH'] if b.get('status') == 'mismatch' else ''))
        paused = (doc.get('organization') or {}).get('paused') or []
        items.append(_item('containment', 'No containment pause in Rem0te', WARN if paused else OK,
                           ('Paused: ' + ', '.join(paused) + '.') if paused else ''))
    else:
        items.append(_item('business', "Business binding agrees with the inventory API key's business", NA,
                           'Not supported by the connected Rem0te (contract revision 1 does not report it).'))
    techs = doc.get('technicians') or {}
    if techs:
        bad = [f'{t}: {v.get("message")}' for t, v in techs.items() if v.get('status') == FAIL]
        items.append(_item('technicians', 'Technician mapping (checked by Test connection)', FAIL if bad else OK,
                           ' '.join(bad) if bad else ', '.join(sorted(techs)) + ' mapped.'))
    else:
        items.append(_item('technicians', 'Technician mapping', UNKNOWN, 'Press Test connection to check yours.'))
    missing_profiles = [p for p in pairing.usable_profile_slugs(connection) if p not in (doc.get('model_profiles') or [])]
    items.append(_item('profiles', 'Model profiles offered by Rem0te', WARN if missing_profiles else OK,
                       ('Not offered: ' + ', '.join(missing_profiles) + ' (modelProfiles in the peers file).')
                       if missing_profiles else ''))
    return items
