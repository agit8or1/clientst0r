# Microsoft 365 documents (SharePoint / OneDrive)

The Microsoft 365 connection (`integrations.M365Connection`) has a separately
enabled **Documents (SharePoint/OneDrive)** capability. With it on, people can:

- browse the SharePoint libraries, OneDrive folders and sites that an
  administrator has allowed;
- link a file to the organization's documents, a document, an asset or a ticket;
- open a linked file in Microsoft 365;
- create a new Word, Excel or PowerPoint file in an allowed folder;
- import a copy of a file into clientst0r;
- export a copy of a clientst0r file to an allowed folder.

Each person signs in to Microsoft with their own account (delegated
permissions). Every Graph call runs as that person, so Microsoft's own
permissions apply on top of clientst0r's.

Code: `integrations/m365docs/`. Models and migration:
`integrations/migrations/0041_m365_documents.py`. Tests:
`integrations/tests_m365docs.py`, plus `integrations/tests_m365docs_e2e.py`
for a real tenant (opt-in; **not run** so far).

## What it does not change

- The tenant-read and mail features keep their client-credentials token
  (`scope=https://graph.microsoft.com/.default`), their application
  permissions and their admin consent. Turning documents on or off, or
  changing their mode, writes only the `docs_*` columns. A test checks that
  the credentials, tenant ID and cached data stay the same.
- The document permissions are requested only at each person's **Connect my
  Microsoft 365 documents** step, using incremental (dynamic) consent.
- The Azure AD single sign-on in `accounts/` (which requests `User.Read`) is
  separate and is not touched.

## Permissions per mode

An administrator picks the **access** (read only, or read and write) and the
**SharePoint** reach. The permissions requested are exactly these:

| Access | SharePoint | Delegated permissions requested |
|---|---|---|
| Read only | Users' own OneDrive only | `Files.Read`, `offline_access` |
| Read only | Libraries the user can reach | `Files.Read`, `Files.Read.All`, `offline_access` |
| Read only | Only sites granted to the app | `Files.Read`, `Sites.Selected`, `offline_access` |
| Read and write | Users' own OneDrive only | `Files.ReadWrite`, `offline_access` |
| Read and write | Libraries the user can reach | `Files.ReadWrite`, `Files.ReadWrite.All`, `offline_access` |
| Read and write | Only sites granted to the app | `Files.ReadWrite`, `Sites.Selected`, `offline_access` |

Why each one is needed:

- **`Files.Read` / `Files.ReadWrite`**: the signed-in user's own files. These
  cover listing children, reading items and downloading (`Files.Read`), and
  uploading (`Files.ReadWrite`).
- **`Files.Read.All` / `Files.ReadWrite.All`** (delegated): files in any
  library the user can already open. Microsoft still checks the user's own
  access on every call.
- **`Sites.Selected`** (delegated): only the site collections that a
  SharePoint administrator has granted to this app. Within those sites, the
  app's grant and the user's access are intersected.
- **`offline_access`**: a refresh token, so the user does not sign in every
  hour.

Admin consent:

- According to the Graph permissions reference, none of these delegated
  permissions requires administrator consent.
- A tenant can still restrict user consent by policy. In that case an
  administrator consents once for everyone. Use **Enterprise applications → the
  app → Permissions → Grant admin consent**, or add the delegated permissions
  to the registration and press **Grant admin consent**.

Never requested:

- `Files.Read.Selected` / `Files.ReadWrite.Selected`. Microsoft says they are
  "only exposed for working with Office 365 file handlers" and "should not be
  used for directly calling Microsoft Graph APIs".
- `User.Read` and `openid`. clientst0r identifies the account from
  `GET /me/drive` (`owner.user`).
- `Sites.Read.All` (delegated). Any other permission is also never requested.

Whether delegated `Files.Read` alone reaches SharePoint team-site libraries
is **unverified**. Microsoft's wording ("the signed-in user's files")
suggests it does not, which is why the SharePoint modes add `Files.*.All` or
`Sites.Selected`.

## App registration steps

Use the app registration the connection already has (same client ID and
secret).

