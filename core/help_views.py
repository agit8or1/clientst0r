"""
Integrated documentation and help system
"""
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
import markdown
import os
import re


# ── Searchable index ─────────────────────────────────────────────────────────
# Each entry: section title, url name, anchor id, heading, plain-text keywords
HELP_INDEX = [
    # Getting Started
    {'section': 'Getting Started', 'url_name': 'core:help_getting_started',
     'anchor': 'quick-start', 'heading': 'Quick Start',
     'text': 'setup organization users login first steps onboarding'},
    {'section': 'Getting Started', 'url_name': 'core:help_getting_started',
     'anchor': 'organizations', 'heading': 'Organizations',
     'text': 'organizations clients multi-tenant isolation scoping'},
    {'section': 'Getting Started', 'url_name': 'core:help_getting_started',
     'anchor': 'users-roles', 'heading': 'Users & Roles',
     'text': 'users roles permissions rbac owner admin editor read-only invite'},
    {'section': 'Getting Started', 'url_name': 'core:help_getting_started',
     'anchor': 'api-keys', 'heading': 'API Keys',
     'text': 'api keys authentication tokens bearer authorization profile'},

    # Assets
    {'section': 'Asset Management', 'url_name': 'core:help_assets',
     'anchor': 'asset-tracking', 'heading': 'Asset Tracking',
     'text': 'asset tracking make model serial number purchase date warranty lifecycle custom fields attachments photos QR code'},
    {'section': 'Asset Management', 'url_name': 'core:help_assets',
     'anchor': 'network-management', 'heading': 'Network Management',
     'text': 'network ip address subnet vlan mac address topology diagram port assignment switch patch panel'},
    {'section': 'Asset Management', 'url_name': 'core:help_assets',
     'anchor': 'rack-management', 'heading': 'Rack Management',
     'text': 'rack data center location u-space drag drop power consumption temperature humidity'},
    {'section': 'Asset Management', 'url_name': 'core:help_assets',
     'anchor': 'port-configuration', 'heading': 'Port Configuration',
     'text': 'port configuration switch patch panel access trunk hybrid vlan native tagged speed status'},
    {'section': 'Asset Management', 'url_name': 'core:help_assets',
     'anchor': 'asset-categories', 'heading': 'Asset Categories',
     'text': 'server virtual machine network switch router firewall storage NAS SAN workstation laptop mobile printer UPS PDU'},
    {'section': 'Asset Management', 'url_name': 'core:help_assets',
     'anchor': 'reporting', 'heading': 'Reporting & Analytics',
     'text': 'report analytics export csv pdf depreciation warranty alert needs reorder'},

    # Vehicles
    {'section': 'Service Vehicles', 'url_name': 'core:help_vehicles',
     'anchor': 'vehicle-tracking', 'heading': 'Vehicle Tracking',
     'text': 'vehicle fleet tracking make model year VIN license plate mileage odometer status condition GPS'},
    {'section': 'Service Vehicles', 'url_name': 'core:help_vehicles',
     'anchor': 'insurance', 'heading': 'Insurance & Registration',
     'text': 'insurance registration policy provider expiration premium renewal alert 30 days'},
    {'section': 'Service Vehicles', 'url_name': 'core:help_vehicles',
     'anchor': 'maintenance', 'heading': 'Maintenance Management',
     'text': 'maintenance service history oil change tire rotation inspection scheduled cost labor parts next due overdue'},
    {'section': 'Service Vehicles', 'url_name': 'core:help_vehicles',
     'anchor': 'fuel', 'heading': 'Fuel Tracking',
     'text': 'fuel log fill-up gallons cost MPG miles per gallon efficiency trend analysis'},
    {'section': 'Service Vehicles', 'url_name': 'core:help_vehicles',
     'anchor': 'damage', 'heading': 'Damage Reporting',
     'text': 'damage incident report photo severity minor moderate major repair tracking insurance claim'},
    {'section': 'Service Vehicles', 'url_name': 'core:help_vehicles',
     'anchor': 'vehicle-inventory', 'heading': 'Vehicle Inventory',
     'text': 'vehicle inventory equipment cables tools hardware quantity low stock value storage location'},

    # Vault
    {'section': 'Password Vault', 'url_name': 'core:help_vault',
     'anchor': 'security-features', 'heading': 'Security Features',
     'text': 'AES-256 encryption zero knowledge master password access control audit log'},
    {'section': 'Password Vault', 'url_name': 'core:help_vault',
     'anchor': 'breach-detection', 'heading': 'Breach Detection',
     'text': 'breach detection HIBP have i been pwned compromised password alert scan reuse'},
    {'section': 'Password Vault', 'url_name': 'core:help_vault',
     'anchor': 'password-management', 'heading': 'Password Management',
     'text': 'password store organize search copy clipboard show hide notes URL tags labels'},
    {'section': 'Password Vault', 'url_name': 'core:help_vault',
     'anchor': 'password-generator', 'heading': 'Password Generator',
     'text': 'password generator random strong cryptographic length character passphrase pronounceable'},
    {'section': 'Password Vault', 'url_name': 'core:help_vault',
     'anchor': 'totp', 'heading': 'TOTP / Two-Factor Auth',
     'text': 'TOTP two factor 2FA authenticator QR code one-time password OTP'},
    {'section': 'Password Vault', 'url_name': 'core:help_vault',
     'anchor': 'sharing', 'heading': 'Sharing & Collaboration',
     'text': 'share credential organization access control read-only temporary history'},
    {'section': 'Password Vault', 'url_name': 'core:help_vault',
     'anchor': 'import-export', 'heading': 'Import & Export',
     'text': 'import export CSV LastPass 1Password backup migrate'},

    # Monitoring
    {'section': 'Website & WAN Monitoring', 'url_name': 'core:help_monitoring',
     'anchor': 'overview', 'heading': 'Overview',
     'text': 'website monitor WAN connection outbound check from the server no agent'},
    {'section': 'Website & WAN Monitoring', 'url_name': 'core:help_monitoring',
     'anchor': 'website-monitors', 'heading': 'Website Monitors',
     'text': 'HTTP HTTPS URL check interval status code redirect response time history uptime 30 90 365'},
    {'section': 'Website & WAN Monitoring', 'url_name': 'core:help_monitoring',
     'anchor': 'alerting', 'heading': 'Alerting',
     'text': 'alert down recovery email webhook monitor.down monitor.up check_failed threshold'},
    {'section': 'Website & WAN Monitoring', 'url_name': 'core:help_monitoring',
     'anchor': 'ssl-monitoring', 'heading': 'Certificate and Domain Expiry',
     'text': 'SSL certificate expiry warning days issuer domain expiration WHOIS daily email'},
    {'section': 'Website & WAN Monitoring', 'url_name': 'core:help_monitoring',
     'anchor': 'wan-checks', 'heading': 'WAN Connection Checks',
     'text': 'WAN ping monitor target check status on demand not scheduled no alerts'},
    {'section': 'Website & WAN Monitoring', 'url_name': 'core:help_monitoring',
     'anchor': 'status-pages', 'heading': 'Status Pages and Incidents',
     'text': 'status page incident maintenance window uptime published'},

    # Security
    {'section': 'Security', 'url_name': 'core:help_security',
     'anchor': 'vulnerability-scanning', 'heading': 'Vulnerability Scanning',
     'text': 'vulnerability scan CVE python package OS severity critical high medium low scheduled fix'},
    {'section': 'Security', 'url_name': 'core:help_security',
     'anchor': 'authentication', 'heading': 'Authentication & Access Control',
     'text': '2FA two-factor TOTP Azure AD SSO password policy session timeout IP whitelist lockout'},
    {'section': 'Security', 'url_name': 'core:help_security',
     'anchor': 'rbac', 'heading': 'Role-Based Access Control',
     'text': 'RBAC role permissions owner admin editor read-only custom organization scoping'},
    {'section': 'Security', 'url_name': 'core:help_security',
     'anchor': 'audit-logging', 'heading': 'Audit Logging',
     'text': 'audit log action timestamp user change before after search filter export retention immutable'},
    {'section': 'Security', 'url_name': 'core:help_security',
     'anchor': 'data-protection', 'heading': 'Data Protection',
     'text': 'encryption rest transit TLS backup GDPR data privacy secure file'},

    # API
    {'section': 'API', 'url_name': 'core:help_api',
     'anchor': 'api-overview', 'heading': 'API Overview',
     'text': 'REST API GraphQL webhook API key authentication rate limit'},
    {'section': 'API', 'url_name': 'core:help_api',
     'anchor': 'authentication', 'heading': 'Authentication',
     'text': 'API key bearer token Authorization header profile settings generate'},
    {'section': 'API', 'url_name': 'core:help_api',
     'anchor': 'rest-api', 'heading': 'REST API',
     'text': 'REST endpoint assets passwords organizations vehicles monitors GET POST PUT DELETE'},
    {'section': 'API', 'url_name': 'core:help_api',
     'anchor': 'webhooks', 'heading': 'Webhooks',
     'text': 'webhook event payload asset created updated monitor down up vulnerability breach'},
    {'section': 'API', 'url_name': 'core:help_api',
     'anchor': 'filtering', 'heading': 'Filtering & Pagination',
     'text': 'filter search ordering pagination page size query parameter'},

    # Reports
    {'section': 'Reports & Analytics', 'url_name': 'core:help_reports',
     'anchor': 'dashboards', 'heading': 'Custom Dashboards',
     'text': 'dashboard widget analytics asset count warranty monitor status vault health activity'},
    {'section': 'Reports & Analytics', 'url_name': 'core:help_reports',
     'anchor': 'report-templates', 'heading': 'Report Templates',
     'text': 'report template data source filter columns CSV PDF export inventory warranty depreciation'},
    {'section': 'Reports & Analytics', 'url_name': 'core:help_reports',
     'anchor': 'scheduled-reports', 'heading': 'Scheduled Reports',
     'text': 'scheduled report recurring daily weekly monthly email delivery automation'},
    {'section': 'Reports & Analytics', 'url_name': 'core:help_reports',
     'anchor': 'analytics', 'heading': 'Analytics',
     'text': 'analytics trend chart asset growth uptime vault usage audit events'},

    # Workflows
    {'section': 'Workflows', 'url_name': 'core:help_workflows',
     'anchor': 'processes', 'heading': 'Processes',
     'text': 'workflow process checklist stages steps onboarding offboarding maintenance incident procedure'},
    {'section': 'Workflows', 'url_name': 'core:help_workflows',
     'anchor': 'executing', 'heading': 'Executing a Process',
     'text': 'execute run workflow checklist stage complete progress audit trail assigned user'},
    {'section': 'Workflows', 'url_name': 'core:help_workflows',
     'anchor': 'global-processes', 'heading': 'Global Processes',
     'text': 'global process shared organization standard procedure template library'},

    # Documentation
    {'section': 'Documentation & KB', 'url_name': 'core:help_documentation',
     'anchor': 'documents', 'heading': 'Documents',
     'text': 'document runbook WYSIWYG markdown editor upload category tag knowledge base'},
    {'section': 'Documentation & KB', 'url_name': 'core:help_documentation',
     'anchor': 'templates', 'heading': 'Document Templates',
     'text': 'document template reusable skeleton runbook client report onboarding'},
    {'section': 'Documentation & KB', 'url_name': 'core:help_documentation',
     'anchor': 'knowledge-base', 'heading': 'Knowledge Base',
     'text': 'knowledge base KB article search category global publish organization'},
    {'section': 'Documentation & KB', 'url_name': 'core:help_documentation',
     'anchor': 'diagrams', 'heading': 'Network Diagrams',
     'text': 'network diagram topology visual drag drop node switch server connection export'},
    {'section': 'Documentation & KB', 'url_name': 'core:help_documentation',
     'anchor': 'ai-assistant', 'heading': 'AI Writing Assistant',
     'text': 'AI assistant generate enhance validate document draft improve quality'},

    # Locations
    {'section': 'Locations & WAN', 'url_name': 'core:help_locations',
     'anchor': 'locations', 'heading': 'Locations',
     'text': 'location site office data center address floor plan physical'},
    {'section': 'Locations & WAN', 'url_name': 'core:help_locations',
     'anchor': 'wan-connections', 'heading': 'WAN Connections',
     'text': 'WAN internet connection ISP fibre cable DSL bandwidth circuit ID public IP contract'},
]


def _highlight(text, query):
    """Wrap query matches in <mark> tags (case-insensitive)."""
    if not query:
        return text
    escaped = re.escape(query)
    return re.sub(f'({escaped})', r'<mark>\1</mark>', text, flags=re.IGNORECASE)


@login_required
def help_search(request):
    """Full-text search across all help sections."""
    q = request.GET.get('q', '').strip()
    results = []
    if q:
        q_lower = q.lower()
        seen = set()
        for entry in HELP_INDEX:
            key = (entry['url_name'], entry['anchor'])
            if key in seen:
                continue
            haystack = (
                entry['heading'] + ' ' +
                entry['text'] + ' ' +
                entry['section']
            ).lower()
            if q_lower in haystack:
                seen.add(key)
                results.append({
                    **entry,
                    'heading_hl': _highlight(entry['heading'], q),
                    'text_hl': _highlight(entry['text'], q),
                    'section_hl': _highlight(entry['section'], q),
                })
    return render(request, 'core/help/search_results.html', {
        'q': q,
        'results': results,
        'title': 'Help Search',
    })


@login_required
def help_index(request):
    """Main help documentation index"""
    sections = [
        {'icon': 'fa-rocket', 'title': 'Getting Started', 'url_name': 'core:help_getting_started',
         'desc': 'First steps, organizations, users, and API keys.'},
        {'icon': 'fa-server', 'title': 'Asset Management', 'url_name': 'core:help_assets',
         'desc': 'Track hardware, networks, racks, and ports.'},
        {'icon': 'fa-truck', 'title': 'Service Vehicles', 'url_name': 'core:help_vehicles',
         'desc': 'Fleet management, maintenance, fuel, and damage reports.'},
        {'icon': 'fa-lock', 'title': 'Password Vault', 'url_name': 'core:help_vault',
         'desc': 'Encrypted credential storage, breach detection, and TOTP.'},
        {'icon': 'fa-heartbeat', 'title': 'Website & WAN Monitoring', 'url_name': 'core:help_monitoring',
         'desc': 'Scheduled website checks with down alerts and certificate expiry; on-demand WAN ping checks.'},
        {'icon': 'fa-shield-alt', 'title': 'Security', 'url_name': 'core:help_security',
         'desc': 'Vulnerability scanning, RBAC, audit logging, and 2FA.'},
        {'icon': 'fa-chart-bar', 'title': 'Reports & Analytics', 'url_name': 'core:help_reports',
         'desc': 'Custom dashboards, report templates, scheduled reports, and analytics.'},
        {'icon': 'fa-tasks', 'title': 'Workflows', 'url_name': 'core:help_workflows',
         'desc': 'Step-by-step checklists and process executions for repeatable IT tasks.'},
        {'icon': 'fa-book', 'title': 'Documentation & KB', 'url_name': 'core:help_documentation',
         'desc': 'Runbooks, knowledge base articles, network diagrams, and AI writing assistant.'},
        {'icon': 'fa-map-marker-alt', 'title': 'Locations & WAN', 'url_name': 'core:help_locations',
         'desc': 'Physical site management and WAN internet connection tracking.'},
        {'icon': 'fa-plug', 'title': 'API & Integrations', 'url_name': 'core:help_api',
         'desc': 'REST API, webhooks, authentication, and RMM integrations.'},
    ]
    return render(request, 'core/help/index.html', {
        'title': 'Help & Documentation',
        'sections': sections,
    })


