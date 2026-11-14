"""Every landing page is reachable from the navigation.

A landing page is a named GET page with no path arguments (see
nav_landing_routes.py for how they are found). Each one must be linked by
core/navigation.py — an entry, a section tab, or a tab's / section's `also`
(a sub-page that lights its parent) — or be listed in ALLOWED_UNLINKED below
with the reason it has no link of its own: usually the page one level up that
links it ("reached from X"), sometimes that it is an alias or a dead page.

When this test fails for a new page, add it to navigation.py (preferred) or
to the allow-list with a reason. The before → after map of the navigation is
docs/navigation-map.md.
"""
from django.test import SimpleTestCase

from core import navigation
from core.tests.nav_landing_routes import landing_routes

# Linked from base.html itself rather than navigation.py.
BASE_HTML = {
    'home': 'the brand link',
    'core:search': 'the top-bar search form',
}

ALLOWED_UNLINKED = {
    'accounts:password_change': 'reached from accounts:profile',
    'accounts:quick_add_menu': 'legacy quick-add launcher (require_admin); only its own quick forms link back to it. Not linked on purpose',
    'accounts:two_factor_setup': 'reached from accounts:profile',
    'assets:contact_list': 'reached from assets:contact_detail',
    'assets:equipment_model_list': 'reached from assets:equipment_model_detail',
    'assets:relationship_map': 'BROKEN: its template assets/relationship_map.html does not exist (500). Not linked until it is fixed',
    'assets:rma_list': 'reached from assets:serial_search',
    'core:free_consult': 'reached from core:about',
    'core:global_dashboard': 'reached through the client switcher (Global View, accounts:switch_to_global_view)',
    'core:help_assets': 'reached from core:help_index',
    'core:help_documentation': 'reached from core:help_index',
    'core:help_features': 'dead page: linked only from shadowed core/templates/core/help/*.html that never render',
    'core:help_getting_started': 'reached from core:help_index',
    'core:help_locations': 'reached from core:help_index',
    'core:help_monitoring': 'reached from core:help_index',
    'core:help_reports': 'reached from core:help_index',
    'core:help_search': 'reached from core:help_index',
    'core:help_security': 'reached from core:help_index',
    'core:help_vault': 'reached from core:help_index',
    'core:help_vehicles': 'reached from core:help_index',
    'core:help_workflows': 'reached from core:help_index',
    'core:report_bug': 'a fetch POST endpoint, opened as the Report Bug modal (Help tabs)',
    'docs:agreement_list': 'reached from docs:agreement_manage',
    'docs:ai_assistant': 'reached from docs:document_list',
    'docs:category_list': 'reached from psa:kb_browse',
    'docs:diagram_template_list': 'reached from docs:diagram_list',
    'docs:document_import': 'reached from docs:document_list',
    'docs:template_list': 'reached from docs:document_list',
    'field_ops:my_location_history': 'reached from field_ops:dispatch_sharing',
    'hardware:coverage': 'reached from hardware:catalog',
    'hardware:import_jobs': 'reached from hardware:catalog',
    'hardware:model_requests': 'reached from hardware:catalog',
    'hardware:search': 'reached from hardware:cable_list',
    'integrations:m365docs_home': 'reached from integrations:m365_detail',
    'integrations:psa_companies': 'reached from the integration detail page (integrations:integration_list)',
    'integrations:psa_contacts': 'reached from integrations:psa_contact_detail',
    'integrations:psa_tickets': 'reached from the integration detail page (integrations:integration_list)',
    'integrations:rmm_software': 'reached from integrations:rmm_detail',
    'inventory:category_list': 'reached from inventory:inventory_dashboard',
    'inventory:location_list': 'reached from inventory:inventory_dashboard',
    'inventory:transaction_list': 'reached from inventory:inventory_dashboard',
    'locations:location_list': 'reached from the dashboard and location forms (Clients > Infrastructure)',
    'netconfig:lifecycle': 'reached from netconfig:device_list',
    'processes:execution_list': 'reached from processes:process_list',
    'processes:global_process_list': 'reached from core:global_dashboard',
    'psa:request_type_list': 'reached from psa:service_catalog',
    'psa:request_type_report': 'reached from psa:request_type_list',
    'psa:request_type_starters': 'reached from psa:request_type_list',
    'psa:requester_sites': 'reached from assets:contact_detail',
    'readiness:broken_relationships': 'reached from readiness:overview',
    'readiness:repair_queue': 'reached from readiness:overview',
    'readiness:standard_list': 'reached from readiness:overview',
    'reports:accounting_reconciliation': 'reached from reports:home',
    'reports:agreement_reconciliation': 'reached from reports:home',
    'reports:ar_aging_report': 'reached from reports:home',
    'reports:asset_lifecycle_report': 'reached from reports:home',
    'reports:bank_reconciliation_report': 'reached from reports:home',
    'reports:billing_reconciliation_report': 'reached from reports:home',
    'reports:crm_sales_funnel': 'reached from reports:home',
    'reports:exec_scorecard': 'reached from reports:home',
    'reports:hardware_margin_report': 'reached from reports:home',
    'reports:kpi_dashboard': 'reached from reports:home',
    'reports:mrr_forecast_report': 'reached from reports:home',
    'reports:multi_location_report': 'reached from reports:home',
    'reports:operational_metrics_report': 'reached from reports:home',
    'reports:procurement_forecasting': 'reached from reports:home',
    'reports:procurement_summary': 'reached from reports:home',
    'reports:psa_client_health': 'reached from reports:home',
    'reports:psa_effective_hourly_rate': 'reached from reports:home',
    'reports:psa_margin_analytics': 'reached from reports:home',
    'reports:psa_profitability_by_client': 'reached from reports:home',
    'reports:psa_profitability_by_contract': 'reached from reports:home',
    'reports:psa_profitability_by_project': 'reached from reports:home',
    'reports:psa_profitability_by_tech': 'reached from reports:home',
    'reports:psa_reports_list': 'reached from reports:home',
    'reports:psa_revenue_leakage': 'reached from reports:home',
    'reports:psa_sla_trends': 'reached from reports:home',
    'reports:quote_conversion_report': 'reached from reports:home',
    'reports:saved_query_list': 'reached from reports:home',
    'reports:scheduled_list': 'reached from reports:home',
    'reports:sla_forecast_report': 'reached from reports:home',
    'reports:ticket_aging_report': 'reached from reports:home',
    'reports:trends_report': 'reached from reports:home',
    'reports:vendor_cost_history': 'reached from reports:home',
    'reports:wallboard': 'reached from reports:home',
    'reports:workflow_performance_report': 'reached from reports:home',
    'resourcing:capacity_report': 'reached from resourcing:tech_roster',
    'resourcing:leave_approvals': 'reached from resourcing:my_leave',
    'resourcing:tech_cost_rate_list': 'reached from resourcing:tech_cost_rate_edit',
    'resourcing:tech_roster': 'reached from resourcing:my_resourcing',
    'scheduling:overdue_tasks': 'reached from scheduling:task_list',
    'scheduling:scheduling_dashboard': 'reached from My Tasks (scheduling:my_tasks)',
    'ticket_routing:alert_maintenance': 'reached from ticket_routing:overview',
    'ticket_routing:on_call': 'reached from ticket_routing:overview',
    'vehicles:vehicles_dashboard': 'reached from vehicles:service_alert_list',
}


