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
# interruption (HUP/INT/TERM) runs the EXIT trap (rollback_cutover): it proves the service DOWN,
# reads from the filesystem — directory identities and run-script hashes, never flags — what was
# really changed, puts back exactly the run script and state that ran before, starts only that
# pair and waits for authenticated READY (ROLLBACK_READY_VERIFIED); otherwise it leaves the
# service proven DOWN (or reports SERVICE_STATE_UNKNOWN) and every directory as found. The state
# writer lock is owned by this shell's own descriptor for the whole critical section (see
# lock_state_dir). The service is only
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
CUTOVER=0          # 1 once a stop was requested (set BEFORE sv down, never reset): rollback is due on failure
# What a failure must undo is read from the filesystem, not from flags (PR #87 review F-05): a
# signal can land after a rename and before the next command. These identify the before/after:
ORIG_RUN_SHA=""    # sha256 of the run script that ran before this invocation
NEW_RUN_SHA=""     # sha256 of the run script this invocation installs
LIVE_ID=""         # dev:ino of the live state directory before this invocation
INCOMING_ID=""     # dev:ino of the incoming state copy (--restore-state)
STATE_LOCK_HELD=0     # 1 while fd 9 of THIS shell owns the live state's writer flock
STATE_LOCK_DIR=""     # where the state locked through fd 9 is now (--restore-state moves it)
INCOMING_LOCK_HELD=0  # 1 while fd 8 of THIS shell owns the incoming state's writer flock
INCOMING_LOCK_DIR=""
BK=""              # recovery dir of this invocation
PREV_RUN=""        # run script to put back on failure
ROLLBACK_CONF=""   # config and release that PREV_RUN starts: a rollback is verified against them
ROLLBACK_RID=""

