"""Who may see and change what. Customer isolation lives here.

One install serves one MSP; an Organization is a customer of that MSP. Every
data row is scoped by `organization` (the customer); NULL means "MSP-wide /
not mapped to a customer yet" and is visible only to users whose role reaches
every customer (`has_global_reach`). `allowed_orgs` is the set of customers
where the user holds the flag (accounts.permission_utils.orgs_with_perm),
subsidiaries included.
"""
from django.db.models import Q

from accounts.permission_utils import orgs_with_perm
from core.models import Organization

VIEW = 'view_backup_status'
MANAGE = 'manage_backup_integrations'


def allowed_orgs(user, perm=VIEW):
    """Organization queryset the user holds `perm` for."""
    ids = orgs_with_perm(user, perm)
    if ids is None:
        return Organization.objects.all()
    return Organization.objects.filter(pk__in=ids)


def has_global_reach(user, perm=VIEW):
    """True when `perm` holds for every customer (so MSP-wide rows are theirs)."""
    return orgs_with_perm(user, perm) is None


def visible(user, perm=VIEW, field='organization'):
    """Q for rows whose customer the user reaches (+ unmapped rows for MSP-wide users)."""
    q = Q(**{f'{field}__in': allowed_orgs(user, perm)})
    if has_global_reach(user, perm):
        q |= Q(**{f'{field}__isnull': True})
    return q


def can_act_on(user, organization_id, perm=MANAGE):
    if organization_id is None:
        return has_global_reach(user, perm)
    return allowed_orgs(user, perm).filter(pk=organization_id).exists()
