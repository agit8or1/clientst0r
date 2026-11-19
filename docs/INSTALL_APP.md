# Installing ClientSt0r on Your Phone or Desktop

ClientSt0r is a **Progressive Web App (PWA)** — you can add it to your home screen on any phone or computer and it works like a native app. No app store, no APK, no download required.

## Where to Find the Install Page

**Account menu** (your user name in the top-right corner; on a phone, open the menu button first) → **Install app**, which opens **Apps & Downloads → Install App / Add to Home Screen**

Or navigate directly to: `https://YOUR-SERVER/core/install/`

The install page is shareable — it works without logging in, so you can send the link to staff.

---

## Android — Chrome

1. Open `https://YOUR-SERVER` in **Chrome**
2. Tap the **⋮** (three-dot) menu in the top-right corner
3. Tap **Add to Home screen** *(may say "Install app")*
4. Tap **Add** — the ClientSt0r icon appears on your home screen

> **Tip:** Chrome may also show an **Install** banner at the bottom of the screen automatically when you first visit. Tap it for one-tap install.

### PWA Shortcuts (Android)
After installing, **long-press** the ClientSt0r icon on your home screen to see shortcuts:
- **Scan Receipt** — opens the vehicle receipt scanner
- **Vehicles** — opens the fleet management page

---

## iPhone / iPad — Safari

> ⚠️ **Must use Safari** — Chrome on iOS does not support Add to Home Screen for PWAs.

1. Open `https://YOUR-SERVER` in **Safari**
2. Tap the **Share** button (square with an arrow pointing up) at the bottom of the screen
3. Scroll down and tap **Add to Home Screen**
4. Optionally rename it, then tap **Add**
5. The ClientSt0r icon appears on your home screen

---

## Desktop — Chrome or Edge

1. Open `https://YOUR-SERVER` in Chrome or Edge
2. Look for the **install icon** (⊕ or download arrow) in the address bar on the right
3. Click it and select **Install**
4. ClientSt0r opens as a standalone window and is added to your taskbar / Start menu / Applications folder

---

## Vehicle Receipt Shortcut

Each vehicle has a **per-vehicle QR code** that links directly to the Add Receipt page. To set it up:

1. Go to **Assets & Network → Vehicles → [your vehicle]**
2. Click the **Receipts** tab
3. Click **Phone Shortcut**
4. Scan the QR code with your phone — opens Add Receipt for that vehicle
5. Follow the Add to Home Screen steps above to bookmark it as an icon

This lets a technician tap one icon on their phone to photograph and submit a receipt for their specific vehicle.

---

## Troubleshooting

| Issue | Solution |
|---|---|
| Install button doesn't appear on Android | Make sure the server is served over **HTTPS** (PWA install requires a secure connection) |
| "Add to Home Screen" missing in Safari | Must use Safari; Chrome on iOS doesn't support this |
| Icon opens a browser tab, not a standalone app | On iOS this is expected — Safari PWAs open in Safari's app mode which looks full-screen |
| Already installed, want to reinstall | Uninstall the existing icon from your home screen first, then re-add |
