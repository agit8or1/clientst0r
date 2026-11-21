/**
 * Agit8or Connect — TypeScript reference SDK (protocol agit8or-connect/1).
 *
 * node:crypto only. Mirrors agit8or_connect (Python): same canonical JSON,
 * same JWS bytes, same error codes. Interop is proven by both SDKs verifying
 * docs/agit8or-connect/test-vectors/*.json.
 *
 * Erasable TypeScript only (no enums, no parameter properties, no
 * namespaces) so `node --test` runs it without a build step.
 */
import {
  createHash, createHmac, createPrivateKey, createPublicKey, generateKeyPairSync, randomBytes,
  sign as edSign, timingSafeEqual, verify as edVerify, KeyObject,
} from 'node:crypto';

export const PROTOCOL = 'agit8or-connect';
export const PROTOCOL_ID = 'agit8or-connect/1';
export const SUPPORTED_VERSIONS = ['1'];

// --- errors -------------------------------------------------------------------

export class ConnectError extends Error {
  code: string;
  status: number;
  constructor(code: string, message = '', status = 400) {
    super(message ? `${code}: ${message}` : code);
    this.code = code;
    this.status = status;
  }
}

// --- canonical JSON, base64url, digests ------------------------------------------------

export type Json = null | boolean | number | string | Json[] | { [k: string]: Json };

export function canonicalJson(value: unknown): string {
  if (value === null) return 'null';
  if (value === true) return 'true';
  if (value === false) return 'false';
  if (typeof value === 'string') return JSON.stringify(value);
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new ConnectError('invalid_request', 'canonical_json: number out of range');
    if (Number.isInteger(value) && !Number.isSafeInteger(value)) {
      throw new ConnectError('invalid_request', 'canonical_json: number out of range');
    }
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return '[' + value.map(canonicalJson).join(',') + ']';
  if (typeof value === 'object') {
    const obj = value as Record<string, unknown>;
    // Default sort compares UTF-16 code units, as the protocol requires.
    const keys = Object.keys(obj).filter((k) => obj[k] !== undefined).sort();
    return '{' + keys.map((k) => JSON.stringify(k) + ':' + canonicalJson(obj[k])).join(',') + '}';
  }
  throw new ConnectError('invalid_request', `canonical_json: unsupported type ${typeof value}`);
}

export function b64url(data: Buffer | Uint8Array | string): string {
  return Buffer.from(data as Uint8Array).toString('base64url');
}

export function fromB64url(s: string): Buffer {
  if (typeof s !== 'string' || !/^[A-Za-z0-9_-]*$/.test(s) || s.length % 4 === 1) {
    throw new ConnectError('invalid_request', 'not base64url');
  }
  return Buffer.from(s, 'base64url');
}

export function sha256Hex(data: Buffer | string): string {
  return createHash('sha256').update(data).digest('hex');
}

export function sha256B64url(data: Buffer | string): string {
  return createHash('sha256').update(data).digest('base64url');
}

// --- keys ----------------------------------------------------------------------

export interface PublicJwk { kty: 'OKP'; crv: 'Ed25519'; x: string; kid?: string; alg?: string; use?: string; [k: string]: unknown }

const PKCS8_ED25519_PREFIX = Buffer.from('302e020100300506032b657004220420', 'hex');

export function generatePrivateKey(): KeyObject {
  return generateKeyPairSync('ed25519').privateKey;
}

/** TEST VECTORS only: a key from a fixed 32-byte seed. */
export function privateKeyFromSeed(seed: Buffer): KeyObject {
  if (seed.length !== 32) throw new ConnectError('invalid_request', 'an Ed25519 seed is 32 bytes');
  return createPrivateKey({ key: Buffer.concat([PKCS8_ED25519_PREFIX, seed]), format: 'der', type: 'pkcs8' });
}

function asPublic(key: KeyObject): KeyObject {
  return key.type === 'private' ? createPublicKey(key) : key;
}

export function rawPublicX(key: KeyObject): string {
  const jwk = asPublic(key).export({ format: 'jwk' }) as { x: string; crv: string };
  if (jwk.crv !== 'Ed25519') throw new ConnectError('invalid_request', 'not an Ed25519 key');
  return jwk.x;
}

export function thumbprint(key: KeyObject): string {
  return sha256B64url(canonicalJson({ crv: 'Ed25519', kty: 'OKP', x: rawPublicX(key) }));
}

export function publicJwk(key: KeyObject): PublicJwk {
  return { kty: 'OKP', crv: 'Ed25519', x: rawPublicX(key), kid: thumbprint(key), alg: 'EdDSA', use: 'sig' };
}

export function publicKeyFromJwk(jwk: unknown): KeyObject {
  if (!jwk || typeof jwk !== 'object') throw new ConnectError('invalid_request', 'JWK must be an object');
  const j = jwk as Record<string, unknown>;
  if (j.kty !== 'OKP' || j.crv !== 'Ed25519') throw new ConnectError('invalid_request', 'only OKP / Ed25519 keys');
  if ('d' in j) throw new ConnectError('invalid_request', 'a private key must never be sent');
  if (j.alg !== undefined && j.alg !== 'EdDSA') throw new ConnectError('invalid_request', 'JWK alg must be EdDSA');
  const raw = fromB64url(String(j.x ?? ''));
  if (raw.length !== 32) throw new ConnectError('invalid_request', 'Ed25519 public key must be 32 bytes');
  const key = createPublicKey({ key: { kty: 'OKP', crv: 'Ed25519', x: String(j.x) }, format: 'jwk' });
  if (j.kid !== undefined && j.kid !== thumbprint(key)) {
    throw new ConnectError('invalid_request', 'JWK kid does not match its thumbprint');
  }
  return key;
}

export function fingerprint(key: KeyObject): string {
  return (thumbprint(key).match(/.{1,4}/g) ?? []).join(' ');
}

export type KeyRing = Map<string, KeyObject>;

export function keyring(keys: unknown[]): KeyRing {
  const out: KeyRing = new Map();
  for (const jwk of (keys ?? []).slice(0, 8)) {
    try {
      const k = publicKeyFromJwk(jwk);
      out.set(thumbprint(k), k);
    } catch { /* skip */ }
  }
  return out;
}

// --- JWS -----------------------------------------------------------------------

export function signCompact(privateKey: KeyObject, header: Record<string, unknown>, payload: Record<string, unknown>): string {
  if (header.alg !== 'EdDSA') throw new ConnectError('invalid_request', 'only EdDSA is produced');
  const h = b64url(canonicalJson(header));
  const p = b64url(canonicalJson(payload));
  const sig = edSign(null, Buffer.from(`${h}.${p}`, 'ascii'), privateKey);
  return `${h}.${p}.${b64url(sig)}`;
}

function parts(token: string): string[] {
  if (typeof token !== 'string' || !token || token.length > 8192) throw new ConnectError('invalid_request', 'token missing or too long');
  const p = token.split('.');
  if (p.length !== 3 || !p[0] || !p[1] || !p[2]) throw new ConnectError('invalid_request', 'not a compact JWS');
  return p;
}

function parseObj(seg: string, what: string): Record<string, unknown> {
  let v: unknown;
  try { v = JSON.parse(fromB64url(seg).toString('utf8')); } catch { throw new ConnectError('invalid_request', `malformed JWS ${what}`); }
  if (!v || typeof v !== 'object' || Array.isArray(v)) throw new ConnectError('invalid_request', `malformed JWS ${what}`);
  return v as Record<string, unknown>;
}

export function unverifiedHeader(token: string): Record<string, unknown> {
  const h = parseObj(parts(token)[0], 'header');
  if (h.alg !== 'EdDSA') throw new ConnectError('invalid_signature', 'unsupported JWS algorithm');
  if ('crit' in h) throw new ConnectError('invalid_request', 'critical JWS header parameters are not supported');
  return h;
}

export function unverifiedPayload(token: string): Record<string, unknown> {
  return parseObj(parts(token)[1], 'payload');
}

export interface VerifyOptions {
  typ: string; audience?: string; issuer?: string; now?: number; maxLifetime?: number; skew?: number; required?: string[];
}

const isInt = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v);

export function checkTimes(claims: Record<string, unknown>, now: number, maxLifetime?: number, skew = 120, requireIat = true): void {
  for (const n of ['exp', 'iat', 'nbf']) {
    if (claims[n] !== undefined && !isInt(claims[n])) throw new ConnectError('invalid_request', `${n} must be an integer`);
  }
  const exp = claims.exp as number | undefined, iat = claims.iat as number | undefined, nbf = claims.nbf as number | undefined;
  if (exp === undefined || (requireIat && iat === undefined)) throw new ConnectError('invalid_request', 'exp and iat are required');
  if (now >= exp + skew) throw new ConnectError('expired', 'token expired', 401);
  if (iat !== undefined && iat > now + skew) throw new ConnectError('invalid_request', 'token issued in the future', 401);
  if (nbf !== undefined && nbf > now + skew) throw new ConnectError('invalid_request', 'token not yet valid', 401);
  if (maxLifetime !== undefined && iat !== undefined && exp - iat > maxLifetime) throw new ConnectError('invalid_request', 'token lifetime exceeds the maximum', 401);
  if (iat !== undefined && exp <= iat) throw new ConnectError('invalid_request', 'exp must be after iat', 401);
}

