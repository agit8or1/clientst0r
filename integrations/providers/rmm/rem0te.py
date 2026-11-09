"""
Rem0te Provider

Rem0te is a self-hosted remote support portal built on RustDesk.

API documentation: docs/PUBLIC-API.md in the Rem0te repository
(https://github.com/agit8or1/rem0te). Public API under /api/v1/pub/v1/.
Authentication: Bearer API key (rk_...), scope computers:read.

A Rem0te API key belongs to exactly one business and sees nothing outside
it, so a Rem0te connection is always single-customer: one key, one business,
one ClientSt0r organization. The business behind the key is recorded on the
first sync, and a later sync refuses to run if the key now answers for a
different business, rather than filing that business's computers here.
"""
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from urllib.parse import quote

from ..rmm_base import BaseRMMProvider, ProviderError, AuthenticationError

logger = logging.getLogger('integrations')

API_PATH = '/api/v1/pub/v1'
BUSINESS_PIN = 'rem0te_business_id'


def site_root(url):
    """The Rem0te host, whether the API path was entered with it or not."""
    url = (url or '').strip().rstrip('/')
    if url.endswith(API_PATH):
        url = url[:-len(API_PATH)]
    return url.rstrip('/')


class Rem0teProvider(BaseRMMProvider):
    """
    Rem0te provider implementation.

    Supports:
    - Computer inventory sync (hostname, serial, MAC, OS, IP, liveness)

    Rem0te has no alerts or software inventory in its public API.
    """

    provider_name = 'Rem0te'
    supports_alerts = False
    supports_software = False

    PLATFORM_MAP = {
        'windows': 'windows',
        'linux': 'linux',
        'macos': 'macos',
        'darwin': 'macos',
        'mac': 'macos',
    }

    def __init__(self, connection):
        super().__init__(connection)
        self.base_url = site_root(self.base_url) + API_PATH

    def _get_auth_headers(self) -> Dict[str, str]:
        api_key = self.connection.get_credentials().get('api_key')
        if not api_key:
            raise AuthenticationError('Rem0te API key not configured')
        return {
            'Authorization': f'Bearer {api_key}',
            'Accept': 'application/json',
        }

    def whoami(self) -> Dict[str, Any]:
        """The key's business and scopes. No `data` wrapper on this route."""
        data = self._make_request('GET', '/whoami').json()
        if not isinstance(data, dict) or not data.get('businessId'):
            raise ProviderError('Rem0te did not say which business this API key belongs to.')
        return data

    def test_connection(self) -> bool:
        try:
            info = self.whoami()
        except Exception as e:
            logger.error(f"Rem0te connection test failed: {e}")
            return False
        if 'computers:read' not in (info.get('scopes') or []):
            # Rem0te answers a missing scope with 401 on the route itself, so
            # say which scope is missing here instead of "authentication failed".
            logger.error('Rem0te API key lacks the computers:read scope')
            return False
        return True

    def _check_business(self) -> str:
        """The key's business ID, refusing a key that changed business."""
        business_id = str(self.whoami()['businessId'])
        mappings = self.connection.field_mappings or {}
        pinned = mappings.get(BUSINESS_PIN)
        if pinned and pinned != business_id:
            raise ProviderError(
                'This Rem0te API key belongs to a different business than the one this '
                'connection was set up for. Sync stopped so that business\'s computers are '
                'not filed under this organization. Use a key for the original business, '
                'or create a separate connection for the new one.')
        if not pinned and self.connection.pk:
            mappings[BUSINESS_PIN] = business_id
            self.connection.field_mappings = mappings
            self.connection.save(update_fields=['field_mappings'])
        return business_id

    def list_devices(self, page_size: int = 100, updated_since: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Every computer in the key's business. Only this route paginates."""
        business_id = self._check_business()
        devices = []
        page, limit = 1, 200
        while True:
            body = self._make_request('GET', '/computers', params={'page': page, 'limit': limit}).json()
            data = (body or {}).get('data') or {}
            for raw in data.get('endpoints') or []:
                # The API is scoped to the key's business; anything else is
                # dropped rather than trusted.
                if str(raw.get('customerId') or '') != business_id:
                    logger.warning('Rem0te: skipped computer %s from another business', raw.get('id'))
                    continue
                if raw.get('status') == 'ARCHIVED':
                    continue
                try:
                    devices.append(self.normalize_device(raw))
                except Exception as e:
                    logger.error(f"Error normalizing Rem0te computer {raw.get('id')}: {e}")
            pages = int(data.get('pages') or 1)
            if page >= pages:
                break
            page += 1
        logger.info(f"Rem0te: Retrieved {len(devices)} computers")
        return devices

    def get_device(self, device_id: str) -> Dict[str, Any]:
        body = self._make_request('GET', f"/computers/{quote(str(device_id), safe='')}").json()
        return self.normalize_device((body or {}).get('data') or {})

    def list_alerts(self, device_id=None, status=None, updated_since=None, page_size=100) -> List[Dict]:
        return []

    def normalize_device(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Rem0te computer structure (GET /computers):
        {
            "id": "cmtaiwkdb0017za3stnccaho1",
            "name": "BACKOFFICE-01",
            "hostname": "BACKOFFICE-01",
            "status": "OFFLINE",
            "platform": "Windows",
            "osVersion": "Microsoft Windows NT 10.0.26100.0",
            "ipAddress": "203.0.113.26",
            "macAddress": "00:11:22:33:44:55",
            "serialNumber": "ABC123",
            "isOnline": false,
            "lastSeenAt": "2026-08-24T20:05:12.095Z",
            "customerId": "cmtaiwkcv000rza3semyybks5",
            "customer": {"id": "...", "name": "Cascade Accounting"},
            "site": {"id": "...", "name": "Main office"},
            "rustdeskNode": {"rustdeskId": "145925926", "lastSeenAt": "...", "hasPassword": true}
        }
        """
        platform = str(raw_data.get('platform') or '').lower()
        os_type = next((v for k, v in self.PLATFORM_MAP.items() if k in platform), 'other' if platform else '')
        customer = raw_data.get('customer') or {}
        site = raw_data.get('site') or {}
        node = raw_data.get('rustdeskNode') or {}
        hostname = raw_data.get('hostname') or raw_data.get('name') or ''
        # Never keep a credential, even if a future API version returned one.
        raw = {k: v for k, v in raw_data.items() if k != 'rustdeskNode'}
        raw['rustdeskNode'] = {k: v for k, v in node.items()
                               if k in ('rustdeskId', 'lastSeenAt', 'hasPassword')} if node else None
        return {
            'external_id': str(raw_data.get('id') or ''),
            'device_name': raw_data.get('name') or hostname,
            'device_type': 'unknown',
            'manufacturer': '',
            'model': '',
            'serial_number': raw_data.get('serialNumber') or '',
            'os_type': os_type,
            'os_version': raw_data.get('osVersion') or '',
            'hostname': hostname,
            'ip_address': raw_data.get('ipAddress') or '',
            'mac_address': raw_data.get('macAddress') or '',
            'is_online': bool(raw_data.get('isOnline')),
            'last_seen': self._parse_datetime(raw_data.get('lastSeenAt')),
            'client_id': str(raw_data.get('customerId') or customer.get('id') or ''),
            'client_name': customer.get('name') or '',
            'site_id': str(site.get('id') or ''),
            'site_name': site.get('name') or '',
            'raw_data': raw,
        }

    # The computer's page in the Rem0te web app (apps/web/app/(app)/endpoints/[id]).
    # It opens with the technician's own Rem0te sign-in, which decides whether
    # they may see or connect to it; the link carries no key or credential.
    console_link_mode = 'static'
    console_link_label = 'Connect with Rem0te'

    @classmethod
    def console_hosts(cls, connection):
        from .console import host_of
        host = host_of(site_root(getattr(connection, 'console_base_url', '') or connection.base_url))
        return {host} if host else set()

    @classmethod
    def device_console_url(cls, connection, device):
        base = site_root(getattr(connection, 'console_base_url', '') or connection.base_url)
        if not base or not device.external_id:
            return ''
        return f"{base}/endpoints/{quote(device.external_id, safe='')}"


# --- Ticket integration pairing (docs/contracts/ticket-rmm-v1) -------------
#
# Separate from the inventory API key above. Pairing a Rem0te connection as a
# ticket processor needs two shared secrets — one ClientSt0r signs its
# requests with, one Rem0te signs its callbacks and inference calls with —
# plus a key ID both sides quote. The secrets live in the connection's
# encrypted credentials; the switch, key ID, processing location and the
# capabilities Rem0te last advertised live in field_mappings.
#
# Turning the pairing on, or marking it on-premises, widens what ClientSt0r
# will send, so it goes through a protected change (tech_access.protected):
# a second administrator approves it. Changing a secret on a live pairing
# switches the pairing off until it is approved again.

INTEGRATION_ENABLED = 'rem0te_integration_enabled'
INTEGRATION_KEY_ID = 'rem0te_integration_key_id'
INTEGRATION_LOCATION = 'rem0te_processing_location'
INTEGRATION_CAPS = 'rem0te_capabilities'
LOCATIONS = (('hosted', 'Hosted / off-premises'), ('local', 'On-premises'))


def integration_settings(connection) -> Dict[str, Any]:
    mappings = connection.field_mappings or {}
    creds = connection.get_credentials() or {}
    has_secrets = bool(creds.get('integration_outbound_secret') and creds.get('integration_inbound_secret'))
    key_id = str(mappings.get(INTEGRATION_KEY_ID) or '')
    return {
        'enabled': bool(mappings.get(INTEGRATION_ENABLED)) and has_secrets and bool(key_id)
                   and connection.provider_type == 'rem0te' and connection.is_active,
        'requested': bool(mappings.get(INTEGRATION_ENABLED)),
        'has_secrets': has_secrets,
        'key_id': key_id,
        'location': 'local' if mappings.get(INTEGRATION_LOCATION) == 'local' else 'hosted',
        'site': site_root(connection.base_url),
    }


def integration_secrets(connection) -> Dict[str, str]:
    creds = connection.get_credentials() or {}
    return {'outbound': creds.get('integration_outbound_secret') or '',
            'inbound': creds.get('integration_inbound_secret') or ''}


def advertised_capabilities(connection) -> set:
    """What Rem0te said it supports, from its last capabilities document.
    Empty until the pairing is live and the document has been fetched."""
    if not integration_settings(connection)['enabled']:
        return set()
    doc = (connection.field_mappings or {}).get(INTEGRATION_CAPS) or {}
    caps = doc.get('capabilities') if isinstance(doc, dict) else None
    return {c for c in (caps or []) if isinstance(c, str)}


def record_capabilities(connection, document: Dict[str, Any]):
    caps = document.get('capabilities') if isinstance(document, dict) else None
    mappings = dict(connection.field_mappings or {})
    mappings[INTEGRATION_CAPS] = {
        'capabilities': sorted(c for c in (caps or []) if isinstance(c, str))[:64],
        'contract': str(document.get('contract') or '')[:40],
        'fetched_at': datetime.utcnow().isoformat() + 'Z',
    }
    connection.field_mappings = mappings
    connection.save(update_fields=['field_mappings'])
