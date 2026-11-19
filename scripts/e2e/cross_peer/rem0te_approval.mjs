#!/usr/bin/env node
/**
 * Test-only approval machinery for the cross-peer run's remediation chain
 * (s12/s13), built from Rem0te's own pieces the way its e2e-approved-action
 * suite does: the offline release tool (RELEASE_BIN, rem0te-release) for a
 * signed update repository carrying a stand-in agent build and the signer's
 * approval/keys.json; the approval signer's own CLI for its key and roster;
 * synthetic passkeys (a port of Rem0te's scripts/lib/synthetic-passkey.mjs
 * whose private key is kept in a file, so one approver can answer across
 * separate invocations) that the signer's real WebAuthn verification checks.
 *
 * Everything lives in the run's work directory and Rem0te's scratch database
 * (the name must contain "scratch" or "test"). Nothing here touches a real
 * signer, roster or update repository. Prints one JSON object on stdout.
 *
 *   node rem0te_approval.mjs release '{work, releaseBin}'
 *        → {repo, signerDir, agentSha256, keysFile}
 *   node rem0te_approval.mjs enrol '{work, api, members: [{tag, userId, approve: [...], customer: [...]}]}'
 *        → {tag: {fingerprint, added}} — sets a password, a passkey, reads the export from the portal's
 *          own Passkeys list, and adds it to the signer's roster with the fingerprint read back
 *   node rem0te_approval.mjs approve '{work, jobId, tag, origin, publicUrl, decision?}'
 *        → {status, body} of the signer's /decide (or of /challenge when that refused)
 */
