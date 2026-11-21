"""
Regenerate docs/agit8or-connect/test-vectors/*.json.

    python -m agit8or_connect.tools.generate_vectors [--check]

Every value is deterministic: Ed25519 signatures are deterministic, JWS
segments are canonical JSON, and every key is derived from a FIXED,
PUBLISHED, TEST-ONLY seed. Never use these keys for anything else.

--check regenerates in memory and exits 1 if the files on disk differ (CI).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

from agit8or_connect import audit, keys, pairing, tokens, webhooks
from agit8or_connect import quick_connect as qc
from agit8or_connect.canonical import b64url, canonical_json, sha256_hex
from agit8or_connect.jws import sign_compact, unverified_header, unverified_payload

NOW = 1767225600  # 2026-01-01T00:00:00Z
OUT = os.path.join(os.path.dirname(__file__), '..', '..', 'docs', 'agit8or-connect', 'test-vectors')
NOTICE = 'TEST-ONLY KEYS. Published seeds; never use outside conformance tests.'


def seed(name: str) -> bytes:
    return hashlib.sha256(f'agit8or-connect/1 TEST-ONLY key {name}'.encode()).digest()


KEYS = {n: keys.private_key_from_seed(seed(n)) for n in ('A', 'B', 'C')}
INSTALL = {'A': '11111111-1111-4111-8111-111111111111', 'B': '22222222-2222-4222-8222-222222222222'}


def key_section():
    out = {}
    for n, k in KEYS.items():
        out[n] = {'seed_hex': seed(n).hex(), 'public_jwk': keys.public_jwk(k), 'thumbprint': keys.thumbprint(k),
                  'fingerprint': keys.fingerprint(k)}
    return out


def canonical_vectors():
    cases = [
        {'b': 1, 'a': [True, False, None], 'c': {'z': 'x', 'y': 1.5}},
        {'unicode': 'é ☃  ', 'ctrl': '\u0001\n\t"\\', 'emoji': '😀'},
        {'n': [0, -1, 1e-7, 0.1, 123456789012, 2.5e-3, -0.0, 123.456, 1.5e-10]},
        {'é': 1, 'z': 2, 'A': 3, '😀': 4, 'a': 5},
        [],
        {},
    ]
    return [{'input': c, 'canonical': canonical_json(c)} for c in cases]


def token_vectors():
    a, b = KEYS['A'], KEYS['B']
    endpoint = 'https://responder.example.test/connect/v1/token'
    client_id = '33333333-3333-4333-8333-333333333333'
    ca = tokens.build_client_assertion(a, client_id, endpoint, now=NOW, jti='assertion-jti-0001')
    at, at_claims = tokens.issue_access_token(b, issuer=INSTALL['B'], client_id=client_id,
                                              scopes=['customers:read', 'connection:read'],
                                              jkt=keys.thumbprint(a), now=NOW, jti='access-token-jti-0001')
    api = 'https://responder.example.test/connect/v1/customers/current'
    dpop_token = tokens.build_dpop_proof(a, 'POST', endpoint, now=NOW, jti='dpop-token-jti-0001')
    dpop_api = tokens.build_dpop_proof(a, 'GET', api, now=NOW, jti='dpop-api-jti-0001', access_token=at)
    tampered = ca[:-4] + ('AAAA' if not ca.endswith('AAAA') else 'BBBB')
    return {
        'notice': NOTICE, 'now': NOW,
        'client_assertion': {'signer': 'A', 'client_id': client_id, 'token_endpoint': endpoint, 'jws': ca,
                             'verify': [
                                 {'at': NOW + 10, 'expect': 'valid'},
                                 {'at': NOW + 60 + 121, 'expect': 'invalid_client'},
                                 {'at': NOW + 10, 'token_endpoint': 'https://other.example.test/token',
                                  'expect': 'invalid_client'},
                                 {'at': NOW + 10, 'replay_twice': True, 'expect': 'replayed'},
                             ],
                             'tampered_jws': tampered, 'tampered_expect': 'invalid_client'},
        'access_token': {'signer': 'B', 'issuer': INSTALL['B'], 'jws': at,
                         'claims': at_claims, 'verify': [
                             {'at': NOW + 299, 'expect': 'valid'},
                             {'at': NOW + 300, 'expect': 'invalid_token'},
                             {'at': NOW + 1, 'issuer': INSTALL['A'], 'expect': 'invalid_token'},
                             {'at': NOW + 1, 'verify_with': 'C', 'expect': 'invalid_token'}]},
        'dpop': {'signer': 'A', 'token_request': {'method': 'POST', 'url': endpoint, 'jws': dpop_token},
                 'resource_request': {'method': 'GET', 'url': api, 'jws': dpop_api, 'access_token': at,
                                      'ath': tokens.access_token_hash(at)},
                 'htu_normalization': [
                     {'in': 'HTTPS://Responder.Example.TEST:443/connect/v1/token?x=1#f',
                      'out': 'https://responder.example.test/connect/v1/token'},
                     {'in': 'https://h.example.test:8443/a', 'out': 'https://h.example.test:8443/a'}],
                 'verify': [
                     {'at': NOW + 5, 'expect': 'valid'},
                     {'at': NOW + 121, 'expect': 'invalid_dpop_proof'},
                     {'at': NOW + 5, 'method': 'PUT', 'expect': 'invalid_dpop_proof'},
                     {'at': NOW + 5, 'replay_twice': True, 'expect': 'replayed'},
                     {'at': NOW + 5, 'expected_jkt_of': 'C', 'expect': 'invalid_dpop_proof'}]},
    }


def pairing_vectors():
    a, b = KEYS['A'], KEYS['B']
    pepper = b'agit8or-connect TEST-ONLY pepper'
    codes = ['7K3QM-9XD2P', '7k3qm9xd2p', 'oil00-ABCDE']
    req, claims = pairing.build_request(
        a, initiator_app={'type': 'clientst0r', 'version': '3.17.0', 'display_name': 'MSP A',
                          'installation_id': INSTALL['A']},
        responder_installation=INSTALL['B'], pairing_code='7K3QM-9XD2P',
        connection_id='44444444-4444-4444-8444-444444444444',
        discovery_url='https://initiator.example.test/.well-known/agit8or-connect',
        requested_scopes=['customers:read', 'events:publish'],
        proposed_tenants=[{'id': 'org-1', 'label': 'Customer One'}], now=NOW, jti='pairing-jti-0001')
    th = pairing.transcript_hash(request_jws=req, request_jti=claims['jti'], initiator_installation=INSTALL['A'],
                                 initiator_jkt=keys.thumbprint(a), responder_installation=INSTALL['B'],
                                 responder_jkt=keys.thumbprint(b))
    ack = pairing.build_ack(b, responder_app={'type': 'rem0te', 'version': '0.60.0', 'display_name': 'Rem0te',
                                              'installation_id': INSTALL['B']},
                            initiator_installation=INSTALL['A'], request_id='55555555-5555-4555-8555-555555555555',
                            request_jti=claims['jti'], connection_id='66666666-6666-4666-8666-666666666666',
                            now=NOW)
    result = pairing.build_result(b, responder_installation=INSTALL['B'], initiator_installation=INSTALL['A'],
                                  request_id='55555555-5555-4555-8555-555555555555', request_jti=claims['jti'],
                                  status='approved', connection_id='66666666-6666-4666-8666-666666666666',
                                  granted_scopes=['customers:read'],
                                  tenant_grants=[{'tenant': 'cust-1', 'label': 'Customer One',
                                                  'remote_tenant': 'org-1', 'scopes': ['customers:read']}],
                                  requested_scopes=['tickets:write'], endpoints={}, now=NOW)
    poll = pairing.build_poll(a, initiator_installation=INSTALL['A'], responder_installation=INSTALL['B'],
                              request_id='55555555-5555-4555-8555-555555555555', now=NOW, jti='poll-jti-0001')
    return {
        'notice': NOTICE, 'now': NOW, 'pepper_utf8': pepper.decode(),
        'codes': [{'input': c, 'normalized': pairing.normalize_code(c), 'hmac_sha256': pairing.hash_code(c, pepper)}
                  for c in codes],
        'invalid_codes': ['7K3QM-9XD2', 'UUUUU-UUUUU', '', '7K3QM-9XD2P-1'],
        'request': {'signer': 'A', 'jws': req, 'responder_installation': INSTALL['B']},
        'ack': {'signer': 'B', 'jws': ack},
        'result': {'signer': 'B', 'jws': result},
        'poll': {'signer': 'A', 'jws': poll},
        'transcript_hash': th, 'sas': pairing.short_authentication_string(th),
        'qr_payload': pairing.qr_payload('https://responder.example.test', '7K3QM-9XD2P', INSTALL['B']),
    }


def webhook_vectors():
    a = KEYS['A']
    env = webhooks.envelope(event_type='alert.raised', tenant='org-1', data={'alert_id': 'a-1', 'severity': 'high'},
                            sender=INSTALL['A'], event_id='77777777-7777-4777-8777-777777777777', occurred_at=NOW)
    body = webhooks.body_of(env)
    conn = '66666666-6666-4666-8666-666666666666'
    headers = webhooks.sign(a, connection_id=conn, event_id=env['id'], sender=INSTALL['A'], receiver=INSTALL['B'],
                            body=body, timestamp=NOW)
    return {'notice': NOTICE, 'now': NOW, 'signer': 'A', 'sender': INSTALL['A'], 'receiver': INSTALL['B'],
            'connection_id': conn, 'body_utf8': body.decode(),
            'signing_string': webhooks.signing_string(connection_id=conn, event_id=env['id'], timestamp=NOW,
                                                      sender=INSTALL['A'], receiver=INSTALL['B'], body=body),
            'headers': headers,
            'verify': [{'at': NOW + 119, 'expect': 'valid'}, {'at': NOW + 121, 'expect': 'expired'},
                       {'at': NOW, 'mutate_body': True, 'expect': 'invalid_signature'},
                       {'at': NOW, 'receiver': INSTALL['A'], 'expect': 'invalid_signature'}],
            'backoff_ceiling_seconds': [min(3600, 30 * 2 ** n) for n in range(10)]}


def audit_vectors():
    records = [
        {'seq': 1, 'ts_us': NOW * 1_000_000, 'operation': 'pairing.invitation_created', 'result': 'ok',
         'connection_id': '', 'tenant': '', 'scopes': [], 'actor': 'user:1', 'initiating_app': INSTALL['A'],
         'correlation_id': 'c-1', 'detail': {}},
        {'seq': 2, 'ts_us': NOW * 1_000_000 + 1, 'operation': 'token.issued', 'result': 'ok',
         'connection_id': '66666666-6666-4666-8666-666666666666', 'tenant': '', 'scopes': ['customers:read'],
         'actor': 'app:' + INSTALL['B'], 'initiating_app': INSTALL['B'], 'correlation_id': 'c-2', 'detail': {}},
    ]
    chain, prev = [], audit.GENESIS
    for r in records:
        h = audit.entry_hash(prev, r)
        chain.append({'record': r, 'prev_hash': prev, 'hash': h})
        prev = h
    return {'genesis': audit.GENESIS, 'chain': chain}


def jwks_vectors():
    a, c = KEYS['A'], KEYS['C']
    doc = keys.endorsed_jwks(a, [keys.public_jwk(a), keys.public_jwk(c)], INSTALL['A'],
                             '44444444-4444-4444-8444-444444444444', now=NOW)
    return {'notice': NOTICE, 'now': NOW, 'endorser': 'A', 'issuer': INSTALL['A'],
            'connection_id': '44444444-4444-4444-8444-444444444444', 'document': doc,
            'keys_sha256': keys.keys_digest(doc['keys']),
            'expect': {'trusted_A': 'valid', 'trusted_C_only': 'invalid_signature',
                       'trusted_B_only': 'invalid_signature'}}


# --- protocol revision 1.1 (PROTOCOL-1.1.md) -------------------------------------------
# New files only; the v1 files above are never touched by this section.

QC_NOTICE = 'TEST-ONLY KEYS AND NONCES (agit8or-connect/1.1). Never use outside conformance tests.'
QC_A_BASE = 'https://initiator.example.test'
QC_B_BASE = 'https://responder.example.test'
QC_REDIRECT = QC_A_BASE + '/agit8or-connect/qc-callback'
QC_ATTEMPT = '44444444-4444-4444-8444-444444444444'
QC_B_CONN = '66666666-6666-4666-8666-666666666666'
QC_REQUEST_ID = '55555555-5555-4555-8555-555555555555'
QC_A_APP = {'type': 'clientst0r', 'version': '3.17.0', 'display_name': 'MSP A', 'installation_id': INSTALL['A']}
QC_B_APP = {'type': 'reference-peer', 'version': '1.1.0', 'display_name': 'Responder B',
            'installation_id': INSTALL['B']}
QC_A_EGRESS = [{'net': '203.0.113.10/32', 'note': 'office NAT'}]
QC_B_EGRESS = [{'net': '198.51.100.0/28', 'note': 'data centre'}, {'net': '2001:db8:10::/48', 'note': ''}]
QC_SCOPES = ['customers:read', 'events:publish']


def qc_value(name: str) -> str:
    """A fixed 256-bit TEST-ONLY value, base64url (43 characters)."""
    return b64url(hashlib.sha256(f'agit8or-connect/1.1 TEST-ONLY {name}'.encode()).digest())


QC_VERIFIER = qc_value('pkce-verifier')
QC_CODE = qc_value('authorization-code')
QC_STATE = qc_value('state')
QC_NONCE = qc_value('nonce')


def resign(key, token: str, *, header=None, claims=None, drop=()):
    """A negative case: the token's header/claims with changes, signed by `key`."""
    h = dict(unverified_header(token), **(header or {}))
    c = dict(unverified_payload(token), **(claims or {}))
    for k in drop:
        c.pop(k, None)
    return sign_compact(key, h, c)


