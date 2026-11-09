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
        self._client_ids, self._site_ids = self._client_site_ids()

        try:
            # Tactical RMM returns all agents in single response
            response = self._make_request('GET', '/agents/')
            data = self._safe_json(response)

            if not isinstance(data, list):
                logger.error(f"Unexpected response format from Tactical RMM: {type(data)}")
                return devices

            for agent_data in data:
                try:
                    # If any hardware or network fields are absent/null in the list response,
                    # fetch full agent detail — some TRMM deployments only populate hardware
                    # and MAC address on the per-agent endpoint, not the bulk list.
                    _has_mac = (agent_data.get('MACAddress') or agent_data.get('mac_address') or
                                agent_data.get('mac') or
                                any(m for m in (agent_data.get('mac_addresses') or []) if m) or
                                any(i.get('mac') or i.get('physicalAddress') or i.get('macAddress')
                                    for i in (agent_data.get('nics') or agent_data.get('interfaces') or [])))
                    if not agent_data.get('total_ram') or not agent_data.get('disks') or not _has_mac:
                        agent_id = agent_data.get('agent_id') or agent_data.get('id')
                        if agent_id:
                            try:
                                detail_resp = self._make_request('GET', f'/agents/{agent_id}/')
                                detail = self._safe_json(detail_resp)
                                if isinstance(detail, dict):
                                    # Merge: detail fills in missing fields but must not
                                    # overwrite non-empty values from the list response
                                    # (detail sometimes returns null for fields the list had)
                                    merged = dict(agent_data)
                                    for k, v in detail.items():
                                        if v is not None and v != [] and v != '':
                                            merged[k] = v
                                    agent_data = merged
                            except Exception as detail_err:
                                logger.debug(f"TRMM: could not fetch detail for agent {agent_id}: {detail_err}")
                    devices.append(self.normalize_device(agent_data))
                except Exception as e:
                    logger.error(f"Error normalizing Tactical RMM agent {agent_data.get('agent_id')}: {e}")

            logger.info(f"Tactical RMM: Retrieved {len(devices)} agents")
            return devices

        except Exception as e:
            logger.error(f"Error listing Tactical RMM agents: {e}")
            raise ProviderError(f"Failed to list devices: {e}")

    def _client_site_ids(self):
        """Real client and site IDs from one GET /clients/ per sync.

        The agent list carries only `client_name` and `site_name`. Tactical
        RMM keeps client names unique and site names unique within a client,
        so the (client, site) name pair maps to exactly one pair of IDs.
        """
        clients, sites = {}, {}
        try:
            data = self._safe_json(self._make_request('GET', '/clients/'))
        except Exception as e:
            logger.warning(f"Tactical RMM: client list unavailable, using names: {e}")
            return clients, sites
        for client in data if isinstance(data, list) else []:
            cname = str(client.get('name') or '').casefold()
            if client.get('id') is None or not cname:
                continue
            clients[cname] = str(client['id'])
            for site in client.get('sites') or []:
                sname = str(site.get('name') or '').casefold()
                if site.get('id') is not None and sname:
                    sites[(cname, sname)] = str(site['id'])
        return clients, sites

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
            # /alerts/ lists with PATCH (GET is not allowed); an empty filter
            # body returns every alert that isn't hidden.
            response = self._make_request('PATCH', '/alerts/', json={})
            data = self._safe_json(response)

            if not isinstance(data, list):
                logger.error(f"Unexpected response format from Tactical RMM alerts: {type(data)}")
                return alerts

            for alert_data in data:
                try:
                    # Filter by device_id if specified
                    if device_id and str(alert_data.get('agent_id')) != str(device_id):
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

    def list_software(self, device_id: str, uuid: str = '') -> List[Dict[str, Any]]:
        """
        List software installed on an agent.

        Tries multiple endpoint paths to handle different TRMM versions:
        - /software/{numeric_pk}/ — primary path, requires numeric PK
        - /agents/{device_id}/software/ — alternative path
        - /agents/{uuid}/software/ — UUID-based fallback

        Args:
            device_id: Tactical RMM numeric agent PK (preferred) or UUID
            uuid: Agent UUID (agent_id field) for fallback path

        Returns:
            List of normalized software dictionaries
        """
        # Build ordered list of paths to try
        paths_to_try = [f'/software/{device_id}/']
        if device_id != uuid:
            paths_to_try.append(f'/agents/{device_id}/software/')
        if uuid and uuid != device_id:
            paths_to_try.append(f'/agents/{uuid}/software/')

        last_error = None
        for path in paths_to_try:
            try:
                response = self._make_request('GET', path)
                if response.status_code == 404:
                    logger.debug(f"Tactical RMM: 404 at {path}, trying next")
                    continue
                data = self._safe_json(response)

                # Some paths return {"software": [...]} wrapper
                if isinstance(data, dict):
                    data = data.get('software') or data.get('installed_software') or []

                if not isinstance(data, list):
                    logger.debug(f"Tactical RMM: unexpected format at {path}: {type(data)}")
                    continue

                software_list = []
                for sw_data in data:
                    try:
                        software_list.append(self.normalize_software(sw_data))
                    except Exception as e:
                        logger.error(f"Error normalizing Tactical RMM software: {e}")

                logger.info(f"Tactical RMM: Retrieved {len(software_list)} software items via {path}")
                return software_list

            except Exception as e:
                last_error = e
                logger.debug(f"Tactical RMM: error at {path}: {e}")
                continue

        logger.error(
            f"Tactical RMM: could not fetch software for agent {device_id} "
            f"(tried {paths_to_try}); last error: {last_error}"
        )
        return []

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

        # Get IP address — prefer private/local IP; fall back to public IP
        # Also scan all known NIC/adapter structures for IP and MAC data.
        #
        # TRMM wmi_detail.network_adapter is a LIST OF LISTS:
        #   [[{MACAddress, PhysicalAdapter, ...}], [{...}], ...]
        # Each outer element is a single-item list wrapping one adapter dict.
        # network_config has the same structure with IPEnabled instead of PhysicalAdapter.
        wmi = raw_data.get('wmi_detail') or {}

        def _flatten_wmi_list(key):
            """Flatten TRMM's list-of-lists wmi_detail structure into a flat list of dicts."""
            raw = wmi.get(key) or []
            flat = []
            for item in raw:
                if isinstance(item, list):
                    flat.extend(d for d in item if isinstance(d, dict))
                elif isinstance(item, dict):
                    flat.append(item)
            return flat

        wmi_adapters = _flatten_wmi_list('network_adapter')
        wmi_configs  = _flatten_wmi_list('network_config')
        nics = raw_data.get('nics') or raw_data.get('interfaces') or []

        # MAC extraction — priority order:
        # 1. Top-level MACAddress (primary physical adapter, set by TRMM agent)
        # 2. mac_addresses list (skip empty strings)
        # 3. wmi_detail physical adapters (PhysicalAdapter == True)
        # 4. wmi_detail active network configs (IPEnabled == True)
        # 5. Any wmi adapter with a MAC
        # 6. nics/interfaces loop
        _mac_list = [m for m in (raw_data.get('mac_addresses') or []) if m]
        mac_address = (
            raw_data.get('MACAddress') or raw_data.get('mac_address') or raw_data.get('mac') or
            (_mac_list[0] if _mac_list else '') or
            next((a['MACAddress'] for a in wmi_adapters
                  if a.get('PhysicalAdapter') and a.get('MACAddress')), '') or
            next((a['MACAddress'] for a in wmi_configs
                  if a.get('IPEnabled') and a.get('MACAddress')), '') or
            next((a['MACAddress'] for a in wmi_adapters if a.get('MACAddress')), '') or
            next((a['MACAddress'] for a in wmi_configs  if a.get('MACAddress')), '') or
            ''
        )

        nic_ips = []
        for nic in nics + wmi_adapters + wmi_configs:
            if not mac_address:
                mac_address = (nic.get('mac_address') or nic.get('mac') or
                               nic.get('macAddress') or nic.get('physicalAddress') or
                               nic.get('MACAddress') or '')
            nic_ip_list = nic.get('ip_addresses') or nic.get('ips') or nic.get('ipAddresses') or []
            if isinstance(nic_ip_list, list):
                # Filter out link-local (169.254.x.x) and loopback addresses
                for ip in nic_ip_list:
                    s = str(ip).strip()
                    if s and not s.startswith('169.254') and not s.startswith('127.'):
                        nic_ips.append(s)
            elif isinstance(nic_ip_list, str) and nic_ip_list:
                nic_ips.append(nic_ip_list)

        raw_local_ips = raw_data.get('local_ips') or nic_ips or []
        # Normalise to a list — TRMM sometimes returns a comma-separated string
        if isinstance(raw_local_ips, str):
            local_ips = [ip.strip() for ip in raw_local_ips.replace(';', ',').split(',') if ip.strip()]
        elif isinstance(raw_local_ips, list):
            local_ips = [str(ip).strip() for ip in raw_local_ips if str(ip).strip()]
        else:
            local_ips = []
        # Filter out link-local and loopback
        local_ips = [ip for ip in local_ips
                     if not ip.startswith('169.254') and not ip.startswith('127.')]

        if local_ips:
            ip_address = local_ips[0]
        else:
            # Try every plausible single-value field name before falling back to public IP
            ip_address = (raw_data.get('local_ip') or raw_data.get('lan_ip') or
                          raw_data.get('agent_ip') or raw_data.get('private_ip') or
                          raw_data.get('ip') or raw_data.get('public_ip') or '')

        # Parse OS type
        plat = raw_data.get('plat', '').lower()
        os_type = self._map_os_type_from_plat(plat)

        # Parse last seen timestamp
        last_seen = self._parse_datetime(raw_data.get('last_seen'))

        # Site/Client information for organization mapping.
        # Tactical RMM API variants:
        #   Newer:  { "client_name": "Acme", "site_name": "Main Office" }
        #   Older:  { "client": "Acme",      "site": "Main Office" }   ← name IS the value
        from django.utils.text import slugify

        raw_client = str(raw_data.get('client', '')) if raw_data.get('client') else ''
        raw_site   = str(raw_data.get('site',   '')) if raw_data.get('site')   else ''
        client_name = raw_data.get('client_name', '')
        site_name   = raw_data.get('site_name',   '')

        # When the API returns only 'client'/'site' (the name string), use it as name too
        if raw_client and not client_name:
            client_name = raw_client
        if raw_site and not site_name:
            site_name = raw_site

        # Real IDs from /clients/. Without them the identity is the client
        # name, marked as such (client_id stays empty), so a rename shows up
        # as a change for review rather than a new customer. Earlier versions
        # used name slugs as IDs; `legacy_client_ids` lets those mappings
        # carry over.
        client_id = getattr(self, '_client_ids', {}).get(client_name.casefold(), '') if client_name else ''
        site_id = (getattr(self, '_site_ids', {}).get((client_name.casefold(), site_name.casefold()), '')
                   if client_name and site_name else '')
        legacy_client_ids = [slugify(client_name)] if client_name else []

        # Parse location data if available
        # Check for location in various possible fields
        location_data = raw_data.get('location') or raw_data.get('gps_location') or raw_data.get('coordinates')
        latitude, longitude = self._parse_location(location_data)

        # Hardware specs
        # cpu_model in TRMM is a list of CPU strings; join them for display
        cpu_raw = raw_data.get('cpu_model') or raw_data.get('cpu') or ''
        if isinstance(cpu_raw, list):
            cpu = ', '.join(str(c) for c in cpu_raw if c)
        else:
            cpu = str(cpu_raw) if cpu_raw else ''

        # total_ram in Tactical RMM is stored in GB (integer), not MB
        ram_gb = None
        total_ram_val = raw_data.get('total_ram') or 0
        if total_ram_val:
            try:
                ram_gb = round(float(total_ram_val), 1)
            except (ValueError, TypeError):
                pass

        # Disk summary: "C: 200GB (75% used), D: 500GB"
        # TRMM disk fields: device (not dev), total/used/free in GB (float), percent
        storage = ''
        disks = raw_data.get('disks') or []
        if disks:
            parts = []
            for disk in disks:
                dev = disk.get('device') or disk.get('dev', '?')
                total_raw = disk.get('total_gb') or disk.get('total') or 0
                used_raw = disk.get('used_gb') or disk.get('used') or 0
                percent = disk.get('percent')
                # total/used may be pre-formatted strings like "3.7 TB" — parse numeric prefix
                try:
                    total = float(str(total_raw).split()[0])
                    used = float(str(used_raw).split()[0])
                    total_unit = str(total_raw).split()[1] if len(str(total_raw).split()) > 1 else 'GB'
                except (ValueError, TypeError, IndexError):
                    total = 0
                    used = 0
                    total_unit = 'GB'
                if total:
                    if percent is not None:
                        pct = round(float(percent))
                    else:
                        pct = round(used / total * 100) if total else 0
                    parts.append(f"{dev} {total:.1f} {total_unit} ({pct}% used)")
            storage = ', '.join(parts)

        # Agent notes/description
        agent_notes = raw_data.get('notes') or raw_data.get('description') or ''

        return {
            'external_id': str(raw_data.get('agent_id') or ''),
            'device_name': raw_data.get('hostname', ''),
            'device_type': device_type,
            'manufacturer': manufacturer,
            'model': model,
            'serial_number': raw_data.get('serial_number', ''),
            'os_type': os_type,
            'os_version': raw_data.get('operating_system', ''),
            'hostname': raw_data.get('hostname', ''),
            'ip_address': ip_address,
            'mac_address': mac_address,
            'latitude': latitude,
            'longitude': longitude,
            'is_online': bool(raw_data.get('online')) or raw_data.get('status') == 'online',
            'last_seen': last_seen,
            # Hardware specs from TRMM
            'cpu': cpu,
            'ram_gb': ram_gb,
            'storage': storage,
            'agent_notes': agent_notes,
            # Site/Client information for organization mapping
            'site_name': site_name,
            'site_id': site_id,
            'client_name': client_name,
            'client_id': client_id,
            'legacy_client_ids': legacy_client_ids,
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
        triggered_at = self._parse_datetime(raw_data.get('alert_time') or raw_data.get('created'))
        resolved_at = self._parse_datetime(raw_data.get('resolved_on')) if status == 'resolved' else None

        # `agent` is the agent's database key; `agent_id` is the string ID
        # devices are stored under. Alerts on checks without an agent have
        # neither and are skipped.
        return {
            'external_id': str(raw_data.get('id') if raw_data.get('id') is not None else ''),
            'device_id': str(raw_data.get('agent_id') or ''),
            'alert_type': raw_data.get('alert_type', ''),
            'message': raw_data.get('message', ''),
            'severity': severity,
            'status': status,
            'triggered_at': triggered_at,
            'resolved_at': resolved_at,
            'raw_data': raw_data,
        }

    # The web app routes agents at /agents/<agent_id> (tacticalrmm-web,
    # src/router/routes.ts). Its host is not the API host, so links are
    # offered only when the connection has its web console URL configured.
    console_link_mode = 'static'

    @classmethod
    def console_hosts(cls, connection):
        from .console import host_of
        host = host_of(getattr(connection, 'console_base_url', '') or '')
        return {host} if host else set()

    @classmethod
    def device_console_url(cls, connection, device):
        from urllib.parse import quote
        base = (getattr(connection, 'console_base_url', '') or '').rstrip('/')
        if not base or not device.external_id:
            return ''
        return f"{base}/agents/{quote(device.external_id, safe='')}"

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
