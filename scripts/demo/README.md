# Demo instance for documentation media

Everything in this directory exists to produce the screenshots in
[`docs/screenshots.md`](../../docs/screenshots.md) and the walkthrough video,
against a **real running ClientSt0r** that contains only invented data.

Nothing here is imported by the application at runtime. No app, no settings
module and no management command references it; it only runs when you invoke it.

## What it guarantees

- The database is a throwaway SQLite file under `$DEMO_DIR` — never the
  configured MariaDB.
- The deployment's `.env` is never read: `demo_settings.py` disables
  `load_dotenv()` before importing the project settings and supplies throwaway
  values for `SECRET_KEY`, `API_KEY_SECRET` and `APP_MASTER_KEY`, so no real
  database credential, encryption key or AI provider key reaches the demo.
- `MEDIA_ROOT`, `STATIC_ROOT` and `UPLOAD_ROOT` are under `$DEMO_DIR`, so
  nothing writes into a deployed tree, and logging goes to the console instead
  of `/var/log/itdocs`.
- Email uses the in-memory backend, so seeding cannot send anything.
- `setup_demo.py`, `seed_demo.py` and `scripts/capture_screenshots.py` refuse to
  run if the database they are pointed at does not look like a demo one.

## Requirements

The project's own Python environment, plus the `playwright` Python package and
its Chromium build for capturing (`pip install playwright && playwright install
chromium`, or a user-site install added to `PYTHONPATH`). Don't install it into
a production virtualenv.

## Regenerating the media

```bash
export DEMO_DIR=/var/tmp/clientst0r-demo     # start from an empty directory
export PYTHONPATH=scripts/demo:.

# 1. Build the isolated instance (schema + the whole fictitious dataset).
python scripts/demo/setup_demo.py

# 2. Serve it on a port nothing else uses. The two AXES_* variables make
#    Settings → Security show its "Set by environment" badges.
AXES_COOLOFF_TIME=1 AXES_FAILURE_LIMIT=5 \
  python manage.py runserver 127.0.0.1:8099 --settings=demo_settings --noreload

# 3. Capture. Themes are switched through the application's own toggle.
python scripts/capture_screenshots.py --out docs/images/github
python scripts/build_gallery.py

# 4. Record the walkthrough (writes MP4 + poster + transcript + captions).
python scripts/capture_walkthrough.py --out /var/tmp/clientst0r-media
```

Some dates in the dataset are relative to the moment it is built (SLA timers,
appointments, review dates), so build and capture in one sitting.

`$DEMO_DIR` is deliberately outside the repository: raw captures, the SQLite
file and the browser profile must not be committed.

## The dataset

`setup_demo.py` runs the application's own seed commands (`seed_demo_data`,
`psa_seed_defaults`, `seed_pci_dss`, `seed_hipaa`, `readiness_seed_samples`,
`psa_seed_portal_requests`) around `seed_demo.py` and `seed_compliance.py`.

`seed_demo.py` creates one MSP tenant (**Beacon Managed IT**) and four client
tenants — Northwind Logistics, Ridgeline Dental Group, Harbor Point Credit Union
and Cascade Manufacturing — with assets, documentation, runbooks, credentials,
tickets with time and SLA state, contracts, quotes, invoices, a project plan
with dependencies, a rack elevation, IPAM and monitors. It also fills the newer
screens: a technician's My Work queues (running timer, customer replies,
waiting queues, a pending approval, an internal-note draft), document version
history, drafts, an archived page, template drift and zero-result searches for
KB analytics, two readiness standards with a mix of met and unmet requirements
and an audited exception, a portal customer user with a submitted guided
request, and run history for the built-in scheduler. Individual steps can be
re-run by name: `python scripts/demo/seed_demo.py seed_my_work`.

`seed_compliance.py` enrols two clients in the compliance frameworks and answers
the controls in a weighted spread.

Every organization, person, hostname, address, IP and credential in it is
invented. Domains use the reserved `.example` TLD (the sample records from
`seed_demo_data`, kept in the Beacon tenant, use `.demo`) and addresses are
RFC 1918. Vault entries hold placeholder strings — and the application never renders a
secret into a list or a ticket in any case, so no screenshot needs masking.
