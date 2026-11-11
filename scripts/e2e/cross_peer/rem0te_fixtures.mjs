#!/usr/bin/env node
/**
 * Synthetic Rem0te fixtures for the cross-peer run, written with Rem0te's own
 * Prisma client (resolved from REM0TE_SRC/apps/api). Refuses any database
 * whose name does not contain "scratch" or "test", like Rem0te's own e2e
 * scripts. Prints one JSON object on stdout.
 *
 *   node rem0te_fixtures.mjs setup '<json>'      → businesses, users, mappings, endpoints, monitors
 *   node rem0te_fixtures.mjs caps '<json>'       → {userId, customerId, capabilities} on the membership
 *   node rem0te_fixtures.mjs mapping '<json>'    → {peerId, externalOrgId, externalTechnicianId, revoked}
 *   node rem0te_fixtures.mjs job '<json>'        → {id} → the integration job row (status, errorCode)
 *   node rem0te_fixtures.mjs alert '<json>'      → {endpointId} → open alerts for the computer
 *   node rem0te_fixtures.mjs deliveries '<json>' → {peerId} → alert events and whether each was acknowledged
 *   node rem0te_fixtures.mjs retryNow '<json>'   → {peerId} → bring Rem0te's next delivery attempt forward
 *   node rem0te_fixtures.mjs pause '<json>'      → {customerId, kinds, reason} → a business containment pause
 *   node rem0te_fixtures.mjs unpause '<json>'    → {id} → lift it
 *   node rem0te_fixtures.mjs rebootRule '<json>' → {customerId} → a REBOOT_PENDING (1 h) monitor rule
 *   node rem0te_fixtures.mjs rebootSince '<json>'→ {endpointId, minutes} → backdate the pending restart
 *   node rem0te_fixtures.mjs cleanup '<json>'    → remove what setup created
 */
import { createRequire } from 'node:module';
import { createHash, randomBytes } from 'node:crypto';
import path from 'node:path';

const SRC = process.env.REM0TE_SRC;
if (!SRC) { console.error('REM0TE_SRC is required'); process.exit(2); }
const require = createRequire(path.join(SRC, 'apps', 'api', 'package.json'));
const { PrismaClient } = require('@prisma/client');

const DB = process.env.DATABASE_URL ?? '';
const dbName = DB.split('/').pop()?.split('?')[0] ?? '';
if (!/scratch|test/.test(dbName)) {
  console.error(`Refusing to run against database "${dbName}": name must contain "scratch" or "test".`);
  process.exit(2);
}
const prisma = new PrismaClient();
const sha = (b) => createHash('sha256').update(b).digest('hex');
const [, , cmd, arg = '{}'] = process.argv;
const input = JSON.parse(arg);

