"""Where each navbar entry leads, and the local tabs on its landing page.

The global menu in ``templates/base.html`` is short: every dropdown carries
three to seven entries, one per *section*. A section is a landing page plus the
handful of sibling pages that used to sit beside it in the menu. Those siblings
are listed here as the section's tabs, and ``base.html`` renders them as a row
of pills above the page content whenever the current page is one of them — so
the secondary destinations are one ordinary click away from the landing page,
without search and without a nested flyout.

The navbar itself stays hand-written in the template, with its permission and
feature-flag checks exactly where they always were. This module is the other
half: the tabs, and which menu/entry to mark active for the current page.
``core/tests/test_navbar_grouping.py`` checks the two agree.

Gating: a tab's ``gate`` uses the same condition the old navbar used for that
link (``_msp_staff`` is base.html's ``is_staff_user or user.is_superuser or
user.is_staff``). A section's ``gate`` applies to the whole strip. Pages keep
their own view-level checks; hiding a tab is presentation, not access control.
"""
from dataclasses import dataclass, field

from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext_lazy as _


# -- gates (each takes the template context) ---------------------------------

def _user(ctx):
    return ctx.get('user')


def _superuser(ctx):
    u = _user(ctx)
    return bool(u is not None and u.is_superuser)


def _msp_staff(ctx):
    """base.html's `is_staff_user or user.is_superuser or user.is_staff`."""
    u = _user(ctx)
    return bool(ctx.get('is_staff_user')
                or (u is not None and (u.is_superuser or u.is_staff)))


def _staff_user_or_superuser(ctx):
    """base.html's `is_staff_user or user.is_superuser` (no Django is_staff)."""
    return bool(ctx.get('is_staff_user') or _superuser(ctx))


def _flag(name):
    def gate(ctx):
        return bool(ctx.get(name))
    return gate


def _ai_enabled(ctx):
    """OPTIONAL AI: the AI Inbox 404s unless `psa_ai_enabled` is on."""
    return bool(getattr(ctx.get('system_settings'), 'psa_ai_enabled', False))


def _all(*gates):
    def gate(ctx):
        return all(g(ctx) for g in gates)
    return gate


# Gates that mirror a page's own view-level check, so the link appears exactly
# for the users the page would let in. Each imports lazily (navigation is
# loaded early) and fails closed.

def _view_check(fn):
    def gate(ctx):
        u = _user(ctx)
        if u is None or not getattr(u, 'is_authenticated', False):
            return False
        try:
            return bool(fn(u, ctx))
        except Exception:
            return False
    return gate


def _is_msp_staff(user):
    from psa.visibility import is_msp_staff
    return bool(is_msp_staff(user))


def _check_shift_manager(u, ctx):
    """resourcing.shift_views.templates: can_manage_shifts (MSP staff)."""
    from resourcing.shift_views import can_manage_shifts
    return _is_msp_staff(u) and can_manage_shifts(u)


def _check_geo_admin(u, ctx):
    """field_ops.dispatch_views.dispatch_geo_settings: a superuser technician."""
    return u.is_superuser and _is_msp_staff(u)


def _check_routing_manager(u, ctx):
    """psa.routing PERM_MANAGE: alert policy, support workflows admin."""
    from psa.routing.permissions import can_manage
    return can_manage(u)


def _check_org_admin(u, ctx):
    """core.decorators.require_admin: superuser, Django staff, or an
    Owner/Admin membership of the current customer."""
    if u.is_superuser or u.is_staff:
        return True
    request = ctx.get('request')
    if request is None:
        return False
    from core.decorators import get_user_membership
    membership = get_user_membership(request)
    return bool(membership and membership.can_admin())


def _check_billing_reviewer(u, ctx):
    """psa.views.billing_review: require_admin plus MSP staff."""
    return _check_org_admin(u, ctx) and (u.is_superuser or _is_msp_staff(u))


def _check_digest_reader(u, ctx):
    """security_alerts.views.digest_subscriptions: security_alerts_view."""
    from accounts.permission_utils import user_has_perm
    return user_has_perm(u, 'security_alerts_view')


def _check_rmm_policy_reader(u, ctx):
    """rmm_permissions.views._gate: policy.manage or audit.review."""
    from rmm_permissions.views import _reader
    return _reader(u)


_shift_manager = _view_check(_check_shift_manager)
_geo_admin = _view_check(_check_geo_admin)
_routing_manager = _view_check(_check_routing_manager)
_org_admin = _view_check(_check_org_admin)
_billing_reviewer = _view_check(_check_billing_reviewer)
_digest_reader = _view_check(_check_digest_reader)
_rmm_policy_reader = _view_check(_check_rmm_policy_reader)


@dataclass(frozen=True)
class Tab:
    label: str
    url_name: str = ''
    icon: str = ''
    args: tuple = ()
    gate: object = None
    modal: str = ''        # id of a modal in base.html this tab opens instead
    dom_id: str = ''       # an id base.html's scripts look for
    download: bool = False  # a file download rather than a page


@dataclass(frozen=True)
class Section:
    key: str
    menu: str
    label: str
    tabs: tuple
    gate: object = None
    # False where the landing page already carries its own local nav
    # (hardware/_nav.html, readiness/_nav.html). The section still drives the
    # navbar's active state.
    render_tabs: bool = True
    # Pages that belong to the section for the navbar's active state but are
    # not tabs (forms, detail pages).
    also: tuple = field(default=())


