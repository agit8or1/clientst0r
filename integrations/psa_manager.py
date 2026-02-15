"""
PSA Manager - Unified interface for PSA ticket operations
"""
import logging
import requests
from django.core.exceptions import ValidationError

logger = logging.getLogger('integrations')


class PSAManager:
    """
    Unified manager for PSA ticket operations across different providers.
    """

    def __init__(self):
        self.logger = logging.getLogger('integrations.psa_manager')

    def add_ticket_note(self, ticket, note, internal=False):
        """
        Add a note/comment to a PSA ticket.

        Args:
            ticket: PSATicket instance
            note: Note text to add
            internal: Whether the note is internal/private (default: False)

        Returns:
            bool: True if successful, False otherwise
        """
        if not ticket or not ticket.connection:
            self.logger.error("Invalid ticket or connection")
            return False

        provider = ticket.connection.provider_type
        self.logger.info(f"Adding note to {provider} ticket {ticket.ticket_number}")

        try:
            if provider == 'itflow':
                return self._add_note_itflow(ticket, note, internal)
            elif provider == 'connectwise_manage':
                return self._add_note_connectwise(ticket, note, internal)
            elif provider == 'autotask':
                return self._add_note_autotask(ticket, note, internal)
            elif provider == 'halo_psa':
                return self._add_note_halo(ticket, note, internal)
            elif provider == 'syncro':
                return self._add_note_syncro(ticket, note, internal)
            else:
                self.logger.warning(f"PSA provider {provider} not supported for ticket notes")
                return False

        except Exception as e:
            self.logger.error(f"Failed to add note to {provider} ticket: {e}")
            return False

    def _get_credentials(self, connection):
        """Decrypt and return connection credentials."""
        from vault.encryption_v2 import decrypt_v2
        import json

        try:
            decrypted = decrypt_v2(connection.encrypted_credentials)
            return json.loads(decrypted)
        except Exception as e:
            self.logger.error(f"Failed to decrypt credentials: {e}")
            return None

    def _add_note_itflow(self, ticket, note, internal=False):
        """Add note to ITFlow ticket."""
        creds = self._get_credentials(ticket.connection)
        if not creds:
            return False

        api_key = creds.get('api_key')
        if not api_key:
            self.logger.error("ITFlow API key not found in credentials")
            return False

        # ITFlow API endpoint
        url = f"{ticket.connection.base_url.rstrip('/')}/api/v1/tickets/add_comment.php"

        data = {
            'api_key': api_key,
            'ticket_id': ticket.external_id or ticket.ticket_number,
            'comment': note,
            'internal': 1 if internal else 0
        }

        try:
            response = requests.post(url, data=data, timeout=30)
            response.raise_for_status()
            self.logger.info(f"Successfully added note to ITFlow ticket {ticket.ticket_number}")
            return True
        except requests.RequestException as e:
            self.logger.error(f"ITFlow API error: {e}")
            return False

    def _add_note_connectwise(self, ticket, note, internal=False):
        """Add note to ConnectWise Manage ticket."""
        creds = self._get_credentials(ticket.connection)
        if not creds:
            return False

        company_id = creds.get('company_id')
        public_key = creds.get('public_key')
        private_key = creds.get('private_key')

        if not all([company_id, public_key, private_key]):
            self.logger.error("ConnectWise credentials incomplete")
            return False

        # ConnectWise API endpoint
        url = f"{ticket.connection.base_url.rstrip('/')}/v4_6_release/apis/3.0/service/tickets/{ticket.external_id}/notes"

        # ConnectWise auth format
        import base64
        auth_string = f"{company_id}+{public_key}:{private_key}"
        encoded_auth = base64.b64encode(auth_string.encode()).decode()

        headers = {
            'Authorization': f'Basic {encoded_auth}',
            'Content-Type': 'application/json',
            'clientId': creds.get('client_id', 'Client St0r')
        }

        data = {
            'text': note,
            'detailDescriptionFlag': not internal,  # If not internal, it's customer-visible
            'internalAnalysisFlag': internal
        }

        try:
            response = requests.post(url, json=data, headers=headers, timeout=30)
            response.raise_for_status()
            self.logger.info(f"Successfully added note to ConnectWise ticket {ticket.ticket_number}")
            return True
        except requests.RequestException as e:
            self.logger.error(f"ConnectWise API error: {e}")
            return False

    def _add_note_autotask(self, ticket, note, internal=False):
        """Add note to Autotask ticket."""
        # TODO: Implement Autotask ticket note API
        self.logger.warning("Autotask ticket notes not yet implemented")
        return False

    def _add_note_halo(self, ticket, note, internal=False):
        """Add note to HaloPSA ticket."""
        # TODO: Implement HaloPSA ticket note API
        self.logger.warning("HaloPSA ticket notes not yet implemented")
        return False

    def _add_note_syncro(self, ticket, note, internal=False):
        """Add note to Syncro ticket."""
        creds = self._get_credentials(ticket.connection)
        if not creds:
            return False

        api_key = creds.get('api_key')
        if not api_key:
            self.logger.error("Syncro API key not found")
            return False

        # Syncro API endpoint
        url = f"{ticket.connection.base_url.rstrip('/')}/api/v1/tickets/{ticket.external_id}/comments"

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        data = {
            'comment': note,
            'hidden': internal
        }

        try:
            response = requests.post(url, json=data, headers=headers, timeout=30)
            response.raise_for_status()
            self.logger.info(f"Successfully added note to Syncro ticket {ticket.ticket_number}")
            return True
        except requests.RequestException as e:
            self.logger.error(f"Syncro API error: {e}")
            return False
