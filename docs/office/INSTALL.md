# Installing and running an Office editor

clientst0r opens Word, Excel and PowerPoint files in a separate editor service:
ONLYOFFICE Docs or Collabora Online. This page covers installing that editor,
connecting it, and running it: firewalls, certificates, health checks, backups,
upgrades, switching providers and uninstalling.

The editor holds only working copies. Every saved version is stored by
clientst0r (`MEDIA_ROOT/office/revisions/…`). Nothing you do to the editor host,
including uninstalling it, deletes a document or a version.

> **Status.** The installer and the commands below have automated tests that
> run them against a fake host (stubbed `apt-get`, `systemctl`, `nginx`,
> `curl`; real `gpg` with the vendors' real public keys). They have **not** been
> run on a real Ubuntu 24.04 or Debian 12 machine, and no editor has been
> installed with them yet. Before relying on them, do the
> [manual verification](#manual-verification) on a test VM.

## Contents

- [Choosing where the editor runs](#choosing-where-the-editor-runs)
- [The installer](#the-installer)
- [Same server](#same-server)
- [Separate server](#separate-server)
- [Network paths and ports](#network-paths-and-ports)
- [Firewall rules](#firewall-rules)
- [Private addresses and a private CA](#private-addresses-and-a-private-ca)
- [Reverse proxy](#reverse-proxy)
- [Health checks and logs](#health-checks-and-logs)
- [Backup and recovery](#backup-and-recovery)
- [Upgrades](#upgrades)
- [Draining sessions](#draining-sessions)
- [Switching provider](#switching-provider)
- [Uninstalling](#uninstalling)
- [Manual verification](#manual-verification)
- [Appendix: Docker](#appendix-docker)
- [Sources and unverified points](#sources-and-unverified-points)

## Choosing where the editor runs

| | Separate VM (recommended) | Same server as clientst0r |
|---|---|---|
| Isolation | Editor process cannot read clientst0r's `.env`, database or media | Separate service user, but shares the host |
| Resources | Sized for the editor alone | Needs headroom: the preflight adds 2 cores, 2 GB RAM, 10 GB disk for clientst0r |
| Nginx | Its own | Shares clientst0r's Nginx; one extra server block |
| Host name | `docs.example.com` | Must be dedicated: never clientst0r's own host name |

Editions:

- **ONLYOFFICE Docs Community** (`onlyoffice-documentserver`), pinned to
  **10.0.0-169**. clientst0r refuses anything older than 10.0.0, which fixed an
  SSRF in the WOPI endpoints and a macro-sandbox bypass. 9.4 removed the old
  20-connection limit; clientst0r assumes no limit and records the detected
  version. The Community edition must keep ONLYOFFICE's branding.
- **Collabora Online Development Edition (CODE)** (`coolwsd` 26.04.6.1-1 +
  `code-brand` 26.04.6-1). Collabora describes it as for evaluation, testing,
  home use and small teams, *not recommended for production*.
- **Collabora Online** (licensed). Needs your subscription repository URL and
  the exact package versions from it.

## The installer

`scripts/office/install-editor.sh` runs **as root on the editor host**.
clientst0r never runs it. Settings → Integrations → Office Documents → Install
guidance prints the exact commands for your setup, with no secret in them.

```
install-editor.sh --provider onlyoffice|collabora-code|collabora-online
                  --mode same-server|separate-server
                  --hostname docs.example.com
                  --clientstor-url https://clientstor.example.com
                  [--clientstor-ip 192.0.2.10]      # default: resolved from --clientstor-url
                  [--ca-file /root/clientst0r-ca.pem]   # CA of clientst0r's certificate
                  [--tls existing-cert|certbot|none-behind-proxy]
                  [--cert-file F --key-file F]      # default /etc/ssl/clientst0r-office/<host>.crt|.key
                  [--certbot-email you@example.com]
                  [--version V] [--brand-version V]
                  [--repo-url-file /root/collabora-repo-url]   # collabora-online
                  [--accept-mscorefonts-eula]       # onlyoffice
                  [--app-user U]                    # same-server: owner of the import file
                  [--no-import-file] [--accept-low-resources]
                  [--dry-run] [--preflight-only]
install-editor.sh --upgrade --version V [--brand-version V] [--confirm-drained]
install-editor.sh --uninstall [--purge-state] [--dry-run]
install-editor.sh --health-check
```

Run these in order: `--preflight-only` (checks only), `--dry-run` (prints every
action and changes nothing; it does download the signing key to a temporary
directory to check its fingerprint), then the real install.

### What it does

1. **Preflight**
   - OS: Ubuntu 22.04/24.04 or Debian 12, amd64. ONLYOFFICE's install page
     names Debian 12 and Ubuntu 18.04 "or other compatible distribution", but
     not 24.04, so 24.04 gives a warning. Collabora's own supported-platform
     list could not be read, so Collabora always gives a "check it" warning.
   - CPU, RAM, swap and free disk on `/var`:
     - ONLYOFFICE: its published minimum is 2 cores, 2 GB RAM, 4 GB swap and
       40 GB disk.
     - Collabora: clientst0r's own floor of 2 cores, 4 GB RAM and 10 GB disk.
       Collabora's published figures were not verified.
     - Same-server adds headroom for clientst0r. A shortfall fails the check
       and recommends a separate VM. `--accept-low-resources` turns that into
       a warning.
   - Ports:
     - the editor's own port (ONLYOFFICE 8083, Collabora 9980) must be free;
     - 80 and 443 must be served by Nginx or by nothing.
   - Nginx: lists its sites and detects clientst0r's own site. That is any
     file that proxies to `clientst0r_app` or `gunicorn.sock`, or names
     clientst0r's host. The installer refuses when:
     - the editor host name is served by clientst0r's site or by any other site;
     - the editor host name equals clientst0r's host name.
   - Conflicting packages:
     - ONLYOFFICE: the Enterprise and Developer editions;
     - Collabora: `loolwsd`, and the other brand package;
     - both editors on one host gives a warning;
     - so does `apache2`.
   - Running containers are listed.
   - DNS: the editor host name, and clientst0r's address. That address is
     the only private address the editor may fetch from.
   - TLS material.
2. **Repository**
   - Downloads the signing key over HTTPS.
   - Requires exactly one primary key, and checks its fingerprint against the
     pinned one:
     - ONLYOFFICE `E09C A29F 6E17 8040 EF22 B409 8320 CA65 CB2D E8E5`;
     - Collabora `7EB1 5308 18B7 6832 8448 3B7B D891 5E45 6E7C 440E`.
   - On a mismatch it stops before anything is written.
   - The key goes to `/etc/apt/keyrings/clientst0r-office-<provider>.gpg`.
     The source in `/etc/apt/sources.list.d/clientst0r-office-<provider>.*`
     is `signed-by` that keyring only.
3. **Pinning**
   - `/etc/apt/preferences.d/clientst0r-office-<provider>.pref` pins the exact
     version with `Pin-Priority: 1001`.
   - The vendor repository gets priority 100, so it can never replace a
     distribution package.
   - The packages are `apt-mark hold`. A plain `apt upgrade`, unattended
     upgrades and clientst0r's own package updates leave the editor alone (see
     [Upgrades](#upgrades)).
4. **Secret**
   - 256 random bits are written to `/etc/clientst0r-office/secret`
     (root, 0600). The secret is never printed and never placed on a command
     line.
   - ONLYOFFICE gets it through debconf on stdin before the package installs,
     so the service never runs with the vendor's default secret.
   - The installer refuses `--secret` on the command line.
5. **Configuration**: see the [ONLYOFFICE](#onlyoffice-configuration) and
   [Collabora](#collabora-configuration) sections below.
6. **Nginx**
   - Writes one server block for the editor host:
     `/etc/nginx/sites-available/clientst0r-office-<host>.conf` plus its
     `sites-enabled` link (or `conf.d/` on hosts without `sites-available`).
   - HTTP on port 80 redirects to HTTPS, apart from the ACME challenge path.
   - HTTPS on 443 has WebSocket upgrade and long timeouts.
   - Runs `nginx -t` before the reload. If the test fails, it restores the
     previous file and stops.
7. **Import file** (unless `--no-import-file`)
   - `/var/lib/clientst0r-office-import/import-<host>.env`, mode 0600.
   - Same-server: owned by the clientst0r app user (`--app-user`, or `APP_USER`
     from `/etc/clientst0r/root-helper.conf`). Separate server: owned by root.
   - Holds the provider, the three URLs and the secret.
8. **Health check, then the values to enter**
   - Checks the editor on loopback, the editor through Nginx with its
     certificate verified, and that this host reaches `<clientstor-url>/health/`.
   - Prints the values to enter in clientst0r:
     - Browser URL
     - Internal URL
     - Callback URL
     - where the secret is

### ONLYOFFICE configuration

The installer edits `/etc/onlyoffice/documentserver/local.json`. It keeps the
file's owner and mode, and never edits `default.json`.

| Key | Value |
|---|---|
| `services.CoAuthoring.token.enable.browser`, `.request.inbox`, `.request.outbox` | `true` |
| `services.CoAuthoring.secret.{browser,inbox,outbox}.string` | the generated secret |
| `services.CoAuthoring.secret.session.string` | a separate random value |
| `services.CoAuthoring.token.{inbox,outbox}.header` | `Authorization` |
| `services.CoAuthoring.request-filtering-agent.allowPrivateIPAddress` | `false` |
| `services.CoAuthoring.request-filtering-agent.allowMetaIPAddress` | `false` |
| `services.CoAuthoring.request-filtering-agent.allowIPAddressList` | `[<clientst0r IP>]` |
| `storage.fs.secretString` | random; replaces the published default |
| `aiSettings.enable` | `false` |

Notes:

- The request-filtering agent stays on. Only clientst0r's own address is
  allowed, instead of switching on every private address.
- **Plugins, macros and AI in the editor** are switched off per document by
  clientst0r's editor configuration (`customization.plugins`, `macros`,
  `macrosMode`, `ai.disabled`). `local.json` has no verified server-wide
  switch for plugins or macros. Bundled plugins removed with
  `documentserver-pluginsmanager.sh` come back after an upgrade, so the
  installer does not remove them.
- **Private CA**: `--ca-file` installs the CA into the system store
  (`update-ca-certificates`). It also adds `NODE_EXTRA_CA_CERTS` as a systemd
  drop-in to every installed `ds-*` unit (see
  [Private addresses and a private CA](#private-addresses-and-a-private-ca)).
- **Service units**: the unit names after 9.4's single-process consolidation
  are unverified, so the installer acts on whatever `ds-*.service` units exist.

### Collabora configuration

The installer edits `/etc/coolwsd/coolwsd.xml`. It keeps the file's comments,
owner and mode.

| Key | Value |
|---|---|
| `storage.wopi.alias_groups` | `mode="groups"`, one group holding only `https://<clientst0r host>:<port>` |
| `ssl.enable` | `false` |
| `ssl.termination` | `true` (TLS ends at Nginx) |
| `net.listen` | `loopback` |
| `net.content_security_policy` | `frame-ancestors <clientst0r origin>;` |
| `net.lok_allow` | present but empty: no external data sources |
| `net.post_allow` | loopback plus clientst0r's address |
| `security.enable_macros_execution` | `false` |
| `admin_console.enable` | `false` |
| `ai.enabled` | `false` |
| `storage.ssl.ca_file_path` | `/etc/coolwsd/clientst0r-office-ca.pem`, with `--ca-file` |

The installer also runs `coolconfig generate-proof-key` if
`/etc/coolwsd/proof_key` is missing.

About the secret for Collabora: Collabora shares no secret with clientst0r.
Requests are signed with the proof key published in discovery. clientst0r's
instance form still requires a value, so the installer generates one for
clientst0r's own use.

## Same server

1. Point a dedicated host name (e.g. `docs.example.com`) at this server and get
   a certificate for it. Put it at `/etc/ssl/clientst0r-office/<host>.crt` and
   `.key`, or use `--tls certbot`.
2. Copy the installer from this release's **signed tag** rather than running
   it from the app directory. The app user can write to that directory, and
   you are about to run the script as root:

   ```
   git -C /home/administrator -c gpg.ssh.allowedSignersFile=/etc/clientst0r/allowed_signers \
       verify-tag v3.17.NNN && \
   git -C /home/administrator show v3.17.NNN:scripts/office/install-editor.sh \
       | sudo install -m 0700 -o root -g root /dev/stdin /root/clientst0r-install-editor.sh
   ```

3. Run it: preflight, dry run, then the install.

   ```
   sudo bash /root/clientst0r-install-editor.sh --provider onlyoffice --mode same-server \
       --hostname docs.example.com --clientstor-url https://clientstor.example.com/ \
       --tls existing-cert --app-user administrator --preflight-only
   …same with --dry-run…
   …same with --accept-mscorefonts-eula…
   ```

4. Import the secret as the app user:

   ```
   sudo -u administrator /home/administrator/venv/bin/python /home/administrator/manage.py \
       office_setup --import-secret /var/lib/clientst0r-office-import/import-docs.example.com.env
   ```

   This creates a **disabled** instance from the file and shreds the file. To
   set the secret on an existing instance instead, add `--instance N`.
5. In clientst0r, run the instance's Health check, Diagnostics and round-trip
   test, then enable the instance.

For ONLYOFFICE on the same server, the internal URL may be
`http://127.0.0.1:8083/`. The form accepts plain http only for loopback on a
same-server instance. Collabora is always reached by its browser address,
because its discovery builds URLs from the request host.

The installer never edits clientst0r's Nginx site, its app directory or any
`.env`. Every write is checked against those paths and refused if it would
touch them.

## Separate server

1. Create an Ubuntu 22.04/24.04 or Debian 12 VM with a DNS name on your LAN or
   VPN.
2. Download the installer from the release tag and check its SHA-256. The
   install guidance page shows the exact `curl … && sha256sum -c` command. If
   the checksum does not match, your clientst0r is not on a release build:
   `scp` the file from the clientst0r server instead.
3. On the VM, run `--preflight-only`, then `--dry-run`, then the install, with
   `--mode separate-server`.
4. Move the import file to clientst0r and remove it from the VM:

   ```
   scp root@docs.example.com:/var/lib/clientst0r-office-import/import-docs.example.com.env ./office-import.env
   chmod 600 ./office-import.env
   ssh root@docs.example.com shred -u /var/lib/clientst0r-office-import/import-docs.example.com.env
   ```

   The file must be owned by the user who runs the import.
5. On clientst0r, run
   `manage.py office_setup --import-secret ./office-import.env` as the app user.
6. Apply the firewall rules below. Then run the Health check, Diagnostics and
   round-trip test, and enable the instance.

## Network paths and ports

| Path | From → to | Port | What |
|---|---|---|---|
| Browser → editor | users' browsers → `https://docs.example.com` | 443/tcp (HTTPS + WebSocket) | Editor JS, the editing session |
| Editor → clientst0r | editor host → clientst0r's callback URL | 443/tcp | ONLYOFFICE: download the file and post the save callback. Collabora: WOPI CheckFileInfo/GetFile/PutFile/Lock |
| clientst0r → editor | clientst0r → the editor's internal or browser URL | 443/tcp (or loopback 8083 for same-server ONLYOFFICE) | Health check, discovery, ONLYOFFICE command service (force-save), saved-file download, conversion |

The editor's own ports stay internal and are reached only through Nginx:
ONLYOFFICE on 8083 (DEB/RPM default since 10.0), Collabora on 9980. Port 80 is
needed only for the HTTP→HTTPS redirect and Let's Encrypt.

## Firewall rules

Separate editor VM (ufw). Replace the networks with yours:

```
ufw default deny incoming
ufw default allow outgoing
ufw allow from 10.0.0.0/16 to any port 443 proto tcp       # users' browsers
ufw allow from 192.0.2.10 to any port 443 proto tcp        # clientst0r server
ufw allow from 10.0.5.0/24 to any port 22 proto tcp        # your admin network
# only with --tls certbot (Let's Encrypt HTTP challenge):
# ufw allow 80/tcp
ufw deny 8083/tcp                                          # ONLYOFFICE's own port, Nginx proxies it
ufw deny 9980/tcp                                          # Collabora's own port (coolwsd listens on loopback anyway)
ufw enable
```

On the clientst0r server, allow the editor to reach clientst0r:

```
ufw allow from <editor VM IP> to any port 443 proto tcp
```

If your outbound traffic is filtered, the editor VM needs HTTPS to the vendor
repository for installs and upgrades: `download.onlyoffice.com`, or
`www.collaboraoffice.com` and `collaboraoffice.com`.

For the same server, add a rule that keeps 8083/9980 off the network:
`ufw deny 8083/tcp`.

## Private addresses and a private CA

The two directions are trusted separately.

**clientst0r trusting the editor.** If the editor's certificate is issued by
your private CA, paste that CA certificate into the instance's **CA bundle**
field. clientst0r verifies TLS against it. Verification can never be switched
off from the web UI. `office/net.py` fetches only from the configured editor
host and pins its DNS answer. A private editor address is allowed because you
approved it on that instance; SSRF protection is not disabled globally.

**The editor trusting clientst0r.** If clientst0r's certificate is from a
private CA, pass that CA to the installer with `--ca-file`:

- the CA is installed into the system trust store;
- ONLYOFFICE also gets `NODE_EXTRA_CA_CERTS`, because Node.js does not read the
  system store. This is standard Node.js behaviour, but ONLYOFFICE does not
  document it, so it is **unverified** for this product;
- Collabora gets `storage.ssl.ca_file_path` in `coolwsd.xml`.

Never set ONLYOFFICE's `requestDefaults.rejectUnauthorized=false`. ONLYOFFICE's
documentation describes it as for diagnostics only.

**Private addresses.** The editor's request filtering blocks private and
metadata addresses by default. The installer allows exactly one address:
clientst0r's. That is `--clientstor-ip`, or what `--clientstor-url` resolves
to. If clientst0r's address changes, update it:

- ONLYOFFICE: `allowIPAddressList` in `local.json`, then restart the `ds-*`
  units;
- Collabora: `post_allow` and the alias group in `coolwsd.xml`, then restart
  `coolwsd`.

## Reverse proxy

The installer writes the Nginx server block. If TLS ends at another proxy in
front, use `--tls none-behind-proxy`: the block then listens on port 80 only,
for the editor host. Allow only your proxy to reach that port, for example
with `allow <proxy-ip>; deny all;` in the block or with the firewall. The
front proxy must pass WebSocket upgrades and long-lived connections. An Nginx
front proxy looks like this:

```nginx
# Front proxy -> editor host. UNVERIFIED as a whole: adapt to your proxy.
map $http_upgrade $connection_upgrade { default upgrade; '' close; }
server {
    listen 443 ssl;
    server_name docs.example.com;
    ssl_certificate     /etc/ssl/docs.example.com.crt;
    ssl_certificate_key /etc/ssl/docs.example.com.key;
    client_max_body_size 200m;
    location / {
        proxy_pass http://<editor-host-ip>:80;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 36000s;
        proxy_buffering off;
    }
}
```

The Collabora locations in the generated block cover:

- `^~ /cool/`, which handles both `/cool/ws` (new in 26.04) and the legacy
  `/cool/<doc>/ws`;
- `/browser`;
- `/hosting/discovery`;
- `/hosting/capabilities`.

Everything else returns 404. This layout is community-reported: Collabora's
official SDK proxy page could not be read during research, so treat it as
**unverified** and check it against that page.

## Health checks and logs

| Check | ONLYOFFICE | Collabora |
|---|---|---|
| Liveness on the host | `curl http://127.0.0.1:8083/healthcheck` returns `true` | `curl http://127.0.0.1:9980/hosting/discovery` (XML with `wopi-discovery`) |
| Through Nginx | `curl https://docs.example.com/healthcheck` | `curl https://docs.example.com/hosting/capabilities` (JSON with `productVersion`) |
| Installer | `install-editor.sh --health-check` | same |
| From clientst0r | Instance → Health check, Diagnostics, round-trip test | same |

Logs:

| What | Where |
|---|---|
| ONLYOFFICE service | `journalctl -u 'ds-*'` |
| ONLYOFFICE files | `/var/log/onlyoffice/documentserver/` (path unverified for 10.0) |
| Collabora | `journalctl -u coolwsd` |
| Editor Nginx | `/var/log/nginx/clientst0r-office-access.log` and `-error.log` |
| clientst0r | `journalctl -u clientst0r-gunicorn` (`office.*` loggers redact tokens) |
| Audit | Audit log, `extra_data.office_event`: `save`, `quarantine`, `settings_change` and others |

## Backup and recovery

**On the editor host.** No documents live there, so the backup is only
configuration:

- `/etc/clientst0r-office/`: the install record and the secret (root only);
- ONLYOFFICE: `/etc/onlyoffice/documentserver/local.json`;
- Collabora: `/etc/coolwsd/coolwsd.xml` and `/etc/coolwsd/proof_key`. If the
  proof key changes, clientst0r picks up the new public key from discovery;
- `/etc/nginx/sites-available/clientst0r-office-*.conf` and the certificate
  and key;
- `/etc/apt/preferences.d/clientst0r-office-*`, the sources file and the keyring.

Treat the backup as secret, because it contains the shared secret. To recover,
reinstall the same pinned version with the installer, then restore these
files. Alternatively, install fresh and import the new secret into the
existing instance with `office_setup --import-secret FILE --instance N`.

**On clientst0r.** This is what matters:

- the database: `FileRevision` and `QuarantinedSave` rows, and the
  `EditorInstance` with its encrypted secret;
- the media directory: `MEDIA_ROOT/office/revisions/`,
  `MEDIA_ROOT/office/quarantine/` and the targets' own files.

clientst0r's normal backup covers both. Restore them together: a revision row
without its file, or a file without its row, is not usable.

An editor outage loses no saved version. Unsaved edits that the editor could
not deliver are retried by the editor while it runs. A save that arrives late
or stale is quarantined (Settings → Office Documents → Quarantine), not
discarded.

## Upgrades

Editor upgrades are **pinned and explicit**. They never happen as a side
effect of anything else:

- the package is pinned with `Pin-Priority: 1001` and held, so `apt upgrade`
  skips it;
- clientst0r's own update (Settings → Updates, `upgrade_apply`,
  `scripts/auto_update.sh`, `deploy/update_instructions.sh`) never names,
  restarts or reconfigures an editor service. A test (`office.test_ops_commands.UpgradeSafetyTests`)
  checks those files;
- the root helper's `apt upgrade-packages` refuses editor packages, and
  `update_system_packages` skips them with a message;
- the root helper's `restart` can only touch `clientst0r-*` units.

To upgrade:

1. Read the vendor's release notes for the target version. Test it on a
   staging VM, with the [manual verification](#manual-verification) steps.
2. Drain: `manage.py office_sessions --drain N` (see below).
3. On the editor host:

   ```
   sudo bash /root/clientst0r-install-editor.sh --upgrade --version 10.0.2-5 --confirm-drained
   # Collabora also needs: --brand-version <brand package version>
   ```

   The installer:
   - re-verifies the key fingerprint;
   - moves the pin and installs that exact version;
   - re-holds the packages;
   - re-applies clientst0r's settings and restarts the editor;
   - runs the health check.

   It refuses to downgrade, and refuses ONLYOFFICE versions below 10.0.0.
4. In clientst0r, run the instance's Health check, which records the new
   version and capabilities. Then run
   `manage.py office_sessions --resume N`.

## Draining sessions

```
manage.py office_sessions --status [--instance N]
manage.py office_sessions --drain N [--timeout 600] [--poll 10] [--revoke-remaining]
manage.py office_sessions --resume N
```

`--status` lists each instance (enabled or blocked, health, version) and its
open sessions: user, file, mode, state, opened, idle time. It never shows
tokens, secrets or document keys.

`--drain N` does four things:

1. **Blocks new sessions** on instance N by disabling it. This happens first,
   so nobody starts a new session while the drain runs.
2. **Asks the editor to save** each open co-editing group, once per document
   key, through the provider's `force_save`:
   - ONLYOFFICE has a command-service `forcesave` the connector can use;
   - Collabora has no server-side save request, so the drain reports
     "not supported" and waits for users to close their editors.
3. **Waits** until no live session is left, or `--timeout` passes.
4. **On timeout** lists the remaining sessions and exits 1. With
   `--revoke-remaining`, it revokes them instead. Anything they save later is
   quarantined and can be recovered, never written over a newer revision.

`--resume N` enables the instance again.

While an instance is blocked, an organization whose policy can fall back to
another enabled instance opens new sessions there. The core's revision checks
reject or quarantine any save based on an older revision. Still, drain at a
quiet time if users may be editing the same files.

## Switching provider

For example, moving from Collabora CODE to ONLYOFFICE, or from CODE to
licensed Collabora Online:

1. Install the new editor, on a new VM or with a different host name, and add
   it as a new instance. Run Health check, Diagnostics and the round-trip test.
2. `manage.py office_sessions --drain <old>`. Wait for it to report drained,
   or use `--revoke-remaining` at the agreed time.
3. Set the new instance as the default (Settings → Office Documents) and
   enable it. Update the organizations' preferred instances, and any dedicated
   instance assignments.
4. Keep the old instance disabled for a few days. Look in Quarantine for late
   saves from it.
5. Uninstall the old editor, and remove the old instance in clientst0r.
   Documents and revisions stay, because they belong to clientst0r, not to the
   instance.

## Uninstalling

```
sudo bash /root/clientst0r-install-editor.sh --uninstall --dry-run
sudo bash /root/clientst0r-install-editor.sh --uninstall [--purge-state]
```

The uninstall:

- stops the editor services and removes the editor packages (`apt-get remove`);
- removes the editor's Nginx site and link (`nginx -t`, then reload);
- removes the apt source, keyring and pin;
- removes the CA drop-ins;
- keeps `/etc/clientst0r-office/` (the install record and secret) unless
  `--purge-state` is given.

It **never touches clientst0r's documents or versions**, and says so when it
runs. They live on the clientst0r server, never on the editor. It also never
touches clientst0r's database, Nginx site, app directory or `.env`. Every
removal is limited to paths the installer created.

Afterwards, disable or remove the instance in clientst0r. Documents stay.

## Manual verification

These steps have **not** been carried out. Run them on throwaway VMs:
Ubuntu 24.04 and Debian 12, 4 cores, 8 GB RAM, 60 GB disk.

1. **Separate server, ONLYOFFICE, Ubuntu 24.04**
   1. Run `--preflight-only`. Expect the 24.04 warning and every other check
      `ok`.
   2. Run `--dry-run`. Expect "Signing key fingerprint verified:
      E09CA29F…E8E5", and no files changed (`find /etc -newer <stamp>` is
      empty).
   3. Install with `--accept-mscorefonts-eula --tls existing-cert`.
   4. Check the package state:
      - `apt-cache policy onlyoffice-documentserver` shows `10.0.0-169`,
        priority 1001;
      - `apt-mark showhold` lists the package;
      - `apt-get -s upgrade` does not upgrade it.
   5. Check the service and config:
      - `systemctl list-units 'ds-*'` lists the actual unit names. Record them
        in this document;
      - `curl -s http://127.0.0.1:8083/healthcheck` returns `true`;
      - `jq .services.CoAuthoring.secret /etc/onlyoffice/documentserver/local.json`
        shows the secret, which matches `/etc/clientst0r-office/secret`;
      - `journalctl -u 'ds-*'` has no "developer-only" secret warning.
   6. Check that the secret was never printed: `grep -r <secret> ~/.bash_history /var/log`
      finds nothing.
   7. Import into clientst0r. Health check is `ok` with version 10.0.0.
      Diagnostics pass. The round-trip test passes.
   8. Stock nginx 1.24 works, despite the "1.30" claim on the install page.
      Record the result.
2. **Private CA**: issue the clientst0r certificate from a test CA and
   reinstall with `--ca-file`. The editor's saves reach clientst0r. Record
   whether `NODE_EXTRA_CA_CERTS` was needed or honoured.
3. **Collabora CODE, Debian 12**: install with `--provider collabora-code`.
   - `curl -s http://127.0.0.1:9980/hosting/discovery | head` works;
   - `/etc/coolwsd/proof_key` exists;
   - opening a document from clientst0r works, including WebSockets through
     Nginx;
   - a WOPI request from a host not in `alias_groups` is refused.
4. **Same server**: on a clientst0r test install, install ONLYOFFICE with
   `--mode same-server --hostname docs.<domain>`.
   - clientst0r's site file and `.env` are byte-identical before and after
     (`sha256sum`);
   - clientst0r keeps serving during and after the install;
   - `ss -ltnp` shows 8083 on Nginx and Node.
5. **Upgrade**: drain, then `--upgrade --version <next> --confirm-drained`.
   The pin moves, the hold is restored and the Health check shows the new
   version. Then run clientst0r's own Settings → Updates → Apply: the editor
   version and uptime are unchanged
   (`systemctl show -p ActiveEnterTimestamp <unit>`).
6. **Uninstall**: `--uninstall`. Packages are gone, the site is gone and Nginx
   still serves clientst0r. In clientst0r, documents and Version History are
   intact.
7. **Negative tests**:
   - point `curl` at a mirror that serves a different key (or edit
     `KEY_URL`/`KEY_FPR` in a copy of the script): the install stops with a
     fingerprint mismatch;
   - same-server with clientst0r's own host name is refused.

## Appendix: Docker

Native packages with systemd are the supported path. If you must run an editor
in a container, run it on the editor host as a separate deployment, not in
clientst0r's `docker-compose.yml`. Pin the image by version, never `latest`.

- ONLYOFFICE: `onlyoffice/documentserver:10.0.0`, with `JWT_ENABLED=true` and
  `JWT_SECRET` read from a root-only env file.
- Collabora: `collabora/code:<26.04 tag>`, with `aliasgroup1=https://clientstor.example.com:443`.

The image tags and environment variable names are **unverified** for these
versions. Check the vendor's image documentation. Put the same Nginx server
block (from a dry run of the installer) in front. The installer, pinning,
drain and upgrade steps above do not manage containers.

## Sources and unverified points

Pinned facts come from the vendors' package indexes, release notes, source
trees and public keys:

- **ONLYOFFICE**: `download.onlyoffice.com` Packages, `CHANGELOG.md`, the API
  and helpcenter configuration pages.
- **Collabora**: the CODE-deb `Packages` file, and the 26.04 `coolwsd.xml.in`,
  `WopiStorage.cpp` and `ProofKey.cpp` files in the `online.mirror` repository.

Still **unverified**:

- ONLYOFFICE on Ubuntu 24.04;
- the real minimum nginx version for ONLYOFFICE (1.22 in the package metadata,
  1.30 on the install page);
- ONLYOFFICE 10 systemd unit names;
- `NODE_EXTRA_CA_CERTS` support in ONLYOFFICE;
- the ONLYOFFICE log directory for 10.0;
- Collabora's hardware requirements and supported distributions;
- Collabora's official Nginx proxy example;
- the format of the licensed Collabora repository URL and the package versions
  in it;
- the Docker image tags.
