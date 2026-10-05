"""
UniFi Site Manager (cloud) API provider.
API: https://api.ui.com/v1/
Authentication: API key in X-API-KEY header (from account.ui.com → API Keys)
"""
import logging
import requests

from core.safe_http import configured_service_policy, guard_session

logger = logging.getLogger(__name__)

CLOUD_BASE = 'https://api.ui.com'


class UnifiCloudProvider:
    """Read-only UniFi Site Manager cloud API client."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = guard_session(requests.Session(), configured_service_policy())
        self.session.headers.update({
            'X-API-KEY': api_key,
            'Accept': 'application/json',
        })

    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{CLOUD_BASE}{path}"
        resp = self.session.get(url, params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def _get_all(self, path: str, params: dict = None) -> list:
        """Page through results using nextToken cursor."""
        params = dict(params or {})
        results = []
        while True:
            data = self._get(path, params)
            items = data.get('data', [])
            results.extend(items)
            next_token = data.get('nextToken') or (data.get('pagination') or {}).get('nextToken')
            if not next_token:
                break
            params['nextToken'] = next_token
        return results

    def test_connection(self) -> dict:
        try:
            data = self._get('/v1/hosts')
            hosts = data.get('data', [])
            return {'success': True, 'message': f"Connected to UniFi Site Manager. Found {len(hosts)} host(s)."}
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                return {'success': False, 'error': 'Authentication failed — check your API key from account.ui.com.'}
            return {'success': False, 'error': str(e)}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_hosts(self) -> list:
        try:
            return self._get_all('/v1/hosts')
        except Exception as e:
            logger.warning(f"UniFi Cloud get_hosts failed: {e}")
            return []

    def get_sites(self) -> list:
        try:
            return self._get_all('/v1/sites')
        except Exception as e:
            logger.warning(f"UniFi Cloud get_sites failed: {e}")
            return []

    def get_devices(self) -> list:
        try:
            return self._get_all('/v1/devices')
        except Exception as e:
            logger.warning(f"UniFi Cloud get_devices failed: {e}")
            return []

    def sync(self) -> dict:
        """Pull all data from cloud and return structured summary."""
        hosts = self.get_hosts()
        all_devices = self.get_devices()
        all_sites = self.get_sites()

        # Group devices by hostId
        devices_by_host = {}
        for d in all_devices:
            hid = d.get('hostId') or 'unknown'
            devices_by_host.setdefault(hid, []).append(d)

        sites_result = []
        for host in hosts:
            hid = host.get('id') or ''
            host_name = host.get('reportedState', {}).get('hostname') or host.get('hardwareId') or hid
            devices = devices_by_host.get(hid, [])
            type_counts = {}
            for d in devices:
                dtype = d.get('productType') or d.get('type') or 'unknown'
                type_counts[dtype] = type_counts.get(dtype, 0) + 1
            sites_result.append({
                'id': hid,
                'name': host_name,
                'devices': devices,
                'device_type_counts': type_counts,
                'wlans': [],
                'vlans': [],
                'firewall_rules': [],
                'firewall_policies': [],
                'traffic_rules': [],
                'client_count': 0,
                '_is_cloud': True,
            })

        return {
            'sites': sites_result,
            'has_legacy_data': False,
            'legacy_login_ok': False,
            '_cloud_mode': True,
            '_host_count': len(hosts),
            '_site_count': len(all_sites),
        }
