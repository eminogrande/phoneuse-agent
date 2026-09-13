#!/usr/bin/env bash
# farm/adb_watchdog.sh — keep adb-over-TCP alive for every enabled manifest node.
#
#   every INTERVAL (default 30s): for each node in farm/manifest.json compute
#   <lan_ip|adb_host>:<adb_port>; if `adb devices` does not list it as `device`,
#   run `adb connect <host>:<port>`. Offline/unauthorized entries are re-connected
#   too (connect is a no-op when already connected).
#
# Usage:
#   farm/adb_watchdog.sh                 # loop forever, 30s interval
#   farm/adb_watchdog.sh --once          # single pass (cron / launchd / systemd timer)
#   INTERVAL=15 farm/adb_watchdog.sh     # override interval
#   PUA_MANIFEST=/path/manifest.json farm/adb_watchdog.sh
#   DRY_RUN=1 farm/adb_watchdog.sh --once
#
# Exit 0 always in loop mode; with --once exits 1 if any enabled node is not `device`.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="${PUA_MANIFEST:-$HERE/manifest.json}"
LOG_ROOT="${PUA_LOG_ROOT:-$HERE/logs}"
INTERVAL="${INTERVAL:-${PUA_WATCHDOG_INTERVAL:-30}}"
ADB="${ADB:-adb}"
DRY_RUN="${DRY_RUN:-0}"

ONCE=0
[ "${1:-}" = "--once" ] && ONCE=1

command -v "$ADB" >/dev/null 2>&1 || { echo "adb not found (set ADB=)" >&2; exit 2; }
[ -f "$MANIFEST" ] || { echo "manifest not found: $MANIFEST" >&2; exit 2; }

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# Print TAB-separated: host:port <TAB> serial <TAB> index
targets() {
  python3 - "$MANIFEST" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
for n in m.get("nodes", []):
    if n.get("enabled", True) is False:
        continue
    idx = int(n.get("index", 0))
    host = n.get("lan_ip") or ""
    if not host:
        ep = n.get("adb_endpoint") or ""
        host = ep.rsplit(":", 1)[0] if ":" in ep else ""
    if not host:
        continue
    port = int(n.get("adb_port", 5555 + idx))
    print("%s:%d\t%s\t%d" % (host, port, n.get("serial", "?"), idx))
PY
}

log() { # log <serial> <message>
  local serial="$1"; shift
  local dir="$LOG_ROOT/$serial"
  mkdir -p "$dir"
  printf '%s %s\n' "$(ts)" "$*" >> "$dir/adb.log"
}

pass() {
  local rc=0
  local state; state="$("$ADB" devices | tr -d '\r')"
  while IFS=$'\t' read -r endpoint serial _idx; do
    [ -n "${endpoint:-}" ] || continue
    local line
    line="$(printf '%s\n' "$state" | awk -F'\t' -v e="$endpoint" '$1==e {print $2; exit}')"
    if [ "$line" = "device" ]; then
      continue
    fi
    rc=1
    if [ "$DRY_RUN" = "1" ]; then
      echo "[dry-run] adb connect $endpoint  (serial=$serial state=${line:-absent})"
      log "$serial" "would reconnect $endpoint state=${line:-absent}"
      continue
    fi
    if [ "$line" = "unauthorized" ]; then
      # connect cannot fix this: the phone must accept the RSA prompt (USB once).
      log "$serial" "SKIP $endpoint unauthorized — accept the RSA prompt on the device"
      continue
    fi
    local out
    out="$("$ADB" connect "$endpoint" 2>&1 | tr -d '\r')"
    log "$serial" "connect $endpoint state=${line:-absent} -> $out"
    echo "$(ts) $serial $endpoint ${line:-absent} -> $out"
  done < <(targets)
  return $rc
}

if [ "$ONCE" = "1" ]; then
  pass
  exit $?
fi

echo "$(ts) adb_watchdog start manifest=$MANIFEST interval=${INTERVAL}s manifest_hash=$(shasum -a 256 "$MANIFEST" | awk '{print $1}')"
trap 'echo "$(ts) adb_watchdog stop"; exit 0' INT TERM
while :; do
  pass || true
  sleep "$INTERVAL"
done
