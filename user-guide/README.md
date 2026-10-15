# ClientSt0r User Guide

ClientSt0r is a self-hosted IT management platform for MSPs and IT teams — combining asset inventory, a password vault, fleet management, WAN monitoring, and security tooling, all scoped per organization.

> **In-app help** is also available at `/help/` once logged in.

---

## Sections

| Section | Description |
|---------|-------------|
| [Getting Started](getting-started.md) | Organizations, users, roles, the service desk at a glance, API keys |
| [Asset Management](asset-management.md) | Hardware inventory, networks, racks, port configuration |
| [Service Vehicles](service-vehicles.md) | Fleet tracking, maintenance, fuel logs, damage reports |
| [Password Vault](password-vault.md) | AES-256 encrypted credentials, TOTP, breach detection |
| [WAN Monitoring](wan-monitoring.md) | HTTP/TCP/ICMP checks, SSL expiry, alerting |
| [Security](security.md) | 2FA, LDAP and SSO sign-in, Security settings, RBAC, audit logs, encryption and key rotation |
| [Compliance](compliance.md) | PCI-DSS / HIPAA attestation, customer reports, recertification |
| [Reports & Analytics](reports.md) | Custom dashboards, report templates, scheduled reports |
| [Workflows](workflows.md) | Step-by-step checklists and process executions |
| [Documentation & KB](documentation.md) | Runbooks, knowledge base, document lifecycle and versions, documentation readiness, diagrams, AI assistant |
| [Locations & WAN](locations.md) | Physical sites and WAN connection management |
| [API & Integrations](api.md) | REST API, webhooks, RMM integrations |

---

## Architecture

```
All data is organization-scoped.
Every asset, password, document, ticket, vehicle and monitor belongs to one organization.
Users can belong to multiple organizations with different roles in each.
MSP staff (User Type = Staff) work across every organization; customer users see only
their own organizations, only tickets shared with them, and no internal notes.
```

See [Getting Started → MSP staff and customer users](getting-started.md#msp-staff-and-customer-users).

## Role Overview

| Role | Create/Edit | Delete | Manage Users | Org Settings |
|------|:-----------:|:------:|:------------:|:------------:|
| **Owner** | ✓ | ✓ | ✓ | ✓ |
| **Admin** | ✓ | ✓ | ✓ | — |
| **Editor** | ✓ | — | — | — |
| **Read-Only** | — | — | — | — |

Custom roles with granular permissions are also supported. The **View passwords**, **View documents** and **View assets** switches are enforced everywhere; **View files**, **View monitors** and **View integrations** are not enforced yet.

## API Authentication

```http
Authorization: Bearer itdocs_live_<your_api_key>
```

Generate keys at **Profile → API Keys** (`/api/keys/`). Keys inherit your organization membership and role permissions, and stop working when the user is deactivated.

---

*For installation and deployment, see [INSTALL.md](../INSTALL.md).*
