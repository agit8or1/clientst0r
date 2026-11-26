# Shared MSP design system — v1.0.0

| | |
|---|---|
| Spec version | **1.0.0** (2026-11-25) |
| Tokens | [`docs/ux/design-tokens.json`](design-tokens.json) — the source of truth; this page explains it |
| Validator | `scripts/ux/check_design_tokens.py` (standard library only) · test `core/tests/test_design_tokens.py` |
| Reference implementation | Clientst0r. Implementation state: **planned** — no `--cs-*` CSS variable exists yet (validator: 0 of 306 implemented). The increments in §14 do the migration. |
| Consumers | Rem0te and future MSPZero applications, each adopting it independently (§12) |

The design system is a **development-time specification, not a runtime dependency**. Every application bundles its
own CSS, fonts, icons and scripts. Nothing is loaded from another application's server, from GitHub or from a CDN.
An application that has never heard of any other MSPZero app must look complete with this spec.

Contents: 1 Principles · 2 Current state (measured) · 3 Token model · 4 Colour · 5 Typography and Inter ·
6 Icons · 7 Space, radius, borders, elevation, motion, density, breakpoints, layers · 8 Components ·
9 Layout and shell · 10 Application switcher · 11 Customer branding · 12 Versioning and adoption ·
13 Validator and drift · 14 Migration increments · 15 Not verified / open points

---

## 1. Principles

1. **Semantic first.** Templates and component CSS use role tokens (`--cs-color-text-muted`,
   `--cs-color-status-danger-text`), never raw hex or primitives. Primitives exist only to be aliased.
2. **Accessible by construction.** Every foreground/background pair the spec intends to be used together is listed in
   `contrast-pairs` and checked: 4.5:1 for text (WCAG 1.4.3), 3:1 for large text, UI-component boundaries and
   graphics (1.4.11) and focus indicators. A role that fails cannot ship.
3. **Status never by colour alone** (1.4.1). A status always carries an icon and/or a word; colour reinforces it.
4. **Dense but calm.** Operators look at queues all day. Compact is the default density; hierarchy comes from type
   weight, spacing and one accent colour, not from many coloured cards, gradients or shadows.
5. **One look in light and dark.** Both themes define the same roles. No component has theme-specific markup.
6. **Self-contained.** Each app ships its own assets; the spec can be copied, not linked.
7. **Standalone-complete.** Nothing in the shell reserves space for, advertises or links to an application that is not
   configured (§10).
8. **Change is versioned.** Any token change is a semver change of the spec (§12).

## 2. Current state in Clientst0r (measured 2026-11-25, branch dev/ux-program at 2d26c309)

| Area | What exists | Where |
|---|---|---|
| Token systems | Four overlapping sets: 12 theme palettes (`--primary-color`, `--surface`, …), legacy `:root` names (`--spacing-*`, `--border-radius*`, `--shadow-*`, `--gray-*`), the shared `--ui-*` set (spacing, type, radius, density, neutral fallbacks) and the sidebar's `--appnav-*` | `static/css/themes.css:13`, `static/css/custom.css:7`, `static/css/ui.css:37`, `static/css/navigation.css:91` |
| Portal tokens | A fifth, separate set (`--portal-*`), already light/dark/system-following | `static/css/portal.css:16-57` |
| Themes | 12 selectable colour themes; default for new profiles is Professional Dark. No system-following option in the staff UI (the portal has one) | `accounts/models.py:568`, `templates/base.html:3` |
| Density | `compact` (default) / `comfortable` via `html[data-density]` | `accounts/models.py:701`, `static/css/ui.css:141` |
| Contrast tests | Link colour per theme (`test_theme_contrast.py`); portal accent guarded to 4.5:1 | `core/tests/test_theme_contrast.py`, `core/portal_branding.py:64` |
| Font | System stack (`--ui-font`). Inter is **not vendored**; `portal.css:29` names "Inter" first, so it renders only where a visitor has Inter installed locally | `static/css/ui.css:48`, `static/css/portal.css:29` |
| Icons | Font Awesome Free 6.5.1 vendored (`all.min.css` 100 KB; solid 156 KB, regular 25 KB, brands 117 KB woff2). 796 template files use `fa-` classes, 5,942 occurrences, 453 distinct `fa-*` class names (includes modifiers such as `fa-spin`) | `static/vendor/fontawesome/6.5.1/`, grep of `templates/`, `core/navigation.py`, `static/js/` |
| Icon naming drift | Same concept under FA 5 alias and FA 6 name, e.g. `fa-info-circle` 231 vs `fa-circle-info` 26; `fa-exclamation-triangle` 189 vs `fa-triangle-exclamation` 36; `fa-times` 187 vs `fa-xmark` 7; `fa-edit` 129 vs `fa-pen-to-square` 1; `fa-tachometer-alt` 15 vs `fa-gauge-high` 3. Across the 95 concepts in §6: 1,681 retired-alias uses vs 1,957 canonical | grep, exact-name match |
| External CDNs still loaded | 19 templates load from cdn.jsdelivr.net / cdnjs / unpkg: Chart.js 4.4.1 (5), Quill 2.0.3 (3 templates, although `static/vendor/quill/2.0.3` is vendored), Font Awesome 6.0/6.4 (4: `firewall_blocked.html`, `axes/lockout.html`, `psa/csat_*.html`), SortableJS (3), jsvectormap (2), html5-qrcode (1, unversioned) | e.g. `templates/docs/document_form.html:473`, `templates/reports/dashboard_detail.html:152`, `templates/vehicles/take_inventory.html` |
| z-index | Bootstrap layers plus ad-hoc values up to `100003 !important` (10 rules ≥ 9999) | `static/css/themes.css:500-593`, `static/css/custom.css:841` |
| Breakpoints | Bootstrap's 576/768/992/1200/1400 plus 1440, 1500, 1600, 1800, 1850, 861 in app CSS; sidebar: drawer < 768, rail 768–1199, full ≥ 1200 | `grep @media static/css/*.css`, `static/css/navigation.css:80-89` |
| Reduced motion | Handled per component in 9 places, no global rule | `navigation.css:341,613,730`, `command_palette.css:139-158`, `dashboard.css:513`, `ui.css:898` |
| Application switcher | None in the staff UI templates | grep of `templates/` for switcher / peer markup: no match |
| Customer branding | Staff UI: custom company name and logo (install-wide). Portal: accent per customer (`Organization.portal_primary_color`) or install default (`portal_accent_color`), logo, login background | `core/models.py:84,758,784-812`, `core/portal_branding.py:124-160` |

Consequences: a colour is defined up to four times for one role, so changing "muted text" means editing several files;
CDN loads break the no-CDN rule and the CSP surface; the icon drift makes a later icon-set change expensive.

## 3. Token model

**File format.** `design-tokens.json` follows the W3C Design Tokens Community Group draft: each token is
`{"$value", "$type", "$description"}`; groups nest; `{a.b.c}` is an alias. Types used: `color` (`#RRGGBB`, or
`#RRGGBBAA` for overlays), `dimension` (px), `duration` (ms), `number`, `fontWeight`, `fontFamily` (list),
`cubicBezier` (4 numbers), `shadow` (CSS shorthand string; the DTCG composite form is a possible 1.x addition).

**Top-level sections.** `meta` (version, CSS prefix, contexts) · `program-palette` (the §4 starting values, record
only) · `primitive.color` (raw scales, never used directly in CSS) · `theme.light` / `theme.dark` (`color.*`,
`shadow.*`) · `space` · `font` · `radius` · `border-width` · `motion` · `density` · `breakpoint` · `z-index` ·
`layout` · `icon` · `contrast-pairs`.

**CSS names.** Prefix `--cs-`. The path below the section becomes the name:

