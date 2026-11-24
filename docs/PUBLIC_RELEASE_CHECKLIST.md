# Play Console Public Release — Checklist

Everything you need to flip from **internal testing** to a **production release** on Google Play. As of v3.17.461.

---

## A. Things this repo gives you for free

| Item | Where | Notes |
|---|---|---|
| **Privacy policy URL** | `https://huduglue.agit8or.net/privacy-policy/` | Live after Apply (route shipped v3.17.447). Renders `docs/PRIVACY_POLICY.md`. |
| **Privacy policy source-of-truth** | `docs/PRIVACY_POLICY.md` | Updated v3.17.461 to cover camera + location + photos. |
| **Data safety form prefill** | `docs/PLAY_DATA_SAFETY.md` | Walks through every Play Console question. Updated v3.17.461. |
| **Store listing copy** | `docs/PLAY_STORE_LISTING.md` | App name, short / full description, what's new, app-access reviewer text, content rating answers. |
| **Signed AAB** | `/play_publish/` UI on the canonical server | Button → `clientst0r-v3.17.NNN.aab` |
| **R8 mapping file** | Same UI, uploaded automatically | For crash symbolication in Play Console. |

---

## B. Things you have to provide (Play Console UI, one-time)

These can't ship from the repo. Each is filled in at `play.google.com/console` → your app → relevant section.

### Visual assets

| Asset | Spec | Where you stand |
|---|---|---|
| **App icon (high-res)** | 512×512 PNG, 32-bit | ✅ You have `mobile/assets/icon.png`. Verify it's at least 512×512. |
| **Feature graphic** | 1024×500 PNG/JPG | ❌ Missing. Required to publish. Quick build: solid background + project logo + "Clientst0r Mobile" text in Figma / Inkscape (~5 min). |
| **Phone screenshots** | 1080×1920 (or any 16:9 ratio), ≥2 | ❌ Need fresh ones from a phone running v3.17.461 (the dashboard, vault, ticket detail, dispatch board, and timeclock-on-the-clock are all visually different from earlier builds). |
| **Tablet screenshots** | Optional | Skip unless you want tablet support. |
| **Promo video URL (YouTube)** | Optional | Skip. |

### Forms / questionnaires

1. **App content → Privacy policy URL** → paste `https://huduglue.agit8or.net/privacy-policy/`
2. **App content → App access** → select "All functionality is available with the following credentials," paste the reviewer text from `PLAY_STORE_LISTING.md`. **Create the `play-reviewer` test account on the canonical server first** with read-only access to a demo organization.
3. **App content → Ads** → "No, my app does not contain ads"
4. **App content → Content ratings** → Run the IARC questionnaire. Answers from `PLAY_STORE_LISTING.md` produce **Everyone (3+)** for a B2B IT app.
5. **App content → Target audience** → Ages 18+.
6. **App content → Data safety** → Walk through every question; answers in `docs/PLAY_DATA_SAFETY.md`. **This will take ~20 minutes the first time.** Expect Play to flag location + photos for follow-up justification (template wording is in the doc).
7. **App content → News app** → No
8. **App content → Government app** → No
9. **App content → COVID-19 contact tracing or status** → No
10. **App content → Health connect** → No (we don't integrate)
11. **App content → Financial features** → No

### Store listing copy (paste from `PLAY_STORE_LISTING.md`)

- **App name** (≤ 30 chars): `Clientst0r Mobile`
- **Short description** (≤ 80 chars): line provided in doc
- **Full description** (≤ 4000 chars): markdown body provided in doc
- **App category**: Business
- **Tags**: IT, MSP, ticketing, knowledge base
- **What's new**: per-release; latest in `CHANGELOG.md`

---

## C. Sequence to actually flip the switch

1. **Apply on prod** to land everything from v3.17.453 → 461.
   - `https://huduglue.agit8or.net/settings/updates/` → Check for Updates → Apply.
   - After Apply: `/privacy-policy/` route is live, vault entry 107 reveals, all the new mobile API endpoints respond.
2. **Build signed AAB v3.17.461** in `/play_publish/`. Output: `clientst0r-v3.17.461.aab`. Upload runs as a draft release on the internal track.
3. **Confirm internal testing still works** — install on your test phone via Play Store, run through dashboard / vault / scan / damage photo. Catch surprises here, not in production review.
4. **Capture phone screenshots** (5–8) running v3.17.461. Suggested screens: dashboard, dispatch board, ticket detail with status pills, vault list grouped by org, timeclock on-the-clock card, vehicle detail, inventory low-stock list.
5. **Make the feature graphic** (1024×500). Even a flat-color rectangle with the project name passes review.
6. **Create the `play-reviewer` test account** on the canonical server. Demo organization. Read-only role. Note the credentials (you'll paste them into App access).
7. **Fill out every red-badged section** in Play Console's left nav. App content is the long one.
8. **Promote the v3.17.461 release from Internal → Production** (Play Console → Release → Production → Create new release → Copy from Internal).
9. **Roll out to production**, % rollout slider. Start at 5–10%. Monitor crash rate in Play Console → Quality.

---

## D. What to expect from Play's review

| Issue | Likelihood | Mitigation |
|---|---|---|
| **"Permission misuse — background location"** | **High once you enable background tracking by default.** As of v3.17.464 the app declares `ACCESS_BACKGROUND_LOCATION` so the opt-in toggle works, but it's OFF by default. **Play Console will require a 30-second sample video showing your in-app opt-in flow** and an `Allowed by Google` declaration confirming the feature is core to the app. Submit those before the production release reviews. |
| **"Photo library purpose unclear"** | Medium. The image-picker plugin's purpose string is honest. | Privacy policy v3.17.461 explicitly addresses photo handling. |
| **"Sensitive data — financial info"** | Low. Fuel receipts have totals but those aren't personal financial data. | If flagged, declare them under App activity, not Financial info. |
| **"Functionality concern — backend required"** | Possible. App requires a self-hosted server URL to do anything. | App access section + reviewer test account answers this. The `play-reviewer` account on the canonical server gives them a working demo. |
| **First-review delay** | 1–7 business days for production. Internal testing is usually <1 hour. | Plan around it. |

---

## E. What's still deferred (and what to tell users about it)

Features not yet in the AAB but on the roadmap. Not blockers for public release.

| Feature | Status | Setup needed |
|---|---|---|
| **Receipt OCR** | Endpoint shipped v3.17.465; off by default | Set `OCR_PROVIDER=cloudvision` + `GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json` in the gunicorn env, then `pip install google-cloud-vision`. Mobile fuel form will auto-fill gallons / $/gal / station from receipt photos. |
| **Push notifications** | Shipped v3.17.463 | No additional setup; uses Expo's relay. |
| **Background GPS** | Shipped v3.17.464; **off by default**, opt-in via Settings | Production release requires a 30-second sample video showing the in-app opt-in for Play Console's background-location justification. |

---

## F. After production launch

- **Monitor `Play Console → Quality → Android vitals`** for crash-free user rate. ANRs / crashes get triaged here using the R8 mapping we ship with each AAB.
- **`docs/ROADMAP.md`** is published live at `/core/roadmap/` and via `/core/roadmap.json` (cached). Customers can poll for status. Update it as you ship.
- **Update `What's new`** on each Play Console release with a 200–500 char summary; pull from `CHANGELOG.md`.
