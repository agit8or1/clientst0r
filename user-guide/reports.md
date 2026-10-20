# Reports & Analytics

Generate, schedule, and export reports across all data in your organization. Build custom dashboards and track trends over time.

---

## Overview

| Feature | URL |
|---------|-----|
| Reports Home | `/reports/` |
| Custom Dashboards | `/reports/dashboards/` |
| Report Templates | `/reports/templates/` |
| Generated Reports | `/reports/generated/` |
| Scheduled Reports | `/reports/scheduled/` |
| Analytics | `/reports/analytics/` |

---

## Custom Dashboards

Build organization-specific dashboards that combine widgets from multiple data sources:

| Widget Type | Shows |
|-------------|-------|
| **Asset count** | Total assets by type, status, or location |
| **Warranty alerts** | Assets with warranties expiring within 30/60/90 days |
| **Monitor status** | Website monitors currently down, and a breakdown by status; SSL certificates expiring soon |
| **Vault health** | Breached or expiring credentials count |
| **Vehicle fleet** | Fleet status and upcoming maintenance |
| **Recent activity** | Audit log summary |

- Create multiple dashboards per organization
- Dashboards are shareable with all org members
- Pin widgets and drag to rearrange layout

---

## Report Templates

Report templates define what data to include, how to format it, and who receives it.

| Field | Description |
|-------|-------------|
| **Name** | Template identifier |
| **Data Source** | Assets, Passwords, Vehicles, Monitors, Audit, etc. |
| **Filters** | Scope to specific types, statuses, date ranges |
| **Columns** | Choose which fields to include |
| **Format** | CSV, PDF, or HTML |
| **Output** | Download, email, or save to generated reports |

### Common Report Templates

- **Asset Inventory** — all assets with serial, location, warranty, status
- **Expiring Warranties** — assets with warranty ending in N days
- **Needs Reorder** — flagged assets requiring replacement
- **Breached Credentials** — vault entries with HIBP hits
- **Vehicle Maintenance Due** — overdue and upcoming service items
- **Monitor Uptime** — 30-day uptime per website monitor and overall, from the check history
- **User Activity** — audit log summary by user and action type

---

## Generating Reports

1. Go to *Reports → Templates* and select a template
2. Optionally override filters or date range
3. Click **Generate Report**
4. Download the result or save it to *Generated Reports*

Generated reports are stored and accessible at `/reports/generated/` with download history.

---

## Scheduled Reports

Automate report delivery on a recurring schedule:

| Field | Options |
|-------|---------|
| **Template** | Any report template |
| **Frequency** | Daily / Weekly / Monthly |
| **Day/Time** | When to run |
| **Recipients** | Email addresses to deliver to |
| **Format** | CSV, PDF, or HTML attachment |
| **Active** | Toggle schedule on/off |

Scheduled reports can be paused without deleting them. Delivery history is logged per scheduled report.

---

## Analytics

The analytics dashboard provides real-time metrics and trend charts:

- **Asset growth** — number of assets added over time
- **Vault usage** — new entries, reveals, breach rate
- **Audit events** — activity volume by type and user

---

*Back to [User Guide](README.md)*
