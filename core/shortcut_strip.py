"""
Per-user shortcut strip: up to three pinned destinations shown next to the
navbar for MSP staff.

Pins are keys into `SHORTCUT_REGISTRY`, a fixed whitelist of named routes.
Each entry carries the same condition the navigation uses for that menu item
(feature flag, staff check, RoleTemplate permission). Pins are stored on
`UserProfile.shortcut_pins` and resolved on every request: a pin whose
destination is no longer permitted, whose module is off, or whose route no
longer reverses is dropped silently, never rendered as a dead link.

Customer (portal) users get no strip at all.

This is separate from record Favorites (`core.Favorite`), which star
individual records; the strip pins whole pages.
"""
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext_lazy as _

MAX_PINS = 3

# Shown to MSP staff who have never saved a choice. Hidden (by the gates)
# when PSA is off.
DEFAULT_PIN_KEYS = ['my_work', 'tickets']


def _flag(name):
    def gate(user, flags):
        return bool(flags.get(name))
    return gate


def _staff(user, flags):
    """Mirrors base.html's `is_staff_user or user.is_superuser or user.is_staff`."""
    if user.is_superuser or user.is_staff:
        return True
    profile = getattr(user, 'profile', None)
    return bool(profile is not None and profile.is_staff_user())


def _perm(perm_name):
    def gate(user, flags):
        from accounts.permission_utils import user_has_perm
        return user_has_perm(user, perm_name)
    return gate


def _all(*gates):
    def gate(user, flags):
        return all(g(user, flags) for g in gates)
    return gate


def _always(user, flags):
    return True


_psa = _flag('psa_enabled')

# key -> label, FA icon, url name, gate(user, flags). Order = picker order.
SHORTCUT_REGISTRY = [
    {'key': 'my_work', 'label': _('My Work'), 'icon': 'fa-user-check',
     'url_name': 'psa:my_work', 'gate': _psa},
    {'key': 'tickets', 'label': _('Tickets'), 'icon': 'fa-list',
     'url_name': 'psa:ticket_list', 'gate': _psa},
    {'key': 'dispatch_board', 'label': _('Dispatch Board'), 'icon': 'fa-table-list',
     'url_name': 'psa:dispatch_board', 'gate': _all(_psa, _staff)},
    {'key': 'projects', 'label': _('Projects'), 'icon': 'fa-diagram-project',
     'url_name': 'psa:project_list', 'gate': _psa},
    {'key': 'approvals', 'label': _('Approvals'), 'icon': 'fa-circle-check',
     'url_name': 'psa:approval_list', 'gate': _all(_psa, _staff)},
    {'key': 'knowledge_base', 'label': _('Knowledge Base'), 'icon': 'fa-book',
     'url_name': 'psa:kb_browse', 'gate': _all(_psa, _staff)},
    {'key': 'quotes', 'label': _('Quotes'), 'icon': 'fa-file-invoice-dollar',
     'url_name': 'psa:quote_list', 'gate': _psa},
    {'key': 'invoices', 'label': _('Invoices'), 'icon': 'fa-file-invoice',
     'url_name': 'psa:invoice_list', 'gate': _psa},
    {'key': 'assets', 'label': _('Assets'), 'icon': 'fa-box',
     'url_name': 'assets:asset_list', 'gate': _always},
    {'key': 'passwords', 'label': _('Passwords'), 'icon': 'fa-key',
     'url_name': 'vault:password_list', 'gate': _always},
    {'key': 'documents', 'label': _('Documents'), 'icon': 'fa-file-alt',
     'url_name': 'docs:document_list', 'gate': _always},
    {'key': 'workflows', 'label': _('Workflows'), 'icon': 'fa-tasks',
     'url_name': 'processes:process_list', 'gate': _flag('workflows_enabled')},
    {'key': 'my_tasks', 'label': _('My Tasks'), 'icon': 'fa-user-check',
     'url_name': 'scheduling:my_tasks', 'gate': _flag('scheduling_enabled')},
    {'key': 'website_monitors', 'label': _('Website Monitors'), 'icon': 'fa-globe',
     'url_name': 'monitoring:website_monitor_list', 'gate': _flag('monitoring_enabled')},
    {'key': 'reports', 'label': _('Reports'), 'icon': 'fa-chart-line',
     'url_name': 'reports:home',
     'gate': _all(_flag('reports_enabled'), _staff, _perm('reports_view_dashboards'))},
    {'key': 'crm_pipeline', 'label': _('Pipeline'), 'icon': 'fa-columns',
     'url_name': 'crm:pipeline',
     'gate': _all(_flag('crm_enabled'), _staff, _perm('crm_manage_pipeline'))},
]

_BY_KEY = {e['key']: e for e in SHORTCUT_REGISTRY}


def get_entry(key):
    return _BY_KEY.get(key)


def feature_flags():
    """The module toggles the navigation reads, fresh from SystemSetting.
    Fails closed: if settings can't be read, no gated module is offered."""
    names = ('psa_enabled', 'crm_enabled', 'workflows_enabled',
             'scheduling_enabled', 'monitoring_enabled', 'reports_enabled')
    try:
        from core.models import SystemSetting
        row = SystemSetting.get_settings()
        return {n: bool(getattr(row, n, False)) for n in names}
    except Exception:
        return {n: False for n in names}


def strip_eligible(user):
    """Only MSP staff get a strip; customer (portal) users never do."""
    from psa.visibility import is_msp_staff
    return is_msp_staff(user)


def saved_keys(user):
    """The user's stored pins, or the defaults when they never chose.
    An explicit empty list means "no pins" and is kept."""
    profile = getattr(user, 'profile', None)
    saved = getattr(profile, 'shortcut_pins', None) if profile is not None else None
    if saved is None:
        return list(DEFAULT_PIN_KEYS)
    return [k for k in saved if isinstance(k, str)]


def _resolve(entry, user, flags):
    try:
        if not entry['gate'](user, flags):
            return None
        url = reverse(entry['url_name'])
    except NoReverseMatch:
        return None
    except Exception:
        return None
    return {'key': entry['key'], 'label': entry['label'],
            'icon': entry['icon'], 'url': url}


def available_for_user(user, flags=None):
    """Whitelist entries this user may pin right now."""
    if not strip_eligible(user):
        return []
    flags = feature_flags() if flags is None else flags
    out = []
    for entry in SHORTCUT_REGISTRY:
        item = _resolve(entry, user, flags)
        if item:
            out.append(item)
    return out


def resolve_pins(user, flags=None):
    """The pins to render for `user`, re-checked against current permissions,
    feature flags and routes. Stale or unknown pins are dropped silently."""
    if not user or not user.is_authenticated or not strip_eligible(user):
        return []
    flags = feature_flags() if flags is None else flags
    out, seen = [], set()
    for key in saved_keys(user):
        if key in seen:
            continue
        seen.add(key)
        entry = get_entry(key)
        if not entry:
            continue
        item = _resolve(entry, user, flags)
        if item:
            out.append(item)
        if len(out) >= MAX_PINS:
            break
    return out


def validate_choice(user, keys):
    """Check a submitted pin list. Returns (clean_keys, error_message)."""
    clean = []
    for k in keys:
        if k and k not in clean:
            clean.append(k)
    if len(clean) > MAX_PINS:
        return None, _('Choose at most %(n)d shortcuts.') % {'n': MAX_PINS}
    allowed = {item['key'] for item in available_for_user(user)}
    if any(k not in allowed for k in clean):
        return None, _('One of the chosen shortcuts is not available to you.')
    return clean, None
