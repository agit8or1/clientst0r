# Competitor feature matrix (official sources only)

Internal planning document. Retrieval date for every source: 2026-11-20. Competitor names appear here because this is a benchmark; keep them out of ROADMAP.md, FEATURES.md and marketing prose.

## Method and legend

- Reuse note: `docs/plans/competitive/GAP_ANALYSIS.md` records benchmark counts but contains no URLs, so every cell below was researched fresh and carries its own source.
- Sources: vendor product pages, vendor help/docs sites and vendor press releases only. Some pages were reached through a search result on the vendor's own domain rather than a direct fetch; those are marked `(s)` in the source list. Nothing from review sites, forums or comparison blogs is used.
- **Yes** = documented as a feature of that stack. **Partial** = documented in limited form, or only part of the category. **Add-on/Int** = separate paid product or third-party integration documented by the vendor. **NF** = Not found: not documented on the pages reached. NF is not a statement that the feature is absent. Several pages were unreachable (Atera main site and ticketing page returned 403; NinjaOne /psa/ and SuperOps /platform returned 404).
- Stack columns: Halo = HaloPSA + NinjaOne (Halo has no RMM of its own; RMM cells reflect NinjaOne, PSA cells reflect Halo). CW = ConnectWise PSA + ConnectWise RMM. AT = Autotask PSA + Datto RMM. Syncro, Atera and SuperOps are single-vendor stacks.
- Syncro's domain syncromsp.com now answers with a 301 to syncrosecure.com (server-supplied redirect); its docs are on docs.syncrosecure.com. Treated as the same vendor because the page identifies itself as Syncro.
- NinjaOne marketing and docs disagree on packaging: one page says PSA (billing, ticketing, documentation, ITAM) is generally available since Q1 2026; a support doc calls the billing tool "NinjaOne Billing (formerly NinjaOne PSA)" without ticketing/docs/ITAM [N4s]. Cells assume the marketing page.

## Matrix

| Category | Halo+Ninja | CW PSA+RMM | Autotask+Datto | Syncro | Atera | SuperOps |
|---|---|---|---|---|---|---|
| PSA ticketing | Yes [H1] | Yes [C1] | Yes [A1] | Yes [S1] | Yes [AT4] | Yes [SO1] |
| CRM / sales pipeline | Yes [H1] | Yes (opportunities to quotes) [C1] | Yes (opportunities) [A1] | NF | NF | Partial (service CRM, timeline; external CRM for pipeline) [SO6] |
| Billing (contracts, block hours, recurring) | Yes (recurring invoices, prepay block top-up) [H2][H3] | Yes (automated billing, agreements); block hours NF [C1] | Yes (six contract types incl. block hours, recurring service) [A3] | Yes (billing and invoicing, automated invoicing) [S1] | Yes (contracts, billing, invoices from tracked time) [AT1] | Yes (contracts by user/device, recurring invoices) [SO1] |
| Quoting | Yes (optional module) [H1] | Yes (quotes tied to opportunities and agreements) [C1] | Yes (native quote on opportunity; Quote Manager add-on) [A4][A5] | Yes (estimates) [S3] | NF | Yes (versioned quotes, templates) [SO4] |
| Electronic signatures | NF (portal approve/reject only) [H6] | Partial (signature/approval in higher PSA tier and Sell product; not confirmed on official PSA page) [C9] | Add-on (Quote Manager digital signature; quote API holds a response-signature field) [A5][A4] | NF (portal Approve/Decline buttons only) [S3] | NF | NF (link/portal approval; SLA agreements cannot be signed in-platform) [SO4][SO7] |
| Contracts | Yes [H3] | Yes [C1] | Yes [A3] | NF | Yes [AT1] | Yes [SO1] |
| Procurement / purchase orders | Yes (optional module; sales orders) [H1][H4] | Yes (requisition, PO, receiving, drop ship) [C3] | Add-on (Inventory and Procurement module, premium editions) [A1][A2] | Yes (PO create, check-in, vendor e-ordering) [S2] | NF | Yes (procurement queue grouped into POs) [SO5] |
| Inventory | Yes [H1] | Yes (warehouses, bins, serials, min stock) [C3] | Add-on (same module) [A1][A2] | Yes [S2] | NF | Yes [SO5] |
| IT documentation | Partial (knowledge base) [H1] | NF | Partial (Document Manager, KB matching) [A1] | NF | NF | Yes (IT documentation tied to assets, SOPs) [SO1][SO6] |
| RMM monitoring | Add-on/Int (NinjaOne, Halo integration) [N1][H1] | Yes [C2] | Yes [A6] | Yes [S1] | Yes [AT5] | Yes [SO1] |
| Remote access | Add-on/Int (NinjaOne native, four remote options) [N1] | Yes (ScreenConnect) [C2] | Yes (Web Remote) [A6] | Yes [S1] | Yes (Splashtop/AnyDesk, BYO TeamViewer/ScreenConnect) [AT3] | Yes (unattended, terminal, registry) [SO1]; RMM page lists third-party tools only [SO2] |
| Scripting / automation | Add-on/Int (NinjaOne) [N1] | Yes (PowerShell, bash, batch; workflows) [C2] | Yes (scripts, policies, webhooks, auto-resolve) [A6] | Yes (scripting engine) [S1] | Partial (AI-assisted scripting documented) [AT1] | Yes (runbooks, AI script generation) [SO1] |
| OS patching | Add-on/Int (NinjaOne) [N1] | Yes [C2] | Yes [A6] | Yes [S1] | Yes [AT2] | Yes [SO1] |
| Third-party app patching | Add-on/Int (NinjaOne, 200+ / 8,800+ apps per page) [N1][N2] | Yes (7,000+ apps) [C6] | Partial (policy patching for Microsoft and third-party, stated in a search summary; product page silent) [A9] | Yes [S1] | Yes (WinGet/Chocolatey/Homebrew) [AT2][AT3] | Yes [SO1][SO2] |
| Backup | Add-on/Int (NinjaOne Backup) [N2] | Add-on (x360Recover via Asio) [C8] | Add-on (Datto backup/SIRIS) [A6][A7] | Yes (cloud backup for M365 and Entra) [S1] | Add-on (Acronis, Axcient in App Center) [AT3] | Partial (backup status/alerts; Acronis integration) [SO1] |
| Security (EDR/AV) | Add-on/Int (NinjaOne endpoint security; CrowdStrike, SentinelOne) [N1] | Add-on (Defender for Business integration; managed EDR separate) [C7][C2] | Yes (native ransomware detection) plus Datto EDR integration [A7][A8] | Partial (baselines, security readiness) [S1] | NF | Add-on (SentinelOne, Bitdefender, Huntress, Acronis one-click) [SO1][SO2] |
| Microsoft 365 management | Partial (Halo CSP/Entra import; NinjaOne Intune/Entra link) [H5][N1] | Add-on (separate M365 SaaS Security and Cloud Backup products) [C2] | Yes (native onboard/offboard/quarantine, password reset) [A6] | Yes [S1] | NF | NF (Teams integration only) [SO1] |
| AI features (OPTIONAL in our terms) | Yes (Halo AI agents; Ninja Katana with RBAC and global kill switch) [H1][N1] | Yes (AI service desk agents) [C1] | NF | Yes (agentic service delivery, MCP server) [S1] | Yes (Copilot, Robin agent) [AT1] | Yes (Monica AI) [SO1] |
| Customer portal | Yes (self-service portal) [H1] | Yes (End User Portal) [C4] | Yes (Client Access Portal) [A2] | Yes [S1][S4] | NF | Yes [SO3] |
| Reporting / BI | Yes [H1] | Yes (BrightGauge dashboards) [C1] | Yes (dashboards and widgets) [A1] | Yes [S1] | Partial (PSA reporting mentioned) [AT1] | Yes [SO1] |

