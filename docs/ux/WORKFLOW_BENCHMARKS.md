# Workflow and performance baselines

Baseline for the section 23 usability targets and the section 20 performance work. Measured 2026-11-25 on the demo
instance data, code at v3.17.776 plus the uncommitted working tree of the `dev/ux-program` worktree. These are
**baselines, not claims of final performance**. "Measured" means a script ran it; "estimated" means arithmetic on top
of a measurement and is labelled.

Re-run for before/after:

| Script | What it does |
|---|---|
| `scripts/ux/workflow_benchmarks.py` | Playwright. Drives the section 23 workflows against a URL given on the command line. Read-only unless `--allow-writes`, which creates only records named `UXBENCH...`. Refuses non-loopback hosts without `--allow-remote`. Never opens a settings form. |
| `scripts/ux/page_baseline.py` | Django test client, in process, against a demo SQLite database (refuses anything else). Records time and SQL query count per page. Run it on a copy of the demo database. |

## 1. Test conditions

| Item | Value |
|---|---|
| Host | 40 vCPU (QEMU virtual CPU), 31 GiB RAM (about 24 GiB available), Linux 6.8 |
| Load average during runs | 10.4 to 11.6 (1 minute) on 40 CPUs: the machine was busy with other test suites. Absolute times are inflated and noisy; compare before/after on a similar load or quote the load. |
| Server for workflows | `manage.py runserver --noreload` (threaded, one process) on port 8123, against a **copy** of the demo database made with the SQLite backup API. The shared demo on 8099 was not written to. |
| Server for page timing | in-process Django test client (middleware, view, template render; no network, no gunicorn) against the same copy |
| Settings | `scripts/demo/demo_settings.py` (SQLite, templates uncached, 2FA, lockout and firewall middleware removed, locmem cache) |
| Browser | Playwright Chromium headless, 1440 x 900, fresh context per run |
| User | `demo.tech` (superuser technician). Customer pages with Ridgeline Dental Group selected, billing pages with Beacon Managed IT (the MSP's own organization) selected. A non-superuser technician was **not** measured. |
| Runs | median of 5 (workflows) or 5 plus one warm-up (pages). W12 is one run: it consumes its source charges. |

### Dataset (demo database before the benchmark writes)

| Table | Rows | Table | Rows |
|---|---|---|---|
| organizations | 6 (1 MSP, 5 customers) | tickets (`psa_native_tickets`) | 36 |
| assets | 37 | ticket comments | 38 |
| RMM devices | 2 (2 connections, both inactive) | ticket time entries | 16 |
| documents | 56 | invoices | 4 |
| vault passwords | 28 | contacts | 9 |
| users | 18 | audit log rows | 723 |

The database file is 111 MB because of reference data (582 tables), not volume. **This is a small dataset**: it
measures page cost per page, not growth. Section 4 describes the larger datasets; none has been built or measured yet.

## 2. Workflow baselines (section 23)

Time is the machine time from the first user action to the visible result, with typing instantaneous. "Est. total" adds
0.2 s per typed character and 0.8 s per click (**estimates** of a practised user; no person was timed). Security steps
are counted separately and are in none of the click counts.

| ID | Target | Starting conditions | Steps (clicks / keys / chars typed) | Measured median (min-max) | Est. total | Security steps | Target met? |
|---|---|---|---|---|---|---|---|
| W01 | Find a customer in 5 s | On the dashboard | Ctrl+K, type `Ridgeline`, Enter (0 clicks / 2 keys / 9 chars) | 1.81 s (1.77-1.97) | 3.6 s | none | Yes (estimate) |
| W02 | Find a device in 5 s | Dashboard | Ctrl+K, `RDG-OP3`, Enter (0 / 2 / 7). The first hit is the asset page. | 1.64 s (1.61-2.05) | 3.0 s | none | Yes (estimate) |
| W03 | Find a ticket in 5 s | Dashboard | Ctrl+K, `Operatory 3 PC`, Enter (0 / 2 / 14) | 2.55 s (2.42-3.24) | 5.3 s | none | **Borderline**: over 5 s only because of the 14 characters typed. `Operatory` (9) finds it too, about 4.3 s. |
| W04a | Create a basic ticket in 15 s | On the ticket list | New ticket, pick client, click subject, type subject, Create Ticket (4 / 0 / 23). Client is not preselected. | 2.23 s (1.97-3.71) | 10.0 s | none | Yes (estimate) |
| W04b | same | On the client workspace | Create ticket (client preselected), click subject, type, Create Ticket (3 / 0 / 23) | 2.13 s (1.99-2.18) | 9.1 s | none | Yes (estimate) |
| W05 | Start or stop a timer in one click | Ticket detail, no timer running | Start timer (1 click); later Stop and log (1 click) | start 1.74 s, stop 1.64 s | 2.5 s | none | Yes on click count. **But**: the button sits 4129 px down the page (viewport 900 px), so a scroll is needed first; each click is a full page POST and reload (`psa/views.py:2659` redirects to the ticket page). |
| W06 | Authorized credential in 2-3 clicks | Ticket detail | Click the credential link (opens a **new tab**), click Reveal (2 / 0 / 0) | 1.20 s (1.15-1.48) | 2.8 s | none **on this credential**. The reveal view has gates that were not triggered by this demo row: a per-credential approval (`requires_reveal_approval`), access rules, and a 30-per-hour rate limit (`vault/views.py:260-310`). Each would add steps. | Yes (2 clicks) |
| W07 | Open a linked RMM device in one click | Ticket with a linked device | Click `Open in <RMM>` (1 / 0 / 0). Opens the RMM's own page in a new tab. | 0.24 s to the new tab request | 1.0 s | none on this side | Click count: yes. **Destination not measurable**: the demo peer host is an invented `.example` name, the harness blocked the request. |
| W08 | Linked endpoint health in one click | Client workspace | RMM tab (1 / 0 / 0): shows devices with stale / online state | 0.69 s (0.66-0.80) | 1.5 s | none | Yes. Demo devices show **STALE DATA** (no check-in since 2026-11-20), which the page says. |
| W09 | Remediation in 3 clicks, excluding approvals | Ticket with a paired device | Open "Refer a fix", click title, Tab, type description (the form refuses an empty one), Refer (3 / 1 / 71) | 2.06 s (1.92-2.26) | 18.7 s | Approval happens in the RMM, by design, and is excluded by the target. | Yes (3 clicks). The 71 characters are the cost. Nothing was sent to a real RMM. |
| W10a | Create a customer in 2 minutes | Client list | Create Organization, click name, type name, Create (3 / 0 / 25) | 1.71 s (1.62-1.81) | 9.1 s | none | Yes (estimate). Only creates the record: sites, contacts, contract, RMM mapping, onboarding are separate steps. |
| W10b | same, 12 fields | Create form | Name, legal name, address (4 fields), phone, email, website, contact name, email, phone, type (14 / 0 / 171) | 2.97 s (2.94-4.24) | 48.4 s | none | Yes (estimate), about 50 s of 120 s. |
| W11 | Customer health report in 3 clicks | Dashboard | Open the Business group, Client Health, customer row (3 / 0 / 0). Lands on `/client-health/<id>/`. | 1.37 s (1.22-2.48) | 3.8 s | none | Yes for reaching the health page. Whether a printable or sendable report exists was **not** checked. |
| W12 | Invoice draft from approved charges in 3 clicks | Dashboard, MSP organization selected | Open Business group, open the parent entry, Billing Review, tick a ticket, Create draft invoices for selected, **confirm dialog** (5 clicks + 1 confirm) | 2.91 s (1 run); page load 1.60 s | 6.9 s | A confirm dialog (`data-confirm`, `templates/psa/billing_review.html:203`). Kept: it is a guard, not a security control to remove. | **No**: 5 clicks (3 to reach the page, 2 on it) plus the confirm. The page itself needs 2 clicks plus the confirm. Result verified: invoice count 5 to 6. |
| W13 | Return from a linked page without losing context | Ticket detail | Workspace link, Back to PSA-... (2 / 0 / 0). Returns to `/psa/t/<n>/#ticket-rmm-panel`. | 2.40 s round trip | 3.6 s | none | Yes: back on the same ticket, scrolled to the panel. |
| W14 | Switch applications in one click | n/a | There is no application switcher in `templates/base.html` or the top bar. Agit8or Connect is off on the demo. | n/a | n/a | n/a | **Not measurable on the demo.** In standalone mode no switcher is correct (`CLAUDE.md`, standalone rules); needs a configured peer. |
| W15 | Pair applications in 5 minutes | n/a | `/settings/integrations/connected-apps/` returns 404 on the demo (`AGIT8OR_CONNECT_ENABLED` off, `config/settings.py:788`); pairing also needs a second application. | n/a | n/a | n/a | **Not measurable on the demo.** |

### Observations from the runs

- **Creating a customer appears to make it the session's current client.** After W10 ran, `/assets/17/` and the
  workspace link returned 404 in the same session (asset 17 belongs to Ridgeline) while the ticket page still loaded.
  Inferred from the 404s (the session was not inspected). Needs checking; if true, a technician who creates a customer
  mid-ticket gets 404s from links on the ticket they came from.
- The ticket page's device workspace link and `/assets/<id>/` return a bare 404 when the current client differs from the
  asset's client; nothing offers to switch (`assets/workspace_views.py:35-42`).
- Each ticket page load also fires `GET core/palette.json?parts=current&path=...` (28 queries, 74 ms) and two
  `POST .../presence/` calls within the first second (seen in the server log).
- W09 and W07 ran against the ticket RMM panel while `templates/psa/_ticket_rmm_panel.html` was being edited in the
  same worktree by another task; re-measure after that change lands.

## 3. Page baselines (section 20)

Median of 5 in-process requests after one warm-up. `Cold` is the first request after the process started. SQL ms is the
time the database reported (SQLite on a warm file: near zero), so time is almost all Python and template work. HTML is
the response size. All pages returned 200.

Existing ceilings: `core/tests/test_page_budgets.py` (`BUDGETS`, superuser / technician) cover 10 pages. They run on a
near-empty fixture, so they do not see data-dependent cost; compare the last two columns.

| Rank | Page | Median ms | Cold ms | Queries | SQL ms | HTML KB | Existing ceiling (su / tech) |
|---|---|---|---|---|---|---|---|
| 1 | Ticket detail (`/psa/t/PSA-2026-000036/`) | 826 | 928 | **214** | 5 | 240 | 96 / 100 |
| 2 | Billing review | 497 | 610 | 61 | 37 | 178 | 26 / none |
| 3 | Dispatch board | 474 | 491 | **328** | 0 | 189 | none |
| 4 | My Work | 417 | 455 | 69 | 4 | 197 | none |
| 5 | Client workspace (Ridgeline) | 350 | 359 | 66 | 6 | 201 | none |
| 6 | Ticket list | 333 | 348 | 22 | 2 | 230 | 31 / 36 |
| 7 | Ticket create form | 298 | 290 | 20 | 1 | 160 | none |
| 8 | Invoice detail | 272 | 469 | 26 | 3 | 165 | none |
| 9 | Asset detail | 253 | 626 | 37 | 33 | 236 | none |
| 10 | Security dashboard | 253 | 231 | 36 | 1 | 212 | none (cold run seen at 7.6 s once) |
| 11 | Invoice list | 252 | 393 | 15 | 10 | 162 | none |
| 12 | Dashboard | 218 | 1081 | 22 | 1 | 223 | 31 / 37 |
| 13 | Reports home | 210 | 337 | 15 | 6 | 176 | none |
| 14 | Client health list | 193 | 288 | 30 | 4 | 159 | none |
| 15 | Quote detail | 187 | 175 | 26 | 1 | 164 | none |
| 16 | Global search (`?q=server`) | 173 | 199 | 34 | 3 | 158 | none |
| 17 | Document list | 173 | 231 | 16 | 0 | 217 | 24 / 28 |
| 18 | Asset list | 167 | 185 | 23 | 1 | 177 | 29 / 33 |
| 19 | Contract detail | 163 | 169 | 23 | 0 | 158 | none |
| 20 | PSA reports list | 158 | 188 | 10 | 5 | 158 | none |
| 21 | Client operations | 150 | 176 | 29 | 0 | 163 | none |
| 22 | Integrations list | 144 | 546 | 26 | 0 | 179 | 35 / 39 |
| 23 | RMM devices | 142 | 166 | 16 | 0 | 160 | none |
| 24 | Quote list | 140 | 168 | 11 | 0 | 159 | none |
| 25 | Client list | 135 | 521 | 12 | 1 | 167 | none |
| 26 | Settings home | 132 | 119 | 10 | 2 | 173 | 19 / 22 |
| 27 | Global KB list | 126 | 143 | 13 | 0 | 162 | none |
| 28 | Timesheet | 126 | 192 | 12 | 0 | 157 | none |
| 29 | Contract list | 121 | 141 | 15 | 0 | 158 | none |
| 30 | Vault list | 119 | 128 | 10 | 1 | 156 | 19 / 24 |
| 31 | Palette home (JSON) | 74 | 74 | 28 | 0 | 40 | none |
| 32 | Palette search (JSON, `q=ridge`) | 51 | 66 | 20 | 7 | 1 | none |
| 33 | Wallboard data (JSON) | 34 | 34 | 26 | 1 | 2 | none |

Not measured: `core/clients/switcher-search/` (my probe got an HTML page, so the parameter is not `q`), a non-superuser
technician, a customer-portal user, and anything behind a second factor. `psa:billing_review` is 61 queries here
against a ceiling of 26 because the demo has billing data and the test fixture does not.

### What the query logs show

Counted by normalizing the SQL of one request (`CaptureQueriesContext`):

- **Ticket detail, 215 queries.** The largest repeats are authorization lookups: `tech_access_containments` 21 times,
  `auth_user` 14, `tech_access_denies` 13, `tech_access_customer_policies` 13, `tech_access_assignments` 13 plus 8
  more joins. The same capability data is read once per capability check, not once per request.
- **Dispatch board, 328 queries.** Per-technician repeats: user profile 44, group membership 40, ticket counts 37,
  skills 36, active membership 36, shift assignment lookups. Cost grows with technicians (4 on the demo).
- Page weight is 155 to 240 KB of HTML for every page, about 150 KB of it the shared shell (navigation and menus), which
  is rendered on each request.

## 4. Synthetic scale datasets (described, not built)

Targets from section 20: 10 customers / 100 endpoints, 60 / 1,200, 200 / 5,000, larger if the hardware allows,
several technicians at once, substantial ticket, asset and document history.

**Does a seeding command exist?** Not for volume.

| Command | What it does | Scale support |
|---|---|---|
| `scripts/demo/seed_demo.py` (and `setup_demo.py`) | the fixed demo: 6 organizations, hand-written content, many named scenario seeds | none; fixed content |
| `manage.py seed_module_samples` | additive sample data for modules; `--customers` takes a list of existing slugs, `--techs`, `--only` | no counts; scales only by how many organizations you already have |
| `manage.py seed_demo_data` | one demo company | none |
| `manage.py seed_all` | equipment catalog and global KB articles | `--quick` shrinks it; unrelated to customers |
| `manage.py import_demo_data` | loads demo data | none |

So the datasets need a new generator. Proposed design (planned):

1. A script `scripts/ux/seed_scale.py` (not built). Runs with `demo_settings` against a **copy** of the demo database,
   refuses anything that is not a demo SQLite file (same guard as `scripts/capture_screenshots.py`). Deterministic
   (`random.seed`), additive, idempotent by name prefix `SCALE-`.
2. Profiles by flag: `--profile s|m|l|xl` or `--customers N --endpoints M`:

   | Profile | Customers | Endpoints (Asset + RMM device) | Tickets (3 years) | Documents | Credentials | Contacts | Invoices |
   |---|---|---|---|---|---|---|---|
   | S | 10 | 100 | about 1,000 | 150 | 100 | 100 | 120 |
   | M | 60 | 1,200 | about 15,000 | 900 | 600 | 600 | 720 |
   | L | 200 | 5,000 | about 60,000 | 3,000 | 2,000 | 2,000 | 2,400 |
   | XL | 500 | 15,000 | about 200,000 | per hardware | | | |

   The ratios (about 17 to 25 tickets per endpoint over history, 4 comments and 2 time entries per ticket, 12 invoices
   per customer) are proposals to be adjusted against a real install's counts, not measurements.
3. Use `bulk_create` in batches inside one transaction per customer; set `created_at` across the history so list
   ordering and date filters are realistic; endpoints get Asset rows plus `RMMDevice` rows on one inactive
   connection (no outbound calls, as in the demo).
4. Workload: `workflow_benchmarks.py` already takes any base URL; add a mode that runs 5, 10 and 20 Playwright
   contexts at once with a mixed script (find, open ticket, add comment, start timer, reports home), and `page_baseline.py`
   run against each profile. Use gunicorn with the production worker count (8) for the concurrent runs, not `runserver`.
5. Record per run: hardware, load average, profile, row counts, median and p95 per page, queries per page, peak
   RSS of the web workers, and whether any page exceeded its target. Repeat on MariaDB if a production-like database
   is available: all numbers here are SQLite and will not transfer.

Known limits of this baseline: one small dataset, one user type, loopback network, a busy host, SQLite only, no
concurrent users, no browser-side rendering metrics (only the wall-clock result time).

## 5. Ranking

### Slowest pages (this dataset)

1. Ticket detail: 826 ms, 214 queries. Most-used page; cost is authorization lookups repeated per check.
2. Billing review: 497 ms, 61 queries (the only page with noticeable SQL time, 37 ms).
3. Dispatch board: 474 ms, 328 queries; grows with the number of technicians.
4. My Work: 417 ms, 69 queries; it is the technician's home page.
5. Client workspace: 350 ms, 66 queries.
6. Ticket list: 333 ms for only 22 queries (template and 230 KB of HTML).

Cheapest wins by query count: dispatch board, ticket detail, My Work, client workspace.

### Workflows furthest from target

1. **W12 invoice draft**: 5 clicks plus a confirm against a target of 3 (measured).
2. **W14, W15 application switch and pairing**: cannot be measured without a configured peer; Connect is off on the demo.
3. **W05 timer**: one click, but 4,000+ px down the page and a full reload, 1.7 s each way (measured).
4. **W03 find a ticket**: borderline at about 5 s with a 14-character query (estimate).
5. **W06 credential**: 2 clicks, but the reveal gates (approval, access rules) were not exercised and would add steps.
6. **W09 remediation**: 3 clicks, but needs a 71-character description (estimate 19 s).

Everything else meets its click or time target on this dataset (W01, W02, W04, W07 click count, W08, W10, W11, W13).

## 6. Proposed P0 increments

Each is small and shippable; none removes an approval, confirmation or server-side check.

1. **Per-request cache for technician access decisions (ticket detail).** Memoize `tech_access` lookups
   (containments, denies, customer policy, assignments) on the request, keyed by user, customer and capability.
   Acceptance: ticket detail for demo ticket 36 as superuser runs 100 queries or fewer (now 215) and no table in the
   top-5 repeat list is read more than twice; median time 400 ms or less on a similar load; add the rich ticket (RMM
   panel, devices, comments) to `core/tests/test_page_budgets.py` with a ceiling; a permission test shows a denied
   technician is still denied (the cache is per request, so no staleness).
2. **Dispatch board without per-technician queries.** Prefetch profile, groups, skills, memberships, shifts and counts
   for all technicians in one query each. Acceptance: query count the same for 4 and 20 technicians (test, like the
   existing scaling tests), 60 or fewer on the demo (now 328), and a ceiling in `BUDGETS`.
3. **Budgets for the pages that have none.** Add My Work, client workspace, billing review (with data), dispatch,
   palette home, palette search, global search. Acceptance: each has a ceiling in `BUDGETS` and a scaling test.
4. **Palette home: one request, no per-page fetch.** `parts=current` runs 28 queries on every page load. Acceptance:
   at most 10 queries and cached per user for the request window, or fetched only when the star menu opens.
5. **Timer reachable and fast.** Show start / stop in the ticket header (first viewport) and in My Work; submit without
   a full page reload and update a visible running indicator. Acceptance: Start timer is inside the first 900 px on
   ticket detail; click to visible "Running" in 300 ms or less on the demo (now 1,740 ms); still one click; the same
   server checks (`_staff_or_403`, `tickets_edit`) apply; works without JavaScript as a normal POST.
6. **Billing: reach Billing Review in one click and prepare the invoice in two.** Make Billing Review a top-level
   entry or a default pin, and let "Create draft invoices" act on a customer's ready tickets from one control (tick
   all by default, with the existing confirmation kept). Acceptance: W12 is 1 click to the page, 1 to create, 1 to
   confirm (3 total, the confirm counted), invoice count increases, and nothing is sent.
