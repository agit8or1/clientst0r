"""
Organization import utilities for PSA/RMM integrations
"""
from django.utils.text import slugify
from core.models import Organization
from audit.models import AuditLog
import logging

logger = logging.getLogger('integrations')


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

        # Update custom fields to track PSA linkage
        if not org.custom_fields:
            org.custom_fields = {}
        org.custom_fields['psa_provider'] = connection.provider_type
        org.custom_fields['psa_company_id'] = external_id
        org.custom_fields['psa_connection_id'] = connection.id

        # Update optional fields from PSA
        if 'phone' in company_data and company_data['phone']:
            org.custom_fields['psa_phone'] = company_data['phone']
        if 'address' in company_data and company_data['address']:
            org.custom_fields['psa_address'] = company_data['address']
        if 'website' in company_data and company_data['website']:
            org.custom_fields['psa_website'] = company_data['website']

        org.save()

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
            custom_fields={
                'psa_provider': connection.provider_type,
                'psa_company_id': external_id,
                'psa_connection_id': connection.id,
                'psa_phone': company_data.get('phone', ''),
                'psa_address': company_data.get('address', ''),
                'psa_website': company_data.get('website', ''),
                'imported_from_psa': True,
            }
        )

        logger.info(f"Created new organization {org.slug} from PSA company {company_name}")

        AuditLog.objects.create(
            event_type='psa_org_created',
            description=f'Created organization {org.slug} from PSA: {company_name}',
            metadata={
                'psa_provider': connection.provider_type,
                'psa_company_id': external_id,
                'organization_id': org.id,
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

    # Check if organization already exists (by custom field or slug)
    org = find_existing_organization_by_rmm_id(connection, external_id)

    if org:
        # Update existing organization
        org.name = display_name

        # Update custom fields to track RMM linkage
        if not org.custom_fields:
            org.custom_fields = {}
        org.custom_fields['rmm_provider'] = connection.provider_type
        org.custom_fields['rmm_site_id'] = external_id
        org.custom_fields['rmm_connection_id'] = connection.id

        # Update optional fields from RMM
        if 'description' in site_data and site_data['description']:
            org.custom_fields['rmm_description'] = site_data['description']
        if 'contact' in site_data and site_data['contact']:
            org.custom_fields['rmm_contact'] = site_data['contact']

        org.save()

        logger.info(f"Updated organization {org.slug} from RMM site {site_name}")

        AuditLog.objects.create(
            event_type='rmm_org_updated',
            description=f'Updated organization {org.slug} from RMM: {site_name}',
            metadata={
                'rmm_provider': connection.provider_type,
                'rmm_site_id': external_id,
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
            custom_fields={
                'rmm_provider': connection.provider_type,
                'rmm_site_id': external_id,
                'rmm_connection_id': connection.id,
                'rmm_description': site_data.get('description', ''),
                'rmm_contact': site_data.get('contact', ''),
                'imported_from_rmm': True,
            }
        )

        logger.info(f"Created new organization {org.slug} from RMM site {site_name}")

        AuditLog.objects.create(
            event_type='rmm_org_created',
            description=f'Created organization {org.slug} from RMM: {site_name}',
            metadata={
                'rmm_provider': connection.provider_type,
                'rmm_site_id': external_id,
                'organization_id': org.id,
            }
        )

        return org


def find_existing_organization_by_psa_id(connection, external_id):
    """
    Find existing organization by PSA company ID.

    Searches custom_fields for psa_company_id matching the external_id
    and psa_connection_id matching the connection.

    Returns:
        Organization instance or None
    """
    # Search for organizations with matching PSA company ID
    orgs = Organization.objects.filter(
        custom_fields__psa_company_id=str(external_id),
        custom_fields__psa_connection_id=connection.id
    )

    return orgs.first()


def find_existing_organization_by_rmm_id(connection, external_id):
    """
    Find existing organization by RMM site ID.

    Searches custom_fields for rmm_site_id matching the external_id
    and rmm_connection_id matching the connection.

    Returns:
        Organization instance or None
    """
    # Search for organizations with matching RMM site ID
    orgs = Organization.objects.filter(
        custom_fields__rmm_site_id=str(external_id),
        custom_fields__rmm_connection_id=connection.id
    )

    return orgs.first()


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