say() { echo "[$(date +%T)] $*"; }
field() { python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$1" "$2"; }
svpid() { sv status hg-runtime | sed -n 's/^run: hg-runtime: (pid \([0-9]*\)).*/\1/p'; }
sha() { sha256sum "$1" | cut -d' ' -f1; }

stop_service() {
  CUTOVER=1
  sv -w 60 -v down hg-runtime > /dev/null || { say "graceful stop did not finish in 60 s"; return 1; }
  sv status hg-runtime | grep -q '^down: hg-runtime' || { sv status hg-runtime; return 1; }
}

start_and_wait() {   # start_and_wait <config> <expected release id>: authenticated READY, stable pid
  # Every step returns explicitly: on_exit calls this inside `if`, where set -e does not apply.
  rm -f "$FINISH_STATE/hg-runtime-finish.count" "$FINISH_STATE/hg-runtime.HELD"
  sv up hg-runtime || return 1
  [ -n "$1" ] && [ -n "$2" ] || { say "no service config/release id to wait for"; return 1; }
  HG_SERVICE_CONFIG="$1" python3 -I -B "$SMOKE" ready-wait "$2" 180 || return 1
  pid1="$(svpid)"; sleep 5; pid2="$(svpid)"
  [ -n "$pid1" ] && [ "$pid1" = "$pid2" ] || { say "service pid changed ($pid1 -> $pid2): restart loop?"; return 1; }
  HG_SERVICE_CONFIG="$1" python3 -I -B "$SMOKE" ready-wait "$2" 10 || return 1
}

ensure_down() {   # ask runit for a graceful stop and PROVE it with sv status (never SIGKILL)
  sv -w 60 -v down hg-runtime > /dev/null 2>&1 || true
  sv status hg-runtime 2>/dev/null | grep -q '^down: hg-runtime'
}

absent() { [ ! -e "$1" ] && [ ! -L "$1" ]; }

dir_id() {   # dir_id <path>: dev:ino of a real (non-symlink) directory, empty otherwise
  python3 -I -c 'import os, stat, sys
try:
    st = os.lstat(sys.argv[1])
except OSError:
    sys.exit(0)
if stat.S_ISDIR(st.st_mode):
    print(f"{st.st_dev}:{st.st_ino}")' "$1"
}

classify_state() {   # where the live/incoming state directories really are: ORIGINAL|MOVED_ASIDE|SWAPPED|UNKNOWN
  live_now="$(dir_id "$STATE")"; prev_now="$(dir_id "$STATE.prev-$TS")"; inc_now="$(dir_id "$STATE.incoming-$TS")"
  if [ -n "$LIVE_ID" ] && [ "$live_now" = "$LIVE_ID" ] && absent "$STATE.prev-$TS"; then
    echo ORIGINAL                                   # live state untouched (an incoming copy may sit beside it)
  elif [ -n "$LIVE_ID" ] && [ -n "$INCOMING_ID" ] && absent "$STATE" && [ "$prev_now" = "$LIVE_ID" ] \
      && [ "$inc_now" = "$INCOMING_ID" ]; then
    echo MOVED_ASIDE                                # first rename done, second not
  elif [ -n "$LIVE_ID" ] && [ -n "$INCOMING_ID" ] && [ "$live_now" = "$INCOMING_ID" ] \
      && [ "$prev_now" = "$LIVE_ID" ] && absent "$STATE.incoming-$TS"; then
    echo SWAPPED                                    # both renames done
  else
    echo UNKNOWN
  fi
}

classify_run() {   # which run script is installed: ORIGINAL|NEW|UNKNOWN
  if [ -f "$S/run" ] && [ ! -L "$S/run" ] && [ -n "$ORIG_RUN_SHA" ]; then
    run_now="$(sha "$S/run")"
    if [ "$run_now" = "$ORIG_RUN_SHA" ]; then echo ORIGINAL; return; fi
    if [ -n "$NEW_RUN_SHA" ] && [ "$run_now" = "$NEW_RUN_SHA" ]; then echo NEW; return; fi
  fi
  echo UNKNOWN
}

lock_for_state_rollback() {   # $1 MOVED_ASIDE|SWAPPED: own both state locks where the directories are now
  if [ "$1" = SWAPPED ]; then inc_dir="$STATE"; else inc_dir="$STATE.incoming-$TS"; fi
  # Lock paths follow the directories; require_state_locks then proves each descriptor owns the
  # lock file at that path, so a wrong guess fails closed instead of being trusted.
  if [ "$STATE_LOCK_HELD" = 1 ]; then STATE_LOCK_DIR="$STATE.prev-$TS"
  else lock_state_dir "$STATE.prev-$TS" live || return 1; fi
  if [ "$INCOMING_LOCK_HELD" = 1 ]; then INCOMING_LOCK_DIR="$inc_dir"
  else lock_state_dir "$inc_dir" incoming || return 1; fi
}

rollback_cutover() {   # put back exactly the run script and state that ran before; start only that pair
  if ! ensure_down; then
    unlock_state
    say "could not prove hg-runtime DOWN: nothing is put back or started; inspect sv status hg-runtime, $S/run and $STATE*"
    echo "ROLLBACK_INCOMPLETE_SERVICE_STATE_UNKNOWN"
    return 0
  fi
  layout="$(classify_state)"; run_found="$(classify_run)"
  say "after the failure: state layout $layout, run script $run_found"
  back=1
  case "$layout" in
    ORIGINAL) ;;
    MOVED_ASIDE|SWAPPED)
      # Renaming state back is a state change too: only under locks this switch provably owns
      # (taken again if they were already released for the start; the service is DOWN now).
      if lock_for_state_rollback "$layout" && require_state_locks && restore_state_previous; then
        :
      else
        back=0
        say "state rollback incomplete; inspect $STATE.prev-$TS, $STATE.incoming-$TS and $STATE.failed-$TS"
      fi ;;
    *)
      back=0
      say "state layout is not one this switch produced: nothing is moved; inspect $STATE and $STATE.*-$TS" ;;
  esac
  case "$run_found" in
    ORIGINAL) ;;
    NEW)
      if cp -p "$PREV_RUN" "$S/run.tmp" && mv "$S/run.tmp" "$S/run"; then
        say "previous run script put back"
      else
        back=0
        say "run-script rollback incomplete; inspect $S/run and $PREV_RUN"
      fi ;;
    *)
      back=0
      say "run script is neither the previous nor the new one: left as it is; inspect $S/run" ;;
  esac
  unlock_state
  # Start only the pair that ran before, re-read from the filesystem after the rollback.
  if [ "$back" = 1 ] && [ "$(classify_state)" = ORIGINAL ] && [ "$(classify_run)" = ORIGINAL ]; then
    # `sv up` alone proves nothing (F-04): authenticated READY with a stable pid, or stop it again.
    if start_and_wait "$ROLLBACK_CONF" "$ROLLBACK_RID"; then
      say "hg-runtime is READY again on release $ROLLBACK_RID"
      echo "ROLLBACK_READY_VERIFIED release=$ROLLBACK_RID"
      return 0
    fi
    say "previous release did not reach authenticated READY with a stable pid: stopping it so runit cannot restart-loop it"
    echo "ROLLBACK_READY_UNVERIFIED release=${ROLLBACK_RID:-UNKNOWN}"
    if ensure_down; then
      echo "SERVICE_DOWN_VERIFIED"
    else
      say "could not prove hg-runtime DOWN; inspect sv status hg-runtime"
      echo "SERVICE_STATE_UNKNOWN"
    fi
    return 0
  fi
  if ensure_down; then
    say "HG runtime deliberately remains DOWN: the previous run script and state could not both be proven back in place"
    echo "ROLLBACK_INCOMPLETE_SERVICE_DOWN"
  else
    say "could not prove hg-runtime DOWN; inspect sv status hg-runtime"
    echo "ROLLBACK_INCOMPLETE_SERVICE_STATE_UNKNOWN"
  fi
}

