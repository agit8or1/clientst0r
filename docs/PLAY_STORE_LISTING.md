# Play Console — Store Listing Copy

Pre-written copy for the Play Console **Main store listing** page. Lengths are inside Play Console limits. Edit freely; the wording rules in `CLAUDE.md` (no competitor name-dropping, "OPTIONAL AI" tag for AI-assisted features) apply if you change anything.

---

## App name (max 30 chars)
```
Clientst0r Mobile
```

(If "Clientst0r" is unavailable as a Play Store name due to similarity rules, alternative: `Clientst0r MSP` — 16 chars.)

---

## Short description (max 80 chars)
```
Field companion for IT technicians using Clientst0r — tickets, KB, vault, more.
```

(79 chars — counted.)

---

## Full description (max 4000 chars)

```
Clientst0r Mobile is the on-the-go companion app for technicians using the Clientst0r IT service-management platform. It connects to your organization's self-hosted Clientst0r server so your team can work tickets, look up client documentation, and access vaulted credentials from the field.

The app is designed for IT service providers (MSPs) and internal IT teams who already run Clientst0r on their own infrastructure. It is not a standalone product — you need a Clientst0r server URL and an account on it to sign in.

WHAT YOU CAN DO FROM THE APP

• PSA Tickets — File new tickets with a client picker, log time as you work, attach photos to comments, reassign with one tap, and check off SLA-driven due dates from a built-in calendar. Tickets you work on automatically deduct from the client's block-of-hours contract.

• Scheduled Tasks & Calendar — See the next 7 days at a glance on the dashboard. Tap any day to schedule a new task or look at open tickets due that day. Tasks you sign off close automatically.

• On-site Time & Geofencing — Clock in once, and the app auto-detects when you arrive at and leave a client site. Each visit records as a separate time entry against the matching ticket. Off-shift GPS is suppressed at the server.

• Vault — Search and reveal credentials for the clients you're working with. Per-credential approval gates, GeoIP rules, and access-rule denials are all honored on the device. Edit and rotate passwords without leaving the app.

• Assets — Read the full asset record (identity, hardware, lifecycle, primary contact). Edit on the fly. Link a vault secret to an asset so the next tech can find it in one tap.

• Dispatch — Daily dispatch board with overdue / today / upcoming buckets. Acknowledge an assignment, sign off when complete, comment as you go.

• Vehicles & Receipts — Log fuel fill-ups, file damage reports with photos, upload receipts that get OCR'd into structured records.

• Inventory — Scan a part QR code, see the on-vehicle / on-shelf count, adjust quantities.

• Knowledge Base — Search SOPs and KB articles.

• Workflow Runner — Start a workflow and step through stages with prompts, condition gates, and signatures.

PRIVACY AND SECURITY

The app is a thin client to the Clientst0r server you operate. It does not send data to any third-party service except the optional Sentry crash-reporting service (which only receives stack traces and device model — no PII). All traffic to your server is encrypted with TLS. On-device storage (auth token, server URL, basic profile cache) is encrypted with the Android Keystore. Vault secrets retrieved through the reveal flow are held in memory only — never written to disk.

Location is collected only while you are clocked in, and only against client sites your organization has configured. Off-shift GPS is dropped at the server. You can disable background location entirely from the Settings screen, and you can delete your own location history at any time.

Photos are uploaded only when you explicitly attach them to a ticket comment, damage report, or receipt. The camera is used to scan inventory QR codes and capture receipts; images are sent only to your Clientst0r server.

WHAT YOU NEED

• A Clientst0r server (self-hosted) reachable over HTTPS
• An account on that server with API access
• Android 7 (Nougat) or newer

For setup, contact your Clientst0r administrator for your server URL.

BETA STATUS

This is a public beta. Active features get incremental updates; please send feedback via the BETA ribbon at the top of the screen.
```

(Approx 2900 chars; well under 4000.)

---

## What's new (per release, max 500 chars)

For **v3.17.446**:
```
Bug fixes for first internal-testing release:
• Login fix — the field was sending email instead of username on POST, causing "username and password are required" with credentials clearly entered.
• Build unblock — patched expo-modules-core for Android SDK 35 (PackageInfo.requestedPermissions became nullable, broke Kotlin compile).
```

(331 chars.)

---

## Graphic assets you still need to provide

Play Console requires these to publish (Internal Testing is more lenient but Production requires all):

| Asset | Required size | Required for Internal Testing? | Notes |
|---|---|---|---|
| App icon (high-res) | 512×512 PNG, 32-bit | Yes | You have `mobile/assets/icon.png` — check it's at least 512×512 |
| Feature graphic | 1024×500 PNG/JPG | Yes | This is *not* the icon; it's a wide banner shown above the listing. **You don't have one yet.** |
| Phone screenshots | 1080×1920 (or any 16:9 to 9:16) PNG/JPG, ≥2 | Yes | At least 2 phone screenshots required. Take them from a real device or emulator showing the dashboard, ticket list, and login screen |
| Tablet screenshots | Optional | No | Skip unless you tablet-test |
| Promo video (YouTube URL) | Optional | No | |

If you don't have a feature graphic, the simplest path is a 1024×500 image with the project logo on a colored background — Inkscape or Figma can produce one in 5 minutes. Or render one programmatically with PIL + the existing icon.

---

## App category, content rating, target audience

| Field | Suggested answer |
|---|---|
| App category | **Business** (Productivity is also valid) |
| Tags | "IT", "MSP", "service desk", "ticketing", "knowledge base" |
| Content rating | Run the IARC questionnaire — for a B2B IT app it should come back **Everyone** (3+) |
| Target audience age | **Ages 18+** (it's a tool for working professionals; no need to worry about Families Policy) |
| Are ads in your app? | **No** |
| Government app? | **No** |
| COVID-19 contact tracing app? | **No** |
| News app? | **No** |
| Health app? | **No** |
| Financial features? | **No** |

---

## App access (test login for Google's reviewer)

Play Console asks how their reviewer can log in to test the app. Since this is a self-hosted app that requires an account on a server you own, give them a test account:

**Suggested answer (free-text in Play Console):**

*"This app is a thin client to a self-hosted Clientst0r server. To test, set the server URL to `https://huduglue.agit8or.net/api/mobile/v1` on the login screen and use the following credentials:*

*  Username: `play-reviewer`*
*  Password: `[generated, share via Play Console secure note]`*

*This is a read-only reviewer account scoped to a demo organization. The reviewer will be able to see tickets, KB articles, and the asset list, but will not have vault access or write permissions. The account is rate-limited to prevent abuse."*

(Translation: you'll want to actually create that `play-reviewer` user before submitting. It only needs to exist when Play's reviewer checks the app, which is during the first content-review pass.)
