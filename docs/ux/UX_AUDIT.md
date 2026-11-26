# UX audit of the current application

Audit date: 2026-11-25. Application version: v3.17.776 (branch `dev/ux-program`, worktree `.wt-ux`).
Scope: program sections 3, 4 (visual problems only), 5, 7 to 11, 16 to 19 and 21.
Companion document: [COMPONENT_INVENTORY.md](COMPONENT_INVENTORY.md) (what the components are, how often each variant is used, and what they should converge on).

Nothing in this document is a plan that has been built. Every item under "Findings" is open unless it says otherwise.

## 1. Method and what was measured

| Item | What was done |
|---|---|
| Instance | The isolated demo instance on `http://127.0.0.1:8099` (SQLite, invented data, version 3.17.776). Nothing was saved; no settings were changed. |
| Users and themes | Light = `demo.tech` (superuser technician, theme "Default Blue"). Dark = `demo.lchen` (superuser staff, theme "Professional Dark"). Both used the same organisation for each page. The two users differ in theme only; roles are equivalent. Portal = `demo.dwhitfield` (customer user), light and dark via the browser colour scheme. |
| Current organisation | Northwind Logistics for service-desk, asset, document and vault pages (it has tickets, assets, documents). Beacon Managed IT (the MSP's own organisation) for billing, contracts, projects and CRM pages, because that is where the demo holds that data. |
| Pages | 82 page definitions: every navigation section's landing page, its main detail page or form (ticket, project, client, asset, document, password, contract, quote, invoice), dashboard (new and classic), ticket workspace, client workspace, settings centre and 9 settings pages, profile, help, favourites, customer portal home and portal new-ticket. |
| Captures | 82 pages x 2 themes at 1440x900 (164 captures, full content height, capped at 3000 px). 29 key pages x 2 themes at 390, 768 and 2560 (174 captures). Plus the Ctrl+K palette (light/dark, 1440 and 390), the phone menu, and the portal in both colour schemes. Captures are in the session scratchpad (`.../scratchpad/ux/audit/shots`), not in the repository. |
| What I looked at | Every 1440 light capture was viewed (two pages per sheet). Dark captures were viewed as 4-up contact sheets for 12 pages plus a pixel check of all 82 for light panels on dark pages; the dark theme was otherwise checked by measurement (contrast on every text node). 390, 768 and 2560 captures were viewed as contact sheets for 14 pages; the rest were checked by measurement only. So "looked at" is complete for light 1440 and partial for dark and responsive. |
| Measurements | A script run on each page in the browser: horizontal overflow, header-stack height (position of the first heading and first content block), heading structure, landmarks, unlabelled form controls, controls with no accessible name, duplicate ids, targets under 24x24 px, inline style count, DOM size, load time to network idle, and a WCAG contrast ratio for every visible text node (computed colour against the composited ancestor background; text over background images is skipped and counted). The first 10 Tab stops were checked for a visible focus indicator on every 1440 page. |
| Axe | axe-core is not present offline (not in `node_modules`, not in the Python environment). No axe scan was run. The checks above are manual equivalents of a subset of axe rules (labels, names, headings, landmarks, duplicate ids, contrast, target size). They do not cover everything axe does (ARIA validity, table headers beyond a `th` check, focus order, reading order). Treat the accessibility section as a floor, not a full audit. A screen reader was not used. |
| Not verified | Real keyboard-only walk-through of every page, focus order, screen-reader output, browser zoom to 200 percent and 400 percent, touch interaction on a device, loading and error states other than those listed, the user-visible effect of `prefers-reduced-motion`. Click counts and task timings are in `WORKFLOW_BENCHMARKS.md` (not this document). |

"Measured" below means taken from the script output or a computed style in the running demo. "Code" means read from a template or stylesheet at the path given. "Estimated" is used where neither applies.

## 2. Summary

The Phase 67 shell is a real improvement and mostly works: one navigation definition, ten sections, icon rail, flyouts, a working Ctrl+K palette, the settings centre, a compact dashboard that fits a 1440x900 screen, and a consistent dark theme. The remaining problems are not in the shell. They are in the 700-odd page templates that still carry their own header, tab, table, button and empty-state markup, and in accessibility basics.

Highest-value findings (full list in section 5):

1. **P0, S.** Server error messages are unstyled. `base.html:205` renders `alert-{{ message.tags }}` and Django's tag for `messages.error()` is `error`; no stylesheet defines `.alert-error` (measured: transparent background, grey border). Failures look like body text.
2. **P0, S.** The skip link is blue text on a blue background when focused (computed 1.3:1 light, 2.1:1 dark). `mobile.css:470` sets white text but a link colour rule wins.
3. **P0, S.** The current page number in every Bootstrap pagination is unreadable in the default light theme (1.3:1) on at least 6 pages (`themes.css:614` styles `.page-link` but only the Professional theme styles the active item).
4. **P0, M.** 111 form controls on 26 of 80 staff pages have no label, `aria-label` or `title` (asset create: 25, security alerts: 22, project detail: 11, ticket create: 9). Filters on lists are the commonest case.
5. **P0, M.** Icon-only buttons and links with no accessible name (users list: 71, audit log: 51, racks, change requests, scheduling), plus the logo link on every page.
6. **P1, M.** 47 of 80 staff pages have no `<h1>`; where one exists it is one of 17 variants. Titles are `h1`, `h2` or a card header depending on the template.
7. **P1, M.** Every section shows its sub-pages twice (sidebar children and the tab strip above the content), and some a third time (Hardware & Ports). Together with saved views, breadcrumb and title, the median page has 232 px of chrome before the first content block (90th percentile 336 px, worst 829 px).
8. **P1, M.** Three vocabularies for the same thing across breadcrumbs, titles and navigation (PSA / Service Desk / Business; Organization / Client / Customer; Processes / Runbooks / Workflows; Documentation / Knowledge Base).
9. **P1, M.** Five scripts and stylesheets load from public CDNs on 14 templates (Chart.js, Quill, SortableJS, jsvectormap, html5-qrcode, Font Awesome 6.0/6.4), against the standalone and no-CDN requirement. Inter is not bundled.
10. **P1, S.** 404 and 500 responses are bare Django pages with no shell and no way back (measured on a logged-in session).

Already meeting the program (do not rebuild): see section 6.

## 3. Per-page record

Columns: where it was seen (URL), layout, consistency and navigation, accessibility, and state coverage. Widths are 1440 light unless stated. "Chrome" is the vertical space above the first content block. Page keys in `code` match the capture file names.

### 3.1 Dashboard, My Work, Service Desk

| Page | Findings |
|---|---|
| `/core/dashboard/` (`dashboard`) | Fits 1440x900 without scrolling (page is viewport-fitted, inner widgets scroll). Seven KPI tiles, five widgets, header actions. Good density. Widgets stretch to the viewport: at 2560x1440 the three upper widgets are about 600 px tall and mostly empty (see `dashboard` at 2560). Icon-only header buttons (4) have titles only. Targets: 13 interactive items under 24 px (the "View all" links at 19 px, widget buttons 25x17). Dark: consistent. |
| `/core/dashboard/?layout=classic` | Old layout still present: 32 px title "Dashboard: Northwind Logistics", no `h1` on the page (measured 0), eight quick-action tiles in a different style from the compact dashboard's header actions, KPI cards with a third style, a map. Light panel area is large in dark theme only because of the map tiles. Phase 67 leftover (kept on purpose as a fallback, no end date). |
| `/psa/my-work/` | Dense, useful; 26 targets under 24 px, longest page here (2849 px light, 7442 px at 390). Mine / All customers switch is a button group that looks like tabs. Run-on explanatory line under the title at 14 px. Two columns collapse to one on phones, putting the alerts column after 5 screens of tickets. |
| `/psa/` tickets | 3470 px tall: no pagination limit seen at 36 rows (loads all). Chrome is about 220 px: tab strip + breadcrumb row, saved-views strip with the empty-state sentence "No saved views yet..." always shown, title, then a 3x4 filter grid. At 390 the table is clipped at the right (Status shows "In Progre"). Row status chips use three different badge styles (priority grey, status coloured, "NEEDS REPLY" solid red). |
| `/psa/new/` | No `h1` (title is a heading in the card). Form is full-width at 1440 (about 800 px wide controls for short values). Priority list shows "P1 - Critical" first with no placeholder, so the default submission is Critical (the form was not submitted; this is the first option shown). 9 unlabelled controls (client, subject, description, queue, status, priority, type, assignee, workflow have visible text but no `for` association). |
| `/psa/t/<number>/` ticket workspace | The strongest page in the app: conversation first, public reply / internal note with distinct colouring, keyboard hints on the tabs, right-hand context column, closeout checklist. Problems: no `h1`; duplicate id `shortcutHelpTitle` (measured); at 1440 the first screen is the header block (title, six chips, two lines of metadata) before the conversation starts at about 380 px; chips use five colours with no legend ("P3 NORMAL", "NEW", "HELPDESK", "UNASSIGNED", "NEEDS REPLY"), and unassigned/needs-reply are conveyed by colour plus text so they are not colour-only. Right column cards have four different header styles. 14 targets under 24 px at 390. Slowest page measured after the system pages (3.4 s to network idle, 2.2 s dark; light run was first after the cache was cold, so treat as an upper bound). |
| `/psa/dispatch/` | No `h1`. Board is readable. Overdue banner is a full-width solid red block that pushes the board down. Wait columns empty for most days at 1440 (demo data). |
| `/scheduling/tasks/` | 28 px title with big filter buttons (Filter, Clear) taller than the table rows. Row backgrounds pink for overdue with link colour on pink: 4.37:1 (measured, `scheduling`). 7 icon-only buttons with no name. |
| `/resourcing/shifts/` | Fine; good empty state with an action. |
| `/psa/projects/`, `/psa/projects/1/` | List: Configure button on its own row above the breadcrumb (three rows of chrome for a one-row table). No `h1`. Detail: Task rows are dense and clear; 11 unlabelled inputs in the add-task row; the "Ticket" button on every row is a tall outlined button that is heavier than the task title. |
| `/psa/catalog/` | Title is `h2`. Breadcrumb root says "PSA" while the sidebar section is "Service Desk". Tile cards have three badge styles per card. |
| `/psa/changes/` | No `h1`. 11 icon-only links (view eye) with no name. Submitted column wraps to two lines. |
| `/processes/` | Title "Processes"; sidebar says "Runbooks" and "Workflows"; breadcrumb says "Service Desk / Workflows / Runbooks". Old DataTables look: "Show 25 entries" selector, oversized Previous/1/Next with an invisible current page. Cyan info banner repeats the page purpose. |

### 3.2 Clients, assets, infrastructure

| Page | Findings |
|---|---|
| `/accounts/organizations/` | Title "Organizations", button "Create Organization", sidebar "Clients" / "All Clients". Merge and Create buttons touch (no gap). |
| `/accounts/organizations/1/` client workspace | Good: compact header, current-client banner, quick actions, tab strip, KPI row, cards. Problems: banner + quick-action row + tab row + KPI row = 385 px before the first card (firstContentTop 385); 33 targets under 24 px (quick actions and card links at 19 px); the "VoIP / Email / O365 / Web / Firewall / Procedures" row is text with tiny icons and no clear purpose; at 390 the quick-action row is clipped. |
| `/accounts/organizations/create/` | No `h1`; the title is a card header. Width: full 1140 px column for fields like "Tax ID". Customer portal colour is a plain text box where a colour control with preview is expected. Section headings are bold labels, not headings. |
| `/onboarding/` | Page title in a bare box; "In progress" card and a right column; fine but a third header style. |
| `/core/customers/1/operations/` | Title "Customer operations: Beacon Managed IT" at 28 px; five empty sections each with "Nothing needs attention here." which fills the page with empty cards. Redirect from `/core/customers/operations/` works. |
| `/assets/` | Chrome about 360 px (views strip, tab strip, title, filter card with 7 fields on two rows, buttons). The table is compact and clear. Row actions are two small icons. Icons in the Type column use red for servers, grey for network: colour carries category without a legend. |
| `/assets/create/` | 25 controls have no label association, and the labels shown are generated from field names ("Os name", "Ip address", "Mac address", "Ram gb", "Cpu"). Full-width single-column inputs. Group headings are small caps labels, not headings. |
| `/assets/33/` asset detail | Illustration (front and rear artwork) takes 440 px before any data; five action buttons wrap onto two rows next to a two-line title. Five duplicate ids from the embedded SVG artwork (`gBodya`, `gEara`, `pBrusha`, `fShadowa`, `gShield`). Tabs are small text tabs (a fourth tab style). Good: sample-artwork and spec-confidence badges say what is approximate. |
| `/hardware/` | Breadcrumb root "Home" (others use the section name), title with organisation in grey, tab strip in a different pill style from other sections, sidebar shows the same six items again. Good empty state with two actions. |
| `/hardware/diagrams/connectivity/` | Canvas page; breadcrumb, title, tab strip, search box, filters, buttons: chrome 230 px. The diagram itself is specialised and should stay as it is (program section 18). |
| `/monitoring/racks/` | DataTables chrome; Actions column icon is clipped at the card edge at 1440 (the edit icon is cut). Current-page "1" unreadable. Name column wraps to three lines while the card has free width. |
| `/backup-monitoring/` | Small text tabs (fifth style), "STALE DATA" badge inline in a sentence, empty table with a one-line state. |
| `/monitoring/ipam/` | Empty state uses a very large solid blue square "+ Add Subnet" button: a different empty-state design from every other page. |
| `/inventory/`, `/vehicles/vehicles/` | Inventory KPI cards are centred with large icons (a third KPI card style). Vehicles list filter shows the text "None" inside the search box (`templates/vehicles/vehicle_list.html:45` prints `{{ search }}` which is `None`); the same on `/monitoring/websites/` (`website_monitor_list.html:17`, `{{ query }}`). |

### 3.3 Business

| Page | Findings |
|---|---|
| `/psa/contracts/`, `/psa/contracts/1/` | Breadcrumb root "PSA"; the sibling "Contract Documents" has root "Business". Title is `h2`. Hours column mixes "2.58 (unlimited)" with "2.83 / 40.00 (37.17 left)". Detail is clear; "ACCEPTED BEFORE E-SIGNATURES WERE REQUIRED" is a solid green chip that reads as a success state while it is a caveat. |
| `/contracts/` | Four metric cards that show "$0.00" and "0 / 0" with a full empty state below it: both an empty state and zeroed KPIs. Filter row uses a native date input showing `mm/dd/yyyy`. |
| `/psa/quotes/`, `/psa/quotes/1/` | Row actions are five unlabelled icon buttons (view, edit, pdf, download, email). Detail title is long and the status chip sits after it; "Copy Sign URL" and "Send for Approval" are plain text buttons next to bordered ones (three button styles in one row). |
| `/psa/invoices/`, `/psa/invoices/1/` | The saved-views strip sits above the breadcrumb here and below it on tickets (inconsistent order). Detail: title wraps over two lines and the action buttons (Edit, View PDF, Download, Email, Push to accounting, Issue Credit Memo) collide with it; "Issue Credit Memo" is red link text next to a yellow solid "Push to accounting". Amounts are left-aligned in the list. 5 unlabelled inputs in Record Payment. |
| `/psa/aging/`, `/payments/` | Fine. Payments has a different header container (white bar with title and button) from aging. |
| `/psa/requisitions/` | Sub-tabs "All / Pending approval / My requisitions" as a fourth tab style. |
| `/licensing/` | Centred narrow layout with different left margin from every other page; title not bold; links in the attention list are long underlined sentences. |
| `/client-health/` | At 1440 the table is clipped on the right (columns "COMP..." and the date are cut) with no scroll cue. Status chips: orange, red, green, grey UNKNOWN; text is present so not colour-only. |
| `/crm/` | Breadcrumb is only "CRM"; large title; tabs on the right under the title. Metric cards in the CRM style (a fourth KPI style). |

### 3.4 Knowledge and Vault

| Page | Findings |
|---|---|
| `/docs/` | Two rows of controls in the header (AI assistant, Organize, Import & export, Upload files, New Office file, New document) and a list/card switch; the page does not explain which is primary. The AI control is shown without an "Optional AI" tag on this page (code: not checked whether it is gated by `psa_ai_enabled`; do not assume). |
| `/docs/create/` | No `h1`. Two large cyan banners (an "Upload files" tip and "Start from template") fill the first screen. Help text under the Editor field contains broken glyphs (tofu boxes where emoji were intended), measured in the screenshot. Editor toolbar is fine. Narrow centred card (about 660 px) while the asset form is full width: form widths are inconsistent. |
| `/psa/kb/` | Breadcrumb root "PSA" but the sidebar section is Knowledge & Vault; "Knowledge Base" is both a Service Desk tab and a Knowledge & Vault item (duplicate destination). Audience badges ("EVERY CUSTOMER", "STAFF ONLY") are heavy and wrap. |
| `/docs/diagrams/` | Fine. |
| `/vault/`, `/vault/21/`, `/vault/create/` | List OK; every demo row shows an amber "WEAK" security badge with an icon and text. Detail: breadcrumb root "Home". Create form is a narrow centred card (third form width) and its bottom buttons are below the first screen. A "Specific users" multi-select is a native multi-select with no search. |
| `/core/secure-notes/` | Fine. New message row is highlighted pale blue; in dark theme this was checked by pixel scan only. |

### 3.5 Security, monitoring, reports

| Page | Findings |
|---|---|
| `/security/overview/` | Good: honest "Collection not verified" text rather than green. Heavy: 17 targets under 24 px, six cards each with its own sub-grid and link row. |
| `/security/events/`, `/security/alerts/`, `/security/incidents/` | No `h1` on all three. Alerts: 22 unlabelled controls (row checkboxes), row actions are three tiny unlabelled icon buttons. Three different breadcrumb roots ("Security & Monitoring", "Security", "Security & Monitoring"). Date inputs show browser placeholders. |
| `/integrations/rmm/alerts/` | Saved-views strip above breadcrumb; strong empty state. |
| `/monitoring/websites/`, `/status/`, `/netconfig/` | Websites: DataTables pager, "None" in the search box. Status pages: "LIVE & PUBLIC" amber solid chips for a good state (amber conventionally means warning). Netconfig: plain grey box as empty state (not the shared empty state). |
| `/reports/` | Quick Actions grid has 40 text links in six colours (green, red, blue, grey) with no grouping; at 390 it is one 40-item column (3522 px page). 6 heading skips. |
| `/reports/exec-scorecard/` | Good: KPI tiles with definitions, "INCOMPLETE" markers instead of invented numbers, a chart with axis titles and a legend. Chart colours are green and blue lines, distinguishable. Chart.js comes from a CDN (see F-13). |
| `/reports/dashboards/`, `/reports/analytics/`, `/reports/wallboards/` | "Api Events" (should be "API events"): label produced by capitalising a key. Analytics event-type badges grey/blue. |

### 3.6 Settings, account, help, portal

| Page | Findings |
|---|---|
| `/core/settings/` (settings centre) | Good: nine groups, 58 pages, "Find a setting", install-readiness check, OPTIONAL AI tag on the AI group. Nothing to rebuild. |
| Settings pages (`/core/settings/general/`, `/psa/`, `/security/`, `/core/security/`, `/accounts/users/`, `/roles/`, `/integrations/`, `/settings/integrations/connected-apps/`, `/core/settings/features/`, `/system-status/`, `/updates/`, `/audit/`) | Up to four navigation layers before the page: sidebar (Administration shows one entry), breadcrumb, group icon strip (eleven icon-only group buttons, only the active one has a text label), page tab strip, then a card header carrying the title. 8 of 12 have no `h1`. Page title sizes vary from a 15 px card header (general, PSA, security settings) to 28 px (users, integrations, audit). Cyan info banner as the first element on PSA, security, roles, features. Roles page is 4020 px tall with no filter. System status is 3700 px (all scheduled tasks inline). Updates page: 4824 DOM nodes (largest), 4.9 s to idle. Security dashboard: 4.2 s (first run). |
| `/accounts/profile/` | Fine. A "DISABLED" two-factor chip in amber with an icon; the same page has "Sign out everywhere" as a solid red button next to ordinary links. |
| `/core/help/` | Fine. The top bar, account menu, sidebar and this page's own tab strip expose four overlapping help destinations (see F-9). |
| `/core/favorites/` | Empty state present. |
| Customer portal `/portal/`, `/portal/new/` | Separate layout and tokens (`portal.css`), dark/light by browser scheme (verified both). Clean, no overflow, no inline styles (0), 163 DOM nodes. Problems: ticket number column wraps ("PSA-2026-" / "000035"); new-ticket page uses 360 px cards in a column on a 1440 screen, leaving the right 60 percent empty; green and amber badges are text plus colour. The portal meets more of the contrast and structure checks than the staff app (0 contrast failures in 67 text nodes). |

### 3.7 Command palette (Ctrl+K), notifications, switcher

| Item | Result |
|---|---|
| Palette open/close | Opens on Ctrl+K from the dashboard at 1440 and 390. `role="dialog"`, `aria-modal="true"`, `aria-labelledby="cmdkTitle"`, an `aria-live` region exists. Measured: focus moves into the dialog; 8 consecutive Tab presses stay inside it; Escape closes it. Focus after close returned to the page container, not to a visible control (it was opened by shortcut, not from the button, so returning to the page is expected; return-to-trigger when opened from the button was not tested). |
| Content | Empty input: Favorites, Recent, quick commands. Typing "tick" showed Commands (Create Ticket) and Pages (nine rows with breadcrumb path) and a "Search everything" row. Record results come from `core:palette_search` after two characters (`static/js/command_palette.js:12`); the "tick" query returned page matches only in the demo, so record results were not exercised here. |
| Dark | Matches. |
| Phone (390) | Full-width sheet; usable. The top-bar search field next to it in the phone menu is white regardless of theme. |

### 3.8 Responsive summary (29 pages at 390, 768, 2560)

| Check | Result |
|---|---|
| Horizontal page overflow | None on any captured page at 390, 768 or 2560 (measured; `responsive_tables.js` wraps wide tables in a scroller). |
| Tables on phone | Still the main problem: tables scroll inside their card with no scroll indicator, so columns appear cut ("Waiting o", "In Progre", "Synolo" at 390 on tickets, assets, invoices, racks). Row actions and the last columns are not discoverable. Estimated: this affects most of the 400 templates with tables. |
| Phone page length | My Work 7442 px, tickets 4924, ticket workspace 6618, client workspace 4727, reports 3522, settings centre 3159. |
| Phone page headers | Title and primary button sit on one row and squeeze each other (Rack Management / Add Rack, Invoices / Billing review / New Invoice). The saved-views strip and the quick-action row wrap into 3 lines. |
| Touch targets under 24x24 px at 390 | My Work 20, client workspace 32, security overview 15, ticket workspace 14, dashboard 12, settings centre 11. Sidebar footer links ("Clientst0r Docs", "Keyboard shortcuts") are 19 px high on every page. |
| 768 | Icon rail by default, content readable. Asset detail's action buttons stack into a full-width column. |
| 2560 | Staff pages cap content at about 1296 px centred in a 2312 px main area: about 500 px empty each side (measured content span 756 to 2052). The dashboard and the settings centre use the full width; widgets stretch tall with little in them. Not wrong, but wasted. Portal content spans 736 to 1824. |

## 4. Cross-cutting measurements (80 staff pages, light, 1440)

| Measure | Value |
|---|---|
| Pages with a horizontal page overflow | 0 |
| Pages with no `<h1>` | 47 of 80 |
| Pages with heading-level skips | 23 |
| Median chrome above first content block | 232 px (90th percentile 336, max 829 on the executive scorecard) |
| `<h1>` top position, median | 136 px (max 268, settings pages) |
| Pages with at least one unlabelled form control | 26 (111 controls in total) |
| Pages with duplicate ids | 2 (ticket workspace 1, asset detail 5) |
| Console errors / failed requests | none on any captured page |
| Load to network idle (demo, loaded machine) | median 1.4 s; over 2.5 s: security dashboard 4.2, system updates 4.9, system status 2.9, ticket workspace 3.4 |
| Median inline `style=` attributes per page | 11 (max 100 on document create) |
| Median DOM nodes | 1714 (max 4824, updates) |
| Text nodes below WCAG AA contrast, light | 3 to 4 per page, all in the top bar and pagination (section 5, F-2 to F-4) |
| Text nodes below WCAG AA contrast, dark | 1 per page (skip link only) |
| Non-colour status | Status chips carry text in all pages reviewed; colour-only dots with no text: 0 found by the script. Tick/cross icons in the users list carry no text (Django staff column shows a tick or a cross glyph only: `users` capture). |
| Focus indicator on first 10 Tab stops | A visible outline or 4 px ring on all (no page failed). The 3 px ring is rgba(13,110,253,.5): about 2.3:1 against white, below the 3:1 that WCAG 2.2 asks for focus indicators (computed; see F-7). |

## 5. Findings, ranked

Priority: P0 = breaks function or accessibility basics or is misleading; P1 = significant usability or consistency cost; P2 = polish. Effort: S = under a day, M = 1 to 3 days, L = more than 3 days. "Impact" is estimated unless marked measured.

### P0

| ID | Finding | Where seen | Effort | Notes |
|---|---|---|---|---|
| F-1 | Error flash messages have no styling. `alert-error` is not a Bootstrap class and no stylesheet defines it. | `templates/base.html:205`; computed style on `/psa/` (background transparent, border grey `rgb(222,226,230)`, vs `alert-danger` solid red). No `MESSAGE_TAGS` setting exists. | S | Map level tags to Bootstrap classes (`MESSAGE_TAGS = {ERROR: 'danger'}`) or add one CSS rule. Add `role="alert"` for error and `role="status"` for success. Add `aria-label` to the close button (49 `btn-close` in templates, 27 without a label). Portal base has its own loop (`templates/portal/base.html:93`) and was not checked. |
| F-2 | Skip link unreadable when focused (blue on blue). | `static/css/mobile.css:470-484`; computed colour `rgb(11,94,215)` on `rgb(13,110,253)` = 1.3:1 light, 2.1:1 dark, measured on all 80 pages. | S | Raise specificity or use `!important` colour; target 4.5:1 and 3:1 focus ring. |
| F-3 | Current page number in pagination unreadable in the default theme. | `static/css/themes.css:614` (`.page-link`) has no `.active` rule except `[data-theme="professional"]` (line 1330); measured 1.3:1 on `/processes/`, `/monitoring/racks/`, `/vault/`, `/audit/`, `/vehicles/vehicles/`, `/monitoring/websites/`. | S | One rule for `.page-item.active .page-link`; better, converge on one pagination component (COMPONENT_INVENTORY section 8). |
| F-4 | 111 form controls without an accessible label on 26 pages. | Measured. Worst: `/assets/create/` 25, `/security/alerts/` 22, `/psa/projects/1/` 11, `/psa/new/` 9, `/psa/invoices/1/` 5, `/security/events/` 4. Typical case: filter selects and search boxes with a placeholder only; Django-rendered forms where the label is visible but not associated. | M | Fix in the shared form and filter-bar partials first (largest effect), then individual templates. Add a test that fails when a visible control has no label. |
| F-5 | Icon-only controls with no accessible name; logo link with no name. | Measured on `/accounts/users/` (71), `/audit/` (51), `/psa/changes/` (11), `/monitoring/racks/` (11), `/scheduling/tasks/` (7), `/security/alerts/` (3). The logo link `a.navbar-brand` has no name on all 80 pages. Code: 49 of 49 sampled `<a class="btn ..."><i ...></i></a>` have neither `aria-label` nor `title`. | M | Shared icon-button component that requires a label (renders `aria-label` and a tooltip). The logo link needs `aria-label`. |

### P1

| ID | Finding | Where seen | Effort |
|---|---|---|---|
| F-6 | Top bar text on the Default Blue theme fails contrast: white on `rgb(61,139,253)` = 3.32:1 for the active pill and account name; "Ctrl K" key cap 3.77:1. Existing users on this theme only; new profiles start on Professional Dark. | Measured, 17 pages for the pill, 80 for the key cap. | S |
| F-7 | Focus ring is `rgba(13,110,253,.5)` 3 px on white: about 2.3:1 for the indicator alone; the `box-shadow` variant on nav links is `rgba(13,110,253,.25)`: lower. WCAG 2.2 AA asks for 3:1. | Measured computed styles on first 10 Tab stops. `static/css/ui.css` already defines `--ui-focus` (`#0d6efd` light, `#8fb4e8` dark); the Bootstrap default ring wins on links and the navbar. | S |
| F-8 | 47 of 80 pages have no `<h1>`; the page title is an `h2`, a card header, or plain text. Where an `h1` exists there are 17 variants (class `mb-4`, `mb-0`, `h3`, `h5`, `ui-page-title`, `portal-page-title`, ...) and sizes from 15 px to 32 px. 23 pages skip heading levels. | Measured; code: 254 templates contain `<h1`, 106 use `<h2 class="mb-0">` as title; only 5 use `ui-page-title`. | M (shared page header), L (migrate all) |
| F-9 | Navigation shown twice or three times. Every section lists its pages as sidebar children and again as a tab strip above the content; Hardware & Ports shows them a third time; the Reports section's 8 sidebar children equal its 6 tab buttons plus "More". Help appears in the top bar, account menu, sidebar footer and as a tab strip (four places, three destinations: `/core/help/`, `/core/docs/`, `/core/documentation/`). "Knowledge Base" is a tab under Service Management and a top-level item under Knowledge & Vault. "Approvals" is in three places. | Section 3; `templates/core/_section_tabs.html`, `_primary_nav.html`. | M |
| F-10 | Too much chrome before content. Up to four stacked rows (saved views, breadcrumb + tabs, title and actions, filter card). Median 232 px, p90 336 px, max 829 px. Settings pages add the icon strip and a second tab row. | Measured. Worst: executive scorecard 829, roles 512, customer-ops/integrations about 356. The saved-views strip prints "No saved views yet..." on every list even when empty. | M |
| F-11 | Terminology. Breadcrumb roots: PSA (contracts, quotes, invoices, aging, KB, catalog, projects, ticket create), Service Desk (tickets), Business (contract documents, payments, client health, licensing), Home (hardware, vault detail, RMM alerts), Dashboard. One object, many names: Organization / Client / Customer (title "Organizations", button "Create Organization", nav "Clients", fields "Customer"); Processes / Runbooks / Workflows; Documentation / Documents / Knowledge Base / KB; Contracts (PSA) / Contract Documents; Reports / Analytics / Dashboards / Wallboards. Generated labels: "Os name", "Ip address", "Ram gb", "Api Events". | Section 3. | M |
| F-12 | Tables clip silently on narrow screens and on some desktop pages (`/client-health/` 1440, `/monitoring/racks/` actions icon). `responsive_tables.js` wraps them in a scroller, but there is no edge fade, no sticky first column and no "scroll" cue. | Captures at 390 and 1440. | M |
| F-13 | External CDNs and no bundled Inter: Chart.js (`cdn.jsdelivr.net`, 5 templates), Quill 2.0.3 (3), SortableJS (3), jsvectormap (2), html5-qrcode (unpkg, 1), Font Awesome 6.0/6.4.0 from two CDNs (4 templates, while 6.5.1 is vendored), diagrams.net embed (1), Google Maps embed (1). Body font is the system stack (`--ui-font`), not Inter. Against program section 4 (no required CDN) and the standalone/offline rule. | Code: grep of `templates/`. | M (vendor the libraries), M (Inter) |
| F-14 | No themed 404 or 500 page; a logged-in user gets Django's bare "Not Found" page with no shell, search or link back. No `templates/404.html`, `500.html`, no `handler404/500`. | Measured on `/psa/t/NOPE/` (status 404, text only). | S |
| F-15 | Three token systems plus hard-coded colours. `themes.css` (100 variables, 383 hex literals, 301 `!important`), `custom.css :root` (38 variables), `ui.css --ui-*` (56) and `navigation.css`, `portal.css` and `dashboard.css` each define their own. Templates contain 1335 hex colours in 94 files, 887 inline `style=` attributes in 301 files, and 101 `<style>` blocks in 97 files. `ui.css` components are used by 9 templates of about 1000. | Code; see COMPONENT_INVENTORY section 2. | L |
| F-16 | Primary, success, warning, info colours in use fail AA with white text: white on `#198754` 4.53 (passes narrowly), on `#ffc107` 1.63, on `#fd7e14` 2.57, on `#0dcaf0` 1.96, on `#6c757d` 4.69. The badges use dark text on amber and cyan, which passes, but the combination is chosen per template (202 uses of `badge bg-warning text-dark`). Several progress bars use white text on cyan (1.96:1, measured on `/core/settings/system-status/`). The program's starter palette also needs adjusted foregrounds: white on `#0D9488` 3.74, `#16A34A` 3.30, `#D97706` 3.19, `#0284C7` 4.10 (computed). | Computed. | S (rule), M (sweep) |
| F-17 | Phase 67 leftovers: classic dashboard still reachable with a different header, KPI and quick-action style; client create, vault create, document create, licensing, CRM, hardware, IPAM, network config, inventory, onboarding and about 380 other templates keep their own header block, form width (full, 800, 660) and empty state. `ui.css` page header, filter bar, table wrapper and badge classes exist and are used by 5 to 9 templates only. | Section 3. | L |
| F-18 | Form layout inconsistency: full-width single column (asset, client, ticket, settings), narrow centred card (vault, document), two-column grid (settings PSA), with long single-value fields stretching to 800 to 1140 px. Required markers: asterisk in label text on some, `required` attribute only on others. 41 templates show `invalid-feedback`; 180 use `required`. | Section 3.2 and 3.4. | M |
| F-19 | Icon-only row actions are small and unlabelled in lists (quotes: five per row, security alerts: three, invoices: four), and use mixed icons for the same action (eye, magnifier, "View" button; pencil, "Edit" text, "edit" glyph). | Captures. | M |
| F-20 | Weak hierarchy on dense pages: reports quick-actions (40 equal links in six colours), asset detail (artwork before data), ticket header (six chips), security overview (six equal cards). | Captures. | M |
| F-21 | Tooling gaps for repeated destructive actions: delete buttons are solid red next to edit on document and vault detail pages (prominence of Delete equals Edit); confirmation is `data-confirm` on 83 templates, `confirm()` JS in 19, Bootstrap modals in 25, so the confirmation experience is three different patterns. | Code and captures. | M |
| F-22 | Status colour semantics are not consistent: amber is used for "live and public" (status pages), "weak" (vault), "disabled" two-factor, "stale data", "incomplete"; green for "accepted before e-signatures were required" (a caveat); cyan for both "sent" and informational type chips. | Captures. | M |
| F-23 | Phone layouts are desktop layouts reflowed: filter grids stay expanded, saved-views strip wraps to 3 lines, title and primary button squeeze, 40-link quick-action column. No mobile-specific list pattern (cards) for tables. | Captures at 390. | L |
| F-24 | Two-thousand-pixel-plus pages without in-page navigation or pagination: tickets 3470 px (36 rows, all rendered), roles 4020, system status 3700, audit log 3587. | Measured. | M |

### P2

| ID | Finding | Effort |
|---|---|---|
| F-25 | Wide-screen use: content capped at 1296 px on 2560 screens with about 500 px empty each side; the dashboard stretches widgets without adding information. | S |
| F-26 | Targets under 24x24 px (WCAG 2.5.8): sidebar footer links 19 px on every page, widget "View all" 19 px, `btn-link` rows, row-action icons. | S |
| F-27 | Duplicate ids: `shortcutHelpTitle` (ticket workspace), five SVG gradient ids in asset artwork. | S |
| F-28 | Empty states: five different designs (shared `core/_empty_state.html` 32 includes; `ui-empty` 4 templates; large solid-button IPAM; plain grey box on network config; "Nothing needs attention" cards on customer operations). | M |
| F-29 | Date and time inputs are native browser controls with locale-dependent placeholders (`mm/dd/yyyy`), 53 `type="date"`, 18 `datetime-local`; no shared range picker for report filters. | M |
| F-30 | Mixed capitalisation and uppercase transforms (all-caps chips, table headers) reduce legibility of long labels such as "CUSTOMER APPROVAL REQUIRED - PENDING, NOT APPROVED WORK YET". | S |
| F-31 | `None` rendered as a value in search inputs on vehicles and website monitors. | S |
| F-32 | Font Awesome (about 5000 icon uses, almost all `fas`) mixes solid, regular and brand styles; no icon policy, so the same concept has different icons (view = eye, magnifier, external-link). | M |
| F-33 | Portal ticket number wraps; portal request page leaves 60 percent of a wide screen empty. | S |
| F-34 | Default priority on the new-ticket form shows "P1 - Critical" first with no placeholder; users who do not change it open a critical ticket. Confirm in the view/form before changing. | S |

## 6. What already meets the program (do not rebuild)

| Program item | Where | Evidence |
|---|---|---|
| One navigation definition, permission-filtered, ten sections, icon rail and flyouts, persistent rail setting, jump-to filter | `core/navigation.py`, `static/js/app_nav.js`, `static/css/navigation.css` | Seen on every page; 768 px defaults to the rail. |
| Settings centre with search and grouping; OPTIONAL AI tag | `/core/settings/` | Captured. |
| Ctrl+K palette: dialog semantics, focus trap, Escape, live region, favourites and recent, record search, permission-filtered, no secret indexing (nothing written to storage, query in a header) | `static/js/command_palette.js`, `core/palette.py` | Measured, section 3.7. |
| Compact dashboard that fits 1440x900, widgets from a registry, per-role layouts, keyboard customisation, density preference | `core/dashboard_widgets.py`, `static/css/dashboard.css` | Measured: no scroll at 1440x900. |
| Professional Dark theme, consistent across 80 pages | `themes.css` | Pixel scan: no light panels on any dark page except map tiles; one contrast failure per page (skip link). |
| Density setting (`data-density` compact/comfortable) | `ui.css:37` onward | Code. |
| Spacing tokens on a 4/8 scale; semantic status tokens | `ui.css` section 1 | Code. |
| Client workspace tab strip, current-client banner, KPI row | `/accounts/organizations/1/` | Captured. |
| Ticket workspace: conversation first, public/internal distinction, timers, closeout, keyboard hints, links | `/psa/t/<n>/` | Captured. |
| Security overview that refuses to show unverified sources as healthy | `/security/overview/` | Captured. |
| Executive scorecard: documented metrics, "INCOMPLETE" instead of invented numbers, chart with legend | `/reports/exec-scorecard/` | Captured. |
| Empty states with an action (shared include) | `templates/core/_empty_state.html` (32 includes) | Seen on shifts, hardware, RMM alerts, favourites. |
| Skip link, `<main id="main-content">`, `lang`, landmarks on every page | `templates/base.html:57,201` | Measured: lang present, one `main` per page, skip link present. |
| No horizontal page overflow at 390, 768, 1440, 2560 | `static/js/responsive_tables.js` | Measured on 29 pages. |
| Reduced-motion rules exist | 10 rules across 6 stylesheets | Code count. |
| Customer portal: own tokens, light and dark by system setting, clean markup, no failures in contrast checks | `static/css/portal.css`, `templates/portal/` | Measured and captured. |
| Specialised visual infrastructure tools (rack elevation, hardware artwork, diagrams, port maps) | assets, hardware, racks | Captured; keep as they are. |
| Documentation with annotated screenshots (Phase 112) | `docs/*.md`, `docs/images/guides/` | Exists; screenshots will need regeneration after UI changes. |

## 7. Proposed first increments (small, shippable)

Each has acceptance criteria that can be checked with a test or a measurement. Detailed scheduling belongs in `UX_ROADMAP.md`.

| # | Increment | Acceptance |
|---|---|---|
| 1 | Message tags and flash markup (F-1) | `messages.error()` renders a visibly red alert in both themes; error/warning get `role="alert"`, others `role="status"`; close buttons have a label; a view test asserts the rendered classes. |
| 2 | Skip link, pagination, focus ring, top-bar contrast (F-2, F-3, F-6, F-7) | Contrast script reports 0 failures on the 80 pages for these elements; skip link readable on focus in both themes; focus ring at least 3:1 on every theme surface. |
| 3 | Label and name lint (F-4, F-5) | A test renders a set of key pages and fails on a visible control without a label/name; baseline of 111 + 160 findings is driven to 0 on the shared partials and the five worst pages. Logo link has a name. |
| 4 | 404/500 pages (F-14) | Logged-in and anonymous 404 render inside the shell with search and a Dashboard link; 500 page is static and does not query the database; no stack trace in either. |
| 5 | Shared page header (F-8) | One include renders `<h1>`, subtitle, primary and secondary actions; 10 high-traffic pages migrated; the audit script reports an `h1` on all of them and chrome height does not increase. |
| 6 | Navigation duplication decision (F-9, F-10) | Decide tab strip vs sidebar children per section; the saved-views strip hides when there are no views and no saved-view action; median chrome on the 80 pages falls from 232 px to 160 px or less (measured by the same script). |
| 7 | Vendor remaining CDN libraries (F-13) | `grep` of `templates/` finds no `https://` script or stylesheet source other than user-configured embeds; pages work with the network blocked (Playwright with external requests aborted). |

## 8. Open questions for the owner

1. Which of the sidebar children or the tab strip should be removed per section (F-9)? Both are Phase 67 work and either could be the keeper.
2. Is "Service Desk" or "PSA" the user-facing name (F-11)? The sidebar and docs say Service Desk; breadcrumbs and several titles say PSA.
3. Should the classic dashboard be retired once the compact one has run for a release (F-17)?
4. Is Inter acceptable as a bundled font (OFL license, about 300 KB for variable woff2)? The program asks for it; no decision is recorded.


### 113.4 label and name check

Checker: `core/a11y_lint.py` (stdlib HTML parser; skips template, hidden, aria-hidden and display:none subtrees). Test: `core/tests/test_a11y_names.py` (add pages to `CHECKED_PAGES`). It counts a visible control with no label, `aria-label`, `aria-labelledby` or `title`, and an `a`/`button` with no text, name attribute or `img alt`. `title` counts as a name here, so row-action buttons that only had `title` are not counted (the audit's browser script did not count them); the user list actions now also have `aria-label` naming the record. Counts are findings on the page rendered for a superuser with a little seeded data, so they can differ from the 2026-11 browser measurements.

Fixed pages (before / after):

| Page | Before | After |
|---|---|---|
| `/core/dashboard/` | 0 | 0 |
| `/psa/` | 0 | 0 |
| `/psa/new/` | 9 | 0 |
| `/assets/create/` | 24 | 0 |
| `/assets/` | 0 | 0 |
| `/security/alerts/` | 7 | 0 |
| `/accounts/users/` | 0 | 0 |
| `/audit/` | 0 | 0 |
| `/monitoring/racks/` | 0 | 0 |
| `/psa/changes/` | 2 | 0 |
| `/scheduling/tasks/` | 2 | 0 |
| `/psa/projects/1/` | 5 | 0 |

Remaining on other navigation landing pages (after; pages not listed have 0):

| Page | Findings |
|---|---|
| `/core/settings/scheduler/` | 152 |
| `/settings/security/technician-access/` | 45 |
| `/hardware/labels/` | 20 |
| `/core/free-consult/` | 7 |
| `/field-ops/dispatch-geo/` | 7 |
| `/psa/routing/alerts/maintenance/` | 7 |
| `/hardware/vlans/` | 6 |
| `/psa/routing/alerts/` | 6 |
| `/psa/routing/` | 6 |
| `/hardware/catalog/` | 5 |
| `/resourcing/shifts/templates/` | 5 |
| `/psa/routing/on-call/` | 5 |
| `/security/events/` | 4 |
| `/inventory/` | 4 |
| `/licensing/mappings/` | 4 |
| `/scheduling/` | 4 |
| `/vehicles/vehicles/` | 4 |
| `/core/settings/psa/` | 3 |
| `/docs/diagrams/` | 3 |
| `/docs/kb/` | 3 |
| `/hardware/` | 3 |
| `/inventory/items/` | 3 |
| `/locations/` | 3 |
| `/monitoring/wans/` | 3 |
| `/psa/problems/` | 3 |
| `/psa/settings/` | 3 |
| `/readiness/repair/` | 3 |
| `/reports/psa/revenue-leakage/` | 3 |
| `/vehicles/inventory/by-vehicle/` | 3 |
| `/vehicles/inventory/global/` | 3 |
| `/vehicles/inventory/` | 3 |
| `/vehicles/inventory/shop/` | 3 |
| `/assets/rma/` | 2 |
| `/core/settings/firewall/` | 2 |
| `/core/install/` | 2 |
| `/core/secure-notes/links-dashboard/` | 2 |
| `/crm/commissions/` | 2 |
| `/crm/leads/` | 2 |
| `/hardware/import/` | 2 |
| `/licensing/renewals/` | 2 |
| `/monitoring/websites/` | 2 |
| `/processes/` | 2 |
| `/reports/psa/effective-hourly-rate/` | 2 |
| `/reports/psa/margin-analytics/` | 2 |
| `/reports/psa/profitability-by-client/` | 2 |
| `/reports/psa/profitability-by-contract/` | 2 |
| `/reports/psa/profitability-by-project/` | 2 |
| `/reports/psa/profitability-by-tech/` | 2 |
| `/reports/psa/sla-trends/` | 2 |
| `/resourcing/capacity/` | 2 |
| `/security/incidents/` | 2 |
| `/settings/security/technician-access/superusers/` | 2 |
| `/vault/access-rules/` | 2 |
| `/assets/serials/` | 1 |
| `/core/help/assets/` | 1 |
| `/core/help/documentation/` | 1 |
| `/core/help/features/` | 1 |
| `/core/help/getting-started/` | 1 |
| `/core/help/` | 1 |
| `/core/help/locations/` | 1 |
| `/core/help/monitoring/` | 1 |
| `/core/help/reports/` | 1 |
| `/core/help/search/` | 1 |
| `/core/help/security/` | 1 |
| `/core/help/vault/` | 1 |
| `/core/help/vehicles/` | 1 |
| `/core/help/workflows/` | 1 |
| `/core/settings/maintenance/` | 1 |
| `/core/search/` | 1 |
| `/crm/opportunities/` | 1 |
| `/docs/lifecycle/analytics/` | 1 |
| `/field-ops/my-location-history/` | 1 |
| `/hardware/cables/` | 1 |
| `/hardware/catalog/coverage/` | 1 |
| `/integrations/rmm/software/` | 1 |
| `/inventory/tools/` | 1 |
| `/payments/` | 1 |
| `/psa/catalog-changes/` | 1 |
| `/psa/kb/` | 1 |
| `/psa/timesheet/` | 1 |
| `/psa/purchase-orders/` | 1 |
| `/psa/projects/` | 1 |
| `/psa/quotes/` | 1 |
| `/psa/releases/` | 1 |
| `/psa/requisitions/` | 1 |
| `/readiness/` | 1 |
| `/reports/asset-lifecycle/` | 1 |
| `/reports/billing-reconciliation/` | 1 |
| `/reports/hardware-margin/` | 1 |
| `/reports/operational-metrics/` | 1 |
| `/reports/quote-conversion/` | 1 |
| `/reports/vendor-cost-history/` | 1 |
| `/scheduling/wallboard/` | 1 |

Not checked (page errors when rendered with seed data): `/accounts/roles/why/` (error TypeError), `/assets/relationships/map/` (error TemplateDoesNotExist), `/core/report-bug/` (HTTP 405), `/psa/ai/inbox/` (HTTP 404).
