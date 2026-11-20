# Competitive program — Phase 0 security review

Findings from the Phase 0 internal code audit (ClientSt0r v3.17.719) and the ClientSt0r ↔ Rem0te integration
audit (Rem0te v0.67.0 `2dab9ef`). Static reading only: nothing was run against any instance, and no finding
below has been reproduced. Where this document re-read code at v3.17.720 (`58a83b32`), it says so; a re-read
confirms that the code path exists, not that it is exploitable.

## Conventions

- **ID.** `SR-nn` is a stable reference used by `GAP_ANALYSIS.md` and `PRIORITIZED_ROADMAP.md`. The order
  below is by severity, so IDs are not sequential.
- **Severity.** High / Medium / Low / Informational, judged on impact × who can trigger it in a single-MSP
  install (customers are Organizations; MSP staff work across them; see the project's single-MSP model).
  Reasoning is given per finding.
- **Status.** "Unverified — needs a reproducing test" unless stated otherwise. A finding is closed only when
  a test that fails before the fix and passes after it is merged.
- **No exploit payloads.** Preconditions describe who could trigger a finding, not how.
- `r0:` paths are in the Rem0te repository.

## Summary

| ID | Finding | Severity | Status |
|---|---|---|---|
| SR-01 | Workflow rules re-enter through `ticket.save()`; `create_charge` unbounded | High | Unverified (code path re-read) |
| SR-02 | Proxmox Backup Server provider makes unguarded requests to an operator URL | Medium–High | Unverified (code path re-read) |
| SR-03 | Workflow assign/watch actions accept any active user | Medium | Unverified |
| SR-04 | Invoice approval lacks separation of duties and an explicit staff check | Medium | Unverified |
| SR-05 | Bulk document upload performs no file validation | Medium | Unverified (code path re-read) |
| SR-07 | Audit log has no tamper evidence, retention or export | Medium | Confirmed as a design gap |
| SR-08 | Security-alert auto-tickets have no dedup; legacy webhooks accept token-only posts | Medium | Unverified |
| SR-17 | No routine scheduled backup; keys stored beside data | Medium | Unverified (scheduler registry read) |
| SR-24 | Rem0te silently drops alert kinds ClientSt0r cannot see | Medium | Confirmed by Rem0te code read |
| SR-25 | Cross-peer assurance is stale (pinned 0.30.1) and never exercises remediation | Medium | Confirmed (configuration fact) |
| SR-06 | Ticket attachments trust the declared MIME type and allow SVG | Low–Medium | Unverified (code path re-read) |
| SR-14 | Some staff views skip per-customer restriction checks | Low–Medium | Unverified |
| SR-16 | Legacy IT Glue/Hudu importer makes unguarded requests | Low–Medium | Unverified |
| SR-09 | Alert re-delivery with the same external id overwrites fields | Low–Medium | Unverified |
| SR-11 | Public lead form rate-limits on the proxy address | Low–Medium | Unverified (code path re-read) |
| SR-21 | Interim R2 policy accepts unknown fields from a peer declaring revision > 2 | Low–Medium | Confirmed as deliberate design |
| SR-27 | Double tickets when Rem0te automatic PSA tickets also target ClientSt0r | Low–Medium | Unverified |
| SR-10 | Vendor webhook severity is stored unvalidated | Low | Unverified |
| SR-12 | Public token endpoints without throttles | Low | Unverified |
| SR-13 | `asset_api_detail` exempt from CSRF with session auth | Low | Unverified (code path re-read) |
| SR-15 | `asset_api_detail` falls back to an unscoped lookup | Low | Unverified |
| SR-18 | Bulk document upload logs POST data | Low | Confirmed by code read |
| SR-19 | Credentialed CORS for localhost origins on every path | Low | Unverified (settings read; new in this review) |
| SR-22 | Rem0te business pin is trust-on-first-use | Low | Confirmed as design |
| SR-23 | No client-certificate support for Rem0te peers that pin one | Low | Confirmed by code read |
| SR-26 | `DIRECT_MODE_PORTAL_ONLY` refusal not mapped; envelope unverified | Low | Unverified |
| SR-28 | Rem0te returns the containment reason in 423 bodies | Low | Rem0te side; unverified |
| SR-29 | Rem0te inference retries only three times (R11) | Low | Confirmed by Rem0te code read |
| SR-30 | Rem0te mapping uniqueness includes revoked rows | Low | Unverified |
| SR-31 | Technician probe relies on undocumented 404-vs-403 and spends a `jti` | Low | Confirmed by code read |
| SR-34 | API key scopes are organization reach plus three levels | Low | Confirmed as design gap |
| SR-20 | Dead GraphQL URL module with `csrf_exempt` | Informational | Re-read: not mounted |
| SR-32 | Proposed P16 ticket request has no idempotency | Informational | Not active (fail-closed 404) |
| SR-33 | Vendored `clientst0r-interop.json` older than the PIN claims | Informational | Confirmed |
| SR-35 | Vault extension views are `csrf_exempt` | Informational | Re-read: bearer-only, not a finding |
| SR-36 | Payment webhooks `csrf_exempt` without a comment | Informational | Provider signatures verified (per audit) |

---

## High

### SR-01 — Workflow rules re-enter through `ticket.save()`; `create_charge` is unbounded

- **Finding.** Rule actions that change a ticket call `ticket.save()`. The ticket `post_save` handler calls
  `fire('ticket_updated', ...)` on every non-create save. `fire()` appends the rule to the per-thread chain
  but never checks whether that rule is already in it (only `fire_rule` chaining checks membership). A
  `ticket_updated` rule whose condition remains true after its own action can therefore run itself again
  until Python's recursion limit, and the `RecursionError` is caught per rule. If the rule also contains
  `create_charge`, each level can create a billable `Charge`; `create_charge` has no cap, approval,
  idempotency key or fire-once requirement.
- **Evidence.** `psa/signals.py:144-153` (fires `ticket_updated` on every update);
  `psa/workflow_engine.py:335-394` (`fire()` appends at ~L379, no membership check);
  `psa/workflow_engine.py:310-314` (membership check exists only for `fire_rule`);
  `psa/workflow_engine.py:260-` (`create_charge`); `fire_once_per_ticket` guard L363-368 (opt-in).
  Re-read at v3.17.720.
- **Severity: High.** Billing integrity (repeated real charges on a customer account) and request-time
  denial of service on ticket saves. Not higher because creating a rule needs an administrator.
- **Exploit preconditions.** An administrator has saved a `ticket_updated` rule whose condition survives its
  own action (an ordinary misconfiguration, not malice). After that, anyone who can update a ticket in scope
  triggers it, including customer portal users replying to their own ticket.
- **Status.** Unverified — needs a reproducing test.
- **Proposed fix.** In `fire()`, skip any rule already on the chain; suppress `fire()` while a rule's own
  actions are saving (or pass `update_fields` and ignore saves originating from the engine); cap total actions
  per top-level event. Make `create_charge` require `fire_once_per_ticket` or an approval (`PSAApproval` kind
  `action`), with an idempotency key `(rule, ticket, rule_version)`. Add the execution log from gap 4.02.
- **Test to add.** `psa/tests/test_workflow_reentrancy.py`: a `ticket_updated` rule with `set_priority` +
  `create_charge`; one ticket update must produce at most one firing and at most one Charge; a second
  update with `fire_once_per_ticket` produces none; no `RecursionError` in `last_error`.

---

## Medium–High

### SR-02 — Proxmox Backup Server provider makes unguarded requests to an operator URL

- **Finding.** The PBS provider calls `requests.get` on the connection's `base_url` without `core.safe_http`,
  so internal addresses and cloud metadata endpoints are reachable, and `verify_tls` can be turned off per
  connection. Error text includes the base URL and exception class (no body), which limits read-back but still
  permits internal port probing by status code.
- **Evidence.** `backup_monitoring/providers/pbs.py:50-62` (re-read at v3.17.720). Central guard:
  `core/safe_http.py`.
- **Severity: Medium–High.** SSRF from the application host. Response bodies are not echoed, which keeps
  it below High; on-premises PBS servers are usually on private addresses, so the fix needs an explicit,
  audited opt-in rather than a blanket block.
- **Exploit preconditions.** A user with backup-connection MANAGE permission. The audit notes this can be a
  customer-scoped manager (unverified); if a customer user can hold it, a customer can probe the MSP's
  network.
- **Status.** Unverified — needs a reproducing test.
- **Proposed fix.** Route through `core.safe_http`; add a per-connection "private address allowed" flag that
  only MSP staff with a specific permission can set, recorded in the audit log; keep metadata ranges blocked
  unconditionally.
- **Test to add.** `backup_monitoring/tests.py`: connection with a loopback / link-local / metadata
  `base_url` is refused before any socket is opened (mock the transport); a private address is refused
  unless the staff-only flag is set; a customer-scoped user cannot set the flag.

---

## Medium

### SR-03 — Workflow assign/watch actions accept any active user

- **Finding.** `assign_to` and `add_watcher` resolve any active username, including customer-portal users of
  another Organization. Legacy `assign_round_robin` / `assign_skill_match` / `assign_load_balanced` choose
  from `is_staff` users without per-customer authorization, availability or `restrict_technicians` checks
  (the newer routing engine does check these).
- **Evidence.** `psa/workflow_engine.py:133-137` (`_resolve_user`), assignment actions ~L170-250; contrast
  `psa/routing/engine.py` `_authorization_problem` L247.
- **Severity: Medium.** Cross-customer disclosure: a watcher receives ticket notifications for a customer
  they do not belong to; a restricted technician is assigned work outside their scope.
- **Exploit preconditions.** An administrator builds a rule naming a wrong user, or an MSP-wide rule
  round-robins to a restricted technician. Not triggerable by customers on their own.
- **Status.** Unverified — needs a reproducing test.
- **Proposed fix.** Validate the target at rule save and at action time through the routing engine's
  authorization check; refuse portal users as assignees or watchers of another customer's tickets.
- **Test to add.** Rule with `add_watcher` naming a portal user of Organization B fires on an Organization A
  ticket: watcher not added, `last_error` explains; round-robin skips a technician restricted from A.

### SR-04 — Invoice approval lacks separation of duties and an explicit staff check

- **Finding.** `invoice_approve` checks admin role and the `billing_send_invoices` flag for the invoice's
  customer, then `Invoice.approve(user)` records the approver without comparing it to the creator. There is
  no explicit MSP-staff check, so a customer-organization administrator holding that flag for their own
  Organization may be able to clear the approval gate on an invoice addressed to them.
- **Evidence.** `psa/views.py:5844-5856` (re-read at v3.17.720); `Invoice.approve` (psa/models.py ~L4709).
- **Severity: Medium.** Financial control bypass; an approval gate the MSP relies on can be cleared by the
  person who created the invoice, or possibly by the customer.
- **Exploit preconditions.** An MSP user who both creates and approves (no SoD), or a customer admin with
  the flag (unverified).
- **Status.** Unverified — needs a reproducing test.
- **Proposed fix.** Require MSP staff; refuse when approver == creator (configurable only to a stricter
  rule); log the refusal. Apply the same rule to credit memos and line edits after approval (gap 5.05).
- **Test to add.** `psa/tests/test_invoice_permissions.py`: customer admin with the flag → 403; creator → 403;
  a different staff approver → 200 and audit entry.

### SR-05 — Bulk document upload performs no file validation

- **Finding.** `document_upload` creates a `Document` per uploaded file with the client-declared content type
  and the original extension. No size, extension, MIME or magic-byte check; `Document.file` has no validators.
  `files/upload_rules.py` exists and is used elsewhere.
- **Evidence.** `docs/views.py:585-640` (re-read at v3.17.720); `docs/models.py` L148; `files/upload_rules.py`.
- **Severity: Medium.** Stored active content and unbounded storage use. Impact depends on how
  `core/media_views.py` serves the file (forced download vs inline); that is the part to verify.
- **Exploit preconditions.** Any user with documentation create permission in an Organization, which can
  include customer users with docs write access.
- **Status.** Unverified — needs a reproducing test.
- **Proposed fix.** Run every file through `upload_rules` (size, extension allowlist, magic bytes);
  store the detected type, not the declared one; confirm `media_views` serves non-allowlisted types as
  attachments with `nosniff`.
- **Test to add.** `docs/tests.py`: HTML declared as an image is refused; oversize refused; allowed PDF
  accepted; served response for any stored document has `Content-Disposition: attachment` unless allowlisted.

### SR-07 — Audit log has no tamper evidence, retention or export

- **Finding.** `AuditLog` is an ordinary table. Admin add/change are disabled; superusers can delete, and the
  deletion is recorded in the same table. ORM and SQL access can alter history silently. No scheduler task
  prunes or exports audit records.
- **Evidence.** `audit/admin.py:17-42`; `audit/models.py`; `core/management/commands/run_scheduler.py`
  `COMMAND_TASKS` (no audit task).
- **Severity: Medium** for security; **High for any compliance claim** (Phase 39/41 evidence packs rely on
  this log).
- **Exploit preconditions.** A superuser or anyone with database access.
- **Status.** Confirmed as a design gap (no reproduction needed for absence); tamper detection itself needs a
  test once built.
- **Proposed fix.** Hash-chain each row (previous hash + canonical row), a verification command, optional
  shipping to an external append-only target (syslog/WORM), retention with export-before-prune, and remove
  the admin delete action or require a protected change (Phase 57.4).
- **Test to add.** `audit/tests.py`: modifying or deleting a row breaks `verify_audit_chain`; retention
  exports before pruning; admin delete refused without protected-change approval.

### SR-08 — Security-alert auto-tickets have no dedup; legacy webhooks accept token-only posts

- **Finding.** `_maybe_auto_ticket` creates one ticket per new alert per matching rule with no check for an
  open ticket on the same asset/title. Alert dedup is only by `(connection or endpoint, external_id)`.
  Vendor/SIEM connections created before v3.17.715 keep `require_signature=False`, so a leaked webhook URL
  is enough to post alerts.
- **Evidence.** `security_alerts/adapters/base.py` L71; `security_alerts/models.py` L73-75, L326;
  `api_access/webhook_guard.py` (replay protection).
- **Severity: Medium.** Ticket flood and service-desk denial of service on one customer; no data
  disclosure. Address limits (Phase 81) reduce volume but do not remove it.
- **Exploit preconditions.** Knowledge of a legacy connection's webhook token (URL in logs, proxies or
  vendor configuration screens).