export function verifyCompact(token: string, key: KeyObject, o: VerifyOptions): Record<string, unknown> {
  const header = unverifiedHeader(token);
  if (header.typ !== o.typ) throw new ConnectError('invalid_request', `expected a ${o.typ} token`, 401);
  const p = parts(token);
  let ok = false;
  try {
    const sig = fromB64url(p[2]);
    ok = sig.length === 64 && edVerify(null, Buffer.from(`${p[0]}.${p[1]}`, 'ascii'), asPublic(key), sig);
  } catch { ok = false; }
  if (!ok) throw new ConnectError('invalid_signature', 'signature does not verify', 401);
  const claims = unverifiedPayload(token);
  const required = o.required ?? ['iat', 'exp'];
  for (const r of required) if (!(r in claims)) throw new ConnectError('invalid_request', `missing claim ${r}`, 401);
  if (o.audience !== undefined && claims.aud !== o.audience) throw new ConnectError('invalid_signature', 'wrong audience', 401);
  if (o.issuer !== undefined && claims.iss !== o.issuer) throw new ConnectError('invalid_signature', 'wrong issuer', 401);
  if (required.includes('exp')) {
    checkTimes(claims, o.now ?? Math.floor(Date.now() / 1000), o.maxLifetime, o.skew ?? 120, required.includes('iat'));
  }
  return claims;
}

// --- replay store ------------------------------------------------------------------

export interface ReplayStore { add(namespace: string, key: string, expiresAt: number): boolean }

export class MemoryReplayStore implements ReplayStore {
  seen = new Map<string, number>();
  clock: () => number;
  constructor(clock: () => number = () => Math.floor(Date.now() / 1000)) { this.clock = clock; }
  add(namespace: string, key: string, expiresAt: number): boolean {
    const k = `${namespace}\u0000${key}`;
    const prev = this.seen.get(k);
    if (prev !== undefined && prev > this.clock()) return false;
    this.seen.set(k, expiresAt);
    return true;
  }
}

// --- tokens ------------------------------------------------------------------------

export const CLIENT_ASSERTION_TYPE = 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer';
export const TYP_ASSERTION = 'client-authentication+jwt';
export const TYP_ACCESS_TOKEN = 'at+jwt';
export const TYP_DPOP = 'dpop+jwt';
const SKEW = 120;

const nowS = (now?: number) => Math.floor(now ?? Date.now() / 1000);
export const newJti = () => randomBytes(18).toString('base64url');

type KeySource = KeyRing | ((kid: string) => KeyObject | undefined);
const lookup = (src: KeySource, kid: string) => (typeof src === 'function' ? src(kid) : src.get(kid));

function rewrap<T>(code: string, fn: () => T): T {
  try { return fn(); } catch (e) {
    if (e instanceof ConnectError) throw new ConnectError(code, e.message, 401);
    throw e;
  }
}

export function buildClientAssertion(key: KeyObject, clientId: string, tokenEndpoint: string, now?: number, jti?: string, lifetime = 60): string {
  if (!(lifetime > 0 && lifetime <= 60)) throw new ConnectError('invalid_request', 'assertion lifetime must be 1..60 s');
  const iat = nowS(now);
  return signCompact(key, { alg: 'EdDSA', typ: TYP_ASSERTION, kid: thumbprint(key) },
    { iss: clientId, sub: clientId, aud: tokenEndpoint, iat, exp: iat + lifetime, jti: jti ?? newJti() });
}

export function verifyClientAssertion(assertion: string, keys: KeySource, o: { clientId: string; tokenEndpoint: string; replay: ReplayStore; now?: number }): { claims: Record<string, unknown>; kid: string } {
  const header = rewrap('invalid_client', () => unverifiedHeader(assertion));
  const kid = String(header.kid ?? '');
  const key = lookup(keys, kid);
  if (!key) throw new ConnectError('invalid_client', 'unknown client key', 401);
  const claims = rewrap('invalid_client', () => verifyCompact(assertion, key, {
    typ: TYP_ASSERTION, audience: o.tokenEndpoint, issuer: o.clientId, now: o.now, maxLifetime: 60, skew: SKEW,
    required: ['iss', 'sub', 'aud', 'iat', 'exp', 'jti'],
  }));
  if (claims.sub !== o.clientId || typeof claims.jti !== 'string' || !claims.jti) throw new ConnectError('invalid_client', 'assertion subject or jti invalid', 401);
  if (!o.replay.add('assertion', `${o.clientId}:${claims.jti}`, (claims.exp as number) + SKEW)) throw new ConnectError('replayed', 'client assertion already used', 401);
  return { claims, kid };
}

export function issueAccessToken(key: KeyObject, o: { issuer: string; clientId: string; scopes: string[]; jkt: string; now?: number; lifetime?: number; jti?: string }): { token: string; claims: Record<string, unknown> } {
  const lifetime = o.lifetime ?? 300;
  if (!(lifetime > 0 && lifetime <= 300)) throw new ConnectError('invalid_request', 'access token lifetime must be 1..300 s');
  const iat = nowS(o.now);
  const claims = {
    iss: o.issuer, aud: o.issuer, sub: o.clientId, client_id: o.clientId, scope: [...new Set(o.scopes)].sort().join(' '),
    iat, nbf: iat, exp: iat + lifetime, jti: o.jti ?? newJti(), cnf: { jkt: o.jkt },
  };
  return { token: signCompact(key, { alg: 'EdDSA', typ: TYP_ACCESS_TOKEN, kid: thumbprint(key) }, claims), claims };
}

export function verifyAccessToken(token: string, keys: KeySource, o: { issuer: string; now?: number }): Record<string, unknown> {
  const header = rewrap('invalid_token', () => unverifiedHeader(token));
  const key = lookup(keys, String(header.kid ?? ''));
  if (!key) throw new ConnectError('invalid_token', 'token signed by an unknown key', 401);
  const claims = rewrap('invalid_token', () => verifyCompact(token, key, {
    typ: TYP_ACCESS_TOKEN, audience: o.issuer, issuer: o.issuer, now: o.now, maxLifetime: 300, skew: 0,
    required: ['iss', 'aud', 'sub', 'client_id', 'scope', 'iat', 'exp', 'jti', 'cnf'],
  }));
  const cnf = claims.cnf as Record<string, unknown> | undefined;
  if (!cnf || typeof cnf.jkt !== 'string' || !cnf.jkt) throw new ConnectError('invalid_token', 'token is not sender-constrained', 401);
  if (claims.sub !== claims.client_id) throw new ConnectError('invalid_token', 'token subject mismatch', 401);
  return claims;
}

export function normalizeHtu(url: string): string {
  const u = new URL(url);
  const scheme = u.protocol.replace(':', '').toLowerCase();
  const port = u.port; // WHATWG URL already drops default ports and lower-cases the host
  const host = u.hostname.toLowerCase();
  return `${scheme}://${host}${port ? ':' + port : ''}${u.pathname || '/'}`;
}

export const accessTokenHash = (token: string) => sha256B64url(Buffer.from(token, 'ascii'));

export function buildDpopProof(key: KeyObject, method: string, url: string, o: { now?: number; jti?: string; accessToken?: string } = {}): string {
  const claims: Record<string, unknown> = { jti: o.jti ?? newJti(), htm: method.toUpperCase(), htu: normalizeHtu(url), iat: nowS(o.now) };
  if (o.accessToken) claims.ath = accessTokenHash(o.accessToken);
  const jwk = publicJwk(key);
  return signCompact(key, { alg: 'EdDSA', typ: TYP_DPOP, jwk: { kty: jwk.kty, crv: jwk.crv, x: jwk.x } }, claims);
}

export function verifyDpopProof(proof: string, o: { method: string; url: string; replay: ReplayStore; now?: number; accessToken?: string; expectedJkt?: string; allowedJkts?: string[] }): { jkt: string; claims: Record<string, unknown> } {
  if (typeof proof !== 'string' || !proof) throw new ConnectError('invalid_dpop_proof', 'DPoP proof missing', 401);
  const header = rewrap('invalid_dpop_proof', () => unverifiedHeader(proof));
  const key = rewrap('invalid_dpop_proof', () => publicKeyFromJwk(header.jwk));
  const jkt = thumbprint(key);
  if (o.expectedJkt !== undefined && jkt !== o.expectedJkt) throw new ConnectError('invalid_dpop_proof', 'proof key does not match the token binding', 401);
  if (o.allowedJkts !== undefined && !o.allowedJkts.includes(jkt)) throw new ConnectError('invalid_dpop_proof', 'proof key is not a key of this connection', 401);
  const now = nowS(o.now);
  const claims = rewrap('invalid_dpop_proof', () => verifyCompact(proof, key, { typ: TYP_DPOP, now, required: ['jti', 'htm', 'htu', 'iat'] }));
  const iat = claims.iat;
  if (!isInt(iat) || Math.abs(now - iat) > 120) throw new ConnectError('invalid_dpop_proof', 'proof too old or from the future', 401);
  if (claims.htm !== o.method.toUpperCase() || claims.htu !== normalizeHtu(o.url)) throw new ConnectError('invalid_dpop_proof', 'proof is for another request', 401);
  if (o.accessToken !== undefined && claims.ath !== accessTokenHash(o.accessToken)) throw new ConnectError('invalid_dpop_proof', 'proof is for another access token', 401);
  const jti = claims.jti;
  if (typeof jti !== 'string' || jti.length < 8 || jti.length > 128) throw new ConnectError('invalid_dpop_proof', 'proof jti invalid', 401);
  if (!o.replay.add('dpop', `${jkt}:${jti}`, iat + 120 + SKEW)) throw new ConnectError('replayed', 'DPoP proof already used', 401);
  return { jkt, claims };
}

