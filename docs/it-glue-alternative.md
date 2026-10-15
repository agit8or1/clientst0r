# Moving from IT Glue to ClientSt0r

ClientSt0r is a self-hosted, MIT-licensed IT documentation and service desk platform for
MSPs. Teams coming from IT Glue often evaluate it because they want documentation,
credentials, assets and ticketing in one system they run themselves. This page describes
what ClientSt0r offers and how much of an IT Glue account its importer brings over today.
It makes no claims about IT Glue's current features or pricing.

## ClientSt0r at a glance

| Category | ClientSt0r |
| --- | --- |
| Licence | MIT, open source; no licence fee, seat or client limits |
| Hosting | Self-hosted (Docker or native install). Optional managed hosting and support are offered separately by [MSP Reboot](https://mspreboot.com) |
| Data control | Your server, your database, your backups |
| Customisation | Source is public and modifiable |
| Support | Community (GitHub Issues and Discussions), or commercial support through MSP Reboot |

## Capabilities

| Capability | Status in ClientSt0r |
| --- | --- |
| Asset management (fixed asset types, tags, photos, relationships) | Available; per-type custom fields are not in the UI yet |
| Encrypted password vault (AES-256-GCM, audited reveals) | Available |
| Knowledge base, runbooks and per-client documents | Available |
| IPAM, VLANs and rack elevations | Available |
| Built-in service desk with SLAs, contracts and invoicing | Available (opt-in) |
| PSA integrations | Available — ConnectWise Manage, Autotask, HaloPSA, Kaseya BMS, Syncro, Freshservice, Zendesk, ITFlow (companies, contacts, tickets); RangerMSP and Alga PSA Limited (newly added) |
| RMM integrations | Available — 5 providers: Tactical RMM, NinjaOne, Datto RMM, Atera, ConnectWise Automate (devices, alerts, software) |
| Multi-organization with customer logins | Available |
| Sign-in | Azure AD / Entra ID SSO and LDAP / Active Directory sign-in available (LDAP needs optional packages); 2FA enforced by default |
| Documentation readiness and lifecycle | Available — per-client readiness scores and a repair queue, document owners and review dates, drafts, version compare and restore |
| Bitwarden / Vaultwarden import | Available |
| Fleet (service vehicle) management | Available |

Full list with limitations: [FEATURES.md](../FEATURES.md).

## What the IT Glue importer brings over

The importer (**Imports**, `/imports/`) connects to the IT Glue API with an API key.

| IT Glue data | Imported today |
| --- | --- |
| Organizations | Yes — matched to existing organizations, or created |
| Configurations (as assets) | Yes |
| Passwords | Yes — encrypted on arrival |
| Documents | Yes |
| Contacts | Not yet |
| Locations | Not yet |
| Networks | Not yet |
| Flexible assets, attachments, relationships, permissions | Not yet |

- A **dry run** is on by default and reports counts without writing anything.
- Each job keeps a log and history, and imported records are tagged with their source.
- **One or all organizations.** Import into a single target organization, or import every
  IT Glue organization at once.
- Each record goes to the client its source record belongs to.
- A job shows "Completed" only when nothing failed; otherwise "Completed with errors" or
  "Failed", with imported / skipped / failed counts that add up to the source total, and the
  log on the import page.
- **Rollback** runs in one transaction. Records edited after the import are kept and listed,
  and organizations the import created are removed only when nothing else uses them; if
  anything was kept the job shows "Partially rolled back".

## Before you switch

* Run a dry run, then a real import into a test organization, and compare record counts
  with IT Glue.
* Plan how you will bring over contacts, locations and networks (CSV import or by hand)
  until those importers ship. CSV contact and password imports work, and re-running a CSV
  import updates matching rows instead of duplicating them.
* Check the integrations, sign-in method and exports you depend on against
  [FEATURES.md](../FEATURES.md).

## Install

```bash
# Docker
git clone https://github.com/agit8or1/clientst0r.git && cd clientst0r
cp .env.example .env   # set SECRET_KEY, DB_PASSWORD, DB_ROOT_PASSWORD, APP_MASTER_KEY
docker compose up -d

# or native, on Ubuntu 20.04+ / Debian 11+
git clone https://github.com/agit8or1/clientst0r.git && cd clientst0r && bash install.sh
```

---

[Back to docs index](README.md)