7. **Synthetic dataset generator and the first M-profile run.** Build `scripts/ux/seed_scale.py` as in section 4 and
   publish the 10/100, 60/1,200 and 200/5,000 results beside these numbers. Acceptance: each profile builds on a demo
   copy in under 15 minutes, `page_baseline.py` and a 5-technician concurrent run complete, and the results table
   records hardware, load, row counts, median and p95.
8. **Investigate the session-context 404** (observation above): confirm whether creating a customer switches the
   current client, and make cross-client links on a ticket either switch with a notice or explain the 404.
   Acceptance: a test that opens a ticket's device workspace link after the current client changed.

## 7. How to reproduce

```bash
# 1. a copy of the demo database (never run the benchmark against the shared instance)
python - <<'PY'
import sqlite3, os
os.makedirs('/tmp/bench/db', exist_ok=True)
s = sqlite3.connect('file:/var/tmp/clientst0r-demo/demo.sqlite3?mode=ro', uri=True)
d = sqlite3.connect('/tmp/bench/db/demo.sqlite3'); s.backup(d)
PY
export DEMO_DIR=/tmp/bench/db DJANGO_SETTINGS_MODULE=demo_settings PYTHONPATH=scripts/demo:.
# 2. page baseline (in process, read-only apart from one session row)
python scripts/ux/page_baseline.py --runs 5 --json pages.json
# 3. serve the copy and run the workflows (needs a session key per user/organization; see scripts/capture_screenshots.py make_session)
DEMO_PORT=8123 python manage.py runserver 127.0.0.1:8123 --noreload --settings=demo_settings &
python scripts/ux/workflow_benchmarks.py --base http://127.0.0.1:8123 --cookie sessionid=KEY \
    --msp-cookie sessionid=KEY2 --runs 5 --allow-writes --json workflows.json
```