| Token path | CSS variable | Where it is defined |
|---|---|---|
| `theme.light.color.text.muted` | `--cs-color-text-muted` | `:root, [data-cs-theme="light"]` |
| `theme.dark.color.text.muted` | `--cs-color-text-muted` | `[data-cs-theme="dark"]`, and under `@media (prefers-color-scheme: dark)` for `:root[data-cs-theme="system"]` |
| `theme.*.shadow.2` | `--cs-shadow-2` | per theme |
| `space.4` | `--cs-space-4` | `:root` |
| `font.size.md` | `--cs-font-size-md` | `:root` |
| `radius.md`, `border-width.focus` | `--cs-radius-md`, `--cs-border-width-focus` | `:root` |
| `motion.duration.fast` | `--cs-motion-duration-fast` | `:root`; `0ms` under `prefers-reduced-motion: reduce` |
| `density.compact.control-height` | `--cs-control-height` | `:root, [data-density="compact"]`; `[data-density="comfortable"]`; `@media (max-width: 767.98px)` (touch) |
| `z-index.dialog` | `--cs-z-dialog` | `:root` |
| `breakpoint.lg` | `--cs-breakpoint-lg` | `:root` (for scripts; media queries use the literal px) |
| `layout.sidebar-width` | `--cs-layout-sidebar-width` | `:root` |

`check_design_tokens.py --emit-css` prints the complete stylesheet these rules produce (306 variables). Other apps may
choose their own prefix (`meta.cssPrefix`) but keep the names after it.

## 4. Colour

### 4.1 Roles (both themes)

| Role | Light | Dark | Use |
|---|---|---|---|
| `bg.page` | `#F4F7FB` | `#0B1220` | App background |
| `bg.surface` | `#FFFFFF` | `#152033` | Cards, tables, dialogs |
| `bg.raised` | `#FFFFFF` (+shadow) | `#1B2F4B` | Menus, popovers |
| `bg.sunken` | `#EEF2F7` | `#0B1220` | Table headers, wells, read-only fields, code |
| `bg.hover` | `#EEF2F7` | `#1B2F4B` | Row / item hover |
| `bg.selected` | `#E8F0FE` | `#1B3358` | Selected row, current menu item |
| `bg.backdrop` | `#0B122099` | `#000000A6` | Dialog / drawer backdrop |
| `text.primary` | `#172033` | `#E2E8F0` | Body, headings |
| `text.secondary` | `#3F4A5C` | `#B8C2D1` | Labels |
| `text.muted` | `#5B6576` | `#94A3B8` | Metadata, help text (still ≥ 4.5:1 on every ground) |
| `text.disabled` | `#8A94A6` | `#7C8799` | Disabled labels (WCAG-exempt; held at 3:1) |
| `text.link` / `link-hover` | `#1D4ED8` / `#1E40AF` | `#93C5FD` / `#BFDBFE` | Links; underlined in running text |
| `text.inverse` | `#FFFFFF` | `#0B1220` | Tooltips (inverse text on a `text.primary` fill) |
| `border.subtle` | `#DCE3EC` | `#24395A` | Card outlines, dividers (decorative) |
| `border.default` | `#C5CED9` | `#2B3A55` | Table grid, group separators |
| `border.strong` | `#7A8597` | `#6B7A92` | Form controls, checkboxes, meaningful outlines (≥ 3:1) |
| `focus.ring` | `#2563EB` | `#60A5FA` | Focus ring, 2px + 2px offset |
| `focus.ring-danger` | `#B91C1C` | `#F87171` | Focus inside an invalid field |
| `action.primary.bg / hover / active / text` | `#2563EB / #1D4ED8 / #1E40AF / #FFFFFF` | same | Primary button |
| `action.secondary.bg / hover / active / text / border` | `#FFFFFF / #EEF2F7 / #E6EBF1 / #172033 / #7A8597` | `#152033 / #1B2F4B / #24395A / #E2E8F0 / #6B7A92` | Default button |
| `action.ghost.hover / active / text` | `#EEF2F7 / #E6EBF1 / #3F4A5C` | `#1B2F4B / #24395A / #B8C2D1` | Toolbar and icon buttons |
| `action.danger.bg / hover / active / text` | `#DC2626 / #B91C1C / #991B1B / #FFFFFF` | same | Destructive button |
| `action.disabled.bg / text / border` | `#E6EBF1 / #5B6576 / #DCE3EC` | `#1B2F4B / #7C8799 / #24395A` | Disabled control |
| `accent.solid / on-solid / text / graphic` | `#0F766E / #FFFFFF / #0F766E / #0D9488` | `#0F766E / #FFFFFF / #2DD4BF / #14B8A6` | Restrained secondary emphasis (active nav, highlights) |
| `status.<role>.solid / on-solid / text / graphic / subtle / border` | see 4.3 | see 4.3 | Badges, alerts, dots, chart marks |
| `nav.*` | navy, identical in both themes | | Sidebar, rail, flyouts (4.4) |
| `chart.1`–`chart.8`, `chart.grid`, `chart.axis` | 4.5 | 4.5 | Categorical series |

Status roles: `success`, `warning`, `danger`, `info`, `pending`, plus `neutral` (unknown / draft / not applicable).
Every status role has `solid` (filled badge/banner), `on-solid` (text on it), `text` (status-coloured text on page,
surface and its own subtle tint), `graphic` (dots, bars, left borders, chart marks), `subtle` (tint) and `border`.

### 4.2 Program colours adjusted

The §4 program palette is kept in `program-palette` for the record. Each colour was checked in the pairings it will
actually be used in; where it failed, a darker (light theme) or lighter (dark theme) step took that role and the
program colour moved to a role it passes.

| Program colour | Problem (computed) | Decision |
|---|---|---|
| Navigation `#14243A` | none: nav text `#CBD5E1` 10.53:1 | kept as `nav.bg` |
| Primary `#2563EB` | white on it 5.17:1 ✓; as text on dark surface 3.16:1 ✗ | kept for fills, light focus ring; dark links use `#93C5FD` (9.05), dark focus ring `#60A5FA` (6.42) |
| Accent `#0D9488` | white on it 3.74:1 ✗ (text) | kept as `accent.graphic` (3.74 on white ✓ 3:1); fill and text use `#0F766E` (5.47) |
| Information `#0284C7` | white on it 4.10:1 ✗; on page 3.81 (text ✗) | kept as light `status.info.graphic` (4.10); fill and text `#0369A1` (5.93) |
| Success `#16A34A` | white on it 3.30:1 ✗; on page 3.07 (barely ≥ 3) | replaced by `#15803D` in fill, text and graphic (5.02 with white; 4.67 on page) |
| Warning `#D97706` | white on it 3.19:1 ✗; on page 2.96 ✗ even for graphics | replaced by `#B45309` (fill 5.02 with white, graphic 4.67 on page) and `#92400E` for text on the amber tint (6.37) |
| Danger `#DC2626` | white on it 4.83 ✓; as text on the red tint 4.36 ✗ | kept for fill and graphic; text `#B91C1C` (5.30 on tint) |
| Pending `#7C3AED` | white 5.70 ✓; on dark surface 2.86 ✗ | kept in light theme and as fill in both; dark text/graphic `#A78BFA` (6.00) |
| Light background `#F4F7FB`, surface `#FFFFFF`, text `#172033` | 15.14 / 16.27 | kept |
| Dark background `#0B1220`, surface `#152033`, text `#E2E8F0` | 15.19 / 13.24 | kept. Surface vs page is only 1.15:1, so dark cards need `border.subtle` to read as separate (decorative, no minimum) |

Fills are the same in both themes (white text on a mid-dark fill): a lighter dark-theme fill would push white text
under 4.5:1. That is why `action.primary.bg-hover` gets **darker** in the dark theme too.

### 4.3 Contrast (computed by the validator)

Selected pairs; the full list (250 pairs, all passing) comes from
`venv/bin/python scripts/ux/check_design_tokens.py --contrast`. Ratios use WCAG 2.x relative luminance.

