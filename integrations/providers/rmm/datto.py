"""
Datto RMM Provider

API Documentation: https://rmm.datto.com/help/en/Content/4WEBPORTAL/API.htm
Authentication: API Key + Secret Key
"""
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from ..rmm_base import BaseRMMProvider, ProviderError, AuthenticationError

logger = logging.getLogger('integrations')


class DattoRMMProvider(BaseRMMProvider):
    """
    Datto RMM (formerly Autotask Endpoint Management / Centrastage) provider.

    Supports:
    - Device inventory sync
    - Alert monitoring
    - Software inventory
    - Component monitoring
    """

    provider_name = 'Datto RMM'
    supports_software = True

    # Device type mapping
    DEVICE_TYPE_MAP = {
        'desktop': 'workstation',
        'laptop': 'laptop',
        'server': 'server',
        'workstation': 'workstation',
        'esxi': 'server',
        'vm': 'virtual',
        'unknown': 'unknown',
    }

    def _get_auth_headers(self) -> Dict[str, str]:
        """
        Datto RMM uses API Key + Secret Key authentication.

        Credentials should contain:
        - api_key: Datto RMM API key
        - api_secret: Datto RMM secret key
        - platform: API platform (concord, pinotage, merlot, etc.)
        """
        credentials = self.connection.get_credentials()

        if not credentials.get('api_key') or not credentials.get('api_secret'):
            raise AuthenticationError('Datto RMM api_key and api_secret required')

        # Datto uses API key in header
        return {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'ApiKey': credentials['api_key'],
            'ApiSecretKey': credentials['api_secret'],
        }

    def test_connection(self) -> bool:
        """
        Test API connectivity by fetching account info.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            response = self._make_request('GET', '/api/v2/account')
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Datto RMM connection test failed: {e}")
            return False

    def _paged(self, endpoint, key, page_size=250):
        """Datto pages with `max` and hands back `pageDetails.nextPageUrl`
        until the last page. The next URL must stay on the configured API
        host; anything else ends the listing."""
        from urllib.parse import urlsplit
        api_host = urlsplit(self.base_url).hostname
        params = {'max': min(page_size, 250)}
        url = endpoint
        for _ in range(10000):
            data = self._make_request('GET', url, params=params).json() or {}
            for item in data.get(key) or []:
                yield item
            nxt = (data.get('pageDetails') or {}).get('nextPageUrl')
            if not nxt:
                return
            parts = urlsplit(nxt)
            if parts.hostname and parts.hostname != api_host:
                logger.warning(f"Datto RMM: ignoring a next-page URL on another host ({parts.hostname})")
                return
            url = parts.path + (f'?{parts.query}' if parts.query else '')
            params = None

    def list_devices(self, page_size: int = 250, updated_since: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        List all devices (GET /api/v2/account/devices). The API has no
        "changed since" filter, so the full list is read and `updated_since`
        is ignored: skipping devices by last-seen time would hide moves
        between sites.
        """
        devices = []
        try:
            for device_data in self._paged('/api/v2/account/devices', 'devices', page_size):
                try:
                    devices.append(self.normalize_device(device_data))
                except Exception as e:
                    logger.error(f"Error normalizing Datto device {device_data.get('uid')}: {e}")
            logger.info(f"Datto RMM: Retrieved {len(devices)} total devices")
            return devices
        except Exception as e:
            logger.error(f"Error listing Datto RMM devices: {e}")
            raise ProviderError(f"Failed to list devices: {e}")

    def get_device(self, device_id: str) -> Dict[str, Any]:
        """
        Get single device by UID.

        Args:
            device_id: Datto device UID

        Returns:
            Normalized device dictionary
        """
        try:
            # Datto RMM API v2: GET /v2/device/{deviceUid}.
            response = self._make_request('GET', f'/api/v2/device/{device_id}')
            return self.normalize_device(response.json())
        except Exception as e:
            logger.error(f"Error getting Datto device {device_id}: {e}")
            raise ProviderError(f"Failed to get device: {e}")

    def list_alerts(
        self,
        device_id: Optional[str] = None,
        status: Optional[str] = None,
        updated_since: Optional[datetime] = None,
        page_size: int = 250
    ) -> List[Dict[str, Any]]:
        """
        List open alerts (GET /api/v2/account/alerts/open; resolved ones with
        status='resolved'). Each alert names its device in
        `alertSourceInfo.deviceUid`.
        """
        alerts = []
        which = 'resolved' if status == 'resolved' else 'open'
        try:
            for alert_data in self._paged(f'/api/v2/account/alerts/{which}', 'alerts', page_size):
                try:
                    alert = self.normalize_alert(alert_data)
                    if device_id and alert['device_id'] != str(device_id):
                        continue
                    alerts.append(alert)
                except Exception as e:
                    logger.error(f"Error normalizing Datto alert {alert_data.get('alertUid')}: {e}")
            logger.info(f"Datto RMM: Retrieved {len(alerts)} alerts")
            return alerts
        except Exception as e:
            logger.error(f"Error listing Datto RMM alerts: {e}")
            raise ProviderError(f"Failed to list alerts: {e}")

    def list_software(self, device_id: str) -> List[Dict[str, Any]]:
        """
        List software installed on a device.

        Args:
            device_id: Datto device UID

        Returns:
            List of normalized software dictionaries
        """
        software_list = []

        try:
            # Datto RMM API v2: GET /v2/audit/device/{deviceUid}/software,
            # paged like the other lists; items carry name and version.
            for sw_data in self._paged(f'/api/v2/audit/device/{device_id}/software', 'software'):
                try:
                    software_list.append(self.normalize_software(sw_data))
                except Exception as e:
                    logger.error(f"Error normalizing Datto software: {e}")

            logger.debug(f"Datto RMM: Retrieved {len(software_list)} software items for device {device_id}")
            return software_list

        except Exception as e:
            logger.error(f"Error listing Datto RMM software for device {device_id}: {e}")
            # Raise so the sync keeps this device\'s stored software
            # instead of reading the failure as "nothing installed".
            raise ProviderError(f"Failed to list software: {e}")

    def normalize_device(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize a Datto RMM device (API v2 spec):

            {
              "id": 101, "uid": "abc-123", "hostname": "FRONTDESK",
              "description": "Front desk PC", "intIpAddress": "192.168.1.10",
              "online": true, "lastSeen": 1767920400000,       # epoch ms
              "siteId": 9, "siteUid": "site-9", "siteName": "Acme Ltd",
              "deviceType": {"category": "Desktop"},
              "operatingSystem": "Microsoft Windows 11 Pro",
              "portalUrl": "https://pinotage.centrastage.net/…"
            }

        Datto's site is the customer: the same site becomes both the customer
        and its only site, so one site never yields two customers. Serial,
        make and model live in the per-device audit, which is not fetched
        (one call per device); devices match on hostname within the customer.
        """
        device_type_category = str((raw_data.get('deviceType') or {}).get('category') or 'unknown').lower()
        device_type = self.DEVICE_TYPE_MAP.get(device_type_category, 'unknown')
        os_name = raw_data.get('operatingSystem', '') or ''
        site_uid = raw_data.get('siteUid') or ''
        site_name = raw_data.get('siteName', '') or ''
        bios = raw_data.get('bios') or {}
        system = raw_data.get('systemInfo') or {}

        return {
            'external_id': str(raw_data.get('uid') or ''),
            'device_name': raw_data.get('hostname', '') or raw_data.get('description', ''),
            'device_type': device_type,
            'manufacturer': system.get('manufacturer') or raw_data.get('manufacturer', '') or '',
            'model': system.get('model') or raw_data.get('model', '') or '',
            'serial_number': bios.get('serialNumber') or raw_data.get('serialNumber', '') or '',
            'os_type': self._map_os_type(os_name),
            'os_version': os_name,
            'hostname': raw_data.get('hostname', '') or '',
            'ip_address': raw_data.get('intIpAddress') or raw_data.get('ipAddress') or None,
            'mac_address': raw_data.get('macAddress', '') or '',
            'is_online': bool(raw_data.get('online', False)),
            'last_seen': self._parse_datetime(raw_data.get('lastSeen')),
            'client_id': str(site_uid),
            'client_name': site_name,
            'site_id': str(site_uid),
            'site_name': site_name,
            'raw_data': raw_data,
        }

    def normalize_alert(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize a Datto RMM alert: `alertUid`, `priority`, `resolved`,
        `resolvedOn`, `timestamp` (epoch ms) and
        `alertSourceInfo {deviceUid, deviceName, siteUid, siteName}`.
        """
        priority_map = {
            'information': 'info',
            'low': 'info',
            'moderate': 'warning',
            'normal': 'warning',
            'high': 'error',
            'critical': 'critical',
        }
        severity = priority_map.get(str(raw_data.get('priority') or 'moderate').lower(), 'warning')
        resolved = bool(raw_data.get('resolved'))
        source = raw_data.get('alertSourceInfo') or {}
        message = (raw_data.get('diagnostics') or raw_data.get('alertMessage')
                   or (raw_data.get('alertContext') or {}).get('@class') or 'Datto RMM alert')

        return {
            'external_id': str(raw_data.get('alertUid') or ''),
            'device_id': str(source.get('deviceUid') or ''),
            'alert_type': (raw_data.get('alertContext') or {}).get('@class') or 'alert',
            'message': message,
            'severity': severity,
            'status': 'resolved' if resolved else 'active',
            'triggered_at': self._parse_datetime(raw_data.get('timestamp')),
            'resolved_at': self._parse_datetime(raw_data.get('resolvedOn')) if resolved else None,
            'raw_data': raw_data,
        }

    # The device object carries its own console address in `portalUrl`. It
    # must point at the web portal of the same platform as the API host
    # (pinotage-api.centrastage.net → pinotage.centrastage.net).
    console_link_mode = 'static'

    @classmethod
    def console_hosts(cls, connection):
        from .console import host_of
        host = host_of(connection.base_url)
        if host.endswith('-api.centrastage.net'):
            return {host.replace('-api.centrastage.net', '.centrastage.net')}
        return set()

    @classmethod
    def device_console_url(cls, connection, device):
        return (device.raw_data or {}).get('portalUrl') or ''

    def normalize_software(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize Datto RMM software data to standard format.

        Datto software structure:
        {
            "name": "Google Chrome",
            "version": "120.0.6099.71",
            "publisher": "Google LLC",
            "installDate": "2025-12-15"
        }
        """
        # Parse install date (date only, no time)
        install_date_str = raw_data.get('installDate')
        install_date = None
        if install_date_str:
            try:
                install_date = datetime.strptime(install_date_str, '%Y-%m-%d')
            except Exception:
                pass

        return {
            'external_id': '',  # Datto doesn't provide unique software IDs
            'name': raw_data.get('name', ''),
            'version': raw_data.get('version', ''),
            'vendor': raw_data.get('publisher', ''),
            'install_date': install_date,
            'raw_data': raw_data,
        }

    def _map_os_type(self, os_name: str) -> str:
        """Map OS name to standard OS type."""
        os_lower = os_name.lower()

        if 'windows' in os_lower:
            return 'windows'
        elif 'mac' in os_lower or 'darwin' in os_lower or 'os x' in os_lower:
            return 'macos'
        elif 'linux' in os_lower or 'ubuntu' in os_lower or 'centos' in os_lower or 'debian' in os_lower:
            return 'linux'
        elif 'ios' in os_lower:
            return 'ios'
        elif 'android' in os_lower:
            return 'android'
        else:
            return 'other'
