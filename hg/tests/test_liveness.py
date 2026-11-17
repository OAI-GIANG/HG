"""RF-1 restart forensics: how the previous run ended, stalls, bounds, and the hg serve wiring.

Soak 3 (2026-11-15..17) lost 23.8 h and 31.5 h of production with no HG record; these tests pin that
every start now records how the previous run ended, with evidence that matches what is knowable.
"""
import contextlib
import io
import json
import os
import signal
import socket
import stat
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from hg import liveness as lv
from hg.liveness import Liveness, classify, read_heartbeat, summarize


class FakeClock:
    def __init__(self, wall=1_000_000.0, boottime=500.0, monotonic=400.0):
        self.now = {"wall": wall, "boottime": boottime, "monotonic": monotonic}

    def __call__(self):
        return dict(self.now)

    def advance(self, awake, suspended=0.0, frozen=0.0):
        """awake: process ran; suspended: CPU asleep; frozen: device awake, process not scheduled."""
        total = awake + suspended + frozen
        self.now["wall"] += total
        self.now["boottime"] += total
        self.now["monotonic"] += awake + frozen


class LivenessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hg-liveness-")
        self.state = Path(self.temp.name)
        self.clock = FakeClock()
        self.stderr = io.StringIO()

    def tearDown(self):
        self.temp.cleanup()

    def live(self, boot="boot-a", interval=60.0, release="r" * 64):
        return Liveness(self.state, release_id=release, interval=interval, clock=self.clock,
                        boot_id_reader=lambda: boot, stderr=self.stderr)

    def records(self):
        path = self.state / lv.RECORDS_FILE
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]

    def test_first_start_is_unknown_and_files_are_private(self):
        rec = self.live().start()
        self.assertEqual(rec["previous"], {"class": "FIRST_START", "evidence": "UNKNOWN"})
        self.assertEqual(rec["since_boot_s"], 500.0)
        hb, problem = read_heartbeat(self.state)
        self.assertIsNone(problem)
        self.assertEqual((hb["boot_id"], hb["stopped"], hb["beats"]), ("boot-a", None, 0))
        for name in (lv.HEARTBEAT_FILE, lv.RECORDS_FILE):
            self.assertEqual(stat.S_IMODE(os.stat(self.state / name).st_mode), 0o600)
        self.assertEqual(len(self.records()), 1)

    def test_clean_stop_is_confirmed_with_measured_downtime(self):
        a = self.live()
        a.start()
        self.clock.advance(120)
        a.beat()
        self.assertTrue(a.stop("signal"))
        self.assertFalse(a.stop("signal"))
        self.clock.advance(30)
        p = self.live().start()["previous"]
        self.assertEqual((p["class"], p["evidence"], p["stopped_reason"]), ("CLEAN_STOP", "CONFIRMED", "signal"))
        self.assertEqual(p["downtime_s"], 30.0)
        self.assertNotIn("downtime_max_s", p)

    def test_error_exit_is_confirmed_and_not_clean(self):
        a = self.live()
        a.start()
        a.stop("error")
        p = self.live().start()["previous"]
        self.assertEqual((p["class"], p["evidence"]), ("ERROR_EXIT", "CONFIRMED"))

    def test_unclean_end_same_boot_is_only_suspected_and_bounds_downtime(self):
        a = self.live()
        a.start()
        self.clock.advance(60)
        a.beat()                                    # last beat, then Android kills the tree
        self.clock.advance(awake=1800, suspended=3600)
        p = self.live().start()["previous"]
        self.assertEqual((p["class"], p["evidence"]), ("UNCLEAN_END_SAME_BOOT", "SUSPECTED"))
        self.assertEqual(p["downtime_max_s"], 5400.0)
        self.assertEqual(p["downtime_min_s"], 5340.0)
        self.assertEqual(p["suspended_s"], 3600.0)    # from the kernel clocks, not a guess
        self.assertEqual(p["uptime_s"], 60.0)
        self.assertNotIn("downtime_s", p)

    def test_changed_boot_id_is_a_confirmed_reboot(self):
        a = self.live(boot="boot-a")
        a.start()
        self.clock.advance(60)
        a.beat()
        self.clock.now["wall"] += 31.5 * 3600
        self.clock.now["boottime"] = 113_000.0
        self.clock.now["monotonic"] = 62_000.0
        rec = self.live(boot="boot-b").start()
        p = rec["previous"]
        self.assertEqual((p["class"], p["evidence"]), ("DEVICE_REBOOT", "CONFIRMED"))
        self.assertEqual(p["downtime_max_s"], 113400.0)
        self.assertNotIn("suspended_s", p)            # clocks of two boots are not comparable
        self.assertEqual(rec["since_boot_s"], 113000.0)  # HG came back 31 h after the boot

    def test_unknown_boot_id_stays_unknown(self):
        self.live(boot=None).start()
        self.clock.advance(100)
        p = self.live(boot=None).start()["previous"]
        self.assertEqual((p["class"], p["evidence"]), ("UNCLEAN_END_UNKNOWN_BOOT", "UNKNOWN"))

    def test_unreadable_heartbeat_is_unknown_and_start_continues(self):
        for bad in (b"{not json", json.dumps({"schema": "other"}).encode(), b"x" * (lv.MAX_HEARTBEAT_BYTES + 1)):
            (self.state / lv.HEARTBEAT_FILE).write_bytes(bad)
            p = self.live().start()["previous"]
            self.assertEqual((p["class"], p["evidence"]), ("PREVIOUS_UNREADABLE", "UNKNOWN"))
            self.assertIsNone(read_heartbeat(self.state)[1])

    def test_symlinked_heartbeat_is_not_followed(self):
        target = self.state / "elsewhere.json"
        target.write_text(json.dumps({"schema": lv.SCHEMA, "started": 1, "last_alive": 2}), encoding="utf-8")
        (self.state / lv.HEARTBEAT_FILE).symlink_to(target)
        self.assertEqual(read_heartbeat(self.state), (None, "unreadable"))
        self.live().start()
        self.assertFalse((self.state / lv.HEARTBEAT_FILE).is_symlink())
        self.assertEqual(json.loads(target.read_text())["last_alive"], 2)

    def test_clock_going_backwards_gives_no_downtime(self):
        a = self.live()
        a.start()
        self.clock.now["wall"] -= 500
        p = self.live().start()["previous"]
        self.assertTrue(p["clock_inconsistent"])
        self.assertIsNone(p["downtime_max_s"])

    def test_stall_splits_suspend_from_awake_freeze(self):
        a = self.live()
        a.start()
        self.clock.advance(awake=60)
        a.beat()                                      # on time: no stall
        self.clock.advance(awake=60, suspended=100)   # 160 s < 3 intervals: no stall
        a.beat()
        self.clock.advance(awake=60, suspended=1200, frozen=300)
        a.beat()                                      # stall >= 600 s: counted and recorded
        self.clock.advance(awake=60, frozen=150)
        a.beat()                                      # stall 210 s: counted, not recorded
        hb, _ = read_heartbeat(self.state)
        self.assertEqual(hb["stalls"], 2)
        self.assertEqual(hb["suspended_total_s"], 1200.0)
        self.assertEqual(hb["stalled_awake_total_s"], 450.0)
        stalls = [r for r in self.records() if r["event"] == "STALL"]
        self.assertEqual(len(stalls), 1)
        self.assertEqual((stalls[0]["elapsed_s"], stalls[0]["suspended_s"], stalls[0]["stalled_awake_s"]),
                         (1560.0, 1200.0, 300.0))

    def test_records_are_bounded_with_one_rotation(self):
        with patch.object(lv, "MAX_RECORDS_BYTES", 2048):
            for _ in range(40):
                a = self.live()
                a.start()
                a.stop("signal")
        size = os.path.getsize(self.state / lv.RECORDS_FILE)
        self.assertLessEqual(size, 2048)
        self.assertTrue((self.state / (lv.RECORDS_FILE + ".1")).exists())
        self.assertFalse((self.state / (lv.RECORDS_FILE + ".2")).exists())

    def test_write_failure_is_reported_once_and_never_raises(self):
        a = self.live()
        a.start()
        self.temp.cleanup()                           # state dir disappears under the service
        self.assertFalse(a.beat())
        self.assertFalse(a.beat())
        self.assertFalse(a.stop("signal"))
        self.assertEqual(self.stderr.getvalue().count("HG_LIVENESS_WRITE_FAILED heartbeat"), 1)
        self.assertNotIn(str(self.state), self.stderr.getvalue())

    def test_beats_after_stop_are_ignored(self):
        a = self.live()
        a.start()
        a.stop("signal")
        self.clock.advance(60)
        self.assertFalse(a.beat())
        self.assertEqual(read_heartbeat(self.state)[0]["stopped"]["reason"], "signal")

    def test_thread_beats_and_stop_joins_it(self):
        a = Liveness(self.state, release_id="r" * 64, interval=0.05, boot_id_reader=lambda: "b",
                     stderr=self.stderr)
        a.start()
        a.start_thread()
        deadline = time.monotonic() + 5
        while read_heartbeat(self.state)[0]["beats"] < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertGreaterEqual(read_heartbeat(self.state)[0]["beats"], 2)
        a.stop("signal")
        self.assertFalse(a._thread.is_alive())

    def test_summarize_counts_unobserved_gaps_but_not_deliberate_stops(self):
        a = self.live()
        a.start()
        self.clock.advance(60)
        a.beat()
        self.clock.advance(awake=0, suspended=0, frozen=7200)    # killed, 2 h gap
        b = self.live()
        b.start()
        b.stop("signal")
        self.clock.advance(300)                                    # deliberate 5 min stop
        c = self.live()
        c.start()
        self.clock.advance(60)
        c.beat()
        report = summarize(self.state, now=self.clock.now["wall"] + 30)
        self.assertEqual(report["starts"], 3)
        self.assertEqual(report["by_class"], {"FIRST_START": 1, "UNCLEAN_END_SAME_BOOT": 1, "CLEAN_STOP": 1})
        self.assertEqual(report["unobserved_s"], 7200.0)
        self.assertEqual(report["intentional_down_s"], 300.0)
        self.assertEqual(report["current"]["state"], "ALIVE")
        stale = summarize(self.state, now=self.clock.now["wall"] + 600)
        self.assertEqual(stale["current"]["state"], "STALE")
        self.assertEqual(summarize(self.state, since=self.clock.now["wall"] + 1)["starts"], 0)

    def test_availability_cli_is_read_only_and_exit_reflects_current_state(self):
        from hg.__main__ import main
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["availability", "--state-dir", str(self.state)]), 1)   # nothing yet
        self.assertEqual(json.loads(out.getvalue())["current"], {"heartbeat": "missing"})
        self.assertEqual(sorted(os.listdir(self.state)), [])
        a = Liveness(self.state, release_id="r" * 64, interval=60, boot_id_reader=lambda: "b", stderr=self.stderr)
        a.start()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["availability", "--state-dir", str(self.state)]), 0)
        a.stop("signal")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["availability", "--state-dir", str(self.state)]), 1)

    def test_classify_is_pure_on_missing_input(self):
        self.assertEqual(classify(None, "missing", FakeClock()(), "b")["class"], "FIRST_START")
        self.assertEqual(classify(None, "unreadable", FakeClock()(), "b")["class"], "PREVIOUS_UNREADABLE")


