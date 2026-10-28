#!/data/data/com.termux/files/usr/bin/sh
# HG v1 — switch the hg-runtime runit service to a verified release, with a recorded recovery point.
# usage: sh switch_service.sh <new_release_id>        -> writes $E/switch-<ts>/ and prints its path
# Recovery: sh switch_service.sh --restore <switch dir>  (puts back the recorded run script)
set -eu
E="$HOME/hg-v1-evidence"
S="$PREFIX/var/service/hg-runtime"
CONFDIR="$HOME/.config/hg"
OLDCONF="$CONFDIR/runtime-service.json"

wait_state() {   # wait_state up|down
  i=0
  while [ $i -lt 40 ]; do
    if sv status hg-runtime | grep -q "^$1: hg-runtime"; then return 0; fi
    sleep 0.5; i=$((i + 1))
  done
  echo "hg-runtime did not reach state $1"; sv status hg-runtime; return 1
}

if [ "${1:-}" = "--restore" ]; then
  BK="$2"
  sv down hg-runtime; wait_state down
  cp -p "$BK/run.old" "$S/run.tmp" && mv "$S/run.tmp" "$S/run"
  sha256sum "$S/run" | sed "s#$S/##" > "$BK/run.restored.sha256"
  sv up hg-runtime; wait_state run
  echo RESTORED_RUN_SCRIPT
  exit 0
fi

NEW="$1"
ROOT="$HOME/hg-releases/$NEW"
MAN="$CONFDIR/releases/$NEW.json"
NEWCONF="$CONFDIR/runtime-service-$NEW.json"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BK="$E/switch-$TS"
mkdir -m 700 "$BK"
test -f "$ROOT/hg/__main__.py"
test -f "$MAN"

# 1. recovery point: run script, shared config, status
cp -p "$S/run" "$BK/run.old"
cp -p "$OLDCONF" "$BK/runtime-service.json.old"
sha256sum "$S/run" "$OLDCONF" > "$BK/hashes.before"
sv status hg-runtime > "$BK/status.before"
STATE="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["state_dir"])' "$OLDCONF")"

# 2. one config file per release (the old one is not modified)
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

# 3. read-only preflight of the new release against the live state dir
( cd "$ROOT" && python3 -B -m hg serve --config "$NEWCONF" --check ) > "$BK/preflight.json"
grep -q PREFLIGHT_PASS "$BK/preflight.json"

# 4. stop, back up the whole state dir (including sqlite -wal/-shm) with hashes
sv down hg-runtime; wait_state down
cp -a "$STATE" "$BK/state"
( cd "$STATE" && find . -type f -exec sha256sum {} + | sort -k 2 ) > "$BK/state.sha256"

# 5. new run script (same shape as before) and a finish script that stops a fail-closed
#    start (exit 78) from restarting in a loop and burning the GitHub API quota
cat > "$S/run.tmp" <<EOF
#!/data/data/com.termux/files/usr/bin/sh
exec 2>&1
set -eu
umask 077
termux-wake-lock 2>/dev/null || true
export HG_CANONICAL_REPOSITORY="OAI-GIANG/HG"
cd "$ROOT" || { echo 'HG_BLOCKED: verified release directory missing'; exit 78; }
exec python3 -B -u -m hg serve --config "$NEWCONF"
EOF
chmod 700 "$S/run.tmp"
mv "$S/run.tmp" "$S/run"
if [ ! -e "$S/finish" ]; then
  cat > "$S/finish" <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
# runit passes the run script's exit code as $1. 78 = fail-closed startup: do not restart.
if [ "${1:-}" = "78" ]; then
  echo "HG_BLOCKED: exit 78, service held down (fix, then: sv up hg-runtime)"
  exec sv down "$(pwd)"
fi
EOF
  chmod 700 "$S/finish"
fi
sha256sum "$S/run" "$S/finish" "$NEWCONF" > "$BK/hashes.after"
sv up hg-runtime; wait_state run
echo "SWITCH_DIR=$BK"
echo SWITCH_OK
