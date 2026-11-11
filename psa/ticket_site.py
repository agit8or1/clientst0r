"""Which of the customer's sites (locations.Location) a ticket is about.

A ticket's site is optional. It is filled at intake when it can be worked
out, in this order:

  1. the ticket's asset, when the asset's hardware record names a site;
  2. the requester contact's default site (the ticket's contact, or the
     contact at this customer whose email matches the requester email);
  3. the portal user's default site (the user who created the ticket);
  4. the customer's only site, when it has exactly one active site.

Anything else leaves it blank. A technician can set or clear it on the ticket
at any time, and can remember that choice as the requester's default site.

Only a site that belongs to the ticket's customer (its own, or a shared site
the customer is associated with) is ever stored. Nothing here changes the
ticket's customer, access, assignment or SLA.
"""
from __future__ import annotations

import logging

from django.db.models import Q

logger = logging.getLogger('psa.ticket_site')

SOURCE_MANUAL = 'manual'
SOURCE_ASSET = 'asset'
SOURCE_CONTACT = 'contact'
SOURCE_REQUESTER = 'requester'
SOURCE_ONLY_SITE = 'only_site'
SOURCE_PORTAL = 'portal'
SOURCE_CHOICES = [
    ('', 'Not set'),
    (SOURCE_MANUAL, 'Set on the ticket'),
    (SOURCE_ASSET, "From the asset's site"),
    (SOURCE_CONTACT, "Contact's default site"),
    (SOURCE_REQUESTER, "Portal user's default site"),
    (SOURCE_ONLY_SITE, "The customer's only site"),
    (SOURCE_PORTAL, 'Chosen by the requester in the portal'),
]

INACTIVE_STATUSES = ('inactive', 'closed')


def sites_for(organization):
    """The customer's sites a ticket may name, primary first."""
    from locations.models import Location
    if organization is None or getattr(organization, 'pk', None) is None:
        return Location.objects.none()
    return (Location.objects
            .filter(Q(organization_id=organization.pk)
                    | Q(is_shared=True, associated_organizations__id=organization.pk))
            .exclude(status__in=INACTIVE_STATUSES)
            .distinct()
            .order_by('-is_primary', 'name'))


def portal_sites_for(organization):
    """Sites a portal user of `organization` may pick on a new ticket: the
    customer's own active sites only (never another customer's shared site,
    even one associated with this customer)."""
    from locations.models import Location
    if organization is None or getattr(organization, 'pk', None) is None:
        return Location.objects.none()
    return (Location.objects.filter(organization_id=organization.pk)
            .exclude(status__in=INACTIVE_STATUSES).order_by('-is_primary', 'name'))


def portal_default_site(organization, user):
    """The portal user's default site at this customer, if it is still one
    they may pick."""
    loc = _default_for(organization, user=user)
    if loc is None or not portal_sites_for(organization).filter(pk=loc.pk).exists():
        return None
    return loc


def set_default(organization, location, *, contact=None, user=None, actor=None):
    """Set (or with location=None clear) a contact's or portal user's default
    site at `organization`. Raises ValueError for a site or requester that
    does not belong to the customer."""
    from psa.models import RequesterDefaultSite
    if (contact is None) == (user is None):
        raise ValueError('Pick a contact or a portal user.')
    if contact is not None and contact.organization_id != organization.pk:
        raise ValueError('That contact belongs to a different customer.')
    if user is not None:
        from accounts.models import Membership
        if not Membership.objects.filter(user=user, organization=organization, is_active=True).exists():
            raise ValueError('That user is not a member of this customer.')
    key = {'contact': contact} if contact is not None else {'user': user}
    if location is None:
        RequesterDefaultSite.objects.filter(organization=organization, **key).delete()
        return None
    if not site_allowed(organization, location) or location.status in INACTIVE_STATUSES:
        raise ValueError("That site doesn't belong to this customer.")
    row, _ = RequesterDefaultSite.objects.update_or_create(
        organization=organization, **key, defaults={'location': location, 'updated_by': actor})
    return row


