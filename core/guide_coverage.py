"""Which guide documents each part of the application (roadmap 112.1).

Every navigation section (core.navigation.SECTIONS) is either documented by a
guide in Clientst0r Docs (SECTION_GUIDES) or still waiting for one
(PENDING_SECTIONS). Every guide either carries an annotated figure (a
``<!-- guide-figure: … -->`` block filled by scripts/guide_figures.py) or is
still waiting for one (GUIDES_WITHOUT_FIGURE).

The two waiting lists only shrink: core.tests.test_guide_coverage fails when
an entry is done but still listed, and when either list grows past its
recorded size. A new navigation section therefore arrives with its guide.

A section counts as documented only when the guide explains how to use it,
not when it is mentioned in passing.
"""
from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings

FIGURE_RE = re.compile(r'<!-- guide-figure: [\w-]+ -->')

# Navigation section key -> slug of the guide (core.guides.GUIDES) that documents it.
SECTION_GUIDES = {
    'clients_onboarding': 'assets',
    'assets_all': 'assets',
    'assets_ipam': 'assets',
    'assets_infra': 'infrastructure',
    'assets_diagrams': 'infrastructure',
    'ops_inventory': 'inventory-and-vehicles',
    'ops_vehicles': 'inventory-and-vehicles',
    'psa_my_work': 'my-work',
    'psa_shifts': 'my-work',
    'ops_scheduling': 'my-work',
    'psa_tickets': 'tickets',
    'psa_dispatch': 'tickets',
    'psa_projects': 'tickets',
    'psa_service': 'service-management',
    'ops_workflows': 'workflows',
    'clients_all': 'organizations',
    'assets_hardware': 'hardware-inventory',
    'assets_backups': 'backup-monitoring',
    'mod_contracts': 'billing',
    'psa_invoices': 'billing',
    'psa_billing': 'billing',
    'mod_pulse': 'pulse-checks',
    'mod_crm': 'crm',
    'psa_quotes': 'quotes-and-licensing',
    'mod_licensing': 'quotes-and-licensing',
    'psa_procurement': 'procurement',
    'psa_vendors': 'procurement',
    'mod_health': 'client-health',
    'docs_documents': 'documents-and-diagrams',
    'docs_diagrams': 'documents-and-diagrams',
    'docs_kb': 'knowledge-base',
    'docs_review': 'knowledge-base',
    'docs_readiness': 'knowledge-base',
    'vault_passwords': 'password-vault',
    'vault_personal': 'password-vault',
    'vault_notes': 'password-vault',
    'mod_reports': 'reports',
    'mod_security': 'security-alerts-and-incidents',
    'mod_security_ops': 'security-alerts-and-incidents',
    'ops_monitoring': 'monitoring',
    'settings_general': 'settings-general',
    'settings_security': 'security-settings',
    'settings_ai': 'ai-automation-and-communications',
    'settings_automation': 'ai-automation-and-communications',
    'settings_email': 'ai-automation-and-communications',
    'settings_features': 'admin-guide',
    'settings_access': 'roles-and-access',
    'settings_integrations': 'integrations',
    'settings_system': 'auto-update',
    'settings_maintenance': 'backup-and-restore',
    'account_profile': 'your-account',
    'account_work': 'my-work',
    'account_help': 'getting-started',
    'account_apps': 'install-app',
}

# Sections without a guide yet, by roadmap batch.
PENDING_SECTIONS = frozenset({
})

# Guides (by slug) without an annotated figure yet (112.10 and the batches above).
GUIDES_WITHOUT_FIGURE = frozenset({
    'screenshots',  # the screenshot gallery itself
})


def has_figure(guide) -> bool:
    path = Path(settings.BASE_DIR) / guide.path
    return path.is_file() and bool(FIGURE_RE.search(path.read_text(encoding='utf-8')))


def guide_for_section(key: str):
    """The guide that documents navigation section `key`, or None."""
    from core.guides import GUIDES_BY_SLUG
    slug = SECTION_GUIDES.get(key)
    return GUIDES_BY_SLUG.get(slug) if slug else None
