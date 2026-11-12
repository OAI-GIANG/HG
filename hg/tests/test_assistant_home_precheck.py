"""Oracle: a release is published for the owner's `hg` command, or the service is switched to it,
only after that release's own readers have read a private copy of the owner's assistant home.

Since #174/#176/#178 the readers of notes.jsonl and config.json refuse histories and values
older releases accepted. `install_release.sh` published the `hg` pointer and `switch_service.sh`
switched chat to a candidate without ever asking the candidate to read the production home, so a
home the candidate refuses was found only afterwards: `hg note list` exit 78, chat 503. The
ledger (§43, §45) kept this as a manual pre-switch step.

Oracle (the candidate's readers themselves, run from the candidate's root):
`deploy/termux/assistant_precheck.py <release_root> [<home>]` exits 0 exactly when
`Notebook.active()`, `Notebook.trusted_ids()`, `config.load()` and `repair.inspect()` (every
*.jsonl, OK only) of that release accept a copy of the home; otherwise exit 1 naming the file.
The live home is never changed: same names, bytes and mtimes; nothing created (not even .lock).
Controls: genuine home, absent home, empty home.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from hg.assistant.config import save
from hg.assistant.notes import Notebook
from hg.verification.evidence import EventLog
from hg.tests.test_memory_replay_history_oracle import FORGED, _append_raw, _seed

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "deploy" / "termux"
SCRIPT = DEPLOY / "assistant_precheck.py"


def _snapshot(home):
    if not home.exists():
        return None
    return {p.name: (p.read_bytes() if p.is_file() and not p.is_symlink() else os.readlink(p) if p.is_symlink() else None,
                     p.lstat().st_mtime_ns, p.lstat().st_mode)
            for p in sorted(home.iterdir())} | {".": home.lstat().st_mode}


class AssistantHomePrecheck(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _run(self, *args, env=None):
        full = dict(os.environ, **(env or {}))
        full.pop("HG_MODEL", None)
        proc = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), *map(str, args)],
                              capture_output=True, text=True, timeout=120, env=full)
        self.assertNotIn("Traceback", proc.stderr)
        report = json.loads(proc.stdout) if proc.stdout.strip() else None
        return proc.returncode, report

    def _genuine(self, name):
        home = self.root / name
        book = Notebook(home)
        first, _ = book.add("Giờ học tiếng Anh là 19:00 thứ Ba.", subject="lich hoc")
        book.add("Mật khẩu wifi để trong ngăn kéo.", subject="wifi")
        book.trust(first["memory_id"])
        save(home, {"max_tokens": 512, "think": False})
        EventLog(home / "asks-2026-11.jsonl").append("ASK", None, {"question": "x", "labels": []})
        return home

    def _check(self, home, expect_rc, *, file=None):
        before = _snapshot(home)
        rc, report = self._run(REPO, home)
        self.assertEqual(rc, expect_rc, report)
        self.assertEqual(_snapshot(home), before, "the live home must not change")
        if file is not None:
            failed = [c for c in report["checks"] if not c["ok"]]
            self.assertTrue(any(c["file"] == file for c in failed), report)
            self.assertTrue(all(c["detail"] for c in failed), report)
            self.assertEqual(report["result"], "FAIL")
        return report

    # ---- controls ----
    def test_genuine_home_passes_and_is_left_unchanged(self):
        home = self._genuine("genuine")
        report = self._check(home, 0)
        self.assertEqual(report["result"], "OK")
        self.assertEqual(report["release"], str(REPO))
        by = {c["name"]: c for c in report["checks"]}
        self.assertEqual(by["notes"]["detail"], {"active": 2, "trusted": 1})
        self.assertTrue(by["config"]["ok"])
        self.assertEqual({c["file"] for c in report["checks"] if c["name"] == "ledger"},
                         {"notes.jsonl", "asks-2026-11.jsonl"})

    def test_absent_home_is_reported_and_not_created(self):
        home = self.root / "absent"
        rc, report = self._run(REPO, home)
        self.assertEqual((rc, report["result"]), (0, "ABSENT"))
        self.assertFalse(home.exists())

    def test_empty_home_passes_without_creating_a_lock(self):
        home = self.root / "empty"
        home.mkdir(mode=0o700)
        report = self._check(home, 0)
        self.assertEqual(report["result"], "OK")
        self.assertEqual(list(home.iterdir()), [])

    def test_home_from_hg_home_env(self):
        home = self._genuine("env")
        before = _snapshot(home)
        rc, report = self._run(REPO, env={"HG_HOME": str(home)})
        self.assertEqual((rc, report["result"], report["home"]), (0, "OK", str(home)))
        self.assertEqual(_snapshot(home), before)

    # ---- homes the release refuses ----
    def test_forged_notes_history_fails(self):
        for name in FORGED:
            with self.subTest(case=name):
                home = self.root / f"forged-{name}"
                Notebook(home)
                kept, gone = _seed(home / "notes.jsonl")
                os.chmod(home / "notes.jsonl", 0o600)
                kind, build = FORGED[name]
                _append_raw(home / "notes.jsonl", kind, build(kept, gone))
                self._check(home, 1, file="notes.jsonl")

    def test_torn_notes_tail_fails_and_names_hg_repair(self):
        home = self._genuine("torn")
        with (home / "notes.jsonl").open("ab") as stream:
            stream.write(b'{"event_id": "torn", "seq": 99, "ki')
        report = self._check(home, 1, file="notes.jsonl")
        self.assertIn("hg repair", json.dumps(report, ensure_ascii=False))

    def test_unusable_config_value_fails_naming_the_key(self):
        for key, value in (("max_tokens", "512"), ("think", "no"), ("model_digest", ""), ("timeout_s", -1)):
            with self.subTest(key=key):
                home = self._genuine(f"cfg-{key}")
                (home / "config.json").write_text(json.dumps({key: value}), encoding="utf-8")
                report = self._check(home, 1, file="config.json")
                self.assertIn(key, json.dumps(report))

    def test_unknown_config_key_and_bad_json_fail(self):
        for name, text in (("unknown", '{"modle": "x"}'), ("json", "{"), ("dup", '{"think": true, "think": false}')):
            with self.subTest(case=name):
                home = self._genuine(f"cfgx-{name}")
                (home / "config.json").write_text(text, encoding="utf-8")
                self._check(home, 1, file="config.json")

    def test_damaged_receipt_ledger_fails(self):
        home = self._genuine("receipt")
        with (home / "asks-2026-11.jsonl").open("ab") as stream:
            stream.write(b"not json\n")
        self._check(home, 1, file="asks-2026-11.jsonl")

    def test_symlinked_ledger_is_refused_and_not_followed(self):
        home = self._genuine("link")
        target = self.root / "elsewhere.jsonl"
        (home / "notes.jsonl").rename(target)
        os.symlink(target, home / "notes.jsonl")
        self._check(home, 1, file="notes.jsonl")

    def test_unsafe_home_permissions_fail(self):
        home = self._genuine("perm")
        os.chmod(home, 0o750)
        self._check(home, 1, file=".")

    # ---- usage ----
    def test_bad_usage_exits_2(self):
        home = self._genuine("usage")
        for args in ((), ("relative/root", home), (REPO, "relative/home"), (REPO, home, "extra"),
                     (self.root / "no-release", home)):
            with self.subTest(args=args):
                rc, report = self._run(*args)
                self.assertEqual(rc, 2, report)
                self.assertEqual(report["result"], "FAIL")

    # ---- where it runs ----
    def test_install_runs_it_after_verification_and_before_the_pointer(self):
        text = (DEPLOY / "install_release.sh").read_text(encoding="utf-8")
        seal = text.index("seal_root(")
        verify_again = text.index("verify_root(", seal)
        check = text.index('assistant_precheck.py" "$ROOT"')
        pointer = text.index('"$POINTER.tmp"')
        self.assertLess(verify_again, check)
        self.assertLess(check, pointer)

    def test_switch_runs_it_before_stopping_the_service(self):
        full = (DEPLOY / "switch_service.sh").read_text(encoding="utf-8")
        text = full[full.index("# ---------------------------------------------------------------- switch forward"):]
        self.assertLess(text.index('release_ok "$NEWCONF" "$NEW"'), text.index('assistant_ok "$ROOT"'))
        self.assertLess(text.index('assistant_ok "$ROOT"'), text.index("stop_service"))
        self.assertIn('"$ASSISTANT_PRECHECK"', text[:text.index("# 1. recovery point")])   # kept as evidence
        body = full[full.index("assistant_ok() {"):]
        body = body[:body.index("\n}\n")]
        self.assertIn("7<&- 8<&- 9<&-", body)          # release code never inherits the lock descriptors


if __name__ == "__main__":
    unittest.main()