1. **Authentication → Add a platform → Web.** Add the redirect URI shown on the
   connection's *Document settings* page, normally
   `https://<your clientst0r host>/integrations/m365/documents/callback/`.
   - The URI is built from the request's host.
   - Set `M365_DOCS_REDIRECT_URI` in Django settings to pin it, for example
     behind a reverse proxy.
   - Plain `http` is rewritten to `https` unless `DEBUG` is on.
2. **API permissions → Add a permission → Microsoft Graph → Delegated** (optional).
   - Add the permissions for the chosen mode from the table above.
   - Dynamic consent means this step is not strictly required, but listing
     them makes admin consent possible.
   - Do not remove the existing application permissions; tenant read and
     mail still need them.
3. **Supported account types** stays as it is.
   - Sign-in uses the connection's tenant as the authority:
     `https://login.microsoftonline.com/<tenant>/oauth2/v2.0/authorize`.
   - So only that tenant's accounts and its guests can connect.
4. The client secret is the connection's existing secret. Certificate
   credentials, which Microsoft recommends, are **not implemented**: the
   connection stores a secret.

## Granting Sites.Selected

All three steps are required. Microsoft: "If any of the three steps are
missed, the application doesn't have access."

1. **Consent the scope.** Consent to `Sites.Selected` (delegated) in Entra ID.
   This happens at a user's Connect step, or once by an administrator.
2. **Grant the app on each site.** A SharePoint administrator grants the
   app on each site:

   ```http
   POST https://graph.microsoft.com/v1.0/sites/{site-id}/permissions
   Content-Type: application/json

   {"roles": ["write"],
    "grantedToIdentities": [{"application": {"id": "<client id>", "displayName": "clientst0r"}}]}
   ```

   - Use `"read"` for read-only mode.
   - Microsoft returns `201 Created`.
   - The caller needs **`Sites.FullControl.All`** (delegated or application).
   - In a delegated call, the caller must hold a SharePoint Administrator role
     or higher.
   - clientst0r does not make this call. It never requests
     `Sites.FullControl.All`. Run it from Graph Explorer or PowerShell as a
     SharePoint administrator.
   - Lists, folders and files can be granted at a lower level with the
     `/lists/{id}/permissions` and driveItem `/permissions` endpoints. That
     breaks inheritance, and clientst0r does not drive it.
3. **Get a token that contains the scope.** Each user does this by clicking
   **Connect my Microsoft 365 documents**, or **Connect again** if the mode
   changed after they connected.

## Allowed locations

Nothing is browsable until an organization administrator (the
`integrations_configure` role permission) adds allowed locations on the
connection's *Document settings* page. An allowed location is one of:

| Kind | What it allows |
|---|---|
| Each user's own OneDrive | The signed-in user's drive (`/me/drive`) |
| SharePoint site | Every library of that site (`GET /sites/{id}/drives`) |
| Library (drive) | One document library |
| Folder | One folder and everything below it |

How each kind is added:

- **Sites** are added by URL, for example
  `https://contoso.sharepoint.com/sites/Finance`. The site is resolved with
  `GET /sites/{host}:/{path}` as the administrator. If Microsoft refuses the
  delegated token (`Files.*.All` does not cover site metadata), the lookup
  falls back to the connection's **existing** tenant-read application token
  (`Sites.Read.All` application, already consented for tenant read). The page
  says which one was used.
- **Libraries and folders** are picked from a site, browsing as the
  administrator. The administrator must connect first.

The rule is enforced on every browse, link, open, create, import and export
(`integrations/m365docs/access.py`):

- IDs from the browser are validated against a strict pattern before they
  are put in a Graph path. A slash, colon, `..` or other unexpected character
  is refused with 404.
- The item is fetched from Graph and must be in the requested drive.
- For a folder, the item must be inside the allowed folder. This is proven
  by walking `parentReference.id` up from the item until the allowed folder
  is reached (at most 64 levels). A renamed or moved folder therefore never
  widens the rule.
- Locations belong to one connection and one organization. A location of
  another connection is ignored.
- Removing a location takes effect at once: existing links to files there
  can no longer be opened or imported.

## clientst0r permissions

These are checked before any Graph call, on the connection's organization.