_psa = _flag('psa_enabled')

SECTIONS = (
    # ---- PSA --------------------------------------------------------------
    Section('psa_my_work', 'psa', _('My Work'), gate=_psa, tabs=(
        Tab(_('My Work'), 'psa:my_work', 'fa-user-check'),
    )),
    Section('psa_tickets', 'psa', _('Tickets'), gate=_psa, also=('psa:ticket_create',), tabs=(
        Tab(_('Tickets'), 'psa:ticket_list', 'fa-list'),
        Tab(_('Recurring Tickets'), 'psa:recurring_list', 'fa-repeat'),
        Tab(_('Canned Replies'), 'psa:canned_reply_list', 'fa-magic'),
        Tab(_('Workflow Rules'), 'psa:workflow_rule_list', 'fa-bolt'),
        Tab(_('Workflow Flow Map'), 'psa:workflow_rule_map', 'fa-project-diagram',
            # require_admin lets a customer's Owner in too; the map of every
            # rule is an MSP tool, so the link is offered to MSP staff only.
            gate=_all(_org_admin, _msp_staff)),
        Tab(_('Email Ingestion'), 'psa:email_config_list', 'fa-envelope-open-text'),
        Tab(_('AI Inbox'), 'psa_ai:inbox', 'fa-wand-magic-sparkles', gate=_ai_enabled),
    )),
    Section('psa_dispatch', 'psa', _('Dispatch Board'), gate=_psa, tabs=(
        Tab(_('Dispatch Board'), 'psa:dispatch_board', 'fa-table-list'),
        # Routing pages check their own permissions (manage / test / override).
        Tab(_('Routing Triage'), 'ticket_routing:triage', 'fa-inbox', gate=_msp_staff),
        Tab(_('Ticket Routing'), 'ticket_routing:overview', 'fa-route', gate=_msp_staff),
    )),
    # Who works when, and where dispatch may see them: dispatch, on-call and
    # ticket routing read the shift schedule, so it lives with them.
    Section('psa_shifts', 'psa', _('Shifts & Locations'), gate=_all(_msp_staff, _psa), tabs=(
        Tab(_('Shift Schedule'), 'resourcing:shift_schedule', 'fa-user-clock'),
        Tab(_('Shift Templates'), 'resourcing:shift_templates', 'fa-layer-group', gate=_shift_manager),
        # A technician's own opt-in to share their position with dispatch.
        Tab(_('Location Sharing'), 'field_ops:dispatch_sharing', 'fa-location-dot'),
        Tab(_('Dispatch Locations'), 'field_ops:dispatch_geo_settings', 'fa-map-location-dot',
            gate=_geo_admin),
    )),
    Section('psa_projects', 'psa', _('Projects'), gate=_psa, tabs=(
        Tab(_('Projects'), 'psa:project_list', 'fa-diagram-project'),
        Tab(_('Project Templates'), 'psa:project_template_list', 'fa-clipboard-list'),
    )),
    Section('psa_service', 'psa', _('Service Management'), gate=_psa, tabs=(
        Tab(_('Service Catalog'), 'psa:service_catalog', 'fa-th'),
        Tab(_('Catalog Changes'), 'psa:catalog_change_list', 'fa-clipboard-check'),
        Tab(_('Change Requests'), 'psa:change_request_list', 'fa-code-branch'),
        Tab(_('Problems'), 'psa:problem_list', 'fa-bug'),
        Tab(_('Releases'), 'psa:release_list', 'fa-rocket'),
        Tab(_('Approvals'), 'psa:approval_list', 'fa-circle-check', gate=_msp_staff),
        Tab(_('Knowledge Base'), 'psa:kb_browse', 'fa-book', gate=_msp_staff),
    )),
    Section('psa_billing', 'psa', _('Billing'), gate=_psa, tabs=(
        Tab(_('Contracts'), 'psa:contract_list', 'fa-file-contract'),
        Tab(_('Quotes'), 'psa:quote_list', 'fa-file-invoice-dollar'),
        Tab(_('Invoices'), 'psa:invoice_list', 'fa-file-invoice'),
        Tab(_('Aging Report'), 'psa:aging_report', 'fa-chart-column'),
        Tab(_('Billing Review'), 'psa:billing_review', 'fa-list-check', gate=_billing_reviewer),
    )),
    Section('psa_procurement', 'psa', _('Procurement'), gate=_psa, tabs=(
        Tab(_('Requisitions'), 'psa:requisition_list', 'fa-clipboard-list'),
        Tab(_('Purchase Orders'), 'psa:po_list', 'fa-file-invoice'),
        Tab(_('Back-orders'), 'psa:back_order_list', 'fa-hourglass-half'),
        Tab(_('Vendors'), 'psa:vendor_list', 'fa-truck'),
    )),

    # ---- Operations -------------------------------------------------------
    Section('ops_workflows', 'ops', _('Workflows'), gate=_flag('workflows_enabled'), tabs=(
        Tab(_('Workflows'), 'processes:process_list', 'fa-tasks'),
    )),
    Section('ops_inventory', 'ops', _('Inventory'), gate=_flag('inventory_enabled'), tabs=(
        Tab(_('Dashboard'), 'inventory:inventory_dashboard', 'fa-tachometer-alt'),
        Tab(_('All Items'), 'inventory:item_list', 'fa-boxes'),
        Tab(_('Low Stock'), 'inventory:low_stock_report', 'fa-exclamation-triangle'),
        Tab(_('Tools'), 'inventory:tool_list', 'fa-screwdriver-wrench'),
    )),
    Section('ops_scheduling', 'ops', _('Scheduling'), gate=_flag('scheduling_enabled'), tabs=(
        Tab(_('All Tasks'), 'scheduling:task_list', 'fa-tasks'),
        Tab(_('My Tasks'), 'scheduling:my_tasks', 'fa-user-check'),
        Tab(_('Calendar'), 'scheduling:task_calendar', 'fa-calendar-alt'),
        Tab(_('Wallboard'), 'scheduling:wallboard_settings', 'fa-tv'),
    )),
    Section('ops_monitoring', 'ops', _('Monitoring'), gate=_flag('monitoring_enabled'), tabs=(
        Tab(_('Website Monitors'), 'monitoring:website_monitor_list', 'fa-globe'),
        Tab(_('WAN Connections'), 'monitoring:wan_monitor_list', 'fa-network-wired'),
        Tab(_('Expirations'), 'monitoring:expiration_list', 'fa-calendar-times'),
        Tab(_('Status Pages'), 'statuspage:list', 'fa-heart-pulse'),
        Tab(_('Config Backups'), 'netconfig:device_list', 'fa-file-code'),
    )),
    Section('ops_vehicles', 'ops', _('Vehicles'), gate=_flag('vehicles_enabled'), tabs=(
        Tab(_('All Vehicles'), 'vehicles:vehicle_list', 'fa-truck'),
        Tab(_('Service Alerts'), 'vehicles:service_alert_list', 'fa-bell'),
    )),

    # ---- Modules (MSP staff only) -----------------------------------------
    Section('mod_security', 'modules', _('Security'), gate=_all(_msp_staff, _psa), tabs=(
        Tab(_('Security Alerts'), 'security_alerts:alert_list', 'fa-triangle-exclamation'),
        Tab(_('Vendor Connections'), 'security_alerts:connection_list', 'fa-plug'),
        Tab(_('Auto-Ticket Rules'), 'security_alerts:rule_list', 'fa-bolt'),
        Tab(_('Weekly Digest'), 'security_alerts:digest_subscriptions', 'fa-envelope-open-text',
            gate=_digest_reader),
    )),
    Section('mod_crm', 'modules', _('CRM'), gate=_all(_msp_staff, _flag('crm_enabled')), tabs=(
        Tab(_('Overview'), 'crm:home', 'fa-home'),
        Tab(_('Pipeline'), 'crm:pipeline', 'fa-columns'),
        Tab(_('Leads'), 'crm:lead_list', 'fa-user-plus'),
        Tab(_('Opportunities'), 'crm:opportunity_list', 'fa-handshake'),
        Tab(_('Campaigns'), 'crm:campaign_list', 'fa-bullhorn'),
        Tab(_('Commissions'), 'crm:commission_list', 'fa-hand-holding-usd'),
        Tab(_('Commission Rules'), 'crm:commission_rule_list', 'fa-cogs'),
    )),
    Section('mod_reports', 'modules', _('Reports'), gate=_all(_msp_staff, _flag('reports_enabled')), tabs=(
        Tab(_('Reports Home'), 'reports:home', 'fa-home'),
        Tab(_('Dashboards'), 'reports:dashboard_list', 'fa-th-large'),
        Tab(_('Wallboards'), 'reports:wallboard_list', 'fa-tv'),
        Tab(_('Generate Reports'), 'reports:template_list', 'fa-file-pdf'),
        Tab(_('Report History'), 'reports:generated_list', 'fa-history'),
    )),

    # ---- Assets -----------------------------------------------------------
    Section('assets_all', 'assets', _('All Assets'), tabs=(
        Tab(_('All Assets'), 'assets:asset_list', 'fa-box'),
        Tab(_('Serial Search'), 'assets:serial_search', 'fa-barcode'),
    )),
    # hardware/_nav.html already is this section's local nav.
    Section('assets_hardware', 'assets', _('Hardware & Ports'), render_tabs=False, tabs=(
        Tab(_('Devices'), 'hardware:device_list', 'fa-server'),
        Tab(_('Cables'), 'hardware:cable_list', 'fa-ethernet'),
        Tab(_('VLANs'), 'hardware:vlan_list', 'fa-layer-group'),
        Tab(_('Connectivity'), 'hardware:diagram', 'fa-project-diagram', args=('connectivity',)),
        Tab(_('Labels'), 'hardware:labels', 'fa-tags'),
        Tab(_('Import / export'), 'hardware:import_csv', 'fa-file-csv'),
        Tab(_('Catalog'), 'hardware:catalog', 'fa-book'),
    )),
    Section('assets_infra', 'assets', _('Infrastructure'), tabs=(
        Tab(_('Racks'), 'monitoring:rack_list', 'fa-server'),
        Tab(_('Network Closets'), 'monitoring:network_closet_list', 'fa-network-wired'),
        Tab(_('IPAM'), 'monitoring:subnet_list', 'fa-sitemap'),
        Tab(_('VLANs'), 'monitoring:vlan_list', 'fa-layer-group'),
    )),
    Section('assets_setup', 'assets', _('Asset Setup'), gate=_msp_staff, tabs=(
        Tab(_('Equipment Catalog'), 'assets:vendor_list', 'fa-database'),
        Tab(_('Custom Fields & Types'), 'assets:custom_field_list', 'fa-sliders-h'),
    )),

    # ---- Docs -------------------------------------------------------------
    Section('docs_documents', 'docs', _('Documents'), tabs=(
        Tab(_('Documents'), 'docs:document_list', 'fa-file-alt'),
    )),
    Section('docs_diagrams', 'docs', _('Diagrams'), tabs=(
        Tab(_('Diagrams'), 'docs:diagram_list', 'fa-project-diagram'),
        Tab(_('Import Floor Plans'), 'locations:floor_plan_import', 'fa-file-upload'),
    )),
    Section('docs_review', 'docs', _('Review & Publishing'), tabs=(
        Tab(_('Drafts'), 'docs:document_drafts_list', 'fa-pen-ruler'),
        Tab(_('Approval Queue'), 'docs:kb_approval_queue', 'fa-check-double'),
        Tab(_('Review Queue'), 'docs:kb_review_queue', 'fa-calendar-check'),
        Tab(_('Archived'), 'docs:document_archived_list', 'fa-box-archive'),
        Tab(_('KB Analytics'), 'docs:kb_analytics', 'fa-chart-line', gate=_staff_user_or_superuser),
    )),
    # readiness/_nav.html already is this section's local nav.
    Section('docs_readiness', 'docs', _('Documentation Readiness'), render_tabs=False, tabs=(
        Tab(_('Documentation Readiness'), 'readiness:overview', 'fa-clipboard-check'),
    )),

    # ---- Vault ------------------------------------------------------------
    Section('vault_passwords', 'vault', _('Passwords'), tabs=(
        Tab(_('Passwords'), 'vault:password_list', 'fa-key'),
    )),
    Section('vault_personal', 'vault', _('My Vault'), tabs=(
        Tab(_('My Vault'), 'vault:personal_vault_list', 'fa-sticky-note'),
    )),
    Section('vault_notes', 'vault', _('Secure Notes'), gate=_flag('secure_notes_enabled'), tabs=(
        Tab(_('Secure Notes'), 'core:secure_note_inbox', 'fa-lock'),
    )),
    Section('vault_rules', 'vault', _('Access Rules'), tabs=(
        Tab(_('Access Rules'), 'vault:access_rule_list', 'fa-shield-halved'),
    )),

    # ---- Admin (superuser) ------------------------------------------------
    Section('admin_system', 'admin', _('System'), gate=_superuser, tabs=(
        Tab(_('Settings'), 'core:settings_general', 'fa-sliders-h'),
        Tab(_('System Status'), 'core:system_status', 'fa-heartbeat'),
        Tab(_('System Updates'), 'core:system_updates', 'fa-sync-alt'),
    )),
    Section('admin_security', 'admin', _('Security'), gate=_superuser, tabs=(
        Tab(_('Security Dashboard'), 'core:security_dashboard', 'fa-shield-alt'),
        Tab(_('Security Features'), 'core:security_features', 'fa-list-check'),
        Tab(_('Vault Visibility'), 'core:vault_visibility', 'fa-eye-slash'),
        Tab(_('Superuser Approval'), 'tech_access:superuser_policy', 'fa-user-shield'),
        Tab(_('Vulnerability Scans'), 'core:snyk_scans', 'fa-bug'),
        Tab(_('Scan Configuration'), 'core:settings_snyk', 'fa-cog'),
    )),
    # The organization list is also every technician's "All clients" page
    # (client switcher), so the section itself is ungated; Access Management
    # stays superuser-only, and a lone tab renders no strip.
    Section('admin_access', 'admin', _('Organizations & Access'), tabs=(
        Tab(_('Organizations'), 'accounts:organization_list', 'fa-building'),
        Tab(_('Access Management'), 'accounts:access_management', 'fa-users-cog', gate=_superuser),
    )),
    Section('admin_integrations', 'admin', _('Integrations'), gate=_superuser, tabs=(
        Tab(_('Integrations'), 'integrations:integration_list', 'fa-plug'),
        Tab(_('Webhooks'), 'core:webhook_list', 'fa-bolt'),
        Tab(_('Rem0te Setup'), 'integrations:rem0te_setup', 'fa-desktop'),
    )),
    Section('admin_mobile', 'admin', _('Mobile'), gate=_superuser, tabs=(
        Tab(_('Mobile Apps'), 'core:mobile_apps_admin', 'fa-mobile-alt'),
        Tab(_('Beta tester requests'), 'core:beta_test_admin', 'fa-user-check'),
    )),

    # ---- Account ----------------------------------------------------------
    Section('account_profile', 'account', _('My Profile'), tabs=(
        Tab(_('My Profile'), 'accounts:profile', 'fa-user'),
        # OPTIONAL AI: a technician's own provider keys (psa_ai.profile_views.own_keys).
        Tab(_('My AI keys'), 'psa_ai:own_keys', 'fa-key', gate=_all(_ai_enabled, _staff_user_or_superuser)),
    )),
    Section('account_work', 'account', _('My Work Details'), tabs=(
        Tab(_('My Resources'), 'resourcing:my_resourcing', 'fa-user-graduate'),
        Tab(_('My Leave'), 'resourcing:my_leave', 'fa-umbrella-beach'),
        Tab(_('My Billable Target'), 'resourcing:my_billable_target', 'fa-bullseye'),
    )),
    Section('account_help', 'account', _('Help'), tabs=(
        Tab(_('Documentation & Help'), 'core:help_index', 'fa-book'),
        Tab(_('About'), 'core:about', 'fa-info-circle'),
        Tab(_('Roadmap'), 'core:roadmap', 'fa-map'),
        Tab(_('Report Bug'), icon='fa-bug', modal='reportBugModal'),
        Tab(_('Help Us Grow'), icon='fa-heart', modal='supportProjectModal'),
    )),
    Section('account_apps', 'account', _('Apps & Downloads'), tabs=(
        # `menu-install-pwa` is the hook base.html's PWA script attaches the
        # install prompt to (it used to be on the account-menu entry).
        Tab(_('Install App / Add to Home Screen'), 'core:install_app', 'fa-download',
            dom_id='menu-install-pwa'),
        Tab(_('Android App (APK)'), 'core:download_mobile_app', 'fab fa-android',
            args=('android',), download=True),
        Tab(_('Beta test the Android app'), 'core:beta_test_signup', 'fa-flask'),
        Tab(_('Browser Extension'), 'core:download_browser_extension', 'fa-puzzle-piece',
            download=True),
    )),
)

