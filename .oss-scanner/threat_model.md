# Client St0r — threat model

Guidance for automated security review (Anthropic OSS Scanner). Read this
before starting; it describes what the project is, where untrusted input
enters, what we care about most, and how we rate severity.

## What this project is

Client St0r is a self-hosted, multi-tenant IT documentation platform and
service desk for managed service providers (MSPs). One deployment holds data
for many **client organizations**: asset inventory, runbooks, network configs,
tickets, invoices — and an **encrypted credential vault** containing the
passwords, TOTP seeds and API keys the MSP uses to administer every client's
infrastructure.

That last point drives the whole threat model: a single compromised instance
can hand an attacker administrative access to dozens of downstream networks.
Treat anything that leaks vault contents, crosses a tenant boundary, or yields
code execution on the host as the most serious class of bug.

- Stack: Python 3.12, Django 6, Django REST Framework, MariaDB in production
  (SQLite in this scanner image), gunicorn behind nginx, systemd timers for
  background jobs. Optional Docker Compose deployment.
- Deployments are usually internet-facing (technicians and client portal users
  reach it remotely).

## Actors and trust levels (least → most trusted)

1. **Anonymous internet user** — no session, no token.
2. **Holder of a share/capability token** — secure-note links, public status
   pages, CSAT survey links, quote-signing links, wallboard links, inbound
   webhook URLs, network-discovery collector tokens.
3. **Client-portal user** (`UserProfile.user_type = ORG_USER`) — a customer of
   the MSP. Must only see their own organization's portal data.
4. **Org member, read-only role** → **editor** → **admin** → **owner** of an
   organization (`accounts/models.py` roles + RoleTemplate flags). Membership is
   per-organization; org hierarchy lets parent orgs see descendants.
5. **MSP staff** (`user_type = STAFF`) — can switch between all orgs.
6. **Django `is_staff` / superuser** — instance administrator. Can run the
   updater, backups/restore, system settings. Superuser is trusted with the
   host *through intended features*, but must not get capabilities the UI
   does not intend (e.g. arbitrary shell beyond what a feature exposes).
7. **API clients** — REST API keys (`api/`), DRF tokens (`api_mobile/`),
   browser-extension tokens (`vault/extension_*`). Each acts as the user who
   owns it and must be bound by that user's org memberships and permissions.

## Security invariants we care about

- **Tenant isolation.** Users must never read or modify objects belonging to
  an organization they are not a member of (except STAFF / superuser). Scoping
  is done through `core/middleware.py` (current org), `core/tenancy.py`
  helpers and per-view checks. Every surface — HTML views, REST, mobile API,
  GraphQL, extension API, exports, search, reports, PDF/CSV generation,
  webhooks — must enforce it.
- **Vault confidentiality.** Plaintext credentials and TOTP seeds must only
  be revealed to users permitted by `vault/permissions.py` and
  `vault/access_rules.py` (per-entry permissions, IP/time access rules).
  Every reveal path must go through those checks and be audit-logged.
- **Authentication strength.** When `REQUIRE_2FA=True`, no password-only
  session or token should reach authenticated functionality. Login is
  rate-limited by django-axes.
- **Cryptography.** Vault data is encrypted with keys derived from
  `APP_MASTER_KEY` (`vault/encryption.py`, `vault/encryption_v2.py`; AES-GCM,
  HKDF per-purpose keys, AAD binding org/type/id in v2). Ciphertext must not
  be swappable between records/orgs, and keys must never reach logs, API
  responses, templates, or backups in plaintext.
- **No host compromise from the web tier** other than via deliberately
  superuser-only features.
- **Client IP trust.** `X-Forwarded-For` must only be honoured from
  `TRUSTED_PROXY_CIDRS` (`core/client_ip.py`) wherever the IP is used for a
  security decision (firewall, vault access rules, rate limits, audit trail).

## Where untrusted input enters

