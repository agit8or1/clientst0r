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
from agit8or_connect.canonical import b64url, canonical_json, sha256_hex

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


def build():
    return {
        'keys.json': {'notice': NOTICE, 'keys': key_section(), 'installations': INSTALL},
        'canonical-json.json': {'cases': canonical_vectors()},
        'tokens.json': token_vectors(),
        'pairing.json': pairing_vectors(),
        'webhooks.json': webhook_vectors(),
        'audit-chain.json': audit_vectors(),
        'jwks.json': jwks_vectors(),
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
