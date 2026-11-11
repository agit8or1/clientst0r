# How ClientSt0r protects client data

This page describes what ClientSt0r does as of v3.17.656, plus the
ticket-to-RMM integration that ships in v3.17.658 (marked where it applies).
Planned work is in [ROADMAP.md](ROADMAP.md), not here. Every statement below
points to the code or test that backs it. Administrators can see whether each
safeguard is actually in effect at a given customer under **Admin → Security →
Security Features** (`/core/security/features/`).

The examples use made-up customers, people and tickets.

## Who can see what

ClientSt0r has two kinds of users, and they get different reach on purpose.

| | Customer users (User Type: Organization User) | MSP staff (User Type: Staff) and superusers |
|---|---|---|
| Customers they can open | Only organizations they're a member of (a parent organization covers its subsidiaries) | **Every customer.** Staff work across all clients by design (`core/tenancy.py`, `is_cross_tenant_user`) |
| What they can do there | Their membership's role: Owner, Admin, Editor, Read-only, or a custom role | A staff global role, if one is set, narrows this; without one, staff have full reach. Superusers can do everything |
| Tickets | Tickets shared with them, and only the public conversation | Every ticket, including internal notes and working data |
| Vault entries (titles, usernames, counts) | Customers where their role has "view vault" | Superusers always. Staff with a global role: every customer when it grants "view vault". Staff **without** a global role: only customers where a membership grants it (since v3.17.653) |
| Vault values | Only with the reveal permission at that customer (below) | Superusers always; staff when their global role allows it |
| Ticket AI and RMM tools | Never | Only with a technician access assignment at that customer (below). Staff, admin and superuser flags grant nothing on their own |

