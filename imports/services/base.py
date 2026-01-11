"""
Base import service for IT Glue and Hudu migrations
"""
import requests
import logging
from django.utils import timezone
from django.db import transaction

logger = logging.getLogger('imports')


class BaseImportService:
    """
    Base class for import services.
    Provides common functionality for IT Glue and Hudu imports.
    """

    def __init__(self, import_job):
        self.job = import_job
        self.organization = import_job.target_organization
        self.session = requests.Session()
        self.session.headers.update(self._get_auth_headers())

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
                'assets': 0,
                'passwords': 0,
                'documents': 0,
                'contacts': 0,
                'locations': 0,
                'networks': 0,
                'errors': []
            }

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