async function setup({ peerId, sfx, orgs, techs, endpoints }) {
  const tenant = await prisma.tenant.findFirst({ orderBy: { createdAt: 'asc' } });
  if (!tenant) throw new Error('seed the scratch database first (prisma migrate deploy; prisma db seed)');
  const roleUser = await prisma.role.findFirst({ where: { type: 'BUSINESS_USER' } });
  const roleOwner = await prisma.role.findFirst({ where: { type: 'BUSINESS_OWNER' } });
  const out = { tenantId: tenant.id, businesses: {}, users: {}, owners: {}, endpoints: {}, apiKeys: {} };
  for (const o of orgs) {
    const c = await prisma.customer.create({ data: { tenantId: tenant.id, name: `${o.name} ${sfx}` } });
    out.businesses[o.ext] = c.id;
    await prisma.integrationOrgMapping.create({ data: { peerId, externalOrgId: o.ext, customerId: c.id, tenantId: tenant.id, createdById: 'cross-peer-e2e' } });
    // Disk below 30% free is critical for this business; tickets offered from WARNING.
    await prisma.monitorRule.create({ data: { scopeKey: `b:${c.id}`, customerId: c.id, key: 'disk-free', kind: 'DISK_FREE', name: 'System disk (e2e)', severity: 'CRITICAL', params: { minFreePercent: 30 }, createdById: 'cross-peer-e2e' } });
    await prisma.monitorNotifyPolicy.create({ data: { scopeKey: `b:${c.id}`, customerId: c.id, levels: [], ticketing: { enabled: true, minSeverity: 'WARNING' }, updatedById: 'cross-peer-e2e' } });
    // A read-only inventory key, the one ClientSt0r's device sync uses. Rem0te
    // honours a key only while its creator is an active owner of the business.
    const owner = await prisma.user.create({ data: { email: `cp-owner-${o.ext}-${sfx}@test.invalid`, passwordHash: 'x', firstName: 'CP', lastName: `owner ${o.ext}`, status: 'ACTIVE' } });
    await prisma.membership.create({ data: { userId: owner.id, tenantId: tenant.id, customerId: c.id, roleId: roleOwner.id } });
    out.owners[o.ext] = owner.id;
    const raw = `rk_${randomBytes(24).toString('hex')}`;
    await prisma.apiKey.create({ data: { tenantId: tenant.id, customerId: c.id, createdById: owner.id, name: `cross-peer ${sfx}`, keyHash: sha(raw), keyPrefix: raw.slice(0, 12), scopes: ['computers:read'] } });
    out.apiKeys[o.ext] = raw;
  }
  for (const t of techs) {
    const u = await prisma.user.create({ data: { email: `cp-${t.ext}-${sfx}@test.invalid`, passwordHash: 'x', firstName: 'CP', lastName: t.ext, status: 'ACTIVE' } });
    out.users[`${t.org}/${t.ext}`] = u.id;
    await prisma.membership.create({ data: { userId: u.id, tenantId: tenant.id, customerId: out.businesses[t.org], roleId: roleUser.id, capabilities: t.caps } });
    await prisma.integrationTechnicianMapping.create({ data: { peerId, externalOrgId: t.org, externalTechnicianId: t.ext, userId: u.id, createdById: 'cross-peer-e2e' } });
  }
  for (const e of endpoints) {
    const ep = await prisma.endpoint.create({ data: { tenantId: tenant.id, customerId: out.businesses[e.org], name: e.hostname, hostname: e.hostname, status: 'ACTIVE', isOnline: true, isManaged: true, accessMode: 'COMPANY_WIDE', lastSeenAt: new Date(), agentVersion: '0.29.0', deviceClass: 'WORKSTATION' } });
    const rid = String(100000000 + ((Math.random() * 899999999) | 0));
    const secret = randomBytes(24).toString('hex');
    await prisma.rustdeskNode.create({ data: { tenantId: tenant.id, endpointId: ep.id, rustdeskId: rid, agentSecretHash: sha(secret) } });
    out.endpoints[e.org] = { id: ep.id, rid, secret, hostname: e.hostname };
  }
  return out;
}

async function caps({ userId, customerId, capabilities }) {
  const r = await prisma.membership.updateMany({ where: { userId, customerId }, data: { capabilities } });
  return { updated: r.count };
}

async function mapping({ peerId, externalOrgId, externalTechnicianId, revoked }) {
  const r = await prisma.integrationTechnicianMapping.updateMany({ where: { peerId, externalOrgId, externalTechnicianId }, data: { revokedAt: revoked ? new Date() : null } });
  return { updated: r.count };
}

async function job({ id }) {
  const j = await prisma.integrationJob.findUnique({ where: { id } });
  return j ? { status: j.status, errorCode: j.errorCode ?? null } : null;
}

async function alert({ endpointId }) {
  const a = await prisma.monitorAlert.findMany({ where: { endpointId }, orderBy: { firstSeenAt: 'asc' } });
  return a.map((x) => ({ id: x.id, state: x.state, ruleKey: x.ruleKey, severity: x.severity }));
}

async function deliveries({ peerId }) {
  const rows = await prisma.integrationAlertEvent.findMany({ where: { peerId }, orderBy: [{ externalOrgId: 'asc' }, { sequence: 'asc' }] });
  return rows.map((r) => ({ org: r.externalOrgId, sequence: r.sequence, type: r.type, alertId: r.alertId, acked: !!r.ackedAt, attempts: r.deliveryAttempts }));
}

async function retryNow({ peerId }) {
  // Bring Rem0te's next delivery attempt forward (its backoff is minutes).
  const r = await prisma.integrationAlertEvent.updateMany({ where: { peerId, ackedAt: null }, data: { nextDeliveryAt: new Date() } });
  return { updated: r.count };
}

