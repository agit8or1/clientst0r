# How ClientSt0r protects client data

This page describes what ClientSt0r does today (v3.17.651). Planned work is
in [ROADMAP.md](ROADMAP.md), not here. Every statement below points to the
code or test that backs it. Administrators can see whether each safeguard is
actually in effect at a given customer under **Settings → Security → Security
Features** (`/core/security/features/`).

The examples use made-up customers, people and tickets.

## Who can see what

ClientSt0r has two kinds of users, and they get different reach on purpose.

| | Customer users (User Type: Organization User) | MSP staff (User Type: Staff) and superusers |
|---|---|---|
| Customers they can open | Only organizations they're a member of (a parent organization covers its subsidiaries) | **Every customer.** Staff work across all clients by design (`core/tenancy.py`, `is_cross_tenant_user`) |
| What they can do there | Their membership's role: Owner, Admin, Editor, Read-only, or a custom role | A staff global role, if one is set, narrows this; without one, staff have full reach. Superusers can do everything |
| Tickets | Tickets shared with them, and only the public conversation | Every ticket, including internal notes and working data |
| Vault values | Only with the reveal permission at that customer (below) | Superusers always; staff when their global role allows it |
| Ticket AI and RMM tools | Never | Only with a technician access assignment at that customer (below). Staff, admin and superuser flags grant nothing on their own |

Evidence: `accounts/permission_utils.py` (`user_has_org_perm`, `orgs_with_perm`),
`psa/visibility.py`, `tech_access/resolver.py`;
tests `psa/tests/test_internal_ticket_visibility.py`,
`tech_access/tests.py` (`test_superuser_staff_and_owner_flags_never_imply_access`,
`test_portal_users_are_outside_presets_even_with_an_assignment`).

### Built-in roles and the vault

| Role | See credential titles | Reveal a credential value |
|---|---|---|
| Owner | yes | yes |
| Admin | yes | yes |
| Editor | yes | yes |
| Read-only | yes | **no** |
| New custom role | yes (default) | **no** unless "View actual password values" is ticked (since v3.17.650) |

Review existing custom roles under **Settings → Roles**: roles created before
v3.17.650 had the reveal box ticked by default.

### Technician access levels (ticket AI and RMM tools)

A technician needs an L1, L2 or L3 preset (or a custom one) **at each
customer**. An assignment at one customer gives nothing at another. Full
detail: [TECHNICIAN_ACCESS.md](TECHNICIAN_ACCESS.md). Source:
`tech_access/catalog.py`.

| Capability | L1 Help Desk | L2 Technician | L3 Senior | Who finally decides |
|---|---|---|---|---|
| Analyze ticket (one model) | yes | yes | yes | ClientSt0r |
| Editable AI reply drafts | yes | yes | yes | ClientSt0r |
| Send a reply that started as an AI draft (customer reply) | – | yes | yes | The technician presses Send |
| Compare models | – | yes | yes | ClientSt0r (customer policy must allow it) |
| Apply AI-suggested ticket changes | – | yes | yes | The technician |
| Other technicians' tickets | – | – | yes | ClientSt0r |
| Private RMM handoff | – | yes | yes | ClientSt0r *(planned — not built yet)* |
| Read-only diagnostics | – | standard workstations | + servers | rem0te *(planned)* |
| Remote session (view / control / elevation) | – | may **request** view or control | may request view, control or elevation | **rem0te** *(planned)* |
| Request a catalog fix | – | low-risk | low- and higher-risk | **rem0te** approves and runs it *(planned)* |
| Approve an endpoint fix | locked | locked | locked | Only rem0te, on its own approval page |
| Vault data, bulk export, cross-customer access, security administration | locked | locked | locked | Never through a preset |