@login_required
def help_getting_started(request):
    """Getting started guide"""
    toc = [
        {'anchor': 'quick-start', 'heading': 'Quick Start'},
        {'anchor': 'organizations', 'heading': 'Organizations'},
        {'anchor': 'users-roles', 'heading': 'Users & Roles'},
        {'anchor': 'api-keys', 'heading': 'API Keys'},
    ]
    content = """
    <h4>Getting Started with ClientSt0r</h4>
    <p class="lead">Welcome! This guide walks you through setting up your instance and getting your team up and running.</p>

    <h5 class="mt-4" id="quick-start"><i class="fas fa-rocket"></i> Quick Start</h5>
    <ol>
        <li><strong>Log in</strong> — Use your credentials or Azure AD SSO if configured.</li>
        <li><strong>Create or select an Organization</strong> — All data is scoped to organizations.</li>
        <li><strong>Invite your team</strong> — Go to <em>Settings → Users</em> and invite members.</li>
        <li><strong>Assign roles</strong> — Grant appropriate permissions (Owner, Admin, Editor, Read-Only).</li>
        <li><strong>Add assets or passwords</strong> — Start populating your inventory or vault.</li>
        <li><strong>Set up monitoring</strong> — Create monitors for servers and services.</li>
    </ol>

    <h5 class="mt-4" id="organizations"><i class="fas fa-building"></i> Organizations</h5>
    <p>Organizations are the top-level containers for all data. ClientSt0r is multi-tenant — each client, department, or team has its own organization with full data isolation.</p>
    <ul>
        <li><strong>Create:</strong> <em>Admin → Organizations → New Organization</em></li>
        <li><strong>Switch:</strong> Use the organization selector in the top navigation</li>
        <li><strong>Scoping:</strong> Assets, passwords, vehicles, and monitors all belong to one organization</li>
        <li><strong>Global items:</strong> Some templates and reference data are shared across all organizations</li>
    </ul>

    <div class="help-screenshot mt-3 mb-4">
      <svg viewBox="0 0 700 200" xmlns="http://www.w3.org/2000/svg" class="help-svg-screenshot">
        <!-- Top nav bar -->
        <rect width="700" height="48" fill="#161b22" stroke="#30363d"/>
        <text x="16" y="30" fill="#e6edf3" font-size="14" font-weight="bold" font-family="sans-serif">ClientSt0r</text>
        <!-- Org selector button -->
        <rect x="180" y="10" width="180" height="28" rx="5" fill="#1f2937" stroke="#30363d"/>
        <circle cx="198" cy="24" r="8" fill="#1f6feb"/>
        <text x="210" y="28" fill="#e6edf3" font-size="11" font-family="sans-serif">Acme Corp  ▾</text>
        <!-- Nav links -->
        <text x="390" y="28" fill="#8b949e" font-size="11" font-family="sans-serif">Assets</text>
        <text x="450" y="28" fill="#8b949e" font-size="11" font-family="sans-serif">Vault</text>
        <text x="510" y="28" fill="#8b949e" font-size="11" font-family="sans-serif">Vehicles</text>
        <text x="590" y="28" fill="#8b949e" font-size="11" font-family="sans-serif">👤 jsmith</text>
        <!-- Dropdown -->
        <rect x="180" y="40" width="200" height="145" rx="5" fill="#1c2128" stroke="#30363d"/>
        <text x="196" y="60" fill="#8b949e" font-size="10" font-family="sans-serif">SWITCH ORGANIZATION</text>
        <!-- Org list items -->
        <rect x="186" y="66" width="188" height="26" rx="4" fill="#1f6feb22"/>
        <circle cx="200" cy="79" r="7" fill="#1f6feb"/>
        <text x="212" y="83" fill="#e6edf3" font-size="11" font-family="sans-serif">Acme Corp</text>
        <text x="348" y="83" fill="#3fb950" font-size="9" font-family="sans-serif">✓</text>
        <rect x="186" y="96" width="188" height="26" rx="4" fill="transparent"/>
        <circle cx="200" cy="109" r="7" fill="#6e40c9"/>
        <text x="212" y="113" fill="#c9d1d9" font-size="11" font-family="sans-serif">Beta Client Inc</text>
        <rect x="186" y="126" width="188" height="26" rx="4" fill="transparent"/>
        <circle cx="200" cy="139" r="7" fill="#e3701b"/>
        <text x="212" y="143" fill="#c9d1d9" font-size="11" font-family="sans-serif">Gamma Solutions</text>
        <line x1="186" y1="158" x2="374" y2="158" stroke="#30363d" stroke-width="1"/>
        <text x="196" y="175" fill="#58a6ff" font-size="11" font-family="sans-serif">+ New Organization</text>
        <!-- Annotation -->
        <line x1="270" y1="40" x2="320" y2="10" stroke="#79c0ff" stroke-width="1.5" stroke-dasharray="3,2"/>
        <rect x="310" y="1" width="170" height="14" rx="7" fill="#1f6feb44"/>
        <text x="395" y="12" fill="#79c0ff" font-size="10" font-family="sans-serif" text-anchor="middle">Click to switch organization</text>
      </svg>
      <p class="help-screenshot-caption">Organization selector in the top navigation — switch between clients instantly. All data (assets, passwords, monitors) is isolated per organization.</p>
    </div>

    <h5 class="mt-4" id="users-roles"><i class="fas fa-users"></i> Users &amp; Roles</h5>
    <p>Access control uses role-based permissions with four built-in roles:</p>
    <div class="table-responsive mt-3">
        <table class="table table-sm table-bordered">
            <thead><tr><th>Role</th><th>Capabilities</th></tr></thead>
            <tbody>
                <tr><td><span class="badge bg-danger">Owner</span></td><td>Full control including billing and organization deletion</td></tr>
                <tr><td><span class="badge bg-warning text-dark">Admin</span></td><td>Manage users, settings, all data — no billing</td></tr>
                <tr><td><span class="badge bg-primary">Editor</span></td><td>Create and edit data; cannot manage users or settings</td></tr>
                <tr><td><span class="badge bg-secondary">Read-Only</span></td><td>View data only; cannot create, edit, or delete</td></tr>
            </tbody>
        </table>
    </div>
    <p>Custom roles with 42 granular permissions are available for fine-grained control.</p>

    <div class="help-screenshot mt-3 mb-4">
      <svg viewBox="0 0 700 180" xmlns="http://www.w3.org/2000/svg" class="help-svg-screenshot">
        <rect width="700" height="180" rx="6" fill="#1a1f2e" stroke="#30363d"/>
        <!-- Header -->
        <rect width="700" height="36" rx="6" fill="#161b22" stroke="#30363d"/>
        <rect y="18" width="700" height="18" fill="#161b22"/>
        <text x="16" y="22" fill="#8b949e" font-size="10" font-family="monospace">User</text>
        <text x="200" y="22" fill="#8b949e" font-size="10" font-family="monospace">Email</text>
        <text x="400" y="22" fill="#8b949e" font-size="10" font-family="monospace">Role</text>
        <text x="520" y="22" fill="#8b949e" font-size="10" font-family="monospace">Last Active</text>
        <text x="630" y="22" fill="#8b949e" font-size="10" font-family="monospace">Actions</text>
        <!-- Rows -->
        <rect y="36" width="700" height="36" fill="#0d1117" stroke="#21262d" stroke-width="0.5"/>
        <text x="16" y="58" fill="#e6edf3" font-size="12" font-family="sans-serif">John Smith</text>
        <text x="200" y="58" fill="#8b949e" font-size="11" font-family="sans-serif">j.smith@acme.com</text>
        <rect x="400" y="46" width="48" height="16" rx="8" fill="#da3633"/>
        <text x="424" y="58" fill="#fff" font-size="10" font-family="sans-serif" text-anchor="middle">Owner</text>
        <text x="520" y="58" fill="#8b949e" font-size="11" font-family="sans-serif">2m ago</text>

        <rect y="72" width="700" height="36" fill="#161b22" stroke="#21262d" stroke-width="0.5"/>
        <text x="16" y="94" fill="#e6edf3" font-size="12" font-family="sans-serif">Sarah Lee</text>
        <text x="200" y="94" fill="#8b949e" font-size="11" font-family="sans-serif">s.lee@acme.com</text>
        <rect x="400" y="82" width="44" height="16" rx="8" fill="#9a6700"/>
        <text x="422" y="94" fill="#fff" font-size="10" font-family="sans-serif" text-anchor="middle">Admin</text>
        <text x="520" y="94" fill="#8b949e" font-size="11" font-family="sans-serif">1h ago</text>

        <rect y="108" width="700" height="36" fill="#0d1117" stroke="#21262d" stroke-width="0.5"/>
        <text x="16" y="130" fill="#e6edf3" font-size="12" font-family="sans-serif">Mike Johnson</text>
        <text x="200" y="130" fill="#8b949e" font-size="11" font-family="sans-serif">m.johnson@acme.com</text>
        <rect x="400" y="118" width="46" height="16" rx="8" fill="#1f6feb"/>
        <text x="423" y="130" fill="#fff" font-size="10" font-family="sans-serif" text-anchor="middle">Editor</text>
        <text x="520" y="130" fill="#8b949e" font-size="11" font-family="sans-serif">3d ago</text>

        <rect y="144" width="700" height="36" fill="#161b22" stroke="#21262d" stroke-width="0.5"/>
        <text x="16" y="166" fill="#e6edf3" font-size="12" font-family="sans-serif">Anna Chen</text>
        <text x="200" y="166" fill="#8b949e" font-size="11" font-family="sans-serif">a.chen@acme.com</text>
        <rect x="400" y="154" width="68" height="16" rx="8" fill="#3d444d"/>
        <text x="434" y="166" fill="#e6edf3" font-size="10" font-family="sans-serif" text-anchor="middle">Read-Only</text>
        <text x="520" y="166" fill="#8b949e" font-size="11" font-family="sans-serif">1w ago</text>
      </svg>
      <p class="help-screenshot-caption">User management table showing the four built-in roles. Roles are color-coded: <strong style="color:#f85149">Owner</strong> (red), <strong style="color:#d29922">Admin</strong> (amber), <strong style="color:#58a6ff">Editor</strong> (blue), <strong style="color:#8b949e">Read-Only</strong> (grey).</p>
    </div>

    <h5 class="mt-4" id="api-keys"><i class="fas fa-key"></i> API Keys</h5>
    <p>API keys authenticate programmatic access to the REST API and the browser extension.</p>
    <ul>
        <li><strong>Generate:</strong> Click your username → <em>API Keys</em> → <em>Create New Key</em></li>
        <li><strong>Format:</strong> Keys are prefixed <code>itdocs_live_…</code></li>
        <li><strong>Usage:</strong> Pass as <code>Authorization: Bearer YOUR_KEY</code></li>
        <li><strong>Scope:</strong> Keys are tied to your user and inherit your organization access</li>
        <li><strong>Revoke:</strong> Delete a key instantly to invalidate all uses</li>
    </ul>

    <div class="help-screenshot mt-3 mb-4">
      <svg viewBox="0 0 700 160" xmlns="http://www.w3.org/2000/svg" class="help-svg-screenshot">
        <rect width="700" height="160" rx="6" fill="#1a1f2e" stroke="#30363d"/>
        <!-- Card header -->
        <rect width="700" height="42" rx="6" fill="#161b22" stroke="#30363d"/>
        <rect y="24" width="700" height="18" fill="#161b22"/>
        <text x="16" y="27" fill="#e6edf3" font-size="13" font-weight="bold" font-family="sans-serif">API Keys</text>
        <rect x="570" y="10" width="116" height="22" rx="4" fill="#1f6feb"/>
        <text x="628" y="25" fill="#fff" font-size="11" font-family="sans-serif" text-anchor="middle">+ Create New Key</text>
        <!-- Key row -->
        <rect x="12" y="52" width="676" height="42" rx="4" fill="#0d1117" stroke="#30363d"/>
        <text x="28" y="70" fill="#e6edf3" font-size="11" font-family="sans-serif">Browser Extension Key</text>
        <rect x="28" y="76" width="340" height="14" rx="3" fill="#161b22" stroke="#30363d"/>
        <text x="36" y="87" fill="#3fb950" font-size="10" font-family="monospace">itdocs_live_xK9mP…Qr7v</text>
        <rect x="380" y="73" width="66" height="18" rx="4" fill="#21262d" stroke="#30363d"/>
        <text x="413" y="85" fill="#8b949e" font-size="10" font-family="sans-serif" text-anchor="middle">⧉ Copy</text>
        <rect x="460" y="73" width="60" height="18" rx="4" fill="#21262d" stroke="#30363d"/>
        <text x="490" y="85" fill="#f85149" font-size="10" font-family="sans-serif" text-anchor="middle">🗑 Revoke</text>
        <text x="534" y="85" fill="#8b949e" font-size="10" font-family="sans-serif">Created 2d ago</text>
        <!-- Warning box -->
        <rect x="12" y="104" width="676" height="44" rx="4" fill="#3fb95022" stroke="#3fb95055"/>
        <text x="28" y="122" fill="#3fb950" font-size="11" font-family="sans-serif">✓ Key created! Copy it now — it will only be shown once.</text>
        <rect x="28" y="128" width="440" height="14" rx="3" fill="#161b22" stroke="#30363d"/>
        <text x="36" y="139" fill="#79c0ff" font-size="10" font-family="monospace">itdocs_live_xK9mPL3t8nQjR2sYfBdWcAeZuHvMoTgNiXkCpDwF4yEq0Qr7v</text>
        <!-- Annotations -->
        <line x1="200" y1="87" x2="200" y2="106" stroke="#f0b429" stroke-width="1.5" stroke-dasharray="3,2"/>
        <rect x="120" y="106" width="160" height="0" rx="8" fill="#f0b42944"/>
      </svg>
      <p class="help-screenshot-caption">API key management. Copy the full key immediately after creation — it is only shown once. Use the key prefix shown afterwards to identify it.</p>
    </div>
    """
    return render(request, 'core/help/section.html', {
        'title': 'Getting Started',
        'section_id': 'getting-started',
        'prev_section': None,
        'next_section': {'title': 'Asset Management', 'url_name': 'core:help_assets'},
        'toc': toc,
        'content': content,
    })


@login_required
def help_features(request):
    """Features documentation"""
    features_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'FEATURES.md')
    try:
        with open(features_path, 'r') as f:
            content = f.read()
            html_content = markdown.markdown(content, extensions=['tables', 'fenced_code', 'toc'])
    except Exception:
        html_content = "<p>Features documentation not available.</p>"

    return render(request, 'core/help/section.html', {
        'title': 'Features',
        'section_id': 'features',
        'toc': [],
        'content': html_content,
        'prev_section': None,
        'next_section': None,
    })


@login_required
def help_assets(request):
    """Asset management help"""
    toc = [
        {'anchor': 'asset-tracking', 'heading': 'Asset Tracking'},
        {'anchor': 'network-management', 'heading': 'Network Management'},
        {'anchor': 'rack-management', 'heading': 'Rack Management'},
        {'anchor': 'port-configuration', 'heading': 'Port Configuration'},
        {'anchor': 'asset-categories', 'heading': 'Asset Categories'},
        {'anchor': 'reporting', 'heading': 'Reporting & Analytics'},
    ]
    content = """
    <h4>Asset Management</h4>
    <p class="lead">Track and manage all IT equipment, servers, network devices, and hardware assets.</p>

    <h5 class="mt-4" id="asset-tracking"><i class="fas fa-server"></i> Asset Tracking</h5>
    <ul>
        <li><strong>Comprehensive Information:</strong> Track make, model, serial numbers, purchase dates, warranties</li>
        <li><strong>Custom Fields:</strong> Add unlimited custom fields for organization-specific needs</li>
        <li><strong>Attachments:</strong> Upload photos, manuals, invoices, and documentation</li>
        <li><strong>Relationships:</strong> Link related assets, dependencies, and parent/child relationships</li>
        <li><strong>QR Codes:</strong> Generate QR codes for physical asset labels</li>
        <li><strong>Lifecycle Tracking:</strong> Monitor asset status from purchase to retirement</li>
        <li><strong>Needs Reorder:</strong> Flag assets for physical replacement — visible in the asset list with a yellow badge</li>
    </ul>

    <div class="help-screenshot mt-3 mb-4">
      <svg viewBox="0 0 700 200" xmlns="http://www.w3.org/2000/svg" class="help-svg-screenshot">
        <rect width="700" height="200" rx="6" fill="#1a1f2e" stroke="#30363d"/>
        <!-- Table header -->
        <rect x="0" y="0" width="700" height="36" rx="6" fill="#161b22" stroke="#30363d"/>
        <rect x="0" y="18" width="700" height="18" fill="#161b22"/>
        <text x="16" y="22" fill="#8b949e" font-size="11" font-family="monospace">Name</text>
        <text x="200" y="22" fill="#8b949e" font-size="11" font-family="monospace">Type</text>
        <text x="320" y="22" fill="#8b949e" font-size="11" font-family="monospace">IP / Host</text>
        <text x="460" y="22" fill="#8b949e" font-size="11" font-family="monospace">Status</text>
        <text x="580" y="22" fill="#8b949e" font-size="11" font-family="monospace">Actions</text>
        <!-- Row 1 -->
        <rect x="0" y="36" width="700" height="40" fill="#0d1117" stroke="#21262d" stroke-width="0.5"/>
        <text x="16" y="60" fill="#e6edf3" font-size="12" font-family="sans-serif">Core Switch</text>
        <text x="200" y="60" fill="#79c0ff" font-size="11" font-family="sans-serif">Switch</text>
        <text x="320" y="60" fill="#8b949e" font-size="11" font-family="monospace">192.168.1.1</text>
        <rect x="460" y="48" width="54" height="18" rx="9" fill="#1f6feb"/>
        <text x="487" y="61" fill="#fff" font-size="10" font-family="sans-serif" text-anchor="middle">Active</text>
        <!-- Reorder badge callout -->
        <rect x="535" y="48" width="68" height="18" rx="9" fill="#d29922"/>
        <text x="569" y="61" fill="#fff" font-size="10" font-family="sans-serif" text-anchor="middle">↩ Reorder</text>
        <!-- Row 2 -->
        <rect x="0" y="76" width="700" height="40" fill="#161b22" stroke="#21262d" stroke-width="0.5"/>
        <text x="16" y="100" fill="#e6edf3" font-size="12" font-family="sans-serif">Rack A Server 1</text>
        <text x="200" y="100" fill="#79c0ff" font-size="11" font-family="sans-serif">Server</text>
        <text x="320" y="100" fill="#8b949e" font-size="11" font-family="monospace">192.168.1.10</text>
        <rect x="460" y="88" width="54" height="18" rx="9" fill="#1f6feb"/>
        <text x="487" y="101" fill="#fff" font-size="10" font-family="sans-serif" text-anchor="middle">Active</text>
        <!-- Row 3 -->
        <rect x="0" y="116" width="700" height="40" fill="#0d1117" stroke="#21262d" stroke-width="0.5"/>
        <text x="16" y="140" fill="#e6edf3" font-size="12" font-family="sans-serif">Patch Panel A</text>
        <text x="200" y="140" fill="#79c0ff" font-size="11" font-family="sans-serif">Patch Panel</text>
        <text x="320" y="140" fill="#8b949e" font-size="11" font-family="sans-serif">–</text>
        <rect x="460" y="128" width="68" height="18" rx="9" fill="#21262d"/>
        <text x="494" y="141" fill="#8b949e" font-size="10" font-family="sans-serif" text-anchor="middle">Inactive</text>
        <!-- Annotation: Reorder badge -->
        <line x1="569" y1="48" x2="620" y2="20" stroke="#f0b429" stroke-width="1.5" stroke-dasharray="4,2"/>
        <rect x="600" y="4" width="96" height="20" rx="10" fill="#f0b42966"/>
        <text x="648" y="18" fill="#f0b429" font-size="10" font-family="sans-serif" text-anchor="middle">Reorder flag</text>
      </svg>
      <p class="help-screenshot-caption">Asset list showing the yellow <strong>↩ Reorder</strong> badge on flagged assets. Use the filter bar to show only assets needing reorder.</p>
    </div>

    <h5 class="mt-4" id="network-management"><i class="fas fa-network-wired"></i> Network Management</h5>
    <ul>
        <li><strong>IP Address Management:</strong> Track IPs, subnets, VLANs</li>
        <li><strong>MAC Addresses:</strong> Record network interface details</li>
        <li><strong>Network Diagrams:</strong> Create visual network topology maps</li>
        <li><strong>Port Assignments:</strong> Track switch ports and patch panel connections</li>
    </ul>

    <h5 class="mt-4" id="rack-management"><i class="fas fa-warehouse"></i> Rack Management</h5>
    <ul>
        <li><strong>Data Centers:</strong> Organize assets by locations and data centers</li>
        <li><strong>Racks:</strong> Visual rack layout with U-space allocation</li>
        <li><strong>Drag &amp; Drop:</strong> Easily move devices between rack positions</li>
        <li><strong>Power Management:</strong> Track power consumption and capacity</li>
        <li><strong>Environmental Monitoring:</strong> Record temperature, humidity, and conditions</li>
    </ul>

    <div class="help-screenshot mt-3 mb-4">
      <svg viewBox="0 0 700 280" xmlns="http://www.w3.org/2000/svg" class="help-svg-screenshot">
        <rect width="700" height="280" rx="6" fill="#1a1f2e" stroke="#30363d"/>
        <!-- Rack cabinet frame -->
        <rect x="60" y="20" width="200" height="240" rx="4" fill="#0d1117" stroke="#444c56" stroke-width="2"/>
        <text x="160" y="14" fill="#8b949e" font-size="10" font-family="sans-serif" text-anchor="middle">Rack A — 42U</text>
        <!-- U number ruler -->
        <rect x="60" y="20" width="22" height="240" fill="#161b22" stroke="#30363d"/>
        <!-- U rows — filled devices -->
        <!-- 1U patch panel at top -->
        <rect x="82" y="28" width="174" height="14" rx="2" fill="#2d333b" stroke="#444c56"/>
        <text x="90" y="39" fill="#8b949e" font-size="8" font-family="monospace">1U</text>
        <text x="170" y="39" fill="#6e7681" font-size="8" font-family="sans-serif" text-anchor="middle">Patch Panel A</text>
        <!-- 1U switch -->
        <rect x="82" y="44" width="174" height="14" rx="2" fill="#1f3a5f" stroke="#1f6feb"/>
        <text x="90" y="55" fill="#58a6ff" font-size="8" font-family="monospace">2U</text>
        <text x="170" y="55" fill="#79c0ff" font-size="8" font-family="sans-serif" text-anchor="middle">Core Switch</text>
        <!-- 2U server -->
        <rect x="82" y="60" width="174" height="28" rx="2" fill="#1a3a2a" stroke="#3fb950"/>
        <text x="90" y="71" fill="#56d364" font-size="8" font-family="monospace">3U</text>
        <text x="170" y="74" fill="#3fb950" font-size="8" font-family="sans-serif" text-anchor="middle">Server A (2U)</text>
        <circle cx="238" cy="74" r="3" fill="#3fb950"/>
        <!-- 1U blank -->
        <rect x="82" y="90" width="174" height="14" rx="2" fill="#161b22" stroke="#30363d" stroke-dasharray="2,2"/>
        <text x="90" y="101" fill="#3d444d" font-size="8" font-family="monospace">5U</text>
        <text x="170" y="101" fill="#3d444d" font-size="8" font-family="sans-serif" text-anchor="middle">— empty —</text>
        <!-- 4U storage -->
        <rect x="82" y="106" width="174" height="56" rx="2" fill="#2d1f3f" stroke="#8957e5"/>
        <text x="90" y="117" fill="#bc8cff" font-size="8" font-family="monospace">6U</text>
        <text x="170" y="134" fill="#bc8cff" font-size="8" font-family="sans-serif" text-anchor="middle">NAS Storage (4U)</text>
        <!-- UPS at bottom -->
        <rect x="82" y="220" width="174" height="28" rx="2" fill="#3a2a1a" stroke="#e3b341"/>
        <text x="90" y="231" fill="#e3b341" font-size="8" font-family="monospace">38U</text>
        <text x="170" y="234" fill="#e3b341" font-size="8" font-family="sans-serif" text-anchor="middle">UPS (2U)</text>

        <!-- Legend / info panel -->
        <rect x="300" y="20" width="380" height="240" rx="4" fill="#161b22" stroke="#30363d"/>
        <text x="316" y="38" fill="#e6edf3" font-size="12" font-weight="bold" font-family="sans-serif">Rack A Details</text>
        <line x1="316" y1="44" x2="664" y2="44" stroke="#30363d"/>
        <!-- Stats -->
        <text x="316" y="62" fill="#8b949e" font-size="10" font-family="sans-serif">Location</text>
        <text x="460" y="62" fill="#e6edf3" font-size="10" font-family="sans-serif">Server Room 1, Rack Row B</text>
        <text x="316" y="80" fill="#8b949e" font-size="10" font-family="sans-serif">Total U</text>
        <text x="460" y="80" fill="#e6edf3" font-size="10" font-family="sans-serif">42U</text>
        <text x="316" y="98" fill="#8b949e" font-size="10" font-family="sans-serif">Used U</text>
        <text x="460" y="98" fill="#e6edf3" font-size="10" font-family="sans-serif">12U</text>
        <text x="316" y="116" fill="#8b949e" font-size="10" font-family="sans-serif">Free U</text>
        <text x="460" y="116" fill="#3fb950" font-size="10" font-family="sans-serif">30U available</text>
        <text x="316" y="134" fill="#8b949e" font-size="10" font-family="sans-serif">Power Draw</text>
        <text x="460" y="134" fill="#e6edf3" font-size="10" font-family="sans-serif">1.4 kW / 4.0 kW cap</text>
        <!-- Power bar -->
        <rect x="460" y="140" width="160" height="8" rx="4" fill="#21262d"/>
        <rect x="460" y="140" width="56" height="8" rx="4" fill="#1f6feb"/>
        <text x="316" y="165" fill="#8b949e" font-size="10" font-family="sans-serif">Temperature</text>
        <text x="460" y="165" fill="#3fb950" font-size="10" font-family="sans-serif">22°C ✓</text>
        <!-- Device list -->
        <text x="316" y="188" fill="#8b949e" font-size="10" font-family="sans-serif">Assets in rack:</text>
        <rect x="316" y="194" width="8" height="8" rx="1" fill="#1f6feb"/>
        <text x="330" y="202" fill="#c9d1d9" font-size="10" font-family="sans-serif">Core Switch</text>
        <rect x="316" y="208" width="8" height="8" rx="1" fill="#3fb950"/>
        <text x="330" y="216" fill="#c9d1d9" font-size="10" font-family="sans-serif">Server A</text>
        <rect x="316" y="222" width="8" height="8" rx="1" fill="#8957e5"/>
        <text x="330" y="230" fill="#c9d1d9" font-size="10" font-family="sans-serif">NAS Storage</text>
        <rect x="316" y="236" width="8" height="8" rx="1" fill="#e3b341"/>
        <text x="330" y="244" fill="#c9d1d9" font-size="10" font-family="sans-serif">UPS</text>
        <!-- Annotation -->
        <line x1="256" y1="74" x2="296" y2="74" stroke="#3fb950" stroke-width="1.5" stroke-dasharray="3,2"/>
        <rect x="258" y="66" width="40" height="16" rx="8" fill="#1a7f3744"/>
        <text x="278" y="77" fill="#3fb950" font-size="9" font-family="sans-serif" text-anchor="middle">Online</text>
      </svg>
      <p class="help-screenshot-caption">Visual rack layout showing U-space allocation, power consumption bar, and environmental data. Drag devices between U positions to reorganize.</p>
    </div>

    <h5 class="mt-4" id="port-configuration"><i class="fas fa-ethernet"></i> Port Configuration</h5>
    <p>Switches and patch panels support per-port configuration with VLAN management.</p>
    <ul>
        <li><strong>Switch ports:</strong> Set mode (Access / Trunk / Hybrid), native VLAN, tagged VLANs, speed, and status</li>
        <li><strong>Patch panel ports:</strong> Set label, destination cable, cable type, VLAN, and status</li>
        <li><strong>Bulk edit:</strong> Configure all ports in one screen — changes saved in a single click</li>
    </ul>

    <div class="help-screenshot mt-3 mb-4">
      <svg viewBox="0 0 700 160" xmlns="http://www.w3.org/2000/svg" class="help-svg-screenshot">
        <rect width="700" height="160" rx="6" fill="#1a1f2e" stroke="#30363d"/>
        <!-- Header row -->
        <rect x="0" y="0" width="700" height="32" rx="6" fill="#161b22" stroke="#30363d"/>
        <rect x="0" y="18" width="700" height="14" fill="#161b22"/>
        <text x="16" y="21" fill="#8b949e" font-size="10" font-family="monospace">Port #</text>
        <text x="80" y="21" fill="#8b949e" font-size="10" font-family="monospace">Description</text>
        <text x="240" y="21" fill="#8b949e" font-size="10" font-family="monospace">Mode</text>
        <text x="330" y="21" fill="#8b949e" font-size="10" font-family="monospace">Native VLAN</text>
        <text x="460" y="21" fill="#8b949e" font-size="10" font-family="monospace">Tagged VLANs</text>
        <text x="590" y="21" fill="#8b949e" font-size="10" font-family="monospace">Status</text>
        <!-- Port row -->
        <rect x="0" y="32" width="700" height="38" fill="#0d1117" stroke="#21262d" stroke-width="0.5"/>
        <text x="22" y="55" fill="#e6edf3" font-size="12" font-weight="bold" font-family="sans-serif" text-anchor="middle">1</text>
        <rect x="80" y="38" width="150" height="22" rx="3" fill="#21262d" stroke="#30363d"/>
        <text x="88" y="53" fill="#8b949e" font-size="10" font-family="sans-serif">Uplink to Core</text>
        <!-- Mode select -->
        <rect x="240" y="38" width="80" height="22" rx="3" fill="#21262d" stroke="#30363d"/>
        <text x="250" y="53" fill="#e6edf3" font-size="10" font-family="sans-serif">Trunk ▾</text>
        <!-- Native VLAN -->
        <rect x="330" y="38" width="120" height="22" rx="3" fill="#21262d" stroke="#30363d"/>
        <text x="340" y="53" fill="#e6edf3" font-size="10" font-family="sans-serif">VLAN 1 - Default ▾</text>
        <!-- Tagged -->
        <rect x="460" y="38" width="120" height="22" rx="3" fill="#21262d" stroke="#30363d"/>
        <text x="470" y="53" fill="#e6edf3" font-size="10" font-family="sans-serif">10, 20, 30 ▾</text>
        <!-- Status -->
        <rect x="590" y="38" width="80" height="22" rx="3" fill="#21262d" stroke="#30363d"/>
        <text x="600" y="53" fill="#3fb950" font-size="10" font-family="sans-serif">Active ▾</text>
        <!-- Port row 2 -->
        <rect x="0" y="70" width="700" height="38" fill="#161b22" stroke="#21262d" stroke-width="0.5"/>
        <text x="22" y="93" fill="#e6edf3" font-size="12" font-weight="bold" font-family="sans-serif" text-anchor="middle">2</text>
        <rect x="80" y="76" width="150" height="22" rx="3" fill="#21262d" stroke="#30363d"/>
        <text x="88" y="91" fill="#8b949e" font-size="10" font-family="sans-serif">Workstation A</text>
        <rect x="240" y="76" width="80" height="22" rx="3" fill="#21262d" stroke="#30363d"/>
        <text x="250" y="91" fill="#e6edf3" font-size="10" font-family="sans-serif">Access ▾</text>
        <rect x="330" y="76" width="120" height="22" rx="3" fill="#21262d" stroke="#30363d"/>
        <text x="340" y="91" fill="#e6edf3" font-size="10" font-family="sans-serif">VLAN 10 - Staff ▾</text>
        <rect x="460" y="76" width="120" height="22" rx="3" fill="#21262d" stroke="#30363d" opacity="0.4"/>
        <text x="470" y="91" fill="#555" font-size="10" font-family="sans-serif">(disabled)</text>
        <rect x="590" y="76" width="80" height="22" rx="3" fill="#21262d" stroke="#30363d"/>
        <text x="600" y="91" fill="#3fb950" font-size="10" font-family="sans-serif">Active ▾</text>
        <!-- Annotations -->
        <line x1="280" y1="38" x2="280" y2="14" stroke="#79c0ff" stroke-width="1.5" stroke-dasharray="3,2"/>
        <rect x="220" y="2" width="120" height="16" rx="8" fill="#1f6feb44"/>
        <text x="280" y="13" fill="#79c0ff" font-size="10" font-family="sans-serif" text-anchor="middle">Mode controls VLANs</text>
        <line x1="500" y1="108" x2="500" y2="138" stroke="#f0b429" stroke-width="1.5" stroke-dasharray="3,2"/>
        <rect x="420" y="138" width="160" height="16" rx="8" fill="#f0b42944"/>
        <text x="500" y="149" fill="#f0b429" font-size="10" font-family="sans-serif" text-anchor="middle">Disabled in Access mode</text>
      </svg>
      <p class="help-screenshot-caption">Port configuration table. <strong>Mode</strong> controls which VLAN fields are active — Tagged VLANs are disabled in Access mode.</p>
    </div>

    <h5 class="mt-4" id="asset-categories"><i class="fas fa-list"></i> Asset Categories</h5>
    <p>Supported asset types include:</p>
    <div class="row">
        <div class="col-md-6">
            <ul>
                <li>Servers &amp; Virtual Machines</li>
                <li>Network Equipment (switches, routers, firewalls)</li>
                <li>Storage Devices (NAS, SAN)</li>
                <li>Workstations &amp; Laptops</li>
            </ul>
        </div>
        <div class="col-md-6">
            <ul>
                <li>Mobile Devices (phones, tablets)</li>
                <li>Printers &amp; Peripherals</li>
                <li>Security Equipment (cameras, access control)</li>
                <li>Power Distribution (UPS, PDU)</li>
            </ul>
        </div>
    </div>

    <h5 class="mt-4" id="reporting"><i class="fas fa-chart-line"></i> Reporting &amp; Analytics</h5>
    <ul>
        <li><strong>Asset Reports:</strong> Generate reports on inventory, warranties, and costs</li>
        <li><strong>Export Options:</strong> Export data to CSV, PDF, or Excel</li>
        <li><strong>Depreciation Tracking:</strong> Monitor asset value over time</li>
        <li><strong>Warranty Alerts:</strong> Get notified before warranties expire</li>
    </ul>
    """
    return render(request, 'core/help/section.html', {
        'title': 'Asset Management',
        'section_id': 'assets',
        'toc': toc,
        'content': content,
        'prev_section': {'title': 'Getting Started', 'url_name': 'core:help_getting_started'},
        'next_section': {'title': 'Service Vehicles', 'url_name': 'core:help_vehicles'},
    })


