"""Protocol revision 1.1 vectors (docs/agit8or-connect/test-vectors/qc-*.json).
The TypeScript SDK runs the same files (sdk/typescript/agit8or-connect/test/qc.test.ts)."""
import json
import os
import unittest

from agit8or_connect import keys, pairing, quick_connect as qc, tokens
from agit8or_connect.canonical import canonical_json, sha256_hex
from agit8or_connect.errors import ConnectError
from agit8or_connect.jws import unverified_header, unverified_payload
from agit8or_connect.replay import MemoryReplayStore

DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'docs', 'agit8or-connect', 'test-vectors')
V1_FILES = ('keys.json', 'canonical-json.json', 'tokens.json', 'pairing.json', 'webhooks.json', 'audit-chain.json',
            'jwks.json')
# SHA-256 of the v1 vector files as published up to v3.17.746. Protocol 1.1 must never change them.
V1_DIGESTS = {
    'keys.json': 'd15eb79cce935aaa49b743ab7026bab2e64dae9f2266e55e0c8abe9599cbef71',
    'canonical-json.json': '78f67c1053cb630e22e650858a560f60686699af50c916aa28afa58d2c89631b',
    'tokens.json': '03383d848017fea0898e30dd023f321f1c91bd52d1598bc55a2b8c7368906bc1',
    'pairing.json': '4bada6fa498bdcf339b63eccb06316ebed40c266d8463d23690aab4f7baaae24',
    'webhooks.json': 'da32fe4a20860bcc321a752fa5a4092dae493c41d13bc6379f52b3444f9fa4d4',
    'audit-chain.json': '6544ffb958a4de8e017486a113cdd6055cd7ab76353b0f9ad6cdaf92e6bbc4d3',
    'jwks.json': 'ca2e9988695145e07403b54a4bd8db71e8bef99e1cc3b57d5d279dfb76606f51',
}


def load(name):
    with open(os.path.join(DIR, name), encoding='utf-8') as f:
        return json.load(f)


KEYS = load('keys.json')


def priv(name):
    return keys.private_key_from_seed(bytes.fromhex(KEYS['keys'][name]['seed_hex']))


def code_of(fn):
    try:
        fn()
        return 'valid'
    except ConnectError as e:
        return e.code


class InvitationVectors(unittest.TestCase):
    v = load('qc-invitation.json')

    def test_rebuild_byte_for_byte(self):
        v, c = self.v, self.v['invitation']['claims']
        self.assertEqual(qc.pkce_challenge(v['pkce']['code_verifier']), v['pkce']['code_challenge'])
        jws, claims = qc.build_invitation(
            priv('A'), initiator_app=c['app'], responder_origin=c['aud'], attempt=c['attempt'], base=c['base'],
            redirect_uri=c['redirect_uri'], egress=c['egress'], requested_scopes=c['requested_scopes'],
            code_challenge=c['code_challenge'], nonce=c['nonce'], now=c['iat'], jti=c['jti'])
        self.assertEqual(jws, v['invitation']['jws'])
        self.assertEqual(claims, c)
        self.assertLessEqual(len(jws), qc.MAX_INVITATION_LENGTH)
        self.assertEqual(qc.authorization_url(v['responder_origin'] + qc.AUTHORIZE_ENTRY_PATH, jws, v['state']),
                         v['authorization_url'])
        q = qc.parse_query(v['authorization_url'])
        self.assertEqual(q, {'invitation': jws, 'state': v['state']})

    def test_cases(self):
        v = self.v
        for case in v['cases']:
            store = MemoryReplayStore(clock=lambda: case['at'])

            def run():
                for _ in range(2 if case.get('replay_twice') else 1):
                    qc.verify_invitation(case['jws'], responder_origin=case.get('responder_origin',
                                                                                 v['responder_origin']),
                                         responder_installation=v['responder_installation'], replay=store,
                                         now=case['at'])
            self.assertEqual(code_of(run), case['expect'], case['name'])

    def test_v1_verifier_refuses_invitation(self):
        x = self.v['v1_verifier_refuses_invitation']
        self.assertEqual(code_of(lambda: pairing.verify_request(
            x['jws'], responder_installation=x['responder_installation'], replay=MemoryReplayStore(),
            now=x['at'])), x['expect'])

    def test_addresses(self):
        v = self.v
        for n in v['net_normalization']:
            self.assertEqual(qc.normalize_net(n['in']), n['out'], n)
            self.assertEqual(qc.check_net(n['out']), n['out'])
        for bad in v['net_malformed']:
            self.assertEqual(code_of(lambda: qc.normalize_net(bad)), 'invalid_egress', bad)
        for bad in v['net_refused']:
            self.assertEqual(code_of(lambda: qc.check_net(bad)), 'invalid_egress', bad)
        for p in v['net_private']:
            self.assertEqual(qc.is_private_net(p['net']), p['private'], p)

    def test_urls(self):
        v = self.v
        for u in v['base_valid']:
            self.assertEqual(qc.check_base(u), u)
        for u in v['base_invalid']:
            self.assertEqual(code_of(lambda: qc.check_base(u)), 'invalid_base', u)
        for r in v['redirect_checks']:
            self.assertEqual(code_of(lambda: qc.check_redirect_uri(r['redirect_uri'], r['base'])), r['expect'], r)


