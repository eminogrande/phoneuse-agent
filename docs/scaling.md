# Multi-phone scaling layer

How the controller grows from 1 phone to 50.

Files in this layer:

| File | Role |
|---|---|
| `farm/manifest.json` | single source of truth: one object per phone |
| `farm/manifest.schema.json` | JSON Schema (draft 2020-12) for that file |
| `farm/render_manifest.py` | manifest → on-device env/sshd/apply files + `farm/render/nodes.json` |
| `farm/adb_watchdog.sh` | controller-side loop that keeps `adb connect` alive |
| `farm/logs/<serial>/` | per-device log root (`adb.log`, `task.log`, `agent.log`, …) |

Design constraints come from `~/phone-farm-research/CONSOLIDATED_REPORT.md` §1 and §5
(USB hard limits, hybrid bootstrap, Termux/sshd behaviour) and from the v1 control
plane at `~/phonefarm/farm/server.py`.

---

## 0. Invariants

1. **One manifest, generated artifacts.** Never hand-edit env files or `nodes.json`; edit
   `manifest.json` and re-render. `index` is the only thing you allocate by hand.
2. **Index is permanent.** node-01 = `index 0`, node-50 = `index 49`. Appending is fine;
   renumbering breaks ports, ACLs, log dirs and dashboards. Disable a node
   (`"enabled": false`), don't recycle its slot.
