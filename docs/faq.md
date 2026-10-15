# Frequently Asked Questions

## General

**Is ClientSt0r open source?**
Yes. ClientSt0r is MIT-licensed. Every first-party feature works on a self-hosted install
with no paid tier, seat limit or licence key.

**Is ClientSt0r self-hosted?**
Yes. ClientSt0r is self-hosted software that you run on infrastructure you control. There
is no public demo instance. Optional managed hosting and commercial support are offered
separately by [MSP Reboot](https://mspreboot.com) for teams that would rather not run it
themselves; they are not required to use any feature.

**Who should use ClientSt0r?**
Managed service providers and IT teams who want client documentation, credentials,
assets and a service desk in one system, on their own server.

**Can I move my data from IT Glue or Hudu?**
Partly. The built-in importers (**Imports**, `/imports/`) connect to the IT Glue or Hudu API
and bring over assets, passwords and documents, each into the client its source record
belongs to. Contacts, locations and networks are not imported yet (CSV import covers
contacts). A dry run is on by default and writes nothing; a job reports "Completed" only
when nothing failed, and rollback keeps anything edited since the import. Review the result
before switching over. See [Moving from IT Glue](it-glue-alternative.md)
and [Moving from Hudu](hudu-alternative.md).

## Installation

**What are the system requirements?**
Either Docker Engine 24.0+ with the Compose v2 plugin, or Ubuntu 20.04+ / Debian 11+ with
2 GB RAM (4 GB recommended) and 10 GB free disk for the native installer, which sets up
Python 3.12, MariaDB, Gunicorn and the systemd units.

**How do I install ClientSt0r?**

Docker:
```bash
git clone https://github.com/agit8or1/clientst0r.git
cd clientst0r
cp .env.example .env   # set SECRET_KEY, DB_PASSWORD, DB_ROOT_PASSWORD, APP_MASTER_KEY
docker compose up -d
```

Native install on Ubuntu or Debian:
```bash
git clone https://github.com/agit8or1/clientst0r.git && cd clientst0r && bash install.sh
```

See the [README](../README.md#quick-start), [INSTALL.md](../INSTALL.md) and
[docker.md](docker.md).

**Can I update without SSH?**
Yes, on native installs. Go to **Settings → Updates** (`/core/settings/updates/`), click
*Check for Updates*, then *Apply*. The web service is reloaded gracefully. Docker installs
update with `docker compose pull && docker compose up -d`. Take a backup first; there is no
automatic rollback.

**Do I need to set up cron jobs?**
No. Since v3.17.599 every periodic job (recurring invoices, email-to-ticket polling,
recurring tickets, contract renewals, SLA checks, reminders and the rest) runs from the
built-in scheduler. You can see each job's last run and last error, and turn jobs on or
off, at **Settings → Scheduler** (`/core/settings/scheduler/`). Native installs drive it with
`clientst0r-scheduler.timer`; Docker installs run a `scheduler` service.

## Users and access

**What is the difference between MSP staff and customer users?**
MSP staff are superusers or users whose **User Type** is *Staff* (Access Management →
Users → Edit). They work across every customer. Everyone else is a customer user: they
see only the customers they are a member of, only tickets marked as visible to the client,
and no internal notes or internal attachments. If your technicians were set up as ordinary
members of customer organizations, change their User Type to Staff. Staff users can be
assigned tickets, projects and recurring work for any customer.

**Do role permissions control what people can see?**
Partly. **View passwords**, **View documents** and **View assets** (contacts follow View
assets) are enforced everywhere those records appear, including search, the APIs, the
mobile app and the browser extension. **View files**, **View monitors** and **View
integrations** are saved but not enforced yet; the role editor marks them as such.

## Features

**Does ClientSt0r support multiple organizations?**
Yes. Every asset, document, credential, location and ticket belongs to an organization,
and customer users are limited to their own organizations.

**Does ClientSt0r support SSO?**
Azure AD / Microsoft Entra ID single sign-on is supported, and so is LDAP / Active Directory
sign-in (Settings → Directory, with a Test connection button). LDAP needs the optional
`django-auth-ldap` and `python-ldap` packages from `requirements-optional.txt`. Local
accounts keep working alongside it. SAML and generic OIDC are not available.

**Is 2FA supported?**
Yes. TOTP 2FA is enforced for every account by default. It is set install-wide with
**Require 2FA** in Settings → Security; a `REQUIRE_2FA` environment variable, if set,
overrides that and locks the field. LDAP users follow the same rule. Users who sign in
through Azure AD / Entra ID SSO skip the local 2FA prompt, so enforce MFA in Entra ID for
them.

**Where do session, lockout and password-policy settings come from?**
Settings → Security, since v3.17.610. An environment variable such as
`SESSION_IDLE_TIMEOUT`, `AXES_COOLOFF_TIME` or `PASSWORD_MIN_LENGTH` wins when it is set,
and the field then shows "set by environment".

**Are stored credentials encrypted?**
Yes. Vault entries and every other stored secret (integration, SMTP/SMS, directory and
webhook credentials and the like) are encrypted with AES-256-GCM; tokens the app only
compares are stored as hashes. `python manage.py rotate_encryption_key` rotates the master
key and `python manage.py check_secrets_storage` reports anything stored unprotected. See
[SECURITY.md](../SECURITY.md#secrets-management).

**What PSA integrations are available?**
ConnectWise Manage, Autotask, HaloPSA, Kaseya BMS, Syncro, Freshservice, Zendesk and
ITFlow. ClientSt0r also has its own built-in service desk (off until an administrator turns
on `psa_enabled`).

**Where does a technician start the day?**
**My Work** (`/psa/my-work/`, first item in the PSA menu): open tickets in SLA order,
running timers, tickets where the customer replied, waiting queues, pending approvals and
appointments.

**Can customers request services themselves?**
Yes. Portal users get **Request a service**: they pick an item from the service catalog,
answer a guided form, see knowledge-base articles that might already help, and submit. The
request becomes a ticket routed to the right queue, and can ask the customer's admin for
approval. Mark catalog items as visible in the portal to offer them.

**Does ClientSt0r alert me when a website goes down?**
Yes. With "notify on down" on, a monitor emails superusers and the customer's admins once
after two failed checks in a row and once when it recovers, and fires `monitor.down` /
`monitor.up` webhooks.

**Are AI features required?**
No. AI-assisted features are optional. Nothing calls an AI provider until you configure
one. Documentation AI and receipt scanning can use Anthropic, OpenAI, Moonshot, MiniMax or
a local Ollama model; the service desk AI features currently use Anthropic only. The
service desk AI, documentation AI and vehicle receipt scanning are additionally gated by
`psa_ai_enabled`, which is off by default.
