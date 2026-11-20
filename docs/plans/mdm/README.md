# Device management (MDM) integrations — specification

Roadmap Phase 106 (P2) and 92.7; directive of 2026-11-20. **Planned; nothing here is built.** Clientst0r
integrates established MDM/UEM providers and does not run an MDM server. Provider facts and their sources:
[PROVIDER_API_NOTES.md](PROVIDER_API_NOTES.md) (official documentation, retrieved 2026-11-20).

## What exists today

- No MDM integration in Clientst0r. Microsoft 365 is a read-only tenant inventory (Phase 109 plans more).
- Rem0te detects Intune update rings, and refuses to manage them, and does Apple warranty lookups. It has no MDM
  integration.
- Reuse: integration connection patterns (sealed credentials, TLS verification, connection test), assets and
  RMM devices, the Phase 82 event layer, alert-to-ticket policy, the roles registry (Phase 64), step-up
  authentication (Phase 57), onboarding and offboarding checklists, verified-usage billing (Phase 92).

## Providers and what their APIs allow

| Provider | Credentials (least privilege) | Inventory | Actions by API | Change notifications | Notes |
|---|---|---|---|---|---|
| Microsoft Intune + Entra ID | App registration per customer tenant, client credentials, admin consent; read: `DeviceManagementManagedDevices.Read.All`, `Device.Read.All` | Managed devices, compliance, encryption, OS, user, ownership, last sync | Lock, retire, wipe and others; wipe needs `DeviceManagementManagedDevices.PrivilegedOperations.All` (other actions' permissions not confirmed) | None for these resources — poll | 2,000 requests / 20 s per app per tenant for managed devices; app-only consent is not granted through GDAP, so each customer's administrator consents |
| Jamf Pro | API roles and clients (client credentials) with granular read-only privileges | Computers and mobile devices inventory | MDM commands, erase | Webhooks listed (signing and retry not confirmed) | At most 5 concurrent connections recommended |
| Kandji (Iru) | Per-tenant bearer token with per-endpoint permissions | Devices, apps, compliance | Many device actions | None found — poll | 10,000 requests per hour per customer |
| Apple Business Manager API | OAuth with an ES256 JWT assertion; granular permissions | Automated Device Enrollment inventory and MDM server assignment | Assignment only — no lock or wipe | Signed (HMAC) webhooks | Lock/wipe for Apple devices goes through the customer's MDM, not ABM |
| Android Enterprise (Android Management API) | Service account; one `androidmanagement` scope (no read-only scope) | Devices, policies, compliance | Lock, wipe, lost mode via `issueCommand` | Pub/Sub | 1,000 queries / 100 s per project; read-only must be enforced inside Clientst0r |
| Mosyle | **Not confirmed** — no official API documentation found | — | — | — | Blocked until official documentation is obtained |

Provider details change; each connection's test records the provider version and the permissions actually
granted, and Clientst0r offers only what that connection allows.

## Data model (planned)

- `MdmConnection`: provider, customer (one connection per customer tenant for Microsoft; MSP-wide connections
  with per-customer mapping where the provider is multi-tenant), sealed credentials, consent state, capability
  set, polling interval, last sync and error.
- `MdmDevice`: provider id (stable), connection, platform, model, serial, OS and version, enrollment, last check-in,
  compliance, encryption, policy state, ownership (corporate/personal), assigned user, observed-at; link to an
  asset and to a Rem0te endpoint, confirmed once. Apps stored only where the provider returns them and the
  customer allows it (personal devices: no app list).
- `MdmActionRequest`: device, action, requester, reason, ticket, approval record, provider response, status.

## Workflows

1. **Inventory and compliance** — poll (or receive signed notifications where offered), upsert by provider id,
   suggest asset matches by serial; non-compliant, unencrypted and stale devices become events and, by policy,
   tickets.
2. **Approved actions** — lock, lost mode, retire, wipe, policy/profile assignment, app deployment, enrollment
   and assignment, offered only when the connection's capability set includes them. Each destructive action
   needs its own permission (`mdm.wipe`, `mdm.retire`), fresh authentication, typed confirmation of the device
   name, a reason, and an audit record; the provider's own authorization stays separate. No automation and no
   AI starts a destructive action; AI may explain compliance state only (OPTIONAL AI, no secrets sent).
3. **Leaver** — approved offboarding checklist → account disable request (Phase 109) → MDM device review →
   authorized retirement → license recovery → documentation update; each step a recorded task.
4. **Joiner** — device assignment and enrollment tasks from the new-employee request.
5. **Portal** — customers see their managed-device counts and compliance summary (77.9), never device secrets.
6. **Billing** — verified device counts per customer feed Phase 92 review (92.7).

## Security

Least-privilege credentials per provider (read-only first, privileged permissions only when actions are switched
on for that connection), sealed storage and rotation, TLS verification, customer isolation in every query,
export and report, signed notifications verified where offered, idempotent upserts, rate-limit backoff, audit
for every action, no default destructive automation, no credentials or personal data sent to AI.

## Acceptance

1. Against a sandbox or test tenant per provider: connection test records permissions; inventory import is
   idempotent; devices match existing assets without duplicates.
2. A technician without `mdm.wipe`, or without fresh authentication, is refused at the API, not only in the UI.
3. A restricted technician sees no other customer's devices in pages, API or exports.
4. With Android's single scope, no write call is made unless actions are switched on for that connection.

## Order

106.1 connections → 106.2 inventory → 106.3 compliance events → 106.6 one device record → 106.5 leaver/joiner
tasks → 106.4 actions (last, per provider, starting with lock and retire before wipe).
