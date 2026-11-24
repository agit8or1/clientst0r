# Clientst0r Mobile — Public Beta

Welcome. This is the public beta of the Clientst0r Mobile companion app for Android. You are here because someone pointed you at the opt-in URL — thanks for testing.

> **Heads up:** This is a beta. You will hit rough edges. Please report them — that's the entire point of being here.

---

## 1. Join the beta

1. Tap the opt-in link:
   <p>
     <a class="cta" href="https://play.google.com/apps/testing/com.clientstor.mspreboot">
       Join the Clientst0r beta on Google Play →
     </a>
   </p>
2. Sign in with the same Google account you use on your phone.
3. Tap **Become a tester**, then **Download it on Google Play**.
4. Install. The app appears on your home screen as **Clientst0r Mobile**.

The Play Store listing shows a small *(Unreleased)* badge next to the app name while you're a beta tester.

---

## 2. Set up your account

You need a working Clientst0r account on the server you'll be connecting to. **This app is not a standalone product** — it talks to a Clientst0r server your organization (or your provider) operates.

1. Get your server's public URL from your administrator. It looks like `https://yourcompany.clientstor.app` (or whatever your provider configured).
2. Get your username + password — same credentials you use for the web app.
3. If your account has 2FA enabled, have your authenticator handy. The app supports TOTP.

On first launch:
- Tap **Login**
- Enter your server URL when prompted
- Enter your username + password
- If 2FA is on, the app asks for a 6-digit code — enter it

That's it. You land on the dashboard.

---

## 3. What works in this beta

Working today:
- **PSA Tickets** — file, view, comment, assign, log time, schedule
- **Vault** — read, edit, rotate, create entries
- **Assets** — view, edit, link vault secrets to assets
- **Calendar** — see scheduled tasks and ticket due dates by day; schedule new items on any day
- **Dispatch** — your assigned tasks, ack + sign off
- **Timeclock** — clock in/out, optional GPS geofencing
- **Vehicles + Receipts** — fuel log, damage reports, receipt OCR
- **Inventory** — QR scan, counts, transactions
- **Knowledge base** — search and read articles
- **Workflows** — start a workflow, step through stages

Known limitations:
- **Background location** is opt-in only and defaults to OFF — toggle it in Settings if your dispatcher needs auto-on-site time tracking.
- **Offline mode** is partial. Most reads work briefly after losing network; writes (new ticket, time entry, etc.) require a live connection.
- **Push notifications** require your administrator to enable the Firebase config on the server side. If you don't get a push when a ticket is assigned to you, that's why.
- **iOS** is not yet shipped. Android only for now.

---

## 4. How to send feedback

The fastest way: tap the orange **BETA** ribbon at the top of any screen. It opens a pre-filled ticket against your primary org with subject "Mobile beta feedback". Fill in the description with what happened, hit Create.

Alternative channels:
- Email: `beta@<your-domain>` (replace with your operator's address)
- Phone screenshot + send via the app

Please include:
- What you were trying to do
- What actually happened
- Your app version (shown in the BETA ribbon and on the Settings screen)
- A screenshot if visual

If the app **crashed**, Sentry sees the stack trace automatically (no PII attached). You don't need to do anything — but a one-liner telling us "I tapped X and the app vanished" makes it much faster to find your crash in the dashboard.

---

## 5. Privacy

The app talks **only** to your Clientst0r server. It does not include analytics or ad SDKs. The one exception is optional crash reporting via Sentry — stack traces only, no user data.

Full details: see the [Privacy Policy](/privacy-policy/).

---

## 6. Leaving the beta

To go back to the public (non-beta) version:
1. Visit the [Play Store opt-in page](https://play.google.com/apps/testing/com.clientstor.mspreboot)
2. Tap **Leave the program**
3. Uninstall and reinstall the app from Google Play

Beta is rolling — when we promote a build to general release, your beta install just becomes the production install automatically. You don't have to do anything.

---

## 7. Need help that isn't a bug?

Ask your administrator — they hold the keys to your Clientst0r server, user accounts, and 2FA. We can't reset your password from this side; the server is yours.

Thanks for testing. Every bug report you file makes the next build better.
