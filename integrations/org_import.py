"""
Organization import utilities for PSA/RMM integrations
"""
from django.utils.text import slugify
from core.models import Organization
from audit.models import AuditLog
from integrations.models import ExternalObjectMap
import logging

logger = logging.getLogger('integrations')


def create_inherited_memberships(new_org, parent_org):
    """
    Create memberships on newly imported organization by inheriting
    from parent organization's owners.

    When an organization is imported from PSA/RMM, this function automatically
    grants access to users who own the parent organization (the organization
    that owns the PSA/RMM connection).

    Args:
        new_org: The newly created/imported Organization
        parent_org: The parent Organization that owns the integration connection
    """
    from accounts.models import Membership

    # Find all owner memberships in parent organization
    parent_owners = Membership.objects.filter(
        organization=parent_org,
        role='owner',
        is_active=True
    )

    created_count = 0
    for parent_membership in parent_owners:
        # Create owner membership on imported org if doesn't exist
        membership, created = Membership.objects.get_or_create(
            user=parent_membership.user,
            organization=new_org,
            defaults={
                'role': 'owner',
                'is_active': True,
                'invited_by': parent_membership.user,
            }
        )

        if created:
            created_count += 1
            logger.info(
                f"Created owner membership for {parent_membership.user.username} "
                f"on imported organization {new_org.name}"
            )

    return created_count


def import_organization_from_psa(connection, company_data):
    """
    Import or update an organization from PSA company data.

    Args:
        connection: PSAConnection instance
        company_data: dict with company information from PSA
            Required keys: 'external_id', 'name'
            Optional keys: 'status', 'phone', 'address', 'website', etc.

    Returns:
        Organization instance or None
    """
    if not connection.import_organizations:
        return None

    external_id = str(company_data.get('external_id', ''))
    company_name = company_data.get('name', '').strip()

    if not external_id or not company_name:
        logger.warning(f"Missing required company data for import: {company_data}")
        return None

    # Apply prefix if configured
    if connection.org_name_prefix:
        display_name = f"{connection.org_name_prefix}{company_name}"
    else:
        display_name = company_name

    # Generate slug from company name
    base_slug = slugify(company_name)
    if not base_slug:
        base_slug = f"company-{external_id}"

    # Check if organization already exists (by custom field or slug)
    org = find_existing_organization_by_psa_id(connection, external_id)

    if org:
        # Update existing organization
        org.name = display_name
        org.save()

        # Update ExternalObjectMap
        ExternalObjectMap.objects.update_or_create(
            connection=connection,
            external_type='company',
            external_id=str(external_id),
            defaults={
                'organization': org,
                'local_type': 'organization',
                'local_id': org.id,
            }
        )

        logger.info(f"Updated organization {org.slug} from PSA company {company_name}")

        AuditLog.objects.create(
            event_type='psa_org_updated',
            description=f'Updated organization {org.slug} from PSA: {company_name}',
            metadata={
                'psa_provider': connection.provider_type,
                'psa_company_id': external_id,
                'organization_id': org.id,
            }
        )

        return org

    else:
        # Create new organization
        # Ensure slug is unique
        slug = base_slug
        counter = 1
        while Organization.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1

        org = Organization.objects.create(
            name=display_name,
            slug=slug,
            is_active=connection.org_import_as_active,
        )

        logger.info(f"Created new organization {org.slug} from PSA company {company_name}")

        # Create inherited memberships from parent organization
        memberships_created = create_inherited_memberships(org, connection.organization)
        if memberships_created > 0:
            logger.info(f"Created {memberships_created} inherited memberships for {org.name}")

        # Create ExternalObjectMap to track this organization
        ExternalObjectMap.objects.create(
            connection=connection,
            external_type='company',
            external_id=str(external_id),
            organization=org,
            local_type='organization',
            local_id=org.id,
        )

        AuditLog.objects.create(
            event_type='psa_org_created',
            description=f'Created organization {org.slug} from PSA: {company_name}',
            metadata={
                'psa_provider': connection.provider_type,
                'psa_company_id': external_id,
                'organization_id': org.id,
                'memberships_created': memberships_created,
            }
        )

        return org


