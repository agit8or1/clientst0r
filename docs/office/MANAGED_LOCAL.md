# Managed local editor (ONLYOFFICE Docs or Collabora CODE)

The managed local editor is one more way to edit Office documents in clientst0r. clientst0r installs and runs **one** editor container on its own server and manages it: install, start, stop, restart, update, roll back, uninstall, switch engine and switch address layout. Two engines are available, one at a time:

- **ONLYOFFICE Docs** ("Managed Local ONLYOFFICE"), Community or Enterprise;
- **Collabora Online Development Edition** ("Managed Local Collabora (CODE)"), for **evaluation, development, home use and small teams**. Collabora does not recommend CODE for production. For production, use a licensed Collabora Online server through the existing external Collabora provider ([COLLABORA.md](COLLABORA.md)).

Which engines this server may run is root-owned configuration (`ENGINES=`); the app only picks between those engine ids. The other ways keep working: an editor installed with `install-editor.sh` on this server or on a separate VM, an editor service that already runs, external ONLYOFFICE or Collabora Online (WOPI), and Microsoft 365.

It is **off by default**. A superuser turns it on in **Settings → Office Documents → Managed local editor**. A root administrator must first run a one-time setup on the server (see [Setup](#setup)).

> **Status: not verified against a real container.** Everything below is covered by unit and integration tests that use protocol models: a fake `docker` binary, a fake helper socket, fake `nginx`/`systemctl`/`openssl` binaries, and fake ONLYOFFICE Docs and Collabora servers. The Collabora engine, the reverse-proxy setup and the capacity checks shipped in v3.17.671 and have not been run on a real host yet (see [Not yet verified live](#not-yet-verified-live)). The live suite and the browser checklist ([Live verification](#live-verification)) have **not been run**. Every release in the helper's list is marked `tested: False`, so the helper refuses to install any of them until the live checklist passes and a release is marked tested. The one exception is a disposable test VM whose root configuration sets `ALLOW_UNTESTED_RELEASES=yes`.

## Contents

- [Architecture](#architecture)
- [Networking](#networking)
- [Setup](#setup)
- [Engines](#engines)
- [Collabora CODE engine](#collabora-code-engine)
- [Address layouts and the reverse proxy](#address-layouts-and-the-reverse-proxy)
- [Capacity](#capacity)
- [Switching engine or layout](#switching-engine-or-layout)
- [Enabling managed Collabora on a server behind upstream TLS](#enabling-managed-collabora-on-a-server-behind-upstream-tls)
- [Automation interface (helper verbs, commands, jobs)](#automation-interface-helper-verbs-commands-jobs)
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
  - queries: `preflight [engine]`, `status`, `releases`, `logs` (at most 500 lines, redacted), `secret`, `proxy-status`, `proxy-install <host name>`, `proxy-remove` and `callback-check`;
  - lifecycle verbs: `install [engine]`, `start`, `stop`, `restart`, `update <release id from the list>`, `rollback`, `uninstall` and `set-layout <dedicated|same-host>`.

  `purge` exists only on the root CLI. No verb takes an image name, a path, a command, a Docker option, an Nginx directive or environment. The only scalar arguments are an engine id, a layout id, a release id from the compiled list, a line count, and a host name that must equal the one the root configuration assigns to the current layout.
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

- **Host name.** The editor gets its own HTTPS host name, for example `office.example.com`. It must differ from clientst0r's: the editor's JavaScript runs on that origin, and a different origin keeps it out of clientst0r's cookies and CSP scope. For ONLYOFFICE a subpath (`/office/` on clientst0r's host) is **not supported**: the vendor's virtual-path proxy example is not version-specific, was not verified for 10.0, and would put the editor on clientst0r's origin. For Collabora an opt-in **same-host** layout exists (see [Address layouts](#address-layouts-and-the-reverse-proxy)); a dedicated host name stays the recommended default.
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

**From Settings (servers with the root helper, the default for native installs).** Managed local editor → **Set up this server**: pick the engine and the address layout, accept the same-host warning if you use it, and choose whether releases that are not live-verified yet may be installed. Settings only records the request. Within a minute the scheduler starts `manage.py office_managed --host-setup-run` in its own process, which calls the root helper:

- `clientst0r-root-helper office-setup ENGINE LAYOUTS CLIENTSTOR_HOST DEPLOYMENT_ID OFFICE_HOST|- tested|untested` runs `scripts/office/install-editor.sh --mode managed-local` from the signed release tag the root helper itself was installed from (its own mirror, the signature checked again), never from the app directory. TLS is always `upstream` and the app user comes from `/etc/clientst0r/root-helper.conf`. Docker is installed only if absent. Once the office service is configured, its clientst0r host name and deployment id can only be changed from a root shell.
- For the same-host layout, `clientst0r-root-helper office-site-include on` adds the include line before each active `location / {` in the one enabled Nginx site that serves clientst0r (the one that names the app directory), runs `nginx -t`, puts the file back if that fails, and reloads Nginx. `off` removes the lines it added.

clientst0r's host name is the one the request came in on. The output is shown on the page, and the request and the result are audited. On success managed local editing is turned on; then run Setup checks and Install as below. Other TLS modes (a certificate on this server, certbot) and installs without the root helper use the shell commands below.

**From a shell (any install).**

1. DNS: point the office host name at this server (or at the TLS device in front of it), and have a certificate for it: on this server (`--tls existing-cert`, `--tls certbot`) or on the device in front (`--tls upstream`). Collabora's same-host layout needs no new name or certificate.
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
   - `--provider onlyoffice|collabora` (the engine installed first), `--engines onlyoffice,collabora` (which engines the app may choose between; default: the provider)
   - `--layouts dedicated[,same-host]` (Collabora only for same-host; the first one is used at install), `--hostname` (optional when the layouts are only same-host)
   - `--tls existing-cert --cert-file F --key-file F` | `--tls certbot --certbot-email E` | `--tls upstream [--callback-upstream-ip IP]` (TLS ends on a device in front of this server; the IP defaults to what clientst0r's host name resolves to)
   - `--collabora-memory-mb` (default 1536), `--collabora-cpus` (default 1.5), `--collabora-bind-port` (default 9981)
   - `--allow-untested-releases` (writes `ALLOW_UNTESTED_RELEASES=yes`; needed for Collabora until a CODE release is live-verified)
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
   - **Nginx:** creates `/etc/nginx/clientst0r-office/` (the helper's sandbox cannot create directories under `/etc`), then calls `clientst0r-office-helper cli proxy-install <host>`. The helper writes only its own files (see [Address layouts](#address-layouts-and-the-reverse-proxy)), runs `nginx -t`, reloads, and restores the previous files if anything fails. With `--tls certbot` it first installs an ACME-only block, runs `certbot certonly --webroot`, then installs the full block. With `--tls existing-cert` the certificate and key are copied to `/etc/clientst0r/office/tls/` (key 0600), the only directory besides `/etc/ssl` and `/etc/letsencrypt/live` the helper accepts. For the same-host layout the script prints the one `include` line to add to clientst0r's site; it never edits that site.
   - **Never:** pulls or starts a container, edits clientst0r's own Nginx site, or replaces an existing Docker.
4. In clientst0r, as a superuser, open Settings → Office Documents → Managed local editor. Turn it on, pick the engine, run **Setup checks** (preflight, capacity, reverse proxy, the three paths), then click **Install**.

Re-running the script with new options (for example `--layouts same-host,dedicated --hostname office.example.com` later) rewrites the root configuration and keeps data, secrets and the installed container.

The helper's preflight checks:
- OS (Ubuntu 22.04/24.04, Debian 12) and CPU architecture (x86_64; aarch64 with a warning);
- Docker and Compose v2, and nftables;
- capacity for the chosen engine (see [Capacity](#capacity)): memory, available memory, CPU, swap; disk (at least 10 GB; a warning below 40 GB);
- that the loopback port is free and that a proxy listens on 443 (or on 80 with `PROXY_TLS=upstream`), that `nginx` and `openssl` are installed;
- the callback route (`CALLBACK_ROUTE`, and `CALLBACK_UPSTREAM_IP` is set for `upstream`);
- that the bridge subnet does not overlap the host's routes;
- DNS for both host names;
- that an installable release is in the list, and (Enterprise) the license file.


## Engines

| | ONLYOFFICE Docs | Collabora CODE |
|---|---|---|
| Image | `docker.io/onlyoffice/documentserver[-ee]` by digest | `docker.io/collabora/code` by digest |
| Compose project / container | `clientst0r-office` / `clientst0r-office-ds` | `clientst0r-office-cool` / `clientst0r-office-cool` |
| Loopback port | `BIND_PORT` (8090) → 80 | `COLLABORA_BIND_PORT` (9981) → 9980 |
| Default limits | `MEMORY_MB` 4096, `CPUS` | `COLLABORA_MEMORY_MB` 1536, `COLLABORA_CPUS` 1.5 |
| Provider | ONLYOFFICE (JWT from the helper) | Collabora WOPI (proof keys required) |
| Address layouts | dedicated | dedicated or same-host |
| Health (host side) | `/healthcheck` | `/hosting/discovery` |
| Graceful stop | `documentserver-prepare4shutdown` | SIGTERM, `stop_grace_period` 120 s |
| Data volumes / backups | data, logs, lib, fonts | none (stateless; documents live in clientst0r) |

Only one engine is installed at a time. `install` refuses while the other one is installed; the app's **Switch engine** operation drains, uninstalls the old one (data, secrets and backups kept), installs the new one and verifies it. Per-engine install records live in `/var/lib/clientst0r-office/state/installed-<engine>.json`.

## Collabora CODE engine

- **Image and releases.** `COLLABORA_RELEASES` in the helper pins `docker.io/collabora/code` by digest (edition `code`, compat group `code-26.04`). Every entry is `tested: False`, so installing needs `ALLOW_UNTESTED_RELEASES=yes` until the live checklist passes. Digests were read on 2026-11-13 from `registry-1.docker.io` (`Docker-Content-Digest`) and cross-checked with the Docker Hub tags API:

  | Release id | Digest |
  |---|---|
  | `26.04.5.2.1-code` | `sha256:c7415b963e32eb0986a562583f154d36d3d7a461e1ddfb660a95e87094328acb` |
  | `26.04.6.1.1-code` | `sha256:95f29f1c0a1778999125f53f058d968fe0afb37c95e32ebfb9f3444140faebd2` |

- **Configuration** (generated compose, from validated root config only): `aliasgroup1=https://<clientst0r host>:443` is the WOPI allow-list, so the editor accepts documents only from this deployment; `server_name` is the public editor host (dedicated name, or clientst0r's host for same-host); `DONT_GEN_SSL_CERT=1`, `ssl.enable=false`, `ssl.termination=true` (TLS ends at Nginx or upstream); `net.content_security_policy` sets `frame-ancestors https://<clientst0r host>`; the admin console and macros are off; `net.proto=IPv4`, `num_prespawn_children=1`, `logging.level=warning`.
- **Secrets.** The admin password and the WOPI proof key are generated by the helper. The password stays root-only in `/etc/clientst0r/office/` (`collabora-admin.secret`, `collabora.env`, 0600; the admin console itself is off). The proof key (`/var/lib/clientst0r-office/collabora/proof_key`, 0400, owned by the container's uid 1001) is mounted read-only into the container. Both are covered by the log redaction. The app never sees either; the Collabora instance's `shared_secret` gets a random placeholder because the generic instance checks expect one, and `provider_options.require_proof=True` makes the WOPI host verify the proof signature on every request.
- **Container hardening.** Loopback-only port, `mem_limit = memswap_limit`, `pids_limit` 2048, json-file logs 10m × 3, `cap_drop: NET_RAW`, no Docker socket, no host paths besides the proof key. `no-new-privileges` is **not** set: `coolforkit-caps` needs its file capabilities (`cap_fowner`, `cap_chown`, `cap_sys_chroot`) to set up document jails. The image has no `curl`, so the health check runs from the host.
- **Firewall.** The same nftables table: the container may reach only clientst0r over HTTPS (`gateway:443`, or `CALLBACK_UPSTREAM_IP:443` with `CALLBACK_ROUTE=upstream`).
- **Auto-configuration.** After a verified install, start, update, rollback, engine switch or layout switch, the job creates or updates one `EditorInstance(provider='collabora', mode='managed_local')`, enables the `collabora` provider, makes the instance the default only if there was none or the default was the other managed instance, and closes the other managed instance. External instances are never changed.
- **Verification.** Collabora edits through a browser WebSocket, so the server-driven round trip cannot run the edit step. Verification requires: no failed step, discovery and session pass, and at least one WOPI step passes.

## Address layouts and the reverse proxy

| Layout | Public address | Nginx file (the helper's own) | When |
|---|---|---|---|
| `dedicated` (recommended) | `https://<OFFICE_HOSTNAME>/` | `/etc/nginx/sites-available/clientst0r-office-managed` + `sites-enabled` link | both engines |
| `same-host` (opt-in) | `https://<clientst0r host>/browser/…` | `/etc/nginx/clientst0r-office/same-host.conf` | Collabora only |

`PROXY_LAYOUTS=` in the root config lists the layouts this server allows; the first one is used at install.

**Which include option, and why.** For same-host, the administrator adds **one line**, once, inside the server block that serves clientst0r:

```
include /etc/nginx/clientst0r-office/same-host.conf;
```

The helper manages only that snippet file and never edits clientst0r's site (on prod `/etc/nginx/sites-enabled/itdocs.conf`, detected read-only by `proxy-status`). The snippet always exists (empty when the layout is not active), so the include keeps passing `nginx -t` after a layout switch, an uninstall or `--remove-units`. The alternative (the helper inserting the include into the site file) was rejected: it would make a root program rewrite a file it does not own.

**What the helper renders.**
- Collabora locations: `^~ /browser/`, `^~ /hosting/discovery`, `^~ /hosting/capabilities`, the WebSocket `~ ^/cool/(.*/)?ws$` (Upgrade, 36000 s timeouts) and `~ ^/(cool|lool)/`, all to `127.0.0.1:COLLABORA_BIND_PORT`. Blocked with 403: `/cool/getMetrics`, `/cool/adminws`, `/browser/dist/admin`. `access_log off` on these paths because the WOPI access token is in the URL.
- On every editor location: `proxy_set_header Cookie ""`, `proxy_set_header Authorization ""`, `proxy_hide_header Set-Cookie`, `X-Content-Type-Options nosniff`, `Referrer-Policy`. Because these locations define `add_header`, they do not inherit the server-level `X-Frame-Options: DENY`; the frame restriction comes from Collabora's own CSP `frame-ancestors https://<clientst0r host>`.
- Dedicated site: the Collabora locations plus `location / { return 404; }` (ONLYOFFICE: everything to the container, with the WebSocket map). TLS: `PROXY_TLS=upstream` → listens on 80 only (TLS on the device in front; no local certificate); `local-cert` / `letsencrypt` → 80 redirects to 443, 443 with the certificate, HSTS. `letsencrypt` without the certificate yet → an ACME-only block for the webroot challenge.
- Safety: the helper refuses to overwrite a file without its marker, refuses a `server_name` another enabled site already serves, backs up its files, writes, runs `nginx -t`, reloads, and puts the backup back (and does not reload) on any failure.

**Origin-sharing risk (same-host).** With same-host, Collabora's front-end JavaScript runs on clientst0r's own origin. A cross-site-scripting flaw in the editor front-end would then run with clientst0r's origin: it could read pages a signed-in user can read and act as that user. Mitigations in place: Cookie and Authorization are stripped before requests reach the editor, Set-Cookie is dropped from its replies, the editor may only be framed by clientst0r, the admin console and metrics are blocked, and the editor paths are not logged. These reduce, but do not remove, the risk. The Managed page shows this warning, and switching to same-host requires an explicit checkbox that is recorded (`same_host_acknowledged_at/by`) and audited. Prefer a dedicated host name as soon as DNS and TLS allow it.

**Setup checks for the proxy** (Managed page → Setup checks): DNS for the editor host (points here, or at the TLS device), certificate (valid and matching, checked on this server; for `upstream` it is proven by the verified HTTPS check), the helper's Nginx files installed and current, the include line present (same-host), and the three reachability paths: browser → editor (browser probe), clientst0r → editor (loopback health check), editor → clientst0r (`callback-check`: a TLS handshake with verification from inside the container).

## Capacity

The helper computes a verdict per engine from `/proc/meminfo` and the CPU count (`status.capacity`, `preflight`):

- **fail** if `MemTotal < limit + RESERVE_MB`, if `MemAvailable − limit < 1024 MB`, or if fewer than 1 CPU would stay for clientst0r;
- **warn** if `MemAvailable − limit < RESERVE_MB` (2048), if fewer than 2 CPUs would stay, or if there is no swap (ONLYOFFICE: less than 2 GB);
- `install` **refuses** on fail. The Managed page shows each engine's verdict, its limits and a recommendation.

Sizing used: Collabora sizes about 1 vCPU per 15 active users and 50 MB RAM per active user (openDesk's scaling guide, citing Collabora's technical documentation); ONLYOFFICE recommends 4 GB RAM, dual-core 2 GHz and 2 GB swap for the Docker image.

| Host | ONLYOFFICE Docs (4096 MB) | Collabora CODE (1536 MB, 1.5 CPU) |
|---|---|---|
| 4 vCPU, 7 GB RAM, about 4 GB available (prod-like) | **fail**: only about 0.5 GB would be left; use a separate VM | **warn** (no swap): fits, about 2.5 GB stay free, 2.5 CPUs stay; roughly 15 active users |
| 8 vCPU, 16 GB RAM | pass | pass |

## Switching engine or layout

Both are supported operations; neither loses documents.

- **Switch engine** (Managed page → Engine and capacity → type `switch`; or `manage.py office_managed --queue switch_engine --engine collabora --user <superuser>`): drain → `uninstall` (data, secrets and backups kept) → `install {"engine": …}` → configure the new provider instance, close the old one → verify. If the drain cannot be verified the operation is postponed and nothing is uninstalled. If the install fails, both managed instances stay closed and external editors keep working; switch back or fix and retry.
- **Switch layout** (Managed page → Address and reverse proxy; or `manage.py office_managed --queue set_layout --layout same-host --accept-same-host --user <superuser>`):
  1. drain open sessions;
  2. the helper's `set-layout` rewrites its Nginx files for the new layout (`nginx -t`, reload, restore on failure), then re-creates the container with the new `server_name` (no image pull, no reinstall, data kept);
  3. the job updates the provider's browser URL and verifies;
  4. run **Setup checks** again.

  A dedicated layout needs `OFFICE_HOSTNAME` and `dedicated` in `PROXY_LAYOUTS`; add them by re-running the installer with `--layouts same-host,dedicated --hostname <name>`. If the editor is not running, the layout is saved and used at the next Start.

## Enabling managed Collabora on a server behind upstream TLS

For a host like prod: 4 vCPU, 7 GB RAM (about 4 GB available), no Docker, Nginx on :80 only with `server_name _;` (`/etc/nginx/sites-enabled/itdocs.conf`, proxy to gunicorn, sets `X-Forwarded-Proto`), TLS terminated on an upstream device that clientst0r's host name resolves to. Start with same-host, move to a dedicated name later.

1. **Back up** clientst0r as usual (database and `MEDIA_ROOT`).
With the root helper (prod has it), steps 2–4 are one click: Managed page → **Set up this server** → Collabora CODE, same host, accept the warning and allow untested releases. Otherwise from a shell:

2. **Copy the installer from the signed tag** (Managed page → Server setup shows the exact commands).
3. **Preflight, then dry run, then install** (Docker is installed only with `--install-docker`, and an existing Docker is never replaced):
   ```
   sudo bash /root/clientst0r-office-managed/scripts/office/install-editor.sh --provider collabora \
     --mode managed-local --layouts same-host --clientstor-url https://huduglue.agit8or.net/ \
     --deployment-id <id> --tls upstream --allow-untested-releases --install-docker --preflight-only
   ```
   Then the same with `--dry-run`, then without either. `--tls upstream` sets `CALLBACK_ROUTE=upstream` and takes `CALLBACK_UPSTREAM_IP` from what `huduglue.agit8or.net` resolves to (here 184.175.206.231); pass `--callback-upstream-ip` to choose another address. The editor container may reach only that address on 443.
4. **Add the include line once** inside the `server { … }` block of `/etc/nginx/sites-enabled/itdocs.conf`, then `sudo nginx -t && sudo systemctl reload nginx`:
   ```
   include /etc/nginx/clientst0r-office/same-host.conf;
   ```
   It must be in clientst0r's server block. The snippet's `^~` prefix locations win over `location /` wherever the line is; if the block has its own regex locations (`location ~ …`; prod's has none), put the include before them so the editor's WebSocket regex is matched first. The rendered snippet, wrapped in a prod-like server block, passes `nginx -t` syntax checking with nginx 1.24.
5. **Upstream device:** nothing to change for same-host (it already forwards `huduglue.agit8or.net` to this server's :80). The container must be able to reach `https://huduglue.agit8or.net` through the device (hairpin); `callback-check` tests that.
6. In clientst0r: **Settings → Office Documents → Managed local editor** → Turn on → Engine: Collabora CODE (Select) → Address and reverse proxy: read the same-host warning → **Setup checks** (capacity warn for no swap is expected; include line present; callbacks pass) → **Install** → **Run browser probe**.
7. Open a document from a file's "Edit in office" menu.

**Later, a dedicated host name** (for example `office.agit8or.net`):
1. DNS: an A record to the upstream device; on the device, a TLS certificate for the name and a rule forwarding it to this server's :80 (like `huduglue.agit8or.net`).
2. Re-run the installer with `--layouts same-host,dedicated --hostname office.agit8or.net` (same other options). Nothing is reinstalled.
3. Managed page → Address and reverse proxy → **Switch to the dedicated host name** (drains, rewrites the proxy, re-creates the container, updates the provider's URL), then **Setup checks** and the browser probe.
4. Optionally remove `same-host` from `--layouts` and the include line from `itdocs.conf` (the snippet file is then empty; leaving the include is harmless).

**Other installs** with TLS on this server: `--layouts dedicated --hostname office.example.com --tls existing-cert --cert-file F --key-file F` or `--tls certbot --certbot-email E`; `CALLBACK_ROUTE=gateway` (the container reaches this server's Nginx on the bridge gateway).

## Automation interface (helper verbs, commands, jobs)

For scripts and the live-verification harness. Everything goes through these; nothing else is supported.

**Root CLI** (`sudo clientst0r-office-helper cli <op> [arg]`, JSON on stdout, exit code 1 with a message on stderr on failure):

| Op | Arg | Sync/async | Result |
|---|---|---|---|
| `status` | – | sync | `config` (incl. `engine`, `layout`, `browser_url`, `internal_url`, `engines`, `layouts`, `engine_layouts`, `engine_memory_mb`, `engine_cpus`, `proxy_tls`, `callback_route`), `installed` (incl. `engine`), `container`, `capacity` (`host`, per engine `verdict/checks/recommendation`), `proxy`, `operation` |
| `preflight` | `onlyoffice`/`collabora` | sync | `checks: [{key, status, detail}]` |
| `releases` | – | sync | both release lists, installability |
| `install` | `onlyoffice`/`collabora` (when nothing is installed) | async | journal; refuses if the other engine is installed or capacity fails |
| `start`, `stop`, `restart`, `rollback`, `uninstall` | – | async | journal |
| `update` | release id | async | journal; refuses other-engine releases |
| `set-layout` | `dedicated`/`same-host` | async | journal; `result.recreated` |
| `proxy-status` | – | sync | `hostname`, `layout`, `tls`, `files`, `installed`, `include_line`, `include_present`, `clientstor_site`, `dns`, `certificate`, `preview` |
| `proxy-install` | host name (must equal the current layout's host) | sync | `layout`, `note` |
| `proxy-remove` | – | sync | – |
| `callback-check` | – | sync | `ok`, `target`, `route`, `detail` |
| `logs` | 1..500 | sync | redacted log |
| `purge --confirm <DEPLOYMENT_ID>` | – | root only, after uninstall | – |

Async ops print the reply, then block until done and print the journal (`/var/lib/clientst0r-office/state/operation.json`: `id, op, args, state, step, error, result`). One operation at a time (`flock` on `/run/clientst0r-office/operation.lock`).

**Root config keys** (`/etc/clientst0r/office-service.conf`, see `deploy/office-helper/office-service.conf.example`): `ENGINES`, `PROXY_LAYOUTS`, `PROXY_TLS`, `PROXY_CERT_FILE`, `PROXY_KEY_FILE`, `PROXY_MAX_BODY_MB`, `CALLBACK_ROUTE`, `CALLBACK_UPSTREAM_IP`, `COLLABORA_BIND_PORT`, `COLLABORA_CPUS`, `COLLABORA_MEMORY_MB`, plus the existing keys. Only root edits it (or re-runs the installer).

**App side:**
- `manage.py office_managed --status` (refresh and print the helper status), `--run-pending` (advance the active operation; the scheduler task `office_managed_operations` runs it every minute), `--queue ACTION [--release R] [--engine E] [--layout L --accept-same-host] --user <superuser>`. Actions: `install`, `start`, `stop`, `restart`, `update`, `rollback`, `uninstall`, `switch_engine`, `set_layout`.
- Jobs: `ManagedOfficeOperation` (`action`, `state`: queued/draining/running/verifying/succeeded/failed/postponed/cancelled, `target_release`, `target_engine`, `target_layout`, `progress`, `result`, `error`). `ManagedOfficeService` (`enabled`, `engine`, `instance`, `status` cache, `same_host_acknowledged_at/by`).
- Settings: `OFFICE_MANAGED_SOCKET`, `OFFICE_MANAGED_LEASE_SECONDS`, `OFFICE_MANAGED_SLICE_SECONDS`, `OFFICE_MANAGED_DRAIN_SECONDS`, `OFFICE_MANAGED_POLL_SECONDS`.
- Web (superuser, CSRF): `POST /office/settings/managed/engine/` (`engine`, `confirm=switch`), `.../layout/` (`layout`, `accept_same_host=1`), `.../proxy/` (`action=install&hostname=` or `action=remove&confirm=remove`), `.../probe/` (`outcome=reached|failed|timeout`). Audit: `object_type=office.managed`; browser probe `office_event=browser_probe`.

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
| Switch engine | **yes** | `uninstall` the old engine (data kept), `install` the new one | health + round trip, provider reconfigured |
| Switch layout | **yes** | rewrite the helper's Nginx files, re-create the container with the new public name | health + round trip, provider URL updated |

For Collabora, "prepare4shutdown" is a SIGTERM with a 120 s grace period, after the drain has confirmed that every edit is stored.

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
- One editor per deployment, on the same server as clientst0r. ONLYOFFICE needs at least 4 GB for the editor on top of clientst0r's own needs; on a 4 vCPU / 7 GB host the capacity check refuses it (use a separate VM). Collabora CODE fits there with its default limits (see [Capacity](#capacity)).
- Collabora CODE is for evaluation, development, home use and small teams. It shows Collabora's development-edition notices; any usage limits CODE applies are Collabora's and are not changed here. Production: a licensed Collabora Online server through the external provider.
- Collabora editing needs a browser WebSocket: the automatic verification after an operation cannot exercise the edit step; the browser probe and a manual edit do.
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

- **Collabora CODE** (sources read 2026-11-13):
  - Product page https://www.collaboraonline.com/code/: CODE "is perfect for testing, home use or small teams, but not recommended for production environments"; "Free to test – sandbox environment for testing and development".
  - Image: Docker Hub `collabora/code` (tags API `https://hub.docker.com/v2/repositories/collabora/code/tags/`), digests above.
  - Image build: `CollaboraOnline/online`, `docker/from-source-gh-action/` (Dockerfile and `start-collabora-online.sh`: `coolwsd --use-env-vars`, env `aliasgroup1`, `server_name`, `DONT_GEN_SSL_CERT`, `username`/`password`, `extra_params`; port 9980; user 1001) and `docker/cool-seccomp-profile.json`.
  - Sizing: https://docs.opendesk.eu/operations/scaling/ (1 vCPU per 15 active users, 50 MB RAM per active user, 1 Mbit/s per 10 active users), which cites Collabora's technical documentation.
  - The Collabora SDK site (`sdk.collaboraonline.com`, including the proxy settings page and the coolwsd configuration reference) sits behind a bot check and **could not be read** here. The proxy paths (`/browser`, `/hosting/discovery`, `/hosting/capabilities`, `/cool/` with its WebSocket) and the `--o:` option names used in the compose file follow Collabora's documented layout as known from the repository and earlier documentation, and are **unverified against the current SDK pages**. The live checklist covers them.

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

**Collabora CODE.** Facts: the Collabora Online sources (`CollaboraOnline/online`) carry MPL-2.0 headers (for example `docker/from-source-gh-action/start-collabora-online.sh`); the underlying LibreOffice core is MPL-2.0. clientst0r pulls the published `collabora/code` image by digest and runs it unmodified, configured only through its documented environment and `--o:` options. Open questions:

8. **CODE terms of use.** Collabora positions CODE as not for production. Are there terms beyond the source licenses (for example on the CODE download page, the image, or in-product notices) that restrict operating it for a business's own staff or for an MSP's customers? Not found on the pages that could be read; **unverified**.
9. **Image contents.** The image bundles third-party components (fonts, dictionaries, LibreOffice core). Do any of them impose terms on a hosted operator?
10. **Trademark.** "Collabora", "Collabora Online" and "CODE" are Collabora Productivity's marks. Is naming the feature "Managed Local Collabora (CODE)" and showing the engine's name in the UI nominative use? The CODE label is shown with an "evaluation / development" badge and a pointer to licensed Collabora Online.
11. **Same-host layout.** Not a licensing question but a risk acceptance: the operator accepts that the editor front-end runs on clientst0r's origin (recorded and audited).

## Testing

```
manage.py test office.test_managed_helper            # the helper as a program, fake docker on PATH
manage.py test office.test_managed_collabora_helper  # Collabora engine, nginx rendering/validation, capacity,
                                                     # layouts, callback route, input injection
manage.py test office.test_managed                   # IPC, SSRF rule, provisioning, jobs, drain, views
manage.py test office.test_managed_collabora         # engine switch, layout switch, Collabora provisioning,
                                                     # proxy views, browser probe, setup checks, command
manage.py test office.test_managed_installer         # install-managed-local.sh on a fake host
manage.py test core.tests.test_root_helper     # engine guard + office-helper self-update
```

These prove that the code follows the documented protocols. They do **not** prove that a real container behaves the same.

## Live verification

**Automated harness:** `scripts/office/live/run_live_checks.py` runs the browser and lifecycle checks below automatically, on a live install (the default local profile) or on a disposable VM, and is the evidence `mark-tested` needs to mark a release tested. See [LIVE_VERIFICATION.md](LIVE_VERIFICATION.md). It shipped in v3.17.671 and has not been run against a real editor yet.

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

### Not yet verified live

Shipped in v3.17.671 and covered by tests with fakes only:

- the Collabora CODE container itself: start-up with the generated `--o:` options, `aliasgroup1` enforcement, the mounted proof key being used (`/etc/coolwsd/proof_key`), file capabilities with `cap_drop: NET_RAW`, the host-side discovery health check, SIGTERM shutdown within 120 s;
- Nginx: the rendered blocks on a real `nginx -t`, WebSocket upgrade through `/cool/…/ws`, Collabora's `/browser` paths loading in the same-host layout next to clientst0r's `location /`, header stripping not breaking the editor;
- the upstream callback route: the container reaching `https://<clientst0r host>` through the TLS device (hairpin) with verification; Docker's embedded DNS with the forward-drop rule;
- capacity numbers on a real host under load (the 1536 MB / 1.5 CPU defaults are an estimate from the published sizing);
- the browser probe across the upstream device;
- engine and layout switches end to end, including the provider's browser URL change for users with an editor open.

The live harness (`scripts/office/live/`, developed separately) drives these through the [Automation interface](#automation-interface-helper-verbs-commands-jobs).