| Foreground | Background | Light | Dark | Min |
|---|---|---|---|---|
| text.primary | bg.page | `#172033` on `#F4F7FB` **15.14** | `#E2E8F0` on `#0B1220` **15.19** | 4.5 |
| text.primary | bg.surface | `#172033` on `#FFFFFF` **16.27** | `#E2E8F0` on `#152033` **13.24** | 4.5 |
| text.secondary | bg.surface | `#3F4A5C` on `#FFFFFF` **8.95** | `#B8C2D1` on `#152033` **9.08** | 4.5 |
| text.muted | bg.page | `#5B6576` on `#F4F7FB` **5.48** | `#94A3B8` on `#0B1220` **7.30** | 4.5 |
| text.muted | bg.hover | `#5B6576` on `#EEF2F7` **5.24** | `#94A3B8` on `#1B2F4B` **5.27** | 4.5 |
| text.link | bg.surface | `#1D4ED8` on `#FFFFFF` **6.70** | `#93C5FD` on `#152033` **9.05** | 4.5 |
| text.disabled | bg.surface | `#8A94A6` on `#FFFFFF` **3.06** | `#7C8799` on `#152033` **4.50** | 3.0 (project rule) |
| border.strong | bg.surface | `#7A8597` on `#FFFFFF` **3.73** | `#6B7A92` on `#152033` **3.75** | 3.0 |
| focus.ring | bg.page | `#2563EB` on `#F4F7FB` **4.81** | `#60A5FA` on `#0B1220` **7.36** | 3.0 |
| focus.ring | bg.surface | `#2563EB` on `#FFFFFF` **5.17** | `#60A5FA` on `#152033` **6.42** | 3.0 |
| action.primary.text | action.primary.bg | `#FFFFFF` on `#2563EB` **5.17** | same **5.17** | 4.5 |
| action.primary.text | action.primary.bg-hover | `#FFFFFF` on `#1D4ED8` **6.70** | same **6.70** | 4.5 |
| action.danger.text | action.danger.bg | `#FFFFFF` on `#DC2626` **4.83** | same **4.83** | 4.5 |
| accent.on-solid | accent.solid | `#FFFFFF` on `#0F766E` **5.47** | same **5.47** | 4.5 |
| accent.text | bg.surface | `#0F766E` on `#FFFFFF` **5.47** | `#2DD4BF` on `#152033` **8.77** | 4.5 |
| accent.graphic | bg.surface | `#0D9488` on `#FFFFFF` **3.74** | `#14B8A6` on `#152033` **6.56** | 3.0 |
| status.success.on-solid | status.success.solid | `#FFFFFF` on `#15803D` **5.02** | same **5.02** | 4.5 |
| status.success.text | status.success.subtle | `#15803D` on `#DCFCE7` **4.57** | `#4ADE80` on `#0F2A1D` **8.80** | 4.5 |
| status.success.graphic | bg.surface | `#15803D` on `#FFFFFF` **5.02** | `#4ADE80` on `#152033` **9.37** | 3.0 |
| status.warning.on-solid | status.warning.solid | `#FFFFFF` on `#B45309` **5.02** | same **5.02** | 4.5 |
| status.warning.text | status.warning.subtle | `#92400E` on `#FEF3C7` **6.37** | `#FBBF24` on `#2E2410` **9.14** | 4.5 |
| status.warning.graphic | bg.surface | `#B45309` on `#FFFFFF` **5.02** | `#FBBF24` on `#152033` **9.78** | 3.0 |
| status.danger.on-solid | status.danger.solid | `#FFFFFF` on `#DC2626` **4.83** | same **4.83** | 4.5 |
| status.danger.text | status.danger.subtle | `#B91C1C` on `#FEE2E2` **5.30** | `#F87171` on `#301619` **6.05** | 4.5 |
| status.danger.graphic | bg.surface | `#DC2626` on `#FFFFFF` **4.83** | `#F87171` on `#152033` **5.90** | 3.0 |
| status.info.on-solid | status.info.solid | `#FFFFFF` on `#0369A1` **5.93** | same **5.93** | 4.5 |
| status.info.text | status.info.subtle | `#0369A1` on `#E0F2FE` **5.17** | `#38BDF8` on `#0F2433` **7.42** | 4.5 |
| status.info.graphic | bg.surface | `#0284C7` on `#FFFFFF` **4.10** | `#38BDF8` on `#152033` **7.62** | 3.0 |
| status.pending.on-solid | status.pending.solid | `#FFFFFF` on `#7C3AED` **5.70** | same **5.70** | 4.5 |
| status.pending.text | status.pending.subtle | `#6D28D9` on `#EDE9FE` **5.98** | `#A78BFA` on `#251A40` **5.93** | 4.5 |
| status.pending.graphic | bg.surface | `#7C3AED` on `#FFFFFF` **5.70** | `#A78BFA` on `#152033` **6.00** | 3.0 |
| nav.text | nav.bg | `#CBD5E1` on `#14243A` **10.53** | same | 4.5 |
| nav.text-muted | nav.active-bg | `#94A3B8` on `#133A44` **4.77** | same | 4.5 |
| nav.active-text | nav.active-bg | `#5EEAD4` on `#133A44` **8.27** | same | 4.5 |
| nav.active-indicator | nav.bg | `#2DD4BF` on `#14243A` **8.40** | same | 3.0 |
| nav.focus | nav.bg | `#7DD3FC` on `#14243A` **9.38** | same | 3.0 |

Tightest passing margins (watch these when editing): light `status.success.text` on its tint 4.57; light
`text.disabled` 3.06; dark `border.strong` on `bg.raised` 3.10.

Focus: a 2px ring with a 2px offset sits on the surrounding surface, so the ring is measured against page, surface and
raised, not against the control fill. This also meets the WCAG 2.2 focus-appearance guidance (2.4.13, AAA) for area
and contrast.

### 4.4 Navigation

`nav.bg #14243A` (program colour) in both themes, `bg-raised`/`hover #1B2F4B`, `border #24395A`, `text #CBD5E1`,
`text-muted #94A3B8`, `text-strong #F8FAFC`, `active-bg #133A44`, `active-text #5EEAD4`, `active-indicator #2DD4BF`
(3px bar), `focus #7DD3FC`. Active state = indicator bar + `active-text` + `aria-current="page"`, never colour alone.
The navy sidebar is a deliberate constant: it identifies the shell in both themes and leaves the accent free.

### 4.5 Charts

Categorical order (light / dark): 1 blue `#2563EB`/`#60A5FA` · 2 teal `#0D9488`/`#2DD4BF` · 3 amber
`#B45309`/`#FBBF24` · 4 violet `#7C3AED`/`#A78BFA` · 5 pink `#DB2777`/`#F472B6` · 6 cyan `#0E7490`/`#22D3EE` ·
7 lime `#4D7C0F`/`#A3E635` · 8 grey `#64748B`/`#94A3B8`. Each ≥ 3:1 on page and surface in its theme.
Rules: categorical colours never mean good/bad — use `status.*.graphic` for that; more than 8 series → group into
"Other"; every series is also identified by a legend label or direct label (and by marker shape or dash on line charts
with more than 3 series); gridlines `chart.grid` (decorative), axis text `chart.axis` (4.5:1); every chart has a text
equivalent (table toggle or summary). Chart.js must be vendored (it is loaded from a CDN today, §2).

## 5. Typography and Inter

| Token | Size / line height | Use |
|---|---|---|
| `font.size.xs` | 12 / 16 | Captions, counts, timestamps |
| `font.size.sm` | 13 / 18 | Secondary table lines, metadata |
| `font.size.md` | 14 / 20 | Body, table cells, controls (base) |
| `font.size.lg` | 16 / 24 | Card / section headings; body text on phones |
| `font.size.xl` | 18 / 24 | Dialog titles, sub-page titles |
| `font.size.2xl` | 22 / 28 | Page title in compact density and on phones |
| `font.size.3xl` | 26 / 32 | Page title in comfortable density |
| `font.size.kpi` | 28 / 32 | KPI values, tabular numerals |

Weights: 400 body, 500 labels/buttons/table headers, 600 headings and KPI values, 700 rarely (single emphasis).
Numbers in tables, KPIs and timers use `font-variant-numeric: tabular-nums`. Monospace (`font.family.mono`) for IPs,
MACs, serials, hostnames, code and revealed secrets. Body copy max ~72ch (`layout.content-max-reading`).
Headings follow document order (one `h1` per page = page title); size never substitutes for a heading level.