on_exit() {
  rc=$?
  trap '' HUP INT TERM     # the rollback must run to its end: a second signal must not cut it short
  trap - EXIT
  if [ "$rc" -ne 0 ] && [ -n "$BK" ]; then
    say "FAILED (exit $rc) — returning to the state before this run"
    if [ "$CUTOVER" = 1 ]; then
      rollback_cutover || true
    else
      unlock_state         # nothing was stopped or changed yet
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

run_config() {   # run_config <run script>: the --config file a rendered hg-runtime ./run starts the service with
  sed -n 's/^exec python3 -B -u -m hg serve --config "\(.*\)"$/\1/p' "$1"
}

finish_ok() {
  [ -f "$S/finish" ] && cmp -s "$S/finish" "$FINISH_SRC" \
    || { say "hg-runtime/finish is not the reviewed version: run --install-finish first"; return 1; }
}

# State writer locks (PR #87 review F-01). The flock is taken on an open file description of THIS
# shell — fd 9 for the live state, fd 8 for an incoming copy — by a short child that only calls
# flock() on the inherited descriptor (state_lock.py acquire). flock locks belong to the open
# file description, so the lock lasts exactly as long as this script keeps the descriptor: no
# helper process exists whose death could free it while the switch carries on, and if this shell
# dies the switch stops with it. Before every state, backup or run-script change the switch still
# PROVES, through its own descriptors, that it owns each lock (require_state_locks); a flag, a
# ready file or a path check is never taken as that proof. Children that do not need the
# descriptors get them closed (`8<&- 9<&-`).
lock_state_dir() {   # lock_state_dir <state dir> <live|incoming>
  lock_root="$1"; lock_kind="$2"; lock_path="$1/.writer.lock"
  case "$lock_kind" in
    live) lock_fd=9; [ "$STATE_LOCK_HELD" = 0 ] || { say "live state lock is already held"; return 1; } ;;
    incoming) lock_fd=8; [ "$INCOMING_LOCK_HELD" = 0 ] || { say "incoming state lock is already held"; return 1; } ;;
    *) say "unknown state lock kind: $lock_kind"; return 1 ;;
  esac
  if [ -L "$lock_path" ] || [ ! -f "$lock_path" ]; then
    say "$lock_kind state writer lock is missing or not a regular file: $lock_path"
    return 1
  fi
  if [ "$lock_fd" = 9 ]; then exec 9< "$lock_path"; else exec 8< "$lock_path"; fi
  if python3 -I -B "$HERE/state_lock.py" acquire "$lock_fd" "$lock_path"; then
    lock_rc=0
  else
    lock_rc=$?
  fi
  if [ "$lock_rc" -ne 0 ]; then
    if [ "$lock_fd" = 9 ]; then exec 9<&-; else exec 8<&-; fi
    say "could not acquire the $lock_kind state writer lock (state_lock.py exit $lock_rc)"
    return 1
  fi
  if [ "$lock_fd" = 9 ]; then
    STATE_LOCK_HELD=1; STATE_LOCK_DIR="$lock_root"
  else
    INCOMING_LOCK_HELD=1; INCOMING_LOCK_DIR="$lock_root"
  fi
  say "$lock_kind state writer lock held on fd $lock_fd of switch PID $$"
}

