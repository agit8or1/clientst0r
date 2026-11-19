# Evaluating ClientSt0r

This page is for teams deciding whether ClientSt0r fits next to, or instead of, the tools they
already run. It is organized by **tool category**: for each, what ClientSt0r covers natively, what
it covers through integrations, what is planned, and where a dedicated tool is the better fit.

Status labels follow [FEATURES.md](FEATURES.md): **Available**, **Limited** (works with a stated
limitation, or not yet verified against the real external service), **Planned**, and **Separate
component**. Planned work is tracked in the [roadmap](docs/ROADMAP.md).

---

## The basics

| | ClientSt0r |
|---|---|
| License | MIT; no license fee, seat or client limits, or paid tiers |
| Deployment | Self-hosted: `docker compose up -d`, or `bash install.sh` on Ubuntu / Debian |
| Database | MariaDB (MySQL also supported) on your infrastructure; SQLite for local development |
| Topology | Single server per MSP; no clustered deployment |
| Tenancy | Every record belongs to a customer organization; customer users see only their own |
| Updates | Settings → System → System Updates: signed-tag check, preflight and a verified backup before Apply. Rollback is a manual restore command |
| Exports | Documents to Markdown, HTML, DOCX, PDF; audit logs to CSV/JSON; financial reports to CSV; whole-install JSON export |
| What you pay for | Your server and your time. Optional hosting and support are offered separately by [MSP Reboot](https://mspreboot.com) |

---

## IT documentation tools

**Native**

| Capability | Status | Notes |
|---|---|---|
| Per-customer documents, templates, global knowledge base shared with chosen customers or groups | Available | WYSIWYG or Markdown; no file attachments, favorites or share links on documents |
| Versions, compare and restore; owners, review dates, drafts, approval | Available | |
| Documentation readiness scores and repair queue | Available | |
| Assets with custom types and fields on the form and API | Available | No bulk edit or per-asset change history |
| Hardware catalog, panel artwork, ports, cables, racks, labels, diagrams | Available | Documentation only; nothing is read from or pushed to devices |
| IPAM, VLANs, network config backups over SSH | Available | |
| Search | Limited | Substring match plus the Ctrl+K Go to palette; no ranking |
| Office document editing (ONLYOFFICE, Collabora, Microsoft 365) | Limited | Not yet verified against real editor services |

**Through integrations and importers:** IT Glue and Hudu importers (organizations, assets,
passwords, documents; contacts, locations, networks, attachments and relationships not yet),
CSV/xlsx import, MagicPlan floor plans, UniFi, Omada and Grandstream controller sync.

**Planned:** service dependency and impact mapping (Phase 88).

**When a dedicated tool fits better:** if you need ranked full-text search, document attachments
and share links, or a hosted service with no server to run.

### Importer behavior

Dry run is on by default. Each job keeps a log and tags imported records with their source; records
land in the customer their source record belongs to. A job is "Completed" only when nothing failed.
Rollback runs in one transaction, keeps records edited after the import, and reports "Partially
rolled back" when anything was kept. Re-running a CSV import matches existing rows instead of
duplicating them. Guides: [IT Glue](docs/importing-from-it-glue.md), [Hudu](docs/importing-from-hudu.md).

---

## PSA and ticketing

**Native** (opt-in, `psa_enabled`)

| Capability | Status | Notes |
|---|---|---|
| Tickets, queues, SLAs with pause, time entries, expenses, My Work | Available | SLAs run on calendar time |
| Email-to-ticket (IMAP, Microsoft 365) | Available | |
| Service catalog with guided portal requests and approvals | Available | |
| Problems, changes with CAB, workflow rules, rule-based routing (not AI) | Available | No loop guard between chained workflow rules |
| Projects, dispatch board, scheduling, resourcing | Available | Dispatch drag changes the assignee, not the date |
| Customer portal | Available | Customers see only tickets you share with them |

**Through integrations:** sync of companies, contacts and tickets from ConnectWise Manage,
Autotask, HaloPSA, Kaseya BMS, Syncro, Freshservice, Zendesk and ITFlow (Available), and RangerMSP
and Alga PSA (Limited, newly added). Projects, agreements and field mapping are not synced.
Process runs can post notes to ITFlow, ConnectWise Manage, Syncro, HaloPSA and Autotask tickets.

**Planned:** quote → contract and quote → invoice conversion (Phase 70), alert routing, on-call and
escalation (Phase 87).

**When a dedicated tool fits better:** if you need per-customer business-hours calendars, deep
two-way PSA field mapping, or a service desk spread across several servers.

---

## RMM

ClientSt0r is **not an RMM**. It stores and shows RMM data and works with a paired RMM from tickets.

| Capability | Status | Notes |
|---|---|---|
| Device, alert and software sync | Available | Atera, ConnectWise Automate, Datto RMM, NinjaOne, Tactical RMM, Rem0te; polling |
| Device Workspace, ticket RMM panel, alert-to-ticket policy | Available | |
| Rem0te pairing (signed contract, Ed25519) and Rem0te alerts as tickets with link back | Available | Tested with both real applications in CI. Rem0te is a separate application |
| Diagnostics, remediation proposals and results from a ticket | Limited | In development; contract routes agreed but not yet built on the Rem0te side |
| Running anything on a device | Not in ClientSt0r | Endpoint actions are approved and run in the RMM, never in ClientSt0r or by AI |

**Planned:** Rem0te endpoint actions in security automation (Phase 86).

**When a dedicated tool fits better:** always for endpoint management itself: patching, scripting,
remote control and monitoring agents belong in the RMM.

---

## Password managers

| Capability | Status | Notes |
|---|---|---|
| Per-customer encrypted vault (AES-256-GCM), 15 entry types, folders, TOTP codes | Available | |
| Audited reveals, access rules, reveal approval, break-glass, expiry warnings | Available | |
| Vault visibility for technicians per customer | Available | |
| Breach checks (Have I Been Pwned, k-anonymity) | Available | Blocking breached passwords only by environment variable |
| Customer portal visibility per entry | Available | |
| Personal vault | Limited | Encrypted with the server master key, not a per-user key |
| Browser extension | Separate component | Unsigned, developer mode only |

**Through importers:** Bitwarden / Vaultwarden JSON.

**When a dedicated tool fits better:** for end-to-end (zero-knowledge) encryption, a signed browser
extension with offline access, or password management for your customers' own staff.

---

## Monitoring and SIEM

| Capability | Status | Notes |
|---|---|---|
| Website, SSL and WAN monitors, status pages | Available | Checks at most every 5 minutes; no WHOIS |
| Backup monitoring | Available | Proxmox Backup Server (polled); restic, Borg, Kopia (push reports) |
| Security alerts by generic JSON webhook | Limited | Vendor names in the list are labels; no vendor API polling works yet |
| SIEM webhook endpoints (CEF, JSON, Syslog format over HTTPS) | Available | No network syslog listener |
| Incidents, playbooks, auto-ticket rules, Security Overview | Available | |
| Events: one list of security, RMM, Rem0te, backup and monitor alerts | Available | First release; Phase 82 in progress |
| Wallboards | Available | Configurable boards; NOC/SOC presentation mode planned |

**Planned:** NOC/SOC wallboards and display pairing (Phase 83), a connector framework with vendor
connectors in batches (Phase 84), Operations Center and correlation (Phase 85), SOAR Lite
(Phase 86), posture scorecards (Phase 89).

**When a dedicated tool fits better:** for log collection, retention and search, network
monitoring by SNMP, or detection engineering. ClientSt0r receives and organizes alerts; it does not
collect logs.

---

## Standalone billing

| Capability | Status | Notes |
|---|---|---|
| Contracts, recurring invoices, aging, late fees, approval gate | Available | |
| Quotes with e-signature; contract documents with signing | Available / Limited | Contract starter templates are sample wording |
| Price book, service plans, labor rate cards | Limited | Managed in the Django admin |
| Profitability, Business Overview, pricing advisor, licensing | Available | |
| Payments (Stripe, GoCardless) and sales tax (Avalara, TaxJar) | Limited | In the code; not yet verified against live or sandbox services |

**Through integrations:** QuickBooks Online and Xero (customer sync, invoice push, payment status
pull); Microsoft 365 and Pax8 license sync; Ingram Micro Xvantage, Pax8 and TD Synnex catalog and
pricing lookups.

**Planned:** payment posting, credit memos and refunds to accounting (Phase 71), quote and contract
conversion (Phase 70), customer command center portal (Phase 77).

**When a dedicated tool fits better:** for your general ledger and accounting, and for payment or
tax processing you need verified today.

---

## Identity and AI

| Capability | Status | Notes |
|---|---|---|
| TOTP 2FA required by default, LDAP / Active Directory | Available | |
| Azure AD / Entra ID SSO | Limited | Counts as 2FA only when Microsoft confirms MFA |
| OIDC sign-in | Limited | Off by default; not yet verified against a live provider |
| SAML, passkeys | Planned | |
| View passwords, documents, assets, files, monitors, integrations permissions | Available | Enforced per customer |
| AI (OPTIONAL AI, off by default) | Available | Ticket AI: Anthropic, OpenAI, Ollama; documentation AI adds Moonshot and MiniMax. Redaction runs on all evidence. Ticket Analyze/Compare need a paired RMM |

---

## Getting started

```bash
git clone https://github.com/agit8or1/clientst0r.git
cd clientst0r
cp .env.example .env
# set SECRET_KEY, APP_MASTER_KEY, API_KEY_SECRET, DB_PASSWORD, DB_ROOT_PASSWORD
docker compose up -d
```

Or on Ubuntu / Debian: `bash install.sh` (creates `admin` / `ChangeMe123!`; change it at first
login). Full guides: [README](README.md#quick-start), [INSTALL.md](INSTALL.md),
[docs/docker.md](docs/docker.md).

## Learn more

- [Full feature list](FEATURES.md)
- [Screenshots](docs/screenshots.md)
- [Roadmap](docs/ROADMAP.md)
- [API documentation](API_V2_GRAPHQL.md)
- [Security policy](SECURITY.md)
- [Changelog](CHANGELOG.md)