SECTIONS_BY_KEY = {s.key: s for s in SECTIONS}

# Pages outside any section still light up their top-level menu.
NAMESPACE_MENU = {
    'psa': 'psa', 'psa_ai': 'psa',
    'processes': 'ops', 'inventory': 'ops', 'scheduling': 'ops',
    'vehicles': 'ops', 'statuspage': 'ops', 'netconfig': 'ops',
    'security_alerts': 'modules', 'crm': 'modules', 'reports': 'modules',
    'assets': 'assets', 'hardware': 'assets',
    'docs': 'docs', 'readiness': 'docs', 'locations': 'docs',
    'vault': 'vault',
    'resourcing': 'account',
    'integrations': 'admin',
}
# Monitoring hosts both the uptime tools (Operations) and the physical
# infrastructure pages (Assets → Infrastructure).
_MONITORING_INFRA_PREFIXES = ('rack', 'network_closet', 'subnet', 'ip_address',
                              'vlan', 'patch_panel')


def _build_index():
    index = {}
    for section in SECTIONS:
        for tab in section.tabs:
            if tab.url_name:
                index.setdefault(tab.url_name, section)
        for name in section.also:
            index.setdefault(name, section)
    return index


VIEW_INDEX = _build_index()


def section_for(view_name):
    return VIEW_INDEX.get(view_name)


