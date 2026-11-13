"""deploy/termux/staging_rehearsal.sh + staging_probe.py — the G6/G8-A staging rehearsal (2026-11-13).

The rehearsal runs a real runit cutover, restore and interrupted switch on a second service, so the
one property that must never fail is isolation: nothing it starts, stops or writes may be the
production service, its state, config, token, release pointer or port. These tests pin the refusals
that run before anything is created or started.
"""
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[2] / "deploy" / "termux"
SCRIPT = DEPLOY / "staging_rehearsal.sh"
PROBE = DEPLOY / "staging_probe.py"
POSIX_SH = shutil.which("dash") or shutil.which("sh")
COMMIT = "21c42a8f6c41d3d04401a8ca3ed81b2115de66b0"


def load_probe():
    spec = importlib.util.spec_from_file_location("hg_staging_probe_under_test", PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeTermux:
    """A HOME/PREFIX laid out like the owner's phone: production run script, config and manifest."""

    def __init__(self, root):
        self.home = root / "home"
        self.prefix = root / "usr"
        rid = "a" * 64
        conf_dir = self.home / ".config" / "hg"
        (conf_dir / "releases").mkdir(parents=True)
        (self.home / "hg-releases" / rid).mkdir(parents=True)
        (self.home / ".local" / "share" / "hg" / "runtime-service-state").mkdir(parents=True)
        self.conf = conf_dir / f"runtime-service-{rid}.json"
        manifest = conf_dir / "releases" / f"{rid}.json"
        manifest.write_text(json.dumps({"commit": "4eaac81132ae57028cf2432eec911a01b6ecf1fd", "release_id": rid}))
        self.conf.write_text(json.dumps({
            "schema": "hg-runtime-service-config-v1", "host": "127.0.0.1", "port": 18766, "max_body_bytes": 262144,
            "state_dir": str(self.home / ".local/share/hg/runtime-service-state"),
            "token_file": str(conf_dir / "runtime-service.token"),
            "release_root": str(self.home / "hg-releases" / rid), "release_manifest": str(manifest),
            "release_id": rid}))
        sv = self.prefix / "var" / "service" / "hg-runtime"
        sv.mkdir(parents=True)
        (sv / "run").write_text(f'#!/bin/sh\ncd "{self.home}/hg-releases/{rid}"\n'
                                f'exec python3 -B -u -m hg serve --config "{self.conf}"\n')

    def run(self, *args):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.home), "PREFIX": str(self.prefix)}
        return subprocess.run([POSIX_SH, str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=60)


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hg-staging-probe-"))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.fake = FakeTermux(self.tmp)
        self.probe = load_probe()

    def test_guard_accepts_a_separate_staging_dir_and_port(self):
        self.probe.guard(str(self.fake.conf), str(self.fake.home / "hg-staging-x"), 18867)

    def test_guard_refuses_the_production_port(self):
        with self.assertRaisesRegex(self.probe.Refused, "production port"):
            self.probe.guard(str(self.fake.conf), str(self.fake.home / "hg-staging-x"), 18766)

    def test_guard_refuses_a_staging_dir_that_overlaps_production(self):
        for stg in (self.fake.home, self.fake.home / ".local" / "share" / "hg",
                    self.fake.home / ".local/share/hg/runtime-service-state" / "x",
                    self.fake.home / ".config" / "hg" / "stg", self.fake.home / "hg-releases" / "stg"):
            with self.subTest(stg=stg), self.assertRaises(self.probe.Refused):
                self.probe.guard(str(self.fake.conf), str(stg), 18867)

    def test_staging_conf_refuses_paths_outside_the_staging_dir_and_needs_the_dir(self):
        stg = self.tmp / "stg"
        stg.mkdir()
        with unittest.mock.patch.dict(os.environ, {"HG_STAGING_DIR": str(stg)}):
            with self.assertRaisesRegex(self.probe.Refused, "outside the staging directory"):
                self.probe.staging_conf(str(self.fake.conf))           # the production config itself
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(self.probe.Refused, "HG_STAGING_DIR"):
                self.probe.staging_conf(str(self.fake.conf))

    def test_mkconf_writes_a_private_staging_config_once(self):
        stg = self.tmp / "stg"
        conf = stg / "c.json"
        stg.mkdir()
        self.probe.mkconf(str(conf), "b" * 64, str(stg / "home"), 18867, str(stg / "t"))
        self.assertEqual(stat.S_IMODE(conf.stat().st_mode), 0o600)
        self.probe.mkconf(str(conf), "b" * 64, str(stg / "home"), 18867, str(stg / "t"))   # same content: fine
        with self.assertRaisesRegex(self.probe.Refused, "other content"):
            self.probe.mkconf(str(conf), "b" * 64, str(stg / "home"), 18868, str(stg / "t"))
        with unittest.mock.patch.dict(os.environ, {"HG_STAGING_DIR": str(stg)}):
            self.assertEqual(self.probe.staging_conf(str(conf))["port"], 18867)

    def test_j2_check_requires_the_observed_hash_to_equal_the_file_on_disk(self):
        state = self.tmp / "state"
        (state / "root" / "out").mkdir(parents=True)
        body = b"HG v1 deploy smoke J2"
        (state / "root" / "out" / "f.txt").write_bytes(body)
        digest = __import__("hashlib").sha256(body).hexdigest()

        def ledger(observed, status="SUCCEEDED"):
            events = [{"kind": "ACTION_STARTED", "payload": {"action_id": "T-1:S-1:3", "tool": "fs.write"}},
                      {"kind": "ACTION_COMPLETED", "payload": {"action_id": "T-1:S-1:3", "status": status,
                                                               "observed": {"sha256": observed}}},
                      {"kind": "ACTION_COMPLETED", "payload": {"action_id": "T-10:S-1:1", "status": "SUCCEEDED",
                                                               "observed": {"sha256": "0" * 64}}}]
            (state / "actions.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))

        ledger(digest)
        record = self.probe.j2_check(state, "T-1", "out/f.txt")
        self.assertTrue(record["observed_matches_file"], record)
        self.assertEqual([a["action_id"] for a in record["actions"]], ["T-1:S-1:3"])     # T-10 is another task
        ledger("f" * 64)
        self.assertFalse(self.probe.j2_check(state, "T-1", "out/f.txt")["observed_matches_file"])
        ledger(digest, status="UNKNOWN")
        self.assertFalse(self.probe.j2_check(state, "T-1", "out/f.txt")["observed_matches_file"])
        with self.assertRaises(self.probe.Refused):
            self.probe.j2_check(state, "T-1", "../../etc/passwd")

    def test_cli_refusal_is_exit_2_and_names_the_reason(self):
        proc = subprocess.run(["python3", "-I", "-B", str(PROBE), "guard", str(self.fake.conf),
                               str(self.fake.home / "x"), "18766"], capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("STAGING_REFUSED: port 18766 is the production port", proc.stderr)


@unittest.skipIf(POSIX_SH is None, "no POSIX sh")
class RehearsalRefusalTests(unittest.TestCase):
    """Each refusal exits 2 before the staging dir is created and before any service is touched."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hg-staging-rehearsal-"))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.fake = FakeTermux(self.tmp)

    def assertRefused(self, proc, reason):
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("STAGING_REFUSED", proc.stderr)
        self.assertIn(reason, proc.stderr)

    def test_refuses_bad_arguments(self):
        home = self.fake.home
        cases = [
            ((), "usage"),
            (("stg", COMMIT), "absolute path"),
            ((str(home), COMMIT), "inside $HOME"),
            ((str(self.tmp / "elsewhere"), COMMIT), "inside $HOME"),
            ((f"{home}/a/../b", COMMIT), "plain path"),
            ((f"{home}/a b", COMMIT), "plain path"),
            ((f"{home}/stg", "21c42a8"), "40-hex"),
            ((f"{home}/stg", COMMIT, "x1"), "port must be a number"),
        ]
        for args, reason in cases:
            with self.subTest(args=args):
                self.assertRefused(self.fake.run(*args), reason)
        self.assertFalse((home / "stg").exists())

    def test_refuses_the_production_port_and_live_directories(self):
        home = self.fake.home
        self.assertRefused(self.fake.run(f"{home}/stg", COMMIT, "18766"), "production port")
        self.assertRefused(self.fake.run(f"{home}/.config/hg/stg", COMMIT), "live HG directory")
        self.assertRefused(self.fake.run(f"{home}/.local/share/hg/runtime-service-state/stg", COMMIT), "overlaps")
        self.assertFalse((home / "stg").exists())

    def test_refuses_an_existing_dir_that_is_not_a_staging_dir(self):
        (self.fake.home / "notes").mkdir()
        self.assertRefused(self.fake.run(f"{self.fake.home}/notes", COMMIT), "no .hg-staging marker")

    def test_refuses_without_a_production_run_script(self):
        (self.fake.prefix / "var" / "service" / "hg-runtime" / "run").unlink()
        self.assertRefused(self.fake.run(f"{self.fake.home}/stg", COMMIT), "no production run script")

    def test_isolation_is_exported_before_the_first_staging_write(self):
        text = SCRIPT.read_text(encoding="utf-8")
        body = text[text.index("# ---------------------------------------------------------------- from here on"):]
        export = body.index('export HOME="$STG/home" PREFIX="$STG/prefix" SVDIR="$STG/prefix/var/service"')
        for later in ('sh "$HERE/build_release.sh"', 'nohup runsvdir', 'RSVPID=$!', 'sh "$SCR/switch_service.sh"'):
            self.assertLess(export, body.index(later), later)
        start = body.index("nohup runsvdir")
        for before in ('mkdir -m 700 "$STATE"', 'export PATH="$PREFIX/bin:$PATH"', "termux-notification termux-wake-lock",
                       'rm -f "$HOME/.local/state/hg/hg-runtime-finish.count"'):
            self.assertLess(body.index(before), start, before)
        # teardown is defined earlier but stops a service only once RSVPID was set after the export
        teardown = body[body.index("teardown() {"):body.index("finish() {")]
        self.assertTrue(teardown.splitlines()[1].strip().startswith('if [ -n "$RSVPID" ]'))
        for line in body.splitlines():                  # production is only ever read
            if "PRODSV" in line and "sv " in line:
                self.assertIn("sv status", line)


if __name__ == "__main__":
    unittest.main()