- **Status.** Unverified — needs a reproducing test.
- **Proposed fix.** Dedup window by (customer, asset hint, normalized title) and a per-connection
  auto-ticket cap per hour; warn on Security Overview for every unsigned connection; offer a one-click
  "require signatures" migration with a dated cut-over.
- **Test to add.** `security_alerts/tests.py`: 50 distinct-external-id alerts for the same asset/title →
  one ticket; cap reached → alerts recorded, no tickets, health issue raised; unsigned connection listed on
  Security Overview.

### SR-17 — No routine scheduled backup; keys stored beside data

- **Finding.** Verified pre-upgrade snapshots exist, but full `manage.py backup` is not a scheduler task;
  snapshots keep `keys.env` on the same host as the data.
- **Evidence.** `run_scheduler.py` `COMMAND_TASKS` (lines 20-82, only `upgrade_backup_prune`);
  `core/upgrade/snapshot.py`. `install.sh` cron coverage unverified.
- **Severity: Medium.** Resilience and confidentiality: a host loss loses data and keys together; a host
  compromise yields both.
- **Exploit preconditions.** None for loss (operational); host access for the key exposure.
- **Status.** Unverified — needs a test that the scheduler registry lacks the task and an install check.
- **Proposed fix.** Scheduler task for an encrypted routine backup to a configured off-host target, with
  periodic restore verification (reuse Phase 59.4); key escrow guidance and a separate key export.
