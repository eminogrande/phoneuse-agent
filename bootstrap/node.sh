#!/usr/bin/env bash
# phoneuse-agent — idempotent adb bootstrap for one Android phone node.
#
#   adb plug phone  ->  ./bootstrap/node.sh  ->  node online
#
# Turns a stock (non-rooted) Android phone into an AI-operable agent node:
#   * Termux VPS        — key-only sshd on :8022, Termux:Boot, wake lock
#   * system hardening  — phantom-process killer off, wifi sleep off, stay-awake, doze whitelist
#   * control channel   — PUA accessibility service (broadcast-driven dump/click/type/launch)
#
# Safe to re-run. Requires: adb (platform-tools), ssh-keygen, curl.
# The PUA control APK needs gradle + JDK 17 + an Android SDK (ANDROID_HOME) to build,
# or point PUA_APK at a prebuilt app-debug.apk. Everything else runs without them.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ADB="${ADB:-adb}"
STAGE=/sdcard/phoneuse
APK_CACHE="$ROOT/bootstrap/apks"
KEY="$ROOT/keys/node_ed25519"

TERMUX_PKG=com.termux
TERMUX_BOOT_PKG=com.termux.boot
TERMUX_BASH=/data/data/com.termux/files/usr/bin/bash
CTRL_APK_SRC="$ROOT/android/pua-control/app/build/outputs/apk/debug/app-debug.apk"
CTRL_PKG=com.phoneuse.control

log()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

dev() { "$ADB" -s "$SERIAL" "$@"; }

require_adb() {
  command -v "$ADB" >/dev/null 2>&1 || die "adb not found — install Android platform-tools."
  command -v ssh-keygen >/dev/null 2>&1 || die "ssh-keygen not found."
}

pick_serial() {
  if [ -n "${ANDROID_SERIAL:-}" ]; then SERIAL="$ANDROID_SERIAL"; return 0; fi
  local out n
  out="$("$ADB" devices | awk 'NR>1 && $2=="device"{print $1}')"
  n="$(printf '%s\n' "$out" | grep -c . || true)"
  if [ "$n" -eq 0 ]; then
    if "$ADB" devices | grep -q unauthorized; then
      die "device unauthorized — accept the USB-debugging prompt on the phone (or: adb kill-server && adb start-server)."
    fi
    die "no adb device — plug the phone in over USB and enable USB debugging."
  fi
  if [ "$n" -gt 1 ]; then
    warn "multiple devices; using the first — set ANDROID_SERIAL to choose."
  fi
  SERIAL="$(printf '%s\n' "$out" | head -1)"
}

pkg_installed() { dev shell pm list packages 2>/dev/null | grep -qx "package:$1"; }

# Download + cache an F-Droid APK using the package's suggested version code.
fdroid_apk() { # <pkg> <dest>
  local pkg="$1" dest="$2" ver
  if [ -f "$dest" ]; then printf '%s' "$dest"; return 0; fi
  ver="$(curl -fsSL "https://f-droid.org/api/v1/packages/$pkg" \
        | grep -oE '"suggestedVersionCode":[0-9]+' | grep -oE '[0-9]+' | head -1)"
  [ -n "$ver" ] || die "could not resolve $pkg version from F-Droid."
  curl -fsSL --retry 3 "https://f-droid.org/repo/${pkg}_${ver}.apk" -o "$dest"
  printf '%s' "$dest"
}

install_termux() {
  if pkg_installed "$TERMUX_PKG"; then
    log "Termux already installed"
    return 0
  fi
  mkdir -p "$APK_CACHE"
  local apk="${TERMUX_APK:-$APK_CACHE/com.termux.apk}"
  log "fetching Termux (F-Droid)"
  apk="$(fdroid_apk "$TERMUX_PKG" "$apk")"
  log "installing Termux"
  dev install -r "$apk" >/dev/null
}