def import_organization_from_rmm(connection, site_data):
    """
    Import or update an organization from RMM site/client data.

    Args:
        connection: RMMConnection instance
        site_data: dict with site/client information from RMM
            Required keys: 'external_id', 'name'
            Optional keys: 'description', 'contact', etc.

    Returns:
        Organization instance or None
    """
    if not connection.import_organizations:
        return None

    external_id = str(site_data.get('external_id', ''))
    site_name = site_data.get('name', '').strip()

    if not external_id or not site_name:
        logger.warning(f"Missing required site data for import: {site_data}")
        return None

    # Apply prefix if configured
    if connection.org_name_prefix:
        display_name = f"{connection.org_name_prefix}{site_name}"
    else:
        display_name = site_name

    # Generate slug from site name
    base_slug = slugify(site_name)
    if not base_slug:
        base_slug = f"site-{external_id}"

    # Check if organization already exists by name (with prefix)
    # Note: RMM connections don't use ExternalObjectMap (PSA-only)
    org = Organization.objects.filter(name=display_name).first()

    if not org:
        # Try slug match as fallback
        org = Organization.objects.filter(slug=base_slug).first()

    if org:
        # Update existing organization
        org.name = display_name
        org.save()

        logger.info(f"Updated organization {org.slug} from RMM site {site_name}")

        AuditLog.objects.create(
            action='sync',
            object_type='organization',
            object_id=org.id,
            object_repr=org.name,
            description=f'Updated organization from RMM: {site_name} ({connection.provider_type}, site ID: {external_id})',
            organization=org
        )

        return org

    else:
        # Create new organization
        # Ensure slug is unique
        slug = base_slug
        counter = 1
        while Organization.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1

        org = Organization.objects.create(
            name=display_name,
            slug=slug,
            is_active=connection.org_import_as_active,
        )

        logger.info(f"Created new organization {org.slug} from RMM site {site_name}")

        # Create inherited memberships from parent organization
        memberships_created = create_inherited_memberships(org, connection.organization)
        if memberships_created > 0:
            logger.info(f"Created {memberships_created} inherited memberships for {org.name}")

        AuditLog.objects.create(
            action='sync',
            object_type='organization',
            object_id=org.id,
            object_repr=org.name,
            description=f'Created organization from RMM: {site_name} ({connection.provider_type}, site ID: {external_id}, {memberships_created} memberships)',
            organization=org
        )

        return org


def find_existing_organization_by_psa_id(connection, external_id):
    """
    Find existing organization by PSA company ID.

    Searches ExternalObjectMap for matching PSA company ID.

    Returns:
        Organization instance or None
    """
    # Search for ExternalObjectMap with matching PSA company ID
    mapping = ExternalObjectMap.objects.filter(
        connection=connection,
        external_type='company',
        external_id=str(external_id),
        local_type='organization'
    ).first()

    if mapping:
        # Get the organization by local_id
        try:
            return Organization.objects.get(id=mapping.local_id)
        except Organization.DoesNotExist:
            # Orphaned mapping, delete it
            logger.warning(f"Found orphaned ExternalObjectMap for organization ID {mapping.local_id}, deleting")
            mapping.delete()
            return None

    return None


def find_existing_organization_by_rmm_id(connection, external_id):
    """
    Find existing organization by RMM site ID.

    For RMM connections, we don't use ExternalObjectMap (PSA-only).
    Instead, search by organization name/slug that would have been created.

    Returns:
        Organization instance or None
    """
    # RMM connections don't use ExternalObjectMap - just return None
    # Organizations will be matched by name in import_organization_from_rmm
    return None


def bulk_import_organizations_from_psa(connection, companies_data):
    """
    Bulk import organizations from PSA companies.

    Args:
        connection: PSAConnection instance
        companies_data: list of company dicts from PSA

    Returns:
        dict with statistics: {'created': int, 'updated': int, 'errors': int}
    """
    stats = {'created': 0, 'updated': 0, 'errors': 0}

    for company_data in companies_data:
        try:
            # Check if organization already exists
            external_id = str(company_data.get('external_id', ''))
            existing = find_existing_organization_by_psa_id(connection, external_id)

            org = import_organization_from_psa(connection, company_data)
            if org:
                if existing:
                    stats['updated'] += 1
                else:
                    stats['created'] += 1
        except Exception as e:
            logger.error(f"Error importing PSA company {company_data.get('name')}: {e}")
            stats['errors'] += 1

    return stats


def bulk_import_organizations_from_rmm(connection, sites_data):
    """
    Bulk import organizations from RMM sites.

    Args:
        connection: RMMConnection instance
        sites_data: list of site dicts from RMM

    Returns:
        dict with statistics: {'created': int, 'updated': int, 'errors': int}
    """
    stats = {'created': 0, 'updated': 0, 'errors': 0}

    for site_data in sites_data:
        try:
            # Check if organization already exists
            external_id = str(site_data.get('external_id', ''))
            existing = find_existing_organization_by_rmm_id(connection, external_id)

            org = import_organization_from_rmm(connection, site_data)
            if org:
                if existing:
                    stats['updated'] += 1
                else:
                    stats['created'] += 1
        except Exception as e:
            logger.error(f"Error importing RMM site {site_data.get('name')}: {e}")
            stats['errors'] += 1

    return stats
