# API & Integrations

Full REST API with DRF browsable interface, webhook events, and RMM integrations.

---

## API Overview

| Feature | Details |
|---------|---------|
| **Base URL** | `/api/` |
| **Format** | JSON (default); browsable HTML UI at `/api/` |
| **Auth** | API key Bearer token |
| **Versioning** | URL-based (current: v1) |
| **Rate Limiting** | Configurable per key |

---

## Authentication

All API requests require an API key in the `Authorization` header:

```http
GET /api/assets/ HTTP/1.1
Host: your-server.example.com
Authorization: Bearer itdocs_live_xK9mPL3t8n...
```

Generate keys at **Profile → API Keys** (`/api/keys/`). Keys inherit your organization access and role permissions: a role without **View passwords**, **View documents** or **View assets** gets no results from those endpoints. A key stops working when its user is deactivated, or when a customer user no longer belongs to the key's organization. Keys don't expire on their own.

---

## REST API Endpoints

### Assets

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/assets/` | List assets (filterable) |
| POST | `/api/assets/` | Create asset |
| GET | `/api/assets/{id}/` | Get asset detail |
| PUT/PATCH | `/api/assets/{id}/` | Update asset |
| DELETE | `/api/assets/{id}/` | Delete asset |

### Passwords (Vault)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/passwords/` | List vault entries |
| POST | `/api/passwords/` | Create entry |
| GET | `/api/passwords/{id}/` | Get entry detail |
| GET | `/api/passwords/{id}/?reveal=true` | Get entry with plaintext password |
| GET | `/api/passwords/{id}/otp/` | Get current TOTP code |
| PUT/PATCH | `/api/passwords/{id}/` | Update entry |
| DELETE | `/api/passwords/{id}/` | Delete entry |

### Organizations

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/organizations/` | List accessible organizations |
| GET | `/api/organizations/{id}/` | Get organization detail |

### Vehicles

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/vehicles/` | List vehicles |
| POST | `/api/vehicles/` | Create vehicle |
| GET | `/api/vehicles/{id}/` | Get vehicle detail |
| PUT/PATCH | `/api/vehicles/{id}/` | Update vehicle |

### Monitoring

There are no REST endpoints for monitors. Website monitors are readable through GraphQL at `/api/v2/graphql/`: the `websiteMonitors` and `websiteMonitor` queries return configuration, current status, last response and certificate expiry. They are read-only. Webhooks can push the `monitor.down`, `monitor.up` and `monitor.check_failed` events (see [Website & WAN Monitoring](wan-monitoring.md#webhooks)).

---

## Filtering & Pagination

All list endpoints support:

```
GET /api/assets/?search=switch&ordering=-created_at&page=2&page_size=50
```

| Parameter | Description |
|-----------|-------------|
| `search` | Full-text search across key fields |
| `ordering` | Sort by any field; prefix `-` for descending |
| `page` | Page number (default: 1) |
| `page_size` | Results per page (default: 25, max: 200) |

Field-specific filters vary by endpoint — see the browsable API at `/api/` for all available filters.

---

## Webhooks

Configure webhooks at *Settings → Webhooks* (`/core/webhooks/`). Each webhook belongs to one
organization and receives a POST for the events you tick. Since v3.17.609 every event offered
in the form fires, from the data layer, so changes made through the API, the mobile app and
integration syncs count too.

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
| `workflow.started` / `workflow.completed` / `workflow.failed` | Workflow run events |
| `integration.synced` / `integration.failed` | Integration sync finished or failed |
| `user.login` / `user.logout` / `user.login_failed` / `user.password_changed` | Sign-in events for customer users |

MSP staff activity is never sent to a customer's webhooks.

### Webhook Payload Structure

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

If the webhook has a secret, each request carries an `X-Webhook-Signature` header. Secrets and
custom header values are stored encrypted; header values show as `********` on the form.
Deliveries are logged with the response status.

---

## RMM Integrations

ClientSt0r can sync devices from Remote Monitoring & Management platforms:

| Platform | Features |
|----------|---------|
| **Tactical RMM** | Devices, alerts, software, sites; device coordinates for the map |
| **NinjaOne** | Devices, alerts, software |
| **Datto RMM** | Devices, alerts, software |
| **Atera** | Devices, alerts, software |
| **ConnectWise Automate** | Devices, alerts, software |

Configure at *Integrations → RMM* (`/integrations/rmm/create/`). Sync can be triggered manually, and runs on a schedule from the built-in scheduler's `rmm_sync` task (off by default; turn it on in *Settings → Scheduler*) or the `clientst0r-rmm-sync` timer on native installs.

---

*Previous: [Security](security.md) · Back to [User Guide](README.md)*
