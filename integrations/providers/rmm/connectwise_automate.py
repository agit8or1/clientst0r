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

    def _paged(self, endpoint, page_size=100, extra=None):
        """Automate pages with `page` (from 1) and `pageSize`."""
        page = 1
        while True:
            params = {'page': page, 'pageSize': page_size}
            params.update(extra or {})
            data = self._make_request('GET', endpoint, params=params).json()
            if not data or not isinstance(data, list):
                return
            yield from data
            if len(data) < page_size:
                return
            page += 1

    def _name_lookups(self):
        """Client and location names, read once per sync, for payloads that
        carry only the IDs. Names are for display; identity is the ID."""
        clients, locations = {}, {}
        try:
            for row in self._paged('/cwa/api/v1/Clients', 500):
                clients[str(row.get('Id'))] = row.get('Name') or ''
            for row in self._paged('/cwa/api/v1/Locations', 500):
                locations[str(row.get('Id'))] = row.get('Name') or ''
        except Exception as e:
            logger.warning(f"ConnectWise Automate: client/location names unavailable: {e}")
        return clients, locations

    def list_devices(self, page_size: int = 100, updated_since: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        List all computers (GET /cwa/api/v1/Computers). Every sync reads the
        full list: a "changed since" condition would miss computers moved to
        another client without checking in.
        """
        devices = []
        try:
            rows = list(self._paged('/cwa/api/v1/Computers', page_size))
            needs_names = any(not isinstance(r.get('Client'), dict) and r.get('ClientId') for r in rows)
            self._client_names, self._location_names = self._name_lookups() if needs_names else ({}, {})
            for device_data in rows:
                try:
                    devices.append(self.normalize_device(device_data))
                except Exception as e:
                    logger.error(f"Error normalizing Automate device {device_data.get('Id')}: {e}")
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
        List alerts (GET /cwa/api/v1/Alerts, or one computer's
        /Computers/{id}/Alerts). Each alert names its computer in
        `Computer.Id`.
        """
        alerts = []
        endpoint = f'/cwa/api/v1/Computers/{device_id}/Alerts' if device_id else '/cwa/api/v1/Alerts'
        try:
            for alert_data in self._paged(endpoint, page_size):
                try:
                    alerts.append(self.normalize_alert(alert_data))
                except Exception as e:
                    logger.error(f"Error normalizing Automate alert {alert_data.get('AlertId')}: {e}")
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
        Normalize an Automate computer (REST API v1):

            {
              "Id": "12345", "ComputerName": "FRONTDESK", "FriendlyName": "",
              "SerialNumber": "ABC12345", "BiosManufacturer": "Dell Inc.",
              "Status": "Online", "RemoteAgentLastContact": "2026-11-08T09:00:00",
              "LocalIPAddress": "192.168.1.10", "MACAddress": "00:11:…",
              "OperatingSystemName": "Microsoft Windows 11 Pro",
              "Client": {"Id": 1, "Name": "Acme Ltd"},
              "Location": {"Id": 10, "Name": "Main Office"}
            }

        Older servers return flat `ClientId` / `LocationId` instead; their
        names come from the lookups read once per sync. Client and location
        stay separate: the client is the customer, the location its site.
        """
        comp_type = str(raw_data.get('Type', '0'))
        device_type = self.COMPUTER_TYPE_MAP.get(comp_type, 'workstation')
        os_name = raw_data.get('OperatingSystemName') or raw_data.get('OS') or ''
        status = str(raw_data.get('Status') or '').lower()

        client = raw_data.get('Client') if isinstance(raw_data.get('Client'), dict) else {}
        location = raw_data.get('Location') if isinstance(raw_data.get('Location'), dict) else {}
        client_id = client.get('Id', raw_data.get('ClientId'))
        location_id = location.get('Id', raw_data.get('LocationId'))
        client_name = client.get('Name') or getattr(self, '_client_names', {}).get(str(client_id), '')
        location_name = location.get('Name') or getattr(self, '_location_names', {}).get(str(location_id), '')

        name = raw_data.get('ComputerName') or raw_data.get('Name') or raw_data.get('FriendlyName') or ''
        last_seen = (raw_data.get('RemoteAgentLastContact') or raw_data.get('LastHeartbeat')
                     or raw_data.get('LastContact'))

        return {
            'external_id': str(raw_data.get('Id') if raw_data.get('Id') is not None else ''),
            'device_name': raw_data.get('FriendlyName') or name,
            'device_type': device_type,
            'manufacturer': raw_data.get('BiosManufacturer') or raw_data.get('Manufacturer', '') or '',
            'model': raw_data.get('Model', '') or '',
            'serial_number': raw_data.get('SerialNumber', '') or '',
            'os_type': self._map_os_type(os_name),
            'os_version': os_name,
            'hostname': name,
            'ip_address': raw_data.get('LocalIPAddress') or None,
            'mac_address': raw_data.get('MacAddress') or raw_data.get('MACAddress', '') or '',
            'is_online': status == 'online',
            'last_seen': self._parse_datetime(last_seen),
            'client_id': str(client_id) if client_id not in (None, '') else '',
            'client_name': client_name or '',
            'site_id': str(location_id) if location_id not in (None, '') else '',
            'site_name': location_name or '',
            'raw_data': raw_data,
        }

    def normalize_alert(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize an Automate alert: `AlertId`, `AlertDate`, `Severity`,
        `Message`, `Source`, `Computer {Id, Name}`.
        """
        severity_map = {
            'informational': 'info',
            'information': 'info',
            'warning': 'warning',
            'error': 'error',
            'critical': 'critical',
        }
        sev = raw_data.get('Severity')
        if isinstance(sev, dict):
            sev = sev.get('Name') or sev.get('Label') or ''
        severity = severity_map.get(str(sev or 'warning').lower(), 'warning')
        computer = raw_data.get('Computer') if isinstance(raw_data.get('Computer'), dict) else {}
        computer_id = computer.get('Id', raw_data.get('ComputerId'))
        alert_id = raw_data.get('AlertId', raw_data.get('Id'))

        return {
            'external_id': str(alert_id) if alert_id is not None else '',
            'device_id': str(computer_id) if computer_id is not None else '',
            'alert_type': raw_data.get('Source') or raw_data.get('Name', '') or '',
            'message': raw_data.get('Message', '') or '',
            'severity': severity,
            'status': 'active',
            'triggered_at': self._parse_datetime(raw_data.get('AlertDate') or raw_data.get('CreateDate')),
            'resolved_at': None,
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