Today only the first six rows do anything. The RMM, diagnostics, remote
session and fix rows are capability switches waiting for rem0te's side of the
contract ([ticket-rmm-v1](contracts/ticket-rmm-v1/README.md), "Later
milestones"); they show **Unavailable** until a paired rem0te advertises them.

## Sign-in

| Safeguard | Default | Where to change it |
|---|---|---|
| Two-factor sign-in (TOTP) | Required for everyone | Settings → Security, or `REQUIRE_2FA` |
| Lockout | 5 failures (same username + address) → 30 minutes | Settings → Security, or `AXES_FAILURE_LIMIT` / `AXES_COOLOFF_TIME` |
| Passwords | 12+ characters with a special character; Argon2 hashes | Settings → Security, or `PASSWORD_MIN_LENGTH` / `PASSWORD_REQUIRE_SPECIAL` |
| Sessions | 60 minutes idle, 8 hours after sign-in | Settings → Security, or `SESSION_IDLE_TIMEOUT` / `SESSION_COOKIE_AGE` |
| IP / country firewall | Off | Settings → Firewall |
| HTTPS | HSTS one year; Secure, HttpOnly cookies | `SECURE_HSTS_SECONDS` |

An environment variable always wins over the saved setting, and the settings
page shows that field read-only. Source: `core/security_policy.py`; tests
`core/tests/test_security_policy.py`, `security_tests/test_release_650.py`.

## A shared ticket seen by the customer

*Example.* Example Dental's office manager reports "Printer offline at front
desk". The technician adds an internal note ("toner driver v3 is broken on
this model; use v2") and logs 45 minutes. The office manager opens the ticket:

- **They see** the subject, the description and the public replies, and can
  reply, attach a photo and watch the ticket.
- **They don't see** the internal note, the time entry, expenses, the kit
  list, workflow runs, canned replies, similar tickets, the contract, or
  what the RMM reports about the printer's PC, on the portal or on the staff
  ticket page (`/psa/t/<number>/`). The mobile API also leaves out internal
  notes.
- **They can't** merge, close by quick action, add expenses or kit, link
  knowledge-base articles or launch workflows, even by posting to those URLs
  directly (403).
- Their attachment is always public. A customer can't mark it internal.
- Tickets that aren't shared with the customer don't appear at all.

Evidence: `psa/views.py` (`ticket_detail`, `STAFF_ONLY_TICKET_CONTEXT`,
`_staff_or_403`), `assets/views.py`; tests
`psa/tests/test_customer_on_staff_ticket_page.py`,
`psa/tests/test_internal_ticket_visibility.py`,
`integrations/tests_rmm_association.py`
(`test_asset_page_offers_rmm_to_technicians_only`).

## Revealing a vault credential

*Example.* An Editor at Example Accounting opens the entry "Front desk
Wi-Fi" and clicks Reveal.

1. **Permission.** ClientSt0r checks `vault_view_password` for the entry's
   own customer. A Read-only member gets 403. Membership elsewhere doesn't
   count.
2. **Approval** (if the entry requires it). Without an unused, unexpired
   approval the reveal is refused. Break-glass lets the requester approve
   themselves only with a written justification, and that is recorded.
3. **Access rules** (if any). Deny rules for a country, address range or time
   win. If the rules can't be evaluated the reveal is refused (503), not
   allowed.
4. **Rate limit.** 30 reveals per hour per user.
5. **Audit.** The reveal writes an audit event: action `reveal`, object
   type `password`, the user, the entry, the customer and the address. Copying
   the value is recorded as a reveal. (Browser-extension reveals are recorded
   as action `read` with event `vault_extension_reveal`, so filter on both.)

The same checks guard the web vault, the REST API (`?reveal=true` and
`/reveal/`), the mobile API and the browser extension's reveal and TOTP
calls. List responses never
include the value. GraphQL lists only entries in customers where the caller
has vault access, and never returns the value.

Evidence: `vault/permissions.py` (`gate_reveal`), `vault/access_rules.py`,
`api/views.py`; tests `vault/tests.py`, `vault/tests_extension_gate.py`,
`api/tests.py`, `security_tests/test_vault_and_proxy.py`.

## Encryption

| Data | Protection |
|---|---|
| Vault passwords, TOTP seeds, stored integration credentials | AES-256-GCM, with a separate HKDF-derived key per purpose, from `APP_MASTER_KEY` |
| API and mobile tokens | Stored only as HMAC-SHA256 hashes |
| Sign-in passwords | Argon2 hashes |
| AI provider keys | Sealed to the AI gateway's key (X25519 + HKDF + AES-GCM) |
| Backups | Encrypted (Fernet) |
| Ticket text, documents, attachments | **Not encrypted by the app.** Protect the database, disk and backups |

`APP_MASTER_KEY` lives in the environment, not the database; production
refuses to start without it. Tests: `vault/tests_secrets_at_rest.py`.

## Ticket AI

**OPTIONAL AI.** Ticket AI is off until an administrator turns it on.

- **Who enables it.** Only a superuser: AI on for the install (`psa_ai_enabled`),
  provider profiles (Settings → AI), and each customer's AI policy (analysis,
  model comparison, allowed profiles, daily budget, on-premises only, and
  whether technicians may use their own keys). Without a customer policy
  nothing is allowed there. Technicians then also need L1 or above at that
  customer.
