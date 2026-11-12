# Office documents

The `office` app opens Word, Excel and PowerPoint files that clientst0r stores in an
external browser editor. It saves edits back as numbered revisions.

This document covers the **provider-independent core**: storage, sessions, tokens,
policy, the network guard, templates, the UI and the settings pages.

The editor connectors are separate work. Both `onlyoffice` and `collabora` are
registered **stubs**. Until a real connector replaces a stub, every Edit button
is shown disabled with the reason "connector not installed". Diagnostics report
the provider checks as *not run*.

## What can be edited

| Where the file lives | Model | URL code | Edit permission |
|---|---|---|---|
| Documents (file type) | `docs.Document` | `doc` | `docs.permissions.can_edit` |
| Attachments on assets, documents, … | `files.Attachment` | `att` | `files_upload` (plus `vault_edit` for password attachments) |
| Ticket attachments | `psa.TicketAttachment` | `tkt` | MSP staff with `files_upload` |
| Office templates and diagnostic files | `office.OfficeFile` | `ofi` | Templates: superuser, or `org_manage_settings` for that org's own templates. Diagnostic files: superuser only |

Projects have no attachment model, so project files are not covered.

### Formats

| Formats | How they are handled |
|---|---|
| `docx`, `xlsx`, `pptx` | Editable |
| `doc`, `xls`, `ppt` (legacy) | Opened read-only. **Convert** makes a new modern copy when the provider supports it. The original is left alone |
| `docm`, `xlsm`, `pptm` (macro) | Opened read-only |
| `dotx`, `xltx`, `potx` (templates) | Uploaded as templates. A new document is made from a template by rewriting the main part's content type |

The core refuses an `editor_save` for any read-only format, even when a
provider sends one.

`office/formats.py` validates every stored revision:

- **Zip limits:** entry count, total uncompressed size and compression ratio.
- **`[Content_Types].xml`** is parsed with `defusedxml`.
- **The main part** must be present with the content type the extension implies.
- **VBA** (`vbaProject.bin`) is refused in macro-free formats.
- **Legacy formats** must start with the OLE header.

## Data model

| Model | Purpose |
|---|---|
| `EditorInstance` | One editor server. Holds: <ul><li>provider and mode (`same_server` / `separate_server` / `existing_service`)</li><li>`browser_url`, `internal_url`, `callback_base_url`</li><li>the shared secret (encrypted) and an optional CA bundle</li><li>`verify_tls`, which can only be switched **on** (from the CLI); the web UI never offers to switch it off</li><li>detected version, edition and capabilities</li><li>size and timeout limits</li><li>`enabled`; shared, or dedicated to a set of organizations</li><li>last health result</li></ul>No connection limit is hard-coded; the detected edition is stored for the connectors to use. |
| `OfficeSettings` | Singleton (`OfficeSettings.get()`): <ul><li>enabled providers and default instance</li><li>whether organizations may choose their own instance</li><li>quarantine retention (30 days)</li><li>session idle TTL (240 min), session hard cap (24 h) and token TTL (60 min)</li></ul> |
| `OrganizationOfficePolicy` | Per organization: Office on/off, and a preferred instance. |
| `OfficeFile` | Office templates (global or per organization), and disposable diagnostic files with no organization that expire after a day. |
| `FileRevision` | One immutable stored version. <ul><li>Points at exactly one target (four nullable FKs with CASCADE; a check constraint enforces one).</li><li>Fields: `revision_number` (unique per target), `sha256`, `size`, `mime`, `source`, `editor_session`, `based_on_revision`, `restored_from`.</li><li>`source` is one of `create` / `upload` / `editor_save` / `restore` / `copy` / `import` / `convert`.</li></ul> |
| `EditSession` | One user's editor window. <ul><li>`document_key` (shared by co-editors)</li><li>`mode` view/edit</li><li>`state` open/closing/closed/revoked/failed</li><li>`base_revision`, idle `expires_at` and hard `max_expires_at`</li><li>`provider_state` JSON for the connector</li></ul>Target FKs use SET_NULL, so the history survives deletion. |
| `AccessToken` | Hash of a bearer token bound to one session, with `ops` (`read` / `write` / `lock` / `rename` / `export`), expiry and revocation. Only the hash is stored. |
| `QuarantinedSave` | Content the core refused to make current, kept for an administrator. <ul><li>`reason` is one of stale / revoked / permission / validation / storage_error.</li><li>Expires after the retention period.</li><li>Never served by the media view.</li></ul> |

