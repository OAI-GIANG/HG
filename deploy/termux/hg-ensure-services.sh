#!/data/data/com.termux/files/usr/bin/sh
# hg-ensure-services.sh — the single start entrypoint for the Termux service supervisor (P3 Strategy C).
#
# Called by Termux:Boot (`--source boot`) and by the profile.d hook (`--source profile`, in the
# background). Both paths share one flock, so at most one caller acts at a time.
#
# What it does, in order:
#   1. takes the lock (a second concurrent caller logs "SKIP locked" and exits 0);
#   2. requests the Termux wake lock and records success or failure (both start paths);
#   3. proves from /proc whether a runsvdir for the production SVDIR is alive;
#   4. only if /proc shows it absent: `service-daemon start` (termux-services: start-stop-daemon
#      with a pidfile), waits for the new supervisor, then `sv up` for the allow-listed services.
#
# What it never does: start a second supervisor, restart or signal a live one, touch an individual
# service of a live supervisor (an owner's `sv down` stays down), or guess. If /proc cannot be read,
# a pid cannot be verified or SVDIR is not private to this uid, it logs BLOCKED and starts nothing.
#
# Limit (recorded in ledger §67): this script runs only when something calls it. If Android kills the
# whole Termux process tree while the phone stays on, neither entrypoint runs until the owner opens
# Termux or the phone reboots.
#
# Exit: 0 present/started/skipped, 2 BLOCKED, 4 start failed or unverified, 5 several supervisors.
# Test hooks: HG_ENSURE_PROC, HG_ENSURE_SVDIR, HG_ENSURE_STATE, HG_ENSURE_WAIT_S.
set -u
umask 077

SOURCE=unknown
while [ $# -gt 0 ]; do
  case "$1" in
    --source) SOURCE="${2:-unknown}"; shift 2 ;;
    *) shift ;;
  esac
done
case "$SOURCE" in boot|profile|guard|manual) ;; *) SOURCE=unknown ;; esac

: "${HOME:=/data/data/com.termux/files/home}"
: "${PREFIX:=/data/data/com.termux/files/usr}"
SVDIR="${HG_ENSURE_SVDIR:-$PREFIX/var/service}"
PROC="${HG_ENSURE_PROC:-/proc}"
STATE="${HG_ENSURE_STATE:-$HOME/.local/state/hg-ensure-services}"
WAIT_S="${HG_ENSURE_WAIT_S:-15}"
ALLOW_UP="desktop-commander-remote desktop-commander-watchdog"
LOG="$STATE/ensure.log"
export SVDIR
export LOGDIR="${LOGDIR:-$PREFIX/var/log}"

mkdir -p "$STATE" 2>/dev/null && chmod 700 "$STATE" 2>/dev/null || exit 2

log() {
  printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*" >> "$LOG"
  if [ "$(wc -c < "$LOG" 2>/dev/null || echo 0)" -gt 16384 ]; then
    # Bound bytes, not lines (one long line must not defeat the cap); drop the cut first line.
    tail -c 8192 "$LOG" | sed 1d > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
  fi
}

command -v flock >/dev/null 2>&1 || { log "BLOCKED flock_missing source=$SOURCE"; exit 2; }
exec 9>"$STATE/lock" || { log "BLOCKED lock_unopenable source=$SOURCE"; exit 2; }
if ! flock -n 9; then
  log "SKIP locked source=$SOURCE"
  exit 0
fi

# Wake lock on every start path (both entrypoints). Failure is recorded, not fatal.
if termux-wake-lock >/dev/null 2>&1; then
  log "WAKE_LOCK_OK source=$SOURCE"
else
  log "WAKE_LOCK_FAILED rc=$? source=$SOURCE"
fi

me="$(id -u)"

# SVDIR must exist, belong to this uid and be private, or a foreign supervisor could be in play.
if [ ! -d "$SVDIR" ] || [ "$(stat -c %u "$SVDIR" 2>/dev/null)" != "$me" ]; then
  log "BLOCKED svdir_unverified source=$SOURCE"
  exit 2
