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
        self._agents_by_guid = {}
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
                        normalized = self.normalize_device(device_data)
                        devices.append(normalized)
                        self._remember_agent(device_data)
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

    def _remember_agent(self, agent):
        guid = str(agent.get('DeviceGuid') or '').strip().lower()
        if guid and agent.get('AgentID') is not None:
            self._agents_by_guid[guid] = (str(agent['AgentID']), str(agent.get('CustomerID') or ''))

    def _agent_lookup(self):
        """DeviceGuid → (AgentID, CustomerID), from this sync's agent list or,
        when devices weren't synced, one paged read of /v3/agents."""
        if getattr(self, '_agents_by_guid', None):
            return self._agents_by_guid
        self._agents_by_guid = {}
        page = 1
        while True:
            data = self._make_request('GET', '/v3/agents', params={'page': page, 'itemsInPage': 50}).json() or {}
            for agent in data.get('items') or []:
                self._remember_agent(agent)
            if page >= (data.get('totalPages') or 0):
                break
            page += 1
        return self._agents_by_guid

    def list_alerts(
        self,
        device_id: Optional[str] = None,
        status: Optional[str] = None,
        updated_since: Optional[datetime] = None,
        page_size: int = 50
    ) -> List[Dict[str, Any]]:
        """
        List alerts (GET /v3/alerts). An alert names its machine by
        `DeviceGuid`; it is tied to an agent only when that GUID belongs to an
        agent of this account and both carry the same `CustomerID`.

        Earlier versions read /v3/tickets and treated a ticket's `EndUserID`
        as the device. EndUserID is the contact who raised the ticket, so
        alerts were pinned to whichever device happened to share that number.
        """
        alerts = []
        page = 1
        page_size = min(page_size, 50)
        try:
            agents = self._agent_lookup()
            while True:
                params = {'page': page, 'itemsInPage': page_size}
                if status == 'active':
                    params['alertStatus'] = 'Open'
                elif status == 'resolved':
                    params['alertStatus'] = 'Closed'
                data = self._make_request('GET', '/v3/alerts', params=params).json() or {}
                for alert_data in data.get('items') or []:
                    try:
                        alert = self.normalize_alert(alert_data)
                        guid = str(alert_data.get('DeviceGuid') or '').strip().lower()
                        agent = agents.get(guid) if guid else None
                        alert_customer = str(alert_data.get('CustomerID') or '')
                        if agent and (not alert_customer or not agent[1] or alert_customer == agent[1]):
                            alert['device_id'] = agent[0]
                        else:
                            alert['device_id'] = ''
                        if device_id and alert['device_id'] != str(device_id):
                            continue
                        alerts.append(alert)
                    except Exception as e:
                        logger.error(f"Error normalizing Atera alert {alert_data.get('AlertID')}: {e}")
                if page >= (data.get('totalPages') or 0):
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
            # Raise so the sync keeps this device\'s stored software
            # instead of reading the failure as "nothing installed".
            raise ProviderError(f"Failed to list software: {e}")

    def normalize_device(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize an Atera agent (/v3/agents):

            {
              "AgentID": 123456, "DeviceGuid": "6f0c…", "MachineName": "FRONTDESK",
              "CustomerID": 42, "CustomerName": "Acme Ltd", "FolderID": 3,
              "Online": true, "Vendor": "Dell Inc.", "VendorBrandModel": "OptiPlex 7090",
              "VendorSerialNumber": "ABC12345", "OSType": "Windows", "OSVersion": "11",
              "IpAddresses": ["192.168.1.10"], "MacAddresses": ["00-11-…"],
              "LastSeen": "2026-11-08T09:00:00", "AppViewUrl": "https://app.atera.com/…"
            }

        The customer is Atera's own CustomerID. Atera has no site level
        (FolderID is a grouping inside a customer), so no site is reported.
        """
        agent_type = str(raw_data.get('AgentType') or raw_data.get('DeviceType') or 'Workstation').lower()
        device_type = self.AGENT_TYPE_MAP.get(agent_type, 'workstation')

        os_name = raw_data.get('OSType', '') or ''
        os_version = f"{os_name} {raw_data.get('OSVersion', '') or ''}".strip()

        ips = raw_data.get('IpAddresses') or []
        macs = raw_data.get('MacAddresses') or []
        ip_address = raw_data.get('IPAddress') or (ips[0] if ips else None)
        mac_address = (raw_data.get('MacAddress') or (macs[0] if macs else '') or '').replace('-', ':')

        customer_id = raw_data.get('CustomerID')
        machine = raw_data.get('MachineName') or raw_data.get('AgentName') or raw_data.get('SystemName') or ''
        last_seen = (raw_data.get('LastSeen') or raw_data.get('LastSeenTime') or raw_data.get('Modified'))

        return {
            'external_id': str(raw_data.get('AgentID') if raw_data.get('AgentID') is not None else ''),
            'device_name': machine,
            'device_type': device_type,
            'manufacturer': raw_data.get('Vendor') or raw_data.get('Manufacturer', '') or '',
            'model': raw_data.get('VendorBrandModel') or raw_data.get('Model', '') or '',
            'serial_number': raw_data.get('VendorSerialNumber') or raw_data.get('SerialNumber', '') or '',
            'os_type': self._map_os_type(os_name.lower()),
            'os_version': os_version,
            'hostname': machine,
            'ip_address': ip_address,
            'mac_address': mac_address,
            'is_online': bool(raw_data.get('Online', False)),
            'last_seen': self._parse_datetime(last_seen),
            'client_id': str(customer_id) if customer_id is not None else '',
            'client_name': raw_data.get('CustomerName', '') or '',
            'site_id': '',
            'site_name': '',
            'raw_data': raw_data,
        }

    def normalize_alert(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize an Atera alert: `AlertID`, `DeviceGuid`, `CustomerID`,
        `Severity` (Information / Warning / Critical), `Title`, `Created`,
        `Archived`, `ArchivedDate`. The device is filled in by list_alerts
        once the GUID is verified against an agent.
        """
        severity_map = {'information': 'info', 'warning': 'warning', 'critical': 'critical', 'error': 'error'}
        severity = severity_map.get(str(raw_data.get('Severity') or 'Information').lower(), 'warning')
        archived = bool(raw_data.get('Archived'))

        return {
            'external_id': str(raw_data.get('AlertID') if raw_data.get('AlertID') is not None else ''),
            'device_id': '',
            'alert_type': raw_data.get('AlertCategoryID') or raw_data.get('Source') or 'alert',
            'message': raw_data.get('Title') or raw_data.get('AlertMessage') or '',
            'severity': severity,
            'status': 'resolved' if archived else 'active',
            'triggered_at': self._parse_datetime(raw_data.get('Created')),
            'resolved_at': self._parse_datetime(raw_data.get('ArchivedDate')) if archived else None,
            'raw_data': raw_data,
        }

    # Atera returns each agent's console address in `AppViewUrl`; it is
    # shown only when it points at Atera's own web app.
    console_link_mode = 'static'

    @classmethod
    def console_hosts(cls, connection):
        return {'app.atera.com'}

    @classmethod
    def device_console_url(cls, connection, device):
        return (device.raw_data or {}).get('AppViewUrl') or ''

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
