"""
TP-Link Omada SDN Controller API provider.

Authentication:
  - GET {host}/api/info  → omadacId
  - POST {host}/{omadacId}/api/v2/login → session cookie + CSRF token
  - All subsequent requests: Cookie TPSESSIONID + Csrf-Token header

Reference: https://www.tp-link.com/us/support/download/omada-software-controller/
"""
import logging
import urllib3
import requests

from core.safe_http import guard_session, lan_controller_policy

logger = logging.getLogger(__name__)


class OmadaProvider:
    """Read-only TP-Link Omada SDN Controller API client."""

    # Map Omada device type integers to Asset ASSET_TYPES keys
    TYPE_MAP = {
        0: 'wireless_ap',   # EAP (indoor)
        1: 'switch',         # switch
        2: 'router',         # gateway/router
        3: 'wireless_ap',   # EAP (outdoor)
    }

    def __init__(self, host: str, username: str, password: str, verify_ssl: bool = False):
        self.host = host.rstrip('/')
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self._omadac_id = ''
        self._csrf_token = ''

        self.session = guard_session(requests.Session(), lan_controller_policy())
        self.session.headers.update({
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        })
        if not verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def _get_info(self) -> str:
        """GET /api/info → return omadacId string."""
        url = f"{self.host}/api/info"
        resp = self.session.get(url, verify=self.verify_ssl, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        omadac_id = data.get('result', {}).get('omadacId', '')
        if not omadac_id:
            raise ValueError("Could not retrieve omadacId from /api/info")
        return omadac_id

    def _login(self) -> None:
        """POST /{omadacId}/api/v2/login — set session cookie and CSRF token."""
        if not self._omadac_id:
            self._omadac_id = self._get_info()
        url = f"{self.host}/{self._omadac_id}/api/v2/login"
        payload = {'username': self.username, 'password': self.password}
        resp = self.session.post(url, json=payload, verify=self.verify_ssl, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        error_code = data.get('errorCode', -1)
        if error_code != 0:
            msg = data.get('msg', 'Unknown error')
            raise ValueError(f"Omada login failed (errorCode={error_code}): {msg}")
        token = data.get('result', {}).get('token', '')
        if token:
            self._csrf_token = token
            self.session.headers.update({'Csrf-Token': token})

    def _get(self, path: str, **kwargs) -> dict:
        """Authenticated GET with CSRF header."""
        if not self._omadac_id:
            self._login()
        url = f"{self.host}/{self._omadac_id}{path}"
        resp = self.session.get(url, verify=self.verify_ssl, timeout=15, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def _paginate(self, path: str) -> list:
        """Fetch all pages for paginated Omada endpoints."""
        results = []
        page = 1
        page_size = 100
        while True:
            data = self._get(path, params={'page': page, 'pageSize': page_size})
            result = data.get('result', {})
            items = result.get('data', [])
            results.extend(items)
            total = result.get('totalRows', 0)
            if len(results) >= total or not items:
                break
            page += 1
        return results

    def test_connection(self) -> dict:
        """Try login, return {'success': True/False, 'message': '...'}."""
        try:
            self._omadac_id = ''  # Force fresh login
            self._login()
            sites = self.get_sites()
            return {'success': True, 'message': f"Connected. Found {len(sites)} site(s)."}
        except requests.exceptions.SSLError:
            return {'success': False, 'error': 'SSL error — try disabling SSL verification for self-signed certificates.'}
        except requests.exceptions.ConnectionError as e:
            return {'success': False, 'error': f'Cannot reach host: {e}'}
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code in (401, 403):
                return {'success': False, 'error': 'Authentication failed — check your username and password.'}
            return {'success': False, 'error': str(e)}
        except ValueError as e:
            return {'success': False, 'error': str(e)}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_sites(self) -> list:
        """GET /{omadacId}/api/v2/sites — return list of site dicts."""
        try:
            return self._paginate('/api/v2/sites')
        except Exception as e:
            logger.warning(f"Omada get_sites failed: {e}")
            return []

    def get_devices(self, site_id: str) -> list:
        """GET /{omadacId}/api/v2/sites/{siteId}/devices — return list of device dicts."""
        if not site_id:
            return []
        try:
            return self._paginate(f'/api/v2/sites/{site_id}/devices')
        except Exception as e:
            logger.warning(f"Omada get_devices({site_id}) failed: {e}")
            return []

    def normalize_device(self, d: dict, site_name: str = '') -> dict:
        """Normalize raw Omada device dict to standard import format."""
        mac = (d.get('mac') or '').replace('-', ':').lower()
        device_type = d.get('type', 0)
        asset_type = self.TYPE_MAP.get(device_type, 'wireless_ap')
        return {
            'name': d.get('name') or mac or 'Unknown Device',
            'mac': mac,
            'ip': d.get('ip') or '',
            'model': d.get('model') or '',
            'asset_type': asset_type,
            'manufacturer': 'TP-Link',
            'serial_number': d.get('serial') or d.get('serialNumber') or '',
            'os_version': d.get('firmwareVersion') or '',
            'online': d.get('status', 0) == 1,
            'site_name': site_name,
        }

    def sync(self) -> dict:
        """Sync all sites and devices. Returns data dict compatible with cached_data."""
        self._omadac_id = ''  # Force fresh login
        self._login()
        raw_sites = self.get_sites()
        sites = []
        for s in raw_sites:
            site_id = s.get('siteId', '')
            site_name = s.get('name', '')
            raw_devices = self.get_devices(site_id)
            devices = [self.normalize_device(d, site_name) for d in raw_devices]
            sites.append({
                'siteId': site_id,
                'name': site_name,
                'devices': devices,
            })
        return {
            'mode': 'omada',
            'sites': sites,
        }
