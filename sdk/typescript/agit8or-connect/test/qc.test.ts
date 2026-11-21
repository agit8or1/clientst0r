// Protocol revision 1.1 vectors (docs/agit8or-connect/test-vectors/qc-*.json) — the
// same files agit8or_connect/tests/test_qc_vectors.py verifies.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import * as c from '../src/index.ts';

const DIR = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..', 'docs', 'agit8or-connect', 'test-vectors');
const load = (n: string) => JSON.parse(readFileSync(join(DIR, n), 'utf8'));
const K = load('keys.json');
const priv = (n: string) => c.privateKeyFromSeed(Buffer.from(K.keys[n].seed_hex, 'hex'));
const codeOf = (fn: () => unknown) => { try { fn(); return 'valid'; } catch (e) { if (e instanceof c.ConnectError) return e.code; throw e; } };

const INV = load('qc-invitation.json');
const EX = load('qc-exchange.json');
const TR = load('qc-transcript.json');
const DI = load('qc-discovery.json');
const DG = load('qc-diagnostics.json');

const verifiedInvitation = () => c.verifyInvitation(EX.invitation_jws, { responderOrigin: INV.responder_origin, replay: new c.MemoryReplayStore(() => INV.now), now: INV.now + 10 });

test('qc invitation: rebuild byte for byte', () => {
  const cl = INV.invitation.claims;
  assert.equal(c.pkceChallenge(INV.pkce.code_verifier), INV.pkce.code_challenge);
  const { jws, claims } = c.buildInvitation(priv('A'), { initiatorApp: cl.app, responderOrigin: cl.aud, attempt: cl.attempt, base: cl.base, redirectUri: cl.redirect_uri, egress: cl.egress, requestedScopes: cl.requested_scopes, codeChallenge: cl.code_challenge, nonce: cl.nonce, now: cl.iat, jti: cl.jti });
  assert.equal(jws, INV.invitation.jws);
  assert.deepEqual(claims, cl);
  assert.equal(c.authorizationUrl(INV.responder_origin + c.QC_AUTHORIZE_ENTRY_PATH, jws, INV.state), INV.authorization_url);
  assert.deepEqual(c.parseQuery(INV.authorization_url), { invitation: jws, state: INV.state });
});

test('qc invitation: every case', () => {
  for (const cs of INV.cases) {
    const store = new c.MemoryReplayStore(() => cs.at);
    const got = codeOf(() => {
      for (let i = 0; i < (cs.replay_twice ? 2 : 1); i++) {
        c.verifyInvitation(cs.jws, { responderOrigin: cs.responder_origin ?? INV.responder_origin, responderInstallation: INV.responder_installation, replay: store, now: cs.at });
      }
    });
    assert.equal(got, cs.expect, cs.name);
  }
  const x = INV.v1_verifier_refuses_invitation;
  assert.equal(codeOf(() => c.verifyPairingRequest(x.jws, { responderInstallation: x.responder_installation, replay: new c.MemoryReplayStore(), now: x.at })), x.expect);
});

test('qc addresses and URLs', () => {
  for (const n of INV.net_normalization) { assert.equal(c.normalizeNet(n.in), n.out, n.in); assert.equal(c.checkNet(n.out), n.out); }
  for (const bad of INV.net_malformed) assert.equal(codeOf(() => c.normalizeNet(bad)), 'invalid_egress', bad);
  for (const bad of INV.net_refused) assert.equal(codeOf(() => c.checkNet(bad)), 'invalid_egress', bad);
  for (const p of INV.net_private) assert.equal(c.isPrivateNet(p.net), p.private, p.net);
  for (const u of INV.base_valid) assert.equal(c.checkBase(u), u);
  for (const u of INV.base_invalid) assert.equal(codeOf(() => c.checkBase(u)), 'invalid_base', u);
  for (const r of INV.redirect_checks) assert.equal(codeOf(() => c.checkRedirectUri(r.redirect_uri, r.base)), r.expect, r.redirect_uri);
  assert.ok(c.sourceInEgress('198.51.100.7', [{ net: '198.51.100.0/28' }]));
  assert.ok(!c.sourceInEgress('198.51.100.17', [{ net: '198.51.100.0/28' }]));
});

test('qc accept: rebuild, browser legs, every case', () => {
  const { claims: inv } = verifiedInvitation();
  const a = EX.accept;
  const acc = c.buildAccept(priv('B'), { responderApp: a.claims.app, invitation: inv, invitationJws: EX.invitation_jws, connectionId: a.connection_id, base: a.base, egress: a.egress, code: EX.code, now: a.built_at });
  assert.equal(acc, a.jws);
  assert.deepEqual(c.unverifiedPayload(acc), a.claims);
  assert.equal(c.authorizationResponseUrl(inv.redirect_uri, { state: EX.state, code: EX.code, accept: acc }), EX.authorization_response_url);
  assert.deepEqual(c.parseAuthorizationResponse(EX.authorization_response_url, EX.state), { code: EX.code, accept: acc, state: EX.state });
  assert.equal(codeOf(() => c.parseAuthorizationResponse(EX.authorization_response_url, 'x'.repeat(43))), 'state_mismatch');
  assert.equal(codeOf(() => c.parseAuthorizationResponse(EX.authorization_error_url, EX.state)), 'access_denied');
  for (const cs of EX.accept_cases) {
    assert.equal(codeOf(() => c.verifyAccept(cs.jws, { invitation: inv, invitationJws: EX.invitation_jws, code: cs.code ?? EX.code, now: cs.at })), cs.expect, cs.name);
  }
});

