"""Who may see and change what. Customer isolation lives here.

Every data row is scoped by `organization` (the customer); connections by the
owning `organization`. `allowed_orgs` is the set of customers where the user
holds the flag (accounts.permission_utils.orgs_with_perm: None = every
customer), subsidiaries included.
"""
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


def scoped(qs, user, perm=VIEW, field='organization'):
    return qs.filter(**{f'{field}__in': allowed_orgs(user, perm)})