@login_required
def help_vehicles(request):
    """Service vehicles help"""
    toc = [
        {'anchor': 'vehicle-tracking', 'heading': 'Vehicle Tracking'},
        {'anchor': 'insurance', 'heading': 'Insurance & Registration'},
        {'anchor': 'maintenance', 'heading': 'Maintenance Management'},
        {'anchor': 'fuel', 'heading': 'Fuel Tracking'},
        {'anchor': 'damage', 'heading': 'Damage Reporting'},
        {'anchor': 'vehicle-inventory', 'heading': 'Vehicle Inventory'},
        {'anchor': 'assignments', 'heading': 'User Assignments'},
    ]
    content = """
    <h4>Service Vehicle Fleet Management</h4>
    <p class="lead">Comprehensive fleet management for service vehicles with mileage tracking, maintenance scheduling, and inventory management.</p>

    <h5 class="mt-4" id="vehicle-tracking"><i class="fas fa-truck"></i> Vehicle Tracking</h5>
    <ul>
        <li><strong>Vehicle Information:</strong> Track make, model, year, VIN, license plate</li>
        <li><strong>Mileage Tracking:</strong> Automatic odometer updates from fuel logs</li>
        <li><strong>Vehicle Status:</strong> Monitor active, maintenance, or retired status</li>
        <li><strong>Condition Tracking:</strong> Rate condition from excellent to needs repair</li>
        <li><strong>GPS Location:</strong> Store current vehicle coordinates (lat/long)</li>
        <li><strong>User Assignments:</strong> Track who's using each vehicle</li>
    </ul>

    <h5 class="mt-4" id="insurance"><i class="fas fa-shield-alt"></i> Insurance &amp; Registration</h5>
    <ul>
        <li><strong>Insurance Tracking:</strong> Policy number, provider, expiration dates</li>
        <li><strong>Premium Management:</strong> Track insurance costs</li>
        <li><strong>Registration Expiry:</strong> Monitor registration renewal dates</li>
        <li><strong>Expiration Alerts:</strong> Get notified 30 days before expiration</li>
    </ul>

    <h5 class="mt-4" id="maintenance"><i class="fas fa-wrench"></i> Maintenance Management</h5>
    <ul>
        <li><strong>Service History:</strong> Complete maintenance and repair logs</li>
        <li><strong>Scheduled Maintenance:</strong> Oil changes, tire rotations, inspections</li>
        <li><strong>Cost Tracking:</strong> Labor and parts costs for each service</li>
        <li><strong>Next Due:</strong> Track next service by mileage or date</li>
        <li><strong>Overdue Detection:</strong> Automatic alerts for overdue maintenance</li>
        <li><strong>Service Providers:</strong> Record mechanics and service centers</li>
    </ul>

    <div class="help-screenshot mt-3 mb-4">
      <svg viewBox="0 0 700 220" xmlns="http://www.w3.org/2000/svg" class="help-svg-screenshot">
        <rect width="700" height="220" rx="6" fill="#1a1f2e" stroke="#30363d"/>
        <!-- Header -->
        <rect width="700" height="36" rx="6" fill="#161b22" stroke="#30363d"/>
        <rect y="18" width="700" height="18" fill="#161b22"/>
        <text x="16" y="22" fill="#e6edf3" font-size="12" font-weight="bold" font-family="sans-serif">Service History — Van 01 (Ford Transit 2022)</text>
        <rect x="580" y="8" width="106" height="22" rx="4" fill="#1f6feb"/>
        <text x="633" y="23" fill="#fff" font-size="10" font-family="sans-serif" text-anchor="middle">+ Log Service</text>
        <!-- Column headers -->
        <rect y="36" width="700" height="24" fill="#161b22" stroke="#21262d" stroke-width="0.5"/>
        <text x="16" y="52" fill="#8b949e" font-size="10" font-family="monospace">Date</text>
        <text x="110" y="52" fill="#8b949e" font-size="10" font-family="monospace">Service Type</text>
        <text x="280" y="52" fill="#8b949e" font-size="10" font-family="monospace">Mileage</text>
        <text x="370" y="52" fill="#8b949e" font-size="10" font-family="monospace">Cost</text>
        <text x="450" y="52" fill="#8b949e" font-size="10" font-family="monospace">Provider</text>
        <text x="590" y="52" fill="#8b949e" font-size="10" font-family="monospace">Next Due</text>
        <!-- Row 1 — overdue -->
        <rect y="60" width="700" height="36" fill="#3a1a1a" stroke="#5a2a2a" stroke-width="0.5"/>
        <text x="16" y="80" fill="#f85149" font-size="11" font-family="sans-serif">Jan 10</text>
        <text x="110" y="80" fill="#e6edf3" font-size="11" font-family="sans-serif">Oil Change</text>
        <text x="280" y="80" fill="#c9d1d9" font-size="11" font-family="monospace">48,320 mi</text>
        <text x="370" y="80" fill="#e6edf3" font-size="11" font-family="sans-serif">$89.00</text>
        <text x="450" y="80" fill="#8b949e" font-size="11" font-family="sans-serif">Quick Lube Plus</text>
        <rect x="586" y="68" width="100" height="18" rx="9" fill="#da363344"/>
        <text x="636" y="81" fill="#f85149" font-size="10" font-family="sans-serif" text-anchor="middle">⚠ Overdue 2k mi</text>
        <!-- Row 2 — ok -->
        <rect y="96" width="700" height="36" fill="#0d1117" stroke="#21262d" stroke-width="0.5"/>
        <text x="16" y="116" fill="#e6edf3" font-size="11" font-family="sans-serif">Dec 5</text>
        <text x="110" y="116" fill="#e6edf3" font-size="11" font-family="sans-serif">Tire Rotation</text>
        <text x="280" y="116" fill="#c9d1d9" font-size="11" font-family="monospace">46,100 mi</text>
        <text x="370" y="116" fill="#e6edf3" font-size="11" font-family="sans-serif">$45.00</text>
        <text x="450" y="116" fill="#8b949e" font-size="11" font-family="sans-serif">Bob's Garage</text>
        <rect x="590" y="104" width="90" height="18" rx="9" fill="#1a7f3744"/>
        <text x="635" y="117" fill="#3fb950" font-size="10" font-family="sans-serif" text-anchor="middle">Due in 6k mi</text>
        <!-- Row 3 — inspection -->
        <rect y="132" width="700" height="36" fill="#161b22" stroke="#21262d" stroke-width="0.5"/>
        <text x="16" y="152" fill="#e6edf3" font-size="11" font-family="sans-serif">Nov 20</text>
        <text x="110" y="152" fill="#e6edf3" font-size="11" font-family="sans-serif">Annual Inspection</text>
        <text x="280" y="152" fill="#c9d1d9" font-size="11" font-family="monospace">44,800 mi</text>
        <text x="370" y="152" fill="#e6edf3" font-size="11" font-family="sans-serif">$210.00</text>
        <text x="450" y="152" fill="#8b949e" font-size="11" font-family="sans-serif">State DMV</text>
        <rect x="590" y="140" width="90" height="18" rx="9" fill="#1a7f3744"/>
        <text x="635" y="153" fill="#3fb950" font-size="10" font-family="sans-serif" text-anchor="middle">Due Nov 2026</text>
        <!-- Total cost summary -->
        <rect y="168" width="700" height="52" fill="#0d1117" stroke="#30363d"/>
        <text x="16" y="190" fill="#8b949e" font-size="10" font-family="sans-serif">Total this year: <tspan fill="#e6edf3">$1,248.00</tspan>   |   Avg cost/service: <tspan fill="#e6edf3">$156.00</tspan>   |   Services logged: <tspan fill="#e6edf3">8</tspan></text>
        <text x="16" y="208" fill="#f85149" font-size="10" font-family="sans-serif">⚠ 1 service overdue — oil change was due at 50,320 mi (current: 52,200 mi)</text>
        <!-- Annotation -->
        <line x1="636" y1="68" x2="636" y2="46" stroke="#f85149" stroke-width="1.5" stroke-dasharray="3,2"/>
        <rect x="576" y="36" width="120" height="0" fill="transparent"/>
      </svg>
      <p class="help-screenshot-caption">Maintenance service history log. Overdue services are highlighted in red — the row turns red when mileage or date has passed the scheduled next-due point.</p>
    </div>

    <h5 class="mt-4" id="fuel"><i class="fas fa-gas-pump"></i> Fuel Tracking</h5>
    <ul>
        <li><strong>Fuel Logs:</strong> Record every fill-up with gallons and cost</li>
        <li><strong>MPG Calculation:</strong> Automatic miles-per-gallon tracking</li>
        <li><strong>Cost Analysis:</strong> Track fuel expenses per vehicle</li>
        <li><strong>Station Locations:</strong> Record where fuel was purchased</li>
        <li><strong>Trend Analysis:</strong> Monitor fuel efficiency over time</li>
    </ul>

    <div class="help-screenshot mt-3 mb-4">
      <svg viewBox="0 0 700 180" xmlns="http://www.w3.org/2000/svg" class="help-svg-screenshot">
        <rect width="700" height="180" rx="6" fill="#1a1f2e" stroke="#30363d"/>
        <!-- Stat cards row -->
        <rect x="12" y="12" width="155" height="60" rx="4" fill="#161b22" stroke="#30363d"/>
        <text x="28" y="32" fill="#8b949e" font-size="10" font-family="sans-serif">Avg MPG (30 days)</text>
        <text x="28" y="58" fill="#3fb950" font-size="26" font-weight="bold" font-family="sans-serif">22.4</text>

        <rect x="180" y="12" width="155" height="60" rx="4" fill="#161b22" stroke="#30363d"/>
        <text x="196" y="32" fill="#8b949e" font-size="10" font-family="sans-serif">Fuel Cost (month)</text>
        <text x="196" y="58" fill="#e6edf3" font-size="26" font-weight="bold" font-family="sans-serif">$284</text>

        <rect x="348" y="12" width="155" height="60" rx="4" fill="#161b22" stroke="#30363d"/>
        <text x="364" y="32" fill="#8b949e" font-size="10" font-family="sans-serif">Total Gallons</text>
        <text x="364" y="58" fill="#e6edf3" font-size="26" font-weight="bold" font-family="sans-serif">68.2</text>

        <rect x="516" y="12" width="172" height="60" rx="4" fill="#161b22" stroke="#30363d"/>
        <text x="532" y="32" fill="#8b949e" font-size="10" font-family="sans-serif">Fill-ups (month)</text>
        <text x="532" y="58" fill="#e6edf3" font-size="26" font-weight="bold" font-family="sans-serif">6</text>

        <!-- MPG trend chart -->
        <rect x="12" y="84" width="676" height="84" rx="4" fill="#161b22" stroke="#30363d"/>
        <text x="28" y="100" fill="#8b949e" font-size="10" font-family="sans-serif">MPG Trend (last 8 fill-ups)</text>
        <!-- Chart axes -->
        <line x1="50" y1="106" x2="50" y2="158" stroke="#30363d" stroke-width="1"/>
        <line x1="50" y1="158" x2="670" y2="158" stroke="#30363d" stroke-width="1"/>
        <!-- Y labels -->
        <text x="40" y="115" fill="#8b949e" font-size="8" font-family="monospace" text-anchor="end">25</text>
        <text x="40" y="135" fill="#8b949e" font-size="8" font-family="monospace" text-anchor="end">20</text>
        <text x="40" y="155" fill="#8b949e" font-size="8" font-family="monospace" text-anchor="end">15</text>
        <!-- Data points — MPG values mapped to y: 25mpg=y108, 20mpg=y128, 15mpg=y148 -->
        <!-- x positions: 75, 150, 225, 300, 375, 450, 525, 600 -->
        <polyline points="75,132 150,126 225,136 300,120 375,118 450,124 525,116 600,110"
                  fill="none" stroke="#1f6feb" stroke-width="2"/>
        <polyline points="75,132 150,126 225,136 300,120 375,118 450,124 525,116 600,110"
                  fill="url(#mpg-fill)" stroke="none" opacity="0.2"/>
        <!-- Data dots -->
        <circle cx="75" cy="132" r="3" fill="#58a6ff"/>
        <circle cx="150" cy="126" r="3" fill="#58a6ff"/>
        <circle cx="225" cy="136" r="3" fill="#58a6ff"/>
        <circle cx="300" cy="120" r="3" fill="#58a6ff"/>
        <circle cx="375" cy="118" r="3" fill="#58a6ff"/>
        <circle cx="450" cy="124" r="3" fill="#58a6ff"/>
        <circle cx="525" cy="116" r="3" fill="#58a6ff"/>
        <circle cx="600" cy="110" r="4" fill="#3fb950" stroke="#56d364" stroke-width="1.5"/>
        <text x="612" y="107" fill="#3fb950" font-size="9" font-family="monospace">22.4</text>
      </svg>
      <p class="help-screenshot-caption">Fuel tracking dashboard showing average MPG, monthly cost, and an MPG trend chart. MPG is auto-calculated from each fill-up's mileage delta ÷ gallons.</p>
    </div>

    <h5 class="mt-4" id="damage"><i class="fas fa-car-crash"></i> Damage Reporting</h5>
    <ul>
        <li><strong>Incident Reports:</strong> Document damage with photos and descriptions</li>
        <li><strong>Severity Levels:</strong> Minor, moderate, major, or total loss</li>
        <li><strong>Repair Tracking:</strong> Monitor repair status from reported to completed</li>
        <li><strong>Cost Estimates:</strong> Track estimated and actual repair costs</li>
        <li><strong>Insurance Claims:</strong> Claim numbers and payout tracking</li>
        <li><strong>Photo Attachments:</strong> Upload damage photos for documentation</li>
        <li><strong>Side Diagrams:</strong> Click damage areas on the interactive vehicle diagram (driver and passenger sides)</li>
    </ul>

    <h5 class="mt-4" id="vehicle-inventory"><i class="fas fa-boxes"></i> Vehicle Inventory</h5>
    <ul>
        <li><strong>Equipment Tracking:</strong> Cables, connectors, hardware, tools</li>
        <li><strong>Quantity Management:</strong> Track item quantities and units</li>
        <li><strong>Low Stock Alerts:</strong> Get notified when inventory runs low</li>
        <li><strong>Value Tracking:</strong> Monitor total inventory value per vehicle</li>
        <li><strong>Categories:</strong> Organize by cables, tools, hardware, supplies</li>
        <li><strong>Storage Locations:</strong> Note where items are stored in vehicle</li>
    </ul>

    <h5 class="mt-4" id="assignments"><i class="fas fa-user-check"></i> User Assignments</h5>
    <ul>
        <li><strong>Assignment History:</strong> Track who used each vehicle and when</li>
        <li><strong>Mileage Records:</strong> Starting and ending mileage per assignment</li>
        <li><strong>Duration Tracking:</strong> Calculate how long each assignment lasted</li>
        <li><strong>Active Assignments:</strong> See current vehicle assignments</li>
    </ul>
    """
    return render(request, 'core/help/section.html', {
        'title': 'Service Vehicles',
        'section_id': 'vehicles',
        'toc': toc,
        'content': content,
        'prev_section': {'title': 'Asset Management', 'url_name': 'core:help_assets'},
        'next_section': {'title': 'Password Vault', 'url_name': 'core:help_vault'},
    })


