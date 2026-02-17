"""
Hudu import service
API Documentation: https://github.com/hudu-team/hudu-api-docs
"""
import logging
from .base import BaseImportService

logger = logging.getLogger('imports')


class HuduImportService(BaseImportService):
    """
    Import data from Hudu.

    Hudu uses API key authentication and has endpoints for:
    - Assets
    - Passwords
    - Articles (documents)
    - Companies
    """

    def _get_auth_headers(self):
        """Hudu uses x-api-key header authentication."""
        return {
            'x-api-key': self.job.source_api_key,
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

    def list_organizations(self):
        """
        List all companies from Hudu.

        Endpoint: GET /api/v1/companies
        Returns: list of dicts with 'id' and 'name'
        """
        organizations = []
        page = 1

        try:
            while True:
                response = self._make_request(
                    'GET',
                    '/api/v1/companies',
                    params={'page': page, 'page_size': 100}
                )
                data = response.json()

                companies = data.get('companies', [])
                if not companies:
                    break

                for company in companies:
                    organizations.append({
                        'id': company['id'],
                        'name': company['name']
                    })

                # Hudu pagination
                page += 1
                if len(companies) < 100:
                    break

            logger.info(f"Found {len(organizations)} companies in Hudu")
            return organizations

        except Exception as e:
            logger.error(f"Failed to list organizations: {e}")
            raise

    def import_assets(self):
        """
        Import assets from Hudu.

        Endpoint: GET /api/v1/assets
        """
        from assets.models import Asset

        self.job.add_log("Importing assets...")
        count = 0
        page = 1

        try:
            while True:
                response = self._make_request(
                    'GET',
                    '/api/v1/assets',
                    params={'page': page, 'page_size': 100}
                )
                data = response.json()

                items = data.get('assets', [])
                if not items:
                    break

                for item in items:
                    try:
                        # Check if already imported
                        if self.get_existing_mapping('asset', item['id']):
                            self.job.items_skipped += 1
                            continue

                        if not self.job.dry_run:
                            asset = self._create_asset_from_hudu(item)
                            self.create_mapping('asset', item['id'], 'Asset', asset.id)

                        count += 1
                        self.job.items_imported += 1

                    except Exception as e:
                        error_msg = f"Failed to import asset {item.get('id')}: {str(e)}"
                        logger.error(error_msg)
                        self.job.add_log(f"ERROR: {error_msg}")
                        self.job.items_failed += 1

                # Hudu pagination
                page += 1
                if len(items) < 100:
                    break

            self.job.add_log(f"Imported {count} assets")
            self.job.save()
            return count

        except Exception as e:
            logger.error(f"Asset import failed: {e}")
            raise

    def _create_asset_from_hudu(self, item):
        """Create Asset from Hudu asset."""
        from assets.models import Asset

        # Get organization for this asset
        # In multi-org imports, look up by company_id
        # In single-org imports, use target organization
        organization = self.organization
        if not organization and item.get('company_id'):
            organization = self.get_or_create_organization(
                source_org_id=item['company_id'],
                source_org_name=item.get('company_name', f"Company {item['company_id']}")
            )

        if not organization:
            raise ValueError(f"Cannot determine organization for asset {item.get('id')}. company_id: {item.get('company_id')}")

        # Map Hudu asset layout name to asset type
        layout_name = item.get('asset_layout_name', '').lower()
        asset_type_map = {
            'computer': 'computer',
            'server': 'server',
            'laptop': 'computer',
            'desktop': 'computer',
            'workstation': 'computer',
            'network': 'network',
            'switch': 'network',
            'router': 'network',
            'firewall': 'network',
            'mobile': 'mobile',
        }

        asset_type = 'other'
        for key, value in asset_type_map.items():
            if key in layout_name:
                asset_type = value
                break

        # Extract fields from asset_fields
        fields = item.get('asset_fields', [])
        field_dict = {f.get('label', '').lower(): f.get('value', '') for f in fields}

        return Asset.objects.create(
            organization=organization,
            name=item.get('name', 'Imported Asset'),
            asset_type=asset_type,
            serial_number=field_dict.get('serial number', ''),
            manufacturer=field_dict.get('manufacturer', ''),
            model=field_dict.get('model', ''),
            hostname=field_dict.get('hostname', ''),
            ip_address=field_dict.get('ip address', ''),
            mac_address=field_dict.get('mac address', ''),
            notes=item.get('notes', ''),
            custom_fields={
                'imported_from': 'hudu',
                'hudu_id': item['id'],
                'asset_layout': item.get('asset_layout_name', ''),
                'all_fields': field_dict,
            }
        )

    def import_passwords(self):
        """
        Import passwords from Hudu.

        Endpoint: GET /api/v1/asset_passwords
        """
        from vault.models import Password

        self.job.add_log("Importing passwords...")
        count = 0
        page = 1

        try:
            while True:
                response = self._make_request(
                    'GET',
                    '/api/v1/asset_passwords',
                    params={'page': page, 'page_size': 100}
                )
                data = response.json()

                items = data.get('asset_passwords', [])
                if not items:
                    break

                for item in items:
                    try:
                        # Check if already imported
                        if self.get_existing_mapping('password', item['id']):
                            self.job.items_skipped += 1
                            continue

                        if not self.job.dry_run:
                            password = self._create_password_from_hudu(item)
                            self.create_mapping('password', item['id'], 'Password', password.id)

                        count += 1
                        self.job.items_imported += 1

                    except Exception as e:
                        error_msg = f"Failed to import password {item.get('id')}: {str(e)}"
                        logger.error(error_msg)
                        self.job.add_log(f"ERROR: {error_msg}")
                        self.job.items_failed += 1

                # Hudu pagination
                page += 1
                if len(items) < 100:
                    break

            self.job.add_log(f"Imported {count} passwords")
            self.job.save()
            return count

        except Exception as e:
            logger.error(f"Password import failed: {e}")
            raise

    def _create_password_from_hudu(self, item):
        """Create Password from Hudu password."""
        from vault.models import Password

        # Get organization for this password
        # In multi-org imports, look up by company_id
        # In single-org imports, use target organization
        organization = self.organization
        if not organization and item.get('company_id'):
            organization = self.get_or_create_organization(
                source_org_id=item['company_id'],
                source_org_name=item.get('company_name', f"Company {item['company_id']}")
            )

        if not organization:
            raise ValueError(f"Cannot determine organization for password {item.get('id')}. company_id: {item.get('company_id')}")

        password = Password.objects.create(
            organization=organization,
            title=item.get('name', 'Imported Password'),
            username=item.get('username', ''),
            url=item.get('url', ''),
            notes=item.get('description', ''),
        )

        # Set encrypted password
        plaintext = item.get('password', '')
        if plaintext:
            password.set_password(plaintext)

        password.save()
        return password

    def import_documents(self):
        """
        Import articles from Hudu.

        Endpoint: GET /api/v1/articles
        """
        from docs.models import Document

        self.job.add_log("Importing documents (articles)...")
        count = 0
        page = 1

        try:
            while True:
                response = self._make_request(
                    'GET',
                    '/api/v1/articles',
                    params={'page': page, 'page_size': 100}
                )
                data = response.json()

                items = data.get('articles', [])
                if not items:
                    break

                for item in items:
                    try:
                        # Check if already imported
                        if self.get_existing_mapping('document', item['id']):
                            self.job.items_skipped += 1
                            continue

                        if not self.job.dry_run:
                            document = self._create_document_from_hudu(item)
                            self.create_mapping('document', item['id'], 'Document', document.id)

                        count += 1
                        self.job.items_imported += 1

                    except Exception as e:
                        error_msg = f"Failed to import document {item.get('id')}: {str(e)}"
                        logger.error(error_msg)
                        self.job.add_log(f"ERROR: {error_msg}")
                        self.job.items_failed += 1

                # Hudu pagination
                page += 1
                if len(items) < 100:
                    break

            self.job.add_log(f"Imported {count} documents")
            self.job.save()
            return count

        except Exception as e:
            logger.error(f"Document import failed: {e}")
            raise

    def _create_document_from_hudu(self, item):
        """Create Document from Hudu article."""
        from docs.models import Document

        return Document.objects.create(
            organization=self.organization,
            title=item.get('name', 'Imported Document'),
            body=item.get('content', ''),
            content_type='markdown',  # Hudu articles are typically Markdown
            created_by=None,  # Will be set to import user
        )

    def import_contacts(self):
        """Import contacts from Hudu (stub - contacts not yet implemented)."""
        self.job.add_log("Skipping contacts import (not implemented)")
        return 0

    def import_locations(self):
        """Import locations/companies from Hudu (stub)."""
        self.job.add_log("Skipping locations import (not implemented)")
        return 0

    def import_networks(self):
        """Import networks from Hudu (stub)."""
        self.job.add_log("Skipping networks import (not implemented)")
        return 0
