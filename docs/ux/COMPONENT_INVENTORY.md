# Component inventory

Date: 2026-11-25. Application version: v3.17.776.
Companion document: [UX_AUDIT.md](UX_AUDIT.md). Target components named here are specified in `SHARED_DESIGN_SYSTEM.md` and `design-tokens.json`; this document does not define them, it records the current state and the direction of travel.

## How the counts were taken

- Template counts are `grep -rl` (files containing the pattern) and, where useful, `grep -rho | wc -l` (occurrences) over `templates/**/*.html` on this branch. The repository has 1002 templates; 703 extend `base.html`, 25 extend `portal/base.html`, the rest are partials, email, PDF and standalone pages.
- A pattern that appears in a template is counted as "used", whether or not the page is reachable. Counts are of markup, not of page views.
- "Browser-measured" means taken from the running demo (80 staff pages, light, 1440 px).
- Nothing here is a plan that has shipped. The "Target" column is the direction recorded for the shared design system and is **planned**.

## 1. Where components are defined

| Layer | File | Size | Role |
|---|---|---|---|
| Framework | `static/vendor/bootstrap/5.3.0` | | Base components and utilities; the main vocabulary in templates. |
| Icons | `static/vendor/fontawesome/6.5.1` | | About 5000 icon uses in 794 templates (almost all `fas`). |
| Palettes | `static/css/themes.css` | 55 KB, 100 variables, 383 hex literals, 301 `!important` | Theme palettes (`default`, `dark`, `dracula`, `green`, `gruvbox`, `monokai`, `nord`, `ocean`, `professional`, `purple`, `solarized`, `sunset`), overrides of Bootstrap components per theme. |
| Legacy tokens and components | `static/css/custom.css` | 44 KB, 38 variables | `:root` names (`--primary-blue`, `--gray-*`, `--spacing-*`, `--shadow-*`), cards, forms, tables, compact pass. |
| Shared layer | `static/css/ui.css` | 49 KB, 56 variables | `--ui-*` tokens, density, page head, filter bar, table wrapper, badges, empty state, field. Loaded after Bootstrap, themes and custom CSS. |
| Shell | `static/css/navigation.css` (35 KB), `command_palette.css`, `dashboard.css`, `client_workspace.css`, `ticket_workspace.css`, `ticket_conversation.css`, `security_overview.css` | | Sidebar, top bar, palette, dashboard widgets, client and ticket workspaces. |
| Responsive | `static/css/mobile.css` | 12.6 KB | Small-screen overrides, skip link, focus ring, print. |
| Portal | `static/css/portal.css` | 17 KB, 55 variables | Separate tokens and components for customer pages. |
| Specialised | `rack_elevation.css`, `geoip-map.css`, `contracts.css`, `contract-sign.css`, `office-editor.css` | | Visual tools; keep. |
| Template includes | `templates/core/_empty_state.html`, `_section_tabs.html`, `_primary_nav.html`, `_shortcut_strip.html`, `_quick_actions.html`, `_settings_menu.html`, `_client_switcher.html`, `_topbar_quick.html`, `_form_org.html`; `templates/includes/favorite_button.html`, `org_selector_warning.html` | 15 shared includes in `core/` and `includes/` | The only real reusable template components. The most-included partial is `core/_empty_state.html` (32 includes); `ticket_routing/_nav.html` (13) and `security_alerts/_so_stat.html` (20) are module-local. |
| Scripts | `static/js/` | 35 files | `app_nav.js`, `command_palette.js`, `responsive_tables.js`, `form_guard.js`, `client-switcher.js` are shell-level; the rest are page-specific. |

There is no component showcase page and no style guide route (`grep` for "showcase" and "styleguide" in templates and `core/urls.py` finds nothing).

## 2. The three token systems and hard-coded colours

