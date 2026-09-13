# Messaging Capability Matrix — Agent-Driven Send/Receive on Stock, Non-Rooted Android 14/15

**Question answered:** on a factory-stock, **non-rooted Android 14/15** phone, what are *all* the ways an
agent can send **and** receive messages programmatically, per platform — WhatsApp, WhatsApp Business,
Signal, Telegram, SMS, Instagram DMs, TikTok DMs, Discord, X DMs?

**Per platform × per path** we document: does it work at all · registration requirements (SMS‑capable
number / primary device) · send capability · read capability · ban‑risk notes · the exact OSS library +
repo URL.

**Method:** primary docs, official API references, and OSS repo READMEs/wiki, each cited with a URL.
Anything I could not confirm against a primary source is marked **UNVERIFIED**.

Legend: ✅ works · ⚠️ works with caveats · ❌ not possible / prohibited · 🟡 unclear or not independently verified.

---

## 0. What a stock, non-rooted phone actually lets you do

There is **no root** and no `/data/data` access, so the phone is a *client*, not a *server*, for anything
it does not own. Five distinct channels exist. Nearly every platform row below is one of these five.

| # | Channel | What it is | Needs | Send | Receive | Notes |
|---|---------|-----------|-------|------|---------|-------|
| 1 | **Cloud / official API over the network** | You call the platform's server API from anywhere (VPS, phone, laptop). The phone is irrelevant unless the account setup needs a SIM. | API credentials, business account on some platforms | ✅ | ✅ (webhook/poll) | No device access → no policy/root issues. |
| 2 | **Linked-device bridge** (whatsmeow / Baileys / signal-cli / Telethon) | A library registers/link as the account **on the wire** and speaks the app's real protocol. Runs on the phone (Termux) or on a server. | Account + (usually) the ability to link a companion device or register a number by SMS/voice | ✅ | ✅ | Unofficial: violates platform ToS on some apps; ban risk. Some need a **SMS-capable number**. |
| 3 | **On-device UI automation** (accessibility service / ADB) | The agent reads the screen and taps/types inside the *real* app. | Accessibility service granted, or ADB (wireless debugging) | ✅ | ✅ | Universal — works for any app that has no API. Slow, brittle, screen must be reachable. |
| 4 | **NotificationListenerService** (receive-only) | System delivers every posted notification (including message text) to your service. | User grants "Notification access" | ❌ | ✅ | The **universal receive path**; pairs with UI automation or intents for send. |
| 5 | **Telephony APIs** (SMS/MMS) | `SmsManager` to send; must be the **default SMS app** to receive. | `SEND_SMS` runtime grant (send); `ROLE_SMS` default-app role (receive) | ✅ | ⚠️ only as default SMS app | Stock Android, sideloaded APK only (Play restricts SMS perms). |

**Cross-cutting 14/15 constraints worth knowing up front**