## Workflow features a self-hosted PSA+RMM should match

1. **Alert-to-ticket with dedup and status sync.** Autotask/Datto: alert engine removes duplicates and syncs status [A1]; Datto retries ticket creation, falls back to an organization-level ticket, puts alert tickets in an AEM category, unassigned by default [A9]. NinjaOne creates, updates and closes PSA tickets from conditions, scheduled automations and policy activities [N6].
2. **Ticket-to-device remote session, with session record written back.** ConnectWise Control opens sessions from a service ticket and saves chat, notes and timestamps to it [C5]. Autotask "One-Click Workflows" go from ticket to RMM device or remote session [A1].
3. **Patch-failure monitor raising a ticket.** Datto monitor fires when a policy-managed device installs fewer patches than required; ticket creation is a separate per-monitor setting [A9].
4. **Quote approval in the portal converting to work.** Syncro estimate approve/decline in the portal, then convert to ticket/invoice [S3]; SuperOps approved quote becomes a sales order, assigned to a technician, then invoiced [SO4]; NinjaOne quotes convert to one-time invoices or recurring agreements [N4].
5. **Automatic time-to-agreement linking and contract profitability.** NinjaOne links time entries to agreements for manual, ticket and automated work [N4]; SuperOps shows contract profitability and delivery-based COGS [SO1].
6. **Block hours with auto top-up and remaining balance.** Halo prepay hours topped up per billing template, optionally without an invoice [H3]; Autotask shows remaining block hours on contract summaries [A3].
7. **PO receive into inventory with accounting posting and ticket/project link.** ConnectWise closes POs into inventory and exports item receipts to accounting; POs link to the originating ticket or project [C3]; Syncro check-in receives items into inventory [S2].
8. **SLA timers with threshold alerts.** NinjaOne alerts at 80 percent of allotted time and at breach [N4]; ConnectWise flags at-risk tickets [C1].
9. **AI governance controls.** NinjaOne Katana: role-based access and a global kill switch [N1]. Matches our `psa_ai_enabled` gating.

## Sources (retrieval date 2026-11-20 for all; `(s)` = reached via vendor-domain search result, not direct fetch)

