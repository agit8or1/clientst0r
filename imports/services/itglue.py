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

    def list_organizations(self):
        """
        List all organizations from IT Glue.

        Endpoint: GET /organizations
        Returns: list of dicts with 'id' and 'name'
        """
        organizations = []
        page = 1

        try:
            while True:
                response = self._make_request(
                    'GET',
                    '/organizations',
                    params={'page[number]': page, 'page[size]': 50}
                )
                data = response.json()

                orgs = data.get('data', [])
                if not orgs:
                    break

                for org in orgs:
                    attributes = org.get('attributes', {})
                    organizations.append({
                        'id': org['id'],
                        'name': attributes.get('name', '')
                    })

                # IT Glue pagination - check if there's a next page
                meta = data.get('meta', {})
                if not meta.get('next-page'):
                    break

                page += 1

            logger.info(f"Found {len(organizations)} organizations in IT Glue")
            return organizations

        except Exception as e:
            logger.error(f"Failed to list organizations: {e}")
            raise

    def _paged(self, endpoint):
        """Yield every item of a paginated IT Glue collection."""
        page = 1
        while True:
            response = self._make_request(
                'GET',
                endpoint,
                params={'page[number]': page, 'page[size]': 50}
            )
            data = response.json()

            items = data.get('data', [])
            if not items:
                break
            yield from items

            # Check for next page
            if not data.get('links', {}).get('next'):
                break
            page += 1

    def _record_org(self, item):
        """Organization for an IT Glue record (its ``organization-id``)."""
        attrs = item.get('attributes', {}) or {}
        return self.resolve_record_organization(
            attrs.get('organization-id'), attrs.get('organization-name', ''))

    def _import_collection(self, endpoint, source_type, noun, create):
        self.job.add_log(f"Importing {noun}...")
        count = 0
        for item in self._paged(endpoint):
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
        Import configuration items from IT Glue.

        Endpoint: GET /configurations
        """
        return self._import_collection(
            '/configurations', 'asset', 'assets (configuration items)',
            self._create_asset_from_itglue)

    def _create_asset_from_itglue(self, item, organization):
        """Create Asset from IT Glue configuration item."""
        from assets.models import Asset

        attrs = item.get('attributes', {})

        # Map IT Glue configuration type to asset type
        config_type = (attrs.get('configuration-type-name') or '').lower()
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

        fields = dict(
            organization=organization,
            name=attrs.get('name') or 'Imported Asset',
            asset_type=asset_type,
            serial_number=attrs.get('serial-number') or '',
            manufacturer=attrs.get('manufacturer-name') or '',
            model=attrs.get('model-name') or '',
            hostname=attrs.get('hostname') or '',
            mac_address=attrs.get('mac-address') or '',
            notes=attrs.get('notes') or '',
            custom_fields={
                'imported_from': 'itglue',
                'itglue_id': item['id'],
                'configuration_type': attrs.get('configuration-type-name', ''),
            }
        )
        ip = self.clean_ip(attrs.get('primary-ip'))
        if ip:
            fields['ip_address'] = ip
        return Asset.objects.create(**fields)

    def import_passwords(self):
        """
        Import passwords from IT Glue.

        Endpoint: GET /passwords
        """
        return self._import_collection(
            '/passwords', 'password', 'passwords', self._create_password_from_itglue)

    def _create_password_from_itglue(self, item, organization):
        """Create Password from IT Glue password (encrypted via set_password)."""
        from vault.models import Password

        attrs = item.get('attributes', {})

        password = Password(
            organization=organization,
            title=attrs.get('name') or 'Imported Password',
            username=attrs.get('username') or '',
            url=attrs.get('url') or '',
            notes=attrs.get('notes') or '',
            created_by=self.job.started_by,
        )

        # Set encrypted password
        plaintext = attrs.get('password') or ''
        if plaintext:
            password.set_password(plaintext)

        password.save()
        return password

    def import_documents(self):
        """
        Import documents from IT Glue.

        Endpoint: GET /documents
        """
        return self._import_collection(
            '/documents', 'document', 'documents', self._create_document_from_itglue)

    def _create_document_from_itglue(self, item, organization):
        """Create Document from IT Glue document."""
        from docs.models import Document

        attrs = item.get('attributes', {})
        title = attrs.get('name') or 'Imported Document'

        return Document.objects.create(
            organization=organization,
            title=title,
            slug=self.unique_document_slug(organization, title),
            body=attrs.get('body') or '',
            content_type='markdown',  # ITGlue documents are typically Markdown
            created_by=self.job.started_by,
        )

    def _canon(self, source_type):
        from imports.migration.normalize import itglue_canonical
        return lambda item: itglue_canonical(source_type, item, {}, {})

    def import_contacts(self):
        """Import contacts from IT Glue (GET /contacts)."""
        return self.import_canonical_collection(
            self._paged('/contacts'), 'contact', 'contacts', self._canon('contact'), self._record_org)

    def import_locations(self):
        """Import locations from IT Glue (GET /locations)."""
        return self.import_canonical_collection(
            self._paged('/locations'), 'location', 'locations', self._canon('location'), self._record_org)

    def _flexible_assets(self, type_id, type_name):
        page = 1
        while True:
            data = self._make_request('GET', '/flexible_assets', params={
                'filter[flexible_asset_type_id]': type_id, 'page[number]': page,
                'page[size]': 50}).json()
            items = data.get('data', [])
            if not items:
                return
            for item in items:
                item = dict(item)
                item['_type_name'] = type_name
                yield item
            if not data.get('links', {}).get('next'):
                return
            page += 1

    def import_networks(self):
        """Import networks from IT Glue: flexible assets whose type is a
        network type (IT Glue has no dedicated networks endpoint)."""
        from imports.migration.normalize import itglue_flexible_kind
        items = []
        for t in self._paged('/flexible_asset_types'):
            name = (t.get('attributes') or {}).get('name', '')
            if itglue_flexible_kind(name, {}) == 'network':
                items.extend(self._flexible_assets(t.get('id'), name))
        return self.import_canonical_collection(
            items, 'network', 'networks (network flexible assets)', self._canon('flexible_asset'),
            self._record_org)
