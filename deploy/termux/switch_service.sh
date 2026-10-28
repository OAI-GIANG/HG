#!/data/data/com.termux/files/usr/bin/sh
# HG v1 — switch the hg-runtime runit service between verified releases, with a recovery point.
#
#   sh switch_service.sh --install-finish         install deploy/termux/hg-runtime.finish (old one backed up)
#   sh switch_service.sh <new_release_id>         switch forward; prints SWITCH_DIR=<dir>
#   sh switch_service.sh --restore <switch dir>   go back to the run script recorded in <dir>
#   sh switch_service.sh --restore-state <dir>    same, and also put back the state recorded in <dir>
#                                                 (only if the new release left state the old one cannot read)
#
# Every check that can fail runs BEFORE the service is stopped. After the stop, any failure or
# interruption (HUP/INT/TERM) runs the EXIT trap, which puts the previous run script (and, for
# --restore-state, the previous state) back and starts the service again. The service is only
# stopped with a graceful `sv down` (never SIGKILL: a killed POST would leave its key IN_DOUBT).
# Run it detached so a dropped remote session cannot cut it short:
#   nohup sh switch_service.sh <args> > ~/hg-v1-evidence/switch-$(date +%s).log 2>&1 &
set -eu
export SVDIR="$PREFIX/var/service"
E="$HOME/hg-v1-evidence"
HERE="$(cd "$(dirname "$0")" && pwd)"
S="$SVDIR/hg-runtime"
CONFDIR="$HOME/.config/hg"
OLDCONF="$CONFDIR/runtime-service.json"
SMOKE="$HERE/deploy_smoke.py"
PRECHECK="$HERE/state_precheck.py"
FINISH_SRC="$HERE/hg-runtime.finish"
RUN_TEMPLATE="$HERE/hg-runtime.run.in"
FINISH_STATE="${HG_FINISH_STATE_DIR:-$HOME/.local/state/hg}"
MIN_QUOTA="${HG_MIN_QUOTA:-20}"
STOPPED=0          # 1 once a stop was requested (set BEFORE sv down: a timed-out stop still counts)
SWAPPED=0          # 1 while $S/run is not the script that was running before this invocation
STATE_SWAPPED=0    # 1 while the live state dir is the restored copy (--restore-state)
BK=""              # recovery dir of this invocation
PREV_RUN=""        # run script to put back on failure

