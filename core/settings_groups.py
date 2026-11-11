"""Settings sidebar groups — one source of truth for the order and gating.

`templates/core/_settings_menu.html` renders these five groups; the navbar's
Admin dropdown can link each group to the first page the viewer may open via
``landing_url_name(group_key, user, psa_enabled)`` (or the
``{% settings_group_url %}`` tag in ``core.templatetags.settings_menu``).

Each entry is ``(active_page, url_name, gate)``. ``gate`` is one of:

* ``'superuser'``   — the view is ``user_passes_test(is_superuser)``
* ``'staff'``       — staff or superuser
* ``'login'``       — any signed-in user (the view narrows further itself)
* ``'psa'``         — superuser *and* the PSA feature toggle is on

Keep this list in the same order as the template; a test checks they agree.
"""
from django.urls import reverse

GROUP_ORDER = ('system', 'security', 'access', 'integrations', 'mobile')

GROUP_LABELS = {
    'system': 'System',
    'security': 'Security',
    'access': 'Organizations & Access',
    'integrations': 'Integrations',
    'mobile': 'Mobile',
}

SETTINGS_GROUPS = {
    'system': (
        ('general', 'core:settings_general', 'superuser'),
        ('updates', 'core:system_updates', 'superuser'),
        ('system_status', 'core:system_status', 'superuser'),
        ('features', 'core:settings_features', 'superuser'),
        ('modules', 'core:settings_modules', 'superuser'),
        ('psa', 'core:settings_psa', 'psa'),
        ('scheduler', 'core:settings_scheduler', 'superuser'),
        ('smtp', 'core:settings_smtp', 'superuser'),
        ('maintenance', 'core:maintenance', 'superuser'),
        ('data_import', 'imports:import_list', 'superuser'),
        ('data_export', 'core:settings_data_export', 'superuser'),
        ('kb_import', 'core:settings_kb_import', 'superuser'),
    ),
    'security': (
        ('security', 'core:settings_security', 'superuser'),
        ('technician_access', 'tech_access:index', 'superuser'),
        ('rmm_permissions', 'rmm_permissions:index', 'superuser'),
        ('security_dashboard', 'core:security_dashboard', 'superuser'),
        ('firewall', 'core:firewall_settings', 'superuser'),
        ('fail2ban', 'core:fail2ban_status', 'superuser'),
        ('snyk', 'core:settings_snyk', 'superuser'),
    ),
    'access': (
        ('access_management', 'accounts:access_management', 'login'),
        ('organizations', 'accounts:organization_list', 'login'),
        ('directory', 'core:settings_directory', 'superuser'),
        ('office_org_policy', 'office:org_policy', 'login'),
    ),
    'integrations': (
        ('webhooks', 'core:webhook_list', 'login'),
        ('integrations', 'integrations:integration_list', 'superuser'),
        ('rmm_rem0te', 'integrations:rem0te_setup', 'superuser'),
        ('ai', 'core:settings_ai', 'superuser'),
        ('ticket_ai', 'psa_ai:profiles', 'superuser'),
        ('sms', 'core:settings_sms', 'superuser'),
        ('office_documents', 'office:settings', 'superuser'),
    ),
    'mobile': (
        ('mobile_apps', 'core:mobile_apps_admin', 'staff'),
        ('beta_testers', 'core:beta_test_admin', 'superuser'),
    ),
}

ACTIVE_PAGE_GROUP = {
    page: group
    for group, entries in SETTINGS_GROUPS.items()
    for page, _url, _gate in entries
}


def group_for_active_page(active_page):
    """The group key holding ``active_page`` (None when it is not a menu page)."""
    return ACTIVE_PAGE_GROUP.get(active_page or '')


def _allowed(gate, user, psa_enabled):
    if user is None or not getattr(user, 'is_authenticated', False):
        return False
    if gate == 'login':
        return True
    if gate == 'staff':
        return bool(user.is_staff or user.is_superuser)
    if gate == 'psa':
        return bool(user.is_superuser and psa_enabled)
    return bool(user.is_superuser)


def visible_entries(group_key, user, psa_enabled=False):
    return [
        entry for entry in SETTINGS_GROUPS.get(group_key, ())
        if _allowed(entry[2], user, psa_enabled)
    ]


def landing_url_name(group_key, user, psa_enabled=False):
    """URL name of the first page in ``group_key`` the user may open, or None."""
    entries = visible_entries(group_key, user, psa_enabled)
    return entries[0][1] if entries else None


def landing_url(group_key, user, psa_enabled=False):
    name = landing_url_name(group_key, user, psa_enabled)
    return reverse(name) if name else ''


# Static landing for a superuser (the navbar's Admin menu is superuser-only).
GROUP_LANDING_URL_NAMES = {
    group: SETTINGS_GROUPS[group][0][1] for group in GROUP_ORDER
}