test('qc exchange: rebuild and every case', () => {
  const { claims: inv, jwk } = verifiedInvitation();
  const e = EX.exchange.claims;
  const { jws } = c.buildExchange(priv('A'), { invitation: inv, accept: EX.accept.claims, acceptJws: EX.accept.jws, code: EX.code, codeVerifier: EX.code_verifier, initiatorApp: e.app, discoveryUrl: e.discovery_url, requestedScopes: e.requested_scopes, proposedTenants: e.proposed_tenants, now: EX.exchange.built_at, jti: e.jti });
  assert.equal(jws, EX.exchange.jws);
  assert.equal(c.buildDpopProof(priv('A'), 'POST', EX.exchange_url, { now: EX.exchange.built_at, jti: EX.exchange.dpop_jti }), EX.exchange.dpop);
  assert.equal(c.exchangeCodeSha256(jws), EX.code_sha256);
  const verify = (token: string, dpop: string, at: number, store: c.ReplayStore, over: Record<string, any> = {}) => c.verifyExchange(token, {
    dpop, url: EX.exchange_url, invitation: inv, invitationJwk: jwk, acceptJws: EX.accept.jws, codeSha256: EX.code_sha256,
    codeExpiresAt: over.code_expires_at ?? EX.code_expires_at, responderInstallation: over.responder_installation ?? EX.responder_installation, replay: store, now: at,
  });
  for (const cs of EX.exchange_cases) {
    if (cs.sequence) {
      const store = new c.MemoryReplayStore(() => cs.sequence[0].at);
      assert.deepEqual(cs.sequence.map((s: any) => codeOf(() => verify(s.jws, s.dpop, s.at, store))), cs.expect, cs.name);
      continue;
    }
    const store = new c.MemoryReplayStore(() => cs.at);
    const got = codeOf(() => { for (let i = 0; i < (cs.replay_twice ? 2 : 1); i++) verify(cs.jws, cs.dpop, cs.at, store, cs); });
    assert.equal(got, cs.expect, cs.name);
  }
  const x = EX.v1_verifier_refuses_exchange;
  assert.equal(codeOf(() => c.verifyPairingRequest(x.jws, { responderInstallation: x.responder_installation, replay: new c.MemoryReplayStore(), now: x.at })), x.expect);
  const ack = c.verifyPairingAck(EX.ack.jws, { initiatorInstallation: e.iss, responderInstallation: e.aud, requestJti: e.jti, now: EX.now + 41 });
  c.checkAckKey(ack.jwk, c.unverifiedHeader(EX.accept.jws).jwk);
  assert.equal(codeOf(() => c.checkAckKey(ack.jwk, K.keys.C.public_jwk)), 'key_mismatch');
});

test('qc transcript and SAS', () => {
  const inputs = {
    invitationJws: TR.invitation_jws, acceptJws: TR.accept_jws, exchangeJws: TR.exchange_jws,
    initiatorInstallation: TR.inputs.initiator_installation, initiatorJkt: TR.inputs.initiator_jkt, initiatorEgress: TR.inputs.initiator_egress,
    responderInstallation: TR.inputs.responder_installation, responderJkt: TR.inputs.responder_jkt, responderEgress: TR.inputs.responder_egress,
    destinationHost: TR.inputs.destination_host, destinationPort: TR.inputs.destination_port,
  };
  assert.equal(createHash('sha256').update(TR.canonical_input).digest('hex'), TR.transcript_hash);
  assert.equal(c.qcTranscriptHash(inputs), TR.transcript_hash);
  assert.equal(c.qcTranscriptFromMessages(TR.invitation_jws, TR.accept_jws, TR.exchange_jws), TR.transcript_hash);
  assert.equal(c.qcSas(TR.transcript_hash), TR.sas);
  const camel: Record<string, string> = { initiator_jkt: 'initiatorJkt', responder_jkt: 'responderJkt', initiator_egress: 'initiatorEgress', responder_egress: 'responderEgress', destination_host: 'destinationHost', destination_port: 'destinationPort' };
  for (const m of TR.mutations) {
    const ch = Object.fromEntries(Object.entries(m.change).map(([k, v]) => [camel[k], v]));
    const t = c.qcTranscriptHash({ ...inputs, ...ch });
    assert.equal(t, m.transcript_hash, m.name);
    assert.equal(c.qcSas(t), m.sas);
    assert.notEqual(m.sas, TR.sas);
  }
});

