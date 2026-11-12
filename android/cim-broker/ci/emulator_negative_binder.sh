#!/usr/bin/env bash
# Emulator negative-Binder qualification for the HG CIM Broker (G7-CI).
# Run as one bash process: reactivecircus/android-emulator-runner executes each line of an
# inline `script:` in its own `sh -c`, so variables, functions and heredocs did not survive
# between lines (run 2026-11-10: `test -s "$BROKER"` saw an empty path and exited 1).
set -euo pipefail
# No early-exiting reader in a pipeline: with pipefail, `awk ... exit` made adb/tr die of SIGPIPE
# and the script exit 141 (run on 403c830, 2026-11-13).
BROKER=broker-artifacts/app-debug.apk
PROBE=broker-artifacts/probe-debug.apk
test -s "$BROKER"
test -s "$PROBE"
adb install --no-streaming termux-fdroid-0.118.3.apk
adb install --no-streaming "$BROKER"
adb install --no-streaming "$PROBE"

uid_for() {
  adb shell pm list packages -U | tr -d '\r' \
    | awk -v package="package:$1" '$1 == package && uid == "" { sub(/^uid:/, "", $2); uid = $2 } END { print uid }'
}
TERMUX_UID="$(uid_for com.termux)"
BROKER_UID="$(uid_for org.hg.cim.broker)"
PROBE_UID="$(uid_for org.hg.cim.broker.probe)"
test -n "$TERMUX_UID"
test -n "$BROKER_UID"
test -n "$PROBE_UID"
test "$TERMUX_UID" != "$BROKER_UID"
test "$PROBE_UID" != "$BROKER_UID"
test "$TERMUX_UID" != "$PROBE_UID"
{
  echo "TERMUX_UID=$TERMUX_UID"
  echo "BROKER_UID=$BROKER_UID"
  echo "PROBE_UID=$PROBE_UID"
  echo "UIDS_DISTINCT=PASS"
} | tee android-emulator-uid-evidence.txt

adb shell am start -W -n org.hg.cim.broker/.MainActivity
python3 - <<'PY'
import subprocess, time, re, xml.etree.ElementTree as ET

def dump_ui():
    subprocess.run(
        ["adb", "shell", "uiautomator", "dump", "/sdcard/window.xml"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
    )
    raw = subprocess.check_output(
        ["adb", "shell", "cat", "/sdcard/window.xml"], text=True, errors="replace"
    )
    return ET.fromstring(raw[raw.find("<?xml"):])

def norm(text):
    return " ".join(text.split()).casefold()

def tap_label(label, timeout=75):
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            root = dump_ui()
            seen = []
            for node in root.iter("node"):
                names = [node.attrib.get("text", ""), node.attrib.get("content-desc", "")]
                seen.extend(n.strip() for n in names if n.strip())
                # Buttons render with textAllCaps, so uiautomator may report "TRUST THIS ...".
                if any(norm(n) == norm(label) for n in names):
                    bounds = node.attrib.get("bounds", "")
                    match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                    if match:
                        x1, y1, x2, y2 = map(int, match.groups())
                        if y2 > y1 and x2 > x1:
                            subprocess.run(
                                ["adb", "shell", "input", "tap",
                                 str((x1+x2)//2), str((y1+y2)//2)],
                                check=True
                            )
                            time.sleep(2)
                            return
            last = "label not visible; seen: " + " | ".join(seen[:25])
            subprocess.run(
                ["adb", "shell", "input", "swipe", "540", "1800", "540", "700", "400"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
            )
        except Exception as exc:
            last = type(exc).__name__
        time.sleep(2)
    raise SystemExit(f"could not tap owner confirmation control {label!r}: {last}")

tap_label("Trust this installed Termux")
tap_label("Trust")
PY

PAIRING="$(adb shell run-as org.hg.cim.broker cat shared_prefs/hg_cim_broker_owner_pairing_v1.xml | tr -d '\r')"
echo "$PAIRING" | grep -E 'name="owner_paired".*value="true"'
echo "$PAIRING" | grep -E 'name="termux_uid".*value="'"$TERMUX_UID"'"'

adb logcat -c
adb shell am force-stop org.hg.cim.broker.probe
adb shell am start -W -n org.hg.cim.broker.probe/.BinderProbeActivity
sleep 3
adb logcat -d -s HGBinderProbe:V | tee android-emulator-binder-negative.log
grep -F "NEGATIVE_BINDER_PASS_DENY_UID caller_uid=$PROBE_UID" android-emulator-binder-negative.log
! grep -E "NEGATIVE_BINDER_FAIL|NEGATIVE_BINDER_INCONCLUSIVE" android-emulator-binder-negative.log
