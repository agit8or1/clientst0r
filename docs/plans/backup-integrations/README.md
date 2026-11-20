# Backup integrations — St0r/UrBackup, Comet Backup and unified backup management

Specification for roadmap Phase 74.7–74.12, 77.8 and 92.6 (directive of 2026-11-20). **Planned; nothing here is
built yet.** Priority P1, after the Stage 1 (P0) core. No backup engine inside Clientst0r: St0r (with UrBackup
underneath) and Comet stay independent backup products, and Clientst0r reads from them and, later, requests
permissioned actions through their own APIs.

## What exists today (Phase 74.1–74.2, shipped v3.17.695)

- `backup_monitoring` app: `BackupConnection` (several per provider; MSP-wide or per customer, with per-customer
  mapping; sealed credentials; TLS verification on; private addresses refused unless allowed), `ProtectedSystem`,
  `BackupJob`, `BackupRun`, `BackupRepository` (capacity), `RestoreTest`, `BackupAlertPolicy`, `BackupAlert`
  with ticket creation; customer and device views; stale data shown as stale.
- Providers behind `backup_monitoring/providers/base.py` (`test_connection`, `list_jobs`, `list_runs`,
  `list_repositories`): Proxmox Backup Server polling, and signed push reports for restic, Borg and Kopia.
- Documentation: `docs/BACKUP_MONITORING.md`.

Every addition below is a new provider class or an extension of these models. Nothing creates a second backup
module, alert path or billing path.

## St0r / UrBackup (74.7)

### St0r as it is today

Audit of St0r v3.2.140 (`9e1a0a39`, 2026-11-20, static read):

- Node/Express backend with its own MariaDB; manages **one** UrBackup server on the same host, through
  UrBackup's local HTTP API and its SQLite databases.
- Has customers and customer-scoped read-only users.
- API is unversioned (`/api/*`), undocumented, and authenticated by password login that issues a 24-hour JWT
  in a cookie. No integration tokens, scopes or service accounts.
- Read data a scoped user can get: clients, file and image status, last backup times, job history, running
  jobs, per-client usage, effective schedule and retention, recovery-drill results. Server storage and
  replication are administrator-only.
- Start backup and restore exist but are administrator-only, not idempotent and not audited; webhooks are
  unsigned.

**Conclusion:** St0r has no API that Clientst0r can use safely today. Clientst0r will not log in with a
password or scrape a cookie. 74.7 waits for the St0r API below, which is recorded in the St0r repository's
roadmap.

### St0r API that Clientst0r needs (St0r roadmap items)

Read-only first, all under `/api/v1/`, JSON, described by OpenAPI:

1. **Integration tokens:** hashed, shown once, named, scoped (`backup:read`, `replication:read`,
   `recovery:read`, `server:read`; later `actions:start_backup`, `actions:restore_request`), optional customer
   allowlist and source-address allowlist, expiry, rotation with an overlap window, revocation, per-token rate
   limit, a log of each call.
2. `GET /api/v1/health` — UrBackup reachable, collector age, St0r version.
3. `GET /api/v1/customers`, `GET /api/v1/endpoints?customer=&updated_since=` — stable identifiers.
4. Backup status per endpoint: last file and image success and failure, current state; paged bulk form.
5. Jobs history and running jobs, with stable job identifiers.
6. Effective schedule and retention (no secrets).
7. Storage, replication (status, lag, last success) and restore-verification results, marking simulated vs real.
8. `GET /api/v1/events?since=<cursor>` and signed webhooks with retry and a delivery log.
9. No secrets or host paths in any response.

Actions (second step): start backup with a required idempotency key (202 + request id); restore as an
approval-gated **request** resource with an immutable audit trail; a queryable audit log.

St0r hygiene noted by the audit and recorded for St0r: stop logging UrBackup session data, enforce HTTPS for the
integration API, CORS locked by default, administrator data endpoints not readable by every signed-in user.

### Clientst0r side

- One `BackupConnection` per St0r installation (several allowed): URL, token (sealed), customer and site
  mapping, polling interval, alert settings, management permission level.
- Poll `/api/v1` with `updated_since` cursors; later consume the signed events feed.
- Protected clients become `ProtectedSystem` rows, matched to assets (see coverage below).
- Health and storage map to `BackupRepository`; replication and recovery verification to `RestoreTest` plus
  two new run kinds.
- Connection test reports St0r version, token scopes and which data are available.

## Comet Backup (74.8)

Researched against Comet's official API documentation; details and sources in
[COMET_API_NOTES.md](COMET_API_NOTES.md).

What the documentation shows (see the notes for sources and the points not confirmed):

