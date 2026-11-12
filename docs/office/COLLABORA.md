# Collabora Online connector

clientst0r is a **WOPI host** for Collabora Online. Users edit Office files that
clientst0r stores in a Collabora iframe. Every save comes back through WOPI
`PutFile` and becomes a new revision (see [OFFICE_DOCUMENTS.md](../OFFICE_DOCUMENTS.md)).

> **Status: built, not yet tested against a real Collabora server.** The unit
> and integration tests use a protocol-accurate fake (described under Tests
> below). The real-service suite exists, but it has **not been run**.

The Collabora facts in this document come from Collabora's own **26.04 source
tree** (`distro/collabora/co-26.04` on the read-only GitHub mirror), from
their package repository, and from collaboraonline.com. The official SDK site
(sdk.collaboraonline.com) could not be read during development. Anything
marked *unverified* should be checked against it before you rely on it.

## What is implemented

| Area | Behaviour |
|---|---|
| Discovery | Fetches `GET /hosting/discovery` through `office.net.fetch`. Parses `urlsrc` per extension and action (`view`, `edit`). Caches the result for 1 hour by default (the `discovery_ttl_s` option). The proof key is read from `<proof-key modulus= exponent= oldmodulus= oldexponent=>` |
| Capabilities | Reads `GET /hosting/capabilities` for `productName`, `productVersion` and `convert-to.available`/`endpoint` |
| CODE | Detected from `productName` ("Collabora Online Development Edition"). Labelled **"Evaluation / development only"** in the detected edition, the health detail, diagnostics and an editor-page badge |
| Formats | Edit: `docx`, `xlsx` and `pptx`, but only where discovery lists an `edit` action. View: any handled extension with a `view` or `edit` action. Legacy and macro formats always open read-only |
| Conversion | PDF export and legacy→OOXML ("Convert to a new copy") through `POST /cool/convert-to/<fmt>`. Advertised only when `/hosting/capabilities` reports `convert-to.available` |
| WOPI | CheckFileInfo, GetFile, PutFile, LOCK, UNLOCK, REFRESH_LOCK, GET_LOCK, UNLOCK_AND_RELOCK and RenameFile. `PUT_RELATIVE` (Save As) answers 501 and is hidden with `UserCanNotWriteRelative: true` |
| Proof keys | `X-WOPI-Proof` / `X-WOPI-ProofOld` are verified (RSA-SHA256) whenever discovery publishes a key |
| Editor page | Form-POSTs the token into a named iframe, and speaks the postMessage protocol from `static/js/office-collabora.js` |
| Diagnostics, round trip | See [Diagnostics and the round trip](#diagnostics-and-the-round-trip) |

### Code layout

- `office/providers/collabora/` — the provider (`__init__.py`), plus `discovery.py`, `proof.py`, `locks.py`, `wopi.py`, `views.py`, `selftest.py` and `options.py`.
- `office/models.py`
  - `WopiLock` holds one lock row per file.
  - `EditorInstance.provider_options` holds the per-instance options.
  - Migration: `office/migrations/0002_collabora_wopi.py`.
- `templates/office/collabora/editor.html` and `static/js/office-collabora.js`.
- `office/management/commands/office_collabora.py`.

## The three network paths

```
browser ──https + WebSocket──▶ Collabora (browser_url)           iframe /browser/…/cool.html, /cool/…/ws
Collabora ──https (WOPI)──▶ clientst0r (callback_base_url)       /office/api/wopi/files/<id>[/contents]
clientst0r ──https──▶ Collabora (internal_url or browser_url)    /hosting/discovery, /hosting/capabilities,
                                                                 /cool/convert-to/<fmt>, WebSocket probe
```

- **Browser → Collabora.** Users' browsers must reach `browser_url` over HTTPS, and the proxy must pass WebSocket upgrades on `/cool/`.
- **Collabora → clientst0r.** Collabora must reach the callback origin.
  - That origin must be listed in `storage.wopi.alias_groups`.
  - clientst0r's GeoIP firewall must not block it. LAN addresses are exempt, but a public-IP Collabora server outside the allowed countries is refused.
- **clientst0r → Collabora.** All of these requests go through the Office network guard: approved origin only, DNS pinned, TLS verified with the instance CA bundle.
  - Collabora only accepts `convert-to` from addresses listed in `net.post_allow`. The defaults are RFC 1918 and loopback.

## Collabora server configuration (`/etc/coolwsd/coolwsd.xml`)

Restart with `sudo systemctl restart coolwsd` after editing. All the keys below are
from the 26.04 `coolwsd.xml.in`.

**Trusted WOPI hosts.** 26.04 uses `alias_groups`; the old flat `storage.wopi.host` list is not what the template uses. The default `mode="first"` trusts whichever host connects first after each start, so set `mode="groups"`:

```xml
<storage>
  <wopi allow="true">
    <alias_groups desc="..." mode="groups">
      <group>
        <host desc="clientst0r" allow="true">https://clientstor.example.com:443</host>
      </group>
    </alias_groups>
  </wopi>
  <filesystem allow="false"/>
</storage>
```

The host is the origin of the instance's **Callback URL**. The 26.04 release notes say that entries without a scheme are now accepted.

**TLS.** There are two ways to set it up:

- **Collabora terminates TLS itself:** `<ssl><enable>true</enable>…` with its certificate.
- **A reverse proxy terminates TLS (recommended):**

  ```xml
  <ssl><enable type="bool">false</enable><termination type="bool">true</termination></ssl>
  ```

  The template's comment: "SSL off-load can be done in a proxy, if so disable SSL, and enable termination below in production".

For a private CA, paste the CA certificate into the instance's **CA bundle** in
clientst0r. Never switch verification off.

**Framing.** `net.frame_ancestors` is marked OBSOLETE in 26.04. Use the content security policy instead:

```xml
<net>
  <content_security_policy>frame-ancestors https://clientstor.example.com</content_security_policy>
```

**External data.** Restrict `net.lok_allow`. It controls `=WEBSERVICE()`, external cell references and inserted graphics. "Without this section every host is allowed"; if it is present and no host ends up allowed, every host is denied. Keep an explicit empty or minimal list:

```xml
  <lok_allow desc="external data sources"></lok_allow>
  <post_allow><host desc="clientst0r">192\.168\.1\.10</host></post_allow>   <!-- convert-to -->
</net>
```

**Macros, AI and the admin console.**

- `security.enable_macros_execution` defaults to `false`. Leave it.
- `ai.enabled` defaults to `false`. Leave it.
- Consider `admin_console.enable=false`.
- Keep `security.capabilities=true` and `security.seccomp=true` (both the defaults).

**Host name in discovery.** Set `server_name` to the browser host name. Collabora writes the host it was asked on into `urlsrc`. When clientst0r uses an internal address, clientst0r rewrites those URLs to the browser origin, and diagnostics warn until `server_name` is set.

**Proof keys.** Collabora signs WOPI requests only when `/etc/coolwsd/proof_key` exists. To create it:

```
sudo coolconfig generate-proof-key
sudo systemctl restart coolwsd
```

Without a key, discovery has no `<proof-key>`, clientst0r cannot tell Collabora's requests from anyone else's, and diagnostics show a warning.

**Lock refresh.** `storage.wopi.locking.refresh` (default 900 s) is how often Collabora re-LOCKs. clientst0r locks last 30 minutes, so keep the refresh below that.

## Reverse proxy (Nginx) — *unverified*

The official example is on the SDK "Proxy settings" page, which could not be read.
26.04 accepts both the new `/cool/ws` path and the legacy `/cool/<docURI>/ws`. A
single `/cool/` block with WebSocket headers covers both. This configuration is
community-reported (a Nextcloud forum post), not from Collabora:

```nginx
server {
    listen 443 ssl;
    server_name office.example.com;
    # ssl_certificate ...;

    location ^~ /browser            { proxy_pass http://127.0.0.1:9980; proxy_set_header Host $host; }
    location ^~ /hosting/discovery  { proxy_pass http://127.0.0.1:9980; proxy_set_header Host $host; }
    location ^~ /hosting/capabilities { proxy_pass http://127.0.0.1:9980; proxy_set_header Host $host; }
    location ^~ /cool/ {
        proxy_pass http://127.0.0.1:9980;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "Upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 36000s;
    }
}
```

Diagnostics check that the proxy passes the upgrade (see below).

**Logging.** WOPI puts `access_token` in the query string; that is how the protocol works.

- clientst0r redacts it from its own logs: `office.*`, `django.request`, `django.server` and `gunicorn.access`.
- Nginx in front of **clientst0r** must not log it either. Use a `log_format` with `$uri` instead of `$request` / `$request_uri` for `location /office/api/wopi/`.

## clientst0r settings

**Settings → Office documents → Add instance**, with provider *Collabora Online*:

| Field | Value |
|---|---|
| Browser URL | `https://office.example.com/`, the address users' browsers load |
| Internal URL | Optional. A LAN address clientst0r uses for discovery and conversion |
| Callback URL | `https://clientstor.example.com/`, the address Collabora uses to reach clientst0r. **Only its origin is used**; the WOPISrc path is clientst0r's own |
| Shared secret | Collabora does not use one. The form and the core diagnostics still ask for one, so enter a random 32+ character value. *(Known gap, reported to the core.)* |
| CA bundle | The private CA certificate, when the editor uses one |

Then run **Health check**. It stores the version, the edition and the
capabilities, and Edit buttons only work after a healthy check.

Per-instance options are set from the trusted CLI. There is no web form for them yet:

```
manage.py office_collabora --instance 3                       # show
manage.py office_collabora --instance 3 --require-proof on    # default on
manage.py office_collabora --instance 3 --disable-print on --hide-export on
manage.py office_collabora --instance 3 --discovery-ttl 3600 --refresh-discovery
```

- **`require_proof`** (default on): when discovery publishes a key, any WOPI request without a valid proof gets HTTP 500, as the WOPI proof-key rules require. Turning it off is audited and shown as a warning in diagnostics.
- **`disable_print` / `hide_export`**: set `DisablePrint` + `HidePrintOption` and `DisableExport` + `HideExportOption` in CheckFileInfo.

## How a session works

1. **The user clicks Edit.** The core opens an `EditSession`, and the provider then does the following:
   - Fetches discovery (from the cache when it can).
   - Picks `urlsrc` for the extension.
   - Issues a token scoped to the session with `read write lock rename` (edit) or `read` (view).
   - Renders a hidden form `POST urlsrc?WOPISrc=<callback origin>/office/api/wopi/files/<document_key>&lang=…` with `access_token` and `access_token_ttl` in the body, targeting a named iframe.
2. **What the token is like.**
   - It appears only in that form body. It is never in a URL that clientst0r builds.
   - `access_token_ttl` is the session's hard end, in milliseconds since the epoch.
   - On the server the token is short-lived (Settings → token lifetime). The page renews it every third of that lifetime (`/office/api/collabora/s/<session>/renew/`, signed in, CSRF-protected).
   - When the page stops renewing (it was closed, or the laptop is asleep), the token expires and further WOPI calls get 401.
3. **What `file_id` is.** It is the session's `document_key`: random and opaque, and shared by everyone co-editing the same revision. Collabora groups co-editors by WOPISrc, so this is what makes co-authoring work.
   - A revision written outside the group (an upload, a restore, a different editor) gives the next opener a new key and therefore a separate Collabora document. A save from the old group then fails the timestamp check.
4. **Every WOPI request** passes these checks, in order:
   - `file_id` must match `[A-Za-z0-9_-]{16,128}`.
   - The token must be known.
   - The token's session must be a Collabora session whose `document_key` equals `file_id`.
   - The proof must verify (when the key is published and `require_proof` is on).
   - `office.tokens.validate(op=…)` must pass. It checks expiry, revocation, scope, the session, the user and live permission.
   - An unknown, expired, revoked, wrong-scope or other-file token gets 401. Lost permission gets 403, and the session is revoked.
5. **CheckFileInfo** returns:
   - `BaseFileName`, `Size`, `Version` (`<revision>-<sha256 prefix>`), `OwnerId`, `UserId` and `UserFriendlyName`. Collabora fails to load without `UserFriendlyName`.
   - `LastModifiedTime`, in ISO 8601 UTC with microseconds and `Z`.
   - `UserCanWrite`. It requires an edit session, a token with `write`, an editable format and the user's current edit permission.
   - `UserCanNotWriteRelative=true`, `UserCanRename`/`SupportsRename`, `SupportsLocks`, `SupportsGetLock`, `SupportsUpdate` and `PostMessageOrigin` (the clientst0r origin the page was served from).
   - `EnableInsertRemoteImage/File=false`, `EnableRemoteAIContent=false`, `EnableShare=false` and `IsAdminUser=false`.
   - The print and export flags set by the options.
   - `SupportsUpdate` is a WOPI spec field; Collabora 26.04 does not read it.
6. **PutFile**, in order:
   1. Check the token (`write`).
   2. Check the size against `Content-Length` and while reading. Over the limit gets 413.
   3. Check the lock. A mismatch gets 409 with `X-WOPI-Lock: <current>`. An unlocked non-empty file gets 409 with an empty `X-WOPI-Lock`.
   4. Check `X-COOL-WOPI-Timestamp` against the current revision's `LastModifiedTime`. A mismatch gets **409 `{"COOLStatusCode":1010}`**, and Collabora then offers the user "overwrite or reload".
      - The exception is the same bytes this co-editing group already stored, which is a retried reply.
      - A forced save after "overwrite" carries no timestamp and is accepted on top of the current revision. The older revision stays in history.
   5. Store with `storage.save_or_quarantine(..., expected_base_revision=current)`, which validates the format and runs the scan hook.
   6. Reply `200 {"LastModifiedTime": …}` **only after the durable commit**.
   - `IsModifiedByUser`, `IsAutosave` and `IsExitSave` are recorded in the session's `provider_state` and the log.
   - Every refused body (lock or timestamp conflict, revoked or permission-lost token, failed validation) is kept as a `QuarantinedSave`.
7. **Locks** live in `office.models.WopiLock`, one row per file. They are changed by compare-and-set UPDATEs, so they are atomic on SQLite, MySQL and PostgreSQL.
   - Locks expire after 30 minutes.
   - `LOCK` with the held id refreshes the lock; Collabora re-LOCKs every 900 s. `LOCK` + `X-WOPI-OldLock` is UNLOCK_AND_RELOCK.
   - A lock whose holder group has no live session left (the editor crashed) can be taken over by another group.
   - Collabora 26.04 itself sends only LOCK and UNLOCK; the other operations follow the WOPI specification.
8. **RenameFile.** It needs the `rename` scope (edit permission) and the lock, if one is held. The requested name is decoded from UTF-7 and sanitised, and the extension is kept. The rename is audited.
9. **Closing.** On `pagehide` the core moves the session to `closing`, so Collabora's exit save and UNLOCK are still accepted. A successful UNLOCK on a closing session closes it.

### postMessage (`static/js/office-collabora.js`)

Messages are only accepted when `event.origin` is the instance's browser origin **and**
`event.source` is the editor iframe. Outgoing messages name that origin.

| Message | Direction | What the page does |
|---|---|---|
| `App_LoadingStatus` `Frame_Ready` | from the editor | Sends `Host_PostmessageReady` first, as the protocol requires |
| `App_LoadingStatus` `Document_Loaded` | from the editor | Records a browser event (used by diagnostics) and requests `Get_Views` |
| `Doc_ModifiedStatus` `Modified: true` | from the editor | Shows "Changes in editor" |
| `Doc_ModifiedStatus` `Modified: false` | from the editor | Shows "Saving…" |
| `Action_Save_Resp` | from the editor | `success: false` shows the failure |
| `Action_Save` | to the editor | Sent by **Save now** and **Retry save** |

- **"Saved to clientst0r"** appears only when `ClientstorOffice.watchServer()` sees a new stored revision.
- **No new revision.** If Collabora reports "not modified" and no revision appears within 45 s, the indicator goes back to "No unsaved changes". This happens when the content is unchanged, because the same content is not stored twice.
- **Unverified message names.** `Get_Views`/`Get_Views_Resp`/`View_Added`/`View_Removed` (collaborator list) and the `Failed` loading status are *unverified*. If they never arrive, nothing else breaks.

### CSP

The editor page adds only the instance's browser origin, to `frame-src`, `child-src`
and `form-action`. `connect-src` is not widened, because the page itself never calls
Collabora. The iframe is not sandboxed: Collabora rejects messages from an
`origin === 'null'` sandboxed frame.

## Diagnostics and the round trip

**Diagnostics** (Settings → Office documents → instance → Diagnostics):

| Check | How it is proven |
|---|---|
| Discovery | Fetched fresh and parsed; lists the formats with edit actions |
| Editor address in discovery | Warns when `urlsrc` named another host |
| TLS | The fetch succeeded with verification (system trust store plus the CA bundle) |
| Server capabilities | Product, version, convert-to. **CODE shows a warning** ("evaluation / development only") |
| WOPI proof key | Pass when published and required. Warns when missing (remedy: `coolconfig generate-proof-key`) or when `require_proof` is off |
| WebSocket upgrade | An HTTP/1.1 Upgrade request to `/cool/<WOPISrc>/ws` on the **browser** address, so it passes through the proxy. `101` is a pass; anything else is a warning with the status. The probe form is based on the 26.04 source (legacy path still accepted), *unverified* against a live server |
| Collabora → clientst0r WOPI | **Pass only when Collabora has actually called CheckFileInfo** in the last 30 days. The page shows when, and whether the proof verified. Otherwise *not run*, with instructions |
| Browser loads the editor | **Pass only when a browser reported `Document_Loaded`**. Otherwise *not run*: a server cannot test what users' browsers reach |

**Round trip.** The core creates a disposable `.docx` and opens an edit session on it. The provider then runs these steps:

1. `discovery`: a fresh fetch from Collabora.
2. `convert_pdf`: real Collabora renders the file with `convert-to/pdf`.
3. `resave`: real Collabora loads the `.docx` and saves it again with `convert-to/docx`. The output is checked as a valid `.docx`.
4. The `wopi_*` steps send Collabora's request sequence to clientst0r's own WOPI views, **in-process**, with a real token: CheckFileInfo, LOCK, GetFile, PutFile (Collabora's re-saved bytes), CheckFileInfo (the version changed), GetFile (same bytes) and UNLOCK. These are labelled "in-process": they prove the host side (tokens, locks, timestamps, validation, durable storage), not network reachability. They skip proof verification, because Collabora did not sign them.
5. `editor_to_wopi`: pass only with evidence that Collabora reached clientst0r (see above).
6. `browser`: always **not run**. Collabora edits only through its browser client over a WebSocket, so typing and saving cannot be driven from the server. The step says what to do by hand.

The report therefore never shows "passed" overall without a browser.

## CODE vs licensed Collabora Online

- **CODE** (`coolwsd` + `code-brand`, repo `https://www.collaboraoffice.com/repos/CollaboraOnline/CODE-deb`) is "the development version of Collabora Online … not recommended for production environments". clientst0r labels it **Evaluation / development only**.
  - Current at research time: `coolwsd` 26.04.6.1-1 / `code-brand` 26.04.6-1.
  - Signing key fingerprint `7EB1 5308 18B7 6832 8448 3B7B D891 5E45 6E7C 440E`.
- **Collabora Online** (licensed) is the supported production build. It comes from a per-customer repository, with the `collabora-online-brand` package. Current at research time: 26.04.5.3, released 2026-11-09.
  - The repository URL format and the supported-distribution matrix are *unverified* (the SDK page was unreadable).
- **CODE limits** (verbatim from the 26.04 `configure.ac`): the default build has unlimited connections and documents but shows a welcome and feedback nag. The optional home mode removes the nag and "limits concurrent open connections to 20 and concurrent open documents to 10". clientst0r hard-codes no limit.
- **Licence.** Collabora Online is MPL-2.0. MPL is file-level copyleft. clientst0r (MIT) only talks to coolwsd over HTTP/WOPI, which our reading says does not affect clientst0r's licence. *That is a general MPL reading, not a vendor statement (unverified).*
- **Branding.** Branding ships in the brand packages. clientst0r does not remove, hide or replace Collabora branding, and does not bypass CODE's nag or limits. Trademark rules are *unverified*.

## Tests

`office/tests_collabora.py` uses two fakes:

- **`FakeCollaboraServer`** is a real local HTTP server. It serves:
  - discovery, with an RSA proof key generated for the test run and an old key;
  - `/hosting/capabilities` (CODE or licensed, convert on or off);
  - `convert-to` (it checks the multipart `data` field);
  - the WebSocket upgrade, with a correct `Sec-WebSocket-Accept`.
- **`FakeCollaboraClient`** sends WOPI requests the way coolwsd does:
  - token in the query string;
  - `X-WOPI-Proof` signed over `token + UPPER(url) + ticks`, with `ProofOld` a copy of it;
  - `X-COOL-WOPI-Timestamp` echoing the last `LastModifiedTime`;
  - one lock id, and re-LOCK as the refresh;
  - the `Is*Save` flags.

Covered: every WOPI operation; lock conflicts, refresh, expiry and takeover; the 1010
timestamp conflict and the overwrite that follows; duplicate PutFile; expired, revoked,
wrong-scope, other-file and other-tenant tokens; lost permission (403 plus quarantine);
proof keys (valid, old key, forged, missing, older than 20 minutes, rotated key);
CheckFileInfo fields (ISO `Z`, `UserFriendlyName`, the required fields); size limits;
path-like file ids; RenameFile; the editor page (no token in the URL, CSP origins);
diagnostics; the round trip; conversion; and log redaction.

```
PYTHONPATH=<scratchpad>/office:. venv/bin/python manage.py test office --settings=<settings> --keepdb --noinput
```

**Real service: `CollaboraRealServiceTests` (NOT RUN).**

- It is skipped unless `OFFICE_E2E_COLLABORA_URL` is set.
- Optional variables: `OFFICE_E2E_CALLBACK_URL`, a clientst0r address the server can reach, and `OFFICE_E2E_CA_BUNDLE`.
- It runs the health check, diagnostics, the round trip and PDF export of each format against a real server.
- **It has not been run: no Collabora server was available.**

**Manual browser checklist** (SPEC §9; none of these has been done yet):

1. Edit, type, save and reopen DOCX, XLSX and PPTX. "Saved to clientst0r" appears, and Versions shows the new revision.
2. Open a file as a read-only user: the editor is view-only, with no Save.
3. Two users on the same file: both appear in the collaborators list, and both see each other's edits.
4. Restore an old revision while someone is editing. Their next save shows Collabora's "document changed" dialog, and the refused copy is in the quarantine.
5. Revoke the user's access mid-session: the next save fails and the body is in the quarantine.
6. Leave the editor open past the token lifetime: renewal keeps it working.
7. Stop coolwsd mid-edit: the page shows the failure. Restart: diagnostics recover.
8. Same-server and separate-server installs, both with proof keys enabled.
