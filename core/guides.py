"""Clientst0r Docs: the guides in docs/*.md, read in the app.

The Markdown files in the repository stay the single source (they are also
what GitHub shows). This module lists the user-facing ones, renders them with
in-app links and images, and searches them section by section.

Only files named in GUIDES are ever read; images are served only from the
documentation image folders (see asset_path).
"""
from __future__ import annotations

import html as html_lib
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

from django.conf import settings
from django.urls import reverse

GITHUB_BLOB = 'https://github.com/agit8or1/clientst0r/blob/main/'


@dataclass(frozen=True)
class Guide:
    slug: str
    path: str          # relative to the repository root
    category: str
    summary: str = ''


CATEGORIES = (
    'Getting started',
    'Everyday work',
    'Business and billing',
    'Access and security',
    'Integrations and API',
    'Install and operate',
)

GUIDES = (
    # Getting started
    Guide('getting-started', 'docs/GETTING_STARTED.md', 'Getting started',
          'Finding your way: dashboard, a customer, a ticket, these docs.'),
    Guide('what-is-clientst0r', 'docs/what-is-clientst0r.md', 'Getting started',
          'What the product is for and how it fits together.'),
    Guide('features', 'FEATURES.md', 'Getting started', 'The full feature list.'),
    Guide('admin-guide', 'docs/ADMIN_GUIDE.md', 'Getting started',
          'First steps for the administrator of a new installation.'),
    Guide('organizations', 'docs/ORGANIZATIONS.md', 'Getting started',
          'Customers (organizations), members and Global View.'),
    Guide('screenshots', 'docs/screenshots.md', 'Getting started',
          'A tour of the application, screen by screen.'),
    Guide('faq', 'docs/faq.md', 'Getting started', 'Frequently asked questions.'),
    # Everyday work
    Guide('my-work', 'docs/MY_WORK.md', 'Everyday work',
          'Your queue, tasks, timesheet, schedule, leave and resources; shifts and scheduled tasks.'),
    Guide('tickets', 'docs/TICKETS.md', 'Everyday work',
          'Ticket views, working a ticket, time, the dispatch board and projects.'),
    Guide('service-management', 'docs/SERVICE_MANAGEMENT.md', 'Everyday work',
          'Service catalog, change requests, problems, releases and approvals.'),
    Guide('workflows', 'docs/WORKFLOWS.md', 'Everyday work',
          'Runbooks, workflow templates and suggested rules.'),
    Guide('support-workflows', 'docs/SUPPORT_WORKFLOWS.md', 'Everyday work',
          'Guided fixes a technician runs on a ticket, with verification and follow-up.'),
    Guide('ticket-routing', 'docs/TICKET_ROUTING.md', 'Everyday work',
          'Queues, routing rules and assignment.'),
    Guide('msp-documentation', 'docs/msp-documentation.md', 'Everyday work',
          'Documenting customers: assets, passwords, knowledge base.'),
    Guide('assets', 'docs/ASSETS.md', 'Everyday work',
          'Onboarding a customer, assets and the asset page, serial search, network scans and IPAM.'),
    Guide('infrastructure', 'docs/INFRASTRUCTURE.md', 'Everyday work',
          'Racks, network closets, patch panels, port configurations and network diagrams.'),
    Guide('inventory-and-vehicles', 'docs/INVENTORY_AND_VEHICLES.md', 'Everyday work',
          'Stock, low stock, tools, service vehicles and van stock.'),
    Guide('hardware-inventory', 'docs/HARDWARE_INVENTORY.md', 'Everyday work',
          'Device artwork, ports, cables, racks, diagrams and labels.'),
    Guide('documents-and-diagrams', 'docs/DOCUMENTS_AND_DIAGRAMS.md', 'Everyday work',
          'Write, organise and version customer documents, keep templates, draw diagrams and import floor plans.'),
    Guide('knowledge-base', 'docs/KNOWLEDGE_BASE.md', 'Everyday work',
          'Write, review, approve and publish articles, keep them current, and check documentation readiness.'),
    Guide('password-vault', 'docs/PASSWORD_VAULT.md', 'Everyday work',
          'Shared credentials, reveal and approval, two-factor codes, My Vault, secure notes and secret links.'),
    Guide('office-documents', 'docs/OFFICE_DOCUMENTS.md', 'Everyday work',
          'Editing Word, Excel and PowerPoint files in the browser.'),
    Guide('pulse-checks', 'docs/PULSE_CHECKS.md', 'Everyday work',
          'Quick health checks for customer sites.'),
    Guide('reports', 'docs/REPORTS.md', 'Everyday work',
          'Generate reports, use the ready-made report catalogue, see what was generated, and check software compliance.'),
    Guide('executive-reporting', 'docs/EXECUTIVE_REPORTING.md', 'Everyday work',
          'Business Overview, the Executive Scorecard, custom dashboards and analytics for owners and managers.'),
    Guide('wallboards-and-pricing-advisor', 'docs/WALLBOARDS_AND_PRICING_ADVISOR.md', 'Everyday work',
          'Build wallboards for a wall-mounted screen, and act on the Pricing Advisor\'s profitability findings.'),
    Guide('security-alerts-and-incidents', 'docs/SECURITY_ALERTS_AND_INCIDENTS.md', 'Everyday work',
          'Receive, triage and ticket security alerts, connect vendors and SIEMs, and handle incidents with playbooks.'),
    Guide('monitoring', 'docs/MONITORING.md', 'Everyday work',
          'Watch customer websites and internet connections, and track domains, certificates and other expirations.'),
    Guide('status-pages-and-config-backups', 'docs/STATUS_PAGES_AND_CONFIG_BACKUPS.md', 'Everyday work',
          'Publish service status to customers and keep a versioned history of network device configurations.'),
    Guide('backup-monitoring', 'docs/BACKUP_MONITORING.md', 'Everyday work',
          'Watching customer backup jobs.'),
    Guide('ai-troubleshoot', 'docs/AI_TROUBLESHOOT.md', 'Everyday work',
          'OPTIONAL AI: guided troubleshooting on a ticket.'),
    # Business and billing
    Guide('billing', 'docs/BILLING.md', 'Business and billing',
          'Time and charges, prepaid hours, invoices and contracts.'),
    Guide('crm', 'docs/CRM.md', 'Business and billing',
          'Leads, opportunities, the pipeline board, campaigns, and how commissions are worked out.'),
    Guide('quotes-and-licensing', 'docs/QUOTES_AND_LICENSING.md', 'Business and billing',
          'Build, send and get quotes e-signed; customer software subscriptions, seats and renewals.'),
    Guide('procurement', 'docs/PROCUREMENT.md', 'Business and billing',
          'Requisitions, purchase orders, receiving, back-orders and vendors.'),
    Guide('client-health', 'docs/CLIENT_HEALTH.md', 'Business and billing',
          'How the Client Health score is built, what the colours mean, and who can change the weights.'),
    Guide('payments', 'docs/PAYMENTS.md', 'Business and billing',
          'Card and direct-debit payments.'),
    Guide('tax', 'docs/TAX.md', 'Business and billing', 'Sales tax.'),
    # Access and security
    Guide('settings-general', 'docs/SETTINGS_GENERAL.md', 'Access and security',
          'General settings, the customer portal, Service Desk and billing defaults, custom fields, tags, holidays.'),
    Guide('security-settings', 'docs/SECURITY_SETTINGS.md', 'Access and security',
          'Sign-in and session rules, technician access, single sign-on, firewall, fail2ban and vulnerability scans.'),
    Guide('ai-automation-and-communications', 'docs/AI_AUTOMATION_AND_COMMUNICATIONS.md', 'Access and security',
          'OPTIONAL AI configuration, scheduled jobs and workflows, and e-mail and SMS settings.'),
    Guide('roles-and-access', 'docs/ROLES_AND_ACCESS.md', 'Access and security',
          'Roles, permissions and access groups.'),
    Guide('technician-access', 'docs/TECHNICIAN_ACCESS.md', 'Access and security',
          'Per-customer technician access and Superuser Approval.'),
    Guide('client-data-protection', 'docs/CLIENT_DATA_PROTECTION.md', 'Access and security',
          'Who sees what, and the limits of each protection.'),
    Guide('azure-sso', 'docs/AZURE_SSO_SETUP.md', 'Access and security',
          'Microsoft (Azure AD / Entra ID) sign-in.'),
    Guide('oidc-sso', 'docs/OIDC_SSO.md', 'Access and security',
          'Single sign-on with OpenID Connect.'),
    Guide('security-policy', 'SECURITY.md', 'Access and security',
          'Reporting a vulnerability and supported versions.'),
    # Integrations and API
    Guide('integrations', 'docs/INTEGRATION_SETUP_GUIDE.md', 'Integrations and API',
          'Connecting PSA, RMM and other systems.'),
    Guide('connected-applications', 'docs/CONNECTED_APPLICATIONS.md', 'Integrations and API',
          'Agit8or Connect and Quick Connect.'),
    Guide('api-access', 'docs/API_ACCESS_CONTROL.md', 'Integrations and API',
          'API keys, scopes and restrictions.'),
    Guide('api-multi-org', 'docs/api-multi-org.md', 'Integrations and API',
          'REST API access across organizations.'),
    Guide('graphql-api', 'docs/API_V2_GRAPHQL.md', 'Integrations and API', 'The GraphQL API.'),
    Guide('browser-extension-api', 'docs/browser-extension-api.md', 'Integrations and API',
          'What the browser extension calls.'),
    Guide('importing-from-it-glue', 'docs/importing-from-it-glue.md', 'Integrations and API',
          'Bringing documentation over from IT Glue.'),
    Guide('importing-from-hudu', 'docs/importing-from-hudu.md', 'Integrations and API',
          'Bringing documentation over from Hudu.'),
    # Install and operate
    Guide('install', 'INSTALL.md', 'Install and operate', 'Native install on Ubuntu / Debian.'),
    Guide('docker', 'docs/docker.md', 'Install and operate', 'Running with Docker Compose.'),
    Guide('auto-update', 'docs/AUTO_UPDATE.md', 'Install and operate',
          'How updates are found and applied.'),
    Guide('upgrade-and-recovery', 'docs/UPGRADE_AND_RECOVERY.md', 'Install and operate',
          'Upgrading, and recovering from a failed upgrade.'),
    Guide('manual-update', 'docs/MANUAL_UPDATE_GUIDE.md', 'Install and operate',
          'Updating from the command line.'),
    Guide('upgrade-notes', 'docs/UPGRADE_NOTES.md', 'Install and operate',
          'Notes for specific upgrades.'),
    Guide('backup-and-restore', 'docs/BACKUP_AND_RESTORE.md', 'Install and operate',
          'Off-host encrypted backups and restore checks.'),
    Guide('seeding-data', 'docs/SEEDING_DATA.md', 'Install and operate',
          'Catalogs, knowledge base and demo samples.'),
    Guide('package-scanner', 'docs/PACKAGE_SCANNER.md', 'Install and operate',
          'Finding pending OS security updates.'),
    Guide('install-app', 'docs/INSTALL_APP.md', 'Install and operate',
          'The phone and desktop app.'),
)