Migrations: `office/migrations/0001_initial.py` and
`core/migrations/0090_scheduledtask_office_purge_quarantine.py` (the scheduler task type).

## Storage (`office/storage.py`)

### Where files live

Revisions are stored at:

```
MEDIA_ROOT/office/revisions/<org>/<kind>-<pk>/<uuid>.<ext>
```

The target's own file field always names the current revision's file. The rest
of the app (downloads, previews, search) therefore keeps working unchanged.

The target is moved with a queryset update, so `Document.save()` side effects
(the text snapshot, the image optimiser) do not run on every editor save.

### What a save does

1. **Spool.** The content is spooled to `MEDIA_ROOT/office/tmp` with a size cap.
   The sha256 is computed and the file is fsynced.
2. **Check the content.** The name and extension are checked, the format is
   validated, and the scan hook runs.
3. **Move it into place.** The file goes to its final name with `os.replace`,
   then the directory is fsynced.
4. **Commit.** Inside `transaction.atomic(durable=True)` the core:
   1. locks the target row with `select_for_update`;
   2. re-checks that the session is live and the user still has permission;
   3. detects duplicates;
   4. checks the base revision;
   5. creates the `FileRevision` and points the target at it.
5. **On failure** inside the transaction, the file is moved back to the spool
   and deleted. No row, no file and no target change remain.

### Duplicates and stale bases

A save is a **duplicate** in either case:

- it has the same sha256, session and base as an existing revision; or
- the current revision has the same sha256 and came from the same `document_key` group.

A duplicate returns the existing revision with `.duplicate = True`. This makes
editor callback retries idempotent.

The **expected base** for an editor session is the latest revision written by
its key group, or the session's base revision if the group has written none.
Force-saves therefore chain on. A revision written outside the group
(an upload, a restore, another editor) makes the base stale, and the save
raises `StaleRevision`.

### API

```python
revisions(target) -> QuerySet[FileRevision]          # oldest first
current(target) -> FileRevision | None
open_revision(revision) -> binary file object

save_new_revision(target, data, *, user, source, expected_base_revision=None,
                  session=None, original_name=None) -> FileRevision   # .duplicate set
save_or_quarantine(target, data, *, user, source, expected_base_revision=None,
                   session=None, original_name=None) -> SaveOutcome
restore(target, revision, user) -> FileRevision       # new revision, source='restore'
ensure_current(target, user=None) -> FileRevision | None
store_initial(target, data, *, user, source, original_name=None) -> FileRevision
safe_filename(name, *, fallback='document') -> str
max_bytes(instance=None) -> int
purge_unreferenced_file(name)
```

Arguments and return values:

- `data` may be bytes, a file object, a Django `File`, or an iterable of byte chunks.
- `ensure_current` seeds revision 1 from a file uploaded before Office existed.
  It also records a file that was changed outside Office as a new `upload` revision.
- `store_initial` is used for newly created files. It skips the edit-permission
  check because the creator already passed the create check.
- `SaveOutcome` has the fields `revision`, `quarantined` and `error`, and the
  properties `ok` and `duplicate`.

Exceptions (all subclasses of `StorageError`; each has `.reason` and `.message`):

| Exception | `reason` | When |
|---|---|---|
| `StaleRevision` | `stale` | The base is not the current revision. Has `.expected` and `.current` |
| `SessionRevoked` | `revoked` | The session is no longer live |
| `PermissionRevoked` | `permission` | The user lost edit permission |
| `RevisionRejected` | `validation` | The content was refused. `.code` is `too_large` / `invalid` / `scan` / `read_only` |
| `StorageError` | `storage_error` | Anything else |

`save_or_quarantine` stores refused content as a `QuarantinedSave` and audits
the failure. Over-size content is the exception: it is never fully read, so it
is reported without a quarantine row.

### Malware scanning

**No malware scanner exists in this repository.** `office/scanning.py` provides
a hook and fails closed:

```python
OFFICE_SCAN_HOOK = 'myapp.scan.scan'   # settings; '' = no scanner
def scan(path, *, name, target, user) -> office.scanning.ScanResult: ...
```

The default reports "not scanned". Diagnostics show a warning while no scanner
is configured.

### Quarantine and purge

`office.quarantine.purge_expired()` does three things:

- deletes expired quarantine rows and their files;
- deletes expired diagnostic `OfficeFile`s;
- closes expired sessions.

It runs from the scheduler task `office_purge_quarantine` (hourly) and from
`manage.py office_purge_quarantine`.

Superusers can review, download and restore quarantined saves at
**Settings → Office documents → Quarantine**.

## Policy (`office/policy.py`)