def site_allowed(organization, location) -> bool:
    if location is None or organization is None:
        return False
    if location.organization_id == organization.pk:
        return True
    return bool(location.is_shared
                and location.associated_organizations.filter(pk=organization.pk).exists())


def _asset_site(ticket):
    asset = getattr(ticket, 'related_asset', None) if ticket.related_asset_id else None
    if asset is None or asset.organization_id != ticket.organization_id:
        return None
    try:
        hw = asset.hardware
    except Exception:  # noqa: BLE001 — no hardware record
        return None
    return hw.site if getattr(hw, 'site_id', None) else None


def _contact(ticket):
    if ticket.contact_id:
        c = ticket.contact
        return c if c.organization_id == ticket.organization_id else None
    email = (ticket.requester_email or '').strip()
    if not email:
        return None
    from assets.models import Contact
    return (Contact.objects.filter(organization_id=ticket.organization_id, email__iexact=email)
            .order_by('pk').first())


def _default_for(organization, *, contact=None, user=None):
    from psa.models import RequesterDefaultSite
    qs = RequesterDefaultSite.objects.filter(organization=organization).select_related('location')
    if contact is not None:
        row = qs.filter(contact=contact).first()
    elif user is not None:
        row = qs.filter(user=user).first()
    else:
        row = None
    return row.location if row else None


def infer_site(ticket):
    """(location, source) for a ticket being created, or (None, '')."""
    org = ticket.organization

    def contact_site():
        contact = _contact(ticket)
        return _default_for(org, contact=contact) if contact is not None else None

    candidates = [(lambda: _asset_site(ticket), SOURCE_ASSET), (contact_site, SOURCE_CONTACT)]
    if ticket.created_by_id:
        candidates.append((lambda: _default_for(org, user=ticket.created_by), SOURCE_REQUESTER))
    for get, source in candidates:
        try:
            loc = get()
        except Exception:  # noqa: BLE001 — a lookup problem never blocks intake
            logger.exception('site lookup (%s) failed', source)
            loc = None
        if loc is not None and site_allowed(org, loc) and loc.status not in INACTIVE_STATUSES:
            return loc, source
    sites = list(sites_for(org)[:2])
    if len(sites) == 1:
        return sites[0], SOURCE_ONLY_SITE
    return None, ''


def fill_on_create(ticket):
    """Called before a new ticket is first saved. Leaves an explicit site alone
    (after checking it belongs to the customer)."""
    if getattr(ticket, 'organization_id', None) is None:
        return
    if ticket.site_id:
        if not site_allowed(ticket.organization, ticket.site):
            ticket.site = None
            ticket.site_source = ''
        elif not ticket.site_source:
            ticket.site_source = SOURCE_MANUAL
        return
    loc, source = infer_site(ticket)
    if loc is not None:
        ticket.site = loc
        ticket.site_source = source


def remember_default(ticket, location, actor=None):
    """Store `location` as the requester's default site at this customer: for
    the ticket's contact when it has one, otherwise for the portal user who
    created it. Returns a short description of what was remembered, or ''."""
    from psa.models import RequesterDefaultSite
    from psa.visibility import is_msp_staff
    org = ticket.organization
    if location is None or not site_allowed(org, location):
        return ''
    contact = _contact(ticket)
    if contact is not None:
        RequesterDefaultSite.objects.update_or_create(
            organization=org, contact=contact,
            defaults={'location': location, 'updated_by': actor})
        return f'default site for contact {contact}'
    user = ticket.created_by if ticket.created_by_id else None
    if user is not None and not is_msp_staff(user):
        RequesterDefaultSite.objects.update_or_create(
            organization=org, user=user,
            defaults={'location': location, 'updated_by': actor})
        return f'default site for portal user {user.get_username()}'
    return ''
