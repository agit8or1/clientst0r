# Comet Backup API notes (official documentation, retrieved 2026-11-20)

Retrieval date: 2026-11-20. Official vendor documentation only. Nothing was signed up for and no vendor was contacted.
Rule used: a fact has a URL; anything not found on an official page is marked "not confirmed". Items marked "(inference)" are my planning conclusions, not vendor statements.
Retrieval note: several Comet/Apple/Jamf pages were read from the raw HTML/JSON/markdown behind the doc site (same official pages), because the rendered fetch was truncated.

Short URLs used below
- COMET-GUIDE = https://docs.cometbackup.com/latest/api/api-guide/
- COMET-METHODS = https://docs.cometbackup.com/latest/api/api-methods/ (each method is an anchor on this one page)
- COMET-STRUCT = https://docs.cometbackup.com/latest/api/api-data-structures/
- COMET-CONST = https://docs.cometbackup.com/latest/api/api-constants/
- COMET-OTHER = https://docs.cometbackup.com/latest/api/other-apis/
- COMET-PORTAL = https://docs.cometbackup.com/latest/api/account-portal-api/
- COMET-CFG = https://docs.cometbackup.com/latest/installation/comet-server-configuration/
- COMET-REL = https://docs.cometbackup.com/release-notes/26-10-0-epimetheus-released/

---------------------------------------------------------------------
# PART A - COMET BACKUP
---------------------------------------------------------------------

## A1. API style, auth, least privilege
- Style: HTTP(S) RPC. Every call is a POST with form-encoded parameters, path `/api/v1/admin/...` (admin) or user-scoped equivalents (`UserWeb...`). Any action in the web console or desktop client is available via API; the web UI is built only on this public API. Official SDKs: PHP, Go, Python, Ruby, JS/TS. TLS 1.2+. Backward compatible (old aliases kept "indefinitely"). [COMET-GUIDE], [COMET-METHODS]
- Two separate APIs with non-interchangeable credentials: (1) Management Console API (self-hosted AND Comet-hosted console) using admin/user account; (2) Account Portal API at https://account.cometbackup.com using an Account Portal API token (Bearer or `auth_type=token&token=`). [COMET-GUIDE], [COMET-PORTAL]
- Auth parameters on every admin call: `Username`, `AuthType` in {Password, PasswordTOTP, PasswordWebAuthn, TOTP, SessionKey}, plus `Password` / `TOTP` / `SessionKey` / `WebAuthnSign` as applicable. [COMET-METHODS] (any method section, e.g. AdminListUsersFull)
- Sessions: `POST /api/v1/admin/account/session-start` returns a session key (>= 17.2.0); `session-revoke`, `session-upgrade` (>= 23.6.8). Can then use `AuthType=SessionKey`. Session start/start-as-user do NOT accept personal API tokens. [COMET-METHODS]
- 2FA implication: if the admin has TOTP enabled, a TOTP code must accompany password auth ("PasswordTOTP"); WebAuthn is also supported. Docs recommend a dedicated API-only admin account with a long random password. [COMET-GUIDE], [COMET-METHODS] (the "dedicated account" recommendation came from a search summary of the API guide/config docs; wording not re-verified verbatim: partly not confirmed).
- Personal Admin API tokens (new): `POST /api/v1/admin/account/api-token/create|list|revoke` (>= 26.8.3 per methods page; datastructures say 26.8.4; release notes page is titled 26.10.0 and lists "Admin API tokens"; the version numbers are inconsistent across pages, treat "26.8.x or later" as the floor). Token default expiry 90 days; 0 = never. Token shown only once. Create requires re-supplying the password unless external auth. Server must have `AllowAdminAPITokens` (default true on new installs, false on upgrade) and the admin must not have `PreventAPITokens`. 156 methods are marked "accepts admin personal API token (AuthType=Token)"; 29 are not (admin-user/new, webhook-options/set, session-start, token list...). [COMET-METHODS], [COMET-STRUCT] (AdminAccountPropertiesResponse, AdminAPIToken, AdminUserPermissions, ServerConfigOptions), [COMET-REL]
  - Exactly which request field carries the token value alongside `AuthType=Token`: not confirmed on the pages read.
