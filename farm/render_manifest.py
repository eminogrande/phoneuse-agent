#!/usr/bin/env python3
"""Render farm/manifest.json into on-device env files + controller registry.

One source of truth (manifest.json) -> three artifacts:

    farm/render/env/<serial>.env          per-device env, pushed to the phone
    farm/render/ssh/<serial>.sshd_config  Termux sshd override (port, key-only)
    farm/render/apply/<serial>.sh         idempotent on-device apply script
    farm/render/nodes.json                controller registry (phonefarm server.py shape)
    farm/render/adb_targets.txt           host:port list for the watchdog / tooling
    farm/render/tailscale/enroll.sh       reusable auth-key enrollment for the whole fleet
    farm/render/tailscale/grants.json     ACL snippet: tag:pua-controller -> tag:pua-node

Also creates farm/logs/<serial>/ (per-device log root).

Stdlib only. `jsonschema` is used for full schema validation when installed.

Usage:
    python3 farm/render_manifest.py                      # render everything
    python3 farm/render_manifest.py --check              # validate only, write nothing
    python3 farm/render_manifest.py --controller 100.64.0.1
    python3 farm/render_manifest.py --manifest farm/manifest.json --out farm/render
Exit: 0 ok, 1 validation error, 2 usage/IO error.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import sys
from pathlib import Path

FARM = Path(__file__).resolve().parent
DEFAULT_MANIFEST = FARM / "manifest.json"
DEFAULT_SCHEMA = FARM / "manifest.schema.json"
DEFAULT_OUT = FARM / "render"
LOG_ROOT = FARM / "logs"

BASE = {"sshd": 8022, "adb": 5555, "portal": 8080}
MAX_NODES = 50
RE_SERIAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_.-]*$")
RE_NAME = re.compile(r"^node-\d{2,3}$")
RE_E164 = re.compile(r"^\+[1-9]\d{6,14}$")
RE_IPV4 = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")
RE_A11Y = re.compile(r"^[A-Za-z0-9_.]+/[A-Za-z0-9_.]+$")
RE_TS_HOST = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")

# Termux paths (device side).
TERMUX_HOME = "/data/data/com.termux/files/home"
PUA_DIR = f"{TERMUX_HOME}/.pua"


# ---------------------------------------------------------------- load / validate

def load_manifest(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        sys.exit(f"error: manifest not found: {path}")
    except json.JSONDecodeError as e:
        sys.exit(f"error: manifest is not valid JSON: {e}")


def with_defaults(manifest: dict) -> dict:
    """Copy of the manifest with `defaults` merged into every node.

    Schema validation runs on this so a node may inherit a11y_package /
    brain_provider / admin_number from `defaults` instead of repeating them.
    """
    defaults = manifest.get("defaults") or {}
    out = dict(manifest)
    out["nodes"] = [({**defaults, **n}) for n in manifest.get("nodes", [])]
    return out


def schema_validate(manifest: dict, schema_path: Path) -> list[str]:
    """Use jsonschema when available; otherwise run the built-in checks below."""
    if not schema_path.exists():
        return []
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return []
    schema = json.loads(schema_path.read_text())
    validator = jsonschema.Draft202012Validator(schema)
    errs = []
    for e in sorted(validator.iter_errors(manifest), key=lambda e: list(e.path)):
        loc = "/".join(str(p) for p in e.path) or "<root>"
        msg = e.message if len(e.message) <= 200 else e.message[:197] + "..."
        errs.append(f"{loc}: {msg}")
    return errs


def semantic_validate(manifest: dict) -> tuple[list[str], list[str]]:
    """Returns (errors, warnings). Runs even when jsonschema is absent."""
    errs: list[str] = []
    warns: list[str] = []

    if manifest.get("version") != 1:
        errs.append("version: must be 1")
    nodes = manifest.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        errs.append("nodes: must be a non-empty array")
        return errs, warns
    if len(nodes) > MAX_NODES:
        errs.append(f"nodes: {len(nodes)} > {MAX_NODES} (fleet cap)")

    base = {**BASE, **(manifest.get("port_base") or {})}
    defaults = manifest.get("defaults") or {}
    seen: dict[str, list] = {"serial": [], "name": [], "index": [], "ts": [],
                             "ssh": [], "adb": [], "portal": []}

    for i, n in enumerate(nodes):
        where = n.get("name") or n.get("serial") or f"nodes[{i}]"
        for field in ("serial", "name", "tailscale_hostname", "a11y_package",
                      "admin_number", "brain_provider"):
            if not n.get(field) and not defaults.get(field):
                errs.append(f"{where}: missing required field '{field}'")
        idx = n.get("index", i)
        if not isinstance(idx, int) or idx < 0 or idx >= MAX_NODES:
            errs.append(f"{where}: index must be an int in 0..{MAX_NODES - 1}")
            continue
        if n.get("name") and not RE_NAME.match(n["name"]):
            errs.append(f"{where}: name must look like node-01")
        if n.get("name") and n["name"] != f"node-{idx + 1:02d}":
            warns.append(f"{where}: name does not match index {idx} (expected node-{idx + 1:02d})")
        if n.get("serial") and not RE_SERIAL.match(n["serial"]):
            errs.append(f"{where}: serial has illegal characters")
        if n.get("tailscale_hostname") and not RE_TS_HOST.match(n["tailscale_hostname"]):
            errs.append(f"{where}: tailscale_hostname must be a lowercase DNS label")
        a11y = n.get("a11y_package") or defaults.get("a11y_package", "")
        if a11y and not RE_A11Y.match(a11y):
            errs.append(f"{where}: a11y_package must be 'package/class'")
        num = n.get("admin_number") or defaults.get("admin_number", "")
        if num and not RE_E164.match(num):
            errs.append(f"{where}: admin_number must be E.164 (+<cc><number>)")
        for ipf in ("lan_ip", "tailscale_ip"):
            if n.get(ipf) and not RE_IPV4.match(n[ipf]):
                errs.append(f"{where}: {ipf} is not an IPv4 address")
        if not n.get("lan_ip") and not n.get("adb_endpoint"):
            warns.append(f"{where}: no lan_ip / adb_endpoint — watchdog cannot reach it")
        if n.get("lan_ip") in ("192.168.1.0", "127.0.0.1", "0.0.0.0"):
            errs.append(f"{where}: lan_ip {n['lan_ip']} is a placeholder address")

        ssh_p = n.get("ssh_port", base["sshd"] + idx)
        adb_p = n.get("adb_port", base["adb"] + idx)
        prt_p = n.get("portal_port", base["portal"] + idx)
        if n.get("ssh_port") and n["ssh_port"] != base["sshd"] + idx:
            warns.append(f"{where}: ssh_port {ssh_p} deviates from base+index "
                         f"({base['sshd'] + idx})")
        if len({ssh_p, adb_p, prt_p}) != 3:
            errs.append(f"{where}: derived ports collide ({ssh_p}/{adb_p}/{prt_p})")

        seen["serial"].append(n.get("serial"))
        seen["name"].append(n.get("name"))
        seen["index"].append(idx)
        seen["ts"].append(n.get("tailscale_hostname"))
        seen["ssh"].append(ssh_p)
        seen["adb"].append(adb_p)
        seen["portal"].append(prt_p)

    for key, label in (("serial", "serial"), ("name", "name"), ("index", "index"),
                       ("ts", "tailscale_hostname"), ("ssh", "ssh_port"),
                       ("adb", "adb_port"), ("portal", "portal_port")):
        vals = [v for v in seen[key] if v is not None]
        dupes = sorted({v for v in vals if vals.count(v) > 1})
        if dupes:
            errs.append(f"duplicate {label}: {dupes}")

    used = sorted(i for i in seen["index"] if isinstance(i, int))
    if used and used != list(range(len(used))):
        warns.append(f"index is not contiguous 0..{len(used) - 1}: {used} "
                     "(append-only is fine, gaps waste ports)")

    ranges = [("ssh", base["sshd"], seen["ssh"]),
              ("adb", base["adb"], seen["adb"]),
              ("portal", base["portal"], seen["portal"])]
    for name, _base, vals in ranges:
        for p in vals:
            if isinstance(p, int) and not (1024 <= p <= 65535):
                errs.append(f"{name}: port {p} outside 1024..65535")
    r = {n: (min(v) if v else 0, max(v) if v else 0) for n, _, v in ranges}
    if r["ssh"][1] >= r["portal"][0]:
        warns.append("sshd and portal port ranges overlap; widen the bases")
    return errs, warns


# ---------------------------------------------------------------- render helpers

def resolve(node: dict, defaults: dict) -> dict:
    """Fill defaults + derived ports into a copy of the node."""
    n = dict(node)
    for k, v in defaults.items():
        n.setdefault(k, v)
    idx = int(n["index"])
    n["ssh_port"] = int(n.get("ssh_port", BASE["sshd"] + idx))
    n["adb_port"] = int(n.get("adb_port", BASE["adb"] + idx))
    n["portal_port"] = int(n.get("portal_port", BASE["portal"] + idx))
    return n


def adb_host(node: dict) -> str:
    if node.get("lan_ip"):
        return node["lan_ip"]
    ep = node.get("adb_endpoint") or ""
    return ep.rsplit(":", 1)[0] if ":" in ep else ""


def env_q(v) -> str:
    """Shell-quote for a `set -a; . file` env file."""
    return "" if v is None else shlex.quote(str(v))


def render_env(n: dict, controller: str) -> str:
    host = adb_host(n)
    endpoint = f"{host}:{n['adb_port']}" if host else ""
    lines = [
        "# generated by farm/render_manifest.py from farm/manifest.json — do not edit",
        f"PUA_INDEX={n['index']}",
        f"PUA_NAME={n['name']}",
        f"PUA_SERIAL={n['serial']}",
        f"PUA_MODEL={env_q(n.get('model', ''))}",
        f"PUA_SSH_PORT={n['ssh_port']}",
        f"PUA_PORTAL_PORT={n['portal_port']}",
        f"PUA_ADB_PORT={n['adb_port']}",
        f"PUA_A11Y_PACKAGE={n['a11y_package']}",
        f"PUA_ADMIN_NUMBER={n['admin_number']}",
        f"PUA_BRAIN_PROVIDER={n['brain_provider']}",
        f"PUA_WA_ACCOUNT={env_q(n.get('wa_account') or '')}",
        f"PUA_TS_HOSTNAME={n['tailscale_hostname']}",
        f"PUA_CONTROLLER={env_q(controller)}",
        f"PUA_ADB_ENDPOINT={env_q(endpoint)}",
        f"PUA_LOG_DIR={PUA_DIR}/logs",
    ]
    return "\n".join(lines) + "\n"


def render_sshd_config(n: dict) -> str:
    return f"""# generated for {n['name']} ({n['serial']}) — do not edit