require_state_locks() {   # fail unless this shell provably still owns every state lock it took
  [ "$STATE_LOCK_HELD" = 1 ] || [ "$INCOMING_LOCK_HELD" = 1 ] || { say "no state writer lock is held"; return 1; }
  if [ "$STATE_LOCK_HELD" = 1 ]; then
    python3 -I -B "$HERE/state_lock.py" verify 9 "$STATE_LOCK_DIR/.writer.lock" \
      || { say "live state writer lock is no longer owned by this switch: stopping before any further change"; return 1; }
  fi
  if [ "$INCOMING_LOCK_HELD" = 1 ]; then
    python3 -I -B "$HERE/state_lock.py" verify 8 "$INCOMING_LOCK_DIR/.writer.lock" \
      || { say "incoming state writer lock is no longer owned by this switch: stopping before any further change"; return 1; }
  fi
}

unlock_state() {   # closing this shell's descriptors releases the flocks (no child keeps a copy)
  # Closed unconditionally: a signal between `exec 9<` and the bookkeeping must not leave a lock behind.
  exec 8<&- 9<&-
  INCOMING_LOCK_HELD=0; INCOMING_LOCK_DIR=""
  STATE_LOCK_HELD=0; STATE_LOCK_DIR=""
}

restore_state_previous() {   # restore the old state even if the incoming rename never created $STATE
  if [ ! -d "$STATE.prev-$TS" ]; then
    say "previous state rollback directory is missing"
    return 1
  fi
  if [ -d "$STATE" ]; then
    mv "$STATE" "$STATE.failed-$TS" || return 1
  fi
  mv "$STATE.prev-$TS" "$STATE" || return 1
  say "state put back"
}

space_ok() {   # room for two copies of the state dir plus 1 MB
  need=$(( $(du -sk "$STATE" | cut -f1) * 2 + 1024 ))
  avail=$(df -Pk "$HOME" | awk 'NR==2 {print $4}')
  [ "$avail" -ge "$need" ] || { say "not enough free space ($avail KB < $need KB)"; return 1; }
}