// --- pairing -------------------------------------------------------------------

export const CODE_ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
export const TYP_REQUEST = 'agit8or-pairing-request+jwt';
export const TYP_ACK = 'agit8or-pairing-ack+jwt';
export const TYP_RESULT = 'agit8or-pairing-result+jwt';
export const TYP_POLL = 'agit8or-pairing-poll+jwt';

export function generateCode(): string {
  let s = '';
  for (const b of randomBytes(10)) s += CODE_ALPHABET[b & 31];
  return `${s.slice(0, 5)}-${s.slice(5)}`;
}

export function normalizeCode(code: string): string {
  if (typeof code !== 'string' || code.length > 32) throw new ConnectError('invalid_pairing_code', 'pairing code malformed');
  const map: Record<string, string> = { O: '0', I: '1', L: '1' };
  const s = [...code.toUpperCase()].filter((c) => !'- \t'.includes(c)).map((c) => map[c] ?? c).join('');
  if (s.length !== 10 || [...s].some((c) => !CODE_ALPHABET.includes(c))) throw new ConnectError('invalid_pairing_code', 'pairing code malformed');
  return s;
}

export function hashCode(code: string, pepper: Buffer): string {
  return createHmac('sha256', pepper).update(Buffer.concat([Buffer.from('agit8or-connect/1 pairing-code\n'), Buffer.from(normalizeCode(code), 'ascii')])).digest('hex');
}

export function codeMatches(code: string, storedHash: string, pepper: Buffer): boolean {
  try {
    const a = Buffer.from(hashCode(code, pepper)), b = Buffer.from(storedHash ?? '');
    return a.length === b.length && timingSafeEqual(a, b);
  } catch { return false; }
}

export function transcriptHash(o: { requestJws: string; requestJti: string; initiatorInstallation: string; initiatorJkt: string; responderInstallation: string; responderJkt: string }): string {
  return sha256Hex(canonicalJson({
    v: `${PROTOCOL_ID} pairing-transcript`, request_sha256: sha256Hex(o.requestJws), request_jti: o.requestJti,
    initiator: { installation_id: o.initiatorInstallation, jkt: o.initiatorJkt },
    responder: { installation_id: o.responderInstallation, jkt: o.responderJkt },
  }));
}

export function shortAuthenticationString(transcript: string): string {
  const d = createHash('sha256').update(`${PROTOCOL_ID} sas\n${transcript}`, 'ascii').digest();
  const n = d.readBigUInt64BE(0) % 100000000n;
  const s = n.toString().padStart(8, '0');
  return `${s.slice(0, 4)}-${s.slice(4)}`;
}

type App = { type: string; version: string; display_name: string; installation_id: string };
const appOf = (a: App): App => ({ type: String(a.type ?? ''), version: String(a.version ?? ''), display_name: String(a.display_name ?? ''), installation_id: String(a.installation_id ?? '') });
const uniqSorted = (xs: string[]) => [...new Set(xs)].sort();

export function buildPairingRequest(key: KeyObject, o: { initiatorApp: App; responderInstallation: string; pairingCode: string; connectionId: string; discoveryUrl: string; requestedScopes: string[]; proposedTenants?: { id: string; label?: string }[]; now?: number; jti?: string; lifetime?: number }): { jws: string; claims: Record<string, unknown> } {
  const iat = nowS(o.now);
  const jwk = publicJwk(key);
  const claims = {
    protocol: PROTOCOL_ID, iss: o.initiatorApp.installation_id, aud: o.responderInstallation, iat, exp: iat + (o.lifetime ?? 300),
    jti: o.jti ?? newJti(), pairing_code: o.pairingCode, app: appOf(o.initiatorApp), connection_id: o.connectionId,
    discovery_url: o.discoveryUrl, connection_key: jwk, requested_scopes: uniqSorted(o.requestedScopes),
    proposed_tenants: (o.proposedTenants ?? []).map((t) => ({ id: String(t.id), label: String(t.label ?? '').slice(0, 200) })),
  };
  return { jws: signCompact(key, { alg: 'EdDSA', typ: TYP_REQUEST, kid: jwk.kid, jwk }, claims), claims };
}

export function buildPairingAck(key: KeyObject, o: { responderApp: App; initiatorInstallation: string; requestId: string; requestJti: string; connectionId: string; now?: number; lifetime?: number }): string {
  const iat = nowS(o.now);
  const jwk = publicJwk(key);
  return signCompact(key, { alg: 'EdDSA', typ: TYP_ACK, kid: jwk.kid, jwk }, {
    protocol: PROTOCOL_ID, iss: o.responderApp.installation_id, aud: o.initiatorInstallation, iat, exp: iat + (o.lifetime ?? 3600),
    request_id: o.requestId, request_jti: o.requestJti, connection_id: o.connectionId, app: appOf(o.responderApp),
    connection_key: jwk, status: 'pending_approval',
  });
}

export function buildPairingResult(key: KeyObject, o: { responderInstallation: string; initiatorInstallation: string; requestId: string; requestJti: string; status: 'approved' | 'rejected'; connectionId: string; grantedScopes?: string[]; tenantGrants?: Record<string, unknown>[]; requestedScopes?: string[]; endpoints?: Record<string, string>; now?: number; lifetime?: number }): string {
  const iat = nowS(o.now);
  return signCompact(key, { alg: 'EdDSA', typ: TYP_RESULT, kid: thumbprint(key) }, {
    protocol: PROTOCOL_ID, iss: o.responderInstallation, aud: o.initiatorInstallation, iat, exp: iat + (o.lifetime ?? 3600),
    request_id: o.requestId, request_jti: o.requestJti, status: o.status, connection_id: o.connectionId,
    granted_scopes: uniqSorted(o.grantedScopes ?? []), tenant_grants: o.tenantGrants ?? [], requested_scopes: uniqSorted(o.requestedScopes ?? []),
    endpoints: o.endpoints ?? {},
  });
}

export function verifyPairingRequest(token: string, o: { responderInstallation: string; replay: ReplayStore; now?: number }): { claims: Record<string, unknown>; jwk: PublicJwk } {
  const header = unverifiedHeader(token);
  const key = rewrap('invalid_signature', () => publicKeyFromJwk(header.jwk));
  const claims = verifyCompact(token, key, {
    typ: TYP_REQUEST, audience: o.responderInstallation, now: o.now, maxLifetime: 600,
    required: ['protocol', 'iss', 'aud', 'iat', 'exp', 'jti', 'pairing_code', 'app', 'connection_id', 'connection_key'],
  });
  if (claims.protocol !== PROTOCOL_ID) throw new ConnectError('unsupported_version', 'pairing request protocol not supported');
  if (thumbprint(publicKeyFromJwk(claims.connection_key)) !== thumbprint(key)) throw new ConnectError('invalid_signature', 'request not signed by the announced connection key', 401);
  const app = claims.app as Record<string, unknown>;
  if (!app || app.installation_id !== claims.iss) throw new ConnectError('invalid_request', 'app identity does not match the issuer');
  if (!o.replay.add('pairing', `${claims.iss}:${claims.jti}`, (claims.exp as number) + 120)) throw new ConnectError('replayed', 'pairing request already submitted', 401);
  return { claims, jwk: publicJwk(key) };
}

export function verifyPairingAck(token: string, o: { initiatorInstallation: string; responderInstallation: string; requestJti: string; now?: number }): { claims: Record<string, unknown>; jwk: PublicJwk } {
  const header = unverifiedHeader(token);
  const key = publicKeyFromJwk(header.jwk);
  const claims = verifyCompact(token, key, {
    typ: TYP_ACK, audience: o.initiatorInstallation, issuer: o.responderInstallation, now: o.now, maxLifetime: 3600,
    required: ['iss', 'aud', 'iat', 'exp', 'request_id', 'request_jti', 'connection_id', 'connection_key'],
  });
  if (claims.request_jti !== o.requestJti) throw new ConnectError('invalid_signature', 'ack is for another pairing request', 401);
  if (thumbprint(publicKeyFromJwk(claims.connection_key)) !== thumbprint(key)) throw new ConnectError('invalid_signature', 'ack not signed by the announced key', 401);
  return { claims, jwk: publicJwk(key) };
}

export function verifyPairingResult(token: string, responderKey: KeyObject, o: { initiatorInstallation: string; responderInstallation: string; requestJti: string; now?: number }): Record<string, unknown> {
  const claims = verifyCompact(token, responderKey, {
    typ: TYP_RESULT, audience: o.initiatorInstallation, issuer: o.responderInstallation, now: o.now, maxLifetime: 3600,
    required: ['iss', 'aud', 'iat', 'exp', 'request_id', 'request_jti', 'status', 'connection_id'],
  });
  if (claims.request_jti !== o.requestJti) throw new ConnectError('invalid_signature', 'result is for another pairing request', 401);
  if (claims.status !== 'approved' && claims.status !== 'rejected') throw new ConnectError('invalid_request', 'unknown pairing status');
  return claims;
}

export function buildPairingPoll(key: KeyObject, o: { initiatorInstallation: string; responderInstallation: string; requestId: string; now?: number; jti?: string }): string {
  const iat = nowS(o.now);
  return signCompact(key, { alg: 'EdDSA', typ: TYP_POLL, kid: thumbprint(key) },
    { iss: o.initiatorInstallation, aud: o.responderInstallation, iat, exp: iat + 60, jti: o.jti ?? newJti(), request_id: o.requestId });
}