- Least privilege: yes, partially.
  - Read-only admin: `AdminUserPermissions.PreventWriteActions` (Comet 26.8.2+); release notes: "Restrict this account to read-only access prevents an admin account from using any API method that performs a write action." [COMET-STRUCT], [COMET-REL]
  - Other permission flags on AdminUserPermissions: PreventEditServerSettings, PreventServerShutdown, PreventChangePassword, AllowEditBranding / EditEmailOptions / EditRemoteStorage / EditWebhooks / EditExternalAuthSources, DenyConstellationRole, DenyViewServerHistory, DenyViewServerInfo, PreventDeleteStorageVault, PreventRequestStorageVault, PreventAddCustomStorageVault, AllowedUserPolicies, DenySoftwareBuildRole, PreventAPITokens. [COMET-STRUCT]
  - Some methods are blocked "on a per-administrator basis" (e.g. branding/webhook-options get/set, server config). [COMET-METHODS]
  - Caveat for this plan: the actions we want (run-backup, run-restore) are writes, so a single token can't be "read-only except start backup". Use two accounts (read-only admin for sync; a separate, tenant-scoped admin for actions). (inference)

## A2. Multi-tenant model
- "Tenants" (called "Organizations" before Comet 21.12.0; API still uses Organization/OrgID names) split one console into isolated zones for resellers/clients. Tenant admins see only their zone; visibility restrictions are applied automatically from the credentials supplied. [COMET-CFG], search summary of docs
- Methods: `organization/list|set|delete|export` (>= 20.9.0; set/delete top-level admin only). `admin-user/new` takes `TargetOrgID`; `add-user` takes `TargetOrganization` (>= 22.5.0). UserProfileConfig has `OrganizationID`. Organization object holds Name, Hosts, IsSuspended, WebhookOptions, PSAConfigs, Email, Branding, RemoteStorage. [COMET-METHODS], [COMET-STRUCT]
- Tenant admin limits: no bulk upgrade page; cannot point storage anywhere beyond what top-level configured; LDAP external auth for top-level admins only (OIDC works for tenant admins). [COMET-CFG]
- Mapping for an MSP PSA (inference): one Clientst0r Organization (customer) <-> one Comet tenant/Organization ID, and optionally one tenant-scoped read-only admin per customer. Alternative: one top-level read-only admin and filter by `OrganizationID` on user profiles.
- Self-hosted vs Comet-hosted: the API guide says its Management Console API covers both, authenticating against your own console URL [COMET-GUIDE]. Comet's marketing/blog states tenants, replication, on-prem storage and full API access are self-hosted-only and that the hosted tier does not support tenants (https://www.cometbackup.com/blog/comet-hosted-vs-self-hosted-backup-management-how-to-choose-the-right-model/ and https://www.cometbackup.com/blog/2024-05-02-self-hosted-comet-server-pricing-change/). That claim comes from vendor blog/pricing pages, not API docs: treat as "vendor-stated, verify before designing hosted support". The docs MCP page says the MCP server needs a self-hosted console (https://docs.cometbackup.com/latest/ , via search).

