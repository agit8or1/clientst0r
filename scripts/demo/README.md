# Demo instance for documentation media

Everything in this directory exists to produce the screenshots in
[`docs/screenshots.md`](../../docs/screenshots.md) and the walkthrough video,
against a **real running ClientSt0r** that contains only invented data.

Nothing here is imported by the application at runtime. No app, no settings
module and no management command references it; it only runs when you invoke it.

## What it guarantees

- The database is a throwaway SQLite file under `$DEMO_DIR` — never the
  configured MariaDB.
- `MEDIA_ROOT` and `STATIC_ROOT` are under `$DEMO_DIR`, so `collectstatic`
  cannot write into a deployed tree.
- Email uses the in-memory backend, so seeding cannot send anything.
- `scripts/capture_screenshots.py` refuses to start if the database it is
  pointed at does not look like a demo one.

## Regenerating the media

```bash
export DEMO_DIR=/var/tmp/clientst0r-demo
export PYTHONPATH=scripts/demo:.

# 1. Build the isolated instance (schema + fictitious dataset).
python scripts/demo/setup_demo.py

# 2. Serve it.
python manage.py runserver 127.0.0.1:8099 --settings=demo_settings --noreload

# 3. Capture. Themes are switched through the application's own toggle.
python scripts/capture_screenshots.py --out docs/images/github

# 4. Record the walkthrough (writes MP4 + poster + transcript + captions).
python scripts/capture_walkthrough.py --out /var/tmp/clientst0r-media
```

`$DEMO_DIR` is deliberately outside the repository: raw captures, the SQLite
file and the browser profile must not be committed.

## The dataset

`seed_demo.py` creates one MSP tenant (**Beacon Managed IT**) and four client
tenants — Northwind Logistics, Ridgeline Dental Group, Harbor Point Credit Union
and Cascade Manufacturing — with assets, documentation, runbooks, credentials,
tickets with time and SLA state, contracts, quotes, invoices, a project plan
with dependencies, a rack elevation, IPAM and monitors.

Every organization, person, hostname, address, IP and credential in it is
invented. Domains use the reserved `.example` TLD and addresses are RFC 1918.
Vault entries hold placeholder strings — and the application never renders a
secret into a list or a ticket in any case, so no screenshot needs masking.