Run the creating workflows (W04, W05, W09, W10, W12) only against the copy. W10 is listed last because creating a
customer changes the session's context (see observations).

## 113.9 invoice draft (W12, part B)

Counted from the code paths and the test client (`psa/tests/test_billing_113_9_draft.py`), not re-timed in a browser.

| | Path | Clicks |
|---|---|---|
| Before | Open the Business group, Billing (lands on Aging Report), Billing Review, tick a ticket, Create draft invoices for selected, confirm dialog | 5 + confirm (6) |
| After | **Ready to invoice** (dashboard figure, or the Billing summary panel's link) opens Billing Review at Ready for Billing; **Create draft** on the customer opens the preview with every line, coverage and total; **Confirm** | 3, including the kept confirmation |

- The confirmation is kept as a full preview page instead of a browser dialog: it shows more than the dialog did
  (every line, rate, coverage, per-draft subtotal and the total before tax), and the confirm POST is refused when
  anything changed since the preview (a digest of the previewed lines) or when nothing is left (double submit).
- The old buttons and their confirm dialogs are unchanged for drafting a selection of tickets.
- **Ready to invoice** is in the widget catalog (Customize) and not in any built-in preset, because every preset
  already shows the maximum of seven figures. Out of the box the one-click entry is the Billing summary panel's
  **Ready to invoice** link (in the Service Manager preset, which Billing / Finance users get). For the
  Owner / Administrator preset it is one click after adding the figure; through the sidebar it is still 3 clicks
  to reach Billing Review.
- Not timed: re-run W12 with `scripts/ux/workflow_benchmarks.py` against a copy to record the time.

### 113.9 results

**W05 timer (part A of 113.9).** Before: the Start timer button sat 4,129 px down the ticket page and each click
was a full POST, redirect and reload, 1.74 s to start and 1.64 s to stop (measured above).

After, on a runserver of `dev/ux-113-9` against a backup-API copy of the demo database (Chromium 1440x900,
`scripts/ux/workflow_benchmarks.py --only W05 --runs 5 --allow-writes`, machine under load):

| Measure | Before | After |
|---|---|---|
| Timer control position | 4,129 px down the page | 287 px down the page, first element of the main column, inside the first viewport |
| Start (click to running state visible) | 1.74 s, full page reload | median 281 ms (275 to 295), no reload |
| Stop (click to stopped state visible) | 1.64 s, full page reload | median 505 ms, no reload (includes the harness click overhead) |
| Server time, start / stop | not measured | 103 ms / 91 ms (test client) |
| Server checks | permission, ownership | unchanged: same views, same checks, same time entry |

Also checked in the browser: the document is not reloaded (a window marker survives start and stop, no navigation
events); `aria-pressed` flips and the live region says "Timer started." / "Timer stopped, N minutes logged."; the Time &
Charges card's own Start / Stop controls follow the inline control; a timer started in a second tab shows in the first
on focus. Workspace layout: Essentials folds the secondary ticket cards (5 More buttons on the demo ticket) and 6 My
Work panels, More/Less toggles with `aria-expanded`; Advanced opens the optional `<details>` sections; no page errors.
The W05 script now uses the inline control when the page has it and falls back to the old card otherwise.

### Scale run — 60 customers / 1,200 endpoints

Part B of increment 113.7: the generator `scripts/ux/seed_scale.py` and the runner `scripts/ux/scale_benchmark.py`
(this is the first published run; the 10/100 and 200/5,000 profiles are built by the same command and not yet run).

**What was run.** `seed_scale.py --profile medium --with-rmm` into a fresh SQLite file under `/var/tmp`, then
`scale_benchmark.py --runs 3` (in-process Django test client, median of 3 after one warm-up request, query counts from
`CaptureQueriesContext`). Two users: `scale.super` (superuser technician) and `scale.l1` (L1 Tech role, client scope
"selected" = 6 of the 60 customers). Reproduce:

```bash
nice -n 10 python scripts/ux/seed_scale.py /var/tmp/clientst0r-scale-60/demo.sqlite3 --profile medium --with-rmm
nice -n 10 python scripts/ux/scale_benchmark.py /var/tmp/clientst0r-scale-60/demo.sqlite3 --runs 3 --md out.md --json out.json
```

The generator refuses an existing non-empty file, the production database, and any path outside `/var/tmp` and the
scratchpad. Migrations on an empty SQLite database took about 23 minutes on this loaded machine (591 migration files);
`--save-template` stores the migrated empty database and `--template` starts later builds from it (the build then takes
under a minute).

**Environment.** 40 vCPU (QEMU Virtual CPU version 2.5+), 31 GB RAM, Linux 6.8, SQLite (not MariaDB: numbers will not
transfer). The machine was shared and busy: load average 13.4 / 14.4 / 13.1 (1/5/15 min) at the end of the run, 15.8 at
the start, so absolute times are inflated and noisy; query counts are exact. The database file is 48 MB.

**Code state.** Measured on the working tree of branch `dev/ux-113-7` at 2026-11-25 19:16, which at that moment
contained the other agent's uncommitted query optimisations (25 files, 470 insertions, 102 deletions outside docs and
tests; among them `psa/views.py`, `psa/sla.py`, `core/palette.py`, `core/search_views.py`, `core/workspace.py`,
`tech_access/resolver.py`, `resourcing/shifts.py`, `resourcing/views.py`). So this is neither the base commit nor a
final state: treat it as "branch at that time" and re-run after the optimisation work is committed.