def menu_for(view_name):
    section = section_for(view_name)
    if section is not None:
        return section.menu
    namespace, _sep, url_name = (view_name or '').rpartition(':')
    if namespace == 'monitoring':
        return 'assets' if url_name.startswith(_MONITORING_INFRA_PREFIXES) else 'ops'
    return NAMESPACE_MENU.get(namespace, '')


def _allowed(gate, ctx):
    return gate is None or gate(ctx)


def _href(tab):
    try:
        return reverse(tab.url_name, args=tab.args)
    except NoReverseMatch:
        return ''


def _is_current(tab, match):
    if tab.url_name != match.view_name:
        return False
    if tab.args:
        return tuple(str(a) for a in tab.args) == tuple(str(a) for a in match.args) or \
            tuple(str(a) for a in tab.args) == tuple(str(v) for v in match.kwargs.values())
    return True


def resolve_tabs(section, ctx, match=None):
    """The visible tabs of `section` for this context, as plain dicts."""
    out = []
    for tab in section.tabs:
        if not _allowed(tab.gate, ctx):
            continue
        href = '#' if tab.modal else _href(tab)
        if not href:
            continue
        out.append({
            'label': tab.label,
            'href': href,
            'icon': tab.icon if ' ' in tab.icon else f'fas {tab.icon}',
            'modal': tab.modal,
            'dom_id': tab.dom_id,
            'download': tab.download,
            'active': bool(match is not None and not tab.modal and _is_current(tab, match)),
        })
    return out


