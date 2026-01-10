"""
Zendesk Provider
Implements full integration with Zendesk Support API.
"""
import base64
import logging
from typing import List, Dict, Optional
from datetime import datetime
from .base import BaseProvider, ProviderError, AuthenticationError

logger = logging.getLogger('integrations')


class ZendeskProvider(BaseProvider):
    """
    Zendesk Support provider.
    Requires credentials: email, api_token, subdomain
    API Documentation: https://developer.zendesk.com/api-reference/
    """
    provider_name = "Zendesk"
    supports_companies = True
    supports_contacts = True
    supports_tickets = True
    supports_projects = False
    supports_agreements = False

    def _get_auth_headers(self):
        """Zendesk uses Basic Auth with email/token:api_token."""
        email = self.credentials.get('email', '')
        api_token = self.credentials.get('api_token', '')

        if not all([email, api_token]):
            raise AuthenticationError("Missing Zendesk credentials")

        # Zendesk Basic Auth format: email/token:api_token
        auth_string = f"{email}/token:{api_token}"
        auth_b64 = base64.b64encode(auth_string.encode()).decode('ascii')

        return {
            'Authorization': f'Basic {auth_b64}',
            'Content-Type': 'application/json',
        }

    def test_connection(self) -> bool:
        """Test connection by fetching current user."""
        try:
            response = self._make_request('GET', '/api/v2/users/me.json')
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Zendesk connection test failed: {e}")
            return False

    def list_companies(self, page_size=100, updated_since=None) -> List[Dict]:
        """List organizations from Zendesk."""
        companies = []
        url = '/api/v2/organizations.json'

        while url:
            try:
                response = self._make_request('GET', url)
                data = response.json()

                organizations = data.get('organizations', [])
                if not organizations:
                    break

                for raw_org in organizations:
                    # Filter by updated_since if provided
                    if updated_since:
                        updated_at = raw_org.get('updated_at')
                        if updated_at:
                            org_updated = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                            if org_updated < updated_since:
                                continue

                    companies.append(self.normalize_company(raw_org))

                # Check for next page
                url = data.get('next_page')

            except Exception as e:
                logger.error(f"Error fetching Zendesk organizations: {e}")
                break

        return companies

    def get_company(self, company_id: str) -> Dict:
        """Get single organization from Zendesk."""
        try:
            response = self._make_request('GET', f'/api/v2/organizations/{company_id}.json')
            data = response.json()
            return self.normalize_company(data.get('organization', {}))
        except Exception as e:
            logger.error(f"Error fetching Zendesk organization {company_id}: {e}")
            raise ProviderError(f"Failed to fetch organization: {e}")

    def list_contacts(self, company_id: Optional[str] = None, page_size=100, updated_since=None) -> List[Dict]:
        """List users from Zendesk."""
        contacts = []

        if company_id:
            # Get users for specific organization
            url = f'/api/v2/organizations/{company_id}/users.json'
        else:
            # Get all users
            url = '/api/v2/users.json'

        while url:
            try:
                response = self._make_request('GET', url)
                data = response.json()

                users = data.get('users', [])
                if not users:
                    break

                for raw_user in users:
                    # Filter by updated_since if provided
                    if updated_since:
                        updated_at = raw_user.get('updated_at')
                        if updated_at:
                            user_updated = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                            if user_updated < updated_since:
                                continue

                    contacts.append(self.normalize_contact(raw_user))

                # Check for next page
                url = data.get('next_page')

            except Exception as e:
                logger.error(f"Error fetching Zendesk users: {e}")
                break

        return contacts

    def list_tickets(self, company_id: Optional[str] = None, status: Optional[str] = None,
                     updated_since: Optional[datetime] = None, page_size=100) -> List[Dict]:
        """List tickets from Zendesk."""
        tickets = []

        if company_id:
            # Get tickets for specific organization
            url = f'/api/v2/organizations/{company_id}/tickets.json'
        else:
            # Get all tickets
            url = '/api/v2/tickets.json'

        while url:
            try:
                response = self._make_request('GET', url)
                data = response.json()

                ticket_list = data.get('tickets', [])
                if not ticket_list:
                    break

                for raw_ticket in ticket_list:
                    # Filter by updated_since
                    if updated_since:
                        updated_at = raw_ticket.get('updated_at')
                        if updated_at:
                            ticket_updated = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                            if ticket_updated < updated_since:
                                continue

                    # Filter by status
                    if status:
                        ticket_status = self._normalize_status(raw_ticket.get('status'))
                        if ticket_status != status:
                            continue

                    tickets.append(self.normalize_ticket(raw_ticket))

                # Check for next page
                url = data.get('next_page')

            except Exception as e:
                logger.error(f"Error fetching Zendesk tickets: {e}")
                break

        return tickets

    def get_ticket(self, ticket_id: str) -> Dict:
        """Get single ticket from Zendesk."""
        try:
            response = self._make_request('GET', f'/api/v2/tickets/{ticket_id}.json')
            data = response.json()
            return self.normalize_ticket(data.get('ticket', {}))
        except Exception as e:
            logger.error(f"Error fetching Zendesk ticket {ticket_id}: {e}")
            raise ProviderError(f"Failed to fetch ticket: {e}")

    def _normalize_status(self, status_str: str) -> str:
        """Convert Zendesk status to common status."""
        status_map = {
            'new': 'open',
            'open': 'open',
            'pending': 'waiting',
            'hold': 'waiting',
            'solved': 'resolved',
            'closed': 'closed',
        }
        return status_map.get(status_str, 'open')

    def _normalize_priority(self, priority_str: str) -> str:
        """Convert Zendesk priority to common priority."""
        priority_map = {
            'low': 'low',
            'normal': 'medium',
            'high': 'high',
            'urgent': 'critical',
        }
        return priority_map.get(priority_str, 'medium')

    def normalize_company(self, raw_data: Dict) -> Dict:
        """Normalize Zendesk organization data to common format."""
        return {
            'external_id': str(raw_data.get('id', '')),
            'name': raw_data.get('name'),
            'phone': None,
            'email': None,
            'address': None,
            'city': None,
            'state': None,
            'zip': None,
            'country': None,
            'website': raw_data.get('url'),
            'notes': raw_data.get('notes'),
            'created_at': raw_data.get('created_at'),
            'updated_at': raw_data.get('updated_at'),
            'custom_fields': {
                'external_id': raw_data.get('external_id'),
                'domain_names': raw_data.get('domain_names'),
                'details': raw_data.get('details'),
            }
        }

    def normalize_contact(self, raw_data: Dict) -> Dict:
        """Normalize Zendesk user data to common format."""
        # Split name into first/last
        name = raw_data.get('name', '')
        name_parts = name.split(maxsplit=1)
        first_name = name_parts[0] if name_parts else ''
        last_name = name_parts[1] if len(name_parts) > 1 else ''

        return {
            'external_id': str(raw_data.get('id', '')),
            'company_id': str(raw_data.get('organization_id')) if raw_data.get('organization_id') else None,
            'first_name': first_name,
            'last_name': last_name,
            'email': raw_data.get('email'),
            'phone': raw_data.get('phone'),
            'mobile': None,
            'title': None,
            'notes': raw_data.get('notes'),
            'created_at': raw_data.get('created_at'),
            'updated_at': raw_data.get('updated_at'),
            'custom_fields': {
                'role': raw_data.get('role'),
                'time_zone': raw_data.get('time_zone'),
                'locale': raw_data.get('locale'),
                'verified': raw_data.get('verified'),
            }
        }

    def normalize_ticket(self, raw_data: Dict) -> Dict:
        """Normalize Zendesk ticket data to common format."""
        return {
            'external_id': str(raw_data.get('id', '')),
            'company_id': str(raw_data.get('organization_id')) if raw_data.get('organization_id') else None,
            'number': raw_data.get('id'),  # Zendesk uses ID as ticket number
            'subject': raw_data.get('subject'),
            'description': raw_data.get('description'),
            'status': self._normalize_status(raw_data.get('status', 'new')),
            'priority': self._normalize_priority(raw_data.get('priority', 'normal')),
            'created_at': raw_data.get('created_at'),
            'updated_at': raw_data.get('updated_at'),
            'resolved_at': None,  # Zendesk doesn't have a resolved_at field
            'due_date': raw_data.get('due_at'),
            'assignee_name': None,  # Would need to fetch assignee details separately
            'custom_fields': {
                'type': raw_data.get('type'),
                'via': raw_data.get('via'),
                'requester_id': raw_data.get('requester_id'),
                'assignee_id': raw_data.get('assignee_id'),
                'group_id': raw_data.get('group_id'),
                'tags': raw_data.get('tags'),
            }
        }
