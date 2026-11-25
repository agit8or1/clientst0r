"""Default per-feature permissions for the default access groups.

Each default group (by seed key) is given its default per-feature
permissions only when doing so widens nothing: every default key must
already be granted by the role the group carries right now. That is true
for a default group still on its built-in role (the defaults are a subset
of it), so new installs and untouched groups get the defaults; a default
group whose role an administrator changed or removed, or that already has
per-feature permissions, is left as it is - the group page then offers
"Reset to defaults", which an administrator applies under the usual rules.

Frozen copy of accounts.group_features.default_keys() at the time of this
migration; later changes to the defaults never reach existing groups
through this migration."""
from django.db import migrations

DEFAULTS = {
    'l1_tech': (
        'assets_view', 'change_create', 'change_view', 'docs_view', 'events_view', 'files_view',
        'kb_view_articles', 'monitoring_view', 'org_view_members', 'problem_create', 'problem_view',
        'procurement_view', 'psa_ai_request_triage', 'psa_ai_view', 'release_view',
        'reports_view_dashboards', 'security_alerts_view', 'tickets_close', 'tickets_create',
        'tickets_edit', 'tickets_view', 'tickets_view_internal', 'vault_view', 'vehicles_view',
        'view_backup_status',
    ),
    'l2_tech': (
        'assets_edit', 'assets_view', 'catalog_propose_change', 'change_create', 'change_view',
        'docs_create', 'docs_edit', 'docs_view', 'events_link', 'events_view', 'files_upload',
        'files_view', 'kb_edit_articles', 'kb_view_articles', 'monitoring_trigger',
        'monitoring_view', 'org_view_members', 'problem_create', 'problem_view', 'procurement_view',
        'psa_ai_request_triage', 'psa_ai_view', 'release_view', 'reports_export',
        'reports_view_dashboards', 'security_alerts_acknowledge', 'security_alerts_view',
        'tickets_close', 'tickets_create', 'tickets_edit', 'tickets_view', 'tickets_view_internal',
        'vault_view', 'vehicles_view', 'view_backup_status',
    ),
    'l3_tech': (
        'assets_create', 'assets_edit', 'assets_view', 'catalog_propose_change', 'change_create',
        'change_implement', 'change_view', 'docs_create', 'docs_edit', 'docs_view', 'events_link',
        'events_view', 'files_upload', 'files_view', 'kb_edit_articles', 'kb_move_articles',
        'kb_view_articles', 'monitoring_create', 'monitoring_edit', 'monitoring_trigger',
        'monitoring_view', 'org_view_members', 'problem_assign', 'problem_create',
        'problem_resolve', 'problem_view', 'procurement_view', 'psa_ai_request_triage',
        'psa_ai_view', 'release_view', 'reports_export', 'reports_view_dashboards',
        'security_alerts_acknowledge', 'security_alerts_view', 'tickets_assign', 'tickets_close',
        'tickets_create', 'tickets_edit', 'tickets_view', 'tickets_view_internal', 'vault_view',
        'vehicles_view', 'view_backup_status',
    ),
    'managers': (
        'assets_create', 'assets_edit', 'assets_view', 'catalog_approve_change',
        'catalog_propose_change', 'change_approve_cab', 'change_create', 'change_implement',
        'change_view', 'docs_create', 'docs_edit', 'docs_publish', 'docs_view', 'events_link',
        'events_view', 'files_upload', 'files_view', 'integrations_view', 'kb_edit_articles',
        'kb_move_articles', 'kb_publish_articles', 'kb_view_articles', 'monitoring_create',
        'monitoring_edit', 'monitoring_trigger', 'monitoring_view', 'org_view_members',
        'outsourcing_share_tickets', 'problem_assign', 'problem_create', 'problem_resolve',
        'problem_view', 'procurement_approve_pr', 'procurement_create_pr', 'procurement_view',
        'psa_ai_apply_low_risk', 'psa_ai_approve_action', 'psa_ai_approve_reply',
        'psa_ai_request_triage', 'psa_ai_send_low_risk', 'psa_ai_view', 'psa_manage_workflow_rules',
        'release_freeze', 'release_manage', 'release_view', 'reports_export',
        'reports_manage_dashboards', 'reports_view_capacity', 'reports_view_dashboards',
        'reports_view_sla', 'resourcing_approve_leave', 'resourcing_view_team',
        'routing_manage_rules', 'routing_override', 'routing_test', 'scheduling_manage_wallboard',
        'security_alerts_acknowledge', 'security_alerts_view', 'tickets_assign', 'tickets_close',
        'tickets_create', 'tickets_edit', 'tickets_view', 'tickets_view_all',
        'tickets_view_internal', 'timesheets_approve', 'vehicles_manage', 'vehicles_view',
        'view_backup_status',
    ),
    'sales': (
        'contracts_edit_draft', 'contracts_submit_approval', 'contracts_view',
        'contracts_view_pricing', 'crm_create_lead', 'crm_manage_pipeline', 'crm_view',
        'files_upload', 'files_view', 'kb_view_articles', 'org_view_members', 'quotes_edit',
        'quotes_view', 'reports_view_dashboards', 'tickets_create', 'tickets_view',
    ),
    'sales_managers': (
        'contracts_download_signed', 'contracts_edit_draft', 'contracts_submit_approval',
        'contracts_view', 'contracts_view_pricing', 'crm_approve_commissions', 'crm_create_lead',
        'crm_manage_campaigns', 'crm_manage_pipeline', 'crm_view', 'crm_view_forecast',
        'files_upload', 'files_view', 'kb_view_articles', 'org_view_members',
        'pricing_approve_discounts', 'quotes_approve_discount', 'quotes_edit', 'quotes_send',
        'quotes_view', 'reports_export', 'reports_manage_dashboards', 'reports_view_dashboards',
        'tickets_create', 'tickets_view',
    ),
    'owners': (
        'act_on_pricing_recommendations', 'api_access', 'assets_create', 'assets_delete',
        'assets_edit', 'assets_view', 'audit_export', 'audit_view', 'billing_approve_invoices',
        'billing_issue_credit', 'billing_manage_charges', 'billing_record_payments',
        'billing_send_invoices', 'billing_view_aging', 'billing_view_invoices',
        'catalog_approve_change', 'catalog_propose_change', 'change_approve_cab', 'change_create',
        'change_implement', 'change_view', 'contracts_approve', 'contracts_countersign',
        'contracts_download_signed', 'contracts_edit_draft', 'contracts_manage_links',
        'contracts_manage_templates', 'contracts_send', 'contracts_submit_approval',
        'contracts_view', 'contracts_view_audit', 'contracts_view_pricing', 'contracts_void',
        'crm_approve_commissions', 'crm_create_lead', 'crm_manage_campaigns', 'crm_manage_pipeline',
        'crm_view', 'crm_view_forecast', 'docs_create', 'docs_delete', 'docs_edit', 'docs_publish',
        'docs_view', 'events_link', 'events_view', 'files_delete', 'files_upload', 'files_view',
        'integrations_sync', 'integrations_view', 'integrations_view_synced_psa',
        'kb_edit_articles', 'kb_manage_categories', 'kb_move_articles', 'kb_publish_articles',
        'kb_view_articles', 'manage_backup_integrations', 'manage_customer_onboarding',
        'manage_health_score_settings', 'manage_licensing', 'manage_tax_settings',
        'monitoring_create', 'monitoring_delete', 'monitoring_edit', 'monitoring_trigger',
        'monitoring_view', 'netconfig_view_configs', 'org_invite_members', 'org_manage_members',
        'org_view_members', 'outsourcing_share_tickets', 'pricing_approve_discounts',
        'pricing_manage_labor_rate_cards', 'pricing_manage_price_books',
        'pricing_manage_service_plans', 'pricing_view_internal_cost_rates', 'problem_assign',
        'problem_create', 'problem_resolve', 'problem_view', 'procurement_approve_pr',
        'procurement_create_po', 'procurement_create_pr', 'procurement_send_po', 'procurement_view',
        'psa_ai_apply_high_risk', 'psa_ai_apply_low_risk', 'psa_ai_approve_action',
        'psa_ai_approve_reply', 'psa_ai_billing', 'psa_ai_create_workflow', 'psa_ai_request_triage',
        'psa_ai_run_script', 'psa_ai_send_high_risk', 'psa_ai_send_low_risk', 'psa_ai_view',
        'psa_manage_workflow_rules', 'quotes_approve_discount', 'quotes_edit', 'quotes_send',
        'quotes_view', 'release_freeze', 'release_manage', 'release_view', 'reports_export',
        'reports_manage_dashboards', 'reports_manage_scheduled', 'reports_view_capacity',
        'reports_view_dashboards', 'reports_view_financial', 'reports_view_sla',
        'resourcing_approve_leave', 'resourcing_manage_cost_rates', 'resourcing_manage_holidays',
        'resourcing_view_payroll', 'resourcing_view_team', 'routing_manage_rules',
        'routing_override', 'routing_test', 'scheduling_manage_wallboard',
        'security_alerts_acknowledge', 'security_alerts_create_rules', 'security_alerts_view',
        'tickets_assign', 'tickets_close', 'tickets_create', 'tickets_delete', 'tickets_edit',
        'tickets_view', 'tickets_view_all', 'tickets_view_internal', 'timesheets_approve',
        'vault_approve_reveal', 'vault_create', 'vault_delete', 'vault_edit', 'vault_view',
        'vault_view_password', 'vehicles_manage', 'vehicles_view', 'view_backup_status',
        'view_profitability',
    ),
    'administrators': (
        'api_access', 'assets_create', 'assets_delete', 'assets_edit', 'assets_view', 'audit_view',
        'catalog_approve_change', 'catalog_propose_change', 'change_approve_cab', 'change_create',
        'change_implement', 'change_view', 'contracts_view', 'crm_view', 'docs_create',
        'docs_delete', 'docs_edit', 'docs_publish', 'docs_view', 'events_link', 'events_view',
        'files_delete', 'files_upload', 'files_view', 'integrations_sync', 'integrations_view',
        'integrations_view_synced_psa', 'kb_edit_articles', 'kb_manage_categories',
        'kb_move_articles', 'kb_publish_articles', 'kb_view_articles', 'manage_backup_integrations',
        'manage_customer_onboarding', 'manage_health_score_settings', 'manage_licensing',
        'monitoring_create', 'monitoring_delete', 'monitoring_edit', 'monitoring_trigger',
        'monitoring_view', 'org_view_members', 'problem_assign', 'problem_create',
        'problem_resolve', 'problem_view', 'procurement_approve_pr', 'procurement_create_pr',
        'procurement_view', 'psa_ai_request_triage', 'psa_ai_view', 'psa_manage_workflow_rules',
        'quotes_view', 'release_freeze', 'release_manage', 'release_view', 'reports_export',
        'reports_manage_dashboards', 'reports_view_capacity', 'reports_view_dashboards',
        'reports_view_sla', 'resourcing_approve_leave', 'resourcing_manage_holidays',
        'resourcing_view_payroll', 'resourcing_view_team', 'routing_manage_rules',
        'routing_override', 'routing_test', 'scheduling_manage_wallboard',
        'security_alerts_acknowledge', 'security_alerts_create_rules', 'security_alerts_view',
        'tickets_assign', 'tickets_close', 'tickets_create', 'tickets_edit', 'tickets_view',
        'tickets_view_all', 'tickets_view_internal', 'timesheets_approve', 'vehicles_manage',
        'vehicles_view', 'view_backup_status',
    ),
    'billing': (
        'act_on_pricing_recommendations', 'billing_approve_invoices', 'billing_issue_credit',
        'billing_manage_charges', 'billing_record_payments', 'billing_send_invoices',
        'billing_view_aging', 'billing_view_invoices', 'contracts_download_signed',
        'contracts_view', 'contracts_view_pricing', 'files_view', 'kb_view_articles',
        'manage_tax_settings', 'org_view_members', 'pricing_approve_discounts',
        'pricing_manage_labor_rate_cards', 'pricing_manage_price_books',
        'pricing_manage_service_plans', 'pricing_view_internal_cost_rates', 'procurement_view',
        'quotes_view', 'reports_export', 'reports_manage_scheduled', 'reports_view_dashboards',
        'reports_view_financial', 'resourcing_view_payroll', 'tickets_view', 'view_profitability',
    ),
    'auditors': (
        'assets_view', 'audit_view', 'change_view', 'contracts_view', 'crm_view', 'docs_view',
        'events_view', 'integrations_view', 'kb_view_articles', 'monitoring_view',
        'org_view_members', 'problem_view', 'procurement_view', 'quotes_view', 'release_view',
        'reports_view_capacity', 'reports_view_dashboards', 'reports_view_sla',
        'security_alerts_view', 'tickets_view', 'tickets_view_all', 'tickets_view_internal',
        'vehicles_view', 'view_backup_status',
    ),
}


def forwards(apps, schema_editor):
    TechnicianGroup = apps.get_model('tech_access', 'TechnicianGroup')
    for g in TechnicianGroup.objects.filter(seed_key__in=list(DEFAULTS)).select_related('role_template'):
        if g.feature_permissions:
            continue
        keys = DEFAULTS[g.seed_key]
        role = g.role_template
        if role is None or any(not getattr(role, k, False) for k in keys):
            continue  # would widen what members hold today
        g.feature_permissions = list(keys)
        g.save(update_fields=['feature_permissions'])


def backwards(apps, schema_editor):
    TechnicianGroup = apps.get_model('tech_access', 'TechnicianGroup')
    for g in TechnicianGroup.objects.filter(seed_key__in=list(DEFAULTS)):
        if sorted(g.feature_permissions or []) == sorted(DEFAULTS[g.seed_key]):
            g.feature_permissions = []
            g.save(update_fields=['feature_permissions'])


class Migration(migrations.Migration):

    dependencies = [
        ('tech_access', '0010_techniciangroup_feature_permissions'),
        ('accounts', '0067_userprofile_last_global_view_at'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
