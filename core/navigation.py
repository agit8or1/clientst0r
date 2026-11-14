"""The application's navigation, in one place.

Everything that links one page to another at the application level is built
from this module:

* the sidebar (``PRIMARY``: nine work sections, plus ``ADMIN`` pinned at its
  foot as one link to the settings center),
* the section tabs above a page's content (``SECTIONS``), with an overflow
  "More" menu and a per-section "Configure" menu (``Section.configure``),
* the breadcrumb trail (section › workspace › page),
* the settings center (``core:settings_home``) and the settings workspace
  header on every settings page (ten ``SETTINGS_CATEGORIES``, rendered by
  ``core/_settings_menu.html``),
* the top bar's shortcuts (``TOPBAR``) and the account menu,
* ``destinations_for(ctx)``: every destination the user may open, flat.

A *section* is a landing page plus the handful of sibling pages that belong
beside it; they render as a row of pills (``core/_section_tabs.html``) when
the current page is one of them, and the current one's are nested in the
sidebar.

Gating: every tab and entry carries a ``gate`` that mirrors the page's own
view-level check (feature flag, MSP staff, superuser, role permission,
OPTIONAL AI), and ``_PermProbe`` adds the URL-prefix rules
``SectionPermissionMiddleware`` applies. A link the server would answer with
403 is not drawn. Pages keep their own checks; hiding a link is presentation,
never access control. docs/navigation-map.md maps every old menu entry to its
place here, and core/tests/test_nav_reachability.py fails when a new
landing page has no link and no allow-list reason.
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


def _django_staff_or_superuser(ctx):
    """`user_passes_test(lambda u: u.is_staff or u.is_superuser)`: Django's
    is_staff flag, not the MSP-staff profile type."""
    u = _user(ctx)
    return bool(u is not None and (u.is_staff or u.is_superuser))


def _flag(name):
    def gate(ctx):
        return bool(ctx.get(name))
    return gate


def _ai_enabled(ctx):
    """OPTIONAL AI: the AI pages 404 or stay empty unless `psa_ai_enabled` is on."""
    return bool(getattr(ctx.get('system_settings'), 'psa_ai_enabled', False))


def _all(*gates):
    def gate(ctx):
        return all(g(ctx) for g in gates)
    return gate


def _current_org(ctx):
    request = ctx.get('request')
    org = getattr(request, 'current_organization', None) if request is not None else None
    return org if org is not None else ctx.get('current_organization')


def _has_org(ctx):
    return _current_org(ctx) is not None


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


def _check_contracts(u, ctx):
    """contracts.views.dashboard: MSP staff with contracts_view somewhere."""
    from contracts import permissions as contract_perms
    return _is_msp_staff(u) and contract_perms.has_any(u, contract_perms.VIEW)


def _check_contract_settings(u, ctx):
    from contracts import permissions as contract_perms
    return _is_msp_staff(u) and contract_perms.has_any(u, contract_perms.SETTINGS)


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


def _check_aging_reader(u, ctx):
    # Same rule as psa.views.aging_report: billing_view_aging somewhere.
    from accounts.permission_utils import orgs_with_perm
    allowed = orgs_with_perm(u, 'billing_view_aging')
    return allowed is None or bool(allowed)


def _perm(name):
    """`@require_perm(name)`: accounts.permission_utils.user_has_perm."""
    def check(u, ctx):
        from accounts.permission_utils import user_has_perm
        return user_has_perm(u, name)
    return _view_check(check)


def _org_perm(name):
    """A body check `has_perm_for_org(user, <selected client>, name)`; with no
    client selected the view redirects (or shows the global view), so the
    link stays."""
    def check(u, ctx):
        org = _current_org(ctx)
        if org is None:
            return True
        from accounts.permission_utils import has_perm_for_org
        return has_perm_for_org(u, org.pk, name)
    return _view_check(check)


def _check_access_rules(u, ctx):
    """vault.views._require_access_rules_perm: vault_manage_access_rules, and
    in the selected client when one is selected."""
    from accounts.permission_utils import user_has_org_perm, user_has_perm
    if not user_has_perm(u, 'vault_manage_access_rules'):
        return False
    org = _current_org(ctx)
    return org is None or user_has_org_perm(u, org, 'vault_manage_access_rules')


def _check_catalog_changes(u, ctx):
    """psa.views.catalog_change_list: staff (else 404) holding
    catalog_propose_change or catalog_approve_change."""
    from accounts.permission_utils import user_has_perm
    return ((u.is_superuser or bool(ctx.get('is_staff_user')))
            and (user_has_perm(u, 'catalog_propose_change')
                 or user_has_perm(u, 'catalog_approve_change')))


def _perm_any_org(name):
    """`@require_perm_any_org(name)`."""
    def check(u, ctx):
        from accounts.permission_utils import user_has_perm_any_org
        return user_has_perm_any_org(u, name)
    return _view_check(check)


def _msp_wide(name, legacy='membership'):
    """`reports.access.require_msp_wide_perm(name, legacy=...)`."""
    def check(u, ctx):
        from reports.access import has_msp_wide_perm
        return has_msp_wide_perm(u, name, legacy=legacy)
    return _view_check(check)


def _check_rmm_policy_reader(u, ctx):
    """rmm_permissions.views._gate: policy.manage or audit.review."""
    from rmm_permissions.views import _reader
    return _reader(u)


def _check_members(u, ctx):
    """accounts.views.member_list admits any active member of the current
    organization; the link is offered to those who administer it (Owner /
    Admin, or a role that manages or invites members)."""
    org = _current_org(ctx)
    if org is None:
        return False
    m = (u.memberships.filter(organization=org, is_active=True)
         .select_related('role_template').first())
    if m is None:
        return False
    if u.is_superuser or m.can_admin():
        return True
    from accounts.permission_utils import user_has_org_perm
    return (user_has_org_perm(u, org, 'org_manage_members')
            or user_has_org_perm(u, org, 'org_invite_members'))


def _check_roles(u, ctx):
    """accounts.roles_views.role_list: a current organization and
    _can_view_roles (roles_manage, or manage / invite members)."""
    org = _current_org(ctx)
    if org is None:
        return False
    from accounts.roles_views import _can_view_roles
    return _can_view_roles(u, org)


def _check_office_org_manager(u, ctx):
    """office.views_admin.org_policy: a current organization the user may
    manage (superuser, or org_manage_settings there)."""
    from office.views_admin import _can_manage_org
    return _can_manage_org(u, _current_org(ctx))


def _check_office_templates(u, ctx):
    """office.views_admin.template_list: _can_manage_org or superuser."""
    if u.is_superuser:
        return True
    from office.views_admin import _can_manage_org
    return _can_manage_org(u, _current_org(ctx))


def _check_field_ops_admin(u, ctx):
    """field_ops.views.settings_view: _org_admin_only."""
    from field_ops.views import _org_admin_only
    return _org_admin_only(u)


def _check_timesheet_approver(u, ctx):
    """psa.views._may_approve_timesheets."""
    if u.is_superuser:
        return True
    if not ctx.get('is_staff_user'):
        return False
    from accounts.permission_utils import orgs_with_perm
    return orgs_with_perm(u, 'resourcing_approve_leave') is None


def _check_catalog_manager(u, ctx):
    """assets.views_custom.require_catalog_manager."""
    from assets.views_custom import can_manage_asset_catalog
    return can_manage_asset_catalog(u)


_shift_manager = _view_check(_check_shift_manager)
_geo_admin = _view_check(_check_geo_admin)
_routing_manager = _view_check(_check_routing_manager)
_org_admin = _view_check(_check_org_admin)
_billing_reviewer = _view_check(_check_billing_reviewer)
_digest_reader = _perm('security_alerts_view')
_security_reader = _perm('security_alerts_view')
_aging_reader = _view_check(_check_aging_reader)
_rmm_policy_reader = _view_check(_check_rmm_policy_reader)
_members_admin = _view_check(_check_members)
_roles_reader = _view_check(_check_roles)
_office_org_manager = _view_check(_check_office_org_manager)
_office_templates = _view_check(_check_office_templates)
_field_ops_admin = _view_check(_check_field_ops_admin)
_timesheet_approver = _view_check(_check_timesheet_approver)
_catalog_manager = _view_check(_check_catalog_manager)


def _global_kb_alone(ctx):
    """base.html's old rule: Global KB sat in the bar only while PSA is off
    (with PSA on it is Service Management → Knowledge Base)."""
    return bool(ctx.get('global_kb_enabled') and not ctx.get('psa_enabled')
                and _staff_user_or_superuser(ctx))


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
    keywords: str = ''     # extra words the settings search matches
    # Sub-pages (forms, detail pages, a hub's children) that mark this tab
    # as the current one.
    also: tuple = ()
    # A shortcut to a page whose home is another section (My Work → My Tasks,
    # which lives in Scheduling). It is drawn in this section's strip but not
    # indexed here, never marked current here and not nested in the sidebar,
    # so the page keeps one place in the navigation.
    link_only: bool = False


@dataclass(frozen=True)
class Section:
    key: str
    menu: str
    label: str
    tabs: tuple
    gate: object = None
    # False where the landing page already carries its own local nav
    # (hardware/_nav.html, readiness/_nav.html), and for the settings
    # categories, whose pages render the settings workspace instead.
    render_tabs: bool = True
    # Pages that belong to the section for the navbar's active state but are
    # not tabs (forms, detail pages).
    also: tuple = field(default=())
    icon: str = ''
    # Secondary / configuration pages of the section (rules, templates,
    # connections). They are not sidebar links: they appear in the section's
    # "Configure" menu beside its tabs, in the sidebar filter and in
    # destinations_for(), each behind its own gate. They are indexed like
    # tabs, so their pages light this section.
    configure: tuple = ()


_psa = _flag('psa_enabled')
_workflows = _flag('workflows_enabled')
_contracts = _view_check(_check_contracts)

SECTIONS = (
    # ---- My Work ---------------------------------------------------------
    # The technician's own pages. The sidebar lists them flat (PRIMARY →
    # My Work); this section is their shared tab strip. Each tab carries the
    # gate of the page it opens.
    Section('psa_my_work', 'psa', _('My Work'), tabs=(
        Tab(_('My Queue'), 'psa:my_work', 'fa-inbox', gate=_psa,
            keywords='my work assigned sla timers waiting'),
        Tab(_('My Tasks'), 'scheduling:my_tasks', 'fa-list-check', gate=_flag('scheduling_enabled'),
            link_only=True),
        Tab(_('My Timesheet'), 'psa:my_timesheet', 'fa-clock', gate=_psa),
        Tab(_('Timesheet Approvals'), 'psa:timesheet_approval_queue', 'fa-user-clock',
            gate=_all(_psa, _timesheet_approver)),
        # resourcing.shift_views.schedule: a technician sees their own week.
        Tab(_('My Schedule'), 'resourcing:shift_schedule', 'fa-calendar-week', gate=_all(_msp_staff, _psa),
            link_only=True),
        Tab(_('My Leave'), 'resourcing:my_leave', 'fa-umbrella-beach'),
        Tab(_('My Resources'), 'resourcing:my_resourcing', 'fa-user-graduate',
            keywords='skills certifications working hours'),
        Tab(_('My Billable Target'), 'resourcing:my_billable_target', 'fa-bullseye'),
    )),

    # ---- Service Desk ------------------------------------------------------
    Section('psa_tickets', 'psa', _('Tickets'), gate=_psa, also=('psa:ticket_create',), tabs=(
        Tab(_('All Tickets'), 'psa:ticket_list', 'fa-list', keywords='tickets helpdesk'),
        Tab(_('My Queue'), 'psa:my_work', 'fa-inbox', link_only=True),
        Tab(_('AI Inbox'), 'psa_ai:inbox', 'fa-wand-magic-sparkles', gate=_ai_enabled),
    ), configure=(
        Tab(_('Recurring Tickets'), 'psa:recurring_list', 'fa-repeat'),
        Tab(_('Canned Replies'), 'psa:canned_reply_list', 'fa-magic'),
        Tab(_('Email Ingestion'), 'psa:email_config_list', 'fa-envelope-open-text'),
        # MSP-wide automation; the views are MSP staff only.
        Tab(_('Workflow Rules'), 'psa:workflow_rule_list', 'fa-bolt', gate=_msp_staff),
        Tab(_('Workflow Flow Map'), 'psa:workflow_rule_map', 'fa-project-diagram',
            # require_admin lets a customer's Owner in too; the map of every
            # rule is an MSP tool, so the link is offered to MSP staff only.
            gate=_all(_org_admin, _msp_staff)),
    )),
    Section('psa_dispatch', 'psa', _('Dispatch Board'), gate=_all(_msp_staff, _psa), tabs=(
        Tab(_('Dispatch Board'), 'psa:dispatch_board', 'fa-table-list'),
        # Routing pages check their own permissions (manage / test / override).
        Tab(_('Routing Triage'), 'ticket_routing:triage', 'fa-inbox', gate=_msp_staff),
        # psa.views.dispatch_heatmap: MSP staff (_staff_or_403).
        Tab(_('Load Heatmap'), 'psa:dispatch_heatmap', 'fa-table-cells'),
    ), configure=(
        Tab(_('Ticket Routing'), 'ticket_routing:overview', 'fa-route', gate=_msp_staff,
            keywords='routing rules queues on-call'),
    )),
    # Who works when, and where dispatch may see them.
    Section('psa_shifts', 'psa', _('Shifts & Locations'), gate=_all(_msp_staff, _psa), tabs=(
        Tab(_('Shift Schedule'), 'resourcing:shift_schedule', 'fa-user-clock'),
        # A technician's own opt-in to share their position with dispatch.
        Tab(_('Location Sharing'), 'field_ops:dispatch_sharing', 'fa-location-dot'),
        # field_ops.views.timeclock_dashboard: Django staff or superuser.
        Tab(_('Timeclock'), 'field_ops:timeclock_dashboard', 'fa-stopwatch',
            gate=_django_staff_or_superuser),
    ), configure=(
        Tab(_('Shift Templates'), 'resourcing:shift_templates', 'fa-layer-group', gate=_shift_manager),
        Tab(_('Dispatch Locations'), 'field_ops:dispatch_geo_settings', 'fa-map-location-dot',
            gate=_geo_admin),
    )),
    Section('ops_scheduling', 'ops', _('Scheduling'), gate=_flag('scheduling_enabled'), tabs=(
        Tab(_('All Tasks'), 'scheduling:task_list', 'fa-tasks'),
        Tab(_('My Tasks'), 'scheduling:my_tasks', 'fa-user-check'),
        Tab(_('Calendar'), 'scheduling:task_calendar', 'fa-calendar-alt'),
    ), configure=(
        Tab(_('Wallboard'), 'scheduling:wallboard_settings', 'fa-tv', gate=_msp_staff),
    )),
    Section('psa_projects', 'psa', _('Projects'), gate=_psa, tabs=(
        Tab(_('Projects'), 'psa:project_list', 'fa-diagram-project'),
    ), configure=(
        Tab(_('Project Templates'), 'psa:project_template_list', 'fa-clipboard-list'),
    )),
    Section('psa_service', 'psa', _('Service Management'), gate=_psa, tabs=(
        Tab(_('Service Catalog'), 'psa:service_catalog', 'fa-th'),
        Tab(_('Catalog Changes'), 'psa:catalog_change_list', 'fa-clipboard-check',
            gate=_view_check(_check_catalog_changes)),
        Tab(_('Change Requests'), 'psa:change_request_list', 'fa-code-branch', gate=_perm('change_view')),
        Tab(_('Problems'), 'psa:problem_list', 'fa-bug', gate=_perm('problem_view')),
        Tab(_('Releases'), 'psa:release_list', 'fa-rocket', gate=_perm('release_view')),
        Tab(_('Approvals'), 'psa:approval_list', 'fa-circle-check', gate=_msp_staff),
        # Its home is Knowledge & Vault → Knowledge Base.
        Tab(_('Knowledge Base'), 'psa:kb_browse', 'fa-book', gate=_msp_staff, link_only=True),
    )),
    # Workflows: runbooks (processes, a module switch), the ticket support
    # workflows (routing managers) and the rule templates / suggestions whose
    # home is Administration → Automation.
    Section('ops_workflows', 'ops', _('Workflows'), also=('support_workflows:admin_new',
                                                         'support_workflows:admin_edit'), tabs=(
        Tab(_('Runbooks'), 'processes:process_list', 'fa-tasks', gate=_all(_workflows, _org_perm('docs_view')),
            keywords='workflows processes procedures'),
        # processes.views.runbook_dashboard needs a customer selected.
        Tab(_('Workflow Dashboard'), 'processes:runbook_dashboard', 'fa-gauge', gate=_all(_workflows, _has_org),
            keywords='runbook dashboard'),
        Tab(_('Support Workflows'), 'support_workflows:admin', 'fa-diagram-next',
            gate=_all(_psa, _routing_manager), keywords='ticket workflows guided troubleshooting'),
        Tab(_('Templates'), 'psa:workflow_template_list', 'fa-clone', gate=_all(_psa, _msp_staff),
            link_only=True),
        # OPTIONAL AI: suggestions come from the AI engine.
        Tab(_('Suggestions'), 'psa:workflow_suggestion_list', 'fa-lightbulb',
            gate=_all(_psa, _msp_staff, _ai_enabled), link_only=True),
    )),

    # ---- Clients -------------------------------------------------------------
    # The organization list is every technician's "All clients" page (client
    # switcher) and a customer user's list of their organizations.
    Section('clients_all', 'clients', _('Clients'), tabs=(
        # The client workspace (owned by the client-workspace pages) and its
        # forms light Clients; the workspace draws its own ?tab= strip.
        Tab(_('All Clients'), 'accounts:organization_list', 'fa-building', also=(
            'accounts:organization_detail', 'accounts:organization_edit',
            'accounts:organization_create', 'accounts:organization_delete',
            'accounts:organization_service_info', 'accounts:ownership_transfer',
            'accounts:member_add', 'accounts:member_edit', 'accounts:member_remove')),
    )),

    # ---- Assets & Network ----------------------------------------------------
    Section('assets_all', 'assets', _('All Assets'), tabs=(
        Tab(_('All Assets'), 'assets:asset_list', 'fa-box'),
        Tab(_('Serial Search'), 'assets:serial_search', 'fa-barcode'),
        # require_organization_context: needs a customer selected.
        Tab(_('Network Scan Import'), 'assets:network_scan_import', 'fa-satellite-dish', gate=_has_org),
    )),
    # hardware/_nav.html already is this section's local nav.
    Section('assets_hardware', 'assets', _('Hardware & Ports'), render_tabs=False, tabs=(
        Tab(_('Devices'), 'hardware:device_list', 'fa-server'),
        Tab(_('Cables'), 'hardware:cable_list', 'fa-ethernet'),
        # The same VLAN records as IPAM → VLANs, seen from the switch ports
        # (tagged / untagged members, VLAN groups).
        Tab(_('VLAN Ports'), 'hardware:vlan_list', 'fa-layer-group', keywords='vlans tagged untagged groups'),
        Tab(_('Labels'), 'hardware:labels', 'fa-tags'),
        Tab(_('Import / export'), 'hardware:import_csv', 'fa-file-csv'),
        Tab(_('Hardware Catalog'), 'hardware:catalog', 'fa-book', keywords='models catalog'),
    )),
    Section('assets_diagrams', 'assets', _('Network Diagrams'), render_tabs=False, tabs=(
        Tab(_('Physical Connectivity'), 'hardware:diagram', 'fa-project-diagram', args=('connectivity',),
            keywords='connectivity topology'),
        Tab(_('VLAN View'), 'hardware:diagram', 'fa-sitemap', args=('vlan',)),
    )),
    Section('assets_infra', 'assets', _('Infrastructure'), tabs=(
        Tab(_('Racks'), 'monitoring:rack_list', 'fa-server'),
        Tab(_('Network Closets'), 'monitoring:network_closet_list', 'fa-network-wired'),
        Tab(_('Patch Panels'), 'monitoring:patch_panel_list', 'fa-grip'),
        Tab(_('Port Configurations'), 'assets:port_config_list', 'fa-ethernet'),
    )),
    Section('assets_ipam', 'assets', _('IPAM'), tabs=(
        Tab(_('Subnets & IPs'), 'monitoring:subnet_list', 'fa-sitemap', keywords='ipam subnets addresses'),
        # The VLAN register with its subnets (the canonical VLAN list).
        Tab(_('VLANs'), 'monitoring:vlan_list', 'fa-layer-group'),
    )),
    Section('ops_inventory', 'ops', _('Inventory'), gate=_all(_flag('inventory_enabled'), _staff_user_or_superuser), tabs=(
        Tab(_('Dashboard'), 'inventory:inventory_dashboard', 'fa-tachometer-alt'),
        Tab(_('All Items'), 'inventory:item_list', 'fa-boxes'),
        Tab(_('Low Stock'), 'inventory:low_stock_report', 'fa-exclamation-triangle'),
        Tab(_('Tools'), 'inventory:tool_list', 'fa-screwdriver-wrench'),
    )),
    # The fleet pages are MSP staff only (vehicles/urls.py).
    Section('ops_vehicles', 'ops', _('Vehicles'), gate=_all(_msp_staff, _flag('vehicles_enabled')),
            also=('vehicles:inventory_global_list', 'vehicles:inventory_by_vehicle',
                  'vehicles:shop_inventory_list'), tabs=(
        Tab(_('All Vehicles'), 'vehicles:vehicle_list', 'fa-truck'),
        Tab(_('Service Alerts'), 'vehicles:service_alert_list', 'fa-bell'),
        Tab(_('Vehicle Inventory'), 'vehicles:inventory_list', 'fa-boxes-stacked'),
    )),

    # ---- Business ------------------------------------------------------------
    Section('mod_crm', 'modules', _('CRM'), gate=_all(_msp_staff, _flag('crm_enabled')), tabs=(
        Tab(_('Overview'), 'crm:home', 'fa-home'),
        Tab(_('Pipeline'), 'crm:pipeline', 'fa-columns'),
        Tab(_('Leads'), 'crm:lead_list', 'fa-user-plus'),
        Tab(_('Opportunities'), 'crm:opportunity_list', 'fa-handshake'),
        Tab(_('Campaigns'), 'crm:campaign_list', 'fa-bullhorn'),
        Tab(_('Commissions'), 'crm:commission_list', 'fa-hand-holding-usd'),
        Tab(_('Commission Rules'), 'crm:commission_rule_list', 'fa-cogs'),
    )),
    # One Contracts heading over two distinct systems: the PSA service
    # agreements (billing) and the contract-document system (drafting,
    # clauses, signing). Each tab keeps its own gate.
    Section('mod_contracts', 'modules', _('Contracts'), tabs=(
        Tab(_('PSA Contracts'), 'psa:contract_list', 'fa-file-contract', gate=_psa,
            keywords='service agreements billing'),
        Tab(_('Contract Documents'), 'contracts:dashboard', 'fa-file-signature', gate=_contracts,
            keywords='agreements signing e-signature msa sow proposals'),
        Tab(_('Templates'), 'contracts:template_list', 'fa-file-lines', gate=_contracts),
        Tab(_('Clauses'), 'contracts:clause_list', 'fa-paragraph', gate=_contracts),
    ), configure=(
        Tab(_('Contract Settings'), 'contracts:settings', 'fa-sliders',
            gate=_all(_contracts, _view_check(_check_contract_settings))),
    )),
    Section('psa_quotes', 'psa', _('Quotes'), gate=_psa, tabs=(
        Tab(_('Quotes'), 'psa:quote_list', 'fa-file-invoice-dollar'),
    )),
    Section('psa_invoices', 'psa', _('Invoices'), gate=_psa, tabs=(
        Tab(_('Invoices'), 'psa:invoice_list', 'fa-file-invoice'),
    )),
    Section('psa_billing', 'psa', _('Billing'), gate=_psa, tabs=(
        Tab(_('Aging Report'), 'psa:aging_report', 'fa-chart-column', gate=_aging_reader),
        Tab(_('Billing Review'), 'psa:billing_review', 'fa-list-check', gate=_billing_reviewer),
    )),
    # Purchasing carries vendor costs: MSP staff only (psa.views._msp_staff_only).
    Section('psa_procurement', 'psa', _('Procurement'), gate=_all(_msp_staff, _psa), tabs=(
        Tab(_('Requisitions'), 'psa:requisition_list', 'fa-clipboard-list'),
        Tab(_('Purchase Orders'), 'psa:po_list', 'fa-file-invoice'),
        Tab(_('Back-orders'), 'psa:back_order_list', 'fa-hourglass-half'),
        Tab(_('Vendors'), 'psa:vendor_list', 'fa-truck', link_only=True),
    )),
    Section('psa_vendors', 'psa', _('Vendors'), gate=_all(_msp_staff, _psa), tabs=(
        Tab(_('Vendors'), 'psa:vendor_list', 'fa-truck'),
    )),
    Section('mod_pulse', 'modules', _('Pulse Checks'), gate=_all(_msp_staff, _flag('pulse_enabled')),
            also=('pulse:check_create', 'pulse:check_detail', 'pulse:check_edit', 'pulse:check_send',
                  'pulse:send_detail'), tabs=(
        Tab(_('Pulse Checks'), 'pulse:check_list', 'fa-heart-pulse'),
        Tab(_('Opt-outs'), 'pulse:opt_out_list', 'fa-user-slash'),
    )),

    # ---- Knowledge & Vault ---------------------------------------------------
    Section('docs_documents', 'docs', _('Documentation'), tabs=(
        Tab(_('Documents'), 'docs:document_list', 'fa-file-alt'),
        Tab(_('Office Templates'), 'office:template_list', 'fa-file-word', gate=_office_templates),
    )),
    # One Knowledge Base entry point: the PSA knowledge browser while PSA is
    # on, the documentation-side global KB list while it is off. Both read
    # the same global KB articles; each is staff only.
    Section('docs_kb', 'docs', _('Knowledge Base'), tabs=(
        Tab(_('Knowledge Base'), 'psa:kb_browse', 'fa-book', gate=_all(_psa, _msp_staff),
            keywords='kb articles global'),
        Tab(_('Knowledge Base'), 'docs:global_kb_list', 'fa-book', gate=_global_kb_alone,
            keywords='kb articles global'),
    )),
    Section('docs_diagrams', 'docs', _('Diagrams'), tabs=(
        Tab(_('Diagrams'), 'docs:diagram_list', 'fa-project-diagram'),
        Tab(_('Import Floor Plans'), 'locations:floor_plan_import', 'fa-file-upload',
            gate=_org_perm('assets_create')),
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
    Section('vault_passwords', 'vault', _('Password Vault'), tabs=(
        Tab(_('Passwords'), 'vault:password_list', 'fa-key'),
        # vault.views.vault_reveal_request_list: superuser or MSP staff.
        Tab(_('Reveal Requests'), 'vault:reveal_request_list', 'fa-eye', gate=_staff_user_or_superuser),
    ), configure=(
        Tab(_('Vault Access Rules'), 'vault:access_rule_list', 'fa-shield-halved',
            gate=_view_check(_check_access_rules)),
    )),
    Section('vault_personal', 'vault', _('My Vault'), tabs=(
        Tab(_('My Vault'), 'vault:personal_vault_list', 'fa-sticky-note'),
    )),
    Section('vault_notes', 'vault', _('Secure Notes'), gate=_flag('secure_notes_enabled'), tabs=(
        Tab(_('Inbox'), 'core:secure_note_inbox', 'fa-inbox'),
        Tab(_('Sent'), 'core:secure_note_sent', 'fa-paper-plane'),
        Tab(_('Secret Links'), 'core:secure_note_links_dashboard', 'fa-link'),
    )),

    # ---- Security & Monitoring ----------------------------------------------
    # Operational security (alerts, incidents); the administrative security
    # settings are Administration → Security.
    Section('mod_security', 'modules', _('Security Alerts'), gate=_all(_msp_staff, _psa), tabs=(
        Tab(_('Security Alerts'), 'security_alerts:alert_list', 'fa-triangle-exclamation'),
    ), configure=(
        Tab(_('Vendor Connections'), 'security_alerts:connection_list', 'fa-plug', keywords='edr'),
        Tab(_('Auto-Ticket Rules'), 'security_alerts:rule_list', 'fa-bolt'),
        Tab(_('SIEM Endpoints'), 'security_alerts:siem_endpoint_list', 'fa-tower-broadcast',
            gate=_security_reader),
        Tab(_('Weekly Digest'), 'security_alerts:digest_subscriptions', 'fa-envelope-open-text',
            gate=_digest_reader),
    )),
    # Incident handling: each view is @require_perm('security_alerts_view');
    # the MTTA report is reports_view_sla across every customer.
    Section('mod_security_ops', 'modules', _('Security Incidents'), gate=_all(_msp_staff, _psa), tabs=(
        Tab(_('Incidents'), 'security_alerts:incident_list', 'fa-fire', gate=_security_reader),
        Tab(_('Incident Playbooks'), 'security_alerts:playbook_list', 'fa-book-open', gate=_security_reader),
        Tab(_('Threat Overview'), 'security_alerts:threat_overview', 'fa-shield-virus',
            gate=_security_reader),
        Tab(_('Alert Response Times'), 'reports:security_alert_mtta', 'fa-stopwatch',
            gate=_msp_wide('reports_view_sla'), keywords='mtta security response analytics'),
    )),
    Section('ops_monitoring', 'ops', _('Monitoring'), gate=_flag('monitoring_enabled'), tabs=(
        Tab(_('Website Monitors'), 'monitoring:website_monitor_list', 'fa-globe'),
        Tab(_('WAN Connections'), 'monitoring:wan_monitor_list', 'fa-network-wired'),
        Tab(_('Expirations'), 'monitoring:expiration_list', 'fa-calendar-times'),
        Tab(_('Status Pages'), 'statuspage:list', 'fa-heart-pulse'),
        Tab(_('Configuration Backups'), 'netconfig:device_list', 'fa-file-code', keywords='config backups'),
    )),

    # ---- Reports -------------------------------------------------------------
    Section('mod_reports', 'modules', _('Reports'), gate=_all(_msp_staff, _flag('reports_enabled')), tabs=(
        Tab(_('Reports Home'), 'reports:home', 'fa-home'),
        Tab(_('Dashboards'), 'reports:dashboard_list', 'fa-th-large'),
        Tab(_('Analytics'), 'reports:analytics_overview', 'fa-chart-line',
            gate=_perm('reports_view_dashboards')),
        Tab(_('Wallboards'), 'reports:wallboard_list', 'fa-tv'),
        Tab(_('Generate Reports'), 'reports:template_list', 'fa-file-pdf'),
        Tab(_('Report History'), 'reports:generated_list', 'fa-history'),
        Tab(_('Software Compliance'), 'reports:software_compliance_report', 'fa-scale-balanced',
            gate=_msp_wide('assets_view', legacy='staff')),
        # Its home is Security & Monitoring → Security Incidents.
        Tab(_('Security Response Analytics'), 'reports:security_alert_mtta', 'fa-stopwatch',
            gate=_all(_psa, _msp_wide('reports_view_sla')), link_only=True),
    )),

    # ---- Settings center: ten categories -------------------------------------
    # The Administration landing (core:settings_home) shows them as cards;
    # each settings page carries the settings workspace header
    # (core/_settings_menu.html: category tabs plus the category's pages).
    # Every gate is the page's own check.
    Section('settings_general', 'settings', _('General'), icon='fa-sliders-h', render_tabs=False, tabs=(
        Tab(_('General Settings'), 'core:settings_general', 'fa-sliders-h', gate=_superuser,
            keywords='site name url timezone branding logo'),
        Tab(_('Customer Portal'), 'core:settings_portal', 'fa-door-open', gate=_superuser,
            keywords='portal customer client branding logo login sign-in background url host '
                     'hostname layout navigation theme colour color welcome support contact'),
        Tab(_('PSA'), 'core:settings_psa', 'fa-ticket-alt', gate=_all(_superuser, _psa),
            keywords='tickets portal surfaces ai optional', also=('psa:settings', 'psa:client_settings')),
        Tab(_('Custom Fields & Types'), 'assets:custom_field_list', 'fa-sliders-h',
            gate=_catalog_manager, keywords='asset types fields setup'),
        Tab(_('Tags'), 'core:tag_list', 'fa-tags', gate=_superuser,
            also=('core:tag_create', 'core:tag_edit', 'core:tag_delete')),
        Tab(_('Holidays'), 'resourcing:holiday_list', 'fa-calendar-day',
            gate=_perm_any_org('resourcing_manage_holidays'), keywords='public holidays calendar'),
        Tab(_('Equipment Catalog'), 'assets:vendor_list', 'fa-database', gate=_msp_staff,
            keywords='vendors models asset setup'),
    )),
    Section('settings_access', 'settings', _('Users & Access'), icon='fa-users-cog',
            render_tabs=False, tabs=(
        Tab(_('Users'), 'accounts:user_list', 'fa-user', gate=_superuser,
            also=('accounts:user_create', 'accounts:user_detail', 'accounts:user_edit')),
        Tab(_('Members'), 'accounts:member_list', 'fa-users', gate=_members_admin,
            keywords='invite team people'),
        Tab(_('Roles'), 'accounts:role_list', 'fa-id-badge', gate=_roles_reader,
            keywords='permissions templates', also=('accounts:role_review', 'accounts:role_compare',
                                                    'accounts:permission_catalog', 'accounts:portal_access',
                                                    'accounts:access_explain')),
        Tab(_('Access Management'), 'accounts:access_management', 'fa-users-cog', gate=_superuser,
            keywords='users roles permissions api keys'),
        Tab(_('Directory Services'), 'core:settings_directory', 'fa-address-book', gate=_superuser,
            keywords='ldap active directory azure'),
        Tab(_('LDAP Group Mappings'), 'accounts:ldap_group_mappings', 'fa-sitemap', gate=_superuser,
            keywords='directory active directory ldap groups roles',
            also=('accounts:ldap_group_mapping_delete',)),
        Tab(_('Audit Log'), 'audit:audit_log_list', 'fa-clipboard-list', gate=_org_admin,
            keywords='activity history who'),
    )),
    Section('settings_security', 'settings', _('Security'), icon='fa-shield-alt', render_tabs=False, tabs=(
        Tab(_('Security Dashboard'), 'core:security_dashboard', 'fa-chart-line', gate=_superuser,
            also=('core:package_scanner_dashboard', 'core:python_scanner_dashboard')),
        Tab(_('Security Settings'), 'core:settings_security', 'fa-shield-alt', gate=_superuser,
            keywords='password policy session 2fa'),
        Tab(_('Security Features'), 'core:security_features', 'fa-list-check', gate=_superuser),
        Tab(_('Technician Access'), 'tech_access:index', 'fa-user-shield', gate=_superuser,
            keywords='l1 l2 l3 presets assignments',
            also=('tech_access:why', 'tech_access:assignment_detail', 'tech_access:change_detail')),
        Tab(_('Superuser Approval'), 'tech_access:superuser_policy', 'fa-user-lock', gate=_superuser),
        Tab(_('RMM Permissions'), 'rmm_permissions:index', 'fa-user-lock', gate=_rmm_policy_reader,
            keywords='rmm roles overrides approvals remote actions policy',
            also=('rmm_permissions:approvals', 'rmm_permissions:technician', 'rmm_permissions:customer')),
        Tab(_('Vault Visibility'), 'core:vault_visibility', 'fa-eye-slash', gate=_superuser),
        Tab(_('Firewall & GeoIP'), 'core:firewall_settings', 'fa-shield-halved', gate=_superuser,
            keywords='ip rules country block', also=('core:firewall_ip_rules', 'core:firewall_country_rules',
                                                     'core:firewall_logs')),
        Tab(_('Fail2ban'), 'core:fail2ban_status', 'fa-ban', gate=_superuser),
        Tab(_('Vulnerability Scans'), 'core:snyk_scans', 'fa-bug', gate=_superuser, keywords='snyk'),
        Tab(_('Scan Configuration'), 'core:settings_snyk', 'fa-cog', gate=_superuser, keywords='snyk'),
    )),
    Section('settings_integrations', 'settings', _('Integrations'), icon='fa-plug', render_tabs=False, tabs=(
        Tab(_('Integrations'), 'integrations:integration_list', 'fa-plug', gate=_superuser,
            keywords='psa rmm m365 unifi connections overview'),
        Tab(_('RMM · Rem0te'), 'integrations:rem0te_setup', 'fa-desktop', gate=_superuser,
            keywords='remote access rmm'),
        Tab(_('Accounting'), 'integrations:accounting_list', 'fa-calculator', gate=_django_staff_or_superuser,
            keywords='quickbooks xero'),
        Tab(_('Distributors'), 'integrations:distributor_list', 'fa-warehouse',
            gate=_django_staff_or_superuser, keywords='pricing stock suppliers'),
        Tab(_('Webhooks'), 'core:webhook_list', 'fa-bolt', gate=_org_admin,
            also=('core:webhook_create', 'core:webhook_edit', 'core:webhook_delete',
                  'core:webhook_deliveries')),
        Tab(_('Office Documents'), 'office:settings', 'fa-file-word', gate=_superuser,
            keywords='onlyoffice collabora editor',
            also=('office:install', 'office:managed', 'office:quarantine_list', 'office:instance_new',
                  'office:instance_edit', 'office:instance_delete', 'office:instance_diagnostics',
                  'office:managed_diagnostics', 'office:onlyoffice_browser_probe')),
        Tab(_('Office Documents (organization)'), 'office:org_policy', 'fa-file-word',
            gate=_office_org_manager, keywords='office editing organization policy'),
    )),
    # OPTIONAL AI. The master switch (psa_ai_enabled) is in General → PSA;
    # these pages configure the provider and the ticket models, so they stay
    # open to superusers while the switch is off (the card says so).
    Section('settings_ai', 'settings', _('AI Configuration'), icon='fa-robot', render_tabs=False, tabs=(
        Tab(_('AI & LLM'), 'core:settings_ai', 'fa-robot', gate=_superuser,
            keywords='openai anthropic models optional ai provider'),
        Tab(_('Ticket AI models'), 'psa_ai:profiles', 'fa-wand-magic-sparkles', gate=_superuser,
            keywords='optional ai profiles'),
    )),
    Section('settings_automation', 'settings', _('Automation'), icon='fa-gears', render_tabs=False, tabs=(
        Tab(_('Task Scheduler'), 'core:settings_scheduler', 'fa-clock', gate=_superuser,
            keywords='cron jobs periodic'),
        Tab(_('Workflow Templates'), 'psa:workflow_template_list', 'fa-clone', gate=_all(_psa, _msp_staff),
            keywords='ticket rules starter'),
        # OPTIONAL AI: suggestions come from the AI engine.
        Tab(_('Workflow Suggestions'), 'psa:workflow_suggestion_list', 'fa-lightbulb',
            gate=_all(_psa, _msp_staff, _ai_enabled), keywords='ai rules'),
    )),
    Section('settings_email', 'settings', _('Communications'), icon='fa-envelope',
            render_tabs=False, tabs=(
        Tab(_('SMTP / Email'), 'core:settings_smtp', 'fa-envelope', gate=_superuser,
            keywords='mail outgoing smtp'),
        Tab(_('SMS Provider'), 'core:settings_sms', 'fa-sms', gate=_superuser, keywords='twilio text'),
        Tab(_('Consultation Requests'), 'core:consult_requests', 'fa-comments', gate=_superuser),
    )),
    Section('settings_features', 'settings', _('Modules'), icon='fa-puzzle-piece',
            render_tabs=False, tabs=(
        Tab(_('Feature Toggles'), 'core:settings_features', 'fa-toggle-on', gate=_superuser,
            keywords='enable disable psa crm features'),
        Tab(_('Optional Modules'), 'core:settings_modules', 'fa-puzzle-piece', gate=_superuser),
        Tab(_('Field Ops'), 'field_ops:settings', 'fa-location-crosshairs', gate=_field_ops_admin,
            keywords='gps geofence retention'),
    )),
    Section('settings_system', 'settings', _('System'), icon='fa-server', render_tabs=False, tabs=(
        Tab(_('System Status'), 'core:system_status', 'fa-heartbeat', gate=_superuser,
            keywords='health services disk'),
        Tab(_('System Updates'), 'core:system_updates', 'fa-sync-alt', gate=_superuser,
            keywords='upgrade version release'),
        Tab(_('Mobile Apps'), 'core:mobile_apps_admin', 'fa-mobile-alt', gate=_django_staff_or_superuser,
            keywords='android apk builds'),
        Tab(_('Beta tester requests'), 'core:beta_test_admin', 'fa-user-check', gate=_superuser),
    )),
    Section('settings_maintenance', 'settings', _('Maintenance'), icon='fa-tools', render_tabs=False, tabs=(
        Tab(_('Maintenance'), 'core:maintenance', 'fa-tools', gate=_superuser, keywords='cleanup backup'),
        Tab(_('Data Import'), 'imports:import_list', 'fa-file-import', gate=_superuser,
            keywords='migrate import', also=('imports:rehearsal_list',)),
        Tab(_('Data Export'), 'core:settings_data_export', 'fa-file-export', gate=_superuser),
        Tab(_('Demo Data'), 'core:settings_kb_import', 'fa-database', gate=_superuser,
            keywords='sample knowledge base import'),
        Tab(_('Vault Import'), 'core:vault_import', 'fa-key', gate=_superuser, keywords='passwords csv'),
    )),

    # ---- Account ----------------------------------------------------------
    Section('account_profile', 'account', _('My Profile'), tabs=(
        Tab(_('My Profile'), 'accounts:profile', 'fa-user'),
        # OPTIONAL AI: a technician's own provider keys (psa_ai.profile_views.own_keys).
        Tab(_('My AI keys'), 'psa_ai:own_keys', 'fa-key', gate=_all(_ai_enabled, _staff_user_or_superuser)),
    )),
    # The account menu's "My Work Details": the same pages as My Work's
    # resourcing tabs, whose home is the My Work section.
    Section('account_work', 'account', _('My Work Details'), tabs=(
        Tab(_('My Resources'), 'resourcing:my_resourcing', 'fa-user-graduate', link_only=True),
        Tab(_('My Leave'), 'resourcing:my_leave', 'fa-umbrella-beach', link_only=True),
        Tab(_('My Billable Target'), 'resourcing:my_billable_target', 'fa-bullseye', link_only=True),
    )),
    Section('account_help', 'account', _('Help'), tabs=(
        Tab(_('Documentation & Help'), 'core:help_index', 'fa-book'),
        Tab(_('Platform Documentation'), 'core:documentation', 'fa-book-open'),
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

# The settings workspace, in display order.
SETTINGS_CATEGORIES = tuple(s.key for s in SECTIONS if s.menu == 'settings')

# Pages outside any section still light up their top-level menu.
NAMESPACE_MENU = {
    'psa': 'psa', 'psa_ai': 'psa',
    'processes': 'ops', 'inventory': 'ops', 'scheduling': 'ops',
    'vehicles': 'ops', 'statuspage': 'ops', 'netconfig': 'ops',
    'security_alerts': 'modules', 'crm': 'modules', 'reports': 'modules', 'pulse': 'modules',
    'assets': 'assets', 'hardware': 'assets',
    'docs': 'docs', 'readiness': 'docs', 'locations': 'docs',
    'vault': 'vault',
    'resourcing': 'account',
    'integrations': 'settings',
}
# Monitoring hosts both the uptime tools (Operations) and the physical
# infrastructure pages (Assets → Infrastructure).
_MONITORING_INFRA_PREFIXES = ('rack', 'network_closet', 'subnet', 'ip_address',
                              'vlan', 'patch_panel')


def _build_index():
    """view name → its home section. Link-only tabs point at a page whose
    home is elsewhere and are skipped; configure pages belong to their
    section like tabs do."""
    index = {}
    for section in SECTIONS:
        for tab in section.tabs + section.configure:
            if tab.link_only:
                continue
            if tab.url_name:
                index.setdefault(tab.url_name, section)
            for name in tab.also:
                index.setdefault(name, section)
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
    view_name = getattr(match, 'view_name', '')
    if view_name in tab.also:
        return True
    if tab.url_name != view_name:
        return False
    if tab.args:
        return tuple(str(a) for a in tab.args) == tuple(str(a) for a in match.args) or \
            tuple(str(a) for a in tab.args) == tuple(str(v) for v in match.kwargs.values())
    return True


def _icon(name):
    return name if ' ' in name else f'fas {name}'


def _resolve(tabs, ctx, match):
    out = []
    for tab in tabs:
        if not _allowed(tab.gate, ctx):
            continue
        href = '#' if tab.modal else _href(tab)
        if not href:
            continue
        out.append({
            'key': tab.url_name,
            'label': tab.label,
            'href': href,
            'icon': _icon(tab.icon),
            'modal': tab.modal,
            'dom_id': tab.dom_id,
            'download': tab.download,
            'keywords': tab.keywords,
            'link_only': tab.link_only,
            'active': bool(match is not None and not tab.modal and not tab.link_only
                           and _is_current(tab, match)),
        })
    return out


def resolve_tabs(section, ctx, match=None):
    """The visible tabs of `section` for this context, as plain dicts."""
    return _resolve(section.tabs, ctx, match)


def resolve_configure(section, ctx, match=None, probe=None):
    """The section's Configure menu for this context: its configure pages
    that pass their gates (and, with a probe, the server's URL rules)."""
    if not section.configure or not _allowed(section.gate, ctx):
        return []
    items = [t for t in _resolve(section.configure, ctx, match) if not t['modal'] and not t['download']]
    if probe is not None:
        items = [t for t in items if probe.allows(t['href'].split('?', 1)[0])]
    return items


# A tab strip shows this many pills; when more survive the gates, the rest
# go into its "More" menu (one extra pill would cost what the menu does, so
# a strip of STRIP_TABS + 1 is drawn whole). The current page always stays
# among the visible pills. static/js/app_nav.js moves further pills into
# "More" when even these do not fit the row, so the strip never wraps.
STRIP_TABS = 6


def split_tabs(tabs, limit=STRIP_TABS):
    """(visible, more) for a strip of `tabs`."""
    tabs = list(tabs)
    if len(tabs) <= limit + 1:
        return tabs, []
    visible, more = tabs[:limit], tabs[limit:]
    current = next((t for t in more if t.get('active')), None)
    if current is not None:
        bumped = visible[-1]
        visible = visible[:-1] + [current]
        more = [bumped] + [t for t in more if t is not current]
    return visible, more


def _empty_state():
    return {'menu': '', 'section': '', 'section_label': '', 'tabs': [], 'tabs_visible': [],
            'tabs_more': [], 'configure': [], 'configure_active': None}


def nav_state(ctx):
    """What base.html needs for the current page.

    Returns ``{'menu', 'section', 'section_label', 'tabs', 'tabs_visible',
    'tabs_more', 'configure', 'configure_active'}``. ``tabs`` is non-empty
    only when the current page is itself one of the section's tabs or
    configure pages, the section is visible to this user, and more than one
    tab survives the gates — a strip with a single pill is noise.
    ``tabs_visible`` / ``tabs_more`` split it for the strip's "More" menu.
    ``configure`` is the section's Configure menu on those same pages.
    """
    state = _empty_state()
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
    own = [t for t in section.tabs + section.configure if not t.link_only]
    if not any(t.url_name == view_name for t in own):
        return state  # a form or detail page: highlight the menu, no strip
    tabs = resolve_tabs(section, ctx, match)
    if len(tabs) > 1:
        state['tabs'] = tabs
        state['tabs_visible'], state['tabs_more'] = split_tabs(tabs)
    if section.configure:
        state['configure'] = resolve_configure(section, ctx, match, _PermProbe(ctx))
        state['configure_active'] = next((c for c in state['configure'] if c['active']), None)
    return state


# =============================================================================
# Primary navigation: the sidebar.
#
# Ten sections (Dashboard, My Work, Service Desk, Clients, Assets & Network,
# Business, Knowledge & Vault, Security & Monitoring, Reports, and
# Administration pinned at the sidebar's foot). Each group's entries point at
# a SECTION above (its landing page is the first tab this user may open) or
# at a single page. The current entry's tabs are nested under it; a section's
# Configure pages are not sidebar links but stay findable through the
# sidebar filter (primary_nav()['extra']) and destinations_for().
# Administration is one link, to the settings center (core:settings_home),
# whose cards are the settings categories.
#
# Two layers of gating, both evaluated per request:
#   * the entry's own gate plus its section's gate (feature flags, staff,
#     superuser, role permissions, OPTIONAL AI): the page's own conditions;
#   * `_PermProbe`: the URL-prefix rules SectionPermissionMiddleware applies
#     (staff-only /reports/ /crm/ /security/ ..., and the vault_view /
#     docs_view / assets_view role flags for the current customer). A link the
#     server would answer with 403 is not drawn.
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
    shortcut: str = ''     # "g <key>" opens this entry (first visible wins)
    nest: bool = True      # False: the section's tabs are not drawn under it
    # The url takes the selected client's id (Client Workspace); the entry is
    # drawn only while a client is selected.
    current_org: bool = False


@dataclass(frozen=True)
class Group:
    key: str
    label: str
    icon: str
    entries: tuple
    shortcut: str = ''     # "g <key>" opens the group's landing page
    gate: object = None


PRIMARY = (
    # The user's shortcut pins (core/shortcut_strip.py) are appended to this
    # group per request; see _overview_pins().
    Group('dashboard', _('Dashboard'), 'fa-gauge-high', shortcut='h', entries=(
        Entry(_('Overview'), url_name='core:dashboard', icon='fa-tachometer-alt',
              keywords='home dashboard personalized widgets'),
        Entry(_('Favorites'), url_name='core:favorite_list', icon='fa-star', keywords='starred'),
    )),
    # The technician's own pages, flat; their tab strip is SECTIONS
    # psa_my_work. My Tasks and My Schedule open the Scheduling and Shifts
    # pages; My Leave / Resources / Billable Target are also in the account
    # menu (My Work Details).
    Group('my_work', _('My Work'), 'fa-clipboard-check', shortcut='w', entries=(
        Entry(_('My Queue'), url_name='psa:my_work', icon='fa-inbox', gate=_psa,
              keywords='my work workspace assigned sla timers approvals'),
        Entry(_('My Tasks'), url_name='scheduling:my_tasks', icon='fa-list-check',
              gate=_flag('scheduling_enabled'), keywords='scheduled tasks'),
        Entry(_('My Timesheet'), url_name='psa:my_timesheet', icon='fa-clock', gate=_psa,
              keywords='time entries hours log time'),
        Entry(_('Timesheet Approvals'), url_name='psa:timesheet_approval_queue', icon='fa-user-clock',
              gate=_all(_psa, _timesheet_approver)),
        Entry(_('My Schedule'), url_name='resourcing:shift_schedule', icon='fa-calendar-week',
              gate=_all(_msp_staff, _psa), keywords='shifts rota on-call week'),
        Entry(_('My Leave'), url_name='resourcing:my_leave', icon='fa-umbrella-beach',
              keywords='holiday vacation time off'),
        Entry(_('My Resources'), url_name='resourcing:my_resourcing', icon='fa-user-graduate',
              keywords='skills certifications working hours'),
        Entry(_('My Billable Target'), url_name='resourcing:my_billable_target', icon='fa-bullseye',
              keywords='utilization target'),
    )),
    Group('service_desk', _('Service Desk'), 'fa-headset', shortcut='t', entries=(
        Entry(_('Tickets'), section='psa_tickets', icon='fa-ticket',
              keywords='psa helpdesk queue ai inbox'),
        Entry(_('Dispatch Board'), section='psa_dispatch', icon='fa-table-list', nest=False,
              keywords='schedule routing triage heatmap'),
        Entry(_('Scheduling'), section='ops_scheduling', icon='fa-calendar-alt',
              keywords='tasks calendar wallboard'),
        Entry(_('Shifts & Locations'), section='psa_shifts', icon='fa-user-clock',
              keywords='shift schedule templates rota on-call dispatch location sharing consent geo timeclock'),
        Entry(_('Projects'), section='psa_projects', icon='fa-diagram-project'),
        Entry(_('Service Management'), section='psa_service', icon='fa-th',
              keywords='itil catalog change problem release approvals'),
        Entry(_('Workflows'), section='ops_workflows', icon='fa-diagram-next',
              keywords='runbooks processes support workflows templates suggestions'),
    )),
    Group('clients', _('Clients'), 'fa-building', shortcut='c', entries=(
        Entry(_('All Clients'), section='clients_all', icon='fa-building',
              keywords='customers organizations clients'),
        # The selected client's workspace (accounts:organization_detail).
        Entry(_('Client Workspace'), url_name='accounts:organization_detail', icon='fa-id-card',
              current_org=True, gate=_has_org, keywords='current client overview workspace'),
        Entry(_('Customer Operations'), url_name='core:customer_ops_current', icon='fa-binoculars',
              keywords='sla uptime renewals invoices aging'),
    )),
    Group('assets', _('Assets & Network'), 'fa-server', shortcut='d', entries=(
        Entry(_('All Assets'), section='assets_all', icon='fa-box',
              keywords='devices inventory serial relationships'),
        Entry(_('RMM Devices'), url_name='integrations:rmm_devices', icon='fa-desktop',
              gate=_msp_staff, keywords='agents endpoints online offline'),
        Entry(_('Device Workspace'), url_name='assets:device_workspace_home', icon='fa-laptop-medical',
              gate=_msp_staff, keywords='workspace connect diagnose patches recent devices'),
        Entry(_('Hardware & Ports'), section='assets_hardware', icon='fa-network-wired',
              keywords='devices cables vlans labels catalog'),
        Entry(_('Network Diagrams'), section='assets_diagrams', icon='fa-project-diagram',
              keywords='connectivity topology vlan view'),
        Entry(_('Infrastructure'), section='assets_infra', icon='fa-server',
              keywords='racks closets patch panels ports'),
        Entry(_('IPAM'), section='assets_ipam', icon='fa-sitemap', keywords='subnets ip addresses vlans'),
        Entry(_('Inventory'), section='ops_inventory', icon='fa-boxes', keywords='stock tools low'),
        Entry(_('Vehicles'), section='ops_vehicles', icon='fa-truck-pickup', keywords='fleet'),
    )),
    Group('business', _('Business'), 'fa-briefcase', shortcut='b', entries=(
        Entry(_('CRM'), section='mod_crm', icon='fa-chart-pie',
              keywords='sales pipeline leads opportunities campaigns commissions'),
        Entry(_('Contracts'), section='mod_contracts', icon='fa-file-signature',
              keywords='psa contracts agreements documents signing templates clauses'),
        Entry(_('Quotes'), section='psa_quotes', icon='fa-file-invoice-dollar', keywords='proposals'),
        Entry(_('Invoices'), section='psa_invoices', icon='fa-file-invoice'),
        Entry(_('Billing'), section='psa_billing', icon='fa-money-check-dollar',
              keywords='aging billing review'),
        Entry(_('Procurement'), section='psa_procurement', icon='fa-cart-shopping',
              keywords='requisitions purchase orders back-orders'),
        Entry(_('Vendors'), section='psa_vendors', icon='fa-truck', keywords='suppliers'),
        Entry(_('Pulse Checks'), section='mod_pulse', icon='fa-heart-pulse',
              keywords='feedback survey nps satisfaction client health'),
    )),
    Group('knowledge', _('Knowledge & Vault'), 'fa-book-open', shortcut='k', entries=(
        Entry(_('Documentation'), section='docs_documents', icon='fa-file-alt',
              keywords='docs documents office templates'),
        Entry(_('Knowledge Base'), section='docs_kb', icon='fa-book', keywords='kb articles'),
        Entry(_('Diagrams'), section='docs_diagrams', icon='fa-project-diagram', keywords='floor plans'),
        Entry(_('Review & Publishing'), section='docs_review', icon='fa-check-double',
              keywords='drafts approval review archived kb analytics'),
        Entry(_('Documentation Readiness'), section='docs_readiness', icon='fa-clipboard-check'),
        Entry(_('Password Vault'), section='vault_passwords', icon='fa-key',
              keywords='passwords vault credentials reveal access rules'),
        Entry(_('My Vault'), section='vault_personal', icon='fa-sticky-note',
              keywords='personal passwords'),
        Entry(_('Secure Notes'), section='vault_notes', icon='fa-lock', keywords='inbox share secret links'),
    )),
    Group('security', _('Security & Monitoring'), 'fa-shield-halved', shortcut='a', entries=(
        Entry(_('Security Alerts'), section='mod_security', icon='fa-triangle-exclamation',
              keywords='edr siem vendor connections auto-ticket rules digest'),
        Entry(_('Security Incidents'), section='mod_security_ops', icon='fa-fire',
              keywords='incidents playbooks threats mtta response'),
        Entry(_('RMM Alerts'), url_name='integrations:rmm_alerts', icon='fa-bell',
              gate=_msp_staff, keywords='monitoring rmm alerts'),
        # Which RMM / monitoring alerts open tickets, and maintenance windows.
        Entry(_('Alert Policies'), url_name='ticket_routing:alerts', icon='fa-sliders',
              gate=_all(_psa, _routing_manager),
              keywords='alert policy rules auto ticket maintenance suppression rmm'),
        Entry(_('Monitoring'), section='ops_monitoring', icon='fa-globe',
              keywords='uptime websites wan expirations status pages config backups'),
    )),
    Group('reports', _('Reports'), 'fa-chart-column', shortcut='r', entries=(
        Entry(_('Reports'), section='mod_reports', icon='fa-chart-bar',
              keywords='dashboards wallboards analytics compliance history'),
    )),
)

# Administration, pinned at the sidebar's foot: one link to the settings
# center (core:settings_home), which lists these ten categories as cards.
# The entries stay the categories, each landing on its first page this user
# may open (settings_workspace(), the workspace header, destinations_for()).
# Customer users never get this group; an organization administrator on the
# customer side reaches the pages their own checks admit (Members, Roles,
# Webhooks, Office policy) from the account menu's "Organization settings".
ADMIN = Group('settings', _('Administration'), 'fa-gear', shortcut='s', gate=_msp_staff, entries=tuple(
    Entry(SECTIONS_BY_KEY[key].label, section=key, icon=SECTIONS_BY_KEY[key].icon, nest=False,
          keywords=' '.join(str(t.label) for t in SECTIONS_BY_KEY[key].tabs))
    for key in SETTINGS_CATEGORIES
))
# Kept for callers that still say SETTINGS.
SETTINGS = ADMIN

ALL_GROUPS = PRIMARY + (ADMIN,)

# Top-bar shortcuts: (entry key, label, icon). Each is drawn only when that
# entry is in this user's sidebar, with the sidebar's href.
TOPBAR = (
    ('core:dashboard', _('Dashboard'), 'fa-tachometer-alt'),
    ('psa:my_work', _('My Work'), 'fa-clipboard-check'),
    ('psa_tickets', _('Tickets'), 'fa-ticket'),
    ('clients_all', _('Clients'), 'fa-building'),
    ('assets_all', _('Assets'), 'fa-server'),
    ('psa_projects', _('Projects'), 'fa-diagram-project'),
    ('mod_reports', _('Reports'), 'fa-chart-bar'),
)


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
    'psa': 'service_desk', 'psa_ai': 'service_desk', 'ticket_routing': 'service_desk',
    'processes': 'service_desk', 'scheduling': 'service_desk', 'field_ops': 'service_desk',
    'support_workflows': 'service_desk',
    'resourcing': 'my_work',
    'inventory': 'assets', 'vehicles': 'assets',
    'assets': 'assets', 'hardware': 'assets', 'network_discovery': 'assets', 'locations': 'assets',
    'statuspage': 'security', 'netconfig': 'security', 'security_alerts': 'security',
    'crm': 'business', 'pulse': 'business', 'contracts': 'business',
    'reports': 'reports',
    'docs': 'knowledge', 'readiness': 'knowledge', 'vault': 'knowledge',
    'integrations': 'settings', 'tech_access': 'settings', 'imports': 'settings',
    'audit': 'settings', 'rmm_permissions': 'settings',
}
# PSA pages that are commercial rather than service work.
_PSA_BUSINESS_PREFIXES = ('invoice', 'quote', 'contract', 'aging', 'billing', 'requisition',
                          'po_', 'purchase', 'back_order', 'vendor', 'credit_memo')
