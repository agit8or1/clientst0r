# Reports & Dashboards

Reports, dashboards and wallboards for the MSP: per-customer reports you can generate or schedule, built-in PSA and finance reports across customers, configurable dashboards and TV wallboards, and saved queries.

Reports are for MSP staff only. Most of them cover every customer, so customer users get a 403 under `/reports/` and don't see the Reports menu.

---

## Where Things Are

All under **More → Reports**, starting at `/reports/`.

| Page | URL |
|------|-----|
| Reports home (counts, quick links, recent reports) | `/reports/` |
| Dashboards | `/reports/dashboards/` |
| Wallboards | `/reports/wallboards/` |
| Report templates (generate a report) | `/reports/templates/` |
| Generated reports (history) | `/reports/generated/` |
| Scheduled reports | `/reports/scheduled/` |
| PSA reports | `/reports/psa/` |
| Saved queries | `/reports/saved-queries/` |

### Permissions

On top of being MSP staff, role permissions decide what you can do:

| Permission | Allows |
|------------|--------|
| **View dashboards** | Reports home, dashboards, wallboards, report templates, generating and downloading reports |
| **Manage dashboards** | Creating and editing dashboards and report templates |
| **Manage scheduled reports** | Creating, editing, pausing and deleting schedules |
| **View financial reports** | Profitability, revenue, AR and other money reports |
| **View SLA reports** | SLA trends and forecasts |

---

## Report Templates

A report template is a named report type. Generating it produces a file for one customer: the one selected in the organization switcher.

Built-in templates (available to every customer):

| Template | Contains |
|----------|----------|
| **Asset Summary** | Asset totals, recently added, needing reorder, warranty expired, and counts by type |
| **Asset Lifecycle** | Assets by age |
| **Password Security Audit** | Shared vault entries (not personal ones): totals, how many have TOTP, updated in the last 90 days, expired and expiring within 30 days, requiring reveal approval, by type and folder |
| **Document Usage** | Document totals, archived, recently created, counts by category and type |
| **Monitor Uptime** | 30-day uptime per website monitor and per monitored WAN connection, from their check history; overall uptime for websites |
| **Expiration Forecast** | Tracked expirations: already expired, due in the coming weeks and months, by type |
| **User Activity** | Audit log over the last 30 days: events by action, events per user (sign-ins and changes), failed sign-ins |
| **Organization Metrics** | Members, assets, vault entries, documents and monitors for the customer |

`update.sh` creates the built-in templates. On a new install or a Docker install, run `python manage.py create_default_reports` once to add them.

To add your own, go to *Templates → New Template*, give it a name and pick one of these report types. Staff can mark a template **Global** so every customer has it.

### Generating

1. Open *Templates*, pick a template and click **Generate Report**.
2. Choose **PDF**, **CSV** or **JSON**.
3. The report opens in *Generated Reports*, where you can view (PDF) or download it.

The formats are plain:

- **JSON** is the full report data.
- **CSV** has one row per top-level value, with lists written as JSON in the value column.
- **PDF** is a simple text document of the same data, good for an attachment or an audit trail. It isn't a formatted, charted report.

---

## Scheduled Reports

*Scheduled → New Schedule* runs a template on a schedule for the selected customer.

| Field | Options |
|-------|---------|
| **Template** | Any template available to the customer |
| **Frequency** | Daily, Weekly, Monthly (every 30 days) or Quarterly (every 90 days), counted from when the schedule is saved |
| **Delivery** | Email, Download Only, or Email and Download |
| **Format** | PDF, CSV or JSON |
| **Recipients** | Email addresses, separated by commas; required for the email options |

The scheduler's **Scheduled Reports** task (`run_scheduled_reports`, every 15 minutes, on by default; see *Settings → Scheduler*) generates each due report and saves it under *Generated Reports*. For the email options, each recipient gets their own message with the file attached, sent through the SMTP settings in *Settings → Email*. If SMTP isn't set up or sending fails, the report is still saved, the problem is noted on it, and the schedule moves on to its next run.

Schedules can be paused and resumed from the list without deleting them.

---

## PSA and Finance Reports

`/reports/psa/` and the Reports home link to reports that read tickets, time entries, invoices, contracts and procurement across all customers. They include:

- **Tickets:** open tickets by client, SLA breaches, response time by tech, resolution time by client, tickets by queue/type/priority, tickets by assignee, ticket aging, recurring issues (assets with repeat tickets), SLA trends and SLA forecast.
- **Profitability:** by client, tech, contract and project; effective hourly rate; revenue leakage; margin analytics; hardware margin.
- **Billing and accounting:** agreement, billing, accounting and bank reconciliation; AR aging; MRR forecast; quote conversion.
- **Operations:** KPI dashboard, operational metrics, workflow performance, trends, client health, executive scorecard, multi-location.
- **Procurement:** summary, vendor cost history, forecasting, asset lifecycle, software compliance.

Most take a date range and offer a CSV export.

---

## Dashboards

Dashboards are pages of widgets you choose. Create one at *Dashboards → New Dashboard*, then add widgets. Each widget shows one data source as a metric, table or chart. Data sources include:

- **Tickets and SLA:** open tickets, SLA-overdue tickets, tickets by priority, my assigned tickets, tickets opened in the last 30 days, SLA breach trend, average time to resolve.
- **Money:** revenue this period, revenue trend, top clients by revenue, unbilled hours, billable vs non-billable hours.
- **Customers and sales:** at-risk clients, client health breakdown, recent sales activity, low-stock items.
- **Monitoring and security:** monitors currently down, monitor status breakdown, SSL certificates and domains expiring soon, warranties expiring soon, security alerts (last 24 hours, open critical/high, by severity), failed logins and vault events in the last 24 hours, techs signed in.

## Wallboards

Wallboards are full-screen boards for a NOC or office TV. They use the same widgets as dashboards. A new board can start from a template (operations, tickets, security and alerts, monitoring, sales, client health, or empty). Each board has its own refresh interval, and several boards can rotate on a timer. The **Wallboard** quick link on the Reports home is a fixed ticket board: open tickets, SLA overdue, unassigned, P1, opened and closed today, the newest tickets, and techs on shift.

---

## Saved Queries

*Saved Queries* let you filter, choose columns and sort tickets, assets, vault entries (no secrets), invoices or time entries, save the query, and run it again later. A saved query can be limited to one customer, and shared with the other members of that customer.

---

*Back to [User Guide](README.md)*
