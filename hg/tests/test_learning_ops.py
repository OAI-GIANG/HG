"""C-18 learning loop, C-19 regression cases + benchmark, C-21 health -- on real runtime ledgers."""
import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

from maep.core import MAEPError
from hg.brain.providers import ModelRouter
from hg.memory.store import MemoryStore
from hg.ops import health
from hg.tests.fakes import ScriptedProvider
from hg.tests.support import TempDirMixin, content_verifier, grant, make_task, write_step
from hg.tools.gateway import LocalFileWriteAdapter
from hg.verification.benchmark import run_benchmark, verdict
from hg.verification.learning import analyze, normalise, record_lessons
from hg.verification.regressions import load_cases, run_case

REPO = Path(__file__).resolve().parents[2]


class FailingRuntime(TempDirMixin):
    def make_failures(self):
        """Two denied tasks (no grant) and two failed checks, in one runtime."""
        rt = self.build([grant("AUTH-W1", task_id="T-3"), grant("AUTH-W1b", task_id="T-4")],
                        verifiers={"AC-1": content_verifier(self.root, expected="never")})
        for tid in ("T-1", "T-2"):
            rt.orch.execute_task(make_task(tid), [write_step(authorization_id=f"AUTH-{tid}")])
        rt.orch.execute_task(make_task("T-3"), [write_step(authorization_id="AUTH-W1")])
        rt.orch.execute_task(make_task("T-4"), [write_step(authorization_id="AUTH-W1b")])
        return rt


class LearningTests(FailingRuntime):
    def test_recurring_failures_become_lessons_with_guard_cases(self):
        self.make_failures()
        report = analyze(self.workdir, threshold=2)
        classes = {l["class"]: l for l in report["lessons"]}
        self.assertEqual(classes["AUTHORIZATION_DENIED"]["count"], 2)
        self.assertEqual(classes["VERIFICATION_FAILED"]["count"], 2)
        case = classes["AUTHORIZATION_DENIED"]["regression_case"]
        self.assertEqual((case["grants"], case["expect"]), ("none", {"no_effect": True}))
        replay = run_case(case, Path(self.tmp) / "replay")                  # the guard holds today
        self.assertTrue(replay["passed"], replay["mismatches"])
        self.assertTrue(classes["VERIFICATION_FAILED"]["regression_case"]["expect"]["not_closed"])

    def test_single_failure_is_not_a_lesson(self):
        self.make_failures()
        self.assertEqual(analyze(self.workdir, threshold=3)["lessons"], [])

    def test_lessons_stored_as_hypotheses_once(self):
        self.make_failures()
        memory = MemoryStore(Path(self.tmp) / "memory.jsonl", clock=self.clock)
        report = analyze(self.workdir)
        first = record_lessons(report, memory)
        self.assertTrue(first and all(m["kind"] == "HYPOTHESIS" and m["layer"] == "PROJECT" and m["evidence_refs"]
                                      for m in first))
        self.assertEqual(record_lessons(report, memory), [])               # unchanged lessons are not duplicated
        bumped = copy.deepcopy(report)
        bumped["lessons"][0]["count"] += 1
        again = record_lessons(bumped, memory)
        self.assertEqual(len(again), 1)
        self.assertEqual(again[0]["version"], 2)

    def test_normalise_removes_volatile_parts(self):
        self.assertEqual(normalise("Grant AUTH-12 expired at 2026-10-23 id 9fa662bc5487"),
                         "grant auth-# expired at #-#-# id <id>")

    def test_loop_does_not_touch_code_or_policy(self):
        self.make_failures()
        before = {p: p.stat().st_mtime_ns for p in (REPO / "maep").rglob("*.py")}
        analyze(self.workdir)
        self.assertEqual(before, {p: p.stat().st_mtime_ns for p in (REPO / "maep").rglob("*.py")})


class RegressionCaseTests(TempDirMixin):
    def test_case_file_validation(self):
        path = Path(self.tmp) / "cases.json"
        base = load_cases()[0]
        for bad in ([base, base], [{k: v for k, v in base.items() if k != "expect"}], [dict(base, mode="magic")]):
            path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(MAEPError):
                load_cases(path)

    def test_mismatch_is_reported(self):
        case = dict(load_cases()[0], grants="none")                       # expects CLOSED but has no grant
        result = run_case(case, Path(self.tmp) / "c")
        self.assertFalse(result["passed"])
        self.assertIn("state PLANNED != CLOSED_VERIFIED", result["mismatches"])


