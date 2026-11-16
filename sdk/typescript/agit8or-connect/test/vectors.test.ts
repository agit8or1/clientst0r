// Verifies docs/agit8or-connect/test-vectors/*.json — the same files the
// Python SDK verifies. Run: node --test test/*.test.ts
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import * as c from '../src/index.ts';

const DIR = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..', 'docs', 'agit8or-connect', 'test-vectors');
const load = (n: string) => JSON.parse(readFileSync(join(DIR, n), 'utf8'));
const K = load('keys.json');
const priv = (n: string) => c.privateKeyFromSeed(Buffer.from(K.keys[n].seed_hex, 'hex'));
const pub = (n: string) => c.publicKeyFromJwk(K.keys[n].public_jwk);
const ring = (kidOf: string, keyOf = kidOf) => new Map([[K.keys[kidOf].thumbprint as string, pub(keyOf)]]);
const codeOf = (fn: () => unknown) => { try { fn(); return 'valid'; } catch (e) { if (e instanceof c.ConnectError) return e.code; throw e; } };

test('keys: JWK, thumbprint, fingerprint', () => {
  for (const [n, k] of Object.entries<any>(K.keys)) {
    assert.deepEqual(c.publicJwk(priv(n)), k.public_jwk);
    assert.equal(c.thumbprint(priv(n)), k.thumbprint);
    assert.equal(c.fingerprint(priv(n)), k.fingerprint);
  }
  assert.throws(() => c.publicKeyFromJwk({ ...K.keys.A.public_jwk, d: 'AAAA' }));
  assert.throws(() => c.publicKeyFromJwk({ ...K.keys.A.public_jwk, kid: K.keys.B.thumbprint }));
});

test('canonical JSON', () => {
  for (const cs of load('canonical-json.json').cases) assert.equal(c.canonicalJson(cs.input), cs.canonical);
  assert.throws(() => c.canonicalJson({ n: 2 ** 53 }));
  assert.throws(() => c.canonicalJson({ n: Infinity }));
});

test('client assertion', () => {
  const v = load('tokens.json'); const ca = v.client_assertion;
  assert.equal(c.buildClientAssertion(priv('A'), ca.client_id, ca.token_endpoint, v.now, 'assertion-jti-0001'), ca.jws);
  for (const cs of ca.verify) {
    const store = new c.MemoryReplayStore(() => cs.at);
    const got = codeOf(() => {
      for (let i = 0; i < (cs.replay_twice ? 2 : 1); i++) {
        c.verifyClientAssertion(ca.jws, ring('A'), { clientId: ca.client_id, tokenEndpoint: cs.token_endpoint ?? ca.token_endpoint, replay: store, now: cs.at });
      }
    });
    assert.equal(got, cs.expect, JSON.stringify(cs));
  }
  assert.equal(codeOf(() => c.verifyClientAssertion(ca.tampered_jws, ring('A'), { clientId: ca.client_id, tokenEndpoint: ca.token_endpoint, replay: new c.MemoryReplayStore(), now: v.now })), ca.tampered_expect);
});

test('access token', () => {
  const v = load('tokens.json'); const at = v.access_token;
  const { token } = c.issueAccessToken(priv('B'), { issuer: at.issuer, clientId: at.claims.client_id, scopes: at.claims.scope.split(' '), jkt: at.claims.cnf.jkt, now: v.now, jti: 'access-token-jti-0001' });
  assert.equal(token, at.jws);
  for (const cs of at.verify) {
    assert.equal(codeOf(() => c.verifyAccessToken(at.jws, ring('B', cs.verify_with ?? 'B'), { issuer: cs.issuer ?? at.issuer, now: cs.at })), cs.expect, JSON.stringify(cs));
  }
});

