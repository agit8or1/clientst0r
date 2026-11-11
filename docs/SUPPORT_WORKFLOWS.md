# Support workflows

A support workflow takes a technician from a monitoring alert on a ticket through these steps:

1. **Evidence**: what monitoring and the RMM report, each item with when it was observed and whether that is still fresh.
2. **Likely causes**: rules over that evidence.
3. **Remediation**: an approved catalog action where one exists, or guided manual steps.
4. **Verification**: an outcome confirmed by monitoring.

Workflows are rules and data, not AI. They work the same with AI switched off.

Open them from a ticket that has a monitoring alert (**Support workflows** on the ticket, `/psa/workflows/t/<ticket>/`). Manage them under **Ticket Routing → Support workflows** (`/psa/workflows/manage/`), which needs the routing *manage* permission.

## Built-in workflows

| Workflow | Alert category | Action it may offer |
|---|---|---|
| Computer offline | offline | manual steps only |
| Disk nearly full | disk | manual steps only |
| Service stopped | service | *Start the Print Spooler service* (Rem0te `windows.service.start@1`), for the Spooler only |
| Windows Update failure | windows_update | manual steps only (updates go through Rem0te's staged patching) |
| High CPU | cpu | manual steps only |
| High memory | memory | manual steps only |
| Pending reboot | reboot_pending | manual steps only |
| Application failure | application | manual steps only |
| Network connectivity | network | manual steps only |
| Unresponsive application | unresponsive_app | manual steps only |
| Endpoint security alert | security | manual steps only |
| Backup failure | backup | manual steps only; offered only when a backup integration is connected |

You can turn any workflow off, edit it (your copy replaces the built-in, keeping its slug), or **Reset** it to the built-in. Runs already started keep the version they started with.

## Editing a workflow

The editor has these sections:

- **Name, description, alert categories**: which alerts the workflow is offered for.
- **Evidence is stale after**: evidence older than this many minutes is marked stale. The fact `evidence_stale` lets a cause say "refresh before acting".
- **Evidence to gather**: these items are all read-only.
  - the alert
  - the alert's current state in Rem0te
  - device status and inventory from the RMM sync
  - disk free space
  - reported utilisation
  - Rem0te's patch summary
  - other computers at the same site
  - this issue on this computer in the last 30 days
- **Likely causes**: plain-language text, each with a **When** condition.
- **Suggested actions**: choose from the Rem0te catalog actions ClientSt0r knows, with an optional impact note and a **When** condition. There is no field for a command, script, path or URL.
- **Manual steps**: one per line. These are shown when no advertised action fits.
- **Verification**: how many minutes monitoring has to confirm the fix.

**Conditions** are "Always", or a list of rules that must *all* hold or *any* may hold. Each rule compares one fact with a value:

- Facts include `severity`, `occurrences`, `device_online`, `site_offline_count`, `repeat_count_30d`, `service_name`, `disk_free_pct`, `disk_free_gb`, `metric_pct`, `reboot_required`, `pending_updates`, `failed_updates`, `patch_freshness`, `device_type`, `os_type` and `evidence_stale`.
- Ops are `eq ne gt gte lt lte in truthy falsy missing`.
- Values are read as JSON when possible (`5`, `true`, `["a","b"]`), otherwise as text. `in` also takes a comma-separated list.

**More rows** adds blank causes, actions and rules without saving.

**Advanced: JSON** shows the same definition as JSON, the format documented in `psa/support_workflows/builtins.py`. Use it for conditions nested deeper than one all/any list. The editor keeps such a condition as JSON in that condition's own field, so switching between the two views loses nothing.

Every save, from either view, is checked as a whole. If anything is wrong (an unknown fact, op, category or evidence item, an action ClientSt0r doesn't know, extra keys on an action, or text over 600 characters), the problems are listed and nothing is stored.

## What needs Rem0te

- **Proposing an action** needs all of the following:
  - the ticket reaches the computer through a verified link to a Rem0te paired for the same customer;
  - that Rem0te currently advertises the action and acts as the processor;
  - the action's condition holds;
  - the technician may request fixes of that risk there.

  The proposal goes through the existing fix-referral flow. Rem0te answers *awaiting approval*, and its approvers approve on Rem0te's own signer. ClientSt0r never approves, dispatches or runs anything.
- **The alert's current state** (`alert_now`) is a read-only call to Rem0te. It is made only when the technician holds read-only diagnostics for that customer. Servers need the advanced diagnostics access.
- **Read-only diagnostics** are the RMM's own advertised diagnostics, requested through the normal request flow.
- **Without Rem0te** (or with an RMM that takes only fix referrals), workflows still gather what ClientSt0r holds, explain likely causes and give manual steps. The run page says why each action isn't offered.

## How verification works

A run is marked **Confirmed by monitoring** only when the alert recovers in monitoring within the workflow's window. If the alert had already recovered when the run started, the run says so. The RMM reporting that a job succeeded is recorded, but it doesn't count as the fix. If the window passes without recovery, the run becomes **Not confirmed by monitoring**, and the technician can try another action or record manual steps.

Notes the workflow adds to the ticket are internal. A workflow never sends a customer message and never closes a ticket.
