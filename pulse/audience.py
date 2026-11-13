"""Who a pulse check goes to.

Organizations: every active client (``all_organizations``; internal and
subcontractor organizations are left out) or the chosen ones. Inactive
organizations never receive a send.

People, within those organizations:
  * ``all``      — every active portal user (active membership, active user
                   with an e-mail address); with ``include_contacts`` also the
                   organization's contacts that have an e-mail address.
  * ``roles``    — portal users whose membership matches one of the chosen
                   role groups (owners, managers/administrators, editors,
                   read-only) or holds one of the chosen named roles as its
                   primary or an additional role.
  * ``specific`` — the chosen users (at each target organization they are an
                   active member of) and the chosen contacts (at their own
                   organization, when it is a target).

MSP staff are never recipients, even when they hold a membership at a client.
Each (organization, e-mail) is one recipient; a portal user wins over a
contact with the same address. Opted-out addresses are dropped and counted.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Q


@dataclass
class Recipient:
    organization: object
    email: str
    name: str
    user: object = None
    contact: object = None


EXCLUDED_ORG_TYPES = ('internal', 'subcontractor')


def target_organizations(check):
    from core.models import Organization
    if check.all_organizations:
        qs = Organization.objects.exclude(organization_type__in=EXCLUDED_ORG_TYPES)
    else:
        qs = check.organizations.all()
    return qs.filter(is_active=True).order_by('name')


def membership_matches(membership, groups, template_ids):
    """Whether a membership falls in the chosen role groups / named roles."""
    groups = set(groups or ())
    template_ids = set(template_ids or ())
    if 'owners' in groups and membership.is_owner():
        return True
    if 'admins' in groups and membership.can_admin() and not membership.is_owner():
        return True
    if not membership.role_template_id:
        if 'editors' in groups and membership.role == 'editor':
            return True
        if 'readonly' in groups and membership.role == 'readonly':
            return True
    if template_ids:
        if membership.role_template_id in template_ids:
            return True
        if any(r.pk in template_ids for r in membership.additional_roles.all()):
            return True
    return False


def _display_name(user):
    full = (user.get_full_name() or '').strip()
    return full or user.username


def resolve(check):
    """``(recipients, opted_out_count)`` for a send of `check` now."""
    from accounts.models import Membership
    from assets.models import Contact
    from .models import PulseCheck, PulseOptOut

    orgs = list(target_organizations(check))
    org_ids = [o.pk for o in orgs]
    if not org_ids:
        return [], 0

    members = (Membership.objects
               .filter(organization_id__in=org_ids, is_active=True,
                       user__is_active=True, user__email__gt='')
               .exclude(user__in=_staff_users())
               .select_related('user', 'organization', 'role_template')
               .prefetch_related('additional_roles')
               .order_by('organization__name', 'user__email'))
    contacts = Contact.objects.none()

    if check.audience == PulseCheck.AUDIENCE_ALL:
        if check.include_contacts:
            contacts = Contact.objects.filter(organization_id__in=org_ids, email__gt='')
    elif check.audience == PulseCheck.AUDIENCE_ROLES:
        groups = list(check.audience_roles or [])
        template_ids = set(check.audience_role_templates.values_list('pk', flat=True))
        members = [m for m in members if membership_matches(m, groups, template_ids)]
    elif check.audience == PulseCheck.AUDIENCE_SPECIFIC:
        members = members.filter(user__in=check.specific_users.all())
        contacts = check.specific_contacts.filter(organization_id__in=org_ids, email__gt='')
    else:
        return [], 0

    seen = {}
    for m in members:
        key = (m.organization_id, m.user.email.strip().lower())
        if key not in seen:
            seen[key] = Recipient(m.organization, m.user.email.strip(), _display_name(m.user), user=m.user)
    for c in contacts.select_related('organization'):
        key = (c.organization_id, c.email.strip().lower())
        if key not in seen:
            name = f'{c.first_name} {c.last_name}'.strip()
            seen[key] = Recipient(c.organization, c.email.strip(), name, contact=c)

    opted = set(PulseOptOut.objects.filter(
        email__in={r.email.lower() for r in seen.values()}).values_list('email', flat=True))
    out, skipped = [], 0
    for r in seen.values():
        if r.email.lower() in opted:
            skipped += 1
            continue
        out.append(r)
    out.sort(key=lambda r: (r.organization.name, r.email.lower()))
    return out, skipped


def _staff_users():
    from django.contrib.auth.models import User
    from psa.visibility import msp_staff_q
    return User.objects.filter(msp_staff_q())
