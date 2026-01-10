"""
Kaseya BMS Provider
Implements integration with Kaseya BMS (Business Management Solution) API.
"""
import logging
from typing import List, Dict, Optional
from datetime import datetime
from .base import BaseProvider, ProviderError, AuthenticationError

logger = logging.getLogger('integrations')


class KaseyaBMSProvider(BaseProvider):
    """
    Kaseya BMS provider.
    Requires credentials: api_key, server_url
    API Documentation: https://help.kaseya.com/
    """
    provider_name = "Kaseya BMS"
    supports_companies = True
    supports_contacts = True
    supports_tickets = True
    supports_projects = True
    supports_agreements = True

    def _get_auth_headers(self):
        """Kaseya BMS uses API key in headers."""
        api_key = self.credentials.get('api_key', '')

        if not api_key:
            raise AuthenticationError("Missing Kaseya BMS API key")

        return {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

    def test_connection(self) -> bool:
        """Test connection by fetching account info."""
        try:
            response = self._make_request('GET', '/api/v1/account')
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Kaseya BMS connection test failed: {e}")
            return False

    def list_companies(self, page_size=100, updated_since=None) -> List[Dict]:
        """List companies from Kaseya BMS."""
        companies = []
        page = 1

        while True:
            params = {
                'page': page,
                'pageSize': min(page_size, 100),
            }

            if updated_since:
                params['updatedSince'] = updated_since.isoformat()

            try:
                response = self._make_request('GET', '/api/v1/companies', params=params)
                data = response.json()

                company_list = data.get('data', [])
                if not company_list:
                    break

                for raw_company in company_list:
                    companies.append(self.normalize_company(raw_company))

                # Check if there are more pages
                if len(company_list) < params['pageSize']:
                    break

                page += 1

            except Exception as e:
                logger.error(f"Error fetching Kaseya BMS companies page {page}: {e}")
                break

        return companies

    def get_company(self, company_id: str) -> Dict:
        """Get single company from Kaseya BMS."""
        try:
            response = self._make_request('GET', f'/api/v1/companies/{company_id}')
            data = response.json()
            return self.normalize_company(data.get('data', {}))
        except Exception as e:
            logger.error(f"Error fetching Kaseya BMS company {company_id}: {e}")
            raise ProviderError(f"Failed to fetch company: {e}")

    def list_contacts(self, company_id: Optional[str] = None, page_size=100, updated_since=None) -> List[Dict]:
        """List contacts from Kaseya BMS."""
        contacts = []
        page = 1

        while True:
            params = {
                'page': page,
                'pageSize': min(page_size, 100),
            }

            if company_id:
                params['companyId'] = company_id

            if updated_since:
                params['updatedSince'] = updated_since.isoformat()

            try:
                response = self._make_request('GET', '/api/v1/contacts', params=params)
                data = response.json()

                contact_list = data.get('data', [])
                if not contact_list:
                    break

                for raw_contact in contact_list:
                    contacts.append(self.normalize_contact(raw_contact))

                if len(contact_list) < params['pageSize']:
                    break

                page += 1

            except Exception as e:
                logger.error(f"Error fetching Kaseya BMS contacts page {page}: {e}")
                break

        return contacts

    def list_tickets(self, company_id: Optional[str] = None, status: Optional[str] = None,
                     updated_since: Optional[datetime] = None, page_size=100) -> List[Dict]:
        """List tickets from Kaseya BMS."""
        tickets = []
        page = 1

        while True:
            params = {
                'page': page,
                'pageSize': min(page_size, 100),
            }

            if company_id:
                params['companyId'] = company_id

            if status:
                params['status'] = status

            if updated_since:
                params['updatedSince'] = updated_since.isoformat()

            try:
                response = self._make_request('GET', '/api/v1/tickets', params=params)
                data = response.json()

                ticket_list = data.get('data', [])
                if not ticket_list:
                    break

                for raw_ticket in ticket_list:
                    tickets.append(self.normalize_ticket(raw_ticket))

                if len(ticket_list) < params['pageSize']:
                    break

                page += 1

            except Exception as e:
                logger.error(f"Error fetching Kaseya BMS tickets page {page}: {e}")
                break

        return tickets

    def get_ticket(self, ticket_id: str) -> Dict:
        """Get single ticket from Kaseya BMS."""
        try:
            response = self._make_request('GET', f'/api/v1/tickets/{ticket_id}')
            data = response.json()
            return self.normalize_ticket(data.get('data', {}))
        except Exception as e:
            logger.error(f"Error fetching Kaseya BMS ticket {ticket_id}: {e}")
            raise ProviderError(f"Failed to fetch ticket: {e}")

    def _normalize_status(self, status_str: str) -> str:
        """Convert Kaseya BMS status to common status."""
        status_map = {
            'new': 'open',
            'open': 'open',
            'in_progress': 'in_progress',
            'on_hold': 'waiting',
            'resolved': 'resolved',
            'closed': 'closed',
        }
        return status_map.get(status_str.lower().replace(' ', '_'), 'open')

    def _normalize_priority(self, priority_str: str) -> str:
        """Convert Kaseya BMS priority to common priority."""
        priority_map = {
            'low': 'low',
            'medium': 'medium',
            'normal': 'medium',
            'high': 'high',
            'critical': 'critical',
            'urgent': 'critical',
        }
        return priority_map.get(priority_str.lower(), 'medium')

    def normalize_company(self, raw_data: Dict) -> Dict:
        """Normalize Kaseya BMS company data to common format."""
        return {
            'external_id': str(raw_data.get('id', '')),
            'name': raw_data.get('name'),
            'phone': raw_data.get('phone'),
            'email': raw_data.get('email'),
            'address': raw_data.get('address'),
            'city': raw_data.get('city'),
            'state': raw_data.get('state'),
            'zip': raw_data.get('zipCode'),
            'country': raw_data.get('country'),
            'website': raw_data.get('website'),
            'notes': raw_data.get('notes'),
            'created_at': raw_data.get('createdAt'),
            'updated_at': raw_data.get('updatedAt'),
            'custom_fields': {
                'account_number': raw_data.get('accountNumber'),
                'status': raw_data.get('status'),
                'type': raw_data.get('type'),
            }
        }

    def normalize_contact(self, raw_data: Dict) -> Dict:
        """Normalize Kaseya BMS contact data to common format."""
        return {
            'external_id': str(raw_data.get('id', '')),
            'company_id': str(raw_data.get('companyId', '')),
            'first_name': raw_data.get('firstName'),
            'last_name': raw_data.get('lastName'),
            'email': raw_data.get('email'),
            'phone': raw_data.get('phone'),
            'mobile': raw_data.get('mobilePhone'),
            'title': raw_data.get('title'),
            'notes': raw_data.get('notes'),
            'created_at': raw_data.get('createdAt'),
            'updated_at': raw_data.get('updatedAt'),
            'custom_fields': {
                'department': raw_data.get('department'),
                'isPrimary': raw_data.get('isPrimary'),
            }
        }

    def normalize_ticket(self, raw_data: Dict) -> Dict:
        """Normalize Kaseya BMS ticket data to common format."""
        return {
            'external_id': str(raw_data.get('id', '')),
            'company_id': str(raw_data.get('companyId', '')),
            'number': raw_data.get('ticketNumber'),
            'subject': raw_data.get('subject'),
            'description': raw_data.get('description'),
            'status': self._normalize_status(raw_data.get('status', 'new')),
            'priority': self._normalize_priority(raw_data.get('priority', 'medium')),
            'created_at': raw_data.get('createdAt'),
            'updated_at': raw_data.get('updatedAt'),
            'resolved_at': raw_data.get('resolvedAt'),
            'due_date': raw_data.get('dueDate'),
            'assignee_name': raw_data.get('assignedTo', {}).get('name') if raw_data.get('assignedTo') else None,
            'custom_fields': {
                'category': raw_data.get('category'),
                'subcategory': raw_data.get('subcategory'),
                'source': raw_data.get('source'),
                'contactId': raw_data.get('contactId'),
            }
        }