def nav_state(ctx):
    """What base.html needs for the current page.

    Returns ``{'menu', 'section', 'section_label', 'tabs'}``. ``tabs`` is
    non-empty only when the current page is itself one of the section's tabs,
    the section is visible to this user, and more than one tab survives the
    gates — a strip with a single pill is noise.
    """
    state = {'menu': '', 'section': '', 'section_label': '', 'tabs': []}
    user = _user(ctx)
    if user is None or not user.is_authenticated:
        return state  # signed-out pages carry no application navigation
    request = ctx.get('request')
    match = getattr(request, 'resolver_match', None) if request is not None else None
    view_name = getattr(match, 'view_name', '') or ''
    state['menu'] = menu_for(view_name)
    section = section_for(view_name)
    if section is None:
        return state
    state['section'] = section.key
    state['section_label'] = section.label
    if not (section.render_tabs and _allowed(section.gate, ctx)):
        return state
    if not any(t.url_name == view_name for t in section.tabs):
        return state  # a form or detail page: highlight the menu, no strip
    tabs = resolve_tabs(section, ctx, match)
    if len(tabs) > 1:
        state['tabs'] = tabs
    return state


# =============================================================================
# Primary navigation: the technician-first sidebar.
#
# Seven groups a technician works through all day (My Work, Tickets, Clients,
# Devices, Alerts, Tools, Reports) plus Settings at the foot for
# administrative and advanced configuration. Each entry points at a SECTION
# above (its landing page is the first tab this user may open) or at a single
# page. A section's tabs are rendered as nested links under its entry, so the
# sidebar filter finds every page by name; the section strip above the content
# keeps working as before.
#
# Two layers of gating, both evaluated per request:
#   * the entry's own gate plus its section's gate (feature flags, staff,
#     superuser, OPTIONAL AI): the conditions the old navbar used;
#   * `_PermProbe`: the URL-prefix rules SectionPermissionMiddleware applies
#     (staff-only /reports/ /crm/ /security/, and the vault_view / docs_view /
#     assets_view role flags for the current customer). A link the server
#     would answer with 403 is not drawn.
# Pages keep their own view-level checks; hiding a link is presentation.
# docs/navigation-map.md lists where every old menu entry went.
# =============================================================================

