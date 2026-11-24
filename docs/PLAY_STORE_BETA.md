# Clientst0r Mobile — Play Store Beta Release Guide

> **Single source of truth** for building the AAB and shipping it to Google Play Open Testing.
> If something in this guide is wrong, fix this file rather than working around it.

Companion docs (all in `docs/`):
- `PLAY_STORE_LISTING.md` — paste-ready copy for the store listing
- `PLAY_DATA_SAFETY.md` — paste-ready answers for the Data Safety questionnaire
- `BETA_ONBOARDING.md` — rendered at `/beta-onboarding/` for testers
- `PRIVACY_POLICY.md` — rendered at `/privacy-policy/` (required for the Play listing)

---

## Phase 0 — Pre-flight (do once)

### 0.1 Confirm the backend is publicly reachable

From a phone on cellular (NOT your LAN wifi), open:
```
https://<your-public-domain>/api/mobile/v1/version/
```
Expect a JSON response. Common breakage: self-signed cert, port not open, internal-only DNS.

### 0.2 Confirm the mobile app points at the public URL

The mobile source lives at `/home/administrator/mobile/` (and the dev worktree copy at `/home/administrator/.dev-worktree/mobile/`). Both are off-GitHub since 2026-05-14 — code lives on disk only.

```
mobile/.env
```
should contain:
```
EXPO_PUBLIC_API_BASE=https://<your-public-domain>/api/mobile/v1
EXPO_PUBLIC_BUILD_CHANNEL=beta
# Optional crash reporting (free Sentry tier, sentry.io):
EXPO_PUBLIC_SENTRY_DSN=https://abcdef@o0.ingest.sentry.io/0
```

Any change here must be followed by a rebuild — the values are baked into the AAB at build time.

### 0.3 Create the demo reviewer account

In the web UI, create a user like `play-reviewer@<your-domain>` with:
- Memorable password
- ONE organization membership with a Technician role (real-looking data: a few tickets, assets, vault entries)
- **2FA disabled** for that account

Google's reviewers will use this. Most first-time rejections are "we couldn't log in."

### 0.4 Privacy Policy is reachable

In a fresh browser (incognito), hit `https://<your-public-domain>/privacy-policy/`. Must work without login.

### 0.5 Beta onboarding page is reachable

Same test: `https://<your-public-domain>/beta-onboarding/`. Must work without login.

---

## Phase 1 — Build the release AAB locally

The build pipeline is documented from v3.17.445 (targetSdk 35) + v3.17.446 (`patches/expo-modules-core+*.patch`) + v3.17.481 (permission allowlist + Sentry hook).

### 1.1 One-time environment

If this is a fresh build host:
```bash
# JDK 17 (required by Expo SDK 51+ / AGP 8.x)
sudo apt install openjdk-17-jdk
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64

# Android SDK (command-line tools)
mkdir -p ~/Android/Sdk/cmdline-tools
# ... unzip commandlinetools-linux-*.zip into ~/Android/Sdk/cmdline-tools/latest/
export ANDROID_HOME=~/Android/Sdk
export ANDROID_SDK_ROOT=~/Android/Sdk

sdkmanager "platforms;android-35" "build-tools;35.0.0" "platform-tools"
yes | sdkmanager --licenses
```

Persist `JAVA_HOME` and `ANDROID_HOME` in your `~/.bashrc`.

### 1.2 Install dependencies

```bash
cd /home/administrator/mobile
npm ci
```

`npm ci` (not `npm install`) — uses the locked `package-lock.json` so version drift can't break the build silently. The `postinstall` hook applies `patches/expo-modules-core+*.patch` automatically (fixes the SDK 35 Kotlin null-safety break on `PackageInfo.requestedPermissions`).

If you want Sentry crash reporting:
```bash
npm install @sentry/react-native
```
(Without it, `_layout.tsx` initializes a no-op transport — fine for builds without the DSN.)

### 1.3 Bump the version

Edit `mobile/app.json`:
- `expo.version`: matches the server's `config/version.py` (e.g. `"3.17.481"`)
- `expo.android.versionCode`: monotonic integer following the pattern `3170481` (= `3.17.481`). **Must strictly increase** vs the last AAB uploaded to Play.

### 1.4 Generate the native android/ tree

```bash
npx expo prebuild --platform android --clean
```

`--clean` wipes `mobile/android/` and regenerates it from `app.json` + plugins. This is the step that picks up new permissions, new Expo plugins, version bumps, and the icon/splash.

