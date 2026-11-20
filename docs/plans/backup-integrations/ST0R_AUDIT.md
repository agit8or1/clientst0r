# St0r read-only audit (for Clientst0r integration)

Repo: https://github.com/agit8or1/St0r, shallow clone (depth 50). Audited commit: 9e1a0a3935cc39109e25b5f6e2703cc92379086a (2026-11-20, "v3.2.140"). Nothing was executed. Paths are relative to repo root. "(unverified)" marks inference.

## 1. What St0r is
- Stack: Node 20+/Express 5 backend (TypeScript, `backend/src/server.ts:1-40`, `app.get('/{*splat}')` Express-5 syntax at :188), React/Vite frontend, MariaDB for St0r's own data (README "How it works"), plus a separate root-run "stor-agent" for remote hosts (`agent/src/index.ts`).
- Version: `VERSION` = 3.2.140; CHANGELOG top entry `## [3.2.140] - 2026-11-20` (CHANGELOG.md:10).
- Talks to UrBackup three ways (README "How it works"): (1) reads UrBackup SQLite DBs directly (`backend/src/config/urbackupDb.ts:8-31`, `/var/urbackup/backup_server.db`, opened read-only; a read-write opener exists for settings DB, `services/urbackup.ts:3`); (2) UrBackup HTTP API on `localhost:55414/x` with an admin account from `.env` (`services/urbackup.ts:7-10`); (3) reads backup storage from disk (browse/download). It also uses a sudo root helper (SECURITY.md "Installs and updates").
- Single UrBackup server only, must be on the same host: README "St0r manages one UrBackup instance"; code: `controllers/urbackup.ts:13-18` ("single local service instance", `getService()` returns a singleton); `controllers/storage.ts:34-39` hard-codes "Local UrBackup Server". The `managed_servers` table / `/api/servers` is for OS/agent management of hosts (`controllers/servers.ts:64,155`), not additional UrBackup backends.
- Tenancy: yes, "customers" (`database/migrations/002_add_totp_and_customers.sql`: `customers`, `customer_clients` (client_name per customer), `customer_users`). Non-admin accounts are scoped to the clients of assigned customers, fail-closed (`middleware/scope.ts:7-15,34-77`). Customers can be disabled (CHANGELOG 3.2.140). Single MSP per install.

