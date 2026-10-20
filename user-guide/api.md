# API & Integrations

A JSON REST API for assets, contacts, documents, passwords, tags and organizations; an optional GraphQL endpoint; outgoing webhooks; and RMM integrations.

---

## API Overview

| Feature | Details |
|---------|---------|
| **Base URL** | `/api/` (one version; there is no `/api/v1/` prefix) |
| **Format** | JSON. The browsable HTML view is only on when `DEBUG` is on. |
| **Auth** | API key as a Bearer token, or your signed-in web session |
| **Pagination** | 50 results per page, `?page=N` |
| **Rate limit** | 1,000 requests per hour per user (all of that user's keys together) |

The mobile app uses its own API under `/api/mobile/v1/`; it is not covered here.

---

## API Keys

Create keys at **Admin → Access Management → API Keys**, or go straight to `/api/keys/`: any signed-in user can make keys for themselves, and organization owners and admins see every key in their organization. The key is shown once, when it is created; only a hash of it is stored.

Send it in the `Authorization` header:

```http
GET /api/assets/ HTTP/1.1
Host: your-server.example.com
Authorization: Bearer itdocs_live_xK9mPL3t8n...
```

Each key has two settings:

**Permission level** caps what the key can do. A key never does more than its owner's own role allows; the level can only take away from that.

| Level | Can |
|-------|-----|
| **Read-Only** | Read. No creating, editing, deleting, and no password, OTP or license-key reveals. |
| **Editor** | Read, create and edit, and reveal passwords. No deleting, and no publishing or unpublishing documents. |
| **Admin** / **Owner** | Everything the owner's role allows. |

**Organization scope** sets which customers the key can reach:

| Scope | Reaches |
|-------|---------|
| **Single organization** (default) | The organization the key was created in. |
| **Organization + sub-locations** | That organization and the organizations under it. |
| **All accessible organizations** | Every customer the owner can reach. |

A key stops working when it is turned off or deleted, when its user is deactivated, or when a customer user no longer belongs to the key's organization. Keys don't expire on their own. Every request made with a key is written to the audit log.

---

## Permissions

The API applies the same role permissions as the web app, per customer:

- Reading assets and contacts needs **View assets**; documents need **View documents**; passwords need **View passwords**. Rows you can't view are left out of lists and answer 404.
- Creating, editing and deleting need the matching **Create**, **Edit** and **Delete** permission in that customer (assets and contacts use the asset permissions).
- Publishing or unpublishing a document, through the `publish` action or the `is_published` field, needs **Publish documents**.
- Revealing a password goes through the same checks as the web vault: the reveal permission, reveal approval when the entry requires it, and vault access rules. Every reveal is audited.
- Tags can be read by anyone in scope; only superusers can create, rename or delete them, as in the web app. Tags attached to a record must belong to the record's organization.

---

## Choosing an Organization

Add `?organization=<id or slug>` to read or write in one customer, or `?organization=all` for every customer in the key's scope. Without it, a single-organization key (and a web session) uses its own organization, and a multi-organization key covers its whole scope. Asking for a customer outside the scope returns 403.

On create, the organization comes from `?organization=`, then the `organization` field in the body, then the default above.

---

## Endpoints

### Assets — `/api/assets/`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/assets/` | List assets |
| POST | `/api/assets/` | Create an asset |
| GET | `/api/assets/{id}/` | Asset detail |
| PUT/PATCH | `/api/assets/{id}/` | Update |
| DELETE | `/api/assets/{id}/` | Delete |

Filters: `asset_type`, `needs_reorder`. Search (`?search=`) covers name, serial number, model, manufacturer, MAC address and IP address. Ordering: `name`, `created_at`, `updated_at`.

### Contacts — `/api/contacts/`

Same methods as assets. Search covers first name, last name, email and phone. Ordering: `last_name`, `first_name`, `created_at`.

### Documents — `/api/documents/`

Same methods as assets, plus:

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/documents/{id}/publish/` | Publish |
| POST | `/api/documents/{id}/archive/` | Archive |

Filters: `is_published`, `is_template`, `is_archived`, `category`, `content_type`. Search covers title and body. Ordering: `title`, `created_at`, `updated_at`.

### Passwords — `/api/passwords/`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/passwords/` | List entries (metadata only) |
| POST | `/api/passwords/` | Create an entry |
| GET | `/api/passwords/{id}/` | Entry detail; the password and license key show as `**********` |
| GET | `/api/passwords/{id}/?reveal=true` | Entry detail with the password, license key and current OTP code |
| POST | `/api/passwords/{id}/reveal/` | Just the password (and license key, if any) |
| GET | `/api/passwords/{id}/otp/` | Current TOTP code, for OTP entries |
| PUT/PATCH | `/api/passwords/{id}/` | Update |
| DELETE | `/api/passwords/{id}/` | Delete |

Lists include the customer's shared entries and your own personal entries, never other users' personal entries. Filter: `password_type`. Search covers title, username and URL. Ordering: `title`, `created_at`, `updated_at`. A refused reveal answers 403 with an `error` message (and `"requires_approval": true` when the entry needs approval first).

### Tags — `/api/tags/`

List and read tags; create, update and delete for superusers. Search covers name.

### Organizations — `/api/organizations/`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/organizations/` | Active organizations in the key's scope |
| GET | `/api/organizations/{id}/` | Organization detail |

Read-only. A multi-organization integration can use it to find which customers it can query.

### Not in the REST API

Website monitors, WAN connections, locations, tickets and the other modules have no REST endpoints. Website monitors, locations, diagrams and expirations can be read through GraphQL (below). Webhooks can push monitor and WAN events (see [Webhooks](#webhooks)).

---

## Filtering, Search & Pages

```
GET /api/assets/?search=switch&asset_type=server&ordering=-created_at&page=2
```

| Parameter | Description |
|-----------|-------------|
| `search` | Text search over the fields listed for each endpoint |
| `ordering` | One of the fields listed for each endpoint; prefix `-` for descending |
| `page` | Page number (default 1); 50 results per page |
| `organization` | See [Choosing an Organization](#choosing-an-organization) |

List responses have `count`, `next`, `previous` and `results`.

---

## GraphQL

An optional GraphQL endpoint is at `/api/v2/graphql/`. It needs the `graphene-django` package (from `requirements-graphql.txt`; `update.sh` installs it on native installs, the Docker image doesn't include it).

- It uses your signed-in web session and Django's CSRF token. **API keys are not accepted** there.
- Queries include `me`, `organizations`, `assets`, `passwords` (no secrets), `documents`, `diagrams`, `locations`, `websiteMonitors`, `expirations`, `expiringSoon`, `dashboardStats`, and single-item versions of most of them.
- Mutations: `createAsset`, `updateAsset`, `deleteAsset`, `createDocument`.
- The same view and write permissions apply as in the REST API.

---

## Webhooks

Configure webhooks at *Settings → Webhooks* (`/core/webhooks/`). Each webhook belongs to one
organization and receives a POST for the events you tick. Every event offered in the form
fires, from the data layer, so changes made through the API, the mobile app and integration
syncs count too.

### Events

| Event | Trigger |
|-------|---------|
| `asset.created` / `asset.updated` / `asset.deleted` | Asset added, changed, removed |
| `document.created` / `document.updated` / `document.deleted` | Document added, changed, removed |
| `password.created` / `password.updated` / `password.deleted` | Vault entry added, changed, removed — metadata only, never the secret |
| `password.accessed` | A password was revealed |
| `location.created` / `location.updated` / `location.deleted` | Location added, changed, removed |
| `organization.updated` | Organization details changed |
| `monitor.down` / `monitor.up` | A website monitor is declared down (after two failed checks in a row) or recovers |
| `monitor.check_failed` | A single website check failed |
| `wan.down` / `wan.up` | A WAN connection is declared down (after two checks in a row with no answer) or answers again |
| `wan.check_failed` | A single WAN check got no answer |
| `workflow.started` / `workflow.completed` / `workflow.failed` | Workflow run events |
| `integration.synced` / `integration.failed` | Integration sync finished or failed |
| `user.login` / `user.logout` / `user.login_failed` / `user.password_changed` | Sign-in events for customer users |

MSP staff activity is never sent to a customer's webhooks.

### Payload

```json
{
  "event": "monitor.down",
  "timestamp": 1760538720,
  "data": {
    "monitor_id": 7,
    "name": "Main Website",
    "url": "https://www.example.com",
    "status": "down",
    "status_code": null,
    "response_time_ms": null,
    "consecutive_failures": 2,
    "error": "Connection timed out",
    "checked_at": "2026-10-15T14:32:00+00:00"
  },
  "webhook_id": 3,
  "organization": "acme-corp"
}
```

`timestamp` is Unix seconds; `organization` is the organization's slug. The WAN payload fields are listed in [Website & WAN Monitoring](wan-monitoring.md#webhooks).

### Signature

If the webhook has a secret, each request carries `X-Webhook-Signature: sha256=<hex>`, the
HMAC-SHA256 of the raw request body keyed with the secret. To verify, compute the same HMAC over
the body exactly as received and compare in constant time:

```python
import hashlib, hmac

def valid(body: bytes, header: str, secret: str) -> bool:
    expected = 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header or '')
```

Secrets and custom header values are stored encrypted; header values show as `********` on the
form. Deliveries are sent after the change is saved and are logged with the response status.

---

## RMM Integrations

Clientst0r can sync devices from Remote Monitoring & Management platforms:

| Platform | Syncs |
|----------|-------|
| **Tactical RMM** | Devices, alerts, software; device coordinates for the map |
| **NinjaOne** | Devices, alerts, software |
| **Datto RMM** | Devices, alerts, software |
| **Atera** | Devices, alerts, software |
| **ConnectWise Automate** | Devices, alerts, software |

Configure at *Integrations → RMM* (`/integrations/rmm/create/`). Sync can be triggered manually, and runs on a schedule from the built-in scheduler's `rmm_sync` task (off by default; turn it on in *Settings → Scheduler*) or the `clientst0r-rmm-sync` timer on native installs.

---

*Previous: [Security](security.md) · Back to [User Guide](README.md)*
