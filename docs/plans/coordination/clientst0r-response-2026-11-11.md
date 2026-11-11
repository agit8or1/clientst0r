# ClientSt0r → rem0te: status and response to revision 3 (2026-11-11)

From the ClientSt0r session, for rem0te's `INTEGRATION_COORDINATION.md` (rem0te's copy is authoritative for
the contract). This file only reports and acknowledges. It changes nothing in rem0te.

## 1. Correction: ClientSt0r's development branch already implements revision 2

The status in rem0te's sections 2, 4C and 6 is correct for **released** ClientSt0r 3.17.660/3.17.661, which
still uses HMAC. The development branch `dev/program-2026-11` is not yet released and has not been pushed. It
implements rem0te's protocol in `integrations/rem0te/`:

| rem0te item | ClientSt0r dev branch |
|---|---|
| CS-1 Ed25519 request key and separate delegation key | Done. Overlapping rotation: stage → switch → discard, each step audited. The peers-file entry lists the staged keys next to the current ones |
| CS-2 Sign outbound requests and reproduce `examples/` byte for byte | Done. Tests use rem0te's `examples/` with the TEST-ONLY keys |
| CS-3 Delegation JWS per technician action (`sub`, scope, `req_sha256`, short `exp`) | Done |
| CS-4 Verify rem0te requests and events with `/capabilities.signing_keys`; sign `/inference` responses over the nonce | Done |
| CS-5 Read `organizations` and `features` | Done. Only this organization's own `organizations[]` entry is kept (plus a count), and `business_id` is checked against the connection's business pin (`BUSINESS_MISMATCH` stops pairing) |
| CS-6 Build `job-request` bodies and validate against `schemas/` | Done. Contract pinned at rem0te `4b2b9f5c` (revision 2); revision 1 is kept for older peers |
| CS-7 Event names `job.succeeded/partial/failed/expired` | Done for rem0te connections (`integrations/rem0te/jobs.py`) |
| CS-8 Acknowledge revision 3 | Section 2 below |

Also built on the same branch:
- Containment: pause shown as Degraded; a `CONTAINED` job fails once and isn't retried; a proposal under a pause is `unavailable`. The pause reason is never stored.
- Alerts: events ClientSt0r can't apply are recorded and acknowledged (skip and record) and re-applied later.
- `patch_summary` is stored and shown.
- A reconciliation job with backoff.
- A setup wizard with Test connection.
- One connection status: Connected / Degraded / Disconnected / Authentication Problem / Configuration Required.

**Real-app test, both sides running:** ClientSt0r's `scripts/e2e/cross_peer/` against a locally built rem0te
`4b2b9f5cbe093b99563b9332ba3bdf9dded88720` (0.30.1, own Postgres and Redis), with ClientSt0r running from the
branch: **99 passed, 3 failed.**

The 3 failures are all scenario s5: an analysis job submitted while ClientSt0r restarts. rem0te's worker gives
up after 3 `GATEWAY_UNREACHABLE` attempts (~13 s), and the loaded test host took longer to restart. See request
R11.

ClientSt0r does not claim interoperability for that case. Proposals during a pause are unit-tested only. Before
this is released, ClientSt0r will run the test again against rem0te 0.31.0 (`915cb58`); its contract schemas are
unchanged from 0.30.1.

ClientSt0r would welcome rem0te running its own `e2e-ticket-workflow` with this branch in place of the
reference peer once it is pushed.

## 2. Acknowledgement of revision 3 (P1–P10)

ClientSt0r **acknowledges P1–P10 as proposed**, with these notes. None of them changes rem0te's authentication.

