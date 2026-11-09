"""
Organization import utilities for PSA/RMM integrations
"""
from django.utils.text import slugify
from django.contrib.contenttypes.models import ContentType
from core.models import Organization
from audit.models import AuditLog
from integrations.models import ExternalObjectMap
import logging


def _eom_filter(connection, **kwargs):
    """
    Return an ExternalObjectMap queryset filtered by connection.

    GenericForeignKey cannot be used in ORM filter() calls directly.
    Use connection_type (ContentType) + connection_id instead.
    """
    ct = ContentType.objects.get_for_model(connection)
    return ExternalObjectMap.objects.filter(
        connection_type=ct,
        connection_id=connection.pk,
        **kwargs,
    )

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
        ct = ContentType.objects.get_for_model(connection)
        ExternalObjectMap.objects.update_or_create(
            connection_type=ct,
            connection_id=connection.pk,
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

        # Populate additional fields from PSA company data
        if company_data.get('phone'):
            org.phone = company_data['phone']
        if company_data.get('website'):
            org.website = company_data['website']
        if company_data.get('email'):
            org.email = company_data['email']

        # Parse address components if available
        if company_data.get('address'):
            org.street_address = company_data.get('address', '')
        if company_data.get('city'):
            org.city = company_data['city']
        if company_data.get('state'):
            org.state = company_data['state']
        if company_data.get('zip'):
            org.postal_code = company_data['zip']
        if company_data.get('country'):
            org.country = company_data['country']

        org.save()

        logger.info(f"Created new organization {org.slug} from PSA company {company_name}")

        # Create inherited memberships from parent organization
        memberships_created = create_inherited_memberships(org, connection.organization)
        if memberships_created > 0:
            logger.info(f"Created {memberships_created} inherited memberships for {org.name}")

        # Create ExternalObjectMap to track this organization
        ct = ContentType.objects.get_for_model(connection)
        ExternalObjectMap.objects.create(
            connection_type=ct,
            connection_id=connection.pk,
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


def import_organization_from_rmm(connection, site_data, *, force=False):
    """
    Import or update an organization from RMM site/client data.

    Args:
        connection: RMMConnection instance
        site_data: dict with site/client information from RMM
            Keys: 'external_id', 'name' (site), 'client_name', 'client_id'
            Optional keys: 'description', 'contact', etc.

    Returns:
        Organization instance or None
    """
    if not (connection.import_organizations or force):
        return None

    # PREFER client_name over site_name for organization naming
    # This avoids issues where multiple clients have sites in the same location
    # Example: "Bob's Storage" (client) not "melbourne" (site)
    client_name = site_data.get('client_name', '').strip()
    site_name = site_data.get('name', '').strip()

    # Use client name if available, otherwise fall back to site name
    org_name = client_name if client_name else site_name

    # The customer's identity: its real ID, or — for payloads that carry
    # only a name — the name, recorded as a name mapping (never as an ID).
    from .rmm_association import _map_value, customer_identity, map_customer, mapped_organization
    identity = customer_identity({'client_id': site_data.get('client_id', '') or site_data.get('external_id', ''),
                                  'client_name': org_name})
    external_id = identity.client_id or identity.client_name if identity else ''

    if not identity or not org_name:
        logger.warning(f"Missing required data for RMM import: {site_data}")
        return None

    # Apply prefix if configured
    if connection.org_name_prefix:
        display_name = f"{connection.org_name_prefix}{org_name}"
    else:
        display_name = org_name

    # Generate slug from org name (client or site)
    base_slug = slugify(org_name)
    if not base_slug:
        base_slug = f"rmm-{external_id}"

    # Check if organization already exists by external_id mapping
    # Use ExternalObjectMap for reliable tracking (prevents slug collisions)
    org = mapped_organization(connection, identity)

    if not org:
        # Organizations created before mappings were recorded are found by
        # their exact name — but only when exactly one has it and no other
        # customer of this connection is already mapped to it. A slug match
        # ("Main Office" vs "main-office") is too loose to trust.
        same_name = list(Organization.objects.filter(name=display_name)[:2])
        if len(same_name) == 1 and not _eom_filter(
                connection, local_type='organization', local_id=same_name[0].pk,
        ).exclude(external_id=_map_value(identity)).exists():
            org = same_name[0]

    if org:
        # Update existing organization
        org.name = display_name
        org.save()

        map_customer(connection, identity, org)

        logger.info(f"Updated organization {org.slug} from RMM: {org_name} (client: {client_name}, site: {site_name})")

        AuditLog.objects.create(
            action='sync',
            object_type='organization',
            object_id=org.id,
            object_repr=org.name,
            description=f'Updated organization from RMM: {org_name} ({connection.provider_type}, ID: {external_id})',
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

        logger.info(f"Created new organization {org.slug} from RMM: {org_name} (client: {client_name or 'N/A'}, site: {site_name or 'N/A'})")

        # Create inherited memberships from parent organization
        memberships_created = create_inherited_memberships(org, connection.organization)
        if memberships_created > 0:
            logger.info(f"Created {memberships_created} inherited memberships for {org.name}")

        map_customer(connection, identity, org)

        AuditLog.objects.create(
            action='sync',
            object_type='organization',
            object_id=org.id,
            object_repr=org.name,
            description=f'Created organization from RMM: {org_name} (client_name: {client_name}, site_name: {site_name}, {connection.provider_type}, ID: {external_id}, {memberships_created} memberships)',
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
    mapping = _eom_filter(
        connection,
        external_type='company',
        external_id=str(external_id),
        local_type='organization',
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
    Find existing organization by RMM client/site ID.

    Searches ExternalObjectMap for matching RMM client ID.
    This ensures stable mapping and prevents slug collisions.

    Returns:
        Organization instance or None
    """
    if not external_id:
        return None

    # Search for ExternalObjectMap with matching RMM client/site ID
    # Use 'rmm_client' or 'rmm_site' as external_type
    for external_type in ['rmm_client', 'rmm_site']:
        mapping = _eom_filter(
            connection,
            external_type=external_type,
            external_id=str(external_id),
            local_type='organization',
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