GUIDES_BY_SLUG = {g.slug: g for g in GUIDES}
_BY_PATH = {g.path: g for g in GUIDES}

# Folders images may be served from, relative to the repository root.
ASSET_DIRS = ('docs/images', 'docs/screenshots', 'docs/media')
ASSET_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
               '.gif': 'image/gif', '.webp': 'image/webp', '.svg': 'image/svg+xml'}


def _root() -> Path:
    return Path(settings.BASE_DIR).resolve()


def asset_path(rel: str) -> Path | None:
    """The file for a documentation image, or None if it is not one."""
    if not rel or '\x00' in rel:
        return None
    root = _root()
    candidate = (root / 'docs' / rel).resolve()
    if candidate.suffix.lower() not in ASSET_TYPES or not candidate.is_file():
        return None
    for d in ASSET_DIRS:
        base = (root / d).resolve()
        if candidate.is_relative_to(base):
            return candidate
    return None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()

_HEADING_RE = re.compile(r'<h([1-4]) id="([^"]+)">(.*?)</h\1>', re.S)
_TAG_RE = re.compile(r'<[^>]+>')
_WS_RE = re.compile(r'\s+')


def _strip(html: str) -> str:
    return _WS_RE.sub(' ', html_lib.unescape(_TAG_RE.sub(' ', html))).strip()


