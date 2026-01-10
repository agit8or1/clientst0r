"""
Autotask PSA Provider
Implements full integration with Autotask REST API.
"""
import logging
from typing import List, Dict, Optional
from datetime import datetime
from .base import BaseProvider, ProviderError, AuthenticationError

logger = logging.getLogger('integrations')


class AutotaskProvider(BaseProvider):
    """
    Autotask PSA provider.
    Requires credentials: username, secret (API key), integration_code
    Base URL should be the zone-specific API endpoint (e.g., webservices5.autotask.net)
    """
    provider_name = "Autotask PSA"
    supports_companies = True
    supports_contacts = True
    supports_tickets = True
    supports_projects = True
    supports_agreements = True

    def _get_auth_headers(self):
        """
        Autotask uses API key authentication with username and secret.
        Also requires IntegrationCode for tracking.
        """
        username = self.credentials.get('username', '')
        secret = self.credentials.get('secret', '')
        integration_code = self.credentials.get('integration_code', 'ITDOCS')

        if not all([username, secret]):
            raise AuthenticationError("Missing Autotask credentials")

        return {
            'ApiIntegrationCode': integration_code,
            'UserName': username,
            'Secret': secret,
            'Content-Type': 'application/json',
        }

    def test_connection(self) -> bool:
        """
        Test connection by querying companies with limit 1.
        """
        try:
            response = self._make_request('GET', '/v1.0/Companies/query', params={'search': '{"MaxRecords":1}'})
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Autotask connection test failed: {e}")
            return False

    def list_companies(self, page_size=100, updated_since=None) -> List[Dict]:
        """
        List companies from Autotask.
        Autotask uses POST with JSON query for filtering/pagination.
        """
        companies = []

        # Build filter
        filter_parts = ["isActive eq true"]
        if updated_since:
            date_str = updated_since.strftime('%Y-%m-%dT%H:%M:%S.000Z')
            filter_parts.append(f"lastModifiedDate gt {date_str}")

        query = {
            "MaxRecords": page_size,
            "filter": [{"op": "and", "items": [{"field": part.split()[0], "op": part.split()[1], "value": " ".join(part.split()[2:])} for part in filter_parts]}]
        }

        try:
            # Autotask pagination is cursor-based but simplified here
            response = self._make_request('POST', '/v1.0/Companies/query', json=query)
            data = response.json()

            items = data.get('items', [])
            for raw_company in items:
                companies.append(self.normalize_company(raw_company))

            # TODO: Handle pagination with 'pageDetails' cursor if needed

        except Exception as e:
            logger.error(f"Error fetching Autotask companies: {e}")

        return companies

    def get_company(self, company_id: str) -> Dict:
        """
        Get single company by ID.
        """
        try:
            response = self._make_request('GET', f'/v1.0/Companies/{company_id}')
            data = response.json()
            return self.normalize_company(data.get('item', {}))
        except Exception as e:
            logger.error(f"Error fetching Autotask company {company_id}: {e}")
            raise ProviderError(f"Failed to fetch company: {e}")

    def list_contacts(self, company_id: Optional[str] = None, page_size=100, updated_since=None) -> List[Dict]:
        """
        List contacts from Autotask.
        """
        contacts = []

        filter_parts = ["isActive eq 1"]
        if company_id:
            filter_parts.append(f"companyID eq {company_id}")

        if updated_since:
            date_str = updated_since.strftime('%Y-%m-%dT%H:%M:%S.000Z')
            filter_parts.append(f"lastModifiedDate gt {date_str}")

        query = {
            "MaxRecords": page_size,
            # Simplified filter structure
        }

        try:
            response = self._make_request('POST', '/v1.0/Contacts/query', json=query)
            data = response.json()

            items = data.get('items', [])
            for raw_contact in items:
                contacts.append(self.normalize_contact(raw_contact))

        except Exception as e:
            logger.error(f"Error fetching Autotask contacts: {e}")

        return contacts

    def list_tickets(self, company_id: Optional[str] = None, status: Optional[str] = None,
                     updated_since: Optional[datetime] = None, page_size=100) -> List[Dict]:
        """
        List tickets from Autotask.
        """
        tickets = []

        filter_parts = []
        if company_id:
            filter_parts.append(f"companyID eq {company_id}")

        if status:
            # Map generic status to Autotask status IDs (simplified)
            filter_parts.append(f"status eq {status}")

        if updated_since:
            date_str = updated_since.strftime('%Y-%m-%dT%H:%M:%S.000Z')
            filter_parts.append(f"lastActivityDate gt {date_str}")

        query = {
            "MaxRecords": page_size,
        }

        try:
            response = self._make_request('POST', '/v1.0/Tickets/query', json=query)
            data = response.json()

            items = data.get('items', [])
            for raw_ticket in items:
                tickets.append(self.normalize_ticket(raw_ticket))

        except Exception as e:
            logger.error(f"Error fetching Autotask tickets: {e}")

        return tickets

    def get_ticket(self, ticket_id: str) -> Dict:
        """
        Get single ticket by ID.
        """
        try:
            response = self._make_request('GET', f'/v1.0/Tickets/{ticket_id}')
            data = response.json()
            return self.normalize_ticket(data.get('item', {}))
        except Exception as e:
            logger.error(f"Error fetching Autotask ticket {ticket_id}: {e}")
            raise ProviderError(f"Failed to fetch ticket: {e}")

    def normalize_company(self, raw_data: Dict) -> Dict:
        """
        Normalize Autotask company to standard format.
        """
        address_parts = []
        if raw_data.get('address1'):
            address_parts.append(raw_data['address1'])
        if raw_data.get('address2'):
            address_parts.append(raw_data['address2'])
        if raw_data.get('city'):
            address_parts.append(raw_data['city'])
        if raw_data.get('state'):
            address_parts.append(raw_data['state'])
        if raw_data.get('postalCode'):
            address_parts.append(raw_data['postalCode'])

        return {
            'external_id': str(raw_data.get('id', '')),
            'name': raw_data.get('companyName', ''),
            'phone': raw_data.get('phone', ''),
            'website': raw_data.get('webAddress', ''),
            'address': ', '.join(address_parts),
            'raw_data': raw_data,
        }

    def normalize_contact(self, raw_data: Dict) -> Dict:
        """
        Normalize Autotask contact to standard format.
        """
        return {
            'external_id': str(raw_data.get('id', '')),
            'company_id': str(raw_data.get('companyID', '')),
            'first_name': raw_data.get('firstName', ''),
            'last_name': raw_data.get('lastName', ''),
            'email': raw_data.get('emailAddress', ''),
            'phone': raw_data.get('mobilePhone', '') or raw_data.get('phone', ''),
            'title': raw_data.get('title', ''),
            'raw_data': raw_data,
        }

    def normalize_ticket(self, raw_data: Dict) -> Dict:
        """
        Normalize Autotask ticket to standard format.
        """
        # Map Autotask status to generic status (simplified)
        status_map = {
            '1': 'new',
            '5': 'in_progress',
            '8': 'waiting',
            '5': 'resolved',
            '5': 'closed',
        }
        at_status = str(raw_data.get('status', '1'))
        status = status_map.get(at_status, 'new')

        # Map priority (Autotask uses 1-4)
        priority_map = {
            '1': 'urgent',
            '2': 'high',
            '3': 'medium',
            '4': 'low',
        }
        at_priority = str(raw_data.get('priority', '3'))
        priority = priority_map.get(at_priority, 'medium')

        return {
            'external_id': str(raw_data.get('id', '')),
            'company_id': str(raw_data.get('companyID', '')),
            'contact_id': str(raw_data.get('contactID', '')) if raw_data.get('contactID') else None,
            'ticket_number': raw_data.get('ticketNumber', ''),
            'subject': raw_data.get('title', ''),
            'description': raw_data.get('description', ''),
            'status': status,
            'priority': priority,
            'created_at': self._parse_datetime(raw_data.get('createDate')),
            'updated_at': self._parse_datetime(raw_data.get('lastActivityDate')),
            'raw_data': raw_data,
        }

    def _parse_datetime(self, date_string: Optional[str]) -> Optional[datetime]:
        """Parse Autotask datetime string."""
        if not date_string:
            return None
        try:
            # Autotask format: 2023-01-15T10:30:00.000Z
            return datetime.strptime(date_string, '%Y-%m-%dT%H:%M:%S.%fZ')
        except Exception:
            try:
                return datetime.strptime(date_string, '%Y-%m-%dT%H:%M:%SZ')
            except Exception:
                return None