def tamper(token: str) -> str:
    return token[:-4] + ('AAAA' if not token.endswith('AAAA') else 'BBBB')


def qc_messages():
    a, b = KEYS['A'], KEYS['B']
    inv, inv_claims = qc.build_invitation(
        a, initiator_app=QC_A_APP, responder_origin=QC_B_BASE, attempt=QC_ATTEMPT, base=QC_A_BASE,
        redirect_uri=QC_REDIRECT, egress=QC_A_EGRESS, requested_scopes=QC_SCOPES,
        code_challenge=qc.pkce_challenge(QC_VERIFIER), nonce=QC_NONCE, now=NOW, jti='qc-invitation-jti-0001')
    acc = qc.build_accept(b, responder_app=QC_B_APP, invitation=inv_claims, invitation_jws=inv,
                          connection_id=QC_B_CONN, base=QC_B_BASE, egress=QC_B_EGRESS, code=QC_CODE, now=NOW + 30)
    acc_claims = unverified_payload(acc)
    exch_url = QC_B_BASE + qc.EXCHANGE_PATH
    exch, exch_claims = qc.build_exchange(
        a, invitation=inv_claims, accept=acc_claims, accept_jws=acc, code=QC_CODE, code_verifier=QC_VERIFIER,
        initiator_app=QC_A_APP, discovery_url=QC_A_BASE + '/.well-known/agit8or-connect',
        requested_scopes=QC_SCOPES, proposed_tenants=[{'id': 'org-1', 'label': 'Customer One'}], now=NOW + 40,
        jti='qc-exchange-jti-0001')
    dpop = tokens.build_dpop_proof(a, 'POST', exch_url, now=NOW + 40, jti='qc-dpop-exchange-0001')
    ack = pairing.build_ack(b, responder_app=QC_B_APP, initiator_installation=INSTALL['A'],
                            request_id=QC_REQUEST_ID, request_jti=exch_claims['jti'], connection_id=QC_B_CONN,
                            now=NOW + 40)
    return dict(inv=inv, inv_claims=inv_claims, acc=acc, acc_claims=acc_claims, exch=exch,
                exch_claims=exch_claims, exch_url=exch_url, dpop=dpop, ack=ack)