**Dataset (generated in 48 s with the template, deterministic seed 20261125).** 60 customers (+1 MSP tenant), 89
locations, 600 contacts, 1,200 assets, 865 RMM device rows (workstations, laptops and servers; one inactive
connection), 15,000 tickets over 3 years with 60,124 comments and 22,525 time entries, 850 documents (including 10
global KB articles), 600 vault entries, 60 contracts, 60 quotes, 720 account charges, 720 invoices, 9 technicians in
the L1/L2/L3 access groups.

**Results** (ms of server time / SQL queries / HTTP status; median of 3):

| Page | superuser: ms / queries / status | L1 technician (10% of customers): ms / queries / status |
|---|---|---|
| Dashboard | 238 / 23 / 200 | 13 / 10 / 302 |
| Ticket list | 1056 / 24 / 200 | 245 / 26 / 200 |
| Ticket detail | 502 / 81 / 200 | 23 / 11 / 404 |
| Ticket create form | 305 / 21 / 200 | 258 / 17 / 200 |
| My Work | 630 / 61 / 200 | 372 / 34 / 200 |
| Dispatch board | 623 / 29 / 200 | 3578 / 35 / 200 |
| Client workspace | 328 / 61 / 200 | 27 / 13 / 302 |
| Client list | 153 / 13 / 200 | 304 / 18 / 200 |
| Client operations | 145 / 26 / 200 | 32 / 10 / 404 |
| Asset list | 235 / 24 / 200 | 373 / 22 / 200 |
| Asset detail | 226 / 34 / 200 | 60 / 13 / 404 |
| Global search (q=server) | 205 / 33 / 200 | 290 / 22 / 200 |
| Palette home JSON | 50 / 18 / 200 | 106 / 21 / 200 |
| Palette search JSON (q=ridge) | 59 / 19 / 200 | 222 / 20 / 200 |
| Client switcher search JSON | 120 / 11 / 200 | 306 / 18 / 200 |
| Reports home | 156 / 15 / 200 | 304 / 21 / 200 |
| PSA reports list | 128 / 10 / 200 | 192 / 16 / 403 |
| Client health list | 166 / 13 / 200 | 266 / 18 / 200 |
| Billing review | 4729 / 974 / 200 | 257 / 17 / 200 |
| Invoice list | 314 / 16 / 200 | 198 / 19 / 200 |
| Invoice detail | 194 / 27 / 200 | 219 / 19 / 403 |
| Contract list | 222 / 32 / 200 | 211 / 17 / 200 |
| Contract detail | 220 / 32 / 200 | 29 / 11 / 404 |
| Quote list | 205 / 12 / 200 | 326 / 17 / 200 |
| Quote detail | 203 / 28 / 200 | 388 / 35 / 200 |
| Document list (KB/docs) | 192 / 17 / 200 | 292 / 17 / 200 |
| Global KB list | 165 / 14 / 200 | 32 / 12 / 302 |
| Vault list | 119 / 11 / 200 | 235 / 18 / 200 |
| RMM devices | 152 / 17 / 200 | 289 / 20 / 200 |
| Integrations list | 172 / 27 / 200 | 287 / 29 / 200 |
| Settings home | 136 / 11 / 200 | 312 / 16 / 200 |
| Security dashboard | 224 / 35 / 200 | 17 / 8 / 302 |
| Timesheet | 236 / 13 / 200 | 323 / 19 / 200 |
| Wallboard data JSON | 342 / 41 / 200 | 484 / 47 / 200 |

