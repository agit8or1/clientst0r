"""
PSA and RMM sync engines
Handles synchronization of data from PSA and RMM systems to local database.
"""
import logging
import hashlib
import json
from datetime import datetime, timedelta
from django.utils import timezone
from django.db import transaction
from .models import (
    PSAConnection, PSACompany, PSAContact, PSATicket,
    RMMConnection, RMMDevice, RMMAlert, RMMSoftware,
    ExternalObjectMap
)
from .providers import get_provider
from .providers.rmm import get_rmm_provider
from .org_import import import_organization_from_rmm
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
            'organizations': {'created': 0, 'updated': 0, 'errors': 0},
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

        # Determine target organization (may import new org if enabled)
        target_org = self._determine_target_organization(company_data)

        # Check if exists
        company, created = PSACompany.objects.update_or_create(
            connection=self.connection,
            external_id=external_id,
            defaults={
                'organization': target_org,
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
                'organization': target_org,
                'local_type': 'psa_company',
                'local_id': company.id,
                'external_hash': data_hash,
            }
        )

        return company

    def _determine_target_organization(self, company_data):
        """
        Determine which organization this PSA company should belong to.

        If import_organizations is enabled, attempts to import/create organization
        from PSA company data. Falls back to connection organization.

        Args:
            company_data: Normalized company data from provider

        Returns:
            Organization instance
        """
        if not self.connection.import_organizations:
            # Organization import disabled - use connection's organization
            return self.organization

        # Import/create organization for this PSA company
        try:
            from .org_import import import_organization_from_psa, find_existing_organization_by_psa_id

            # Check if organization already exists
            external_id = company_data.get('external_id', '')
            existing_org = find_existing_organization_by_psa_id(self.connection, external_id)

            # Attempt to import/create organization
            imported_org = import_organization_from_psa(self.connection, company_data)

            if imported_org:
                # Track if this was a create or update
                if existing_org:
                    if not hasattr(self.stats, 'organizations'):
                        self.stats['organizations'] = {'created': 0, 'updated': 0, 'errors': 0}
                    self.stats['organizations']['updated'] += 1
                    logger.debug(f"Updated existing organization {imported_org.name} for company {company_data.get('name')}")
                else:
                    if not hasattr(self.stats, 'organizations'):
                        self.stats['organizations'] = {'created': 0, 'updated': 0, 'errors': 0}
                    self.stats['organizations']['created'] += 1
                    logger.info(f"Created new organization {imported_org.name} for company {company_data.get('name')}")

                logger.info(f"PSA company {company_data.get('name')} mapped to organization {imported_org.name}")
                return imported_org
            else:
                # Import returned None - fallback to connection org
                logger.warning(f"Failed to import organization for company {company_data.get('name')}, using connection org")
                return self.organization

        except Exception as e:
            logger.error(f"Error importing organization for company {company_data.get('name')}: {e}")
            if not hasattr(self.stats, 'organizations'):
                self.stats['organizations'] = {'created': 0, 'updated': 0, 'errors': 0}
            self.stats['organizations']['errors'] += 1
            # On error, fallback to connection org
            return self.organization

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
        # Use default=str to handle datetime objects and other non-JSON-serializable types
        data_str = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(data_str.encode()).hexdigest()