export function verifyPairingPoll(token: string, initiatorKey: KeyObject, o: { initiatorInstallation: string; responderInstallation: string; requestId: string; replay: ReplayStore; now?: number }): Record<string, unknown> {
  const claims = verifyCompact(token, initiatorKey, {
    typ: TYP_POLL, audience: o.responderInstallation, issuer: o.initiatorInstallation, now: o.now, maxLifetime: 120,
    required: ['iss', 'aud', 'iat', 'exp', 'jti', 'request_id'],
  });
  if (claims.request_id !== o.requestId) throw new ConnectError('invalid_signature', 'proof is for another pairing request', 401);
  if (!o.replay.add('poll', `${o.requestId}:${claims.jti}`, (claims.exp as number) + 120)) throw new ConnectError('replayed', 'status proof already used', 401);
  return claims;
}

// --- webhooks ------------------------------------------------------------------

export const EVENT_PREFIX = 'agit8or-connect-event-v1';
/** Connection-level events: no tenant, accepted from any active connection. */
export const CONNECTION_EVENTS = ['connect.test', 'connect.connection.revoked'];
export const isConnectionEvent = (env: { type?: unknown; tenant?: unknown }): boolean =>
  CONNECTION_EVENTS.includes(String(env.type)) && !env.tenant;

export function eventSigningString(o: { connectionId: string; eventId: string; timestamp: number; sender: string; receiver: string; body: Buffer }): string {
  return [EVENT_PREFIX, o.connectionId, o.eventId, String(o.timestamp), o.sender, o.receiver, sha256Hex(o.body)].join('\n');
}

export function signEvent(key: KeyObject, o: { connectionId: string; eventId: string; sender: string; receiver: string; body: Buffer; timestamp?: number }): Record<string, string> {
  const ts = nowS(o.timestamp);
  const msg = eventSigningString({ ...o, timestamp: ts });
  return {
    'Agit8or-Connection': o.connectionId, 'Agit8or-Event-Id': o.eventId, 'Agit8or-Timestamp': String(ts),
    'Agit8or-Key-Id': thumbprint(key), 'Agit8or-Signature': b64url(edSign(null, Buffer.from(msg, 'utf8'), key)),
    'Content-Type': 'application/json',
  };
}

const hdr = (h: Record<string, string>, n: string) => Object.entries(h).find(([k]) => k.toLowerCase() === n.toLowerCase())?.[1] ?? '';
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export function verifyEvent(headers: Record<string, string>, body: Buffer, keys: KeyRing, o: { sender: string; receiver: string; connectionId: string; now?: number }): { eventId: string; kid: string } {
  if (body.length > 1024 * 1024) throw new ConnectError('too_large', 'event body too large', 413);
  const conn = hdr(headers, 'Agit8or-Connection'), eid = hdr(headers, 'Agit8or-Event-Id'), ts = hdr(headers, 'Agit8or-Timestamp');
  const kid = hdr(headers, 'Agit8or-Key-Id'), sig = hdr(headers, 'Agit8or-Signature');
  if (conn !== o.connectionId || !UUID_RE.test(eid) || !/^\d{1,11}$/.test(ts)) throw new ConnectError('invalid_request', 'missing or malformed event headers', 401);
  if (Math.abs(nowS(o.now) - Number(ts)) > 120) throw new ConnectError('expired', 'event timestamp outside the allowed window', 401);
  const key = keys.get(kid);
  if (!key) throw new ConnectError('invalid_signature', 'event signed by an unknown key', 401);
  let ok = false;
  try {
    const raw = fromB64url(sig);
    ok = raw.length === 64 && edVerify(null, Buffer.from(eventSigningString({ connectionId: conn, eventId: eid, timestamp: Number(ts), sender: o.sender, receiver: o.receiver, body }), 'utf8'), key, raw);
  } catch { ok = false; }
  if (!ok) throw new ConnectError('invalid_signature', 'event signature does not verify', 401);
  return { eventId: eid, kid };
}

export function backoffSeconds(attempt: number, rng: () => number = Math.random, base = 30, cap = 3600): number {
  const ceiling = Math.min(cap, base * 2 ** Math.max(0, Math.min(attempt, 20)));
  return Math.max(1, Math.floor(ceiling * (0.5 + 0.5 * rng())));
}

// --- audit chain -----------------------------------------------------------------

export const GENESIS = '0'.repeat(64);
export const entryHash = (prev: string, record: unknown) => sha256Hex(canonicalJson({ prev, record }));

export function verifyChain(entries: { record: unknown; prev_hash: string; hash: string }[], startPrev = GENESIS): number | null {
  let prev = startPrev;
  for (let i = 0; i < entries.length; i++) {
    const e = entries[i];
    if (e.prev_hash !== prev || entryHash(prev, e.record) !== e.hash) return i;
    prev = e.hash;
  }
  return null;
}

// --- endorsed JWKS ----------------------------------------------------------------

export const JWKS_TYP = 'agit8or-jwks+jwt';

export function keysDigest(jwks: PublicJwk[]): string {
  const norm = jwks.map((k) => ({ crv: 'Ed25519', kid: thumbprint(publicKeyFromJwk({ kty: 'OKP', crv: 'Ed25519', x: k.x })), kty: 'OKP', x: k.x }))
    .sort((a, b) => (a.kid < b.kid ? -1 : a.kid > b.kid ? 1 : 0));
  return sha256Hex(canonicalJson(norm));
}

export function endorsedJwks(signingKey: KeyObject, publicKeys: KeyObject[], issuer: string, connectionId: string, now?: number, lifetime = 3600): { keys: PublicJwk[]; endorsement: string } {
  const iat = nowS(now);
  const keys = publicKeys.map(publicJwk);
  return {
    keys,
    endorsement: signCompact(signingKey, { alg: 'EdDSA', typ: JWKS_TYP, kid: thumbprint(signingKey) },
      { iss: issuer, sub: connectionId, keys_sha256: keysDigest(keys), iat, exp: iat + lifetime }),
  };
}

export function verifyEndorsedJwks(doc: { keys?: unknown; endorsement?: unknown }, trusted: KeyRing, issuer: string, connectionId: string, now?: number): KeyRing {
  if (!doc || !Array.isArray(doc.keys)) throw new ConnectError('invalid_request', 'JWKS must be an object with a keys array');
  if (doc.keys.length > 8) throw new ConnectError('invalid_request', 'too many keys in JWKS');
  if (typeof doc.endorsement !== 'string') throw new ConnectError('invalid_signature', 'JWKS is not endorsed');
  const header = unverifiedHeader(doc.endorsement);
  const key = trusted.get(String(header.kid ?? ''));
  if (!key) throw new ConnectError('invalid_signature', 'JWKS endorsed by a key that is not trusted');
  const claims = verifyCompact(doc.endorsement, key, { typ: JWKS_TYP, issuer, now, maxLifetime: 86400, required: ['iss', 'sub', 'keys_sha256', 'iat', 'exp'] });
  if (claims.sub !== connectionId) throw new ConnectError('invalid_signature', 'JWKS endorsement is for another connection');
  const ring = keyring(doc.keys);
  if (ring.size !== doc.keys.length || claims.keys_sha256 !== keysDigest([...ring.values()].map(publicJwk))) {
    throw new ConnectError('invalid_signature', 'JWKS keys do not match the endorsement');
  }
  return ring;
}

// =====================================================================================
// Protocol revision 1.1: Quick Connect extensions (docs/agit8or-connect/PROTOCOL-1.1.md)
// qc-bootstrap/1, qc-source-binding/1, qc-diagnostics/1. Additive and negotiated:
// nothing above this line changes. Mirrors agit8or_connect/quick_connect.py and is
// proven by test-vectors/qc-*.json.
// =====================================================================================

export const QC_REVISION = '1.1';
export const PROTOCOL_ID_1_1 = 'agit8or-connect/1.1';
export const EXT_BOOTSTRAP = 'qc-bootstrap';
export const EXT_SOURCE_BINDING = 'qc-source-binding';
export const EXT_DIAGNOSTICS = 'qc-diagnostics';
export const BOOTSTRAP_ID = 'qc-bootstrap/1';
export type Extensions = Record<string, number[]>;
export const SUPPORTED_EXTENSIONS: Extensions = { [EXT_BOOTSTRAP]: [1], [EXT_SOURCE_BINDING]: [1], [EXT_DIAGNOSTICS]: [1] };
export const EXTENSION_ENDPOINTS: Record<string, string[]> = { [EXT_BOOTSTRAP]: ['qc_authorize', 'qc_exchange'], [EXT_SOURCE_BINDING]: [], [EXT_DIAGNOSTICS]: ['qc_probe'] };
export const EXTENSION_REQUIRES: Record<string, string[]> = { [EXT_BOOTSTRAP]: [EXT_SOURCE_BINDING] };
export const TYP_QC_INVITATION = 'agit8or-qc-invitation+jwt';
export const TYP_QC_ACCEPT = 'agit8or-qc-accept+jwt';
export const TYP_QC_EXCHANGE = 'agit8or-qc-exchange+jwt';
export const QC_INVITATION_MAX_LIFETIME = 600;
export const QC_ACCEPT_MAX_LIFETIME = 600;
export const QC_EXCHANGE_MAX_LIFETIME = 120;
export const QC_CODE_TTL = 120;
export const QC_TEMPORARY_RULE_TTL = 900;
export const QC_MAX_INVITATION_LENGTH = 4096;
export const QC_AUTHORIZE_ENTRY_PATH = '/agit8or-connect/qc-authorize';
export const QC_EXCHANGE_PATH = '/connect/v1/qc/exchange';
export const QC_PROBE_PATH = '/connect/v1/qc/probe';
export const QC_NS_INVITATION = 'qc-inv';
export const QC_NS_EXCHANGE = 'qc-exchange';
export const QC_NS_CODE = 'qc-code';
const QC_SKEW = 120;
const MAX_EGRESS = 8, MAX_NOTE = 100, MAX_URL = 512;

