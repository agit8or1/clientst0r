# Navigation map: before → after

## Primary sidebar (technician workspace)

The dropdown menus in the top bar were replaced by a sidebar of seven
technician groups — **My Work, Tickets, Clients, Devices, Alerts, Tools,
Reports** — with **Settings** at its foot for administrative and advanced
configuration. The registry is `core/navigation.py` (`PRIMARY`, `SETTINGS`);
the markup is `templates/core/_primary_nav.html`; behaviour (filter as you
type, collapse to an icon rail, phone/tablet drawer, `g`-shortcuts) is
`static/js/app_nav.js`. The top bar keeps the brand, search, client switcher,
utility buttons and the account menu. **No URL changed**; every section keeps
its tabs above the content, and every tab is also nested under its entry in
the sidebar so the filter finds it by name.

Gating is the old gate for each entry plus the server's own URL rules
(`SectionPermissionMiddleware`: MSP-staff-only `/reports/ /crm/ /security/`,
and `vault_view` / `docs_view` / `assets_view` for the current customer). A
link the server would answer with 403 is not drawn.

| Before (top bar) | After (sidebar) | Gate |
|---|---|---|
| Dashboard (direct link) | My Work → Dashboard | auth |
| PSA → My Work | My Work → My Work | psa |
| PSA → Tickets | Tickets → Tickets (tabs nested) | psa |
| PSA → Dispatch Board | Tickets → Dispatch Board | psa |
| PSA → Projects | Tickets → Projects | psa |
| PSA → Service Management | Tickets → Service Management | psa |
| PSA → Billing | Clients → Billing | psa |
| PSA → Procurement | Tools → Procurement | psa |
| Operations → Workflows | Tools → Workflows | workflows |
| Operations → Inventory | Tools → Inventory | inventory |
| Operations → Scheduling | Tools → Scheduling | scheduling |
| Operations → Monitoring | Alerts → Monitoring | monitoring |
| Operations → Vehicles | Tools → Vehicles | vehicles |
| Modules → Security | Alerts → Security Alerts | staff + psa |
| Modules → CRM | Clients → CRM | staff + crm |
| Modules → Reports | Reports → Reports | staff |
| Assets → All Assets | Devices → All Assets | auth + assets_view |
| Assets → Hardware & Ports | Devices → Hardware & Ports | auth + assets_view |
| Assets → Infrastructure | Devices → Infrastructure | auth |
| Assets → Asset Setup | Settings → Asset Setup | staff + assets_view |
| Docs → Documents / Diagrams / Review & Publishing / Documentation Readiness | Clients → same four entries | auth + docs_view |
| Vault → Passwords | Clients → Passwords | auth + vault_view |
| Vault → Access Rules | Clients → Vault Access Rules | auth + vault_view |
| Vault → My Vault | My Work → My Vault | auth |
| Vault → Secure Notes | My Work → Secure Notes | auth |
| Admin → System / Security / Integrations / Mobile | Settings → System / Security / Integrations / Mobile | su |
| Admin → Organizations & Access | Clients → All Clients (Organizations); Settings → Access Management | auth / su |
| Favorites star (bar) | unchanged in the bar; also My Work → Favorites | auth |
| Global KB link (bar, PSA off) | Tools → Global KB | global_kb, not psa, staff/su |
| *(new)* | Clients → Customer Operations (`core:customer_ops_current`) | auth |
| *(new)* | Devices → RMM Devices (`integrations:rmm_devices`) | staff |
| *(new)* | Alerts → RMM Alerts (`integrations:rmm_alerts`) | staff |
| Account menu (My Profile, My Work Details, Help, Apps & Downloads, Sign Out) | unchanged, top bar | auth |

### Pages added on the dev branch (previously linked only from inside their apps)

