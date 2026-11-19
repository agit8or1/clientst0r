# Phase 99 — Phone system integration and call-to-ticket

**Priority:** P2 · **Size:** XL · **Status:** planned · Roadmap: [Phase 99](../../ROADMAP.md) ·
Index: [Phases 96–100](README.md)

The shared compatibility and safety requirements in the [index](README.md) apply. This spec lists only what
is specific to Phase 99.

## 1. Goals and business value

- Connect ClientSt0r to the PBX an MSP already runs. ClientSt0r does not replace the PBX, does not carry media
  and does not administer the PBX.
- When a call rings: identify the caller (contact, customer, prospect, or unknown, including ambiguous
  matches), show a small popup with open tickets and permitted contract/SLA facts, and let the technician create
  a ticket or a lead in one click.
- Click-to-call from customer, contact, ticket and lead records through the PBX, with call activity logged on
  the right timelines.
- Missed calls, optional voicemail-to-ticket and callback tasks, so no call falls through.
- A provider-neutral adapter framework so further PBXs can be added; support is claimed for a platform only
  after a verified, tested integration.

## 2. Research summary and MVP choice

Research notes (items marked unverified there remain unverified here):

- **Asterisk 22 LTS (supported to 2029-10-16 per the Asterisk version table) via AMI** pushes call, bridge,
  queue and CDR/CEL events to a connected client and supports originate and redirect actions. AMI is a plain TCP
  protocol with weak transport security by default, so it should stay on localhost or a private network. Exact
  event and action names for 22 are to be confirmed against the generated AMI reference during 99.2.
- **FreePBX 17** runs Asterisk; its GraphQL API is configuration-oriented and documented by the vendor as still
  in development, so the practical event source is AMI on the same host (using a custom manager include, since
  FreePBX regenerates `manager.conf`).
- **ARI** is powerful but requires routing calls into a Stasis application, which is intrusive on an existing
  PBX. Not used for the MVP.
- Push-native platforms (Yeastar P-Series signed webhooks, 3CX CRM templates or Call Control) can call
  ClientSt0r directly; their licensing terms for API access are unverified.

**MVP:** Asterisk 22 LTS and FreePBX 17 through AMI, with a small bridge process on the PBX host.

**Ranked later adapters** (each needs its own verification before it is listed as supported): Yeastar P-Series;
3CX (CRM template path first, Call Control after confirming edition licensing); Wazo Platform; FreeSWITCH and
FusionPBX via the event socket using the same bridge contract; Grandstream UCM; Kazoo.

## 3. Existing components to reuse

| Need | Reuse | Notes |
|---|---|---|
| Signed inbound events with replay protection | `api_access/webhook_guard.py` (`read_body`, `timestamp`, `signed_material`, `claim`, `release`, `duplicate_response`), `api_access.WebhookDelivery` | DB-backed replay claim; pruned by the `api_access_tick` task. |
| Endpoint and secret model | `security_alerts.SIEMWebhookEndpoint` and `siem_webhook_receive` (`security_alerts/views.py`): URL token stored as a hash, `hmac_secret` encrypted, `require_hmac`, `last_seen_at`, `last_error`, `received_count`, `X-Cst0r-Signature` | The connection model copies this shape. |
| Network rules for the receiver | `api_access/groups.py` `_ROUTES` and `classify`, `api_access` IP rules and trusted proxies, `core/client_ip.py` | Add a `/telephony/bridge/` route with group `pbx_bridge`, so IP allowlists and refusal logging apply. |
| Credential encryption | `vault/secret_fields.py` `EncryptedTextField` (row-bound), key rotation `manage.py rotate_encryption_key` | |
| Number normalization | `phonenumbers` 8.13.x, already installed through `django-two-factor-auth[phonenumbers]` (`requirements.txt`) | Pin it explicitly in `requirements.txt` so it is not an accidental transitive dependency. |
| Contact records to match | `assets.Contact.phone`, `core.Organization.phone` / `primary_contact_phone`, `crm.Lead.contact_phone`, `integrations.PSAContact`, `accounts.UserProfile.phone` | Free-text fields; matching uses a derived index (§6). |
| Timelines | `crm.SalesActivity` (`activity_type='call'`, `duration_minutes`, `outcome`, `source`, `raw_payload`), `psa.TicketComment`, `psa.TicketTimeEntry`, `assets.ContactNote` | Calls get their own model and link into these. |
| Browser refresh | `fetch` polling pattern (`core:palette_search`, security dashboard scan poll) | No WebSockets, SSE or Channels exist; four sync gunicorn workers. |
| Background notifications | `psa.WebPushSubscription` (VAPID) when configured | Optional channel for missed calls. |
| Health alerts | `events/sources.py` `Adapter`, `OperationalEvent` (Phase 82) | Bridge offline and trunk-down alerts only; call records stay out of the event layer. |
| Business hours | `resourcing.WorkingHours`, `resourcing.Holiday`; Phase 93 calendars when shipped | For after-hours labels and callback due times. |
| Audit | `audit.AuditLog.log` | Click-to-call, dispositions, recording access, configuration changes. |
| Settings placement | `core/navigation.py` `settings_integrations` section | One new tab. |
| `tel:` links | about 20 hand-built `tel:` hrefs; `core/portal_branding.tel_href` | Replaced by a shared template tag that renders a click-to-call control when allowed and a `tel:` link otherwise. |