3. **Two planes, different failure modes.**
   - *Control plane* = adb-over-TCP + sshd, over the LAN/Tailscale mesh. Carries all
     real traffic (tasks, screens, logs).
   - *Bootstrap/reboot plane* = USB, only to arm `adb tcpip`, accept the adb RSA key,
     install/update the APK, and (with `uhubctl`) hard-reboot a wedged phone.
   Hybrid is the documented pattern: pure USB dies at ~30 phones/controller, pure Wi-Fi
   drops entries regularly (STF issue #972: devices "regularly lose connection with adb
   through wifi" across 150 devices).
4. **A dead phone is a state, not an exception.** Every layer (watchdog, controller,
   job runner) must tolerate `absent / offline / unauthorized` without stalling.

---

## 1. Topology

```
                       CONTROLLER (1 host, grows to 2-3)
     jobs/API ────────▶  registry (nodes.json) · health poller · task runner
     browser  ────────▶  scrcpy fan-out (1 process/phone, h264 -m720 -b4M)
                         adb_watchdog.sh (systemd timer / launchd / cron)
                             │                        │
                    Tailscale mesh              LAN (Wi-Fi/LAN)
                  sshd :8022+index            adb :5555+index
                             │                        │
        ┌────────────────────┴────────────────────────┴───────────────┐
        │  PHONE  node-NN  (Termux sshd + com.phoneuse.control)       │
        │  USB  ──▶ bootstrap only: adb tcpip 5555+index, APK, uhubctl│
        └─────────────────────────────────────────────────────────────┘
```

USB provider host is *not* the controller in a 50-phone layout — it is a Linux box (or
PCIe xHCI card) you plug phones into when onboarding or when a node needs a hard reboot.
See §7.

---

## 2. Manifest

`farm/manifest.json`:

```json
{
  "version": 1,
  "port_base": { "sshd": 8022, "adb": 5555, "portal": 8080 },
  "defaults": {
    "a11y_package": "com.phoneuse.control/com.phoneuse.control.PuaAccessibilityService",
    "admin_number": "+49…",
    "brain_provider": "ollama:qwen3:8b"
  },
  "nodes": [
    {
      "index": 0,
      "serial": "R58M00000000",
      "name": "node-01",
      "role": "agent+vps",
      "model": "SM-G991B",
      "tailscale_hostname": "pua-node-01",
      "lan_ip": "192.168.1.50",
      "a11y_package": "com.phoneuse.control/com.phoneuse.control.PuaAccessibilityService",
      "admin_number": "+49…",
      "brain_provider": "ollama:qwen3:8b",
      "wa_account": null,
      "usb": { "hub": "1-1", "port": "1-1.1", "uhubctl_device": "1", "controller": "ctrl0" },
      "enabled": true
    }
  ]
}
```

| Field | Req | Meaning |
|---|---|---|
| `index` | ✅ | 0-based permanent slot. Drives every port. |
| `serial` | ✅ | adb USB serial; also the log directory name. |
| `name` | ✅ | `node-NN`, NN = index + 1 (node-01 = index 0). |
| `role` | – | free tag surfaced by the API (`agent+vps`). |
| `model` | – | `ro.product.model`, for the dashboard. |
| `tailscale_hostname` | ✅ | mesh DNS name, unique in the tailnet. |
| `tailscale_ip` | – | recorded after enrollment. |
| `lan_ip` | –* | WiFi IPv4 for adb-over-TCP. Use a DHCP reservation. |
| `adb_endpoint` | –* | explicit `host:port` when `lan_ip` isn't enough. |
| `ssh_port` | – | derived `8022 + index`; pin only to document a deviation. |
| `adb_port` | – | derived `5555 + index`. |
| `portal_port` | – | derived `8080 + index` (on-device HTTP control portal). |
| `a11y_package` | ✅ | `enabled_accessibility_services` entry, `package/class`. |
| `admin_number` | ✅ | E.164 number this node's agent reports to. |
| `brain_provider` | ✅ | LLM for this node, e.g. `ollama:qwen3:8b`, `guiowl:gui-owl-1.5-8b`, `openai_like:http://127.0.0.1:8080/v1`. |
| `wa_account` | – | WhatsApp account/number signed in on this phone, else `null`. |
| `usb` | – | physical position: `hub`, `port` (uhubctl spec), `uhubctl_device`, `controller`. |
| `enabled` | – | `false` keeps the slot, stops rendering/monitoring. |

\* at least one of `lan_ip` / `adb_endpoint` is required for the watchdog to reach the node.

`defaults` fills `a11y_package` / `admin_number` / `brain_provider` for any node that omits
them — on a 50-phone fleet you usually set these once.

Validate at any time:

```bash
python3 farm/render_manifest.py --check
```

Hard failures: duplicate serial/name/index/hostname/port, non-E.164 `admin_number`,
placeholder IPs (`192.168.1.0`, `127.0.0.1`), port collisions, >50 nodes.
Warnings: name/index mismatch, non-contiguous index, missing `lan_ip`, port deviation.

---

## 3. Port allocation

| Plane | Base | Rule | node-01 | node-50 | Reachable from |
|---|---|---|---|---|---|
| Termux sshd | 8022 | `8022 + index` | 8022 | 8071 | Tailscale |
| adb-over-TCP | 5555 | `5555 + index` | 5555 | 5604 | LAN / Wi-Fi |
| on-device portal | 8080 | `8080 + index` | 8080 | 8129 | Tailscale |

Fifty nodes stay inside `8022–8071`, `5555–5604`, `8080–8129` — no overlap, all
>1024 (no root needed on the phone side).

**Why per-node ports at all**, when each phone has its own IP and `:8022`/`:5555`
everywhere would technically work:

- controller-side `adb forward` / `ssh -L` tunnels land on *localhost* and collide —
  an index-derived port keeps the tunnel table and the direct table identical;
- `adb devices` output, ACL port ranges, logs and dashboards stay unambiguous
  (one row = one port);
- the same table covers mesh, LAN, and USB-forwarded access with no special cases.

Termux sshd's own default is 8022, so node-01 needs no change; every other phone gets
`Port <8022+index>` in `$PREFIX/etc/ssh/sshd_config` (rendered file:
`farm/render/ssh/<serial>.sshd_config`).

Arming a node (USB, once per boot until `adb tcpip` persists):

```bash
adb -s <serial> tcpip 5555+index        # e.g. node-02 -> 5556
adb -s <serial> shell ip -f inet addr show wlan0   # record as lan_ip
adb connect <lan_ip>:<5555+index>
```

---

## 4. Renderer

```bash
python3 farm/render_manifest.py                        # → farm/render/
python3 farm/render_manifest.py --controller 100.64.0.1
python3 farm/render_manifest.py --check                # validate, write nothing
```

Output (regenerated wholesale; `farm/render/` is a build artifact):

| Artifact | Goes to | Content |
|---|---|---|
| `render/env/<serial>.env` | phone `~/.pua/env/<serial>.env` | `PUA_*` env (index, serial, ports, a11y package, admin number, brain, WA account, controller, log dir) |
| `render/ssh/<serial>.sshd_config` | phone `$PREFIX/etc/ssh/sshd_config` | `Port <8022+i>`, key-only, no root |
| `render/apply/<serial>.sh` | run on the phone | idempotent: installs env, writes sshd config, enables the a11y service, wake-lock, restarts sshd under termux-services |
| `render/nodes.json` | controller `farm/nodes.json` | registry read by `server.py` |
| `render/adb_targets.txt` | controller | `host:port<TAB>serial<TAB>index` |
| `render/tailscale/{mint_key,enroll}.sh`, `grants.json` | controller | fleet enrollment + ACL snippet |
| `render/index.json` | controller | node count + port map (for dashboards/tests) |

`nodes.json` row (superset of the v1 `{serial,name,role}` shape — existing consumers keep
working):

```json
{
  "index": 0, "serial": "R58M00000000", "name": "node-01", "role": "agent+vps",
  "model": "SM-G991B", "enabled": true,
  "ssh_port": 8022, "adb_port": 5555, "portal_port": 8080,
  "adb_endpoint": "192.168.1.50:5555",
  "tailscale_hostname": "pua-node-01", "tailscale_ip": null,
  "a11y_package": "com.phoneuse.control/com.phoneuse.control.PuaAccessibilityService",
  "admin_number": "+49…", "brain_provider": "ollama:qwen3:8b", "wa_account": null,
  "usb": { "hub": "1-1", "port": "1-1.1", "uhubctl_device": "1", "controller": "ctrl0" },
  "controller": "100.64.0.1", "log_dir": "farm/logs/R58M00000000/"
}
```

Apply to a node (env + sshd + a11y in one shot):

```bash
scp farm/render/apply/<serial>.sh pua-node-02:~/apply-<serial>.sh
ssh -p 8023 pua-node-02 'sh ~/apply-<serial>.sh'
```

### 4.1 Relationship to `bootstrap/node.sh`

Two phases, no overlap — run them in order, both are idempotent:

| Phase | Script | Scope |
|---|---|---|
| 1. create the node | `bootstrap/node.sh` (USB, one-time per phone) | installs Termux + Termux:Boot, generates/installs the node key, hardens the device (phantom killer, Wi-Fi sleep, doze), installs the PUA APK, brings up sshd on **:8022** |
| 2. give it a slot | `farm/render/apply/<serial>.sh` (per node, over ssh) | writes `~/.pua/env/<serial>.env`, rewrites `sshd_config` with the node's `8022+index`, enables the a11y service, restarts sshd under termux-services |

`node.sh` is single-node by construction (`:8022`, "register it as `node-01`"). It stays the
onboarding path; **the generated apply script is what makes node-02…node-50 differ** — it is
the only thing that moves a phone off :8022 and stamps its identity. `node.sh`'s a11y grant
uses the short form `com.phoneuse.control/.PuaAccessibilityService`; the renderer writes the
fully-qualified form and matches on the package name, so re-applying never double-registers
the service.


---

## 5. Tailscale enrollment

One **reusable, pre-authorized auth key tagged `tag:pua-node`** covers the whole fleet.

Mint it once (admin API key, not an auth key):

```bash
export TS_API_KEY=tskey-api-…
sh farm/render/tailscale/mint_key.sh          # prints tskey-auth-…, reusable+tagged
```

The script POSTs to `https://api.tailscale.com/api/v2/tailnet/<tailnet>/keys` with
`{"capabilities":{"devices":{"create":{"reusable":true,"preauthorized":true,"tags":["tag:pua-node"]}}}}`
and a 90-day expiry (auth keys can be 1–90 days; node keys default to 180 days).

Per-phone enrollment — **Android has no `tailscale` CLI**, so the phone-side step is the
official app's *Sign in → Use an auth key* screen (drive it with phoneuse-agent, or do it
by hand while the phone is on the bench):

