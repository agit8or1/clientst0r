# What is ClientSt0r?

ClientSt0r is **self-hosted, open-source (MIT) IT documentation and service desk software
for Managed Service Providers (MSPs)** and IT teams.

It keeps client documentation, assets, credentials and support work in one structured,
searchable system that you run on your own server. Optional managed hosting and support
are offered separately by [MSP Reboot](https://mspreboot.com).

## Typical Use Cases

- Client documentation, runbooks and an internal knowledge base, with owners, review
  dates, drafts and version history
- Documentation readiness: standards for what each client must have documented, a score
  per client and a repair queue for the gaps
- Asset tracking, rack elevations and warranty / lifecycle dates
- Credential storage (AES-256-GCM encrypted vault with audited reveals)
- Network infrastructure (IPAM, VLANs, subnets)
- Service desk (opt-in): tickets, SLAs, contracts, quotes and invoices, with a My Work
  page for each technician
- Customer portal where clients see the tickets you share with them and request services
  through guided forms
- Fleet and service vehicle management

## Who It's For

- Managed Service Providers
- Internal IT departments
- Homelab operators needing structured documentation

## Technology

Built with Django (Python) on MariaDB, running on Linux. Install with Docker Compose or the
`install.sh` native installer; update from the web UI. See the
[README](../README.md#quick-start).

## Related

- [Moving from IT Glue](it-glue-alternative.md)
- [Moving from Hudu](hudu-alternative.md)
- [MSP Documentation Overview](msp-documentation.md)
- [Full feature list](../FEATURES.md)
