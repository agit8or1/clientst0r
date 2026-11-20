"""Who may configure single sign-on: superusers, and MSP staff whose global
role holds `manage_sso_settings` (critical). Customer memberships never
grant it: SSO is an install-wide setting."""


def can_manage_sso(user) -> bool:
    if user is None or not getattr(user, 'is_authenticated', False) or not user.is_active:
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, 'profile', None)
    if profile is None or not profile.is_staff_user():
        return False
    role = profile.global_role_template
    if role is not None and getattr(role, 'manage_sso_settings', False):
        return True
    # An access group covering every customer counts like a global role.
    from accounts.access_groups import holds_msp_wide
    return holds_msp_wide(user, 'manage_sso_settings')