class RMMSync:
    """
    Synchronizes data from an RMM connection to local database.
    Handles devices, alerts, and software inventory.
    """

    def __init__(self, connection):
        self.connection = connection
        self.provider = get_rmm_provider(connection)
        self.organization = connection.organization
        self.sync_start = timezone.now()
        self.stats = {
            'devices': {'created': 0, 'updated': 0, 'mapped': 0, 'errors': 0},
            'alerts': {'created': 0, 'updated': 0, 'errors': 0},
            'software': {'created': 0, 'updated': 0, 'deleted': 0, 'errors': 0},
            'organizations': {'created': 0, 'updated': 0, 'errors': 0},
        }

    def sync_all(self):
        """
        Sync all enabled entity types.
        """
        logger.info(f"Starting RMM sync for {self.connection}")

        try:
            # Test connection first
            if not self.provider.test_connection():
                raise SyncError("RMM connection test failed")

            # Sync devices first (required for alerts and software)
            if self.connection.sync_devices:
                self.sync_devices()

            # Sync alerts
            if self.connection.sync_alerts:
                self.sync_alerts()

            # Sync software
            if self.connection.sync_software and self.provider.supports_software:
                self.sync_software()

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
                object_type='rmm_connection',
                object_id=self.connection.id,
                object_repr=str(self.connection),
                description=f"RMM sync completed: {self.stats}",
                success=True
            )

            logger.info(f"RMM sync completed successfully: {self.stats}")
            return self.stats

        except Exception as e:
            error_msg = str(e)
            logger.error(f"RMM sync failed for {self.connection}: {error_msg}")

            self.connection.last_sync_at = self.sync_start
            self.connection.last_sync_status = 'error'
            self.connection.last_error = error_msg[:500]
            self.connection.save()

            AuditLog.log(
                user=None,
                action='sync',
                organization=self.organization,
                object_type='rmm_connection',
                object_id=self.connection.id,
                object_repr=str(self.connection),
                description=f"RMM sync failed: {error_msg}",
                success=False
            )

            raise

    def sync_devices(self):
        """Sync devices from RMM."""
        logger.info(f"Syncing devices for {self.connection}")

        # Get updated_since from last successful sync
        updated_since = None
        if self.connection.last_sync_at and self.connection.last_sync_status == 'success':
            updated_since = self.connection.last_sync_at

        try:
            devices_data = self.provider.list_devices(updated_since=updated_since)

            for device_data in devices_data:
                try:
                    with transaction.atomic():
                        # Determine target organization for this device
                        target_org = self._determine_target_organization(device_data)

                        # Create/update device with the determined organization
                        device = self._upsert_device(device_data, target_org)

                        # Auto-map to assets if enabled
                        if self.connection.map_to_assets:
                            self._map_device_to_asset(device)

                except Exception as e:
                    logger.error(f"Error syncing device {device_data.get('external_id')}: {e}")
                    self.stats['devices']['errors'] += 1

        except Exception as e:
            logger.error(f"Error listing devices: {e}")
            raise

    def sync_alerts(self):
        """Sync alerts from RMM."""
        logger.info(f"Syncing alerts for {self.connection}")

        updated_since = None
        if self.connection.last_sync_at and self.connection.last_sync_status == 'success':
            # Get alerts from last 7 days to catch status changes
            updated_since = timezone.now() - timedelta(days=7)

        try:
            alerts_data = self.provider.list_alerts(updated_since=updated_since)

            for alert_data in alerts_data:
                try:
                    with transaction.atomic():
                        self._upsert_alert(alert_data)
                except Exception as e:
                    logger.error(f"Error syncing alert {alert_data.get('external_id')}: {e}")
                    self.stats['alerts']['errors'] += 1

        except Exception as e:
            logger.error(f"Error listing alerts: {e}")
            raise

    def sync_software(self):
        """Sync software inventory for all online devices."""
        logger.info(f"Syncing software for {self.connection}")

        try:
            # Get all online devices
            devices = RMMDevice.objects.filter(
                connection=self.connection,
                is_online=True
            )

            for device in devices:
                try:
                    software_data = self.provider.list_software(device.external_id)
                    
                    # Track existing software IDs
                    existing_software_ids = set()
                    
                    for sw_data in software_data:
                        try:
                            sw = self._upsert_software(device, sw_data)
                            existing_software_ids.add(sw.id)
                        except Exception as e:
                            logger.error(f"Error syncing software {sw_data.get('name')} for device {device.external_id}: {e}")
                            self.stats['software']['errors'] += 1
                    
                    # Remove software that no longer exists
                    deleted_count = RMMSoftware.objects.filter(
                        device=device
                    ).exclude(
                        id__in=existing_software_ids
                    ).delete()[0]
                    
                    if deleted_count > 0:
                        self.stats['software']['deleted'] += deleted_count
                        logger.debug(f"Removed {deleted_count} software items from device {device.external_id}")
                        
                except Exception as e:
                    logger.error(f"Error syncing software for device {device.external_id}: {e}")

        except Exception as e:
            logger.error(f"Error in software sync: {e}")
            raise

    def _determine_target_organization(self, device_data):
        """
        Determine which organization this device should belong to.

        If import_organizations is enabled, attempts to import/find organization
        from RMM site/client data. Falls back to connection organization.

        Args:
            device_data: Normalized device data from provider

        Returns:
            Organization instance
        """
        if not self.connection.import_organizations:
            # Organization import disabled - use connection's organization
            return self.organization

        # Extract site/client information from device
        site_id = device_data.get('site_id', '') or device_data.get('client_id', '')
        site_name = device_data.get('site_name', '') or device_data.get('client_name', '')

        if not site_id or not site_name:
            # No site/client info available - fallback to connection org
            logger.debug(f"Device {device_data.get('external_id')} has no site/client info, using connection org")
            return self.organization

        # Build site data for organization import
        site_data = {
            'external_id': site_id,
            'name': site_name,
            'description': f"Imported from {self.connection.get_provider_type_display()}",
        }

        try:
            # Check if organization already exists before importing
            from .org_import import find_existing_organization_by_rmm_id
            existing_org = find_existing_organization_by_rmm_id(self.connection, site_id)

            # Attempt to import/find organization
            imported_org = import_organization_from_rmm(self.connection, site_data)

            if imported_org:
                # Track if this was a create or update
                if existing_org:
                    self.stats['organizations']['updated'] += 1
                    logger.debug(f"Updated existing organization {imported_org.name} for site {site_name}")
                else:
                    self.stats['organizations']['created'] += 1
                    logger.info(f"Created new organization {imported_org.name} for site {site_name}")

                logger.info(f"Device {device_data.get('device_name')} mapped to organization {imported_org.name}")
                return imported_org
            else:
                # Import returned None - fallback to connection org
                logger.warning(f"Failed to import organization for site {site_name}, using connection org")
                return self.organization

        except Exception as e:
            logger.error(f"Error importing organization for site {site_name}: {e}")
            self.stats['organizations']['errors'] += 1
            # On error, fallback to connection org
            return self.organization

    def _upsert_device(self, device_data, target_org):
        """
        Create or update RMM device.

        Args:
            device_data: Normalized device data from provider
            target_org: Organization to assign device to
        """
        external_id = device_data['external_id']

        # Check if exists
        device, created = RMMDevice.objects.update_or_create(
            connection=self.connection,
            external_id=external_id,
            defaults={
                'organization': target_org,
                'device_name': device_data['device_name'],
                'device_type': device_data['device_type'],
                'manufacturer': device_data.get('manufacturer', ''),
                'model': device_data.get('model', ''),
                'serial_number': device_data.get('serial_number', ''),
                'os_type': device_data.get('os_type', ''),
                'os_version': device_data.get('os_version', ''),
                'hostname': device_data.get('hostname', ''),
                'ip_address': device_data.get('ip_address'),
                'mac_address': device_data.get('mac_address', ''),
                'latitude': device_data.get('latitude'),
                'longitude': device_data.get('longitude'),
                'is_online': device_data.get('is_online', False),
                'last_seen': device_data.get('last_seen'),
                'raw_data': device_data.get('raw_data', {}),
            }
        )

        if created:
            self.stats['devices']['created'] += 1
        else:
            self.stats['devices']['updated'] += 1

        # Note: ExternalObjectMap not used for RMM devices (PSA-only)
        # RMM devices already have connection FK for tracking

        return device

    def _upsert_alert(self, alert_data):
        """Create or update RMM alert."""
        external_id = alert_data['external_id']
        device_external_id = alert_data.get('device_id', '')

        # Find the device this alert belongs to
        device = None
        if device_external_id:
            try:
                device = RMMDevice.objects.get(
                    connection=self.connection,
                    external_id=device_external_id
                )
            except RMMDevice.DoesNotExist:
                logger.warning(f"Device {device_external_id} not found for alert {external_id}, skipping alert")
                return None

        if not device:
            logger.warning(f"No device specified for alert {external_id}, skipping")
            return None

        # Check if exists
        alert, created = RMMAlert.objects.update_or_create(
            connection=self.connection,
            external_id=external_id,
            defaults={
                'organization': self.organization,
                'device': device,
                'alert_type': alert_data.get('alert_type', ''),
                'message': alert_data.get('message', ''),
                'severity': alert_data.get('severity', 'info'),
                'status': alert_data.get('status', 'active'),
                'triggered_at': alert_data.get('triggered_at'),
                'resolved_at': alert_data.get('resolved_at'),
                'raw_data': alert_data.get('raw_data', {}),
            }
        )

        if created:
            self.stats['alerts']['created'] += 1
        else:
            self.stats['alerts']['updated'] += 1

        # Note: ExternalObjectMap not used for RMM alerts (PSA-only)
        # RMM alerts already have connection FK for tracking

        return alert

    def _upsert_software(self, device, sw_data):
        """Create or update software item for a device."""
        external_id = sw_data.get('external_id', '')
        name = sw_data['name']
        version = sw_data.get('version', '')

        # Use name+version as unique key if external_id not available
        if not external_id:
            external_id = f"{name}_{version}"

        # Check if exists
        software, created = RMMSoftware.objects.update_or_create(
            device=device,
            external_id=external_id,
            defaults={
                'organization': self.organization,
                'name': name,
                'version': version,
                'vendor': sw_data.get('vendor', ''),
                'install_date': sw_data.get('install_date'),
                'raw_data': sw_data.get('raw_data', {}),
            }
        )

        if created:
            self.stats['software']['created'] += 1
        else:
            self.stats['software']['updated'] += 1

        return software

    def _map_device_to_asset(self, device):
        """
        Automatically map RMM device to Asset record.
        Tries to find existing asset by serial number or hostname.
        Creates new asset if not found.
        """
        from assets.models import Asset

        # Skip if already mapped
        if device.linked_asset:
            return

        # Try to find existing asset by serial number
        asset = None
        if device.serial_number:
            asset = Asset.objects.filter(
                organization=self.organization,
                serial_number=device.serial_number
            ).first()

        # Try hostname if serial not found
        if not asset and device.hostname:
            asset = Asset.objects.filter(
                organization=self.organization,
                hostname__iexact=device.hostname
            ).first()

        # Try IP address if still not found
        if not asset and device.ip_address:
            asset = Asset.objects.filter(
                organization=self.organization,
                ip_address=device.ip_address
            ).first()

        # Create new asset if not found
        if not asset:
            # Map device type to asset type
            asset_type_map = {
                'workstation': 'computer',
                'server': 'server',
                'laptop': 'computer',
                'network': 'network',
                'mobile': 'mobile',
                'virtual': 'server',
                'cloud': 'server',
            }
            asset_type = asset_type_map.get(device.device_type, 'other')

            asset = Asset.objects.create(
                organization=self.organization,
                name=device.device_name,
                asset_type=asset_type,
                serial_number=device.serial_number or '',
                manufacturer=device.manufacturer or '',
                model=device.model or '',
                hostname=device.hostname or '',
                ip_address=device.ip_address or '',
                mac_address=device.mac_address or '',
                status='active' if device.is_online else 'offline',
                custom_fields={
                    'rmm_synced': True,
                    'rmm_provider': self.connection.provider_type,
                    'rmm_external_id': device.external_id,
                    'os_type': device.os_type,
                    'os_version': device.os_version,
                    'last_rmm_sync': timezone.now().isoformat(),
                }
            )

            logger.info(f"Created asset {asset.id} from RMM device {device.external_id}")

        # Link device to asset
        device.linked_asset = asset
        device.save()

        self.stats['devices']['mapped'] += 1
        logger.debug(f"Mapped RMM device {device.external_id} to asset {asset.id}")

    def _hash_data(self, data):
        """Generate hash of data for change detection."""
        data_str = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(data_str.encode()).hexdigest()
