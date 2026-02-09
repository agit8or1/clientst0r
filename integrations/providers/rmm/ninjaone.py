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

    def list_devices(self, page_size: int = 100, updated_since: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        List all devices with cursor-based pagination.

        NinjaOne uses cursor-based pagination with X-Page-After header.

        Args:
            page_size: Number of devices per page (max 1000)
            updated_since: Only return devices updated after this time

        Returns:
            List of normalized device dictionaries
        """
        devices = []
        params = {'pageSize': min(page_size, 1000)}

        if updated_since:
            # NinjaOne expects ISO 8601 format
            params['updatedAfter'] = updated_since.isoformat()

        page_after = None

        try:
            while True:
                if page_after:
                    params['pageAfter'] = page_after

                response = self._make_request('GET', '/v2/devices', params=params)
                data = response.json()

                # NinjaOne returns array of devices
                if not isinstance(data, list):
                    logger.error(f"Unexpected response format from NinjaOne: {type(data)}")
                    break

                for device_data in data:
                    try:
                        devices.append(self.normalize_device(device_data))
                    except Exception as e:
                        logger.error(f"Error normalizing NinjaOne device {device_data.get('id')}: {e}")

                # Check for next page cursor in response headers
                page_after = response.headers.get('X-Page-After')
                if not page_after:
                    break

                logger.debug(f"NinjaOne: Fetched {len(data)} devices, continuing with cursor {page_after}")

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
        List monitoring alerts.

        Args:
            device_id: Filter by device ID
            status: Filter by status (OPEN, CLOSED)
            updated_since: Only return alerts updated after this time
            page_size: Number of alerts per page

        Returns:
            List of normalized alert dictionaries
        """
        alerts = []
        params = {'pageSize': min(page_size, 1000)}

        if device_id:
            params['deviceId'] = device_id
        if status:
            params['status'] = status.upper()
        if updated_since:
            params['updatedAfter'] = updated_since.isoformat()

        try:
            # NinjaOne alerts endpoint with pagination
            response = self._make_request('GET', '/v2/alerts', params=params)
            data = response.json()

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
            # Don't raise - software listing is optional
            return software_list

    def normalize_device(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize NinjaOne device data to standard format.

        NinjaOne device structure:
        {
            "id": 123,
            "nodeClass": "WINDOWS_WORKSTATION",
            "online": true,
            "lastContact": "2026-01-11T02:00:00Z",
            "system": {
                "name": "DESKTOP-ABC123",
                "dnsName": "desktop-abc123.domain.local",
                "manufacturer": "Dell Inc.",
                "model": "OptiPlex 7090",
                "serialNumber": "ABC12345",
                "biosSerialNumber": "ABC12345",
                "biosVersion": "1.2.3",
                "ipAddresses": ["192.168.1.100", "fe80::1"],
                "macAddresses": ["00:11:22:33:44:55"]
            },
            "os": {
                "name": "Microsoft Windows 10 Pro",
                "version": "10.0.19045",
                "build": "19045"
            }
        }
        """
        system = raw_data.get('system', {})
        os_info = raw_data.get('os', {})

        # Map node class to device type
        node_class = raw_data.get('nodeClass', '').upper()
        device_type = self.NODE_CLASS_MAP.get(node_class, 'unknown')

        # Get first IP and MAC address
        ip_addresses = system.get('ipAddresses', [])
        mac_addresses = system.get('macAddresses', [])

        ip_address = ip_addresses[0] if ip_addresses else None
        mac_address = mac_addresses[0] if mac_addresses else ''

        # Parse OS type from OS name
        os_name = os_info.get('name', '')
        os_type = self._map_os_type(os_name)

        # Build OS version string
        os_version = os_info.get('name', '')
        if os_info.get('version'):
            os_version = f"{os_name} {os_info['version']}"

        # Parse last contact timestamp
        last_seen = self._parse_datetime(raw_data.get('lastContact'))

        # Extract organization/client information
        # NinjaOne provides organizationId and organization name in device data
        organization_id = raw_data.get('organizationId', '') or raw_data.get('orgId', '')
        # Organization name might be in 'organization' field or need separate lookup
        organization_name = raw_data.get('organizationName', '') or raw_data.get('orgName', '')

        # Location/site information (if provided)
        location_id = raw_data.get('locationId', '')
        location_name = raw_data.get('locationName', '')

        return {
            'external_id': str(raw_data['id']),
            'device_name': system.get('name', ''),
            'device_type': device_type,
            'manufacturer': system.get('manufacturer', ''),
            'model': system.get('model', ''),
            'serial_number': system.get('serialNumber') or system.get('biosSerialNumber', ''),
            'os_type': os_type,
            'os_version': os_version,
            'hostname': system.get('dnsName', ''),
            'ip_address': ip_address,
            'mac_address': mac_address,
            'is_online': raw_data.get('online', False),
            'last_seen': last_seen,
            # Organization/Client mapping for proper org assignment
            'organization_id': str(organization_id) if organization_id else '',
            'organization_name': organization_name,
            'client_id': str(organization_id) if organization_id else '',  # Alias
            'client_name': organization_name,  # Alias
            # Location/Site info (less preferred than organization)
            'location_id': str(location_id) if location_id else '',
            'location_name': location_name,
            'site_id': str(location_id) if location_id else '',  # Alias
            'site_name': location_name,  # Alias
            'raw_data': raw_data,
        }

    def normalize_alert(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize NinjaOne alert data to standard format.

        NinjaOne alert structure:
        {
            "uid": "abc-123-def-456",
            "deviceId": 123,
            "type": "ANTIVIRUS",
            "message": "Threat detected",
            "severity": "CRITICAL",
            "status": "OPEN",
            "createTime": "2026-01-11T01:00:00Z",
            "updateTime": "2026-01-11T01:30:00Z"
        }
        """
        # Map NinjaOne severity to standard levels
        severity_map = {
            'NONE': 'info',
            'MINOR': 'warning',
            'MODERATE': 'warning',
            'MAJOR': 'error',
            'CRITICAL': 'critical',
        }

        ninja_severity = raw_data.get('severity', 'NONE').upper()
        severity = severity_map.get(ninja_severity, 'info')

        # Map status
        ninja_status = raw_data.get('status', 'OPEN').upper()
        status = 'active' if ninja_status == 'OPEN' else 'resolved'

        # Parse timestamps
        triggered_at = self._parse_datetime(raw_data.get('createTime'))
        resolved_at = self._parse_datetime(raw_data.get('resolvedTime')) if status == 'resolved' else None

        return {
            'external_id': str(raw_data.get('uid', '')),
            'device_id': str(raw_data.get('deviceId', '')),
            'alert_type': raw_data.get('type', ''),
            'message': raw_data.get('message', ''),
            'severity': severity,
            'status': status,
            'triggered_at': triggered_at,
            'resolved_at': resolved_at,
            'raw_data': raw_data,
        }

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