const B64URL_RE = /^[A-Za-z0-9_-]+$/;
const JTI_RE = /^[A-Za-z0-9_-]{16,128}$/;
const VERIFIER_RE = /^[A-Za-z0-9._~-]{43,128}$/;
const NET_SYNTAX = /^(?:[0-9]{1,3}(?:\.[0-9]{1,3}){3}|[0-9A-Fa-f:.]{2,45})(?:\/(?:0|[1-9][0-9]{0,2}))?$/;
const ce = (code: string, msg: string, status = 400) => new ConnectError(code, msg, status);

// --- random values -----------------------------------------------------------------------

export const qcGenerateCode = () => b64url(randomBytes(32));
export const qcGenerateState = () => b64url(randomBytes(32));
export const qcGenerateNonce = () => b64url(randomBytes(32));
export const generatePkceVerifier = () => b64url(randomBytes(32));

export function pkceChallenge(verifier: string): string {
  if (typeof verifier !== 'string' || !VERIFIER_RE.test(verifier)) throw ce('invalid_request', 'code_verifier malformed');
  return sha256B64url(Buffer.from(verifier, 'ascii'));
}

// --- IP addresses (no dependency: parse to BigInt, format per RFC 5952) -----------------

interface Net { v: 4 | 6; addr: bigint; prefix: number }
const bits = (v: 4 | 6) => (v === 4 ? 32 : 128);

function parseV4(s: string): bigint | null {
  const p = s.split('.');
  if (p.length !== 4) return null;
  let n = 0n;
  for (const o of p) {
    if (!/^(0|[1-9][0-9]{0,2})$/.test(o) || Number(o) > 255) return null;
    n = (n << 8n) | BigInt(o);
  }
  return n;
}

function parseV6(s: string): bigint | null {
  const dbl = s.indexOf('::');
  if (dbl !== s.lastIndexOf('::')) return null;
  const groups = (part: string, last: boolean): number[] | null => {
    if (part === '') return [];
    const out: number[] = [];
    const items = part.split(':');
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      if (last && i === items.length - 1 && it.includes('.')) {
        const v4 = parseV4(it);
        if (v4 === null) return null;
        out.push(Number(v4 >> 16n), Number(v4 & 0xffffn));
      } else if (/^[0-9A-Fa-f]{1,4}$/.test(it)) out.push(parseInt(it, 16));
      else return null;
    }
    return out;
  };
  let hextets: number[];
  if (dbl < 0) {
    const g = groups(s, true);
    if (!g || g.length !== 8) return null;
    hextets = g;
  } else {
    const left = groups(s.slice(0, dbl), false), right = groups(s.slice(dbl + 2), true);
    if (!left || !right || left.length + right.length > 7) return null;
    hextets = [...left, ...Array(8 - left.length - right.length).fill(0), ...right];
  }
  return hextets.reduce((n, h) => (n << 16n) | BigInt(h), 0n);
}

function formatV4(n: bigint): string {
  return [24n, 16n, 8n, 0n].map((s) => String((n >> s) & 0xffn)).join('.');
}

function formatV6(n: bigint): string {
  const h = [...Array(8).keys()].map((i) => Number((n >> BigInt(16 * (7 - i))) & 0xffffn));
  let best = -1, bestLen = 0;
  for (let i = 0; i < 8;) {
    if (h[i] !== 0) { i++; continue; }
    let j = i;
    while (j < 8 && h[j] === 0) j++;
    if (j - i > bestLen && j - i > 1) { best = i; bestLen = j - i; }
    i = j;
  }
  const hex = (xs: number[]) => xs.map((x) => x.toString(16)).join(':');
  if (best < 0) return hex(h);
  return hex(h.slice(0, best)) + '::' + hex(h.slice(best + bestLen));
}

const formatNet = (n: Net) => `${n.v === 4 ? formatV4(n.addr) : formatV6(n.addr)}/${n.prefix}`;

function netOf(text: string): Net {
  const [a, p] = text.split('/');
  const v = (a.includes(':') ? 6 : 4) as 4 | 6;
  const addr = v === 4 ? parseV4(a) : parseV6(a);
  if (addr === null) throw ce('invalid_egress', 'address malformed');
  const prefix = p === undefined ? bits(v) : Number(p);
  if (prefix > bits(v)) throw ce('invalid_egress', 'address malformed');
  const hostMask = (1n << BigInt(bits(v) - prefix)) - 1n;
  if ((addr & hostMask) !== 0n) throw ce('invalid_egress', 'address malformed');
  return { v, addr, prefix };
}

function overlaps(a: Net, b: Net): boolean {
  if (a.v !== b.v) return false;
  const p = Math.min(a.prefix, b.prefix), shift = BigInt(bits(a.v) - p);
  return (a.addr >> shift) === (b.addr >> shift);
}

const nets = (xs: string[]) => xs.map(netOf);
const REFUSED_NETS = nets(['0.0.0.0/8', '127.0.0.0/8', '169.254.0.0/16', '224.0.0.0/4', '240.0.0.0/4', '100.100.100.200/32',
  '192.0.0.192/32', '::/128', '::1/128', '::ffff:0:0/96', 'fe80::/10', 'ff00::/8', 'fd00:ec2::254/128']);
