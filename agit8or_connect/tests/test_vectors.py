"""The shared cross-language test vectors (docs/agit8or-connect/test-vectors).
The TypeScript SDK runs the same files (sdk/typescript/agit8or-connect/test)."""
import json
import os
import unittest

from agit8or_connect import audit, keys, pairing, tokens, webhooks
from agit8or_connect.canonical import canonical_json
from agit8or_connect.errors import ConnectError
from agit8or_connect.replay import MemoryReplayStore
from agit8or_connect.tools import generate_vectors

DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'docs', 'agit8or-connect', 'test-vectors')


def load(name):
    with open(os.path.join(DIR, name), encoding='utf-8') as f:
        return json.load(f)


KEYS = load('keys.json')


def priv(name):
    return keys.private_key_from_seed(bytes.fromhex(KEYS['keys'][name]['seed_hex']))


def pub(name):
    return keys.public_key_from_jwk(KEYS['keys'][name]['public_jwk'])


def code_of(fn):
    try:
        fn()
        return 'valid'
    except ConnectError as e:
        return e.code


class VectorFilesUpToDate(unittest.TestCase):
    def test_generator_matches_files(self):
        self.assertEqual(generate_vectors.main(['--check']), 0)


class KeyVectors(unittest.TestCase):
    def test_jwk_and_thumbprint(self):
        for name, k in KEYS['keys'].items():
            key = priv(name)
            self.assertEqual(keys.public_jwk(key), k['public_jwk'])
            self.assertEqual(keys.thumbprint(key), k['thumbprint'])
            self.assertEqual(keys.fingerprint(key), k['fingerprint'])

    def test_private_member_refused(self):
        jwk = dict(KEYS['keys']['A']['public_jwk'], d='AAAA')
        with self.assertRaises(ConnectError):
            keys.public_key_from_jwk(jwk)

    def test_wrong_kid_refused(self):
        jwk = dict(KEYS['keys']['A']['public_jwk'], kid=KEYS['keys']['B']['thumbprint'])
        with self.assertRaises(ConnectError):
            keys.public_key_from_jwk(jwk)


class CanonicalVectors(unittest.TestCase):
    def test_cases(self):
        for case in load('canonical-json.json')['cases']:
            self.assertEqual(canonical_json(case['input']), case['canonical'])


class TokenVectors(unittest.TestCase):
    v = load('tokens.json')

    def test_assertion_bytes_and_verify(self):
        ca = self.v['client_assertion']
        self.assertEqual(tokens.build_client_assertion(priv('A'), ca['client_id'], ca['token_endpoint'],
                                                       now=self.v['now'], jti='assertion-jti-0001'), ca['jws'])
        ring = {KEYS['keys']['A']['thumbprint']: pub('A')}
        for case in ca['verify']:
            store = MemoryReplayStore(clock=lambda: case['at'])

            def run():
                for _ in range(2 if case.get('replay_twice') else 1):
                    tokens.verify_client_assertion(ca['jws'], ring, client_id=ca['client_id'],
                                                   token_endpoint=case.get('token_endpoint', ca['token_endpoint']),
                                                   replay=store, now=case['at'])
            self.assertEqual(code_of(run), case['expect'], case)
        self.assertEqual(code_of(lambda: tokens.verify_client_assertion(
            ca['tampered_jws'], ring, client_id=ca['client_id'], token_endpoint=ca['token_endpoint'],
            replay=MemoryReplayStore(), now=self.v['now'])), ca['tampered_expect'])

    def test_access_token(self):
        at = self.v['access_token']
        tok, claims = tokens.issue_access_token(priv('B'), issuer=at['issuer'], client_id=at['claims']['client_id'],
                                                scopes=at['claims']['scope'].split(), jkt=at['claims']['cnf']['jkt'],
                                                now=self.v['now'], jti='access-token-jti-0001')
        self.assertEqual(tok, at['jws'])
        for case in at['verify']:
            signer = case.get('verify_with', 'B')
            ring = {KEYS['keys']['B']['thumbprint']: pub(signer)}
            self.assertEqual(code_of(lambda: tokens.verify_access_token(
                at['jws'], ring, issuer=case.get('issuer', at['issuer']), now=case['at'])), case['expect'], case)

    def test_dpop(self):
        d = self.v['dpop']
        tr, rr = d['token_request'], d['resource_request']
        self.assertEqual(tokens.build_dpop_proof(priv('A'), tr['method'], tr['url'], now=self.v['now'],
                                                 jti='dpop-token-jti-0001'), tr['jws'])
        self.assertEqual(tokens.build_dpop_proof(priv('A'), rr['method'], rr['url'], now=self.v['now'],
                                                 jti='dpop-api-jti-0001', access_token=rr['access_token']),
                         rr['jws'])
        self.assertEqual(tokens.access_token_hash(rr['access_token']), rr['ath'])
        for n in d['htu_normalization']:
            self.assertEqual(tokens.normalize_htu(n['in']), n['out'])
        for case in d['verify']:
            store = MemoryReplayStore(clock=lambda: case['at'])
            jkt = KEYS['keys'][case.get('expected_jkt_of', 'A')]['thumbprint']

            def run():
                for _ in range(2 if case.get('replay_twice') else 1):
                    tokens.verify_dpop_proof(rr['jws'], method=case.get('method', rr['method']), url=rr['url'],
                                             replay=store, now=case['at'], access_token=rr['access_token'],
                                             expected_jkt=jkt)
            self.assertEqual(code_of(run), case['expect'], case)