## 4. Architecture

### 4.1 Components

```
 PBX host (customer or MSP network)                ClientSt0r server
 ┌────────────────────────────┐   HTTPS (outbound only)   ┌────────────────────────────┐
 │ Asterisk 22 / FreePBX 17   │                           │ /telephony/bridge/events/  │
 │   AMI on 127.0.0.1:5038    │                           │ /telephony/bridge/commands/│
 │        ▲                   │                           │ DB: CallRecord, CallEvent, │
 │        │ AMI (local)       │  signed JSON events  ───► │     CallCommand, PhoneIndex│
 │ clientst0r-pbx-bridge      │  ◄─── poll for commands   │ browser polls /telephony/  │
 │ (systemd unit or container)│                           │     me/active/             │
 └────────────────────────────┘                           └────────────────────────────┘
```

- **Media and routing stay on the PBX.** Calls never transit ClientSt0r.
- **The bridge** is a small long-running process installed on the PBX host (or a host on the same private
  network). It holds the AMI connection, translates events into the vendor-neutral contract, buffers events on
  disk while ClientSt0r is unreachable, retries with backoff, and polls ClientSt0r for approved commands
  (originate). All connections are outbound from the PBX side, so no PBX management port is exposed and
  ClientSt0r never needs to reach into the PBX network.
- **Push-native PBXs** (later adapters) post directly to a vendor-specific receiver that verifies the vendor's
  signature and converts to the same internal event shape.
- **Failure isolation:** the receiver is a separate URL group, rate-limited and size-capped; processing is a short
  DB transaction. A disconnected bridge only marks the connection unhealthy. Sign-in, ticketing and every other
  page are unaffected; telephony UI shows "phone integration offline".

### 4.2 Signed event contract (version 1)

Request: `POST /telephony/bridge/events/<token>/` with headers `X-Cst0r-Timestamp` (Unix seconds) and
`X-Cst0r-Signature` (HMAC-SHA256 over `signed_material(ts, body)`, the same scheme as the SIEM receiver), body a
JSON batch of up to N events (size cap):

```json
{"v": 1, "bridge": {"id": "…", "version": "1.0.0", "adapter": "asterisk-ami", "pbx_version": "22.x"},
 "events": [{"event_id": "uuid", "seq": 1042, "type": "call.ringing", "occurred_at": "…",
             "call_id": "<PBX linked id>", "direction": "inbound", "from": "+15555550123",
             "from_raw": "5555550123", "to": "+15555550100", "did": "+15555550100",
             "extension": "201", "queue": "support", "attributes": {}}]}
```

- Event types: `call.ringing`, `call.answered`, `call.transferred`, `call.ended` (with duration and cause),
  `call.missed`, `voicemail.created` (mailbox, duration, message id), `agent.status`, `queue.status`,
  `bridge.heartbeat`.
- **Authentication:** URL token (stored hashed) plus mandatory HMAC (`require_hmac` cannot be turned off for
  bridges); timestamp required, 300 s window as in `webhook_guard`.
- **Replay and dedup:** `claim()` on the batch digest, plus a unique `(connection, event_id)` on `CallEvent`.
- **Ordering:** `seq` is monotonic per bridge. Events are applied to a `CallRecord` by state machine
  (ringing → answered → ended), so late or out-of-order events cannot move a call backwards; gaps in `seq` are
  recorded for health diagnostics.
