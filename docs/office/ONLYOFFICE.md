# ONLYOFFICE Docs connector

clientst0r can open, edit and co-edit `.docx`, `.xlsx` and `.pptx` files in
ONLYOFFICE Docs (Document Server). It uses the official Docs JavaScript API
and the callback protocol. clientst0r stays the canonical store: every save
from the editor becomes a new binary revision in clientst0r (see
[OFFICE_DOCUMENTS.md](../OFFICE_DOCUMENTS.md)).

The connector code is `office/providers/onlyoffice/`. It was written against
the ONLYOFFICE Docs **10.0** documentation and has been tested only against a
protocol model of the server (see [Testing](#testing)). **It has not yet been
run against a real Document Server.**

## Supported versions and editions

- **ONLYOFFICE Docs 10.0.0 or later.** The health check refuses older versions
  ("degraded"). 10.0 changed the default port, the token `operation` field and
  the command/conversion token rules, and fixed security problems (an SSRF in
  the WOPI endpoints and a macro sandbox bypass).
- **Community, Enterprise or Developer edition.** The health check reads the
  version with the signed `version` command. It reads the edition from the
  `license` command's `server.packageType` field. That field's meaning was
  taken from the command service description and has not been checked against
  10.0.
- **No connection or user limit is assumed.** 9.4 removed the old limit of 20
  simultaneously open documents. The GitHub README still says "up to 20
  recommended" for Community. How many users an instance can carry depends on
  the edition, the licence and the hardware you deploy.

## What works

| Capability | How |
|---|---|
| Edit `.docx` / `.xlsx` / `.pptx` | Docs API editor, `mode: edit` |
| View `.doc` / `.xls` / `.ppt` / `.docm` / `.xlsm` / `.pptm` | `mode: view`; the original is never overwritten |
| Co-editing | `coEditing.mode: fast`; everyone on the same revision shares one document key |
| Comments, review (Word) | `permissions.comment` / `review`, only in edit sessions |
| Save now | The **Save now** button and the editor's own Save button (`customization.forcesave`) send a command-service `forcesave`. Docs answers with a status-6 callback, which clientst0r stores as a revision. |
| Final save on close | Status-2 callback, about 10 s after the last editor closes |
| Save a copy | `onRequestSaveAs`: clientst0r fetches the file from the editor host and stores it as a new file |
| PDF export | Conversion service; offered only if the health check's test conversion worked |
| Legacy/macro → OOXML copy | Conversion service; the original is kept |
| Collaborators | Names of the users Docs reports in its status-1 callbacks |
| Revocation | A revoked session is dropped from the editor with the `drop` command, and its later saves are quarantined |

Not offered: macros, plugins and the editor's AI integration. They are
switched off in the editor config (`customization.macros: false`,
`macrosMode: disable`, `plugins: false`, `ai.disabled: true`).

## How a session works

1. **Opening a file.** clientst0r opens an edit session. It then renders
   `/office/edit/<session>/`, which loads
   `<browser URL>/web-apps/apps/api/documents/api.js` and starts
   `DocsAPI.DocEditor`.
2. **The signed config.** The config carries:
   - `document.fileType`, `key`, `title` and `url`
   - `document.permissions`
   - `editorConfig.callbackUrl`, `user` (an anonymised id plus a display name), `mode`, `lang` and `coEditing`
   - `token`: the whole config signed with HS256 and the instance secret. The secret itself never reaches the browser.
3. **Fetching the document.** `document.url` is
   `<callback base>/office/api/onlyoffice/file/<session>/?access_token=…`.
   It serves the revision the editor key stands for, and only when both
   checks pass:
   - the Office access token is valid for `read`, with the session live and the user's permission re-checked;
   - the request carries Docs' outbox JWT (`operation: download`).

   Each fetch is audited.
4. **Callbacks.** Docs posts them to
   `<callback base>/office/api/onlyoffice/callback/<session>/`. The callback
   section below covers them.
5. **The browser glue.** `static/js/office-onlyoffice.js` connects the editor
   events to the page's save indicator:

   | Event | Indicator |
   |---|---|
   | `onDocumentStateChange` | "Changes in editor" |
   | Save now | "Saving…" |
   | A revision clientst0r confirmed (status poll) | "Saved to clientst0r". An editor event never sets this. |
   | `onError`, or a save error from a callback | "Save failed" |

### Document keys

Every session in a co-editing group shares one core `document_key`. The
editor key is `<document_key>.<generation>`:

- It stays the same for the whole co-editing session, including force-saves.
- A status-2 save marks it **spent** before anything is stored. The next
  open, or a reload, then gets the next generation. ONLYOFFICE requires a new
  key after every completed save.

### Callback handling

The callback is checked in this order:

1. **Rate limit.** `OFFICE_ONLYOFFICE_CALLBACK_RATE` per session per minute, default 120.
2. **Session.** It must exist, use ONLYOFFICE and still have its instance.
3. **JWT.** `Authorization: Bearer` (the header name can be changed per instance):
   - HS256 only, so `none` and every other algorithm is refused;
   - signed with the instance secret;
   - `exp` present and not past;
   - `operation` equal to `callback` where present;
   - fields wrapped in `payload`.

   The fields used come from the token. A body that contradicts the token is
   refused. A token in the body is accepted only when the instance is
   configured for it (see below).
4. **Key.** The callback's `key` must equal the session's editor key. Sessions
   of another file or organization have other keys, so a callback can never
   write another tenant's file.

What each status does:

| Status | Meaning | clientst0r does |
|---|---|---|
| 1 | being edited | records the connected users |
| 2 | ready for saving | marks the key spent, downloads `url`, stores a revision, closes the sessions waiting for the final save |
| 3 | save error | keeps `url` in quarantine if it downloads, shows "Save failed" |
| 4 | closed, no changes | closes the waiting sessions |
| 6 | force-save | downloads `url` and stores a revision; the session stays open |
| 7 | force-save error | as 3; the session stays open |

**Downloads.** They use `office.net.fetch`:

- only from the instance's browser or internal origin, which also blocks
  metadata, link-local and DNS-rebinding tricks;
- with the instance size limit;
- with TLS verified against the instance CA bundle.

**Storing.** clientst0r first checks the file is a real OOXML package of the
file's own format. It then stores it with `storage.save_or_quarantine`, with
the co-editing group's expected base revision. The outcomes:

- **A repeated delivery** of a stored save is recognised and answered `{"error":0}` with nothing written.
- **Stale content is quarantined.** That means a save based on an older revision than the current one, for example after a restore or an upload in the meantime. A newer revision is never overwritten.
- **A revoked or expired session, lost permission or invalid content** is also quarantined.

**Replies.**

- `{"error":0}` is sent only when the bytes are durable: stored, a recognised
  duplicate, or kept in quarantine. Once the bytes are quarantined, a retry
  would only deliver the same refused bytes.
- HTTP 500 `{"error":1}` is sent when nothing could be kept: the download
  failed, the URL was on another host, the file is over the size limit, or
  storage failed. Docs then retries and keeps its own copy.

## Configuring the Document Server

Edit `/etc/onlyoffice/documentserver/local.json`. Never edit `default.json` or
`production-linux.json`, because upgrades replace them. Restart the
service after changing it. The JWT documentation says `systemctl restart ds-*`;
the unit names after 9.4's single-process change have not been checked.

```json
{
  "services": {
    "CoAuthoring": {
      "secret": {
        "browser": { "string": "<SECRET>" },
        "inbox":   { "string": "<SECRET>" },
        "outbox":  { "string": "<SECRET>" },
        "session": { "string": "<ANOTHER RANDOM SECRET>" }
      },
      "token": {
        "enable": { "browser": true, "request": { "inbox": true, "outbox": true } },
        "inbox":  { "header": "Authorization", "inBody": false },
        "outbox": { "header": "Authorization", "inBody": false }
      },
      "request-filtering-agent": {
        "allowPrivateIPAddress": false,
        "allowMetaIPAddress": false,
        "allowIPAddressList": ["<clientst0r server IP>"]
      }
    }
  },
  "storage": { "fs": { "secretString": "<ANOTHER RANDOM SECRET>" } },
  "aiSettings": { "enable": false }
}
```

Notes on these settings:

- **Secrets.** `<SECRET>` is the instance's shared secret in clientst0r
  (Settings → Office Documents → instance → Shared secret), at least 32
  random characters. Every vendor default secret is
  `developer-only-not-a-real-secret`, and the storage default is
  `verysecretstring`. clientst0r refuses both. Its diagnostics also send a
  command signed with the default secret, and fail if Docs accepts it. Docs
  also accepts it when inbox token checking is off.
- **Private addresses.** Only needed when clientst0r has a private (LAN/VPN)
  address. Prefer listing the clientst0r address in `allowIPAddressList`
  over setting `allowPrivateIPAddress: true`, so Docs can reach clientst0r
  and nothing else private. This is our recommendation, not a vendor one.
  Do not enable `allowMetaIPAddress`.
- **Body token.** `inBody` stays `false`. If you turn on
  `token.outbox.inBody`, also allow it for the instance in clientst0r's
  settings:

  ```python
  OFFICE_ONLYOFFICE_INSTANCE_OPTIONS = {
      '<instance name>': {'body_token': True},
      # 'header': 'AuthorizationJwt',   # only if token.outbox.header was changed
  }
  ```

- **Plugins and macros.** clientst0r switches them off in every editor
  config. To also remove the bundled plugins server-side, use
  `documentserver-pluginsmanager.sh --remove=…`. Removed plugins come back
  after a Docs upgrade.
- **AI.** `aiSettings.enable: false` makes `/ai-proxy` answer 403.
  clientst0r has no AI features for documents.
- **WOPI.** Leave it off. clientst0r uses the Docs API, not WOPI, with ONLYOFFICE.

### Private CA

If clientst0r's certificate (the callback address) comes from a private CA,
the Document Server must trust it. **`NODE_EXTRA_CA_CERTS` is not documented
by ONLYOFFICE.** It is the standard Node.js variable, and community posts add
it to the Docs systemd units:

```
# systemctl edit <docs unit>   (unit names after 9.4 not verified)
[Service]
Environment=NODE_EXTRA_CA_CERTS=/usr/local/share/ca-certificates/clientst0r-ca.crt
```

Do not set `requestDefaults.rejectUnauthorized: false`; the vendor marks it
"only for diagnostics".

In the other direction, paste the editor's CA certificate into the instance's
**CA bundle** field. clientst0r verifies TLS against it plus the normal trust
store.

## Ports and addresses

| What | Default |
|---|---|
| Public HTTP(S) port, DEB/RPM install, since 10.0 | **8083**. Set it with `echo onlyoffice-documentserver onlyoffice/ds-port select <PORT> \| sudo debconf-set-selections` before installing. |
| Internal docservice port | 8000 (`services.CoAuthoring.server.port`), not exposed |
| Healthcheck | `GET <server>/healthcheck` → `true` |
| Editor script | `<browser URL>/web-apps/apps/api/documents/api.js` |
| Command service | `POST <server>/command` |
| Conversion service | `POST <server>/converter` |

clientst0r uses three addresses:

- **Browser URL.** Users' browsers load the editor from here. It must be
  https with a certificate the browsers trust. The editor page's CSP allows
  scripts, frames and connections (including `wss:`) to this origin only.
- **Internal URL** (optional). clientst0r uses it for the command service,
  the conversion service, the healthcheck and downloads. Without it, the
  browser URL is used.
- **Callback base URL.** The Document Server reaches clientst0r here for
  `/office/api/onlyoffice/…`. That traffic is the callback, the document
  download and the conversion source link.

Firewall rules:

- **Browser → Docs:** 443 (or the published port).
- **clientst0r → Docs:** the internal port.
- **Docs → clientst0r:** 443 on the callback address.

Every reverse proxy in front of Docs must pass WebSocket upgrades:
`proxy_http_version 1.1`, `Upgrade` and `Connection: upgrade`, and long
timeouts.

## Diagnostics

Settings → Office Documents → instance → **Run diagnostics** adds these
checks to the core checks (addresses, secret, DNS/address policy,
reachability and TLS from clientst0r):

| Check | How it is decided |
|---|---|
| `/healthcheck` | `GET` through the internal URL must answer `true` |
| Browser address TLS | when the internal URL is on another origin, the browser URL is also fetched from this server |
| Signed requests (JWT) | a signed `version` command is accepted |
| Version | ≥ 10.0.0 |
| Default secret refused | a command signed with the vendor default must be refused (error 6) |
| Editor reaches clientst0r (document download) | a test conversion: Docs downloads a blank file from a signed, 10-minute link on the callback address, with its outbox JWT, and converts it to PDF |
| Editor reaches clientst0r (save callback) | **pass** when a real callback arrived in the last 30 days, else **not run**. Docs only calls back for a document open in a browser, so open a document, change it and press Save, then run the diagnostics again. |
| WebSocket through the proxy | **not run**: the co-editing socket is opened by the browser. The check explains what to look for, and mentions when an editing session last reported connected users. That proves co-editing connected, possibly over long polling. |
| Browser loads the editor | the **browser check** page (`/office/api/onlyoffice/instances/<id>/browser-probe/`) loads `api.js` in an administrator's browser and records the result. Without a result from the last 30 days the check is **not run**. |

**Run health check** stores the version, edition and capabilities.
Conversion and PDF export are advertised only when the test conversion
succeeded. If Docs cannot download from clientst0r at all, the instance is
marked degraded.

**Run round-trip test** steps:

1. Create a disposable `.docx`.
2. Open an edit session.
3. Have Docs download the document through the session's own document URL
   and re-save it with the conversion service (docx → docx).
4. Store the result through the same persistence path a callback uses.
5. Reopen the stored revision and compare SHA-256.
6. Report the callback step from real callback evidence (otherwise not run),
   then clean up.

Because the callback step cannot be produced without a browser, the round
trip reports "not passed" until a real callback has been seen.

## Licensing

- **Licence terms.** ONLYOFFICE Docs is licensed under the GNU AGPL v3 with
  additional terms:
  - keep the notices and attribution;
  - mark modified versions;
  - keep the UI legal notices identifying ONLYOFFICE as the original developer;
  - no trademark licence.
- **Branding.** The Community edition must keep its original branding;
  removing it needs a commercial licence. `customization.logo` is
  Developer-edition only. clientst0r does not change or hide ONLYOFFICE
  branding and sets no logo or white-label options.
- **How clientst0r is set up.** clientst0r (MIT) does not bundle, modify or
  redistribute ONLYOFFICE. The administrator installs the Document Server
  separately and unmodified from the vendor's signed repository. clientst0r
  only talks to it over HTTP and loads its JavaScript from the Document
  Server itself.
- **Legal ambiguity.** The vendor's statements, such as "any derivative work"
  being AGPL and applications using its source code having to be AGPL, do not
  say whether calling an unmodified, separately installed server over its
  API makes the caller a derivative work. The vendor's own integration
  examples are Apache-2.0, while its Nextcloud/ownCloud connectors are
  AGPL-3.0. **Get a legal opinion before distributing clientst0r with
  ONLYOFFICE integration commercially.**

## Testing

There are two test suites:

- **`office/tests_onlyoffice.py`.** This suite runs in every test run. It
  works against `FakeDocumentServer`, a model of the Docs 10.0 HTTP protocol
  built from the documented payloads:
  - healthcheck;
  - command service (`version`, `license`, `forcesave`, `drop`, `info`, with
    inbox JWT checks);
  - conversion service (it downloads from clientst0r's real endpoints with
    an outbox JWT);
  - cache downloads;
  - signed callbacks.

  The fake replaces `office.net.fetch`, but the real `net.check_url` policy
  still runs first. The tests cover:
  - config signing, verified with PyJWT;
  - callback JWT rejection: missing token, wrong secret, HS512, `none`,
    expired, no expiry, wrong operation, no payload wrapper, body
    contradicting the token, body token only when configured;
  - every status;
  - duplicate, stale, revoked, lost-permission, oversized, non-zip and
    wrong-format saves;
  - per-save key rotation, and the key staying stable across force-saves;
  - save attribution, forcesave, drop and save-as;
  - SSRF refusal: another host, `169.254.169.254`, userinfo tricks, `file:`;
  - cross-tenant and cross-instance callbacks;
  - the per-session rate limit;
  - health, diagnostics, the round trip, conversion and the signed source
    link.

  **Passing these proves the connector follows the documented protocol, not
  that a real Document Server behaves the same.**
- **`OnlyOfficeRealServiceTests`.** These are skipped unless the following
  are set:

  ```
  OFFICE_E2E_ONLYOFFICE_URL=https://docs.example.lan/      # browser URL of a real Docs 10.x
  OFFICE_E2E_ONLYOFFICE_SECRET=<its JWT secret>
  OFFICE_E2E_CALLBACK_BASE=http://<this host>:<port>/      # how Docs reaches the test server
  OFFICE_E2E_PORT=<port>  OFFICE_E2E_BIND=0.0.0.0          # live server bind
  # optional: OFFICE_E2E_ONLYOFFICE_INTERNAL_URL, OFFICE_E2E_CA_BUNDLE_PEM, OFFICE_E2E_MODE=same_server
  manage.py test office.tests_onlyoffice.OnlyOfficeRealServiceTests
  ```

  They cover:
  - health, version, JWT and the default-secret check;
  - the round trip;
  - DOCX, XLSX and PPTX revisions produced by Docs, stored, reopened and
    exported to PDF;
  - a revoked token refused when Docs fetches the document;
  - SSRF refusal.

  **They have not been run yet**: no Document Server was available when the
  connector was written.

### Manual browser checklist (real server)

These need a person in a browser. They have **not** been done.

1. New DOCX, XLSX and PPTX: open, type, the indicator shows "Changes in editor", press Save now, and it shows "Saved to clientst0r". Check that Version History has a new revision.
2. Close the editor. About 10 s later a revision appears, and reopening shows the content with a new document key.
3. A reader opens the same file: read-only, no Save now.
4. Two users co-edit the same file. Both see each other in the collaborators slot. Closing both leads to one final revision attributed to the last editor.
5. Restore an older revision while someone edits. Their next save lands in quarantine (stale) and the editor shows "Save failed". Restore from quarantine works.
6. Revoke the user's access while they edit. They are dropped from the editor, and a late save is quarantined.
7. Stop the Document Server while editing, then start it again. The page shows the failure, and the next save succeeds.
8. Export PDF and "Convert to a new copy" for a `.doc` file.
9. Run the browser check page from a user network, and the diagnostics.
10. Same-server and separate-server installs.