Reading the L1 column: a non-200 status is an authorisation outcome, not a failure of the page. The page set picks
sample records from the first customer; the L1 role is limited to its scope and permissions, so ticket detail, client operations, asset detail and contract detail answer 404, the dashboard,
client workspace and global KB redirect (302) and invoice detail and PSA reports answer 403. Times for those rows are
the cost of refusing, not of rendering.

**Ten slowest pages, superuser** (ms / queries / SQL ms):

| Page | Server ms | Queries | SQL ms |
|---|---|---|---|
| Billing review | 4,729 | 974 | 803 |
| Ticket list | 1,056 | 24 | 141 |
| My Work | 630 | 61 | 191 |
| Dispatch board | 623 | 29 | 10 |
| Ticket detail | 502 | 81 | 2 |
| Wallboard data JSON | 342 | 41 | 306 |
| Client workspace | 328 | 61 | 8 |
| Invoice list | 314 | 16 | 4 |
| Ticket create form | 305 | 21 | 0 |
| Dashboard | 238 | 23 | 17 |

**Ten slowest pages, L1 technician** (200 responses only matter here, the rest are refusals):

| Page | Server ms | Queries | SQL ms |
|---|---|---|---|
| Dispatch board | 3,578 | 35 | 392 |
| Wallboard data JSON | 484 | 47 | 382 |
| Quote detail | 388 | 35 | 17 |
| Asset list | 373 | 22 | 16 |
| My Work | 372 | 34 | 4 |
| Quote list | 326 | 17 | 4 |
| Timesheet | 323 | 19 | 37 |
| Settings home | 312 | 16 | 3 |
| Client switcher search JSON | 306 | 18 | 14 |
| Client list | 304 | 18 | 5 |