- **Retries:** the bridge retries non-2xx responses with backoff; duplicates are acknowledged with
  `duplicate_response()`.
- **Commands:** `GET /telephony/bridge/commands/<token>/` (signed the same way) returns pending approved commands
  (originate) for that connection; the bridge reports results to `POST …/commands/<id>/result/`. Short poll every
  2 seconds; no long-poll, so no gunicorn worker is held open.

### 4.3 Call state in the database

The cache is a per-process `LocMemCache` across four workers, so call state, popups and command queues are
DB-backed. Queries used by polling are indexed and bounded (active calls for one user, last few minutes).

### 4.4 Real-time delivery to the browser

| Option | Fit today | Trade-offs |
|---|---|---|
| **Short polling (MVP)** | Works with sync gunicorn workers | One small indexed query per open tab every 3 s, only for users with a mapped extension and only while the tab is visible (Page Visibility API); `ETag`/304 when nothing changed. Popup latency up to ~3 s plus bridge latency. |
| Server-sent events | Poor: each open stream pins a sync worker; four workers would be exhausted by four tabs | Would need a separate async worker (ASGI or gevent) behind the same proxy; revisit together with the "live wallboard updates over SSE" item under consideration. |
| WebSockets (Channels) | Not present; needs ASGI server, a channel layer (Redis) and deployment changes | Out of scope for the MVP. |
| Web Push | Optional add-on for missed calls when `WEBPUSH_*` is configured | Not suitable for the live popup. |

### 4.5 Bridge process

- Python 3, no Django dependency, small dependency set; AMI client with reconnect; config file with AMI
  credentials (read-only `call`, `cdr`, `agent` classes plus `originate` only when click-to-call is enabled),
  ClientSt0r URL, token and HMAC secret; on-disk queue with size cap; structured logs without secrets.
- Distributed from this repository (`telephony/bridge/`), with a systemd unit and a container image; versioned
  separately from the app and reporting its version in every batch, so ClientSt0r can warn about outdated
  bridges.
- Least privilege on the PBX: a dedicated AMI user bound to `127.0.0.1`, `permit` limited to localhost, write
  class limited to `originate` when enabled.

## 5. New functionality

### 5.1 Connections and extension mapping

- **Settings → Integrations → Phone System:** add a connection (platform, name, default region for number
  parsing, outbound enabled yes/no), show the token and HMAC secret once (SIEM form pattern), download a bridge
  config, see health (last event, last heartbeat, bridge version, clock skew, error count).
- Map extensions to users (manual, with suggestions from user phone fields). A user without a mapped extension
  gets no popups and no click-to-call.

### 5.2 Number normalization and matching

- Parse with `phonenumbers` using the connection's default region; store E.164 plus the raw value and extension.
  Internal extensions and trunk prefixes configured per connection are never treated as external numbers.
- A derived `PhoneIndex` table (E.164 → contact, organization, lead, PSA contact, user) is maintained on save of
  the source records and rebuildable by `manage.py rebuild_phone_index`. The source fields stay free text.
- Match result: `none`, `single`, `ambiguous` (several contacts or customers share the number — all candidates
  listed), `confirmed` (a user picked the match for this call; never stored as a permanent identity).

### 5.3 Caller popup

- Small slide-out (bottom right, no modal) for the user whose extension rings, and optionally for queue members:
  caller number, match state, contact and customer (or lead), the caller's open tickets, and contract/SLA facts
  only if the user may see them for that customer. Buttons: open contact, new ticket (pre-filled), add note,
  new lead (unknown caller, when CRM is on), dismiss.
- An "unverified caller" label is always shown: **a phone number alone never establishes identity or
  authorization**. The popup never offers password resets, vault reveals or account changes, and nothing in
  ClientSt0r treats a matched number as verification.

### 5.4 Click-to-call

- A shared template tag renders a call button next to phone numbers where the user has `telephony_click_to_call`
  for that record's customer and an extension is mapped; otherwise a plain `tel:` link (works with desktop
  softphones registered as `tel:` handlers).