`instance_for(org, provider=None)` picks an editor instance as follows:

1. If the organization has Office switched off, the result is `None`.
2. If organizations are allowed to choose, the org's preferred instance (if it is available to them).
3. An instance dedicated to the organization.
4. The platform default instance.
5. The first shared instance, by name.

Only instances that are enabled, whose provider is enabled, and that are
available to the organization are considered.

`availability(user, target, provider=None) -> Availability` is used by every
button. It returns:

- `can_edit` and `can_view_in_editor`;
- `reason`, a human-readable explanation when something is unavailable;
- `instance`, `provider` and `capabilities`;
- `read_only_format`, `can_convert`, `can_export_pdf` and `user_may_edit`.

Edit is enabled only when every one of these holds:

- the file is an Office format;
- an instance is resolved and is healthy;
- the provider's connector is installed;
- the file is within the size limit;
- the provider supports the format;
- the user has edit permission.

## Sessions and tokens

### `office/sessions.py`

```python
open_session(target, user, *, mode, instance=None, request=None) -> EditSession
get_live(session_id, *, user=None) -> EditSession       # Http404 otherwise
renew(session) -> EditSession                           # SessionRevoked when no longer live
touch(session)
expected_base(session) -> int
close(session, *, reason='', pending_final_save=False, request=None)
revoke(session, reason)
revoke_for_target(target, reason)
still_allowed(session) -> bool
recheck_user(user_or_id, reason=...)
recheck_all(reason=...)
live_sessions() -> QuerySet
```

- **`open_session`** raises `PermissionDenied` when the user lacks the
  permission for `mode`, and `NotConfigured` when there is no instance.
- **`document_key`**:
  - is 32 characters from `[A-Za-z0-9_-]` (well within the 128-character
    `[0-9a-zA-Z._=-]` limit);
  - is shared by live sessions whose group base equals the current revision;
  - is new for anyone who opens the file after a revision written outside the group.

  A connector that must change the key after every save stores a derived key
  in `provider_state`.
- **`close` and `revoke`** call `provider.on_session_closed` /
  `on_session_revoked` after commit. `revoke` also revokes the session's tokens.
  - With `close(..., pending_final_save=True)` the session moves to `closing`,
    so a final callback can still land.

### `office/tokens.py`

```python
issue(session, ops=None, *, ttl_minutes=None, purpose='browser') -> str   # raw token, shown once
validate(raw, *, op, session_id=None, target=None) -> AccessToken         # .target attached
renew(raw, *, ttl_minutes=None) -> datetime                               # also renews the session
revoke(raw)
revoke_session_tokens(session)
```

How tokens behave:

- **Scopes.** `ops` defaults to `('read',)` for a view session and
  `('read', 'write', 'lock')` for an edit session. A view session cannot be
  given write, lock or rename.
- **Expiry.** It is capped at the session's `max_expires_at`. The TTL is in
  minutes; a Collabora connector converts it to milliseconds for `access_token_ttl`.
- **What `validate` checks on every call:** the token hash, expiry and
  revocation, the requested op, the bound session and target, that the user is
  active, and that the user still has permission. If the permission is gone, it
  revokes the session.
- **Errors.** `validate` raises `TokenError` with a `.reason`: `unknown` /
  `revoked` / `expired` / `scope` / `session` / `permission`.
- **Storage.** Tokens are stored as `hash_token(raw, 'office.access')`
  (listed in `HASHED_SECRET_FIELDS`).
- **Transport.** Raw tokens must never be put in a URL the core builds or logs.
  A WOPI connector receives `access_token` from the editor and must pass it
  straight to `validate`.

### Revocation signals (`office/signals.py`)

Live sessions are revoked, on commit, when any of these happens:

- a membership is saved or deleted;
- a role template changes;
- a user profile changes;
- a user is deactivated;
- the target Document, Attachment, TicketAttachment or OfficeFile is deleted;
- a Document is switched away from the file type.

Bulk updates fire no signals; `validate` and the storage commit re-check
permission on every call to cover them.

## Provider interface (`office/providers/`)

```python
from office.providers import (EditorProvider, Capabilities, HealthResult, EditorPage,
                              DiagnosticCheck, RoundTripReport, NotConfigured, NotSupported,
                              PASS, FAIL, WARN, NOT_RUN, register, get_provider, all_providers)

class EditorProvider:
    key = ''      # 'onlyoffice' | 'collabora' | ...
    label = ''
    def capabilities(self, instance) -> Capabilities
    def editor_page_context(self, session, request) -> EditorPage
    def health_check(self, instance) -> HealthResult
    def diagnostics(self, instance) -> list[DiagnosticCheck]
    def round_trip(self, instance, session, report: RoundTripReport) -> None
    def convert(self, instance, revision, target_ext, *, user=None) -> bytes
    def on_session_revoked(self, session) -> None
    def on_session_closed(self, session) -> None

register(provider, *, replace=False)
get_provider(key) -> EditorProvider     # NotConfigured if unknown
```