- **Test to add.** `core/tests`: scheduler registry contains the backup task; the task refuses to run with
  no destination configured and raises a health issue; restore-verify runs on the produced archive.

### SR-24 — Rem0te silently drops alert kinds ClientSt0r cannot see

- **Finding.** Rem0te filters out DRIVE_FREE, UPTIME_LONG, UPDATES_MISSING, UPDATE_FAILED,
  WARRANTY_EXPIRING and AGENT_SILENT because they are not contract kinds. ClientSt0r shows the integration as
  Connected with no indication that these conditions are invisible to it.
- **Evidence.** `r0:apps/api/src/monitoring/alert-events.service.ts:44,75`; `r0:apps/api/prisma/schema.prisma:3211-3225`
  vs `r0:apps/api/src/integration/contract.ts:406`.
- **Severity: Medium.** Fail-safe for data, but a technician relying on ClientSt0r misses agent-silent and
  failed-update conditions (missed detection, not a breach).
- **Exploit preconditions.** None; it is the normal state.
- **Status.** Confirmed by reading Rem0te code; no reproduction needed.
- **Proposed fix.** ClientSt0r: show a notice on the connection page listing kinds not sent (gap 9.01).
  Rem0te: a contract revision that adds the kinds gated on the peer's declared revision.
- **Test to add.** Template test for the notice; cross-peer test per kind once the revision ships.