class BenchmarkTests(TempDirMixin):
    @classmethod
    def setUpClass(cls):
        cls.report = run_benchmark()

    def test_suite_passes_with_zero_invariant_violations(self):
        metrics = self.report["metrics"]
        self.assertEqual((metrics["passed"], metrics["cases"]), (len(load_cases()), len(load_cases())))
        self.assertEqual((metrics["unauthorized_effects"], metrics["false_closures"]), (0, 0))
        self.assertEqual(self.report["recovery"]["recovered"], True)
        self.assertEqual(verdict(self.report), [])

    def test_verdict_flags_invariants_and_regressions(self):
        broken = copy.deepcopy(self.report)
        broken["metrics"]["false_closures"] = 1
        self.assertIn("false_closures = 1 (must be 0)", verdict(broken))
        worse = copy.deepcopy(self.report)
        worse["metrics"]["pass_rate"] = 0.9
        self.assertIn("regression: pass_rate 1.0 -> 0.9", verdict(worse, baseline=self.report))

    def test_failed_case_fails_the_verdict(self):
        bad_case = dict(load_cases()[3], case_id="R-X", expect={"state": "CLOSED_VERIFIED"})
        report = run_benchmark([bad_case], workdir=Path(self.tmp) / "b")
        self.assertTrue(any(p.startswith("case R-X failed") for p in verdict(report)))


class CrashOnce(LocalFileWriteAdapter):
    name = "crashonce.write"

    def _perform(self, params):
        super()._perform(params)
        raise RuntimeError("died")


class HealthTests(FailingRuntime):
    def test_ok_runtime(self):
        rt = self.build([grant()])
        rt.orch.execute_task(make_task(), [write_step()])
        report = health(self.workdir)
        self.assertEqual((report["status"], report["tasks"]), ("OK", {"CLOSED_VERIFIED": 1}))

    def test_pending_action_degrades(self):
        rt = self.build([grant()], extra_adapters=[CrashOnce(self.root)])
        rt.orch.execute_task(make_task(), [write_step(tool="crashonce.write")])
        report = health(self.workdir)
        self.assertEqual(report["status"], "DEGRADED")
        self.assertEqual(len(report["pending_actions"]), 1)

    def test_corrupt_ledger_fails(self):
        self.build([grant()]).orch.execute_task(make_task(), [write_step()])
        (self.workdir / "actions.jsonl").write_text("{not json\n", encoding="utf-8")
        self.assertEqual(health(self.workdir)["status"], "FAILING")

    def test_offline_router_without_local_model_degrades(self):
        router = ModelRouter([ScriptedProvider("remote", offline=False)], offline=True)
        report = health(Path(self.tmp) / "empty", router=router)
        self.assertEqual(report["status"], "DEGRADED")
        self.assertIn("no provider available in offline mode", json.dumps(report))

    def test_trust_root_failure_degrades(self):
        def broken():
            raise RuntimeError("404")
        self.assertEqual(health(Path(self.tmp) / "empty", trust_loader=broken)["status"], "DEGRADED")


class CliTests(FailingRuntime):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "hg", *args], cwd=REPO, capture_output=True, text=True, timeout=300)

    def test_bench_learn_health_commands(self):
        out = Path(self.tmp) / "bench.json"
        proc = self.run_cli("bench", "--json", str(out))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["verdict"], ["PASS"])
        self.make_failures()
        cases = Path(self.tmp) / "cases.json"
        learn = self.run_cli("learn", "--workdir", str(self.workdir), "--cases-out", str(cases))
        self.assertEqual(learn.returncode, 0, learn.stderr)
        self.assertTrue(json.loads(cases.read_text(encoding="utf-8")))
        state = self.run_cli("health", "--workdir", str(self.workdir))
        self.assertEqual((state.returncode, json.loads(state.stdout)["status"]), (0, "OK"))


if __name__ == "__main__":
    unittest.main()