@login_required
def help_vault(request):
    """Password vault help"""
    toc = [
        {'anchor': 'security-features', 'heading': 'Security Features'},
        {'anchor': 'breach-detection', 'heading': 'Breach Detection'},
        {'anchor': 'password-management', 'heading': 'Password Management'},
        {'anchor': 'password-generator', 'heading': 'Password Generator'},
        {'anchor': 'totp', 'heading': 'TOTP / Two-Factor Auth'},
        {'anchor': 'sharing', 'heading': 'Sharing & Collaboration'},
        {'anchor': 'import-export', 'heading': 'Import & Export'},
    ]
    content = """
    <h4>Password Vault</h4>
    <p class="lead">Securely store and manage credentials with AES-256 encryption, breach detection, and TOTP support.</p>

    <h5 class="mt-4" id="security-features"><i class="fas fa-lock"></i> Security Features</h5>
    <ul>
        <li><strong>AES-256 Encryption:</strong> Military-grade encryption for all stored passwords</li>
        <li><strong>Zero-Knowledge Architecture:</strong> Passwords encrypted at rest and in transit</li>
        <li><strong>Master Password:</strong> Organization-level encryption keys</li>
        <li><strong>Access Control:</strong> Role-based permissions for vault access</li>
        <li><strong>Audit Logging:</strong> Track every password access and modification</li>
    </ul>

    <h5 class="mt-4" id="breach-detection"><i class="fas fa-shield-alt"></i> Breach Detection</h5>
    <ul>
        <li><strong>Have I Been Pwned Integration:</strong> Check passwords against known breaches</li>
        <li><strong>Automatic Scanning:</strong> Regular checks for compromised credentials</li>
        <li><strong>Breach Alerts:</strong> Immediate notification if password found in breach</li>
        <li><strong>Security Score:</strong> Rate password strength and security</li>
        <li><strong>Reuse Detection:</strong> Identify duplicate passwords across accounts</li>
    </ul>

    <div class="help-screenshot mt-3 mb-4">
      <svg viewBox="0 0 700 170" xmlns="http://www.w3.org/2000/svg" class="help-svg-screenshot">
        <rect width="700" height="170" rx="6" fill="#1a1f2e" stroke="#30363d"/>
        <!-- Card -->
        <rect x="12" y="12" width="676" height="146" rx="6" fill="#161b22" stroke="#30363d"/>
        <!-- Title row -->
        <text x="28" y="38" fill="#e6edf3" font-size="14" font-weight="bold" font-family="sans-serif">company-server-root</text>
        <text x="28" y="54" fill="#8b949e" font-size="11" font-family="sans-serif">username: root   |   server.company.com</text>
        <!-- Breach badge -->
        <rect x="500" y="22" width="80" height="20" rx="10" fill="#da363344"/>
        <text x="540" y="36" fill="#f85149" font-size="10" font-family="sans-serif" text-anchor="middle">⚠ Breached</text>
        <!-- Password row -->
        <rect x="28" y="66" width="320" height="28" rx="4" fill="#0d1117" stroke="#30363d"/>
        <text x="44" y="84" fill="#8b949e" font-size="13" font-family="monospace" letter-spacing="4">••••••••••••</text>
        <!-- Reveal button -->
        <rect x="360" y="66" width="80" height="28" rx="4" fill="#21262d" stroke="#30363d"/>
        <text x="400" y="84" fill="#79c0ff" font-size="11" font-family="sans-serif" text-anchor="middle">👁 Reveal</text>
        <!-- Copy button -->
        <rect x="452" y="66" width="80" height="28" rx="4" fill="#21262d" stroke="#30363d"/>
        <text x="492" y="84" fill="#8b949e" font-size="11" font-family="sans-serif" text-anchor="middle">⧉ Copy</text>
        <!-- TOTP -->
        <rect x="28" y="106" width="150" height="28" rx="4" fill="#1f6feb22" stroke="#1f6feb66"/>
        <text x="44" y="124" fill="#79c0ff" font-size="13" font-family="monospace">⏱ 483 291</text>
        <text x="190" y="124" fill="#8b949e" font-size="10" font-family="sans-serif">expires in 18s</text>
        <!-- Annotations -->
        <line x1="540" y1="42" x2="580" y2="10" stroke="#f85149" stroke-width="1.5" stroke-dasharray="3,2"/>
        <rect x="560" y="1" width="130" height="14" rx="7" fill="#da363344"/>
        <text x="625" y="12" fill="#f85149" font-size="10" font-family="sans-serif" text-anchor="middle">HIBP breach alert</text>
        <line x1="400" y1="66" x2="400" y2="44" stroke="#79c0ff" stroke-width="1.5" stroke-dasharray="3,2"/>
        <rect x="340" y="34" width="120" height="14" rx="7" fill="#1f6feb44"/>
        <text x="400" y="44" fill="#79c0ff" font-size="10" font-family="sans-serif" text-anchor="middle">Reveal shows plaintext</text>
        <line x1="103" y1="134" x2="60" y2="156" stroke="#3fb950" stroke-width="1.5" stroke-dasharray="3,2"/>
        <rect x="10" y="152" width="120" height="14" rx="7" fill="#1a7f3744"/>
        <text x="70" y="163" fill="#3fb950" font-size="10" font-family="sans-serif" text-anchor="middle">Live TOTP counter</text>
      </svg>
      <p class="help-screenshot-caption">Password entry with breach detection badge, reveal-on-click password, copy button, and live TOTP counter.</p>
    </div>

    <h5 class="mt-4" id="password-management"><i class="fas fa-key"></i> Password Management</h5>
    <ul>
        <li><strong>Organized Storage:</strong> Group passwords by category, client, or service</li>
        <li><strong>Quick Search:</strong> Fast search across all credentials</li>
        <li><strong>Copy Protection:</strong> Secure clipboard with auto-clear</li>
        <li><strong>Show/Hide:</strong> Toggle password visibility</li>
        <li><strong>Notes &amp; URLs:</strong> Store additional context and login URLs</li>
        <li><strong>Tags &amp; Labels:</strong> Organize with custom tags</li>
    </ul>

    <h5 class="mt-4" id="password-generator"><i class="fas fa-random"></i> Password Generator</h5>
    <ul>
        <li><strong>Strong Passwords:</strong> Generate cryptographically secure passwords</li>
        <li><strong>Customizable:</strong> Set length, character types, and complexity</li>
        <li><strong>Pronounceable Options:</strong> Create memorable yet secure passwords</li>
        <li><strong>Passphrase Generator:</strong> Multi-word passphrases for better memorability</li>
    </ul>

    <h5 class="mt-4" id="totp"><i class="fas fa-mobile-alt"></i> TOTP / Two-Factor Auth</h5>
    <ul>
        <li><strong>TOTP Storage:</strong> Store TOTP secrets alongside credentials</li>
        <li><strong>Live Counter:</strong> View the current 6-digit code with countdown timer</li>
        <li><strong>QR Code Setup:</strong> Scan QR codes directly from authenticator apps</li>
        <li><strong>Browser Extension:</strong> TOTP codes auto-copied during autofill</li>
    </ul>

    <h5 class="mt-4" id="sharing"><i class="fas fa-users"></i> Sharing &amp; Collaboration</h5>
    <ul>
        <li><strong>Secure Sharing:</strong> Share credentials within organization</li>
        <li><strong>Access Control:</strong> Grant read-only or full access</li>
        <li><strong>Temporary Access:</strong> Time-limited credential sharing</li>
        <li><strong>Sharing History:</strong> Track who accessed shared passwords</li>
    </ul>

    <h5 class="mt-4" id="import-export"><i class="fas fa-download"></i> Import &amp; Export</h5>
    <ul>
        <li><strong>Import from CSV:</strong> Bulk import from other password managers</li>
        <li><strong>LastPass Import:</strong> Direct import from LastPass export</li>
        <li><strong>1Password Import:</strong> Import from 1Password exports</li>
        <li><strong>Secure Export:</strong> Export encrypted backups</li>
    </ul>
    """
    return render(request, 'core/help/section.html', {
        'title': 'Password Vault',
        'section_id': 'vault',
        'toc': toc,
        'content': content,
        'prev_section': {'title': 'Service Vehicles', 'url_name': 'core:help_vehicles'},
        'next_section': {'title': 'Monitoring', 'url_name': 'core:help_monitoring'},
    })


@login_required
def help_monitoring(request):
    """Monitoring help. Kept in step with user-guide/wan-monitoring.md."""
    toc = [
        {'anchor': 'overview', 'heading': 'Overview'},
        {'anchor': 'website-monitors', 'heading': 'Website Monitors'},
        {'anchor': 'alerting', 'heading': 'Alerting'},
        {'anchor': 'ssl-monitoring', 'heading': 'Certificate and Domain Expiry'},
        {'anchor': 'wan-checks', 'heading': 'WAN Connection Checks'},
        {'anchor': 'status-pages', 'heading': 'Status Pages and Incidents'},
    ]
    content = """
    <h4>Website &amp; WAN Monitoring</h4>
    <p class="lead">Checks run from the server outward; nothing is installed on what is being checked. Only website monitors run on a schedule and send alerts.</p>

    <h5 class="mt-4" id="overview"><i class="fas fa-wifi"></i> Overview</h5>
    <ul>
        <li><strong>Website monitors</strong> (<em>Monitoring &rarr; Website Monitors</em>): an <code>http://</code> or <code>https://</code> URL, checked on a schedule and on <strong>Check Now</strong>, with down and recovery alerts, certificate expiry emails, and a stored check history.</li>
        <li><strong>WAN connection checks</strong> (on a location's WAN connection): one ping to the WAN's monitor target, only when someone clicks <strong>Check Status</strong>. No schedule, no alerts.</li>
        <li>There are no TCP port, DNS or keyword-match checks.</li>
    </ul>

    <h5 class="mt-4" id="website-monitors"><i class="fas fa-globe"></i> Website Monitors</h5>
    <ul>
        <li><strong>Interval:</strong> set per monitor in minutes (default 60). The scheduler looks for due monitors every 5 minutes, so shorter intervals behave like 5.</li>
        <li><strong>The check:</strong> one <code>GET</code> with a 10-second timeout; redirects are not followed.</li>
        <li><strong>Status:</strong> 2xx is <strong>Active</strong>; a redirect is <strong>Warning</strong> (the site answered); any other code, a timeout, a connection error or an invalid certificate is <strong>Down</strong>. An address refused by the outbound-request guard (private networks unless <code>ALLOW_PRIVATE_IP_INTEGRATIONS=True</code>; cloud metadata always) is <strong>Error</strong>, which does not alert.</li>
        <li><strong>Certificates:</strong> for HTTPS the certificate is validated and its issuer, subject, serial, validity dates and TLS version are recorded.</li>
        <li><strong>History and uptime:</strong> every check is kept for 400 days. Uptime is the share of checks that were not Down, shown on status pages (30, 90 and 365 days), in the Monitor Uptime report (30 days) and in compliance evidence packs. A monitor with no checks in a window shows no figure.</li>
    </ul>

    <h5 class="mt-4" id="alerting"><i class="fas fa-bell"></i> Alerting</h5>
    <ul>
        <li><strong>Down:</strong> with <em>Notify on down</em> on, one email after 2 failed checks in a row (setting <code>WEBSITE_DOWN_ALERT_THRESHOLD</code>); further failures send nothing.</li>
        <li><strong>Recovery:</strong> one email on the first successful check after a down alert.</li>
        <li><strong>Recipients:</strong> active superusers and the admins and owners of the monitor's organization. Needs outgoing email under <em>Settings &rarr; SMTP/Email</em>.</li>
        <li><strong>Webhooks:</strong> organization webhooks can subscribe to <code>monitor.check_failed</code> (every failed check), <code>monitor.down</code> and <code>monitor.up</code> (once per transition). Plain JSON, signed when the webhook has a secret; no built-in Slack or Teams format.</li>
        <li>There are no escalation policies, alert grouping or per-monitor recipient lists.</li>
    </ul>

    <h5 class="mt-4" id="ssl-monitoring"><i class="fas fa-certificate"></i> Certificate and Domain Expiry</h5>
    <ul>
        <li><strong>Certificates:</strong> a daily job emails once when a certificate enters its warning window (the larger of the monitor's and the global setting) and once more when it expires. A renewed certificate starts over.</li>
        <li><strong>Domains:</strong> there is no WHOIS lookup. Enter domains on <em>Monitoring &rarr; Expirations</em>; the same daily job emails about them.</li>
    </ul>

    <h5 class="mt-4" id="wan-checks"><i class="fas fa-network-wired"></i> WAN Connection Checks</h5>
    <ul>
        <li>Turn on monitoring for the WAN connection and set a monitor target (IP or hostname).</li>
        <li><strong>Check Status</strong> sends one ping (2-second timeout) and records up or down, the response time and the last outage time. <em>Monitoring &rarr; WAN Connections</em> lists the results.</li>
        <li>WAN checks are not scheduled and send no alerts; the check interval and uptime fields are not used yet. For automatic alerts, add a website monitor for something that answers over HTTP or HTTPS through that connection.</li>
    </ul>

    <h5 class="mt-4" id="status-pages"><i class="fas fa-history"></i> Status Pages and Incidents</h5>
    <ul>
        <li>Status pages publish chosen website monitors under audience-friendly names, with current status and uptime.</li>
        <li>Incidents and maintenance windows are posted on a status page by hand, optionally linked to a ticket. Outages do not create incidents, and maintenance windows do not silence monitor alerts.</li>
    </ul>
    """
    return render(request, 'core/help/section.html', {
        'title': 'Website & WAN Monitoring',
        'section_id': 'monitoring',
        'toc': toc,
        'content': content,
        'prev_section': {'title': 'Password Vault', 'url_name': 'core:help_vault'},
        'next_section': {'title': 'Security', 'url_name': 'core:help_security'},
    })


