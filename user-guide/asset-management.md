# Asset Management

Track and manage all IT equipment, servers, network devices, and hardware assets across your organizations.

---

## Asset Tracking

Each asset record stores:

| Field | Description |
|-------|-------------|
| **Name, type, asset tag, serial number** | Identification. The type is a built-in type or a custom one (see below). |
| **Manufacturer and model** | Type them, or pick a product from the [equipment catalog](#equipment-catalog) to fill them in |
| **Hostname, IP address, MAC address** | Network identity |
| **OS, CPU, RAM, storage, firmware version** | Hardware and software details |
| **Rack-mount and rack units, port count** | For racks and switch/patch panel port maps |
| **Purchase date, expected lifespan, end-of-life reminders** | Lifecycle tracking |
| **Warranty expiry and warranty status** | Warranty tracking and expiry emails (when enabled in Settings) |
| **Primary contact, tags, notes** | People and labels |
| **Custom fields** | Extra fields your MSP defines (see below) |

The asset page also shows images attached to the asset, its relationships, linked RMM devices, and the values in its custom fields.

### Needs Reorder Flag
Mark an asset for physical replacement with the **↩ Reorder** flag. Flagged assets appear with a yellow badge in the asset list and can be filtered separately.

### Custom fields and custom asset types

MSP staff who can edit assets for every customer (and superusers) manage these at *Assets → Custom Fields & Types* (`/assets/custom-fields/`). They apply to every customer.

- **Custom fields** add inputs to the asset form. Each has a label, a key (the stored name), a type (text, long text, number, date, checkbox, dropdown, URL or email), optional help text, and can be required. Limit a field to certain asset types, or leave the list empty to show it on every type. Values appear on the asset's **Custom Fields** tab.
- **Custom asset types** are added to the built-in types in the asset form's **Type** list. A type that is in use can't be deleted; mark it inactive to stop offering it.
- Values that imports and integrations store (for example `discovered_os` from a network scan) keep showing on the Custom Fields tab under their stored names.
- Through the REST API, assets accept a custom type code in `asset_type` and return `asset_type_display`. `custom_fields` is a JSON object, and writing it replaces the whole object.

### Equipment catalog

*Assets → Equipment Catalog* (`/assets/vendors/`) lists manufacturers and their models, shared by every customer. On the asset form, **Catalog manufacturer** and **Catalog model** are an optional shortcut: picking a model fills in Manufacturer and Model (and rack size for rack-mount models). The catalog records who makes a product, not the reseller you bought it from. Everyone can browse it; only MSP staff who can edit assets for every customer can add or change entries.

---

## Network Management

| Feature | Details |
|---------|---------|
| **IP Addresses** | Track IPs and subnets per asset |
| **VLANs** | Assign assets to VLANs, manage VLAN definitions |
| **MAC Addresses** | Record all network interface MACs |
| **Network Diagrams** | Create visual topology maps |
| **Port Assignments** | See switch ports and patch panel connections per asset |

---

## Rack Management

Organize equipment in data center racks with a visual drag-and-drop layout.

```
┌─────────────────────────┐
│  Rack A — 42U           │
├─────────────────────────┤
│ 1U  Patch Panel A       │  ← grey
│ 2U  Core Switch         │  ← blue (network)
│ 3U  Server A (2U)  ●    │  ← green (active)
│ 5U  — empty —           │
│ 6U  NAS Storage (4U)    │  ← purple (storage)
│     ...                 │
│ 38U UPS (2U)            │  ← amber (power)
└─────────────────────────┘
  Power: 1.4 kW / 4.0 kW
  Temp:  22°C ✓
```

| Feature | Details |
|---------|---------|
| **U-space allocation** | Drag devices to any U position |
| **Power tracking** | Total draw vs. capacity with visual bar |
| **Environmental** | Log temperature and humidity readings |
| **Locations** | Organize racks by data center → room → row |

---

## Port Configuration

Switches and patch panels support full per-port configuration:

### Switch Ports

| Field | Options |
|-------|---------|
| **Description** | Free-text label (e.g., "Uplink to Core") |
| **Mode** | Access / Trunk / Hybrid |
| **Native VLAN** | Single VLAN for untagged traffic |
| **Tagged VLANs** | Multiple VLANs (Trunk/Hybrid mode only) |
| **Speed** | 100M / 1G / 10G / 25G / 40G / 100G |
| **Status** | Active / Inactive / Error |

> **Tip:** Tagged VLANs are automatically disabled in Access mode.

### Patch Panel Ports

| Field | Description |
|-------|-------------|
| **Label** | Port identifier |
| **Destination** | What the cable connects to |
| **Cable Type** | Cat5e, Cat6, Cat6a, fiber, etc. |
| **VLAN** | Associated VLAN |
| **Status** | Active / Inactive |

**Bulk edit** — configure all ports on one screen; save with a single click.

---

## Asset Types

The asset form offers about 60 built-in types, among them servers, desktops, laptops, mobile devices and tablets; switches, routers, firewalls, wireless access points and controllers, patch and fiber panels; NAS, SAN and backup appliances; printers, copiers and scanners; cameras, NVRs, door controllers and other access control equipment; UPS, PDU and generators; phones, PBX and conferencing equipment. Add your own under [Custom fields and custom asset types](#custom-fields-and-custom-asset-types).

---

## Reporting

- The asset list filters by type, manufacturer and the Needs Reorder flag.
- MSP staff can generate the **Asset Summary** and **Asset Lifecycle** reports (PDF, CSV or JSON) under *Reports*. See [Reports & Dashboards](reports.md).
- There is no Excel export.

---

*Previous: [Getting Started](getting-started.md) · Next: [Service Vehicles](service-vehicles.md)*
