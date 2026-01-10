"""
ConnectWise Manage PSA Provider
Implements full integration with ConnectWise Manage API.
"""
import base64
import logging
from typing import List, Dict, Optional
from datetime import datetime
from .base import BaseProvider, ProviderError, AuthenticationError

logger = logging.getLogger('integrations')


class ConnectWiseManageProvider(BaseProvider):
    """
    ConnectWise Manage provider.
    Requires credentials: company_id, public_key, private_key, client_id
    """
    provider_name = "ConnectWise Manage"
    supports_companies = True
    supports_contacts = True
    supports_tickets = True
    supports_projects = True
    supports_agreements = True

    def _get_auth_headers(self):
        """
        ConnectWise Manage uses Basic Auth with company_id+public_key:private_key
        Plus a clientId header.
        """
        company_id = self.credentials.get('company_id', '')
        public_key = self.credentials.get('public_key', '')
        private_key = self.credentials.get('private_key', '')
        client_id = self.credentials.get('client_id', 'itdocs')

        if not all([company_id, public_key, private_key]):
            raise AuthenticationError("Missing ConnectWise credentials")

        # Format: company_id+public_key:private_key
        auth_string = f"{company_id}+{public_key}:{private_key}"
        auth_bytes = auth_string.encode('utf-8')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')

        return {
            'Authorization': f'Basic {auth_b64}',
            'clientId': client_id,
            'Content-Type': 'application/json',
        }

    def test_connection(self) -> bool:
        """
        Test connection by fetching company info endpoint.
        """
        try:
            response = self._make_request('GET', '/v4_6_release/apis/3.0/company/info')
            return response.status_code == 200
        except Exception as e:
            logger.error(f"ConnectWise connection test failed: {e}")
            return False

    def list_companies(self, page_size=100, updated_since=None) -> List[Dict]:
        """
        List companies from ConnectWise Manage.
        """
        companies = []
        page = 1
        conditions = ""

        if updated_since:
            # CW uses lastUpdated field
            date_str = updated_since.strftime('%Y-%m-%dT%H:%M:%SZ')
            conditions = f"lastUpdated>[{date_str}]"

        while True:
            params = {
                'pageSize': page_size,
                'page': page,
            }
            if conditions:
                params['conditions'] = conditions

            try:
                response = self._make_request('GET', '/v4_6_release/apis/3.0/company/companies', params=params)
                batch = response.json()

                if not batch:
                    break

                for raw_company in batch:
                    companies.append(self.normalize_company(raw_company))

                # If we got less than page_size, we're done
                if len(batch) < page_size:
                    break

                page += 1

            except Exception as e:
                logger.error(f"Error fetching ConnectWise companies page {page}: {e}")
                break

        return companies

    def get_company(self, company_id: str) -> Dict:
        """
        Get single company by ID.
        """
        try:
            response = self._make_request('GET', f'/v4_6_release/apis/3.0/company/companies/{company_id}')
            return self.normalize_company(response.json())
        except Exception as e:
            logger.error(f"Error fetching ConnectWise company {company_id}: {e}")
            raise ProviderError(f"Failed to fetch company: {e}")

    def list_contacts(self, company_id: Optional[str] = None, page_size=100, updated_since=None) -> List[Dict]:
        """
        List contacts from ConnectWise Manage.
        """
        contacts = []
        page = 1
        conditions = ""

        if company_id:
            conditions = f"company/id={company_id}"

        if updated_since:
            date_str = updated_since.strftime('%Y-%m-%dT%H:%M:%SZ')
            if conditions:
                conditions += f" and lastUpdated>[{date_str}]"
            else:
                conditions = f"lastUpdated>[{date_str}]"

        while True:
            params = {
                'pageSize': page_size,
                'page': page,
            }
            if conditions:
                params['conditions'] = conditions

            try:
                response = self._make_request('GET', '/v4_6_release/apis/3.0/company/contacts', params=params)
                batch = response.json()

                if not batch:
                    break

                for raw_contact in batch:
                    contacts.append(self.normalize_contact(raw_contact))

                if len(batch) < page_size:
                    break

                page += 1

            except Exception as e:
                logger.error(f"Error fetching ConnectWise contacts page {page}: {e}")
                break

        return contacts

    def list_tickets(self, company_id: Optional[str] = None, status: Optional[str] = None,
                     updated_since: Optional[datetime] = None, page_size=100) -> List[Dict]:
        """
        List service tickets from ConnectWise Manage.
        """
        tickets = []
        page = 1
        conditions_parts = []

        if company_id:
            conditions_parts.append(f"company/id={company_id}")

        if status:
            # CW has complex status board/status relationships, simplified here
            conditions_parts.append(f"status/name='{status}'")

        if updated_since:
            date_str = updated_since.strftime('%Y-%m-%dT%H:%M:%SZ')
            conditions_parts.append(f"lastUpdated>[{date_str}]")

        conditions = " and ".join(conditions_parts) if conditions_parts else ""

        while True:
            params = {
                'pageSize': page_size,
                'page': page,
            }
            if conditions:
                params['conditions'] = conditions

            try:
                response = self._make_request('GET', '/v4_6_release/apis/3.0/service/tickets', params=params)
                batch = response.json()

                if not batch:
                    break

                for raw_ticket in batch:
                    tickets.append(self.normalize_ticket(raw_ticket))

                if len(batch) < page_size:
                    break

                page += 1

            except Exception as e:
                logger.error(f"Error fetching ConnectWise tickets page {page}: {e}")
                break

        return tickets

    def get_ticket(self, ticket_id: str) -> Dict:
        """
        Get single ticket by ID.
        """
        try:
            response = self._make_request('GET', f'/v4_6_release/apis/3.0/service/tickets/{ticket_id}')
            return self.normalize_ticket(response.json())
        except Exception as e:
            logger.error(f"Error fetching ConnectWise ticket {ticket_id}: {e}")
            raise ProviderError(f"Failed to fetch ticket: {e}")

    def normalize_company(self, raw_data: Dict) -> Dict:
        """
        Normalize ConnectWise company to standard format.
        """
        return {
            'external_id': str(raw_data.get('id', '')),
            'name': raw_data.get('name', ''),
            'phone': raw_data.get('phoneNumber', ''),
            'website': raw_data.get('website', ''),
            'address': self._format_address(raw_data),
            'raw_data': raw_data,
        }

    def normalize_contact(self, raw_data: Dict) -> Dict:
        """
        Normalize ConnectWise contact to standard format.
        """
        company_id = None
        if 'company' in raw_data and raw_data['company']:
            company_id = str(raw_data['company'].get('id', ''))

        return {
            'external_id': str(raw_data.get('id', '')),
            'company_id': company_id,
            'first_name': raw_data.get('firstName', ''),
            'last_name': raw_data.get('lastName', ''),
            'email': raw_data.get('defaultEmail', '') or raw_data.get('communicationItems', [{}])[0].get('value', ''),
            'phone': raw_data.get('defaultPhone', ''),
            'title': raw_data.get('title', ''),
            'raw_data': raw_data,
        }

    def normalize_ticket(self, raw_data: Dict) -> Dict:
        """
        Normalize ConnectWise ticket to standard format.
        """
        company_id = None
        if 'company' in raw_data and raw_data['company']:
            company_id = str(raw_data['company'].get('id', ''))

        contact_id = None
        if 'contact' in raw_data and raw_data['contact']:
            contact_id = str(raw_data['contact'].get('id', ''))

        # Map CW status to generic status
        status_map = {
            'New': 'new',
            'In Progress': 'in_progress',
            'Waiting': 'waiting',
            'Resolved': 'resolved',
            'Closed': 'closed',
        }
        status_name = raw_data.get('status', {}).get('name', 'new')
        status = status_map.get(status_name, 'new')

        # Map priority
        priority_name = raw_data.get('priority', {}).get('name', 'Medium').lower()
        priority = priority_name if priority_name in ['low', 'medium', 'high', 'urgent'] else 'medium'

        return {
            'external_id': str(raw_data.get('id', '')),
            'company_id': company_id,
            'contact_id': contact_id,
            'ticket_number': str(raw_data.get('id', '')),
            'subject': raw_data.get('summary', ''),
            'description': raw_data.get('initialDescription', ''),
            'status': status,
            'priority': priority,
            'created_at': self._parse_datetime(raw_data.get('dateEntered')),
            'updated_at': self._parse_datetime(raw_data.get('lastUpdated')),
            'raw_data': raw_data,
        }

    def _format_address(self, company_data: Dict) -> str:
        """Format company address from CW format."""
        parts = []
        if company_data.get('addressLine1'):
            parts.append(company_data['addressLine1'])
        if company_data.get('addressLine2'):
            parts.append(company_data['addressLine2'])
        if company_data.get('city'):
            parts.append(company_data['city'])
        if company_data.get('state'):
            parts.append(company_data['state'])
        if company_data.get('zip'):
            parts.append(company_data['zip'])
        return ', '.join(parts)

    def _parse_datetime(self, date_string: Optional[str]) -> Optional[datetime]:
        """Parse ConnectWise datetime string."""
        if not date_string:
            return None
        try:
            # CW format: 2023-01-15T10:30:00Z
            return datetime.strptime(date_string, '%Y-%m-%dT%H:%M:%SZ')
        except Exception:
            return None