install_termux_boot() {
  if pkg_installed "$TERMUX_BOOT_PKG"; then
    log "Termux:Boot already installed"
  else
    mkdir -p "$APK_CACHE"
    local apk="${TERMUX_BOOT_APK:-$APK_CACHE/com.termux.boot.apk}"
    log "fetching Termux:Boot (F-Droid)"
    apk="$(fdroid_apk "$TERMUX_BOOT_PKG" "$apk")"
    log "installing Termux:Boot — if Android blocks it (Play Protect), tap"
    log "  \"More details\" -> \"Install anyway\" + biometric confirm on the phone."
    dev install -r "$apk" >/dev/null || warn "Termux:Boot install blocked — enable the a11y/persistence manually."
  fi
  # Termux:Boot only receives BOOT_COMPLETED after its UI has been opened once.
  dev shell monkey -p "$TERMUX_BOOT_PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
}

grant_storage() {
  log "granting storage to Termux"
  dev shell appops set "$TERMUX_PKG" MANAGE_EXTERNAL_STORAGE allow >/dev/null 2>&1 || true
  dev shell pm grant "$TERMUX_PKG" android.permission.WRITE_EXTERNAL_STORAGE >/dev/null 2>&1 || true
}

wait_for_termux() {
  log "first Termux launch — laying down its package bootstrap (this takes a minute)"
  dev shell monkey -p "$TERMUX_PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
  local i
  for i in $(seq 1 60); do
    if dev shell "run-as $TERMUX_PKG test -x $TERMUX_BASH && echo READY" 2>/dev/null | grep -q READY; then
      return 0
    fi
    sleep 2
  done
  return 1
}

# Run a command inside Termux's bash, non-interactively (headless). Works because
# the F-Droid Termux build is debuggable, so `run-as` is permitted.
termux_exec() { # <command-string>
  dev shell "run-as $TERMUX_PKG $TERMUX_BASH -lc '$1'"
}

# Fallback: type the command into the Termux terminal UI.
# TRAP: `input text` treats %s as a space; every other %XX hex escape is typed
# LITERALLY (e.g. %20 lands as the four characters "%20"). Keep the typed command
# free of special characters and put any shell redirection INSIDE the script.
ui_type() { # <command-string containing spaces>
  dev shell input text "$(printf '%s' "$1" | sed 's/ /%s/g')"
  dev shell input keyevent 66
}

run_setup() {
  log "pushing bootstrap files"
  dev shell mkdir -p "$STAGE"
  dev push "$ROOT/bootstrap/termux-setup.sh" "$STAGE/termux-setup.sh" >/dev/null
  dev push "$KEY.pub" "$STAGE/authorized_keys" >/dev/null

  log "running on-phone setup (Termux packages, sshd, boot script)"
  if termux_exec "sh $STAGE/termux-setup.sh"; then
    :
  else
    warn "run-as failed — falling back to driving the Termux UI"
    ui_type "sh $STAGE/termux-setup.sh"
    log "waiting for setup to finish (up to ~10 min for the first pkg upgrade)…"
    local i
    for i in $(seq 1 120); do
      dev shell "grep -q BOOTSTRAP_DONE $STAGE/termux_bootstrap.status" 2>/dev/null && break
      sleep 5
    done
  fi
  dev pull "$STAGE/setup.log" "$ROOT/bootstrap/setup.log" >/dev/null 2>&1 \
    && log "on-phone setup log -> bootstrap/setup.log" || true
}

system_settings() {
  log "system hardening (phantom killer, wifi sleep, stay awake, doze whitelist)"
  dev shell settings put global settings_enable_monitor_phantom_procs false || true
  dev shell device_config put activity_manager max_phantom_processes 2147483647 || true
  dev shell settings put global wifi_sleep_policy 2 || true
  dev shell settings put global stay_on_while_plugged_in 3 || true
  dev shell "dumpsys deviceidle whitelist +$TERMUX_PKG" >/dev/null 2>&1 || true
}

