"""
Alga PSA provider integration

Alga PSA is an open-source MSP PSA platform by Nine-Minds.
API documentation: https://github.com/Nine-Minds/alga-psa/tree/release/0.16.0/sdk/docs/openapi

Repository: https://github.com/Nine-Minds/alga-psa
Default hosted: https://algapsa.com
"""
from ..base import BaseProvider, ProviderError, AuthenticationError
import requests
import logging
import json
from typing import List, Dict, Any, Optional

logger = logging.getLogger('integrations')


class AlgaPSAProvider(BaseProvider):
    """
    Alga PSA integration provider.

    Alga PSA uses API key authentication with tenant-based multi-tenancy.
    Based on OpenAPI spec v0.1.0 and SDK samples from release/0.16.0.

    Required credentials:
        - api_key: API authentication key (from Alga PSA settings)
        - tenant_id: Tenant/organization UUID (from Alga PSA instance)

    Base URL: https://algapsa.com (production) or self-hosted instance URL

    Authentication:
        - Header: x-api-key
        - Header: x-tenant-id (required for all API calls)
    """

    provider_name = 'Alga PSA'

    def __init__(self, connection):
        super().__init__(connection)
        self.base_url = connection.base_url.rstrip('/')
        self.session = requests.Session()

    def _get_auth_headers(self) -> Dict[str, str]:
        """
        Get authentication headers for Alga PSA API.

        Returns headers with x-api-key and x-tenant-id.
        """
        credentials = self.connection.get_credentials()

        api_key = credentials.get('api_key', '')
        tenant_id = credentials.get('tenant_id', '')

        if not api_key:
            raise AuthenticationError("API key not configured for Alga PSA")

        if not tenant_id:
            raise AuthenticationError("Tenant ID not configured for Alga PSA")

        return {
            'x-api-key': api_key,
            'x-tenant-id': tenant_id,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'Client St0r/2.24 (PSA Integration Client)',
        }

    def _safe_json(self, response):
        """
        Safely parse JSON response with better error handling.
        Handles Alga PSA error format: {error: {code, message, details}}
        """
        # Check if response has content
        if not response.content:
            raise ProviderError(
                f"Empty response from Alga PSA API (Status: {response.status_code}, "
                f"URL: {response.url}). The API endpoint may not exist or returned no data. "
                f"Please verify your Alga PSA base URL and tenant ID are correct."
            )

        # Try to parse JSON
        try:
            data = response.json()

            # Check for Alga PSA error format
            if isinstance(data, dict) and 'error' in data:
                error_info = data['error']
                error_message = error_info.get('message', 'Unknown error')
                error_code = error_info.get('code', 'unknown')
                error_details = error_info.get('details', {})

                raise ProviderError(
                    f"Alga PSA API error ({error_code}): {error_message}. "
                    f"Details: {error_details}"
                )

            return data

        except json.JSONDecodeError as e:
            # Log the actual response content for debugging
            content_preview = response.text[:500] if response.text else "(empty)"
            logger.error(
                f"Invalid JSON from Alga PSA API. "
                f"Status: {response.status_code}, "
                f"URL: {response.url}, "
                f"Content preview: {content_preview}"
            )
            raise ProviderError(
                f"Invalid JSON response from Alga PSA API (Status: {response.status_code}). "
                f"Please verify:\n"
                f"1. Your Alga PSA base URL is correct (e.g., https://algapsa.com)\n"
                f"2. Your API key and tenant ID have the correct permissions\n"
                f"3. The API endpoint exists on your Alga PSA version\n"
                f"Response preview: {content_preview}"
            )

    def test_connection(self) -> bool:
        """
        Test API connectivity by fetching clients with limit=1.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            headers = self._get_auth_headers()
            # Test with clients endpoint (limit 1 for speed)
            response = self.session.get(
                f'{self.base_url}/api/v1/clients',
                headers=headers,
                params={'limit': 1},
                timeout=10
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Alga PSA connection test failed: {e}")
            return False

    def list_companies(self, updated_since: Optional[Any] = None) -> List[Dict[str, Any]]:
        """
        List all companies/clients from Alga PSA.

        Endpoint: GET /api/v1/clients
        Response format: {data: [{client_id, client_name, ...}], pagination: {...}}
        Supports pagination via page/limit query parameters.

        Args:
            updated_since: datetime to filter by last update (not currently supported by Alga PSA)

        Returns:
            list of normalized company dicts
        """
        companies = []
        headers = self._get_auth_headers()
        page = 1
        page_size = 100

        try:
            while True:
                # Alga PSA uses /api/v1/clients endpoint with pagination
                response = self.session.get(
                    f'{self.base_url}/api/v1/clients',
                    headers=headers,
                    params={'page': page, 'limit': page_size},
                    timeout=30
                )
                response.raise_for_status()

                result = self._safe_json(response)

                # Alga PSA wraps data in {data: [...], pagination: {...}} format
                client_list = result.get('data', [])
                if not isinstance(client_list, list):
                    logger.warning(f"Unexpected response format from Alga PSA clients endpoint: {type(client_list)}")
                    break

                if not client_list:
                    break  # No more data

                for client_data in client_list:
                    try:
                        companies.append(self.normalize_company(client_data))
                    except Exception as e:
                        logger.error(f"Error normalizing Alga PSA client {client_data.get('client_id')}: {e}")

                # Check pagination info
                pagination = result.get('pagination', {})
                has_next = pagination.get('hasNext', False)

                if not has_next:
                    break

                page += 1

            logger.info(f"Alga PSA: Retrieved {len(companies)} clients")

        except Exception as e:
            logger.error(f"Error fetching Alga PSA clients: {e}")
            raise ProviderError(f"Failed to fetch companies: {e}")

        return companies

    def get_company(self, company_id: str) -> Dict[str, Any]:
        """
        Get single company/client details.

        Endpoint: GET /api/v1/clients/{id}

        Args:
            company_id: Client UUID

        Returns:
            Normalized company dict
        """
        headers = self._get_auth_headers()

        try:
            response = self.session.get(
                f'{self.base_url}/api/v1/clients/{company_id}',
                headers=headers,
                timeout=10
            )
            response.raise_for_status()

            result = self._safe_json(response)
            client_data = result.get('data', result)  # Handle both wrapped and unwrapped responses

            return self.normalize_company(client_data)
        except Exception as e:
            logger.error(f"Error fetching Alga PSA client {company_id}: {e}")
            raise ProviderError(f"Failed to fetch company: {e}")

    def list_contacts(self, company_id: Optional[str] = None, updated_since: Optional[Any] = None) -> List[Dict[str, Any]]:
        """
        List contacts from Alga PSA.

        Endpoints:
        - GET /api/v1/contacts (all contacts)
        - GET /api/v1/clients/{id}/contacts (contacts for specific client)

        Supports pagination via page/limit query parameters.

        Args:
            company_id: Optional client UUID to filter contacts
            updated_since: datetime to filter by last update (not currently supported)

        Returns:
            list of normalized contact dicts
        """
        contacts = []
        headers = self._get_auth_headers()
        page = 1
        page_size = 100

        # Use client-specific endpoint if company_id provided
        if company_id:
            url = f'{self.base_url}/api/v1/clients/{company_id}/contacts'
        else:
            url = f'{self.base_url}/api/v1/contacts'

        try:
            while True:
                response = self.session.get(
                    url,
                    headers=headers,
                    params={'page': page, 'limit': page_size},
                    timeout=30
                )
                response.raise_for_status()

                result = self._safe_json(response)
                contact_list = result.get('data', [])

                if not isinstance(contact_list, list):
                    logger.warning(f"Unexpected response format from Alga PSA contacts endpoint: {type(contact_list)}")
                    break

                if not contact_list:
                    break

                for contact_data in contact_list:
                    try:
                        contacts.append(self.normalize_contact(contact_data))
                    except Exception as e:
                        logger.error(f"Error normalizing Alga PSA contact {contact_data.get('contact_id')}: {e}")

                # Check pagination
                pagination = result.get('pagination', {})
                has_next = pagination.get('hasNext', False)

                if not has_next:
                    break

                page += 1

            logger.info(f"Alga PSA: Retrieved {len(contacts)} contacts")

        except Exception as e:
            logger.error(f"Error fetching Alga PSA contacts: {e}")
            raise ProviderError(f"Failed to fetch contacts: {e}")

        return contacts

    def list_tickets(self, company_id: Optional[str] = None, status: Optional[str] = None, updated_since: Optional[Any] = None) -> List[Dict[str, Any]]:
        """
        List tickets from Alga PSA.

        Endpoint: GET /api/v1/tickets
        Can filter by company_id and status using query parameters.
        Supports pagination via page/limit query parameters.

        Args:
            company_id: Optional client UUID to filter tickets
            status: Optional status filter
            updated_since: datetime to filter by last update (not currently supported)

        Returns:
            list of normalized ticket dicts
        """
        tickets = []
        headers = self._get_auth_headers()
        page = 1
        page_size = 100

        params = {'page': page, 'limit': page_size}
        if company_id:
            params['company_id'] = company_id
        if status:
            params['status'] = status

        try:
            while True:
                params['page'] = page
                response = self.session.get(
                    f'{self.base_url}/api/v1/tickets',
                    headers=headers,
                    params=params,
                    timeout=30
                )
                response.raise_for_status()

                result = self._safe_json(response)
                ticket_list = result.get('data', [])

                if not isinstance(ticket_list, list):
                    logger.warning(f"Unexpected response format from Alga PSA tickets endpoint: {type(ticket_list)}")
                    break

                if not ticket_list:
                    break

                for ticket_data in ticket_list:
                    try:
                        tickets.append(self.normalize_ticket(ticket_data))
                    except Exception as e:
                        logger.error(f"Error normalizing Alga PSA ticket {ticket_data.get('ticket_id')}: {e}")

                # Check pagination
                pagination = result.get('pagination', {})
                has_next = pagination.get('hasNext', False)

                if not has_next:
                    break

                page += 1

            logger.info(f"Alga PSA: Retrieved {len(tickets)} tickets")

        except Exception as e:
            logger.error(f"Error fetching Alga PSA tickets: {e}")
            raise ProviderError(f"Failed to fetch tickets: {e}")

        return tickets

    def normalize_company(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize Alga PSA client to standard company format.

        Alga PSA client structure:
        {
            "client_id": "uuid",
            "client_name": "Company Name",
            "phone_no": "+1 555 0100",
            "email": "hello@example.com",
            "url": "https://example.com",
            "billing_cycle": "monthly",
            "tenant": "uuid",
            "client_type": "...",
            "account_manager_id": "uuid",
            "notes": "...",
            "tags": ["..."],
            "created_at": "2026-01-19T...",
            "updated_at": "2026-01-19T..."
        }

        Returns standard company dict format
        """
        # Alga PSA stores website in 'url' field
        website = raw_data.get('url', '')

        # Determine status - Alga PSA may have is_active or status field
        status = 'active' if raw_data.get('is_active', True) else 'inactive'
        if 'status' in raw_data:
            status = raw_data['status']

        return {
            'external_id': str(raw_data.get('client_id', '')),
            'name': raw_data.get('client_name', ''),
            'status': status,
            'phone': raw_data.get('phone_no', ''),
            'address': raw_data.get('address', ''),  # Alga PSA may store address differently
            'website': website,
            'raw_data': raw_data,
        }

    def normalize_contact(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize Alga PSA contact to standard format.

        Alga PSA likely uses:
        - contact_id (UUID)
        - company_id/client_id (UUID)
        - first_name, last_name
        - email, phone_number/phone
        - role/title
        - is_primary
        """
        # Alga PSA may use either 'company_id' or 'client_id' for the parent company
        company_id = raw_data.get('company_id') or raw_data.get('client_id', '')

        return {
            'external_id': str(raw_data.get('contact_id', raw_data.get('id', ''))),
            'company_id': str(company_id),
            'first_name': raw_data.get('first_name', ''),
            'last_name': raw_data.get('last_name', ''),
            'email': raw_data.get('email', ''),
            'phone': raw_data.get('phone', raw_data.get('phone_number', '')),
            'title': raw_data.get('title', raw_data.get('role', '')),
            'is_primary': raw_data.get('is_primary', False),
            'raw_data': raw_data,
        }

    def normalize_ticket(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize Alga PSA ticket to standard format.

        Alga PSA likely uses:
        - ticket_id (UUID)
        - company_id/client_id (UUID)
        - contact_id (UUID)
        - title, description
        - status, priority
        - assigned_to (user_id)
        - created_at, updated_at
        """
        # Map Alga status to standard status
        status_map = {
            'new': 'open',
            'open': 'open',
            'in_progress': 'in_progress',
            'in progress': 'in_progress',
            'pending': 'waiting',
            'resolved': 'resolved',
            'closed': 'closed',
            'cancelled': 'closed',
        }

        alga_status = raw_data.get('status', 'open').lower()
        standard_status = status_map.get(alga_status, 'open')

        # Alga PSA may use 'subject' instead of 'title'
        title = raw_data.get('title', raw_data.get('subject', ''))

        # Company ID might be 'company_id' or 'client_id'
        company_id = raw_data.get('company_id', raw_data.get('client_id', ''))

        return {
            'external_id': str(raw_data.get('ticket_id', raw_data.get('id', ''))),
            'ticket_number': str(raw_data.get('ticket_number', raw_data.get('number', ''))),
            'company_id': str(company_id),
            'contact_id': str(raw_data.get('contact_id', '')),
            'subject': title,
            'description': raw_data.get('description', ''),
            'status': standard_status,
            'priority': raw_data.get('priority', 'medium'),
            'created_at': self._parse_datetime(raw_data.get('created_at')),
            'updated_at': self._parse_datetime(raw_data.get('updated_at')),
            'raw_data': raw_data,
        }

    def _parse_datetime(self, date_string: Optional[str]) -> Optional[Any]:
        """
        Parse Alga PSA datetime string to Python datetime.

        Alga PSA uses ISO 8601 format (e.g., "2026-01-19T14:30:00Z" or "2026-01-19T14:30:00.123Z")

        Args:
            date_string: ISO 8601 datetime string or None

        Returns:
            datetime object or None
        """
        if not date_string:
            return None
        try:
            from datetime import datetime
            # Try ISO 8601 format with Z timezone
            return datetime.fromisoformat(date_string.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            logger.warning(f"Failed to parse Alga PSA datetime: {date_string}")
            return None