## A3. Endpoints for the data we need (all POST, `/api/v1/admin/...`, [COMET-METHODS])
| Need | Endpoint | Notes |
|---|---|---|
| Users list | `list-users` (names), `list-users-full` (UserProfileConfig dict) | >= 17.2.0 |
| User profile | `get-user-profile` (also `-and-hash`, `-hash`); `set-user-profile` writes | returns UserProfileConfig |
| Devices, sources, vaults, policy, quotas | fields inside UserProfileConfig: Devices, Sources (Protected Items, with SourceStatistics), Destinations (Storage Vaults), PolicyID/Policy, AllProtectedItemsQuotaEnabled/Bytes, MaximumDevices, QuotaOffice365ProtectedAccounts, QuotaHyperVGuests/VMware/Proxmox, IsSuspended, OrganizationID, Emails | [COMET-STRUCT] UserProfileConfig |
| Retention | in Source/backup-rule config inside the profile, plus `dispatcher/apply-retention-rules` action | exact retention field names: not confirmed (not read) |
| Job history by time | `get-jobs-for-date-range` (Start/End unix; jobs started or ended in range; both 0 = only incomplete jobs) (>= 17.6.8); `get-jobs-recent`; `get-jobs-for-user`; `get-jobs-all`; `get-jobs-for-custom-search` and `count-jobs-for-custom-search` (>= 22.12.2) | returns List<BackupJobDetail> |
| Running jobs | date-range with Start=End=0; `Status` 6xxx; `EndTime==0`; `dispatcher/list-active` is live device connections, not jobs | |
| Job log | `get-job-log`, `get-job-log-entries` (>= 20.6.8, MinSeverity filter) | |
| Last successful backup per item | `SourceStatistics{LastStartTime, LastBackupJob, LastSuccessfulBackupJob}` per Protected Item in the profile | [COMET-STRUCT] |
| Storage usage / quota | `storage/list-buckets`, `storage/bucket-properties` (size, `AfterTimestamp` to allow stale), `storage/free-space`, `squota/list-all` (>= 25.9.8), `constellation/status|last-report|new-report` (bucket usage report), `dispatcher/ping-destination` | per-user quotas in profile |
| Snapshots / restore points | live-device only: `dispatcher/request-vault-snapshots` (TargetID live connection GUID + Destination vault ID, >= 18.9.1), `dispatcher/search-snapshots` (>= 23.3.4). Per-job `BackupJobDetail.SnapshotID` gives the snapshot for each job without a live device | |
| Licensing / usage | `meta/stats` -> StatResult{Buckets, Users, Devices, Boosters, NetworkDevices} (>= 18.6.2); `meta/version` -> ServerMetaVersionInfo incl. ConfiguredDevices, BoosterLimit, ServerLicenseLimit (24.6.3+), LicenseValidUntil. Account Portal: `/api/v1/license/list_licenses` (token auth). | per-customer billing split must be derived from per-tenant user/device counts (inference); portal license endpoint fields not confirmed |
| Server status | `meta/version` (Version, VersionCodename, role flags, ServerStartTime, ServerStartHash, CurrentTime, ServerLicense*), `replication/state`, `meta/read-logs` | |
- Job status codes [COMET-CONST] (JOB_STATUS): 5000 success (5xxx = stopped OK); 6000-6004 running family (6001 active, 6002 revived, 6003 retry-wait, 6004 not yet started); 7000 timeout, 7001 warning, 7002 error, 7003 quota exceeded, 7004 schedule missed, 7005 cancelled, 7006 skipped already running, 7007 abandoned (7xxx = stopped unsuccessfully). Classification: BACKUP, RESTORE, RETENTION, UNLOCK, DELETE_CUSTOM, REMEASURE, UPDATE.
- BackupJobDetail fields: GUID, Username, Classification, Status, StartTime, EndTime (0 if running), SourceGUID, DestinationGUID, DeviceID, SnapshotID, BackupRuleGUID (24.6.6+), ClientVersion, TotalDirectories/Files/Size/Chunks, UploadSize, DownloadSize, VM/Office365 counts, ConflictingJob. [COMET-STRUCT]
- Methods marked "requires the Auth Role" (nearly all above) mean the server must run the Authentication Role (true for normal installs; `meta/version` exposes the role flags).

## A4. Events / webhooks / streaming [COMET-OTHER], [COMET-STRUCT], [COMET-CONST]
- Webhooks (>= 20.6.1): server POSTs StreamableEvent JSON to a configured URL. Config via console (Settings > Webhooks), `meta/webhook-options/get|set` (set does NOT accept tokens and interrupts queued messages), or `cometd.cfg` WebhookOptions. WebhookOption fields: URL, CustomHeaders, Level (`full`|`none`), WhiteListedEventTypes (empty = all), PayloadFormat (raw default; slack; email; aws_sns/sqs/eventbridge; formats 26.5.4+ / 26.11.1+). Webhooks are per organization/tenant (Organization.WebhookOptions).
- Auth/signing: NO HMAC signature documented. The only mechanism is static `CustomHeaders` (e.g. `Authorization: Bearer ...`) plus an `x-Comet-Tracing-Id` header on each request. Receiver should authenticate with the shared header secret and TLS. [COMET-OTHER]
- Replay/ordering: receiver must return HTTP 200; failures are logged and retried "a finite number of times"; parallel sends, order not guaranteed, retried deliveries are unordered. No documented event ID/dedupe key apart from the tracing ID; StreamableEvent has Actor, OwnerOrganizationID, ResourceID, Type, Timestamp, TypeString, Data. Plan: idempotent handling keyed on (Type, ResourceID, Timestamp) and a periodic poll reconciliation. [COMET-OTHER] (event structure per search summary of the same page; Timestamp/ResourceID dedupe is my inference)
- Websocket stream: `/api/v1/events/stream`, outbound connection from client (no public URL needed), in-order while connected, auth by five text frames (username, auth type, password, session key, TOTP), optional `allowList` query param; first message SEVT_META_HELLO. [COMET-OTHER] (via search summary; frame detail not re-verified: partly not confirmed)
- Useful event types [COMET-CONST]: SEVT_JOB_NEW, SEVT_JOB_COMPLETED (4201 per summary), SEVT_ACCOUNT_NEW/REMOVED/UPDATED, SEVT_DEVICE_NEW/REMOVED/LIVE_CONNECT/LIVE_DISCONNECT/LOBBY_CONNECT, SEVT_BUCKET_NEW/REMOVED, SEVT_SERVER_STARTED/RESTARTED/SHUTDOWN/UPDATED, SEVT_TENANT_NEW/REMOVED/UPDATED, SEVT_POLICY_*, admin login/token events.
- Slack-format webhooks render SEVT_JOB_COMPLETED as a summary card (status, type, user, device, data, files, uploaded, duration). Not needed for Clientst0r.

