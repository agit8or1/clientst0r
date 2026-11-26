"""Interface components showcase (usability increment 113.11).

One entry per component in docs/ux/SHARED_DESIGN_SYSTEM.md section 8.  The
page (templates/core/component_showcase.html) draws each entry's header from
this list and its demo from the real markup; core/tests/test_component_showcase.py
checks that every heading in that section of the spec has an entry here and a
matching section on the page, so a new spec component cannot be forgotten.

Nothing here touches the database.
"""
from collections import namedtuple

SPEC_FILE = 'docs/ux/SHARED_DESIGN_SYSTEM.md'
SPEC_URL = 'https://github.com/agit8or1/clientst0r/blob/main/' + SPEC_FILE

Component = namedtuple('Component', 'key title spec_heading defined note')

# `spec_heading` is the "###" heading text in section 8 of the spec;
# the spec anchor is its GitHub slug.
COMPONENTS = (
    Component('page-header', 'Page header', 'Page header',
              'templates/core/ (per page) using .ui-page-head, .ui-page-title, .ui-page-sub in static/css/ui.css',
              'One h1 per page, one primary action; others secondary or in an overflow menu. Adopted by only a few templates today.'),
    Component('section-header', 'Section header', 'Section header',
              '.ui-section-title in static/css/ui.css (card headers are used instead on most pages)',
              'A heading outside a card, with an optional count and ghost actions on the right.'),
    Component('buttons', 'Buttons', 'Buttons',
              'Bootstrap .btn (static/vendor/bootstrap) restyled in static/css/themes.css and ui.css; .ui-btn is barely used',
              'One primary per region. Disabled and loading buttons keep their label; loading sets aria-busy.'),
    Component('icon-only-actions', 'Icon-only actions', 'Icon-only actions',
              'Bootstrap .btn with a Font Awesome icon; no dedicated component yet',
              'Every icon-only button needs an accessible name (aria-label) and a tooltip with the same text.'),
    Component('tables', 'Tables', 'Tables',
              '.ui-table-wrap and main .table in static/css/ui.css; sorting is per template; DataTables on 16 pages',
              'Sortable headers are buttons with aria-sort; empty table shows an empty state in the frame.'),
    Component('forms', 'Forms', 'Forms',
              'Bootstrap .form-control, .form-select, .form-check; .ui-field for filter bars; static/js/form_guard.js',
              'Label above, help below, error text with an icon linked by aria-describedby, aria-invalid on the field.'),
    Component('tabs', 'Tabs', 'Tabs',
              'templates/core/_section_tabs.html (navigation tabs); Bootstrap .nav-tabs for in-page tabs',
              'Arrow keys move between tabs; the selected tab is reflected in the URL on real pages.'),
    Component('dialogs', 'Dialogs', 'Dialogs',
              'Bootstrap .modal (static/vendor/bootstrap); confirmations are per template',
              'Focus moves in, is trapped and returns on close; a destructive confirm names the action and count.'),
    Component('dropdown-menus', 'Dropdown menus', 'Dropdown menus',
              'Bootstrap .dropdown-menu; templates/core/_settings_menu.html, _quick_actions.html',
              'Danger items last and separated; Esc closes and returns focus.'),
    Component('tooltips', 'Tooltips', 'Tooltips',
              'Bootstrap tooltip initialised in templates/base.html (data-bs-toggle="tooltip")',
              'A hint only, never the only place essential information lives.'),
    Component('status-indicators', 'Status indicators', 'Status indicators',
              '.ui-badge--* in static/css/ui.css; Bootstrap .badge bg-*; .dash-tone-* on the dashboard',
              'Always a word and an icon besides the colour. Stale external data is neutral with a last-synced time.'),
    Component('alerts', 'Alerts (inline banners)', 'Alerts (inline banners)',
              'Bootstrap .alert; Django messages rendered in templates/base.html with alert-(tag)',
              'role="status" for info and success; role="alert" only for errors raised by an action.'),
    Component('notifications', 'Notifications (toasts)', 'Notifications (toasts and notification centre)',
              'window.appToast() in static/js/app_nav.js and .app-toast in static/css/navigation.css',
              'Errors stay until dismissed. The notification centre (bell) is part of the shell, not this page.'),
    Component('breadcrumbs', 'Breadcrumbs', 'Breadcrumbs',
              'Bootstrap .breadcrumb in 348 templates; the shell trail .app-trail in templates/base.html',
              'Current page last, not a link, aria-current="page", inside nav aria-label="Breadcrumb".'),
    Component('search', 'Search components', 'Search components',
              'static/js/command_palette.js and static/css/command_palette.css (global, Ctrl+K); in-page inputs per template',
              'In-page search shows a clear button and announces its result count.'),
    Component('charts', 'Charts', 'Charts',
              'Dashboard bars (.dash-bars in static/css/dashboard.css) and Chart.js 4.4.1 loaded from a CDN on 5 report pages',
              'Every chart has a table view or text summary; colour never carries meaning alone.'),
    Component('filters', 'Filters', 'Filters',
              '.ui-filter-bar, .ui-field, .ui-applied, .ui-chip in static/css/ui.css',
              'Applied filters are removable chips with Clear all; state belongs in the URL.'),
    Component('pagination', 'Pagination', 'Pagination',
              'Bootstrap .pagination (templates/locations/location_list.html, docs/document_versions.html); DataTables pager on 16 pages',
              'Shows "1-50 of 1,234", previous and next, a page-size select; current page has aria-current.'),
    Component('bulk-action-toolbar', 'Bulk-action toolbar', 'Bulk-action toolbar',
              'Per template (ticket and inventory lists); no shared component',
              'Replaces the filter bar in place; shows the count, Select all, actions and Clear.'),
    Component('date-time', 'Date and time controls', 'Date and time controls',
              'Native input type date, time and datetime-local with Bootstrap .form-control',
              'Relative time under 24 hours with the absolute value in title and datetime attributes.'),
    Component('loading', 'Loading indicators', 'Loading indicators',
              'Bootstrap .spinner-border and .progress',
              'Region loading uses aria-busy and visually hidden text; show nothing for the first 300 ms.'),
    Component('skeletons', 'Skeleton loaders', 'Skeleton loaders',
              'Bootstrap .placeholder / .placeholder-glow (no shared skeleton component)',
              'Match the final layout so nothing shifts; one live Loading label, blocks aria-hidden.'),
    Component('empty-states', 'Empty states', 'Empty states',
              'templates/core/_empty_state.html (32 includes) and .ui-empty in static/css/ui.css',
              'Distinguish nothing yet from no results for these filters.'),
    Component('error-states', 'Error states', 'Error states',
              '.ui-state-error in static/css/ui.css; Bootstrap .alert-danger; templates/403.html',
              'Say what failed, whether data is stale, and offer a retry; the rest of the page keeps working.'),
    Component('success-messages', 'Success messages', 'Success messages',
              'Django messages (alert-success) and window.appToast(message, "success")',
              'Say what happened ("Ticket #1042 closed") and offer Undo when reversible.'),
    Component('disabled-states', 'Disabled states', 'Disabled states',
              'Bootstrap :disabled and .disabled; no aria-disabled convention yet',
              'Use aria-disabled when the reason is explained nearby so keyboard users can reach it.'),
)

