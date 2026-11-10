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
        Tab(_('Email Ingestion'), 'psa:email_config_list', 'fa-envelope-open-text'),
        Tab(_('AI Inbox'), 'psa_ai:inbox', 'fa-wand-magic-sparkles', gate=_ai_enabled),
    )),
    Section('psa_dispatch', 'psa', _('Dispatch Board'), gate=_psa, tabs=(
        Tab(_('Dispatch Board'), 'psa:dispatch_board', 'fa-table-list'),
        # Routing pages check their own permissions (manage / test / override).
        Tab(_('Routing Triage'), 'ticket_routing:triage', 'fa-inbox', gate=_msp_staff),
        Tab(_('Ticket Routing'), 'ticket_routing:overview', 'fa-route', gate=_msp_staff),
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
    Section('mod_reports', 'modules', _('Reports'), gate=_msp_staff, tabs=(
        Tab(_('Reports Home'), 'reports:home', 'fa-home'),
        Tab(_('Dashboards'), 'reports:dashboard_list', 'fa-th-large'),
        Tab(_('Wallboards'), 'reports:wallboard_list', 'fa-tv'),
        Tab(_('Generate Reports'), 'reports:template_list', 'fa-file-pdf'),
        Tab(_('Report History'), 'reports:generated_list', 'fa-history'),
    )),

    # ---- Assets -----------------------------------------------------------
    Section('assets_all', 'assets', _('All Assets'), tabs=(
        Tab(_('All Assets'), 'assets:asset_list', 'fa-box'),
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
    Section('vault_notes', 'vault', _('Secure Notes'), tabs=(
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
