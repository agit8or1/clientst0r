# Locations & WAN Connections

Manage physical locations (offices, data centers, sites) and the WAN internet connections for each location.

---

## Overview

| Feature | URL |
|---------|-----|
| Location List | `/locations/` |
| WAN Connections | `/locations/{id}/wan/` |

---

## Locations

A **Location** represents a physical site where equipment is installed or staff work:

| Field | Description |
|-------|-------------|
| **Name** | e.g., "Head Office", "Data Center 1", "Remote Site A" |
| **Address** | Street, city, state, country |
| **Notes** | Free-text site notes |
| **Floor Plan** | Attach or auto-generate a floor plan diagram |

Locations provide a physical grouping for assets — assets can be associated with a location and further with a specific rack or room.

---

## WAN Connections

Each location can have one or more **WAN connections** — the internet links serving that site:

| Field | Description |
|-------|-------------|
| **Name** | e.g., "Primary Fibre", "4G Failover" |
| **ISP** | Internet service provider name |
| **Type** | Fibre / Cable / DSL / 4G/LTE / MPLS / etc. |
| **Bandwidth** | Download and upload speeds |
| **Public IP** | Static or range |
| **Circuit ID** | ISP circuit reference number |
| **Contract Expiry** | Renewal date |
| **Status** | Active / Inactive / Maintenance |
| **Notes** | Support contacts, escalation details |

### WAN Status Check

With monitoring enabled and a monitor target (IP or hostname) set, **Check Status** on the WAN detail page sends one ping from the ClientSt0r server and records up or down and the response time. The check runs only when you click it: it is not scheduled and sends no alerts.

> For automatic checks and down alerts, add a [website monitor](wan-monitoring.md) for something that answers over HTTP or HTTPS through that connection.

---

## Floor Plans

Attach a floor plan image to a location to map where equipment is physically installed:

- **Upload** — attach an existing PNG/SVG floor plan
- **Generate** — auto-generate a simple floor plan from rack/asset data
- **Import** — import from a structured JSON format

Floor plans are visible on the location detail page and can be linked from asset records.

---

*Back to [User Guide](README.md)*
