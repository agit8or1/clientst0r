"""Phase 8: RoleTemplate.rmm_tier and the four built-in RMM role templates.

Every existing template gets rmm_tier = '' (no change in access). The new
templates are only created, never updated: an install that already has a
template with one of these names (organization NULL) keeps it as it is.
The list below is a frozen copy of accounts.rmm_role_templates.
"""
from django.db import migrations, models

_L1 = dict(
    vault_view=True, assets_view=True, docs_view=True, files_view=True, monitoring_view=True,
    org_view_members=True, kb_view_articles=True, reports_view_dashboards=True, procurement_view=True,
    change_view=True, change_create=True, problem_view=True, problem_create=True, release_view=True,
    security_alerts_view=True, psa_ai_view=True, psa_ai_request_triage=True,
    tickets_view=True, tickets_create=True, tickets_edit=True, tickets_close=True,
)
_L2 = dict(
    _L1, assets_edit=True, docs_create=True, docs_edit=True, files_upload=True, monitoring_trigger=True,
    kb_edit_articles=True, security_alerts_acknowledge=True, catalog_propose_change=True,
)
_L3 = dict(
    _L2, assets_create=True, monitoring_create=True, monitoring_edit=True, kb_move_articles=True,
    change_implement=True, problem_assign=True, problem_resolve=True, tickets_assign=True,
)
_PLATFORM = dict(
    vault_view=True, assets_view=True, docs_view=True, files_view=True, monitoring_view=True,
    integrations_view=True, integrations_configure=True, integrations_sync=True,
    audit_view=True, audit_export=True, org_view_members=True, org_manage_settings=True,
    security_alerts_view=True, security_alerts_manage_connections=True, kb_view_articles=True,
    reports_view_dashboards=True, tickets_view=True,
)

TEMPLATES = [
    ('RMM L1 — Help Desk', 'l1',
     'Reads permitted devices and alerts, views approved diagnostics, requests remote support and submits '
     'remediation requests. No unrestricted shell or scripts; no credential reveal without the vault '
     'permission.', _L1),
    ('RMM L2 — Technician', 'l2',
     'L1 plus approved diagnostics and workflows, private RMM handoffs, scoped script execution only where '
     'specifically granted, and restricted patch deployment (standard workstations, second-person approval).',
     _L2),
    ('RMM L3 — Senior Technician', 'l3',
     "L2 plus expanded device administration and remediation, advanced diagnostics, automation and "
     "deployment (high-impact work needs a second person). Never automatic all-tenant access or security "
     "administration.", _L3),
    ('Platform Administrator', 'platform_admin',
     'Integration configuration, RMM policy and role management, security settings and audit review. Grants '
     'no device work by itself.', _PLATFORM),
]


def create_templates(apps, schema_editor):
    RoleTemplate = apps.get_model('accounts', 'RoleTemplate')
    booleans = [f.name for f in RoleTemplate._meta.get_fields()
                if isinstance(f, models.BooleanField) and f.name != 'is_system_template']
    for name, tier, description, flags in TEMPLATES:
        if RoleTemplate.objects.filter(name=name, organization__isnull=True).exists():
            continue
        data = {f: False for f in booleans}
        data.update({k: v for k, v in flags.items() if k in data})
        RoleTemplate.objects.create(name=name, organization=None, is_system_template=True,
                                    description=description, rmm_tier=tier, **data)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0039_roletemplate_routing_manage_rules_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='roletemplate',
            name='rmm_tier',
            field=models.CharField(
                blank=True, default='', max_length=20,
                choices=[('', 'None'), ('l1', 'RMM L1'), ('l2', 'RMM L2'), ('l3', 'RMM L3'),
                         ('platform_admin', 'Platform Administrator')],
                help_text='RMM role tier, from the global role template only.'),
        ),
        # Reverse leaves the rows: removing templates could strand memberships.
        migrations.RunPython(create_templates, migrations.RunPython.noop),
    ]