def qc_invitation_vectors():
    a, c = KEYS['A'], KEYS['C']
    m = qc_messages()
    inv = m['inv']
    v1_request = pairing_vectors()['request']['jws']
    cases = [
        {'name': 'valid', 'jws': inv, 'at': NOW + 10, 'expect': 'valid'},
        {'name': 'valid_at_skew_edge', 'jws': inv, 'at': NOW + 600 + 119, 'expect': 'valid'},
        {'name': 'expired', 'jws': inv, 'at': NOW + 600 + 120, 'expect': 'invitation_expired'},
        {'name': 'replayed', 'jws': inv, 'at': NOW + 10, 'replay_twice': True, 'expect': 'invitation_used'},
        {'name': 'wrong_audience', 'jws': inv, 'at': NOW + 10, 'responder_origin': 'https://other.example.test',
         'expect': 'wrong_audience'},
        {'name': 'wrong_responder_installation',
         'jws': resign(a, inv, claims={'responder_installation': INSTALL['A']}), 'at': NOW + 10,
         'expect': 'wrong_audience'},
        {'name': 'bad_signature', 'jws': tamper(inv), 'at': NOW + 10, 'expect': 'invalid_signature'},
        {'name': 'header_key_substituted', 'jws': resign(a, inv, header={'jwk': keys.public_jwk(c),
                                                                        'kid': keys.thumbprint(c)}),
         'at': NOW + 10, 'expect': 'invalid_signature'},
        {'name': 'lifetime_too_long', 'jws': resign(a, inv, claims={'exp': NOW + 900}), 'at': NOW + 10,
         'expect': 'invalid_request'},
        {'name': 'downgrade_protocol_v1', 'jws': resign(a, inv, claims={'protocol': 'agit8or-connect/1'}),
         'at': NOW + 10, 'expect': 'unsupported_version'},
        {'name': 'downgrade_extensions_stripped', 'jws': resign(a, inv, claims={'extensions': {}}),
         'at': NOW + 10, 'expect': 'invalid_request'},
        {'name': 'redirect_other_origin',
         'jws': resign(a, inv, claims={'redirect_uri': 'https://evil.example.test/agit8or-connect/qc-callback'}),
         'at': NOW + 10, 'expect': 'invalid_redirect_uri'},
        {'name': 'redirect_with_query', 'jws': resign(a, inv, claims={'redirect_uri': QC_REDIRECT + '?x=1'}),
         'at': NOW + 10, 'expect': 'invalid_redirect_uri'},
        {'name': 'base_loopback', 'jws': resign(a, inv, claims={'base': 'https://127.0.0.1',
                                                               'redirect_uri': 'https://127.0.0.1/cb'}),
         'at': NOW + 10, 'expect': 'invalid_base'},
        {'name': 'egress_allow_all', 'jws': resign(a, inv, claims={'egress': [{'net': '0.0.0.0/0', 'note': ''}]}),
         'at': NOW + 10, 'expect': 'invalid_egress'},
        {'name': 'egress_loopback', 'jws': resign(a, inv, claims={'egress': [{'net': '127.0.0.1/32', 'note': ''}]}),
         'at': NOW + 10, 'expect': 'invalid_egress'},
        {'name': 'egress_not_canonical',
         'jws': resign(a, inv, claims={'egress': [{'net': '2001:DB8::1/128', 'note': ''}]}),
         'at': NOW + 10, 'expect': 'invalid_egress'},
        {'name': 'egress_empty', 'jws': resign(a, inv, claims={'egress': []}), 'at': NOW + 10,
         'expect': 'invalid_egress'},
        {'name': 'plain_method', 'jws': resign(a, inv, claims={'code_challenge_method': 'plain'}), 'at': NOW + 10,
         'expect': 'invalid_request'},
        {'name': 'v1_pairing_request_presented', 'jws': v1_request, 'at': NOW + 10, 'expect': 'invalid_request'},
    ]
    return {
        'notice': QC_NOTICE, 'now': NOW, 'signer': 'A', 'responder_origin': QC_B_BASE,
        'responder_installation': INSTALL['B'],
        'pkce': {'code_verifier': QC_VERIFIER, 'code_challenge': qc.pkce_challenge(QC_VERIFIER)},
        'nonce': QC_NONCE, 'state': QC_STATE,
        'invitation': {'jws': inv, 'claims': m['inv_claims'], 'length': len(inv)},
        'authorization_url': qc.authorization_url(QC_B_BASE + qc.AUTHORIZE_ENTRY_PATH, inv, QC_STATE),
        'cases': cases,
        'v1_verifier_refuses_invitation': {'jws': inv, 'responder_installation': INSTALL['B'], 'at': NOW + 10,
                                           'expect': 'invalid_request'},
        'net_normalization': [{'in': i, 'out': qc.normalize_net(i)} for i in (
            '203.0.113.10', '203.0.113.10/32', '198.51.100.0/28', '2001:DB8:0:0:0:0:0:1', '2001:db8:0:0:1:0:0:1',
            '2001:0:0:1:0:0:0:1', '1:0:0:2:0:0:3:4', '2001:db8:0:1:1:1:1:1', '64:ff9b::1.2.3.4',
            '2001:db8:10::/48', '1:2:3:4:5:6:7::', '::1:2:3:4:5:6:7', '01:2::3', '2001:db8::0:1', '0:0:0:0:0:0:0:2',
            '2001:db8:0:0:1:1:0:0', '2001:db8:1::/64')],
        'net_malformed': ['', ' 203.0.113.10', '203.0.113.010', '203.0.113.10/24', '203.0.113.256',
                          'fe80::1%eth0', '::ffff:203.0.113.10', '2001:db8::/129', 'example.test',
                          '203.0.113.0/255.255.255.0', '203.0.113.10/032', '1::2::3', '00001::', '1:2:3:4:5:6:7:8:9',
                          '2001:db8::/64 ', '::ffff:cb00:710a', '1.2.3.4.5', '12345::', ':1::', '1:::2'],
        'net_refused': ['0.0.0.0/0', '::/0', '10.0.0.0/8', '2001:db8::/31', '127.0.0.1/32', '169.254.169.254/32',
                        '0.0.0.0/32', '224.0.0.1/32', '255.255.255.255/32', '::1/128', 'fe80::1/128', 'ff02::1/128',
                        'fd00:ec2::254/128', '100.100.100.200/32', '2001:DB8::1/128'],
        'net_private': [{'net': n, 'private': qc.is_private_net(n)} for n in (
            '10.1.2.3/32', '172.16.0.0/16', '192.168.1.0/24', '100.64.0.1/32', 'fd12:3456::/48',
            '203.0.113.10/32', '2001:db8::1/128', '172.32.0.1/32')],
        'base_valid': ['https://initiator.example.test', 'https://initiator.example.test/psa',
                       'https://203.0.113.10', 'https://[2001:db8::1]', 'https://10.0.0.5/app'],
        'base_invalid': ['http://initiator.example.test', 'https://initiator.example.test/',
                         'https://Initiator.example.test', 'https://initiator.example.test:443',
                         'https://initiator.example.test:8443', 'https://u@initiator.example.test',
                         'https://initiator.example.test?a=1', 'https://initiator.example.test#f',
                         'https://initiator.example.test/a/../b', 'https://initiator.example.test/%41',
                         'https://127.0.0.1', 'https://169.254.169.254', 'https://[::1]',
                         'https://[2001:DB8::1]', 'https://localhost', 'https://app.localhost',
                         'https://203.0.113.010', 'https://initiator.example.test:0443'],
        'redirect_checks': [
            {'redirect_uri': QC_REDIRECT, 'base': QC_A_BASE, 'expect': 'valid'},
            {'redirect_uri': QC_A_BASE + '/psa/cb', 'base': QC_A_BASE + '/psa', 'expect': 'valid'},
            {'redirect_uri': QC_A_BASE, 'base': QC_A_BASE, 'expect': 'invalid_redirect_uri'},
            {'redirect_uri': 'https://initiator.example.test:8443/cb', 'base': QC_A_BASE,
             'expect': 'invalid_redirect_uri'},
            {'redirect_uri': 'http://initiator.example.test/cb', 'base': QC_A_BASE,
             'expect': 'invalid_redirect_uri'},
            {'redirect_uri': QC_A_BASE + '/cb#x', 'base': QC_A_BASE, 'expect': 'invalid_redirect_uri'}],
    }