@login_required
def help_security(request):
    """Security features help"""
    toc = [
        {'anchor': 'vulnerability-scanning', 'heading': 'Vulnerability Scanning'},
        {'anchor': 'authentication', 'heading': 'Authentication & Access Control'},
        {'anchor': 'rbac', 'heading': 'Role-Based Access Control'},
        {'anchor': 'audit-logging', 'heading': 'Audit Logging'},
        {'anchor': 'data-protection', 'heading': 'Data Protection'},
        {'anchor': 'security-alerts', 'heading': 'Security Alerts'},
    ]
    content = """
    <h4>Security Features</h4>
    <p class="lead">Comprehensive security tools including vulnerability scanning, breach detection, and audit logging.</p>

    <h5 class="mt-4" id="vulnerability-scanning"><i class="fas fa-shield-alt"></i> Vulnerability Scanning</h5>
    <ul>
        <li><strong>Python Package Scanner:</strong> Scan Python dependencies for known vulnerabilities</li>
        <li><strong>OS Package Scanner:</strong> Check system packages for security updates</li>
        <li><strong>CVE Database:</strong> Integration with Common Vulnerabilities and Exposures database</li>
        <li><strong>Severity Ratings:</strong> CRITICAL, HIGH, MEDIUM, LOW classifications</li>
        <li><strong>Automated Scans:</strong> Scheduled security checks (hourly, daily, weekly)</li>
        <li><strong>Fix Recommendations:</strong> Suggested remediation actions</li>
        <li><strong>Historical Tracking:</strong> Monitor vulnerability trends over time</li>
    </ul>

    <div class="help-screenshot mt-3 mb-4">
      <svg viewBox="0 0 700 220" xmlns="http://www.w3.org/2000/svg" class="help-svg-screenshot">
        <rect width="700" height="220" rx="6" fill="#1a1f2e" stroke="#30363d"/>
        <!-- Header -->
        <rect width="700" height="36" rx="6" fill="#161b22" stroke="#30363d"/>
        <rect y="18" width="700" height="18" fill="#161b22"/>
        <text x="16" y="25" fill="#e6edf3" font-size="12" font-weight="bold" font-family="sans-serif">Package Vulnerability Scan — Latest Results</text>
        <rect x="578" y="8" width="108" height="22" rx="4" fill="#1f6feb"/>
        <text x="632" y="23" fill="#fff" font-size="10" font-family="sans-serif" text-anchor="middle">▶ Run New Scan</text>
        <!-- Summary row -->
        <rect x="12" y="44" width="90" height="44" rx="4" fill="#3a1a1a" stroke="#f85149"/>
        <text x="57" y="62" fill="#f85149" font-size="20" font-weight="bold" font-family="sans-serif" text-anchor="middle">3</text>
        <text x="57" y="78" fill="#ff7b72" font-size="9" font-family="sans-serif" text-anchor="middle">CRITICAL</text>
        <rect x="112" y="44" width="90" height="44" rx="4" fill="#2d1f00" stroke="#e3b341"/>
        <text x="157" y="62" fill="#e3b341" font-size="20" font-weight="bold" font-family="sans-serif" text-anchor="middle">7</text>
        <text x="157" y="78" fill="#e3b341" font-size="9" font-family="sans-serif" text-anchor="middle">HIGH</text>
        <rect x="212" y="44" width="90" height="44" rx="4" fill="#1a1f2e" stroke="#d29922"/>
        <text x="257" y="62" fill="#d29922" font-size="20" font-weight="bold" font-family="sans-serif" text-anchor="middle">12</text>
        <text x="257" y="78" fill="#d29922" font-size="9" font-family="sans-serif" text-anchor="middle">MEDIUM</text>
        <rect x="312" y="44" width="90" height="44" rx="4" fill="#161b22" stroke="#30363d"/>
        <text x="357" y="62" fill="#8b949e" font-size="20" font-weight="bold" font-family="sans-serif" text-anchor="middle">5</text>
        <text x="357" y="78" fill="#8b949e" font-size="9" font-family="sans-serif" text-anchor="middle">LOW</text>
        <!-- Table -->
        <rect y="100" width="700" height="22" fill="#161b22" stroke="#21262d" stroke-width="0.5"/>
        <text x="16" y="115" fill="#8b949e" font-size="10" font-family="monospace">Package</text>
        <text x="180" y="115" fill="#8b949e" font-size="10" font-family="monospace">Installed</text>
        <text x="260" y="115" fill="#8b949e" font-size="10" font-family="monospace">CVE</text>
        <text x="380" y="115" fill="#8b949e" font-size="10" font-family="monospace">Severity</text>
        <text x="470" y="115" fill="#8b949e" font-size="10" font-family="monospace">Fix version</text>
        <text x="590" y="115" fill="#8b949e" font-size="10" font-family="monospace">Action</text>

        <!-- Row 1 - critical -->
        <rect y="122" width="700" height="28" fill="#1a0a0a" stroke="#4a1515" stroke-width="0.5"/>
        <text x="16" y="140" fill="#e6edf3" font-size="11" font-family="monospace">cryptography</text>
        <text x="180" y="140" fill="#8b949e" font-size="11" font-family="monospace">41.0.3</text>
        <text x="260" y="140" fill="#58a6ff" font-size="10" font-family="monospace">CVE-2024-0727</text>
        <rect x="378" y="128" width="64" height="16" rx="8" fill="#da3633"/>
        <text x="410" y="140" fill="#fff" font-size="10" font-family="sans-serif" text-anchor="middle">CRITICAL</text>
        <text x="470" y="140" fill="#3fb950" font-size="11" font-family="monospace">42.0.8</text>
        <rect x="590" y="128" width="80" height="16" rx="4" fill="#1f6feb"/>
        <text x="630" y="140" fill="#fff" font-size="10" font-family="sans-serif" text-anchor="middle">Auto-fix</text>

        <!-- Row 2 - high -->
        <rect y="150" width="700" height="28" fill="#1a1400" stroke="#3a3000" stroke-width="0.5"/>
        <text x="16" y="168" fill="#e6edf3" font-size="11" font-family="monospace">pillow</text>
        <text x="180" y="168" fill="#8b949e" font-size="11" font-family="monospace">10.0.1</text>
        <text x="260" y="168" fill="#58a6ff" font-size="10" font-family="monospace">CVE-2023-50447</text>
        <rect x="378" y="156" width="44" height="16" rx="8" fill="#9a6700"/>
        <text x="400" y="168" fill="#fff" font-size="10" font-family="sans-serif" text-anchor="middle">HIGH</text>
        <text x="470" y="168" fill="#3fb950" font-size="11" font-family="monospace">10.3.0</text>
        <rect x="590" y="156" width="80" height="16" rx="4" fill="#1f6feb"/>
        <text x="630" y="168" fill="#fff" font-size="10" font-family="sans-serif" text-anchor="middle">Auto-fix</text>

        <!-- Row 3 - medium -->
        <rect y="178" width="700" height="28" fill="#0d1117" stroke="#21262d" stroke-width="0.5"/>
        <text x="16" y="196" fill="#e6edf3" font-size="11" font-family="monospace">django</text>
        <text x="180" y="196" fill="#8b949e" font-size="11" font-family="monospace">4.2.8</text>
        <text x="260" y="196" fill="#58a6ff" font-size="10" font-family="monospace">CVE-2024-27351</text>
        <rect x="378" y="184" width="58" height="16" rx="8" fill="#6e4c00"/>
        <text x="407" y="196" fill="#e3b341" font-size="10" font-family="sans-serif" text-anchor="middle">MEDIUM</text>
        <text x="470" y="196" fill="#3fb950" font-size="11" font-family="monospace">4.2.14</text>
        <rect x="590" y="184" width="80" height="16" rx="4" fill="#1f6feb"/>
        <text x="630" y="196" fill="#fff" font-size="10" font-family="sans-serif" text-anchor="middle">Auto-fix</text>
      </svg>
      <p class="help-screenshot-caption">Vulnerability scanner results showing CVE IDs, severity levels, installed vs safe versions, and one-click auto-fix. Scans run on schedule or on-demand.</p>
    </div>

    <h5 class="mt-4" id="authentication"><i class="fas fa-user-shield"></i> Authentication &amp; Access Control</h5>
    <ul>
        <li><strong>Two-Factor Authentication (2FA):</strong> TOTP-based 2FA with QR code setup</li>
        <li><strong>Azure AD Integration:</strong> Single sign-on with Microsoft Azure AD</li>
        <li><strong>Password Policies:</strong> Enforce strong password requirements</li>
        <li><strong>Session Management:</strong> Automatic timeout and secure session handling</li>
        <li><strong>IP Whitelisting:</strong> Restrict access by IP address</li>
        <li><strong>Failed Login Detection:</strong> Account lockout after repeated failures</li>
    </ul>

    <h5 class="mt-4" id="rbac"><i class="fas fa-user-tag"></i> Role-Based Access Control (RBAC)</h5>
    <ul>
        <li><strong>42 Granular Permissions:</strong> Fine-grained control over features</li>
        <li><strong>Custom Roles:</strong> Create organization-specific roles</li>
        <li><strong>Role Templates:</strong> Owner, Admin, Editor, Read-Only presets</li>
        <li><strong>Permission Inheritance:</strong> Hierarchical role structures</li>
        <li><strong>Organization Scoping:</strong> Isolate data by organization</li>
    </ul>

    <h5 class="mt-4" id="audit-logging"><i class="fas fa-clipboard-list"></i> Audit Logging</h5>
    <ul>
        <li><strong>Comprehensive Logs:</strong> Every action logged with timestamp and user</li>
        <li><strong>Change Tracking:</strong> Before/after values for all modifications</li>
        <li><strong>Search &amp; Filter:</strong> Query logs by user, action, date, or resource</li>
        <li><strong>Export Logs:</strong> Download audit trails for compliance</li>
        <li><strong>Retention Policies:</strong> Configurable log retention periods</li>
        <li><strong>Immutable Records:</strong> Logs cannot be modified or deleted</li>
    </ul>

    <div class="help-screenshot mt-3 mb-4">
      <svg viewBox="0 0 700 190" xmlns="http://www.w3.org/2000/svg" class="help-svg-screenshot">
        <rect width="700" height="190" rx="6" fill="#1a1f2e" stroke="#30363d"/>
        <!-- Header -->
        <rect width="700" height="36" rx="6" fill="#161b22" stroke="#30363d"/>
        <rect y="18" width="700" height="18" fill="#161b22"/>
        <text x="16" y="25" fill="#e6edf3" font-size="12" font-weight="bold" font-family="sans-serif">Audit Log</text>
        <!-- Filter bar -->
        <rect x="12" y="44" width="140" height="22" rx="4" fill="#21262d" stroke="#30363d"/>
        <text x="20" y="59" fill="#8b949e" font-size="10" font-family="sans-serif">All users ▾</text>
        <rect x="162" y="44" width="120" height="22" rx="4" fill="#21262d" stroke="#30363d"/>
        <text x="170" y="59" fill="#8b949e" font-size="10" font-family="sans-serif">All actions ▾</text>
        <rect x="292" y="44" width="120" height="22" rx="4" fill="#21262d" stroke="#30363d"/>
        <text x="300" y="59" fill="#8b949e" font-size="10" font-family="sans-serif">Last 7 days ▾</text>
        <!-- Column headers -->
        <rect y="74" width="700" height="22" fill="#161b22" stroke="#21262d" stroke-width="0.5"/>
        <text x="16" y="89" fill="#8b949e" font-size="10" font-family="monospace">Time</text>
        <text x="110" y="89" fill="#8b949e" font-size="10" font-family="monospace">User</text>
        <text x="210" y="89" fill="#8b949e" font-size="10" font-family="monospace">Action</text>
        <text x="360" y="89" fill="#8b949e" font-size="10" font-family="monospace">Resource</text>
        <text x="530" y="89" fill="#8b949e" font-size="10" font-family="monospace">IP Address</text>
        <!-- Rows -->
        <rect y="96" width="700" height="28" fill="#0d1117" stroke="#21262d" stroke-width="0.5"/>
        <text x="16" y="114" fill="#8b949e" font-size="10" font-family="monospace">09:42:11</text>
        <text x="110" y="114" fill="#e6edf3" font-size="11" font-family="sans-serif">jsmith</text>
        <rect x="210" y="102" width="72" height="16" rx="8" fill="#1f6feb44"/>
        <text x="246" y="114" fill="#79c0ff" font-size="10" font-family="sans-serif" text-anchor="middle">password.view</text>
        <text x="360" y="114" fill="#c9d1d9" font-size="11" font-family="sans-serif">Vault: github-root</text>
        <text x="530" y="114" fill="#8b949e" font-size="10" font-family="monospace">10.0.1.5</text>

        <rect y="124" width="700" height="28" fill="#161b22" stroke="#21262d" stroke-width="0.5"/>
        <text x="16" y="142" fill="#8b949e" font-size="10" font-family="monospace">09:38:04</text>
        <text x="110" y="142" fill="#e6edf3" font-size="11" font-family="sans-serif">s.lee</text>
        <rect x="210" y="130" width="66" height="16" rx="8" fill="#1a7f3744"/>
        <text x="243" y="142" fill="#3fb950" font-size="10" font-family="sans-serif" text-anchor="middle">asset.create</text>
        <text x="360" y="142" fill="#c9d1d9" font-size="11" font-family="sans-serif">Asset: New NAS Unit</text>
        <text x="530" y="142" fill="#8b949e" font-size="10" font-family="monospace">10.0.1.12</text>

        <rect y="152" width="700" height="28" fill="#1a0d0d" stroke="#4a1515" stroke-width="0.5"/>
        <text x="16" y="170" fill="#8b949e" font-size="10" font-family="monospace">09:31:55</text>
        <text x="110" y="170" fill="#e6edf3" font-size="11" font-family="sans-serif">unknown</text>
        <rect x="210" y="158" width="80" height="16" rx="8" fill="#da363344"/>
        <text x="250" y="170" fill="#f85149" font-size="10" font-family="sans-serif" text-anchor="middle">login.failed</text>
        <text x="360" y="170" fill="#c9d1d9" font-size="11" font-family="sans-serif">User: admin (3rd attempt)</text>
        <text x="530" y="170" fill="#f85149" font-size="10" font-family="monospace">185.234.x.x</text>
        <!-- Annotation -->
        <line x1="250" y1="158" x2="300" y2="138" stroke="#f85149" stroke-width="1.5" stroke-dasharray="3,2"/>
        <rect x="282" y="128" width="130" height="14" rx="7" fill="#da363344"/>
        <text x="347" y="139" fill="#f85149" font-size="10" font-family="sans-serif" text-anchor="middle">Failed logins highlighted</text>
      </svg>
      <p class="help-screenshot-caption">Audit log showing every user action with timestamp, action type color-coded by category, resource affected, and source IP. Failed logins are highlighted in red.</p>
    </div>

    <h5 class="mt-4" id="data-protection"><i class="fas fa-lock"></i> Data Protection</h5>
    <ul>
        <li><strong>Encryption at Rest:</strong> Database encryption for sensitive data</li>
        <li><strong>Encryption in Transit:</strong> TLS 1.2+ for all connections</li>
        <li><strong>Secure File Storage:</strong> Encrypted file attachments</li>
        <li><strong>Backup Encryption:</strong> Encrypted database backups</li>
        <li><strong>GDPR Compliance:</strong> Data privacy and right-to-delete support</li>
    </ul>

    <h5 class="mt-4" id="security-alerts"><i class="fas fa-bell"></i> Security Alerts</h5>
    <ul>
        <li><strong>Vulnerability Alerts:</strong> Notify when new CVEs discovered</li>
        <li><strong>Breach Notifications:</strong> Alert when passwords found in breaches</li>
        <li><strong>Failed Login Alerts:</strong> Suspicious authentication attempts</li>
        <li><strong>Permission Changes:</strong> Notify on role or access modifications</li>
        <li><strong>Certificate Expiration:</strong> Warn before SSL certificates expire</li>
    </ul>
    """
    return render(request, 'core/help/section.html', {
        'title': 'Security',
        'section_id': 'security',
        'toc': toc,
        'content': content,
        'prev_section': {'title': 'Monitoring', 'url_name': 'core:help_monitoring'},
        'next_section': {'title': 'Reports & Analytics', 'url_name': 'core:help_reports'},
    })


@login_required
def help_api(request):
    """API documentation"""
    toc = [
        {'anchor': 'api-overview', 'heading': 'API Overview'},
        {'anchor': 'authentication', 'heading': 'Authentication'},
        {'anchor': 'rest-api', 'heading': 'REST API'},
        {'anchor': 'webhooks', 'heading': 'Webhooks'},
        {'anchor': 'filtering', 'heading': 'Filtering & Pagination'},
    ]
    content = """
    <h4>API Documentation</h4>
    <p class="lead">Programmatic access to ClientSt0r via REST API, webhooks, and the browser extension.</p>

    <h5 class="mt-4" id="api-overview"><i class="fas fa-plug"></i> API Overview</h5>
    <ul>
        <li><strong>REST API:</strong> Full-featured RESTful API for all resources</li>
        <li><strong>Webhooks:</strong> Real-time event notifications to external services</li>
        <li><strong>API Keys:</strong> Secure bearer token authentication</li>
        <li><strong>Rate Limiting:</strong> Fair usage policies (100 req/min standard)</li>
        <li><strong>Browser Extension:</strong> Uses the same API with your personal key</li>
    </ul>

    <h5 class="mt-4" id="authentication"><i class="fas fa-key"></i> Authentication</h5>
    <p>Include your API key in every request header:</p>
    <div class="card mt-2 mb-3">
        <div class="card-body bg-dark">
            <code class="text-info">Authorization: Bearer itdocs_live_YOUR_KEY_HERE</code>
        </div>
    </div>
    <p>Generate API keys: <strong>Profile menu → API Keys → Create New Key</strong></p>

    <h5 class="mt-4" id="rest-api"><i class="fas fa-exchange-alt"></i> REST API</h5>
    <p><strong>Base URL:</strong> <code>https://your-server/api/</code></p>

    <table class="table table-sm mt-3">
        <thead><tr><th>Resource</th><th>Endpoint</th><th>Methods</th></tr></thead>
        <tbody>
            <tr><td>Assets</td><td><code>/api/assets/</code></td><td>GET, POST, PATCH, DELETE</td></tr>
            <tr><td>Passwords</td><td><code>/api/passwords/</code></td><td>GET, POST, PATCH, DELETE</td></tr>
            <tr><td>Organizations</td><td><code>/api/organizations/</code></td><td>GET, POST, PATCH, DELETE</td></tr>
            <tr><td>Vehicles</td><td><code>/api/vehicles/</code></td><td>GET, POST, PATCH, DELETE</td></tr>
            <tr><td>VLANs</td><td><code>/api/vlans/</code></td><td>GET, POST, PATCH, DELETE</td></tr>
        </tbody>
    </table>

    <pre class="bg-dark p-3 rounded mt-3"><code class="text-light">curl -s https://your-server/api/assets/ \\
  -H "Authorization: Bearer itdocs_live_xxxxx" \\
  | python3 -m json.tool</code></pre>

    <h5 class="mt-4" id="webhooks"><i class="fas fa-bell"></i> Webhooks</h5>
    <p>Configure webhooks at <strong>Settings → Webhooks → Create Webhook</strong>.</p>
    <p>Supported events (fired from web, REST API, mobile and sync jobs alike):</p>
    <ul>
        <li><code>asset.created</code> / <code>asset.updated</code> / <code>asset.deleted</code></li>
        <li><code>document.created</code> / <code>document.updated</code> / <code>document.deleted</code></li>
        <li><code>password.created</code> / <code>password.updated</code> / <code>password.deleted</code> / <code>password.accessed</code> &mdash; metadata only, never the secret</li>
        <li><code>location.created</code> / <code>location.updated</code> / <code>location.deleted</code></li>
        <li><code>organization.updated</code></li>
        <li><code>user.login</code> / <code>user.logout</code> / <code>user.login_failed</code> / <code>user.password_changed</code> &mdash; customer users only, sent to the organizations they belong to (MSP staff activity is never sent)</li>
        <li><code>monitor.down</code> / <code>monitor.up</code> / <code>monitor.check_failed</code></li>
        <li><code>workflow.started</code> / <code>workflow.completed</code> / <code>workflow.failed</code></li>
        <li><code>integration.synced</code> / <code>integration.failed</code></li>
    </ul>
    <p>Each POST body is <code>{"event", "timestamp", "organization", "webhook_id", "data"}</code>. When a secret is set, the body is signed with HMAC-SHA256 in the <code>X-Webhook-Signature</code> header (<code>sha256=&lt;hex&gt;</code>). Deliveries are sent after the change is saved and are logged under the webhook's delivery history.</p>

    <div class="help-screenshot mt-3 mb-4">
      <svg viewBox="0 0 700 200" xmlns="http://www.w3.org/2000/svg" class="help-svg-screenshot">
        <rect width="700" height="200" rx="6" fill="#1a1f2e" stroke="#30363d"/>
        <!-- Header -->
        <rect width="700" height="36" rx="6" fill="#161b22" stroke="#30363d"/>
        <rect y="18" width="700" height="18" fill="#161b22"/>
        <text x="16" y="25" fill="#e6edf3" font-size="12" font-weight="bold" font-family="sans-serif">Webhooks</text>
        <rect x="578" y="8" width="108" height="22" rx="4" fill="#1f6feb"/>
        <text x="632" y="23" fill="#fff" font-size="10" font-family="sans-serif" text-anchor="middle">+ Create Webhook</text>

        <!-- Webhook card 1 -->
        <rect x="12" y="44" width="676" height="64" rx="4" fill="#161b22" stroke="#30363d"/>
        <circle cx="34" cy="76" r="8" fill="#1a7f37"/>
        <text x="54" y="70" fill="#e6edf3" font-size="12" font-weight="bold" font-family="sans-serif">Slack Alerts</text>
        <text x="54" y="84" fill="#8b949e" font-size="10" font-family="monospace">https://hooks.slack.com/services/T…</text>
        <!-- Event badges -->
        <rect x="340" y="62" width="80" height="14" rx="7" fill="#1f6feb44"/>
        <text x="380" y="73" fill="#79c0ff" font-size="9" font-family="sans-serif" text-anchor="middle">monitor.down</text>
        <rect x="428" y="62" width="74" height="14" rx="7" fill="#1f6feb44"/>
        <text x="465" y="73" fill="#79c0ff" font-size="9" font-family="sans-serif" text-anchor="middle">monitor.up</text>
        <rect x="508" y="62" width="104" height="14" rx="7" fill="#da363344"/>
        <text x="560" y="73" fill="#f85149" font-size="9" font-family="sans-serif" text-anchor="middle">monitor.check_failed</text>
        <text x="54" y="100" fill="#3fb950" font-size="10" font-family="sans-serif">✓ Active  |  Last delivery: 12m ago (200 OK)</text>
        <rect x="630" y="58" width="50" height="16" rx="4" fill="#21262d" stroke="#30363d"/>
        <text x="655" y="70" fill="#8b949e" font-size="9" font-family="sans-serif" text-anchor="middle">Test</text>

        <!-- Webhook card 2 -->
        <rect x="12" y="118" width="676" height="64" rx="4" fill="#161b22" stroke="#30363d"/>
        <circle cx="34" cy="150" r="8" fill="#6e40c9"/>
        <text x="54" y="144" fill="#e6edf3" font-size="12" font-weight="bold" font-family="sans-serif">Teams Notifications</text>
        <text x="54" y="158" fill="#8b949e" font-size="10" font-family="monospace">https://acmecorp.webhook.office.com/…</text>
        <rect x="340" y="136" width="80" height="14" rx="7" fill="#1f6feb44"/>
        <text x="380" y="147" fill="#79c0ff" font-size="9" font-family="sans-serif" text-anchor="middle">asset.created</text>
        <rect x="428" y="136" width="80" height="14" rx="7" fill="#1f6feb44"/>
        <text x="468" y="147" fill="#79c0ff" font-size="9" font-family="sans-serif" text-anchor="middle">asset.updated</text>
        <text x="54" y="174" fill="#3fb950" font-size="10" font-family="sans-serif">✓ Active  |  Last delivery: 2h ago (200 OK)</text>
        <rect x="630" y="132" width="50" height="16" rx="4" fill="#21262d" stroke="#30363d"/>
        <text x="655" y="144" fill="#8b949e" font-size="9" font-family="sans-serif" text-anchor="middle">Test</text>
        <!-- Annotation -->
        <line x1="560" y1="62" x2="600" y2="44" stroke="#f85149" stroke-width="1.5" stroke-dasharray="3,2"/>
        <rect x="570" y="36" width="120" height="12" rx="6" fill="#da363344"/>
        <text x="630" y="46" fill="#f85149" font-size="9" font-family="sans-serif" text-anchor="middle">Event types subscribed</text>
      </svg>
      <p class="help-screenshot-caption">Webhook configuration. Each webhook subscribes to specific event types (shown as badges). Use <strong>Test</strong> to send a sample payload and verify delivery.</p>
    </div>

    <h5 class="mt-4" id="filtering"><i class="fas fa-filter"></i> Filtering &amp; Pagination</h5>
    <ul>
        <li><strong>Filter:</strong> <code>?asset_type=server&amp;organization=1</code></li>
        <li><strong>Search:</strong> <code>?search=server</code></li>
        <li><strong>Ordering:</strong> <code>?ordering=-created_at</code></li>
        <li><strong>Pagination:</strong> <code>?page=2&amp;page_size=50</code></li>
        <li><strong>Needs Reorder:</strong> <code>?needs_reorder=true</code></li>
    </ul>
    """
    return render(request, 'core/help/section.html', {
        'title': 'API & Integrations',
        'section_id': 'api',
        'toc': toc,
        'content': content,
        'prev_section': {'title': 'Locations & WAN', 'url_name': 'core:help_locations'},
        'next_section': None,
    })