Each gate is the page's own view-level check, so the link appears exactly for
the users the page lets in (`core/navigation.py`, the `_check_*` gates).
Pages with their own local nav (ticket routing's `_nav.html`) get a sidebar
entry rather than a tab strip.

| Page | Sidebar | Gate |
|---|---|---|
| Shift schedule (`resourcing:shift_schedule`, `/resourcing/shifts/`) | Tickets → Shifts & Locations (landing, tab) | staff |
| Shift templates (`resourcing:shift_templates`) | Tickets → Shifts & Locations → tab | staff + `can_manage_shifts` (`resourcing_approve_leave` or `routing_manage_rules`, su) |
| Share my position with dispatch, the technician's consent (`field_ops:dispatch_sharing`) | Tickets → Shifts & Locations → Location Sharing | staff |
| Dispatch geo settings (`field_ops:dispatch_geo_settings`) | Tickets → Shifts & Locations → Dispatch Locations | su who is MSP staff |
| Billing review (`psa:billing_review`, `/psa/billing-review/`) | Clients → Billing → tab | psa + `require_admin` + staff |
| Serial search (`assets:serial_search`, `/assets/serials/`) | Devices → All Assets → tab | auth + assets_view |
| Workflow flow map (`psa:workflow_rule_map`, `/psa/rules/flow/`) | Tickets → Tickets → Workflow Flow Map | psa + `require_admin` + staff |
| Support workflows admin (`support_workflows:admin`) | Tools → Support Workflows | psa + `routing_manage_rules` |
| Alert policy (`ticket_routing:alerts`) | Alerts → Alert Policy (its rule and maintenance pages light up Alerts too) | psa + `routing_manage_rules` |
| RMM permissions (`rmm_permissions:index`, `/settings/security/rmm-permissions/`) | Settings → RMM Permissions (also still in the Settings page menu) | `policy.manage` or `audit.review` |
| KB analytics (`docs:kb_analytics`) | Clients → Review & Publishing → KB Analytics (already a tab; unchanged) | staff/su |
| Security digest (`security_alerts:digest_subscriptions`) | Alerts → Security Alerts → Weekly Digest | staff + psa + `security_alerts_view` |
| LDAP group mappings (`accounts:ldap_group_mappings`) | Settings → LDAP Group Mappings | su |
| Rem0te setup wizard (`integrations:rem0te_setup`) | Settings → Integrations → Rem0te Setup (also still in the Settings page menu) | su |

### Saved views and default filters

The saved-views bar (`core/workspace.py` `SAVED_VIEW_LISTS`, drawn by
`templates/core/_work_context.html`) is on these lists. Each list keeps its
existing URL and query parameters; a saved view stores only those
parameters, and `?view=all` skips a default view.

| List | Filters (query parameters) | Bar shown to |
|---|---|---|
| Tickets (`psa:ticket_list`) | client status priority queue assigned q | staff |
| RMM devices (`integrations:rmm_devices`) | q status type link | staff |
| All assets (`assets:asset_list`) | client type manufacturer status location (site) needs_reorder q/search, sort, per_page (25/50/100/200, default 50, sorted by name); staff also rmm (online/offline/stale/linked/unlinked) and alerts=active | anyone who may open the list; RMM presets staff only |
| RMM alerts (`integrations:rmm_alerts`) | status severity client q | staff |
| Routing triage (`ticket_routing:triage`) | client routing (suggested/fallback) priority q | staff |
| Invoices (`psa:invoice_list`) | status client q | staff, or `billing_view_invoices` |
| Timesheet approvals (`psa:timesheet_approval_queue`) | tech decision | staff |

Keyboard: `?` help, `/` search, `j` jump-to (sidebar filter), `[` collapse,
`g` then `w t c d a o r s` for the groups.

The sections below describe the earlier condensed dropdowns; their **tabs**
are unchanged and still apply.

## Condensed dropdowns (superseded by the sidebar)

The global menu was condensed so each dropdown holds 3–7 entries. Every
destination the old menus carried is still reachable by ordinary clicks: either
as a menu entry, or as a **tab** on that entry's landing page. Tabs are drawn
above the page content by `templates/base.html` from the registry in
`core/navigation.py` (`SECTIONS`) through `templates/core/_section_tabs.html`,
and only on pages that are themselves tabs of the section. No URL changed, so
bookmarks and deep links keep working.

Gate shorthand (same conditions the old `base.html` used, entry for entry):

| Shorthand | Condition |
|---|---|
| **auth** | signed in |
| **staff** | `is_staff_user or user.is_superuser or user.is_staff` (MSP staff, see `psa/visibility.py:is_msp_staff`) |
| **staff/su** | `is_staff_user or user.is_superuser` |
| **su** | `user.is_superuser` |
| **psa**, **crm**, **workflows**, **inventory**, **scheduling**, **monitoring**, **vehicles**, **global_kb** | the matching `*_enabled` feature toggle |

Top-level order after: Dashboard · PSA · Operations · Modules · Assets · Docs ·
Vault · Admin, then the right-hand cluster (Favorites, Beta app, Install app,
Help Us Grow, Global KB, search, theme, clock, client switcher, account menu).

## Entry counts

| Menu | Before | After |
|---|---|---|
| Dashboard | direct link | direct link |
| PSA | 27 | 7 |
| Operations | 16 (all toggles on) | 5 |
| More → **Modules** | 17 (superuser, all on) | 3 |
| Assets | 12 (staff) | 4 (staff), 3 (customer) |
| Docs | 9 (staff) | 4 |
| Vault | 4 | 4 |
| Admin | 10 | 5 |
| Account | 15 (superuser, incl. Sign Out) | 5 (incl. Sign Out) |

## Dashboard

| Before | After | Gate |
|---|---|---|
| Dashboard (`core:dashboard`) | unchanged, direct link | auth |

## PSA (menu gate: psa)

| Before (PSA menu) | After | Gate |
|---|---|---|
| My Work | PSA → My Work | psa |
| Tickets | PSA → Tickets (tab: Tickets) | psa |
| New Ticket | "New Ticket" button on the ticket list | psa |
| Clients (`accounts:organization_list`) | Client switcher → All clients (also Admin → Organizations & Access) | psa or su |
| Service Catalog | PSA → Service Management (landing, tab) | psa |
| Catalog Changes | PSA → Service Management → tab | psa |
| Projects | PSA → Projects (tab: Projects) | psa |
| Project Templates | PSA → Projects → tab | psa |
| Recurring Tickets | PSA → Tickets → tab | psa |
| Knowledge Base (`psa:kb_browse`) | PSA → Service Management → tab | psa + staff |
| Approvals | PSA → Service Management → tab | psa + staff |
| Change Requests | PSA → Service Management → tab | psa |
| Problems | PSA → Service Management → tab | psa |
| Releases | PSA → Service Management → tab | psa |
| Contracts | PSA → Billing (landing, tab) | psa |
| Quotes | PSA → Billing → tab | psa |
| Invoices | PSA → Billing → tab | psa |
| Aging Report | PSA → Billing → tab | psa |
| Dispatch Board | PSA → Dispatch Board | psa |
| Requisitions | PSA → Procurement (landing, tab) | psa |
| Purchase Orders | PSA → Procurement → tab | psa |
| Back-orders | PSA → Procurement → tab | psa |
| Vendors (`psa:vendor_list`) | PSA → Procurement → tab | psa |
| Workflow Rules | PSA → Tickets → tab | psa |
| Canned Replies | PSA → Tickets → tab | psa |
| Email Ingestion | PSA → Tickets → tab | psa |
| AI Inbox | PSA → Tickets → tab (OPTIONAL AI: now hidden while `psa_ai_enabled` is off, when the page 404s) | psa + psa_ai_enabled |

## Operations (menu gate: any of workflows / inventory / scheduling / monitoring / vehicles)

| Before | After | Gate |
|---|---|---|
| Workflows | Operations → Workflows | workflows |
| Inventory: Dashboard | Operations → Inventory (landing, tab "Dashboard") | inventory |
| Inventory: All Items | Operations → Inventory → tab | inventory |
| Inventory: Low Stock | Operations → Inventory → tab | inventory |
| Inventory: Tools | Operations → Inventory → tab | inventory |
| Scheduling: All Tasks | Operations → Scheduling (landing, tab) | scheduling |
| Scheduling: Wallboard | Operations → Scheduling → tab | scheduling |
| Scheduling: My Tasks | Operations → Scheduling → tab | scheduling |
| Scheduling: Calendar | Operations → Scheduling → tab | scheduling |
| Monitoring: Website Monitors | Operations → Monitoring (landing, tab) | monitoring |
| Monitoring: WAN Connections | Operations → Monitoring → tab | monitoring |
| Monitoring: Expirations | Operations → Monitoring → tab | monitoring |
| Monitoring: Status Pages | Operations → Monitoring → tab | monitoring |
| Monitoring: Config Backups | Operations → Monitoring → tab | monitoring |
| Vehicles: All Vehicles | Operations → Vehicles (landing, tab) | vehicles |
| Vehicles: Service Alerts | Operations → Vehicles → tab | vehicles |

## More → Modules (menu gate: staff)

| Before (More) | After | Gate |
|---|---|---|
| Security Alerts | Modules → Security (landing, tab) | staff + psa |
| Vendor Connections | Modules → Security → tab | staff + psa |
| Auto-Ticket Rules | Modules → Security → tab | staff + psa |
| Security Dashboard | Admin → Security (landing, tab) | su |
| Vulnerability Scans | Admin → Security → tab | su |
| CRM Overview | Modules → CRM (landing, tab) | staff + crm |
| Pipeline, Leads, Opportunities, Campaigns, Commissions, Commission Rules | Modules → CRM → tabs | staff + crm |
| Reports Home | Modules → Reports (landing, tab) | staff |
| Dashboards, Wallboards, Generate Reports, Report History | Modules → Reports → tabs | staff |

## Assets (menu gate: none)

| Before | After | Gate |
|---|---|---|
| All Assets | Assets → All Assets | auth |
| Hardware & Ports | Assets → Hardware & Ports (existing `hardware/_nav.html` tabs) | auth |
| Cables | Hardware & Ports → Cables tab | auth |
| Connectivity Diagram | Hardware & Ports → Connectivity tab | auth |
| Labels | Hardware & Ports → Labels tab | auth |
| Hardware Catalog | Hardware & Ports → Catalog tab | auth |
| Infrastructure: Racks | Assets → Infrastructure (landing, tab) | auth |
| Infrastructure: Network Closets | Assets → Infrastructure → tab | auth |
| Infrastructure: IPAM | Assets → Infrastructure → tab | auth |
| Infrastructure: VLANs (`monitoring:vlan_list`) | Assets → Infrastructure → tab (distinct from Hardware's `hardware:vlan_list` tab) | auth |
| Setup: Equipment Catalog | Assets → Asset Setup (landing, tab) | staff |
| Setup: Custom Fields & Types | Assets → Asset Setup → tab | staff |

## Docs (menu gate: none)

| Before | After | Gate |
|---|---|---|
| Documents | Docs → Documents | auth |
| Diagrams | Docs → Diagrams (landing, tab) | auth |
| Import Floor Plans | Docs → Diagrams → tab | auth |
| Drafts | Docs → Review & Publishing (landing, tab) | auth |
| Approval Queue | Docs → Review & Publishing → tab | auth |
| Review Queue | Docs → Review & Publishing → tab | auth |
| Archived | Docs → Review & Publishing → tab | auth |
| KB Analytics | Docs → Review & Publishing → tab | staff/su |
| Documentation Readiness | Docs → Documentation Readiness (existing `readiness/_nav.html` tabs) | auth |

## Vault (menu gate: none)

| Before | After | Gate |
|---|---|---|
| Passwords | Vault → Passwords | auth |
| My Vault | Vault → My Vault | auth |
| Secure Notes | Vault → Secure Notes | auth |
| Access Rules | Vault → Access Rules | auth |

## Admin (menu gate: su)

| Before | After | Gate |
|---|---|---|
| Settings | Admin → System (landing, tab "Settings"; Settings sidebar unchanged) | su |
| System Status | Admin → System → tab (also in the Settings sidebar) | su |
| System Updates | Admin → System → tab | su |
| Security Dashboard | Admin → Security (landing, tab) | su |
| Vulnerability Scans | Admin → Security → tab | su |
| Scan Configuration | Admin → Security → tab (also in the Settings sidebar) | su |
| *(new, v3.17.651)* Security Features | Admin → Security → tab | su |
| *(new, v3.17.653)* Vault Visibility | Admin → Security → tab | su |
| *(new, v3.17.653)* Superuser Approval | Admin → Security → tab | su |
| Organizations | Admin → Organizations & Access (landing, tab) | su (page also reached by All clients) |
| Access Management | Admin → Organizations & Access → tab | su |
| Webhooks | Admin → Integrations → tab | su |
| *(Integrations — previously only in the Settings sidebar)* | Admin → Integrations (landing, tab) | su |
| Mobile Apps | Admin → Mobile (landing, tab) | su |

## Account menu (gate: auth)

| Before | After | Gate |
|---|---|---|
| My Profile | Account → My Profile | auth |
| My Resources | Account → My Work Details (landing, tab "My Resources") | auth |
| My Leave | Account → My Work Details → tab | auth |
| My Billable Target | Account → My Work Details → tab | auth |
| Documentation & Help | Account → Help (landing, tab) | auth |
| About | Account → Help → tab | auth |
| Roadmap | Account → Help → tab | auth |
| Report Bug (opens `#reportBugModal`) | Account → Help → tab, opens the same modal (modal still on every page) | auth |
| Help Us Grow (opens `#supportProjectModal`) | navbar Help Us Grow button (unchanged) and Account → Help → tab | auth |
| Install App / Add to Home Screen (`#menu-install-pwa`) | Account → Apps & Downloads (landing); the tab carries `id="menu-install-pwa"` so the PWA install prompt still attaches; Install app navbar button unchanged | auth |
| Android App (APK) | Account → Apps & Downloads → tab (download) | auth |
| Beta test the Android app | Account → Apps & Downloads → tab; Beta app navbar button unchanged | auth |
| Beta tester requests | Admin → Mobile → tab | su |
| Browser Extension | Account → Apps & Downloads → tab (download) | auth |
| Sign Out (POST form to `logout`) | Account → Sign Out, same POST form with CSRF token | auth |

## Unchanged right-hand cluster

| Control | Gate |
|---|---|
| Favorites, Beta app, Install app, Help Us Grow (modal) buttons | auth |
| Global KB link | global_kb and not psa, staff/su |
| Search form, theme toggle, clock | auth |
| Client switcher (`core/_client_switcher.html`, `#orgDropdown`): active client / Global View pill, switch list, new "All clients" link | `current_organization or su or is_staff_user`; Global View entry su or is_staff_user; All clients psa or su |
| Shortcut strip (`core/_shortcut_strip.html`, below the navbar): up to three pinned pages, My Work and Tickets by default, edited with the pencil | MSP staff only (`core/shortcut_strip.py`) |
| Update badge (links to Settings → Updates) when the scheduled check found a newer release | su |
| Customer operations link in the client switcher's current-context block (`core:customer_ops`); also an Operations button on the customer page | `current_organization`; the page itself gates each section by role |

## Settings sidebar additions

Pages reached from the Settings sidebar (`templates/core/_settings_menu.html`)
rather than a top-level menu:

| Page | Sidebar entry | Gate |
|---|---|---|
| Technician Access (`/settings/security/technician-access/`) | Security → Technician Access | su |
| Ticket AI models and customer AI policies (OPTIONAL AI; used only while `psa_ai_enabled` is on) | Integrations → Ticket AI models | su |
| RMM pairing for ticket integration (v3.17.658) | Integrations → Integrations (or Admin → Integrations), then the RMM connection → Configure | admin (Owner or Admin of that customer, staff or su); turning pairing on is a protected change |
| Optional Modules (`/core/settings/modules/`): every optional module, its dependencies, what users see, links to its settings | System → Optional Modules (next to Feature Toggles) | su |

## Customer users

Customer users (`profile.user_type != 'staff'`) get no Modules or Admin menu,
no Asset Setup entry and no staff-gated tabs (Approvals, Knowledge Base, KB
Analytics, Access Management). Pages under `/reports/`, `/crm/` and
`/security/` stay MSP-staff-only in `SectionPermissionMiddleware`; the
customer portal (`portal/base.html`) has its own navigation and is untouched.