**Findings.** Billing review is the outlier by far: 974 queries for 60 customers (about 16 per customer), so its query
count grows with the customer count and the 113.7 "billing review budget" is the first thing to fix at this scale
(the same page ran 45 queries on the 3-customer test set). Ticket list is the slowest ordinary page at 1.1 s with only
24 queries: the cost is the 15,000-row table (count, ordering and filtering), not the query count. The L1 dispatch
board takes 3.6 s with 35 queries and only 392 ms of SQL, so the time is in Python for a scoped user (a per-technician
or per-customer loop outside the ORM). Pages other than those named stay under about 500 ms at this load.

**Gaps.** Single user at a time: the 5/10/20-technician concurrent run, p95 and web-worker RSS are not done. MariaDB
was not tested. The page set is the page_baseline set (33 pages); search with a term that matches many rows, ticket
list filters and pagination depth are not covered. Running the 10/100 and 200/5,000 profiles is open.

## 113.7 results — page performance, part A

Measured 2026-11-25 with `scripts/ux/page_baseline.py` (median of 5 after a warm-up, in-process test client,
user `demo.tech`) on two fresh copies of the demo database made with the SQLite backup API and migrated: one served
by the code before this change (commit `2efe8881e`), one by the change. The two were run alternately, twice each.
**Load average 12.4 to 13.2 (1 minute) on 40 CPUs** during the page runs — higher than for section 3 — so times
are noisy (pages this change does not touch moved by up to 2x between runs). Queries are exact; for times, the
back-to-back column (7 requests each, old and new code one after the other, same load) is the fairer comparison.