### SR-25 — Cross-peer assurance is stale and never exercises remediation

- **Finding.** CI runs both real applications but pins Rem0te 0.30.1. It never sends a proposal to Rem0te,
  never approves, never observes a result, and bypasses ClientSt0r's second-admin enablement.
- **Evidence.** `integrations/rem0te/contract/PIN.json`; `.github/workflows/cross-peer-e2e.yml`;
  `scripts/e2e/cross_peer/run.py:327` (fixture technician capabilities), `:355` (bypass), `:457-468`.
- **Severity: Medium (assurance).** The security properties claimed for remediation (AI never approves,
  technician request is not approval, revoked actor refused mid-flight) are tested only on each side
  separately.
- **Exploit preconditions.** n/a.
- **Status.** Confirmed (configuration fact).
- **Proposed fix.** Increments R-02/R-03 in `PRIORITIZED_ROADMAP.md`.
- **Test to add.** Scenarios in `INTEGRATION_TEST_MATRIX.md`.

---

## Low–Medium

### SR-06 — Ticket attachments trust the declared MIME type and allow SVG

- **Finding.** `ticket_attach` checks size and the client-declared `content_type` against an allowlist that
  includes `image/svg+xml`; no extension or magic-byte check. `media_views` forces SVG to download with a
  safe CSP, which mitigates stored XSS if the TicketAttachment rule takes that branch (unverified).