| Action | Requires |
|---|---|
| Connect, browse | `docs_view` |
| Open / import from a link | view permission on the link's parent: `docs_view`, the document's own view rule, `assets_view`, or MSP staff + `tickets_view` |
| Link / unlink | edit permission on the parent: `docs_edit`, `docs.permissions.can_edit`, `assets_edit`, or MSP staff + `tickets_edit` |
| Create a file in Microsoft 365 | read-write mode + `docs_create` (+ link permission on the parent) |
| Import a copy (new Document) | `docs_create` |
| Export a copy | read-write mode + view permission on the file + `docs_edit`; ticket attachments need MSP staff |
| Settings, allowed locations | organization admin with `integrations_configure` |

Tenant isolation:

- A connection, location or link of another organization is a 404.
- Microsoft's sign-in for one connection is never used for another.

## Sign-in: authorization code + PKCE

`integrations/m365docs/oauth.py` implements the flow.

**Starting the sign-in**

- **Connect** is a CSRF-protected POST.
- It creates a 256-bit `state` and a PKCE verifier. It sends
  `code_challenge=<S256(verifier)>` and `code_challenge_method=S256` with
  `response_type=code`.
- It keeps `{connection, user, verifier, scopes, time, redirect_uri}` in the
  user's server-side session, keyed by state. At most 5 sign-ins can be
  pending, and each expires after 10 minutes.

**The callback** (a GET from Microsoft, so Django's CSRF token cannot be
present):

- The state must exist in this session, belong to this user and not be
  expired. It is removed on first use.
- Only then is the code exchanged, with `code_verifier`, `client_secret` and
  the same `redirect_uri`.
- A missing refresh token (no `offline_access`) is refused.

**Storing tokens**

- Tokens are kept in `M365DocsGrant`, one row per (connection, user).
- `refresh_token` and `access_token` are `EncryptedTextField`s (the `enc2$`
  AES-GCM envelope bound to the column).
- Tokens, codes and verifiers are never logged or put in audit entries.

**Refreshing**

- Access tokens are refreshed shortly before they expire.
- Microsoft rotates refresh tokens; the new one always replaces the old.
- `invalid_grant`, `interaction_required` or `consent_required` deletes the
  grant, and the user is asked to connect again.

**Disconnecting** deletes both tokens and is audited.

- Microsoft's identity platform documents no endpoint that revokes a single
  application's refresh token on request. So clientst0r cannot revoke at
  Microsoft.
- The page tells the user to remove the app's consent in My Apps
  (myapplications.microsoft.com), or to ask an administrator. An
  administrator can revoke a user's sessions in Entra ID.
- An unused refresh token expires on Microsoft's schedule.

Turning documents off for a connection deletes every stored sign-in for it.

## Network rules

`integrations/m365docs/http.py` handles all traffic. It is built on
`office.net.fetch`, which:

- resolves the host once and pins the connection to the checked addresses;
- verifies TLS against the system trust store;
- ignores proxies and `.netrc`;
- caps the response size;
- refuses cross-host redirects.

On top of that:

- Only `https` on port 443, with no credentials in the URL.
- **Fixed hosts.** `graph.microsoft.com` for Graph and
  `login.microsoftonline.com` for tokens.
- **Public addresses only.** `public_only`, a new attribute that
  `office.net.ip_allowed` honours. Editor instances are unaffected. A DNS
  answer pointing at a private, loopback or metadata address is refused.
- **Download URLs and web URLs.** A `@microsoft.graph.downloadUrl` (fetched
  *without* the bearer token) and a `webUrl` (the redirect target for
  **Open**) are followed only when the host is the tenant's
  `<tenant>.sharepoint.com` or `<tenant>-my.sharepoint.com`.
  - The SharePoint host is set on the settings page, or learned from the
    first user's OneDrive URL.
  - Sovereign clouds (`sharepoint.us`, `sharepoint.cn`, …) and vanity
    domains are **not supported**.
- **Sharing and anonymous viewers are never called.** Any Graph path
  containing `createLink`, `invite`, `permissions`, `grant`, `shares` or
  `preview` is refused in `http.check`, whatever the caller asks. The
  feature never creates sharing links and never uses an anonymous viewer.
- `@odata.nextLink` pages are followed only on `graph.microsoft.com`, for at
  most 10 pages.

## The actions

**Open in Microsoft 365**

- A POST (form `target="_blank"`) to `/integrations/m365/documents/linked/<id>/open/`.
- clientst0r fetches the item again with Graph as the user, re-checks the
  allowed locations, checks the `webUrl` host and redirects to it with
  `Referrer-Policy: no-referrer`.
