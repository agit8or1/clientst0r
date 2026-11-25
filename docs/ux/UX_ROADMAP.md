# UX roadmap (Phase 113)

Phase 113 in [docs/ROADMAP.md](../ROADMAP.md#phase-113) is the status of record; this page holds the plan. It builds on
Phase 67 (shipped: one navigation definition, ten sections with icon rail and flyouts, settings center, Ctrl+K palette with
Favorites and Recent, compact customizable dashboard with role layouts, density, Professional Dark theme, client and
ticket workspaces, Security Overview). Nothing here is done until its acceptance criteria pass; planned items are marked
planned.

Inputs: [UX_AUDIT](UX_AUDIT.md), [COMPONENT_INVENTORY](COMPONENT_INVENTORY.md),
[WORKFLOW_BENCHMARKS](WORKFLOW_BENCHMARKS.md), [SHARED_DESIGN_SYSTEM](SHARED_DESIGN_SYSTEM.md),
[STANDALONE_REQUIREMENTS](STANDALONE_REQUIREMENTS.md), [CROSS_APP_UX_CONTRACT](CROSS_APP_UX_CONTRACT.md).

## Ground rules

- Standalone first: every increment is tested with no peer application and no RMM configured; a failing standalone check
  blocks the release.
- Incremental, never a front-end rewrite. Each increment ships on its own with tests, before/after screenshots and,
  where it targets speed or clicks, a before/after measurement from `scripts/ux/`.
- Presentation never changes permissions. Approvals, confirmations, step-up and server-side checks are never removed to
  save a click; they are counted separately in measurements.
- Existing financial calculations and postings are not changed for presentation reasons.
- Rem0te and future applications adopt the design specification independently; protocol changes go through the
  integration coordination document.

## Decisions taken (2026-11-25)

| Question from the audit | Decision |
|---|---|
| Sidebar children or section tab strip | Keep both definitions; show the tab strip only when the sidebar is collapsed to the rail or on phones. |
| "PSA" or "Service Desk" in the interface | "Service Desk" wherever users see it; "Customer" for the organisation a technician works for. |
| Classic dashboard | Retire on the existing plan (docs/plans/classic-dashboard-retirement.md) after its review period. |
| Fonts | Bundle Inter (OFL 1.1) with the system font stack as fallback. |
| Icons | Keep the vendored Font Awesome Free; a semantic icon map and an `{% icon %}` tag replace direct class names over time. |
| Legacy colour themes | Kept, rebuilt on the semantic tokens so they pass the same contrast checks. |
| Full sidebar breakpoint | 1280 px (rail below), matching the design breakpoints. |

## Increments

| # | Increment | Priority | Effort | Risk | Depends on | Status |
|---|---|---|---|---|---|---|
| 113.1 | Audit and baselines | P0 | M | low | — | shipped with this batch |
| 113.2 | Design specification v1.0.0, tokens, contrast test | P0 | M | low | — | shipped with this batch |
| 113.3 | Standalone requirements, cross-app contract, handoff; two standalone fixes | P0 | M | low | — | shipped with this batch |
| 113.4 | Urgent accessibility fixes (flash message styles, skip link, pagination, focus ring, top-bar contrast, labels and names on the worst pages, 404/500 in the shell) | P0 | S–M | low | — | planned |
| 113.5 | Token stylesheet generated from the JSON; themes mapped onto it; system-following theme; Inter and every CDN asset bundled | P0 | M | medium (visual) | 113.2 | planned |
| 113.6 | Standalone hardening: no-network page smoke test, peer-unreachable fixture, RMM-only UI hidden without an RMM, timeout lint, safe RMM removal, restore-without-peer test | P0 | M | medium | 113.3 | planned |
| 113.7 | Performance: access-decision cache on ticket detail, dispatch board query fix, budgets for My Work / workspace / billing review / palette / search, synthetic scale datasets | P0 | M | medium | — | planned |
| 113.8 | Shell: one page-header component, tab-strip rule above, consistent names, less chrome above content | P1 | M | medium (visual) | 113.5 | planned |
| 113.9 | Technician speed: timer without reload in the first screen, invoice draft in three clicks with confirmation, workspace presets | P1 | M | medium | 113.7 | planned |
| 113.10 | Optional application switcher and customer-context deep links | P1 | M | high (cross-app) | contract proposals agreed | planned |
| 113.11 | Component showcase; role dashboards; setup wizard and customer onboarding; migration previews; search ranking and saved searches; bulk-action previews; security-center views; training paths | P1–P2 | L | varies | 113.5, 113.8 | planned |

Each increment's acceptance criteria are in [UX_ACCEPTANCE_CRITERIA](UX_ACCEPTANCE_CRITERIA.md) and, in more detail, in
the source document named in that file.

## Coordination

- Design specification version and handoff: [REM0TE_HANDOFF](REM0TE_HANDOFF.md). The tag that carries a spec version is
  recorded there at release.
- Contract proposals CX-1 to CX-8 in [CROSS_APP_UX_CONTRACT](CROSS_APP_UX_CONTRACT.md) need the peer's agreement before
  113.10 starts; other increments do not wait for it.
