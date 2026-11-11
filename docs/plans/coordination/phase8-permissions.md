# Phase 8 — RMM permission and security model (coordination note)

Branch `dev/rmm-p8-roles`. App: `rmm_permissions`. For agents building the Rem0te protocol, the device
workspace and ticket panel, alert workflows and AI: **call this API for every RMM action**.

## What existed before Phase 8

| Area | State before | Phase 8 |
|---|---|---|
| `tech_access` presets L1/L2/L3 (per-customer assignments, explicit denies, customer restrictions, containment, two-admin protected changes, "why" page) | Shipped. Gated the ticket RMM panel (handoff, diagnostics, remote, fix referral) through `tech_access.resolver.decide` | Kept, unchanged. One input to the new decision: grants, blocks and the customer scope |
| `RoleTemplate` flags | Shipped, but nothing about RMM tiers | `rmm_tier` added (default `''`). Four new built-in templates |
| Platform administrator role | Missing. Superuser stood in | Built-in **Platform Administrator** template (tier `platform_admin`) |
| High-impact RMM work (scripts, patches, device administration, automation) | Missing | Actions in the catalog. They need second-person approval |
| Per-org / per-action allow, deny and require-approval overrides | Missing. `tech_access` had per-capability denies and restrictions only | `RMMPermissionOverride` |
| Second-person approval of RMM operations | Missing in ClientSt0r. Rem0te has its own | `RMMApproval` |
| Audit of every allow and deny | Partial: only requests that were created | `rmm_action()` audits every allow and deny |
| Composition with a Rem0te refusal | Partial: each path handled it by hand | `record_remote_refusal()` |

## The API

```python
from rmm_permissions import can, rmm_action, require, record_remote_refusal, RMMPermissionDenied
from rmm_permissions.approvals import request_approval, approve, reject

d = can(user, organization, 'patch.deploy', device=rmm_device, ticket=None)   # pure, no audit: for rendering
d = rmm_action(user, organization, 'patch.deploy', device=rmm_device, digest=op_digest, request=request)
if d.permitted_now:            # same as bool(d)
    ...do it...
elif d.allowed and d.needs_approval:
    request_approval(user, organization, 'patch.deploy', device=rmm_device, digest=op_digest, summary='...')
else:
    refuse(d.reason)
# after the paired RMM answers:
if rem0te_refused:
    d = record_remote_refusal(d, user, organization, code=r.code, message=r.message, request=request)
```

The `Decision` fields:

- `allowed`: the actor may do this, or may ask for it.
- `needs_approval` and `approval_level`: a second person must approve before it runs. Levels: `peer`, `l3` or `platform_admin`.
- `permitted_now`: allowed and, if needed, approved. `rmm_action` consumed a matching approval and set `approval_id`.
- `grant`: `allowed`, or `request` (the paired RMM grants the session itself, as for remote view and control).
- `reason`: the human answer.
- `source`: what decided it: `tier:l2`, `tech_access`, `legacy:<flag>`, `override:<pk>`, `tenant`, `rem0te` and so on.
- `rem0te_scope`: the ticket-rmm-v1 delegation scope used for this action. `''` means synced data with no delegation. `None` means Rem0te has no route for it.
- `steps`: the chain behind the decision (layer, effect, detail, decisive). The effective-permissions pages render it.
- `as_dict()`: the same, as a dict.

Rules for callers:

- Use `can()` to show or hide buttons. Call `rmm_action()` (or `require()`) **immediately before acting**, on the server, every time. It re-reads every row, so demotion, revocation and new denies apply to the next call, queued jobs included.
- Pass the `device` (an `integrations.RMMDevice`, or an `assets.Asset`) and the `ticket` whenever there is one. That is how the tenant checks, the workstation-only limits, the own-ticket limits and the Rem0te-route checks happen.
- Pass a `digest` of the exact operation (for example sha256 of the canonical payload) both to `request_approval` and to `rmm_action`. An approval only matches the same requester, customer, action, device and digest, and it is used once.
- After Rem0te or another RMM refuses, call `record_remote_refusal`. **Its refusal always wins**: do not retry around it.
- When you refuse for a reason of your own (for example, the RMM doesn't advertise the feature), call `audit_denial(user, organization, action, reason, device=..., request=...)`. That way every denied RMM action is in the audit log.

## Action keys

The catalog is `rmm_permissions/catalog.py`. `tech_access` capability = the preset capability also consulted. Rem0te = the ticket-rmm-v1 scope, `''` = no delegation needed, none = no Rem0te route (refused on Rem0te-managed devices).

| Key | L1 | L2 | L3 | tech_access | Rem0te |
|---|---|---|---|---|---|
| device.view, alert.view | yes | yes | yes | — | `''` |
| diagnostics.view | yes | yes | yes | — | none |
| remote.request_support | request | request | request | remote_view | none |
| remediation.request_low | yes | yes | yes | fix_request_low | actions:propose |
| rmm.handoff | — | yes | yes | rmm_handoff | none |
| diagnostics.run | — | workstations | yes | diagnostics_readonly | none |
| workflow.run_approved | — | yes | yes | — | none |
| remote.request_control | — | request | request | remote_control | none |
| script.run_scoped | — | only by an approved allow override; approval l3 | approval peer | — | none |
| patch.deploy | — | workstations, approval l3 | approval peer | — | none |
| diagnostics.run_advanced | — | — | yes | diagnostics_advanced | none |
| remediation.request_high, remediation.refer | — | — | yes | fix_request_high / fix_refer | actions:propose |
| remote.request_elevation | — | — | request | elevation | none |
| device.administer, automation.deploy | — | — | approval peer | — | none |
| credential.reveal | only with the vault reveal permission at that customer; no tier or override grants it | | | — | none |
| integration.configure, policy.manage, security.settings, audit.review | Platform Administrator only (legacy: integrations_configure, superuser, audit_view) | | | — | — |

Locked (never available): `shell.unrestricted`, `tenant.all_access`, `approval.self`, `endpoint.approve`.

ClientSt0r invents no Rem0te scopes. The only ones it uses are Rem0te's own `ticket_analysis:submit`, `ticket_analysis:read`, `actions:propose` and `actions:read` (`integrations/rem0te/protocol.py SCOPES`). A test checks this. Rem0te's approval roster, passkeys and signer still apply on top of any ClientSt0r approval.

## How a decision is made

The order is in the docstring of `rmm_permissions/decision.py`. In short:

1. **Blocks come first**: locked actions, the user not being a technician, containment, the customer boundary, deny overrides, tech_access denies and restrictions, an unavailable integration, and no Rem0te route.
2. **Then grants**:
   - the role tier, read only from the technician's *global* role, and only at customers where they hold a live tech_access assignment;
   - the tech_access preset;
   - the legacy flags;
   - approved allow overrides.
3. **Then approval.** A deny always wins.

**Upgrade.** Existing templates have no tier and there are no override rows. The preset and legacy-flag grants are exactly the checks used before, so existing users get the same answers. Tests cover this.

## Overrides and approvals

- **Deny and require-approval** apply at once. They can target one action or `*`, one customer or every customer, and one technician, one global role or everyone.
- **Allow** names one action at one customer. It stays pending until a *different* Platform Administrator approves it, after a fresh password check. The person it grants to cannot approve it. High-impact actions also need a tier that lists them. An allow never covers credential reveal.
- **Lifting a deny or a require-approval** also needs a second administrator.
- **RMMApproval approvers.** Nobody approves their own request. The approver re-authenticates, and must qualify now: *peer* = may do the same action there; *l3* = L3 tier or an L3 preset at that customer; *platform_admin* = holds policy.manage. The requester is re-checked when the approval is given and again when it runs. Approvals expire after 24 hours.

## Pages

These are under Settings → Security → **RMM Permissions** (`/settings/security/rmm-permissions/`):

| Page | Shows | Who |
|---|---|---|
| Index | Overrides and their reviews | policy.manage to change; audit.review to read |
| `technician/<id>/?organization=` | Effective permissions and approval requirements, with the chain for each, linked to tech_access's "why" for mapped capabilities | policy.manage or audit.review |
| `customer/<id>/` | Every assigned technician × every action | policy.manage or audit.review |
| `approvals/` | Approvals waiting for a second person | Technicians |

## Wiring

`psa_ai/services/rmm_actions.py` calls the API for the existing ticket panel actions (handoff, diagnostic, remote view and control, fix referrals). The panel uses `can()`. Each operation calls `rmm_action()` before it acts, and Rem0te proposal refusals are recorded with `record_remote_refusal()`.