1. install Tailscale from Play, open it once, paste the auth key;
2. rename the device to the manifest `tailscale_hostname` (`pua-node-01`);
3. `tailscale status | awk '/pua-node-/ {print $2, $1}'` → record the IPs into
   `tailscale_ip` and re-render.

Notes that bite:

- Android allows **one active VPN** — Tailscale owns it; never put a second VPN app on a node.
- Tags: 50 tagged devices are included on all Tailscale plans; `tag:pua-node` keeps the
  phones out of the user-device bucket.
- Self-hosted alternative: **headscale** speaks the same Android client
  ("Use an alternate server" / "Use an auth key").
- **Revocation is instant**: delete the node (or its node key) in the admin console.
  Prefer that over trying to firewall a phone — stock Termux has no iptables/fail2ban.

ACL (deny-by-default; merge `render/tailscale/grants.json`):

```json
{"grants": [
  {"src": ["tag:pua-controller"], "dst": ["tag:pua-node"], "ip": ["tcp:8022-8071", "tcp:8080-8129"]},
  {"src": ["tag:pua-node"], "dst": ["tag:pua-controller"], "ip": ["tcp:8787"]}
]}
```

Nodes never reach each other, never reach the LAN, and never listen on a public address.

---

## 6. adb-over-TCP resilience