Default behaviour of the base class:

- The first four methods and `round_trip` raise `NotConfigured`.
- `convert` raises `NotSupported`.
- The two hooks do nothing.

Data types:

- **`Capabilities`** (frozen) has `edit_formats`, `view_formats`, `convert`
  (a set of `(src, dst)` pairs), `coauthoring`, `comments`, `review` and
  `max_file_mb`. It provides `can_edit` / `can_view` / `can_convert` /
  `can_export_pdf`, the `export_pdf` property, and `to_json` / `from_json`.
- **`HealthResult(status, detail, version, edition, capabilities)`**: `status`
  is `ok` / `degraded` / `down`. The diagnostics page stores version, edition
  and capabilities on the instance.
- **`EditorPage(template, context, config, script_urls, csp, static_js)`**:
  - `config` is emitted as `#office-provider-config` and must contain no secrets.
  - `script_urls` and `csp` sources must be on the instance's `browser_url`
    origin. The view drops anything else and builds the page's CSP from the
    remaining sources.
- **`RoundTripReport.step(key, label, status, detail='', remedy='')`** records a
  step; `.passed` is true only when every step passed.

Provider HTTP endpoints (callbacks, WOPI) go in `office/provider_urls.py`,
which is mounted at `/office/api/` and is currently empty.

## Outbound HTTP (`office/net.py`)

All calls from clientst0r to an editor must go through
`fetch(url, instance, max_bytes, *, method='GET', headers=None, data=None, timeout=None) -> FetchResult`.

**Destination rules**

- The URL's scheme, host and port must match the instance's `browser_url` or
  `internal_url`.
- URLs with credentials are refused.

**Address rules**

- The name is resolved once, and every resolved address must be allowed.
- The connection is pinned to those addresses, so DNS rebinding cannot switch
  the target.
- Always blocked: link-local, cloud metadata, multicast, reserved and
  documentation ranges.
- Loopback is allowed only for `same_server` instances.
- Private ranges are allowed, because the host is the approved editor.

**Request rules**

- At most 3 redirects, same origin only.
- Response size is capped.
- No proxies from the environment.
- TLS uses the system CA set plus the instance's CA bundle.

Exceptions are `DestinationNotAllowed` and its base `OfficeFetchError`.
`check_url`, `allowed_fetch`, `ip_allowed` and `resolve` are exposed for
validating callback URLs.

## Editor page and JS API

`/office/edit/<session>/` is a full-screen page with a Back link, a save-status
indicator and a collaborators slot. `static/js/office-editor.js` exposes
`window.ClientstorOffice`:

```
config, providerConfig
changesInEditor()  saving()  savedToServer({revision, savedAt})  saveFailed(message)
setState('clean'|'dirty'|'saving'|'saved'|'failed'|'readonly', detail)
setCollaborators([{id, name}])  onRetry(fn)  watchServer({interval})  renew()  isUnsaved()
```

DOM events:

- To set the state: `clientstor-office:set-state` with `{detail: {state, detail}}`.
- Every change is announced as `clientstor-office:statechange` with
  `{detail: {state, previous, detail}}`.

"Saved" is shown only for a revision that clientst0r confirmed.
`watchServer()` polls `editor_status`, which returns:

- `state`
- `currentRevision`
- `lastSavedRevision` and `lastSavedAt`
- `lastFailure`
- `expiresAt`

Leaving the page with unsaved changes asks for confirmation. On `pagehide` the
page closes the session with `sendBeacon`. Nothing on the page uses an inline
handler.

## UI

**Documents list**

- A **New Office file** menu (Word / Excel / PowerPoint / From template) when
  the user has `docs_create`.

**Document detail (file type)**

- Edit or View in editor, Download, Versions, Rename, Copy.
- Export PDF and Convert, only when the provider supports them.
- Edit is shown disabled with the reason when it cannot work.

**Asset detail**

- Office attachments with the same actions.
- **New Office file**, which creates an attachment.

**Ticket detail**

- Per-attachment actions for Office files.

**`/office/f/<code>/<pk>/` pages**

- A file page and a version history with download and restore. Restore always
  adds a new revision.

