# phoneuse-agent

**Turn old Android phones into AI-operable agent nodes.**

PUA (phone-use agent) is to phones what CUA is to desktops: an agent reads the
screen and taps, types and navigates like a person — no root, no proprietary
cloud, no screenshots required. A laptop holds the brain and the control plane;
each phone is a small VPS plus a control target. Add phones, they join the fleet.

```
adb plug phone  →  ./bootstrap/node.sh  →  node online
```

---

## Why

A drawer of old Android phones is a pile of idle CPUs, screens, radios and
batteries. Rooted only by an accessibility service and `adb`, each one becomes a
headless node that can:

- run Linux-ish workloads in **Termux** (sshd, cron, python, node, git)
- be **operated by an LLM** — read the accessibility tree, tap coordinates,
  type into fields, launch apps, press home/back
- be **farmed** — the control plane polls every node, streams its screen and
  runs tasks on any of them

No root. No flashing. No proprietary backend. F-Droid apps, `adb`, and an
OpenAI-compatible model endpoint.

## Architecture

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

Details and measured latencies: [`docs/architecture.md`](docs/architecture.md).

## Quickstart

Requirements: `adb` (Android platform-tools), `ssh-keygen`, `curl`, and on the
phone a USB-debugging-enabled **Android 8+**, **non-rooted** device.

```sh
git clone https://github.com/<you>/phoneuse-agent && cd phoneuse-agent

# one phone, over USB:
./bootstrap/node.sh
# → ✓ node online  serial=XXXX  LAN IP=192.168.1.42
```

`node.sh` is idempotent. It installs Termux + Termux:Boot (F-Droid), grants
storage, bootstraps the Termux VPS (key-only sshd on :8022, boot script, wake
lock), hardens the device against being killed, installs the PUA control
channel and prints the node's LAN IP and an `ssh` command.

Register the node and start the control plane:

```sh
cp farm/nodes.example.json farm/nodes.json     # edit serial + name
pip install -r farm/requirements.txt
cd farm && python server.py                    # dashboard at http://localhost:8787
```

### Fleet manifest (optional — for many phones)

For a larger fleet, `farm/manifest.json` is a single source of truth (per-node
SSH/ADB/portal ports, Tailscale hostname, brain, USB port). Render it into
per-node artifacts and keep adb-over-TCP connected:

```sh
cp farm/manifest.example.json farm/manifest.json   # edit serials + IPs
python3 farm/render_manifest.py                    # -> farm/render/{env,ssh,apply}
python3 farm/render_manifest.py --check            # validate only
farm/adb_watchdog.sh                               # reconnect nodes over TCP
```

### Give the agent a brain

```sh
pip install mobilerun
mobilerun configure --provider openai_like \
  --base-url https://your-endpoint/v1 --model your-model --api-key "$API_KEY"

mobilerun run --no-reasoning --steps 15 -d <serial> "Open Chrome and go to example.com"
```

The dashboard runs exactly this command against whichever node you pick, and
streams the log back.

### Add more phones

Run `./bootstrap/node.sh` once per phone (or set `ANDROID_SERIAL=<serial>` when
several are attached), then add each serial to `farm/nodes.json`. Over the
network, `adb connect <ip>:5555` and the same scripts apply.

## Repo layout

```
bootstrap/
  node.sh            idempotent adb bootstrap: adb plug phone → node online
  termux-setup.sh    on-phone script (packages, sshd, boot, hardening)
android/pua-control/ accessibility control channel (dump/click/type/launch)
control/
  pua-control.sh     host or on-device CLI for the control channel
farm/
  server.py          FastAPI control plane (multi-node)
  static/index.html  dashboard
  nodes.json         node registry (template)
  nodes.example.json node registry example
  manifest.example.json  fleet manifest: ports, tailscale, per-node brain
  render_manifest.py     render the manifest -> per-node env/ssh/apply artifacts
  adb_watchdog.sh        keep adb-over-TCP alive for every node
docs/
  architecture.md    components + latency table
  messaging.md       driving Telegram/WhatsApp from a node
  scaling.md         growing the controller from 1 to 50 phones
```

## Requirements

| Part | Needs |
|---|---|
| Node (phone) | Android 8+, USB debugging, ~1.5 GB free |
| Bootstrap host | `adb`, `ssh-keygen`, `curl` |
| Control channel | `gradle` + JDK 17 + Android SDK `$ANDROID_HOME` (or a prebuilt `PUA_APK`) |
| Control plane | Python 3.10+ (`fastapi`, `uvicorn`, `pydantic`) |
| Agent harness | `pip install mobilerun` + an OpenAI-compatible endpoint |

The Termux VPS bootstraps even without the Android SDK; only the control channel
needs it.

## Security

- The control channel is an accessibility service with full UI control of the
  phone. Enable it only on devices you own, and only while `adb` access is
  trusted. Keep USB debugging off on any phone that leaves your control.
- sshd is **key-only** on :8022 (`PasswordAuthentication no`). Node keys live in
  `keys/` and are git-ignored — never commit them.
- No secrets belong in this repo. Node registries, keys and logs are all
  git-ignored.

## License

MIT — see [LICENSE](LICENSE).