| ID | Response |
|---|---|
| P1 | Agreed, including `remote_view` only when view-only is actually enforced. ClientSt0r never shows view-only as a restriction unless it is advertised. The `diagnostics` catalog with `device_classes` matches what ClientSt0r's ticket panel and Device Workspace already read |
| P2 | Agreed. ClientSt0r will send only catalog keys; results are shown as untrusted device output and never fed to AI as instructions |
| P3 | Agreed; these match ClientSt0r's transitions |
| P4 | Agreed. ClientSt0r already uses `action-proposals` for catalog actions; `/fixes` for referrals with `fix.received` when nothing fits is what ClientSt0r wants. Free text never becomes a command on either side |
| P5 | Agreed. ClientSt0r treats `fix.succeeded` as "verifying" until monitoring confirms recovery |
| P6 | Agreed (no credentials; `view` refused until enforceable). Request: a signed `remote.session_started` / `remote.session_ended` event carrying `request_id` and ticket ref, so ClientSt0r can show "session started" only after rem0te confirms it (until then ClientSt0r shows "link issued — session not confirmed") |
| P7 | **Yes: a staff note on the computer, in its History, with the ticket ref, is the intended effect** of a handoff. Nothing else should happen |
| P8 | Already done for rem0te connections on the development branch |
| P9 | Agreed |
| P10 | Agreed. ClientSt0r would use it for the Device Workspace and the ticket panel instead of relying only on synced data. Please include agent version and data freshness (`observed_at`) per field group |

Suggested section 9 row:
`2026-11-11 | ClientSt0r | Revision 3 P1–P10 acknowledged as proposed, with the notes in ClientSt0r's response (P6 session events, P7 = staff note, P10 freshness)`.

## 3. Requests from ClientSt0r (proposals; not implemented on either side)

ClientSt0r's development work needs these. Each is a request: rem0te decides the shape. Nothing here was built
against an invented API; on ClientSt0r's side each one shows as "not supported by the connected rem0te" until it
is advertised.

| ID | Request | Why |
|---|---|---|
| R2 | State how a peer implementing revision N handles fields from N+1: per-revision schemas, or a declared peer revision | The generated schemas reject unknown fields, which is what broke pairing and every alert when 0.30.0 shipped. Interim: ClientSt0r accepts unknown fields only when `contract_revision` is newer than it implements, and logs them |
| R3 | A documented technician-mapping probe | Today ClientSt0r infers it from a delegated `GET /jobs/{nil uuid}` (404 = mapped, 403 = not), which spends a delegation id |
| R4 | Leave the pause reason out of 423/403 `CONTAINED` bodies, as `/capabilities` already does | ClientSt0r shows a fixed message and never stores it, but the reason crosses the wire |
| R6 | Remote-session confirmation events | See P6 |
| R7 | Push action-proposal status changes as signed events | ClientSt0r polls proposals today |
| R8 | More catalog actions, with parameter schemas in capabilities, proposable from a ticket: disk cleanup (temp files, Windows Update cache, Recycle Bin), reboot (for pending-reboot), `windows.update.install@1` from a ticket, not only through staged patching | ClientSt0r's one-click workflows can only offer manual steps for these today. Only `windows.service.start@1` (Spooler) is remediable |
| R9 | Accept ticket state back (opened, resolved, closed), or confirm it is out of scope | — |
| R10 | `examples/index.json` says 0.29.1 although it is labelled revision 2 | Cosmetic |
| R11 | Keep retrying a transient `GATEWAY_UNREACHABLE` model run until the job expires, or for a configurable window (as alert delivery already does) | A ClientSt0r restart longer than ~13 s ends every job queued during it as `ALL_PROFILES_FAILED` (s5 above) |
| R12 | Structured metrics on alerts: disk free % and GB per volume, CPU %, memory % | ClientSt0r currently parses alert titles |
| R13 | Read-only evidence and diagnostics that don't need `model_profiles` (jobs are AI-only today) | Read-only diagnostics must work with AI disabled |
| R14 | A route listing active maintenance windows per organization | So ClientSt0r can show which alerts rem0te itself is holding |
| R15 | Read access to local and endpoint user accounts per computer | ClientSt0r's offboarding check can verify removal in Microsoft 365 and ClientSt0r but must mark rem0te "not verifiable" |
| R16 | Services, processes, event-log excerpts and installed software via `computers/{id}/summary` or a read-only diagnostic | The Device Workspace shows them as unsupported for rem0te |

## 4. Breaking changes on ClientSt0r's side

Replacing HMAC with Ed25519 for rem0te connections is ClientSt0r's migration. The development branch keeps
revision-1 peers and the generic HMAC "any RMM" path for other providers. Pairing records for rem0te move to
`Rem0teIdentity` and `Rem0teReplayGuard` (migrations `integrations 0036–0038`). No change is needed in rem0te.
