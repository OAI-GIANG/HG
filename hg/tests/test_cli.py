"""Runtime entry point: `python -m hg` runs the real path in a fresh process."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

from hg.tests.support import TempDirMixin

REPO = Path(__file__).resolve().parents[2]


def run(*args):
    return subprocess.run([sys.executable, "-m", "hg", *args], cwd=REPO, capture_output=True,
                          text=True, timeout=60)


class CliTests(TempDirMixin):
    def test_selfcheck_passes_in_a_fresh_process(self):
        proc = run("selfcheck", "--workdir", f"{self.tmp}/sc")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads(proc.stdout)
        self.assertEqual(report["result"], "PASS")
        self.assertEqual([s["observed_state"] for s in report["scenarios"]],
                         ["CLOSED_VERIFIED", "PLANNED", "BLOCKED"])
        self.assertFalse((Path(self.tmp) / "sc/ungranted/root/out/ungranted.txt").exists())

    def test_selfcheck_refuses_non_empty_workdir(self):
        busy = Path(self.tmp) / "busy"
        busy.mkdir()
        (busy / "keep.txt").write_text("user data", encoding="utf-8")
        proc = run("selfcheck", "--workdir", str(busy))
        self.assertEqual(proc.returncode, 2)
        self.assertEqual((busy / "keep.txt").read_text(encoding="utf-8"), "user data")

    def test_status_reads_ledgers_without_writing(self):
        run("selfcheck", "--workdir", f"{self.tmp}/sc")
        workdir = Path(self.tmp) / "sc" / "authorized"
        before = {p.name: p.read_bytes() for p in workdir.glob("*.jsonl")}
        proc = run("status", "--workdir", str(workdir))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([(t["task_id"], t["state"]) for t in json.loads(proc.stdout)["tasks"]],
                         [("SC-1", "CLOSED_VERIFIED")])
        self.assertEqual({p.name: p.read_bytes() for p in workdir.glob("*.jsonl")}, before)


if __name__ == "__main__":
    unittest.main()
