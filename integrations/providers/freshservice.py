"""
Freshservice Provider
Implements full integration with Freshservice ITSM API.
"""
import base64
import logging
from typing import List, Dict, Optional
from datetime import datetime
from .base import BaseProvider, ProviderError, AuthenticationError

logger = logging.getLogger('integrations')


class FreshserviceProvider(BaseProvider):
    """
    Freshservice ITSM provider.
    Requires credentials: api_key, domain
    API Documentation: https://api.freshservice.com/
    """
    provider_name = "Freshservice"
    supports_companies = True
    supports_contacts = True
    supports_tickets = True
    supports_projects = False
    supports_agreements = False

    def _get_auth_headers(self):
        """Freshservice uses Basic Auth with API key as username, password as 'X'."""
        api_key = self.credentials.get('api_key', '')

        if not api_key:
            raise AuthenticationError("Missing Freshservice API key")

        # Freshservice uses Basic Auth: api_key:X
        auth_string = f"{api_key}:X"
        auth_b64 = base64.b64encode(auth_string.encode()).decode('ascii')

        return {
            'Authorization': f'Basic {auth_b64}',
            'Content-Type': 'application/json',
        }

    def test_connection(self) -> bool:
        """Test connection by fetching agents (current user info)."""
        try:
            response = self._make_request('GET', '/api/v2/agents?per_page=1')
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Freshservice connection test failed: {e}")
            return False

    def list_companies(self, page_size=100, updated_since=None) -> List[Dict]:
        """List companies (departments) from Freshservice."""
        companies = []
        page = 1

        while True:
            params = {
                'page': page,
                'per_page': min(page_size, 100),
            }

            try:
                response = self._make_request('GET', '/api/v2/departments', params=params)
                data = response.json()

                departments = data.get('departments', [])
                if not departments:
                    break

                for raw_dept in departments:
                    # Filter by updated_since if provided
                    if updated_since:
                        updated_at = raw_dept.get('updated_at')
                        if updated_at:
                            dept_updated = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                            if dept_updated < updated_since:
                                continue

                    companies.append(self.normalize_company(raw_dept))

                # Check if there are more results
                if len(departments) < params['per_page']:
                    break

                page += 1

            except Exception as e:
                logger.error(f"Error fetching Freshservice departments page {page}: {e}")
                break

        return companies

    def get_company(self, company_id: str) -> Dict:
        """Get single department from Freshservice."""
        try:
            response = self._make_request('GET', f'/api/v2/departments/{company_id}')
            data = response.json()
            return self.normalize_company(data.get('department', {}))
        except Exception as e:
            logger.error(f"Error fetching Freshservice department {company_id}: {e}")
            raise ProviderError(f"Failed to fetch department: {e}")

    def list_contacts(self, company_id: Optional[str] = None, page_size=100, updated_since=None) -> List[Dict]:
        """List requesters (end users) from Freshservice."""
        contacts = []
        page = 1

        while True:
            params = {
                'page': page,
                'per_page': min(page_size, 100),
            }

            # Freshservice doesn't filter requesters by department in list endpoint
            # We'll have to filter after fetching

            try:
                response = self._make_request('GET', '/api/v2/requesters', params=params)
                data = response.json()

                requesters = data.get('requesters', [])
                if not requesters:
                    break

                for raw_requester in requesters:
                    # Filter by department if provided
                    if company_id and str(raw_requester.get('department_ids', [None])[0] if raw_requester.get('department_ids') else None) != company_id:
                        continue

                    contacts.append(self.normalize_contact(raw_requester))

                if len(requesters) < params['per_page']:
                    break

                page += 1

            except Exception as e:
                logger.error(f"Error fetching Freshservice requesters page {page}: {e}")
                break

        return contacts

    def list_tickets(self, company_id: Optional[str] = None, status: Optional[str] = None,
                     updated_since: Optional[datetime] = None, page_size=100) -> List[Dict]:
        """List tickets from Freshservice."""
        tickets = []
        page = 1

        while True:
            params = {
                'page': page,
                'per_page': min(page_size, 100),
            }

            # Build filter query
            filters = []
            if updated_since:
                # Freshservice uses predefined filters, not custom date queries in list endpoint
                pass  # We'll filter after fetching

            try:
                response = self._make_request('GET', '/api/v2/tickets', params=params)
                data = response.json()

                ticket_list = data.get('tickets', [])
                if not ticket_list:
                    break

                for raw_ticket in ticket_list:
                    # Filter by company/department
                    if company_id and str(raw_ticket.get('department_id')) != company_id:
                        continue

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

                if len(ticket_list) < params['per_page']:
                    break

                page += 1

            except Exception as e:
                logger.error(f"Error fetching Freshservice tickets page {page}: {e}")
                break

        return tickets

    def get_ticket(self, ticket_id: str) -> Dict:
        """Get single ticket from Freshservice."""
        try:
            response = self._make_request('GET', f'/api/v2/tickets/{ticket_id}')
            data = response.json()
            return self.normalize_ticket(data.get('ticket', {}))
        except Exception as e:
            logger.error(f"Error fetching Freshservice ticket {ticket_id}: {e}")
            raise ProviderError(f"Failed to fetch ticket: {e}")

    def _normalize_status(self, status_code: int) -> str:
        """Convert Freshservice status code to common status."""
        status_map = {
            2: 'open',
            3: 'in_progress',
            4: 'resolved',
            5: 'closed',
            6: 'waiting',
        }
        return status_map.get(status_code, 'open')

    def _normalize_priority(self, priority_code: int) -> str:
        """Convert Freshservice priority code to common priority."""
        priority_map = {
            1: 'low',
            2: 'medium',
            3: 'high',
            4: 'critical',
        }
        return priority_map.get(priority_code, 'medium')

    def normalize_company(self, raw_data: Dict) -> Dict:
        """Normalize Freshservice department data to common format."""
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
            'website': None,
            'notes': raw_data.get('description'),
            'created_at': raw_data.get('created_at'),
            'updated_at': raw_data.get('updated_at'),
            'custom_fields': {
                'head_user_id': raw_data.get('head_user_id'),
                'prime_user_id': raw_data.get('prime_user_id'),
            }
        }

    def normalize_contact(self, raw_data: Dict) -> Dict:
        """Normalize Freshservice requester data to common format."""
        # Extract department_id (first one if multiple)
        department_ids = raw_data.get('department_ids', [])
        department_id = str(department_ids[0]) if department_ids else None

        return {
            'external_id': str(raw_data.get('id', '')),
            'company_id': department_id,
            'first_name': raw_data.get('first_name'),
            'last_name': raw_data.get('last_name'),
            'email': raw_data.get('primary_email'),
            'phone': raw_data.get('work_phone_number'),
            'mobile': raw_data.get('mobile_phone_number'),
            'title': raw_data.get('job_title'),
            'notes': raw_data.get('background_information'),
            'created_at': raw_data.get('created_at'),
            'updated_at': raw_data.get('updated_at'),
            'custom_fields': {
                'time_zone': raw_data.get('time_zone'),
                'language': raw_data.get('language'),
                'location_id': raw_data.get('location_id'),
            }
        }

    def normalize_ticket(self, raw_data: Dict) -> Dict:
        """Normalize Freshservice ticket data to common format."""
        return {
            'external_id': str(raw_data.get('id', '')),
            'company_id': str(raw_data.get('department_id')) if raw_data.get('department_id') else None,
            'number': raw_data.get('id'),  # Freshservice uses ID as ticket number
            'subject': raw_data.get('subject'),
            'description': raw_data.get('description_text'),
            'status': self._normalize_status(raw_data.get('status', 2)),
            'priority': self._normalize_priority(raw_data.get('priority', 2)),
            'created_at': raw_data.get('created_at'),
            'updated_at': raw_data.get('updated_at'),
            'resolved_at': raw_data.get('stats', {}).get('resolved_at'),
            'due_date': raw_data.get('due_by'),
            'assignee_name': None,  # Would need to fetch responder details separately
            'custom_fields': {
                'type': raw_data.get('type'),
                'source': raw_data.get('source'),
                'category': raw_data.get('category'),
                'sub_category': raw_data.get('sub_category'),
                'item_category': raw_data.get('item_category'),
                'requester_id': raw_data.get('requester_id'),
                'responder_id': raw_data.get('responder_id'),
            }
        }
