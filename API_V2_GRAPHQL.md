# Client St0r API v2 - GraphQL

Modern GraphQL API for Client St0r, providing flexible and efficient data querying alongside the REST API v1.

## Quick Start

### GraphQL Endpoint

```
POST /api/v2/graphql/
```

### GraphQL Playground (Development)

Visit `http://your-domain/api/v2/graphql/playground/` for an interactive GraphQL IDE.

## Authentication

### Using JWT Tokens

```graphql
mutation {
  tokenAuth(username: "your_username", password: "your_password") {
    token
    refreshToken
  }
}
```

Include the token in headers:
```
Authorization: JWT your-token-here
```

## Example Queries

### Get Current User

```graphql
query {
  me {
    id
    username
    email
    firstName
    lastName
  }
}
```

### List Organizations

```graphql
query {
  organizations {
    edges {
      node {
        id
        name
        memberCount
        assetCount
        passwordCount
      }
    }
  }
}
```

### Get Assets with Filtering

```graphql
query {
  assets(organization: 1, isActive: true, name_Icontains: "server") {
    edges {
      node {
        id
        name
        assetType {
          name
        }
        manufacturer
        model
        serialNumber
        organization {
          name
        }
      }
    }
  }
}
```

### Search Documents

```graphql
query {
  documents(title_Icontains: "network", organization: 1) {
    edges {
      node {
        id
        title
        category {
          name
        }
        createdAt
        updatedAt
      }
    }
  }
}
```

### Get Expiring Items

```graphql
query {
  expiringSoon(days: 30) {
    id
    name
    type
    expirationDate
    daysUntilExpiry
    organization {
      name
    }
  }
}
```

### Dashboard Statistics

```graphql
query {
  dashboardStats {
    totalOrganizations
    totalAssets
    totalPasswords
    totalDocuments
    totalDiagrams
    activeMonitors
  }
}
```

## Example Mutations

### Create Asset

```graphql
mutation {
  createAsset(
    name: "New Server"
    assetTypeId: 1
    organizationId: 1
    manufacturer: "Dell"
    model: "PowerEdge R740"
    serialNumber: "ABC123"
    description: "Production web server"
  ) {
    success
    errors
    asset {
      id
      name
      serialNumber
    }
  }
}
```

### Update Asset

```graphql
mutation {
  updateAsset(
    id: 123
    name: "Updated Server Name"
    description: "Updated description"
    isActive: true
  ) {
    success
    errors
    asset {
      id
      name
      description
    }
  }
}
```

### Delete Asset

```graphql
mutation {
  deleteAsset(id: 123) {
    success
    errors
  }
}
```

### Create Document

```graphql
mutation {
  createDocument(
    title: "Network Documentation"
    content: "Complete network topology and configuration details..."
    organizationId: 1
    categoryId: 5
  ) {
    success
    errors
    document {
      id
      title
      createdAt
    }
  }
}
```

## Advanced Queries

### Nested Relationships

```graphql
query {
  organizations {
    edges {
      node {
        id
        name
        assets {
          edges {
            node {
              name
              assetType {
                name
              }
            }
          }
        }
        passwords {
          totalCount
        }
        documents {
          totalCount
        }
      }
    }
  }
}
```

### Pagination

```graphql
query {
  assets(first: 10, after: "cursor-here") {
    pageInfo {
      hasNextPage
      hasPreviousPage
      startCursor
      endCursor
    }
    edges {
      cursor
      node {
        id
        name
      }
    }
  }
}
```

### Filtering and Sorting

```graphql
query {
  assets(
    organization: 1
    assetType: 2
    isActive: true
    name_Icontains: "server"
    orderBy: "-created_at"
  ) {
    edges {
      node {
        id
        name
        createdAt
      }
    }
  }
}
```

## Available Filters

### String Filters
- `exact`: Exact match
- `iexact`: Case-insensitive exact match
- `contains`: Contains substring
- `icontains`: Case-insensitive contains
- `startswith`: Starts with
- `istartswith`: Case-insensitive starts with
- `endswith`: Ends with
- `iendswith`: Case-insensitive ends with

