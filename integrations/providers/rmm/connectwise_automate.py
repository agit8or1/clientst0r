"""
ConnectWise Automate (LabTech) RMM Provider

API Documentation: https://docs.connectwise.com/ConnectWise_Automate/ConnectWise_Automate_Documentation
Authentication: Username + Password (Basic Auth) or API Token
"""
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
import base64
from ..rmm_base import BaseRMMProvider, ProviderError, AuthenticationError

logger = logging.getLogger('integrations')


class ConnectWiseAutomateProvider(BaseRMMProvider):
    """
    ConnectWise Automate (formerly LabTech) provider implementation.

    Supports:
    - Computer (device) inventory sync
    - Alert monitoring
    - Software inventory
    - Client/location hierarchy
    """

    provider_name = 'ConnectWise Automate'
    supports_software = True

    # Computer type to device type mapping
    COMPUTER_TYPE_MAP = {
        '0': 'workstation',  # Workstation
        '1': 'server',       # Server
        '2': 'laptop',       # Laptop
        '3': 'network',      # Network Device
    }

    def _get_auth_headers(self) -> Dict[str, str]:
        """
        ConnectWise Automate uses Basic Authentication or API Token.

        Credentials should contain:
        - username: Automate username or API user
        - password: Password or API token
        - client_id: Optional client ID for API token auth
        """
        credentials = self.connection.get_credentials()

        if not credentials.get('username') or not credentials.get('password'):
            raise AuthenticationError('ConnectWise Automate username and password required')

        # Create Basic Auth header
        auth_string = f"{credentials['username']}:{credentials['password']}"
        auth_bytes = auth_string.encode('utf-8')
        auth_b64 = base64.b64encode(auth_bytes).decode('utf-8')

        headers = {
            'Authorization': f'Basic {auth_b64}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

        # Add client ID if provided (for API token auth)
        if credentials.get('client_id'):
            headers['ClientID'] = credentials['client_id']

        return headers

    def test_connection(self) -> bool:
        """
        Test API connectivity by fetching system info.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            response = self._make_request('GET', '/cwa/api/v1/apiinfo')
            return response.status_code == 200
        except Exception as e:
            logger.error(f"ConnectWise Automate connection test failed: {e}")
            return False

    def list_devices(self, page_size: int = 100, updated_since: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        List all computers (devices).

        ConnectWise Automate uses index/limit pagination.

        Args:
            page_size: Number of devices per page
            updated_since: Filter by last contact time

        Returns:
            List of normalized device dictionaries
        """
        devices = []
        index = 0

        try:
            while True:
                params = {
                    'index': index,
                    'limit': page_size,
                }

                # Add condition for updated_since if specified
                if updated_since:
                    # Automate uses specific filter syntax
                    updated_str = updated_since.strftime('%Y-%m-%d %H:%M:%S')
                    params['condition'] = f"LastContact >= '{updated_str}'"

                response = self._make_request('GET', '/cwa/api/v1/computers', params=params)
                data = response.json()

                if not data or not isinstance(data, list):
                    break

                for device_data in data:
                    try:
                        devices.append(self.normalize_device(device_data))
                    except Exception as e:
                        logger.error(f"Error normalizing Automate device {device_data.get('Id')}: {e}")

                # Check if we got a full page (if not, we're done)
                if len(data) < page_size:
                    break

                index += page_size
                logger.debug(f"ConnectWise Automate: Fetched {index} devices")

            logger.info(f"ConnectWise Automate: Retrieved {len(devices)} total devices")
            return devices

        except Exception as e:
            logger.error(f"Error listing ConnectWise Automate devices: {e}")
            raise ProviderError(f"Failed to list devices: {e}")

    def get_device(self, device_id: str) -> Dict[str, Any]:
        """
        Get single computer by ID.

        Args:
            device_id: Automate computer ID

        Returns:
            Normalized device dictionary
        """
        try:
            response = self._make_request('GET', f'/cwa/api/v1/computers/{device_id}')
            return self.normalize_device(response.json())
        except Exception as e:
            logger.error(f"Error getting ConnectWise Automate device {device_id}: {e}")
            raise ProviderError(f"Failed to get device: {e}")

    def list_alerts(
        self,
        device_id: Optional[str] = None,
        status: Optional[str] = None,
        updated_since: Optional[datetime] = None,
        page_size: int = 100
    ) -> List[Dict[str, Any]]:
        """
        List monitoring alerts (from internal monitors).

        Args:
            device_id: Filter by computer ID
            status: Filter by status (active, resolved)
            updated_since: Filter by date
            page_size: Number of alerts per page

        Returns:
            List of normalized alert dictionaries
        """
        alerts = []
        index = 0

        try:
            while True:
                params = {
                    'index': index,
                    'limit': page_size,
                }

                # Build condition filter
                conditions = []
                if device_id:
                    conditions.append(f"ComputerId = {device_id}")
                if status == 'active':
                    conditions.append("Status = 'Alert'")
                elif status == 'resolved':
                    conditions.append("Status = 'Resolved'")

                if conditions:
                    params['condition'] = ' AND '.join(conditions)

                # Automate calls them "internal monitors"
                response = self._make_request('GET', '/cwa/api/v1/internalmonitors', params=params)
                data = response.json()

                if not data or not isinstance(data, list):
                    break

                for alert_data in data:
                    try:
                        alerts.append(self.normalize_alert(alert_data))
                    except Exception as e:
                        logger.error(f"Error normalizing Automate alert {alert_data.get('Id')}: {e}")

                if len(data) < page_size:
                    break

                index += page_size

            logger.info(f"ConnectWise Automate: Retrieved {len(alerts)} alerts")
            return alerts

        except Exception as e:
            logger.error(f"Error listing ConnectWise Automate alerts: {e}")
            raise ProviderError(f"Failed to list alerts: {e}")

    def list_software(self, device_id: str) -> List[Dict[str, Any]]:
        """
        List software installed on a computer.

        Args:
            device_id: Automate computer ID

        Returns:
            List of normalized software dictionaries
        """
        software_list = []
        index = 0
        page_size = 100

        try:
            while True:
                params = {
                    'condition': f'ComputerId = {device_id}',
                    'index': index,
                    'limit': page_size,
                }

                response = self._make_request('GET', '/cwa/api/v1/computers/software', params=params)
                data = response.json()

                if not data or not isinstance(data, list):
                    break

                for sw_data in data:
                    try:
                        software_list.append(self.normalize_software(sw_data))
                    except Exception as e:
                        logger.error(f"Error normalizing Automate software: {e}")

                if len(data) < page_size:
                    break

                index += page_size

            logger.debug(f"ConnectWise Automate: Retrieved {len(software_list)} software items for computer {device_id}")
            return software_list

        except Exception as e:
            logger.error(f"Error listing ConnectWise Automate software for computer {device_id}: {e}")
            return software_list

    def normalize_device(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize ConnectWise Automate computer data to standard format.

        Automate computer structure:
        {
            "Id": 12345,
            "Name": "DESKTOP-ABC123",
            "Domain": "WORKGROUP",
            "Type": "0",
            "Manufacturer": "Dell Inc.",
            "Model": "OptiPlex 7090",
            "SerialNumber": "ABC12345",
            "OS": "Windows 10 Pro",
            "LocalIPAddress": "192.168.1.100",
            "MACAddress": "00:11:22:33:44:55",
            "Status": "Online",
            "LastContact": "2026-01-11T02:00:00Z",
            "ClientId": 1,
            "LocationId": 10
        }
        """
        # Map computer type
        comp_type = str(raw_data.get('Type', '0'))
        device_type = self.COMPUTER_TYPE_MAP.get(comp_type, 'workstation')

        # Parse OS type
        os_name = raw_data.get('OS', '')
        os_type = self._map_os_type(os_name)

        # Parse last contact
        last_seen = self._parse_datetime(raw_data.get('LastContact'))

        # Determine online status
        status = raw_data.get('Status', '').lower()
        is_online = status == 'online'

        return {
            'external_id': str(raw_data.get('Id', '')),
            'device_name': raw_data.get('Name', ''),
            'device_type': device_type,
            'manufacturer': raw_data.get('Manufacturer', ''),
            'model': raw_data.get('Model', ''),
            'serial_number': raw_data.get('SerialNumber', ''),
            'os_type': os_type,
            'os_version': os_name,
            'hostname': raw_data.get('Name', ''),
            'ip_address': raw_data.get('LocalIPAddress'),
            'mac_address': raw_data.get('MACAddress', ''),
            'is_online': is_online,
            'last_seen': last_seen,
            'raw_data': raw_data,
        }

    def normalize_alert(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize ConnectWise Automate internal monitor data to standard format.

        Automate alert structure:
        {
            "Id": 123,
            "ComputerId": 12345,
            "Name": "Disk Space",
            "Message": "C: drive low on space",
            "Status": "Alert",
            "Severity": "Warning",
            "CreateDate": "2026-01-11T01:00:00Z",
            "LastAlertDate": "2026-01-11T01:30:00Z"
        }
        """
        # Map severity
        severity_map = {
            'informational': 'info',
            'warning': 'warning',
            'error': 'error',
            'critical': 'critical',
        }

        sev = raw_data.get('Severity', 'Warning').lower()
        severity = severity_map.get(sev, 'warning')

        # Map status
        status = 'active' if raw_data.get('Status') == 'Alert' else 'resolved'

        # Parse timestamps
        triggered_at = self._parse_datetime(raw_data.get('CreateDate'))
        resolved_at = None  # Automate doesn't track resolution time directly

        return {
            'external_id': str(raw_data.get('Id', '')),
            'device_id': str(raw_data.get('ComputerId', '')),
            'alert_type': raw_data.get('Name', ''),
            'message': raw_data.get('Message', ''),
            'severity': severity,
            'status': status,
            'triggered_at': triggered_at,
            'resolved_at': resolved_at,
            'raw_data': raw_data,
        }

    def normalize_software(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize ConnectWise Automate software data to standard format.

        Automate software structure:
        {
            "Id": 12345,
            "ComputerId": 123,
            "Name": "Google Chrome",
            "Version": "120.0.6099.71",
            "Publisher": "Google LLC",
            "InstallDate": "2025-12-15T00:00:00Z"
        }
        """
        install_date = self._parse_datetime(raw_data.get('InstallDate'))

        return {
            'external_id': str(raw_data.get('Id', '')),
            'name': raw_data.get('Name', ''),
            'version': raw_data.get('Version', ''),
            'vendor': raw_data.get('Publisher', ''),
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