class ExchangeVectors(unittest.TestCase):
    v = load('qc-exchange.json')
    inv = load('qc-invitation.json')

    def invitation(self):
        claims, jwk = qc.verify_invitation(self.v['invitation_jws'], responder_origin=self.inv['responder_origin'],
                                           replay=MemoryReplayStore(), now=self.inv['now'] + 10)
        return claims, jwk

    def test_accept_rebuild_and_cases(self):
        v = self.v
        inv_claims, _ = self.invitation()
        a = v['accept']
        acc = qc.build_accept(priv('B'), responder_app=a['claims']['app'], invitation=inv_claims,
                              invitation_jws=v['invitation_jws'], connection_id=a['connection_id'], base=a['base'],
                              egress=a['egress'], code=v['code'], now=a['built_at'])
        self.assertEqual(acc, a['jws'])
        self.assertEqual(unverified_payload(acc), a['claims'])
        self.assertEqual(qc.authorization_response_url(inv_claims['redirect_uri'], state=v['state'], code=v['code'],
                                                       accept=acc), v['authorization_response_url'])
        self.assertEqual(qc.parse_authorization_response(v['authorization_response_url'], expected_state=v['state']),
                         {'code': v['code'], 'accept': acc, 'state': v['state']})
        self.assertEqual(code_of(lambda: qc.parse_authorization_response(v['authorization_response_url'],
                                                                         expected_state='x' * 43)), 'state_mismatch')
        self.assertEqual(code_of(lambda: qc.parse_authorization_response(v['authorization_error_url'],
                                                                         expected_state=v['state'])), 'access_denied')
        for case in v['accept_cases']:
            self.assertEqual(code_of(lambda: qc.verify_accept(
                case['jws'], invitation=inv_claims, invitation_jws=v['invitation_jws'],
                code=case.get('code', v['code']), now=case['at'])), case['expect'], case['name'])

    def test_exchange_rebuild(self):
        v = self.v
        inv_claims, _ = self.invitation()
        e = v['exchange']['claims']
        jws, claims = qc.build_exchange(
            priv('A'), invitation=inv_claims, accept=v['accept']['claims'], accept_jws=v['accept']['jws'],
            code=v['code'], code_verifier=v['code_verifier'], initiator_app=e['app'],
            discovery_url=e['discovery_url'], requested_scopes=e['requested_scopes'],
            proposed_tenants=e['proposed_tenants'], now=v['exchange']['built_at'], jti=e['jti'])
        self.assertEqual(jws, v['exchange']['jws'])
        self.assertEqual(tokens.build_dpop_proof(priv('A'), 'POST', v['exchange_url'], now=v['exchange']['built_at'],
                                                 jti=v['exchange']['dpop_jti']), v['exchange']['dpop'])
        self.assertEqual(qc.exchange_code_sha256(jws), v['code_sha256'])

    def _verify(self, inv_claims, inv_jwk, jws, dpop, at, store, **over):
        v = self.v
        return qc.verify_exchange(jws, dpop=dpop, url=v['exchange_url'], invitation=inv_claims,
                                  invitation_jwk=inv_jwk, accept_jws=v['accept']['jws'],
                                  code_sha256=v['code_sha256'],
                                  code_expires_at=over.get('code_expires_at', v['code_expires_at']),
                                  responder_installation=over.get('responder_installation',
                                                                  v['responder_installation']),
                                  replay=store, now=at)

    def test_exchange_cases(self):
        inv_claims, inv_jwk = self.invitation()
        for case in self.v['exchange_cases']:
            if 'sequence' in case:
                store = MemoryReplayStore(clock=lambda: case['sequence'][0]['at'])
                got = [code_of(lambda s=s: self._verify(inv_claims, inv_jwk, s['jws'], s['dpop'], s['at'], store))
                       for s in case['sequence']]
                self.assertEqual(got, case['expect'], case['name'])
                continue
            store = MemoryReplayStore(clock=lambda: case['at'])

            def run():
                for _ in range(2 if case.get('replay_twice') else 1):
                    self._verify(inv_claims, inv_jwk, case['jws'], case['dpop'], case['at'], store,
                                 **{k: case[k] for k in ('code_expires_at', 'responder_installation') if k in case})
            self.assertEqual(code_of(run), case['expect'], case['name'])

    def test_v1_verifier_refuses_exchange_and_ack_is_v1(self):
        x = self.v['v1_verifier_refuses_exchange']
        self.assertEqual(code_of(lambda: pairing.verify_request(
            x['jws'], responder_installation=x['responder_installation'], replay=MemoryReplayStore(),
            now=x['at'])), x['expect'])
        e = self.v['exchange']['claims']
        ack, ack_jwk = pairing.verify_ack(self.v['ack']['jws'], initiator_installation=e['iss'],
                                          responder_installation=e['aud'], request_jti=e['jti'],
                                          now=self.v['now'] + 41)
        qc.check_ack_key(ack_jwk, unverified_header(self.v['accept']['jws'])['jwk'])
        self.assertEqual(ack['connection_id'], self.v['accept']['connection_id'])
        self.assertEqual(code_of(lambda: qc.check_ack_key(ack_jwk, KEYS['keys']['C']['public_jwk'])),
                         'key_mismatch')