import { createRequire } from 'node:module';
import { createHash, generateKeyPairSync, createPrivateKey, randomBytes, sign } from 'node:crypto';
import { execFileSync, spawnSync } from 'node:child_process';
import { chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';

const SRC = process.env.REM0TE_SRC;
if (!SRC) { console.error('REM0TE_SRC is required'); process.exit(2); }
const API_DIR = path.join(SRC, 'apps', 'api');
const require = createRequire(path.join(API_DIR, 'package.json'));
const DB = process.env.DATABASE_URL ?? '';
const dbName = DB.split('/').pop()?.split('?')[0] ?? '';
if (!/scratch|test/.test(dbName)) {
  console.error(`Refusing to run against database "${dbName}": name must contain "scratch" or "test".`);
  process.exit(2);
}
const SIGNER_MAIN = path.join(API_DIR, 'dist', 'approval-signer', 'main.js');
const sha = (b) => createHash('sha256').update(b).digest('hex');
const b64u = (b) => Buffer.from(b).toString('base64url');
const [, , cmd, arg = '{}'] = process.argv;
const input = JSON.parse(arg);

const signerDirOf = (work) => path.join(work, 'signer');
function signerCli(work, args) {
  const env = { ...process.env, APPROVAL_SIGNER_DIR: signerDirOf(work) };
  delete env.DATABASE_URL; // the signer has no database
  return spawnSync(process.execPath, [SIGNER_MAIN, ...args], { encoding: 'utf8', env });
}

async function release({ work, releaseBin }) {
  if (!releaseBin || !existsSync(releaseBin)) throw new Error('RELEASE_BIN (rem0te-release) is required');
  const base = path.join(work, 'release');
  const keys = path.join(base, 'keys'), files = path.join(base, 'files'), repo = path.join(base, 'repo');
  mkdirSync(keys, { recursive: true }); mkdirSync(files, { recursive: true });
  mkdirSync(signerDirOf(work), { recursive: true, mode: 0o700 });
  const rel = (...a) => execFileSync(releaseBin, a, { encoding: 'utf8' });
  for (const k of ['r1', 'r2', 'r3', 'targets', 'snapshot', 'timestamp']) rel('keygen', '-out', path.join(keys, `${k}.pem`));
  rel('init', '-repo', repo, '-root-key', path.join(keys, 'r1.pem'), '-root-key', path.join(keys, 'r2.pem'), '-root-key', path.join(keys, 'r3.pem'),
    '-root-threshold', '2', '-targets-key', path.join(keys, 'targets.pem'), '-snapshot-key', path.join(keys, 'snapshot.pem'), '-timestamp-key', path.join(keys, 'timestamp.pem'));
  // A stand-in agent build (Rem0te's own suite does the same): the plan names its digest.
  const slot = Buffer.concat([Buffer.from('REM0TE_INST_URL:'), Buffer.alloc(240)]);
  const agentBin = Buffer.concat([Buffer.from('MZ stand-in signed agent (cross-peer e2e) '), randomBytes(64), slot]);
  writeFileSync(path.join(files, 'agent.exe'), agentBin);
  const kg = signerCli(work, ['keygen']);
  if (kg.status !== 0) throw new Error(`signer keygen: ${kg.stderr}`);
  const keysFile = path.join(files, 'approval-keys.json');
  writeFileSync(keysFile, kg.stdout);
  rel('release', '-repo', repo, '-targets-key', path.join(keys, 'targets.pem'), '-snapshot-key', path.join(keys, 'snapshot.pem'),
    '-timestamp-key', path.join(keys, 'timestamp.pem'), '-add', `windows/rem0te-agent.exe=${path.join(files, 'agent.exe')}`,
    '-add', `approval/keys.json=${keysFile}`);
  return { repo, signerDir: signerDirOf(work), agentSha256: sha(agentBin), keysFile };
}

// ── Synthetic passkeys (format identical to scripts/lib/synthetic-passkey.mjs) ──
const pkFile = (work, tag) => path.join(work, 'passkeys', `${tag}.json`);
function newPasskey(work, tag, userId, name) {
  const { privateKey, publicKey } = generateKeyPairSync('ec', { namedCurve: 'P-256' });
  const jwk = publicKey.export({ format: 'jwk' });
  const cose = Buffer.concat([
    Buffer.from([0xa5, 0x01, 0x02, 0x03, 0x26, 0x20, 0x01, 0x21, 0x58, 0x20]), Buffer.from(jwk.x, 'base64url'),
    Buffer.from([0x22, 0x58, 0x20]), Buffer.from(jwk.y, 'base64url'),
  ]);
  const st = { userId, name, credentialId: b64u(randomBytes(16)), publicKey: b64u(cose), counter: 0,
    privateKeyPem: privateKey.export({ type: 'pkcs8', format: 'pem' }).toString() };
  mkdirSync(path.dirname(pkFile(work, tag)), { recursive: true, mode: 0o700 });
  writeFileSync(pkFile(work, tag), JSON.stringify(st)); chmodSync(pkFile(work, tag), 0o600);
  return st;
}
function assertion(work, tag, options, origin) {
  const st = JSON.parse(readFileSync(pkFile(work, tag), 'utf8'));
  st.counter += 1;
  writeFileSync(pkFile(work, tag), JSON.stringify(st));
  const clientDataJSON = Buffer.from(JSON.stringify({ type: 'webauthn.get', challenge: options.challenge, origin, crossOrigin: false }));
  const ctr = Buffer.alloc(4); ctr.writeUInt32BE(st.counter);
  const authData = Buffer.concat([createHash('sha256').update(options.rpId).digest(), Buffer.from([0x01 | 0x04]), ctr]);
  const sig = sign('sha256', Buffer.concat([authData, createHash('sha256').update(clientDataJSON).digest()]), createPrivateKey(st.privateKeyPem));
  return {
    id: st.credentialId, rawId: st.credentialId, type: 'public-key', clientExtensionResults: {},
    response: { clientDataJSON: b64u(clientDataJSON), authenticatorData: b64u(authData), signature: b64u(sig), userHandle: b64u(Buffer.from(st.userId)) },
  };
}

async function enrol({ work, api, members }) {
  const { PrismaClient } = require('@prisma/client');
  const argon2 = require('argon2');
  const prisma = new PrismaClient();
  const out = {};
  try {
    const pw = `cp-e2e-${randomBytes(12).toString('hex')}`; // test-only, never printed
    const hash = await argon2.hash(pw, { type: argon2.argon2id });
    for (const m of members) {
      const u = await prisma.user.update({ where: { id: m.userId }, data: { passwordHash: hash } });
      const k = newPasskey(work, m.tag, u.id, [u.firstName, u.lastName].filter(Boolean).join(' '));
      await prisma.userMfaMethod.create({ data: { userId: u.id, type: 'WEBAUTHN', isActive: true, credentialId: k.credentialId, publicKey: Buffer.from(k.publicKey, 'base64url'), signCount: 0, name: 'Cross-peer e2e key' } });
      // The roster ceremony: the export and fingerprint come from the person's own Passkeys list.
      const ipAddr = `10.77.${(Math.random() * 250) | 0}.${1 + ((Math.random() * 250) | 0)}`;
      const lr = await fetch(`${api}/auth/login`, { method: 'POST', headers: { 'content-type': 'application/json', 'x-forwarded-for': ipAddr }, body: JSON.stringify({ email: u.email, password: pw }) });
      const tok = (lr.headers.get('set-cookie') ?? '').match(/access_token=([^;]+)/);
      if (lr.status !== 200 || !tok) throw new Error(`login ${m.tag}: HTTP ${lr.status} ${(await lr.text()).slice(0, 300)}`);
      const list = await fetch(`${api}/auth/passkeys`, { headers: { cookie: `access_token=${tok[1]}`, 'x-forwarded-for': ipAddr } });
      const body = await list.json();
      const mine = (body?.data ?? body ?? []).find((p) => p.approvalExport && JSON.parse(p.approvalExport).credentialId === k.credentialId);
      if (!mine) throw new Error(`no approval export for ${m.tag}: HTTP ${list.status}`);
      const args = ['roster', 'add', '--export', mine.approvalExport, '--confirm-fingerprint', mine.approvalFingerprint];
      if (m.approve?.length) args.push('--approve', m.approve.join(','));
      if (m.customer?.length) args.push('--customer', m.customer.join(','));
      const add = signerCli(work, args);
      if (add.status !== 0) throw new Error(`roster add ${m.tag}: ${add.stderr}`);
      out[m.tag] = { fingerprint: mine.approvalFingerprint, added: true };
    }
  } finally {
    await prisma.$disconnect();
  }
  return out;
}

async function approve({ work, jobId, tag, origin, publicUrl, decision = 'approve', role = 'approver' }) {
  const post = async (p, body) => {
    const r = await fetch(`${publicUrl}/approve/${jobId}${p}`, { method: 'POST', headers: { 'content-type': 'application/json', origin }, body: JSON.stringify(body) });
    let b = null; try { b = await r.json(); } catch { /* html */ }
    return { status: r.status, body: b };
  };
  const c = await post('/challenge', { decision, role });
  if (c.status !== 200) return c;
  return post('/decide', { challengeId: c.body.challengeId, assertion: assertion(work, tag, c.body.options, origin) });
}

const handlers = { release, enrol, approve };
try {
  if (!handlers[cmd]) throw new Error(`unknown command ${cmd}`);
  process.stdout.write(JSON.stringify((await handlers[cmd](input)) ?? null));
} catch (e) {
  console.error(e.stack ?? String(e));
  process.exitCode = 1;
}