test('qc discovery: negotiation, 1.0 fallback, downgrade', () => {
  assert.deepEqual(c.signedExtensions(), DI.ours);
  assert.deepEqual(c.qcDiscoveryEndpoints('https://responder.example.test'), DI.v1_1_endpoints);
  for (const cs of DI.negotiation) {
    const got = c.negotiateExtensions(c.advertisedExtensions(cs.discovery, DI.discovery_url));
    assert.deepEqual(got, cs.negotiated, cs.name);
    assert.equal(c.pairingFlow(got), cs.flow, cs.name);
  }
  for (const cs of DI.downgrade) {
    assert.equal(codeOf(() => c.checkNoDowngrade(cs.signed, c.advertisedExtensions(cs.discovered, DI.discovery_url))), cs.expect, cs.name);
  }
  const doc = c.extendDiscoveryDocument({ protocol: 'agit8or-connect', versions: ['1'], endpoints: { token: 'x' } }, 'https://responder.example.test');
  assert.deepEqual({ revision: doc.revision, extensions: doc.extensions }, DI.v1_1_document_members);
  assert.equal((doc.endpoints as any).token, 'x');
});

test('qc diagnostics: probe DPoP and response', () => {
  const at = DG.access_token;
  assert.equal(c.issueAccessToken(priv('B'), { issuer: DG.issuer, clientId: at.claims.client_id, scopes: at.claims.scope.split(' '), jkt: at.claims.cnf.jkt, now: DG.now, jti: at.claims.jti }).token, at.jws);
  const ring = new Map([[K.keys.B.thumbprint as string, c.publicKeyFromJwk(K.keys.B.public_jwk)]]);
  for (const cs of DG.verify) {
    const store = new c.MemoryReplayStore(() => cs.at);
    const got = codeOf(() => {
      for (let i = 0; i < (cs.replay_twice ? 2 : 1); i++) {
        const claims = c.verifyAccessToken(at.jws, ring, { issuer: DG.issuer, now: cs.at });
        c.verifyDpopProof(cs.dpop, { method: 'POST', url: DG.probe_url, replay: store, now: cs.at, accessToken: at.jws, expectedJkt: (claims.cnf as any).jkt });
      }
    });
    assert.equal(got, cs.expect, cs.name);
  }
  const nonce = DG.request.body.nonce; const r = DG.response;
  assert.deepEqual(c.validateProbeResponse(r, nonce), r);
  assert.deepEqual(c.buildProbeResponse({ observedSource: r.observed_source, serverTime: r.server_time, connectionState: r.connection_state, sourceCheck: r.checks.source, peerReachedAt: r.peer_reached_at, nonce }), r);
  for (const bad of DG.response_invalid) assert.equal(codeOf(() => c.validateProbeResponse(bad, nonce)), 'invalid_request', JSON.stringify(bad));
});

test('qc round trip with fresh keys (1.1 initiator and responder in one process)', () => {
  const ka = c.generatePrivateKey(), kb = c.generatePrivateKey(), now = 1767225600;
  const A = { type: 'x', version: '1', display_name: 'A', installation_id: '11111111-1111-4111-8111-111111111111' };
  const B = { type: 'y', version: '1', display_name: 'B', installation_id: '22222222-2222-4222-8222-222222222222' };
  const verifier = c.generatePkceVerifier(), state = c.qcGenerateState(), code = c.qcGenerateCode();
  const { jws: inv } = c.buildInvitation(ka, { initiatorApp: A, responderOrigin: 'https://b.example.test', attempt: '44444444-4444-4444-8444-444444444444', base: 'https://a.example.test', redirectUri: 'https://a.example.test/cb', egress: ['203.0.113.10'], requestedScopes: ['customers:read'], codeChallenge: c.pkceChallenge(verifier), nonce: c.qcGenerateNonce(), now });
  const store = new c.MemoryReplayStore(() => now);
  const { claims, jwk } = c.verifyInvitation(c.parseQuery(c.authorizationUrl('https://b.example.test/agit8or-connect/qc-authorize', inv, state)).invitation, { responderOrigin: 'https://b.example.test', replay: store, now });
  const acc = c.buildAccept(kb, { responderApp: B, invitation: claims, invitationJws: inv, connectionId: '66666666-6666-4666-8666-666666666666', base: 'https://b.example.test', egress: ['198.51.100.7/32'], code, now });
  const back = c.parseAuthorizationResponse(c.authorizationResponseUrl(claims.redirect_uri, { state, code, accept: acc }), state);
  const { claims: accept } = c.verifyAccept(back.accept, { invitation: claims, invitationJws: inv, code: back.code, now });
  const url = 'https://b.example.test/connect/v1/qc/exchange';
  const { jws: ex } = c.buildExchange(ka, { invitation: claims, accept, acceptJws: acc, code, codeVerifier: verifier, initiatorApp: A, discoveryUrl: 'https://a.example.test/.well-known/agit8or-connect', requestedScopes: ['customers:read'], now });
  c.verifyExchange(ex, { dpop: c.buildDpopProof(ka, 'POST', url, { now }), url, invitation: claims, invitationJwk: jwk, acceptJws: acc, codeSha256: c.exchangeCodeSha256(ex), codeExpiresAt: now + 120, responderInstallation: B.installation_id, replay: store, now });
  assert.match(c.qcSas(c.qcTranscriptFromMessages(inv, acc, ex)), /^\d{4}-\d{4}$/);
});
