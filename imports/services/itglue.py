"""
IT Glue import service
API Documentation: https://api.itglue.com/developer/
"""
import logging
from .base import BaseImportService

logger = logging.getLogger('imports')


class ITGlueImportService(BaseImportService):
    """
    Import data from IT Glue.

    IT Glue uses API key authentication and has endpoints for:
    - Configuration Items (assets)
    - Passwords
    - Documents
    - Contacts
    - Locations
    """

    def _get_auth_headers(self):
        """IT Glue uses x-api-key header authentication."""
        return {
            'x-api-key': self.job.source_api_key,
            'Content-Type': 'application/vnd.api+json',
            'Accept': 'application/vnd.api+json'
        }

    def import_assets(self):
        """
        Import configuration items from IT Glue.

        Endpoint: GET /configurations
        """
        from assets.models import Asset

        self.job.add_log("Importing assets (configuration items)...")
        count = 0
        page = 1

        try:
            while True:
                response = self._make_request(
                    'GET',
                    '/configurations',
                    params={'page[number]': page, 'page[size]': 50}
                )
                data = response.json()

                items = data.get('data', [])
                if not items:
                    break

                for item in items:
                    try:
                        # Check if already imported
                        if self.get_existing_mapping('asset', item['id']):
                            self.job.items_skipped += 1
                            continue

                        if not self.job.dry_run:
                            asset = self._create_asset_from_itglue(item)
                            self.create_mapping('asset', item['id'], 'Asset', asset.id)

                        count += 1
                        self.job.items_imported += 1

                    except Exception as e:
                        logger.error(f"Failed to import asset {item.get('id')}: {e}")
                        self.job.items_failed += 1

                # Check for next page
                if not data.get('links', {}).get('next'):
                    break
                page += 1

            self.job.add_log(f"Imported {count} assets")
            self.job.save()
            return count

        except Exception as e:
            logger.error(f"Asset import failed: {e}")
            raise

    def _create_asset_from_itglue(self, item):
        """Create Asset from IT Glue configuration item."""
        from assets.models import Asset

        attrs = item.get('attributes', {})

        # Map IT Glue configuration type to asset type
        config_type = attrs.get('configuration-type-name', '').lower()
        asset_type_map = {
            'computer': 'computer',
            'server': 'server',
            'laptop': 'computer',
            'desktop': 'computer',
            'workstation': 'computer',
            'network device': 'network',
            'switch': 'network',
            'router': 'network',
            'firewall': 'network',
            'mobile': 'mobile',
            'phone': 'mobile',
        }

        asset_type = 'other'
        for key, value in asset_type_map.items():
            if key in config_type:
                asset_type = value
                break

        return Asset.objects.create(
            organization=self.organization,
            name=attrs.get('name', 'Imported Asset'),
            asset_type=asset_type,
            serial_number=attrs.get('serial-number', ''),
            manufacturer=attrs.get('manufacturer-name', ''),
            model=attrs.get('model-name', ''),
            hostname=attrs.get('hostname', ''),
            ip_address=attrs.get('primary-ip', ''),
            mac_address=attrs.get('mac-address', ''),
            notes=attrs.get('notes', ''),
            custom_fields={
                'imported_from': 'itglue',
                'itglue_id': item['id'],
                'configuration_type': attrs.get('configuration-type-name', ''),
            }
        )

    def import_passwords(self):
        """
        Import passwords from IT Glue.

        Endpoint: GET /passwords
        """
        from vault.models import Password

        self.job.add_log("Importing passwords...")
        count = 0
        page = 1

        try:
            while True:
                response = self._make_request(
                    'GET',
                    '/passwords',
                    params={'page[number]': page, 'page[size]': 50}
                )
                data = response.json()

                items = data.get('data', [])
                if not items:
                    break

                for item in items:
                    try:
                        # Check if already imported
                        if self.get_existing_mapping('password', item['id']):
                            self.job.items_skipped += 1
                            continue

                        if not self.job.dry_run:
                            password = self._create_password_from_itglue(item)
                            self.create_mapping('password', item['id'], 'Password', password.id)

                        count += 1
                        self.job.items_imported += 1

                    except Exception as e:
                        logger.error(f"Failed to import password {item.get('id')}: {e}")
                        self.job.items_failed += 1

                # Check for next page
                if not data.get('links', {}).get('next'):
                    break
                page += 1

            self.job.add_log(f"Imported {count} passwords")
            self.job.save()
            return count

        except Exception as e:
            logger.error(f"Password import failed: {e}")
            raise

    def _create_password_from_itglue(self, item):
        """Create Password from IT Glue password."""
        from vault.models import Password

        attrs = item.get('attributes', {})

        password = Password.objects.create(
            organization=self.organization,
            title=attrs.get('name', 'Imported Password'),
            username=attrs.get('username', ''),
            url=attrs.get('url', ''),
            notes=attrs.get('notes', ''),
        )

        # Set encrypted password
        plaintext = attrs.get('password', '')
        if plaintext:
            password.set_password(plaintext)

        password.save()
        return password

    def import_documents(self):
        """
        Import documents from IT Glue.

        Endpoint: GET /documents
        """
        from docs.models import Document

        self.job.add_log("Importing documents...")
        count = 0
        page = 1

        try:
            while True:
                response = self._make_request(
                    'GET',
                    '/documents',
                    params={'page[number]': page, 'page[size]': 50}
                )
                data = response.json()

                items = data.get('data', [])
                if not items:
                    break

                for item in items:
                    try:
                        # Check if already imported
                        if self.get_existing_mapping('document', item['id']):
                            self.job.items_skipped += 1
                            continue

                        if not self.job.dry_run:
                            document = self._create_document_from_itglue(item)
                            self.create_mapping('document', item['id'], 'Document', document.id)

                        count += 1
                        self.job.items_imported += 1

                    except Exception as e:
                        logger.error(f"Failed to import document {item.get('id')}: {e}")
                        self.job.items_failed += 1

                # Check for next page
                if not data.get('links', {}).get('next'):
                    break
                page += 1

            self.job.add_log(f"Imported {count} documents")
            self.job.save()
            return count

        except Exception as e:
            logger.error(f"Document import failed: {e}")
            raise

    def _create_document_from_itglue(self, item):
        """Create Document from IT Glue document."""
        from docs.models import Document

        attrs = item.get('attributes', {})

        return Document.objects.create(
            organization=self.organization,
            title=attrs.get('name', 'Imported Document'),
            content=attrs.get('body', ''),
            created_by=None,  # Will be set to import user
        )

    def import_contacts(self):
        """Import contacts from IT Glue (stub - contacts not yet implemented)."""
        self.job.add_log("Skipping contacts import (not implemented)")
        return 0

    def import_locations(self):
        """Import locations from IT Glue (stub - locations import not yet implemented)."""
        self.job.add_log("Skipping locations import (not implemented)")
        return 0

    def import_networks(self):
        """Import networks from IT Glue (stub - networks import not yet implemented)."""
        self.job.add_log("Skipping networks import (not implemented)")
        return 0
