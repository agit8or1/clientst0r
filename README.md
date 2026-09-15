<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/github/clientst0r-wordmark-dark.svg">
  <img src="docs/images/github/clientst0r-wordmark.svg" alt="ClientSt0r" width="420">
</picture>

**Self-hosted IT documentation and service desk for MSPs.**

Keep customer documentation, assets, credentials and support workflows on your own infrastructure — one place for the runbook, the device it describes, the credential it needs, and the ticket it came from.

[![License: MIT](https://img.shields.io/github/license/agit8or1/clientst0r?color=blue)](LICENSE) [![Latest release](https://img.shields.io/github/v/release/agit8or1/clientst0r?label=release)](https://github.com/agit8or1/clientst0r/releases) [![CodeQL](https://github.com/agit8or1/clientst0r/actions/workflows/codeql.yml/badge.svg)](https://github.com/agit8or1/clientst0r/actions/workflows/codeql.yml) [![Docker image](https://github.com/agit8or1/clientst0r/actions/workflows/docker-image.yml/badge.svg)](https://github.com/agit8or1/clientst0r/actions/workflows/docker-image.yml)

[Screenshots](docs/screenshots.md) · [Quick Start](#quick-start) · [Documentation](#documentation) · [Releases](https://github.com/agit8or1/clientst0r/releases) · [Report a bug](https://github.com/agit8or1/clientst0r/issues/new?template=bug_report.yml)

</div>

---

[![The ClientSt0r dashboard for a managed client: quick actions, record counts, a site map with two mapped locations, and panels for the next seven days of scheduled work, outstanding tasks and website monitor status](docs/images/github/dashboard.png)](docs/images/github/dashboard.png)

## Why MSPs run it

**Documentation that sits next to the work.** A ticket opens with the client's active
contract, the asset it concerns, the runbook that covers it and the vault entries the
technician will need — without leaving the ticket or opening a second product. Secrets are
never rendered into the ticket page; opening one goes through the vault's own permissions
and is logged.

**A service desk you own, not one you rent.** Queues, SLA timers with pause logic, time
entries, quotes, invoices, contracts, projects, approvals and workflow rules are built in
and run on your server. Your ticket history and your client data stay in your database, on
your hardware, under your backup policy.

**One tenant per client, from day one.** Every asset, document, credential, location and
ticket belongs to an organization. Technicians switch client context in one click;
role-based membership decides who sees what. Multi-site clients, parent/child
organizations and per-client PSA settings are first-class, not bolted on.

## A closer look

### A ticket that already knows the customer

[![Ticket detail showing the client's active contract and hours used, an SLA countdown, internal and client-visible activity, the linked network asset, vault context listing five credentials by title and username with every secret hidden, and logged billable time](docs/images/github/ticket-detail.png)](docs/images/github/ticket-detail.png)

Contract and hours consumed, SLA countdown, client-visible replies separated from internal
notes, the linked asset, the credentials this job needs — listed by title and username, never
by secret — and the time logged against it, billable or not.

<table>
<tr>
<td width="33%" valign="top">
<a href="docs/images/github/tickets.png"><img src="docs/images/github/tickets.png" alt="Service desk queue listing nine tickets across four client organizations, with filters for client, status, priority, queue and assignee"></a>
<b>Service desk queue</b><br>Every client in one list, filtered by status, priority, queue or technician.
</td>
<td width="33%" valign="top">
<a href="docs/images/github/client-overview.png"><img src="docs/images/github/client-overview.png" alt="Client overview page for a logistics company showing company information, primary contact details and two mapped sites"></a>
<b>Client overview</b><br>Contacts, sites and the documentation stack for one customer.
</td>
<td width="33%" valign="top">
<a href="docs/images/github/vault.png"><img src="docs/images/github/vault.png" alt="Password vault listing nine credentials for one client with usernames and security status shown and every secret hidden"></a>
<b>Encrypted vault</b><br>AES-GCM at rest, per-entry access rules, reveals audited.
</td>
</tr>
</table>

[See the full tour — assets, knowledge base, runbooks →](docs/screenshots.md)

## Quick Start

### Docker (recommended)

Requires Docker Engine 24.0+ with the Compose v2 plugin, about 2 GB of disk for the image
and 1 GB for the database volume.

```bash
git clone https://github.com/agit8or1/clientst0r.git
cd clientst0r
cp .env.example .env
# edit .env — at minimum: SECRET_KEY, DB_PASSWORD, DB_ROOT_PASSWORD, APP_MASTER_KEY
docker compose up -d
```

Open `http://localhost:8000`. The entrypoint runs migrations and collects static files on
first boot; set `DJANGO_SUPERUSER_*` in `.env` and it creates the admin account too.
Pre-built images are published to `ghcr.io/agit8or1/clientst0r`.

Optional services are behind compose profiles:

```bash
docker compose --profile proxy up -d   # Nginx + TLS on 80/443
docker compose --profile cache up -d   # Redis (only if you switch CACHES to Redis)
```

Full guide: **[docs/docker.md](docs/docker.md)**.

### Native install on Ubuntu or Debian

Ubuntu 20.04+ / Debian 11+, 2 GB RAM (4 GB recommended), 10 GB free disk. The installer
adds Python 3.12, MariaDB, Gunicorn and the systemd units, generates the encryption keys,
runs migrations and starts the service.

```bash
git clone https://github.com/agit8or1/clientst0r.git && cd clientst0r && bash install.sh
```

It detects an existing installation and offers upgrade, system check or clean reinstall.
Full guide: **[INSTALL.md](INSTALL.md)**.

### First steps after install

1. Sign in and enrol 2FA — it is enforced for every account by default.
2. Create your first client organization under **Admin → Organizations**.
3. Turn the service desk on under **Admin → System → Settings → Feature Toggles** (`psa_enabled` is off by
   default, so the PSA menu stays hidden until you switch it on).

## Updating and backups

**Update** from **Admin → System → System Updates** in the web UI: *Check for Updates*, then *Apply*.
The apply step is a graceful reload — no manual service restart.

CLI fallback:

```bash
git pull && python manage.py migrate && sudo systemctl restart clientst0r-gunicorn.service
```

Under Docker, `docker compose pull && docker compose up -d`.

**Back up before every upgrade.** The bundled command writes the database and media to a
single archive:

```bash
python manage.py backup --output-dir /var/backups/clientst0r --encrypt --retention-days 30
```

Docker users: see [Backups](docs/docker.md#backups) for the volume-level equivalent.

## Supported versions and limitations

- Security fixes land on the current **3.17.x** line. See [SECURITY.md](SECURITY.md).
- **Single-server by design.** There is no clustered or multi-node deployment story; it
  targets one VM or one container host per MSP.
- **Self-hosted only.** There is no hosted service and no public demo instance — you run it.
- **The service desk is opt-in.** `psa_enabled` is off until an administrator turns it on.
- **AI-assisted features are optional** and gated behind `psa_ai_enabled`. Nothing calls an
  external model unless you enable it and supply a key.
- Third-party PSA and RMM integrations (ConnectWise, Autotask, HaloPSA, NinjaOne, Datto RMM,
  Syncro, Atera and others) are supported for teams that already run one — but the service
  desk here is native, not a front end for someone else's.

## Security

- Enforced TOTP 2FA, Argon2 password hashing, brute-force lockout, session timeouts.
- AES-GCM encryption at rest for vault entries, integration credentials and API keys.
- Per-entry vault access rules, approval and break-glass flows, audited reveals.
- Optional Azure AD / Entra ID SSO and LDAP / Active Directory authentication.
- CodeQL and dependency scanning run on every push to `main` and weekly.

**Found a vulnerability?** Please report it privately via
[GitHub Security Advisories](https://github.com/agit8or1/clientst0r/security/advisories/new)
rather than a public issue. Full policy and response timelines: [SECURITY.md](SECURITY.md).

## Documentation

| Guide | What it covers |
|---|---|
| [Installation](INSTALL.md) | Native install, upgrade, troubleshooting |
| [Docker](docs/docker.md) | Compose layout, profiles, backups, upgrades |
| [Features](FEATURES.md) | Full capability list by area |
| [Screenshots](docs/screenshots.md) | Complete visual tour |
| [Roadmap](docs/ROADMAP.md) | Shipped, in progress and planned phases |
| [Changelog](CHANGELOG.md) | Release history |
| [Integrations](docs/INTEGRATION_SETUP_GUIDE.md) | Connecting PSA, RMM, M365, accounting and distributors |
| [API](API_V2_GRAPHQL.md) | REST and GraphQL endpoints |
| [Security](SECURITY.md) | Policy, supported versions, reporting |
| [FAQ](docs/faq.md) | Common questions |
| [More docs](docs/README.md) | Everything else |

## Contributing

Issues and pull requests are welcome.

- **Bugs:** [open a bug report](https://github.com/agit8or1/clientst0r/issues/new?template=bug_report.yml)
- **Ideas:** [open a feature request](https://github.com/agit8or1/clientst0r/issues/new?template=feature_request.yml)
- **Code:** fork, branch, add a test in the relevant app's `tests.py`, run
  `python manage.py test <app>`, then open a PR. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Support

Questions and troubleshooting go in [GitHub Issues](https://github.com/agit8or1/clientst0r/issues)
or [Discussions](https://github.com/agit8or1/clientst0r/discussions).

## License

MIT — see [LICENSE](LICENSE). Use it, fork it, run it for your clients.

---

<div align="center">

If ClientSt0r saves you time, a ⭐ helps other MSPs find it.

<sub>Built by a small team and one German Shepherd. 🐕 Luna supervises.</sub>

</div>