- If Microsoft no longer lets the user see the file (unshared, moved,
  deleted), the open fails. There is no fallback to a stored URL.
- That `webUrl` opens Office files in Office for the web is **unverified**.
  Microsoft documents it as "URL that displays the resource in the browser",
  and the behaviour depends on library settings.

**Link**

- Stores `driveId`, `itemId`, name, `webUrl`, `eTag` and size in
  `LinkedCloudDocument`, together with the organization, the connection, the
  allowed location and at most one parent (Document, ticket or asset; none
  means the organization's documents).
- No content is copied, and there is no sync in either direction.

**Create**

- Uploads the core's vetted blank `.docx` / `.xlsx` / `.pptx`
  (`office/templates_files/`) with
  `PUT /drives/{drive-id}/items/{parent-id}:/{name}:/content?@microsoft.graph.conflictBehavior=fail`.
- An existing file is never replaced. On a 409 the user is asked for
  another name.
- The new file is then linked.

**Import a copy**

- A confirmation page shows the source and the destination (a new Document
  in the organization).
- The file is downloaded through its `downloadUrl`, within
  `office.storage.max_bytes()`.
- It is stored with `office.storage.store_initial(..., source='import')`, so
  it gets revision 1 and the core's format validation and scan hook.
- Only Office formats can be imported.

**Export a copy**

- From an Office file page (Document, attachment or ticket attachment),
  choose **Export a copy to Microsoft 365**, browse to an allowed folder and
  choose **Export here**.
- A confirmation page shows the destination folder and the file name.
- The current revision is uploaded with `conflictBehavior=fail`.

**Audit.** Every action is audited:

| Event (`extra_data.office_event`) | AuditLog action |
|---|---|
| `m365_settings` | update |
| `m365_location_add` / `m365_location_remove` | update |
| `m365_connect` / `m365_disconnect` | update |
| `m365_link` | create |
| `m365_unlink` | delete |
| `m365_open` | read; failures are recorded with `success=False` |
| `m365_create` | create |
| `m365_import` | import |
| `m365_export` | export |

Entries carry IDs, names, eTags and SHA-256 digests, never tokens, download
URLs or content.

## UI

- **Integrations → Microsoft 365 connection → Documents (SharePoint/OneDrive).**
  This is the capability switch.
  - Turning it on shows a review page with the exact permissions (and why
    each is needed) before anything is saved.
  - The same page holds the redirect URI, the allowed locations and your own
    sign-in.
- **Documents → Microsoft 365** tab. It appears only when the organization
  has a documents-enabled connection the user may use. It offers Connect /
  Disconnect, the allowed locations, browsing, Link, Import a copy, New file
  here, and the links on the organization's documents.
- **Document, asset and ticket pages** show a *Microsoft 365 files* section
  with Open in Microsoft 365, Import a copy, Unlink and *Link a Microsoft 365
  file…*. Ticket links are shown to MSP staff only.
- **Office file page** (`/office/f/<code>/<pk>/`) has *Export a copy to
  Microsoft 365…*.
- No inline handlers or scripts; everything is plain forms and links.

## Edit in Microsoft 365 (working-copy round trip)

*Shipped in v3.17.671. Verified only against a
fake Microsoft (see Tests); it has not been run against a real tenant.*

A clientst0r Word, Excel or PowerPoint file (`.docx`, `.xlsx`, `.pptx`) can be
edited in Microsoft 365 through a **working copy**. clientst0r stays the
place the file lives; Microsoft 365 only ever holds a copy, and clientst0r
gets its content back only when someone chooses **Save back to clientst0r**.

Code: `integrations/m365docs/editing.py` (service), `views_edit.py` (views),
`signals.py` (revocation), `integrations/management/commands/m365_edit_sessions.py`
(scheduled task). Model `integrations.M365EditSession`
(`integrations/migrations/0042_m365_edit_sessions.py`). Tests:
`integrations/tests_m365edit.py`.

### The flow

1. **Start.** On the Office file page (`/office/f/<code>/<pk>/`) a user who
   may edit the file chooses **Edit in Microsoft 365** (a form posted to a new
   tab). clientst0r:
   - re-checks permission and that the connection belongs to the file's
     organization;
   - reads the current revision and verifies it against its stored SHA-256;
   - uploads it as the user (delegated token) into the working-copy folder
     with `PUT …:/<name>:/content?@microsoft.graph.conflictBehavior=fail`, so
     nothing is ever replaced (the name is `<file> (clientst0r edit).<ext>`,
     with a random suffix if that exists);
   - records the session: file, base revision and checksum, user,
     organization, connection, location, drive id, item id, eTag and cTag;
   - redirects to the item's `webUrl` (tenant SharePoint host only,
     `Referrer-Policy: no-referrer`).
   Starting again while a session is open reopens the same working copy.