BY_KEY = {c.key: c for c in COMPONENTS}


def spec_anchor(heading):
    """GitHub's slug for a markdown heading."""
    import re
    s = heading.lower()
    s = re.sub(r'[^\w\s-]', '', s)
    return re.sub(r'\s', '-', s.strip())


def section_meta():
    """Template context: key -> dict(title, defined, note, spec_url, section_id)."""
    out = {}
    for c in COMPONENTS:
        out[c.key.replace('-', '_')] = {
            'key': c.key,
            'section_id': 'cmp-' + c.key,
            'title': c.title,
            'defined': c.defined,
            'note': c.note,
            'spec_heading': c.spec_heading,
            'spec_url': '%s#%s' % (SPEC_URL, spec_anchor(c.spec_heading)),
        }
    return out


THEMES = (
    ('default', 'Default (light)', False),
    ('professional', 'Professional Dark', True),
    ('dark', 'Dark', True),
    ('dracula', 'Dracula', True),
    ('monokai', 'Monokai', True),
    ('nord', 'Nord', False),
    ('solarized', 'Solarized', False),
    ('gruvbox', 'Gruvbox', False),
    ('ocean', 'Ocean', False),
    ('green', 'Green', False),
    ('purple', 'Purple', False),
    ('sunset', 'Sunset', False),
)