say() { echo "[$(date +%T)] $*"; }
field() { python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$1" "$2"; }
svpid() { sv status hg-runtime | sed -n 's/^run: hg-runtime: (pid \([0-9]*\)).*/\1/p'; }
sha() { sha256sum "$1" | cut -d' ' -f1; }

stop_service() {
  STOPPED=1
  sv -w 60 -v down hg-runtime > /dev/null || { say "graceful stop did not finish in 60 s"; return 1; }
  sv status hg-runtime | grep -q '^down: hg-runtime' || { sv status hg-runtime; return 1; }
}

start_and_wait() {   # start_and_wait <config> <expected release id>
  rm -f "$FINISH_STATE/hg-runtime-finish.count" "$FINISH_STATE/hg-runtime.HELD"
  sv up hg-runtime
  HG_SERVICE_CONFIG="$1" python3 -I -B "$SMOKE" ready-wait "$2" 180
  pid1="$(svpid)"; sleep 5; pid2="$(svpid)"
  [ -n "$pid1" ] && [ "$pid1" = "$pid2" ] || { say "service pid changed ($pid1 -> $pid2): restart loop?"; return 1; }
  HG_SERVICE_CONFIG="$1" python3 -I -B "$SMOKE" ready-wait "$2" 10
  STOPPED=0
}

on_exit() {
  rc=$?
  trap - EXIT HUP INT TERM
  if [ "$rc" -ne 0 ] && [ -n "$BK" ]; then
    say "FAILED (exit $rc) — returning to the state before this run"
    if [ "$SWAPPED" = 1 ] || [ "$STATE_SWAPPED" = 1 ]; then
      sv -w 60 -v down hg-runtime > /dev/null 2>&1 || true
    fi
    if [ "$STATE_SWAPPED" = 1 ]; then
      if [ -d "$STATE.prev-$TS" ]; then
        mv "$STATE" "$STATE.failed-$TS" && mv "$STATE.prev-$TS" "$STATE" && say "state put back"
      fi
    fi
    if [ "$SWAPPED" = 1 ] && [ -n "$PREV_RUN" ]; then
      cp -p "$PREV_RUN" "$S/run.tmp" && mv "$S/run.tmp" "$S/run" && say "previous run script put back"
    fi
    if [ "$STOPPED" = 1 ] || [ "$SWAPPED" = 1 ] || [ "$STATE_SWAPPED" = 1 ]; then
      rm -f "$FINISH_STATE/hg-runtime-finish.count" "$FINISH_STATE/hg-runtime.HELD"
      sv up hg-runtime && say "hg-runtime started again (check: sv status hg-runtime)"
    fi
    echo "ROLLED_BACK_AFTER_FAILURE dir=$BK"
  fi
  exit "$rc"
}
trap on_exit EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

quota_ok() {
  remaining="$(curl -sS -m 10 https://api.github.com/rate_limit | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["resources"]["core"]["remaining"])')"
  say "GitHub unauthenticated quota remaining: $remaining"
  [ "$remaining" -ge "$MIN_QUOTA" ] || { say "GitHub quota below $MIN_QUOTA: wait for the reset"; return 1; }
}

release_ok() {   # release_ok <config> <release id>
  root="$HOME/hg-releases/$2"
  ( cd "$root" && python3 -I -B -c 'import sys; sys.path.insert(0, "."); from hg.release import main; sys.exit(main(sys.argv[1:]))' \
      verify-root --root "$root" --manifest "$CONFDIR/releases/$2.json" --release-id "$2" ) > /dev/null
  ( cd "$root" && python3 -B -m hg serve --config "$1" --check ) | grep -q PREFLIGHT_PASS
  for k in state_dir port token_file host max_body_bytes; do
    [ "$(field "$1" $k)" = "$(field "$OLDCONF" $k)" ] || { say "config $1 differs from $OLDCONF in $k"; return 1; }
  done
  [ "$(field "$1" release_id)" = "$2" ] && [ "$(field "$1" release_root)" = "$root" ] \
    && [ "$(field "$1" release_manifest)" = "$CONFDIR/releases/$2.json" ] \
    || { say "config $1 does not name release $2"; return 1; }
}

finish_ok() {
  [ -f "$S/finish" ] && cmp -s "$S/finish" "$FINISH_SRC" \
    || { say "hg-runtime/finish is not the reviewed version: run --install-finish first"; return 1; }
}

space_ok() {   # room for two copies of the state dir plus 1 MB
  need=$(( $(du -sk "$STATE" | cut -f1) * 2 + 1024 ))
  avail=$(df -Pk "$HOME" | awk 'NR==2 {print $4}')
  [ "$avail" -ge "$need" ] || { say "not enough free space ($avail KB < $need KB)"; return 1; }
}

backup_state() {   # backup_state <dest>: copy the stopped state dir under its writer lock, hash both trees
  python3 -I - "$STATE" "$1" <<'PY'
import fcntl, hashlib, os, subprocess, sys
src, dst = sys.argv[1], sys.argv[2]
fd = os.open(os.path.join(src, ".writer.lock"), os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)          # fails if any writer still holds the state
subprocess.run(["cp", "-a", src, dst], check=True)
def tree(root):
    out = {}
    for base, _dirs, files in os.walk(root):
        for name in files:
            p = os.path.join(base, name)
            if os.path.islink(p):
                out[os.path.relpath(p, root)] = "symlink"
                continue
            with open(p, "rb") as f:
                out[os.path.relpath(p, root)] = hashlib.sha256(f.read()).hexdigest()
    return out
a, b = tree(src), tree(dst)
os.close(fd)
if a != b:
    sys.exit("state copy differs from the live state")
with open(dst + ".sha256", "w") as f:
    for k in sorted(a):
        f.write(f"{a[k]}  {k}\n")
print(f"state backed up: {len(a)} files")
PY
}

precheck_with() {   # precheck_with <release root> <state dir> <report>: load a COPY with that release's code
  cp -a "$2" "$2.precheck"
  python3 -I -B "$PRECHECK" "$1" "$2.precheck" > "$3" || { cat "$3"; rm -rf "$2.precheck"; return 1; }
  rm -rf "$2.precheck"
}

TS="$(date -u +%Y%m%dT%H%M%SZ)"
STATE="$(field "$OLDCONF" state_dir)"

# ---------------------------------------------------------------- --install-finish
if [ "${1:-}" = "--install-finish" ]; then
  sh -n "$FINISH_SRC"
  FB="$E/finish-$TS"
  mkdir -m 700 "$FB"
  if [ -e "$S/finish" ]; then cp -p "$S/finish" "$FB/finish.old"; sha256sum "$S/finish" > "$FB/finish.old.sha256"; fi
  install -m 700 "$FINISH_SRC" "$S/finish.tmp" && mv "$S/finish.tmp" "$S/finish"
  sha256sum "$S/finish" > "$FB/finish.new.sha256"
  # ./finish only runs when ./run exits, so the running service is not touched.
  echo "FINISH_DIR=$FB"
  echo FINISH_INSTALLED
  exit 0
fi

# ---------------------------------------------------------------- --restore / --restore-state
if [ "${1:-}" = "--restore" ] || [ "${1:-}" = "--restore-state" ]; then
  MODE="$1"; SRC="$2"
  test -f "$SRC/run.old" && test -f "$SRC/hashes.before"
  grep -q "$(sha "$SRC/run.old")" "$SRC/hashes.before" || { say "run.old does not match its recorded hash"; exit 1; }
  grep -q "$(sha "$OLDCONF")" "$SRC/hashes.before" \
    || { say "the shared config changed since the switch; refusing to restore onto it"; exit 1; }
  OLD_RID="$(field "$OLDCONF" release_id)"
  OLD_ROOT="$HOME/hg-releases/$OLD_RID"
  BK="$E/restore-$TS"
  mkdir -m 700 "$BK"
  cp -p "$S/run" "$BK/run.current"
  PREV_RUN="$BK/run.current"
  sv status hg-runtime > "$BK/status.before"
  if [ "$MODE" = "--restore-state" ]; then
    ( cd "$SRC/state" && sha256sum -c --quiet "$SRC/state.sha256" ) || { say "backed-up state fails its hashes"; exit 1; }
  fi
  quota_ok
  release_ok "$OLDCONF" "$OLD_RID"
  finish_ok
  space_ok
  stop_service
  backup_state "$BK/state"
  if [ "$MODE" = "--restore-state" ]; then
    cp -a "$SRC/state" "$STATE.incoming-$TS"
    precheck_with "$OLD_ROOT" "$STATE.incoming-$TS" "$BK/state-precheck.json"
    mv "$STATE" "$STATE.prev-$TS"
    STATE_SWAPPED=1
    mv "$STATE.incoming-$TS" "$STATE"
    say "state restored from $SRC/state (the replaced copy is kept at $STATE.prev-$TS)"
  else
    precheck_with "$OLD_ROOT" "$BK/state" "$BK/state-precheck.json"
  fi
  cp -p "$SRC/run.old" "$S/run.tmp" && mv "$S/run.tmp" "$S/run"
  SWAPPED=1
  start_and_wait "$OLDCONF" "$OLD_RID"
  SWAPPED=0; STATE_SWAPPED=0
  sha256sum "$S/run" > "$BK/run.restored.sha256"
  echo "RESTORE_DIR=$BK"
  echo RESTORED
  exit 0
fi

# ---------------------------------------------------------------- switch forward
NEW="$1"
ROOT="$HOME/hg-releases/$NEW"
NEWCONF="$CONFDIR/runtime-service-$NEW.json"
test -f "$ROOT/hg/__main__.py"
test -f "$RUN_TEMPLATE"
BK="$E/switch-$TS"
mkdir -m 700 "$BK"
cp "$0" "$SMOKE" "$PRECHECK" "$FINISH_SRC" "$RUN_TEMPLATE" "$BK/"

# 1. recovery point (the shared config is never modified by this script)
cp -p "$S/run" "$BK/run.old"
PREV_RUN="$BK/run.old"
cp -p "$OLDCONF" "$BK/runtime-service.json.old"
sha256sum "$S/run" "$OLDCONF" > "$BK/hashes.before"
[ -e "$S/finish" ] && sha256sum "$S/finish" >> "$BK/hashes.before"
sv status hg-runtime > "$BK/status.before"

# 2. one config file per release
if [ ! -e "$NEWCONF" ]; then
  python3 -I - "$OLDCONF" "$NEWCONF" "$NEW" <<'PY'
import json, os, sys
src, dst, rid = sys.argv[1:]
home = os.environ["HOME"]
data = json.load(open(src))
data.update(release_id=rid, release_root=f"{home}/hg-releases/{rid}",
            release_manifest=f"{home}/.config/hg/releases/{rid}.json")
fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as stream:
    json.dump(data, stream, indent=2, sort_keys=True)
    stream.write("\n")
PY
fi

# 3. every check that can fail, while the old release keeps serving
quota_ok
release_ok "$NEWCONF" "$NEW"
finish_ok
space_ok
sed -e "s#@ROOT@#$ROOT#g" -e "s#@CONF@#$NEWCONF#g" "$RUN_TEMPLATE" > "$BK/run.new"
sh -n "$BK/run.new"
if grep -q "@ROOT@\|@CONF@" "$BK/run.new"; then say "run template not fully rendered"; exit 1; fi   # `! cmd` is ignored by set -e

# 4. stop, back up the state under the service's own lock, prove the new release can read it
stop_service
backup_state "$BK/state"
precheck_with "$ROOT" "$BK/state" "$BK/state-precheck.json"

# 5. new run script, start, READY on the new release with a stable pid
install -m 700 "$BK/run.new" "$S/run.tmp" && mv "$S/run.tmp" "$S/run"
SWAPPED=1
start_and_wait "$NEWCONF" "$NEW"
SWAPPED=0
sha256sum "$S/run" "$S/finish" "$NEWCONF" > "$BK/hashes.after"
echo "SWITCH_DIR=$BK"
echo SWITCH_OK
