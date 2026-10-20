# Password Vault

Encrypted credential storage for teams — AES-256-GCM encryption, TOTP, breach detection, and access controls. Status and limitations of each capability: [FEATURES.md](../FEATURES.md#password-vault).

---

## Security Features

| Feature | Details |
|---------|---------|
| **Encryption** | AES-256-GCM at rest, with per-purpose keys derived from the install's master key (`APP_MASTER_KEY`); TLS in transit |
| **Server-side decryption** | Credentials are decrypted on the server only when an authorized user reveals or copies them. This is not a zero-knowledge design: anyone with the server and its master key can decrypt the vault |
| **Access Control** | Entries belong to an organization. Roles need **View passwords** to see any credential — in the vault, global search, dashboards, the ticket sidebar, the APIs, the mobile app and the browser extension. Access rules can narrow this further |
| **Audit Log** | Every reveal is recorded with user, time and IP; creates, edits and deletes appear in the audit log's request entries |
| **Reveal approval / break-glass** | Entries can require an approval before reveal; break-glass access is logged and emailed to administrators |
| **Session Security** | Idle timeout (default 60 minutes) and maximum session length (default 8 hours), set in Settings → Security; an environment variable overrides each when set |
| **Key rotation** | The master key can be rotated with `python manage.py rotate_encryption_key`; see [SECURITY.md](../SECURITY.md#key-rotation) |

---

## Breach Detection

ClientSt0r checks stored passwords against **Have I Been Pwned (HIBP)**:

- Uses k-anonymity: only the first 5 characters of the password's hash are sent; the password never leaves your server
- Breached entries are flagged with a **Breached** badge
- A scheduled scan runs daily (*Settings → Scheduler*); an individual entry can be checked on demand
- Saving a breached password can be blocked install-wide with the `HIBP_BLOCK_BREACHED` environment variable (off by default)

---

## Password Management

| Feature | Details |
|---------|---------|
| **Store** | Title, username, password, URL, notes, tags, folder, one of 15 credential types |
| **Search** | Global search matches titles, usernames, URLs and notes — never the password itself |
| **Copy** | Copy username or password to the clipboard with one click |
| **Reveal** | Show the password (requires an explicit click; logged) |
| **Folders and tags** | Organize entries |
| **Expiry** | Set an expiration date; email warnings before it passes |
| **Favorites** | Pin frequently used entries |

---

## Password Generator

| Option | Details |
|--------|---------|
| **Length** | 8–128 characters |
| **Character Sets** | Uppercase, lowercase, numbers, symbols (each toggleable) |
| **Strength Meter** | Visual strength indicator on the entry form |

---

## TOTP / Two-Factor Codes

Store TOTP secrets alongside credentials and generate one-time codes without a separate authenticator app:

1. Paste the TOTP secret into the vault entry
2. A live 6-digit code is displayed and refreshes every 30 seconds
3. Copy the code with one click
4. A QR code of the secret is available for moving it to an authenticator app

---

## Sharing & Collaboration

| Feature | Details |
|---------|---------|
| **Organization scope** | Members of the entry's organization whose role has **View passwords** can see it |
| **Access rules** | Allow or deny reveals by country, source IP range and time of day, scoped to one entry, one user or a whole organization; deny rules win |
| **Customer portal** | Off by default per entry; can be shown to all of the customer's users, specific users, or a list managed by the customer's admin |
| **Personal vault** | Private entries for one user (`/vault/personal/`); not shown to other users or in the portal |
| **Access history** | Reveals of an entry appear in the audit log (`/audit/`) |

---

## Import & Export

| Format | Import | Export |
|--------|:------:|:------:|
| Bitwarden / Vaultwarden JSON | ✓ (superusers, `/core/settings/vault-import/`) | — |
| IT Glue / Hudu (via their APIs) | ✓ (`/imports/`) | — |
| CSV / spreadsheet | ✓ (`/imports/`) — encrypted on import; re-running matches title + username + URL instead of duplicating | — |
| Encrypted backup | ✓ (`manage.py restore`) | ✓ (`manage.py backup`) |

There is no plaintext vault export. Backups keep vault secrets encrypted with the master key, so keep `APP_MASTER_KEY` safe: without it a restored vault cannot be decrypted.

---

*Previous: [Service Vehicles](service-vehicles.md) · Next: [Website & WAN Monitoring](wan-monitoring.md)*