test('DPoP', () => {
  const v = load('tokens.json'); const d = v.dpop; const tr = d.token_request, rr = d.resource_request;
  assert.equal(c.buildDpopProof(priv('A'), tr.method, tr.url, { now: v.now, jti: 'dpop-token-jti-0001' }), tr.jws);
  assert.equal(c.buildDpopProof(priv('A'), rr.method, rr.url, { now: v.now, jti: 'dpop-api-jti-0001', accessToken: rr.access_token }), rr.jws);
  assert.equal(c.accessTokenHash(rr.access_token), rr.ath);
  for (const n of d.htu_normalization) assert.equal(c.normalizeHtu(n.in), n.out);
  for (const cs of d.verify) {
    const store = new c.MemoryReplayStore(() => cs.at);
    const got = codeOf(() => {
      for (let i = 0; i < (cs.replay_twice ? 2 : 1); i++) {
        c.verifyDpopProof(rr.jws, { method: cs.method ?? rr.method, url: rr.url, replay: store, now: cs.at, accessToken: rr.access_token, expectedJkt: K.keys[cs.expected_jkt_of ?? 'A'].thumbprint });
      }
    });
    assert.equal(got, cs.expect, JSON.stringify(cs));
  }
});

test('pairing: codes, messages, transcript, SAS', () => {
  const v = load('pairing.json'); const pepper = Buffer.from(v.pepper_utf8, 'utf8');
  for (const cd of v.codes) {
    assert.equal(c.normalizeCode(cd.input), cd.normalized);
    assert.equal(c.hashCode(cd.input, pepper), cd.hmac_sha256);
    assert.ok(c.codeMatches(cd.input, cd.hmac_sha256, pepper));
  }
  for (const bad of v.invalid_codes) assert.throws(() => c.normalizeCode(bad));
  const { claims, jwk } = c.verifyPairingRequest(v.request.jws, { responderInstallation: v.request.responder_installation, replay: new c.MemoryReplayStore(), now: v.now });
  const rebuilt = c.buildPairingRequest(priv('A'), { initiatorApp: claims.app as any, responderInstallation: claims.aud as string, pairingCode: claims.pairing_code as string, connectionId: claims.connection_id as string, discoveryUrl: claims.discovery_url as string, requestedScopes: claims.requested_scopes as string[], proposedTenants: claims.proposed_tenants as any, now: v.now, jti: claims.jti as string });
  assert.equal(rebuilt.jws, v.request.jws);
  const ack = c.verifyPairingAck(v.ack.jws, { initiatorInstallation: claims.iss as string, responderInstallation: claims.aud as string, requestJti: claims.jti as string, now: v.now });
  assert.equal(c.buildPairingAck(priv('B'), { responderApp: ack.claims.app as any, initiatorInstallation: claims.iss as string, requestId: ack.claims.request_id as string, requestJti: claims.jti as string, connectionId: ack.claims.connection_id as string, now: v.now }), v.ack.jws);
  const th = c.transcriptHash({ requestJws: v.request.jws, requestJti: claims.jti as string, initiatorInstallation: claims.iss as string, initiatorJkt: jwk.kid!, responderInstallation: claims.aud as string, responderJkt: ack.jwk.kid! });
  assert.equal(th, v.transcript_hash);
  assert.equal(c.shortAuthenticationString(th), v.sas);
  const res = c.verifyPairingResult(v.result.jws, pub('B'), { initiatorInstallation: claims.iss as string, responderInstallation: claims.aud as string, requestJti: claims.jti as string, now: v.now });
  assert.deepEqual(res.granted_scopes, ['customers:read']);
  assert.equal(c.buildPairingResult(priv('B'), { responderInstallation: claims.aud as string, initiatorInstallation: claims.iss as string, requestId: res.request_id as string, requestJti: claims.jti as string, status: 'approved', connectionId: res.connection_id as string, grantedScopes: res.granted_scopes as string[], tenantGrants: res.tenant_grants as any, requestedScopes: res.requested_scopes as string[], endpoints: {}, now: v.now }), v.result.jws);
  assert.equal(c.buildPairingPoll(priv('A'), { initiatorInstallation: claims.iss as string, responderInstallation: claims.aud as string, requestId: ack.claims.request_id as string, now: v.now, jti: 'poll-jti-0001' }), v.poll.jws);
  const store = new c.MemoryReplayStore(() => v.now);
  c.verifyPairingPoll(v.poll.jws, pub('A'), { initiatorInstallation: claims.iss as string, responderInstallation: claims.aud as string, requestId: ack.claims.request_id as string, replay: store, now: v.now });
  assert.equal(codeOf(() => c.verifyPairingPoll(v.poll.jws, pub('A'), { initiatorInstallation: claims.iss as string, responderInstallation: claims.aud as string, requestId: ack.claims.request_id as string, replay: store, now: v.now })), 'replayed');
  assert.equal(codeOf(() => c.verifyPairingRequest(v.request.jws, { responderInstallation: 'someone-else', replay: new c.MemoryReplayStore(), now: v.now })), 'invalid_signature');
});