class TranscriptVectors(unittest.TestCase):
    v = load('qc-transcript.json')

    def test_transcript_and_sas(self):
        v = self.v
        inputs = dict(v['inputs'], invitation_jws=v['invitation_jws'], accept_jws=v['accept_jws'],
                      exchange_jws=v['exchange_jws'])
        self.assertEqual(sha256_hex(v['canonical_input']), v['transcript_hash'])
        self.assertEqual(qc.transcript_hash(**inputs), v['transcript_hash'])
        self.assertEqual(qc.transcript_from_messages(v['invitation_jws'], v['accept_jws'], v['exchange_jws']),
                         v['transcript_hash'])
        self.assertEqual(qc.sas(v['transcript_hash']), v['sas'])
        seen = {v['sas']}
        for m in v['mutations']:
            t = qc.transcript_hash(**dict(inputs, **m['change']))
            self.assertEqual(t, m['transcript_hash'], m['name'])
            self.assertEqual(qc.sas(t), m['sas'])
            self.assertNotIn(m['sas'], seen, m['name'])
            seen.add(m['sas'])


class DiscoveryVectors(unittest.TestCase):
    v = load('qc-discovery.json')

    def test_negotiation_and_fallback(self):
        v = self.v
        self.assertEqual(qc.signed_extensions(), v['ours'])
        self.assertEqual(qc.discovery_endpoints('https://responder.example.test'), v['v1_1_endpoints'])
        for cs in v['negotiation']:
            got = qc.negotiate_extensions(qc.advertised_extensions(cs['discovery'], v['discovery_url']))
            self.assertEqual(got, cs['negotiated'], cs['name'])
            self.assertEqual(qc.pairing_flow(got), cs['flow'], cs['name'])

    def test_downgrade(self):
        v = self.v
        for cs in v['downgrade']:
            adv = qc.advertised_extensions(cs['discovered'], v['discovery_url'])
            self.assertEqual(code_of(lambda: qc.check_no_downgrade(cs['signed'], adv)), cs['expect'], cs['name'])

    def test_v1_parser_ignores_1_1_members(self):
        from agit8or_connect import discovery
        from agit8or_connect.reference_peer import Network, ReferencePeer
        peer = ReferencePeer('https://responder.example.test', Network(), quick_connect=True)
        doc = peer.document()
        self.assertEqual(doc['revision'], '1.1')
        info = discovery.parse_document(doc, discovery.discovery_url(peer.base))
        self.assertEqual(info.version, '1')
        self.assertNotIn('qc_exchange', info.endpoints)


