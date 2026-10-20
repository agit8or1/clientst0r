# Website & WAN Monitoring

Checks run from the ClientSt0r server outward. No agent is installed on anything being checked. There are two separate features, and only website monitors run on a schedule and send alerts:

| | Website monitors | WAN connection checks |
|---|---|---|
| **Where** | *Monitoring → Website Monitors* (`/monitoring/websites/`) | The WAN connection's page under its location; *Monitoring → WAN Connections* lists them |
| **What is checked** | An `http://` or `https://` URL | A ping to the WAN's monitor target (IP or hostname) |
| **When** | On a schedule, and on **Check Now** | Only when someone clicks **Check Status** |
| **Alerts** | Email and webhooks on down and recovery; certificate expiry emails | None |
| **History and uptime** | Every check is kept; 30/90/365-day uptime | Last result only |

There are no TCP port, DNS or keyword-match checks.

---

## Website monitors

### Creating a monitor

1. Go to *Monitoring → Website Monitors* and click **Add Website Monitor**.
2. Enter a name and the full URL, including `http://` or `https://`.
3. Set the check interval in minutes (default 60).
4. Choose the notifications: **Notify on down**, **Notify on SSL expiry** and **Notify on domain expiry** are on by default. Set the warning windows for certificate expiry (default 30 days) and domain expiry (default 60 days).

The scheduler looks for due monitors every 5 minutes, so an interval shorter than 5 minutes behaves like 5.

### What a check does

Each check sends one `GET` request with a 10-second timeout and does not follow redirects.

| Result | Status |
|---|---|
| 2xx response | **Active** |
| 3xx response (redirect) | **Warning**: the site answered; counts as up |
| Any other status code, a timeout, a connection error or an invalid certificate | **Down** |
| Address refused by the outbound-request guard | **Error**: a configuration problem, not an outage; no alert |

Addresses on private networks are refused unless `ALLOW_PRIVATE_IP_INTEGRATIONS=True` is set in `.env`. Cloud metadata addresses are always refused.

For `https://` URLs the certificate is validated, and the monitor records:

- the issuer and subject;
- the serial number;
- the issue and expiry dates;
- the TLS version.

An invalid chain or a name mismatch fails the check. Chain details are not stored.

**Check Now** on a monitor's page runs a check immediately.

### History and uptime

Every check is stored with its status, HTTP code, response time and error. History older than 400 days is deleted by a daily job.

Uptime is the share of checks in the window that were not **Down**. Redirects count as up. A monitor with no checks in the window shows no figure rather than 0% or 100%. Uptime appears in three places:

- **Status pages:** 30, 90 and 365 days for each published service.
- **The Monitor Uptime report:** 30 days per monitor, and overall.
- **Compliance evidence packs.**

The monitor list shows current status, response time, certificate expiry and last check time. It has no uptime column.

---

## Alerting (website monitors)

### Down and recovery emails

With **Notify on down** on:

- **When the site goes down:** one email is sent after **2 failed checks in a row**. You can change the threshold with the `WEBSITE_DOWN_ALERT_THRESHOLD` setting. Further failed checks send nothing.
- **When it recovers:** one email is sent on the first successful check after that.

Emails go to active superusers and to the admins and owners of the monitor's organization. They need outgoing email configured under *Settings → SMTP/Email* (`/core/settings/smtp/`). Without it, the alert is skipped and logged, but the down or recovered state is still recorded, so fixing email later doesn't send a stale alert.

There are no escalation policies, alert grouping or per-monitor recipient lists.

### Webhooks

Organization webhooks (the **Webhooks** page, `/core/webhooks/`) can subscribe to three monitor events:

| Event | Fires |
|---|---|
| `monitor.check_failed` | On every failed check |
| `monitor.down` | Once, when the down alert threshold is reached |
| `monitor.up` | Once, on recovery after a `monitor.down` |

`monitor.down` and `monitor.up` fire even when **Notify on down** is off, and with no email configured.

Webhooks must be switched on under *Settings → Features*. Each delivery is a JSON `POST`. If the webhook has a secret, the request is signed and the signature is in the `X-Webhook-Signature` header. The payload is plain JSON; there is no built-in Slack or Teams message format, so those tools need a relay that reshapes it.

```json
{
  "event": "monitor.down",
  "timestamp": 1792420320,
  "organization": "acme-corp",
  "webhook_id": 3,
  "data": {
    "monitor_id": 12,
    "name": "Main Website",
    "url": "https://example.com",
    "status": "down",
    "status_code": null,
    "response_time_ms": null,
    "consecutive_failures": 2,
    "error": "Connection timeout",
    "checked_at": "2026-10-19T14:31:58+00:00"
  }
}
```

### Certificate and domain expiry emails

A daily job emails about certificates that are inside their warning window or already expired. The window is the larger of the monitor's own setting and the global setting under *Settings → SMTP/Email*. Each certificate gets:

- one email when it enters its warning window;
- one more when it actually expires.

A renewed certificate starts over.

Domain expiry dates are **not** looked up automatically (there is no WHOIS lookup). Enter domains on *Monitoring → Expirations* (`/monitoring/expirations/`). The same daily job emails about those.

---

## WAN connection checks

A WAN connection is recorded on its location (see [Locations & WAN](locations.md)). To make it checkable:

1. Turn on **Enable uptime monitoring for this WAN connection**.
2. Enter a **monitor target**: the IP or hostname to ping, such as the site's public IP.

**Check Status** on the WAN's page sends one ping from the server (2-second timeout). It then records **Active** or **Down**, the response time and the time of the last outage. *Monitoring → WAN Connections* lists every WAN with monitoring enabled, with these results.

WAN checks have three limits:

- **No scheduling:** they don't run unless someone clicks **Check Status**.
- **No alerts:** they don't send email or webhooks.
- **Unused fields:** the form's check interval and the uptime field on the WAN page are not used yet.

To be alerted automatically when a site's connection drops, add a website monitor for something that answers over HTTP or HTTPS through that connection, such as the firewall's or router's web interface published on the WAN address.

---

## Status pages, incidents and maintenance

*Monitoring → Status Pages* (`/status/`) publishes chosen website monitors, under names you write for the audience, with their current status and uptime.

You post incidents and maintenance windows on a status page by hand, optionally linked to a ticket. Outages don't create incidents, and maintenance windows don't silence monitor alerts.

---

*Previous: [Password Vault](password-vault.md) · Next: [Security](security.md)*
