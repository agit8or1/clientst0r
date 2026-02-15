"""
Base import service for IT Glue and Hudu migrations
"""
import requests
import logging
from django.utils import timezone
from django.db import transaction
from imports.org_matcher import OrganizationMatcher
from imports.models import OrganizationMapping

logger = logging.getLogger('imports')


class BaseImportService:
    """
    Base class for import services.
    Provides common functionality for IT Glue and Hudu imports.
    """

    def __init__(self, import_job):
        self.job = import_job
        self.organization = import_job.target_organization  # May be None for multi-org imports
        self.session = requests.Session()
        self.session.headers.update(self._get_auth_headers())

        # Initialize organization matcher for multi-org imports
        if not self.organization and self.job.use_fuzzy_matching:
            self.org_matcher = OrganizationMatcher(threshold=self.job.fuzzy_match_threshold)
        else:
            self.org_matcher = None

        # Cache for organization mappings (source_org_id -> Client St0r Organization)
        self.org_map = {}

    def _get_auth_headers(self):
        """Get authentication headers. Override in subclass."""
        raise NotImplementedError

    def _make_request(self, method, endpoint, **kwargs):
        """Make API request with error handling."""
        url = f"{self.job.source_url.rstrip('/')}{endpoint}"

        try:
            response = self.session.request(method, url, timeout=30, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            logger.error(f"API request failed: {method} {url} - {e}")
            raise

    def run_import(self):
        """
        Run the complete import process.
        Returns: dict with statistics
        """
        try:
            self.job.mark_running()
            self.job.add_log(f"Starting import from {self.job.get_source_type_display()}")

            stats = {
                'organizations': 0,
                'assets': 0,
                'passwords': 0,
                'documents': 0,
                'contacts': 0,
                'locations': 0,
                'networks': 0,
                'errors': []
            }

            # Import organizations first (if multi-org import)
            if not self.organization:
                stats['organizations'] = self.import_organizations()

            # Import in order (dependencies first)
            if self.job.import_locations:
                stats['locations'] = self.import_locations()

            if self.job.import_contacts:
                stats['contacts'] = self.import_contacts()

            if self.job.import_assets:
                stats['assets'] = self.import_assets()

            if self.job.import_passwords:
                stats['passwords'] = self.import_passwords()

            if self.job.import_documents:
                stats['documents'] = self.import_documents()

            if self.job.import_networks:
                stats['networks'] = self.import_networks()

            # Update job statistics
            self.job.total_items = sum(v for k, v in stats.items() if k != 'errors')
            self.job.items_imported = self.job.total_items

            self.job.add_log(f"Import completed successfully")
            self.job.add_log(f"Total items imported: {self.job.items_imported}")
            self.job.mark_completed()

            return stats

        except Exception as e:
            error_msg = str(e)
            logger.exception(f"Import failed: {error_msg}")
            self.job.mark_failed(error_msg)
            self.job.add_log(f"ERROR: {error_msg}")
            raise

    def get_or_create_organization(self, source_org_id, source_org_name):
        """
        Get or create organization based on source data.

        If target_organization is set, always returns that.
        Otherwise, uses fuzzy matching to find/create organization.

        Args:
            source_org_id: Organization ID in source system
            source_org_name: Organization name in source system

        Returns:
            Organization instance
        """
        # If single-org import, always use target organization
        if self.organization:
            return self.organization

        # Check cache first
        if source_org_id in self.org_map:
            return self.org_map[source_org_id]

        # Check if already mapped in this import
        existing_mapping = OrganizationMapping.objects.filter(
            import_job=self.job,
            source_id=str(source_org_id)
        ).first()

        if existing_mapping:
            self.org_map[source_org_id] = existing_mapping.organization
            return existing_mapping.organization

        # Match or create organization
        org, was_created, match_score = self.org_matcher.match_or_create(
            source_name=source_org_name,
            source_id=source_org_id,
            dry_run=self.job.dry_run
        )

        # Create mapping (even in dry run for tracking)
        if not self.job.dry_run or was_created:
            OrganizationMapping.objects.create(
                organization=org if not self.job.dry_run else None,
                import_job=self.job,
                source_id=str(source_org_id),
                source_name=source_org_name,
                was_created=was_created,
                match_score=match_score
            )

        # Update statistics
        if was_created:
            self.job.organizations_created += 1
        else:
            self.job.organizations_matched += 1
        self.job.save(update_fields=['organizations_created', 'organizations_matched'])

        # Cache the mapping
        self.org_map[source_org_id] = org

        return org

    def list_organizations(self):
        """
        List all organizations/companies from source.
        Override in subclass for actual implementation.

        Returns:
            list of dicts with keys: id, name
        """
        raise NotImplementedError("Subclass must implement list_organizations")

    def import_organizations(self):
        """
        Import all organizations from source system.
        Only runs if target_organization is None.

        Returns:
            Number of organizations processed
        """
        if self.organization:
            # Single-org import, skip organization import
            return 0

        self.job.add_log("Importing organizations...")
        count = 0

        try:
            orgs = self.list_organizations()

            for org_data in orgs:
                try:
                    self.get_or_create_organization(
                        source_org_id=org_data['id'],
                        source_org_name=org_data['name']
                    )
                    count += 1
                except Exception as e:
                    logger.error(f"Failed to import organization {org_data.get('name')}: {e}")
                    self.job.items_failed += 1

            self.job.add_log(f"Imported {count} organizations ({self.job.organizations_created} created, {self.job.organizations_matched} matched)")
            self.job.save()
            return count

        except Exception as e:
            logger.error(f"Organization import failed: {e}")
            raise

    def import_assets(self):
        """Import configuration items/assets. Override in subclass."""
        raise NotImplementedError

    def import_passwords(self):
        """Import passwords. Override in subclass."""
        raise NotImplementedError

    def import_documents(self):
        """Import documents/articles. Override in subclass."""
        raise NotImplementedError

    def import_contacts(self):
        """Import contacts. Override in subclass."""
        return 0  # Optional

    def import_locations(self):
        """Import locations. Override in subclass."""
        return 0  # Optional

    def import_networks(self):
        """Import networks. Override in subclass."""
        return 0  # Optional

    def create_mapping(self, source_type, source_id, target_model, target_id):
        """Create import mapping to prevent duplicates."""
        from imports.models import ImportMapping

        ImportMapping.objects.get_or_create(
            import_job=self.job,
            source_type=source_type,
            source_id=str(source_id),
            defaults={
                'target_model': target_model,
                'target_id': target_id,
            }
        )

    def get_existing_mapping(self, source_type, source_id):
        """Check if item was already imported."""
        from imports.models import ImportMapping

        try:
            mapping = ImportMapping.objects.get(
                import_job=self.job,
                source_type=source_type,
                source_id=str(source_id)
            )
            return mapping
        except ImportMapping.DoesNotExist:
            return None
