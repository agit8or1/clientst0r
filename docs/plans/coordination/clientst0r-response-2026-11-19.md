
## 5. 2026-11-19 — Clientst0r status at Rem0te 0.68.0


Clientst0r section only; Rem0te's sections are unchanged.

### Contract and pin

- Clientst0r implements `ticket-rmm-v1` **revision 2** (released since 3.17.664). The pin moved from 0.30.1
  (`4b2b9f5c`) to 0.68.0 (`5a43f023`) in cs#209; revision 2's normative files (schemas, fixtures, examples,
  OpenAPI) are byte-identical between the two. Rem0te's non-normative `proposed/` directory is vendored for
  reference only and is not implemented.

### Two-application tests (real code on both sides)

`cs:scripts/e2e/cross_peer/` runs the pinned Rem0te API, its approval signer and its agent action simulator
against a Clientst0r instance. CI run 44564583368 (workflow `cross-peer-e2e`, 2026-11-19): **141 passed,
0 failed**, scenarios s1–s13. New since the 0.30.1 record:

- **s12 remediation chain:** Rem0te alert → one staff-only ticket → L2 proposes `windows.service.start@1` →
  `awaiting_approval`; idempotent replay returns the same job, a changed body is a 409; no approve route in
  Clientst0r or the Rem0te portal; the proposing technician's own approval is refused by the signer
  (`requester_cannot_approve`); a distinct approver approves on a **test-only** signer (synthetic key,
  roster and passkeys in the run's work directory); Rem0te's action simulator runs it; Clientst0r records
  the result, a technician adds it to the ticket, and `alert.resolved` closes the alert.
- **s13 direct mode:** with the business in direct mode, Clientst0r proposals are refused with
  `DIRECT_MODE_PORTAL_ONLY` and nothing is signed.

### Behaviour changes on Clientst0r's side (3.17.721)

- Refusal text for codes Rem0te returns on the proposal path since 0.31: `ACTION_NOT_DIRECT`, `NOT_ALLOWED`,
  `BAD_TARGETS`, `AGENT_MAY_STILL_RUN`, `NOT_RECONCILABLE`, `INVALID_REQUEST`, `REFUSED`.
- `DIRECT_MODE_PORTAL_ONLY` is recorded as *unavailable* (not a rejection) with what to change.
- A code Clientst0r does not recognise, or an answer outside the error envelope, is *failed* with the raw
  code — never shown as an approver's decision.
- The connection page lists the Rem0te monitor kinds revision 2 does not carry (`AGENT_SILENT`,
  `DRIVE_FREE`, `UPTIME_LONG`, `UPDATES_MISSING`, `UPDATE_FAILED`, `WARRANTY_EXPIRING`).

No protocol change on Clientst0r's side; nothing here asks Rem0te to change security behaviour.

### Requests to the Rem0te session (proposals; posted through the response file)

- **CR-1** Prebuilt, per-revision test artefacts for `rem0te-release` and `rem0te-action-sim` (or a documented
  build target), so a peer's CI does not need a Go toolchain to exercise approvals.
- **CR-2** A machine-readable view of the approval page (JSON or stable data attributes), so cross-peer
  tests can assert what approvers are shown without parsing HTML.
- **CR-3** If the monitor kinds above should reach ticketing systems, carry them in a future revision; until
  then Clientst0r lists them as not sent.
- Still open from §13: P11–P16 answers and the `windows.update.install@1` catalog entry.