def qc_exchange_vectors():
    a, b, c = KEYS['A'], KEYS['B'], KEYS['C']
    m = qc_messages()
    inv, inv_claims, acc, exch = m['inv'], m['inv_claims'], m['acc'], m['exch']
    url = m['exch_url']
    code_expires = NOW + 30 + qc.CODE_TTL
    second, _ = qc.build_exchange(
        a, invitation=inv_claims, accept=m['acc_claims'], accept_jws=acc, code=QC_CODE, code_verifier=QC_VERIFIER,
        initiator_app=QC_A_APP, discovery_url=QC_A_BASE + '/.well-known/agit8or-connect',
        requested_scopes=QC_SCOPES, proposed_tenants=[{'id': 'org-1', 'label': 'Customer One'}], now=NOW + 45,
        jti='qc-exchange-jti-0002')
    second_dpop = tokens.build_dpop_proof(a, 'POST', url, now=NOW + 45, jti='qc-dpop-exchange-0002')
    wrong_verifier = qc_value('another-pkce-verifier')
    by_c, _ = qc.build_exchange(
        c, invitation=inv_claims, accept=m['acc_claims'], accept_jws=acc, code=QC_CODE, code_verifier=QC_VERIFIER,
        initiator_app=QC_A_APP, discovery_url=QC_A_BASE + '/.well-known/agit8or-connect',
        requested_scopes=QC_SCOPES, now=NOW + 40, jti='qc-exchange-jti-0003')
    d = {'dpop': m['dpop'], 'at': NOW + 41}
    exchange_cases = [
        dict(d, name='valid', jws=exch, expect='valid'),
        dict(d, name='dpop_replayed', jws=exch, replay_twice=True, expect='replayed'),
        {'name': 'code_reused', 'sequence': [{'jws': exch, 'dpop': m['dpop'], 'at': NOW + 41},
                                             {'jws': second, 'dpop': second_dpop, 'at': NOW + 46}],
         'expect': ['valid', 'code_used']},
        dict(d, name='code_expired', jws=exch, at=code_expires, expect='code_expired'),
        dict(d, name='exchange_expired', jws=exch, at=NOW + 40 + 60 + 120, code_expires_at=NOW + 10000,
             expect='expired'),
        dict(d, name='wrong_audience', jws=exch, responder_installation=INSTALL['A'], expect='wrong_audience'),
        dict(d, name='wrong_verifier', jws=resign(a, exch, claims={'code_verifier': wrong_verifier}),
             expect='pkce_mismatch'),
        dict(d, name='unknown_code', jws=resign(a, exch, claims={'code': qc_value('other-code')}),
             expect='invalid_grant'),
        dict(d, name='signed_by_other_key', jws=by_c, expect='key_mismatch'),
        dict(d, name='bad_signature', jws=tamper(exch), expect='invalid_signature'),
        dict(d, name='accept_hash_mismatch', jws=resign(a, exch, claims={'accept_sha256': sha256_hex('x')}),
             expect='wrong_attempt'),
        dict(d, name='connection_key_substituted', jws=resign(a, exch, claims={'connection_key': keys.public_jwk(c)}),
             expect='key_mismatch'),
        dict(d, name='downgrade_protocol_v1', jws=resign(a, exch, claims={'protocol': 'agit8or-connect/1'}),
             expect='unsupported_version'),
        dict(d, name='dpop_signed_by_other_key',
             dpop=tokens.build_dpop_proof(c, 'POST', url, now=NOW + 40, jti='qc-dpop-exchange-0003'),
             jws=exch, expect='invalid_dpop_proof'),
        dict(d, name='dpop_for_other_url',
             dpop=tokens.build_dpop_proof(a, 'POST', QC_B_BASE + '/connect/v1/pairing/requests', now=NOW + 40,
                                          jti='qc-dpop-exchange-0004'),
             jws=exch, expect='invalid_dpop_proof'),
        dict(d, name='dpop_missing', dpop='', jws=exch, expect='invalid_dpop_proof'),
        dict(d, name='v1_pairing_request_presented', jws=pairing_vectors()['request']['jws'],
             expect='invalid_request'),
    ]
    accept_cases = [
        {'name': 'valid', 'jws': acc, 'at': NOW + 35, 'expect': 'valid'},
        {'name': 'expired', 'jws': acc, 'at': NOW + 30 + 600 + 120, 'expect': 'expired'},
        {'name': 'bad_signature', 'jws': tamper(acc), 'at': NOW + 35, 'expect': 'invalid_signature'},
        {'name': 'wrong_audience', 'jws': resign(b, acc, claims={'aud': INSTALL['B']}), 'at': NOW + 35,
         'expect': 'wrong_audience'},
        {'name': 'other_invitation', 'jws': resign(b, acc, claims={'invitation_sha256': sha256_hex('x')}),
         'at': NOW + 35, 'expect': 'wrong_attempt'},
        {'name': 'code_swapped', 'jws': acc, 'code': qc_value('other-code'), 'at': NOW + 35,
         'expect': 'invalid_grant'},
        {'name': 'other_destination', 'jws': resign(b, acc, claims={'base': 'https://elsewhere.example.test'}),
         'at': NOW + 35, 'expect': 'destination_mismatch'},
        {'name': 'egress_allow_all', 'jws': resign(b, acc, claims={'egress': [{'net': '::/0', 'note': ''}]}),
         'at': NOW + 35, 'expect': 'invalid_egress'},
        {'name': 'downgrade_protocol_v1', 'jws': resign(b, acc, claims={'protocol': 'agit8or-connect/1'}),
         'at': NOW + 35, 'expect': 'unsupported_version'},
        {'name': 'v1_ack_presented', 'jws': m['ack'], 'at': NOW + 35, 'expect': 'invalid_request'},
    ]
    return {
        'notice': QC_NOTICE, 'now': NOW, 'initiator_signer': 'A', 'responder_signer': 'B',
        'invitation_jws': inv, 'code': QC_CODE, 'code_sha256': sha256_hex(QC_CODE), 'state': QC_STATE,
        'code_verifier': QC_VERIFIER, 'code_expires_at': code_expires,
        'responder_installation': INSTALL['B'], 'exchange_url': url,
        'accept': {'jws': acc, 'claims': m['acc_claims'], 'connection_id': QC_B_CONN, 'base': QC_B_BASE,
                   'egress': QC_B_EGRESS, 'built_at': NOW + 30},
        'authorization_response_url': qc.authorization_response_url(QC_REDIRECT, state=QC_STATE, code=QC_CODE,
                                                                    accept=acc),
        'authorization_error_url': qc.authorization_response_url(QC_REDIRECT, state=QC_STATE, error='access_denied'),
        'accept_cases': accept_cases,
        'exchange': {'jws': exch, 'claims': m['exch_claims'], 'dpop': m['dpop'], 'built_at': NOW + 40,
                     'dpop_jti': 'qc-dpop-exchange-0001',
                     'request_body': {'exchange': exch}},
        'exchange_cases': exchange_cases,
        # The exchange header has no `jwk`, so a v1 pairing-request verifier refuses it before the typ check.
        'v1_verifier_refuses_exchange': {'jws': exch, 'responder_installation': INSTALL['B'], 'at': NOW + 41,
                                         'expect': 'invalid_signature'},
        'ack': {'signer': 'B', 'jws': m['ack'], 'request_id': QC_REQUEST_ID,
                'note': 'The unchanged v1 ack (typ agit8or-pairing-ack+jwt); request_jti = exchange jti.'},
    }


