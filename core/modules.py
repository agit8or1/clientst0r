"""Optional modules: one registry of what can be switched on, what each one
needs, and what people see once it is on.

Rendered by core.modules_views.settings_modules (Settings → System →
Optional modules). Nothing here changes a default: the switches are the
existing SystemSetting booleans (and, for routing and the portal, their own
settings rows), read as they are.

A module is either
  * *switchable here* — `field` names a SystemSetting boolean. The page can
    turn it on or off. Turning it on while something in `requires` is off is
    refused; turning it off while a module that requires it is on is allowed
    but the page says which modules stop working;
  * *managed elsewhere* — `field` is None and `state` reads the module's own
    settings (routing mode, per-customer portal rows, status pages). The page
    links to where it is managed.

`requires` lists hard dependencies: the dependent module's pages 404 or its
menu is hidden while the dependency is off. `works_better_with` lists soft
ones, shown as a hint only.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.urls import NoReverseMatch, reverse


@dataclass(frozen=True)
class Module:
    key: str
    label: str
    icon: str
    summary: str
    shows: tuple                     # what users see when it is on
    settings_links: tuple = ()       # ((label, url_name), ...)
    field: str = ''                  # SystemSetting boolean, '' = managed elsewhere
    requires: tuple = ()             # module keys
    works_better_with: tuple = ()    # module keys (hint only)
    optional_ai: bool = False
    note: str = ''
    group: str = 'Service desk'


MODULES = (
    # ---- Service desk ---------------------------------------------------
    Module(
        'psa', 'PSA / Service desk', 'fa-ticket-alt',
        'Native tickets, queues, SLA, projects, contracts, quotes, invoices and procurement.',
        shows=(
            'PSA menu for MSP staff: My Work, Tickets, Dispatch Board, Projects, '
            'Service Management, Billing, Procurement',
            'Modules → Security (security alerts) for MSP staff',
            'SLA, contract renewal and overdue invoice sections on Customer operations',
            'Customers with an active external PSA connection are opted out automatically',
        ),
        settings_links=(('PSA settings', 'core:settings_psa'),
                        ('Per-customer PSA settings', 'psa:client_settings')),
        field='psa_enabled',
    ),
    Module(
        'ticket_ai', 'Ticket AI', 'fa-wand-magic-sparkles',
        'OPTIONAL AI: suggested replies and suggested actions on PSA tickets.',
        shows=(
            'AI suggestions on the ticket page for staff whose role allows it',
            'PSA → Tickets → AI Inbox tab',
            'My Profile → My AI keys for MSP staff',
        ),
        settings_links=(('PSA settings (AI knobs)', 'core:settings_psa'),
                        ('AI provider and key', 'core:settings_ai'),
                        ('Ticket AI profiles', 'psa_ai:profiles')),
        field='psa_ai_enabled', requires=('psa',), optional_ai=True,
        note='Also needs an AI provider key (Settings → AI). Every suggestion '
             'is reviewed by a person before anything is sent or applied.',
    ),
    Module(
        'routing', 'Ticket routing', 'fa-route',
        'Rule-based choice of queue, team or technician for new and rerouted tickets. Not AI.',
        shows=(
            'Suggest only: a routing suggestion on the ticket for staff to accept or reject',
            'Automatic: new tickets are assigned by the rules',
        ),
        settings_links=(('Routing settings and rules', 'ticket_routing:overview'),),
        requires=('psa',),
        note='Switched by the routing mode (Off / Suggest only / Automatic) on its own page.',
    ),
    Module(
        'portal', 'Customer portal', 'fa-door-open',
        'Signed-in customer users see their shared tickets, file requests and read their status page.',
        shows=(
            '/portal/ for users of customers with the portal turned on',
            'Portal tickets, requests, knowledge base and status page',
        ),
        settings_links=(('Per-customer PSA settings', 'psa:client_settings'),),
        requires=('psa',),
        note='Turned on per customer (Per-customer PSA settings → portal). There is '
             'no global portal switch: the unused one on PSA settings was removed.',
    ),
    Module(
        'portal_announcements', 'Portal announcements', 'fa-bullhorn',
        'Announcements on the portal home page.',
        shows=('An announcements panel on the customer portal home',),
        field='psa_portal_announcements_enabled', requires=('psa',), works_better_with=('portal',),
    ),
    Module(
        'portal_voting', 'Portal "affected too" votes', 'fa-hand',
        'Portal users can mark a ticket they can see as affecting them too.',
        shows=('An "I\'m affected too" button on portal tickets',),
        field='psa_portal_voting_enabled', requires=('psa',), works_better_with=('portal',),
    ),
    Module(
        'portal_escalation', 'Portal escalation', 'fa-arrow-up',
        'Portal users can escalate one of their tickets.',
        shows=('An Escalate button on portal tickets',),
        field='psa_portal_escalation_enabled', requires=('psa',), works_better_with=('portal',),
    ),
    Module(
        'portal_approvals', 'Portal customer approvals', 'fa-circle-check',
        'Approvals flagged for the customer are shown to portal users to decide.',
        shows=('Approvals in the customer portal menu',),
        field='psa_portal_customer_approvals_enabled', requires=('psa',), works_better_with=('portal',),
    ),
    Module(
        'csat', 'Satisfaction surveys (CSAT)', 'fa-star',
        'Email a 1–5 star survey link when a ticket is resolved or closed.',
        shows=('A survey email to the requester after resolution',),
        field='psa_csat_enabled', requires=('psa',),
        note='Needs outgoing email (Settings → Email / SMTP).',
    ),
    Module(
        'pulse', 'Pulse checks', 'fa-heart-pulse',
        'Service-feedback surveys sent to people at client organizations, by hand or monthly / quarterly.',
        shows=('Clients → Pulse Checks for MSP staff',
               'A Feedback page in the customer portal (requests to answer, opt-out switch)',
               'A pulse check trend card on client records for MSP staff'),
        settings_links=(('Pulse checks', 'pulse:check_list'),),
        field='pulse_enabled', works_better_with=('portal',),
        note='E-mailed links need outgoing email (Settings → Email / SMTP); without it, '
             'portal users can still answer from the portal.',
    ),
    Module(
        'security_alerts', 'Security alerts', 'fa-shield-halved',
        'Alerts from security vendors, auto-ticket rules and vendor connections.',
        shows=('Modules → Security for MSP staff',),
        requires=('psa',),
        note='No switch of its own: it is shown whenever PSA is on.',
    ),

    # ---- Sales -----------------------------------------------------------
    Module(
        'crm', 'CRM', 'fa-chart-pie',
        'Leads, opportunities, campaigns and commissions.',
        shows=('Modules → CRM for MSP staff',),
        field='crm_enabled', works_better_with=('psa',), group='Sales',
        note='Converting an opportunity into a quote creates a PSA quote; turn on PSA to work with it.',
    ),

    # ---- Operations ------------------------------------------------------
    Module(
        'monitoring', 'Monitoring', 'fa-heart-pulse',
        'Website and SSL monitoring, WAN connections, expirations, status pages and config backups.',
        shows=('Operations → Monitoring', 'Uptime section on Customer operations'),
        settings_links=(('Website monitors', 'monitoring:website_monitor_list'),),
        field='monitoring_enabled', group='Operations',
    ),
    Module(
        'status_pages', 'Status pages', 'fa-signal',
        'Public or portal status pages with services and incidents.',
        shows=('Operations → Monitoring → Status Pages for staff',
               'Each page is off until enabled; public pages are reached only by their link'),
        settings_links=(('Status pages', 'statuspage:list'),),
        requires=('monitoring',), group='Operations',
        note='Each page has its own on/off switch. The menu entry sits under Monitoring.',
    ),
    Module(
        'workflows', 'Workflows', 'fa-tasks',
        'Process definitions and tracked runs.',
        shows=('Operations → Workflows',),
        settings_links=(('Workflows', 'processes:process_list'),),
        field='workflows_enabled', group='Operations',
    ),
    Module(
        'inventory', 'Inventory', 'fa-boxes',
        'Spare parts, consumables, tools and stock alerts.',
        shows=('Operations → Inventory',),
        settings_links=(('Inventory', 'inventory:inventory_dashboard'),),
        field='inventory_enabled', group='Operations',
    ),
    Module(
        'scheduling', 'Scheduling', 'fa-calendar-alt',
        'Recurring scheduled tasks with sign-off, calendar and wallboard.',
        shows=('Operations → Scheduling',),
        settings_links=(('Scheduled tasks', 'scheduling:task_list'),),
        field='scheduling_enabled', group='Operations',
    ),
    Module(
        'vehicles', 'Service vehicles', 'fa-truck',
        'Fleet, mileage, maintenance, fuel and damage logs.',
        shows=('Operations → Vehicles',),
        settings_links=(('Vehicles', 'vehicles:vehicle_list'),),
        field='vehicles_enabled', group='Operations',
    ),
    Module(
        'webhooks', 'Webhooks', 'fa-bolt',
        'Send event notifications to your endpoints.',
        shows=('Events are delivered to the endpoints configured on the Webhooks page',),
        settings_links=(('Webhooks', 'core:webhook_list'),),
        field='webhooks_enabled', group='Operations',
    ),
    Module(
        'global_kb', 'Global knowledge base', 'fa-globe',
        'A staff-only knowledge base shared across customers.',
        shows=('Global KB entries in the navigation for staff',),
        settings_links=(('KB import', 'core:settings_kb_import'),),
        field='global_kb_enabled', group='Operations',
    ),

    Module(
        'reports', 'Reports & Analytics', 'fa-chart-bar',
        'Dashboards, wallboards, report templates, scheduled reports and the PSA / billing reports.',
        shows=('Modules → Reports for MSP staff', 'Wallboard and agreement reconciliation quick actions',
               'Scheduled report emails'),
        settings_links=(('Feature toggles', 'core:settings_features'),),
        field='reports_enabled', group='Operations',
        note='Off: every /reports/ page is a 404 and scheduled reports pause.',
    ),
    Module(
        'secure_notes', 'Secure Notes', 'fa-lock',
        'Encrypted, self-destructing notes sent to users or by link.',
        shows=('Vault → Secure Notes',),
        settings_links=(('Feature toggles', 'core:settings_features'),),
        field='secure_notes_enabled', group='Operations',
        note='Off: the notes pages are a 404. Links already sent, and ticket secure '
             'messages, still open until they expire.',
    ),

    # ---- Asset health ----------------------------------------------------
    Module(
        'asset_age', 'Asset age warnings', 'fa-hourglass-half',
        'Warn when assets approach or pass the age thresholds in General settings.',
        shows=('Age warnings on asset pages', 'Aged assets in the Customer operations asset section'),
        settings_links=(('General settings (thresholds)', 'core:settings_general'),),
        field='asset_age_warnings_enabled', group='Asset health',
    ),
    Module(
        'warranty_checks', 'Warranty lookups', 'fa-certificate',
        'Look up warranty expiry for PCs and servers from vendor APIs (Dell, HP, Lenovo).',
        shows=('Warranty dates filled in on assets by the scheduler',),
        field='warranty_checks_enabled', group='Asset health',
        note='Needs vendor API credentials.',
    ),
    Module(
        'firmware_checks', 'Firmware checks', 'fa-microchip',
        'Check network devices for newer firmware.',
        shows=('Firmware update badges on assets',),
        field='firmware_checks_enabled', group='Asset health',
    ),

    # ---- Always available ------------------------------------------------
    Module(
        'imports', 'Data imports', 'fa-file-import',
        'Bring in data from other documentation tools and spreadsheets.',
        shows=('Settings → System → Data Import for superusers',),
        settings_links=(('Data import', 'imports:import_list'),),
        group='Always available',
        note='No switch: always available to superusers.',
    ),
    Module(
        'mobile', 'Mobile app', 'fa-mobile-alt',
        'The Android app and its API.',
        shows=('Apps & Downloads in the account menu', 'Mobile app builds under Settings → Mobile'),
        settings_links=(('Mobile apps', 'core:mobile_apps_admin'),),
        group='Always available',
        note='No switch: the mobile API is always available to signed-in users.',
    ),
)

MODULES_BY_KEY = {m.key: m for m in MODULES}
GROUP_ORDER = ('Service desk', 'Sales', 'Operations', 'Asset health', 'Always available')

def _custom_state(key, settings):
    """(on, detail) for modules managed outside SystemSetting."""
    if key == 'routing':
        try:
            from psa.routing.models import RoutingSettings
            mode = RoutingSettings.load()
            return mode.mode != 'off', f'Mode: {mode.get_mode_display()}'
        except Exception:
            return False, 'Mode: Off'
    if key == 'portal':
        try:
            from psa.models import ClientPSASettings
            n = ClientPSASettings.objects.filter(portal_enabled=True).count()
        except Exception:
            n = 0
        return n > 0, f'On for {n} customer(s)'
    if key == 'status_pages':
        try:
            from statuspage.models import StatusPage
            n = StatusPage.objects.filter(is_enabled=True).count()
        except Exception:
            n = 0
        return n > 0, f'{n} page(s) enabled'
    if key == 'security_alerts':
        return bool(settings.psa_enabled), 'Follows PSA'
    if key in ('imports', 'mobile'):
        return True, 'Always on'
    return False, ''


def is_on(module, settings):
    """The module's own switch, ignoring its dependencies."""
    if module.field:
        return bool(getattr(settings, module.field, False))
    return _custom_state(module.key, settings)[0]