backup_state() {   # backup_state <dest>: copy the stopped state dir under its writer lock, hash both trees
  require_state_locks
  HG_STATE_LOCK_FD=9 python3 -I - "$STATE" "$1" "$HERE/state_lock.py" 8<&- <<'PY'
import datetime, fcntl, hashlib, importlib.util, json, os, stat, subprocess, sys, uuid
src, dst = sys.argv[1], sys.argv[2]
lock_path = os.path.join(src, ".writer.lock")
fd = None
held = None
if "HG_STATE_LOCK_FD" in os.environ:
    # The switch owns the flock on its own descriptor, inherited here. A variable naming that
    # descriptor proves nothing by itself: prove the descriptor owns the lock before the copy
    # and again after hashing, or the copy is not a backup.
    if len(sys.argv) != 4:
        sys.exit("HG_STATE_LOCK_FD needs the path of state_lock.py")
    spec = importlib.util.spec_from_file_location("hg_switch_state_lock", sys.argv[3])
    state_lock = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(state_lock)
    lock_fd = int(os.environ["HG_STATE_LOCK_FD"])
    def held():
        try:
            state_lock.verify_held(lock_fd, lock_path)
        except (state_lock.LockNotHeld, state_lock.LockRefused, OSError) as exc:
            sys.exit(f"state writer lock is not owned by the switch: {exc}")
    held()
else:
    fd = os.open(lock_path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # standalone use: no live writer may hold the state
subprocess.run(["cp", "-a", src, dst], check=True)
def tree(root):
    out = {}
    for base, _dirs, files in os.walk(root):
        for name in files:
            p = os.path.join(base, name)
            if os.path.relpath(p, root) == ".hg-state-copy.json":
                continue                   # a copy attestation is not state
            if os.path.islink(p):
                out[os.path.relpath(p, root)] = "symlink"
                continue
            with open(p, "rb") as f:
                out[os.path.relpath(p, root)] = hashlib.sha256(f.read()).hexdigest()
    return out
a, b = tree(src), tree(dst)
if held is not None:
    held()                                     # still the switch's lock after copy and hashing
if fd is not None:
    os.close(fd)
if a != b:
    sys.exit("state copy differs from the source state")
if any(value == "symlink" for value in a.values()):
    sys.exit("state copy contains a symlink; manual review required")
inventory = []
for base, _dirs, files in os.walk(dst):
    for name in files:
        p = os.path.join(base, name)
        if os.path.islink(p) or os.path.basename(p) == ".hg-state-copy.json":
            continue
        with open(p, "rb") as stream:
            raw = stream.read()
        inventory.append({"path": os.path.relpath(p, dst), "bytes": len(raw),
                          "sha256": hashlib.sha256(raw).hexdigest()})
stale = os.path.join(dst, ".hg-state-copy.json")
if os.path.lexists(stale):        # an attestation copied from the source describes another copy
    os.unlink(stale)
required = {"tasks.jsonl", "actions.jsonl", "memory.jsonl", "http-idempotency.sqlite3"}
if not required.issubset({item["path"] for item in inventory}):
    sys.exit("state copy lacks one or more required runtime domains")
attestation = {
    "schema": "hg-state-copy-attestation-v1",
    "copy_id": uuid.uuid4().hex,
    "source_ref": "service-runtime-state-copy",
    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "assurance": "OPERATIONAL_INTEGRITY_UNAUTHENTICATED",
    "inventory": sorted(inventory, key=lambda item: item["path"]),
}
with open(os.path.join(dst, ".hg-state-copy.json"), "x", encoding="utf-8") as stream:
    json.dump(attestation, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    stream.write("\n")
with open(dst + ".sha256", "w") as f:
    for k in sorted(a):
        f.write(f"{a[k]}  {k}\n")
print(f"state backed up: {len(a)} files")
PY
  require_state_locks
  say "state backup taken under the live writer lock: $1"
}

precheck_with() {   # precheck_with <release root> <state dir> <report>: load a COPY with that release's code
  require_state_locks
  cp -a "$2" "$2.precheck"
  # Name the real live state (from the service config) so the precheck refuses to load it.
  # The release code it loads gets no copy of the lock descriptors.
  HG_RUNTIME_STATE_DIR="$STATE" HG_SERVICE_CONFIG="$OLDCONF" \
    python3 -I -B "$PRECHECK" "$1" "$2.precheck" > "$3" 8<&- 9<&- || { cat "$3"; rm -rf "$2.precheck"; return 1; }
  rm -rf "$2.precheck"
  require_state_locks
  say "state precheck passed with $1"
}

rollback_target() {   # rollback_target <run script>: the config/release that script starts, or fail
  ROLLBACK_CONF="$(run_config "$1")"
  [ -n "$ROLLBACK_CONF" ] && [ -f "$ROLLBACK_CONF" ] \
    || { say "the running run script names no readable service config: an automatic rollback could not be verified"; return 1; }
  ROLLBACK_RID="$(field "$ROLLBACK_CONF" release_id)" || return 1
  grep -qF "cd \"$HOME/hg-releases/$ROLLBACK_RID\"" "$1" \
    || { say "the running run script does not start release $ROLLBACK_RID: an automatic rollback could not be verified"; return 1; }
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
  # The release to go back to is the one run.old started, with the config it started it with.
  # The forward switch never edits the shared config, so its release_id can be older (F-W2).
  OLD_RUNCONF="$(run_config "$SRC/run.old")"
  [ -n "$OLD_RUNCONF" ] && [ -f "$OLD_RUNCONF" ] || { say "run.old names no readable service config"; exit 1; }
  OLD_RID="$(field "$OLD_RUNCONF" release_id)"
  OLD_ROOT="$HOME/hg-releases/$OLD_RID"
  grep -qF "cd \"$OLD_ROOT\"" "$SRC/run.old" || { say "run.old does not start release $OLD_RID from $OLD_RUNCONF"; exit 1; }
  BK="$E/restore-$TS"
  mkdir -m 700 "$BK"
  cp -p "$S/run" "$BK/run.current"
  PREV_RUN="$BK/run.current"
  ORIG_RUN_SHA="$(sha "$PREV_RUN")"
  NEW_RUN_SHA="$(sha "$SRC/run.old")"
  rollback_target "$BK/run.current"
  LIVE_ID="$(dir_id "$STATE")"
  [ -n "$LIVE_ID" ] || { say "live state $STATE is not a real directory"; exit 1; }
  sv status hg-runtime > "$BK/status.before"
  if [ "$MODE" = "--restore-state" ]; then
    ( cd "$SRC/state" && sha256sum -c --quiet "$SRC/state.sha256" ) || { say "backed-up state fails its hashes"; exit 1; }
  fi
  quota_ok
  release_ok "$OLD_RUNCONF" "$OLD_RID"
  finish_ok
  space_ok
  stop_service
  lock_state_dir "$STATE" live
  backup_state "$BK/state"
  if [ "$MODE" = "--restore-state" ]; then
    require_state_locks
    cp -a "$SRC/state" "$STATE.incoming-$TS"
    INCOMING_ID="$(dir_id "$STATE.incoming-$TS")"
    [ -n "$INCOMING_ID" ] || { say "incoming state copy is not a real directory"; exit 1; }
    precheck_with "$OLD_ROOT" "$STATE.incoming-$TS" "$BK/state-precheck.json"
    require_state_locks
    rm -f "$STATE.incoming-$TS/.hg-state-copy.json"   # the copy attestation must not become live state
    lock_state_dir "$STATE.incoming-$TS" incoming
    require_state_locks
    mv "$STATE" "$STATE.prev-$TS"
    STATE_LOCK_DIR="$STATE.prev-$TS"                 # fd 9's lock file moved with its directory
    say "live state moved aside to $STATE.prev-$TS"
    require_state_locks
    mv "$STATE.incoming-$TS" "$STATE"
    INCOMING_LOCK_DIR="$STATE"
    say "state restored from $SRC/state (the replaced copy is kept at $STATE.prev-$TS)"
  else
    precheck_with "$OLD_ROOT" "$BK/state" "$BK/state-precheck.json"
  fi
  require_state_locks
  cp -p "$SRC/run.old" "$S/run.tmp" && mv "$S/run.tmp" "$S/run"
  unlock_state
  start_and_wait "$OLD_RUNCONF" "$OLD_RID"
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
ORIG_RUN_SHA="$(sha "$PREV_RUN")"
rollback_target "$BK/run.old"      # a failure after the stop must be able to prove the old release READY
LIVE_ID="$(dir_id "$STATE")"
[ -n "$LIVE_ID" ] || { say "live state $STATE is not a real directory"; exit 1; }
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
NEW_RUN_SHA="$(sha "$BK/run.new")"

# 4. stop, back up the state under the service's own lock, prove the new release can read it
stop_service
lock_state_dir "$STATE" live
backup_state "$BK/state"
precheck_with "$ROOT" "$BK/state" "$BK/state-precheck.json"

# 5. new run script, start, READY on the new release with a stable pid
require_state_locks
install -m 700 "$BK/run.new" "$S/run.tmp" && mv "$S/run.tmp" "$S/run"
unlock_state
start_and_wait "$NEWCONF" "$NEW"
sha256sum "$S/run" "$S/finish" "$NEWCONF" > "$BK/hashes.after"
echo "SWITCH_DIR=$BK"
echo SWITCH_OK
