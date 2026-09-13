# pua-control — on-device accessibility control channel

A single-file-and-a-few-classes Android app that exposes a broadcast-driven control
channel over the accessibility service. Allows a host (Mac/PC/Linux, over `adb`) or
the phone itself (via `am broadcast`) to:

- `dump` — full accessible-view tree of the current window (text, ids, bounds)
- `click x y` / `click-id <viewId>` — tap by coordinate or by accessibility node
- `set-focused-text <text>` / `set-text <viewId> <text>` — type without an IME
- `launch <package>` / `open-url <url>` / `home` / `back` / `recents`
- notifications — read active notifications, open the latest

All commands are plain `am broadcast` intents, so the tunnel is `adb` (USB or TCP).
No root, no proprietary service, no network socket.

## Build

Requires JDK 17 and an Android SDK (`ANDROID_HOME` set). Gradle 8.x.

```sh
export JAVA_HOME="$(/usr/libexec/java_home -v 17)"   # macOS; use your JDK17 path elsewhere
gradle -q assembleDebug
# → app/build/outputs/apk/debug/app-debug.apk
```

Install + enable (the repo's `bootstrap/node.sh` does this automatically):

```sh
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell settings put secure enabled_accessibility_services com.phoneuse.control/.PuaAccessibilityService
adb shell settings put secure accessibility_enabled 1
adb shell cmd notification allow_listener com.phoneuse.control/.PuaNotificationListenerService
```

Then drive it with `control/pua-control.sh`.

`minSdk 26` (Android 8). No runtime permissions beyond the accessibility bind.
