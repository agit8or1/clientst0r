# Play Console — Data Safety Form Answers

This is a fill-in guide for Play Console's **App content → Data safety** questionnaire. Answers reflect the current AAB (`v3.17.481` / `versionCode 3170481`) — the first **public beta** build:

- **Precise location** — captured at user-initiated clock-in for geofence verification (added v3.17.452)
- **Background location** — opt-in only; default OFF (Settings → "Background location"). Enables auto-on-site time tracking via geofence visits (added v3.17.464).
- **Camera + Photos** — capture damage report photos, fuel receipt photos, scan inventory QR codes (added v3.17.460 + v3.17.461)
- **Authentication credentials, app activity, device IDs** — same as v1
- **Crash logs + diagnostics** — sent to Sentry if `EXPO_PUBLIC_SENTRY_DSN` is set at build time (added v3.17.481). Stack traces + device model only; no PII.

Update this doc and re-fill the Play Console form whenever the app starts collecting a new data type or stops collecting one.

The questionnaire is six sections in Play Console; this doc mirrors them.

---

## Section 1 — Data collection and security

> Does your app collect or share any of the required user data types?
**Answer: Yes.**

> Is all of the user data collected by your app encrypted in transit?
**Answer: Yes.** All API traffic uses TLS (HTTPS) to the user-configured server. Multipart uploads (photos) use the same channel.

> Do you provide a way for users to request that their data is deleted?
**Answer: Yes — through their Clientst0r administrator.**

In the free-text "How users can request data deletion": *"Clientst0r is self-hosted; contact your organization's Clientst0r administrator to request export or deletion of data on the server. On-device app data is cleared by signing out, clearing app data in Android Settings, or uninstalling the app."*

---

## Section 2 — Data types collected

For each row below, mark **Collected** if listed, **Not collected** otherwise. Anything marked "Collected" requires the follow-up answers in Section 3.

### Personal info
| Type | Status | Notes |
|---|---|---|
| Name | **Collected** | Full name returned by `/auth/me/`, cached locally |
| Email address | **Collected** | Used for login (sent to server), cached locally |
| User IDs | **Collected** | Auth token + user ID returned by server, cached locally |
| Address | Not collected | |
| Phone number | Not collected | |
| Race and ethnicity | Not collected | |
| Political or religious beliefs | Not collected | |
| Sexual orientation | Not collected | |
| Other personal info | Not collected | |

### Financial info
All **Not collected.** Fuel receipt totals are stored as numbers but are not personal financial data — they're per-vehicle business expenses.

### Health and fitness
All **Not collected**.

### Messages
| Type | Status | Notes |
|---|---|---|
| Emails | Not collected | |
| SMS or MMS | Not collected | |
| Other in-app messages | **Collected** | Ticket comments + scheduled-task comments the user types are sent to the server |

### Photos and videos
| Type | Status | Notes |
|---|---|---|
| Photos | **Collected** | v3.17.460 — damage report photos and fuel receipt photos. Camera and library access requested at use time. |
| Videos | Not collected | |

### Audio files
All **Not collected**.

### Files and docs
| Type | Status |
|---|---|
| Files and docs | Not collected |

(KB articles and ticket attachments are *displayed* but not collected as user data — they are content the server already has.)

### Calendar
**Not collected.**

### Contacts
**Not collected.**

### App activity
| Type | Status | Notes |
|---|---|---|
| App interactions | **Collected** | Audit log records actions like ticket views, vault reveals, dispatch sign-offs, stock adjustments |
| In-app search history | **Collected** | KB / ticket / inventory / asset / vault search queries |
| Installed apps | Not collected | |
| Other user-generated content | **Collected** | Ticket comments, time entries, fuel logs, damage reports, inventory transactions, workflow stage notes, dispatch task comments |
| Other actions | Not collected | |

### Web browsing
**Not collected.**

### App info and performance
| Type | Status | Notes |
|---|---|---|
| Crash logs | **Collected** | (a) Google Play collects from signed AABs; we ship R8 mapping for symbolication. (b) v3.17.481 added optional Sentry SDK — sends stack traces + device model + OS version. DSN is build-time only; if `EXPO_PUBLIC_SENTRY_DSN` is unset, no third-party crash reporting happens. |
| Diagnostics | **Collected** | Same — collected by Play Console and (if Sentry enabled) Sentry. |
| Other app performance data | Not collected | |