def _resolve(guide: Guide, target: str) -> str:
    """Repository-relative path for a link written in `guide`."""
    import posixpath
    base = posixpath.dirname(guide.path)
    return posixpath.normpath(posixpath.join(base, target))


def _rewrite_link(guide: Guide, href: str) -> str:
    if not href or href.startswith(('#', 'http://', 'https://', 'mailto:', '/')):
        return href
    path, _, frag = href.partition('#')
    resolved = _resolve(guide, path)
    target = _BY_PATH.get(resolved)
    if target is not None:
        url = reverse('core:guide', args=[target.slug])
    elif resolved.startswith(tuple(d + '/' for d in ASSET_DIRS)):
        url = reverse('core:guide_asset', args=[resolved[len('docs/'):]])
    elif resolved.startswith('..'):
        return href
    else:
        url = GITHUB_BLOB + resolved
    return url + ('#' + frag if frag else '')


def _rewrite_img(guide: Guide, src: str) -> str:
    if src.startswith(('http://', 'https://', '/', 'data:')):
        return src
    resolved = _resolve(guide, src)
    if resolved.startswith('docs/'):
        return reverse('core:guide_asset', args=[resolved[len('docs/'):]])
    return src


_IMG_RE = re.compile(r'<img([^>]*?)\ssrc="([^"]+)"([^>]*?)\s*/?>')
_A_RE = re.compile(r'<a([^>]*?)\shref="([^"]+)"')
_TITLE_RE = re.compile(r'\stitle="([^"]*)"')


