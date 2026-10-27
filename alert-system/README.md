# Edith Alert

Press a button on a website (works on iPhone or any browser) and chosen Android phones play a
loud siren, even on silent, until someone taps **Dismiss**. Similar to an Amber Alert, but for your own group.

```
Sender's browser ──► Cloudflare Worker ──► Firebase Cloud Messaging ──► Edith Alert APK
 (behind Cloudflare     (free; signs the        (free; only the push       (alarm stream at max
  Access login)          pairing codes)          part, no database)         volume, full-screen)
```

**No database.** Each phone's code is `HMAC(CODE_SECRET, name)`. Only your Worker can create a valid
code, and the phone listens on a push topic derived from it. You type the code into the phone once and
it remembers it. The same name always gives the same code.

## What it does on the phone
- Plays a generated siren on the **alarm** stream. The silent/vibrate switch doesn't mute that stream, and the app turns its volume up to maximum.
- With "Do Not Disturb access" it switches DND to *alarms only* while ringing, then restores your setting.
- Shows a full-screen red alarm screen, even over the lock screen, and vibrates.
- Rings until someone taps Dismiss, the sender presses "Stop alarm", or 10 minutes pass. Then volume and DND go back to how they were.

---

## Setup (about 30 minutes, once)

### 1. Firebase (free, used only for push)
1. Go to <https://console.firebase.google.com>, then **Add project**. Analytics isn't needed.
2. **Add app → Android**, package name `com.projectedith.alert`. Download **google-services.json**.
3. Go to **Project settings → Service accounts → Generate new private key**. Keep this JSON file
   private: anyone who has it can push to your app.

### 2. Build the APK
**Option A, GitHub builds it:** repo **Settings → Secrets and variables → Actions → New secret**,
name `GOOGLE_SERVICES_JSON`, value = the whole contents of google-services.json. Then
**Actions → Build Edith Alert APK → Run workflow**. When it finishes, download `edith-alert-apk`
from the run's page (it's a zip containing `app-debug.apk`).

**Option B, Android Studio:** put google-services.json in `alert-system/android/app/`, open
`alert-system/android`, then **Build → Build APK(s)**.

> Each GitHub build is signed with a new debug key. To install a newer build, uninstall the
> old app first, then enter the code again.

### 3. Deploy the website to Cloudflare (free)
```bash
cd alert-system/worker
npm install
npx wrangler login
npx wrangler deploy                                   # prints https://edith-alert.<you>.workers.dev
openssl rand -base64 32 | npx wrangler secret put CODE_SECRET
npx wrangler secret put FCM_SERVICE_ACCOUNT < path/to/service-account.json
```
Keep `CODE_SECRET` the same from then on: **changing it changes every phone's code.**

### 4. Lock the website with Cloudflare Access (Zero Trust, free for 50 users)
1. In the Cloudflare dashboard go to **Workers & Pages → edith-alert → Settings → Domains & Routes**.
   On the `workers.dev` row, enable **Cloudflare Access**. If asked, create a Zero Trust team; the free plan is fine.
2. Under **Zero Trust → Access → Applications**, edit that application's policy so that only your senders'
   emails are allowed. They log in with a one-time code sent to their email.
3. From the application's settings, copy the **Audience (AUD) tag** and your team domain
   (`<team>.cloudflareaccess.com`). Add them under **Worker → Settings → Variables** as text
   variables named `ACCESS_AUD` and `ACCESS_TEAM_DOMAIN`.

The Worker refuses to do anything until these are set, and it checks the Access login signature on every
request itself, so it isn't relying only on the dashboard setting.

### 5. Set up each phone
1. Open the website, type the person's name under **Add a phone** and press **Get code**.
2. On the Android phone, install the APK (allow "install unknown apps" when asked), open
   **Edith Alert** and enter the code.
3. Tap each **Allow:** button until all four show ✓ (notifications, full-screen alerts,
   Do Not Disturb, battery). On Samsung/Xiaomi/Oppo/Vivo/Huawei, also set the app's
   battery setting to **Unrestricted** and turn on **Autostart** if the phone has it.
4. Press **Test the alarm**. Then lock the phone and send a real alert from the website.

---

## Good to know
- **"Sent" means Google accepted the alert**, not that the phone rang. Without a database there are no
  read receipts. Alerts expire after 10 minutes, so a phone that was off doesn't ring hours later.
- **The phone list on the website is saved in each sender's browser.** Another sender just adds the same
  names; the same name gives the same code.
- **If someone's code leaks**, give that person a new name (e.g. "Sara 2") and pair their phone again.
  The old code keeps receiving "Sara" alerts, so stop sending to "Sara".
- **Phones without Google Play Services** (most Huawei phones since 2019) can't receive Firebase push.
- **iPhones can send but not receive.** iOS only lets apps override silent mode with Apple's
  "Critical Alerts" permission, which Apple grants mostly to medical and public-safety apps.
- **This isn't a real government alert.** Those come from phone carriers' cell broadcasts, which apps can't
  use. This needs mobile data or Wi-Fi.

## Development
```bash
cd alert-system/worker && npm test       # pairing codes, Access login check, Firebase sending (mocked)
cp .dev.vars.example .dev.vars && npm run dev   # local site with the login check switched off
```
The Android unit test (`CodesTest.kt`) checks the app derives the same codes and topics as the Worker.
CI runs it on every push that touches `alert-system/android/`.