Expected warnings (safe to ignore unless they reference a plugin):
- `userInterfaceStyle: Install expo-system-ui` — only matters if you start theming
- Anything about Expo Updates is fine; we have it disabled (see `expo.modules.updates.ENABLED=false` in the manifest)

### 1.5 Verify the regenerated AndroidManifest

```bash
grep "uses-permission" mobile/android/app/src/main/AndroidManifest.xml
```

Expected permissions (post-v3.17.481 audit):
- `INTERNET`, `ACCESS_NETWORK_STATE`
- `VIBRATE`
- `CAMERA`
- `ACCESS_COARSE_LOCATION`, `ACCESS_FINE_LOCATION`, `ACCESS_BACKGROUND_LOCATION`
- `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_LOCATION`
- `POST_NOTIFICATIONS`, `READ_MEDIA_IMAGES`

**Must NOT contain:**
- `RECORD_AUDIO` (we don't capture audio)
- `SYSTEM_ALERT_WINDOW` (triggers heavy Play review)
- `READ_EXTERNAL_STORAGE` / `WRITE_EXTERNAL_STORAGE` (legacy; scoped storage replaces them)

If any of the "must not" set appears, edit `app.json` → `android.blockedPermissions` to suppress, then re-run prebuild.

### 1.6 Configure signing

Keystore lives in `/home/administrator/.keystores/clientstor-upload.jks` (not in the repo; never commit). On first build:
```bash
keytool -genkeypair -v \
  -keystore /home/administrator/.keystores/clientstor-upload.jks \
  -alias clientstor-upload \
  -keyalg RSA -keysize 2048 \
  -validity 10000
```
Save the password to your password manager. **You upload this key to Play App Signing on first upload** — Google then re-signs with a Google-managed release key.

Edit `mobile/android/app/build.gradle` (regenerated each prebuild — apply the patch in `mobile/patches/` if there is one) to point at the keystore:
```gradle
android {
    signingConfigs {
        release {
            storeFile file('/home/administrator/.keystores/clientstor-upload.jks')
            storePassword System.getenv('KEYSTORE_PASSWORD')
            keyAlias 'clientstor-upload'
            keyPassword System.getenv('KEYSTORE_PASSWORD')
        }
    }
    buildTypes {
        release { signingConfig signingConfigs.release }
    }
}
```

Or use a `~/.gradle/gradle.properties` file with the credentials (less brittle, never goes into the repo).

### 1.7 Build the AAB

```bash
cd mobile/android
export KEYSTORE_PASSWORD='<your-password>'
./gradlew bundleRelease
```

Output: `mobile/android/app/build/outputs/bundle/release/app-release.aab` (typical size 40–60 MB).

First build takes 5–15 minutes (downloads dependencies). Subsequent builds are 1–3 minutes.

#### Known failure: `SDK location not found`
Gradle can't find the Android SDK. Either:
- `export ANDROID_HOME=$HOME/Android/Sdk` (and `ANDROID_SDK_ROOT` to the same path) in the shell that invokes `./gradlew`, OR
- Create `mobile/android/local.properties` with one line: `sdk.dir=/home/administrator/android-sdk`.

The `local.properties` approach is more robust because Gradle daemons inherit it once and don't depend on the parent shell environment.

#### Known failure: `Could not get unknown property 'release'`
This appears with `expo-modules-core@1.12.26` + AGP 8.x on a clean prebuild. The plugin's `from components.release` resolves before the Android library variant is published. The existing `patches/expo-modules-core+1.12.26.patch` fixes the Kotlin null-safety issue but not this Gradle publishing one.

Workaround until a second patch lands:

1. After `npx expo prebuild --platform android --clean` and BEFORE `./gradlew bundleRelease`, edit
   `mobile/node_modules/expo-modules-core/android/ExpoModulesCorePlugin.gradle`
   and wrap the `project.afterEvaluate { publishing { … } }` block in a `try`:

   ```groovy
   try {
     project.afterEvaluate {
       publishing { publications { release(MavenPublication) { from components.release } } }
       repositories { maven { url = mavenLocal().url } }
     }
   } catch (Throwable ignored) { /* AGP 8 publishing — only needed for module publishing, not app builds */ }
   ```

2. Re-run `npx patch-package expo-modules-core` to generate `patches/expo-modules-core+1.12.26.patch.new` (then merge into the existing patch and commit *locally* — patches live in the gitignored `mobile/` tree).

The block being wrapped is for publishing the Expo modules as a Maven artifact, which AAB builds don't need. Skipping it is safe.

**Note on try/catch limitation:** wrapping `project.afterEvaluate { ... }` in a `try` only catches errors that throw at *registration* time, not when Gradle executes the closure later. The `from components.release` is a closure-time error, so the try doesn't help. The cleaner fix is to delete the publishing block entirely from the plugin file, or guard the inner block with `if (project.components.findByName('release') != null)`.

#### Build status as of 2026-05-14
`./gradlew bundleRelease` produced a **37 MB signed AAB** at v3.17.481 / versionCode 3170481. The patched `expo-modules-core+1.12.26.patch` resolved the `components.release` issue (guard inside the `afterEvaluate` closure rather than a try-around). Cold-build time: ~10 minutes.

**Final permission set in the AAB** (verified via `aapt2 dump`):
- INTERNET, ACCESS_NETWORK_STATE
- VIBRATE, WAKE_LOCK
- CAMERA
- ACCESS_FINE_LOCATION, ACCESS_COARSE_LOCATION, ACCESS_BACKGROUND_LOCATION
- FOREGROUND_SERVICE, FOREGROUND_SERVICE_LOCATION
- POST_NOTIFICATIONS, RECEIVE_BOOT_COMPLETED, BIND_JOB_SERVICE, READ_APP_BADGE
- READ_MEDIA_IMAGES, READ_MEDIA_VIDEO
- USE_BIOMETRIC, USE_FINGERPRINT (added by expo-secure-store)
- DETECT_SCREEN_CAPTURE (added by expo-screen-capture for vault security)

**Successfully stripped** (allowlist worked): RECORD_AUDIO, SYSTEM_ALERT_WINDOW, READ_EXTERNAL_STORAGE, WRITE_EXTERNAL_STORAGE.

### 1.8 Verify the AAB locally

```bash
ls -lh mobile/android/app/build/outputs/bundle/release/app-release.aab

# Inspect the AAB's manifest
$ANDROID_HOME/build-tools/35.0.0/bundletool dump manifest \
  --bundle=mobile/android/app/build/outputs/bundle/release/app-release.aab \
  | head -40
# Or if bundletool isn't installed: unzip + inspect base/manifest/AndroidManifest.xml
```

Confirm:
- `versionCode` matches `app.json`
- Permission list matches Section 1.5
- Package name is `com.clientstor.mspreboot`

---

## Phase 2 — Google Play Console account ($25, 1–3 day wait first time)

### 2.1 Sign up
1. Go to **play.google.com/console**
2. **Create developer account** → pick **personal** or **organization**
3. Pay $25 USD (lifetime fee)
4. Verify identity (government ID for personal, DUNS + legal-entity docs for org — orgs wait 2–4 weeks)

### 2.2 Enable hardware 2FA on the Google account
Play Console is a phishing target. A hardware key (YubiKey, etc.) is strongly recommended over SMS.

---

## Phase 3 — Create the app in Play Console (~10 min)

1. **All apps → Create app**
2. App name: pick from `PLAY_STORE_LISTING.md` (under 30 chars)
3. Default language: English (United States)
4. App or game: **App**
5. Free or paid: **Free**
6. Tick all the policy/export-compliance boxes (you read them, right?)
7. **Create app**

> **Permanent decision:** the application ID (`com.clientstor.mspreboot`) is set on first upload. You cannot change it later without rebuilding under a new ID and asking users to re-install. Make sure `app.json` → `expo.android.package` is what you want.

---

## Phase 4 — Fill the dashboard checklist (a few hours)

Play Console gives you a dashboard with ~10 checklist items. The order below minimizes review back-and-forth.

### 4.1 App access
**Setup → App access → Manage**
- "Login credentials required" — yes
- Add the demo reviewer account from Phase 0.3
- Instructions: *"Tap Login on first launch. Enter the server URL `https://<your-public-domain>` if asked. Username: `play-reviewer@<your-domain>`. Password: see Play Console form. 2FA: disabled for this account."*

### 4.2 Ads
**Setup → Ads** → "No, my app does not contain ads"

### 4.3 Content rating
**Setup → Content rating → Start questionnaire**
- Email: yours
- Category: Productivity / Reference / Communication
- Answer "No" to almost everything for a business productivity app
- Result: **Everyone** rating (probably)

### 4.4 Target audience
**Setup → Target audience and content**
- Target age groups: **18 and over only**
- Appeals to children: **No**

### 4.5 News app declaration
**Setup → News app** → "No"

### 4.6 COVID-19 contact tracing
**Setup → COVID-19 contact tracing** → "No"

### 4.7 Data safety ← biggest task
**App content → Data safety → Manage** → paste from `docs/PLAY_DATA_SAFETY.md` section by section.

Key honesty checks (Google cross-references the AndroidManifest):
- We declare `ACCESS_FINE_LOCATION` → must declare Precise location collected
- We declare `CAMERA` → must declare Photos collected
- We declare `POST_NOTIFICATIONS` → must declare Device IDs (push token) collected
- If `EXPO_PUBLIC_SENTRY_DSN` was set at build time → declare Crash logs as shared to a third party (Sentry)

### 4.8 Government apps
**Setup → Government apps** → "No"

### 4.9 Financial features
**Setup → Financial features** — only check boxes that obviously apply (invoice / billing surfaces). For a beta with no live billing on mobile, leave all unchecked.

### 4.10 Health features
**Setup → Health features** → "No"

---

## Phase 5 — Store listing (~30 min)

**Grow → Store presence → Main store listing**

Paste content from `docs/PLAY_STORE_LISTING.md`:
- App name (≤ 30)
- Short description (≤ 80)
- Full description (≤ 4000)
- App icon — upload `mobile/assets/icon.png` resized to 512×512 if it isn't already
- Feature graphic — `docs/screenshots/feature-graphic-1024x500.png` (or wherever the v3.17.475 asset lives)
- Phone screenshots — `docs/screenshots/phone/*.png` (you have these from v3.17.475)
- Tablet screenshots — `docs/screenshots/7-tablet/` and `10-tablet/` (also from v3.17.475)
- Promo video URL — leave blank for beta

Save → Send for review on this surface; it doesn't go live until the AAB is in a public track.

**Store settings:**
- Category: **Business** (or Productivity)
- Tags: 3–5 from the list
- Contact details: support email (required), website URL, no phone for beta
- Privacy Policy URL: `https://<your-public-domain>/privacy-policy/`

---

## Phase 6 — Upload to Internal Testing (~20 min + first-time review wait)

> **Always Internal first, NOT straight to Open.** Internal has no review delay; you sanity-check on a real device before showing reviewers your app.

### 6.1 Create the Internal track
**Testing → Internal testing → Create new release**

### 6.2 First time only — Play App Signing
Console asks "Use Play App Signing?" → **Yes**. Upload your AAB; Google takes the signing key off your hands and re-signs with a Google-managed release key. You keep an *upload key* (the one you generated in 1.6).

### 6.3 Upload AAB
Drag-and-drop `app-release.aab`.

Fill in **release notes** per language (English first):
```
First public beta build.

Highlights since the last internal build:
• New asset edit + vault link/unlink flows
• Ticket detail shows total/billable hours and contract block status
• Calendar shows scheduled tasks AND ticket due dates per day
• Beta ribbon at the top of every screen — tap to send feedback

Known issues:
• Push notifications require server-side Firebase config
• Offline mode is partial (reads only)
• iOS build not yet available
```

### 6.4 Add yourself as a tester
**Testers → Email list → Create email list**. Add your Google account.

### 6.5 Roll out
**Review release → Start rollout to Internal testing**.

Within 5 minutes, the opt-in URL appears under **Testers → How testers join your test**. Open it on your phone (signed into the tester Google account), tap **Become a tester**, install via Play Store.

### 6.6 Smoke-test on real hardware
- Cold launch — should reach Dashboard within 3 seconds
- Log in with a real account
- Tap through every nav tile
- File a feedback ticket via the BETA banner — confirm it lands in the server
- Trigger one network error (airplane mode) — confirm graceful degradation
- Background-foreground the app — confirm state restoration

### 6.7 Read the pre-launch report
About 1–2 hours after upload, Console emails you a pre-launch report. It runs your app on 3–4 real devices and lists crashes / security warnings / accessibility issues. Fix anything red before promoting.

---

## Phase 7 — Closed Testing → reviewer first contact (1–7 days)

### 7.1 Create Closed track
**Testing → Closed testing → Create track** → name it "Beta — Wave 1".

### 7.2 Promote the AAB
On the Closed track page, click **Promote release → from Internal**. No re-upload needed.

### 7.3 Add the demo reviewer + a few colleagues
**Testers** tab → paste email list. Reviewer first, then 3–5 trusted colleagues.

### 7.4 Submit for review
**Review release → Start rollout to Closed testing.**

This is the first review. Google's reviewers (sometimes automated, sometimes human) check:
- App opens without crashing
- Reviewer credentials work
- Privacy policy URL works
- Sensitive permission declarations match Data Safety
- App doesn't violate the developer policy

Timeline: 1–3 days typical, up to 7 days possible.

**Common rejections + fixes:**
- "Login failed" → check reviewer creds, disable 2FA on the demo account
- "Permission declared but not justified" → fix Data Safety
- "Privacy Policy URL broken" → confirm `/privacy-policy/` is public
- "Background location not justified" → in the Console, fill the BG location justification ("Auto-detect on-site time at client geofences for billable-time accuracy")

---

## Phase 8 — Open Testing = PUBLIC BETA (~10 min once Closed is approved)

### 8.1 Create the Open track
**Testing → Open testing → Create track**.

### 8.2 Promote from Closed
Same UI as before — **Promote release → from Closed**.

### 8.3 Set the rollout percentage
Start at **20%** (Play will throttle the rollout for safety). Bump to 100% once you confirm the first wave isn't crash-looping.

### 8.4 Submit
**Review release → Start rollout to Open testing.**

Open Testing usually goes live within hours since it's a track *promotion*, not a fresh review.

### 8.5 Grab the public opt-in URL
**Testers → How testers join your test → Copy link**. It looks like:
```
https://play.google.com/apps/testing/com.clientstor.mspreboot
```

Update `docs/BETA_ONBOARDING.md` if your package ID differs, and confirm `https://<your-public-domain>/beta-onboarding/` shows the correct URL.

### 8.6 Announce
- Your marketing site → add a "Join the beta" CTA pointing at `/beta-onboarding/`
- Social / community channels
- Customer emails — include the URL with one-line install instructions

---

## Phase 9 — Ongoing release cadence

For every subsequent build (e.g. v3.17.482):

1. Update server (`config/version.py`, `CHANGELOG.md`, `docs/ROADMAP.md`) per the existing release pattern
2. Bump `mobile/app.json` → `expo.version` and `expo.android.versionCode` (e.g. `3170482`)
3. `npx expo prebuild --platform android --clean`
4. `cd mobile/android && ./gradlew bundleRelease`
5. Upload to **Internal testing** → smoke-test
6. **Promote → Open testing** (no new review unless permissions/declarations change)

Cadence rule of thumb for active beta: **weekly or biweekly**, not daily. Faster than that and testers can't keep up.

---

## Phase 10 — Monitoring once live

**Quality → Android vitals**:
- **ANR rate** — keep under 0.47% (over this → Play deprioritizes you in search)
- **Crash rate** — keep under 1.09%
- **Stability** — Play surfaces top crashes; fix the ones with > 50 affected devices first

If you enabled Sentry:
- sentry.io dashboard shows crashes with stack traces, device model, OS version
- Set up Slack/email alerts on new crash signatures

---

## Recovery — common ops

### Roll back a broken build
**Testing → Open testing → Production releases history → Halt rollout**. Promote the previous AAB instead. The fix is to ship a higher versionCode, not to undo — Play doesn't truly "downgrade".

### Withdraw the beta entirely
**Testing → Open testing → Manage** → "Stop testing". Users keep their installed copy but the Play Store listing hides the beta opt-in. Re-open when ready.

### Forgot the keystore password
**You can't recover.** You CAN re-enroll a new upload key by contacting Play Support — they'll let you rotate the upload key without losing the Play App Signing release key. Takes ~1 business day.

### Tester reports "the app won't open"
1. Check Sentry / Android vitals for crash stack
2. Check the public API URL is reachable from cellular
3. Check the AAB version they have vs the latest — they may not have updated

---

## Appendix — Files referenced by this guide

| File | Purpose | Public? |
|---|---|---|
| `docs/PLAY_STORE_BETA.md` | This file | No |
| `docs/PLAY_STORE_LISTING.md` | Listing copy paste source | No |
| `docs/PLAY_DATA_SAFETY.md` | Data Safety form answers | No |
| `docs/BETA_ONBOARDING.md` | Rendered at `/beta-onboarding/` | Yes (rendered) |
| `docs/PRIVACY_POLICY.md` | Rendered at `/privacy-policy/` | Yes (rendered) |
| `mobile/app.json` | Expo config, permission allowlist, versionCode | No (gitignored since 2026-05-14) |
| `mobile/app/_layout.tsx` | Sentry init + Beta banner mount | No (gitignored) |
| `mobile/src/components/BetaBanner.tsx` | The orange ribbon | No (gitignored) |
| `mobile/patches/` | Expo SDK 35 build fixes | No (gitignored) |