@dataclass(frozen=True)
class Entry:
    label: str
    section: str = ''      # key into SECTIONS_BY_KEY
    url_name: str = ''     # a single page (when no section)
    icon: str = ''
    args: tuple = ()
    gate: object = None
    keywords: str = ''     # extra words the sidebar filter matches


@dataclass(frozen=True)
class Group:
    key: str
    label: str
    icon: str
    entries: tuple
    shortcut: str = ''     # "g <key>" opens the group's landing page


def _global_kb_alone(ctx):
    """base.html's old rule: Global KB sat in the bar only while PSA is off
    (with PSA on it is PSA → Service Management → Knowledge Base)."""
    return bool(ctx.get('global_kb_enabled') and not ctx.get('psa_enabled')
                and _staff_user_or_superuser(ctx))


PRIMARY = (
    Group('my_work', _('My Work'), 'fa-user-check', shortcut='w', entries=(
        Entry(_('My Work'), section='psa_my_work', icon='fa-user-check',
              keywords='workspace queue assigned sla timers approvals'),
        Entry(_('Dashboard'), url_name='core:dashboard', icon='fa-tachometer-alt',
              keywords='home overview'),
        Entry(_('Favorites'), url_name='core:favorite_list', icon='fa-star', keywords='starred'),
        Entry(_('My Vault'), section='vault_personal', icon='fa-sticky-note',
              keywords='personal passwords'),
        Entry(_('Secure Notes'), section='vault_notes', icon='fa-lock', keywords='inbox share'),
    )),
    Group('tickets', _('Tickets'), 'fa-ticket-alt', shortcut='t', entries=(
        Entry(_('Tickets'), section='psa_tickets', icon='fa-list', keywords='psa helpdesk'),
        Entry(_('Dispatch Board'), section='psa_dispatch', icon='fa-table-list',
              keywords='schedule routing triage'),
        Entry(_('Shifts & Locations'), section='psa_shifts', icon='fa-user-clock',
              keywords='shift schedule templates rota on-call dispatch location sharing consent geo'),
        Entry(_('Projects'), section='psa_projects', icon='fa-diagram-project'),
        Entry(_('Service Management'), section='psa_service', icon='fa-th',
              keywords='itil catalog change problem release approvals knowledge'),
    )),
    Group('clients', _('Clients'), 'fa-building', shortcut='c', entries=(
        Entry(_('All Clients'), section='admin_access', icon='fa-building',
              keywords='customers organizations'),
        Entry(_('Customer Operations'), url_name='core:customer_ops_current', icon='fa-binoculars',
              keywords='sla uptime renewals invoices aging'),
        Entry(_('Documents'), section='docs_documents', icon='fa-file-alt', keywords='docs'),
        Entry(_('Diagrams'), section='docs_diagrams', icon='fa-project-diagram',
              keywords='floor plans'),
        Entry(_('Review & Publishing'), section='docs_review', icon='fa-check-double',
              keywords='drafts approval kb'),
        Entry(_('Documentation Readiness'), section='docs_readiness', icon='fa-clipboard-check'),
        Entry(_('Passwords'), section='vault_passwords', icon='fa-key', keywords='vault credentials'),
        Entry(_('Vault Access Rules'), section='vault_rules', icon='fa-shield-halved'),
        Entry(_('Billing'), section='psa_billing', icon='fa-file-invoice-dollar',
              keywords='contracts quotes invoices aging'),
        Entry(_('CRM'), section='mod_crm', icon='fa-chart-pie',
              keywords='sales pipeline leads opportunities'),
    )),
    Group('devices', _('Devices'), 'fa-laptop', shortcut='d', entries=(
        Entry(_('All Assets'), section='assets_all', icon='fa-box', keywords='devices inventory'),
        Entry(_('RMM Devices'), url_name='integrations:rmm_devices', icon='fa-desktop',
              gate=_msp_staff, keywords='agents endpoints online offline'),
        Entry(_('Device Workspace'), url_name='assets:device_workspace_home', icon='fa-laptop-medical',
              gate=_msp_staff, keywords='workspace connect diagnose patches recent devices'),
        Entry(_('Hardware & Ports'), section='assets_hardware', icon='fa-network-wired',
              keywords='cables vlans labels'),
        Entry(_('Infrastructure'), section='assets_infra', icon='fa-server',
              keywords='racks closets ipam subnets'),
    )),
    Group('alerts', _('Alerts'), 'fa-bell', shortcut='a', entries=(
        Entry(_('RMM Alerts'), url_name='integrations:rmm_alerts', icon='fa-bell',
              gate=_msp_staff, keywords='monitoring'),
        Entry(_('Security Alerts'), section='mod_security', icon='fa-triangle-exclamation',
              keywords='edr siem incidents'),
        Entry(_('Monitoring'), section='ops_monitoring', icon='fa-globe',
              keywords='uptime websites wan expirations status pages'),
        # Which RMM / monitoring alerts open tickets, and maintenance windows.
        Entry(_('Alert Policy'), url_name='ticket_routing:alerts', icon='fa-sliders',
              gate=_all(_psa, _routing_manager),
              keywords='alert rules auto ticket maintenance suppression rmm'),
    )),
    Group('tools', _('Tools'), 'fa-toolbox', shortcut='o', entries=(
        Entry(_('Workflows'), section='ops_workflows', icon='fa-tasks', keywords='runbooks processes'),
        Entry(_('Support Workflows'), url_name='support_workflows:admin', icon='fa-diagram-next',
              gate=_all(_psa, _routing_manager),
              keywords='ticket workflows guided troubleshooting playbooks'),
        Entry(_('Scheduling'), section='ops_scheduling', icon='fa-calendar-alt',
              keywords='tasks calendar wallboard'),
        Entry(_('Inventory'), section='ops_inventory', icon='fa-boxes', keywords='stock'),
        Entry(_('Procurement'), section='psa_procurement', icon='fa-truck',
              keywords='requisitions purchase orders vendors'),
        Entry(_('Vehicles'), section='ops_vehicles', icon='fa-truck-pickup', keywords='fleet'),
        Entry(_('Global KB'), url_name='docs:global_kb_list', icon='fa-book', gate=_global_kb_alone,
              keywords='knowledge base'),
    )),
    Group('reports', _('Reports'), 'fa-chart-bar', shortcut='r', entries=(
        Entry(_('Reports'), section='mod_reports', icon='fa-chart-bar',
              keywords='dashboards wallboards analytics'),
    )),
)

