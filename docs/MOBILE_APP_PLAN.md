# Mobile App API Plan

**Status:** Planning doc for the v3.17.345 → v3.17.353 mobile-API backend release train. Companion document to Phase 8 in `docs/ROADMAP.md`.

This describes the **server-side** API that an Expo React Native client (built in a separate `mobile/` worktree by another agent) will consume. The RN client itself is out of scope for this document.

## Found architecture

The repo is a Django 6 / Python 3.12 / MariaDB MSP platform with the following relevant pre-existing pieces:

| Concern | Where it lives | Notes |
|---|---|---|
| Django REST Framework | `requirements.txt`, `config/settings.py::INSTALLED_APPS` | Already installed (`djangorestframework==3.15.*`, `rest_framework.authtoken`). Default permission `IsAuthenticated`. |
| Existing REST API | `api/` | Generic API-key-authenticated REST API (`/api/`) for assets/contacts/passwords/etc. — used by the browser extension and external integrations. **We do not modify this.** |
| Session auth + 2FA | `accounts/middleware.py::Enforce2FAMiddleware`, `accounts/views.py` (TOTP via `django_otp.plugins.otp_totp.models.TOTPDevice`), `pyotp` | The web app uses session auth; 2FA is enforced via middleware. |
| Brute-force protection | `django-axes==6.1.*`, `AxesMiddleware` | Locks out IPs after repeated failed logins. |
| Tenant model | `core.Organization` + `accounts.Membership` (M2M user↔org with `Role`) | Every domain object is org-scoped. |
| Audit log | `audit.models.AuditLog` | `AuditLog.objects.create(action=..., user=..., object_type=..., ip_address=..., extra_data={...})` is the canonical helper. |
| Vault | `vault.models.Password` | `requires_reveal_approval` (Phase 37) gates plaintext behind `VaultRevealRequest`. `vault.access_rules.evaluate()` runs GeoIP/IP/time gates. |
| PSA tickets | `psa.models.Ticket`, `TicketComment`, `TicketStatus`, `TicketPriority` | Tenant FK is `organization → core.Organization`. |
| Assets | `assets.models.Asset` | Org-scoped via `BaseModel`. |
| Monitoring / expirations | `monitoring.models.WebsiteMonitor`, `monitoring.models.Expiration` | |
| Security alerts | `security_alerts.models.SecurityAlert`, `SecurityIncident` (Phase 23 v2 v3.17.338) | |
| KB | `docs.models.Document` (`content_type='markdown'`, `render_markdown()` helper, `is_global` flag) | This is the knowledge-base equivalent — Phase 22 closed using `docs.Document` with `is_visible_in_portal`. |
| TEST_MIDDLEWARE pattern | Multiple files (`api/tests.py`, `core/tests/test_tenant_isolation.py`, `psa/tests/_base.py`) | Strips `Enforce2FAMiddleware` + `AxesMiddleware` for fast view tests. |

## API approach

A **new `api_mobile/` Django app** under `/api/mobile/v1/`, separate from the existing `api/` namespace so we do not destabilise the browser-extension and external API key surface.

**Authentication:** DRF token auth (`rest_framework.authtoken`). Already in `INSTALLED_APPS`. Tokens are issued by the mobile login endpoint after credential + 2FA validation. The same user model is shared with the web app, so RBAC continues to work via `Membership`.

**Reasoning for token auth (vs SimpleJWT):** the project already has `rest_framework.authtoken` installed, the `authtoken_token` table will be auto-created by its migration, and per-device token revocation is straightforward. SimpleJWT would add a new dependency for no real benefit here. We can layer JWT on later if push-notification round-trips need a stateless verifier.

**Layered with existing auth — does not replace it.** The web app continues to use Django session auth + 2FA + Axes. The mobile API adds token auth as an **additional** authentication class for `/api/mobile/v1/`-prefixed views only.

**Throttling:** DRF throttle classes — `UserRateThrottle` 1000/day, `AnonRateThrottle` 60/hour globally; `LoginRateThrottle` 10/hour per IP for `/auth/login/`.

**CSRF:** DRF's `TokenAuthentication` is CSRF-exempt by design (the browser-only attack surface does not apply to a token-bearing native client). We document this explicitly so future reviewers do not file a "CSRF missing" finding.

**GeoIP / Axes / 2FA still apply.** The `AxesMiddleware` reads from the request stack so failed mobile logins still feed the IP lockout cache. Vault reveal endpoints continue to call `vault.access_rules.evaluate()` so GeoIP / IP / time rules apply identically to web and mobile.

## Mobile screens (what the RN agent will build)

