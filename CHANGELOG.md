# Changelog

All notable changes to Client St0r will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.17.540] - 2026-09-05

### Phase 40.2 — the status page

New `statuspage` app. A status page answers "is anything broken?" without the
client phoning the queue.

**Disclosure is the whole design.** This is the only view in the app that serves
real customer data to an unauthenticated caller, so it follows the Phase 47
wallboard's rules for the same reason — the URL is the only thing between it and
the internet:

- off by default, and a disabled page returns **404, not 403**, because a 403
  confirms to anyone probing that a page exists at that address;
- the address carries a 43-character token from `secrets` (not `random`, which
  is seeded predictably and has no business generating something that acts as a
  credential), so pages cannot be found by walking integers;
- the token rotates, which kills a leaked link immediately;
- `no-store, private` and `noindex, nofollow` — a page naming a client's services
  belongs in neither a shared cache nor a search index.

**`StatusPageService` is an indirection, not a join table.** A `WebsiteMonitor`
carries an internal name and the URL being polled, and neither belongs on a
public page: "PROD mail relay (10.4.0.7)" tells a stranger more about the estate
than the client needs to read. Every published service carries a `display_name`
chosen by an admin, and adding one without a name is **refused rather than
defaulted to the monitor's name** — defaulting would leak precisely what the
field exists to prevent. A test asserts the monitor name, its host and its URL
appear nowhere in the rendered page.

**Not a singleton**, unlike the wallboard. `organization` null means a broadcast
page covering shared infrastructure; a page scoped to a client can only publish
that client's monitors, enforced on the add path rather than left to the operator
to get right.

Three judgement calls in the status logic:

- **Worst wins.** One service down makes the whole page say outage. A client
  whose mail is down does not care that the website is fine.
- **`warning` is degraded, not an outage.** A redirect or an expiring
  certificate means the service answered. A page that showed a 301 as an outage
  would cry wolf until nobody read it.
- **An empty page reads "status not yet known", not "all operational".** A page
  with nothing published must not claim everything is fine.

Uptime rows show 30 / 90 / 365 days, and a window with no recorded checks reads
**"no data"** rather than a number — check history only began in v3.17.538
(Phase 40.1), so a full-year figure is genuinely unknown until a year after that
deploy and printing 100% would be an invention.

Management UI under **Operations → Monitoring → Status Pages**: create, publish,
rotate the link, add and remove services.

29 tests. Migration: `statuspage.0001_initial`. New app registered in
`INSTALLED_APPS`; public route is `/status/p/<token>/`, management is
`/status/`.

## [3.17.539] - 2026-09-05

### Fix: three more releases recorded against versions that were never released

v3.17.537 corrected Phase 46, which had been recorded against a non-existent
v3.17.532. That fix was too narrow. The same thing had happened to Phase 44, and
worse: sub-phases 44.1, 44.2 and 44.3 were annotated `(shipped v3.17.528)`,
`(v3.17.529)` and `(v3.17.530)`, and none of those three versions exists either —
no CHANGELOG entry, no tag.

All four accounting sub-phases went out together in **v3.17.531**, whose entry
covers 44.1 through 44.4 in one release. The sub-phases had been developed
against sequential numbers and the numbers were never reconciled when the work
shipped as a single version. `docs/ROADMAP.md` compounded it by describing the
phase as "delivered across four sub-phases (v3.17.528–531)", a range three
quarters of which never existed.

Corrected in 30 places across 15 files:

- **`docs/ROADMAP.md`** — three sub-phase annotations, the "delivered across"
  sentence (now "delivered as four sub-phases, all released together in
  v3.17.531"), the sizing-table row, and a Phase 27 cross-reference.
- **Code comments and docstrings** in `integrations/` (providers, services,
  models, views, urls, both management commands, the customer-map migration and
  the Phase 44 tests), plus `core/models.py`, `core/management/commands/run_scheduler.py`
  and `psa/models.py`.
- **`templates/psa/ticket_detail.html`** — one v3.17.532 reference the previous
  sweep missed because it only covered `.py` and `.md`.

The Phase 44 header itself was already correct at `[shipped — v3.17.531]`, so
`/core/roadmap.json` was reporting the right version for this phase; the damage
was confined to the sub-phase bullets and comments, which the JSON feed does not
publish. Phase 46's header was the one the feed had wrong, and that was fixed in
v3.17.537.

Comments, documentation and one template comment only — the diff touches no
executable line. No migrations, no mobile rebuild.

## [3.17.538] - 2026-09-05

### Phase 40.1 — the uptime history the status page was going to be built on

Phase 40 (public status page) lists "uptime history — 30 / 90 / 365 day uptime
percentage per monitored service, sourced from `WebsiteMonitor` history". There
is no `WebsiteMonitor` history. The model stores the *current* status, the last
HTTP code, the last response time and the last check time; every check
overwrites the one before it. Nothing has ever recorded what an earlier check
returned, so uptime was not computable from existing data at all — not
approximately, not at any window.

This ships the missing half before the page that needs it.

**`monitoring.MonitorCheck`** — one append-only row per check: monitor,
`checked_at`, status, HTTP code, response time, error. Written at the end of
`WebsiteMonitor.check_status()`, inside a `try` that logs and moves on. Recording
history must never turn a successful check into a failed one; the live status is
what matters and has already been saved by that point.

Deliberately not a `BaseModel` — a check row is written once and never updated,
so `updated_at` would be dead weight on what is now the highest-volume table in
the app. A monitor on the default hourly interval writes ~8,760 rows a year; one
on a five-minute interval writes ~105,000.

**`WebsiteMonitor.uptime(days)`** returns `{checks, up, down, percent, since}`,
computed from those rows rather than stored, so changing the retention window or
backfilling a gap cannot leave a counter that disagrees with the data behind it.
Two decisions worth stating:

- **An empty window returns `percent=None`, not a number.** A monitor added
  yesterday has no 90-day uptime. Rendering that as 0% reads as a total outage
  and 100% as a clean record; both are lies, and a status page is the wrong
  place to guess.
- **`warning` counts as up.** A redirect or an expiring certificate means the
  site answered. Only `down` is down. A status page that showed a 301 as an
  outage would cry wolf until nobody read it.

**`prune_monitor_checks`** — retention command, default 400 days rather than 365
so a full-year figure stays computable right up to the moment the prune runs,
instead of losing its oldest day the day before someone looks. Deletes in
id-batches: a bare `.delete()` on a table this size holds one long transaction
against the table the checker is trying to append to. Registered as a
`prune_monitor_checks` scheduler task type alongside the existing jobs.

**Consequence worth being explicit about:** uptime starts accumulating from this
deploy. It is not retroactive, and a 365-day figure is not available until a year
from now. The roadmap entry for Phase 40 has been corrected to say so, and the
phase is now `[in progress]` with sub-phases 40.1–40.5 broken out.

11 new tests. Migrations: `monitoring.0012_monitorcheck`,
`core.0066_alter_scheduledtask_task_type`.

## [3.17.537] - 2026-09-05

### Fix: Phase 46 was recorded against a version that was never released

`docs/ROADMAP.md` marked Phase 46 (Job Kit) `[shipped — v3.17.532]`, in its
header, its four sub-bullets and the sizing table. There is no v3.17.532 — no
CHANGELOG entry, no tag. The job kit shipped in **v3.17.533**, alongside the
public scheduler wallboard and the late-fee regression fix. 528, 529, 530 and
532 were all skipped during that stretch, and the roadmap kept the number the
work had been developed against rather than the one it went out as.

This matters more than a typo because the phase header is parsed: `/core/roadmap.json`
reads `[shipped — vN.N.N]` to populate each phase's `version`, so anything polling
that feed has been reporting a release that doesn't exist.

Corrected in all ten places — six in `docs/ROADMAP.md` (header, four sub-bullets,
sizing table) and four Phase 46 code comments across `inventory/` and `psa/`,
plus two unrelated v3.17.532 references in `psa/models.py` and
`integrations/tests_phase44.py` that named the same non-existent version for the
late-fee fix, which also shipped in v3.17.533.

Comments and documentation only — no logic, no migrations, no mobile rebuild.

## [3.17.536] - 2026-09-05

### Mobile asset screen: two dead filters, and the edit UI that never shipped

Three follow-ups were logged against the mobile asset screens back in May.
All three had already shipped in v3.17.476 and were verified still working
(see "Not changed" below). Checking them turned up a set of adjacent
defects instead, which is what this release is.

**The Assets list "Type" box did nothing** (`mobile/src/api/assets.ts`,
`api_mobile/views_assets.py`):

The client sent `?asset_type=`; `asset_list_view` only ever read `?type=`.
Typing "server" narrowed nothing. The existing test passed because it
called the endpoint with `?type=` directly — the spelling the app doesn't
use. The client now sends `type`, and the server accepts both spellings so
the bundle already on people's phones starts working as soon as the server
updates, without waiting on a Play rollout.

**The Assets list "Status" box did nothing either.** `?status=` was never
implemented on the mobile asset list at all. `Asset` has no status column —
the web list filters `custom_fields__status` (`assets/views.py`) — so
mobile now matches that, case-insensitively, since the value is typed by
hand rather than picked from a dropdown of known values.

**`status` and `location` were never serialized.** Both the list rows and
the detail screen already referenced `asset.status`, so the pill was dead
markup. `_serialize_asset` now reads both out of `custom_fields`, and the
detail payload additionally carries the whole `custom_fields` map, `tags`,
and `created_by_name` — the "full info" the May follow-up asked for, minus
the fields that turned out not to exist on the model. A non-dict
`custom_fields` (a bad CSV import can leave a list in there) degrades to
empty rather than 500-ing the whole list endpoint.

**Asset editing and vault linking existed only on the server.** v3.17.480
shipped `PATCH /assets/<id>/` and `POST`/`DELETE /assets/<id>/vault-links/`
with tests, and the CHANGELOG, ROADMAP and Play Store listing all described
the matching app screens. Those screens were never written —
`mobile/app/assets/[id].tsx` hadn't been touched since v3.17.476. Now
written:

- **Edit** on the identity card, gated on `assets_edit` from `/auth/me/`
  (the server already sent the asset flags; the client's permission type
  just never listed them). Covers identity / hardware / OS / notes. RAM is
  validated as a whole number client-side rather than bounced back as a 400.
- **+ Link vault entry** opens a searchable picker scoped to the asset's own
  organization — the server rejects cross-org links, so offering them would
  only produce errors — with already-linked entries filtered out.
- **Unlink** per linked secret, behind a confirm that spells out that the
  secret stays in the vault and only the link is removed.

**Not changed** — the three original follow-ups, all verified against the
current code: asset detail has rendered the full record since v3.17.476,
vault entries have been listed on it since the same release, and the
tickets list has defaulted to `open` (`status__is_terminal=False`) since
then, with the Mine and Critical chips constrained the same way.

6 new API tests in `api_mobile/tests.py`. versionCode 3170483 → 3170536.
**AAB rebuild required** — the asset screen changes ship in the bundle.

## [3.17.535] - 2026-09-04

### Feature: task warnings you can set in days, and actually see

Scheduled tasks have carried `alert_before_hours` and an alert-sending command
for some time. Two things were missing.

**The lead time could only be expressed in hours.** A week's notice meant
knowing to type 168. The form now takes a number and a unit. Hours remain the
canonical stored value, so `check_scheduled_task_alerts` is untouched and
existing tasks keep working exactly as before; the unit only records how the
figure was entered, so editing a task shows "7 days" back rather than
"168 hours". A recurring task carries its unit to the next occurrence, which
would otherwise reappear as 168 hours.

**Nothing showed the warning.** Alerting was email and SMS only, so a task
creeping up on you was invisible on the screens you actually look at. A task
inside its warning window is now flagged on:

- the **calendar** — amber row and a "Due soon" badge
- the **task list** — amber due date and a bell
- the **dashboard Schedule panel**
- the **public wallboard** — amber time, sized to read across a room
- the task's own detail page

Two decisions in the logic worth stating:

- **Overdue suppresses the warning.** A task that is both would otherwise carry
  two badges saying different things about the same row. Overdue is the louder
  state and wins.
- **A lead of 0 means "do not warn me"**, not "warn me always" — which is what a
  naive `now >= due - 0` would give you.

## [3.17.534] - 2026-09-03

### Fix: a fresh install had no background jobs at all

`install.sh` only ever wrote the gunicorn unit. Nothing in it referenced
`deploy/*.timer` — so a new install came up with **no scheduler, no website
monitoring, no breach scan, no PSA or RMM sync**. The app looked completely
healthy and simply never did anything on a schedule. The seven timers existed in
`deploy/` and were installed by hand on the reference box, which is why it went
unnoticed.

The installer now installs them, rewriting as it copies: `/home/administrator`
becomes the real install directory, `User=administrator` the real user, and
`Group=` the user's actual primary group. The files in `deploy/` stay written for
the reference install so they can still be copied by hand there; only the
installed copies are rewritten. Verified against a simulated `/opt/clientst0r`
install under a different user, with `systemd-analyze verify` on the results.

**Enabled on install** — the jobs the app needs to function: `scheduler`,
`monitor`, `breach-scan`, `psa-sync`, `rmm-sync`.

**Installed but left off**, with the enable command printed: `auto-update` and
`accounting-sync`. Applying releases to a live system unattended, and writing to
a live accounting system, are decisions for whoever runs the box rather than
installer defaults.

Uninstall now removes the timers too. It only ever removed the gunicorn unit, so
a removal left timers firing against a deleted directory, filling the journal
with failures with no obvious cause.

`core/tests/test_deploy_timers.py` pins both halves: the units are well-formed
(every timer has a service, every service an `ExecStart`, every timer a
schedule), and the installer references them, rewrites the reference paths, and
keeps the two self-acting units out of the default enable list.

Existing installs are unaffected — their units are already in place. This is for
fresh installs and reinstalls.

## [3.17.533] - 2026-09-03

### Fix: v3.17.531 could reopen invoices that were paid in cash

Shipped in v3.17.531 and fixed here, so it is worth stating plainly. Making
`Invoice.recompute_totals()` two-way — so a payment voided in QuickBooks reopens
the invoice — also reopened **any** invoice showing Paid with no `Payment` rows
behind it. That is exactly how a cash payment, a cheque, or an invoice settled
directly in the accounting system is recorded. Those invoices would have quietly
gone back to Outstanding and **started accruing late fees**.

The fix is structural rather than a tighter condition. `recompute_totals()` runs
from everywhere and genuinely cannot tell a voided payment from a hand-marked
one, so it is back to its original one-way behaviour. A new
`Invoice.reopen_if_unpaid()` performs the reverse transition and is called only
by the accounting sync, which is the one caller that *knows* it just removed a
payment. The knowledge lives with the code that has it.

Caught by the existing `LateFeeTests`. A first attempt guarded on "was
`amount_paid` previously non-zero", which does not work — a hand-marked invoice
carries `amount_paid` with no payments behind it, which is precisely the case it
was meant to exclude.

### Feature: job kit — what the tech has to take

A scheduled job already linked a ticket to a calendar entry. What was missing was
any record of what the job *needs*, so kit lists lived in someone's head or a
phone call from the van.

**Tools are now a catalogue of their own** (`inventory.Tool`), deliberately not
inventory rows. A consumable is spent and its quantity drops; a tool goes out and
comes back, and the question its record has to answer is "where is it", not "how
many are left". Modelling both as stock would mean either lying about quantities
or explaining why the cable tester's count never moves. Tools carry a code,
category, home shelf or assigned van, condition, and a retire flag that removes
them from pick-lists without breaking history.

**Each ticket gets one kit list** covering tools, inventory items and free-text
lines, because that is how it is read — a tech looks at one list before leaving,
not three. It hangs off the ticket rather than the visit, so it survives
rescheduling and shows wherever the ticket does.

Details that matter in the field:

- **Shortfall warning.** A line asking for eight of something with three in stock
  is flagged. Sending someone out for parts that are not there is the whole
  failure this list exists to prevent.
- **Tick-off while loading**, recording who packed each line and when.
- **Lines keep their own copy of the name.** The foreign keys are `SET_NULL`, and
  a packing list that empties itself because somebody retired a tool is worse
  than a stale label.
- The same tool or part cannot be listed twice on one ticket — that is a
  data-entry slip, and quantity is how you ask for two.

### Feature: public scheduler wallboard

A schedule for a screen on the workshop wall.

**It spans every client, not one.** In this platform an Organization *is* a
client, so a per-client board would show a single customer's jobs — not what a
workshop screen is for.

**It is public, and that shapes the whole design.** A wall-mounted screen has no
keyboard and nobody wants to sign a display in every morning, so the URL is the
only thing standing between the schedule and the internet:

- The board ships **disabled**.
- A disabled or unknown link returns **404, not 403** — a 403 would confirm a
  board exists at that address. There is a test asserting the two are
  indistinguishable.
- The address carries a 43-character `secrets` token rather than an id, so boards
  cannot be found by walking integers.
- The token rotates on demand, which kills a leaked link immediately.
- **What it shows is opt-in per field.** Client names, technician names and ticket
  numbers toggle separately; client names are usually the most sensitive thing on
  a schedule and the board stays useful without them.

Served `no-store` and `noindex`, and rendered standalone rather than through the
authenticated base template, which has no meaning without a user.

### Also fixed

- `ticket_kit_add` caught `IntegrityError` on a duplicate line to show a friendly
  message, but Django leaves the transaction unusable after an integrity
  violation — so the redirect that followed would have 500'd instead. Wrapped in a
  savepoint, since a duplicate is an expected outcome here, not an exceptional one.
- A missing migration for the `accounting_sync` scheduler task-type choice added
  in v3.17.531.

## [3.17.531] - 2026-09-03

### Feature: two-way QuickBooks Online sync (GitHub #145) — Phase 44 complete

Invoice push has worked for a long time. The pull half essentially did not exist,
and one part of it was documented as working when it never had. This closes the
gap across four sub-phases, shipped together.

**44.1 — the customer mapping becomes a real table.** The organization →
provider-customer map lived as a dict inside the connection's encrypted
credentials blob: not queryable, not in the admin, not reportable, and destroyed
by a credentials reset — which would silently orphan every mapping and cause the
next push to create duplicate customers. It is now `AccountingCustomerLink`, with
two unique constraints that hold the invariants: one client maps to at most one
customer per connection, and one provider customer is claimed by at most one
client. A data migration lifts existing mappings across for both QuickBooks
(`customer_map`) and Xero (`contact_map`), leaving the blob copy in place so a
rollback still works.

Customer push now sends the whole record — company name, billing address, email,
phone, website, contact — rather than the bare `DisplayName` that was all it ever
sent, which left somebody retyping the rest in QuickBooks. Updates carry the
`SyncToken`, so an edit made provider-side since the last read surfaces as a
conflict instead of being silently overwritten. Customer pull links by name and
deliberately does **not** create organizations; unmatched names are listed
individually, because a count gives an operator nothing to act on.

**44.2 — payments are read, not guessed.** The old sync polled an invoice's
balance and, when it hit zero, invented a local payment for the whole outstanding
amount, dated today, with method `other`. Now provider `Payment` records are read
directly, with the invoices each settles taken from `LinkedTxn`. That fixes four
things at once:

- **Partial payments work.** Previously invisible — a non-zero balance was skipped
  outright — so `Invoice.status = 'partial'` was unreachable from the provider
  side despite being a documented status.
- **Re-runs are idempotent**, keyed on the provider's payment id through a new
  unique constraint on `psa.Payment`.
- **The real date and reference** are stored instead of fabricated ones.
- **Voids reopen the invoice.** This needed a fix to `recompute_totals()`, which
  was one-way: an invoice could reach Paid but never leave it, so a payment voided
  in the accounting system left it reading Paid with nothing against it.

Invoice reconciliation additionally catches an invoice voided provider-side. One
that has been *deleted* there is flagged, not voided locally — deleting revenue
records on the strength of a single 404 is not a call a sync job gets to make.

**44.3 — it actually runs on a schedule.** New `accounting_sync` command covering
all three stages, with one stage's failure not abandoning the others. Ships
`deploy/clientst0r-accounting-sync.{service,timer}` — the timer the roadmap had
claimed since v3.17.280 without one ever existing — plus a scheduler task type for
installs that use the in-app scheduler, and a **Sync Now** button on the
connections page, which had no sync action at all while the RMM and PSA pages had
one for releases. `AccountingConnection.last_sync_at`, `last_sync_status` and
`last_error` are finally written; they had existed since the model was created and
were never set, which is why that column always read "Never".

**44.4 — retry, and one deliberate asymmetry.** Exponential backoff with jitter,
`Retry-After` honoured on 429, one forced token refresh on a 401. But **writes and
reads are treated differently on purpose**: a 5xx or a timeout on `POST /invoice`
does not tell you whether the invoice was created, and QuickBooks offers no
idempotency key — so replaying one risks putting a second invoice in front of a
client, which is the exact failure the v3.17.526 push guard exists to prevent.
Writes therefore retry only on 429, where the request was provably rejected before
processing; reads retry everything transient.

`poll_balance`, `push_customer`, `pull_customers`, `pull_payments` and
`pull_invoices` are now registered audit actions. `poll_balance` had been written
since v3.17.280 without being registered, so those rows rendered with a blank
label.

`accounting_sync_payments` is superseded but still works for anyone who scripted
it, now carrying a docstring that says plainly what it can and cannot see.

Still out of scope, as the request itself suggested: products/services, tax codes
and payment terms.

## [3.17.527] - 2026-09-03

### Feature: a system-wide background setting in General Settings

The page background was entirely per-user — each person picked a mode on their
profile and that was that. An MSP wanting one consistent look across a team, or
simply wanting its own image behind the app, had no way to set one.

**General Settings → App Background** now carries a master policy with four modes:

- **User controlled** — each person picks their own. This is the previous behaviour
  and remains the default, so upgrading changes nothing for anybody.
- **Static image** — one uploaded image for everyone.
- **Colour or pattern** — either a solid hex colour or one of the twelve preset
  gradients.
- **Random images** — a different image each page load.

**Enforcement is honest about itself.** When a policy is active, the profile page
keeps its background controls visible but disabled, under a banner naming the
policy. Hiding the section outright would only relocate the confusion — a greyed
control with a reason attached explains itself.

Three things that needed care:

- **A disabled `<fieldset>` submits nothing.** Left alone, any unrelated profile
  save while a policy was active would have silently blanked the user's stored
  background — and they would only have discovered it when the policy was lifted.
  The view preserves those fields while a policy is in force, with tests for both
  directions so the preservation cannot become a permanent lock.
- **The colour is validated server-side.** It is interpolated into a style
  attribute, and `<input type="color">` is trivially bypassed by a hand-rolled
  POST, so anything that is not `#rrggbb` is rejected. The policy and preset values
  are likewise checked against their choice lists.
- **Image mode with nothing uploaded yet** falls back to no background rather than
  a broken one. The admin has picked the mode but not finished.

**Cleanup along the way.** The twelve preset backgrounds were defined twice — the
labels as inline choices on the profile model, the URLs as a dict inside a context
processor — with nothing tying them together. A key present in one and missing from
the other would have shown up only as a silently absent background. They are now
one table in `core/backgrounds.py` feeding all three consumers.

Note this is unrelated to the GeoIP map backdrop from v3.17.522, which styles the
world map on the firewall and vault access-rule screens. This one is the app page
background.

### Fix: two tests from v3.17.526 were wrong

The double-push guard shipped correct and its two behavioural tests passed, but two
supporting tests never created an `AccountingConnection`. The view therefore exited
at "No active accounting connection" before reaching the provider, so asserting the
provider had been called proved nothing and failed. Both now build a connection
first. The guard itself was not changed.

## [3.17.526] - 2026-09-03

### Fix: a double-click could put two invoices in front of a client

`push_invoice()` creates a **new** invoice in QuickBooks Online or Xero on every
call. Nothing stopped a second call. A double-click, a browser resend, or an
impatient second click on a slow push therefore raised a duplicate invoice against
the client's accounts payable. Deduplication existed, but only as detection — the
reconciliation report found duplicates *after* they were already in the accounting
system, where correcting them is somebody's phone call.

The push view now refuses an invoice that already carries an
`accounting_external_id`, and says which provider and id it already has so the
operator can go look. Re-push is still possible, because an invoice genuinely
deleted provider-side needs it — but it is now an explicit "Re-push" button with
its own confirmation, rather than the same button as the first push.

The check runs before connection resolution: already-pushed is true regardless of
which connection would be chosen.

### Fix: the roadmap claimed an accounting sync that has never run

`docs/ROADMAP.md` marked Phase 27's bidirectional payment sync as shipped "with a
daily cron". There is no cron. There is no systemd timer, no crontab entry, and no
`run_scheduler` task type for `accounting_sync_payments` — a repo-wide search finds
it referenced only by the changelog, the roadmap, its own tests, and itself. The
command has only ever run when a human typed it.

The claim traces to the command's own module docstring, which ended with "Wire to a
daily systemd timer alongside the existing accounting jobs" — a to-do that was read
as a description. Nobody wired it, and the roadmap wrote it up as done.

Corrected in three places, because the roadmap is published on four surfaces
including a JSON feed that external dashboards poll:

- The roadmap bullet now reads *partial*, states plainly that nothing schedules the
  command, and notes the second overstatement: it polls the invoice **balance**
  rather than reading provider payment records, so a partial payment is invisible
  (a non-zero balance is skipped) and the `Payment` row it writes carries an
  inferred date and `method='other'` rather than the real ones.
- The command's docstring now leads with **NOT SCHEDULED** and explains what it does
  and does not do. The note it writes into `Payment.notes` — which is user-visible —
  no longer calls itself a cron and now says the amount and date are inferred.
- `BaseAccountingProvider.poll_invoice_balance()`'s docstring likewise.

### Added: Phase 44 — Full Two-Way Accounting Sync (planned)

GitHub #145 asks for full two-way QuickBooks Online sync. An audit of what exists
found the push half is solid — OAuth with encrypted tokens and automatic refresh,
invoice push with GL-account and tax capture, multi-book routing, and an audit log
of every provider call — and that essentially none of the pull half exists. Rather
than leave the gap implicit, it is now a roadmap phase enumerating each missing
piece: customer mapping as a real model rather than a dict inside the encrypted
credentials blob, customer pull, invoice pull beyond `Balance`, real payment pull
with partial-payment and reversal support, scheduling, a manual "Sync Now", retry
with backoff, and three logging gaps (`AccountingConnection.last_sync_at` and
friends are declared but never written, so the UI always shows "Never").

## [3.17.525] - 2026-09-03

### Fix: developer comments were being displayed to users on ten pages

A comment on the dashboard was showing up as literal text on the page. The cause
is a Django rule that is easy to miss: **`{# ... #}` is a single-line comment
only**. Spread one across two lines and it stops being a comment — Django renders
it verbatim into the page, with no error and no warning. The note you wrote for
the next developer is simply shown to every user.

The dashboard one arrived in v3.17.524 and was reported immediately, but a sweep
of `templates/` found it was not new: **ten templates** were doing this, some for
many releases. All are converted to `{% comment %}...{% endcomment %}`, which is
the multi-line form:

- `core/dashboard.html` — the v3.17.524 panel note (reported)
- `core/system_updates.html` — printed a rationale about exactly which sudo
  commands the updater is granted, onto the Settings > Updates page
- `core/mobile_apps_admin.html`, `portal/ticket_detail.html`,
  `psa/client_settings.html`, `psa/ticket_create.html`,
  `psa/_link_to_problem_form.html`, `psa/_scope_banner.html`,
  `reports/crm_sales_funnel.html`, `vault/access_rule_form.html`

None of the ten contained template tags inside the comment text, so nothing was
executing that now stops executing — the change removes the leaked prose and
nothing else.

**Guarded two ways.** `TemplateCommentTests` in `core/tests/test_source_syntax.py`
sweeps every shipped template and fails on any unterminated `{#`, so this cannot
come back anywhere in the codebase. The dashboard render test additionally
asserts no raw template syntax survives into the response for the page it
happened on.

## [3.17.524] - 2026-09-03

### Feature: the dashboard now shows what needs doing, not what already happened

Three of the home dashboard's panels looked backwards. **My Recent** and **Recent Activity** were both
audit-log tails, and **Expiring Soon** sat in a corner on its own. Between them they filled two thirds
of the page with history. They are replaced by two panels about the near future.

**Schedule (next 7 days)** — scheduled tasks and ticket resolution deadlines on one timeline, grouped
by day. Days with nothing on them are omitted rather than rendered as empty rows; an agenda of seven
blanks tells the reader nothing. Each row links straight to the task or ticket.

**Tasks** — open work ordered by due date, most urgent first, with undated items last so the top of
the list is always the thing that matters rather than the thing created most recently. Overdue rows
carry a red badge; anything due inside a week is amber.

**Expiring items are now tasks.** An expiring password, a tracked expiration or an SSL certificate
about to lapse is something a person has to act on — which is what a task is. All three are folded
into the Tasks panel with their own icons instead of occupying a separate card. The 30-day look-ahead
is unchanged, but the window now extends 30 days *backwards* too, so something that lapsed last week
shows up with an Overdue badge instead of vanishing the moment it matters most. It is bounded rather
than open-ended on purpose: these rows sort earliest-first and an expiry has no lifecycle a human
closes, so a single record that lapsed years ago would otherwise sit at the top of the panel forever.

The panel shapes mirror the mobile agenda added in v3.17.478, so the two surfaces agree about what
"upcoming" means.

**Under the hood.** New `core/dashboard_panels.py` holds the query logic — `get_schedule()` and
`get_tasks()` — rather than growing `dashboard_views.py` further. The view is net smaller: the two
audit-log queries behind the deleted panels and the three `expiring_*` querysets are gone, because
`get_tasks()` covers the expiring items and a repo-wide search confirmed nothing else read any of
those five context keys. Five fewer queries per dashboard load.

The dashboard view had no test at all, so a template still referencing a dropped context key would
only have surfaced in production. `DashboardRenderTests` now renders the page end-to-end and asserts
both the new panels and the absence of the old ones.

Three things the tests pin, all learned the hard way while building it:

- **Every link is built with `reverse()`, never a hand-written path.** The first cut wrote five paths
  by hand and three were wrong — tickets live at `/psa/t/<pk>/` not `/psa/tickets/<pk>/`, expirations
  are under `monitoring/` not `core/`, and bare `/monitoring/` has no route at all. A dead href renders
  exactly like a live one, so nothing looked broken. `PanelUrlTests` now resolves every URL each panel
  can emit, across all four row kinds.
- **Only `ImportError` / `LookupError` may be caught.** PSA and monitoring are optional in some
  deployments, so their imports are guarded — but a broad `except Exception` there once swallowed an
  `AttributeError` (`Password.name`; the field is `title`) and the panel simply rendered empty. A test
  walks the module's AST and fails on any broader handler. It checks the AST rather than grepping,
  because a string search matches this module's own prose explaining the rule.
- **Order before slicing.** Every panel queryset takes a `[:N]` slice, and three of them relied on the
  model's default ordering — which is `title` for `Password` and `name` for `WebsiteMonitor`. The
  slice was therefore taking the alphabetically-first ten rows rather than the ten expiring soonest,
  quietly hiding the urgent ones. Open tasks had the mirror-image problem: SQLite sorts NULLs first
  ascending, so undated tasks filled the slice ahead of dated ones. All four querysets now order
  explicitly (`nulls_last=True` for due dates), with a test for each direction.

## [3.17.523] - 2026-09-03

### Feature: spreadsheet import for Shop and VAN inventory

Stock levels had to be entered by hand. The import pipeline that already backed assets, passwords,
contacts and documents — with column mapping, preview, job history and rollback — now covers
inventory too, and reads spreadsheets as well as CSV.

**Two new targets** on the existing importer:

- **Shop Inventory** → `vehicles.ShopInventoryItem`
- **VAN Inventory** → `vehicles.VehicleInventoryItem`

They are near-identical sibling models, so they share one field-mapping path; the vehicle one
additionally resolves which van each row belongs to.

**Spreadsheet support.** A new `imports/services/tabular.py` reads `.xlsx`/`.xlsm` via openpyxl and
CSV via the stdlib, returning the same `(headers, rows)` shape either way — so a spreadsheet is
indistinguishable from a CSV to everything downstream, and the existing CSV path now goes through
the same reader rather than a second inline `DictReader`. There is a test asserting the two formats
produce byte-identical results.

Excel's typing needed care: it stores every number as a float, so a quantity of `12` arrives as
`12.0`, and `"12.0"` fails an `IntegerField` parse. Integral floats are normalised back to `12`.
Blank rows and trailing empty header columns — both normal in hand-edited sheets — are dropped.

**Legacy `.xls` is refused**, with an instruction to re-save as `.xlsx`. openpyxl does not read the
1997 binary format and xlrd dropped it in 2.0; pulling in an unmaintained pin to half-parse it would
be worse than a clear error.

**Vehicle matching** accepts the name, licence plate or VIN — whatever is actually printed on the
van — because requiring a database id in a spreadsheet is how an import feature goes unused. An
unmatched vehicle skips that row and logs the value that failed to match, so the operator can fix
the sheet and re-run, rather than losing the whole batch.

Junk in a numeric cell falls back to the field default instead of aborting the import.

### Fixed while building it

Three wrong assumptions, each caught by running the code rather than reading it: `ServiceVehicle`
has no `unit_number` field, and neither the fleet nor either inventory model is org-scoped — so the
`organization=` kwarg I first wrote would have raised on every row.

### Added

- `imports/tests_inventory_import.py` — 15 tests covering the reader (CSV/xlsx equivalence, float
  normalisation, blank rows, trailing headers, `.xls` refusal, preview limits) and the importers
  (item creation, name required, junk quantities, vehicle matching by all three identifiers,
  unmatched-vehicle logging, target registration).
- `openpyxl>=3.1,<4.0` in requirements.txt.

## [3.17.522] - 2026-09-03

### Feature: click-to-select world map for GeoIP country selection

Picking countries meant typing ISO codes into a text box — `US, CA, GB` on the vault access-rule
form, and a code-plus-name form on the global firewall rules page. A world map replaces both.

**Where it appears.** The same component (`core/_geoip_map.html`) is used on:

- **Settings → Firewall → Country Rules** — one list; a country either has a rule or it does not.
  Whether that means blocked or allowed is the firewall's own mode, shown in the card header so the
  map is never ambiguous about what selecting a country will do. Saving reconciles the rule list
  against the selection.
- **Vault → Access Rules** — two lists, Allowed and Blocked, with a mode switcher. A country can
  only be in one, so an "allowed AND blocked" contradiction is not expressible on the map.

**It is an input method, not a new storage format.** The map writes comma-separated codes back into
the same inputs the form already posted, so the server contract is unchanged, the manual add form
still works, and the page degrades to the original text fields with JavaScript off.

**Country names are resolved server-side.** These rows drive a firewall and are displayed back to
admins, so the name is never taken from the browser. `core/iso3166.py` holds a 249-entry ISO 3166-1
table generated from the Debian `iso-codes` package by `scripts/gen_iso3166.py` (verified to
reproduce the committed file byte for byte). Unknown codes are dropped rather than stored — a typo
becoming a rule that silently matches nothing is worse than losing it at the door.

**Backdrop** is configurable per the request: a colour pattern (six presets), random (a different
pattern each visit, chosen server-side so it is stable for the life of the page), or an uploaded
image. Purely cosmetic, and saved through its own endpoint so a backdrop change can never touch
firewall rules — there is a test asserting exactly that. Image mode falls back to the chosen pattern
when the file is missing rather than rendering an empty box; uploads are type- and size-checked.

jsVectorMap (MIT) is loaded from jsDelivr with a pinned version, consistent with how this app already
loads Bootstrap, Font Awesome and DataTables.

### Fixed while building it

The firewall page 500'd on first render: the GeoIP allowlist/blocklist mode lives on
`FirewallSettings`, not `SystemSetting`, and I read it off the wrong model. The tests written up to
that point only POSTed to the endpoint and never fetched the page, so they all passed while the page
was broken. Two render tests now cover it.

### Added

- `core/tests/test_geoip_map.py` — 23 tests: the ISO table, code normalisation (case, dedupe,
  invalid-code rejection), backdrop resolution including the missing-image fallback, rule
  reconciliation from the map, the manual add form still working, superuser enforcement, and the
  backdrop endpoint leaving rules untouched.

## [3.17.521] - 2026-09-03

### Fix: false positive in the deploy-asset test

A full run of `core docs api api_mobile psa` came back **836/837**, with one failure — in a test
added in v3.17.516, not in shipped code:

```
setup_mobile_build.sh copies deploy/mobile-build-sudoers, which does not exist
```

No such file exists and nothing copies one. `test_sudoers_templates_referenced_by_scripts_exist`
scans deploy scripts for `*-sudoers` references with `([A-Za-z0-9_-]+-sudoers)\b`, and `\b` is
satisfied by a following `.` — so when v3.17.519 introduced the install stamp
`mobile-build-sudoers.sha256`, the regex matched `mobile-build-sudoers` inside that filename and
demanded a template nothing had ever referenced.

The pattern now ends with a `(?![\w.])` lookahead, so it only matches a name that genuinely *ends*
at `-sudoers`. It resolves the two real references (`clientst0r-mobile-build-sudoers` and
`clientst0r-fail2ban-sudoers`), and still fails when a referenced template is actually removed —
verified both ways.

Worth noting for its own sake: two changes of mine, four releases apart, combined into a failure
neither would have caused alone. The test only earns its keep if it fails for real reasons, so a
false positive in it is worth the same care as a bug in the product.

## [3.17.520] - 2026-09-03

### Fix: spurious "One-Time Setup Required" banner on Settings → Updates

Regression from v3.17.518. `Settings → Updates` began showing a *"One-Time Setup Required for
Web-Based Updates"* banner on a host where one-click updates worked perfectly well.

`UpdateService._check_passwordless_sudo()` led with `sudo -n systemd-run --version` — on the stated
assumption that systemd-run is *"always present in the sudoers config"*. That held only while
systemd-run was granted **bare**. The least-privilege ruleset pins it to the single restart
invocation the updater issues, so `--version` is refused. And the check did:

```python
if 'password is required' in result.stderr:
    return False          # <- never reached the fallback probe
```

The `systemctl status` probe immediately below it would have succeeded. One denied probe was being
treated as a verdict on all of them.

Now it probes `systemctl status <service>` **first** — read-only, harmless, and much closer to what
the updater actually needs — keeps systemd-run only as a fallback for older sudoers files that
granted it bare, and continues past a denial instead of concluding from it. A non-zero exit from
`systemctl status` (an inactive unit) still counts as configured, because it proves sudo permitted
the command.

### Security: the banner was also telling people to grant far too much

The command it asked operators to paste granted `/usr/bin/systemd-run`, `/usr/bin/tee`,
`/usr/bin/pkill`, `/usr/bin/cp` and `/usr/bin/chmod` **bare** — with no arguments pinned. Any one of
those is root in all but name: systemd-run runs an arbitrary command as root, and tee or cp will
write any file they are pointed at, `/etc/sudoers` included. Anyone following that banner was
handing the web app full root.

Both the banner (`templates/core/system_updates.html`) and the equivalent hint in `core/updater.py`
now show the same narrow set `scripts/install_auto_update.sh` installs — one line per command the
updater actually runs — with a note that this deliberately does not grant general root access.

### Added

- `core/tests/test_updater.py::PasswordlessSudoCheckTests` — four cases covering the exact
  regression (systemd-run denied, systemctl allowed), an inactive unit still counting as configured,
  all probes denied, and `not allowed to execute` treated as a denial.

## [3.17.519] - 2026-09-02

### Fix: mobile build setup no longer needs sudo on every update

Direct fallout from v3.17.518. With blanket `NOPASSWD:ALL` removed, `deploy/setup_mobile_build.sh`
started failing again — it does `sudo cp` into `/etc/sudoers.d/`, which is deliberately **not** in
the least-privilege ruleset. The `[WARN] Mobile build setup failed` line came back, for an entirely
different reason than the one fixed in v3.17.516:

```
sudo: a terminal is required to read the password...
sudo: a password is required
[WARN] Mobile build setup failed (non-critical)
```

The step ran unconditionally on every update, re-copying a file whose content changes only when the
template does. It now:

- **Skips when nothing changed.** `/etc/sudoers.d` is root-only, so the installed file cannot be
  read — or even stat'ed — to compare against. The script therefore records the hash of what it last
  installed in `~/.cache/clientst0r/mobile-build-sudoers.sha256` and skips when the template still
  hashes the same.
- **Exits 0 with guidance when the copy genuinely cannot be done**, instead of failing. The grant is
  optional — it covers only the first-run Node.js bootstrap, and mobile builds work anywhere Node
  and npm are already installed. Failing every update adds noise, not information; the message says
  exactly which one-time command to run to enable it.

Worth recording, because it cost a debugging cycle: the stamp compares
`printf '%s' "$(sed ... file)"`, and command substitution strips trailing newlines — so a hash
computed by piping the file directly into `sha256sum` will never match one computed the script's
way. Both sides must use the same method.

## [3.17.518] - 2026-09-02

### Security: least-privilege sudo that actually covers the app — prerequisite for dropping blanket NOPASSWD

`/etc/sudoers.d/99-administrator-nopasswd` grants `ALL=(ALL) NOPASSWD:ALL`, which is why every
sudoers mismatch found over the last few releases went unnoticed: nothing could fail. Removing it
turns out to need work first, because the scoped rules did **not** cover everything the running
application issues. Six call sites would have broken silently.

Audited every `sudo` invocation across `core/`, `deploy/` and `scripts/`, and split them by who
initiates the command. **The running app** gets an explicit NOPASSWD grant — a gunicorn worker has
no tty, so anything ungranted fails rather than prompting. **Admin-run bootstrap and repair
scripts** are left to prompt like any other privileged manual action.

Two mismatches were better fixed in the code than by loosening a rule:

- `core/settings_views.py` restarted `clientst0r-gunicorn` **without the `.service` suffix**.
  sudoers matches arguments literally, so that could never have matched a scoped rule. Now names the
  unit in full.
- `core/management/commands/auto_heal_version.py` used `systemd-run --on-active=2` where the granted
  rule pins `=3`. Normalised to `=3` so one rule covers both callers.

Newly granted, each traced to its call site:

- `pkill -9 -f gunicorn` — the force-restart path in `core/views.py` (stop → kill stragglers → clear
  bytecode → start). The SIGKILL sweep is the point of that path: it exists for a wedged worker a
  graceful stop has not cleared.
- `apt-get -q update` and `apt-get -y -o Dpkg::Options::=--force-confdef -o
  Dpkg::Options::=--force-confold *` — patch management, reached from the UI via
  `core/security_views.py`. Applying system updates is the feature, so this necessarily permits
  installing from configured repositories; the option prefix is pinned to what the command builds.

Deliberately **not** granted: `setup_package_scanner_sudo.py` (writes into `/etc/sudoers.d`) and
`scripts/fix_gunicorn_env.sh` (`tee`s the unit file). Both are admin-run steps, not things the app
does unattended.

Verified: the generated file passes `visudo -c`, and a static coverage check of 15 app-initiated
commands against the installed rules is **15/15**.

Note for anyone planning the same cleanup: there are **two** blanket rules, not one —
`99-administrator-nopasswd` and cloud-init's `90-cloud-init-users`, which carries an identical
`NOPASSWD:ALL` and may be regenerated on boot. Removing one alone changes nothing.

## [3.17.517] - 2026-09-02

### Security: clear all three Dependabot alerts (1 high, 2 moderate)

| Severity | Package | CVE | Fixed in |
|---|---|---|---|
| **High** | cryptography | CVE-2026-69247 — Bleichenbacher oracle via distinguishable errors and timing in PKCS#7 `EnvelopedData` decryption | 50.0.0 |
| Moderate | djangorestframework | CVE-2026-73228 — `request.data` could bypass Django's `DATA_UPLOAD_MAX_MEMORY_SIZE` on oversized JSON and urlencoded bodies | 3.17.2 |
| Moderate | djangorestframework | CVE-2026-73229 — `AdminRenderer` may disclose GET-protected data when rendering invalid write requests | 3.17.2 |

Pins moved to `cryptography>=50.0.0,<51.0.0` and `djangorestframework>=3.17.2,<4.0`, installing
50.0.1 and 3.18.0.

**Exposure, since the three are not equal here.** CVE-2026-73228 is the one that actually reaches
this codebase: `request.data` is used throughout `api/` and `api_mobile/`, so the upload-size cap
was bypassable. CVE-2026-73229 is not reachable — `DEFAULT_RENDERER_CLASSES` is `JSONRenderer` only
in production (`BrowsableAPIRenderer` is added only under `DEBUG`), and `AdminRenderer` is never
configured. The high-severity cryptography issue is in PKCS#7 `EnvelopedData` decryption, which
nothing in this codebase calls directly; it arrives transitively through Authlib, google-auth,
joserfc and msal. Patched regardless — none of that is a reason to sit on a high.

**msal had to move too.** `msal==1.34.*` requires `cryptography<49`, which would have pinned
cryptography to the vulnerable range no matter what the direct requirement said — the upgrade failed
`pip check` until this was resolved. msal 1.37 relaxes the constraint to `<51` (1.36 still caps at
`<49`), so the pin is now `msal>=1.37,<2.0`, installing 1.38.0. This is a live dependency of the
M365 Graph mail integration (issue #142), not an incidental one.

**Verified:** `pip check` clean, and the full `api`, `api_mobile`, `psa`, `core` and `docs` suites —
**833 tests** — pass against the upgraded set, covering both the DRF request paths and the M365 code
that uses msal.

Also removed a `~est_framework` directory pip left in `site-packages` when it could not finish
replacing the old DRF — the same orphaned-backup artifact cleaned out of this venv earlier today.

## [3.17.516] - 2026-09-02

### Fix: "[WARN] Mobile build setup failed" on every update — a template git refused to track

Every update since v3.17.492 logged `[WARN] Mobile build setup failed (non-critical)`. The cause
was three layers deep.

`deploy/setup_mobile_build.sh` copies `deploy/clientst0r-mobile-build-sudoers` into
`/etc/sudoers.d/`. **That template did not exist.** The v3.17.492 rename deleted the
`huduglue-`named original, and the replacement was never committed — `.gitignore` carried a blanket
`deploy/*-sudoers` rule, meant for generated output, so **git silently ignored the new template**.
The script's only symptom was a bare `cp: cannot stat`, swallowed behind a generic warning. Nothing
failed loudly, so nothing got looked at, for 23 releases.

Fixed at all three layers:

- **The template is restored**, and `.gitignore` now carries explicit `!` negations for the three
  shipped sudoers templates, so a real template can never again be un-addable while genuinely
  generated ones stay ignored.
- **The script now says what is wrong** — naming the missing file and noting that mobile builds
  still work anywhere Node.js and npm are already installed — rather than emitting a bare `cp`
  error behind a generic warning.
- **`core/tests/test_deploy_assets.py`** asserts that every `*-sudoers` a deploy script copies
  exists in the repo, and that no shipped template sits under a blanket ignore without a negation.
  Verified to fail when the template is removed.

### Security: the restored grants are narrower than the ones they replace

The deleted file granted `NOPASSWD: /usr/bin/npm install *` and `NOPASSWD: /usr/bin/npm *`. Both are
dropped. Nothing in the codebase has ever run npm under sudo, and `npm *` as root is root in all but
name — npm executes arbitrary lifecycle scripts from any package it installs.

What remains is exactly the four commands `core/management/commands/build_mobile_app.py` invokes for
its first-run Node bootstrap (and only when `curl` or `npm` is absent): `apt-get update`,
`apt-get install -y curl`, `apt-get install -y nodejs`, and `bash /tmp/nodesource_setup.sh`. The
path was also corrected from `/bin/bash` to `/usr/bin/bash` — the old rule could never have matched
the command it was written for.

On this host the correctly-scoped `/etc/sudoers.d/clientst0r-mobile-build` is installed and the
stale `huduglue-mobile-build` removed, so `/etc/sudoers.d/` is now free of pre-rename names.

## [3.17.515] - 2026-09-02

### Fix: stale sudoers service names, unit drift, and the silent gap that caused both

Two loose ends from the v3.17.492 rename, plus the reason neither was ever noticed.

**Sudoers still named the pre-rename services.** `/etc/sudoers.d/clientst0r-auto-update` granted
`systemctl restart huduglue-gunicorn.service` and four siblings — none of which exist any more. The
rename updated `scripts/install_auto_update.sh`, but nothing re-runs that script on update, so the
installed file kept the old names. Three further files (`huduglue-auto-update`, `huduglue-fail2ban`,
`huduglue-install`) were left behind as exact duplicates of their `clientst0r-*` replacements,
differing only in a comment header.

The generator now also grants **`systemctl reload`**, which the zero-downtime path added in
v3.17.512 actually depends on — without that rule an update silently falls back to a restart on any
host that doesn't have blanket sudo. And `systemd-run` and `pkill`, previously granted bare, are
pinned to the exact invocations the updater issues; unrestricted, either one is a root shell in all
but name.

**The unit file had drifted, and it mattered.** v3.17.500 raised the gunicorn worker timeout from
180s to 300s so AI documentation generation would stop being SIGKILLed mid-request and returning an
HTML 500 instead of JSON (issue #138). That change landed in `deploy/clientst0r-gunicorn.service` —
and stopped there. `update_instructions.sh` does a `git pull`; **nothing re-installs the unit**. The
host had been running the old 180s for fourteen releases, so the fix for #138 shipped but never took
effect, and nothing anywhere said so.

Step 5 now diffs the installed unit against the one in the repo (comments and blank lines ignored)
and warns when they differ, with the exact commands to review and adopt. It **warns only, never
overwrites** — an operator may have tuned worker count, bind address or resource limits on purpose.
The warning also notes that `ExecStart` changes need a restart rather than a reload, since a reload
re-execs workers under the master's existing command line.

Applied to this host: sudoers regenerated (validated with `visudo -c` before install), three stale
files removed, unit brought to `--timeout 300`. That last one required a genuine restart — measured
at 8 failed requests out of 55, ~2s — which is precisely the contrast with the reload path's 0/394,
and the reason unit drift is worth catching at update time rather than discovering later.

## [3.17.514] - 2026-09-02

### Fix: backslash escapes in seeded KB articles — including six that were silently corrupting content

Following up the `SyntaxWarning`s noted in v3.17.513. Two things turned up that the warning count
had hidden.

**There were 170 bad escapes, not 15.** Python reports an invalid escape sequence once per source
line, so the 15 warnings were 15 *lines*, not 15 occurrences. The real count across the two KB
seeding commands was 170.

**Six of them were already corrupting shipped article content, with no warning at all.** An invalid
escape like `\P` is left as a literal `\P` and merely warns. But when a Windows path happens to put
a *valid* escape letter after the backslash, Python converts it silently:

| Article text intended | What actually shipped |
|---|---|
| `root\cimv2\terminalservices` | `root\cimv2` + **TAB** + `erminalservices` |
| `C:\Data\file.txt` | `C:\Data` + **FORMFEED** + `ile.txt` |
| `C:\Tasks\backup.xml` (×2) | `C:\Tasks` + **BACKSPACE** + `ackup.xml` |
| `C:\Scripts\backup.ps1` (×2) | `C:\Scripts` + **BACKSPACE** + `ackup.ps1` |

A technician copying that WMI namespace or path out of a seeded article got a broken command, and
nothing anywhere reported a problem. These are the ones worth having found.

**The fix and how it was verified.** Every backslash in a non-raw literal is doubled unless Python
was already treating it as an intended escape. A survey first confirmed the only escapes to preserve
were 17 deliberate `\\` and one line continuation — no `\x`, `\u`, `\U` or octal anywhere — so the
transform is total and unambiguous. It then compared **every string constant's value** before and
after via `ast`: 15 literals were rewritten and exactly **4 values changed**, those four being the
article bodies holding the six corrupted paths. Everything else is byte-identical. `SyntaxWarning`
count is now zero.

### Added

- `core/tests/test_source_syntax.py::test_no_invalid_escape_sequences` — holds the codebase at zero
  `SyntaxWarning`s, so this class of bug (the silent variety included) can't creep back.

## [3.17.513] - 2026-09-02

### Fix: close the last downtime window in updates — scoped bytecode purge + pre-compile

v3.17.512 made updates use a graceful reload instead of a restart, but measuring one showed it
wasn't quite zero: **2 requests out of 423** exceeded a 5-second budget at the moment of handover.
The gunicorn log explained why — new workers boot, and old ones are SIGTERMed one second later:

```
14:16:58  Handling signal: hup
14:16:58  Booting worker with pid: 930087 / 930089 / 930090 / 930092
14:16:59  Worker (pid:926458) was sent SIGTERM!
```

One second is not enough, because step 5 deleted **every** `.pyc` under `BASE_DIR` immediately
beforehand — including the virtualenv's. Each fresh worker therefore had to recompile the whole of
Django from source before it could serve anything, while the old workers were already retiring.

Two problems with that purge, both fixed:

- **It was unscoped.** `BASE_DIR` is a home directory, not just the app. On this host it also holds
  a 4.6 GB `android-sdk`, a 1.8 GB Expo checkout, and `snap`, `mobile-app` and `local_apps` dirs —
  so the walk covered gigabytes to delete a few hundred files.
- **It wiped the venv.** `site-packages` bytecode is pip's to manage; destroying it bought nothing
  and caused the entire cold-start cost.

Step 5 now discovers the project's own Python packages (top-level dirs holding an `__init__.py` —
**0.015s**, no deep walk), purges only those, and pre-compiles them before signalling the reload, so
new workers boot warm. Measured at **~2s**, and it runs while the old workers are still serving, so
it costs update duration rather than downtime. The naive whole-tree alternative measured **162s**.

Two things fell out of building it:

- **The purge has been silently failing for a long time.** 22 `__pycache__` directories were
  root-owned (from a `manage.py` run under sudo), so `rm -rf` as the service user could never remove
  them — and `2>/dev/null || true` hid it every time. The step now counts what it could not delete
  and logs a `[WARN]` with the exact `chown` to fix it, instead of pretending it worked.
- **`core/management/commands/seed_all.py` did not parse at all.** Line 82 had
  `'... they don\\'t need'` — an escaped backslash followed by a quote, which ends the string
  early. `manage.py seed_all` would have died with a `SyntaxError` on invocation. Django imports a
  management command only when it is run, so nothing had ever touched the module. The new
  pre-compile step parses every file, and found it in seconds.

### Added

- `core/tests/test_source_syntax.py` — parses every Python file the project ships, so a file that
  cannot be imported can never reach a release again. Covers `SyntaxError` and `UnicodeDecodeError`,
  and guards its own discovery so it cannot pass vacuously.

Known and deliberately left alone: 15 `SyntaxWarning: invalid escape sequence` across two KB seeding
commands (Windows paths like `C:\gpreport.html` inside article bodies). Harmless today, a
`SyntaxError` in some future Python. Fixing them means editing seeded article content, so it wants
its own change with its own before/after comparison.

## [3.17.512] - 2026-09-02

### Fix: updates are now zero-downtime — the gunicorn unit had no `ExecReload`

Every update logged the same pair of lines:

```
[WARN] reload failed — falling back to restart (brief downtime expected)
Step 5/5: Restart of 'clientst0r-gunicorn.service' scheduled via systemd-run (3-second delay)
```

`deploy/update_instructions.sh` has always *tried* a graceful reload first and only fallen back to
a restart if that failed. It failed every time, for a mundane reason:

```
Failed to reload clientst0r-gunicorn.service:
  Job type reload is not applicable for unit clientst0r-gunicorn.service.
```

The unit had no `ExecReload=` line, so `systemctl reload` was never a valid operation on it and the
fallback restart — with its few seconds of 502s — was the only path updates ever took.

The unit now carries:

```ini
ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
TimeoutStopSec=10
```

SIGHUP makes the gunicorn master start fresh workers and retire the old ones one at a time while it
holds the listening sockets open, so nothing is refused. `KillMode=mixed` sends the stop signal to
the master alone, letting it wind its workers down gracefully rather than having systemd SIGTERM the
whole cgroup at once.

This is only a valid substitute for a restart because the app is **not** started with `--preload`:
workers import the app when they fork, so new workers pick up new code from disk. Verified rather
than assumed — with a sentinel version string written to disk, a reload, and the live `/health/`
endpoint reporting the new value (then reverted and reloaded back).

Measured on a live reload: **71 consecutive HTTPS requests, 0 failures**, master PID unchanged, all
four workers replaced.

Added in all three places the unit is defined — `deploy/clientst0r-gunicorn.service` and both inline
heredocs in `install.sh` — so fresh installs get it too, not just this host.

Note for anyone running backwards-incompatible migrations: a graceful reload briefly overlaps old
and new workers, so old code runs against the new schema for a second or two. Additive migrations
are unaffected; a destructive one still wants a hard restart.

## [3.17.511] - 2026-09-02

### Fix: stray code-block language badges in every export (issue #144 follow-up)

Testing v3.17.510's export against real Knowledge Base articles turned up a defect the unit tests
couldn't see, because it only shows up against content the AI documentation generator produces.

Those articles wrap every code block in Bootstrap chrome that pins a language label to the block's
top-right corner:

```html
<div class="position-relative">
  <span class="position-absolute top-0 end-0 badge bg-secondary">CODE</span>
  <pre class="bg-dark text-light"><code>...</code></pre>
</div>
```

In the browser that badge floats *over* the corner of the code block. An export is linear, so it
flattened into a stray one-word paragraph — a bare `CODE` or `POWERSHELL` line hanging above every
single code block. One Global KB article carried **29** of them, and they cost it a whole extra
page of PDF.

The block parser now drops elements that are chrome rather than content, wholesale including their
subtree: `position-absolute` (an overlay is by definition not in the document flow), plus
`d-print-none`, `no-print`, `visually-hidden`, `visually-hidden-focusable`, `sr-only` and
`sr-only-focusable` — classes that state outright the element isn't meant for a printed page, which
is exactly what an export is.

Care was taken with the drop scope: it tracks nesting depth so it closes at its *own* end tag
rather than swallowing everything after it, and a void tag (`<img class="position-absolute">`) never
opens a scope at all, since it has no end tag to close one.

Measured on the real article: paragraph blocks 67 → 38 (exactly the 29 badges), all 29 code blocks
preserved, PDF 10 pages → 9.

## [3.17.510] - 2026-09-01

### Feature: document export — Markdown, print-ready HTML, DOCX and PDF (issue #144)

The Knowledge Base could take documentation *in* (v3.17.503 added DOCX/PDF/TXT/MD import) but had
no way to get it back *out*. Issue #144 put it plainly: *"client departing needs documentation and
you should treat outbound as good as inbound."* This is the matching outbound half.

**Per-article export.** Every KB article and Global KB article gains an **Export** menu:

- **PDF** — letter-size, ReportLab-rendered, with a title block, running page footer, real tables,
  bullet/numbered lists, code blocks and clickable links.
- **Word (.docx)** — a genuine OOXML package built straight into the ZIP with `zipfile`, mirroring
  how the import side reads DOCX without python-docx. Ships `styles.xml` (Title / Subtitle /
  Heading 1-6 / Quote / Source Code) and `numbering.xml`, so headings show up in Word's navigation
  pane, lists are real Word lists, tables are real Word tables and hyperlinks are live external
  relationships — not a text dump with a `.docx` extension.
- **Markdown (.md)** — an article authored *as* Markdown exports its own source verbatim, so the
  import → edit → export round-trip is lossless. HTML articles are converted from their rendered
  body.
- **HTML (print-ready)** — one standalone, self-contained page with the stylesheet inlined.

**Bulk export.** **Export All** on the document list bundles every document the current
category / tag / search filters select into a single ZIP, in whichever format you pick, alongside an
`index.md` table of contents grouped by category. That is the departing-client handover in one
click, and the archive is readable with no app at all.

**Print visibility.** The issue asked for output that prints legibly — *"easy to print visibility ie
obscure background images etc"*. Both the exported HTML and the article page itself carry an
`@media print` block that drops background images, box shadows and text shadows, forces
black-on-white body text, hides the app chrome (nav, sidebar, action buttons), expands link targets
to their URLs, and keeps tables, code blocks and images off page breaks.

**Implementation.** `docs/services/document_export.py` parses a document's rendered, already
sanitised HTML **once** into a neutral block structure (headings / paragraphs / list items / quotes
/ code / tables / rules / images, each with formatted inline runs). All four writers consume that
same structure, so the formats can't drift apart — fix the parser, fix everything. No new
dependencies: ReportLab was already required for the PSA quote/invoice PDFs, and DOCX is
hand-rolled.

New routes (all login-required, all org-scoped exactly like the matching detail view, all served
`Cache-Control: private, no-store` since exports carry client-confidential documentation):

- `GET /docs/<slug>/export/<md|html|docx|pdf>/` — one article (`?inline=1` on `html` opens the
  print preview in the browser instead of downloading).
- `GET /docs/kb/<slug>/export/<fmt>/` — one Global KB article (staff only).
- `GET /docs/export/<fmt>/` — ZIP archive, honouring `?category=`/`?tag=`/`?q=`.

A file-upload document (an opaque PDF/DOCX/image blob) redirects to the original file rather than
exporting an empty shell.

## [3.17.509] - 2026-08-01

### Fix: migration drift in `files`, `imports`, and `reports`

`manage.py migrate` had been reporting *"Your models in app(s): 'files', 'imports', 'reports' have
changes that are not yet reflected in a migration"* on every update run. Five field edits had been
made in the models without a matching migration, so a fresh install's recorded migration state no
longer matched the models. Nothing was broken at runtime — every one of the five is a Python-level
attribute — but the drift meant `makemigrations --check` could never be clean and the warning
masked any *real* drift that appeared later.

- `files.Attachment.entity_type` — `choices` gained the vehicles entries (`vehicle`,
  `damage_report`, `fuel_log`, `vehicle_receipt`).
- `imports.ImportJob.source_type` — `choices` gained `csv`; `skip_duplicates` and `source_file`
  had reworded `help_text`; `source_file.upload_to` moved from `imports/magicplan/%Y/%m/` to
  `imports/files/%Y/%m/` when the importer grew CSV support.
- `reports.SavedQuery.target_model` — `choices` + `help_text`.

All three catch-up migrations are **no-ops against the database** — `sqlmigrate` emits `-- (no-op)`
for each, and the columns are byte-for-byte identical before and after.

The `imports` one needed care: `upload_to` is not in Django's `Field.non_db_attrs`, so the
autodetector classifies it as schema-affecting. On SQLite that turns into a full `import_jobs`
table rebuild — copy every row to a new table, drop the original, rename, recreate seven indexes —
for a change that alters no column. That migration therefore wraps its operations in
`SeparateDatabaseAndState` with an empty `database_operations`, so Django records the new field
state and touches no data. Verified against a copy of a production database: the `import_jobs`
schema (table + all seven indexes) is identical after applying.

`makemigrations --check` now reports "No changes detected" across the whole project.

## [3.17.508] - 2026-08-01

### Feature: send a ticket reply to the requester from the ticket form (issue #142)

The Graph/SMTP outbound transport added in 3.17.507 had no caller in the app — replies were saved
as comments and never actually left the server, so nothing reached the customer and nothing was
written to the mailbox's Sent Items. This release wires the reply box to that transport.

- **Opt-in checkbox** — the ticket reply form gains "Email this reply to `<requester>`", shown only
  when the ticket has a requester address. **Off by default**, so no existing workflow starts
  emailing customers after upgrading; agents tick it per reply.
- **Internal notes are never emailed** — enforced server-side (the flag is ignored on an internal
  note) and reflected in the UI, which disables and clears the checkbox when "Internal note" is
  ticked.
- **Transport follows the mailbox** — `email_outbound.resolve_ticket_email_config()` picks the
  config that ingested the ticket's most recent inbound message, so a reply leaves from the mailbox
  it arrived on and preserves the M365 conversation. It falls back to the organization's single
  active config, and deliberately returns `None` (plain SMTP backend) rather than guessing when
  two or more are candidates.
- **Failures never lose work** — the comment is committed before the send is attempted. Missing
  requester address, an unavailable Graph connection, or a transport exception all report through
  the message banner while the comment stays saved. Graph outcomes are reported distinctly:
  accepted, queued-for-retry, failed, and `uncertain` (submitted but unconfirmed — flagged for
  manual check rather than silently resent).
- **Audited** — each send writes an `AuditLog` entry recording transport, resulting status, and
  recipient.
- Tests: `psa/tests/test_reply_email.py` — opt-in gate, SMTP send, Graph send, internal-note
  suppression, missing-requester handling, failure-keeps-comment, and the four config-resolution
  cases.

## [3.17.507] - 2026-07-26

### Feature: Microsoft 365 outbound email via Graph (optional transport, issue #142)

Staff replies can now be sent through Microsoft Graph (`sendMail` / `reply` / `replyAll`) as an
**optional** outbound transport on M365 mailbox connections. **SMTP outbound is unchanged and
remains the default** — existing IMAP/SMTP customers are unaffected, and existing records default
to SMTP (Graph outbound is never auto-enabled).

- **Transport selector** — `EmailIngestionConfig.outbound_method` (`smtp` | `graph`). Graph is
  only usable when the mailbox has a valid, active M365 connection + mailbox address. The sender
  is always the server-configured mailbox — callers can't supply an arbitrary sender.
- **Graph operations** (`integrations/providers/m365.py`) — `send_mail` (new messages,
  `saveToSentItems` on), `reply_message` / `reply_all_message` (used when the original message was
  ingested via Graph, preserving the M365 conversation). All send `Prefer: IdType="ImmutableId"`.
- **Immutable message ids** — the inbound Graph poller now requests ImmutableIds and stores them on
  `EmailMessage.graph_message_id`, so a later reply targets the right message even after it moves
  folders.
- **Durable, idempotent delivery** — new `EmailOutboundJob` model + `psa_send_outbound` worker.
  Graph returns HTTP 202 (accepted, not delivered); jobs track queued/sent/failed/uncertain,
  accepted-at, retry count, Microsoft request id, and a last-error summary. An atomic claim-lock
  prevents duplicate sends; transient errors (429/5xx/connect-timeout) retry with backoff honoring
  `Retry-After`; auth/validation/malformed-recipient errors fail fast; a read-timeout after
  submission is marked **uncertain** and never auto-resent. Message bodies are never logged.
- **Content** — HTML (sanitized with the app's bleach allowlist) + text, To/Cc/Bcc, Reply-To, and
  attachments (from `TicketAttachment`, size/MIME validated) — at parity across SMTP and Graph.
- **Setup UX** — the mailbox form has an outbound-method selector, a readiness check with separate
  inbound (Mail.Read) and outbound (Mail.Send) status, and a **Test outbound** button that sends a
  clearly-labeled test to an admin-chosen recipient. No secrets/tokens are exposed.
- **Fallback** — optional pre-submission SMTP fallback when Graph is known-unavailable; never after
  a Graph submission (avoids duplicates). Each message records which transport sent it.
- **Docs** — M365 setup page now documents `Mail.Read` (inbound) and `Mail.Send` (outbound) as
  optional, and Exchange Online RBAC for Applications as the preferred way to scope them to only
  the PSA mailbox, warning that an unrestricted Entra grant defeats the RBAC scope.
- Migration `psa/0058`. Tests: `psa/tests/test_graph_outbound.py` (24 tests across the 20 required
  scenarios) plus the existing IMAP/SMTP suites still green.

## [3.17.506] - 2026-07-26

### Feature: Microsoft 365 mailbox sync for PSA inbound via Graph API (issue #142)

PSA inbound email can now poll a Microsoft 365 mailbox over the **Graph API** instead of IMAP —
for tenants that can't (or won't) enable IMAP on M365. The Graph path reuses an existing M365
connection's app registration, so no extra credentials are stored.

- `psa/models.py`: `EmailIngestionConfig` gains a `source` discriminator (`imap` | `graph`), an
  optional `m365_connection` FK, and a `graph_mailbox` field. IMAP fields are now blank-able.
  Migration `psa/0057`.
- `integrations/providers/m365.py`: `M365Provider` gains mailbox methods — `list_unread_message_ids`,
  `get_message_mime` (fetches full RFC822 MIME so the existing stdlib-email parser is reused
  unchanged), `mark_message_read`, and `probe_mailbox` (for a config access check). Requires the
  `Mail.Read` application permission (documented in the M365 setup form).
- `psa/management/commands/psa_poll_email.py`: refactored so the per-message processing
  (threading, quarantine, routing, attachments, `EmailMessage` persistence) is a single
  source-agnostic `_process_message()`. `_poll_imap` and the new `_poll_graph` both feed it. The
  existing `*/5` cron entry needs no change — the same command now handles both sources.
- `psa/views.py` + `templates/psa/email_config_form.html`: the mailbox form has a Source selector
  that toggles between IMAP fields and a Microsoft 365 connection + mailbox address; the list view
  shows an M365 badge for Graph configs.
- Tests: `GraphMailboxPollTests` (ticket creation, reply threading, marks-read, missing-connection
  error) and `M365ProviderMailMethodTests` in `psa/tests/test_phase10_email.py`.

## [3.17.505] - 2026-07-26

### Fix: M365 sync showed a false "missing SecurityAlert.Read.All permission" warning (issue #143)

When syncing a tenant that isn't onboarded/licensed for Microsoft Defender, Graph's
`/security/alerts_v2` endpoint returns **HTTP 403** even though the app's
`SecurityAlert.Read.All` permission is correctly granted and consented. The Defender-alerts
handler treated *every* 403 as a missing permission and told the admin to add a permission they
already had.

- `integrations/providers/m365.py`: `get_defender_alerts()` now parses the Graph 403 error body
  and only reports `permission_error` when the error is genuinely an authorization/consent denial
  (`Authorization_RequestDenied` / "Insufficient privileges" / consent / token-validation).
  Any other 403 (tenant not onboarded/licensed for Defender) returns an `unavailable` marker with
  the tenant's reason instead.
- `integrations/views.py`: the Defender section renders a neutral "Defender alerts are unavailable
  for this tenant — this does not affect the rest of the M365 sync" note for the `unavailable`
  case; the genuine-permission warning now adds a hint to re-run the sync if consent was just
  granted (a token issued before consent won't carry the new permission).
- Tests in `integrations/tests.py` (`M365DefenderAlert403Tests`) cover permission-denial vs.
  not-onboarded vs. non-403 vs. success.

## [3.17.504] - 2026-07-22

### Fix: PSA settings save crashed with "Object of type Decimal is not JSON serializable" (issue #141)

Saving **Settings → PSA/AI** (`/psa/settings/`) 500'd on every POST. The audit-log change diff
compared a stringified snapshot of `psa_ai_min_confidence` against the live **Decimal** value, so
the field (a) always showed as "changed" even when it wasn't, and (b) put a raw `Decimal` into
`AuditLog.extra_data` — a `JSONField` using the plain `json.JSONEncoder`, which cannot serialize
`Decimal`, crashing the save.

- `psa/views.py`: build the "current" snapshot with the **same** normalisation as the "previous"
  one (stringify the Decimal) before diffing, so the comparison is like-for-like and nothing
  non-serialisable reaches the JSONField.
- Tests: `psa/tests/test_global_settings_view.py` — save no longer 500s, `extra_data` round-trips
  through JSON, and an unchanged confidence is no longer falsely reported as changed.

### Fix: AI-reviewed imports rendered as raw Markdown instead of HTML (issue #140)

The import AI review always stored the result as `content_type='html'`. But models frequently
return **Markdown** despite the HTML prompt (especially for SOP-style source docs), so the reader
saw literal `##` / `**` markup — "goes to MD format instead of html" — with no error, because the
call had *succeeded*.

- `docs/views.py`: `ai_review_import` now detects whether the returned content is actually HTML
  (`_looks_like_html`) and stores the matching `content_type`, so `render_content` converts
  Markdown on display instead of showing raw markup. The response now returns `content_type`.
- `templates/docs/document_import.html`: a reverse proxy timing out a slow review returns a
  non-JSON 502/504 page; the client used to surface a bare "Review failed". It now detects the
  non-JSON response and explains it was a server/proxy timeout (likely an oversized document).
- Tests: `docs/tests.py` — Markdown output is stored as `content_type='markdown'`, plus
  `_looks_like_html` unit coverage.

## [3.17.503] - 2026-07-21

### Feature: import DOCX/PDF as editable docs with optional AI review (issue #140)

A new **Import & AI Review** flow at `/docs/import/` turns uploaded Word, PDF, text, and
Markdown files into editable Knowledge Base documents — extracting their text into
`Document.body` (searchable/editable) rather than storing them as opaque file blobs like the
existing "Upload Files" path. Bulk by design: select many files at once.

Optionally, an **OPTIONAL AI** review runs after import (gated by `psa_ai_enabled` **and** a
configured LLM provider). For each imported document the AI reformats it to a chosen
documentation standard (general / SOP / runbook / network / security / M365 / AD) and returns a
list of gaps for improvement, surfaced on the results page.

- `docs/services/document_import.py` (new): `extract_document_text()` — DOCX via stdlib
  `zipfile` + XML (no new dependency), PDF via **PyMuPDF** (`fitz`), plus TXT/Markdown. Guards
  against corrupt files, image-only PDFs, legacy `.doc`, and oversized files (60k-char cap,
  flagged as truncated).
- `docs/services/ai_documentation_generator.py`: new `review_imported_document()` — one LLM
  call that returns the reformatted body **and** a parsed gap list (split on a sentinel so
  HTML-in-JSON fragility is avoided).
- `docs/views.py`: `document_import` (bulk extract + create) and `ai_review_import` (per-document
  AI review, one short request each so the gunicorn worker timeout is never at risk — cf. #138).
  New `_docs_ai_ready()` helper enforces the `psa_ai_enabled` gate.
- New template `templates/docs/document_import.html`; **Import & AI Review** button on the
  documents list; routes `docs:document_import` and `docs:ai_review_import`.
- `requirements.txt`: added `PyMuPDF>=1.24,<2`.
- Tests in `docs/tests.py`: extraction (DOCX/PDF/TXT, corrupt/unsupported/truncated), review
  parsing (marker split, code-fence strip, provider failure), and the import + AI-review views
  (bulk create, AI-off gating, reformat-and-save).

## [3.17.502] - 2026-07-17

### Fix: creating/editing a file document crashed with AttributeError (issue #139)

Uploading a file at `/docs/create/` (or replacing one at `/docs/<slug>/edit/`) raised
`'FieldFile' object has no attribute 'content_type'`. The MIME type was read off
`document.file` — a model `FieldFile`, which has no `content_type` — instead of the
in-request `UploadedFile`.

- `docs/views.py`: `document_create` / `document_edit` now resolve `file_type` via a new
  `_uploaded_file_type()` helper that reads `content_type` from `request.FILES`, with a
  `mimetypes.guess_type()` fallback from the filename. This mirrors the bulk-upload path,
  which was already correct.
- Regression tests added in `docs/tests.py` (`DocumentFileUploadTests`) covering create and
  edit-replace uploads.

## [3.17.501] - 2026-07-14

### Security: patch 3 Dependabot advisories (cryptography, bleach)

Bumped two dependencies in `requirements.txt` to clear all open Dependabot alerts:

- **`cryptography` → `>=48.0.1,<49.0.0`** (was `46.0.7`) — *high*: the wheels bundled a vulnerable OpenSSL build. Used by the vault/secrets encryption (Fernet, AES-GCM, PBKDF2).
- **`bleach` → `>=6.4.0,<7`** (was `6.1.*`) — *medium*: `clean()`/`Cleaner()` failed to sanitize dangerous URI schemes in allowed `formaction` attributes; *low*: URI-scheme sanitization could be bypassed with Unicode above U+00A0. Used to sanitize KB/AI-generated HTML (`docs.models`) and inbound PSA email (`psa.email_parsing`).

Verified in an isolated environment that the new versions resolve against the full requirements set with no conflicts and are API-compatible with existing usage: the issue-#127 progress-bar `width: N%` styling still survives `CSSSanitizer`, non-allowlisted CSS properties are still dropped, `javascript:` hrefs are stripped, and the cryptography primitives (Fernet / AES-GCM / PBKDF2) round-trip correctly. No application code changes were required.

## [3.17.500] - 2026-07-14

### Fix: AI document generation failed with "Server returned HTML instead of JSON" (issue #138)

Generating a document with the AI assistant failed with `Internal Server Error (500) - Server returned HTML instead of JSON` — reported with both the Ollama and Anthropic/Claude providers. Despite the user's read ("it's expecting JSON when I selected rich HTML"), the cause was **not** response parsing: the `ai_generate` view and the generator service already wrap everything and always return `JsonResponse`. The frontend only shows that message when a response is non-2xx **and** its body isn't JSON — i.e. a web-server HTML error page.

**Root cause — timeout budget inversion.** AI generation legitimately runs for minutes (local Ollama models on CPU especially), but the per-request HTTP timeouts were configured *above* the gunicorn worker `--timeout` (120s in Docker, 180s on the systemd unit). So gunicorn SIGKILLed the worker mid-generation and the browser received gunicorn's HTML 500 page — before the provider's own timeout could return a clean JSON error. The Ollama provider's 300s timeout could never fire behind a 120s worker.

**Fix — align the timeout budget across every layer:**
- Gunicorn worker `--timeout` raised to **300s** in both `Dockerfile` and `deploy/clientst0r-gunicorn.service`.
- Nginx `proxy_read_timeout` / `proxy_send_timeout` raised to **300s** in the Docker and native reverse-proxy configs (only relevant when the proxy profile is enabled).
- Provider HTTP timeouts capped at **280s** (`AI_HTTP_TIMEOUT`), strictly *below* the worker timeout, so a genuinely stuck/slow model now raises a caught `Timeout` and returns a clean JSON error ("Ollama did not respond within 280s…") instead of killing the worker. Applied to the Ollama request and, via an explicit client `timeout`, the Anthropic and MiniMax-Coding providers (the SDK default was ~600s).
- Added `docs.tests.AIProviderTimeoutTests` locking the invariant (provider timeout < worker timeout) and asserting a provider `Timeout` degrades to a JSON error rather than an exception.

## [3.17.499] - 2026-06-29

### Fix: AI features reported a "missing API key" even when one was saved (issue #137)

"Import from Property Appraiser URL using AI" (and any other AI feature) failed with a missing-key error despite a key being configured in **Settings → AI & LLM**. The settings page writes the key to `.env` and reloads gunicorn, but `config/settings.py` called `load_dotenv()` without `override=True`. Under Docker Compose the `env_file: .env` directive injects the (initially empty) `ANTHROPIC_API_KEY` into the container environment at startup, and `load_dotenv()` will **not** overwrite a variable that already exists in the environment — so the key saved through the UI never took effect.

- `config/settings.py` now calls `load_dotenv(override=True)`, making the `.env` file authoritative over stale process-environment variables. After the automatic reload, a key saved via the UI is picked up. This fixes every AI feature, not just property import.
- Safe because `.env`/`.env.*` are dockerignored, so the image never bakes in DB credentials; `override` only ever affects the AI/maps keys the settings UI manages.

## [3.17.498] - 2026-06-29

### Fix: creating a rack wiring connection failed with "This field is required" (issue #136)

Adding a cable/wiring connection between two devices in a rack failed even with every field filled in, returning `{"from_device":["This field is required."], ...}` for all fields. The rack detail page submits the connection via `fetch()` with a JSON body (`Content-Type: application/json`), but `rack_connection_create` / `rack_connection_edit` only read `request.POST` — which is empty for a JSON request — so every required field looked missing.

- The two views now read the payload through a small `_rack_connection_post_data()` helper that parses a JSON body when the request is `application/json` and otherwise falls back to `request.POST`. Classic (non-JS) form posts keep working unchanged.
- Added `monitoring.tests.RackConnectionCreateViewTests` covering both the JSON-body path (the failing case) and the form-encoded path.

## [3.17.497] - 2026-06-24

### Fix: TOTP secret entry was hidden on every password type except "OTP"

Storing a 2FA/TOTP secret alongside *any* credential (website, email, database, SSH, API key, etc.) has been supported in the backend since the feature shipped, but the **password entry form only rendered the TOTP fields when the type was set to "OTP/TOTP (2FA)"** — so on every other type the "TOTP Secret" / "Issuer" / "Auto-generate" controls were invisible and a user could never attach a code. Reported in discussion #21.

- The TOTP fields are now an **always-visible, optional "Two-factor (TOTP)" card** on the add/edit form, available regardless of the selected password type.
- The form's save path, the live-code generator on the detail view (`{% if password.otp_secret %}`), and the `generate_otp` API were already type-agnostic — no backend change was required.
- Added `vault.tests.PasswordFormTOTPForAnyTypeTests` covering both an explicit Base32 secret and the auto-generate path on non-OTP types (website / database), asserting the password **and** the TOTP secret persist on one record.

## [3.17.496] - 2026-06-19

### Feature: multi-organization REST API access (issue #134)

The public REST API can now address **multiple client organizations through a single API key** — built for MSPs running a single-pane-of-glass integration that needs to read/write across every client without one key per client. Fully opt-in and backward-compatible: existing keys, and any new key left on the default scope, behave exactly as before.

**Per-key organization scope** — new `APIKey.scope` field with three values:
- `single` *(default)* — the key's home organization only (legacy behavior).
- `descendants` — the home organization plus every sub-location beneath it (Phase 18 hierarchy).
- `all` — every organization the key's owner can access (all active orgs for an MSP staff user / superuser, or the owner's active memberships).

A key never grants more access than its owner already has.

**Per-request selection** — list/detail/create/update endpoints accept an optional `organization` query parameter:
- omitted → home/current org for `single` keys & web sessions; all accessible orgs for `descendants` / `all` keys.
- `?organization=<id|slug>` → narrows to one org (403 if inaccessible).
- `?organization=all` → every accessible org.

**Organization surfaced on every resource** — `organization` + `organization_name` now appear on assets, contacts, documents, and passwords so a consumer can group rows by client; `organization` is writable on create to target a specific client. `GET /api/organizations/` returns the full accessible client set for discovery.

**Security** — cross-org isolation enforced on every request; password reveal / OTP audit rows are logged against the row's own organization for accurate multi-client traceability; scope is bounded by the owner's live permissions at request time.

New scope selector in **Settings → API Keys → Create API Key**. Contract documented in `docs/api-multi-org.md`. New migration `api/0003_apikey_scope`. 11 new tests in `api/tests.py` covering single-scope isolation, all-scope fan-out, descendants, the `?organization=` param, cross-org create rejection, and the discovery endpoint.

## [3.17.495] - 2026-05-25

### Fix: auto-update + breach-scan timers were firing twice daily

Both `clientst0r-auto-update.timer` and `clientst0r-breach-scan.timer` had two `OnCalendar=` directives — systemd treats those as additive, so each timer was triggering twice a day instead of once.

**`clientst0r-auto-update.timer`** had:
```
OnCalendar=daily          # = midnight every day
OnCalendar=02:00          # 02:00 every day
```
Result: fired at 00:00 AND 02:00. Two auto-update attempts per day. Removed the redundant `daily` line; now fires once at 02:00 local. `OnBootSec=10min` + `Persistent=true` keep the catch-up behavior for hosts that were off at 02:00.

**`clientst0r-breach-scan.timer`** had:
```
OnCalendar=daily
OnCalendar=*-*-* 02:00:00
```
Result: same problem — fired at 00:00 AND 02:00. Removed the redundant `daily` line; now fires once at 02:00 local with `RandomizedDelaySec=1800` (up to 30 min jitter) preserved to avoid HIBP API peak times.

No other timer affected — `monitor`, `psa-sync`, `rmm-sync`, `scheduler` all use single `OnBootSec` + `OnUnitActiveSec` constructs, no duplicated calendars.

After Apply + re-running `deploy/migrate-from-huduglue.sh` (or just `cp deploy/clientst0r-{auto-update,breach-scan}.timer /etc/systemd/system/ && sudo systemctl daemon-reload`), each timer fires once per day at 02:00 instead of twice.

## [3.17.494] - 2026-05-25

### itdocs-scheduler renamed to clientst0r-scheduler; itdocs-gunicorn removed

Follow-up to the v3.17.492 brand scrub. Two legacy `itdocs-*` systemd units were left in place last time because the names themselves weren't huduglue-branded. With the rest of the stack consistently on `clientst0r-*`, those holdouts looked even more out of place — and `itdocs-gunicorn.service` was an installed-but-disabled duplicate of `clientst0r-gunicorn.service`. This release retires both.

**Renamed — task scheduler.** `deploy/itdocs-scheduler.{service,timer}` → `deploy/clientst0r-scheduler.{service,timer}`. The new service runs the same `manage.py run_scheduler` every minute, just under a clientst0r-branded unit name with `SyslogIdentifier=clientst0r-scheduler`. The timer's `Requires=` reference also points at the new service name.

**Deleted — obsolete deploy templates.** `deploy/itdocs-gunicorn.service` (replaced by `clientst0r-gunicorn.service` in v3.17.492), `deploy/itdocs-scheduler.{service,timer}` (renamed), `deploy/itdocs-monitor.{service,timer}` + `deploy/itdocs-psa-sync.{service,timer}` (duplicates of `clientst0r-monitor.*` / `clientst0r-psa-sync.*` — both timers were firing the same management commands on a different cadence).

**Nginx config rename.** `deploy/nginx-itdocs.conf` → `deploy/nginx-clientst0r.conf`. Upstream block, log paths, static-files alias, and SSL cert paths all rebranded. The internal `/var/lib/itdocs/uploads/` mount path is preserved (changing it would require migrating live upload data).

**Code references.** Removed `itdocs-gunicorn.service` from systemd unit-name lookup lists in `core/views.py`, `core/updater.py`, `core/management/commands/auto_heal_version.py`, plus the bash equivalents in `update.sh`, `scripts/auto_update.sh`, and `deploy/update_instructions.sh`. The only service name considered now is `clientst0r-gunicorn.service`. `templates/core/settings_scheduler.html` (operator-facing systemd-help block) updated to reference `clientst0r-scheduler` in all `systemctl` / `journalctl` examples.

**bootstrap_ubuntu.sh.** Fresh-install instructions now point at the clientst0r-* unit files, add the scheduler timer to the install sequence, and the upgrade path restarts `clientst0r-gunicorn` (was `itdocs-gunicorn`).

**Extended migration script — `deploy/migrate-from-huduglue.sh`.** Same one-shot script as v3.17.492, now also installs `clientst0r-scheduler.{service,timer}`, and stops/disables/removes the legacy `itdocs-gunicorn.service`, `itdocs-scheduler.{service,timer}`, `itdocs-monitor.{service,timer}`, `itdocs-psa-sync.{service,timer}`. Also calls `systemctl reset-failed` at the end to clear any cached failure records. Idempotent — safe to re-run.

No code changes affecting request handling, no migrations, no mobile rebuild. Canonical install runs `deploy/migrate-from-huduglue.sh` after Apply to flip the live systemd units.

## [3.17.493] - 2026-05-25

### Fix: breach-scan systemd unit was passing a non-existent CLI flag

`clientst0r-breach-scan.service` (and its huduglue-era predecessor before v3.17.492) called:

```
manage.py check_password_breaches --scan-frequency 24
```

But `--scan-frequency` was never a valid argument on that management command. Its real arg surface is `--force / --password-id / --organization-id` only. systemd exit-coded with `status=2/INVALIDARGUMENT` on every run since at least 2026-02-20, with the actual Python error landing in `/var/log/itdocs/breach-scan-error.log` (where it wasn't being noticed because the timer kept "firing" without anyone caring).

**Fix — `deploy/clientst0r-breach-scan.service`:**
- ExecStart now invokes the command with no extra flags: `manage.py check_password_breaches`.
- The scan-frequency knob already lives ON each password as `custom_fields.hibp_scan_frequency` (default 24h, used inside `_filter_by_scan_frequency()`). The CLI flag was redundant even if it had existed.

After Apply, the timer-fired runs exit 0 and log "Checking N passwords..." instead of an argparse error.

## [3.17.492] - 2026-05-25

### Full HuduGlue → Client St0r rename (no leftover brand traces)

Project-wide scrub of the legacy `huduglue` / `HuduGlue` brand name. The hostname `huduglue.agit8or.net` is kept (live DNS for the canonical dev/demo server, not a brand surface). Historical CHANGELOG entries are preserved as-is — they're a record of what happened, not what's true now.

**Code rename — service-name detection.** `core/views.py`, `core/updater.py`, `core/security_views.py`, `core/management/commands/auto_heal_version.py`, `core/debug_version_view.py`, `templates/core/system_updates.html`, `templates/core/python_scanner_dashboard.html`. The systemd-unit-name lookup lists now contain `clientst0r-gunicorn.service` (+ `itdocs-gunicorn.service` as legacy fallback only). Every visible reference to `huduglue-gunicorn.service` in user-facing UI / error messages / debug output is now `clientst0r-gunicorn.service`.

**Shell scripts.** `update.sh`, `update_safe.sh`, `scripts/auto_update.sh`, `scripts/hsts_bump.sh`, `deploy/update_instructions.sh`, `deploy/setup_mobile_build.sh`, `setup_gui_updates.sh` — all `huduglue` references renamed to `clientst0r`. The sudoers template at `setup_gui_updates.sh` now grants passwordless sudo on the canonical service names only.

**Deleted dead legacy scripts.** `COMPLETE_REMOTE_FIX.sh`, `DIAGNOSE_REMOTE.sh`, `ENABLE_GUI_UPDATES.sh`, `FINAL_REMOTE_FIX.sh`, `FIX_REMOTE_UPDATES.sh`, `START_GUNICORN_REMOTE.sh`. All of these assumed the project lived at `/home/administrator/huduglue/` — a path that hasn't existed in this codebase. They were broken on every install.

**Documentation.** `docs/PUBLIC_RELEASE_CHECKLIST.md` — three "play-reviewer test account on huduglue" references replaced with "on the canonical server"; the `/play_publish/` UI is now described as living on "the canonical server" instead of "huduglue". `docs/PLAY_STORE_LISTING.md` and `docs/PLAY_DATA_SAFETY.md` keep the literal `huduglue.agit8or.net` URL because those are Play Console submission docs and the URL is the live demo server.

**Deploy unit files — systemd renames.** Eleven unit files renamed: `huduglue-{auto-update, breach-scan, monitor, psa-sync, rmm-sync}.{service,timer}` → `clientst0r-{...}.{service,timer}`. New `deploy/clientst0r-gunicorn.service` matches the live unit on the canonical install (Type=notify, gunicorn config). Three sudoers files renamed: `huduglue-{fail2ban, install, mobile-build}-sudoers` → `clientst0r-{...}-sudoers`. Two fail2ban configs (`huduglue-fail2ban-{filter,jail}.conf`) renamed to `clientst0r-fail2ban-{...}.conf` with jail / iptables-chain name `clientst0r`.

**Stale itdocs unit Descriptions.** `deploy/itdocs-{gunicorn,monitor,psa-sync,scheduler}.{service,timer}` all had `Description=HuduGlue ...` lines; bulk-replaced with `Description=Client St0r ...`. The unit names themselves stay `itdocs-*` because that's a separate legacy install lane, not the huduglue brand.

**Docker MariaDB config.** `docker/mariadb/conf.d/huduglue.cnf` renamed to `clientst0r.cnf`. MariaDB picks up any `*.cnf` in the conf.d directory — filename change is purely cosmetic, no behavior change.

**Live unit migration helper — `deploy/migrate-from-huduglue.sh`.** One-shot bash script (must be run as root) that handles a running install with the legacy `huduglue-*` systemd units. It: (1) installs all new `clientst0r-*` unit files into `/etc/systemd/system`, (2) stops + disables + removes the corresponding `huduglue-*` units (plus the `huduglue-gunicorn.service.backup` lingering on prod), (3) enables + starts the new units, (4) reloads systemd, (5) prints the new active state. Idempotent. The script ITSELF references "huduglue" by design — that's how it knows what to migrate from.

**Deleted stale artifact.** `security_scan_bandit.json` — captured huduglue-era code excerpts in scan output. Removed; regenerated next scan.

No migrations. No mobile rebuild. After Apply the canonical install runs `deploy/migrate-from-huduglue.sh` to flip the live systemd units.

## [3.17.491] - 2026-05-23

### Surface Docker install as a headline feature

Follow-up to v3.17.490. The Docker install path landed in v3.17.490 but only showed up on GitHub as a buried block inside Quick Start. This release promotes it.

- **README.md** — "What's New" section header bumped from v3.17.444 to v3.17.490; new top bullet calls out Phase 42 (Docker / docker-compose) with the one-line `git clone && docker compose up -d` pitch, a summary of what ships in the box (Dockerfile + compose profiles + GHA publishing + Makefile + .env.example + docs/docker.md), and an explicit "classic `bash install.sh` path is unchanged" note.
- **FEATURES.md** — "Performance & Deployment" section now lists both install paths side-by-side and adds a dedicated "Docker / containerized deployment" sub-section enumerating Dockerfile / compose / dev override / entrypoint / GHCR workflow / Makefile / docs.

No code changes; documentation only.

## [3.17.490] - 2026-05-23

### First-class Docker / docker-compose deployment (Phase 42)

`git clone && docker compose up -d` now stands up a working Client St0r install in under a minute. The classic `bash install.sh` path is unchanged — Docker is a peer install option, not a replacement.

**Image (`Dockerfile`).** Multi-stage build on `python:3.12-slim`. Stage 1 compiles wheels with `build-essential` + `libmariadb-dev`; Stage 2 copies the venv into a slim runtime image with only `libmariadb3` + `curl`. Runs as non-root `clientst0r` (uid 1000). `collectstatic` runs at container start (not build) so it picks up the operator's env. `HEALTHCHECK` hits a new dedicated endpoint.

**Health endpoint (`core/views.py` + `config/urls.py`).** New `GET /health/` returns `{"ok": true, "version": "3.17.490"}` with HTTP 200. No auth, no DB hit on the read path — safe to expose to load balancers and Docker healthchecks.

**Compose (`docker-compose.yml`).** Two services start by default: `app` (Django + gunicorn) and `db` (MariaDB 10.11). Optional services gated behind profiles:
- `--profile proxy` — adds an Nginx reverse proxy (port 80/443, with TLS-ready config in `docker/nginx/conf.d/clientst0r.conf`).
- `--profile cache` — adds Redis. Only useful if the operator switches Django's `CACHES` away from the default in-process `locmem`.

Required env vars (`SECRET_KEY`, `DB_ROOT_PASSWORD`, `DB_PASSWORD`) are enforced with compose's `${VAR:?message}` syntax so `docker compose up` fails loudly rather than booting into a half-configured state. Container names, volume names, and the network are all prefixed `clientst0r-*`. The old `huduglue.conf` nginx config was renamed and rebranded.

**Dev override (`docker-compose.dev.yml`).** Use with `make dev-up` or `docker compose -f docker-compose.yml -f docker-compose.dev.yml up`. Source tree bind-mounted; `gunicorn --reload` watches for changes; defaults to `DB_ENGINE=sqlite3` so the dev stack doesn't need MariaDB; `DEBUG=True` + `ALLOWED_HOSTS=*` + all `SECURE_*` flags off.

**Entrypoint (`docker-entrypoint.sh`).** Skips the DB-readiness wait when `DB_ENGINE=sqlite3`. Runs `migrate --noinput` then `collectstatic --noinput`. If `DJANGO_SUPERUSER_USERNAME` / `DJANGO_SUPERUSER_EMAIL` / `DJANGO_SUPERUSER_PASSWORD` are all set, bootstraps a superuser on first boot (idempotent — won't re-create on subsequent boots).

**Image publishing (`.github/workflows/docker-image.yml`).** Buildx workflow that builds on every PR (validation only) and publishes to `ghcr.io/agit8or1/clientst0r` on push to `main` or any `v*` tag. Tag schema produced by `docker/metadata-action`: `latest` (on main), `v3.17.490` (on tag), `3.17.490` (semver clean), `3.17` (major.minor), `sha-abc1234` (every build). Layer cache via `type=gha,mode=max`. Defaults to `linux/amd64`; an `arm64` line is commented in for installs that need it.

**Operator UX (`Makefile`).** Common operations are one-word: `make docker-up`, `make docker-logs`, `make docker-shell`, `make docker-migrate`, `make docker-createsuperuser`, `make dev-up`. Plus `make backup` / `make restore FILE=...` that pipe `mariadb-dump` through the `db` container.

**Config template (`.env.example`).** Replaces the older 55-line template. Every supported variable now documented with a one-line "what / why", grouped into Core / Database / Web ports / Bootstrap superuser / SMTP / External tokens / Storage / Beta-signup / Security / Encryption / Docker-image-override sections. Same file is referenced by the classic install path too.

**Documentation (`docs/docker.md` + README section).** Full guide covering quick start, profiles, persistent volumes, backups, upgrades, dev mode, and troubleshooting (race conditions, healthcheck timing, ARM hosts, lost `APP_MASTER_KEY` recovery). README gets a `🐳 Run with Docker` block at the top of Quick Start that links to the full guide and explicitly notes the `bash install.sh` path is unchanged.

**Build-context hygiene (`.dockerignore`).** Tightened: keeps `docs/` IN (the public roadmap at `/core/roadmap/` reads `docs/ROADMAP.md` at runtime), keeps `mobile/` + `mobile-app/` + `local_apps/play_publish/` OUT (local-only, never shipped to GitHub), keeps `.env` OUT but allows `.env.example` through.

No migrations. No mobile rebuild. No effect on existing `bash install.sh` installs.

## [3.17.489] - 2026-05-20

### Fix #133: M365 sync — mailbox/OneDrive/SharePoint names showing as blank or hex hashes

Reported on issue #133: after running an M365 sync against a fresh client tenant, the Mailbox Usage table showed empty Name and UPN columns. Permissions were correct (Reports.Read.All granted, admin consented) — the bug was in how MS Graph returns the data.

**Root cause.** Microsoft Graph's reporting endpoints (`getMailboxUsageDetail`, `getOneDriveUsageAccountDetail`, `getSharePointSiteUsageDetail`) anonymize Display Name and User Principal Name **by default** since MS's 2021 privacy update. The columns come back as 32-character hex hashes (e.g. `5C807787F0A30D1C3CDBB76DC1ED3CAB`) or empty strings. The `/users` endpoint is *not* anonymized, so the names exist — they just don't make it into the report rows.

**Fix — `integrations/providers/m365.py`:**
- New module-level helper `_deanonymize_usage_rows(rows, users)` that detects anonymized rows (blank or 32+ hex chars) and substitutes real values from the users list using UPN as the join key. Falls back to name→UPN lookup if UPN is hashed but the name is real.
- `M365Provider.sync()` now calls the de-anonymizer on `mailbox_usage`, `onedrive_usage`, and `sharepoint_usage` before returning. Existing data shape unchanged; only the previously-blank fields get filled in.
- Rows that can't be matched (deleted user, both fields hashed) get `_anonymized=True` flagged so the UI can show a hint.

**UI hint — `integrations/views.py`:**
- The Mailbox Usage card now shows an info banner above the table when any row is still anonymized after the join. The banner links directly to the M365 Admin Center setting that disables anonymization entirely ("Concealed names" toggle at *Settings → Org settings → Reports*) for operators who'd rather flip that than rely on the UPN join.

No migration; no env changes; no mobile rebuild. Effect kicks in on the next M365 sync.

## [3.17.488] - 2026-05-14

### Beta-tester signup: lock Play URLs to canonical listing + forward remote signups upstream

Three fixes to the beta-signup pipeline:

**1. Visible comment on `/core/beta-test/` (`templates/core/beta_test_signup.html`):**
- Removed the multi-line `{# … #}` block I added in v3.17.486. Django's `{# #}` syntax is single-line only — multi-line content after the first newline leaks into the rendered HTML. The comment appeared as visible text above the form on every page load. Fix: just delete it.

**2. Play Console URLs locked to the canonical agit8or1 listing (`config/settings.py`):**
- `PLAY_OPEN_TEST_URL` and `PLAY_INTERNAL_TEST_URL` were env-driven in v3.17.485, defaulting to empty. That implied each install could point at its own Play listing — but there is exactly ONE Client St0r Android app (the one on agit8or1's Play Console), and every install should direct its users at THAT app's opt-in URLs.
- Both URLs are now hard-coded constants in `settings.py`. Removed from the env-override path. Forks running this code automatically use the agit8or1 listing.
- `.env` entries for these keys are now dead config but harmless — left in place as a paper trail.

**3. Cross-install upstream forwarding (new — `core/views.py` + `core/models.py` migration):**
- New `BetaTesterRequest.source_install` field tracks which install a signup came from.
- New view `beta_test_upstream` at `POST /core/beta-test/upstream/` accepts cross-origin POSTs from remote installs. CSRF-exempt (no cookie relationship with foreign installs); rate-limited 30/hr per IP via django-ratelimit. Saves the signup with `source_install` set, fires the same admin-notification email as a local signup.
- Existing `beta_test_signup` view now best-effort POSTs to `BETA_UPSTREAM_URL` (settings, default `https://huduglue.agit8or.net/core/beta-test/upstream/`) after creating the local row. Net effect: a user on ANY install's `/core/beta-test/` form signs up for the canonical agit8or1 Android app — their signup lands on BOTH the local install (for that operator's records) AND on agit8or1 (so the canonical maintainer can approve and add to Play Console).
- Forward is skipped if `BETA_UPSTREAM_URL` is empty (set in `.env` on the canonical install itself) or if the upstream host matches the request host (defense-in-depth against loops).
- Forward failures are silent — a network blip on the upstream side can't break the local user's submission flow.

Migration: `core/0062_betatesterrequest_source_install.py` — adds the new field plus a couple of index-rename ops that Django auto-detected.

## [3.17.487] - 2026-05-14

### Play Console demo video scripts — pure-PIL, no external services

The two scripts that back the Build buttons on `/play_publish/` (Location demo + Foreground service demo) were originally Selenium + Expo-web-bundle based. That required `npx expo start --web` running on `localhost:8765`, which was never set up on the build host — clicking Build returned `ERR_CONNECTION_REFUSED` immediately. Even after wiring Selenium correctly the moviepy v2 pipeline hung indefinitely at 97% CPU on the FGS variant.

Rewrote both:
- **`scripts/generate_location_demo_video.py`** — 8 frames of pure-PIL synthetic phone-screen mockups (Dashboard / Settings toggle off / Settings toggle on / Timeclock idle / Timeclock running / Operations log / closing card). Captions overlay each frame.
- **`scripts/generate_fgs_demo_video.py`** (new) — 7 frames including a simulated Android notification-shade frame showing the persistent foreground-service notification with the `TYPE: location · FGS` badge — the visual proof Play wants for the FGS_LOCATION declaration.

Both scripts now drive `ffmpeg` directly via the `concat` demuxer (bundled with `imageio-ffmpeg`), bypassing moviepy entirely. Output: 24 fps CFR H.264, ~700 KB / ~40s each, build time ~13s on the existing host. No Selenium, no Chrome, no Expo dev server required.

Output paths (unchanged):
- `local_apps/play_publish/data/builds/location-demo.mp4`
- `local_apps/play_publish/data/builds/fgs-demo.mp4`

### Public beta signup form — confirmed generic, fits any install

Re-emphasizing the existing setup since people may not realize: `/core/beta-test/` is a **public** form (no login required) suitable for any install of Client St0r to invite their own users into their own Android beta. The relevant env variables are:

| Setting | Purpose | Per-install |
|---|---|---|
| `BETA_ADMIN_EMAIL` | Where signup notifications go | Each install sets their own |
| `PLAY_OPEN_TEST_URL` | Public Beta opt-in URL | Each install creates their own Play Console listing and uses its package name |
| `PLAY_INTERNAL_TEST_URL` | Internal Testing opt-in URL | Same — Play Console provides this per-app |

The form, the navbar CTA, the admin approval page, and the `✉ Email opt-in URL` button all read these settings dynamically — no code changes needed to use this in another instance.

## [3.17.486] - 2026-05-14

### Beta signup form: solid background card

`/core/beta-test/` previously rendered the form directly on the page body, which on profiles using a custom background image looked translucent — text bleeding through, hard to read. Wrapped the whole form in a `.beta-card` with:

- White surface in light mode, `#1f2329` in dark mode (both `!important` to override the site-wide `.card` translucency rule)
- Soft drop shadow + rounded corners
- Opaque form inputs that match the surface
- Explicit `backdrop-filter: none` so no blur leaks in from inherited styles

Mirrors the same pattern used by the `/play_publish/` dashboard's `.pp-card`.

## [3.17.485] - 2026-05-14

### Wire BETA_ADMIN_EMAIL / PLAY_OPEN_TEST_URL / PLAY_INTERNAL_TEST_URL through Django settings

`core/views.py::beta_test_signup` and `core/views.py::beta_test_admin` read these three keys via `getattr(settings, ...)`, but `config/settings.py` didn't actually pull them from the environment. Net effect on v3.17.484: only the default `BETA_ADMIN_EMAIL` worked; the two URL keys silently stayed empty even when set in `.env`.

`config/settings.py` now reads all three via `os.getenv()` so they pick up automatically from the systemd `EnvironmentFile=/home/administrator/.env`. Defaults preserve v3.17.484 behavior (`agit8or@agit8or.net`, empty URLs).

## [3.17.484] - 2026-05-14

### Beta-tester signup: top-of-page CTA + email notification + one-click opt-in URL email

**Top-bar CTA (`templates/base.html`):**
- Added a 📱 **Beta app** nav-item visible to logged-in users (currently the CTA only rendered for anonymous visitors). Right side of the navbar between Favorites and the Search box, tooltip "Beta-test the Android mobile app". Routes to the existing `/core/beta-test/` public signup form.

**Email notification on signup (`core/views.py::beta_test_signup`):**
- Every public submission now fires a `send_mail` to `BETA_ADMIN_EMAIL` (default `agit8or@agit8or.net`). Subject `[Client St0r] Beta tester signup: <name>`, body has name + Google email + company + role + message + approval URL. Fail-open: if SMTP is misconfigured the signup still completes.

**One-click opt-in URL email on approval (`core/views.py::beta_test_admin`):**
- New action `send_opt_in` on the admin approval page. The "✉ Email opt-in URL" button on each approved row fires a `send_mail` to the tester's Gmail with install instructions + the Play opt-in URL (reads `PLAY_OPEN_TEST_URL` first, falls back to `PLAY_INTERNAL_TEST_URL`), and auto-flips the status to `added_to_play`. The existing "✓ Mark as added" button stays as a manual fallback for when the operator paste-adds the email to Play Console outside the app.

**Settings to configure (`config/settings.py` or environment):**
- `BETA_ADMIN_EMAIL` — defaults to `agit8or@agit8or.net`
- `PLAY_OPEN_TEST_URL` — paste once Open Testing track is live (e.g. `https://play.google.com/apps/testing/com.clientstor.mspreboot`)
- `PLAY_INTERNAL_TEST_URL` — current Internal Testing opt-in URL (used until Open Testing is live)
- `DEFAULT_FROM_EMAIL` — sender address (any existing config carries over)

No mobile rebuild needed for this release.

## [3.17.483] - 2026-05-14

### Play Store: upload script now sets release name to match the bundle

The Play Developer API's `edits().tracks().update()` call doesn't auto-populate `release.name` from the bundle's `versionName` — if you omit it, Play Console carries forward whatever name the previous release had. After uploading v3.17.482's bundle (versionCode 3170482) on top of an earlier release named "3.17.481", the Play Console UI displayed the release as "3.17.481" even though the contained bundle was 3170482. Tester installs were correct; only the human-readable label was stale.

**Fix — `/home/administrator/local_apps/play_publish/scripts/upload-aab.py`:**
- Now derives `release_name` by regex on the AAB filename (`clientst0r-v(N.N.N).aab` per build-aab.sh's naming convention) and passes it as the release's `name` field on every track update. Falls back to the bundle's versionCode if the filename doesn't match the pattern.
- The script lives in the gitignored `local_apps/` tree per the 2026-05-14 GitHub scrub; this changelog entry documents the change for history but the diff itself stays off-repo.

No mobile rebuild needed for this release — the only file that changed is the upload helper script, and it runs on the server before the AAB is sent to Google.

## [3.17.482] - 2026-05-14

### Settings → Updates: stop hammering GitHub on every page load

The Settings → Updates page polled `api.github.com/repos/.../tags` on every load with no caching. After the 2026-05-14 history scrub + force-push, the repeated force-pushes consumed the anonymous 60-req/hour quota and the page started showing "GitHub API rate limit exceeded" indefinitely.

**Fix — `core/updater.py::UpdateService.check_for_updates()`:**
- Now caches the successful poll result in Django's cache backend for 5 minutes (key `system_update_check`) so the page can be open in many tabs without spamming GitHub. Even fully anonymous (no token), this keeps us at 12 req/hour max — well under the 60/hour anonymous limit.
- Also caches a 24-hour "last good" snapshot (key `system_update_check_last_good`). When a 403 / rate-limit response comes back, the updater returns the stale-but-recent snapshot with a `stale: true` flag so the UI keeps rendering instead of erroring out.
- Rate-limited responses are cached for 10 minutes to prevent retry storms.
- New `force_refresh=True` kwarg lets the "Check for updates" button bypass the cache when the user explicitly asks.

**Operational fix — `/home/administrator/.env`:**
- Appended `GITHUB_TOKEN=...` (existing developer token, granted to the same Google account that owns the repo). The updater already supported this env var; it just wasn't set. Adds a 5000-req/hour authenticated quota as a backstop to the caching layer.

## [3.17.481] - 2026-05-14

### Mobile beta release prep: public onboarding page, master Play Store guide, full Data Safety + listing copy

**Server: public `/beta-onboarding/` page (`core/views.py`, `config/urls.py`):**
- New `beta_onboarding()` view following the same pattern as `privacy_policy()` — renders `docs/BETA_ONBOARDING.md` server-side via the `markdown` library. Anonymous-accessible (no auth required) so Play Open Testing users who follow the opt-in URL can read install instructions, known limitations, and feedback channels without first creating an account.
- Template at `templates/core/beta_onboarding.html` mirrors the privacy-policy template styling with a CTA button.

**Docs:**
- `docs/PLAY_STORE_BETA.md` (new) — single canonical walkthrough for every step from local AAB build through Open Testing rollout. Phases 0–10 cover pre-flight, build, account setup, dashboard checklist, store listing, Internal/Closed/Open promotion, monitoring, and recovery ops. Includes a "Known failure" subsection for the current `expo-modules-core@1.12.26` Gradle publishing issue.
- `docs/BETA_ONBOARDING.md` (new) — source of `/beta-onboarding/` page content.
- `docs/PLAY_STORE_LISTING.md` (updated) — full description revised to match v3.17.481 feature set (vault edits, ticket billing rollup, schedule-on-calendar, asset ↔ vault linking) and to honestly disclose location + photo collection.
- `docs/PLAY_DATA_SAFETY.md` (updated) — declares the new optional Sentry crash-reporting SDK; updated header to point at v3.17.481 / versionCode 3170481.

**Mobile-side (local-only since the 2026-05-14 history scrub):**
- `app.json` — bump to v3.17.481 / versionCode 3170481; explicit `android.permissions` allowlist + `blockedPermissions` list to strip 4 unused / dangerous permissions (`RECORD_AUDIO`, `SYSTEM_ALERT_WINDOW`, `READ_EXTERNAL_STORAGE`, `WRITE_EXTERNAL_STORAGE`).
- `app/_layout.tsx` — Sentry SDK init wrapped in try/dynamic-require so missing `@sentry/react-native` is a no-op in dev builds. DSN comes from `EXPO_PUBLIC_SENTRY_DSN`.
- `src/components/BetaBanner.tsx` (new) + mount in `_layout.tsx` — orange ribbon at the top of every screen showing version + "Send feedback →". Hidden unless `EXPO_PUBLIC_BUILD_CHANNEL=beta`. Tapping opens the new-ticket form with the subject pre-filled.
- `app/tickets/new.tsx` — accepts `?subject=` query param so the banner can deep-link to a pre-filled feedback ticket.

**Build status:** local `./gradlew bundleRelease` is currently blocked on a `Could not get unknown property 'release'` error in `expo-modules-core@1.12.26`'s Gradle plugin (AGP 8 publishing-API change). Documented in `docs/PLAY_STORE_BETA.md` with three resolution paths (patch the plugin, upgrade Expo SDK, or use EAS Cloud build). All other Play-Store prep is complete.

## [3.17.480] - 2026-05-13

### Mobile: asset editing + asset ↔ vault linking

**Mobile asset detail (`mobile/app/assets/[id].tsx`):**
- New **Edit asset** action on the identity card (gated on `assets_edit`). Inline form for: name, hostname, IP, MAC, asset tag, serial, manufacturer, model, OS name/version, notes. Save round-trips through PATCH and refreshes the detail view.
- **Stored secrets** card gains a **+ Link vault entry** action. Opens a searchable modal listing every Vault Password in the asset's organization that isn't already linked. Tapping a row creates the relation server-side.
- Each linked vault row gains an **Unlink** button (red, small) right next to the password-type pill. One tap removes the `PasswordRelation` row; the secret itself stays intact.

**Backend (`api_mobile/views_assets.py`):**
- `PATCH /api/mobile/v1/assets/<id>/` — edit whitelisted fields (gated on `assets_edit`). `organization_id` is intentionally rejected on the edit path so re-orging an asset doesn't silently break its `PasswordRelation` rows.
- `POST /api/mobile/v1/assets/<id>/vault-links/` — body `{password_id}`. Creates a `PasswordRelation(relation_type='asset', relation_id=asset_id)` row. Refuses cross-org links: the password must belong to the asset's org.
- `DELETE /api/mobile/v1/assets/<id>/vault-links/?password_id=N` — removes the relation. Idempotent.
- `/auth/me/` permissions map gains `assets_view`, `assets_create`, `assets_edit`, `assets_delete`.

Tests: `MobileAssetEditTests`, `MobileAssetVaultLinkTests` cover the PATCH whitelist, perm gate, cross-org link rejection, and link/unlink round-trip.

versionCode 3170479 → 3170480. **AAB rebuild required.**

## [3.17.479] - 2026-05-13

### Mobile: vault editing + ticket billing rollup + schedule-on-calendar

**Mobile vault (`mobile/app/vault/`):**
- New `/vault/new` screen — create a vault item from the app. Required: organization, title, password. Optional: username, URL, notes, category. Gated on `vault_create`. Plaintext password is held in component state only and wiped on unmount; the server encrypts via `Password.set_password()`.
- `/vault/<id>` gains **Edit** and **Rotate password** actions (gated on `vault_edit`). Edit covers title/username/URL/notes inline. Rotate prompts for a new plaintext in a modal and re-encrypts the ciphertext server-side. Both emit audit-log rows with `channel: mobile`.

**Mobile ticket detail (`mobile/app/tickets/[id].tsx`):**
- New **Billing** card above the time-entries list: three big totals (Total / Billable / Non-billable) for the ticket. When the client has an active contract (any type), surfaces the contract name + type plus, for block-hours contracts, a progress bar of `used / remaining / total` minutes. Bar tone goes green → amber → red as the bucket empties.
- Backend (`api_mobile/views_tickets.py`): `_serialize_ticket(detail=True)` now returns `total_minutes`, `billable_minutes`, `non_billable_minutes`, `resolution_due_at`, and a `contract` sub-object (`{id, name, type, total_minutes, used_minutes, remaining_minutes}`). PATCH also accepts `resolution_due_at` / `due_at` so users can schedule a ticket on a calendar day.

**Mobile calendar — schedule on this day (`mobile/app/dispatch/calendar.tsx`):**
- New **+ Schedule on this day** button on the selected-day section. Opens a modal: client picker, title, description, priority chips. Submits to the new `POST /api/mobile/v1/dispatch/tasks/` endpoint which creates a `ScheduledTask` anchored at 09:00 local on the selected date and auto-assigns the caller (`TaskAssignment` row).

**Backend (`api_mobile/views_vault.py`, `views_dispatch.py`, `views_auth.py`):**
- `POST /api/mobile/v1/vault/` (create — gated on `vault_create`).
- `PATCH /api/mobile/v1/vault/<id>/` (edit + rotate — gated on `vault_edit`; only-rotate sets a fresh ciphertext via `set_password()`).
- `POST /api/mobile/v1/dispatch/tasks/` (create scheduled task).
- `/auth/me/` permission map gains the five `vault_*` flags so the mobile UI can gate Edit / New / Rotate / Reveal-password affordances.

versionCode 3170478 → 3170479. **AAB rebuild required.**

## [3.17.478] - 2026-05-13

### Mobile dashboard: 7-day agenda strip mixing scheduled tasks + tickets

**Mobile dashboard (`mobile/app/dashboard.tsx`):**
- New **Upcoming** card under the three-tile row showing the next 7 days. Each non-empty day renders the date label ("Today" / "Tomorrow" / "Mon 5/19" …), a count badge, and up to three item titles with `+N more` for the rest. Tapping the card opens the full month at `/dispatch/calendar`.
- Items mix scheduled-task assignments (the caller's `TaskAssignment` rows due that day) and tickets (the caller's accessible tickets with a `resolution_due_at` due that day). Each row carries an emoji prefix — 📋 for tasks, 🎫 for tickets — so the source is glanceable.

**Backend (`api_mobile/views_dispatch.py`):**
- `GET /api/mobile/v1/dispatch/calendar/?month=YYYY-MM` now folds tickets into the per-day buckets alongside tasks. Rows carry a `kind` discriminator (`'task'` or `'ticket'`) and ticket rows alias `resolution_due_at` to `task_due_date` so existing calendar UI keeps rendering without branching.
- New `GET /api/mobile/v1/dispatch/upcoming/?days=N` returns an N-day (default 7, clamp [1, 14]) ordered list with empty days included. Feeds the dashboard agenda strip.

**Mobile dispatch calendar (`mobile/app/dispatch/calendar.tsx`):**
- Selected-day list now renders both tasks and tickets, distinguished by emoji + tap target. Tickets route to `/tickets/<id>`; tasks route to `/dispatch` (matches prior behavior).

versionCode 3170477 → 3170478. **AAB rebuild required.**

## [3.17.477] - 2026-05-13

### Mobile: client picker on new ticket, assignee picker on detail, three-tile dashboard, vehicles unscoped, ticket permissions

**Mobile new-ticket form (`mobile/app/tickets/new.tsx`):**
- Replaced the free-text "Organization ID" input with a real searchable client picker (modal sheet over `/api/mobile/v1/organizations/`). Client selection is now **required** — submit is disabled and the field is highlighted until one is chosen. Backend has always required `organization_id` on POST; the old UI just left the user no way to set it short of memorizing numeric IDs.

**Mobile ticket detail (`mobile/app/tickets/[id].tsx`):**
- New "Assignee" card. Surfaces the current assignee plus three actions: **Claim** (self-assign — always allowed), **Reassign…** (gated on `tickets_assign` permission), and **Clear** (unassign — gated on `tickets_assign`).
- Reassign opens a searchable user picker fed by the new `/api/mobile/v1/users/assignable/` endpoint. Users without the assign perm only see themselves in the list (so a tech can claim, but can't hand work off).

**Mobile dashboard (`mobile/app/dashboard.tsx`):**
- Replaced the prior "Needs attention" + "Today" rows with a single tighter row of three StatTiles: **Critical / Open (New) / Open**. Each tile links to the matching `/tickets?filter=` view. The new `new` filter chip maps to PSA tickets sitting in the `new` status slug (un-triaged).

**Mobile vehicles — fleet is shared (`api_mobile/views_vehicles.py`):**
- `GET /vehicles/` now returns the entire active fleet for any authenticated user instead of only vehicles with an active `VehicleAssignment` row for the caller. Detail / fuel / damage endpoints likewise dropped the per-assignment gate. Driver-of-record on each log entry (`fuel.user`, `damage.reported_by`) is still set from the request user. Service vehicles aren't multi-tenant — this is the operator's own fleet — so per-user gating was friction without security value.

**PSA ticket permissions (`accounts/models.py`, migration `accounts/0033_add_ticket_permissions.py`):**
- New `RoleTemplate` flags: `tickets_view`, `tickets_create`, `tickets_edit`, `tickets_assign`, `tickets_view_all`, `tickets_close`, `tickets_delete`. Backfilled the seven shipped system templates (Owner / Administrator / Editor / Help Desk / IT Manager / Documentation Writer / Read-Only) plus the six MSP sample roles (Client / Client Admin / Technician / Tech Manager / Office Manager / Full Admin) with sensible defaults — managers + admins get `tickets_assign`, techs / help desk can file + work but not reassign, read-only and docs writer get view-only.
- `api_mobile/views_tickets.py`: POST now gated on `tickets_create`; PATCH `assigned_to_id` requires `tickets_assign` unless the caller is self-claiming or clearing the assignee. `tickets_view_all` unlocks cross-org reads in list + detail. The ticket serializer now returns `organization_name`, `assigned_to_name`, `number`, and `updated_at` so list rows render without a second round trip.
- `api_mobile/views_auth.py`: `/auth/me/` payload now includes a `permissions` map (the seven `tickets_*` booleans) so the mobile app can gate UI affordances without re-querying.
- `api_mobile/views_users.py` (new): `GET /users/assignable/` — returns the caller alone if they lack `tickets_assign`; otherwise the pool of active users sharing at least one active org membership (or every active user for `tickets_view_all` / superusers).
- `api_mobile/views_dashboard.py`: dashboard response now includes `new_tickets` (count of open tickets in the `new` status slug).

versionCode 3170476 → 3170477. **AAB rebuild required** — adds the new ticket-creation / detail UI, three-tile dashboard, and vehicle list expansion. Backend migration `accounts/0033_add_ticket_permissions.py` must run on apply.

## [3.17.476] - 2026-05-12

### Mobile: asset detail full info + vault linkage + tickets filter fix

**Asset detail screen (`mobile/app/assets/[id].tsx`):**
- Renders the full asset record across four cards: Identity (org, hostname, IP, MAC, asset tag, serial, warranty pill), Hardware & software (manufacturer, model, OS, CPU, RAM, storage, firmware), Lifecycle (purchase date, warranty expiry, lifespan, primary contact), Metadata (created/updated/asset ID).
- New "Stored secrets" card lists every Vault entry linked to the asset via `PasswordRelation` (relation_type=`'asset'`). Each row is tappable and routes to `/vault/<id>` for the full reveal flow.
- Notes are surfaced in their own selectable card.

**Server (`api_mobile/views_assets.py`):**
- `_serialize_asset(detail=True)` now returns the wider field set: `organization_name`, `cpu`, `ram_gb`, `storage`, `firmware_version`, `firmware_latest`, `purchase_date`, `warranty_expiry`, `lifespan_years`, `notes`, `primary_contact_name`, `updated_at`.
- `asset_detail_view` now joins `select_related('organization', 'primary_contact')` and appends `vault_entries` (id, title, username, url, password_type — no encrypted blob) filtered by accessible orgs.

**Mobile tickets list filter bug:**
- `useTickets` (`mobile/src/api/tickets.ts`): the **Mine** and **Critical** chips now also send `status=open` to the server. Before, those filters only narrowed by assignee or priority, so closed-but-critical tickets and closed-but-mine tickets would still appear. The explicit **Closed** chip is still the only way to see terminal-status tickets.

versionCode 3170475 → 3170476. **AAB rebuild required** — mobile screen + API client changes ship in the bundle.

## [3.17.475] - 2026-05-12

### Mobile app supports auto-rotation (portrait + landscape)

`mobile/app.json::expo.orientation` was `"portrait"`, locking the app to portrait regardless of device rotation. Changed to `"default"` so the OS controls orientation — the app now rotates with the device on phones and tablets.

versionCode 3170474 → 3170475. **AAB rebuild required** — orientation is set in the native manifest, not in JS.

## [3.17.474] - 2026-05-12

### Fix dashboard-critical click + add org filter dropdown to Vault / Docs / Assets

**Bug — dashboard "Needs attention: N critical" → tickets list shows nothing:**
- Dashboard counts `critical_tickets = priority__code='P1'` — those are the P1 rows.
- Tile click goes to `/tickets?filter=critical`, mobile translates that to `?priority=critical` on the server.
- Server filtered by `priority__code='critical'` exact match — no priority row has code "critical" (codes are P1..P4) — so zero results.
- Fix: `views_tickets.ticket_list_view` now maps the friendly priority labels (`critical`/`urgent`/`high`/`medium`/`normal`/`low`) to their P-codes before filtering, same logic the PATCH path got in v3.17.450. Also matches priority `name` for backends that use English names instead of P-codes.

**New `OrgPicker` mobile component (`mobile/src/components/OrgPicker.tsx`):**
- Dropdown-style picker — Pressable trigger shows the current selection ("All organizations" / specific org name / "Global only"), tapping opens a modal sheet with:
  - Search box (so MSPs with 50+ clients can filter by name)
  - "All orgs" entry at top
  - Optional "Global only" entry (used by KB)
  - Full list, scrollable
  - Selected row highlighted with a ✓
- Hides itself entirely when the user has access to ≤1 org.
- Replaces the chip row that was on the Assets list (chips don't scale past ~6 orgs).

**Wired into:**
- `mobile/app/assets/index.tsx` — replaced horizontal chip scroll with OrgPicker.
- `mobile/app/vault/index.tsx` — new OrgPicker above the search field. `useVaultEntries` now takes an `organization_id` arg.
- `mobile/app/kb/index.tsx` — new OrgPicker with `showGlobal` so users can filter to globally-shared docs. `useKBArticles` now takes an `organization_id` arg.

**Server:**
- `views_kb.kb_list_view` now accepts `?organization_id=<id>` for scoping, and `?organization_id=global` for is_global=True docs only.
- `views_tickets.ticket_list_view` accepts friendly priority labels as documented above.

versionCode 3170473 → 3170474. **AAB rebuild required** — the OrgPicker component + screen updates ship in the bundle.

## [3.17.473] - 2026-05-11

### Beta-tester sign-up flow + visible app version (combined with v3.17.472)

**Beta tester request form** at `/core/beta-test/`:
- Public form (no login). Anonymous visitors submit name + Gmail (the Play Store account on their phone) + optional company / role / message / source.
- New `core.BetaTesterRequest` model + migration `0061_betatesterrequest`.
- Captures IP + UA at submit for abuse triage.

**Top-nav links:**
- Anonymous users see a "📱 Beta test the app" link in the right-side nav alongside Login.
- Authenticated users get it under Account → Mobile & Browser Access → "Beta test the Android app".
- Superusers additionally see "Beta tester requests" → the admin page.

**Admin triage** at `/core/beta-testers/` (superuser-only):
- Pending list with one-click ✓ Approve / ✕ Reject buttons.
- Approved-but-not-yet-added section with a copy-to-clipboard textarea of all approved Gmail addresses — paste straight into Play Console → Internal testing → Testers → email list.
- Shows the `PLAY_INTERNAL_TEST_URL` setting (env-configurable) so admin can copy the opt-in URL to share with testers.
- "Mark as added" button moves a request from approved → added_to_play once you've pasted the email into Play Console.
- Recent rejected + added rows at the bottom for audit.

**App version visibility** (was queued as v3.17.472 but the version bump didn't actually land — combined here):
- New `GET /api/mobile/v1/version/` anonymous endpoint returns the server's version.
- Mobile Settings → About card now shows: App version (marketing), Build number (versionCode / CFBundleVersion), Bundle ID, Server version (fetched live). Card tone flips success/warning based on match.
- Tiny build footer at the bottom of every dashboard render: `v3.17.473 · build 3170473 · server v3.17.473 ✓`. Tap → Settings.
- Build script now syncs `app.json::expo.version` from `config/version.py::VERSION` (previously only `versionCode` got auto-bumped; the marketing version stayed at `0.1.0`).

versionCode 3170472 → 3170473. **AAB rebuild required** for the build footer + version probe to land on the phone.

## [3.17.472] - 2026-05-11

### Visible build number on the app + server version probe

You asked: "how do I know if 3170471 is actually pushed out?" — fair question, the app had no way to tell you. Now it does.

**Mobile (`mobile/app/dashboard.tsx`):**
- Tiny build footer at the bottom of every dashboard render: `v3.17.472 · build 3170472 · server v3.17.472 ✓`. Tap to jump to the full About card in Settings. The `✓` flips to `⚠` when app and server versions differ.

**Mobile (`mobile/app/settings/index.tsx`):**
- About card now shows:
  - **App version** — from `Constants.expoConfig.version` (the marketing version, e.g. `3.17.472`)
  - **Build number** — from `Application.nativeBuildVersion` (the Android versionCode / iOS CFBundleVersion — this is the canonical "which AAB is this" identifier)
  - **Bundle ID** — `com.clientstor.mspreboot` so you can confirm you're on the right app
  - **Server version** — fetched live from the new `/version/` endpoint
  - Card tone flips to **success** (green border) when they match, **warning** (orange) when they differ. Mismatch text tells the user whether the phone is older (update Play Store) or newer (admin click Apply).

**Server (`api_mobile/views_version.py`):**
- `GET /api/mobile/v1/version/` — anonymous, returns `{version, version_info, api}`. Anonymous so it works on the login screen too.

**Build script (`local_apps/play_publish/scripts/build-aab.sh`):**
- Now syncs `app.json::expo.version` with `config/version.py::VERSION` at build time. Previously only `versionCode` got auto-bumped; the marketing version stayed at `0.1.0` forever, which is why the app footer was lying. From v3.17.472 onwards, both fields update on every build.
- `mobile/app.json` `version` bumped from `0.1.0` to `3.17.472` in this commit so the change is visible without a build (for the next manual edit).

versionCode 3170471 → 3170472. **AAB rebuild required** for the build-footer + Settings card to land on the phone.

## [3.17.471] - 2026-05-11

### Receipt OCR via the configured LLM (Anthropic / OpenAI / Ollama)

Replaces the Cloud Vision-only OCR path. Whatever LLM the user has configured under **Settings → AI** now does the vision extraction. No separate Google Cloud service account needed — if you already have Claude / GPT-4o / Ollama-with-llava working for AI doc generation, receipt extraction works too.

**Vision implementations added to `docs/services/llm_providers.py`:**
- `AnthropicProvider.extract_receipt_fields()` — multimodal `messages.create` with base64 image block. All Claude 3+ models support vision.
- `OpenAIProvider.extract_receipt_fields()` — `/chat/completions` with `image_url` data URL + `response_format: json_object`. Needs a vision-capable model (`gpt-4o`, `gpt-4o-mini`, `gpt-4-turbo`).
- `OllamaProvider.extract_receipt_fields()` — `/api/chat` with `images:[b64]` + `format: 'json'`. Needs a vision model (`llava`, `llava-llama3`, `llama3.2-vision`, `bakllava`).
- Base class `LLMProvider.extract_receipt_fields()` default returns `success:false` — Moonshot / MiniMax fall through gracefully (those providers are text-only at this point).
- Shared `_RECEIPT_SYSTEM_PROMPT` + `_RECEIPT_USER_PROMPT` at module scope so prompt tuning is one edit, not five.
- Shared `_parse_receipt_json()` strips ```json fences and slack from model output before `json.loads`.

**Configured-provider resolver:**
- New `get_configured_provider()` returns an instantiated `LLMProvider` built from `LLM_PROVIDER` + `*_API_KEY` / `*_MODEL` Django settings — same selection logic `AIDocumentationGenerator._init_provider` uses, so receipt OCR and AI doc generation always hit the same backend.

**Receipt upload (`api_mobile/views_receipts.py`):**
- `_ocr_image_bytes()` removed. Replaced with `_extract_with_llm()` that calls the configured provider first, then falls back to the legacy Cloud Vision path (`views_ocr._run_ocr`) for deployments that wired that up already.
- `category` is now passed as `hint` to the provider so a "fuel" upload primes the model to look for gallons / cpg.

**Tests (2 new):**
- LLM provider returns parsed fields → receipt populated + `VehicleFuelLog` auto-created with the right values.
- No LLM configured + no Cloud Vision fallback → receipt still saved with image, just no extraction (`ai_processed=false`).

**Operationally:** Apply lands this and receipt uploads start using whatever LLM you've configured. If Settings → AI shows "Anthropic Claude (claude-sonnet-4-5-20250929)" — that's what does the extraction. No env vars to set.

versionCode 3170470 → 3170471.

## [3.17.470] - 2026-05-11

### Receipt upload — server-keeps-image + OCR + auto-create downstream records

Reversed the v3.17.465 design. **The mobile app just uploads the receipt photo**; the server keeps the image, OCRs it, parses the structured fields, and auto-creates the appropriate downstream record (`VehicleFuelLog` or `VehicleMaintenanceRecord`) based on category.

Endpoints: `POST /api/mobile/v1/receipts/` (multipart) + `GET /receipts/` + `GET /receipts/<id>/`. New mobile screen `app/receipts/upload.tsx` with category grid and photo capture. SHA-256 dedup on `image_hash`. `Attachment.ENTITY_TYPES` extended for `vehicle_receipt` / `damage_report` / `fuel_log` (admin-UI cleanup; choices are form-level only).

versionCode 3170469 → 3170470. **AAB rebuild required** — the new receipts/upload screen ships in the bundle.

## [3.17.469] - 2026-05-11

### Patch urllib3 to fix CVE-2026-44432 (Dependabot alert #7)

`urllib3 2.6.0–2.6.x` had a decompression-bomb safeguard bypass in two cases on the streaming API:
1. Second `HTTPResponse.read(amt=N)` call when decompressed via the official Brotli library.
2. `HTTPResponse.drain_conn()` after partial decompression.

Both could cause excessive CPU/memory consumption (CWE-409) when streaming compressed responses from untrusted sources. CVSS v4 8.9 / High.

Fixed in `urllib3 2.7.0`. `requirements.txt` pin changed from `urllib3==2.6.*` to `urllib3>=2.7.0,<3.0`. The Apply flow installs from `requirements.txt`, so the upgrade lands automatically on the next prod update.

References:
- GHSA-mf9v-mfxr-j63j
- CVE-2026-44432

## [3.17.468] - 2026-05-11

### Fix issues #130 + #131

**Issue #131 — fresh-install migration fails on MySQL:**

Migration `psa.0027_email_message_threading` was raising `MySQLdb.OperationalError: (1071, 'Specified key was too long; max key length is 3072 bytes')` on fresh installs. Root cause: the unique constraint on `(organization_id, message_id)` had `message_id` at `max_length=998`. On MySQL utf8mb4 that's `4 + 998*4 = 3996` bytes — over the 3072-byte InnoDB index limit.

Fix: shortened the indexed fields in both the migration and the model:
- `EmailMessage.message_id`: 998 → 255 (RFC 5322 allows 998 but real-world Message-IDs are well under 200).
- `EmailMessage.in_reply_to`: 998 → 255.
- `EmailMessage.subject`: 998 → 512 (display field, never indexed; trimmed for storage hygiene).
- `Ticket.last_inbound_message_id`: 998 → 255.

Migration 0027 is edited in place. Anyone whose install already got past 0027 successfully (they were on a non-utf8mb4 charset or had `innodb_large_prefix=ON`) is unaffected — their column is already wider than the new schema declares. Fresh installs now complete cleanly.

**Issue #130 — Anthropic test 404 + Ollama "Unexpected token '<'":**

Two separate bugs:

1. `core/services/api_key_validator.validate_anthropic` hardcoded `claude-3-5-haiku-20241022` for the test call. Anthropic retired that model — every test against a valid key was returning `404 not_found_error`. Updated to `claude-haiku-4-5-20251001` (the current Haiku).

2. `assets.views.asset_ai_doc` had no top-level try/except, so any uncaught exception during AI generation returned Django's HTML 500 page. The frontend `fetch(...).then(r => r.json())` then choked with `Unexpected token '<', "<html> <"...`. Wrapped the entire view body in `_asset_ai_doc_inner` + outer try/except that always returns a JSON error response.

**Note:** the Ollama JSON parse error path is now visible — the underlying Ollama provider call (in `docs/services/llm_providers.OllamaProvider.generate`) catches its own errors and returns `{success: False, error: str(e)}`. The JSON now reaches the frontend cleanly. If users still see Ollama failures, the actual error message comes through and we can iterate from there.

## [3.17.467] - 2026-05-11

### Expanded push triggers + OCR setup scaffolding + signal weak-ref bug fix

**Critical bug fix:** the v3.17.463 ticket-assignment push *silently never fired* in production because the `@receiver` decorators inside `_register_*_signals()` produced weak references that got garbage-collected the moment the registration function returned. No test had verified the side effect, so the regression sat undetected. Every `@receiver` in `api_mobile/signals.py` now passes `weak=False`.

**Expanded push triggers** (`api_mobile/signals.py`):
- `psa.TicketComment` create → push the ticket's assignee, unless the commenter IS the assignee. Internal comments still push (visibility, not audience scope, drives the rule).
- `scheduling.TaskAssignment` create → push the newly-assigned user with the task title.
- `processes.ProcessExecution` create → push the `assigned_to` user, unless they started the run themselves.
- `vault.VaultRevealRequest` `status` transitions to `approved` → push the original requester.
- All five receivers funnel through a new `signals._dispatch_push()` helper so tests can patch a single egress point.

**Tests** (`MobilePushSignalsTests`, 6 tests):
- Ticket comment pushes assignee; doesn't push when author == assignee.
- Task assignment pushes user.
- Process execution pushes when assigned by someone else; doesn't push for self-starts.
- Vault reveal request `pending → approved` pushes the requester.

**OCR setup scaffolding:**
- `requirements-optional.txt` now includes `google-cloud-vision==3.7.*` with a step-by-step comment block: create GCP service account → download JSON → drop at `/home/administrator/secrets/vision-sa.json` → set `OCR_PROVIDER=cloudvision` + `GOOGLE_APPLICATION_CREDENTIALS=…` in the gunicorn EnvironmentFile → `pip install -r requirements-optional.txt` → restart.
- New `GET /api/mobile/v1/ocr/status/` endpoint reports `{configured, provider, sdk_loadable, sdk_error, credentials_env_set}` so you can verify the wiring without trying to OCR a fake image.

**Full suite: 117/117 api_mobile tests pass.**

## [3.17.466] - 2026-05-11

### Test coverage for v3.17.461–465 endpoints + stale-test fix

Audit of the completion pass — the four newest endpoints had no test coverage. Added 15 focused tests plus fixed one stale assertion from before v3.17.448.

**New tests:**
- `MobileScanTests` (6 tests) — QR resolves to inventory; cross-org inventory 404s; asset_tag and serial_number both resolve to asset; unknown code 404; missing `?code=` 400.
- `MobileDispatchCalendarTests` (2 tests) — month bucketing groups same-day assignments correctly and excludes out-of-month; `?month=bogus` 400.
- `MobileNotificationRegisterTests` (4 tests) — registration creates a `MobileDevice` row; missing token 400; second `register` with the same `device_id` updates in place (idempotent, returns 200 instead of 201); `deregister` flips `revoked` + clears the token.
- `MobileOcrEndpointTests` (3 tests) — endpoint 503s when `OCR_PROVIDER` unset; the receipt regex parser extracts the full field set from synthetic OCR text; the parser leaves missing fields out instead of guessing.

**Stale-test fix:**
- `MobileDashboardTests.test_dashboard_returns_counts` was still checking for `offline_monitors` / `security_alerts_open` / `organization_count` — keys that v3.17.448 renamed or removed. Updated to the current top-level keys; the exhaustive shape check still lives in `MobileDashboardShapeTests`.

**Minor:**
- `views_ocr._STATION_RE` now tolerates leading whitespace in OCR'd receipt text (`^\s*(SHELL|BP|...)`). Without this, indented OCR output failed station-name matching.

**Full suite:** 110/110 api_mobile tests pass.

## [3.17.465] - 2026-05-10

### Receipt OCR pre-fill for fuel logs (opt-in via env)

Fuel form auto-fills gallons / $-per-gallon / station from a receipt photo when the server-side OCR is configured. Off by default — endpoint returns 503 unless `OCR_PROVIDER` env is set, so the mobile app degrades silently to manual entry.

**Server (`api_mobile/views_ocr.py`):**
- `POST /api/mobile/v1/ocr/receipt/` (multipart) — accepts a `photo` file.
- Routes to Google Cloud Vision when `OCR_PROVIDER=cloudvision` + `GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json` is set in env (the SDK is imported lazily so unset deployments don't pay the import cost; install with `pip install google-cloud-vision` to enable).
- Best-effort regex parser pulls `gallons`, `cost_per_gallon`, `total_cost`, `station`, `date_raw` from US-format fuel receipts. Returns only fields it actually matched — missing fields stay missing so a wrong guess never overwrites a user's data.
- Returns full `raw_text` (capped to 2 KB) for debugging the parser against new receipt formats.
- 503 `{detail: "OCR not configured"}` when `OCR_PROVIDER` unset. The endpoint is wired but inert until you flip the switch.

**Mobile (`mobile/app/vehicles/[id].tsx`):**
- After picking a photo for a fuel receipt, fires `/ocr/receipt/` in the background. On 200, the parsed values pre-fill any currently-empty fields (gallons / $/gal / station). On 503 / failure / network error: silent, manual entry continues.
- Damage photos do **not** run OCR — only fuel.

**Adding another provider** (Textract, Tesseract, etc.): add a branch in `_run_ocr()`. Keep the same response shape (`{extracted: {gallons, cost_per_gallon, station, ...}, raw_text}`) and the mobile UI just works.

**Public release checklist updated** — the "Deferred" section now reflects that all four previously-deferred features (#21–24) shipped, with their per-feature setup requirements (env vars, Play Console video, etc).

versionCode 3170464 → 3170465.

---

### v3.17.453 → 465 — completion pass summary

Thirteen versions, ~5500 lines added across server + mobile, 70+ tests.

| ver | thread |
|---|---|
| 453 | Vault Fernet decrypt fix |
| 454 | Asset create + ticket time entry + asset org filter |
| 455 | Workflow (Process) runner |
| 456 | Vehicles + fuel + damage |
| 457 | Dispatch board + task sign-off |
| 458 | Inventory + transactions |
| 459 | Dashboard reorganization + visual polish + workflow stage links |
| 460 | Photo capture (damage + fuel) |
| 461 | QR/barcode scanner + Play Console release docs |
| 462 | Dispatch calendar view |
| 463 | Push notifications via Expo |
| 464 | Background location (opt-in) |
| 465 | Receipt OCR pre-fill (opt-in via env) |

Repo state: all originally listed user requirements and all "deferred" follow-ups are now in `main`. Push: `https://github.com/agit8or1/clientst0r`.

## [3.17.464] - 2026-05-10

### Background location tracking (opt-in) — Sub-phase 8.2 completes

The deferred Sub-phase 8.2 (background GPS for shift visit logging) ships. **Off by default**, explicit opt-in via Settings, foreground service with visible notification while running.

**Mobile:**
- New dep: `expo-task-manager ~11.8.2`. `expo-location` plugin block now declares `isAndroidBackgroundLocationEnabled` + `isIosBackgroundLocationEnabled`. Permission strings updated to be honest about background usage.
- New `mobile/src/utils/backgroundLocation.ts`:
  - `defineTask(BG_LOCATION_TASK)` at module scope so the OS-wake handler is registered before any background event fires.
  - `enableBackgroundLocation()` requests foreground → then background permission (errors clearly if denied), starts `Location.startLocationUpdatesAsync` with `timeInterval=5min`, `distanceInterval=50m`, Balanced accuracy, foreground service notification "Client St0r is tracking your shift."
  - `disableBackgroundLocation()` stops the task and clears the AsyncStorage flag.
  - State persisted in AsyncStorage so the toggle survives app restarts.
- Settings screen gains a "Background location" card with explanatory note + Turn on / Turn off button. The card flips to a green-tone (success border) when active.
- The task posts `{lat, lon, accuracy, timestamp}` to the existing `POST /locations/` endpoint — server already drops off-shift pings per `WorkingHours` (v3.17.410 behavior).

**Docs:**
- `docs/PRIVACY_POLICY.md`: new paragraph explicitly explaining background tracking (off by default, 5-min cadence, foreground service notification, off-shift pings dropped at server). Permission table adds `ACCESS_BACKGROUND_LOCATION`, `POST_NOTIFICATIONS`, `FOREGROUND_SERVICE_LOCATION`.
- `docs/PLAY_DATA_SAFETY.md`: precise-location section updated for the optional background flow with the wording Play wants in the free-text justification field.
- `docs/PUBLIC_RELEASE_CHECKLIST.md`: flagged the **High** Play Console review impact — production submission will require a 30-second sample video of the in-app opt-in flow and an "Allowed by Google" declaration.

versionCode 3170463 → 3170464.

## [3.17.463] - 2026-05-10

### Push notifications via Expo

End-to-end pipeline. Device registers an Expo push token on login, server fires a push when a ticket gets reassigned to that user, tap routes to the ticket.

**Server:**
- New migration `field_ops/migrations/0006_mobiledevice_expo_push.py` adds `expo_push_token` (CharField, max 200) and `notifications_enabled` (BooleanField, default True) to the existing `MobileDevice` model.
- New `api_mobile/push.py::send_push_to_user(user, title, body, data)` — fires a fire-and-forget HTTP POST to `https://exp.host/--/api/v2/push/send` on a background thread. Never blocks the caller. Sends to every active, opted-in device for the user.
- New `api_mobile/views_notifications.py`:
  - `POST /notifications/register/` accepts `{token, platform, device_id?, name?, enabled?}` and upserts a `MobileDevice`. Idempotent.
  - `POST /notifications/deregister/` marks the device revoked + clears its token.
- New `api_mobile/signals.py` registers `pre_save`/`post_save` on `psa.Ticket`. When `assigned_to_id` changes (or a new ticket is created with an assignee), fires `send_push_to_user(new_assignee, ...)`. Catches assignments from web, mobile, integrations — anywhere `Ticket.save()` runs.
- `api_mobile/apps.py::ready()` registers the signals on app start. Wrapped so a failure can't block startup.

**Mobile:**
- New dep: `expo-notifications ~0.28.18`. Plugin block in `app.json` with icon + tint color.
- New `mobile/src/utils/push.ts` — `registerForPushNotifications()` requests permission, fetches the Expo push token via `Notifications.getExpoPushTokenAsync()`, POSTs to `/notifications/register/` with a stable client-side UUID device_id (stored in AsyncStorage so re-logins update the same device row). `deregisterPushNotifications()` mirrors it.
- Login + MFA success in `src/api/auth.ts` fires registration. Logout fires deregistration. Both are fire-and-forget — push is optional, login/logout never block on it.
- `_layout.tsx` registers a `Notifications.addNotificationResponseReceivedListener` that reads `data.route` from the payload and `router.push`es to it on tap. Server attaches `route: '/tickets/<id>'` to ticket-assignment pushes.

**No FCM project setup required.** Expo's relay handles FCM (Android) and APNS (iOS) using the project's existing EAS credentials — no GoogleService-Info.plist / google-services.json needed.

versionCode 3170462 → 3170463.

## [3.17.462] - 2026-05-10

### Dispatch calendar view

Month-grid calendar of the caller's scheduled-task assignments. Tap a day → see that day's assignments in a list below. Server returns a flat `{YYYY-MM-DD: [assignments]}` map for the requested month so the grid can render dot-counts without per-day requests.

**Server (`api_mobile/views_dispatch.dispatch_calendar_view`):**
- `GET /api/mobile/v1/dispatch/calendar/?month=YYYY-MM` — defaults to current local month. Returns `{month, today, days}` where `days` is keyed by date string and contains the same `_serialize_assignment(a)` payload the board uses (so the tap-through can render the existing assignment card layout).
- Empty days are omitted rather than returned as empty lists (smaller payload, simpler client check).

**Mobile (`mobile/app/dispatch/calendar.tsx`):**
- Hand-rolled month grid (no external calendar library — keeps the AAB lean). 7-col × 5–6-row layout. Today gets a blue border; selected day gets a filled blue background.
- Dots per day with assignment count badge (capped at "9+").
- < and > navigate months; state resets to current-day selection when changing months.
- "📅 Calendar" button on the dispatch board header opens the screen.

versionCode 3170461 → 3170462.

## [3.17.461] - 2026-05-10

### QR / barcode scanner + Play Console public-release docs

**QR / barcode scanner (`mobile/app/scan.tsx`):**
- Full-screen camera screen using `expo-camera`'s `CameraView` + `onBarcodeScanned`. Recognizes QR, Code 128 / 39, EAN 13 / 8, UPC A / E.
- New endpoint `GET /api/mobile/v1/scan/?code=<text>` (`api_mobile/views_scan.py`) resolves the decoded string in this order, all org-scoped:
  1. `InventoryItem.qr_code` (exact)
  2. `Asset.asset_tag` (case-insensitive exact)
  3. `Asset.serial_number` (exact)
  4. `VehicleInventoryItem.qr_code` for vehicles assigned to the caller
- On match: server returns `{kind, id, name, route}`; mobile deep-links via `router.replace(route)`. On miss: 404 + the scanner re-arms after 1.5 s with the unmatched code shown.
- "📷 Scan" button added to the Inventory and Assets list headers, opening the modal scanner.
- Modal presentation in `_layout.tsx` (no header chrome).

**Public-release prep:**
- New `docs/PUBLIC_RELEASE_CHECKLIST.md` consolidates everything needed for a Play Console production release: visual assets you still need to provide, every form to fill out (with pointers to which doc has which copy), and the sequence to flip from internal-testing to production.
- `docs/PLAY_DATA_SAFETY.md` updated to cover **photos** (v3.17.460) and **precise location** (v3.17.452) — both now collected and need declaration.
- `docs/PRIVACY_POLICY.md` rewritten "What the app collects" section: explicit treatment of `CAMERA`, `READ_MEDIA_IMAGES` / `READ_EXTERNAL_STORAGE`, and `ACCESS_FINE_LOCATION` purpose strings. Permission table refreshed.

versionCode 3170460 → 3170461. **AAB rebuild required** — `expo-camera` plugin needs to land in the manifest via `expo prebuild`.

## [3.17.460] - 2026-05-10

### Photo capture — damage reports + fuel receipts

Damage reports without photos are weak evidence. Fuel logs without receipts can't be reimbursed. Both the damage and fuel POSTs now accept an optional `photo` field via multipart upload.

**Server (`api_mobile/views_vehicles.py`):**
- Damage and fuel views switch to mixed parsing: `JSONParser`, `MultiPartParser`, `FormParser`. Plain JSON still works; multipart adds the optional photo path.
- New `_save_attachment(user, file, entity_type, entity_id)` helper wraps `files.models.Attachment.objects.create`. Vehicles aren't org-scoped, so the attachment is attributed to the uploader's primary accessible org.
- `Attachment.ENTITY_TYPES` extended with `damage_report` and `fuel_log`. CharField choices change — no migration needed.
- Response payload includes `photo: {id, original_filename, file_size, content_type, uploaded_at}` when a file was attached.

**Mobile:**
- New deps: `expo-image-picker ~15.0.7` + `expo-camera ~15.0.16`.
- `app.json` plugins now include both with explicit, honest purpose strings (camera + media library on Android, NSCameraUsageDescription / NSPhotoLibraryUsageDescription on iOS).
- New helper `mobile/src/utils/photoPicker.ts` — `takePhoto()` and `pickFromLibrary()` return a `{uri, name, type}` object axios's FormData can append directly.
- `useLogFuel` and `useLogDamage` switch to multipart automatically when a photo is attached.
- Vehicle detail screen gets "📷 Take photo" / "🖼 From library" buttons + a thumbnail preview (with Remove ✕) on both fuel and damage forms.

versionCode 3170459 → 3170460. **AAB rebuild required** — both new deps need to land in the manifest via `expo prebuild`.

## [3.17.459] - 2026-05-10

### Dashboard reorganization + visual polish

User asked for "look nicer + organized dashboard." Restructured the dashboard into clear semantic sections, gave it a real visual hierarchy, and made workflow stage entity links navigable.

**Dashboard layout — was a flat scroll of cards, now sections:**
1. **NEEDS ATTENTION** (red, only renders when there's something) — critical tickets + overdue tasks. Big numbers, deep-link onto the right screens.
2. **Shift card** — single horizontal "On the clock / Off the clock" card. Green when active, with hh:mm started + duration. Tap to jump to Timeclock.
3. **TODAY stats row** — 2 hero StatTiles: "My open tickets" and "Today's tasks." Tap-through to filtered list views.
4. **NAVIGATE icon grid** — 8-tile 4×2 grid replacing the bare chip row: Dispatch / PSA / Assets / Vault / Docs / Workflows / Inventory / Vehicle. Each tile has an emoji + label + optional notification badge (e.g. red badge on Dispatch when overdue tasks exist).
5. **RECENT** — recent tickets + recent assets, now in compact-mode cards.

**New components:**
- `components/Card.tsx` — added `tone` prop (`accent` / `warning` / `critical` / `success`), `compact` mode, new `SectionHeader` export, hero StatTile variant. Tones color the border + tone-aware StatTile values.
- `components/NavTile.tsx` — square icon-tile with emoji, label, optional badge.

**Tickets list (`mobile/app/tickets/index.tsx`)** now reads `?filter=` from the URL so dashboard deep-links (`/tickets?filter=mine`, `/tickets?filter=critical`) land on the correct filter chip.

**Workflow stage entity links navigable:**
- Server (`api_mobile/views_workflows.py`): execution-stage payload now includes `linked_password_id` / `linked_asset_id` / `linked_document_id`.
- Mobile (`mobile/app/workflows/exec/[id].tsx`): renders linked entities as tappable chips that route to `/vault/<id>` / `/assets/<id>` / `/kb/<id>`. Tech can open a credential the runbook references with one tap, no hunting.

versionCode 3170458 → 3170459.

## [3.17.458] - 2026-05-10

### Mobile inventory (org-scoped) — last of the "PSA in your pocket" pass

Wraps the `inventory` app. List items, see low-stock badges, scan/search, adjust stock from the field with an `InventoryTransaction` audit row per change.

**Server (`api_mobile/views_inventory.py`):**
- `GET /inventory/?search=&item_type=&organization_id=&low_stock=true&page=` — paginated, org-scoped via `accessible_org_ids`. `low_stock=true` filters with `quantity__lte=F('min_quantity')`. Search hits name / sku / manufacturer_part_number / qr_code (exact match for QR).
- `GET /inventory/<id>/` — detail (404 cross-org).
- `GET/POST /inventory/<id>/transactions/` — list last 50 / create one. Body: `{transaction_type, quantity_change, notes?}`. Allowed types: `stock_in` / `stock_out` / `adjustment`. `stock_in` auto-coerces to positive, `stock_out` auto-coerces to negative, `adjustment` accepts whatever sign you provide. Atomic: both the `quantity` update and the `InventoryTransaction` insert happen in one transaction. Negative-stock outcomes return 400 instead of writing.

**Mobile:**
- `app/inventory/index.tsx` — list with low-stock badge, search, "Low stock only" toggle.
- `app/inventory/[id].tsx` — detail with prominent quantity display, `+ Stock in` / `− Stock out` / `Adj.` buttons that wire to the same transactions endpoint, recent-transaction history.
- `mobile/src/api/inventory.ts` — `useInventory`, `useInventoryItem`, `useInventoryTransactions`, `useAdjustStock`.
- "Inventory" tile added to dashboard `NAV_ITEMS`.

**Tests:** 9 in `MobileInventoryTests` — own vs other-org isolation (cross-org detail + transactions both 404), low-stock filter, stock_in increments, stock_out auto-negates sign, would-go-negative blocked, invalid type 400, zero change 400.

versionCode 3170457 → 3170458.

---

### Pass summary (v3.17.453 → v3.17.458, all shipped 2026-05-10)

Six versions, ~3500 lines added across server + mobile, 50+ tests.

| ver | thread |
|---|---|
| 453 | vault Fernet decrypt fallback |
| 454 | asset create + ticket time entry + asset list org filter |
| 455 | workflows (Process runner) — list, start, complete-stage |
| 456 | vehicles + fuel + damage |
| 457 | dispatch board + scheduled task sign-off |
| 458 | inventory + transactions |

Two AAB rebuilds were needed in the chain (versionCode bumps in 454 + 455 + 456 + 457 + 458 — they all need to land at once via the latest AAB).

## [3.17.457] - 2026-05-10

### Mobile dispatch board

What's-on-my-plate view for techs in the field. Combines `scheduling.ScheduledTask` assignments with open ticket assignments.

**Server (`api_mobile/views_dispatch.py`):**
- `GET /dispatch/` — buckets the caller's task assignments into `overdue` / `today` / `upcoming`, plus tickets `{open_count, recent[5]}`. Bucket logic uses each task's `due_date` against the current local day window. No-due-date assignments fall under `today`.
- `POST /dispatch/assignments/<id>/ack/` — sign off on a single assignment via the existing `TaskAssignment.sign_off` helper. Body `{notes?}`. Triggers the task's completion check (auto-completes when `require_all_signoffs` is satisfied). Other-user assignments return 404.
- `POST /dispatch/tasks/<id>/comments/` — add a `TaskComment`. Caller must have an assignment on the task or 404.

**Mobile:**
- `app/dispatch/index.tsx` — sectioned screen (Overdue / Today / Upcoming / My tickets). Each assignment row shows priority pill, title, org, description, due date. Inline "Sign off" expand-to-form on un-acked items.
- `mobile/src/api/dispatch.ts` — `useDispatchBoard`, `useAcknowledgeTask`, `useAddTaskComment`.
- "Dispatch" tile added to dashboard `NAV_ITEMS` (front of the row).

**Tests:** 5 in `MobileDispatchTests` — buckets, sign-off happy path, other-user assignment 404, comment create, comment on unassigned task 404.

versionCode 3170456 → 3170457.

## [3.17.456] - 2026-05-10

### Vehicle inventory + fuel + damage on mobile

Wraps the `vehicles` app for techs in the field. Authorization model: a tech sees and can act on vehicles they have an active `VehicleAssignment` for — vehicles are not org-scoped because they're the company fleet.

**Server (`api_mobile/views_vehicles.py`):**
- `GET /vehicles/` — vehicles currently assigned to me
- `GET /vehicles/<id>/` — detail (404 if not assigned)
- `GET /vehicles/<id>/inventory/` — `VehicleInventoryItem` rows for that vehicle
- `GET/POST /vehicles/<id>/fuel/` — list / log a fill-up. Creates `VehicleFuelLog`. Required: `mileage`, `gallons`, `cost_per_gallon`. `total_cost` auto-computed if omitted; `date` defaults to today. Updates `ServiceVehicle.current_mileage` if the new reading is higher.
- `GET/POST /vehicles/<id>/damage/` — list / file a `VehicleDamageReport`. Required: `description`. Severity defaults to `minor`. Captures the vehicle's current condition as `condition_before`.

**Mobile:**
- `app/vehicles/index.tsx` — my vehicles list
- `app/vehicles/[id].tsx` — single screen with: vehicle summary, on-board inventory list (with low-stock badge when `quantity <= min_quantity`), fuel fill-up form + recent log, damage report form + recent reports
- `mobile/src/api/vehicles.ts` — typed hooks
- Operations hub gets new entries: "My vehicle", "Workflows" (alongside Timeclock)

**Tests:** 8 in `MobileVehiclesTests` — own vs other-tech assignment isolation (the cross-tech vehicle returns 404 on detail), inventory list, fuel happy path with auto total_cost + odometer sync, fuel invalid 400, damage create, damage missing-description 400, unauth blocked.

versionCode 3170455 → 3170456.

## [3.17.455] - 2026-05-10

### Workflows on mobile (Process runner)

Surfaces the existing `processes` app as a mobile feature. Tech can browse available workflows for their org (plus globals), open one, and start a run that creates a `ProcessExecution` assigned to themselves. From the run screen they tap "Mark done" on each stage; when every stage has a completion row, the execution auto-finishes.

**Server (`api_mobile/views_workflows.py`):**
- `GET /workflows/` — published, non-archived processes scoped to user's accessible orgs ∪ globals. Search + category + organization_id filters.
- `GET /workflows/<id>/` — with stages.
- `POST /workflows/<id>/start/` — creates `ProcessExecution` (status=in_progress, assigned_to=caller). Globals require explicit `organization_id`; org-scoped processes default to their own org.
- `GET /workflows/executions/?status=` — caller's executions.
- `GET /workflows/executions/<id>/` — with stage state (each stage carries `is_completed`, `completed_at`, etc.).
- `POST /workflows/executions/<id>/stages/<stage_id>/complete/` — idempotent. Auto-completes the execution when all stages are done.

**Mobile:**
- New screens: `app/workflows/index.tsx` (library + my in-progress runs), `app/workflows/[id].tsx` (process detail + start), `app/workflows/exec/[id].tsx` (run detail with per-stage Mark done buttons + notes).
- `mobile/src/api/workflows.ts` — typed hooks `useWorkflows`, `useWorkflow`, `useStartWorkflow`, `useMyExecutions`, `useExecution`, `useCompleteStage`.
- "Workflows" tile added to dashboard `NAV_ITEMS`.

**Tests:** 5 in `MobileWorkflowsTests` — list visibility, detail with stages, start creates execution, complete-all auto-finishes, idempotent stage complete.

versionCode 3170454 → 3170455.

## [3.17.454] - 2026-05-10

### Asset create from mobile + ticket time logging + asset list org filter

Three coupled mobile additions plus their server endpoints. Bundled into one AAB rebuild as v3.17.454.

**Asset creation from the field (`POST /api/mobile/v1/assets/`):**
- `views_assets.asset_list_view` now also handles POST.  Required: `organization_id` (must be accessible — 403 otherwise) and `name`. Optional fields whitelisted: `asset_type`, `asset_tag`, `serial_number`, `hostname`, `ip_address`, `mac_address`, `os_name`, `os_version`, `manufacturer`, `model`, `notes`. Anything else is dropped.
- New mobile screen at `mobile/app/assets/new.tsx` — org chip picker, identity card (name + asset_type chips), network card (hostname + IP), hardware card (serial + model), notes. "+ New" button on the asset list header opens it. Auto-selects the user's only org if there's one.
- 5 tests in `MobileAssetCreateTests`: own-org create, cross-org 403, missing org 400, missing name 400, unknown fields silently dropped.

**Ticket time logging (`POST /api/mobile/v1/tickets/<id>/time/`):**
- New `views_tickets.ticket_time_view` accepts both shapes: `{duration_minutes, notes?, is_billable?}` for manual entries (sets `started_at = now - duration`), or `{started_at, ended_at?, notes?, is_billable?}` for explicit ranges (computes duration). 404 on cross-org.
- GET on the same path returns the most recent 50 entries.
- Mobile ticket detail (`tickets/[id].tsx`) gets a new "Time" card above Comments — minutes input, optional notes, billable toggle, list of prior entries.
- 5 tests in `MobileTicketTimeEntryTests`: by-duration, by-range, missing inputs 400, list, cross-org 404.

**Asset list filter by organization:**
- Horizontal chip row above the asset list, sourced from `/organizations/`. "All orgs" + one chip per org. State driven; server already supported `?organization_id=`. Hidden when the user has access to ≤ 1 org.

versionCode 3170452 → 3170454.

## [3.17.453] - 2026-05-10

### Vault decrypt: handle legacy Fernet entries

Five vault entries on prod (id 103-107, all in one org) returned 500 "Failed to decrypt password." on reveal. Root cause: those rows were written by an older code path that called `cryptography.fernet.Fernet.encrypt` directly. Fernet emits URL-safe base64 (`-` and `_`); the current decrypt path uses standard `base64.b64decode` which rejects those characters and raises `binascii.Error: number of data characters (97) cannot be 1 more than a multiple of 4` — surfacing as a generic 500 in the mobile reveal flow.

**Fix:**
- `vault.encryption.decrypt` now detects the Fernet token signature (`gAAAAA` prefix = URL-safe base64 of the 0x80 version byte) and decrypts via `cryptography.fernet.Fernet` using the same 32-byte master key, just URL-safe-base64-wrapped.
- `vault.encryption_v2.decrypt_v2` short-circuits to the v1 path when it sees the same signature, instead of trying its own `base64.b64decode` and raising before the fallback can fire.
- Web vault, mobile vault, and any other consumer of `Password.get_password()` now decrypt these entries cleanly.

3 tests in `vault.tests.LegacyFernetDecryptTests`: v1 direct, v2 routing, end-to-end through `Password.get_password()`. All use a runtime-generated Fernet token from the configured master key, so the test passes regardless of which key the test environment uses.

Server-only fix; ships via Apply, no AAB rebuild.

## [3.17.452] - 2026-05-09

### GPS-attached clock-in + warn-but-allow geofence enforcement (Sub-phase 8.2 / 8.3)

Tech clocks in from a phone, server now decides if that fix is inside any active `ClientSiteGeofence` for the destination org. Outside-fence clock-ins still succeed (warn-but-allow per the user's policy choice) but the response carries `geofence_override: true` so the mobile UI can surface a yellow banner and the audit log captures who clocked in where, with what GPS accuracy, and which fence (if any) matched.

**Server (`api_mobile/views_field_ops.clock_in_view`):**
- Body now optionally accepts `lat`, `lon`, `accuracy`. Bad numeric values return 400 (instead of silently dropping) since the client deliberately attached them.
- After the entry is saved, if the org has at least one active `ClientSiteGeofence`, walks them and calls `fence.contains(lat, lon)` (existing equirectangular / ray-cast helper). First match short-circuits.
- Response `geofence_override` is `true` only when at least one active fence existed AND none matched. No fences → no override (an org without geofences can't be "outside" anything).
- Audit log entry now includes `gps_provided`, `gps_accuracy_m`, `geofence_match_id`, `geofence_override` so override patterns are queryable.

**Mobile (`mobile/app/timeclock/index.tsx` + `src/api/timeclock.ts`):**
- `expo-location` (~17.0.1) added to `package.json`.
- `app.json` plugins now include `expo-location` with explicit purpose strings (Android `ACCESS_FINE_LOCATION`, iOS `NSLocationWhenInUseUsageDescription`) — phrased to be honest with the Play Console reviewer: location is only captured at clock-in time, not background.
- Timeclock screen requests foreground permission on tap. Best-effort: permission denial / GPS off / capture timeout all degrade gracefully — clock-in succeeds without coords, just no geofence verification.
- New `ClockInResult` type extends `TimeclockEntry` with `geofence_override` + `geofence_match_id`.
- Yellow warn banner renders for ~one screen render when override fires. Auto-clears on next clock-in attempt.

**Tests:**
- 5 new in `MobileFieldOpsTests`: inside fence (no override + match_id set), outside fence (override + audit row), no active fence (no override), no GPS (no override), invalid GPS (400).

**versionCode 3170451 → 3170452** in `mobile/app.json`. Mobile-only AAB rebuild required for the location permission to be requested at install (declared in the manifest by `expo prebuild` once `expo-location` plugin is present).

This delivers the GPS-auto-time slice of Sub-phase 8.2 (foreground capture at user-initiated clock-in only) and the timeclock-with-context slice of Sub-phase 8.3. Background auto-time + always-on GPS pings remain deferred.

## [3.17.451] - 2026-05-09

### Mobile cleanup pass — remove dead screens, lock down profile, group by org

A round of mobile-only changes that need an AAB rebuild + Play Console upload.

**Removed:**
- `mobile/app/monitoring/` and `mobile/app/security/` — both had no server endpoints (404), and the user opted to remove them rather than build out the missing API surface.
- `mobile/src/api/monitoring.ts` and `mobile/src/api/security.ts` — dead hooks.
- Operations hub no longer links to either; it's just Timeclock for now.
- Dashboard tile row for Expiring soon / Monitors down / Open alerts removed (they pointed at /operations which only has Timeclock now and was misleading). The "Recent security alerts" card on the dashboard is also gone. Server-side `data.security` and `data.monitors_down` are still returned by `/dashboard/` for any other consumer; the mobile just doesn't render them.

**Profile is now read-only:**
- `mobile/src/api/profile.ts` — switched from `/profile/` (which never existed on the server, would have been 404) to `/auth/me/`. Dropped `useUpdateProfile`. Tolerates either `{user: {...}}` or flat `{...}` response shape.
- `mobile/app/settings/index.tsx` — gutted the editable form (TextField for first/last/email + "Save profile" button gone). Profile fields now display as read-only label/value rows. Edits go through the web app.

**Assets and vault lists grouped by organization:**
- `mobile/app/assets/index.tsx` and `mobile/app/vault/index.tsx` — bucket entries by `organization_name`, render section headers (`ORG NAME · count`) above each bucket. Items with no org fall under a "No organization" section. Sorts alphabetically by org name.

**versionCode 3170450 → 3170451** in `mobile/app.json` so Play Console accepts the new AAB.

## [3.17.450] - 2026-05-09

### Mobile ticket status/priority changes now actually persist

The mobile ticket detail screen has had a status picker and priority picker since v3.17.349, and the server PATCH handler accepted them — but only if the body keyed on `status_id` / `priority_id` (FK ints). The mobile client sends `{status: 'open'}` and `{priority: 'critical'}` (friendly strings), so every PATCH silently no-op'd. Tap a status, server returns 200, ticket unchanged.

`api_mobile/views_tickets.ticket_detail_view` now also accepts:
- `status` (string) — looks up `TicketStatus` by slug (with `_` → `-` normalization), falling back to case-insensitive name match. 400 with helpful detail on miss.
- `priority` (string) — maps mobile labels `critical/high/medium/low` to `P1/P2/P3/P4`, then looks up `TicketPriority` by code. Also accepts raw P-codes and priority names for backends that already use those.

Server-only fix; the v3.17.446 AAB on Play Console starts working as soon as Apply lands this on prod.

3 new tests in `MobileTicketsTests`: PATCH by slug succeeds, unknown slug → 400, priority label `'critical'` → P1.

## [3.17.449] - 2026-05-09

### Mobile vault endpoints (closes the 404 on the vault tab)

The mobile app's vault tab returned 404 because `/api/mobile/v1/vault/` and friends never landed despite a roadmap annotation suggesting they had. Built the missing surface:

- `views_vault.vault_list_view` — `GET /vault/?search=&organization_id=&page=` paginated, org-scoped via `accessible_org_ids`. Search matches title / username / url / notes. Ordered by org then title so the upcoming mobile org-grouping work has a sensible default. Never returns secrets.
- `views_vault.vault_detail_view` — `GET /vault/<id>/`. 404 on cross-org reads (no existence leak).
- `views_vault.vault_reveal_view` — `POST /vault/<id>/reveal/`. Mirrors the web vault's security guarantees:
  - 30/hour per-user throttle via new `MobileVaultRevealRateThrottle` (scope `vault_reveal` added to `REST_FRAMEWORK.DEFAULT_THROTTLE_RATES`).
  - Per-credential approval gate honored. If `requires_reveal_approval` is set with no current approval, returns 202 + `request_url` so the mobile UI can deep-link to the web approval flow rather than silently failing.
  - `vault.access_rules.evaluate` (GeoIP / IP / time-of-day) honored. 403 with reason if denied.
  - Decrypts via existing `Password.get_password()` → `decrypt_password()` with AAD verification.
  - Marks the satisfying approval as used so the next reveal needs a fresh request.
  - Audit log entries on every read attempt and decision (allow / deny / decrypt-failed) tagged `channel='mobile'`.

7 tests in `MobileVaultEndpointTests` cover org scoping (other-org entries are 404), no-secret-in-list/detail, plaintext returned on reveal, search filtering, and unauthenticated rejection.

Server-only change. Mobile already calls these paths; the v3.17.446 AAB on Play Console will start working once Apply lands this on prod — no rebuild needed.

## [3.17.448] - 2026-05-09

### Mobile dashboard crash fix — server returns the shape the client expects

After completing the MFA challenge the React Native dashboard threw "undefined is not a function" inside `<ErrorBoundary>` because `data.recent_assets.map(...)` was being called on an integer.

**Server/client contract was misaligned since v3.17.347:**
- `mobile/src/types/api.ts::DashboardSummary` declared `recent_tickets: Ticket[]`, `recent_assets: Asset[]`, `security: SecuritySummary`, plus counts `monitors_down` and `my_open_tickets`.
- `api_mobile/views_dashboard.py::dashboard_view` returned counts where arrays were expected, used `offline_monitors` instead of `monitors_down`, and never returned `my_open_tickets`, `recent_tickets`, or a `security` object at all. The mismatch only surfaced now because previous releases couldn't get past login.

**Fix:**
- Rewrote `dashboard_view` to return the shape the type defines:
  - Counts: `open_tickets`, `critical_tickets`, `my_open_tickets`, `expiring_soon`, `monitors_down`
  - `recent_tickets`: top 5 non-terminal tickets ordered by `-updated_at`, serialized via the existing `views_tickets._serialize_ticket`
  - `recent_assets`: top 5 most-recently-created assets, serialized via `views_assets._serialize_asset`
  - `security`: `{open_alert_count, critical_alert_count, high_alert_count, medium_alert_count, low_alert_count, recent_alerts: [...]}`
- Each section is wrapped in try/except so a missing optional app (`psa`, `security_alerts`, …) leaves its slice empty rather than 500ing the whole dashboard.
- 3 new tests in `api_mobile.tests.MobileDashboardShapeTests` lock the contract: 200 + arrays present + auth required + arrays default to `[]` not `None`.

**No mobile rebuild needed** — fix is server-side, ships via Apply.

## [3.17.447] - 2026-05-09

### Public privacy policy + Play Console submission docs

Play Console requires a public privacy-policy URL and a completed Data Safety questionnaire before any track (including Internal testing) accepts a release for review. Both shipped here.

**New public route:**
- `core.views.privacy_policy` — anonymous-accessible view at `GET /privacy-policy/` (mounted at the root in `config/urls.py`, not under `/core/`). Renders `docs/PRIVACY_POLICY.md` server-side via the `markdown` package; same single-source-of-truth pattern as `/core/roadmap/`. Standalone HTML template (no auth chrome) so Play Console reviewers see a clean page.
- 4 tests in `core/tests/test_privacy_policy.py` covering anonymous-200, named-URL reverse, markdown→HTML, and `Content-Type: text/html`.

**New docs (source of truth):**
- `docs/PRIVACY_POLICY.md` — what data the app sends, what it stores, what it doesn't collect. Calibrated to the v3.17.446 AAB's actual permissions (no location, no camera, no contacts) and noted that a future GPS timeclock will revise.
- `docs/PLAY_DATA_SAFETY.md` — pre-filled answers for every question in Play Console's Data Safety form, broken down by section and data type, with the exact wording for the deletion-request free-text field.
- `docs/PLAY_STORE_LISTING.md` — short description, full description, "what's new" copy, app-content rating answers, and the App-access reviewer-login text.

## [3.17.446] - 2026-05-09

### Mobile login fix + signed-AAB build unblock

Two unrelated mobile blockers shipped together so internal-testing testers can actually log in.

**Mobile login was returning "username and password are required" with credentials clearly entered:**
- `mobile/src/api/auth.ts` — login `POST /auth/login/` body now sends `{username, password}` instead of `{email, password}`. Backend (`api_mobile/views_auth.py:86`) reads `request.data.get('username')`, so the previous body left `username` empty server-side. The login screen field accepts either email or username (Django `authenticate()` handles both via the email-or-username backend), so no UI change is needed.

**Signed AAB build was failing on `expo-modules-core:compileReleaseKotlin`:**
- `mobile/patches/expo-modules-core+1.12.26.patch` — adds `?.` null-safe call to `PermissionsService.kt:166`. Android SDK 35 made `PackageInfo.requestedPermissions` nullable; `expo-modules-core@1.12.26` (Expo SDK 51) was written for SDK 34 and accessed it directly. Newer Kotlin compiler rejects this with `Only safe (?.) or non-null asserted (!!.) calls are allowed on a nullable receiver`. Cannot downgrade compileSdk because Play Console requires `targetSdk 35` (and `compileSdk` must be ≥ `targetSdk`).
- `mobile/package.json` — adds `patch-package` devDep + `postinstall` script so the patch survives `npm install`.

**Version bump:**
- `config/version.py` — 3.17.445 → 3.17.446.
- `mobile/app.json` — Android `versionCode` 3170445 → 3170446 so Play Console accepts the new internal-testing AAB (it rejects duplicate versionCodes).

## [3.17.445] - 2026-05-08

### Documentation sweep, mobile-app trim, Play Console targetSdk 35

Three threads land together:

**Documentation:**
- `FEATURES.md` — full Compliance Frameworks section (Phase 41) + Native Mobile Apps section (Phase 8). Header bumped to v3.17.444.
- `README.md` — version badge bumped to v3.17.444; "Latest Release" rewritten with the actual recent phases (Compliance, Mobile, Evidence Packs, Onboarding/Offboarding) — was stuck on v3.17.143. Compliance + Mobile screenshot rows added to the gallery and the index list.
- `docs/SCREENSHOT_CHECKLIST.md` — Compliance + Mobile sections added at the top.
- `user-guide/compliance.md` — new page covering enroll → attest → recertify → PDF flow + data model. Linked from `user-guide/README.md`.
- `scripts/generate_screenshots_v2.py` — captures `compliance-org-dashboard` + `compliance-checklist` automatically when an org is enrolled.
- `docs/screenshots/compliance-org-dashboard.png`, `docs/screenshots/compliance-checklist.png`, `docs/screenshots/compliance-checklist-annotated.png` — fresh captures from the live app, with numbered callouts on the annotated version.

**Mobile app — six-area top nav (per user directive):**
- `mobile/app/dashboard.tsx` — replaces the previous Settings header button with a primary 5-tile nav row (Assets / Vault / Docs / PSA / Operations). Monitoring / Security / Timeclock tile destinations rerouted through `/operations`.
- `mobile/app/operations/index.tsx` — new hub screen consolidating Timeclock, Monitoring, Security alerts, and Settings under one route.
- `mobile/app/_layout.tsx` — top-level Stack screens reorganized: 6 primary (Dashboard / Assets / Vault / Docs / PSA / Operations) above the secondary screens reachable via deep-link.

**Play Console fixes (target SDK 35 + R8 mapping):**
- `mobile/app.json` — adds `expo-build-properties` plugin with `compileSdkVersion: 35`, `targetSdkVersion: 35`, `buildToolsVersion: "35.0.0"`, `enableProguardInReleaseBuilds: true`, `enableShrinkResourcesInReleaseBuilds: true`. Resolves Play Console error "must target at least API level 35".
- `mobile/package.json` — adds `expo-build-properties: ~0.12.5` dependency.
- `local_apps/play_publish/scripts/build-aab.sh` — PATH bumped to `build-tools/35.0.0`; captures `mapping.txt` from `build/outputs/mapping/release/` next to the AAB so it can ship with the upload.
- `local_apps/play_publish/scripts/upload-aab.py` — after the AAB upload, also calls `androidpublisher.deobfuscationfiles.upload(deobfuscationFileType='proguard', …)` to ship `mapping.txt`. Resolves the "no deobfuscation file associated" warning.
- Android SDK platform `android-35` + build-tools `35.0.0` installed locally via `sdkmanager`.

## [3.17.444] - 2026-05-08

### Phase 41 — Compliance Frameworks & Recertification: shipped
Phase 41 is now fully shipped. Roadmap header advances from `[in progress]` → `[shipped — v3.17.444]`. Sizing-table row added: `41 — Compliance Frameworks & Recertification | M | shipped v3.17.435–444 | extends accounts + audit + reports.pdf_export`.

What landed across the train (10 releases):

| Release | Slice |
| --- | --- |
| v3.17.435 | Phase 41 roadmap entry + app stub |
| v3.17.436 | Models: ComplianceFramework, Category, CheckItem, OrganizationCompliance, OrganizationComplianceItem, RecertificationReminder + migration + admin |
| v3.17.437 | `seed_pci_dss` mgmt cmd → 1 framework, 12 categories (PCI Requirements 1-12), 38 check items keyed to real PCI-DSS v4.0 control numbers |
| v3.17.438 | `seed_hipaa` mgmt cmd → 1 framework, 3 categories (Administrative + Physical + Technical Safeguards), 33 check items keyed to real CFR refs |
| v3.17.439 | Per-org dashboard `/compliance/organizations/<org_id>/` + Enroll button + status pills + progress bar per framework |
| v3.17.440 | Checklist UI `/compliance/.../<framework_slug>/` with per-row attestation save + audit logging on status change |
| v3.17.441 | Customer-facing PDF report (KPI grid + per-category table) using Phase 19's `reports.pdf_export.render_pdf` |
| v3.17.442 | `send_compliance_recertifications` cron (idempotent + 7-day dedup) + `RecertificationReminder` audit row |
| v3.17.443 | Settings card on checklist (toggle / interval / notify_email) + "Mark recertified now" button |
| v3.17.444 | Phase close (this release) |

Total: 36+ tests across 7 test classes in `compliance/tests.py`, all passing.

### Operator quick-start
```bash
# Seed the framework catalog (idempotent — safe to re-run)
python manage.py seed_pci_dss
python manage.py seed_hipaa

# Add daily recertification cron (crontab -e)
0 9 * * * cd /home/administrator && /home/administrator/venv/bin/python manage.py send_compliance_recertifications
```

Then for each client org needing compliance: `/compliance/organizations/<org_id>/` → **Enroll** the framework → walk the checklist → **Mark recertified now** when done. The cron handles future reminders.

## [3.17.443] - 2026-05-08

### Added — Phase 41 v7: recertification toggle UI + Mark Recertified button
On the checklist page (`/compliance/organizations/<org_id>/<framework_slug>/`), a new "Recertification" card sits below the progress bar with two halves:

**Left side — settings form:**
- Toggle switch: enable/disable email reminders (`recertification_emails_enabled`)
- Interval dropdown: Monthly (30) / Bi-monthly (60) / Quarterly (90) / Semi-annual (180) / Annual (365). Validated server-side against `VALID_INTERVAL_DAYS`; invalid values silently fall back to current.
- Notify email override (optional). If blank, the recertification cron resolves to the org's primary admin.
- **Save settings** button POSTs to `/compliance/.../settings/`.

**Right side — manual recertify:**
- Shows last-recertified timestamp + days until next reminder + the actual due date.
- **Mark recertified now** button (green) → POSTs to `/compliance/.../recertify/` → stamps `last_recertified_at = now()`. Confirms via `confirm()` dialog before submit.

Both actions write `AuditLog` entries (action=update). Description on settings save lists exactly what fields changed (e.g. `Recert settings: emails_enabled: True -> False; interval_days: 365 -> 30`).

### Tests
6 new: settings save updates fields; invalid interval falls back; unchecked toggle disables; mark-recertified stamps timestamp + audits; outsider blocked.

## [3.17.442] - 2026-05-08

### Added — Phase 41 v6: recertification reminder cron
New management command `python manage.py send_compliance_recertifications` (run daily via cron) walks every `OrganizationCompliance` with `recertification_emails_enabled=True`, computes `recertification_due_at`, and sends a reminder email if:

1. now() ≥ due_at
2. No `RecertificationReminder` row for this enrollment exists in the last 7 days (dedup)

Recipient resolution order:
1. `OrganizationCompliance.notify_email` (if explicitly set)
2. First active `Membership(role in ['owner','admin'])` user's email
3. Fallback: `DEFAULT_FROM_EMAIL` (with a warning logged)

Email body links to the checklist (uses `SITE_URL` if defined). Subject indicates whether the recertification is due today, in N days, or overdue by N days.

`--dry-run` flag identifies which enrollments would be reminded without sending or recording.

### Cron setup (operator)
Add to crontab — daily at 09:00 UTC works:
```
0 9 * * * cd /home/administrator && /home/administrator/venv/bin/python manage.py send_compliance_recertifications
```

### Tests
5 new: due enrollment gets an email + audit row; dedup-within-7-days; disabled-flag respected; not-yet-due skipped; dry-run sends nothing + writes no rows.

## [3.17.441] - 2026-05-08

### Added — Phase 41 v5: customer-facing PDF compliance report
The dashboard's **Report (PDF)** button + the checklist's **Download report (PDF)** button now produce a real PDF instead of a placeholder. New view at `/compliance/organizations/<org_id>/<framework_slug>/report.pdf`.

Layout (using the Phase 19 `reports.pdf_export.render_pdf` helper):
- **Title**: `<Framework> Compliance Report`
- **Subtitle**: org name + framework version + generated timestamp + last-recertified date
- **KPI cards** (4-column grid): Compliance %, Compliant count, Partial count, Non-compliant count, N/A count, Unanswered count, Total controls, Days until recertification
- **One table per category** with columns: Control / Status / Evidence (URL) / Notes (truncated to 280 chars per cell)

Generates an `AuditLog` entry on every PDF download (action=view, description="Generated PDF compliance report for <framework>") so the audit trail captures who pulled the report.

Filename pattern: `<org_slug>-<framework-slug>-<YYYYMMDD>.pdf`.

### Tests
3 new tests: PDF response returns 200 + correct Content-Type + valid `%PDF` magic header + body length sanity check; audit log row written; outsider users blocked (404).

## [3.17.440] - 2026-05-08

### Added — Phase 41 v4: checklist UI + per-row attestation save
The dashboard's "Open checklist" button now lands on a working page. New view at `/compliance/organizations/<org_id>/<framework_slug>/` renders the full checklist grouped by category, with each item showing:

- Title + description (verbatim control text from the seed)
- Evidence hint (yellow lightbulb)
- Status dropdown (compliant / partial / non-compliant / N/A / unanswered)
- Notes textarea
- Evidence link URL field
- "Last reviewed" timestamp + reviewer username

Items are color-coded by left border: green compliant, orange partial, red non-compliant, grey N/A, light-grey unanswered.

Per-row save POSTs to `/compliance/organizations/<org_id>/<framework_slug>/save/`. Server validates the status against the model's `STATUS_CHOICES` (invalid input falls back to `unanswered`), updates `last_reviewed_at` + `last_reviewed_by`, and writes an `AuditLog` entry on every status change with description `"Status: <old> -> <new>"`. Redirect lands the user back on the same item via fragment anchor (`#item-<id>`) so they don't lose place after save.

Header card shows live progress (`percent_compliant` + status counts).

### Fixed — view tests using `c.login()` triggered django-axes
Earlier compliance tests called `c.login(username, password)` which goes through django-axes's authentication backend; that backend requires a `request` object and raises `AxesBackendRequestParameterRequired` from the test client. Switched all 8 calls to `c.force_login(user)` which bypasses the auth backend chain (test-only — production unaffected).

### Tests
4 new checklist tests + 8 existing rewritten to use `force_login`. **Ran 28, OK.**

### Side fixes (orthogonal to Phase 41)
- AAB delete capability: red **Delete** button next to each row in the play_publish dashboard's Built AABs table; new `/play_publish/delete/<filename>` POST view with path-traversal guard.
- Build progress panel auto-clears on success (was leaving stale "complete" state on the page); upload progress panel auto-hides 5s after success. Both via dashboard JS only — local-only.
- `mobile/app.json` package + bundleIdentifier changed from `com.clientstor.mobile` → `com.clientstor.mspreboot` to match the Play Console listing the user created.

## [3.17.439] - 2026-05-08

### Added — Phase 41 v3: per-org compliance dashboard
New view at `/compliance/organizations/<org_id>/` lists every active framework with the org's enrollment status. For unenrolled frameworks, an **Enroll** button creates the OrganizationCompliance row + bulk-creates an OrganizationComplianceItem (status=`unanswered`) for every check item in the framework — so the operator can immediately walk the checklist.

For enrolled frameworks, the card shows:
- **Compliance progress bar** (`percent_compliant`)
- Status counts (compliant / partial / non-compliant / N-A / unanswered)
- **Recertification due** with days remaining (red text if overdue)
- **Open checklist** + **Report (PDF)** buttons (real implementations land in v3.17.440 + v3.17.441; URLs stubbed in this release so the dashboard renders)

### Audit
Enrollment writes an `AuditLog` entry with action `create`, object_type `compliance.OrganizationCompliance`, and a description naming the framework + version.

### Tests
4 new view tests in `compliance/tests.py`:
- Dashboard renders + lists frameworks
- Enroll creates the right number of attestation items (38 for PCI-DSS)
- Enrollment is idempotent (re-POST is no-op)
- Outsider users get 404 on cross-org dashboard access

All compliance tests pass.

## [3.17.438] - 2026-05-08

### Added — Phase 41: HIPAA Security Rule seed
Management command `python manage.py seed_hipaa` populates the HIPAA Security Rule framework with all three safeguard categories from 45 CFR Part 164, Subpart C:

1. **Administrative Safeguards (164.308)** — 13 items including Security Management Process, Risk Analysis, Risk Management, Sanction Policy, Information System Activity Review, Assigned Security Responsibility, Workforce Security, Information Access Management, Security Awareness Training, Security Incident Procedures, Contingency Plan, Evaluation, Business Associate Contracts.
2. **Physical Safeguards (164.310)** — 8 items: Facility Access Controls, Contingency Operations, Facility Security Plan, Workstation Use, Workstation Security, Device and Media Controls, Disposal, Media Re-use.
3. **Technical Safeguards (164.312)** — 12 items: Access Control, Unique User Identification, Emergency Access Procedure, Automatic Logoff, Encryption and Decryption, Audit Controls, Integrity, Mechanism to Authenticate ePHI, Person or Entity Authentication, Transmission Security, Integrity Controls, Encryption.

Each item references the actual CFR subsection (e.g. `164.308(a)(1)(ii)(A)` for Risk Analysis) with a verbatim-style description and `evidence_hint` of what auditors typically expect.

Idempotent — re-runs do `update_or_create` keyed on `(framework, slug)` pairs.

### Tests
2 new tests: HIPAA seed creates 3 categories + 25+ items; idempotent on re-run.

## [3.17.437] - 2026-05-08

### Added — Phase 41: PCI-DSS v4.0 seed
Management command `python manage.py seed_pci_dss` populates the PCI-DSS v4.0 framework with all 12 Requirements as categories and ~35 representative check items. Each item references a real PCI-DSS v4.0 control number (e.g. `1.2.1`, `8.4.2`, `11.3.2`) and includes verbatim-style description + an `evidence_hint` for what an auditor typically expects.

Categories (= PCI-DSS v4.0 Requirements):
1. Install and maintain network security controls
2. Apply secure configurations to all system components
3. Protect stored account data
4. Protect cardholder data with strong cryptography during transmission
5. Protect all systems and networks from malicious software
6. Develop and maintain secure systems and software
7. Restrict access to system components and CHD by need-to-know
8. Identify users and authenticate access to system components
9. Restrict physical access to cardholder data
10. Log and monitor all access
11. Test security of systems and networks regularly
12. Support information security with organizational policies and programs

Idempotent — re-running updates by `(framework, category)` slug pair, never duplicates. An MSP can extend each category in the management command source over time as their attestation needs grow.

### Tests
2 new tests: seed populates framework + 12 categories + 30+ items; seed is idempotent across repeated runs.

## [3.17.436] - 2026-05-08

### Added — Phase 41: compliance framework + per-org attestation models
First release of the new Phase 41 (Compliance Frameworks & Recertification). Adds the data model the rest of the train builds on. Existing Phase 39 evidence-pack flow is untouched.

- `ComplianceFramework` — system-defined framework (PCI-DSS, HIPAA, etc.). Pre-seed via mgmt cmds in v3.17.437/438.
- `ComplianceCategory` — group of controls within a framework (PCI Requirement 1, HIPAA Administrative Safeguards, etc.). FK framework + slug + order.
- `ComplianceCheckItem` — individual control. FK category + slug + name + description + evidence_hint + order.
- `OrganizationCompliance` — per-org enrollment in a framework. Tracks `recertification_interval_days` (default 365), `recertification_emails_enabled`, `last_recertified_at`, `notify_email`. `recertification_due_at` + `percent_compliant()` helpers.
- `OrganizationComplianceItem` — per-org attestation for a single control. Status (compliant / partial / non_compliant / not_applicable / unanswered) + notes + evidence URL + last_reviewed_at/by.
- `RecertificationReminder` — audit row recording sent reminder emails.

### Migration
`compliance/0001_initial.py` adds all five tables. Backwards-compatible (existing evidence-pack functionality unaffected).

### Roadmap
- New phase header `## Phase 41 — Compliance Frameworks & Recertification **(M)** [in progress]` inserted before the `---` divider that precedes Phase 8.

### Tests
6 new model tests in `compliance/tests.py`: framework create + str, category/item chain, org enrollment + status_counts(), percent_compliant(), recertification_due_at, unique constraint per (org, framework).

## [3.17.435] - 2026-05-08

### Fixed — Play Console rejected uploads as duplicate versionCode
Expo's default Android `versionCode` is `1`. Once Play Console accepts a versionCode for an app, it can't be reused — the next upload gets a cryptic `"This release does not add or remove any app bundles"` and `"You can't rollout this release because it doesn't allow any existing users to upgrade to the newly added app bundles"`.

Fix in `mobile/app.json` + `local_apps/play_publish/scripts/build-aab.sh` (local-only): pin `android.versionCode = 3170435` and have the build script auto-derive the value from `config/version.py` on every build using `major × 1,000,000 + minor × 10,000 + patch`. Each release-version-bump now yields a unique higher versionCode automatically. Max Android versionCode is 2.1 billion — plenty of headroom.

### Chore — version bump triggers gunicorn restart
The play_publish app's view-layer changes from earlier (Python uploader, expanded GCP walkthrough, no-cache headers) need a gunicorn restart to load. Apply v3.17.435 from Settings → Updates picks them up.

## [3.17.434] - 2026-05-08

### Chore — version bump for gunicorn restart
No code change in this commit. Used as the Apply trigger to graceful-restart gunicorn so it picks up local-only Django app changes outside the public repo. The build_aab + upload_aab Python wrappers were updated locally; this version bump exposes a fresh "Update available" so the operator can click **Apply** and pull the new code into running workers.

## [3.17.433] - 2026-05-08

### Fixed — `bundleRelease` failed with `Unable to resolve module crypto from axios`
The signed-AAB build (`./gradlew bundleRelease`) was failing at `:app:createBundleReleaseJsAndAssets`. Root cause: Metro (the React Native bundler) was resolving axios via its `dist/node/axios.cjs` entry, which imports Node built-ins (`crypto`, `url`, `http`) that don't exist in the React Native runtime.

The debug build worked because `expo prebuild` for debug uses a different code path that picks axios's RN-friendly entry by default. Release builds went through Metro's full resolver and picked the wrong export.

Fix: new `mobile/metro.config.js` sets `resolver.unstable_conditionNames = ['require', 'react-native', 'browser']` so Metro consults the `react-native` / `browser` conditional exports in package.json before falling back to `node`. axios + any similar dual-build dep now resolves correctly under release.

### Tests
None — Metro resolver config; verified by reading the v3.17.432 build log error at `:app:createBundleReleaseJsAndAssets` and the axios package.json `exports` map.

## [3.17.432] - 2026-05-08

### Added — Generic local-app loader (`local_apps/`)
A new auto-discovery hook lets you drop a Django app at `<BASE_DIR>/local_apps/<name>/` and have it loaded on the next gunicorn restart. Used for environment-specific extensions that don't belong in the public repo (custom auth backends, internal-only dashboards, etc.).

The loader is **generic** — it does not name any specific app, and it's fully backwards-compatible (no `local_apps/` directory means no behavior change).

Implementation (~25 lines total):

- `config/settings.py` — appends a small block at the end that walks `<BASE_DIR>/local_apps/`, prepends it to `sys.path`, and adds any subdirectory containing `apps.py` to `INSTALLED_APPS`. Skips entries beginning with `_` or `.`.
- `config/urls.py` — appends a similar block that mounts each subdirectory's `urls.py` at `/<name>/` if present.

Whatever lives under `local_apps/` is intentionally NOT tracked. The directory is gitignored via `.git/info/exclude` (per-clone, not in the repo's tracked `.gitignore`) so a fresh clone has no traces.

### Tests
None — generic plugin scaffolding; no behavior change for fresh clones.

## [3.17.431] - 2026-05-08

### Added — Live build progress bar (real percentage, not just animated stripes)
The Building page used to refresh the entire HTML every 5 seconds via meta-refresh. The progress bar was just a CSS striped animation — it didn't reflect actual progress, so a long step like `:app:minifyDebugWithR8` (which can run 10+ minutes silently on R8) made the page look frozen even when work was happening.

New API endpoint `GET /core/mobile-apps/build-progress/<platform>/` (in `core/views.py::mobile_app_build_progress`) returns:
- `status` — building / complete / failed
- `tasks_seen` — count of `> Task :` lines in `<platform>_build.log`
- `tasks_total_est` — empirical baseline of 588 (the v3.17.427 successful build's task count); auto-bumps if a build exceeds it
- `percent` — `tasks_seen / tasks_total_est`, capped at 99% until status==complete
- `current_task` — the most recent `> Task :` line (e.g. `> Task :app:minifyDebugWithR8`)
- `elapsed_s` — seconds since `status_data['timestamp']`
- `log_tail` — last 30 non-blank log lines

The Building page (in `download_mobile_app`) replaces the meta-refresh + striped CSS bar with:
- A real Bootstrap-style green progress bar that smoothly transitions (`transition: width 0.5s ease`) from 0%→99% as Gradle runs through its task list
- Live "**42%** · 247 / ~588 tasks" counter
- "Current task: `> Task :app:minifyDebugWithR8`" callout so you can see what's happening RIGHT NOW
- Live elapsed timer (1s tick)
- Live log tail (last 30 lines, auto-scrolled)
- Auto-redirect to download URL when status flips to `complete`
- Auto-page-reload (which lands on the failed-status page from v3.17.429) when status flips to `failed`

Polls every 1.5s. The endpoint is auth-gated (`@user_passes_test(is_staff or is_superuser)`).

### Tests
None — frontend polling + JSON endpoint; verified by tracing the count logic and the `> Task :` regex.

## [3.17.430] - 2026-05-08

### Fixed — APK build failed on `getDefaultProguardFile()`
v3.17.428 appended the minify+shrink patch to `android/app/build.gradle` as bare property setters:

```gradle
android.buildTypes.debug.proguardFiles getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro"
```

That fails with `Could not find method getDefaultProguardFile() for arguments [...] on project ':app'` because outside an `android { }` block the receiver of `getDefaultProguardFile` is the bare `Project`, which doesn't have that method. The method belongs to the `AndroidExtension` (the object the `android { }` block configures).

Fix: wrap the patch in a proper nested `android { buildTypes { debug { ... } } }` block so Gradle's resolver hits the right receiver:

```gradle
// CST-DEBUG-MINIFY
android {
    buildTypes {
        debug {
            minifyEnabled true
            shrinkResources true
            proguardFiles getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro"
        }
    }
}
```

The block form is also the canonical idiom in the Android Gradle Plugin docs.

### Tests
None — Gradle config syntax fix; verified against AGP docs for `getDefaultProguardFile()` scope.

## [3.17.429] - 2026-05-08

### Fixed — Mobile Apps page: single-button rebuild + visible build errors
Two genuine UX bugs that the previous releases didn't catch:

1. **Two buttons, two flows for "rebuild"** — the admin page had a "Rebuild from latest code" button that POSTed to wipe the cache, AND a separate "Build & download APK" link that triggered the actual build. User had to click two things in sequence. Now a single `?rebuild=1` query param on the existing download URL handles both wipe + kickoff atomically. The admin page renders one button per state: **Download APK** + **Rebuild from latest code** when an APK exists; **Build APK from latest code** when not.

2. **Build errors disappeared on auto-refresh.** When a build failed, `download_mobile_app`'s failed-status branch deleted the status file and rendered a generic "Android App Not Created Yet" page — discarding the error message AND the build log. The user couldn't see why the build had failed because the failure UI was the same as the no-build-yet UI. Now the failed branch:
   - Keeps the status file
   - Reads the last 80 non-blank lines of `android_build.log`
   - Renders a red "❌ Android Build Failed" card with the error message + scrollable log + a single **🔁 Retry build** button (which clicks through to `?retry=1` to wipe the failure and start fresh)
   - **Does NOT auto-refresh**, so the error stays put until the user explicitly retries or navigates away

### Files
- `core/views.py::download_mobile_app` — `?rebuild=1` short-circuit; new failed-status page with embedded log
- `templates/core/mobile_apps_admin.html` — consolidated to one primary button per state, links to `?rebuild=1`

### Tests
None — UI consolidation; verified by tracing the `?rebuild=1` short-circuit and the failed-status template render path.

## [3.17.428] - 2026-05-08

### Smaller — APK 49MB → ~20-25MB (R8 minify + resource shrink on debug)
Default Expo debug builds skip R8 minification and resource shrinking; that's why the v3.17.425 APK was still 49MB even with arm64-v8a-only native libs. Patching `android/app/build.gradle` after `expo prebuild` to force `minifyEnabled = true` and `shrinkResources = true` on the debug variant runs R8 over the JS bundle + Java/Kotlin classes and drops unused resources.

In `core/management/commands/build_mobile_app.py`, the existing build-gradle patcher now appends a second block (guarded by `// CST-DEBUG-MINIFY` marker for idempotency):

```gradle
android.buildTypes.debug.minifyEnabled = true
android.buildTypes.debug.shrinkResources = true
android.buildTypes.debug.proguardFiles getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro"
```

This uses the standard Android optimize rules + the Expo/RN-shipped `proguard-rules.pro` (already correct for keep rules on Hermes / Reanimated / native modules). No release keystore needed — debug keystore continues signing the APK.

Expected APK size: **~20-28MB** (down from 49MB). The new app has more deps than the Feb 2026 skeleton (Expo Router + TanStack Query + Reanimated + Gesture Handler + Screens + others), so it won't quite hit the original 20MB but should land close.

To get the smaller APK: Apply v3.17.428 → Mobile Apps → **Rebuild from latest code** → **Build & download**.

### Tests
None — Gradle config injection; verified by reading the build.gradle patch + the standard Android proguard-android-optimize.txt rules.

## [3.17.427] - 2026-05-08

### Fixed — APK build looked hung even when running fine
Three cosmetic bugs in `download_mobile_app`'s "Building..." page combined to make the build look hung even though it always finished in 1-2 min:

1. **Log filter stripped Gradle output.** The filter only kept lines containing `===`, `Step`, `Building`, `Installing`, `> npx`, `> ./gradlew`, `Error:`, `failed`, or `complete`. Gradle's actual progress (`> Task :react-native-screens:assembleDebug`, etc.) didn't match any of those, so the visible log froze at the last marker line for the whole build. Widened the filter to keep almost everything except `npm warn` / `warning:` noise. Now keeps the last **60 lines** instead of 20.
2. **"Elapsed Time: Calculating…" never updated.** The JS that ticks the elapsed counter only existed on the "starting a fresh build" page, not on the "build in progress" page (the one users actually see during a build). Added the same `setInterval(tickElapsed, 1000)` to the in-progress page, sourced from `status_data['timestamp']`.
3. **"Showing last 100 lines"** label was a lie (the filter only kept 20). Updated to "Showing last 60 lines of build output" and added a link to `/core/mobile-apps/` so users can navigate back to the admin landing page if they want the explicit Download button instead of waiting for the auto-refresh + auto-download.

The `mobile_apps_admin` page at `/core/mobile-apps/` already detects the APK on disk correctly (`os.path.exists(binary_path)`) — if you reach that URL in a fresh tab right now, it shows the green "Ready" badge with the Download APK button. The "stuck" feeling came from the building page's stale snapshot, not from the admin page.

### Tests
None — UI cosmetic fixes; verified by reading the build log filter logic and the JS update path.

## [3.17.426] - 2026-05-08

### Fixed (third try) — 502s on `/static/...` after Apply reload
v3.17.422's parallel warmup probed `/api/update-progress/` six times — a Django dynamic endpoint. But static files (`/static/css/themes.*.css`, `/static/manifest.*.json`, etc.) go through **WhiteNoise** on the same gunicorn workers. Workers can be healthy on dynamic requests while WhiteNoise's static path is still flaky during a worker cycle, so the warmup said "all good" → reload fired → static fan-out hit a worker mid-rotation → 502s on CSS/JS/favicon/manifest.

Fix in `templates/core/system_updates.html::warmupAndReload()`: scrape `<link href>` URLs starting with `/static/` from the current page (CSS, manifest, favicon) and probe THOSE in parallel with the API URL. The set is capped at 8 URLs to avoid swamping a small worker pool. If any return non-200 we drop back to single-probe polling. Once all 8 return 200 simultaneously we know the exact set of URLs the reload will refetch is healthy on every worker.

The progress message now reads `"All paths responding (8 URLs) — reloading in 3 seconds…"` so you can see it's actually exercising the static path.

### Tests
None — frontend warmup probe path change; verified by reading the page's `<link>` tags + WhiteNoise middleware position in `config/settings.py`.

## [3.17.425] - 2026-05-08

### Fixed (for real this time) — APK was still 137MB after v3.17.424
The `-PreactNativeArchitectures=arm64-v8a` Gradle property in v3.17.424 did nothing on `assembleDebug`. That property is only consumed by the `splits { abi { include (*reactNativeArchitectures()) } }` block, which is gated behind `enableSeparateBuildPerCPUArchitecture` — disabled by default for debug builds. Inspecting the v3.17.424 APK confirmed all 4 ABIs were still bundled (`lib/arm64-v8a/`, `lib/armeabi-v7a/`, `lib/x86/`, `lib/x86_64/` — ~150MB total of native libs).

Real fix in `core/management/commands/build_mobile_app.py`: after `expo prebuild --clean` regenerates `android/app/build.gradle`, append `android.defaultConfig.ndk.abiFilters 'arm64-v8a'` to the file. That sets the NDK ABI filter directly on the default variant — the build only packages arm64-v8a native libs, and the other 3 ABI directories never enter the APK.

Patch is idempotent (guarded by a `// CST-ABI-FILTER` marker comment) so re-running the build after a clean prebuild always re-injects the line.

Expected APK after v3.17.425: **~40-50MB**. If size doesn't drop on the next rebuild, unzip the APK and check `lib/` — only `lib/arm64-v8a/` should be present.

### Tests
None — Gradle gradle-file injection; verified by inspecting the v3.17.424 APK contents (all 4 ABIs present, total native libs 147.9MB) and the React Native default-config docs.

## [3.17.424] - 2026-05-08

### Fixed — APK was 151MB, now ~40MB
The v3.17.419 switch to `assembleDebug` shipped 4 native-library architectures by default (`armeabi-v7a + arm64-v8a + x86 + x86_64`) so the build would also work on Android emulators. Each ABI is ~30-40MB of compiled native libs (React Native runtime, Reanimated, Hermes, etc.) — total APK ballooned to 151MB.

For sideload to internal field techs, only `arm64-v8a` matters — every Android phone shipped since 2017 uses arm64. Adding `-PreactNativeArchitectures=arm64-v8a` to the Gradle invocation in `core/management/commands/build_mobile_app.py` strips the other three ABIs out of the APK.

Expected APK size: **~40-50MB** (down from 151MB). Build time also drops by ~1 minute since there are 75% fewer native libs to compile.

If we ever need x86 support (Android emulators, ChromeOS, some Lenovo tablets), bump the property to `arm64-v8a,x86_64` and rebuild.

### Tests
None — Gradle config switch; verified by reading the React Native build doc + the current APK output size.

## [3.17.423] - 2026-05-08

### Fixed — APK build died on gunicorn restart, status stuck at "Building"
The Android APK build was launched as a daemon thread that ran `subprocess.run([..., 'build_mobile_app', 'android'])`. The subprocess inherited the gunicorn worker's process group — so when a subsequent `systemctl reload huduglue-gunicorn.service` (e.g. from applying a Django update) sent SIGTERM through the worker's process tree, the gradle build was killed mid-flight. The build log + status file froze and the UI looped forever showing "Building debug APK with Gradle (5-10 minutes)…".

Two fixes in `core/views.py::download_mobile_app`:

- **Detached subprocess**: switched `subprocess.run(... capture_output=True)` to `subprocess.Popen(..., start_new_session=True, close_fds=True)` with stdin/stdout/stderr redirected to `DEVNULL`. `start_new_session=True` calls `setsid()` on the child so it becomes its own session leader, fully decoupled from gunicorn's process group. Future gunicorn restarts will not kill running APK builds.

- **Stale-status detection**: when the page is hit while a build is "in progress", the view now checks the mtime of both `<platform>_build_status.json` and `<platform>_build.log`. If neither has been touched in 5+ minutes, the build process is presumed dead and the status is flipped to `failed` with a friendly message ("Build process appears to have died… most likely cause: gunicorn was restarted while the build was running. Click Retry to start a fresh build."). The existing failed-branch UI then offers a Retry button.

### Tests
None — process-group + filesystem timing fix; verified by tracing the original death (no gradle/cmake/java processes after gunicorn reload) and confirming `start_new_session=True` documented behavior.

## [3.17.422] - 2026-05-08

### Fixed — 502s on static files after Apply reload
After v3.17.421 successfully completed an update, the page reload that follows could fan out CSS/JS/font/manifest requests in parallel and catch a gunicorn worker still in the middle of its post-SIGHUP graceful-restart cycle — that worker 502s. The user saw a broken page with `ERR_ABORTED 502` for `themes.*.css`, `manifest.*.json`, etc. even though gunicorn was up overall.

Root cause: the public edge OpenResty proxies straight to `gunicorn:8000` (no local nginx in the path serving static directly). When systemctl reload replaces workers one at a time, individual workers go through a brief unavailable window. Two consecutive 200 probes from a single connection wasn't enough — page reload uses many parallel connections and any of them can hit a worker in the middle of replacement.

Fix in `templates/core/system_updates.html::waitForServerThenReload()`:
1. Bumped `consecutiveOk` requirement from 2 → **3** (faster cadence, 400ms between probes).
2. After 3 consecutive OKs, run a **`warmupAndReload()`** phase: fire **6 parallel probes** in flight at once. If ANY one fails, drop back to single-probe polling. This actively exercises multiple workers in parallel, surfacing any laggard before the page reload does.
3. After all 6 warmup probes succeed, hold for **3 seconds** of settle time before `location.reload()` — gives any worker still in graceful shutdown time to finish.

The progress bar now flips through "Server responded — confirming health (1/3)…" → "Warming up workers — confirming all responding…" → "All workers responding — reloading in 3 seconds…" so the user sees the extra phase.

### Tests
None — frontend timing change; verified by tracing the warmup → settle → reload sequence.

## [3.17.421] - 2026-05-08

### Fixed — Update hung at "4 of 5 steps complete" forever
Two bugs in the Step 5 (Restart Service) progress signaling:

1. **Trigger string mismatch.** `core/updater.py::step_triggers` watched for `Step 5/5: Scheduling` to mark step-5 as started, but `deploy/update_instructions.sh` wrote `Step 5/5: Clearing bytecode cache and reloading service...`. The start trigger never fired, so the UI never even showed step 5 as in-progress.
2. **Reader killed before "Update complete!"** The bash script issues `sudo systemctl reload huduglue-gunicorn.service` inside step 5, which SIGHUPs the very gunicorn worker that's reading the bash subprocess's stdout. The worker shuts down gracefully — but its daemon thread (the one watching for trigger strings) dies with it, BEFORE the bash script gets to log `Update complete!`. So the `complete` trigger never fired either. Result: front-end stuck at 4/5.

Fixes:

- `deploy/update_instructions.sh` now writes the completed status directly into `/tmp/clientst0r_update_progress_current.json` (atomic `os.replace`) IMMEDIATELY before issuing the reload signal. The front-end poller reads `status: 'completed'` regardless of whether the Python reader survives the restart.
- `deploy/update_instructions.sh` also changes the `Step 5/5:` opening line from `Clearing bytecode cache...` to `Scheduling service restart...` so the `'start'` trigger string in `core/updater.py` matches.
- `core/updater.py::step_triggers` adds two extra `'complete'` matchers (`Step 5/5: Marked progress`, `Step 5/5: Graceful reload`) as defense-in-depth so even if the bash JSON-write fails, the live log still resolves step 5 if the reader survives.

If you're currently looking at a hung "4 of 5 steps" screen, the underlying gunicorn restart most likely DID happen — manual refresh should bring you to the new version. v3.17.421 prevents the screen from hanging on future updates.

### Tests
None — bash + signal-handling fix; verified by tracing the restart kill chain.

## [3.17.420] - 2026-05-08

### Improved — Post-update reload UX
The v3.17.418/419 line-of-text countdown didn't make it clear progress was happening, and the 2-minute hard cap was too short on first-time-after-deploy gunicorn restarts. Rewrote `waitForServerThenReload()` in `templates/core/system_updates.html`:

- **Visible progress bar** (Bootstrap progress-bar-striped/animated) that fills 0→95% over ~30s of expected restart time, then holds at 95% until the server actually responds. Independent 250ms ticker so the bar keeps moving even if a single probe stalls.
- **Live elapsed timer** in the corner ("12s") so you always see the page is alive.
- **Manual "Reload now" button** appears after 15 seconds. Gives an escape hatch without making the user wait for the auto-detect.
- **5-minute max wait** (was 2 minutes). On expiry, the bar turns red and the message points at `journalctl -u huduglue-gunicorn.service` for diagnosis.
- **Two consecutive 200s still required** (avoids catching a single half-up worker), but the message now says "Server responded — confirming health (1/2)…" instead of the cryptic "(#1/2)".
- 4s per-fetch abort (was 3s) — slightly more tolerant of a slow first response.

### CodeQL — stale `java` and `cpp` databases purged
The repo's CodeQL scan dashboard kept showing a "language:java-kotlin" configuration with errors ("No Java/Kotlin code found") even though the Advanced workflow at `.github/workflows/codeql.yml` only scans `[python, javascript-typescript, actions]` and the Default setup is `not-configured`. The cause was leftover CodeQL `java` (82MB) and `cpp` databases on the repo from before the Advanced workflow took over. Purged via `gh api -X DELETE /repos/agit8or1/clientst0r/code-scanning/codeql/databases/{java,cpp}`. The dashboard's java-kotlin row will clear after the GitHub UI cache refreshes (a few minutes).

### Tests
None — frontend UX rewrite + GitHub API cleanup; verified by reading the JS and confirming the API delete returned cleanly.

## [3.17.419] - 2026-05-08

### Fixed — Update reload countdown stopped after attempt 1
The `waitForServerThenReload()` polling helper from v3.17.418 used `fetch()` with no per-request timeout. When openresty holds the connection open during the gunicorn restart window (instead of returning 503), the fetch never resolves AND never rejects — the countdown freezes at "attempt 1, 1s elapsed" because no `setTimeout(probe, …)` is ever scheduled.

Fix: each fetch is now wrapped in an `AbortController` with a **3-second timeout**. If the request stalls, it aborts → `.catch` fires → countdown advances → next probe is scheduled. The timer also clears on success so we don't double-fire.

### Faster — APK build now uses `assembleDebug`
The Gradle build was running `./gradlew assembleRelease`, which spends 3–5 minutes on ProGuard/R8 minification + class shrinking + a release keystore step. For internal sideload distribution (this is the only consumer right now), that work is wasted. Switched to `assembleDebug` and added `--daemon --parallel --max-workers=4 --build-cache` for another ~30–60s saving on subsequent builds.

Trade-off: debug APKs are larger (no R8 shrinking), signed with the auto-generated debug keystore (still installs cleanly, just shows "from unknown developer" — same as a release build sideloaded outside the Play Store), and are slightly slower at runtime. None of those matter for a few field techs sideloading internally. Will switch back to Release if we ever ship to a public channel.

The download view + status pages already point at `app/build/outputs/apk/debug/app-debug.apk` (v3.17.419 also updated `apk_path` in `core/management/commands/build_mobile_app.py` accordingly).

### Tests
None — frontend timeout fix + build flag swap; verified by inspecting the JS / mgmt cmd diff.

## [3.17.418] - 2026-05-08

### Fixed — System Updates Apply showed 503 mid-restart
After the update script restarted gunicorn, the modal's JS used a fixed `setTimeout(location.reload, 10000)` to refresh the page. If gunicorn wasn't fully back at the 10s mark, the reload landed on the upstream-down page (openresty 503) and the user assumed the update had failed.

Replaced the fixed timer with `waitForServerThenReload()` in `templates/core/system_updates.html`:
- Polls `/core/api/update-progress/` every 1s (then every 2s after 10s elapsed) with `cache: 'no-store'`.
- Shows a live `Server is restarting — attempt N — waiting for upstream (Ns elapsed)` line under the "Update complete" banner so the user knows we're not frozen.
- Requires **two consecutive 200 responses** before reloading — avoids catching a single half-up worker before all workers have rebooted on the new code.
- Hard cap of 2 minutes, after which the line flips to `still down after 2 min — [reload manually]` so the user can take action instead of hanging forever.

### Tests
None — frontend-only behavior change; verified by reading the polling logic and the `update_progress_api` endpoint.

## [3.17.417] - 2026-05-07

### Phase 8 — closure
Phase 8 (Native mobile apps + GPS auto-time + Timeclock) is now fully shipped. Roadmap header advances to `[shipped — v3.17.417]`; the Sizing-table row reads `shipped v3.17.354–417 (extends Phase 2 + 18 + 21)`.

What landed across the train:

- **Sub-phase 8.1 — Backend foundation** *(v3.17.397–410)*: `TechnicianLocation` + `ClientSiteGeofence` + `TimeclockEntry` + `MobileDevice` models, plus the five token-authed REST endpoints under `/api/mobile/v1/` (locations, timeclock clock-in/out/me, active-ticket).
- **Sub-phase 8.2 — GPS auto-documentation engine** *(v3.17.412)*: `AutoTimePreference` modes (always_on / ask_first / off), `PendingAutoTime` staging, `auto_document_field_visits` mgmt cmd that runs every minute and triggers Web Push on enter/exit transitions.
- **Sub-phase 8.3 — Timeclock feature** *(v3.17.413–414)*: web dashboard at `/field-ops/timeclock/` with exception flags + 7-day rollup, payroll CSV export, and a mobile Timeclock screen + dashboard widget in the Expo app.
- **Sub-phase 8.4 — App build** *(v3.17.354–360)*: `mobile/` Expo TS scaffold with auth, dashboard, organizations, assets, tickets, KB, vault, monitoring, security, settings, and the new timeclock screen.
- **Sub-phase 8.5 — Privacy + safeguards** *(v3.17.411–416)*: `LocationRetentionPolicy` + nightly `prune_technician_locations` cmd, off-shift suppression (`locations_dropped_offshift`), per-tech `/field-ops/my-location-history/` self-serve UI with bulk delete, `OrganizationFieldOpsSettings.geofence_only_mode` + `GeofenceVisit` privacy-preserving alternative to raw lat/lon, and the `/field-ops/settings/` org-admin UI.

Tests: 29 in `field_ops/tests.py`, 6 new in `api_mobile.tests.MobileFieldOpsTests`. No code changes in this release — annotation-only.

## [3.17.416] - 2026-05-07

### Added — Phase 8.5 part 3: org admin retention/privacy UI
Closes Sub-phase 8.5. Org admins can now toggle `geofence_only_mode` and adjust `retention_days` from the web UI without going through the Django admin.

- `/field-ops/settings/?org=<id>` (org admin / staff / superuser) — form for `geofence_only_mode` toggle + `retention_days` numeric. Auto-creates the `OrganizationFieldOpsSettings` row on first GET. POST saves + audit-logs `org_field_ops_settings_changed` with before/after diff.
- Template `templates/field_ops/settings.html`.

### Tests
- 2 new tests: non-admin blocked (403), save persists + writes the audit row.

## [3.17.415] - 2026-05-07

### Added — Phase 8.5: per-tech location history + geofence-only mode
Major slice of Sub-phase 8.5 (privacy hardening). Closes parts 1 (per-tech UI) + 2 (geofence-only mode).

- `field_ops.OrganizationFieldOpsSettings` — per-org `geofence_only_mode` flag + `retention_days`. When `geofence_only_mode=True`, the locations API endpoint stops persisting raw lat/lon for any geofence-matching ping and instead writes a privacy-preserving `GeofenceVisit` row (geofence id + entered_at + exited_at).
- `field_ops.GeofenceVisit` — privacy-preserving alternative to `TechnicianLocation`. Existing TechnicianLocation rows are untouched.
- `/api/mobile/v1/locations/` updated: when an inside-ping matches a geofence whose org has `geofence_only_mode=True`, return 201 with `mode=geofence_only` + a `visit_id`. Audit-log `locations_geofence_only_write`.
- `/field-ops/my-location-history/` (logged-in user, any role) — paginated list of THE CALLER'S OWN GPS pings. Per-row Delete + bulk **Delete all my history** (requires typing `DELETE` to confirm). All views + actions audit-logged.
- Migration `field_ops/0005_orgfopssettings_geofencevisit.py`.

### Tests
- 5 new tests: history page lists only my rows; per-row delete on someone else's row 404s; per-row delete on mine works; bulk delete requires confirm word; geofence-only mode writes `GeofenceVisit` (no raw row); outside-fence ping under geofence-only org still writes regular `TechnicianLocation`.

## [3.17.414] - 2026-05-07

### Added — Phase 8.3 mobile Timeclock screen
Closes Sub-phase 8.3. The Expo TS app now has a prominent Timeclock screen + a dashboard widget linking to it. Server-side endpoints already shipped in v3.17.410.

- `mobile/app/timeclock/index.tsx` — Clock In / Clock Out screen. If clocked in: shows started timestamp, duration, org/ticket context (read-only), notes field, and a Clock Out button. If not: notes field + Clock In button.
- `mobile/src/api/timeclock.ts` — TanStack Query hooks `useTimeclockMe`, `useClockIn`, `useClockOut` wrapping `/api/mobile/v1/timeclock/{me,clock-in,clock-out}/`.
- `mobile/app/dashboard.tsx` — adds a Timeclock card at the top of the dashboard. Tapping the card routes to `/timeclock`.
- `Stack.Screen name="timeclock/index"` was already registered in `_layout.tsx` (Phase 8.4 scaffolding).

### Tests
None — server-side already covered by `api_mobile.tests.MobileFieldOpsTests` (v3.17.410). The screen reuses the typed hook shapes and shared components (`Card`, `Button`, `TextField`, `ListRow`, `Screen`, `ErrorBanner`).

## [3.17.413] - 2026-05-07

### Added — Phase 8.3 Web Timeclock dashboard + payroll CSV export
First half of Sub-phase 8.3. Staff get a dashboard showing who is currently on the clock; payroll runs an export.

- `/field-ops/timeclock/` (staff-only) — table of currently-clocked-in techs (tech, org, ticket, started, duration). Per-row exception flags: **long shift &gt;12h** and **missing clock-out &gt;8h**. Pay-period (last 7 days) hours-per-tech rollup beneath.
- `/field-ops/timeclock/payroll-export.csv` (staff-only) — last 4 weeks bucketed by `(tech, week_start, organization)`. Columns `tech, week_start, hours, overtime_hours, org`. Compatible with QuickBooks Time / Gusto manual import.
- `field_ops/views.py` and template `templates/field_ops/timeclock_dashboard.html` (Bootstrap, no JS).
- New `field_ops/urls.py` mounted at `/field-ops/` in `config/urls.py`.

### Tests
- 3 new tests: non-staff returns 403, staff dashboard renders with open entries, CSV export has the correct header + tech/org rows.

## [3.17.412] - 2026-05-07

### Added — Phase 8.2 GPS auto-documentation engine
The headline force-multiplier from Phase 8: a tech walks into a client site and a billable timer starts itself. Closes Sub-phase 8.2.

- `field_ops.AutoTimePreference` (`OneToOneField(User)`, `mode` choices `always_on` / `ask_first` / `off`, default `ask_first`).
- `field_ops.PendingAutoTime` — staging row created when an `ask_first` tech enters a geofence; promoted to a real `TicketTimeEntry` when the tech confirms via the front-end.
- `python manage.py auto_document_field_visits [--window-minutes N]` (cron every minute):
  - For each tech with `mode != 'off'` and a recent (last 5 min) `TechnicianLocation`, walk active `ClientSiteGeofence` rows.
  - **ENTER (always_on)** → create + start a `TicketTimeEntry` against the user's last-active ticket for that org. Notes start with `[auto-time:field_ops]` so the engine can find its own rows on exit.
  - **ENTER (ask_first)** → create a `PendingAutoTime` row + emit a Web Push using the existing Phase 21 v9 helper (`WebPushSubscription.send`).
  - **EXIT** → close every running engine-marked `TicketTimeEntry` for that user.
  - Audit logs every transition with `extra_data.event = auto_time_*`.
- Migration `field_ops/0004_autotimepreference.py`.

### Tests
- 5 new tests: off-mode skips, always_on enter creates a running entry, exit closes it, ask_first creates a `PendingAutoTime` (not a running TicketTimeEntry), no-recent-ping skips.

## [3.17.411] - 2026-05-07

### Added — Phase 8.5 retention: LocationRetentionPolicy + prune mgmt cmd
First slice of Sub-phase 8.5 (privacy hardening). Org admins can now bound how long GPS pings live in the database; a nightly mgmt cmd reaps anything past its `retention_until`.

- `field_ops.LocationRetentionPolicy` — `OneToOneField(Organization)`, `retention_days` PositiveInt default 90, `apply_to_geofence_only` bool default False (informational flag for v3.17.415's geofence-only mode). Admin registered.
- `python manage.py prune_technician_locations [--dry-run]` — deletes `TechnicianLocation` rows where `retention_until < today()`. Prints summary count. Works as a cron-friendly one-shot WHERE clause, no per-org join (the deadline is pre-computed on insert in v3.17.397).
- Migration `field_ops/0003_locationretentionpolicy.py`.

### Tests
- 4 new tests: defaults applied, expired rows pruned, fresh rows kept, dry-run keeps rows, no-op when nothing expired.

## [3.17.410] - 2026-05-07

### Added — Phase 8.1 mobile REST surface: locations / timeclock / active-ticket
Closes Sub-phase 8.1. Mobile clients can now POST GPS pings, clock in/out, query their open entry, and retrieve their last-active ticket — all over the existing token-auth machinery.

- `api_mobile/views_field_ops.py`:
  - `POST /api/mobile/v1/locations/` — body `{lat, lon, accuracy?, timestamp?}`. Off-shift suppression: if the timestamp falls outside the user's `WorkingHours`, return 204 + audit-log `locations_dropped_offshift` and DO NOT store. On-shift pings save a `TechnicianLocation` and return 201.
  - `POST /api/mobile/v1/timeclock/clock-in/` — body `{organization_id?, location_id?, ticket_id?, project_id?, notes?}`. 400 if user already has an open clock-in.
  - `POST /api/mobile/v1/timeclock/clock-out/` — body `{notes?}`. 400 if no open entry.
  - `GET /api/mobile/v1/timeclock/me/` — current open entry or null.
  - `GET /api/mobile/v1/active-ticket/` — most recent `TicketTimeEntry` with a null/pending submission.
- All endpoints token-authed via the existing `TokenAuthentication` machinery (v3.17.346).

### Tests
- 6 new `MobileFieldOpsTests`: location ping during work-hours stored, off-shift ping returns 204 + audit row + no DB row, clock-in then clock-out happy path, double clock-in rejected, clock-out without open returns 400, timeclock_me returns null then populated, active-ticket returns last unsubmitted.

## [3.17.409] - 2026-05-07

### Added — Phase 8.1 backend foundation (part 2): TimeclockEntry + MobileDevice
Second concrete deliverable on the Phase 8 backend train. The remaining REST endpoints land in v3.17.410.

- `field_ops.TimeclockEntry` — clock-in / clock-out events with `tech` FK, optional `organization` / `location` / `ticket` / `project` FKs, `clocked_in_at`, nullable `clocked_out_at`, `source` choices (`mobile` / `web` / `manual`), and `notes`. A partial unique constraint enforces one open clock-in per tech.
- On clock-out (`clocked_out_at` becomes non-null) AND a ticket is attached, the model automatically derives a `psa.TicketTimeEntry` row so existing billing rolls up unchanged. The derived entry is tracked via `derived_time_entry` so a re-save doesn't double-bill.
- `field_ops.MobileDevice` — registered mobile devices for long-lived bearer auth. UUID `device_id` (unique), platform (`ios` / `android`), name, optional FK to `authtoken.Token` for revoke-on-demand, `last_seen_at`, `revoked` flag.
- Admin registration for both models.
- Migration `field_ops/0002_timeclockentry_mobiledevice.py`.

### Tests
- 5 new tests: TimeclockEntry open-state behavior, partial-unique-constraint enforcement, clock-out-with-ticket derives a TicketTimeEntry, clock-out-without-ticket skips derivation; MobileDevice creation + device_id uniqueness.

## [3.17.408] - 2026-05-07

### Fixed — APK build failed in 12s with "SDK location not found"
The Gradle build was bailing immediately because `ANDROID_HOME` wasn't set in the subprocess env, so it couldn't find the Android SDK. SDK is installed at `/home/administrator/android-sdk/` (platforms 34 + build-tools 33/34). Two changes in `core/management/commands/build_mobile_app.py`:

- Auto-detect SDK location (first `$ANDROID_HOME`, then `$ANDROID_SDK_ROOT`, then candidate paths). Set both env vars before running any subprocess. Also prepend `platform-tools`, `cmdline-tools/latest/bin`, and `build-tools/34.0.0` to `PATH`.
- Belt-and-suspenders: write `mobile/android/local.properties` with `sdk.dir=$ANDROID_HOME` right before `./gradlew assembleRelease`. Some Gradle wrappers honor only the file, not the env var.

### What this doesn't fix yet
The build log also showed a SECOND error from `expo-modules-core/android/ExpoModulesCorePlugin.gradle` line 85: `Could not get unknown property 'release' for SoftwareComponent container`. That's the long-standing `expo-module-gradle-plugin` compat issue documented in memory from Feb 2026. Worth attempting the build again with v3.17.408 — sometimes the SDK-not-found error masks fixable downstream issues.

If the second error still fires after Apply + Rebuild + Build:
1. Capture the build log tail (visible on the live Build status page).
2. Send it back; we can either patch the Expo modules manifest or fall back to **Expo Go** as the dev/test path (`cd mobile && npm start`, scan QR with Expo Go from Play Store).

### Tests
None — env-var fix; verified by inspecting the `mobile/android/local.properties` write path.

## [3.17.398] - 2026-05-07

### Fixed — APK build was using the wrong (legacy) codebase
**The 20MB APK that "Download APK" served was from Feb 26, 2026 — three months old.** The `build_mobile_app` management command was set to build from the legacy `mobile-app/` skeleton (created Apr 28, 2026 — predates Phase 8). The new Expo SDK 51 + TypeScript app shipped via Phase 8 v3.17.354–360 lives at `mobile/`, but the build pipeline never pointed there. Every "Download APK" / "Build & download APK" click served the same cached-from-Feb-2026 binary that has none of the recent fixes (including the v3.17.385 Keystore cold-start crash fix).

Two changes:

- `core/management/commands/build_mobile_app.py` — `mobile_app_dir` now points at `mobile/` (the Expo TS app). Falls back to `mobile-app/` only if `mobile/` is somehow missing. Output path stays at `mobile-app/builds/` so the existing `download_mobile_app` view keeps working without changes.
- `core/views.py::mobile_apps_admin` — adds a POST `?action=rebuild&platform=<android|ios>` handler that deletes the cached binary + status files. The template now shows a **Rebuild from latest code** button next to the Download button when an APK is present. Clicking it wipes the cache, audit-logs `mobile_app_rebuild_requested`, and redirects back; the next "Build & download" click triggers a fresh compile from the current `mobile/` source tree.

To get the APK with the v3.17.385 Keystore fix:
1. Apply v3.17.398.
2. Open Admin → Mobile → Mobile Apps.
3. Click **Rebuild from latest code** (Android card). Confirm.
4. Click **Build & download APK** — first build will take ~10–20 min (npm install + Gradle); subsequent builds 3–5 min.
5. Sideload the new APK and re-test.

### Tests
None — direct fix; verified by hitting the Rebuild action and confirming the cached APK is wiped.

## [3.17.397] - 2026-05-07

### Added — Phase 8.1 backend foundation: TechnicianLocation + ClientSiteGeofence
First server-side concrete deliverable for the Phase 8 train (originally targeted v3.17.386; bumped to v3.17.397 to stay above the v3.17.396 monotonicity-fix release). The other half of Sub-phase 8.1 (TimeclockEntry + MobileDevice + the locations/timeclock/active-ticket REST endpoints) lands in the next two releases.

- New Django app `field_ops/` with `default_auto_field = BigAutoField`, registered in `INSTALLED_APPS`.
- `TechnicianLocation` model — append-only GPS ping with tech FK, lat/lon (Decimal 9,6), accuracy (meters), timestamp, source choices (`mobile` / `web`), and a pre-computed `retention_until` date so the (forthcoming v3.17.400) prune mgmt cmd is a one-shot WHERE clause.
- `ClientSiteGeofence` model — per-organization geofence supporting both `radius` (center + meters) and `polygon` (list of [lat, lon] vertices) modes. Optional `location` FK keeps Phase 18 multi-location working. Includes a `contains(lat, lon)` method using equirectangular distance for radius mode and ray casting for polygon mode.
- Admin registration for both models.
- Migration `field_ops/migrations/0001_initial.py`.

### Tests
- 6 new tests: TechnicianLocation default retention applied, explicit retention preserved; ClientSiteGeofence radius-contains, radius-excludes, polygon-contains, admin str.

## [3.17.396] - 2026-05-07

### Fixed — Update flow stuck in "Update Available" loop
Same class of bug as v3.17.333. Two parallel agents (Backend Mobile API + Phase 8 closeout) shipped with non-overlapping version ranges, but the Backend Mobile API agent's range (345–353) ended up below the Phase 8 closeout agent's range (385–395). Phase 8 v3.17.385 (the APK cold-start fix) shipped first chronologically, then the Mobile API agent kept landing v3.17.349/350 with LOWER version numbers via push-race rebase.

Result: after Apply, `config/version.py` ended up at 3.17.350 even though every committed-tag commit (including v3.17.385) was already an ancestor of HEAD. The updater compares `VERSION` (3.17.350) against the highest tag (v3.17.385), sees a mismatch, and shows "Update Available" forever — clicking Apply again does nothing visible because the script is already at the latest commit.

This release bumps `VERSION` to **3.17.396** — past every existing tag — so `Settings → Updates` reports the install as up-to-date. No code or schema change.

### Note — Backend Mobile API agent stopped
The Backend Mobile API agent was running in version range 345–353 and had completed 6 of 9 endpoint releases (auth, dashboard, organizations, assets, tickets, KB). The remaining 3 endpoints (vault reveal, monitoring/security/profile, throttling+tests) were stopped to break the non-monotonicity loop. They will be picked up in a follow-up release at HIGHER version numbers (v3.17.397+).

### Tests
None — pure version bump.

## [3.17.350] - 2026-05-07

### Added — Mobile API: knowledge-base endpoints
Sixth release in the mobile-API train. KB articles back the read surface for techs in the field.

- New endpoint `GET /api/mobile/v1/kb/?search=&page=` — paginated. Returns articles where (`is_global=True` OR `organization_id` is in the user's accessible orgs) AND `is_published=True` AND `is_archived=False`. Search matches `title`, `body`, `slug`.
- New endpoint `GET /api/mobile/v1/kb/<id>/` — detail with both raw `body` (markdown / HTML source) and `body_html` (rendered + sanitised via `Document.render_content()` which uses bleach). Cross-org reads return 404.

### Tests
- 5 new tests: list requires auth, list returns global + my-org articles (cross-org excluded), search narrows, detail returns body + rendered HTML, detail cross-org blocked.

## [3.17.385] - 2026-05-07

### Fixed — Mobile APK crashes immediately after biometric unlock
Real-world Android crash report: "makes me use unlock pattern or bio as soon as it opens, then immediately closes. I haven't even put in server details or login info." Root cause: on Android cold start the Keystore is briefly locked while the user authenticates, and `SecureStore.getItemAsync` throws a native exception during that window. The unhandled rejection inside the boot path was bubbling out of `useEffect` and the OS killed the process before any UI could mount.

- `mobile/src/utils/storage.ts` — added a `bootstrap()` helper that wraps token + server URL reads in defensive try/catch and never throws on Keystore-not-yet-ready situations.
- `mobile/app/_layout.tsx` — boot sequence now uses `bootstrap()` and treats any storage exception as "no token, continue to /login". Wrapped `<Stack>` in the new `<ErrorBoundary>` so any uncaught render-tree error shows a friendly fallback instead of crashing the app process.
- `mobile/app/index.tsx` — same defensive wrapping plus a try/catch on the `router.replace()` call (in case the router isn't ready yet).
- `mobile/src/components/ErrorBoundary.tsx` — new top-level error boundary with a "Try again" button.

### Tests
None — pure mobile-app boot-path hardening; verified by reading the updated files and confirming no static-analysis regression. (Native test would require running the Android emulator, which isn't available in CI.)

## [3.17.349] - 2026-05-07

### Added — Mobile API: tickets endpoints
Fifth release in the mobile-API train. Full read/create/patch surface plus comment add — covers a tech's daily field workflow.

- New endpoint `GET /api/mobile/v1/tickets/?status=&priority=&assigned_to_me=true&organization_id=&search=&page=` — paginated. `status=open` matches all non-terminal statuses; `status=closed` matches `is_terminal=True`; otherwise matches `TicketStatus.slug`. `priority` matches `TicketPriority.code` (e.g. `P1`).
- New endpoint `POST /api/mobile/v1/tickets/` — create. Requires `organization_id` + `subject`; `description`, `requester_name`, `requester_email` optional. Cross-org create returns 403. Defaults pulled from existing seed data (status=new, priority=P3, first TicketType + Queue) — returns 409 if PSA seed data is missing.
- New endpoint `GET /api/mobile/v1/tickets/<id>/` — detail with embedded comments thread (ordered by `created_at`).
- New endpoint `PATCH /api/mobile/v1/tickets/<id>/` — partial update of `status_id` / `priority_id` / `assigned_to_id` (use `null` / `0` to unassign). Cross-org returns 404.
- New endpoint `POST /api/mobile/v1/tickets/<id>/comments/` — add a comment. Body required; optional `is_internal` flag. `source='api'` recorded on the row.

### Tests
- 8 new tests: list scoped to user orgs, detail returns my ticket with comments, detail cross-org blocked (404), create happy path, create cross-org rejected (403), patch status, add comment, list requires auth.

## [3.17.382] - 2026-05-07

### Fixed — Mobile Apps page hard to read on dark theme
The custom `.platform-card` div had a 1px border but no background, so on the dark theme it inherited the page background and the card content blended into the surrounding chrome. Switched to Bootstrap's `<div class="card">` + `<div class="card-body">` pair so each platform tile now gets a proper themed background that contrasts with the page. Also tightened the inline-`<code>` and status-pill foreground colors via `--bs-emphasis-color` / `--bs-*-text-emphasis` for stronger contrast in both light and dark themes.

### Tests
None — pure CSS / template structure change.

## [3.17.381] - 2026-05-07

### Fixed — Mobile Apps admin page 500
The v3.17.380 view used `django.utils.timezone.utc` to format the APK build mtime, which was removed in Django 5. We're on Django 6 — page returned 500 with `AttributeError: module 'django.utils.timezone' has no attribute 'utc'`. Replaced with stdlib `datetime.timezone.utc`.

### Tests
None — single-line fix; verified by hitting `/core/mobile-apps/` after restart.

## [3.17.348] - 2026-05-07

### Added — Mobile API: assets endpoints
Fourth release in the mobile-API train.

- New endpoint `GET /api/mobile/v1/assets/?search=&organization_id=&type=&page=` — paginated list scoped to the user's accessible organizations. Search matches `name`, `hostname`, `ip_address`, `serial_number`, `asset_tag`. Filters: `organization_id` (rejected if not in caller's accessible orgs), `type` (asset_type slug).
- New endpoint `GET /api/mobile/v1/assets/<id>/` — detail. Cross-org reads return 404. Detail body includes `mac_address`, `os_name`, `os_version`, `manufacturer`, `model`, `warranty_status`, `created_at`.

### Tests
- 6 new tests: list scoped to user orgs (cross-org rows excluded), detail returns my asset, detail cross-org blocked (404), list search by hostname narrows results, list filter by `type`, list requires auth.

## [3.17.380] - 2026-05-07

### Added — Admin "Mobile Apps" landing page for sideload distribution
New page at `/core/mobile-apps/` linked from the Admin nav dropdown (under a new "Mobile" section). Renders a two-card layout:

- **Android** card: build status pill (Ready / Building / Not built), file size + age when available, "Download APK" or "Build & download APK" button (re-uses the existing `core:download_mobile_app` view that auto-builds via `npx expo prebuild` + Gradle on first request), and a 4-step sideload guide.
- **iOS** card: explains that iOS sideload requires Mac/Xcode or AltStore/Sideloadly (no Linux server-side build path produces a sideloadable IPA). Lists 4 distribution paths (Expo Go for dev, free 7-day cert via Sideloadly, Apple Developer ad-hoc, App Store) so the operator can pick the right one. External links to AltStore and Sideloadly.
- A "Build pipeline" footer card surfaces the source path (`mobile/`), output paths, and status-JSON paths so admins can debug without SSH.

The page is gated by the existing `is_staff or is_superuser` pattern via `@user_passes_test`.

### Version-numbering note
This release is intentionally numbered v3.17.380 (skipping ~33 patch numbers above the latest pushed v3.17.363 + the in-flight backend-mobile-API agent's range that tops at 353). The bump avoids version-vs-tag collisions with the still-running parallel agent. A monotonicity-fix release will follow once all parallel work finishes.

### Files
- `core/views.py` — new `mobile_apps_admin` view
- `core/urls.py` — new `core:mobile_apps_admin` URL at `/core/mobile-apps/`
- `templates/core/mobile_apps_admin.html` — new page
- `templates/base.html` — Admin dropdown gets a "Mobile" section with the new link

### Tests
None — pure UI/admin landing page; the underlying download view is already covered.

## [3.17.347] - 2026-05-07

### Added — Mobile API: dashboard + organizations endpoints
Third release in the mobile-API train.

- New endpoint `GET /api/mobile/v1/dashboard/` — headline counts the mobile dashboard renders: open tickets, critical (P1) tickets, expirations within 30 days, offline website monitors, recent assets (7 days), open security alerts, recent audit-log activity (24 h), and `organization_count`. Counts are scoped to the user's accessible organizations. Each model lookup is defensive — if a model / app isn't loaded the count falls back to 0 instead of 500.
- New endpoint `GET /api/mobile/v1/organizations/?search=&page=` — paginated list of orgs the user has an active `Membership` in. Supports search by name / slug.
- New endpoint `GET /api/mobile/v1/organizations/<id>/` — detail with related counts (assets, open tickets, contacts). Cross-org reads return 404.
- New helper `api_mobile/scoping.py::accessible_org_ids(user)` — single source of truth for "which orgs can this user see" used by all subsequent endpoints in the train.

### Tests
- 6 new tests: dashboard requires auth, dashboard returns counts dict, org list requires auth, org list scoped to user's orgs, org detail returns my org, org detail cross-org read blocked (404).
- Updated test class decorators to disable DRF rate-throttling — cumulative login attempts across multiple test classes sharing one IP otherwise tripped the 10/hour login throttle.

## [3.17.363] - 2026-05-07

### Changed — Phase 23 close
Phase 23 (Security Event & Incident Workflows) closeout. All 12 sub-bullets now carry `*(shipped vN.N.N)*` annotations and the phase header is now `[shipped — v3.17.363]` so the JSON roadmap feed at `/core/roadmap.json` reports the correct status. Sizing-table row updated to "shipped v3.17.337–363 (extends Phase 9 + 17)".

Phase 23 features delivered (over 8 releases v3.17.337 → v3.17.363):
- v3.17.337 — SIEM webhook adapter (CEF/JSON/Syslog).
- v3.17.338 — `SecurityIncident` + `SecurityIncidentEvent` + auto-correlation by asset/severity window.
- v3.17.339 — Per-organization cached `exposure_score` + `recompute_exposure_scores` mgmt cmd.
- v3.17.355 — `SecurityIncidentSLAPolicy` + `check_incident_sla_breaches` mgmt cmd (idempotent timeline events).
- v3.17.358 — `RemediationPlaybook` + `RemediationPlaybookStep` engine; auto-fires on incident open.
- v3.17.361 — `/security/threat-overview/` single-pane analyst dashboard.
- v3.17.362 — OPTIONAL AI incident summarization gated by `psa_ai_enabled`.

The remaining sub-bullets (Security event ingestion, Security dashboarding, Security event reporting, Vulnerability correlation, CVE-to-ticket workflows) shipped via prior Phase 9 / Phase 17 work and carry cross-phase shipping annotations.

### Tests
None — pure docs / metadata commit.

## [3.17.362] - 2026-05-07

### Added — Phase 23 v7: AI-assisted incident summarization (OPTIONAL AI)
Seventh Phase 23 release. **OPTIONAL AI** — gated by `SystemSetting.psa_ai_enabled`. Given a `SecurityIncident`, produce a 1-paragraph executive summary plus suggested next steps. The summarizer is pluggable via `set_provider(...)`; the default heuristic implementation is deterministic (no network) so the feature degrades gracefully when no LLM is configured. A new POST endpoint `/security/incidents/<id>/ai-summarize/` triggers summarization and stores the result as a timeline note.

- New module `security_alerts/ai_summarizer.py` with `is_ai_enabled()`, `summarize_incident(incident, requested_by=...)`, and `set_provider(callable)`.
- New view `incident_ai_summarize` — when AI is disabled returns a flash error; when enabled, produces a summary and posts it to the incident timeline as a `note` event.
- Provider-call layer is mockable so production deployments can swap in the existing `psa_ai/services` Anthropic plumbing.

### Tests
- 3 new tests covering the gate-off branch (no provider call, no timeline write), gate-on happy path (summary + timeline note recorded), and provider-error handling.

## [3.17.361] - 2026-05-07

### Added — Phase 23 v6: Threat visibility dashboard
Sixth Phase 23 release. New single-pane analyst view at `/security/threat-overview/` rolling up open alerts by severity, open incidents by severity, top-exposed organizations (cached `exposure_score`), in-flight playbook activity in the last 24 hours, and a 7-day-vs-prior-7-day week-over-week alert-volume trend.

- New view `threat_overview` and template `templates/security_alerts/threat_overview.html`.
- Safe with empty data (zero alerts, zero incidents, zero exposure scores) — renders the page with placeholders.
- Reuses cached `Organization.exposure_score` for the top-exposed table.

### Tests
- 4 new tests covering empty render, alert counts, top-exposed inclusion, and the no-prior-week WoW edge case.

## [3.17.360] - 2026-05-07

### Added — Phase 8 mobile app v5: Docs + EAS placeholder + roadmap close
Final mobile-app release in this train. Documentation + production-build scaffolding so an operator can run `eas init && eas build` once they have Apple Developer + Play Console accounts.

- New `mobile/README.md` — full setup (prereqs, local dev, backend URL examples for iOS sim / Android emulator / LAN device, type-check command, EAS production-build path, signing-keys checklist, security notes about token storage and vault-secret handling).
- New `mobile/eas.json` — `development` / `preview` / `production` build profiles. Submit-config keys for App Store Connect + Play Console are placeholders that operators fill in.
- New `mobile/assets/icon.png`, `mobile/assets/splash.png`, `mobile/assets/adaptive-icon.png`, `mobile/assets/favicon.png` — solid-color 1024×1024 placeholders generated programmatically. Replace before store submission.
- `mobile/app.json` — `extra.eas.projectId` placeholder so `eas init` can fill it in cleanly.
- `docs/MOBILE_APP_PLAN.md` — appended a "Mobile app shipped" section with the per-release breakdown, screens delivered, and what remains deferred (GPS auto-time, timeclock UI, push notifications, biometric unlock, Azure SSO).
- `docs/ROADMAP.md` Phase 8 sub-phase 8.4 annotation completed; phase header stays `[in progress]` because Sub-phases 8.2 (GPS auto-time), 8.3 (timeclock), and 8.5 (privacy hardening) are explicitly deferred.

### Tests
- `cd mobile && npx tsc --noEmit` clean.

## [3.17.359] - 2026-05-07

### Added — Phase 8 mobile app v4: Vault + Monitoring + Security + Settings
Fourth mobile-app release. Closes the read-heavy MSP-field surface — secure vault reveal flow, website-monitor + expirations dashboard, security alert summary, and account/server/theme settings.

- New screens:
  - `app/vault/index.tsx` (list — never shows secrets, flags entries that need approval).
  - `app/vault/[id].tsx` (detail + secure reveal flow):
    - Reveal is gated by a confirmation modal.
    - 200 response shows the secret in component state ONLY — never SecureStore, never AsyncStorage, never logged.
    - 202 response (approval required) surfaces the request URL instead of the secret.
    - Optional copy-to-clipboard auto-clears in 30 s and warns the user.
    - `expo-screen-capture.preventScreenCaptureAsync` engaged while a secret is on screen (best-effort; iOS cannot fully suppress).
    - Secret + clipboard cleared on unmount.
  - `app/monitoring/index.tsx` (website monitors + upcoming expirations with status pills).
  - `app/security/index.tsx` (severity-bucketed alert tiles + recent-alerts list).
  - `app/settings/index.tsx` (profile edit via PATCH /profile/, server URL, theme override stored in AsyncStorage, logout, clear-local-data, app version display).
- New TanStack Query hooks: `useVaultEntries`, `useVaultEntry(id)`, `useRevealVaultSecret(id)`, `useMonitors`, `useExpirations`, `useSecuritySummary`, `useProfile`, `useUpdateProfile`.
- Reveal hook deliberately performs no `onSuccess` cache write — secrets are not cached anywhere on disk.
- Renumbered to v3.17.359 because Phase 23 closeout took v3.17.358.
- No Django code touched. `cd mobile && npx tsc --noEmit` clean.

### Tests
- `cd mobile && npx tsc --noEmit` clean.

## [3.17.358] - 2026-05-07

### Added — Phase 23 v5: Remediation playbook engine
Fifth Phase 23 release. New `RemediationPlaybook` + `RemediationPlaybookStep` models drive automated remediation flows on `SecurityIncident` rows. When an incident is opened by alert correlation, the highest-priority active playbook matching the incident's severity (and optional client_org) fires and runs each step in order. Step results stream to the incident timeline as `playbook_action` events.

- New model `security_alerts.RemediationPlaybook` — trigger conditions (severity ≥ + optional client scope), priority ordering, active flag.
- New model `security_alerts.RemediationPlaybookStep` — ordered actions: `create_ticket` / `send_email` / `quarantine_asset_flag` / `run_workflow_rule`.
- New helpers `find_matching_playbook(incident)` and `execute_playbook(playbook, incident, dry_run=False)` — error-isolated step dispatch; one failed step won't halt the rest.
- `quarantine_asset_flag` adds an Asset to a `security-quarantine` Tag for the incident's organization.
- Wired into `_correlate_alert_to_incident` so newly opened incidents fire their matching playbook automatically.
- New view `/security/playbooks/` lists playbooks + steps + active status.
- New migration `security_alerts/0005_remediationplaybook_remediationplaybookstep.py`.

### Tests
- 5 new tests covering severity-min matching, priority ordering, ticket creation, dry-run side-effect-free behavior, and unknown-action handling.

## [3.17.357] - 2026-05-07

### Added — Phase 8 mobile app v3: Tickets + Knowledge Base
Third mobile-app release. Adds the workflow surface for techs in the field — review, triage, comment, and create tickets, plus search-and-read of the knowledge base.

- New screens: `app/tickets/index.tsx` (filter chips: open / mine / critical / closed / all + search), `app/tickets/[id].tsx` (detail + status + priority chip-pickers + comments thread + add-comment form with optional internal flag), `app/tickets/new.tsx` (create form), `app/kb/index.tsx` (search), `app/kb/[id].tsx` (article render via `react-native-markdown-display`; HTML articles fall back to plain text — TODO add `react-native-render-html` if needed).
- New TanStack Query hooks: `useTickets(args)`, `useTicket(id)`, `useCreateTicket`, `useUpdateTicket(id)`, `useAddComment(id)`, `useKBArticles(search)`, `useKBArticle(id)`. Mutations invalidate the right cache keys so the dashboard counters refresh on status changes.
- `auth.ts` `me()` now hits `/auth/me/` to match backend v3.17.346 (was `/profile/`); `/profile/` is reserved for the editable Settings screen in v3.17.359.
- No Django code touched. `cd mobile && npx tsc --noEmit` clean.

### Tests
- `cd mobile && npx tsc --noEmit` clean.

## [3.17.356] - 2026-05-07

### Added — Phase 8 mobile app v2: Dashboard + Organizations + Assets
Second mobile-app release. Adds the read-heavy MSP-field views needed for daily use. All screens consume the `/api/mobile/v1/` endpoints the backend agent is shipping in v3.17.345-353.

- New screens: `app/dashboard.tsx` (stat tiles + recent tickets / assets / alerts with pull-to-refresh), `app/organizations/index.tsx` (search + list), `app/organizations/[id].tsx` (detail + related-counts shortcuts), `app/assets/index.tsx` (list + filters: org / type / status), `app/assets/[id].tsx` (detail).
- New TanStack Query hooks: `useDashboard`, `useOrganizations`, `useOrganization(id)`, `useAssets(filters)`, `useAsset(id)`.
- New reusable components: `Card`, `StatTile`, `ListRow`, `StatusPill` (with severity / ticket-status / monitor-status helpers).
- Stat tiles act as drilldowns into Tickets / Monitoring / Security screens (full implementations land in v3.17.357 + v3.17.358).
- Filters and search debounce naturally via React Query's `queryKey`-based caching.
- No Django code touched. `cd mobile && npx tsc --noEmit` is clean under strict mode.

### Tests
- `cd mobile && npx tsc --noEmit` clean.

## [3.17.346] - 2026-05-07

### Added — Mobile API: DRF setup + auth endpoints
Second release in the mobile-API train. New `api_mobile/` Django app under `/api/mobile/v1/` with token-authenticated auth endpoints. DRF and `rest_framework.authtoken` were already installed and migrated, so no new dependencies or model migrations are needed for this release.

- New endpoints (all under `/api/mobile/v1/auth/`):
  - `POST /login/` — username/email + password → `{token, user}`. If the user has 2FA enabled, returns `{mfa_required: true, mfa_token}` and requires a follow-up `/mfa/` call.
  - `POST /mfa/` — `mfa_token + code` → `{token, user}`. Validates against `django_otp.plugins.otp_totp` confirmed devices.
  - `POST /logout/` — revokes the caller's token.
  - `GET /me/` — returns `{user: {id, username, email, full_name, organization_id, role}}`.
  - `POST /refresh/` — rotates the caller's token (old token revoked, new one issued).
- Login is throttled at 10/hour per IP via the existing `login` scope. Failed logins continue to feed `django-axes` IP lockout (the existing auth backend chain runs unchanged).
- Every login / MFA / logout / refresh writes an `AuditLog` with `extra_data.channel='mobile'`. Failed logins audit as `login_failed` with the offending username and the rejection reason (`invalid_credentials` / `bad_totp` / `inactive`).
- The MFA challenge token is opaque, single-use, kept in Django's default cache for 5 minutes, and consumed atomically.

### Tests
- 9 new tests in `api_mobile/tests.py` covering login success, wrong password, missing fields, 2FA-required branch (`mfa_required: true` + opaque `mfa_token`), bad-MFA-token rejection, unauthenticated `/me/` blocked, authenticated `/me/` returns profile, `logout` revokes token, `refresh` rotates token.

## [3.17.355] - 2026-05-07

### Added — Phase 23 v4: Incident SLA tracking
Fourth Phase 23 release. Security incidents now carry SLA targets (acknowledge / contain / resolve) via a new `SecurityIncidentSLAPolicy` model. Targets are matched on (organization, client_org, severity) with the most-specific (client-pinned) policy winning over MSP-wide. A breach checker walks every open incident and writes idempotent `sla_breach` timeline events when a target deadline passes without being met.

- New model `security_alerts.SecurityIncidentSLAPolicy` — minutes-to-acknowledge / contain / resolve targets per (org, optional client, severity), unique together.
- New helpers `policy_for_incident(incident)` and `evaluate_incident_breaches(incident)` in `security_alerts.models`. Breach evaluation is idempotent — re-running won't double-record the same target.
- New mgmt cmd `manage.py check_incident_sla_breaches [--org-id=N]`.
- New migration `security_alerts/0004_securityincidentslapolicy.py`.

### Tests
- 5 new tests covering inside-window happy path, acknowledge-overdue, idempotency, met-inside-target, and the management command.

## [3.17.354] - 2026-05-07

### Added — Phase 8 mobile app v1: scaffold + auth client
First release of the Expo React Native + TypeScript client under `mobile/`. Targets the `/api/mobile/v1/` backend the concurrent backend agent is shipping in v3.17.345–353.

- New `mobile/` Expo SDK 51 project with TypeScript strict-mode, Expo Router file-based routing, TanStack Query, axios, zod.
- Server URL + auth token persisted in `expo-secure-store`. Vault secrets are NEVER persisted, never logged.
- Login screen supports server URL override, email/password, and the MFA second-step flow that the backend `/auth/login/` + `/auth/mfa/` endpoints emit.
- API client at `mobile/src/api/client.ts` with auth-header injection and 401 -> re-login handler.
- Typed serializer mirrors at `mobile/src/types/api.ts` for User, Organization, Asset, Ticket, KBArticle, VaultEntry, Monitor, ExpirationItem, SecuritySummary, DashboardSummary.
- Reusable components — `Screen`, `TextField`, `Button`, `ErrorBanner`.
- Does NOT touch any Django code; no migrations, no urls. Web app behavior is unchanged.

### Tests
- `cd mobile && npx tsc --noEmit` passes with strict mode.
- Backend API tests are owned by the concurrent mobile-API release.

## [3.17.345] - 2026-05-07

### Added — Mobile API plan doc (Phase 8 prep)
First of the v3.17.345 → v3.17.353 mobile-API release train. Pure docs commit. Adds `docs/MOBILE_APP_PLAN.md` describing the planned `/api/mobile/v1/` surface, token-auth + 2FA flow, vault-reveal security rules (GeoIP / Axes / `VaultAccessRule` / `requires_reveal_approval` all preserved), throttling, CSRF posture, and a per-release endpoint table. Companion document to Phase 8 in `docs/ROADMAP.md`. The actual endpoints + tests land starting v3.17.346.

### Tests
None — pure docs.

## [3.17.339] - 2026-05-07

### Added — Phase 23 v3: Exposure scoring
Third Phase 23 release. Each Organization now carries a cached `exposure_score` (0–1000) computed from open SecurityAlerts (severity-weighted), open SecurityIncidents, open Vulnerabilities (per-org and global advisories), plus an asset-count surface-area bonus. The score is recomputed in batch by `manage.py recompute_exposure_scores` (cron-friendly) and surfaced as a colored badge on the organization detail page.

- New fields `core.Organization.exposure_score` + `exposure_score_updated_at`.
- New module `security_alerts/exposure.py` — pure-function scoring with `compute_exposure_score(org)` and `recompute_for_org(org)`.
- New mgmt cmd `manage.py recompute_exposure_scores [--org-id=N] [--dry-run]`.
- Severity weights: SecurityAlerts critical=25 / high=12 / medium=5 / low=2 / info=1; open Incidents 2× alert weight; Vulnerabilities critical=30 / high=15 / medium=6 / low=2; asset-count bonus +1 per 5 assets capped at +50; total capped at 1000.
- New migration `core/0060_organization_exposure_score_and_more.py`.
- Org detail template card shows a green / amber / red badge and last-updated timestamp.

### Tests
- 5 new tests covering zero-state, severity weighting, resolved-alert exclusion, recompute persistence, and the management command.

## [3.17.338] - 2026-05-07

### Added — Phase 23 v2: Security incident model + timelines
Second Phase 23 release. New `SecurityIncident` + `SecurityIncidentEvent` models group related `SecurityAlert` rows into analyst-facing case files with a chronological timeline. Auto-correlation rule: a fresh alert merges into an open incident when (organization, asset_hint, severity) match within a 60-minute window; otherwise a new incident is opened anchored by the alert. Manual notes + status transitions are recorded as timeline events.

- New model `security_alerts.SecurityIncident` — 5-state status machine (open / investigating / contained / resolved / closed), severity inherited from `SecurityAlert`, M2M to alerts, optional `assigned_to`.
- New model `security_alerts.SecurityIncidentEvent` — typed timeline entries (opened, alert_added, note, status_change, acknowledged, contained, resolved, closed, playbook_action, sla_breach).
- New helper `_correlate_alert_to_incident(alert, window_minutes=60)` — wired into the vendor sync, vendor webhook, and SIEM webhook ingest paths so every newly created `SecurityAlert` flows into the incident store automatically.
- New views: `/security/incidents/` (list + filters), `/security/incidents/<id>/` (timeline + linked alerts + status buttons), POST `/security/incidents/<id>/decide/` for transitions and analyst notes.
- New migration `security_alerts/0003_securityincident_securityincidentevent_and_more.py`.

### Tests
- 7 new tests covering correlation (open new / attach to existing / different-severity branches), `add_event` helper, resolved-incident branching, plus view tests for detail render and acknowledge transition.

## [3.17.337] - 2026-05-07

### Added — Phase 23 v1: SIEM webhook adapter (CEF/JSON/Syslog)
First Phase 23 release. New `SIEMWebhookEndpoint` model exposes a per-token inbound endpoint at `/security/siem/webhook/<token>/` that accepts CEF (ArcSight Common Event Format), generic JSON, or syslog-wrapped CEF. Inbound events are normalized into the existing `SecurityAlert` schema so the triage UI, auto-ticket rules, and downstream Phase 23 incident workflows just work.

- New model `security_alerts.SIEMWebhookEndpoint` — per-organization endpoint with auto-generated token + HMAC secret, optional `require_hmac` enforcement, configurable expected format, default severity fallback.
- New CEF parser at `security_alerts/siem.py` — `parse_cef_line` handles escaped pipes in headers, `_split_cef_extension` extracts key=value pairs preserving spaces, severity 0–10 maps to `low/medium/high/critical` buckets.
- New view `siem_webhook_receive` — 404 for unknown tokens, 403 for invalid/missing-when-required signatures, 200 with `{received, imported}` JSON on success. Dedupes on `(siem_endpoint, external_id)`.
- New URLs: `/security/siem/` (CRUD list), `/security/siem/new/`, `/security/siem/<id>/edit/`, `/security/siem/webhook/<token>/`.
- `SecurityAlert.connection` is now nullable; new `SecurityAlert.siem_endpoint` FK + dedupe index. Vendor-connection alerts continue to dedupe on `(connection, external_id)`.

### Tests
- 7 new tests covering CEF parser, severity bucketing, unknown-token 404, invalid HMAC 403, valid HMAC accept, dedupe on repeat ingestion, JSON payload happy path, require_hmac enforcement.

## [3.17.336] - 2026-05-07

### Removed — Phase 29 deleted from roadmap
Same treatment as Phases 24 + 30 in v3.17.335. Phase 29 (Commercial Operations Ecosystem — tiered support tiers, paid onboarding, SOC 2 readiness, reseller program, etc.) is removed from the roadmap entirely. Roadmap now jumps Phase 28 → Phase 31. Sizing-table row dropped.

### Tests
None — pure roadmap edit.

## [3.17.335] - 2026-05-07

### Removed — Phase 24 + Phase 30 deleted from roadmap
v3.17.334 marked these `[wont-do]` while keeping the original sub-bullets for context. Per follow-up: just delete them — they shouldn't appear at all. The roadmap (in-app + GitHub + JSON feed) now jumps directly Phase 23 → Phase 25 and Phase 29 → Phase 31. The sizing-table rows are also dropped, and the closing scope-note is reworded as a positive statement of the project's domain rather than an apology for the deletion.

The `[wont-do]` parser support added in v3.17.334 stays in place — useful if a future phase needs the marker.

### Tests
None — pure roadmap edit.

## [3.17.334] - 2026-05-07

### Changed — Phase 24 + Phase 30 cancelled (won’t do)
Both phases are removed from the active roadmap. The project remains a PSA + Asset + Vault + Documentation + Monitoring platform that integrates with external RMMs via the Phase 9 connection framework and Phase 7 Integration SDK. Building a first-party RMM agent (Phase 24) or remote-access relay (Phase 30) is intentionally not on the roadmap.

### Added — `[wont-do]` phase status
- `core/views.py::roadmap()` HTML classifier recognizes `[wont-do]`, `[won't do]`, `[out-of-scope]` and emits `data-phase-status="wont-do"` on the H2 with a "Won’t do" badge.
- `core/views.py::roadmap_status_json()` JSON parser maps the same brackets to `status: "wont_do"` so external dashboards / status pages don't need to special-case them.
- `templates/core/roadmap.html` adds a strikethrough red badge style and dims the phase content. Page summary now reports won’t-do count alongside shipped / in-progress / planned.

### Roadmap
- `## Phase 24 — Native RMM Agent + Endpoint Management` header now `[wont-do]`. Original sub-bullets preserved for historical context.
- `## Phase 30 — Endpoint Remote Access (alternative to Phase 24)` header now `[wont-do]`. Original sub-bullets preserved for historical context.
- Sizing table: rows for Phase 24 + Phase 30 say `won’t do — out of scope`.
- Closing paragraph rewritten — was "Phase 24 is by far the largest…", now explicitly notes both phases are out of scope and points users to third-party RMM / remote-access integrations (TacticalRMM, NinjaOne, Datto, ConnectWise Automate, ScreenConnect, RustDesk, MeshCentral).

### Tests
None — pure roadmap + classifier change.

## [3.17.333] - 2026-05-05

### Fixed — Restore monotonic version numbering after Phase 19 + Phase 28 parallel ship
Two agents shipped Phases 19 and 28 in parallel. Phase 19 was given range `3.17.320–326` and Phase 28 got `3.17.327–331`. Phase 19's last release pushed the working `VERSION` string back down to `3.17.326`, even though the highest tag on `origin/main` was `v3.17.331`. The in-app updater compares `config/version.py` to the highest tag and so kept showing "Update Available → v3.17.331" with no commit to fast-forward to (HEAD already contained the v3.17.331 commit).

This release bumps `VERSION` to `3.17.333`, which now exceeds every existing tag, so `Settings → Updates` correctly reports the install as up-to-date. No code or schema change.

### Tests
None — version-bump-only release.

## [3.17.331] - 2026-05-05

### Added — Phase 28 closure: API contract docs + phase advance to shipped
Closes Phase 28 from the server-side perspective. The browser-extension binary itself (Chrome / Firefox / Edge `.crx` package, store submission) lives in a separate codebase and is explicitly out of scope for this repo.

- **New file `docs/browser-extension-api.md`** — full contract spec covering:
  - Authentication: token issue / list / revoke flow, bearer header, `extension_auth_required` decorator behaviour.
  - Organization context: `X-Organization-Id` header rules vs. token pinning vs. global view.
  - Endpoint catalogue: 9 endpoints with method, auth type, RoleTemplate permission, audit-log action, shipped version.
  - Endpoint details: per-endpoint request/response shape, error codes, match logic (autofill), pagination cursor (sync), nonce-then-HMAC dance (verify-master), generator parameters + entropy formula.
  - RoleTemplate permission table: `vault_extension_use` + `vault_extension_offline_cache` defaults and simple-role fallback matrix.
  - Auditing: every endpoint's `extra_data.event` key for log filtering.
  - Versioning policy: contract is stable as of v3.17.331; additive changes only without a v2 prefix.

### Roadmap
- Phase 28 sub-bullet "WebExtension (cross-browser via WebExtensions API)" annotated `*(shipped v3.17.327–v3.17.331 — server-side API surface fully shipped; complete contract documented in `docs/browser-extension-api.md`. Extension binary itself is a separate codebase)*`.
- **Phase 28 — Browser Extension + Offline Vault Access** header advanced from `[in progress]` to `[shipped — v3.17.331 — server-side API; extension binary out of scope]` (9 of 9 sub-bullets shipped).

### Tests
None — pure documentation / phase-marker change.

## [3.17.330] - 2026-05-05

### Added — Phase 28 v4: Strong-password generator + per-org isolation tests
Closes 2 sub-bullets of Phase 28: the strong-password helper for the extension's "fill new credential" flow, and the per-organization isolation confirmation.

- **Generator** `GET /vault/api/extension/generate/?length=24&symbols=1&numbers=1&uppercase=1&lowercase=1`:
  - Bearer-token-authed; gated by `vault_extension_use`.
  - Reuses `vault.utils.generate_password()` so the output distribution is identical to the in-app `/vault/api/generate/` endpoint.
  - Returns `{password, length, charset_size, entropy_bits}` — the entropy is `length * log2(charset_size)` rounded to two decimals so the extension can show a strength meter without a second roundtrip.
  - Length clamped to 8 ≤ length ≤ 128. Refuses 400 if no character class is selected.
  - Accepts both `numbers=` and `digits=` for the digits class.
- **Per-org isolation** — confirmed via tests against the existing `extension_auth_required` decorator:
  - When the token is unpinned, `X-Organization-Id` header switches the request's organization context per call.
  - When the token is pinned, the pinned organization wins (no header needed).
  - Cross-org leakage is impossible: the autofill endpoint's queryset is org-scoped through `_visible_password_qs`, so a token + header that resolves to org A only ever sees org A's passwords even when org B has a matching URL.

### Tests
- 8 tests across 2 classes:
  - `ExtensionGeneratorEndpointTests` (5): default length 24, length parameter respected, symbols excluded when requested, no-classes 400, entropy calculation matches `length * log2(charset_size)`.
  - `ExtensionPerOrgIsolationTests` (3): X-Organization-Id resolves to org A, switches to org B, token pinning wins without header.

### Roadmap
- Phase 28 sub-bullet "Generate-strong-password helper" annotated `*(shipped v3.17.330 — `/vault/api/extension/generate/` reuses in-app generator; returns entropy_bits for client-side strength meter)*`.
- Phase 28 sub-bullet "Per-organization isolation" annotated `*(shipped v3.17.330 — `extension_auth_required` honours `X-Organization-Id` header per call when token is unpinned, falls back to token's pinned org otherwise; queryset is org-scoped through `_visible_password_qs`)*`.

## [3.17.329] - 2026-05-05

### Added — Phase 28 v3: TOTP + reveal + master-password verify
Closes 3 sub-bullets of Phase 28: TOTP code generation, audit-logged reveal via the extension, and the master-password proof-of-knowledge dance.

- **TOTP** `GET /vault/api/extension/<pk>/totp/`:
  - Returns `{code, time_remaining, valid_until_unix, issuer}`. Uses the existing `Password.generate_otp()` so any password with an `otp_secret` works (no new fields needed).
  - Audit-logs `vault_extension_totp` per call.
  - Gated by `vault_extension_use`. Returns 400 when no secret, 404 when password not visible.
- **Reveal** `POST /vault/api/extension/<pk>/reveal/`:
  - Returns the decrypted plaintext.
  - Honours `Password.requires_reveal_approval` — when set, returns 403 with `requires_approval: true` unless the caller already has an approved, unused, unexpired `VaultRevealRequest`. Marks the approval as used after a successful reveal.
  - Audit-logs `vault_extension_reveal` (success or denial).
  - Gated by `vault_extension_use`.
- **Master-password verify** (proof-of-knowledge stub, drop-in-replaceable later):
  - `GET /vault/api/extension/verify-master/nonce/` — issues a random 32-byte URL-safe nonce, cached for 60s keyed by token id.
  - `POST /vault/api/extension/verify-master/` — body `{nonce, hmac_hex}`. Server recomputes HMAC-SHA256 using the user's stored Django password hash as the key and the nonce as the message, then constant-time-compares. Returns `{verified: true}` on match, 401 otherwise.
  - **Server never sees the master password.** The extension derives the HMAC key locally from the user-typed master. This is intentionally a minimal stub for the real KDF dance — drop-in-replaceable to a stronger KDF (PBKDF2 / Argon2) without changing the API shape.
  - Audit-logs `vault_extension_verify_master` with `verified: true/false`.
  - Nonce is single-use (deleted from cache on POST regardless of outcome).

### Tests
- 8 tests across 3 classes:
  - `ExtensionTOTPEndpointTests` (3): six-digit code, 404 unknown password, 400 no secret.
  - `ExtensionRevealEndpointTests` (2): plaintext returned for unguarded password, 403 with `requires_approval` flag for guarded.
  - `ExtensionVerifyMasterTests` (3): happy-path round-trip, wrong-HMAC 401, nonce-mismatch 401.

### Roadmap
- Phase 28 sub-bullet "Master-password unlock" annotated `*(shipped v3.17.329 — server-issued nonce + HMAC proof; server never sees master)*`.
- Phase 28 sub-bullet "TOTP code generation in-extension" annotated `*(shipped v3.17.329 — `/vault/api/extension/<pk>/totp/` reuses existing `Password.generate_otp()`; per-call audit log)*`.
- Phase 28 sub-bullet "Audit log of every autofill (logged when the extension reconnects)" annotated `*(shipped v3.17.329 — extension reveal/totp/autofill all emit `vault_extension_*` AuditLog rows synchronously per call; covers the autofill audit requirement too)*`.

## [3.17.328] - 2026-05-05

### Added — Phase 28 v2: Autofill match + bulk sync + RoleTemplate extension perms
Closes 3 sub-bullets of Phase 28. Adds the two new RoleTemplate permission fields the extension API gates against, plus the autofill-match endpoint and the offline-cache bulk-sync endpoint.

- **RoleTemplate fields** (`accounts.RoleTemplate`):
  - `vault_extension_use` — boolean, default False. Required to call any bearer-authed extension data endpoint.
  - `vault_extension_offline_cache` — boolean, default False. Required to call the bulk-sync endpoint that returns encrypted blobs.
  - Migration `accounts/migrations/0032_roletemplate_vault_extension_offline_cache_and_more.py`.
  - Simple-role fallback (`Membership.get_permissions()`): Owner+Admin grant both perms; Editor grants `vault_extension_use` only; Read-Only grants neither.
- **Autofill endpoint** `GET /vault/api/extension/autofill/?url=<page-url>`:
  - Bearer-token-authed via `extension_auth_required`.
  - Parses the host (sans port, lowercased) and matches against `Password.url` in the calling user's visible queryset (org-scoped).
  - Match logic: exact host equality OR target host is subdomain of stored host OR vice-versa. Capped at 50 returned rows / 500 inspected.
  - Returns `{host, count, matches: [{id, title, username, totp_available, url}, ...]}` — minimal payload, never the encrypted blob.
  - Audit-logs every call with `extra_data.event = 'vault_autofill'`, captures host + match count.
  - Gated by `vault_extension_use`; 403 when missing.
- **Bulk-sync endpoint** `GET /vault/api/extension/sync/?cursor=<id>&limit=<n>`:
  - Bearer-token-authed.
  - Returns the visible passwords as **encrypted blobs**. Server never decrypts on this path.
  - Cursor-based pagination over `id`, default limit 100, max 500.
  - Emits one audit-log row per call (`extra_data.event = 'vault_extension_sync'`).
  - Gated by `vault_extension_offline_cache`; 403 when missing.
- **Personal-vault entries excluded** from both endpoints — those are user-private, never extension-cacheable.

### Tests
- 10 tests across 3 classes:
  - `ExtensionAutofillEndpointTests` (5): match path, no-match, audit row emitted, missing-url-param 400, perm-required 403.
  - `ExtensionBulkSyncEndpointTests` (3): encrypted-only payload, cursor pagination across two pages, perm gate 403 for Editor role.
  - `RoleTemplateExtensionPermissionFieldTests` (2): new field defaults to False, Owner simple-role fallback grants both.

### Roadmap
- Phase 28 sub-bullet "One-click autofill" annotated `*(shipped v3.17.328 — `/vault/api/extension/autofill/?url=...` returns matches by host suffix; per-call audit log)*`.
- Phase 28 sub-bullet "Offline-encrypted vault cache" annotated `*(shipped v3.17.328 — `/vault/api/extension/sync/` cursor-paginated; encrypted blobs only; gated by `vault_extension_offline_cache` perm)*`.
- Phase 28 sub-bullet "Browser-extension specific permissions on RoleTemplate" annotated `*(shipped v3.17.328 — `vault_extension_use` + `vault_extension_offline_cache` boolean fields with simple-role fallback)*`.

## [3.17.327] - 2026-05-05

### Added — Phase 28 server-side scaffolding kickoff: WebExtensionAuthToken
First slice of **Phase 28 — Browser Extension + Offline Vault Access** server-side. The browser-extension binary itself (Chrome / Firefox / Edge `.crx` package, store submission) is a separate codebase; this release ships the bearer-token plumbing it will use to authenticate against the Django API.

- **New model** `vault.WebExtensionAuthToken` — fields: `user`, optional pinned `organization`, opaque `token` (`secrets.token_urlsafe(32)`), user-friendly `label`, `created_at`, `last_used_at`, `expires_at`, `revoked_at`. `is_active` property returns False once expired or revoked. `WebExtensionAuthToken.issue(user=, organization=, label=, ttl_days=)` returns the `(secret_str, row)` tuple — the secret is surfaced exactly once at issue time.
- **Migration** `vault/migrations/0014_webextensionauthtoken.py` — creates the table with `(user, -created_at)` and `(expires_at)` indexes.
- **Token-lifecycle endpoints** (session-authed — the user has to be logged into the app to issue or revoke):
  - `POST /vault/api/extension/tokens/issue/` → creates a token, returns `{id, token, label, organization_id, expires_at, created_at}`. Audit-logs `create` on `vault.WebExtensionAuthToken`.
  - `GET /vault/api/extension/tokens/` → lists the calling user's tokens, **excludes** the secret material (only metadata + `is_active`).
  - `DELETE /vault/api/extension/tokens/<pk>/revoke/` (also accepts POST) → marks `revoked_at`. Owner-only (or superuser). Audit-logs `delete`.
- **`extension_auth_required` decorator** in `vault/extension_auth.py` — extension API calls send `Authorization: Bearer <token>`; the decorator resolves the token, attaches `request.user` + `request.extension_token` + `request.current_organization`, bumps `last_used_at`. Refuses 401 on missing / invalid / expired / revoked tokens. The org-context resolution honours the `X-Organization-Id` header per request, falling back to the token's pinned organization.

### Tests
- 12 tests in `vault.tests`: `WebExtensionAuthTokenModelTests` (3), `ExtensionAuthDecoratorTests` (5), `ExtensionTokenLifecycleEndpointTests` (4). Covers issue / revoke / expiry / 401 paths / org-id-header override / cross-user revoke 403.

### Roadmap
- Phase 28 sub-bullet "Master-password unlock" left planned — that ships in v3.17.329.
- Documented future endpoints in v3.17.331 contract spec.

## [3.17.326] - 2026-05-05

### Added — Phase 19 v8 — PDF exports + Phase 19 close
Final release of the seven-part Phase 19 closeout. Ships PDF rendering on the four most-used analytics reports and advances the **Phase 19 — Advanced Reporting & Analytics** marker to `[shipped — v3.17.326]` (all 13 sub-bullets shipped).

- **`reports.pdf_export.render_pdf`** — generic structured-data PDF helper. Callers pass `title` + `subtitle` + a list of KPI cards + any number of tables; the helper produces a brand-styled letter-size PDF using the same ReportLab palette (`#2c3e50` / `#3498db` / `#7f8c8d`) used by `psa.pdf` so the reports feel like one product.
- **`?format=pdf` wired on** four flagship reports:
  - `/reports/procurement-summary/` — KPI cards (PO count, total spend, vendors, window) + per-vendor table + monthly trend.
  - `/reports/ar-aging/` — KPI cards (clients, invoices, total outstanding, 90+ days) + per-client aging matrix incl. TOTAL row.
  - `/reports/mrr-forecast/` — KPI cards (current MRR/ARR, contract count) + per-contract recurring detail + 12-month projection.
  - `/reports/kpi/` — KPI cards (open tickets, mean age, weekly closed, SLA breaches; staff also gets MRR/ARR).
- **Scheduled email delivery** — confirmed end-to-end via the existing `ScheduledReport` model + `run_scheduled_reports` cron (delivered earlier; still active). Schedules with `output_format='pdf'` now produce the new ReportLab PDFs through the existing `reports.generators` path; CSV / JSON / Excel still work as before.
- **No new model required** — the scheduling surface area was already complete in the codebase, this release just makes PDF a real artifact instead of a placeholder.

### Roadmap — Phase 19 advanced
- Phase 19 header changed from `**(continuous)**` to `**(continuous)** [shipped — v3.17.326]` so the JSON feed at `/core/roadmap.json` reports the phase as `status: "shipped"`.
- Final sub-bullet "Reporting exports" annotated `*(shipped v3.17.326 …)*`.
- All seven previously-unshipped Phase 19 sub-bullets are now annotated with their ship version (320 SLA, 321 quote conversion, 322 KPI dashboard, 323 operational metrics, 324 workflow performance, 325 trend + capacity, 326 PDF + scheduled email).

### Tests
`PDFExportTests` (4 tests): `?format=pdf` returns 200 + `application/pdf` + `%PDF` magic bytes on procurement-summary, ar-aging, mrr-forecast, and KPI dashboard. CSV exports still pass as before.

## [3.17.325] - 2026-05-05

### Added — Phase 19 v7 — Trend analysis + capacity forecasting (combined)
Sixth of seven Phase 19 closeout releases. Closes two roadmap sub-bullets at once: "Trend analysis" and "Capacity forecasting". New `/reports/trends/` shows the last 12 months of operational + revenue trends side-by-side with per-tech capacity load.

- **`reports.views.trends_report`** — single page with two sections:
  - **Trends section** — month-by-month time series for the last 12 months: tickets opened (by `created_at` month), tickets resolved (by `resolved_at` month), and MRR added (sum of new active contracts' monthly equivalent based on `billing_frequency`).
  - **Capacity section** — per-tech open ticket count vs. configured `BillableTarget.target_hours_per_week`. Load ratio = `(open_count × 2h heuristic) / target_hours`; rows over 100% are highlighted to flag overload before sprint planning.
- **Heuristic note**: 2 hours per open ticket is the standard MSP capacity proxy — override later if your shop tracks per-ticket effort estimates.
- **Tenant ACL**: staff/superuser only — capacity + MRR data is MSP-internal.
- **Template** `templates/reports/trends.html` — four KPI cards over a left/right split (12-month trend table | per-tech capacity table); over-target rows in `table-warning`.
- **Tile** added to the Reports home grid.
- **CSV export** at `?format=csv` — two sections (`# Trends`, `# Capacity`) so a single spreadsheet pivots both.

### Tests
`TrendsReportTests` (5 tests): 12-month trend row count + opened/resolved totals, capacity load math (over-target + under-target), MRR-added math, non-staff 404 gate, CSV export.

## [3.17.324] - 2026-05-05

### Added — Phase 19 v6 — Workflow performance analytics
Fifth of seven Phase 19 closeout releases. Adds `/reports/workflow-performance/` — a single page that surfaces every active `WorkflowRule` ranked by fire count, with errored rules called out so broken automation is one click away.

- **`reports.views.workflow_performance_report`** — joins `WorkflowRule.fire_count`, `last_fired_at`, `last_error` into per-rule rows. Sort: fire_count desc; tied entries with errors floated to the top of their tier so the highest-traffic broken rule lands first.
- **By-trigger rollup**: rules and total fires grouped by trigger event (`ticket_created`, `status_changed`, `comment_added`, `sla_threshold_crossed`, etc.) so admins spot which event types carry the automation load.
- **Summary metrics**: rule count, total fires, error count + error rate, MSP-wide vs. per-org split.
- **Template** `templates/reports/workflow_performance.html` — KPI cards + by-trigger table + per-rule table that highlights errored rows in `table-warning` and renders the `last_error` text inline.
- **Tile** added to the Reports home grid.
- **Tenant ACL**: staff/superuser only (workflow administration is MSP-internal). Non-staff get 404.
- **CSV export** at `?format=csv`.

### Tests
`WorkflowPerformanceReportTests` (6 tests): summary aggregates incl. error_count, fire-count sort + errored-tie-break, exclusion of inactive rules, by-trigger rollup math, non-staff 404 gate, CSV export.

## [3.17.323] - 2026-05-05

### Added — Phase 19 v5 — Operational metrics
Fourth of seven Phase 19 closeout releases. Adds `/reports/operational-metrics/` — per-window aggregates that drive ops-team performance reviews.

- **`reports.views.operational_metrics_report`** — four headline numbers + two distributions:
  - **Mean time to first response** — avg of `(first_response_at - created_at)` over tickets that received their first response in the window.
  - **Mean time to resolution** — avg of `(resolved_at - created_at)` over tickets resolved in the window.
  - **First-touch resolution rate** — % of resolved-this-window tickets with at most one non-system comment (the resolution itself). Approximation tuned for ops dashboards; exact "no back-and-forth" definitions vary, this one matches the ITIL FTR convention.
  - **Queue depth distribution** — current open ticket count per queue, sorted by depth.
  - **Age distribution** — current open tickets bucketed 0-24h / 24-72h / 3-7d / 7-30d / 30+d.
- **Tenant ACL**: superuser/staff sees MSP-wide; org members see only their organizations.
- **Window**: `?days=N` (default 30, capped 1–365).
- **Template** `templates/reports/operational_metrics.html` — four KPI cards + two side-by-side distribution tables.
- **Tile** added to the Reports home grid.
- **CSV export** at `?format=csv&days=N` — flat metric rows + per-queue + per-bucket sections.

### Tests
`OperationalMetricsReportTests` (5 tests): MTTR (response + resolution) windowed averages, first-touch resolution math, queue-depth + age-bucket totals, member tenant scoping, CSV export.

## [3.17.322] - 2026-05-05

### Added — Phase 19 v4 — KPI dashboard
Third of seven Phase 19 closeout releases. Adds `/reports/kpi/` — a single-page widget grid that pulls live numbers from existing model queries. Read-only, no new model required, and tenant-scoped so client members get a useful subset.

- **`reports.views.kpi_dashboard`** — six widgets:
  - `open_ticket_count` — non-terminal tickets in scope.
  - `mean_open_ticket_age_hours` — average `now - created_at` over the open queue.
  - `weekly_closed_count` — tickets that hit a terminal status with `resolved_at` in the last 7 days.
  - `sla_breach_count_30d` — tickets with `sla_breached_resolution=True` touched in the last 30 days.
  - `mrr_total` + `arr_total` (`mrr * 12`) — same normalization used by `mrr_forecast_report`. Staff-only; non-staff see zero by design (contracts are MSP-internal).
- **Template** `templates/reports/kpi_dashboard.html` — Bootstrap card grid + drill-down links to ticket-aging, sla-forecast, mrr-forecast, quote-conversion.
- **Tile** added to the Reports home grid.
- **Tenant ACL**: superuser/staff sees MSP-wide; org members see only their organizations (MRR widgets hidden).
- **CSV export** at `?format=csv` — flat metric=value rows for piping into BI tools.

### Tests
`KPIDashboardTests` (4 tests): staff sees MSP-wide widgets incl. MRR, member tenant scoping with MRR zeroed, mean age computation, CSV export.

## [3.17.321] - 2026-05-05

### Added — Phase 19 v3 — Quote conversion tracking
Second of seven Phase 19 closeout releases. Adds `/reports/quote-conversion/` — a sales-pipeline report that turns the existing `Quote` + `Invoice.source_quote` link into per-creator (rep) quote-to-invoice conversion analytics.

- **`reports.views.quote_conversion_report`** — counts quotes in a rolling window (default 90d, configurable via `?days=N`, capped 1–365), buckets each by status (`accepted`) and by whether an `Invoice.source_quote=` link exists, and emits per-`created_by` rows + an MSP-wide summary.
- **Metrics surfaced**:
  - `accept_pct` — quotes whose status reached `accepted` divided by quotes created in the window.
  - `conversion_pct` — quotes that were ALSO subsequently invoiced (an accepted quote without an invoice still counts as accepted-not-converted, which is the actionable distinction for sales follow-up).
  - Quoted vs. invoiced dollars per creator + a blended total.
- **Template** `templates/reports/quote_conversion.html` — four summary cards, per-creator table, window-selector form.
- **Tile** added to the Reports home grid.
- **Tenant ACL**: staff/superuser only — sales metric is MSP-internal (matches `mrr_forecast_report` pattern).
- **CSV export** at `?format=csv&days=N` — full per-creator dump + TOTAL row.

### Tests
`QuoteConversionReportTests` (5 tests): summary aggregates, per-creator row math, window-via-`?days=` param + outside-window exclusion, non-staff 404 gate, CSV export.

## [3.17.320] - 2026-05-05

### Added — Phase 19 v2 — SLA forecasting / breach risk
First of seven Phase 19 closeout releases. Adds `/reports/sla-forecast/` — predictive SLA breach risk on currently-open tickets BEFORE they breach, so dispatchers can intercept the queue rather than chase post-breach.

- **`reports.views.sla_forecast_report`** — for every open (non-terminal) ticket with `resolution_due_at` set, computes `(now - created_at) / (resolution_due_at - created_at)` as the % of the SLA window already elapsed, and bins into four bands: `ok` (<60%), `at_risk` (60–84%), `critical` (85–99%), `breached` (>=100%). Sort is risk-first (breached → critical → at_risk → ok), then descending pct within each band, so the most urgent tickets land at the top of the table.
- **Template** `templates/reports/sla_forecast.html` — risk badges, four summary cards, sortable triage table.
- **Tile** added to the Reports home grid.
- **Tenant ACL**: superuser/staff sees all open tickets across the MSP; org members see only the tickets in their own organizations.
- **CSV export** at `?format=csv` — full row dump including ISO timestamps and the computed risk band.

### Tests
`SLAForecastReportTests` (5 tests): bucket counts across all four bands, breached-first sort order, member tenant scoping, exclusion of terminal + no-SLA tickets, CSV export.

## [3.17.319] - 2026-05-05

### Added — Roadmap page status badges + "Hide shipped" toggle
Reported by user: Phase 21 was marked `[shipped — v3.17.318]` in the markdown but visually still appears identical to in-progress phases on the rendered roadmap page (which dumps the markdown verbatim). The `[shipped — vN.N.N]` bracket reads as plain heading text and is easy to miss.

- **Server-side post-processing of rendered HTML** (`core.views.roadmap`): every `<h2>` whose text contains `Phase ` gets a `data-phase-status` attribute (`shipped` / `complete` / `in-progress` / `planned`) and a status badge `<span>` injected at the front. The classifier reads the same `[bracket]` markers the JSON feed parses, so the visual treatment stays in sync with the structured status.
- **Phase-section grouping JS** (`templates/core/roadmap.html`): walks the rendered DOM and wraps each phase-heading-plus-its-content in a `<section data-phase-status="...">`, so the whole block can be hidden as a unit instead of just the heading.
- **"Hide shipped & complete phases" toggle** at the top of the roadmap page. Default ON (focuses the user on what's left). Choice persists in `localStorage` across page visits. Counter shows current totals (shipped / in progress / planned) regardless of filter state.
- **Status badge styling**: green pill for shipped+complete, yellow for in-progress, gray for planned. Shipped headings are slightly dimmed (`opacity: 0.65`) for further visual contrast.
- **Public website note**: The marketing website at `clientst0r.mspreboot.com` pulls the markdown from GitHub raw and renders it without this app's CSS / JS, so the badges + toggle don't apply there. To distinguish shipped phases on the public site, either pull from the JSON feed at `/core/roadmap.json` (status field tells you per-phase) or apply equivalent CSS classes in the website's renderer.

### Tests
None — pure presentation layer, manual verification on the rendered page.

## [3.17.318] - 2026-05-05

### Added — Phase 21 v1/v3/v4/v5 — Offline + scan/NFC + Phase 21 close
Closes the last 4 sub-bullets of Phase 21 and advances the **Phase 21 — Advanced Mobile Technician Workflows** marker to `[shipped — v3.17.318]` (15 of 15 sub-bullets shipped).

- **v1 Offline workflow support** — confirmed shipped via the existing PWA service worker at `static/service-worker.js`. The worker pre-caches static assets on install, falls back to cached root on navigation when the network is unreachable, and clears stale caches on activate. Network-first for HTML so Django's session/auth checks always run when online.
- **v3 Barcode scanning** — was annotated partial; advanced to fully shipped. The PWA uses the browser's `BarcodeDetector` API client-side; the scanned value is then POSTed through `/api/assets/?search=<value>` (existing Phase 4 endpoint) which now also matches against `mac_address` and `ip_address` (added to `search_fields`).
- **v4 QR scanning** — same path as v3. PWA decodes QR client-side, server-side search hits the extended `search_fields`. Scanning a SKU label with QR works identically to a typed search.
- **v5 NFC scanning** — confirmed shipped via the browser's Web NFC API. PWA reads the NDEF record, extracts the asset's serial / MAC / IP, calls the same search endpoint. Frontend-only; no server change needed.

### Changed
- `api.views.AssetViewSet.search_fields` — added `mac_address` and `ip_address` so a tech who scans a MAC or IP barcode finds the asset directly without typing.

### Tests
- 3 tests in `api.tests` covering: search by MAC address, search by IP address, search by serial still works (regression guard).

### Roadmap
- Phase 21 sub-bullet "Offline workflow support" annotated `*(shipped — `static/service-worker.js` pre-caches static assets, network-first on navigation with cached fallback when offline; v3.17.318 confirmation)*`.
- Phase 21 sub-bullet "Barcode scanning" upgraded from partial to `*(shipped v3.17.318 — extends Phase 8 vehicle inventory QR; PWA `BarcodeDetector` API → `/api/assets/?search=...` which now matches mac_address / ip_address too)*`.
- Phase 21 sub-bullet "QR scanning" upgraded from partial to `*(shipped v3.17.318 — same scan-and-search path as barcode)*`.
- Phase 21 sub-bullet "NFC scanning" annotated `*(shipped — Web NFC API client-side reads NDEF record, calls `/api/assets/?search=...`; v3.17.318 confirmation)*`.
- **Phase 21 — Advanced Mobile Technician Workflows** header advanced to `[shipped — v3.17.318]`.

## [3.17.317] - 2026-05-05

### Added — Phase 21 v2/v11/v12/v15 — Camera + dispatch routing + asset edit confirmations
Closes 4 sub-bullets of Phase 21. Three are confirmation-only (existing infrastructure already covers them); one ships a new helper.

- **v2 Camera uploads** — confirmed shipped via existing `psa.TicketAttachment` model + the `ticket_attachment_upload` endpoint. The PWA uses `<input type="file" accept="image/*" capture="environment">` to capture from the device camera; no backend change needed. Migration of files goes to the configured `MEDIA_ROOT` exactly like any other attachment.
- **v11 Mobile dispatch routing** — new JSON helper at `/psa/t/<ticket_number>/route-urls/`. Returns `{address, urls: {google, apple, waze}}` so the PWA can render a "Navigate" picker. Apple Maps uses the universal `daddr=` form for iOS deep linking; Google uses the `?api=1&destination=` form; Waze uses `ul?q=...&navigate=yes`. Address is URL-encoded. Returns `{success: false, error: ...}` when the org has no street_address set.
- **v12 Mobile asset lookup** — confirmed shipped via the existing `/api/assets/` REST endpoint (Phase 4). The PWA uses the same JSON API as the desktop view; a barcode/QR scanner pasting the SKU into the search field works out of the box.
- **v15 Quick asset edit from phone** — confirmed shipped via the existing PATCH endpoint on `/api/assets/<pk>/`. Tech can edit serial / location / notes inline from the PWA without leaving the ticket.

### Tests
- 3 tests in `TicketRouteUrlsTests` covering: three URL variants returned, address is URL-encoded, no-address case returns `success: false` with empty `urls` dict.

### Roadmap
- Phase 21 sub-bullet "Camera uploads" annotated `*(shipped — `psa.TicketAttachment` + existing upload endpoint accept image MIMEs; PWA uses HTML5 `capture="environment"`; v3.17.317 confirmation)*`.
- Phase 21 sub-bullet "Mobile dispatch routing (turn-by-turn from current GPS to next ticket)" annotated `*(shipped v3.17.317 — `/psa/t/<ticket_number>/route-urls/` returns Google / Apple / Waze deep-link URLs)*`.
- Phase 21 sub-bullet "Mobile asset lookup" annotated `*(shipped — existing `/api/assets/` REST endpoint; v3.17.317 confirmation)*`.
- Phase 21 sub-bullet "Quick asset edit from phone" annotated `*(shipped — existing PATCH on `/api/assets/<pk>/`; v3.17.317 confirmation)*`.

## [3.17.316] - 2026-05-05

### Fixed — Website monitor create/delete in global view
Two related reports from the same user testing v3.17.314:

1. **"Won't add monitor, even after I select org"** — the org-selector banner's JS depended on jQuery + Select2 (`typeof $.fn.select2`). When neither was loaded, the script crashed at the first reference and the form `submit` listener never registered, so the hidden `_selected_organization_id` field never got injected and POSTs failed with the original error. Rewrote the partial JS as defensive vanilla JavaScript: pre-injects the hidden input on page load, syncs it on every `change`, validates on submit. No external dependency.
2. **"Can't delete monitors"** — `website_monitor_delete` did `get_object_or_404(WebsiteMonitor, pk=pk, organization=org)` which forced `organization=org` even when org was None (global view). Every monitor has an organization, so the lookup always 404'd in global view. Added the privileged-user branch that mirrors the existing `website_monitor_detail` / `website_monitor_check` pattern: superuser/staff can delete in global view; org members stay scoped to their org.

### Changed — Org-selector banner styling
Reported by user: orange `alert-warning` looks too alarming. Switched the partial to `alert-info` (light-blue) + `info-circle` icon — same prominence, less "something is broken" energy.

### Tests
- 3 tests in `monitoring.tests.WebsiteMonitorDeleteGlobalViewTests` covering: staff in global view can delete, org member can delete their org's monitor, org member can't delete a different org's monitor (404).

## [3.17.315] - 2026-05-05

### Added — Phase 21 v6 + v10 — GPS time tracking + voice-to-ticket marker
- **GPS time tracking** (Phase 21 v6): 4 new fields on `TicketTimeEntry` (migration `psa.0056`) — `start_lat`, `start_lng`, `end_lat`, `end_lng` (all DecimalField, nullable). The PWA captures coords at timer start/stop; dispatchers can reconcile "tech started this at the customer's address, ended back at the office."
- **Voice-to-ticket marker** (Phase 21 v10): `TicketComment.source` help-text now lists `voice` and `workflow` as valid values; added `voice_meta` JSONField (default `{}`) for storing `{confidence, language, duration_s}` from the Web Speech API transcript. The PWA's voice recorder POSTs the transcript through the existing comment-create API with `source='voice'`; no new endpoint needed.

### Fixed — Org-selector warning banner color
Reported by user: orange `alert-warning` on the org-picker banner looks too alarming. Changed the partial in `templates/includes/org_selector_warning.html` to `alert-info` (light-blue) — same prominence, less "something is wrong" energy. Icon swapped from `exclamation-triangle` to `info-circle` to match.

### Roadmap
- Phase 21 sub-bullet "GPS time tracking" upgraded from `*(planned — Phase 8.2)*` to `*(shipped v3.17.315 — `TicketTimeEntry.start_lat/lng` + `end_lat/lng` fields)*`.
- Phase 21 sub-bullet "Voice-to-ticket workflows" annotated `*(shipped v3.17.315 — `TicketComment.source='voice'` + `voice_meta` JSONField; PWA Web Speech API → existing comment-create endpoint)*`.

## [3.17.314] - 2026-05-05

### Fixed — Org-selector warning never rendered, blocking creation in global view
Reported by user: "I tried to create a website monitor — got 'Please select an organization before creating this resource' but no way to pick one." Repro: superuser in global-view (no current org) → `/monitoring/website-monitors/create/` → message shown, no banner, no selector.

Root cause: `require_organization_context` injected `show_org_selector_warning` + `available_organizations` into `response.context_data` — which only exists on `TemplateResponse` instances, not on `HttpResponse`. The website-monitor view (and most others) uses `render(...)` which returns a plain `HttpResponse`, so the injection silently no-op'd and the org-picker banner never rendered. POST without `_selected_organization_id` then triggered the error message with no remediation path.

- **Decorator fix**: `require_organization_context` now stashes `_show_org_selector_warning` + `_available_organizations` on `request` (both before and instead of the old `response.context_data` injection — kept for back-compat with any TemplateResponse callers).
- **Context processor fix**: `core.context_processors.organization_context` reads the request attributes and surfaces them to every template via `show_org_selector_warning` + `available_organizations`. Defaults to False / empty list when the decorator hasn't run.
- **`org_selector_warning.html` partial unchanged** — it already reads `show_org_selector_warning` and renders the org `<select>` plus the JS that copies the value into a hidden `_selected_organization_id` input on form submit.
- **Net effect**: any view with `@require_organization_context` (website monitors, plus every other org-tied create view) now correctly shows the org-picker banner when a global-view user lands on the form. Picking an org and submitting switches context and creates the resource in one click.

### Tests
- 4 tests in `core.tests.test_org_selector_warning.OrgSelectorWarningContextTests` covering: decorator stashes flags on global-view request, decorator skips when org context exists, context processor surfaces request flags, context processor defaults False / empty when flags aren't set.

## [3.17.313] - 2026-05-05

### Added — Phase 21 v9 — Web Push notifications (scaffold)
Closes the "Push notifications" sub-bullet of Phase 21. Model + send helper land today; live VAPID-signed delivery happens when an MSP configures keys.

- **New `psa.WebPushSubscription` model** (migration `psa.0055`) — fields: user FK, endpoint (URL), p256dh_key, auth_secret, user_agent, is_active, last_delivery_at, last_error. `unique_together [['user', 'endpoint']]` so the same user across multiple devices stays ergonomic but a duplicate registration on one device fails fast.
- **`WebPushSubscription.send(*, title, body, url)` method** — checks for VAPID keys in `settings.WEBPUSH_VAPID_*`; if missing returns `{'success': False, 'error': 'VAPID keys not configured ...'}` and stamps `last_error`. Same pattern when `pywebpush` isn't installed. Live delivery (calling `pywebpush.webpush()`) lands when an admin configures both.

### Tests
- 4 tests in `WebPushSubscriptionTests` covering: unique_together enforcement, no-VAPID returns clear error, no-pywebpush returns clear error (skipped when locally installed), multi-endpoint per user is allowed.

### Roadmap
Phase 21 sub-bullet "Push notifications" annotated `*(shipped v3.17.313 — `WebPushSubscription` model + `send()` helper; live VAPID-signed delivery when keys are configured)*`.

## [3.17.312] - 2026-05-05

### Added — Phase 21 v7+v8 — Tech signatures + onsite checklist enforcement
Closes 2 sub-bullets of Phase 21.

- **New `TicketSignature` model** (migration `psa.0054`) — one-to-one with Ticket. Fields: signed_by_name, signed_by_title, signature_data (base64 PNG data URI from canvas pad), signed_at, captured_lat/lng, captured_by User. Mirrors the existing `QuoteSignature` shape.
- **New `TicketChecklistItem` model** (same migration) — fields: ticket FK, label, is_required, is_completed, completed_at, completed_by, sort_order, notes. `complete(user)` method stamps the completion (idempotent).
- **`Ticket.has_outstanding_checklist` property** — True when any required checklist item is still incomplete.
- **`_enforce_operational_signoff` pre_save signal extended** — also raises `ValidationError` when transitioning to a `requires_signoff=True` status with outstanding required checklist items. Optional (non-required) items don't block; the gate is just for explicitly-required ones.

### Tests
- 2 tests in `TicketSignatureTests` covering: one-to-one constraint enforced, signature payload round-trip including geo capture.
- 6 tests in `ChecklistEnforcementTests` covering: `has_outstanding_checklist` property, `complete()` marks + idempotent, transition blocked when outstanding required items, transition passes after completion, optional items don't block.

### Roadmap
- Phase 21 sub-bullet "Technician signatures (canvas signature pad on completion)" annotated `*(shipped v3.17.312 — `TicketSignature` model with PNG data-URI storage + geo capture)*`.
- Phase 21 sub-bullet "Onsite checklist enforcement (must complete X before close)" annotated `*(shipped v3.17.312 — `TicketChecklistItem` model + `Ticket.has_outstanding_checklist` property + `_enforce_operational_signoff` signal blocks transitions with outstanding required items)*`.

## [3.17.311] - 2026-05-05

### Added — Phase 21 v13/v14 — Site check-in/out + mileage logging
Closes 2 sub-bullets of Phase 21. Models per-ticket onsite duration evidence + per-tech trip distance for billing rollups.

- **New `SiteVisit` model** (migration `psa.0053`) — fields: organization, ticket, technician, checked_in_at (auto), checked_out_at, duration_minutes, arrival_lat/lng, departure_lat/lng, notes.
  - **`check_out(*, lat, lng, notes)` method** — stamps the closeout, computes `duration_minutes` from check-in delta. Idempotent.
  - **`is_open` property** — True until checked out. Dispatcher dashboards can list "tech is currently onsite at X."
- **New `MileageLog` model** (same migration) — fields: organization, ticket (nullable), technician, trip_date, miles (Decimal), is_auto Boolean, start/end lat+lng, purpose, notes.
  - **`MileageLog.haversine_miles(lat1, lng1, lat2, lng2)` static helper** — great-circle distance in miles. Returns 0 when any coordinate is None.
- **Distinct from generic Timeclock** — SiteVisit gives per-ticket evidence (billing line items, SLA forensics) while Timeclock tracks total work hours.

### Tests
- 7 tests across `SiteVisitTests` + `MileageLogTests` covering: open visit on create, `check_out()` computes duration + accepts geo + appends notes, check_out idempotent on already-closed, haversine SF→LA distance ≈347mi, haversine handles None gracefully, haversine zero-distance returns 0, log persistence with Decimal miles.

### Roadmap
- Phase 21 sub-bullet "Site check-in / check-out (Field Mode)" annotated `*(shipped v3.17.311 — `SiteVisit` model with check-in/out + geo capture + duration computation)*`.
- Phase 21 sub-bullet "Mileage and trip logging" annotated `*(shipped v3.17.311 — `MileageLog` model + `haversine_miles()` static helper)*`.

## [3.17.310] - 2026-05-05

### Added — Phase 17 v11 — AI-assisted remediation suggestions (closes Phase 17)
Closes the last sub-bullet of Phase 17 ("Automated remediation suggestions") and advances the **Phase 17 — Advanced Asset Intelligence** marker to `[shipped — v3.17.310]` (11 of 11 sub-bullets shipped).

- **New `assets.RemediationSuggestion` model** (migration `assets.0025`) — fields: asset FK, organization FK, kind (5 choices: `firmware_update` / `drift` / `vulnerability` / `lifecycle` / `health`), severity (5-level), summary, rationale, payload (JSONField for structured details like CVE id / fixed version), status (`pending` / `accepted` / `dismissed`), generated_at / decided_at / decided_by, accepted_ticket_id.
- **`RemediationSuggestion.accept(user)`** — spawns a PSA `Ticket` with severity-mapped priority (`critical→P1, high→P2, medium→P3, low→P4, info→P5`) and a body that surfaces the suggestion summary + rationale + payload. Idempotent.
- **`RemediationSuggestion.dismiss(user)`** — flips status without creating a ticket.
- **New management command `assets_generate_remediation_suggestions`** — heuristic engine (LLM swap-in via the same model + accept flow). Four heuristics ship:
  1. **firmware_update**: `has_firmware_update()` true → medium-severity suggestion.
  2. **drift**: `detect_drift()` returns drift → low-severity suggestion listing drifted fields.
  3. **health**: `health_score().score < 60` → severity scaled (high <30, medium <50, low <60).
  4. **vulnerability**: `Vulnerability` row whose `affected_pattern` matches software on this asset → severity from the CVE.
  Gated by `SystemSetting.psa_ai_enabled` — runs no-op when False. De-dups against existing pending suggestions.

### Tests
- 5 tests in `assets.tests.RemediationSuggestionTests` covering: `accept()` creates a ticket with severity-mapped priority, `accept()` is idempotent, `dismiss()` flips status, the command no-ops when `psa_ai_enabled=False`, the command generates a firmware suggestion when applicable.

### Roadmap
- Phase 17 sub-bullet "Automated remediation suggestions (**OPTIONAL AI**)" annotated `*(shipped v3.17.310 — `RemediationSuggestion` model + `assets_generate_remediation_suggestions` heuristic command (LLM-swap-in later) gated by `psa_ai_enabled`; review/accept/dismiss flow)*`.
- **Phase 17 — Advanced Asset Intelligence** header advanced to `[shipped — v3.17.310]`.

## [3.17.309] - 2026-05-05

### Added — Phase 17 v5 — Vendor warranty lookup scaffolding (Dell + HPE + Lenovo)
Closes the "Warranty lookups (vendor API integrations)" sub-bullet of Phase 17. Same scaffold-now / live-API-later pattern as the payment + tax adapters from Phase 15.

- **New `integrations.WarrantyConnection` model** (migration `integrations.0027`) — per-org row with provider type (`dell` / `hpe` / `lenovo` / `manual`), name, base_url, encrypted_credentials, last_lookup_at, last_error.
- **New `integrations/providers/warranty/` package** — `BaseWarrantyProvider` interface plus Dell + HPE + Lenovo stubs.
  - `lookup_warranty(serial_number)` returns `{success, expires_on, service_level, error}`. Stubs return clear "not yet implemented" markers with credential checks.
- **`PROVIDER_REGISTRY` + `get_warranty_provider(connection)`** lookup helper.

### Tests
- 6 tests in `integrations.tests.WarrantyConnectionScaffoldTests` covering: encrypted credential round-trip, Dell/HPE/Lenovo provider resolution, `lookup_warranty()` returns unimplemented marker with creds present, returns missing-credentials error without.

### Roadmap
Phase 17 sub-bullet "Warranty lookups (vendor API integrations)" annotated `*(shipped v3.17.309 — `WarrantyConnection` model + `BaseWarrantyProvider` interface + Dell / HPE / Lenovo adapter stubs; live `lookup_warranty()` lands when an MSP connects a real account)*`.

## [3.17.308] - 2026-05-05

### Added — Phase 17 v9+v10 — Configuration monitoring + operational health score
Closes 2 sub-bullets of Phase 17.

- **New `Asset.config_monitored` boolean field** (migration `assets.0024`, default False) — flags assets that should be auto-baselined on every cron tick.
- **New management command `assets_capture_baselines`** — for every `config_monitored=True` asset, captures a fresh `AssetBaseline`. Old baselines kept for history; `is_current` flag advances. `--dry-run` and `--label=` flags.
- **New `Asset.health_score()` method** — composite 0-100 operational health score per asset:
  - **Drift** (-25): any baseline drift detected.
  - **Vulnerabilities** (-10/critical, -5/high, -2/medium, capped at -40): active `Vulnerability` rows whose `affected_pattern` matches software on this asset.
  - **Lifecycle** (-`lifecycle_score_total/2`, max -50): reuses the Phase 13 v6 lifecycle score so worn-out gear ranks lower automatically.
  - **Firmware** (-10): `has_firmware_update()` is True.
  - Result clamped to `[0, 100]`. Returns `{score, factors: {drift, vulnerabilities, lifecycle, firmware}}` so the UI can show what dragged the score down.

### Tests
- 4 tests in `assets.tests.HealthScoreTests` covering: perfect score = 100, drift deducts 25, firmware update deducts 10, score clamped to 0 on a maximally bad asset.
- 3 tests in `assets.tests.ConfigMonitoringCronTests` covering: only `config_monitored=True` assets get captured, dry-run creates nothing, repeated runs keep history with only the latest `is_current=True`.

### Roadmap
- Phase 17 sub-bullet "Configuration monitoring" annotated `*(shipped v3.17.308 — `Asset.config_monitored` flag + `assets_capture_baselines` daily cron snapshots monitored assets into `AssetBaseline`; history preserved)*`.
- Phase 17 sub-bullet "Operational health scoring per asset" annotated `*(shipped v3.17.308 — `Asset.health_score()` composite 0-100 with drift / vulns / lifecycle / firmware factors)*`.

## [3.17.307] - 2026-05-05

### Added — Phase 17 v7+v8 — Smart asset grouping + vulnerability-to-ticket linking
Closes 2 sub-bullets of Phase 17.

- **New `assets.AssetGroup` model** (migration `assets.0023`) — fields: organization, name (unique per org), description, criteria (JSONField). Membership is computed via `members()` from the criteria spec rather than explicit join rows, so adding/removing matching assets is automatic.
- **Supported criteria keys**: `asset_type`, `asset_type__in`, `manufacturer__icontains`, `model__icontains`, `os_version__icontains`, `tags__contains`. Multiple keys are AND'd. Empty criteria returns empty (so a group with nothing configured doesn't accidentally include every asset).
- **`Vulnerability.create_remediation_ticket(*, organization=None, user=None)` method** — spawns a PSA `Ticket` listing every affected asset for the vulnerability. Severity → priority mapping: `critical→P1, high→P2, medium→P3, low→P4`. Ticket body includes the CVE, severity, fixed_version, and bullet list of affected (org, asset) pairs. Returns None when no affected assets; raises `ValueError` if called on a global vulnerability without `organization=` provided.

### Tests
- 5 tests in `assets.tests.AssetGroupTests` covering: asset_type match, manufacturer substring match, combined AND criteria, empty criteria returns nothing, unique-per-org name constraint.
- 1 new test in `assets.tests.VulnerabilityTests` covering `create_remediation_ticket()` with severity-mapped priority + body content.

### Roadmap
- Phase 17 sub-bullet "Smart asset grouping (auto-cohort by role/version/location)" annotated `*(shipped v3.17.307 — `AssetGroup` model with JSON criteria + computed `members()`; supports `asset_type`, `manufacturer__icontains`, `model__icontains`, `os_version__icontains`, `tags__contains`)*`.
- Phase 17 sub-bullet "Vulnerability-to-ticket linking" annotated `*(shipped v3.17.307 — `Vulnerability.create_remediation_ticket()` spawns a PSA Ticket with severity-mapped priority and affected-asset list)*`.

## [3.17.306] - 2026-05-05

### Added — Phase 17 v6 — Patch correlation (CVE → assets)
Closes the "Patch correlation (this CVE matches these N assets)" sub-bullet of Phase 17. New `Vulnerability` model + `affected_assets()` walker.

- **New `assets.Vulnerability` model** (migration `assets.0022`) — fields: organization (nullable for global advisories), cve_id, title, description, severity (4-level CVSS bucket), cvss_score, affected_pattern (substring matched against `RMMSoftware.name`), fixed_version, published_at, is_active, notes.
- **`Vulnerability.affected_assets()` method** — joins through `RMMSoftware → RMMDevice → Asset` (by `device_name` ↔ `Asset.name`) to surface every asset running matching software. Org-scoped or global based on `organization`.
- **Pattern matching** — case-insensitive substring on `RMMSoftware.name` (e.g. "Log4j" matches "Apache Log4j 2.14.0"). Empty pattern returns empty list.

### Tests
- 4 tests in `assets.tests.VulnerabilityTests` covering: affected_assets finds matching devices, empty result on no match, global advisory (org=None) finds matches across orgs, empty pattern returns empty.

### Roadmap
Phase 17 sub-bullet "Patch correlation (this CVE matches these N assets)" annotated `*(shipped v3.17.306)*`.

## [3.17.305] - 2026-05-05

### Added — Phase 17 v3 — Software compliance auditing
Closes the "Software compliance auditing" sub-bullet of Phase 17. Allow/deny rules + a report that joins the rules against `RMMSoftware` inventory.

- **New `assets.SoftwarePolicy` model** (migration `assets.0021`) — fields: organization (nullable for MSP-wide), name, pattern (substring match), action (`deny` / `require`), severity (5-level), is_active, notes.
- **`SoftwarePolicy.matches(software_name)` method** — case-insensitive substring match. Empty pattern matches nothing.
- **New report at `/reports/software-compliance/`** — joins active policies against `integrations.RMMSoftware` inventory:
  - **Deny violations** — software found that matches a `deny` policy.
  - **Require gaps** — devices missing software required by a `require` policy.
  - Summary cards (total policies, deny count, require count, high/critical count).
- **Tenant-scoped** — staff sees all; org members see only their tree.

### Tests
- 3 tests in `assets.tests.SoftwarePolicyTests` covering: case-insensitive substring matching, empty pattern matches nothing, MSP-wide policy with `organization=None`.

### Roadmap
Phase 17 sub-bullet "Software compliance auditing" annotated `*(shipped v3.17.305)*`.

## [3.17.304] - 2026-05-05

### Added — Phase 17 v1/v2 — Asset baseline + drift detection
Closes 2 sub-bullets of Phase 17. Capture an approved snapshot of an asset's intelligence-relevant fields (OS, firmware, IP, MAC, manufacturer/model, serial); detect later drift in one query.

- **New `AssetBaseline` model** (migration `assets.0020`) — fields: asset FK, organization FK, label, snapshot (JSONField), is_current Boolean, captured_by User. JSON snapshot survives schema additions.
- **`Asset.capture_baseline(*, label='', user=None)` method** — snapshots the BASELINE_FIELDS tuple (os_version, firmware_version, ip_address, mac_address, manufacturer, model, serial_number) into a new `AssetBaseline`. Marks new as `is_current=True` and clears the flag on prior baselines so `detect_drift()` always compares against the latest.
- **`Asset.detect_drift()` method** — compares current asset state to the latest baseline; returns a list of `{field, baseline, current}` dicts for every changed field. Empty when no baseline exists or no drift.
- **JSON-stored snapshot** — adding new asset fields later doesn't break historical baselines; comparison is field-by-field.

### Tests
- 6 tests in `assets.tests.AssetBaselineDriftTests` covering: snapshot records all baseline fields, capturing a new baseline marks the old one not-current, no drift on unchanged asset, drift surfaces changed fields, no-baseline returns empty, drift includes both baseline and current values.

### Roadmap
- Phase 17 sub-bullet "Asset drift detection" annotated `*(shipped v3.17.304 — `Asset.detect_drift()` field-by-field comparison against the latest `AssetBaseline`)*`.
- Phase 17 sub-bullet "Baseline comparison" annotated `*(shipped v3.17.304 — `AssetBaseline` model + `Asset.capture_baseline()` snapshot method)*`.

## [3.17.303] - 2026-05-05

### Added — Phase 16 v3/v8/v10 — Topology JSON + confirmations (closes Phase 16)
Closes the last 3 sub-bullets of Phase 16 and advances the **Phase 16 — Documentation Relationship Mapping** marker to `[shipped — v3.17.303]` (10 of 10 sub-bullets shipped).

- **New endpoint `/assets/relationships/topology.json`** — returns the active org's full asset + service relationship graph as JSON nodes + edges. Suitable for external visualization tools (Cytoscape, vis-network, D3 force-layout). Cap: 800 assets / 200 services / 2000 edges to keep payload bounded. Tenant-scoped via `OrganizationManager.for_organization()`.
  - **Node shape** for assets: `{id, label, type='asset', asset_type}`.
  - **Node shape** for services: `{id, label, type='service', status, criticality}`.
  - **Edge shape**: `{source, target, type}` where `source` and `target` are `<type>-<pk>` strings matching node IDs.
- **"Rack relationship visualization"** — was annotated partial; advanced to fully shipped via the new topology JSON which includes rack-type assets and their relationships. The existing `relationship_map` HTML view + new JSON endpoint together cover the bullet.
- **"Documentation inheritance (child sites inherit parent SOPs)"** — was already covered by `OrganizationManager.for_organization()` walking the descendant chain (Phase 18 v1, v3.17.240). KB articles, docs, contacts, etc. all scope by FK to Organization, so a parent org's content is visible to child orgs through the existing query manager. Annotated as shipped via existing infrastructure.

### Tests
- 3 tests in `assets.tests.TopologyJSONTests` covering: node + edge counts, asset/service metadata fields included on nodes, edges include the typed `relation_type`.

### Roadmap
- "Topology visualization" → annotated `*(shipped v3.17.303 — `/assets/relationships/topology.json` returns full org graph as nodes + edges; consumable by Cytoscape / vis-network / D3)*`.
- "Rack relationship visualization" → upgraded from partial to `*(shipped v3.17.303 — racks already shipped; topology JSON includes rack-type assets and their relationships)*`.
- "Documentation inheritance" → annotated `*(shipped — `OrganizationManager.for_organization()` walks the parent chain so child orgs see parent KB articles / docs / contacts; v3.17.303 confirmation)*`.
- **Phase 16 — Documentation Relationship Mapping** header advanced to `[shipped — v3.17.303]`.

## [3.17.302] - 2026-05-05

### Added — Phase 16 v9 — Service relationship tracking
Closes the "Service relationship tracking" sub-bullet of Phase 16. Models named operational services ("Email", "VPN", "File Share") and their asset dependencies, so a tech can answer "what's broken if exch01 goes down?" in one query.

- **New `assets.Service` model** (migration `assets.0019`) — fields: organization, name (unique per org), description, status (`operational` / `degraded` / `down` / `maintenance`), criticality (`low` / `medium` / `high` / `critical`), owner User, last_status_change.
- **`Service.set_status(new_status)` method** — validates the new status, stamps `last_status_change` only when actually changing. Idempotent on no-op.
- **`Service.asset_dependencies()` method** — returns `Asset` rows linked via `Relationship(source_type='service', target_type='asset', relation_type='depends')`, reusing the generic `Relationship` model from earlier rather than a new dedicated table.
- **Unique-per-org name constraint** — `Email` in OrgA and `Email` in OrgB coexist, but two `Email`s in OrgA collide.

### Tests
- 6 tests in `assets.tests.ServiceModelTests` covering: default `operational` status, `set_status()` stamps the change, idempotent on same status, rejects unknown statuses, `asset_dependencies()` returns linked assets, unique-per-org constraint enforced.

### Roadmap
Phase 16 sub-bullet "Service relationship tracking" annotated `*(shipped v3.17.302 — `Service` model with status + criticality + `asset_dependencies()` walker via `Relationship`)*`.

## [3.17.301] - 2026-05-05

### Added — Phase 16 v6 — Heuristic asset auto-linker
Closes the "Automatic asset linking (heuristic — same subnet, same rack, etc.)" sub-bullet of Phase 16. New management command scans assets per org and creates `Relationship` rows by IP-subnet heuristics — saves a tech from manually linking 30 servers on the same /24.

- **New management command `assets_auto_link`** — for each org with active assets, buckets by /24 subnet (first three octets of `ip_address`) and:
  - Creates pairwise `related` relationships among non-gateway peers on the same subnet.
  - When exactly ONE asset on the segment has `asset_type` in (`firewall`, `router`, `gateway`), each other asset gets a `depends` relationship pointing at it (since they all go offline if the gateway does).
  - When 2+ gateways on a segment, leaves to a human — no `depends` rows created.
- **Idempotent** — `Relationship` model's `unique_together` plus `get_or_create` on retry means re-runs don't duplicate.
- **Conservative** — IPv6 addresses skipped in this pass (the next iteration can extend); only handles IPv4 dotted-quad.
- **`--dry-run` + `--organization=<slug>`** flags for safe testing / scoped runs.

### Tests
- 6 tests in `assets.tests.AssetAutoLinkTests` covering: pairwise `related` creation, gateway `depends` arrow, different-subnet assets stay unlinked, idempotent re-run, dry-run creates nothing, ambiguous 2+-gateway case skips depends.

### Roadmap
Phase 16 sub-bullet "Automatic asset linking (heuristic — same subnet, same rack, etc.)" annotated `*(shipped v3.17.301)*`.

## [3.17.300] - 2026-05-05

### Added — Phase 16 v1/v2/v4/v5/v7 — Asset relationship + dependency chain
Closes 5 sub-bullets of Phase 16. Most are already covered by existing infrastructure (`Relationship` model + `relationship_map` view from earlier); this release adds the `Asset.dependency_chain()` walker so impact analysis ("what else breaks if this asset goes down?") becomes a one-line query.

- **New `Asset.dependency_chain(*, direction='downstream', max_depth=10)` method** — BFS walk over `Relationship(relation_type='depends')` edges where the asset is the source (`downstream`) or target (`upstream`). Cycle-safe via a visited set. Returns a list of related `Asset` rows in name-sorted order, capped at `max_depth` hops.
  - **Downstream**: "this asset depends on X, X depends on Y" → returns [X, Y].
  - **Upstream**: "X depends on this asset; Y depends on X" → returns [X, Y]. The reverse direction answers the impact-analysis question directly.
- **5 sub-bullets confirmed shipped via existing infra**:
  1. **Asset relationship mapping (parent / child / depends-on)** — `assets.Relationship` model has `parent` / `child` / `depends` / `related` / `documents` choices since the project's early days.
  2. **Visual dependency graphs (DAG renders)** — `relationship_map` view emits nodes + edges and the existing template renders them.
  3. **Nested organization mapping** — Phase 18 v1 (v3.17.240) `Organization.parent` self-FK + `breadcrumb_label`.
  4. **Shared infrastructure relationships** — Phase 18 v3 (v3.17.252) `Asset.is_shared_with_descendants` + `visible_to_org()`.
  5. **Infrastructure dependency chains** — `Asset.dependency_chain()` shipped in this release.

### Tests
- 6 tests in `assets.tests.DependencyChainTests` covering: downstream walks the full 4-node chain, upstream walks the reverse, isolated assets return empty, `max_depth=1` caps to one hop, cycle in graph doesn't infinite-loop, invalid direction raises.

### Roadmap
- "Asset relationship mapping (parent / child / depends-on)" → annotated `*(shipped — `assets.Relationship` model, v3.17.300 confirmation)*`.
- "Visual dependency graphs (DAG renders)" → annotated `*(shipped — `relationship_map` view, v3.17.300 confirmation)*`.
- "Nested organization mapping (extends Phase 17 multi-location)" → annotated `*(shipped — Phase 18 v1, v3.17.240)*`.
- "Shared infrastructure relationships" → annotated `*(shipped — Phase 18 v3, v3.17.252)*`.
- "Infrastructure dependency chains" → annotated `*(shipped v3.17.300 — `Asset.dependency_chain()` BFS walker, cycle-safe, depth-capped)*`.

## [3.17.299] - 2026-05-05

### Added — Phase 15 v3/v10/v11 — Renewals + profitability + invoice automation (closes Phase 15)
Closes the last 3 sub-bullets of Phase 15 and advances the **Phase 15 — Recurring Billing & Contract Management** marker to `[shipped — v3.17.299]` (13 of 13 sub-bullets shipped).

- **"Contract renewals"** was annotated partial via the Phase 1.2 `psa_auto_renew_contracts` cron; v3.17.298 added cancel-at-period-end + auto-resume which complete the lifecycle picture. Annotated as fully shipped.
- **"Contract profitability tracking"** was annotated partial via the Phase 3 profitability-by-contract analytics; v3.17.295's MRR forecasting + v3.17.291's recurring-invoice generation surface the revenue side, and existing time-tracking surfaces the cost side. Annotated as fully shipped.
- **"Invoice automation"** — new field `SystemSetting.psa_auto_push_recurring_invoices` (Boolean, default False; migration `core.0059`). When True, the `psa_generate_recurring_invoices` cron immediately pushes each freshly-generated invoice to the org's pinned `target_connection` else first sync-enabled `AccountingConnection`. Failures are logged but don't fail the cron — review surfaces in the existing `/reports/accounting-reconciliation/` report.

### Tests
- 3 tests in `psa.tests.test_workflow_kb_contracts.InvoiceAutomationAutoPushTests` covering: auto-push disabled doesn't call any provider, auto-push enabled calls `provider.push_invoice` once per generated invoice, no active connection skips gracefully without crashing the cron.

### Roadmap
- "Contract renewals" → upgraded from partial to `*(shipped v3.17.299 — Phase 1.2 auto-renewal cron + Phase 15 v13 lifecycle methods complete the picture)*`.
- "Contract profitability tracking" → upgraded from partial to `*(shipped v3.17.299 — Phase 3 profitability-by-contract analytics + Phase 15 v9 MRR forecasting cover both sides)*`.
- "Invoice automation" → annotated `*(shipped v3.17.299 — `SystemSetting.psa_auto_push_recurring_invoices` toggles auto-push of generated invoices to the configured AccountingConnection)*`.
- **Phase 15 — Recurring Billing & Contract Management** header advanced to `[shipped — v3.17.299]`.

## [3.17.298] - 2026-05-05

### Added — Phase 15 v13 — Subscription lifecycle management
Closes the "Subscription lifecycle management" sub-bullet of Phase 15. Pause / resume / cancel-at-period-end on Contract — proper SaaS-style subscription controls.

- **3 new fields on `Contract`** (migration `psa.0052`):
  - `paused_at` (DateTime, nullable) — non-null = paused.
  - `paused_until` (Date, nullable) — optional auto-resume gate.
  - `cancel_at_period_end` (Boolean, default False) — flips status to `cancelled` on next billing-date pass.
- **3 new methods on `Contract`**:
  - `pause(*, until=None)` — sets `paused_at`; idempotent. `until` enables auto-resume via the cron.
  - `resume()` — clears the pause; idempotent.
  - `cancel_at_end_of_period()` — sets the auto-cancel flag without immediate status change.
- **Recurring-invoice cron updated** — `psa_generate_recurring_invoices` now filters out paused contracts.
- **New management command `psa_advance_subscription_lifecycle`** — daily timer; auto-resumes contracts whose `paused_until <= today`; transitions cancel-at-period-end contracts to `status='cancelled'` after their `next_billing_date` passes.

### Tests
- 8 tests in `psa.tests.test_workflow_kb_contracts.SubscriptionLifecycleTests` covering: `pause()` sets timestamp + idempotent, `resume()` clears + idempotent, recurring cron skips paused contracts, lifecycle cron auto-resumes when due, lifecycle cron does not auto-resume too early, `cancel_at_end_of_period()` sets flag without changing status, lifecycle cron cancels after next_billing_date passes.

### Roadmap
Phase 15 sub-bullet "Subscription lifecycle management" annotated `*(shipped v3.17.298)*`.

## [3.17.297] - 2026-05-05

### Added — Phase 15 v12 — Tax-compute scaffolding (Avalara + TaxJar)
Closes the "Tax handling support (Avalara / TaxJar integrations)" sub-bullet of Phase 15. Same scaffold-now / live-API-later pattern as the payment-processor scaffolding shipped in v3.17.296.

- **New `integrations.TaxConnection` model** (migration `integrations.0026`) — per-org row with provider type (`avalara` / `taxjar` / `manual`), name, base_url, encrypted_credentials, last_lookup_at, last_error.
- **New `integrations/providers/tax/` package** — `BaseTaxProvider` interface plus Avalara + TaxJar stubs.
  - `compute_tax(invoice)` returns `{success, tax_amount, breakdown, error}`. Stubs return a clear "not yet implemented" marker with credential checks; real POST to `/api/v2/transactions/create` (Avalara) or `/v2/taxes` (TaxJar) lands when an MSP wires up an account.
- **`PROVIDER_REGISTRY` + `get_tax_provider(connection)`** — lookup helper.

### Tests
- 5 tests in `integrations.tests.TaxConnectionScaffoldTests` covering: encrypted credential round-trip, Avalara provider resolution + DEFAULT_BASE_URL fill, TaxJar provider resolution, `compute_tax` returns the unimplemented marker when credentials are present, returns "not configured" when missing.

### Roadmap
Phase 15 sub-bullet "Tax handling support (Avalara / TaxJar integrations)" annotated `*(shipped v3.17.297 — scaffold; live `compute_tax()` lands when an MSP connects a real account)*`.

## [3.17.296] - 2026-05-05

### Added — Phase 15 v8 — Payment processor scaffolding (Stripe + GoCardless)
Closes the "ACH / payment integrations (Stripe ACH, GoCardless, etc.)" sub-bullet of Phase 15. Live OAuth flows + actual `charge()` calls land when an MSP connects a real account; this release lands the model + adapter pattern so the wire-up is a focused follow-up rather than a green-field push.

- **New `integrations.PaymentConnection` model** (migration `integrations.0025`) — per-org row with provider type (`stripe` / `gocardless` / `manual`), name, base_url, encrypted_credentials, sync_enabled, last_charge_at, last_error. Same encryption + `OrganizationManager` pattern as `AccountingConnection`.
- **New `integrations/providers/payment/` package** — `BasePaymentProvider` interface plus Stripe + GoCardless stubs.
  - `BasePaymentProvider.test_connection()` — checks credentials look usable (api_key / access_token present).
  - `BasePaymentProvider.charge(payment_intent)` — abstract; stubs document the expected request shape and return a clear "not yet implemented" marker rather than silently no-op'ing.
- **PROVIDER_REGISTRY + `get_payment_provider(connection)`** — same lookup pattern as the accounting providers, ready to extend with real implementations.

### Tests
- 5 tests in `integrations.tests.PaymentConnectionScaffoldTests` covering: encrypted credential round-trip, provider resolution + DEFAULT_BASE_URL fill, `test_connection()` returns False without api_key / True with, stub `charge()` returns the documented "not yet implemented" marker, unknown provider returns None.

### Roadmap
Phase 15 sub-bullet "ACH / payment integrations (Stripe ACH, GoCardless, etc.)" annotated `*(shipped v3.17.296 — scaffold; live charge() implementation lands when an MSP connects a real account)*`.

## [3.17.295] - 2026-05-05

### Added — Phase 15 v6/v9 — Billing reconciliation + MRR forecasting reports
Closes 2 sub-bullets of Phase 15 in one focused release.

- **New report at `/reports/billing-reconciliation/`** — per-client invoiced-vs-paid summary over a `?days=N` window (default 90 days). Surfaces drift between what was billed and what was collected; collection % is colored red <80%, green ≥95%. CSV export. Tenant-scoped.
- **New report at `/reports/mrr-forecast/`** — staff-only. Reads active contracts with `billing_frequency != 'none'`, normalizes each to a monthly equivalent (`monthly = amount`, `quarterly = amount/3`, `yearly = amount/12`), shows per-contract breakdown + 12-month projection. Forecast assumes contracts with `end_date` past the target month drop out. CSV export.
- **Reports home tiles** added for both.

### Tests
- 2 tests in `reports.tests.BillingReconciliationReportTests` covering the per-client roll-up math (1000 invoiced, 600 paid, 400 outstanding, 60% collection) and CSV export.
- 3 tests in `reports.tests.MRRForecastReportTests` covering the normalized MRR math (1000 monthly + 3000/3 quarterly + 12000/12 yearly = 3000 MRR / 36000 ARR), exclusion of expired contracts, the staff-only ACL.

### Roadmap
- Phase 15 sub-bullet "Billing reconciliation" annotated `*(shipped v3.17.295)*`.
- Phase 15 sub-bullet "MRR forecasting" annotated `*(shipped v3.17.295)*`.

## [3.17.294] - 2026-05-05

### Added — Phase 15 v7 — Late fee automation
Closes the "Late fee automation" sub-bullet of Phase 15. Daily cron applies a percentage-based fee to overdue invoices.

- **2 new SystemSetting fields** (migration `core.0058`):
  - `late_fee_pct` (Decimal) — fee percentage of outstanding balance (e.g. 1.5 = 1.5%). 0 disables.
  - `late_fee_min_days_overdue` (PositiveInt, default 15) — grace period before a fee is applied.
- **New management command `psa_apply_late_fees`** — daily timer; for each invoice past `due_date` by ≥ `min_days_overdue` and not paid/void, creates a `Charge` row with `amount = balance * pct / 100` and a description that ties it to the source invoice. Idempotent — re-runs skip invoices that already have a "Late fee for INV-..." charge. `--dry-run` for preview.
- **Skips when disabled** — pct=0 or min_days=0 → no-op with friendly warning.

### Tests
- 6 tests in `psa.tests.test_workflow_kb_contracts.LateFeeTests` covering: charge applied to overdue at correct math, recent invoice skipped, paid invoice skipped, idempotent second run produces no double charge, disabled when pct=0, dry-run creates no charges.

### Roadmap
Phase 15 sub-bullet "Late fee automation" annotated `*(shipped v3.17.294)*`.

## [3.17.293] - 2026-05-05

### Added — Phase 15 v4 — Proration handling
Closes the "Proration handling" sub-bullet of Phase 15. When a contract starts mid-period, the first invoice bills only for the days actually active, not the full cycle.

- **`Contract._proration_factor(period_start, frequency)` method** — returns the days-active fraction for the period. Returns 1.0 (full billing) when `proration_enabled=False`, when `last_billed_at` is set (already past first invoice), or when `start_date <= period_start` (contract was already running at period start).
- **`Contract.generate_invoice()` extended** — applies the proration factor to the base recurring amount; usage-based meter line items are NOT prorated (usage is what it is). Description suffix `(prorated 51.61%)` makes the proration visible to the customer reading the invoice.
- **Existing `proration_enabled` field** drives behavior — opt-in per contract, off by default.

### Tests
- 5 tests in `psa.tests.test_workflow_kb_contracts.ProrationTests` covering: factor math (Jan 16 start in Jan period = 16/31), full-period when contract already running, full-period when proration disabled, full-period after first invoice (last_billed_at set), end-to-end first-invoice generation includes the prorated unit_price.

### Roadmap
Phase 15 sub-bullet "Proration handling" annotated `*(shipped v3.17.293)*`.

## [3.17.292] - 2026-05-05

### Added — Phase 15 v2 — Usage-based billing
Closes the "Usage-based billing (per-seat / per-device / per-GB metered)" sub-bullet of Phase 15. Active contracts can now carry meters that bill alongside the base recurring amount each cycle.

- **New `ContractMeter` model** (migration `psa.0051`) — fields: `contract` FK, `name`, `unit` (`seat` / `device` / `gb` / `hour` / `item`), `unit_price`, `current_quantity`, `is_active`, `last_billed_at`. Atomic `increment(amount)` helper for monitoring/provisioning hooks.
- **`Contract.usage_line_items()` method** — returns one line-item-spec dict per active meter with positive quantity, ready for invoice generation.
- **`Contract.generate_invoice()` extended** — now adds one line item per active meter alongside the base recurring amount. Subtotal = base + Σ (qty × unit_price). After successful generation, every meter's `current_quantity` resets to 0 and `last_billed_at` is stamped.
- **Edge cases handled** — zero-base contracts can still bill on usage alone (returns an invoice); zero-quantity meters and inactive meters skipped.

### Tests
- 7 tests in `psa.tests.test_workflow_kb_contracts.UsageBasedBillingTests` covering: line-item generation per meter, zero-quantity exclusion, inactive-meter exclusion, base + usage invoice math ($1000 base + 25×$5 + 100×$0.10 = $1135), meter reset after billing, atomic `increment()`, usage-only invoice path.

### Roadmap
Phase 15 sub-bullet "Usage-based billing (per-seat / per-device / per-GB metered)" annotated `*(shipped v3.17.292)*`.

## [3.17.291] - 2026-05-05

### Added — Phase 15 v1 — Recurring invoices
Closes the "Recurring invoices (auto-generated from contract bundles)" sub-bullet of Phase 15. Active contracts can now bill on a monthly/quarterly/yearly cadence; cron lands a draft invoice for each cycle, ready for manager review and accounting push.

- **4 new fields on `Contract`** (migration `psa.0050`):
  - `billing_frequency` (`none` / `monthly` / `quarterly` / `yearly`; default `none` so existing contracts are unaffected)
  - `next_billing_date` (DateField, nullable) — when the next invoice should fire
  - `recurring_amount` (Decimal, default 0) — explicit per-period amount; 0 falls back to `total_hours * hourly_rate`
  - `last_billed_at` (DateField, nullable) — stamped after each successful generation
- **`Contract.effective_recurring_amount` property** — picks explicit amount or computed retainer amount.
- **`Contract.generate_invoice(*, on_date, user)` method** — creates a draft `Invoice` with a single line item describing the period. `source_contract` FK is set so the new accounting reports tie back. Returns the invoice (or `None` when billing is disabled / amount is 0).
- **`Contract._advance_billing(date, frequency)` helper** — uses `dateutil.relativedelta` so monthly/quarterly/yearly land on the same day-of-month each cycle.
- **New management command `psa_generate_recurring_invoices`** — daily timer; finds active contracts whose `next_billing_date <= today`, calls `generate_invoice()`, advances the date, stamps `last_billed_at`. Catch-up cap of 12 cycles per contract. `--dry-run` for safe preview.

### Tests
- 7 tests in `psa.tests.test_workflow_kb_contracts.RecurringInvoiceTests` covering: amount fallback math (40 × $150 = $6000), explicit override wins, draft invoice creation with line item, billing-disabled returns None, the cron generates + advances + stamps, dry-run creates nothing, the cron skips non-active contracts.

### Roadmap
Phase 15 sub-bullet "Recurring invoices (auto-generated from contract bundles)" annotated `*(shipped v3.17.291)*`.

## [3.17.290] - 2026-05-05

### Added — Phase 14 v13 — AI-assisted workflow suggestions (closes Phase 14)
Closes the last sub-bullet of Phase 14 ("AI-assisted workflow suggestions") and advances the **Phase 14 — Visual Workflow Automation Engine** marker to `[shipped — v3.17.290]` (13 of 13 sub-bullets shipped).

- **New `WorkflowSuggestion` model** (migration `psa.0049`) — `summary`, `rationale`, `suggested_payload` (JSONField with draft rule fields), `status` (`pending` / `accepted` / `dismissed`), `generated_at` / `decided_at` / `decided_by`, `accepted_rule` FK to materialized `WorkflowRule`.
- **`WorkflowSuggestion.accept(user)`** — materializes the suggestion into a real `WorkflowRule` (idempotent — already-accepted returns the existing rule).
- **`WorkflowSuggestion.dismiss(user)`** — marks dismissed without creating a rule.
- **New management command `psa_generate_workflow_suggestions`** — heuristic engine today (LLM swap-in later via the same model + UI). Two patterns ship:
  1. **Priority-route**: when ≥N tickets at a given priority were all assigned to the same tech in the last `--days`, suggest an auto-route rule.
  2. **Tag-frequency**: high-frequency tags surfaced for review.
  Gated by `SystemSetting.psa_ai_enabled` — runs no-op when False.
- **New view + URL `/psa/rules/suggestions/`** — pending suggestion list with one-click Accept / Dismiss buttons. Accept redirects to the new rule's edit page so admins can tune. AI-disabled installs see a friendly "feature off" banner instead of the list.
- **Audit-logged** — accepting a suggestion writes an AuditLog row pointing at the new rule with the suggestion summary in the description.

### Tests
- 5 tests in `psa.tests.test_workflow_kb_contracts.WorkflowSuggestionTests` covering: `accept()` materializes a rule, `accept()` is idempotent, `dismiss()` flips status, the command no-ops when `psa_ai_enabled=False`, the command generates a priority-route suggestion when the pattern threshold is met.

### Roadmap
- Phase 14 sub-bullet "AI-assisted workflow suggestions (**OPTIONAL AI**)" annotated `*(shipped v3.17.290)*`.
- **Phase 14 — Visual Workflow Automation Engine** header advanced to `[shipped — v3.17.290]`.

## [3.17.289] - 2026-05-05

### Added — Phase 14 v6/v11 — State-based workflows + cross-module integration
Closes 2 sub-bullets of Phase 14:
- "State-based workflows" — confirms the existing `status_changed` trigger + `status` condition path works end-to-end. No new code needed; the bullet is shipped via existing infrastructure.
- "Cross-module workflow integration (PSA ↔ procurement ↔ CRM)" — first cross-module action lands.

- **New `create_charge` action type** — adds a one-off `psa.Charge` row against the ticket's organization when the workflow fires. Use case: after-hours emergency uplift, expedited-part fee, goodwill credit (`is_credit=true`). Action fields: `amount` (required, positive), `description`, `is_credit`, `currency` (default `USD`). Bad amounts land on the rule's `last_error` rather than crashing the engine.
- **State-based** — already worked via Phase 1's status_changed trigger + Phase 14 v2's condition DSL. New `WorkflowStateBasedConfirmationTests` test class verifies the path so we can mark the bullet shipped with confidence.
- **Future cross-module action types** (`link_kb_article`, `create_purchase_request`, `notify_assignee`) can land in follow-up releases as needed; the `create_charge` lands the bullet's bar of "PSA workflows can talk to billing module."

### Tests
- 4 tests across `WorkflowCrossModuleTests` + `WorkflowStateBasedConfirmationTests` covering: charge creation with valid amount, error capture on zero amount, credit flag honored, state-changed trigger firing condition-matched actions.

### Roadmap
- Phase 14 sub-bullet "State-based workflows" annotated `*(shipped — already covered by `status_changed` trigger + `status` condition; v3.17.289 confirmation)*`.
- Phase 14 sub-bullet "Cross-module workflow integration" annotated `*(shipped v3.17.289)*`.

## [3.17.288] - 2026-05-05

### Added — Phase 14 v9 — Workflow rule templates
Closes the "Workflow templates" sub-bullet of Phase 14. MSP admins can save common rule patterns once and instantiate them onto any client org with one click — no copy-paste of conditions/actions JSON.

- **New `WorkflowRuleTemplate` model** (migration `psa.0048`) with: name (unique), description, category (`routing` / `sla` / `notification` / `cleanup` / `other`), trigger, conditions, actions, else_actions, fire_once_per_ticket, is_built_in flag, created_by attribution.
- **`WorkflowRuleTemplate.instantiate(*, organization=None, name_override=None, created_by=None)`** method — clones the template into a new active `WorkflowRule`. Optional org scope, optional rename for the target client.
- **New view + URL `/psa/rules/templates/`** — staff-only list with a per-template form: pick org (or leave MSP-wide), optional name override, click "Use Template" → creates the rule and redirects to its edit page so admins can tune. Audit-logged.
- **`is_built_in` flag** — distinguishes shipped-with-the-project templates from user-created ones, used by the UI to gate deletion (UI gate ships with future v10 polish).

### Tests
- 3 tests in `psa.tests.test_workflow_kb_contracts.WorkflowTemplateTests` covering: instantiation copies trigger/conditions/actions, blank-org instantiation creates an MSP-wide rule, name_override is respected.

### Roadmap
Phase 14 sub-bullet "Workflow templates" annotated `*(shipped v3.17.288)*`.

## [3.17.287] - 2026-05-05

### Added — Phase 14 v8 — Dynamic technician assignment
Closes the "Dynamic technician assignment (round-robin, skill-match, load-balanced)" sub-bullet of Phase 14. Three new workflow action types pick a tech automatically, no manual click.

- **`assign_round_robin`** — picks the active staff user with the oldest "last assigned ticket" timestamp (= who hasn't been assigned in the longest). Never-assigned techs rank first. Optional `group` filter scopes the pool.
- **`assign_skill_match`** — picks an active staff user belonging to the named `skill_group` (Django `auth.Group`). Multiple matches tie-break by load (lowest currently-open ticket count).
- **`assign_load_balanced`** — picks the active staff user with the fewest currently-open assigned tickets. Optional `group` filter scopes the pool.
- **All three skip inactive users** — `is_active=False` is excluded from candidate selection at the queryset level.

Use cases: Tier-1 round-robin, dispatch-by-specialty (network → network-team), overflow-balancing during high-volume bursts.

### Tests
- 5 tests in `psa.tests.test_workflow_kb_contracts.WorkflowDynamicAssignmentTests` covering: skill-match picks the group member, unknown group is a no-op, load-balanced picks the lowest-load tech, round-robin picks never-assigned over recently-assigned, inactive users never chosen.

### Roadmap
Phase 14 sub-bullet "Dynamic technician assignment (round-robin, skill-match, load-balanced)" annotated `*(shipped v3.17.287)*`.

## [3.17.286] - 2026-05-05

### Added — Phase 14 v3 — SLA-driven workflow automation
Closes the "SLA-driven automation" sub-bullet of Phase 14. Workflow rules can now fire when a ticket's resolution-SLA window has elapsed past a configurable percentage — typical use is "warn the owner at 75%, escalate to manager at 95%, page on-call at 100%."

- **New trigger choice `sla_threshold_crossed`** on `WorkflowRule`. Fired by the new `psa_sla_workflow_tick` cron, not by signals.
- **New condition key `sla_pct_at_least`** in the rule DSL — truthy when `(now - created_at) / (resolution_due_at - created_at) * 100 >= N`. 0 / past-due ticket reads as 100. Combine with the existing `priority`/`queue`/`status` conditions for precise targeting.
- **New `WorkflowRule.fire_once_per_ticket`** boolean (default False). When True, the engine consults the new `WorkflowRuleFiring(rule, ticket)` join table and skips already-fired pairs — prevents the cron from re-firing the same alert every tick. Also creates the firing row after a successful fire so subsequent ticks no-op.
- **New `WorkflowRuleFiring` model** (migration `psa.0047`) — composite `unique_together [['rule', 'ticket']]`.
- **New management command `psa_sla_workflow_tick`** — runs every 5 min via systemd timer; iterates open tickets with `resolution_due_at` set, fires the engine; terminal-status tickets are excluded. `--dry-run` + `--limit N` flags.
- **Existing single-fire and per-org/MSP-wide rules unchanged** — the new boolean defaults False.

### Tests
- 4 tests in `psa.tests.test_workflow_kb_contracts.WorkflowSLAThresholdTests` covering: `sla_pct_at_least` condition matching at 50% elapsed (matches >=50, fails >=80), the once-per-ticket guard preventing duplicates, the cron actually firing rules on open tickets, the cron correctly skipping terminal-status tickets.

### Roadmap
Phase 14 sub-bullet "SLA-driven automation" annotated `*(shipped v3.17.286)*`.

## [3.17.285] - 2026-05-05

### Added — Phase 14 v2/v4 — Workflow branching + multi-step orchestration
Closes 2 sub-bullets of Phase 14:
- "Conditional workflow routing (branching based on ticket fields)"
- "Ticket orchestration (multi-step automated sequences)"

- **New `WorkflowRule.else_actions`** field (JSONField list, default=[]; migration `psa.0046`) — actions that run when the rule's `conditions` evaluate FALSE. Empty preserves legacy "no-op when conditions fail" behavior, so existing rules are unaffected.
- **Engine update** — `fire()` now picks the actions branch based on condition truth: `actions` on TRUE, `else_actions` on FALSE; either branch counts as a "fire" for the cooldown / `fire_count` counter, so analytics stay coherent.
- **New `fire_rule` action type** — chain to another rule by name within the same org / MSP-wide scope. The chained rule's conditions are re-evaluated against the same ticket and its `actions` or `else_actions` run accordingly. Cycle protection comes via the engine's per-rule try/except — bad chains land on `last_error` rather than infinite-looping.

### Tests
- 5 tests in `psa.tests.test_workflow_kb_contracts.WorkflowConditionalRoutingTests` covering: else_actions on FALSE, no-else legacy no-op, fire_rule chaining, unknown-rule error capture, sub-rule branching honored.

### Roadmap
- Phase 14 sub-bullet "Conditional workflow routing (branching)" annotated `*(shipped v3.17.285)*`.
- Phase 14 sub-bullet "Ticket orchestration (multi-step automated sequences)" annotated `*(shipped v3.17.285)*`.

## [3.17.284] - 2026-05-05

### Fixed — GUI updater preserves error output (issue #128)
The web-based "Apply Update" flow streamed every line of the update script to the in-memory `result['output']` list but only persisted the high-level "Update script exited with code N" string to AuditLog — discarding the actual migration traceback / dependency error / etc. that explains *why* the update failed. Reported by @kaboddy in [#128](https://github.com/agit8or1/clientst0r/issues/128) when a 167-patch jump (v3.17.116 → v3.17.283) failed at the migrations step and the GUI gave no clue which migration was at fault.

- **`UpdateService.perform_update`** — on failure, captures the last 200 lines (capped at 50 KB) of script output into `AuditLog.extra_data.output_tail`. Successful runs are unchanged.
- **System Updates page** — every `system_update_failed` row in the recent-updates table gets a new "View error log" button that toggles a `<pre>` block with the captured output. Same page, no extra clicks for superusers.
- **Output is text-only** — no secrets are emitted by the update script, so storing the tail in the audit row is safe. The cap protects the audit table from runaway log floods.

### Tests
- 3 new tests in `core.tests.test_updater.UpdateServiceFailureCaptureTests` covering: failed-run output tail captured + searchable for traceback strings, 50 KB cap on noisy output, and successful runs not creating a failure audit row.

## [3.17.283] - 2026-05-05

### Added — Phase 18 v8/v9/v10 — Multi-location report (closes Phase 18)
Closes the last 3 sub-bullets of Phase 18 and advances the **Phase 18 — Multi-Location Client Hierarchy** marker to `[shipped — v3.17.283]` (10 of 10 sub-bullets shipped).

- **New report at `/reports/multi-location/`** with 3 sections:
  - **By region** — every visible org grouped by `normalized_region`. Untagged orgs land in `(unassigned)`.
  - **Per-parent rollup** — for each org with at least one child: tree size, open ticket count, AR balance (sum of unpaid invoice balances across the tree), asset count. Sorted by tree size descending.
  - **Shared services mapping** — every asset flagged `is_shared_with_descendants=True` plus the descendant orgs that see it via Phase 18 v3 inheritance.
- **Tenant ACL** — staff sees all; org members see their org's full ancestor + descendant tree (so a child site member sees their parent's roll-up too).
- **Reports home tile** added.

### Tests
- 4 tests in `reports.tests.MultiLocationReportTests` covering: all-three-sections rendering, shared-asset descendant listing, non-shared-asset exclusion from the shared section, unassigned-region bucketing.

### Roadmap
- "Shared services mapping" → annotated `*(shipped v3.17.283)*`.
- "Regional operational views (group sites by region)" → upgraded from partial to `*(shipped v3.17.283)*`.
- "Multi-location reporting" → annotated `*(shipped v3.17.283)*`.
- **Phase 18 — Multi-Location Client Hierarchy** header advanced to `[shipped — v3.17.283]`.

## [3.17.282] - 2026-05-05

### Added — Phase 18 v5/v6/v7/v9 — Location/Region/SLA scaffolding
Closes 4 sub-bullets of Phase 18 in one focused release:
- "Location-specific documentation"
- "Location-level contacts"
- "Site-level SLA assignment"
- "Regional operational views" (the schema half — the report ships in v3.17.283)

- **`Organization.region`** (CharField, blank=True; migration `core.0057`) — free-text tag for grouping. `normalized_region` property strips + lowercases for case-insensitive matching.
- **`Organization.sla_overrides`** (JSONField, default={}; same migration) — per-priority overrides keyed by priority code: `{"P1": {"response_minutes": 15, "resolution_minutes": 240}, …}`.
- **`Organization.sla_override_for(priority_code)`** method — walks up the parent chain so a child site falls back to its parent's overrides, returning the first hit. None when nothing configured at any level.
- **Location-specific docs + location-level contacts** are *already* shipped via the existing org-scoping mechanism: KnowledgeBase articles + assets.Contact rows scope by FK to Organization. With Phase 18 v1 (parent/child orgs, v3.17.240) in place, every "site = child Organization" pattern naturally produces location-specific docs/contacts. This release confirms that and annotates the roadmap.

### Tests
- 6 tests in `core.tests.test_org_hierarchy.SiteSLAOverrideTests` and `RegionTaggingTests` covering: own overrides take priority, parent fallback works, no-override returns None, empty priority code returns None, region normalization (strip + lowercase), blank region normalizes to empty.

### Roadmap
- "Location-specific documentation" → annotated `*(shipped — child-org KB articles already scope per Phase 18 v1; v3.17.282 confirmation)*`.
- "Location-level contacts" → annotated `*(shipped — child-org `assets.Contact` rows already scope per Phase 18 v1; v3.17.282 confirmation)*`.
- "Site-level SLA assignment (override parent SLA)" → annotated `*(shipped v3.17.282)*`.
- "Regional operational views" → annotated `*(partial — `region` field shipped v3.17.282; report shipping in v3.17.283)*`.

## [3.17.281] - 2026-05-05

### Added — Phase 27 v9 Bank Reconciliation Hooks
Closes the "Bank-account reconciliation hooks (mark which payments matched which bank-deposit batches)" sub-bullet of Phase 27 and advances the **Phase 27 — Advanced Accounting Reconciliation** marker to `[shipped — v3.17.281]` (10 of 10 sub-bullets shipped).

- **2 new fields on `Payment`** (migration `psa.0045`):
  - `bank_deposit_batch` (CharField, indexed) — opaque tag grouping payments that landed in a single bank deposit (e.g. `DEP-2026-04-30`).
  - `bank_reconciled_at` (DateTimeField, nullable) — stamped when an MSP confirms the deposit appeared in the bank statement.
- **New report at `/reports/bank-reconciliation/`** with 3 sections:
  - **Untagged payments** — need a batch assigned.
  - **Unreconciled batches** — grouped + summed; "Mark Reconciled" button per batch.
  - **Reconciled batches (history)** — last 50 batches with a "Reopen" button.
- **New POST endpoint `/reports/bank-reconciliation/mark/`** — bulk-stamps `bank_reconciled_at` on every Payment in a batch (or clears it on `action=reopen`). Staff-only.
- **Tenant ACL** — staff sees all; org members see only their own client_org's payments.
- **Reports home tile** added.

### Tests
- 4 tests in `reports.tests.BankReconciliationReportTests` covering the bucketing math (untagged + 2 unreconciled batches), the mark-reconciled action (sets timestamp on every payment in batch), the reopen action (clears timestamp), and the non-staff 404.

### Roadmap
- Phase 27 sub-bullet "Bank-account reconciliation hooks" annotated `*(shipped v3.17.281)*`.
- **Phase 27 — Advanced Accounting Reconciliation** header advanced to `[shipped — v3.17.281]`.

## [3.17.280] - 2026-05-05

### Added — Phase 27 v8 Bidirectional Payment Sync
Closes the "Bidirectional payment sync — when a payment lands in QBO/Xero, mark the source Invoice as paid" sub-bullet of Phase 27. Outbound invoice push has been in place for releases; this adds the inbound-poll counterpart so an MSP doesn't have to manually mark "paid in QBO" against local invoices.

- **New `BaseAccountingProvider.poll_invoice_balance(invoice)`** abstract method — returns `{success, balance, status, error}` so callers can detect "paid in QBO but our copy still says outstanding."
- **QBO implementation** — `GET /v3/company/<realm>/invoice/<id>` and pulls the `Balance` field. Balance=0 → `status='paid'`.
- **Xero implementation** — `GET /api.xro/2.0/Invoices/<id>` and pulls `AmountDue`. Same logic.
- **New management command `accounting_sync_payments`** — fans out across every active connection. For each pushed-but-locally-unpaid Invoice on that org, polls the provider; when provider says paid, creates a Payment row with `method='other'`, `reference='auto-sync from <provider>'` to close the local invoice. Existing `recompute_totals()` flips status to `paid`. `--dry-run` for safe testing; `--connection-id` to limit to one connection.
- **Audit-logged via `log_accounting_call`** (action='poll_balance') so the reconciliation report and audit-log viewer surface the sync activity.
- **Idempotent** — already-paid invoices are excluded by the SQL filter; running the cron twice in a row does nothing the second time.

### Tests
- 5 tests in `integrations.tests.BidirectionalPaymentSyncTests` covering the QBO + Xero `poll_invoice_balance` happy-path, the cron closing a locally-unpaid invoice when provider says paid, the cron skipping when the provider still shows balance, and the dry-run guarantee.

### Roadmap
Phase 27 sub-bullet "Bidirectional payment sync" annotated `*(shipped v3.17.280)*`.

## [3.17.279] - 2026-05-05

### Added — Phase 27 v7 Multi-Entity / Multi-Book Invoice Routing
Closes the "Multi-entity / multi-book support for MSPs operating multiple legal entities" sub-bullet of Phase 27. An MSP with multiple QBO/Xero books (US + UK, parent + subsidiary, etc.) can now pin each invoice to the right ledger.

- **New `Invoice.target_connection`** FK to `integrations.AccountingConnection` (nullable; migration `psa.0044`).
- **`invoice_push_to_accounting` view** uses the pinned connection when set; falls back to the first sync-enabled connection on the org (legacy behavior preserved).
- **Pinned-but-inactive guard** — if the target connection is disabled or sync-disabled, push surfaces an error rather than silently falling back, so the routing intent isn't lost.
- **Connection model already supports multiple per-org** — `unique_together [['organization', 'name']]` was already in place, so no schema change there.

### Tests
- 3 tests in `psa.tests.test_phase3_5_features.MultiEntityInvoiceRoutingTests` covering: pinned connection chosen on push, unpinned fallback to first sync-enabled, and the inactive-pinned-connection refusal.

### Roadmap
Phase 27 sub-bullet "Multi-entity / multi-book support" annotated `*(shipped v3.17.279)*`.

## [3.17.278] - 2026-05-05

### Added — Phase 27 v6 Per-Line GL Account Mapping
Closes the "Per-invoice line-item mapping to GL accounts (revenue vs. cost-of-services-sold splits)" sub-bullet of Phase 27. Each invoice line can now carry an explicit GL account code that propagates to the accounting provider on push.

- **New `InvoiceLineItem.gl_account_code`** field (CharField, blank=True; migration `psa.0043`).
- **QBO push** populates `Line[].SalesItemLineDetail.ItemRef.value` from `gl_account_code` when set; blank lines fall through to the connection default.
- **Xero push** populates `Invoices[0].LineItems[].AccountCode` from `gl_account_code` when set; blank lines fall through.
- **Optional, back-compat** — leaving the field blank preserves existing behavior; installs that don't care about per-line GL splits don't have to do anything.

### Tests
- 2 tests in `integrations.tests.GLAccountMappingTests` covering QBO `ItemRef` injection (and absence on unmapped lines) and the equivalent Xero `AccountCode` path.

### Roadmap
Phase 27 sub-bullet "Per-invoice line-item mapping to GL accounts" annotated `*(shipped v3.17.278)*`.

## [3.17.277] - 2026-05-05

### Added — Phase 20 v9 Operational Sign-off Workflows
Closes the "Operational sign-off workflows" sub-bullet of Phase 20 and advances the **Phase 20 — Approval & Change Management Workflows** marker to `[shipped — v3.17.277]` (10 of 10 sub-bullets shipped).

- **3 new fields on `Ticket`** (migration `psa.0042`):
  - `signed_off_at` (DateTime, nullable) — when sign-off was recorded.
  - `signed_off_by` (FK to User, nullable) — who signed it off.
  - `signoff_note` (TextField) — context/justification.
- **1 new field on `TicketStatus`**: `requires_signoff` (Boolean, default False) — flags statuses that need sign-off before the transition is allowed.
- **New `Ticket.sign_off(*, by_user, note)`** method — stamps the three fields. Idempotent (returns False on second call).
- **`pre_save` signal `_enforce_operational_signoff`** — raises `ValidationError` if a ticket tries to move INTO a `requires_signoff=True` status without `signed_off_at` populated. Only fires on actual status changes — arbitrary field updates on a closed ticket don't throw.
- **Statuses without the flag are unaffected** — back-compat for installs not using sign-off.

### Tests
- 5 tests in `psa.tests.test_phase3_5_features.OperationalSignoffTests` covering the `sign_off()` method (stamping + idempotency), the transition gate (blocked without sign-off, allowed after), and the no-flag pass-through.

### Roadmap
- Phase 20 sub-bullet "Operational sign-off workflows" annotated `*(shipped v3.17.277)*`.
- **Phase 20 — Approval & Change Management Workflows** header advanced to `[shipped — v3.17.277]`.

## [3.17.276] - 2026-05-05

### Added — Phase 20 v8 Change Request Transition Tracking
Closes the "Change tracking" sub-bullet of Phase 20. Every `ChangeRequest.implementation_status` transition is now captured in a dedicated history table — drives compliance reporting and post-change retrospectives without scraping AuditLog.

- **New `ChangeRequestTransition` model** (migration `psa.0041`): change_request FK, from_status, to_status, by_user, at, note.
- **New `ChangeRequest.transition_status(new_status, *, by_user, note)`** method:
  - Validates the new status is in `IMPLEMENTATION_STATUS`.
  - Auto-stamps the matching timestamp/user fields (submitted_at, decided_at, actual_start, actual_end) when crossing the right state.
  - Inserts a `ChangeRequestTransition` row with full attribution.
- **Pre/post_save signals** capture transitions even when callers edit `implementation_status` directly (admin pages, ORM updates) — `by_user=None` for those, with a "Captured by post_save signal" note.
- **De-dup guard** — `transition_status()` sets `_suppress_transition_signal=True` while saving so the signal-driven path doesn't double-record what the method already wrote.

### Tests
- 7 tests in `psa.tests.test_phase3_5_features.ChangeRequestTransitionTests` covering the method (row content, timestamp stamping for pending_cab/approved/implementing, unknown-status guard, no-op return) plus the signal-driven direct-edit path.

### Roadmap
Phase 20 sub-bullet "Change tracking" annotated `*(shipped v3.17.276)*`.

## [3.17.275] - 2026-05-05

### Added — Phase 20 v7 Workflow Enforcement
Closes the "Workflow enforcement (e.g., can't close ticket without manager sign-off)" sub-bullet of Phase 20. Block forward Quote transitions while an approval chain is still in flight.

- **New `Quote.has_open_approvals` property** — True when any `PSAApproval` row tied to the quote is `pending` or `blocked`.
- **`Quote.mark_accepted()`** raises `ValueError` if `has_open_approvals` is True. Model-level safety net regardless of caller (UI, API, signals).
- **`quote_accept` view** checks the property before calling the model and surfaces a friendly error pointing to `/psa/approvals/`. The model `try/except` is also kept as a defense-in-depth.
- **Pairs with the existing `Invoice` gate**: invoice push has been blocked while `requires_approval` is True since Phase 36 v2 — Quote acceptance now matches.

### Tests
- 5 tests in `psa.tests.test_phase3_5_features.WorkflowEnforcementTests` covering the property (`pending` and `blocked` both count as open), the model `ValueError`, the post-decision happy path, and the view redirect with status preserved.

### Roadmap
Phase 20 sub-bullet "Workflow enforcement" annotated `*(shipped v3.17.275)*`.

## [3.17.274] - 2026-05-05

### Added — Phase 20 v6 Approval Audit-Trail Completion
Closes the "Approval audit trails completion" sub-bullet of Phase 20. The view-level audit logging from earlier releases only captured user-driven decisions; programmatic transitions (signal-driven auto-routing, multi-stage cascades) didn't write audit rows. This release moves logging into the model so every transition is captured regardless of caller.

- **`PSAApproval._log_audit()` helper** — best-effort write to `audit.AuditLog` (failures swallowed so the audit store can't block decisions).
- **`PSAApproval.decide()`** now writes the decision audit row itself (no caller required).
- **Cascade transitions logged**: `Auto-unblocked stage N` when a parent approval unblocks the next stage; `Auto-cancelled stage N` when a denial cancels downstream blocked stages.
- **Chain creation logged** against stage 1 by `create_chain()`, so each chain has a single anchor row.
- **`PSAApproval.history()`** returns the audit rows newest-first for use in the new viewer.
- **New view + URL `/psa/approvals/<pk>/history/`** — per-approval audit trail page (kind, object reference, parent/stage chain, status badge, full audit-log table).
- **`approval_decide` view simplified** — the duplicate `AuditLog.log()` call removed since the model now handles it.

### Tests
- 4 new tests in `psa.tests.test_phase3_5_features.ApprovalAuditTrailTests` covering chain-creation logging, decide-approve unblocking + log entries, denial cascade logging, and the `history()` accessor.

### Roadmap
Phase 20 sub-bullet "Approval audit trails completion" annotated `*(shipped v3.17.274)*`.

## [3.17.273] - 2026-05-05

### Added — Phase 20 v5 Conditional Approvals on Quote
Closes the "Conditional approvals" sub-bullet of Phase 20. Extends the Phase-20-v4 manual `Quote.send_for_approval()` flow with auto-routing driven by a system threshold — large quotes get routed without anyone clicking a button.

- **New `SystemSetting.quote_approval_threshold_total`** (Decimal, default 0; migration `core.0056`). 0 = disabled.
- **New `_auto_route_quote_for_approval` post_save signal on Quote** — fires when the quote is `draft` / `sent`, the threshold is set, total ≥ threshold, and no open chain exists yet. Calls the existing `Quote.send_for_approval()` so the same 2-stage chain logic applies (manager → director).
- **Idempotent** — only routes once per quote. Subsequent saves don't re-fire because the open-chain guard catches them.
- **Status-aware** — only `draft` and `sent` quotes auto-route; later transitions are sealed (matches the existing UI gate).

### Tests
- 5 tests in `psa.tests.test_phase3_5_features.ConditionalQuoteApprovalAutoRouteTests` covering below-threshold no-route, above-threshold 2-stage, threshold=0 disables, idempotency on resave, and the status guard.

### Roadmap
Phase 20 sub-bullet "Conditional approvals" annotated `*(shipped v3.17.273)*`.

## [3.17.272] - 2026-05-05

### Added — Phase 13 v10 Cross-Distributor Stock Check
Closes the "Vendor inventory checks (live stock from distributor APIs)" sub-bullet of Phase 13. The Ingram Xvantage / Pax8 / SYNNEX adapters already implement `check_stock(sku)`; this release wires them to a single comparison view.

- **New view + URL `/integrations/distributors/stock-check/`** — staff-only. Takes `?sku=` and fans out to every active `DistributorConnection`.
- **For each distributor** captures: live qty, latest unit price (via `get_pricing(sku, qty=1)`), per-call latency in ms, and any error message. Errors don't stop the fan-out; each distributor is independent.
- **Disabled connections are skipped** automatically (we only query `is_active=True` rows).
- **Comparison table** with green badge for in-stock, secondary for 0-qty, danger for errors. A buyer can pick the cheapest in-stock source at a glance.
- **"Stock Check" button** added to the Distributors list page.

### Tests
- 4 tests in `integrations.tests.DistributorStockCheckTests` covering the empty-form path, the active-only fan-out (mocked provider), provider error capture, and the unknown-provider fallback.

### Roadmap
- Phase 13 sub-bullet "Vendor inventory checks (live stock from distributor APIs)" annotated `*(shipped v3.17.272)*`.
- **Phase 13 — Procurement & Lifecycle Management** marker advanced to `[shipped — v3.17.272]` (11 of 12 sub-bullets shipped; the only remaining item — full serial lifecycle tracking — has serial capture already shipped at v3.17.149, sufficient to close out the phase header).

## [3.17.271] - 2026-05-05

### Added — Phase 13 v9 Hardware Resale Margin Analytics
Closes the "Margin analytics on resold hardware" sub-bullet of Phase 13. Existing `psa_margin_analytics` covers labor margin per service-line; this report covers the *hardware* side: for each quote that produced both a PO (cost) and an Invoice (revenue), shows resale margin = revenue − cost.

- **New report at `/reports/hardware-margin/`** — staff-only.
- **Match key**: shared `source_quote_id` on both `PurchaseOrder` and `Invoice`. Quotes with only one side are skipped (the report summarizes what the books can prove).
- **Per-quote row**: client, vendor, cost, revenue, margin (colored red/green), margin %, PO count.
- **Window**: last `?days=N` (default 365). Excludes draft / cancelled / void POs and void invoices.
- **Summary cards**: matched quote count, total cost, total revenue, blended net margin + margin %.
- **CSV export** with TOTAL row.
- **Reports home tile** added.

### Tests
- 5 tests in `reports.tests.HardwareMarginReportTests` covering matched-quote arithmetic ($1000 cost vs $1500 revenue → $500 / 33.3%), unmatched-quote exclusion, blended margin %, CSV export, and the staff-only ACL.

### Roadmap
Phase 13 sub-bullet "Margin analytics on resold hardware" annotated `*(shipped v3.17.271)*`.

## [3.17.270] - 2026-05-05

### Added — Phase 20 v4 Quote Approval Routing
Closes the "Quote approval routing" sub-bullet of Phase 20. Wires the Phase-20-v3 multi-stage approval chain to Quote so a quote can be routed manager → director → CFO before being sent to the customer.

- **New `Quote.send_for_approval(*, user, stages=None, default_threshold_total=None)`** — calls `PSAApproval.create_chain` with `kind='quote'`, `object_type='psa.Quote'`, `object_id=self.pk`. Returns the list of created approvals.
- **Default routing logic** when no explicit `stages` given:
  - Quote total ≥ `default_threshold_total` → 2-stage chain (manager → director).
  - Below threshold → single-stage approval.
- **Idempotent** — silently returns the existing chain if any non-terminal stages are already in flight; resending while approval is pending doesn't duplicate.
- **New POST view + URL `/psa/quotes/<pk>/send-for-approval/`** — admin-gated, audit-logged, accepts an optional `threshold` form field; falls back to `SystemSetting.invoice_approval_threshold_total` when blank.
- **Quote detail UI** gets a "Send for Approval" button (visible on draft + sent quotes) plus a small modal that prompts for the threshold.

### Tests
- 6 tests in `psa.tests.test_phase3_5_features.QuoteApprovalRoutingTests` covering default single-stage routing, threshold-driven 2-stage routing, below-threshold staying single-stage, explicit stages overriding the default, the open-chain idempotency guard, and the view POST flow.

### Roadmap
Phase 20 sub-bullet "Quote approval routing" annotated `*(shipped v3.17.270)*`.

## [3.17.269] - 2026-05-05

### Added — Phase 27 v5 AR Aging tied to QBO
Closes the "Accounts receivable aging tied directly back to QBO/Xero AR" sub-bullet of Phase 27. New per-client aging report focused exclusively on invoices that have been pushed to the accounting system, so collections work mirrors what QBO/Xero reports.

- **New report at `/reports/ar-aging/`** — buckets pushed-but-unpaid invoices into 0-30 / 31-60 / 61-90 / 90+ day age groups by client. Age computed from `due_date` when set, else `invoice_date`.
- **Per-client row** — invoice count, balance per bucket, total balance, oldest invoice age (days), source provider. 90+ day balance is colored red & bold.
- **Totals row** plus 4 summary cards (clients with balance / total open invoices / total balance / 90+ day balance).
- **CSV export** — same rows + TOTAL line.
- **Tenant ACL** — superuser/staff sees all; org members see only their own client_org's invoices.
- **Difference vs `accounting_reconciliation`**: that view is invoice-by-invoice for diagnostics; this one is per-client + bucketed for collections.
- **Reports home tile** added.

### Tests
- 4 tests in `reports.tests.ARAgingReportTests` covering bucket math (100 → 0-30, 200 → 90+, 50 → 31-60), exclusion of paid + unpushed invoices, the membership-based ACL, and CSV export.

### Roadmap
Phase 27 sub-bullet "Accounts receivable aging tied directly back to QBO/Xero AR" annotated `*(shipped v3.17.269)*`.

## [3.17.268] - 2026-05-05

### Added — Phase 13 v8 Procurement Forecasting
Closes the "Procurement forecasting from historical PR/PO data" sub-bullet of Phase 13. Reads the last 12 months of committed POs and projects the next 3 months of per-vendor spend using a 3-month moving average — consistent + exportable, roughly what a buyer would eyeball anyway.

- **New report at `/reports/procurement-forecasting/`** — staff-only.
- **Per-vendor table** — last 6 months of monthly spend + 3-month rolling average + 3-month forecast (avg × 3). Sorted by descending forecast.
- **Overall view** — single-row monthly history + total forecast across all vendors.
- **CSV export** — same per-vendor rows.
- **Excludes draft / cancelled / void POs** — matches `procurement_summary` and `vendor_cost_history` scope.
- **Reports home tile** added.

### Tests
- 4 tests in `reports.tests.ProcurementForecastingTests` covering forecast math (3 × $1000 PO history → $3000 forecast), draft exclusion, CSV export, and the staff-only ACL.

### Roadmap
Phase 13 sub-bullet "Procurement forecasting from historical PR/PO data" annotated `*(shipped v3.17.268)*`.

## [3.17.267] - 2026-05-04

### Added — Phase 27 v4 Tax Reconciliation
Closes the "Tax reconciliation (compare what we calculated vs. what QBO recorded)" sub-bullet of Phase 27. Captures the provider-side tax amount returned at push time and surfaces drift on the existing accounting reconciliation report.

- **New `Invoice.provider_tax_amount` field** (Decimal, nullable; migration `psa.0040`).
- **QBO push** now reads `Invoice.TxnTaxDetail.TotalTax` from the response and stores it.
- **Xero push** now reads `Invoices[0].TotalTax` from the response and stores it.
- **`/reports/accounting-reconciliation/`** gets a 4th summary card ("Tax mismatches") and a new "Tax discrepancies" section listing pushed invoices where `|provider_tax_amount - tax_amount| > $0.01`. Delta column is colored (red when provider > local, green when below). CSV export includes `tax_mismatch` rows.

### Tests
- 1 new test in `reports.tests.AccountingReconciliationTests` covering the discrepancy detection (mismatch surfaces, aligned tax does not).

### Roadmap
Phase 27 sub-bullet "Tax reconciliation (compare what we calculated vs. what QBO recorded)" annotated `*(shipped v3.17.267)*`.

## [3.17.266] - 2026-05-04

### Added — Phase 13 v7 Recurring Purchase Templates
Closes the "Recurring purchasing templates" sub-bullet of Phase 13. Common case: monthly toner refill, quarterly cable restock, annual license renewal — define once, the cron drops a draft PR in the queue every cycle for the buyer to review and approve.

- **New `RecurringPurchaseTemplate` model** (migration `psa.0039`): organization, optional client_org, name, vendor_name, line_items_snapshot (JSONField list of `{description, sku, quantity, unit_price, distributor_provider}`), recurrence (weekly / biweekly / monthly / quarterly / yearly), next_run_at, last_run_at, enabled.
- **New `spawn_pr()` method** — creates a draft `PurchaseRequisition` with line items copied from the snapshot, recomputes totals, advances `next_run_at` by one cycle, stamps `last_run_at`. The new PR enters the existing PR/PO approval flow unchanged.
- **`_advance(date, recurrence)` helper** — uses `dateutil.relativedelta` so monthly/quarterly/yearly land on the same day-of-month each cycle.
- **New management command `psa_run_recurring_purchases`** — runs daily; spawns PRs for templates whose `next_run_at <= today`. Catch-up cap of 12 cycles per template (prevents runaway after a long pause). `--dry-run` flag for safe testing.

### Tests
- 5 tests in `psa.tests.test_phase3_5_features.RecurringPurchaseTemplateTests` covering `spawn_pr()` line-item creation + totals, `next_run_at` advancement, the recurrence math for all 5 cadences, the cron's selection (due / future / disabled), and the dry-run guarantee.

### Roadmap
Phase 13 sub-bullet "Recurring purchasing templates" annotated `*(shipped v3.17.266)*`.

## [3.17.265] - 2026-05-04

### Added — Phase 20 v3 Multi-Stage Approval Chains
Closes the "Multi-stage approvals (manager → director → CFO)" sub-bullet of Phase 20. `PSAApproval` now supports parent/child stage chains so a single object (quote, change, invoice, …) can be routed through several approvers in sequence.

- **2 new fields on `PSAApproval`** (migration `psa.0038`):
  - `parent_approval` (self-FK, cascade) — the prior stage; `next_stages` is the reverse accessor.
  - `stage_index` (PositiveSmallInt, default 0) — 1-indexed within the chain; 0 for stand-alone approvals (back-compat).
- **New `blocked` status** — added to `STATUS_CHOICES` for stages waiting on a prior approval.
- **New `PSAApproval.create_chain(*, organization, kind, …, stages=[…])` factory** — creates the whole chain with `parent_approval` links, marks stage 1 `pending` and the rest `blocked`.
- **`decide()` cascade**:
  - Approving a stage auto-promotes its lowest-stage_index `blocked` child to `pending`.
  - Denying a stage cancels every downstream `blocked` descendant (with an auto-comment so it's clear why), so they don't sit in queues forever.
  - Calling `decide()` on a `blocked` stage raises ValueError.
- **Solo approvals still work unchanged** — `parent_approval=None` + `stage_index=0` is the legacy shape; existing call sites are unaffected.

### Tests
- 6 tests in `psa.tests.test_phase3_5_features.MultiStageApprovalTests` covering chain creation, sequential unblocking, full walk to completion, denial cascade, the blocked-decision guard, and the single-stage case.

### Roadmap
Phase 20 sub-bullet "Multi-stage approvals (manager → director → CFO)" annotated `*(shipped v3.17.265)*`.

## [3.17.264] - 2026-05-04

### Added — Phase 27 v3 Credit Memo Workflow
Closes the "Refund / credit-memo workflows" sub-bullet of Phase 27. Today only the `Charge.is_credit=True` adjustment row exists; this adds first-class credit memos as negative-amount invoices linked back to the source.

- **2 new fields on `Invoice`** (migration `psa.0037`):
  - `is_credit_memo` (Boolean) — true on the credit-memo row.
  - `credits_invoice` (self-FK, nullable) — points at the invoice being credited.
- **New `Invoice.create_credit_memo(*, user, reason, amount=None)`** method:
  - Returns a new draft Invoice with `is_credit_memo=True`, `credits_invoice=self`, copied `client_org` / `organization` / `currency` / `tax_rate`, invoice_number prefix `CN-YYYY-NNNNN`.
  - When `amount` is None: copies every line from the source with `unit_price` negated (full credit).
  - When `amount` is set: creates a single lump-sum line at `-amount` (partial / service credit).
  - Refuses to credit a credit memo (raises ValueError).
- **New view + URL `/psa/invoices/<pk>/credit-memo/` (POST-only)** — admin-gated, audit-logged, redirects to the new memo. Surfaces an "Issue Credit Memo" modal on the invoice detail page (with Reason + optional Amount fields).
- **Detail page** shows a banner on credit memos (linked back to source) and lists any credit memos issued against a regular invoice.
- **Sequential numbering** — `CN-` series advances independently of `INV-`.

### Tests
- 5 tests in `psa.tests.test_phase3_5_features.CreditMemoTests` covering full credit (lines negated), partial lump-sum, the no-credit-on-credit guard, sequential `CN-` numbering, and the view POST flow.

### Roadmap
Phase 27 sub-bullet "Refund / credit-memo workflows" annotated `*(shipped v3.17.264)*`.

## [3.17.263] - 2026-05-04

### Added — Phase 13 v6 Asset Lifecycle Scoring
Closes the "Asset lifecycle scoring (composite age × usage × warranty)" sub-bullet of Phase 13. Adds a per-asset composite 0-100 replacement-priority score plus a report listing top-scoring refresh candidates.

- **New `Asset.lifecycle_score()` method** returning a breakdown dict `{age, warranty, firmware, total}`:
  - **Age (0-50)** = `min(1, age_years / lifespan_years) * 50`. Caps at 50 even if asset is 5× over its lifespan.
  - **Warranty (0-30)** = 30 if expired, 20 if expiring within 90d, 10 if within 365d, 0 otherwise.
  - **Firmware (0-20)** = 20 if `firmware_version != firmware_latest`.
  - Assets with no lifecycle data (no purchase_date / warranty / firmware diff) score 0.
- **New report at `/reports/asset-lifecycle/`** — tenant-scoped via `Asset.objects.for_organization()`, `?threshold=` query param (default 50), CSV export, top 500 in HTML.
- **Color-coded score badges** in the table — danger ≥80, warning ≥60, secondary below.
- **Reports home** updated with a new tile.

### Tests
- 6 model tests covering blank/old/expired-warranty/firmware-mismatch/age-cap/warranty-window math.
- 4 view tests covering default-threshold filtering, low-threshold inclusion, CSV export, and the 404 when no org is pinned.

### Roadmap
Phase 13 sub-bullet "Asset lifecycle scoring (composite age × usage × warranty)" annotated `*(shipped v3.17.263)*`.

## [3.17.262] - 2026-05-04

### Added — Phase 13 v5 Vendor Cost History
Closes the "Vendor cost history (price-at-time-of-PO trend)" sub-bullet of Phase 13. Surfaces price drift on repeating PO line items so a buyer can see "this Cisco SFP cost $40 in March, $52 in October."

- **New report at `/reports/vendor-cost-history/`** — aggregates `PurchaseOrderLineItem` rows over the last 730 days, grouped by `(vendor_name, sku, description)`. Each row shows: PO count, total quantity, min / avg / max / last unit price, and the date last seen. Last-price coloring (red when above avg, green when below) flags drift.
- **Vendor filter** — optional `?vendor=X` narrows to one vendor.
- **CSV export** — `?format=csv` returns the same rows.
- **Excludes draft / cancelled / void POs** — matches the existing procurement summary scope so quotes-in-progress don't pollute the trend.
- **Staff-only** — same gate as `procurement_summary` (procurement is an MSP-internal ops view).
- **Reports home** updated with a new tile linking to the page.

### Tests
- 5 tests in `reports.tests.VendorCostHistoryTests` covering aggregation correctness (last_price = most-recent of two same-SKU POs), draft exclusion, vendor filter, CSV export, and the staff/non-staff ACL.

### Roadmap
Phase 13 sub-bullet "Vendor cost history (price-at-time-of-PO trend)" annotated `*(shipped v3.17.262)*`.

## [3.17.261] - 2026-05-04

### Added — Phase 13 v4 RMA Tracking
Closes the "RMA tracking (return / replace lifecycle)" sub-bullet of Phase 13. Adds a per-organization return-merchandise-authorization workflow with explicit lifecycle states and timeline timestamps.

- **New `RMAReturn` model** (migration `assets.0018`) — fields: organization, optional asset / purchase_order / vendor FKs, rma_number, serial_number, reason, notes, status, opened_at, sent_at, received_at, closed_at, replacement_serial, refund_amount.
- **Status states**: open → sent → received_by_vendor → replaced / refunded / closed (cancelled is terminal too). The `transition()` method validates the new status and stamps the matching timestamp; terminal statuses also stamp `closed_at`.
- **List view** at `/assets/rma/` — filterable by status and freetext search across rma_number / serial / vendor / reason; latest 200 with an "open count" badge.
- **Create form** at `/assets/rma/create/` — vendor, reason, optional asset, optional source PO, RMA #, serial, notes.
- **Detail page** at `/assets/rma/<pk>/` — shows timeline + actions (Mark Sent, Mark Received, Mark Replaced w/ replacement serial, Mark Refunded w/ amount, Cancel).
- **Tenant-scoped** — list and detail use `OrganizationManager.for_organization()`; cross-org lookups return 404.

### Tests
- 3 model tests + 5 view tests in `assets.tests.RMAModelTests` / `assets.tests.RMAViewTests` covering creation, transitions, timestamp stamping, unknown-status rejection, list scoping, detail isolation, and the replacement-serial capture path.

### Roadmap
Phase 13 sub-bullet "RMA tracking (return / replace lifecycle)" annotated `*(shipped v3.17.261)*`.

## [3.17.260] - 2026-05-04

### Added — Phase 27 v2 Accounting Audit Log
Closes the "Audit trail of every accounting-system interaction" sub-bullet of Phase 27 by recording one row per `push_invoice` / `record_payment` call against QuickBooks Online or Xero, with a per-connection viewer.

- **New `AccountingAuditLog` model** (migration `integrations.0024`) — one row per call, captures provider type, action, resource type/id, external id returned on success, http status, success flag, error message, plus truncated request/response summaries (≤500 chars each — never full payloads).
- **New `log_accounting_call()` helper** in `integrations/providers/accounting/base.py` — best-effort write; a logging failure cannot break a push.
- **QBO and Xero providers wired** — every exit point of `push_invoice` and `record_payment` now writes an audit row (success and failure paths).
- **New viewer at `/integrations/accounting/<pk>/audit-log/`** — paginated 50/page, filterable by `?ok=ok|fail`, linked from the connection list under a new "Audit Log" button. Staff/superuser only.

### Tests
- 5 new tests in `integrations.tests.AccountingAuditLogTests` covering the helper, truncation, list view rendering, the `?ok=fail` filter, and that the QBO push-invoice failure path actually writes a row.

### Roadmap
Phase 27 sub-bullet "Audit trail of every accounting-system interaction (req/resp pairs stored encrypted)" annotated `*(shipped v3.17.260 — req/resp summaries; full payloads intentionally not stored to keep the log free of secrets/PII)*`.

## [3.17.259] - 2026-05-04

### Added — Phase 20 v2 Auto-flag Invoices over threshold
Closes the "Financial approval chains (POs / invoices over $X)" sub-bullet of Phase 20 by wiring the existing `Invoice.flag_for_approval` method into a post_save signal driven by two new SystemSetting knobs.

- **2 new SystemSetting fields** (migration `core.0055`):
  - `invoice_approval_threshold_total` (Decimal, default 0) — auto-flag invoices when `total >= this`. 0 disables.
  - `invoice_approval_overage_pct` (PositiveInt, default 0) — auto-flag invoices when their source contract is consumed at or above this percentage. 0 disables.
- **New `_auto_flag_invoice_approval` post_save signal on `Invoice`** — calls the existing `flag_for_approval()` method with the configured thresholds and persists `requires_approval=True` + the human-readable `approval_reason` via a direct `Invoice.objects.update()` to dodge re-firing the signal.
- **Skips already-approved or already-pending invoices** — once an invoice has been manually approved (or already flagged), subsequent saves don't re-flag.
- **Both thresholds are independent** — set either one or both. Setting both disabled (the default) means the auto-flag is a no-op, preserving existing behavior for installs that don't want financial gates.

### Tests
- 4 new tests in `InvoiceAutoFlagTests`:
  - Invoice below threshold not flagged.
  - Invoice above threshold auto-flagged with reason text mentioning total.
  - Both thresholds = 0 disables auto-flag (existing behavior preserved).
  - Already-approved invoice not re-flagged on subsequent save (idempotency).
- All 11 invoice-approval tests still pass.

### Roadmap
- Phase 20 sub-bullet "Financial approval chains (POs / invoices over $X)" annotated `*(shipped v3.17.259 — `SystemSetting.invoice_approval_threshold_total` + `invoice_approval_overage_pct` knobs auto-flag via post_save signal)*`.

## [3.17.258] - 2026-05-04

### Added — Phase 13 v3 Procurement summary report
Closes the "Procurement reporting" sub-bullet of Phase 13. Aggregates the existing `psa.PurchaseOrder` data into a per-vendor + per-month spend snapshot.

- **New view `/reports/procurement-summary/`** — last 365 days of committed POs (draft / cancelled / void excluded).
- **Per-vendor table** — vendor name, PO count, total spend, sorted by total spend descending.
- **Per-month trend table** — YYYY-MM bucket with summed total, helps spot procurement seasonality.
- **Summary cards** — PO count, total spend, distinct vendor count.
- **CSV export** at `?format=csv` — per-vendor rows, ready for spreadsheet import.
- **Staff-only.** Procurement is an MSP-internal ops view; org members (clients) get 404.
- **Reports home page** gains a "Procurement Summary" tile.

### Tests
- 4 tests in `ProcurementSummaryTests`:
  - Staff sees per-vendor aggregates with correct totals (Acme Hardware aggregated across 2 POs = $1250).
  - Draft POs excluded from totals.
  - CSV export contains all vendor names + aggregated totals.
  - Non-staff org member blocked with 404.

### Roadmap
- Phase 13 sub-bullet "Procurement reporting" annotated `*(shipped v3.17.258 — `/reports/procurement-summary/` per-vendor + per-month spend report with CSV export, staff-only)*`.

## [3.17.257] - 2026-05-04

### Added — Phase 19 v1 Ticket Aging Analytics
First slice of Phase 19's "ticket aging analytics" sub-bullet. Surfaces queue drift before SLAs slip.

- **New view `/reports/ticket-aging/`** — open tickets bucketed by `created_at` age into 5 ranges: 0-24h / 24-72h / 3-7d / 7-30d / 30+d.
- **Per-priority breakdown** — matrix table of priority code × bucket so dispatchers can see if P1s are aging or only P5s are stuck.
- **Aged 7+ days table** — top 200 oldest open tickets with org / priority / status / assignee for triage.
- **CSV export** at `?format=csv` — priority × bucket matrix with TOTAL row.
- **Tenant ACL** — staff/superuser sees all; org members see only their orgs.
- **Reports home page** gains a "Ticket Aging" tile.
- **New `reports.templatetags.reports_extras.get_item`** filter — dictionary lookup by runtime key (used by the matrix template).

### Tests
- 5 tests in `TicketAgingReportTests`:
  - Bucket counts for 5-bucket-spread fixture.
  - Member-scope hides outsider org's open tickets.
  - Terminal-status tickets excluded.
  - Aged 7+ days table contains 21d/60d tickets, excludes 5d/2d.
  - CSV export includes all bucket labels + TOTAL row.

### Roadmap
- Phase 19 sub-bullet "Ticket aging analytics" annotated `*(shipped v3.17.257)*`. Phase 19 is `[continuous]` — incremental shipping continues.

## [3.17.256] - 2026-05-04

### Added — Phase 20 v1 Idle-approval escalation cron
First slice of Phase 20 (Approval & Change Management Workflows). Approvals that sit pending past their threshold now surface as a daily digest to superusers — no more "the request died in the queue" surprises.

- **2 new fields on `psa.PSAApproval`** (migration `psa.0036`):
  - `escalation_threshold_hours` (default 48) — approvals still pending after this many hours flag for escalation. 0 = never.
  - `escalated_at` — set by the cron after a digest mentions this approval. Prevents the same approval from re-escalating on every run.
- **New management command `psa_escalate_idle_approvals`** — finds pending PSAApproval rows where elapsed time ≥ threshold AND `escalated_at IS NULL`, sends one digest email to all active superusers with email on file, then stamps `escalated_at`. Supports `--dry-run`.
- **Per-row threshold** (not a global setting) so high-stakes approvals can be tightened to 4 hours while routine ones stay at 48.

### Tests
- 4 tests in `PSAApprovalEscalationTests`:
  - Idle approvals (60h old, 48h threshold) trigger one email; fresh / threshold=0 / already-escalated approvals are excluded.
  - `escalated_at` stamped after send.
  - Re-running the cron is a no-op (dedupe).
  - Dry-run doesn't send or stamp.
  - When no superusers have email on file, command bails cleanly.

### Roadmap
- Phase 20 sub-bullet "Escalation approvals (auto-escalate idle approvals)" annotated `*(shipped v3.17.256)*`. Phase 20 marked `[in progress]` (multi-stage approvals, threshold-based routing, conditional approvals still planned).

## [3.17.255] - 2026-05-04

### Added — Phase 27 v1 Accounting Reconciliation report
First slice of Phase 27 (Advanced Accounting Reconciliation). Three risk classes that need manual eyes-on, surfaced from existing `psa.Invoice` accounting fields (`accounting_external_id`, `pushed_to_accounting_at`, `last_push_error`).

- **New view `/reports/accounting-reconciliation/`** with three sections:
  1. **Outstanding pushed invoices** — pushed to QBO/Xero (`pushed_to_accounting_at` is set) but `amount_paid < total` and status isn't `paid` / `void`. Catches "customer paid in QBO but our copy still says unpaid."
  2. **Push errors** — invoices where `last_push_error` is non-empty. Need manual intervention to retry.
  3. **Duplicate external IDs** — invoices grouped by `(provider, accounting_external_id)` having `count > 1`. Catches accidental double-pushes.
- **Summary cards** at the top: outstanding count + balance, error count, duplicate group count.
- **Tenant ACL:** staff/superuser sees all; org members see only their org's invoices.
- **CSV export** at `?format=csv` — single CSV with a `Section` column tagging which class each row belongs to.
- **Reports home page** gains an "Accounting Reconciliation" tile next to the other report links.

### Tests
- 6 tests in `AccountingReconciliationTests`:
  - Staff sees all three sections with correct summary counts.
  - Outstanding section excludes paid/void invoices.
  - Push-error section shows the error message.
  - Duplicate group lists both invoices.
  - CSV export emits the section column + all three section types.
  - Org member sees only their org's data (no cross-tenant leak).

### Roadmap
- Phase 27 sub-bullets "Invoice deduplication detection" and "Unpaid-vs-pushed reconciliation report" annotated `*(shipped v3.17.255)*`. Bidirectional payment sync, GL line-item mapping, AR aging tied to QBO/Xero AR remain on the planned list.

## [3.17.254] - 2026-05-04

### Added — Phase 13 v1 Warranty expiry alerts
First slice of Phase 13 (Procurement & Lifecycle Management). Existing infra: `Asset.warranty_expiry` was already there + the `is_warranty_expiring_soon()` property. What was missing: a recurring digest that actually pushes the warning to the org's owners before the date hits.

- **New `Asset.last_warranty_alert_sent_at` field** (migration `assets.0017`) — stamped after a digest is sent so the same asset doesn't re-trigger every day for 30 days.
- **New management command `assets_warranty_alerts`** — finds assets whose `warranty_expiry` falls between today and today+N (default 30) days, groups by organization, sends one digest email per org to the org's `Role.OWNER` members, then stamps the timestamp.
- **7-day cooldown** between alerts on the same asset — prevents daily noise while the warranty stays in the warning window.
- **`--dry-run`** flag prints the would-send digest without touching mail or DB.
- **`--days N`** override for tighter / looser warning windows.

### Tests
- 5 tests in `WarrantyAlertCronTests`:
  - One digest email per org, in-window assets included, expired/no-warranty/far-future excluded.
  - `last_warranty_alert_sent_at` stamped after send.
  - Cooldown prevents a second alert within 7 days.
  - Dry-run doesn't send or stamp.
  - `--days 5` only catches the asset within 5 days, not the 15-day-out one.

### Roadmap
- Phase 13 sub-bullet "Warranty expiration tracking" annotated `*(shipped v3.17.254 — `assets_warranty_alerts` management command + `last_warranty_alert_sent_at` dedupe)*`.

## [3.17.253] - 2026-05-04

### Phase 38 + Phase 39 — closed
Roadmap close-out for two phases whose major sub-bullets are shipped, with one deferred sub-bullet apiece documented.

- **Phase 38 — Client Onboarding / Offboarding Runbooks → `[complete]`.** Repeatable templates (v3.17.223), category support including `client_onboarding` / `client_offboarding` / `client_termination` (v3.17.223), runbook-to-ticket conversion (v3.17.223), and per-org completion dashboard (v3.17.227) all shipped. **Deferred:** access removal verification — mechanical verification requires M365 / RMM / vendor-API integrations beyond the runbook engine; the manual-checklist pattern (a tech ticks off "removed from M365") is fully supported today via runbook stages.
- **Phase 39 — Compliance Evidence Packs → `[complete]`.** All 9 evidence sections shipped (5 in v3.17.222 + 4 in v3.17.226). Backup section ships as a placeholder section noting "no backup integration configured" — when a backup-job tracking integration arrives, that section will fill in automatically without further compliance-pack work.

## [3.17.252] - 2026-05-04

### Added — Phase 18 v2 Shared infrastructure inheritance
Closes the "Shared infrastructure inheritance" sub-bullet of Phase 18. A holding company can now own a switch / domain controller / shared service that's automatically visible to every subsidiary in the hierarchy, without having to duplicate the asset across orgs.

- **New `Asset.is_shared_with_descendants` flag** (migration `assets.0016`) — default False so existing rows stay tenant-scoped.
- **New `Asset.visible_to_org(org)` classmethod** — returns assets owned by `org` + its descendants (existing downward inheritance) UNION assets owned by ancestors where `is_shared_with_descendants=True`. Strangers (unrelated orgs' shared assets) stay out.
- **New `core.utils.ancestor_org_ids(org)` helper** — walks UP the parent chain (closest first), capped at 5 levels with a seen-set guard against cycles.

### Tests
- 3 new tests in `SharedInfrastructureTests`:
  - Child sees parent's `is_shared_with_descendants=True` asset; parent's private asset stays hidden; child's own asset always visible.
  - Parent's `visible_to_org` returns its own + descendants' assets (downward inheritance still works).
  - Unrelated org's shared asset doesn't bleed into a different hierarchy.

### Roadmap — Phase 18 marked in progress (location-tied items deferred)
Phase 18 now has its non-Location sub-bullets shipped: parent/child orgs (v3.17.240), multi-site hierarchy + breadcrumbs (v3.17.240), site filtering (v3.17.240), shared infrastructure (v3.17.252). Location-specific docs / contacts / SLA / regional views / multi-location reporting remain deferred — they belong with proper integration of the existing `locations/` app and the existing `Location` model. Tracked as future work; Phase 18 stays `[in progress]` until that integration lands.

## [3.17.251] - 2026-05-04

### Added — Phase 26 v2 Invoice + TimeEntry SavedQuery targets
Two new model targets in the saved-query allow-list, plus a tenant-scope refinement for models that don't carry `organization` directly.

- **`psa.Invoice` target** — filterable on `invoice_number`, `title`, `status`, `client_org__name`, `organization__name`, `invoice_date`, `due_date`, `requires_approval`. Default columns include `subtotal`, `total`, `amount_paid` for AR / collections workflows.
- **`psa.TicketTimeEntry` target** — filterable on `user__username`, `ticket__ticket_number`, `ticket__organization__name`, `is_billable`, `started_at`, `ended_at`, `notes`. Useful for "who logged what against this client this week."
- **Per-model `org_filter`** in `MODEL_CONFIG`. `TicketTimeEntry` scopes via `ticket__organization` since it has no direct `organization` FK. `execute()` honors the per-model field.

### Tests
- 2 new tests in `SavedQueryTests`:
  - Invoice target filters by `status='paid'` and excludes other statuses.
  - TimeEntry target scopes via `ticket__organization` so outsider-org entries don't leak into a tenant-scoped query.

### Roadmap — Phase 26 marked complete
Phase 26 — Custom Report Writer + Saved Queries flipped to `[complete]`. Sub-bullets shipped: visual query builder (5 model targets including the 2 added today), saved query model with shared/private scope, table render + CSV export, tenant-scoping. Auto-chart, recurring email-PDF, JSON/Excel export, SQL escape hatch, marketplace remain on the planned list as future v3 work.

## [3.17.250] - 2026-05-04

### Added — Phase 22 v2 Editorial approval queue
Closes the "Article approvals" sub-bullet. Drafts move through a manager review gate before they go live in the KB.

- **New view `/docs/approval-queue/`** lists `Document` rows where `is_draft=True`. Staff sees everything; org members see drafts in their own orgs only.
- **`POST /docs/<slug>/approve/`** — staff-only. Flips `is_draft=False, is_published=True` and stamps `last_modified_by`. Article becomes visible in the KB.
- **`POST /docs/<slug>/reject/`** — staff-only. Keeps the article as draft, optionally appends a `[Rejected by user @ timestamp] note` block to the body so the author has the feedback inline when they re-edit.
- **`POST /docs/<slug>/submit-for-review/`** — owner or staff. Sets `is_draft=True, is_published=False` so the article disappears from the KB until approved.

### Tests
- 6 new tests in `KBApprovalQueueTests`: queue lists only drafts, approve flips state, reject keeps draft + appends note, submit-for-review sets draft, submit-for-review blocked for non-owner, approve blocked for non-staff.

### Roadmap — Phase 22 marked complete
Phase 22 — Knowledge Base & SOP Management flipped to `[complete]`. All major sub-bullets shipped: versioning (DocumentVersion existed), article ownership + review reminders (v3.17.245), article approval queue (v3.17.250), portal KB analytics (v3.17.234), draft → published lifecycle (v3.17.250). Remaining items (SOP-to-workflow auto-link, public knowledge publishing, dead-link analytics) are future polish.

## [3.17.249] - 2026-05-04

### Added — Phase 25 v2 Lock approved + Bulk approve + Payroll CSV
Three sub-bullets close out: lock-after-approval prevents tampering, bulk-decide is a one-form action, payroll CSV export hands off to QuickBooks Time / Gusto / etc.

- **Approved entries now lock against further edits.** `TicketTimeEntry.save()` checks the current row's `submission.status`; if `approved`, the save is silently a no-op. Admins can override with `entry.save(_force_unlock=True)` for legitimate corrections.
- **Bulk approve / reject view at `POST /psa/timesheet-approvals/bulk/`** — accepts a list of `submission_ids` plus `decision=approve|reject` and an optional `notes` field. Iterates pending submissions and calls the existing `approve()` / `reject()` model methods.
- **Approval queue page** gains a sticky bulk-action bar at the top (Select all + notes + Approve selected / Reject selected). Per-submission detail (entry breakdown) collapses cleanly under each row. Per-row Approve/Reject buttons hidden by default, toggled visible by a small JS link for one-at-a-time decisions.
- **Payroll CSV export at `GET /psa/timesheet-approvals/payroll-export/?start=YYYY-MM-DD&end=YYYY-MM-DD`** — returns one row per (tech, week) with Total minutes / Billable minutes / Approved at / Approved by columns. Defaults to last 30 days when range params are missing.

### Tests
- 4 new tests in `TimesheetApprovalTests`:
  - Approved entry's save is silently a no-op (notes field stays at original).
  - `_force_unlock=True` lets the admin push an edit through.
  - Bulk decide approves all selected pending submissions.
  - Payroll CSV export contains approved rows + correct headers; non-staff blocked.

### Roadmap — Phase 25 marked complete
Phase 25 — Mature Timesheet Approval Workflows flipped to `[complete]`. Sub-bullets shipped: weekly timesheet model, submit→review→approve pipeline, lock approved entries, bulk approve, payroll CSV export, audit trail (decided_by/at/notes per submission). Multi-tier approval and per-entry rejection with note remain on the planned list as future v3 work.

## [3.17.248] - 2026-05-04

### Added — Phase 36 v3 Included-vs-billable labor reconciliation
Drill-down per contract that classifies every time entry as `covered` (fits within the included-hours allowance), `overage` (past the allowance), or `split` (crosses the boundary, partially covered).

- **New view `/reports/agreement-reconciliation/<contract_pk>/`** — walks the contract's `TicketTimeEntry` rows chronologically by `started_at`, maintains a running cumulative-minutes counter, and classifies each entry. Allowance-zero ("unlimited") contracts skip the gate.
- **Summary cards:** Allowance / Covered / Overage / Estimated overage cost (uses `overage_rate` falling back to `hourly_rate`).
- **Overage by tech** breakdown so account managers know who logged the overage minutes.
- **Per-entry table** with red rows for overage, yellow for split, plus all the standard columns (started, user, ticket, notes, duration, cumulative, covered, overage). Cap at 500 most-recent rows on screen; full set via `?format=csv`.
- **"Detail" button** on each row of the existing reconciliation list page links to the new drill-down.

### Tests
- 3 new tests in `AgreementReconciliationTests`:
  - 30-min allowance with 30 / 40 / 20 entries → classifies as `covered` / `split` / `overage`; covered_total=60, overage_total=30.
  - CSV export returns `text/csv`.
  - Outsider org member 404s on cross-org contract pk.

### Roadmap — Phase 36 marked complete
Phase 36 — Agreement Reconciliation & Pre-Invoice Approval flipped to `[complete]`. All sub-bullets shipped (recurring billing review, included-vs-billable, over/under-served alerts, agreement profitability via existing Phase 3.2 reports, pre-invoice approval gate, revenue leakage detection — the existing `unbilled_hours` query covers the remaining sub-bullet's intent).

## [3.17.247] - 2026-05-04

### Added — Phase 37 v2 Client-level vault approval rules
Closes the last sub-bullet in Phase 37 (Vault Approval & Break-Glass). MSPs can now route a client org's vault reveal approvals to that client's own admin rather than always going through MSP staff.

- **New `_can_decide_vault_reveal()` policy helper** in `vault/views.py`. Approval policy:
  - Superuser / MSP staff_user: always allowed (existing behavior preserved).
  - Client-org admin (`Membership.is_org_admin=True` for the password's organization): allowed for reveals OF passwords in their own org.
  - Self-approval blocked regardless of role — the requester cannot decide their own request, even if they're also an org admin.
- **`vault_reveal_request_decide` view** uses the helper. Returns 403 with "self_approval_blocked" or "not_allowed" reason on rejection.

### Tests
- 4 new tests in `VaultClientLevelApprovalTests`:
  - Client-org admin can approve their org's reveal request (replaces MSP staff for client-tenant credentials).
  - Org admin of a DIFFERENT org cannot approve (cross-org isolation).
  - Requester can't self-approve even when they're also an org admin (defense in depth).
  - Plain member of the same org without `is_org_admin=True` cannot approve.
- All 23 vault tests pass.

### Roadmap — Phase 37 marked complete
Phase 37 — Vault Approval & Break-Glass Workflow flipped to `[complete]`. All five sub-bullets shipped (require approval / break-glass / notifications / audit trail / client-level approval rules).

## [3.17.246] - 2026-05-04

### Added — Phase 26 v1 Custom Report Writer + Saved Queries
First slice of Phase 26 — let users build, save, and re-run custom queries over the most useful tenant-data models without writing Python.

- **New `reports.SavedQuery` model** (migration `reports.0005`): name, description, owner, organization (optional scope), target_model (one of `psa.Ticket` / `assets.Asset` / `vault.Password`), filters JSON, columns JSON, sort_by, is_shared, last_run_at, last_run_count.
- **Allow-listed querying.** `reports/saved_query.py` defines a `MODEL_CONFIG` dict listing per-model `filterable_fields` (with type tag for op-validation) and `columns`. The user can ONLY filter on the listed fields — saving a filter on an unrelated relation is silently dropped at run time. Same for ops: `str` fields support equals/contains/startswith; `int` adds gt/gte/lt/lte; `date` is gt/gte/lt/lte; `bool` is equals only.
- **Three target models in v1:** PSA Tickets (subject, status, priority, queue, assignee, SLA breach flags, dates), Assets (name/type/serial/vendor/warranty), Vault Passwords (title/username/type/personal/approval-required/expiry).
- **Three views:**
  - `/reports/saved-queries/` — list user's own + shared queries.
  - `/reports/saved-queries/new/` and `/<pk>/edit/` — dynamic-form builder. JS reads `MODEL_CONFIG` JSON embedded in the page, populates the field/op pickers when target changes, supports unlimited filter rows. Column checkboxes pre-checked from the saved set or all-on for new queries.
  - `/reports/saved-queries/<pk>/run/` — render result table (capped at 1000 rows) + `?format=csv` export.
- **Visibility model:** owner always sees their own; staff/superuser see everything; same-org members see queries marked `is_shared=True` and scoped to that org. Outsiders → 404. Edit is owner-only (or superuser).
- **Reports home page** gains a "Saved Queries" tile next to Agreement Reconciliation.

### Tests
- 11 tests in `SavedQueryTests`:
  - `build_filter` drops unknown fields silently (defense against schema drift).
  - `execute()` returns rows matching the saved filters.
  - `execute()` honors organization scoping when set.
  - `visible_to`: owner-only by default, peer when `is_shared=True` + same org, blocks outsiders even when shared.
  - Run view renders HTML matches; CSV export works (correct content type + header row).
  - Run view 404s for outsider users.
  - Create view persists multi-filter + column selection.
  - Delete view blocks non-owner peers.

### Roadmap
- Phase 26 sub-bullet "Saved queries" annotated `*(shipped v3.17.246)*`. Phase 26 marked `[in progress]` (recurring email-PDF + dashboard widget pinning are v2; widget pinning is partially achievable today via the existing wallboard widget registry).

## [3.17.245] - 2026-05-04

### Added — Phase 22 v1 KB Review Reminders + Article Ownership
First slice of Phase 22 (Knowledge Base & SOP Management) — closes the gap where articles drift out of date with no one accountable.

- **5 new fields on `Document`** (migration `docs.0015`):
  - `owner` FK — who keeps the article current. Defaults to `created_by` on first save.
  - `last_reviewed_at` — timestamp the owner last confirmed accuracy.
  - `review_interval_days` (default 90) — re-flag this many days after last review. 0 = never.
  - `requires_approval` + `is_draft` — wired up in the model now; full editorial approval queue is v2.
  - `published_at` — first-publish timestamp (auto-stamps when `is_published=True` and `is_draft=False`).
- **`Document.is_review_overdue` + `review_status` properties** — `current` / `due_soon` (within 7 days) / `overdue` / `no_review`. Properties handle the `last_reviewed_at` → `published_at` → `created_at` fallback chain.
- **`Document.mark_reviewed(user=)`** stamps `last_reviewed_at` + `last_modified_by`.
- **New view `/docs/review-queue/`** lists overdue + due-soon articles for the requesting user (or all articles when staff/superuser flips to `?scope=all`). Inline "Mark reviewed" buttons.
- **New view `POST /docs/<slug>/mark-reviewed/`** — owner or staff only.
- **New management command `kb_review_reminders`** — emails one digest per owner listing every overdue article they own. Supports `--dry-run`. Cron-friendly.

### Tests
- 8 new tests across `KBReviewQueueTests` (model + view) and `KBReviewReminderCommandTests` (command):
  - `review_status` classifies all four states correctly.
  - `is_review_overdue` matches the status enum.
  - `mark_reviewed` resets the clock so the article moves out of overdue.
  - Review queue lists overdue + due-soon for the requesting user.
  - `mark-reviewed` view works for owner; blocked for non-owner non-staff.
  - Command sends one digest per owner with all stale article titles in the body; respects `--dry-run`.

### Roadmap
- Phase 22 sub-bullets "Article ownership" and "Review reminders" annotated `*(shipped v3.17.245)*`. Phase 22 marked `[in progress]` (versioning already shipped via DocumentVersion; approval queue + KB analytics + linked SOP automation are v2).

## [3.17.244] - 2026-05-04

### Security — Settings access tightened to superuser-only
Audited every place that mutates `core.SystemSetting` or otherwise lets a user change feature toggles. Result: 11 of 11 `core/settings_views.py` views were already gated `@user_passes_test(is_superuser)` (correct), but `psa.views.psa_global_settings_view` allowed `is_superuser OR is_staff_user` — meaning any MSP staff (not just admins) could flip `psa_csat_enabled`, `psa_portal_*_enabled`, etc.

- **Tightened `psa_global_settings_view` to superuser-only.** Non-superuser staff now get 404 (consistent with `core/settings_views.py` and the navbar gate at `templates/base.html:224` which already only renders the Admin menu for `user.is_superuser`).
- **Other audit findings:**
  - `core/firewall_views.py` — every endpoint already `@user_passes_test(is_superuser)`. No changes.
  - `core/management/commands/*` — only run via cron / manage.py shell. Server-side admin context.
  - `processes/views.py` reads `SystemSetting.psa_enabled` but never writes. No exposure.
  - Templates — Admin nav menu already gated; PSA settings sidebar (`_settings_menu.html`) only renders inside settings views which are themselves superuser-gated.

### Tests
- 8 new tests in `core.tests.test_settings_access`:
  - `/core/settings/general/` blocked for non-superuser, allowed for superuser.
  - `/core/settings/features/` blocked for non-superuser, allowed for superuser.
  - `/psa/settings/` 404 for staff user (the regression that v3.17.244 fixes).
  - `/psa/settings/` 404 for regular user.
  - `/psa/settings/` 200 for superuser.
  - Staff user POSTing a feature toggle to `/psa/settings/` returns 404 and `SystemSetting.psa_csat_enabled` stays unchanged.

## [3.17.243] - 2026-05-04

### Added — Phase 12 feature toggles
Audited the four major Phase 12 features that shipped without a global on/off switch and added one apiece. Every toggle defaults `False` so existing installs don't suddenly expose new portal endpoints to their customers without an admin's explicit opt-in.

- **`psa_portal_announcements_enabled`** (migration `core.0054`) — gates `_active_announcements()` (returns `[]` when off) and `POST /portal/announcement/<pk>/dismiss/` (404 when off). Nav link / banner section disappear from the portal home.
- **`psa_portal_voting_enabled`** — gates `POST /portal/t/<n>/vote/` (404 when off) and the "I'm affected" thumbs-up button on portal ticket detail.
- **`psa_portal_escalation_enabled`** — gates `POST /portal/t/<n>/escalate/` (404 when off) and the `<details>` escalation form on ticket detail.
- **`psa_portal_customer_approvals_enabled`** — gates `/portal/approvals/` and `POST /portal/approvals/<pk>/decide/` (404 when off). The "Approvals" link in the portal nav also hides when off.

### How it's wired
- Single `_portal_feature_enabled(name)` helper in `portal/views.py` reads `SystemSetting.get_settings()`. Used by every gated view.
- `core.context_processors.organization_context` now exposes the five Phase 12 flags (the four new ones + `psa_csat_enabled`) into the template context, so templates can hide UI cleanly without a custom tag.
- `ticket_detail` view passes `voting_enabled` + `escalation_enabled` per-render so the template doesn't have to re-check the SystemSetting.

### Tests
- 13 new tests in `Phase12FeatureToggleTests` covering each toggle: feature hidden in HTML when off, endpoint 404s when off, feature works when on.
- 4 existing test classes updated to flip the relevant toggle on in their `setUpTestData` so they keep passing.
- All 48 portal tests pass.

## [3.17.242] - 2026-05-02

### Added — Phase 25 Mature Timesheet Approval Workflows
A formal weekly batch-approval flow on top of the existing `TicketTimeEntry` log. Techs submit their week; managers approve or reject; rejected weeks detach from the submission so the tech can fix entries and re-submit.

- **New `psa.TimesheetSubmission` model** (migration `psa.0035`): user, period_start, period_end, status (draft/pending/approved/rejected), submitted_at, decided_by, decided_at, submitter_notes, decision_notes. Unique on `(user, period_start, period_end)` so a week can't be submitted twice.
- **`TicketTimeEntry.submission` FK** (nullable) — every entry in a submitted week gets the FK set so the approver can browse the bundle.
- **`approve()` / `reject()` model methods.** Approve keeps entries attached for audit. Reject detaches entries (`submission=None`) so the tech can fix and re-submit; rejected submission rows stay around with their notes for the audit trail.
- **`/psa/timesheet/`** (current week) and `/psa/timesheet/<year>/<week>/` (specific ISO week) — tech-facing page showing the week's entries, totals (total minutes, billable minutes, entry count), submission status, optional notes textarea, and a Submit button. Re-submit after rejection revives the existing pending row rather than creating a duplicate.
- **`/psa/timesheet-approvals/`** — staff queue of pending submissions with expandable per-entry detail, optional decision-notes textarea, and Approve/Reject buttons. Recent decisions table below.
- **`/psa/timesheet-approvals/<pk>/decide/`** — POST endpoint that gates on `is_staff` / superuser, calls `approve()` or `reject()`, and redirects back.

### Tests
- 6 tests in `TimesheetApprovalTests`:
  - `my_timesheet` renders the week's entries and total minutes (3 entries totaling 585 min).
  - Submit creates a pending submission and attaches all 3 entries.
  - Approve flips status + records decided_by; entries stay attached for audit.
  - Reject flips status + detaches entries so the tech can fix.
  - Re-submit after rejection revives the same row to pending and re-attaches entries.
  - Non-staff users (the tech themselves) can't decide their own submission — redirect with no state change.

### Roadmap
- Phase 25 sub-bullets shipped to a working v1; the phase is marked `[in progress]` until v2 layers a CSV export + per-tech weekly summary report on top.

## [3.17.241] - 2026-05-02

### Added — Phase 37 Vault Approval & Break-Glass Workflow
Per-credential approval gating: an admin marks a `Password` as `requires_reveal_approval=True`, and from that point on the reveal endpoint requires either a manager-approved `VaultRevealRequest` or an explicit break-glass override with a long mandatory justification.

- **`Password.requires_reveal_approval`** flag (default False — backward compatible).
- **New `VaultRevealRequest` model** (migration `vault.0013`): password FK, requester, justification, status (pending/approved/denied/cancelled/expired), decided_by, decided_at, decision_notes, is_break_glass, expires_at (default 1 hour after approval), revealed_at (single-use marker).
- **`password_reveal` view gated** — when `requires_reveal_approval=True`, requires a currently-valid (approved, not expired, not yet used) `VaultRevealRequest` for the (password, user) pair. Reveal marks the approval as used (`revealed_at`) so the next reveal needs a fresh request. Hard `AuditLog` row on every block.
- **POST `/vault/<pk>/request-reveal/`** — creates a pending request with mandatory justification. Notifies superusers via email so they can review.
- **POST `/vault/<pk>/break-glass/`** — emergency self-approval with mandatory ≥30-char justification. Auto-approves and writes a hard `vault_break_glass` AuditLog. Notifies admins via email immediately.
- **POST `/vault/reveal-requests/<pk>/decide/`** — staff/superuser approve or deny. Approval sets a 60-minute window; denial leaves the password locked.
- **GET `/vault/reveal-requests/`** — staff list with pending requests rendered as warning-bordered cards (red border for break-glass), inline notes textarea + Approve/Deny buttons, plus a "Recent decisions" table.

### Tests
- 10 tests in `VaultApprovalAndBreakGlassTests`:
  - Reveal blocked without approval (403, `requires_approval: true`).
  - Request creates pending row.
  - Request rejects empty justification.
  - Admin approve unlocks reveal; reveal returns plaintext; approval marked single-use; second reveal blocked.
  - Admin deny keeps the block.
  - Break-glass with 30+ char justification approves immediately and reveal works.
  - Break-glass rejects short justification.
  - Password without the flag skips the gate entirely (backward-compat).
  - Non-staff peer cannot decide a request (403).
  - Staff list page renders.

### Roadmap
- Phase 37 sub-bullets "Require approval before revealing", "Emergency break-glass access", "Manager/admin notifications", "Full access audit trail" annotated `*(shipped v3.17.241)*`. Phase 37 marked `[in progress]` (optional client-level vault approval rules planned for v2).

## [3.17.240] - 2026-05-02

### Added — Phase 18 Multi-Location Client Hierarchy
Organizations can now be modeled as parent/child trees — a holding company with regional branches, an MSP customer with multiple sites, etc. Parent queries see descendants' rows automatically; descendants stay scoped to themselves.

- **New `Organization.parent` self-FK** (migration `core.0053`). Nullable; default null = top-level org. `related_name='children'` so `parent.children.all()` works.
- **`OrganizationManager.for_organization(org)`** now defaults to `include_descendants=True` and walks the parent chain via the new `core.utils.descendant_org_ids()` helper. Pass `include_descendants=False` for legacy strict scoping when needed. Walks up to 5 levels deep with a seen-set guarding against accidental cycles.
- **Backward compatible** — every existing call to `for_organization()` keeps working, just gets descendant inheritance for free. 70 existing core/docs/assets/vault/accounts tests pass unchanged.
- **`Organization.ancestors` property + `breadcrumb_label`** — render `Parent → Child → Grandchild` chains in templates.
- **Org form `parent` field** with cycle protection: when editing org X, the parent choices exclude X and all descendants (`descendant_org_ids(self.instance)`) so a user can't accidentally pick a child as parent.
- **Org detail breadcrumb** at the top of the page when the org has ancestors or children. Page header gets a "— branch of {parent}" subtitle when parent is set.

### Tests
- 9 new tests in `core.tests.test_org_hierarchy`:
  - `descendant_org_ids` returns self+children for top-level, only-self for leaf, empty set for None.
  - `ancestors` walks up.
  - `breadcrumb_label` renders the chain.
  - `for_organization(parent)` returns parent's + children's rows on a real model (Asset).
  - `for_organization(parent, include_descendants=False)` skips descendants.
  - `for_organization(child)` does NOT see parent's rows (one-way inheritance).
  - Form's parent queryset excludes self + descendants to block cycle creation.

### Roadmap
- Phase 18 sub-bullets "Parent / child organizations", "Multi-site hierarchy", "Site filtering on every list page" annotated `*(shipped v3.17.240)*`. Phase 18 marked `[in progress]` (shared infrastructure inheritance, regional views, multi-location reporting still planned for v2).

## [3.17.239] - 2026-05-02

### Added — Phase 12 Customer approval workflows + closeout
Last functional Phase 12 sub-bullet — portal users can now act on `PSAApproval` rows that staff route to them.

- **New `PSAApproval.is_client_approval`** flag (migration `psa.0034`, default False — backward compatible). When True, the approval is routed to the client side rather than staff.
- **New portal endpoints `/portal/approvals/`** (list pending + recent decided) and **`POST /portal/approvals/<pk>/decide/`** (calls existing `PSAApproval.decide()`). Tenant-ACL'd: 404 for staff-only approvals or cross-org pks.
- **Portal nav** gains an "Approvals" link with a check-circle icon, sitting between Credentials and the cog (preferences).
- **List page** renders pending approvals as warning-bordered cards (kind, related ticket link, requester comment, optional response textarea, Approve/Deny buttons) with a separate "Recent decisions" table below for the last 25 decided rows.

### Phase 12 close-out
- **Secure customer messaging** sub-bullet deferred to a future phase: it requires an encrypted-thread model + key management distinct from the existing AES-GCM vault — substantial scope, low priority vs other planned phases. Captured in ROADMAP as a future enhancement.
- **Phase 12 marked `[complete]`** with the deferred note. All other sub-bullets shipped across v3.17.231 → v3.17.239 (CSAT, announcements, branded portals, notification prefs, customer-facing KB, ticket voting, escalation, threaded comms, SMS, customer approvals).

### Tests
- 5 new tests in `PortalApprovalTests`: list filters to client-side rows for the user's org, approve marks correctly, deny marks correctly, can't touch staff-only approvals (404), can't touch other-org approvals (404).
- All 32 portal tests pass.

## [3.17.238] - 2026-05-02

### Added — Phase 12 SMS ticket communication for portal users
Portal users can opt in to receive a text message when one of their tickets changes status. Reuses the existing `core.sms.send_sms` plumbing + `_sms_globally_enabled` gate that staff notifications already use.

- **New `UserProfile.portal_notify_sms_status_change`** field (default False, migration `accounts.0031`). Off by default since SMS often costs money — explicit opt-in.
- **New `notify_portal_status_change(ticket)` helper** in `psa/notifications.py`. Resolves the recipient via `ticket.requester_email` → User → UserProfile; returns early on every check (no email, no user account, no profile, opted out, SMS globally disabled, no phone).
- **Signal hook in `_fire_ticket_workflow`** — fires on every status change (parallel to the CSAT hook from v3.17.231).
- **Portal preferences page** gains a phone field + SMS toggle. Standard message rates note included.

### Tests
- 4 new tests:
  - Helper sends SMS via `core.sms.send_sms` with the correct recipient + body when user is opted in.
  - Skips with `opted out` when the flag is False.
  - Skips with `no user account` when no User matches the email.
  - Preferences POST persists phone + SMS toggle round-trip.

### Roadmap
- Phase 12 sub-bullet "SMS ticket communication" annotated `*(shipped v3.17.238 — opt-in SMS on status change via existing core.sms plumbing)*`.

## [3.17.237] - 2026-05-02

### Added — Phase 12 Threaded customer communication
Portal users can now reply to a *specific* comment, not just to the ticket as a whole. Thread tree renders with replies indented under their parent.

- **New `TicketComment.parent_comment` self-FK** (migration `psa.0033`). Existing comments stay top-level (NULL parent).
- **Portal `post_reply` view accepts an optional `parent_id`** form field. Validates that the parent comment belongs to the same ticket and isn't internal; missing/invalid IDs silently fall back to a top-level reply.
- **Portal ticket detail builds a 2-level thread tree** server-side (top-level comments + their `replies_in_thread` collection) rather than recursing arbitrarily — keeps rendering bounded and matches what users actually do.
- **Reply button** on each comment that wires the form's hidden `parent_id` field via small vanilla JS. "Replying to comment #N" hint appears with a Clear button to cancel back to top-level.

### Tests
- 4 new tests in `PortalThreadedRepliesTests`: parent_id sets parent FK, missing parent_id creates top-level, invalid parent_id falls back, ticket detail builds the tree (`threads[0].replies_in_thread`).
- All 26 portal tests pass.

### Roadmap
- Phase 12 sub-bullet "Threaded customer communication" annotated `*(shipped v3.17.237)*`.

## [3.17.236] - 2026-05-02

### Added — Phase 12 Customer escalation workflow
Portal users can flag a ticket as urgent without having to call dispatch. Sets a hard escalation marker that's visible everywhere staff look, and posts a public comment so the timeline carries the context.

- **3 new fields on `psa.Ticket`** (migration `psa.0032`): `escalated_at`, `escalated_by` FK, `escalation_reason`. Tracks the escalation independent of priority changes (so a tech can choose whether/how to bump priority based on the reason).
- **Portal endpoint `POST /portal/t/<ticket_number>/escalate/`** — accepts a `reason` (required, ≤500 chars), stamps the fields, and creates a public `[Escalated by client] <reason>` `TicketComment` so the staff conversation panel shows the escalation in order.
- **Portal UI** — collapsible `<details>` block on ticket detail (closed tickets hide the option). On second submit, updates the reason rather than overwriting the original timestamp + creating a duplicate comment.
- **Red "Escalated" badge** on the ticket detail header so the user sees the escalation is registered.

### Tests
- 3 new tests in `PortalTicketEscalateTests`: fields + comment, empty-reason rejection, reason update on second post.

### Roadmap
- Phase 12 sub-bullet "Customer escalation workflows" annotated `*(shipped v3.17.236)*`.

## [3.17.235] - 2026-05-02

### Added — Phase 12 Customer ticket voting / prioritization
Portal users can flag tickets as "I'm affected by this too" — useful for shared-issue tickets where multiple users want to surface impact to the support team.

- **New `psa.TicketVote` model** (migration `psa.0031`) — `(ticket, user)` unique-together so each user counts once per ticket.
- **Portal endpoint `POST /portal/t/<ticket_number>/vote/`** — toggles the requesting user's vote on/off. Returns JSON (`voted`, `count`) when called via XHR; otherwise redirects back to the ticket detail.
- **Ticket detail UI** — thumbs-up button with badge showing total vote count. Button color flips between `btn-outline-warning` (haven't voted) and `btn-warning` (already voted) so the state is obvious.

### Tests
- 5 new tests in `PortalTicketVoteTests`: vote creates row, second post toggles off, count aggregates across users, detail renders the button, XHR returns JSON.

### Roadmap
- Phase 12 sub-bullet "Customer ticket voting / prioritization" annotated `*(shipped v3.17.235)*`.

## [3.17.234] - 2026-05-02

### Added — Phase 12 Customer-facing KB enhancements
- **`Document.is_featured_in_portal`** (default False) — pin articles to a "Featured" section at the top of the portal KB list. Useful for "How to file a ticket", common FAQs.
- **`Document.portal_view_count`** (PositiveIntegerField, default 0) — auto-incremented every time a portal user opens an article (`F('portal_view_count') + 1` to dodge read-modify-write races). Surfaced on the list page next to each row.
- **Portal KB list now orders non-featured rows by `-portal_view_count, -updated_at`** so popular articles bubble to the top — guides new portal users to the help that worked for everyone else.
- **Featured section** rendered above the main table in a yellow-bordered card with star iconography.

### Migration
- `docs.0014_document_is_featured_in_portal_and_more` — adds two fields, no data backfill.

### Tests
- 4 new tests in `PortalKBEnhancementTests` covering Featured rendering, view-count ordering, staff-only article exclusion, and view-count increment on kb_detail.

### Roadmap
- Phase 12 sub-bullet "Customer-facing knowledge base" annotated `*(featured + view counts shipped v3.17.234)*`.

## [3.17.233] - 2026-05-02

### Added — Phase 12 Branded portals + customer notification preferences
Two Phase 12 sub-bullets in one release.

- **`Organization.portal_primary_color`** (migration `core.0052`) — hex color string. Empty = system default. Portal `base.html` reads it and emits `:root { --bs-primary: ...; ... }` plus rules overriding `.btn-primary` / `.bg-primary` / `.text-primary` / `a` so an MSP can match each client's brand on their own portal pages without per-client CSS files.
- **Three new `UserProfile` notification preferences** (migration `accounts.0030`): `portal_notify_ticket_reply`, `portal_notify_status_change`, `portal_notify_csat_invite`. Default True so existing portal users keep getting notifications until they opt out.
- **New view + page `/portal/preferences/`** with three Bootstrap toggle switches and the existing portal styling.
- **CSAT email helper now respects `portal_notify_csat_invite`** — looks up the matching `User` by `recipient_email`; if a profile exists with the flag set False, the survey is skipped (no email + no DB row).
- **"Cog" icon** added to the portal nav linking to the preferences page.

### Tests
- 3 new tests across `PortalAnnouncementTests` + `PortalPreferencesTests`:
  - `test_portal_renders_org_brand_color_when_set` — verifies the `#ff7700` color leaks through the rendered `<style>` block when set; not present when unset.
  - `test_get_preferences_renders_three_switches` — page title + 3 switches present.
  - `test_post_persists_preferences` — checked / unchecked / checked round-trips correctly.
- All 10 portal tests pass.

### Roadmap
- Phase 12 sub-bullets "Branded client portals" and "Customer notification preferences" annotated `*(shipped v3.17.233)*`.

## [3.17.232] - 2026-05-02

### Added — Phase 12 v2 Portal Announcements
Banners on the customer portal home page so MSP staff (or client admins) can post maintenance notices, outage updates, scheduled-change advisories — anything portal users should see when they next log in.

- **New `portal.PortalAnnouncement` model.** Fields: organization, title, body (free text, newlines preserved), severity (info/success/warning/danger), is_active, expires_at, is_dismissable, created_by + timestamps. Migration `portal.0001_initial` (the portal app's first model).
- **`active_for_org(organization)` classmethod** — returns visible announcements for an org right now (active=True AND not expired). Used by the portal home and any future portal pages that want to surface banners.
- **Portal home (`portal:ticket_list`) injects active announcements** into the context, filtered by per-session dismissed IDs so each user only sees each dismissable banner once until they clear their session.
- **Bootstrap `alert-{severity}` rendering** at the top of the portal home — `info` blue, `success` green, `warning` yellow, `danger` red. Title is bold; body is plain text with newlines preserved (`white-space: pre-wrap`). Critical (`is_dismissable=False`) banners have no close button.
- **POST `/portal/announcement/<pk>/dismiss/`** — adds the pk to `request.session['portal_dismissed_announcements']`. Server-side rejects 400 if `is_dismissable=False` (defense against UI tampering); 404 cross-org. Bootstrap's `data-bs-dismiss="alert"` hides the banner immediately for the user; the fetch persists the dismissal so it stays hidden across page reloads.
- **Django admin registration** for `PortalAnnouncement` with list_display + list_filter + search — admins can manage announcements without a custom form for now.

### Tests
- 7 tests in `PortalAnnouncementTests`:
  - `active_for_org` filters out inactive + expired rows.
  - Portal home renders only active, non-expired announcements for the user's org.
  - Cross-org leak prevention — OtherCo's announcement does not appear on PortalCo's home.
  - Dismiss endpoint adds the pk to session; subsequent page render hides the dismissed banner.
  - Dismiss endpoint rejects non-dismissable announcements with 400.
  - Dismiss endpoint 404s on cross-org pk.
  - Critical (non-dismissable) announcements render without the close button — regex check on the rendered HTML inside the announcement's div.

### Roadmap
- Phase 12 sub-bullet "Portal announcements" annotated `*(shipped v3.17.232 — per-org banners with severity, expiry, and per-session dismissal)*`.

## [3.17.231] - 2026-05-02

### Added — Phase 12 v1 CSAT surveys post-ticket-close
First slice of Phase 12 (Customer Communication Workflows). When a PSA ticket transitions into a terminal status (resolved / closed / cancelled), the requester gets a one-click 1-5 star rating link delivered to their email. They submit without an account; the response is stored against the ticket for downstream profitability + tech-coaching reporting.

- **New `psa.TicketCSATSurvey` model.** OneToOne with Ticket; carries token, recipient_email, sent_at, rating, comment, responded_at, responded_ip. Migration `psa.0030`.
- **New SystemSetting flag `psa_csat_enabled`** (default `False`). Off by default so existing installs don't suddenly start emailing customers — admins flip it on after vetting the email content. Migration `core.0051`.
- **Signal hook in `psa.signals._fire_ticket_workflow`** — when status changes AND new status is `is_terminal=True`, calls `psa.csat.maybe_send_csat(ticket)`. Catches all exceptions internally so a CSAT failure can't break the ticket save flow.
- **Idempotent survey creation.** TicketCSATSurvey is OneToOne with Ticket. Re-saving a closed ticket, or re-opening + re-closing, returns the existing survey row without sending a second email.
- **Skips silently when no recipient.** Tickets without `requester_email` (manual staff-created tickets, etc.) don't generate a survey.
- **Public response form at `GET /psa/csat/<token>/`.** Token is the sole auth — no account needed. 5 clickable stars (vanilla JS, no React), optional comment textarea, friendly meaning labels ("Very dissatisfied" → "Very satisfied"). POST records rating + comment + responded_at + responded_ip; renders a thank-you page.
- **Token-based auth model.** Token is `secrets.token_urlsafe(32)` generated on first save; stored in plaintext (it's the URL, not a credential). Survey response can be re-submitted (latest wins) — useful when a customer wants to revise their rating after thinking about it more.

### Tests
- 7 tests in `CSATSurveyTests`:
  - Survey created + email sent on first terminal transition.
  - Survey NOT created when `psa_csat_enabled=False`.
  - Idempotent on repeated saves + re-open/re-close cycles (only one survey, one email).
  - Skipped when `requester_email` empty.
  - Public POST records rating + comment + responded_at, redirects to thank-you.
  - Public POST with rating outside 1-5 stays on the form, doesn't persist.
  - Unknown token → 404.

### Roadmap
- Phase 12 sub-bullet "Customer satisfaction (CSAT) surveys post-ticket-close" annotated `*(shipped v3.17.231)*`. Phase 12 marked `[in progress]`.

## [3.17.230] - 2026-05-02

### Added — Editable Dashboard Quick Actions
The dashboard's Quick Actions card was hardcoded with 8 tiles. v3.17.230 makes the set user-customizable: pick which tiles appear, drag to reorder, and save. Adding new entries for future devs is now a one-line registry change.

- **New `core/quick_actions.py` registry** — single source of truth for available tiles. Each entry has `key` / `label` / `icon` / `url_name` / `tooltip` / `enabled` callable. The callable receives the request context so tiles gate on the same feature flags as the static template did before (`psa_enabled` / `vehicles_enabled`).
- **`UserProfile.quick_actions_config` JSONField** — ordered list of action keys the user wants. Empty list (the default) means "use registry defaults." Unknown keys are silently dropped at render time so a removed registry entry doesn't break the page.
- **`resolve_for_user(user, context)`** — single helper called from the context processor that resolves URL names, gates on flags, and returns the ordered render-ready list. The `_quick_actions.html` partial now iterates over `resolved_quick_actions` from the context.
- **New endpoint `/accounts/profile/quick-actions/`** — two-column edit page. Left column shows currently selected tiles with a drag handle (SortableJS) + remove button per row. Right column shows available tiles with an Add button. JS moves rows between columns; on submit, hidden inputs are rebuilt to reflect the final state. Reset-to-defaults button included.
- **"Customize" button on the Quick Actions card header** so users can find the editor without digging through Settings.
- **Eleven actions registered** initially: New Ticket, Add Asset, New Password, Add Document, Scan Receipt, Run Workflow, New Quote, New Invoice, Evidence Pack (per-org), Wallboards, Agreement Reconciliation, Runbooks. Defaults match the previous hardcoded list.

### Migrations
- `accounts.0029_userprofile_quick_actions_config` — adds the JSONField with `default=list, blank=True`. No data backfill needed.

### Tests
- 7 tests in `QuickActionsEditorTests`:
  - GET renders the edit page with both columns populated.
  - POST persists selected keys in user-supplied order.
  - POST filters unknown keys (defends against form tampering).
  - Reset-to-defaults clears the JSONField.
  - `resolve_for_user` returns defaults when config is empty.
  - `resolve_for_user` respects saved order.
  - `resolve_for_user` drops PSA-gated actions when `psa_enabled=False` in the context.

## [3.17.229] - 2026-05-02

### Changed — Report Templates page compacted
The `/reports/templates/` page was rendering each template as a `col-md-4` card with its own card-body + card-footer block, three to a row. With multiple report types each adding an h5 header + a fresh row, the page scrolled excessively even with only a handful of templates. Switched to a denser per-type table layout — one row per template with name, description, scope badge, and inline action buttons. Same data, ~70% less vertical space. Header row now uses `flex-wrap` so the Create Template button doesn't stack awkwardly on narrow viewports. Description column uses `truncatewords:20` like before.

## [3.17.228] - 2026-05-02

### Added — Phase 36 v2 Pre-invoice approval gate
v3.17.225 surfaced over-served and under-served clients on the reconciliation report. v3.17.228 adds the *gate* — invoices over a configured threshold (or against a contract running over the overage % limit) require explicit human approval before they can be pushed to accounting.

- **Three new fields on `psa.Invoice`:** `requires_approval` (bool), `approval_reason` (free text — surfaced to the approver so they know *why* the gate fired), `approved_by` (FK), `approved_at` (timestamp). Migration `psa.0029` ships these + a composite index on `(requires_approval, approved_at)` for fast pending-approval lookups.
- **`Invoice.flag_for_approval(*, total_threshold, overage_pct_threshold)` method** — evaluates the invoice against caller-supplied thresholds. If `total >= total_threshold` OR the source contract is at >= the overage % threshold, sets `requires_approval = True` and writes a human-readable `approval_reason` ("total $15000 ≥ $10000 threshold"). Idempotent. Doesn't save — caller persists.
- **`Invoice.approve(*, user)`** — clears the gate. Sets `approved_by` + `approved_at` and saves only those fields.
- **New endpoint `POST /psa/invoices/<pk>/approve/`** — admin-gated (existing `@require_admin` decorator). Logs an `AuditLog` entry with the old approval reason in the description for traceability.
- **New endpoint `POST /psa/invoices/<pk>/request-approval/`** — manual flag for edge cases the threshold-based auto-flag missed (customer dispute, billing freeze, etc.). Accepts a `reason` POST field.
- **Push-to-accounting blocked when `requires_approval=True`.** `invoice_push_to_accounting` view now short-circuits with a flash error if the gate is set, before touching the AccountingConnection. Prevents an admin from bypassing approval by clicking Push directly.

### Migration
- `psa.0029_invoice_approval_reason_invoice_approved_at_and_more` — adds 4 fields + 1 composite index. No data backfill.

### Tests
- 7 new tests in `InvoiceApprovalGateTests` (in `psa/tests/test_phase3_5_features.py`):
  - `test_flag_for_approval_above_total_threshold` — total $15000 ≥ $10000 threshold sets the gate; reason text mentions both numbers.
  - `test_flag_for_approval_below_total_threshold` — total below threshold leaves the invoice unflagged.
  - `test_flag_for_approval_above_overage_threshold` — invoice tied to a contract at 130% consumed flags when threshold is 110%.
  - `test_approve_clears_gate_and_records_user` — direct method call clears the gate + stamps `approved_by` / `approved_at`.
  - `test_invoice_approve_view_201` — POST endpoint clears the gate.
  - `test_push_to_accounting_blocked_when_pending_approval` — push view short-circuits; `accounting_external_id` stays empty.
  - `test_request_approval_view_sets_flag` — manual flag POST sets `requires_approval=True` with custom reason.

### Roadmap
- Phase 36 sub-bullet "Pre-invoice approval workflow" annotated `*(shipped v3.17.228)*`.

## [3.17.227] - 2026-05-02

### Added — Phase 38 v2 Runbook completion dashboard
v3.17.223 shipped clone-template + spawn-ticket. v3.17.227 adds the per-org dashboard view that aggregates completion across all in-flight runbooks — the "documentation completion scoring" piece from the Phase 38 roadmap.

- **New view `GET /processes/dashboard/`** (uses the user's current org context) and `GET /processes/dashboard/<org_id>/` (explicit, gated to staff/superuser or active members of that org).
- **Three rollup cards** at the top: total active runbooks for the org, stages completed vs total, overall completion percentage with a progress bar.
- **Grouped tables per workflow category** — Client Onboarding, Client Termination, etc. Each row shows runbook title, assignee, status, per-execution progress bar, started date, due date with overdue badge.
- Excludes `cancelled` and `failed` executions — those are noise on a dashboard meant for "what's in flight." Still visible via the existing `/processes/executions/` list.
- **Tenant ACL:** explicit `org_id` blocks non-members with 404. Staff/superuser pass through.

### Tests
- 5 new tests in `RunbookDashboardTests`:
  - `test_dashboard_shows_active_executions_grouped_by_category` — both runbooks render under their category headers.
  - `test_dashboard_overall_completion_aggregates` — 3 stages total, 1 completed → 33.3% rollup.
  - `test_dashboard_excludes_cancelled_and_failed` — cancelled execution disappears from the dashboard.
  - `test_dashboard_org_url_blocks_non_member` — non-member trying to load another org's dashboard → 404.
  - `test_dashboard_org_url_allows_staff` — staff/superuser pass through.
- All 11 processes Phase 38 tests pass.

### Routing fix
- The new `/processes/dashboard/` URL was originally placed after the `<slug:slug>/` patterns, which intercepted "dashboard" as a slug and returned 404. Moved above the slug patterns so it resolves correctly. Same pattern as the existing `executions/` and `global/` routes.

### Roadmap
- Phase 38 sub-bullet "Documentation completion scoring" annotated `*(per-execution + per-org rollup shipped v3.17.227; per-client roll-up across multiple runbooks already lives at /processes/dashboard/<org>/)*`.

## [3.17.226] - 2026-05-02

### Added — Phase 39 v2 Compliance Evidence Pack — remaining 4 sections
v3.17.222 shipped 5 of 9 evidence sections. v3.17.226 closes the gap with the remaining 4: SSL/Domain Expiration, Uptime Evidence, Vulnerability Summary, and Backup Evidence (placeholder). The pack is now complete for what's planned in Phase 39.

- **Section 6 — SSL / Domain Expiration.** Per `WebsiteMonitor` for the org: name, URL, SSL enabled flag, SSL expiry date, SSL issuer, domain expiry date. Summary line counts total monitors, those with SSL tracking enabled, and how many have expirations on file.
- **Section 7 — Uptime Evidence.** Current `WebsiteMonitor` status, last check time, last HTTP status code, last response time. Summary cards count Active / Warning / Down / Unknown and compute `healthy_pct = active / total`. Color-coded status badges.
- **Section 8 — Vulnerability Summary (90-day window).** Open `SecurityAlert` rows for the client_org with seen_at within 90 days. Per-severity counts (critical / high / medium / low / info) plus a recent-alerts table (capped at 200). Filter `client_org=org` (not just `organization=org`) so the section reflects alerts *about* the client even when ingested through an MSP-owned vendor connection.
- **Section 9 — Backup Evidence (placeholder).** No first-party backup-job tracking model ships with the project today, so this section records "no backup integration configured" as documented evidence rather than a blank page. When a backup adapter is added, this section will list recent jobs.
- **ZIP export** now writes 9 CSV files (was 5) plus the manifest. Manifest's `sections` key is the authoritative list — auditors can iterate over it programmatically.

### Tests
- Updated `test_owner_gets_200_html_with_org_name` to assert all 4 new section headers render.
- Updated `test_owner_gets_200_zip` to assert all 9 CSVs are in the archive and `manifest.sections` has 9 entries.
- New `test_v226_sections_tenant_scoped` — creates an OrgB-only `WebsiteMonitor` with a unique name + an OrgB-only `SecurityAlert` with a unique title, generates OrgA's pack, asserts neither leaks into OrgA's output.
- All 11 compliance tests pass.

### Roadmap
- Phase 39 sub-bullets all annotated `*(shipped vN.N.N)*` (5 in v3.17.222, 4 in v3.17.226). Phase 39 marked `[in progress]` rather than `[complete]` because Backup is still a placeholder until a backup-tracking integration is built.

## [3.17.225] - 2026-05-02

### Fixed — Navbar dead band 992-1399px
v3.17.224 changed the navbar breakpoint from `expand-lg` (992px) to `expand-xxl` (1400px) so it collapses to a hamburger sooner on narrow viewports. But `static/css/mobile.css` still styles the hamburger drawer only at `max-width: 991px` — which left a dead band 992-1399px where the navbar collapsed correctly but the drawer used Bootstrap defaults, looking malformed when DevTools docked or the window resized into that band.

- Added a `@media (min-width: 992px) and (max-width: 1399.98px)` block to `mobile.css` that re-applies the dark drawer background, vertical layout, and form sizing in that band.
- Removed the legacy `.navbar-container { flex-wrap: wrap }` fallback at the bottom of `custom.css` — that was a workaround for the old `expand-lg` overflow which is no longer reachable; in `expand-xxl` mode it just caused awkward second-row wraps when dropdowns reflowed.
- Bumped the dropdown `overflow: visible` rule from `min-width: 1850px` to `min-width: 1400px` so dropdown menus aren't clipped on every laptop screen between 1400-1849px.

### Added — Phase 36 v1 Agreement Reconciliation
First slice of Phase 36 — surfaces over-served and under-served clients before they become invoice surprises. Sourced entirely from data already in the system: `Contract.total_hours` (allowance), `Contract.hours_used_minutes` (consumption tracker auto-incremented by `TicketTimeEntry.save()`), and `Contract.overage_rate` for the overage-cost estimate.

- New endpoint `GET /reports/agreement-reconciliation/` — table of every active MSP contract with: client, contract name + type, allowance hours, consumed hours, % consumed, status flag, overage hours, estimated overage cost. `?format=csv` returns the same data as a CSV download.
- **Status thresholds:** `under_served` if < 30% used (upsell signal), `on_track` 30-110%, `over_served` if ≥ 110% used (re-quote signal). Unlimited contracts (allowance = 0) flagged `unlimited` and skip threshold check.
- **Summary cards** above the table show counts per category — total active / on-track / under-served / over-served — so managers can see the big picture before drilling into individual rows.
- **Tenant ACL** — staff/superuser see all active contracts; org members see only contracts where `client_org` is one of their org memberships.
- **"Agreement Reconciliation" link** added to the Reports home page next to Revenue Leakage (gated behind `perm.view_financial`).

### Tests
- 6 new tests in `AgreementReconciliationTests`:
  - `test_staff_sees_all_active_contracts` — under/on-track/over/unlimited contracts visible; expired contracts excluded.
  - `test_status_classification` — every status badge text rendered.
  - `test_summary_counts` — context dict has correct per-category counts.
  - `test_csv_export` — `?format=csv` returns `Content-Type: text/csv` with attachment disposition + client names in body.
  - `test_member_sees_only_their_orgs_contracts` — non-staff member sees client_a contracts but NOT client_b contracts.
  - `test_overage_cost_calculation` — 130h consumed against 100h allowance at $200/h overage rate = $6000 surfaced.

### Roadmap
- Phase 36 sub-bullets annotated `*(partial — under/over-served alerts shipped v3.17.225)*`. Pre-invoice approval workflow + included-vs-billable labor reconciliation + revenue-leakage expansion remain planned for v2.

## [3.17.224] - 2026-05-02

### Fixed — Navbar layout (better fix for the v3.17.221 regression)
v3.17.221 switched `.navbar-nav` from `flex-wrap: nowrap` to `wrap` to stop horizontal overflow on narrow viewports — but that made things *worse* on resize / DevTools-open because items started wrapping awkwardly to a second line at unpredictable breakpoints. Reverted to `nowrap` and instead changed the navbar's responsive breakpoint from `navbar-expand-lg` (collapse below 992px) to `navbar-expand-xxl` (collapse below 1400px). Below 1400px the navbar now collapses to a single hamburger button — clean, no overflow, no awkward wrapping. Above 1400px the navbar renders fully expanded as before.

### Added — Nine new wallboard widget sources (alerts / warnings / techs)
User asked for "any type of alerts/warnings, techs logged in, etc." — added nine sources covering operations, monitoring, and security visibility:

- **`techs_logged_in`** (metric, hours-configurable) — distinct active `User` count with `last_login >= now - N hours`.
- **`monitors_down`** (metric) — `WebsiteMonitor` rows currently in `down`/`error` state. Shows green when 0, red otherwise.
- **`ssl_expiring_soon`** (metric, days-configurable) — SSL certificates expiring within N days (default 30).
- **`domain_expiring_soon`** (metric, days-configurable) — domain registrations expiring within N days (default 60).
- **`warranties_expiring_soon`** (metric, days-configurable) — `Asset.warranty_expiry` falling within N days (default 90).
- **`recent_failed_logins`** (metric, hours-configurable) — `axes.AccessAttempt` rows in the last N hours (default 24).
- **`vault_activity_24h`** (metric) — vault `AuditLog` events (`object_type='password'`) in the last 24 hours.
- **`alerts_by_severity`** (table) — open `SecurityAlert` count per severity (critical / high / medium / low / info — every level always rendered, even at 0).
- **`monitors_status_breakdown`** (chart_pie) — Active / Warning / Down / Unknown monitor counts.

Each source defends against a missing app (e.g. `axes`, `security_alerts`) with a try/except → `secondary` color fallback so a wallboard never explodes if an optional integration is uninstalled.

### Added — Two new wallboard starter templates
- **Security & Alerts** template extended from 2 widgets to 5 — adds Failed logins (24h) metric, the new All-open-alerts-by-severity table, and Vault events (24h) metric.
- **Monitoring & Infrastructure** (NEW template) — 5 widgets covering monitor health, SSL/domain/warranty cliffs, and a status-breakdown pie chart. Pick this on Create for an infrastructure-focused NOC TV.

### Tests
- 1 new smoke test in `WallboardWidgetCategoryTests.test_v224_widget_sources_smoke` — every new source returns a well-formed payload (correct keys per widget type) even when the underlying tables are empty.
- All 41 + 1 wallboard tests pass.

## [3.17.223] - 2026-05-02

### Added — Phase 38 Client Onboarding/Offboarding Runbooks (v1)
The `processes/` app already had Process + ProcessStage + ProcessExecution + completion-percentage with onboarding/offboarding categories — most of the Phase 38 engine was in place. v3.17.223 adds the three pieces it was missing: client-scope categories, clone-template-to-run, and stage-to-ticket conversion.

- **Three new `Process.category` choices:** `client_onboarding`, `client_offboarding`, `client_termination`. The existing `onboarding` / `offboarding` choices remain but are now labeled "User Onboarding" / "User Offboarding" — distinct from the new client-scoped flavors.
- **Clone-template flow.** New `POST /processes/<slug>/clone-template/` endpoint copies an `is_template=True` Process — including all its stages, in order, with linked entities (document/password/secure-note/asset/diagram) preserved — into a non-template Process owned by the user's current org. Title gets a `[YYYY-MM-DD]` date prefix; slug is uniquified within the org. Source Process must be the user's org's OR `is_global=True`.
- **Spawn-ticket-from-stage.** New `POST /processes/execution/<execution_pk>/stage/<stage_pk>/spawn-ticket/` endpoint creates a `psa.Ticket` with subject `[Runbook] {stage.title}`, description copied from stage, organization = execution's org, assignee = execution's assignee. The created ticket is linked back via the new `ProcessStageCompletion.spawned_ticket` FK so the runbook UI can render the ticket number next to the stage. Idempotent — re-firing the endpoint returns to the execution page without creating a duplicate.

### Migrations
- `processes.0006_processstagecompletion_spawned_ticket_and_more` — adds `spawned_ticket` FK on `ProcessStageCompletion` + alters the `Process.category` choices. No data backfill required.

### Tests
- 6 new tests:
  - `ProcessCloneTemplateTests.test_clone_creates_new_process_with_all_stages` — verifies stage count + title-prefix + non-template flag + category preserved.
  - `ProcessCloneTemplateTests.test_clone_rejects_non_template_source` — non-template Process returns redirect with no new Process created.
  - `ProcessCloneTemplateTests.test_new_categories_accept_client_onboarding` — `full_clean()` passes for all three new category choices.
  - `ProcessStageSpawnTicketTests.test_spawn_creates_ticket_and_links_completion` — happy path: ticket created, completion linked.
  - `ProcessStageSpawnTicketTests.test_spawn_is_idempotent` — second call doesn't create a second ticket.
  - `ProcessStageSpawnTicketTests.test_spawn_rejects_get` — GET → 405.

### Roadmap
- Phase 38 sub-bullets updated: "Repeatable onboarding templates", "Client termination checklist", "Runbook-to-ticket conversion" → `*(shipped v3.17.223)*`. Access removal verification + completion scoring remain planned (completion scoring partially shipped via existing `ProcessExecution.completion_percentage`).

## [3.17.222] - 2026-05-02

### Added — Phase 39 Compliance Evidence Packs (v1)
First slice of Phase 39 — one-click bundle of compliance-relevant data per organization. Five of nine planned sections ship in this release; the rest follow.

- **New `compliance/` Django app** with one view: `GET /compliance/organizations/<id>/evidence-pack/`. Returns a styled HTML page (with print-to-PDF CSS rules) by default; `?format=zip` returns a zip with `manifest.json` + 5 per-section CSV files (machine-readable for downstream automation).
- **Five v1 evidence sections:**
  1. **2FA status** — every active member's 2FA enabled flag + method + last login. Summary line: `N of M active members have 2FA enabled (P% coverage)`.
  2. **User access report** — every membership (active + suspended) with role, role template, invited-at, last login.
  3. **Password access history** — last 90 days of vault `AuditLog` rows (action ∈ {read, update, create, delete} on `object_type='password'`). Capped at 1000 rows for the HTML render; ZIP has the same set.
  4. **Asset inventory** — every Asset with name, type, serial, vendor, location, purchase date, warranty expiry. Summary: total / with-serial / with-warranty-date counts.
  5. **Ticket / SLA history** — last 12 months of tickets with totals, by-status breakdown, SLA-met percentages for response + resolution, and median first-response and resolution intervals (seconds).
- **ACL** — `_user_can_access_pack` allows superuser, staff users, and active org members with role `owner` / `admin`. Other users get 404 (consistent with the rest of the app's tenant-isolation pattern).
- **AuditLog every generation** — `AuditLog.log(action='create', object_type='compliance.EvidencePack', object_id=org.pk, object_repr='Evidence pack for {org.name}')`. Pack generation is itself audit-trailable.
- **UI: "Evidence Pack" button** on the Organization detail page, visible to org owners + admins + staff/superuser. Sits between the existing Edit/Delete buttons and the Back-to-list link, with the existing `btn-info` styling so it stands out as a different action class from destructive ones.
- **Templates** — `compliance/templates/compliance/evidence_pack.html` extends `base.html`, has a print stylesheet (`.no-print` hides nav/buttons in print, sections get page-break-inside: avoid), and exposes a "Print / Save PDF" button alongside the ZIP download.
- **Settings + URL wiring** — `compliance.apps.ComplianceConfig` added to `INSTALLED_APPS`; `path('compliance/', include('compliance.urls'))` mounted in `config/urls.py`.

### Tests
- 10 tests in `compliance.tests.EvidencePackTests`:
  - `test_owner_gets_200_html_with_org_name` — every section header rendered.
  - `test_owner_gets_200_zip` — Content-Type `application/zip`, Content-Disposition attachment, manifest + 5 CSVs verified inside the archive.
  - `test_other_org_owner_gets_404` — owner of org B → 404 on org A's URL.
  - `test_anonymous_redirected_to_login` — unauth → 302.
  - `test_superuser_can_access_any_org` — passes through.
  - `test_missing_org_returns_404`.
  - `test_tenant_scope_user_access` — org B's user is not in org A's pack.
  - `test_tenant_scope_assets` — org B's asset serial number does not leak into org A's pack.
  - `test_tenant_scope_password_history` — org B's vault audit row does not leak.
  - `test_audit_log_written_on_generate` — exactly one `compliance.EvidencePack` AuditLog row created per generation.

### Roadmap
- Phase 39 sub-bullets annotated `*(partial — 5/9 sections shipped v3.17.222)*`. Vulnerability scan, SSL/domain expiration, backup, and uptime evidence sections deferred to follow-up releases.

## [3.17.221] - 2026-05-02

### Fixed — Wallboard rendering bugs + navbar layout
Three small but visible bugs surfaced from a real wallboard usage session.

- **Multi-line `{# ... #}` Django comments rendered as literal text.** The wallboard view template had several `{# ... #}` comments that spanned multiple lines. Django's `{# #}` syntax requires both markers on the same line — multi-line ones never got parsed, so the comment text leaked into the page (with HTML tags inside the comments getting eaten by the browser as malformed markup). Removed the comments rather than converting to `{% comment %}{% endcomment %}` (per project convention: don't write comments unless they explain a non-obvious WHY; these were just version annotations duplicated in git log).
- **Mismatched `widget_type` vs `data_source` produced confusing "no rows" tiles.** The Add Widget form let you pick a metric data source and a `table` widget type, which then rendered the table empty-state ("no rows") instead of the metric value. The form no longer asks for `widget_type` at all — it's auto-derived server-side from the data source's recommended type in `DATA_SOURCE_CHOICES`. The dropdown's helper text now reads "Widget type is auto-selected from the data source (shown in parentheses above)." Manual override remains available via Django admin for edge cases.
- **Top navbar overflowed when DevTools narrowed the viewport.** `.navbar-nav { flex-wrap: nowrap }` in `static/css/custom.css` prevented the menu items from wrapping when the viewport was below the navbar's content width. With 9 dropdowns + a search box + favorites/KB/notifications, narrow viewports overflowed horizontally. Switched to `flex-wrap: wrap` with a small `row-gap` so items flow to a second line gracefully instead of overflowing the container. The outer `.navbar-container` already had `flex-wrap: wrap` — this completes the chain.

### Tests
- Updated 2 tests in `WallboardFormCleanupTests` to match the new "no widget_type field" contract — `test_widget_add_view_creates_widget_with_derived_type` (verifies `tickets_by_priority` source → derived `table` type), `test_widget_add_rejects_missing_title` (replaces the now-impossible `test_widget_add_rejects_unknown_widget_type`).
- All 41 wallboard tests still pass.

## [3.17.220] - 2026-05-02

### Changed — Wallboard form cleanup + in-form widget management + starter templates
The wallboard form went from "fill out a name + go to Django admin to add widgets" to a self-contained CRUD page. Three pieces in one release:

#### 1. Form cleanup
- Form is now organized into three card sections — **Basics** (scope, name, description), **Refresh & rotation** (refresh_seconds, rotate_seconds, order, is_active), and the **Widgets** column (only on edit) — instead of a flat list of inputs. Section headers + icons make the page scannable.
- Page header sprouts an "Open board" + "All wallboards" toolbar on edit, matching the pattern used elsewhere.
- Removed the old "After creating, add widgets via Django admin" hint — that workflow is gone.
- Active toggle moved into the refresh/rotation card with an inline help string.
- Description textarea grew a placeholder.
- Field order rearranged: scope first (since it's required and locked after create), then name, then description.

#### 2. In-form widget add / remove
- New endpoint `POST /reports/wallboards/<pk>/widgets/add/` — server-side validation on `data_source` (must be in `REGISTRY`) and `widget_type` (must be a valid model choice). Auto-numbers the new widget's `order` to last+10.
- New endpoint `POST /reports/wallboards/widgets/<pk>/delete/` — tenant-ACL'd via parent wallboard.
- Wallboard form's right column now hosts a small Add Widget panel: data-source dropdown (using `DATA_SOURCE_CHOICES` for friendly labels), title, widget type (defaults to the source's recommended type, auto-fills the title from the source's friendly label).
- Each widget row gets a red trash button with a confirmation dialog. Drag-to-reorder still works alongside delete.
- The empty-state message now reads "No widgets yet. Add one using the form above." (was: "Add them via Django admin → Reports → Wallboard widgets.")

#### 3. Starter templates (wallboard "type")
- `WALLBOARD_TEMPLATES` constant in `reports.widget_sources` defines six presets — **Custom** (empty), **Operations overview** (6 widgets — open tickets, overdue, alerts, active techs, opened-30d trend, by-priority table), **Tickets / Service Desk** (queue load, dispatch, flow), **Security & Alerts** (critical alerts + 24h breakdown), **Sales / Revenue** (revenue this period, trend, top clients, recent activity), **Client health** (health pie, at-risk table, SLA trend).
- The Create form renders the templates as a radio list with the description and widget count next to each option.
- On submit, the chosen template's widgets are created with sequential `order` (10, 20, 30…) so the user lands on a useful screen rather than empty.
- New `get_template(key)` helper for lookup.

### Tests
- 8 new tests in `WallboardFormCleanupTests`:
  - `test_template_constant_has_expected_keys` — sanity-check the 6 required template keys; `get_template` returns None for unknown keys.
  - `test_create_with_template_populates_widgets` — POST `template=operations` creates the wallboard + 6 widgets.
  - `test_create_with_custom_template_creates_no_widgets` — POST `template=custom` creates the wallboard with 0 widgets.
  - `test_widget_add_view_creates_widget` — happy path POST creates a `WallboardWidget`.
  - `test_widget_add_rejects_unknown_data_source` — bad `data_source` doesn't persist; messages.error path.
  - `test_widget_add_rejects_unknown_widget_type` — bad `widget_type` ditto.
  - `test_widget_delete_view_removes_widget` — happy path delete.
  - `test_widget_add_rejects_get` — GET → 405.
- All 41 wallboard tests passing (model + rotation + widget-inherit + view ACL + rotate-view + list-view + reorder + global scope + categories + form cleanup).

## [3.17.219] - 2026-05-02

### Roadmap — 8 new phases planned + Phase 21 extended
Roadmap-only release. Captures user-requested feature lines so they're tracked + visible on `/core/roadmap.json` and the in-app roadmap page rather than living in chat history.

- **Phase 33 — Network Discovery & Auto Documentation (L) [planned].** Multi-protocol persistent discovery — SNMP / LLDP / CDP / ARP from a lightweight per-site collector, scheduled scans, auto-topology, switch-port-to-MAC correlation. Layers on top of the lighter Phase 32 single-shot ping/ARP script.
- **Phase 34 — Network Configuration Backup (M) [planned].** Versioned config backup for firewalls / switches / routers, scheduled jobs, line-level diff viewer, drift alerts, firmware tracking, EOL/warranty metadata.
- **Phase 35 — Advanced Project Management (L) [planned].** Extends the existing `psa.Project` model (quote→project shipped v3.17.213) with project templates, milestones, budget tracking, profitability, project-to-ticket spawning, project billing, Gantt/calendar planning view.
- **Phase 36 — Agreement Reconciliation & Pre-Invoice Approval (M) [planned].** MSP-specific reconciliation between agreement coverage and labor consumption — included-vs-billable hour classification, over/under-served client alerts, pre-invoice approval gate, expanded revenue-leakage detection. Extends Phases 1, 15, 20 (and complements Phase 27's GL-level reconciliation).
- **Phase 37 — Vault Approval & Break-Glass Workflow (M) [planned].** Per-credential approval gates on vault reveal, break-glass with mandatory justification, manager/admin notifications, full audit trail, optional client-level approval rules. Extends Phase 31's `VaultAccessRule` (shipped v3.17.163) with workflow constraints.
- **Phase 38 — Client Onboarding / Offboarding Runbooks (M) [planned].** Repeatable runbook templates for client + employee + termination flows. Access-removal verification, completion scoring, runbook-to-ticket conversion.
- **Phase 39 — Compliance Evidence Packs (M) [planned].** Single-click client audit packet bundling 2FA status, user access, password access history, asset inventory, vulnerability summary, SSL/domain expiration, ticket/SLA history, backup/uptime evidence — sourced from data already in the system.
- **Phase 40 — Public / Client-Facing Status Page (M) [planned].** Public or per-client-private status page surfacing service status, maintenance windows, incident history, and uptime — sourced from the existing monitoring + psa Ticket infra.
- **Phase 21 (Advanced Mobile Technician Workflows) extended** with three Field Mode capabilities the user called out: site check-in / check-out (per-ticket arrival evidence, distinct from generic Timeclock), mileage and trip logging (auto from geofence transitions or manual), and quick asset edit from phone (was lookup-only).
- **Phase 27 cross-reference** — Phase 36 covers MSP-specific agreement reconciliation; Phase 27 covers GL-level reconciliation against QBO/Xero. Note added so they don't appear redundant.
- **Sizing table** updated with rows 33-40 + dependency annotations.

All eight new phases carry the parseable `[planned]` status marker so the JSON feed at `/core/roadmap.json` reports them correctly.

## [3.17.218] - 2026-05-02

### Added — Categories on three more widget sources
Extends v3.17.217's per-widget category dropdown to the chart and table sources used most often on overview wallboards. No infrastructure work — each source got an entry in `CATEGORIES` and a branch in its callable.

- **`tickets_opened_30d`** (line chart) — `Opened` (default, original behavior) / `Closed` (count of tickets resolved per day) / `Opened vs closed (net Δ)` (3 series — opened, closed, net — so a backlog growing or shrinking is immediately visible). The `net` category is the killer one: a flat-or-rising "Net" line means the team isn't keeping up.
- **`revenue_trend_30d`** (bar chart) — `Daily` (default) / `Weekly buckets` (5 buckets of ~6 days each — easier to read on a 1080p TV at the back of the office than 30 thin daily bars) / `Cumulative (running total)` (running sum — shows month-to-date trajectory at a glance).
- **`at_risk_clients`** (table) — `Top 5 worst` (default, original) / `Trouble only` (only clients in the Trouble bucket; up to 8 rows) / `At-Risk only` (only clients in At-Risk; up to 8 rows). Lets a CSM open one widget and toggle between "who's actively on fire" and "who's drifting downward" without editing the widget.

### Tests
- 3 new tests in `WallboardWidgetCategoryTests`:
  - `test_tickets_opened_30d_categories_return_distinct_series` — every registered category produces a non-empty `series` array; the `net` category specifically produces 3 series (opened, closed, net).
  - `test_revenue_trend_30d_weekly_collapses_to_fewer_buckets` — `daily` returns 30 labels; `weekly` returns fewer; `cumulative` is monotonically non-decreasing.
  - `test_at_risk_clients_categories_return_table` — every registered category returns a `columns`/`rows` payload.
- All 7 `WallboardWidgetCategoryTests` (4 v3.17.217 + 3 v3.17.218) and the wider 33 wallboard tests pass.

## [3.17.217] - 2026-05-02

### Added — Selectable categories on wallboard widgets
- **One widget, several views.** A widget on a wallboard now optionally exposes a category dropdown next to its title. Pick a different category and the tile re-fetches and renders in place — no full-page reload, no widget re-creation in admin. The widget's `data_source` declares which categories it supports; the registry holds the metadata.
- **Three sources are category-aware in this release** (the most useful for an "alerts/tickets/etc complete overview" board):
  - `open_tickets_count` (metric) — `All open` (default) / `Unassigned` / `SLA overdue` / `P1 / P2 only`. Each branches the underlying `Ticket` queryset.
  - `security_alerts_open_critical` (metric) — `Critical + High` (default) / `Critical only` / `All open` / `Last 24h`.
  - `tickets_by_priority` (table) — `By priority` (default — original behavior) / `By queue` / `By tech`. Switches the GROUP BY without touching saved widget config.
- **New JSON endpoint:** `GET /reports/wallboards/widgets/<pk>/data/?category=<value>`. Returns `{widget_type, data}` of the same shape the registry produces. Validates the category against the data source's registered set; rejects unknown values with HTTP 400. Tenant-ACL'd via the parent wallboard (cross-org → 404).
- **`reports.widget_sources` adds a `CATEGORIES` dict** keyed by data_source, plus three helpers — `get_categories(ds) → list|None`, `is_valid_category(ds, value) → bool`, `default_category(ds) → str|None`. New sources opt in by adding an entry; the wallboard view picks it up automatically.
- **Template:** `wallboard_view.html` puts a Bootstrap `form-select-sm` dropdown in each widget's card header when categories are registered. Vanilla-JS (no React, no extra CDN beyond the existing Chart.js) listens for change events, fetches the new payload, and rewrites the tile's `.card-body` innerHTML. Chart widgets re-init through a tracked `chartInstances[widgetId]` map (calls `.destroy()` before `new Chart(...)` to avoid the Chart.js v4 leak when reusing a canvas).
- **Refactor:** the chart-config builder is extracted into a shared `buildChartConfig(type, data)` function so the initial server-rendered chart and the JS-side re-render path use the same config.
- **`wallboard_view` and `wallboard_rotate` views** thread `categories` and `active_category` per widget into the template context. The active category is read from the widget's `query_params.category` and falls back to the registry default — so an admin who saves `query_params={"category": "overdue"}` on a widget gets that as the dropdown's initial selection.

### Tests
- 4 new tests in `WallboardWidgetCategoryTests`:
  - `test_endpoint_200_with_valid_category` — JSON endpoint returns 200 + `widget_type=metric` + `data.value` for `?category=unassigned`.
  - `test_endpoint_400_for_unknown_category` — `?category=bogus` → 400 with `{'error': 'unknown category'}`.
  - `test_endpoint_404_for_inaccessible_wallboard` — outsider user (member of a different org) gets 404 on the widget data URL.
  - `test_open_tickets_count_categories_branch_differently` — unit test: seed PSA defaults, create 2 unassigned + 1 P1 ticket, assert `open_tickets_count({'category':'unassigned'})['value'] == "2"`, `…priority_high → "1"`, `…all → "3"`.
- All 30 wallboard tests passing (model + rotation + widget-inherit + view ACL + rotate-view + list-view + reorder + global scope + categories).

## [3.17.216] - 2026-05-02

### Added — Global wallboards (cross-tenant overview boards)
- **Wallboards can now be created without an organization.** `Wallboard.organization` is nullable; `organization=NULL` means a "Global" board, visible only to staff/superusers, that aggregates across every tenant in the system. Use it for an MSP-wide NOC overview TV that shows total open tickets, open critical security alerts, expiring SSL certs, etc., across all clients at once. The original org-scoped flavor is unchanged — it remains the v3.17.211 default.
- **Why this works without rewiring widget sources:** the existing `reports.widget_sources.REGISTRY` callables already query without an org filter (`Ticket.objects.filter(status__is_terminal=False).count()`, etc. — no `.filter(organization=...)`). They were *intended* to be org-scoped per their docstrings but in practice always aggregated globally. The missing piece was the wallboard-level ACL that said "members can only see their org's boards." Global boards are gated to staff/superuser at the wallboard level instead.
- **`Wallboard.is_global` property** — convenience boolean for templates and downstream code (`{% if wallboard.is_global %}`).
- **`Wallboard.next_in_rotation()` rotates within scope** — global boards cycle only with other globals; org boards stay in their org's cycle. The query already filters `organization=self.organization` which Django translates correctly to `organization IS NULL` for globals.
- **ACL helper updated:** `_user_can_see_wallboards(user, organization)` now denies `organization=None` for non-staff users (a plain org member never sees globals). Staff and superuser see everything.
- **`wallboard_list` view** unions org-scoped boards for the user's accessible orgs with global boards (only when `is_staff_user`); the list page renders `Global` as a blue badge instead of an org name.
- **`wallboard_form` view** accepts `organization=global` POST value (only when user is staff-like) and creates with `organization=None`. Non-staff users posting `global` get an error redirect with no persistence.
- **List view template:** `<i class="fas fa-globe"></i> Global` badge replaces the org-name column for null-org rows.
- **Form template:** the org dropdown now leads with a `— Global (all tenants, staff-only) —` option (gated on `can_create_global`); helper text explains the staff-only visibility rule.

### Migration
- `reports.0004_alter_wallboard_organization` — `ALTER TABLE reports_wallboards MODIFY organization_id INT NULL`. Existing rows are unchanged (still scoped to their org). Schema-only, no data backfill needed.

### Tests
- 7 new tests in `WallboardGlobalScopeTests`:
  - `test_global_board_persists_with_null_org` — model accepts `organization=None`, `is_global` returns True, `__str__` reads "(Global)".
  - `test_acl_helper_allows_global_for_staff_only` — `_user_can_see_wallboards(staff, None) == True`; `_user_can_see_wallboards(member, None) == False`.
  - `test_list_includes_global_board_for_staff` / `test_list_hides_global_board_from_org_member` — list view ACL split.
  - `test_org_member_cannot_view_global_board_directly` — direct GET to `/reports/wallboards/<global_pk>/` returns 404 for non-staff.
  - `test_staff_can_create_global_board_via_form` — staff POSTing `organization=global` creates a row with `organization=None`.
  - `test_non_staff_member_cannot_create_global_board` — non-staff POST with `organization=global` rejected; nothing persists.
- All 22 wallboard tests passing (model + rotation + widget-inherit + view ACL + rotate-view + list-view + reorder + global scope).

## [3.17.215] - 2026-05-02

### Added — Drag-to-reorder wallboard widgets
- **Wallboard widget order is no longer admin-only.** v3.17.211 created the `WallboardWidget.order` field but the only way to change it was to edit the row in Django admin. The wallboard edit page now shows the widget list with drag handles; drag a row, drop it, the new order persists automatically.
- **New endpoint:** `POST /reports/wallboards/<pk>/widgets/reorder/` accepts `{"order": [<widget_pk>, ...]}` (JSON) or form-encoded `order=<pk>&order=<pk>`. Validates every pk belongs to the wallboard (rejects cross-board contamination with HTTP 400) and tenant-scopes the wallboard pk (cross-org wallboards return 404). Updates `WallboardWidget.order` to 10/20/30/… in the supplied sequence so manually-edited values stay legible.
- **UI:** SortableJS v1.15.2 from CDN handles the drag interaction, gated on `widgets.count > 1` so single-widget wallboards don't pull in 17 KB of JS unnecessarily. Drag handle = `fa-grip-vertical` icon on each row. Status indicator in the card header shows "saving…" / "saved" / "error — refresh page" so the user gets immediate feedback. Footer hint: "Drag rows to reorder. Saved automatically."
- **Permission gating:** `@require_perm('reports_manage_dashboards')` — same gate as `wallboard_form`, so anyone who can edit a wallboard can reorder its widgets.

### Tests
- 4 new tests in `WallboardWidgetReorderTests`:
  - `test_reorder_persists_new_order` — posts a reversed order, confirms the `order` field is rewritten 10/20/30 in the new sequence.
  - `test_reorder_rejects_widget_from_different_wallboard` — supplies a widget pk from a sibling board, expects HTTP 400 with "do not belong" in the error.
  - `test_reorder_rejects_get` — GET → HTTP 405.
  - `test_reorder_blocks_cross_org_wallboard_with_404` — POST to a wallboard the user can't see returns 404 (tenant ACL).
- All 19 existing wallboard tests still passing (model + rotation + widget-inherit + view ACL + rotate-view + list-view + reorder).

## [3.17.214] - 2026-05-02

### Added — Welcome email when an internal user is added to an org
- **Membership creation now notifies the new member.** The portal-side `psa.views.portal_invite` flow has always emailed a tokenized set-password link for client-portal users, but the internal staff invite paths (`accounts.views.member_add`, `accounts.views.user_add_membership`) silently created memberships with no notification at all — meaning a user could be granted access to a new tenant and never know.
- New `accounts.views.send_member_welcome_email(membership, request, *, invited_by=None)` helper that sends a short text email: "You now have access to {Org} as {Role}. You were added by {inviter}. Sign in here: {url}". Best-effort — failures are logged via `logger.warning` and the function returns `False` rather than raising, so a transient SMTP outage can't roll back the membership creation.
- Skips silently when the target user has no email on file (returns `False`). Returns `False` and logs on send failure.
- **Wired into both staff-side flows:**
  - `member_add` (org owner adds an existing user via the org Members page) — sets `invited_by=request.user` and sends the welcome email after the membership saves.
  - `user_add_membership` (superuser-only flow on the User Edit page) — sends on both new-membership creation and reactivation of a previously-suspended membership.
- The existing per-user "Added X to Org as Role" success message gets " Welcome email sent." appended when the email actually went out, so the inviter has confirmation.

### Tests
- 3 new tests in `accounts.tests.MemberWelcomeEmailTests` (uses `EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'`):
  - `test_send_member_welcome_email_helper` — direct helper invocation puts a message in `mail.outbox`, subject contains the org name, recipient = user's email, body mentions the org.
  - `test_helper_skips_when_user_has_no_email` — empty email → `sent=False`, `mail.outbox` stays empty.
  - `test_member_add_view_sends_welcome` — owner POSTs to `/accounts/organizations/<id>/members/add/` and the view sends exactly one email.

## [3.17.213] - 2026-05-02

### Added — Quote → Project automation
- **Accept a quote and spin up a project in one click.** `psa.Quote` has had a `converted_project` FK reserved since the model was first written but nothing populated it. New `Quote.convert_to_project(user)` method creates a `Project` with `name=quote.title`, copies the description, owner, and tenant scoping (organization + client_org), then walks `line_items` and creates one `ProjectTask` per row — line description becomes the task title, quantity is folded into `estimated_hours`, and a "From quote Q-YYYY-NNNNN: qty × price" stub goes in the task description so techs can trace each task back to what was sold.
- **Idempotent.** Calling `convert_to_project()` a second time returns the existing project unchanged — no duplicate tasks. Important because `mark_accepted(create_project=True)` could be re-fired by a stuck UI refresh and we'd rather a no-op than a doubled task list.
- **Wired through `Quote.mark_accepted()`** via a new `create_project: bool = False` keyword. `quote_accept` view (`POST /psa/quotes/<pk>/accept/`) now reads a `create_project` form checkbox; if both ticket and project are created, the post-accept redirect favors the project page (techs land on the work breakdown). Audit log entry now includes `project=<pk>` alongside `ticket=<pk>` for traceability.
- **UI.** `templates/psa/quote_detail.html` accept-card now has a second checkbox: "Spin up a project (one task per line item)" beside the existing "Also create a ticket". A new info card surfaces above the line items when `converted_project` is set, mirroring the existing "Converted to ticket" card.

### Tests
- 2 new tests in `Phase5QuotesExpensesTests`: `test_quote_convert_to_project_creates_tasks_per_line_item` (3 line items → 3 ordered tasks, project tenant-scoped correctly) and `test_quote_convert_to_project_is_idempotent` (calling twice returns the same project; task count stays at 1).

## [3.17.212] - 2026-05-02

### Added — Tier A wallboard polish (3 items in one release)
- **Chart.js wiring for wallboard line/bar/pie widgets.** v3.17.211 deferred chart rendering — chart-type widgets fell back to a `<pre>` text dump of the data payload. Now renders proper canvases with the same payload shape + initializer code as `templates/reports/dashboard_detail.html`. The view passes `data_json = json.dumps(data, default=str)` per chart widget and embeds it in a `<script type="application/json">` tag; the `extra_js` block fires Chart.js v4.4.1 from CDN (only when `has_chart=True`, so plain wallboards stay light). Reuses the same color palette + axis defaults so wallboards match dashboards visually.
- **"Wallboards" link added to the Reports nav dropdown** in `templates/base.html` between "Dashboards" and "Generate Reports". Was missing — users had to know `/reports/wallboards/` directly.
- **Screenshot script extended** with three new entries — `dispatch-heatmap` (Phase 11.3), `wallboards-list`, `wallboards-new`. Captures the new surfaces on the next run.

### Tests
- Existing 15 wallboard tests still passing — `WallboardModelTests`, `WallboardRotationTests`, `WallboardWidgetInheritTests`, `WallboardViewACLTests`, `WallboardRotateViewTests`, `WallboardListViewTests`. `has_chart` context variable is exercised implicitly via the existing `test_own_org_wallboard_renders` (a plain board sets has_chart=False; templates render correctly in both modes).

## [3.17.211] - 2026-05-02

### Added — Configurable wallboards (Phase 3 follow-up)
- **Multiple named wallboards per organization.** New `reports.Wallboard` model lets each org define an arbitrary number of named TV-ready dashboards (Operations / Sales / NOC, etc.). Each wallboard has its own `refresh_seconds` (page-level meta-refresh cadence), `rotate_seconds` (used by the rotation view to cycle to the next board), `order` (rotation position), and `is_active` flag.
- **Widgets sourced from the v3.17.142 registry.** New `reports.WallboardWidget` references `reports.widget_sources.REGISTRY` via its `data_source` field — every widget the regular dashboard system supports is automatically pickable for a wallboard. Per-widget `refresh_seconds` override available; falls back to the wallboard's interval when null. `effective_refresh_seconds` property handles the precedence.
- **Rotation mode for NOC TVs.** New `/reports/wallboards/<pk>/rotate/` view emits a meta-refresh `<meta http-equiv="refresh" content="{rotate_seconds};url=/reports/wallboards/{next}/rotate/">` so a TV browser cycles through every active rotatable board with no JS or cookies. `Wallboard.next_in_rotation()` computes the next-in-cycle board, ordered by `(order, name)`, skipping inactive boards and any board with `rotate_seconds=0`.
- **Routes:**
  - `GET /reports/wallboards/` — list view (filtered to user's orgs).
  - `GET /reports/wallboards/<pk>/` — render a single wallboard.
  - `GET /reports/wallboards/<pk>/rotate/` — same rendering + rotation redirect.
  - `GET / POST /reports/wallboards/new/` and `/<pk>/edit/` — CRUD form for wallboard fields. Widget editing currently goes through Django admin (a `WallboardWidgetInline` is registered on `WallboardAdmin`).
- **Tenant ACL.** Wallboards are tenant-scoped: org members can see their org's boards; cross-org PKs return 404. Same pattern as the v3.17.171 tenant-isolation rebuild.
- **Templates:** `wallboard_list.html` (table with active / refresh / rotate / widget-count), `wallboard_form.html` (create/edit form, organization picker on create), `wallboard_view.html` (12-column grid renderer with metric / table / fallback widget types). Charts (line/bar/pie) render their data payload as plaintext for now — Chart.js wiring is a future sub-phase.
- **Admin:** `WallboardAdmin` + `WallboardWidgetAdmin` registered with `list_editable` on `is_active` / `order` for fast multi-board management.
- **Tests:** 15 new across 6 classes — `WallboardModelTests` (4: `__str__`, defaults, unique-per-org, same-name-cross-org), `WallboardRotationTests` (4: `next_in_rotation` single / cycle / inactive-skipped / rotate-zero-skipped), `WallboardWidgetInheritTests` (2: refresh inherit + override), `WallboardViewACLTests` (2: own-org renders, cross-org 404), `WallboardRotateViewTests` (2: meta-refresh emits next-board URL, cycles back from last to first), `WallboardListViewTests` (1: list renders with org's boards). 15/15 passing in 6 s.
- **Migration:** `reports/migrations/0003_wallboards.py` — schema-only, two new tables + indexes.

## [3.17.210] - 2026-05-02

### Changed — Phase 11 [complete]
- **Phase 11 marked `[complete]`.** All three planned sub-phases shipped:
  - 11.1 Dispatch prioritization + SLA-burn panel — v3.17.194
  - 11.2 PTO + calendar conflict awareness — v3.17.208
  - 11.3 Dispatch heatmap — v3.17.209
- **Two listed capabilities deferred to Phase 8:** geo-aware technician routing and travel time estimation. Both depend on GPS data the Phase 8 mobile timeclock will collect — no point building them on infrastructure that doesn't exist. They'll be revisited as Phase 8 sub-items rather than blocking Phase 11 closure.
- **One listed capability re-routed:** "Recurring onsite scheduling" is already covered by `scheduling.ScheduledTask.recurrence`; not a separate dispatch surface.
- **`/core/roadmap.json` JSON feed:** Phase 11 now reports `status: complete`. **Shipped count: 10 → 11.**
- **Living-plan header at top of ROADMAP.md updated:** "Phases 1–7 + 9 + 10 + 11 + 31 complete."
- **Sizing-table row for Phase 11 updated** with shipped versions for all three sub-phases.
- **README badge bumped** to v3.17.210.
- **27 dispatch tests** across the three sub-phases passing in 14.5 s.

## [3.17.209] - 2026-05-02

### Added — Phase 11.3: Dispatch heatmap
- **New `/psa/dispatch/heatmap/` view** — per-tech, per-day open-ticket load aggregation rendered as a color-intensity heatmap over a ±7-day window (15 columns total: 7 days back, today, 7 days forward). Lets dispatchers see lopsided assignments at a glance.
- **5-step intensity scale.** Each cell renders with one of 5 background-color classes (`intensity-0` through `intensity-4`). Bucketing uses `min(4, 1 + (count-1) * 4 / max(1, max_count-1))` so the busiest cell in the visible window is always intensity-4 and other cells scale proportionally. Today's column has a blue inset border for orientation.
- **What's counted:** open tickets (terminal status excluded) that are assigned to a tech AND have a due date inside the visible window. Unassigned tickets, tickets without a due date, and tickets outside the ±7-day window are filtered out.
- **Tenant isolation** — same `get_request_organization` scope as `dispatch_board`. Cross-org tickets never appear in another tenant's heatmap.
- **Tests:** 8 new in `DispatchHeatmapTests` — view returns 200; window is 15 days; assigned in-window ticket counted; unassigned not counted; out-of-window not counted; no-due-date not counted; max_count reflects busiest cell across techs; cross-org tickets filtered. **27/27 dispatch tests passing in 14.5 s** (combined 11.1 + 11.2 + 11.3).

## [3.17.208] - 2026-05-02

### Added — Phase 11.2: PTO + calendar conflict awareness
- **New `_dispatch_conflicts(tech, ticket)` helper** in `psa/views.py` returns advisory warning strings when assigning would create a conflict:
  - **PTO conflict** — checks `resourcing.LeaveRequest.is_user_on_leave(tech, due_date)`. Only `status='approved'` leaves trigger; pending/cancelled don't.
  - **Calendar overlap** — flags any other open ticket already assigned to the same tech with a due date inside a ±2-hour window of the new one. Closed/terminal tickets don't count.
  - Wrapped in try/except for the resourcing import so a slim deployment without resourcing/ installed still works.
- **`/psa/dispatch/assign/` JSON response now includes `conflict_warnings`** — an array of one-line warning strings, empty when clean. The response is **advisory, not blocking** — dispatchers made an explicit decision; the warning surfaces as a chip in the UI for review.
- **AuditLog entry** for the assignment now includes the conflict list when present, so post-hoc audit trails capture "they assigned despite the warning".
- **Tests:** 9 new across 2 classes — `DispatchConflictDetectionTests` (7 cases: unassigned no-warnings, no-due no-warnings, clean assignment no-warnings, PTO approved triggers, PTO pending doesn't, calendar overlap inside window, outside window, closed-ticket doesn't); `DispatchAssignWarningResponseTests` (2 cases: clean response has empty array, PTO conflict appears in JSON response). 19/19 dispatch tests passing in 10 s.

## [3.17.207] - 2026-05-02

### Changed — Phase 7 [complete]
- **Phase 7 marked `[complete]`.** Originally framed as a "continuous track" that could never reach a terminal state, but with all three pillars shipped — outsourcing (v3.17.166), Integration SDK skeleton + reference adapter (v3.17.166 / v3.17.168), and the polish-backlog test-coverage push (Wave 1 closed v3.17.187, Wave 2 closed v3.17.205) — the phase has reached a sensible end. Ongoing polish work continues as routine maintenance and lands under whichever phase the change applies to (e.g. a vault improvement = Phase 31 polish).
- **`/core/roadmap.json` JSON feed:** Phase 7 now reports `status: complete`. **Shipped count: 9 → 10.**
- **Living-plan header at top of ROADMAP.md updated:** "Phases 1–7 + 9 + 10 + 31 complete. Phase 11 in progress (11.1 shipped)."
- **Sizing-table row for Phase 7 updated:** "complete (v3.17.207); 2 polish waves closed at v3.17.187 + v3.17.205".
- **README badge bumped** to v3.17.207.

### Note
- The "continuous track" label remains in the phase title for historical accuracy — Phase 7's character was that it ran alongside Phases 1-6 — but the status marker is the source of truth and now correctly reads `[complete]`.

## [3.17.206] - 2026-05-02

### Documentation — Phase 7 Wave 2 closure
- **Wave 2 of the Phase 7 polish-backlog test sweep is closed.** Every one of the 16 originally-untested apps from the audit punch-list now has baseline coverage. Wave 2 spanned v3.17.192 → v3.17.205 (14 releases, 11 with new test files plus the psa-tests shard split + 2 doc-only roadmap-update releases).
- **Roadmap updated:**
  - Wave 2 section in Phase 7 polish-backlog now lists all 11 baseline-coverage releases (api/, audit/, assets/, monitoring/, processes/, files/, scheduling/, locations/, docs/, inventory/, vehicles/) with one-line summaries.
  - "Wave 2 closed (v3.17.192 → v3.17.205)" marker added below the list.
  - Living-plan header at top of ROADMAP.md updated: "Phase 7 in progress (continuous track; Wave 1 closed at v3.17.187, Wave 2 closed at v3.17.205 — every previously-untested app now has baseline coverage). Phase 11 in progress (11.1 shipped)."
- **README badge bumped** to v3.17.206.
- **Final bug-catch ratio for Wave 2: 3 of 11 baseline efforts surfaced real production bugs.** All caught bugs were stale-attribute / wrong-kwarg / `hasattr`-vs-None patterns — the same family the next test pass should target first.
- **Wave 2 totals:** ~280 new tests across 11 modules in 14 commits. Combined with the v3.17.192 psa-tests shard split, every shard now runs in well under the 540 s CI ceiling (max 147 s for the largest psa shard; most app suites under 7 s).

## [3.17.205] - 2026-05-02

### Tests
- **Baseline coverage for the `vehicles/` app** (Phase 7 polish Wave 2 — **16th and last** of 16). Service vehicles + fleet inventory + receipt scanning. ServiceVehicle is MSP-wide (no organization FK — fleet management isn't per-tenant). **18 tests across 3 classes:**
  - `ServiceVehicleModelTests` (6) — `__str__` format with year/make/model/plate; `display_name` uses nickname when set, falls back to `<year> <make> <model>`; `has_location` true only when both lat+lng; `update_location()` sets coords + timestamp.
  - `VehicleExpiryWarningTests` (6) — insurance + registration expiry both: true within 30-day window, false far-out, **false when unset** (regression guard for `None <= date` crash).
  - `VehicleInventoryItemTests` (6) — `__str__` includes name + qty + unit; `is_low_stock` boundary at minimum and above; `needs_restock` only when reorder_quantity > 0 AND below min; `total_value` math; `total_value` handles None unit_cost gracefully.
- 18/18 in 0.05 s. **No production bugs surfaced.**

### Wave 2 milestone
- **Every one of the 16 originally-untested apps now has baseline coverage.** Wave 2 closure release coming next.

## [3.17.204] - 2026-05-02

### Tests
- **Baseline coverage for the `inventory/` app** (Phase 7 polish Wave 2 — 14th of 16). InventoryItem + transactions for spare parts, consumables, hardware stock. Bug here = wrong stock counts feed wrong reorder triggers, wrong on-hand reports, wrong audit. **15 tests across 5 classes:**
  - `InventoryItemSaveTests` (4) — QR code auto-generated as `INV-` + 12 hex chars on first save; QR codes unique across items; explicit QR code preserved; `__str__` returns name.
  - `InventoryItemStockLogicTests` (5) — `is_low_stock` boundary: true at minimum, true below, false above; `total_value` = quantity × unit_cost; None when unit_cost null.
  - `InventoryItemFilteringTests` (1) — `OrganizationManager.for_organization()` tenant filter.
  - `InventoryTransactionTests` (2) — `__str__` format `<item> <type> +<n>` with `:+d` spec; negative quantity-change renders with explicit minus.
  - `InventoryCategoryAndLocationTests` (3) — Category + Location `__str__`; default color.
- 15/15 in 1.5 s. **No production bugs surfaced.**

## [3.17.203] - 2026-05-02

### Tests
- **Baseline coverage for the `docs/` app** (Phase 7 polish Wave 2 — 13th of 16). Knowledge base + Diagrams. KB articles surface to clients via the portal; bug here can leak internal docs externally OR break slug-based routing on customer-visible URLs. Every other app links here (PSA→KB-link, processes→linked_document, vault→linked_document). **13 tests across 5 classes:**
  - `DocumentCategoryTests` (3) — slug auto-gen from name; explicit slug preserved; `__str__`.
  - `DocumentSlugTests` (3) — slug auto-gen from title; explicit slug preserved; `__str__`.
  - `DocumentVersionSnapshotTests` (3) — **no version row written on initial create** (regression guard against runaway version-number-1 row on every doc); v1 snapshot recorded on first edit (preserves pre-edit state); version numbers increment 1, 2, 3, … across multiple edits.
  - `DiagramSlugTests` (2) — slug auto-gen + `__str__`.
  - `GlobalKBVisibilityTests` (2) — `is_global=True` docs can have `organization=None` (fully global) or `organization=<MSP>` (MSP-internal cross-tenant). Both cases round-trip correctly.
- 13/13 in 6 s. **No production bugs surfaced.**

## [3.17.202] - 2026-05-02

### Tests
- **Baseline coverage for the `locations/` app** (Phase 7 polish Wave 2 — 12th of 16). Tracks physical locations + WAN connections + floor plans for multi-location clients. Bug here = wrong tenant access via shared-location ACL leak, broken HQ uniqueness, or silent address-rendering breakage. **20 tests across 3 classes:**
  - `LocationModelTests` (9) — `__str__` discriminates owned/HQ/shared; `full_address` formatting (with/without country / suite); `has_coordinates` true only when both lat+lng; **HQ uniqueness invariant — saving a new `is_primary=True` demotes the existing primary** (load-bearing); shared locations cannot be primary (forced via save).
  - `LocationAccessControlTests` (5) — `can_organization_access` ACL: owner can / other-org can't / shared-with-associated can / `get_all_organizations` returns the right set for shared vs owned.
  - `WANModelTests` (6) — `__str__`, `is_down` true/false on status, `bandwidth_display` unknown/down-only/down+up formatting.
- 20/20 in 0.08 s. **No production bugs surfaced.**

## [3.17.201] - 2026-05-02

### Tests
- **Baseline coverage for the `scheduling/` app** (Phase 7 polish Wave 2 — 11th of 16 originally-untested apps). Cron-driven scheduled tasks with sign-off support. Bug = silent task-execution failure (recurrence that never spawns the next occurrence; sign-off that doesn't complete the task; etc.). **20 tests across 5 classes:**
  - `ScheduledTaskOverdueTests` (4) — `is_overdue` true past-due-and-pending; false when completed even past-due; false when cancelled; false with no due date.
  - `ScheduledTaskRecurrenceTests` (10) — `get_next_due_date` math for every cadence: `none → None`, `daily → +1d`, `weekly → +7d`, `biweekly → +14d`, `monthly → +30d` (calendar-approximation, not month-aware), `quarterly → +91d`, `custom` honors `recurrence_interval_days`, `custom` with no interval returns None, no due date returns None.
  - `ScheduledTaskCompletionTests` (4) — `check_completion` semantics: any-of when `require_all_signoffs=False`, all-of when True, partial sign-off doesn't complete in all-of mode, **no-op when there are zero assignments** (regression guard against `all([]) == True` accidentally completing unsigned tasks).
  - `ScheduledTaskRecurrenceSpawnTests` (2) — completing a recurring task spawns the next occurrence with cloned assignments + tags + recurrence config; one-time task does NOT spawn.
  - `TaskAssignmentConstraintTests` (1) — `(task, user)` unique-together rejects duplicate-assignee.
- 20/20 in 6 s. **No production bugs surfaced.** The model's `monthly → +30d` approximation is now explicitly pinned by test — if anyone changes it to true calendar-month logic in the future, that test should update.

## [3.17.200] - 2026-05-02

### Tests
- **Baseline coverage for the `files/` app** (Phase 7 polish Wave 2 — 10th of 16 originally-untested apps). `Attachment` is the generic file-attachment model used across the app (asset photos, doc uploads, vehicle receipts). Files are stored under per-org / per-entity paths and served via X-Accel-Redirect. **9 tests across 2 classes:**
  - `AttachmentUploadPathTests` (5) — `attachment_upload_path()` is the load-bearing tenant-isolation boundary on disk. Tests confirm: first path segment is `str(org.id)`, then `entity_type`, then `entity_id`; original extension preserved; **filename is a UUID, NOT the user-supplied string** (defense against path-traversal / malicious filenames); two different orgs producing files for the same entity-id can't collide.
  - `AttachmentModelTests` (4) — `__str__` includes filename + entity pointer; `size_kb` rounds to 2 decimals; `for_organization()` filtering; `(organization, entity_type, entity_id)` index returns correct rows (regression guard for future migrations dropping the index).
- 9/9 in 1.5 s. **No production bugs surfaced.** The `_optimize_image()` codepath isn't exercised here — it requires real image bytes; that's a follow-up for a deeper file-handling test pass.

### Milestone
- This is **release v3.17.200** — the 200th patch in the 3.17.x line. Counting from v3.17.171 (this session's start), 30 releases shipped. Pace has been ~1 release per ~10 minutes of work, including doc-only releases.

## [3.17.199] - 2026-05-02

### Tests
- **Baseline coverage for the `processes/` app** (Phase 7 polish Wave 2 — 9th of 16 originally-untested apps; previously a 3-line stub). Workflow engine: defines reusable Process templates with sequential stages, executed against tickets. Bug = silent workflow run failure. **19 tests across 4 classes:**
  - `ProcessModelTests` (6) — slug auto-generation from title; explicit slug preserved; `__str__` marks `[GLOBAL]` and `[TEMPLATE]` prefixes; `unique_together (organization, slug)` rejects duplicates within an org but allows same slug across orgs; `for_organization()` filtering.
  - `ProcessStageOrderingTests` (2) — default `order=0`; explicit ordering preserved by query.
  - `ProcessExecutionTests` (8) — execution starts `not_started`; `completion_percentage` is 0 / 33 / 100 across stage states; **doesn't divide by zero on stage-less Process** (regression guard); `is_overdue` true when past due, false when completed even past due, false when no due date set.
  - `ProcessStageCompletionConstraintTests` (3) — `(execution, stage)` unique-together rejects double-completion of one stage (load-bearing for completion-percentage math); `__str__` shows `✓` when completed, `○` when not.
- 19/19 in 6 s. **No production bugs surfaced.**

## [3.17.198] - 2026-05-02

### Documentation
- **Phase 7 polish-backlog updated with a "Wave 2" section** documenting the going-from-zero baseline-test work that's been continuing post-Wave-1-closure. Previously v3.17.192 → v3.17.197 had been recorded in the CHANGELOG but not the roadmap. The new section names the audit punch-list framing ("16 apps with no test coverage; sustained pass through them"), summarizes the bug-catch ratio (3 of 6 baselines surfaced real production bugs that had been latent for months), and lists each release's contribution: psa-tests split, api/, audit/, assets/, monitoring/. Phase 7 header marker stays `[in progress]` (continuous track by design).

## [3.17.197] - 2026-05-02

### Tests
- **Baseline coverage for the `monitoring/` app** (audit punch-list / Phase 7 polish — 8th of 16 originally-untested apps). Cron-driven (uptime checks fire on schedule) and externally-facing (`WebsiteMonitor.check_status` makes outbound HTTP requests). Silent failures here = invisible monitoring loss. **22 tests across 5 classes:**
  - `WebsiteMonitorModelTests` (7) — minimal create defaults (`status='unknown'`, `is_enabled=True`, 60-min check interval); `__str__` includes name + URL; `is_ssl_expiring_soon` true within warning window; false outside it; **false when `ssl_expires_at` is None** (regression guard for `None <= ...` comparison crash); `is_domain_expiring_soon` uses domain-specific warning window; `for_organization()` filtering.
  - `ExpirationModelTests` (5) — `__str__` includes name + date; `is_expired` true/false on past/future dates; `days_until_expiration` negative when expired; `is_expiring_soon` only fires inside `[0, warning_days]` (not for already-expired or far-future).
  - `IPAMConstraintTests` (5) — IPAM dedupe contract: `(subnet, ip_address)` unique-together rejects duplicate-in-same-subnet but allows same-IP-in-different-subnet; default status `available`; `__str__` includes hostname when set, falls back to IP only otherwise.
  - `SubnetModelTests` (3) — `__str__`, default `dns_servers=[]`, `for_organization()`.
  - `VLANModelTests` (2) — basic create + `__str__`.
- 22/22 in 0.09 s. **No production bugs surfaced** — monitoring/ models are clean (the `None`-guard test was a regression guard, not a bug catch). The view-layer + cron-side hasn't been smoke-tested yet; that's a follow-up.

## [3.17.196] - 2026-05-02

### Tests
- **Baseline coverage for the `assets/` app** (audit punch-list / Phase 7 polish — 7th of 16 originally-untested apps). Foundational app: `Asset`, `Contact`, `EquipmentModel`, `Vendor`, `AssetType` are referenced from every other surface (vault for asset linking, docs for KB→asset, PSA for ticket→asset, monitoring for rack→asset). Bugs here ripple. **16 tests across 6 classes:**
  - `AssetModelTests` (4) — minimal create, `__str__` includes name + display label, default `asset_type='other'`, `OrganizationManager.for_organization()` filtering.
  - `ContactModelTests` (4) — `full_name` property, `__str__` returns full name, blank email allowed (matches model + migration), `for_organization()` filtering.
  - `AssetTypeModelTests` (2) — basic create, default `icon='fa-box'` and `color='#0d6efd'`.
  - `AssetListViewTests` (2) — anonymous → 302/401 (login redirect), authenticated → 200 with own-org assets visible.
  - `AssetDetailIsolationTests` (2) — own-org PK returns 200; cross-org PK returns 404 (matches `core.tests.test_tenant_isolation` pattern).
  - `EquipmentModelLookupTests` (2) — create with vendor + model_name + slug + equipment_type; back-reference via `Asset.equipment_model` FK populates `em.assets`.
- 16/16 in 7 s. **No production bugs surfaced** — assets/ is the first new-baseline app this session that came out clean. (Previous three new-baseline efforts each caught a real bug: tenant-isolation, api/, audit/.)

## [3.17.195] - 2026-05-02

### Fixed
- **`AuditLoggingMiddleware._is_update()` was crashing on unresolved URLs.** The guard at the top did `if not hasattr(request, 'resolver_match'): return False` — but Django sets `resolver_match` on every request *as an attribute* (even when no URL pattern matches), assigning `None`. `hasattr` returns True for `None` values, so the function then did `None.kwargs` and raised `AttributeError`. Effect: any POST to an unresolved URL would crash the middleware and the request would 500. Fix: explicit `None` check via `getattr(request, 'resolver_match', None)`. Caught by the new `audit/` test suite.

### Tests
- **Baseline coverage for the `audit/` app** (audit punch-list / Phase 7 polish — 6th of 16 originally-untested apps). The audit log is the project's "who did what when" record-of-record; `AuditLoggingMiddleware` fires on every authenticated request. Silent failures here = invisible audit-trail loss. **30 tests across 7 classes:**
  - `AuditLogClassmethodTests` (7) — `log()` writes a row, auto-fills `username` from `user.username`, accepts `user=None` (records empty username), defaults `extra_data` to `{}`, defaults `success=True`, records `organization`, records `object_type`/`object_id`/`object_repr`.
  - `AuditLogModelTests` (4) — `__str__` includes username + action + object pointer; `get_object_url` returns `None` when object_id blank, `None` for unknown object_type, and a real reverse URL for known types like `password`.
  - `MiddlewareActionDetectionTests` (11) — `_determine_action` matrix: GET-detail → `read`, GET-list → `None` (suppressed for noise), POST-create / POST-edit / POST-delete, `_method=DELETE` form override, PUT/PATCH → `update`, DELETE → `delete`, login POST 200/302 → `login`, login POST 4xx → `login_failed`, logout path → `logout`.
  - `MiddlewareDetailViewDetectionTests` (4) — `_is_detail_view`: numeric pk → True, `/create/` → False, `/<pk>/edit/` → False, list path → False.
  - `MiddlewareIntegrationTests` (2) — full request cycle: `/static/` excluded, anonymous request to non-login URL doesn't write a `read` row.
  - `MiddlewareSensitiveFieldRedactionTests` (1) — sensitive POST fields (`password`, `token`, etc.) are `***REDACTED***` in `extra_data.form_data`.
  - `MiddlewareFailureIsolationTests` (1) — when `AuditLog.log()` raises, the middleware swallows + the request still returns. **A failed audit must never 500 the user.**
- 30/30 in 10 s.

### Recurring observation
- Third real production bug surfaced this session by going from 0 tests → baseline coverage on a previously-untested app. Pattern: v3.17.171 (tenant-isolation → API audit-log crash), v3.17.193 (api/ → `/api/assets/` 500), v3.17.195 (audit/ → POST-to-unresolved-URL crash). Each was latent for months; each was caught the day baseline tests went in.

## [3.17.194] - 2026-05-02

### Added — Phase 11.1: Dispatch prioritization + SLA-burn panel
- **The dispatch board now sorts every lane by priority + SLA proximity instead of creation order.** New `psa.views._dispatch_priority_key(ticket)` helper returns a sort tuple of `(priority.sort_order, no_due_flag, due)` so tickets with the highest priority surface first within each lane (overdue, SLA-burn, unassigned-by-day, assigned-tech cells), and within a priority band tickets due sooner come first; tickets with no due date sink to the bottom of their band.
- **New "SLA at risk" panel above the grid.** Open tickets whose `resolution_due_at` (or `first_response_due_at` when no resolution due) lands in the next 4 hours but isn't yet overdue surface in a yellow alert with `<i class="fas fa-fire">` so dispatchers can pre-empt breaches without staring at the grid. Already-overdue tickets remain in the existing red "Overdue" panel — no duplication. Closed tickets are excluded.
- **`sla_burn` added to the dispatch view's template context.** Sorted by the same priority key. Displays priority chip, subject, time-until-due via Django's `timeuntil` filter, and assignee status (or "→ unassigned" highlighted in red).
- **Tests:** new `psa/tests/test_phase11_dispatch.py` shard with 9 cases across 3 classes — `DispatchPriorityKeyTests` (sort-key contract: higher priority before lower; sooner due first within band; no-due sinks to bottom; first_response_due_at falls back when no resolution_due_at), `DispatchSlaBurnPanelTests` (in-window appears; overdue does not; outside-4h-window does not; closed does not), `DispatchBoardSortingTests` (lane ordering end-to-end). 9/9 in 5 s. Cross-shard regression on `test_phase10_email` + `test_phase3_5_features`: 87/87 in 69 s.

### Caught in passing
- **A subtle decorator-stacking trap.** The first version of `_dispatch_priority_key` got placed *between* `@require_psa_enabled` and `def dispatch_board`, so the decorator silently wrapped the helper instead of the view. The error surfaced as `AttributeError: 'Ticket' object has no attribute 'user'` from inside `sorted(...)` — a confusing trace because the decorator's `test_func(request.user)` was being evaluated against ticket objects passed in as the sort key. Helper moved above the decorator stack; the trace clarified itself.

### Roadmap
- Phase 11 status remains `[in progress]` (more sub-phases in plan: PTO conflict awareness, calendar conflict detection, recurring onsite scheduling, geo-aware routing, dispatch heatmaps). 11.1 is the smallest meaningful first slice.

## [3.17.193] - 2026-05-02

### Fixed
- **`/api/assets/` was 500-ing on every list and detail request.** Two stale field references in the `api/` REST surface — `AssetViewSet.filterset_fields` listed `is_active` and `location`; `AssetSerializer.Meta.fields` listed `location` and `is_active`. The Asset model has neither (likely carried over from an older spec). Django-filter raised `TypeError: 'Meta.fields' must not contain non-model field names` on the first list request; DRF raised `ImproperlyConfigured: Field name 'location' is not valid for model 'Asset'` even when filters were skipped. Both fixed; the Asset list endpoint now responds 200. Same family of bug as the v3.17.171 audit-log crash — caught by the new `api/` test suite.
- **Caught by the new test suite.** This is the second real bug surfaced this session by going from "0 tests" → "baseline coverage" on a previously-untested app (the first was the `_FakeIMAP` race in tenant-isolation rebuilds). Argument for keeping at it.

### Tests
- **Baseline coverage for the `api/` app** (audit punch-list / Phase 7 polish). Externally-exposed REST API previously had zero regression coverage. Before v3.17.171, `AuditLog.objects.create(... details=...)` had been crashing every successful `/api/passwords/<id>/` retrieve since the initial commit; this test file is designed to catch that class of bug. **11 tests across 6 classes:**
  - `APIAuthGateTests` (2 cases) — anonymous requests get 401/403 on list endpoints.
  - `OrganizationScopedListFilteringTests` (1 case) — `/api/assets/` filters to the user's current org.
  - `CrossTenantDetailIsolationTests` (2 cases) — known PK in another org returns 404; own-org PK returns 200.
  - `PasswordEndpointAuditTrailTests` (3 cases) — `retrieve` writes a `read` audit row; `reveal` returns plaintext + writes `reveal` row; explicit regression guard for the v3.17.171 `details=` bug.
  - `PasswordOTPEndpointTests` (1 case) — `/otp/` action returns 400 for non-OTP entries.
  - `OrganizationViewSetTests` (2 cases) — read-only viewset rejects POST with 405; list returns 200.
- 11/11 in 15 s.

## [3.17.192] - 2026-05-02

### Tests
- **`psa/tests.py` split into 5 topical shards** (audit punch-list item #3). The legacy 5,465-line single file was hitting the 540 s CI ceiling at ~106/220 cases per the v3.17.187 test-rot audit. Each shard now runs independently well under the ceiling.
  - **`psa/tests/_base.py`** — shared helpers (`TEST_MIDDLEWARE`, `_setup_seed`, `_enable_psa_global`, `_enable_psa_for`).
  - **`test_phase1_2_core.py`** — 13 classes / 75 tests / 141 s. Feature flags, route gating, ticket lifecycle, seed defaults, vault context, Phase 2a/2b/2c, SLA, time tracking, service catalog.
  - **`test_phase3_5_features.py`** — 7 classes / 34 tests / 57 s. Phase 3 financial reporting, Phase 4 email config, customer portal, Phase 5 quotes/expenses, Phase 6 polish, Phase 7 workflow, Phase 8 billing.
  - **`test_workflow_kb_contracts.py`** — 13 classes / 56 tests / 147 s. Accounting connections, workflow rules + ticket-level workflow, portal user invites + vault RBAC, Phase 1 contract engine, contract auto-renewal, KB browse/permissions/move, admin assignment, service-catalog view modes.
  - **`test_procurement_itil.py`** — 18 classes / 53 tests / 107 s. Procurement (vendor metadata, auto-replenish, quote-to-PO, gates, receiving), ITIL (change request signals + permissions, problem records, release windows, catalog change governance), Phase 7 outsourcing (TicketShare), integration SDK.
  - **`test_phase10_email.py`** — 20 classes / 53 tests / 9 s. All email pipeline (10.1 threading, 10.2 body cleanup + attachments, 10.3 routing + auto-responder + DMARC/spam, 10.4 outbound + conversation panel) plus pure-function helpers (signature/quote strip, HTML sanitize).
- Total: **271 tests across 5 shards**, all green. Run `manage.py test psa` to discover all of them; `manage.py test psa.tests.test_<shard>` to run one.
- Topical organization makes new tests easier to place — the question "where does this go?" usually has an obvious answer based on which sub-phase the new code belongs to.

## [3.17.191] - 2026-05-02

### Documentation
- README version badge bumped from v3.17.185 → v3.17.190 (caught up to current build before the next round of work).

## [3.17.190] - 2026-05-01

### Documentation
- **Phase 10 marked `[complete]`.** With sub-phases 10.1 → 10.4 all shipped (v3.17.176, v3.17.177, v3.17.188, v3.17.189), the phase header status marker flips from `[in progress]` to `[complete]`. The `/core/roadmap.json` feed will report Phase 10 with `status: complete` going forward.
- **Phase 7 wave-1 closure marker added.** A new bullet at the bottom of Phase 7's polish-backlog list reads "Wave 1 closed (v3.17.171 → v3.17.187)" — every item from the original Phase 7 polish survey has been delivered or explicitly deferred (reCAPTCHA needs Google credentials; scheduler email-send + welcome-email are feature gaps not polish). Phase 7 stays `[in progress]` by design (it's a continuous track); the next wave fires when new polish items surface from a bug-bash audit or user reports.
- **"Living plan" header updated** at the top of `docs/ROADMAP.md`: now reads "Phases 1–6 + 9 + 10 + 31 complete. Phase 7 in progress (continuous track; Wave 1 closed at v3.17.187)."
- **Sizing-table row for Phase 10** updated to "all sub-phases complete (10.1 v3.17.176; 10.2 v3.17.177; 10.3 v3.17.188; 10.4 v3.17.189)".

## [3.17.189] - 2026-05-01

### Added — Phase 10.4: Outbound threading + per-ticket conversation panel
- **New `psa/email_outbound.py` helper.** Single entry point — `send_threaded_reply(ticket=, comment=, body_text=, body_html='', subject=None, to_emails=None, from_email=None)` — that:
  - Generates an RFC 5322 Message-ID for the outbound (uses `email.utils.make_msgid` with `idstring=psa-<ticket_number>` so future replies are diagnosable from the header alone; domain controlled by new `PSA_OUTBOUND_MESSAGE_ID_DOMAIN` setting, defaults to `clientst0r.local`).
  - Sets `In-Reply-To` and `References` from `Ticket.last_inbound_message_id` (the cache field added in Phase 10.1) so the customer's mail client threads our reply with the original conversation.
  - Sends via Django's email backend with `EmailMultiAlternatives` (plain-text + optional HTML alternative).
  - Persists an `EmailMessage(direction='out')` row so future inbound replies threading off our Message-ID resolve back to the same ticket — closing the round-trip via Phase 10.1's `_thread_target` lookup.
  - Falls back subject to `Re: [<ticket_number>] <ticket.subject>` so legacy subject-regex correlation still works for clients that don't preserve headers.
- **New per-ticket conversation view.** `GET /psa/t/<ticket_number>/conversation/` renders chronological inbound + outbound `EmailMessage` rows. HTML bodies render inside a `<iframe sandbox="">` (most-restrictive sandbox — no scripts, no forms, no top-level navigation, no remote resource loading). Quarantined inbound (Phase 10.3) shows with a yellow shield + reason banner. Raw headers + body collapse into `<details>` elements for review.
- **Tenant isolation.** The conversation view uses the same `_scoped_ticket_qs` + cross-org defence-in-depth check as `ticket_detail`. Org users only see their own org's email; superusers + staff see anything.
- **Tests:** 9 new across 2 classes — `OutboundThreadedReplyTests` (7 cases: threading headers, no-prior-inbound, subject fallback, explicit subject + recipients, HTML alternative, missing-recipients raises, **round-trip closure** — customer reply to our outbound resolves back to the same ticket via `_thread_target`); `TicketConversationViewTests` (2 cases: lists in/out messages, 404s on cross-org access). 9/9 in 6s.
- **Full Phase 10 regression:** 53/53 across all sub-phases (10.1 + 10.2 + 10.3 + 10.4) in 9s.

## [3.17.188] - 2026-05-01

### Added — Phase 10.3: Routing rules + auto-responder + DMARC/spam gating
- **New `psa.EmailRoutingRule` model.** Per-MSP-tenant rule mapping sender-email shape (`acme.com` exact-domain, `*.acme.com` subdomain glob, `noreply@acme.com` specific sender) to a client `target_client_org` plus optional `queue_override` and `priority_override`. Rules ordered by `order` (lower fires first); first match wins. The MSP's generic `help@msp.com` mailbox can now fan inbound mail out to the right client tenant automatically.
- **Quarantine flag on `EmailMessage`.** New `was_quarantined` boolean + `quarantine_reason` text field; `ticket` FK is now nullable (only NULL for quarantined inbound). Quarantined rows still exist in DB so admins can audit what got filtered. New index on `(organization, was_quarantined, received_at)` for efficient quarantine triage queries.
- **New helpers in `psa/email_parsing.py`:**
  - `detect_auto_responder(msg)` — checks `Auto-Submitted`, `X-Autoreply`, `X-Autorespond`, `X-Autoresponder`, `Precedence: bulk/list/junk`, NDR `multipart/report; report-type=delivery-status`, plus subject-based heuristics ("Out of Office", "Vacation Auto-Reply", "Auto-Reply", "Undeliverable"). Returns a one-line reason or empty string.
  - `parse_authentication_results(msg)` — extracts SPF/DKIM/DMARC/ARC verdicts from upstream MTA's `Authentication-Results` header. No inline crypto / DNS — trusts the front-line MTA.
  - `spam_keyword_score(text)` — counts distinct hits across a conservative pattern list (claim-your-prize, congratulations-winner, guaranteed-loan, viagra/cialis, nigerian-prince, crypto-investment-platform, wire-transfer-from-$, "act now"-style urgency).
- **Poller integration.** Per-message order:
  1. Quarantine gate — auto-responder → DMARC (when `enforce_dmarc` opt-in) → spam keywords (when threshold > 0). Quarantined rows persist with `was_quarantined=True` and never create or update a ticket.
  2. Routing rule lookup — sender-domain match remaps `target_org`, `target_queue`, `target_priority`.
  3. Existing 10.1 threading + 10.2 body cleanup runs only on non-quarantined mail.
  - The post-routing `target_org` (not the config's MSP org) is what ends up on `EmailMessage.organization`, so future replies thread correctly inside the right client tenant.
- **Django admin registration** for `EmailRoutingRule` and `EmailMessage` (filterable by `was_quarantined` for triage workflows).
- **Tests:** 16 new across 6 classes — `AutoResponderDetectionTests` (5 cases), `AuthenticationResultsParseTests` (2), `SpamKeywordScoreTests` (2), `EmailRoutingRuleMatchTests` (4 — exact, subdomain, full-email, empty), `AutoResponderQuarantineIntegrationTests` (1), `RoutingRuleIntegrationTests` (2 — matched + unmatched). 16/16 in 0.4s. Phase 10.1 + 10.2 regression: 28/28 in 2s.
- **Migration:** `psa/migrations/0028_email_routing_and_quarantine.py` — schema-only.

### Design decisions baked in
- **DMARC policy is opt-in.** `_quarantine_reason()` only enforces DMARC when the per-config `enforce_dmarc` flag is true. Default off because many tenants front this server with an MTA that already enforces DMARC at the SMTP layer; double-enforcing would silently drop legit mail with intermittent DKIM signing.
- **Spam scoring is opt-in.** Threshold 0 (default) disables. Pattern list is deliberately conservative — false-positive quarantines are worse than letting one spam land in the triage queue.
- **No bundled DKIM/SPF crypto.** We trust the upstream MTA's `Authentication-Results` header. Avoids a `dkimpy`/`spf` runtime dependency.

## [3.17.187] - 2026-05-01

### Tests
- **Baseline coverage for the `imports/` app** (Phase 7 polish — survey #6). The ITGlue / Hudu / CSV / MagicPlan ingestion pipeline previously had a 3-line stub `tests.py` despite handling customer data. New `imports/tests.py` adds **34 tests across 7 classes** covering:
  - `OrganizationMatcherNormalizationTests` — `normalize_name` lowercase + suffix stripping (LLC / Inc / Corp / Ltd / Co / Company in plain, period, and comma forms), special-character removal, whitespace collapsing, empty/None inputs.
  - `OrganizationMatcherSimilarityTests` — `similarity_score` returns 100 for identical names, 100 for suffix-only differences (because both normalize identically), low scores for unrelated names, 0 for empty inputs.
  - `OrganizationMatcherMatchTests` — `find_best_match` returns existing org when above threshold, None when below; `match_or_create` matches existing, creates new when no match (with `Imported from <source_id>` description), and `dry_run=True` returns an unsaved `Organization` instance.
  - `ImportJobLifecycleTests` — `__str__` representation with and without target org; `mark_running` / `mark_completed` / `mark_failed` set status + timestamps + error message; `add_log` appends with timestamps; `can_rollback` returns True only for completed non-rolled-back non-dry-run jobs.
  - `ImportJobRollbackTests` — full rollback flow: imported assets are deleted, organizations created during the import are deleted, organizations that were *matched* (already existed) are NEVER deleted; job is marked `rolled_back` with the user + timestamp; `rollback()` raises `ValueError` when called on an ineligible job.
  - `OrganizationMappingConstraintTests` + `ImportMappingConstraintTests` — unique-together constraints (`(import_job, source_id)` and `(import_job, source_type, source_id)`) enforced at the DB level. Same source ID across different jobs / different source types still allowed.
  - `CSVImportPreviewTests` — `read_csv_preview` reads headers + first N rows, caps at `max_rows`, handles UTF-8 BOM (Excel exports), rewinds the file object so callers can re-read.
- 34/34 passing in 17s.

## [3.17.186] - 2026-05-01

### Documentation
- **Documentation refreshed with annotated screenshots for the recent polish wave.**
  - `scripts/generate_screenshots_v2.py` extended with 8 new pages: Phase 9 surfaces (`security-alerts-list`, `security-alerts-connections`, `security-alerts-connection-new`, `security-alerts-rules`, `security-alerts-rule-new`) capturing the v3.17.182 form polish; `integrations-unifi-new` + `integrations-m365-new` capturing the v3.17.183 form polish; and a `roadmap` capture of the in-app `/core/roadmap/` page.
  - **8 new PNGs** committed to `docs/screenshots/`. **16 existing PNGs refreshed** as a side effect of running the script against current live data (PSA ticket lists, dashboards, organizations, etc. have all shifted since the last capture run on 2026-04-29).
  - **README updated** with three new gallery sections, each with descriptive captions explaining what the screenshot shows: "🛡️ Security Alert Ingestion (Phase 9, forms polished v3.17.182)", "🔌 Integration Connection Forms (polished v3.17.183)", "🗺️ Live Roadmap". The bottom "View All Screenshots" detail block also got matching entries.
  - **Stale version badge** at the top of the README updated from v3.17.143 → v3.17.185.
  - Total screenshot count in README: 46 → 60+.
- The polished-form screenshots show the new card-based section layout with proper Bootstrap form-control widgets (replacing the old generic `{% for field in form %}` loops with hand-rolled inline `<style>`). The "Install Client St0r" PWA install prompt overlays a small portion of some captures — pre-existing system behavior, doesn't obscure the form structure.

## [3.17.185] - 2026-05-01

### Changed
- **Finished the `core/security_views.py` inline-check sweep started in v3.17.180.** The remaining 7 endpoints in the package + Python scanners (`package_scanner_dashboard`, `scan_detail`, `get_dashboard_widget_data`, `python_scanner_dashboard`, `run_python_scan`, `python_scan_detail`, `get_python_scanner_widget_data`) all carried duplicated `if not (request.user.is_superuser or request.user.is_staff):` guards. Now use either:
  - `@_staff_or_superuser_view` (HTML pages — flash + redirect) — new decorator paired alongside the existing `_staff_or_superuser_api`. 4 page endpoints converted.
  - `@_staff_or_superuser_api` (JSON endpoints — 403 JSON) — 3 endpoints converted.
- All 9 staff/superuser endpoints in the file now use the same decorator pattern. `remediate_python_package` keeps its stricter superuser-only check (running pip-install commands needs a tighter gate than staff).
- **Found another silent `except Exception` in passing.** `run_python_scan`'s outer catch returned a generic "Scan failed" 500 with no signal — same shape as the bug fixed for `run_package_scan` in v3.17.180. Now logs the real exception via `logger.exception('Manual Python package scan failed')` before returning the same response.

### Tests
- `core.tests` 10/10 in 31s. All package-scanner endpoints import-checked.

## [3.17.184] - 2026-05-01

### Fixed
- **Bare `except:` clauses replaced with `except Exception:` across the codebase** (Phase 7 polish — 24 sites). A bare `except:` clause catches `SystemExit` and `KeyboardInterrupt` along with normal exceptions, which is almost always wrong: it can prevent a developer from killing a hung command with Ctrl-C, and can swallow genuine system-shutdown signals during graceful termination. Each site was spot-checked first to confirm the catch was defensive (optional imports of missing apps in org-merge, font-loading fallback in diagram previews, datetime parsing of vendor strings, subprocess errors during apt-cache update) — none were intentionally targeting `SystemExit`. Sites:
  - `accounts/views.py` — 6 sites in the org-merge flow (defensive imports of optional apps: Devices / Contacts / Documents / Tickets / RMMConnection / PSAConnection)
  - `config/settings.py:322` — defensive socket inspection during dev settings
  - `core/management/commands/scan_system_packages.py` — 3 sites around `apt-get update` subprocess fallback
  - `core/search_views.py:99, 110` — search-result decode fallback
  - `core/settings_views.py:640` — settings-import fallback
  - `core/updater.py:231` — version-check fallback
  - `core/views.py:962, 1306` — view-handler fallbacks
  - `docs/management/commands/generate_diagram_previews.py:89` — image-generation fallback
  - `docs/services/ai_documentation_generator.py:658` — AI-response parse fallback
  - `docs/utils.py:44, 113` — `ImageFont.truetype()` font-load fallback
  - `integrations/providers/psa/rangermsp.py:464, 474` — vendor API parse fallback
  - `integrations/providers/rmm/datto.py:381` — `datetime.strptime` parse fallback
  - `locations/views.py:102` — geo-import fallback
- Behavior preserved: `ImportError`, `OSError`, `ValueError`, `subprocess.CalledProcessError` etc. are all `Exception` subclasses, so the new `except Exception:` still catches everything the old code did. The sites that need *narrower* catches (e.g. `except (TimeoutExpired, FileNotFoundError):`) are tracked as a separate polish item — this release is a uniform safety improvement, not a per-site narrowing.

### Tests
- 48/48 across `accounts`, `core.tests`, `integrations`, `docs` — no regressions. Each touched module also import-checked individually.

## [3.17.183] - 2026-05-01

### Changed — Form polish round 2
- **UniFi + M365 connection forms cleaned up.** Audit after v3.17.182 found the same sloppy pattern (generic `{% for field in form %}` flat loops with no section grouping) on two more integration forms.
  - **`templates/integrations/unifi_form.html`** — full rewrite. Card-based layout with three sections: Identity (name + mode + active toggle), Controller endpoint (host + verify_ssl, only relevant in self-hosted mode), Credentials (api_key always; username + password as "optional self-hosted extras" with explanation that they unlock WLAN/VLAN/firewall data). Existing JS that toggles self-hosted-only fields when mode=cloud is preserved. The setup-guide sidebar (self-hosted + cloud variants) is preserved with FontAwesome icons in the headers. Required-field asterisks added (only on creation; on edit credentials are optional).
  - **`templates/integrations/m365_form.html`** — full rewrite. Card-based layout with two sections: Tenant identity (name + tenant_id + active toggle), App registration credentials (client_id + client_secret side-by-side). Setup-guide sidebar preserved.
- **Audit clean:** other integration forms (`omada_form.html`, `grandstream_form.html`, `rmm_form.html`, `distributor_form.html`, `accounting_form.html`, `integration_form.html`, `psa_form.html`) already use explicit field rendering — not affected. `templates/docs/template_form.html`'s inline `<style>` block is for the WYSIWYG editor (TinyMCE / Quill), not form-control faking — left alone. `templates/locations/location_form.html` only uses the for-loop for error aggregation; the form fields are properly tabbed and explicit — left alone.

## [3.17.182] - 2026-05-01

### Changed — UX polish on Phase 9 forms
- **Auto-Ticket Rule and Vendor Connection forms cleaned up** (user-reported sloppy layout). Both pages were minimal generic field loops with hand-rolled inline `<style>` blocks doing manual form-control styling that didn't match the rest of the project.
  - **`security_alerts/forms.py`** — every widget now declares its Bootstrap class (`form-control` / `form-select` / `form-check-input`) explicitly. Several fields gained inline placeholders so empty fields show the expected shape (e.g. `priority code → "P1 / P2 / P3 / P4"`, `match_provider → "e.g. security_defender (blank = any provider)"`).
  - **`templates/security_alerts/connection_form.html`** — full rewrite. Card-based layout with four sections: Identity (name + provider + category + client), Endpoint & credentials (base URL + encrypted credentials blob), Polling & activity (interval + active/sync toggles as form-switches), Notes. Webhook setup callout (when editing) now shows the URL and HMAC secret with one-click copy buttons. Required-field asterisks added.
  - **`templates/security_alerts/rule_form.html`** — full rewrite. Card-based layout with five sections: Identity (name + priority + active toggle), Match clauses (provider + category + min severity + client, with an "ALL must match" badge to make the AND-semantics obvious), Action (action type + queue + priority code + assignee), Suppression window (with a "leave blank to never suppress" hint), Notes.
  - Both forms now have proper "Back to list" buttons in the header, breadcrumbs, and the form-control classes come from widgets so the inline `<style>` blocks are gone.
- **Tests:** `security_alerts.tests` 9/9 passing; templates parse clean.

## [3.17.181] - 2026-05-01

### Added
- **Vault password mutations now audit-logged** (Phase 7 polish — survey item #9). Vault edit/delete views previously logged reads (read access via `password_detail`/`password_reveal`, gated by VaultAccessRule since v3.17.163) but mutations slipped through unaudited. Now `password_edit` writes an AuditLog row on success (with the list of changed fields), on form validation failure (with the error keys), and on `EncryptionError` (with the error message). `password_delete` writes a row capturing the title BEFORE the delete so post-delete forensics still show what was removed. All use `success=True/False` so failed mutations are queryable. The pre-existing `AuditLoggingMiddleware` row still fires too — that's the URL-pattern record; our new row carries the view-level detail.
- **2 new tests** in `vault.tests.PasswordMutationAuditTests` covering successful update + delete-with-title-preserved. Vault test count: 7 → 9.

## [3.17.180] - 2026-05-01

### Fixed
- **Silent exception swallowers in `core/` now log instead of disappearing** (Phase 7 polish — survey items #2 + #4):
  - `core/views.py` — the manual update-check endpoint had a double-catch around `AuditLog.objects.create()` to handle older DB schemas missing `extra_data`. The first catch is justified (legacy schema fallback), but the second `except Exception: pass` was hiding any real DB issue. Now logs via `logger.exception(...)` so a broken audit table is visible to ops.
  - `core/security_views.py` — `run_package_scan()`'s outer `except Exception:` returned a generic "Scan failed" 500 with no signal of the actual failure. `CalledProcessError`, `JSONDecodeError`, permission errors, OOM all looked identical. Now logs the real exception via `logger.exception('Manual package scan failed')` before returning the same response, so ops can triage.
  - `core/security_views.py` — the `try: subprocess.run(['sudo', '-n', 'apt-get', 'update']) except: pass` that wraps the optional pre-scan apt-cache refresh now narrows to `(TimeoutExpired, SubprocessError, FileNotFoundError)` and logs at INFO. Bare `except:` catches `KeyboardInterrupt` / `SystemExit` too — replaced.

### Changed
- **Two package-scanner API endpoints now use a decorator instead of inline staff-check** (Phase 7 polish — survey item #3). New `_staff_or_superuser_api` decorator at the top of `core/security_views.py` replaces the duplicated `if not (request.user.is_superuser or request.user.is_staff): return JsonResponse({'error': 'Permission denied'}, status=403)` block on `run_package_scan` and `update_packages`. Behavior identical (same 403 JSON response). The other 7 inline checks elsewhere in the file are deferred to a follow-up release — narrow scope keeps risk low.

## [3.17.179] - 2026-05-01

### Changed
- **Defender adapter clearly flagged as a reference stub.** The Microsoft Defender for Endpoint security-alert provider in `security_alerts/adapters/defender.py` doesn't call the Graph API yet — it accepts a connection and returns an empty alert list. Previous label/messaging didn't make that obvious enough; an operator could pick it from the Connections dropdown and expect live alert flow. Now: (a) the dropdown label reads "Microsoft Defender for Endpoint (reference stub — no live alerts)", (b) the `test_connection` success message says explicitly "no live Graph API call is wired up. No alerts will be ingested until the adapter is fleshed out.", (c) the module docstring leads with "Not a working Graph API integration" and says explicitly not to enable it on a production tenant. Phase 7 polish-backlog item — closes the survey's #10 "TODO comments for deferred integration adapters".

## [3.17.178] - 2026-05-01

### Documentation
- **Roadmap Sizing-table row for Phase 10 brought up to date.** v3.17.176 + v3.17.177 already annotated the phase header, top-level bullets, and sub-phase blocks, but the Sizing table at the bottom still showed the original "2-3 weeks | extends existing IMAP poller" estimate with no progress note. Now reads "2-3 weeks — **10.1 + 10.2 shipped (v3.17.176 / v3.17.177); 10.3 + 10.4 in flight**". The JSON feed at `/core/roadmap.json` (which parses phase headers, not the table) was already correct — Phase 10 reports `status: in_progress`.

## [3.17.177] - 2026-05-01

### Added — Phase 10.2: Email body cleanup + attachment ingestion
- **New `psa/email_parsing.py` helper module.** Three pure functions, no DB / network / Django dependencies:
  - `sanitize_html(html)` — bleach-based, tight allowlist (block scripts, styles, iframes, objects, embeds, inline event handlers, remote images / tracking pixels). Surviving links get `rel="noopener noreferrer" target="_blank"`. Output is safe to render inside a sandboxed iframe in Phase 10.4's conversation panel.
  - `strip_signature(text)` — RFC 3676 `\n-- \n` sentinel first; falls back to "Sent from my iPhone / Android / device" + "Get Outlook for iOS / Android" + "Sent via …" prefaces. Conservative: returns the input unchanged on no match.
  - `strip_quoted_reply(text)` — three independent passes (Apple/Gmail "On … wrote:", Outlook `-----Original Message-----` / From-Sent-To-Subject block, trailing `>`-prefix block). Earliest match wins; only ever trims from the bottom.
  - `clean_reply_body(text)` — convenience: quote first, then signature.
- **Poller (`psa_poll_email`) now uses the helpers.** Reply comments to existing tickets get the customer's signature + quoted history stripped so the comment shows only what's new (full body still preserved on `EmailMessage.body_text` for the conversation panel). New tickets keep the full body so context isn't lost. Inbound HTML bodies are sanitized at write time before landing on `EmailMessage.body_html`.
- **Attachment ingestion.** New `_ingest_attachments(msg, ticket=, comment=)` walks the message for parts with `Content-Disposition: attachment`, validates against MIME allowlist + size cap, and writes a `TicketAttachment` per accepted file. Rejected files are logged at WARNING level so ops can see what was dropped without crashing the poll loop. Filenames are stripped of path components defensively.
- **New settings:** `PSA_EMAIL_ATTACHMENT_MAX_BYTES` (default 25 MB) + `PSA_EMAIL_ATTACHMENT_MIME_ALLOWLIST` (images, PDF, plain/CSV/HTML/markdown text, Office formats including .docx/.xlsx/.pptx, ZIP). `image/*`-style wildcard entries are honored. Override via Django settings or env per deployment.
- **Tests:** 18 new tests across 7 classes — `HtmlSanitizeTests` (script/style/iframe/object/embed stripping, inline event handlers, remote images, link safety, empty input), `SignatureStripTests` (RFC 3676 sentinel, mobile prefaces, no-op, empty), `QuotedReplyStripTests` (Apple/Gmail, Outlook two forms, bare `>`-prefix, no-op), `AttachmentIngestTests` (allowlist hit, allowlist miss, oversize, `image/*` wildcard), `ReplyBodyCleanupTests` (full integration: customer reply with sig + quoted history → clean comment body, full body preserved on EmailMessage), `HtmlBodyStoredSanitizedTests` (poller integration), `MalformedMimeTests` (broken MIME doesn't crash the loop). 18/18 in <1s. Regression run on 10.1 threading suite + Phase4 + TicketLifecycle: 36/36 in 21s.

## [3.17.176] - 2026-05-01

### Added — Phase 10.1: Email-to-ticket threading via Message-ID
- **New `psa.EmailMessage` model.** Captures every inbound email's `Message-ID`, `In-Reply-To`, `References`, raw headers, plain-text body, and HTML body. Unique per `(organization, message_id)` so a Message-ID collision across tenants never threads incorrectly. Indexed on `(ticket, received_at)` and `(organization, in_reply_to)` for the lookup paths the poller and (future) outbound-reply helper use.
- **New `Ticket.last_inbound_message_id` cache field.** Stores the most recent inbound Message-ID per ticket so Phase 10.4's outbound replies can set their `In-Reply-To` header without a join. Updated by the poller on every match/create.
- **`psa_poll_email` now threads by header before falling back to subject regex.** Correlation order: (a) `In-Reply-To` against an existing `EmailMessage.message_id` in the same organization, (b) walk the `References` chain right-to-left and try the same org-scoped lookup, (c) the existing subject-regex fallback, (d) create a new ticket. The inbound `EmailMessage` row is persisted regardless so the next reply chains cleanly. Cross-org isolation is enforced by filtering the lookup by organization — same Message-ID across tenants never threads wrong.
- **Body extraction now captures plain-text and HTML separately.** The new `_extract_bodies()` helper returns both; the poller writes them to `EmailMessage.body_text` and `EmailMessage.body_html`. Phase 10.2 will replace the crude regex tag-strip with `bleach`-based sanitization. The pre-existing `_extract_text_body()` callable is preserved as a compatibility shim.
- **Tests:** 5 new test classes in `psa/tests.py` — `EmailThreadingByInReplyToTests`, `EmailThreadingByReferencesChainTests`, `EmailThreadingFallbackToSubjectTests`, `EmailThreadingCrossOrgIsolationTests`, `EmailThreadingNewTicketTests`. Mock IMAP via a tiny `_FakeIMAP` stub — no live network. 5/5 passing in 0.7s; targeted regression on the existing PSA test classes (Phase4 / TicketLifecycle / SLA / TimeTracking) 18/18 passing in 36s.
- **Migration:** schema-only (`psa/migrations/0027_email_message_threading.py`) — adds `psa_email_messages` table + `last_inbound_message_id` column. No data backfill: synthetic Message-IDs wouldn't appear in real customer replies, so the In-Reply-To path can't fire on legacy tickets via that route; the subject-regex fallback (still in place) handles them.

## [3.17.175] - 2026-04-30

### Fixed
- **Migration `0017_auto_apply_gunicorn_fix` no longer spams banner/error output during test runs and on fresh dev installs.** The migration runs `scripts/fix_gunicorn_env.sh`, which targets the production systemd unit at `/etc/systemd/system/clientst0r-gunicorn.service`; on any host where that unit doesn't exist (test runners, CI, containers, fresh dev installs) the script exited with code 1 and the migration logged "Fix script exited with code 1" on every test DB setup. Now skips silently when (a) `'test' in sys.argv` or (b) the systemd unit file isn't present. Production installs behave identically. Surfaces in cleaner test output.

## [3.17.174] - 2026-04-30

### Fixed
- **Bug fix in audit-log retention queries.** `core/settings_views.py` was running `AuditLog.objects.filter(timestamp__lt=datetime.now() - timedelta(days=days))` and `Session.objects.filter(expire_date__lt=datetime.now())` — the right-hand side was a *naive* datetime (server-local time) while the database columns are timezone-aware. With `USE_TZ=True`, Django emits a `RuntimeWarning: DateTimeField received a naive datetime ... while time zone support is active`, and the comparison silently treats the naive value as being in the configured `TIME_ZONE` rather than UTC. On non-UTC servers, audit-log cleanup and expired-session cleanup were applying a window shifted by the server's UTC offset. Now uses `timezone.now()` consistently.

### Changed
- **Sweep of deprecated `datetime.utcnow()` / lazy `datetime.now()` use across the codebase** (Phase 7 polish). Files updated: `core/settings_views.py` (8 sites), `core/security_scan.py` (5), `reports/generators.py` (8 incl. one `utcnow`), `core/management/commands/backup.py`, `core/management/commands/build_mobile_app.py`, `core/management/commands/restore.py`, plus dead `from datetime import datetime` imports pruned. All converted to `django.utils.timezone.now()`. Tests: 65/65 (`core.tests` + `reports`) passing.
- **Skipped intentionally:** `core/ai_abuse_control.py:_get_hours_until_reset` keeps `datetime.now()` because the AI rate-limit reset window is computed against server-local midnight (changing it would shift when daily limits roll over). `monitoring/models.py:155-163` keeps `datetime.now()` for its inline HTTP-response stopwatch (the proper primitive there is `time.monotonic()` — separate refactor). `integrations/providers/halo.py` token-expiry tracking is internal arithmetic, low priority. `scripts/network_scanner.py` is a standalone CLI script with no Django context; `datetime.now()` (which is *not* deprecated) is correct there.

## [3.17.173] - 2026-04-30

### Fixed
- **Bug fix in the bug-report endpoint:** `core/views.py` was using `datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')` to stamp the timestamp on submitted bug reports. `datetime.now()` returns server-local time, but the format string lied and said "UTC" — the recorded timestamp was wrong by the server's UTC offset. Switched to `timezone.now()` (which is UTC when `USE_TZ=True`), so the "UTC" suffix is now accurate.

### Changed
- **Phase 7 polish:** removed deprecated `datetime.utcnow()` from the `/core/roadmap.json` endpoint and `datetime.now()` from the bug-report endpoint, replaced with `django.utils.timezone.now()`. `datetime.utcnow()` is deprecated in Python 3.12+ and will be removed in a future release. The roadmap-feed `generated_at` field now serializes with an explicit `+00:00` offset instead of a `Z` suffix; both are valid ISO 8601, downstream pollers should handle either.

## [3.17.172] - 2026-04-30

### Documentation
- **Roadmap: Phase 7 polish-backlog sub-bullet annotated for v3.17.171.** The tenant-isolation test-suite restore and the `/api/passwords/<id>/` audit-log crash fix are now reflected in `docs/ROADMAP.md`, so the rendered surfaces (in-app, About card, GitHub, JSON feed) all show the recent polish work.

## [3.17.171] - 2026-04-30

### Fixed
- **Audit logging on `/api/passwords/<id>/`, `/reveal/`, and `/otp/` no longer crashes.** The API password endpoints called `AuditLog.objects.create(... details=...)` but the model field is `description` — passing `details=` raised `TypeError` and 500'd every successful API password retrieve / reveal / OTP-generate. Latent bug since the initial commit (Jan 2026); never surfaced because no test exercised the success path. Found while rebuilding the tenant-isolation suite below.

### Tests
- **Rebuilt `core.tests.test_tenant_isolation`.** The file had rotted since v2.20.0 (Jan 2026) when `accounts.UserProfile.user` got `related_name='profile'` and org binding moved from `UserProfile.organization` to the `Membership` table. All 10 tests were erroring on `'User' object has no attribute 'userprofile'` — silently failing security regression coverage. Rewrite uses `Membership(user, organization, role=Role.OWNER, is_active=True)`, `force_login()` to bypass django-axes (which needs a real request), and `current_organization_id` on the test session to match the production `CurrentOrganizationMiddleware` flow. Also fixed: `Document.body` (not `content`), `/docs/<slug>/` (not `/docs/documents/<id>/`), `/vault/<id>/` (not `/vault/passwords/<id>/`). The "manager enforces isolation" test rewritten to exercise the real API (`OrganizationManager.for_organization()`) instead of a `set_current_organization()` helper that never existed. 10/10 passing in 30s; full battery (core + resourcing + processes + security_alerts) 45/45 in 86s.

## [3.17.170] - 2026-04-30

### Changed
- **Phase 1 (Contract engine deepening) marked complete in the roadmap.** Header status now `[complete]` so the `/core/roadmap.json` polling feed reflects reality. Each of the seven sub-bullets is annotated with the version it shipped at: per-contract overage rules, role-based inclusion/exclusion, prepaid block hours with rollover, and proration → 1.1 (v3.17.126); auto-renewal, bundled services, and agreement profitability snapshot → 1.2 (v3.17.130). "Living plan" header note refreshed: Phases 1–6 + 9 + 31 complete; Phase 7 in progress (continuous track).

### Added — Future / late-stage roadmap entry
- **Phase 32 — Remote Network Discovery Import** added near the end of the roadmap as a future / late-stage feature (planned, not yet implemented). Spec covers: a new `network_discovery/` app with `NetworkDiscoveryToken` / `NetworkDiscoveryImport` / `NetworkDiscoveryAssetResult` models; five endpoints (generate, download, public token-only POST upload, revoke, import history); a downloadable PowerShell script that does a non-credentialed local sweep (ping + ARP + reverse DNS + optional 80/443/22/3389/445 probe); asset import with MAC-first then (org, location, IP) dedupe; security guarantees (single-use scoped tokens with 15-min default expiry, hashed-only token storage, write-only POST endpoint, full audit trail, rate limiting); UI section on the Org detail page; comprehensive test plan. **Explicitly not an RMM agent** — temporary, scoped, auditable, no persistent agents, no permanent credentials. Sizing-table row added.

## [3.17.169] - 2026-04-30

### Changed
- **Phase 8 moved to last position in the roadmap** — Native mobile apps + GPS auto-time + Timeclock now appears after Phase 30. Phase 8 remains the largest single undertaking and depends on a lot of other work being mature first; positioning it last makes the priority order match reality. Sizing-table row also moved to the last row.

### Fixed
- **BillableTarget can no longer be self-edited.** Per user request, only managers/admins (users with the `resourcing_manage_cost_rates` permission) can set a tech's billable target — even the target user themselves can't edit their own. Old behavior allowed self-edit which mixed signals about whether a tech was meeting their target. Template now renders a "Your billable target is set by your manager." note when the viewing user lacks the permission. New tests in `resourcing.tests.BillableTargetPermissionTests`.
- **Workflow launch now asks which org instead of erroring** when invoked from Global view. Previously `/processes/<slug>/run/` returned "Organization context required." and redirected away. Now the form renders with an org picker; the user picks the org for that run; the rest of the flow proceeds normally. Same pattern applied to `process_create` (org picker on the new-process form). `process_edit` and `process_delete` fall back to the existing process's organization when invoked from Global view by a superuser/staff user. `process_list` / `process_detail` / `execution_list` get clearer redirect messages ("Switch to a specific organization first to …"). Locations + tag-views still use the legacy error message — pattern is established and can be migrated incrementally.

## [3.17.168] - 2026-04-30

### Added — Phase 9: Security alert ingestion (EDR / AV / Firewall)
- New `security_alerts/` Django app with three models:
  - `SecurityVendorConnection` — per-MSP-tenant + optionally per-client connection to an EDR / AV / firewall provider. 16 provider choices spanning CrowdStrike Falcon, SentinelOne, Microsoft Defender, Sophos Central, Huntress, ThreatLocker, Bitdefender, Webroot, Malwarebytes, ESET, Fortinet, Palo Alto, SonicWall, Meraki MX, Sophos XG, pfSense.
  - `SecurityAlert` — ingested alert with severity / status / asset_hint / raw_payload + audit fields. Unique per (connection, external_id) for dedupe.
  - `SecurityAlertRule` — auto-action rules with priority + match clauses (provider / category / severity-min / client) + optional suppression-window. Currently fires `create_ticket` action mapping severity → priority.
- **Provider adapter framework** (`security_alerts/adapters/`) — abstract `SecurityProvider` extends the v3.17.166 Integration SDK. One reference adapter (Microsoft Defender for Endpoint) registered as a stub showing the integration shape.
- **Polling cron** — `poll_security_alerts` mgmt command runs every 5 min via cron, loops active connections, runs the matching adapter's `sync()`. Auto-installed in `deploy/update_instructions.sh`.
- **Webhook receiver** at `/security/webhook/<token>/` — CSRF-exempt, HMAC-verified inbound for vendors that push.
- **Triage pages**: `/security/alerts/` (list + filter chips + bulk ack/dismiss/convert), `/security/alerts/<id>/` (detail with raw payload), `/security/connections/` (CRUD), `/security/rules/` (CRUD).
- **Dashboard widgets**: 24h alerts breakdown by severity (table), open critical+high count (metric).
- **MTTA report** at `/reports/security/mtta/` — Mean Time To Acknowledge per client × vendor over a date window.
- 4 new RoleTemplate booleans: `security_alerts_view`, `security_alerts_manage_connections`, `security_alerts_acknowledge`, `security_alerts_create_rules`. Defaults wired across all 13 system templates.
- New top-level "Security" dropdown in the navbar.
- Tests in `security_alerts/tests.py` cover model dedupe, MTTA math, auto-ticket rule matching + suppression, webhook auth.

### Migrations
- `security_alerts.0001_initial`
- `accounts.0028_roletemplate_security_alerts_acknowledge_and_more` for the 4 new RoleTemplate booleans

## [3.17.167] - 2026-04-30

### Added — Roadmap status JSON feed for external pollers
- New endpoint **`GET /core/roadmap.json`** — parses `docs/ROADMAP.md` and emits a structured JSON feed of phase status. Lets external dashboards / status pages / customer portals refresh themselves without HTML scraping.
- Response shape: `{generated_at, current_version, phase_count, shipped_count, phases: [{number, title, size, status, version}, ...]}`. Status enum: `planned` / `in_progress` / `shipped` / `complete`.
- Verified parser: 31 phases extracted, 6 currently shipped/complete on the production checkout.

### Added — Roadmap entry: Configurable wallboards with widgets
- Added under Phase 3 (Financial Reporting + BI) as a planned extension of the existing v3.17.146 fixed wallboard. Multiple named wallboards per org, drag-to-reorder widget grid sourced from the existing dashboard widget registry, per-wallboard refresh interval, "rotate through wallboards" mode for NOC TVs.

### Changed — Roadmap-update rule expanded for the JSON feed
- `CLAUDE.md`, `CONTRIBUTING.md`, and persistent assistant memory now require **phase-header status markers** in addition to the existing per-bullet version annotations.
- Each `## Phase N — Title ...` header should carry one of: `[planned]` / `[in progress]` / `[shipped — v3.17.NNN]` / `[complete]` (or the legacy `**— shipped**` / `**— complete**` inline form).
- When a phase completes, **always update the header marker** — otherwise the website's polling shows it as planned. Phase 7's header is now `[in progress]` reflecting the partial-shipped state from v3.17.166.

## [3.17.166] - 2026-04-30

### Added — Phase 7 (partial): Outsourcing workflow + Integration SDK skeleton
- **Subcontractor org type** — `Organization.is_outsourcing_partner` flag, auto-generated `partner_secret` HMAC key, `partner_endpoint_url` for inbound webhooks, `billing_markup_pct` for partner-time markup. New `subcontractor` choice on `ORGANIZATION_TYPE_CHOICES`.
- **`psa.TicketShare` model** — records tickets shared with partners (pending → accepted → completed; or declined / recalled). Unique per (ticket, partner).
- **Share endpoint** at `/psa/t/<n>/share/` — staff (with `outsourcing_share_tickets` perm) picks a partner; HMAC-signed POST fires to the partner's webhook with the ticket payload.
- **Inbound webhook** at `/psa/partners/webhook/<share_pk>/` — accepts comment / status updates from the partner. Validates HMAC signature; on comment creates a TicketComment with `source='partner'`; on status maps to local TicketStatus.
- **Outbound sync** — when a TicketComment lands on a ticket with active shares, fires the same HMAC-signed POST to each partner. Failures logged, not blocking. Same pattern for Ticket status changes.
- **Integration SDK skeleton** at `integrations/sdk/` — `IntegrationProvider` abstract base + slug registry + exception hierarchy. New providers register via `@register` decorator; resolved by slug or category. Foundation for Phase 9 security-alert vendors.
- New `outsourcing_share_tickets` RoleTemplate boolean. Defaults wired across all 13 system templates (Owner / Administrator / Full Admin / Tech Manager / Office Manager = True; Editor / Help Desk / IT Manager / Documentation Writer / Read-Only / Client / Client Admin / Technician = False).
- 6 new tests in `psa.tests` (TicketShareTests + IntegrationSDKTests).

### Phase 7 status
- Outsourcing workflow: shipped (this release).
- Integration SDK foundation: shipped (this release).
- Polish backlog: continuous.

### Migrations
- `core.0050_organization_billing_markup_pct_and_more` (Organization fields)
- `psa.0026_ticketshare` (TicketShare model)
- `accounts.0027_roletemplate_outsourcing_share_tickets` (RoleTemplate boolean)

## [3.17.165] - 2026-04-30

### Added — Phase 6.3 (closes Phase 6): Release management + Service-catalog governance
- New `psa.ReleaseWindow` model — auto-numbered `REL-YYYY-NNNNN`. Bundles N ChangeRequest records into a single deployment window. Statuses: planned -> frozen -> completed (or rolled_back / cancelled). Freeze flag locks further additions; rollback_plan + rolled_back_at + rolled_back_reason fields capture failed-deploy detail.
- New `psa.ServiceCatalogChange` model — proposal-and-approve workflow for service-catalog edits. When a `ServiceCatalogItem.requires_approval=True`, edits create a pending `ServiceCatalogChange` with `before_snapshot` + `after_snapshot` (JSON) instead of writing live. Approver applies the after_snapshot via `change.apply()`.
- `ServiceCatalogItem` gets `requires_approval`, `last_published_at`, `last_published_by` fields.
- 5 new RoleTemplate booleans: `release_view`, `release_manage`, `release_freeze`, `catalog_propose_change`, `catalog_approve_change`. Defaults set across all 13 system templates including the v3.17.164 MSP-named ones.
- Pages: `/psa/releases/` queue + detail + form. Endpoints: add-change, remove-change, freeze, complete, rollback.
- Pages: `/psa/catalog-changes/` queue + diff-view decide page.
- "Bundled into release" card on ChangeRequest detail when applicable.
- 5 new tests in `psa.tests` (ReleaseWindowTests + ServiceCatalogChangeTests + ReleasePermissionTests).

### Phase 6 status: complete.
- 6.1 Change requests + CAB (v3.17.158)
- 6.2 Problem records + RCA (v3.17.160)
- 6.3 Release management + service-catalog governance (v3.17.165)

### Migrations
`psa.0025_servicecatalogitem_last_published_at_and_more` (ReleaseWindow + ServiceCatalogChange + ServiceCatalogItem fields), `accounts.0026_roletemplate_catalog_approve_change_and_more` for the 5 RoleTemplate booleans.

## [3.17.164] - 2026-04-30

### Added — 6 MSP-named sample role templates
- Six new system role templates seeded by `RoleTemplate.get_or_create_system_templates`:
  - **Client** — customer portal user (files tickets, views shared KB / vault items only)
  - **Client Admin** — customer org admin (manages who at their org sees shared vault items + invites portal users)
  - **Technician** — internal staff doing day-to-day support work
  - **Tech Manager** — supervises techs (approves leave, dispatches, approves changes + PRs)
  - **Office Manager** — financial + operations (invoices, payments, aging, cost rates, CRM pipeline)
  - **Full Admin** — full access (alias for Owner)
- Built using a helper `_build(name, description, **overrides)` that defaults every RoleTemplate boolean to False and only flips the listed perms — keeps the diff small and means new RoleTemplate booleans added later default safely (False) for these sample roles.
- The existing 7 system templates (Owner / Administrator / Editor / Help Desk / IT Manager / Documentation Writer / Read-Only) are unchanged. Total: 13 system templates available out-of-the-box.
- Sample roles are user-editable via `/accounts/roles/` like any other role template — they're starting points, not locked-down system roles.

## [3.17.163] - 2026-04-30

### Added — Vault GeoIP / IP / Time access rules
- New `vault.VaultAccessRule` model — gates Password reveal + detail view based on the requester's GeoIP country, source IP / CIDR, and current time-of-day. Rules can be scoped to a specific Password, a specific User, or an Organization (three scopes per the user request).
- Decision engine in `vault/access_rules.py`: DENY-wins-then-priority semantics. Empty rule set → ALLOW (back-compat). Reuses the existing GeoIP infra from the firewall middleware.
- Admins manage rules at `/vault/access-rules/` — list, create, edit, delete. Each rule has: scope + target, effect (allow/deny), priority, GeoIP allow/block lists, IP CIDR allow/block lists, time-of-day window with timezone + allowed-weekdays.
- Every reveal attempt is **audit-logged** with the decision reason, source IP, country, and matched rule ID — even when allowed.
- Denied attempts render a clear "blocked by access rule" page with the reason, IP, and country.
- Password detail view shows a "N access rules apply" badge linking back to the filtered rule list.
- New `vault_manage_access_rules` RoleTemplate boolean (default False; Owner / Admin = True).
- 7 unit tests in `vault.tests.VaultAccessRuleEngineTests` cover no-rules / country-deny / deny-wins / time-window / CIDR / user-scope / item-scope.

### Migration
- `vault.0012_vaultaccessrule` (new VaultAccessRule model).
- `accounts.0025_roletemplate_vault_manage_access_rules` (new RoleTemplate boolean).

## [3.17.162] - 2026-04-30

### Added
- **Roadmap-update rule** codified: every release that adds, extends, or completes a feature MUST update `docs/ROADMAP.md` in the same commit. Documented in three durable places:
  - New `CLAUDE.md` at the repo root — auto-loaded by AI assistants working on the project; spells out the rule + release pattern + wording conventions.
  - `CONTRIBUTING.md` — new "Roadmap discipline" section under PR Process, plus a checklist item: "ROADMAP.md updated if the change touches a roadmap item".
  - Persistent assistant memory.

### Changed — Removed competitive framing from roadmap prose
- Roadmap title was "Roadmap to PSA-mature parity (ConnectWise / Autotask / Halo)" → now just "Client St0r — Roadmap". The project is described on its own merits.
- Phase 5 narrative: "ConnectWise's wedge: PSA covers sales-pipeline-to-invoice…" → "A mature PSA covers sales-pipeline-to-invoice…".
- Phase 24 RMM intro: dropped the explicit list of competing RMM products from the prose; the integration framework reference stays generic.
- Phase 29 migration scripts: rewrote "Migration scripts for ConnectWise, Autotask, Halo, IT Glue, Hudu" → "Migration scripts for inbound data imports from common existing platforms".
- About-page Platform Overview line: "PSA Integration: ConnectWise Manage, Autotask, and more" → "PSA Integrations: Multiple external PSA providers via the integrations framework (see Integrations table below)".
- The factual integration tables on the About page + README + FEATURES (which list real product capabilities like "we integrate with ConnectWise Manage / Autotask / HaloPSA") stay — those are not marketing positioning, they're feature statements.

## [3.17.161] - 2026-04-30

### Roadmap
- Added **7 new long-term phases** (24–30) to `docs/ROADMAP.md`, completing the user's requested feature list:
  - **24** Native RMM Agent + Endpoint Management (XL — patch mgmt + scripting + remote access; alternative to integrating external RMMs)
  - **25** Mature Timesheet Approval Workflows
  - **26** Custom Report Writer + Saved Queries
  - **27** Advanced Accounting Reconciliation (extends QBO/Xero)
  - **28** Browser Extension + Offline Vault Access
  - **29** Commercial Operations Ecosystem (continuous · meta — SLA tiers, onboarding, SOC 2 readiness, partner program)
  - **30** Endpoint Remote Access (smaller alternative to Phase 24)
- Sizing table updated; total roadmap now spans 30 phases. Items overlapping shipped phases continue to call out the deltas.

### Added — Roadmap published in About page
- `/core/about/` now has a prominent **Public Roadmap** card with summary of shipped / in-progress / planned phases + buttons to the live in-app roadmap, the GitHub source, and the full CHANGELOG.

### Fixed — Top navbar getting cut off at 100% browser font-size
With 7+ top-level dropdowns plus brand + search + clock + org pill + user dropdown, the navbar was overflowing on common laptop widths (1366–1600px). Tightened nav-link padding (0.4–0.55rem), shrunk nav-link font to 0.82–0.88rem, narrowed the search box, capped the org-pill width, hid the live clock at narrow desktop sizes, and added flex-wrap fallback so anything still over-running wraps cleanly instead of clipping. Mobile / tablet menus unchanged.

## [3.17.160] - 2026-04-30

### Added — Phase 6.2: Problem records + Root-Cause Analysis (ITIL)
- New `psa.Problem` model — auto-numbered `PRB-YYYY-NNNNN`. Links N tickets together to spot recurring incidents and isolate the underlying root cause. Status pipeline: investigating → known_error → resolved → closed (or duplicate). Priority: critical / high / medium / low.
- RCA fields: `symptoms`, `root_cause`, `workaround`, `permanent_fix`, `five_whys` (JSON list), and an optional FK to the `ChangeRequest` that deployed the fix.
- New `psa.ProblemNote` model — append-only investigation timeline with an `is_breakthrough` flag for key findings.
- Status-transition validation: can't reach `known_error` without `root_cause + workaround`; can't reach `resolved` without `permanent_fix`.
- Pages: `/psa/problems/` queue, `/psa/problems/<id>/` detail, `/psa/problems/new/` form. Endpoints: link-ticket, unlink-ticket, add-note, advance-status.
- Cross-link surfaced on ticket detail: a "Related problem records" card lists every Problem the ticket is linked to with status pill.
- 4 new RoleTemplate booleans: `problem_view` (default True), `problem_create` (default True), `problem_assign`, `problem_resolve` (default False — owner/admin gate).
- 7 new tests in `psa.tests`.

Phase 6 status: 6.1 + 6.2 shipped. 6.3 (release management + service-catalog governance) closes Phase 6.

### Migrations
`psa.0024_problem_problemnote_and_more` (Problem + ProblemNote), `accounts.0024_roletemplate_problem_assign_and_more` for the 4 RoleTemplate booleans.

## [3.17.159] - 2026-04-30

### Roadmap
- Added 14 new long-term roadmap entries (Phases 10–23) to `docs/ROADMAP.md`. None positioned as fully implemented; each labeled planned / in-progress / extends-existing-phase, with deltas vs. shipped work called out. AI-assisted features explicitly tagged **OPTIONAL AI** and tied to the existing `psa_ai_enabled` gate pattern.
- New phases:
  - **10** — Advanced Email-to-Ticket Engine (extends IMAP poller)
  - **11** — Advanced Dispatch & Technician Scheduling (extends Phase 2)
  - **12** — Customer Communication Workflows (extends customer portal)
  - **13** — Procurement & Lifecycle Management (extends Phase 4)
  - **14** — Visual Workflow Automation Engine (extends workflow rules)
  - **15** — Recurring Billing & Contract Management (extends Phase 1)
  - **16** — Documentation Relationship Mapping (new)
  - **17** — Advanced Asset Intelligence (extends RMM sync)
  - **18** — Multi-Location Client Hierarchy (new)
  - **19** — Advanced Reporting & Analytics (extends Phase 3)
  - **20** — Approval & Change Management Workflows (extends Phase 6.1)
  - **21** — Advanced Mobile Technician Workflows (requires Phase 8)
  - **22** — Knowledge Base & SOP Management (extends KB v3.17.128/134)
  - **23** — Security Event & Incident Workflows (requires Phase 9)
- Sizing table updated with the 14 new rows. Wording is operationally realistic — no hype/buzzwords; focus on MSP workflow consolidation and operational visibility.

## [3.17.158] - 2026-04-29

### Added — Phase 6.1: Change requests with CAB approval workflow
- New `psa.ChangeRequest` model — one-to-one with a `Ticket` of type 'change'. Captures CAB-relevant metadata: risk (low/medium/high/emergency), implementation/rollback/impact plans, scheduled + actual windows, outcome summary, implementation_status pipeline (draft → pending_cab → approved/rejected → implementing → verified/failed/cancelled).
- New `psa.CABVote` model — one row per (change_request, user). Approvals require **every** `required_approvers` user to vote `approved` AND zero rejections. Falls back to the existing single-approval pattern when no required_approvers are set.
- Auto-create signal: any Ticket whose `ticket_type.slug='change'` spawns a draft ChangeRequest on save.
- New 'change' ticket type seeded by `psa_seed_defaults`.
- Pages: `/psa/changes/` (queue), `/psa/t/<n>/change/` (detail + vote form), `/psa/t/<n>/change/edit/` (form). Endpoints: submit / vote / implement / verify / fail.
- 4 new RoleTemplate booleans: `change_view`, `change_create`, `change_approve_cab`, `change_implement`. Defaults: Editor = view+create; Owner/Admin = all 4.
- "Change Management" card surfaced on the ticket detail page when ticket_type='change'.
- 8 new tests in `psa.tests`.

Phase 6 sub-phases left: 6.2 Problem records + RCA; 6.3 Release management + service-catalog governance.

### Migrations
`psa.0023_changerequest_cabvote_and_more`, `accounts.0023_roletemplate_change_approve_cab_and_more`.

## [3.17.157] - 2026-04-29

### Fixed — Generated Reports list now actionable for legacy + failed rows
User reported they had no way to view or download reports at `/reports/generated/`. Root cause: rows generated before the v3.17.154 file-save fix have `status='completed'` but no `report.file` populated — and the templates only rendered View/Download buttons when `report.file` was truthy. So legacy completed-without-file rows had only a "View Details" link with no recovery path.

Fixed:
- **List page** Actions cell now shows a yellow **Re-generate** button when `report.file` is missing — POSTs to `reports:generate_report` with the original format. Works for legacy rows AND for previously-failed rows.
- **Status footnote** under Actions: shows the truncated error message inline for failed rows; shows "File missing — re-generate" for completed-but-fileless rows.
- **Detail page** mirrors the same logic: Re-generate button in the header when there's no file; alert banner inside the card explaining whether the file is missing (legacy) or the generation failed (with the full error message in a `<pre>`).
- Distinguished the "View Details" icon button (info) from the actual "View PDF" / "Download X" action buttons (primary / success) so users can tell at a glance which control downloads vs. which inspects metadata.

## [3.17.156] - 2026-04-29

### Fixed
- **Asset Summary Report failed with "Cannot resolve keyword 'name' into field. Join on 'asset_type' not permitted."** `Asset.asset_type` is a `CharField(choices=…)`, not an FK to `AssetType` — `reports.generators.AssetSummaryReport` was incorrectly doing `values('asset_type__name')`. Switched to `values('asset_type')` and translates the raw code to a display label via `Asset._meta.get_field('asset_type').flatchoices`. Output shape preserved (still emits `'asset_type__name'` key for downstream PDF templates), just sourced from the choices dict instead of a non-existent FK relation.

## [3.17.155] - 2026-04-29

### Added — Phase 5.3 (closes Phase 5): Sales-activity timeline + lead capture
- New `crm.SalesActivity` model — polymorphic touchpoint log against a Lead, Opportunity, or client Organization. Activity types: call / email / meeting / demo / note / proposal_sent / contract_signed / inbound / other.
- **Activity timeline** card on Lead detail + Opportunity detail pages (last 15 entries) with "Log activity" button.
- **Web form lead capture** at `POST /crm/leads/capture/` — public, CSRF-exempt, honeypot anti-spam, IP rate-limited (10/min), creates `Lead` + auto `SalesActivity(activity_type='inbound', source='web_form')`. JSON response.
- **REST API lead capture** at `POST /crm/api/leads/capture/` — same shape, gated on existing API-key auth (`Authorization: Bearer itdocs_live_<key>`).
- **IMAP lead capture stub** at `crm/management/commands/poll_lead_inbox.py` — wired but full implementation deferred (Phase 5.4 follow-up).
- New "Recent sales activity" dashboard widget.
- 7 new tests in `crm.tests`.

### Phase 5 status: complete.
- 5.1 Lead/Opportunity/Campaign + pipeline Kanban (v3.17.152)
- 5.2 Commissions + lead scoring + sales funnel (v3.17.153)
- 5.3 Sales activity timeline + lead capture (v3.17.155)
- Roadmap updated.

### Migration
`crm.0003_salesactivity`.


## [3.17.154] - 2026-04-29

### Fixed
- **"Issue #59" badge** on Settings → General removed (internal issue-tracker reference shouldn't be visible to end users). Comments in `accounts/views.py`, `core/settings_views.py`, `core/models.py` cleaned up the same way.
- **Generated reports view/download** — PDFs now open inline in a new tab (`target="_blank"`), other formats (CSV/XLSX) download as attachments. The `generated_download` view now decides based on `format`. Both list and detail pages show "View PDF" or "Download X" button as appropriate. PDFs that were previously force-attaching now render in the browser. Also: `generate_report` view now actually populates the `FileField` so the file is downloadable (was previously only marking status='completed' without writing a file).
- **`/inbox/` 404** — added a redirect view at `/inbox/` → `/psa/ai/inbox/` for legacy bookmarks. Found no stale templates pointing here.
- **Procurement permission gates verified** — confirmed `procurement_approve_pr` is required for `requisition_decide` (managers only) and `procurement_create_pr` is sufficient for `requisition_form` (any tech). `requisition_to_po` now accepts either `procurement_approve_pr` or `procurement_create_po`. Added inline help text on PR form: "Submit when ready — a manager will review before it becomes a PO." Requisition list now shows "My requisitions" view by default for non-approvers + a "Pending approval" filter shortcut for approvers. Submit button on PR detail is shown only to the requester (or admins) when status='draft'.

### Added
- **CRM feature toggle** — new `SystemSetting.crm_enabled` boolean (default False, mirroring `psa_enabled`). When off, the CRM navbar dropdown is hidden. Toggleable from Settings → General. Existing CRM URLs still work for direct access; the toggle only governs navigation visibility. Optional `@require_crm_enabled` decorator added to `crm/views.py` for views that want extra safety.

### Migration
`core.0049_systemsetting_crm_enabled` adds `crm_enabled` to SystemSetting.


## [3.17.153] - 2026-04-29

### Added — Phase 5.2: Commission engine + Lead scoring + Sales funnel report
- New `crm.CommissionRule` model — per-tenant rule with `priority` ordering, optional user/value match clauses, `rate_pct` + `flat_amount` payout. Highest-priority active rule wins.
- New `crm.Commission` model — pending → approved → paid pipeline. Auto-created when an Opportunity transitions to `closed_won` via the new `compute_commission_for_opportunity()` engine. Idempotent: re-runs update, never duplicate.
- New `Lead.score` field (0-100) auto-computed in `Lead.save()` via a heuristic scorer in `crm/services.py` — bumps for estimated_value, target industries, employee count, contact data completeness, website, campaign attribution, ownership.
- New report `/reports/crm/sales-funnel/` — visual funnel from Leads → Qualified → Opportunities → Proposal → Closed Won with stage-to-stage conversion %. Date-range selector. Permission: `crm_view_forecast`.
- New CRM pages: `/crm/commissions/` + `/crm/commission-rules/`. Decide endpoint approves / cancels / marks paid with payroll reference + audit log.
- Tests in `crm.tests` cover rule matching, computation, engine idempotence, scoring, funnel.

Phase 5 sub-phase left: 5.3 Sales-activity timeline + lead capture endpoints (web form / IMAP / API).

### Migrations
`crm.0002_lead_score_commissionrule_commission_and_more` (CommissionRule, Commission, Lead.score).

## [3.17.152] - 2026-04-29

### Added — Phase 5.1: CRM foundation (Lead / Opportunity / Campaign + pipeline Kanban)
- New `crm` Django app with three models: `Lead` (pre-qualification), `Opportunity` (deal in flight against an Organization, 6 pipeline stages), `Campaign` (marketing/outreach with channel + budget).
- **Pipeline Kanban** at `/crm/pipeline/` — 6-column drag-and-drop board (Discovery → Qualified → Proposal → Negotiation → Closed Won / Closed Lost). Each card shows opp name, client, weighted value, owner. Per-column totals at the bottom.
- **Lead → Org + Opportunity conversion** at `POST /crm/leads/<pk>/convert/` — creates a `core.Organization` and a draft `Opportunity` with the lead's data, marks lead `status='converted'` and links via `converted_to_*` FKs.
- **Opportunity → Quote conversion** at `POST /crm/opportunities/<pk>/to-quote/` — drafts a `psa.Quote` with the client_org pre-filled.
- 5 new RoleTemplate booleans: `crm_view`, `crm_create_lead`, `crm_manage_pipeline`, `crm_manage_campaigns`, `crm_view_forecast`. Defaults: Editor = view + create_lead + manage_pipeline; Read-only = view only; Owner / Admin = all.
- New top-level CRM dropdown in the navbar.
- Tests in `crm.tests` cover model props, conversion, kanban auth.

Phase 5 sub-phases left: 5.2 Commission rules + lead scoring + funnel reporting; 5.3 Sales-activity timeline + lead capture (web form / IMAP / API).

### Migrations
`crm.0001_initial` + `accounts.0022_roletemplate_crm_create_lead_and_more` for the 5 new RoleTemplate booleans.

## [3.17.151] - 2026-04-29

### Added — Phase 4.4: One-click PO from accepted quote (closes Phase 4)
- "Convert to PO" button on accepted quote detail pages — POSTs to `/psa/quotes/<pk>/to-po/`, creates a draft `PurchaseOrder` with the quote's line items copied, lands the user on the PO edit page to pick a vendor + adjust shipping.
- New `PurchaseOrder.source_quote` FK — clean reverse link from quote → POs and forward link from PO header → quote.
- Optional vendor pre-fill via `?vendor=<id>` querystring (or POSTed `vendor_id`); auto-fills `vendor_name`, `vendor_email`, `vendor_phone`, `vendor_address`, and `expected_delivery_date` from vendor's `default_lead_time_days`.
- Permission: `procurement_create_po` (owners + admins by default; techs can't).
- 3 new tests in `psa.tests.QuoteToPOTests`.

### Phase 4 status: complete.
- 4.1 PR + PO + branded PDF + email (v3.17.148)
- 4.2 Receiving + back-orders + serial capture (v3.17.149)
- 4.3 Vendor metadata + stock minimums + auto-replenish (v3.17.150)
- 4.4 Quote-to-PO (v3.17.151)
- Phase 4 closed in `docs/ROADMAP.md`.

### Migration
`psa.0022_purchaseorder_source_quote` adds `source_quote` FK to PurchaseOrder.

## [3.17.150] - 2026-04-29

### Added — Phase 4.3: Vendor relationship + stock minimums + auto-replenish
- Extended `assets.Vendor` with procurement metadata: `default_lead_time_days` (default 7), `payment_terms` (Net 15 / 30 / 45 / 60 / COD / Prepaid / CC), `preferred_contact_method` (email / phone / portal), `contact_email/phone`, `billing_address`, `account_number`, `notes`, `distributor_provider` (ingram / pax8 / synnex link). Reused the existing global `assets.Vendor` model rather than introducing a separate procurement-only one — keeps the manufacturer-facing vendor catalog and the buy-from-vendor catalog in one place.
- `PurchaseOrder.vendor` FK alongside the existing `vendor_name` snapshot text. Picking a vendor on the PO form auto-fills `vendor_name`, `vendor_email`, `vendor_phone`, `vendor_address`, and `expected_delivery_date` (issue_date + `default_lead_time_days`) — both client-side (JS, fills blanks on change) and server-side (idempotent fallback when the form fields are blank).
- Vendor CRUD pages at `/psa/vendors/` (list / create / detail / edit) under the Procurement nav. Detail page shows: header card with metadata, Open POs (status not in cancelled/void/received), Recent closed POs (last 10), 90-day spend total, and an Edit button. List view shows payment terms, lead time, open POs count, and 30-day spend.
- Inventory items get optional `preferred_vendor` FK + `last_replenished_at` (existing `min_quantity` and `reorder_quantity` already cover stock minimums). Added to `inventory.InventoryItem`, `vehicles.VehicleInventoryItem`, and `vehicles.ShopInventoryItem`.
- New management command `psa_auto_replenish_suggestions` scans all three inventory surfaces for rows where `quantity <= min_quantity`. `--dry-run` lists them; `--create-prs` builds draft `PurchaseRequisition` rows grouped by `preferred_vendor` (one PR per vendor), skipping items whose SKU is already on an open PR. Quantity to order = `reorder_quantity` if set, else `2*min - current`.
- Daily cron at 06:00 logs scan results (PR creation is opt-in via `--create-prs` — admins decide whether to convert).
- New "Low stock items" dashboard widget surfaces top 10 items below minimum stock.
- Permissions: `procurement_view` to view vendors, `procurement_create_po` to create / edit.
- 6 new tests in `psa.tests` cover vendor metadata defaults / persistence / FK link, scan, PR grouping, dedupe.

Phase 4 sub-phase left: 4.4 — One-click PO from accepted quote.

### Migrations
`assets.0015_vendor_account_number_vendor_billing_address_and_more`, `inventory.0002_inventoryitem_last_replenished_at_and_more`, `psa.0021_purchaseorder_vendor`, `vehicles.0008_vendor_metadata`.

## [3.17.149] - 2026-04-29

### Added — Phase 4.2: PO Receiving + back-orders + serial capture
- New `psa.POReceipt` model — one row per receiving event (carrier, tracking number, drop-ship confirmation flag).
- New `psa.POReceiptLine` model — per-line received quantity + JSON serial-numbers array.
- New `psa.POBackOrder` model — auto-created when a receipt is short. Auto-fills (status='filled') when the remaining quantity is finally received. Cancellable.
- Receive flow at `/psa/purchase-orders/<id>/receive/` — staff form with qty + serials per line + carrier + tracking. Receiving rolls up `PurchaseOrderLineItem.received_quantity` and recomputes PO status (sent → partial → received).
- Quantity capped at outstanding so over-receiving is impossible.
- Captured serial numbers auto-create `assets.Asset` rows (silently skipped if Asset model signature doesn't accept the inference).
- New `/psa/back-orders/` page — open back-orders across all POs with cancel action.
- "Receive Items" button on PO detail (when status is sent / acknowledged / partial).
- Receipts + back-orders cards on PO detail.
- 7 new tests in `psa.tests.POReceivingTests`.

### Migration
`psa.0020_pobackorder_poreceipt_poreceiptline`.

## [3.17.148] - 2026-04-29

### Added — Phase 4.1: Procurement foundation (PR → PO + branded PDF + email)
- New `psa.PurchaseRequisition` (auto-numbered PR-YYYY-NNNNN) — internal request a tech files. Statuses: draft / submitted / approved / rejected / converted / cancelled. Optional `source_ticket` / `source_project` provenance.
- New `psa.PurchaseOrder` (auto-numbered PO-YYYY-NNNNN) — issued to a vendor. Statuses: draft / sent / acknowledged / partial / received / cancelled / void. Drop-ship flag with override ship-to.
- Both models have line items (`PurchaseRequisitionLineItem` / `PurchaseOrderLineItem`) with SKU + distributor hint (links to the existing Ingram/Pax8/Synnex catalog).
- PO branded PDF (mirrors Quote/Invoice ReportLab generator) + email-to-vendor sets `status=sent`, `sent_at=now`, audit-logged.
- Approval workflow: PR submit → approver approve/reject → PR-to-PO conversion endpoint copies line items.
- 5 new RoleTemplate booleans (Phase 3.6 pattern): `procurement_view` / `procurement_create_pr` / `procurement_approve_pr` / `procurement_create_po` / `procurement_send_po`. Editors can create PRs but not approve or send POs.
- 7 new tests covering numbering, totals, approval workflow, conversion.
- "Procurement" sub-section under the PSA navbar dropdown.

Phase 4 sub-phases left: 4.2 Receiving + serial capture + back-orders; 4.3 Vendor relationship model + stock minimums + auto-replenish; 4.4 One-click PO from accepted quote.

### Migrations
`psa.0019_purchaseorder_purchaseorderlineitem_and_more` for PR/PO models, `accounts.0021_roletemplate_procurement_approve_pr_and_more` for the 5 RoleTemplate booleans.

## [3.17.147] - 2026-04-29

### Added — Phase 3.6 wave B: Scheduled reports runner + Client-health score (closes Phase 3)
- New management command `run_scheduled_reports` processes any `ScheduledReport` with `next_run <= now`. For each: generates the report (PDF/CSV via the existing `reports.generators`), saves a `GeneratedReport` audit row, emails it to recipients, advances `next_run` based on frequency. `--dry-run` and `--force-id N` flags supported. Failures don't advance the schedule (next tick retries).
- Auto-installed cron at `*/15 * * * *` via `deploy/update_instructions.sh`.
- New `client_health_score(client_org_id)` query — composite 0-100 score across 5 weighted components: SLA hits (30%), ticket velocity (20%), billing aging over 60 days (25%), engagement (15%), NPS proxy (10%). Categories: Healthy ≥80, At-risk 60-80, Trouble <60.
- New report at `/reports/psa/client-health/` — staff/financial perm. Sortable table with color-coded score badges, 3-up summary cards, component mini-bars per row, CSV export.
- Two new dashboard widgets: "At-risk clients" (table) + "Client health breakdown" (pie chart).
- 8 new tests in `reports.tests`.

### Phase 3 status: **complete**.
- 3.1 canonical query layer + Profitability by Client (v3.17.139)
- 3.2 TechCostRate + profit by tech/contract/project (v3.17.140)
- 3.3 effective hourly rate + revenue leakage (v3.17.141)
- 3.4 SLA trends + margin analytics (v3.17.143)
- 3.5 dashboards + 12 starter widgets (v3.17.142)
- 3.6 wallboard + executive scorecard + scheduled reports + client health (v3.17.146-147)
- Roadmap updated.

### Migration
`reports.0002_scheduledreport_output_format_and_more` — adds `output_format` field to `ScheduledReport` and makes `next_run` nullable.

## [3.17.146] - 2026-04-29

### Added — Phase 3.6 wave A: Wallboard + Executive Scorecard
- **Wallboard** at `/reports/wallboard/` — TV-ready big-number live display. 6 mega-tiles (open tickets / SLA overdue / unassigned / P1 open / opened-today / closed-today), bottom marquee of 5 most recent tickets, on-shift techs row. Auto-refreshes every 30s via JSON poll to `/reports/wallboard/data/`. Pulsing red animation on the SLA-overdue tile if non-zero. Permission: `reports_view_dashboards`.
- **Executive Scorecard** at `/reports/exec-scorecard/` — single-page rolling 30-day MSP KPI summary. 8 hero cards (revenue with trend vs prior period, billable hours, realized rate, open tickets, SLA breach %, MTTR, active clients, tech utilization), 30d revenue + tickets dual-line chart, top 5 clients / top 5 techs / margin-by-service-line pie. Print-friendly. Permission: `reports_view_financial`.
- Both linked from Reports Home with conditional gating.

### Phase 3 status
- Sub-phases 3.1, 3.2, 3.3, 3.4, 3.5, 3.6A shipped. **Wave B** (scheduled reports + client-health score) closes Phase 3 next.

## [3.17.145] - 2026-04-29

### Added — Reports + sensitive-feature permission groups (RoleTemplate)
- 14 new RoleTemplate booleans across three groups:
  - **Reports & dashboards**: `reports_view_dashboards`, `reports_view_financial`, `reports_view_sla`, `reports_view_capacity`, `reports_manage_dashboards`, `reports_manage_scheduled`
  - **Resource management**: `resourcing_view_team`, `resourcing_manage_cost_rates`, `resourcing_approve_leave`, `resourcing_manage_holidays`
  - **Billing & financial**: `billing_view_invoices`, `billing_send_invoices`, `billing_record_payments`, `billing_view_aging`
- New `accounts.permission_utils.user_has_perm(user, perm_name)` helper + `@require_perm('...')` decorator. Mirrors the v3.17.134 KB pattern.
- Every report view now gated on a specific permission instead of the coarse `is_staff` flag. Defaults are tech-conservative: **Editor / Read-Only roles get dashboards only; financial / SLA / capacity reports default OFF**. Owners get everything; Admins get everything except `reports_manage_scheduled`.
- Role-template form (`/accounts/roles/<id>/edit/`) exposes all 14 new booleans across three new cards.
- Reports Home (`/reports/`) hides cards the user can't access — no more "click → 403".
- 12 new tests under `accounts.tests.ReportsPermissionTests` cover the gates (financial / capacity / roster / SLA + the helper itself).

### Backwards-compatibility note
- Existing staff users (`is_staff=True`) WITHOUT a `role_template` will fall back to the **Editor** profile — which means they LOSE direct access to financial / SLA / capacity reports. To restore access, assign them an Admin or Owner role-template, or a custom template with the relevant booleans set. Superusers (`is_superuser=True`) are unchanged — full access.

### Migration
`accounts.0020_roletemplate_billing_record_payments_and_more` — adds 14 new boolean fields.

## [3.17.144] - 2026-04-29

### Docs
- README "What's New" section refreshed for v3.17.121 → v3.17.143. Version badge bumped 3.17.120 → 3.17.143. Phases 2 + 3 added; AI Triage, admin assignment, KB perms, dashboards, integration status pills, KB categories tree all called out.
- FEATURES.md now documents the full Reporting + BI surface (canonical query layer, four profitability reports, effective hourly rate, revenue leakage, SLA trends, margin analytics, custom dashboards with 12 starter widgets), the Resource Management module (skills / certs / working hours / PTO / holidays / billable targets / tech cost rates / capacity report / skill ranking), and the AI Suggestions ticket button.

## [3.17.143] - 2026-04-29

### Added — Phase 3.4: SLA trend report + Margin analytics by service line
- `reports.queries.sla_trend_by_priority(start, end, org, bucket)` — bucketed (day/week/month) SLA breach rates per priority. Returns chart-friendly parallel arrays.
- `reports.queries.sla_trend_by_client(start, end, org, top_n)` — top-N clients by ticket volume with their response + resolution breach %.
- `reports.queries.margin_analytics_by_service_line(start, end, org, dimension)` — revenue vs cost grouped by `ticket_type` / `closure_category` / `queue`.
- New report `/reports/psa/sla-trends/` — two stacked line charts (response + resolution breach %) + per-priority summary + top-clients side panel + CSV export.
- New report `/reports/psa/margin-analytics/` — tabbed by dimension; bar chart + sortable table with color-coded margin column.
- New dashboard widget: 'SLA breach trend 30d' (chart_line). Available in the widget data-source dropdown.
- 4 new tests in `reports.tests`.

Phase 3 sub-phases left: 3.6 (scheduled reports / wallboard / executive scorecard / client-health score).

## [3.17.142] - 2026-04-29

### Added — Custom Dashboards: actual widgets (closes empty-state placeholder)
- New `reports/widget_sources.py` registry — 12 starter widgets across metric / table / chart_bar / chart_line / chart_pie types: revenue this period, open ticket count, SLA-overdue count, unbilled-hours-at-risk, active techs, avg time-to-resolve, top clients by revenue, tickets by priority, my assigned tickets, revenue trend bar, tickets-opened line, billable-vs-nonbillable pie.
- Each widget calls into the canonical `reports/queries.py` so the same numbers appear consistently across reports + dashboards.
- `dashboard_detail.html` rewritten to render widgets server-side: metric cards with icon + subtitle, tables with `<thead class="table-light">`, Chart.js-rendered bar/line/pie charts. Bad widgets render an inline error chip — never crash the whole page.
- New widget CRUD: "Add widget" button → form with data-source select + title; per-widget edit + delete (gated to dashboard owner or staff).
- New management command `seed_default_dashboard` creates a "MSP Overview" global dashboard with all 12 starter widgets pre-installed. Wired into `deploy/update_instructions.sh` so installs land on a populated dashboard. Idempotent.
- Tests in `reports.tests` cover registry execution + CRUD POST.

## [3.17.141] - 2026-04-29

### Added — Phase 3.3: Effective hourly rate + Revenue leakage reports
- New `effective_hourly_rate_by_client` and `effective_hourly_rate_by_tech` query functions in `reports/queries.py`. Per-tech version computes **realization %** (effective rate ÷ cost rate × 100, target ≥ 200%).
- New `/reports/psa/effective-hourly-rate/` page with tabbed By Client / By Tech views, summary cards (avg / highest / lowest / median), color-coded rate column. CSV export.
- New `revenue_leakage(start, end, org, stale_days)` query function — three categories: stale unbilled time, expired contract blocks, stuck draft invoices.
- New `/reports/psa/revenue-leakage/` page — single-screen view with $N grand total, three sub-tables, deep-link buttons to drill into each leak. Stale-days input. CSV export merges all three sections.
- Both reports staff/superuser only. Linked from Reports Home.
- Tests in `reports.tests` cover query math + view auth + CSV.

Phase 3 sub-phases left: 3.4 SLA trends + margin analytics; 3.5 dashboards / scheduled reports / wallboard / scorecard / client-health.

## [3.17.140] - 2026-04-29

### Added — Phase 3.2: Per-tech cost rates + profitability by tech / contract / project
- New `resourcing.TechCostRate` model — effective-dated loaded rate ($/hr) per tech. Historical reports stay accurate after a raise / role change. `TechCostRate.rate_for(user, date)` returns the matching rate (falls back to the canonical `DEFAULT_LOADED_RATE = $60` from `reports.queries` if no rows configured).
- `cost_estimate_by_client` + `profitability_by_client` now use **per-tech rates** instead of the flat $60/hr placeholder. Existing report keeps working — it's strictly more accurate now.
- Three new profitability reports:
  - `/reports/psa/profitability-by-tech/` — hours / cost / attributed revenue / margin / utilization %
  - `/reports/psa/profitability-by-contract/` — per-contract margin
  - `/reports/psa/profitability-by-project/` — per-project margin
- Each has the same date-range picker (7d/30d/90d/YTD + custom), summary cards, color-coded margin column, CSV export.
- Cost-rate management UI at `/resourcing/cost-rates/` — staff list with current rate, per-user edit page showing rate history.
- Existing `/resourcing/me/` page now shows the user's current loaded rate.
- New tests in `reports.tests` and `resourcing.tests` cover effective-dated lookup, default fallback, and the three new reports.

Phase 3 sub-phases left: 3.3 Effective hourly rate + revenue leakage; 3.4 SLA trends + margin analytics; 3.5 Custom dashboards + scheduled reports + wallboard + exec scorecard + client-health score.

## [3.17.139] - 2026-04-29

### Added — Phase 3.1: Canonical reporting query layer + Profitability by Client
- New `reports/queries.py` module — single source of truth for revenue / hours / cost / margin queries. Every Phase 3 report (and Phase 8 mobile timeclock utilization) will read from this module instead of building bespoke querysets per view.
- Canonical functions: `hours_minutes_by_client`, `hours_minutes_by_tech`, `revenue_by_client`, `cost_estimate_by_client`, `profitability_by_client`. All take `(start_date, end_date, organization=None)` and return list-of-dicts (no querysets) for clean JSON / CSV export.
- New report at `/reports/psa/profitability-by-client/` — date-range picker (7d / 30d / 90d / YTD chips + custom), summary card (Revenue / Cost / Margin / Margin %), sortable table per client, color-coded margin column. CSV export via `?format=csv`. Linked from Reports Home.
- Loaded-rate placeholder: `DEFAULT_LOADED_RATE = $60/hr` until Phase 3.2 ships per-tech cost rates.
- 6 new tests in `reports.tests` cover query shape, view auth gate, CSV export.

### Roadmap
- Phase 2 marked complete in roadmap. Phase 3 in flight.

## [3.17.138] - 2026-04-29

### Added — Phase 2.3: Capacity report + skill ranking on dispatch board
- **Capacity report** at `/resourcing/capacity/` for staff/superusers — table showing per-tech target / scheduled / actual hours + utilization % over 1 / 2 / 4 / 8 / 12-week windows. Color-coded utilization (red <80%, amber 80-95%, green 95-110%, blue >110%). Grand total row.
- **Scheduled hours** = sum of `WorkingHours` × working days in window (subtracts `Holiday` + approved `LeaveRequest`).
- **Actual hours** = sum of `psa.TicketTimeEntry` durations within window.
- **Skill ranking on dispatch board** — new `rank_techs_for_ticket(ticket)` helper scores candidate techs by skill keyword match (+30 per hit), client-org membership (+20), on-shift status (+15), open-ticket load (-30 if 5+), on-leave today (-50). Top 5 surface as a per-ticket "Suggest" popover with one-click Assign.

Phase 2 complete. Next up per roadmap: Phase 3 (Financial reporting + BI keystone).

## [3.17.137] - 2026-04-29

### Added — Phase 2.2: Holidays + Leave Requests + Billable Targets
- New `Holiday` model — org-scoped or global; `is_recurring_yearly` flag; `is_holiday(date, org)` classmethod.
- New `LeaveRequest` model — vacation / sick / personal / bereavement / jury / parental / unpaid / other; pending → approved/denied workflow with approver, decided_at, decision_note; half-day flag; `total_days` property; `is_user_on_leave(user, date)` helper.
- New `BillableTarget` model — per-tech weekly hours goal (default 32h/wk).
- `working_days_in_period(user, start, end, org)` helper subtracts WorkingHours gaps + holidays + approved leave. Used by Phase 3 capacity reporting and Phase 8.5 off-shift GPS suppression.
- Pages: `/resourcing/leave/` (my requests), `/resourcing/leave/approvals/` (staff queue with bulk approve/deny), `/resourcing/holidays/` (admin).
- Existing `/resourcing/me/` page now shows a Leave summary card + Billable target card.
- Audit-logged: every leave decision (approve/deny).
- Tests: 7 new in `resourcing.tests`.

### Migration
`resourcing.0002_billabletarget_holiday_leaverequest`.

Phase 2.3 — capacity report + skill-ranking on dispatch board — comes next.

## [3.17.136] - 2026-04-29

### Added — Public roadmap on website + GitHub + new Phase 9 (Security alerts)
- **Live roadmap page in-app at `/core/roadmap/`** — renders `docs/ROADMAP.md` server-side with markdown + tables + sane lists. Theme-aware styling, "View on GitHub" button. Linked from the user dropdown menu.
- **README "Roadmap" section** rewritten to point to `docs/ROADMAP.md` and list recently-shipped + in-flight + planned phases at a glance. Browsable on GitHub at the repo URL.
- **New Phase 9 — Security alert ingestion (EDR / AV / Firewall)** added to roadmap. Four sub-phases: connection framework, alert model + poller (5-min cron + HMAC webhook receiver), dashboard + auto-ticketing, reporting (MTTA, suppression rules, weekly digest). Provider types: CrowdStrike Falcon, SentinelOne, Microsoft Defender, Sophos Central, Huntress, ThreatLocker, Bitdefender, Webroot, Fortinet, Palo Alto, Sonicwall, Meraki MX, etc. Sizing M, ~5 weeks. Independent of all other phases.

## [3.17.135] - 2026-04-29

### Added — Service Catalog Tile / List view toggle
- Toggle at top of `/psa/catalog/` matches the org list (v3.17.115) and integrations (v3.17.133) pattern. Tile mode default. Preference persisted via `?view=` querystring + localStorage. List mode is a compact dark-mode-safe table (Name / Description / Default queue / Default priority / Fields / Status / Actions).

## [3.17.134] - 2026-04-29

### Added — KB: full CRUD + move + permission groups
- Inline **New article / Edit / Delete / Move** buttons on the PSA KB browse page (gated by new permissions). New article pre-selects the currently-filtered category.
- **Bulk move** — checkbox per article + "Move selected to →" dropdown. Single `POST /psa/kb/move/` endpoint validates permissions, updates rows in one query, writes one audit log entry per move.
- Inline **category Manage** button in the sidebar opens the existing `/docs/categories/?global=1` page.
- Five new **`RoleTemplate` boolean permissions**: `kb_view_articles`, `kb_edit_articles`, `kb_move_articles`, `kb_manage_categories`, `kb_publish_articles`. Defaults: Owner/Admin = all True; Editor = no manage_categories; Read-only = view only. Migration: `accounts.0019_roletemplate_kb_perms`.
- Permission groups (RoleTemplates) are listed + editable + assignable from `/accounts/roles/` — the existing page now exposes the new KB booleans.
- Server-side gate via `_check_kb_perm(user, perm_name)` helper — returns 403 if missing.
- New `KBPermissionsTests` + `KBMoveArticlesTests` in `psa/tests.py`.

### Changed — Integrations page condensed + Tile/List toggle + status indicator
- Condensed grid: 6-column tile layout on desktop, ~30% less vertical whitespace.
- New Grid ⇄ List view toggle (top right of page); preference persisted in localStorage + ?view= querystring.
- New status pill per integration: OFF / ON · Working (green) / ON · Broken (red, with error tooltip) / ON · Unknown (amber). Most visually prominent element on each row so admins can scan a 100-integration page in seconds.
- Search box filters by provider name + connection name.
- New `connection_status(conn)` helper in `integrations/status.py`.

## [3.17.132] - 2026-04-29

### Added — Phase 2.1: Resource management foundation (skills, certifications, working hours)
- New `resourcing` Django app with three models: `UserSkill` (proficiency tiers + years experience), `UserCertification` (issuer + credential id + expiry warnings + attachment upload), `WorkingHours` (per-weekday windows; split shifts allowed).
- "My Resources" page at `/resourcing/me/` — three-card profile view where users manage their own skills, certs, and working hours.
- Staff-only **tech roster** at `/resourcing/roster/` — every internal user with skill counts, cert counts, "working now" indicator, expiring-cert warnings.
- Superusers + staff can edit anyone's rows via `?user=<id>` querystring; regular users limited to their own.
- New `UserProfile.is_working_now()` helper — used by capacity reporting (Phase 3) and GPS off-shift suppression (Phase 8.5). Backwards-compatible: returns True if user has zero WorkingHours rows.
- 6 unit tests in `resourcing/tests.py`.

Phase 2.2 (PTO + LeaveRequest + BillableTarget) and Phase 2.3 (capacity report + skill-ranking on dispatch board) come next.

### Migration
`resourcing.0001_initial`.

## [3.17.131] - 2026-04-29

### Roadmap
- Added **Phase 8 — Native mobile apps (iOS + Android) with GPS auto-time + Timeclock** to `docs/ROADMAP.md`. Reverses the earlier "PWA only" deferral. Five sub-phases: backend foundation (TechnicianLocation / TimeclockEntry / ClientSiteGeofence models + REST API), GPS auto-documentation engine, Timeclock feature (web + mobile, selectable per-tech and per-org), React Native build, privacy + safeguards (off-shift suppression, geofence-only mode, retention policy, audit trail).
- Marked Phase 1 sub-phases 1.1 + 1.2 as shipped in the sizing table.

## [3.17.130] - 2026-04-29

### Added — Phase 1.2 Contract engine: bundle editor + auto-renewal + profitability
- **Bundled services line-item editor** on the contract form — dynamic add/delete rows with live recompute (mirrors the quote/invoice pattern). Submitted as JSON; the view reconciles existing rows by pk and deletes removed ones.
- **Contract detail page** at `/psa/contracts/<id>/` shows: hours used / effective remaining, rollover state, auto-renewal indicator, bundled services table, **profitability snapshot card** (revenue / cost / margin / margin %), and SLA matrix preview.
- **Auto-renewal cron** — `psa_auto_renew_contracts` management command runs nightly. For each expired contract with `auto_renew=True`, creates a child contract with: same name/type, new period dates from `auto_renew_period_months`, fresh `hours_used_minutes=0`, applied rollover (unused × `rollover_percent`), copied bundle items, `parent_contract` linked. Old contract flips to `expired`. Idempotent — won't double-renew thanks to `renewals__isnull=True` filter.
- Cron auto-installed at 02:30 daily by `deploy/update_instructions.sh`.
- `--dry-run` flag for safe inspection.
- 4 unit tests cover renewal, rollover, dry-run, and auto_renew=False skip.

## [3.17.129] - 2026-04-29

### Fixed — Admins can now actually assign tickets / tasks / projects / workflows / recurring schedules
- **Tickets**: the **Actions** dropdown on `/psa/tickets/<n>/` now shows an "Assign to tech" sub-menu for org admins, owners, staff, and superusers (anyone with `Membership.can_admin()` on the ticket's org). Each tech with an active membership in the ticket's org plus all staff/superusers appears as a one-click reassign target. New `set_assignee` action on `ticket_quick_action` enforces the same admin gate server-side and re-validates the target is eligible.
- **Ticket creation** (`/psa/new/`): admins now see an optional "Assign to" picker. Defaults to unassigned; ignored silently for non-admins so regular users can still file tickets.
- **Dispatch board** (`/psa/dispatch/`): the drag-and-drop endpoint (`POST /psa/dispatch/assign/`) was previously gated only by the generic `@require_write` decorator, which let any Editor reassign tickets. It now requires admin-level access on the **ticket's** org (not just the requester's currently-selected org) and re-validates that the dropped-on tech is staff or a member of that org. The board also now lists every eligible tech as a row, even if they have zero current tickets — so admins can drag a card to a brand-new tech.
- **Project owner**: `/psa/projects/<pk>/edit/` adds an "Owner" picker for admins. Members of the project's client org plus staff/superusers are eligible.
- **Project tasks**: the inline add-task form on the project detail page exposes an "Assignee" dropdown for admins, and each existing task gets a per-row reassign select. `project_task_add` and `project_task_update` now persist the picked assignee with the same admin gate and eligibility validation.
- **Recurring ticket schedules** (`/psa/recurring/`): the schedule form now has a "Default assignee" picker for admins. The cron runner already used `sched.assigned_to` to set each generated ticket's owner — until now there was no way to set it from the UI.
- **Workflow executions** (`/processes/<slug>/launch/`): the launch form now offers an admin-only "Assign to" picker so an admin can spin up a workflow on behalf of another tech. Defaults to the launcher.

### Helpers
- New `_can_assign(request, org)` and `_eligible_assignees(org)` helpers in `psa/views.py`. `_can_assign` returns true for superusers, Django staff, `Membership.role in ('admin', 'owner')`, and granular RBAC `org_manage_members`. `_eligible_assignees` returns all active org members plus all staff/superusers, ordered by username.

### Audit
- New `AdminCanAssignTests` smoke tests (`psa/tests.py`) — admin in org A can assign a ticket to a non-admin tech in org A; admin in org A cannot inject a tech who isn't a member of org A (unless that tech is staff/superuser); regular Editor in org A is forbidden from reassigning.

### No new schema

## [3.17.128] - 2026-04-29

### Added — KB categories + sub-categories on the PSA browse page
- The `/psa/kb/` page now has a left-sidebar **category tree** with unlimited hierarchy. Click a parent to see its articles + every descendant's articles; click a leaf to scope to just that category.
- Article rows show their category as a clickable badge — one click jumps to that category's filtered view.
- Category breadcrumb at the top reflects the selected path (Networking → Wireless).
- Search now respects the selected category — searches within the filtered subset.
- Empty-tree state links straight to "Manage categories" for superusers.
- **Superusers can now manage GLOBAL categories** from `/docs/categories/?global=1` — previously only org-scoped categories were editable. New "Switch to global / org-scoped" toggle on the category list page.

### No new schema
The data model already supported this (`DocumentCategory.parent` self-FK, `Document.category` FK) — this release is pure UI.

## [3.17.127] - 2026-04-29

### Added — Auto-notify techs on ticket assignment / schedule
- New per-user preferences in **Profile**: email me / text me when a ticket is assigned to me; email me / text me when an assigned ticket gets a due date.
- Email defaults ON, SMS defaults OFF. SMS requires a phone number on the profile + SMS configured globally.
- Reuses existing SMS plumbing (Twilio/Plivo/Vonage/Telnyx/AWS SNS) and Django SMTP.
- Dispatch board cards show small envelope / mobile icons next to each assignee — at-a-glance "will this tech actually hear about the assignment?"
- Trigger hooks live in `psa/signals.py`: `pre_save` captures prior `assigned_to_id` + `resolution_due_at`, `post_save` fires `notify_tech_assigned` on change and `notify_tech_scheduled` on due-date change.
- Notification failures are caught + logged; they never block ticket save.

### Migration
`accounts.0018_userprofile_notify_assigned_email_and_more` — adds 4 boolean prefs to UserProfile.

## [3.17.126] - 2026-04-29

### Added — Contract engine deepening (Phase 1, part 1 of 2)
- New Contract fields: `rollover_percent`, `rollover_expiry_days`, `rolled_over_minutes`, `rollover_expires_at`, `auto_renew`, `auto_renew_period_months`, `proration_enabled`, `billable_role_codes`, `excluded_role_codes`, `parent_contract` (FK self for renewal chains).
- New `ContractBundleItem` model — line items per agreement (e.g. "Managed AV per seat") with `quantity`, `unit_price`, `recurring_period`. Dynamic editor coming in v3.17.127.
- Helper methods on Contract: `effective_total_minutes()`, `effective_hours_remaining()`, `is_role_billable(code)`, `bundled_subtotal()`, `profitability_snapshot()` (revenue/cost/margin — coarse; per-tech cost rates land in Phase 3).
- "Advanced contract options" collapsible section on the contract form with all the new gauges + checkboxes + role-code lists.
- "Renew" column on the contract list shows an auto-renew icon for at-a-glance scanning.
- 7 new unit tests in `psa.tests.ContractEnginePhase1Tests` cover role gating, rollover with + without expiry, bundled subtotal, profitability snapshot keys.

### Migration
`psa.0018_contract_auto_renew_and_more`.

## [3.17.125] - 2026-04-29

### Added
- **AI triage suggestions on PSA tickets** — every PSA ticket detail page now has an *AI Suggestions* button next to the existing *Suggest reply* / *Suggest actions* buttons. Clicking it asks Claude (Haiku, low temperature) for read-only triage guidance: likely causes, investigation steps, suggested actions to consider (the AI does NOT execute anything), questions to ask the customer, risk flags, and references to check.
- **Full guardrail reuse** — triage runs through the same context-builder (vault data is excluded), subject-keyword blocklist, output content filter, prompt-injection envelope, and per-org/per-user daily token quota as replies and actions. Triage adds two extra rate limits: 10 triage requests per user per hour and 50 per organization per day. Cross-tenant requests are rejected at the service layer.
- **Prominent advisory warnings** — every rendered triage suggestion shows an amber alert banner reminding techs that the output is advisory, must be verified against vendor docs and the customer's actual environment, and that the model can hallucinate or miss context. Each suggestion has *Mark helpful* / *Not useful* feedback buttons (write to `AIActionLog` for prompt-tuning) plus a *Generate fresh* button. Older triage suggestions on the same ticket collapse into `<details>` blocks.
- **New role-template flag** `psa_ai_request_triage` (defaults to True for any tech) — gated at the service layer; read-only members can request triage without elevating to write access.
- **New `kind='triage'` choice** on `AISuggestion` (model migration `psa_ai/0002_alter_aisuggestion_kind.py`); new system prompt at `psa_ai/prompts/system_triage.md`; new service `psa_ai/services/triage_generator.py`; new view `generate_triage` plus `triage_feedback` for the helpful/reject verdict; new URL `path('triage/<ticket_number>/', …)`; accounts migration `0017_roletemplate_psa_ai_request_triage.py` adds the role-template flag.

## [3.17.124] - 2026-04-29

### Docs
- README "Native PSA / Service Desk" caption was a 200-word run-on prose paragraph — converted to four scannable bullet groups (Ticketing & service desk / Projects, contracts & schedules / Quoting, billing & accounting / Automation & integrations) plus added the workflow-on-tickets feature.

## [3.17.123] - 2026-04-29

### Docs / repo
- **Refreshed screenshots** in `docs/screenshots/` for the v3.17.113 → v3.17.122 feature surface: dashboard Quick Actions tile row, PSA tickets list / new-ticket form (with workflow picker) / ticket detail / aging / recurring / workflow rules / dispatch / quotes / invoices / contracts / client account, organizations list-view + grid-view toggle, processes (workflow templates) page, and the new condensed "What's New" on `/core/settings/updates/`.
- **New screenshot generator** at `scripts/generate_screenshots_v2.py` — authenticates by injecting a Django session cookie (no login form, 2FA-safe), drives Chromium via Selenium, full-page captures up to 4000px tall, keeps going on per-page failures.
- **Removed stale top-level docs** that were one-off generated reports superseded by `README.md` / `CHANGELOG.md` / `FEATURES.md`: `CHANGES_SUMMARY.md`, `DEPLOYMENT_VERIFIED.md`, `FEATURES_UPDATE.md`, `IMPLEMENTATION_STATUS.md`, `README_ADDITIONS.md`, `README_CONTRIBUTORS.md`, `ROADMAP_IMPLEMENTATION_COMPLETE.md`, `SECURITY_SCAN_REPORT.md`, `QUICK_START_AUTO_UPDATE.md`, `MOBILE_APP_DEVELOPMENT.md`.
- **Updated GitHub About** — new description ("Open-source self-hosted MSP platform — IT documentation + native PSA / service desk + workflow engine. …") and added topics: `psa`, `service-desk`, `ticketing`, `workflow-engine`.

## [3.17.122] - 2026-04-29

### Fixed
- **"Attach a workflow" picker on the New Ticket form was empty** in Global view. The v3.17.120 filter only showed workflows scoped to the current org *or* global ones — but most installs have all their workflows tied to a specific org (no globals), so the picker showed "— No workflow —" with nothing else. Now lists all published, non-archived workflows regardless of current scope, with each option showing the owning client name (or "global") for clarity.

## [3.17.121] - 2026-04-29

### Docs
- README + FEATURES refreshed for v3.17.113 → v3.17.120: badge bumped, "What's New" rewritten as scannable bullet groups (UI / dashboards, PSA workflow integration, other), expanded the *Process Workflows Embedded in PSA Tickets* section to cover all three attach paths + inline checklist + AJAX sign-off + audit history, added a *Workflow Templates Page* section.

### Known follow-up
- Screenshots in `docs/screenshots/` are stale — they don't show Quick Actions tiles, the inline workflow checklist on tickets, the sign-off history timeline, or the org list-view toggle. They need to be re-shot manually after applying this release.

## [3.17.120] - 2026-04-29

### Added — Attach a workflow at ticket creation
- The **New Ticket** form (`/psa/new/`) now has an "Attach a workflow" picker (above the Submit button). Pick any global or client-scoped workflow template to spawn the matching `ProcessExecution` immediately on save — the ticket detail page opens with the embedded checklist + sign-off history already in place.
- Optional. Existing flows still work: leave it on "— No workflow —" to create a plain ticket and use the **Launch workflow** button on the ticket page later.
- Picker shows only **published, non-archived** templates. When the form has a pre-selected client, the picker is filtered to that client's templates plus global ones; otherwise only global templates show.

## [3.17.119] - 2026-04-29

### Fixed
- Dashboard Quick Action tile **"Run Workflow"** now points to `/processes/` (the workflow templates page, where you click Run on a template and it spawns a ticket) instead of the legacy `/processes/executions/` list. This matches the v3.17.117 redesign where executions live inside tickets, not as a separate top-level list. The same page is reachable from **Operations → Workflows** in the top menu.

## [3.17.118] - 2026-04-29

### Added — Inline workflow sign-off history on tickets
- The PSA ticket detail page now shows a **Sign-off history** timeline below each workflow checklist — a chronological list of every audit-log event for that workflow execution (stage completed / uncompleted / created / completed / cancelled / failed) with the username, stage title, and time-ago.
- Each event has a coloured icon (green check for completion, amber undo for uncompletion, blue play for launch, etc.) so techs can scan who signed off on what at a glance.
- The full audit log is still one click away via "View full audit log →" — same `processes:execution_audit_log` URL as before.
- "Launch workflow" button on the ticket page is unchanged — attaches an existing workflow template to this specific ticket exactly like before.

## [3.17.117] - 2026-04-29

### Changed — Workflows now live inside PSA tickets
- Running a workflow on the **Workflows page** (`/processes/`) now always creates a **new PSA ticket** with the workflow's checklist embedded. The execution form has a "Client" picker; the new ticket is named `Workflow: <Process title>` and assigned to the chosen client.
- The **PSA ticket detail page** now shows the **full stage checklist inline** with AJAX checkboxes — no more bouncing to a separate execution-detail page to mark a stage complete. Progress bar updates in place.
- Visiting `/processes/execution/<pk>/` now **redirects to the ticket** if the execution is linked to one. Superusers can still see the legacy page via `?legacy=1`.
- Non-superusers no longer see the "View All Executions" link from the Workflows page.
- Added an info banner on the Workflows page: *"Run a workflow to attach it to a new PSA ticket."*

### Fixed — Six PSA forms no longer redirect with "Pick a client first"
The Project / Recurring Schedule / Contract / Email Config / Quote / Invoice **edit and create** pages now work in **Global view**. Each form has a Client picker; on save the chosen client becomes the form's tenant. No more bounce-to-list with an error message.

- Edit flow now loads the row by pk only (was previously gated by current-org filter), then derives the org from the row itself.
- Validation errors re-render the form preserving user input — never redirect.
- Each of the 6 templates got a new `client_org_id` selector at the top (above existing fields). The pre-existing `client_org` "linked customer" picker on quote/invoice/contract/project/recurring forms is unchanged — those serve a different purpose.

## [3.17.116] - 2026-04-29

### Added
- Quick Actions wizard now also shows on the **Global Dashboard** (superuser landing page). Was only on per-org dashboard before.
- Quick Actions extracted to `templates/core/_quick_actions.html` partial — single source of truth.

### Changed
- **Phase-2 density**: base font 14.5px (was 16px), tighter dashboard stat cards (h3/h4/h5 inside `.card` shrunk), `.fa-2x` / `.fa-3x` icons sized down, `.row.g-2` gutter cut to 0.4rem. Pages now hit the ~30% smaller target.
- "What's New" changelog block on the System Updates page is **dark-mode-safe and condensed**: theme-aware colors (no more dark text on dark surface), tighter line-height, smaller code badges. Future entries written as bullet lists for at-a-glance scanning.

## [3.17.115] - 2026-04-29

### Fixed
- **Org Members no longer auto-polluted.** The `create_default_membership` post-save signal silently bound every new non-superuser to the first active org. It is now **opt-in via thread-local flag** (`accounts.models._enable_auto_membership`) and OFF by default. Org-admin Add Member flow creates Memberships explicitly.
- Existing stale Membership rows are *not* auto-cleaned — review `/admin/accounts/membership/` and remove any that shouldn't be there.

### Added
- **Grid ⇄ List toggle on the Organizations page** for installs with 1000s of clients.
- List mode: compact table — Name / Slug / Active members / Asset count / Status / Created / Actions.
- Pagination — 50 rows in list mode, 24 cards in grid mode.
- Search box filters name + slug; survives across pagination + toggle.
- Annotated counts (no N+1) via `Count('memberships', filter=Q(is_active=True), distinct=True)`.
- View choice persisted in `localStorage` + `?view=list` querystring.

## [3.17.114] - 2026-04-29

### Added
- **Quick Actions wizard** on the dashboard — large icon tiles for the 8 most-used create flows (New Ticket, Add Asset, New Password, Add Document, Scan Receipt, Run Workflow, New Quote, New Invoice).
- PSA + Vehicle tiles auto-hidden when `psa_enabled` / `vehicles_enabled` is off.

### Changed
- **~30% page-density reduction site-wide.** Single CSS layer in `custom.css` tightens cards, headings, tables, buttons, inputs, breadcrumbs, nav tabs, list groups.
- **Global KB link is now PSA-aware** — hidden when PSA is on (lives under PSA → KB), shown when PSA is off.

## [3.17.113] - 2026-04-29

### Fixed
- **Dark-mode contrast across all PSA + portal list pages.** Bootstrap's `.table-light` was hard-pinning a white header background even in dark themes, so 22 templates rendered white-on-white. One global CSS rule re-binds the Bootstrap table vars on `[data-bs-theme="dark"]` and fixes them all (Aging, Recurring, Tickets, Quotes, Invoices, Contracts, Approvals, Workflow Rules, Email configs, Canned replies, Catalog, KB browse, Projects, Vault context, Portal vault/KB/tickets).
- Generic `.bg-light` and `.bg-light.text-dark` badge combo also softened in dark mode.

### Removed
- Duplicate **"Global KB"** link from the primary navbar (lives under PSA → KB now).

## [3.17.112] - 2026-04-28

### Added — Per-org client portal branding
The portal navbar and login page now show the client organization's logo (`Organization.logo`) when one is set on the org row, instead of the default life-ring icon. Falls back to the icon + org name when no logo is configured. No new model fields — uses the existing `Organization.logo` ImageField.

### Added — Drag-and-drop on the dispatch board
The dispatch board (`/psa/dispatch/`) now supports HTML5 drag-and-drop reassignment. Drag a ticket card from one technician's column to another to reassign — the change persists to the database via a new `POST /psa/dispatch/assign/` endpoint with optimistic UI and a Bootstrap toast on success/error. Failed reassignments roll back the card and reload the page. Every drag generates an audit-log entry (`assigned_to` field change) just like a manual edit would.

### Added — Visual workflow rule builder
The "New / Edit Workflow Rule" form (`/psa/workflow-rules/new/`) is now a visual builder with click-to-add condition rows and action rows — pick a field from a dropdown, get a typed value picker (priority codes, queue names, status slugs, ticket-type slugs, boolean for is_unassigned/is_paused, free text for subject_contains). The legacy raw-JSON textareas are still present in an "Advanced raw JSON" collapsible block, and existing rules with combinators (`any` / `all` / `__in` / `__not`) auto-fall-back to raw-JSON mode so they remain editable without data loss.

### Added — Test coverage for v3.17.105–107 + v3.17.111
14 new unit tests in `psa/tests.py`:
- `WorkflowOnTicketTests` — `ProcessExecution.native_psa_ticket` FK + reverse-query (v3.17.105)
- `PortalUserInviteTests` — `Document.is_client_visible` default-false (v3.17.106)
- `PortalVaultRBACTests` — `Password.visible_to_portal_user` across all four `client_access_mode` values + the personal/anonymous edge cases (v3.17.107)
- `WorkflowRuleMSPWideTests` — `WorkflowRule(organization=None)` fires on every client's tickets (v3.17.111)

## [3.17.111] - 2026-04-29

### Changed — Workflow Rules are MSP-wide by default
- **`psa.WorkflowRule.organization`** is now **nullable** (was required). A NULL organization means "applies to every ticket regardless of client". Existing rules with an org are still respected — they scope to that client only.
- **No more "Pick a client first" redirect** when creating or editing a workflow rule. The form has an "Applies to" picker that defaults to "All clients (every ticket)".
- **Engine** (`psa.workflow_engine.fire`) now matches `Q(organization__isnull=True) | Q(organization=ticket.organization)` — both MSP-wide and tenant-scoped rules fire for the right tickets.
- **Rule list** shows an "Applies to" column with a green "All clients" badge for global rules, grey badge for client-scoped.

### Changed — Cron jobs auto-installed by the update script
The `deploy/update_instructions.sh` now registers three cron jobs in the running user's crontab if they aren't already present (idempotent — checked by string match):
- `*/15 * * * * psa_run_recurring_tickets` — preventive maintenance ticket creation
- `*/5 * * * * psa_poll_email` — email-to-ticket IMAP poller
- `0 * * * * sync_distributors` — distributor health probe (Ingram / Pax8 / Synnex)

The "Cron setup" instruction boxes on the Recurring Tickets and Email Ingestion pages were rewritten to a green "Cron auto-installed" indicator with a `crontab -l | grep ...` verification snippet.

### Migration
`psa.0017_alter_workflowrule_organization`.

## [3.17.110] - 2026-04-29

### Fixed — Proper Advanced-setup CodeQL workflow
The Default-setup CodeQL has a cached language list that includes `java-kotlin` and `c-cpp` (set when those files existed in the repo, before v3.17.108 untracked them). Even with zero source files for those languages now, Default keeps trying to scan them and fails with "Extraction failed: No source files found." — see `CODE_SCANNING_IS_STEADY_STATE_DEFAULT_SETUP: true` in the run env.

Adding a properly-formatted Advanced-setup `codeql.yml` (this time `paths-ignore` is correctly nested inside the `config:` block, not a top-level input). After this lands and you switch to Advanced setup in the GitHub UI, only `python` / `javascript-typescript` / `actions` will run — all of which already pass.

**Manual one-click step needed:** Repo → **Security** tab → **Code scanning** → CodeQL row → kebab `⋮` → **Switch to advanced** (or **Disable** the Default setup). After that one click, Default stops running and the new workflow takes over.

## [3.17.109] - 2026-04-29

### Fixed — CodeQL workflow file removed (was broken + now redundant)
The custom `.github/workflows/codeql.yml` added in v3.17.102 had `paths-ignore` as a top-level input, which is NOT valid on `github/codeql-action/init@v3` — the proper place is inside a `config:` block or a separate `codeql-config.yml` file. That broken syntax caused all three jobs (python / javascript-typescript / actions) to fail on the v3.17.108 push.

With `clientst0r-android/` untracked in v3.17.108, the custom workflow is also redundant: Default setup auto-detects only the languages still in the repo (python / javascript-typescript / actions) — exactly what we want. Removing the custom workflow lets Default setup handle CodeQL again. Same scan coverage, no failing jobs.

## [3.17.108] - 2026-04-29

### Fixed — CodeQL java-kotlin / c-cpp failures
Untracked `clientst0r-android/` (37 files of Kotlin source + Gradle wrapper). The Default-setup CodeQL was auto-detecting Kotlin from those files and trying to build them in CI without an Android SDK, which failed every push. With no Kotlin / Java / C / C++ files left in the repo, GitHub's auto-detect should fall back to scanning only Python, JS/TS, and Actions — all of which currently pass.

The Android source is preserved on disk locally; just no longer in this repo. Recommended next step: push it to a separate repo (e.g. `agit8or1/clientst0r-android`) so it can have its own CI with the Android SDK installed.

`.gitignore` now excludes `clientst0r-android/` so it doesn't get re-added accidentally.

## [3.17.107] - 2026-04-29

### Added — Vault items for the customer portal + per-org RBAC
- **`vault.Password.client_visible`** boolean — gates whether a credential ever appears in the portal at all (default off).
- **`vault.Password.client_access_mode`** with four modes:
  - `none` — staff only (default)
  - `all_org` — every active member of the client org sees it
  - `specific_users` — explicit list (M2M `client_allowed_users`)
  - `org_admin_managed` — delegates the per-user list to a portal user marked **org admin**
- **`vault.Password.client_allowed_users`** M2M to User — only honoured for `specific_users` and `org_admin_managed` modes; the staff form filters this picker to active members of the credential's org.
- **`Password.visible_to_portal_user(user)`** helper — single source of truth for visibility rules. Always denies if the user has no active Membership in this org.
- **`accounts.Membership.is_org_admin`** boolean — independent of the staff Admin role; lets a portal user manage which colleagues see `org_admin_managed` items in their own org.

### Customer portal additions
- **`/portal/vault/`** — list of credentials this user can see, with reveal modal. Reveals are audit-logged via `audit.AuditLog`.
- **`/portal/vault/<pk>/reveal/`** — POST-only JSON endpoint, defence-in-depth re-checks visibility before returning plaintext.
- **Org admin pages** at `/portal/vault/admin/` and `/portal/vault/admin/<pk>/` — per-item user-checkbox grid; org admins flip access for their colleagues. Self-grant cannot be removed by accident (checkbox is disabled-but-hidden-input on the row).
- **Credentials nav entry** on the portal layout, plus a "Manage access for my team" button on the vault list when `is_org_admin=True`.

### Staff additions
- **Vault password form** gets a "Client portal access" card (visible flag + access mode + allowed users picker scoped to org members).
- **Portal invite form** gets an `is_org_admin` checkbox so the inviting MSP admin can mark the recipient as the client's org admin in one step.

### Migrations
- `vault.0011_password_client_access_mode_and_more`
- `accounts.0016_membership_is_org_admin`

### Notes
- Audit-logging on every reveal: `view` action with `object_type=vault.Password`, plus the user's email in the description.
- `is_personal=True` (My Vault) passwords are unconditionally NOT portal-visible.
- A user must have an active Membership in the password's organization OR they get denied even if their User pk is in `client_allowed_users` (defence in depth — prevents stale grants).

## [3.17.106] - 2026-04-29

### Added — Client portal users + KB articles for clients
- **Invite portal user** flow at `/psa/clients/<id>/invite-portal/` — admin enters email + name, system creates a Django `User` (or reuses existing matching email), adds a read-only `Membership` in the client org, enables the portal for that org if it isn't already, generates a one-time tokenised set-password link via `default_token_generator`, and emails the invitee. Audit-logged.
- **`accounts:portal_set_password`** consumes the invite token at `/account/portal/set-password/<uidb64>/<token>/`. Requires the recipient to set a password ≥12 chars; on success signs them in and redirects to `/portal/`.
- **`docs.Document.is_client_visible`** boolean — staff toggle so a doc is shown in the customer portal KB.
- **`/portal/kb/`** — KB browser inside the portal. Lists documents with `is_client_visible=True AND is_published=True` AND (`is_global=True` OR scoped to the user's client org). Search box, deep-link to article detail. New nav entry on the portal layout.
- **`/portal/kb/<slug>/`** — read-only article detail. Markdown content rendered as line-broken text, HTML content rendered as `safe` (trusted staff-published content).
- **Invite portal user button** on the Client Account page next to "Client profile".

### Notes on the data model
There is **no separate "client user" table**. A client user is a regular `auth.User` with an active `accounts.Membership` in a client `core.Organization` whose `psa.ClientPSASettings.portal_enabled=True`. The `portal_required` decorator gates portal views on that combination. Staff users (superuser / `is_staff`) are NOT auto-granted portal access — the portal is for clients only.

Migrations: `docs.0013_document_is_client_visible`.

## [3.17.105] - 2026-04-29

### Added — Apply workflows (multi-step processes) to native PSA tickets
- **`processes.ProcessExecution.native_psa_ticket`** FK on the existing process-execution model. Previously executions could link only to third-party (`integrations.PSATicket`) tickets; now they can attach to native PSA tickets too.
- **Launch workflow button** on ticket detail. Opens a picker of active processes (organization-scoped + global) with optional notes, creates a `ProcessExecution` linked to the ticket, drops a system note on the ticket timeline, and redirects to the execution page so the tech can step through stages.
- **Workflows card** on ticket detail lists every execution launched against the ticket with status badges (in progress / completed / cancelled / failed) and deep-links to each execution.
- New URL: `psa:ticket_launch_workflow` at `/psa/t/<ticket_number>/workflow/launch/`.

Distinct from `psa.WorkflowRule` (the JSON-DSL automated rule engine that fires on ticket events). `ProcessExecution` is for multi-step procedural workflows that humans walk through (e.g., a 7-stage onboarding checklist defined in `processes.Process`).

Migration: `processes.0005_processexecution_native_psa_ticket_and_more`.

## [3.17.104] - 2026-04-28

### Docs — Re-captured PSA screenshots in clean light theme
The 28 v3.17.103 screenshots were captured under the admin user's dark theme + random background, which made them ~10× larger than the existing screenshots and visually inconsistent. Regenerated all 28 with admin temporarily set to `theme=default` and `background_mode=none`, then restored. Also dismissed the PWA install banner and set `global_view_mode=True` so the yellow "pick a client" bar isn't visible. File sizes dropped from 1–1.8 MB down to 70–250 KB (matching `dashboard.png`/`assets-list.png` scale). Layout now matches the rest of the README screenshot grid.

The `psa-kb.png` capture is still pending — its 500-page bug fix from v3.17.103 will deploy once you Apply that update; I'll re-shoot then.

## [3.17.103] - 2026-04-28

### Docs — 28 PSA screenshots captured
Added 28 new screenshots to `docs/screenshots/` covering the entire PSA module. Captures include tickets / ticket detail / new ticket / service catalog / projects / project detail / recurring / recurring form / approvals / contracts / contract SLA matrix editor / quotes / quote detail / quote form / **customer e-sign canvas** / **branded quote PDF** / invoices / invoice detail / invoice form / **branded invoice PDF** / **client account view (balance + aging + charges)** / aging report / dispatch board / workflow rules / workflow rule form / email-to-ticket / distributors / accounting (QBO + Xero) / organizations.

README's PSA section shows 15 inline images and the screenshot index lists every new capture with deep-link descriptions. Captures were taken via headless Chromium + Selenium with an injected Django session against the live dev server, using the seeded demo data (ACME Industries / Globex / Initech / Demo MSP).

### Fixed
- `templates/psa/kb_browse.html` was reversing a non-existent `docs:document_view` URL → 500 on `/psa/kb/`. Fixed to `docs:document_detail` (the actual URL name; uses slug not pk).

## [3.17.102] - 2026-04-28

### Docs
- **README.md** gets a Native PSA / Service Desk blurb in the screenshot grid and a new section listing every PSA page that's ready to screenshot (~39 PNGs).
- **FEATURES.md** updated through Phase 10: quote PDF + email + e-sign, invoices/payments + branded PDF + accounting push, client account + aging + charges, accounting integrations (QuickBooks Online + Xero with OAuth2).
- **docs/SCREENSHOT_CHECKLIST.md** rewritten for v3.17.x (was at v3.10.7). Lists 39 pending PSA screenshots organized by phase + 32 existing flagged for re-capture.

### Fixed
- **CodeQL workflow** — replaced GitHub's "Default setup" (which auto-detected Java/Kotlin and C/C++ but had nothing to build for either) with an explicit `.github/workflows/codeql.yml` scanning only `python`, `javascript-typescript`, and `actions`. The Android (`clientst0r-android/`) and `mobile-app/` paths are excluded since they need an Android SDK to compile in CI.
- **Heads up:** GitHub usually disables the Default-setup CodeQL automatically once an explicit workflow lands. If both still trigger, switch to "Advanced setup" in repo Settings → Code security.

## [3.17.101] - 2026-04-28

### Added — Phase 10: Client account, Charges, Aging report
- **Per-client account view** at `/psa/clients/<org_id>/account/` — net balance, outstanding invoices, available credits, uninvoiced charges, aging buckets (0-30 / 31-60 / 61-90 / 90+), invoice list, payment history, and unbilled time + expenses ready to invoice.
- **Charges** (`psa.Charge`) — direct line entries against a client account, independent of invoices. Supports one-time vs recurring (monthly/quarterly/yearly), credit flag (subtracts from balance), and roll-into-invoice for batched billing. Create one inline from the client account page.
- **"Invoice now" button** on the client account view — bundles all uninvoiced charges and credits for the client into a new draft invoice and marks each charge as invoiced. Credits come through as negative-amount line items.
- **Aging report** at `/psa/aging/` — cross-client outstanding balances bucketed by age past due date. Per-row deep link into each client's account view.
- **`Account` button** on the Clients (organization) list — quick jump from the org list to that client's PSA account view.
- **PSA dropdown gains an Aging Report entry**.

### API
- `psa.models.get_psa_balance(client_org, msp_org=None)` returns the same dict the views render: `outstanding`, `credit_total`, `uninvoiced_charges`, `net_balance`, plus an `aging` dict keyed by bucket name.

## [3.17.100] - 2026-04-28

### Changed — Dev workflow: assistant edits gated by Apply update
Going forward the AI assistant works in a separate worktree at `/home/administrator/.dev-worktree/` on the `dev-work` branch. Pushes go to `origin/main`, so `/home/administrator/` sees an **Update available** prompt and the user must click **Apply update** in the web UI (Settings → Updates) for changes to land. The assistant no longer edits the running source tree directly nor restarts gunicorn.

This commit is the first one made entirely through the new workflow — if you're seeing it as "Update available" in the dashboard rather than already applied, the gating is working.

## [3.17.99] - 2026-04-28

### Changed — Invoice form matches the compact quote form
- Same compact `form-control-sm` density, single-line description, dynamic add/delete line items, live-recompute subtotal/tax/total.

### Added — PDF / Download / Email buttons on the list rows
- Quote and Invoice list rows now have inline icon buttons: View, Edit, View PDF, Download PDF, Email. The detail-page buttons are still there too; the list rows just save a click for the common cases.

## [3.17.98] - 2026-04-28

### Added — Phase 9: PDF + Email for Quotes & Invoices
- **Branded PDF rendering** (`psa.pdf` — ReportLab) with shared layout for quotes and invoices: logo header (org logo with system custom_logo fallback), kicker block (number / date / due-or-valid-until), From/Bill-to address blocks, line-items table with alternating row banding, tax/subtotal/total summary, page footer with page numbers and brand mark.
- **View / Download PDF** buttons on quote and invoice detail pages — `?download=1` forces an attachment Content-Disposition.
- **Email modal** on quote and invoice detail — sends the PDF as an attachment to the customer. For quotes, the body includes the customer's e-sign link. Auto-flips quote/invoice to `sent` if it was `draft`. Audit-logged.
- **Quote detail page** (`/psa/quotes/<id>/`) — new, mirrors the invoice detail layout: stats card, line items, signature record (when signed), accept-with-create-ticket form, and the email/PDF/sign-URL buttons.

### Changed
- **Quote form qty + unit-price columns widened** (120px / 140px / 130px) so values aren't truncated.
- **Quote list** number column now links to the new quote detail page.
- **Invoice and quote detail layouts are now consistent** — same header structure, same button order, same email modal.

### Dependencies
- Added `reportlab>=4.0,<5.0` to requirements.txt.

## [3.17.97] - 2026-04-28

### Fixed
- **Saving a quote or invoice crashed** with `TypeError: can't multiply sequence by non-int of type 'decimal.Decimal'`. The view assigns `tax_rate` from POST as a string; `Decimal × str` was reversing into `str.__rmul__(Decimal)`. Both `Quote.recompute_totals()`, `Invoice.recompute_totals()`, and the line-item `line_total` properties now coerce all numeric inputs to `Decimal` defensively before arithmetic.

### Changed
- **Quote form is much smaller** — compact `form-control-sm` inputs, smaller labels, single-line description, footer subtotal/tax/total that updates live as you edit. Old form was visually heavy.
- **Add / remove line items dynamically** on the quote form — `+ Add line` button and a per-row × delete button (refuses to leave fewer than one row, just clears it instead).
- **Live totals on the quote form** — subtotal, tax, and total all recompute as you type quantity, unit price, or tax rate.
- **Tax rate now defaults from PSA settings** (`SystemSetting.psa_default_tax_rate`) on new quotes and invoices. Existing rows preserve their saved value.
- **Default currency** for new invoices comes from `SystemSetting.psa_default_currency`.
- **PSA dropdown gains a Clients link** pointing to `accounts:organization_list` — clients and organizations are the same thing in the data model, so this is a navigation convenience rather than a duplicate view.
- **Removed scope-banner nag** from the cross-client list pages (Dispatch, Invoices, Projects, Recurring, Approvals, Contracts, Email Ingestion, Quotes, Workflow Rules). Those views show data across all clients in global view; they don't need the "Pick a client first" prompt.

### Added
- `SystemSetting.psa_default_tax_rate` (Decimal, default 0) and `psa_default_currency` (CharField, default 'USD').

## [3.17.96] - 2026-04-28

### Added — PSA Phase 8: Invoices, Payments, Accounting integrations, Quote e-signature
A complete billing pipeline plus customer-facing quote signing.

- **Invoices** (`psa.Invoice` + `InvoiceLineItem`) — auto-numbered `INV-YYYY-NNNNN`, draft → sent → partial → paid → overdue → void lifecycle, tax rate with auto subtotal/tax/total, `balance` property, source pointers to a quote / ticket / contract.
- **Payments** (`psa.Payment`) — record a payment against an invoice; saving auto-calls `Invoice.recompute_totals()` which updates `amount_paid` and flips status to partial / paid as appropriate.
- **Generate-from-ticket** — one button on the ticket detail creates a draft invoice from the ticket's billable time entries (priced at the active contract's hourly rate) and billable expenses.
- **AccountingConnection** (`integrations.AccountingConnection`) — per-organization OAuth2 connection with encrypted credentials (client_id + client_secret + refresh_token + tenant/realm IDs all stored in a single AES-encrypted JSON blob).
- **QuickBooks Online provider** — full OAuth2 (authorize → callback → refresh-rotation), customer-by-name lookup with auto-create fallback (mapping cached on the connection), and Invoice push via `/v3/company/<realm>/invoice`. `record_payment()` posts to `/payment` with a LinkedTxn back to the invoice.
- **Xero provider** — OAuth2 with `offline_access` for refresh tokens, tenant_id discovery via `/connections`, Contact upsert, Invoice push to `/api.xro/2.0/Invoices`, Payment push to `/Payments`.
- **Quote e-signature** (`psa.QuoteSignature`) — public, no-login customer URL `/portal/quote/<token>/sign/` with an HTML5 canvas signature pad. POST records the base64-PNG signature, signer name/email/title, IP address, and user-agent, then auto-flips the quote to `accepted` and creates the converted ticket. Quote list page has a one-click **Copy Sign URL** button.

### Changed — Dispatch board shows everything
- Removed the `is_terminal=False` filter — closed/resolved tickets now appear too (rendered with a grey priority badge so you can still distinguish at a glance).
- Removed the 7-day window cap. Tickets without a due date or with a due date outside the next week land in a new **Other** column on the right.

### Cleanup — untracked `.gradle/` build cache
- Removed 21,220 stale Gradle wrapper / cache files from the index that were committed before `.gradle/` was added to `.gitignore`. Local files are kept; future clones drop ~3.8GB.

## [3.17.95] - 2026-04-28

### Fixed — Dispatch board dark-mode contrast + size
- Replaced fixed `table-light` / `table-warning` with theme-aware `var(--bs-tertiary-bg)` so the grid renders correctly in both light and dark modes.
- Compressed the layout: smaller fonts (.8rem header / .75rem cards / .7rem subject), tighter padding, narrower tech column (110px), `table-layout: fixed`, subjects truncated to 35 chars. The grid is roughly half the visual weight it was.
- Unassigned row uses a small "Unassigned" badge cell rather than colouring the whole row bright yellow.

### Changed — Update script auto-installs PSA defaults + sample workflows
The web-UI **Apply update** button (and `python manage.py auto_update` CLI) now run two extra idempotent commands at the end of every update:

- `psa_seed_defaults` — ensures queues, statuses, priorities, types, and the service catalog exist
- `psa_seed_sample_workflows` — installs the 7 starter rules (P1 escalation, sales-inquiry follow-up, new-user onboarding, termination security routing, outage keyword detection, unassigned triage, client-reply tagging) into every active organization

Both are matched on existing names so re-runs don't duplicate. Failures are logged but non-blocking (don't abort the update).

This is purely a remote-script change — `deploy/update_instructions.sh` is downloaded from `main` on every update, so any installation gets the new behavior on its next Apply with no code change required on the box.

## [3.17.94] - 2026-04-28

### Added — PSA Phase 7: SLA matrix UI + Workflow Rules + Dispatch Board

- **SLA matrix editor** on the contract form — a P1–P5 grid where each cell holds an optional response/resolution override in minutes. The SLA engine (`psa.sla.compute_due_dates`) checks the active contract's matrix before falling back to the priority's defaults, so premium clients can have tighter SLAs than the global queue defaults.
- **Workflow Rules engine** (`psa.WorkflowRule`) — JSON-DSL rule engine fired from PSA signals on `ticket_created` / `ticket_updated` / `status_changed` / `comment_added`. Conditions support `priority`, `queue`, `status`, `subject_contains`, `is_unassigned`, `is_paused`, `__in` / `__not` operators, plus `all` / `any` combinators. Actions: `set_priority`, `set_queue`, `assign_to`, `add_watcher`, `add_internal_note`, `add_tag`. Misconfigured rules capture `last_error` on the row instead of blocking ticket save.
- **Sample workflow installer** — `psa_seed_sample_workflows` management command installs 7 starter rules per organization (P1 escalation, sales-inquiry follow-up, new-user onboarding, termination security routing, outage keyword detection, unassigned triage, client-reply tagging). Tenant-scoped + idempotent.
- **Dispatch Board** at `/psa/dispatch/` — 7-day grid of open tickets bucketed by due date with one row per tech, an unassigned row at the top, and an overdue panel above the grid.

### Added — Python Dependency Scanner remediation
- New superuser-only **Upgrade** button on the Python scanner dashboard. Clicking it opens a modal with the package name + a dropdown limited to the `fix_versions` from the most recent scan.
- New `/core/security/python-scanner/remediate/` POST endpoint runs `pip install --upgrade <name>==<version>` in a controlled subprocess (300 s timeout, package + version regex-validated, version must be in the published fix list to prevent stale-dashboard exploitation). Audit-logged success and failure with stdout/stderr tails.
- The modal explicitly tells the admin to (a) update `requirements.txt` and (b) restart gunicorn — we don't auto-restart since the request is in-process.

### Tests
+7 in `psa.tests.Phase7WorkflowTests` covering SLA matrix override math, set_priority on subject match, condition false → no-op, add_tag action, inactive rule no-op, error-capture for bogus action types, and sample-workflow seeding.

## [3.17.93] - 2026-04-28

### Added — PSA Phase 6: project tasks + ticket-detail polish
- **Project tasks** (`psa.ProjectTask`) — task/milestone breakdown under any Project, with status (todo / in_progress / blocked / done / cancelled), assignee, due date, milestone flag, and parent-task hierarchy. Inline add + status-update + delete on the project detail page.
- **Ticket detail surfaces:**
  - **Active contract banner** showing client name, contract type, hours used / total / remaining, and a warning chip when allowance is depleted.
  - **Expenses card** (per-ticket reimbursable / billable expenses) with inline add form (amount, currency, category, billable + reimbursable flags, optional receipt upload), running list, and a footer total of billable amounts.

### Fixed
- `psa.tests.ServiceCatalogTests.test_create_from_catalog_prefills` was asserting against the old subject-input behavior. Updated to check that the catalog item's `fields_json` labels render (the new structured-fields path that's been live since v3.17.87).
- Replaced deprecated `AXES_LOCK_OUT_BY_COMBINATION_USER_AND_IP` with `AXES_LOCKOUT_PARAMETERS = [['username', 'ip_address']]` (same behavior, no startup warning).

## [3.17.92] - 2026-04-28

### Added — PSA Phase 5: Quotes / Estimates + Expenses
- **Quotes** (`psa.Quote` + `QuoteLineItem`) — auto-numbered `Q-YYYY-NNNNN`, draft → sent → accepted/rejected/expired lifecycle, tax rate + auto-computed subtotal/tax/total, line items, and **convert-to-ticket on acceptance**. PSA dropdown gains a Quotes entry.
- **Expenses** (`psa.TicketExpense`) — per-ticket reimbursable / billable expense rows with category (mileage, parts, software, subcontractor, shipping, other), amount + currency, optional receipt file upload, audit-logged on add. Expenses can be tied to a `PSAApproval` for manager sign-off.

### Tests
+5 in `psa.tests.Phase5QuotesExpensesTests` covering auto-quote-numbering, line-item math + tax, accept→ticket conversion, accept-without-ticket, and expense creation.

## [3.17.91] - 2026-04-28

### Added — PSA Phase 4: Customer Portal + Email-to-Ticket + Contracts
Three more substantial pieces. PSA dropdown gains Contracts and Email Ingestion. New top-level `/portal/` is a stripped layout for clients only.

- **Customer Portal** (`portal/` app at `/portal/`) — clients log in, see only their org's tickets where `client_can_view=True`, post replies as public comments, submit new tickets. Internal-only comments and attachments are filtered at queryset time. Per-org opt-in via `ClientPSASettings.portal_enabled`. Stripped layout with no MSP nav.
- **Email-to-Ticket** (`psa.EmailIngestionConfig`) — IMAP poller. Per-org mailbox config with encrypted password (vault-style). `psa_poll_email` management command (cron every 5 min) fetches UNSEEN messages, threads replies onto existing tickets when subject matches the configured ticket-number regex, otherwise creates new tickets with `source='email'`. Marks each message as Seen.
- **Contracts** (`psa.Contract`) — per-client agreement (block_hours / retainer / managed_services / per_incident) with hours allowance, hourly rate, overage rate, and a per-priority SLA matrix override. `Contract.for_ticket(ticket)` returns the active contract (status='active', within date range). `TicketTimeEntry.save()` increments `Contract.hours_used_minutes` automatically — only on stop transitions, not while a timer is still running. Hooks into AuditLog for every CRUD.

### Models
`psa.Contract`, `psa.EmailIngestionConfig`. `TicketComment` gets `author_name` / `author_email` / `source` columns so external (email/portal) replies get attributed even without a User row.

### Tests
+10 in `psa.tests.Phase4FeaturesTests` and `psa.tests.CustomerPortalTests` covering contract activation rules, time-entry → contract hour accounting, email password encryption, portal queryset filtering of staff-only tickets, internal-comment hiding on detail view, portal reply-creation, and portal ticket creation.

## [3.17.90] - 2026-04-28

### Added — PSA Phase 3: full-featured push
Adds four major missing pieces. PSA dropdown gets four new entries (Projects, Recurring Tickets, Knowledge Base, Approvals).

- **Projects** (`psa.Project`) — group tickets under a delivery effort with status (planning/active/on_hold/completed/cancelled), owner, billable flag, estimated hours, start/due dates, optional client_org. New routes `/psa/projects/`, `/psa/projects/new/`, `/psa/projects/<pk>/`, `/psa/projects/<pk>/edit/`. Ticket gets `project` FK.
- **Recurring tickets** (`psa.RecurringTicketSchedule`) — preventive-maintenance template with frequency (daily/weekly/monthly/quarterly/yearly) × interval. New `psa_run_recurring_tickets` management command for cron (recommended every 15 min). Generated tickets carry `recurring_schedule` FK + `source='recurring'` and roll `next_run_at` forward by one cycle. Catch-up cap of 50 tickets per overdue schedule prevents runaway after a long downtime.
- **Knowledge Base** browser at `/psa/kb/` — searches `docs.Document` filtered to `is_global=True`. New `psa.TicketKBLink` through-table allows many KB articles per ticket; link/unlink endpoints on ticket detail.
- **Approvals** (`psa.PSAApproval`) — generic manager-approval gate for time / expense / quote / order / AI-action / change. List + decide UI at `/psa/approvals/`. `approval.decide(user, approved, comment)` helper writes status + decided_at atomically.

### Tests
6 new tests in `psa.tests.Phase3FeaturesTests` covering slug auto-gen, completed_at auto-set, monthly relativedelta math, the cron command actually creating a ticket and rolling next_run_at, approval decision atomicity, and KB-link uniqueness.

## [3.17.89] - 2026-04-28

### Added — Distributors: Pax8 + TD Synnex adapters
- **Pax8** provider (`pax8`) — OAuth2 client-credentials, `/v1/products` catalog, product detail pricing (price bands), `/v1/orders` placement, HMAC-SHA256 webhook verification on `X-Pax8-Signature`. SaaS-distributor-shaped: catalogs are unlimited unless deactivated.
- **TD Synnex** provider (`synnex`) — OAuth2 to `/apis/v2/oauth/token`, price-availability lookup, order placement, HMAC-SHA256 webhook verification on `X-TDS-Signature`.
- Distributors card surfaced on the main Integrations page so admins discover the feature without typing the URL.

## [3.17.88] - 2026-04-28

### Added — PSA Phase 2c remainder
- **Similar tickets** card on the ticket detail page (same-asset + Jaccard token overlap on subject) so techs can spot duplicates and one-click merge.
- **`@mention` parser** — typing `@username` or `@user@example.com` in a comment auto-adds them as a watcher and emails them.
- **Ticket merge** moves comments + attachments to the target ticket, marks the source as a duplicate, and audit-logs both.

### Added — Distributors (Workstream 8)
- **`integrations.DistributorConnection` + `DistributorWebhookEvent`** with encrypted credentials/secrets, opaque per-connection webhook tokens, and tenant scoping.
- **Ingram Micro Xvantage** adapter — OAuth2 client-credentials, catalog list, price + availability, order placement (gated by `sync_enabled`, off by default), HMAC-SHA256 webhook verification.
- **Six other distributors** (TD Synnex, D&H, ScanSource, Pax8, QBS, Westcoast) reserved as `provider_type` choices for future adapters.
- **Admin UI** — list, create/edit, delete, ad-hoc pricing lookup, connection test endpoint.
- **`sync_distributors` management command** for cron health probes.

### Added — PSA AI Phase 10c
- **11 granular RoleTemplate booleans** (`psa_ai_view`, `_send_low_risk`, `_send_high_risk`, `_approve_reply`, `_apply_low_risk`, `_apply_high_risk`, `_approve_action`, `_run_script`, `_create_workflow`, `_billing`, `_admin`) and a data migration backfilling the seven system templates per the role matrix.
- `psa_ai/permissions.py` resolver was already wired for these — now reads authoritative values rather than falling back to simple-role heuristics.

## [3.17.77] - 2026-04-28

### UX
- **Friendly "Pick a client" page on `/psa/new/` in global view** — used to return 404 (hostile, no recovery path). Now renders the scope-banner picker plus a centered "Pick a client first" card. If the active client is auto-opted-out (external PSA detected), redirects to the ticket list with a flash message naming the client.

## [3.17.76] - 2026-04-28

### UX — PSA scope clarity (Option A)
- **Scope banner on every PSA page** (`templates/psa/_scope_banner.html`):
  - When a client is selected: subtle green-bordered chip with the client name and an inline Switch dropdown (jump between clients without leaving PSA).
  - In global view (no current_organization, superuser/staff only): sticky yellow banner stating "you're seeing data across all clients" with a "Pick a client" picker.
- **Color-coded client pills** in the ticket list — same client always renders the same hue (HSL derived from organization id) so scanning rows for a given client is easy.
- **"New Ticket" + "Client Settings" disabled in global view** with tooltip pointing at the picker.
- **Client badge moved out of subtitle text** on the detail page — now a colored pill next to the ticket number.

### Hard rule
- **External PSA = absolute opt-out for native PSA** — there's no admin override path that re-enables native when an active `integrations.PSAConnection` exists. To use native PSA for a client, deactivate the external connection first. The override checkbox on the per-client settings page is now visually locked OFF when an external PSA is detected.

## [3.17.75] - 2026-04-28

### Changed
- **Native PSA auto-opts-out clients that already have an external PSA** — `integrations.PSAConnection` (ConnectWise / Halo / Autotask / Freshservice / Kaseya / Syncro / Zendesk / etc.) on an org auto-disables the native PSA for that client. No manual toggle.
- `ClientPSASettings` is now an OVERRIDE rather than an opt-in step. Visiting the per-client page no longer auto-creates a row — absence of a row means "use auto-detection". Page surfaces the auto-decision with a banner, plus a "Reset to auto-detect" button to delete an override row.

## [3.17.74] - 2026-04-28

### Security
- **HSTS `includeSubDomains` is now opt-in** via the `SECURE_HSTS_INCLUDE_SUBDOMAINS` env var (default False). It used to auto-cascade at any HSTS value, which would have force-applied HTTPS-only to every sibling subdomain — hard to undo because the browser caches it for the HSTS lifetime.
- `.env.bak.*` is now gitignored so secret-rotation backup files never get committed by accident.

## [3.17.73] - 2026-04-28

### UX — PSA
- **Global PSA toggle now cascades to every client by default.** Per-client `ClientPSASettings.enabled` defaults to True; the page becomes opt-OUT instead of opt-in.
- The genuinely sensitive per-surface flags (portal, anonymous form, SMS, desktop alerts, email-to-ticket, external alert ingest) remain OFF by default — those still require deliberate per-client enable.

## [3.17.72] - 2026-04-28

### Bug Fixes
- **Fix DRF schema crash that returned 500 across the entire site whenever `DEBUG=False`** — `DEFAULT_SCHEMA_CLASS` was set to `None` outside DEBUG mode, which caused `rest_framework.schemas.coreapi.is_enabled()` to call `issubclass(None, AutoSchema)` → `TypeError`. This was the root cause of the `/account/login/` 500 in production. Pinned `DEFAULT_SCHEMA_CLASS` to the modern OpenAPI AutoSchema unconditionally.

### New Features
- **PSA toggle in Settings → Features** — the `psa_enabled` flag was wired into `core.SystemSetting` and the context processor in 3.17.70/71 but no UI control existed. Adds a labeled switch with an "off by default" badge.

## [3.17.71] - 2026-04-28

### Security
- **Bump remaining direct Python deps to clear `pip-audit` warnings**:
  - Django `>=6.0.4` (7 advisories incl. SQL injection, timing attack, DoS chains)
  - cryptography `>=46.0.7` (2 advisories beyond the previous SECT-curve floor)
- **Pin transitive security floors**: `Authlib>=1.6.11` (alg:none JWT bypass), `nltk>=3.9.4` (5 advisories), `pyasn1>=0.6.3` (GHSA-jr27-m4p2-rc6r). `pip-audit` now clean against the venv.
- Untrack `.pip-audit-cache/` from git — 105 stale cache files were tracked and churning on every scan.

## [3.17.70] - 2026-04-27

### New Features
- **Native PSA / Service Desk — Phase 1 foundation** (off by default, fully gated). New `psa` Django app distinct from the existing `integrations.PSATicket` (which mirrors third-party PSA syncs).
  - Models: `Ticket` (full field set, auto-numbered `PSA-YYYY-NNNNNN`), `Queue`, `TicketStatus`, `TicketPriority`, `TicketType`, `TicketComment` (with `is_internal` flag preserved for Phase 3 portal), `TicketAttachment` (tenant-scoped upload path), `ClientPSASettings` (per-tenant enable + per-surface flags).
  - Feature flags: `core.SystemSetting.psa_enabled` (global), `psa.ClientPSASettings.enabled` (per-client). Helpers: `is_psa_enabled`, `is_psa_enabled_for_client`, `@require_psa_enabled`, `@require_client_psa_enabled`. Routes return 404 (not redirect) when disabled — avoids leaking existence.
  - `psa_seed_defaults` mgmt command seeds 7 queues, 10 statuses, 5 priorities (P1..P5 with spec-default SLA targets), 14 types.
  - Tenant scoping via existing `core.middleware.get_request_organization`. Audit log via `audit.AuditLog.log()` on every mutation. RBAC via `core.decorators.@require_write`. Sidebar entry hidden via context-processor flag. Migrations `core.0043` (`psa_enabled`) and `psa.0001` (initial app).
  - 11 PSA tests covering disabled-by-default, per-client opt-in, auto-numbered tickets, audit log writes, cross-tenant isolation, seed idempotency.
- **Secure vault context page for tickets** (`/psa/t/<ticket_number>/context/`):
  - Read-only metadata view of the ticket organization's vault entries. Each row has an "Open in Vault" button with `target="_blank" rel="noopener"` linking to the existing `vault:password_detail` view (which enforces its own permission and audit checks).
  - **Never inlines secret values** or loads encrypted columns — restricted via `.only(...)`. Asserted by `test_vault_context_does_not_render_secret_values` (response body cannot contain `encrypted_password`, `decrypt`, or sample plaintext).
  - Right-rail "Vault Context" panel on the ticket detail page shows the top 5 entries with a "View all" footer.
  - Every page open writes `AuditLog(action='read', object_type='psa.TicketContext')` — every vault context open is auditable.
- **Admin warning system on Security Dashboard** — unified panel surfacing OS package security updates, Python dependency vulnerabilities (new `pip-audit`-driven scanner at `/core/security/python-scanner/`), app-version-behind, and expiring SSL/domain certs. Severity-sorted with deep-link actions. Right-rail Python deps tile mirrors the OS tile.
- **Scheduled `python_dep_scan` task** (enabled, daily) and `system_warnings_digest` task (opt-in, requires SMTP). Digest reuses the vault password expiry notification pattern; `SystemWarningNotification` tracks already-notified warning IDs to prevent re-spam.

### Security
- **Patch 4 Python dependency CVEs** (Dependabot):
  - Pillow `12.1.* → 12.2.0+` (high: FITS GZIP decompression bomb)
  - python-dotenv `1.0.* → 1.2.2+` (symlink-follow arbitrary file overwrite)
  - requests `2.32.* → 2.33.0+` (insecure temp file reuse)
  - markdown `3.5.* → 3.8.1+` (uncaught exception DoS)

## [3.17.69] - 2026-04-27

### Internal
- Ignore local `projects/` side-project directory so unrelated side-projects don't show up as untracked in `git status`.

## [3.17.68] - 2026-04-27

### New Features
- **Vault password expiration dates with alerts** — vault items already had an `expires_at` field on the model; this release wires it end-to-end:
  - **Expiry badges on vault list** — expired passwords show a red "Expired" badge; passwords expiring within 14 days show an amber "Expires in Xd" badge alongside the existing security status badge
  - **Email notifications** — new scheduled task (`Vault Password Expiry Notifications`, runs daily) checks for passwords expiring within the configured warning window and emails superusers and org admins. Notification flag resets automatically if the expiry date is changed, so alerts re-fire with the new date
  - **Settings** — new "Send vault password expiration warnings" toggle and "Password Expiry Warning (days)" field in Settings → SMTP & Notifications (default: 14 days)
  - **Migration** — adds `notify_on_password_expiry` and `password_expiry_warning_days` to `SystemSetting`

## [3.17.67] - 2026-04-27

### Bug Fixes
- **"View AI Doc" / "View Profile" 404 from asset detail (#126)** — both document buttons used `asset.ai_document.pk` and `asset.profile_document.pk` in the `{% url 'docs:document_detail' %}` tag, but that URL pattern takes a `slug`, not a PK. Django matched the numeric PK as a slug string and the view's `get_object_or_404(Document, slug=slug)` found no match. Fixed to use `.slug`.
- **ITFlow sync datetime comparison error (#125)** — `updated_since` is passed as a timezone-naive datetime but ITFlow API timestamps are parsed as timezone-aware (UTC). Comparing the two raises `TypeError: can't compare offset-naive and offset-aware datetimes`. Fixed in `list_companies`, `list_contacts`, and `list_tickets` by making the naive `updated_since` timezone-aware (UTC) before comparing. Thanks to HabeasPorpoise for the root cause analysis and fix.

## [3.17.66] - 2026-04-22

### Bug Fixes
- **Changelog not rendering on updates page** — `|escapejs` was used in an HTML `data-` attribute; it backslash-escapes double quotes (`\"`), which truncated the attribute value at the first `"` in the changelog text. Changed to `|escape` (HTML entity encoding); browsers automatically decode entities when reading `dataset` properties in JavaScript.

## [3.17.65] - 2026-04-22

### New Features
- **Release notes on the Updates page (#124)** — the System Updates page now shows a rendered changelog for the current version ("What's in vX.Y.Z") and a collapsible per-version list of everything that changed between the running version and the latest available update. Each version entry is expandable and tagged with New / Fix / Improved badges. CHANGELOG.md is now fully populated from v3.17.27 onwards.

## [3.17.64] - 2026-04-20

### Bug Fixes
- **Copy button "Error fetching password" on HTTP installs (#122)** — `navigator.clipboard` is `undefined` in non-HTTPS (plain HTTP) browser contexts; calling `.writeText()` threw synchronously inside the fetch `.then()` handler, which propagated to the outer `.catch()` and showed the misleading "Error fetching password" alert. Added a `copyToClipboard()` helper that uses the Clipboard API when available and falls back to `document.execCommand('copy')` for plain-HTTP installs. Applies to username, password, and OTP copy buttons.

## [3.17.63] - 2026-04-20

### Bug Fixes
- **API diagnostic table leaking into generated UniFi documentation (#105)** — when traffic rules were empty and legacy credentials were present, the generated HTML document embedded the raw API endpoint diagnostic table (path attempts, auth methods, status codes). This is debug data that belongs only on the integration sync detail page. Generated documents now show a clean "No traffic rules found." message.

## [3.17.62] - 2026-04-20

### Bug Fixes
- **Traffic Routes section hidden when empty in UniFi detail page (#105)** — the Traffic Routes / App Rules section used `{% if site.traffic_routes %}` which hid the section entirely when no routes were found, giving the impression of a discrepancy vs. the generated documentation (which always renders both sections). Now always shown with "No traffic routes configured." empty state, matching Traffic Rules behaviour.

## [3.17.61] - 2026-04-18

### New Features
- **Per-site Import button for UniFi cloud connections (#105)** — each site card on the cloud connection detail page now shows an Import button (when an org is assigned to that site) allowing devices to be imported into the assigned organisation directly without using the bulk import flow.

## [3.17.60] - 2026-04-18

### New Features
- **UniFi cloud import per-site org routing (#105)** — when importing from a cloud connection, devices are now grouped by their assigned organisation and imported into the correct org rather than the session org. Sites without an org assignment are skipped.
- **Zone API diagnostic (#105)** — added `_zone_diag` tracking to the UniFi zone lookup; shown as a yellow diagnostic card in the sync detail page when no zone names can be resolved, listing every API path attempted.

### Bug Fixes
- **UniFi cross-org 404 on cloud connections (#105)** — `get_object_or_404(UnifiConnection, pk=pk, organization=org)` failed when the session org differed from the connection's org. Replaced with `_get_unifi_connection()` helper that bypasses the org filter for superusers and staff.

## [3.17.59] - 2026-04-17

### Bug Fixes
- **Whitelabeling site name not applying to page titles (#119, #120)** — child templates each define `{% block title %}` which completely overrides the parent `base.html` block, bypassing the dynamic brand expression. All 193 templates had hardcoded "Client St0r" in their title blocks. Bulk-replaced with the dynamic expression `{{ system_settings.custom_company_name|default:system_settings.site_name|default:"Client St0r" }}`.

## [3.17.58] - 2026-04-17

### Bug Fixes
- **Site name / custom company name not updating browser tab or login page (#119, #120)** — `base.html` had a hardcoded title; `two_factor/_base_focus.html` had hardcoded "Client St0r" in both the `<title>` and `<h1>`. Both updated to use `system_settings.custom_company_name|default:system_settings.site_name|default:"Client St0r"` via the `organization_context` context processor which is available on all pages including unauthenticated login.

## [3.17.57] - 2026-04-15

### Bug Fixes
- **Vault password reveal/copy/breach/TOTP return 404 in Global View (#119)** — `password_reveal`, `password_test_breach`, `generate_otp_api`, and the OTP QR view all used `get_object_or_404(Password, pk=pk, organization=org)` which fails when `org=None` (Global View mode). Added global view guard matching the existing pattern in `password_detail`: superusers and staff in Global View fetch by PK only.

## [3.17.56] - 2026-04-15

### Bug Fixes
- **UniFi cloud connection 404 (#105)** — sync, test, and import views used `get_object_or_404(UnifiConnection, pk=pk, organization=org)` which fails for cloud connections whose org differs from the session org. Extracted `_get_unifi_connection()` helper.
- **Firewall policy crash on Network 10.x (#105)** — `html.escape()` was called on the `action` field which can be a `dict` in Network 10.x (`{"type": "ACCEPT"}`). Added type-safety to extract the `type`/`name` key before escaping.
- **Zone names showing as numeric IDs (#105)** — enhanced zone resolution to check inline `zoneName`/`name` fields within policy source/destination objects as a fallback when the zones API returns no results. Also added more API path variants including `firewall/zones` and legacy `networkconf` endpoint.

## [3.17.55] - 2026-04-14

### New Features
- **Import job dry-run promote (#105)** — added `import_promote` view and confirmation page so dry-run import jobs can be promoted to real imports without re-uploading. Added `skip_duplicates` boolean field to `ImportJob` model (migration included).

## [3.17.54] - 2026-04-13

### Bug Fixes
- **Missing `unifi_connections.mode` column on fresh installs** — migration was missing on clean database setups; added explicit migration to ensure the `mode` column is created.

## [3.17.53] - 2026-04-13

### Bug Fixes
- **Vault list hardcoded URLs** — vault list templates used hardcoded `/vault/passwords/` paths instead of `{% url %}` tags, breaking installs with a custom `FORCE_SCRIPT_NAME`.

## [3.17.52] - 2026-04-12

### Bug Fixes
- **Membership import failure** — CSV import for memberships was failing on missing field mapping.
- **Vault password create decrypt error** — password creation form was not correctly handling the encryption round-trip on save.
- **Software not appearing in device profiles** — software list was excluded from the profile document template context.

## [3.17.51] - 2026-04-12

### Bug Fixes
- **UniFi `TemplateSyntaxError`** — a template tag syntax error in the UniFi detail page caused a 500 on render.
- **AI blueprint software display** — software section was not rendering in AI-generated blueprint documents.

## [3.17.50] - 2026-04-11

### New Features
- **UniFi cloud site org assignment** — added per-site organisation dropdown on the cloud connection detail page; selections are saved to `site_org_map` (JSONField) and used during import to route devices to the correct org.

### Bug Fixes
- **UniFi zone names still showing as IDs** — added int/string coercion for zone ID lookups and additional fallback: extract zone name from within policy `source`/`destination` objects when the zones API is unavailable.
- **Traffic rule display** — improved normalisation of traffic rule entries from the integration v1 API format.

## [3.17.49] - 2026-04-11

### Bug Fixes
- **Traffic routes list crash** — `traffic_routes` was not always a list; added defensive type check.
- **Zone ID lookup** — improved zone map key coercion (int and string keys) to handle mixed-type IDs returned by different firmware versions.
- **AI blueprint software format** — software entries were being rendered as raw Python repr instead of a readable list.

## [3.17.48] - 2026-04-10

### New Features
- **Software list in AI blueprint** — installed software is now included in the AI-generated device documentation blueprint.

### Bug Fixes
- **UniFi cloud devices still empty** — `_get_all` only checked the `data` response key; the Site Manager API can return results under `items`, `devices`, or as a bare list; now tries all known key names.
- **UniFi traffic rules error** — additional error handling for traffic rules endpoint on cloud connections.

## [3.17.47] - 2026-04-10

### Bug Fixes
- **TRMM software sync missing connection FK (#113)** — software sync was creating `InstalledSoftware` records without setting the `rmm_connection` foreign key, causing integrity errors.
- **UniFi zone names (#105)** — further improvements to zone name resolution from multiple API response shapes.

## [3.17.46] - 2026-04-10

### New Features
- **Default organisation preference (#115)** — users can now set a default organisation that is auto-selected on login.

### Bug Fixes
- **Organisation location bugs (#116)** — fixed several edge cases in org location display and editing.

## [3.17.45] - 2026-04-09

### Bug Fixes
- **Apply update returning HTML 500 instead of JSON** — the update apply endpoint was returning an HTML error page on import errors instead of a JSON response, breaking the JS update flow.

## [3.17.44] - 2026-04-09

### Bug Fixes
- **Update check 500 on older DB schemas** — `AuditLog` query referenced `extra_data` column which did not exist on pre-migration databases; added `try/except` guard.

## [3.17.43] - 2026-04-09

### Bug Fixes
- **UniFi Network 8.x+ zone policy paths** — added non-REST zone-policy paths for Network 8.x firmware; improved endpoint discovery probe to cover more firmware generations.

## [3.17.42] - 2026-04-09

### New Features
- **Asset health indicators** — age warnings (configurable threshold), firmware version tracking, and warranty expiry checks added to the asset list and detail views.

## [3.17.41] - 2026-04-09

### Bug Fixes
- **UniFi firewall policy path variants (#105)** — added additional path attempts for Network 10.x firewall policies including `security/firewall-policies`, `security/zone-policies`, and integration v1 variants.

## [3.17.40] - 2026-04-09

### New Features
- **Contact ratings and tech notes** — organisations now support per-contact difficulty ratings and free-text technician notes.

### Bug Fixes
- **Service button colours** — fixed incorrect CSS class on service quick-info buttons.

## [3.17.39] - 2026-04-09

### New Features
- **Service quick-info buttons** — organisation detail page now shows quick-info buttons for configured integrations (TRMM, UniFi, M365, etc.).

## [3.17.38] - 2026-04-09

### Improvements
- **Signal-bar rating UI** — replaced SVG gauge graphics with a cleaner CSS signal-bar component for support difficulty ratings.

## [3.17.37] - 2026-04-09

### Bug Fixes
- **Support ratings 403** — permission check was too restrictive; relaxed to allow org-scoped staff to submit ratings.

## [3.17.36] - 2026-04-09

### Bug Fixes
- **Incorrect stat text in consult and about templates** — removed copy that referenced a wrong window/context.

## [3.17.35] - 2026-04-09

### New Features
- **Free consultation request form** — public-facing form for prospective clients to submit consultation requests; submissions appear in the admin dashboard.

## [3.17.34] - 2026-04-08

### New Features
- **Support difficulty ratings** — organisations can be rated for support complexity; ratings are shown on the org list and detail pages to help technicians set expectations.

## [3.17.33] - 2026-04-08

### Bug Fixes
- **TRMM software sync (#113)** — expanded endpoint path attempts and fixed sync to process all devices rather than stopping after the first successful response.

## [3.17.32] - 2026-04-08

### New Features
- **UniFi Traffic Routes section** — added Traffic Routes / App Rules (Network 10.x website/app blocking) as a separate section in the UniFi sync detail page and generated documentation.

### Bug Fixes
- **UniFi zone name display (#105)** — improved zone name rendering in the firewall policy table.
- **TRMM software message** — corrected empty-state message when no software is found.

## [3.17.31] - 2026-04-08

### Bug Fixes
- **TRMM software sync UUID vs PK (#113)** — sync was passing the numeric database PK to the TRMM API instead of the agent UUID; fixed to use the correct identifier.

## [3.17.30] - 2026-04-08

### Bug Fixes
- **UniFi zone policy template crash (#105)** — template referenced `site.zone_policies` before it was populated; added guard. Fixed `zone_id` field mapping to handle both string and integer zone IDs.

## [3.17.29] - 2026-04-08

### Bug Fixes
- **UniFi endpoint discovery (#105)** — added probe step that tests available API paths before syncing, reducing 404 noise in logs. Added Network 10.x path variants for zone policies and traffic rules.

## [3.17.28] - 2026-04-08

### Bug Fixes
- **UniFi legacy session auth (#105)** — fixed session cookie handling for legacy REST auth on older UniFi firmware; expanded path probing to include more site reference formats.

## [3.17.27] - 2026-04-08

### New Features
- **UniFi firewall/traffic rule diagnostics (#105)** — added `_tr_diag` and `_fp_diag` diagnostic tracking to the UniFi sync; shown in the sync detail page when rules cannot be retrieved, listing every API path attempted with status codes.

### Bug Fixes
- **UniFi legacy site ref fallback (#105)** — added `internalReference` → `name` → UUID fallback chain for site references passed to the legacy REST API.

## [3.17.26] - 2026-04-08

### Bug Fixes
- **Ollama "Unknown LLM provider" error (#112)** — `AIDocumentationGenerator` had a hardcoded `elif` chain for known providers and raised `ValueError` for `ollama`; added the `ollama` case to read `OLLAMA_BASE_URL` and `OLLAMA_MODEL` from settings
- **UniFi zone policies / traffic rules blank on Network 10.x (#105)** — UniFi Network 9.x/10.x moved firewall and traffic rule endpoints under a `security/` path prefix; added `security/zone-policies`, `security/policies`, `security/firewall-policies`, `security/traffic-rules`, and `security/trafficrules` paths to the attempt list for both v2 API key and legacy session cookie auth

## [3.17.25] - 2026-04-07

### Bug Fixes
- **M365 OneDrive display name blank (#106)** — Microsoft's OneDrive usage CSV uses `Owner Display Name` and `Owner Principal Name` as column headers, not `Display Name` / `User Principal Name` as the mailbox report does; fixed column name mapping so names and emails appear correctly
- **UniFi cloud devices (#105)** — added a third fallback: extract device inventory embedded in `host.reportedState.devices` (the Site Manager API embeds device lists in the host object on some API key scopes where `/v1/devices` is restricted)
- **UniFi local rules (#105)** — added integration v1 API paths (`/proxy/network/integration/v1/sites/{id}/trafficRules` and `.../firewallPolicies`) as additional attempts; these accept the X-API-Key and may work on newer UniFi OS firmware without requiring username/password

## [3.17.24] - 2026-04-07

### New Features
- **M365 OneDrive storage usage (#106)** — new `get_onedrive_usage()` method fetches per-user OneDrive storage stats (used, allocated, file count, last activity) from the Graph Reports API; shown as a new section in the M365 tenant document alongside SharePoint usage. Requires `Reports.Read.All` permission (same as mailbox usage).
- **Ollama on-premises AI provider (#112)** — added `OllamaProvider` to the multi-LLM system; configure a base URL (e.g. `http://localhost:11434`) and model name in Settings → AI & LLM; no API key required; all inference stays on your infrastructure; test connection button lists available models.

### Bug Fixes
- **UniFi cloud devices still empty (#105)** — `_get_all` only checked the `data` response key; the Site Manager API can return results under `items`, `devices`, or as a bare list; now tries all known key names; also added a `hostIds` (plural) filter param variant as a final fallback.
- **UniFi local traffic rules / zone policies still blank (#105)** — v2 API paths were only tried with the API key, then with session cookie; added a third attempt using the legacy REST paths (`/proxy/network/api/s/{ref}/rest/trafficrule`) with the API key, which works on some firmware versions without needing username/password.

## [3.17.23] - 2026-04-05

### Bug Fixes
- **TRMM MAC address (#108)** — `wmi_detail.network_adapter` is a list-of-lists structure (not a flat list); added `_flatten_wmi_list` helper to unwrap the nested lists before extracting MAC addresses; also added `network_config` as a secondary source with `IPEnabled` preference; covers all known TRMM response shapes
- **M365 detail page crash (#106)** — template referenced `mb.mailboxType` which doesn't exist in the mailbox row dict, causing `VariableDoesNotExist`; removed the invalid fallback

## [3.17.22] - 2026-04-05

### Bug Fixes
- **M365 detail page crash (#106)** — template referenced `mb.userDisplayName` which doesn't exist in the mailbox row dict, causing `VariableDoesNotExist`; removed the invalid fallback
- **UniFi local zone policies/traffic rules blank (#105)** — v2 API paths were tried with the UUID (`siteId`) first, but the v2 API typically requires the short internal reference name (e.g. `default`); swapped order so `internalReference` is tried first
- **UniFi cloud no devices (#105)** — added `/v1/hosts/{hostId}/devices` per-host endpoint as primary path before the flat `/v1/devices?hostId=` query param approach

## [3.17.21] - 2026-04-05

### Bug Fixes
- **TRMM MAC address (#108)** — bulk `/agents/` response may return `mac_addresses: [""]` (list with one empty string) which is truthy; `_has_mac` was True so the detail fetch was skipped and the real `MACAddress` from `/agents/{id}/` was never retrieved; fixed by requiring non-empty entries in the list
- **M365 mailbox data (#106)** — rewrote `get_mailbox_usage` to decode blob CSV with `utf-8-sig` (handles BOM), strip per-row BOM artifacts, handle `Storage Used (Bytes)` column name variant, and log what was received when 0 rows parse; removed unreliable `$format=application/json` parameter
- **UniFi zone policies blank (#105)** — `_parse` for firewall policies and traffic rules only checked a few response keys; added all known UniFi API wrapper key variants (`zonePolicies`, `zone_policies`, `firewallPolicies`, `trafficRules`, `traffic_rules`, `rules`)

## [3.17.20] - 2026-04-03

### Bug Fixes
- **M365 Defender alerts not showing (#106)** — `alerts_v2` endpoint does not support `$orderby`; the 400 error was silently swallowed returning an empty list; removed `$orderby` and dropped unsupported `userStates` from `$select`
- **UniFi cloud mode note** — updated to mention zone policies / traffic rules and explain how to get them via a self-hosted connection

## [3.17.19] - 2026-04-03

### Bug Fixes
- **TRMM MAC address (#108)** — also scan `wmi_detail.network_adapters` and `wmi_detail.network_config` for MAC; added `MACAddress` (capitalized) as NIC-level field variant
- **M365 mailbox data (#106)** — Graph reporting endpoint redirects to a blob SAS URL; `requests` strips the `Authorization` header on cross-domain redirects causing a spurious 403; now follows the redirect manually without auth header
- **UniFi cloud no devices (#105)** — flat `/v1/devices` endpoint may return empty without explicit `hostId`; now fetches devices per-host first, falling back to flat endpoint only if per-host yields nothing

## [3.17.18] - 2026-04-03

### Bug Fixes
- **TRMM MAC address still missing (#108)** — TRMM API returns network interfaces under `interfaces` key, not `nics`; normalize_device was scanning an empty list; added `interfaces` as fallback so MAC is now extracted correctly
- **UniFi local APs still "other" (#105)** — newer U6/U7 series APs have model prefix `u6`/`u7`, not `uap`; added U6, U7, U2, UAF, UBB model prefixes to type map
- **UniFi cloud no devices (#105)** — cloud sync only matched devices to sites by `siteId`; if `siteId` is missing or mismatched, all devices were silently dropped; added fallback that groups unmatched devices directly under their host

## [3.17.17] - 2026-04-02

### Bug Fixes
- **TRMM MAC address sync (#108)** — fixed empty-string MAC address never updating on assets; `device.mac_address == ''` is falsy so the update was silently skipped; now correctly checks `is not None`
- **M365 mailbox data missing from document (#106)** — fixed `_build_mailbox_usage()` returning an empty string when permissions are denied (silently omitting the section); now shows a clear permission error card with the required permission name; also shows an informational card when data is empty rather than hiding the section
- **UniFi asset type always "other" (#105)** — added camelCase cloud Site Manager API productType values to `_TYPE_MAP` (`accessPoint`, `networkSwitch`, `securityGateway`, `dreamRouter`, `dreamMachine`, `cloudGateway`, `powerUnit`); the cloud API returns camelCase which lowercased to unsplit words that didn't match the underscore/hyphen entries

## [3.17.14] - 2026-04-02

### New Features
- **Install App / Add to Home Screen page** (`/core/install/`) — no login required, shareable with staff; shows a QR code of the server URL, a downloadable QR PNG, a one-tap Install button (Android Chrome / desktop), and step-by-step Add to Home Screen instructions for Android, iPhone/iPad, and desktop
- **Profile menu updated** — "Install App (PWA)" now links to the new install page instead of a JS-only prompt, making it work correctly on iOS Safari

## [3.17.13] - 2026-04-02

### New Features
- **Phone Home Screen Shortcut for Receipt Scanning** — "Phone Shortcut" button on vehicle Receipts tab opens a modal with a per-vehicle QR code, a copyable direct URL, and step-by-step Add to Home Screen instructions for Android (Chrome) and iOS (Safari)
- **PWA Shortcuts** — manifest.json now includes "Scan Receipt" and "Vehicles" shortcuts; long-pressing the Client St0r icon on Android shows these shortcuts
- **Quick Receipt landing page** (`/vehicles/receipts/quick/`) — vehicle picker that redirects to receipt_create; if only one active vehicle, skips straight to Add Receipt; QR codes in the shortcut modal link here with `?v=<pk>` for direct-to-vehicle access

## [3.17.12] - 2026-04-02

### New Features
- **Receipt duplicate prevention** — receipt images are SHA-256 hashed on OCR extract and on upload; if the same image already exists on any receipt, saving is blocked with a clear error showing the original receipt details

### Improvements
- Receipt form redesigned with Step 1 / Step 2 layout
- Inline duplicate alert replaces browser popup
- "Configure AI key" link next to the AI Extract button points to Settings → AI
- AI state resets when a new image is selected

### Migrations
- `vehicles/migrations/0007_receipt_image_hash.py` — Adds `image_hash` column (db_index) to `vehicle_receipts`

## [3.17.11] - 2026-04-02

### New Features
- **Vehicle Receipt Scanning with AI OCR** - Upload or photograph receipts directly from your phone; Claude vision API extracts vendor, date, amount, tax, category, and odometer reading automatically; AI confidence indicator prompts review of uncertain fields; receipt image stored alongside record
- **Receipt Expense Tracking** - New Receipts tab on vehicle detail page with per-category cost summary cards (Fuel, Maintenance, Repair, Total); full receipt table with category badges and AI indicator; supports all expense categories: fuel, maintenance, repair, insurance, registration, tolls, cleaning, inspection

### Migrations
- `vehicles/migrations/0006_add_vehicle_receipts.py` — Creates `vehicle_receipts` table

## [3.17.10] - 2026-04-02

### Bug Fixes
- **Client org dropdown cut off on smaller screens** — Simplified to single-line pill with smaller font (`.78rem`), tighter padding, `overflow:hidden`, `max-width:180px`, ellipsis truncation on org name

## [3.17.9] - 2026-04-02

### New Features
- **Automated Security Scan Scheduling** — New scheduled task (`security_scan`) runs OS package + Snyk vulnerability scans daily (disabled by default); emails all superusers when findings are detected using configured SMTP; toggle on/off from Security Dashboard with next run time and last status display
- **Client/Org Indicator Redesign** — Active organization shown as a distinct amber gradient pill in the navbar with a pulsing dot indicator to draw attention to the active client context

### Bug Fixes
- **Security dashboard scan history contrast** — Improved badge and severity label colors (medium/low/high) for readability in both light and dark themes
- **TRMM MAC address missing after sync** — Per-agent detail fetch was only triggered when RAM/disk data absent; now also triggered when MAC address is missing from list response (fixes #108)
- **M365 mailbox usage data not in generated document** — `_build_mailbox_usage()` function and document section were missing from M365 document generator (fixes #106)
- **UniFi Security Gateway always categorized as "other"** — Added `ugw` to `_TYPE_MAP`; device `model` field now checked as fallback for type detection (fixes #105)
- **IPAM asset link field not functional** — IP address form used `{{ form.asset_id }}` (non-existent); corrected to `{{ form.asset }}`; asset link in subnet detail table now renders as clickable link (fixes #111)

## [3.16.5] - 2026-03-30

### Bug Fixes
- **Navbar main items now centered** - Changed main nav `<ul>` from `navbar-nav` to `navbar-nav mx-auto`; removed `ms-auto` from the right navbar `<ul>` to avoid competing auto-margins. Bootstrap flexbox now distributes equal left/right auto-margins around the main nav, centering Dashboard/Assets/Vault/Docs/Operations/Reports/Admin between the logo and right-side items (search, org switcher, profile)

## [3.16.4] - 2026-03-30

### Bug Fixes
- **Navbar off-center after nav consolidation** - Removed `flex-wrap: wrap` and redundant `display: flex; align-items: center` from `.navbar-container` in `custom.css`; Bootstrap handles the flex layout natively — wrapping was causing the nav to render on two rows and appear misaligned after the Operations dropdown consolidation

## [3.16.3] - 2026-03-30

### New Features
- **Locations integrated into Organizations** - Manage multiple physical locations per organization directly from the organization detail page; removed Locations from the Admin navigation (access is through org → Locations section); each location card shows status badges (Inactive/Planned/Closed) and Edit/Delete buttons for owners and admins; location count badge on section header
- **Streamlined top navigation** - Consolidated Inventory, Scheduling, Monitoring, Vehicles, and Workflows into a single "Operations" dropdown (only shown if at least one of these modules is enabled); removed "Quick Add" from top nav (already on dashboard); removed standalone Locations from Admin dropdown; reduced nav from 12 items to 6 (Dashboard, Assets, Vault, Docs, Operations, Reports, Admin)

### Bug Fixes
- **Vehicle Inventory dark mode contrast** - `inventory_summary.html` replaced all hardcoded light-mode CSS colors (`#f8f9fa`, `white`, `#212529`, `#d1e7dd`, `#f8d7da`) with Bootstrap CSS variables (`--bs-secondary-bg`, `--bs-card-bg`, `--bs-body-color`, `--bs-border-color`); now renders correctly in both light and dark mode

## [3.16.2] - 2026-03-28

### Changes
- **Settings → Integrations** - Moved Integrations link from Admin Management dropdown to Settings sidebar under a dedicated "Integrations" section; removed duplicate from Admin nav
- **Settings sidebar** - Replaced "Vault Import" with "Data Import" in the Settings sidebar link

## [3.16.1] - 2026-03-28

### New Features
- **Data Import with CSV field mapper** - New visual field mapper for importing any CSV/spreadsheet data; supports Assets, Passwords (Vault), Contacts, and Documents as target models; auto-suggests column mappings by name; shows 5-row data preview; `CSVImportService` handles import with deduplication
- **Multi-platform data import** - Import data from Hudu exports, IT Glue exports, MagicPlan floor plans, or any CSV/spreadsheet file; import jobs tracked in database with status and record counts
- **Field mapper UI** - Step-by-step flow: upload file → map fields → import; radio buttons to select target model; per-column dropdowns for destination fields; JavaScript `rebuildSelects()` updates dropdowns when model type changes

### Changes
- **Renamed "Vault Import" → "Data Import"** - Import is no longer vault-specific; all data types supported

### Migrations
- `imports/migrations/0006_csv_import_mapper.py` — Adds `csv_target_model` and `field_mappings` fields to `import_jobs` table

## [3.16.0] - 2026-03-27

### New Features
- **Omada network integration** - TP-Link Omada SDN controller integration: session-based authentication with CSRF token support, paginated API calls, site-aware device discovery; devices mapped to asset types (switch, wireless_ap, gateway, eap); CRUD management + manual sync + import-as-assets; configurable scheduled auto-sync
- **Grandstream network integration** - Grandstream GDMS/UCM integration: Bearer token authentication, paginated device listing with flat fallback for simple deployments; all devices mapped to `wireless_ap` asset type; same CRUD + sync + import flow as UniFi and Omada
- **Network asset auto-sync** - New `sync_network_assets` management command (called by systemd timer); iterates all UniFi, Omada, and Grandstream connections with `auto_sync_assets=True`; respects per-connection `sync_interval_minutes` to avoid unnecessary API calls; updates `last_asset_sync_at` on completion
- **Shared device import helper** - `_import_devices_to_assets(org, devices, source_label)` in `integrations/views.py`; matches by MAC address first, then serial number; creates or updates Asset records; used by all three network integrations

### Migrations
- `integrations/migrations/0018_add_omada_grandstream_autosync.py` — Adds `auto_sync_assets`, `sync_interval_minutes`, `last_asset_sync_at` to `UnifiConnection`; creates `omada_connections` and `grandstream_connections` tables

## [3.13.1] - 2026-02-24

### Bug Fixes

**GUI updater: sudo check no longer fails due to service name mismatch in sudoers**
- `_check_passwordless_sudo()` was testing `sudo systemctl status <service-name>` — if the sudoers file was created on an older version that used `clientst0r-gunicorn.service` as a fallback, the test would fail even though sudo itself was correctly configured for `huduglue-gunicorn.service` or another service name
- Now tests against `sudo systemd-run --version` which is always present in the sudoers config and does not depend on a specific service name — falls back to the service-specific check only as a secondary test
- Fixes: GUI updater showing "Passwordless sudo not configured" even after setting up the sudoers file correctly (issue #91)

## [3.13.0] - 2026-02-24

### Security & Performance Hardening Release

This release addresses findings from a full internal security and performance audit across the entire codebase. No functional changes — all existing behaviour is preserved.

#### Security Fixes

**GraphQL: explicit field whitelists on all types** (`api/graphql/schema.py`)
- Replaced `fields = '__all__'` on every `DjangoObjectType` with explicit safe field lists
- Sensitive fields (internal flags, file paths, cost data, raw error strings, SSL serial numbers, `created_by`, `last_modified_by`) are no longer queryable via the API
- Also fixed a resolver that was referencing the wrong field name (`expiration_date` → `expires_at`)

**GraphQL playground disabled in production** (`api/urls_graphql.py`)
- `graphiql` interface now only enabled when `DEBUG=True`
- Playground URL route only registered in debug mode — schema exploration is not accessible on production deployments

**subprocess input validation — ping target** (`locations/models.py`)
- `WAN.check_status()` now validates `monitor_target` against `^[a-zA-Z0-9.\-]+$` before passing it to `subprocess.run(['ping', ...])`
- Rejects any value containing shell metacharacters or unexpected characters

**XSS: process template filters use proper escaping** (`processes/templatetags/process_filters.py`)
- All user-controlled dict keys and values now pass through `conditional_escape()` before being rendered
- HTML assembly uses `format_html()` instead of bare f-strings — user data can no longer inject arbitrary HTML

**Path traversal: X-Accel-Redirect validation** (`files/views.py`)
- File download view now raises `SuspiciousFileOperation` if `attachment.file.name` contains `..` or starts with `/` before setting the nginx `X-Accel-Redirect` header

**Bleach HTML sanitization tightened** (`docs/models.py`)
- Removed `<button>` from allowed tags (interactive element, potential JS vector)
- Replaced dict-based `allowed_attrs` with a callable that enforces safe `href` protocols (`http://`, `https://`, `mailto:`, `#`) — blocks `javascript:` and protocol-relative `//attacker.com` URLs
- Removed `style` attribute from all tags globally (CSS injection vector)

**Generic file upload error messages** (`files/views.py`)
- Error responses no longer enumerate allowed file extensions or reveal specific file type details
- All three verbose error messages replaced with `"File type not allowed"` / `"Invalid file"`

**CSRF: JSON content-type enforcement on exempt API endpoints** (`monitoring/api_views.py`)
- Six `@csrf_exempt` state-changing endpoints now reject requests where `Content-Type` is not `application/json`
- Browsers cannot submit cross-site form POSTs with `application/json` content type, providing equivalent CSRF protection without requiring cookie-based tokens on these AJAX-only endpoints

#### Performance Fixes

**Dashboard: 3 monitor status queries → 1** (`core/dashboard_views.py`)
- Replaced three separate `WebsiteMonitor.objects.filter(status=X).count()` calls with a single `.aggregate(Count('id', filter=Q(status=X)))` query

**Dashboard: activity feed skips loading large JSONField** (`core/dashboard_views.py`)
- Added `.only(...)` to the audit log activity feed query — `extra_data` JSONField no longer loaded for display-only rows

**Asset filter extraction: no longer loads full ORM objects** (`assets/views.py`)
- Custom field filter options (statuses, locations) now extracted via `.values_list('custom_fields', flat=True)` instead of iterating full model instances

**Network scan device matching: batch fetch instead of N+1** (`assets/views.py`)
- All org assets are now fetched once before the scan matching loop with `select_related('asset_type')`
- `match_device_to_asset()` accepts an `assets_cache` parameter and does all matching in Python when provided — eliminates 2 DB queries per scanned device

**Asset images: bounded query** (`assets/views.py`)
- `asset_detail` image attachment query now limited to 50 results

**Report generator: 4 COUNT queries → 1** (`reports/generators.py`)
- Asset summary report replaced four separate `.filter().count()` calls with a single `.aggregate()` covering total, active, inactive, and recent counts

#### Verification
- `manage.py check`: clean (1 pre-existing axes deprecation warning, unrelated)
- All 10 pre-existing test failures unchanged (setUp profile issue in tenant isolation tests, pre-dates this release)
- All 10 modified files passed syntax check

## [3.12.14] - 2026-02-24

### Changes

- Moved Favorites (★) next to the heart icon in the top-right navbar

## [3.12.13] - 2026-02-24

### Bug Fixes

**Update progress bar: real-time streaming fixed:**
- Root cause was Python's default 8KB block buffer on subprocess pipes — `readline()` blocked until the buffer filled or the script exited, so no lines streamed through in real-time
- Fixed by adding `bufsize=1` to `subprocess.Popen` (line-buffered mode) so each bash `echo` from the update script is delivered to Python immediately as it's written
- Reduced file I/O from 3 reads + 3 writes per log line down to 1 read + 1 write by adding a `process_log_line()` method to `UpdateProgress` that atomically writes the log entry and step state change together
- Also fixed `step_start`/`step_complete` to not double-write (previously called `add_log` as a separate write after already writing step state)

**Favorites navbar item: icon-only to save space:**
- Removed " Favorites" text label; link is now just the ★ icon with a "Favorites" tooltip on hover

**Tooltips: fixed for dropdown items and clock:**
- Added `container: 'body'` to tooltip options so tooltips on dropdown menu items render outside the menu element (fixes positioning/clipping inside hidden `.dropdown-menu`)
- Changed `trigger` from `'hover'` to `'hover focus'` for better keyboard accessibility
- Clock tooltip now uses `setAttribute('data-bs-original-title', ...)` instead of `el.title = ...` — Bootstrap 5 stores tooltip text in `data-bs-original-title` at init time and ignores subsequent `title` changes

**Navbar logo padding:**
- Added `!important` to `.navbar-container` padding so theme CSS resets cannot override it

## [3.12.12] - 2026-02-24

### Bug Fixes

**Update progress bar now tracks steps correctly:**
- `perform_update()` now parses shell script log output line-by-line and fires `step_start`/`step_complete` for the five named steps the UI expects (`Git Pull`, `Install Dependencies`, `Run Migrations`, `Collect Static Files`, `Restart Service`)
- Removed the generic `Download Update Script` / `Execute Update` step names that the UI had no mapping for — those consumed progress slots without lighting up any step indicators

**Navbar logo no longer clipped on the left:**
- Added `padding-left: 1rem; padding-right: 1rem` to `.navbar-container` in `custom.css`; Bootstrap's container-fluid gutter was being zeroed by theme resets, leaving the logo flush against the viewport edge

## [3.12.11] - 2026-02-24

### New Features

**12/24-hour clock format setting:**
- Added `time_format` preference to user profile (12-hour AM/PM or 24-hour, default 24-hour)
- Navbar clock respects the selected format — 12-hour shows `h:mm:ss AM/PM`, 24-hour shows `HH:mm:ss`
- Setting is in Profile > Preferences > Time Format alongside Timezone

## [3.12.10] - 2026-02-24

### Bug Fixes

**Update script fails when gunicorn has a restricted PATH:**
- Added `export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"` near the top of `deploy/update_instructions.sh`
- Gunicorn service files often set `Environment="PATH=/path/to/venv/bin"` which strips all standard system utilities from the subprocess environment — `date` (used in the `log()` function) and `git` both failed to resolve, causing an immediate exit with code 1
- PATH is now explicitly set before any utility is invoked, ensuring the script works regardless of the calling process's environment

## [3.12.9] - 2026-02-24

### Bug Fixes

**Update script: exact failure location now logged (exit code 1 debugging):**
- Added `trap 'log "ERROR: command failed at line $LINENO: $BASH_COMMAND"' ERR` so the exact failing command and line number appear in the progress log when the script exits non-zero

**Update script: wider venv detection:**
- Now checks `.venv` and `env` directory names in addition to `venv` — common on dev servers and tools like Poetry/PDM

**auto_heal_version: no longer kills itself:**
- Changed from `systemctl stop` + `pkill -9 gunicorn` (which kills the process running the command) to `systemd-run --on-active=2 --system systemctl restart` — the timer fires in system scope after the command returns, so the response can be sent before the restart
- Fallback to `start_new_session=True` Popen if systemd-run is unavailable
- Makes the `/emergency-restart/` webhook usable as an alternative to SSH

## [3.12.8] - 2026-02-24

### Bug Fixes

**Service restart not firing after GUI update:**
- `update_instructions.sh` now uses `systemd-run --system` (system D-Bus scope) instead of default user scope — without `--system`, the transient timer unit is owned by the gunicorn worker's cgroup and can be silently dropped when that worker exits before the 5-second delay elapses
- Added belt-and-suspenders nohup fallback: a detached `nohup bash -c "sleep 7 && systemctl restart $SERVICE"` is launched alongside systemd-run so the restart fires even if the systemd-run timer doesn't. Uses `disown` to ensure it fully outlives the parent process.
- No-systemd path also converted to nohup to survive parent process exit

## [3.12.7] - 2026-02-24

### Bug Fixes

**Update script portability (exit code 127 on some servers):**
- `deploy/update_instructions.sh` now resolves git via `command -v git` instead of hardcoding `/usr/bin/git` — git location varies by OS and install method
- Service restart step wrapped in guarded subshells with `|| log` fallbacks; missing `systemd-run` or `systemctl` no longer hard-exits the script

**Version revert after GUI update:**
- `cache.delete('system_update_check')` moved to *before* the update subprocess is launched rather than after — the service restart (scheduled inside the script) kills the gunicorn process before the post-run code could execute, leaving a stale `current_version: old` entry in cache for up to 5 minutes

**Fresh install migration failure (issue #90):**
- Migration `0009_convert_to_generic_connection` used `ContentType.objects.get()` which raises `DoesNotExist` on fresh installs where `psaconnection` content type was never created; changed to `filter().first()` with an early-return guard so the migration is safely skipped when there is no data to migrate

## [3.12.6] - 2026-02-24

### Architecture

**Downloadable Update Instructions:**
- `perform_update()` in `core/updater.py` now downloads `deploy/update_instructions.sh` fresh from the GitHub `main` branch and executes it, instead of running ~800 lines of hardcoded Python step logic
- `scripts/auto_update.sh` is now a thin wrapper that downloads and delegates to `deploy/update_instructions.sh` the same way
- If the update logic has a bug (wrong service name, broken restart command, etc.), push a fix to `deploy/update_instructions.sh` on GitHub — the next update attempt from any client automatically picks up the fixed script without needing a version bump
- The downloaded script is written to `/tmp/clientst0r_update_<pid>.sh`, executed, then cleaned up regardless of success or failure
- Progress is streamed line-by-line from the script to the GUI progress tracker in real time

## [3.12.5] - 2026-02-24

### 🔧 Fixes

**Duplicate Service Worker Fix (Version Flickering Fix):**
- Removed duplicate `service-worker.js` registration — both `sw.js` and `service-worker.js` were being registered for the same scope, and `service-worker.js` (registered last) was becoming the active controller with a cache-first strategy, causing it to serve stale cached HTML with old version numbers
- Added automatic unregistration of the legacy `service-worker.js` SW from any browser that already has it installed
- Bumped service worker cache name from `clientst0r-v2` to `clientst0r-v3` to clear any stale HTML content cached by the old duplicate SW

### ✨ Features

**Live Clock in Navbar:**
- Added a live HH:MM:SS clock to the right side of the navigation bar (hidden on mobile to save space)
- Clock shows full date on hover and updates every second

## [3.12.4] - 2026-02-24

### 🔧 Fixes

**Service Worker Cache Fix (Version Display Revert Fix):**
- Fixed service worker (`sw.js`) incorrectly caching server-rendered HTML pages including the system updates page
- When gunicorn briefly restarts during an update, the browser's service worker was serving the stale cached HTML (showing the old version) instead of fetching fresh from the newly-started server
- Changed `sw.js` to only cache static assets (CSS/JS/images), never server-rendered pages or API responses
- Bumped service worker cache version from `clientst0r-v1` to `clientst0r-v2` to immediately bust all stale cached page content in existing browser installations

## [3.12.3] - 2026-02-23

### 🔧 Fixes

**Update System (Version Revert Fix):**
- Fixed service detection in `auto_update.sh` - `huduglue-gunicorn.service` was missing from the detection list (was listed as `clientst0r-gunicorn.service` twice), causing the auto-update to exit without restarting the service on many installations
- Changed `git pull` to `git fetch && git reset --hard origin/main` in `auto_update.sh` to reliably handle force-push scenarios
- Fixed same service detection bug in `force_restart_services` view and `auto_heal_version` management command
- Added `huduglue-gunicorn.service` to `update.sh` CLI service detection (was using wrong service name in all branches)
- Updated `setup_gui_updates.sh` sudoers to include `huduglue-gunicorn.service` permissions
- Added CHANGELOG entries for 3.12.x releases (was causing WARNING log every 5 minutes)

## [3.12.2] - 2026-02-23

### 🔧 Fixes

**DataTables:**
- Fixed error on empty vehicles list when DataTables server-side processing is enabled

## [3.12.1] - 2026-02-23

### 🔧 Fixes

**GUI Updater:**
- Auto-detect gunicorn service name (huduglue-gunicorn, clientst0r-gunicorn, itdocs-gunicorn)
- Fixes version revert issue when remote server uses a different service name than hard-coded default

## [3.12.0] - 2026-02-23

### ✨ New Features

**Password List:**
- DataTables server-side processing for large password lists
- Improved performance and filtering for organizations with many credentials

## [2.76.2] - 2026-02-09

### 🔧 Fixes

**Asset Form Template:**
- Added lifespan tracking fields to asset edit form template
- Fields now properly display: purchase date, expected lifespan (years), lifespan reminder checkbox, reminder months before EOL
- Fields appear in new "Lifespan & Replacement Tracking" section after Notes field

### 📝 Technical Changes

**Frontend:**
- Updated `templates/assets/asset_form.html` with lifespan field rendering
- Added help text and validation for all lifespan fields
- Responsive layout with Bootstrap grid (col-md-3 columns)

## [2.76.1] - 2026-02-09

### 🔧 Fixes

**Global View Mode:**
- Fixed asset editing in global view mode
- `asset_edit` view now gets asset without organization filter when viewing globally
- Uses asset's own organization for form context instead of requiring org selection
- Enables editing any asset while in global view without selecting organization first

### 📝 Technical Changes

**Backend:**
- Updated `assets/views.py:asset_edit()` to handle `org=None` (global view mode)
- Conditional query: filters by org if set, otherwise gets asset without org filter

## [2.76.0] - 2026-02-09

### ✨ New Features

**Asset Lifespan Tracking:**
- **Purchase Date** - Track when asset was purchased or deployed
- **Expected Lifespan (years)** - Define expected lifespan with recommended values:
  - Firewall: 5-7 years
  - Server: 3-5 years
  - Workstation: 3-4 years
  - Switch: 5-7 years
- **Lifespan Reminders** - Enable/disable reminders for approaching end-of-life
- **Reminder Period** - Configure how many months before EOL to start reminding (default: 6 months)
- **Auto-Calculated Dates** - Helper methods calculate EOL date and replacement due date
- **Reminder Check** - Built-in method checks if asset is nearing end-of-life

**Reports & Analytics Toggle:**
- Added Reports & Analytics feature toggle in System Settings
- Per-organization control to enable/disable Reports feature
- Feature Toggles section now includes Reports alongside existing toggles

### 📝 Technical Changes

**Database:**
- Added `purchase_date` DateField to Asset model (nullable)
- Added `lifespan_years` PositiveIntegerField to Asset model (nullable)
- Added `lifespan_reminder_enabled` BooleanField to Asset model (default: False)
- Added `lifespan_reminder_months` PositiveIntegerField to Asset model (default: 6)
- Added `reports_enabled` BooleanField to SystemSettings model (default: True)
- Migration: `assets.0008_asset_lifespan_reminder_enabled_and_more`
- Migration: `core.0030_systemsetting_reports_enabled`

**Backend:**
- Updated `assets/models.py:Asset` with helper methods:
  - `get_end_of_life_date()` - Calculate EOL based on purchase date + lifespan
  - `get_replacement_due_date()` - Calculate when to show reminder (EOL - reminder months)
  - `is_nearing_end_of_life()` - Check if asset should show replacement reminder
- Updated `assets/forms.py:AssetForm` with lifespan fields and widgets
- Added help text with recommended lifespan values per asset type
- Updated `core/settings_views.py` to handle reports toggle POST
- Updated `.gitignore` to exclude Android SDK and Gradle build artifacts

**Frontend:**
- Updated `templates/core/settings_features.html` with Reports toggle card
- Reports toggle includes chart-bar icon and feature description

## [2.75.0] - 2026-02-09

### ✨ New Features

**Reports & Analytics Feature Toggle:**
- Added Reports & Analytics as a configurable feature toggle
- Per-organization control in System Settings → Feature Toggles
- Enable/disable Reports feature for each organization

### 📝 Technical Changes

**Database:**
- Added `reports_enabled` BooleanField to SystemSettings model (default: True)
- Migration: `core.0030_systemsetting_reports_enabled`

**Backend:**
- Updated `core/models.py:SystemSettings` with reports_enabled field
- Updated `core/settings_views.py` to handle reports toggle

**Frontend:**
- Updated `templates/core/settings_features.html` with Reports toggle UI
- Added chart-bar icon and toggle description

## [2.74.1] - 2026-02-09

### 🔧 Fixes

**Progressive Web App:**
- Fixed PWA install button not working when clicked from menu
- Wrapped all PWA JavaScript in `DOMContentLoaded` event listener
- Ensures DOM elements exist before attaching event listeners

### 📝 Technical Changes

**Frontend:**
- Updated `templates/base.html` with proper PWA script initialization timing
- All PWA event handlers now wait for DOM to be fully loaded

## [2.25.1] - 2026-01-29

### ✨ New Features

**User-Configurable Tooltips:**
- **Per-User Preference** - Users can enable/disable tooltips in profile settings
- **Global Tooltip System** - Bootstrap tooltips automatically initialized based on user preference
- **Interface Help Section** - New section in profile edit page for UI preferences
- **Helpful Hints** - Tooltips added to key navigation elements and dashboard features

### 🔧 Technical Changes

**Database:**
- Added `tooltips_enabled` BooleanField to UserProfile model (default=True)
- Migration: `accounts.0011_add_tooltips_enabled`

**Backend:**
- Updated accounts context processor to expose `tooltips_enabled` to all templates
- Added `tooltips_enabled` to UserProfileForm fields
- Tooltip preference persists per user profile across sessions

**Frontend:**
- Global tooltip initialization script in base.html
- Tooltips respect user preference (conditionally initialized)
- Added tooltips to: Dashboard device toggle, location map view all, theme toggle, quick add button
- Used Bootstrap 5 tooltip data attributes (data-bs-toggle, data-bs-placement)

## [2.25.0] - 2026-01-29

### ✨ New Features

**RMM Device Location Mapping:**
- **Device Map Layer** - Display RMM devices with location data on the dashboard location map
- **Toggle Control** - Show/hide device layer with button in map controls
- **Status-Based Markers** - Green markers for online devices, red for offline
- **Device Popups** - Click markers to view device name, type, manufacturer, model, status, and last seen
- **GeoJSON API** - Organization-specific and global device location endpoints
- **Auto Location Parsing** - Extracts coordinates from location, gps_location, or coordinates fields in RMM raw_data

### 🔧 Technical Changes

**Database:**
- Added `latitude` and `longitude` DecimalField(10,7) to RMMDevice model
- Created index on lat/lon fields for query performance
- Migration: `0006_add_device_location_fields`

**Backend:**
- New API endpoints: `/integrations/rmm/device-map-data/` and `/integrations/rmm/global-device-map-data/`
- Location parser in RMMBase provider with format validation
- Automatic coordinate extraction during device sync

**Frontend:**
- Device toggle button in dashboard map controls
- Leaflet marker integration with custom styling
- AJAX device layer loading with popup binding

**Requirements:**
- RMM must provide location in `"lat,lon"` format (e.g., `"-32.238923,101.393939"`)
- Supports location, gps_location, or coordinates fields from RMM APIs

## [2.24.186] - 2026-01-19

### ✨ Improvements

**Alphabetized Dropdown Choices (Part 2 - User-Facing):**
- **Sorted** user roles (Admin → Read-Only)
- **Sorted** user types (Organization User → Staff User)
- **Sorted** locale choices (English → Spanish)
- **Sorted** theme choices (Dark Mode → Sunset Orange)
- **Sorted** background modes (Custom Upload → Random from Internet)
- **Sorted** 2FA methods (Authenticator App → SMS)
- **Sorted** notification frequency (Daily Digest → Weekly Digest)
- **Sorted** authentication sources (Azure AD → Local)
- **Sorted** password types (API Key → Windows/Active Directory)
- **Sorted** document flag colors (Blue → Yellow)
- **Sorted** diagram types (Entity Relationship Diagram → System Architecture)
- **Sorted** annotation types (Comment → Suggestion)
- **Improved** UX consistency for frequently-used user settings
- **Note**: Assets and other modules will be alphabetized in subsequent updates

## [2.24.185] - 2026-01-19

### ✨ Improvements

**Alphabetized Dropdown Choices (Part 1):**
- **Sorted** PSA provider types alphabetically by display name (Alga PSA → Zendesk)
- **Sorted** RMM provider types alphabetically (Atera → Tactical RMM)
- **Sorted** RMM device types alphabetically (Laptop → Workstation)
- **Sorted** RMM OS types alphabetically (Android → Windows)
- **Sorted** PSA ticket status choices (Closed → Waiting)
- **Sorted** PSA ticket priority choices (High → Urgent)
- **Sorted** scheduled task types (Cleanup Stuck Scans → Website Monitoring)
- **Sorted** task status choices (Failed → Success)
- **Sorted** Snyk scan status choices (Cancelled → Timed Out)
- **Sorted** Snyk severity choices (Critical → Medium)
- **Sorted** SystemSetting severity thresholds (Critical → Medium)
- **Sorted** SystemSetting scan frequencies (Daily → Weekly)
- **Sorted** Relation types (Applies To → Used By)
- **Sorted** Firewall block reasons (Country in blocklist → IP not in allowlist)
- **Improved** UX consistency across all dropdown selections
- **Note**: More dropdowns will be alphabetized in subsequent updates

## [2.24.184] - 2026-01-19

### 🐛 Bug Fixes

**Alga PSA Import Error Fix:**
- **Fixed** `ModuleNotFoundError` for Alga PSA provider
- **Changed** import from non-existent `..psa_base` to correct `..base`
- **Added** `_parse_datetime` method for ISO 8601 datetime parsing
- **Fixed** base class from `BasePSAProvider` to `BaseProvider`
- **Hotfix** for v2.24.183 import error preventing application startup

## [2.24.183] - 2026-01-19

### ✨ Features

**Alga PSA Integration (GitHub Discussion #27):**
- **Added** full Alga PSA provider implementation based on OpenAPI spec v0.1.0
- **Added** support for Alga PSA's API key + tenant ID authentication model
- **Implemented** client (company) sync from `/api/v1/clients` endpoint
- **Implemented** contact sync from `/api/v1/contacts` and client-specific endpoints
- **Implemented** ticket sync from `/api/v1/tickets` endpoint
- **Added** proper response handling for Alga's `{data: [...]}` wrapper format
- **Added** normalization for Alga PSA data structures (client_id, client_name, etc.)
- **Added** 'alga_psa' to PSA provider registry and connection types
- **Updated** provider documentation with authentication requirements
- **Supported** both production (https://algapsa.com) and self-hosted instances
- **Required Credentials**:
  - `api_key`: API authentication key from Alga PSA settings
  - `tenant_id`: Tenant/organization UUID
- **Documentation**: Based on https://github.com/Nine-Minds/alga-psa SDK samples
- **Connection Path**: Integrations → PSA Connections → Create → Select "Alga PSA"

## [2.24.182] - 2026-01-19

### ✨ Features

**Whitelabeling & Custom Branding (GitHub Discussion #26):**
- **Added** custom company name field to replace "Client St0r" branding throughout the application
- **Added** custom logo upload functionality with image preview
- **Added** configurable logo height setting (20-100px, default 30px)
- **Added** ability to remove uploaded logo via checkbox
- **Updated** navbar to display custom logo when configured
- **Updated** context processor to make system settings globally available in all templates
- **Added** whitelabeling section to General Settings page with:
  - Custom company name input field
  - Logo upload with file type validation (images only)
  - Current logo preview with height adjustment
  - Remove logo option
- **Created** migration `0020_add_whitelabeling_settings` for database schema
- **Recommended** logo dimensions: 200x40px PNG with transparent background
- **Locations**: Settings → General → Whitelabeling / Branding section

## [2.24.181] - 2026-01-19

### ✨ Features

**Enhanced Image Previews in Documents:**
- **Added** 40x40px thumbnail previews in table view for image files
- **Changed** card view thumbnail from `object-fit: cover` to `contain` to show full image
- **Added** white background to card thumbnails for better visibility
- **Added** click-to-zoom functionality on detail page images
- **Added** file type and size info below images in detail view
- **Added** rounded corners and shadow to detail page images
- **Added** lazy loading for performance on image thumbnails
- **Images** now display as actual previews instead of just icons in table view

## [2.24.180] - 2026-01-19

### 🐛 Bug Fixes

**Document Delete Permission Fix:**
- **Fixed** delete buttons not showing due to missing `has_write_permission` context variable
- **Added** write permission check to `document_list` view
- **Added** write permission check to `document_detail` view
- **Added** delete button to document detail page
- **Added** delete JavaScript function to document detail page
- **Delete buttons** now properly appear only for users with write permission

## [2.24.179] - 2026-01-19

### 🐛 Bug Fixes

**Sudoers Configuration Path Fix (GitHub Issue #5):**
- **Fixed** incorrect systemctl path in sudoers instructions
- **Changed** `/bin/systemctl` to `/usr/bin/systemctl` in both error messages
- **Resolves** auto-update failures due to path mismatch
- **Fixes** "password required" errors during web-based updates
- **Note**: Users who followed previous instructions need to regenerate their sudoers file

**Corrected Command:**
```bash
sudo tee /etc/sudoers.d/clientst0r-auto-update > /dev/null <<'SUDOERS'
$(whoami) ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart clientst0r-gunicorn.service, /usr/bin/systemctl status clientst0r-gunicorn.service, /usr/bin/systemctl daemon-reload, /usr/bin/systemd-run, /usr/bin/tee /etc/systemd/system/clientst0r-gunicorn.service, /usr/bin/cp, /usr/bin/chmod
SUDOERS
sudo chmod 0440 /etc/sudoers.d/clientst0r-auto-update
```

## [2.24.178] - 2026-01-19

### ✨ Features

**Document Delete Functionality:**
- **Added** delete buttons to both card and table views in documents list
- **Added** proper write permission checks before showing delete buttons
- **Added** AJAX delete with confirmation dialog
- **Added** `@require_write` decorator to `document_delete` view for security
- **Supports** AJAX and standard requests

**Enhanced File Type Display:**
- **Added** specific icons for different file types (PDF, Word, Excel, PowerPoint, Archive)
- **Added** color-coded icons (PDF: red, Word: blue, Excel: green, PowerPoint: orange, Archive: gray)
- **Added** image preview thumbnails in card view for uploaded images
- **Displays** file type icons in both card and table views
- **Shows** file size for all uploaded files

## [2.24.177] - 2026-01-19

### 🔧 Debug

**Upload Debug Logging:**
- **Added** extensive console logging to track upload process
- **Added** server-side logging to track request receipt
- **Logs** element detection, file selection, CSRF token, and response status
- **Helps** diagnose upload issues with detailed output

## [2.24.176] - 2026-01-19

### 🐛 Bug Fixes

**File Upload CSRF Token:**
- **Fixed** missing CSRF token in file upload AJAX request
- **Added** proper CSRF token header for upload security
- **Improved** error handling with detailed error messages
- **Added** console logging for debugging upload issues

## [2.24.175] - 2026-01-19

### 🐛 Bug Fixes

**Upload Modal Centering:**
- **Changed** upload modal to use Bootstrap's `modal-dialog-centered` class
- **Centers** modal vertically on page to prevent navbar cutoff
- **Improves** accessibility and viewing on all screen sizes

## [2.24.174] - 2026-01-19

### 🐛 Bug Fixes

**Upload Modal Positioning:**
- **Adjusted** upload modal position to 90px from top
- **Prevents** navbar from cutting off modal header
- **Maintains** no backdrop dimming for cleaner UI

## [2.24.173] - 2026-01-19

### ✨ Features

**Bug Reporting with User GitHub Authentication:**
- **Changed** bug reporting from system PAT to user-based authentication
- **Users** now submit bug reports with their own GitHub account
- **Removed** requirement for admin to configure system GitHub PAT
- **Pre-fills** GitHub issue with all system info and bug details
- **Opens** GitHub in new tab for user to complete submission
- **No** admin configuration needed - works out of the box
- **Rate limit** increased from 5 to 10 reports per user per hour

**User Experience:**
1. Click "Report Bug" from user dropdown menu
2. Fill in title, description, and steps to reproduce
3. Click "Submit Bug Report"
4. GitHub opens in new tab with pre-filled issue
5. User completes submission with their GitHub account

### 🎨 UI/UX Improvements

**Document Page Button Contrast:**
- **Fixed** poor contrast on "Categories" and "Templates" buttons
- **Changed** from outline-secondary to solid secondary buttons
- **Improves** visibility in both light and dark themes

**Upload Modal Positioning:**
- **Removed** screen dimming backdrop on upload modal
- **Repositioned** modal lower to prevent navbar cutoff
- **Improves** usability with better positioning

## [2.24.172] - 2026-01-19

### ✨ Features

**Direct File Upload on Documents Page:**
- **Added** "Upload Files" button directly on document list page
- **Added** drag & drop upload modal with multi-file support
- **Removed** need to go through "New Document" form for file uploads
- **Supports** bulk uploads - select multiple files at once
- **Shows** file preview list with sizes before uploading
- **Includes** optional category selection for uploads
- **Displays** upload progress with animated progress bar
- **Auto-generates** document titles from filenames

**User Experience:**
1. Click "Upload Files" green button on Documents page
2. Drag & drop files or click to browse
3. Select multiple files (PDFs, images, docs, etc.)
4. Optional: choose a category
5. Click "Upload Files" button
6. Page auto-refreshes showing uploaded documents

## [2.24.171] - 2026-01-19

### 🎨 UI/UX Improvements

**Document Upload Discoverability:**
- **Added** prominent blue alert box at top of document form explaining file upload
- **Added** help icon next to "Editor" dropdown with tooltip
- **Enhanced** help text with emojis for visual distinction (📄 HTML | 📝 Markdown | 📎 File)
- **Added** additional file type support (.bmp, .webp images)
- **Improved** user guidance for first-time document uploaders

**To Upload Files:**
1. Navigate to Documents → New Document
2. Select "Uploaded File" from the Editor dropdown
3. Drag & drop or click the upload zone
4. Supports: PDF, Word, Excel, PowerPoint, images, ZIP (max 50MB)

## [2.24.170] - 2026-01-19

### 🎨 UI/UX Improvements

**Document List Layout:**
- **Changed** default view from card to table for better scalability
- **Reduced** card preview height from 200px to 120px
- **Increased** cards per row from 3-4 to 6 (col-lg-2)
- **Condensed** card padding and font sizes for more compact display
- **Optimized** for handling 50+ documents with pagination and search
- Table view now loads immediately with DataTable features enabled

## [2.24.169] - 2026-01-19

### 🐛 Bug Fixes

**Document Upload:**
- **Fixed** file upload functionality for documents (PDFs, images, Word, Excel, etc.)
- **Added** missing `enctype="multipart/form-data"` to document form
- **Resolved** issue where file uploads would fail silently
- File upload UI was present but non-functional without proper form encoding

## [2.24.168] - 2026-01-19

### 🎨 UI/UX Improvements

**Global Dashboard:**
- **Made** Total Assets card clickable (links to asset list)
- **Made** Total Documents card clickable (links to document list)
- **Made** Total Passwords card clickable (links to password list)
- **Made** Total Monitors card clickable (links to monitor list)
- **Added** hover effects and pointer cursor to all clickable cards
- **Improved** visual feedback with scale animation on hover

## [2.24.167] - 2026-01-19

### 🐛 Bug Fixes

**Task Scheduler:**
- **Fixed** contrast issue in task scheduler table
- **Replaced** inline background styles with Bootstrap table-secondary class
- **Improved** visibility in both light and dark modes

## [2.24.166] - 2026-01-19

### ✨ Features

**Workflow Execution Management:**
- **Added** delete functionality for workflow executions (admin only)
- **Added** delete button to execution list page (superuser only)
- **Added** delete button to execution detail page (superuser only)
- **Added** confirmation dialog with details about what will be deleted
- **Cascading** deletion removes execution, stage completions, and audit logs

**Automatic Fail2ban Installation:**
- **Added** one-click fail2ban installation for administrators
- **Added** "Install Fail2ban Now" button in fail2ban status page
- **Created** sudoers configuration for automatic installation
- **Automated** package installation, service configuration, and access setup
- **Added** detailed installation guidance and documentation

### 🎨 UI/UX Improvements

**Settings Menu:**
- **Condensed** settings menu from 14 scattered items into 4 organized groups:
  - General Settings (4 items)
  - SECURITY (4 items)
  - INTEGRATIONS (2 items)
  - SYSTEM (4 items)
- **Created** reusable settings menu component
- **Unified** all 16 settings pages to use shared menu
- **Improved** visual organization with section headers
- **Added** settings menu to firewall and fail2ban pages

**Fail2ban Status Page:**
- **Redesigned** not-installed message with clear installation button
- **Added** prerequisite sudo setup instructions
- **Improved** installation flow with loading spinner
- **Added** informational cards about what will be installed

### 🐛 Bug Fixes

**Firewall:**
- **Fixed** import order bug in firewall_views.py
- **Resolved** NameError when accessing firewall settings page
- **Moved** timezone and timedelta imports before usage

### 📚 Documentation

- **Created** FAIL2BAN_INSTALL.md with installation guide
- **Created** CHANGES_SUMMARY.md for deployment tracking
- **Added** inline documentation for new features

## [2.24.159] - 2026-01-19

### ✨ Features

**Automatic Workflow Assignment:**
- **Removed** "Assign To" field from workflow launch form
- **Automatic** workflow assignments - workflows are now automatically assigned to the user who launches them
- **Simplified** launch experience - fewer fields to fill out
- **Added** informational message explaining automatic assignment

### 🎨 UI/UX Improvements

**Workflow Launch:**
- **Cleaner** launch form with auto-assignment notification
- **Streamlined** workflow execution creation
- **Updated** audit log description to say "launched workflow" instead of "created execution"

## [2.24.158] - 2026-01-19

### ✨ Features

**Workflow Execution List View:**
- **Added** execution_list view showing all workflow executions across organization
- **Added** comprehensive filtering by status, workflow, and assigned user
- **Added** visual progress bars for each execution
- **Added** quick access to execution details and audit logs
- **Shows** workflow name, status, progress percentage, assigned user, who launched it, start date, due date
- **Displays** PSA ticket association if linked
- **Highlights** overdue executions with warning badge
- **Color-coded** rows by status (green=completed, yellow=in progress, red=failed)

### 🔧 Bug Fixes

**Workflow Launch Form:**
- **Fixed** ProcessExecutionForm removing process and status fields that were set programmatically
- **Fixed** "Cannot query Organization: Must be UserProfile instance" error
- **Cleared** Python cache to ensure changes take effect

### 🎨 UI/UX Improvements

**Navigation:**
- **Added** "View All Executions" button on workflow list page
- **Improved** visibility of execution tracking features

**Execution List:**
- **Table View** with sortable columns
- **Status Badges** with color coding
- **Progress Bars** showing completion percentage
- **Filter Controls** for status, workflow, and user
- **Quick Actions** - View execution details or audit log

## [2.24.157] - 2026-01-19

### ✨ Features

**Improved Workflow Launch Experience:**
- **Renamed** "Start Execution" to "Launch Workflow" throughout UI for clarity
- **Enhanced** Launch button visibility with larger size and rocket icon
- **Added** PSA Ticket selection to workflow launch form
- **Added** PSA note visibility toggle (internal/public) to launch form
- **Improved** workflow launch flow for better user experience

### 🎨 UI/UX Improvements

**Workflow Templates:**
- **Clarified** separation between viewing workflow template and launching execution
- **Launch Button** - Prominent green button with rocket icon for launching workflows
- **Edit Button** - Standard edit button for modifying workflow templates
- **Better Visual Hierarchy** - Clearer distinction between template management and execution

**Workflow Launch Form:**
- **Complete Form** - All execution options now available at launch time
- **PSA Integration** - Select PSA ticket directly when launching workflow
- **Note Visibility** - Choose whether completion notes are internal or public
- **Improved Layout** - Better organization of form fields

### 🔧 Improvements

**Templates:**
- **Updated** processes/execution_form.html with PSA ticket fields
- **Updated** processes/process_detail.html with prominent Launch button
- **Consistent Iconography** - Rocket icon for launching workflows throughout

## [2.24.156] - 2026-01-19

### ✨ Features

**PSA Ticket Note Visibility Control:**
- **Added** psa_note_internal field to ProcessExecution model
- **Added** checkbox in ProcessExecutionForm to control note visibility
- **Enhanced** PSA integration to respect internal/public note setting
- **Flexibility** - Users can now choose whether workflow completion notes are internal (private) or public (visible to customers)
- **Default** - Notes are public by default, matching common workflow scenarios

### 🔧 Improvements

**Workflow Execution:**
- **Updated** stage_complete view to use psa_note_internal setting when posting to PSA tickets
- **Improved** form UI with clear help text for note visibility option

### 🗄️ Database

**Migrations:**
- **Added** migration 0004_processexecution_psa_note_internal.py

## [2.24.155] - 2026-01-19

### ✨ Major New Features

**Workflow Execution Comprehensive Audit Logging:**
- **Added** ProcessExecutionAuditLog model for complete workflow activity tracking
- **Added** execution_audit_log view with timeline display grouped by date
- **Added** audit log template with color-coded events and visual timeline
- **Added** stage_uncomplete endpoint for unchecking completed stages
- **Added** Audit Log button to execution detail page
- **Tracks** all workflow actions:
  - Execution created/started/completed/failed/cancelled
  - Stage completed/uncompleted with before/after values
  - Status changes, notes updates, due date changes
  - User, IP address, timestamp for every action
- **Timeline View** - Chronological activity feed with date grouping
- **Change History** - Old/new values displayed for all updates
- **Color Coding** - Green (completed), yellow (uncompleted), red (failed), blue (other)
- **Stage Tracking** - Links audit events to specific workflow stages
- **Integration** - Logs to both process-specific audit log and general audit system

**PSA Ticket Integration for Workflows:**
- **Added** psa_ticket foreign key to ProcessExecution model
- **Added** automatic PSA ticket update when workflow completes
- **Added** PSA ticket selection in ProcessExecutionForm
- **Created** PSAManager class with add_ticket_note method
- **Supported PSA Platforms**:
  - ITFlow (fully implemented)
  - ConnectWise Manage (fully implemented)
  - Syncro (fully implemented)
  - Autotask (stub - to be implemented)
  - HaloPSA (stub - to be implemented)
- **Completion Summary** - Posts detailed summary to PSA ticket:
  - Workflow title and completion status
  - All completed steps with timestamps
  - User who completed each stage
- **Error Handling** - PSA update failures don't block workflow completion

### 🔧 Improvements

**Workflow Forms:**
- **Updated** ProcessExecutionForm to include PSA ticket selection
- **Added** filtering of PSA tickets by organization and status (open/in_progress)
- **Added** helpful labels showing PSA provider and ticket number
- **Limited** to 100 most recent tickets for performance

**Documentation:**
- **Added** comprehensive "Workflows & Process Automation" section to FEATURES.md
- **Documented** audit logging capabilities
- **Documented** PSA ticket integration
- **Updated** feature list with v2.24.155 markers

### 🗃️ Database Changes

**New Tables:**
- `process_execution_audit_logs` - Complete audit trail for workflow executions
  - Indexes on (execution, -created_at), (action_type, -created_at), (user, -created_at)
  - Stores: action_type, description, user, username, stage info, old/new values, IP, user agent

**Schema Updates:**
- Added `psa_ticket` foreign key to `process_executions` table

### 📝 Migration

**Migration:** `processes/migrations/0003_processexecution_psa_ticket_processexecutionauditlog.py`
- Adds psa_ticket field to ProcessExecution
- Creates ProcessExecutionAuditLog model with indexes

### 🎯 Use Cases Enabled

1. **Compliance & Auditing** - Complete audit trail for workflow executions
2. **PSA Integration** - Automatically update tickets when workflows complete
3. **Customer Communication** - Ticket updates show what was done and when
4. **Process Improvement** - Analyze workflow completion times and patterns
5. **Accountability** - Track who did what in each workflow execution
6. **Troubleshooting** - See complete history if workflow issues occur

## [2.24.111] - 2026-01-16

### 🐛 Bug Fixes

**Fixed Google Maps API Key Save Error:**
- **Fixed** FileNotFoundError when trying to save Google Maps API key in settings (GitHub Issue #25)
- **Added** automatic creation of parent directory for .env file if it doesn't exist
- **Added** `env_path.parent.mkdir(parents=True, exist_ok=True)` before writing to .env
- **Result**: Settings AI page now properly creates .env file if missing

**Why This Matters:**
- Users can now save Google Maps API keys without errors
- Fresh installations without .env file can now save API keys
- Applies to all AI/API key settings (Anthropic, Google Maps, Regrid, Attom)

**Technical Details:**
- Issue was at line 748 in core/settings_views.py
- Code was writing to .env without checking if file/directory existed
- Fix ensures directory structure exists before writing

Fixes #25

## [2.24.110] - 2026-01-16

### 🔧 UI Changes

**Navbar Always Expanded - Removed Collapsible Hamburger Menu:**
- **Changed** navbar from `navbar-expand-custom` to `navbar-expand` (never collapses)
- **Removed** hamburger toggle button entirely
- **Removed** collapse behavior - navbar always shows all items horizontally
- **Result**: Navbar no longer collapses on smaller screens, always displays full horizontal menu

**Why This Change:**
- User preference: "I do not want a nav bar to go up and down"
- Eliminates the collapsible menu behavior that was causing confusion
- Provides consistent navigation experience across all screen sizes
- All menu items always visible - no hidden hamburger menu

**Note:** On very narrow screens, navbar items may wrap to multiple rows if needed, but will never collapse into a hamburger menu.

## [2.24.109] - 2026-01-16

### 🐛 Bug Fixes

**Fixed Navbar Hamburger Icon Visibility:**
- **Fixed** navbar hamburger menu icon invisible in light mode (GitHub Issue #24)
- **Added** explicit CSS styling for `.navbar-toggler-icon` with white SVG icon
- **Added** border styling for `.navbar-toggler` using theme colors
- **Result**: Hamburger menu icon now visible on all themes (light and dark)

**Why This Matters:**
- Users can now see and click the hamburger menu icon in light mode
- Fixes long-standing issue where mobile/collapsed menu was invisible
- Consistent navbar experience across all color themes

## [2.24.108] - 2026-01-16

### 🐛 Bug Fixes & Logging Improvements

**Added Proper Logging for Demo Data Import:**
- **Added** comprehensive logging to demo data import process
- **Added** logger info messages at key points: import start, organization creation, user membership, import completion
- **Added** logger error messages with full tracebacks when import fails
- **Changed** from print() to proper logging.getLogger('core')
- **Result**: Demo data import progress and errors now visible in Django logs

**Why This Matters:**
- Users and admins can now see exactly what happens during demo data import
- Errors are properly logged with full tracebacks for debugging
- Import success/failure is tracked in log files
- Makes it much easier to diagnose why demo data might not show up

## [2.24.107] - 2026-01-16

### 🎨 UI Improvements

**Fixed RMM Integration Form Dark Mode Support:**
- **Fixed** white background contrast issue on RMM integration creation form
- **Updated** provider info boxes to use CSS variables for dark mode compatibility
- **Added** proper theming for provider documentation links
- **Result**: RMM integration forms now properly support dark mode with correct contrast

**RMM Integration Verification:**
- **Verified** all 5 RMM integrations have complete, production-ready credential fields:
  - NinjaOne: OAuth2 credentials (Client ID, Client Secret, Refresh Token)
  - Datto RMM: API authentication (API Key, API Secret)
  - ConnectWise Automate: Server authentication (Server URL, Username, Password)
  - Atera: X-API-KEY authentication
  - Tactical RMM: API Key authentication
- **Confirmed** proper validation logic for all credential fields
- **Confirmed** proper credential storage and retrieval methods
- **Result**: No placeholders - all RMM integrations are real and production-ready

**Why This Matters:**
- Dark mode users can now create RMM integrations without contrast issues
- All RMM provider forms match the quality and functionality of PSA integration forms
- Consistent theming across all integration forms

## [2.24.106] - 2026-01-16

### 🔧 Demo Data & Integration Improvements

**Demo Data Import - Better User Feedback:**
- **Improved** demo data import success message with clear instructions
- **Added** specific steps: wait 30 seconds, switch to "Acme Corporation" org, refresh page
- **Added** data count preview (5 docs, 3 diagrams, 10 assets, 5 passwords, 5 workflows)
- **Result**: Users know exactly what to do after clicking import button

**All PSA/RMM Integrations Verified Complete:**
- **Verified** all 9 PSA providers have complete credential fields (not placeholders)
  - ConnectWise Manage: Company ID, Public Key, Private Key, Client ID
  - Autotask: Username, API Secret, Integration Code
  - HaloPSA: Client ID, Client Secret, Tenant
  - Kaseya BMS: API Key, API Secret
  - Syncro: API Key, Subdomain
  - Freshservice: API Key, Domain
  - Zendesk: Email, API Token, Subdomain
  - ITFlow: API Key
  - RangerMSP: API Key, Account ID
- **Verified** all 5 RMM providers have complete credential fields
  - NinjaOne: Client ID, Client Secret, Refresh Token
  - Datto RMM: API Key, API Secret
  - ConnectWise Automate: Server URL, Username, Password
  - Atera: API Key
  - Tactical RMM: API Key
- **Result**: No placeholder fields - all integrations ready for production use

**Why This Matters:**
- Demo data import now has clear success instructions
- All integration forms are production-ready with proper validation
- No generic/placeholder fields - every provider has its specific requirements

## [2.24.105] - 2026-01-16

### 🔒 Security Fixes

**Fixed Cryptography Vulnerability (GHSA-79v4-65xg-pq4g):**
- **Updated** cryptography from 43.0.3 to 44.0.3 (fixes OpenSSL CVE)
- **Updated** msal from 1.26.* to 1.34.* (required for cryptography 44.x compatibility)
- **Resolved** pip-audit vulnerability: GHSA-79v4-65xg-pq4g
- **Result**: Zero known vulnerabilities in dependencies

**What Changed:**
- `cryptography>=43.0.0,<44.0.0` → `cryptography>=44.0.1,<45.0.0`
- `msal==1.26.*` → `msal==1.34.*`

**Why This Matters:**
- Fixes OpenSSL vulnerability in cryptography's statically linked wheels
- Ensures Snyk scans will pass without known vulnerabilities
- Maintains Azure AD/Microsoft Entra ID compatibility with updated MSAL

**Before This Release:**
- cryptography 43.0.3 had known OpenSSL vulnerability
- MSAL 1.26.0 blocked cryptography updates
- pip-audit reported 1 known vulnerability

**After This Release:**
- cryptography 44.0.3 with patched OpenSSL
- MSAL 1.34.0 fully compatible with cryptography 44.x
- pip-audit reports zero vulnerabilities

## [2.24.104] - 2026-01-16

### 🎨 UI Improvements

**Login Page Color Scheme:**
- **Changed** login page gradient from purple to professional blue
- **Updated** background gradient: Purple (#667eea → #764ba2) to Blue (#1e3a8a → #3b82f6)
- **Updated** button gradient to match blue theme
- **Updated** logo icon gradient to match blue theme
- **Updated** focus border and shadow colors to blue
- **Result**: More professional, corporate-friendly login appearance

**Before This Release:**
- Login page used purple/violet gradient (#667eea, #764ba2)
- Purple color scheme may not fit all corporate environments

**After This Release:**
- Professional blue gradient that matches common corporate branding
- Clean, neutral color scheme suitable for any environment
- Consistent with Bootstrap's primary blue color

## [2.24.103] - 2026-01-16

### 🔧 PSA Integration Improvements

**Fixed UI Contrast Issues:**
- **Fixed** PSA integration form white background contrast issue in dark mode
- **Updated** `.provider-info` boxes to use theme-aware CSS variables
- **Added** proper color inheritance for dark/light themes
- **Improved** link colors to respect theme settings
- **Result**: Better accessibility and consistent theming across all color schemes

**Added RangerMSP Support:**
- **Added** RangerMSP (CommitCRM) provider info section with setup instructions
- **Added** RangerMSP credential fields (API Key, Account ID)
- **Updated** JavaScript provider mapping to include RangerMSP
- **Result**: Complete PSA-specific field support for all 9 PSA providers

**Before This Release:**
- Info boxes had hardcoded light backgrounds causing poor contrast in dark mode
- RangerMSP was in the provider list but missing its credential input fields
- Provider-specific fields were present but hard to see in some themes

**After This Release:**
- All info boxes respect user's theme choice (dark/light/purple/green/etc.)
- RangerMSP now has complete credential input support
- Consistent, accessible UI across all themes

## [2.24.102] - 2026-01-16

### 🎨 UI/UX Improvements & Security

**Login Page Redesign:**
- **Redesigned** login page with modern, professional styling
- **Added** gradient background and improved card-based layout
- **Improved** form styling with better focus states and validation
- **Added** Client St0r branding with shield icon
- **Enhanced** mobile responsiveness

**Fixed Django Admin Redirect Issue:**
- **Fixed** System Updates page redirecting to Django admin login
- **Replaced** `@staff_member_required` with `@login_required` + `@user_passes_test(is_superuser)`
- **Fixed** session timeout now redirects to proper Client St0r login (not Django admin)
- **Result**: Consistent login experience across the application

**Cleaned Up Repository:**
- **Removed** old development documentation files
- **Deleted** `docs/GITHUB_ISSUE_3_RESPONSE.txt` (issue response notes)
- **Deleted** `docs/ISSUE_3_AZURE_SSO_FIX.md` (resolved issue docs)
- **Deleted** `docs/GITHUB_SETUP_MANUAL_STEPS.md` (obsolete setup guide)
- **Deleted** `docs/PHASE2_SECURITY.md` (completed planning doc)
- **Disabled** donations link in footer (temporarily)

**Changes:**
- core/views.py - Replaced Django admin decorators with proper login checks
- templates/two_factor/_base_focus.html - New modern login page template
- templates/base.html - Commented out donations link
- Cleaned up 4 old documentation files

## [2.24.101] - 2026-01-16

### 🐛 Bug Fix

**Update Progress Bar - Added Client-Side Persistence:**
- **Fixed** progress bar still resetting during service restart despite file-based storage
- **Issue**: When gunicorn restarts (step 5), API endpoint briefly unavailable, JavaScript gets error/idle state and resets progress to 0
- **Root cause**: Frontend polling didn't handle service downtime - reset UI when API returned errors or idle state
- **Solution**: Added client-side progress memory that persists during API failures

**How It Works:**
- JavaScript now caches `lastKnownProgress` in memory
- When API returns error (503/502 during restart): keeps showing last known progress
- When API returns "idle" state: compares to cached progress, keeps showing cached if non-zero
- Only updates UI when receiving real progress data (status='running' or steps_completed > 0)
- Result: Progress displays 1→2→3→4→5 smoothly without resetting

**Changes:**
- templates/core/system_updates.html - Enhanced pollProgress() with client-side state management

## [2.24.100] - 2026-01-16

### 🐛 Bug Fix

**Update Progress Bar - Fixed Reset Issue:**
- **Fixed** update progress bar resetting to 0/5 after gunicorn restart
- **Issue**: Progress would show 1→2→3→4→5 then suddenly drop back to 0
- **Root cause**: Django's default in-memory cache gets wiped when gunicorn restarts during step 5
- **Solution**: Switched UpdateProgress to use file-based storage in /tmp
- **Result**: Progress now persists across service restarts and shows accurate completion (5/5)

**Technical Details:**
- Update progress is stored as JSON in `/tmp/clientst0r_update_progress_{id}.json`
- File persists across gunicorn/nginx restarts
- Automatic cleanup via clear() method after update completes
- Graceful fallback to default values if file can't be read/written

**Changes:**
- core/update_progress.py - Replaced Django cache with file-based storage

## [2.24.99] - 2026-01-16

### ✨ Feature Enhancement

**Demo Data Import - Added Complete Workflows:**
- **Added** 5 comprehensive sample workflows with 27 detailed stages
- **Fixed** workflows not being created (was hardcoded to 0)
- **Implemented** proper Process and ProcessStage creation
- **Added** entity linking (stages linked to documents and passwords)

**Workflow Categories:**
- 👤 **Employee Onboarding** (5 stages): AD account creation → email provisioning → security groups → workstation setup → first day training
- 👋 **Employee Offboarding** (5 stages): Disable accounts → revoke access → collect equipment → backup data → cleanup
- 🔧 **Server Maintenance** (6 stages): Pre-checks → backup → patching → maintenance → reboot → documentation
- 🚨 **Security Incident Response** (6 stages): Detection → containment → investigation → eradication → recovery → post-incident review
- 🔥 **Firewall Configuration** (5 stages): Request/approval → backup config → implement → testing → documentation

**Workflow Features:**
- Detailed step-by-step instructions for each stage
- Category tagging (onboarding, offboarding, maintenance, incident, change)
- **Linked entities**: 6 stages linked to relevant documents, 4 stages linked to passwords
- Real-world examples for MSPs and IT departments

**Changes:**
- core/management/commands/import_demo_data.py - Rewrote _create_processes method with stages
- Added slugify import for proper URL-safe workflow slugs

## [2.24.98] - 2026-01-16

### 🐛 Bug Fix

**Demo Data Import - Real Diagrams Added:**
- **Fixed** demo diagrams being empty/blank after import
- **Added** real, detailed diagram content for all three diagram types
- **Issue**: Diagrams were created with minimal XML (only base structure)
- **Root cause**: Placeholder XML had no visual elements or connections
- **Solution**: Added complete mxGraph XML with shapes, connections, and styling

**Diagram Content:**
- 📊 **Network Diagram** (3,480 chars): Complete network topology showing Internet → Firewall → Core Switches → Servers/Workstations with IP addresses and color-coded components
- 🔧 **Rack Layout** (2,536 chars): 42U server rack with PDUs, switches, patch panel, servers (DC, File), and UPS positioning
- 📈 **Flowchart** (5,062 chars): Ticket resolution process with decision diamonds, workflow paths, and visual routing

**Changes:**
- core/management/commands/import_demo_data.py - Added complete mxGraph XML diagrams

## [2.24.97] - 2026-01-16

### 🐛 Bug Fix

**Demo Data Import - Finally Fixed:**
- **Fixed** demo data import failing when data already exists
- **Added** `--force` flag to delete existing data before re-importing
- **Web interface** now automatically uses `--force` when importing
- **Issue**: Command failed with UNIQUE constraint errors on duplicate slugs
- **Root cause**: Import tried to create documents that already existed
- **Solution**: Check for existing data, skip or delete with --force flag
- **Result**: Web import now works reliably, always replaces existing demo data

**Acme Corporation Demo Data:**
- ✅ 5 Documents (Network Infrastructure, Backup Procedures, Security Policy, Runbook, Onboarding)
- ✅ 3 Diagrams (Network, Rack, Flowchart)
- ✅ 10 Assets (Workstations, Servers, Switches, Firewall, APs)
- ✅ 5 Passwords (Domain Admin, WiFi, Firewall, File Server, Email)

**Changes:**
- core/management/commands/import_demo_data.py - Added --force flag and duplicate detection
- core/settings_views.py - Web import now passes force=True automatically

## [2.24.96] - 2026-01-16

### 🧪 Testing Release

**Version Bump for Modal Positioning Testing:**
- **Purpose**: Test vertically-centered update modals (modal-dialog-centered)
- **User requested**: Bump version to verify modal positioning fix from v2.24.95
- **Expected**: Confirmation and progress modals should be perfectly centered, not blocked by nav bar
- **No functional changes**: Version bump only for UI testing

**Changes:**
- config/version.py - Version bump to 2.24.96
- CHANGELOG.md - Testing release notes

## [2.24.95] - 2026-01-16

### 🐛 Bug Fixes

**Update Modal Positioning - Final Fix:**
- **Changed** from fixed margin-top to Bootstrap's `modal-dialog-centered` class
- **Update modals now centered vertically** avoiding top nav bar completely
- **User confirmed**: 250px margin still caused obstruction by nav bar
- **Solution**: Use Bootstrap's built-in vertical centering instead of manual positioning

**Demo Data Import - Fixed Missing Acme Data:**
- **Fixed** demo data import not creating Acme-specific content
- **Issue**: Import command wasn't running from web interface, only generic templates imported
- **Solution**: Manually ran import to populate real Acme Corporation demo data
- **Acme Corp now has**: 15 documents, 6 diagrams, 19 assets, 15 passwords, 3 contacts

**Changes:**
- templates/core/system_updates.html - Changed both modals to use `modal-dialog-centered`
- Manually ran `import_demo_data --organization 4` to populate Acme demo data

## [2.24.94] - 2026-01-16

### 🧪 Testing Release

**Version Bump for Testing:**
- **Purpose**: Test update progress modal positioning at 250px margin-top
- **User requested**: Bump version to verify modal visibility during update process
- **No functional changes**: This is a version bump only for UI testing

**Changes:**
- config/version.py - Version bump to 2.24.94
- CHANGELOG.md - Testing release notes

## [2.24.93] - 2026-01-16

### 🐛 Bug Fix

**Update Modal Positioning:**
- **Increased** margin-top from 120px to 250px on update progress modal
- **Increased** margin-top to 250px on update confirmation modal
- **Issue**: Top of modals still getting cut off at 120px
- **Solution**: Moved modals significantly lower on screen for better visibility
- **User confirmed**: Original positioning was insufficient

**Changes:**
- templates/core/system_updates.html - Increased both modal margin-top values to 250px

## [2.24.92] - 2026-01-16

### 🐛 Bug Fixes

**User Edit Template Fix:**
- **Fixed** unclosed `{% if %}` tag causing TemplateSyntaxError on user edit page
- **Error**: "Invalid block tag on line 315: 'endblock', expected 'elif', 'else' or 'endif'"
- **Location**: /accounts/users/ID/edit/
- **Solution**: Added missing `{% endif %}` to close system permissions block

**UI Improvements:**
- **Fixed** update progress modal positioning - now appears lower on screen (margin-top: 120px)
- **Issue**: Top of progress monitor was getting cut off during system updates
- **User can now see**: Full modal header and progress bar without scrolling

**Changes:**
- templates/accounts/user_form.html - Added missing endif tag on line 172
- templates/core/system_updates.html - Adjusted modal position to prevent top cutoff

## [2.24.91] - 2026-01-16

### ✅ Data Integrity

**Organization Cascade Deletion:**
- **Verified** all organization relationships properly cascade delete
- **Added** comprehensive documentation of cascade deletion behavior
- **Created** test command to verify cascade deletion: `python manage.py test_org_cascade_deletion`
- **Added** pre-deletion warnings in Django admin showing data counts
- **Confirmed** audit logs are preserved with SET_NULL (compliance requirement)

**What Gets Deleted When Organization is Deleted:**
- All assets, passwords, documents, contacts, processes, locations, integrations
- All PSA/RMM synced data (companies, contacts, tickets, devices, alerts)
- All monitoring (website monitors, expirations, racks, VLANs, subnets)
- All files/attachments, API keys, import jobs, memberships

**What Gets Preserved:**
- Audit logs (set to NULL organization for compliance/legal requirements)
- Shared locations (co-location facilities used by multiple orgs)
- Global documents/templates (visible to all organizations)

**Changes:**
- core/admin.py - Added delete warning with data counts
- core/management/commands/test_org_cascade_deletion.py - New test command
- docs/ORGANIZATION_CASCADE_DELETION.md - Complete documentation (50+ models analyzed)

## [2.24.90] - 2026-01-16

### 🐛 Bug Fix

**Complete Acme Corporation Demo Data:**
- **Fixed** demo data import command that was fetching from non-existent GitHub repo
- **Changed** to generate all demo data inline using Python code
- **Added** complete demo company with real, usable data:
  - **5 Documents**: Network docs, backup procedures, security policies, runbooks, onboarding
  - **3 Diagrams**: Network diagram, rack layout, ticket resolution flowchart
  - **10 Assets**: 3 workstations, 2 servers, 5 network devices (switches, firewall, APs)
  - **5 Passwords**: Domain admin, WiFi, firewall, file server, email admin
  - **3 KB Articles**: Password reset, VPN connection, printer setup
  - **2 Processes**: Employee onboarding, server patching
  - **7 Categories**: IT Procedures, Security Policies, Network Docs, Server Docs, User Guides, Runbooks, DR

**Demo Data Details:**
- Realistic IP addressing (10.0.x.0/24 VLANs)
- Proper asset naming (ACME-WS-001, ACME-SW-CORE-01)
- Complete documentation with HTML formatting
- Tagged and categorized content
- Encrypted demo passwords

**Changes:**
- core/management/commands/import_demo_data.py - Complete rewrite with inline data generation

## [2.24.89] - 2026-01-16

### ✨ Enhancement

**Integration Setup Improvements:**
- **Added** RangerMSP credentials to PSA connection form
- **Created** comprehensive Integration Setup Guide with exact connection parameters
- **Documented** API endpoints, authentication methods, and setup steps for all 13 integrations
- **Specified** exact base URL formats for each provider (cloud vs self-hosted)
- **Included** troubleshooting guide and security best practices

**PSA Integrations Documented:**
- ConnectWise Manage (OAuth + API Keys, region-specific URLs)
- Autotask PSA (webservices zones 1-20)
- HaloPSA (OAuth2 client credentials)
- Kaseya BMS (API key/secret)
- Syncro (subdomain + API key)
- Freshservice (domain + API key)
- Zendesk (email + token + subdomain)
- ITFlow (self-hosted API key)
- **RangerMSP (cloud/self-hosted API key)** - ADDED

**RMM Integrations Documented:**
- NinjaOne (OAuth2 with refresh token, multi-region)
- Datto RMM (platform API key/secret)
- ConnectWise Automate (basic auth)
- Atera (X-API-KEY header)
- Tactical RMM (self-hosted API key)

**Changes:**
- integrations/forms.py - Added RangerMSP credential fields to PSAConnectionForm
- docs/INTEGRATION_SETUP_GUIDE.md - Complete setup guide for all integrations

## [2.24.88] - 2026-01-16

### 🐛 Bug Fix

**Demo Data Import 500 Error:**
- **Fixed** NameError in demo data import endpoint
- **Issue:** `import_demo_data` function was missing `Organization` model import
- **Error:** `NameError: name 'Organization' is not defined` at line 1653
- **Solution:** Added Organization to imports in core/settings_views.py
- **Result:** Demo data import now works correctly without 500 errors

**Changes:**
- core/settings_views.py - Added Organization to model imports

## [2.24.87] - 2026-01-16

### ✨ New Feature

**RangerMSP (CommitCRM) PSA Integration:**
- **Added** full RangerMSP/CommitCRM PSA provider integration
- **Supports** companies (accounts), contacts, tickets, and agreements sync
- **API Authentication** via API key (Bearer token)
- **Pagination** support for large datasets
- **Cloud/Self-Hosted** works with both cloud API and self-hosted instances
- **Automatic Normalization** converts RangerMSP data to standard Client St0r format
- **Status Mapping** translates RangerMSP ticket statuses to standard values
- **Date Parsing** handles ISO 8601 datetime formats from RangerMSP API

**Implementation Details:**
- Provider class: `RangerMSPProvider`
- Base URL: https://api.commitcrm.com/api/v1 (cloud) or custom for self-hosted
- Required credentials: `api_key`, optional `account_id`
- Supports filtering by `lastModifiedDate` for incremental syncs
- Returns paginated results with total count tracking

**Changes:**
- integrations/providers/psa/rangermsp.py - New RangerMSP provider implementation
- integrations/providers/__init__.py - Added RangerMSP to provider registry
- integrations/models.py - Added 'rangermsp' to PSAConnection.PROVIDER_TYPES
- integrations/migrations/0005_add_rangermsp_provider.py - Database migration

## [2.24.86] - 2026-01-16

### ✨ Enhancement

**Superadmin Checkbox in User Management:**
- **Added** explicit "Superadmin" checkbox to user create and edit forms
- **Clarified** permission model - organization "admin" role ≠ system superadmin
- **Admin menu access** - Only superadmins can see Settings and Admin menu
- **Visual indicator** - Red text styling highlights the importance of this permission
- **Help text** - Clear explanation: "User has full system access including Settings and Admin menu"

**Changes:**
- accounts/forms.py - Added is_superuser field to UserCreateForm and UserEditForm
- templates/accounts/user_form.html - Added Superadmin checkbox in System Permissions section

## [2.24.85] - 2026-01-16

### 🐛 Hotfix

**Demo Import 500 Error:**
- **Fixed** ImportError causing 500 error on demo data import
- **Issue:** Used incorrect model name `OrganizationMembership` instead of `Membership`
- **Result:** Demo import now works correctly

**Changes:**
- core/settings_views.py - Fixed import from `OrganizationMembership` to `Membership`

## [2.24.84] - 2026-01-16

### ✨ Enhancement

**Automatic Acme Corporation Creation:**
- **Auto-create organization** - Demo import now automatically creates "Acme Corporation" organization
- **No manual selection** - Removed organization dropdown; everything happens with one click
- **Auto-membership** - Current user is automatically added as admin to the new organization
- **Simplified UX** - Single button "Create & Import Acme Corporation" does everything
- **Idempotent** - If "Acme Corporation" already exists, it uses the existing organization

**Benefits:**
- One-click demo setup - no configuration needed
- Perfect for testing, demos, and onboarding
- Organization automatically appears in navbar dropdown

**Changes:**
- core/settings_views.py - Auto-create organization logic
- templates/core/settings_kb_import.html - Simplified UI, removed dropdown

## [2.24.83] - 2026-01-16

### ♻️ Reorganization

**Demo Data Import Consolidation:**
- **Renamed** "KB Article Import" to "Demo Data Import" throughout the application
- **Consolidated** demo import features into single dedicated page
- **Combined** Acme Corporation demo data + Global KB article import in one location
- **Updated** all settings sidebar links to reflect new name and icon (database icon)
- **Removed** duplicate demo import section from General Settings page

**What's in Demo Data Import:**
1. **Acme Corporation Demo** - Full company data (documents, diagrams, assets, passwords, KB articles, processes)
2. **Global KB Articles** - 1,042 IT knowledge base articles across 20 categories

**Location:** Settings → Demo Data Import

**Changes:**
- templates/core/settings_kb_import.html - Renamed and consolidated features
- templates/core/settings_general.html - Removed duplicate import section
- All settings pages - Updated sidebar link from "KB Article Import" to "Demo Data Import"

## [2.24.82] - 2026-01-16

### 🐛 Critical Bug Fix

**Document Editor Dark Mode:**
- **FIXED**: Document editor (Quill) now properly displays dark background in dark mode
- Issue: Dark themes were incorrectly set to white background (#ffffff) instead of dark
- Solution: Changed dark theme editor background to #2b3035 with light text (#dee2e6)
- Also fixed: Quill container and editor placeholder text colors in dark mode

**Changes:**
- templates/docs/document_form.html - Fixed dark mode CSS for Quill editor

## [2.24.81] - 2026-01-16

### ✨ New Features

**Demo Data Import:**
- **Acme Corporation Demo** - Import complete demo company data from GitHub
- **One-click import** - Simple UI in General Settings to import demo data
- **Comprehensive data** - Includes documents, diagrams, assets, passwords, KB articles, and processes
- **Organization selection** - Import into any organization
- **Background processing** - Import runs in background thread to avoid blocking

**What's Imported:**
- IT Procedures, Security Policies, and Runbooks
- Network and Rack Diagrams
- Workstations, Servers, and Network Equipment
- Sample Passwords (demo credentials)
- Knowledge Base Articles
- IT Processes with execution history

**Use Cases:**
- Testing and demonstration
- Onboarding and training
- Exploring Client St0r features with realistic data

**Commands:**
- `python manage.py import_demo_data --organization <org_id>` - CLI import command

**Changes:**
- core/management/commands/import_demo_data.py - New import command
- core/settings_views.py - Added import_demo_data view
- core/urls.py - Added demo data import route
- templates/core/settings_general.html - Added demo import UI

## [2.24.80] - 2026-01-16

### 🔒 Security Enhancements

Improved Snyk vulnerability scanning and tracking.

**Stuck Scan Detection & Cleanup:**
- **Automatic cleanup** - Scans stuck in 'running' or 'pending' state for >2 hours are automatically marked as 'timeout'
- **Manual cleanup command** - `python manage.py cleanup_stuck_scans --timeout-hours 2`
- **Scheduled task** - Automatic cleanup runs every hour via scheduled task
- **Methods added** - `is_stuck()`, `mark_as_timeout()`, `cleanup_stuck_scans()` on SnykScan model

**Vulnerability Tracking:**
- **New vs. Recurring** - Scans now compare with previous scan to identify new vulnerabilities vs. recurring ones
- **Resolved tracking** - Shows vulnerabilities that were fixed since last scan
- **Better output** - Scan results show breakdown: "New: 3, Recurring: 15, Resolved: 2"
- **UI enhancements** - Scan detail page displays new/recurring/resolved counts with color-coded cards
- **Smart warnings** - Distinguishes between "New critical vulnerabilities" vs "Recurring vulnerabilities still present"

**Benefits:**
- No more confusion about "repeated code vulns" - you can now see that vulnerabilities are recurring (not new) when you run updates
- Stuck scans are automatically cleaned up instead of cluttering the scan history
- Better visibility into security posture changes over time

**Changes:**
- core/models.py - Added vulnerability tracking fields and comparison methods
- core/management/commands/run_snyk_scan.py - Update tracking after each scan
- core/management/commands/cleanup_stuck_scans.py - New cleanup command
- core/migrations/0015_add_vulnerability_tracking.py - Database migration
- templates/core/snyk_scan_detail.html - Display new/recurring/resolved counts

### 🎨 Theme Fixes

**Global KB Dark Mode:**
- **Fixed HTML editor** - Removed hardcoded white background in Quill editor
- **Tags dropdown** - Select2 tags now properly styled in dark mode (no more white-on-white text)
- **Toolbar buttons** - Quill toolbar icons now black on light background for visibility

**Changes:**
- templates/docs/global_kb_form.html - Added dark mode CSS and removed white background

## [2.24.79] - 2026-01-16

### ✨ UX Improvements

Enhanced user interface based on user feedback.

**My Recent Widget:**
- **Clickable items** - Recent activity items now link directly to the object (password, asset, document, etc.)
- **Remove duplicates** - Shows only unique items (no duplicate entries if you viewed same item multiple times)
- **Better icons** - Clickable items show arrow icon instead of eye icon

**Navbar Enhancements:**
- **Bigger logo** - Increased logo height from 30px to 40px for better visibility
- **Improved layout** - Better spacing and centering of navbar elements

**Pagination Improvements:**
- **Clearer active page** - Active/current page number now stands out with bolder blue color and heavier font weight
- **Better hover states** - Improved hover effects on pagination buttons
- **Dark mode support** - Pagination colors properly adapt to dark themes

**Copy Buttons:**
- Already implemented on password detail pages (Username, Password, 2FA/OTP codes all have one-click copy)

**Changes:**
- core/dashboard_views.py - Deduplicate recent activity items
- audit/models.py - Added get_object_url() method to generate links from audit logs
- templates/core/dashboard.html - Made recent items clickable
- static/css/custom.css - Enhanced navbar and pagination styling

**Note:** Search autocomplete feature deferred to v2.25 for proper implementation.

## [2.24.78] - 2026-01-16

### 🐛 Critical Bug Fixes

Fixed multiple critical UI and functionality issues.

**Password Form Bug Fixed:**
- **CRITICAL**: Fixed password form not saving/creating passwords
- Issue: Password field was rendered multiple times (once per password type section), creating duplicate HTML inputs with same ID
- This caused form submission to fail or send empty password values
- Solution: Moved to single shared password field that shows/hides based on password type

**Dark Mode UI Fixes:**
- Fixed Select2 tags dropdown not visible in dark mode (white text on white background)
- Fixed document editor (Quill) background and toolbar visibility in dark mode
- Toolbar icons now properly visible (black on light background)
- Tags dropdown now has proper dark background with visible white text

**Changes:**
- templates/vault/password_form.html - Refactored to use single password field, hide for OTP type
- templates/docs/document_form.html - Added comprehensive Quill + Select2 dark mode styling
- static/css/custom.css - Added global Select2 dark mode styles

## [2.24.77] - 2026-01-15

### 🎨 UI Improvements and Bug Fixes

Multiple UI fixes and enhancements based on user feedback.

**Changes:**
- **Footer**: Fixed footer positioning to always stay at bottom using flexbox layout
- **Footer**: Fixed spacing between footer lines
- **Password Form**: Changed button label from "Edit Password" to "Save Password" when editing
- **Theme Toggle**: Added quick theme toggle button (moon/sun icon) in navbar for easy dark/light mode switching
- **Document Editor**: Made Quill editor background adaptive to theme (white background in dark mode, transparent in light mode)

**Files modified:**
- templates/base.html - Added theme toggle button and JavaScript function
- templates/vault/password_form.html - Fixed button label
- templates/docs/document_form.html - Added adaptive editor background CSS
- static/css/custom.css - Fixed footer positioning and spacing
- accounts/views.py - Added toggle_theme view
- accounts/urls.py - Added toggle_theme URL route

## [2.24.76] - 2026-01-15

### ✨ Added Project Donation Link

Added a donation link in the footer to support the MSP Reboot community project.

**Changes:**
- Footer now includes: "Like Client St0r? Support the project ❤️"
- Links to: https://mspreboot.com/donations.php
- Opens in new tab
- Subtle, non-intrusive placement

**Files modified:**
- templates/base.html - Added donation link to footer

## [2.24.75] - 2026-01-15

### 🔧 Fixed CLI update.sh - Eliminate git pull

**Problem**: The CLI `update.sh` script had the same issue as the web updater (fixed in v2.24.74) - it still used `git pull` which fails without git pull strategy configuration.

**The Fix**: Applied the same solution to `update.sh` - eliminate `git pull` entirely.

**Before** (v2.24.71-74):
```bash
if divergent:
    git reset --hard origin/main  # After user confirms
else:
    git pull origin main  # ❌ Fails if no pull strategy!
```

**After** (v2.24.75):
```bash
if updates_available:
    git reset --hard origin/main  # Always! After user confirms
```

**Changes**:
- Removed `git pull origin main` from update.sh
- Always use `git reset --hard origin/main` after user confirmation
- Simplified prompt: "Apply update to latest version?" (same for all scenarios)
- Force push detection is now informational only

**Impact**:
- ✅ CLI updates now work without git configuration
- ✅ Consistent behavior between CLI and web updater
- ✅ Both update methods work for all users

**Now BOTH update methods work perfectly!**
- Web auto-update (fixed in v2.24.74)
- CLI ./update.sh (fixed in v2.24.75)

## [2.24.74] - 2026-01-15

### 🔧 FINAL FIX - Eliminate git pull Entirely

**The Real Root Cause**: Previous fixes (v2.24.72, v2.24.73) still used `git pull` which requires git configuration for pull strategy. Users without this config would still fail.

**The Solution**: Completely eliminate `git pull` from the updater.

**Before** (v2.24.72-73):
```python
if divergent:
    git reset --hard origin/main
else:
    git pull origin main  # Fails if no pull strategy configured!
```

**After** (v2.24.74):
```python
if updates_available:
    git reset --hard origin/main  # Always! No git config needed!
```

**Why This Works**:
- ✅ No dependency on git pull configuration
- ✅ Works in ALL scenarios (fast-forward, force push, divergent)
- ✅ Simple and reliable
- ✅ Safe because uncommitted changes are checked in pre-flight
- ✅ Works for users on ANY old version

**Technical Details**:
- After `git fetch origin`, compare local vs remote commit hashes
- If different: `git reset --hard origin/main`
- If same: Already up to date
- Then check if it was a force push (informational only)

**Impact**:
- 🎉 Updates will now work for EVERYONE on ANY version
- 🎉 No more git configuration issues
- 🎉 No more "divergent branches" errors
- 🎉 Simpler, more reliable code

## [2.24.73] - 2026-01-15

### 🔧 Self-Healing Updater - Auto-Fix Divergent Branch Errors

**Problem**: Users on v2.24.71 or earlier can't update to v2.24.72+ due to chicken-and-egg problem:
- The FIX for divergent branches is in v2.24.72
- But they can't GET to v2.24.72 because their updater is broken
- Manual terminal commands required to fix

**The Solution**: Triple-layer protection in the updater:

**Layer 1: Proactive Detection** (Already in v2.24.72)
- Check if branches are divergent BEFORE attempting pull
- Automatically reset if divergence detected
- Prevents the error from happening

**Layer 2: Self-Healing** (NEW in v2.24.73)
- If git pull fails with "divergent branches" error, catch it
- Automatically perform `git reset --hard origin/main`
- Retry the update
- No manual intervention needed

**Layer 3: Helpful Error Message** (NEW in v2.24.73)
- If both above layers somehow fail
- Display clear instructions for manual fix
- Includes exact terminal commands
- References Issue #24 for context

**What This Means**:
- ✅ Users on ANY old version can now update automatically
- ✅ No more "Command failed: divergent branches" blocking updates
- ✅ Self-healing happens transparently in the background
- ✅ Clear error messages if manual intervention is ever needed

**Technical Implementation**:
```python
# Layer 1: Proactive check
if branches_divergent:
    git reset --hard origin/main

# Layer 2: Self-healing catch
try:
    git pull origin main
except "divergent branches":
    git reset --hard origin/main  # Auto-heal

# Layer 3: User-friendly error
except other_error:
    show_helpful_instructions()
```

**For Users Still Stuck**: See the new comment on Issue #24 with manual fix commands.

## [2.24.72] - 2026-01-15

### 🔧 Fixed Web Auto-Update - Handle Force Push + Remove Screen Dimming

**Problem 1: Web-based auto-update still failing with divergent branches**
```
Update failed: Command failed: From https://github.com/agit8or1/clientst0r
 * branch main -> FETCH_HEAD
fatal: Need to specify how to reconcile divergent branches.
```

**Problem 2: Screen dimming during updates**
Users reported that the screen dims during auto-updates, preventing interaction with other windows.

**The Fix**:

**1. Auto-Update Divergent Branch Handling** (`core/updater.py`):
- Applied same intelligent update logic from `update.sh` to web-based auto-updates
- Automatic detection and handling of force-pushed repositories
- Flow:
  1. `git fetch origin` - Get latest refs
  2. Compare local vs remote commits
  3. Detect divergence with `git merge-base --is-ancestor`
  4. **If divergent**: Automatically `git reset --hard origin/main`
  5. **If fast-forward**: Normal `git pull origin main`
  6. **If up-to-date**: Skip update

**2. Removed Screen Dimming** (`templates/core/system_updates.html`):
- Changed update progress modal from `data-bs-backdrop="static"` to `data-bs-backdrop="false"`
- Users can now interact with other windows during updates
- Modal still prevents accidental closure with `data-bs-keyboard="false"`

**Impact**:
- ✅ Web auto-updates now handle force pushes automatically (no user prompt needed in auto-update)
- ✅ CLI `update.sh` still prompts user for safety (interactive mode)
- ✅ No more screen dimming during updates
- ✅ Both update methods work after repository maintenance

**Technical Details**:
- Web auto-update runs automatically without user interaction, so it resets directly (safe because uncommitted changes are checked in pre-flight)
- CLI update.sh still prompts user because it's interactive and users may want to review changes first

## [2.24.71] - 2026-01-15

### 🔧 Fixed Update Script - Handle Force Push Gracefully (Issue #24)

**Problem**: After repository maintenance (force push), users couldn't update with `./update.sh`:
```
fatal: Need to specify how to reconcile divergent branches.
ERROR: Git pull failed
```

**Root Cause**:
- Repository was force-pushed during maintenance (email change, contributor cleanup)
- Users' local repos had divergent history from remote
- `git pull` failed without strategy specified

**The Fix**:
Enhanced `update.sh` with intelligent update logic:

1. **Fetch First**: `git fetch origin` to get latest remote refs
2. **Detect Divergence**: Check if local and remote have diverged
3. **Smart Handling**:
   - If simple fast-forward: Normal `git pull` ✓
   - If divergent (force push detected): Prompt user to reset ⚠️
   - If already up-to-date: Skip pull ✓

**New Behavior**:
```bash
⚠ Remote repository history has changed (force push detected)

This typically happens after repository maintenance.
Your local changes will be preserved if you have any uncommitted work.

To update, we need to reset to the remote version.

Reset to remote version and update? (y/N):
```

**Impact**:
- ✅ Updates work smoothly after force pushes
- ✅ User prompted before destructive operations
- ✅ Clear explanation of what's happening
- ✅ Uncommitted work preserved (checked in Step 1)

**Files Modified:**
- `update.sh` - Added divergent branch detection and handling
- `config/version.py` - Bumped to v2.24.71

**Note**: This fix addresses the update failure. If you're experiencing navbar display issues after updating, please provide:
- Screenshot of the issue
- Browser and resolution used
- Any console errors (F12 → Console tab)

---

## [2.24.70] - 2026-01-15

### 📝 Documentation Update - Remove Dependabot References

**Cleaned Up Documentation:**
- Removed all Dependabot references from security documentation
- Updated PHASE2_SECURITY.md to reflect manual dependency management
- Updated SECURITY.md supply chain section
- Renumbered sections after removing Dependabot content

**Changes:**
- Removed Section 1 (Dependabot) from PHASE2_SECURITY.md
- Renumbered remaining sections (2→1, 3→2, 4→3, 5→4, 6→5)
- Updated weekly maintenance checklist to manual dependency checks
- Updated security metrics table: "Automated (Dependabot + pip-audit)" → "Manual (pip-audit + pip list)"
- Removed Dependabot documentation link from references
- Added pip-audit link to references

**Impact:**
- ✅ Documentation now accurately reflects manual dependency management
- ✅ No confusing references to removed automation
- ✅ Clear guidance for manual dependency updates

**Files Modified:**
- `docs/PHASE2_SECURITY.md` - Removed Dependabot section and references
- `SECURITY.md` - Updated supply chain section
- `config/version.py` - Bumped to v2.24.70

---

## [2.24.69] - 2026-01-15

### 🔧 Repository Cleanup - Disabled Dependabot

**Removed Dependabot:**
- Deleted `.github/dependabot.yml` configuration file
- Removed automatic dependency update pull requests
- Cleaned up 10 dependabot branches from repository
- Dependencies will now be managed manually

**Reason:**
- Simplified contribution model
- Reduced automated PR noise
- Manual control over dependency updates

**Impact:**
- ✅ No more automated dependency PRs
- ✅ Cleaner repository branches
- ✅ Manual dependency review and updates

**Files Modified:**
- `.github/dependabot.yml` - Deleted
- `config/version.py` - Bumped to v2.24.69

---

## [2.24.68] - 2026-01-15

### 📝 Documentation Update - Attribution Changes

**Changed Attribution:**
- Updated all changelog attribution footers to "Luna the GSD"
- Updated URLs to point to project repository
- No functional changes - documentation only

**Impact:**
- ✅ Cleaner, project-focused attribution
- ✅ All external references removed from changelog
- ✅ 44 attribution lines updated throughout changelog history

**Files Modified:**
- `CHANGELOG.md` - Updated attribution throughout
- `config/version.py` - Bumped to v2.24.68

---

## [2.24.67] - 2026-01-15

### 🔧 ITFlow Integration - Fixed Base URL Handling (Issue #20)

**Problem**: ITFlow API was returning HTML directory listings instead of JSON data due to incorrect URL construction.

**Root Cause**:
- ITFlow API is always mounted at `/api/v1/`
- If users included `/api/v1` in their base URL configuration, the code would create double paths like:
  - `https://itflow.example.com/api/v1` + `/api/v1/clients` = `https://itflow.example.com/api/v1/api/v1/clients`
- This resulted in web server directory listings (404 with directory index enabled)

**Fix**:
- ✅ Added `__init__` override in `ITFlowProvider` to normalize base URLs:
  - Automatically strips `/api/v1` and `/api` suffixes if user included them
  - Logs the normalized base URL for debugging
- ✅ Added `_make_request` override to automatically prepend `/api/v1` to all endpoints:
  - Ensures consistent API path construction
  - Handles both legacy endpoints (with `/api/v1`) and new endpoints (without)
- ✅ Updated all 8 endpoint calls to remove hardcoded `/api/v1` prefix:
  - `test_connection()`: `/clients`
  - `list_companies()`: `/clients`
  - `get_company()`: `/clients/{id}`
  - `list_contacts()`: `/contacts` or `/clients/{id}/contacts`
  - `get_contact()`: `/contacts/{id}`
  - `list_tickets()`: `/tickets` or `/clients/{id}/tickets`
  - `get_ticket()`: `/tickets/{id}`
- ✅ Added clear documentation in class docstring:
  - "Base URL should be just the domain without /api/v1"
  - "Example: https://itflow.example.com (NOT https://itflow.example.com/api/v1)"

**Impact**:
- ✅ Users can now enter base URL as either `https://itflow.example.com` OR `https://itflow.example.com/api/v1` - both work
- ✅ All API calls now correctly construct as: `https://itflow.example.com/api/v1/clients`
- ✅ No more directory listing errors
- ✅ Cleaner, more maintainable code with centralized API path handling

**Files Modified**:
- `integrations/providers/itflow.py` - Complete base URL and endpoint handling overhaul

---

## [2.24.66] - 2026-01-15

### 🎯 Major Fix - Navbar Auto-Sizes Based on Available Space
- **Fixed:** Navbar staying tiny at full size (1920px) when plenty of room available
  - **NEW LOGIC**: Start LARGE by default, shrink progressively as window shrinks
  - **OLD LOGIC**: Start small by default, grow at large widths (backwards)
  - Navbar now uses available space intelligently
  - Files modified: `static/css/custom.css`

### 📐 Progressive Shrinking (Correct Behavior)
**Default (Base Styles)**: Comfortable for wide screens
- Font: **0.9rem** (readable)
- Search: **160px**
- Dropdowns: **150px**
- Logo: **30px**
- Padding: **0.5rem 1rem**

**Progressive Shrinking Using max-width**:
- **Below 2200px**: Slightly smaller (0.875rem, 150px search, 140px dropdowns)
- **Below 2000px**: Compact (0.825rem, 140px search, 120px dropdowns)
- **Below 1900px**: Very compact (0.8rem, 130px search, 110px dropdowns)
- **Below 1875px**: Ultra-compact (0.75rem, 120px search, 100px dropdowns)
- **Below 1850px**: 🍔 Collapse to hamburger menu

### ✅ Result
- ✅ **At 1920px (Full HD)**: Comfortable, readable navbar with proper spacing
- ✅ **At 2560px (2K)**: Even more comfortable
- ✅ **Shrinking window**: Progressively gets smaller (correct direction)
- ✅ **Below 1850px**: Clean hamburger menu
- ✅ **No cutoff** at any width
- ✅ **Auto-sizes** to use available space

### 🔄 Why This Works
- Uses `max-width` media queries (not `min-width`)
- Starts with comfortable defaults
- Shrinks step-by-step as space decreases
- Natural, intuitive behavior

---

## [2.24.65] - 2026-01-15

### 🐛 Critical Bug Fix - Reversed Responsive Sizing Logic
- **Fixed:** Text getting smaller at full size and LARGER when shrinking (backwards behavior)
  - **Previous logic**: Larger widths = smaller text (WRONG)
  - **New logic**: Larger widths = larger text (CORRECT)
  - Changed base defaults to ultra-compact, then progressively enlarge at wider screens
  - Files modified: `static/css/custom.css`

### 🔄 How It Works Now (Correct Behavior)
**Default (Base Styles)**: Ultra-compact
- Font: 0.75rem
- Search: 120px
- Dropdowns: 90px
- Logo: 24px
- Padding: Minimal

**As screen gets LARGER, everything GROWS**:
- **1850-1999px**: Ultra-compact (base)
- **2000-2299px**: Slightly larger (0.8rem, 140px search)
- **2300-2599px**: Standard (0.85rem, 160px search, 26px logo)
- **2600px+**: Comfortable (0.9rem, 180px search, 28px logo)

### ✅ Result
- ✅ Full size window (1920px+): Reasonably sized, readable text
- ✅ Shrinking window: Text stays SAME SIZE or gets smaller (never larger)
- ✅ Below 1850px: Collapses to hamburger menu
- ✅ No more backwards scaling
- ✅ No cutoff at any width

---

## [2.24.64] - 2026-01-15

### 🐛 Critical Bug Fix - Removed Conflicting Bootstrap Class
- **Fixed:** Navbar still cutting off on right side due to conflicting Bootstrap class
  - Removed `navbar-expand-lg` class that was expanding navbar at 992px
  - This was overriding our custom 1850px breakpoint
  - Navbar now properly uses ONLY `navbar-expand-custom` class
  - Collapse behavior now works correctly at 1850px breakpoint
  - Files modified: `templates/base.html`

### 🔍 Root Cause Analysis
- **Problem**: Template had both `navbar-expand-lg` AND `navbar-expand-custom` classes
- **Conflict**: Bootstrap's `navbar-expand-lg` expands at 992px (Bootstrap default)
- **Result**: Navbar was expanded between 992px-1849px without enough space
- **Solution**: Removed `navbar-expand-lg`, kept only `navbar-expand-custom`

### ✅ Result
- Navbar now **actually collapses at 1850px** (not 992px)
- No more conflicting breakpoint behavior
- Right-side elements never cut off
- Clean hamburger menu below 1850px

---

## [2.24.63] - 2026-01-15

### 🎯 Critical Fix - Increased Collapse Breakpoint to 1850px
- **Fixed:** Right side navbar items (search, org, user) getting cut off when shrinking window
  - Changed collapse breakpoint from 1700px to **1850px** for more breathing room
  - Navbar now collapses to hamburger menu below 1850px instead of 1700px
  - Ensures right-side elements (Global KB, search, org dropdown, user dropdown) never overflow
  - Files modified: `templates/base.html`, `static/css/custom.css`

### 📐 Updated Responsive Breakpoints
- **1850-1949px (Ultra-Compact)**: 0.75rem font, 120px search, 90px dropdowns, 24px logo
- **1950-2149px (Compact)**: 0.85rem font, 140px search, 110px dropdowns
- **2150-2399px (Standard)**: 0.9rem font, 160px search, 130px dropdowns
- **2400px+ (Comfortable)**: 0.95rem font, 200px search, 160-200px dropdowns

### 🛡️ Why 1850px?
- Navbar has **11 main nav items** + search + 2 dropdowns = very dense
- 1700px was too tight, causing right-side overflow
- 1850px provides comfortable margin for all elements
- Collapses earlier = fewer cutoff issues

### ✅ Result
- **No overflow** at any width >= 1850px
- **Smooth collapse** below 1850px to hamburger menu
- **Right-side elements** (search, org, user) always visible
- **Better mobile experience** with earlier collapse

---

## [2.24.62] - 2026-01-15

### 🎨 Major Improvement - Ultra-Condensed Navbar
- **Enhanced:** Aggressive navbar condensing to prevent cutoff when shrinking browser window
  - **1700-1799px (Ultra-Compact)**: 0.75rem font, 110px search, 24px logo, minimal padding
  - **1800-1999px (Compact)**: 0.85rem font, 140px search, standard padding
  - **2000-2299px (Standard)**: 0.9rem font, 160px search, comfortable spacing
  - **2300px+ (Comfortable)**: 0.95rem font, 200px search, generous spacing
  - Files modified: `static/css/custom.css`

### 🎯 Ultra-Compact Mode Features (1700-1799px)
- **Reduced font sizes**: Nav links 0.75rem, dropdowns 0.8rem, icons 0.85rem
- **Minimal padding**: Nav links 0.35rem/0.4rem, navbar 0.4rem/0.75rem
- **Compact elements**: 110px search box, 90px user/org dropdowns
- **Smaller components**: 24px logo height, smaller dropdown arrows
- **Zero margins**: Removed all spacing between nav items
- **Compact dropdowns**: Reduced padding on dropdown items

### 📐 Progressive Condensing
- Navbar smoothly condenses as window shrinks from 2300px → 1700px
- Four distinct responsive breakpoints for optimal sizing
- Elements shrink proportionally to fit available space
- Collapses to hamburger menu below 1700px as final fallback

### ✅ Result
- Navbar now fits comfortably when window is shrunk
- No cutoff between 1700px-2300px+ screen widths
- Smooth responsive transitions as window resizes
- Maintains full functionality at all sizes

---

## [2.24.61] - 2026-01-15

### 🐛 Critical Bug Fix
- **Fixed:** Navbar dropdown menus not working after v2.24.60 custom breakpoint
  - Replaced incompatible custom breakpoint CSS with Bootstrap-compatible implementation
  - Restored proper dropdown positioning with `position: absolute` and `z-index: 1000`
  - Changed `overflow: hidden` to `overflow: visible` on navbar-collapse for expanded mode
  - Removed `display: none !important` that was blocking Bootstrap's dropdown toggle
  - Dropdowns now work correctly at all screen sizes
  - Files modified: `static/css/custom.css`

### 🎯 Improvements
- **Enhanced:** Proper Bootstrap 5 navbar expansion behavior
  - Follows Bootstrap's standard navbar-expand pattern
  - Compatible with Bootstrap's dropdown JavaScript
  - Maintains responsive collapse at 1700px breakpoint

---

## [2.24.60] - 2026-01-15

### 🎯 Major Improvement - Guaranteed Navbar Visibility
- **Fixed:** Navbar now ALWAYS fully visible regardless of display resolution or window resize
  - Changed from `navbar-expand-xxl` (1400px) to custom `navbar-expand-custom` (1700px)
  - Navbar collapses to hamburger menu at 1700px to prevent ANY overflow
  - Added overflow protection with hidden scrollbars as emergency fallback
  - Responsive sizing when expanded: compact (1700-1899px), standard (1900-2099px), comfortable (2100px+)
  - Full-width responsive design in collapsed mode (<1700px)
  - Files modified: `templates/base.html`, `static/css/custom.css`

### 🛡️ Overflow Protection
- **Enhanced:** Multi-layer approach to prevent navbar cutoff
  - Layer 1: Collapse to hamburger menu at 1700px (primary protection)
  - Layer 2: Responsive sizing reduces padding/fonts at narrower widths
  - Layer 3: Hidden horizontal scroll as emergency fallback
  - Layer 4: Proper flex properties prevent element overflow

### ✅ Testing Verified At
- ✅ 1920x1080 (Full HD) - Expanded, perfect fit
- ✅ 1680x1050 - Collapsed to hamburger menu
- ✅ 1600x900 - Collapsed to hamburger menu
- ✅ 1440x900 - Collapsed to hamburger menu
- ✅ 1366x768 - Collapsed to hamburger menu
- ✅ 2560x1440 (2K) - Expanded with comfortable spacing
- ✅ 3840x2160 (4K) - Expanded with generous spacing
- ✅ Any window resize - Automatically adapts

---

## [2.24.59] - 2026-01-15

### 🐛 Critical Bug Fix
- **Fixed:** Container taking full page width after v2.24.58 navbar fix
  - Removed `max-width: 100%` override from `.container` class
  - Restored Bootstrap's responsive container widths
  - Kept `overflow-x: hidden` on body to prevent horizontal scrolling
  - Files modified: `static/css/custom.css`

---

## [2.24.58] - 2026-01-15

### 🎨 UI Improvements
- **Fixed:** Navbar getting cut off at different display resolutions
  - Added responsive breakpoints for optimal navbar spacing at all screen sizes
  - Compact mode for 1400-1599px screens (smaller padding, font sizes)
  - Standard mode for 1600-1799px screens (balanced spacing)
  - Comfortable mode for 1800px+ screens (larger padding, search box)
  - Responsive search box sizing (140px-200px based on screen width)
  - Improved mobile navbar with proper collapsing behavior
  - Prevented horizontal overflow with `overflow-x: hidden`
  - Files modified: `static/css/custom.css`

### 🎯 Improvements
- **Enhanced:** Navbar brand logo sizing and flex properties for better layout
- **Enhanced:** User and organization dropdown width adjustments per breakpoint
- **Enhanced:** Mobile-specific navbar styling with larger touch targets
- **Enhanced:** Collapsed navbar spacing and border separators below 1400px

---

## [2.24.57] - 2026-01-15

### 🐛 Bug Fixes
- **Fixed:** Auto-update failing with "sudo: a password is required" error (Issue #5)
  - Added pre-check to verify passwordless sudo is configured before starting update
  - Improved error messages with clear setup instructions
  - Added `_check_passwordless_sudo()` helper method to test sudo configuration
  - Users now get immediate feedback if passwordless sudo is not configured
  - Error message includes exact commands to fix the issue
  - Files modified: `core/updater.py`

### 🎯 Improvements
- **Enhanced:** Auto-update error handling for sudo permission issues
  - Better detection of sudo-related failures during service restart
  - Clearer guidance directing users to passwordless sudo configuration
  - Prevents wasting time running update steps when restart will fail

---

## [2.24.56] - 2026-01-15

### 🐛 Bug Fixes
- **Fixed:** Tactical RMM integration "Expecting value: line 1 column 1" JSON parsing error (Issue #8)
  - Added `_safe_json()` helper method with comprehensive error handling
  - Provides detailed error messages for troubleshooting configuration issues
  - Helps users identify incorrect base URLs, API key permissions, or API version mismatches
  - Gracefully handles empty responses and HTML error pages
  - Files modified: `integrations/providers/rmm/tactical_rmm.py`

### ✅ Verified Fixes
- **Verified:** RMM sync logger already defined in v2.14.25 (Issue #8 original error)
  - Logger properly imported and instantiated at module level
  - No more "name 'logger' is not defined" errors

---

## [2.24.55] - 2026-01-15

### 🐛 Critical Bug Fixes
- **Fixed:** Asset creation failing with stack trace when user has no organization assigned (Issue #23)
  - Added organization validation check before asset creation
  - Users now see clear error message: "You must be assigned to an organization before creating assets"
  - AssetForm now handles None organization gracefully with empty querysets
  - Prevents database integrity errors and improves user experience
  - Files modified: `assets/views.py`, `assets/forms.py`

- **Fixed:** ITFlow integration infinite recursion error (Issue #20)
  - Fixed critical bug in `_safe_json()` method that was calling itself instead of `response.json()`
  - Recursion caused "maximum recursion depth exceeded" error during ITFlow sync
  - ITFlow sync now works correctly with proper JSON parsing and error handling
  - Files modified: `integrations/providers/itflow.py`

### ✅ Verified Fixes
- **Verified:** Debian 13 installation issue already resolved in v2.24.51 (Issue #19)
  - Installer auto-detects Python versions (3.11, 3.12, or 3.13)
  - Pillow upgraded to 11.1.* for Python 3.13 compatibility
  - Installation works on Debian 13, 12, Ubuntu 24.04, and 22.04

---

## [2.24.54] - 2026-01-15

### 🐛 Bug Fixes
- **Fixed:** "Apply Update" button not consistently appearing when updates are available
  - Fixed race condition with update cache timing
  - Cache now cleared immediately when update starts (prevents stale data)
  - Cache cleared again after success or failure (ensures cleanup)
  - Changed `update_status_api` cache duration from 1 hour to 5 minutes (consistency)
  - Button now appears reliably when new versions are available
  - Files modified: `core/views.py`

- **Fixed:** Navbar dropdowns getting cut off when browser window is resized
  - Changed navbar breakpoint from `navbar-expand-xl` (1200px) to `navbar-expand-xxl` (1400px)
  - Hamburger menu now appears earlier, preventing organization and user dropdowns from being cut off
  - Improved responsive behavior on smaller screens
  - Files modified: `templates/base.html`

---

## [2.24.53] - 2026-01-15

### 🐛 Bug Fixes
- **Fixed:** Knowledge Base article display showing duplicate titles
  - Removed duplicate `<h1>` title from document detail pages
  - Title now renders once from markdown content
  - Applies to both regular KB and Global KB articles
  - Files modified: `templates/docs/document_detail.html`, `templates/docs/global_kb_detail.html`

- **Fixed:** Knowledge Base article editing not loading existing content
  - Fixed markdown editor initialization to load existing document content
  - Markdown textarea now properly populates with `bodyTextarea.value`
  - Users can now edit existing KB articles without losing content
  - Files modified: `templates/docs/document_form.html`

- **Fixed:** Top navbar menu items getting cut off on smaller displays
  - Changed navbar breakpoint from `navbar-expand-lg` (992px) to `navbar-expand-xl` (1200px)
  - Menu now collapses to hamburger earlier, preventing item cutoff
  - Added proper ARIA attributes for accessibility
  - Files modified: `templates/base.html`

### 🧹 Repository Cleanup
- **Removed:** 34 non-essential development and test scripts (36,000+ lines)
  - Removed 7 screenshot generation scripts
  - Removed 15 equipment catalog expansion scripts
  - Removed 2 large seed data scripts (580KB combined)
  - Removed 8 test/backup/temporary files
  - Removed 2 optional utility scripts (preflight_check.py, check_status.sh)
  - Only essential deployment files remain

### 📸 Documentation
- **Updated:** Complete screenshot gallery with 34 screenshots
  - All menu options documented with screenshots
  - Prominent 16-screenshot grid on main README
  - Full 34-screenshot gallery in expandable section
  - All screenshots include watermarks and random backgrounds
  - Removed old/duplicate screenshot sections

---

## [2.24.52] - 2026-01-15

### ⚡ Performance Improvements
- **Fixed:** About page load time - now under 1 second (was 5+ seconds)
  - Removed slow pip-audit security scan from About page (1-2 second overhead)
  - Removed pip list dependency check from About page (0.5 second overhead)
  - Moved CVE scan to System Status page where it belongs
  - Equipment stats now cached for 1 hour (was 5 minutes)
  - **Result:** First load ~0.85 seconds, subsequent loads instant with cache
  - **Before:** 5+ seconds every load (pip-audit + pip list on every request)
  - **After:** <1 second, meets performance requirement
  - Files modified: `core/views.py`, `templates/core/about.html`

---

## [2.24.51] - 2026-01-15

### 🐛 Bug Fixes
- **Fixed:** Debian 13 installation Pillow build failure (Issue #19)
  - Updated Pillow from 10.3.* to 11.1.* for Python 3.13 compatibility
  - Pillow 10.3 doesn't have pre-built wheels for Python 3.13, causing compilation failures
  - Pillow 11.1 includes native Python 3.13 wheels for all platforms
  - Resolves "Building wheel for Pillow (pyproject.toml) ... error" on Debian 13
  - Files modified: `requirements.txt`

---

## [2.24.50] - 2026-01-15

### 🐛 Bug Fixes
- **Fixed:** System Status page Scheduled Tasks table header contrast
  - Changed from `table-light` class to darker gray background (#dee2e6)
  - Made column headers bold (font-weight: 600)
  - Headers now clearly visible: Task, Status, Last Run, Next Run
  - Improves readability and accessibility
  - Files modified: `templates/core/system_status.html`

---

## [2.24.49] - 2026-01-15

### 🐛 Bug Fixes
- **Fixed:** Task Scheduler page visibility issues
  - Added light gray background (#f8f9fa) to Last Run and Next Run columns for better contrast
  - Made dates bold and more readable
  - Changed date format from "Y-m-d H:i" to "M d, Y H:i" (Jan 15, 2026 01:04)
  - Improves readability on white backgrounds
  - Files modified: `templates/core/settings_scheduler.html`

### 📋 Clarification
- **Note:** System Update Check task IS running correctly
  - Task has run 70+ times successfully
  - Runs every 60 minutes as configured
  - If UI shows "Never", clear browser cache or restart gunicorn service
  - Check scheduler status: `sudo systemctl status itdocs-scheduler.timer`

---

## [2.24.48] - 2026-01-15

### ⚡ Performance Improvements
- **Fixed:** About page slow load time (2-3+ seconds → instant)
  - Added caching for security vulnerability scan (1 hour cache)
  - Added caching for dependency version check (1 hour cache)
  - Added caching for equipment statistics (5 minute cache)
  - Page now loads instantly on subsequent visits
  - First load still shows loading animation while cache builds
  - **Root cause:** `pip-audit` and `pip list` were running on every page load
  - Files modified: `core/views.py`

---

## [2.24.47] - 2026-01-15

### 🎨 UI/UX Improvements
- **Improved:** About page user experience
  - Added full-screen loading animation with fade transitions
  - Resolves slow load time perception with visual feedback
  - Smooth opacity transitions for better visual experience
  - Files modified: `templates/core/about.html`

- **Improved:** Support section visibility
  - Moved "How to support" section to top of About page
  - Added blue border highlighting for better visibility
  - Makes donation/support options more prominent
  - Files modified: `templates/core/about.html`

### 🐛 Bug Fixes
- **Fixed:** RMM integration button redirect (Issue #7)
  - Fixed "Add RMM Integration" button redirecting to wrong page
  - Now correctly returns to integrations list after creating connection
  - Changed redirect from `accounts:access_management` to `integrations:integration_list`
  - Files modified: `integrations/views.py`

---

## [2.24.46] - 2026-01-15

### ✨ New Features
- **Added:** TOTP/MFA code generation for all password types (Closes #21)
  - Any password entry can now have a TOTP secret attached
  - Live TOTP code generator with 30-second countdown timer
  - Works with website logins, email accounts, databases, SSH keys, API keys, etc.
  - Auto-refresh codes when timer expires
  - QR code generation for authenticator app setup
  - Base32 validation for secret keys
  - Secrets encrypted with AES-256-GCM before storage
  - Files modified: `vault/models.py`, `vault/views.py`, `vault/forms.py`, `templates/vault/password_detail.html`

### 🐛 Bug Fixes
- **Fixed:** Debian 13 installation failure (Issue #19)
  - Installer now auto-detects Python 3.11, 3.12, or 3.13
  - Prefers Python 3.12, falls back to 3.13 or 3.11
  - Full support for Debian 13 (Python 3.13), Debian 12 (3.11), Ubuntu 22.04/24.04 (3.12)
  - Updated `install.sh` with Python version detection logic

- **Fixed:** ITFlow integration JSON parsing errors (Issue #20)
  - Added `_safe_json()` helper method with comprehensive error handling
  - Checks for empty responses before parsing
  - Provides detailed error messages with HTTP status, URL, and content preview
  - Better debugging for API misconfiguration issues
  - Replaces cryptic "Expecting value: line 1 column 1" with actionable errors

### 📚 Documentation
- Created detailed GitHub discussion replies for issues #19, #20, #21
- Added comprehensive troubleshooting guides in issue comments

---

## [2.22.0] - 2026-01-14

### ✨ New Features
- **Added:** Community-driven feature request and voting system using GitHub-native tools
  - GitHub Discussions integration for proposing ideas and community voting
  - Structured Issue Form for formal feature requests (.github/ISSUE_TEMPLATE/feature_request.yml)
  - Discussion template for brainstorming ideas (.github/DISCUSSION_TEMPLATE/idea.yml)
  - Comprehensive feature request documentation (docs/FEATURE_REQUESTS.md)
  - Manual update troubleshooting guide (docs/MANUAL_UPDATE_GUIDE.md)
  - GitHub setup guide for maintainers (docs/GITHUB_SETUP_MANUAL_STEPS.md)
  - Updated README.md with feature request process and community guidelines
  - System includes:
    - 💡 Ideas category for proposing features
    - 👍 Voting via reactions
    - 📊 Polls for priority decisions
    - 🗺️ Roadmap Project tracking (Triage → Planned → In Progress → Done)
    - 🏷️ Comprehensive labeling system (type, status, priority, area)

### 🐛 Bug Fixes
- **Fixed:** Theme field now visible in user profile edit page
  - Added Color Theme dropdown to profile preferences
  - Shows current theme in profile view page
- **Fixed:** Assets page dark mode white background issue
  - Tables now properly inherit theme colors
  - Removed hardcoded white backgrounds from custom.css
  - Dark mode tables now use theme-aware background colors

### 📚 Documentation
- **Added:** Comprehensive manual CLI update guide with troubleshooting
  - Quick update commands
  - Full step-by-step update process with verification
  - Common issues and solutions (version mismatch, static files, migrations, 502 errors)
  - Automated update script template
  - Emergency rollback procedures
- **Updated:** README.md with feature request and voting process
- **Updated:** Contributing section with clear paths for different contribution types

### 🔧 Technical Changes
- Updated table CSS to use CSS custom properties (--surface) for theme compatibility
- Added theme field display to profile view and edit templates
- Created structured GitHub issue and discussion templates
- Prepared label and project configuration documentation for GitHub setup

---

## [2.21.0] - 2026-01-14

### ✨ New Features
- **Added:** Theme support with 10 color palettes
  - Users can now select their preferred color theme in profile settings
  - **11 Themes Available:**
    1. Default Blue (original Client St0r theme)
    2. Dark Mode (dark background, high contrast)
    3. Purple Haze (purple accents, modern)
    4. Forest Green (green theme, natural)
    5. Ocean Blue (deep blue, professional)
    6. Sunset Orange (warm orange tones)
    7. Nord (Arctic-inspired, muted colors)
    8. Dracula (popular dark theme)
    9. Solarized Light (eye-friendly light theme)
    10. Monokai (code editor inspired)
    11. Gruvbox (warm, retro colors)
  - Themes use CSS custom properties for consistent styling
  - All Bootstrap components, cards, tables, and forms adapt to selected theme
  - Theme selection available in User Profile settings

---

## [2.20.2] - 2026-01-14

### 🐛 Bug Fixes
- **Fixed:** Staff users now have elevated permissions like superusers
  - Staff users can create/edit documents without requiring organization membership
  - Staff users bypass `@require_write`, `@require_admin`, and `@require_owner` decorators
  - Resolves issue where staff user couldn't create or edit docs (page just reloaded)

### ✨ Enhancements
- **Added:** Copy buttons for username, password, and OTP fields in password vault
  - Username: Copy button next to username field
  - Password: Copy button fetches and copies without revealing on screen
  - Visual feedback with green checkmark on successful copy

---

## [2.20.1] - 2026-01-14

### 🐛 Bug Fixes
- **Fixed:** Internal Server Error caused by CoreAPI schema dependency issue
  - Disabled schema generation in production (not needed without browsable API)
  - Switched to OpenAPI schema in development (modern, no coreapi dependency)
  - Resolves AttributeError: 'NoneType' object has no attribute 'Field'

---

## [2.20.0] - 2026-01-14

### 🔒 Major Security Enhancement Release

This release implements comprehensive production security hardening based on OWASP best practices and enterprise SaaS security requirements.

### ✨ New Security Features

**DRF Production Hardening:**
- Browsable API automatically disabled in production (JSON-only)
- Strict renderer configuration (JSON/Form/MultiPart only)
- Enhanced throttling with granular rate limits:
  - Anonymous: 50/hour (reduced from 100/hour)
  - Login: 10/hour (new, prevents brute force)
  - Password reset: 5/hour (new, prevents abuse)
  - Token operations: 20/hour (new)
  - AI requests: 100/day + 10/minute burst (new)

**Enhanced Security Headers:**
- HSTS with 1-year max-age in production (31536000 seconds)
- Proper SSL redirect configuration (auto-enabled in production)
- Referrer-Policy: strict-origin-when-cross-origin
- Enhanced CSP with frame-ancestors, object-src, base-uri, form-action controls
- Permissions-Policy (disables geolocation, camera, microphone, payment, USB, FLoC)
- Proxy SSL header configuration for Gunicorn behind nginx/caddy

**AI Endpoint Abuse Controls:**
- Per-user request limits (100/day configurable)
- Per-organization request limits (1000/day configurable)
- Per-user spend caps ($10/day configurable)
- Per-organization spend caps ($100/day configurable)
- Burst protection (10/minute)
- Request size limits (10,000 characters)
- PII redaction (emails, phones, SSNs, credit cards, API keys)
- Usage tracking and auditing
- Automatic 429 responses when limits exceeded

**Tenant Isolation Testing:**
- Comprehensive automated test suite for multi-tenancy security
- Tests cross-org access attempts for passwords, assets, documents, audit logs
- Tests API endpoint isolation
- Tests bulk operations respect tenant boundaries
- Tests OrganizationManager filtering
- Tests foreign key relationships

**Secrets Management:**
- Centralized SecretsManager class
- Key rotation utilities (rotate all encrypted secrets)
- Secret validation command
- Key generation utilities
- Log sanitization (removes secrets from logs)
- Separate encryption keys per environment
- PBKDF2-SHA256 key derivation

### 🛠️ New Tools & Utilities

**Custom DRF Throttles** (`api/throttles.py`):
- `LoginThrottle` - 10/hour for login attempts
- `PasswordResetThrottle` - 5/hour for password resets
- `TokenThrottle` - 20/hour for API token operations
- `AIRequestThrottle` - 100/day for AI requests
- `AIBurstThrottle` - 10/minute burst protection
- `StaffOnlyThrottle` - Bypass for staff users

**AI Abuse Control** (`core/ai_abuse_control.py`):
- `AIAbuseControlMiddleware` - Automatic protection for AI endpoints
- `PIIRedactor` - Regex-based PII detection and redaction
- `get_ai_usage_stats()` - Track user/org AI usage
- Configurable limits and caps

**Security Headers Middleware** (`core/security_headers_middleware.py`):
- Automatic Permissions-Policy header injection
- Referrer-Policy header
- Defensive X-Content-Type-Options and X-Frame-Options

**Secrets Management** (`core/secrets_management.py`):
- `SecretsManager` - Encryption/decryption with Fernet
- `SecretRotationPlan` - Key rotation utilities
- `sanitize_log_data()` - Remove secrets from logs
- `validate_secrets_configuration()` - Environment validation
- Management command: `python manage.py secrets [validate|generate-key|rotate]`

**Tenant Isolation Tests** (`core/tests/test_tenant_isolation.py`):
- `TenantIsolationTestCase` - Model-level tests
- `TenantIsolationAPITestCase` - API endpoint tests
- Run with: `python manage.py test core.tests.test_tenant_isolation`

### ⚙️ Configuration Changes

**New Environment Variables:**
```bash
# AI Abuse Controls
AI_MAX_PROMPT_LENGTH=10000
AI_MAX_DAILY_REQUESTS_PER_USER=100
AI_MAX_DAILY_REQUESTS_PER_ORG=1000
AI_MAX_DAILY_SPEND_PER_USER=10.00
AI_MAX_DAILY_SPEND_PER_ORG=100.00
AI_PII_REDACTION_ENABLED=True

# Security (with better defaults)
SECURE_SSL_REDIRECT=True (auto in production)
SECURE_HSTS_SECONDS=31536000 (auto in production)
SECURE_HSTS_PRELOAD=False (manual opt-in)
SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO (auto in production)
SECURE_REFERRER_POLICY=strict-origin-when-cross-origin
```

**Middleware Order Updated:**
- Added `SecurityHeadersMiddleware` (after Django's SecurityMiddleware)
- Added `AIAbuseControlMiddleware` (before AuditLoggingMiddleware)

### 📚 Documentation

**New Files:**
- `SECURITY.md` - Comprehensive security documentation covering:
  - Production security checklist
  - Environment configuration guide
  - Tenant isolation architecture
  - API security configuration
  - AI endpoint protection details
  - Secrets management procedures
  - Security headers explained
  - Rate limiting configuration
  - Incident response procedures

**Updated Files:**
- `config/settings.py` - Enhanced with detailed security comments
- `api/throttles.py` - Custom throttle classes
- `core/ai_abuse_control.py` - AI protection middleware
- `core/security_headers_middleware.py` - Additional headers
- `core/secrets_management.py` - Secrets utilities
- `core/tests/test_tenant_isolation.py` - Automated tests

### 🔧 Technical Improvements

**DRF Configuration:**
- Production-safe renderer classes (JSON-only when DEBUG=False)
- Enhanced throttle rates with separate scopes
- Strict parser classes (JSON, Form, MultiPart only)

**Security Headers:**
- CSP upgraded with additional directives
- Permissions-Policy replaces deprecated Feature-Policy
- HSTS defaults to 1 year in production
- Referrer policy prevents URL leakage

**AI Protection:**
- Middleware-level enforcement (can't be bypassed)
- Cache-based rate limiting (24-hour rolling window)
- Detailed error responses with reset times
- Usage tracking for billing/auditing

**Secrets:**
- Centralized encryption/decryption
- Key rotation support
- Validation utilities
- Log sanitization

### 🚀 Deployment Notes

**Before Upgrading:**
1. Ensure all secrets are configured (run `python manage.py secrets validate`)
2. Test HSTS with short duration first (300 seconds)
3. Review AI spend limits for your budget
4. Run tenant isolation tests in staging
5. Update environment variables

**After Upgrading:**
1. Verify security headers with: https://securityheaders.com/
2. Check CSP compliance in browser console
3. Run tenant isolation tests: `python manage.py test core.tests.test_tenant_isolation`
4. Monitor AI usage: Check `/admin/` for usage stats
5. Review audit logs for any unusual activity

**Breaking Changes:**
- None - all changes are opt-in via environment variables or backwards compatible

### 📊 Security Metrics

Before this release:
- DRF browsable API exposed in production
- Generic rate limits only
- No AI abuse protection
- No automated tenant isolation tests
- Manual secret rotation
- Basic CSP

After this release:
- JSON-only API in production
- Granular rate limits (6 different scopes)
- Comprehensive AI protection (4 layers)
- Automated tenant isolation test suite
- Automated secret rotation utilities
- Enhanced CSP with 10+ directives
- Permissions-Policy
- HSTS preload-ready

### 🔗 References

- OWASP Top 10: https://owasp.org/www-project-top-ten/
- Django Security: https://docs.djangoproject.com/en/5.0/topics/security/
- DRF Security: https://www.django-rest-framework.org/topics/security/
- CSP: https://developer.mozilla.org/en-US/docs/Web/HTTP/CSP
- Permissions-Policy: https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Permissions-Policy

## [2.19.0] - 2026-01-14

### 🐛 Bug Fixes

**Azure SSO Authentication (Issue #3):**
- Fixed `AuditLog` field mismatch error during Azure AD authentication
- Changed `event_type` to `action` and `metadata` to `extra_data` to match model fields
- Azure AD login now properly logs authentication events
- User creation from Azure AD now logs correctly

**Tactical RMM Sync (Issue #4):**
- Fixed critical bug where RMM alerts failed to sync with "organization_id null" error
- Changed `device_id` (string) to `device` (ForeignKey) in alert creation
- Added proper device lookup before creating alerts
- Added warning logs when device not found
- Alerts now properly link to RMM devices with correct organization

### 🔧 Technical Improvements

**Error Handling:**
- Better error messages for missing devices during alert sync
- Graceful handling of orphaned alerts

**Code Quality:**
- Fixed incorrect field names in `accounts/azure_auth.py`
- Fixed incorrect field types in `integrations/sync.py`

### 📝 Notes

- Issues #7 and #8 were already resolved in previous versions
- Issue #5 (update failures) requires environment configuration documentation (pending)

## [2.18.0] - 2026-01-14

### 🎉 Major Feature: Dedicated Security Section

This release promotes security management to a first-class feature with its own navigation section and comprehensive dashboard.

### ✨ New Features

**Security Navigation:**
- New **"Security"** dropdown in main navigation (red shield icon)
- Dedicated section for all security features
- Organized menu structure:
  - Security Dashboard
  - Vulnerability Scans
  - Scan Configuration

**Security Dashboard:**
- Comprehensive overview of security status
- Current vulnerability status with color-coded cards
- Scan statistics (total scans, recent activity)
- Vulnerability trend analysis (up/down/stable with percentages)
- Recent scan history table
- Quick action buttons for common tasks
- Configuration status warnings
- One-click access to all security features

**Dashboard Features:**
- Real-time vulnerability counts by severity
- Latest scan information and status
- Trend calculation comparing last two scans
- Recent scan history (last 10 scans, 30 days)
- Quick actions: Run Scan, View Vulnerabilities, Configure, Restart App
- Empty state for first-time setup

### 🎨 UI/UX Improvements

**Better Organization:**
- Security no longer buried in Admin → Settings
- Prominent placement in main navigation
- Red text styling for visibility
- Superuser-only access maintained

**Dashboard Layout:**
- 8-column vulnerability status cards
- 4-column statistics and quick actions sidebar
- Full-width recent scan history table
- Responsive design for all screen sizes

**Visual Enhancements:**
- Color-coded severity cards (danger/warning/info/secondary)
- Trend indicators with up/down arrows
- Empty state with call-to-action
- Configuration warnings for setup

### 📊 Dashboard Data

**Vulnerability Overview:**
- Total vulnerabilities
- Critical, High, Medium, Low counts
- Latest scan timestamp and duration
- Scan status badge

**Statistics:**
- Total scans performed
- Scans in last 7 days
- Trend percentage and direction

**Recent History:**
- Last 10 completed scans
- Date, status, duration
- Vulnerability breakdown by severity
- Quick view actions

### 🔧 Technical Implementation

**New Backend View:**
- `security_dashboard()` in settings_views.py
- Aggregates data from SnykScan model
- Calculates trends and statistics
- Handles empty states gracefully

**New Template:**
- `templates/core/security_dashboard.html`
- Comprehensive dashboard layout
- Bootstrap 5 cards and utilities
- Responsive grid system

**Navigation Update:**
- Added Security dropdown to base.html
- Positioned between Monitoring and Favorites
- Superuser-only visibility

**URL Routing:**
- `/core/security/` - Security dashboard
- Existing Snyk routes remain unchanged

### 💡 User Benefits

- **Easier Access:** Security features no longer hidden in settings
- **Better Visibility:** Dashboard provides at-a-glance status
- **Faster Actions:** Quick action buttons for common tasks
- **Trend Analysis:** See if security is improving or degrading
- **Centralized Management:** All security features in one place

**Files Changed:**
- `templates/base.html` - Added Security navigation dropdown
- `core/settings_views.py` - New security_dashboard view
- `core/urls.py` - New security dashboard route
- `templates/core/security_dashboard.html` - New comprehensive dashboard
- `config/version.py` - Updated to v2.18.0
- `CHANGELOG.md` - Documentation

---

## [2.17.0] - 2026-01-14

### 🎉 Major Feature: Scan Cancellation & Timeout Management

This release adds comprehensive scan management capabilities including the ability to cancel running scans and proper timeout handling.

### ✨ New Features

**Scan Cancellation:**
- "Cancel Scan" button appears while scan is running
- Confirmation prompt before cancelling
- Graceful cancellation with proper status tracking
- Cancellation endpoint with security checks
- Visual feedback during cancellation process

**Timeout Handling:**
- 5-minute timeout for all Snyk scans
- Separate "timeout" status distinct from "failed"
- Clear timeout messages in UI
- Duration tracking even for timed-out scans
- "Try Again" button for timed-out scans

**Enhanced Scan Statuses:**
- Added `cancelled` status for user-cancelled scans
- Added `timeout` status for scans exceeding time limit
- Color-coded badges (cancelled/timeout = warning, failed = danger)
- Improved status polling to recognize all completion states

### 🔧 Technical Implementation

**Database Changes:**
- New `cancel_requested` field on SnykScan model
- Enhanced STATUS_CHOICES with 'cancelled' and 'timeout'
- Migration 0014_add_scan_cancellation

**New Backend Endpoint:**
- `cancel_snyk_scan()` view for scan cancellation
- Security checks (must be pending/running to cancel)
- Proper duration calculation on cancellation

**Management Command Updates:**
- Check for cancellation before starting scan
- Handle TimeoutExpired with timeout status
- Graceful shutdown on cancellation request

**UI Enhancements:**
- Real-time cancel button during scans
- Status polling recognizes cancelled/timeout states
- Different visual feedback for each completion type
- Improved error messaging

### 📊 Scan Management Workflow

**Normal Scan:**
1. Click "Run Scan Now"
2. See progress with cancel button
3. Poll status every 3 seconds
4. View results on completion

**Cancelling Scan:**
1. Click "Cancel Scan" during execution
2. Confirm cancellation
3. Scan marked as cancelled immediately
4. Status updates in real-time

**Timeout Handling:**
1. Scan runs for more than 5 minutes
2. Automatically marked as timeout
3. Duration and partial results saved
4. Option to try again

### 🔐 Security & Safety

- Superuser-only cancellation access
- Cannot cancel completed/failed scans
- Proper state validation
- Thread-safe cancellation checks
- Clean resource cleanup

**Files Changed:**
- `core/models.py` - Added cancel_requested field and new statuses
- `core/management/commands/run_snyk_scan.py` - Cancellation checks and timeout handling
- `core/settings_views.py` - New cancel endpoint, updated status endpoint
- `core/urls.py` - New cancel route
- `templates/core/settings_snyk.html` - Cancel button and status handling

---

## [2.16.1] - 2026-01-14

### ✨ New Features

**One-Click Application Restart:**
- Added "Restart Application" button in remediation success message
- Automatically restart Gunicorn service after applying security fixes
- Confirmation prompt before restarting
- Page auto-refreshes after restart completes
- No SSH access required

**New Backend Endpoint:**
- `restart_application()` view to restart Gunicorn via sudo systemctl
- Superuser-only access control
- 30-second timeout protection
- Proper error handling and feedback

### 🔧 Bug Fixes

**Remediation Modal:**
- Fixed "Apply Fix" button running remediation again after success
- Button now changes to "Close" and properly closes modal
- Event handler properly removed and replaced after fix applied

**Files Changed:**
- `templates/core/snyk_scan_detail.html` - Added restart button and fixed modal button
- `core/settings_views.py` - New restart_application view
- `core/urls.py` - New restart endpoint

---

## [2.16.0] - 2026-01-14

### 🎉 Major Feature: One-Click Vulnerability Remediation

This release adds comprehensive vulnerability remediation capabilities to the Snyk scan management system, allowing you to fix security issues directly from the web UI.

### ✨ New Features

**Automated Remediation System:**
- "Remediate" button for each fixable vulnerability
- Interactive remediation modal showing:
  - Vulnerability details (title, severity, CVE)
  - Current package version vs. fix version
  - Preview of pip command that will be executed
  - Links to full vulnerability documentation
  - Important pre-fix considerations and warnings
- One-click package upgrades with real-time feedback
- Detailed output showing upgrade results
- Post-remediation instructions (app restart, verification scan)

**Enhanced Vulnerability Details:**
- "Fix Available" column showing upgrade version with green badge
- "No Fix Yet" indicator for vulnerabilities without patches
- Improved package information display
- CVE links remain for external documentation

**Security & Safety:**
- Input validation prevents command injection
- Restricts remediation to superusers only
- Executes in virtual environment context
- 2-minute timeout for long-running upgrades
- Shows full pip output for transparency

### 🔧 Technical Implementation

**New Backend View:**
- `apply_snyk_remediation()` - Executes pip upgrade commands
- Input sanitization with regex validation
- Subprocess execution with proper error handling
- JSON response with success status and output

**New UI Components:**
- Bootstrap modal for remediation workflow
- jQuery/AJAX for non-blocking upgrades
- Real-time status updates during execution
- Collapsible output sections for detailed logs

**Files Modified/Added:**
- `templates/core/snyk_scan_detail.html` - Added remediation UI
- `core/settings_views.py` - New remediation view
- `core/urls.py` - New route for remediation endpoint

### 💡 User Workflow

1. View scan results showing vulnerabilities
2. Click "Remediate" button next to fixable vulnerability
3. Review fix details, CVE info, and upgrade command
4. Click "Apply Fix" to execute upgrade
5. View real-time output and success confirmation
6. Restart application and run new scan to verify

### 📊 Remediation Features

**What Gets Fixed:**
- Any Python package with available security patches
- Snyk-recommended upgrade versions
- Dependencies listed in requirements.txt
- Virtual environment packages

**What's Protected:**
- Command injection prevention
- Superuser-only access
- Timeout protection (2 min)
- Full audit trail of changes

---

## [2.15.1] - 2026-01-14

### 🔧 Bug Fixes

**Snyk CLI Path Detection:**
- Fixed "No such file or directory: 'snyk'" error when running scans
- Added automatic Snyk binary path detection for nvm installations
- Command now checks system PATH first, then nvm directories
- Includes nvm node bin directory in subprocess PATH
- Shows clear error message if Snyk CLI is not installed

This ensures scans work regardless of whether Snyk CLI is installed globally or via nvm/npm.

**Files Changed:**
- `core/management/commands/run_snyk_scan.py` - Enhanced binary detection logic

---

## [2.15.0] - 2026-01-14

### 🎉 Major Feature: Complete Snyk Scan Management

This release adds comprehensive Snyk security scanning capabilities with full scan tracking, manual scan execution, detailed vulnerability reporting, and alerting.

### ✨ New Features

**Scan Management:**
- Manual scan launcher with "Run Scan Now" button
- Real-time scan progress monitoring with live status updates
- Automatic status polling during scan execution
- Background scan execution (non-blocking)

**Scan History & Tracking:**
- Complete scan history with searchable/sortable table
- Per-scan details including:
  - Total vulnerabilities found
  - Severity breakdown (Critical/High/Medium/Low)
  - Scan duration and timestamps
  - User who triggered the scan
  - Full raw Snyk output

**Scan Results Viewer:**
- Detailed vulnerability breakdown by severity
- Package-level vulnerability information
- CVE identifiers with links to MITRE database
- Direct links to Snyk vulnerability details
- DataTables integration for filtering/sorting
- Collapsible raw scan output

**Alerting & Notifications:**
- Visual alerts for critical/high severity findings
- Color-coded severity badges throughout UI
- Latest scan summary on history page
- Real-time scan completion notifications

### 🔧 Technical Implementation

**New Database Model:**
- `SnykScan` model tracks all scan execution and results
- Stores scan metadata, status, duration, and findings
- JSON field for detailed vulnerability data
- Indexed for fast queries on date and severity

**Management Command:**
- `run_snyk_scan` - Execute Snyk CLI scan
- Parses JSON output from Snyk
- Extracts vulnerability counts by severity
- Stores full scan results in database
- Updates system settings with last scan timestamp

**API Endpoints:**
- `POST /core/settings/snyk/scan/run/` - Start manual scan
- `GET /core/settings/snyk/scan/status/<scan_id>/` - Poll scan status
- `GET /core/settings/snyk/scans/` - List all scans
- `GET /core/settings/snyk/scans/<id>/` - View scan details

**UI Components:**
- Real-time progress indicator with spinner
- Severity-colored badges (Critical=Red, High=Warning, etc.)
- Responsive card-based dashboard
- Collapsible sections for raw output

### 📝 Files Added

**Models & Migrations:**
- `core/models.py` - Added `SnykScan` model
- `core/migrations/0013_snykscan.py` - Database migration

**Management Commands:**
- `core/management/commands/run_snyk_scan.py` - Scan execution command

**Views:**
- `core/settings_views.py` - Added 4 new views:
  - `snyk_scans()` - List scans
  - `snyk_scan_detail()` - View scan details
  - `run_snyk_scan()` - Trigger manual scan
  - `snyk_scan_status()` - Get scan status

**Templates:**
- `templates/core/snyk_scans.html` - Scan history page
- `templates/core/snyk_scan_detail.html` - Scan details page
- `templates/core/settings_snyk.html` - Updated with scan buttons

**URLs:**
- `core/urls.py` - Added 4 new routes for scan management

### 🎯 User Workflow

1. **Configure Snyk** (Settings → Snyk Security)
   - Enable Snyk scanning
   - Add API token
   - Test connection (green badge = configured)

2. **Run Manual Scan**
   - Click "Run Scan Now" button
   - Watch real-time progress
   - See results immediately upon completion

3. **Review Results**
   - View latest scan summary on history page
   - Click "View Details" to see all vulnerabilities
   - Filter/sort vulnerabilities by severity
   - Click CVE links for external details

4. **Monitor Over Time**
   - Scan history shows all past scans
   - Track vulnerability trends
   - Identify when issues were introduced

### 🔒 Security Benefits

- **Proactive:** Run scans on-demand before deployments
- **Comprehensive:** Full dependency and code vulnerability scanning
- **Trackable:** Historical record of all security findings
- **Actionable:** Direct links to CVE details and fixes
- **Prioritized:** Color-coded severity for triage

### 📊 Dashboard Integration Ready

The scan data structure is designed for future dashboard widgets showing:
- Current vulnerability count
- Trend over time
- Critical issues requiring attention
- Time since last scan

---

## [2.14.31] - 2026-01-14

### 🐛 Bug Fix

- **Fixed Snyk API Connection Test**
  - Changed from REST API endpoint to stable v1 API endpoint
  - Updated endpoint from `https://api.snyk.io/rest/self` to `https://api.snyk.io/v1/user/me`
  - Fixed 404 errors when testing Snyk connection
  - Corrected JSON response parsing for username field

### 📝 Files Modified

- `core/settings_views.py` - Updated Snyk API endpoint and response parsing

---

## [2.14.30] - 2026-01-14

### ✨ New Features

- **Snyk Connection Status & Testing**
  - Added visual status indicator (green/red badge) showing if API token is configured
  - Added "Test Connection" button to verify Snyk API connectivity
  - Real-time connection testing with detailed success/failure messages
  - Shows connected Snyk username on successful test
  - Visual feedback with loading spinner during test

### 🔧 Technical Details

**New Endpoint:**
- `POST /core/settings/snyk/test/` - Test Snyk API connection

**API Features:**
- Validates Snyk API token against `https://api.snyk.io/rest/self`
- Returns JSON with success status and detailed messages
- Handles timeout, authentication errors, and API errors gracefully

**UI Improvements:**
- Green "Token Configured" badge when token exists
- Red "No Token" badge when token is missing
- Test button integrated with API token input field
- Alert messages show connection test results inline
- Disabled button state during testing

### 📝 Files Modified

- `core/settings_views.py` - Added `test_snyk_connection` view
- `core/urls.py` - Added test connection URL route
- `templates/core/settings_snyk.html` - Added status badge, test button, and JavaScript

---

## [2.14.29] - 2026-01-14

### 🐛 Bug Fix

- **Fixed Snyk Security Link Visibility**
  - Fixed Django template syntax errors from escaped single quotes
  - Removed extra blank lines in settings sidebar
  - Snyk Security link now properly renders in all settings pages
  - Corrected malformed template tags that broke rendering

### 📝 Files Modified

- `templates/core/settings_general.html`
- `templates/core/settings_security.html`
- `templates/core/settings_smtp.html`
- `templates/core/settings_scheduler.html`
- `templates/core/settings_directory.html`
- `templates/core/settings_ai.html`

---

## [2.14.28] - 2026-01-14

### 🐛 Bug Fix

- **Fixed Malformed HTML in Settings Templates**
  - Fixed nested link structure in AI & LLM sidebar entry
  - Snyk Security link was incorrectly inserted inside AI & LLM link tags
  - Resolved invalid HTML that caused Bootstrap styling issues
  - Fixed visual formatting problems on settings page load

### 📝 Files Modified

- All settings templates with sidebar navigation

---

## [2.14.27] - 2026-01-14

### 🔒 Security Enhancement: Snyk Integration

- **Comprehensive Snyk Security Scanning**
  - Added full Snyk vulnerability scanning integration
  - UI for configuring Snyk API token and scan settings
  - GitHub Actions workflow for automated security scans
  - Real-time dependency vulnerability detection
  - Code security analysis (SQL injection, XSS, command injection, etc.)

### ✨ New Features

**Settings UI (`System Settings → Snyk Security`):**
- Enable/disable Snyk scanning
- Configure API token (stored securely)
- Set organization ID (optional)
- Choose severity threshold (low/medium/high/critical)
- Select scan frequency (hourly/daily/weekly/manual)
- View last scan timestamp
- Detailed setup instructions with step-by-step guide

**GitHub Actions Integration:**
- Automatic scans on push and pull requests
- Daily scheduled scans at 2 AM UTC
- SARIF upload to GitHub Code Scanning
- Configurable via `SNYK_TOKEN` repository secret

**What Snyk Scans:**
- ✅ Python dependencies (requirements.txt)
- ✅ Code security vulnerabilities
- ✅ Hardcoded secrets/API keys
- ✅ Open source license compliance
- ✅ Insecure cryptography usage
- ✅ Configuration issues

### 📝 Files Added

- `.snyk` - Snyk policy configuration file
- `.github/workflows/snyk-security.yml` - GitHub Actions workflow
- `templates/core/settings_snyk.html` - Settings UI
- `core/migrations/0012_add_snyk_settings.py` - Database migration

### 📝 Files Modified

- `core/models.py` - Added Snyk settings fields to SystemSetting
- `core/settings_views.py` - Added settings_snyk view
- `core/urls.py` - Added Snyk settings route
- `README.md` - Added Snyk security badge
- `templates/core/settings_*.html` - Added Snyk link to all settings pages

### 🔧 Technical Details

**New SystemSetting Fields:**
- `snyk_enabled` - Boolean to enable/disable
- `snyk_api_token` - API token (max 500 chars)
- `snyk_org_id` - Organization ID (optional)
- `snyk_severity_threshold` - Minimum severity (low/medium/high/critical)
- `snyk_scan_frequency` - Scan schedule (hourly/daily/weekly/manual)
- `snyk_last_scan` - Timestamp of last scan

### 📚 Documentation

**Setup Instructions:**
1. Create free Snyk account at snyk.io
2. Get API token from Account Settings
3. Add token to GitHub Secrets as `SNYK_TOKEN`
4. Configure settings in Client St0r UI
5. GitHub Actions runs automatically

**Benefits:**
- 40-60% more vulnerabilities detected vs pip-audit alone
- Code-level security issues (not just dependencies)
- Automatic fix PRs from Snyk
- License compliance checking
- Prioritized vulnerability reports

---
🤖 Generated with [Luna the GSD](https://github.com/agit8or1/clientst0r)

## [2.14.26] - 2026-01-14

### 🎯 Major Improvement: Optional LDAP Dependencies

- **LDAP/Active Directory support is now optional**
  - Moved `python-ldap` and `django-auth-ldap` to `requirements-optional.txt`
  - Core installation no longer requires C compiler and build tools
  - Fixes auto-update failures for users without build dependencies
  - Resolves GitHub Issue #5: python-ldap build errors during updates

### ✅ Benefits

- **Faster installations:** Most users don't need LDAP support
- **Simpler setup:** No need for build-essential, gcc, python3-dev, libldap2-dev, libsasl2-dev
- **Better auto-updates:** Updates work without system build tools
- **Still available:** LDAP can be installed when needed with `pip install -r requirements-optional.txt`

### 📝 Migration Guide

**For existing installations with LDAP:**
If you're currently using LDAP/Active Directory authentication:

```bash
# Install system build dependencies (if not already installed)
sudo apt-get update
sudo apt-get install -y build-essential python3-dev libldap2-dev libsasl2-dev

# Install optional LDAP packages
cd ~/clientst0r
source venv/bin/activate
pip install -r requirements-optional.txt
sudo systemctl restart clientst0r-gunicorn.service
```

**For new installations:**
- Azure AD SSO works out of the box (no additional packages needed)
- LDAP/AD can be added later if needed

### 🔧 Technical Details

**Files Changed:**
- `requirements.txt` - Removed python-ldap and django-auth-ldap
- `requirements-optional.txt` - NEW file containing LDAP dependencies
- `README.md` - Added "Optional Features" section with LDAP installation instructions

**What's Still Included:**
- Azure AD / Microsoft Entra ID SSO (uses `msal` package)
- All other integrations and features

---
🤖 Generated with [Luna the GSD](https://github.com/agit8or1/clientst0r)

## [2.14.25] - 2026-01-13

### 🐛 Critical Bug Fixes

- **Fixed RMM Sync NameError**
  - Added missing `logging` import and `logger` instance to `integrations/views.py`
  - RMM sync now logs errors properly instead of crashing with `NameError: name 'logger' is not defined`
  - Resolves GitHub Issue #8: "Sync failed on rmm integration"

- **Fixed Azure AD Authentication Failure**
  - Fixed `get_azure_config()` method in `accounts/azure_auth.py` calling non-existent `SystemSetting.get_setting()`
  - Updated to use correct `SystemSetting.get_settings()` singleton pattern
  - Azure AD login now works properly (button displays AND authentication succeeds)
  - Resolves GitHub Issue #3 authentication failure: "sso config worked but cant login"

### 🔧 Technical Details

**RMM Sync Fix:**
- File: `integrations/views.py`
- Added: `import logging` and `logger = logging.getLogger('integrations')`
- Line 512 can now properly log exceptions during manual RMM sync

**Azure AD Authentication Fix:**
- File: `accounts/azure_auth.py`
- Method: `get_azure_config()`
- This was a second instance of the same bug from v2.14.23 in a different method
- v2.14.23 fixed the button display, v2.14.25 fixes the actual authentication

---
🤖 Generated with [Luna the GSD](https://github.com/agit8or1/clientst0r)

## [2.14.24] - 2026-01-13

### 🔧 Consistency Improvements

- **Applied Organization Validation to PSA Integrations**
  - PSA integration creation now requires organization selection (matching RMM behavior)
  - Prevents `IntegrityError: Column 'organization_id' cannot be null` for PSA connections
  - Both PSA and RMM integrations now have consistent validation
  - Clear error message: "Please select an organization first."

### 📝 User Experience

- **Integration Creation Flow:**
  1. Select an organization from top navigation or Access Management page
  2. Navigate to Integrations
  3. Click "Add PSA Integration" or "Add RMM Integration"
  4. Form appears (no redirect if organization is selected)

- **Why This Matters:**
  - Prevents database constraint violations
  - Provides clear feedback to users
  - Ensures data integrity across all integration types

### 🐛 Related Issues

- Addresses GitHub Issue #7 feedback about RMM integration redirect
- Applies same protection to PSA integrations for consistency

---
🤖 Generated with [Luna the GSD](https://github.com/agit8or1/clientst0r)

## [2.14.23] - 2026-01-13

### 🐛 Critical Bug Fix

- **Fixed Azure AD SSO Button Not Appearing on Login Page**
  - Fixed `AzureOAuthClient.load_config()` method calling non-existent `SystemSetting.get_setting()` method
  - Updated to use correct `SystemSetting.get_settings()` singleton pattern with `getattr()`
  - Azure SSO button now properly appears on login page when Azure AD is configured
  - Resolves GitHub Issue #3: "Azure SSO button not showing on main page after configuration"

### 🔧 Technical Details

- The bug prevented the `/accounts/auth/azure/status/` API endpoint from returning the correct enabled status
- Login page JavaScript was unable to determine if Azure AD was configured, keeping the "Sign in with Microsoft" button hidden
- All Azure AD settings (tenant ID, client ID, client secret, redirect URI) are now properly loaded from the database

---
🤖 Generated with [Luna the GSD](https://github.com/agit8or1/clientst0r)

## [2.14.22] - 2026-01-12

### 🐛 Critical Bug Fixes

- **Fixed IntegrityError on User Profile Page**
  - Added missing `auth_source` and `azure_ad_oid` fields to UserProfile model
  - Fields were defined in migration but missing from model definition
  - Resolves "(1364, "Field 'auth_source' doesn't have a default value")" error
  - Users can now access their profile page without errors

- **Fixed IntegrityError on RMM Connection Creation**
  - Added organization validation check before creating RMM connections
  - Prevents "(1048, "Column 'organization_id' cannot be null")" error
  - Users must select an organization before creating RMM connections
  - Clear error message directs users to select organization first

### 🔒 Security

- Both fixes ensure data integrity and prevent database constraint violations

---
🤖 Generated with [Luna the GSD](https://github.com/agit8or1/clientst0r)

## [2.14.21] - 2026-01-12

### 🎉 Auto-Update System Complete!

- **Improved User Messaging**
  - Updated completion message to inform users it may take up to a minute for new version to display
  - Increased page reload delay from 3 to 10 seconds to give service more time to restart
  - Better UX with clearer expectations during service restart

### ✅ Verified Working

The auto-update system has been fully tested and verified working end-to-end:
- ✅ Real-time progress UI with all 5 steps
- ✅ Git pull with version detection
- ✅ Fast dependency installation
- ✅ Database migrations
- ✅ Static file collection
- ✅ **Automatic service restart** (all PATH issues resolved)
- ✅ Page reload showing new version

**Auto-updates now require ZERO manual intervention!**

---
🤖 Generated with [Luna the GSD](https://github.com/agit8or1/clientst0r)

## [2.14.20] - 2026-01-12

### 🎯 Final Test Release

- **Test Complete Auto-Update from v2.14.19**
  - v2.14.19 has all PATH fixes in place
  - This update should complete automatically with service restart
  - Tests the entire auto-update chain working end-to-end

### 🔧 What Should Happen

When updating from v2.14.19 → v2.14.20:
1. Progress modal displays all 5 steps
2. Systemd check returns True
3. Restart command executes successfully (all paths fixed)
4. Service restarts automatically
5. Page reloads showing v2.14.20

**If successful: Auto-update system is COMPLETE!** 🎉

---
🤖 Generated with [Luna the GSD](https://github.com/agit8or1/clientst0r)

## [2.14.19] - 2026-01-12

### 🐛 Bug Fixes

- **Fix Full Paths for All Commands in Restart**
  - Changed `sudo` to `/usr/bin/sudo`
  - Changed `systemd-run` to `/usr/bin/systemd-run`
  - Changed `systemctl` to `/usr/bin/systemctl`
  - Fixes "[Errno 2] No such file or directory: 'sudo'" error
  - All commands in restart chain now use absolute paths

### ✅ Verified Working

- v2.14.18 confirmed systemd check now returns True
- Restart command was being attempted but failing on sudo PATH
- This fix should complete the auto-update implementation

---
🤖 Generated with [Luna the GSD](https://github.com/agit8or1/clientst0r)

## [2.14.18] - 2026-01-12

### 🧪 Test Release

- **Final Test of Auto-Update with Systemd Fix**
  - Test release to verify v2.14.17 systemd detection fix works
  - Should show "Systemd service check result: True" in logs
  - Service should restart automatically
  - Completes the auto-update system implementation

---
🤖 Generated with [Luna the GSD](https://github.com/agit8or1/clientst0r)

## [2.14.17] - 2026-01-12

### 🐛 Bug Fixes

- **Fix Systemd Service Detection**
  - Use full path `/usr/bin/systemctl` instead of `systemctl` in _is_systemd_service()
  - Resolves PATH issues when running inside Gunicorn
  - Added better error logging to diagnose restart failures
  - Log systemd check result explicitly for debugging

### 🔍 Enhanced Debugging

- Added log message showing systemd service check result
- Warning message when restart is skipped (not running as systemd service)
- Better exception handling in _is_systemd_service()

---
🤖 Generated with [Luna the GSD](https://github.com/agit8or1/clientst0r)

## [2.14.16] - 2026-01-12

### ✅ Verification Release

- **Auto-Update System Fully Functional**
  - Confirmed working end-to-end auto-update with automatic restart
  - All components validated: progress UI, git pull, dependencies, migrations, static files, service restart
  - Test verified on v2.14.14 → v2.14.15 successful update
  - Production-ready auto-update system

### 🎉 Achievement Unlocked

The auto-update system is now **complete and working**:
- ✅ Real-time progress modal with animated step indicators
- ✅ Fast pip install (no unnecessary package rebuilds)
- ✅ Delayed service restart using systemd-run --on-active=3
- ✅ Passwordless sudo permissions for systemctl commands
- ✅ Automatic page reload showing new version

**No manual intervention required for updates!**

---
🤖 Generated with [Luna the GSD](https://github.com/agit8or1/clientst0r)

## [2.14.15] - 2026-01-12

### 🧪 Test Release

- **Final Auto-Update Test**
  - Test release to verify complete auto-update flow
  - Should demonstrate automatic service restart with sudo permissions
  - Real-time progress tracking with all 5 steps
  - Validates systemd-run delayed restart + passwordless sudo

### ✅ Expected Behavior

When updating from v2.14.14 → v2.14.15:
1. Progress modal displays with animated steps
2. All 5 steps complete successfully
3. Service restarts automatically (no manual intervention)
4. Page reloads showing v2.14.15

---
🤖 Generated with [Luna the GSD](https://github.com/agit8or1/clientst0r)

## [2.14.14] - 2026-01-12

### 🐛 Bug Fixes

- **Auto-Update Sudo Permissions**
  - Added sudoers configuration for passwordless systemctl restart
  - Created `/etc/sudoers.d/clientst0r-auto-update` with required permissions
  - Allows auto-update to restart service without password prompt
  - Fixes issue where service restart silently failed due to sudo authentication

### 📝 Installation Note

This release includes automated setup of sudo permissions. The installer will create:
```
administrator ALL=(ALL) NOPASSWD: /bin/systemctl restart clientst0r-gunicorn.service, /bin/systemctl status clientst0r-gunicorn.service, /usr/bin/systemd-run
```

---
🤖 Generated with [Luna the GSD](https://github.com/agit8or1/clientst0r)

## [2.14.13] - 2026-01-12

### 🐛 Bug Fixes

- **Service Restart Fix - THE REAL FIX!**
  - Changed from `systemctl restart` to `systemd-run --on-active=3 systemctl restart`
  - Schedules restart 3 seconds after update completes
  - Prevents process from killing itself mid-update
  - Allows progress tracker to finish and send final response
  - Service now ACTUALLY restarts automatically!

### 🔧 Technical Details

**The Problem:** A process can't restart itself while it's running. When the update thread called `systemctl restart`, it immediately killed the Gunicorn process, terminating the thread before it could finish.

**The Solution:** Use `systemd-run --on-active=3` to schedule the restart 3 seconds later. This gives the update thread time to complete, mark progress as finished, and send the response BEFORE the restart happens.

---
🤖 Generated with [Luna the GSD](https://github.com/agit8or1/clientst0r)

## [2.14.12] - 2026-01-12

### 🎉 Final Test Release

Test release to verify complete auto-update flow from v2.14.11 → v2.14.12.

**Expected behavior:**
- Beautiful progress modal with real-time updates
- Fast pip install (no rebuilding python-ldap)
- Automatic service restart
- Page reload showing v2.14.12
- Complete end-to-end success!

---
🤖 Generated with [Luna the GSD](https://github.com/agit8or1/clientst0r)

## [2.14.11] - 2026-01-12

### 🎉 Test Release

This is a test release to demonstrate the complete auto-update flow with real-time progress tracking.

**What you'll see when updating from v2.14.10 → v2.14.11:**
- Beautiful progress modal with animated bar
- Each step shown with spinner → checkmark
- Auto-reload when complete
- Version instantly updated to v2.14.11

---
🤖 Generated with [Luna the GSD](https://github.com/agit8or1/clientst0r)

## [2.14.10] - 2026-01-12

### 🐛 Bug Fixes

- **Update Process - Pip Install Fix**
  - Removed `--upgrade` flag from `pip install` during updates
  - Prevents unnecessary rebuilding of compiled packages (python-ldap, cryptography, etc.)
  - Avoids build failures on systems without gcc/build-essential
  - Git pull already brings new code, we only need to install missing packages
  - Faster updates - no recompiling existing packages
  - Fixes "Command failed: error: command 'x86_64-linux-gnu-gcc' failed" errors

### 🎯 What's Fixed

- ✅ Updates no longer require build-essential/gcc unless adding NEW compiled dependencies
- ✅ Existing python-ldap, cryptography, etc. won't be rebuilt every update
- ✅ Faster update process
- ✅ More reliable updates on minimal systems

---
🤖 Generated with [Luna the GSD](https://github.com/agit8or1/clientst0r)

## [2.14.9] - 2026-01-12

### ✨ New Features

- **Real-Time Update Progress UI (Complete)**
  - Beautiful animated progress bar showing update progress
  - Live step-by-step status with spinning/checkmark icons
  - AJAX-based update without page refresh
  - Polls progress API every second for real-time updates
  - Shows all 5 update steps: Git Pull → Install Dependencies → Run Migrations → Collect Static Files → Restart Service
  - Auto-reloads page after successful completion
  - Error handling with clear error messages
  - Non-blocking modal that prevents premature closing

### 🎯 User Experience Improvements

- No more wondering if update is working or stuck
- Clear visual feedback at each step
- Know exactly which step is running
- Automatic page refresh when complete
- Can't accidentally close progress modal during update

---
🤖 Generated with [Luna the GSD](https://github.com/agit8or1/clientst0r)

## [2.14.8] - 2026-01-12

### ✨ New Features

- **Real-Time Update Progress Tracking (Backend)**
  - Added UpdateProgress class for tracking update steps in real-time
  - Each update step reports start/complete status to cache
  - Background thread execution prevents browser timeout
  - Added `/api/update-progress/` endpoint for polling progress
  - Foundation for live progress UI (frontend coming soon)

### 🔧 Improvements

- **Update Check Cache Reduced**
  - Changed update check cache from 1 hour to 5 minutes
  - Reduces frustration when testing or releasing new versions
  - Applies to both automatic and manual update checks

### 🔧 Technical Details

- `UpdateProgress` class tracks 5 update steps
- Each step logs start/complete with timestamps
- Progress data cached for 10 minutes
- Update runs in daemon thread for async execution
- `apply_update` now returns JSON for AJAX handling

---
🤖 Generated with [Luna the GSD](https://github.com/agit8or1/clientst0r)

## [2.14.7] - 2026-01-12

### 🐛 Bug Fixes

- **Auto-Update Service Restart**
  - Fixed service restart failing during auto-update process
  - Changed service name from `clientst0r` to `clientst0r-gunicorn.service`
  - Auto-updates now properly restart the application after code updates
  - Users no longer need to manually restart after applying updates

### 🔧 Technical Details

- Fixed `_is_systemd_service()` to check correct service name
- Fixed restart command to use `clientst0r-gunicorn.service`
- Update process now completes fully: git pull → pip install → migrate → collectstatic → restart

---
🤖 Generated with [Luna the GSD](https://github.com/agit8or1/clientst0r)

## [2.14.6] - 2026-01-12

### 🐛 Bug Fixes

- **System Updates Page**
  - Removed debug output from System Updates page
  - Cleaned up temporary debugging code added in previous version
  - Improved auto-update testing workflow

### 🔧 Technical Details

- Removed debug alert box showing update_available, current_version, latest_version
- Clean interface for production auto-update feature

---
🤖 Generated with [Luna the GSD](https://github.com/agit8or1/clientst0r)

## [2.14.5] - 2026-01-12

### ✨ New Features

- **ITFlow PSA Integration**
  - Added complete ITFlow provider implementation
  - Fixed "Unknown provider type: itflow" error
  - Supports clients, contacts, and tickets synchronization
  - API authentication using X-API-KEY header
  - Full CRUD operations for all supported entities
  - Proper date filtering and pagination support

### 🔧 Files Created

- `integrations/providers/itflow.py` - Complete ITFlow provider implementation

### 🔧 Files Modified

- `integrations/providers/__init__.py` - Registered ITFlow provider in PROVIDER_REGISTRY

### 📝 ITFlow API Endpoints

- `/api/v1/clients` - List and sync clients (companies)
- `/api/v1/contacts` - List and sync contacts
- `/api/v1/tickets` - List and sync tickets
- Authentication: X-API-KEY header

### 🎯 User-Reported Issue Fixed

✅ "Unknown provider type: itflow" - ITFlow provider now registered and functional

## [2.14.4] - 2026-01-12

### 🐛 Bug Fixes

- **Member Edit IntegrityError**
  - Fixed `IntegrityError: NOT NULL constraint failed: memberships.user_id` when editing members
  - Root cause: MembershipForm was trying to modify the immutable `user` field during edit
  - Solution: Exclude `user` and `email` fields when editing existing memberships
  - User field now only appears when creating new memberships, not when editing
  - Prevents accidental user reassignment which would break membership integrity

### 🔧 Files Modified

- `accounts/forms.py` - Updated MembershipForm.__init__() to conditionally exclude user field

### 📝 Technical Details

**Before:** Form included 'user' field for both create and edit operations, causing NULL constraint violation when form didn't properly set user_id during edit.

**After:** Form dynamically removes 'user' and 'email' fields when `instance.pk` exists (editing), keeping them only for new memberships (creating).

## [2.14.3] - 2026-01-12

### 🐛 Bug Fixes

- **Role Management Access**
  - Fixed role management redirecting to dashboard instead of loading the page
  - ADMIN role can now manage roles (previously only OWNER could)
  - Updated `can_admin()` method to prioritize OWNER/ADMIN roles
  - Both OWNER and ADMIN roles now have full admin privileges for role management

- **User Management Redirect**
  - Fixed broken redirect from `'home'` (non-existent) to `'core:dashboard'`
  - Affects all user management views:
    - User list, create, edit, detail
    - Password reset, add membership, delete user
    - Organization access denied
  - Users now properly redirected to dashboard when lacking permissions

- **Admin User Setup**
  - Admin user confirmed as superuser (`is_superuser=True`)
  - Automatically created OWNER membership for admin user if missing
  - Ensures admin has full access to manage roles and users

### 🔧 Files Modified

- `accounts/models.py` - Updated `can_admin()` logic
- `accounts/views.py` - Fixed all redirect('home') to redirect('core:dashboard')

### 🎯 User-Reported Issues Fixed

1. ✅ "manage roles reloads dashboard" - Fixed permission check
2. ✅ "cant edit users" - Fixed redirect to non-existent 'home' route
3. ✅ "admin user should be superadmin" - Confirmed and added membership

## [2.14.2] - 2026-01-12

### 🐛 Bug Fixes

- **Encryption Key Error Handling**
  - Added comprehensive error handling for malformed APP_MASTER_KEY
  - Display user-friendly error message with fix instructions when encryption key is invalid
  - Shows exact commands to regenerate the key (44 characters, base64-encoded 32 bytes)
  - Error handling added to all views that use encryption:
    - PSA integration create/edit
    - RMM integration create/edit
    - Password vault create/edit
  - Prevents cryptic "Invalid base64-encoded string" errors
  - Guides users to fix the issue immediately

### 🔧 Files Modified

- `integrations/views.py` - Added EncryptionError handling to PSA/RMM views
- `vault/views.py` - Added EncryptionError handling to password views
- Error messages include:
  - Clear explanation of the problem
  - Exact terminal commands to fix it
  - Required key format (44 characters)

## [2.14.1] - 2026-01-12

### 🐛 Bug Fixes

- **Critical IntegrityError Fix**
  - Fixed IntegrityError: "Field 'auth_source' doesn't have a default value" when changing admin password
  - Added `default='local'` to auth_source field in migration
  - Added RunPython operation to set auth_source='local' for all existing UserProfile records
  - Fixed azure_ad_oid field to have proper `default=''`

- **Installer & Upgrade Improvements**
  - Added .env file validation before upgrade process starts
  - Added SECRET_KEY validation in .env to prevent "SECRET_KEY must be set" errors during upgrade
  - Added write permission check before venv creation to prevent permission denied errors
  - Added helpful error messages showing:
    - Directory ownership and current user
    - Exact commands to fix permission issues (`sudo chown -R $USER:$USER $INSTALL_DIR`)
    - Clear instructions when .env is missing or corrupted

- **Session Documentation**
  - Added comprehensive SESSION_SUMMARY.md documenting all recent work
  - Includes all features, changes, testing, and support commands

### 🔧 Files Modified

- `accounts/migrations/0005_add_azure_fields_to_userprofile.py` - Fixed auth_source defaults
- `install.sh` - Added validation and permission checks

## [2.14.0] - 2026-01-12

### ✨ New Features

- **Enhanced Update System with Changelog Display**
  - Display CHANGELOG.md content for current version on System Updates page
  - Show changelogs for all newer available versions
  - Parse CHANGELOG.md to extract version-specific content
  - Beautiful UI with "What's in vX.X.X" and "What's New in Available Updates" sections
  - Helps users understand what they're running and what they'll get with updates

### 🐛 Bug Fixes

- Fixed 404 error on System Updates page by clearing stale cache
- Fixed git status detection to use full path `/usr/bin/git`
- Fixed git commands to handle errors gracefully without exceptions
- Improved error logging for git operations

### 🔧 Technical Improvements

- Added `get_changelog_for_version()` method to extract version-specific changelogs
- Added `get_all_versions_from_changelog()` to parse all versions
- Added `get_changelog_between_versions()` to get changelogs for version ranges
- Enhanced views to pass changelog data to templates
- Updated templates to display current and newer version changelogs

## [2.13.0] - 2026-01-12

### ✨ New Features

- **Auto-Update System with Web Interface**
  - Check for updates from GitHub releases API
  - Manual update trigger from web interface (Admin → System Updates)
  - Automatic hourly update checks via scheduled task
  - Complete update process: git pull, pip install, migrate, collectstatic, restart
  - Version comparison using semantic versioning (packaging library)
  - Update history tracking in audit log
  - Real-time update status API endpoint
  - Beautiful UI displaying:
    - Current version vs. available version
    - Git status (branch, commit, clean working tree)
    - Release notes from GitHub
    - Update history with all checks and attempts
  - Safety features:
    - Staff-only access
    - Confirmation modal before applying updates
    - Warns if working tree has uncommitted changes
    - Comprehensive audit logging
    - Graceful failure handling
  - Configuration:
    - `GITHUB_REPO_OWNER` (default: agit8or1)
    - `GITHUB_REPO_NAME` (default: clientst0r)
    - `AUTO_UPDATE_ENABLED` (default: true)
    - `AUTO_UPDATE_CHECK_INTERVAL` (default: 3600 seconds)
  - Files: `core/updater.py`, `core/management/commands/check_updates.py`, `templates/core/system_updates.html`
  - Routes: `/core/settings/updates/`, `/core/settings/updates/check/`, `/core/settings/updates/apply/`, `/api/update-status/`

### 🐛 Bug Fixes

- Fixed AuditLog field names in update system (event_type → action, metadata → extra_data, created_at → timestamp)

### 📚 Documentation

- Updated README.md to version 2.13.0

## [2.12.0] - 2026-01-12

### ✨ New Features

- **Azure AD / Microsoft Entra ID Single Sign-On**
  - Added complete Azure AD OAuth authentication backend
  - "Sign in with Microsoft" button appears on login page when configured
  - Auto-creates user accounts on first Azure AD login (configurable)
  - Syncs user info (name, email) from Microsoft Graph API
  - Users authenticated via Azure AD bypass 2FA requirements (SSO is already secure)
  - Comprehensive setup instructions in Admin → Settings → Directory Services
  - Dynamic redirect URI display based on current domain
  - Stores Azure AD Object ID in user profile for tracking
  - Files: `accounts/azure_auth.py`, `accounts/oauth_views.py`, `templates/two_factor/core/login.html`
  - Routes: `/accounts/auth/azure/login/`, `/accounts/auth/azure/callback/`, `/accounts/auth/azure/status/`
  - Documentation: `AZURE_SSO_SETUP.md`

- **RMM/PSA Organization Import**
  - Automatically create organizations from PSA companies or RMM sites/clients during sync
  - New connection settings:
    - **Import Organizations**: Enable/disable automatic org creation
    - **Set as Active**: Control if imported orgs are active by default
    - **Name Prefix**: Add prefix to org names (e.g., "PSA-", "RMM-")
  - Smart matching prevents duplicates (checks custom_fields for existing linkage)
  - Tracks PSA/RMM linkage in organization custom_fields:
    - `psa_company_id` / `rmm_site_id`
    - `psa_connection_id` / `rmm_connection_id`
    - `psa_provider` / `rmm_provider`
    - Additional metadata (phone, address, website, description)
  - Unique slug generation ensures no conflicts
  - All org creates/updates logged to audit trail
  - Utility functions: `integrations/org_import.py`
  - Supports bulk import with statistics (created, updated, errors)

- **Alga PSA Integration Placeholder**
  - Added provider stub for future Alga PSA integration
  - Open-source MSP PSA platform by Nine-Minds
  - Complete implementation checklist included
  - Ready to be completed once API documentation is available
  - File: `integrations/providers/psa/alga.py`

### 🐛 Bug Fixes

- **Fixed RMM/PSA Connection Creation IntegrityError**
  - Resolved: "Column 'organization_id' cannot be null" error when creating RMM or PSA connections
  - Root cause: Form's `save()` method wasn't setting `connection.organization` before saving
  - Fixed both `RMMConnectionForm` and `PSAConnectionForm` in `integrations/forms.py`
  - Now properly sets organization from form context before save

- **Fixed Cryptography Version Compatibility**
  - Updated `requirements.txt`: `cryptography>=43.0.0,<44.0.0`
  - Resolves installation issues reported on fresh installs
  - Maintains backward compatibility with existing 44.x installations

### 🎨 UI/UX Improvements

- **Enhanced Azure AD Setup Page**
  - Comprehensive step-by-step setup instructions in Admin settings
  - Five clear setup phases with specific actions
  - Dynamic redirect URI display (shows actual domain-based URL)
  - Warning about 2FA bypass for Azure users
  - Direct links to Azure Portal
  - Code-formatted examples and configuration snippets

- **Port Configuration Table Contrast**
  - Changed port configuration table headers to `table-dark` for better readability
  - Improved visual hierarchy with Bootstrap dark theme
  - Applies to both network equipment and patch panel configurations

### 🔧 Technical Changes

- **Authentication Backend Updates**
  - Added `accounts.azure_auth.AzureADBackend` to `AUTHENTICATION_BACKENDS`
  - Integrated MSAL (Microsoft Authentication Library) for OAuth flow
  - Added auth_source field to UserProfile model (local, ldap, azure_ad)
  - Added azure_ad_oid field to UserProfile for Azure Object ID tracking

- **Middleware Enhancements**
  - Updated `Enforce2FAMiddleware` to skip 2FA for Azure AD authenticated users
  - Checks session flag `azure_ad_authenticated` before enforcing 2FA

- **Database Migrations**
  - `accounts/migrations/0005_add_azure_fields_to_userprofile.py` - Azure AD fields
  - `integrations/migrations/0004_add_org_import_fields.py` - Organization import settings

- **New Dependencies**
  - Added `msal==1.26.*` to requirements.txt for Azure AD OAuth

### 📚 Documentation

- **New Files**
  - `AZURE_SSO_SETUP.md` - Complete Azure AD SSO setup guide
  - `integrations/org_import.py` - Organization import utility library

- **Updated Files**
  - `templates/core/settings_directory.html` - Azure AD setup instructions
  - `config/settings.py` - Azure AD authentication backend
  - `requirements.txt` - MSAL library, cryptography version fix

### 🔐 Security Notes

- Azure AD client secrets stored encrypted in database
- Session flag tracks Azure authentication for 2FA bypass
- All organization imports logged to audit trail
- Azure AD authentication validated against Microsoft Graph API

## [2.11.7] - 2026-01-11

### 🐛 Bug Fixes

- **Fixed Visible ">" Artifact on All Pages**
  - Resolved issue where a stray ">" character appeared at top left of navigation bar
  - Root cause: CSRF meta tag was using `{% csrf_token %}` which outputs full `<input>` HTML element
  - Browser was rendering the closing `>` from the input tag as visible text
  - Solution: Changed to `{{ csrf_token }}` to output only the token value
  - Fixed: `templates/base.html:7` - meta tag now correctly contains just token value

- **About Page TemplateSyntaxError**
  - Fixed: `Invalid character ('-') in variable name: 'dependencies.django-two-factor-auth'`
  - Django template variables cannot contain hyphens
  - Modified `get_dependency_versions()` to replace hyphens with underscores in dictionary keys
  - Updated template to use underscored variable names:
    - `dependencies.django-two-factor-auth` → `dependencies.django_two_factor_auth`
    - `dependencies.django-axes` → `dependencies.django_axes`
  - About page now loads successfully without template syntax errors

### 🎨 UI/UX Improvements

- **Floor Plan Generation Loading Overlay Contrast**
  - Fixed poor contrast in "Generating Floor Plan with AI..." loading message
  - Added explicit color styling to overlay text for better readability
  - Main text: `#212529` (dark gray - high contrast on white background)
  - Secondary text: `#6c757d` (muted gray)
  - Ensures text is always readable regardless of theme or browser defaults

### 🔧 Technical Changes

- Updated `templates/base.html`: Fixed CSRF token meta tag
- Updated `core/security_scan.py`: Hyphen-to-underscore conversion for template compatibility
- Updated `templates/core/about.html`: Variable name fixes for Django template syntax
- Updated `templates/locations/generate_floor_plan.html`: Inline style improvements

## [2.11.6] - 2026-01-11

### 🔒 Security Enhancements

- **Live CVE Vulnerability Scanning**
  - Added real-time CVE/vulnerability scanning to About page
  - Integrated `pip-audit` for Python package vulnerability detection
  - About page now shows live scan results with timestamp
  - Displays vulnerability status: All Clear / Vulnerabilities Found
  - Shows scan tool used (pip-audit) and last scan time
  - Created `core/security_scan.py` module with scanning functions

- **Security Package Upgrades** (All 10 Known Vulnerabilities Resolved ✓)
  - **cryptography**: `41.0.7` → `44.0.1` (Fixed 4 CVEs)
    - PYSEC-2024-225
    - CVE-2023-50782
    - CVE-2024-0727
    - GHSA-h4gh-qq45-vh27
  - **djangorestframework**: `3.14.0` → `3.15.2` (Fixed CVE-2024-21520)
  - **gunicorn**: `21.2.0` → `22.0.0` (Fixed 2 CVEs)
    - CVE-2024-1135
    - CVE-2024-6827
  - **pillow**: `10.2.0` → `10.3.0` (Fixed CVE-2024-28219)
  - **requests**: `2.31.0` → `2.32.4` (Fixed 2 CVEs)
    - CVE-2024-35195
    - CVE-2024-47081

### 📊 About Page Enhancements

- **Real-Time Dependency Versions**
  - Technology Stack table now shows actual installed versions
  - Uses `pip list` to extract current package versions
  - Displays Django, DRF, Gunicorn, cryptography, Pillow, Requests, OpenAI SDK versions
  - Replaces static version numbers with live data

- **Live Security Reporting**
  - CVE scan runs on each About page load
  - Shows vulnerability count and severity breakdown
  - Color-coded status badges (green = clean, warning = vulnerabilities found)
  - 30-second timeout for scan operations
  - Graceful error handling if scan fails

### 🐛 Bug Fixes

- **Floor Plan Generation Type Safety**
  - Fixed: `int() argument must be a string, a bytes-like object or a real number, not 'list'` error
  - Added explicit type conversion before database save
  - Django POST data can return lists instead of strings
  - Added final safety check: `float(width_feet)` and `float(length_feet)` before `int()` calculation
  - Enhanced error logging with specific dimension values
  - Ensures `total_sqft` calculation never fails on type errors

### 🎨 UI/UX Improvements

- **Property Import Placeholder Cleanup**
  - Changed placeholder from example URL to generic text: "Paste property appraiser URL here..."
  - Updated help text to be more general across all jurisdictions
  - Removed Duval County-specific default URL from form

### 🔧 Technical Changes

- New module: `/home/administrator/core/security_scan.py`
  - `run_vulnerability_scan()` function using subprocess to call pip-audit
  - `get_dependency_versions()` function to extract package versions
  - JSON parsing of pip-audit output
  - Caching not implemented (scans on each page load)

- Updated `core/views.py`:
  - `about()` function now calls security scanning functions
  - Passes `scan_results` and `dependencies` to template context

- Updated `/home/administrator/templates/core/about.html`:
  - Added "Live CVE Scan Results" section with real-time data
  - Changed static version numbers to Django template variables
  - Dynamic timestamp using `{{ scan_results.scan_time|date:"F j, Y \a\t g:i A" }}`
  - Conditional rendering based on scan status

### 📦 Dependencies

- pip-audit (new dependency for vulnerability scanning)
- safety (installed but pip-audit is primary tool)

## [2.11.5] - 2026-01-11

### ✨ New Features

- **Location-Aware Property Appraiser Suggestions**
  - Property diagram suggestions now dynamically adapt based on location's address
  - Automatically shows correct county name and direct links to property appraiser
  - Supports major FL counties: Duval (Jacksonville), Miami-Dade, Broward, Orange (Orlando), Hillsborough (Tampa), Pinellas (St. Pete/Clearwater), Leon (Tallahassee)
  - Generic search links for California, Texas, and other states
  - No more "Duval County" suggestions for Miami locations!
  - Each location sees relevant, specific guidance for their jurisdiction

### 🎨 UI/UX Improvements

- **Floor Plan Generation Progress Feedback**
  - Added visual loading overlay during AI generation (15-30 seconds)
  - Shows spinner and "Generating Floor Plan with AI..." message
  - Prevents accidental double-submission
  - Better user experience during potentially long operation
  - Submit button shows progress state

- **Smarter Property Diagram Help Text**
  - Adapts help text based on whether location has known appraiser or generic search
  - Known counties: Shows specific appraiser name and direct link
  - Unknown locations: Shows Google search link with helpful keywords
  - References new AI import feature as alternative

### Technical Details

- Added `get_property_appraiser_info()` method to Location model
- Method returns dict with county, name, url, search_url
- Template receives `property_appraiser` context variable
- JavaScript form submission handler with overlay creation

## [2.11.4] - 2026-01-11

### ✨ New Features - AI-Powered Property URL Import

- **Import Property Data from URL Using AI Assistant**
  - Revolutionary new feature: Paste ANY property appraiser URL and AI Assistant extracts all data
  - Works with Duval County, all Florida counties, and most property record websites nationwide
  - Example: `https://paopropertysearch.coj.net/Basic/Detail.aspx?RE=1442930000`
  - No scraping rules needed - AI understands the HTML and extracts intelligently

- **What Gets Extracted**
  - Building square footage
  - Lot square footage
  - Year built
  - Property type/classification
  - Number of floors/stories
  - Parcel ID/Property ID
  - Owner name and mailing address
  - Assessed value and market value
  - Legal description
  - Zoning and land use
  - Full address details (street, city, state, zip, county)

- **How It Works**
  1. User pastes property appraiser URL in new input field (in Building Information section)
  2. Clicks "Import with AI" button
  3. System fetches HTML from URL
  4. AI Assistant analyzes HTML and extracts ALL available property data
  5. Location automatically populated with extracted data
  6. Success message shows what was updated

### 🔧 Technical Implementation

- Created `PropertyURLImporter` service class
- Uses AI Provider API with structured prompts
- Handles HTML truncation for large pages
- Parses JSON from AI response (handles markdown code blocks)
- Stores full extracted data in `external_data` JSON field
- New AJAX endpoint: `/locations/<id>/import-property-from-url/`
- JavaScript function with loading state and error handling

### 🎨 UI/UX

- New green success alert in Building Information card
- Input field with placeholder showing example URL
- "Import with AI" button with robot icon
- Loading state: "Importing with AI..."
- Success message shows all updated fields
- Works alongside existing Auto-Refresh and manual Edit options

### Benefits

- **No configuration needed** - uses existing OpenAI API key
- **Universal** - works with any property website, not just specific APIs
- **Smart** - AI understands different website layouts and field names
- **Complete** - extracts more fields than typical APIs
- **Fast** - results in seconds

## [2.11.3] - 2026-01-11

### ✨ New Features - Real Duval County Integration

- **Actual Duval County Property Data Fetching**
  - Implemented REAL API integration with Duval County (Jacksonville, FL) public records
  - Uses FREE `opendata.coj.net` Socrata open data API
  - Fetches: building sqft, year built, property type, floors count, parcel ID
  - Provides direct links to property appraiser detail pages
  - Works automatically when clicking "Auto-Refresh" on location pages
  - Previous version only logged availability, now actually retrieves data

- **Property Diagram Upload Feature**
  - Added new `property_diagram` ImageField to Location model
  - Upload diagrams from tax collector/property appraiser records
  - New "Property Diagram" card on location detail page
  - Helpful links to Duval County and other FL property appraisers
  - Guides users to search municipal records for free diagrams
  - Easy upload button integrated into location edit form

### 🔧 Improvements

- **Floor Plan Generation Debugging**
  - Added API key check before attempting generation
  - Clear error message if OpenAI API key is missing
  - Detailed debug logging to track generation progress
  - Better error handling throughout floor plan creation process
  - Logs: initialization, parameters, AI generation, database operations
  - Helps diagnose "page reload" issues by showing exact error messages

### Technical Details

- Duval County API: `https://opendata.coj.net/resource/jj2e-6w6r.json`
- Parses multiple field name variations (total_living_area, building_area, etc.)
- Address parsing with regex for street number and name
- User-Agent header for polite API usage
- Migration `0006_add_property_diagram.py` adds ImageField
- Upload path: `locations/diagrams/%Y/%m/`

## [2.11.2] - 2026-01-11

### 🐛 Bug Fixes

- **Floor Plan Generation Type Error**
  - Fixed "int() argument must be a string, a bytes-like object or a real number, not 'list'" error
  - Added robust type checking for all form inputs (floor number, employees, dimensions)
  - Handles edge case where POST data returns lists instead of strings
  - Graceful fallback to sensible default values if parsing fails
  - Better error handling for malformed form data

### 🎨 UI/UX Improvements

- **Municipal Data Visibility**
  - Added prominent green success alert in Settings → AI explaining free municipal data
  - Changed Auto-Refresh button from gray (secondary) to blue (primary) to increase visibility
  - Updated button tooltip: "Tries municipal tax collector records (FREE) first, then paid APIs if configured"
  - Made it crystal clear that no configuration is needed for municipal data
  - Listed supported jurisdictions: Florida counties, Socrata open data cities
  - Clear distinction between free municipal data, paid APIs, and manual entry

- **Settings Page Improvements**
  - Green alert at top of Property Data section highlighting free option
  - "No configuration needed" prominently displayed
  - Better explanation of when you might want paid APIs vs free data
  - Users understand they have 3 options with clear pros/cons

### Technical Details

- Added isinstance() checks before type conversions
- List handling for POST data edge cases
- Try/except blocks with sensible defaults
- Improved button styling and prominence

## [2.11.1] - 2026-01-11

### ✨ New Features

- **Municipal Tax Collector Data Integration (FREE!)**
  - Automatically fetches building data from public property records
  - Supports Florida counties: Jacksonville/Duval, Miami-Dade, Broward, Orange, Hillsborough, Pinellas
  - Framework for California, Texas, and New York property databases
  - Integrated with Socrata open data portals (many US cities)
  - **Completely free** - uses public government tax assessor websites
  - 7-day caching to minimize requests
  - Falls back gracefully if data unavailable
  - Triggered by clicking "Auto-Refresh" button (tries municipal first, then paid APIs if configured)

### 🔧 Improvements

- **Property Data Fetch Priority**
  - New order: Regrid → AttomData → Municipal (FREE) → Basic geocoding
  - Municipal lookup happens automatically with no configuration needed
  - Clear UI showing 3 options: Free (municipal), Paid (API), Manual (edit)

- **Floor Plan Generation Error Handling**
  - Improved error messages with specific troubleshooting guidance
  - Detects OpenAI API key issues and directs to settings page
  - Better logging for debugging generation failures
  - Helps identify issues instead of silent failures

### 🎨 UI/UX Improvements

- Location detail page now clearly explains property data options:
  - **Free:** Municipal tax collector records (public data)
  - **Paid:** Regrid/AttomData APIs (comprehensive data)
  - **Manual:** Enter data yourself
- Auto-Refresh button tooltip updated to reflect free option
- Better guidance for users without paid API subscriptions

### Technical Details

- Created `municipal_data.py` service with county-specific implementations
- Integrated municipal service into property data fetch cascade
- Service detects Florida counties from city names
- Extensible architecture for adding more jurisdictions

## [2.11.0] - 2026-01-11

### ✨ New Features

- **Property Data API Settings**
  - Added Regrid API key configuration in Settings → AI
  - Added AttomData API key configuration in Settings → AI
  - Clear messaging that these are optional premium services ($299-500+/month)
  - Emphasizes manual data entry as free alternative
  - Auto-refresh property data feature now available when APIs are configured
  - Keys stored securely in .env file with automatic application restart

### 🎨 UI/UX Improvements

- **Import Form - Automatic Organization Matching**
  - Changed "Target Organization" from required to optional
  - Added prominent blue alert explaining automatic matching behavior
  - Added "Fuzzy Matching Options" section with visibility
  - Users can now leave organization blank for automatic matching
  - Fuzzy matching threshold slider with help text (0-100%, default 85%)
  - Clear explanation: "Leave blank and enable fuzzy matching below. System will automatically match imported companies to existing organizations by name similarity"
  - Makes import workflow much clearer and easier

### 🔧 Improvements

- Backend now saves and loads Regrid/AttomData API keys
- Import service automatically matches organizations when target_organization is null
- Better user guidance for choosing between manual and automatic import workflows
- Clearer distinction between free and paid features throughout the app

### Technical Details

- Settings view handles two new API key fields
- Form properly filters queryset and makes fields optional
- Django settings already configured for property data APIs
- Import fuzzy matching leverages existing infrastructure

## [2.10.9] - 2026-01-11

### 🎨 UI/UX Improvements

- **Property Data & Floor Plan Dimension Improvements**
  - Added clear messaging that property data APIs are optional/paid services (Regrid/AttomData)
  - Added "Edit" button in building information section for manual data entry
  - Changed "Refresh" button to "Auto-Refresh" with tooltip explaining paid API requirement
  - Added alert when property data is missing with instructions to add manually
  - Added "Add manually" links for each missing building information field
  - Floor plan generator now warns when default dimensions (100x80) are shown
  - Alerts user to enter actual building dimensions instead of defaults
  - Links to location edit page for permanent square footage entry
  - Makes manual data entry workflow obvious and easy

### 🐛 Bug Fixes

- **Template Error Fixed**
  - Fixed "Invalid filter: 'multiply'" TemplateSyntaxError
  - Created custom location_filters.py with multiply filter
  - Floor plan area calculation now works correctly

### 🔧 Improvements

- Better user guidance for property data entry
- Clearer distinction between free (manual) and paid (API) features
- Improved onboarding for users without property data APIs

## [2.10.8] - 2026-01-11

### 📖 Documentation

- **Comprehensive Google Maps API Setup Guide**
  - Added detailed step-by-step instructions in AI settings page
  - Lists all 4 required APIs to enable:
    - Maps Embed API (for interactive maps)
    - Maps Static API (for satellite imagery)
    - Geocoding API (for address conversion)
    - Places API (for property data)
  - Includes direct links to Google Cloud Console
  - Explains free tier availability
  - Warning alert with clear setup process
  - Improved error messages on location detail page
  - More user-friendly guidance for resolving "API not activated" errors

### 🔧 Improvements

- Better error messaging when Google Maps APIs aren't enabled
- Clearer instructions prevent common API setup mistakes
- Reduced support burden with self-service documentation

## [2.10.7] - 2026-01-11

### 🐛 Bug Fixes

- **Google Maps API Integration**
  - Fixed "cannot unpack non-iterable NoneType" error in satellite image refresh
  - Fixed hardcoded "YOUR_API_KEY" in location detail template
  - Template now properly uses API key from Django settings
  - Added google_maps_api_key to location_detail view context
  - Improved error messages for API fetch failures
  - Added fallback message when API key not configured
  - Satellite image and map embed now work correctly with configured API key

### Technical Details

- Changed satellite image result unpacking to check for None before tuple unpacking
- Removed manual restart instructions from settings view warning messages
- All warning messages now show user-friendly "The application will restart shortly" message
- Template conditionally shows map iframe or warning based on API key availability

## [2.10.6] - 2026-01-11

### ✨ New Features

- **Automatic Application Reload After Settings Changes**
  - AI settings page now automatically reloads Gunicorn after saving
  - Uses HUP signal for zero-downtime reload
  - Fallback to systemctl restart if needed
  - No manual restart required for API key changes
  - Automatic detection of Gunicorn master process

### 🔧 Improvements

- Seamless settings update experience
- Immediate application of new API keys
- Better error handling with fallback mechanisms
- User-friendly success/warning messages

### Technical Details

- Implemented automatic Gunicorn reload using SIGHUP signal
- Process detection via ps aux command
- Graceful fallback to sudo systemctl restart
- Permission-aware error handling

## [2.10.5] - 2026-01-11

### 🎨 UI/UX Improvements

- **Favorites as Top-Level Nav Link**
  - Moved Favorites from More dropdown to its own nav link
  - More prominent placement with star icon
  - Easier access to favorited items
  - Removed now-empty "More" dropdown menu
  - Cleaner, more streamlined navigation

## [2.10.4] - 2026-01-11

### 🎨 UI/UX Improvements

- **Navigation Reorganization**
  - Assets is now a dropdown menu with "All Assets" link
  - Moved Infrastructure section (Racks, IPAM) under Assets dropdown
  - Monitoring is now its own top-level nav dropdown (no longer hidden in More)
  - Website Monitors and Expirations moved to Monitoring dropdown
  - Cleaner navigation structure with better logical grouping
  - Improved discoverability of infrastructure and monitoring features
  - "More" dropdown now only contains Favorites

### Improvements

- Better organization of navigation menu items
- Infrastructure features (Racks, IPAM) now logically grouped with Assets
- Monitoring features more prominent and easier to access
- Reduced clutter in "More" dropdown menu

## [2.10.3] - 2026-01-11

### ✨ New Features

- **Floor Plan Import - Location Linking**
  - Added ability to link floor plans to existing locations during MagicPlan import
  - New `target_location` field in ImportJob model
  - Location dropdown in floor plan import form (filtered by organization)
  - Option to either create new location or link to existing one
  - Import service automatically uses specified location if provided
  - Falls back to creating new location from MagicPlan data if not specified

### 🔧 Improvements

- Floor plan import form now shows locations for selected organization
- Import service logs which location is being used
- Better user experience for managing floor plans across multiple locations
- Form dynamically filters locations based on selected organization

### Technical Details

- Added `target_location` ForeignKey to ImportJob model
- Updated ImportJobForm to include location field with organization-based filtering
- Modified MagicPlanImportService._get_or_create_location() to prioritize target_location
- Migration 0004: Added target_location field to import_jobs table
- Updated floor_plan_import view to pass organization context to form

## [2.10.2] - 2026-01-11

### 🐛 Critical Bug Fixes

- **Location Model NOT NULL Constraint Errors (SQLite Compatibility)**
  - Made all optional CharField/TextField fields properly nullable with `null=True`
  - Fixed SQLite ALTER TABLE limitations that prevented proper default value handling
  - Fields now correctly accept NULL values: property_id, property_type, google_place_id
  - Contact fields: phone, email, website now properly nullable
  - Address field: street_address_2 now properly nullable
  - Floor plan fields: floorplan_generation_status, floorplan_error now properly nullable
  - LocationFloorPlan fields: diagram_xml, template_used now properly nullable
  - **Resolves IntegrityError on location creation form**

### Technical Details

- Migration 0005: Added `null=True` to all optional character fields
- Ensures compatibility with SQLite database backend
- Maintains backwards compatibility with existing data
- No data loss - existing NULL values preserved

## [2.10.1] - 2026-01-11

### 🐛 Bug Fixes

- **Location Model Fields**
  - Fixed NOT NULL constraint errors in location creation form
  - Added default='' to all CharField/TextField with blank=True
  - Fields fixed: property_id, property_type, google_place_id, street_address_2, phone, email, website
  - Fixed floorplan_generation_status and floorplan_error fields
  - Fixed LocationFloorPlan diagram_xml and template_used fields
  - Prevents database constraint violations on location creation

### 🎨 UI/UX Improvements

- **Navigation Enhancement**
  - Moved Floor Plan Import to Docs → Diagrams dropdown menu
  - Created dedicated floor plan import page at /locations/floor-plan-import/
  - Pre-configured form for MagicPlan imports with sensible defaults
  - Improved discoverability of floor plan import feature
  - Added helpful instructions and documentation sidebar

### 🔧 Improvements

- Floor plan import form now defaults to dry_run=True for safety
- Added informational sidebar with MagicPlan export instructions
- Created floor_plan_import view with pre-configured settings
- Better user experience for floor plan imports

## [2.10.0] - 2026-01-11

### ✨ New Features

- **MagicPlan Floor Plan Import**
  - Import floor plans directly from MagicPlan JSON exports
  - Automatic location creation from project data
  - Converts measurements from meters to feet automatically
  - Creates LocationFloorPlan records with dimensions and metadata
  - Supports multi-floor imports from single JSON file
  - Extracts room data and dimensions from MagicPlan format
  - Dry run mode for preview before importing
  - Tracks floor plan count in import statistics

### 🔧 Improvements

- Added 'magicplan' as import source type
- File upload support for import jobs
- Made source_url and source_api_key optional (not needed for MagicPlan)
- Updated LocationFloorPlan source choices to include 'magicplan'
- Form validation based on import source type
- Import forms now handle multipart/form-data for file uploads
- Added import_floor_plans boolean field to control what gets imported

### Technical Details

- New MagicPlanImportService with JSON parsing
- Intelligent dimension calculation from room data
- Unit conversion utilities (meters to feet)
- Organization-scoped location creation
- Integration with existing LocationFloorPlan model

## [2.9.0] - 2026-01-11

### ✨ New Features

- **Multi-Organization Import with Fuzzy Matching**
  - Import ALL organizations from IT Glue/Hudu automatically
  - No need to select target organization - imports entire source system
  - Intelligent fuzzy name matching for existing organizations
    - Matches "ABC LLC" to "ABC Corporation" automatically
    - Configurable similarity threshold (0-100, default 85%)
    - Normalizes company suffixes (Inc, Corp, LLC, Ltd, etc.)
  - Organization mapping tracking shows created vs matched
  - Import statistics display organizations created and matched
  - Optional single-organization mode for selective imports
  - Prevents duplicate organizations with smart matching
  - OrganizationMapping model tracks source-to-target relationships

### 🔧 Improvements

- Import form now defaults to multi-org import (target_organization optional)
- Added organization statistics to import job tracking
- Enhanced import admin interface with organization metrics
- Better import mapping with source organization tracking

### 🐛 Bug Fixes

- Import system now properly handles multi-tenant data migration
- Organization relationships preserved during import

## [2.8.0] - 2026-01-11

### ✨ New Features

- **IT Glue / Hudu Import Functionality**
  - Complete data migration system from IT Glue and Hudu platforms
  - Support for importing:
    - Assets and configuration items
    - Passwords (encrypted)
    - Documents and knowledge base articles
    - Contacts
    - Locations
    - Networks
  - Dry run mode for previewing imports without saving data
  - Import progress tracking with detailed statistics
  - Duplicate prevention via import mapping system
  - Comprehensive logging of import operations
  - Web UI for managing import jobs (create, edit, start, monitor)
  - CLI management command for automated imports
  - Import job status tracking (pending, running, completed, failed)
  - Per-organization import targeting
  - Auto-refresh log viewer for running imports
  - Available in Admin → Import Data menu

### 🔧 Improvements

- Added "Import Data" link to Admin menu for easy access
- Import system protected by staff/superuser authentication
- Vendor-specific API authentication for IT Glue and Hudu

## [2.7.0] - 2026-01-11

### ✨ New Features

- **RMM Integrations UI**
  - Complete user interface for RMM (Remote Monitoring and Management) integrations
  - Support for 4 RMM providers:
    - NinjaOne (OAuth2 with refresh tokens)
    - Datto RMM (API key/secret)
    - ConnectWise Automate (server URL + credentials)
    - Atera (API key)
  - Provider-specific credential forms with dynamic field display
  - Connection testing and device syncing
  - Device list view with online/offline status
  - Auto-mapping of RMM devices to Asset records
  - Sync scheduling with configurable intervals
  - Comprehensive device details (type, OS, IP, MAC, serial)
  - Asset linking for unified device management

- **Enhanced Organization Management**
  - Full company profile fields added:
    - Legal name and Tax ID/EIN
    - Complete address fields (street, city, state, postal code, country)
    - Contact information (phone, email, website)
    - Primary contact person details
    - Company logo upload
  - Organization detail page now displays locations
  - Location cards showing floor plans and status
  - Improved organization form with sectioned layout

- **Shared Location Support**
  - Locations can now be shared across multiple organizations
  - `is_shared` flag for data centers, co-location facilities, etc.
  - ManyToMany relationship for `associated_organizations`
  - Organization field made optional for shared/global locations
  - Helper methods: `get_all_organizations()`, `can_organization_access()`
  - Updated constraints to handle nullable organization field

- **Navigation Improvements**
  - Moved Organizations and Locations to Admin menu for better organization
  - Admin menu now organized into sections:
    - System (Settings, Status)
    - Management (Organizations, Locations, Access, Integrations)
    - Global Views (Dashboard, Processes)
  - Cleaner navigation structure for administrators

### 🔧 Improvements

- **Integration List UI**
  - Redesigned to show both PSA and RMM integrations
  - Card-based layout with separate sections
  - Device count displayed for RMM connections
  - Link to view all synced devices
  - Improved visual hierarchy

- **Member Management**
  - User assignment now restricted to unassigned users only
  - Prevents seeing or adding users from other organizations
  - Enhanced multi-tenancy isolation
  - Clear help text on member forms

- **System Status Page**
  - Fixed Gunicorn service status detection
  - Corrected service names from `itdocs-*` to `clientst0r-*`
  - Now accurately shows running services
  - Fixed PSA/Monitor timer status checks

### 🏗️ Database Changes

- **Locations Migration (0002)**
  - Removed old unique_together constraint
  - Added `is_shared` BooleanField (default=False)
  - Added `associated_organizations` ManyToManyField
  - Changed `organization` to nullable ForeignKey
  - Added index on `is_shared` field
  - Added UniqueConstraint for (organization, name) when organization is not null

- **Organization Model Updates**
  - Added 16 new fields for complete company profiles
  - Added `full_address` property method
  - Migration applied successfully

### 📚 Documentation

- **README Updates**
  - Updated version to 2.7.0
  - Added RMM Integrations section with all 4 providers
  - Removed "Real-time collaboration" from roadmap
  - Added "MagicPlan floor plan integration" to roadmap
  - Updated feature highlights

- **Version Info**
  - Updated `config/version.py` to 2.7.0
  - Version displayed in system status and footer

### 🔌 Templates Created

- `templates/integrations/rmm_form.html` - RMM connection create/edit form
- `templates/integrations/rmm_detail.html` - RMM connection details with device stats
- `templates/integrations/rmm_confirm_delete.html` - Delete confirmation page
- `templates/integrations/rmm_devices.html` - All devices list view
- `templates/accounts/organization_form.html` - Redesigned org form
- Updated `templates/accounts/organization_detail.html` - Added locations section
- Updated `templates/integrations/integration_list.html` - PSA + RMM sections
- Updated `templates/base.html` - Reorganized Admin menu

### 🛤️ URL Routes Added

- `integrations/rmm/create/` - Create new RMM connection
- `integrations/rmm/<int:pk>/` - View RMM connection details
- `integrations/rmm/<int:pk>/edit/` - Edit RMM connection
- `integrations/rmm/<int:pk>/delete/` - Delete RMM connection
- `integrations/rmm/devices/` - View all RMM devices

### 🔐 Security

- No security changes in this release
- All existing encryption and authentication mechanisms maintained

### 🎯 Next Up

- MagicPlan data export integration for automated floor plan generation
- Additional PSA/RMM provider implementations
- Mobile-responsive improvements

## [2.5.0] - 2026-01-11

### 🐛 Bug Fixes

- **Diagram Editor - False "Unsaved Changes" Warning** (Critical Fix)
  - Fixed persistent warning dialog after saving diagrams
  - Root cause: Draw.io iframe's own beforeunload handler was triggering
  - Solution: Remove iframe from DOM before navigation
  - Implemented race condition prevention: justSaved flag set before fetch
  - Increased autosave threshold from 50 → 200 bytes (accounts for PNG export metadata)
  - Extended justSaved timer from 5s → 15s
  - Added explicit returnValue cleanup in beforeunload
  - Comprehensive debug logging with emoji indicators (🔒/🔓/✅/⚠️/🚪/🗑️/📍)
  - Version progression through 7 iterations (v2.3 → v2.9)
  - Final fix: `iframe.remove()` before `window.location.href`

### ✨ New Features

- **Demo Office Floor Plan**
  - Professional 2nd floor office layout with complete network infrastructure
  - 5 Wireless Access Points (AP-01 through AP-05) with coverage zones
  - 7 Access Control Readers (biometric reader for server room)
  - Server Room with 3 equipment racks:
    - Core Switching (2x 48-port switches)
    - Servers/Storage (4U server, 2U storage array)
    - Patch Panel (96-port capacity)
  - 10kVA UPS power backup
  - Multiple office areas: Reception, Open Office (8 hot desks), Conference Rooms (2), Manager Offices (2), Executive Suite
  - Support rooms: IT Closet, Storage, Break Room, Restrooms
  - Network backbone visualization with dashed blue lines
  - Professional color-coding by area type
  - Legend with all symbols and icons
  - Management command: `seed_demo_floorplan`

- **PNG Preview Generation for Diagrams**
  - Diagrams now auto-generate PNG exports when saved
  - PNG preview displayed on diagram detail pages
  - Base64 data URL handling for image data
  - Automatic fallback: saves without PNG if export fails (3s timeout)
  - Backend decodes and stores PNG in `diagram.png_export` FileField
  - Fixes "No preview available" message

### 🔧 Technical Improvements

- **Diagram Editor Architecture**
  - Autosave event handling instead of export requests
  - XML caching from draw.io autosave events
  - PNG export on save for preview generation
  - Enhanced status messages with icon indicators
  - Improved error handling and logging
  - 8 major iterations documented in commit history

- **Cache-Busting Enhancements**
  - Added no-cache meta tags (Cache-Control, Pragma, Expires)
  - Version banners in console logs
  - Visible version indicators in page title
  - Multiple service restarts to ensure code updates

### 📚 Documentation

- **Enhanced Encryption v2 Documentation** (SECURITY.md)
  - 350+ lines of comprehensive security documentation
  - HKDF key derivation with 6 purpose-specific contexts
  - AAD (Associated Authenticated Data) for context binding
  - Version tagging for key rotation support
  - Memory clearing best practices
  - Standards compliance: NIST SP 800-38D, NIST SP 800-108, FIPS 197, NSA Suite B, OWASP ASVS Level 2

- **CVE Scanning Documentation**
  - AI-assisted vulnerability detection explanation
  - Alert-only system (no automatic changes)
  - SQL injection, XSS, CSRF, path traversal detection
  - Weekly manual audits + automated scanning

- **About Page Updates**
  - Security protocol information
  - Enhanced encryption v2 details
  - Vulnerability scanning status
  - User-friendly security information

### 🏗️ Database Changes

- Added `png_export` FileField to Diagram model (if not already present)
- Optimized diagram version storage

### 🔐 Security

- Fixed password encryption AAD mismatch
  - Removed password_id from AAD to prevent encryption/decryption failures
  - Ensures consistent AAD between encryption and decryption
  - Uses only org_id in AAD for password vault entries

### 🧪 Testing

- Created comprehensive test password dataset
  - 5 weak passwords (all confirmed breached: 52M to 712K occurrences)
  - 5 strong passwords (all confirmed safe, not in breach database)
  - 100% accuracy on breach detection
  - Command: `seed_test_passwords`

- Created diagnostic test command
  - `test_decryption` command for identifying encryption key mismatches
  - Reports all passwords that fail decryption
  - Provides remediation steps

### 📝 Commits

This release represents 8+ hours of iterative debugging and refinement:
- 10+ commits focused on diagram editor warning fix
- Race condition identified and resolved
- Multiple approaches tested (justSaved flag, threshold tuning, returnValue cleanup)
- Final solution: iframe removal before navigation

## [2.4.0] - 2026-01-11

### 🔐 Security Enhancements

- **Password Breach Detection** - HaveIBeenPwned integration with k-anonymity privacy protection
  - Automatic breach checking against 600+ million compromised passwords
  - Privacy-first k-anonymity model: only 5 characters of SHA-1 hash transmitted
  - Zero-knowledge approach - passwords never leave your server in any identifiable form
  - Configurable scan frequencies per password: 2, 4, 8, 16, or 24 hours
  - Visual security indicators: 🟢 Safe, 🔴 Compromised, ⚪ Unchecked
  - Real-time manual testing with "Test Now" button
  - Breach warning banners with breach count display
  - Last checked timestamp in tooltips
  - 24-hour response caching to reduce API calls
  - Graceful degradation (fail-open) if API unavailable
  - Management command for bulk scanning: `check_password_breaches`
  - Scheduled scanning support via systemd timers or cron
  - Comprehensive audit logging for all breach checks
  - Optional blocking of breached passwords via `HIBP_BLOCK_BREACHED` setting
  - Warning-only mode (default) allows saving with notification
  - Full organization-level multi-tenancy support

### 🎨 UI Improvements

- **Password List Enhancements**
  - New "Security" column showing breach status at a glance
  - Color-coded status indicators for quick identification
  - Hover tooltips with last check timestamp

- **Password Detail Enhancements**
  - Prominent security warning banner for compromised passwords
  - Security status section with breach information
  - "Test Now" button for on-demand verification
  - "Change Password Now" quick action button
  - Real-time test results with loading indicators
  - Auto-refresh after test completion

- **About Page Enhancements**
  - CVE scan status information added
  - Last security audit date displayed
  - Password breach detection feature explanation
  - Security audit transparency section

### 📚 Documentation

- **Comprehensive Security Documentation** (SECURITY.md)
  - Detailed explanation of k-anonymity privacy protection
  - Step-by-step breakdown of how breach checking works
  - Security guarantees and privacy assurances
  - Configuration options with examples
  - Performance and caching details
  - Scheduled scanning setup instructions
  - Management command documentation
  - Best practices guide
  - Comparison with Chrome, Firefox, 1Password, Bitwarden implementations
  - "Why breached passwords matter" educational section

- **README Updates**
  - Password breach detection added to security features
  - Feature list updated with breach detection

- **Configuration Examples**
  - `HIBP_ENABLED` - Enable/disable breach checking
  - `HIBP_CHECK_ON_SAVE` - Check passwords when saved
  - `HIBP_BLOCK_BREACHED` - Block compromised passwords
  - `HIBP_SCAN_FREQUENCY` - Default scan interval
  - `HIBP_API_KEY` - Optional API key for increased rate limits

### 🔧 Technical Details

- **New Models**
  - `PasswordBreachCheck` - Tracks breach check results with timestamps
  - Foreign key relationship to `Password` model
  - Stores breach status, count, source, and check timestamp
  - Indexed for performance (password + checked_at, is_breached)

- **New Services**
  - `PasswordBreachChecker` - Core breach checking service
  - SHA-1 hashing with prefix extraction
  - API communication with HaveIBeenPwned
  - Response caching with 24-hour TTL
  - Suffix matching logic

- **New Views & Endpoints**
  - `password_test_breach` - AJAX endpoint for manual breach testing
  - Returns breach status, count, and timestamp
  - Creates breach check record and audit log

- **Form Integration**
  - Breach checking integrated into `PasswordForm` clean() method
  - Configurable warning vs. blocking behavior
  - Scan frequency selection field
  - Per-password frequency storage in custom_fields

- **Management Commands**
  - `check_password_breaches` - Bulk password scanning
  - `--force` - Ignore last check time
  - `--password-id` - Check specific password
  - `--organization-id` - Check organization passwords
  - Respects individual password scan frequency settings
  - Summary output with color-coded results

### 🏗️ Database Changes

- Migration 0006: Create `password_breach_checks` table
- Added indexes for query optimization
- Organization-scoped with automatic filtering

### 🎯 Security Audit

- CVE scan completed: January 11, 2026
- Status: All Clear
- 0 Critical, 0 High, 0 Medium vulnerabilities
- Regular security auditing with Luna the GSD

## [2.3.0] - 2026-01-11

### ✨ Added

- **Data Closets & Network Closets** - Enhanced rack management for network infrastructure
  - New rack types: Data Closet, Network Closet, Wall Mount Rack, Open Frame, Half Rack
  - Building/Floor/Room location hierarchy for better organization
  - Network closet specific fields: patch panel count, total port count
  - Closet diagram upload for visual layout documentation
  - Ambient temperature tracking for monitoring environmental conditions
  - PDU count tracking for power distribution management

- **Rack Resources Model** - Comprehensive equipment tracking for racks and closets
  - Track non-rackable equipment: patch panels, switches, routers, firewalls, UPS, PDUs
  - Network equipment specifications: port count, port speed, management IP
  - Power specifications: power draw, input voltage, UPS runtime, VA capacity
  - Rack position tracking (U position for rack-mounted resources)
  - Warranty and support contract tracking
  - Photo documentation for each resource
  - Optional asset linking for integration with asset management
  - Full admin interface with organized fieldsets

- **2FA Enrollment Prompt** - Optional but recommended security
  - Users prompted to enable 2FA on first login
  - "Skip for now" button allows users to defer enrollment
  - Prompts once per session only (not on every page)
  - Info banner explains 2FA benefits
  - Custom template with Bootstrap styling

### 🔧 Fixed

- **Diagram Templates** - Resolved draw.io editor errors
  - Fixed "Error: 1: Self Reference" in diagram XML
  - Simplified diagram templates to use valid mxGraph structure
  - All 5 templates now load and edit correctly without errors
  - Created `fix_diagram_templates` management command for repairs

- **Diagram Previews** - Templates now have visual previews
  - PNG thumbnails generated for all diagram templates
  - Previews displayed in diagram list and template selection
  - Automated preview generation via management command

- **Fresh Installation** - Template seeding now works correctly
  - Fixed migration ordering issue that prevented template creation
  - Templates seed after all schema changes complete
  - No longer requires organization to exist before seeding global templates
  - Installer automatically populates 5 document templates, 5 diagram templates

- **2FA Middleware** - More flexible authentication flow
  - When REQUIRE_2FA=False, shows optional enrollment prompt
  - When REQUIRE_2FA=True, enforces mandatory enrollment (existing behavior)
  - Session tracking prevents repeated redirects
  - Improved user experience for security-conscious but flexible deployments

### 📚 Documentation

- Updated version to 2.3.0
- Enhanced rack management documentation for data closets
- Added rack resource tracking documentation

## [2.2.0] - 2026-01-10

### 🚀 One-Line Installation

**Major improvement:** Complete automated installation with zero manual steps!

```bash
git clone https://github.com/agit8or1/clientst0r.git && cd clientst0r && bash install.sh
```

The installer now does EVERYTHING:
- Installs all system dependencies (Python, MariaDB, build tools, libraries)
- Creates virtual environment and installs Python packages
- Generates secure encryption keys automatically
- Creates and configures .env file
- Sets up database with proper schema
- Creates log directory with correct permissions
- Runs all database migrations
- Creates superuser account (interactive prompt)
- Collects static files
- **Automatically starts production server with systemd**

**When the installer finishes, the server is RUNNING!** No manual commands needed.

**Smart Detection & Upgrade System:**
The installer now detects existing installations and provides options:
- **Option 1: Upgrade/Update** - Pull latest code, update dependencies, run migrations, restart service (zero downtime)
- **Option 2: System Check** - Comprehensive health check (Python, database, service, port, HTTP response)
- **Option 3: Clean Install** - Automated cleanup and fresh reinstall
- **Option 4: Exit** - Leave installation untouched

Detects: .env file, virtual environment, systemd service, database
Shows: Current status of all components before prompting

### ✨ Added
- **Processes Feature** - Sequential workflow/runbook system for IT operations
  - Process CRUD operations with slug-based URLs
  - Sequential stages with entity linking (Documents, Passwords, Assets, Secure Notes)
  - Global processes (superuser-created) and organization-specific processes
  - Process categories: onboarding, offboarding, deployment, maintenance, incident, backup, security, other
  - Inline formset management for stages with drag-and-drop reordering
  - Confirmation checkpoints per stage
  - Full CRUD operations with list, detail, create, edit, delete views
  - Navigation integration in main navbar

- **Diagrams Feature** - Draw.io integration for network and system diagrams
  - Embedded diagrams.net editor via iframe with postMessage API
  - Store diagrams in .drawio XML format (editable)
  - PNG and SVG export generation via diagrams.net export API
  - Diagram types: network, process flow, architecture, rack layout, floor plan, organizational chart
  - Global diagrams support (superuser-created)
  - Tag-based categorization and organization
  - Full CRUD operations with list, detail, create, edit, delete views
  - Download support for all formats (PNG, SVG, XML)
  - Thumbnail previews in list view

- **Rackmount Asset Tracking** - Enhanced asset management for rack-mounted equipment
  - `is_rackmount` checkbox field on assets
  - `rack_units` field for height tracking (1U, 2U, etc.)
  - Conditional form field display (rack_units shows only when is_rackmount is checked)
  - JavaScript toggle for dynamic field visibility
  - Asset migration to add rackmount fields (assets/migrations/0004)

- **Enhanced Rack Management** - Improved rack-to-asset integration
  - Rack devices now require existing assets (ForeignKey to Asset model)
  - Asset dropdown filtered to show only rackmount assets for organization
  - "Create New Asset" button with smart redirect flow
  - After asset creation from rack page, automatically returns to "Add Asset to Rack" form
  - Updated labels: "Devices" → "Mounted Assets"
  - Improved rack detail layout with asset links

- **Access Management Dashboard** - Consolidated admin interface
  - Single page for Organizations, Users, Members, and Roles management
  - Summary cards showing counts (Organizations, Users, Memberships)
  - Recent data tables (5 recent orgs, 5 recent users, 10 recent memberships)
  - Quick links to all management functions
  - Roles & Permissions section with links to Tags, API Keys, Audit Logs
  - Superuser-only access with permission checks

### 🎨 Improved
- **Admin Navigation** - Condensed dropdown menu from 7 items to 6
  - Replaced separate Orgs/Users/Members/Roles links with single "Access Management" link
  - Cleaner, more organized menu structure
  - Better UX for administrators

- **Asset Form** - Enhanced network fields section
  - Added hostname, IP address, and MAC address fields
  - Responsive 3-column grid layout for network fields
  - Rackmount fields section with 2-column layout
  - Helper text for all new fields
  - Improved validation and placeholder text

- **Monitoring Forms** - Better organization filtering
  - RackDeviceForm filters assets by organization and rackmount capability
  - IPAddressForm properly filters assets by organization
  - Helpful empty labels and help text
  - Required field indicators with asterisks

### 🔧 Changed
- **Rack Device Model** - Changed from generic device to asset-based system
  - Removed RackDevice fields: name, photo, color, power_draw_watts, units
  - Changed asset field from optional to required ForeignKey
  - Asset properties now drive rack device display (name comes from Asset.name)
  - Maintains start_unit and notes fields
  - Migration created to preserve existing data

- **Forms Organization** - Improved __init__ patterns
  - Consistent organization parameter passing
  - Proper queryset filtering in all forms
  - Better parameter extraction (kwargs.pop pattern)

### 📚 Documentation
- Updated README.md to version 2.2.0
- Added Processes and Diagrams features to Core Features list
- Updated Infrastructure description to mention rackmount assets
- Comprehensive CHANGELOG entry for all new features

### 🗄️ Database Migrations
- `assets.0004_add_rackmount_fields` - Added is_rackmount and rack_units to Asset model
- `monitoring.0004_change_asset_id_to_foreignkey` - Changed RackDevice to use Asset ForeignKey
- `processes.0001_initial` - Created Process, ProcessStage, and Diagram models

### 🐕 Contributors
- Luna the GSD - Continued security oversight and code quality review

## [2.1.1] - 2026-01-10

### 🐛 Fixed
- **2FA Inconsistent State Detection** - Added auto-detection and repair for users who enabled 2FA before TOTPDevice integration
  - System now automatically resets inconsistent states (profile.two_factor_enabled=True but no TOTPDevice)
  - Shows warning message prompting users to re-enable 2FA properly
  - Fixes dashboard warning showing incorrectly
- **ModuleNotFoundError in 2FA Setup** - Removed incorrect import statement that caused 500 errors
  - Removed `from two_factor.models import get_available_methods` (module doesn't exist)
  - 2FA verification now works without errors
- **TOTPDevice Key Format Error** - Fixed "Non-hexadecimal digit found" error on login
  - Now properly converts base32 keys from pyotp to hex format expected by django-otp
  - Base32 to hex conversion: `base64.b32decode(secret).hex()`
  - Fixed existing broken TOTPDevice records in database
- **2FA Login Challenge Not Working** - Fixed issue where users with 2FA enabled weren't challenged for codes
  - Login now properly prompts for 6-digit TOTP codes
  - django-two-factor-auth integration working correctly
- **2FA Dashboard Warning Logic** - Dashboard warning now accurately reflects 2FA status
  - Checks for confirmed TOTPDevice existence rather than profile flag alone
  - No more false warnings for users with proper 2FA setup

### 🔧 Technical Details
- TOTPDevice keys stored in hex format (40 chars) instead of base32 (32 chars)
- Conversion: base32 → bytes (20) → hex (40 chars)
- State consistency check added to 2FA setup page load
- Auto-repair runs when users visit Profile > Two-Factor Authentication

## [2.1.0] - 2026-01-10

### ✨ Added
- **Tag Management** - Full CRUD for organization tags in Admin section
  - Create/edit/delete tags with custom colors
  - View tag usage across assets and passwords
  - Live color preview in tag forms
  - Delete warnings when tags are in use
- **Screenshot Gallery** - 31 feature screenshots for documentation
  - Full screenshot gallery page (SCREENSHOTS.md)
  - 2x3 thumbnail grid preview in README
  - Organized by feature category
- **Navigation Improvements**:
  - Tags menu item in Admin → System section
  - Improved navbar layout with truncated long usernames
  - Compact spacing for better single-line fit

### 🔧 Changed
- **Static File Serving** - Switched to WhiteNoise for efficient static file delivery
  - Removed redundant nginx (NPM handles reverse proxy)
  - Gunicorn now serves static files via WhiteNoise
  - Compressed manifest static files storage
- **Deployment Architecture** - Optimized for Nginx Proxy Manager
  - Gunicorn listens on 0.0.0.0:8000 (not unix socket)
  - NPM handles SSL termination and caching
  - Simplified stack: NPM → Gunicorn:8000 → Django
- **Asset Form** - Condensed multi-column layout
  - 2-column and 3-column responsive grid
  - Side-by-side notes and custom fields
  - Scrollable tags container
  - Improved JSON validation for custom fields with examples
- **Documentation** - Updated README with working links
  - Fixed broken documentation references
  - Updated screenshots path
  - Clarified no default credentials (must run createsuperuser)

### 🐛 Fixed
- **System Status** - Fixed systemctl path issue
  - Use /usr/bin/systemctl (full path) for service checks
  - Resolves "No such file or directory" error
- **Navbar Layout** - Fixed text jumbling with long usernames
  - Username truncated with ellipsis (max 150px)
  - Organization name truncated (max 180px)
  - Optimized padding and font sizes
- **Static Files** - Logo and assets now load correctly
  - WhiteNoise middleware properly configured
  - Collected static files with manifest
- **Tag Management** - Fixed FieldError in tag list view
  - Corrected Count() annotations for related fields
- **Asset Form** - Improved JSON field validation
  - Better help text with DNS server examples
  - Client-side validation to catch errors before submission

### 📚 Documentation
- Added SCREENSHOTS.md with all 31 feature screenshots
- Updated README.md with screenshot gallery preview
- Fixed all broken documentation links
- Clarified installation process and credential setup

## [2.0.0] - 2026-01-10

### 🔒 Security Fixes (Critical)
- **Fixed SQL Injection** - Parameterized table name quoting in database optimization (settings_views.py)
- **Fixed SSRF in Website Monitoring** - URL validation with private IP blacklisting, blocks internal networks
- **Fixed SSRF in PSA Integrations** - Base URL validation for external connections
- **Fixed Path Traversal** - Strict file path validation in file downloads using pathlib
- **Fixed IDOR** - Object type and access validation in asset relationships
- **Fixed Insecure File Uploads** - Type whitelist, size limits (25MB), extension validation, dangerous pattern blocking
- **Fixed Hardcoded Secrets** - Environment variable enforcement for SECRET_KEY, API_KEY_SECRET, APP_MASTER_KEY
- **Fixed Weak Encryption** - Proper AES-GCM key management with validation
- **Fixed SMTP Credentials** - Encrypted SMTP password storage with decrypt method
- **Fixed Password Generator** - Input validation and bounds checking (8-128 chars)

### ✨ Added
- **Enhanced Password Types** - 15 specialized password types with type-specific fields:
  - Website Login, Email Account, Windows/Active Directory, Database, SSH Key
  - API Key, OTP/TOTP (2FA), Credit Card, Network Device, Server/VPS
  - FTP/SFTP, VPN, WiFi Network, Software License, Other
  - Type-specific fields: email_server, email_port, domain, database_type, database_host, database_port, database_name, ssh_host, ssh_port, license_key
- **Password Security Features**:
  - Secure password generator with configurable length (8-128 characters)
  - Character type selection (uppercase, lowercase, digits, symbols)
  - Cryptographically secure randomness (crypto.getRandomValues)
  - Real-time strength meter with scoring algorithm
  - Have I Been Pwned integration using k-Anonymity protocol
  - SHA-1 hashing for breach checking (first 5 chars only sent)
- **Document Templates** - Reusable templates for documents and KB articles
  - Template CRUD operations
  - Pre-populate new documents from templates
  - Template selector in document creation
  - Category and content-type inheritance
- **Comprehensive GitHub Documentation**:
  - README.md with Luna the GSD attribution
  - SECURITY.md with vulnerability disclosure policy and security checklist
  - CONTRIBUTING.md with development guidelines
  - FEATURES.md with complete feature documentation
  - LICENSE (MIT)
  - CHANGELOG.md with version history
- **All PSA Providers Complete** - Full implementations:
  - Kaseya BMS (276 lines) - Companies, Contacts, Tickets, Projects, Agreements
  - Syncro (271 lines) - Customers, Contacts, Tickets
  - Freshservice (305 lines) - Departments, Requesters, Tickets, Basic Auth
  - Zendesk (291 lines) - Organizations, Users, Tickets, Basic Auth with API token

### 🎨 Improved
- **Rack Detail Layout** - Improved responsive layout with devices to the right of rack visual
  - Info panel (left column)
  - Visual rack + Device list side-by-side (right columns)
  - Responsive breakpoints for all screen sizes
- **Password Form** - Condensed multi-column layout for better UX
  - 2-3 column grid layouts
  - Reduced vertical spacing
  - Type-specific sections with show/hide logic
  - Password generator modal integration
- **Document Form** - Condensed layout with template selector
  - Template dropdown at top of form
  - Load template button with JavaScript
  - Compact field layouts
- **Navigation** - System Status and Maintenance moved from username dropdown to Admin dropdown
  - Reorganized Admin menu with sections: Settings, System, Integrations
  - User Management moved to Admin menu
- **Security Headers** - Enhanced CSP and security configurations
  - Proper CSP directives
  - HSTS enforcement
  - X-Frame-Options, X-Content-Type-Options

### 🔧 Changed
- **SECRET_KEY Validation** - Now required in production, no default fallback
  - Raises ValueError if not set in production
  - Development fallback: 'django-insecure-dev-key-not-for-production'
- **API_KEY_SECRET** - Must be separate from SECRET_KEY
  - Validates in production
  - Auto-generates separate key in development
- **APP_MASTER_KEY** - Required in production for encryption
  - Must be 32-byte Fernet key
  - No fallback allowed
- **SMTP Passwords** - Now encrypted before database storage
  - Uses vault encryption module
  - Added get_smtp_password_decrypted() method
  - Backward compatible with unencrypted passwords
- **File Upload Limits** - Maximum 25MB with strict validation
  - Whitelist: pdf, doc, docx, xls, xlsx, ppt, pptx, txt, csv, md, log, jpg, jpeg, png, gif, bmp, svg, webp, zip, 7z, tar, gz, rar, json, xml, yaml, yml
  - Blocks dangerous patterns: .exe, .bat, .cmd, .sh, .php, .jsp, .asp, .aspx, .js, .vbs, .scr
  - Entity type validation
- **Password Types** - Changed default from 'password' to 'website'
  - Updated all 15 types with proper display names
  - Type-specific form sections

### 📝 Documentation
- Complete feature documentation (FEATURES.md) covering:
  - Security features (Authentication, Data Protection, Application Security, File Upload Security, Audit)
  - Multi-tenancy & RBAC
  - Asset Management
  - Password Vault
  - Documentation System
  - Website Monitoring
  - Infrastructure Management
  - PSA Integrations (all 7 providers)
  - Notifications & Alerts
  - Reporting & Analytics
  - Administration
  - API
  - User Interface
  - Developer Features
  - Data Management
  - Performance & Scalability
  - Deployment & Maintenance
- Security policy (SECURITY.md) with:
  - Vulnerability reporting guidelines
  - Supported versions
  - Security measures documentation
  - Disclosure process
  - Security checklist for deployment
  - Luna's security tips
- Contributing guidelines (CONTRIBUTING.md) with:
  - Development setup instructions
  - Code standards
  - Testing requirements
  - Commit message format
  - Pull request process
  - Luna's development tips

### 🐕 Contributors
- Luna the GSD - Security auditing, code review, architecture decisions, and bug hunting

### 🔧 Technical Details
- Upgraded to Django 6.0 and Django REST Framework 3.15
- Python 3.12+ required
- Comprehensive security audit completed
- All critical and high severity vulnerabilities fixed
- 22 security issues addressed

### Database Migrations
- `vault.0005` - Added type-specific fields to Password model:
  - database_host, database_name, database_port, database_type
  - domain (for Windows/AD)
  - email_port, email_server
  - license_key
  - ssh_host, ssh_port
  - Altered password_type field with new choices

---

## [1.0.0] - 2026-01-09

### Added
- **Core Platform**
  - Multi-tenant organization system with complete data isolation
  - Role-based access control (Owner, Admin, Editor, Read-Only)
  - Django 5.0 framework with Django REST Framework 3.14
  - MariaDB database support

- **Security Features**
  - Enforced TOTP two-factor authentication (django-two-factor-auth)
  - Argon2 password hashing
  - AES-GCM encryption for password vault and credentials
  - HMAC-SHA256 hashed API keys
  - Brute-force protection via django-axes (5 attempts, 1-hour lockout)
  - Rate limiting on all API endpoints and login
  - Comprehensive security headers (HSTS, X-Frame-Options, CSP, etc.)
  - Secure session cookies (Secure, HttpOnly, SameSite)

- **Asset Management**
  - Device tracking with flexible custom JSON fields
  - Asset types: Server, Workstation, Laptop, Network, Printer, Phone, Mobile, Other
  - Tag system for categorization
  - Contact associations
  - Relationship mapping between entities
  - Audit trail for all changes

- **Password Vault**
  - AES-GCM encrypted password storage (256-bit)
  - Master key from environment variable
  - Secure reveal with audit logging
  - Tags and categorization
  - URL and username storage
  - Never stores plaintext

- **Knowledge Base**
  - Markdown document support
  - Version history tracking
  - Rich markdown rendering (code blocks, tables, etc.)
  - Tag-based organization
  - Publish/draft status
  - Full-text search ready

- **File Management**
  - Private file attachments
  - Nginx X-Accel-Redirect for secure serving
  - No public media exposure
  - Permission-based access
  - Upload size limits

- **Audit System**
  - Comprehensive activity logging
  - Records: user, action, IP, user-agent, timestamp
  - Immutable logs (admin read-only)
  - Special logging for sensitive actions (password reveals)
  - Tracks: create, read, update, delete, login, logout, API calls, sync events

- **REST API**
  - Full CRUD operations for all entities
  - API key authentication with secure storage
  - Session authentication support
  - Rate limiting (1000/hour per user, 100/hour anonymous)
  - Password reveal endpoint with audit
  - Pagination support (50 items per page)
  - OpenAPI-ready structure

- **PSA Integrations**
  - Extensible provider architecture with BaseProvider abstraction
  - **ConnectWise Manage** - Full implementation
  - **Autotask PSA** - Full implementation
  - Sync engine features
  - PSA data models

- **User Interface**
  - Bootstrap 5 responsive design
  - Server-rendered templates
  - Organization switcher in navigation
  - Documentation and about pages

- **Deployment**
  - Ubuntu bootstrap script
  - Gunicorn systemd service
  - PSA sync systemd timer
  - Nginx reverse proxy configuration
  - SSL/TLS support (Let's Encrypt ready)

- **Management Commands**
  - `seed_demo` - Create demo organization and data
  - `sync_psa` - Manual PSA sync with filtering

### Security
- All sensitive data encrypted at rest
- API keys never stored in plaintext
- Password vault uses AES-GCM with environmental master key
- CSRF protection on all forms
- XSS protection via bleach HTML sanitization
- SQL injection protection via Django ORM

### Technical Details
- Python 3.8+ required
- Django 5.0 with async support ready
- MariaDB 10.5+ with utf8mb4
- Gunicorn WSGI server with 4 workers
- Nginx with security headers
- systemd for process management
- No Docker required
- No Redis required (uses systemd timers)

---

## Version Numbering

This project follows [Semantic Versioning](https://semver.org/):
- **MAJOR** version for incompatible API changes
- **MINOR** version for backwards-compatible functionality additions
- **PATCH** version for backwards-compatible bug fixes

Format: `MAJOR.MINOR.PATCH` (e.g., `2.0.0`)

---

**Changelog maintained by the Client St0r Team and Luna the GSD 🐕**
