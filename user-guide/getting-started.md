# Getting Started

## Quick Start

1. **Log in** — Use your credentials, or Azure AD SSO or LDAP / Active Directory if configured.
2. **Create or select an Organization** — All data is scoped to organizations.
3. **Add your team** — *Admin → Access Management* (`/accounts/access-management/`).
4. **Set each technician's User Type to Staff** — see [MSP staff and customer users](#msp-staff-and-customer-users).
5. **Assign roles** — Grant Owner, Admin, Editor, or Read-Only per user and organization.
6. **Add assets or passwords** — Start populating inventory or the vault.
7. **Set up monitoring** — Create monitors for public-facing endpoints.

---

## Organizations

Organizations are the top-level containers for all data. ClientSt0r is **multi-tenant** — each client, department, or team has its own organization.

| Action | Where |
|--------|-------|
| Create | *Admin → Organizations → New Organization* |
| Switch | Organization selector in the top navigation bar |
| Scope | Assets, passwords, documents, tickets, vehicles and monitors belong to one org |
| Global | Templates and reference data can be shared across all organizations |

**Switching organizations** — click the org name in the top nav bar. All data views immediately update to reflect the selected organization. MSP staff also have a Global View that shows all organizations at once; customer users don't.

---

## MSP staff and customer users

Every user is one of two kinds. The difference decides what they can see, independently of their role.

| | MSP staff | Customer users |
|---|---|---|
| Who | Superusers, and users whose **User Type** is *Staff* | Everyone else — people who log in for one of your customers |
| Customers they see | All of them | Only the organizations they are a member of |
| Assignable work (tickets, problems, projects and tasks, recurring work, dispatch) | Yes, for any customer | No — they never appear as assignees, on the dispatch board or in technician suggestions |
| Assigning work to technicians | Yes | No, not even a customer's organization admin |
| Tickets | All tickets | Only tickets marked as visible to the client |
| Internal notes and internal attachments | Yes | No |
| Global dashboard (every customer's counts and activity) | Yes | No |
| Global document templates | Can edit | Can use; edit only their own organization's templates |

Set the User Type under *Admin → Access Management → Users → Edit* (`/accounts/users/<id>/edit/`, superusers only).

> **Upgrading from before v3.17.600?** A technician who was set up as an ordinary member of several customer organizations is now treated as a customer user: in the web UI and the mobile app they see only shared tickets, no internal notes, and only their own customers. Change their User Type to Staff to restore full access.

Tickets are **not** shared with the client by default. Share the ones customer users should see, or create them from the customer portal, which shares them automatically.

If you use LDAP sign-in, the optional MSP staff group in Settings → Directory sets each directory user's type at sign-in.

---

## Service desk at a glance

Once the service desk is on (`psa_enabled` in *Settings → Feature Toggles*):

- **My Work** (`/psa/my-work/`, first item in the PSA menu, and a button on the dashboard) is
  each technician's starting point: open tickets in SLA order, running timers with a stop
  button, tickets where the customer replied, "waiting on customer" and "waiting on us"
  queues, pending approvals, and today's and upcoming appointments.
- On a ticket, choose **Public reply** or **Internal note** explicitly; internal notes use an
  amber composer, and a public reply asks you to confirm the recipient before it is emailed.
  Drafts save as you type. Press `?` for keyboard shortcuts.
- Resolving or closing a ticket checks the resolution summary, category, required checklist
  items and sign-off, whichever route you take.
- Customers can **Request a service** in the portal (`/portal/requests/`): items from the
  service catalog marked as visible in the portal, with guided forms and optional approval
  by the customer's admin. `python manage.py psa_seed_portal_requests` adds sample request
  types.

---

## Users & Roles

Within an organization, access is set by a role. Four built-in roles cover most cases:

| Role | Capabilities |
|------|-------------|
| **Owner** | Full control of the organization, including its users |
| **Admin** | Manage users, integrations, settings and all data |
| **Editor** | Create and edit data; cannot manage users or settings |
| **Read-Only** | View data only; cannot create, edit, or delete |

- Custom roles (*Admin → Access Management → Roles*) combine individual permission switches.
- A user can have **different roles** in different organizations.
- **View passwords**, **View documents** and **View assets** are enforced everywhere those records appear — lists, detail pages, global search, dashboards, the REST and GraphQL APIs, the mobile app and the browser extension. Contacts follow **View assets**. A user's own personal vault is not affected.
- **View files**, **View monitors** and **View integrations** are saved but **not enforced yet**; the role editor marks them "(not enforced yet)". Don't rely on them to hide those areas.

---

## API Keys

API keys authenticate programmatic access to the REST API and the browser extension.

| Action | Details |
|--------|---------|
| Generate | Click your username → *API Keys* → *Create New Key* (`/api/keys/`) |
| Format | Keys are prefixed `itdocs_live_…` |
| Usage | `Authorization: Bearer YOUR_KEY` header |
| Scope | Keys inherit your user's organization access and role permissions |
| Revoke | Delete a key instantly to invalidate all current uses |
| Deactivation | A key stops working when its user is deactivated, or when a customer user no longer belongs to the key's organization |

```bash
# Example API call
curl -H "Authorization: Bearer itdocs_live_xK9mPL..." \
     https://your-server/api/assets/
```

> **Security:** Copy your key immediately after creation — it is only shown once. Keys don't expire on their own; delete keys you no longer use.

---

*Next: [Asset Management](asset-management.md)*