Port {n['ssh_port']}
PasswordAuthentication no
PubkeyAuthentication yes
PermitRootLogin no
AllowTcpForwarding yes
GatewayPorts no
"""


APPLY_TEMPLATE = """#!/data/data/com.termux/files/usr/bin/sh
# generated by farm/render_manifest.py — idempotent on-device apply for @NAME@.
# Run: scp this file to the phone, then
#      ssh -p @SSH_PORT@ @TS_HOST@ 'sh ~/apply-@SERIAL@.sh'
set -eu
PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
HOME_DIR="${HOME:-/data/data/com.termux/files/home}"
mkdir -p "$HOME_DIR/.pua/logs" "$HOME_DIR/.pua/env"
cat > "$HOME_DIR/.pua/env/@SERIAL@.env" <<'PUA_ENV'
@ENV@
PUA_ENV

# sshd: port + key-only. Back up once, then idempotent overwrite.
CFG="$PREFIX/etc/ssh/sshd_config"
[ -f "$CFG.pua.bak" ] || cp "$CFG" "$CFG.pua.bak" 2>/dev/null || true
cat > "$CFG" <<'PUA_SSHD'
@SSHD@
PUA_SSHD

# grant the a11y service (idempotent; needs the shell user, i.e. adb or Termux)
# match on the package name so both the short (pkg/.Class) and normalised
# (pkg/full.Class) forms already present in Settings are recognised.
CUR="$(settings get secure enabled_accessibility_services 2>/dev/null || echo none)"
if ! printf '%s' "$CUR" | grep -q '@A11Y_PKG@'; then
  if [ "$CUR" = "none" ] || [ -z "$CUR" ]; then
    settings put secure enabled_accessibility_services '@A11Y@' 2>/dev/null \\
      || echo "WARN: enable the a11y service manually on this device"
  else
    settings put secure enabled_accessibility_services "$CUR:@A11Y@" 2>/dev/null \\
      || echo "WARN: enable the a11y service manually on this device"
  fi
