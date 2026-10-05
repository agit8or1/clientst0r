"""Object-level checks shared by browser and mobile vault handlers."""
from accounts.permission_utils import user_has_org_perm


def can_access_password(user, password, permission='vault_view_password'):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if password.is_personal:
        return password.personal_owner_id == user.pk
    return user_has_org_perm(user, password.organization_id, permission)