class PairingVectors(unittest.TestCase):
    v = load('pairing.json')

    def test_codes(self):
        pepper = self.v['pepper_utf8'].encode()
        for c in self.v['codes']:
            self.assertEqual(pairing.normalize_code(c['input']), c['normalized'])
            self.assertEqual(pairing.hash_code(c['input'], pepper), c['hmac_sha256'])
        for bad in self.v['invalid_codes']:
            with self.assertRaises(ConnectError):
                pairing.normalize_code(bad)

    def test_messages_and_sas(self):
        v = self.v
        claims, jwk = pairing.verify_request(v['request']['jws'], responder_installation=v['request'][
            'responder_installation'], replay=MemoryReplayStore(), now=v['now'])
        self.assertEqual(jwk['kid'], KEYS['keys']['A']['thumbprint'])
        ack, rjwk = pairing.verify_ack(v['ack']['jws'], initiator_installation=claims['iss'],
                                       responder_installation=claims['aud'], request_jti=claims['jti'], now=v['now'])
        th = pairing.transcript_hash(request_jws=v['request']['jws'], request_jti=claims['jti'],
                                     initiator_installation=claims['iss'], initiator_jkt=jwk['kid'],
                                     responder_installation=claims['aud'], responder_jkt=rjwk['kid'])
        self.assertEqual(th, v['transcript_hash'])
        self.assertEqual(pairing.short_authentication_string(th), v['sas'])
        res = pairing.verify_result(v['result']['jws'], pub('B'), initiator_installation=claims['iss'],
                                    responder_installation=claims['aud'], request_jti=claims['jti'], now=v['now'])
        self.assertEqual(res['granted_scopes'], ['customers:read'])
        pairing.verify_poll(v['poll']['jws'], pub('A'), initiator_installation=claims['iss'],
                            responder_installation=claims['aud'], request_id=ack['request_id'],
                            replay=MemoryReplayStore(), now=v['now'])
        self.assertEqual(pairing.parse_qr_payload(v['qr_payload'])['code'], '7K3QM-9XD2P')


class WebhookVectors(unittest.TestCase):
    v = load('webhooks.json')

    def test_sign_and_verify(self):
        v = self.v
        body = v['body_utf8'].encode()
        h = webhooks.sign(priv('A'), connection_id=v['connection_id'], event_id=v['headers']['Agit8or-Event-Id'],
                          sender=v['sender'], receiver=v['receiver'], body=body, timestamp=v['now'])
        self.assertEqual(h, v['headers'])
        ring = {KEYS['keys']['A']['thumbprint']: pub('A')}
        for case in v['verify']:
            b = body + b' ' if case.get('mutate_body') else body
            self.assertEqual(code_of(lambda: webhooks.verify(
                v['headers'], b, ring, sender=v['sender'], receiver=case.get('receiver', v['receiver']),
                connection_id=v['connection_id'], now=case['at'])), case['expect'], case)
        self.assertEqual([webhooks.backoff_seconds(n, rng=lambda: 1.0) for n in range(10)],
                         v['backoff_ceiling_seconds'])


class AuditVectors(unittest.TestCase):
    def test_chain(self):
        v = load('audit-chain.json')
        entries = [(e['record'], e['prev_hash'], e['hash']) for e in v['chain']]
        self.assertIsNone(audit.verify_chain(entries))
        tampered = [(dict(entries[0][0], result='denied'),) + entries[0][1:]] + entries[1:]
        self.assertEqual(audit.verify_chain(tampered), 0)


class JwksVectors(unittest.TestCase):
    def test_endorsement(self):
        v = load('jwks.json')
        a = {KEYS['keys']['A']['thumbprint']: pub('A')}
        ring = keys.verify_endorsed_jwks(v['document'], a, v['issuer'], v['connection_id'], now=v['now'])
        self.assertIn(KEYS['keys']['C']['thumbprint'], ring)
        for only in ('C', 'B'):
            t = {KEYS['keys'][only]['thumbprint']: pub(only)}
            self.assertEqual(code_of(lambda: keys.verify_endorsed_jwks(v['document'], t, v['issuer'],
                                                                       v['connection_id'], now=v['now'])),
                             'invalid_signature')
