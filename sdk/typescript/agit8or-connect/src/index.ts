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
