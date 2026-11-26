# MSPZero Monitoring Health and Reliability Standard

**Specification version:** 1.1.0
**Status:** Contract as implemented by Clientst0r; 1.1.0 adds coverage over time (gaps, recovery, backfill)
**Schema:** [`monitoring-health/schema-1.1.0.json`](monitoring-health/schema-1.1.0.json)
([1.0.0](monitoring-health/schema-1.0.0.json) stays published; every 1.0.0 record is a valid 1.1.0 record)
**Reference implementation:** [`events/source_health.py`](../../events/source_health.py) (pure Python, no framework imports);
coverage and backfill: [`events/coverage.py`](../../events/coverage.py)
**Example payloads:** [`monitoring-health/examples/`](monitoring-health/examples/)

> **Core principle.** An absence of alerts is not evidence of a healthy system unless monitoring is verified to be
> functioning correctly.

---

## Contents

1. [Why "zero alerts" does not mean "healthy"](#1-why-zero-alerts-does-not-mean-healthy)
2. [Scope and terms](#2-scope-and-terms)
3. [The four independent fields](#3-the-four-independent-fields)
4. [Telemetry contract](#4-telemetry-contract)
5. [Collector behaviour](#5-collector-behaviour)
6. [Freshness, retry, transitions and notification](#6-freshness-retry-transitions-and-notification)
7. [Presentation and AI rules](#7-presentation-and-ai-rules)
8. [Security and tenant isolation](#8-security-and-tenant-isolation)
9. [Conformance tests](#9-conformance-tests)
10. [Adopting the standard in another product](#10-adopting-the-standard-in-another-product)
11. [Reporting health to Clientst0r](#11-reporting-health-to-clientst0r)
12. [Compliance matrix](#12-compliance-matrix)
13. [Versioning and changelog](#13-versioning-and-changelog)
14. [Acknowledgment](#14-acknowledgment)

[Appendix A — Coverage audit of Clientst0r 3.17.790](#appendix-a--coverage-audit-of-clientst0r-317790)

The key words MUST, MUST NOT, SHOULD and MAY are used as in RFC 2119.

---

## 1. Why "zero alerts" does not mean "healthy"

A monitoring dashboard that shows **0 alerts** can mean two very different things:

* the source was read successfully and nothing happened, or
* the source could not be read at all — the credentials expired, an API permission was removed, the endpoint
  was unreachable, the response was malformed, or the events were retrieved but could not be stored.

A single counter loses that difference, and the second case is the dangerous one: it looks exactly like a quiet,
well-protected customer. This standard keeps *whether monitoring works* separate from *what monitoring found*,
requires positive evidence before anything is shown as healthy, and makes every product that consumes the data
— dashboards, wallboards, notifications, customer reports and AI summaries — follow the same rules.

## 2. Scope and terms

The standard applies to any component that collects operational or security data and presents its result:
security connectors (EDR, SIEM, firewall, identity), RMM alert collection, backup monitoring, infrastructure and
website monitoring, event ingestion pipelines, and products that report their own health to another product.

| Term | Meaning |
|---|---|
| **Source** | One configured integration that is collected from, e.g. one vendor connection for one customer. |
| **Collection attempt** | One run that asks a source for data in a query window. |
| **Query window** | The time range an attempt asked for (`start` may be null for a full sync). |
| **Verification** | Evidence that an empty result is trustworthy (§5.2). |
| **Tenant** | The customer the source belongs to. Provider-wide sources have no single tenant. |
| **Product** | The application that owns the source and produces the record (`product_id`). |

All timestamps are UTC, ISO 8601, with a trailing `Z` in payloads.

## 3. The four independent fields

Each source record carries four fields that MUST be modeled independently. A source can be healthy with active
critical alerts; a source can report zero alerts while broken. Never conflate them.

### 3.1 `health` — operational health of the collector

| Value | Meaning |
|---|---|
| `healthy` | The latest collection succeeded completely, was verified, and is within the freshness threshold. |
| `degraded` | Working partly: some records were rejected, or a transient failure (unreachable, timeout, rate limited) has not yet persisted. |
| `failed` | Collection does not work: a non-transient failure (credentials, permissions, configuration, invalid response, ingestion), or a transient one that persisted (§6.3). |
| `unknown` | Not verified: never collected, an empty window that could not be verified, or stale data. |

### 3.2 `collection_outcome` — what the latest attempt did

`success` · `partial` (some records rejected) · `failed` · `not_attempted`.

### 3.3 `alert_status` — what monitoring found

| Value | Meaning |
|---|---|
| `active_alerts` | Alerts were found (or are open) for this source. Factual even when collection is degraded. |
| `no_alerts` | A **verified, complete, fresh** collection found nothing. Only valid when `health` is `healthy`. |
| `unknown` | Monitoring cannot say whether there are alerts. |

### 3.4 `failure_reason` — why it is not working (null when nothing is wrong)

| Value | Typical evidence | Transient? |
|---|---|---|
| `authentication_failure` | HTTP 401, invalid key, expired token | no |
| `permission_denied` | HTTP 403, missing API scope or role | no |
| `endpoint_unavailable` | connection refused, DNS failure, HTTP 5xx | yes |
| `timeout` | connect / read timeout, HTTP 408 / 504 | yes |
| `rate_limited` | HTTP 429 (honour `Retry-After`) | yes |
| `invalid_response` | not JSON, wrong shape, adapter returned no list, other HTTP 4xx | no |
| `ingestion_failed` | records retrieved but could not be stored | no |
| `stale_data` | last success older than the freshness threshold (set at read time) | — |
| `configuration_error` | missing URL / token, HTTP 404 / 405, address refused by the outbound policy | no |
| `other` | anything else (classify more precisely when possible) | no |

### 3.5 Derived display states

People see one of these labels, derived from the four fields (`display()` in the reference implementation).
Nothing stores a label; the derivation is the same everywhere.

| Display state | Label | Derived when | Icon (Font Awesome) |
|---|---|---|---|
| `healthy_quiet` | Healthy / quiet | `health=healthy`, `alert_status=no_alerts` | `fa-circle-check` |
| `healthy_active` | Healthy / alerts | `health=healthy`, `alert_status=active_alerts` | `fa-bell` |
| `healthy_recovering` | Healthy / recovering | `health=healthy` while a coverage gap is not recovered yet (1.1.0, §6.5) | `fa-clock-rotate-left` |
| `degraded` | Degraded | `health=degraded` (no more specific state) | `fa-triangle-exclamation` |
| `permission_denied` | Permission denied / Authentication failed | reason `permission_denied` or `authentication_failure` | `fa-lock` |
| `source_unavailable` | Source unavailable | `health=failed`, reason `endpoint_unavailable` or `timeout` | `fa-plug-circle-xmark` |
| `ingestion_failed` | Ingestion failed | `health=failed`, reason `ingestion_failed` | `fa-inbox` |
| `collection_failed` | Collection failed | `health=failed`, any other reason | `fa-circle-xmark` |
| `stale` | Stale | reason `stale_data` | `fa-hourglass-end` |
| `unknown` | Unknown | anything else | `fa-circle-question` |

Severity order for roll-ups (worst first): permission denied = source unavailable > ingestion failed = collection
failed > stale > degraded > unknown = healthy / recovering > healthy / alerts > healthy / quiet.

Coverage (§6.5) is shown next to these states, never folded into them: current health says whether collection
works now; coverage says whether the source's events were seen as they happened.

## 4. Telemetry contract

### 4.1 Fields

| Field | Type | Required | Null means | Notes |
|---|---|---|---|---|
| `schema_version` | string `1.y.z` | yes | — | Consumers accept any 1.x. |
| `product_id` | string `[a-z0-9._-]` | yes | — | e.g. `clientst0r`, `rem0te`, `st0r`. |
| `tenant_id` | string | yes | provider-wide | The **producer's** tenant id; consumers map it explicitly (§8). |
| `source_id` | string ≤ 200 | yes | — | Stable and opaque; never contains a secret. |
| `source_type` | string | yes | — | e.g. `security`, `rmm`, `backup`, `monitor`. |
| `health` | enum §3.1 | yes | — | |
| `collection_outcome` | enum §3.2 | yes | — | |
| `alert_status` | enum §3.3 | yes | — | |
| `failure_reason` | enum §3.4 or null | yes | no failure | |
| `completeness` | `complete` / `partial` / `unverified` | yes | — | |
| `verification` | enum §5.2 or null | no | not recorded | |
| `freshness` | `fresh` / `stale` | yes | — | Evaluated at the time the record is produced. |
| `freshness_threshold_minutes` | integer 15–43200 | yes | — | Configurable per source. |
| `last_attempt_at` | UTC timestamp | yes | never attempted | |
| `last_success_at` | UTC timestamp | yes | never succeeded | |
| `query_window` | `{start, end}` or null | no | not windowed | `start` null = full sync. |
| `records.retrieved` | integer ≥ 0 | yes | — | Returned by the source for the window. |
| `records.processed` | integer ≥ 0 | yes | — | Normalized into the product's shape. |
| `records.rejected` | integer ≥ 0 | yes | — | Could not be normalized or stored. |
| `records.committed` | integer ≥ 0, ≤ retrieved when retrieved > 0 | yes | — | Stored successfully. |
| `newest_event_at` | UTC timestamp | yes | **unknown** | Never invented (§5.4). |
| `newest_event_basis` | `source_order` / `validated_timestamps` / `unknown` | no | — | |
| `consecutive_failures` | integer ≥ 0 | yes | — | Reset by a successful attempt. |
| `duration_ms` | integer ≥ 0 | no | — | |
| `display_state` | enum §3.5 | no | — | Convenience; consumers MAY re-derive. |
| `diagnostic` | string ≤ 500 or null | no | none | Redacted (§8). |
| `coverage` | object or null | no (1.1.0) | not tracked | Coverage over time, §6.5. |
| `coverage.state` | enum §6.5 | yes, in `coverage` | — | Current coverage of the source. |
| `coverage.last_verified_coverage_at` | UTC timestamp | no | never verified | End of the last completely collected window (the cursor). |
| `coverage.gap` | object or null | no | no gap in 30 days | The open gap, else the most recent one. |
| `coverage.gap.state` | `coverage_gap` / `recovered_late` / `partial_recovery` / `unrecoverable_gap` | yes, in `gap` | — | |
| `coverage.gap.coverage_lost_at` | UTC timestamp | no | — | Last verified coverage before the outage: events after it were not seen. |
| `coverage.gap.outage_started_at` | UTC timestamp | no | — | The first failed read (or when a stopped collector went stale). |
| `coverage.gap.recovered_at` | UTC timestamp | no | not recovered | The first successful read after the outage. |
| `coverage.gap.resolved_at` | UTC timestamp | no | still open | When the gap's outcome was decided. |
| `coverage.gap.failed_reads` | integer ≥ 0 | no | — | Failed reads during the gap. |
| `coverage.gap.backfill_state` | `pending` / `running` / `complete` / `incomplete` / `failed` / `unsupported` / `disabled` or null | no | not started | |
| `coverage.gap.events_delivered_late` | integer ≥ 0 | no | — | New events stored for the gap after the fact. |
| `coverage.gap.duplicates_skipped` | integer ≥ 0 | no | — | Already stored; not stored, ticketed or notified again. |
| `coverage.gap.records_rejected` | integer ≥ 0 | no | — | Retrieved but not storable (prevents `complete`). |
| `coverage.gap.max_delivery_delay_seconds` | integer ≥ 0 or null | no | unknown | Largest ingestion time minus event time. |
| `coverage.gap.lookback_truncated` | boolean | no | — | Part of the gap was older than the lookback allowed. |
| `coverage.gap.complete` | boolean | yes, in `gap` | — | True exactly when `state = recovered_late`. |
| `coverage.history_capability` | object or null | no | not declared | `supports_history`, `max_lookback_minutes`, `ordering`, `pagination` as declared by the provider (§6.5.2). |

### 4.2 Examples

| State | File |
|---|---|
| Healthy, verified quiet window | [`healthy-quiet.json`](monitoring-health/examples/healthy-quiet.json) |
| Healthy with alerts | [`healthy-active.json`](monitoring-health/examples/healthy-active.json) |
| Degraded (partial ingestion) | [`degraded-partial.json`](monitoring-health/examples/degraded-partial.json) |
| Failed (permission denied) | [`failed-permission.json`](monitoring-health/examples/failed-permission.json) |
| Unknown (empty window not verifiable) | [`unknown-unverified.json`](monitoring-health/examples/unknown-unverified.json) |
| Stale | [`stale.json`](monitoring-health/examples/stale.json) |
| Collecting again, gap not recovered yet (1.1.0) | [`coverage-gap-recovering.json`](monitoring-health/examples/coverage-gap-recovering.json) |
| Gap recovered completely, events delivered late (1.1.0) | [`recovered-delivered-late.json`](monitoring-health/examples/recovered-delivered-late.json) |
| Quiet now, earlier gap unrecoverable (1.1.0) | [`unrecoverable-gap.json`](monitoring-health/examples/unrecoverable-gap.json) |

```json
{
  "schema_version": "1.0.0", "product_id": "clientst0r", "tenant_id": "42",
  "source_id": "security:31:7", "source_type": "security",
  "health": "failed", "collection_outcome": "failed", "alert_status": "unknown",
  "failure_reason": "permission_denied", "completeness": "unverified",
  "freshness": "fresh", "freshness_threshold_minutes": 60,
  "last_attempt_at": "2026-11-20T12:10:00Z", "last_success_at": "2026-11-20T12:05:00Z",
  "records": {"retrieved": 0, "processed": 0, "rejected": 0, "committed": 0},
  "newest_event_at": "2026-11-20T12:03:41Z", "consecutive_failures": 1
}
```

### 4.3 Cross-field rules

The JSON Schema cannot express these; validators MUST enforce them (`validate()` in the reference implementation):

1. `health = healthy` requires `collection_outcome = success`, `completeness = complete` and `freshness = fresh`.
2. `alert_status = no_alerts` requires `health = healthy`.
3. `collection_outcome = failed` requires a `failure_reason`.
4. `records.committed` ≤ `records.retrieved` when `retrieved` > 0.
5. The major version of `schema_version` must match the consumer's.
6. (1.1.0) `coverage.state = verified_quiet` requires `health = healthy`, `alert_status = no_alerts` and no open
   gap.
7. (1.1.0) An open gap (`coverage.gap.state = coverage_gap`) forbids `alert_status = no_alerts` and makes
   `coverage.state` `coverage_gap`.
8. (1.1.0) `coverage.gap.complete` is true exactly when `coverage.gap.state = recovered_late`.
9. (1.1.0) `recovered_late` requires a fully declared history capability (history supported, a maximum
   lookback, an ordering and a pagination completeness signal other than `none`) and `lookback_truncated`
   false.

### 4.4 Idempotency and deduplication

* Each attempt MAY carry a `collection_id`. A record with the same `collection_id` as the last one stored for the
  source is ignored, so a retried report does not count twice (failure counters stay correct).
* Events inside a collection are deduplicated by the source's own event id (Clientst0r: `external_id` per
  connection; a re-delivery updates the alert and never lowers its severity).
* Transitions are recorded with compare-and-set on the stored display state, so two workers record one
  transition once.

* (1.1.0) Backfilled events go through the same deduplication as live ones. An event already stored is counted
  as a duplicate and creates no ticket, incident, notification or second record; only a newly stored event is
  marked delivered late.

### 4.5 Retention

The record is a **current-state** row per source (overwritten by each attempt). History is kept as audit entries
of state transitions (§6.4), retained with the product's audit log. Coverage gaps (1.1.0) are kept as one row per
gap that a later outage never overwrites (§6.5.5). Diagnostics are short and redacted; no event
content is stored in the health record.

## 5. Collector behaviour

### 5.1 Failures are never empty results

A collector MUST raise (or otherwise report a failure) on an HTTP error, a refused permission, a malformed
response or a transport failure. Returning an empty list means only "the query succeeded and the window is
empty". Errors MUST NOT be swallowed into an empty list.

### 5.2 Empty-window verification

When a window comes back empty:

1. Confirm the query itself completed (status, shape).
2. Where the provider supports it, run **one bounded verification probe**: read-only, tenant-scoped, at most one
   small page (e.g. `top=1`, no filter beyond the tenant), within the provider's documented limits. Do not assume
   every API accepts an unfiltered query; use the provider-specific capability.
3. A failed, forbidden or malformed probe **fails the read** (classified as in §3.4); it is not a quiet window.
4. No uncontrolled retries and no expensive API-wide queries.
5. If the source offers no way to verify, record `verification = not_supported`: the result is `health = unknown`,
   `completeness = unverified`, `alert_status = unknown` — never healthy / quiet.

| `verification` | Counts as verified empty? |
|---|---|
| `probe_passed` | yes |
| `connection_test` — an authenticated read in the same attempt that could have failed on the same permissions | yes |
| `records_returned` | n/a (window not empty) |
| `not_supported` | **no** |
| `push_only` — the source pushes to us; a quiet period cannot be confirmed | **no** |

### 5.3 Counting

Count `retrieved`, `processed`, `committed` and `rejected` per attempt. One bad record does not abandon the run;
it is counted and the outcome is `partial` (health `degraded`, reason `ingestion_failed`). If nothing could be
stored, the outcome is `failed` with reason `ingestion_failed`.

### 5.4 Newest event

Do not assume chronological order. The newest event is:

* the first record, **only** if the provider documents newest-first ordering (`source_order`) and that record's
  timestamp validates; otherwise
* the maximum of the timestamps that validate (`validated_timestamps`): timezone-aware, not before 2000, not more
  than 5 minutes in the future;
* otherwise **unknown** (null). Never invent a value; never let a later attempt with no valid timestamps move it.

### 5.5 Collection cursor

A collector's incremental cursor ("since") MUST advance only after a complete, successful window. A failed or
partial attempt leaves it where it was, so the window is asked for again rather than silently skipped.

## 6. Freshness, retry, transitions and notification

### 6.1 Freshness

Each source has a configurable threshold (default: three poll intervals, minimum 15 minutes; 120 minutes when
unknown). At read time a source whose last success is older than its threshold is shown as **stale**: `health`
`healthy` becomes `unknown`, `alert_status` `no_alerts` becomes `unknown`, `failure_reason` becomes
`stale_data` unless a failure reason is already known. A scheduled sweep evaluates freshness because a collector
that stopped running writes nothing.

### 6.2 Retry and backoff

After a failed attempt the next attempt waits `min(cap, base × 2^(failures−1))`, half fixed and half random
jitter (base 60 s, cap 1 h in Clientst0r), and never less than the provider's `Retry-After`. A failing source is
**never** disabled automatically and its failure is never suppressed.

### 6.3 Transient versus persistent

Transient reasons (`endpoint_unavailable`, `timeout`, `rate_limited`) on a source that has succeeded before are
`degraded` for the first two consecutive failures and `failed` from the third. Every other reason is `failed`
immediately.

### 6.4 Transitions, audit and notification

* Every change of the derived display state is written to the audit log with the old and new state, the four
  fields and the failure count.
* Technicians are notified when a **critical** source enters a persistent failure state (`failed`) or goes
  stale, **once** per source and state (deduplicated, at most once per 30 minutes), and once when it recovers.
  Degraded (transient) states are visible on the dashboards but do not notify, to avoid alert floods.
* Persistent failures appear in the product's system warnings until resolved.

### 6.5 Coverage gaps, recovery and backfill (1.1.0)

Added from community feedback in GitHub Discussion #161: a source that recovers after several failed reads and
then backfills the missed window must be marked **recovered, delivered late** — not look verified quiet — so
analysts know those alerts were not seen in real time.

#### 6.5.1 States

Coverage is tracked independently per tenant and per source.

| State | Label | Meaning | Icon |
|---|---|---|---|
| `verified_quiet` | Verified Quiet | Collection verified and uninterrupted; no qualifying alerts. | `fa-circle-check` |
| `active_monitoring` | Active Monitoring | Collection verified and uninterrupted; alerts arriving in real time. | `fa-satellite-dish` |
| `coverage_gap` | Coverage Gap | Interrupted now, or recovered but the missed window is not resolved yet. | `fa-link-slash` |
| `recovered_late` | Recovered – Delivered Late | The missed window was retrieved and proven complete; its events were not seen in real time. Shown as **Recovered – None Missed** when the complete window held no events. | `fa-clock-rotate-left` |
| `partial_recovery` | Partial Recovery | Part of the window was retrieved, or completeness could not be proven. Alerts may be missing. | `fa-circle-half-stroke` |
| `unrecoverable_gap` | Unrecoverable Gap | The window cannot be retrieved (no history support, nothing returned). Alerts may be missing permanently. | `fa-ban` |
| `not_verified` | Not Verified | No coverage claim is possible (e.g. push-only sources). Not one of the six states above. | `fa-circle-question` |

`coverage_gap`, `recovered_late`, `partial_recovery` and `unrecoverable_gap` are also the states of a gap
record. The source's current state is `coverage_gap` while it has an open gap; otherwise it follows the current
collection. An interruption is **never** represented as verified quiet: while a gap is open the source's
`alert_status` cannot be `no_alerts` and its display state is `healthy_recovering` even if collection works again.

#### 6.5.2 Declared history capability

Each provider declares what it can return for a past window:

| Field | Values | Meaning |
|---|---|---|
| `supports_history` | true / false / null | Events can be asked for by time window. |
| `max_lookback` | duration / null | How far back the provider keeps and returns events. |
| `ordering` | `ascending` / `descending` / `unordered` / null | Result ordering (`unordered`: every timestamp is validated). |
| `pagination` | `cursor_exhausted` / `short_page` / `total_count` / `none` / null | How the provider signals the end of the results. |

Null in any field means **not declared**, and an undeclared capability never makes a window complete.

#### 6.5.3 When a window is fully recovered

A gap is `recovered_late` only when **both** hold:

1. the declared capability is complete (history supported, a maximum lookback, a known ordering and a
   completeness signal other than `none`), **and**
2. the retrieval proved the end of the results by that signal — `cursor_exhausted`: no next cursor *and* an
   explicit end; `short_page`: a page shorter than the requested limit; `total_count`: as many records fetched as
   the provider's total — with no record rejected and no part of the gap older than the lookback.

A successful (HTTP 200) response alone proves nothing. Otherwise the gap is `partial_recovery` when anything was
retrieved or covered, else `unrecoverable_gap`. A source without history support resolves at recovery: what the
first successful read delivered is all there is (`partial_recovery` if it delivered anything, else
`unrecoverable_gap`).

#### 6.5.4 Backfill behaviour

* Runs in the scheduler or collector, **never** on page render.
* Requests the window from the last verified coverage to the recovery time, never further back than the provider's
  maximum lookback or the product's lookback cap.
* Pages are bounded; each page's records and its checkpoint (the next page token) are committed together and
  persisted, so a restart resumes at the next page and a page fetched twice finds only duplicates.
* A failed page is retried with the backoff of §6.2 from the same checkpoint; after a bounded number of attempts
  the gap is resolved as `partial_recovery` or `unrecoverable_gap`.
* A source that fails again before its window is recovered keeps one gap (it grows), resumed from the same
  checkpoint.
* Backfilled records go through the product's normal ingest path: deduplication keys, alert-to-ticket rules,
  incident correlation and playbook approvals apply unchanged. Nothing is bypassed or auto-approved because an
  alert arrived late.

#### 6.5.5 Timestamps, delayed events and history

* The event's own time (validated; else unknown) is kept separately from the ingestion time, and the delivery
  delay (ingestion minus event time) is recorded.
* A newly stored event is **delivered late** when its event time falls inside an open gap — or, without a
  trustworthy time, when it came from the backfill or the first read after recovery. Tickets and incident
  timelines created from it say so.
* Delayed events are identifiable wherever alerts are shown (alert lists, incident details, the event timeline,
  wallboards), with an icon and text, and filterable.
* Each gap is its own record: failed reads, consecutive failures, outage start, recovery time, last successful read,
  last verified coverage, backfill result, events delivered late, duplicates skipped and maximum delay. A later
  outage opens a new record; gaps stay visible after recovery.

#### 6.5.6 Notifications

Configurable, through the product's existing technician notifications, **once per gap**: when a critical source
has been interrupted longer than a threshold (Clientst0r default 60 minutes; 0 switches it off), and when a gap is
resolved as `partial_recovery` or `unrecoverable_gap` (default on). Each change of these settings is audited.

## 7. Presentation and AI rules

1. A green / healthy indicator represents **verified** operational health only.
2. Zero alerts without verified collection is shown as unknown, never as healthy or "all clear".
3. Stale, partial, failed and unknown are each identifiable, with an icon and text (never colour alone), a
   tooltip, and the last successful collection time.
4. Monitoring health and alert severity are shown separately (a separate column, badge or strip).
5. Roll-ups: a tenant is **verified** only when every critical source is verified healthy; one failed, stale or
   unknown critical source makes the tenant unverified. Provider-wide sources count against every tenant they
   serve.
6. AI: health is decided by deterministic code, never by a model. AI analysis receives the source-health facts
   (`ai_context()`: verified flag, visibility statement, per-source state and last success; no credentials, no
   error text, no event content). Output about a scope that is not verified MUST carry the deterministic
   visibility statement, e.g.:
   *"Zero threats detected in the successfully monitored sources. Monitoring is not verified for Microsoft
   Defender (source unavailable), so overall security status cannot be verified."*
   The product enforces this on the model's output (`guard_ai_text()`); a model cannot override it.
7. Customer-facing "all clear" messages are sent only when monitoring is verified.
8. (1.1.0) Current health and coverage history are shown separately, each state with icon, text and tooltip.
   Wallboards show outage duration, events delivered late and the maximum delivery delay, and can filter to delayed
   alerts and historical gaps. A recent gap that was not fully recovered is added to the visibility statement
   ("Alerts from … may be missing: the coverage gap could not be fully recovered.").

## 8. Security and tenant isolation

* A collector writes only its own source's record; the tenant is taken from the source's configuration, **never
  from the payload**. A compromised or malfunctioning integration cannot change the health of another source or
  tenant.
* Records are exposed only to users and integrations authorized for that tenant. Provider-wide records are
  visible only to users who can see every tenant. Shared sources never reveal other tenants' ids.
* Diagnostics are redacted (credentials, tokens, `user:pass@` URLs, JWTs, authorization headers) and capped at
  500 characters. No event content, no customer data, no secrets in health records, notifications or AI prompts.
* Verification probes are read-only, bounded and tenant-scoped.
* Cross-product reports (§11) use authenticated, least-privilege credentials with explicit tenant mapping.

## 9. Conformance tests

A product MUST pass the applicable cases before claiming conformance. Fixtures must be deterministic (mocked HTTP,
fixed clocks). Clientst0r's implementations are in `events/tests_source_health.py` (cases A–J come from the
original Phase 82 acceptance list).

| # | Case | Expected | Clientst0r test |
|---|---|---|---|
| C1 | Verified successful collection, zero alerts | `healthy` / `no_alerts` only with verification; unverified → `unknown` | `test_A_verified_quiet_window` |
| C2 | Successful collection with active alerts | `healthy` / `active_alerts` | `test_C2_active_alerts_with_healthy_collector` |
| C3 | Permission denied (403, also from the probe) | `permission_denied`, never quiet | `test_B_missing_permission` |
| C4 | Authentication failure (401) | `authentication_failure` | `test_C4_authentication_failure` |
| C5 | Endpoint unreachable / timeout | `endpoint_unavailable` / `timeout`, display source unavailable | `test_D_endpoint_unavailable` |
| C6 | Rate limiting | `rate_limited`, next attempt ≥ Retry-After; malformed → `invalid_response` | `test_C6_*` |
| C7 | Partial collection | accurate counts, `partial` / `degraded` | `test_G_partial_ingestion` |
| C8 | Failed ingestion | `ingestion_failed`, cursor not advanced | `test_C_failed_ingestion` |
| C9 | Stale data | stale after threshold; one notification | `test_E_stale_after_threshold`, `test_E_repeated_failures_go_failed` |
| C10 | Out-of-order timestamps | newest = max validated, else unknown | `test_F_unordered_results` |
| C11 | Recovery after failure | healthy, counters reset, recovery notice, audit trail | `test_J_recovery` |
| C12 | Tenant isolation | other tenants unchanged and not visible | `test_I_multi_tenant_isolation`, `ViewTests` |
| C13 | Duplicate and retried ingestion | same `collection_id` ignored; events deduplicated | `test_C13_duplicate_attempt_is_idempotent` |
| C14 | Disconnection from Clientst0r | producer keeps local state; Clientst0r shows the remote source stale | *planned with §11* |
| C15 | Incorrect / incomplete evidence presented to AI | output carries the visibility statement; model cannot claim healthy | `test_H_ai_cannot_report_healthy` |

Coverage cases (1.1.0; `events/tests_coverage.py`):

| # | Case | Expected | Clientst0r test |
|---|---|---|---|
| C16 | Healthy, no alerts | `verified_quiet`, no gap | `test_01_healthy_no_alerts` |
| C17 | Single failed read | gap opened at the last verified coverage, never quiet | `test_02_single_failed_read` |
| C18 | Multiple consecutive failures | one gap, failed reads counted | `test_03_multiple_consecutive_failures` |
| C19 | Recovery with complete backfill | `recovered_late`, events marked late, original times kept, delay recorded | `test_04_recovery_and_complete_backfill` |
| C20 | Recovery with no missed events | `recovered_late` with zero events ("None Missed"); gap stays on record | `test_05_recovery_with_no_missed_events` |
| C21 | Partial backfill (lookback) | `partial_recovery`, request bounded by the lookback | `test_06_partial_backfill_lookback_cap` |
| C22 | Source without history capability; undeclared capability | `partial_recovery` / `unrecoverable_gap`, never complete | `test_07_source_without_history_capability` |
| C23 | Backfill pagination failure | retried with backoff from the checkpoint, then `partial_recovery` | `test_08_backfill_pagination_failure` |
| C24 | Duplicates during recovery | no second alert, ticket, incident or notification | `test_09_duplicates_during_recovery` |
| C25 | Out-of-order events | lateness and delay from validated times, not order | `test_10_out_of_order_events` |
| C26 | Repeated outages | one record per gap; a failure during recovery extends the gap | `test_11_repeated_outages` |
| C27 | Restart during recovery | resumes at the persisted checkpoint, no duplicates | `test_12_restart_during_recovery` |
| C28 | Tenant isolation | other tenants' gaps and delayed alerts never visible | `test_13_tenant_isolation`, `CoverageViewTests` |
| C29 | Delayed high-severity alert | normal ticket rule and incident, marked delayed; playbook still needs approval | `test_14_delayed_high_severity_alert_goes_through_workflow` |
| C30 | Historical wallboard accuracy after recovery | gap state, outage, delivered-late count and max delay; current health separate | `test_15_historical_wallboard_accuracy_after_recovery` |
| C31 | Multiple sources in different states | each source keeps its own state; roll-up names unrecovered gaps | `test_16_multiple_sources_with_different_states` |
| C32 | Notifications | once per gap; threshold 0 switches off; non-critical sources silent | `CoverageNotificationTests` |

Schema conformance: every payload a product emits MUST validate against `schema-1.1.0.json` (or
`schema-1.0.0.json` for a 1.0.0 producer) **and** the cross-field rules (§4.3). `SchemaTests` validates the example payloads and checks that the schema's enumerations match the
reference implementation.

## 10. Adopting the standard in another product

No shared service or package is required. Each product keeps its own code and implements this specification.

**Options, from least to most coupling:**

1. Implement from this document and validate payloads against the JSON Schema plus §4.3.
2. Copy the reference implementation: `events/source_health.py` is a single file with no Django or third-party
   imports (standard library only). Pin the copy to a specification version and note it in the product.
3. Use the example payloads in `monitoring-health/examples/` as shared fixtures.

A separate package is not published yet: one file and a schema are cheaper to keep in step than a package, and
products deploy independently. Revisit when a third product adopts it.

**Python interface (reference):**

```python
from source_health import CollectionResult, evaluate, effective, display, to_contract, V_PROBE

result = CollectionResult(attempted_at=now, window_start=since, window_end=now,
                          retrieved=len(items), processed=len(items), committed=stored, rejected=failed,
                          verification=V_PROBE if probe_ok else '', event_times=[i['time'] for i in items],
                          error=exc)               # exc: None, or the exception that failed the attempt
fields = evaluate(result, previous)                # deterministic; never consults a model
shown = display(effective(fields, now))            # label, icon, tooltip
payload = to_contract(effective(fields, now), tenant_id=tenant, source_id=sid, source_type='rmm',
                      product_id='rem0te')
```

**TypeScript (for web or mobile consumers):**

```ts
type Health = 'healthy' | 'degraded' | 'failed' | 'unknown';
type Outcome = 'success' | 'partial' | 'failed' | 'not_attempted';
type AlertStatus = 'no_alerts' | 'active_alerts' | 'unknown';
type Reason = 'authentication_failure' | 'permission_denied' | 'endpoint_unavailable' | 'timeout'
  | 'rate_limited' | 'invalid_response' | 'ingestion_failed' | 'stale_data' | 'configuration_error' | 'other';
interface SourceHealthV1 {
  schema_version: string; product_id: string; tenant_id: string | null; source_id: string; source_type: string;
  health: Health; collection_outcome: Outcome; alert_status: AlertStatus; failure_reason: Reason | null;
  completeness: 'complete' | 'partial' | 'unverified'; freshness: 'fresh' | 'stale';
  freshness_threshold_minutes: number; last_attempt_at: string | null; last_success_at: string | null;
  records: { retrieved: number; processed: number; rejected: number; committed: number };
  newest_event_at: string | null; consecutive_failures: number;
  coverage?: Coverage | null;                                    // 1.1.0
}
type CoverageState = 'verified_quiet' | 'active_monitoring' | 'coverage_gap' | 'recovered_late'
  | 'partial_recovery' | 'unrecoverable_gap' | 'not_verified';
interface Coverage {
  state: CoverageState; last_verified_coverage_at?: string | null;
  gap?: { state: 'coverage_gap' | 'recovered_late' | 'partial_recovery' | 'unrecoverable_gap'; complete: boolean;
          coverage_lost_at?: string | null; outage_started_at?: string | null; recovered_at?: string | null;
          failed_reads?: number; events_delivered_late?: number; max_delivery_delay_seconds?: number | null;
          lookback_truncated?: boolean; backfill_state?: string | null } | null;
  history_capability?: { supports_history: boolean | null; max_lookback_minutes: number | null;
                         ordering: string | null; pagination: string | null } | null;
}
```

**Developer checklist**

- [ ] Collectors raise on HTTP errors, permission refusals and malformed responses; `[]` means empty only.
- [ ] Empty windows run a bounded probe, or are recorded as `not_supported` / `push_only`.
- [ ] Counts retrieved / processed / committed / rejected per attempt.
- [ ] Newest event from validated timestamps; unknown when none validate.
- [ ] Cursor advances only after a complete window.
- [ ] Freshness threshold per source, evaluated by a sweep as well as on write.
- [ ] Backoff with jitter and `Retry-After`; never auto-disable.
- [ ] Audit every display-state transition; notify once on persistent failure and once on recovery.
- [ ] Dashboards separate monitoring health from alert severity; no colour-only states; last success shown.
- [ ] AI receives `ai_context()` facts and its output is guarded.
- [ ] Tenant taken from configuration, never from payloads; outputs scoped to authorized tenants.
- [ ] Diagnostics redacted; no secrets or event content in health records.
- [ ] (1.1.0) A gap record per interruption; no `no_alerts` while a gap is open.
- [ ] (1.1.0) Provider history capability declared; complete only when declared and proven (§6.5.3).
- [ ] (1.1.0) Backfill off the request path, bounded, checkpointed, through the normal ingest path; late events marked.
- [ ] Conformance cases C1–C32 that apply pass; payloads validate against the schema and §4.3.

## 11. Reporting health to Clientst0r

*Status: specified, planned — not implemented in 1.0.0.*

Products MAY report their sources' health to Clientst0r over **Agit8or Connect** (the existing paired, signed
HTTPS connection between applications), not a new channel:

* **Transport:** a new inbound event type `monitoring.source_health` under the existing `events:publish` scope,
  delivered through Connect's queued, signed event delivery (retries, ordering, dead letters already exist).
* **Payload:** one schema 1.0.0 record per event; `tenant_id` must be a customer granted to the connection
  (`org-<n>`); anything else is refused. `product_id` must match the paired application's type.
* **Storage:** one current-state row per (connection, `source_id`), written only for that connection — a product
  can never change Clientst0r's own sources or another connection's sources.
* **Least privilege:** the scope allows publishing events for granted customers only; no administrative access,
  no reading of other data.
* **Intervals:** the product chooses its reporting interval (minimum 1 minute; reports above Connect's rate limit
  are refused, not queued without bound). Clientst0r applies the record's `freshness_threshold_minutes`; a
  product that stops reporting (or a Connect connection that goes Offline) is shown **stale**.
* **Offline behaviour:** a product keeps working and keeps its local monitoring state when Clientst0r is
  unreachable; Connect queues and delivers later. Clientst0r never treats a missing report as healthy.
* **Data minimisation:** no event content, credentials or customer data beyond the granted tenant id.

It will ship when the Connect event catalog takes the new event type (after the Quick Connect work in progress).

## 12. Compliance matrix

| Product | Standard version | Implementation status | Test coverage | Known limitations |
|---|---|---|---|---|
| Clientst0r | 1.1.0 | **Implemented** for polled security connectors, RMM sync, polled backup connections; derived records for website monitors, webhook / SIEM push sources and the event pipeline. Coverage gaps for polled security, RMM and backup sources (1.1.0, in progress) | C1–C13, C15 (`events/tests_source_health.py`); C16–C32 (`events/tests_coverage.py`) | §11 inbound reporting planned (C14). Backfill: Proxmox Backup Server declares history (7-day lookback, short-page signal); no shipped security vendor adapter declares history yet, so security gaps resolve as Partial Recovery or Unrecoverable Gap until Phase 84 connectors implement `fetch_history`; RMM sync is a current-state list (declared no history). Push sources (webhooks, SIEM) are Not Verified and have no gap records. No working security vendor API adapter ships yet (the Defender adapter is a stub), so the probe path is exercised by test adapters until Phase 84 connectors land. RMM alert-list errors are counted as rejected records (partial), not as a separate collection failure. Push-style backup connections keep their per-job freshness rules and are not recorded as collections. |
| rem0te | — | Not started | — | Adopt via §10; report to Clientst0r via §11. |
| st0r | — | Not started | — | |
| OPNManager | — | Not started | — | |
| m0nitor | — | Not started | — | |
| ExploitHound | — | Not started | — | |
| MailThreatZero | — | Not started | — | |

No product other than Clientst0r is compliant; update this table only after a product's conformance tests pass.

## 13. Versioning and changelog

Semantic versioning:

* **Patch** — wording, examples, clarifications; no behaviour change.
* **Minor** — new optional fields, new enumeration values that consumers can treat as `other` / `unknown`, new
  conformance cases. Consumers MUST ignore unknown fields.
* **Major** — removed or renamed fields, changed meaning, new required fields.

### Changelog

#### 1.1.0 — 2026-11-26

Coverage over time, from community feedback in GitHub Discussion #161 (roadmap 82.15–82.20):

* Optional `coverage` object: current coverage state, last verified coverage, the open or latest gap and the
  provider's declared history capability; display state `healthy_recovering`.
* Coverage states Verified Quiet, Active Monitoring, Coverage Gap, Recovered – Delivered Late, Partial Recovery,
  Unrecoverable Gap (and Not Verified).
* Completeness rule: a declared capability and a proven end of results, never a 200 response alone (§6.5.3).
* Backfill, timestamp, delayed-event, history and notification rules (§6.5.4–6.5.6); cross-field rules 6–9.
* Conformance cases C16–C32; schema 1.1.0 and three examples. Fully backward compatible with 1.0.0.

#### 1.0.0 — 2026-11-21

Initial contract, as implemented by Clientst0r (roadmap Phase 82.7–82.12):

* Four independent fields (health, collection outcome, alert status, failure reason) and derived display states.
* Telemetry record, JSON Schema 1.0.0, cross-field rules and example payloads.
* Empty-window verification, newest-event rules, cursor rule, freshness, retry, transition and notification rules.
* Presentation and AI rules; security and tenant isolation requirements.
* Conformance cases C1–C15; compliance matrix.
* Cross-product reporting over Agit8or Connect specified (planned).

## 14. Acknowledgment

The initial design was strengthened by feedback from **Dijar Vrella** in Clientst0r GitHub Discussion #161
(<https://github.com/agit8or1/clientst0r/discussions/161>): his recommendation to make a verified quiet period
visibly different from a source the collector could not read, his suggestions to record the last successful read,
the query window, counts read / normalized / accepted and the newest event time only when ordering can be trusted,
and his proposed acceptance check — replaying the same quiet window with a working endpoint, a missing permission
and a failed submission — which became conformance cases C1, C3 and C8.

Version 1.1.0 follows his next suggestion in the same discussion: a source that recovers after several failed
reads and backfills the missed window should be marked "recovered, delivered late" rather than look verified
quiet, so analysts know those alerts were not seen in real time.

## Appendix A — Coverage audit of Clientst0r 3.17.790

What existed before 1.1.0 for each coverage requirement (file:line at v3.17.790), and what 1.1.0 added. The
coverage work extends these pieces; it does not replace them.

| Requirement | Existing (3.17.790) | Gap | 1.1.0 |
|---|---|---|---|
| Per tenant and per source | `integrations/models.py:1953` `IntegrationSyncHealth` (one row per connection and kind, customer copied from the connection: `events/source_health_store.py:38–51`) | — | Gap rows (`events.CoverageWindow`) keyed by the same source id; customer copied from the health row |
| Failed reads, consecutive failures | `consecutive_failures` (`events/source_health.py:317`) | Failed reads per outage not kept after recovery | `CoverageWindow.failed_reads`, `first_failure_at`, `last_failure_at` |
| Outage start, recovery time | Only `state_changed_at` and audit transitions (`events/source_health_store.py:_transition`) | Not stored as data | `first_failure_at`, `recovered_at`, `resolved_at` |
| Last successful read / last verified coverage | `last_success_at`; cursor `window_end_complete` (`integrations/models.py:2006`, `events/source_health_store.py:131`) | — | Copied to `coverage_lost_at` when a gap opens; exposed as `last_verified_coverage_at` |
| Never verified quiet | `evaluate()` / `effective()` (`events/source_health.py:291`, `:379`) | After recovery a source looked Healthy / quiet even though it missed a window | `gap_open` keeps `alert_status` unknown, display `healthy_recovering` |
| Backfill after recovery | Security poll asks again from the cursor (`security_alerts/adapters/base.py:65`) — one call, no paging, no completeness; backup poll from last success − 2 days (`backup_monitoring/recording.py:118`), one page of 500 (`backup_monitoring/providers/pbs.py:160`); RMM full state sync (`integrations/sync.py:92`) | No pagination, checkpoint or completeness proof; nothing marked late | Scheduler backfill with durable checkpoints (`events/coverage.py:backfill_tick`); PBS paging |
| Deduplication | `upsert_alert` by connection + external id (`security_alerts/ingest.py:12`, `security_alerts/models.py:217`); `record_run` (`backup_monitoring/recording.py:61`); event layer `uniq_event_source_dedup` (`events/models.py:80`); auto-ticket join and hourly cap (`security_alerts/adapters/base.py:169`) | — | Reused unchanged; duplicates counted per gap |
| Original timestamps | `seen_at` only (`security_alerts/models.py:199`); vendor `occurred_at` used for the newest-event time then dropped; event layer `first_seen_at = seen_at` (`events/sources.py:75`) | Event time and delay not stored | `occurred_at`, `delivery_delay_seconds`, `delivered_late` on alerts and events |
| States | Eight health display states (`events/source_health.py:424`) | No coverage states | Six coverage states (+ Not Verified) |
| Capability declaration | `supports_empty_window_probe`, `ordering_guaranteed` (`security_alerts/adapters/base.py`) | No history capability | `HistoryCapability`; unknown = never complete |
| Delayed alerts visible | — | — | Alert list/detail, incident detail, event list/detail, reliability page, wallboard widget |
| Normal workflows | `_maybe_auto_ticket`; incident correlation with SR-37 playbook approval (`security_alerts/models.py:909`, `:954`) | — | Backfill uses the same path (`ingest_polled_alert`); ticket and incident marked delivered late |
| Notifications | Once per source and state per 30 minutes (`events/source_health_store.py:373`) | Nothing for long gaps or failed recovery | Once per gap, configurable threshold, audited settings |
| History after recovery | Current-state row plus audit transitions (§4.5) | Gap details lost | One row per gap, never overwritten |
| Isolation, RBAC, audit | Reliability views scoped by `events_view` (`events/views.py:260`); config changes audited | — | Gaps reachable only through scoped sources; coverage settings audited |
| Fault isolation | `events_tick` scheduler; `due()` backoff | — | Backfill in `events_tick` with its own budget, bounded pages and attempts, lookback cap |