### Numeric Filters
- `exact`: Exact match
- `lt`: Less than
- `lte`: Less than or equal
- `gt`: Greater than
- `gte`: Greater than or equal

### Boolean Filters
- `exact`: true or false

### Date Filters
- `exact`: Exact date
- `lt`: Before date
- `lte`: Before or on date
- `gt`: After date
- `gte`: After or on date
- `year`: Year
- `month`: Month
- `day`: Day

## Introspection

Get the complete schema:

```graphql
query {
  __schema {
    types {
      name
      description
    }
  }
}
```

Get type details:

```graphql
query {
  __type(name: "AssetType") {
    name
    fields {
      name
      type {
        name
      }
    }
  }
}
```

## Error Handling

Errors are returned in a structured format:

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

## Rate Limiting

- **Authenticated**: 1000 requests per hour
- **Unauthenticated**: 100 requests per hour

## Best Practices

### 1. Request Only What You Need

```graphql
# ✅ Good - Request specific fields
query {
  assets {
    edges {
      node {
        id
        name
      }
    }
  }
}

# ❌ Bad - Requesting everything
query {
  assets {
    edges {
      node {
        id
        name
        description
        serialNumber
        manufacturer
        model
        ... # All fields
      }
    }
  }
}
```

### 2. Use Fragments for Reusability

```graphql
fragment AssetDetails on AssetType {
  id
  name
  manufacturer
  model
  serialNumber
}

query {
  asset(id: 1) {
    ...AssetDetails
  }
}
```

### 3. Batch Queries

```graphql
query {
  assets: assets(first: 10) {
    edges {
      node {
        id
        name
      }
    }
  }
  documents: documents(first: 10) {
    edges {
      node {
        id
        title
      }
    }
  }
}
```

### 4. Use Variables

```graphql
query GetAsset($id: Int!) {
  asset(id: $id) {
    id
    name
    description
  }
}

# Variables
{
  "id": 123
}
```

## Client Libraries

### JavaScript/TypeScript

```bash
npm install @apollo/client graphql
```

```javascript
import { ApolloClient, InMemoryCache, gql } from '@apollo/client';

const client = new ApolloClient({
  uri: 'https://your-domain/api/v2/graphql/',
  cache: new InMemoryCache(),
  headers: {
    Authorization: `JWT ${token}`
  }
});

const GET_ASSETS = gql`
  query {
    assets {
      edges {
        node {
          id
          name
        }
      }
    }
  }
`;

client.query({ query: GET_ASSETS })
  .then(result => console.log(result));
```

### Python

```bash
pip install gql[all]
```

```python
from gql import gql, Client
from gql.transport.requests import RequestsHTTPTransport

transport = RequestsHTTPTransport(
    url='https://your-domain/api/v2/graphql/',
    headers={'Authorization': f'JWT {token}'}
)

client = Client(transport=transport, fetch_schema_from_transport=True)

query = gql('''
    query {
        assets {
            edges {
                node {
                    id
                    name
                }
            }
        }
    }
''')

result = client.execute(query)
print(result)
```

## Subscriptions (Coming Soon)

Real-time updates using WebSocket subscriptions:

```graphql
subscription {
  assetUpdated {
    id
    name
    updatedAt
  }
}
```

## Migration from REST API v1

| REST API v1 | GraphQL API v2 |
|-------------|----------------|
| `GET /api/v1/assets/` | `query { assets { ... } }` |
| `GET /api/v1/assets/:id/` | `query { asset(id: X) { ... } }` |
| `POST /api/v1/assets/` | `mutation { createAsset(...) { ... } }` |
| `PUT /api/v1/assets/:id/` | `mutation { updateAsset(id: X, ...) { ... } }` |
| `DELETE /api/v1/assets/:id/` | `mutation { deleteAsset(id: X) { ... } }` |

## Support

- **Documentation**: https://github.com/agit8or1/clientst0r/wiki/GraphQL-API
- **Issues**: https://github.com/agit8or1/clientst0r/issues
- **Discussions**: https://github.com/agit8or1/clientst0r/discussions