fi
settings put secure accessibility_enabled 1 2>/dev/null || true

# keep the CPU awake, stop Wi-Fi sleeping (best effort, no root)
termux-wake-lock 2>/dev/null || true
settings put global wifi_sleep_policy 2 2>/dev/null || true

# restart sshd under termux-services when present, else run it directly
if command -v sv >/dev/null 2>&1; then
  sv-enable sshd 2>/dev/null || true
  sv restart sshd 2>/dev/null || true
else
  pkill -f sshd 2>/dev/null || true
  sshd
fi
echo "applied @NAME@ ssh_port=@SSH_PORT@ env=$HOME_DIR/.pua/env/@SERIAL@.env"
"""


def render_apply(n: dict, env_text: str, sshd_text: str) -> str:
    out = APPLY_TEMPLATE
    for token, value in (
        ("@NAME@", n["name"]),
        ("@SERIAL@", n["serial"]),
        ("@SSH_PORT@", str(n["ssh_port"])),
        ("@TS_HOST@", n["tailscale_hostname"]),
        ("@A11Y@", n["a11y_package"]),
        ("@A11Y_PKG@", n["a11y_package"].split("/", 1)[0]),
        ("@ENV@", env_text.rstrip("\n")),
        ("@SSHD@", sshd_text.rstrip("\n")),
    ):
        out = out.replace(token, value)
    return out


def nodes_json(manifest: dict, resolved: list[dict], controller: str) -> list[dict]:
    out = []
    for n in resolved:
        host = adb_host(n)
        out.append({
            "index": n["index"],
            "serial": n["serial"],
            "name": n["name"],
            "role": n.get("role", "agent+vps"),
            "model": n.get("model", ""),
            "enabled": n.get("enabled", True),
            "ssh_port": n["ssh_port"],
            "adb_port": n["adb_port"],
            "portal_port": n["portal_port"],
            "adb_endpoint": f"{host}:{n['adb_port']}" if host else None,
            "tailscale_hostname": n["tailscale_hostname"],
            "tailscale_ip": n.get("tailscale_ip"),
            "a11y_package": n["a11y_package"],
            "admin_number": n["admin_number"],
            "brain_provider": n["brain_provider"],
            "wa_account": n.get("wa_account"),
            "usb": n.get("usb", {}),
            "controller": controller,
            "log_dir": f"farm/logs/{n['serial']}/",
        })
    return out


def render_tailscale(nodes: list[dict]) -> tuple[str, str]:
    enroll = """#!/usr/bin/env bash