const PRIVATE_NETS = nets(['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '100.64.0.0/10', 'fc00::/7']);
const MAPPED = netOf('::ffff:0:0/96');
const MIN_PREFIX = { 4: 16, 6: 32 };

/** Canonical text of an address or network (exact address -> /32 or /128; RFC 5952 for IPv6). */
export function normalizeNet(value: string): string {
  if (typeof value !== 'string' || !NET_SYNTAX.test(value)) throw ce('invalid_egress', 'address malformed');
  const n = netOf(value);
  if (n.v === 6 && overlaps(n, MAPPED)) throw ce('invalid_egress', 'IPv4-mapped IPv6 addresses are not accepted');
  return formatNet(n);
}

export function isPrivateNet(net: string): boolean {
  const n = netOf(normalizeNet(net));
  return PRIVATE_NETS.some((p) => overlaps(n, p));
}

export function checkNet(value: string): string {
  const canon = normalizeNet(value);
  if (canon !== value) throw ce('invalid_egress', 'address is not in canonical form');
  const n = netOf(canon);
  if (n.prefix < MIN_PREFIX[n.v]) throw ce('invalid_egress', 'address range too broad');
  if (REFUSED_NETS.some((r) => overlaps(n, r))) throw ce('invalid_egress', 'loopback, link-local, multicast, unspecified, mapped or metadata address');
  return canon;
}

export interface EgressEntry { net: string; note?: string }
const cpLen = (s: string) => [...s].length;

export function validateEgress(entries: unknown): EgressEntry[] {
  if (!Array.isArray(entries) || entries.length < 1 || entries.length > MAX_EGRESS) throw ce('invalid_egress', 'egress must list 1 to 8 addresses');
  const seen = new Set<string>();
  for (const e of entries) {
    if (!e || typeof e !== 'object' || typeof (e as EgressEntry).net !== 'string') throw ce('invalid_egress', 'egress entry malformed');
    const note = (e as EgressEntry).note ?? '';
    if (typeof note !== 'string' || cpLen(note) > MAX_NOTE) throw ce('invalid_egress', 'egress note malformed');
    const net = checkNet((e as EgressEntry).net);
    if (seen.has(net)) throw ce('invalid_egress', 'egress address listed twice');
    seen.add(net);
  }
  return entries as EgressEntry[];
}

export function egressEntries(items: (string | EgressEntry)[]): { net: string; note: string }[] {
  const out = items.map((it) => {
    const [net, note] = typeof it === 'string' ? [it, ''] : [it.net, it.note ?? ''];
    return { net: normalizeNet(net), note: [...String(note)].slice(0, MAX_NOTE).join('') };
  });
  validateEgress(out);
  return out;
}

export const egressNets = (entries: EgressEntry[]) => entries.map((e) => e.net);

function addrOf(s: string): Net | null {
  if (typeof s !== 'string' || !/^[0-9A-Fa-f:.]{2,45}$/.test(s)) return null;
  const v = (s.includes(':') ? 6 : 4) as 4 | 6;
  const a = v === 4 ? parseV4(s) : parseV6(s);
  return a === null ? null : { v, addr: a, prefix: bits(v) };
}

export function sourceInEgress(source: string, entries: EgressEntry[]): boolean {
  const a = addrOf(source);
  return !!a && entries.some((e) => { const n = netOf(e.net); return n.v === a.v && overlaps(n, a) && n.prefix <= a.prefix; });
}

// --- URLs (strict canonical grammar, PROTOCOL-1.1.md §4.3) ---------------------------------

const LABEL = '[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?';
const URL_RE = new RegExp(`^https://(${LABEL}(?:\\.${LABEL})*|\\[[0-9a-f:.]+\\])(?::([1-9][0-9]{0,4}))?((?:/[A-Za-z0-9._~-]+)*)$`);
const isAscii = (s: unknown): s is string => typeof s === 'string' && /^[\x21-\x7e]*$/.test(s) && s.length > 0;

export function parseHttpsUrl(url: string, code = 'invalid_base'): { host: string; port: number; path: string } {
  if (!isAscii(url) || url.length > MAX_URL) throw ce(code, 'URL malformed');
  const m = URL_RE.exec(url);
  if (!m) throw ce(code, 'URL is not in canonical form');
  const [, host, portS, path] = m;
  if (path.split('/').some((seg) => seg === '.' || seg === '..')) throw ce(code, 'URL path malformed');
  const port = portS ? Number(portS) : 443;
  if (port > 65535 || (port === 443 && portS)) throw ce(code, 'URL port malformed');
  if (host.startsWith('[')) {
    const inner = host.slice(1, -1);
    const a = parseV6(inner);
    if (a === null) throw ce(code, 'URL host malformed');
    if (formatV6(a) !== inner || overlaps({ v: 6, addr: a, prefix: 128 }, MAPPED)) throw ce(code, 'URL host is not canonical');
  } else if (/^[0-9.]+$/.test(host)) {
    const a = parseV4(host);
    if (a === null) throw ce(code, 'URL host malformed');
    if (formatV4(a) !== host) throw ce(code, 'URL host is not canonical');
  } else if (host.length > 253) throw ce(code, 'URL host too long');
  return { host, port, path: path ?? '' };
}

export function qcOriginOf(url: string, code = 'invalid_base'): string {
  const { host, port } = parseHttpsUrl(url, code);
  return `https://${host}${port !== 443 ? ':' + port : ''}`;
}

export function originHostPort(origin: string): { host: string; port: number } {
  const { host, port } = parseHttpsUrl(origin);
  return { host: host.startsWith('[') ? host.slice(1, -1) : host, port };
}

export function checkBase(url: string, allowedPorts: number[] = [443]): string {
  const { host, port } = parseHttpsUrl(url, 'invalid_base');
  if (!allowedPorts.includes(port)) throw ce('invalid_base', 'base port not allowed');
  if (host === 'localhost' || host.endsWith('.localhost')) throw ce('invalid_base', 'base host not allowed');
  const a = addrOf(host.replace(/^\[|\]$/g, ''));
  if (a && /^[\[0-9]/.test(host) && REFUSED_NETS.some((r) => overlaps(r, a) && r.prefix <= a.prefix)) throw ce('invalid_base', 'base host not allowed');
  return url;
}

export function checkRedirectUri(redirectUri: string, base: string): string {
  const { path } = parseHttpsUrl(redirectUri, 'invalid_redirect_uri');
  if (!path) throw ce('invalid_redirect_uri', 'redirect_uri needs a path');
  if (qcOriginOf(redirectUri, 'invalid_redirect_uri') !== qcOriginOf(base, 'invalid_redirect_uri')) throw ce('invalid_redirect_uri', 'redirect_uri is not on the initiator origin');
  return redirectUri;
}

// --- extensions and negotiation --------------------------------------------------------

function versionsOf(value: unknown): number[] {
  const list = typeof value === 'number' ? [value] : Array.isArray(value) ? value : [];
  return [...new Set(list.filter((v): v is number => typeof v === 'number' && Number.isInteger(v) && v > 0 && v < 1000))].sort((a, b) => a - b);
}

export function normalizeExtensions(value: unknown): Extensions {
  const out: Extensions = {};
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    for (const [name, v] of Object.entries(value as Record<string, unknown>)) {
      const vs = versionsOf(v);
      if (vs.length && name.length <= 64) out[name] = vs;
    }
  }
  return out;
}

export const signedExtensions = (supported: Extensions = SUPPORTED_EXTENSIONS) => normalizeExtensions(supported);

function looseOrigin(url: string): string {
  const u = new URL(url);
  return `${u.protocol.toLowerCase()}//${u.hostname.toLowerCase()}:${u.port || (u.protocol === 'https:' ? '443' : '80')}`;
}

export function advertisedExtensions(doc: unknown, discoveryUrl: string): Extensions {
  if (!doc || typeof doc !== 'object') return {};
  const d = doc as Record<string, unknown>;
  const ext = normalizeExtensions(d.extensions);
  const eps = (d.endpoints && typeof d.endpoints === 'object' ? d.endpoints : {}) as Record<string, unknown>;
  const want = looseOrigin(discoveryUrl);
  for (const [name, needed] of Object.entries(EXTENSION_ENDPOINTS)) {
    if (!(name in ext)) continue;
    for (const ep of needed) {
      const v = eps[ep];
      let ok = isAscii(v);
      try { ok = ok && looseOrigin(v as string) === want; } catch { ok = false; }
      if (!ok) { delete ext[name]; break; }
    }
  }
  return ext;
}

export function negotiateExtensions(theirs: Extensions, ours: Extensions = SUPPORTED_EXTENSIONS): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [name, mine] of Object.entries(ours)) {
    const t = versionsOf(theirs[name] ?? []);
    const common = mine.filter((v) => t.includes(v));
    if (common.length) out[name] = Math.max(...common);
  }
  for (const [name, needs] of Object.entries(EXTENSION_REQUIRES)) {
    if (name in out && needs.some((n) => !(n in out))) delete out[name];
  }
  return out;
}

export const pairingFlow = (negotiated: Record<string, number>) => (negotiated[EXT_BOOTSTRAP] === 1 ? BOOTSTRAP_ID : 'code');

export function checkNoDowngrade(signed: unknown, discovered: unknown, ours: Extensions = SUPPORTED_EXTENSIONS): void {
  const disc = normalizeExtensions(discovered);
  for (const [name, versions] of Object.entries(normalizeExtensions(signed))) {
    if (!(name in ours)) continue;
    const mine = versions.filter((v) => ours[name].includes(v));
    if (mine.some((v) => !(disc[name] ?? []).includes(v))) throw ce('downgrade_detected', `discovery no longer advertises ${name}`, 403);
  }
}

export function qcDiscoveryEndpoints(base: string, authorizeUrl?: string, extensions: Extensions = SUPPORTED_EXTENSIONS): Record<string, string> {
  const b = base.replace(/\/+$/, '');
  const out: Record<string, string> = {};
  if (EXT_BOOTSTRAP in extensions) { out.qc_authorize = authorizeUrl ?? b + QC_AUTHORIZE_ENTRY_PATH; out.qc_exchange = b + QC_EXCHANGE_PATH; }
  if (EXT_DIAGNOSTICS in extensions) out.qc_probe = b + QC_PROBE_PATH;
  return out;
}

export function extendDiscoveryDocument(doc: Record<string, unknown>, base: string, authorizeUrl?: string, extensions: Extensions = SUPPORTED_EXTENSIONS): Record<string, unknown> {
  const ext: Record<string, number | number[]> = {};
  for (const [k, v] of Object.entries(signedExtensions(extensions))) ext[k] = v.length === 1 ? v[0] : v;
  return { ...doc, revision: QC_REVISION, extensions: ext,
    endpoints: { ...((doc.endpoints as Record<string, string>) ?? {}), ...qcDiscoveryEndpoints(base, authorizeUrl, extensions) } };
}

// --- browser legs --------------------------------------------------------------------------

export function parseQuery(urlOrQuery: string): Record<string, string> {
  let q = urlOrQuery.includes('?') ? urlOrQuery.slice(urlOrQuery.indexOf('?') + 1) : urlOrQuery;
  q = q.split('#')[0];
  const out: Record<string, string> = {};
  for (const [k, v] of new URLSearchParams(q)) {
    if (k in out) throw ce('invalid_request', `parameter ${k} repeated`);
    out[k] = v;
  }
  return out;
}

function checkState(state: string): string {
  if (typeof state !== 'string' || !B64URL_RE.test(state) || state.length < 22 || state.length > 128) throw ce('invalid_request', 'state malformed');
  return state;
}

const urlSafe = (s: string) => { if (!/^[A-Za-z0-9._-]*$/.test(s)) throw ce('invalid_request', 'value not URL-safe'); return s; };

export function authorizationUrl(authorizeEndpoint: string, invitation: string, state: string): string {
  checkState(state);
  return `${authorizeEndpoint}${authorizeEndpoint.includes('?') ? '&' : '?'}invitation=${urlSafe(invitation)}&state=${state}`;
}

export function authorizationResponseUrl(redirectUri: string, o: { state: string; code?: string; accept?: string; error?: string }): string {
  checkState(o.state);
  if (o.error !== undefined) return `${redirectUri}?error=${urlSafe(o.error)}&state=${o.state}`;
  if (!o.code || !o.accept) throw new Error('code and accept are required');
  return `${redirectUri}?accept=${urlSafe(o.accept)}&code=${urlSafe(o.code)}&state=${o.state}`;
}

export function parseAuthorizationResponse(url: string, expectedState: string): { code: string; accept: string; state: string } {
  const q = parseQuery(url);
  const state = q.state ?? '';
  const a = Buffer.from(state), b = Buffer.from(expectedState ?? '');
  if (!state || a.length !== b.length || !timingSafeEqual(a, b)) throw ce('state_mismatch', 'state does not match this attempt');
  if ('error' in q) throw ce(/^[a-z_]{1,64}$/.test(q.error) ? q.error : 'invalid_request', 'the other application refused the request');
  const code = q.code ?? '', accept = q.accept ?? '';
  if (!B64URL_RE.test(code) || code.length !== 43 || !accept) throw ce('invalid_request', 'authorisation response incomplete');
  return { code, accept, state };
}

// --- shared checks --------------------------------------------------------------------------

type Claims = Record<string, any>;
const UUID_V = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