# Integrations pages a technician works in daily, not configuration.
_WORK_PAGES = {
    'integrations:rmm_devices': 'assets', 'integrations:rmm_device_detail': 'assets',
    'integrations:rmm_device_delete': 'assets', 'integrations:rmm_software': 'assets',
    'integrations:rmm_alerts': 'security',
    # Alert policy's own sub-pages sit with it under Security & Monitoring.
    'ticket_routing:alerts': 'security',
    'ticket_routing:alert_rule_new': 'security', 'ticket_routing:alert_rule_edit': 'security',
    'ticket_routing:alert_maintenance': 'security',
    'accounts:ldap_group_mapping_delete': 'settings',
    'reports:security_alert_mtta': 'security',
    'core:settings_home': 'settings',
}
_CORE_SETTINGS_PREFIXES = ('settings_', 'security_', 'system_', 'firewall', 'fail2ban', 'snyk',
                           'webhook', 'maintenance', 'vault_visibility', 'mobile_apps', 'beta_test_admin',
                           'tag_', 'consult_requests', 'vault_import', 'package_scanner',
                           'python_scanner')


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
        return 'assets' if url_name.startswith(_MONITORING_INFRA_PREFIXES) else 'security'
    if namespace == 'core' and url_name.startswith(_CORE_SETTINGS_PREFIXES):
        return 'settings'
    if namespace == 'core' and url_name.startswith('secure_note'):
        return 'knowledge'
    if namespace == 'psa' and url_name.startswith(_PSA_BUSINESS_PREFIXES):
        return 'business'
    if namespace == 'psa' and url_name.startswith('kb_'):
        return 'knowledge'
    if namespace == 'accounts' and url_name.startswith('organization'):
        return 'clients'
    if namespace == 'accounts' and url_name.startswith(('member', 'user_', 'role', 'ldap')):
        return 'settings'
    if namespace == 'office' and not url_name.startswith(('edit', 'open', 'new_', 'document')):
        return 'settings'
    return NAMESPACE_GROUP.get(namespace, '')


