# Site collector (Phase 33)

A small poller that runs inside a client network, asks the server what to scan,
sweeps, and posts results back. It **polls outbound only** — nothing ever
connects into the client network.

## What is shipped and tested

The **server side is complete and tested**: collector registration, key rotation
and revocation, the config and results endpoints, device import, LLDP/CDP
topology ingestion, switch-port correlation and the on-demand scan flag. 112
tests cover it.

`collector.py` is a **reference implementation**. Its ping-sweep and ARP paths
work with nothing but the Python standard library. Its SNMP paths —
`emit_neighbours()` and `emit_switch_ports()` — are deliberately left as
documented extension points returning empty lists, because they need `pysnmp`
and real switch hardware to validate against, and an untested SNMP walk that
silently returns nothing would look exactly like a working feature that happens
to find no neighbours. The server accepts and stores that data today; the
docstrings give the exact shape it expects.

Packaging as a container is left to the operator — the script has no
dependencies, so a `FROM python:3-slim` with two `COPY` lines is the whole
Dockerfile.

## Security

The site key is a standing credential, unlike the Phase 32 one-shot token. What
keeps that acceptable:

* it reads **only its own scan settings** — no assets, no passwords, no other
  site;
* it writes **only** discovery results, into one organization and one location;
* it is rotatable and revocable, and both take effect immediately;
* every check-in and scan is audit-logged with a source IP.

If the key leaks, the holder learns which subnets one site sweeps and can file
device records there. It is not a way in.

Keep `/etc/clientst0r-collector.env` root-owned, mode 600.