### Device or other IDs
| Type | Status | Notes |
|---|---|---|
| Device or other IDs | **Collected** | Audit log records request IP address (treated as a device identifier under Play's broad definition) |

### Location (v3.17.452+)
| Type | Status | Notes |
|---|---|---|
| Approximate location | Not collected | |
| Precise location | **Collected** | At user-initiated clock-in always. ALSO collected every 5 minutes in the background IF the user opts in via Settings → Background location (default OFF). Off-shift pings are dropped at the API layer. |

### Authentication info
- Passwords: **transmitted to user-configured server**, **not stored on device**

---

## Section 3 — For each "Collected" data type

Play Console asks the same four questions per type. Defaults that apply to **every** collected type unless noted:

| Question | Answer |
|---|---|
| Is this data collected, shared, or both? | **Collected** (the app does not share with third parties; data goes only to the server URL the user enters, which is the user's own infrastructure) |
| Is this data processed ephemerally? | **No** (stored on the user's server) |
| Is this data required or optional for the user? | **Required** (without auth the app does nothing) — except where noted below |
| Why is this data collected? | **App functionality** + **Account management** for personal info / IDs / messages / app activity / photos / location. **Analytics** also OK for crash logs / diagnostics. **Do not** check Advertising, Personalization, or Developer communications — none apply. |

### Specifically for Crash logs and Diagnostics
- Required or optional: **Optional** (Play allows users to opt out in Android Settings)
- Why collected: **App functionality** + **Analytics**

### Specifically for Device or other IDs (IP address)
- Why collected: **App functionality** + **Fraud prevention, security, and compliance** (audit log)

### Specifically for Photos (v3.17.460)
- Required or optional: **Optional** — damage reports and fuel logs can be filed without a photo. Photo upload is user-initiated per record.
- Why collected: **App functionality** (evidence + reimbursement records).
- Mention in free-text: *"Photos are captured by the user and uploaded to their organization's server only when filing a damage report or fuel receipt. The app does not access the photo library or camera otherwise."*

### Specifically for Precise location (v3.17.452 + v3.17.464)
- Required or optional: **Optional** — clock-in works without GPS; the absence just disables geofence verification. Background tracking is opt-in and off by default.
- Why collected: **App functionality** (geofence verification of timeclock entries, on-shift visit logging) + **Fraud prevention, security, and compliance** (preventing falsified clock-ins).
- Mention in free-text: *"At clock-in time, the app captures a single GPS reading to verify the user is inside a client geofence. If the user explicitly enables 'Background location' in Settings (default OFF), the app also samples location every 5 minutes during their working hours via a foreground service with a persistent notification. Off-shift pings are dropped at the API layer and never stored. The user can turn background tracking off at any time."*

---

## Section 4 — Security practices

| Question | Answer |
|---|---|
| Is all data encrypted in transit? | **Yes** (TLS/HTTPS to the user-configured server, including multipart photo uploads) |
| Do you provide a way for users to request data deletion? | **Yes** (deletion request flow described in Section 1 above) |
| Have you committed to following Google Play's Families Policy? | **No** (the app is not directed at children) |
| Has your app been independently validated against a global security standard? | **No** (leave unchecked unless you have a SOC 2 / ISO 27001 attestation specifically for this app) |

---

## Section 5 — Data sharing

> Does your app share any of the required user data with third parties?
**Answer: No.**

The app sends data only to (1) the server URL the user enters at login (operated by the user's organization, not a third party) and (2) optionally, Sentry.io for crash reporting if `EXPO_PUBLIC_SENTRY_DSN` was baked into the build. No advertising, no analytics, no other third-party SDKs.

**Declare Sentry as data sharing** if you ship a build with the DSN set: data type = "Crash logs" + "Diagnostics", purpose = "Analytics" (technical debugging), processing = "Not processed ephemerally" (Sentry retains for the retention period configured in your Sentry project, default 30 days).

Google Play's automatic crash + diagnostics is governed by Google's own policies; Play Console does not require it to be disclosed as data sharing.

---

## Section 6 — Data deletion

> How can users request that you delete their data?

**Answer (free-text):**
*"Clientst0r is a self-hosted application. The mobile app does not store user data on any infrastructure operated by the developer — all data is held by the user's organization on the Clientst0r server they have deployed. To request deletion of data the organization holds, the user contacts their Clientst0r administrator. To clear app data on the device, the user signs out of the app, clears app data through Android Settings, or uninstalls the app."*

---

## What to paste into "Privacy policy URL"

```
https://huduglue.agit8or.net/privacy-policy/
```

The route was shipped in v3.17.447. Verify it loads anonymously before submitting.

---

## When you have to revisit this

Update this doc and re-fill the Play Console questionnaire whenever:

- You ship a build that adds **background location** (currently foreground-only at clock-in time)
- You ship a build that adds **push notifications** (planned — will need to declare device IDs disclosure differently)
- You add a third-party SDK (analytics, error tracking like Sentry, ad networks)
- You ship a build that adds receipt OCR sent to a third-party service (Cloud Vision / Textract)
- The app starts collecting any of the "Not collected" data types above
