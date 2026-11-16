"""Discovery: GET {base}/.well-known/agit8or-connect (PROTOCOL.md §4).

Parsing is tolerant by design: unknown members are ignored at every level
(a strict schema that rejected an added field once broke Rem0te pairing —
Rem0te audit R2). Only what the protocol needs is checked. Every endpoint
must be on the same origin as the discovery URL, so a discovery document
cannot point a client at some other host.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlsplit

from . import PROTOCOL, SUPPORTED_VERSIONS
from .errors import ConnectError, INVALID_REQUEST, UNSUPPORTED_VERSION
from .scopes import Catalog

WELL_KNOWN = '/.well-known/agit8or-connect'
ENDPOINT_NAMES = ('pairing', 'pairing_status', 'token', 'jwks', 'health', 'capabilities', 'events', 'test',
                  'api_base')
REQUIRED_ENDPOINTS = ('pairing', 'pairing_status', 'token', 'jwks', 'events')
MAX_DOCUMENT = 256 * 1024


def origin(url: str) -> str:
    p = urlsplit(url)
    port = p.port or (443 if p.scheme == 'https' else 80)
    return f'{p.scheme.lower()}://{(p.hostname or "").lower()}:{port}'


def discovery_url(base_url: str) -> str:
    base = (base_url or '').strip().rstrip('/')
    if base.endswith(WELL_KNOWN):
        return base
    return base + WELL_KNOWN


def build_document(*, app: dict, endpoints: dict, catalog: Catalog, events: List[str], tenant_model: dict,
                   versions=SUPPORTED_VERSIONS, extra: Optional[dict] = None) -> dict:
    doc = {'protocol': PROTOCOL, 'versions': list(versions),
           'app': {k: app.get(k, '') for k in ('type', 'version', 'display_name', 'installation_id')},
           'endpoints': dict(endpoints), 'capabilities': catalog.as_list(), 'events': list(events),
           'tenant_model': dict(tenant_model),
           'security': {'token_auth': ['private_key_jwt'], 'token_type': 'DPoP', 'alg': ['EdDSA'],
                        'access_token_max_lifetime': 300, 'webhook_signature': 'ed25519'}}
    doc.update(extra or {})
    return doc


@dataclass
class DiscoveryInfo:
    url: str
    app_type: str
    app_version: str
    display_name: str
    installation_id: str
    version: str
    endpoints: dict
    catalog: Catalog
    events: List[str] = field(default_factory=list)
    tenant_model: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


def negotiate(theirs) -> str:
    common = [v for v in SUPPORTED_VERSIONS if v in (theirs or [])]
    if not common:
        raise ConnectError(UNSUPPORTED_VERSION, 'no common Agit8or Connect protocol version')
    return max(common, key=int)


def parse_document(doc, url: str) -> DiscoveryInfo:
    if not isinstance(doc, dict) or doc.get('protocol') != PROTOCOL:
        raise ConnectError(INVALID_REQUEST, 'not an Agit8or Connect discovery document')
    version = negotiate([str(v) for v in doc.get('versions') or [] if isinstance(v, (str, int))])
    app = doc.get('app') if isinstance(doc.get('app'), dict) else {}
    for k in ('type', 'installation_id'):
        if not isinstance(app.get(k), str) or not app[k] or len(app[k]) > 128:
            raise ConnectError(INVALID_REQUEST, f'discovery app.{k} missing')
    eps = doc.get('endpoints') if isinstance(doc.get('endpoints'), dict) else {}
    want = origin(url)
    endpoints = {}
    for name in ENDPOINT_NAMES:
        v = eps.get(name)
        if not isinstance(v, str) or not v:
            if name in REQUIRED_ENDPOINTS:
                raise ConnectError(INVALID_REQUEST, f'discovery endpoint {name} missing')
            continue
        if origin(v.replace('{connection_id}', 'x').replace('{request_id}', 'x')) != want:
            raise ConnectError(INVALID_REQUEST, f'discovery endpoint {name} is on another origin')
        endpoints[name] = v
    return DiscoveryInfo(url=url, app_type=app['type'], app_version=str(app.get('version') or '')[:64],
                         display_name=str(app.get('display_name') or '')[:200],
                         installation_id=app['installation_id'], version=version, endpoints=endpoints,
                         catalog=Catalog.from_list(doc.get('capabilities')),
                         events=[e for e in doc.get('events') or [] if isinstance(e, str)][:200],
                         tenant_model=doc.get('tenant_model') if isinstance(doc.get('tenant_model'), dict) else {},
                         raw=doc)


def fetch(transport, base_url: str) -> DiscoveryInfo:
    url = discovery_url(base_url)
    r = transport.request('GET', url, headers={'Accept': 'application/json'}, body=None)
    if r.status != 200:
        raise ConnectError('transport_error', f'discovery answered HTTP {r.status}', 502)
    if len(r.body) > MAX_DOCUMENT:
        raise ConnectError('too_large', 'discovery document too large', 502)
    try:
        doc = json.loads(r.body)
    except ValueError as e:
        raise ConnectError(INVALID_REQUEST, 'discovery document is not JSON', 502) from e
    return parse_document(doc, url)