TCP adb drops offline after Wi-Fi roams, Doze, or a DHCP change. Two mechanisms:

**a) Watchdog (controller, always on)** — `farm/adb_watchdog.sh`:

```bash
farm/adb_watchdog.sh                # loop, 30s
farm/adb_watchdog.sh --once         # single pass, exit 1 if any node isn't `device`
INTERVAL=15 DRY_RUN=1 farm/adb_watchdog.sh --once
```

Every pass reads `manifest.json` fresh (edits apply without a restart), computes
`lan_ip:adb_port` per enabled node, and for anything not listed as `device` in
`adb devices` runs `adb connect <host>:<port>`, logging to `farm/logs/<serial>/adb.log`.
`unauthorized` is logged and skipped — reconnecting cannot fix it; the phone must accept
the RSA prompt **over USB once**.

Run it as a service so it survives the controller rebooting:

```bash
# systemd (Linux controller)
cat >/etc/systemd/system/pua-adb-watchdog.service <<'EOF'
[Unit]
Description=phoneuse-agent adb-over-TCP watchdog
After=network-online.target
[Service]
Environment=INTERVAL=30
ExecStart=/opt/phoneuse-agent/farm/adb_watchdog.sh
Restart=always
[Install]
WantedBy=multi-user.target
EOF
systemctl enable --now pua-adb-watchdog

# macOS controller (launchd, every 30s)
# ProgramArguments: farm/adb_watchdog.sh --once   StartInterval: 30
```

**b) Re-arm over USB** — when `adb connect` no longer brings a node back (rebooted
without `adb tcpip` persisting, or the RSA key was cleared), plug it into the USB
provider host and:

```bash
adb -s <serial> tcpip <5555+index>
adb connect <lan_ip>:<5555+index>
```

If the phone doesn't enumerate at all, power-cycle its USB port (§7) before touching it.

Rules that keep this sane:

- **Never rely on `adb reverse` over TCP** — documented broken
  (issuetracker.google.com/issues/37066218). Use sshd/Tailscale for anything that needs a
  reverse tunnel.
- Pin `lan_ip` with a DHCP reservation. A phone that changes IP is an `offline` node until
  someone edits the manifest.
- Expect 10–50 ms/command over LAN vs 5–15 ms over USB — irrelevant for agent tasks,
  decisive for 60 fps streaming (keep streaming on the mesh/controller side).

---

## 7. USB layout & power

The hard numbers (research report §1.5–1.6):

| Limit | Value | Consequence |
|---|---|---|
| USB device addresses per root hub | 127 | not the binding limit |
| Tiers | 7 max (host + root hub = tier 1) | ≤5 chained non-root hubs; a 7-port hub that is really 2×4 chained silently spends a tier |
| **XHCI endpoints per controller** | **~96** (Intel 8-series; some cap at 64) | **the real wall** |
| Endpoints per phone | Pixel 6 = 3, Pixel 9 = 4, Galaxy S8 = 7, S20-class = 11 | modern Pixels are cheapest |
| USB 2.0 bus throughput | 35–40 MB/s | ~50 concurrent 8 Mbps streams saturate a hub *before* endpoints do |

**Phones per controller** = `floor(96 / endpoints_per_phone)`:

| Phone class | ep/phone | per xHCI controller |
|---|---|---|
| Pixel 6/9 | 3–4 | **24–32** |
| Pixel 7 Pro (assumed Pixel-class) | ~4 | ~24 |
| Galaxy S8/S21-class | 7 | ~13 |
| S20-class | 11 | ~8 |

So: **budget 16 phones per xHCI controller** for a mixed fleet (S21 + Pixel), 32 in the
best case (all Pixels). Never plan 32+ on one controller; the research exemplar is
32/controller at 3 endpoints each.

Physical layout rules:

- **Extra PCIe xHCI cards**, not USB3 hub chaining. Linux host (Windows drivers degrade
  badly past a handful of devices).