@login_required
def help_reports(request):
    """Reports & Analytics help"""
    toc = [
        {'anchor': 'dashboards', 'heading': 'Custom Dashboards'},
        {'anchor': 'report-templates', 'heading': 'Report Templates'},
        {'anchor': 'scheduled-reports', 'heading': 'Scheduled Reports'},
        {'anchor': 'analytics', 'heading': 'Analytics'},
    ]
    content = """
    <h4>Reports &amp; Analytics</h4>
    <p class="lead">Generate, schedule, and export reports across all your organization data. Build custom dashboards and track trends over time.</p>

    <h5 class="mt-4" id="dashboards"><i class="fas fa-chart-bar"></i> Custom Dashboards</h5>
    <p>Build organization-specific dashboards that combine data widgets from multiple sources:</p>
    <div class="row">
        <div class="col-md-6">
            <ul>
                <li><strong>Asset count</strong> — totals by type, status, or location</li>
                <li><strong>Warranty alerts</strong> — expiring in 30/60/90 days</li>
                <li><strong>Monitor status</strong> — WAN uptime summary</li>
                <li><strong>Vault health</strong> — breached or expiring credentials</li>
            </ul>
        </div>
        <div class="col-md-6">
            <ul>
                <li><strong>Vehicle fleet</strong> — status and upcoming maintenance</li>
                <li><strong>Recent activity</strong> — audit log summary</li>
                <li>Create multiple dashboards per organization</li>
                <li>Drag widgets to rearrange layout</li>
            </ul>
        </div>
    </div>
    <p>Dashboards are shared with all members of the organization. Navigate to <em>Reports → Dashboards</em> to create or manage them.</p>

    <div class="help-screenshot mt-3 mb-4">
      <svg viewBox="0 0 700 300" xmlns="http://www.w3.org/2000/svg" class="help-svg-screenshot">
        <rect width="700" height="300" rx="6" fill="#0d1117" stroke="#30363d"/>
        <!-- Page title bar -->
        <rect width="700" height="40" rx="6" fill="#161b22" stroke="#30363d"/>
        <rect y="20" width="700" height="20" fill="#161b22"/>
        <text x="16" y="26" fill="#e6edf3" font-size="14" font-weight="bold" font-family="sans-serif">Reports Dashboard</text>
        <rect x="580" y="10" width="106" height="22" rx="4" fill="#1f6feb"/>
        <text x="633" y="25" fill="#fff" font-size="11" font-family="sans-serif" text-anchor="middle">+ New Dashboard</text>

        <!-- Widget row 1 -->
        <!-- Asset count widget -->
        <rect x="12" y="52" width="156" height="100" rx="6" fill="#161b22" stroke="#30363d"/>
        <text x="28" y="72" fill="#8b949e" font-size="10" font-family="sans-serif">Total Assets</text>
        <text x="28" y="104" fill="#e6edf3" font-size="32" font-weight="bold" font-family="sans-serif">247</text>
        <text x="28" y="122" fill="#3fb950" font-size="10" font-family="sans-serif">↑ 12 this month</text>
        <text x="28" y="140" fill="#58a6ff" font-size="9" font-family="sans-serif">Servers · Switches · Laptops</text>

        <!-- Monitor status widget -->
        <rect x="180" y="52" width="156" height="100" rx="6" fill="#161b22" stroke="#30363d"/>
        <text x="196" y="72" fill="#8b949e" font-size="10" font-family="sans-serif">WAN Monitors</text>
        <text x="196" y="96" fill="#3fb950" font-size="22" font-weight="bold" font-family="sans-serif">18</text>
        <text x="228" y="96" fill="#8b949e" font-size="12" font-family="sans-serif">/ 19</text>
        <rect x="196" y="102" width="100" height="8" rx="4" fill="#21262d"/>
        <rect x="196" y="102" width="94" height="8" rx="4" fill="#3fb950"/>
        <text x="196" y="124" fill="#3fb950" font-size="10" font-family="sans-serif">18 UP</text>
        <text x="248" y="124" fill="#f85149" font-size="10" font-family="sans-serif">1 DOWN</text>
        <text x="196" y="140" fill="#8b949e" font-size="9" font-family="sans-serif">99.4% uptime (30 days)</text>

        <!-- Vault health widget -->
        <rect x="348" y="52" width="156" height="100" rx="6" fill="#161b22" stroke="#30363d"/>
        <text x="364" y="72" fill="#8b949e" font-size="10" font-family="sans-serif">Vault Health</text>
        <text x="364" y="100" fill="#f85149" font-size="22" font-weight="bold" font-family="sans-serif">3</text>
        <text x="364" y="118" fill="#f85149" font-size="10" font-family="sans-serif">Breached credentials</text>
        <text x="364" y="134" fill="#d29922" font-size="10" font-family="sans-serif">5 expiring within 30 days</text>
        <text x="364" y="148" fill="#3fb950" font-size="9" font-family="sans-serif">412 total entries healthy</text>

        <!-- Warranty widget -->
        <rect x="516" y="52" width="172" height="100" rx="6" fill="#161b22" stroke="#30363d"/>
        <text x="532" y="72" fill="#8b949e" font-size="10" font-family="sans-serif">Warranty Alerts</text>
        <text x="532" y="96" fill="#d29922" font-size="22" font-weight="bold" font-family="sans-serif">7</text>
        <text x="532" y="114" fill="#d29922" font-size="10" font-family="sans-serif">expiring within 30 days</text>
        <rect x="532" y="122" width="100" height="8" rx="4" fill="#21262d"/>
        <rect x="532" y="122" width="35" height="8" rx="4" fill="#d29922"/>
        <text x="532" y="144" fill="#8b949e" font-size="9" font-family="sans-serif">7 of 20 expiring assets flagged</text>

        <!-- Activity feed widget -->
        <rect x="12" y="164" width="328" height="124" rx="6" fill="#161b22" stroke="#30363d"/>
        <text x="28" y="182" fill="#8b949e" font-size="10" font-family="sans-serif">Recent Activity</text>
        <!-- Activity rows -->
        <circle cx="36" cy="202" r="6" fill="#1f6feb"/>
        <text x="48" y="206" fill="#c9d1d9" font-size="10" font-family="sans-serif">j.smith created asset Core Switch</text>
        <text x="48" y="218" fill="#3d444d" font-size="9" font-family="sans-serif">2 minutes ago</text>
        <circle cx="36" cy="232" r="6" fill="#3fb950"/>
        <text x="48" y="236" fill="#c9d1d9" font-size="10" font-family="sans-serif">s.lee updated password Cisco Router</text>
        <text x="48" y="248" fill="#3d444d" font-size="9" font-family="sans-serif">15 minutes ago</text>
        <circle cx="36" cy="262" r="6" fill="#f85149"/>
        <text x="48" y="266" fill="#c9d1d9" font-size="10" font-family="sans-serif">monitor Main Site DOWN detected</text>
        <text x="48" y="278" fill="#3d444d" font-size="9" font-family="sans-serif">1 hour ago</text>

        <!-- Fleet widget -->
        <rect x="352" y="164" width="336" height="124" rx="6" fill="#161b22" stroke="#30363d"/>
        <text x="368" y="182" fill="#8b949e" font-size="10" font-family="sans-serif">Fleet Status</text>
        <text x="368" y="210" fill="#e6edf3" font-size="12" font-family="sans-serif">Ford Transit (Van 01)</text>
        <rect x="500" y="198" width="54" height="18" rx="9" fill="#1f6feb"/>
        <text x="527" y="211" fill="#fff" font-size="10" font-family="sans-serif" text-anchor="middle">Active</text>
        <text x="368" y="234" fill="#e6edf3" font-size="12" font-family="sans-serif">Toyota Hilux (Van 02)</text>
        <rect x="500" y="222" width="80" height="18" rx="9" fill="#da363344" stroke="#f85149" stroke-width="1"/>
        <text x="540" y="235" fill="#f85149" font-size="10" font-family="sans-serif" text-anchor="middle">Maintenance</text>
        <text x="368" y="258" fill="#e6edf3" font-size="12" font-family="sans-serif">Mercedes Sprinter</text>
        <rect x="500" y="246" width="54" height="18" rx="9" fill="#1f6feb"/>
        <text x="527" y="259" fill="#fff" font-size="10" font-family="sans-serif" text-anchor="middle">Active</text>
        <!-- Annotation -->
        <line x1="420" y1="52" x2="440" y2="30" stroke="#79c0ff" stroke-width="1.5" stroke-dasharray="3,2"/>
        <rect x="420" y="20" width="130" height="14" rx="7" fill="#1f6feb44"/>
        <text x="485" y="31" fill="#79c0ff" font-size="10" font-family="sans-serif" text-anchor="middle">Drag widgets to rearrange</text>
      </svg>
      <p class="help-screenshot-caption">Dashboard showing asset count, WAN monitor status, vault health, warranty alerts, recent activity, and fleet status widgets. Each widget updates in real time.</p>
    </div>

    <h5 class="mt-4" id="report-templates"><i class="fas fa-file-alt"></i> Report Templates</h5>
    <p>Report templates define what data to include, how to format it, and where to send it:</p>
    <div class="table-responsive mt-2">
        <table class="table table-sm table-bordered">
            <thead><tr><th>Field</th><th>Description</th></tr></thead>
            <tbody>
                <tr><td><strong>Data Source</strong></td><td>Assets, Passwords, Vehicles, Monitors, Audit Log, etc.</td></tr>
                <tr><td><strong>Filters</strong></td><td>Scope by type, status, date range, location</td></tr>
                <tr><td><strong>Columns</strong></td><td>Choose exactly which fields to include</td></tr>
                <tr><td><strong>Format</strong></td><td>CSV, PDF, or HTML</td></tr>
            </tbody>
        </table>
    </div>
    <p><strong>Common built-in templates:</strong></p>
    <ul>
        <li>Asset Inventory — full list with serial, location, warranty, status</li>
        <li>Expiring Warranties — assets with warranty ending within N days</li>
        <li>Needs Reorder — all assets flagged for replacement</li>
        <li>Breached Credentials — vault entries with HIBP hits</li>
        <li>Vehicle Maintenance Due — overdue and upcoming service</li>
        <li>Monitor Uptime Summary — 30-day uptime % per endpoint</li>
        <li>User Activity — audit log summary by user and action</li>
    </ul>
    <p>Generate a report at <em>Reports → Templates → (select) → Generate</em>. Results can be downloaded immediately or saved to <em>Generated Reports</em>.</p>

    <div class="help-screenshot mt-3 mb-4">
      <svg viewBox="0 0 700 200" xmlns="http://www.w3.org/2000/svg" class="help-svg-screenshot">
        <rect width="700" height="200" rx="6" fill="#1a1f2e" stroke="#30363d"/>
        <!-- Header -->
        <rect width="700" height="40" rx="6" fill="#161b22" stroke="#30363d"/>
        <rect y="20" width="700" height="20" fill="#161b22"/>
        <text x="16" y="26" fill="#e6edf3" font-size="13" font-weight="bold" font-family="sans-serif">Report Templates</text>
        <rect x="568" y="10" width="118" height="22" rx="4" fill="#1f6feb"/>
        <text x="627" y="25" fill="#fff" font-size="11" font-family="sans-serif" text-anchor="middle">+ New Template</text>
        <!-- Template rows -->
        <rect x="12" y="50" width="676" height="36" rx="4" fill="#0d1117" stroke="#30363d"/>
        <rect x="24" y="60" width="10" height="16" rx="2" fill="#3fb950"/>
        <text x="42" y="72" fill="#e6edf3" font-size="12" font-family="sans-serif">Asset Inventory</text>
        <text x="220" y="72" fill="#8b949e" font-size="11" font-family="sans-serif">Assets · All fields · CSV</text>
        <rect x="520" y="59" width="70" height="18" rx="4" fill="#1f6feb"/>
        <text x="555" y="72" fill="#fff" font-size="10" font-family="sans-serif" text-anchor="middle">▶ Generate</text>
        <rect x="600" y="59" width="70" height="18" rx="4" fill="#21262d" stroke="#30363d"/>
        <text x="635" y="72" fill="#8b949e" font-size="10" font-family="sans-serif" text-anchor="middle">✎ Edit</text>

        <rect x="12" y="92" width="676" height="36" rx="4" fill="#161b22" stroke="#30363d"/>
        <rect x="24" y="102" width="10" height="16" rx="2" fill="#d29922"/>
        <text x="42" y="114" fill="#e6edf3" font-size="12" font-family="sans-serif">Expiring Warranties</text>
        <text x="220" y="114" fill="#8b949e" font-size="11" font-family="sans-serif">Assets · Next 30 days · PDF</text>
        <rect x="520" y="101" width="70" height="18" rx="4" fill="#1f6feb"/>
        <text x="555" y="114" fill="#fff" font-size="10" font-family="sans-serif" text-anchor="middle">▶ Generate</text>
        <rect x="600" y="101" width="70" height="18" rx="4" fill="#21262d" stroke="#30363d"/>
        <text x="635" y="114" fill="#8b949e" font-size="10" font-family="sans-serif" text-anchor="middle">✎ Edit</text>

        <rect x="12" y="134" width="676" height="36" rx="4" fill="#0d1117" stroke="#30363d"/>
        <rect x="24" y="144" width="10" height="16" rx="2" fill="#f85149"/>
        <text x="42" y="156" fill="#e6edf3" font-size="12" font-family="sans-serif">Breached Credentials</text>
        <text x="220" y="156" fill="#8b949e" font-size="11" font-family="sans-serif">Vault · HIBP hits · CSV</text>
        <rect x="520" y="143" width="70" height="18" rx="4" fill="#1f6feb"/>
        <text x="555" y="156" fill="#fff" font-size="10" font-family="sans-serif" text-anchor="middle">▶ Generate</text>
        <rect x="600" y="143" width="70" height="18" rx="4" fill="#21262d" stroke="#30363d"/>
        <text x="635" y="156" fill="#8b949e" font-size="10" font-family="sans-serif" text-anchor="middle">✎ Edit</text>
        <!-- Annotation -->
        <line x1="555" y1="77" x2="620" y2="48" stroke="#79c0ff" stroke-width="1.5" stroke-dasharray="3,2"/>
        <rect x="590" y="38" width="100" height="14" rx="7" fill="#1f6feb44"/>
        <text x="640" y="49" fill="#79c0ff" font-size="10" font-family="sans-serif" text-anchor="middle">Run instantly or save</text>
      </svg>
      <p class="help-screenshot-caption">Report templates list. Click <strong>Generate</strong> to run any template immediately — results download as CSV or PDF. Edit to change filters, columns, or format.</p>
    </div>

    <h5 class="mt-4" id="scheduled-reports"><i class="fas fa-clock"></i> Scheduled Reports</h5>
    <p>Automate report delivery on a recurring schedule:</p>
    <ul>
        <li><strong>Frequency:</strong> Daily, Weekly, or Monthly</li>
        <li><strong>Recipients:</strong> One or more email addresses</li>
        <li><strong>Format:</strong> CSV, PDF, or HTML attachment</li>
        <li><strong>Toggle:</strong> Pause and resume without deleting</li>
        <li><strong>History:</strong> Delivery log with success/failure status</li>
    </ul>
    <p>Manage scheduled reports at <em>Reports → Scheduled</em>.</p>

    <h5 class="mt-4" id="analytics"><i class="fas fa-chart-line"></i> Analytics</h5>
    <p>The analytics overview provides real-time metrics and trend charts at <em>Reports → Analytics</em>:</p>
    <ul>
        <li><strong>Asset growth</strong> — assets added over time</li>
        <li><strong>Monitor reliability</strong> — uptime trend across all monitors</li>
        <li><strong>Vault usage</strong> — new entries, reveals, breach rate</li>
        <li><strong>Audit events</strong> — activity volume by type and user</li>
    </ul>

    <div class="help-screenshot mt-3 mb-4">
      <svg viewBox="0 0 700 220" xmlns="http://www.w3.org/2000/svg" class="help-svg-screenshot">
        <rect width="700" height="220" rx="6" fill="#1a1f2e" stroke="#30363d"/>
        <text x="16" y="28" fill="#e6edf3" font-size="13" font-weight="bold" font-family="sans-serif">Analytics Overview</text>
        <!-- Asset growth chart -->
        <rect x="12" y="40" width="330" height="168" rx="4" fill="#161b22" stroke="#30363d"/>
        <text x="28" y="58" fill="#8b949e" font-size="10" font-family="sans-serif">Asset Growth (last 6 months)</text>
        <!-- Y axis labels -->
        <text x="28" y="80" fill="#3d444d" font-size="8" font-family="monospace">300</text>
        <text x="28" y="120" fill="#3d444d" font-size="8" font-family="monospace">200</text>
        <text x="28" y="160" fill="#3d444d" font-size="8" font-family="monospace">100</text>
        <!-- Grid lines -->
        <line x1="50" y1="76" x2="330" y2="76" stroke="#21262d" stroke-width="0.5"/>
        <line x1="50" y1="116" x2="330" y2="116" stroke="#21262d" stroke-width="0.5"/>
        <line x1="50" y1="156" x2="330" y2="156" stroke="#21262d" stroke-width="0.5"/>
        <!-- Bar chart -->
        <rect x="60" y="144" width="28" height="16" rx="2" fill="#1f6feb88"/>
        <rect x="105" y="136" width="28" height="24" rx="2" fill="#1f6feb88"/>
        <rect x="150" y="126" width="28" height="34" rx="2" fill="#1f6feb88"/>
        <rect x="195" y="118" width="28" height="42" rx="2" fill="#1f6feb88"/>
        <rect x="240" y="106" width="28" height="54" rx="2" fill="#1f6feb"/>
        <rect x="285" y="90" width="28" height="70" rx="2" fill="#1f6feb"/>
        <!-- X labels -->
        <text x="66" y="172" fill="#3d444d" font-size="8" font-family="sans-serif">Sep</text>
        <text x="111" y="172" fill="#3d444d" font-size="8" font-family="sans-serif">Oct</text>
        <text x="156" y="172" fill="#3d444d" font-size="8" font-family="sans-serif">Nov</text>
        <text x="201" y="172" fill="#3d444d" font-size="8" font-family="sans-serif">Dec</text>
        <text x="246" y="172" fill="#3d444d" font-size="8" font-family="sans-serif">Jan</text>
        <text x="289" y="172" fill="#3fb950" font-size="8" font-weight="bold" font-family="sans-serif">Feb</text>
        <text x="28" y="196" fill="#3fb950" font-size="9" font-family="sans-serif">247 total · ↑12 this month</text>

        <!-- Monitor uptime chart -->
        <rect x="354" y="40" width="334" height="168" rx="4" fill="#161b22" stroke="#30363d"/>
        <text x="370" y="58" fill="#8b949e" font-size="10" font-family="sans-serif">Monitor Uptime Trend</text>
        <!-- Line chart grid -->
        <line x1="390" y1="76" x2="672" y2="76" stroke="#21262d" stroke-width="0.5"/>
        <line x1="390" y1="106" x2="672" y2="106" stroke="#21262d" stroke-width="0.5"/>
        <line x1="390" y1="136" x2="672" y2="136" stroke="#21262d" stroke-width="0.5"/>
        <line x1="390" y1="166" x2="672" y2="166" stroke="#21262d" stroke-width="0.5"/>
        <!-- Y axis -->
        <text x="368" y="80" fill="#3d444d" font-size="8" font-family="monospace">100</text>
        <text x="368" y="110" fill="#3d444d" font-size="8" font-family="monospace">99</text>
        <text x="368" y="140" fill="#3d444d" font-size="8" font-family="monospace">98</text>
        <!-- Uptime line (near 100%) -->
        <polyline points="400,82 440,80 480,79 520,85 560,80 600,82 640,78 672,80"
                  fill="none" stroke="#3fb950" stroke-width="2" stroke-linejoin="round"/>
        <!-- Dip point annotation -->
        <circle cx="520" cy="85" r="4" fill="#f85149"/>
        <line x1="520" y1="85" x2="560" y2="60" stroke="#f85149" stroke-width="1.5" stroke-dasharray="3,2"/>
        <rect x="520" y="50" width="90" height="14" rx="7" fill="#da363344"/>
        <text x="565" y="61" fill="#f85149" font-size="9" font-family="sans-serif" text-anchor="middle">Incident: 1h outage</text>
        <text x="370" y="196" fill="#3fb950" font-size="9" font-family="sans-serif">Avg 99.4% · 19 monitors tracked</text>
      </svg>
      <p class="help-screenshot-caption">Analytics charts showing asset growth over 6 months (bar chart) and WAN monitor uptime trend (line chart). Incident dips are annotated with the event details.</p>
    </div>
    """
    return render(request, 'core/help/section.html', {
        'title': 'Reports & Analytics',
        'section_id': 'reports',
        'toc': toc,
        'content': content,
        'prev_section': {'title': 'Security', 'url_name': 'core:help_security'},
        'next_section': {'title': 'Workflows', 'url_name': 'core:help_workflows'},
    })