2. **Edit in Microsoft 365.** Co-authoring with other people happens in
   Microsoft 365, under Microsoft's permissions for that working copy.
3. **Check for changes** reads the item's cTag (content tag) and says whether
   the content changed since clientst0r last had it. It imports nothing.
4. **Save back to clientst0r:**
   - only the session's owner can do it, and their edit permission is checked
     again first (a lost permission revokes the session; nothing is
     downloaded);
   - the item is read again and must be the same drive and item id, a file,
     inside the allowed location;
   - the content is downloaded from the `downloadUrl` (tenant SharePoint
     host, no bearer token) within the size limit;
   - it is stored with `office.storage.save_or_quarantine` (format
     validation, scan hook, edit permission re-checked inside the write
     transaction), expected base = the session's base revision, or the
     revision this session last saved. The revision's source is *Imported*;
     the audit entry says it came from a Microsoft 365 edit session.
   - **Stale base:** when the clientst0r file got a newer revision meanwhile,
     the content is kept as an unaccepted save (quarantine, reason *stale*) in
     the file's version history, where it can be downloaded or restored, and
     the user is told. Nothing is overwritten.
   - **Idempotent:** content identical to what the session already saved (or
     to the base, before any save) creates no revision. A second save-back
     while one runs is refused (a claim on the session row, 10-minute expiry).
5. **Finish** ends the session. It is refused while the Microsoft copy has
   changes clientst0r does not have (cTag differs): save back first, or
   discard. **Discard** ends the session without saving. Then the working
   copy is deleted (`DELETE /drives/{id}/items/{id}`, with `If-Match` on the
   eTag just read for Finish; OneDrive / SharePoint keep it in the recycle
   bin for their retention) or kept, as the administrator chose.

### Visibility and locking

- While a session is open, everyone who can see the file sees *Being edited
  in Microsoft 365 by <name>* on the file page.
- The ONLYOFFICE / Collabora editor page shows *Also being edited in
  Microsoft 365 by …*.
- Nothing is locked: reading, downloading and in-app editing still work. A
  save-back based on an older revision becomes a conflict (above), never an
  overwrite. Several people can each have their own session on the same
  file; each save-back is checked against its own base.

### Administrator settings

On the connection's **Document settings** page, card *Edit in Microsoft 365*
(a customer's own connection: an administrator of that customer with
`integrations_configure`; the platform connection: a platform administrator
in global view):

| Setting | Default | Meaning |
|---|---|---|
| When MSP staff edit this customer's files, use | platform | Only on a customer's own connection: which tenant is preferred when the platform connection also qualifies. |
| Offer Edit in Microsoft 365 | off | Needs documents on and **read and write** access. Turning it off ends every open session (revoked). |
| Working copies go to | — | One allowed location: each user's own OneDrive (private to that user), or one library or folder (visible to whoever Microsoft 365 lets see it there). A whole site is not accepted. |
| Folder for working copies | `clientst0r working copies` | Created once in the location (`POST …/children`, `conflictBehavior=fail`; an existing folder of that name is reused). Empty: the location's top level. |
| When a session ends | delete | `delete` or `keep` the working copy. |
| Remind about idle sessions after | 72 hours | Used by the scheduled task. |

Every change is audited (`m365_edit_settings`).

### Permissions

