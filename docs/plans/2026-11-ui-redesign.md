# UI/UX, navigation and dashboard redesign (Phase 67)

Status: in progress (dev-work, from v3.17.677). Nothing here changes a URL or an
authorization rule; it reorganizes navigation and layout. Hiding a link is
presentation only: every page keeps its own server-side check.

## 1. What the audit found (2026-11-13)

Raw inventories: route walk (2,360 patterns; 306 navigable landing pages), top
bar + settings surfaces, dashboard data sources, visual system. Headlines:

**Navigation**
- The sidebar already has one definition (`core/navigation.py`: PRIMARY groups,
  SETTINGS group, Sections with Tabs, gates, `_PermProbe` mirroring
  `SectionPermissionMiddleware`). Keep it as the single source.
- A second settings hierarchy, `templates/core/_settings_menu.html` +
  `core/settings_groups.py` (5 groups, 33 links, included by 37 templates),
  repeats the sidebar's Settings group under the same five names. 13 pages are
  in both, 20 only in the menu, 7 only in the sidebar. The two disagree on gates
  (Access Management, RMM Permissions, Mobile Apps) and the menu disappears on
  11 of the pages it links to.
- Settings pages stack up to four navigation layers: sidebar Settings group
  (with every tab nested), the section tab strip, a page breadcrumb, the
  settings menu, then the card title.
- Above every page: the shortcut strip (pins, ~45px), the breadcrumb trail and
  the section tabs, with `mt-4`/`mb-3` spacing: ~150px before content.
- The top bar is `navbar-expand-xxl`: below 1400px (1366×768 laptops) search,
  the client switcher and the account menu collapse behind a hamburger. It also
  repeats sidebar destinations (Favorites, Global KB, beta/install/help-us-grow
  which are also in the account menu).
- `ticket_routing/_nav.html` repeats sidebar entries as tabs plus a breadcrumb.
- 35 landing pages have no navigation path at all (Security incidents,
  playbooks, SIEM, threat overview; timesheets and approvals; dispatch heatmap;
  workflow templates/suggestions; analytics overview, MTTA, software
  compliance; field-ops timeclock and settings; accounting; distributors; patch
  panels; port configs; relationship map; vehicle inventory; Office templates;
  vault import; consult requests; secure-note link dashboard; holidays …).
- Role-dependent orphans: members and roles pages are reached only through the
  superuser-only Access Management, so organization Owners/Admins and Customer
  Administrators (who the views admit) have no link. Same for webhooks and the
  organization Office policy.

**Dashboard**
- Server-rendered, no polling; the only fetches are the location map's.
- Overflows 153px at 1366×768, 21px at 1440×900/1600×900.
- No layout, order, hidden-widget or density storage. Quick actions are
  stored per user (`quick_actions_config`) but rendered with feature-flag checks
  only, no permission check.
- No per-role defaults; role templates exist (`accounts/role_seeds.py`).

**Visual**
- Bootstrap 5.3 self-hosted, Font Awesome 6.5. Three token systems
  (themes.css palettes, custom.css `:root`, ui.css `--ui-*`). Shared ui.css
  components exist but only 8 templates use them.
- New users start on the "Navy Space" photo wallpaper with an 85% overlay.
- No density preference; custom.css hard-codes a compact pass.
- `nord` is treated as dark by `toggle_theme` and two stylesheets but it is a
  light palette.

**Security findings to fix on the way**
- `core:webhook_list` needs only a login: any member of an organization
  (customer users included) sees webhook URLs, which for chat services embed
  the token. Create/edit/delete already require `require_admin`.
- Dashboard quick actions are offered without permission checks (the target
  pages still refuse, but the button should not be shown).

## 2. Decisions

- One navigation source: `core/navigation.py`. The settings workspace, the
  sidebar, the top-bar shortcuts and the account menu are all rendered from it.
  `_settings_menu.html` keeps its file name (37 templates include it) but is
  rendered from `navigation.py`; `core/settings_groups.py` becomes a thin
  adapter or goes.
- Sidebar groups: Overview, Operations, Clients & Assets, Business, Tools &
  Automation, Reports & Analytics, then Administration at the foot. Every
  existing entry moves into one of them; groups with no visible entries vanish.
- Settings: nine categories (General, System, Security, Organizations & Access,
  Integrations, Automation, Email & Communications, Features & Modules,
  Maintenance), built from the actual settings pages. The sidebar's
  Administration group lists the categories only; the category's pages appear
  as the settings workspace's secondary navigation, not as sidebar children.
- Top bar: logo, shortcuts (Dashboard, My Work, Tickets, Clients, Devices,
  Projects, Reports; each shown only when its sidebar entry is), search,
  notifications (aggregated from existing counts only), help, settings,
  organization switcher, account menu. Expands at 992px, not 1400px.
- Breadcrumb trail and section tabs share one compact row. Shortcut pins move
  into the sidebar's Overview group (the stored pins are kept).
- Orphans: each of the 35 is either given a section tab / entry, or listed as
  intentionally reached from its parent page. A generated test fails when a new
  landing page has no path.
- Dashboard: a new compact dashboard is the default; the current one stays as
  the "Classic dashboard" (per-user switch, `?layout=classic`) until the new one
  has proven itself. Widgets come from a registry
  (`core/dashboard_widgets.py`), each with its own permission gate, data
  builder (current organization) and default size. Layout per user
  (`UserProfile.dashboard_layout`), role defaults configurable by
  administrators, built-in presets per role. Customization works by keyboard
  (move up/down, show/hide, size) as well as drag.
- Visual: Professional Dark (new theme) is the default for new profiles; new
  profiles start without wallpaper (presets stay available). Existing users keep
  what they chose. Density preference (compact default). Tokens consolidated
  into ui.css and bound per theme.

Groundwork commit (before the parallel work): `accounts/0048` adds
`UserProfile.ui_density`, `dashboard_variant`, `dashboard_layout`, the
`professional` theme choice/default and the `none` background default.

## 3. Work packages

| WP | Scope | Branch |
|---|---|---|
| A Navigation & settings | navigation.py regroup, settings categories, `_settings_menu.html` from navigation, top bar, compact trail + tabs, pins into sidebar, orphans, role-dependent orphans, webhook_list gate, reachability test, navigation-map.md | dev/ui-nav |
| B Dashboard | widget registry, compact viewport-fitting grid, customization, role presets + admin defaults, classic fallback, quick-action permission checks and ordering | dev/ui-dashboard |
| C Visual system | Professional Dark theme, background default, density, token consolidation, nord fix, reduced motion | dev/ui-visual |
| D Validation | role matrix (direct-route denial, sidebar per role), viewport screenshots at 1920×1080 / 1600×900 / 1440×900 / 1366×768 and 125% zoom, regression suite | dev-work after merge |

## 4. Out of scope / later

- Portal (`templates/portal/base.html`) keeps its own layout; a customer
  dashboard for portal users is a later item.
- Rewriting individual pages onto the shared ui.css components beyond the
  dashboard and settings workspace.
