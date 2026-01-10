"""
Syncro Provider
Implements full integration with Syncro RMM & PSA API.
"""
import logging
from typing import List, Dict, Optional
from datetime import datetime
from .base import BaseProvider, ProviderError, AuthenticationError

logger = logging.getLogger('integrations')


class SyncroProvider(BaseProvider):
    """
    Syncro MSP platform provider.
    Requires credentials: api_key, subdomain
    API Documentation: https://api-docs.syncromsp.com/
    """
    provider_name = "Syncro"
    supports_companies = True
    supports_contacts = True
    supports_tickets = True
    supports_projects = False
    supports_agreements = False

    def _get_auth_headers(self):
        """Syncro uses API key in headers."""
        api_key = self.credentials.get('api_key', '')

        if not api_key:
            raise AuthenticationError("Missing Syncro API key")

        return {
            'Authorization': api_key,
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }

    def test_connection(self) -> bool:
        """Test connection by fetching current user info."""
        try:
            response = self._make_request('GET', '/api/v1/me')
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Syncro connection test failed: {e}")
            return False

    def list_companies(self, page_size=100, updated_since=None) -> List[Dict]:
        """List customers from Syncro."""
        companies = []
        page = 1

        while True:
            params = {
                'page': page,
                'per_page': min(page_size, 100),  # Syncro max 100 per page
            }

            try:
                response = self._make_request('GET', '/api/v1/customers', params=params)
                data = response.json()

                customers = data.get('customers', [])
                if not customers:
                    break

                for raw_customer in customers:
                    # Filter by updated_since if provided
                    if updated_since:
                        updated_at = raw_customer.get('updated_at')
                        if updated_at:
                            customer_updated = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                            if customer_updated < updated_since:
                                continue

                    companies.append(self.normalize_company(raw_customer))

                # Check if there are more pages
                meta = data.get('meta', {})
                if page >= meta.get('total_pages', 1):
                    break

                page += 1

            except Exception as e:
                logger.error(f"Error fetching Syncro customers page {page}: {e}")
                break

        return companies

    def get_company(self, company_id: str) -> Dict:
        """Get single customer from Syncro."""
        try:
            response = self._make_request('GET', f'/api/v1/customers/{company_id}')
            data = response.json()
            return self.normalize_company(data.get('customer', {}))
        except Exception as e:
            logger.error(f"Error fetching Syncro customer {company_id}: {e}")
            raise ProviderError(f"Failed to fetch customer: {e}")

    def list_contacts(self, company_id: Optional[str] = None, page_size=100, updated_since=None) -> List[Dict]:
        """List contacts from Syncro."""
        contacts = []
        page = 1

        while True:
            params = {
                'page': page,
                'per_page': min(page_size, 100),
            }

            if company_id:
                params['customer_id'] = company_id

            try:
                response = self._make_request('GET', '/api/v1/contacts', params=params)
                data = response.json()

                contact_list = data.get('contacts', [])
                if not contact_list:
                    break

                for raw_contact in contact_list:
                    contacts.append(self.normalize_contact(raw_contact))

                meta = data.get('meta', {})
                if page >= meta.get('total_pages', 1):
                    break

                page += 1

            except Exception as e:
                logger.error(f"Error fetching Syncro contacts page {page}: {e}")
                break

        return contacts

    def list_tickets(self, company_id: Optional[str] = None, status: Optional[str] = None,
                     updated_since: Optional[datetime] = None, page_size=100) -> List[Dict]:
        """List tickets from Syncro."""
        tickets = []
        page = 1

        while True:
            params = {
                'page': page,
                'per_page': min(page_size, 100),
            }

            if company_id:
                params['customer_id'] = company_id

            if status:
                params['status'] = status

            try:
                response = self._make_request('GET', '/api/v1/tickets', params=params)
                data = response.json()

                ticket_list = data.get('tickets', [])
                if not ticket_list:
                    break

                for raw_ticket in ticket_list:
                    # Filter by updated_since if provided
                    if updated_since:
                        updated_at = raw_ticket.get('updated_at')
                        if updated_at:
                            ticket_updated = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                            if ticket_updated < updated_since:
                                continue

                    tickets.append(self.normalize_ticket(raw_ticket))

                meta = data.get('meta', {})
                if page >= meta.get('total_pages', 1):
                    break

                page += 1

            except Exception as e:
                logger.error(f"Error fetching Syncro tickets page {page}: {e}")
                break

        return tickets

    def get_ticket(self, ticket_id: str) -> Dict:
        """Get single ticket from Syncro."""
        try:
            response = self._make_request('GET', f'/api/v1/tickets/{ticket_id}')
            data = response.json()
            return self.normalize_ticket(data.get('ticket', {}))
        except Exception as e:
            logger.error(f"Error fetching Syncro ticket {ticket_id}: {e}")
            raise ProviderError(f"Failed to fetch ticket: {e}")

    def normalize_company(self, raw_data: Dict) -> Dict:
        """Normalize Syncro customer data to common format."""
        return {
            'external_id': str(raw_data.get('id', '')),
            'name': raw_data.get('business_name') or raw_data.get('firstname', '') + ' ' + raw_data.get('lastname', ''),
            'phone': raw_data.get('phone'),
            'email': raw_data.get('email'),
            'address': raw_data.get('address'),
            'city': raw_data.get('city'),
            'state': raw_data.get('state'),
            'zip': raw_data.get('zip'),
            'country': 'US',  # Syncro is US-focused
            'website': raw_data.get('website'),
            'notes': raw_data.get('notes'),
            'created_at': raw_data.get('created_at'),
            'updated_at': raw_data.get('updated_at'),
            'custom_fields': {
                'business_and_full_name': raw_data.get('business_and_full_name'),
                'business_then_name': raw_data.get('business_then_name'),
            }
        }

    def normalize_contact(self, raw_data: Dict) -> Dict:
        """Normalize Syncro contact data to common format."""
        return {
            'external_id': str(raw_data.get('id', '')),
            'company_id': str(raw_data.get('customer_id', '')),
            'first_name': raw_data.get('name', '').split()[0] if raw_data.get('name') else '',
            'last_name': ' '.join(raw_data.get('name', '').split()[1:]) if raw_data.get('name') and len(raw_data.get('name', '').split()) > 1 else '',
            'email': raw_data.get('email'),
            'phone': raw_data.get('phone'),
            'mobile': raw_data.get('mobile_phone'),
            'title': None,
            'notes': raw_data.get('notes'),
            'created_at': raw_data.get('created_at'),
            'updated_at': raw_data.get('updated_at'),
        }

    def normalize_ticket(self, raw_data: Dict) -> Dict:
        """Normalize Syncro ticket data to common format."""
        status_map = {
            'New': 'open',
            'In Progress': 'in_progress',
            'Waiting on Customer': 'waiting',
            'Scheduled': 'scheduled',
            'Resolved': 'resolved',
            'Closed': 'closed',
        }

        priority_map = {
            'Low': 'low',
            'Medium': 'medium',
            'High': 'high',
            'Emergency': 'critical',
        }

        return {
            'external_id': str(raw_data.get('id', '')),
            'company_id': str(raw_data.get('customer_id', '')),
            'number': raw_data.get('number'),
            'subject': raw_data.get('subject'),
            'description': raw_data.get('problem_description'),
            'status': status_map.get(raw_data.get('status'), 'open'),
            'priority': priority_map.get(raw_data.get('priority'), 'medium'),
            'created_at': raw_data.get('created_at'),
            'updated_at': raw_data.get('updated_at'),
            'resolved_at': raw_data.get('resolved_at'),
            'due_date': raw_data.get('due_date'),
            'assignee_name': None,  # Syncro doesn't expose assignee in list
            'custom_fields': {
                'ticket_type': raw_data.get('ticket_type'),
                'user_id': raw_data.get('user_id'),
            }
        }