def missing_requirements(module, settings):
    """Modules in `requires` that are off."""
    return [MODULES_BY_KEY[k] for k in module.requires if not is_on(MODULES_BY_KEY[k], settings)]


def dependents_on(module, settings):
    """Modules that require `module` and are switched on themselves."""
    return [m for m in MODULES if module.key in m.requires and is_on(m, settings)]


def field_default(module):
    from core.models import SystemSetting
    if not module.field:
        return None
    return SystemSetting._meta.get_field(module.field).default


def _href(url_name):
    try:
        return reverse(url_name)
    except NoReverseMatch:
        return ''


def describe(settings):
    """Rows for the page, grouped: [(group, [row, ...]), ...]."""
    rows = {}
    for m in MODULES:
        own_on = is_on(m, settings)
        missing = missing_requirements(m, settings)
        detail = '' if m.field else _custom_state(m.key, settings)[1]
        rows.setdefault(m.group, []).append({
            'module': m,
            'on': own_on,
            'active': own_on and not missing,
            'missing': missing,
            'requires': [MODULES_BY_KEY[k] for k in m.requires],
            'works_better_with': [MODULES_BY_KEY[k] for k in m.works_better_with],
            'dependents_on': dependents_on(m, settings) if own_on else [],
            'detail': detail,
            'switchable': bool(m.field),
            'default': field_default(m),
            'links': [(label, _href(name)) for label, name in m.settings_links if _href(name)],
        })
    return [(g, rows[g]) for g in GROUP_ORDER if g in rows]


class DependencyError(Exception):
    pass


def set_enabled(module, settings, enabled, user=None):
    """Switch a SystemSetting-backed module.

    Refuses (DependencyError) to turn a module on while something in
    `requires` is off. Returns ``(stopped, soft_missing)``: the modules that
    stop working because this one was turned off (they keep their own
    setting), and the `works_better_with` modules that are off when this one
    is turned on."""
    if not module.field:
        raise ValueError(f'{module.key} is managed on its own settings page')
    soft_missing = []
    if enabled:
        missing = missing_requirements(module, settings)
        if missing:
            raise DependencyError(
                f'{module.label} needs {", ".join(m.label for m in missing)} turned on first.')
        soft_missing = [MODULES_BY_KEY[k] for k in module.works_better_with
                        if not is_on(MODULES_BY_KEY[k], settings)]
    stopped = [] if enabled else dependents_on(module, settings)
    setattr(settings, module.field, bool(enabled))
    if user is not None:
        settings.updated_by = user
    settings.save(update_fields=[module.field, 'updated_by', 'updated_at'])
    return stopped, soft_missing