| System | File | Names | Count | Notes |
|---|---|---|---|---|
| A. Theme palettes | `themes.css` | `--surface`, `--background`, `--background-alt`, `--text-primary`, `--text-secondary`, `--border-color`, `--primary-color`, `--link-color`, `--success-color`, `--warning-color`, `--danger-color`, `--info-color`, `--focus-ring` and others, set per `[data-theme="..."]` | 100 variables | Owns the colour per theme. Eleven palettes are listed in `themes.css` selectors, four of them dark (`professional`, `dark`, `dracula`, `monokai`, as in `DARK_THEMES` in the capture script). The Phase 67 plan recorded `nord` as wrongly treated as dark; not re-verified here. |
| B. Legacy root | `custom.css:7` | `--primary-blue`, `--primary-blue-hover`, `--accent-blue`, `--success-green`, `--warning-yellow`, `--danger-red`, `--gray-50..900`, `--spacing-xs..xxl`, `--border-radius*`, `--shadow-*`, `--transition-*` | 38 | Colours are literals (not themed); spacing, radius and transition now read `--ui-*`. |
| C. Shared | `ui.css:37` | `--ui-1..12` (spacing 4/8/12/16/24/32/48), `--ui-text*`, `--ui-title`, `--ui-radius*`, `--ui-shadow*`, `--ui-control-h`, `--ui-row-h`, `--ui-card-*`, `--ui-page-bg`, `--ui-surface*`, `--ui-border*`, `--ui-muted`, `--ui-primary`, `--ui-link`, `--ui-focus`, `--ui-success/warning/danger/info` | 56 | Bound to system A in `[data-theme]` (`ui.css:~100`). Intended to be the only vocabulary for new CSS. |
| D. Shell-local | `navigation.css:91` (`--appnav-*`, 12), `portal.css:16` (`--portal-*`, 55), `dashboard.css` (9) | | 76 | Separate by design for navigation and the portal; the navigation palette is a fixed dark navy independent of the theme (`--appnav-bg: #0f1a2b`). |

Literals outside the token files:

| Where | Count | Measured |
|---|---|---|
| Hex colours in `static/css/` | themes 383, custom 94, ui 58, navigation 27, dashboard 37, portal 29 | grep |
| Hex colours (6-digit) in templates | 1335 occurrences in 94 files | grep. Heaviest: `monitoring/rack_detail.html` 64, `vehicles/pickup_diagram*.html`/`van_diagram*.html` (about 400 in 13 files; vehicle artwork, acceptable), `vehicles/vehicle_detail.html` 39, `monitoring/network_closet_detail.html` 37, `monitoring/patch_panel_detail.html` 32, `docs/document_form.html` and `global_kb_form.html` 30 each. |
| Most-used template hex values | `#2d3748` 179, `#718096` 86, `#4a5568` 70, `#dee2e6` 65, `#0d6efd` 52, `#6c757d` 46, `#dc3545` 42, `#1a202c` 35 | grep. `#2d3748` and `#4a5568` are dark greys that are 1.36:1 and 2.17:1 on dark surfaces; they are used in inline styles that assume a light page. |
| `style="..."` attributes | 887 in 301 files (142 set a colour or background in 41 files) | grep. Median 11 per rendered page; max 100 (document create). |
| `<style>` blocks inside templates | 101 in 97 files | grep |
| `rgb()/rgba()` in templates | 199 | grep |
| Bootstrap colour utilities that bypass themes | `text-muted` 713 files, `text-danger` 239, `text-success` 120, `text-warning` 116, `bg-light` 120, `bg-dark` 31, `text-dark` 216, `text-white` 105 | grep; these map to Bootstrap variables, which `themes.css` re-binds with `!important` rules, so they work but cannot be audited from one place. |

