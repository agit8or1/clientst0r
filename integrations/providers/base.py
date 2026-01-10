"""
Base provider class for PSA integrations.
All providers must implement this interface.
"""
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger('integrations')


class ProviderError(Exception):
    """Base exception for provider errors."""
    pass


class AuthenticationError(ProviderError):
    """Authentication failed."""
    pass


class RateLimitError(ProviderError):
    """Rate limit exceeded."""
    pass


class BaseProvider:
    """
    Base provider class with common HTTP client and interface.
    All PSA providers must inherit from this and implement the abstract methods.
    """

    # Provider metadata
    provider_name = "Base Provider"
    supports_companies = True
    supports_contacts = True
    supports_tickets = True
    supports_projects = False
    supports_agreements = False
    supports_webhooks = False

    def __init__(self, connection):
        """
        Initialize provider with PSAConnection.
        """
        self.connection = connection
        self.base_url = connection.base_url.rstrip('/')

        # Security: Validate base_url to prevent SSRF
        self._validate_base_url(self.base_url)

        self.credentials = connection.get_credentials()
        self.session = self._create_session()

    def _validate_base_url(self, url):
        """
        Validate base URL to prevent SSRF attacks.
        Raises ProviderError if URL is invalid or unsafe.
        """
        from urllib.parse import urlparse
        import socket
        import ipaddress

        try:
            parsed = urlparse(url)

            # Only allow http/https schemes
            if parsed.scheme not in ['http', 'https']:
                raise ProviderError(f"Invalid URL scheme: {parsed.scheme}. Only http/https allowed.")

            # Require hostname
            if not parsed.hostname:
                raise ProviderError("Invalid URL: no hostname specified")

            # Try to resolve hostname to IP
            try:
                ip_str = socket.gethostbyname(parsed.hostname)
                ip = ipaddress.ip_address(ip_str)

                # Block private IP ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
                if ip.is_private:
                    raise ProviderError(f"Cannot connect to private IP addresses: {ip_str}")

                # Block loopback addresses (127.0.0.0/8)
                if ip.is_loopback:
                    raise ProviderError(f"Cannot connect to loopback addresses: {ip_str}")

                # Block link-local addresses (169.254.0.0/16)
                if ip.is_link_local:
                    raise ProviderError(f"Cannot connect to link-local addresses: {ip_str}")

            except socket.gaierror:
                # Hostname doesn't resolve - this is OK, will fail naturally on connection
                pass

        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"URL validation error: {str(e)}")

    def _create_session(self):
        """
        Create requests session with retry logic and timeouts.
        """
        session = requests.Session()

        # Retry strategy: 3 retries with exponential backoff
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    def _make_request(self, method, endpoint, **kwargs):
        """
        Make HTTP request with error handling and logging.
        Subclasses should call this for all API requests.
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        # Set default timeout if not provided
        kwargs.setdefault('timeout', 30)

        # Add authentication headers (implemented by subclass)
        headers = kwargs.pop('headers', {})
        headers.update(self._get_auth_headers())
        kwargs['headers'] = headers

        try:
            logger.debug(f"{method.upper()} {url}")
            response = self.session.request(method, url, **kwargs)

            # Check for rate limiting
            if response.status_code == 429:
                logger.warning(f"Rate limit hit for {self.provider_name}")
                raise RateLimitError("Rate limit exceeded")

            # Check for auth errors
            if response.status_code == 401:
                logger.error(f"Authentication failed for {self.provider_name}")
                raise AuthenticationError("Authentication failed")

            # Raise for other HTTP errors
            response.raise_for_status()

            return response

        except requests.exceptions.Timeout:
            logger.error(f"Timeout connecting to {self.provider_name}")
            raise ProviderError(f"Request timeout")

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error to {self.provider_name}: {e}")
            raise ProviderError(f"Connection failed: {e}")

        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error from {self.provider_name}: {e}")
            raise ProviderError(f"HTTP error: {e}")

    def _get_auth_headers(self):
        """
        Get authentication headers for requests.
        Must be implemented by subclass.
        """
        raise NotImplementedError("Subclass must implement _get_auth_headers()")

    def _paginate(self, endpoint, params=None, page_size=100):
        """
        Generic pagination helper. Override if provider uses different pagination.
        This is a simple example - subclasses should implement based on their API.
        """
        raise NotImplementedError("Subclass must implement _paginate() if using pagination")

    # Required methods - must be implemented by all providers

    def test_connection(self) -> bool:
        """
        Test connection to PSA. Returns True if successful.
        """
        raise NotImplementedError("Subclass must implement test_connection()")

    def list_companies(self, page_size=100, updated_since=None) -> List[Dict]:
        """
        List companies/clients.
        Returns list of normalized company dicts.
        """
        raise NotImplementedError("Subclass must implement list_companies()")

    def get_company(self, company_id: str) -> Dict:
        """
        Get single company by ID.
        Returns normalized company dict.
        """
        raise NotImplementedError("Subclass must implement get_company()")

    def list_contacts(self, company_id: Optional[str] = None, page_size=100, updated_since=None) -> List[Dict]:
        """
        List contacts, optionally filtered by company.
        Returns list of normalized contact dicts.
        """
        raise NotImplementedError("Subclass must implement list_contacts()")

    def list_tickets(self, company_id: Optional[str] = None, status: Optional[str] = None,
                     updated_since: Optional[datetime] = None, page_size=100) -> List[Dict]:
        """
        List tickets/service requests.
        Returns list of normalized ticket dicts.
        """
        raise NotImplementedError("Subclass must implement list_tickets()")

    def get_ticket(self, ticket_id: str) -> Dict:
        """
        Get single ticket by ID.
        Returns normalized ticket dict.
        """
        raise NotImplementedError("Subclass must implement get_ticket()")

    # Optional methods - implement if provider supports them

    def list_projects(self, company_id: Optional[str] = None) -> List[Dict]:
        """
        List projects.
        """
        if not self.supports_projects:
            raise NotImplementedError(f"{self.provider_name} does not support projects")
        raise NotImplementedError("Subclass must implement list_projects()")

    def list_agreements(self, company_id: Optional[str] = None) -> List[Dict]:
        """
        List agreements/contracts.
        """
        if not self.supports_agreements:
            raise NotImplementedError(f"{self.provider_name} does not support agreements")
        raise NotImplementedError("Subclass must implement list_agreements()")

    def search(self, query: str, entity_types: List[str] = None) -> Dict[str, List[Dict]]:
        """
        Generic search across entity types.
        Returns dict with keys for each entity type containing list of results.
        """
        raise NotImplementedError("Subclass must implement search()")

    # Normalization helpers

    def normalize_company(self, raw_data: Dict) -> Dict:
        """
        Normalize company data to standard format.
        Must be implemented by subclass.
        """
        raise NotImplementedError("Subclass must implement normalize_company()")

    def normalize_contact(self, raw_data: Dict) -> Dict:
        """
        Normalize contact data to standard format.
        """
        raise NotImplementedError("Subclass must implement normalize_contact()")

    def normalize_ticket(self, raw_data: Dict) -> Dict:
        """
        Normalize ticket data to standard format.
        """
        raise NotImplementedError("Subclass must implement normalize_ticket()")