# The permission decorators a view may carry (accounts.permission_utils,
# reports.access), by the qualified name of the wrapper they install.
_PERM_DECORATORS = {
    # accounts.permission_utils
    'require_perm.<locals>.decorator.<locals>._wrapped': 'perm',
    'require_perm_any_org.<locals>.decorator.<locals>._wrapped': 'any_org',
    # reports.access
    'require_msp_wide_perm.<locals>.decorator.<locals>._wrapped': 'msp_wide',
    # psa.routing.permissions
    'require_routing_perm.<locals>.decorator.<locals>.wrapped': 'routing',
    # hardware.access (a client selected and the flag in it)
    'org_view.<locals>.deco.<locals>.wrapper': 'hardware_org',
    'catalog_view.<locals>.wrapper': 'hardware_catalog',
    # core.decorators
    'require_admin.<locals>.wrapper': 'org_admin',
}
_VIEW_REQUIREMENTS = {}


def _view_requirements(path):
    """The role-permission decorators on the view that serves `path`, as
    ``((kind, perm, legacy), ...)``, read from the decorator chain itself
    (functools.wraps keeps ``__wrapped__``), so a link follows the exact
    check the view applies. Cached per path; the URLconf does not change at
    run time."""
    if path in _VIEW_REQUIREMENTS:
        return _VIEW_REQUIREMENTS[path]
    from django.urls import Resolver404, resolve
    reqs = []
    try:
        f = resolve(path).func
    except Resolver404:
        f = None
    seen = set()
    while f is not None and id(f) not in seen:
        seen.add(id(f))
        # functools.wraps copies __qualname__; the code object keeps its own.
        code = getattr(f, '__code__', None)
        kind = _PERM_DECORATORS.get(getattr(code, 'co_qualname', ''))
        if kind:
            cells = dict(zip(f.__code__.co_freevars, f.__closure__ or ()))
            perm = cells.get('perm_name') or cells.get('perm')
            legacy = cells['legacy'].cell_contents if 'legacy' in cells else None
            reqs.append((kind, perm.cell_contents if perm is not None else None, legacy))
        f = getattr(f, '__wrapped__', None)
    _VIEW_REQUIREMENTS[path] = tuple(reqs)
    return _VIEW_REQUIREMENTS[path]


