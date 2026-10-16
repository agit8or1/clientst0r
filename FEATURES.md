# ClientSt0r Features

Feature documentation for ClientSt0r — self-hosted IT documentation and service desk for
MSPs: client assets, runbooks, an encrypted credential vault, native ticketing with SLAs and
billing, monitoring and compliance.

See the [README](README.md) for positioning and install steps, and
[docs/screenshots.md](docs/screenshots.md) for the visual tour.

## How to read this page

Every capability carries one of four labels:

| Label | Meaning |
|---|---|
| **Available** | Works as described. |
| **Limited** | Works, with a limitation stated next to it. |
| **Planned** | Not implemented yet, or only partly built (for example, settings that are saved but not acted on). Planned work is tracked in the [roadmap](docs/ROADMAP.md). |
| **Separate component** | Not part of the web application in this repository, or shipped separately. |

The **Where** column gives the screen (URL path on your install) or the document to read.
Settings pages are under **Admin → System → Settings** (`/core/settings/…`).

Contents:
[Access model](#access-model-msp-staff-and-customer-users) ·
[Security](#security) ·
[Organizations and roles](#organizations-and-roles) ·
[Assets](#assets) ·
[Password vault](#password-vault) ·
[Documentation](#documentation) ·
[Monitoring](#monitoring) ·
[Infrastructure](#infrastructure) ·
[Locations](#locations-and-navigation) ·
[Service vehicles](#service-vehicles) ·
[Workflows](#workflows-process-templates) ·
[Network integrations](#network-hardware-integrations) ·
[Service desk](#service-desk-native-psa) ·
[Billing behaviour](#billing-behaviour-for-administrators) ·
[Scheduled jobs](#scheduled-jobs) ·
[PSA integrations](#psa-integrations) ·
[RMM integrations](#rmm-integrations) ·
[Notifications](#notifications) ·
[Reporting](#reporting-and-financial-analytics) ·
[Resource management](#resource-management) ·
[AI](#ai-features-optional-ai) ·
[Compliance](#compliance-frameworks) ·
[Administration](#administration) ·
[API](#api) ·
[Browser extension](#browser-extension) ·
[Mobile](#mobile) ·
[Import and export](#import-export-and-backup) ·
[Deployment](#deployment) ·
[Architecture](#architecture)

---

## Access model: MSP staff and customer users

Every user is either **MSP staff** or a **customer user**. This decides what they can see,
on top of their role.

- **MSP staff** — superusers, users with Django's staff flag, and users whose **User Type**
  is *Staff* (set at *Admin → Access Management → Users → Edit*, `/accounts/users/<id>/edit/`,
  superusers only). Staff work across every customer: since v3.17.602 a Staff user can be
  assigned tickets, projects and recurring work for any customer, not only customers they
  are a member of, and membership-based permission checks (change approvals, problem
  links, ticket sharing, procurement and similar) also honour a Staff user's global role.
  A global role only adds capabilities; anything a membership grants still applies.
- **Customer users** — everyone else: people who log in for one of your customers. Since
  v3.17.599–600 they:
  - see and act only on the organizations they are a member of (contracts, invoices,
    projects, quotes, recurring schedules, purchase records, email-to-ticket configs,
    canned replies, client accounts and portal invites included);
  - see only tickets marked as visible to the client, with no internal comments and no
    internal attachments — on the staff ticket pages, the customer portal and the mobile
    app alike;
  - cannot open the global dashboard, cannot edit or delete global document templates
    (they manage their own organization's templates), and don't receive the MSP's global
    knowledge base through the APIs or mobile app;
  - have API keys that stop working once they leave the key's organization.

**Action for upgraded installs:** a technician set up as an ordinary member of customer
organizations is now treated as a customer user. Set their User Type to Staff. Tickets are
not shared with the client by default; share the ones customer users should see (tickets
created from the customer portal are shared automatically).

---

## Security

### Authentication and sessions

| Capability | Status | Notes | Where |
|---|---|---|---|
| Enforced TOTP 2FA | Available | On by default for every account. Set install-wide in Settings → Security (**Require 2FA**); the `REQUIRE_2FA` environment variable, if set, overrides it. LDAP users get the same 2FA rules. | `/accounts/profile/2fa/`, `/core/settings/security/` |
| Azure AD / Microsoft Entra ID SSO | Limited | Sign-in with auto-created users works. SSO sessions skip the local 2FA prompt without checking that the user completed MFA in Entra ID, so enforce MFA there. | `/core/settings/directory/` |
| LDAP / Active Directory sign-in | Available | Since v3.17.608. Off until enabled; won't switch on with missing or invalid settings. Several servers, LDAPS or StartTLS with certificate checking (on by default, optional CA file), user search with attribute mapping, a required group (nested AD groups included) and an optional MSP staff group that sets Staff vs customer user at each sign-in. **Test connection** checks the bind and an optional user lookup without saving. Local accounts keep working and a local superuser can always sign in; LDAP never creates superusers or takes over an existing local account. Needs the optional `django-auth-ldap` and `python-ldap` packages (`requirements-optional.txt`); the page says if they're missing. | `/core/settings/directory/` |
| SAML, generic OIDC, passkeys | Planned | | [Roadmap](docs/ROADMAP.md) |
| Argon2 password hashing | Available | | — |
| Brute-force lockout | Available | django-axes, by username + IP. Failed-login limit (default 5) and lockout duration (default 30 minutes) are set in Settings → Security; the `AXES_FAILURE_LIMIT` and `AXES_COOLOFF_TIME` (hours) environment variables, if set, override them. Applies to LDAP users too. | `/core/settings/security/`, `/accounts/locked/` |
| Session expiry | Available | Idle timeout (default 60 minutes) and a real maximum session length (default 8 hours; before v3.17.610 expiry was renewed on every request), set in Settings → Security. `SESSION_IDLE_TIMEOUT` and `SESSION_COOKIE_AGE` (seconds), if set, override them. | `/core/settings/security/` |
| Password policy | Available | Minimum length (default 12) and special-character rule from Settings → Security (`PASSWORD_MIN_LENGTH` / `PASSWORD_REQUIRE_SPECIAL` override); also not a common password, not all numeric, not similar to the username. | `/core/settings/security/` |
| Settings precedence | Available | Since v3.17.610 saved Security settings take effect. An environment variable, if set, wins; the field then shows **set by environment** and is read-only. Check Settings → Security before updating an older install — the saved values become live. | `/core/settings/security/` |

### Data protection

| Capability | Status | Notes | Where |
|---|---|---|---|
| Vault encryption | Available | AES-256-GCM. Vault passwords, TOTP secrets and the personal vault use per-purpose keys derived with HKDF-SHA256 from `APP_MASTER_KEY`, with the record's context bound as associated data. | `/vault/` |
| Stored secrets | Available | Since v3.17.607 every stored secret is encrypted, or hashed where the app only needs to compare it: integration and connection credentials, SMTP and SMS passwords, the LDAP bind password and Azure AD client secret, warranty and scanner API keys, partner secrets, webhook secrets and custom headers, import API keys, push-notification secrets, license keys, security-vendor and SIEM credentials, and browser-extension and inbound webhook tokens. Integration credentials, SMTP/SMS passwords and secure notes use the current format, bound to the field they belong to. Forms never show a stored secret back; leave a field blank to keep it. Since v3.17.612 this also covers mobile app sign-in tokens (hashed, one per device), share links for secure notes, surveys, status pages, wallboards and quotes, and 2FA authenticator seeds and backup codes. License keys are masked until revealed, through the same approval and audit as passwords. | — |
| Key rotation and storage audit | Available | `python manage.py rotate_encryption_key` re-encrypts everything under a new master key in one transaction, verifying every value before committing (`--dry-run` available). `APP_MASTER_KEY_PREVIOUS` lets old keys keep decrypting during a rotation and for restoring older backups. `python manage.py check_secrets_storage` reports any secret stored unprotected and exits non-zero (usable in CI). Losing `APP_MASTER_KEY` makes encrypted data unrecoverable; keep a copy off the server. | [SECURITY.md](SECURITY.md#secrets-management) |
| API key storage | Available | API keys are stored as HMAC-SHA256 hashes; only a prefix is kept in plaintext. | `/api/keys/` |
| Protected file downloads | Available | Since v3.17.600 every `/media/` request goes through a view that finds the record the file belongs to and applies that record's permissions (tickets, documents, diagrams, locations, logos, attachments). Files no record claims return 404. Only the branding logo and login background are public. On Docker, nginx no longer serves `/media/` itself. | — |

### Application security

| Capability | Status | Notes |
|---|---|---|
| SQL injection prevention | Available | Django ORM throughout. |
| XSS protection | Available | Template auto-escaping; document HTML is sanitised. |
| CSRF protection | Available | Including multiple trusted origins. |
| SSRF protection | Available | Outbound URL validation that re-checks the resolved address. |
| Path traversal prevention | Available | Media paths are normalised and confined to the media directory. |
| Tenant isolation (IDOR) | Limited | Org-scoped queries and per-view checks, extended in v3.17.599–600 to PSA records and customer users. Some role checks still pass if a flag is set on any of the user's memberships rather than the record's organization; tracked in the [roadmap](docs/ROADMAP.md). |
| Rate limiting | Limited | DRF throttles on the API; per-view limits on vault reveal and a few other sensitive pages. |
| Security headers | Available | HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy and Permissions-Policy. |
| Content-Security-Policy | Limited | Since v3.17.610, sent on every page with a per-request nonce on inline scripts. It starts in **report-only** mode: violations are logged (`security.csp` logger) and nothing is blocked. Set `CSP_REPORT_ONLY=False` to enforce once the log is quiet; `CSP_ENABLED=False` turns it off. |

### Vulnerability scanning

| Capability | Status | Notes | Where |
|---|---|---|---|
| Dependency scanning (Snyk) | Available | Needs the Snyk CLI and a Snyk token. Python dependency scanning (pip-audit) also available. | `/core/settings/snyk/`, `/core/security/python-scanner/` |
| OS package scanner | Available | apt, yum/dnf and pacman; security-update detection, history, manual scans. | `/core/security/package-scanner/` |
| Scheduled scans with email alerts | Available | Opt-in from the Security dashboard; emails superusers when vulnerabilities are found. Interval is set in Settings → Scheduler. | `/core/security/` |
| Trend view | Limited | Compares the latest scan with the previous one; no long-term chart. | `/core/security/` |
| Webhook notifications for scan results | Planned | Email only. | — |

### File upload checks

| Capability | Status | Notes |
|---|---|---|
| File-type allowlist, 25 MB limit, content sniffing | Limited | Applied to the files/attachments uploads and ticket attachments. The document bulk upload (`/docs/upload/`) does not check type or size. |

### Audit logging

| Capability | Status | Notes | Where |
|---|---|---|---|
| Audit log | Limited | Two sources. Explicit events: sign-ins, credential reveals and reveal approvals, API key use, extension calls, updates, and many create/update/delete actions. Plus a request log: every POST/PUT/DELETE and detail-page view, with method, path, status and (redacted) form fields. There are no before/after values for most changes, and list-page views are not logged. | `/audit/` (Owner/Admin) |
| Security events | Limited | Credential access is logged explicitly. Role and permission edits appear only as request-log entries. Failed logins are recorded by django-axes. | `/audit/` |
| Export | Limited | CSV and JSON, current organization only, up to 5,000 rows per export. | `/audit/?export=csv` |

### IP and country access rules

| Capability | Status | Notes | Where |
|---|---|---|---|
| IP allow and block rules | Available | Enforced by the application (middleware), not by the host firewall. | `/core/settings/firewall/ip-rules/` |
| Country (GeoIP) rules | Available | Uses a local country database refreshed by the scheduler, with an online lookup as fallback. Country rules also cover the sign-in pages. | `/core/settings/firewall/country-rules/` |
| Blocked-request log | Available | | `/core/settings/firewall/logs/` |
| Host firewall (iptables) management | Planned | Not implemented; the rules above are application-level. | — |
| Fail2ban management | Available | View jails and bans, unban one or all, check an IP. Native installs; fail2ban must be installed on the host (a button on the page can install it). Root actions go through the signed root helper. | `/core/settings/fail2ban/` |

---

## Organizations and roles

### Organizations

| Capability | Status | Notes | Where |
|---|---|---|---|
| Per-organization data | Available | Every asset, document, credential, location and ticket belongs to an organization. See [Access model](#access-model-msp-staff-and-customer-users). | `/accounts/organizations/` |
| Unlimited organizations | Available | | |
| Parent / child organizations | Available | A parent organization sees its children's records. | Organization edit page |
| Per-organization branding | Limited | Each organization can have a logo (used in the customer portal) and a portal accent colour. Site name, logo and background are install-wide. | Organization edit page |
| MSP staff global access | Available | Staff see all organizations, limited by their global role. | Organization switcher |

### Roles and permissions

| Capability | Status | Notes | Where |
|---|---|---|---|
| Built-in roles: Owner, Admin, Editor, Read-Only | Available | | Members page |
| Custom roles | Available | Around a hundred individual permission switches, grouped by area. | `/accounts/roles/` |
| **View passwords / View documents / View assets** | Available | Enforced since v3.17.600 everywhere those records appear: vault, documents and assets pages, global search (with real totals), dashboards, REST and GraphQL APIs, mobile app and browser extension. Contacts follow View assets. A user's personal vault is unaffected. The ticket sidebar's credential card follows View passwords and shows titles only. | `/accounts/roles/` |
| **View files / View monitors / View integrations** | Planned | Saved but not enforced; the role editor marks each "(not enforced yet)". | `/accounts/roles/` |
| Vault export permission | Planned | Marked "Not yet implemented" in the role editor. | — |
| Document publish permissions | Available | Since v3.17.605 publishing needs View/Publish documents for that customer (or Publish KB articles for global articles); without it, new documents, uploads and imports save as drafts. | Document form |
| Role assignment limits | Available | A role can be assigned only if it is a system role or the organization's own custom role. | Members page |

### Users

| Capability | Status | Notes | Where |
|---|---|---|---|
| User types: Staff and Organization user | Available | See [Access model](#access-model-msp-staff-and-customer-users). | `/accounts/users/<id>/edit/` |
| Create, edit, suspend, reset password | Available | | `/accounts/users/` |
| Bulk user import / export | Planned | | — |

---

## Assets

| Capability | Status | Notes | Where |
|---|---|---|---|
| Asset records | Available | Name, type, manufacturer, model, serial, hostname, network, OS, hardware, rack position, lifecycle dates, tags, notes. | `/assets/` |
| Asset types | Limited | A fixed list of types. Custom asset types exist in the data model but have no screens. | — |
| Custom fields | Limited | Stored per asset and filled by imports and the API; not editable on the asset form. Required custom fields are not enforced. | — |
| Relationships | Available | Link assets to documents, passwords, contacts and other assets; relationship map. | `/assets/relationships/map/` |
| Tags and photos | Available | Photos are uploaded as attachments and shown in a carousel. | Asset detail |
| Switch / patch-panel port configuration | Available | | `/assets/<id>/ports/`, `/monitoring/patch-panels/` |
| Contacts | Available | Follow the View assets permission. | `/assets/contacts/` |
| RMA tracking | Available | | `/assets/rma/` |
| Filters | Limited | Filter by type, manufacturer, status and location; no keyword box on the list (use global search). | `/assets/` |
| Status (active / retired …) | Limited | Not a dedicated field; stored and filtered as a custom field. | `/assets/` |
| Lifespan and end-of-life | Limited | Purchase date, expected lifespan, calculated EOL date, "Nearing EOL" badge and health score. Reminders are in-app only; warranty alerts are emailed by the scheduler. | Asset form / detail |
| Bulk edit | Planned | | — |
| Per-asset change history | Planned | Changes appear only in the audit log's request entries. | — |
| Export | Limited | Whole-install JSON export (also in Hudu / IT Glue formats, without passwords) and the REST API; no per-list CSV export. | `/core/settings/data-export/` |
| CSV / spreadsheet import | Available | CSV and .xlsx with a field mapper. | `/imports/` |

---

## Password vault

| Capability | Status | Notes | Where |
|---|---|---|---|
| Encrypted credentials | Available | AES-256-GCM with HKDF-derived keys; see [Data protection](#data-protection). | `/vault/` |
| 15 credential types | Available | Website, email, Windows/AD, database, SSH, API key, OTP, credit card, network device, server, FTP/SFTP, VPN, Wi-Fi, software licence, other. | `/vault/create/` |
| Folders | Available | Hierarchical. | `/vault/` |
| Reveal with audit | Available | Every reveal is logged and rate-limited. | `/vault/<id>/` |
| Reveal approval and break-glass | Available | Requests email the administrators (these emails were not sent before v3.17.600). | `/vault/reveal-requests/` |
| Access rules | Available | Allow or deny access by country, source IP range and time of day, scoped to an entry, a user or an organization; deny wins. | `/vault/access-rules/` |
| Password generator | Available | 8–128 characters, cryptographically secure. | Entry form |
| Strength meter | Available | | Entry form |
| Breach detection (Have I Been Pwned) | Available | k-anonymity: only a 5-character hash prefix leaves the server. Scheduled scan; per-entry check. | Entry detail; Settings → Scheduler |
| Blocking breached passwords | Limited | Off by default; enabled only by the `HIBP_BLOCK_BREACHED` environment variable. | — |
| Expiry tracking | Available | Expiry dates with scheduled email warnings. | Entry form |
| TOTP codes and QR | Available | | `/vault/<id>/otp/` |
| Personal vault | Limited | Private to its owner in the application. It is encrypted with the server's master key (not a per-user key), so anyone with server and key access could decrypt it. | `/vault/personal/` |
| Bitwarden / Vaultwarden import | Limited | JSON import of logins, notes, cards and identities, with folders, custom fields, TOTP secrets and update-existing. Superusers only, and the page is not linked from the menus. | `/core/settings/vault-import/` |
| Customer portal visibility | Available | Per entry: hidden (default), all members of the customer, specific users, or managed by the customer's admin. Personal entries are never shown. | `/portal/vault/` |

---

## Documentation

| Capability | Status | Notes | Where |
|---|---|---|---|
| Per-organization documents | Available | Follow the View documents permission. | `/docs/` |
| Categories | Available | Default categories are created at install. | `/docs/categories/` |
| Editor | Available | WYSIWYG (HTML), Markdown, or an uploaded file as the document. | `/docs/create/` |
| Templates | Available | Global templates are edited by MSP staff only; customer users with edit rights manage their own organization's templates. | `/docs/templates/` |
| Version history | Available | A version is saved on every edit. Since v3.17.605 you can view any version, compare two versions and restore one (audited; the replaced content is kept as a version). | `/docs/id/<id>/versions/` |
| Owner and review interval | Available | Editable on the document form; the document page shows the owner and next review date. | Document form / detail |
| Drafts and Archived lists | Available | Drafts never appear in document lists, search, exports or the portal. Archived documents can be unarchived. | Docs → Drafts (`/docs/lifecycle/drafts/`), Docs → Archived (`/docs/lifecycle/archived/`) |
| Template drift | Available | Documents created from a template remember the template version; each template lists the documents that are behind, with a diff of what changed. Nothing is overwritten. | `/docs/templates/<id>/documents/` |
| Search | Limited | Substring match on title and body. | `/docs/?q=`, `/core/search/` |
| Review and approval | Available | Publishing follows the publish permissions (see [Roles](#roles-and-permissions)); documents that require approval go through Submit for review → Approve. Review reminders are emailed weekly. | `/docs/review-queue/`, `/docs/approval-queue/` |
| KB analytics | Available | MSP staff: most viewed, never viewed, past review date, and searches that found nothing. Only zero-result searches are logged (never vault searches), kept for 90 days. | Docs → KB Analytics (`/docs/lifecycle/analytics/`) |
| Documentation readiness | Available | Since v3.17.605. Standards define what every customer (or every customer of a type, or with assets of a type) must have documented: documents by tag, category or title, review freshness, owners, required asset fields, contacts with a role, credential references (metadata only) and asset relationships. Each customer gets a score with a plain explanation and fix link for every unmet requirement, and an owner; a repair queue lists everything unmet across customers. Per-customer exceptions (reason, optional expiry) are audited. Customer users with View documents see their own customer's page read-only. `manage.py readiness_seed_samples` adds a sample Microsoft 365 tenant standard (not added automatically). | Docs → Documentation Readiness (`/readiness/`, `/readiness/repair/`) |
| Broken relationships report | Available | Links whose target no longer exists or belongs to another customer, with cleanup for staff (`manage.py readiness_find_broken_relationships --delete`). | `/readiness/relationships/broken/` |
| Global knowledge base | Available | Staff-only on the web; not returned to customer users by the APIs or mobile app. Client-visible articles appear in the customer portal. | `/docs/kb/` |
| Pre-written KB content | Limited | Not installed by default; an administrator imports it. | `/core/settings/kb-import/` |
| Diagrams (draw.io) | Available | With previews and templates. | `/docs/diagrams/` |
| Export | Available | Markdown, HTML, DOCX and PDF, single or bulk. | Document detail → Export |
| File attachments on documents | Planned | | — |
| Document favorites | Planned | Favorites exist for assets, passwords and some other records. | `/core/favorites/` |
| Share links | Planned | | — |

---

## Monitoring

| Capability | Status | Notes | Where |
|---|---|---|---|
| HTTP/HTTPS uptime checks | Available | Response time and status code. | `/monitoring/websites/` |
| Check interval | Limited | Set per monitor in minutes; checks run at most every 5 minutes. | Monitor form |
| Downtime alerts | Available | Since v3.17.609, with "notify on down" on, a monitor emails superusers and the customer's admins once after two failed checks in a row, and once when it recovers — not on every failed check. The same transitions fire `monitor.down` / `monitor.up` webhooks. | Monitor form |
| SSL certificate details and expiry warnings | Available | Subject, issuer, serial, validity dates, TLS version; expiry warnings by email (daily). | Monitor detail |
| Certificate chain validation | Limited | Invalid chains fail the check; chain details are not stored. | — |
| Domain expiry tracking | Limited | No WHOIS lookup; enter expiry dates by hand. Reminders by email (daily). | `/monitoring/expirations/` |
| View monitors permission | Planned | Not enforced; see [Roles](#roles-and-permissions). | — |

---

## Infrastructure

| Capability | Status | Notes | Where |
|---|---|---|---|
| Rack elevations | Available | U positions, colour-coded devices, free space, click to edit, drag-and-drop placement. | `/monitoring/racks/` |
| Rack power figures | Limited | Utilisation uses an allocated-power value that is not on the rack form and is not summed from devices. | Rack detail |
| Network closet board layout | Available | | Rack detail |
| Patch panels | Available | | `/monitoring/patch-panels/` |
| IPAM: subnets, VLANs, IP assignments | Available | IP statuses: available, assigned, reserved, DHCP. Optional link to an asset. Utilisation counts entered IPs. | `/monitoring/ipam/`, `/monitoring/vlans/` |

---

## Locations and navigation

| Capability | Status | Notes | Where |
|---|---|---|---|
| Locations per organization | Available | Managed from the organization page. Types: office, warehouse, data centre, retail, branch, manufacturing, co-working, remote, other; the primary location is flagged. | `/accounts/organizations/<id>/`, `/locations/` |
| Geocoding | Available | Google, with OpenStreetMap as fallback. | Location detail |
| Floor plans | Limited | Floor plan generation uses AI and is gated by `psa_ai_enabled`; MagicPlan import is available. | Location detail, `/imports/` |
| Navigation links by email / SMS | Available | Google Maps, Apple Maps, Waze. | `/locations/<id>/send-navigation/` |
| SMS providers | Limited | Twilio, Plivo, Vonage and Telnyx work. AWS SNS and Sinch can be selected but are not implemented. Phone numbers are checked only by a form pattern. | `/core/settings/sms/` |

---

## Service vehicles

| Capability | Status | Notes | Where |
|---|---|---|---|
| Vehicles, maintenance, fuel and MPG, assignments | Available | | `/vehicles/` |
| Damage reports with vehicle diagrams | Available | | Vehicle detail |
| Insurance and registration expiry warnings | Limited | Shown on the fleet dashboard; no email or webhook. | `/vehicles/` |
| Vehicle and shop inventory, low stock, reorder links | Available | | `/vehicles/inventory/` |
| QR codes for inventory | Available | Scan-to-edit, PNG download, print sheet. | `/vehicles/inventory/qr-codes/` |
| Receipt scanning (OPTIONAL AI) | Limited | Extracts vendor, date, totals, category and odometer using the configured AI provider. Gated by `psa_ai_enabled` since v3.17.609: with AI off the "AI Extract" button is hidden and the endpoint refuses; mobile receipt uploads still save but skip extraction. Duplicate receipts are flagged during extraction, not blocked on save. | `/vehicles/receipts/quick/` |
| PWA shortcuts | Available | "Scan Receipt" and "Vehicles" on Android. | Home screen icon |
| Module switch | Limited | Turning the module off hides the menu; the pages still open by URL. | `/core/settings/features/` |

---

## Workflows (process templates)

| Capability | Status | Notes | Where |
|---|---|---|---|
| Process templates with stages | Available | Global (MSP staff) or per organization; categories, tags, published / archived. | `/processes/` |
| Run a workflow | Available | Every run is attached to a ticket: at ticket creation, from a ticket, or from the workflows page (which creates a ticket). | `/processes/`, `/psa/new/` |
| Checklist sign-off | Available | Inline on the ticket, with progress bar and sign-off history. | Ticket detail |
| Audit trail | Available | Per-stage events with user, IP and old/new values. | `/processes/execution/<id>/audit-log/` |
| Notes to third-party PSA tickets | Available | ITFlow, ConnectWise Manage, Syncro, HaloPSA and Autotask, plus the built-in service desk. PSA failures don't block completion. | Launch form |
| draw.io flowchart | Available | | Template detail |
| Linked documents, passwords, notes and assets per stage | Available | | Template edit |
| Editing a template that has runs | Limited | Deleting a stage while editing also deletes that stage's sign-off records on existing runs. | `/processes/<slug>/edit/` |
| Module switch | Limited | Hides the menu only. | `/core/settings/features/` |

---

## Network hardware integrations

| Capability | Status | Notes | Where |
|---|---|---|---|
| UniFi | Limited | Switches, access points and gateways (no cameras). The scheduled sync records every device as an access point and ignores per-site organization mapping; use the manual import for correct types. | `/integrations/` |
| Omada | Available | | `/integrations/` |
| Grandstream | Available | Access points. | `/integrations/` |
| Import with de-duplication | Available | Matches by MAC, then serial; preview before import. | Connection page |
| Scheduled sync | Available | Built-in scheduler task (every 30 minutes); enable auto-sync on each connection. | Settings → Scheduler |

---

## Service desk (native PSA)

The built-in service desk is off until an administrator turns on `psa_enabled`
(`/core/settings/features/`). It is separate from the third-party
[PSA integrations](#psa-integrations).

### Tickets

| Capability | Status | Notes | Where |
|---|---|---|---|
| Tickets, queues, statuses, priorities, types | Available | Customer users see only shared tickets. | `/psa/` |
| Public and internal comments, @mentions, watchers | Available | Internal comments are never shown to customer users. | Ticket detail |
| Attachments | Available | Internal flag; downloads go through the protected file view. | Ticket detail |
| Canned replies | Available | Ticket and user variables. | `/psa/canned/` |
| Merge, similar tickets | Available | | Ticket detail |
| Credential context | Available | Titles only, for roles with View passwords; the full list is on an audited page. | Ticket detail |
| Closeout rule | Available | Since v3.17.604 every route to a resolved or closed status checks the resolution summary, category, required checklist items and sign-off (and optionally that time was logged — PSA settings). A closeout checklist card adds, ticks and removes items. Hygiene hints (no assignee, no asset, no first response) remain advisory. | Ticket detail |
| My Work | Available | Since v3.17.604. Your open tickets in SLA order, running timers on every ticket with a stop button, tickets where the customer replied, "waiting on customer" and "waiting on us" queues, pending approvals, and today's and upcoming appointments. Every count matches the list its link opens; the ticket list has the same queue filters. First item in the PSA menu and a button on the dashboard. | `/psa/my-work/` |
| Reply composer | Available | Explicit Public reply / Internal note toggle, an amber internal composer, and a confirmation naming the recipient before a public reply is emailed. Drafts save as you type and are private to you. | Ticket detail |
| Collision warnings | Available | Shows who else is viewing or replying; a reply isn't posted over activity you haven't seen — your text is kept and the new activity highlighted. | Ticket detail |
| Keyboard shortcuts | Available | `a` assign to me, `r` reply, `n` internal note, `t` log time, `x` close, `?` help. | Ticket detail |
| KB draft from a resolution | Available | Creates an unpublished draft (owner: you) from the resolution and public replies, linked to the ticket, which then goes through KB review. | Ticket detail |

### SLAs, time and approvals

| Capability | Status | Notes | Where |
|---|---|---|---|
| SLA targets per priority, per-contract overrides | Available | Calendar time (no business-hours calendar). | Contract form |
| SLA pause | Available | Paused statuses push the due times out. | — |
| Time entries and timers, expenses | Available | Expense receipts downloadable by MSP staff only. | Ticket detail |
| Timesheets and approval queue | Available | | `/psa/timesheet/`, `/psa/timesheet-approvals/` |
| Approvals | Limited | The approvals inbox handles quote approval chains. Time, AI suggestions and changes have their own review flows. | `/psa/approvals/` |

### Catalog, projects, recurring work, KB

| Capability | Status | Notes | Where |
|---|---|---|---|
| Service catalog (templated tickets) | Available | Managed by MSP staff. Since v3.17.606 each item has per-customer availability (include/exclude lists), portal visibility (off by default for existing items), a form builder with conditional fields, an approval policy, expected turnaround, routing (queue, type, priority) and an optional process to start. `manage.py psa_seed_portal_requests` adds sample request types (not added automatically). | `/psa/catalog/` |
| Projects, tasks, milestones, timeline | Available | | `/psa/projects/` |
| Recurring tickets | Available | Run every 15 minutes by the built-in scheduler; catch-up capped at 50 per schedule. | `/psa/recurring/` |
| Knowledge base search and ticket links | Available | | `/psa/kb/` |
| Dispatch board | Limited | Seven-day grid with overdue and unassigned rows. Rows are MSP technicians (User Type Staff); a ticket still assigned to anyone else shows on a row marked "Not a technician". Drag-and-drop changes the assignee, not the date. | `/psa/dispatch/` |

### Email-to-ticket

| Capability | Status | Notes | Where |
|---|---|---|---|
| IMAP and Microsoft 365 mailboxes | Available | Polled every 5 minutes by the built-in scheduler. Passwords stored encrypted. | `/psa/email-configs/` |
| Reply threading | Available | Replies are added as public comments (matched by message headers, then ticket number). Since v3.17.604 a customer reply records the reply time and moves the ticket out of "Waiting on Client"; portal replies do the same. | — |

### Workflow rules

| Capability | Status | Notes | Where |
|---|---|---|---|
| Triggers | Available | Ticket created / updated, status changed, comment added, SLA threshold crossed. | `/psa/rules/` |
| MSP-wide or per-client rules | Available | | Rule form |
| Visual rule builder | Limited | Six actions in the builder (priority, queue, assign, watcher, internal note, tag). Round-robin / skill / load-balanced assignment, charges and rule chaining are available only in raw JSON. | `/psa/rules/new/` |
| Rule chaining safety | Limited | No guard against one rule re-triggering another in a loop; avoid circular `fire_rule` chains. | — |
| Per-rule last fired / count / error, sample rules | Available | | `/psa/rules/templates/` |

### Contracts, quotes and invoices

| Capability | Status | Notes | Where |
|---|---|---|---|
| Contracts | Available | Block hours, retainer, managed services, per-incident; hours used, rollover, renewal, SLA overrides. See [Billing behaviour](#billing-behaviour-for-administrators). | `/psa/contracts/` |
| Quotes | Available | Line items, tax, branded PDF, email, approval chains. | `/psa/quotes/` |
| Customer e-signature | Available | No-login signing link; accepting can open a ticket. | `/portal/quote/<token>/sign/` |
| Invoices | Available | Numbering, line items with origin tags, PDF, email, payments. | `/psa/invoices/` |
| Invoice from ticket | Available | Skips already-invoiced time and respects contract allowances. | Ticket detail |
| Invoice from client charges | Available | | `/psa/clients/<id>/account/` |
| Client account and aging | Available | Balance, open invoices, credits, unbilled time, 0–30 / 31–60 / 61–90 / 90+ buckets. | `/psa/clients/<id>/account/`, `/psa/aging/` |
| Recurring client charges | Limited | The recurrence (monthly / quarterly / yearly) is stored but no job creates the next charge. | Client account |
| Push to QuickBooks Online / Xero | Limited | Invoices push (blocked while approval is pending; no duplicate push unless forced). Payments are not pushed; inbound payment status is synced. | Invoice detail |
| Other accounting providers | Planned | FreshBooks, Wave, Zoho Books and Sage Business Cloud are reserved provider types without adapters. | — |
| Late fees | Available | Scheduled but off by default. | Settings → Scheduler |

### Customer portal

| Capability | Status | Notes | Where |
|---|---|---|---|
| Portal tickets, replies, new tickets | Available | Only tickets shared with the client; portal-created tickets are shared automatically. Portal users who belong to more than one customer can switch between them. Customers with the service desk turned off don't get portal ticket and request pages. | `/portal/` |
| Request a service | Available | Since v3.17.606. Customers browse the service catalog by category and fill in a guided form whose questions appear only when relevant (validated on the server; unknown fields rejected). Before submitting they see knowledge-base articles that might answer the question — only published articles they may see. Submitting creates a shared ticket with the answers shown to customer and staff, routed by the item; it can start a process and ask the customer's admin to approve. | Portal → Request a service (`/portal/requests/`) |
| Plain-language progress | Available | Portal tickets show Received, In progress, Waiting for you, Waiting for approval or Resolved, plus anything waiting on the customer and the expected turnaround. Phrases can be overridden in the admin. | Portal ticket |
| Customer approvals | Available | Pending approvals routed to the customer (including service requests that need approval) are accepted or rejected in the portal. Requires the portal customer-approvals setting. | `/portal/approvals/` |
| Portal opt-in per client | Available | Requires the service desk on and the client's portal enabled (set automatically when you invite someone). | Client PSA settings |
| Invites | Available | | `/psa/clients/<id>/account/` |
| Knowledge base | Available | Client-visible articles. | `/portal/kb/` |
| Attachments | Limited | Internal attachments can't be downloaded; attachments on internal comments may still be listed by name. | Portal ticket |
| Credentials | Available | See [Password vault](#password-vault). | `/portal/vault/` |
| Branding | Available | The client's logo. | `/portal/` |

### Distributors

| Capability | Status | Notes | Where |
|---|---|---|---|
| Ingram Micro Xvantage, Pax8, TD Synnex | Limited | Catalog, price and availability lookups, webhooks, connection test. Order placement exists in the adapters but nothing in the UI calls it. | `/integrations/distributors/` |
| D&H, ScanSource, QBS, Westcoast | Planned | Reserved provider types. | — |

---

## Billing behaviour for administrators

How billing works from v3.17.601 on.

**Recurring invoices** are generated daily by the built-in scheduler and bill **only the
current period**. A contract more than one billing period behind is skipped and listed as an
error on the task in Settings → Scheduler, rather than back-billed. To catch it up, move its
next billing date, or run `python manage.py psa_generate_recurring_invoices` by hand (which
still back-bills). Contracts marked *cancel at period end* are not billed past their paid
period and are cancelled on their next billing date.

**Renewals** (daily) carry the billing schedule, recurring amount, meters (with their
unbilled usage) and bundle items over to the new contract, and continue the billing cadence
without re-billing a period. Contracts marked cancel-at-period-end are not renewed.

**Hours used** on a contract is computed from billable, finished time entries that started
inside the contract's dates, on any of the client's tickets. It respects the contract's
billable and excluded role lists; entries without a role code still count. It is recomputed
when a time entry is saved or deleted. The v3.17.601 update recalculated every contract
once, which lowers hours used where non-billable or double-counted time was included, and
so changes overage flags, the agreement reconciliation report and future rollover.
`python manage.py psa_recompute_contract_hours [--contract N] [--dry-run]` recalculates on
demand.

**Invoices from a ticket** skip time and expenses already on a live invoice (voiding an
invoice frees them) and create nothing if there is nothing new. Under a contract:

| Contract | Ticket time | Expenses |
|---|---|---|
| Hours allowance (any type) | Covered time as a zero-price line; time beyond the allowance billed at the overage rate (or the hourly rate if none) | Billed |
| Managed services or monthly retainer, no allowance | Fully covered | Billed |
| Block of hours without an allowance, or per-incident | Billed hourly | Billed |
| No contract | Billed at a zero rate — set prices on the lines | Billed |

**The approval gate.** An invoice that needs approval cannot be marked sent or paid from
the edit form, emailed, pushed to accounting, or auto-pushed by the recurring job until it
is approved. An approved invoice whose total changes goes back for approval. Sent, paid and
void invoices are locked except for status and notes, and those changes are audited with
before and after values. Recording a payment does not check the gate.

**Editing an invoice** keeps each line's origin (time entry, contract, quote) instead of
rebuilding the lines as manual ones.

---

## Scheduled jobs

Since v3.17.599 every periodic job runs from the **built-in scheduler**, managed at
**Settings → Scheduler** (`/core/settings/scheduler/`). Each task shows its interval, last
run, last result and last error, and can be turned on or off. No crontab is needed.

| How it runs | Detail |
|---|---|
| Native install | `clientst0r-scheduler.timer` runs the scheduler every minute. Updates remove the crontab lines older releases added for these jobs, so nothing runs twice. |
| Docker | The `scheduler` service in `docker-compose.yml`. |
| New tasks | First run one interval after the update that adds them; daily jobs start about a day later. Turn any of them off before then if needed. |

| Interval | Tasks (default) |
|---|---|
| Every 5 minutes | Website checks, email-to-ticket polling, outbound email retry, SLA workflow tick, security alert polling |
| Every 15 minutes | Recurring tickets, scheduled reports, incident SLA checks |
| Every 30 minutes | Network controller asset sync |
| Hourly | Idle-approval escalation, distributor checks, exposure scores, scheduling alerts, network config backup; PSA, RMM and accounting sync (off by default) |
| Daily | Recurring invoices, contract renewals and lifecycle, recurring purchases, subscription lifecycle, workflow suggestions, replenishment suggestions, password breach scan, credential / SSL / domain / warranty expiry, firmware and asset-age checks, dependency scan, compliance recertification reminders, GeoIP database refresh, data pruning. Off by default: late fees, full security scan, system warnings digest |
| Weekly | Knowledge base review reminders, asset baselines |

The older per-job timers (`clientst0r-monitor`, `-psa-sync`, `-rmm-sync`, `-breach-scan`,
`-accounting-sync`) are still shipped in `deploy/`.

---

## PSA integrations

Connect a third-party PSA to mirror its data. Separate from the built-in service desk.

| Provider | Status | Synced |
|---|---|---|
| ConnectWise Manage | Available | Companies, contacts, tickets |
| Autotask PSA | Available | Companies, contacts, tickets |
| HaloPSA | Available | Companies, contacts, tickets (OAuth2) |
| Kaseya BMS | Available | Companies, contacts, tickets |
| Syncro | Available | Customers, contacts, tickets |
| Freshservice | Available | Departments, requesters, tickets |
| Zendesk | Available | Organizations, users, tickets |
| ITFlow | Available | Companies, contacts, tickets |
| RangerMSP | Limited | Companies, contacts, tickets — provider newly added; not yet covered by end-to-end sync tests |
| Alga PSA | Limited | Companies, contacts, tickets — provider newly added; not yet covered by end-to-end sync tests |

| Capability | Status | Notes | Where |
|---|---|---|---|
| Scheduled and manual sync, connection test | Available | Scheduler task `psa_sync` (off by default) or the `clientst0r-psa-sync` timer; per-connection interval. | `/integrations/` |
| Organization auto-import | Available | Creates organizations from PSA companies, de-duplicated by external ID, with optional name prefix. | `/integrations/<id>/map-organizations/` |
| Projects and agreements sync | Planned | | — |
| Field mapping / conflict resolution | Planned | | — |
| Sync history | Limited | Last error on the connection plus audit log entries. | `/integrations/`, `/audit/` |

---

## RMM integrations

| Provider | Status | Synced |
|---|---|---|
| Tactical RMM | Available | Devices, alerts, software, sites; device coordinates for the map |
| NinjaOne | Available | Devices, alerts, software |
| Datto RMM | Available | Devices, alerts, software |
| Atera | Available | Devices, alerts, software |
| ConnectWise Automate | Available | Devices, alerts, software |

| Capability | Status | Notes | Where |
|---|---|---|---|
| Scheduled device sync | Available | Scheduler task `rmm_sync` (off by default) or the `clientst0r-rmm-sync` timer. Polling, not live updates. | `/integrations/rmm/devices/` |
| Asset matching | Available | By serial number and hostname. | — |
| Alerts, software inventory, online status | Available | | `/integrations/rmm/alerts/` |
| Device map | Limited | Only Tactical RMM supplies coordinates. | Dashboard |
| Organization auto-import | Available | | `/integrations/rmm/<id>/map-organizations/` |

---

## Notifications

| Capability | Status | Notes | Where |
|---|---|---|---|
| Email (SMTP) | Available | Expiry warnings (SSL, domains, credentials, warranties), ticket notifications, scan alerts, reminders. | `/core/settings/smtp/` |
| Webhooks | Available | Setup, test and delivery log. Since v3.17.609 every event offered in the form fires, from the data layer so API, mobile and sync changes count too: assets, documents, passwords (metadata only — never the secret), password reveals, locations, organization changes, workflows, monitors (`monitor.up` / `monitor.down`) and integration syncs, plus sign-in events for customer users. MSP staff activity is never sent to a customer's webhooks. Secrets and custom header values are stored encrypted and shown as `********`. | `/core/webhooks/` |
| Website downtime alerts | Available | Email on down (after two failed checks) and on recovery; see [Monitoring](#monitoring). | Monitor form |
| In-app notifications | Limited | System warnings only. | — |

---

## Reporting and financial analytics

Financial reports require the **View financial reports** role permission. They currently
cover every organization on the install, so grant it to MSP staff only.

| Capability | Status | Notes | Where |
|---|---|---|---|
| Profitability by client, technician, contract, project | Available | Cost from technician cost rates (default $60/h when none is set). CSV export. | `/reports/psa/` |
| Effective hourly rate and realization | Available | | `/reports/psa/effective-hourly-rate/` |
| Revenue leakage | Limited | Stale unbilled time, unused contract blocks, old draft invoices. Falls back to $150/h when there is no contract rate. | `/reports/psa/revenue-leakage/` |
| SLA trends, margin by service line | Available | | `/reports/psa/sla-trends/`, `/reports/psa/margin-analytics/` |
| Contract profitability snapshot | Limited | Uses a placeholder cost of 60% of the hourly rate instead of technician cost rates. | Contract detail |
| Client health, executive scorecard, MRR forecast, AR aging, reconciliation reports | Available | | `/reports/` |
| Custom dashboards and wallboards | Available | Starter widgets; a seeded "MSP Overview" dashboard. | `/reports/dashboards/`, `/reports/wallboards/` |
| Scheduled reports | Available | Run every 15 minutes by the scheduler. | `/reports/scheduled/` |
| Audit reports | Available | | `/audit/` |
| Reports module switch | Limited | Install-wide, not per organization. | `/core/settings/features/` |

---

## Resource management

| Capability | Status | Notes | Where |
|---|---|---|---|
| Skills, certifications, working hours | Available | | `/resourcing/me/` |
| Team roster | Available | MSP staff. | `/resourcing/roster/` |
| Leave requests and holidays | Available | | `/resourcing/leave/`, `/resourcing/holidays/` |
| Billable targets and cost rates | Available | | `/resourcing/billable-target/`, `/resourcing/cost-rates/` |
| Capacity report and dispatch suggestions | Available | | `/resourcing/capacity/`, dispatch board |

---

## AI features (OPTIONAL AI)

All AI features are optional. Nothing calls an AI provider until one is configured
(`/core/settings/ai/`).

| Capability | Status | Notes | Where |
|---|---|---|---|
| Master switch `psa_ai_enabled` | Available | Off by default. Gates the service desk AI, documentation AI, floor plan generation and receipt extraction. | Settings → PSA (AI) |
| Documentation generate / enhance / validate | Available | Uses the configured provider: Anthropic, OpenAI, Moonshot, MiniMax, or a local Ollama model. | `/docs/ai/assistant/` |
| Ticket reply drafts and suggested actions | Limited | Human approval before anything is sent or applied; guardrails (rate limits, token quotas, input sanitising, action allowlist); vault secrets never sent. Uses Anthropic only. | `/psa/ai/inbox/` |
| Ticket triage suggestions | Limited | Advisory only. Anthropic only. | Ticket detail |
| AI role permissions | Available | 12 switches (view, request triage, send, approve, apply by risk tier, scripts, workflows, billing, admin). | `/accounts/roles/` |
| Receipt scanning | Limited | See [Service vehicles](#service-vehicles); gated by `psa_ai_enabled` since v3.17.609. | `/vehicles/receipts/quick/` |
| Redaction of personal data before sending | Planned | The redaction code exists but is not called. | — |
| Reviewable AI edits to imported documents | Planned | The AI review of an imported document overwrites its body without a diff. | — |

---

## Compliance frameworks

| Capability | Status | Notes | Where |
|---|---|---|---|
| PCI-DSS v4.0 and HIPAA Security Rule catalogs | Available | Seeded control lists (`seed_pci_dss`, `seed_hipaa`). No other frameworks are seeded. | — |
| Per-organization enrollment and attestation | Available | Status, notes, evidence link and reviewer per control. Owners, admins and MSP staff only. | `/compliance/organizations/<id>/` |
| Customer-facing PDF report | Available | | `…/report.pdf` |
| Recertification reminders | Available | Daily scheduler task with 7-day de-duplication; per-enrollment interval and recipient. | Enrollment settings |
| Evidence pack ZIP | Limited | Includes 2FA status, user access, password history, assets, SLA, SSL/domain, uptime and vulnerability summaries and a manifest. It does not include the attestation answers or evidence links; the backups section is empty. | `/compliance/organizations/<id>/evidence-pack/` |

---

## Administration

| Capability | Status | Notes | Where |
|---|---|---|---|
| General, security, SMTP, SMS, directory, AI settings | Available | Since v3.17.610 saved Security settings (session, 2FA, lockout, password policy) take effect; an environment variable, if set, wins and the field shows "set by environment". Settings → Directory configures Azure AD SSO and LDAP, with a **Test connection** button for LDAP. See [Authentication](#authentication-and-sessions). | `/core/settings/`, `/core/settings/security/`, `/core/settings/directory/` |
| Feature toggles | Limited | Install-wide (not per organization): service desk, AI, vehicles, workflows, monitoring, reports and others. Several only hide the menu. | `/core/settings/features/` |
| Scheduler | Available | See [Scheduled jobs](#scheduled-jobs). | `/core/settings/scheduler/` |
| System updates | Available | Check and apply from the web UI; graceful reload. See [AUTO_UPDATE.md](AUTO_UPDATE.md). | `/core/settings/updates/` |
| Database maintenance | Limited | Clear sessions, prune audit logs, optimize and analyze tables. Backup and restore are command-line only. | `/core/settings/maintenance/` |
| System status | Available | | `/core/settings/system-status/` |
| Maintenance mode | Planned | | — |

---

## API

| Capability | Status | Notes | Where |
|---|---|---|---|
| REST API | Limited | Assets, contacts, documents, passwords and tags (full CRUD); organizations read-only. Pagination, filtering, ordering, throttling. Role view permissions apply. | `/api/`, [user-guide/api.md](user-guide/api.md) |
| API keys | Available | `Authorization: Bearer itdocs_live_…`; stored hashed; stop working when the user is deactivated or (for customer users) leaves the key's organization. No expiry date. | `/api/keys/` |
| GraphQL | Available | Optional dependency (`requirements-graphql.txt`). | `/api/v2/graphql/`, [API_V2_GRAPHQL.md](API_V2_GRAPHQL.md) |
| Field selection, bulk operations, OpenAPI explorer | Planned | | — |
| Mobile API | Available | Token-authenticated; tenant-scoped; customer users get the customer rules. | `/api/mobile/v1/` |

---

## Browser extension

| Capability | Status | Notes | Where |
|---|---|---|---|
| Extension | Separate component | In this repository under [`clientst0r-extension/`](clientst0r-extension/README.md): Manifest V3, Chrome/Edge 88+, Firefox 109+. Unsigned; loads only in developer mode. Not published to browser stores. | `/core/download-browser-extension/` |
| Password search, copy, TOTP, autofill suggestions | Limited | Uses a REST API key and the regular `/api/` endpoints. Credentials are matched by host substring. | Extension popup |
| Dedicated extension API (`/vault/api/extension/`) | Available | Server side only; the extension does not use it yet, and there is no token button in the UI. | [docs/browser-extension-api.md](docs/browser-extension-api.md) |
| Lock / master password, offline vault | Planned | | — |

---

## Mobile

| Capability | Status | Notes | Where |
|---|---|---|---|
| Installable web app (PWA) | Available | Install page with QR code, shareable without login; shortcuts on Android. | `/core/install/` |
| Mobile-friendly pages | Available | Responsive layout; camera capture for receipts; one-handed inventory scan pages. | — |
| Mobile sign-in sessions | Available | Each mobile sign-in gets its own token, stored only as a hash. Signing out ends just that device. Users can sign out all their mobile sessions from their profile, and superusers can do it for any user (audit-logged). Changing a password does not sign out mobile sessions on its own; deactivating a user does. | `/accounts/profile/` |
| Native mobile app (iOS / Android) | Separate component | Built with Expo / React Native. Its source and build tooling are maintained outside this repository. It uses the mobile API above. | — |

---

## Import, export and backup

| Capability | Status | Notes | Where |
|---|---|---|---|
| CSV / spreadsheet import with field mapper | Available | Assets, contacts, passwords, documents, inventory: preview and column auto-matching. CSV password and contact imports work since v3.17.603 (passwords are encrypted on import). Re-running a CSV import doesn't duplicate rows: rows are matched on a natural key (title + username + URL for passwords, serial number or asset tag for assets, email for contacts) — for imports made from v3.17.603 on. | `/imports/` |
| IT Glue import | Limited | Via the IT Glue API: organizations, configurations (as assets), passwords and documents. In an "all organizations" import each record goes to the customer its source record belongs to (fixed in v3.17.603). Contacts, locations, networks, flexible assets, attachments and relationships are not imported. | `/imports/create/` |
| Hudu import | Limited | Via the Hudu API: companies, assets, passwords and articles; each record goes to its source company's customer. Contacts, locations, networks, attachments and relationships are not imported. | `/imports/create/` |
| MagicPlan floor plans | Available | | `/imports/` |
| Import history, dry run, source tags | Available | Dry run is on by default and writes nothing. A job says "Completed" only when nothing failed; otherwise "Completed with errors" or "Failed", with imported / skipped / failed counts that add up to the source total. The import log shows on the import page. | `/imports/` |
| Import rollback | Available | One transaction. Keeps (and lists) any record edited after the import, removes organizations the import created only when nothing else uses them, covers every record type the importers create (including inventory, locations and floor plans), and reports "Partially rolled back" when something was kept. Failed imports that created records can be rolled back too. | `/imports/<id>/` |
| Bitwarden / Vaultwarden | Limited | See [Password vault](#password-vault). | `/core/settings/vault-import/` |
| Whole-install export | Available | JSON, or Hudu / IT Glue formats (passwords excluded). Superusers. | `/core/settings/data-export/` |
| Encrypted backup | Limited | `python manage.py backup` (database and media, encrypted with the master key, retention). Not scheduled; run it from cron or before updates. `make backup` is an unencrypted database dump. | [README](README.md#updating-and-backups) |
| Restore | Limited | `python manage.py restore <file>` on the command line; no web restore. | — |

---

## Deployment

| Capability | Status | Notes | Where |
|---|---|---|---|
| Native install | Available | `bash install.sh` on Ubuntu 20.04+ / Debian 11+: Python 3.12, MariaDB, Gunicorn, Nginx, systemd units. | [INSTALL.md](INSTALL.md) |
| Docker / Compose | Available | `docker compose up -d`: app, MariaDB, scheduler; optional Nginx (`--profile proxy`) and Redis (`--profile cache`). Image at `ghcr.io/agit8or1/clientst0r`. | [docs/docker.md](docs/docker.md) |
| Updates | Available | Web UI apply or `auto_update`; graceful Gunicorn reload. No automatic backup or rollback; installs the tip of `main`. | [AUTO_UPDATE.md](AUTO_UPDATE.md) |
| Health endpoint | Available | Anonymous. | `/health/` |
| Single server | Available | Vertical scaling on one host; clustered / multi-node deployment is out of scope. | — |
| Log rotation | Planned | Configure logrotate yourself for the application logs. | — |

---

## Architecture

| Layer | What it runs on |
|---|---|
| Framework | Django 6.0 |
| API | Django REST Framework 3.17, optional GraphQL |
| Database | MariaDB 10.11 (the Compose default); MySQL 8.0+ also supported, SQLite for local development |
| Application server | Gunicorn, behind Nginx |
| Authentication | `django-two-factor-auth` (TOTP), optional Azure AD / Entra ID SSO, optional LDAP / Active Directory (`django-auth-ldap`) |
| Encryption | Python `cryptography` — AES-256-GCM for secrets at rest |
| Password hashing | Argon2 |
| Frontend | Bootstrap 5 and vanilla JavaScript, no build step |
| Scheduling | Built-in scheduler (`run_scheduler`), driven by a systemd timer or the Docker `scheduler` service — no Redis or Celery |

### Design decisions

- **Two install paths, both first-class** — native systemd install via `install.sh`, or
  `docker compose up -d`. Neither is a wrapper around the other.
- **No broker, no worker fleet** — periodic work runs in the built-in scheduler. Redis is
  optional and only used if you point `CACHES` at it.
- **Single server by design** — one VM or one container host per MSP.
- **Self-hosted software** — you run it; there is no phone-home. Optional managed hosting
  and support are offered separately by [MSP Reboot](https://mspreboot.com). AI features
  call nothing until you configure a provider.
- **API-driven** — REST, GraphQL and the mobile API back the mobile app, the browser
  extension and third-party integrations.

---

**All features developed with assistance from Luna the GSD 🐕**