def linked_names():
    names = set()
    for g in navigation.ALL_GROUPS:
        for e in g.entries:
            if e.url_name:
                names.add(e.url_name)
    for s in navigation.SECTIONS:
        names.update(s.also)
        for t in s.tabs:
            if t.url_name:
                names.add(t.url_name)
            names.update(t.also)
    return names


class ReachabilityTests(SimpleTestCase):

    def test_every_landing_page_is_linked_or_allowed(self):
        missing = sorted(landing_routes() - linked_names() - set(BASE_HTML) - set(ALLOWED_UNLINKED))
        self.assertEqual(missing, [], 'landing pages with no navigation link and no allow-list reason')

    def test_allow_list_is_current(self):
        """No stale entries: each is still a landing page and still unlinked."""
        landing = landing_routes()
        linked = linked_names()
        for name, reason in ALLOWED_UNLINKED.items():
            with self.subTest(name=name):
                self.assertTrue(reason.strip())
                self.assertIn(name, landing)
                self.assertNotIn(name, linked)

    def test_the_audit_orphans_are_resolved(self):
        """The 35 pages the 2026-11 audit found with no link path at all."""
        orphans = [
            'accounts:quick_add_menu', 'assets:network_scan_import', 'assets:port_config_list',
            'assets:relationship_map', 'core:consult_requests', 'core:documentation',
            'core:help_features', 'core:secure_note_links_dashboard', 'core:vault_import',
            'field_ops:settings', 'field_ops:timeclock_dashboard', 'integrations:accounting_list',
            'integrations:distributor_list', 'monitoring:patch_panel_list', 'office:managed_diagnostics',
            'office:template_list', 'processes:runbook_dashboard', 'psa:dispatch_heatmap',
            'psa:my_timesheet', 'psa:timesheet_approval_queue', 'psa:workflow_suggestion_list',
            'psa:workflow_template_list', 'reports:analytics_overview', 'reports:security_alert_mtta',
            'reports:software_compliance_report', 'resourcing:holiday_list',
            'security_alerts:incident_list', 'security_alerts:playbook_list',
            'security_alerts:siem_endpoint_list', 'security_alerts:threat_overview',
            'vault:reveal_request_list', 'vehicles:inventory_by_vehicle',
            'vehicles:inventory_global_list', 'vehicles:inventory_list', 'vehicles:shop_inventory_list',
        ]
        self.assertEqual(len(orphans), 35)
        linked = linked_names()
        for name in orphans:
            with self.subTest(name=name):
                self.assertTrue(name in linked or name in ALLOWED_UNLINKED, name)
