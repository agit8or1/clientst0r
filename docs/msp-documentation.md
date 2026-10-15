# MSP Documentation with ClientSt0r

Effective MSP operations rely on accurate, accessible documentation. ClientSt0r provides a structured platform for organizing client and infrastructure knowledge. See [FEATURES.md](../FEATURES.md) for each capability's status and limitations.

## What ClientSt0r Helps Document

### Clients & Organizations
- Multi-organization support: every record belongs to a client organization, and customer users see only their own
- Per-client documentation spaces
- Contact management

### Assets & Infrastructure
- Device and asset tracking with warranty and end-of-life dates
- Interactive rack diagrams with drag-and-drop placement
- Wall-mounted board layouts for network closets
- IPAM (IP address management) with subnet tracking
- VLAN documentation
- Patch panel management

### Security
- AES-256-GCM encrypted password vault with audited reveals
- Personal vaults per user
- Every stored secret encrypted or hashed at rest, with master-key rotation (`rotate_encryption_key`)
- Sign-in with local accounts and enforced 2FA, Azure AD / Entra ID SSO, or LDAP / Active Directory
- Password breach detection (Have I Been Pwned, k-anonymity)
- Encrypted backups via the `manage.py backup` command

### Knowledge Base
- Per-organization documentation with a saved version on every edit; compare and restore versions
- Document owners, review intervals, drafts, publish approval and an Archived list
- Template drift: see which documents are behind their template, with a diff
- KB analytics: most and never viewed, overdue reviews, searches that found nothing
- Global MSP knowledge base (MSP staff only)
- Draw.io diagram integration
- Floor plan import (MagicPlan)
- SOPs and runbooks

### Documentation Readiness
- Standards for what every client (or every client of a type) must have documented
- A per-client score with a plain explanation and a fix link for every gap
- A repair queue across clients, audited exceptions, and a broken-relationships report

### Monitoring & Expiration Tracking
- Website uptime and SSL certificate checks, with email alerts when a site goes down and recovers
- Email alerts for expiring SSL certificates, domains (dates you enter) and credentials

### Fleet Management
- Service vehicle tracking
- Mileage, maintenance, and fuel logs
- Interactive damage reports with vehicle diagrams
- Vehicle inventory management

### Integrations
- PSA providers (ConnectWise Manage, Autotask, HaloPSA, Kaseya BMS, Syncro, Freshservice, Zendesk, ITFlow) — companies, contacts and tickets; RangerMSP and Alga PSA newly added (Limited)
- 5 RMM providers (Tactical RMM, NinjaOne, Datto RMM, Atera, ConnectWise Automate) — devices, alerts and software
- REST API v1 and GraphQL API v2

## Goal

Reduce tribal knowledge risk, improve onboarding speed, and enable consistent service delivery across the team.
