"""Collabora Online discovery and capabilities.

    get_discovery(instance, *, refresh=False) -> Discovery     (cached)
    get_server_info(instance) -> ServerInfo                    (/hosting/capabilities)
    parse_discovery(xml_bytes, instance) -> Discovery
    parse_server_info(json_bytes) -> ServerInfo

Facts used (Collabora 26.04 source, see docs/office/COLLABORA.md):

* ``GET /hosting/discovery`` returns ``<wopi-discovery><net-zone name=
  "external-https"><app name="writer|calc|impress|<mime>"><action name=
  "view|edit|editnew|..." ext="docx" urlsrc="https://host/browser/<hash>/
  cool.html?"/>``. The version hash in urlsrc changes on upgrade, so urlsrc
  is looked up per extension at runtime and cached with a TTL.
* A ``<proof-key value= modulus= exponent= oldvalue= oldmodulus=
  oldexponent=>`` element is present only when ``/etc/coolwsd/proof_key``
  exists on the server.
* ``GET /hosting/capabilities`` returns JSON with ``productName``,
  ``productVersion``, ``productVersionHash``, ``hasWopiAccessCheck`` and
  ``convert-to: {available: bool, endpoint: '/cool/convert-to'}``.

Collabora fills urlsrc from the Host it was asked on (or its ``server_name``
setting). When clientst0r fetches discovery over the internal address, the
host in urlsrc is not the one browsers use, so the origin of every urlsrc is
rewritten to the instance's browser origin (the path is kept) and
``rewritten`` records that it happened.

Everything is fetched through office.net.fetch.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

from django.core.cache import cache

from ... import net
from ...logging_filters import get_logger
from . import options

logger = get_logger('office.collabora')

MAX_DISCOVERY_BYTES = 2 * 1024 * 1024
MAX_CAPABILITIES_BYTES = 256 * 1024
CACHE_VERSION = 1

# Extensions clientst0r handles, by the discovery action that serves them.
WANTED_EXTS = ('docx', 'xlsx', 'pptx', 'doc', 'xls', 'ppt', 'docm', 'xlsm', 'pptm')


class DiscoveryError(Exception):
    """Discovery could not be fetched or parsed. Message is admin-safe."""


@dataclass
class ProofKey:
    modulus: str = ''
    exponent: str = ''
    old_modulus: str = ''
    old_exponent: str = ''

    @property
    def present(self):
        return bool(self.modulus and self.exponent)

    def to_json(self):
        return {'modulus': self.modulus, 'exponent': self.exponent,
                'old_modulus': self.old_modulus, 'old_exponent': self.old_exponent}

    @classmethod
    def from_json(cls, data):
        data = data or {}
        return cls(data.get('modulus', ''), data.get('exponent', ''),
                   data.get('old_modulus', ''), data.get('old_exponent', ''))


@dataclass
class Discovery:
    actions: dict = field(default_factory=dict)   # ext -> {action: urlsrc}
    proof_key: ProofKey = field(default_factory=ProofKey)
    capabilities_url: str = ''
    zone: str = ''
    rewritten: bool = False
    fetched_at: float = 0.0

    def urlsrc(self, ext, action):
        return (self.actions.get(ext) or {}).get(action, '')

    def has(self, ext, action):
        return bool(self.urlsrc(ext, action))

    def to_json(self):
        return {'v': CACHE_VERSION, 'actions': self.actions, 'proof_key': self.proof_key.to_json(),
                'capabilities_url': self.capabilities_url, 'zone': self.zone,
                'rewritten': self.rewritten, 'fetched_at': self.fetched_at}

    @classmethod
    def from_json(cls, data):
        return cls(actions=data.get('actions') or {},
                   proof_key=ProofKey.from_json(data.get('proof_key')),
                   capabilities_url=data.get('capabilities_url', ''), zone=data.get('zone', ''),
                   rewritten=bool(data.get('rewritten')), fetched_at=data.get('fetched_at', 0.0))


@dataclass
class ServerInfo:
    product_name: str = ''
    version: str = ''
    version_hash: str = ''
    convert_available: bool = False
    convert_endpoint: str = ''
    has_wopi_access_check: bool = False
    raw_keys: list = field(default_factory=list)

    @property
    def is_code(self):
        return is_code_product(self.product_name)

    @property
    def edition(self):
        return edition_label(self.product_name)


CODE_LABEL = 'Evaluation / development only'


def is_code_product(name):
    """CODE reports productName 'Collabora Online Development Edition'
    (the branding package decides the exact string; 'CODE' also matches)."""
    name = (name or '').lower()
    return 'development edition' in name or re.search(r'\bcode\b', name) is not None


def edition_label(name):
    name = (name or '').strip()
    if not name:
        return 'Collabora Online (product not reported)'
    if is_code_product(name):
        return f'CODE ({name}) — {CODE_LABEL}'[:100]
    return name[:100]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _origin_of(url):
    parts = urlsplit(url)
    return parts.scheme, parts.netloc


def _rewrite(urlsrc, browser_url):
    """urlsrc with its scheme and host replaced by the browser origin."""
    b = urlsplit(browser_url)
    u = urlsplit(urlsrc)
    out = urlunsplit((b.scheme, b.netloc, u.path, u.query, ''))
    return out, (u.scheme, u.netloc) != (b.scheme, b.netloc)


_PLACEHOLDER = re.compile(r'<[^>]*>')


def clean_urlsrc(urlsrc):
    """Drop WOPI-style <placeholder&> parts and make sure it ends ready for
    more query parameters."""
    urlsrc = _PLACEHOLDER.sub('', urlsrc or '')
    if '?' not in urlsrc:
        urlsrc += '?'
    elif not urlsrc.endswith(('?', '&')):
        urlsrc += '&'
    return urlsrc


def parse_discovery(xml_bytes, instance) -> Discovery:
    from defusedxml import ElementTree
    try:
        root = ElementTree.fromstring(xml_bytes)
    except Exception as e:
        raise DiscoveryError(f'Discovery is not valid XML ({type(e).__name__}).')
    if root.tag != 'wopi-discovery':
        raise DiscoveryError('The response is not a WOPI discovery document.')
    browser_scheme = urlsplit(instance.browser_url).scheme or 'https'
    zones = {z.get('name', ''): z for z in root.findall('net-zone')}
    preferred = f'external-{browser_scheme}'
    zone_name = preferred if preferred in zones else (next(iter(zones), ''))
    if not zone_name:
        raise DiscoveryError('Discovery lists no net-zone.')
    disc = Discovery(zone=zone_name, fetched_at=time.time())
    for app in zones[zone_name].findall('app'):
        for action in app.findall('action'):
            name = (action.get('name') or '').strip()
            ext = (action.get('ext') or '').strip().lower()
            urlsrc = (action.get('urlsrc') or '').strip()
            if not urlsrc:
                continue
            if app.get('name') == 'Capabilities' and name == 'getinfo':
                disc.capabilities_url, _ = _rewrite(urlsrc, instance.server_url())
                continue
            if ext not in WANTED_EXTS or not name:
                continue
            if not urlsrc.startswith(('https://', 'http://')):
                continue
            fixed, changed = _rewrite(urlsrc, instance.browser_url)
            disc.rewritten = disc.rewritten or changed
            disc.actions.setdefault(ext, {}).setdefault(name, fixed)
    pk = root.find('proof-key')
    if pk is not None:
        disc.proof_key = ProofKey(pk.get('modulus', ''), pk.get('exponent', ''),
                                  pk.get('oldmodulus', ''), pk.get('oldexponent', ''))
    if not disc.actions:
        raise DiscoveryError('Discovery lists no actions for Office formats.')
    return disc


def parse_server_info(body) -> ServerInfo:
    try:
        data = json.loads(body.decode('utf-8'))
    except Exception:
        raise DiscoveryError('/hosting/capabilities did not return JSON.')
    if not isinstance(data, dict):
        raise DiscoveryError('/hosting/capabilities did not return a JSON object.')
    conv = data.get('convert-to') or {}
    if not isinstance(conv, dict):
        conv = {}
    endpoint = str(conv.get('endpoint') or '')
    if not endpoint.startswith('/cool/convert-to'):
        endpoint = '/cool/convert-to' if conv.get('available') else ''
    return ServerInfo(
        product_name=str(data.get('productName') or '')[:100],
        version=str(data.get('productVersion') or '')[:50],
        version_hash=str(data.get('productVersionHash') or '')[:40],
        convert_available=bool(conv.get('available')),
        convert_endpoint=endpoint,
        has_wopi_access_check=bool(data.get('hasWopiAccessCheck')),
        raw_keys=sorted(str(k) for k in data.keys())[:50])


# ---------------------------------------------------------------------------
# Fetching (through office.net, cached)
# ---------------------------------------------------------------------------

def _base(instance):
    return instance.server_url().rstrip('/')


def _cache_key(instance):
    h = hashlib.sha256('|'.join((instance.server_url(), instance.browser_url)).encode()).hexdigest()
    return f'office:collabora:discovery:{instance.pk}:{h[:16]}'


def fetch_discovery(instance) -> Discovery:
    url = _base(instance) + '/hosting/discovery'
    try:
        result = net.fetch(url, instance, MAX_DISCOVERY_BYTES)
    except net.OfficeFetchError as e:
        raise DiscoveryError(f'Could not fetch discovery: {e}'[:500])
    if result.status_code != 200:
        raise DiscoveryError(f'Discovery answered HTTP {result.status_code}.')
    return parse_discovery(result.content, instance)


def get_discovery(instance, *, refresh=False) -> Discovery:
    key = _cache_key(instance)
    if not refresh:
        cached = cache.get(key)
        if cached and cached.get('v') == CACHE_VERSION:
            return Discovery.from_json(cached)
    disc = fetch_discovery(instance)
    cache.set(key, disc.to_json(), options.get(instance)['discovery_ttl_s'])
    return disc


def forget(instance):
    cache.delete(_cache_key(instance))


def get_server_info(instance, discovery=None) -> ServerInfo:
    url = (discovery.capabilities_url if discovery and discovery.capabilities_url else
           _base(instance) + '/hosting/capabilities')
    try:
        result = net.fetch(url, instance, MAX_CAPABILITIES_BYTES)
    except net.OfficeFetchError as e:
        raise DiscoveryError(f'Could not fetch /hosting/capabilities: {e}'[:500])
    if result.status_code != 200:
        raise DiscoveryError(f'/hosting/capabilities answered HTTP {result.status_code}.')
    return parse_server_info(result.content)
