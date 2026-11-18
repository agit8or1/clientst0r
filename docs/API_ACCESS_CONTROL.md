# API access control

**Settings → Security → API Access Control** (superusers). Network rules for the inbound API and inbound
webhooks — roadmap Phase 81.

Rules are an extra check. They never grant access: a request that passes them still needs a valid credential,
the right permissions, its rate limits and customer isolation. Web pages (the app you sign in to) are not
covered here; the site-wide **Firewall & GeoIP** page covers them.

New and upgraded installs start **Unrestricted** with no rules, so nothing changes until an administrator
adds rules.

## What is covered

Every request whose path belongs to one of these endpoint groups:

| Endpoint group | Paths | Surface | Integration |
|---|---|---|---|
| REST API | `/api/` | API | — |
| GraphQL API | `/api/v2/graphql/` | API | — |
| Mobile app API | `/api/mobile/v1/` | API | — |
| Rem0te integration API | `/api/integration/v1/` | API | Rem0te |
| Agit8or Connect API | `/connect/v1/`, `/.well-known/agit8or-connect` | API | Agit8or Connect |
| Security vendor webhooks | `/security/webhook/` | Webhook | Security vendor connections |
| SIEM webhooks | `/security/siem/webhook/` | Webhook | SIEM endpoints |
| Distributor webhooks | `/integrations/distributors/webhooks/` | Webhook | Distributors |
| Payment provider webhooks | `/payments/webhooks/stripe/`, `/payments/webhooks/gocardless/` | Webhook | Stripe, GoCardless |
| Ticket partner webhooks | `/psa/partners/webhook/` | Webhook | Ticket partners |
| Emergency restart webhook | `/core/emergency-restart/` | Webhook | — |

New API or webhook routes are added to `api_access/groups.py`; a test fails if a group has no route.

## Rules

A rule is an IPv4 or IPv6 address or CIDR range, **allow** or **deny**, for the API, webhooks or both, with
one scope:

- **Global** — every covered request on that surface, subject to the global mode.
- **Customer** — API keys that belong to that customer.
- **API key** — one key ("this key may only be used from these networks").
- **Integration** — one integration's endpoints (for example Rem0te or SIEM endpoints).
- **Endpoint group** — one group from the table above.

Rules can expire (temporary access) and can be disabled without deleting them.

### Global mode (one per surface)

| Mode | Global allow rules | Global deny rules |
|---|---|---|
| Unrestricted | ignored | ignored |
| Allowlist only | required | ignored |
| Denylist | ignored | refused |
| Combined | required | refused |

Customer, API key, integration and endpoint-group rules apply in every mode.

### Precedence

1. A matching **deny** rule at any scope refuses the request. An explicit deny always beats an allow.
2. Each scope level (global, customer, integration, endpoint group, API key) that has at least one allow rule
   for the request is an **allowlist**: the address must match one of that level's rules. Default deny: once
   an allowlist applies, anything it does not list is refused.
3. An allowlist mode with no global allow rules refuses everything on that surface.
4. Then normal authentication, permissions and rate limits run.

Private addresses (`10.x`, `172.16–31.x`, `192.168.x`, `fd00::/8`, loopback) get no special treatment.
IPv4-mapped IPv6 addresses (`::ffff:192.0.2.1`) are matched as the IPv4 address.

**Fail closed:** if a request's address cannot be read, or the policy cannot be evaluated, the request is
refused whenever any restriction applies to it. With no restrictions configured, requests pass.

Global, integration and endpoint-group rules are checked before any view runs. Customer and API-key rules
are checked when the key is authenticated; a refused key is not marked as used.

## Client address and reverse proxies

The address used for rules comes from `core/client_ip.py`:

- Only a connecting peer listed in `TRUSTED_PROXY_CIDRS` may supply `X-Forwarded-For`. From anyone else the
  header is ignored and the connecting address is used.
- The chain is read from the nearest hop backwards; the first address that is not a trusted proxy is the
  client. An address a client puts at the front of the header is therefore ignored.
- `X-Real-IP` is never used.
- A request over gunicorn's unix socket (the local nginx) counts as coming from a trusted local proxy.
- A malformed `X-Forwarded-For` from a trusted proxy makes the address unreadable (refused under
  restrictions), never a pass.

**API Access Control → Client address** shows how your own request was read.

Set the trusted proxies in `.env` (comma-separated), then restart the app:

```
TRUSTED_PROXY_CIDRS=127.0.0.1/32,::1/128
```

List only the proxies you run. Never trust a whole private range unless every host in it is your proxy.

### Nginx

```nginx
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
```

With nginx on the same host over the unix socket, nothing else is needed. With nginx on another host, add its
address to `TRUSTED_PROXY_CIDRS`.

### HAProxy

```
option forwardfor
```

Add the HAProxy addresses to `TRUSTED_PROXY_CIDRS`.

### Cloudflare (or another CDN) in front of nginx

The CDN's edge addresses become hops in the chain. Either add the CDN's published ranges to
`TRUSTED_PROXY_CIDRS` (and keep them current), or have nginx restore the client address with its `real_ip`
module limited to those ranges and pass `$remote_addr` on. Without one of these, every request appears to
come from the CDN, and an allowlist of your own addresses refuses everything.

## Before a change is saved

Saving a rule, enabling one, changing a mode or importing rules shows the impact first:

- whether **your address** could still call the REST API;
- every **API key used in the last 90 days** that would be refused from the address it last used;
- a warning when a webhook mode becomes restrictive (webhook senders' addresses are not recorded in advance —
  check each vendor's published ranges).

High-impact changes need an explicit confirmation. Every change bumps the **policy version**, is applied on
the next request in every worker, and is written to the audit log.

**Test an address** evaluates any address against the saved policy for any endpoint group and API key, and
lists the rules that applied.

## Refused requests

Each refusal records the time, source address, endpoint group and integration, method and path (no query
string), API key prefix and customer when known, reason, matched rule and policy version. Repeats from one
source for the same reason within a minute share a row with a count, so a flood writes a handful of rows.
Request bodies, headers and key secrets are never stored. A source refused 10, 100 and 1000 times in an hour
is also reported in the server log.

## Import and export

**Export** downloads every rule as JSON. **Import** validates the whole file first (at most 1000 rules,
512 KB) and adds nothing if any rule is invalid; customer rules are matched by customer name and API-key rules
by key prefix. Imported rules are added; existing rules are not changed.

## Lockout recovery

There is no HTTP bypass. Recovery needs a shell on the server as the application user:

```bash
cd /home/administrator   # the install directory
venv/bin/python manage.py api_access_recover --status
venv/bin/python manage.py api_access_recover --unrestrict              # both surfaces
venv/bin/python manage.py api_access_recover --unrestrict --surface webhook
venv/bin/python manage.py api_access_recover --disable-rule 12
venv/bin/python manage.py api_access_recover --disable-all-rules
```

Each change is audited and takes effect on the next request. Disabled rules stay listed and can be
re-enabled from the settings page.

The settings pages themselves are web pages, so API rules never lock an administrator out of them.

## Planned (Phase 81)

API key expiry, rotation and per-key rate limits; webhook timestamp windows, replay protection and body
limits on every receiver; trusted proxies managed in Settings; an automatic rollback window for global
changes; notifications for repeated violations; optional mutual TLS. See `docs/ROADMAP.md`.