- **Evidence.** `psa/views.py:66,75,1834-1872` (re-read at v3.17.720); `core/media_views.py` L411-418.
- **Severity: Low–Medium.** Mitigated by serving; residual risk is mismatched content stored under an image
  type and shown inline.
- **Exploit preconditions.** Anyone who can attach to a ticket, including portal users on their own tickets.
- **Status.** Unverified — needs a reproducing test.
- **Proposed fix.** Use `upload_rules` (magic bytes, extension); store the detected type.
- **Test to add.** Attachment declared `image/png` with non-PNG bytes refused; SVG served as attachment.

### SR-14 — Some staff views skip per-customer restriction checks

- **Finding.** Staff can open some records by primary key without the per-customer permission or
  `restrict_technicians` check: `website_monitor_detail`, `process_detail` in global view,
  `dashboard_widget_add` (any Django `is_staff` bypasses ownership).
- **Evidence.** `monitoring/views.py` L124, L178; `processes/views.py` L135; `reports/views.py` L330.
- **Severity: Low–Medium.** Limited to MSP staff whose access is restricted to some customers.
- **Exploit preconditions.** A restricted technician who knows or guesses a primary key / slug.
- **Status.** Unverified — needs a reproducing test.
- **Proposed fix.** Use the same reach helpers as the rest of the module (`_in_reach`, `visible(user, …)`).
- **Test to add.** Restricted technician → 404 on each view for a customer outside their scope.

### SR-16 — Legacy IT Glue/Hudu importer makes unguarded requests

- **Finding.** The legacy importer uses `requests.Session()` with the typed `source_url`; the newer
  `imports/migration/transport.py` is guarded.
- **Evidence.** `imports/services/base.py` L27-53; `is_import_admin` L16 (superuser only).
- **Severity: Low–Medium.** SSRF, but only superusers can reach it.
- **Exploit preconditions.** Superuser.
- **Status.** Unverified — needs a reproducing test.
- **Proposed fix.** Use `core.safe_http`, or retire the legacy path in favour of the migration framework.
- **Test to add.** Private / metadata `source_url` refused before connect.

### SR-09 — Alert re-delivery with the same external id overwrites fields

- **Finding.** `update_or_create` on `(connection or endpoint, external_id)` overwrites severity, title and
  description and does not reset status, so a re-delivery could downgrade a critical alert.
- **Evidence.** `security_alerts` ingest (`views.py` `_vendor_ingest` ~L430-455; `siem.py`).
- **Severity: Low–Medium.** Needs a valid token (and a signature on signed connections); replay protection
  blocks identical re-sends but not new deliveries with the same external id.
- **Exploit preconditions.** Holder of a connection's token/secret, or a misbehaving vendor.
- **Status.** Unverified — needs a reproducing test.
- **Proposed fix.** Never lower severity on update without a source-declared reason; record each change in
  the alert history.
- **Test to add.** Second delivery with lower severity keeps the higher severity and records the attempt.

### SR-11 — Public lead form rate-limits on the proxy address

- **Finding.** `lead_capture_web` keys its 10/min limit on `REMOTE_ADDR`; behind nginx every visitor shares
  the proxy address, so the bucket is global.