The companion RN client will ship roughly these screens, all of which map to the API endpoints below:

1. **Login** — username/email + password; 2FA prompt if enabled.
2. **Dashboard** — counts at a glance (tickets, alerts, expirations, monitors).
3. **Organizations** — list + detail (browse the MSP's customer base).
4. **Assets** — list / search / detail per org.
5. **Tickets** — list / filter / detail / create / status update / add comment.
6. **KB** — list + search + read.
7. **Vault** — list (no secret) + detail (no secret) + explicit reveal action with biometric/PIN gate on the device.
8. **Monitors / Expirations** — uptime + cert/domain/warranty rollup.
9. **Security alerts** — counts by severity, optional drill-in.
10. **Profile / settings** — display name, theme, logout.

## Required backend endpoints

All under `/api/mobile/v1/`. All require `Authorization: Token <key>` except the login + MFA endpoints.

### Auth (v3.17.346)

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/login/` | username + password → `{token}` (or `{mfa_required: true, mfa_token}` if 2FA enabled) |
| POST | `/auth/mfa/` | `mfa_token` + `code` → `{token}` |
| POST | `/auth/logout/` | revokes the token |
| GET  | `/auth/me/` | returns current user + memberships |
| POST | `/auth/refresh/` | rotates the token (old token revoked, new token issued) |

### Dashboard + Orgs (v3.17.347)

| Method | Path | Purpose |
|---|---|---|
| GET | `/dashboard/` | counts: open tickets, critical tickets, expiring domains/certs, offline monitors, recent assets, security alerts, recent activity |
| GET | `/organizations/` | paginated list, search by name |
| GET | `/organizations/<id>/` | detail + related counts (assets/tickets/contacts) |

### Assets (v3.17.348)

| Method | Path | Purpose |
|---|---|---|
| GET | `/assets/` | paginated, `?search=`, `?organization_id=&type=&status=` |
| GET | `/assets/<id>/` | detail |

### Tickets (v3.17.349)

| Method | Path | Purpose |
|---|---|---|
| GET | `/tickets/` | `?status=&priority=&assigned_to_me=true&organization_id=&search=` |
| GET | `/tickets/<id>/` | detail with comments |
| POST | `/tickets/` | create |
| PATCH | `/tickets/<id>/` | partial update (status / priority / assignee; closing needs `resolution_summary` + `closure_category` and the closeout checks — v3.17.626) |
| POST | `/tickets/<id>/comments/` | add a comment |

### KB (v3.17.350)

| Method | Path | Purpose |
|---|---|---|
| GET | `/kb/` | list + search (matches `docs.Document.title` + body) |
| GET | `/kb/<id>/` | detail — returns `body` (raw markdown) AND `body_html` (rendered, sanitised by existing `Document.render_markdown()`) |

### Vault (v3.17.351, security-critical)

| Method | Path | Purpose |
|---|---|---|
| GET | `/vault/` | list — **never** returns secret value |
| GET | `/vault/<id>/` | detail — **never** returns secret value |
| POST | `/vault/<id>/reveal/` | explicit reveal — emits `AuditLog` with `event=vault_reveal_mobile`, sets `Cache-Control: no-store`, honours `VaultAccessRule` + `requires_reveal_approval`. If approval required, returns 202 + reveal-request URL instead of the secret. |

### Monitoring + security + profile (v3.17.352)

| Method | Path | Purpose |
|---|---|---|
| GET | `/monitors/` | website monitors (`monitoring.WebsiteMonitor`) |
| GET | `/expirations/` | domain + cert + warranty summary (`monitoring.Expiration`) |
| GET | `/security/summary/` | open-alert counts by severity, exposure score (defensive — falls back to 0 if Phase 23 v3 hasn't landed yet) |
| GET | `/profile/` | current user profile |
| PATCH | `/profile/` | update display name, phone, timezone, theme — never role/permission |

### Cross-cutting (v3.17.353)

* DRF throttle: `UserRateThrottle` 1000/day, `AnonRateThrottle` 60/hour, `LoginRateThrottle` 10/hour per IP.
* Management command `revoke_stale_mobile_tokens` — revokes tokens unused for >90 days; cron-friendly.
* Full unauthenticated-rejection sweep across every endpoint.

## Security considerations

1. **Vault list endpoints never return secret values.** Plaintext is only returned by the explicit `/reveal/` endpoint, which audits every call.
2. **Vault reveals respect `VaultAccessRule`** (Phase 31) — GeoIP, IP-CIDR, and time-of-day rules apply identically to web + mobile.
3. **Vault reveals respect `requires_reveal_approval`** (Phase 37) — if set, returns 202 with the `VaultRevealRequest` URL instead of the secret.
4. **2FA must be cleared.** Login returns a single-use `mfa_token` if the user has TOTP enabled; the actual API token is only issued after `/auth/mfa/` validates the 6-digit code.
5. **Axes lockout still applies.** Failed login bumps the same Axes counter the web login uses. Locked-out IPs get the same response.
6. **No-cache headers on vault detail + reveal.** `Cache-Control: no-store, no-cache, must-revalidate, private` + `Pragma: no-cache`.
7. **CSRF exemption is documented** — token auth is naturally immune; documented in this file so security review does not flag a regression.
8. **Per-device tokens.** Each login issues a new token; logout revokes only that token, not all sessions. The stale-token cron runs nightly.
9. **Profile PATCH cannot change role / membership / permissions** — those edits go through the existing web UI under accounts/.

## Dev / run instructions

```bash
# Activate venv
source /home/administrator/venv/bin/activate

# Install deps (DRF + authtoken already in requirements.txt)
pip install -r requirements.txt

# Run authtoken migration (first time only)
python manage.py migrate authtoken

# Run mobile API tests
python manage.py test api_mobile

# Smoke test login
curl -X POST https://yourhost/api/mobile/v1/auth/login/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"..."}'
```

## Known gaps / TODOs

* **Push notifications** are out of scope for this release train — the existing `WebPushSubscription` model already covers PWA push (Phase 21 v3.17.313); APNS/FCM for native binaries lands in the RN agent's range (v3.17.354+).
* **Offline cache shape** is defined by the RN client, not the API — endpoints return canonical JSON; client decides what to persist.
* **Token rotation on every request** is not implemented — tokens rotate explicitly via `/auth/refresh/`. Added in v3.17.353 if needed.
* **GeoIP for token-issuing** — login currently honours Axes (IP-based) but does not gate by country. Add later if a customer asks.
* **WebAuthn / passkeys for mobile** — deferred; TOTP is the universal floor.

---

## Mobile app shipped (v3.17.354–360)

The Expo React Native + TypeScript client lives at `mobile/`. Shipped across five releases:

| Release | Scope |
|---------|-------|
| v3.17.354 | Scaffold (Expo SDK 51 + Expo Router + TypeScript strict + TanStack Query + axios + zod), SecureStore-backed auth, login screen with MFA second-step. |
| v3.17.356 | Dashboard (stat tiles + recent tickets/assets/alerts), Organizations list/detail, Assets list (search + filters: org / type / status) + detail. |
| v3.17.357 | Tickets list (filter chips: open / mine / critical / closed / all), Ticket detail (status + priority chip-pickers, comments thread, add-comment with internal flag), New-ticket form, KB list + article (markdown via `react-native-markdown-display`). |
| v3.17.359 | Vault list (no secrets), Vault detail with audit-logged reveal flow (confirmation modal, in-state-only secret, 30s clipboard auto-clear, `expo-screen-capture` engaged, 202-approval branch handled), Monitoring (websites + expirations), Security summary, Settings (profile PATCH, server URL, theme override, logout, clear-local). |
| v3.17.360 | README + `eas.json` build profiles + placeholder icons + Phase 8 roadmap closeout. |

Versions skipped over by the mobile-app train (v3.17.355, v3.17.358) were taken by the concurrent Phase 23 release train.

### Screens delivered

`/login`, `/dashboard`, `/organizations`, `/organizations/[id]`, `/assets`, `/assets/[id]`, `/tickets`, `/tickets/[id]`, `/tickets/new`, `/kb`, `/kb/[id]`, `/vault`, `/vault/[id]`, `/monitoring`, `/security`, `/settings`.

### What still needs manual setup

* Apple Developer + Play Console accounts
* `eas init` to fill `extra.eas.projectId` (placeholder in `app.json`)
* iOS / Android signing keys (EAS can manage)
* Store listings (descriptions, screenshots, privacy policy URL)
* APNs key + FCM service-account JSON (only when push notifications ship)

### Deferred from Phase 8 (explicitly out of scope for this train)

* GPS auto-documentation engine (Sub-phase 8.2)
* Timeclock mobile UI (Sub-phase 8.3 mobile half — web side is separate)
* Background location, foreground-only fallback, off-shift suppression (Sub-phase 8.5)
* Push notifications — web push is already shipped (v3.17.313); APNs/FCM native pushes need a paid Apple Developer + Play Console flow
* Biometric unlock — needs `expo-local-authentication` + native rebuild
* iOS Azure SSO via in-app browser (the password fallback is implemented; Azure SSO integration is phase-2)