## 2. API surface
All under `/api/*`, JSON, unversioned (no `/api/v1`). No OpenAPI/Swagger anywhere (grep of repo: none). Only prose docs: `docs/URBACKUP_API_COMPLETE_REFERENCE.md` (that's UrBackup's API, not St0r's). Unmatched `/api` paths return JSON 404 (`server.ts:182-184`). Global read-only gate for non-admin writes: `server.ts:133`, `middleware/auth.ts:175-230`.
Auth legend: A = any authenticated user (customer-scoped for non-admins), ADM = admin only, NONE = unauthenticated.

Unauthenticated (all in `server.ts`):
- GET `/health` (:122) NONE, status+timestamp.
- GET/HEAD `/api/recovery/artifacts/:token/:filename` (:128-129) NONE, random-token drill disk images.
- GET `/api/agent-install/:token`, GET `/api/agent-package/:token`, POST `/api/agent-register` (:159-161) NONE, token-protected agent install.
- GET `/api/version` (`routes/version.ts:15`) NONE, returns version.json and writes an `installations` row if `?installId=` valid (:21-52). GET `/api/version/latest` (:82) NONE. GET `/api/version/stats` (:61) A.
- POST `/api/auth/login`, POST `/api/auth/logout` (`routes/auth.ts:7-8`) no authenticate; GET `/api/auth/validate` A.

Backup data (`routes/urbackup.ts`, `router.use(authenticate)` :36):
- A: GET `/api/urbackup/status`, `/clients`, `/clients/online`, `/clients/offline`, `/clients/failed`, `/clients/:id/backups`, `/activities`, `/activities/current`, `/usage`, `/clients/:id/browse`, `/clients/:id/failed-paths`, `/clients/:id/image-backups/:bid/convert-download`, `/job-logs`, `/job-logs/:logId`, `/backup-stats`, `/storage-by-customer` (:38-64). Scoping via `scopeOf/filterByClientName/assertClientAccess` (`controllers/urbackup.ts:30-35,81-82,203,517,547,597,613,655`).
- ADM: GET `/clients/:id/authkey`, POST `/clients`, DELETE `/clients/:id`, POST `/clients/:id/disable|enable|regenerate-key`, PATCH `/clients/:id/name`, POST `/backups/start`, POST `/activities/:id/stop`, POST `/activities/clear-stale`, DELETE `/clients/:id/backups/:backupId`, GET `/proxy/progress` (:44-55,59,67).
- Browse (`routes/browse.ts`): A GET `/api/browse/backups`, `/files`, `/download`, `/download-folder` (:17-26); ADM POST `/api/browse/restore` (:29).
- Client settings: A GET `/api/client-settings/:clientId`; ADM PUT (`routes/clientSettings.ts:11,15`). Server settings: ADM GET/PUT `/api/server-settings` (`routes/serverSettings.ts:11,14`).
Recovery drills (`routes/recovery.ts`): A GET `/api/recovery/status`, `/report?client=&days=`, `/drills`, `/runs`, `/runs/:id`, `/canaries` (:14-19); ADM POST/PUT/DELETE drills, canaries, hypervisors, POST `/drills/:id/run`, GET `/options` (:22-34).
Replication (`routes/replication.ts:14` `router.use(authenticate, requireAdmin)`): ADM only: settings, targets CRUD, `/targets/:id/test`, `/targets/:id/run`, `/status`, `/runs`, `/runs/:id`, `/alerts/channels` (GET/PUT/DELETE), `/events`.
Alerts (`routes/alerts.ts`): A GET `/api/alerts/rules` (:12, no admin, not scoped; rule names/thresholds/emailTo), A GET `/api/alerts/active` (:58, scoped); ADM PUT `/rules/:type`, POST `/rules/:type/test`.
Storage: ADM GET `/api/storage/total`, `/api/storage/server{/:serverId}` (`routes/storage.ts:7-8`). Storage limits: ADM GET/PUT/DELETE; A POST `/api/storage-limits/status` (`routes/storageLimits.ts:8-11`).
Disk guard: ADM GET `/api/disk-guard`, `/events`, POST `/reclaim|prune-orphans|resume` (`routes/diskGuard.ts:14-20`).
System: A GET `/api/system-update/metrics`, `/urbackup-version`, `/client-versions` (`routes/system.ts:18,27,55`; not admin-gated, unscoped host CPU/mem/uptime/hostname, `controllers/system.ts:120-132`); ADM update/log/auto-update endpoints.
Servers (`routes/servers.ts:14` all ADM): list/CRUD, ping, SSH test, agent install, metrics, OS updates, reboot, St0r/UrBackup version+update.
Customers (`routes/customers.ts`): A GET `/`, `/:id`, `/:id/clients`, `/by-client/:serverId/:clientName`; ADM create/update/disable/enable/delete, client and user assignment.
Users, 2FA, profile, settings (A GET `/api/settings` returns host/port/fqdn/corsLock, `controllers/settings.ts:73-84`), database-backup (ADM), documentation, logs (ADM), client-installer.

## 3. Authentication
- Session login only: POST `/api/auth/login` with username, password, optional `totpToken` (`controllers/auth.ts:12-62`). Issues a 24h stateless JWT (`utils/auth.ts:31-35`) set as HttpOnly, SameSite=strict cookie (`auth.ts:73-79`). The JWT is deliberately NOT returned in the body (`auth.ts:84-88`), so a machine client would have to scrape `Set-Cookie`.
- Bearer: `Authorization: Bearer <jwt>` also accepted (`middleware/auth.ts:77-79`); never from query string (:81-83). The Bearer token is the same user JWT.
- No API keys/tokens, no scopes, no service accounts, no OAuth/OIDC (none found). Only role model: admin vs non-admin (read-only, customer-scoped) (`middleware/auth.ts:158-175`, `scope.ts`). Non-admin + 2FA optional per user.
- Per-request revalidation: account active, role from DB, session revoked when password changes (credentialVersion HMAC) (`middleware/auth.ts:21-144`, `utils/auth.ts:41-49`). Forced password-change gate (`auth.ts:63-66,126-133`). Revocation = disable user or change password; no per-token revocation list. No rotation concept for tokens (only 24h expiry). Hashing: bcrypt cost 10 in code (`utils/auth.ts:11`) while SECURITY.md says cost 12 (doc/code mismatch).
- Rate limiting: login 10 failed/15min/IP (`server.ts:82-87,103`); 10/min on password change and 2FA (:90-94,104-105); 200/min/IP on all `/api/` (:97-101,106). Per-IP, not per-credential. `trust proxy` loopback only (:45).
- TLS: none in the app; assumes Nginx; plain HTTP by default unless `--domain` (README "Known limitations", SECURITY.md "Transport"). Cookie `Secure` is auto from request (`utils/auth.ts:60-65`).
- CSRF: no CSRF token; relies on SameSite=strict cookie. CORS: reflects any origin with credentials unless `CORS_LOCK=true` (`server.ts:64-77`; logged as a warning).
- Suitability for M2M least privilege: partial workaround only. A non-admin "service user" assigned to all customers gets read-only (GET) access to scoped endpoints (A rows above) but: needs password login + cookie scraping, 24h JWT refresh loop, no scopes, shares login rate limits, and all customers must be assigned manually (assignment per customer, `scope.ts:45-52`). Cannot get admin-only data (storage, replication, servers) without being full admin. Not recommended as the long-term design.

## 4. Data availability
Legend: API = available via St0r API (route above), INT = internal only, NP = not present.
- Protected clients/endpoints: API `GET /api/urbackup/clients` (`controllers/urbackup.ts:58-90`; fields id, name, online, lastseen, ip, os, client version, bytes_used_files/images, disabled, file/image_backups_disabled, delete_pending: `services/urbackup.ts:517-640`). Customer mapping: API `GET /api/customers`, `/customers/:id/clients`.
- Backup status: API (`file_ok`, `image_ok`, `GET /api/urbackup/status` counters, `controllers/urbackup.ts:20-56`; `/api/recovery/status` normalises `backup.state` ok/failed/none, `controllers/recovery.ts:398,406`).
- Last successful/failed: API partially: `lastbackup`, `lastbackup_image` per client; ok flags; per-run history via `/activities` last list and `/job-logs`. Explicit "last failed" timestamp is not a field (unverified; derivable from activities).
- File vs image: API (separate `file_ok`/`image_ok`, `lastbackup`/`lastbackup_image`, `GET /clients/:id/backups` returns `{file:[], image:[]}`, `services/urbackup.ts:829-847`).
- Job history: API `/api/urbackup/activities` (current+last 100, `services/urbackup.ts:688-700`), `/job-logs`, `/job-logs/:logId`, `/backup-stats?days=`.
- Running jobs: API `/activities/current` and status counters (`running_file_backups` etc., `controllers/urbackup.ts:38-47`).
- Storage utilisation: per client API (`/usage`, `bytes_used_*`, `/storage-by-customer`, `/storage-limits/status`); server volume total/free API but ADM-only (`/api/storage/total`, `controllers/storage.ts:14-50`); disk guard ADM-only.
- Retention: API via `GET /api/client-settings/:clientId` (A; UrBackup per-client settings incl. intervals/retention counts, resolved value, `controllers/clientSettings.ts:10-30`) and ADM `/api/server-settings` for global (unverified exact keys).
- Replication status/lag: API but ADM-only: `GET /api/replication/status` (lag_seconds, bytes_sent, status, `controllers/replication.ts:305-336`), `/runs`, `/events`. Customer-visible summary also in `/api/recovery/status` `replication.state` (:397-401).
- Restore verification: API, scoped, A: `/api/recovery/status` (state verified/stale/failed/never_run/not_configured, :402-403), `/api/recovery/report`, `/runs`, `/drills`. Simulated runs flagged separately (docs/recovery-verification.md "Simulator").
- Server health: INT/partly API: host CPU/mem/net/uptime `GET /api/system-update/metrics` (A, unscoped); UrBackup version `/system-update/urbackup-version`; disk guard ADM; UrBackup API reachability (testConnection `services/urbackup.ts:491`) INT only. Alerts: `/api/alerts/active` (A, scoped).
- Multi UrBackup server aggregation: NP (one server).

## 5. Actions
- Start backup: ADM `POST /api/urbackup/backups/start` body `{clientName|clientId, backupType: "file"|"image", isIncremental}` (`controllers/urbackup.ts:213-256`); maps to full/incremental file/image (`services/urbackup.ts:867-960`); refuses disabled endpoints with 409 (:231-240); returns 400 on `start_ok=false` (:257-268). No idempotency key, no job id returned/dedupe (unverified beyond the response shape), no per-client authorisation other than ADM (and it does not call `assertClientAccess`, safe only because admin-only).
- Stop job: ADM `POST /activities/:id/stop`; clear stale jobs ADM, plus auto-clean hourly (`server.ts:376-411`).
- Schedules/config/retention view: A `GET /api/client-settings/:id` (scoped); edit ADM `PUT`.
- Restore: ADM `POST /api/browse/restore` {clientId, backupId, paths, restorePath} (`controllers/browse.ts:570-615`), audited (:628). It calls UrBackup `a=restore` with no session (`:603-615`), so it may not work as written (unverified). File download/ZIP for scoped users via `/api/browse/download` (audited). No "restore request/approval" workflow exists.
- Other ADM actions: add/remove/disable/enable client, regenerate key, delete backup, recovery drill run, replication run, reboot, OS/St0r/UrBackup update.
- Protection: `authenticate`+`requireAdmin`; global non-admin write block. Audit lines for downloads/restores only (`utils/audit.ts`; SECURITY.md "Audit Logging"), logged to journal, not a queryable table. Start-backup is NOT audited (`audit(` not called in `startBackup`; unverified for whole function, the viewed lines :213-273 do not call it).

## 6. Webhooks/events/notifications
- Replication/recovery alert channels: email (SMTP) and generic webhook (`services/replicationAlerts.ts:14,41-42,74-101`): POST JSON `{source, severity, type, target_id, message, timestamp}`, 10s timeout, no signature/HMAC, no retries visible, URL not validated (SSRF surface, admin-configured). Drill events reuse these channels (`docs/recovery-verification.md:191-196`: drill_failed, drill_recovered, drill_rpo, drill_cleanup).
- Alert rules (backup_failure, client_offline, storage_low, backup_old): email and Pushover only, not webhook (`services/alertRules.ts:20,25-27,267,289`).
- No outbound event stream, no polling cursor/ETag API, no inbound webhook receiver. Replication events are readable at ADM `/api/replication/events`.

## 7. Roadmap/plan docs
- No ROADMAP/plan file in repo. Files in `docs/`: URBACKUP_API_COMPLETE_REFERENCE.md, URBACKUP_DATABASE_BACKUP.md, github-about.md, installation.md, recovery-verification.md, screenshots.md, security-review-2026-10-02.md, media/. Root: README.md, CHANGELOG.md, SECURITY.md, VERSION, version.json; `.oss-scanner/threat_model.md`.
- No mention of a public/integration API, API tokens, or OpenAPI in README/SECURITY (grep). Only "api key" mentions concern the stor-agent (CHANGELOG.md:150ff) and Proxmox token.
- README claims: UrBackup 2.5.x (verified against 2.5.38), single server on same host, MIT, "St0r reads UrBackup's own database and API", Ubuntu/Debian only, plain HTTP by default.
- CHANGELOG version 3.2.140 (2026-11-20).

## 8. Security concerns relevant to integration
1. UrBackup admin credentials: `URBACKUP_USERNAME/PASSWORD` stored plaintext in `backend/.env` (`services/urbackup.ts:9-10`; set via UI `controllers/serverSettings.ts:331-336`). Backend runs as `st0r` with write access to UrBackup DBs (SECURITY.md note; README "Adjusts UrBackup database permissions").
2. Credential material logged at info level: UrBackup session id, salt, MD5(salt+password), PBKDF2 hash derived from the UrBackup admin password (`services/urbackup.ts:46,95,116,120,143,153,159,215`), to console/journal (`utils/logger.ts:16-24`). Leaks to anyone who can read the journal.
3. Unauthenticated routes: `/health`, `/api/version*` (DB write via installId, bounded), token-gated agent endpoints, artifact URLs.
4. `/api/alerts/rules`, `/api/settings`, `/api/system-update/metrics` etc. are available to any authenticated, even customer-scoped, user and are unscoped (host info, thresholds, destination email) (`routes/alerts.ts:12`, `controllers/settings.ts:73`, `routes/system.ts:18`).
5. Login cookie-only JWT, no token separation; CORS reflects all origins with credentials unless locked (`server.ts:64-77`). Plain HTTP by default; Bearer JWT in plain HTTP would be sniffable.
6. Rate limiting per IP only (a shared Clientst0r IP would share the 200/min bucket with others); login failures from the integrator count toward the lockout.
7. `/api/restore` path has no session to UrBackup (`browse.ts:603-615`) and `proxy/progress` calls UrBackup unauthenticated (`routes/urbackup.ts:67-73`) (unverified impact).
8. Webhook has no signing; replication alert webhook target is an arbitrary URL.
9. Doc/code drift: bcrypt cost 12 in SECURITY.md vs 10 in code.
10. Positives: tests exist for access control and session revocation (`backend/tests/access-control.test.mjs`, `session-revocation.test.mjs`), parameterised SQL, forced password change, scoped customer view, audit logging of downloads/restores, signed releases.

## 9. Missing for a Clientst0r integration
Read-only first (all under `/api/v1/`, JSON, documented via OpenAPI):
1. Machine credentials: `integration_tokens` table (hashed with SHA-256 or Argon2, shown once, prefix id, name, scopes, optional customer allowlist, IP allowlist, created/last_used/expires, revoked_at); `Authorization: Bearer st0r_...`; admin UI + API to create/rotate (overlap window)/revoke; per-token rate limit; audit of each call. Scopes e.g. `backup:read`, `recovery:read`, `replication:read`, `server:read`, `actions:start_backup`, `actions:restore_request`.
2. `GET /api/v1/health` (authenticated detail: UrBackup API reachable, DB readable, last collector time, St0r version, disk guard state) plus unauthenticated minimal liveness.
3. `GET /api/v1/customers` and `/endpoints?customer=&updated_since=` (stable ids, customer mapping, online, disabled, OS, agent version, `last_seen`).
4. `GET /api/v1/endpoints/{id}/backup-status` with explicit `last_file_success_at`, `last_file_failure_at`, `last_image_*`, `file_ok`, `image_ok`, counts, bytes, and a unified `state`; bulk list form with paging.
5. `GET /api/v1/jobs?endpoint=&status=&since=` (history, with stable job ids, type file/image, incremental/full, start/end, result, bytes, error summary) and `/jobs/running`.
6. `GET /api/v1/endpoints/{id}/schedule` and `/retention` (normalised effective settings, read-only, no secrets).
7. `GET /api/v1/storage` (per endpoint, per customer, server volume total/free) and `/replication` (targets, status, lag, last success, last run), `/recovery/verification` (reuse `/recovery/status` and `/report` contracts, flag simulated vs actual).
8. `GET /api/v1/events?since=<cursor>` (backup_failed, client_offline, replication failed, drill failed, disk guard) with cursor, for polling; plus a signed (HMAC) webhook channel with retry and delivery log.
9. Strip secrets from all v1 responses (no authkeys, no host paths, no SSH/Proxmox info); response versioning and ETag/`Last-Modified`.
Actions (second phase):
10. `POST /api/v1/endpoints/{id}/backups` {type: file|image, mode: full|incremental} with required `Idempotency-Key`, returns job/request id, 202; `GET /api/v1/requests/{id}` for state; 409 for disabled/in-progress; scope `actions:start_backup`; per-customer allowlist; server-side rate cap and optional "full image needs approval" rule.
11. Restore requests as a queued, approval-gated resource: `POST /api/v1/restore-requests` (endpoint, backup id, paths, target), `GET`/approve/deny/cancel, immutable audit table with requester (Clientst0r user/ticket id), never direct download tokens by default.
12. Audit log table queryable via `GET /api/v1/audit` (start-backup currently not audited).
13. Fix existing items: stop logging UrBackup session/salt/hashes, add TLS/mutual-TLS guidance or enforce HTTPS for v1, add CORS-lock default on, remove unauthenticated UrBackup proxy usage, verify restore path calls an authenticated session.
14. Clientst0r must not read St0r's MariaDB or UrBackup SQLite directly; everything through v1.