- The Management Console API is form-encoded POST under `/api/v1/admin/...`, available on self-hosted and
  Comet-hosted consoles; authentication is an administrator user name with a password (plus TOTP or WebAuthn if
  enabled), a session key, or — from about 26.8.x — a personal administrator API token (default expiry 90
  days, shown once, server option `AllowAdminAPITokens`).
- Least privilege: an administrator account flagged **read-only** (`PreventWriteActions`, 26.8.2+) blocks every
  write. Clientst0r therefore uses **two accounts**: a read-only one for polling, and — only once 74.11 is
  switched on — a separate, tenant-scoped account for starting backups and restores. Tenant administrators are
  limited to their tenant.
- Data: `list-users-full` / `get-user-profile` (devices, protected items, destinations, policies, retention),
  `get-jobs-for-date-range` (history; running jobs too), per-item statistics for last success, `meta/stats` and
  `meta/version`. Job status codes: 5xxx success, 6xxx running, 7xxx failed.
- Webhooks are configured per tenant and are **not signed** (only static custom headers and a tracing id), with
  limited retries and no ordering guarantee. Clientst0r treats a webhook only as a hint to poll; the poll result
  is what is recorded. A static header secret is still required so random posts are dropped.
- Actions (`dispatcher/run-backup`, `run-backup-custom`, `run-restore`) need the device to be live-connected;
  an offline device is shown as such and never queued silently.

Clientst0r side:

- One `BackupConnection` per Comet Management Server (several allowed), each mapped to customers (Comet users
  or tenants map to Clientst0r customers explicitly; no name guessing).
- Read: users, devices, protected items, storage vaults, policies, job history, last success per item, storage
  use, retention, restore activity, licensing and usage counts — only what the connected server version and
  the administrator account's permissions provide; the connection test records which.
- Devices map to existing assets by stable Comet identifiers; no duplicate inventory records.
- Actions later (74.11): start backup and request restore through Comet's documented dispatcher calls, only
  for devices that are online, under a dedicated permission; provider-administrator operations are never
  offered to ordinary technicians.
- Failure workflow: Comet job failure → Clientst0r event (deduplicated by Comet job identity) → customer and
  device association → ticket → assignment → investigation → resolution verified by a later successful job →
  ticket closure.

## Unified backup management (74.9–74.12)

### Overview page

One page across all providers: customer, site, device, provider, protection status, last success, backup age
against the RPO, replication, restore verification, storage use, open alerts, related tickets; filters for
customer, site, provider, device and status.

### Protection coverage

Compare the asset inventory with every provider's protected systems:

| State | Meaning |
|---|---|
| Protected (verified) | Matched, last success within the RPO |
| Failed | Matched, last run failed |
| Overdue | Matched, last success older than the RPO |
| Not protected | Asset in a class that needs backup, and an administrator confirmed no provider covers it |
| Unknown | No match yet, or no data — **never shown as unprotected** |

Matching uses stable identifiers first (provider device id linked once, then remembered), with hostname and
serial suggestions that a technician confirms.

### Alerts and tickets (74.10)

Failed, missed or overdue backups; unprotected devices; storage near capacity; replication failures and lag;
failed restore tests; server offline; protection outside the RPO. Deduplicated by provider event identity;
existing `BackupAlertPolicy` and alert-to-ticket policy reused; events also written to the Phase 82 event layer.

### Actions (74.11)

Offered only when the connection reports the capability. Start backup: permission `backup.run`. Restore request:
permission `backup.restore`, step-up authentication, a reason, an audit record, and the provider's own approval
where it has one. Nothing destructive by default; no automation starts a restore.

### Customer portal (77.8)

Protected-device counts, health summary, latest backup, restore verification, backup tickets. Never backup
contents, paths, credentials or provider configuration.

### Billing (92.6)

Per protected device, server, workstation or licensed user; per GB/TB only where the provider's measurement is
reliable; or a fixed monthly service. Counts go through the verified-usage review in Phase 92; no automatic
invoice change and no second billing engine.

## Security requirements

Least-privilege tokens, sealed credentials with rotation, TLS verification, customer isolation in every query
and export, explicit provider capability checks, signed events where offered, replay protection and
idempotent processing of events, an audit record for every management action, restricted restore permission,
no default destructive automation, no backup credentials or contents sent to AI.

## Acceptance (per provider)

1. Connection test against a real St0r test install / Comet test server records version and capabilities.
2. Import is idempotent: re-polling or re-delivering the same event creates no new rows, alerts or tickets.
3. A technician restricted to customer A sees no customer B backups in pages, API or exports.
4. An unmatched device shows Unknown, not Not protected.
5. A restore request without the permission or step-up is refused at the API.
