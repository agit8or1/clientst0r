"""
Atera RMM Provider

API Documentation: https://app.atera.com/api/v3/swagger/ui/index
Authentication: API Key (X-API-KEY header)
"""
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from ..rmm_base import BaseRMMProvider, ProviderError, AuthenticationError

logger = logging.getLogger('integrations')


class AteraProvider(BaseRMMProvider):
    """
    Atera RMM provider implementation.

    Supports:
    - Device (agent) inventory sync
    - Alert monitoring
    - Software inventory
    - Simple pagination
    """

    provider_name = 'Atera'
    supports_software = True

    # Agent type to device type mapping
    AGENT_TYPE_MAP = {
        'workstation': 'workstation',
        'server': 'server',
        'laptop': 'laptop',
    }

    def _get_auth_headers(self) -> Dict[str, str]:
        """
        Atera uses API Key authentication in X-API-KEY header.

        Credentials should contain:
        - api_key: Atera API key
        """
        credentials = self.connection.get_credentials()

        if not credentials.get('api_key'):
            raise AuthenticationError('Atera api_key not configured')

        return {
            'X-API-KEY': credentials['api_key'],
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

    def test_connection(self) -> bool:
        """
        Test API connectivity by fetching customers.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            response = self._make_request('GET', '/v3/customers', params={'page': 1, 'itemsInPage': 1})
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Atera connection test failed: {e}")
            return False

    def list_devices(self, page_size: int = 50, updated_since: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        List all agents (devices).

        Atera uses simple page-based pagination.

        Args:
            page_size: Number of devices per page (max 50)
            updated_since: Not supported by Atera API

        Returns:
            List of normalized device dictionaries
        """
        devices = []
        page = 1
        page_size = min(page_size, 50)  # Atera max is 50

        try:
            while True:
                params = {
                    'page': page,
                    'itemsInPage': page_size,
                }

                response = self._make_request('GET', '/v3/agents', params=params)
                data = response.json()

                # Atera returns array of agents
                page_data = data.get('items', [])

                if not page_data:
                    break

                for device_data in page_data:
                    try:
                        devices.append(self.normalize_device(device_data))
                    except Exception as e:
                        logger.error(f"Error normalizing Atera device {device_data.get('AgentID')}: {e}")

                # Check if there are more pages
                total_pages = data.get('totalPages', 0)
                if page >= total_pages:
                    break

                page += 1
                logger.debug(f"Atera: Fetched page {page}/{total_pages}")

            logger.info(f"Atera: Retrieved {len(devices)} total devices")
            return devices

        except Exception as e:
            logger.error(f"Error listing Atera devices: {e}")
            raise ProviderError(f"Failed to list devices: {e}")

    def get_device(self, device_id: str) -> Dict[str, Any]:
        """
        Get single agent by ID.

        Args:
            device_id: Atera agent ID

        Returns:
            Normalized device dictionary
        """
        try:
            response = self._make_request('GET', f'/v3/agents/{device_id}')
            return self.normalize_device(response.json())
        except Exception as e:
            logger.error(f"Error getting Atera device {device_id}: {e}")
            raise ProviderError(f"Failed to get device: {e}")

    def list_alerts(
        self,
        device_id: Optional[str] = None,
        status: Optional[str] = None,
        updated_since: Optional[datetime] = None,
        page_size: int = 50
    ) -> List[Dict[str, Any]]:
        """
        List monitoring alerts.

        Atera tracks alerts in the ticketing system.

        Args:
            device_id: Filter by agent ID
            status: Filter by status (Open, Pending, Resolved)
            updated_since: Filter by date
            page_size: Number of alerts per page

        Returns:
            List of normalized alert dictionaries
        """
        alerts = []
        page = 1
        page_size = min(page_size, 50)

        try:
            while True:
                params = {
                    'page': page,
                    'itemsInPage': page_size,
                }

                # Atera uses tickets for alerts
                response = self._make_request('GET', '/v3/tickets', params=params)
                data = response.json()

                page_data = data.get('items', [])

                if not page_data:
                    break

                for alert_data in page_data:
                    try:
                        # Filter by device if specified
                        if device_id and str(alert_data.get('EndUserID')) != device_id:
                            continue

                        # Filter by status if specified
                        if status:
                            alert_status = 'active' if alert_data.get('TicketStatus') in ['Open', 'Pending'] else 'resolved'
                            if alert_status != status:
                                continue

                        alerts.append(self.normalize_alert(alert_data))
                    except Exception as e:
                        logger.error(f"Error normalizing Atera alert {alert_data.get('TicketID')}: {e}")

                # Check pagination
                total_pages = data.get('totalPages', 0)
                if page >= total_pages:
                    break

                page += 1

            logger.info(f"Atera: Retrieved {len(alerts)} alerts")
            return alerts

        except Exception as e:
            logger.error(f"Error listing Atera alerts: {e}")
            raise ProviderError(f"Failed to list alerts: {e}")

    def list_software(self, device_id: str) -> List[Dict[str, Any]]:
        """
        List software installed on a device.

        Args:
            device_id: Atera agent ID

        Returns:
            List of normalized software dictionaries
        """
        software_list = []

        try:
            # Atera endpoint for agent software
            response = self._make_request('GET', f'/v3/agents/{device_id}/software')
            data = response.json()

            software_data = data.get('items', [])

            for sw_data in software_data:
                try:
                    software_list.append(self.normalize_software(sw_data))
                except Exception as e:
                    logger.error(f"Error normalizing Atera software: {e}")

            logger.debug(f"Atera: Retrieved {len(software_list)} software items for device {device_id}")
            return software_list

        except Exception as e:
            logger.error(f"Error listing Atera software for device {device_id}: {e}")
            return software_list

    def normalize_device(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize Atera agent data to standard format.

        Atera agent structure:
        {
            "AgentID": 123456,
            "MachineName": "DESKTOP-ABC123",
            "DomainName": "WORKGROUP",
            "AgentType": "Workstation",
            "Manufacturer": "Dell Inc.",
            "Model": "OptiPlex 7090",
            "SerialNumber": "ABC12345",
            "OSType": "Windows",
            "OSVersion": "10.0.19045",
            "IPAddress": "192.168.1.100",
            "MacAddress": "00-11-22-33-44-55",
            "Online": true,
            "LastSeenTime": "2026-01-11T02:00:00Z"
        }
        """
        # Map agent type to device type
        agent_type = raw_data.get('AgentType', 'Workstation').lower()
        device_type = self.AGENT_TYPE_MAP.get(agent_type, 'workstation')

        # Parse OS type
        os_type_raw = raw_data.get('OSType', '').lower()
        os_type = self._map_os_type(os_type_raw)

        # Build OS version string
        os_name = raw_data.get('OSType', '')
        os_version_num = raw_data.get('OSVersion', '')
        os_version = f"{os_name} {os_version_num}".strip()

        # Parse last seen time
        last_seen = self._parse_datetime(raw_data.get('LastSeenTime'))

        # Normalize MAC address format (Atera uses dashes)
        mac_address = raw_data.get('MacAddress', '').replace('-', ':')

        return {
            'external_id': str(raw_data.get('AgentID', '')),
            'device_name': raw_data.get('MachineName', ''),
            'device_type': device_type,
            'manufacturer': raw_data.get('Manufacturer', ''),
            'model': raw_data.get('Model', ''),
            'serial_number': raw_data.get('SerialNumber', ''),
            'os_type': os_type,
            'os_version': os_version,
            'hostname': raw_data.get('MachineName', ''),
            'ip_address': raw_data.get('IPAddress'),
            'mac_address': mac_address,
            'is_online': raw_data.get('Online', False),
            'last_seen': last_seen,
            'raw_data': raw_data,
        }

    def normalize_alert(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize Atera ticket data to standard format.

        Atera ticket structure:
        {
            "TicketID": 12345,
            "TicketNumber": 1001,
            "TicketTitle": "Antivirus alert",
            "TicketStatus": "Open",
            "TicketPriority": "High",
            "TicketType": "Problem",
            "EndUserID": 123,
            "CreateDate": "2026-01-11T01:00:00Z",
            "LastEndUserUpdate": "2026-01-11T01:30:00Z",
            "CloseDate": null
        }
        """
        # Map priority to severity
        priority_map = {
            'low': 'info',
            'normal': 'warning',
            'high': 'error',
            'critical': 'critical',
        }

        priority = raw_data.get('TicketPriority', 'Normal').lower()
        severity = priority_map.get(priority, 'warning')

        # Map status
        ticket_status = raw_data.get('TicketStatus', 'Open')
        status = 'active' if ticket_status in ['Open', 'Pending'] else 'resolved'

        # Parse timestamps
        triggered_at = self._parse_datetime(raw_data.get('CreateDate'))
        resolved_at = self._parse_datetime(raw_data.get('CloseDate')) if status == 'resolved' else None

        return {
            'external_id': str(raw_data.get('TicketID', '')),
            'device_id': str(raw_data.get('EndUserID', '')),
            'alert_type': raw_data.get('TicketType', ''),
            'message': raw_data.get('TicketTitle', ''),
            'severity': severity,
            'status': status,
            'triggered_at': triggered_at,
            'resolved_at': resolved_at,
            'raw_data': raw_data,
        }

    def normalize_software(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize Atera software data to standard format.

        Atera software structure:
        {
            "SoftwareID": "abc-123",
            "SoftwareName": "Google Chrome",
            "SoftwareVersion": "120.0.6099.71",
            "Publisher": "Google LLC",
            "InstallDate": "2025-12-15T00:00:00Z"
        }
        """
        install_date = self._parse_datetime(raw_data.get('InstallDate'))

        return {
            'external_id': str(raw_data.get('SoftwareID', '')),
            'name': raw_data.get('SoftwareName', ''),
            'version': raw_data.get('SoftwareVersion', ''),
            'vendor': raw_data.get('Publisher', ''),
            'install_date': install_date,
            'raw_data': raw_data,
        }

    def _map_os_type(self, os_name: str) -> str:
        """Map OS name to standard OS type."""
        os_lower = os_name.lower()

        if 'windows' in os_lower:
            return 'windows'
        elif 'mac' in os_lower or 'darwin' in os_lower or 'osx' in os_lower:
            return 'macos'
        elif 'linux' in os_lower or 'ubuntu' in os_lower or 'centos' in os_lower:
            return 'linux'
        elif 'ios' in os_lower:
            return 'ios'
        elif 'android' in os_lower:
            return 'android'
        else:
            return 'other'
