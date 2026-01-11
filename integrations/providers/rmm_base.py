"""
Base provider class for RMM integrations.
All RMM providers must implement this interface.
"""
import logging
from typing import List, Dict, Optional
from datetime import datetime
from .base import BaseProvider, ProviderError, AuthenticationError, RateLimitError

logger = logging.getLogger('integrations')


class BaseRMMProvider(BaseProvider):
    """
    Base RMM provider class extending BaseProvider.
    All RMM providers must inherit from this and implement the RMM-specific methods.
    """

    # Provider capabilities (override in subclasses)
    supports_devices = True
    supports_alerts = True
    supports_software = False
    supports_network_config = False
    supports_monitoring = True

    # RMM providers don't need PSA-specific methods
    supports_companies = False
    supports_contacts = False
    supports_tickets = False

    # Required methods for all RMM providers

    def list_devices(self, page_size=100, updated_since=None) -> List[Dict]:
        """
        List devices/assets from RMM.

        Args:
            page_size: Maximum number of devices to return per page (default 100)
            updated_since: Optional datetime - only return devices updated after this time

        Returns:
            List of normalized device dicts with keys:
                - external_id: str
                - device_name: str
                - device_type: str (workstation, server, laptop, network, mobile, virtual, unknown)
                - manufacturer: str
                - model: str
                - serial_number: str
                - os_type: str (windows, linux, macos, ios, android, other)
                - os_version: str
                - hostname: str
                - ip_address: str
                - mac_address: str
                - is_online: bool
                - last_seen: datetime
                - raw_data: dict

        Raises:
            ProviderError: On API errors
            AuthenticationError: On auth failures
            RateLimitError: On rate limit exceeded
        """
        raise NotImplementedError("Subclass must implement list_devices()")

    def get_device(self, device_id: str) -> Dict:
        """
        Get single device by ID.

        Args:
            device_id: External device ID from RMM

        Returns:
            Normalized device dict (same format as list_devices)

        Raises:
            ProviderError: On API errors or device not found
        """
        raise NotImplementedError("Subclass must implement get_device()")

    def list_alerts(self, device_id=None, status=None, updated_since=None, page_size=100) -> List[Dict]:
        """
        List monitoring alerts.

        Args:
            device_id: Optional - filter alerts for specific device
            status: Optional - filter by status (active, resolved)
            updated_since: Optional datetime - only return alerts updated after this time
            page_size: Maximum number of alerts to return per page (default 100)

        Returns:
            List of normalized alert dicts with keys:
                - external_id: str
                - device_id: str (external device ID)
                - alert_type: str
                - message: str
                - severity: str (info, warning, error, critical)
                - status: str (active, acknowledged, resolved, closed)
                - triggered_at: datetime
                - resolved_at: datetime (optional)
                - raw_data: dict

        Raises:
            ProviderError: On API errors
        """
        raise NotImplementedError("Subclass must implement list_alerts()")

    def list_software(self, device_id: str) -> List[Dict]:
        """
        List software installed on device.

        Args:
            device_id: External device ID from RMM

        Returns:
            List of normalized software dicts with keys:
                - external_id: str (optional)
                - name: str
                - version: str
                - vendor: str
                - install_date: datetime (optional)
                - raw_data: dict

        Raises:
            ProviderError: On API errors
            NotImplementedError: If provider doesn't support software inventory
        """
        if not self.supports_software:
            raise NotImplementedError(f"{self.provider_name} does not support software inventory")
        raise NotImplementedError("Subclass must implement list_software()")

    # Normalization methods (must be implemented by subclasses)

    def normalize_device(self, raw_data: Dict) -> Dict:
        """
        Normalize device data from provider-specific format to standard format.

        Args:
            raw_data: Provider-specific device data

        Returns:
            Normalized device dict (see list_devices for format)
        """
        raise NotImplementedError("Subclass must implement normalize_device()")

    def normalize_alert(self, raw_data: Dict) -> Dict:
        """
        Normalize alert data from provider-specific format to standard format.

        Args:
            raw_data: Provider-specific alert data

        Returns:
            Normalized alert dict (see list_alerts for format)
        """
        raise NotImplementedError("Subclass must implement normalize_alert()")

    def normalize_software(self, raw_data: Dict) -> Dict:
        """
        Normalize software data from provider-specific format to standard format.

        Args:
            raw_data: Provider-specific software data

        Returns:
            Normalized software dict (see list_software for format)
        """
        raise NotImplementedError("Subclass must implement normalize_software()")

    # Helper methods

    def _parse_datetime(self, date_string: Optional[str]) -> Optional[datetime]:
        """
        Parse provider datetime string to Python datetime.
        Override in subclass if provider has non-standard format.

        Args:
            date_string: ISO 8601 datetime string or None

        Returns:
            datetime object or None
        """
        if not date_string:
            return None
        try:
            # Try ISO 8601 format with Z timezone
            return datetime.fromisoformat(date_string.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return None

    def _paginate(self, method, endpoint, params=None, page_param='page', page_size_param='pageSize',
                  per_page=100, max_pages=None):
        """
        Helper method for paginated API calls.
        Override in subclass if provider uses different pagination scheme.

        Args:
            method: HTTP method ('GET', 'POST', etc.)
            endpoint: API endpoint path
            params: Query parameters dict
            page_param: Name of page parameter (default 'page')
            page_size_param: Name of page size parameter (default 'pageSize')
            per_page: Number of items per page (default 100)
            max_pages: Maximum number of pages to fetch (default unlimited)

        Yields:
            Individual items from paginated responses
        """
        if params is None:
            params = {}

        page = 1
        while True:
            if max_pages and page > max_pages:
                break

            params[page_param] = page
            params[page_size_param] = per_page

            response = self._make_request(method, endpoint, params=params)
            data = response.json()

            # Handle different pagination response formats
            # Override this method if provider uses different structure
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                # Try common pagination keys
                items = data.get('results') or data.get('data') or data.get('items') or []
            else:
                items = []

            if not items:
                break

            for item in items:
                yield item

            # Stop if we got fewer items than requested (last page)
            if len(items) < per_page:
                break

            page += 1
