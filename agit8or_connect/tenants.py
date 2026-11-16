"""Tenant grants.

A token carries no tenant authority. Each request names a tenant in the
CALLER's namespace (header `Agit8or-Tenant`); the receiver resolves it
through the grant table of the connection the token belongs to:

    (connection, remote tenant id) -> local tenant, scopes subset, active

No grant, an inactive (revoked) grant, or a scope outside the grant's subset
is a refusal — the receiver never falls back to "the tenant id the caller
supplied", never looks the id up in its own namespace, and never consults
another connection's grants. Two connections from two installations (two
MSPs) to the same receiver have disjoint grant tables even when they use the
same remote tenant id strings.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Optional, Protocol, Tuple

from .errors import ConnectError, INSUFFICIENT_SCOPE, TENANT_NOT_GRANTED

TENANT_ID_RE = re.compile(r'^[A-Za-z0-9._:@-]{1,128}$')


@dataclass
class TenantGrant:
    connection_id: str
    remote_tenant_id: str
    local_tenant: object
    scopes: Tuple[str, ...] = ()
    active: bool = True
    label: str = ''


class TenantResolver(Protocol):
    def resolve(self, connection_id: str, remote_tenant_id: str) -> Optional[TenantGrant]: ...


def authorize(resolver: TenantResolver, connection_id: str, remote_tenant_id: str, scope: str,
              token_scopes=()) -> TenantGrant:
    if not isinstance(remote_tenant_id, str) or not TENANT_ID_RE.match(remote_tenant_id):
        raise ConnectError(TENANT_NOT_GRANTED, 'tenant missing or malformed', 403)
    if scope not in set(token_scopes):
        raise ConnectError(INSUFFICIENT_SCOPE, f'token lacks {scope}', 403)
    grant = resolver.resolve(connection_id, remote_tenant_id)
    if grant is None or not grant.active or grant.connection_id != connection_id:
        raise ConnectError(TENANT_NOT_GRANTED, 'tenant not granted to this connection', 403)
    if scope not in set(grant.scopes):
        raise ConnectError(INSUFFICIENT_SCOPE, f'{scope} not granted for this tenant', 403)
    return grant


@dataclass
class MemoryTenantResolver:
    grants: Dict[Tuple[str, str], TenantGrant] = field(default_factory=dict)

    def add(self, grant: TenantGrant):
        self.grants[(grant.connection_id, grant.remote_tenant_id)] = grant
        return grant

    def revoke(self, connection_id, remote_tenant_id):
        g = self.grants.get((connection_id, remote_tenant_id))
        if g:
            g.active = False

    def resolve(self, connection_id, remote_tenant_id):
        return self.grants.get((connection_id, remote_tenant_id))