- H1 https://usehalo.com/ (home/feature list)
- H2 https://www.usehalo.com/guides/1356 (Recurring Invoices) (s)
- H3 https://www.usehalo.com/guides/1843 and https://www.usehalo.com/guides/1975 (Agreements; block hours top-up) (s)
- H4 https://www.usehalo.com/guides/1990 (Sales Orders) (s)
- H5 https://www.usehalo.com/guides/1189 (Microsoft CSP) and https://www.usehalo.com/guides/1106 (Entra ID) (s)
- H6 https://usehalo.com/halopsa/guides/891 (Notifications: quote approve/reject) (s)
- N1 https://www.ninjaone.com/rmm/
- N2 https://www.ninjaone.com/endpoint-management/
- N4 https://www.ninjaone.com/blog/release-15-dark-mode-sla-tracking-ddm-chromeos/ (s); N4s https://www.ninjaone.com/docs/professional-services-automation-psa/getting-started-professional-services-automation/ (s)
- N6 https://www.ninjaone.com/blog/how-to-integrate-rmm-with-psa-and-ticketing-systems/ (s)
- C1 https://www.connectwise.com/platform/psa
- C2 https://www.connectwise.com/platform/rmm
- C3 https://www.connectwise.com/platform/business-management/psa/procurement
- C4 https://docs.connectwise.com/ConnectWise_Unified_Product/ConnectWise_PSA_End_User_Portal (s)
- C5 https://docs.connectwise.com/ConnectWise_Control_Documentation/Supported_extensions/ConnectWise_Integrations/ConnectWise_Manage_Integration (s)
- C6 https://www.connectwise.com/company/press/releases/connectwise-advances-asio-platform-with-extensive-rmm-3rd-party-patching-rpa-breakthroughs-and-modernized-psa-capabilities (s)
- C7 https://www.connectwise.com/company/press/releases/connectwise-integrates-microsoft-defender-for-business-with-its-rmm-and-psa-solutions (s)
- C8 https://docs.connectwise.com/x360Recover/Backup_and_Disaster_Recovery_(BDR)/Integrate_ConnectWise_PSA/ConnectWise_Asio_Integration_with_x360Recover (s)
- C9 https://www.connectwise.com/blog/manage-sell-remote-sales-team and https://www.connectwise.com/platform/pricing/support (s; weak, hence Partial)
- A1 https://www.datto.com/products/autotask-psa/features/
- A2 https://www.datto.com/wp-content/uploads/dlm_uploads/PSA_Editions_US.pdf and https://www.datto.com/product-assets/autotask-psa/Autotask_PSA_Datasheet_US.pdf (s)
- A3 https://psa.datto.com/help/DeveloperHelp/Content/APIs/REST/Entities/ContractsEntity.htm (s)
- A4 https://www.autotask.net/help/DeveloperHelp/Content/APIs/REST/Entities/QuotesEntity.htm (s)
- A5 https://www.datto.com/products/msp-quoting-software/ and https://psa.datto.com/help/Content/3_Features/5_Sales/Quotes/Select_Quoting_Tool.htm (s)
- A6 https://www.datto.com/products/rmm/
- A7 https://rmm.datto.com/help/en/Content/3NEWUI/RansomwareDetection.htm (s)
- A8 https://rmm.datto.com/help/en/Content/3NEWUI/Setup/Integrations/DattoEDRIntegration.htm (s)
- A9 https://rmm.datto.com/help/en/Content/3NEWUI/Monitors/Monitors.htm (s)
- S1 https://syncrosecure.com/ (Syncro home, via redirect from syncromsp.com)
- S2 https://docs.syncrosecure.com/products-services-inventory/purchase-orders-restocking-inventory (s)
- S3 https://docs.syncrosecure.com/invoices-billing/estimates-quotes (s)
- S4 https://docs.syncrosecure.com/portal/about-the-portal (s)
- AT1 https://www.atera.com/blog/atera-review/ (s; vendor blog, claims are self-reported)
- AT2 https://www.atera.com/products/patch-management/ (s)
- AT3 https://support.atera.com/hc/en-us/articles/10811809441564-Remote-access-FAQ (s)
- AT4 https://www.atera.com/products/ticketing/ (title/listing only; page returned 403 on fetch) (s)
- AT5 https://www.atera.com/features/remote-access-and-remote-support/ (s)
- SO1 https://superops.com/msp
- SO2 https://superops.com/rmm
- SO3 https://support.superops.com/en/articles/7062695-using-the-client-portal (s)
- SO4 https://superops.com/psa-software/quote-management and https://support.superops.com/en/articles/14484855-creating-and-managing-sales-orders-in-superops (s)
- SO5 https://superops.com/inventory-management (s)
- SO6 https://superops.com/psa-software/client-management (s)
- SO7 https://support.superops.com/en/articles/8123305-faqs-psa (s)

## Caveats

- Atera is the thinnest column (403s); its NF cells (CRM, quoting, portal, documentation, procurement, security, M365) are most likely to be documentation gaps on pages reached.
- Edition gating (Autotask, ConnectWise) was not mapped; "Yes" does not mean included in every tier.
- Datto/Autotask and Quote Manager marketing pages are old; verify before citing in anything external.