- Flow: the user clicks → a `CallCommand` (originate: ring the user's extension first, then dial the number) is
  created after permission and rate-limit checks → the bridge picks it up → result reported → the call appears
  through normal events. Commands expire after 30 seconds if not picked up.
- Optional outbound destinations per user role (for example only domestic numbers) checked in ClientSt0r as well
  as relying on PBX dial rules.

### 5.5 Call log and timelines

- `CallRecord` per call: direction, from/to, DID, queue, extension, user, start, answer, end, duration, outcome
  (answered, missed, voicemail, abandoned), match, notes, linked ticket and lead.
- Shown on the ticket, contact, customer and lead timelines, and in a call history list (filters by user, queue,
  customer, outcome). On leads, a `SalesActivity` of type `call` links to the record (the Phase 97 unified
  timeline).
- Optional time entry from a call on a ticket (pre-filled duration, user confirms).

### 5.6 Missed calls, voicemail-to-ticket and callbacks

- Missed calls appear in a "Missed calls" list in the Service Desk and in the user's popup history.
- **Voicemail-to-ticket (optional, off by default):** on `voicemail.created` for configured mailboxes, create a
  ticket for the matched customer (or an unassigned intake ticket when unknown or ambiguous) with caller, time and
  duration. The audio stays on the PBX by default; see recording rules below.
- **Callback tasks:** from a missed call or voicemail, create a callback assigned to a user or queue with a due time
  computed in business hours (Phase 93 calendars when available).

### 5.7 Queues and agent status

- Where the adapter reports them: queue waiting counts and agent status in a compact Service Desk widget.
- Queue selection and transfers from ClientSt0r only where the PBX supports them and only after the MVP; IVR,
  trunks, DIDs and routing stay in the PBX. DIDs can be labelled (sales, support, management) to choose the popup
  audience and the default action (new lead versus new ticket).

### 5.8 Recording and transcription

- Off by default. ClientSt0r does not record calls. If the PBX records, ClientSt0r may store a link to the
  recording (not the audio) on the call record, visible only with `telephony_listen_recordings`, each access
  audited.
- Transcription, if ever enabled, is **OPTIONAL AI** gated by `psa_ai_enabled` and a separate telephony setting,
  requires a configured consent announcement on the PBX (the administrator confirms it), and has its own
  retention. Not part of the MVP.
- Retention for call records is configurable (default 365 days for metadata) and pruned by a scheduler task.

### 5.9 Health alerts

- A `pbx` source adapter for the Phase 82 event layer raises alerts for bridge offline (no heartbeat for N
  minutes), signature failures above a threshold, and clock skew. Call records are not projected.

## 6. UI and workflows

- **One new settings tab:** **Administration → Integrations → Phone System**. No new sidebar group.
- Contextual controls: call buttons on contact, customer, ticket and lead pages; the popup on every staff page for
  users with a mapped extension; "Calls" tabs on ticket, contact, customer and lead; a "Missed calls" tab in the
  existing Service Desk section; call history reachable from the customer workspace.
- Popup and slide-outs use existing Bootstrap components and themes and respect `prefers-reduced-motion`.

## 7. Proposed data model changes

New app `telephony`:

| Model | Key fields |
|---|---|
| `PbxConnection` | `organization` (MSP), `name`, `platform` (asterisk, freepbx; later others), `adapter`, `token_hash`, `hmac_secret` (`EncryptedTextField`), `default_region`, `internal_prefixes` JSON, `outbound_enabled` (default false), `voicemail_to_ticket` (default false), `is_active`, `last_seen_at`, `last_heartbeat_at`, `last_error`, `received_count`, `bridge_version`, `clock_skew_s`, `last_seq` |
| `PbxExtension` | `connection` FK, `extension`, `user` FK null, `label`, `receives_popups` (default true); unique (`connection`, `extension`) |
| `PbxDid` | `connection` FK, `number_e164`, `purpose` (support, sales, management, other), `label` |
| `CallRecord` | `connection` FK, `pbx_call_id`, `direction`, `state`, `outcome`, `from_e164`, `from_raw`, `to_e164`, `to_raw`, `did` FK null, `queue`, `extension` FK null, `user` FK null, `started_at`, `answered_at`, `ended_at`, `duration_s`, `match_state`, `contact` FK null, `client_org` FK null, `lead` FK null, `confirmed_by` FK null, `ticket` FK null, `notes`, `recording_url` (encrypted, null), `last_seq`; unique (`connection`, `pbx_call_id`); indexes on (`user`, `state`), (`client_org`, `started_at`) |
| `CallEvent` | `connection` FK, `call` FK null, `event_id`, `seq`, `type`, `occurred_at`, `received_at`, `payload` JSON (size-capped); unique (`connection`, `event_id`) |
| `CallPopup` | `user` FK, `call` FK, `created_at`, `seen_at` null, `dismissed_at` null |
| `CallCommand` | `connection` FK, `user` FK, `kind` (originate), `target_e164`, `context` JSON (record type and id), `status` (pending, picked, succeeded, failed, expired), `created_at`, `picked_at`, `result` |
| `CallbackTask` | `call` FK null, `client_org` FK null, `lead` FK null, `assigned_to` FK null, `queue_label`, `due_at`, `status`, `ticket` FK null (or reuse an existing task model if one fits; confirm in 99.7) |
| `PhoneIndex` | `number_e164` (indexed), `kind`, `object_id`, `client_org` FK null, `label`, `source_field` |
| `TelephonySettings` | singleton: `metadata_retention_days`, `popup_poll_seconds`, `click_to_call_rate_per_minute`, `recording_links_enabled` (default false) |

Existing models: `crm.SalesActivity` gains `call` FK null; `accounts.RoleTemplate` booleans. No change to contact
phone fields.

Scheduler: `telephony_tick` (expire commands, mark bridges offline, prune per retention) registered in the three
required places.

## 8. API and integration requirements

- Bridge endpoints as in §4.2, classified in `api_access/groups.py` as group `pbx_bridge`, integration
  `telephony`, so Phase 81 IP rules and refusal logging apply. Body cap, batch cap and per-connection rate limit
  (DB-backed counter per minute, since the cache is per process).
- Browser endpoints (session auth, CSRF for writes): `GET /telephony/me/active/` (poll), `POST /telephony/call/`
  (click-to-call), `POST /telephony/calls/<id>/link/` (link ticket, contact, lead; add note).
- REST API read endpoints for call records (DRF, `api/scoping.py`), permission-checked.
- Adapter interface for later platforms: `parse(request) -> events`, `verify(request, connection)`,
  `capabilities` (originate, transfer, queues, voicemail), so each adapter declares what it can do and the UI
  shows only supported actions.

## 9. Roles and permissions

New keys, new module `telephony` in the registry's module list (`('Phone system', 'Call popups, call history and
click-to-call from a connected PBX.')`), all `staff_only=True`:

| Key | Action | Sensitivity | Per customer | Seeded on |
|---|---|---|---|---|
| `telephony_receive_popups` | view | Standard | — | Level 1/2/3, Service Manager, Sales Rep, Sales Manager, Owner, Org Admin |
| `telephony_view_calls` | view | Elevated | yes | Level 1/2/3, Service Manager, Owner, Org Admin; Sales roles for leads only |
| `telephony_click_to_call` | execute | Elevated | yes | Level 1/2/3, Service Manager, Sales Rep, Sales Manager, Owner, Org Admin |
| `telephony_listen_recordings` | download | Sensitive | yes | Owner only (others by explicit grant) |
| `telephony_manage_connections` | settings | Critical | — | Owner, Org Admin (superusers always) |

- The popup shows customer details, tickets and contract/SLA facts only for customers where the user already has
  the relevant permissions (`orgs_with_perm`, `accounts/scope.py`); otherwise it shows the number and "a customer
  you do not have access to" without names.
- Grants follow the `0064` pattern: derived from existing keys (for example `telephony_view_calls` where
  `tickets_view` is on) only when the module is enabled for the first time, not on upgrade.

## 10. Security

- No PBX management port is exposed: AMI stays on localhost; the bridge connects outbound over HTTPS.
- Bridge requests require token and HMAC with timestamp; replay claims in the DB; IP allowlists through Phase 81;
  size, batch and rate caps; refusals logged.
- PBX credentials never reach ClientSt0r in the MVP (they live in the bridge config on the PBX host). The HMAC
  secret is encrypted at rest and shown once; rotation supported with an overlap window.
- Commands are limited to originate from a mapped extension of the requesting user to a parsed E.164 number;
  per-user and per-connection rate limits; optional destination restrictions; every command audited. No
  unrestricted PBX actions exist in the contract.
- Spoofing: caller ID is untrusted input; displayed as "unverified"; never used for authorization. Payload fields
  are escaped in templates and treated as data.
- Every call-record view by a user without a matching ticket or customer permission is refused; recording access
  and exports are audited.
- Privacy: retention limits; recording links off by default; transcription not in MVP.

## 11. Backward compatibility

- No telephony code exists today; nothing changes for installs that do not enable the module.
- The shared phone template tag renders the same `tel:` link as today when telephony is off.
- `SalesActivity` gains a nullable FK only.

## 12. Migration strategy

1. New `telephony` app (additive). 2. `crm.SalesActivity.call` FK null. 3. `accounts` permission booleans with no
grants on upgrade (granted when the module is first enabled, by the enable action, listed in the audit log).
4. `PhoneIndex` built by a management command when the module is enabled, not in a migration.

## 13. Feature flags and module defaults

| Switch | Field | Fresh | Upgrade |
|---|---|---|---|
| Phone integration | `SystemSetting.telephony_enabled` (`core/modules.py`, group "Integrations") | off | off |
| Click-to-call | `PbxConnection.outbound_enabled` | off | — |
| Voicemail-to-ticket | `PbxConnection.voicemail_to_ticket` | off | — |
| Recording links | `TelephonySettings.recording_links_enabled` | off | — |
| Transcription (OPTIONAL AI) | not in MVP | — | — |

## 14. Testing strategy

- **Unit:** event contract validation; signature, timestamp and replay; state machine with out-of-order and
  duplicate events; E.164 parsing with regions, extensions and internal prefixes; matching (none, single,
  ambiguous); rate limiter across simulated workers (DB-backed).
- **View:** connection settings (secret shown once, rotation), popup polling payload filtered by permissions,
  click-to-call permission and rate-limit refusals, linking a call to a ticket, missed-call list.
- **Tenant isolation:** a technician scoped to customer A never sees B's names, tickets or calls in popups, lists
  or API; copies of `crm/tests_authz.py` and `reports/tests_authz.py` cases.
- **Failure isolation:** with the bridge stopped or the receiver returning errors, sign-in, ticket list and ticket
  create still pass; telephony pages show "offline".
- **Upgrade/migration:** upgraded install has the module off, no grants, no index; reverse migrations.
- **E2E against a real containerized Asterisk (CI):** a GitHub Actions job modelled on
  `.github/workflows/cross-peer-e2e.yml` builds a pinned Asterisk 22 LTS image (from a checksum-verified release
  tarball; base image choice to be fixed in 99.2), loads checked-in `manager.conf`, `pjsip.conf` and a test
  dialplan with two PJSIP endpoints and one voicemail box, runs the bridge against AMI, starts ClientSt0r on SQLite,
  places calls with SIPp (answered, missed, voicemail), and asserts call records, popups, matching and an
  originate round trip through the command queue. A FreePBX 17 run follows when a reproducible FreePBX test image
  is available; until then FreePBX is listed as "via Asterisk AMI, not separately verified".

## 15. Definition of Done

- Connection settings, extension mapping, bridge package with systemd unit and container image, documented
  installation on Asterisk 22 and FreePBX 17.
- Signed, replay-protected, ordered event ingestion; DB-backed call state; polling popup with match states and
  permission filtering; click-to-call through the command queue; call log on ticket, contact, customer and lead;
  missed calls; optional voicemail-to-ticket and callbacks.
- Health in settings and the Phase 82 event layer.
- CI E2E against real Asterisk passes; all tests above pass.
- Roadmap, README and docs list **Asterisk 22 LTS** as supported only after the CI job and a manual test against a
  real PBX pass; FreePBX only after its own verification; no other platform listed as supported.

## 16. Dependencies and sequence

Depends on Phase 81 (API access groups), Phase 82 (health alerts), roles (Phase 64); uses Phase 93 calendars and
Phase 97 leads and timeline when present. Order: 99.1 adapter framework and signed contract → 99.2 Asterisk/FreePBX
bridge and CI harness → 99.3 numbers and matching → 99.4 popup → 99.5 click-to-call → 99.6 call log and timelines
→ 99.7 missed calls, voicemail-to-ticket, callbacks → 99.8 queues and agent status → 99.9 health alerts → 99.10
recording and transcription policy (links only) → 99.11 further adapters, one at a time.

## 17. Limitations and open decisions

- Popup latency is bounded by polling (about 3 s) until an async delivery path exists.
- Browser WebRTC softphones are not part of this phase; the research notes (SIP.js or JsSIP with WSS, DTLS-SRTP and
  TURN) are kept for a later decision. Calls would still go browser to PBX directly.
- STIR/SHAKEN attestation is shown only if an adapter exposes it; it never changes authorization.
- Open decisions: scope (index item 11), second adapter (item 12), browser delivery (item 13), recordings
  (item 14), bridge distribution (item 15).