install_control() {
  local apk="${PUA_APK:-}"
  if [ -z "$apk" ] && [ -f "$CTRL_APK_SRC" ]; then apk="$CTRL_APK_SRC"; fi
  if [ -z "$apk" ] && command -v gradle >/dev/null 2>&1 && [ -n "${ANDROID_HOME:-}" ]; then
    if command -v /usr/libexec/java_home >/dev/null 2>&1; then
      export JAVA_HOME="${JAVA_HOME:-$(/usr/libexec/java_home -v 17)}"
    fi
    log "building control APK (gradle assembleDebug)"
    (cd "$ROOT/android/pua-control" && gradle -q assembleDebug)
    apk="$CTRL_APK_SRC"
  fi
  if [ -z "$apk" ] || [ ! -f "$apk" ]; then
    warn "control APK not found and cannot build (need gradle + JDK 17 + ANDROID_HOME)."
    warn "skipping the control channel — the Termux VPS still works."
    warn "build it: (cd android/pua-control && gradle assembleDebug), then re-run, or set PUA_APK=…"
    return 0
  fi
  log "installing + enabling the PUA control channel"
  dev install -r "$apk" >/dev/null
  dev shell settings put secure enabled_accessibility_services "$CTRL_PKG/.PuaAccessibilityService"
  dev shell settings put secure accessibility_enabled 1
  dev shell cmd notification allow_listener "$CTRL_PKG/.PuaNotificationListenerService" >/dev/null 2>&1 || true
}

ensure_sshd() {
  log "ensuring sshd is up on :8022"
  termux_exec "sshd" >/dev/null 2>&1 || true
  sleep 1
  if dev shell "cat /proc/net/tcp /proc/net/tcp6" 2>/dev/null | grep -qi '1F56'; then
    log "sshd listening on :8022"
  else
    warn "sshd not detected on :8022 — re-run, or check bootstrap/setup.log"
  fi
}

summary() {
  local ip
  ip="$(dev shell 'ip -f inet addr show wlan0' 2>/dev/null | grep -oE 'inet [0-9.]+' | head -1 | awk '{print $2}')"
  printf '\n\033[1;32m✓ node online\033[0m  serial=%s\n' "$SERIAL"
  printf '  model : %s (Android %s)\n' \
    "$(dev shell getprop ro.product.model | tr -d '\r')" \
    "$(dev shell getprop ro.build.version.release | tr -d '\r')"
  printf '  LAN IP: %s\n' "${ip:-unknown — check WiFi}"
  if [ -n "${ip:-}" ]; then
    printf '  ssh   : ssh -i %s -p 8022 -o IdentitiesOnly=yes %s\n' "$KEY" "$ip"
  fi
  printf '\n  register it: add {"serial":"%s","name":"node-01"} to farm/nodes.json\n\n' "$SERIAL"
}

usage() {
  cat <<'EOF'
phoneuse-agent — bootstrap one Android phone as an AI-operable agent node.

  ./bootstrap/node.sh              bootstrap the connected phone (idempotent)
  ANDROID_SERIAL=<serial> ./bootstrap/node.sh

  adb plug phone  ->  ./bootstrap/node.sh  ->  node online

Installs Termux + Termux:Boot, bootstraps the Termux VPS (key-only sshd on
:8022, boot script, wake lock), hardens the device, installs the PUA
accessibility control channel, and prints the node's LAN IP.

Env:
  ANDROID_SERIAL   pick a device when several are attached
  PUA_APK          prebuilt control APK (else built, or skipped)
  ANDROID_HOME     Android SDK (needed to build the control APK)
  TERMUX_APK / TERMUX_BOOT_APK   local APKs instead of downloading from F-Droid
  ADB              adb binary (default: adb)
EOF
}

main() {
  if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    usage
    exit 0
  fi
  require_adb
  "$ADB" start-server >/dev/null 2>&1 || true
  pick_serial
  log "using device $SERIAL"
  "$ADB" -s "$SERIAL" wait-for-device
  dev shell input keyevent KEYCODE_WAKEUP >/dev/null 2>&1 || true

  if [ ! -f "$KEY" ]; then
    mkdir -p "$ROOT/keys"
    log "generating node SSH key -> keys/node_ed25519"
    ssh-keygen -t ed25519 -N '' -C phoneuse-node -f "$KEY" >/dev/null
  fi

  install_termux
  grant_storage
  wait_for_termux || die "Termux never finished its bootstrap — open Termux once, then re-run."
  run_setup
  install_termux_boot
  system_settings
  install_control
  ensure_sshd
  summary
}

main "$@"