def qc_transcript_vectors():
    m = qc_messages()
    th = qc.transcript_from_messages(m['inv'], m['acc'], m['exch'])
    base = dict(invitation_jws=m['inv'], accept_jws=m['acc'], exchange_jws=m['exch'],
                initiator_installation=INSTALL['A'], initiator_jkt=keys.thumbprint(KEYS['A']),
                initiator_egress=['203.0.113.10/32'], responder_installation=INSTALL['B'],
                responder_jkt=keys.thumbprint(KEYS['B']), responder_egress=['198.51.100.0/28', '2001:db8:10::/48'],
                destination_host='responder.example.test', destination_port=443)
    assert qc.transcript_hash(**base) == th
    mutations = []
    for name, change in (('initiator_key_substituted', {'initiator_jkt': keys.thumbprint(KEYS['C'])}),
                         ('responder_key_substituted', {'responder_jkt': keys.thumbprint(KEYS['C'])}),
                         ('initiator_egress_changed', {'initiator_egress': ['203.0.113.11/32']}),
                         ('responder_egress_changed', {'responder_egress': ['198.51.100.0/28']}),
                         ('destination_host_changed', {'destination_host': 'responder2.example.test'}),
                         ('destination_port_changed', {'destination_port': 8443})):
        t = qc.transcript_hash(**dict(base, **change))
        mutations.append({'name': name, 'change': change, 'transcript_hash': t, 'sas': qc.sas(t)})
    canonical_input = canonical_json({
        'v': 'agit8or-connect/1.1 qc-transcript', 'invitation_sha256': sha256_hex(m['inv']),
        'accept_sha256': sha256_hex(m['acc']), 'exchange_sha256': sha256_hex(m['exch']),
        'initiator': {'installation_id': INSTALL['A'], 'jkt': base['initiator_jkt'],
                      'egress': base['initiator_egress']},
        'responder': {'installation_id': INSTALL['B'], 'jkt': base['responder_jkt'],
                      'egress': base['responder_egress']},
        'destination': {'host': 'responder.example.test', 'port': 443}})
    return {'notice': QC_NOTICE, 'inputs': {k: v for k, v in base.items() if not k.endswith('_jws')},
            'invitation_jws': m['inv'], 'accept_jws': m['acc'], 'exchange_jws': m['exch'],
            'canonical_input': canonical_input, 'transcript_hash': th, 'sas': qc.sas(th),
            'v1_sas_of_same_hash_note': 'SAS uses the v1 function (prefix "agit8or-connect/1 sas\\n").',
            'mutations': mutations}


