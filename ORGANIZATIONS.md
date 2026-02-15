# Organizations & Access Control

## Table of Contents

1. [Overview](#overview)
2. [Multi-Tenancy Model](#multi-tenancy-model)
3. [User Types](#user-types)
4. [Roles & Permissions](#roles--permissions)
5. [Organization Management](#organization-management)
6. [Access Scenarios](#access-scenarios)
7. [Best Practices](#best-practices)

---

## Overview

Client St0r uses a **multi-tenant architecture** where all data is isolated by **Organization**. This design is specifically built for:

- **MSPs (Managed Service Providers)** - Manage multiple client organizations from a single installation
- **IT Departments** - Separate data by department, division, or subsidiary
- **Multi-Company Environments** - Maintain strict data separation between business units

### Key Concepts

- **Organization**: A tenant/workspace that contains isolated data (assets, passwords, documents, etc.)
- **Membership**: A user's association with an organization, defining their role and permissions
- **User Type**: Determines if a user is internal staff or an organization-specific user
- **Role**: Defines what actions a user can perform within an organization

---

## Multi-Tenancy Model

### Data Isolation

**Everything is scoped to an organization:**

```
Organization: "Acme Corp"
├── Assets (servers, workstations, devices)
├── Passwords (encrypted credentials)
├── Documents (knowledge base articles)
├── Diagrams (network diagrams, process flows)
├── Processes (runbooks, procedures)
├── Contacts (people at this organization)
├── Files (attachments, uploads)
├── Website Monitors (uptime checks)
├── Racks & Subnets (infrastructure)
└── Secure Notes (ephemeral messages)
```

**Users cannot see data from other organizations unless:**
- They have a Membership in that organization (assigned by owner/admin)
- They are a Staff User (see [User Types](#user-types))

### Organization Switching

Users with access to multiple organizations can switch between them:

1. Click organization name in top navigation bar
2. Select different organization from dropdown
3. All views immediately filter to show only that organization's data

**Active Organization** is stored in the session and persists across pages.

---

## User Types

Client St0r supports two distinct user types, designed for the MSP model:

### 1. Organization Users (Client Users)

**Default user type** - Standard client/customer users.

**Characteristics:**
- Can only access organizations they are explicitly invited to
- Must have a Membership record for each organization
- Cannot see global data or other organizations
- Typical use: Client employees, department staff

**Example Scenario:**
```
User: john@acmecorp.com (Organization User)
Memberships:
  - Acme Corp (Admin role)

Can see: Only Acme Corp data
Cannot see: Other client organizations, global KB, system settings
```

### 2. Staff Users (MSP Techs)

**Internal staff** - Your MSP technicians, administrators.

**Characteristics:**
- Can access **ALL organizations** regardless of membership
- Have global visibility across entire platform
- Can create and manage organizations
- Access Global Knowledge Base (internal documentation)
- Shown with blue "Staff" badge in UI

**Example Scenario:**
```
User: tech@mspreboot.com (Staff User)
Memberships: (optional - can access all orgs without membership)

Can see: All client organizations, global KB, system settings
Automatic: Admin-level access to all organizations
```

**How to Make a User a Staff User:**
1. Navigate to Admin > User Management
2. Edit user profile
3. Change "User Type" from "Organization User" to "Staff User"
4. Save

---

## Roles & Permissions

Client St0r provides a **4-tier simple role system** plus optional **granular role templates**.

### Simple Roles

#### Owner
**Full control** - Highest privilege level.

**Can:**
- ✅ Everything an Admin can do
- ✅ Invite/remove members
- ✅ Change member roles
- ✅ Delete organization
- ✅ Manage organization settings
- ✅ Manage API keys for organization

**Typical Use:** Organization owner, primary contact, MSP account manager

---

#### Admin
**Almost full control** - Cannot manage users or settings.

**Can:**
- ✅ View, create, edit, delete all data (passwords, assets, docs, etc.)
- ✅ Export password vault
- ✅ View password values
- ✅ Configure integrations (PSA, LDAP)
- ✅ Trigger manual syncs
- ✅ View audit logs
- ✅ View organization members

**Cannot:**
- ❌ Invite/remove members
- ❌ Change member roles
- ❌ Modify organization settings
- ❌ Manage API keys

**Typical Use:** IT managers, senior technicians, department heads

---

#### Editor
**Create and edit** - Daily work role.

**Can:**
- ✅ View all data (passwords, assets, docs, monitors, etc.)
- ✅ Create new items (passwords, assets, docs, monitors)
- ✅ Edit existing items
- ✅ View password values
- ✅ Upload files
- ✅ Trigger website monitor checks
- ✅ View organization members
- ✅ API access (with personal API key)

**Cannot:**
- ❌ Delete items (passwords, assets, docs)
- ❌ Export password vault
- ❌ Publish/unpublish documents
- ❌ Configure integrations
- ❌ View audit logs
- ❌ Invite members or change roles

**Typical Use:** Technicians, content creators, daily operators

---

#### Read-Only
**View only** - No modifications.

**Can:**
- ✅ View assets, documents, monitors, files
- ✅ View password entries (title, username, folder)
- ✅ View organization members

**Cannot:**
- ❌ View password values (passwords are masked)
- ❌ Create, edit, or delete anything
- ❌ Upload files
- ❌ Export data
- ❌ Access API

**Typical Use:** Clients viewing their own documentation, report-only users, auditors

---

### Granular Permission System (Advanced)

For fine-grained control beyond simple roles, use **Role Templates**.

**42 Individual Permissions** across 10 categories:

#### Vault Permissions (6)
- `vault_view` - View password list and details
- `vault_create` - Create new passwords
- `vault_edit` - Edit password entries
- `vault_delete` - Delete passwords
- `vault_export` - Export password vault to CSV/JSON
- `vault_view_password` - See actual password values

#### Assets Permissions (4)
- `assets_view` - View asset list and details
- `assets_create` - Create new assets
- `assets_edit` - Edit asset information
- `assets_delete` - Delete assets

#### Documents Permissions (5)
- `docs_view` - View documents
- `docs_create` - Create new documents
- `docs_edit` - Edit documents
- `docs_delete` - Delete documents
- `docs_publish` - Publish/unpublish documents

#### Files Permissions (3)
- `files_view` - View uploaded files
- `files_upload` - Upload new files
- `files_delete` - Delete files

#### Monitoring Permissions (5)
- `monitoring_view` - View website monitors, expirations
- `monitoring_create` - Create monitors
- `monitoring_edit` - Edit monitors
- `monitoring_delete` - Delete monitors
- `monitoring_trigger` - Manually trigger checks

#### Integrations Permissions (3)
- `integrations_view` - View integration connections
- `integrations_configure` - Configure PSA/LDAP/AD connections
- `integrations_sync` - Trigger manual data syncs

#### Audit Permissions (2)
- `audit_view` - View audit logs
- `audit_export` - Export audit logs

#### Organization Permissions (4)
- `org_view_members` - View member list
- `org_invite_members` - Invite new members
- `org_manage_members` - Edit/remove members
- `org_manage_settings` - Change org settings

#### API Permissions (2)
- `api_access` - Use REST API
- `api_keys_manage` - Create/revoke API keys

#### Processes Permissions (4)
- `processes_view` - View processes/runbooks
- `processes_create` - Create processes
- `processes_edit` - Edit processes
- `processes_delete` - Delete processes

---

### Creating Custom Role Templates

**Use Case:** Need a "Help Desk" role that can view passwords but not export them, and create tickets but not delete anything.

**Steps:**
1. Navigate to **Profile Dropdown > Roles**
2. Click **"Create Role Template"**
3. Name it (e.g., "Help Desk Technician")
4. Select specific permissions:
   - ✅ `vault_view`, `vault_create`, `vault_edit`, `vault_view_password`
   - ❌ `vault_delete`, `vault_export`
   - ✅ `assets_view`, `assets_create`, `assets_edit`
   - ❌ `assets_delete`
   - etc.
5. Save template
6. Assign to members via **Members > Edit > Role Template**

**Templates are organization-specific** - Each organization can define their own role templates.

---

## Organization Management

### Creating an Organization

**Who Can Create:**
- Superusers (via Django admin)
- Staff Users (via Organizations page)

**Steps for Staff Users:**
1. Navigate to **Profile Dropdown > Organizations**
2. Click **"Add Organization"**
3. Enter name (slug auto-generates)
4. Add optional description
5. Click **"Save"**
6. You are automatically made the Owner

### Inviting Members

**Who Can Invite:**
- Owners (can invite anyone with any role)
- Admins (can invite Editors and Read-Only users)

**Steps:**
1. Switch to the organization
2. Navigate to **Profile Dropdown > Members**
3. Click **"Invite Member"**
4. Enter username or email
5. Select role (Owner/Admin/Editor/Read-Only)
6. Optional: Select custom role template
7. Click **"Send Invite"**

**Note:** If the user doesn't exist, you'll need to create them first via **Admin > User Management** (superuser only).

### Switching Organizations

**For Organization Users:**
1. Click organization name in top nav
2. Select different organization from dropdown
3. Page reloads with new organization context

**For Staff Users:**
- Same process, OR
- Use **Profile Dropdown > Organizations** to see all orgs
- Can access any organization directly without switching

### Removing Members

**Who Can Remove:**
- Owners only

**Steps:**
1. Navigate to **Profile Dropdown > Members**
2. Find member in list
3. Click **"Remove"** button
4. Confirm removal

**Warning:** Removing a member immediately revokes access to all organization data.

### Deleting an Organization

**Who Can Delete:**
- Superusers only (via Admin panel)

**Process:**
1. Navigate to **Admin > Settings > Maintenance**
2. Find "Organization Management" section
3. Select organization to delete
4. Confirm deletion (requires typing organization name)

**⚠️ WARNING:** Deletion is permanent and cascades:
- All assets, passwords, documents, diagrams, processes
- All memberships
- All files and attachments
- All audit logs for this organization

---

## Access Scenarios

### Scenario 1: New MSP Client

**Goal:** Set up a new client organization and invite their admin.

**Steps:**
1. **Create Organization** (Staff User or Superuser)
   - Name: "Contoso Ltd"
   - Description: "Manufacturing company, 50 employees"

2. **Create Client User Account** (Superuser)
   - Username: `admin@contoso.com`
   - User Type: Organization User
   - Email: admin@contoso.com

3. **Invite to Organization** (Staff User switches to Contoso Ltd)
   - Add membership: admin@contoso.com → Owner role
   - Client can now log in and see only their data

4. **Client Invites Their Team**
   - Client owner invites: helpdesk@contoso.com → Editor
   - Client owner invites: ceo@contoso.com → Read-Only

**Result:**
```
Organization: Contoso Ltd
Members:
  - admin@contoso.com (Owner) - Full access
  - helpdesk@contoso.com (Editor) - Can edit, no delete
  - ceo@contoso.com (Read-Only) - View only

Staff Users (your MSP techs):
  - tech@mspreboot.com (Staff) - Can access all orgs including Contoso
```

---

### Scenario 2: Multi-Department Company

**Goal:** IT department managing multiple divisions.

**Setup:**
1. **Create Organizations:**
   - "Sales Department"
   - "Engineering Department"
   - "Finance Department"

2. **Create Department Users:**
   - sales-admin@company.com → Owner of Sales
   - eng-admin@company.com → Owner of Engineering
   - finance-admin@company.com → Owner of Finance

3. **IT Staff User:**
   - it-manager@company.com → Staff User
   - Automatic access to all departments

**Result:**
- Sales can only see Sales data
- Engineering can only see Engineering data
- Finance can only see Finance data
- IT Manager can see everything across all departments

---

### Scenario 3: MSP with Internal Documentation

**Goal:** Store internal MSP procedures separate from client data.

**Setup:**
1. **Global Knowledge Base:**
   - Navigate to **Docs > Global KB** (Staff only)
   - Create internal articles: "Onboarding Process", "Escalation Procedures"
   - These are **NOT** visible to any organization users

2. **Client-Specific Docs:**
   - Switch to client org (e.g., "Acme Corp")
   - Navigate to **Docs > Documents**
   - Create: "Acme Backup Procedures" (visible to Acme only)

**Result:**
- Staff see: Global KB + all client docs
- Acme users see: Only Acme docs (NOT Global KB)

---

### Scenario 4: Temporary Contractor Access

**Goal:** Give contractor limited access for 3 months.

**Steps:**
1. **Create User:**
   - Username: contractor@vendor.com
   - User Type: Organization User

2. **Invite with Custom Role:**
   - Create role template: "Contractor - Limited"
   - Permissions:
     - ✅ View assets, docs, monitors
     - ✅ Create/edit documents (for project documentation)
     - ❌ View passwords (no vault access)
     - ❌ Delete anything
   - Invite contractor@vendor.com with this template

3. **After Contract Ends:**
   - Navigate to **Members**
   - Remove contractor@vendor.com
   - Access immediately revoked

---

## Best Practices

### For MSPs

✅ **DO:**
- Make all your technicians **Staff Users**
- Use **Organization Users** for all clients
- Create an internal organization or use Global KB for your own documentation
- Assign at least 2 Owners per client organization (redundancy)
- Use custom role templates for specialized access (e.g., "Help Desk", "Junior Tech")

❌ **DON'T:**
- Don't make clients Staff Users (they'll see all other clients!)
- Don't share accounts between technicians
- Don't assign Owner role to junior techs
- Don't give Read-Only users access to password values

---

### For IT Departments

✅ **DO:**
- Create separate organizations for each department/division
- Use Staff Users for IT team members
- Assign department heads as Owners of their respective orgs
- Use role templates for specialized roles (e.g., "Network Admin", "Security Team")

❌ **DON'T:**
- Don't put all departments in one organization (no isolation)
- Don't make all IT staff Superusers (unnecessary privilege)

---

### Security Guidelines

1. **Principle of Least Privilege**
   - Start with Read-Only, elevate as needed
   - Use Editor role for day-to-day work, not Admin

2. **Owner Role Protection**
   - Limit Owner role to 2-3 trusted users
   - Owners can delete entire organizations (dangerous)

3. **Staff User Control**
   - Only promote trusted internal employees to Staff
   - Staff can access ALL client data (high privilege)

4. **Regular Audits**
   - Review members quarterly
   - Remove inactive users promptly
   - Check role assignments for correctness

5. **Two-Factor Authentication**
   - Enforce 2FA for all Owners and Staff Users
   - Recommended for all users

6. **API Key Management**
   - Limit `api_keys_manage` permission
   - Rotate keys every 90 days
   - Use separate keys per integration

---

## Permission Matrix Reference

Quick reference for simple roles:

| Feature | Owner | Admin | Editor | Read-Only |
|---------|-------|-------|--------|-----------|
| View Passwords | ✅ | ✅ | ✅ | ❌ (masked) |
| View Password Values | ✅ | ✅ | ✅ | ❌ |
| Create Passwords | ✅ | ✅ | ✅ | ❌ |
| Edit Passwords | ✅ | ✅ | ✅ | ❌ |
| Delete Passwords | ✅ | ✅ | ❌ | ❌ |
| Export Vault | ✅ | ✅ | ❌ | ❌ |
| View Assets | ✅ | ✅ | ✅ | ✅ |
| Create Assets | ✅ | ✅ | ✅ | ❌ |
| Edit Assets | ✅ | ✅ | ✅ | ❌ |
| Delete Assets | ✅ | ✅ | ❌ | ❌ |
| View Documents | ✅ | ✅ | ✅ | ✅ |
| Create Documents | ✅ | ✅ | ✅ | ❌ |
| Edit Documents | ✅ | ✅ | ✅ | ❌ |
| Delete Documents | ✅ | ✅ | ❌ | ❌ |
| Publish Documents | ✅ | ✅ | ❌ | ❌ |
| Upload Files | ✅ | ✅ | ✅ | ❌ |
| Delete Files | ✅ | ✅ | ❌ | ❌ |
| Configure Integrations | ✅ | ✅ | ❌ | ❌ |
| Trigger PSA Sync | ✅ | ✅ | ❌ | ❌ |
| View Audit Logs | ✅ | ✅ | ❌ | ❌ |
| Export Audit Logs | ✅ | ✅ | ❌ | ❌ |
| View Members | ✅ | ✅ | ✅ | ✅ |
| Invite Members | ✅ | ❌ | ❌ | ❌ |
| Remove Members | ✅ | ❌ | ❌ | ❌ |
| Change Roles | ✅ | ❌ | ❌ | ❌ |
| Manage Settings | ✅ | ❌ | ❌ | ❌ |
| Manage API Keys | ✅ | ❌ | ❌ | ❌ |
| API Access | ✅ | ✅ | ✅ | ❌ |

---

## Troubleshooting

### "User cannot see organization"

**Problem:** Invited user logs in but organization doesn't appear.

**Solutions:**
1. Verify Membership exists:
   - Navigate to **Members** in that organization
   - Check if user is listed

2. Check if membership is active:
   - Membership may be set to `is_active=False`
   - Edit membership and enable it

3. Try switching organizations:
   - User may need to manually switch (click org name in nav)

---

### "Permission denied when creating X"

**Problem:** User gets permission error despite having correct role.

**Solutions:**
1. Check if custom role template is assigned:
   - Custom templates override simple roles
   - Edit membership and check "Role Template" field

2. Verify organization context:
   - User may be in wrong organization
   - Switch to correct org

3. For Staff Users:
   - Staff bypass membership checks
   - Ensure user profile has `user_type='staff'`

---

### "Cannot delete organization"

**Problem:** Delete button doesn't appear or fails.

**Solutions:**
1. Check permissions:
   - Only **Superusers** can delete organizations
   - Owners cannot delete (security measure)

2. Use maintenance page:
   - Navigate to **Admin > Maintenance**
   - Find "Organization Management" section
   - Follow deletion process

---

### "Staff user cannot access organization"

**Problem:** Staff user shows errors when accessing org.

**Solutions:**
1. Verify Staff status:
   - Check user profile: User Type should be "Staff User"
   - Not just Django staff status

2. Check if organization is active:
   - Inactive orgs may not be accessible
   - Django admin: Organizations → Edit → `is_active=True`

---

## API Access Control

Organizations are enforced in the API using the same membership system.

### API Key Scoping

API keys are **user-scoped**, not organization-scoped:

```bash
# User has access to Acme Corp and Contoso Ltd

# Request Acme Corp assets
curl -H "Authorization: ApiKey YOUR_KEY" \
  https://yourdomain.com/api/assets/?organization=acme-corp

# Request Contoso Ltd assets
curl -H "Authorization: ApiKey YOUR_KEY" \
  https://yourdomain.com/api/assets/?organization=contoso-ltd
```

**If user doesn't have membership in requested organization:** `403 Forbidden`

**Staff Users:** Can access all organizations via API automatically.

---

## Advanced: Organization Managers

For custom organization querying in Django:

```python
from core.models import Organization
from accounts.models import Membership

# Get all organizations for a user
user_orgs = Organization.objects.filter(
    memberships__user=request.user,
    memberships__is_active=True
).distinct()

# Check if user has access to organization
org = Organization.objects.get(slug='acme-corp')
has_access = Membership.objects.filter(
    user=request.user,
    organization=org,
    is_active=True
).exists()

# Get user's role in organization
membership = Membership.objects.get(
    user=request.user,
    organization=org
)
permissions = membership.get_permissions()
if permissions.vault_view:
    # User can view passwords
```

---

## Summary

Client St0r's multi-tenant architecture provides:

✅ **Complete data isolation** between organizations
✅ **Flexible access control** with 4 simple roles + 42 granular permissions
✅ **MSP-optimized** with Staff vs Organization user types
✅ **Scalable** for 1 organization or 100+ clients
✅ **Secure by default** with least-privilege access

**Key Takeaway:** Everything in Client St0r is scoped to an organization, and users can only access what they're explicitly granted through memberships.

For questions or issues, see [GitHub Issues](https://github.com/agit8or1/clientst0r/issues).