class _PermProbe:
    """Would the server open `path` for this user? Without raising.

    Two checks, both the server's own: SectionPermissionMiddleware's URL-prefix
    rule, and the role-permission decorators on the view itself
    (``require_perm``, ``require_perm_any_org``, ``require_msp_wide_perm``).
    Checks made inside a view body are mirrored by the tab gates above.

    One probe per render; each answer is looked up once, so a sidebar with
    several /docs/ links costs one orgs_with_perm call.
    """

    def __init__(self, ctx):
        from accounts.middleware import SectionPermissionMiddleware
        self.ctx = ctx
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
        for req in _view_requirements(path):
            if not self._view_allows(*req):
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

    def _view_allows(self, kind, perm, legacy):
        key = (kind, perm, legacy)
        if key not in self._perm:
            u = self.user
            if kind == 'perm':
                from accounts.permission_utils import user_has_perm
                ok = user_has_perm(u, perm)
            elif kind == 'any_org':
                from accounts.permission_utils import user_has_perm_any_org
                ok = user_has_perm_any_org(u, perm)
            elif kind == 'msp_wide':
                from reports.access import has_msp_wide_perm
                ok = has_msp_wide_perm(u, perm, legacy=legacy or 'membership')
            elif kind == 'routing':
                from psa.routing.permissions import has_routing_perm
                ok = has_routing_perm(u, perm)
            elif kind == 'hardware_org':
                # No client selected: the view redirects to pick one.
                from accounts.permission_utils import user_has_org_perm
                org = _current_org(self.ctx)
                ok = org is None or user_has_org_perm(u, org, perm)
            elif kind == 'hardware_catalog':
                from accounts.permission_utils import user_has_perm
                from hardware.access import can_manage_catalog
                ok = user_has_perm(u, 'assets_view') or can_manage_catalog(u)
            elif kind == 'org_admin':
                ok = _check_org_admin(u, self.ctx)
            else:
                ok = True
            self._perm[key] = bool(ok)
        return self._perm[key]