**Templates**

- Organization admins manage their organization's templates.
- Superusers manage global templates.

## Settings

### Settings → Office documents (superuser)

- **Platform settings:** enabled providers, default instance, organization
  override, retention and session lifetimes.
- **Instances:** add or edit an editor instance.
  - URLs must be `https`. Plain `http` is accepted only for a loopback
    `internal_url` in same-server mode.
  - CA bundles must be PEM certificates; private keys are refused.
  - The secret is write-only and is never rendered back.
  - `developer-only-not-a-real-secret`, `verysecretstring` and anything shorter
    than 16 characters are refused.
  - Changing the connection resets the health status.
- **Diagnostics:**
  - Configuration, reachability (through the network guard) and provider
    checks, with remedies.
  - A round trip on a disposable file with no organization.
  - The stubs report *not run*, never *pass*.
- **Install guidance** for same-server, separate-server and existing-service
  setups:
  - a checklist plus shell-quoted commands that run on the server as root;
  - Django never runs a shell command;
  - the secret is passed with `--secret-file`, never on a command line.
  - the commands run `scripts/office/install-editor.sh` (see [office/INSTALL.md](office/INSTALL.md)).
- **Quarantine:** review, download and restore quarantined saves.

### Settings → Office Documents (organization)

For holders of `org_manage_settings`:

- switch Office on or off for the organization (switching it off revokes live
  sessions);
- choose the preferred instance (only instance names are shown);
- manage the organization's templates.

### CLI

```
manage.py office_setup --plan --provider onlyoffice --mode same-server --editor-host docs.example.com
manage.py office_setup --set-secret <id> --secret-file /root/clientst0r-office-secret   # file must be chmod 600
manage.py office_setup --verify-tls <id>
manage.py office_setup --install     # prints the installer commands; installs nothing
manage.py office_setup --import-secret <file> [--instance <id>]   # file from the installer, shredded after import
manage.py office_sessions --status | --drain <id> | --resume <id>
manage.py office_purge_quarantine
```

## Audit and logging

`office/audit.py` writes `AuditLog` rows with a standard action
(create / read / export / update). `extra_data.office_event` holds the specific
event:

- sessions: `session_start`, `open`, `session_end`, `session_revoked`;
- saves: `save`, `save_failed`, `quarantine`, `quarantine_download`, `quarantine_restore`;
- files: `create`, `copy`, `convert`, `rename`, `restore`, `download`, `export`;
- templates: `template_upload`, `template_delete`;
- administration: `settings_change`, `policy_change`, `health_check`, `diagnostics_run`, `round_trip`.

Tokens, secrets and file content are never logged.

All `office.*` loggers carry `RedactSecretsFilter`, which redacts:

- `token=` and `access_token=` values;
- JSON `"token"` values;
- `Authorization` headers;
- JWT-shaped strings.

`audit/middleware.py` now redacts sensitive POST and query keys (`*secret*`,
`*token*`, `password`, …) before logging a request.

## Not implemented here

**Editor connectors.** `office/providers/onlyoffice.py` and `collabora.py` are
stubs; the ONLYOFFICE and Collabora connectors below replace them. A connector must:

- register a provider;
- add its callback / WOPI endpoints to `provider_urls.py`;
- validate the callback JWT / WOPI proof and `access_token` with `tokens.validate`;
- fetch the saved file with `net.fetch`;
- store it with `storage.save_or_quarantine(..., source='editor_save', session=...)`;
- fill `editor_page_context`, `health_check`, `diagnostics`, `round_trip` and `convert`.

**Microsoft 365.** Not started.

**Package installation.** `scripts/office/install-editor.sh` is tested against a faked host only;
no real install on Ubuntu 24.04 or Debian 12 has been run yet (see [office/INSTALL.md](office/INSTALL.md)).

**Malware scanning.** No scanner ships with the repository; see the hook above.

**Project files.** Projects have no attachment model.

**Real-Office compatibility of the blank files.** The blank `docx` / `xlsx` /
`pptx` files are built by `office/templates_files/build_blanks.py` and checked
by the tests: structure, content types and relationship targets.
python-docx and python-pptx load and resave them. They have not been opened in
Microsoft Office, ONLYOFFICE or Collabora.

ONLYOFFICE Docs connector: see [office/ONLYOFFICE.md](office/ONLYOFFICE.md).
Collabora Online connector (WOPI host): see [office/COLLABORA.md](office/COLLABORA.md).
Installing, upgrading, draining and uninstalling the editor: [docs/office/INSTALL.md](office/INSTALL.md).