- **Unauthenticated HTTP**: login + 2FA (`two_factor`), Azure AD OAuth
  callback, mobile login/MFA (`api_mobile/views_auth.py`),
  `/health/`, public pages in `core/urls.py` (about, roadmap.json, consult and
  beta-signup forms), portal set-password links, CRM lead capture.
- **Token-gated URLs**: secure notes (`core/securenotes_views.py`), status
  pages (`statuspage/`), wallboard (`scheduling/`), CSAT (`psa/`), quote
  signing (`portal/`), and inbound webhooks: distributors (`integrations/`),
  PSA partners (`psa/`), vendor/SIEM alerts (`security_alerts/`),
  network-discovery collectors (`network_discovery/`), emergency restart
  (`core/views.py`).
- **Authenticated HTTP**: all app views, REST API (`api/`), mobile API
  (`api_mobile/`), browser-extension API (`vault/extension_views.py`), GraphQL
  (`api/graphql/`, only when the optional graphene dependency is installed).
- **File parsing**: uploads/attachments (`files/`), document import
  (PyMuPDF, DOCX XML — `docs/services/document_import.py`), spreadsheet and
  competitor-export imports (openpyxl, CSV — `imports/`), images (Pillow),
  backup restore archives (`vault`/`core` restore).
- **Rendered user content**: Markdown/HTML documents and KB articles sanitised
  with bleach (`docs/models.py`), inbound ticket email HTML
  (`psa/email_parsing.py`), any `|safe` / `mark_safe` in templates.
- **Data pulled from third parties** (treat as attacker-controlled): PSA/RMM
  sync responses (`integrations/`), IMAP mail polled into tickets
  (`psa/management/commands/psa_poll_email.py`), SSH output from network
  devices (`netconfig/`), monitored websites/certificates (`monitoring/`),
  LLM output (`psa_ai/`, `docs/services/llm_providers.py`) — LLM output is
  untrusted and must not drive privileged actions or be rendered unescaped.
- **Outbound request destinations chosen by users** (SSRF surface): webhook
  targets, integration base URLs, LLM/Ollama URLs, IMAP hosts, website
  monitors, import URLs. `core/safe_http.py` is the intended guard;
  private-network targets are allowed only when
  `ALLOW_PRIVATE_IP_INTEGRATIONS=True`.
- **Privileged operations triggered from the web UI**: the updater
  (`core/updater.py`), system package updates (`core/security_views.py`,
  `update_system_packages`), backups/restore, fail2ban, service restart —
  argument handling and who can trigger them both matter.

## Components that matter most / least

**Highest priority**: `vault/`, `accounts/` (auth, 2FA, Azure SSO, roles),
`core/` (middleware, tenancy, client_ip, safe_http, secure notes, updater,
backups, webhooks), `api/`, `api_mobile/`, `portal/`, `files/`,
`security_alerts/` and other inbound webhooks.

**High**: `psa/` (tickets, billing, email ingestion), `integrations/`,
`imports/`, `docs/`, `netconfig/`, `network_discovery/`, `psa_ai/`,
`statuspage/`, `crm/`.

**Lower but in scope**: `assets/`, `inventory/`, `locations/`, `vehicles/`,
`field_ops/`, `scheduling/`, `resourcing/`, `reports/`, `compliance/`,
`monitoring/`, `processes/`, `audit/`.

**Out of scope**:
- `venv/`, vendored third-party code under `static/` (JS/CSS libraries) —
  report upstream instead, unless our usage of it is the bug.
- Browser-extension client code (`clientst0r-extension/`) except where it
  reveals a server-side flaw.
- `scripts/`, `deploy/`, `install.sh`, `snap/` shell scripts run by the
  administrator by hand — only report if they create an exploitable
  condition on an installed system (e.g. world-writable files, secrets
  written with weak permissions).
- Findings that require `DEBUG=True` (unsupported in production).
- Missing hardening headers, verbose version strings, or rate limits on
  non-security-sensitive endpoints, with no demonstrated impact.