def _section_children(section, ctx, match, probe):
    if not _allowed(section.gate, ctx):
        return []
    return [t for t in resolve_tabs(section, ctx, match)
            if not t['modal'] and not t['download']
            and probe.allows(t['href'].split('?', 1)[0])]


def _resolve_entry(entry, ctx, match, probe, current_section):
    if not _allowed(entry.gate, ctx):
        return None
    view_name = getattr(match, 'view_name', '') or ''
    if entry.section:
        section = SECTIONS_BY_KEY[entry.section]
        tabs = _section_children(section, ctx, match, probe)
        configure = resolve_configure(section, ctx, match, probe)
        if not tabs and not configure:
            return None
        own = [t for t in tabs if not t['link_only']]
        keywords = entry.keywords
        if not entry.nest:
            keywords = ' '.join([str(keywords)] + [str(c['label']) for c in tabs])
        return {
            'key': section.key,
            'label': entry.label,
            'icon': f'fas {entry.icon}',
            'href': (own or tabs or configure)[0]['href'],
            'active': current_section is not None and current_section.key == section.key,
            'keywords': keywords,
            'shortcut': entry.shortcut,
            # Drawn under the entry while it is current. A lone child would
            # only repeat the entry; link-only tabs live elsewhere.
            'children': own if (entry.nest and len(own) > 1) else [],
            # Every tab, for the breadcrumb trail, search and destinations.
            'tabs': tabs,
            # The section's Configure pages (not drawn in the sidebar).
            'configure': configure,
        }
    args = entry.args
    if entry.current_org:
        org = _current_org(ctx)
        if org is None:
            return None
        args = (org.pk,)
    try:
        href = reverse(entry.url_name, args=args)
    except NoReverseMatch:
        return None
    if not probe.allows(href):
        return None
    return {
        'key': entry.url_name,
        'label': entry.label,
        'icon': f'fas {entry.icon}',
        'href': href,
        'active': view_name == entry.url_name and (
            not entry.current_org or tuple(str(a) for a in args) == tuple(
                str(v) for v in (getattr(match, 'args', ()) or tuple(getattr(match, 'kwargs', {}).values())))),
        'keywords': entry.keywords,
        'shortcut': entry.shortcut,
        'children': [],
        'tabs': [],
        'configure': [],
    }


