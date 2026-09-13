#!/system/bin/sh
# pua-control — send accessibility commands to the PUA control channel.
# Runs either on the phone (uses /system/bin/am) or from a host over adb.
set -eu

if [ -d /data/data/com.termux/files/home ]; then
  cd /data/data/com.termux/files/home
  mkdir -p tmp
  export TMPDIR=/data/data/com.termux/files/home/tmp
fi

usage() {
  cat <<'USAGE'
Usage:
  pua-control dump
  pua-control click X Y
  pua-control click-id VIEW_ID
  pua-control set-text VIEW_ID TEXT...
  pua-control set-focused-text TEXT...
  pua-control events
  pua-control clear-events
  pua-control notifications [PACKAGE]
  pua-control open-notification [PACKAGE]
  pua-control launch PACKAGE
  pua-control open-url URL
  pua-control home | back | recents
USAGE
}

component="com.phoneuse.control/.CommandReceiver"
prefix="com.phoneuse.control"

run_am() {
  if [ -x /system/bin/am ]; then
    /system/bin/am broadcast --user 0 -W -n "$component" "$@"
  else
    adb_bin="${ADB:-adb}"
    if [ -n "${ANDROID_SERIAL:-}" ]; then
      "$adb_bin" -s "$ANDROID_SERIAL" shell am broadcast --user 0 -W -n "$component" "$@"
    else
      "$adb_bin" shell am broadcast --user 0 -W -n "$component" "$@"
    fi
  fi
}

cmd="${1:-}"
case "$cmd" in
  dump)
    shift
    [ "$#" -eq 0 ] || { usage >&2; exit 2; }
    run_am -a "$prefix.DUMP"
    ;;
  click)
    shift
    [ "$#" -eq 2 ] || { usage >&2; exit 2; }
    run_am -a "$prefix.CLICK" --ei x "$1" --ei y "$2"
    ;;
  click-id)
    shift
    [ "$#" -eq 1 ] || { usage >&2; exit 2; }
    run_am -a "$prefix.CLICK_ID" --es viewId "$1"
    ;;
  set-text)
    shift
    [ "$#" -ge 2 ] || { usage >&2; exit 2; }
    view_id="$1"
    shift
    run_am -a "$prefix.SET_TEXT" --es viewId "$view_id" --es text "$*"
    ;;
  set-focused-text)
    shift
    [ "$#" -ge 1 ] || { usage >&2; exit 2; }
    run_am -a "$prefix.SET_FOCUSED_TEXT" --es text "$*"
    ;;
  events)
    shift
    [ "$#" -eq 0 ] || { usage >&2; exit 2; }
    run_am -a "$prefix.EVENTS"
    ;;
  clear-events)
    shift
    [ "$#" -eq 0 ] || { usage >&2; exit 2; }
    run_am -a "$prefix.CLEAR_EVENTS"
    ;;
  notifications)
    shift
    [ "$#" -le 1 ] || { usage >&2; exit 2; }
    run_am -a "$prefix.NOTIFICATIONS" --es package "${1:-all}"
    ;;
  open-notification)
    shift
    [ "$#" -le 1 ] || { usage >&2; exit 2; }
    run_am -a "$prefix.OPEN_NOTIFICATION" --es package "${1:-all}"
    ;;
  launch)
    shift
    [ "$#" -eq 1 ] || { usage >&2; exit 2; }
    output="$(run_am -a "$prefix.LAUNCH" --es package "$1")"
    printf '%s\n' "$output"
    if printf '%s\n' "$output" | grep -q 'launch=false' && command -v monkey >/dev/null 2>&1; then
      monkey -p "$1" -c android.intent.category.LAUNCHER 1
    fi
    ;;
  open-url)
    shift
    [ "$#" -eq 1 ] || { usage >&2; exit 2; }
    run_am -a "$prefix.OPEN_URL" --es url "$1"
    ;;
  home|back|recents)
    action="$cmd"
    shift
    [ "$#" -eq 0 ] || { usage >&2; exit 2; }
    run_am -a "$prefix.GLOBAL_ACTION" --es name "$action"
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
