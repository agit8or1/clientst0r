# Managed Local ONLYOFFICE

Managed Local ONLYOFFICE is one more way to edit Office documents in clientst0r. clientst0r installs and runs one ONLYOFFICE Docs container on its own server and manages it: install, start, stop, restart, update, roll back and uninstall. The other ways keep working: an editor installed with `install-editor.sh` on this server or on a separate VM, an editor service that already runs, Collabora Online, and Microsoft 365.

It is **off by default**. A superuser turns it on in **Settings → Office Documents → Managed Local ONLYOFFICE**. A root administrator must first run a one-time setup on the server (see [Setup](#setup)).

> **Status: not verified against a real container.** Everything below is covered by unit and integration tests that use protocol models: a fake `docker` binary, a fake helper socket, and a fake ONLYOFFICE Docs server. The live suite and the browser checklist ([Live verification](#live-verification)) have **not been run**. Every release in the helper's list is marked `tested: False`, so the helper refuses to install any of them until the live checklist passes and a release is marked tested. The one exception is a disposable test VM whose root configuration sets `ALLOW_UNTESTED_RELEASES=yes`.

## Contents

- [Architecture](#architecture)
- [Networking](#networking)
- [Setup](#setup)
- [Operations](#operations)
- [Updates, rollback and the maintenance window](#updates-rollback-and-the-maintenance-window)
- [Backups and restore](#backups-and-restore)
- [Uninstall and purge](#uninstall-and-purge)
- [Recovery](#recovery)
- [Limitations](#limitations)
- [Vendor facts and sources](#vendor-facts-and-sources)
- [Licensing analysis (open questions for legal review)](#licensing-analysis-open-questions-for-legal-review)
- [Testing](#testing)
- [Live verification](#live-verification)

## Architecture

```
browser ──https──▶ host Nginx (office host name) ──▶ 127.0.0.1:BIND_PORT ──▶ container :80
clientst0r ──http──▶ 127.0.0.1:BIND_PORT  (health, command service, conversions)
container ──https──▶ bridge gateway:443 ──▶ host Nginx (clientst0r host name) ──▶ clientst0r
                      (document downloads, save callbacks; TLS verified)

clientst0r (app user) ──unix socket, fixed verbs──▶ clientst0r-office-helper (root)
                                                        └─▶ docker compose (project clientst0r-office)
```

- **The web app never touches Docker.** It has no Docker socket, is not in the `docker` group and gets no new sudo rule. It talks only to `/run/clientst0r-office/helper.sock`. That socket is owned by the app user with mode 0600 and is socket-activated, with one root process per connection. The helper checks the caller with `SO_PEERCRED`, allowing only root and the configured app user. It accepts one JSON request with a fixed verb:
  - queries: `preflight`, `status`, `releases`, `logs` (at most 500 lines, redacted) and `secret`;
  - lifecycle verbs: `install`, `start`, `stop`, `restart`, `update <release id from the list>`, `rollback` and `uninstall`.

  `purge` exists only on the root CLI. No verb takes an image name, a path, a command or a Docker option.
- **Why a separate helper instead of more verbs on the root helper.** Lifecycle operations take minutes (pull, graceful shutdown of up to 5 minutes, backup, first start). They must outlive a gunicorn reload or a scheduler restart. The Office service helper keeps a journal (`/var/lib/clientst0r-office/state/operation.json`) and a lock (`flock`), and runs inside a systemd sandbox. It is installed by `install-editor.sh --mode managed-local`. From then on the existing root helper replaces it at `self-update`, from the same SSH-signed release tag it uses for itself, so neither the app nor the repository alone can change what runs as root.
- **Background jobs.** A web request only queues a `ManagedOfficeOperation`. The scheduler (task `office_managed_operations`, every minute) runs `manage.py office_managed --run-pending`. The job:
  - takes a lease, with a heartbeat;
  - drains sessions where needed;
  - submits the verb once and stores the helper's operation id;
  - polls the helper;
  - then verifies the result.

  A conditional unique constraint allows only one active operation. A stale lease (the runner died) is taken over, and the stored helper id is polled again, never resubmitted. If the helper reports the operation as *interrupted* (helper killed or reboot), the job resubmits it, at most 3 times. Every helper verb converges to the same state, so a retry is safe.
- **Provider.** After `install`, `start`, `restart`, `update` and `rollback`, the job configures one `EditorInstance` with `mode='managed_local'`. It uses the existing ONLYOFFICE provider unchanged: JWT signing, callbacks with status 2 and 6, duplicate and stale save handling, quarantine, and revisions stored in clientst0r before the callback is acknowledged. The job reads the JWT secret from the helper straight into the encrypted field and never logs or shows it. Users can edit again only after a health check and a server-driven round trip (open, edit, save, reopen) pass.
- **Failure isolation.** If the helper or the container is unavailable, only the managed editor's controls and sessions are affected. The settings page shows "unreachable", and documents stay readable and downloadable from clientst0r's own storage.

## Networking

- **Host name.** The editor gets its own HTTPS host name, for example `office.example.com`. It must differ from clientst0r's: the editor's JavaScript runs on that origin, and a different origin keeps it out of clientst0r's cookies and CSP scope. A subpath (`/office/` on clientst0r's host) is **not supported**. The vendor's virtual-path proxy example is not version-specific, was not verified for 10.0, and would put the editor on clientst0r's origin.
- **Bind.** The container publishes `127.0.0.1:BIND_PORT:80` only (default 8090). It is never published on another interface.
- **The three paths and how they are checked** (Setup checks):
  1. Browser → ONLYOFFICE: `https://<office host>/` through the host Nginx. This is proven by the browser probe in the provider diagnostics (it loads `api.js` in an administrator's browser).
  2. clientst0r → ONLYOFFICE: `http://127.0.0.1:BIND_PORT/` (loopback health check, command service, conversions).
  3. ONLYOFFICE → clientst0r: `extra_hosts` maps clientst0r's host name to the bridge gateway, so the container reaches the host Nginx on 443 with clientst0r's real certificate. TLS is verified, with an optional private CA through `NODE_EXTRA_CA_CERTS`. This is proven by the conversion check: the container downloads a signed document URL from clientst0r.
- **Container egress firewall.** nftables table `inet clientst0r_office`, re-applied at boot before Docker. Traffic from the bridge `cs0office0` may reach only `gateway:443`; every other destination, forwarded or local, is dropped. Inside the container, `ALLOW_PRIVATE_IP_ADDRESS=true` is set so that it accepts the private gateway address, and the firewall narrows that to the one port. `ALLOW_META_IP_ADDRESS=false`. Plugins, the welcome page, the example app, metrics and (Enterprise) the admin panel are off, and WOPI is off.
- **clientst0r's SSRF exception.** `office.net` normally refuses loopback for remote editors. For `managed_local` it allows loopback **only on the managed instance's own two ports**: BIND_PORT for the internal URL, and 443 when the office host name resolves to this host. Every other loopback port, every other mode's rules, metadata and link-local addresses, and URLs off the approved origins are refused exactly as before.
- **Not verified, on purpose listed:**
  - whether Docker's embedded DNS (127.0.0.11) keeps working with the forward-drop rule;
  - whether `no-new-privileges` and the custom healthcheck work with this image;
  - whether prod's GeoIP allowlist (an app-level US-only rule) treats the bridge gateway's private address as LAN.

  The live checklist covers all three.

## Setup

1. DNS: point the office host name at this server, and have a certificate for it (or use `--tls certbot`).
2. As an administrator with sudo, copy the installer and the helper from this release's **signed tag** into a root-owned directory. Never run them from the app directory, which the app user can write. The Managed Local ONLYOFFICE page shows the exact commands for this server:

   ```
   git -C <app dir> -c gpg.ssh.allowedSignersFile=/etc/clientst0r/allowed_signers verify-tag vX.Y.Z \
     && sudo install -d -m 0700 /root/clientst0r-office-managed \
     && git -C <app dir> archive vX.Y.Z scripts/office deploy/office-helper | sudo tar -x -C /root/clientst0r-office-managed
   sudo bash /root/clientst0r-office-managed/scripts/office/install-editor.sh --provider onlyoffice \
     --mode managed-local --hostname office.example.com --clientstor-url https://clientstor.example.com/ \
     --deployment-id acme-prod --tls existing-cert --cert-file F --key-file F --preflight-only
   ```

   Then run the same command without `--preflight-only`, adding `--dry-run` first if you like. Options:
   - `--edition enterprise --license-file license.lic`
   - `--ca-file ca.pem` (clientst0r uses a private CA)
   - `--cpus`, `--memory-mb` (default 4096), `--reserve-mb` (default 2048, kept free for clientst0r)
   - `--bind-port`, `--subnet`
   - `--install-docker`

3. What the script does:
   - **Docker:** if it is present, it is used as it is. It is never replaced, reconfigured or restarted, and other containers are not touched. If Compose v2 is missing, the script stops and asks you to add it. If Docker is absent and you pass `--install-docker`, it installs `docker.io` and `docker-compose-v2` from the Ubuntu archive (Debian: install Docker yourself).
   - **nftables:** installed if missing.
   - **Config:** writes `/etc/clientst0r/office-service.conf` (keys documented in `deploy/office-helper/office-service.conf.example`).
   - **Helper:** installs `/usr/local/sbin/clientst0r-office-helper`, `clientst0r-office-helper.socket`, `clientst0r-office-helper@.service` and `clientst0r-office-firewall.service`, then starts the socket.
   - **Unattended upgrades:** keeps the container engine out of unattended-upgrades (`/etc/apt/apt.conf.d/51clientst0r-office-engine`).
   - **Nginx:** writes `/etc/nginx/sites-available/clientst0r-office-managed`, a dedicated server block with WebSockets, `X-Forwarded-*` headers, 3600 s timeouts, a 200 MB body limit, HSTS and nosniff. It runs `nginx -t` first and removes the block again if the test fails.
   - **Never:** pulls or starts a container.
4. In clientst0r, as a superuser, open Settings → Office Documents → Managed Local ONLYOFFICE. Turn it on, run **Setup checks** (preflight plus the three paths), then click **Install**.

The helper's preflight checks:
- OS (Ubuntu 22.04/24.04, Debian 12) and CPU architecture (x86_64; aarch64 with a warning);
- Docker and Compose v2, and nftables;
- memory (`MEMORY_MB + RESERVE_MB` must fit in RAM), swap, CPU (at least one core left for clientst0r) and disk (at least 10 GB; a warning below 40 GB);
- that the loopback port is free and that a proxy listens on 443;
- that the bridge subnet does not overlap the host's routes;
- DNS for both host names;
- that an installable release is in the list, and (Enterprise) the license file.

## Operations

All operations are superuser-only, CSRF-protected, audited (`office_event=managed_operation`) and queued as background jobs, with progress shown on the page:

| Action | Drain first | What the helper does | Verified after |
|---|---|---|---|
| Install / repair | no (users kept out) | pull by digest, check RepoDigests, render compose, `up`, wait healthy | health + round trip |
| Start | no | `up`, wait healthy | health + round trip |
| Stop | **yes** | `documentserver-prepare4shutdown`, then `compose stop` | instance closed to users |
| Restart | **yes** | prepare4shutdown, restart, wait healthy | health + round trip |
| Update | **yes** | pull new image **before** downtime, prepare4shutdown, stop, backup, `up` new, wait healthy; unhealthy → restore backup + old release automatically | health + round trip |
| Roll back | **yes** | needs `previous_release` and a backup from it; safety backup of current data, restore, `up` old | health + round trip |
| Uninstall | **yes** | prepare4shutdown, `compose down`; data, secrets and backups kept | instance closed to users |

**Drain.**
1. New sessions are blocked by disabling the instance.
2. A force-save is requested for every open edit group.
3. `office.drain.verify` asks the editor about every live session, including expired ones.

A group counts as safe in any of these cases:
- a save, or a "no changes" answer, arrived after the drain started;
- the editor never loaded the file;
- the command service says it no longer knows the key (`info` returns error 1); the group is then closed.

`getForgottenList` must also come back empty. If the editor cannot answer, or the forgotten list is non-empty, the result is **unknown**, never zero. After `OFFICE_MANAGED_DRAIN_SECONDS` (default 900) the operation is **postponed** and the editor is opened to users again. The helper's own `prepare4shutdown` runs only after the drain has been verified.

**Settings** (Django settings, all optional):
- `OFFICE_MANAGED_SOCKET`
- `OFFICE_MANAGED_LEASE_SECONDS` (300)
- `OFFICE_MANAGED_SLICE_SECONDS` (50)
- `OFFICE_MANAGED_DRAIN_SECONDS` (900)
- `OFFICE_MANAGED_POLL_SECONDS` (3)

CLI: `manage.py office_managed --status | --run-pending | --queue ACTION [--release R] [--user SUPERUSER]`.

**Package updates.** While `/etc/clientst0r/office-service.conf` exists:
- the root helper refuses `apt upgrade-packages` for `docker.io`, `docker-ce*`, `containerd*`, `runc` and the `docker-compose` packages;
- `apt upgrade` upgrades everything else (planned with `apt-get -s upgrade`);
- `update_system_packages` skips those packages too.

Upgrading the engine restarts `dockerd`, and with it the editor, without saving open documents first. To upgrade it: **Stop** the editor here, upgrade the engine from a root shell, then **Start** it.

## Updates, rollback and the maintenance window

- Updates are **manual by default**. The helper's release list is embedded in the helper program and pins each release to an image digest read from Docker Hub. Only releases marked `tested` are installable, unless `ALLOW_UNTESTED_RELEASES=yes` is set in the root config. Updates never cross editions (Community → Enterprise) or go to a lower version.
- **Maintenance window:** off by default. It needs **both** the app setting (Managed page → Update → maintenance window) **and** `MAINTENANCE_UPDATES=yes` in the root config. Inside the window the scheduler queues at most one update per release per 12 hours. The update drains like a manual one, and is postponed if the drain cannot be verified.
- A clientst0r update never updates or restarts the editor. A new helper version, installed by the root helper's self-update, takes effect at the next socket connection, and an operation that is already running finishes on the old code.

## Backups and restore

The helper takes a backup with the container **stopped**: before every update (`pre-update`) and before every rollback (`pre-rollback`). Backups are written to `/var/lib/clientst0r-office/backups/<id>.tar.gz` with a manifest giving the release, digest and reason.

| Path | What | Back up? |
|---|---|---|
| clientst0r database + `MEDIA_ROOT/office/` | **all documents and revisions** (the source of truth) | yes, as today |
| `/etc/clientst0r/office-service.conf`, `/etc/clientst0r/office/` | config, JWT and secure-link secrets (0600), license, private CA | yes, root-only |
| `/var/lib/clientst0r-office/data/` | editor working data: cache, logs, fonts; Enterprise: PostgreSQL, RabbitMQ, Redis | optional; rebuildable except unsaved "forgotten" files |
| `/var/lib/clientst0r-office/backups/` | the helper's pre-update/rollback backups | optional |

Restoring a host: restore clientst0r as usual. Then restore the two `/etc/clientst0r` paths, run the setup again (it keeps an existing config) and click Install. Users' documents never depend on the container's data.

## Uninstall and purge

- **Uninstall** (Managed page, typed confirmation) drains and then runs `compose down`. clientst0r documents, editor data, secrets and backups are all kept, and the instance is closed to users.
- **Purge** deletes the editor data, secrets and backups. It is a separate root-only step and is never available over the socket: `sudo clientst0r-office-helper cli purge --confirm <DEPLOYMENT_ID>`, which works only after Uninstall.
- **Removing the setup** (helper, units, firewall table, Nginx block, config): `sudo bash .../install-managed-local.sh --remove-units`, after Uninstall (and Purge, if wanted). It refuses while the container runs.

## Recovery

| Symptom | What to do |
|---|---|
| "Helper unreachable" | `systemctl status clientst0r-office-helper.socket`; `journalctl -u 'clientst0r-office-helper@*'`. Rerun the setup if the socket is missing. |
| Operation stuck in "running" | The job polls the helper's journal. `sudo clientst0r-office-helper cli status` shows the helper's own view. A journal left `running` with a free lock is marked *interrupted* and retried, at most 3 times. |
| Update failed | The helper already restored the pre-update backup and the old release. If health still fails, use **Roll back**, or `sudo clientst0r-office-helper cli rollback`. |
| Postponed operation | Read the pending list in the progress panel. Ask users to close their editors, recover any "forgotten" files (`manage.py office_sessions`), then retry. |
| Container won't start after reboot | `systemctl status clientst0r-office-firewall docker`; `sudo clientst0r-office-helper cli status`; Diagnostics (redacted logs). |
| Out of memory (`oom_killed`) | Raise `MEMORY_MB` in the root config if RAM allows, then Restart. |

## Limitations

- Complex formatting, unusual fonts, embedded objects and macros may not round-trip perfectly between formats. Macros are disabled by the provider, and only the image's fonts are available (custom fonts: `/usr/share/fonts/truetype/custom` in the data mount, untested).
- External data: images inserted by URL, linked data and plugins that fetch from the internet are **blocked by the egress firewall**. Plugins are disabled.
- One editor per deployment, on the same server as clientst0r. It needs at least 4 GB for the editor on top of clientst0r's own needs. The development and production VM (4 vCPU, 7 GB RAM) would leave about 1 GB for everything else with the defaults, so a separate editor VM is still the better choice for busy installations.
- Community edition: the vendor's connection limits apply; clientst0r does not hardcode or bypass any limit.
- arm64 images exist but are untested here.

## Vendor facts and sources

All sources were read on 2026-11-12. Digests come from `registry-1.docker.io` manifests and the Docker Hub tags API.

- **Images and digests** (`docker.io/onlyoffice/documentserver` and `documentserver-ee`; Docker Hub tags API at `https://hub.docker.com/v2/repositories/onlyoffice/documentserver/tags/` and `.../documentserver-ee/tags/`):

  | Image | Tag | Digest | Note |
  |---|---|---|---|
  | `documentserver` | `10.0.0` | `sha256:ca17889f10b11141cc6441836aebdd2835cf3e1b49681b2fd6e155c94b7850b3` | |
  | `documentserver` | `9.4.0` | `sha256:e3da62a847b9a5d51a11f73cfea1d9c13c3be3809614490d4edddcf01dcf919b` | not in the list: older than the 10.0 security fixes |
  | `documentserver-ee` | `10.0.0` | `sha256:0c55eb69253012b37e1b0e6f1224e917cb9ba49f317017ac1ee2e52c4d53d666` | **re-pushed 2026-11-09: tags are mutable**, which is why the helper pins and checks digests |
  | `documentserver-ee` | `10.0.2` | `sha256:ca396233b27a2ad19bb2f1eaff32ff1efff9b95114564b4e716613e73e993c0f` | |

- **Resources:**
  - Docker README (https://github.com/ONLYOFFICE/Docker-DocumentServer, `README.md` on master): recommended RAM 4 GB or more, dual-core 2 GHz, swap at least 2 GB, 2 GB of disk.
  - Linux install page (https://helpcenter.onlyoffice.com/docs/installation/docs-community-install-ubuntu.aspx): minimum RAM 2 GB, HDD 40 GB, swap 4 GB.
- **Image environment** (README and `run-document-server.sh` on master):
  - JWT: `JWT_ENABLED`, `JWT_SECRET`, `JWT_HEADER`, `JWT_IN_BODY`.
  - Defaults: `WOPI_ENABLED` (default false), `ALLOW_PRIVATE_IP_ADDRESS`, `ALLOW_META_IP_ADDRESS`, `SECURE_LINK_SECRET`.
  - `PLUGINS_ENABLED`: the plugins manager fetches plugins from the network.
  - Pages: `WELCOME_PAGE_ENABLED`, `EXAMPLE_ENABLED`, `ADMINPANEL_ENABLED` (Enterprise).
  - `NODE_EXTRA_CA_CERTS` (default `/var/www/onlyoffice/Data/certs/extra-ca-certs.pem`), `GENERATE_FONTS`.
  - `IP_FILTER_RULES` does not take CIDR ranges, which is why the network rule is enforced with nftables instead.
- **Volumes:** `/var/log/onlyoffice`, `/var/lib/onlyoffice`, `/var/www/onlyoffice/Data` and `/usr/share/fonts/truetype/custom`. Enterprise bundles PostgreSQL, RabbitMQ and Redis and upgrades its database on start. Enterprise license: `license.lic` in the mounted Data folder.
- **Health:** the image's HEALTHCHECK is `curl http://127.0.0.1/healthcheck`, which returns `true`.
- **Graceful shutdown:** `docker exec <container> documentserver-prepare4shutdown`, which "may take a long time (up to 5 minutes)" (README). `run-document-server.sh` also calls it on SIGTERM, so the helper sets `stop_grace_period: 6m`.
- **Proxy:** https://helpcenter.onlyoffice.com/installation/docs-community-proxy.aspx, and the vendor's `document-server-proxy` repository (AGPL-3.0; `nginx/proxy-https-to-http.conf`, `nginx/proxy-to-virtual-path.conf`). clientst0r's Nginx block was written independently and does not copy those files.
- **Command service** (`info`, `forcesave`, `getForgottenList`): https://api.onlyoffice.com/docs/docs-api/additional-api/command-service/

## Licensing analysis (open questions for legal review)

**This is not a legal opinion, and it does not conclude that the setup is compliant.** The facts:

- ONLYOFFICE Docs (`ONLYOFFICE/DocumentServer`), the Docker packaging (`ONLYOFFICE/Docker-DocumentServer`) and `document-server-proxy` are AGPL-3.0, according to their `LICENSE` files on master. The DocumentServer license adds Additional Terms under AGPL §7:
  - keep the notices;
  - mark modified versions;
  - keep the UI legal notices identifying ONLYOFFICE;
  - no trademark license;
  - CC BY-SA 4.0 for non-code content.
- The trademark policy (https://www.onlyoffice.com/trademark-policy) could not be read: the page renders with JavaScript. Its terms are **unverified**.
- clientst0r is MIT-licensed. It does not ship, modify or rebuild the image. The helper pulls the vendor's published image by digest and runs it unmodified, configured only through the documented environment variables. The editor's own branding and legal notices are left as they are.
- Enterprise is used only with the customer's own `license.lic`. clientst0r neither implements nor bypasses connection limits.

Open questions:
1. **AGPL §13 (network use).** clientst0r now *operates* an AGPL program for its users over a network. Is offering the vendor's unmodified Corresponding Source (the GitHub repositories at the image's version) enough? Does the deployment need a visible source offer beyond the editor's own About notice?
2. **Configuration as modification.** Is the generated `compose.yaml` (environment, disabled plugins, welcome and admin pages, mounts, limits) "modifying" the work under the Additional Terms? Does turning the plugins off count as removing features that must be marked?
3. **Derivative-work boundary.** Does installing and lifecycle-managing the container from an MIT application change the analysis already noted in `docs/office/ONLYOFFICE.md` ("Licensing")?
4. **Trademark.** Is naming the feature "Managed Local ONLYOFFICE" and labelling buttons with the vendor's name nominative use under the policy?
5. **Proxy example.** The vendor's proxy configuration is AGPL. clientst0r's Nginx block was written independently. Should counsel review it for similarity?
6. **Fonts.** Do the image's bundled fonts (for example Microsoft core fonts and their EULA) impose terms on the operator of a hosted service?
7. **Enterprise.** Do the Enterprise license terms allow the deployment pattern of one VM per customer managed by a third-party application, and do they restrict automated install, update or rollback?

## Testing

```
manage.py test office.test_managed_helper      # the helper as a program, fake docker on PATH (31)
manage.py test office.test_managed             # IPC, SSRF rule, provisioning, jobs, drain, views (47)
manage.py test office.test_managed_installer   # install-managed-local.sh on a fake host (10)
manage.py test core.tests.test_root_helper     # engine guard + office-helper self-update
```

These prove that the code follows the documented protocols. They do **not** prove that a real container behaves the same.

## Live verification

**Automated harness:** `scripts/office/live/run_live_checks.py` runs the browser and lifecycle checks below automatically, on a live install (the default local profile) or on a disposable VM, and is the evidence `mark-tested` needs to mark a release tested. See [LIVE_VERIFICATION.md](LIVE_VERIFICATION.md). It is built on the development branch and has not been run against a real editor yet.

Status: **NOT RUN**. It needs a disposable Ubuntu 24.04 VM with at least 4 vCPU, 8 GB RAM and 40 GB disk, Docker, a DNS name and certificate for both host names, clientst0r installed, and `ALLOW_UNTESTED_RELEASES=yes` until a release is marked tested.

**Automated, opt-in:** `office/test_managed_live.py`. Run it on the VM as the app user:

```
OFFICE_E2E_MANAGED_HOST=office.test.example OFFICE_E2E_MANAGED_DISPOSABLE=yes \
  [OFFICE_E2E_MANAGED_UPDATE_TO=<release id>] python manage.py test office.test_managed_live
```

It runs these steps in order:
1. Preflight passes.
2. Install: digest pinned, healthy, instance configured.
3. Loopback-only publish.
4. All setup checks pass, including ONLYOFFICE → clientst0r and HTTPS.
5. Restart, then a round trip.
6. Update and rollback, if a second release in the same compat group exists. Today, Community has only 10.0.0, so this step needs a second release first.
7. Stop, then start.
8. Uninstall keeps data and secrets.

**Root checks (manual):**
- [ ] `docker inspect clientst0r-office-ds`: `Privileged=false`, `SecurityOpt` has `no-new-privileges`, only the four bind mounts, no Docker socket, `RestartPolicy=unless-stopped`, memory and CPU limits set, json-file logs at 10m × 3, image `…@sha256:<digest from the list>`.
- [ ] `ss -ltnp`: the port is bound to 127.0.0.1 only.
- [ ] From inside the container (`docker exec … curl`): `https://<clientst0r host>/` works with TLS verified. `http://<gateway>:8000`, `http://169.254.169.254/` and `https://example.com/` all fail. DNS inside the container still resolves (embedded DNS with the forward drop).
- [ ] After a reboot: the firewall table exists before the container starts, and the container comes back healthy.
- [ ] `apt upgrade` through Settings → Updates leaves docker.io, containerd and runc untouched.
- [ ] Kill the helper mid-update (`systemctl kill 'clientst0r-office-helper@*'`): the operation is marked interrupted, then retried and completed.
- [ ] Update to a release that never becomes healthy (point a test list at a broken digest): the backup and old release are restored automatically.
- [ ] Purge after uninstall removes data, secrets and backups. Purge over the socket is refused.

**Browser (manual; Playwright is not installed in this project):**
- [ ] Open a .docx, .xlsx and .pptx as an editor user. The editor loads from `https://<office host>/`, and the CSP allows only that origin.
- [ ] Two users co-edit; WebSockets stay connected for at least 10 minutes behind Nginx.
- [ ] Edit, close the tab, and a new revision appears (status 2). Force-save gives status 6.
- [ ] Start **Restart** with a document open and unsaved. The page drains: the save arrives first, then the restart. The user sees the editor reconnect or close, and no edit is lost.
- [ ] Keep a document open with no network to clientst0r (drop 443 for the bridge). Start **Stop**: the operation is postponed and the editor is reopened.
- [ ] A reader can only view, a user from another organization gets 403, and a portal user cannot reach the Managed page.
- [ ] Settings page: status, resources, progress panel updating, history, diagnostics download (redacted; no JWT, no `md5=` or `token=` values).
