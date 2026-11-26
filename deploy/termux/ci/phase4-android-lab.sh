#!/usr/bin/env bash
# This test targets only the ephemeral emulator supplied by its workflow.
set -euo pipefail
lab=${HG_ANDROID_LAB:?}
out="$lab/evidence"
mapfile -t devices < <(adb devices | awk '$2=="device" {print $1}')
(( ${#devices[@]} == 1 ))
serial=${devices[0]}
[[ "$serial" =~ ^emulator-[0-9]+$ ]]
d() { adb -s "$serial" "$@"; }
test "$(d shell getprop ro.kernel.qemu | tr -d '\r')" = 1
d root >/dev/null
d wait-for-device
test "$(d shell id -u | tr -d '\r')" = 0
stamp() { date -u +%FT%TZ; }
event() { printf '%s\t%s\n' "$(stamp)" "$*" | tee -a "$out/timeline.tsv"; }
event "EMULATOR_CONFIRMED $serial API=$(d shell getprop ro.build.version.sdk | tr -d '\r')"
for p in com.termux_1002 com.termux.api_1002 com.termux.boot_1000; do
  d install -g "$lab/$p.apk"
done
d shell monkey -p com.termux.boot -c android.intent.category.LAUNCHER 1 >/dev/null
d shell am start -n com.termux/.app.TermuxActivity >/dev/null
prefix=/data/data/com.termux/files/usr
home=/data/data/com.termux/files/home
case_dir=$home/hg-phase4-lab
uid=$(d shell cmd package list packages -U com.termux | tr -d '\r' | awk '$1=="package:com.termux"{sub("uid:","",$2); print $2}')
[[ "$uid" =~ ^[1-9][0-9]+$ ]]
for attempt in {1..90}; do
  if d shell test -x "$prefix/bin/bash"; then break; fi
  sleep 2
done
d shell test -x "$prefix/bin/bash"
d shell mkdir -p "$case_dir" "$home/.termux/boot"
d push "$lab/release.tar.gz" "$case_dir/release.tar.gz" >/dev/null
d push "$lab/release.json" "$case_dir/release.json" >/dev/null
token=$(python -c 'import secrets; print(secrets.token_hex(24))')
printf '%s\n' "$token" > "$lab/token"
d push "$lab/token" "$case_dir/token" >/dev/null
cat > "$lab/start.sh" <<'START'
#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
umask 077
t=/data/data/com.termux/files/home/hg-phase4-lab
p=/data/data/com.termux/files/usr
export PATH="$p/bin:/system/bin" HG_HOME="$t/memory"
actor=${1:?}
printf '%s\t%s\t%s\n' "$("$p/bin/date" -u +%FT%TZ)" "$actor" "$$" >> "$t/triggers.tsv"
cd "$t/release"
exec "$p/bin/python3" -B -u -m hg serve --config "$t/service.json" >> "$t/service.log" 2>&1
START
cat > "$lab/bootstrap.sh" <<'BOOTSTRAP'
#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
umask 077
p=/data/data/com.termux/files/usr
t=/data/data/com.termux/files/home/hg-phase4-lab
export PATH="$p/bin:/system/bin"
exec >> "$t/bootstrap.log" 2>&1
trap 'echo "$?" > "$t/bootstrap.exit"' EXIT
if [ ! -x "$p/bin/python3" ] || [ ! -x "$p/bin/termux-job-scheduler" ]; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y python termux-api
fi
python3 -V > "$t/python-version"
if [ ! -f "$t/service.json" ]; then
  mkdir -m 700 "$t/release" "$t/state" "$t/memory"
  tar -xzf "$t/release.tar.gz" -C "$t/release"
  python3 - "$t" <<'CONFIG'
import json, sys
from pathlib import Path
p=Path(sys.argv[1])
m=json.loads((p/"release.json").read_bytes())
assert m["commit"]=="40254e60802bc59e40cd739d6ae4081241af4acd"
assert m["release_id"]=="95df7ed9e62f83fe32807a625da4952d191342d1babd2ba19945132dff676153"
(p/"service.json").write_text(json.dumps({"schema":"hg-runtime-service-config-v1","host":"127.0.0.1","port":18874,
    "state_dir":str(p/"state"),"token_file":str(p/"token"),"release_root":str(p/"release"),
    "release_manifest":str(p/"release.json"),"release_id":m["release_id"],"max_body_bytes":262144}))
CONFIG
fi
"$p/bin/nohup" "$t/start.sh" bootstrap </dev/null >/dev/null 2>&1 &
if [ -f "$t/arm-recovery" ]; then
  rm "$t/arm-recovery"
  termux-job-scheduler -s "$t/job.sh" --job-id 41226 --period-ms 0 --charging true --battery-not-low false --network none
  termux-job-scheduler -p > "$t/jobs-before.txt"
  date -u +%FT%TZ > "$t/job-armed-utc"
fi
BOOTSTRAP
cat > "$lab/job.sh" <<'JOB'
#!/data/data/com.termux/files/usr/bin/bash
exec /data/data/com.termux/files/home/hg-phase4-lab/start.sh jobscheduler-41226
JOB
cat > "$lab/boot.sh" <<'BOOT'
#!/data/data/com.termux/files/usr/bin/bash
exec /data/data/com.termux/files/home/hg-phase4-lab/start.sh termux-boot
BOOT
for f in start bootstrap job; do d push "$lab/$f.sh" "$case_dir/$f.sh" >/dev/null; done
d push "$lab/boot.sh" "$home/.termux/boot/hg-phase4.sh" >/dev/null
d shell "chown -R $uid:$uid '$case_dir' '$home/.termux'; chmod 700 '$case_dir' '$home/.termux/boot'; chmod 700 '$case_dir/'*.sh '$home/.termux/boot/hg-phase4.sh'; chmod 600 '$case_dir/token'; restorecon -R '$case_dir' '$home/.termux'"
forward() { d forward tcp:18874 tcp:18874 >/dev/null; }
forward
ready() {
  local tag=$1 code
  code=$(curl -s --max-time 2 -o "$lab/ready-response.json" -w '%{http_code}' \
    -H "Authorization: Bearer $token" http://127.0.0.1:18874/v1/health/ready) || return 1
  test "$code" = 200 || return 1
  python - "$lab/ready-response.json" "$out/ready-$tag.json" <<'PY'
import json, sys
from datetime import datetime, timezone
p=json.load(open(sys.argv[1]))
assert p["status"]=="READY" and p["integrity"]=="VERIFIED" and p["trust"]=="LOADED"
assert p["release_id"]=="95df7ed9e62f83fe32807a625da4952d191342d1babd2ba19945132dff676153"
e={k:p[k] for k in ("status","integrity","trust","release_id","idempotency")}
e.update(http=200, observed_at_utc=datetime.now(timezone.utc).isoformat())
with open(sys.argv[2],"w") as f: json.dump(e,f,indent=2)
PY
}
poll_ready() {
  local tag=$1 tries=$2
  for ((i=0;i<tries;i++)); do if ready "$tag"; then event "READY $tag"; return 0; fi; sleep 2; done
  event "NO_READY $tag"
  return 1
}
processes() { d shell ps -A -o UID,PID,NAME | tr -d '\r' | awk -v owner="$uid" '$1==owner {print}'; }
snapshot() { processes > "$out/processes-$1.txt"; }
type_bootstrap() {
  d shell input text "$case_dir/bootstrap.sh"
  d shell input keyevent 66
}
collect() {
  for f in bootstrap.log service.log triggers.tsv bootstrap.exit jobs-before.txt job-armed-utc python-version; do
    if d shell test -r "$case_dir/$f"; then d shell cat "$case_dir/$f" > "$out/$f"; fi
  done
}
trap collect EXIT
d shell dumpsys battery unplug >/dev/null
d shell "touch '$case_dir/arm-recovery'; chown $uid:$uid '$case_dir/arm-recovery'"
type_bootstrap
poll_ready pre-kill 130
for attempt in {1..20}; do if d shell test -s "$case_dir/job-armed-utc"; then break; fi; sleep 1; done
d shell test -s "$case_dir/job-armed-utc"
d shell grep -q 41226 "$case_dir/jobs-before.txt"
snapshot pre-kill
test -s "$out/processes-pre-kill.txt"
mapfile -t pids < <(awk '{print $2}' "$out/processes-pre-kill.txt")
for pid in "${pids[@]}"; do [[ "$pid" =~ ^[1-9][0-9]*$ ]]; done
event "EMULATOR_TEST_INDUCED_UID_TERMINATION_SIGKILL uid=$uid"
d shell kill -9 "${pids[@]}" || true
snapshot killed
test ! -s "$out/processes-killed.txt"
event "ZERO_SHARED_UID_PROCESSES_VERIFIED"
d shell dumpsys battery set ac 1 >/dev/null
event "ANDROID_CHARGING_CONSTRAINT_ENABLED job=41226"
if poll_ready post-kill 45; then
  snapshot post-kill
  if d shell grep -q jobscheduler-41226 "$case_dir/triggers.tsv"; then event "ISOLATED_APP_RECOVERY=PASS"; else event "ISOLATED_APP_RECOVERY=UNATTRIBUTED"; fi
else
  snapshot post-kill-timeout
  event "ISOLATED_APP_RECOVERY=FAIL_OBSERVED_WINDOW"
fi
d shell cat /proc/sys/kernel/random/boot_id | tr -d '\r' > "$out/boot-before.txt"
event "EMULATOR_D04_REBOOT_REQUESTED"
d reboot
timeout 75 adb -s "$serial" wait-for-device
for attempt in {1..75}; do if [ "$(d shell getprop sys.boot_completed | tr -d '\r')" = 1 ]; then break; fi; sleep 2; done
test "$(d shell getprop sys.boot_completed | tr -d '\r')" = 1
d shell cat /proc/sys/kernel/random/boot_id | tr -d '\r' > "$out/boot-after.txt"
! cmp -s "$out/boot-before.txt" "$out/boot-after.txt"
d root >/dev/null
timeout 40 adb -s "$serial" wait-for-device
forward
if poll_ready post-reboot 45; then
  snapshot post-reboot
  if d shell grep -q termux-boot "$case_dir/triggers.tsv"; then event "EMULATOR_D04=PASS"; else event "EMULATOR_D04=UNATTRIBUTED"; fi
else
  snapshot post-reboot-timeout
  event "EMULATOR_D04=FAIL_OBSERVED_WINDOW"
fi
d shell dumpsys battery reset >/dev/null
