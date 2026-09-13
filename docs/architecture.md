# Architecture

phoneuse-agent turns ordinary, unrooted Android phones into AI-operable agent
nodes. Each phone is both a small VPS (Termux) and a control target (an
accessibility service that exposes taps, typing and the view tree over a
broadcast channel). A laptop hosts the brain and the control plane; the phones
are interchangeable workers.

```
                          ┌──────────────────────────────────────────┐
                          │                 BRAIN                    │
                          │   any OpenAI-compatible chat endpoint    │
                          │   (Kimi / GPT / local vLLM / llama.cpp)  │
                          └────────────────────┬─────────────────────┘
                                               │ plan + act loop
                          ┌────────────────────▼─────────────────────┐
                          │        AGENT HARNESS (mobilerun CLI)     │
                          │   reads a11y tree / screenshots, emits   │
                          │   tap · swipe · type · launch · back     │
                          └────────────────────┬─────────────────────┘
                                               │ adb (USB or TCP)
        ┌──────────────────────────────────────┼───────────────────────────────┐
        │                        FARM CONTROL PLANE (farm/)                     │
        │   FastAPI · nodes.json registry · online/offline · live screen · task │
        └───┬──────────────────────┬───────────────────────┬───────────────────┘
            │ adb                  │ adb                    │ adb
   ┌────────▼────────┐   ┌─────────▼────────┐   ┌──────────▼────────┐
   │   NODE 1 phone  │   │   NODE 2 phone   │   │   NODE N phone    │
   │  ┌────────────┐ │   │                  │   │                   │
   │  │ Termux sshd│ │   │   (identical)    │   │   (identical)     │
   │  │ :8022 key  │ │   │                  │   │                   │
   │  ├────────────┤ │   │                  │   │                   │
   │  │ PUA control│ │   │                  │   │                   │
   │  │ a11y svc   │ │   │                  │   │                   │
   │  ├────────────┤ │   │                  │   │                   │
   │  │ Android app│ │   │                  │   │                   │
   │  └────────────┘ │   │                  │   │                   │
   └─────────────────┘   └──────────────────┘   └───────────────────┘
```

## Components

### 1. Control channel — `android/pua-control/` + `control/pua-control.sh`
An Android app exposing a `BroadcastReceiver` plus an `AccessibilityService`
(and a `NotificationListenerService`). The host sends `am broadcast` intents;
the service performs the action and returns the result as broadcast result data.

| Command | Effect |
|---|---|
| `dump` | full accessible-view tree (class, id, text, desc, bounds, focus) |
| `click x y` | tap by coordinate (gesture dispatch) |
| `click-id <viewId>` | click the nearest clickable node with that view id |
| `set-focused-text <t>` | set text on the focused input — **no IME needed** |
| `launch <pkg>` / `open-url <url>` | foreground an app / open a URL |
| `home` / `back` / `recents` | global navigation actions |
| `notifications` / `open-notification` | read / open active notifications |

Why this instead of pure `adb input`: it is faster, works over a single adb
channel, needs no root, and gives the agent a *structured* view tree rather than
a screenshot. `adb input tap` is kept as a fallback; `uiautomator dump` is the
slow path when the a11y service is not available.

### 2. Node VPS — `bootstrap/`
`node.sh` runs on the host and drives everything over adb: installs Termux +
Termux:Boot from F-Droid, grants storage, launches Termux once to lay down its
package bootstrap, then runs `termux-setup.sh` inside Termux (headless via
`run-as`, with a UI-typing fallback). `termux-setup.sh` installs the packages,
writes the boot script (wake lock + sshd + crond), sets up key-only sshd on
:8022, and hardens the device so Android does not kill it:

- `settings_enable_monitor_phantom_procs false`
- `device_config put activity_manager max_phantom_processes 2147483647`
- `wifi_sleep_policy 2`, `stay_on_while_plugged_in 3`
- doze whitelist for `com.termux`

### 3. Farm control plane — `farm/`
A small FastAPI app. `nodes.json` is the registry (serial → name/role). The API
polls every node over `adb devices` for online/offline, gathers battery, IP,
sshd and a11y health, serves a live base64 screen per node, and runs a natural
language task against **any** node through the `mobilerun` CLI. `static/index.html`
is the dashboard (node picker, per-node screen, task runner, log tail).

### 4. Agent harness — `mobilerun` CLI
`pip install mobilerun`. Configure an OpenAI-compatible brain with
`mobilerun configure --provider openai_like --base-url <url> --model <model>
--api-key <key>`, then `mobilerun run --no-reasoning --steps 15 -d <serial> "<task>"`.
The a11y-tree mode (`--no-vision`) is faster and more reliable than vision mode
for typical apps.

## Measured latencies

Galaxy S21 (Exynos 2100, Android 15), USB, persistent SDK connection:

| Operation | Latency |
|---|---|
| tap (gesture dispatch) | **68–93 ms** |
| accessibility view tree (~29 KB) | **~1.4 s** |
| screenshot (`screencap -p`) | **662 ms** |
| scrcpy H.264 frame stream | 35–70 ms (only if video is needed) |
| mobilerun CLI per-command | ~6 s — Python startup, not control latency |
| full agent run (Kimi highspeed, a11y-tree mode, 7 steps) | **49 s** |

Two takeaways drive the design:

1. **Keep a session alive.** Control latency is milliseconds; the ~6 s per-command
   cost is process startup. A persistent SDK/adb connection removes it.
2. **Prefer the a11y tree over screenshots.** The tree is ~2 ms/ms cheaper per
   frame-of-truth and gives exact bounds the model can act on; screenshots cost
   662 ms and add OCR ambiguity.

## Design notes / limits

- No root. Everything uses the accessibility service + `adb`/`am` + Termux userland.
- Termux native packages, never proot (`proot` adds ~110× `fstatat` overhead).
- `minitouch` is broken on Android 13+; use the a11y gesture path or scrcpy.
- On-device LLM is pointless below a modern NPU (≈3–5 tok/s CPU); keep the brain
  on the host or a small server.
- USB hub/controller limit is ~32 devices per XHCI controller; beyond that go
  over the network (WireGuard/Tailscale) with `adb connect`.