async function pause({ customerId, kinds, reason }) {
  // A Platform Admin's containment pause for one business (Rem0te ≥ 0.30).
  const p = await prisma.containmentPause.create({ data: { scope: 'BUSINESS', customerId, kinds, reason, setById: 'cross-peer-e2e', setBy: 'msp' } });
  return { id: p.id };
}

async function unpause({ id }) {
  const r = await prisma.containmentPause.updateMany({ where: { id, clearedAt: null }, data: { clearedAt: new Date(), clearedById: 'cross-peer-e2e-2', clearReason: 'e2e done' } });
  return { updated: r.count };
}

async function rebootRule({ customerId }) {
  // REBOOT_PENDING after 1 h for this business (Rem0te's own e2e does the same).
  await prisma.monitorRule.create({ data: { scopeKey: `b:${customerId}`, customerId, key: 'reboot-pending-e2e', kind: 'REBOOT_PENDING', name: 'Restart pending (e2e)', severity: 'WARNING', params: { hours: 1 }, createdById: 'cross-peer-e2e' } });
  return { ok: true };
}

async function rebootSince({ endpointId, minutes }) {
  // The monitor counts from when Rem0te first saw the restart pending; move that back.
  const r = await prisma.endpointMonitorState.updateMany({ where: { endpointId, ruleKey: 'reboot-pending-e2e' }, data: { breachSince: new Date(Date.now() - minutes * 60_000) } });
  return { updated: r.count };
}

async function cleanup({ peerId, businesses = {}, users = {}, owners = {}, endpoints = {} }) {
  const biz = Object.values(businesses), us = [...Object.values(users), ...Object.values(owners)], eps = Object.values(endpoints).map((e) => e.id);
  const jobs = await prisma.integrationJob.findMany({ where: { customerId: { in: biz } }, select: { id: true } });
  await prisma.integrationReplayGuard.deleteMany({ where: { OR: [{ jobId: { in: jobs.map((j) => j.id) } }, { key: { startsWith: `${peerId}:` } }] } }).catch(() => {});
  await prisma.integrationJob.deleteMany({ where: { customerId: { in: biz } } });
  await prisma.integrationAlertEvent.deleteMany({ where: { peerId } }).catch(() => {});
  await prisma.integrationTechnicianMapping.deleteMany({ where: { peerId } });
  await prisma.integrationOrgMapping.deleteMany({ where: { peerId } });
  await prisma.apiKey.deleteMany({ where: { customerId: { in: biz } } });
  await prisma.containmentPause.deleteMany({ where: { customerId: { in: biz } } }).catch(() => {});
  await prisma.endpointMonitorState.deleteMany({ where: { endpointId: { in: eps } } }).catch(() => {});
  await prisma.monitorNotifyPolicy.deleteMany({ where: { customerId: { in: biz } } });
  await prisma.monitorRule.deleteMany({ where: { customerId: { in: biz } } });
  await prisma.monitorAlert.deleteMany({ where: { endpointId: { in: eps } } }).catch(() => {});
  await prisma.activityLog.deleteMany({ where: { customerId: { in: biz } } }).catch(() => {});
  await prisma.rustdeskNode.deleteMany({ where: { endpointId: { in: eps } } }).catch(() => {});
  await prisma.endpoint.deleteMany({ where: { id: { in: eps } } }).catch(() => {});
  await prisma.membership.deleteMany({ where: { userId: { in: us } } });
  await prisma.user.deleteMany({ where: { id: { in: us } } });
  await prisma.customer.deleteMany({ where: { id: { in: biz } } }).catch(() => {});
  return { ok: true };
}

const handlers = { setup, caps, mapping, job, alert, deliveries, retryNow, pause, unpause, rebootRule, rebootSince, cleanup };
try {
  if (!handlers[cmd]) throw new Error(`unknown command ${cmd}`);
  const out = await handlers[cmd](input);
  process.stdout.write(JSON.stringify(out ?? null));
} catch (e) {
  console.error(e.stack ?? String(e));
  process.exitCode = 1;
} finally {
  await prisma.$disconnect();
}
