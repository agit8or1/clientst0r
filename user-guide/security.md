# Security

Built-in security tooling — vulnerability scanning, role-based access control, audit logging, 2FA, and data protection. For each capability's status and limitations, see [FEATURES.md](../FEATURES.md#security).

---

## Vulnerability Scanning

| Feature | Details |
|---------|---------|
| **Dependency scanning** | Python and JavaScript dependencies via Snyk (needs the Snyk CLI and a token), plus a Python dependency scanner |
| **OS package scanning** | apt, yum/dnf and pacman; flags pending security updates |
| **Scheduled scans** | Opt-in from the Security dashboard (`/core/security/`); the interval is set in *Settings → Scheduler*; superusers are emailed when vulnerabilities are found |
| **Remediation** | Upgrade paths and advisories for each finding |
| **History** | Past scans, with a comparison against the previous one |

### Severity Levels

| Level | Color | CVSS Score |
|-------|-------|------------|
| **Critical** | Red | 9.0–10.0 |
| **High** | Orange | 7.0–8.9 |
| **Medium** | Yellow | 4.0–6.9 |
| **Low** | Grey | 0.1–3.9 |

---

## Authentication & Access Control

| Feature | Details |
|---------|---------|
| **Two-Factor Auth (2FA)** | TOTP, enforced for every account by default. Set install-wide (not per organization) with **Require 2FA** in Settings → Security |
| **Azure AD SSO** | Single sign-on with Microsoft Entra ID. SSO users skip the local 2FA prompt, so enforce MFA in Entra ID |
| **LDAP / Active Directory** | Sign in with directory accounts — see [LDAP sign-in](#ldap--active-directory-sign-in) |
| **Password Policy** | Minimum length (default 12) and a special-character rule, set in Settings → Security; also not a common password, not all numeric, not similar to the username |
| **Session Timeout** | Idle timeout (default 60 minutes) and maximum session length (default 8 hours), set in Settings → Security |
| **IP and country rules** | Allow or block IP addresses and countries (`/core/settings/firewall/`); enforced by the application |
| **Account Lockout** | After the failed-login limit (default 5) per username and IP, sign-in is locked for the lockout duration (default 30 minutes); both set in Settings → Security |

> **Where these values come from.** Settings → Security (`/core/settings/security/`) is
> the source since v3.17.610. A server environment variable, if set, wins:
> `REQUIRE_2FA`, `PASSWORD_MIN_LENGTH`, `PASSWORD_REQUIRE_SPECIAL`, `SESSION_IDLE_TIMEOUT`
> and `SESSION_COOKIE_AGE` (seconds), `AXES_FAILURE_LIMIT`, `AXES_COOLOFF_TIME` (hours).
> Those fields then show **set by environment** and can't be changed on the page; remove
> the variable from `.env` and restart to manage them in the UI.

### LDAP / Active Directory sign-in

Configure at **Settings → Directory** (`/core/settings/directory/`). It is off until you
enable it, and it won't switch on with missing or invalid settings.

1. Install the optional packages on the server: `pip install -r requirements-optional.txt`
   (`django-auth-ldap` and `python-ldap`; the file lists the system packages `python-ldap`
   needs). The page tells you if they're missing.
2. Add one or more servers, with LDAPS or StartTLS. Certificate checking is on by default;
   you can supply a CA file.
3. Set the bind account, user search and attribute mapping, the group a user must belong to
   (nested Active Directory groups count), and optionally an MSP staff group — members
   become Staff users, everyone else a customer user, decided at each sign-in.
4. Click **Test connection** to check the bind and, optionally, look up a user. Nothing is
   saved and no secret is shown.

Local accounts keep working, and a local superuser can always sign in if the directory is
down. LDAP users get the same 2FA rules and lockout as local users. LDAP never makes anyone
a superuser and never takes over an existing local account with the same username.

### Enabling 2FA

1. Go to *Profile → Security → Enable Two-Factor Auth*
2. Scan the QR code with an authenticator app
3. Enter the 6-digit code to confirm
4. Save your backup codes in a secure location

---

## MSP Staff and Customer Users

Every user is either **MSP staff** (a superuser, or a user whose **User Type** is *Staff*) or a **customer user**. Only staff users can be assigned tickets, problems, projects and recurring work (for any customer) or appear on the dispatch board, and their global role counts in permission checks alongside any memberships. Customer users see only the organizations they belong to, only tickets marked as visible to the client, and no internal comments or internal attachments. Set the User Type at *Admin → Access Management → Users → Edit*. See [Getting Started](getting-started.md#msp-staff-and-customer-users).

---

## Role-Based Access Control (RBAC)

Four built-in roles cover most use cases:

| Role | Permissions |
|------|-------------|
| **Owner** | Everything in the organization, including its users |
| **Admin** | All data, users, integrations and settings |
| **Editor** | Create and edit data; no user or settings management |
| **Read-Only** | View data; no write access |

### Custom Roles

Create custom roles at *Admin → Access Management → Roles* (`/accounts/roles/`) by combining individual permission switches, grouped by area (assets, vault, documents, files, monitoring, integrations, service desk, reports, AI and more).

| View permission | Enforced? |
|---|---|
| **View passwords** | Yes — vault, global search, dashboards, ticket credential card, REST/GraphQL APIs, mobile app, browser extension |
| **View documents** | Yes — same places |
| **View assets** (contacts follow it) | Yes — same places |
| **View files** | Not yet — marked "(not enforced yet)" in the role editor |
| **View monitors** | Not yet |
| **View integrations** | Not yet |

Custom roles are assigned per organization, just like built-in roles. A role can only be assigned if it is a system role or that organization's own custom role.

---

## Audit Logging

The audit log (`/audit/`, Owners and Admins) has two kinds of entries:

| Kind | What is recorded |
|------|------------------|
| **Explicit events** | Sign-ins, credential reveals and reveal approvals, API key use, browser-extension calls, system updates, and many create / update / delete actions — with user, time, IP address and a description |
| **Request log** | Every POST / PUT / DELETE and every detail-page view: user, time, IP, method, path, status and the submitted form fields (secrets redacted) |

Most changes are **not** stored with before / after values; invoice status and note changes on sent, paid or void invoices are an exception. List pages are not logged.

### Filtering and Exporting

Filter by user, date range, action type, and object type. Export the filtered results as CSV or JSON (current organization, up to 5,000 rows).

---

## Data Protection

| Layer | Details |
|-------|---------|
| **Encryption at Rest** | AES-256-GCM for vault credentials (with per-purpose derived keys) and for every other stored secret — integration, SMTP, SMS, LDAP and Azure AD, webhook and API-key credentials — each bound to the field it belongs to. Tokens the app only compares (API keys, browser-extension and inbound webhook tokens) are stored as hashes. Forms never show a stored secret back; leave a secret field blank to keep it |
| **Key rotation** | `python manage.py rotate_encryption_key` re-encrypts everything under a new master key; `APP_MASTER_KEY_PREVIOUS` keeps old keys readable during the switch and for older backups. `python manage.py check_secrets_storage` reports anything stored unprotected. See [SECURITY.md](../SECURITY.md#key-rotation) |
| **Content-Security-Policy** | Sent on every page with per-request script nonces; inline event handlers are blocked. Report-only by default (violations logged to `security.csp`); set `CSP_REPORT_ONLY=False` to enforce, or `CSP_ENABLED=False` to turn it off |
| **Encryption in Transit** | HTTPS with HSTS; HTTP redirected to HTTPS in production |
| **Uploaded files** | Every download goes through a permission check on the record the file belongs to; files no record claims return 404 |
| **Backups** | `python manage.py backup` writes an encrypted archive of the database and uploads. It is not scheduled automatically — run it from cron or before updates, and keep `APP_MASTER_KEY` safe and separate |
| **Data export** | Whole-install JSON export for superusers (`/core/settings/data-export/`) |

---

*Previous: [WAN Monitoring](wan-monitoring.md) · Next: [API & Integrations](api.md)*