def qc_discovery_vectors():
    url = QC_B_BASE + '/.well-known/agit8or-connect'
    v11 = qc.extend_discovery_document({'protocol': 'agit8or-connect', 'versions': ['1'],
                                        'app': {'type': 'reference-peer', 'installation_id': INSTALL['B']},
                                        'endpoints': {}}, QC_B_BASE)
    m = qc_messages()
    signed = m['acc_claims']['extensions']
    cases = [
        {'name': 'v1_peer', 'discovery': {'versions': ['1'], 'endpoints': {}}, 'negotiated': {}, 'flow': 'code'},
        {'name': 'v1_1_peer', 'discovery': v11, 'negotiated': {'qc-bootstrap': 1, 'qc-diagnostics': 1,
                                                                'qc-source-binding': 1},
         'flow': 'qc-bootstrap/1'},
        {'name': 'bootstrap_without_source_binding',
         'discovery': dict(v11, extensions={'qc-bootstrap': 1, 'qc-diagnostics': 1}),
         'negotiated': {'qc-diagnostics': 1}, 'flow': 'code'},
        {'name': 'future_versions_only', 'discovery': dict(v11, extensions={'qc-bootstrap': [2, 3],
                                                                           'qc-source-binding': 2}),
         'negotiated': {}, 'flow': 'code'},
        {'name': 'list_form_and_unknown_extension',
         'discovery': dict(v11, extensions={'qc-bootstrap': [1, 2], 'qc-source-binding': [1],
                                            'qc-diagnostics': 1, 'x-future': 7}),
         'negotiated': {'qc-bootstrap': 1, 'qc-diagnostics': 1, 'qc-source-binding': 1}, 'flow': 'qc-bootstrap/1'},
        {'name': 'malformed_values_ignored',
         'discovery': dict(v11, extensions={'qc-bootstrap': True, 'qc-source-binding': '1', 'qc-diagnostics': 0}),
         'negotiated': {}, 'flow': 'code'},
        {'name': 'endpoint_on_other_origin',
         'discovery': dict(v11, endpoints=dict(v11['endpoints'], qc_exchange='https://evil.example.test/x')),
         'negotiated': {'qc-diagnostics': 1, 'qc-source-binding': 1}, 'flow': 'code'},
        {'name': 'endpoint_missing',
         'discovery': dict(v11, endpoints={k: v for k, v in v11['endpoints'].items() if k != 'qc_probe'}),
         'negotiated': {'qc-bootstrap': 1, 'qc-source-binding': 1}, 'flow': 'qc-bootstrap/1'},
    ]
    for cs in cases:
        got = qc.negotiate_extensions(qc.advertised_extensions(cs['discovery'], url))
        assert got == cs['negotiated'] and qc.pairing_flow(got) == cs['flow'], (cs['name'], got)
    downgrade = [
        {'name': 'same', 'signed': signed, 'discovered': v11, 'expect': 'valid'},
        {'name': 'discovery_stripped_to_v1', 'signed': signed,
         'discovered': {'versions': ['1'], 'endpoints': {}}, 'expect': 'downgrade_detected'},
        {'name': 'discovery_dropped_diagnostics', 'signed': signed,
         'discovered': dict(v11, extensions={'qc-bootstrap': 1, 'qc-source-binding': 1}),
         'expect': 'downgrade_detected'},
        {'name': 'unknown_signed_extension_ignored', 'signed': dict(signed, **{'x-future': [1]}),
         'discovered': v11, 'expect': 'valid'},
    ]
    return {'notice': QC_NOTICE, 'discovery_url': url, 'ours': qc.signed_extensions(),
            'v1_1_document_members': {k: v11[k] for k in ('revision', 'extensions')},
            'v1_1_endpoints': qc.discovery_endpoints(QC_B_BASE), 'negotiation': cases,
            'downgrade': downgrade}