function requireStr(c: Claims, name: string, re?: RegExp): string {
  const v = c[name];
  if (typeof v !== 'string' || !v || (re && !re.test(v))) throw ce('invalid_request', `${name} malformed`);
  return v;
}

function checkExtensionClaims(c: Claims): void {
  if (c.protocol !== PROTOCOL_ID_1_1 || c.ext !== BOOTSTRAP_ID) throw ce('unsupported_version', 'not an agit8or-connect/1.1 qc-bootstrap/1 message');
}

function checkSignedExtensions(c: Claims): Extensions {
  const ext = normalizeExtensions(c.extensions);
  if (!(ext[EXT_BOOTSTRAP] ?? []).includes(1) || !(ext[EXT_SOURCE_BINDING] ?? []).includes(1)) {
    throw ce('invalid_request', 'extensions must include qc-bootstrap/1 and qc-source-binding/1');
  }
  return ext;
}

function headerKey(token: string, typ: string): KeyObject {
  const h = unverifiedHeader(token);
  if (h.typ !== typ) throw ce('invalid_request', `expected a ${typ} token`, 401);
  const key = rewrap('invalid_signature', () => publicKeyFromJwk(h.jwk));
  if (h.kid !== undefined && h.kid !== thumbprint(key)) throw ce('invalid_signature', 'kid does not match the header key', 401);
  return key;
}

const safeEq = (x: string, y: string) => { const a = Buffer.from(String(x)), b = Buffer.from(String(y)); return a.length === b.length && timingSafeEqual(a, b); };

// --- invitation ---------------------------------------------------------------------------

export interface InvitationOptions {
  initiatorApp: App; responderOrigin: string; attempt: string; base: string; redirectUri: string;
  egress: (string | EgressEntry)[]; requestedScopes: string[]; codeChallenge: string; nonce: string;
  responderInstallation?: string; extensions?: Extensions; now?: number; jti?: string; lifetime?: number;
}

export function buildInvitation(key: KeyObject, o: InvitationOptions): { jws: string; claims: Claims } {
  const iat = nowS(o.now);
  const jwk = publicJwk(key);
  const claims: Claims = {
    protocol: PROTOCOL_ID_1_1, ext: BOOTSTRAP_ID, extensions: signedExtensions(o.extensions ?? SUPPORTED_EXTENSIONS),
    iss: o.initiatorApp.installation_id, aud: qcOriginOf(o.responderOrigin), iat, exp: iat + (o.lifetime ?? QC_INVITATION_MAX_LIFETIME),
    jti: o.jti ?? b64url(randomBytes(18)), attempt: o.attempt, app: appOf(o.initiatorApp), base: o.base, redirect_uri: o.redirectUri,
    egress: egressEntries(o.egress), requested_scopes: uniqSorted(o.requestedScopes), code_challenge: o.codeChallenge,
    code_challenge_method: 'S256', nonce: o.nonce,
  };
  if (o.responderInstallation) claims.responder_installation = o.responderInstallation;
  return { jws: signCompact(key, { alg: 'EdDSA', typ: TYP_QC_INVITATION, kid: jwk.kid, jwk }, claims), claims };
}

export function verifyInvitation(token: string, o: { responderOrigin: string; replay: ReplayStore; now?: number; responderInstallation?: string; allowedPorts?: number[] }): { claims: Claims; jwk: PublicJwk } {
  if (typeof token === 'string' && token.length > QC_MAX_INVITATION_LENGTH) throw ce('too_large', 'invitation too large', 413);
  const key = headerKey(token, TYP_QC_INVITATION);
  let c: Claims;
  try {
    c = verifyCompact(token, key, { typ: TYP_QC_INVITATION, now: o.now, maxLifetime: QC_INVITATION_MAX_LIFETIME, skew: QC_SKEW,
      required: ['protocol', 'ext', 'iss', 'aud', 'iat', 'exp', 'jti', 'attempt', 'app', 'base', 'redirect_uri', 'egress', 'code_challenge', 'code_challenge_method', 'nonce', 'extensions'] });
  } catch (e) {
    if (e instanceof ConnectError && e.code === 'expired') throw ce('invitation_expired', 'invitation expired');
    throw e;
  }
  checkExtensionClaims(c);
  if (c.aud !== qcOriginOf(o.responderOrigin)) throw ce('wrong_audience', 'invitation is for another application');
  if ('responder_installation' in c && c.responder_installation !== o.responderInstallation) throw ce('wrong_audience', 'invitation is for another installation');
  requireStr(c, 'iss', UUID_V); requireStr(c, 'jti', JTI_RE); requireStr(c, 'attempt', UUID_V);
  if (!c.app || typeof c.app !== 'object' || c.app.installation_id !== c.iss) throw ce('invalid_request', 'app identity does not match the issuer');
  if (c.code_challenge_method !== 'S256') throw ce('invalid_request', 'only S256 is accepted');
  if (typeof c.code_challenge !== 'string' || c.code_challenge.length !== 43 || !B64URL_RE.test(c.code_challenge)) throw ce('invalid_request', 'code_challenge malformed');
  if (typeof c.nonce !== 'string' || c.nonce.length < 22 || c.nonce.length > 128 || !B64URL_RE.test(c.nonce)) throw ce('invalid_request', 'nonce malformed');
  const scopes = c.requested_scopes ?? [];
  if (!Array.isArray(scopes) || !scopes.every((s: unknown) => typeof s === 'string')) throw ce('invalid_request', 'requested_scopes must be a list of strings');
  checkBase(c.base, o.allowedPorts ?? [443]);
  checkRedirectUri(c.redirect_uri, c.base);
  validateEgress(c.egress);
  checkSignedExtensions(c);
  if (!o.replay.add(QC_NS_INVITATION, `${c.iss}:${c.jti}`, c.exp + QC_SKEW)) throw ce('invitation_used', 'invitation already used');
  return { claims: c, jwk: publicJwk(key) };
}

// --- accept -------------------------------------------------------------------------------

export function buildAccept(key: KeyObject, o: { responderApp: App; invitation: Claims; invitationJws: string; connectionId: string; base: string; egress: (string | EgressEntry)[]; code: string; extensions?: Extensions; now?: number; lifetime?: number }): string {
  const iat = nowS(o.now);
  const jwk = publicJwk(key);
  return signCompact(key, { alg: 'EdDSA', typ: TYP_QC_ACCEPT, kid: jwk.kid, jwk }, {
    protocol: PROTOCOL_ID_1_1, ext: BOOTSTRAP_ID, extensions: signedExtensions(o.extensions ?? SUPPORTED_EXTENSIONS),
    iss: o.responderApp.installation_id, aud: o.invitation.iss, iat, exp: iat + (o.lifetime ?? QC_ACCEPT_MAX_LIFETIME),
    attempt: o.invitation.attempt, invitation: o.invitation.jti, invitation_sha256: sha256Hex(o.invitationJws),
    connection_id: o.connectionId, app: appOf(o.responderApp), base: o.base, egress: egressEntries(o.egress), code_sha256: sha256Hex(o.code),
  });
}

export function verifyAccept(token: string, o: { invitation: Claims; invitationJws: string; code: string; now?: number; allowedPorts?: number[] }): { claims: Claims; jwk: PublicJwk } {
  const key = headerKey(token, TYP_QC_ACCEPT);
  const c: Claims = verifyCompact(token, key, { typ: TYP_QC_ACCEPT, now: o.now, maxLifetime: QC_ACCEPT_MAX_LIFETIME, skew: QC_SKEW,
    required: ['protocol', 'ext', 'extensions', 'iss', 'aud', 'iat', 'exp', 'attempt', 'invitation', 'invitation_sha256', 'connection_id', 'app', 'base', 'egress', 'code_sha256'] });
  checkExtensionClaims(c);
  if (c.aud !== o.invitation.iss) throw ce('wrong_audience', 'acceptance is for another installation', 401);
  if (c.invitation !== o.invitation.jti || c.attempt !== o.invitation.attempt || c.invitation_sha256 !== sha256Hex(o.invitationJws)) throw ce('wrong_attempt', 'acceptance is for another attempt', 401);
  if (typeof o.code !== 'string' || !safeEq(c.code_sha256, sha256Hex(o.code))) throw ce('invalid_grant', 'code does not belong to this acceptance', 401);
  requireStr(c, 'iss', UUID_V); requireStr(c, 'connection_id', UUID_V);
  if (!c.app || typeof c.app !== 'object' || c.app.installation_id !== c.iss) throw ce('invalid_request', 'app identity does not match the issuer');
  checkBase(c.base, o.allowedPorts ?? [443]);
  if (qcOriginOf(c.base) !== o.invitation.aud) throw ce('destination_mismatch', 'the answering application is not the approved destination', 401);
  validateEgress(c.egress);
  checkSignedExtensions(c);
  return { claims: c, jwk: publicJwk(key) };
}

export function checkDiscoveredIdentity(accept: Claims, discoveryDoc: Record<string, any>, discoveryUrl: string): Record<string, number> {
  if (!discoveryDoc?.app || discoveryDoc.app.installation_id !== accept.iss) throw ce('identity_mismatch', 'discovery identity differs from the signed acceptance', 403);
  const adv = advertisedExtensions(discoveryDoc, discoveryUrl);
  checkNoDowngrade(accept.extensions ?? {}, adv);
  const negotiated = negotiateExtensions(adv);
  if (pairingFlow(negotiated) !== BOOTSTRAP_ID) throw ce('downgrade_detected', 'qc-bootstrap/1 not negotiated', 403);
  return negotiated;
}

