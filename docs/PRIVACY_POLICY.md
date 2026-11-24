# Privacy Policy — Clientst0r Mobile

**Effective:** 2026-05-09
**Last updated:** 2026-05-10

This policy describes how the **Clientst0r Mobile** Android app handles user data. Clientst0r Mobile is a companion app for the Clientst0r IT service-management platform. It is intended for use by IT technicians and staff at organizations that have deployed Clientst0r on their own infrastructure.

## Who is the data controller

Clientst0r is **self-hosted**. Each customer deploys the Clientst0r server on their own infrastructure and is the data controller for everything stored on that server. The Clientst0r Mobile app is a thin client that connects to the server URL its user enters at first launch.

The app developer **does not operate a centralized backend**, does not host any user data, and never receives data entered into the app. All network traffic from the app goes directly to the user-configured server URL and stays within the user's organization.

If you have questions about how data is processed inside your organization's Clientst0r deployment, contact your Clientst0r administrator. Their privacy policy applies to data on the server.

## What the app sends to your server

When you sign in, the app sends your email or username and password over HTTPS to the server URL you configured. The server returns an authentication token. From that point forward, every API request the app makes carries this token in an `Authorization` header.

While in use, the app may transmit the following data **to your configured server only**:
- Login credentials (email/username + password) at sign-in
- Multi-factor authentication codes if your server requires MFA
- Read requests for tickets, organizations, assets, knowledge-base articles, and vault entries that your server's permission model authorizes you to access
- Comments and updates you make on tickets
- Vault password reveal requests, which your server may rate-limit, audit, and require approval for

All transmission uses TLS (HTTPS). The app does not transmit data to any third-party service, advertising network, or analytics provider.

## What the app stores on your device

The app stores the following on-device, encrypted in the Android Keystore via the `expo-secure-store` library:
- Your authentication token
- The server URL you entered
- A small cached copy of your basic profile (user ID, username, email, full name, organization, role) used to populate the UI between launches

The app does **not** store passwords on the device. Vault secrets retrieved through the reveal flow are held in memory only and are not written to disk.

Signing out (or uninstalling the app) clears all on-device storage.

## What the app collects when you opt in

Since v3.17.452, the app may also capture the following data when you take specific actions. Each capture happens only at the moment of that action — not in the background, not continuously.

- **Precise location** (Android `ACCESS_FINE_LOCATION`) — captured at the moment you tap **Clock in** in the Timeclock screen. The single GPS reading is sent to your server with the clock-in event so it can be checked against your organization's geofence configuration.
- **Background location** (Android `ACCESS_BACKGROUND_LOCATION`, iOS "Always" location) — **off by default**. If you turn it on in Settings, your location is sampled every 5 minutes (and only when you've moved at least 50 meters) and sent to your server while you're on shift. Off-shift pings are dropped at the API layer by the server and never stored. You can turn this off at any time in Settings. When background tracking is active, Android shows a persistent foreground notification labeled "Clientst0r is tracking your shift."
- **Camera** (`CAMERA`) — used for damage report photos, fuel receipt photos, and scanning inventory QR codes / asset barcodes. The camera is opened only when you tap a "Take photo" or "Scan" button, and closes when you complete or cancel the action.
- **Photo library** (`READ_MEDIA_IMAGES` on Android 13+) — used for the "From library" option on damage and fuel forms when you'd rather attach an existing photo than take a new one.

Photos you capture or select are uploaded to your configured server as part of the damage report / fuel log they are attached to, and stored alongside that record. They are not uploaded anywhere else and not used by the app for any other purpose.

## What the app does not collect

The app does **not** request or collect:
- Approximate location
- Continuous location tracking when background location is off (the default)
- Microphone audio
- Contacts, calendar, or call/SMS data
- Health, fitness, or financial data
- Advertising IDs
- Information about other apps installed on your device

## Push notifications

If you grant notification permission at first login, the app registers an Expo push token with your server. Your server uses this to notify you when a ticket is assigned to you (and, in the future, for other events your administrator configures). Push payloads contain only the notification text and a deep-link route within the app — they do not contain credential or vault data.

You can revoke notifications at any time by signing out (the server forgets your push token) or by disabling notifications for the app in Android Settings.

## Crash reporting

When you install the app from Google Play, Google may collect anonymized crash logs and performance diagnostics for the app, governed by Google's own policies. These are visible to the app developer through Play Console for debugging purposes only.

## Third parties

The app does not integrate any third-party SDKs that collect user data. Network traffic flows only between the device and the server URL you entered. The libraries used (React Native, Expo, axios, Tanstack Query, expo-secure-store) do not phone home.

## Data retention and deletion

- **On-device data** is retained until you sign out, clear app data through Android Settings, or uninstall the app.
- **Server-side data** is retained according to your organization's Clientst0r configuration. Contact your Clientst0r administrator to request export, correction, or deletion of data your organization holds about you.

## Children

The app is not intended for users under 13. We do not knowingly collect data from children.

## Permissions the app requests

| Android permission | Why |
|---|---|
| `INTERNET` | To reach the server URL you configured |
| `ACCESS_FINE_LOCATION` | A single GPS reading at clock-in for geofence verification. |
| `ACCESS_BACKGROUND_LOCATION` | Requested only if you turn on background-location tracking in Settings (off by default). Used to record on-shift visits to client sites. |
| `POST_NOTIFICATIONS` | Show push notifications you've explicitly enabled (e.g. when a ticket is assigned to you). |
| `CAMERA` | Damage report photos, fuel receipt photos, and inventory QR / barcode scanning. Camera is opened only at the moment you tap a "Take photo" or "Scan" button. |
| `READ_MEDIA_IMAGES` (Android 13+) / `READ_EXTERNAL_STORAGE` (Android 12 and below) | Used by the "From library" option on damage and fuel forms when you'd rather attach an existing photo than take a new one. |
| `FOREGROUND_SERVICE_LOCATION` | When background location is on, Android requires a persistent foreground service so you can see that the app is tracking you. |
| `SYSTEM_ALERT_WINDOW` | Required by some Expo modules; the app does not draw over other apps |
| `VIBRATE` | Haptic feedback on UI interactions |

## Changes to this policy

If we materially change how the app handles data, we will update this page and bump the "Last updated" date. The version of the policy that applies to your install is the one published at the time you obtained the app.

## Contact

For privacy questions about the **app itself** (not your organization's server data), open an issue at <https://github.com/agit8or1/clientst0r/issues>.

For privacy questions about **data your organization holds in its Clientst0r server**, contact that organization directly.
