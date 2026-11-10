# Navigation map: before → after

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

## Settings sidebar additions

Pages reached from the Settings sidebar (`templates/core/_settings_menu.html`)
rather than a top-level menu:

| Page | Sidebar entry | Gate |
|---|---|---|
| Technician Access (`/settings/security/technician-access/`) | Security → Technician Access | su |
| Ticket AI models and customer AI policies (OPTIONAL AI; used only while `psa_ai_enabled` is on) | Integrations → Ticket AI models | su |
| RMM pairing for ticket integration (v3.17.658) | Integrations → Integrations (or Admin → Integrations), then the RMM connection → Configure | admin (Owner or Admin of that customer, staff or su); turning pairing on is a protected change |

## Customer users

Customer users (`profile.user_type != 'staff'`) get no Modules or Admin menu,
no Asset Setup entry and no staff-gated tabs (Approvals, Knowledge Base, KB
Analytics, Access Management). Pages under `/reports/`, `/crm/` and
`/security/` stay MSP-staff-only in `SectionPermissionMiddleware`; the
customer portal (`portal/base.html`) has its own navigation and is untouched.