## How to exercise it

Everything is installed in `/src` and configured through a throwaway
`/src/.env` (random keys, SQLite, `DEBUG=False`, HTTPS redirect off).

- Full test suite: `python manage.py test --noinput`
- One app: `python manage.py test vault`
- Extra security tests: `python -m unittest discover -s security_tests`
- Run the server: `python manage.py createsuperuser` then
  `python manage.py runserver 127.0.0.1:8000`
- Create orgs/users in a shell: `python manage.py shell`
  (`core.models.Organization`, `accounts.models.Membership`).
- View tests bypass 2FA + HTTPS redirect with
  `@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)`;
  each app's `tests.py` defines its own `TEST_MIDDLEWARE`. Don't rely on that
  bypass when demonstrating an authentication finding — show it against the
  real middleware stack.
- External services (PSA/RMM APIs, LLMs, HIBP, SMTP/IMAP) are unavailable
  offline; mock them as the existing tests do.

## How we rate severity

Assume a default production install: internet-facing, `DEBUG=False`,
`REQUIRE_2FA=True`, behind the bundled nginx config.

**Critical**
- Unauthenticated (or capability-token-only) remote code execution, or any
  path to plaintext vault secrets / `APP_MASTER_KEY` without valid credentials.
- Authentication bypass to an arbitrary account, or a full 2FA bypass for
  password-holding attackers when 2FA is required.
- Low-privilege authenticated user (read-only member, portal user, API key
  holder) → RCE on the host or superuser.
- Cross-tenant read of vault secrets by any authenticated user.

**High**
- Cross-tenant read/write of non-vault data (assets, docs, tickets,
  invoices, configs) by an authenticated user.
- Privilege escalation within an org (read-only → admin/owner) or bypass of
  per-entry vault permissions / access rules within one's own org.
- Stored XSS reachable by low-privilege or external input (portal users,
  inbound email, PSA sync data, uploaded files served inline) that executes
  for staff/admins.
- SSRF that reaches internal networks or cloud metadata when
  `ALLOW_PRIVATE_IP_INTEGRATIONS=False`, or that returns response bodies.
- SQL injection reachable by any authenticated non-superuser.
- Cryptographic flaws that allow decrypting, forging, or swapping vault
  ciphertext.
- Command or argument injection reachable by `is_staff` users who are not
  superusers.

**Medium**
- Stored XSS that requires an admin to plant it, or that only affects the
  attacker's own org.
- Reflected XSS, CSRF on state-changing actions, open redirects usable in the
  login/OAuth flow.
- IP spoofing via `X-Forwarded-For` that defeats a security control (rate
  limit, vault IP rule, audit trail).
- Brute-forceable secrets or tokens (missing rate limit on a credential or
  capability check, non-constant-time comparison of secrets).
- Information disclosure of other users' metadata, internal paths, or
  configuration that materially aids a further attack.
- Superuser-only features that allow more than intended (e.g. arbitrary
  command execution through an option-injection in an admin tool).

**Low**
- Denial of service requiring authentication, or limited to the attacker's
  own org; resource exhaustion with high attacker cost.
- Missing audit logging on a sensitive action.
- Issues requiring a non-default insecure configuration.

Do not report: issues requiring an already-compromised superuser, host
access, or `DEBUG=True`; theoretical crypto weaknesses without a practical
attack; dependency CVEs that are not reachable from our code.

## How we'd like reports and patches

- One report per root cause. Group the same missing check across several
  views into one report and list every affected route/function.
- Include the exact route or function, the minimum role needed, and a
  reproducer — ideally a Django `TestCase` we can drop into the matching
  app's `tests.py`, using the real middleware stack where auth is involved.
- Patches should be minimal and match the existing style. Prefer fixing at a
  shared choke point (`core/tenancy.py`, `vault/permissions.py`,
  `core/client_ip.py`, `core/safe_http.py`) over per-view band-aids, and
  include a regression test.
