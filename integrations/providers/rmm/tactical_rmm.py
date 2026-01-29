"""
Tactical RMM Provider

API Documentation: https://docs.tacticalrmm.com/api/
Authentication: Bearer Token (API Key)
"""
import logging
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from ..rmm_base import BaseRMMProvider, ProviderError, AuthenticationError

logger = logging.getLogger('integrations')


class TacticalRMMProvider(BaseRMMProvider):
    """
    Tactical RMM provider implementation.

    Supports:
    - Device inventory sync
    - Alert monitoring
    - Software inventory
    """

    provider_name = 'Tactical RMM'
    supports_software = True

    # Agent type to device type mapping
    AGENT_TYPE_MAP = {
        'server': 'server',
        'workstation': 'workstation',
        'laptop': 'laptop',
    }

    def _get_auth_headers(self) -> Dict[str, str]:
        """
        API Key authentication.

        Credentials should contain:
        - api_key: Tactical RMM API key
        """
        credentials = self.connection.get_credentials()

        if not credentials.get('api_key'):
            raise AuthenticationError('Tactical RMM API key not configured')

        return {
            'X-API-KEY': credentials['api_key'],
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

    def _safe_json(self, response):
        """
        Safely parse JSON response with better error handling.
        Raises ProviderError with detailed message if parsing fails.
        """
        # Check if response has content
        if not response.content:
            raise ProviderError(
                f"Empty response from Tactical RMM API (Status: {response.status_code}, "
                f"URL: {response.url}). The API endpoint may not exist or returned no data. "
                f"Please verify your Tactical RMM base URL is correct."
            )

        # Try to parse JSON
        try:
            return response.json()
        except json.JSONDecodeError as e:
            # Log the actual response content for debugging
            content_preview = response.text[:500] if response.text else "(empty)"
            logger.error(
                f"Invalid JSON from Tactical RMM API. "
                f"Status: {response.status_code}, "
                f"URL: {response.url}, "
                f"Content preview: {content_preview}"
            )
            raise ProviderError(
                f"Invalid JSON response from Tactical RMM API (Status: {response.status_code}). "
                f"The API may be misconfigured or returning HTML instead of JSON. "
                f"Please verify:\n"
                f"1. Your Tactical RMM base URL is correct (e.g., https://rmm.yourdomain.com)\n"
                f"2. Your API key has the correct permissions\n"
                f"3. The API endpoint exists on your Tactical RMM version\n"
                f"Response preview: {content_preview}"
            )

    def test_connection(self) -> bool:
        """
        Test API connectivity by listing agents (limit 1).

        Returns:
            True if connection successful, False otherwise
        """
        try:
            response = self._make_request('GET', '/agents/', params={'limit': 1})
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Tactical RMM connection test failed: {e}")
            return False

    def list_devices(self, page_size: int = 100, updated_since: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        List all agents (devices).

        Args:
            page_size: Number of devices per page
            updated_since: Only return devices updated after this time (not supported by Tactical RMM)

        Returns:
            List of normalized device dictionaries
        """
        devices = []

        try:
            # Tactical RMM returns all agents in single response
            response = self._make_request('GET', '/agents/')
            data = self._safe_json(response)

            if not isinstance(data, list):
                logger.error(f"Unexpected response format from Tactical RMM: {type(data)}")
                return devices

            for agent_data in data:
                try:
                    devices.append(self.normalize_device(agent_data))
                except Exception as e:
                    logger.error(f"Error normalizing Tactical RMM agent {agent_data.get('agent_id')}: {e}")

            logger.info(f"Tactical RMM: Retrieved {len(devices)} agents")
            return devices

        except Exception as e:
            logger.error(f"Error listing Tactical RMM agents: {e}")
            raise ProviderError(f"Failed to list devices: {e}")

    def get_device(self, device_id: str) -> Dict[str, Any]:
        """
        Get single agent by ID.

        Args:
            device_id: Tactical RMM agent ID

        Returns:
            Normalized device dictionary
        """
        try:
            response = self._make_request('GET', f'/agents/{device_id}/')
            return self.normalize_device(self._safe_json(response))
        except Exception as e:
            logger.error(f"Error getting Tactical RMM agent {device_id}: {e}")
            raise ProviderError(f"Failed to get device: {e}")

    def list_alerts(
        self,
        device_id: Optional[str] = None,
        status: Optional[str] = None,
        updated_since: Optional[datetime] = None,
        page_size: int = 100
    ) -> List[Dict[str, Any]]:
        """
        List alerts.

        Args:
            device_id: Filter by agent ID
            status: Filter by status (not fully supported)
            updated_since: Only return alerts updated after this time
            page_size: Number of alerts per page

        Returns:
            List of normalized alert dictionaries
        """
        alerts = []

        try:
            # Get alerts from alerts endpoint
            response = self._make_request('GET', '/alerts/')
            data = self._safe_json(response)

            if not isinstance(data, list):
                logger.error(f"Unexpected response format from Tactical RMM alerts: {type(data)}")
                return alerts

            for alert_data in data:
                try:
                    # Filter by device_id if specified
                    if device_id and str(alert_data.get('agent')) != str(device_id):
                        continue

                    # Filter by status if specified
                    if status:
                        alert_status = 'active' if not alert_data.get('resolved') else 'resolved'
                        if status != alert_status:
                            continue

                    alerts.append(self.normalize_alert(alert_data))
                except Exception as e:
                    logger.error(f"Error normalizing Tactical RMM alert {alert_data.get('id')}: {e}")

            logger.info(f"Tactical RMM: Retrieved {len(alerts)} alerts")
            return alerts

        except Exception as e:
            logger.error(f"Error listing Tactical RMM alerts: {e}")
            raise ProviderError(f"Failed to list alerts: {e}")

    def list_software(self, device_id: str) -> List[Dict[str, Any]]:
        """
        List software installed on an agent.

        Args:
            device_id: Tactical RMM agent ID

        Returns:
            List of normalized software dictionaries
        """
        software_list = []

        try:
            response = self._make_request('GET', f'/software/{device_id}/')
            data = self._safe_json(response)

            if not isinstance(data, list):
                logger.error(f"Unexpected response format from Tactical RMM software: {type(data)}")
                return software_list

            for sw_data in data:
                try:
                    software_list.append(self.normalize_software(sw_data))
                except Exception as e:
                    logger.error(f"Error normalizing Tactical RMM software: {e}")

            logger.debug(f"Tactical RMM: Retrieved {len(software_list)} software items for agent {device_id}")
            return software_list

        except Exception as e:
            logger.error(f"Error listing Tactical RMM software for agent {device_id}: {e}")
            # Don't raise - software listing is optional
            return software_list

    def normalize_device(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize Tactical RMM agent data to standard format.

        Tactical RMM agent structure:
        {
            "agent_id": "abc-123-def-456",
            "hostname": "DESKTOP-ABC123",
            "client_name": "Acme Corp",
            "site_name": "Main Office",
            "monitoring_type": "workstation",
            "plat": "windows",
            "plat_release": "10",
            "operating_system": "Windows 10 Pro",
            "public_ip": "1.2.3.4",
            "local_ips": ["192.168.1.100"],
            "make_model": "Dell Inc. OptiPlex 7090",
            "serial_number": "ABC12345",
            "online": true,
            "last_seen": "2026-01-11T02:00:00Z"
        }
        """
        # Map monitoring type to device type
        monitoring_type = raw_data.get('monitoring_type', 'workstation')
        device_type = self.AGENT_TYPE_MAP.get(monitoring_type, 'workstation')

        # Parse make/model
        make_model = raw_data.get('make_model', '')
        manufacturer = ''
        model = ''
        if make_model:
            parts = make_model.split(' ', 1)
            manufacturer = parts[0] if len(parts) > 0 else ''
            model = parts[1] if len(parts) > 1 else ''

        # Get IP address
        local_ips = raw_data.get('local_ips', [])
        ip_address = local_ips[0] if local_ips else raw_data.get('public_ip')

        # Parse OS type
        plat = raw_data.get('plat', '').lower()
        os_type = self._map_os_type_from_plat(plat)

        # Parse last seen timestamp
        last_seen = self._parse_datetime(raw_data.get('last_seen'))

        # Site/Client information for organization mapping
        # Try to get site ID and name
        site_id = str(raw_data.get('site', '')) if raw_data.get('site') else ''
        site_name = raw_data.get('site_name', '')

        # If we have a name but no ID, use name as ID (for organization mapping)
        if site_name and not site_id:
            from django.utils.text import slugify
            site_id = slugify(site_name)

        # Try to get client ID and name
        client_id = str(raw_data.get('client', '')) if raw_data.get('client') else ''
        client_name = raw_data.get('client_name', '')

        # If we have a name but no ID, use name as ID (for organization mapping)
        if client_name and not client_id:
            from django.utils.text import slugify
            client_id = slugify(client_name)

        # Parse location data if available
        # Check for location in various possible fields
        location_data = raw_data.get('location') or raw_data.get('gps_location') or raw_data.get('coordinates')
        latitude, longitude = self._parse_location(location_data)

        return {
            'external_id': str(raw_data['agent_id']),
            'device_name': raw_data.get('hostname', ''),
            'device_type': device_type,
            'manufacturer': manufacturer,
            'model': model,
            'serial_number': raw_data.get('serial_number', ''),
            'os_type': os_type,
            'os_version': raw_data.get('operating_system', ''),
            'hostname': raw_data.get('hostname', ''),
            'ip_address': ip_address,
            'mac_address': '',  # Tactical RMM doesn't expose MAC in main agent data
            'latitude': latitude,
            'longitude': longitude,
            'is_online': raw_data.get('online', False),
            'last_seen': last_seen,
            # Site/Client information for organization mapping
            'site_name': site_name,
            'site_id': site_id,
            'client_name': client_name,
            'client_id': client_id,
            'raw_data': raw_data,
        }

    def normalize_alert(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize Tactical RMM alert data to standard format.

        Tactical RMM alert structure:
        {
            "id": 123,
            "agent": "abc-123-def-456",
            "alert_type": "diskspace",
            "message": "Disk C: is 90% full",
            "severity": "warning",
            "resolved": false,
            "email_sent": true,
            "sms_sent": false,
            "created": "2026-01-11T01:00:00Z"
        }
        """
        # Map Tactical RMM severity to standard levels
        severity_map = {
            'info': 'info',
            'warning': 'warning',
            'error': 'error',
            'critical': 'critical',
        }

        tactical_severity = raw_data.get('severity', 'info').lower()
        severity = severity_map.get(tactical_severity, 'info')

        # Map status
        status = 'active' if not raw_data.get('resolved', False) else 'resolved'

        # Parse timestamps
        triggered_at = self._parse_datetime(raw_data.get('created'))
        resolved_at = self._parse_datetime(raw_data.get('resolved_on')) if status == 'resolved' else None

        return {
            'external_id': str(raw_data.get('id', '')),
            'device_id': str(raw_data.get('agent', '')),
            'alert_type': raw_data.get('alert_type', ''),
            'message': raw_data.get('message', ''),
            'severity': severity,
            'status': status,
            'triggered_at': triggered_at,
            'resolved_at': resolved_at,
            'raw_data': raw_data,
        }

    def normalize_software(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize Tactical RMM software data to standard format.

        Tactical RMM software structure:
        {
            "name": "Google Chrome",
            "version": "120.0.6099.71",
            "publisher": "Google LLC",
            "install_date": "2025-12-15"
        }
        """
        install_date = self._parse_datetime(raw_data.get('install_date'))

        return {
            'external_id': '',  # Tactical RMM doesn't provide unique software IDs
            'name': raw_data.get('name', ''),
            'version': raw_data.get('version', ''),
            'vendor': raw_data.get('publisher', ''),
            'install_date': install_date,
            'raw_data': raw_data,
        }

    def _map_os_type_from_plat(self, plat: str) -> str:
        """
        Map Tactical RMM platform to standard OS type.

        Args:
            plat: Platform from Tactical RMM (windows, linux, darwin)

        Returns:
            Standard OS type (windows, macos, linux, etc.)
        """
        plat_lower = plat.lower()

        if 'windows' in plat_lower:
            return 'windows'
        elif 'darwin' in plat_lower or 'mac' in plat_lower:
            return 'macos'
        elif 'linux' in plat_lower:
            return 'linux'
        else:
            return 'other'