**Inter: not vendored today (§2).** Plan (increment I-2, not done):

- Source: the official Inter release (the `rsms/inter` project's GitHub releases, `Inter-4.x.zip`), or the Inter
  family download from Google Fonts. Licence: SIL Open Font License 1.1 — allows bundling and self-hosting; ship
  `LICENSE.txt` next to the files.
- Files: `static/vendor/inter/<version>/InterVariable.woff2` and `InterVariable-Italic.woff2` (one variable file per
  style covers 400–700; measure size when vendoring, and consider a Latin + Latin-1 + Latin Extended-A subset because
  the UI ships en/es/fr/de/pt-BR).
- `@font-face { font-family: Inter; src: url(...) format("woff2"); font-weight: 100 900; font-display: swap; }`,
  preloaded from `base.html` and the portal base. No request to any external host.
- Fallback stack stays (`system-ui`, …) so the page lays out correctly if the file is missing. Accept a small
  metric shift; optionally add `size-adjust` on a local fallback face.

## 6. Icons

**Decision: keep Font Awesome Free 6 (vendored 6.5.1) as Clientst0r's icon set for spec 1.x; do not migrate to Lucide
now.** Lucide (ISC licence) is an equally acceptable choice for a new application, and the semantic map carries a
Lucide name for every concept so Rem0te or a new app can pick either and still show the same picture for the same idea.

| | Font Awesome Free 6.5.1 (keep) | Lucide (alternative) |
|---|---|---|
| Licence | Icons CC BY 4.0, fonts SIL OFL 1.1, code MIT (`static/vendor/fontawesome/6.5.1/LICENSE.txt:13,21,121`) — attribution is in the shipped CSS/licence file | ISC |
| State in Clientst0r | Vendored, used in 796 template files / 5,942 occurrences / 453 class names, plus icon strings in `core/navigation.py` and `static/js/` | Not present |
| Delivery | Icon font + 100 KB CSS; loads ~180 KB of woff2 for solid+regular (brands 117 KB only where brand icons appear) | Inline SVG or an SVG sprite; per-icon cost; best a11y and rendering |
| Brand logos | Has `fa-brands` (used for integration logos) | No brand icons — logos would need separate SVGs |
| Migration cost to Lucide | — | Estimated: a `{% icon %}` tag + sprite build, then ~800 templates and the JS that builds icon markup; ~95 concept mappings plus ~360 long-tail names to map by hand; visual regression review of every page in both themes. Multi-release, high churn, little user-visible gain. |

What changes instead (increment I-5, planned): a semantic icon helper (`{% icon "ticket" %}` → `<i class="fa-solid
fa-ticket" aria-hidden="true"></i>`), canonical FA 6 names everywhere (retire the FA 5 aliases listed below), and the
`navigation.py` entries switched to concept keys. After that, swapping the icon set is a change in one place.

Icon rules: decorative icons `aria-hidden="true"`; an icon-only control has an accessible name (`aria-label`) and a
tooltip with the same text; status icons pair with a word or are announced; sizes 16px in controls and tables, 14px in
dense metadata, 20px in empty states/headers; icons inherit `currentColor`; one style (solid) — regular only for the
"off" state of a toggle (favourite star).

Semantic map (95 concepts; source `icon.concepts` in the JSON; FA names verified against the vendored stylesheet by the
validator; Lucide names checked by name only — confirm against the Lucide release an app adopts):

<!-- icon-map:start (generated from design-tokens.json icon.concepts) -->
| Concept | Font Awesome 6 (`fa-`) | Lucide | Retire (FA 5 alias) | Use |
|---|---|---|---|---|
| `nav-dashboard` | `gauge-high` | `layout-dashboard` | tachometer-alt | Dashboard group |
| `nav-my-work` | `clipboard-check` | `clipboard-check` | – | My Work group |
| `nav-service-desk` | `headset` | `headset` | – | Service Desk group |
| `nav-customers` | `building` | `building-2` | – | Customers / Clients group and a customer record |
| `nav-assets` | `server` | `server` | – | Assets and Network group |
| `nav-business` | `briefcase` | `briefcase` | – | Business group |
| `nav-knowledge` | `book-open` | `book-open` | – | Knowledge and Vault group, KB article |
| `nav-security` | `shield-halved` | `shield` | shield-alt | Security and Monitoring group |
| `nav-reports` | `chart-column` | `chart-column` | chart-bar | Reports group |
| `nav-admin` | `gear` | `settings` | cog | Administration / settings |
| `app-switcher` | `grip` | `grip` | – | Application switcher button (only when a peer is configured) |
| `ticket` | `ticket` | `ticket` | ticket-alt | Ticket |
| `device` | `desktop` | `monitor` | – | Managed device / workstation |
| `laptop` | `laptop` | `laptop` | – | Laptop |
| `server-asset` | `hard-drive` | `hard-drive` | – | Storage / disk |
| `network` | `network-wired` | `network` | – | Network, subnet, switch |
| `wifi` | `wifi` | `wifi` | – | Wireless |
| `printer` | `print` | `printer` | – | Printer / print action |
| `credential` | `key` | `key-round` | – | Password / credential in the vault |
| `locked` | `lock` | `lock` | – | Locked, restricted, secret |
| `user` | `user` | `user` | – | Single user / contact |
| `users` | `users` | `users` | – | Users, team, group |
| `role` | `user-shield` | `user-cog` | – | Role, permission, access group |
| `integration` | `plug` | `plug` | – | Integration / connected application |
| `automation` | `bolt` | `zap` | – | Automation, workflow trigger |
| `module` | `puzzle-piece` | `puzzle` | – | Module / feature toggle |
| `ai` | `robot` | `bot` | – | OPTIONAL AI action (only when psa_ai_enabled) |
| `remote-session` | `terminal` | `terminal` | – | Remote shell / session |
| `invoice` | `file-invoice-dollar` | `receipt-text` | – | Invoice |
| `contract` | `file-contract` | `file-pen-line` | – | Contract / agreement |
| `payment` | `credit-card` | `credit-card` | – | Payment method |
| `procurement` | `truck` | `truck` | – | Purchase order, shipping |
| `inventory` | `boxes-stacked` | `boxes` | – | Stock / inventory |
| `vehicle` | `car` | `car` | – | Vehicle |
| `document` | `file-lines` | `file-text` | file-alt | Document |
| `folder` | `folder` | `folder` | – | Folder / category |
| `attachment` | `paperclip` | `paperclip` | – | Attachment |
| `comment` | `comment` | `message-square` | – | Reply / note / comment |
| `monitoring` | `heart-pulse` | `heart-pulse` | – | Uptime / health check |
| `trend` | `chart-line` | `chart-line` | – | Trend / time series |
| `schedule` | `calendar-days` | `calendar-days` | calendar-alt | Calendar, schedule, date picker |
| `time` | `clock` | `clock` | – | Time entry, SLA timer, timestamp |
| `history` | `clock-rotate-left` | `history` | history | Audit trail, recent records |
| `notification` | `bell` | `bell` | – | Notifications |
| `favorite` | `star` | `star` | – | Favorite (regular = off, solid = on) |
| `pin` | `thumbtack` | `pin` | – | Pin to strip / sidebar |
| `help` | `circle-question` | `circle-help` | question-circle | Help and documentation |
| `email` | `envelope` | `mail` | – | Email |
| `phone` | `phone` | `phone` | – | Phone |
| `location` | `location-dot` | `map-pin` | map-marker-alt | Site / address |
| `home` | `house` | `house` | home | Home / portal start |
| `inbox` | `inbox` | `inbox` | – | Queue / inbox |
| `tasks` | `list-check` | `list-checks` | tasks | Task list, checklist |
| `tag` | `tag` | `tag` | – | Tag / label |
| `bookmark` | `bookmark` | `bookmark` | – | Saved view |
| `action-add` | `plus` | `plus` | – | Create / add |
| `action-edit` | `pen-to-square` | `square-pen` | edit | Edit a record (use pen for inline field edit) |
| `action-edit-inline` | `pen` | `pencil` | pencil-alt | Inline field edit |
| `action-delete` | `trash-can` | `trash-2` | trash, trash-alt | Delete (always confirmed) |
| `action-search` | `magnifying-glass` | `search` | search | Search |
| `action-filter` | `filter` | `funnel` | – | Filter |
| `action-sort` | `sort` | `arrow-up-down` | – | Sortable column |
| `action-refresh` | `arrows-rotate` | `refresh-cw` | sync, sync-alt, redo | Refresh / sync now |
| `action-undo` | `rotate-left` | `undo-2` | undo | Undo / revert |
| `action-save` | `floppy-disk` | `save` | save | Save |
| `action-copy` | `copy` | `copy` | – | Copy to clipboard |
| `action-link` | `link` | `link` | – | Link / relate records |
| `action-external` | `arrow-up-right-from-square` | `external-link` | external-link-alt | Opens outside the page / in a peer app |
| `action-upload` | `upload` | `upload` | – | Upload / import |
| `action-download` | `download` | `download` | – | Download / export |
| `action-more` | `ellipsis` | `ellipsis` | ellipsis-h | Row overflow menu |
| `action-close` | `xmark` | `x` | times | Close dialog / dismiss / clear |
| `action-confirm` | `check` | `check` | – | Confirm, selected |
| `action-sign-out` | `right-from-bracket` | `log-out` | sign-out-alt | Sign out |
| `show` | `eye` | `eye` | – | Reveal secret / view |
| `hide` | `eye-slash` | `eye-off` | – | Hide secret |
| `drag-handle` | `grip-vertical` | `grip-vertical` | – | Reorder handle |
| `menu` | `bars` | `menu` | – | Open the navigation drawer (phones) |
| `expand` | `chevron-down` | `chevron-down` | – | Expand / dropdown |
| `next` | `chevron-right` | `chevron-right` | – | Next, drill in, breadcrumb separator |
| `layout-grid` | `table-cells-large` | `layout-grid` | – | Card / grid view |
| `theme-light` | `sun` | `sun` | – | Light theme |
| `theme-dark` | `moon` | `moon` | – | Dark theme |
| `theme-system` | `circle-half-stroke` | `sun-moon` | – | Follow system theme |
| `status-success` | `circle-check` | `circle-check` | check-circle | Healthy / success (always with text) |
| `status-warning` | `triangle-exclamation` | `triangle-alert` | exclamation-triangle | Warning |
| `status-danger` | `circle-exclamation` | `circle-alert` | exclamation-circle | Critical / error |
| `status-info` | `circle-info` | `info` | info-circle | Information |
| `status-pending` | `hourglass-half` | `hourglass` | – | Pending approval / waiting |
| `status-failed` | `circle-xmark` | `circle-x` | times-circle | Failed / rejected |
| `status-paused` | `circle-pause` | `circle-pause` | – | Paused / on hold |
| `status-unknown` | `circle-question` | `circle-help` | – | Unknown / stale (with last-sync time) |
| `loading` | `spinner` | `loader-circle` | – | Loading (fa-spin; static under reduced motion) |
<!-- icon-map:end -->

## 7. Space, radius, borders, elevation, motion, density, breakpoints, layers

**Space** (4/8): `0 1 2 3 4 5 6 8 10 12 16` = 0, 4, 8, 12, 16, 20, 24, 32, 40, 48, 64 px. Inside components use 4, 8,
12; between components 8, 12, 16, 24; between page regions 24, 32.

**Radius**: `sm 4` badges, tags, checkboxes · `md 6` buttons, inputs, menus · `lg 8` cards, tables, alerts ·
`xl 12` dialogs, drawers, palette · `pill` status pills and counts only. No radius above 12px.

**Borders**: `hairline 1px` for all borders and dividers; `thick 2px` selected-tab underline; `indicator 3px`
active-nav bar and alert left border; `focus 2px` + `focus-offset 2px`. Separation comes from `border.subtle`
first; shadow is for things that float.

**Elevation**: `shadow.0` none (flat cards in tables/dashboards) · `1` optional card lift · `2` dropdowns, popovers,
sticky toolbars · `3` dialogs, drawers, palette. Dark theme uses stronger, darker shadows (values from Professional
Dark today) and relies on `bg.raised` lightness.

**Motion**: `fast 120ms` hover/press/colour · `base 180ms` menus, popovers, tab indicator · `slow 260ms` drawers,
dialogs, sidebar collapse; easing `standard (0.2,0,0,1)` enter/move, `exit (0.4,0,1,1)` leave. Under
`prefers-reduced-motion: reduce` all three durations are `0ms`, slides/scales become instant, skeleton shimmer stops
(static tint), smooth scrolling is off; spinners may keep rotating (they convey state and are small) but must be
paired with text such as "Loading…". No decorative animation, no auto-playing motion longer than 5 s (WCAG 2.2.2).

**Density** (`html[data-density]`, user preference, compact default):

| Token (`--cs-…`) | Compact | Comfortable | Touch (< 768px, any density) | Note |
|---|---|---|---|---|
| `control-height` | 36 | 40 | 44 | ui.css today: 36 / 42 |
| `control-height-sm` | 28 | 32 | — | toolbar / in-row buttons |
| `icon-button` | 32 | 40 | 44 | hit area ≥ 24 (WCAG 2.5.8) in all modes |
| `row-height` (min) | 36 | 48 | 48 | ui.css today: 38 / 48 |
| `cell-padding-y` / `-x` | 6 / 12 | 12 / 16 | — | ui.css today: 6/12, 12/14 |
| `card-padding` | 16 | 20 | — | ui.css today: 14 / 20 |
| `card-header-padding-y` | 8 | 12 | — | ui.css today: 10 / 14 |
| `section-gap` | 12 | 20 | — | |
| `page-gutter` | 16 | 24 | — | 16 on phones |

Values that differ from ui.css today are moved onto the 4px grid; the visual change is ≤ 2px per value.

**Breakpoints** (min-width): `xs 390` phone reference (must also work at 360) · `md 768` tablet · `lg 1280` laptop ·
`xl 1440` desktop · `2xl 1920` wide · `3xl 2560` ultrawide/wallboard. These are the §21 test widths. Bootstrap's grid
breakpoints stay inside Bootstrap; app CSS should use these six only (today it also uses 861, 1500, 1600, 1800, 1850).

**Layers** (`--cs-z-*`): base 0 · raised 1 · dropdown 1000 · sticky 1020 · header 1030 · nav 1040 · nav-flyout 1045 ·
backdrop 1050 · dialog 1055 · command-palette 1060 · popover 1070 · tooltip 1080 · toast 1090 · skip-link 1100.
Aligned with Bootstrap 5.3's own values so vendored components interleave correctly. Nothing above 1100; the
`99999`–`100003 !important` rules in `themes.css:500-593` are to be removed (increment I-6).

**Layout sizes**: sidebar 248, rail 64, top bar 56, form max 960, reading max 760, dialog 400 / 560 / 800,
drawer 480.

## 8. Components

Every component below must exist in the component showcase (planned, §14 I-7) in light and dark, compact and
comfortable. Common requirements for all interactive components:

- Visible focus: `focus.ring`, 2px, 2px offset, `:focus-visible` only; never `outline: none` without a replacement.
- States, in this order of precedence: disabled > active/pressed > focus > hover > rest. Selected and invalid are
  orthogonal and combine with the others.
- Disabled: `action.disabled.*`, `cursor: not-allowed`, `aria-disabled` or `disabled`; explain *why* nearby or in a
  tooltip when the reason isn't obvious (e.g. "Requires the Approver role"). Prefer hiding an action the user can never
  perform over showing it disabled.
- Hit area ≥ 24×24 px (2.5.8) everywhere, 44×44 for primary touch targets below 768px.
- Text never truncates without the full value available (title/tooltip or expandable).
- Keyboard: everything reachable by Tab in visual order; Esc closes the top-most layer and returns focus.

### Page header
Title (`h1`, `font.size.2xl` compact / `3xl` comfortable, weight 600), optional breadcrumb above, optional one-line
description (`text.muted`, sm), actions right-aligned (one primary button max, the rest secondary/ghost or in an
overflow menu). Height: content-driven, no hero banners; total vertical space ≤ 72px compact / 96px comfortable
excluding breadcrumb. Below 768px actions wrap under the title; overflow menu holds all but the primary.
Record pages: title = record name, status pill next to it, key metadata row (sm, muted) below.

### Section header
`h2`/`h3`, `font.size.lg` weight 600, optional count (`text.muted`), optional actions (ghost/sm buttons) right. 8px
below, 24px above (16 compact). A section header is not a card header; cards use the same type but inside the card.

### Buttons
Variants: primary (one per view region), secondary (default), ghost (toolbars), danger (destructive), link (inline).
Height `control-height` (sm: `control-height-sm`), padding-x 12 (sm 8), radius md, label 14/500, icon 16 with 8 gap.
States: rest, hover (`bg-hover`), active (`bg-active`), focus ring, disabled, loading (spinner replaces the icon, label
stays, `aria-busy="true"`, button disabled against double submit). Destructive actions confirm (dialog or undo
toast); never remove an existing confirmation, approval or step-up to save a click.

### Icon-only actions
Square `icon-button` (32 / 40 / 44 touch), icon 16, ghost style, radius md. Must have `aria-label` and a tooltip with
the same text; toggles use `aria-pressed`. Use only for universally understood actions (edit, delete, copy, more,
close, refresh) or in dense table rows; anything else gets a text label.

### Tables
Header row on `bg.sunken`, 13/500 `text.secondary`, sticky (`z.sticky`) on long lists; rows min `row-height`, cell
padding from density; row hover `bg.hover`; selected `bg.selected` with a checked checkbox (not colour alone);
dividers `border.subtle`. Numbers right-aligned with tabular numerals; dates in one format per locale; status column
uses status pills. Sortable headers are buttons with `aria-sort`. Row actions: up to 2 icon buttons + overflow menu,
visible on hover **and** on focus (and always visible on touch). Empty table → empty state (below) inside the table
frame. Below 768px: either a column-priority layout (keep 2–3 key columns, the rest in an expandable row) or stacked
cards — never a page-wide horizontal scroll; horizontal scroll is allowed only inside the table container with a
visible affordance.

### Forms
Label above the field (14/500), required marker `*` plus "required" in the accessible name, help text below (sm,
muted), error text below in `status.danger.text` with an icon, linked by `aria-describedby`, field border
`focus.ring-danger` when invalid and `aria-invalid="true"`. Inputs: `control-height`, padding-x 12, border
`border.strong`, radius md, bg `bg.surface` (read-only: `bg.sunken`). Max form width 960; two columns only ≥ 1280 and
for short related fields. Group with `fieldset`/`legend`. Submit row at the end (primary + cancel), sticky on long
forms. On submit with errors: summary at top listing errors as links, focus moved to it. Unsaved-change guard on long
forms (exists: `static/js/form_guard.js`).

### Tabs
Horizontal tab list (`role="tablist"`), 14/500, padding from density (`--ui-tab-*` today), selected tab
`text.primary` + 2px `action.primary.bg` underline (`border-width.thick`); others `text.secondary`. Arrow keys move
between tabs, Home/End jump; the selected tab is in the URL (hash or query) so reload and links keep it. Counts as
badges after the label. More than ~7 tabs or below 768px → overflow into a "More" menu or a select; no wrapping onto
two lines.

### Dialogs
Sizes `dialog-sm 400`, `md 560`, `lg 800`; full-screen below 768px. Radius xl, `shadow.3`, `bg.surface`, backdrop
`bg.backdrop`, `z.dialog`. Header: title (xl/600) + close button; body scrolls, header and footer stay; footer
actions right (primary last), destructive confirm uses the danger button with a specific label ("Delete 3 tickets"),
not "OK". Focus moves into the dialog (first field or the least destructive action), is trapped, and returns to the
invoking control on close; Esc closes unless the dialog holds unsaved input (then confirm). `role="dialog"`,
`aria-modal="true"`, `aria-labelledby`.

### Dropdown menus
`bg.raised`, `shadow.2`, radius md, `z.dropdown` (in the rail: `z.nav-flyout`), min-width 180, item height
`control-height-sm`+4 (32 compact, 36 comfortable), padding-x 12, icon 16. Hover/keyboard highlight `bg.hover`,
current item checked icon + `aria-checked`. Arrow keys, Home/End, type-ahead, Esc closes and returns focus. Danger
items last, separated, `status.danger.text`. Never nest more than one submenu level.

### Tooltips
Inverse: `text.primary` colour as fill, `text.inverse` text (4.5:1 by construction), 12/16, padding 4×8, radius sm,
max-width 280, `z.tooltip`. Appear on hover after ~300 ms and immediately on keyboard focus; dismissible with Esc,
hoverable (1.4.13). Content is a label or short hint only — never the only place essential information lives, never
interactive.

### Status indicators
Three forms: **pill** (subtle bg + status text + icon, radius pill, 12/500, height 20/22), **solid badge** (`solid` +
`on-solid`, for counts and high-severity), **dot** (8px `graphic` + text label). Every indicator has a text label;
the icon map's `status-*` icons go with each role. Stale external data uses `neutral` + "last synced <time>", never a
success colour.

### Alerts (inline banners)
`subtle` background, 1px `border`, 3px left border in `graphic`, status icon, title (500) + body, optional action
and dismiss. Radius lg, padding 12/16. `role="status"` for info/success, `role="alert"` only for errors that appear
in response to an action. Page-level alerts sit under the page header, not above the shell. No persistent banners
for missing optional integrations (standalone rule).

### Notifications (toasts and notification centre)
Toasts: bottom-right (bottom full-width on phones), `bg.raised`, `shadow.3`, left status bar, max-width 400, stack
max 3, `z.toast`; success/info auto-dismiss after ≥ 5 s and pause on hover/focus; errors stay until dismissed;
`aria-live="polite"` (assertive for errors). Undo appears in the toast for reversible actions. Notification centre:
bell in the top bar with unread count badge (`status.danger.solid`, "9+" cap), panel grouped by day, mark-read on
open, each item links to its record.

### Breadcrumbs
Above the page title, 13px `text.muted`, separator `next` icon (aria-hidden), current page last, not a link,
`aria-current="page"`, inside `nav aria-label="Breadcrumb"`. Max 4 levels; middle levels collapse into "…" menu below
768px. Breadcrumbs reflect the navigation hierarchy, not history.

### Search components
Global search field in the top bar (placeholder names the shortcut, "Search… Ctrl+K"), opens the command palette.
Palette: `xl` radius, `shadow.3`, `z.command-palette`, width min(640px, 100vw − 32), results grouped (Favorites,
Recent, records by type, actions), keyboard: arrows, Enter, Esc; `role="combobox"` + listbox. In-page search/filter
inputs: search icon left, clear button right, debounce 200–300 ms, results count announced (`aria-live`).
Customer-scoped searches show the customer chip inside the field.

### Charts
See §4.5 colours. Chart cards: title (lg/600) + period selector + one-line takeaway; axis 12px; no 3D, no pie with
more than 5 slices (use a bar), no dual axes unless labelled. Empty data → empty state, not an empty grid. Every chart
has a table view or text summary; colours never carry meaning alone.

### Filters
Filter bar above the list: search + up to 4 inline filters (select / multi-select chips) + "More filters" drawer.
Active filters show as removable chips ("Status: Open ×") with a "Clear all". Filter state is in the URL; saved views
(bookmark icon) per user. On phones the bar collapses to search + "Filters (n)" button opening a drawer.

### Pagination
Below the table, right-aligned: "1–50 of 1,234", previous/next icon buttons, page-size select (25/50/100). Page
numbers only when the total is small (≤ 7 pages shown, with ellipsis). Keyboard reachable; current page
`aria-current="page"`. Infinite scroll is not used for operational lists.

### Bulk-action toolbar
Appears when ≥ 1 row is selected, replacing the filter bar in place (no layout jump) or sticky at the top of the
table: "3 selected" + "Select all 1,234" link + actions + clear. Actions respect per-record permissions (count what
will be skipped and say so before running). Destructive bulk actions confirm with the count. Results summary after
("12 updated, 2 skipped — view"). Selection count announced via `aria-live`.

### Date and time controls
Native `input type="date"/"time"/"datetime-local"` styled as inputs (`control-height`), with the user's locale format
shown in help text; relative presets for ranges (Today, Last 7 days, This month, Custom). Times show the timezone when
it differs from the user's. Displayed timestamps: relative for < 24 h ("12 min ago") with the absolute value in
`title`/`<time datetime>`; absolute otherwise.

### Loading indicators
Inline spinner (16px, `currentColor`) in buttons and small regions; region loading: `aria-busy="true"` on the region +
visually hidden "Loading…". Show nothing for the first ~300 ms (avoid flicker); after ~10 s show progress or an
explanation. Long jobs → progress bar with percentage/steps (determinate when possible).

### Skeleton loaders
Blocks in `bg.sunken` matching the final layout (row heights, card sizes) so nothing shifts when content arrives;
shimmer only with `prefers-reduced-motion: no-preference`; `aria-hidden="true"` with a single live "Loading" label for
the region. Use for first loads of dashboards and lists; not for sub-300 ms responses.

### Empty states
Inside the region that is empty (card/table), centred, icon 20–32px in `text.muted`, one-line title, one sentence of
why/what next, one primary action if the user can act (e.g. "Add customer"), a docs link optionally. Distinguish
"nothing yet" from "no results for these filters" (offer "Clear filters"). No illustrations that push content below
the fold; no upsell to install another product.

### Error states
Region-level: alert (danger) inside the region with what failed, whether data shown is stale (with last successful
time), and a retry; the rest of the page keeps working (fault isolation). Page-level (403/404/500): plain page in the
shell with title, explanation, a way back, and a reference ID for support. Field-level: see Forms. Never show raw
stack traces or tokens.

### Success messages
Toast for completed actions on the same page; inline success alert when the result needs reading (e.g. import
summary); after redirects, a one-time message under the page header. Always say what happened ("Ticket #1042
closed"), and offer Undo when reversible.

### Disabled states
See common requirements. Disabled controls are excluded from tab order only when the reason is shown elsewhere;
otherwise use `aria-disabled="true"` so keyboard and screen-reader users can reach the explanation.

## 9. Layout and shell rules (§5)

- **Regions**: top bar (56px: app identity/logo, optional app switcher, customer selector, global search, favourites,
  recent, pending approvals, notifications, help, user menu with theme + density) · sidebar · content. Skip link
  ("Skip to content") is the first focusable element (`z.skip-link`).
- **Sidebar**: one navigation definition (`core/navigation.py`) drives sidebar, rail, flyouts and palette (exists).
  Ten groups in this order: Dashboard, My Work, Service Desk, Customers, Assets and Network, Business, Knowledge and
  Vault, Security and Monitoring, Reports, Administration. Max depth 2 (group → entry; a third level becomes tabs on the
  page). Group icons from the icon map. Navigation search (filter field) at the top. Active entry: indicator bar +
  `aria-current="page"`; parent group shows a dot when collapsed.
- **Widths**: < 768 off-canvas drawer with backdrop (menu button in the top bar) · 768–1279 64px icon rail with
  flyouts · ≥ 1280 248px sidebar, collapsible to the rail; the choice persists per user. (Today the full sidebar starts
  at 1200px — `navigation.css:85` — moving to 1280 is part of I-6.)
- **Flyouts**: open on click/Enter (hover is an enhancement), `aria-expanded`, arrow-key navigation, Esc returns focus
  to the rail button, `z.nav-flyout`.
- **Content width**: data pages are fluid (tables and dashboards use the space); forms ≤ 960; reading text ≤ 760; at
  ≥ 1920 dashboards add columns rather than widening cards; at 2560 wallboard pages may use a larger type step. No
  horizontal page scroll at any of the six widths, at 200% zoom, or at 320 CSS px (1.4.10 reflow).
- **Customer selector**: shows the current customer or "All customers" (Global View); selection persists and every
  customer-scoped page states its scope in the page header.
- **Theme and density**: user menu offers Light, Dark, System (follows `prefers-color-scheme`) and Compact /
  Comfortable; stored on the profile (exists for density and theme, `accounts/models.py:568,701`); applied server-side
  on `<html>` to avoid a flash. System is selectable in the staff UI profile (113.5): the page renders the light
  palette and `static/js/theme_system.js`, loaded in `<head>` before the stylesheets, switches `data-theme` /
  `data-bs-theme` to the dark palette when the device prefers dark and follows changes; `data-cs-theme="system"` lets
  the token stylesheet follow the same media query. The portal already followed the device.
- **Terminology** shared across apps: Customer (not tenant/client in UI copy for new apps; Clientst0r's existing
  "Clients" label may stay), Device, Ticket, Approval, Integration, Workspace.

## 10. Application switcher appearance rules

- **Hidden** unless at least one peer application is configured, securely paired, enabled, and the signed-in user is
  permitted to open it. No placeholder button, no empty space, no "get more apps" entry, no tooltip about
  missing products.
- Position: top bar, immediately right of the app identity; icon `app-switcher` (`fa-grip` / Lucide `grip`), 32px
  icon button with `aria-label="Switch application"`, `aria-haspopup="menu"`.
- Menu: the current app first (checked, not a link), then each configured peer with its own name and logo (bundled by
  the hosting app or fetched once at pairing time and stored locally — never hot-linked from the peer), and a status
  line when degraded ("Unreachable — last seen 10:42"). An unreachable peer stays listed but marked, and opening it
  never blocks the current page.
- Opening a peer goes through the deep-link contract (customer context passed as a verified reference, no secrets in
  the URL, no open redirect); `action-external` icon when it opens in a new tab.
- Capability-aware: entries for features both installed versions support only (detail in
  `docs/ux/CROSS_APP_UX_CONTRACT.md`).
- Each app keeps its own identity: name, logo, and may tint its *accent* role; the shell layout, nav colours and
  status roles stay as specified so users recognise the family.

## 11. Customer branding limits

What an MSP can change today (§2): staff UI company name and logo (install-wide); portal name, logo, login
background, and an accent colour per customer or install-wide.

| Token / asset | Staff UI | Customer portal | Guard |
|---|---|---|---|
| Logo, product display name | yes (install) | yes (install, per customer) | Image sanitised (exists: `core.image_safety`); logo height capped (`custom_logo_height`); alt text = name |
| `accent.*` | no (spec 1.0) | yes | Derived variants must reach 4.5:1 against `bg.surface` in both themes for text, 3:1 for graphics; on-solid text chosen by contrast. Exists for the portal: `readable_on` / `text_on` in `core/portal_branding.py:51-80` (checks against `#ffffff` and `#1a1d20`; to be switched to the `--cs-` surfaces in I-4) |
| `action.primary.*` | no | optional (planned): only if it passes the same guard; otherwise falls back to the spec value with a warning to the admin | as above |
| Login background colour / image | — | yes | Text over it sits on a `bg.surface` card, so contrast never depends on the image |
| Text, backgrounds, borders, focus ring, status roles, navigation, danger, disabled, chart palette, spacing, type, radius | **never** | **never** | — |

The admin preview shows the computed variants and their ratios; an input that cannot be made accessible is
adjusted automatically (darken/lighten toward the guard) and the admin is told what was used.

## 12. Versioning, change process and adoption

- **Semver of the spec** (`meta.version`): **major** — a token removed or renamed, a role's meaning changed, a CSS name
  scheme change; **minor** — new tokens, roles, components or icon concepts; **patch** — value adjustments that keep
  the role's meaning (e.g. a colour moved to fix contrast), description fixes.
- **Change process** (Clientst0r is the owner): edit `design-tokens.json` → run the validator (schema + contrast must
  pass) → bump `meta.version` and `meta.date` → update this document → note the change in
  `docs/ux/REM0TE_HANDOFF.md` (the versioned handoff) → the commit/tag that contains it is the published reference.
  Token changes ship in a Clientst0r release like any other change (CHANGELOG entry).
- **Adoption by Rem0te and future MSPZero apps** (st0r, OPNManager, m0nitor, …): each app copies a tagged version of
  `design-tokens.json` (and, optionally, `check_design_tokens.py`, which is standard-library Python and takes
  `--tokens`/`--css` paths) into its own repository, generates its own CSS with its own build, bundles its own fonts
  and icons, and records the spec version it implements. No app fetches tokens, CSS, fonts or icons from another app or
  from GitHub at runtime. Apps upgrade on their own schedule; a peer on 1.0.0 and another on 1.3.0 still work together
  because nothing is shared at runtime.
- Apps may add app-specific tokens under their own namespace (e.g. `app.*`) and may choose their navigation sections;
  they should not redefine the meaning of shared roles.
- **Compatibility matrix** (maintained in the handoff document; this is its design-spec column):

| Clientst0r version | Design spec | Notes |
|---|---|---|
| ≤ 3.17.776 | none (pre-spec) | themes.css / ui.css tokens |
| next release that ships I-1 | 1.0.0 | tokens.css generated; app CSS unchanged |

## 13. Validator and drift detection

`venv/bin/python scripts/ux/check_design_tokens.py` (CI and `core/tests/test_design_tokens.py`):

1. **Schema** — semver version, `$type` known and value valid for it, aliases resolve without cycles, light and dark
   define the same tokens, keys are lower-kebab, every icon concept has `fa` and `lucide` names and the `fa` name
   exists in the vendored Font Awesome stylesheet.
2. **Contrast** — every pair in `contrast-pairs` meets its minimum (250 pairs today, all pass).
3. **Drift** — maps each token to its `--cs-*` variable and context (theme, density, touch, reduced motion), scans
   `static/css/*.css`; a variable defined with a literal value different from the token **fails**; a variable not
   defined anywhere is **not yet implemented** (reported, not a failure — 306 of 306 today); one defined through
   `var()`/`calc()` is reported as indirect; `--cs-*` names with no token are listed.

Options: `--contrast` (markdown table), `--emit-css` (the generated stylesheet), `--verbose`, `--tokens`, `--css`.

Declarations under a `[data-theme="..."]` selector are an application's own colour theme (Clientst0r's legacy
palettes) and are not compared with the spec's light/dark values; the application checks their contrast itself.

**Generator (113.5).** `venv/bin/python scripts/ux/build_token_css.py` writes `static/css/tokens.css` from the JSON
(the `--emit-css` output plus a header) and the generated "theme-tokens" region of `static/css/themes.css`: one
`:root[data-theme="x"]` block per colour theme that sets `--cs-color-*` from the theme's own variables
(`--cs-color-bg-surface: var(--surface)` …). A token with no source in the theme keeps the spec value of the theme's
mode (`data-cs-theme` on `<html>`); a token that would miss a contrast pair is nudged toward white or black just far
enough and written as a commented literal. `--check` exits 1 when either output is stale;
`core.tests.test_design_tokens` runs it and checks every contrast pair in every theme.

## 14. CSS migration increments

Status (113.5, in progress): I-1 done (tokens.css generated, loaded first in the staff, portal, sign-in and focus
shells); I-2 and I-9 done in 113.5 part 1 (Inter and the CDN libraries bundled); I-3 partly done: every colour theme
(not only Professional Dark) maps onto the tokens from its own palette and the System theme is selectable, but no
legacy variable reads `--cs-*` yet and no new neutral Light theme was added, so no page looks different. The rest are
planned.

| # | Increment | Acceptance criteria |
|---|---|---|
| I-1 | **tokens.css generated from the JSON.** `static/css/tokens.css` written by the validator's `--emit-css` (or a small generator), loaded first in `base.html` and the portal base; `base.html` sets `data-cs-theme` from the profile's dark/light. | File is generated, not hand-edited; validator reports 306/306 implemented and 0 drift; a test fails when tokens.css is stale; no visual change (no existing rule reads `--cs-*` yet). |
| I-2 | **Inter self-hosted.** Vendor the OFL files + licence under `static/vendor/inter/<ver>/`, `@font-face` with `font-display: swap`, preload, `--ui-font` → `var(--cs-font-family-sans)`; portal stack too. | No request to a font host (checked in a browser test / CSP); text renders in Inter on a machine without Inter installed; licence file shipped; page weight increase recorded. |
| I-3 | **themes.css maps onto tokens.** Professional Dark and a new neutral Light theme set their legacy names from `--cs-*` (`--surface: var(--cs-color-bg-surface)` …); `--ui-*` bindings in `ui.css:106-122` read `--cs-*`; System option added to the theme choices (follows `prefers-color-scheme`). Legacy colour themes stay selectable and keep their own values for now. | Professional Dark and Light screenshots at the six widths show no unintended change beyond the documented colour adjustments; `test_theme_contrast.py` still passes; System follows the OS setting with no flash on load. |
| I-4 | **Portal on tokens + branding guard on token surfaces.** `--portal-*` read `--cs-*`; `core/portal_branding.py` guards the accent against `--cs-color-bg-surface` (both themes). | Existing portal tests pass; an accent that fails is auto-adjusted and the settings page shows the used value and its ratio. |
| I-5 | **Semantic icon helper and canonical names.** `{% icon "concept" %}` tag reading `icon.concepts`; `core/navigation.py` uses concept keys; replace retired FA 5 aliases (1,681 uses across the mapped concepts) with canonical names, area by area. | A test fails on new uses of a retired alias in templates; icon-only buttons rendered by the tag always carry `aria-label`; no visual change (aliases render the same glyph). |
| I-6 | **Layers, breakpoints, shell.** Replace the `z-index ≥ 9999` rules with `--cs-z-*`; app CSS media queries limited to the six breakpoints; full sidebar from 1280. | Modals, flyouts, tooltips and toasts stack correctly in the showcase; no `z-index` literal above 1100 in app CSS (test); layout checked at 390/768/1280/1440/1920/2560 without horizontal scroll. |
| I-7 | **Component showcase** (staff-only page) with every §8 component in both themes and densities. | Every component listed in §8 appears; axe-style automated check finds no contrast/name violations on it; screenshots captured for the handoff. |
| I-8 | **ui.css components switch to semantic tokens** (buttons, tables, forms, tabs, badges, alerts first), removing hard-coded hex from app CSS area by area. | Count of hex literals in `static/css/*.css` (excluding tokens.css, vendor) drops each release; contrast sweep `scripts/contrast_check.py` shows no new failures. |
| I-9 | **Vendor the CDN assets** (Chart.js, SortableJS, jsvectormap, html5-qrcode; use the already-vendored Quill and Font Awesome in the 7 templates that still use CDNs). | grep for `cdn.jsdelivr.net`, `cdnjs.cloudflare.com`, `unpkg.com` in `templates/` returns nothing; CSP can drop those hosts. |
| I-10 | **Global reduced-motion rule** using `--cs-motion-*`, replacing per-component overrides where equivalent. | With reduced motion on, no transition or animation longer than 0ms except spinners; verified in the showcase. |

I-1, I-2, I-9 are independent and can ship first; I-3 depends on I-1; I-4 on I-1/I-3; I-8 on I-3 and I-7.

## 15. Not verified / open points

- Lucide icon names are from the Lucide naming scheme as known at authoring time; they are not vendored here and were
  not machine-checked. An adopting app must check them against the Lucide release it bundles.
- Inter file sizes and subsetting savings are not measured (nothing downloaded in this batch).
- The colour decisions were checked numerically, not yet on rendered pages; I-3 includes a screenshot review.
- The 10 legacy colour themes other than Professional Dark and Default Blue are outside spec 1.0 (Default Blue would be
  replaced by the spec's Light theme); whether
  to keep, map onto tokens with a contrast guard, or retire them is an owner decision (it changes user preferences).
- Moving the full-sidebar breakpoint from 1200 to 1280 changes behaviour on 1200–1279px screens; confirm in I-6.
