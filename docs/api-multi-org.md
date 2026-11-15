# Multi-Organization REST API Access

*Issue #134 — shipped v3.17.496*

The public REST API (`/api/`) can address **multiple client organizations
through a single API key**. This is built for MSPs running a single-pane-of-glass
integration (a PSA, a custom dashboard) that needs to pull or push data across
every client without minting one key per client.

Everything here is **opt-in and backward-compatible**: keys created before this
feature — and any new key left on the default scope — behave exactly as they
did before (one key, one organization).

## Key scopes

Every API key has an **Organization Scope**, chosen when you create it under
**Settings → Users & Access → Access Management → API Keys → Create API Key** (`/api/keys/`):

| Scope | Reach |
|---|---|
| `single` *(default)* | The key's home organization only. Legacy behavior. |
| `descendants` | The home organization **plus every sub-location** beneath it in the client hierarchy (Phase 18 `Organization.parent`). |
| `all` | **Every organization the key's owner can access** — all active organizations for an MSP staff user / superuser, or the owner's active memberships for a regular org user. |

A key never grants more access than its owner already has. A broad scope only
*exposes* what the owner could already reach in the web app; it cannot escalate.

## Selecting an organization per request

All list/detail/create/update endpoints accept an optional `organization`
query parameter:

| Request | Result |
|---|---|
| *(no param)* | **`single` keys & web sessions:** the home / current org only.<br>**`descendants` / `all` keys:** every accessible org (single-pane default). |
| `?organization=<id>` or `?organization=<slug>` | Narrows to that one organization. **403** if the key may not access it. |
| `?organization=all` | Every organization the key can access. |

Example — list assets across all clients, then narrow to one:

```bash
# Every client's assets in one call (key must be scope=all)
curl -H "Authorization: Bearer itdocs_live_..." \
     https://your-domain.com/api/assets/

# Just one client
curl -H "Authorization: Bearer itdocs_live_..." \
     "https://your-domain.com/api/assets/?organization=acme-corp"
```

## Knowing which client a row belongs to

Every resource now serializes its owning organization, so a single-pane
consumer can group rows by client:

```json
{
  "id": 42,
  "organization": 7,
  "organization_name": "Acme Corp",
  "name": "ACME-DC01",
  "asset_type": "server"
}
```

`organization` is writable on create/update; `organization_name` is read-only.

## Discovering the client list

`GET /api/organizations/` returns every organization the key can address — use
it to enumerate clients before iterating:

```bash
curl -H "Authorization: Bearer itdocs_live_..." \
     https://your-domain.com/api/organizations/
```

## Creating records under a specific client

On `POST`, the target organization is resolved in this order:

1. `?organization=<id|slug>` query parameter
2. `organization` field in the request body
3. The request's primary organization (home org for a key)

The resolved organization must be in the key's accessible set, otherwise the
request is rejected with **403** and nothing is written.

```bash
curl -X POST \
     -H "Authorization: Bearer itdocs_live_..." \
     -H "Content-Type: application/json" \
     -d '{"name": "NEW-SW01", "asset_type": "switch"}' \
     "https://your-domain.com/api/assets/?organization=42"
```

## Security notes

- Cross-organization isolation is enforced on **every** request: a key can only
  ever see rows in organizations its owner is entitled to. Guessing a primary
  key from another client still returns 404.
- Password reveals and OTP generation are audited against the **row's own
  organization**, so multi-client access stays fully traceable.
- Scope is bounded by the owner's live permissions at request time — revoking a
  user's membership immediately shrinks what their `all`-scoped keys can reach.