A vault title can say something about a customer by itself ("Payroll
Administrator"), so seeing that an entry exists is limited the same way as
the vault itself: the web vault and its counts, global search, the REST,
GraphQL and mobile APIs, the browser extension, dashboards, process-stage
pickers, relationship maps, readiness and vault reports all use the
customer's "view vault" permission. Seeing an entry and revealing it stay
separate: a technician who may see an entry can find it and, when their role
allows reveals, request approval for it. Admin → Security → **Vault
Visibility** lists the staff who lost cross-customer visibility in that
change; it is read-only and grants nothing. To restore access on purpose, add
a membership or a global role that grants "view vault".

Evidence: `accounts/permission_utils.py` (`user_has_org_perm`, `orgs_with_perm`),
`psa/visibility.py`, `tech_access/resolver.py`;
tests `psa/tests/test_internal_ticket_visibility.py`,
`tech_access/tests.py` (`test_superuser_staff_and_owner_flags_never_imply_access`,
`test_portal_users_are_outside_presets_even_with_an_assignment`),
`vault/tests_release_653.py` (`TitleVisibilityTests`, `VisibilityReportTests`).

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
| Private RMM handoff | – | yes | yes | ClientSt0r sends it; the RMM confirms receipt |
| Read-only diagnostics | – | standard workstations | standard workstations (advanced diagnostics: see below) | The RMM runs only diagnostics it advertises |
| Remote session (view / control / elevation) | – | may **request** view or control | may request view, control or elevation | **The paired RMM** grants each session |
| Request a catalog fix | – | low-risk | low- and higher-risk | **The paired RMM** approves and runs it |
| Approve an endpoint fix | locked | locked | locked | Only the paired RMM, on its own approval page |
| Vault data, bulk export, cross-customer access, security administration | locked | locked | locked | Never through a preset |

The RMM, diagnostics, remote-session and fix rows act only through a paired
RMM (v3.17.658, [below](#rmm-pairing-and-ticket-actions)). Each shows
**Unavailable** at a customer until that customer's paired RMM advertises the
matching capability. Read-only diagnostics cover standard workstations only;
advanced diagnostics (servers) and elevation are capability switches with no
ticket action yet.

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

The RMM pages themselves (`/integrations/rmm/`: devices, software, alerts,
console links, connections, sync) answer 403 to customer users, whatever role
they hold at their own organization. Among technicians, deleting a device or
changing a connection needs an administrator, a sync needs write access, and
a device outside the selected customer answers 404. Evidence:
`accounts/middleware.py` (`STAFF_ONLY_PREFIXES`), `integrations/views.py`
(`rmm_staff_only`, `rmm_device_delete`); tests
`integrations/tests_rmm_scope.py`.

## A secret sent with a ticket reply

*Example.* Ridgeline's new starter needs a temporary password. The
technician ticks "Email this reply", opens **Add a secure message** and types
it.

- The secret is stored encrypted as a link-only Secure Note. It opens once by
  default and expires after 1, 3 or 7 days (3 by default).
- The link goes only into the e-mail to the requester, so a secure message
  can't be combined with Cc. Only a hash of the link token is stored, and
  stored copies of the sent e-mail have the link replaced with a placeholder.
  If the e-mail fails, the message is withdrawn.
- The ticket never shows the secret, only its state: sent and not opened yet,
  opened by the recipient, expired unopened, or withdrawn. The customer's
  portal view says it was sent to their e-mail.
- The link opens a page with a **Show the message** button, so mail scanners
  and link previews that fetch links don't use up a one-time message (this
  applies to every read-once or view-limited Secure Note link since
  v3.17.654).

Evidence: `psa/ticket_secure.py` (`create_secure_message`, `secure_status`,
`scrub_secret_links`); tests `psa/tests/test_ticket_cc_secure.py`.

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
4. **Rate limit.** 30 reveals per hour per user, counted across the web vault
   and the browser extension together; the mobile API has its own 30/hour.
5. **Audit.** The reveal writes an audit event: action `reveal`, object
   type `password`, the user, the entry, the customer and the address. Copying
   the value is recorded as a reveal. Browser-extension reveals are recorded
   the same way (since v3.17.652; before that, as action `read` with event
   `vault_extension_reveal`).

The same checks guard the web vault, the REST API (`?reveal=true` and
`/reveal/`), the mobile API and the browser extension's reveal and TOTP
calls. List responses never
include the value. GraphQL lists only entries in customers where the caller
has vault access, and never returns the value.

### Offline copies in the browser extension

A role with "extension offline cache" (off by default) can sync encrypted
copies of vault entries to the extension. An entry whose reveal needs a live
check never goes into that cache with its secret: one that needs approval, or
that any active access rule applies to — a rule on the entry, on its customer
(which every entry there inherits), or on that technician at that customer.
Country, address and time conditions can only be judged when someone
reveals, so a rule applying at all is enough. The sync still lists the entry,
marked `online_only` with no secret and the message "Connect to ClientSt0r to
reveal this password." A complete sync replaces the cache (`cache_policy:
replace`), so an entry cached yesterday and restricted today loses its local
copy at the next successful sync. **A device that stays disconnected keeps
its old copy until it reconnects and syncs**; to cut off a lost device,
revoke its extension token. Each sync is audited with how many entries were
sent and how many were online-only.

Evidence: `vault/permissions.py` (`gate_reveal`), `vault/access_rules.py`
(`online_only_ids`), `vault/extension_views.py` (`bulk_sync`),
`api/views.py`; tests `vault/tests.py`, `vault/tests_extension_gate.py`,
`vault/tests_release_653.py` (`OfflineCacheRestrictionTests`),
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

## RMM pairing and ticket actions

These are not AI features: they work with `psa_ai_enabled` off. They need the
service desk, a technician access assignment at the customer, and a paired
RMM.

| What | What it is | Who enforces it | Status |
|---|---|---|---|
| **Console link** ("Open in …" / "Connect with Rem0te" on asset and ticket pages) | Opens the device's page in the RMM. No key, password or session credential is in the link | **The RMM**, with the technician's own RMM sign-in | Shipped (v3.17.644), technicians only |
| **Pairing** | Any RMM that implements [ticket-rmm-v1](contracts/ticket-rmm-v1/README.md), on a single-customer connection: a key ID and two shared secrets (stored encrypted), signed requests both ways, pinned to the RMM tenant named in its first capabilities check | A second administrator approves turning it on (protected change) | v3.17.658 |
| **Handoff** | The ticket's redacted context, previewed first, sent privately to the RMM | ClientSt0r (preset); marked Sent only on the RMM's signed receipt | v3.17.658 |
| **Read-only diagnostic** | One named diagnostic from the RMM's advertised list, on a standard workstation | The RMM runs it; the result is sanitised, limited to 32 KiB and staff-only | v3.17.658 |
| **Remote session** | A view or control session | **The RMM** grants each session; ClientSt0r checks the launch address is on the connection's console hosts and expires within 10 minutes, then forgets it | v3.17.658 |
| **Fix referral** | A request for work on the device | **The RMM** approves and runs it; ClientSt0r never sends commands | v3.17.658 |

- **Which devices.** Only the ticket's own asset, through an RMM device
  linked to it at the same customer, on a live pairing of that customer. The
  browser can't name any other device.
- **Pairing changes.** Turning pairing on, or marking the RMM on-premises,
  waits for a second administrator. Changing a secret, the key ID, the
  address or the provider of a live pairing switches it off until it is
  approved again. If the RMM ever answers for a different tenant, the pairing
  stops.
- **What comes back.** Signed status events update the request row only. No
  status can close the ticket or send a customer reply, and customers see
  none of it.
- **Audit.** Every request and every remote launch is audited; the launch
  address itself is never stored or logged.

An AI suggestion, a ClientSt0r referral or a technician's preset is **not**
proof that the RMM authorized or ran anything. Only the RMM's own records
show that. ClientSt0r has no endpoint command path: the old `run_rmm_script`
AI action was removed, and the RMM adapters only read.

Evidence: `integrations/ticket_rmm.py`, `psa_ai/services/rmm_actions.py`,
`psa_ai/rmm_views.py`, `tech_access/catalog.py` (`LOCKED`,
`NEEDS_LIVE_REMOTE`, `INTEGRATION_REQUIRES`),
`integrations/rmm_association.py`; tests `psa_ai/tests_rmm.py`.

## Granting superuser

A superuser controls the whole installation. Admin → Security → **Superuser
Approval** turns on an optional policy (off on upgrade): one administrator
requests the grant and a different one approves it, both re-entering their
password (and authenticator code). The account is not a superuser until the
approval. The policy covers creating a superuser and promoting an existing
account on the user page and in Django admin.

- **Turning it on** needs two different eligible administrators (active
  superusers who approve protected changes); with one, nobody could approve.
- **Turning it off** is itself a protected change: one administrator can't do
  it alone.
- **Refused:** approving your own request; the target approving their own
  grant; approving before the requester confirms; approving twice (the second
  finds it already applied). Asking again for the same account returns the
  open request.
- **Logged:** each request, confirmation, approval, rejection and
  cancellation, with the requester, approver, target account and outcome
  (audit events `superuser_grant_requested`, `superuser_grant_approved`,
  and protected-change entries).
- **Host-level commands.** Anyone with a shell on the server as the
  application user already controls the installation, so the application
  can't stop `manage.py createsuperuser` or the Django shell. Every
  superuser grant made outside the approval is recorded
  (`superuser_granted_outside_approval`) and, while the policy is on,
  e-mailed to the other superusers and the verified recovery contact. If only
  one eligible administrator is left, `manage.py superuser_policy --disable
  --reason "..."` turns the policy off from the host; that is audited
  (`superuser_policy_disabled_on_host`) and announced the same way.
  Revoking superuser is never held for approval.

Evidence: `tech_access/services.py` (`propose_superuser_grant`,
`enable_superuser_policy`, `propose_disable_superuser_policy`),
`tech_access/signals.py`, `tech_access/admin.py`, `accounts/views.py`
(`user_create`, `user_edit`),
`tech_access/management/commands/superuser_policy.py`; tests
`tech_access/tests_superuser_653.py`.

## Limitations

Known gaps, stated plainly:

- **The audit log isn't tamper-proof.** Superusers can delete entries (in
  Django admin, and with the Maintenance clean-up). Each deletion is recorded
  with a count, but the deleted entries are gone. There is no automatic
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
- **Superuser approval is optional and off by default.** See
  [Granting superuser](#granting-superuser). Commands run on the host
  bypass it; they are recorded and announced.
- **Ticket text and attachments aren't encrypted** by the app.
- **RMM request status is the RMM's word.** A fix shown as approved or
  succeeded reflects the RMM's signed events, not something ClientSt0r
  checked on the device.
- **Browser-extension offline cache.** Restricted entries are synced without
  their secret (see above), but a disconnected device keeps what it already
  had until it reconnects, and offline use isn't rate-limited. Leave that
  permission off unless you need it (it is off by default).

## Setup checklist

1. Set `APP_MASTER_KEY` and keep it out of backups of the database.
2. Keep two-factor sign-in required. If you use Azure AD, enforce MFA there.
3. Review custom roles: untick "View actual password values" where it isn't
   needed.
4. Turn on reveal approval for high-value credentials, and add access rules if
   reveals should only happen from your office or country.
5. Give MSP staff a global role if they shouldn't have full reach. Check
   Admin → Security → Vault Visibility after upgrading to 3.17.653.
6. With two or more administrators, turn on Superuser Approval.
7. If you use ticket AI, set `AI_GATEWAY_MODE=worker` and set each customer's
   AI policy deliberately.
8. If you pair an RMM, pair one single-customer connection per customer and
   give technicians the lowest preset that covers their work.
9. Check Admin → Security → Security Features for each customer.

## Reporting a vulnerability

See [SECURITY.md](../SECURITY.md).
