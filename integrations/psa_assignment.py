"""Which customer a PSA company (and its contacts and tickets) belongs to.

A customer's own PSA connection keeps the rule it always had: companies go to
the organization imported for them, else to the connection's own customer;
contacts and tickets go to the connection's customer.

A platform-owned PSA connection has no customer of its own. Each company is
assigned to a customer by a mapping (the organization mapping page, or
organization import); a company nobody mapped stays unassigned
(organization empty) and its contacts and tickets with it, so no customer
sees them. Contacts and tickets follow their company's customer.
"""
from django.db import transaction


def mapping_targets(connection):
    """Organizations a company of this connection may be mapped to: any
    active customer for a platform-owned connection, the owning customer and
    its subsidiaries for a customer's own connection."""
    from core.models import Organization
    from core.utils import descendant_org_ids
    qs = Organization.objects.filter(is_active=True)
    if connection.organization_id is not None:
        qs = qs.filter(pk__in=descendant_org_ids(connection.organization_id))
    return qs.order_by('name')


@transaction.atomic
def assign_company(company, org, user=None):
    """Put a platform PSA company — and the contacts and tickets that hang
    off it — with `org` (None unassigns). Audit-logged."""
    from audit.models import AuditLog
    from .models import PSAContact, PSATicket
    previous = company.organization
    company.organization = org
    company.save(update_fields=['organization', 'last_synced_at'])
    contacts = PSAContact.objects.filter(company=company).update(organization=org)
    tickets = PSATicket.objects.filter(company=company).update(organization=org)
    for o in {previous, org}:
        AuditLog.log(user=user, action='update', organization=o, object_type='psa_company',
                     object_id=company.pk, object_repr=company.name[:255],
                     description=(f'PSA company "{company.name}" assigned to {org.name if org else "no customer"}'
                                  f' (was {previous.name if previous else "unassigned"})'),
                     extra_data={'connection_id': company.connection_id, 'contacts': contacts,
                                 'tickets': tickets})
    return contacts, tickets