SETTINGS = Group('settings', _('Settings'), 'fa-cog', shortcut='s', entries=(
    Entry(_('System'), section='admin_system', icon='fa-sliders-h',
          keywords='general updates status features smtp'),
    Entry(_('Security'), section='admin_security', icon='fa-shield-alt',
          keywords='scans vulnerability superuser approval'),
    Entry(_('Access Management'), url_name='accounts:access_management', icon='fa-users-cog',
          gate=_superuser, keywords='users roles permissions'),
    Entry(_('LDAP Group Mappings'), url_name='accounts:ldap_group_mappings', icon='fa-sitemap',
          gate=_superuser, keywords='directory active directory ldap groups roles'),
    Entry(_('RMM Permissions'), url_name='rmm_permissions:index', icon='fa-user-lock',
          gate=_rmm_policy_reader, keywords='rmm roles overrides approvals remote actions policy'),
    Entry(_('Integrations'), section='admin_integrations', icon='fa-plug',
          keywords='rmm psa webhooks'),
    Entry(_('Asset Setup'), section='assets_setup', icon='fa-sliders-h',
          keywords='equipment catalog custom fields types'),
    Entry(_('Mobile'), section='admin_mobile', icon='fa-mobile-alt', keywords='apps beta'),
))

ALL_GROUPS = PRIMARY + (SETTINGS,)


def _build_group_index():
    index = {}
    for group in ALL_GROUPS:
        for entry in group.entries:
            if entry.section:
                index.setdefault(('section', entry.section), group.key)
            if entry.url_name:
                index.setdefault(('url', entry.url_name), group.key)
    return index


GROUP_INDEX = _build_group_index()

# Pages outside any section or entry still light up a group.
NAMESPACE_GROUP = {
    'psa': 'tickets', 'psa_ai': 'tickets', 'ticket_routing': 'tickets',
    'processes': 'tools', 'inventory': 'tools', 'scheduling': 'tools', 'vehicles': 'tools',
    'statuspage': 'alerts', 'netconfig': 'alerts', 'security_alerts': 'alerts',
    'crm': 'clients', 'reports': 'reports',
    'assets': 'devices', 'hardware': 'devices', 'network_discovery': 'devices',
    'docs': 'clients', 'readiness': 'clients', 'locations': 'clients', 'vault': 'clients',
    'integrations': 'settings', 'tech_access': 'settings', 'imports': 'settings',
    'audit': 'settings', 'rmm_permissions': 'settings', 'support_workflows': 'tickets',
}
# Integrations pages a technician works in daily, not configuration.
_WORK_PAGES = {
    'integrations:rmm_devices': 'devices', 'integrations:rmm_device_detail': 'devices',
    'integrations:rmm_device_delete': 'devices', 'integrations:rmm_software': 'devices',
    'integrations:rmm_alerts': 'alerts',
    # Alert policy's own sub-pages sit with it under Alerts.
    'ticket_routing:alert_rule_new': 'alerts', 'ticket_routing:alert_rule_edit': 'alerts',
    'ticket_routing:alert_maintenance': 'alerts',
    'support_workflows:admin_new': 'tools', 'support_workflows:admin_edit': 'tools',
    'accounts:ldap_group_mapping_delete': 'settings',
}
_CORE_SETTINGS_PREFIXES = ('settings_', 'security_', 'system_', 'firewall', 'fail2ban', 'snyk',
                           'webhook', 'maintenance', 'vault_visibility', 'mobile_apps', 'beta_test_admin')