- **What leaves the server.** The ticket's subject, description and public
  conversation (up to 20 replies), plus a summary of its asset and RMM status
  when the asset is verified as the customer's own. It is redacted first:
  private keys, API keys and tokens, `password: …`-style values, card numbers,
  e-mail addresses and phone numbers. The technician sees exactly this before
  sending. It goes to the provider of the chosen profile (Anthropic or OpenAI
  in the cloud, or an approved on-premises Ollama).
- **What never leaves.** Vault entries, keys and backup credentials,
  attachments, internal-note bodies, raw RMM payloads, and session or
  remote-access data.
- **Who reviews.** Results are visible only to technicians. A draft is placed
  in the composer and goes out only when a technician with "Send reviewed AI
  replies" presses Send. No AI output closes a ticket, sends a reply or
  changes a device by itself.

Evidence: `psa_ai/services/evidence.py`, `psa_ai/services/profiles.py`,
`psa_ai/profile_views.py`; tests `psa_ai/tests.py`, `psa_ai/tests_assist.py`.

## RMM: three different things

| What | What it is | Who enforces it | Status |
|---|---|---|---|
| **Connect link** ("Connect with Rem0te" on asset and ticket pages) | Opens the computer's page in rem0te. No key, password or session credential is in the link | **rem0te**, with the technician's own rem0te sign-in | Shipped (v3.17.644), technicians only |
| **Handoff** | A private note about the ticket to the RMM that manages the device | ClientSt0r (preset) | Planned |
| **Remote-session request** | Asking for a view or control session | **rem0te** grants each session; ClientSt0r only asks | Planned |
| **Endpoint change** (a fix) | Work on the device | **rem0te** approves and runs it; ClientSt0r never sends commands | Planned |

An AI suggestion, a ClientSt0r approval or a technician's preset is **not**
proof that rem0te authorized or ran anything. Only rem0te's own records show
that. ClientSt0r has no endpoint command path: the old `run_rmm_script` AI
action was removed, and the RMM adapters only read.

Evidence: `tech_access/catalog.py` (`LOCKED`, `NEEDS_LIVE_REMOTE`),
`integrations/rmm_association.py`,
[contracts/ticket-rmm-v1](contracts/ticket-rmm-v1/README.md).

## Limitations

Known gaps, stated plainly:

- **The audit log isn't tamper-proof.** Superusers can delete entries (in
  Django admin, and with the Maintenance clean-up). There is no automatic
  retention, and audit-log exports aren't themselves recorded.
- **Azure AD single sign-on skips TOTP.** The identity provider is trusted for
  the second factor. Each such sign-in is recorded as `azure_ad_2fa_bypass`.
- **Mobile app tokens last until revoked** unless `MOBILE_TOKEN_TTL_DAYS` is
  set.
- **Content Security Policy is report-only by default.** Set
  `CSP_REPORT_ONLY=False` once the `security.csp` log is clean.
- **AI gateway isolation needs setup.** By default (`AI_GATEWAY_MODE=in_process`)
  the web app opens provider keys itself. Worker mode keeps them away from
  the vault key.
- **Granting superuser is not a two-person change** yet.
- **Staff without a global role** can list vault entry titles at every
  customer. Revealing still needs a membership with the reveal permission, or
  a global role that grants it.
- **Ticket text and attachments aren't encrypted** by the app.
- **Browser-extension offline cache.** A role with "extension offline cache"
  can sync encrypted vault blobs to the extension. That sync doesn't pass
  through the per-entry reveal checks (approval, access rules, rate limit); it
  is recorded once per sync with a count. Leave that permission off unless
  you need it (it is off by default).

## Setup checklist

1. Set `APP_MASTER_KEY` and keep it out of backups of the database.
2. Keep two-factor sign-in required. If you use Azure AD, enforce MFA there.
3. Review custom roles: untick "View actual password values" where it isn't
   needed.
4. Turn on reveal approval for high-value credentials, and add access rules if
   reveals should only happen from your office or country.
5. Give MSP staff a global role if they shouldn't have full reach.
6. If you use ticket AI, set `AI_GATEWAY_MODE=worker` and set each customer's
   AI policy deliberately.
7. Check Settings → Security → Security Features for each customer.

## Reporting a vulnerability

See [SECURITY.md](../SECURITY.md).