def _figure(guide: Guide, m: re.Match) -> str:
    before, src, after = m.group(1), m.group(2), m.group(3)
    attrs = before + after
    title = _TITLE_RE.search(attrs)
    attrs = _TITLE_RE.sub('', attrs)
    img = f'<img{attrs} src="{_rewrite_img(guide, src)}" loading="lazy" class="guide-img">'
    if title and title.group(1):
        return f'<figure class="guide-figure">{img}<figcaption>{title.group(1)}</figcaption></figure>'
    return img


def _slug(text: str, seen: dict) -> str:
    """GitHub's heading anchor, so links written for GitHub work here too."""
    base = re.sub(r'[^\w\- ]', '', text.strip().lower()).replace(' ', '-')
    n = seen.get(base, 0)
    seen[base] = n + 1
    return base if n == 0 else f'{base}-{n}'


def _markdown_html(raw: str) -> tuple[str, list]:
    """CommonMark (as GitHub renders it) with tables, heading ids and a TOC."""
    from markdown_it import MarkdownIt
    md = MarkdownIt('commonmark', {'html': True}).enable(['table', 'strikethrough'])
    tokens = md.parse(raw)
    seen: dict = {}
    toc: list = []
    for i, tok in enumerate(tokens):
        if tok.type != 'heading_open':
            continue
        inline = tokens[i + 1]
        text = ''.join(c.content for c in (inline.children or [])
                       if c.type in ('text', 'code_inline')) or inline.content
        anchor = _slug(text, seen)
        tok.attrSet('id', anchor)
        level = int(tok.tag[1])
        if level == 2:
            toc.append({'level': 2, 'id': anchor, 'name': text, 'children': []})
        elif level == 3 and toc:
            toc[-1]['children'].append({'level': 3, 'id': anchor, 'name': text,
                                        'children': []})
    return md.renderer.render(tokens, md.options, {}), toc