| Page | Queries before | Queries after | Median ms before (2 runs) | Median ms after (2 runs) | Back-to-back median ms, before → after |
|---|---|---|---|---|---|
| Ticket detail (PSA-2026-000036) | 214 | **99** | 768, 789 | 1090, 1210 | 1475 → 1063 (first pair), 1616 → 1041 (second pair) |
| Dispatch board | 328 | **27** | 481, 493 | 372, 550 | 432 → 158 |
| Palette home (full, on open) | 32 | 25 | 73, 89 | 91, 69 | 72 → 61, 69 → 73 (same within noise) |
| Palette star check (`?parts=starred`, every page load) | 13 (`?parts=current` on a ticket page) | **7** | — | — | — |
| Palette search (`q=ridge`) | 20 | 18 | 44, 45 | 71, 40 | — |
| Global search (`q=server`) | 34 | 32 | 167, 166 | 198, 163 | — |
| My Work | 69 | 66 | 392, 431 | 643, 917 | — |
| Client workspace | 66 | 66 | 309, 331 | 425, 313 | — |
| Billing review | 61 | 61 in these runs; **32** after the batched reads below (not timed here) | 288, 318 | 293, 291 | — |

The ticket page's median in the paired runs is higher after, but the back-to-back pairs (same minute, same load)
show it faster and running about a third fewer Python function calls (680k against 1.0M under cProfile). The
acceptance target of 400 ms for ticket detail is **not** met at this load; it was not met before either.

The rendered HTML of ticket detail, dispatch board, My Work, billing review, global search and both palette answers
was compared for six users (superuser technician, two staff technicians, three customer users) at each of the six
demo organizations, old code against new: identical apart from CSRF tokens and a running timer's elapsed seconds.

### What changed