// --- exchange -----------------------------------------------------------------------------

export function buildExchange(key: KeyObject, o: { invitation: Claims; accept: Claims; acceptJws: string; code: string; codeVerifier: string; initiatorApp: App; discoveryUrl: string; requestedScopes: string[]; proposedTenants?: { id: string; label?: string }[]; now?: number; jti?: string; lifetime?: number }): { jws: string; claims: Claims } {
  const lifetime = o.lifetime ?? 60;
  if (!(lifetime > 0 && lifetime <= QC_EXCHANGE_MAX_LIFETIME)) throw new Error('lifetime out of range');
  const iat = nowS(o.now);
  const jwk = publicJwk(key);
  const claims: Claims = {
    protocol: PROTOCOL_ID_1_1, ext: BOOTSTRAP_ID, iss: o.initiatorApp.installation_id, aud: o.accept.iss, iat, exp: iat + lifetime,
    jti: o.jti ?? b64url(randomBytes(18)), code: o.code, code_verifier: o.codeVerifier, invitation: o.invitation.jti,
    accept_sha256: sha256Hex(o.acceptJws), app: appOf(o.initiatorApp), connection_id: o.invitation.attempt,
    discovery_url: o.discoveryUrl, connection_key: jwk, requested_scopes: uniqSorted(o.requestedScopes),
    proposed_tenants: (o.proposedTenants ?? []).map((t) => ({ id: String(t.id), label: String(t.label ?? '').slice(0, 200) })),
  };
  return { jws: signCompact(key, { alg: 'EdDSA', typ: TYP_QC_EXCHANGE, kid: jwk.kid }, claims), claims };
}

export function exchangeCodeSha256(token: string): string {
  try { const c = unverifiedPayload(token).code; return typeof c === 'string' && c ? sha256Hex(c) : ''; } catch { return ''; }
}

export function verifyExchange(token: string, o: { dpop: string; url: string; invitation: Claims; invitationJwk: unknown; acceptJws: string; codeSha256: string; codeExpiresAt: number; responderInstallation: string; replay: ReplayStore; now?: number }): Claims {
  const now = nowS(o.now);
  const h = unverifiedHeader(token);
  if (h.typ !== TYP_QC_EXCHANGE) throw ce('invalid_request', `expected a ${TYP_QC_EXCHANGE} token`, 401);
  const key = publicKeyFromJwk(o.invitationJwk);
  const kid = thumbprint(key);
  if (h.kid !== kid) throw ce('key_mismatch', 'exchange not signed by the invitation key', 401);
  const c: Claims = verifyCompact(token, key, { typ: TYP_QC_EXCHANGE, now, maxLifetime: QC_EXCHANGE_MAX_LIFETIME, skew: QC_SKEW,
    required: ['protocol', 'ext', 'iss', 'aud', 'iat', 'exp', 'jti', 'code', 'code_verifier', 'invitation', 'accept_sha256', 'app', 'connection_id', 'connection_key'] });
  checkExtensionClaims(c);
  if (c.aud !== o.responderInstallation) throw ce('wrong_audience', 'exchange is for another installation', 401);
  if (c.iss !== o.invitation.iss || c.invitation !== o.invitation.jti || c.connection_id !== o.invitation.attempt || c.accept_sha256 !== sha256Hex(o.acceptJws)) {
    throw ce('wrong_attempt', 'exchange is for another attempt', 401);
  }
  const announced = rewrap('key_mismatch', () => thumbprint(publicKeyFromJwk(c.connection_key)));
  if (announced !== kid) throw ce('key_mismatch', 'connection_key is not the invitation key', 401);
  if (!c.app || typeof c.app !== 'object' || c.app.installation_id !== c.iss) throw ce('invalid_request', 'app identity does not match the issuer');
  requireStr(c, 'jti', JTI_RE);
  if (!Array.isArray(c.requested_scopes ?? [])) throw ce('invalid_request', 'requested_scopes must be a list');
  if (typeof c.code !== 'string' || !safeEq(sha256Hex(c.code), o.codeSha256 ?? '')) throw ce('invalid_grant', 'unknown authorisation code');
  if (now >= o.codeExpiresAt) throw ce('code_expired', 'authorisation code expired');
  if (typeof c.code_verifier !== 'string' || !VERIFIER_RE.test(c.code_verifier)) throw ce('invalid_request', 'code_verifier malformed');
  if (!safeEq(pkceChallenge(c.code_verifier), String(o.invitation.code_challenge))) throw ce('pkce_mismatch', 'code_verifier does not match the challenge');
  verifyDpopProof(o.dpop, { method: 'POST', url: o.url, replay: o.replay, now, expectedJkt: kid });
  if (!o.replay.add(QC_NS_EXCHANGE, `${c.iss}:${c.jti}`, c.exp + QC_SKEW)) throw ce('replayed', 'exchange already submitted', 401);
  if (!o.replay.add(QC_NS_CODE, o.codeSha256, o.codeExpiresAt + QC_SKEW)) throw ce('code_used', 'authorisation code already used');
  return c;
}

// --- transcript and SAS -----------------------------------------------------------------

export function qcTranscriptHash(o: { invitationJws: string; acceptJws: string; exchangeJws: string; initiatorInstallation: string; initiatorJkt: string; initiatorEgress: string[]; responderInstallation: string; responderJkt: string; responderEgress: string[]; destinationHost: string; destinationPort: number }): string {
  return sha256Hex(canonicalJson({
    v: `${PROTOCOL_ID_1_1} qc-transcript`,
    invitation_sha256: sha256Hex(o.invitationJws), accept_sha256: sha256Hex(o.acceptJws), exchange_sha256: sha256Hex(o.exchangeJws),
    initiator: { installation_id: o.initiatorInstallation, jkt: o.initiatorJkt, egress: o.initiatorEgress },
    responder: { installation_id: o.responderInstallation, jkt: o.responderJkt, egress: o.responderEgress },
    destination: { host: o.destinationHost, port: o.destinationPort },
  }));
}

export function qcTranscriptFromMessages(invitationJws: string, acceptJws: string, exchangeJws: string): string {
  const inv = unverifiedPayload(invitationJws) as Claims, acc = unverifiedPayload(acceptJws) as Claims;
  const ka = publicKeyFromJwk(unverifiedHeader(invitationJws).jwk), kb = publicKeyFromJwk(unverifiedHeader(acceptJws).jwk);
  const { host, port } = originHostPort(inv.aud);
  return qcTranscriptHash({ invitationJws, acceptJws, exchangeJws, initiatorInstallation: inv.iss, initiatorJkt: thumbprint(ka),
    initiatorEgress: egressNets(inv.egress), responderInstallation: acc.iss, responderJkt: thumbprint(kb), responderEgress: egressNets(acc.egress),
    destinationHost: host, destinationPort: port });
}

/** The v1 SAS function applied to the 1.1 transcript. */
export const qcSas = (transcript: string) => shortAuthenticationString(transcript);

export function checkAckKey(ackJwk: unknown, acceptJwk: unknown): void {
  if (thumbprint(publicKeyFromJwk(ackJwk)) !== thumbprint(publicKeyFromJwk(acceptJwk))) throw ce('key_mismatch', 'ack not signed by the acceptance key', 401);
}

// --- qc-diagnostics/1 ------------------------------------------------------------------

export const PROBE_SOURCE_CHECKS = ['ok', 'not_authorised', 'not_enforced'];
export const probeRequestBody = (nonce?: string) => (nonce ? { nonce } : {});

function canonicalAddress(s: unknown): string | null {
  const a = addrOf(s as string);
  if (!a) return null;
  return a.v === 4 ? formatV4(a.addr) : formatV6(a.addr);
}

export function validateProbeResponse(obj: unknown, nonce?: string): Record<string, unknown> {
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) throw ce('invalid_request', 'probe response must be an object');
  const r = obj as Record<string, any>;
  const canon = canonicalAddress(r.observed_source);
  if (canon === null) throw ce('invalid_request', 'observed_source malformed');
  if (canon !== r.observed_source) throw ce('invalid_request', 'observed_source not canonical');
  if (!isInt(r.server_time)) throw ce('invalid_request', 'server_time malformed');
  if (!r.checks || typeof r.checks !== 'object' || !PROBE_SOURCE_CHECKS.includes(r.checks.source) || r.checks.token !== 'ok') throw ce('invalid_request', 'checks malformed');
  if (typeof r.connection_state !== 'string') throw ce('invalid_request', 'connection_state malformed');
  if (r.peer_reached_at !== null && r.peer_reached_at !== undefined && !isInt(r.peer_reached_at)) throw ce('invalid_request', 'peer_reached_at malformed');
  if (nonce !== undefined && r.nonce !== nonce) throw ce('invalid_request', 'probe nonce not echoed');
  return r;
}

export function buildProbeResponse(o: { observedSource: string; serverTime: number; connectionState: string; sourceCheck: string; tokenCheck?: string; peerReachedAt?: number | null; nonce?: string }): Record<string, unknown> {
  const out: Record<string, unknown> = {
    protocol: PROTOCOL_ID_1_1, observed_source: canonicalAddress(o.observedSource) ?? o.observedSource, server_time: o.serverTime,
    connection_state: o.connectionState, checks: { source: o.sourceCheck, token: o.tokenCheck ?? 'ok' }, peer_reached_at: o.peerReachedAt ?? null,
  };
  if (o.nonce) out.nonce = o.nonce;
  return validateProbeResponse(out, o.nonce);
}
