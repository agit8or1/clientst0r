# GraphQL API

An optional, mostly read-only GraphQL endpoint next to the [REST API](user-guide/api.md).

## Endpoint

```
POST /api/v2/graphql/
```

It is only mounted when the optional dependencies are installed
(`pip install -r requirements-graphql.txt`). `update.sh` installs them on native
installs; the Docker image does not include them. The in-browser GraphiQL IDE is
served at the same URL only when `DEBUG=True`.

## Authentication and scoping

The endpoint uses your normal **web session** (sign in first, including 2FA), so
requests need Django's CSRF token in the `X-CSRFToken` header. **API keys are not
accepted**, and there is no token or JWT sign-in. For scripts and integrations, use
the REST API with an API key.

Every query returns only data from organizations you belong to (MSP staff and
superusers see all organizations). The module view permissions apply (**View
assets**, **View passwords**, **View documents**). Other users' personal vault
entries are never listed, and password entries expose metadata only. Mutations
check your role in the target organization (`assets_create`, `assets_edit`,
`assets_delete`, `docs_create`).

Unlike the REST API, GraphQL requests are not rate-limited.

## Queries

Lists are plain lists (no paging or Relay connections). Arguments in brackets are
optional.

| Query | Returns |
|-------|---------|
| `me` | The signed-in user |
| `user(id)`, `users` | Users you can see |
| `organization(id)`, `organizations`, `myOrganization` | Organizations, with `assetCount` and `passwordCount` |
| `asset(id)`, `assets(organizationId)` | Assets |
| `assetTypes` | Asset types |
| `password(id)`, `passwords(organizationId)` | Vault entry metadata: title, username, URL, type. Never the secret. |
| `document(id)`, `documents(organizationId)` | Documents, including the body |
| `diagram(id)`, `diagrams(organizationId)` | Diagrams, including the diagram XML |
| `location(id)`, `locations` | Locations |
| `websiteMonitor(id)`, `websiteMonitors(organizationId)` | Website monitors: URL, status, last check, status code, response time, SSL and domain expiry |
| `expirations(organizationId)`, `expiringSoon(days = 30)` | Tracked expirations, with `daysUntilExpiry` |
| `dashboardStats` | Counts of organizations, assets, passwords, documents, diagrams and active monitors |

Use the GraphiQL schema explorer (in development) for every field of every type.

## Mutations

| Mutation | Arguments |
|----------|-----------|
| `createAsset` | `name!`, `organizationId!`, `assetType`, `manufacturer`, `model`, `serialNumber` |
| `updateAsset` | `id!`, `name`, `manufacturer`, `model`, `serialNumber` |
| `deleteAsset` | `id!` |
| `createDocument` | `title!`, `content!`, `organizationId!` |

Each returns `success` and `errors`, plus the `asset` or `document` it created or
changed.

## Examples

```graphql
query {
  me { username }
  websiteMonitors {
    name
    url
    status
    lastCheckedAt
    sslExpiresAt
    organization { name }
  }
}
```

```graphql
query ($org: Int) {
  assets(organizationId: $org) {
    id
    name
    assetType
    serialNumber
  }
}
```

```graphql
mutation {
  createAsset(name: "Core Switch", organizationId: 3, assetType: "switch") {
    success
    errors
    asset { id name }
  }
}
```

From a page in the app (same session), send the CSRF token with the request:

```javascript
const csrf = document.cookie.match(/csrftoken=([^;]+)/)[1];
const res = await fetch('/api/v2/graphql/', {
  method: 'POST',
  credentials: 'same-origin',
  headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
  body: JSON.stringify({ query: '{ me { username } }' }),
});
console.log(await res.json());
```

## Errors

Errors come back in the standard GraphQL shape:

```json
{
  "data": null,
  "errors": [
    {
      "message": "Authentication required",
      "locations": [{"line": 2, "column": 3}],
      "path": ["assets"]
    }
  ]
}
```

## Support

- **Issues**: https://github.com/agit8or1/clientst0r/issues