fi
case "$(stat -c %a "$SVDIR" 2>/dev/null)" in
  700) ;;
  *) log "BLOCKED svdir_not_private source=$SOURCE"; exit 2 ;;
esac

# Prints "pids=<list> unknown=<pid list>" for runsvdir processes of this uid that supervise $SVDIR.
# A pid whose directory still exists but whose cmdline cannot be read is unknown: absence is not
# proven. Processes of another uid cannot run a supervisor on a 0700 SVDIR of this uid.
scan() {
  found=""
  unknown=""
  for d in "$PROC"/[0-9]*; do
    [ -d "$d" ] || continue
    pid="${d##*/}"
    case "$pid" in *[!0-9]*) continue ;; esac
    owner="$(stat -c %u "$d" 2>/dev/null)" || owner=""
    if [ -z "$owner" ]; then
      [ -e "$d" ] && unknown="$unknown $pid"
      continue
    fi
    [ "$owner" = "$me" ] || continue
    if ! args="$(tr '\000' '\n' < "$d/cmdline" 2>/dev/null)"; then
      [ -e "$d" ] && unknown="$unknown $pid"
      continue
    fi
    arg0="$(printf '%s\n' "$args" | sed -n 1p)"
    arg1="$(printf '%s\n' "$args" | sed -n 2p)"
    [ "${arg0##*/}" = runsvdir ] && [ "$arg1" = "$SVDIR" ] && found="$found $pid"
  done
  printf 'pids=%s unknown=%s\n' "${found# }" "${unknown# }"
}

if [ ! -r "$PROC/self/cmdline" ] || [ ! -s "$PROC/self/cmdline" ]; then
  log "BLOCKED proc_unreadable source=$SOURCE"
  exit 2
fi

result="$(scan)"
pids="${result#pids=}"; pids="${pids%% unknown=*}"
unknown="${result##*unknown=}"
if [ -n "$unknown" ]; then
  log "BLOCKED pid_unverifiable pid=$unknown source=$SOURCE"
  exit 2
fi
count=0
for _p in $pids; do count=$((count + 1)); done
if [ "$count" -gt 1 ]; then
  log "MULTIPLE_SUPERVISORS pids=$pids source=$SOURCE"
  exit 5
fi
if [ "$count" -eq 1 ]; then
  log "PRESENT pids=$pids source=$SOURCE"
  exit 0
fi

# Absence is proven: start the supervisor through termux-services (pidfile-guarded).
log "ABSENT_VERIFIED source=$SOURCE"
service-daemon start >/dev/null 2>&1
rc=$?
if [ "$rc" -ne 0 ]; then
  log "START_FAILED rc=$rc source=$SOURCE"
  exit 4
fi

n=0
pids=""
while [ "$n" -le "$WAIT_S" ]; do
  result="$(scan)"
  pids="${result#pids=}"; pids="${pids%% unknown=*}"
  [ -n "$pids" ] && break
  sleep 1
  n=$((n + 1))
done
count=0
for _p in $pids; do count=$((count + 1)); done
if [ "$count" -eq 0 ]; then
  log "START_UNVERIFIED source=$SOURCE"
  exit 4
fi
if [ "$count" -gt 1 ]; then
  log "MULTIPLE_SUPERVISORS pids=$pids source=$SOURCE"
  exit 5
fi

# Fresh supervisor only: bring up the allow-listed services that exist (same set as the old boot script).
for s in $ALLOW_UP; do
  [ -d "$SVDIR/$s" ] || continue
  n=0
  while [ "$n" -lt "$WAIT_S" ] && [ ! -p "$SVDIR/$s/supervise/control" ]; do
    sleep 1
    n=$((n + 1))
  done
  if sv up "$SVDIR/$s" >/dev/null 2>&1; then
    log "SV_UP_OK service=$s source=$SOURCE"
  else
    log "SV_UP_FAILED service=$s source=$SOURCE"
  fi
done
log "STARTED pids=$pids source=$SOURCE"
exit 0
