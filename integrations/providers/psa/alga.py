"""
Alga PSA provider integration (PLACEHOLDER)

Alga PSA is an open-source MSP PSA platform by Nine-Minds.
API documentation: To be completed when API is documented

Repository: https://github.com/Nine-Minds/alga-psa
Hosted: api.algapsa.com
"""
from ..psa_base import BasePSAProvider
from ..base import ProviderError, AuthenticationError
import requests
import logging

logger = logging.getLogger('integrations')


class AlgaPSAProvider(BasePSAProvider):
    """
    Alga PSA integration provider.

    NOTE: This is a PLACEHOLDER implementation. Alga PSA's REST API
    is not yet publicly documented. This will need to be completed
    once API documentation is available or by examining the codebase
    at server/src/pages/api in the Alga PSA repository.

    Required credentials:
        - base_url: Alga PSA instance URL (e.g., https://api.algapsa.com)
        - api_key: API authentication key (method TBD)
        OR
        - username: User email
        - password: User password (via NextAuth.js)
    """

    provider_name = 'Alga PSA'

    def __init__(self, connection):
        super().__init__(connection)
        self.base_url = connection.base_url.rstrip('/')
        self.session = requests.Session()

    def _get_auth_headers(self):
        """
        Get authentication headers.

        TODO: Implement actual Alga PSA authentication.
        Options:
        1. API Key in header (if they support this)
        2. NextAuth.js session token
        3. JWT bearer token
        """
        credentials = self.connection.get_credentials()

        # Placeholder - update once auth method is known
        api_key = credentials.get('api_key', '')
        if api_key:
            return {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            }

        raise AuthenticationError("No API key configured for Alga PSA")

    def test_connection(self):
        """
        Test API connectivity.

        TODO: Implement with actual Alga PSA health check endpoint
        Possible endpoints:
        - GET /api/health
        - GET /api/status
        - GET /api/user (to verify auth)
        """
        try:
            headers = self._get_auth_headers()
            # Placeholder endpoint - update with actual health check
            response = self.session.get(
                f'{self.base_url}/api/health',
                headers=headers,
                timeout=10
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Alga PSA connection test failed: {e}")
            return False

    def list_companies(self, updated_since=None):
        """
        List all companies/clients.

        TODO: Implement with actual Alga PSA endpoint
        Expected endpoint: GET /api/companies or /api/clients

        Args:
            updated_since: datetime to filter by last update

        Returns:
            list of normalized company dicts
        """
        companies = []
        headers = self._get_auth_headers()

        # TODO: Replace with actual endpoint
        try:
            response = self.session.get(
                f'{self.base_url}/api/companies',
                headers=headers,
                timeout=30
            )
            response.raise_for_status()

            data = response.json()

            # TODO: Update based on actual response structure
            for company_data in data:
                companies.append(self.normalize_company(company_data))

        except Exception as e:
            logger.error(f"Error fetching Alga PSA companies: {e}")
            raise ProviderError(f"Failed to fetch companies: {e}")

        return companies

    def get_company(self, company_id):
        """
        Get single company details.

        TODO: Implement with actual Alga PSA endpoint
        Expected: GET /api/companies/{id}
        """
        headers = self._get_auth_headers()

        try:
            response = self.session.get(
                f'{self.base_url}/api/companies/{company_id}',
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            return self.normalize_company(response.json())
        except Exception as e:
            logger.error(f"Error fetching Alga PSA company {company_id}: {e}")
            raise ProviderError(f"Failed to fetch company: {e}")

    def list_contacts(self, company_id=None, updated_since=None):
        """
        List contacts.

        TODO: Implement with actual Alga PSA endpoint
        Expected: GET /api/contacts or /api/companies/{id}/contacts
        """
        contacts = []
        headers = self._get_auth_headers()

        # Placeholder implementation
        url = f'{self.base_url}/api/contacts'
        if company_id:
            url = f'{self.base_url}/api/companies/{company_id}/contacts'

        try:
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            data = response.json()
            for contact_data in data:
                contacts.append(self.normalize_contact(contact_data))

        except Exception as e:
            logger.error(f"Error fetching Alga PSA contacts: {e}")
            raise ProviderError(f"Failed to fetch contacts: {e}")

        return contacts

    def list_tickets(self, company_id=None, status=None, updated_since=None):
        """
        List tickets.

        TODO: Implement with actual Alga PSA endpoint
        Expected: GET /api/tickets
        """
        tickets = []
        headers = self._get_auth_headers()

        params = {}
        if company_id:
            params['company_id'] = company_id
        if status:
            params['status'] = status

        try:
            response = self.session.get(
                f'{self.base_url}/api/tickets',
                headers=headers,
                params=params,
                timeout=30
            )
            response.raise_for_status()

            data = response.json()
            for ticket_data in data:
                tickets.append(self.normalize_ticket(ticket_data))

        except Exception as e:
            logger.error(f"Error fetching Alga PSA tickets: {e}")
            raise ProviderError(f"Failed to fetch tickets: {e}")

        return tickets

    def normalize_company(self, raw_data):
        """
        Normalize Alga PSA company to standard format.

        TODO: Update based on actual Alga PSA company data structure

        Expected fields from Alga PSA (to be confirmed):
        - id: company ID
        - name: company name
        - status: active/inactive
        - phone: phone number
        - address: full address or address object
        - website: company website
        """
        return {
            'external_id': str(raw_data.get('id', '')),
            'name': raw_data.get('name', ''),
            'status': raw_data.get('status', 'active'),
            'phone': raw_data.get('phone', ''),
            'address': self._format_address(raw_data.get('address', {})),
            'website': raw_data.get('website', ''),
            'raw_data': raw_data,
        }

    def normalize_contact(self, raw_data):
        """
        Normalize Alga PSA contact to standard format.

        TODO: Update based on actual Alga PSA contact structure
        """
        return {
            'external_id': str(raw_data.get('id', '')),
            'company_id': str(raw_data.get('company_id', '')),
            'first_name': raw_data.get('first_name', ''),
            'last_name': raw_data.get('last_name', ''),
            'email': raw_data.get('email', ''),
            'phone': raw_data.get('phone', ''),
            'title': raw_data.get('title', ''),
            'is_primary': raw_data.get('is_primary', False),
            'raw_data': raw_data,
        }

    def normalize_ticket(self, raw_data):
        """
        Normalize Alga PSA ticket to standard format.

        TODO: Update based on actual Alga PSA ticket structure
        """
        # Map Alga status to standard status
        status_map = {
            'open': 'open',
            'in_progress': 'in_progress',
            'pending': 'waiting',
            'resolved': 'resolved',
            'closed': 'closed',
        }

        alga_status = raw_data.get('status', 'open').lower()
        standard_status = status_map.get(alga_status, 'open')

        return {
            'external_id': str(raw_data.get('id', '')),
            'company_id': str(raw_data.get('company_id', '')),
            'contact_id': str(raw_data.get('contact_id', '')),
            'title': raw_data.get('title', ''),
            'description': raw_data.get('description', ''),
            'status': standard_status,
            'priority': raw_data.get('priority', 'medium'),
            'assigned_to': raw_data.get('assigned_to', ''),
            'created_at': self._parse_datetime(raw_data.get('created_at')),
            'updated_at': self._parse_datetime(raw_data.get('updated_at')),
            'raw_data': raw_data,
        }

    def _format_address(self, address_data):
        """Format address from Alga PSA data structure."""
        if isinstance(address_data, str):
            return address_data

        # TODO: Update based on actual Alga address structure
        parts = [
            address_data.get('street', ''),
            address_data.get('city', ''),
            address_data.get('state', ''),
            address_data.get('postal_code', ''),
            address_data.get('country', ''),
        ]

        return ', '.join(filter(None, parts))


# TODO: Remove this comment block once implementation is complete
"""
IMPLEMENTATION CHECKLIST:

1. Obtain Alga PSA API Documentation
   - Contact Nine-Minds team for API docs
   - OR examine server/src/pages/api directory in their repo
   - Document authentication method
   - Document endpoint paths and parameters

2. Update Authentication
   - Implement actual auth in _get_auth_headers()
   - May need to handle NextAuth.js flow
   - Store tokens in encrypted_credentials

3. Update All Endpoints
   - Replace placeholder URLs with actual endpoints
   - Update response parsing based on real structure
   - Handle pagination if needed
   - Implement error handling for Alga-specific errors

4. Test Connection
   - Implement proper health check in test_connection()
   - Test with real Alga PSA instance

5. Add to Provider Registry
   - Update integrations/providers/psa/__init__.py
   - Add 'alga_psa' to PSA_PROVIDERS dict

6. Update Forms
   - Add Alga PSA credentials fields to PSAConnectionForm
   - Update templates with Alga-specific help text

7. Create Migration
   - Add 'alga_psa' to PSAConnection.PROVIDER_TYPES

8. Documentation
   - Add setup guide to INTEGRATIONS.md
   - Document required credentials
   - Add example configuration
"""