- **Evidence.** `crm/views.py:826-836` (re-read at v3.17.720); `core/client_ip.py` `get_client_ip`.
- **Severity: Low–Medium.** Anyone on the internet can keep the form returning 429 for real prospects; no
  data exposure.
- **Exploit preconditions.** None beyond network reach.
- **Status.** Unverified — needs a reproducing test.
- **Proposed fix.** Use `get_client_ip`.
- **Test to add.** Two requests with different trusted-proxy forwarded addresses get separate buckets.

### SR-21 — Interim R2 policy accepts unknown fields from a peer declaring revision > 2

- **Finding.** ClientSt0r accepts and logs unknown fields in signed documents when the peer declares a
  revision above 2. Deliberate and documented, but fail-open for future revisions.
- **Evidence.** `INTEGRATION_COORDINATION.md` §11 ("Unknown fields (pending R2)"); `schema.errors_from_peer`.
- **Severity: Low–Medium.** Unknown fields are not acted on; risk is a future field changing meaning of a
  known one.
- **Exploit preconditions.** A paired peer (signed), i.e. Rem0te itself or its key holder.
- **Status.** Confirmed as deliberate design.
- **Proposed fix.** Settle R2 with P12 (a capabilities document with declared revisions); then validate
  revision 3+ documents against vendored schemas and refuse unknown required semantics.
- **Test to add.** Revision-3 document with an unknown field is stored, flagged and never applied.

### SR-27 — Double tickets when Rem0te automatic PSA tickets also target ClientSt0r

- **Finding.** Rem0te 0.55 can create tickets in a PSA through email/webhook connectors. If an operator points
  that connector at ClientSt0r while alert events also flow over the contract, each alert opens two tickets.
- **Evidence.** Rem0te CHANGELOG 0.55 Tripwire (`MonitorTicketPolicy`); ClientSt0r `alerts.py:170-177`
  (dedup only within the contract path).
- **Severity: Low–Medium.** Integrity and noise, no disclosure.
- **Exploit preconditions.** Operator configuration on the Rem0te side.
- **Status.** Unverified — needs a reproducing configuration.
- **Proposed fix.** Rem0te suppresses automatic PSA tickets for businesses mapped to a ClientSt0r peer, or
  exposes the setting so ClientSt0r can warn in the setup wizard.
- **Test to add.** Cross-peer: with both paths enabled, ClientSt0r shows a warning and opens one ticket.

---

## Low

### SR-10 — Vendor webhook severity is stored unvalidated

- **Evidence.** `security_alerts/views.py` ~L455 stores `a.get('severity') or 'medium'`; SIEM path buckets
  (`siem.py` L53).
- **Severity: Low.** Unknown severities rank as 0 in auto-ticket logic, so critical alerts can be missed;
  no injection (ORM).
- **Preconditions.** Token holder or vendor format change. **Status.** Unverified.
- **Fix.** Reuse `_bucket_severity`; reject values outside choices. **Test.** Unknown severity mapped and
  logged.

### SR-12 — Public token endpoints without throttles

- **Evidence.** `psa:csat_respond` (`psa/views.py` ~L9912, overwrites rating on re-submit),
  `portal agreement_reminder_unsubscribe`, `security_alerts digest_unsubscribe`, `network_discovery`
  collector endpoints.
- **Severity: Low.** Tokens are hashed and unguessable; risk is resource use and repeat CSAT overwrites.
- **Preconditions.** Holder of a survey/unsubscribe link. **Status.** Unverified.
- **Fix.** Per-address and per-token throttles; CSAT single response or explicit "change answer".
- **Test.** Eleventh request in a minute → 429; second CSAT response handled per policy.

### SR-13 — `asset_api_detail` exempt from CSRF with session authentication

- **Evidence.** `assets/views.py:1067-1070` (re-read at v3.17.720): `@csrf_exempt`, `@login_required`,
  handles GET and PATCH.
- **Severity: Low** (audit said Medium). A cross-site PATCH needs a CORS preflight, and session cookies are
  `SameSite=Lax` (`config/settings.py:424`), so browser-driven exploitation is unlikely; the exemption is
  still unnecessary. See SR-19 for the one CORS path that interacts with it.
- **Preconditions.** A logged-in user visiting a hostile page, plus a browser that ignores the above.
  **Status.** Unverified.