Target: one semantic token set (the spec's `design-tokens.json`), `--ui-*` as its CSS expression, `themes.css` reduced to per-theme token values, `custom.css` colours removed, templates free of literal colours except specialised artwork. Planned.

## 3. Page headers and titles

| Variant | Where defined | Templates | Notes |
|---|---|---|---|
| Plain `<h1>` | markup | 108 (`<h1>`), then `mb-4` 21, `mb-0` 18, `h3` 14, `mb-3` 13, `mb-1` 12, `h5 mb-0` 10, `h3 mb-0` 7, `h2` 7, `h3 mb-1` 4 | 254 templates contain an `h1`; 47 of 80 measured pages have none. |
| `h2` used as page title | markup | `<h2 class="mb-0">` 106 templates; `<h2 class="h6 mb-0">` 58 (card titles) | Page title is a second-level heading. |
| Card header as title | `card-header` | settings pages, create forms (client, vault, document) | The first visible text is a card header at 15 px. |
| `.ui-page-head` + `.ui-page-title` + `.ui-page-sub` | `ui.css` | 6 templates (`ui-page-head`), 5 (`ui-page-title`) | The shared component; barely adopted. Includes an actions slot (`ui-page-head__actions`). |
| `.portal-page-title` | `portal.css` | 4 | Portal. |
| Dashboard head | `dashboard.css` | 1 | Compact title + org chip + greeting + actions. |
| Classic dashboard head | `custom.css` | 1 | 32 px title. |
| Breadcrumb rows above titles | Bootstrap `breadcrumb`, `.app-trail` | 348 templates use `breadcrumb` (1602 occurrences, 336 with `aria-label="breadcrumb"`); `.app-trail` is the Phase 67 compact trail inside `base.html` | Two breadcrumb systems co-exist: per-template Bootstrap breadcrumbs and the shell trail. |

Target: one `page-header` component (title as `h1`, optional subtitle, breadcrumb slot, primary action, overflow menu, status chip slot), required on every page, built from `.ui-page-head`. Planned.

## 4. Buttons

| Variant (class) | Files | Occurrences |
|---|---|---|
| `btn-primary` | 543 | 782 |
| `btn-outline-secondary` | 474 | 894 |
| `btn-outline-primary` | 262 | 434 |
| `btn-secondary` | 212 | 244 |
| `btn-outline-danger` | 151 | 198 |
| `btn-danger` | 126 | 138 |
| `btn-success` | 106 | 145 |
| `btn-link` | 73 | 107 |
| `btn-outline-success` | 54 | 81 |
| `btn-warning` | 49 | 60 |
| `btn-info` | 20 | 20 |
| `btn-light` / `btn-dark` | 5 / 1 | 5 / 1 |
| `btn-sm` | 473 | 1548 |
| `btn-lg` | 17 | 23 |
| `.ui-btn` (shared layer) | 1 | 3 |

Measured on rendered pages: the commonest combination is `btn-sm btn-outline-secondary` (183 on 80 pages), then `btn-link btn-sm` (167), `btn-sm btn-outline-primary` (156).

Inconsistencies:
- Primary action colours: blue (`btn-primary`) on most pages, green (`btn-success`) for "Send Note" and some creates, yellow (`btn-warning`) for "Merge Organizations", "Low Stock", "Push to accounting", "Needs Reorder".
- Two destructive styles side by side with Edit: solid red `btn-danger` (documents, vault) and outline red.
- Icon-only buttons: 4576 of 5017 `fas` icons have no `aria-hidden`; 49 of 49 icon-only anchor buttons sampled have neither `aria-label` nor `title`.
- Some buttons attach (Merge / Create Organization) and some are spaced.
- Button text includes icon + label on some pages and label only on others for the same verb ("New status page" without a plus icon; "+ New Ticket").
- Height: `--ui-control-h` 36 px for inputs and standard buttons in compact density; `btn-sm` 31 px; link-style buttons 19 px.

Target: Primary, Secondary, Tertiary (ghost), Danger, Icon button (required label and tooltip), Split button, one size scale (md, sm), loading state, disabled state, one rule for placing the page's primary action. Planned.

## 5. Tables and lists

| Variant | Where defined | Files |
|---|---|---|
| `table` (Bootstrap) | Bootstrap, `custom.css` | 400 files, 1134 occurrences |
| `table-hover` | Bootstrap | 202 |
| `table-sm` | Bootstrap | 234 |
| `table-responsive` | Bootstrap | 196 |
| `table-striped` | Bootstrap | 33 |
| `thead.table-light` | Bootstrap | 129 |
| `table-bordered` | Bootstrap | 10 |
| `table-dark` / `thead.table-dark` | Bootstrap | 5 |
| `.ui-table-wrap` / `.ui-table` | `ui.css` | 7 |
| DataTables (`.DataTable(`) | vendored jQuery plugin, `dataTables.bootstrap5.css` | 16 initialisations (shows "Show N entries", its own search box, its own pager; Racks, Vehicles, Monitors, Processes, Vault, Audit log) |
| Auto-wrapped scroller | `responsive_tables.js` `.table-autowrap` | runtime, any table wider than its parent |
| `list-group` | Bootstrap | 100 |
| Details / disclosure (`<details>`) | markup | 34 |
| Accordion | Bootstrap | 1 |
| Card grids (tile views) | custom | Clients, service catalog, diagrams, integrations, dashboards |

Most common table classes: `table table-hover mb-0` (80), `table table-sm mb-0` (78), `table table-sm` (50), `table table-sm small mb-0` (40), `table table-hover` (39). The class strings differ in at least 20 other ways.

Inconsistencies:
- Two list idioms: server-side filtered lists (108 templates use `method="get"`) and DataTables lists with client-side search and paging (16). They look and behave differently (search box position, page size selector, pager size).
- Row actions: icon buttons in a column (eye, pencil, download), text "View / Edit" stacked, or a single link on the title; no overflow menu.
- Column alignment: money and counts left-aligned in some lists; `.ui-num` exists but is used by 1 template.
- Sort: DataTables headers sort client-side with an arrow; server lists have no sort control except the tickets and assets pages.
- Status, priority and type columns use four different badge styles (section 7).
- No sticky headers, no column chooser, no density toggle per table, no saved column sets (planned).
- Narrow screens: wide tables scroll in a wrapper with no edge cue (UX_AUDIT F-12).

Target: one `data-table` component (header, toolbar slot, sortable headers, row actions, empty state, loading skeleton, pagination, responsive card mode on phones), with DataTables retained only for the large client-side lists until they are server-side. Planned.

## 6. Cards, panels, KPI tiles

| Variant | Files / occurrences |
|---|---|
| `.card` | 755 files, 4920 occurrences (`card mb-3` 499, `card mb-4` 183) |
| `.card-header` | 447 files, 1110 (645 plain; `d-flex justify-content-between align-items-center` 129; `py-2` 125; `bg-danger text-white` 55; `cw-panel__head` 19) |
| `.card-header bg-*` (coloured) | 82 files, 88 |
| `.card-body` | 714 files, 1757 (`p-0` 151) |
| KPI tiles | at least five designs: dashboard KPI row (`dashboard.css`), client workspace KPI row (`client_workspace.css`), inventory centred tiles, CRM metric cards, security overview `_so_stat.html` (20 includes), reports home tiles, `kpi` in 6 templates |
| Widget panels | `.dash-w` (dashboard), `.cw-panel` (client workspace) |

Inconsistencies: card header weight and padding differ by module (15 px bold, 14 px, 18 px); coloured headers (`bg-primary` 13 files, `bg-danger` 55 occurrences) mix with neutral ones; spacing under cards `mb-3` vs `mb-4` is remapped by density tokens in `ui.css` (`--ui-stack-3`, `--ui-stack-4` are both 0.75rem in compact), so the two utility classes mean the same thing visually.

Target: Card (header, body, footer, optional status stripe), Stat tile (label, value, delta, link to filtered records), Panel (widget with actions). Planned.

## 7. Badges and status indicators

| Pattern | Occurrences (rendered strings) |
|---|---|
| `badge bg-secondary` | 343 |
| `badge bg-success` | 263 |
| `badge bg-danger` | 207 |
| `badge bg-warning text-dark` | 193 (plus 50 `badge bg-warning`) |
| `badge text-bg-secondary` | 122 |
| `badge bg-info` | 118 (plus 50 `bg-info text-dark`) |
| `badge bg-primary` | 79 |
| `badge text-bg-success` / `-warning` / `-danger` | 72 / 52 / 43 |
| `.ui-badge` (`--info`, `--neutral`, `--warn`, `--danger`, `--active`) | 9 files, 50 uses |
| Rounded-pill badges | 9 files |
| Status chips in workspaces | own chip classes in the ticket workspace, dashboard (`dash-*`) and client workspace (`cw-*`) |
| Progress bars as status | 28 files (81 uses); white text on `bg-info` measured 1.96:1 |

Two Bootstrap generations of the same thing (`bg-*` and `text-bg-*`) are both present: 359 files use `badge bg-`, 104 use `badge text-bg`. The same word has different colours on different pages (for example "Open", "Sent", "Active" use cyan, blue, green or grey depending on the module). Uppercase transform is applied to most chips. Amber is used both for warning and for "live and public" (status pages).

Target: Status badge with a semantic variant (neutral, info, success, warning, danger, pending) and a mandatory text label, an optional icon, one mapping table from domain status to variant, documented contrast pairs. Planned.

## 8. Alerts, messages, toasts

| Pattern | Where | Count |
|---|---|---|
| Bootstrap alerts | markup | 434 files, 819 uses; `role="alert"` on 59 files (73 uses); dismissible 15 |
| Flash messages | `templates/base.html:203-210` (loop) and `portal/base.html:93` | one pattern; `alert-{{ message.tags }}`; error level tag has no style (UX_AUDIT F-1); close button has no label |
| Toasts | Bootstrap toast markup | 5 files (62 uses); transient messages after AJAX; hidden in screenshots by the capture script |
| Inline help banners | cyan `alert-info` blocks that describe the page | on at least PSA settings, security settings, roles, features, processes, document create |
| Page banners | overdue (dispatch), install readiness (settings centre), default-password warning (`base.html`), update notice | custom each |
| Modal confirmations | `data-confirm` 83 files (116 uses), `confirm()` 19 files (34), Bootstrap modal 25 files (271 `class="modal`), offcanvas 2 | three patterns for "are you sure" |
| Live regions | `aria-live` 19 files, `role="status"` 47 files | mostly empty states and the palette |

Target: Alert (info, success, warning, danger; title, body, action, dismiss), Toast for transient success, Banner for page-wide state, one Confirm dialog with destructive and typed-confirmation variants, a message-level to variant map, announcements via `role="status"`/`"alert"`. Planned.

## 9. Forms and form controls

| Pattern | Files / occurrences |
|---|---|
| `form-control` | 299 files, 1558 |
| `form-select` | 209 / 911 |
| `form-check` | 195 / 1157 |
| `form-switch` | 46 files |
| `form-label` | 326 / 1904 |
| `form-text` (help) | 165 / 559 |
| `input-group` | 43 / 89 |
| `invalid-feedback` | 40 / 311 |
| `is-invalid` | 6 / 35 |
| Django `as_p` / `form.as_*` | 22 / 7 files (unstyled) |
| `form-floating` | 0 |
| Required marker | `required` attribute 180 files; asterisk text in labels on a subset |
| Selects | native; Select2 (vendored) in 3 templates; multi-select native list in vault and roles |
| `.ui-field` / `.ui-field__label` | 3 templates |
| Unsaved-change guard | `form_guard.js` (global) |
| Rich text | Quill (3 templates, from CDN), EasyMDE (markdown), office editors |

Inconsistencies: field widths (full 1140, 800, 660 px); label above control everywhere but help text above on some; labels not associated with controls on 26 pages (111 controls); generated labels ("Os name", "Ram gb"); inline validation messages exist on 40 templates only; `is-invalid` on 6 so most server errors render as a list at the top or not at all; no double-submit disabling documented beyond `form_guard.js`.

Target: Field (label, control, help, error, required), form layout grid (one-column default, two-column for related pairs, max field width by type), sections with real headings, sticky action bar on long forms, shared validation summary, disabled-on-submit, unsaved-changes prompt. Planned.

## 10. Tabs and sub-navigation

| Pattern | Where | Count |
|---|---|---|
| Section tab strip (pill) | `core/_section_tabs.html` (rendered by `base.html`; pill style, icons, right-aligned beside the breadcrumb, "More" overflow) | every section (≈ 40 sections) |
| Sidebar children | `_primary_nav_group.html` | every section (duplicates the tab strip) |
| Bootstrap `nav-tabs` | markup | 21 files |
| Bootstrap `nav-pills` | markup | 4 files |
| `data-bs-toggle="tab"` content tabs | markup | 7 files (46 uses): ticket sub-panels, asset detail, settings |
| Module-local tab includes | `ticket_routing/_nav.html` (13 includes), `api_access/_subnav.html` (8), `office/settings/_layout_start.html` (9), `rmm_permissions/_frame_start.html` (4), `connect/_steps.html` (5) | custom each |
| Settings group icon strip + page tabs | `_settings_menu.html` | settings pages |
| Saved views strip | list pages | tickets, assets, invoices, RMM alerts |

Observed styles: filled-blue pill with icon (section strip), small text tabs (backup monitoring, asset detail), outlined sub-tabs (requisitions), text-only sub-tabs (licensing), underlined tabs (client workspace), button-group "Mine / All customers" (My Work).

Target: one Tabs component (underline tabs for in-page content, pill tabs for navigation between pages, overflow menu, keyboard arrows, `role="tablist"` for content tabs only), and one rule: either sidebar children or the tab strip shows a section's pages. Planned; decision pending (UX_AUDIT section 8).

## 11. Dialogs, menus, tooltips

| Pattern | Count |
|---|---|
| Bootstrap modal | 25 files, 271 `class="modal` occurrences (including repeated per-row modals), 13 files trigger by `data-bs-toggle="modal"` |
| Offcanvas | 2 files |
| `<dialog>` | 0 |
| Command palette dialog | `command_palette.js` + `command_palette.css`; own markup with `role="dialog"`, `aria-modal`, focus trap (measured) |
| Dropdown menus | 19 files (45 `dropdown-menu`); top bar and shell menus are custom |
| Tooltips | `data-bs-toggle="tooltip"` 8 files (28 uses); `title="..."` 261 files (672 uses) — most icon labels are browser tooltips only |
| Popover | 3 files |
| Flyouts (rail) | `app_nav.js` |

Inconsistencies: modal sizes and footers differ per template; per-row modals repeat in markup; titles as `title` attributes are not announced reliably and do not appear on touch.

Target: Dialog (sizes sm/md/lg, header, body, footer with primary and cancel in a fixed order, focus restore, destructive variant), Menu (action menu with keyboard support, used for row actions), Tooltip (supplementary only; never the sole label). Planned.

## 12. Breadcrumbs, navigation chrome

| Component | Where | Notes |
|---|---|---|
| Bootstrap breadcrumb | 348 templates | Roots differ: PSA, Service Desk, Business, Home, Dashboard, Security, Security & Monitoring (UX_AUDIT F-11). |
| Shell trail `.app-trail` | `base.html` | The Phase 67 compact trail with section tabs on the same row. |
| Shortcut strip | `core/_shortcut_strip.html` | Pins moved into the sidebar Overview group. |
| Top bar | `core/_topbar_quick.html`, `base.html` | Icon-only pins, Ctrl K, favourites, recent, search, notifications, help, settings, client switcher, account. |
| Sidebar | `_primary_nav.html`, `navigation.py` | 248 px, rail 64 px, phone drawer. |
| Client switcher | `core/_client_switcher.html`, `client-switcher.js` | Orange pill in the top bar. |
| Application switcher | not present | Planned in the program; must appear only when a peer is configured (standalone rule). |

## 13. Search, filters, pagination, bulk actions

| Component | Variants | Counts |
|---|---|---|
| Global search | top bar field (`Search... ( / )`) + Ctrl K palette + settings search ("Find a setting... ( / )") + sidebar "Jump to..." filter | four search boxes with different scopes on the same page |
| Filter forms | server-side GET forms | 108 files; `ui-filter-bar` 3 files; filter cards with a heading ("Filters", "Filter Assets") on others; inline selects on others |
| Filter state | no chips for active filters; "Clear" link in most | |
| Saved views | one component (`saved-views` strip) | 1 shared template, used on tickets, assets, invoices, RMM alerts; prints an empty-state sentence even with no views |
| Pagination | Bootstrap `pagination` / `page-link` 9 files (38 uses); `page_obj` 5 files; Django paginator 11; DataTables pager 16 | three pager designs; active item unreadable in the default theme |
| Bulk actions | select-all + action buttons | 12 files; separate toolbars on KB (move, audience), security alerts (acknowledge, dismiss, resolve), documents |
| Date and time | native `type="date"` 31 files (53 uses), `datetime-local` 12 (18), `time` 3 (6); no picker library | locale placeholders |

Target: Filter bar (search, facets, active-filter chips, saved views, clear), Pagination (one design, page size, jump), Bulk toolbar (appears on selection, count, actions, confirmation preview for sensitive actions), Date/range control. Planned.

## 14. Empty, loading, error and success states

| State | Components in use | Counts |
|---|---|---|
| Empty | shared `core/_empty_state.html` (32 includes; has `role="status"`, optional two actions, compact mode) | 9 files mention `empty-state`; `.ui-empty` 4 templates; large solid-button variant (IPAM); grey box (network config); `text-center text-muted` lines in 136 files (180 uses); "No ... found" strings in 54 files |
| Loading | `spinner-border` 13 files (50 uses); `fa-spin` 30 files; "Loading" text 19 files; `progress-bar` 28 | no skeletons (`skeleton`, `placeholder-glow`: 0) |
| Error (page) | no themed 404/500; `403.html`, `403_csrf.html`, `firewall_blocked.html` exist | Django default for 404/500 |
| Error (field/form) | `invalid-feedback` 40 files; flash messages | see section 8 |
| Success | flash messages; toasts (5 files) | |
| Partial success | per-feature text | none shared |
| Disabled | `disabled` attribute 113 files | no shared visual, no explanation text convention |

Target: Empty state (existing include, promoted and extended with variants: first-use, no-results, no-permission, integration-not-configured), Skeleton (table, card, text), Inline loading indicator on buttons, Error page (404, 403, 500) in the shell, Result summary for bulk and import operations (succeeded, skipped, failed with reasons). Planned; the empty-state include already meets the empty-state target and should be the starting point.

## 15. Charts and data visualisation

| Component | Where | Notes |
|---|---|---|
| Chart.js 4.4.1 | CDN script in 5 templates: executive scorecard, dashboard detail, SLA trends, margin analytics, wallboard view | Not bundled; `<canvas>` in 8 templates (11 uses); `new Chart(` in 5 files (10). |
| Inline SVG | 14 templates | rack and hardware artwork, sparklines |
| Progress bars | 28 files | used as status and as bars in SLA overview |
| Leaflet maps | vendored 1.9.4; `geoip-map.css` | 3 templates (location map, GeoIP) |
| jsvectormap (world map) | CDN | 2 templates |
| Network diagrams | custom SVG canvas in `hardware` | keep |
| Chart colours | per-chart literals (green and blue lines on the scorecard) | no shared categorical palette, no colour-blind check |

Target: a chart wrapper with a shared categorical and sequential palette that meets 3:1 against the surface, legends and axis titles by default, a data-table fallback for screen readers, and locally bundled libraries. Planned.

## 16. Shell-level components worth keeping as they are

| Component | Reason |
|---|---|
| Ctrl K palette | Meets focus and dialog expectations (UX_AUDIT section 3.7). |
| Icon rail with flyouts | Works at 768 and 1440. |
| Compact dashboard widgets (`.dash-w`) | Registry-driven, per-role layouts. |
| Client workspace panels (`.cw-panel`) | Dense and consistent. |
| Rack elevation, hardware artwork, diagrams, port maps | Specialised visual tools (program section 18). |
| Shared empty state | Already the target pattern. |

## 17. Convergence summary

| Component | Current variants (approx.) | Template files affected | Target | Effort |
|---|---|---|---|---|
| Page header | 8+ | about 700 | `page-header` | L (shared include M; migration L, by section) |
| Button | 12 colour classes, 3 sizes, 2 icon conventions | 543 files for primary | Button set with icon-only variant | M (rules) + L (sweep) |
| Table | 25+ class combinations, DataTables, scroller | 400 | `data-table` | L |
| Card and KPI tile | 5 KPI designs, 8 card header styles | 755 | Card, Stat tile | M |
| Status badge | 4 syntaxes, uneven colour per word | 359 | Status badge + mapping | M |
| Alert and flash | `alert-*`, toasts, banners, 3 confirmation patterns | 434 | Alert, Toast, Banner, Confirm | M |
| Form field | native, Select2, generated labels, 3 widths | 299 | Field + form layout | L |
| Tabs | 6 styles, 2 positions | about 60 | Tabs + one rule | M |
| Dialog | Bootstrap modal in 25 files, 3 confirm patterns | 83 + 19 + 25 | Dialog + Confirm | M |
| Pagination | 3 | about 30 | Pagination | S |
| Filter bar and saved views | 108 filter forms | 108 | Filter bar | M |
| Bulk toolbar | 12 | 12 | Bulk toolbar | M |
| Empty state | 5 | 32 use the shared one | extend shared | S |
| Skeleton and loading | spinners only | 30 | Skeleton + button loading | S |
| Error pages | none themed for 404/500 | 0 | Error pages | S |
| Charts | Chart.js (CDN), SVG, Leaflet | 5 + 14 + 3 | Chart wrapper, bundled | M |
| Icons | Font Awesome 6.5.1 solid plus CDN copies 6.0 and 6.4 in 4 templates | 794 | One icon policy; vendored set only; the program names Lucide or an equivalent as the preferred set (decision pending) | L if the set changes |
| Tokens | 3 systems + shell-local | all | one token set | L |

## 18. Gaps against the program's component list

| Program item (section 4) | Status in the app |
|---|---|
| Inter typography, locally hosted | Not present. System font stack (`--ui-font`). |
| Consistent icon set | Font Awesome is consistent as a set but not as a convention (same concept, different glyphs). |
| 4/8 px spacing | Present as `--ui-1..12`; not enforced in templates (Bootstrap spacing utilities in use). |
| Border radius, borders, elevation | `--ui-radius*`, `--ui-shadow*` present; custom CSS and themes still set their own. |
| Page headers, section headers | Page header component exists in `ui.css`, 6 templates. Section headers: none shared. |
| Buttons, icon-only actions | See section 4; icon-only has no labelled component. |
| Tables | See section 5. |
| Forms | See section 9. |
| Tabs | See section 10. |
| Dialogs | See section 11. |
| Dropdown menus | Bootstrap and custom. |
| Tooltips | Mostly `title` attributes. |
| Status indicators | See section 7. |
| Alerts, notifications, success messages | See section 8; error style defect. |
| Breadcrumbs | See section 12. |
| Search | Four boxes; the palette is the strongest. |
| Charts | See section 15. |
| Filters, pagination, bulk toolbars | See section 13. |
| Date and time controls | Native only. |
| Loading indicators, skeleton loaders | Spinners only; no skeletons. |
| Empty states, error states | Shared empty state exists; no 404/500. |
| Disabled states | Attribute only. |
| Light, dark, system-following theme | Light and dark themes exist; "system-following" is not a profile option (the portal follows the browser; staff pages use the stored theme). |
| Comfortable and compact density | Present (`data-density`). |
| Persistent preferences | Theme, density, rail, pins: persisted per user. |
| Focus indicators, reduced motion | Present but ring contrast is below 3:1 on light (UX_AUDIT F-7); 10 reduced-motion rules in 6 files. |
| Component showcase in both themes and densities | Not present. Planned. |
