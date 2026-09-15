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

**Recommended: `https://mspreboot.com`.**

The value configured until now — `https://clientst0r.mspreboot.com/` — does not resolve
(no DNS record, checked 2026-09-15), so the About panel was linking visitors to a dead
host. That has to change regardless of what replaces it.

There is no dedicated ClientSt0r product site. `mspreboot.com` does resolve and is the
consulting practice the project comes from, which makes it the most relevant *verified*
URL available. If a product site is stood up later, prefer it here — a dedicated site
serves a visitor looking for the software better than a consulting site does — and keep
the MSP Reboot links in the README and the gallery.

Interim alternative, if you would rather not point the About panel at a consulting site:
`https://github.com/agit8or1/clientst0r#readme`.

**There is no public demo instance**, so no demo URL belongs here, and the README does not
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
- **Social preview image** — not set. `docs/images/github/walkthrough-poster.png` is
  1920×1080 and crops cleanly to the 1280×640 GitHub wants.

## Related links to keep visible

ClientSt0r is built by the people behind **[MSP Reboot](https://mspreboot.com)**, an MSP
consulting practice. The README carries a link in its top navigation and a short section
near the bottom; the screenshot gallery carries one in its footer.

Keep that description accurate: MSP Reboot sells **consulting** — pricing, operations,
margins, service delivery and technology strategy — not a support contract for this
software. Do not describe it as a tools catalogue, a sponsor, or a paid support tier for
ClientSt0r, because none of those are true.
