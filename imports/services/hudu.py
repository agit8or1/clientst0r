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

    def _paged(self, endpoint, key):
        """Yield every item of a paginated Hudu collection."""
        page = 1
        while True:
            response = self._make_request(
                'GET',
                endpoint,
                params={'page': page, 'page_size': 100}
            )
            data = response.json()

            items = data.get(key, [])
            if not items:
                break
            yield from items

            # Hudu pagination: a short page is the last one
            page += 1
            if len(items) < 100:
                break

    def _record_org(self, item):
        """Organization for a Hudu record (its ``company_id``)."""
        company_id = item.get('company_id')
        name = item.get('company_name') or ''
        if company_id not in (None, '') and not name:
            name = self.source_org_names.get(str(company_id), '') or f"Company {company_id}"
        return self.resolve_record_organization(company_id, name)

    def _import_collection(self, endpoint, key, source_type, noun, create):
        self.job.add_log(f"Importing {noun}...")
        count = 0
        for item in self._paged(endpoint, key):
            result = self.process_record(
                source_type, item.get('id'),
                create_fn=lambda item=item: create(item, self._record_org(item)),
                validate_fn=lambda item=item: self._record_org(item),
                label=f"{source_type} {item.get('id')}",
            )
            if result == 'imported':
                count += 1
        self.job.add_log(f"Imported {count} {noun}")
        self.job.save()
        return count

    def import_assets(self):
        """
        Import assets from Hudu.

        Endpoint: GET /api/v1/assets
        """
        return self._import_collection(
            '/api/v1/assets', 'assets', 'asset', 'assets', self._create_asset_from_hudu)

    def _create_asset_from_hudu(self, item, organization):
        """Create Asset from Hudu asset."""
        from assets.models import Asset

        # Map Hudu asset layout name to asset type
        layout_name = (item.get('asset_layout_name') or '').lower()
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
        fields = item.get('asset_fields', []) or []
        field_dict = {(f.get('label') or '').lower(): f.get('value') or '' for f in fields}

        data = dict(
            organization=organization,
            name=item.get('name') or 'Imported Asset',
            asset_type=asset_type,
            serial_number=str(field_dict.get('serial number', '')),
            manufacturer=str(field_dict.get('manufacturer', '')),
            model=str(field_dict.get('model', '')),
            hostname=str(field_dict.get('hostname', '')),
            mac_address=str(field_dict.get('mac address', '')),
            notes=item.get('notes') or '',
            custom_fields={
                'imported_from': 'hudu',
                'hudu_id': item['id'],
                'asset_layout': item.get('asset_layout_name', ''),
                'all_fields': field_dict,
            }
        )
        ip = self.clean_ip(field_dict.get('ip address'))
        if ip:
            data['ip_address'] = ip
        return Asset.objects.create(**data)

    def import_passwords(self):
        """
        Import passwords from Hudu.

        Endpoint: GET /api/v1/asset_passwords
        """
        return self._import_collection(
            '/api/v1/asset_passwords', 'asset_passwords', 'password', 'passwords',
            self._create_password_from_hudu)

    def _create_password_from_hudu(self, item, organization):
        """Create Password from Hudu password (encrypted via set_password)."""
        from vault.models import Password

        password = Password(
            organization=organization,
            title=item.get('name') or 'Imported Password',
            username=item.get('username') or '',
            url=item.get('url') or '',
            notes=item.get('description') or '',
            created_by=self.job.started_by,
        )

        # Set encrypted password
        plaintext = item.get('password') or ''
        if plaintext:
            password.set_password(plaintext)

        password.save()
        return password

    def import_documents(self):
        """
        Import articles from Hudu.

        Endpoint: GET /api/v1/articles

        In an all-organizations import, articles without a company (Hudu's
        global knowledge base) fail with a clear message rather than being
        created with no organization.
        """
        return self._import_collection(
            '/api/v1/articles', 'articles', 'document', 'documents (articles)',
            self._create_document_from_hudu)

    def _create_document_from_hudu(self, item, organization):
        """Create Document from Hudu article."""
        from docs.models import Document

        title = item.get('name') or 'Imported Document'
        return Document.objects.create(
            organization=organization,
            title=title,
            slug=self.unique_document_slug(organization, title),
            body=item.get('content') or '',
            content_type='markdown',  # Hudu articles are typically Markdown
            created_by=self.job.started_by,
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