- **Accessibility-service apps installed by sideload** hit Android 13+ **"Restricted settings"**: the user must explicitly allow restricted settings before the accessibility toggle is available. Practical blocker for a drop-in automation APK. Exact Google doc URL **UNVERIFIED** (third-party write-ups only, e.g. https://droidwin.com/allow-restricted-settings-missing-from-sideloaded-apps-in-android-13-fix/).
- **Foreground service types** (Android 14+) require a declared `foregroundServiceType` for long-running on-phone bridges; without it the service is killed. **UNVERIFIED** here against the exact Android 14 doc page.
- Sideloading bypasses **Google Play** policy (which restricts SMS/accessibility perms), but *not* Android's own runtime role/permission gates.

**tl;dr — best path per platform (details below):**

| Platform | Best agent path on stock Android | Works today? |
|---|---|---|
| WhatsApp | WhatsApp **Cloud API** (official) or **whatsmeow**/**Baileys** linked device (unofficial) | ✅ official / ⚠️ unofficial (ban risk) |
| WhatsApp Business | Same Cloud API (a *different* number than your WhatsApp Messenger account) | ✅ |
| Signal | **signal-cli** (register or link as secondary device) | ⚠️ works; Android/Termux JNI is the hard part |
| Telegram | **Bot API** (bots can't DM first) or **Telethon** user account (full control) | ✅ both |
| SMS | `SmsManager` send + **default-SMS-app role** for receive, from a sideloaded APK | ✅ |
| Instagram DMs | Official **Instagram Messaging API** (business, can't DM first) or **instagrapi** (unofficial) | ✅ official (inbound-first) / ⚠️ unofficial |
| TikTok DMs | **No official DM API**; UI automation only | ❌ official / ⚠️ UI automation |
| Discord | Official **Bot API** (bot can DM users; user-initiated preferred) | ✅ |
| X (Twitter) DMs | Official **X API v2 DM endpoints** (`dm.write`) or **twikit** (unofficial) | ✅ official (paid tier UNVERIFIED) / ⚠️ unofficial |
| *Any app, receive-only* | **NotificationListenerService** | ✅ |

---

## 1. WhatsApp

### 1A. Official — WhatsApp Cloud API (WhatsApp Business Platform)

| Field | Value |
|---|---|
| Works? | ✅ (send + receive) |
| What it is | Meta-hosted HTTP API; no library needed. Get-started: https://developers.facebook.com/documentation/business-messaging/whatsapp/get-started/ |
| Registration | Facebook/Meta account → Meta app with "Connect with customers through WhatsApp" → a **business phone number** registered for the API. Number **cannot be in use with WhatsApp Messenger**; if it is, it must first be deleted from WhatsApp. Can still be used for ordinary calls/SMS. Source: https://developers.facebook.com/docs/whatsapp/cloud-api/phone-numbers |
| Send | ✅ Free-form ("service") messages inside the **24-hour customer-service window**; outside it, only **pre-approved template** messages. Only to users who **opted in**. Source: https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-messages |
| Read | ✅ via **webhooks** (incoming messages/calls trigger the window). Same send-messages doc. |
| Ban risk | Low for compliant use; ban if you spam or breach the Business Messaging Policy. Ban/appeal article: https://faq.whatsapp.com/465883178708358 ; policy: https://business.whatsapp.com/policy |
| Cost | Per-conversation/pricing model; opt-in required. UNVERIFIED exact 2026 price sheet. |
| BSP wrapper | Twilio WhatsApp Business Platform: https://www.twilio.com/docs/whatsapp/api (and other BSPs, e.g. 360dialog). |

> Cloud API is **not** "a WhatsApp account an agent drives" — it is a **Business** identity. It cannot
> participate in personal chats or in chats that began with a personal account.

### 1B. Unofficial — linked-device bridges (`whatsmeow` / `Baileys`) — the "waagent pattern"

| Field | Value |
|---|---|
| Works? | ⚠️ technically yes (send + receive), **against ToS** |
| Library (Go) | **whatsmeow** — "Go library for the WhatsApp web multidevice API." Advertises *sending messages to private chats and groups (text + media)* and *receiving all messages*, read receipts, app-state sync. Not implemented: broadcast lists, calls. Repo: https://github.com/tulir/whatsmeow |
| Library (TS/JS) | **Baileys** — "WebSockets-based TypeScript library for interacting with the WhatsApp Web API." Repo: https://github.com/WhiskeySockets/Baileys (note breaking changes in 7.0.0; guide at https://baileys.wiki). |
| Agent framework on top | **wa-agent** — YAML-defined agent that links via QR ("Powered by … wu-cli for WhatsApp internals"), gives tools, memory, multi-agent routing, rate limiting. Repo: https://github.com/ibrahimhajjaj/wa-agent (+ https://github.com/ibrahimhajjaj/wu-cli) |
| Registration (mode 1: companion) | Link as a **linked device**: scan a QR, *or* **pair by phone number code** — `PairPhone(phone, clientType, displayName)` returns a code (e.g. `ABCD-EFGH`) that the user types into the phone's *Linked devices → Link with phone number*. Requires an **existing WhatsApp account on a phone** (primary device). Source: https://deepwiki.com/tulir/whatsmeow/7.5-phone-pairing-via-code |
| Registration (mode 2: new number) | whatsmeow/Baileys can drive the **registration** flow for a number that is *not yet* on WhatsApp, receiving the verification code via **SMS or voice call**. WhatsApp requires the number to be a real mobile number that can receive SMS/voice; **VoIP, toll-free, premium and UAN numbers are not supported** (landlines only on WhatsApp Business app). Source: https://faq.whatsapp.com/684051319521343/ → this is the "**whatsapp registration flows requiring SMS to a rented number**": rent a number that can receive SMS (or use a phone-farm SIM), request the code, verify. |
| Send | ✅ text + media to private chats and groups |
| Read | ✅ all incoming messages, receipts, group events |
| Ban risk | **Real and documented.** whatsmeow maintainers' discussion "WhatsApp has improved the ban rules for the message automation system": users report bans after only ~5 messages to new numbers — the trigger appears tied to *spam behaviour*, not the library itself. Source: https://github.com/tulir/whatsmeow/discussions/567 . WhatsApp's own help centre: bans for violating Terms / spam: https://faq.whatsapp.com/465883178708358 ; a "temporarily banned" message can indicate use of an **unofficial version** or scraping. |
| Underlying protocol | WhatsApp **multi-device** ("WhatsApp Web multidevice API") — companion devices are a supported product feature; the bridge is an unofficial client of it. |
| On-phone viability | whatsmeow is a Go program → can run in **Termux** (Go toolchain available); storage typically SQLite. **Running whatsmeow's default SQLite store on Android needs cgo/clang — UNVERIFIED end-to-end**; a pure-Go SQLite driver sidesteps it. |

### 1C. UI automation

⚠️ Works in principle (read screen + tap/type in WhatsApp), but is the slowest/least reliable option and
needs accessibility service or ADB. See §10.

---

## 2. WhatsApp Business

| Path | Works? | Registration | Send | Read | Ban risk | Source |
|---|---|---|---|---|---|---|
| **Cloud API** (same platform as §1A) | ✅ | Business number registered for the API; **cannot be simultaneously used in WhatsApp Messenger** | service msgs in 24h window; templates outside | webhooks | low if compliant | https://developers.facebook.com/docs/whatsapp/cloud-api/phone-numbers |
| **WhatsApp Business app linked device** via whatsmeow/Baileys | 🟡 | 🟡 pairing a *Business* account as a companion — technically the multidevice protocol is shared; **UNVERIFIED** that whatsmeow/Baileys officially support the Business app's extra features | ✅ (basic messaging) | ✅ | ⚠️ ToS/ban | https://github.com/tulir/whatsmeow |
| **Business app account bans** | — | — | — | — | Business accounts get the same ban regime + lose Meta Verified on ban | https://faq.whatsapp.com/723378546580115 |
| UI automation | ⚠️ | — | ✅ | ✅ | — | §10 |

**Key distinction:** "WhatsApp Business **Platform**" (= Cloud API, programmatic, opt-in + templates) vs
"WhatsApp Business **app**" (a normal phone app, no API). A personal WhatsApp and a WhatsApp Business
account **must use different phone numbers**. Source: https://faq.whatsapp.com/684051319521343/

---

## 3. Signal

**No official third-party bot/user API exists.** Signal does not publish a messaging API for third
parties (confirmed by absence on signal.org; the only supported "automation" surface is linked devices
under your own account). **UNVERIFIED as an explicit statement — it is a negative.**

### 3A. `signal-cli` (unofficial CLI / JSON-RPC / D-Bus) — the real path

| Field | Value |
|---|---|
| Works? | ⚠️ yes, with Android/Termux friction |
| What it is | "unofficial commandline, JSON-RPC and dbus interface for the Signal messenger… registering, verifying, sending and receiving messages." Uses a patched `libsignal-service-java` extracted from Signal-Android. Repo: https://github.com/AsamK/signal-cli |
| Registration | Requires a **phone number that can receive SMS or an incoming call** (`signal-cli -u +NN… register` → `verify CODE`). Can also **link as a secondary device** (`link`) to an existing Signal install. Source: https://github.com/AsamK/signal-cli (README) |
| Interfaces | CLI; **daemon mode with JSON-RPC** (man page: https://github.com/AsamK/signal-cli/blob/master/man/signal-cli-jsonrpc.5.adoc) and **D-Bus** (https://github.com/AsamK/signal-cli/blob/master/man/signal-cli-dbus.5.adoc). Rust example client in `/client`. |
| Runtime requirements | **JRE 25** + native `libsignal-client`. Pre-built natives ship **only for x86_64 Linux, Windows, macOS**. Other arch/OS → **compile the native lib from source**. Source: https://github.com/AsamK/signal-cli/wiki/Provide-native-lib-for-libsignal |
| Send / Read | ✅ both (CLI, JSON-RPC, D-Bus) |
| Must stay updated | "signal-cli needs to be kept up-to-date… releases older than three months may not work correctly." Same README. |

### 3B. The Android / Termux / proot JNI problem (special focus)

`libsignal-client` is a **Rust** library loaded via **JNI** (`libsignal_jni.so`). On Android aarch64 there
was **no published Android classifier**, so the JVM could not load the native lib → classic
`UnsatisfiedLinkError` JNI failures under Termux/proot. This is now being fixed upstream:

- **PR #2105 — "Support libsignal 0.101.0 Android JNI classifiers"**: adds a Gradle `androidClassifier`
  (e.g. `-PandroidClassifier=android-aarch64`) that resolves `org.signal:libsignal-client:0.101.0:android-aarch64`,
  which provides `libsignal_jni.so`. **"Verified on Termux / Android aarch64"** in the PR. URL: https://github.com/AsamK/signal-cli/pull/2105 (depends on https://github.com/signalapp/libsignal/pull/689)
- **PR #2106 — "Support Android SQLite native classifier"**: same idea for the SQLite native lib. URL: https://github.com/AsamK/signal-cli/pull/2106
- Community prebuilt natives (no Android classifier listed) for reference: https://github.com/exquo/signal-libs-build/

| Field | Value |
|---|---|
| Works on Termux/proot? | ⚠️ **Only with the Android classifier builds above.** Without them: JNI link failure. **UNVERIFIED whether these PRs are merged/released** as of writing — check the PR state. |
| Practical approach | Either run `signal-cli` on a **Linux server** and let the phone be the primary device, or build with `-PandroidClassifier=android-aarch64` inside Termux. |
| Docker/REST alternative | **signal-cli-rest-api** wraps signal-cli as a REST service (Docker). Register, verify, send, receive, link devices. Repo: https://github.com/bbernhard/signal-cli-rest-api — Docker on Android would itself need proot/distro. |
| Legacy Android build | `guardianproject/signal-cli-android` (old; JRE 7, D-Bus only, "formerly textsecure-cli"): https://github.com/guardianproject/signal-cli-android — **not** the modern path. |
| Ban risk | Signal is more tolerant than WhatsApp; registering many numbers or spamming can get numbers blocked. **UNVERIFIED** specific policy text. |

### 3C. UI automation
⚠️ Same universal caveat as §10.

---

## 4. Telegram

Two genuinely different accounts: **bots** (official) and **user accounts** (MTProto). This is the one
platform where both the official and the "user account automation" paths are fully supported.

### 4A. Official Bot API

| Field | Value |
|---|---|
| Works? | ✅ send + receive, **but a bot cannot start a conversation** |
| Hard limit | **"Bots can't start conversations with users. A user must either add them to a group or send them a message first."** Source: https://core.telegram.org/bots |
| API ref | https://core.telegram.org/bots/api (currently **Bot API 10.3**, updated Aug 24 2026) |
| Registration | Create a bot with **@BotFather**, get a token. No phone number, no SIM. |
| Send / Read | ✅ via HTTPS long-poll or **webhooks** (`getUpdates` / `setWebhook`). Rate limits: bots cannot bulk-notify beyond ~30 users/sec (429s). Source: https://core.telegram.org/bots/faq |
| Ban risk | Low for a normal bot; spam → bans. ToS: https://telegram.org/tos (no spam/scam). Bot-developer terms: https://telegram.org/tos/bot-developers |
| Implication | Because bots can't DM first, an agent that must **initiate** contact needs either a *user account* (§4B) or a deep-link the user clicks first. |

### 4B. User account via MTProto (Telethon / Pyrogram) — "can a phone-number account be driven fully?"

| Field | Value |
|---|---|
| Works? | ✅ **Yes — a full user account can be driven programmatically.** Telethon: "an asyncio Python 3 MTProto library to interact with Telegram's API **as a user** or through a bot account." https://github.com/LonamiWebs/Telethon (note: **moved to https://codeberg.org/Lonami/Telethon**; the GitHub repo may be deleted) |
| Registration / creds | You need **`api_id` + `api_hash`** from **https://my.telegram.org** (API Development), then log in as your own phone number (SMS/app code). Source: https://github.com/LonamiWebs/Telethon (sample code comments) |
| Send | ✅ `SendMessage` / `client.send_message('username', …)` — to **any user by username/phone**, no "must message first" rule |
| Read | ✅ full message history, events (`events.NewMessage`) |
| Other libs | **Pyrogram** — "MTProto API framework… user account (custom client) or a bot identity." **No longer maintained.** https://github.com/pyrogram/pyrogram . Native: **TDLib** https://github.com/tdlib/td (UNVERIFIED whether used in this build). |
| Ban risk | ⚠️ Real. Telegram **API ToS** https://core.telegram.org/api/terms and ToS https://telegram.org/tos (spam → ban). New accounts that DM strangers en masse get limited/banned quickly. Getting `api_id` requires a phone number. |
| Verdict | **A phone-number Telegram account can be driven fully** (send to anyone, read everything) with `api_id`/`api_hash` — this is the most capable unofficial-adjacent path on any messenger, because Telegram effectively sanctions third-party clients. |

### 4C. UI automation
⚠️ Also possible (Telegram apps are automation-friendly), but the APIs above make it unnecessary.

---

## 5. SMS (and MMS)

### 5A. `SmsManager` from a sideloaded APK — with default-SMS-app role for receive

| Field | Value |
|---|---|
| Works? | ✅ send; ⚠️ receive **only as the default SMS app** |
| Send | `SmsManager.getDefault().sendTextMessage(...)` — needs the **`SEND_SMS`** runtime permission. Ref: https://developer.android.com/reference/android/telephony/SmsManager |
| Receive | Since Android 4.4, **only the default SMS app** receives the `SMS_DELIVER` broadcast and can write the SMS provider. `SmsManager` docs say: "For information about how to behave as the default SMS app on Android 4.4 (API 19) and higher, see `Telephony`." Same URL. |
| Becoming default | Request the role: `RoleManager.ROLE_SMS` (https://developer.android.com/reference/android/app/role/RoleManager) — or the older `Telephony.Sms.Intents.ACTION_CHANGE_DEFAULT` intent with `EXTRA_PACKAGE_NAME`. Source: https://developer.android.com/guide/topics/permissions/default-handlers |
| Play policy | Google Play restricts SMS/call-log permissions to apps that are the **default handler** (or fall under an exception case). A **sideloaded** APK bypasses Play review but **still** needs the role to receive. Source: https://developer.android.com/guide/topics/permissions/default-handlers |
| Ban risk | N/A (carrier terms apply; bulk SMS via SIM can get the SIM blocked by the carrier — **UNVERIFIED** policy text). |
| Multi-SIM | `getSmsManagerForSubscriptionId(int)` for a specific SIM. Same SmsManager URL. |

**Practical recipe on a phone-farm:** sideload one APK that (a) requests `SEND_SMS`, (b) implements a full
default-SMS-app (receiver + compose/settings activities), then the user taps "Yes" on the role prompt →
the APK can send and read all SMS for that SIM. This is exactly what lets an agent receive the
WhatsApp/Signal/Telegram **registration codes** sent by SMS.

### 5B. Alternatives
- **NotificationListenerService** (§10) also surfaces incoming SMS notifications if your app isn't the default SMS app (notification text, not the raw PDUs).
- **Cloud SMS** (Twilio, etc.) — not on-device, out of scope here.

---

## 6. Instagram DMs

### 6A. Official — Instagram Messaging API (Instagram API with Instagram Login)

| Field | Value |
|---|---|
| Works? | ✅ send + receive, **but only after the user messages you first** |
| Hard limit | "**Conversations only begin when an Instagram user sends a message to your app user** through your app user's Instagram Feed, posts, story mentions, and other channels." Source: https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api |
| Account type | Requires an **Instagram professional account** (Business/Creator). Same URL. |
| Send | `POST https://graph.instagram.com/vXX.0/<IG_ID>/messages` with `recipient.id` + message. Same URL. |
| Windows | **24-hour standard messaging window** to reply; outside it, only limited/"human agent" tags. Source: https://developers.facebook.com/docs/messenger-platform/policy-overview/ |
| Read | ✅ webhooks + conversation events; note API messages are **not marked Read** in the app. Same messaging-api URL. |
| Ban risk | Low if compliant; policy: https://developers.facebook.com/docs/messenger-platform/policy-overview/ |
| Wrapper | Via **Messenger Platform** for IG-through-a-Facebook-Page; same policy page. |

### 6B. Unofficial — `instagrapi`

| Field | Value |
|---|---|
| Works? | ⚠️ yes (private API) |
| Library | **instagrapi** — "Fast and effective unofficial Instagram API wrapper for Python." Repo: https://github.com/subzeroid/instagrapi (there's also an async fork **aiograpi**). |
| Registration | Log in with an existing IG account (username/password, ideally with a session/proxy); no SMS registration of a new number needed beyond the account's own. |
| Send / Read | ✅ direct messages via the private mobile API |
| Ban risk | **High** — private API usage violates Meta's terms; the library's own docs warn about rate limits/checkpoints. Note the maintainer's own note that the previous `@instagrapi` Telegram group "has been restricted by Meta." Same repo. |

### 6C. UI automation
⚠️ Works (Instagram has no bot API for personal accounts). Same caveats as §10.

---

## 7. TikTok DMs

| Path | Works? | Notes | Source |
|---|---|---|---|
| **Official DM API** | ❌ | The TikTok for Developers programme lists **Login Kit, Share Kit, Green Screen Kit, Display API, Content Posting API, Research API, Data Portability API** — **no messaging/Direct-Message API**. | https://developers.tiktok.com/doc/overview |
| **Partner "Direct Messaging"** | 🟡 | A third-party (MessageGate) advertises "TikTok Direct Messaging… early access partner." **Not a TikTok-published API** — UNVERIFIED. | https://www.messagegate.com/en/tiktok-messaging.html |
| **Unofficial OSS DM library** | 🟡 | No widely-used maintained Python/JS TikTok DM library found; **UNVERIFIED**. | — |
| **UI automation** | ⚠️ | Realistically the **only** way an agent can send/read TikTok DMs on a phone today: accessibility service / ADB drives the app. | §10 |

**Bottom line:** treat TikTok DMs as **automation-only**. There is no supported programmatic path.

---

## 8. Discord

### 8A. Official — Bot API

| Field | Value |
|---|---|
| Works? | ✅ send + receive |
| Libraries | **discord.py** https://github.com/Rapptz/discord.py · **discord.js** https://github.com/discordjs/discord.js · raw REST/Gateway: https://discord.com/developers/docs |
| Registration | Create an **application/bot**, get a **bot token**. No phone number, no SIM. (Developer portal: https://discord.com/developers/applications) |
| Send DM | `POST /users/@me/channels` with `{"recipient_id": "<snowflake>"}` to open a DM channel, then post a message. Source: https://docs.discord.com/developers/resources/user ("Create DM") |
| Caveat | "DMs should generally be **initiated by a user action**. If you open a significant amount of DMs too quickly, your bot may be **rate limited or blocked** from opening new ones." Same URL. |
| Read | ✅ Gateway `MESSAGE_CREATE` events + REST history |
| Group DMs | `POST /users/@me/channels` with `access_tokens` (max 10 active group DMs). Same URL. |
| Ban risk | Low for a well-behaved bot. |
| Self-bot (user account) | ❌ **Forbidden.** Discord docs: developers must comply with the Developer ToS, "which includes **refraining from automating standard user accounts (generally called 'self-bots') outside of the OAuth2/bot API**." Account termination risk. Source: https://docs.discord.com/developers/topics/oauth2 |

### 8B. UI automation
⚠️ The desktop/mobile client can be driven, but Discord **explicitly forbids self-bot user-account automation** (above); use the bot API.

---

## 9. X (Twitter) DMs

### 9A. Official — X API v2 Direct Messages

| Field | Value |
|---|---|
| Works? | ✅ send + receive (endpoints exist) |
| Endpoints | `POST /2/dm_conversations` (create conversation) · `POST /2/dm_conversations/with/{participant_id}/messages` (send by participant) · `POST /2/dm_conversations/{id}/messages` · `GET …/dm_events` · `DELETE /2/dm_events/{id}`. Index: https://docs.x.com/x-api/llms.txt (DM section) |
| Example endpoint doc | https://docs.x.com/x-api/direct-messages/create-dm-message-by-participant-id.md ("Sends a new direct message to a specific participant by their ID.") |
| OAuth scopes | **`dm.read`, `dm.write`** (from the OpenAPI spec in the endpoint docs above) |
| Registration | X Developer account + app + user-context OAuth (the DMs act as *the authenticated user*). Developer platform: https://docs.x.com/overview |
| Access tier / cost | X now advertises "flexible **pay-per-usage** pricing." The historical requirement that DM endpoints sit behind a paid/Pro tier is **UNVERIFIED** under the current model — confirm in the Developer Console. |
| Wrapper | **tweepy** (official-API Python wrapper): https://github.com/tweepy/tweepy |
| X Chat (encrypted DMs) | Separate "X Chat" API with message + key-management endpoints: https://docs.x.com/xchat/introduction.md |
| Ban risk | Low when using the official API within rate limits. |

### 9B. Unofficial — `twikit` (private/internal API)

| Field | Value |
|---|---|
| Works? | ⚠️ yes |
| Library | **twikit** — "Twitter API Scraper | Without an API key | Twitter Internal API". Has `await client.send_dm(...)`. Repo: https://github.com/d60/twikit |
| Registration | Log in with an existing X account (cookies/credentials) |
| Ban risk | **High** — uses X's internal API, violates X terms; accounts get locked/suspended. |

### 9C. UI automation
⚠️ Possible; unnecessary given 9A/9B.

---

## 10. Cross-cutting: UI automation + NotificationListener (the "any app" layer)

### 10A. NotificationListenerService — the universal **receive** path

| Field | Value |
|---|---|
| Works? | ✅ receive from **any** app |
| API | "A service that receives calls from the system when new notifications are posted or removed…" Declare with `android.permission.BIND_NOTIFICATION_LISTENER_SERVICE` + the `NotificationListenerService` intent filter; wait for `onListenerConnected()`. Source: https://developer.android.com/reference/android/service/notification/NotificationListenerService |
| Grant | The user enables your app in **Settings → Notifications → Device & app notifications (Notification access)**. Cannot be granted silently. |
| What you get | Notification title/text/extras — i.e. the **content of incoming WhatsApp/Signal/Telegram/IG… messages**, sender, and often an inline reply action. |
| Limitation | Receive-only (you cannot send from a notification listener). Pair it with a **send path** (direct intents, `SharingShortcuts`, or UI automation). |

**Generic description of the aylacontrol pattern** (`com.nuri.aylacontrol/.service.MobilerunNotificationListener`):
a small sideloaded APK whose `NotificationListenerService` subclass (here named after the *Mobilerun*
mobile-agent project, https://github.com/droidrun/mobilerun) is exported under
`android.permission.BIND_NOTIFICATION_LISTENER_SERVICE`. Once the user grants "Notification access", the
service receives every posted notification, extracts sender + text from the `StatusBarNotification`, and
**forwards it to an agent backend** (HTTP/WebSocket). That turns the stock phone into a **read-everything
message sensor** with no root and no per-app integration — the same pattern works for *every* app in this
matrix. The companion *Mobilerun* framework (open-source, "control Android and iOS devices with LLM
agents… tap, swipe, type, plan multi-step workflows") supplies the **send** half by driving the UI. Repo:
https://github.com/droidrun/mobilerun (Android-side app: https://github.com/droidrun/mobilerun-portal).

### 10B. AccessibilityService / ADB UI automation — the universal **send** path

| Tool | What | Repo / doc |
|---|---|---|
| Android **AccessibilityService** | In-app service that reads window content and can perform gestures/clicks; enabled by the user in Accessibility settings. | https://developer.android.com/reference/android/accessibilityservice/AccessibilityService |
| **ADB** (incl. wireless debugging) | `adb shell` — `input tap/text`, `uiautomator dump`, `screencap`. Works on stock phones after enabling **Wireless debugging** (no root). | https://developer.android.com/tools/adb |
| **Appium** + **UiAutomator2 driver** | Cross-platform mobile automation over W3C WebDriver; drives native apps on real devices/emulators. | https://github.com/appium/appium · https://github.com/appium/appium-uiautomator2-driver |
| **Mobilerun** | LLM-agnostic mobile agent framework (inspect UI, tap, swipe, type, plan). | https://github.com/droidrun/mobilerun |

Trade-offs for all UI automation: **brittle** (layouts change), **slow** (~seconds per action), needs the
**screen reachable** (Foreground service type + "screen must be on/unlocked" or a headless pattern), and
sideload + Android 13+ **Restricted settings** friction for accessibility.

---

## 11. Summary table — everything, one place

| Platform | Path | Works? | Registration needs | Send | Read | Ban risk | Library / URL |
|---|---|---|---|---|---|---|---|
| WhatsApp | Official Cloud API | ✅ | Meta app + business number (not on WA Messenger) | ✅ | ✅ webhook | Low | https://developers.facebook.com/documentation/business-messaging/whatsapp/get-started/ |
| WhatsApp | whatsmeow (Go) | ⚠️ | Link device **or** register a SMS-capable number | ✅ | ✅ | High (unofficial) | https://github.com/tulir/whatsmeow |
| WhatsApp | Baileys (TS) | ⚠️ | Link device / register | ✅ | ✅ | High | https://github.com/WhiskeySockets/Baileys |
| WhatsApp | wa-agent (on whatsmeow) | ⚠️ | QR/link | ✅ | ✅ | High | https://github.com/ibrahimhajjaj/wa-agent |
| WhatsApp Business | Cloud API | ✅ | Business number ≠ WA Messenger | ✅ | ✅ | Low | https://developers.facebook.com/docs/whatsapp/cloud-api/phone-numbers |
| WhatsApp Business | Business **app** linked | 🟡 | qr/link | ✅ | ✅ | ⚠️ | https://github.com/tulir/whatsmeow |
| Signal | signal-cli (CLI/RPC/D-Bus) | ⚠️ | Register (SMS/voice) **or** link as 2nd device | ✅ | ✅ | Low–med | https://github.com/AsamK/signal-cli |
| Signal | signal-cli on Android | ⚠️ | + Android JNI classifier (`-PandroidClassifier=android-aarch64`) | ✅ | ✅ | Low–med | https://github.com/AsamK/signal-cli/pull/2105 |
| Signal | signal-cli-rest-api | ⚠️ | Docker | ✅ | ✅ | Low–med | https://github.com/bbernhard/signal-cli-rest-api |
| Telegram | Bot API | ✅ | @BotFather token — **bot can't DM first** | ✅ | ✅ | Low | https://core.telegram.org/bots |
| Telegram | Telethon (user acct) | ✅ | api_id/api_hash (my.telegram.org) + phone | ✅ | ✅ | Med (spam) | https://github.com/LonamiWebs/Telethon |
| Telegram | Pyrogram (user acct) | ⚠️ | same | ✅ | ✅ | Med | https://github.com/pyrogram/pyrogram *(unmaintained)* |
| SMS | `SmsManager` + default-SMS-app role | ✅ | `SEND_SMS` grant; **ROLE_SMS** to receive; sideloaded APK | ✅ | ⚠️ (as default app) | N/A | https://developer.android.com/reference/android/telephony/SmsManager |
| Instagram | Messaging API (official) | ✅ | **Professional account**; **user must message first**; 24h window | ✅ | ✅ | Low | https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api |
| Instagram | instagrapi | ⚠️ | IG account login (private API) | ✅ | ✅ | High | https://github.com/subzeroid/instagrapi |
| TikTok | — | ❌ | **No official DM API** | ❌ | ❌ | — | https://developers.tiktok.com/doc/overview |
| TikTok | UI automation | ⚠️ | accessibility/ADB | ✅ | ✅ | — | §10 |
| Discord | Bot API | ✅ | bot token (no phone) | ✅ (user-initiated preferred) | ✅ | Low | https://docs.discord.com/developers/resources/user |
| Discord | self-bot | ❌ | — | — | — | Termination | https://docs.discord.com/developers/topics/oauth2 |
| X | API v2 DMs | ✅ | X dev app + OAuth `dm.write`; tier UNVERIFIED | ✅ | ✅ | Low | https://docs.x.com/x-api/direct-messages/create-dm-message-by-participant-id.md |
| X | twikit | ⚠️ | X account login | ✅ | ✅ | High | https://github.com/d60/twikit |
| **Any** | **NotificationListenerService** | ✅ | user grants Notification access | ❌ | ✅ | N/A | https://developer.android.com/reference/android/service/notification/NotificationListenerService |
| **Any** | Accessibility/ADB UI automation | ⚠️ | accessibility grant or wireless ADB | ✅ | ✅ | N/A | https://developer.android.com/reference/android/accessibilityservice/AccessibilityService |

---

## 12. Practical recommendations for a phone-use agent

1. **Prefer cloud/official APIs** where they exist and fit the job (Telegram Bot, Discord Bot, WhatsApp
   Cloud, X API, Instagram Messaging) — zero device coupling, no ban risk, no root.
2. **Where the job requires *being the user*** (initiate DMs, personal WhatsApp, personal Signal,
   personal Telegram), the **linked-device bridge** is the only real path: whatsmeow/Baileys (WhatsApp),
   signal-cli (Signal), Telethon (Telegram). Budget for **ban risk** and keep volumes human-sized.
3. **Getting codes onto the phone:** a bridge that registers a **new** number needs **SMS/voice** to that
   number. On a phone-farm, either rent SMS-capable numbers, or make the agent's own APK the
   **default SMS app** (§5) so it can read the verification SMS directly.
4. **Universal fallback:** **NotificationListenerService** for *receive* + **accessibility/ADB** for
   *send* gives you a working agent for **every** app (including TikTok and IG-personal), with no root —
   at the cost of speed and reliability. This is the Mobilerun/aylacontrol pattern.
5. **Never** ship a Discord **self-bot** or run Instagram/Twitter **private-API** automation at volume —
   those are the fastest routes to termination.

---

## Appendix — source index

Official platform docs
- WhatsApp Cloud API get-started — https://developers.facebook.com/documentation/business-messaging/whatsapp/get-started/
- WhatsApp Cloud API phone numbers — https://developers.facebook.com/docs/whatsapp/cloud-api/phone-numbers
- WhatsApp Cloud API service messages / 24h window — https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-messages
- WhatsApp registration requirements — https://faq.whatsapp.com/684051319521343/
- WhatsApp account bans — https://faq.whatsapp.com/465883178708358 · Business bans — https://faq.whatsapp.com/723378546580115
- Instagram Messaging API — https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api
- Messenger/IG messaging policy (24h) — https://developers.facebook.com/docs/messenger-platform/policy-overview/
- Telegram Bot API — https://core.telegram.org/bots/api · Intro (bots can't start chats) — https://core.telegram.org/bots · FAQ — https://core.telegram.org/bots/faq · API ToS — https://core.telegram.org/api/terms
- Discord user resource (Create DM) — https://docs.discord.com/developers/resources/user · self-bot policy — https://docs.discord.com/developers/topics/oauth2
- X API v2 DM endpoints — https://docs.x.com/x-api/llms.txt · send-by-participant — https://docs.x.com/x-api/direct-messages/create-dm-message-by-participant-id.md · X Chat — https://docs.x.com/xchat/introduction.md
- TikTok developer docs (no messaging API) — https://developers.tiktok.com/doc/overview

Android platform
- SmsManager — https://developer.android.com/reference/android/telephony/SmsManager
- Default-handler permissions (SMS) — https://developer.android.com/guide/topics/permissions/default-handlers
- RoleManager (ROLE_SMS) — https://developer.android.com/reference/android/app/role/RoleManager
- NotificationListenerService — https://developer.android.com/reference/android/service/notification/NotificationListenerService
- AccessibilityService — https://developer.android.com/reference/android/accessibilityservice/AccessibilityService
- adb — https://developer.android.com/tools/adb

OSS libraries
- whatsmeow — https://github.com/tulir/whatsmeow · pair-by-code — https://deepwiki.com/tulir/whatsmeow/7.5-phone-pairing-via-code · ban discussion — https://github.com/tulir/whatsmeow/discussions/567
- Baileys — https://github.com/WhiskeySockets/Baileys · wa-agent — https://github.com/ibrahimhajjaj/wa-agent · wu-cli — https://github.com/ibrahimhajjaj/wu-cli
- signal-cli — https://github.com/AsamK/signal-cli · native libs wiki — https://github.com/AsamK/signal-cli/wiki/Provide-native-lib-for-libsignal · Android JNI PR — https://github.com/AsamK/signal-cli/pull/2105 · Android SQLite PR — https://github.com/AsamK/signal-cli/pull/2106 · signal-cli-rest-api — https://github.com/bbernhard/signal-cli-rest-api · signal-cli-android — https://github.com/guardianproject/signal-cli-android
- Telethon — https://github.com/LonamiWebs/Telethon (now https://codeberg.org/Lonami/Telethon) · Pyrogram — https://github.com/pyrogram/pyrogram
- instagrapi — https://github.com/subzeroid/instagrapi · discord.py — https://github.com/Rapptz/discord.py · discord.js — https://github.com/discordjs/discord.js · tweepy — https://github.com/tweepy/tweepy · twikit — https://github.com/d60/twikit
- mobilerun — https://github.com/droidrun/mobilerun · mobilerun-portal — https://github.com/droidrun/mobilerun-portal · Appium — https://github.com/appium/appium · UiAutomator2 driver — https://github.com/appium/appium-uiautomator2-driver
- signal-libs-build (community natives) — https://github.com/exquo/signal-libs-build/

**UNVERIFIED items flagged in this document**
- Exact Google doc URL for Android 13+ "Restricted settings" on sideloaded accessibility apps.
- Android 14+ foreground-service-type behavior for long-running on-phone bridges.
- Whether whatsmeow/Baileys officially support linking a **WhatsApp Business app** account as a companion.
- Whether signal-cli PRs #2105/#2106 are merged/released (check PR state).
- X API v2 DM **access tier / price** under the new pay-per-usage model.
- TikTok partner "Direct Messaging" (MessageGate, early access) as a real API.
- Any maintained OSS TikTok DM library.
- running whatsmeow's default SQLite store end-to-end on Android/Termux.
- Signal's explicit public statement that no third-party API exists (it is a confirmed-by-absence negative).