- **Powered 60 W hubs, 7 phones per hub** — the documented known-good lab used Plugable
  USB 2.0 7-port 60 W hubs, 7 phones/hub, 150 phones across two hosts. 8 hubs for 50 phones.
  60 W ÷ 7 ≈ 8.5 W/port: enough to hold charge on an idle phone, **not** to fast-charge —
  keep screens off and `stay_on_while_plugged_in=3`, and set Samsung "Protect battery 85%".
- **Keep hubs ≤2 levels deep** so every phone lands at tier ≤4 of 7. Skip 7-port hubs that
  are two 4-port chips chained if you can.
- **Label the `usb` block per node** (`hub`/`port`/`controller`) so a power-cycle is a
  lookup, not an archaeology dig.

**Power cycling (remote hard reboot).** Only hubs with per-port VBUS switching support it:

```bash
sudo uhubctl                     # list controllers + per-port switching support
lsusb -v 2>/dev/null | grep wHubCharacteristic   # "Per-port power switching"
uhubctl -a cycle -p 1-1.1 -d 1   # cycle the port from the node's usb.port / usb.uhubctl_device
```

Most hubs do **not** support it (and Raspberry Pi ports are ganged — all-or-nothing).
Known-good hubs: Anker AK-68ANHUB, AmazonBasics HU9002/HU3770, Plugable USB3-HUB7BC,
D-Link DUB-H7 rev D/E, Rosonway RSH-A10/A13.

**USB is not permanent infrastructure for 50 phones.** Two viable patterns:

1. *Bench* (recommended now, 3–10 phones): a 4–7 port powered hub next to the controller,
   used to onboard (APK, `adb tcpip`, RSA key) and to rescue. Phones live on Wi-Fi after.
2. *Permanent rack* (for 50, if you want `uhubctl` hard-reboot on every node): 4 xHCI
   controllers × 16 phones × 8 hubs, all powered, all labelled.

---

## 8. Per-device logs

`farm/logs/<serial>/` is created by the renderer for every node:

```
farm/logs/R58M00000000/
  adb.log      adb_watchdog.sh connect/reconnect decisions
  task.log     task runner stdout/stderr for this node
  agent.log    on-device agent (phone side), shipped back by the controller
  .gitkeep
```

Rules:

- One writer per file. The controller writes `task.log`/`adb.log`; the phone writes
  `agent.log` and it's pulled, not pushed.
- Never a shared `task.log` — the v1 single-file log loses everything the moment two
  nodes run at once.
- Rotate with `logrotate`/`newsyslog` at ~10 MB; phone logs are chatty.
- `farm/.gitignore` keeps `logs/*/` and `render/` out of the repo.

---

## 9. Controller changes (delta from v1)

`~/phonefarm/farm/server.py` (v1, single node) → `farm/server.py` in this repo already
reads `nodes.json`; to go from 1 → 50 the remaining changes are:

| v1 behaviour | Change for N nodes |
|---|---|
| `if f"{s}\tdevice" in adb devices` keyed on USB `serial` | match **both** `serial` and `node["adb_endpoint"]` — a TCP device serial is literally `ip:port` (`connected_serials()` must include the endpoint) |
| single global task slot `_current` | one slot **per serial** (`_current[serial]`), plus a fleet-wide concurrency cap |
| one `task.log` | `farm/logs/<serial>/task.log` per node |
| a11y check hardcodes `mobilerun` / `phoneuse.control` | use `node["a11y_package"]` |
| sshd check hardcodes `0x1F56` (8022) | `hex(node["ssh_port"])` — nodes with index ≥1 listen elsewhere |
| `/api/nodes` returns health only | add the STF-style state (`present/offline/unauthorized/preparing/available/busy`) + `index`, `ssh_port`, `adb_port`, `brain_provider` from the registry |
| `server.py` reads `nodes.json` by hand | read `render/nodes.json` (or copy it to `farm/nodes.json` on deploy) |

Port `8787` stays the controller's own port; `nodes.json` is loaded per request, so
re-rendering and re-deploying needs no restart.

---

## 10. Bring-up runbook (node-03 … node-10)

Per phone, ~6 minutes once USB is attached:

```bash
# 1. slot it in the manifest (append — never renumber)
#    index 2 → node-03, ssh 8024, adb 5557, portal 8082
$EDITOR farm/manifest.json
python3 farm/render_manifest.py --controller <controller-mesh-ip> --check

# 2. USB: identity, APK, adb-over-TCP, RSA key
adb devices -l                       # grab the serial
adb -s <serial> install -r android/pua-control.apk   # or ./gradlew installDebug
adb -s <serial> shell "ip -f inet addr show wlan0"   # → lan_ip into the manifest, re-render
adb -s <serial> tcpip <5555+index>
adb connect <lan_ip>:<5555+index>
adb -s <lan_ip>:<5555+index> shell getprop ro.product.model   # sanity

# 3. build Termux: sshd (key-only) + Termux:Boot + wake-lock, port <8022+index>
scp farm/render/apply/<serial>.sh <lan_ip>:/sdcard/Download/   # or via tailscale once enrolled
#    on device: termux-open, then run it; it installs env + sshd config + a11y

# 4. mesh
export TS_AUTHKEY=…                  # reusable, tagged tag:pua-node
#    Tailscale app → Use an auth key → rename to pua-node-NN; record tailscale_ip

# 5. verify
ssh -p <8022+index> <tailscale_hostname> 'cat ~/.pua/env/<serial>.env'
farm/adb_watchdog.sh --once          # exit 0 when every enabled node is `device`
curl -s localhost:8787/api/nodes | python3 -m json.tool
```

Definition of done for a node: **`adb_endpoint` reaches `adb connect` over the LAN, sshd
answers on `<8022+index>` over Tailscale, the a11y service is listed in
`settings get secure enabled_accessibility_services`, and the watchdog's `--once` pass
exits 0.**

---

## 11. 50-node capacity plan

| Resource | Need at 50 | Note |
|---|---|---|
| Controller(s) | 1 × 16-core/32 GB, 1 GbE | ~0.1–0.3 core per 720p scrcpy stream → serialize heavy streaming; the agent workload itself is light |
| PCIe xHCI controllers | 4 (16 phones each, mixed fleet) | 2 if the fleet is all Pixels and you accept 24/controller |
| Powered 60 W hubs | 8 (7 phones/hub) | only if keeping USB permanent; a bench hub suffices if not |
| Power | ~8.5 W/phone from the hub (50 phones ≈ 425 W) | thermal: expect S21/Pixel-class throttling under sustained load — spread the load |
| Tailscale | 50 tagged devices | within plan limits |
| Ports | 8022–8071, 5555–5604, 8080–8129 | no overlap |
| Manifest rows | ≤50 enforced by schema + validator | node-51 is rejected |

At 3–10 phones (this week): one controller, one 7-port 60 W hub, manifest rows for each,
watchdog in `--once` mode on a timer. Nothing else changes at 50 except USB controllers
and hub count.

---

## 12. Failure states

| State | Detection | Action |
|---|---|---|
| `present` (USB) but not network | `adb devices` shows the serial, no `adb_endpoint` | re-arm `adb tcpip` + `adb connect` |
| `offline` | watchdog: `adb connect` fails, no ping on mesh | uhubctl power-cycle → re-arm. If it recurs, suspect the hub tier/endpoints, not the phone |
| `unauthorized` | `adb devices` shows `unauthorized` | USB once, accept the RSA prompt (`adb keys` on the controller) |
| `no-a11y` | `settings get secure enabled_accessibility_services` missing `a11y_package` | re-run `apply/<serial>.sh`; some OEMs reset this after an update |
| `no-sshd` | mesh port `<8022+index>` closed | `apply/<serial>.sh` (termux-services restart), then Termux:Boot re-registration if it survives reboot badly |
| `busy` | task slot for that serial | queue or 409, never a second writer |
| `absent` | serial gone from `adb devices` *and* unreachable on mesh | phone rebooted or lost the auth key — bench it |

Termux realities (report §5) that produce these states: `BOOT_COMPLETED` is not delivered
before first unlock (the phone must be unlocked once after every boot), the phantom-process
killer kills daemons on Android 12+ unless explicitly disabled, and `termux-wake-lock` is
necessary but not sufficient. Hence: the **off-device watchdog is the real supervisor** —
never trust a phone to keep its own agent alive.

---

## 13. Open items

- `wa_account` has no verified WhatsApp enrollment path yet — the field exists, the
  automation (multi-account WhatsApp on N phones) does not.
- No automated device-state cache: the controller re-polls `adb devices` per request.
  Fine to ~20 nodes; add a polling loop + cache before 50.
- scrcpy fan-out is documented (report §2) but not wired into `server.py` — it is a
  controller-side concern, one process per phone pinned with `-s <adb_endpoint>`.
- `brain_provider` is metadata only; the runner still uses one mobilerun configuration.
  Per-node routing needs a dispatch layer.