def _render(guide: Guide) -> dict:
    raw = (_root() / guide.path).read_text(encoding='utf-8', errors='replace')
    body, toc = _markdown_html(raw)
    body = _IMG_RE.sub(lambda m: _figure(guide, m), body)
    body = _A_RE.sub(lambda m: f'<a{m.group(1)} href="{_rewrite_link(guide, m.group(2))}"', body)

    title = guide.slug
    m = re.search(r'^#\s+(.+)$', raw, re.M)
    if m:
        title = m.group(1).strip().strip('#').strip()

    # Search index: one entry per heading, holding the text up to the next.
    sections = []
    matches = list(_HEADING_RE.finditer(body))
    intro_end = matches[0].start() if matches else len(body)
    if body[:intro_end].strip() and not (matches and matches[0].group(1) == '1'):
        sections.append({'heading': title, 'anchor': '', 'text': _strip(body[:intro_end])})
    for i, h in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections.append({
            'heading': _strip(h.group(3)) or title,
            'anchor': '' if h.group(1) == '1' else h.group(2),
            'text': _strip(body[h.end():end]),
        })
    images = len(re.findall(r'<img\s', body))
    return {'title': title, 'html': body, 'toc': toc, 'sections': sections,
            'images': images}


def load(guide: Guide) -> dict:
    """Rendered guide (cached until the file changes)."""
    path = _root() / guide.path
    mtime = path.stat().st_mtime
    with _lock:
        hit = _cache.get(guide.slug)
        if hit and hit[0] == mtime:
            return hit[1]
    data = _render(guide)
    with _lock:
        _cache[guide.slug] = (mtime, data)
    return data


def available():
    """Guides whose file exists, with their rendered title."""
    out = []
    for g in GUIDES:
        if (_root() / g.path).is_file():
            out.append((g, load(g)))
    return out


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r'[\w.+-]+', re.U)


def _terms(q: str) -> list[str]:
    return [t for t in (w.lower() for w in _WORD_RE.findall(q)) if len(t) > 1][:8]


def _snippet(text: str, terms: list[str], width: int = 220) -> str:
    low = text.lower()
    pos = min((p for p in (low.find(t) for t in terms) if p >= 0), default=0)
    start = max(0, pos - width // 3)
    piece = text[start:start + width]
    if start > 0:
        piece = '… ' + piece
    if start + width < len(text):
        piece += ' …'
    return highlight(piece, terms)


def highlight(text: str, terms: list[str]) -> str:
    """HTML-escaped `text` with each term wrapped in <mark>."""
    escaped = html_lib.escape(text)
    if not terms:
        return escaped
    pattern = re.compile('|'.join(re.escape(html_lib.escape(t)) for t in
                                  sorted(terms, key=len, reverse=True)), re.I)
    return pattern.sub(lambda m: f'<mark>{m.group(0)}</mark>', escaped)


def search(q: str, limit: int = 50) -> list[dict]:
    """Sections holding every word of `q`, best first."""
    terms = _terms(q)
    if not terms:
        return []
    hits = []
    for guide, data in available():
        for s in data['sections']:
            head, text = s['heading'].lower(), s['text'].lower()
            title = data['title'].lower()
            if not all(t in head or t in text or t in title for t in terms):
                continue
            score = sum(5 * head.count(t) + 2 * title.count(t) + min(text.count(t), 10)
                        for t in terms)
            if q.strip().lower() in head:
                score += 20
            url = reverse('core:guide', args=[guide.slug]) + '?' + urlencode({'q': q.strip()})
            hits.append({
                'score': score,
                'guide': data['title'],
                'category': guide.category,
                'heading': s['heading'],
                'heading_hl': highlight(s['heading'], terms),
                'snippet': _snippet(s['text'], terms) if s['text'] else '',
                'url': url + (f"#{s['anchor']}" if s['anchor'] else ''),
            })
    hits.sort(key=lambda h: -h['score'])
    return hits[:limit]
