"""Template checks for vault entries shown outside the vault (v3.17.653)."""
from django import template

from accounts.permission_utils import has_perm_for_org

register = template.Library()


@register.filter
def vault_visible(password, user):
    """True when `user` may see this entry's title: vault_view in its customer.

    A process can be global or linked across customers, so a stage's linked
    credential is checked where it is rendered, not where it was chosen.
    """
    if password is None or getattr(password, 'is_personal', False):
        return False
    return has_perm_for_org(user, password.organization_id, 'vault_view')
