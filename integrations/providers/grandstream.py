"""
Grandstream GWN Manager (WiFi controller) API provider.

Authentication:
  - Bearer token in Authorization header
  - Cloud: base URL https://gwn.cloud
  - Self-hosted: {host} provided by user

Endpoints:
  - GET /api/v1/networks  → list networks
  - GET /api/v1/aps       → list all APs (or /api/v1/networks/{id}/aps)
"""
import logging
import urllib3
import requests

from core.safe_http import guard_session, lan_controller_policy

logger = logging.getLogger(__name__)


class GrandstreamProvider:
    """Read-only Grandstream GWN Manager API client."""

    DEFAULT_HOST = 'https://gwn.cloud'

    def __init__(self, host: str, api_key: str, verify_ssl: bool = False):
        self.host = (host or self.DEFAULT_HOST).rstrip('/')
        self.api_key = api_key
        self.verify_ssl = verify_ssl

        self.session = guard_session(requests.Session(), lan_controller_policy())
        self.session.headers.update({
            'Authorization': f'Bearer {api_key}',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        })
        if not verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def _get(self, path: str, **kwargs) -> dict:
        """Authenticated GET."""
        url = f"{self.host}{path}"
        resp = self.session.get(url, verify=self.verify_ssl, timeout=15, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def _paginate(self, path: str) -> list:
        """Fetch all pages for paginated GWN endpoints (page/pageSize style)."""
        results = []
        page = 1
        page_size = 100
        while True:
            data = self._get(path, params={'page': page, 'pageSize': page_size})
            # GWN may return a list directly or wrapped in data/items/result
            if isinstance(data, list):
                results.extend(data)
                break
            items = (
                data.get('data') or
                data.get('items') or
                data.get('result') or
                []
            )
            if isinstance(items, dict):
                items = items.get('data') or items.get('items') or []
            results.extend(items)
            total = data.get('total') or data.get('totalRows') or 0
            if not items or len(results) >= total:
                break
            page += 1
        return results

    def test_connection(self) -> dict:
        """Test credentials, return {'success': True/False, ...}."""
        try:
            networks = self.get_networks()
            return {'success': True, 'message': f"Connected. Found {len(networks)} network(s)."}
        except requests.exceptions.SSLError:
            return {'success': False, 'error': 'SSL error — try disabling SSL verification for self-signed certificates.'}
        except requests.exceptions.ConnectionError as e:
            return {'success': False, 'error': f'Cannot reach host: {e}'}
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code in (401, 403):
                return {'success': False, 'error': 'Authentication failed — check your API key.'}
            return {'success': False, 'error': str(e)}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_networks(self) -> list:
        """GET /api/v1/networks — return list of network dicts."""
        try:
            data = self._get('/api/v1/networks')
            if isinstance(data, list):
                return data
            return (
                data.get('data') or
                data.get('items') or
                data.get('networks') or
                []
            )
        except Exception as e:
            logger.warning(f"Grandstream get_networks failed: {e}")
            return []

    def get_aps(self, network_id: str = '') -> list:
        """GET /api/v1/aps or /api/v1/networks/{id}/aps — return AP list."""
        try:
            if network_id:
                return self._paginate(f'/api/v1/networks/{network_id}/aps')
            return self._paginate('/api/v1/aps')
        except Exception as e:
            logger.warning(f"Grandstream get_aps({network_id}) failed: {e}")
            return []

    def normalize_device(self, d: dict, site_name: str = '') -> dict:
        """Normalize raw GWN AP dict to standard import format."""
        mac = (d.get('mac') or '').replace('-', ':').lower()
        return {
            'name': d.get('name') or mac or 'Unknown AP',
            'mac': mac,
            'ip': d.get('ip') or d.get('ipAddress') or '',
            'model': d.get('model') or '',
            'asset_type': 'wireless_ap',
            'manufacturer': 'Grandstream',
            'serial_number': d.get('serial') or d.get('serialNumber') or '',
            'os_version': d.get('firmwareVersion') or d.get('firmware') or '',
            'online': bool(d.get('online')) or bool(d.get('status') == 'online'),
            'site_name': site_name,
        }

    def sync(self) -> dict:
        """Sync all networks and APs. Returns data dict compatible with cached_data."""
        networks = self.get_networks()
        sites = []

        if networks:
            for net in networks:
                net_id = net.get('networkId') or net.get('id') or ''
                net_name = net.get('name') or net_id or 'Default'
                raw_aps = self.get_aps(net_id)
                devices = [self.normalize_device(ap, net_name) for ap in raw_aps]
                sites.append({
                    'networkId': net_id,
                    'name': net_name,
                    'devices': devices,
                })
        else:
            # No networks endpoint or empty — try flat AP list
            raw_aps = self.get_aps()
            if raw_aps:
                devices = [self.normalize_device(ap, 'Default') for ap in raw_aps]
                sites.append({
                    'networkId': '',
                    'name': 'Default',
                    'devices': devices,
                })

        return {
            'mode': 'grandstream',
            'sites': sites,
        }