test('webhooks', () => {
  const v = load('webhooks.json'); const body = Buffer.from(v.body_utf8, 'utf8');
  assert.equal(c.eventSigningString({ connectionId: v.connection_id, eventId: v.headers['Agit8or-Event-Id'], timestamp: v.now, sender: v.sender, receiver: v.receiver, body }), v.signing_string);
  assert.deepEqual(c.signEvent(priv('A'), { connectionId: v.connection_id, eventId: v.headers['Agit8or-Event-Id'], sender: v.sender, receiver: v.receiver, body, timestamp: v.now }), v.headers);
  for (const cs of v.verify) {
    const b = cs.mutate_body ? Buffer.concat([body, Buffer.from(' ')]) : body;
    assert.equal(codeOf(() => c.verifyEvent(v.headers, b, ring('A'), { sender: v.sender, receiver: cs.receiver ?? v.receiver, connectionId: v.connection_id, now: cs.at })), cs.expect, JSON.stringify(cs));
  }
  assert.deepEqual([...Array(10).keys()].map((n) => c.backoffSeconds(n, () => 1)), v.backoff_ceiling_seconds);
});

test('audit chain', () => {
  const v = load('audit-chain.json');
  assert.equal(c.verifyChain(v.chain), null);
  const t = structuredClone(v.chain); t[1].record.result = 'denied';
  assert.equal(c.verifyChain(t), 1);
});

test('endorsed JWKS', () => {
  const v = load('jwks.json');
  const r = c.verifyEndorsedJwks(v.document, ring('A'), v.issuer, v.connection_id, v.now);
  assert.ok(r.has(K.keys.C.thumbprint));
  assert.equal(codeOf(() => c.verifyEndorsedJwks(v.document, ring('C'), v.issuer, v.connection_id, v.now)), 'invalid_signature');
  assert.equal(codeOf(() => c.verifyEndorsedJwks(v.document, ring('B'), v.issuer, v.connection_id, v.now)), 'invalid_signature');
  const regenerated = c.endorsedJwks(priv('A'), [pub('A'), pub('C')], v.issuer, v.connection_id, v.now);
  assert.equal(regenerated.endorsement, v.document.endorsement);
});

test('round trip with fresh keys: token + DPoP + event', () => {
  const a = c.generatePrivateKey(), b = c.generatePrivateKey(); const store = new c.MemoryReplayStore();
  const { token } = c.issueAccessToken(b, { issuer: 'inst-b', clientId: 'cid', scopes: ['x:read'], jkt: c.thumbprint(a) });
  const claims = c.verifyAccessToken(token, new Map([[c.thumbprint(b), b]]), { issuer: 'inst-b' });
  const proof = c.buildDpopProof(a, 'GET', 'https://b.example/x', { accessToken: token });
  c.verifyDpopProof(proof, { method: 'GET', url: 'https://b.example/x', replay: store, accessToken: token, expectedJkt: (claims.cnf as any).jkt });
  assert.equal(codeOf(() => c.verifyDpopProof(proof, { method: 'GET', url: 'https://b.example/x', replay: store, accessToken: token, expectedJkt: (claims.cnf as any).jkt })), 'replayed');
  assert.match(c.generateCode(), /^[0-9A-HJKMNP-TV-Z]{5}-[0-9A-HJKMNP-TV-Z]{5}$/);
});