## A5. Actions (dispatcher commands) [COMET-METHODS]
- Dispatcher methods act on a live-connected device identified by `TargetID` = live connection GUID (from `dispatcher/list-active`, which returns Dictionary<string, LiveUserConnection> with Username, DeviceID, ReportedVersion, ReportedPlatform, IP, ConnectionTime, AllowsFilenames). Device must be online and connected; otherwise the call fails. 
- Start backup: `dispatcher/run-backup` (TargetID, BackupRule schedule GUID) and `dispatcher/run-backup-custom` (TargetID, Source = Protected Item GUID, Destination = vault GUID) -> DispatchWithJobIDResponse (gives a job ID to poll via `get-job-properties`). Requires Auth Role; accepts personal token; is a write (blocked for PreventWriteActions admins).
- Restore: `dispatcher/run-restore` (TargetID, Path, Source = Protected Item ID, Destination = Storage Vault ID; >= 17.9.3) and `run-restore-custom`. Restore to a path on the device; file-level restore needs the device's "Allow administrator to view my files" (LiveUserConnection.AllowsFilenames), else some live actions are refused. Snapshot ID parameter details not read: not confirmed.
- Other dispatcher commands: apply-retention-rules, delete-snapshot(s), deepverify-storage-vault, reindex-storage-vault, ping-destination, request-browse-* (disk, VMware, Hyper-V, Proxmox, MSSQL, MySQL...), update-software, uninstall-software, update-login-url/password, unlock, force-login, drop-connection, kill-process, refetch-profile. Job control: `job/cancel`, `job/abandon`. Account actions: `revoke-device`, `reset-user-password`, `disable-user-totp`, `delete-user`.
- Permission needed: an admin account (not read-only) in the owning tenant or top-level. No per-command permission flags are listed beyond AdminUserPermissions above. "Per-administrator prevention" exists only for settings-type methods.
- Suggested safe action set for v1 (inference): run-backup/run-backup-custom, job/cancel; leave restores and snapshot deletion out or behind approval.

## A6. Versioning / compatibility
- Every method lists a minimum server version (e.g. get-jobs-for-date-range >= 17.6.8; custom job search >= 22.12.2; api-token >= 26.8.3; webhook PayloadFormat >= 26.5.4/26.11.1). Fields are annotated "available in Comet X and later", missing fields mean default. [COMET-METHODS], [COMET-STRUCT]
- API is "backward compatible" and deprecated paths remain as aliases "indefinitely". [COMET-GUIDE], [COMET-METHODS]
- Server version endpoint: `POST /api/v1/admin/meta/version` returns Version string + role flags; accepts tokens. Gate features by Version (e.g. only use webhook PayloadFormat or api tokens if Version >= threshold). `meta/stats`, `meta/version` accessible unless DenyViewServerInfo is set (24.3.2+).
- Known doc inconsistency: Admin API token version (26.8.3 / 26.8.4 / "26.10.0 release"). Verify against the target server's `meta/version`.

---------------------------------------------------------------------
