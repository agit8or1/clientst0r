# Evaluating ClientSt0r

> **Self-hosted, MIT-licensed IT documentation and service desk for MSPs — no licence fees, no seat limits, your own database.**

[![License: MIT](https://img.shields.io/github/license/agit8or1/clientst0r?color=blue)](LICENSE) [![Latest release](https://img.shields.io/github/v/release/agit8or1/clientst0r?label=release)](https://github.com/agit8or1/clientst0r/releases)

This page is for teams deciding whether ClientSt0r fits, including teams moving from IT
Glue or Hudu. It describes what ClientSt0r does and how far its importers go. It does not
compare other products' current features or prices; check those vendors' own
documentation for that.

Capability labels follow [FEATURES.md](FEATURES.md): **Available**, **Limited** (works,
with a stated limitation), **Planned**, and **Separate component**.

---

## Cost and licensing

| | ClientSt0r |
|---|---|
| Licence | MIT — use it, fork it, modify it |
| Licence fee | None |
| Seat or client limits | None |
| Paid tiers / feature gating | None — every first-party feature works on a self-hosted install |
| What you pay for | Your own server, and your own time to run it |
| Optional services | Managed hosting and commercial support are offered separately by [MSP Reboot](https://mspreboot.com); they buy time and infrastructure, not features |

---

## Hosting and data control

| | ClientSt0r |
|---|---|
| Deployment | Self-hosted: `docker compose up -d`, or `bash install.sh` on Ubuntu / Debian |
| Database | MariaDB (MySQL 8 also supported) on your infrastructure |
| Topology | Single server by design; no clustered or multi-node deployment |
| Source code | Public and modifiable |
| Updates | From the web UI (Settings → Updates) with a graceful reload, or by `git pull` / `docker compose pull`. Take a backup first; there is no automatic rollback |
| Multi-tenant | Every record belongs to a client organization; customer users see only their own organizations |
| Exports | Documents to Markdown, HTML, DOCX and PDF; audit logs to CSV/JSON; financial reports to CSV; a whole-install JSON export for superusers |

---

## What's included

A summary. See [FEATURES.md](FEATURES.md) for the full list with limitations and where to
find each screen.

### Documentation and knowledge base

| Capability | Status | Notes |
|---|---|---|
| Per-client documents and a global knowledge base | Available | Global KB articles are visible to MSP staff; customer users see only client-visible articles |
| WYSIWYG or Markdown editor, templates, uploaded-file documents | Available | File attachments on documents and document favorites are not available yet |
| Version history | Available | View any version, compare two, restore one (audited) |
| Document lifecycle | Available | Owners and review intervals, drafts that stay out of lists and search until published, publish permissions and Submit for review → Approve, an Archived list, and template drift reports |
| Documentation readiness | Available | Standards for what each client must have documented; a per-client score with an explanation of every gap, a repair queue and audited exceptions |
| KB analytics | Available | Most viewed, never viewed, past review date, and searches that found nothing |
| Search | Limited | Substring matching across titles and bodies; no ranking or saved searches |
| Diagrams (draw.io) | Available | |

### Assets, network and infrastructure

| Capability | Status | Notes |
|---|---|---|
| Asset tracking, tags, photos, relationships | Available | |
| Custom asset types and per-type custom fields | Limited | Assets use a fixed list of types; custom fields are filled by imports and the API but are not editable on the asset form yet |
| Warranty and lifecycle dates | Available | |
| Rack elevations | Available | Drag-and-drop placement |
| IPAM: subnets, VLANs, IP assignments | Available | |
| CSV / spreadsheet import | Available | Assets, contacts, passwords, documents; re-running an import matches existing rows instead of duplicating them |

### Credentials and security

| Capability | Status | Notes |
|---|---|---|
| Encrypted vault | Available | AES-256-GCM with per-purpose keys derived by HKDF-SHA256; every reveal is audited |
| Per-entry access rules, reveal approval, break-glass | Available | |
| TOTP 2FA | Available | Enforced for every account by default |
| SSO and directory sign-in | Limited | Azure AD / Entra ID SSO, and LDAP / Active Directory sign-in (optional packages). SAML and generic OIDC are not available |
| Secrets at rest | Available | Every stored secret encrypted or hashed; `rotate_encryption_key` for master-key rotation and `check_secrets_storage` to audit |
| Role-based access | Limited | View passwords / documents / assets are enforced; View files / monitors / integrations are not yet |
| Audit log | Limited | Credential reveals, API key use and many explicit events are logged; other changes are recorded by request (method, path, form fields), without before/after values. See [FEATURES.md](FEATURES.md) |
| Breach checking (Have I Been Pwned, k-anonymity) | Available | |
| Dependency and OS package scanning | Available | Dependency scanning uses Snyk and needs a Snyk token |
| IP and country (GeoIP) access rules | Available | Enforced by the application, not by the host firewall; plus fail2ban management on native installs |

### Service desk (opt-in, `psa_enabled`)

| Capability | Status | Notes |
|---|---|---|
| Tickets, queues, SLAs with pause logic, time entries | Available | |
| Technician workspace (My Work) | Available | Your tickets in SLA order, running timers, customer replies, waiting queues, approvals and appointments; reply drafts, collision warnings, an explicit public/internal composer and keyboard shortcuts |
| Contracts, quotes with e-signature, invoices, payments | Available | Recurring invoices run from the built-in scheduler |
| Push invoices to QuickBooks Online or Xero | Limited | Invoices push; payments are not pushed |
| Customer portal | Available | Customers see only tickets you share with them, with progress in plain language |
| Guided service requests | Available | "Request a service" in the portal: catalog forms with conditional questions, KB suggestions before submitting, routing and optional customer-admin approval |
| Workflow rules, dispatch board, projects | Available | |

### API, integrations and automation

| Capability | Status | Notes |
|---|---|---|
| REST API | Limited | Assets, contacts, documents, passwords, tags; organizations read-only |
| GraphQL API | Available | Optional dependency |
| PSA integrations | Available | ConnectWise Manage, Autotask, HaloPSA, Kaseya BMS, Syncro, Freshservice, Zendesk, ITFlow — companies, contacts and tickets. RangerMSP and Alga PSA: Limited (newly added) |
| RMM integrations | Available | Tactical RMM, NinjaOne, Datto RMM, Atera, ConnectWise Automate — devices, alerts, software |
| Built-in scheduler for periodic jobs | Available | Settings → Scheduler shows each job's last run and error; no crontab needed |
| Webhooks | Available | Assets, documents, passwords (metadata only), password reveals, locations, organizations, workflows, monitors and integration syncs |
| Website monitoring alerts | Available | Email when a site goes down (after two failed checks) and when it recovers |

### AI (OPTIONAL AI)

| Capability | Status | Notes |
|---|---|---|
| Documentation generation and enhancement | Available | Gated by `psa_ai_enabled`. Uses the configured provider: Anthropic, OpenAI, Moonshot, MiniMax, or a local Ollama model |
| Ticket reply drafts, triage and suggested actions | Available | Gated by `psa_ai_enabled`. Uses Anthropic only |
| Redaction of personal data before sending to a provider | Planned | The redaction code exists but is not wired in |

---

## Migrating from IT Glue or Hudu

ClientSt0r has built-in importers for both, under **Imports** (`/imports/`). They connect to
the source system's API with your API key.

| Data | IT Glue | Hudu |
|---|---|---|
| Organizations | Matched or created | Matched or created |
| Assets / configurations | Imported | Imported |
| Passwords | Imported (encrypted on arrival) | Imported (encrypted on arrival) |
| Documents | Imported | Imported |
| Contacts | Not yet | Not yet |
| Locations | Not yet | Not yet |
| Networks | Not yet | Not yet |
| Attachments, relationships, permissions | Not yet | Not yet |

How the importer behaves today:

- **Dry run is on by default.** It reports counts without writing anything.
- **Import history** is kept per job, with a log, and imported records are tagged with
  their source.
- **Records land in the right client.** In an all-organizations import each record goes to
  the client its source record belongs to.
- **Honest outcomes.** A job is "Completed" only when nothing failed; otherwise "Completed
  with errors" or "Failed", with imported / skipped / failed counts that add up to the
  source total. The import log is on the import page.
- **Rollback** runs in one transaction. Records edited after the import are kept and listed,
  organizations the import created are removed only when nothing else uses them, and a
  rollback that kept anything reports "Partially rolled back". Failed imports that created
  records can be rolled back too.
- **CSV imports** (assets, contacts, passwords, documents) don't duplicate rows when re-run:
  rows are matched on a natural key such as title + username + URL for passwords.

Plan a check after any import: compare record counts with the source, open a sample of
passwords and documents, and recreate contacts and locations by hand or by CSV until those
importers ship. Bitwarden / Vaultwarden JSON exports can also be imported into the vault.

---

## Getting started

Docker:

```bash
git clone https://github.com/agit8or1/clientst0r.git
cd clientst0r
cp .env.example .env
# edit .env — at minimum: SECRET_KEY, DB_PASSWORD, DB_ROOT_PASSWORD, APP_MASTER_KEY
docker compose up -d
```

Native install on Ubuntu 20.04+ / Debian 11+:

```bash
git clone https://github.com/agit8or1/clientst0r.git && cd clientst0r && bash install.sh
```

Full guides: [README](README.md#quick-start), [INSTALL.md](INSTALL.md),
[docs/docker.md](docs/docker.md).

---

## Learn more

- [Full feature list](FEATURES.md)
- [Moving from IT Glue](docs/it-glue-alternative.md)
- [Moving from Hudu](docs/hudu-alternative.md)
- [API documentation](API_V2_GRAPHQL.md)
- [Security policy](SECURITY.md)
- [Changelog](CHANGELOG.md)

---

<p align="center">
  <strong>ClientSt0r</strong> — Built by MSPs, for MSPs.<br>
  <a href="https://github.com/agit8or1/clientst0r/issues">Report a Bug</a> ·
  <a href="https://github.com/agit8or1/clientst0r/issues">Request a Feature</a> ·
  <a href="CONTRIBUTING.md">Contribute</a>
</p>
