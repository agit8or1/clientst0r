"""
PSA sync engine
Handles synchronization of data from PSA systems to local database.
"""
import logging
import hashlib
import json
from datetime import datetime, timedelta
from django.utils import timezone
from django.db import transaction
from .models import PSAConnection, PSACompany, PSAContact, PSATicket, ExternalObjectMap
from .providers import get_provider
from audit.models import AuditLog

logger = logging.getLogger('integrations')


class SyncError(Exception):
    """Sync-specific error."""
    pass


class PSASync:
    """
    Synchronizes data from a PSA connection to local database.
    """

    def __init__(self, connection):
        self.connection = connection
        self.provider = get_provider(connection)
        self.organization = connection.organization
        self.sync_start = timezone.now()
        self.stats = {
            'companies': {'created': 0, 'updated': 0, 'errors': 0},
            'contacts': {'created': 0, 'updated': 0, 'errors': 0},
            'tickets': {'created': 0, 'updated': 0, 'errors': 0},
        }

    def sync_all(self):
        """
        Sync all enabled entity types.
        """
        logger.info(f"Starting sync for {self.connection}")

        try:
            # Test connection first
            if not self.provider.test_connection():
                raise SyncError("Connection test failed")

            # Sync in order (companies -> contacts -> tickets)
            if self.connection.sync_companies:
                self.sync_companies()

            if self.connection.sync_contacts:
                self.sync_contacts()

            if self.connection.sync_tickets:
                self.sync_tickets()

            # Update connection status
            self.connection.last_sync_at = self.sync_start
            self.connection.last_sync_status = 'success'
            self.connection.last_error = ''
            self.connection.save()

            # Audit log
            AuditLog.log(
                user=None,
                action='sync',
                organization=self.organization,
                object_type='psa_connection',
                object_id=self.connection.id,
                object_repr=str(self.connection),
                description=f"PSA sync completed: {self.stats}",
                success=True
            )

            logger.info(f"Sync completed successfully: {self.stats}")
            return self.stats

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Sync failed for {self.connection}: {error_msg}")

            self.connection.last_sync_at = self.sync_start
            self.connection.last_sync_status = 'error'
            self.connection.last_error = error_msg[:500]
            self.connection.save()

            AuditLog.log(
                user=None,
                action='sync',
                organization=self.organization,
                object_type='psa_connection',
                object_id=self.connection.id,
                object_repr=str(self.connection),
                description=f"PSA sync failed: {error_msg}",
                success=False
            )

            raise

    def sync_companies(self):
        """Sync companies from PSA."""
        logger.info(f"Syncing companies for {self.connection}")

        # Get updated_since from last successful sync
        updated_since = None
        if self.connection.last_sync_at and self.connection.last_sync_status == 'success':
            updated_since = self.connection.last_sync_at

        try:
            companies_data = self.provider.list_companies(updated_since=updated_since)

            for company_data in companies_data:
                try:
                    with transaction.atomic():
                        self._upsert_company(company_data)
                except Exception as e:
                    logger.error(f"Error syncing company {company_data.get('external_id')}: {e}")
                    self.stats['companies']['errors'] += 1

        except Exception as e:
            logger.error(f"Error listing companies: {e}")
            raise

    def sync_contacts(self):
        """Sync contacts from PSA."""
        logger.info(f"Syncing contacts for {self.connection}")

        updated_since = None
        if self.connection.last_sync_at and self.connection.last_sync_status == 'success':
            updated_since = self.connection.last_sync_at

        try:
            contacts_data = self.provider.list_contacts(updated_since=updated_since)

            for contact_data in contacts_data:
                try:
                    with transaction.atomic():
                        self._upsert_contact(contact_data)
                except Exception as e:
                    logger.error(f"Error syncing contact {contact_data.get('external_id')}: {e}")
                    self.stats['contacts']['errors'] += 1

        except Exception as e:
            logger.error(f"Error listing contacts: {e}")
            raise

    def sync_tickets(self):
        """Sync tickets from PSA."""
        logger.info(f"Syncing tickets for {self.connection}")

        updated_since = None
        if self.connection.last_sync_at and self.connection.last_sync_status == 'success':
            # Get tickets updated in last 30 days to catch status changes
            updated_since = timezone.now() - timedelta(days=30)

        try:
            tickets_data = self.provider.list_tickets(updated_since=updated_since)

            for ticket_data in tickets_data:
                try:
                    with transaction.atomic():
                        self._upsert_ticket(ticket_data)
                except Exception as e:
                    logger.error(f"Error syncing ticket {ticket_data.get('external_id')}: {e}")
                    self.stats['tickets']['errors'] += 1

        except Exception as e:
            logger.error(f"Error listing tickets: {e}")
            raise

    def _upsert_company(self, company_data):
        """Create or update company."""
        external_id = company_data['external_id']

        # Check if exists
        company, created = PSACompany.objects.update_or_create(
            connection=self.connection,
            external_id=external_id,
            defaults={
                'organization': self.organization,
                'name': company_data['name'],
                'phone': company_data.get('phone', ''),
                'website': company_data.get('website', ''),
                'address': company_data.get('address', ''),
                'raw_data': company_data.get('raw_data', {}),
            }
        )

        if created:
            self.stats['companies']['created'] += 1
            logger.debug(f"Created company: {company.name}")
        else:
            self.stats['companies']['updated'] += 1
            logger.debug(f"Updated company: {company.name}")

        # Update mapping
        data_hash = self._hash_data(company_data)
        ExternalObjectMap.objects.update_or_create(
            connection=self.connection,
            external_type='company',
            external_id=external_id,
            defaults={
                'organization': self.organization,
                'local_type': 'psa_company',
                'local_id': company.id,
                'external_hash': data_hash,
            }
        )

        return company

    def _upsert_contact(self, contact_data):
        """Create or update contact."""
        external_id = contact_data['external_id']

        # Find company if company_id provided
        company = None
        if contact_data.get('company_id'):
            try:
                company = PSACompany.objects.get(
                    connection=self.connection,
                    external_id=contact_data['company_id']
                )
            except PSACompany.DoesNotExist:
                pass

        contact, created = PSAContact.objects.update_or_create(
            connection=self.connection,
            external_id=external_id,
            defaults={
                'organization': self.organization,
                'company': company,
                'first_name': contact_data['first_name'],
                'last_name': contact_data['last_name'],
                'email': contact_data.get('email', ''),
                'phone': contact_data.get('phone', ''),
                'title': contact_data.get('title', ''),
                'raw_data': contact_data.get('raw_data', {}),
            }
        )

        if created:
            self.stats['contacts']['created'] += 1
        else:
            self.stats['contacts']['updated'] += 1

        # Update mapping
        data_hash = self._hash_data(contact_data)
        ExternalObjectMap.objects.update_or_create(
            connection=self.connection,
            external_type='contact',
            external_id=external_id,
            defaults={
                'organization': self.organization,
                'local_type': 'psa_contact',
                'local_id': contact.id,
                'external_hash': data_hash,
            }
        )

        return contact

    def _upsert_ticket(self, ticket_data):
        """Create or update ticket."""
        external_id = ticket_data['external_id']

        # Find company
        company = None
        if ticket_data.get('company_id'):
            try:
                company = PSACompany.objects.get(
                    connection=self.connection,
                    external_id=ticket_data['company_id']
                )
            except PSACompany.DoesNotExist:
                pass

        # Find contact
        contact = None
        if ticket_data.get('contact_id'):
            try:
                contact = PSAContact.objects.get(
                    connection=self.connection,
                    external_id=ticket_data['contact_id']
                )
            except PSAContact.DoesNotExist:
                pass

        ticket, created = PSATicket.objects.update_or_create(
            connection=self.connection,
            external_id=external_id,
            defaults={
                'organization': self.organization,
                'company': company,
                'contact': contact,
                'ticket_number': ticket_data.get('ticket_number', external_id),
                'subject': ticket_data['subject'],
                'description': ticket_data.get('description', ''),
                'status': ticket_data.get('status', 'new'),
                'priority': ticket_data.get('priority', 'medium'),
                'external_created_at': ticket_data.get('created_at'),
                'external_updated_at': ticket_data.get('updated_at'),
                'raw_data': ticket_data.get('raw_data', {}),
            }
        )

        if created:
            self.stats['tickets']['created'] += 1
        else:
            self.stats['tickets']['updated'] += 1

        # Update mapping
        data_hash = self._hash_data(ticket_data)
        ExternalObjectMap.objects.update_or_create(
            connection=self.connection,
            external_type='ticket',
            external_id=external_id,
            defaults={
                'organization': self.organization,
                'local_type': 'psa_ticket',
                'local_id': ticket.id,
                'external_hash': data_hash,
            }
        )

        return ticket

    def _hash_data(self, data):
        """Generate hash of data for change detection."""
        data_str = json.dumps(data, sort_keys=True)
        return hashlib.sha256(data_str.encode()).hexdigest()