# generated by farm/render_manifest.py — enroll every phone onto the tailnet.
#
# One REUSABLE, pre-authorized auth key tagged tag:pua-node covers the whole fleet.
# Android has no tailscale CLI: the phone-side step is the Tailscale app's
# "Use an auth key" screen (or drive it with phoneuse-agent). The controller-side
# step below is `ssh` into any Linux provider host, or run on the controller.
set -euo pipefail
: "${TS_AUTHKEY:?export TS_AUTHKEY=tskey-auth-... (reusable, tag:pua-node)}"
TAG="${TS_TAG:-tag:pua-node}"

# 1. mint the reusable key once (admin API; run on the controller):
#    TAILNET=your-tailnet TS_API_KEY=tskey-api-... sh farm/render/tailscale/mint_key.sh
# 2. verify the key is reusable + pre-authorized + tagged in the admin console.
# 3. on each phone: Tailscale app -> Sign in -> "Use an auth key" -> paste TS_AUTHKEY.
#    The phone then appears as its Android hostname; rename it to the manifest value:
"""
    for n in nodes:
        enroll += (f'#    {n["serial"]}: tailscale_hostname={n["tailscale_hostname"]} '
                   f"-> {n['tailscale_hostname']}\n")
    enroll += """#
# 4. after the phone joins, record its mesh IP back into the manifest:
#    tailscale status | awk '/pua-node-/ {print $1, $2}'
#
# Re-arm core/VM (if a node is ever a Linux box, e.g. a provider host):
#    tailscale up --authkey="$TS_AUTHKEY" --advertise-tags="$TAG" --hostname=<name>
#
# Revocation: delete the node in the tailnet -> instant. Keys expire 1-90d (default 90).
"""

    grants = {
        "_comment": "ACL/grants snippet: controller may SSH/adb to nodes; nodes may reach "
                    "nothing else. Merge into the tailnet policy file.",
        "tagOwners": {"tag:pua-node": ["autogroup:admin"], "tag:pua-controller": ["autogroup:admin"]},
        "grants": [
            {"src": ["tag:pua-controller"], "dst": ["tag:pua-node"], "ip": ["tcp:8022-8071", "tcp:8080-8129"]},
            {"src": ["tag:pua-node"], "dst": ["tag:pua-controller"], "ip": ["tcp:8787"]},
        ],
        "ssh": [
            {"action": "accept", "src": ["tag:pua-controller"], "dst": ["tag:pua-node"], "users": ["termux"]}
        ],
    }
    return enroll, json.dumps(grants, indent=2) + "\n"


def mint_key_script() -> str:
    return """#!/usr/bin/env bash
