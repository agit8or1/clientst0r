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

    def list_devices(self, page_size: int = 100, updated_since: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        List all devices.

        Datto RMM uses offset-based pagination.

        Args:
            page_size: Number of devices per page
            updated_since: Filter by last modified time

        Returns:
            List of normalized device dictionaries
        """
        devices = []
        page = 1

        try:
            while True:
                params = {
                    'pageSize': page_size,
                    'page': page,
                }

                response = self._make_request('GET', '/api/v2/account/devices', params=params)
                data = response.json()

                # Datto returns paginated response
                page_data = data.get('devices', [])

                if not page_data:
                    break

                for device_data in page_data:
                    try:
                        # Filter by updated_since if specified
                        if updated_since:
                            last_seen_str = device_data.get('lastSeen')
                            if last_seen_str:
                                last_seen = self._parse_datetime(last_seen_str)
                                if last_seen and last_seen < updated_since:
                                    continue

                        devices.append(self.normalize_device(device_data))
                    except Exception as e:
                        logger.error(f"Error normalizing Datto device {device_data.get('uid')}: {e}")

                # Check if there are more pages
                page_number = data.get('pageNumber', 0)
                total_pages = data.get('totalPages', 0)

                if page_number >= total_pages:
                    break

                page += 1
                logger.debug(f"Datto RMM: Fetched page {page_number}/{total_pages}")

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
            response = self._make_request('GET', f'/api/v2/account/devices/{device_id}')
            return self.normalize_device(response.json())
        except Exception as e:
            logger.error(f"Error getting Datto device {device_id}: {e}")
            raise ProviderError(f"Failed to get device: {e}")

    def list_alerts(
        self,
        device_id: Optional[str] = None,
        status: Optional[str] = None,
        updated_since: Optional[datetime] = None,
        page_size: int = 100
    ) -> List[Dict[str, Any]]:
        """
        List monitoring alerts (open tickets).

        Args:
            device_id: Filter by device UID
            status: Filter by status (open, resolved)
            updated_since: Only return alerts updated after this time
            page_size: Number of alerts per page

        Returns:
            List of normalized alert dictionaries
        """
        alerts = []
        page = 1

        try:
            while True:
                params = {
                    'pageSize': page_size,
                    'page': page,
                }

                if device_id:
                    params['deviceUid'] = device_id

                # Datto calls them "open tickets"
                response = self._make_request('GET', '/api/v2/account/tickets/open', params=params)
                data = response.json()

                page_data = data.get('tickets', [])

                if not page_data:
                    break

                for alert_data in page_data:
                    try:
                        # Filter by status if specified
                        if status:
                            alert_status = 'active' if alert_data.get('status') == 'open' else 'resolved'
                            if alert_status != status:
                                continue

                        alerts.append(self.normalize_alert(alert_data))
                    except Exception as e:
                        logger.error(f"Error normalizing Datto alert {alert_data.get('id')}: {e}")

                # Check pagination
                page_number = data.get('pageNumber', 0)
                total_pages = data.get('totalPages', 0)

                if page_number >= total_pages:
                    break

                page += 1

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
            response = self._make_request('GET', f'/api/v2/account/devices/{device_id}/software')
            data = response.json()

            software_data = data.get('software', [])

            for sw_data in software_data:
                try:
                    software_list.append(self.normalize_software(sw_data))
                except Exception as e:
                    logger.error(f"Error normalizing Datto software: {e}")

            logger.debug(f"Datto RMM: Retrieved {len(software_list)} software items for device {device_id}")
            return software_list

        except Exception as e:
            logger.error(f"Error listing Datto RMM software for device {device_id}: {e}")
            return software_list

    def normalize_device(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize Datto RMM device data to standard format.

        Datto device structure:
        {
            "uid": "abc-123-def-456",
            "hostname": "DESKTOP-ABC123",
            "description": "John's Computer",
            "deviceType": {
                "category": "desktop"
            },
            "manufacturer": "Dell Inc.",
            "model": "OptiPlex 7090",
            "serialNumber": "ABC12345",
            "operatingSystem": "Microsoft Windows 10 Pro",
            "domain": "WORKGROUP",
            "ipAddress": "192.168.1.100",
            "macAddress": "00:11:22:33:44:55",
            "online": true,
            "lastSeen": "2026-01-11T02:00:00Z"
        }
        """
        # Map device type
        device_type_category = raw_data.get('deviceType', {}).get('category', 'unknown').lower()
        device_type = self.DEVICE_TYPE_MAP.get(device_type_category, 'unknown')

        # Parse OS type
        os_name = raw_data.get('operatingSystem', '')
        os_type = self._map_os_type(os_name)

        # Parse last seen
        last_seen = self._parse_datetime(raw_data.get('lastSeen'))

        # Extract site/client information
        # Datto RMM provides siteUid/siteId and siteName
        site_id = raw_data.get('siteUid', '') or raw_data.get('siteId', '')
        site_name = raw_data.get('siteName', '')

        return {
            'external_id': str(raw_data.get('uid', '')),
            'device_name': raw_data.get('hostname', '') or raw_data.get('description', ''),
            'device_type': device_type,
            'manufacturer': raw_data.get('manufacturer', ''),
            'model': raw_data.get('model', ''),
            'serial_number': raw_data.get('serialNumber', ''),
            'os_type': os_type,
            'os_version': os_name,
            'hostname': raw_data.get('hostname', ''),
            'ip_address': raw_data.get('ipAddress'),
            'mac_address': raw_data.get('macAddress', ''),
            'is_online': raw_data.get('online', False),
            'last_seen': last_seen,
            # Site/Client mapping for proper org assignment
            'site_id': str(site_id) if site_id else '',
            'site_name': site_name,
            'client_id': str(site_id) if site_id else '',  # Datto uses "site" for client
            'client_name': site_name,  # Datto uses "site" for client
            'raw_data': raw_data,
        }

    def normalize_alert(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize Datto RMM alert (ticket) data to standard format.

        Datto alert structure:
        {
            "id": 12345,
            "ticketNumber": "TKT-001",
            "deviceUid": "abc-123-def-456",
            "subject": "Antivirus alert",
            "priority": "high",
            "status": "open",
            "createDate": "2026-01-11T01:00:00Z",
            "modifiedDate": "2026-01-11T01:30:00Z"
        }
        """
        # Map priority to severity
        priority_map = {
            'low': 'info',
            'normal': 'warning',
            'high': 'error',
            'critical': 'critical',
        }

        priority = raw_data.get('priority', 'normal').lower()
        severity = priority_map.get(priority, 'warning')

        # Map status
        status = 'active' if raw_data.get('status') == 'open' else 'resolved'

        # Parse timestamps
        triggered_at = self._parse_datetime(raw_data.get('createDate'))
        resolved_at = self._parse_datetime(raw_data.get('resolvedDate')) if status == 'resolved' else None

        return {
            'external_id': str(raw_data.get('id', '')),
            'device_id': str(raw_data.get('deviceUid', '')),
            'alert_type': raw_data.get('alertSourceInfo', {}).get('source', 'ticket'),
            'message': raw_data.get('subject', ''),
            'severity': severity,
            'status': status,
            'triggered_at': triggered_at,
            'resolved_at': resolved_at,
            'raw_data': raw_data,
        }

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
            except:
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
