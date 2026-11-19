"""P3 Strategy C: deploy/termux/hg-ensure-services.sh, the single start entrypoint for Termux:Boot and profile.d.

Acceptance (owner decision D-02, 2026-11-19):
- both entrypoints request the wake lock and record success or failure;
- one flock: two concurrent calls start the supervisor at most once;
- a live supervisor for the production SVDIR is never started again or restarted;
- the supervisor is started only after /proc shows that it is absent;
- unreadable /proc, an unverifiable pid or a foreign-owned SVDIR -> BLOCKED, nothing is started;
- a failing service-daemon is reported; `sv up` only for the allow-listed services, and only after a fresh start;
- the log is bounded; the profile.d hook never blocks a login shell.

Every command is a fake on PATH and /proc is a fake tree (HG_ENSURE_PROC), so no real service is touched.
"""
import os
import shutil
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[2] / "deploy" / "termux"
SCRIPT = DEPLOY / "hg-ensure-services.sh"
PROFILE_HOOK = DEPLOY / "hg-start-services.profile.sh"
BOOT_HOOK = DEPLOY / "hg-start-services.boot.sh"
SH = shutil.which("dash") or shutil.which("sh")
ALLOW = ("desktop-commander-remote", "desktop-commander-watchdog")

FAKE_SERVICE_DAEMON = """#!/bin/sh
echo "service-daemon $* SVDIR=$SVDIR" >> "$FAKE_CALLS"
[ -n "${FAKE_SD_SLEEP:-}" ] && sleep "$FAKE_SD_SLEEP"
[ "${FAKE_SD_FAIL:-0}" = 1 ] && exit 1
if [ "${FAKE_SD_NOSPAWN:-0}" != 1 ]; then
  n=$((90000 + $(wc -l < "$FAKE_CALLS")))
  mkdir -p "$FAKE_PROC/$n"
  printf '%s\\0%s\\0' "$FAKE_PREFIX/bin/runsvdir" "$SVDIR" > "$FAKE_PROC/$n/cmdline"
  for s in $FAKE_SERVICES; do mkdir -p "$SVDIR/$s/supervise"; mkfifo "$SVDIR/$s/supervise/control" 2>/dev/null; done
fi
exit 0
"""
FAKE_SV = '#!/bin/sh\necho "sv $*" >> "$FAKE_CALLS"\n'
FAKE_WAKE = '#!/bin/sh\necho "wake-lock" >> "$FAKE_CALLS"\n[ "${FAKE_WAKE_FAIL:-0}" = 1 ] && exit 1\nexit 0\n'


def _exe(path, text):
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


class EnsureServicesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hg-ensure-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.prefix = self.tmp / "usr"
        self.svdir = self.prefix / "var" / "service"
        for s in ALLOW + ("hg-runtime", "ollama"):
            (self.svdir / s).mkdir(parents=True)
        self.svdir.chmod(0o700)
        self.proc = self.tmp / "proc"
        (self.proc / "self").mkdir(parents=True)
        (self.proc / "self" / "cmdline").write_bytes(b"sh\0hg-ensure-services.sh\0")
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        _exe(self.bin / "service-daemon", FAKE_SERVICE_DAEMON)
        _exe(self.bin / "sv", FAKE_SV)
        _exe(self.bin / "termux-wake-lock", FAKE_WAKE)
        self.state = self.tmp / "state"
        self.calls = self.tmp / "calls.log"
        self.calls.touch()

    def env(self, **extra):
        env = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "HOME": str(self.tmp / "home"),
            "PREFIX": str(self.prefix),
            "HG_ENSURE_SVDIR": str(self.svdir),
            "HG_ENSURE_PROC": str(self.proc),
            "HG_ENSURE_STATE": str(self.state),
            "HG_ENSURE_WAIT_S": "2",
            "FAKE_CALLS": str(self.calls),
            "FAKE_PROC": str(self.proc),
            "FAKE_PREFIX": str(self.prefix),
            "FAKE_SERVICES": " ".join(ALLOW),
        }
        env.update(extra)
        return env

    def run_script(self, source="profile", **extra):
        return subprocess.run([SH, str(SCRIPT), "--source", source], env=self.env(**extra),
                              capture_output=True, text=True, timeout=30)

    def calls_list(self):
        return self.calls.read_text(encoding="utf-8").splitlines()

    def log(self):
        p = self.state / "ensure.log"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def add_proc(self, pid, *argv):
        d = self.proc / str(pid)
        d.mkdir()
        (d / "cmdline").write_bytes(b"".join(a.encode() + b"\0" for a in argv))
        return d

    def add_live_supervisor(self, pid=4242):
        return self.add_proc(pid, str(self.prefix / "bin" / "runsvdir"), str(self.svdir))

    # --- wake lock on both start paths (scenarios A and B) ---

    def test_profile_and_boot_paths_both_request_the_wake_lock(self):
        for source in ("profile", "boot"):
            with self.subTest(source=source):
                self.calls.write_text("", encoding="utf-8")
                proc = self.run_script(source)
                self.assertEqual(proc.returncode, 0, proc.stderr + self.log())
                self.assertIn("wake-lock", self.calls_list())
                self.assertIn(f"WAKE_LOCK_OK source={source}", self.log())

    def test_wake_lock_failure_is_recorded_and_start_continues(self):
        proc = self.run_script(FAKE_WAKE_FAIL="1")
        self.assertEqual(proc.returncode, 0, self.log())
        self.assertIn("WAKE_LOCK_FAILED", self.log())
        self.assertEqual(sum(c.startswith("service-daemon start") for c in self.calls_list()), 1)

    # --- single start, never a second supervisor ---

    def test_absent_supervisor_is_started_once_and_only_allowlisted_services_are_upped(self):
        proc = self.run_script("boot")
        self.assertEqual(proc.returncode, 0, proc.stderr + self.log())
        calls = self.calls_list()
        self.assertEqual([c for c in calls if c.startswith("service-daemon")],
                         [f"service-daemon start SVDIR={self.svdir}"])
        ups = sorted(c for c in calls if c.startswith("sv "))
        self.assertEqual(ups, sorted(f"sv up {self.svdir}/{s}" for s in ALLOW))
        self.assertIn("STARTED", self.log())

    def test_live_supervisor_is_never_started_again_or_restarted(self):
        self.add_live_supervisor()
        for source in ("profile", "boot"):
            proc = self.run_script(source)
            self.assertEqual(proc.returncode, 0, self.log())
        calls = self.calls_list()
        self.assertFalse([c for c in calls if c.startswith(("service-daemon", "sv "))], calls)
        self.assertIn("PRESENT pids=4242", self.log())

    def test_two_concurrent_calls_start_the_supervisor_at_most_once(self):
        env = self.env(FAKE_SD_SLEEP="1")
        procs = [subprocess.Popen([SH, str(SCRIPT), "--source", src], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for src in ("boot", "profile")]
        codes = [p.wait(timeout=30) for p in procs]
        for p in procs:
            p.stdout.close()
            p.stderr.close()
        self.assertEqual(codes, [0, 0], self.log())
        starts = [c for c in self.calls_list() if c.startswith("service-daemon")]
        self.assertEqual(len(starts), 1, self.calls_list())
        self.assertIn("SKIP locked", self.log())

    def test_supervisor_of_another_svdir_does_not_count_as_present(self):
        self.add_proc(5151, str(self.prefix / "bin" / "runsvdir"), str(self.tmp / "staging" / "service"))
        proc = self.run_script()
        self.assertEqual(proc.returncode, 0, self.log())
        self.assertEqual(sum(c.startswith("service-daemon start") for c in self.calls_list()), 1)

    def test_two_live_supervisors_are_reported_and_nothing_is_started(self):
        self.add_live_supervisor(4242)
        self.add_live_supervisor(4343)
        proc = self.run_script()
        self.assertEqual(proc.returncode, 5, self.log())
        self.assertIn("MULTIPLE_SUPERVISORS pids=4242 4343", self.log())
        self.assertFalse([c for c in self.calls_list() if c.startswith(("service-daemon", "sv "))])

    # --- fail closed ---

    def test_unreadable_proc_blocks_and_starts_nothing(self):
        shutil.rmtree(self.proc / "self")
        proc = self.run_script()
        self.assertEqual(proc.returncode, 2, self.log())
        self.assertIn("BLOCKED proc_unreadable", self.log())
        self.assertFalse([c for c in self.calls_list() if c.startswith(("service-daemon", "sv "))])

    def test_pid_that_cannot_be_read_blocks_and_starts_nothing(self):
        d = self.proc / "777"
        (d / "cmdline").mkdir(parents=True)      # exists but cannot be read as a file, also as root
        proc = self.run_script()
        self.assertEqual(proc.returncode, 2, self.log())
        self.assertIn("BLOCKED pid_unverifiable pid=777", self.log())
        self.assertFalse([c for c in self.calls_list() if c.startswith("service-daemon")])

    def test_svdir_not_private_blocks_and_starts_nothing(self):
        self.svdir.chmod(0o755)
        proc = self.run_script()
        self.assertEqual(proc.returncode, 2, self.log())
        self.assertIn("BLOCKED svdir_not_private", self.log())
        self.assertFalse([c for c in self.calls_list() if c.startswith("service-daemon")])

    # --- failures are reported, never hidden ---

    def test_failing_service_daemon_is_reported(self):
        proc = self.run_script(FAKE_SD_FAIL="1")
        self.assertEqual(proc.returncode, 4, self.log())
        self.assertIn("START_FAILED rc=1", self.log())
        self.assertFalse([c for c in self.calls_list() if c.startswith("sv ")])

    def test_start_that_leaves_no_supervisor_is_unverified(self):
        proc = self.run_script(FAKE_SD_NOSPAWN="1")
        self.assertEqual(proc.returncode, 4, self.log())
        self.assertIn("START_UNVERIFIED", self.log())

    # --- log hygiene ---

    def test_log_is_bounded(self):
        self.state.mkdir(mode=0o700)
        (self.state / "ensure.log").write_text("x" * 40000 + "\n", encoding="utf-8")
        self.add_live_supervisor()
        self.run_script()
        self.assertLessEqual((self.state / "ensure.log").stat().st_size, 16384)
        self.assertTrue(stat.S_IMODE(self.state.stat().st_mode) == 0o700)

    # --- the two entrypoints ---

    def test_profile_hook_returns_at_once_and_calls_the_entrypoint_in_the_background(self):
        home = self.tmp / "home"
        (home / ".local" / "bin").mkdir(parents=True)
        marker = self.tmp / "entry.log"
        _exe(home / ".local" / "bin" / "hg-ensure-services.sh",
             f'#!/bin/sh\nsleep 3\necho "$*" >> "{marker}"\n')
        started = time.monotonic()
        proc = subprocess.run([SH, "-c", f'. "{PROFILE_HOOK}"; echo "SVDIR=$SVDIR"'],
                              env=self.env(), capture_output=True, text=True, timeout=10)
        elapsed = time.monotonic() - started
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertLess(elapsed, 2.0)
        self.assertIn(f"SVDIR={self.prefix}/var/service", proc.stdout)
        for _ in range(60):
            if marker.exists():
                break
            time.sleep(0.1)
        self.assertEqual(marker.read_text(encoding="utf-8").strip(), "--source profile")

    def test_boot_hook_execs_the_entrypoint_with_source_boot(self):
        text = BOOT_HOOK.read_text(encoding="utf-8")
        self.assertIn('exec "$ENTRY" --source boot', text)
        self.assertIn("export SVDIR=", text)
        proc = subprocess.run([SH, "-n", str(BOOT_HOOK)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_both_hooks_fall_back_to_the_old_behaviour_when_the_entrypoint_is_missing(self):
        for hook in (PROFILE_HOOK, BOOT_HOOK):
            text = hook.read_text(encoding="utf-8")
            self.assertIn("service-daemon start", text, hook.name)


if __name__ == "__main__":
    unittest.main()