# generated by farm/render_manifest.py — mint ONE reusable, pre-authorized,
# tagged auth key for the whole phoneuse-agent fleet.
set -euo pipefail
: "${TS_API_KEY:?export TS_API_KEY=tskey-api-... (Tailscale admin key, Settings>Keys)}"
TAILNET="${TAILNET:--}"          # '-' = the tailnet the API key belongs to
TAG="${TS_TAG:-tag:pua-node}"
curl -fsS -u "$TS_API_KEY:" \\
  -X POST "https://api.tailscale.com/api/v2/tailnet/$TAILNET/keys" \\
  -H 'Content-Type: application/json' \\
  -d "{\\"capabilities\\":{\\"devices\\":{\\"create\\":{\\"reusable\\":true,\\"ephemeral\\":false,\\"preauthorized\\":true,\\"tags\\":[\\"$TAG\\"]}}},\\"expirySeconds\\":7776000}"
echo
"""


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--controller", default="",
                    help="controller mesh IP/hostname rendered into each env file")
    ap.add_argument("--check", action="store_true", help="validate only, write nothing")
    args = ap.parse_args()

    manifest = load_manifest(args.manifest)
    errs = schema_validate(with_defaults(manifest), args.schema)
    sem_errs, warns = semantic_validate(manifest)
    errs += sem_errs

    for w in warns:
        print(f"warn:  {w}")
    for e in errs:
        print(f"ERROR: {e}")
    if errs:
        print(f"\n{len(errs)} error(s) — nothing rendered.")
        return 1
    print(f"ok: manifest valid ({len(manifest['nodes'])} node(s), "
          f"{len(warns)} warning(s))")
    if args.check:
        return 0

    controller = args.controller or "100.64.0.1"
    defaults = manifest.get("defaults") or {}
    resolved = [resolve(n, defaults) for n in manifest["nodes"]]

    if args.out.exists():
        shutil.rmtree(args.out)
    (args.out / "env").mkdir(parents=True)
    (args.out / "ssh").mkdir(parents=True)
    (args.out / "apply").mkdir(parents=True)
    (args.out / "tailscale").mkdir(parents=True)

    for n in resolved:
        env_text = render_env(n, controller)
        sshd_text = render_sshd_config(n)
        (args.out / "env" / f"{n['serial']}.env").write_text(env_text)
        (args.out / "ssh" / f"{n['serial']}.sshd_config").write_text(sshd_text)
        apply_p = args.out / "apply" / f"{n['serial']}.sh"
        apply_p.write_text(render_apply(n, env_text, sshd_text))
        apply_p.chmod(0o755)
        (LOG_ROOT / n["serial"]).mkdir(parents=True, exist_ok=True)
        (LOG_ROOT / n["serial"] / ".gitkeep").touch()

    registry = nodes_json(manifest, resolved, controller)
    (args.out / "nodes.json").write_text(json.dumps(registry, indent=2) + "\n")

    (args.out / "adb_targets.txt").write_text(
        "".join(f"{n['adb_endpoint']}\t{n['serial']}\t{n['index']}\n"
                for n in registry if n["adb_endpoint"]))

    enroll, grants = render_tailscale(registry)
    (args.out / "tailscale" / "enroll.sh").write_text(enroll)
    (args.out / "tailscale" / "enroll.sh").chmod(0o755)
    (args.out / "tailscale" / "grants.json").write_text(grants)
    (args.out / "tailscale" / "mint_key.sh").write_text(mint_key_script())
    (args.out / "tailscale" / "mint_key.sh").chmod(0o755)

    summary = {
        "generated_from": str(args.manifest),
        "controller": controller,
        "nodes": len(registry),
        "port_map": {n["name"]: {"ssh": n["ssh_port"], "adb": n["adb_port"],
                                 "portal": n["portal_port"]} for n in registry},
    }
    (args.out / "index.json").write_text(json.dumps(summary, indent=2) + "\n")

    print(f"rendered {len(registry)} node(s) -> {args.out}")
    print(f"  {args.out}/nodes.json")
    print(f"  {args.out}/env/<serial>.env           ({len(registry)} files)")
    print(f"  {args.out}/apply/<serial>.sh          ({len(registry)} files)")
    print(f"  {args.out}/tailscale/{{mint_key,enroll}}.sh, grants.json")
    print(f"  {LOG_ROOT}/<serial>/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
