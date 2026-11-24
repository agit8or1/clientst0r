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
    'settings_access': 'roles-and-access',
    'settings_integrations': 'integrations',
    'settings_system': 'auto-update',
    'settings_maintenance': 'backup-and-restore',
    'account_help': 'getting-started',
    'account_apps': 'install-app',
}

# Sections without a guide yet, by roadmap batch.
PENDING_SECTIONS = frozenset({
    # 112.3 Clients, assets and network
    'clients_onboarding', 'assets_all', 'assets_diagrams', 'assets_infra', 'assets_ipam', 'ops_inventory',
    'ops_vehicles',
    # 112.4 Business
    'mod_crm', 'mod_licensing', 'psa_quotes', 'psa_procurement', 'psa_vendors', 'mod_health',
    # 112.5 Knowledge and vault
    'docs_documents', 'docs_kb', 'docs_diagrams', 'docs_review', 'docs_readiness', 'vault_passwords',
    'vault_personal', 'vault_notes',
    # 112.6 Security and monitoring
    'mod_security', 'mod_security_ops', 'ops_monitoring',
    # 112.7 Reports
    'mod_reports',
    # 112.8 Administration
    'settings_general', 'settings_security', 'settings_ai', 'settings_automation', 'settings_email',
    'settings_features',
    # 112.9 Your account
    'account_profile', 'account_work',
})

# Guides (by slug) without an annotated figure yet (112.10 and the batches above).
GUIDES_WITHOUT_FIGURE = frozenset({
    'what-is-clientst0r', 'features', 'admin-guide', 'screenshots', 'faq',
    'ticket-routing', 'msp-documentation', 'hardware-inventory', 'office-documents',
    'pulse-checks', 'backup-monitoring', 'ai-troubleshoot',
    'payments', 'tax',
    'technician-access', 'client-data-protection', 'azure-sso', 'oidc-sso', 'security-policy',
    'integrations', 'api-access', 'api-multi-org', 'graphql-api', 'browser-extension-api',
    'importing-from-it-glue', 'importing-from-hudu',
    'install', 'docker', 'upgrade-and-recovery', 'manual-update', 'upgrade-notes',
    'seeding-data', 'package-scanner', 'install-app',
})


def has_figure(guide) -> bool:
    path = Path(settings.BASE_DIR) / guide.path
    return path.is_file() and bool(FIGURE_RE.search(path.read_text(encoding='utf-8')))


def guide_for_section(key: str):
    """The guide that documents navigation section `key`, or None."""
    from core.guides import GUIDES_BY_SLUG
    slug = SECTION_GUIDES.get(key)
    return GUIDES_BY_SLUG.get(slug) if slug else None