def qc_diagnostics_vectors():
    a, b, c = KEYS['A'], KEYS['B'], KEYS['C']
    url = QC_B_BASE + qc.PROBE_PATH
    client_id = QC_B_CONN
    at, at_claims = tokens.issue_access_token(b, issuer=INSTALL['B'], client_id=client_id, scopes=['connection:read'],
                                              jkt=keys.thumbprint(a), now=NOW, jti='qc-probe-token-0001')
    proof = tokens.build_dpop_proof(a, 'POST', url, now=NOW, jti='qc-dpop-probe-0001', access_token=at)
    nonce = qc_value('probe-nonce')
    resp = qc.build_probe_response(observed_source='203.0.113.10', server_time=NOW, connection_state='active',
                                   source_check='ok', peer_reached_at=NOW - 60, nonce=nonce)
    return {
        'notice': QC_NOTICE, 'now': NOW, 'probe_url': url, 'issuer': INSTALL['B'],
        'access_token': {'jws': at, 'claims': at_claims, 'signer': 'B'},
        'request': {'method': 'POST', 'dpop': proof, 'body': qc.probe_request_body(nonce), 'signer': 'A'},
        'verify': [
            {'name': 'valid', 'dpop': proof, 'at': NOW + 5, 'expect': 'valid'},
            {'name': 'dpop_replayed', 'dpop': proof, 'at': NOW + 5, 'replay_twice': True, 'expect': 'replayed'},
            {'name': 'dpop_signed_by_other_key', 'at': NOW + 5, 'expect': 'invalid_dpop_proof',
             'dpop': tokens.build_dpop_proof(c, 'POST', url, now=NOW, jti='qc-dpop-probe-0002', access_token=at)},
            {'name': 'dpop_without_ath', 'at': NOW + 5, 'expect': 'invalid_dpop_proof',
             'dpop': tokens.build_dpop_proof(a, 'POST', url, now=NOW, jti='qc-dpop-probe-0003')},
            {'name': 'dpop_for_exchange_url', 'at': NOW + 5, 'expect': 'invalid_dpop_proof',
             'dpop': tokens.build_dpop_proof(a, 'POST', QC_B_BASE + qc.EXCHANGE_PATH, now=NOW,
                                             jti='qc-dpop-probe-0004', access_token=at)},
            {'name': 'dpop_too_old', 'dpop': proof, 'at': NOW + 121, 'expect': 'invalid_dpop_proof'},
        ],
        'response': resp,
        'response_invalid': [
            dict(resp, observed_source='203.0.113.010'), dict(resp, observed_source='2001:DB8::1'),
            dict(resp, checks={'source': 'maybe', 'token': 'ok'}), dict(resp, server_time='1767225600'),
            dict(resp, nonce='other'),
        ],
        'source_not_authorised_error': {'status': 403, 'body': {'error': {
            'code': 'source_not_authorised', 'message': 'This address is not authorised for Agit8or Connect.',
            'correlation_id': '88888888-8888-4888-8888-888888888888'}}},
    }


