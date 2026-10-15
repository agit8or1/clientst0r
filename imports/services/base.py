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


class _DryRunRollback(Exception):
    """Raised to discard everything a dry run wrote."""


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

        # Initialize organization matcher for multi-org imports. Without fuzzy
        # matching, organizations are matched by exact (case-insensitive) name.
        if not self.organization and self.job.use_fuzzy_matching:
            self.org_matcher = OrganizationMatcher(threshold=self.job.fuzzy_match_threshold)
        else:
            self.org_matcher = None

        # Cache for organization mappings (str(source_org_id) -> Organization)
        self.org_map = {}
        # str(source_org_id) -> name, filled by import_organizations()
        self.source_org_names = {}
        # Non-record errors (e.g. an organization that could not be created).
        self.errors = []

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

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run_import(self):
        """
        Run the complete import process.

        Counts are real: ``items_imported`` / ``items_skipped`` /
        ``items_failed`` are incremented per record and ``total_items`` is
        their sum. The final status comes from ``ImportJob.finish()``:
        completed / completed_with_errors / failed.

        A dry run executes inside a transaction that is always rolled back, so
        even if something slips past the per-record ``dry_run`` guards nothing
        but the job row (its counts and log) is persisted.

        Returns: dict with statistics
        """
        stats = {
            'organizations': 0,
            'assets': 0,
            'passwords': 0,
            'documents': 0,
            'contacts': 0,
            'locations': 0,
            'networks': 0,
            'errors': self.errors,
        }
        try:
            self.job.mark_running()
            self.job.reset_counters()
            self.job.add_log(
                f"Starting import from {self.job.get_source_type_display()}"
                + (" (DRY RUN - nothing will be saved)" if self.job.dry_run else ""))

            if self.job.dry_run:
                try:
                    with transaction.atomic():
                        self._run_steps(stats)
                        raise _DryRunRollback()
                except _DryRunRollback:
                    pass
                # The rollback also reverted the job row's intermediate saves;
                # write the in-memory state (counts + log) back.
                self.job.save()
            else:
                self._run_steps(stats)

            status = self.job.finish(extra_errors=len(self.errors))
            self.job.add_log(
                f"Import finished: {self.job.get_status_display()} - "
                f"{self.job.items_imported} imported, {self.job.items_skipped} skipped, "
                f"{self.job.items_failed} failed (of {self.job.total_items})"
                + (f"; {len(self.errors)} other error(s)" if self.errors else "")
            )
            stats['status'] = status
            return stats

        except Exception as e:
            error_msg = str(e)
            logger.exception(f"Import failed: {error_msg}")
            if self.job.dry_run:
                # Persist the log/counts written before the failure.
                self.job.save()
            self.job.mark_failed(error_msg)
            self.job.add_log(f"ERROR: {error_msg}")
            raise

    def _run_steps(self, stats):
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

    # ------------------------------------------------------------------
    # Organizations
    # ------------------------------------------------------------------

    def get_or_create_organization(self, source_org_id, source_org_name):
        """
        Get or create organization based on source data.

        If target_organization is set, always returns that.
        Otherwise, uses fuzzy matching (or an exact, case-insensitive name
        match when fuzzy matching is off) to find or create the organization.

        In a dry run nothing is written: a would-be-created organization is
        returned unsaved and no OrganizationMapping is recorded.

        Returns:
            Organization instance
        """
        # If single-org import, always use target organization
        if self.organization:
            return self.organization

        key = str(source_org_id)

        # Check cache first
        if key in self.org_map:
            return self.org_map[key]

        # Already mapped in this job (e.g. a re-run of a failed job)
        existing_mapping = OrganizationMapping.objects.filter(
            import_job=self.job,
            source_id=key,
        ).select_related('organization').first()

        if existing_mapping:
            self.org_map[key] = existing_mapping.organization
            return existing_mapping.organization

        source_org_name = (source_org_name or '').strip() or f"Imported organization {key}"

        # Match or create organization
        if self.org_matcher is not None:
            org, was_created, match_score = self.org_matcher.match_or_create(
                source_name=source_org_name,
                source_id=key,
                dry_run=self.job.dry_run
            )
        else:
            org, was_created, match_score = self._exact_match_or_create(source_org_name, key)

        if not self.job.dry_run:
            OrganizationMapping.objects.create(
                organization=org,
                import_job=self.job,
                source_id=key,
                source_name=source_org_name,
                was_created=was_created,
                match_score=match_score
            )
            if was_created:
                # Recorded so rollback can remove it again (only if nothing
                # else has come to reference it).
                self.create_mapping('organization', key, org, organization=org,
                                    source_organization_id=key)

        # Update statistics
        if was_created:
            self.job.organizations_created += 1
        else:
            self.job.organizations_matched += 1
        self.job.save(update_fields=['organizations_created', 'organizations_matched'])

        self.org_map[key] = org
        return org

    def _exact_match_or_create(self, name, source_id):
        from core.models import Organization
        existing = Organization.objects.filter(name__iexact=name).first()
        if existing:
            return existing, False, 100
        if self.job.dry_run:
            return Organization(name=name), True, None
        org = Organization.objects.create(name=name, description=f"Imported from {source_id}")
        return org, True, None

    def resolve_record_organization(self, source_org_id, source_org_name=''):
        """Organization a source record belongs to.

        Single-org import: the target organization. All-organizations import:
        the organization mapped from the record's own source organization.
        Raises ValueError when the record carries no source organization.
        """
        if self.organization:
            return self.organization
        if source_org_id in (None, ''):
            raise ValueError(
                "record has no source organization; an all-organizations import only "
                "imports records that belong to an organization")
        key = str(source_org_id)
        name = source_org_name or self.source_org_names.get(key, '')
        return self.get_or_create_organization(key, name)

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
                self.source_org_names[str(org_data['id'])] = org_data.get('name', '')
                try:
                    with transaction.atomic():
                        self.get_or_create_organization(
                            source_org_id=org_data['id'],
                            source_org_name=org_data['name']
                        )
                    count += 1
                except Exception as e:
                    msg = f"Failed to import organization {org_data.get('name')!r}: {e}"
                    logger.error(msg)
                    self.job.add_log(f"ERROR: {msg}")
                    self.errors.append(msg)

            self.job.add_log(f"Imported {count} organizations ({self.job.organizations_created} created, {self.job.organizations_matched} matched)")
            self.job.save()
            return count

        except Exception as e:
            logger.error(f"Organization import failed: {e}")
            raise

    # ------------------------------------------------------------------
    # Records
    # ------------------------------------------------------------------

    def process_record(self, source_type, source_id, create_fn, label=None, validate_fn=None):
        """Import one source record with consistent bookkeeping.

        ``create_fn()`` builds and saves the target object (only called on a
        real run) and returns it. ``validate_fn()`` (optional) runs instead on
        a dry run - typically resolving the record's organization - so a dry
        run reports the same failures a real run would, without writing.

        Duplicate detection, the mapping row and the imported / skipped /
        failed counters are handled here. The object and its mapping are
        written in one savepoint, so a failure never leaves an unmapped record
        behind (which rollback could not find).

        Returns 'imported', 'skipped' or 'failed'.
        """
        label = label or f"{source_type} {source_id}"
        try:
            if self.get_existing_mapping(source_type, source_id):
                self.job.items_skipped += 1
                return 'skipped'

            if self.job.dry_run:
                if validate_fn is not None:
                    validate_fn()
            else:
                with transaction.atomic():
                    obj = create_fn()
                    self.create_mapping(source_type, source_id, obj)
            self.job.items_imported += 1
            return 'imported'
        except Exception as e:
            error_msg = f"Failed to import {label}: {e}"
            logger.error(error_msg)
            self.job.add_log(f"ERROR: {error_msg}")
            self.job.items_failed += 1
            return 'failed'

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

    def create_mapping(self, source_type, source_id, target, *, organization=None,
                       source_organization_id=''):
        """Record that ``target`` was created from ``source_id``.

        Stores the target's organization and its ``updated_at`` as of now, so
        rollback can tell records edited after the import from untouched ones.
        """
        from imports.models import ImportMapping

        if organization is None:
            if target.__class__.__name__ == 'Organization':
                organization = target
            else:
                organization = getattr(target, 'organization', None)
        mapping, _created = ImportMapping.objects.get_or_create(
            import_job=self.job,
            source_type=source_type,
            source_id=str(source_id),
            defaults={
                'target_model': target.__class__.__name__,
                'target_id': target.pk,
                'target_organization': organization,
                'target_updated_at': getattr(target, 'updated_at', None),
                'source_organization_id': str(source_organization_id or ''),
            }
        )
        return mapping

    def get_existing_mapping(self, source_type, source_id):
        """Return a mapping showing this source record was already imported.

        Always checks the current job (a re-run of a failed job must not
        duplicate what the first attempt created). When skip_duplicates is
        enabled, also checks earlier real runs of the same source type that
        still own their records (completed / completed with errors / partially
        rolled back) - scoped to the target organization for single-org jobs.
        A mapping whose target has since been deleted does not count.
        """
        from django.db.models import Q
        from imports.models import ImportJob, ImportMapping

        own = ImportMapping.objects.filter(
            import_job=self.job, source_type=source_type, source_id=str(source_id))
        for mapping in own:
            if mapping.target_exists():
                return mapping

        if getattr(self.job, 'skip_duplicates', False):
            qs = ImportMapping.objects.filter(
                source_type=source_type,
                source_id=str(source_id),
                import_job__source_type=self.job.source_type,
                import_job__status__in=ImportJob.DEDUPE_STATUSES,
                import_job__dry_run=False,
            ).exclude(import_job=self.job)
            if self.job.target_organization_id:
                qs = qs.filter(
                    Q(import_job__target_organization=self.job.target_organization_id)
                    | Q(target_organization=self.job.target_organization_id))
            for mapping in qs.order_by('-created_at')[:5]:
                if mapping.target_exists():
                    return mapping
        return None

    @staticmethod
    def clean_ip(value):
        """Return ``value`` if it is a valid IPv4/IPv6 address, else None."""
        from django.core.exceptions import ValidationError
        from django.core.validators import validate_ipv46_address
        value = (value or '').strip() if isinstance(value, str) else value
        if not value:
            return None
        try:
            validate_ipv46_address(value)
        except ValidationError:
            return None
        return value

    @staticmethod
    def unique_document_slug(organization, title):
        """Documents are unique per (organization, slug), and source systems
        often hold several documents with the same title in one organization."""
        from django.utils.text import slugify
        from docs.models import Document

        base = (slugify(title or '') or 'document')[:240]
        slug = base
        n = 2
        while Document.objects.filter(organization=organization, slug=slug).exists():
            slug = f"{base}-{n}"
            n += 1
        return slug