@login_required
def help_workflows(request):
    """Workflows / Processes help"""
    toc = [
        {'anchor': 'processes', 'heading': 'Processes'},
        {'anchor': 'executing', 'heading': 'Executing a Process'},
        {'anchor': 'global-processes', 'heading': 'Global Processes'},
    ]
    content = """
    <h4>Workflows</h4>
    <p class="lead">Define and execute step-by-step checklists for repeatable IT tasks — onboarding, offboarding, maintenance, incident response, and more.</p>

    <div class="alert alert-info mb-4">
        <i class="fas fa-info-circle"></i> <strong>Terminology:</strong>
        A <strong>Process</strong> is a reusable workflow template.
        An <strong>Execution</strong> is a live running instance of that process for a specific task or client.
    </div>

    <h5 class="mt-4" id="processes"><i class="fas fa-sitemap"></i> Processes</h5>
    <p>Each process defines the ordered steps required to complete a task:</p>
    <div class="table-responsive mt-2">
        <table class="table table-sm table-bordered">
            <thead><tr><th>Field</th><th>Description</th></tr></thead>
            <tbody>
                <tr><td><strong>Name</strong></td><td>e.g., "Employee Onboarding", "Network Device Replacement"</td></tr>
                <tr><td><strong>Category</strong></td><td>Onboarding / Offboarding / Maintenance / Incident / etc.</td></tr>
                <tr><td><strong>Stages</strong></td><td>Ordered list of steps — each with title, instructions, and checklist items</td></tr>
                <tr><td><strong>Organization</strong></td><td>Scoped to one org, or Global (shared across all)</td></tr>
            </tbody>
        </table>
    </div>
    <p>Stages can be drag-reordered and each stage can have:</p>
    <ul>
        <li>Detailed instructions for the person completing the step</li>
        <li>Sub-tasks (checklist items) within the stage</li>
        <li>An assigned role (who is responsible)</li>
        <li>A required flag (must complete before moving on)</li>
    </ul>
    <p>Manage processes at <em>Processes</em> in the navigation.</p>

    <div class="help-screenshot mt-3 mb-4">
      <svg viewBox="0 0 700 260" xmlns="http://www.w3.org/2000/svg" class="help-svg-screenshot">
        <rect width="700" height="260" rx="6" fill="#1a1f2e" stroke="#30363d"/>
        <!-- Header -->
        <rect width="700" height="40" rx="6" fill="#161b22" stroke="#30363d"/>
        <rect y="20" width="700" height="20" fill="#161b22"/>
        <text x="16" y="26" fill="#e6edf3" font-size="13" font-weight="bold" font-family="sans-serif">Employee Onboarding</text>
        <rect x="560" y="10" width="126" height="22" rx="4" fill="#1f6feb"/>
        <text x="623" y="25" fill="#fff" font-size="11" font-family="sans-serif" text-anchor="middle">▶ Execute Process</text>
        <!-- Progress bar -->
        <text x="16" y="58" fill="#8b949e" font-size="10" font-family="sans-serif">Progress: 3 / 6 stages complete</text>
        <rect x="16" y="62" width="668" height="8" rx="4" fill="#21262d"/>
        <rect x="16" y="62" width="334" height="8" rx="4" fill="#1f6feb"/>
        <!-- Stage 1 - complete -->
        <rect x="12" y="82" width="676" height="44" rx="4" fill="#161b22" stroke="#30363d"/>
        <rect x="12" y="82" width="4" height="44" rx="2" fill="#3fb950"/>
        <circle cx="34" cy="104" r="10" fill="#1a7f37" stroke="#3fb950"/>
        <text x="34" y="108" fill="#fff" font-size="12" font-family="sans-serif" text-anchor="middle">✓</text>
        <text x="54" y="99" fill="#e6edf3" font-size="12" font-weight="bold" font-family="sans-serif">1. Create AD Account</text>
        <text x="54" y="115" fill="#3fb950" font-size="10" font-family="sans-serif">Completed by j.admin · 9:02 AM</text>
        <text x="580" y="108" fill="#3d444d" font-size="10" font-family="sans-serif">IT Admin</text>
        <!-- Stage 2 - complete -->
        <rect x="12" y="132" width="676" height="44" rx="4" fill="#161b22" stroke="#30363d"/>
        <rect x="12" y="132" width="4" height="44" rx="2" fill="#3fb950"/>
        <circle cx="34" cy="154" r="10" fill="#1a7f37" stroke="#3fb950"/>
        <text x="34" y="158" fill="#fff" font-size="12" font-family="sans-serif" text-anchor="middle">✓</text>
        <text x="54" y="149" fill="#e6edf3" font-size="12" font-weight="bold" font-family="sans-serif">2. Provision Laptop</text>
        <text x="54" y="165" fill="#3fb950" font-size="10" font-family="sans-serif">Completed by j.admin · 10:45 AM</text>
        <text x="580" y="158" fill="#3d444d" font-size="10" font-family="sans-serif">IT Admin</text>
        <!-- Stage 3 - in progress -->
        <rect x="12" y="182" width="676" height="44" rx="4" fill="#1f3a5f" stroke="#1f6feb"/>
        <rect x="12" y="182" width="4" height="44" rx="2" fill="#1f6feb"/>
        <circle cx="34" cy="204" r="10" fill="#1f6feb" stroke="#58a6ff"/>
        <text x="34" y="208" fill="#fff" font-size="10" font-family="sans-serif" text-anchor="middle">3</text>
        <text x="54" y="199" fill="#e6edf3" font-size="12" font-weight="bold" font-family="sans-serif">3. Set Up Email &amp; Teams</text>
        <text x="54" y="215" fill="#79c0ff" font-size="10" font-family="sans-serif">In Progress — assigned to s.helpdesk</text>
        <rect x="580" y="193" width="96" height="18" rx="4" fill="#1f6feb"/>
        <text x="628" y="206" fill="#fff" font-size="10" font-family="sans-serif" text-anchor="middle">Mark Complete</text>
        <!-- Stage 4 - pending -->
        <rect x="12" y="232" width="676" height="20" rx="4" fill="#0d1117" stroke="#21262d" stroke-width="0.5" opacity="0.7"/>
        <circle cx="34" cy="242" r="8" fill="#21262d" stroke="#30363d"/>
        <text x="34" y="246" fill="#3d444d" font-size="9" font-family="sans-serif" text-anchor="middle">4</text>
        <text x="54" y="246" fill="#6e7681" font-size="11" font-family="sans-serif">4. Security Training (pending)</text>
        <!-- Annotation -->
        <line x1="628" y1="182" x2="660" y2="162" stroke="#79c0ff" stroke-width="1.5" stroke-dasharray="3,2"/>
        <rect x="620" y="150" width="72" height="14" rx="7" fill="#1f6feb44"/>
        <text x="656" y="161" fill="#79c0ff" font-size="9" font-family="sans-serif" text-anchor="middle">Active stage</text>
      </svg>
      <p class="help-screenshot-caption">Process execution view. Green stages are complete (logged with timestamp and user), the blue stage is active, and grey stages are pending. Click <strong>Mark Complete</strong> to advance.</p>
    </div>

    <h5 class="mt-4" id="executing"><i class="fas fa-play-circle"></i> Executing a Process</h5>
    <ol>
        <li>Open a process from the library and click <strong>Execute</strong></li>
        <li>Fill in execution metadata: assigned user, target client, due date</li>
        <li>Work through each stage — check off items as completed</li>
        <li>Add notes per stage as needed</li>
        <li>Process is marked complete when all required stages are done</li>
    </ol>
    <p><strong>Execution tracking:</strong></p>
    <ul>
        <li><strong>Progress bar</strong> — shows % of stages completed</li>
        <li><strong>Audit trail</strong> — every stage completion logged with timestamp and user</li>
        <li><strong>Reassignment</strong> — assign individual stages to specific users</li>
        <li><strong>Due dates</strong> — overall and per-stage deadlines</li>
    </ul>
    <p>View all active and completed executions at <em>Processes → Executions</em>.</p>

    <h5 class="mt-4" id="global-processes"><i class="fas fa-globe"></i> Global Processes</h5>
    <p><strong>Global Processes</strong> are available across all organizations — ideal for standardized IT procedures:</p>
    <ul>
        <li>Only <strong>superusers/staff</strong> can create global processes</li>
        <li>Global processes appear in every organization's process library</li>
        <li>Organizations can <strong>copy</strong> a global process to customize it</li>
    </ul>
    <p>Examples: Employee Onboarding Checklist, New Client Onboarding, Security Incident Response, Quarterly Review.</p>
    <p>Manage global processes at <em>Processes → Global</em> (staff only).</p>
    """
    return render(request, 'core/help/section.html', {
        'title': 'Workflows',
        'section_id': 'workflows',
        'toc': toc,
        'content': content,
        'prev_section': {'title': 'Reports & Analytics', 'url_name': 'core:help_reports'},
        'next_section': {'title': 'Documentation & KB', 'url_name': 'core:help_documentation'},
    })


@login_required
def help_documentation(request):
    """Documentation & Knowledge Base help"""
    toc = [
        {'anchor': 'documents', 'heading': 'Documents'},
        {'anchor': 'templates', 'heading': 'Document Templates'},
        {'anchor': 'knowledge-base', 'heading': 'Knowledge Base'},
        {'anchor': 'diagrams', 'heading': 'Network Diagrams'},
        {'anchor': 'ai-assistant', 'heading': 'AI Writing Assistant'},
    ]
    content = """
    <h4>Documentation &amp; Knowledge Base</h4>
    <p class="lead">Create, organize, and share technical documentation, runbooks, knowledge base articles, and network diagrams — with WYSIWYG or Markdown editors.</p>

    <h5 class="mt-4" id="documents"><i class="fas fa-file-alt"></i> Documents</h5>
    <p>Documents are rich-content pages scoped to your organization. Navigate to <em>Docs</em> to create and manage them.</p>
    <div class="table-responsive mt-2">
        <table class="table table-sm table-bordered">
            <thead><tr><th>Field</th><th>Description</th></tr></thead>
            <tbody>
                <tr><td><strong>Title</strong></td><td>Document name</td></tr>
                <tr><td><strong>Editor</strong></td><td>WYSIWYG (Quill) for formatted content, or Markdown for technical runbooks</td></tr>
                <tr><td><strong>Category</strong></td><td>Organize into folders/categories (up to 3 levels deep)</td></tr>
                <tr><td><strong>Tags</strong></td><td>Free-form labels for filtering and search</td></tr>
            </tbody>
        </table>
    </div>
    <p>Upload existing files (PDF, DOCX, images) at <em>Docs → Upload</em>. Files are served through authenticated views only.</p>

    <div class="help-screenshot mt-3 mb-4">
      <svg viewBox="0 0 700 240" xmlns="http://www.w3.org/2000/svg" class="help-svg-screenshot">
        <rect width="700" height="240" rx="6" fill="#1a1f2e" stroke="#30363d"/>
        <!-- Sidebar -->
        <rect width="180" height="240" rx="6" fill="#161b22" stroke="#30363d"/>
        <rect width="180" height="184" y="56" fill="#161b22"/>
        <text x="14" y="24" fill="#8b949e" font-size="10" font-family="sans-serif">CATEGORIES</text>
        <text x="14" y="46" fill="#c9d1d9" font-size="11" font-family="sans-serif">📁 Network</text>
        <text x="14" y="66" fill="#c9d1d9" font-size="11" font-family="sans-serif">📁 Runbooks</text>
        <rect x="10" y="72" width="160" height="20" rx="4" fill="#1f6feb22"/>
        <text x="22" y="86" fill="#58a6ff" font-size="11" font-family="sans-serif">📄 Outage Runbook</text>
        <text x="14" y="106" fill="#c9d1d9" font-size="11" font-family="sans-serif">📁 Client Reports</text>
        <text x="14" y="126" fill="#c9d1d9" font-size="11" font-family="sans-serif">📁 Change Requests</text>
        <text x="14" y="156" fill="#8b949e" font-size="10" font-family="sans-serif">TAGS</text>
        <rect x="14" y="164" width="48" height="16" rx="8" fill="#1f6feb33" stroke="#1f6feb66"/>
        <text x="38" y="176" fill="#79c0ff" font-size="9" font-family="sans-serif" text-anchor="middle">network</text>
        <rect x="68" y="164" width="52" height="16" rx="8" fill="#3fb95033" stroke="#3fb95066"/>
        <text x="94" y="176" fill="#3fb950" font-size="9" font-family="sans-serif" text-anchor="middle">runbook</text>
        <rect x="126" y="164" width="44" height="16" rx="8" fill="#d2992233" stroke="#d2992266"/>
        <text x="148" y="176" fill="#d29922" font-size="9" font-family="sans-serif" text-anchor="middle">urgent</text>

        <!-- Main doc view -->
        <rect x="188" y="10" width="500" height="220" rx="4" fill="#0d1117" stroke="#21262d"/>
        <text x="204" y="34" fill="#e6edf3" font-size="16" font-weight="bold" font-family="sans-serif">Network Outage Runbook</text>
        <text x="204" y="52" fill="#3d444d" font-size="10" font-family="sans-serif">Last edited by j.admin · 2 days ago · Tags: network, runbook, urgent</text>
        <line x1="204" y1="60" x2="680" y2="60" stroke="#21262d"/>
        <!-- Doc content -->
        <text x="204" y="80" fill="#8b949e" font-size="11" font-weight="bold" font-family="sans-serif">## 1. Immediate Response</text>
        <text x="204" y="98" fill="#c9d1d9" font-size="10" font-family="sans-serif">1. Check WAN monitor dashboard for affected circuits</text>
        <text x="204" y="114" fill="#c9d1d9" font-size="10" font-family="sans-serif">2. Ping default gateway from affected site</text>
        <text x="204" y="130" fill="#c9d1d9" font-size="10" font-family="sans-serif">3. Contact ISP: 1-800-XXX-XXXX · Circuit ID: XXXX-XXXX</text>
        <text x="204" y="156" fill="#8b949e" font-size="11" font-weight="bold" font-family="sans-serif">## 2. Escalation Path</text>
        <text x="204" y="174" fill="#c9d1d9" font-size="10" font-family="sans-serif">Network Engineer → IT Manager → CTO</text>
        <!-- Code block -->
        <rect x="204" y="186" width="460" height="32" rx="4" fill="#161b22" stroke="#30363d"/>
        <text x="216" y="202" fill="#79c0ff" font-size="10" font-family="monospace">ping 8.8.8.8 -c 4  # test external connectivity</text>
        <!-- Annotation -->
        <line x1="350" y1="60" x2="420" y2="38" stroke="#f0b429" stroke-width="1.5" stroke-dasharray="3,2"/>
        <rect x="394" y="26" width="130" height="14" rx="7" fill="#f0b42944"/>
        <text x="459" y="37" fill="#f0b429" font-size="10" font-family="sans-serif" text-anchor="middle">Markdown or WYSIWYG</text>
      </svg>
      <p class="help-screenshot-caption">Document view with category sidebar. Runbooks use Markdown for code snippets and structured steps. Tags are shown as color-coded chips for quick filtering.</p>
    </div>

    <h5 class="mt-4" id="templates"><i class="fas fa-copy"></i> Document Templates</h5>
    <p>Templates are reusable document skeletons — create once, generate new documents instantly:</p>
    <ul>
        <li><strong>Runbooks</strong> — "Network Outage Runbook" starter with standard sections</li>
        <li><strong>Client reports</strong> — "Monthly IT Summary" with placeholder fields</li>
        <li><strong>Onboarding docs</strong> — "New Employee IT Setup" checklist</li>
        <li><strong>Change requests</strong> — structured change request form</li>
    </ul>
    <p>Templates support the same WYSIWYG and Markdown editors as documents. Manage at <em>Docs → Templates</em>.</p>

    <h5 class="mt-4" id="knowledge-base"><i class="fas fa-book"></i> Knowledge Base</h5>
    <p>The Knowledge Base is a searchable article library for reference material within your organization:</p>
    <ul>
        <li><strong>URL slugs</strong> — human-readable URLs (<code>/docs/kb/my-article/</code>)</li>
        <li><strong>Categories</strong> — organize articles by topic</li>
        <li><strong>Search</strong> — full-text search across all KB articles</li>
        <li><strong>Edit history</strong> — versioned changes for all articles</li>
        <li><strong>Global KB</strong> — superusers can publish articles visible across all organizations (company-wide policies, SOPs)</li>
    </ul>

    <h5 class="mt-4" id="diagrams"><i class="fas fa-project-diagram"></i> Network Diagrams</h5>
    <p>Create interactive network topology diagrams with a drag-and-drop canvas at <em>Docs → Diagrams</em>:</p>
    <ul>
        <li><strong>Node types</strong> — servers, switches, routers, firewalls, workstations, cloud, and more</li>
        <li><strong>Connections</strong> — labeled links with cable type and bandwidth</li>
        <li><strong>Templates</strong> — start from predefined diagram layouts</li>
        <li><strong>Export</strong> — PNG, SVG, or JSON format</li>
        <li>Diagrams can be embedded in documents and linked from asset records</li>
    </ul>

    <div class="help-screenshot mt-3 mb-4">
      <svg viewBox="0 0 700 240" xmlns="http://www.w3.org/2000/svg" class="help-svg-screenshot">
        <rect width="700" height="240" rx="6" fill="#1a1f2e" stroke="#30363d"/>
        <text x="16" y="26" fill="#e6edf3" font-size="13" font-weight="bold" font-family="sans-serif">Office Network Topology</text>
        <rect x="580" y="10" width="108" height="22" rx="4" fill="#21262d" stroke="#30363d"/>
        <text x="634" y="25" fill="#8b949e" font-size="11" font-family="sans-serif" text-anchor="middle">Export ▾</text>

        <!-- Internet cloud -->
        <ellipse cx="350" cy="60" rx="60" ry="25" fill="#1f3a5f" stroke="#1f6feb"/>
        <text x="350" y="55" fill="#79c0ff" font-size="10" font-family="sans-serif" text-anchor="middle">☁ Internet</text>
        <text x="350" y="68" fill="#58a6ff" font-size="9" font-family="monospace" text-anchor="middle">203.0.113.1</text>

        <!-- Firewall -->
        <line x1="350" y1="85" x2="350" y2="108" stroke="#e3b341" stroke-width="2"/>
        <rect x="310" y="108" width="80" height="34" rx="4" fill="#3a2a1a" stroke="#e3b341"/>
        <text x="350" y="122" fill="#e3b341" font-size="10" font-family="sans-serif" text-anchor="middle">🔥 Firewall</text>
        <text x="350" y="136" fill="#d29922" font-size="8" font-family="monospace" text-anchor="middle">10.0.0.1</text>

        <!-- Core switch -->
        <line x1="350" y1="142" x2="350" y2="162" stroke="#58a6ff" stroke-width="2"/>
        <rect x="295" y="162" width="110" height="30" rx="4" fill="#1f3a5f" stroke="#1f6feb"/>
        <text x="350" y="180" fill="#79c0ff" font-size="10" font-family="sans-serif" text-anchor="middle">⇄ Core Switch</text>

        <!-- Servers -->
        <line x1="310" y1="177" x2="200" y2="200" stroke="#3fb950" stroke-width="1.5"/>
        <rect x="140" y="200" width="120" height="30" rx="4" fill="#1a3a2a" stroke="#3fb950"/>
        <text x="200" y="218" fill="#3fb950" font-size="10" font-family="sans-serif" text-anchor="middle">🖥 Server Farm</text>

        <!-- Workstations -->
        <line x1="390" y1="177" x2="500" y2="200" stroke="#8957e5" stroke-width="1.5"/>
        <rect x="440" y="200" width="120" height="30" rx="4" fill="#2d1f3f" stroke="#8957e5"/>
        <text x="500" y="218" fill="#bc8cff" font-size="10" font-family="sans-serif" text-anchor="middle">💻 Workstations</text>

        <!-- WiFi AP -->
        <line x1="350" y1="192" x2="350" y2="210" stroke="#c9d1d9" stroke-width="1.5" stroke-dasharray="3,2"/>
        <rect x="310" y="210" width="80" height="26" rx="4" fill="#2d333b" stroke="#6e7681"/>
        <text x="350" y="226" fill="#c9d1d9" font-size="9" font-family="sans-serif" text-anchor="middle">📶 WiFi AP</text>

        <!-- Labels on lines -->
        <text x="255" y="195" fill="#3fb950" font-size="8" font-family="sans-serif">1Gbps</text>
        <text x="435" y="195" fill="#8957e5" font-size="8" font-family="sans-serif">1Gbps</text>
        <text x="355" y="152" fill="#e3b341" font-size="8" font-family="sans-serif">WAN</text>
        <!-- Annotation -->
        <line x1="200" y1="200" x2="160" y2="170" stroke="#79c0ff" stroke-width="1.5" stroke-dasharray="3,2"/>
        <rect x="100" y="156" width="110" height="18" rx="9" fill="#1f6feb44"/>
        <text x="155" y="169" fill="#79c0ff" font-size="10" font-family="sans-serif" text-anchor="middle">Click to edit node</text>
      </svg>
      <p class="help-screenshot-caption">Network diagram canvas showing firewall → core switch → servers/workstations/WiFi topology. Nodes are drag-and-drop; click any node to edit its properties or add links.</p>
    </div>

    <h5 class="mt-4" id="ai-assistant"><i class="fas fa-robot"></i> AI Writing Assistant</h5>
    <p>The built-in AI assistant helps write and improve documentation at <em>Docs → AI Assistant</em>:</p>
    <div class="table-responsive mt-2">
        <table class="table table-sm table-bordered">
            <thead><tr><th>Feature</th><th>What It Does</th></tr></thead>
            <tbody>
                <tr><td><strong>Generate</strong></td><td>Create a document draft from a plain-English prompt</td></tr>
                <tr><td><strong>Enhance</strong></td><td>Improve clarity, grammar, and completeness of existing content</td></tr>
                <tr><td><strong>Validate</strong></td><td>Check a runbook for missing steps or logical gaps</td></tr>
            </tbody>
        </table>
    </div>
    <div class="alert alert-warning mt-2">
        <i class="fas fa-exclamation-triangle"></i> AI features require an API key configured in <em>Settings → AI Integration</em>.
    </div>
    """
    return render(request, 'core/help/section.html', {
        'title': 'Documentation & KB',
        'section_id': 'documentation',
        'toc': toc,
        'content': content,
        'prev_section': {'title': 'Workflows', 'url_name': 'core:help_workflows'},
        'next_section': {'title': 'Locations & WAN', 'url_name': 'core:help_locations'},
    })


