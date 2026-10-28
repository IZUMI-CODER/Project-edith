# Edith Alert

Press a button on a website (works on iPhone or any browser) and chosen Android phones play a
loud siren, even on silent, until someone taps **Dismiss**. Similar to an Amber Alert, but for your own group.

```
Sender's browser ──► Cloudflare Worker ──► Firebase Cloud Messaging ──► Edith Alert APK
 (asks the sender       (free; signs the        (free; only the push       (alarm stream at max
  password once)         pairing codes)          part, no database)         volume, full-screen)
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
**Option A, GitHub builds it:** commit google-services.json as `alert-system/android/app/google-services.json`
(it ships inside every APK, so it isn't a secret), or put its contents in a repository secret named
`GOOGLE_SERVICES_JSON`. Every push that touches `alert-system/android/` builds the app. When it finishes,
download `edith-alert-apk` from the run's page (it's a zip containing `app-debug.apk`).

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

### 4. Set the sender password
```bash
npx wrangler secret put SEND_PASSWORD
```
Pick something long (8+ characters, a short sentence is good). Each sender types it **once** on their
phone or computer along with their name; the browser remembers it after that. To lock everyone out,
set a new password with the same command.

The site refuses to send anything until a password is set. Anyone who has the password can sound the
alarm, so share it only with senders.

*Optional instead:* email login through Cloudflare Access (Zero Trust, free for 50 users). Enable
Access on the Worker's workers.dev domain, then set `ACCESS_TEAM_DOMAIN` and `ACCESS_AUD` as secrets.
When those are set they replace the password.

### 5. Set up each phone
1. Open the website, type the person's name under **Add a phone** and press **Get code**.
2. On the Android phone, install the APK (allow "install unknown apps" when asked), open
   **Edith Alert** and enter the code.
3. Tap each **Allow:** button until all four show ✓ (notifications, full-screen alerts,
   Do Not Disturb, battery). On Samsung/Xiaomi/Oppo/Vivo/Huawei, also set the app's
   battery setting to **Unrestricted** and turn on **Autostart** if the phone has it.
4. Press **Test the alarm**. Then lock the phone and send a real alert from the website.

---

## How alerts reach the phone (two routes)
Every alert goes out two ways, and the phone rings on whichever arrives first:
1. **Direct link.** The app keeps a WebSocket open to your site (`/api/listen`, a free Cloudflare Durable
   Object). The site pings every phone every 30 s, so Wi-Fi extenders and routers that silently drop
   "idle" connections never see it as idle. When you send, the site shows **📶 Connected right now** for
   phones on this link.
2. **Google push (FCM).** Reaches phones whose direct link is down. It can be lost on Wi-Fi extenders,
   because Google's own connection only checks in every ~15 minutes.

The app's address for the direct link is `edith.serverUrl` in `android/gradle.properties`. Change it
if your site has a different address, then push to rebuild the APK.

## Voice messages
On the website, tap **🎤 Record voice message** (up to 30 s; works in iPhone Safari), then send. The recording
waits in the Durable Object for 15 minutes, and only the phones it was sent to can download it. Alerts on both
routes just carry a "has voice" flag, and the audio never goes through Google. The phone plays the chime, then
the voice, then the chime again, repeating until Dismiss. Speech plays 10 dB above the phone's alarm-volume slider.

## Updates
The app updates itself from this repo's latest release: it checks every 6 hours, whenever it's opened, or
when someone taps **Check for updates**. The first self-update asks the person to tap **Update** (and to allow
"install unknown apps" for Edith Alert). After that, Android 12+ installs updates silently. Every CI build gets a
higher version number and publishes `version.json` next to the APK. Android only installs an update signed
with the same key, and CI keeps that key in its cache (`edith-alert-signing-v2`).

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
