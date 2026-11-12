"""False-accept oracle for operator reads of a runtime work directory (WS-04).

``hg health``, ``hg status`` and ``hg learn`` report on a runtime from its ledgers. The
expected outcome comes from how each case is built, not from the code under test:

* a path that is not a directory (missing, a regular file, a dangling symlink) holds no
  runtime, so no read may describe it as a healthy runtime with zero tasks;
* a ledger path that is a dangling symlink or a symlink loop is not a ledger the runtime
  could have written (the writer opens with ``O_NOFOLLOW``), so it may never be read as an
  absent, empty ledger.

Controls show that a fresh work directory (a runtime built, no task yet), a real runtime
work directory and a symlink to that directory still read exactly as before, so a reader
that refuses everything cannot satisfy the oracle.
"""
import contextlib
import io
import json
import os
import shutil
import unittest
from pathlib import Path

from maep import ledger
from maep.core import MAEPError
from hg.__main__ import main as hg_main
from hg.ops import health
from hg.tests.test_learning_ops import FailingRuntime
from hg.verification.learning import analyze

LEDGERS = ("tasks.jsonl", "actions.jsonl")


def _cli(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        try:
            code = hg_main(list(argv))
        except Exception as exc:  # an unhandled error is a refusal too, but record it
            return ("raised", type(exc).__name__), out.getvalue()
    return code, out.getvalue()


class OperatorReadWorkdirOracle(FailingRuntime):
    def setUp(self):
        super().setUp()
        self.make_failures()
        self.base = Path(self.tmp)
        self.baseline_health = health(self.workdir)
        self.baseline_status = _cli("status", "--workdir", str(self.workdir))
        self.baseline_learn = analyze(self.workdir)

    # -- helpers ------------------------------------------------------------------------
    def copy_runtime(self, name):
        target = self.base / name
        shutil.copytree(self.workdir, target, symlinks=True)
        return target

    def bad_workdirs(self):
        cases = {"missing": self.base / "no-such-runtime"}
        regular = self.base / "regular-file"
        regular.write_text("not a runtime\n", encoding="utf-8")
        cases["regular file"] = regular
        dangling = self.base / "dangling-workdir"
        os.symlink(self.base / "gone", dangling)
        cases["dangling symlink"] = dangling
        cases["under a regular file"] = regular / "rt"
        return cases

    def damaged_ledgers(self):
        cases = {}
        for name in LEDGERS + ("memory.jsonl", "models.jsonl"):
            d = self.copy_runtime(f"dangling-{name}")
            p = d / name
            if os.path.lexists(p):
                os.unlink(p)
            os.symlink(d / "gone.jsonl", p)
            cases[f"{name} dangling symlink"] = (d, name)
            d = self.copy_runtime(f"loop-{name}")
            p = d / name
            if os.path.lexists(p):
                os.unlink(p)
            os.symlink(name, p)
            cases[f"{name} symlink loop"] = (d, name)
        return cases

    def assert_refused(self, workdir, label, *, commands=("health", "status", "learn")):
        if "health" in commands:
            report = health(workdir)
            self.assertEqual(report["status"], "FAILING", f"{label}: health {report}")
            code, _ = _cli("health", "--workdir", str(workdir))
            self.assertEqual(code, 2, f"{label}: hg health exit")
        if "status" in commands:
            code, out = _cli("status", "--workdir", str(workdir))
            self.assertNotEqual(code, 0, f"{label}: hg status exit 0 with {out!r}")
            self.assertNotIn('"tasks": []', out, label)
        if "learn" in commands:
            code, out = _cli("learn", "--workdir", str(workdir))
            self.assertNotEqual(code, 0, f"{label}: hg learn exit 0 with {out!r}")

    # -- cases --------------------------------------------------------------------------
    def test_a_path_that_is_not_a_work_directory_is_never_a_healthy_runtime(self):
        for label, workdir in self.bad_workdirs().items():
            with self.subTest(label):
                self.assert_refused(workdir, label)

    def test_a_task_or_action_ledger_symlink_is_never_read_as_an_empty_ledger(self):
        for label, (workdir, name) in self.damaged_ledgers().items():
            if name not in LEDGERS:
                continue
            with self.subTest(label):
                self.assert_refused(workdir, label)

    def test_a_memory_or_model_ledger_symlink_fails_health(self):
        for label, (workdir, name) in self.damaged_ledgers().items():
            if name in LEDGERS:
                continue
            with self.subTest(label):
                self.assert_refused(workdir, label, commands=("health",))

    def test_ledger_reader_refuses_symlinks_and_non_directory_parents(self):
        regular = self.base / "plain"
        regular.write_text("x\n", encoding="utf-8")
        dangling = self.base / "dangling.jsonl"
        os.symlink(self.base / "gone.jsonl", dangling)
        loop = self.base / "loop.jsonl"
        os.symlink("loop.jsonl", loop)
        for label, path in {"dangling": dangling, "loop": loop, "parent is a file": regular / "tasks.jsonl"}.items():
            with self.subTest(label):
                with self.assertRaises(MAEPError):
                    ledger.read_events(path)

    # -- controls -----------------------------------------------------------------------
    def test_control_missing_ledger_in_a_directory_is_absent(self):
        self.assertEqual(ledger.read_events(self.base / "fresh-ledger.jsonl"), [])

    def test_control_fresh_runtime_directory_reads_as_empty_and_healthy(self):
        fresh = self.base / "fresh"
        fresh.mkdir()
        (fresh / "root").mkdir()
        self.assertEqual(health(fresh)["status"], "OK")
        code, out = _cli("status", "--workdir", str(fresh))
        self.assertEqual((code, json.loads(out)["tasks"]), (0, []))
        code, out = _cli("learn", "--workdir", str(fresh))
        self.assertEqual((code, json.loads(out)["failures"]), (0, 0))
        self.assertEqual(_cli("health", "--workdir", str(fresh))[0], 0)

    def test_control_real_runtime_and_a_symlink_to_it_read_unchanged(self):
        self.assertIn(self.baseline_health["status"], {"OK", "DEGRADED"})
        self.assertEqual(self.baseline_status[0], 0)
        self.assertTrue(json.loads(self.baseline_status[1])["tasks"])
        self.assertEqual(self.baseline_learn["failures"], 4)
        link = self.base / "rt-link"
        os.symlink(self.workdir, link)
        for workdir in (self.workdir, link):
            with self.subTest(str(workdir)):
                report = health(workdir)
                self.assertEqual({k: v for k, v in report.items() if k != "workdir"},
                                 {k: v for k, v in self.baseline_health.items() if k != "workdir"})
                code, out = _cli("status", "--workdir", str(workdir))
                self.assertEqual((code, json.loads(out)["tasks"]),
                                 (0, json.loads(self.baseline_status[1])["tasks"]))
                self.assertEqual(analyze(workdir), self.baseline_learn)


if __name__ == "__main__":
    unittest.main()