@login_required
def help_locations(request):
    """Locations & WAN Connections help"""
    toc = [
        {'anchor': 'locations', 'heading': 'Locations'},
        {'anchor': 'wan-connections', 'heading': 'WAN Connections'},
        {'anchor': 'floor-plans', 'heading': 'Floor Plans'},
    ]
    content = """
    <h4>Locations &amp; WAN Connections</h4>
    <p class="lead">Manage physical sites and the internet (WAN) connections serving each location.</p>

    <h5 class="mt-4" id="locations"><i class="fas fa-map-marker-alt"></i> Locations</h5>
    <p>A <strong>Location</strong> represents a physical site where equipment is installed or staff work. Navigate to <em>Locations</em> in the top menu.</p>
    <div class="table-responsive mt-2">
        <table class="table table-sm table-bordered">
            <thead><tr><th>Field</th><th>Description</th></tr></thead>
            <tbody>
                <tr><td><strong>Name</strong></td><td>e.g., "Head Office", "Data Center 1", "Remote Site A"</td></tr>
                <tr><td><strong>Address</strong></td><td>Street, city, state, country</td></tr>
                <tr><td><strong>Notes</strong></td><td>Site contacts, access instructions</td></tr>
                <tr><td><strong>Assets</strong></td><td>Assets can be associated with a location</td></tr>
                <tr><td><strong>Floor Plan</strong></td><td>Attach or auto-generate a floor plan diagram</td></tr>
            </tbody>
        </table>
    </div>
    <p>Locations provide a physical grouping for assets — assets can be further organized by rack or room within a location.</p>

    <div class="help-screenshot mt-3 mb-4">
      <svg viewBox="0 0 700 240" xmlns="http://www.w3.org/2000/svg" class="help-svg-screenshot">
        <rect width="700" height="240" rx="6" fill="#0d1117" stroke="#30363d"/>
        <!-- Page header -->
        <text x="16" y="28" fill="#e6edf3" font-size="14" font-weight="bold" font-family="sans-serif">Locations</text>
        <rect x="598" y="10" width="90" height="26" rx="4" fill="#238636" stroke="#2ea043"/>
        <text x="643" y="27" fill="#fff" font-size="11" font-family="sans-serif" text-anchor="middle">+ Add Location</text>

        <!-- Location card 1 -->
        <rect x="12" y="44" width="210" height="90" rx="6" fill="#161b22" stroke="#30363d"/>
        <text x="26" y="64" fill="#e6edf3" font-size="12" font-weight="bold" font-family="sans-serif">Head Office</text>
        <text x="26" y="80" fill="#8b949e" font-size="10" font-family="sans-serif">123 Main St, Springfield</text>
        <rect x="26" y="90" width="50" height="16" rx="8" fill="#1f6feb33" stroke="#1f6feb66"/>
        <text x="51" y="102" fill="#79c0ff" font-size="9" font-family="sans-serif" text-anchor="middle">42 assets</text>
        <rect x="84" y="90" width="60" height="16" rx="8" fill="#3fb95033" stroke="#3fb95066"/>
        <text x="114" y="102" fill="#3fb950" font-size="9" font-family="sans-serif" text-anchor="middle">2 WAN links</text>
        <rect x="26" y="114" width="72" height="14" rx="3" fill="#21262d"/>
        <text x="62" y="125" fill="#8b949e" font-size="10" font-family="sans-serif" text-anchor="middle">View Details</text>

        <!-- Location card 2 -->
        <rect x="238" y="44" width="210" height="90" rx="6" fill="#161b22" stroke="#30363d"/>
        <text x="252" y="64" fill="#e6edf3" font-size="12" font-weight="bold" font-family="sans-serif">Data Center 1</text>
        <text x="252" y="80" fill="#8b949e" font-size="10" font-family="sans-serif">456 Park Ave, Denver</text>
        <rect x="252" y="90" width="50" height="16" rx="8" fill="#1f6feb33" stroke="#1f6feb66"/>
        <text x="277" y="102" fill="#79c0ff" font-size="9" font-family="sans-serif" text-anchor="middle">89 assets</text>
        <rect x="310" y="90" width="60" height="16" rx="8" fill="#3fb95033" stroke="#3fb95066"/>
        <text x="340" y="102" fill="#3fb950" font-size="9" font-family="sans-serif" text-anchor="middle">3 WAN links</text>
        <rect x="252" y="114" width="72" height="14" rx="3" fill="#21262d"/>
        <text x="288" y="125" fill="#8b949e" font-size="10" font-family="sans-serif" text-anchor="middle">View Details</text>

        <!-- Location card 3 -->
        <rect x="464" y="44" width="210" height="90" rx="6" fill="#161b22" stroke="#30363d"/>
        <text x="478" y="64" fill="#e6edf3" font-size="12" font-weight="bold" font-family="sans-serif">Remote Site A</text>
        <text x="478" y="80" fill="#8b949e" font-size="10" font-family="sans-serif">789 Oak Rd, Austin</text>
        <rect x="478" y="90" width="50" height="16" rx="8" fill="#1f6feb33" stroke="#1f6feb66"/>
        <text x="503" y="102" fill="#79c0ff" font-size="9" font-family="sans-serif" text-anchor="middle">17 assets</text>
        <rect x="536" y="90" width="60" height="16" rx="8" fill="#d2992233" stroke="#d2992266"/>
        <text x="566" y="102" fill="#d29922" font-size="9" font-family="sans-serif" text-anchor="middle">1 WAN link</text>
        <rect x="478" y="114" width="72" height="14" rx="3" fill="#21262d"/>
        <text x="514" y="125" fill="#8b949e" font-size="10" font-family="sans-serif" text-anchor="middle">View Details</text>

        <!-- Location detail panel at bottom -->
        <rect x="12" y="150" width="676" height="78" rx="6" fill="#161b22" stroke="#30363d"/>
        <text x="26" y="170" fill="#e6edf3" font-size="12" font-weight="bold" font-family="sans-serif">Head Office — Detail</text>
        <text x="26" y="186" fill="#8b949e" font-size="10" font-family="sans-serif">Address: 123 Main St, Springfield · Notes: Main reception on ground floor, server room L2</text>
        <text x="26" y="202" fill="#c9d1d9" font-size="10" font-family="sans-serif">42 assets assigned · 2 WAN connections · Floor plan: attached</text>
        <rect x="530" y="158" width="70" height="20" rx="4" fill="#21262d" stroke="#30363d"/>
        <text x="565" y="172" fill="#8b949e" font-size="10" font-family="sans-serif" text-anchor="middle">Edit</text>
        <rect x="608" y="158" width="70" height="20" rx="4" fill="#21262d" stroke="#30363d"/>
        <text x="643" y="172" fill="#8b949e" font-size="10" font-family="sans-serif" text-anchor="middle">Floor Plan</text>

        <!-- Annotation -->
        <line x1="114" y1="102" x2="130" y2="142" stroke="#79c0ff" stroke-width="1.5" stroke-dasharray="3,2"/>
        <rect x="100" y="140" width="100" height="14" rx="7" fill="#1f6feb44"/>
        <text x="150" y="151" fill="#79c0ff" font-size="9" font-family="sans-serif" text-anchor="middle">Asset count badge</text>
      </svg>
      <p class="help-screenshot-caption">Location list showing site cards with address, asset count, and WAN links. Click a card to open the detail view showing full contact info, assigned assets, WAN connections, and floor plan.</p>
    </div>

    <h5 class="mt-4" id="wan-connections"><i class="fas fa-globe"></i> WAN Connections</h5>
    <p>Each location can have one or more <strong>WAN connections</strong> — the internet links serving that site. Access them from the location detail page.</p>
    <div class="table-responsive mt-2">
        <table class="table table-sm table-bordered">
            <thead><tr><th>Field</th><th>Description</th></tr></thead>
            <tbody>
                <tr><td><strong>Name</strong></td><td>e.g., "Primary Fibre", "4G Failover"</td></tr>
                <tr><td><strong>ISP</strong></td><td>Internet service provider name</td></tr>
                <tr><td><strong>Type</strong></td><td>Fibre / Cable / DSL / 4G / MPLS / etc.</td></tr>
                <tr><td><strong>Bandwidth</strong></td><td>Download and upload speeds</td></tr>
                <tr><td><strong>Public IP</strong></td><td>Static IP or range</td></tr>
                <tr><td><strong>Circuit ID</strong></td><td>ISP circuit reference number for support calls</td></tr>
                <tr><td><strong>Contract Expiry</strong></td><td>Renewal date for the ISP contract</td></tr>
                <tr><td><strong>Status</strong></td><td>Active / Inactive / Maintenance</td></tr>
            </tbody>
        </table>
    </div>
    <div class="alert alert-info mt-2">
        <i class="fas fa-info-circle"></i> For <strong>automated uptime monitoring</strong> of a WAN connection, create a
        <a href="{% url 'core:help_monitoring' %}">WAN Monitor</a> targeting the location's public IP or a hosted endpoint.
        WAN connections here are for documentation and ISP contract tracking only.
    </div>

    <div class="help-screenshot mt-3 mb-4">
      <svg viewBox="0 0 700 210" xmlns="http://www.w3.org/2000/svg" class="help-svg-screenshot">
        <rect width="700" height="210" rx="6" fill="#0d1117" stroke="#30363d"/>
        <!-- Section header -->
        <text x="16" y="28" fill="#e6edf3" font-size="13" font-weight="bold" font-family="sans-serif">WAN Connections — Head Office</text>
        <rect x="586" y="10" width="102" height="24" rx="4" fill="#238636" stroke="#2ea043"/>
        <text x="637" y="26" fill="#fff" font-size="11" font-family="sans-serif" text-anchor="middle">+ Add Connection</text>

        <!-- Table header -->
        <rect x="12" y="44" width="676" height="24" rx="4" fill="#161b22" stroke="#30363d"/>
        <text x="26" y="61" fill="#8b949e" font-size="10" font-family="sans-serif">Name</text>
        <text x="154" y="61" fill="#8b949e" font-size="10" font-family="sans-serif">ISP</text>
        <text x="264" y="61" fill="#8b949e" font-size="10" font-family="sans-serif">Type</text>
        <text x="340" y="61" fill="#8b949e" font-size="10" font-family="sans-serif">Down / Up</text>
        <text x="444" y="61" fill="#8b949e" font-size="10" font-family="sans-serif">Circuit ID</text>
        <text x="570" y="61" fill="#8b949e" font-size="10" font-family="sans-serif">Status</text>

        <!-- Row 1 — Primary Fibre -->
        <rect x="12" y="68" width="676" height="34" rx="0" fill="#161b22" stroke="#21262d"/>
        <text x="26" y="89" fill="#e6edf3" font-size="11" font-family="sans-serif">Primary Fibre</text>
        <text x="154" y="89" fill="#c9d1d9" font-size="11" font-family="sans-serif">Comcast</text>
        <text x="264" y="89" fill="#c9d1d9" font-size="11" font-family="sans-serif">Fibre</text>
        <text x="340" y="89" fill="#c9d1d9" font-size="11" font-family="sans-serif">1Gbps / 500Mbps</text>
        <text x="444" y="89" fill="#8b949e" font-size="10" font-family="monospace">CMC-2024-8891</text>
        <rect x="564" y="76" width="52" height="18" rx="9" fill="#1a3a2a" stroke="#3fb950"/>
        <text x="590" y="89" fill="#3fb950" font-size="10" font-family="sans-serif" text-anchor="middle">Active</text>

        <!-- Row 2 — 4G Failover -->
        <rect x="12" y="102" width="676" height="34" rx="0" fill="#0d1117" stroke="#21262d"/>
        <text x="26" y="123" fill="#e6edf3" font-size="11" font-family="sans-serif">4G Failover</text>
        <text x="154" y="123" fill="#c9d1d9" font-size="11" font-family="sans-serif">Verizon</text>
        <text x="264" y="123" fill="#c9d1d9" font-size="11" font-family="sans-serif">4G LTE</text>
        <text x="340" y="123" fill="#c9d1d9" font-size="11" font-family="sans-serif">50Mbps / 20Mbps</text>
        <text x="444" y="123" fill="#8b949e" font-size="10" font-family="monospace">VZN-LTE-0047</text>
        <rect x="557" y="110" width="66" height="18" rx="9" fill="#3a2a1a" stroke="#e3b341"/>
        <text x="590" y="123" fill="#e3b341" font-size="10" font-family="sans-serif" text-anchor="middle">Standby</text>

        <!-- Row 3 — MPLS -->
        <rect x="12" y="136" width="676" height="34" rx="0" fill="#161b22" stroke="#21262d"/>
        <text x="26" y="157" fill="#e6edf3" font-size="11" font-family="sans-serif">MPLS to DC1</text>
        <text x="154" y="157" fill="#c9d1d9" font-size="11" font-family="sans-serif">AT&amp;T</text>
        <text x="264" y="157" fill="#c9d1d9" font-size="11" font-family="sans-serif">MPLS</text>
        <text x="340" y="157" fill="#c9d1d9" font-size="11" font-family="sans-serif">100Mbps / 100Mbps</text>
        <text x="444" y="157" fill="#8b949e" font-size="10" font-family="monospace">ATT-MPLS-5523</text>
        <rect x="564" y="144" width="52" height="18" rx="9" fill="#1a3a2a" stroke="#3fb950"/>
        <text x="590" y="157" fill="#3fb950" font-size="10" font-family="sans-serif" text-anchor="middle">Active</text>

        <!-- Contract expiry note -->
        <rect x="12" y="180" width="676" height="22" rx="4" fill="#1f2d3a" stroke="#1f6feb44"/>
        <text x="24" y="195" fill="#79c0ff" font-size="10" font-family="sans-serif">ℹ Contract expiry reminders: Primary Fibre expires in 47 days — review renewal options</text>

        <!-- Annotation -->
        <line x1="590" y1="89" x2="640" y2="66" stroke="#3fb950" stroke-width="1.5" stroke-dasharray="3,2"/>
        <rect x="620" y="54" width="68" height="14" rx="7" fill="#1a3a2a44"/>
        <text x="654" y="65" fill="#3fb950" font-size="9" font-family="sans-serif" text-anchor="middle">Status badge</text>
      </svg>
      <p class="help-screenshot-caption">WAN connections for a location. Each row shows ISP name, connection type, bandwidth, circuit ID for support calls, and live status. A banner alerts when contracts are nearing expiry.</p>
    </div>

    <h5 class="mt-4" id="floor-plans"><i class="fas fa-drafting-compass"></i> Floor Plans</h5>
    <p>Attach a floor plan image to a location to map where equipment is physically installed:</p>
    <ul>
        <li><strong>Upload</strong> — attach an existing PNG/SVG floor plan image</li>
        <li><strong>Generate</strong> — auto-generate a simple floor plan from rack and asset data</li>
        <li><strong>Import</strong> — import from a structured JSON format</li>
    </ul>
    <p>Floor plans are visible on the location detail page and can be linked from individual asset records.</p>

    <div class="help-screenshot mt-3 mb-4">
      <svg viewBox="0 0 700 240" xmlns="http://www.w3.org/2000/svg" class="help-svg-screenshot">
        <rect width="700" height="240" rx="6" fill="#0d1117" stroke="#30363d"/>
        <text x="16" y="26" fill="#e6edf3" font-size="13" font-weight="bold" font-family="sans-serif">Floor Plan — Head Office, Level 2</text>
        <rect x="590" y="8" width="100" height="22" rx="4" fill="#21262d" stroke="#30363d"/>
        <text x="640" y="23" fill="#8b949e" font-size="11" font-family="sans-serif" text-anchor="middle">Upload Image</text>

        <!-- Floor plan bounding box -->
        <rect x="16" y="38" width="480" height="192" rx="4" fill="#161b22" stroke="#30363d"/>

        <!-- Rooms -->
        <!-- Server Room -->
        <rect x="30" y="52" width="120" height="80" rx="2" fill="#1f3a5f" stroke="#1f6feb" stroke-width="1.5"/>
        <text x="90" y="90" fill="#79c0ff" font-size="10" font-family="sans-serif" text-anchor="middle">Server Room</text>
        <!-- Assets inside server room -->
        <rect x="40" y="98" width="22" height="14" rx="2" fill="#1f6feb66" stroke="#1f6feb"/>
        <text x="51" y="109" fill="#79c0ff" font-size="8" font-family="sans-serif" text-anchor="middle">SRV-1</text>
        <rect x="68" y="98" width="22" height="14" rx="2" fill="#1f6feb66" stroke="#1f6feb"/>
        <text x="79" y="109" fill="#79c0ff" font-size="8" font-family="sans-serif" text-anchor="middle">SW-01</text>
        <rect x="96" y="98" width="22" height="14" rx="2" fill="#1f6feb66" stroke="#1f6feb"/>
        <text x="107" y="109" fill="#79c0ff" font-size="8" font-family="sans-serif" text-anchor="middle">FW-01</text>

        <!-- Meeting Room A -->
        <rect x="160" y="52" width="110" height="70" rx="2" fill="#1a2a1a" stroke="#3fb950" stroke-width="1.5"/>
        <text x="215" y="90" fill="#3fb950" font-size="10" font-family="sans-serif" text-anchor="middle">Meeting A</text>

        <!-- Open Office -->
        <rect x="280" y="52" width="200" height="120" rx="2" fill="#2d1f3f" stroke="#8957e5" stroke-width="1.5"/>
        <text x="380" y="105" fill="#bc8cff" font-size="11" font-family="sans-serif" text-anchor="middle">Open Office</text>
        <!-- Desks grid -->
        <rect x="294" y="64" width="28" height="18" rx="2" fill="#8957e544" stroke="#8957e5"/>
        <rect x="330" y="64" width="28" height="18" rx="2" fill="#8957e544" stroke="#8957e5"/>
        <rect x="366" y="64" width="28" height="18" rx="2" fill="#8957e544" stroke="#8957e5"/>
        <rect x="402" y="64" width="28" height="18" rx="2" fill="#8957e544" stroke="#8957e5"/>
        <rect x="438" y="64" width="28" height="18" rx="2" fill="#8957e544" stroke="#8957e5"/>

        <!-- Corridor -->
        <rect x="30" y="140" width="450" height="20" rx="0" fill="#0d1117"/>
        <text x="255" y="154" fill="#3d444d" font-size="9" font-family="sans-serif" text-anchor="middle">— corridor —</text>

        <!-- Breakroom -->
        <rect x="30" y="168" width="110" height="56" rx="2" fill="#2a1a1a" stroke="#e3b341" stroke-width="1.5"/>
        <text x="85" y="200" fill="#e3b341" font-size="10" font-family="sans-serif" text-anchor="middle">Break Room</text>

        <!-- Bathroom -->
        <rect x="150" y="168" width="80" height="56" rx="2" fill="#1a1a2a" stroke="#6e7681" stroke-width="1.5"/>
        <text x="190" y="200" fill="#6e7681" font-size="10" font-family="sans-serif" text-anchor="middle">WC</text>

        <!-- Storage -->
        <rect x="240" y="168" width="240" height="56" rx="2" fill="#21262d" stroke="#30363d" stroke-width="1.5"/>
        <text x="360" y="200" fill="#8b949e" font-size="10" font-family="sans-serif" text-anchor="middle">Storage / IDF Closet</text>

        <!-- Legend panel -->
        <rect x="510" y="38" width="180" height="192" rx="4" fill="#161b22" stroke="#30363d"/>
        <text x="524" y="58" fill="#8b949e" font-size="10" font-family="sans-serif">LEGEND</text>
        <rect x="524" y="66" width="12" height="10" rx="2" fill="#1f3a5f" stroke="#1f6feb"/>
        <text x="542" y="76" fill="#c9d1d9" font-size="10" font-family="sans-serif">Server / Network</text>
        <rect x="524" y="84" width="12" height="10" rx="2" fill="#2d1f3f" stroke="#8957e5"/>
        <text x="542" y="94" fill="#c9d1d9" font-size="10" font-family="sans-serif">Workstations</text>
        <rect x="524" y="102" width="12" height="10" rx="2" fill="#1a2a1a" stroke="#3fb950"/>
        <text x="542" y="112" fill="#c9d1d9" font-size="10" font-family="sans-serif">Meeting Rooms</text>
        <rect x="524" y="120" width="12" height="10" rx="2" fill="#2a1a1a" stroke="#e3b341"/>
        <text x="542" y="130" fill="#c9d1d9" font-size="10" font-family="sans-serif">Kitchen / Break</text>
        <line x1="524" y1="150" x2="682" y2="150" stroke="#21262d"/>
        <text x="524" y="166" fill="#8b949e" font-size="10" font-family="sans-serif">ASSETS ON FLOOR</text>
        <text x="524" y="182" fill="#58a6ff" font-size="11" font-family="sans-serif">SRV-1 · SW-01 · FW-01</text>
        <text x="524" y="196" fill="#8b949e" font-size="10" font-family="sans-serif">Click asset to open record</text>
        <text x="524" y="212" fill="#3fb950" font-size="10" font-family="sans-serif">3 assets pinned</text>

        <!-- Annotation -->
        <line x1="79" y1="109" x2="79" y2="140" stroke="#79c0ff" stroke-width="1.5" stroke-dasharray="3,2"/>
        <rect x="44" y="138" width="110" height="14" rx="7" fill="#1f6feb44"/>
        <text x="99" y="149" fill="#79c0ff" font-size="9" font-family="sans-serif" text-anchor="middle">Click asset → detail</text>
      </svg>
      <p class="help-screenshot-caption">Floor plan view showing room layout with assets pinned to their physical location. Click any asset badge to jump directly to its asset record. Rooms are color-coded by type.</p>
    </div>
    """
    return render(request, 'core/help/section.html', {
        'title': 'Locations & WAN',
        'section_id': 'locations',
        'toc': toc,
        'content': content,
        'prev_section': {'title': 'Documentation & KB', 'url_name': 'core:help_documentation'},
        'next_section': {'title': 'API & Integrations', 'url_name': 'core:help_api'},
    })