class DiagnosticsVectors(unittest.TestCase):
    v = load('qc-diagnostics.json')

    def test_probe(self):
        v = self.v
        at = v['access_token']
        self.assertEqual(tokens.issue_access_token(priv('B'), issuer=v['issuer'], client_id=at['claims']['client_id'],
                                                   scopes=at['claims']['scope'].split(), jkt=at['claims']['cnf']['jkt'],
                                                   now=v['now'], jti=at['claims']['jti'])[0], at['jws'])
        ring = {KEYS['keys']['B']['thumbprint']: keys.public_key_from_jwk(KEYS['keys']['B']['public_jwk'])}
        for case in v['verify']:
            store = MemoryReplayStore(clock=lambda: case['at'])

            def run():
                for _ in range(2 if case.get('replay_twice') else 1):
                    tokens.authenticate_resource_request(
                        authorization=f'DPoP {at["jws"]}', dpop=case['dpop'], method='POST', url=v['probe_url'],
                        issuer=v['issuer'], token_keys_for=lambda cid: ring, replay=store, now=case['at'])
            self.assertEqual(code_of(run), case['expect'], case['name'])
        nonce = v['request']['body']['nonce']
        self.assertEqual(qc.validate_probe_response(v['response'], nonce=nonce), v['response'])
        r = v['response']
        self.assertEqual(qc.build_probe_response(observed_source=r['observed_source'], server_time=r['server_time'],
                                                 connection_state=r['connection_state'],
                                                 source_check=r['checks']['source'],
                                                 peer_reached_at=r['peer_reached_at'], nonce=nonce), r)
        for bad in v['response_invalid']:
            self.assertEqual(code_of(lambda: qc.validate_probe_response(bad, nonce=nonce)), 'invalid_request', bad)


class V1Untouched(unittest.TestCase):
    def test_v1_vectors_unchanged_and_canonical(self):
        # The generator check covers every file; this pins that the 1.1 files
        # are separate and the v1 files still exist under their old names.
        from agit8or_connect.tools import generate_vectors
        built = generate_vectors.build()
        for name in V1_FILES:
            self.assertIn(name, built)
            with open(os.path.join(DIR, name), encoding='utf-8') as f:
                self.assertEqual(f.read(), json.dumps(built[name], indent=2, ensure_ascii=False, sort_keys=True)
                                 + '\n')
        self.assertTrue(all(n.startswith('qc-') for n in set(built) - set(V1_FILES)))
        import hashlib
        for name, digest in V1_DIGESTS.items():
            with open(os.path.join(DIR, name), 'rb') as f:
                self.assertEqual(hashlib.sha256(f.read()).hexdigest(), digest, name)
        self.assertEqual(canonical_json({'b': 1, 'a': 2}), '{"a":2,"b":1}')


class OpenApiSchemasMatchVectors(unittest.TestCase):
    """The 1.1 claim schemas in openapi.yaml describe the vector messages:
    required members present, no undocumented member, consts and patterns hold."""

    def setUp(self):
        try:
            import yaml
        except ImportError:  # the SDK itself does not depend on PyYAML
            self.skipTest('PyYAML not installed')
        with open(os.path.join(DIR, '..', 'openapi.yaml'), encoding='utf-8') as f:
            self.schemas = yaml.safe_load(f)['components']['schemas']

    def check(self, name, obj):
        import re
        schema = self.schemas[name]
        self.assertLessEqual(set(schema['required']), set(obj), name)
        self.assertLessEqual(set(obj), set(schema['properties']), name)
        for k, prop in schema['properties'].items():
            if k not in obj:
                continue
            if 'const' in prop:
                self.assertEqual(obj[k], prop['const'], (name, k))
            if 'pattern' in prop:
                self.assertRegex(obj[k], re.compile(prop['pattern']), (name, k))
            if prop.get('$ref', '').endswith('/EgressEntry') or (prop.get('items') or {}).get('$ref', '').endswith(
                    '/EgressEntry'):
                for e in obj[k]:
                    self.assertLessEqual(set(e), set(self.schemas['EgressEntry']['properties']))

    def test_messages(self):
        ex = load('qc-exchange.json')
        self.check('QcInvitationClaims', load('qc-invitation.json')['invitation']['claims'])
        self.check('QcAcceptClaims', ex['accept']['claims'])
        self.check('QcExchangeClaims', ex['exchange']['claims'])
        self.check('QcProbeResponse', load('qc-diagnostics.json')['response'])
        members = load('qc-discovery.json')['v1_1_document_members']
        self.assertLessEqual(set(members), set(self.schemas['QcDiscoveryAdditions']['properties']))