def _overview_pins(ctx, probe, taken, path):
    """The user's shortcut pins as Dashboard entries (MSP staff only, the
    same eligibility and gates as the old strip), skipping any already in
    the group, plus the link that edits them."""
    from core import shortcut_strip
    user = _user(ctx)
    try:
        if not shortcut_strip.strip_eligible(user):
            return [], ''
        flags = {n: bool(ctx.get(n)) for n in ('psa_enabled', 'crm_enabled', 'workflows_enabled',
                                                'scheduling_enabled', 'monitoring_enabled',
                                                'reports_enabled')}
        pins = shortcut_strip.resolve_pins(user, flags)
    except Exception:
        return [], ''
    out = []
    for pin in pins:
        if pin['url'] in taken or not probe.allows(pin['url']):
            continue
        out.append({
            'key': f"pin:{pin['key']}",
            'label': pin['label'],
            'icon': f"fas {pin['icon']}",
            'href': pin['url'],
            'active': pin['url'] == path,
            'keywords': 'pinned shortcut',
            'shortcut': '',
            'children': [],
            'tabs': [],
            'pin': True,
        })
    try:
        edit = reverse('accounts:shortcut_pins_edit')
    except NoReverseMatch:
        edit = ''
    return out, edit


def settings_home_url():
    try:
        return reverse('core:settings_home')
    except NoReverseMatch:  # pragma: no cover - the route exists
        return ''