def group_for(view_name):
    """The primary group a page belongs to ('' when none, e.g. account pages)."""
    view_name = view_name or ''
    if view_name in _WORK_PAGES:
        return _WORK_PAGES[view_name]
    if ('url', view_name) in GROUP_INDEX:
        return GROUP_INDEX[('url', view_name)]
    section = section_for(view_name)
    if section is not None:
        # Account / help sections live in the account menu, not the sidebar.
        return GROUP_INDEX.get(('section', section.key), '')
    namespace, _sep, url_name = view_name.rpartition(':')
    if namespace == 'monitoring':
        return 'devices' if url_name.startswith(_MONITORING_INFRA_PREFIXES) else 'alerts'
    if namespace == 'core' and url_name.startswith(_CORE_SETTINGS_PREFIXES):
        return 'settings'
    if namespace == 'accounts' and url_name.startswith(('organization', 'member', 'user_')):
        return 'clients'
    return NAMESPACE_GROUP.get(namespace, '')


class _PermProbe:
    """SectionPermissionMiddleware's decision for a path, without raising.

    One probe per render; each role flag is looked up once, so a sidebar
    with several /docs/ links costs one orgs_with_perm call.
    """

    def __init__(self, ctx):
        from accounts.middleware import SectionPermissionMiddleware
        self.user = _user(ctx)
        self.request = ctx.get('request')
        self.gate = SectionPermissionMiddleware(None)
        self._staff = None
        self._perm = {}

    def _is_staff(self):
        if self._staff is None:
            from psa.visibility import is_msp_staff
            self._staff = bool(is_msp_staff(self.user))
        return self._staff

    def allows(self, path):
        gate = self.gate
        if (path.startswith(gate.STAFF_ONLY_PREFIXES)
                and not path.startswith(gate.STAFF_ONLY_EXEMPT) and not self._is_staff()):
            return False
        perm = gate._required_perm(path)
        if perm is None:
            return True
        if perm not in self._perm:
            from types import SimpleNamespace
            from django.core.exceptions import PermissionDenied
            req = self.request
            if req is None or not hasattr(req, 'current_organization'):
                req = SimpleNamespace(current_organization=getattr(req, 'current_organization', None))
            try:
                gate._check(req, self.user, perm)
                self._perm[perm] = True
            except PermissionDenied:
                self._perm[perm] = False
        return self._perm[perm]


def _resolve_entry(entry, ctx, match, probe, current_section):
    if not _allowed(entry.gate, ctx):
        return None
    view_name = getattr(match, 'view_name', '') or ''
    if entry.section:
        section = SECTIONS_BY_KEY[entry.section]
        if not _allowed(section.gate, ctx):
            return None
        children = [t for t in resolve_tabs(section, ctx, match)
                    if not t['modal'] and not t['download']
                    and probe.allows(t['href'].split('?', 1)[0])]
        if not children:
            return None
        return {
            'key': section.key,
            'label': entry.label,
            'icon': f'fas {entry.icon}',
            'href': children[0]['href'],
            'active': current_section is not None and current_section.key == section.key,
            'keywords': entry.keywords,
            # A lone child would only repeat the entry.
            'children': children if len(children) > 1 else [],
        }
    try:
        href = reverse(entry.url_name, args=entry.args)
    except NoReverseMatch:
        return None
    if not probe.allows(href):
        return None
    return {
        'key': entry.url_name,
        'label': entry.label,
        'icon': f'fas {entry.icon}',
        'href': href,
        'active': view_name == entry.url_name,
        'keywords': entry.keywords,
        'children': [],
    }


def primary_nav(ctx):
    """The sidebar for this request.

    Returns ``{'groups', 'settings', 'active_group', 'breadcrumbs'}``. Each
    group is ``{key, label, icon, shortcut, href, active, entries}``; only
    groups with at least one visible entry are returned, and ``settings`` is
    None when the user may open none of its entries.
    """
    state = {'groups': [], 'settings': None, 'active_group': '', 'breadcrumbs': []}
    user = _user(ctx)
    if user is None or not user.is_authenticated:
        return state
    request = ctx.get('request')
    match = getattr(request, 'resolver_match', None) if request is not None else None
    view_name = getattr(match, 'view_name', '') or ''
    current_section = section_for(view_name)
    active_group = group_for(view_name)
    probe = _PermProbe(ctx)

    def build(group):
        entries = [e for e in (_resolve_entry(en, ctx, match, probe, current_section)
                               for en in group.entries) if e is not None]
        if not entries:
            return None
        return {
            'key': group.key,
            'label': group.label,
            'icon': f'fas {group.icon}',
            'shortcut': group.shortcut,
            'href': entries[0]['href'],
            'active': group.key == active_group,
            'entries': entries,
        }

    state['groups'] = [g for g in (build(g) for g in PRIMARY) if g is not None]
    state['settings'] = build(SETTINGS)
    state['active_group'] = active_group
    state['breadcrumbs'] = _breadcrumbs(state, getattr(request, 'path', ''))
    return state


def _breadcrumbs(state, path):
    """Group › entry › tab for the current page; the last crumb has no link."""
    groups = state['groups'] + ([state['settings']] if state['settings'] else [])
    group = next((g for g in groups if g['active']), None)
    if group is None:
        return []
    trail = [{'label': group['label'], 'href': group['href']}]
    entry = next((e for e in group['entries'] if e['active']), None)
    if entry is not None:
        if str(entry['label']) != str(group['label']):
            trail.append({'label': entry['label'], 'href': entry['href']})
        tab = next((c for c in entry['children'] if c['active']), None)
        if tab is not None and str(tab['label']) != str(trail[-1]['label']):
            trail.append({'label': tab['label'], 'href': tab['href']})
    if trail[-1]['href'] == path:
        trail[-1] = {'label': trail[-1]['label'], 'href': ''}
    return trail