class ServeWiringTests(unittest.TestCase):
    """Through `hg serve` (hg.service.run): a start record, live beats, and a clean stop on SIGTERM."""

    def setUp(self):
        from hg.service import CONFIG_SCHEMA
        from hg.tests.release_helpers import make_tiny_release
        self.temp = tempfile.TemporaryDirectory(prefix="hg-liveness-serve-")
        root = Path(self.temp.name)
        release = make_tiny_release(root / "release")
        self.state = root / "state"
        self.state.mkdir(mode=0o700)
        token = root / "service.token"
        token.write_text("a-very-long-test-token-that-is-not-a-secret\n", encoding="ascii")
        token.chmod(0o600)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        self.config = root / "service.json"
        self.config.write_text(json.dumps({
            "schema": CONFIG_SCHEMA, "host": "127.0.0.1", "port": port,
            "state_dir": str(self.state), "token_file": str(token),
            "release_root": str(release["root"]), "release_manifest": str(release["manifest"]),
            "release_id": release["doc"]["release_id"], "max_body_bytes": 65536,
        }), encoding="utf-8")
        self.config.chmod(0o600)
        self.release_id = release["doc"]["release_id"]

    def tearDown(self):
        self.temp.cleanup()

    def serve_until_beats(self, beats):
        from maep.authority.canonical_source import CanonicalManifest
        from maep.tests.test_canonical_source import FakeGitHub
        from hg.service import run
        authority = CanonicalManifest.from_github(http_get=FakeGitHub().get, max_age_s=0)

        def stopper():
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                hb, _ = read_heartbeat(self.state)
                if hb is not None and hb["stopped"] is None and hb["beats"] >= beats:
                    break                               # this run's own beats, handlers installed
                time.sleep(0.02)
            os.kill(os.getpid(), signal.SIGTERM)

        out, err = io.StringIO(), io.StringIO()
        threading.Thread(target=stopper, daemon=True).start()
        with patch.object(CanonicalManifest, "from_github", return_value=authority), \
                patch.object(lv, "DEFAULT_INTERVAL_S", 0.05), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = run(self.config)
        return code, out.getvalue(), err.getvalue()

    def test_serve_records_start_beats_and_clean_stop(self):
        code, out, _ = self.serve_until_beats(2)
        self.assertEqual(code, 0)
        self.assertIn("HG_RESTART_FORENSICS previous=FIRST_START evidence=UNKNOWN", out)
        self.assertLess(out.index("HG_RESTART_FORENSICS"), out.index("HG_RUNTIME_READY"))
        hb, _ = read_heartbeat(self.state)
        self.assertEqual(hb["release_id"], self.release_id)
        self.assertEqual(hb["stopped"]["reason"], "signal")
        self.assertGreaterEqual(hb["beats"], 2)
        code, out, _ = self.serve_until_beats(1)
        self.assertEqual(code, 0)
        self.assertIn("HG_RESTART_FORENSICS previous=CLEAN_STOP evidence=CONFIRMED", out)
        self.assertNotIn("Bearer", out)
        self.assertNotIn("a-very-long-test-token", (self.state / lv.RECORDS_FILE).read_text())


if __name__ == "__main__":
    unittest.main()