def settings_workspace(ctx, probe=None, match=None):
    """The settings categories this user may open.

    Returns ``{'categories', 'current'}``: each category is ``{key, label,
    icon, href, active, tabs}`` (only categories with a visible page), and
    ``current`` is the category holding the current page, or None.
    """
    probe = probe or _PermProbe(ctx)
    if match is None:
        request = ctx.get('request')
        match = getattr(request, 'resolver_match', None) if request is not None else None
    current_section = section_for(getattr(match, 'view_name', '') or '')
    cats = []
    for key in SETTINGS_CATEGORIES:
        section = SECTIONS_BY_KEY[key]
        tabs = _section_children(section, ctx, match, probe)
        if not tabs:
            continue
        cats.append({
            'key': key,
            'label': section.label,
            'icon': f'fas {section.icon}',
            'href': tabs[0]['href'],
            'active': current_section is not None and current_section.key == key,
            'tabs': tabs,
        })
    current = next((c for c in cats if c['active']), None)
    return {'categories': cats, 'current': current}


def _account_menu(ctx, workspace, nav_section, view_name=''):
    """The account menu, in order. Entries are links ('href') or buttons that
    open a modal ('modal') or run a page action ('action')."""
    u = _user(ctx)
    items = []

    def section_link(key, icon, title):
        section = SECTIONS_BY_KEY[key]
        tabs = [t for t in resolve_tabs(section, ctx) if not t['modal'] and not t['download']]
        if tabs:
            items.append({'label': section.label, 'icon': f'fas {icon}', 'href': tabs[0]['href'],
                          'title': title,
                          'active': nav_section == key or any(t['key'] == view_name for t in tabs)})

    section_link('account_profile', 'fa-user', _('View and edit your user profile'))
    section_link('account_work', 'fa-user-graduate',
                 _('Skills, certifications, working hours, leave and billable target'))
    section_link('account_help', 'fa-book', _('Documentation, about, roadmap and bug reports'))
    # Apps & Downloads is reached through "Install app" below (its first tab).
    # Customer-side organization administrators have no Administration group;
    # this is their way to the settings center, which lists only the pages
    # their own checks admit.
    if workspace['categories'] and not _msp_staff(ctx):
        items.append({'label': _('Organization settings'), 'icon': 'fas fa-users-cog',
                      'href': settings_home_url() or workspace['categories'][0]['href'],
                      'title': _('Members, roles and organization settings'),
                      'active': workspace['current'] is not None or view_name == 'core:settings_home'})
    items.append({'divider': True})
    # The three controls that used to sit in the bar, with the same
    # accessible names (the visible label is the name) and tooltips.
    for label, icon, url_name, title in (
            (_('Beta app'), 'fas fa-mobile-screen-button', 'core:beta_test_signup',
             _('Beta-test the Android app')),
            (_('Install app'), 'fas fa-download', 'core:install_app',
             _('Install the app on your phone or desktop'))):
        try:
            items.append({'label': label, 'icon': icon, 'href': reverse(url_name), 'aria': label,
                          'title': title,
                          'active': url_name == 'core:install_app' and nav_section == 'account_apps'})
        except NoReverseMatch:
            pass
    # Rendered by core/_help_us_grow_button.html (opens #supportProjectModal).
    items.append({'label': _('Help Us Grow'), 'help_grow': True})
    items.append({'label': _('Toggle dark / light theme'), 'icon': 'fas fa-circle-half-stroke',
                  'action': 'toggleTheme', 'title': _('Toggle between dark and light theme')})
    return items if u is not None else []