- **Fix.** Remove `@csrf_exempt`; callers send the CSRF header. **Test.** PATCH without a token → 403.

### SR-15 — `asset_api_detail` falls back to an unscoped lookup

- **Evidence.** `assets/views.py` ~L1067+: `get_object_or_404(Asset, pk=pk)` when no organization is
  selected; the decorator `org_flag_required(..., owner(Asset))` is expected to be the real check.
- **Severity: Low** if the decorator holds. **Preconditions.** Authenticated user without an org context.
  **Status.** Unverified.
- **Fix.** Scope the lookup to the user's reach regardless of context. **Test.** User of Organization A,
  no org selected, requests Organization B's asset → 404.

### SR-18 — Bulk document upload logs POST data

- **Evidence.** `docs/views.py:598-600` logs `request.FILES` and `request.POST` at INFO on every upload.
- **Severity: Low.** No secrets expected, but form values end up in logs.
- **Status.** Confirmed by code read. **Fix.** Remove; log counts only. **Test.** `assertLogs` shows no
  POST values.

### SR-19 — Credentialed CORS for localhost origins on every path (new in this review)

- **Finding.** When `corsheaders` is installed, `CORS_ALLOWED_ORIGINS` lists three `http://localhost` origins
  with `CORS_ALLOW_CREDENTIALS = True` and no `CORS_URLS_REGEX`, so the policy applies to every URL in
  production, not only the GraphQL API it was written for.
- **Evidence.** `config/settings.py:174,213-215,893-900`.
- **Severity: Low.** `SameSite=Lax` cookies are not sent on these cross-site requests in current browsers,
  and the origin must be served from the victim's own machine.
- **Preconditions.** Hostile content on the victim's `localhost:3000/19006/8081`. **Status.** Unverified.
- **Fix.** Apply only under DEBUG, or restrict with `CORS_URLS_REGEX` to token-authenticated API paths.
- **Test.** Settings test: in production settings, credentialed CORS is off or path-restricted.

### SR-22 — Rem0te business pin is trust-on-first-use

- **Evidence.** `integrations/rem0te/pairing.py:281-,512` (first good check pins `business_id`).
- **Severity: Low.** Requires a malicious or misconfigured peer at first pairing, which is already
  authenticated by Ed25519 keys exchanged out of band.
- **Status.** Confirmed as design. **Fix.** Optional: show the business name/id for administrator
  confirmation before pinning. **Test.** Pin requires confirmation when the option is on.

### SR-23 — No client-certificate support for Rem0te peers that pin one

- **Evidence.** `integrations/rem0te/client.py` (no client-cert configuration); Rem0te peers file
  `clientCertSha256`.
- **Severity: Low.** Defence in depth; Ed25519 request signing already authenticates.
- **Status.** Confirmed by code read. **Fix.** Optional client certificate per connection with rotation.
  **Test.** Cross-peer with a pinned certificate passes; wrong certificate refused with a mapped reason.

### SR-26 — `DIRECT_MODE_PORTAL_ONLY` refusal not mapped; envelope shape unverified

- **Evidence.** `r0:apps/api/src/actions/actions.service.ts:178` (Nest `ForbiddenException`, may not use the
  `{error:{code}}` envelope); `integrations/rem0te/actions.py:50-63` (`REFUSAL_TEXT`).
- **Severity: Low.** A proposal refused by policy is shown with a generic or misleading reason; no execution
  happens.
- **Status.** Unverified. **Fix.** Map the code; parse non-envelope 403s as `UNKNOWN_REFUSAL` with the raw
  code stored (no secret values). **Test.** Recorded body for each shape maps to the right state and text.

### SR-28 — Rem0te returns the containment reason in 423 bodies (R4)

- **Evidence.** Rem0te audit §3 "Containment" and §6 (v); ClientSt0r discards it.
- **Severity: Low.** Operator note could disclose incident context to the peer. Rem0te-side fix.
- **Status.** Unverified. **Fix.** Rem0te drops the reason from 423/403 bodies (request R4).
  **Test.** ClientSt0r unit test that no pause reason is stored or displayed.

### SR-29 — Rem0te inference retries only three times (R11)

- **Evidence.** `r0:apps/api/src/integration/worker.service.ts:31,169`.
- **Severity: Low (availability).** A ClientSt0r restart longer than ~13 s fails queued jobs with
  `ALL_PROFILES_FAILED`. **Status.** Confirmed by code read. **Fix.** Rem0te retries until job expiry.
  **Test.** Cross-peer s5 variant with a 60 s ClientSt0r outage.

