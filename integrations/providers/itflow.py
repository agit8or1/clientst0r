"""
ITFlow PSA provider implementation.
ITFlow is an open-source IT documentation platform.
API Documentation: https://docs.itflow.org/api
"""
import logging
from typing import Dict, List
from datetime import datetime
from .base import BaseProvider, AuthenticationError, ProviderError
import json

logger = logging.getLogger('integrations')


class ITFlowProvider(BaseProvider):
    """
    ITFlow provider.
    Requires credentials: api_key
    API Documentation: https://docs.itflow.org/api
    """
    provider_name = "ITFlow"
    supports_companies = True
    supports_contacts = True
    supports_tickets = True
    supports_projects = False
    supports_agreements = False

    def _get_auth_headers(self):
        """ITFlow uses API key in headers."""
        api_key = self.credentials.get('api_key', '')

        if not api_key:
            raise AuthenticationError("Missing ITFlow API key")

        return {
            'X-API-KEY': api_key,
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }

    def _safe_json(self, response):
        """
        Safely parse JSON response with better error handling.
        Raises ProviderError with detailed message if parsing fails.
        """
        # Check if response has content
        if not response.content:
            raise ProviderError(
                f"Empty response from ITFlow API (Status: {response.status_code}, "
                f"URL: {response.url}). The API endpoint may not exist or returned no data."
            )

        # Try to parse JSON
        try:
            return self._safe_json(response)
        except json.JSONDecodeError as e:
            # Log the actual response content for debugging
            content_preview = response.text[:500] if response.text else "(empty)"
            logger.error(
                f"Invalid JSON from ITFlow API. "
                f"Status: {response.status_code}, "
                f"URL: {response.url}, "
                f"Content preview: {content_preview}"
            )
            raise ProviderError(
                f"Invalid JSON response from ITFlow API (Status: {response.status_code}). "
                f"The API may be misconfigured or returning HTML instead of JSON. "
                f"Response preview: {content_preview}"
            )

    def test_connection(self) -> bool:
        """Test connection by fetching clients."""
        try:
            response = self._make_request('GET', '/api/v1/clients')
            return response.status_code == 200
        except Exception as e:
            logger.error(f"ITFlow connection test failed: {e}")
            return False

    def list_companies(self, page_size=100, updated_since=None) -> List[Dict]:
        """List clients from ITFlow."""
        companies = []

        try:
            # ITFlow API endpoint for clients
            response = self._make_request('GET', '/api/v1/clients')
            data = self._safe_json(response)

            # ITFlow returns array of clients
            clients = data if isinstance(data, list) else data.get('data', [])

            for raw_client in clients:
                # Filter by updated_since if provided
                if updated_since:
                    updated_at = raw_client.get('client_updated_at')
                    if updated_at:
                        try:
                            client_updated = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                            if client_updated < updated_since:
                                continue
                        except (ValueError, AttributeError):
                            pass

                companies.append(self.normalize_company(raw_client))

        except Exception as e:
            logger.error(f"Error fetching ITFlow clients: {e}")
            raise ProviderError(f"Failed to fetch clients: {e}")

        return companies

    def get_company(self, company_id: str) -> Dict:
        """Get single client from ITFlow."""
        try:
            response = self._make_request('GET', f'/api/v1/clients/{company_id}')
            raw_client = self._safe_json(response)
            return self.normalize_company(raw_client)
        except Exception as e:
            logger.error(f"Error fetching ITFlow client {company_id}: {e}")
            raise ProviderError(f"Failed to fetch client: {e}")

    def list_contacts(self, company_id=None, page_size=100, updated_since=None) -> List[Dict]:
        """List contacts from ITFlow."""
        contacts = []

        try:
            # Get all contacts or filter by client
            if company_id:
                response = self._make_request('GET', f'/api/v1/clients/{company_id}/contacts')
            else:
                response = self._make_request('GET', '/api/v1/contacts')

            data = self._safe_json(response)
            contact_list = data if isinstance(data, list) else data.get('data', [])

            for raw_contact in contact_list:
                # Filter by updated_since if provided
                if updated_since:
                    updated_at = raw_contact.get('contact_updated_at')
                    if updated_at:
                        try:
                            contact_updated = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                            if contact_updated < updated_since:
                                continue
                        except (ValueError, AttributeError):
                            pass

                contacts.append(self.normalize_contact(raw_contact))

        except Exception as e:
            logger.error(f"Error fetching ITFlow contacts: {e}")
            raise ProviderError(f"Failed to fetch contacts: {e}")

        return contacts

    def get_contact(self, contact_id: str) -> Dict:
        """Get single contact from ITFlow."""
        try:
            response = self._make_request('GET', f'/api/v1/contacts/{contact_id}')
            raw_contact = self._safe_json(response)
            return self.normalize_contact(raw_contact)
        except Exception as e:
            logger.error(f"Error fetching ITFlow contact {contact_id}: {e}")
            raise ProviderError(f"Failed to fetch contact: {e}")

    def list_tickets(self, company_id=None, page_size=100, updated_since=None) -> List[Dict]:
        """List tickets from ITFlow."""
        tickets = []

        try:
            # Get tickets, optionally filtered by client
            if company_id:
                response = self._make_request('GET', f'/api/v1/clients/{company_id}/tickets')
            else:
                response = self._make_request('GET', '/api/v1/tickets')

            data = self._safe_json(response)
            ticket_list = data if isinstance(data, list) else data.get('data', [])

            for raw_ticket in ticket_list:
                # Filter by updated_since if provided
                if updated_since:
                    updated_at = raw_ticket.get('ticket_updated_at')
                    if updated_at:
                        try:
                            ticket_updated = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                            if ticket_updated < updated_since:
                                continue
                        except (ValueError, AttributeError):
                            pass

                tickets.append(self.normalize_ticket(raw_ticket))

        except Exception as e:
            logger.error(f"Error fetching ITFlow tickets: {e}")
            raise ProviderError(f"Failed to fetch tickets: {e}")

        return tickets

    def get_ticket(self, ticket_id: str) -> Dict:
        """Get single ticket from ITFlow."""
        try:
            response = self._make_request('GET', f'/api/v1/tickets/{ticket_id}')
            raw_ticket = self._safe_json(response)
            return self.normalize_ticket(raw_ticket)
        except Exception as e:
            logger.error(f"Error fetching ITFlow ticket {ticket_id}: {e}")
            raise ProviderError(f"Failed to fetch ticket: {e}")

    # Normalization methods

    def normalize_company(self, raw_data: Dict) -> Dict:
        """Normalize ITFlow client to standard company format."""
        return {
            'external_id': str(raw_data.get('client_id', '')),
            'name': raw_data.get('client_name', ''),
            'address': raw_data.get('client_address', ''),
            'city': raw_data.get('client_city', ''),
            'state': raw_data.get('client_state', ''),
            'zip': raw_data.get('client_zip', ''),
            'country': raw_data.get('client_country', ''),
            'phone': raw_data.get('client_phone', ''),
            'website': raw_data.get('client_website', ''),
            'notes': raw_data.get('client_notes', ''),
            'is_active': raw_data.get('client_archived', 0) == 0,
            'created_at': self._parse_datetime(raw_data.get('client_created_at')),
            'updated_at': self._parse_datetime(raw_data.get('client_updated_at')),
            'raw_data': raw_data,
        }

    def normalize_contact(self, raw_data: Dict) -> Dict:
        """Normalize ITFlow contact to standard format."""
        return {
            'external_id': str(raw_data.get('contact_id', '')),
            'company_id': str(raw_data.get('contact_client_id', '')),
            'first_name': raw_data.get('contact_name', '').split()[0] if raw_data.get('contact_name') else '',
            'last_name': ' '.join(raw_data.get('contact_name', '').split()[1:]) if raw_data.get('contact_name') else '',
            'email': raw_data.get('contact_email', ''),
            'phone': raw_data.get('contact_phone', ''),
            'mobile': raw_data.get('contact_mobile', ''),
            'title': raw_data.get('contact_title', ''),
            'notes': raw_data.get('contact_notes', ''),
            'is_primary': raw_data.get('contact_primary', 0) == 1,
            'is_active': raw_data.get('contact_archived', 0) == 0,
            'created_at': self._parse_datetime(raw_data.get('contact_created_at')),
            'updated_at': self._parse_datetime(raw_data.get('contact_updated_at')),
            'raw_data': raw_data,
        }

    def normalize_ticket(self, raw_data: Dict) -> Dict:
        """Normalize ITFlow ticket to standard format."""
        # Map ITFlow status to standard status
        status_map = {
            'Open': 'open',
            'Working': 'in_progress',
            'Waiting': 'waiting',
            'Closed': 'closed',
            'Resolved': 'resolved',
        }
        itflow_status = raw_data.get('ticket_status', 'Open')
        status = status_map.get(itflow_status, 'open')

        # Map priority
        priority_map = {
            'Low': 'low',
            'Medium': 'medium',
            'High': 'high',
            'Critical': 'critical',
        }
        itflow_priority = raw_data.get('ticket_priority', 'Medium')
        priority = priority_map.get(itflow_priority, 'medium')

        return {
            'external_id': str(raw_data.get('ticket_id', '')),
            'company_id': str(raw_data.get('ticket_client_id', '')),
            'contact_id': str(raw_data.get('ticket_contact_id', '')) if raw_data.get('ticket_contact_id') else None,
            'subject': raw_data.get('ticket_subject', ''),
            'description': raw_data.get('ticket_details', ''),
            'status': status,
            'priority': priority,
            'ticket_number': str(raw_data.get('ticket_number', '')),
            'assigned_to': raw_data.get('ticket_assigned_to', ''),
            'created_at': self._parse_datetime(raw_data.get('ticket_created_at')),
            'updated_at': self._parse_datetime(raw_data.get('ticket_updated_at')),
            'closed_at': self._parse_datetime(raw_data.get('ticket_closed_at')),
            'raw_data': raw_data,
        }