def qc_files():
    return {
        'qc-invitation.json': qc_invitation_vectors(),
        'qc-exchange.json': qc_exchange_vectors(),
        'qc-transcript.json': qc_transcript_vectors(),
        'qc-discovery.json': qc_discovery_vectors(),
        'qc-diagnostics.json': qc_diagnostics_vectors(),
    }


def build():
    return {
        'keys.json': {'notice': NOTICE, 'keys': key_section(), 'installations': INSTALL},
        'canonical-json.json': {'cases': canonical_vectors()},
        'tokens.json': token_vectors(),
        'pairing.json': pairing_vectors(),
        'webhooks.json': webhook_vectors(),
        'audit-chain.json': audit_vectors(),
        'jwks.json': jwks_vectors(),
        **qc_files(),
    }


def main(argv):
    files = build()
    os.makedirs(OUT, exist_ok=True)
    differ = []
    for name, content in files.items():
        text = json.dumps(content, indent=2, ensure_ascii=False, sort_keys=True) + '\n'
        path = os.path.join(OUT, name)
        if '--check' in argv:
            try:
                with open(path, encoding='utf-8') as f:
                    if f.read() != text:
                        differ.append(name)
            except FileNotFoundError:
                differ.append(name)
        else:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(text)
    if differ:
        print('test vectors out of date: ' + ', '.join(differ))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