1. **Technician-access rows read once per request** (`tech_access/request_cache.py`). Containment, explicit denies,
   customer policy, assignments (with their presets and groups), what the customer's paired RMMs advertise, and the
   RMM permission overrides are memoised in the request's authorization context (`accounts.authz_cache`, bound by
   `CurrentOrganizationMiddleware`). The rows are memoised, never the decisions: every check still runs the full
   rule order with its own `now`. Outside a request (jobs, commands, scheduler) nothing is memoised. A save, delete
   or group-membership change of a rule row in the request drops the memo; a change that sends no signal (another
   process, `QuerySet.update()`) is seen from the next request — `integrations.ticket_rmm._save` calls
   `invalidate()` after its own `update()`.
2. **Ticket page reads deduplicated** with the same memo or by reusing rows already read: the AI master switch and
   the customer's AI policy, the customer's PSA switch, the active agreement and its prepaid summary, affected
   devices, the customer's asset picker list, each asset's RMM devices, RMM requests, ticket statuses, watchers, the
   last comment id, the running-timer and "time logged" checks.
3. **Dispatch board** reads every technician's skills, memberships, shifts, working hours, leave and open-ticket
   counts once (`resourcing.views.RankingFacts`, `resourcing.shifts.ShiftBook`) instead of once per ticket card and
   technician, and selects profiles with the technicians. 4 and 20 technicians now run the same number of queries.
4. **Palette**: the top bar's star asks `?parts=starred`, which answers without building the navigation when the
   page has no favorite row (7 queries); the navigation context, permission probe and search scope are built only
   when used; recent hardware devices select their asset.

### Budgets (`core/tests/test_page_budgets.py`)

The budget fixture now has several technicians with tickets, two tickets with work, five assets (one the ticket's
device, one affected), and an agreement with approved time this month. Ceilings (superuser / technician) are the
measured count plus headroom: ticket detail 104 / 108 (the code before this change ran 115 / 119 on the same
fixture, and the dispatch board 296 / 368), billing review 34 / 39, My Work 64 / 65, client workspace 67 / 68,
dispatch board 35 / 40, palette home 22 / 27, palette star check 9 / 9, global search 38 / 42. Scaling tests: the
dispatch board runs the same queries for 4 and 20 technicians; My Work, client workspace, billing review, both
palette answers and search run the same queries with more tickets, work and a second customer with agreements.

### Billing review at 60 customers

The scale run above showed billing review running 974 queries at 60 customers against 45 at 3: per customer, ticket
and agreement. It now reads everything once for all of them, and every amount is computed by the same code as before
(only the reads moved):

* **Agreement rows** (`psa.billing_review.build_rows`): which agreements have a prepaid ledger, the ledger's cycle and
  to-date sums and summaries (`ledger.totals_many`, `ledger.summaries_many`: the same `SUM` over the same postings,
  grouped by agreement as well, folded by the same code), the cycle's invoices, and the qualifying time of agreements
  without a ledger (each agreement's own `Contract.qualifying_time_entries()` queryset, combined with `UNION ALL`).
* **Ready for Billing queue** (`psa.billing.queue.build_queue`, `invoicing.ticket_billing_lines_many`): unbilled time
  and items of all queued tickets, their ledger postings, the pricing cutoff, held / excluded and other queue
  decisions, running timers, recurring-fee agreements per customer with their signed contract documents (the
  month-to-month e-signature exemption is read from the request's settings copy), the customers' agreements for every work date
  (`coverage.preload_agreements`: same filter, dates applied in Python to rows kept in the database's order) and the
  billing rules (`pricing.services.BillingRuleBook`: rows in the database's `-effective_from, -pk` order, first match
  per scope in the same precedence as `resolve_billing_rule`).

| Billing review | Before | After |
|---|---|---|
| Scale database, 60 customers, superuser | 975 queries | **32** |
| Scale database, L1 technician | 17 | 18 (no billing rows in its scope; the difference is in the shared page frame) |
| Demo database, superuser | 61 | 32 |

Checked: the rendered page is identical to the old code's (CSRF tokens aside) for 36 renders on the scale database
(two users, six organizations, three filters; pages of 690 KB with 605 rows) and 54 on the demo database (which has a
ledger agreement and a queue decision). `psa/tests/test_billing_batch_reads.py` compares each batched reader with the
per-item one on a mixed fixture (prepaid overage, unapproved time, chargeable and onsite time with fees, items, held
and excluded lines, a running timer, agreements and billing rules at every scope with open, closed, future and
inactive windows), and the budget scaling test runs the same queries with one or two customers holding agreements.

### Dispatch board for the L1 technician (3.2 s)

Not a query problem: 35 queries, about 0.3 s of SQL. The rest is template rendering of **1,000 ticket cards
(3.2 MB of HTML)**. The board's grid query (`psa.views.dispatch_board`) takes the newest 1,000 tickets of the
request's organization, or of **every** customer when there is none: for `scale.l1` (client scope "selected", 6
customers) the board showed tickets of all 60 customers. The code before this change does the same (checked on
commit `2efe8881e`). It is reported as an authorization finding and not changed here, because 113.7 keeps every
allow/deny decision as it was. The superuser's board in the MSP organization shows 10 cards and renders in about
0.6 s. Scoping the grid like the board's own unassigned count (`_scoped_ticket_qs(request)`) would fix both.

### Not done in this part

My Work (66) and client workspace (66) have budgets but were not restructured; the ticket page
is at 99 of its 100-query target on the demo with the remaining reads spread over many different queries (time
entries 7, comments 5, AI history, routing, knowledge suggestions).
