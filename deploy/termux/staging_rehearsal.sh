#!/data/data/com.termux/files/usr/bin/sh
# HG v1 — rehearse a release switch on an isolated STAGING runit service before production (G6, G8-A).
#
#   nohup sh staging_rehearsal.sh <staging dir> <candidate commit> [port] > /dev/null 2>&1 &
#
# The staging dir (absolute, inside $HOME, outside every live HG path) gets its own HOME, PREFIX,
# runsvdir, token, state and port (default 18867). The release production runs is rebuilt there from
# its manifest commit and must reproduce the same release id. Then, with the candidate's own
# deploy scripts: traffic on the production release -> switch_service.sh <candidate> (SWITCH_OK) ->
# G8-A J2 (/v1/tasks, pre-authored fs.write, CLOSED_VERIFIED, file hash = observed hash) and J1
# (/v1/chat through ModelRouter to the local model; no task or action) -> --restore over the state the
# candidate wrote (RESTORED) -> traffic -> a switch interrupted with TERM after the stop
# (ROLLBACK_READY_VERIFIED) -> traffic -> staging torn down. Production is only read: sv status by
# absolute path, file hashes, GET /v1/health/ready; before and after must be equal.
# Result: <staging dir>/rehearsal-<UTC>/rehearsal.log ends with REHEARSAL_RESULT ... and SHA256SUMS.
# Exit 2 = refused before anything was started; see the STAGING_REFUSED line.
set -u
umask 077
HERE="$(cd "$(dirname "$0")" && pwd)"
REALHOME="${HOME:?}"; REALPREFIX="${PREFIX:?PREFIX must be set (Termux)}"
STG="${1:-}"; C="${2:-}"; PORT="${3:-18867}"
refuse() { echo "STAGING_REFUSED: $*" >&2; exit 2; }
[ -n "$STG" ] && [ -n "$C" ] || refuse "usage: staging_rehearsal.sh <staging dir> <candidate commit> [port]"
case "$STG" in /*) ;; *) refuse "staging dir must be an absolute path" ;; esac
STG="${STG%/}"
case "$STG" in "$REALHOME"/?*) ;; *) refuse "staging dir must be inside \$HOME (and not \$HOME itself)" ;; esac
case "$STG" in *..*|*//*|*[!A-Za-z0-9._/-]*) refuse "staging dir must be a plain path ([A-Za-z0-9._/-], no ..)" ;; esac
printf '%s' "$C" | grep -Eq '^[0-9a-f]{40}$' || refuse "candidate must be a full 40-hex commit"
case "$PORT" in ''|*[!0-9]*) refuse "port must be a number" ;; esac
PRODSV="$REALPREFIX/var/service/hg-runtime"
[ -f "$PRODSV/run" ] || refuse "no production run script at $PRODSV/run"
PRODCONF="$(sed -n 's/^exec python3 -B -u -m hg serve --config "\(.*\)"$/\1/p' "$PRODSV/run")"
[ -n "$PRODCONF" ] && [ -f "$PRODCONF" ] || refuse "the production run script names no readable config"
python3 -I -B "$HERE/staging_probe.py" guard "$PRODCONF" "$STG" "$PORT" > /dev/null || exit 2
if [ -e "$STG" ] && [ ! -f "$STG/.hg-staging" ]; then refuse "$STG exists and is not a staging dir (no .hg-staging marker)"; fi
python3 -I -B "$HERE/staging_probe.py" port-free "$PORT" || exit 2
OLD="$(python3 -I -B "$HERE/staging_probe.py" field "$PRODCONF" release_id)" || refuse "production config has no release_id"
OLDCOMMIT="$(python3 -I -B "$HERE/staging_probe.py" field "$(python3 -I -B "$HERE/staging_probe.py" field "$PRODCONF" release_manifest)" commit)" \
  || refuse "production release manifest names no commit"

# ---------------------------------------------------------------- from here on only staging is written
[ -d "$STG" ] || { mkdir -m 700 "$STG" && : > "$STG/.hg-staging"; }
TS="$(date -u +%Y%m%dT%H%M%SZ)"
EV="$STG/rehearsal-$TS"
mkdir -m 700 "$EV"
exec >> "$EV/rehearsal.log" 2>&1
say() { echo "[$(date +%T)] $*"; }
RSVPID=""
STEP="setup"
R_SWITCH=NOT_RUN; R_J2=NOT_RUN; R_J1=NOT_RUN; R_RESTORE=NOT_RUN; R_INTERRUPT=NOT_RUN; R_PROD=UNVERIFIED

prod_snapshot() {   # read-only
  {
    echo "label=$1 time=$(date -u +%FT%TZ)"
    echo "sv_status=$(env -u SVDIR sv status "$PRODSV" 2>&1 | sed -E 's/\) [0-9]+s/) Ns/g')"
    echo "pids=$(pgrep -f "hg serve --config $PRODCONF" | tr '\n' ' ')"
    for f in "$PRODSV/run" "$REALPREFIX/bin/hg" "$REALHOME/.config/hg/assistant-release" "$PRODCONF" \
        "$REALHOME/.config/hg/runtime-service.json"; do [ -e "$f" ] && sha256sum "$f"; done
    echo "ready=$(HOME="$REALHOME" HG_SERVICE_CONFIG="$PRODCONF" python3 -I -B "$HERE/deploy_smoke.py" ready 2>&1 \
      | python3 -I -c 'import json,sys; s,b=json.loads(sys.stdin.read()); print(s, {k: b.get(k) for k in ("status","release_id","integrity","trust")})' 2>&1)"
  } > "$EV/prod-$1.txt" 2>&1
}
teardown() {
  if [ -n "$RSVPID" ]; then
    sv -w 60 down "$S" > /dev/null 2>&1
    kill -TERM "$RSVPID" 2>/dev/null; sleep 2
    sv exit "$S" > /dev/null 2>&1; sleep 3
    RSVPID=""
  fi
  say "staging processes left: $(pgrep -f "hg serve --config $STG/" | wc -l)"
}
finish() {
  rc=$?
  trap - EXIT
  trap '' HUP INT TERM
  teardown
  prod_snapshot after
  grep -v '^label=' "$EV/prod-before.txt" > "$EV/.prod-before.cmp"; grep -v '^label=' "$EV/prod-after.txt" > "$EV/.prod-after.cmp"
  if diff "$EV/.prod-before.cmp" "$EV/.prod-after.cmp" > "$EV/prod-diff.txt"; then R_PROD=UNCHANGED; else R_PROD=CHANGED; fi
  rm -f "$EV/.prod-before.cmp" "$EV/.prod-after.cmp"
  echo "REHEARSAL_RESULT candidate=$C release=${NEW:-UNKNOWN} production_release=$OLD switch=$R_SWITCH j2=$R_J2 j1=$R_J1 restore=$R_RESTORE interruption=$R_INTERRUPT production=$R_PROD last_step=$STEP"
  (cd "$EV" && sha256sum $(ls | grep -v '^SHA256SUMS$') > SHA256SUMS)
  echo "EVIDENCE_DIR=$EV"
  if [ "$rc" -eq 0 ] && { [ "$R_SWITCH" != SWITCH_OK ] || [ "$R_J2" != CLOSED_VERIFIED ] || [ "$R_J1" != ANSWERED_NO_ACTION ] \
      || [ "$R_RESTORE" != RESTORED ] || [ "$R_INTERRUPT" != ROLLBACK_READY_VERIFIED ] || [ "$R_PROD" != UNCHANGED ]; }; then rc=1; fi
  [ "$rc" -eq 0 ] && echo REHEARSAL_PASS || echo REHEARSAL_FAIL
  exit "$rc"
}
trap finish EXIT
trap 'exit 129' HUP; trap 'exit 130' INT; trap 'exit 143' TERM
stop() { say "STOP at $STEP: $*"; exit 1; }

prod_snapshot before
export HOME="$STG/home" PREFIX="$STG/prefix" SVDIR="$STG/prefix/var/service" HG_STAGING_DIR="$STG"
unset HG_HOME XDG_DATA_HOME HG_MODEL HG_SERVICE_CONFIG
[ "$SVDIR" != "$REALPREFIX/var/service" ] || stop "SVDIR is production"
CONFDIR="$HOME/.config/hg"
mkdir -p -m 700 "$HOME" "$PREFIX/bin" "$CONFDIR/releases" "$HOME/.local/share/hg" "$SVDIR"
say "staging HOME=$HOME PREFIX=$PREFIX SVDIR=$SVDIR port=$PORT production release=$OLD ($OLDCOMMIT)"

STEP="bootstrap"
if [ ! -d "$HOME/hg-releases/$OLD" ]; then
  sh "$HERE/build_release.sh" "$OLDCOMMIT" > "$EV/build-production.log" 2>&1 || stop "build of $OLDCOMMIT failed"
  [ "$(python3 -I -B "$HERE/staging_probe.py" field "$HOME/hg-release-build/$OLDCOMMIT/one.json" release_id)" = "$OLD" ] \
    || stop "rebuilding $OLDCOMMIT does not reproduce release $OLD"
  sh "$HERE/install_release.sh" "$OLDCOMMIT" > "$EV/install-production.log" 2>&1 || stop "install of $OLD failed"
fi
TOKEN="$CONFDIR/runtime-service-staging.token"
python3 -I -B "$HERE/staging_probe.py" token "$TOKEN" || stop "token"
OLDCONF="$CONFDIR/runtime-service-staging-$OLD.json"
python3 -I -B "$HERE/staging_probe.py" mkconf "$OLDCONF" "$OLD" "$HOME" "$PORT" "$TOKEN" || stop "staging config"
STATE="$(python3 -I -B "$HERE/staging_probe.py" field "$OLDCONF" state_dir)"
[ -d "$STATE" ] || mkdir -m 700 "$STATE" || stop "staging state dir"   # hg serve requires it (service.py)
[ -e "$CONFDIR/runtime-service.json" ] || cp -p "$OLDCONF" "$CONFDIR/runtime-service.json"
python3 -I -B "$HERE/staging_probe.py" staging-conf "$CONFDIR/runtime-service.json" || stop "shared staging config is not staging"
# J1 needs the model settings; the owner's notes and receipts are never copied.
A="$HOME/.local/share/hg/assistant"
[ -d "$A" ] || mkdir -m 700 "$A"
if [ -f "$REALHOME/.local/share/hg/assistant/config.json" ]; then
  cp "$REALHOME/.local/share/hg/assistant/config.json" "$A/config.json" && chmod 600 "$A/config.json"
fi

STEP="candidate"
sh "$HERE/build_release.sh" "$C" > "$EV/build-candidate.log" 2>&1 || stop "build of $C failed"
grep -q '^BUILD_OK$' "$EV/build-candidate.log" || stop "no BUILD_OK"
sh "$HERE/install_release.sh" "$C" > "$EV/install-candidate.log" 2>&1 || stop "install of $C failed"
NEW="$(python3 -I -B "$HERE/staging_probe.py" field "$HOME/hg-release-build/$C/one.json" release_id)"
SCR="$HOME/hg-release-build/$C/repo/deploy/termux"      # the candidate's own deploy scripts
sha256sum "$SCR"/* "$HERE/staging_rehearsal.sh" "$HERE/staging_probe.py" > "$EV/scripts.sha256" 2>/dev/null
say "candidate commit=$C release=$NEW"

STEP="staging service"
S="$SVDIR/hg-runtime"
[ -d "$S" ] || mkdir -m 700 "$S"
install -m 700 "$SCR/hg-runtime.finish" "$S/finish"
sed -e "s#@ROOT@#$HOME/hg-releases/$OLD#g" -e "s#@CONF@#$OLDCONF#g" "$SCR/hg-runtime.run.in" > "$S/run.tmp"
chmod 700 "$S/run.tmp" && mv "$S/run.tmp" "$S/run"
grep -qF "cd \"$HOME/hg-releases/$OLD\"" "$S/run" || stop "rendered run script is not staging"
# Device-level calls of ./run and ./finish (wake lock, the "HG đã dừng" notification) must not come
# from staging: no-op stubs first on the staging PATH record them in device-calls.log instead.
for tool in termux-notification termux-wake-lock termux-wake-unlock; do
  printf '#!%s\necho "%s $*" >> "%s/device-calls.log"\n' "$REALPREFIX/bin/sh" "$tool" "$EV" > "$PREFIX/bin/$tool"
  chmod 700 "$PREFIX/bin/$tool"
done
export PATH="$PREFIX/bin:$PATH"
[ "$(command -v termux-notification)" = "$PREFIX/bin/termux-notification" ] || stop "notification stub is not first on PATH"
rm -f "$HOME/.local/state/hg/hg-runtime-finish.count" "$HOME/.local/state/hg/hg-runtime.HELD"
nohup runsvdir -P "$SVDIR" > "$EV/runsvdir.log" 2>&1 &
RSVPID=$!
HG_SERVICE_CONFIG="$OLDCONF" python3 -I -B "$SCR/deploy_smoke.py" ready-wait "$OLD" 240 || stop "production release not READY in staging"

smoke() {
  HG_SERVICE_CONFIG="$CONFDIR/runtime-service.json" python3 -I -B "$SCR/deploy_smoke.py" submit "$1" > "$EV/smoke-$1.json" 2>&1
  rc=$?; say "smoke $1 exit=$rc $(cat "$EV/smoke-$1.json")"; return $rc
}
STEP="traffic before switch"; smoke "R0-$TS" || stop "traffic on the production release failed"

STEP="switch"
sh "$SCR/switch_service.sh" "$NEW" > "$EV/switch.log" 2>&1
grep -q '^SWITCH_OK$' "$EV/switch.log" || { R_SWITCH=FAIL; stop "no SWITCH_OK: $(tail -2 "$EV/switch.log" | tr '\n' ' ')"; }
R_SWITCH=SWITCH_OK
SWDIR="$(sed -n 's/^SWITCH_DIR=//p' "$EV/switch.log")"

STEP="G8-A J2"
if smoke "J2-$TS" && python3 -I -B "$HERE/staging_probe.py" j2 "$CONFDIR/runtime-service.json" "DEPLOY-SMOKE-J2-$TS" \
    "out/deploy-smoke-J2-$TS.txt" "$EV"; then R_J2=CLOSED_VERIFIED; else R_J2=FAIL; fi
STEP="G8-A J1"
if python3 -I -B "$HERE/staging_probe.py" chat "$CONFDIR/runtime-service.json" \
    "Thủ đô của Việt Nam là thành phố nào? Trả lời một câu ngắn." "$EV/j1-chat.json"; then R_J1=ANSWERED_NO_ACTION; else R_J1=FAIL; fi
cp "$A"/asks-*.jsonl "$EV/" 2>/dev/null

STEP="restore"
sh "$SCR/switch_service.sh" --restore "$SWDIR" > "$EV/restore.log" 2>&1
grep -q '^RESTORED$' "$EV/restore.log" || { R_RESTORE=FAIL; stop "no RESTORED: $(tail -2 "$EV/restore.log" | tr '\n' ' ')"; }
R_RESTORE=RESTORED
smoke "R1-$TS" || stop "traffic after restore failed"

STEP="interruption"
sh "$SCR/switch_service.sh" "$NEW" > "$EV/switch-interrupted.log" 2>&1 &
SWPID=$!
for _ in $(seq 1 600); do
  grep -q 'live state writer lock held' "$EV/switch-interrupted.log" && break
  kill -0 "$SWPID" 2>/dev/null || break
  sleep 0.5
done
kill -TERM "$SWPID" 2>/dev/null; wait "$SWPID"
if grep -q "^ROLLBACK_READY_VERIFIED release=$OLD$" "$EV/switch-interrupted.log"; then R_INTERRUPT=ROLLBACK_READY_VERIFIED
else R_INTERRUPT=NOT_VERIFIED; fi
smoke "R2-$TS" || stop "traffic after the interrupted switch failed"
STEP="done"
exit 0
