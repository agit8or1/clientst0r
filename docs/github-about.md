# GitHub repository metadata

What to put in the repository's **About** panel (the sidebar on
<https://github.com/agit8or1/clientst0r>) and why. Settings live under the ⚙️ next to
"About" on the repo home page — they are not stored in the repository, so this file is the
record of what they should say.

---

## Description

Keep it under GitHub's 350-character limit, lead with the positioning sentence, and only
claim what ships.

> Self-hosted IT documentation and service desk for MSPs. Client assets, runbooks, an
> encrypted credential vault and a native ticketing system with SLAs, contracts, quotes and
> invoices — multi-tenant, on your own infrastructure. Django 6 + MariaDB, Docker or
> one-line install.

**Shorter variant**, if the panel feels crowded:

> Self-hosted IT documentation and service desk for MSPs — client assets, runbooks, an
> encrypted vault and native ticketing with SLAs and billing, on your own infrastructure.

### Why this over the current description

The description in place at the time of writing opens with "Open-source self-hosted MSP
platform", which does not say what the product *does* until the second clause, and then
lists fourteen nouns. The replacement leads with the one sentence an evaluating MSP owner
needs, and keeps the feature list to the four things that distinguish it.

## Website

**Leave the website field empty**, or point it at the repository's own documentation.

The value currently configured — `https://clientst0r.mspreboot.com/` — does not resolve
(no DNS A record as of 2026-09-15), so the About panel links visitors to a dead host. There
is no other verified project website: `mspreboot.com` resolves and serves a consulting site
that does not mention the product, so it is not a substitute.

If a project site is stood up later, put it here. Until then, either:

- clear the field, so the About panel shows no broken link, or
- set it to `https://github.com/agit8or1/clientst0r#readme`.

There is **no public demo instance**, so no demo URL belongs here and the README does not
advertise one.

## Topics

Each of these maps to functionality that exists in the codebase today.

```
msp
self-hosted
it-documentation
service-desk
ticketing
psa
asset-management
password-vault
knowledge-base
multi-tenant
sla
helpdesk
django
python
docker
open-source
```

GitHub allows up to 20 topics; this is 16, leaving room.

### Changes from the current topic set

| Topic | Action | Reason |
|---|---|---|
| `multi-tenant` | **add** | Per-organization scoping is the core data model, and it is what MSP buyers search for. |
| `sla` | **add** | SLA timers with pause logic are implemented in the ticket engine. |
| `helpdesk` | **add** | Common search term for the service-desk half of the product. |
| `docker` | **add** | First-class install path with a published image at `ghcr.io/agit8or1/clientst0r`. |
| `it-glue-alternative` | **remove** | Competitor name in project metadata; the comparison pages under `docs/` still exist for anyone searching. |
| `hudu-alternative` | **remove** | Same. |
| `rmm` | **remove** | ClientSt0r integrates with RMM tools but is not one — the topic invites the wrong expectation. |
| `workflow-engine` | keep or drop | Accurate (workflow rules ship), but lower search value than the additions above. Drop it if you need the slot. |

Existing topics kept as-is: `msp`, `self-hosted`, `it-documentation`, `service-desk`,
`ticketing`, `psa`, `asset-management`, `password-vault`, `knowledge-base`, `django`,
`python`, `open-source`.

## Other repository settings worth checking

- **Releases are behind the code.** The newest published GitHub Release is `v3.17.495`
  while `config/version.py` reads `3.17.558`. The README's release badge reflects what is
  published, so it will read `v3.17.495` until releases are cut for the newer tags.
- **Social preview image** — not set. A 1280 × 640 crop of
  `docs/images/github/dashboard.png` would do.