### SR-30 — Rem0te mapping uniqueness includes revoked rows

- **Evidence.** `r0:apps/api/prisma/schema.prisma:2514-2529` (`@@unique` without `revokedAt`).
- **Severity: Low.** Re-mapping after revoke may fail or reuse a stale row. **Status.** Unverified.
- **Fix.** Rem0te: partial unique index or delete-on-revoke. **Test.** Cross-peer revoke → re-map.

### SR-31 — Technician probe relies on undocumented 404-vs-403 and spends a `jti` (R3)

- **Evidence.** `integrations/rem0te/setup.py:34`.
- **Severity: Low.** Behaviour could change silently in Rem0te. **Status.** Confirmed by code read.
- **Fix.** Documented probe endpoint (request R3). **Test.** Contract test against the documented response.

### SR-34 — API key scopes are organization reach plus three levels

- **Evidence.** `api/models.py` L40-60; `api/permissions.py` L93.
- **Severity: Low.** Design gap: an integration key cannot be limited to one resource (for example
  tickets read only, no vault).
- **Status.** Confirmed as design gap. **Fix.** Per-resource scopes (gap 8.04). **Test.** Key with
  `tickets:read` gets 403 on vault endpoints.

---

### SR-37 — Security playbooks run without approval; a step reports success without acting

Found by the platform audit, 2026-11-20 (static read of v3.17.732). Severity: Medium.

- `security_alerts/models.py` `_correlate_alert_to_incident` calls `find_matching_playbook` and
  `execute_playbook` whenever a new incident opens, with no approval step and no off switch per customer.
- The `run_workflow_rule` step returns `('ok', 'workflow rule … flagged for execution')` but runs nothing, so
  the incident timeline records an action that did not happen.
- That step looks the rule up by primary key with no check that it belongs to the incident's customer.
- Playbook mail is sent with `fail_silently=True`, so an alert accepted through a legacy token webhook can cause
  mail to go out.

Fix (roadmap 51.20): playbooks off by default or behind an approval; the step either runs the rule through the
workflow engine with the same customer checks as other rule actions, or is removed; the lookup is scoped to the
incident's customer. Tests: an incident opened from a forged alert sends no mail while playbooks are off; a rule
from another customer is refused; the timeline never records "ok" for an action that did not run.

## Informational

- **SR-20 — Dead GraphQL URL module with `csrf_exempt`.** The audit flagged `api/urls_graphql.py` as a
  CSRF-exempt, session-authenticated GraphQL endpoint. Re-read at v3.17.720: the module is not included by
  any URLconf; the mounted endpoint is `/api/v2/graphql/` in `config/urls.py:150-158`, which is **not**
  exempt (comment states why). Action: delete the dead module so it cannot be re-included. Test: a URL
  resolver test that `/graphql/` does not resolve and `/api/v2/graphql/` enforces CSRF for session POSTs.
- **SR-32 — Proposed P16 ticket request has no idempotency.** Rem0te built it gated off; ClientSt0r answers
  404 today (fail-closed). Raise in the P16 answer.
- **SR-33 — Vendored `clientst0r-interop.json` is the 0.29.1 run**, while `PIN.json` says the directory was
  copied at `4b2b9f5c`. Cosmetic; fixed by re-vendoring (increment R-02).
- **SR-35 — Vault extension views are `csrf_exempt`.** Re-read at v3.17.720: `extension_auth_required`
  accepts only a bearer token from the `Authorization` header (`vault/extension_auth.py`
  `resolve_extension_token`) and replaces `request.user`, so session cookies are not used and CSRF does not
  apply. Not a finding; add a comment at each exemption.
- **SR-36 — Payment webhooks `csrf_exempt` without a comment** (`payments/views.py` L183, L191). The audit
  reports provider signature verification in `payments.webhooks`; add comments and a test that an unsigned
  post is refused.

## Verification order

1. SR-01, SR-02, SR-04, SR-05 — reproducing tests first (increment R-01 in `PRIORITIZED_ROADMAP.md`).
2. SR-03, SR-06, SR-08, SR-11, SR-14 — same increment if time allows, otherwise R-01b.
3. SR-07, SR-17 — design work; scheduled in program Phase 8.
4. Rem0te-side items (SR-24, SR-27–SR-31) — through the coordination file.
