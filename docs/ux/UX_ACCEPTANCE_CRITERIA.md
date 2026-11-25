# UX acceptance criteria (Phase 113)

A Phase 113 increment is done only when every criterion that applies to it passes. "The screen exists" is not a
criterion. Measurements come from `scripts/ux/workflow_benchmarks.py` and `scripts/ux/page_baseline.py` on the demo
data, with starting conditions and machine load recorded in [WORKFLOW_BENCHMARKS](WORKFLOW_BENCHMARKS.md).

## Every increment

1. Full test suite passes; new behaviour has regression tests, including authorization and tenant-isolation tests where
   data is shown.
2. Standalone: the change works with no peer application and no RMM configured, and shows no peer-only control, empty
   space, nag or broken link (see [STANDALONE_REQUIREMENTS](STANDALONE_REQUIREMENTS.md) §2).
3. Checked in light and dark themes, comfortable and compact density, at 390, 768, 1440 and 1920 px; before/after
   screenshots kept.
4. New or changed styles use semantic tokens; `core/tests/test_design_tokens.py` passes.
5. No new external network request at page load (no CDN, no peer call while rendering).
6. Server-side checks, approvals, confirmations and step-up are unchanged unless the increment is explicitly about them.
7. Roadmap, changelog and the affected guide are updated; known limits are written down.

## Usability targets (§23 of the program)

Targets, not claims. Baselines from the 2026-11-25 run; "security steps" are counted separately and never removed.

| Target | Baseline (demo) | Status |
|---|---|---|
| Find a customer, device or ticket within 5 s | Ctrl+K 1.6–2.6 s machine time; ticket by text about 5.3 s (estimate) | met / borderline |
| Create a basic ticket within 15 s | 3–4 clicks | met |
| Start or stop a timer in one click | 1 click, but below the fold and a 1.7 s full reload | partly met (113.9) |
| Open an authorised credential in 2–3 clicks | see benchmark W04 | see benchmarks |
| Open a linked RMM device in one click | 1 click | met (demo host is invented) |
| Review linked endpoint health in one click | see benchmark | see benchmarks |
| Request supported remediation in 3 clicks (excluding approvals) | 3 clicks | met |
| Create a customer within 2 minutes | about 9 s name only, about 48 s with 12 fields (estimate) | met |
| Customer health report in 3 clicks | 3 clicks | met |
| Invoice draft from approved charges in 3 clicks | 5 clicks plus confirmation | not met (113.9) |
| Switch configured applications in one click | no switcher | not measurable (113.10) |
| Pair compatible applications within 5 minutes | Connect off on the demo | not measurable |
| Return from a linked application without losing context | 2 clicks back to the ticket panel | met |

## Per increment

| Increment | Criteria |
|---|---|
| 113.4 | Error, warning, info and success messages render with styles and `role="alert"`/`"status"` (view test); skip link, current-page marker, focus ring and top-bar text meet AA (contrast script: 0 failures on the audited pages); a test fails on a visible form control without a label or an icon-only control without a name, and the shared partials plus the five worst pages pass it; 404 and 500 render inside the shell, the 500 page without database queries. |
| 113.5 | Token stylesheet generated from `design-tokens.json`, a test fails when it is stale; validator reports every token implemented; no visual change beyond intended contrast fixes (screenshot diff reviewed); a "System" theme follows the OS setting; no request to a font or script CDN from any template (grep test). |
| 113.6 | Every navigation page renders on a fresh database with outbound sockets blocked; ticket, asset, workspace and dashboard pages render within budget with the peer unreachable; without an RMM connection, RMM-only navigation, widgets and tabs are absent; a lint test fails on an outbound call without a timeout; deleting an RMM connection explains what blocks it and offers Disable, and never removes tickets or history; a restore test passes with no peer. |
| 113.7 | Ticket detail ≤ 100 queries on the demo data; dispatch board query count independent of technician count and ≤ 60 on the demo; budgets added for My Work, client workspace, billing review, palette and search; scale datasets generated and the first 60/1,200 run published with hardware and load recorded. |
| 113.8 | One page-header include renders the page's `<h1>` on the ten busiest pages; median chrome above content ≤ 160 px at 1440; tab strip only with the sidebar collapsed or on phones; no "PSA" or "Client/Organization" wording left in user-facing breadcrumbs. |
| 113.9 | Timer control visible without scrolling on the ticket page at 1440×900, start/stop without a full reload in ≤ 300 ms server time, still server-checked; invoice draft in 3 clicks including the kept confirmation; workspace presets change layout only (test: switching presets never changes a permission check result). |
| 113.10 | Switcher absent with no paired peer and for users without access to the peer; one click to the peer with customer context; no secrets or arbitrary redirect targets in links; peer down → switcher entry shows offline without blocking the page. |

Standalone operation is release-blocking for every increment.
