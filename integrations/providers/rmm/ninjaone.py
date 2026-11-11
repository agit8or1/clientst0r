"""
NinjaOne RMM Provider

API Documentation: https://app.ninjarmm.com/apidocs
Authentication: OAuth 2.0 Bearer Token
"""
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from ..rmm_base import BaseRMMProvider, ProviderError, AuthenticationError

logger = logging.getLogger('integrations')


class NinjaOneProvider(BaseRMMProvider):
    """
    NinjaOne (NinjaRMM) provider implementation.

    Supports:
    - Device inventory sync
    - Alert monitoring
    - Software inventory
    - Cursor-based pagination
    """

    provider_name = 'NinjaOne'
    supports_software = True

    # Node class to device type mapping
    NODE_CLASS_MAP = {
        'WINDOWS_WORKSTATION': 'workstation',
        'WINDOWS_SERVER': 'server',
        'MAC': 'workstation',
        'MAC_SERVER': 'server',
        'LINUX_WORKSTATION': 'workstation',
        'LINUX_SERVER': 'server',
        'NETWORK_DEVICE': 'network',
        'VM_HOST': 'server',
        'VM_GUEST': 'virtual',
        'CLOUD_MONITOR_TARGET': 'cloud',
        'VMWARE_VM_HOST': 'server',
        'VMWARE_VM_GUEST': 'virtual',
        'HYPERV_HOST': 'server',
        'HYPERV_GUEST': 'virtual',
    }

    def _get_auth_headers(self) -> Dict[str, str]:
        """
        OAuth 2.0 Bearer token authentication.

        Credentials should contain:
        - access_token: OAuth access token
        """
        credentials = self.connection.get_credentials()

        if not credentials.get('access_token'):
            raise AuthenticationError('NinjaOne access_token not configured')

        return {
            'Authorization': f'Bearer {credentials["access_token"]}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

    def test_connection(self) -> bool:
        """
        Test API connectivity by listing devices (limit 1).

        Returns:
            True if connection successful, False otherwise
        """
        try:
            response = self._make_request('GET', '/v2/devices', params={'pageSize': 1})
            return response.status_code == 200
        except Exception as e:
            logger.error(f"NinjaOne connection test failed: {e}")
            return False

    def _paged(self, endpoint, page_size=1000):
        """NinjaOne pages with `pageSize` and `after` (the last id seen)."""
        after = None
        while True:
            params = {'pageSize': page_size}
            if after is not None:
                params['after'] = after
            data = self._make_request('GET', endpoint, params=params).json()
            if not isinstance(data, list) or not data:
                return
            yield from data
            last = data[-1].get('id') if isinstance(data[-1], dict) else None
            if len(data) < page_size or last is None or last == after:
                return
            after = last

    def _lookups(self):
        """Organization and location names, fetched once per sync."""
        orgs, locations = {}, {}
        try:
            for row in self._paged('/v2/organizations'):
                orgs[str(row.get('id'))] = row.get('name') or ''
            for row in self._paged('/v2/locations'):
                locations[str(row.get('id'))] = row.get('name') or ''
        except Exception as e:  # names are display only; IDs still resolve
            logger.warning(f"NinjaOne: organization/location names unavailable: {e}")
        return orgs, locations

    def list_devices(self, page_size: int = 1000, updated_since: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        List all devices from /v2/devices-detailed, which (unlike /v2/devices)
        carries the system and OS details. NinjaOne documents no "changed
        since" filter, so every sync reads the full list.
        """
        devices = []
        self._org_names, self._location_names = self._lookups()
        try:
            for device_data in self._paged('/v2/devices-detailed', min(page_size, 1000)):
                try:
                    devices.append(self.normalize_device(device_data))
                except Exception as e:
                    logger.error(f"Error normalizing NinjaOne device {device_data.get('id')}: {e}")
            logger.info(f"NinjaOne: Retrieved {len(devices)} total devices")
            return devices
        except Exception as e:
            logger.error(f"Error listing NinjaOne devices: {e}")
            raise ProviderError(f"Failed to list devices: {e}")

    def get_device(self, device_id: str) -> Dict[str, Any]:
        """
        Get single device by ID.

        Args:
            device_id: NinjaOne device ID

        Returns:
            Normalized device dictionary
        """
        try:
            response = self._make_request('GET', f'/v2/device/{device_id}')
            return self.normalize_device(response.json())
        except Exception as e:
            logger.error(f"Error getting NinjaOne device {device_id}: {e}")
            raise ProviderError(f"Failed to get device: {e}")

    def list_alerts(
        self,
        device_id: Optional[str] = None,
        status: Optional[str] = None,
        updated_since: Optional[datetime] = None,
        page_size: int = 100
    ) -> List[Dict[str, Any]]:
        """
        List the currently triggered alerts. /v2/alerts takes no paging or
        status parameters; every alert it returns is open, and each names its
        device in `deviceId`.
        """
        alerts = []
        endpoint = f'/v2/device/{device_id}/alerts' if device_id else '/v2/alerts'
        try:
            data = self._make_request('GET', endpoint).json()
            if not isinstance(data, list):
                logger.error(f"Unexpected response format from NinjaOne alerts: {type(data)}")
                return alerts
            for alert_data in data:
                try:
                    alerts.append(self.normalize_alert(alert_data))
                except Exception as e:
                    logger.error(f"Error normalizing NinjaOne alert {alert_data.get('uid')}: {e}")
            logger.info(f"NinjaOne: Retrieved {len(alerts)} alerts")
            return alerts
        except Exception as e:
            logger.error(f"Error listing NinjaOne alerts: {e}")
            raise ProviderError(f"Failed to list alerts: {e}")

    def list_software(self, device_id: str) -> List[Dict[str, Any]]:
        """
        List software installed on a device.

        Args:
            device_id: NinjaOne device ID

        Returns:
            List of normalized software dictionaries
        """
        software_list = []

        try:
            response = self._make_request('GET', f'/v2/device/{device_id}/software')
            data = response.json()

            if not isinstance(data, list):
                logger.error(f"Unexpected response format from NinjaOne software: {type(data)}")
                return software_list

            for sw_data in data:
                try:
                    software_list.append(self.normalize_software(sw_data))
                except Exception as e:
                    logger.error(f"Error normalizing NinjaOne software: {e}")

            logger.debug(f"NinjaOne: Retrieved {len(software_list)} software items for device {device_id}")
            return software_list

        except Exception as e:
            logger.error(f"Error listing NinjaOne software for device {device_id}: {e}")
            # Raise so the sync keeps this device\'s stored software
            # instead of reading the failure as "nothing installed".
            raise ProviderError(f"Failed to list software: {e}")

    def normalize_device(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize a NinjaOne device (v2 OpenAPI spec, /v2/devices-detailed).

            {
              "id": 123, "uid": "…", "nodeClass": "WINDOWS_WORKSTATION",
              "systemName": "FRONTDESK", "displayName": "Front desk PC",
              "dnsName": "frontdesk.corp.local", "offline": false,
              "lastContact": 1767920400.5,            # epoch seconds
              "organizationId": 7, "locationId": 12,
              "references": {"organization": {"id": 7, "name": "Acme"},
                             "location": {"id": 12, "name": "Main Office"}},
              "system": {"manufacturer": "Dell Inc.", "model": "OptiPlex 7090",
                         "serialNumber": "ABC12345", "biosSerialNumber": "…"},
              "os": {"name": "Windows 11 Pro"},
              "ipAddresses": ["192.168.1.10"], "macAddresses": ["00:11:…"]
            }

        Organization (the customer) and location (its site) stay separate
        identities. Cloud monitors, VM hosts and unmanaged devices have no
        `system` block.
        """
        system = raw_data.get('system') or {}
        os_info = raw_data.get('os') or {}
        refs = raw_data.get('references') or {}

        node_class = (raw_data.get('nodeClass') or '').upper()
        device_type = self.NODE_CLASS_MAP.get(node_class, 'unknown')

        ip_addresses = raw_data.get('ipAddresses') or system.get('ipAddresses') or []
        mac_addresses = raw_data.get('macAddresses') or system.get('macAddresses') or []
        ip_address = next((ip for ip in ip_addresses if ip and ':' not in ip), None) or (ip_addresses[0] if ip_addresses else None)
        mac_address = mac_addresses[0] if mac_addresses else ''

        os_name = os_info.get('name', '') or ''
        os_version = f"{os_name} {os_info['version']}".strip() if os_info.get('version') else os_name

        if 'offline' in raw_data:
            is_online = not raw_data.get('offline')
        else:
            is_online = bool(raw_data.get('online', False))

        org_id = raw_data.get('organizationId') or (refs.get('organization') or {}).get('id') or ''
        loc_id = raw_data.get('locationId') or (refs.get('location') or {}).get('id') or ''
        org_name = ((refs.get('organization') or {}).get('name')
                    or getattr(self, '_org_names', {}).get(str(org_id), '') or raw_data.get('organizationName', ''))
        loc_name = ((refs.get('location') or {}).get('name')
                    or getattr(self, '_location_names', {}).get(str(loc_id), '') or raw_data.get('locationName', ''))

        name = (raw_data.get('systemName') or system.get('name') or raw_data.get('displayName')
                or raw_data.get('dnsName') or '')
        serial = system.get('serialNumber') or system.get('biosSerialNumber') or system.get('assetSerialNumber') or ''

        return {
            'external_id': str(raw_data.get('id') if raw_data.get('id') is not None else ''),
            'device_name': raw_data.get('displayName') or name,
            'device_type': device_type,
            'manufacturer': system.get('manufacturer', '') or '',
            'model': system.get('model', '') or '',
            'serial_number': serial,
            'os_type': self._map_os_type(os_name),
            'os_version': os_version,
            'hostname': name or raw_data.get('dnsName', ''),
            'ip_address': ip_address,
            'mac_address': mac_address,
            'is_online': is_online,
            'last_seen': self._parse_datetime(raw_data.get('lastContact')),
            'client_id': str(org_id) if org_id else '',
            'client_name': org_name or '',
            'site_id': str(loc_id) if loc_id else '',
            'site_name': loc_name or '',
            'raw_data': raw_data,
        }

    def normalize_alert(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize a NinjaOne alert (v2 spec): `uid`, `deviceId`, `sourceType`,
        `subject`, `message`, `severity`, `createTime` (epoch seconds). Alerts
        listed by the API are open; there is no status field.
        """
        severity_map = {
            'NONE': 'info',
            'MINOR': 'warning',
            'MODERATE': 'warning',
            'MAJOR': 'error',
            'CRITICAL': 'critical',
        }
        severity = severity_map.get(str(raw_data.get('severity') or 'NONE').upper(), 'info')
        device_id = raw_data.get('deviceId')
        if device_id is None:
            device_id = (raw_data.get('device') or {}).get('id')

        return {
            'external_id': str(raw_data.get('uid') or ''),
            'device_id': str(device_id) if device_id is not None else '',
            'alert_type': raw_data.get('sourceType') or raw_data.get('type') or '',
            'message': raw_data.get('message') or raw_data.get('subject') or '',
            'severity': severity,
            'status': 'active',
            'triggered_at': self._parse_datetime(raw_data.get('createTime')),
            'resolved_at': None,
            'raw_data': raw_data,
        }

    # A device's dashboard URL comes from the documented
    # GET /v2/device/{id}/dashboard-url, which returns a short-lived link. It
    # is fetched on the server when the technician clicks, never stored.
    console_link_mode = 'on_demand'

    @classmethod
    def console_hosts(cls, connection):
        from .console import host_of
        host = host_of(connection.base_url)
        return {host} if host.endswith('.ninjarmm.com') or host.endswith('.ninjaone.com') else set()

    def fetch_console_url(self, device):
        data = self._make_request('GET', f'/v2/device/{device.external_id}/dashboard-url').json()
        return (data or {}).get('url', '') if isinstance(data, dict) else ''

    def normalize_software(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize NinjaOne software data to standard format.

        NinjaOne software structure:
        {
            "id": "abc-123",
            "name": "Google Chrome",
            "version": "120.0.6099.71",
            "publisher": "Google LLC",
            "installDate": "2025-12-15T10:30:00Z"
        }
        """
        install_date = self._parse_datetime(raw_data.get('installDate'))

        return {
            'external_id': str(raw_data.get('id', '')),
            'name': raw_data.get('name', ''),
            'version': raw_data.get('version', ''),
            'vendor': raw_data.get('publisher', ''),
            'install_date': install_date,
            'raw_data': raw_data,
        }

    def _map_os_type(self, os_name: str) -> str:
        """
        Map OS name to standard OS type.

        Args:
            os_name: Operating system name from NinjaOne

        Returns:
            Standard OS type (windows, macos, linux, etc.)
        """
        os_lower = os_name.lower()

        if 'windows' in os_lower:
            return 'windows'
        elif 'mac' in os_lower or 'darwin' in os_lower or 'os x' in os_lower:
            return 'macos'
        elif 'linux' in os_lower or 'ubuntu' in os_lower or 'centos' in os_lower or 'debian' in os_lower or 'red hat' in os_lower:
            return 'linux'
        elif 'ios' in os_lower or 'ipad' in os_lower or 'iphone' in os_lower:
            return 'ios'
        elif 'android' in os_lower:
            return 'android'
        else:
            return 'other'