| Who | Needs |
|---|---|
| MSP staff | edit permission on the file (`docs.permissions.can_edit` for a Document, `files_upload` (+ `vault_edit` for a password's file) for an attachment, MSP staff + `files_upload` for a ticket attachment) and `docs_view` on the organization |
| Customer users | the same, **plus** the role permission `office_edit_in_m365` (off for every role, never granted automatically). Without it the button is not shown. |

The session URLs (`/integrations/m365/documents/edit/…`) are exempt from the
`/integrations/` section gate (`integrations_view`); the views decide per
file instead. Connecting one's own Microsoft 365 sign-in still happens on
the existing documents pages, which keep that gate, so a customer user also
needs whatever lets them reach *Documents → Microsoft 365* today.

`office_edit_in_m365` was added in `accounts` 0047 (customer-assignable,
elevated). Built-in roles do not hold it. `docs/ROLES_AND_ACCESS.md` is
generated with `manage.py roles_matrix`.

Revocation: membership, role, user-type and deactivation changes and file
deletion revoke affected sessions at once (`m365docs/signals.py`, the same
events as the in-app editors). Every session action re-checks permission
as well, so a change the signals miss takes effect on the next action. A
revoked session's working copy is deleted by the scheduled task when the
policy is *delete*.

### Which tenant receives the working copy

Integrations are platform-owned by default (integrations/ownership.py), so the
MSP's own Microsoft 365 tenant is usually a **platform** connection
(organization empty). The rules:

| Who | Connections offered |
|---|---|
| MSP staff (user type Staff, Django staff, superuser) who may edit the file at its customer | the **platform** connection, and the file's customer's **own** connection, when each has documents (read and write) and Edit in Microsoft 365 on |
| Customer users (with `office_edit_in_m365`) | their own customer's connection only — never the platform connection |

- A connection owned by a **different customer** is never used, for anyone:
  customer data never lands in another customer's tenant.
- A customer's own connection is used only for that customer's files.
- On the platform connection the working copy goes to the staff member's
  own OneDrive in the MSP tenant, or the platform connection's allowed
  library / folder.
- When both qualify for a staff member, the customer connection's setting
  *When MSP staff edit this customer's files … use* decides which is
  preferred (default: the platform connection).
- **Confirm step.** *Edit in Microsoft 365…* first shows a page (nothing is
  uploaded yet) naming, for each qualifying connection, the connection, its
  owner (*Platform (MSP)* or the customer), the tenant ID, where the copy
  will go and the finish policy, with the preferred one first. The upload
  starts only from that page. When the user has not connected their
  Microsoft sign-in for that connection, the page offers *Connect my
  Microsoft 365 documents first*.
- Sessions are looked up by id **and** owner; anyone else's session is a 404.
  The allowed-locations rule is applied at start, open, check and save-back.
- Audit entries name the connection (`connection`, `connection_name`,
  `connection_owner`, `tenant_id`) and are recorded on the file's customer.

Platform connection administration (documents settings, allowed locations,
Edit in Microsoft 365 settings) is done in **global view** by platform
administrators: superuser, Django staff, or MSP staff whose global role grants
`integrations_configure`. A customer's own connection stays managed inside
that customer by an administrator with `integrations_configure`. The other
document features (browse, link, create, import, export) remain per customer
connection; the platform connection is used only for sign-in and Edit in
Microsoft 365.

### Scheduled task

*Microsoft 365 Edit Sessions* (`m365_edit_sessions`, hourly;
`manage.py m365_edit_sessions`):

- revokes sessions whose user lost permission;
- deletes working copies marked for deletion (for example after a revoke,
  or when Finish could not reach Microsoft);
- for sessions idle longer than the configured time: if the Microsoft copy
  has no changes clientst0r lacks, ends the session and applies the
  delete/keep policy; otherwise reminds the user once per idle period
  (audit entry, plus e-mail when SMTP is configured).
- It **never imports** anything.

### Security notes

- No sharing links, invitations or permission changes are ever made; the
  HTTP layer refuses those endpoints whatever the caller asks.
- Graph calls only to `graph.microsoft.com`, downloads only from the tenant's
  SharePoint hosts, all through the SSRF-safe client (`m365docs/http.py`).
- Tokens stay in the encrypted `M365DocsGrant`; they are never in a URL,
  log line, audit entry or the session row. Download URLs are not stored.
- Size limit: `OFFICE_MAX_FILE_MB` (and at most 250 MB, the single-PUT limit).
- Checksums: the revision is verified before upload; every save-back records
  the SHA-256 of what was stored.

### Audit events

| Event | AuditLog action |
|---|---|
| `m365_edit_start` | export |
| `m365_edit_open` | read |
| `m365_edit_save` (failures and conflicts with `success=False`) | import |
| `m365_edit_finish`, `m365_edit_discard`, `m365_edit_revoked`, `m365_edit_ended`, `m365_edit_reminder`, `m365_edit_settings` | update |

The Office storage path also writes its usual `save` / `quarantine` entries.

### Limits of this approach

- clientst0r gets content only when someone saves back. Changes made in
  Microsoft 365 after the last save-back are not in clientst0r.
- Whether `webUrl` opens the copy in Office for the web, and how often Office
  for the web's autosave changes the cTag, are **unverified** against a real
  tenant.
- Uploads use a single `PUT` (Microsoft's limit 250 MB); upload sessions are
  not implemented.
- The working-copy location must be one of the connection's allowed
  locations; a whole SharePoint site cannot be chosen.

## Direct editing of stored files: not available

Embedding Office for the web over files stored in clientst0r (Microsoft's WOPI
host integration) requires Microsoft's **Cloud Storage Partner Program**.

- Microsoft: the program "is for independent software vendors whose
  business is cloud storage. It's not open to Microsoft 365 customers
  directly".
- Members must offer the solution as SaaS, with files in storage the partner
  owns.
- A self-hosted deployment, where each customer stores the files, does not
  qualify.

clientst0r therefore does not implement it. Use *Edit in Microsoft 365*
(above), which works with a working copy, or edit stored files directly with
ONLYOFFICE or Collabora.

## Limitations

- No automatic sync in either direction, by design. Imported and exported
  copies are independent; an Edit in Microsoft 365 working copy comes back
  only on *Save back to clientst0r*.
- Uploads use a single `PUT`, which Microsoft limits to 250 MB. The
  clientst0r limit (`OFFICE_MAX_FILE_MB`) is normally lower. Upload sessions
  are not implemented.
- The documents features other than Edit in Microsoft 365 (browse, link,
  create, import, export) work on customer-owned connections only.
- Commercial cloud only: `graph.microsoft.com`, `login.microsoftonline.com`,
  `*.sharepoint.com`.
- Client-secret authentication only; certificate credentials are not
  implemented.
- clientst0r cannot revoke a refresh token at Microsoft (see above).
- Site lookup by URL can fall back to the tenant-read application token.
  If that app lacks `Sites.Read.All`, add libraries from a site ID instead.
- A user without a OneDrive licence cannot use the *own OneDrive* location.
  Their name is not shown after connecting.

## Tests

`integrations/tests_m365docs.py` mocks Microsoft at the HTTP layer
(`m365docs.http._net_fetch`, the `office.net.fetch` call). It uses the
response shapes Microsoft documents for the token endpoint and Graph v1.0
`drive`, `driveItem` and `site`. The tests cover:

- **Scopes:** scope selection never touches existing scopes.
- **PKCE:** the state and verifier checks, replay, cross-user and expiry,
  and CSRF on Connect.
- **Tokens:** encrypted token storage, refresh with rotation, `invalid_grant`,
  and disconnect.
- **Allowed locations:** folder, drive, site and own-OneDrive enforcement,
  including IDs outside the allowlist and malformed IDs.
- **Tenant isolation.**
- **Sharing:** no sharing endpoint is ever called; the test asserts on every
  recorded request.
- **Create:** `conflictBehavior=fail`, and a duplicate name never replaces.
- **Import and export:** an explicit destination page, then revision 1
  (`source=import`) or an upload of the current revision.
- **Network rules:** the download host check and public-only DNS.
- **Audit entries.**

These prove clientst0r's side only.

`integrations/tests_m365docs_e2e.py` runs the flow against a real tenant
when these environment variables are set:

```
OFFICE_E2E_M365_TENANT, OFFICE_E2E_M365_CLIENT_ID, OFFICE_E2E_M365_CLIENT_SECRET,
OFFICE_E2E_M365_REFRESH_TOKEN, OFFICE_E2E_M365_DRIVE_ID, OFFICE_E2E_M365_FOLDER_ID,
OFFICE_E2E_M365_SHAREPOINT_HOST
```

It covers refresh, listing, create with conflict `fail` (twice), open URL,
import, export and cleanup. **It has NOT been run.** No tenant was available
when this was built.
