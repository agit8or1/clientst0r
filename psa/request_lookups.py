"""
Organization-scoped lookups for request-form fields (contact, asset,
location).

Every lookup starts from the portal membership the server worked out for
the request — never an organization, contact or asset id the browser sent —
and is limited to what that person may see:

* location — the customer's own active sites (the same list the general
  portal ticket form offers).
* contact  — the customer's portal admins can search the customer's
  contacts by name; everyone else only sees their own contact record.
* asset    — portal admins can search the customer's assets; everyone else
  only sees devices where they are the primary contact.

Searches need at least two characters and return at most MAX_RESULTS
names, so a lookup can't be used to page through a whole directory.
Results carry a display name only: no email address, phone number,
hostname, IP or serial.

`resolve()` re-applies the same scope when a submission arrives, so a
forged or stale id (another customer's, or outside the person's scope) is
rejected.
"""
from __future__ import annotations

MAX_RESULTS = 10
MIN_QUERY = 2


def _is_portal_admin(ctx):
    m = getattr(ctx, 'membership', None)
    return bool(m is not None and m.is_active and m.is_org_admin
                and m.organization_id == getattr(ctx.organization, 'pk', None))


def _own_contacts(ctx):
    from assets.models import Contact
    email = (getattr(ctx.user, 'email', '') or '').strip()
    if not email or ctx.organization is None:
        return Contact.objects.none()
    return Contact.objects.filter(organization_id=ctx.organization.pk, email__iexact=email)


def _contact_label(c):
    name = f'{c.first_name} {c.last_name}'.strip() or 'Unnamed contact'
    return name[:200]


def _asset_label(a):
    tag = f' ({a.asset_tag})' if a.asset_tag else ''
    return f'{a.name}{tag}'[:200]


def scope_note(field, ctx):
    """One line telling the customer what they can pick from."""
    t = field['type']
    if t == 'location':
        return ''
    if _is_portal_admin(ctx):
        return 'Start typing a name to search.'
    if t == 'contact':
        return 'You can pick yourself, or type the person\'s name.'
    return 'Devices assigned to you are listed; otherwise describe the device.'


def location_options(ctx):
    """[(id, label)] of sites the person may pick."""
    from psa.ticket_site import portal_sites_for
    if ctx is None or ctx.organization is None:
        return []
    return [(loc.pk, loc.name) for loc in portal_sites_for(ctx.organization)[:200]]


def _contact_qs(ctx):
    from assets.models import Contact
    if ctx is None or ctx.organization is None:
        return Contact.objects.none()
    if _is_portal_admin(ctx):
        return Contact.objects.filter(organization_id=ctx.organization.pk)
    return _own_contacts(ctx)


def _asset_qs(ctx):
    from assets.models import Asset
    if ctx is None or ctx.organization is None:
        return Asset.objects.none()
    qs = Asset.objects.filter(organization_id=ctx.organization.pk)
    if _is_portal_admin(ctx):
        return qs
    own = list(_own_contacts(ctx).values_list('pk', flat=True))
    return qs.filter(primary_contact_id__in=own) if own else Asset.objects.none()


def search(field, query, ctx):
    """[{id, label}] for a type-ahead. Admins need MIN_QUERY characters;
    other people get their own short list without searching."""
    from django.db.models import Q
    q = (query or '').strip()[:100]
    t = field.get('type')
    if t == 'location':
        opts = location_options(ctx)
        if q:
            opts = [o for o in opts if q.casefold() in o[1].casefold()]
        return [{'id': i, 'label': label} for i, label in opts[:MAX_RESULTS * 5]]
    admin = _is_portal_admin(ctx)
    if admin and len(q) < MIN_QUERY:
        return []
    if t == 'contact':
        qs = _contact_qs(ctx)
        if admin:
            parts = q.split()
            cond = Q()
            for p in parts[:3]:
                cond &= (Q(first_name__icontains=p) | Q(last_name__icontains=p))
            qs = qs.filter(cond)
        return [{'id': c.pk, 'label': _contact_label(c)}
                for c in qs.order_by('last_name', 'first_name')[:MAX_RESULTS]]
    if t == 'asset':
        qs = _asset_qs(ctx)
        if admin:
            qs = qs.filter(Q(name__icontains=q) | Q(asset_tag__icontains=q))
        return [{'id': a.pk, 'label': _asset_label(a)} for a in qs.order_by('name')[:MAX_RESULTS]]
    return []


def resolve(field, pk, ctx):
    """{id, label} when `pk` is something this person may pick, else None."""
    t = field.get('type')
    if ctx is None or ctx.organization is None:
        return None
    if t == 'location':
        for i, label in location_options(ctx):
            if i == pk:
                return {'id': i, 'label': label}
        return None
    if t == 'contact':
        c = _contact_qs(ctx).filter(pk=pk).first()
        return {'id': c.pk, 'label': _contact_label(c)} if c else None
    if t == 'asset':
        a = _asset_qs(ctx).filter(pk=pk).first()
        return {'id': a.pk, 'label': _asset_label(a)} if a else None
    return None