def _empty_primary():
    return {'groups': [], 'settings': None, 'active_group': '', 'breadcrumbs': [],
            'workspace': {'categories': [], 'current': None}, 'topbar': [], 'account': [],
            'shortcuts': [], 'pin_edit': '', 'extra': [], 'destinations': []}


def primary_nav(ctx):
    """The sidebar, top bar and account menu for this request.

    Returns ``{'groups', 'settings', 'active_group', 'breadcrumbs',
    'workspace', 'topbar', 'account', 'shortcuts', 'pin_edit', 'extra',
    'destinations'}``. Each group is ``{key, label, icon, shortcut, href,
    active, entries}``; only groups with at least one visible entry are
    returned, and ``settings`` (the Administration group, whose ``href`` is
    the settings center) is None when the user may open none of it.
    ``destinations`` is destinations_for() for this request and ``extra`` the
    part of it the sidebar does not draw as links (Configure pages, settings
    pages, tabs that are not nested): the sidebar filter searches those too.
    """
    state = _empty_primary()
    user = _user(ctx)
    if user is None or not user.is_authenticated:
        return state
    request = ctx.get('request')
    match = getattr(request, 'resolver_match', None) if request is not None else None
    view_name = getattr(match, 'view_name', '') or ''
    path = getattr(request, 'path', '')
    current_section = section_for(view_name)
    active_group = group_for(view_name)
    probe = _PermProbe(ctx)

    def build(group):
        if not _allowed(group.gate, ctx):
            return None
        entries = [e for e in (_resolve_entry(en, ctx, match, probe, current_section)
                               for en in group.entries) if e is not None]
        if view_name and any(e['active'] and e['key'] == view_name for e in entries):
            # An entry for this exact page (Client Workspace on the selected
            # client) wins over the section entry that also covers it.
            for e in entries:
                if e['key'] != view_name:
                    e['active'] = False
        if group.key == 'dashboard':
            pins, state['pin_edit'] = _overview_pins(ctx, probe, {e['href'] for e in entries}, path)
            entries += pins
        if not entries:
            return None
        if group.key != active_group:
            # A page has one place: an entry lights only inside the current
            # group (My Work → My Tasks, not also Service Desk → Scheduling).
            for e in entries:
                e['active'] = False
                e['children'] = [dict(c, active=False) for c in e.get('children', [])]
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
    state['settings'] = build(ADMIN)
    if state['settings'] is not None:
        state['settings']['href'] = settings_home_url() or state['settings']['href']
    state['active_group'] = active_group
    state['workspace'] = settings_workspace(ctx, probe, match)
    state['breadcrumbs'] = _breadcrumbs(state, path)

    by_key = {e['key']: e for g in state['groups'] for e in g['entries']}
    state['topbar'] = [
        {'key': key, 'label': label, 'icon': f'fas {icon}', 'href': by_key[key]['href'],
         'active': by_key[key]['active']}
        for key, label, icon in TOPBAR if key in by_key
    ]
    state['account'] = _account_menu(ctx, state['workspace'], current_section.key
                                     if current_section else '', view_name)
    seen, shortcuts = set(), []
    for g in state['groups'] + ([state['settings']] if state['settings'] else []):
        if g['shortcut'] and g['shortcut'] not in seen:
            seen.add(g['shortcut'])
            shortcuts.append({'key': g['shortcut'], 'label': g['label']})
        for e in g['entries']:
            if e.get('shortcut') and e['shortcut'] not in seen:
                seen.add(e['shortcut'])
                shortcuts.append({'key': e['shortcut'], 'label': e['label']})
    state['shortcuts'] = shortcuts

    state['destinations'] = _destinations(state, ctx)
    drawn = set()
    for g in state['groups']:
        for e in g['entries']:
            drawn.add(e['href'])
            drawn.update(c['href'] for c in e['children'])
    if state['settings']:
        drawn.add(state['settings']['href'])
    state['extra'] = [d for d in state['destinations'] if d['href'] not in drawn]
    return state


def _breadcrumbs(state, path):
    """Section › workspace › page for the current page; the last crumb has
    no link when it is this page. Detail pages add their own last crumb
    through base.html's {% block breadcrumb_tail %}."""
    groups = state['groups'] + ([state['settings']] if state['settings'] else [])
    group = next((g for g in groups if g['active']), None)
    if group is None:
        current = state['workspace']['current']
        if current is None:
            return []
        # A customer-side administrator on a settings page: no sidebar group.
        home = settings_home_url() or state['workspace']['categories'][0]['href']
        trail = [{'label': _('Organization settings'), 'href': home},
                 {'label': current['label'], 'href': current['href']}]
        tab = next((t for t in current['tabs'] if t['active']), None)
        if tab is not None and str(tab['label']) != str(current['label']):
            trail.append({'label': tab['label'], 'href': tab['href']})
    else:
        trail = [{'label': group['label'], 'href': group['href']}]
        entry = next((e for e in group['entries'] if e['active']), None)
        if entry is not None:
            if str(entry['label']) != str(group['label']):
                trail.append({'label': entry['label'], 'href': entry['href']})
            tab = next((c for c in entry['tabs'] + entry.get('configure', []) if c['active']), None)
            if tab is not None and str(tab['label']) != str(trail[-1]['label']):
                trail.append({'label': tab['label'], 'href': tab['href']})
    if trail[-1]['href'] == path:
        trail[-1] = {'label': trail[-1]['label'], 'href': ''}
    return trail


# =============================================================================
# Every destination this user may open, flat — for the command palette, the
# sidebar filter and the search page. Built from the same resolved (gated and
# probed) navigation as the sidebar, so it can never offer more than the
# sidebar, the Configure menus, the settings center and the account menu do.
# =============================================================================

_ACCOUNT_SECTIONS = ('account_profile', 'account_work', 'account_help', 'account_apps')


def _destinations(state, ctx):
    out, seen, later = [], set(), []

    def add(item, group, section, kind, defer=False):
        href = item.get('href') or ''
        if not href or href == '#' or item.get('modal') or item.get('download'):
            return
        if defer:  # a link-only tab: its own home comes first
            later.append((item, group, section, kind))
            return
        if href in seen:
            return
        seen.add(href)
        out.append({
            'label': str(item['label']),
            'href': href,
            'icon': item.get('icon') or '',
            'group': str(group),
            'section': str(section),
            'keywords': str(item.get('keywords') or ''),
            'kind': kind,
        })

    for g in state['groups']:
        for e in g['entries']:
            if e.get('pin'):
                continue  # a pin repeats a page that has its own home
            add(e, g['label'], e['label'], 'entry')
            for t in e['tabs']:
                add(t, g['label'], e['label'], 'tab', defer=t.get('link_only'))
            for c in e.get('configure', []):
                add(c, g['label'], e['label'], 'configure')
    settings_label = state['settings']['label'] if state['settings'] else _('Organization settings')
    if state['workspace']['categories']:
        home = settings_home_url()
        if home:
            add({'label': _('Settings center'), 'href': home, 'icon': 'fas fa-gear',
                 'keywords': 'administration settings admin'}, settings_label, settings_label, 'settings')
        for cat in state['workspace']['categories']:
            for t in cat['tabs']:
                add(t, settings_label, cat['label'], 'settings')
    for key in _ACCOUNT_SECTIONS:
        section = SECTIONS_BY_KEY[key]
        for t in resolve_tabs(section, ctx):
            add(t, _('Account'), section.label, 'account', defer=t.get('link_only'))
    for item, group, section, kind in later:
        add(item, group, section, kind)
    return out


def destinations_for(ctx, pnav=None):
    """Every destination the user may open, as a flat list of
    ``{label, href, icon, group, section, keywords, kind}`` dicts (one per
    URL; ``kind`` is entry / tab / configure / settings / account).

    `ctx` is a template context, or request_context(request) from a view.
    The gates are the sidebar's: feature flags, MSP staff, superuser, role
    permissions, OPTIONAL AI and the server's URL rules. Pass the result of
    primary_nav(ctx) as `pnav` when you already have it.
    """
    if pnav is None:
        pnav = primary_nav(ctx)
    return list(pnav.get('destinations') or [])


_FLAG_FIELDS = ('monitoring_enabled', 'global_kb_enabled', 'workflows_enabled', 'vehicles_enabled',
                'inventory_enabled', 'scheduling_enabled', 'psa_enabled', 'crm_enabled',
                'reports_enabled', 'secure_notes_enabled', 'pulse_enabled')


def request_context(request):
    """The context keys navigation reads, built from a request (for views
    and JSON endpoints that have no template context): the same values
    core.context_processors.organization_context supplies."""
    from core.models import SystemSetting
    try:
        settings_row = SystemSetting.get_settings()
    except Exception:
        settings_row = None
    ctx = {
        'request': request,
        'user': getattr(request, 'user', None),
        'is_staff_user': getattr(request, 'is_staff_user', False),
        'current_organization': getattr(request, 'current_organization', None),
        'system_settings': settings_row,
    }
    for name in _FLAG_FIELDS:
        ctx[name] = bool(getattr(settings_row, name, False))
    return ctx
